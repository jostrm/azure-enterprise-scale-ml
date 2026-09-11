"""Credential-free tests; all scratch data stays underneath the project."""

import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import yaml

from ml_model_factory.azureml import TASK_SCHEMAS, _check_registration_job, _client, _lake_context, register, render
from ml_model_factory.serving import _model_name_version, deploy, forecast_predictions, load_model_batch_deployment

ROOT = Path(__file__).resolve().parents[1]


class AzureMLTests(unittest.TestCase):
    def setUp(self):
        self.work = ROOT / ".azureml-test-artifacts" / uuid4().hex
        self.work.mkdir(parents=True)
        self.scenario = {
            "name": "sample", "task": "classification", "target": "label",
            "features": ["age", "income"], "sensitive_features": ["group"],
            "dataset": {"provider": "kaggle", "kind": "dataset", "file": "train.csv"},
            "quality": {"min_accuracy": 0.6},
        }
        self.runtime = {
            "subscription_id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "resource_group": "rg-dev", "workspace_name": "ml-dev",
            "compute": "cpu-cluster", "gpu_compute": "gpu-cluster", "datastore": "workspaceblobstore",
            "input_data": "azureml://datastores/raw/paths/train.csv",
            "serving": {"instance_count": 1, "batch_instance_count": 1},
        }

    def tearDown(self):
        shutil.rmtree(self.work)
        try:
            self.work.parent.rmdir()
        except OSError:
            pass

    def document(self, mode="automl", scenario=None, folder="bundle"):
        paths = render(scenario or self.scenario, self.runtime, self.work / folder, ROOT, mode)
        return paths, yaml.safe_load(Path(paths["job"]).read_text(encoding="utf-8"))

    def lake_config(self, **overrides):
        return {
            "project": "001", "environment": "dev", "dataset": "customers",
            "data_version": "source-v3", "snapshot_id": "snapshot-20260911",
            "run_id": "run-001", "storage": {"datastore": "workspaceblobstore"},
            **overrides,
        }

    def test_lake_is_optional_and_does_not_change_default_output_allocation(self):
        paths, standalone = self.document("custom")
        pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text(encoding="utf-8"))
        self.assertNotIn("lake_manifest", paths)
        self.assertNotIn("lake", json.loads(Path(paths["runtime"]).read_text()))
        self.assertNotIn("lake", json.loads(Path(paths["manifest"]).read_text()))
        self.assertNotIn("path", standalone["outputs"]["model"])
        self.assertNotIn("path", pipeline["jobs"]["prepare"]["outputs"]["prepared"])
        for name in ("model", "report"):
            self.assertNotIn("path", pipeline["outputs"][name])
        for node in ("prepare", "evaluate"):
            self.assertNotIn("--lake-config", pipeline["jobs"][node]["command"])

    def test_lake_bindings_cover_all_tasks_and_modes_without_overlapping_split_ports(self):
        self.runtime["lake"] = self.lake_config()
        from ml_model_factory.lake import LakeLayout
        try:
            from azure.ai.ml import load_job
        except ImportError:
            load_job = None

        for mode in ("custom", "automl"):
            for task in TASK_SCHEMAS:
                with self.subTest(mode=mode, task=task):
                    scenario = {**self.scenario, "task": task, "forecast": {
                        "time_column": "date", "series_columns": ["store"], "frequency": "D", "horizon": 7,
                    }}
                    layout = LakeLayout.from_config(self.runtime["lake"], scenario)
                    paths, standalone = self.document(mode, scenario, folder=f"{mode}-{task}")
                    if load_job is not None:
                        for key in ("job", "prepare_job", "pipeline"):
                            if key in paths:
                                self.assertIsNotNone(load_job(source=paths[key]))
                    model_port = "best_model" if mode == "automl" else "model"
                    self.assertEqual(standalone["outputs"][model_port]["path"], layout.azureml_uri("training_model"))
                    lake = json.loads(Path(paths["lake_manifest"]).read_text())
                    self.assertEqual(lake["schema"], "ml-model-factory-lake/v1")
                    self.assertEqual(lake["task"], task)
                    self.assertEqual(lake["paths"], layout.as_dict())
                    self.assertNotIn("output", lake["paths"])
                    self.assertIn("not storage-enforced immutable", lake["write_policy"])
                    self.assertEqual(lake, json.loads((Path(paths["scenario"]).parent / "lake-manifest.json").read_text()))
                    self.assertEqual(lake, json.loads(Path(paths["manifest"]).read_text())["lake"])
                    self.assertEqual(lake["config"], json.loads(Path(paths["runtime"]).read_text())["lake"])
                    if "pipeline" not in paths:
                        self.assertTrue(task.startswith("image_") and mode == "automl")
                        continue
                    pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text())
                    prepare = pipeline["jobs"]["prepare"]
                    self.assertEqual(prepare["outputs"]["prepared"]["path"], layout.azureml_uri("training_run") + "prepared/")
                    self.assertNotEqual(prepare["outputs"]["prepared"]["path"], layout.azureml_uri("training_gold"))
                    self.assertEqual(prepare["outputs"]["prepared"]["mode"], "rw_mount")
                    self.assertIn("--lake-config lake.json", prepare["command"])
                    self.assertIn("--lake-config lake.json", pipeline["jobs"]["evaluate"]["command"])
                    for name, key in (("model", "training_model"), ("report", "training_evaluation")):
                        self.assertEqual(pipeline["outputs"][name]["path"], layout.azureml_uri(key))
                    self.assertEqual(pipeline["tags"]["factory_lake_data_version"], "source-v3")
                    self.assertEqual(pipeline["tags"]["factory_lake_snapshot_id"], "snapshot-20260911")
                    self.assertEqual(pipeline["tags"]["factory_lake_run_id"], "run-001")
                    for split in ("train", "validation", "test"):
                        if split in prepare["outputs"]:
                            self.assertNotIn("path", prepare["outputs"][split])
                            self.assertIn(f"/outputs/{split}/paths/", lake["split_outputs"][split])
                    if mode == "automl":
                        self.assertIn("/outputs/train/paths/", standalone["training_data"]["path"])
                    else:
                        self.assertIn("/outputs/prepared/paths/", standalone["inputs"]["prepared"]["path"])

    def test_lake_run_model_and_snapshot_identifiers_are_independent(self):
        first = _lake_context(self.scenario, {"lake": self.lake_config(model_version="model-1")})
        second = _lake_context(self.scenario, {"lake": self.lake_config(run_id="run-002", model_version="model-2")})
        for key in ("dataset_root", "training_gold", "checkpoint"):
            self.assertEqual(first["paths"][key], second["paths"][key])
        for key in ("training_model", "training_evaluation", "input", "output"):
            self.assertNotEqual(first["paths"][key], second["paths"][key])
        self.assertNotEqual(first["bindings"]["prepared"], second["bindings"]["prepared"])
        third = _lake_context(self.scenario, {"lake": self.lake_config(snapshot_id="new-snapshot")})
        self.assertNotEqual(first["paths"]["training_gold"], third["paths"]["training_gold"])
        self.assertEqual(first["bindings"]["prepared"], third["bindings"]["prepared"])
        self.assertEqual(first["bindings"]["model"], third["bindings"]["model"])

    def test_lake_rejects_unsafe_missing_or_mismatched_configuration_before_rendering(self):
        for field, value in (
            ("project", "01"), ("environment", "stage"), ("dataset", "../escape"),
            ("snapshot_id", "x/y"), ("run_id", r"x\y"), ("data_version", "%2e%2e"),
            ("model_version", "x?sig=secret"), ("model_version", "latest"),
            ("model_version", "champion"), ("model_version", "production"),
        ):
            with self.subTest(field=field):
                self.runtime["lake"] = self.lake_config(**{field: value})
                with self.assertRaises(ValueError):
                    self.document()
                self.assertFalse((self.work / "bundle").exists())
        for field in ("project", "environment", "dataset", "snapshot_id", "run_id", "data_version"):
            with self.subTest(missing=field):
                self.runtime["lake"] = self.lake_config()
                self.runtime["lake"].pop(field)
                with self.assertRaises(ValueError):
                    self.document()
        self.runtime["lake"] = self.lake_config()
        for field, value in (("project_number", "002"), ("environment_name", "prod"),
                             ("target_environment", "test"), ("project", "003")):
            with self.subTest(mismatch=field):
                self.runtime[field] = value
                with self.assertRaisesRegex(ValueError, "does not match"):
                    self.document()
                self.runtime.pop(field)
        self.runtime["lake"] = self.lake_config(storage={"datastore": "different"})
        with self.assertRaisesRegex(ValueError, "datastore"):
            self.document()
        self.assertFalse((self.work / "bundle").exists())

    def test_lake_requires_explicit_datastore_not_an_account_url(self):
        lake = self.lake_config(storage={"account_url": "https://lakeaccount.blob.core.windows.net", "container": "lake"})
        with self.assertRaisesRegex(ValueError, "datastore"):
            _lake_context(self.scenario, {"lake": lake})
        context = _lake_context(self.scenario, {"lake": lake, "datastore": "existing"})
        self.assertTrue(context["bindings"]["prepared"].startswith("azureml://datastores/existing/paths/"))
        self.assertEqual(context["config"]["storage"]["datastore"], "existing")
        lake["storage"]["account_url"] += "?sig=never-copy"
        with self.assertRaises(ValueError):
            _lake_context(self.scenario, {"lake": lake, "datastore": "existing"})

    def test_lake_runtime_serialization_does_not_copy_private_credentials(self):
        self.runtime["lake"] = self.lake_config(
            secret="never-copy-this",
            storage={"datastore": "workspaceblobstore", "account_key": "never-copy-this"},
        )
        self.runtime["environment"] = "azureml:factory:7"
        self.runtime["project_number"] = "001"
        self.runtime["environment_name"] = "dev"
        paths, _ = self.document()
        for key in ("runtime", "lake_config", "lake_manifest", "manifest"):
            self.assertNotIn("never-copy-this", Path(paths[key]).read_text())
        pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text())
        self.assertEqual(pipeline["jobs"]["prepare"]["environment"], "azureml:factory:7")

    def test_lake_preparation_records_lineage_and_refuses_known_duplicate_or_overlapping_outputs(self):
        import pandas as pd
        from scripts import azureml_prepare

        scenario_path, lake_path, raw, prepared = (self.work / name for name in (
            "scenario.json", "lake.json", "raw.csv", "prepared",
        ))
        scenario_path.write_text(json.dumps({**self.scenario, "split": {"group_column": "entity"}}))
        lake_path.write_text(json.dumps(self.lake_config()))
        pd.DataFrame({
            "age": list(range(100)), "income": list(range(100)),
            "group": ["A", "B"] * 50, "label": [0, 1] * 50,
            "entity": [index // 2 for index in range(100)],
        }).to_csv(raw, index=False)
        args = ["azureml_prepare.py", "--scenario", str(scenario_path), "--input", str(raw),
                "--prepared", str(prepared), "--lake-config", str(lake_path),
                "--train", str(self.work / "train-port")]
        with patch.object(sys, "argv", args):
            azureml_prepare.main()
        manifest = json.loads((prepared / "manifest.json").read_text())
        self.assertEqual(manifest["lake"]["config"]["dataset"], "customers")
        self.assertEqual(manifest["lake"]["config"]["snapshot_id"], "snapshot-20260911")
        self.assertEqual(manifest["lake"]["config"]["run_id"], "run-001")
        self.assertIn("source_sha256", manifest)
        self.assertEqual(manifest["split_policy"], "entity-group-disjoint")
        self.assertIn("group", pd.read_parquet(prepared / "train" / "data.parquet"))
        self.assertNotIn("group", pd.read_parquet(self.work / "train-port" / "data.parquet"))
        self.assertNotIn("entity", pd.read_parquet(self.work / "train-port" / "data.parquet"))
        entities = [set(pd.read_parquet(prepared / split / "data.parquet")["entity"])
                    for split in ("train", "validation", "test")]
        self.assertTrue(entities[0].isdisjoint(entities[1] | entities[2]))
        self.assertTrue(entities[1].isdisjoint(entities[2]))
        with patch.object(sys, "argv", args), patch.object(azureml_prepare.subprocess, "run") as prepare:
            with self.assertRaisesRegex(ValueError, "new run_id"):
                azureml_prepare.main()
            prepare.assert_not_called()
        empty = self.work / "fresh"
        args[args.index("--prepared") + 1] = str(empty)
        args[args.index("--train") + 1] = str(empty / "train")
        with patch.object(sys, "argv", args), patch.object(azureml_prepare.subprocess, "run") as prepare:
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                azureml_prepare.main()
            prepare.assert_not_called()

    def test_lake_evaluation_fails_closed_on_lineage_mismatch_and_enriches_passing_gate(self):
        from scripts import azureml_evaluate

        lake = _lake_context(self.scenario, {"lake": self.lake_config()})
        scenario_path, lake_path, prepared, model, report = (self.work / name for name in (
            "scenario.json", "lake.json", "prepared", "model", "report",
        ))
        scenario_path.write_text(json.dumps(self.scenario))
        lake_path.write_text(json.dumps(lake["config"]))
        prepared.mkdir()
        model.mkdir()
        (model / "MLmodel").write_text("artifact_path: model")
        manifest_path = prepared / "manifest.json"
        manifest = {"scenario": self.scenario["name"], "task": self.scenario["task"], "lake": lake}
        args = ["azureml_evaluate.py", "--mode", "custom", "--scenario", str(scenario_path),
                "--lake-config", str(lake_path), "--prepared", str(prepared),
                "--model", str(model), "--output", str(report)]
        for field, value in (("snapshot_id", "another"), ("run_id", "other-run"),
                             ("data_version", "other-data"), ("environment", "prod")):
            changed = json.loads(json.dumps(manifest))
            changed["lake"]["config"][field] = value
            manifest_path.write_text(json.dumps(changed))
            with self.subTest(field=field), patch.object(sys, "argv", args), patch.object(azureml_evaluate.subprocess, "run") as evaluate:
                with self.assertRaisesRegex(ValueError, "lineage does not match"):
                    azureml_evaluate.main()
                evaluate.assert_not_called()
        manifest["task"] = "regression"
        manifest_path.write_text(json.dumps(manifest))
        with patch.object(sys, "argv", args), self.assertRaisesRegex(ValueError, "lineage does not match"):
            azureml_evaluate.main()
        manifest["task"] = self.scenario["task"]
        manifest_path.write_text(json.dumps(manifest))
        def evaluate(*unused, **kwargs):
            report.mkdir()
            (report / "quality-gate.json").write_text(json.dumps({"passed": True}))
        with patch.object(sys, "argv", args), patch.object(azureml_evaluate.subprocess, "run", side_effect=evaluate):
            azureml_evaluate.main()
        gate = json.loads((report / "quality-gate.json").read_text())
        lineage = json.loads((report / "lineage.json").read_text())
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["lake"]["data_version"], "source-v3")
        self.assertEqual(gate["task"], "classification")
        self.assertEqual(lineage["model_output"], "model")
        self.assertEqual(lineage["lake"]["config"], lake["config"])
        with patch.object(sys, "argv", args), patch.object(azureml_evaluate.subprocess, "run") as evaluate:
            with self.assertRaisesRegex(ValueError, "new run_id"):
                azureml_evaluate.main()
            evaluate.assert_not_called()

    def test_automl_pipeline_binds_best_model_and_real_split_ports(self):
        paths, standalone = self.document()
        pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text(encoding="utf-8"))
        self.assertEqual(standalone["type"], "automl")
        self.assertEqual(pipeline["jobs"]["train"]["training_data"], "${{parent.jobs.prepare.outputs.train}}")
        self.assertEqual(pipeline["jobs"]["train"]["outputs"]["best_model"], "${{parent.outputs.model}}")
        self.assertEqual(pipeline["jobs"]["evaluate"]["inputs"]["model"], "${{parent.jobs.train.outputs.best_model}}")
        self.assertIn("azureml_evaluate.py", pipeline["jobs"]["evaluate"]["command"])
        self.assertIn("--no-deps", pipeline["jobs"]["evaluate"]["command"])
        self.assertFalse(pipeline["settings"]["continue_on_step_failure"])
        self.assertEqual(pipeline["jobs"]["prepare"]["outputs"]["test"]["type"], "mltable")
        self.assertTrue((self.work / "bundle" / "code" / "pyproject.toml").is_file())
        self.assertIn("azureml-automl.yml", pipeline["jobs"]["evaluate"]["environment"]["conda_file"])
        self.assertIn("azureml-custom.yml", pipeline["jobs"]["prepare"]["environment"]["conda_file"])

    def test_custom_pipeline_has_optional_actual_rai_components(self):
        paths, standalone = self.document("custom")
        self.assertEqual(standalone["outputs"]["model"]["type"], "mlflow_model")
        rai = yaml.safe_load(Path(paths["rai_pipeline"]).read_text(encoding="utf-8"))
        self.assertEqual(set(rai["jobs"]), {"construct", "explain", "errors", "gather"})
        self.assertTrue(rai["jobs"]["construct"]["component"].endswith("/rai_tabular_insight_constructor/versions/0.22.0"))
        self.assertEqual(rai["jobs"]["construct"]["inputs"]["model_info"], "${{parent.inputs.model_info}}")
        self.assertEqual(rai["jobs"]["gather"]["inputs"]["insight_2"], "${{parent.jobs.errors.outputs.error_analysis}}")

    def test_forecasting_settings_and_no_unsupported_no_code_deployment(self):
        scenario = {**self.scenario, "task": "forecasting", "forecast": {
            "time_column": "date", "series_columns": ["store"], "frequency": "D", "horizon": 7,
        }}
        paths, job = self.document(scenario=scenario)
        self.assertEqual(job["forecasting"]["time_series_id_column_names"], ["store"])
        self.assertEqual(job["forecasting"]["forecast_horizon"], 7)
        self.assertIn("pipeline", paths)
        self.assertNotIn("online_deployment", paths)
        self.assertNotIn("batch_deployment", paths)
        self.assertNotIn("rai_pipeline", paths)

    def test_all_image_tasks_are_explicit_about_automl_limitations(self):
        for task in TASK_SCHEMAS:
            if not task.startswith("image_"):
                continue
            with self.subTest(task=task):
                scenario = {**self.scenario, "task": task}
                paths, job = self.document(scenario=scenario, folder=task)
                self.assertEqual(job["compute"], "azureml:gpu-cluster")
                self.assertNotIn("pipeline", paths)
                self.assertNotIn("prepare_job", paths)
                self.assertNotIn("online_deployment", paths)
                self.assertNotIn("batch_deployment", paths)
                self.assertEqual(job["training_data"]["type"], "mltable")

    def test_custom_vision_pipeline_uses_gpu_without_dummy_table_ports(self):
        paths, job = self.document("custom", {**self.scenario, "task": "image_object_detection"})
        pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text(encoding="utf-8"))
        self.assertEqual(job["compute"], "azureml:gpu-cluster")
        self.assertEqual(pipeline["jobs"]["evaluate"]["compute"], "azureml:gpu-cluster")
        self.assertEqual(set(pipeline["jobs"]["prepare"]["outputs"]), {"prepared"})
        self.assertNotIn("rai_pipeline", paths)
        self.assertNotIn("batch_deployment", paths)

    def test_no_code_tabular_deployments_and_immutable_model_placeholder(self):
        paths, _ = self.document("custom")
        online = yaml.safe_load(Path(paths["online_deployment"]).read_text(encoding="utf-8"))
        batch = yaml.safe_load(Path(paths["batch_deployment"]).read_text(encoding="utf-8"))
        for deployment in (online, batch):
            self.assertNotIn("code_configuration", deployment)
            self.assertNotIn("environment", deployment)
            self.assertEqual(deployment["model"], "azureml:sample:REPLACE_WITH_REGISTERED_VERSION")
        self.assertEqual(batch["settings"]["error_threshold"], 0)

    def test_render_validates_limits_and_does_not_copy_runtime_secrets(self):
        self.runtime["secret"] = "never-copy-this"
        self.scenario["automl"] = {"limits": {"unsupported": 1}}
        with self.assertRaisesRegex(ValueError, "Unsupported AutoML"):
            self.document()
        self.assertFalse((self.work / "bundle").exists())
        self.scenario.pop("automl")
        paths, _ = self.document()
        self.assertNotIn("secret", json.loads(Path(paths["runtime"]).read_text()))
        with self.assertRaisesRegex(ValueError, "empty"):
            self.document()

    def test_explicit_environment_is_preserved(self):
        self.runtime["environment"] = "azureml:factory:7"
        paths, _ = self.document()
        pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text(encoding="utf-8"))
        self.assertEqual(pipeline["jobs"]["prepare"]["environment"], "azureml:factory:7")
        self.assertEqual(pipeline["jobs"]["evaluate"]["environment"], "azureml:factory:7")

    def test_client_binds_cli_credential_to_selected_tenant(self):
        with patch("azure.identity.AzureCliCredential") as credential, patch("azure.ai.ml.MLClient") as client:
            _client(self.runtime)
        credential.assert_called_once_with(tenant_id=self.runtime["tenant_id"])
        self.assertEqual(client.call_args.args[1:], (
            self.runtime["subscription_id"], self.runtime["resource_group"], self.runtime["workspace_name"],
        ))

    def test_client_does_not_fallback_from_managed_identity(self):
        runtime = {**self.runtime, "credential": "managed_identity", "managed_identity_client_id": "identity"}
        with patch("azure.identity.ManagedIdentityCredential") as managed, patch("azure.identity.AzureCliCredential") as cli, patch("azure.ai.ml.MLClient"):
            _client(runtime)
        managed.assert_called_once_with(client_id="identity")
        cli.assert_not_called()

    def test_registration_rejects_unsuccessful_jobs(self):
        for status in ("Running", "Failed", "Canceled", "NotStarted"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                _check_registration_job("pipeline", status, {"factory_quality_gate": "evaluate"},
                                        {"evaluate": {}}, {"model": {}, "report": {}})
        for status in ("Completed", "Succeeded"):
            _check_registration_job("pipeline", status, {"factory_quality_gate": "evaluate"},
                                    {"evaluate": {}}, {"model": {}, "report": {}})

    def registration_client(self, passed=True, lake=None):
        client = MagicMock()
        client.jobs.get.return_value = types.SimpleNamespace(
            type="pipeline", status="Completed",
            tags={"factory_quality_gate": "evaluate", "factory_scenario": "sample", "factory_mode": "custom"},
            jobs={"evaluate": {}}, outputs={"model": {}, "report": {}},
        )
        if lake is not None:
            client.jobs.get.return_value.tags.update(
                {f"factory_lake_{key}": lake["config"][key] for key in (
                    "project", "environment", "use_case", "dataset", "data_version", "snapshot_id", "run_id",
                )}
            )
            client.jobs.get.return_value.tags["factory_task"] = self.scenario["task"]
        def download(**kwargs):
            self.assertEqual(kwargs["output_name"], "report")
            path = Path(kwargs["download_path"]) / "named-outputs" / "report"
            path.mkdir(parents=True)
            (path / "quality-gate.json").write_text(json.dumps({"passed": passed}))
            (path / "lineage.json").write_text(json.dumps({
                "model_output": "model", "scenario": "sample",
                **({"lake": lake, "task": self.scenario["task"]} if lake is not None else {}),
            }))
        client.jobs.download.side_effect = download
        client.models.create_or_update.return_value.id = "azureml:sample:1"
        return client

    def fake_sdk_entities(self):
        constants = types.ModuleType("azure.ai.ml.constants")
        constants.AssetTypes = types.SimpleNamespace(MLFLOW_MODEL="mlflow_model")
        entities = types.ModuleType("azure.ai.ml.entities")
        entities.Model = lambda **kwargs: types.SimpleNamespace(**kwargs)
        return {"azure.ai.ml.constants": constants, "azure.ai.ml.entities": entities}

    def test_register_downloads_gate_and_registers_exact_pipeline_output(self):
        client = self.registration_client()
        with patch.dict(sys.modules, self.fake_sdk_entities()), patch("ml_model_factory.azureml._client", return_value=client):
            result = register("pipeline-123", self.runtime, "sample")
        self.assertEqual(result, "azureml:sample:1")
        model = client.models.create_or_update.call_args.args[0]
        self.assertEqual(model.path, "azureml://jobs/pipeline-123/outputs/model/paths/")
        self.assertEqual(model.tags["quality_gate"], "passed")

    def test_register_fails_closed_on_downloaded_negative_gate(self):
        client = self.registration_client(passed=False)
        with patch.dict(sys.modules, self.fake_sdk_entities()), patch("ml_model_factory.azureml._client", return_value=client):
            with self.assertRaisesRegex(ValueError, "did not pass"):
                register("pipeline-123", self.runtime, "sample")
        client.models.create_or_update.assert_not_called()

    def test_register_preserves_verified_lake_lineage_and_rejects_mismatched_run(self):
        lake = _lake_context(self.scenario, {"lake": self.lake_config()})
        client = self.registration_client(lake=lake)
        with patch.dict(sys.modules, self.fake_sdk_entities()), patch("ml_model_factory.azureml._client", return_value=client):
            self.assertEqual(register("pipeline-123", self.runtime, "sample"), "azureml:sample:1")
        tags = client.models.create_or_update.call_args.args[0].tags
        self.assertEqual(tags["factory_lake_snapshot_id"], "snapshot-20260911")
        self.assertEqual(tags["factory_lake_run_id"], "run-001")
        self.assertEqual(tags["factory_task"], "classification")
        client = self.registration_client(lake=lake)
        client.jobs.get.return_value.tags["factory_lake_run_id"] = "another-run"
        with patch.dict(sys.modules, self.fake_sdk_entities()), patch("ml_model_factory.azureml._client", return_value=client):
            with self.assertRaisesRegex(ValueError, "lake lineage"):
                register("pipeline-123", self.runtime, "sample")
        client.models.create_or_update.assert_not_called()

    def test_model_reference_requires_pinned_version(self):
        self.assertEqual(_model_name_version("azureml:sample:3"), ("sample", "3"))
        self.assertEqual(_model_name_version("/subscriptions/123/models/sample/versions/3"), ("sample", "3"))
        with self.assertRaises(ValueError):
            _model_name_version("azureml:sample@latest")

    def test_deployment_requires_registered_gate_and_switches_traffic_after_success(self):
        try:
            import azure.ai.ml
        except ImportError:
            self.skipTest("azure-ai-ml is optional")
        self.document("custom")
        client = MagicMock()
        model = types.SimpleNamespace(
            type="mlflow_model", id="azureml:sample:3",
            tags={"quality_gate": "passed", "pipeline_job": "pipeline-123",
                  "factory_scenario": "sample", "factory_mode": "custom"},
        )
        client.models.get.return_value = model
        endpoint = types.SimpleNamespace(name="sample-online", traffic={})
        client.online_endpoints.get.return_value = endpoint
        with patch("ml_model_factory.azureml._client", return_value=client):
            self.assertEqual(deploy(self.runtime, self.work / "bundle", model.id), "sample-online")
        self.assertEqual(client.online_endpoints.begin_create_or_update.call_count, 2)
        self.assertEqual(endpoint.traffic, {"blue": 100})
        self.assertEqual(client.online_deployments.begin_create_or_update.call_args.args[0].model, model.id)
        client.reset_mock()
        model.tags["quality_gate"] = "failed"
        with patch("ml_model_factory.azureml._client", return_value=client):
            with self.assertRaisesRegex(ValueError, "passing factory pipeline"):
                deploy(self.runtime, self.work / "bundle", model.id)
        client.online_endpoints.begin_create_or_update.assert_not_called()

    def test_load_jobs_with_sdk_when_installed(self):
        try:
            from azure.ai.ml import (
                load_batch_endpoint, load_job,
                load_online_deployment, load_online_endpoint,
            )
        except ImportError:
            self.skipTest("azure-ai-ml is optional; no dependencies installed by this test")
        for mode in ("custom", "automl"):
            for task in TASK_SCHEMAS:
                with self.subTest(mode=mode, task=task):
                    scenario = {**self.scenario, "task": task, "forecast": {
                        "time_column": "date", "series_columns": ["store"], "frequency": "D", "horizon": 7,
                    }}
                    paths, _ = self.document(mode, scenario, folder=f"{mode}-{task}")
                    for key in ("pipeline", "job", "prepare_job", "rai_pipeline"):
                        if key in paths:
                            self.assertIsNotNone(load_job(source=paths[key]))
                    for key, loader in (
                        ("online_endpoint", load_online_endpoint), ("online_deployment", load_online_deployment),
                        ("batch_endpoint", load_batch_endpoint), ("batch_deployment", load_model_batch_deployment),
                    ):
                        if key in paths:
                            self.assertIsNotNone(loader(source=paths[key]))

    def test_forecast_adapter_aligns_keys_not_position_and_hides_test_targets(self):
        try:
            import mlflow.sklearn
            import numpy as np
            import pandas as pd
        except ImportError:
            self.skipTest("Optional training dependencies are not installed")
        model = self.work / "model"
        model.mkdir()
        (model / "MLmodel").write_text("flavors:\n  sklearn: {}\n")
        scenario = {**self.scenario, "task": "forecasting", "features": ["value"], "target": "sales",
                    "forecast": {"time_column": "date", "series_columns": ["store"], "horizon": 1}}
        history = pd.DataFrame({"date": ["2025-01-01", "2025-01-01"], "store": ["b", "a"],
                                "value": [1, 2], "sales": [10, 20]})
        future = pd.DataFrame({"date": ["2025-01-02", "2025-01-02"], "store": ["b", "a"],
                               "value": [3, 4], "sales": [888, 999]})
        estimator = MagicMock()
        def forecast(query, y_query, ignore_data_errors):
            self.assertNotIn("sales", query)
            np.testing.assert_array_equal(y_query[:2], [10, 20])
            self.assertTrue(np.isnan(y_query[2:]).all())
            self.assertFalse(ignore_data_errors)
            ordered = query.iloc[[1, 3, 0, 2]].set_index(["store", "date"])
            return np.array([20, 22, 10, 11]), ordered
        estimator.forecast.side_effect = forecast
        with patch("mlflow.sklearn.load_model", return_value=estimator):
            np.testing.assert_array_equal(forecast_predictions(model, future, history, scenario), [11, 22])

    def test_preparation_and_gated_evaluation_wrappers_on_real_tabular_data(self):
        try:
            import mlflow
            import pandas as pd
            import pyarrow
        except ImportError:
            self.skipTest("Optional training dependencies are not installed")
        from ml_model_factory.training import train

        scenario = {**self.scenario, "quality": {"min_accuracy": 0.0}}
        raw = self.work / "raw.csv"
        pd.DataFrame({
            "age": list(range(100)), "income": [i * 2 for i in range(100)],
            "group": ["A", "B"] * 50, "label": [0, 1] * 50,
        }).to_csv(raw, index=False)
        config = self.work / "scenario.json"
        config.write_text(json.dumps(scenario))
        prepared, model, report = (self.work / name for name in ("prepared", "model", "report"))
        args = [sys.executable, str(ROOT / "scripts" / "azureml_prepare.py"),
                "--scenario", str(config), "--input", str(raw), "--prepared", str(prepared)]
        for name in ("train", "validation", "test"):
            args += ["--" + name, str(self.work / ("port-" + name))]
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("group", pd.read_parquet(prepared / "test" / "data.parquet"))
        self.assertNotIn("group", pd.read_parquet(self.work / "port-train" / "data.parquet"))
        train(scenario, prepared, model)
        args = [sys.executable, str(ROOT / "scripts" / "azureml_evaluate.py"),
                "--mode", "custom", "--scenario", str(config), "--prepared", str(prepared),
                "--model", str(model), "--output", str(report)]
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads((report / "quality-gate.json").read_text())["passed"])
        self.assertEqual(json.loads((report / "lineage.json").read_text())["model_output"], "model")
        scenario["quality"] = {"min_accuracy": 1.1}
        config.write_text(json.dumps(scenario))
        result = subprocess.run(args[:-1] + [str(self.work / "failed-report")],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads((self.work / "failed-report" / "quality-gate.json").read_text())["passed"])
        self.assertFalse((self.work / "failed-report" / "lineage.json").exists())


if __name__ == "__main__":
    unittest.main()
