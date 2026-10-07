"""Explicit AML lifecycle orchestration; preparation is offline, execution is opt-in."""

from copy import deepcopy
from pathlib import Path
import time

from ml_model_factory.config import load_json, write_json
from ml_model_factory.lake import identifier
from ml_model_factory.tags import assert_scope

from .contracts import PipelineRequest, PipelineType
from .project import ESMLProject
from .naming import ESMLNaming


SCENARIO_NUMBERS = {
    "titanic": 1, "diabetes": 2, "churn": 3, "insurance-regression": 4,
    "air-passengers": 5, "delhi-weather": 6, "orangejuice": 7,
    "image-multiclass": 8, "image-multilabel": 9,
    "image-object-detection": 10, "image-instance-segmentation": 11,
}
ROLLOUT_CONFIG_SCHEMA = "esml.azureml-rollout-config/v1"
BLOCKED_DATASETS = ("required-selection", "license-review", "requires-license-review")


def model_from_scenario(scenario: dict, *, input_path: str, compute: str, naming_style="model-prefix") -> dict:
    name = scenario["name"]
    if name not in SCENARIO_NUMBERS:
        raise ValueError("Assign a reviewed model number before adding a scenario to this rollout")
    number = SCENARIO_NUMBERS[name]
    model = {
        "model_number": number, "model_short_alias": f"M{number:02d}", "model_folder_name": name,
        "model_name": f"M{number:02d}_{name.replace('-', '_')}", "use_case": name,
        "naming_style": naming_style, "compute": compute,
        "dataset_folder_names": [name], "datasets": {name: {
            "input_path": input_path, "format": "csv",
        }},
        "label": scenario.get("target", "label"), "ml_type": scenario["task"],
        "features": scenario.get("features", []), "source": deepcopy(scenario["dataset"]),
        "bronze": True, "bronze_mode": "raw", "table_format": "delta", "aml_table_format": "parquet",
        "merge": {"mode": "concat"},
    }
    for key in ("categorical_features", "sensitive_features", "split", "forecast", "vision", "automl", "custom", "quality"):
        if key in scenario:
            model[key] = deepcopy(scenario[key])
    return model


def settings_from_rollout_config(config: dict, scenarios: Path) -> tuple[dict, list[dict]]:
    """Compile reviewed model-factory scenario bindings into esml.lake-settings/v2, offline.

    `config` uses esml.azureml-rollout-config/v1: shared factory/storage/runtime settings
    plus one reviewed source binding per selected scenario. Dataset selection/license
    gates and the tabular-only ESML boundary are enforced; nothing is submitted.
    """
    if not isinstance(config, dict) or config.get("schema") != ROLLOUT_CONFIG_SCHEMA:
        raise ValueError(f"Expected {ROLLOUT_CONFIG_SCHEMA} configuration")
    chosen = config.get("scenarios")
    if not isinstance(chosen, dict) or not chosen or set(chosen) - set(SCENARIO_NUMBERS):
        raise ValueError("Choose explicit known scenarios with reviewed source bindings")
    models, catalog = [], []
    for name, number in SCENARIO_NUMBERS.items():
        scenario = load_json(Path(scenarios) / f"{name}.json")
        row = {"scenario": name, "model_number": number, "model_alias": f"M{number:02d}",
               "task": scenario["task"], "dataset_status": scenario["dataset"].get("status"),
               "selected": name in chosen}
        if name in chosen:
            source = chosen[name]
            if scenario["dataset"].get("status") in BLOCKED_DATASETS:
                raise ValueError(f"{name}: resolve the existing dataset selection/license gate first")
            if scenario["task"].startswith("image_"):
                raise ValueError(f"{name}: vision needs its ESML task-specific adapter; no tabular fallback")
            if source.get("mode") not in ("custom", "automl"):
                raise ValueError(f"{name}: binding mode must be custom or automl")
            model = model_from_scenario(scenario, input_path=source["input_path"], compute=source["compute"])
            if source["mode"] == "automl":
                if not config.get("automl_evaluation_environment"):
                    raise ValueError("AutoML bindings require a pinned automl_evaluation_environment")
                model["evaluation_environment"] = config["automl_evaluation_environment"]
                model["inference_environment"] = config["automl_evaluation_environment"]
                model["inference_mode"] = "automl"
            if "environment" in source:
                model["environment"] = source["environment"]
            if source.get("limits"):
                model.setdefault("automl", {})["limits"] = source["limits"]
            if "inference_history_path" in source:
                # AutoML forecast scoring needs an explicit lake path of observed history.
                model["inference_history_path"] = source["inference_history_path"]
            models.append(model)
            row.update(mode=source["mode"], compute=source["compute"], status="prepared_not_submitted")
        else:
            row["status"] = "not_selected"
        catalog.append(row)
    settings = {
        "schema": "esml.lake-settings/v2", "aifactory": config["aifactory"],
        "project_number": config["project_number"], "project_folder_name": f"project{config['project_number']:03d}",
        "active_model": models[0]["model_number"], "models": models,
        "runtime": deepcopy(config["runtime"]), "storage": deepcopy(config["storage"]),
    }
    for key in ("use_common_datalake_storage", "storage_targets"):
        if key in config:
            settings[key] = deepcopy(config[key])
    return settings, catalog


def project_from_rollout_config(config: dict, scenarios: Path, *, scenario: str, mode: str | None = None,
                                base_path: Path | None = None, **dependencies) -> ESMLProject:
    """Build an ESMLProject for one reviewed scenario binding, optionally overriding its mode."""
    bindings = config.get("scenarios", {}) if isinstance(config, dict) else {}
    if scenario not in bindings:
        raise ValueError(f"Add a reviewed source binding for {scenario!r} to the rollout configuration")
    binding = deepcopy(bindings[scenario])
    if mode is not None:
        if mode not in ("custom", "automl"):
            raise ValueError("mode must be custom or automl")
        binding["mode"] = mode
    settings, _ = settings_from_rollout_config({**config, "scenarios": {scenario: binding}}, scenarios)
    from .settings import LakeSettings
    return ESMLProject(LakeSettings.from_dict(settings, base_path=base_path), **dependencies)


class AzureMLRollout:
    """Train through the factory, then register only evaluated outputs and models."""

    def __init__(self, project: ESMLProject, output: Path):
        self.project = project
        self.output = Path(output).resolve()

    def prepare(self, *, model_number: int, mode: str, data_date_utc: str, run_id: str,
                data_version: str | None = None) -> dict:
        if mode not in ("automl", "custom"):
            raise ValueError("mode must be automl or custom")
        model = self.project.settings.model(model_number)
        kind = (PipelineType.IN_2_GOLD_TRAINING_AUTOML if mode == "automl"
                else PipelineType.IN_2_GOLD_TRAINING_MANUAL)
        directory = self.output / run_id
        plan = self.project.create_pipeline(kind, PipelineRequest(data_date_utc, run_id, data_version=data_version),
                                           output=directory / "training", model_number=model_number)
        request = {
            "schema": "esml.azureml-rollout/v1", "scope": self.project.settings.scope,
            "workspace": self.project.target.workspace_name, "model_number": model_number,
            "model_name": model.options.get("model_name", model.folder), "mode": mode,
            "run_id": run_id, "data_date_utc": data_date_utc,
            "pipeline": str(plan.yaml_path), "request_sha256": plan.document["tags"]["esml_request_sha256"],
            "experiment_name": plan.document["experiment_name"],
            "compute": plan.document["settings"]["default_compute"],
            "data_assets": [{"name": item["name"], "version": item["version"], "output": item["output"]}
                            for item in plan.manifest["data_assets"]],
            "cloud_submitted": False,
        }
        write_json(directory / "request.json", request)
        return request

    def register_definitions(self, run_id: str, *, component_version: str) -> dict:
        """Make source data and the pipeline component visible before training."""
        directory = self.output / identifier(run_id, "run_id")
        request = load_json(directory / "request.json")
        path = directory / "registered-definitions.json"
        if path.exists():
            raise ValueError("Definitions already have a registration receipt; use the recorded component version")
        plan = self._plan(directory / "training")
        self.project._verify_document(plan.document, plan.base_path)
        self.project._verify_selected_datastore()
        model = self.project.settings.model(request["model_number"])
        naming = ESMLNaming(self.project.settings, model)
        assets = []
        for dataset in model.datasets:
            uri = plan.manifest["paths"]["sources"][dataset.name]
            definition = {
                "name": naming.data("in", dataset=dataset.name),
                "version": plan.manifest["request"]["data_version"],
                "type": "uri_folder", "path": uri,
                "tags": {**self.project.settings.scope, "use_case": model.use_case,
                         "model_alias": model.alias, "medallion_stage": "in"},
            }
            assets.append(self.project._backend().register_data(definition))
        component = self.project.register_pipeline(plan, version=component_version)
        result = {"inputs": assets, "component": component}
        write_json(path, result)
        return result

    def _plan(self, directory: Path):
        import yaml
        from .pipeline import PipelinePlan
        path = directory / "pipeline.yml"
        return PipelinePlan(yaml.safe_load(path.read_text(encoding="utf-8")), directory,
                            load_json(directory / "manifest.json"), path)

    def execute_training(self, run_id: str, *, timeout_seconds=7200, poll_seconds=30,
                         selection_policy: dict | None = None, no_champion=False,
                         champion_evaluation: dict | None = None) -> dict:
        directory = self.output / identifier(run_id, "run_id")
        request = load_json(directory / "request.json")
        if (request["scope"] != self.project.settings.scope or request["workspace"] != self.project.target.workspace_name
                or request["run_id"] != run_id):
            raise ValueError("Rollout request differs from the selected project")
        plan = self._plan(directory / "training")
        if request["request_sha256"] != plan.document["tags"].get("esml_request_sha256"):
            raise ValueError("Rollout request and generated plan differ")
        completed_receipt = directory / "training-completion.json"
        if completed_receipt.exists():
            raise ValueError("Training already has a completion receipt; review it instead of registering duplicate versions")
        registration_intent = directory / "model-registration-intent.json"
        if registration_intent.exists():
            raise ValueError("A previous model registration may have completed; reconcile it before repeating a registry write")
        job = self.project.execute_pipeline(plan)
        write_json(directory / "submitted-job.json", job)
        job = self.project.wait_for_completion(job["name"], timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
        write_json(directory / "completed-job.json", job)
        assets = self.project.register_outputs(plan, job["name"])
        write_json(directory / "registered-data.json", {"job": job["name"], "assets": assets})
        write_json(registration_intent, {"job": job["name"], "model_name": request["model_name"],
                                         "status": "registration_requested"})
        model_id = self.project.register_model(
            job["name"], model_number=request["model_number"], selection_policy=selection_policy,
            no_champion=no_champion, champion_evaluation=champion_evaluation,
            decision_path=directory / "selection-decision.json",
        )
        result = {"schema": "esml.azureml-training-completion/v1", "job": job["name"], "status": job["status"],
                  "experiment_name": request["experiment_name"], "model_id": model_id, "assets": assets,
                  "deployment_created": False}
        write_json(completed_receipt, result)
        return result

    def prepare_inference(self, run_id: str, *, inference_date_utc: str, inference_run_id: str) -> dict:
        directory = self.output / identifier(run_id, "run_id")
        request = load_json(directory / "request.json")
        completion = load_json(directory / "training-completion.json")
        model_id = completion["model_id"]
        from ml_model_factory.serving import _model_name_version
        model_name, version = _model_name_version(model_id)
        if model_name != request["model_name"]:
            raise ValueError("Registered model differs from the rollout request")
        # Inference data must be separately supplied without labels at the declared lake path.
        inference_project = ESMLProject(
            self.project.settings, backend=self.project.backend,
            folder_catalog=self.project.folder_catalog, step_map=self.project.step_map,
        )
        inference_project.settings.model(request["model_number"]).options["inference_mode"] = request["mode"]
        plan = inference_project.create_pipeline(
            PipelineType.GOLD_INFERENCE, PipelineRequest(inference_date_utc, inference_run_id, model_version=version),
            output=directory / "inference", model_number=request["model_number"],
        )
        result = {"pipeline": str(plan.yaml_path), "model_id": model_id,
                  "input": plan.document["inputs"]["gold"]["path"],
                  "output": plan.document["outputs"]["inference"]["path"], "published": False}
        write_json(directory / "inference-request.json", result)
        return result

    def _refuse_other_inference_route(self, directory: Path, route: str) -> None:
        """Endpoint invocation and pipeline submission are alternatives for one reviewed plan, never both."""
        other = {"pipeline": ("inference-invocation-intent.json", "inference-job.json"),
                 "endpoint": ("inference-pipeline-intent.json", "inference-pipeline-job.json")}[route]
        existing = [name for name in other if (directory / name).exists()]
        if existing:
            raise ValueError(f"This inference plan already used the other route ({', '.join(existing)}); "
                             "reconcile that job instead of running inference twice")

    def submit_inference(self, run_id: str) -> dict:
        """Submit the reviewed inference plan as a pipeline job instead of publishing a batch endpoint.

        This is the alternative when pipeline-component batch invocation is unavailable. The job
        receipt is recorded once; an uncertain earlier submission must be reconciled, not repeated.
        """
        directory = self.output / identifier(run_id, "run_id")
        receipt = directory / "inference-pipeline-job.json"
        if receipt.exists():
            return load_json(receipt)
        self._refuse_other_inference_route(directory, "pipeline")
        intent = directory / "inference-pipeline-intent.json"
        if intent.exists():
            raise ValueError("An earlier inference submission has an uncertain outcome; reconcile its job before retrying")
        plan = self._plan(directory / "inference")
        write_json(intent, {"pipeline": str(plan.yaml_path), "status": "submission_requested"})
        job = self.project.execute_pipeline(plan)
        write_json(receipt, job)
        return job

    def deploy_and_invoke(self, run_id: str, *, component_version: str,
                          timeout_seconds=7200, poll_seconds=30) -> dict:
        directory = self.output / identifier(run_id, "run_id")
        if type(timeout_seconds) is not int or type(poll_seconds) is not int or timeout_seconds < 1 or poll_seconds < 1:
            raise ValueError("Bounded positive integer polling intervals are required")
        self._refuse_other_inference_route(directory, "endpoint")
        plan = self._plan(directory / "inference")
        published_path = directory / "published-inference.json"
        published = (load_json(published_path) if published_path.exists()
                     else self.project.publish_pipeline(plan, version=component_version))
        write_json(published_path, published)
        submitted_path = directory / "inference-job.json"
        invoke_intent = directory / "inference-invocation-intent.json"
        if submitted_path.exists():
            job = load_json(submitted_path)
        else:
            if invoke_intent.exists():
                raise ValueError("An earlier invocation has an uncertain outcome; reconcile its job before submitting again")
            write_json(invoke_intent, {"published": published, "status": "invocation_requested"})
            job = self.project.invoke_pipeline(plan, published)
        write_json(submitted_path, job)
        # Batch invocations do not inherit the submitted pipeline job's tags.
        # Pin the returned job and verify actual output bindings before reading data.
        backend = self.project._backend()
        deadline = time.monotonic() + timeout_seconds
        while True:
            finished = backend.get_job(job["name"])
            if finished.get("name") != job["name"]:
                raise ValueError("Batch endpoint returned a different job identity")
            if finished.get("tags", {}).get("aifactory"):
                assert_scope(finished["tags"], self.project.settings.scope)
            status = finished.get("status")
            if status in ("Completed", "Succeeded"):
                break
            if status not in {"NotStarted", "Starting", "Provisioning", "Preparing", "Queued", "Running", "Finalizing"}:
                raise RuntimeError(f"Inference ended in {status!r}; deployment is not verified")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Inference is still running; resume the recorded job, do not invoke again")
            time.sleep(min(remaining, poll_seconds))
        from azure_esml.base_layer.uris import same_data_path
        if not same_data_path(finished.get("outputs", {}).get("inference", {}).get("path"),
                              plan.document["outputs"]["inference"]["path"], self.project.target):
            raise ValueError("Inference output differs from its approved lake destination")
        destination = directory / "inference-result"
        if not destination.exists():
            backend.download_job(job["name"], destination, "inference")
        predictions = list(destination.rglob("predictions.parquet"))
        runinfo = list(destination.rglob("runinfo.json"))
        if len(predictions) != 1 or len(runinfo) != 1:
            raise ValueError("Inference job did not return one predictions file and one runinfo receipt")
        import pandas as pd
        rows = pd.read_parquet(predictions[0])
        if rows.empty or "prediction" not in rows or rows["prediction"].isna().any():
            raise ValueError("Inference produced no usable predictions")
        result = {"schema": "esml.azureml-deployment-completion/v1", "published": published,
                  "job": finished["name"], "status": finished["status"], "predictions": len(rows),
                  "result_path": str(predictions[0]), "runinfo": load_json(runinfo[0])}
        write_json(directory / "deployment-completion.json", result)
        return result
