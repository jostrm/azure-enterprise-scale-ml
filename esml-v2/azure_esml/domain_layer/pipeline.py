"""Offline, SDK/CLI-identical Azure ML v2 medallion pipeline planning."""

from copy import deepcopy
from dataclasses import dataclass
import base64
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
import shutil
from typing import TYPE_CHECKING

import yaml

from ml_model_factory.azureml import SCHEMAS, _automl
from ml_model_factory.lake import LakeLayout, identifier, relative_key
from ml_model_factory.tags import build_tags, validate_tags

from azure_esml.base_layer.contracts import IFolderCatalog
from .contracts import IPipelineStepMap, PipelineRequest, PipelineType, StepOverride, StepType
from .naming import ESMLNaming
from .settings import DatasetSettings, LakeSettings
from ml_model_factory.selection import canonical_hash

if TYPE_CHECKING:
    from .project import ESMLProject


def _key(value):
    value = re.sub(r"[^a-z0-9_]", "_", value.lower())
    return value if value[0].isalpha() else "ds_" + value


def _binding(area, name):
    return "${{parent." + area + "." + name + "}}"


def bundle_fingerprint(document: dict, base_path: Path) -> str:
    inventory = {}
    roots = {"builtin": (Path(base_path) / "code").resolve()}
    for name, node in document.get("jobs", {}).items():
        component = node.get("component")
        if isinstance(component, dict) and component.get("code"):
            code = str(component["code"])
            if not code.startswith("azureml:"):
                resolved = (Path(base_path) / code).resolve()
                if resolved not in roots.values():
                    roots[name] = resolved
    for name, root in roots.items():
        if not root.is_dir():
            raise ValueError(f"Component code directory is missing: {root}")
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("Component bundles must not contain symbolic links or junctions")
            if path.is_file():
                inventory[f"{name}/{relative.as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return canonical_hash(inventory)


@dataclass(frozen=True)
class PipelinePlan:
    document: dict
    base_path: Path
    manifest: dict
    yaml_path: Path

    def to_sdk(self):
        from azure.ai.ml import load_job
        return load_job(StringIO(yaml.safe_dump(self.document)), relative_origin=self.yaml_path)

    def as_component(self, name: str, version: str) -> dict:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", name):
            raise ValueError("Component name must be a valid Azure ML asset name")
        identifier(version, "component_version")
        if version.lower() in ("latest", "active"):
            raise ValueError("Component version must be pinned")
        result = {key: deepcopy(self.document[key]) for key in ("type", "inputs", "outputs", "jobs")}
        result.update({"$schema": SCHEMAS + "pipelineComponent.schema.json", "name": name, "version": version})
        result["inputs"] = {
            key: ({"type": value["type"]} if isinstance(value, dict)
                  else {"type": "string", "default": value})
            for key, value in result["inputs"].items()
        }
        result["outputs"] = {key: {"type": value["type"]} for key, value in result["outputs"].items()}
        return result

    def invocation(self) -> dict:
        return {key: deepcopy(self.document[key]) for key in ("inputs", "outputs")}


class ESMLPipelineFactory:
    """Step maps may implement create_component(step, input_names, output_names, context, *, dataset)."""

    def __init__(self, project_or_settings: "ESMLProject | LakeSettings", *, step_map: IPipelineStepMap | None = None,
                 folder_catalog: IFolderCatalog | None = None):
        if not isinstance(project_or_settings, LakeSettings):
            from .project import ESMLProject
            if not isinstance(project_or_settings, ESMLProject):
                raise TypeError("ESMLPipelineFactory requires ESMLProject or validated LakeSettings")
            project = project_or_settings
            project_or_settings = project.settings
            if step_map is None:
                step_map = project.step_map
            if folder_catalog is None:
                folder_catalog = project.folder_catalog
        self.settings = project_or_settings
        self.step_map = step_map
        self.folder_catalog = folder_catalog

    def _datasets(self, model):
        datasets = {value.name: value for value in model.datasets}
        discovery = {"enabled": bool(model.options.get("discover_datasets")), "names": []}
        if discovery["enabled"]:
            if self.folder_catalog is None:
                raise ValueError("discover_datasets requires an explicit folder_catalog")
            prefix = model.options.get("discovery_prefix", (
                f"{self.settings.storage.get('prefix', 'mlops/v1')}/projects/{self.settings.project_folder}"
                f"/environments/{self.settings.scope['environment']}/datasets"
            ))
            discovery["prefix"] = relative_key(prefix.rstrip("/"))
            required = {name for name, item in datasets.items() if item.source_stage != "silver"}
            try:
                names = tuple(self.folder_catalog.list_folders(discovery["prefix"]))
            except FileNotFoundError:
                if required or not datasets:
                    raise
                names = ()
                discovery["note"] = "No local dataset directory; explicitly bound shared silver supplies all inputs."
            for name in names:
                identifier(name, "discovered_dataset")
            if len(names) != len(set(names)):
                raise ValueError("Discovery returned duplicate dataset folders")
            if (not names and not datasets) or required - set(names):
                raise ValueError("Discovery is empty or configured dataset folders are missing")
            discovery["names"] = sorted(names)
            for name in sorted(names):
                datasets.setdefault(name, DatasetSettings(name, format=model.options.get("input_format", "parquet")))
        if not 1 <= len(datasets) <= 256:
            raise ValueError("A pipeline requires between 1 and 256 datasets")
        keys = [_key(name) for name in datasets]
        if len(keys) != len(set(keys)):
            raise ValueError("Dataset names collide after Azure ML key normalization")
        return tuple(datasets.values()), discovery

    def create_batch_pipeline(self, pipeline_type: PipelineType, request: PipelineRequest, *,
                              output: Path, model_number: int | None = None) -> PipelinePlan:
        if not isinstance(pipeline_type, PipelineType) or not isinstance(request, PipelineRequest):
            raise TypeError("Use PipelineType and PipelineRequest")
        settings, model = self.settings, self.settings.model(model_number)
        if pipeline_type.is_inference and request.model_version is None:
            raise ValueError("Inference requires an explicit registered model_version")
        if (pipeline_type.is_training or pipeline_type.is_inference) and not model.features:
            raise ValueError("Training and inference require explicit features")
        output = Path(output).resolve()
        import ml_model_factory
        packages = [Path(__file__).resolve().parents[1], Path(ml_model_factory.__file__).resolve().parent]
        if any(output == path or output in path.parents or output.is_relative_to(path) for path in packages):
            raise ValueError("Output must not overlap package source")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Render output must be a new or empty directory")
        datasets, discovery = self._datasets(model)
        scenario = model.scenario()
        mode = "automl" if pipeline_type == PipelineType.IN_2_GOLD_TRAINING_AUTOML else "custom"
        if pipeline_type.is_inference:
            mode = model.options.get("inference_mode", "custom")
            if mode not in ("custom", "automl"):
                raise ValueError("inference_mode must be custom or automl")
        layout = LakeLayout.from_config({
            **settings.scope, "use_case": model.use_case, "dataset": datasets[0].name,
            "data_version": request.version, "snapshot_id": request.snapshot, "run_id": request.run_id,
            "model_version": request.model_version, "serving": "batch",
            "prefix": settings.storage.get("prefix", "mlops/v1"), "storage": settings.storage,
        }, scenario)
        naming = ESMLNaming(settings, model)
        tags = {**settings.scope, "run_id": request.run_id, "data_version": request.version,
                "snapshot_id": request.snapshot}
        if pipeline_type.is_training:
            tags = validate_tags({
                **build_tags(scenario, settings.scope, mode=mode, engine="azureml", require_scope=True),
                "dataset": datasets[0].name, "data_version": request.version,
                "snapshot_id": request.snapshot, "run_id": request.run_id,
            }, require_scope=True)
        config = {
            "scenario": scenario, "tags": tags, "mode": mode,
            "table_format": model.options.get("table_format", "delta"),
            "aml_table_format": model.options.get("aml_table_format", model.options.get("table_format", "delta")),
            "bronze_mode": model.options.get("bronze_mode", "raw"),
            "require_gold": True,
            "request": {"data_date_utc": request.data_date_utc, "run_id": request.run_id,
                        "data_version": request.version, "snapshot_id": request.snapshot,
                        "model_version": request.model_version, "pipeline_type": pipeline_type.value,
                        "scope": settings.scope},
        }
        common = {
            "esml_data_date_utc": request.data_date_utc, "esml_model_version": request.model_version or "none",
            "esml_project_name": settings.project_folder, "esml_environment": settings.scope["environment"],
            "esml_run_id": request.run_id, "esml_data_version": request.version, "esml_snapshot_id": request.snapshot,
        }
        identity = json.dumps([settings.scope, model.use_case, pipeline_type.value, request.run_id], sort_keys=True)
        document = {
            "$schema": SCHEMAS + "pipelineJob.schema.json", "type": "pipeline",
            "name": "esml-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
            "display_name": naming.experiment(pipeline_type), "experiment_name": naming.experiment(pipeline_type),
            "tags": {**tags, "esml_pipeline_type": pipeline_type.value,
                     "esml_table_format": config["table_format"], "esml_aml_table_format": config["aml_table_format"]},
            "settings": {"default_compute": "azureml:" + settings.runtime["compute"],
                         "default_datastore": "azureml:" + settings.storage["datastore"],
                         "continue_on_step_failure": False, "force_rerun": not request.allow_reuse},
            "inputs": dict(common), "outputs": {}, "jobs": {},
        }
        if pipeline_type.is_training:
            document["tags"].update(factory_quality_gate="evaluate", factory_mode=mode,
                                    factory_task=model.task, factory_scenario=model.use_case)
        manifest = {
            "schema": "esml.pipeline-plan/v2", "pipeline_type": pipeline_type.value,
            **settings.scope, "use_case": model.use_case, "model_name": scenario["model_name"],
            "model_number": model.number,
            "request": deepcopy(config["request"]), "datasets": [value.name for value in datasets],
            "discovery": discovery, "paths": {"sources": {}, "outputs": {}},
            "snapshot_ref": layout.azureml_uri("training_snapshot"),
            "data_assets": [], "steps": {},
            "table_format": config["table_format"], "aml_table_format": config["aml_table_format"],
            "bronze_mode": config["bronze_mode"], "silver_references": {},
            "write_policy": "Run-scoped staging, not a published immutable snapshot. Use a new run_id per attempt; "
                            "rendering does not check remote existence or prevent concurrent writers.",
            "binding_policy": "Data and output URIs are concrete. Rebuild for a different date, version, or run; "
                              "changing literal invocation inputs alone does not rebind lake paths.",
        }
        configs = {}
        root = layout.key("inference_root" if pipeline_type.is_inference else "training_run")

        def uri(key):
            return f"azureml://datastores/{settings.storage['datastore']}/paths/{relative_key(key.rstrip('/'))}/"

        def input_path(dataset):
            return dataset.input_path.format(
                data_version=request.version, data_date_utc=request.data_date_utc,
                date_folder=request.data_date_utc.replace("-", "/"), run_id=request.run_id,
                model_version=request.model_version or "none", environment=settings.scope["environment"],
                project_folder=settings.project_folder, model_folder=model.folder, dataset=dataset.name)

        def expose(name, key, kind="uri_folder", *, dataset=None, stage=None):
            document["outputs"][name] = {"type": kind, "path": uri(key), "mode": "rw_mount"}
            manifest["paths"]["outputs"][name] = uri(key)
            if kind != "mlflow_model":
                medallion = stage or ("gold" if name in ("gold", "train", "validation", "test") else name)
                representation = (config["aml_table_format"] if name in ("train", "validation", "test")
                                  else "raw" if medallion == "bronze" and config["bronze_mode"] == "raw"
                                  else config["table_format"] if medallion in ("gold", "silver")
                                  else "parquet" if name == "prepared" else "artifact")
                manifest["data_assets"].append({
                    "name": naming.data(stage or name, dataset=dataset, inference=pipeline_type.is_inference),
                    "version": request.run_id, "path": uri(key), "type": kind,
                    "output": name,
                    "tags": {**settings.scope, "use_case": model.use_case, "run_id": request.run_id,
                             "data_version": request.version, "snapshot_id": request.snapshot,
                             "medallion_stage": medallion, "data_format": representation},
                })
            return _binding("outputs", name)

        def add(key, step, operation, inputs, outputs, *, dataset=None, extra=None, labels=None):
            step_config = {**deepcopy(config), **deepcopy(extra or {}), "step": step.value,
                           "dataset_name": dataset.name if dataset else None}
            if labels:
                step_config["input_labels"] = dict(labels)
            if dataset:
                step_config["dataset"] = {"format": dataset.format,
                                          "required_columns": list(dataset.required_columns)}
                if dataset.delta_version is not None:
                    step_config["dataset"]["delta_version"] = dataset.delta_version
            input_types = {name: kind for name, (kind, _) in inputs.items()}
            output_types = {name: kind for name, (kind, _) in outputs.items()}
            builder = getattr(self.step_map, "create_component", None)
            if callable(builder):
                override = builder(step, dict(input_types), dict(output_types), deepcopy(step_config),
                                   dataset=dataset.name if dataset else None)
            else:
                override = self.step_map.resolve(step, dataset.name if dataset else None) if self.step_map else None
            if override is not None and not isinstance(override, StepOverride):
                raise TypeError("Step maps must return StepOverride or None")
            if pipeline_type == PipelineType.IN_2_GOLD_INFERENCE_DBX and (
                    override is None or override.engine != "databricks"):
                raise ValueError(f"All-DBX pipeline requires an explicit Databricks component for {step.value}")
            bindings = {name: value for name, (_, value) in inputs.items()}
            compute = settings.runtime["compute"]
            if step == StepType.TRAINING_AUTOML and override is None:
                automl = _automl(scenario, settings.runtime, standalone=False)
                automl.update(training_data=bindings["train"], validation_data=bindings["validation"])
                automl["outputs"]["best_model"] = outputs["best_model"][1]
                document["jobs"][key] = automl
                manifest["steps"][key] = {"step": step.value, "engine": "azureml", "override": False, "dataset": None}
                return {"best_model": _binding(f"jobs.{key}.outputs", "best_model")}
            if override:
                component = deepcopy(override.component)
                if isinstance(component, str) and component.rsplit(":", 1)[-1].lower() in (
                        "0", "latest", "active", "champion", "production"):
                    raise ValueError("Step component references must use immutable versions")
                if (isinstance(component, dict) and isinstance(component.get("inputs"), dict)
                        and "esml_context_b64" in component["inputs"]):
                    if "esml_context_b64" in inputs:
                        raise ValueError("Dataset input collides with the reserved ESML context port")
                    input_types["esml_context_b64"] = "string"
                    bindings["esml_context_b64"] = base64.b64encode(
                        json.dumps(step_config, sort_keys=True, allow_nan=False).encode("utf-8")).decode("ascii")
                if set(override.inputs) & set(input_types):
                    raise ValueError("Step override inputs cannot replace reserved data ports")
                if isinstance(component, dict):
                    if component.get("code") and not str(component["code"]).startswith("azureml:"):
                        component["code"] = str((settings.base_path / component["code"]).resolve())
                    for direction, expected in (("inputs", input_types), ("outputs", output_types)):
                        actual = component.get(direction, {})
                        if (not isinstance(actual, dict) or any(
                                not isinstance(actual.get(name), dict) or actual[name].get("type") != kind
                                for name, kind in expected.items())):
                            raise ValueError(f"Override {step.value} has incompatible {direction} ports")
                        allowed = set(expected) | (set(override.inputs) if direction == "inputs" else set())
                        if set(actual) != allowed:
                            raise ValueError(f"Override {step.value} has unsupported {direction} ports")
                    if component.get("type") == "command":
                        component["is_deterministic"] = (
                            request.allow_reuse and component.get("is_deterministic", True)
                            and override.engine != "databricks")
                if override.engine == "databricks":
                    document["settings"]["force_rerun"] = True
                bindings.update(deepcopy(override.inputs))
                compute = override.compute or compute
            else:
                if set(inputs) & set(common):
                    raise ValueError("Dataset input ports collide with reserved ESML request context ports")
                input_types.update({name: "string" for name in common})
                bindings.update({name: _binding("inputs", name) for name in common})
                configs[key] = step_config
                command = f"python -m azure_esml.domain_layer.runtime --operation {operation} --config configs/{key}.json"
                for name in inputs:
                    flag = ("--" + name if name in ("prepared", "model") and operation in (
                        "training_manual", "evaluate", "inference") else "--input " + (labels or {}).get(name, name))
                    command += " " + flag + ' "${{inputs.' + name + '}}"'
                for name in outputs:
                    flag = name if operation == "split" and name != "prepared" else "output"
                    command += " --" + flag + ' "${{outputs.' + name + '}}"'
                for name, flag in (
                    ("esml_data_date_utc", "data-date-utc"), ("esml_run_id", "run-id"),
                    ("esml_model_version", "model-version"), ("esml_data_version", "data-version"),
                    ("esml_snapshot_id", "snapshot-id"), ("esml_project_name", "project-name"),
                    ("esml_environment", "environment"),
                ):
                    command += " --" + flag + ' "${{inputs.' + name + '}}"'
                component = {
                    "type": "command", "code": "./code", "environment": settings.runtime["environment"],
                    "is_deterministic": request.allow_reuse, "command": command,
                    "inputs": {name: {"type": kind} for name, kind in input_types.items()},
                    "outputs": {name: {"type": kind} for name, kind in output_types.items()},
                }
            document["jobs"][key] = {
                "type": "command", "component": component,
                "compute": compute if compute.startswith("azureml:") else "azureml:" + compute,
                "inputs": bindings, "outputs": {name: value for name, (_, value) in outputs.items()},
            }
            manifest["steps"][key] = {"step": step.value, "dataset": dataset.name if dataset else None,
                                      "engine": override.engine if override else "azureml",
                                      "override": override is not None}
            return {name: _binding(f"jobs.{key}.outputs", name) for name in outputs}

        if pipeline_type == PipelineType.GOLD_INFERENCE:
            document["inputs"]["gold"] = {"type": "uri_folder", "path": layout.azureml_uri("inference_gold")}
            manifest["paths"]["sources"]["gold"] = layout.azureml_uri("inference_gold")
            gold = _binding("inputs", "gold")
        else:
            silver = {}
            for dataset in datasets:
                key = _key(dataset.name)
                if dataset.input_path:
                    source = input_path(dataset)
                elif pipeline_type.is_inference:
                    source = f"{root}/in/{dataset.name}"
                else:
                    area = settings.storage.get("input_area", "landing")
                    source = f"{layout.key('scope')}/datasets/{dataset.name}/versions/{request.version}/{area}"
                document["inputs"]["raw_" + key] = {"type": "uri_folder", "path": uri(source)}
                manifest["paths"]["sources"][dataset.name] = uri(source)
                data = _binding("inputs", "raw_" + key)
                if dataset.source_stage == "silver":
                    if dataset.format == "delta" and dataset.delta_version is None:
                        raise ValueError("A shared Delta silver binding must pin delta_version explicitly")
                    manifest["silver_references"][dataset.name] = {
                        "path": uri(source), "format": dataset.format, "delta_version": dataset.delta_version,
                        "representation": "reference; no project table copy or repeated bronze refinement",
                    }
                    silver[key] = ("uri_folder", data)
                    continue
                stages = [(StepType.IN_2_SILVER, "in2silver", "silver")]
                if model.options.get("bronze", True):
                    stages = [(StepType.IN_2_BRONZE, "in2bronze", "bronze"),
                              (StepType.BRONZE_2_SILVER, "bronze2silver", "silver")]
                for step, operation, stage in stages:
                    area = "prepared" if pipeline_type.is_inference else "data"
                    target = expose(f"{stage}_{key}", f"{root}/{area}/{dataset.name}/{stage}",
                                    dataset=dataset.name, stage=stage)
                    data = add(f"{operation}_{key}", step, operation, {"data": ("uri_folder", data)},
                               {"output": ("uri_folder", target)}, dataset=dataset)["output"]
                silver[key] = ("uri_folder", data)
            merge = deepcopy(model.options.get("merge", {"mode": "concat"}))
            if not isinstance(merge, dict) or set(merge) - {"mode", "on", "how", "validate"}:
                raise ValueError("merge supports only mode, on, how, and validate")
            if merge.get("mode") not in ("concat", "join"):
                raise ValueError("merge.mode must be concat or join")
            if merge["mode"] == "join" and (
                    not isinstance(merge.get("on"), list) or not merge["on"]
                    or any(not isinstance(name, str) or not name for name in merge["on"])
                    or len(set(merge["on"])) != len(merge["on"])
                    or merge.get("how", "inner") not in ("inner", "left")
                    or merge.get("validate") not in ("one_to_one", "many_to_one")):
                raise ValueError("Join requires unique on columns, inner/left, and one_to_one/many_to_one validation")
            gold = add("merge", StepType.SILVER_MERGED_2_GOLD, "merge", silver,
                       {"output": ("uri_folder", expose("gold", f"{root}/gold" if pipeline_type.is_inference else f"{root}/gold/table"))},
                       extra={"merge": merge, "dataset_overrides": {
                           value.name: {"required_columns": list(value.required_columns)}
                           for value in datasets if value.required_columns
                       }, "input_versions": {
                           value.name: value.delta_version for value in datasets if value.source_stage == "silver" and value.format == "delta"
                       }}, labels={_key(value.name): value.name for value in datasets})["output"]

        if pipeline_type.is_training:
            prepared = add("split", StepType.TRAINING_SPLIT_AND_REGISTER, "split", {"data": ("uri_folder", gold)},
                           {name: (kind, expose(name, f"{root}/{suffix}", kind))
                            for name, kind, suffix in (
                                ("prepared", "uri_folder", "prepared"), ("train", "mltable", "gold/splits/train"),
                                ("validation", "mltable", "gold/splits/validation"), ("test", "mltable", "gold/splits/test"))})
            model_output = expose("model", layout.key("training_model"), "mlflow_model")
            if mode == "automl":
                trained = add("train", StepType.TRAINING_AUTOML, "training_automl",
                              {name: ("mltable", prepared[name]) for name in ("train", "validation")},
                              {"best_model": ("mlflow_model", model_output)})["best_model"]
            else:
                trained = add("train", StepType.TRAINING_MANUAL, "training_manual",
                              {"prepared": ("uri_folder", prepared["prepared"])},
                              {"model": ("mlflow_model", model_output)})["model"]
            add("evaluate", StepType.EVALUATE, "evaluate",
                {"prepared": ("uri_folder", prepared["prepared"]), "model": ("mlflow_model", trained)},
                {"report": ("uri_folder", expose("report", layout.key("training_evaluation")))})
        if pipeline_type.is_inference:
            document["inputs"]["model"] = {"type": "mlflow_model",
                                           "path": f"azureml:{scenario['model_name']}:{request.model_version}"}
            inference_inputs = {"data": ("uri_folder", gold), "model": ("mlflow_model", _binding("inputs", "model"))}
            if model.task == "forecasting" and mode == "automl":
                history = model.options.get("inference_history_path")
                if not isinstance(history, str) or not history:
                    raise ValueError("AutoML forecasting requires explicit inference_history_path")
                history_uri = uri(input_path(DatasetSettings("history", input_path=history)))
                document["inputs"]["history"] = {"type": "uri_folder", "path": history_uri}
                manifest["paths"]["history"] = history_uri
                inference_inputs["history"] = ("uri_folder", _binding("inputs", "history"))
            add("inference", StepType.INFERENCE_GOLD, "inference", inference_inputs,
                {"output": ("uri_folder", expose("inference", layout.key("output")))})

        document["tags"]["esml_config_sha256"] = hashlib.sha256(
            json.dumps(configs, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
        output.mkdir(parents=True, exist_ok=True)
        code_hashes = {}
        for package in packages:
            for source in package.rglob("*.py"):
                relative = source.relative_to(package)
                if (not source.is_file() or "__pycache__" in relative.parts
                        or any(part.startswith(".") for part in relative.parts)
                        or any(part.is_symlink() or getattr(part, "is_junction", lambda: False)()
                               for part in (source, *source.parents) if part.is_relative_to(package))):
                    continue
                destination = output / "code" / package.name / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                code_hashes[destination.relative_to(output / "code").as_posix()] = hashlib.sha256(
                    destination.read_bytes()).hexdigest()
        document["tags"]["esml_code_sha256"] = hashlib.sha256(
            json.dumps(code_hashes, sort_keys=True).encode("utf-8")).hexdigest()
        (output / "code" / "configs").mkdir(parents=True, exist_ok=True)
        for key, value in configs.items():
            (output / "code" / "configs" / f"{key}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
        document["tags"]["esml_bundle_sha256"] = bundle_fingerprint(document, output)
        document["tags"]["esml_request_sha256"] = canonical_hash(document)
        yaml_path = output / "pipeline.yml"
        yaml_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return PipelinePlan(document, output, manifest, yaml_path)
