import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_run", ROOT / "prepare_run.py")
prepare_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_run)


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.runtime = {
            "subscription_id": "00000000-0000-0000-0000-000000000001",
            "resource_group": "example-rg", "workspace_name": "example-ws",
        }
        self.copy = {
            "loadMode": "initial", "sourceContainer": "raw", "sourceFolder": "source",
            "sinkContainer": "prepared", "sinkFolder": "destination",
        }
        self.payload = {"properties": {"jobType": "Command", "command": "python train.py"}}

    def test_initial_rest_shape_and_no_guessed_output(self):
        result = prepare_run.build_parameters(self.runtime, self.copy, self.payload)
        self.assertEqual(result["jobPayload"], self.payload)
        self.assertEqual(result["workspaceName"], "example-ws")
        self.assertNotIn("output", result)

    def test_cli_shape_rejected(self):
        for payload in ({"type": "pipeline"}, {"properties": {"type": "pipeline"}},
                        {"properties": {"jobType": "Command"}, "$schema": "cli"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                prepare_run.build_parameters(self.runtime, self.copy, payload)

    def test_delta_requires_utc_increasing_window(self):
        self.copy.update(loadMode="delta", watermarkStart="2026-01-01T00:00:00Z",
                         watermarkEnd="2026-01-02T00:00:00Z")
        prepare_run.build_parameters(self.runtime, self.copy, self.payload)
        for end in ("2026-01-01T00:00:00Z", "2025-12-31T00:00:00Z", "2026-01-02T00:00:00"):
            self.copy["watermarkEnd"] = end
            with self.subTest(end=end), self.assertRaises(ValueError):
                prepare_run.build_parameters(self.runtime, self.copy, self.payload)

    def test_examples_are_json_but_unresolved_templates(self):
        for path in ROOT.glob("*.json"):
            self.assertIsInstance(prepare_run.load(path), dict)
        with self.assertRaises(ValueError):
            prepare_run.build_parameters(self.runtime, prepare_run.load(ROOT / "copy.example.json"),
                                         prepare_run.load(ROOT / "job-payload.example.json"))

    def lake(self, **overrides):
        return {
            "project": "001", "environment": "dev", "dataset": "stable-data", "data_version": "1",
            "snapshot_id": "snapshot-1", "run_id": "adf-execution-1", "serving": "batch",
            "pipeline_id": "prediction-events", "pipeline_version": "v1",
            "storage": {"account_url": "https://examplestorage.blob.core.windows.net",
                        "container": "ml-model-factory", "datastore": "project_blob"},
            **overrides,
        }

    def lake_parameters(self, **kwargs):
        self.payload["properties"]["inputs"] = {
            "raw": {"jobInputType": "uri_folder", "uri": "azureml://datastores/old/paths/wrong/", "mode": "Download"},
        }
        return prepare_run.build_parameters(
            self.runtime, self.copy, self.payload, lake=kwargs.get("lake", self.lake()),
            scenario=kwargs.get("scenario", {"name": "test-case", "dataset": {"file": "train.csv"}}),
        )

    def test_lake_raw_copy_goes_to_landing_not_silver(self):
        from ml_model_factory.lake import LakeLayout

        layout = LakeLayout.from_config(self.lake(), scenario={"name": "test-case"})
        result = self.lake_parameters()
        self.assertEqual(result["sourceFolder"], "source")
        self.assertEqual(result["sinkContainer"], "ml-model-factory")
        self.assertEqual(result["sinkFolder"], layout.key("landing"))
        self.assertNotEqual(result["sinkFolder"], layout.key("silver"))
        self.assertEqual(result["filePattern"], "train.csv")
        raw = result["jobPayload"]["properties"]["inputs"]["raw"]
        self.assertEqual(raw["jobInputType"], "uri_file")
        self.assertEqual(raw["uri"], layout.azureml_uri("landing") + "train.csv")
        self.assertEqual(self.payload["properties"]["inputs"]["raw"]["jobInputType"], "uri_folder")
        self.assertEqual(result["lakeParameters"]["copyStage"], "landing")
        self.assertEqual(result["jobPayload"]["properties"]["tags"]["lake.runId"], "adf-execution-1")
        self.assertNotIn("outputs", result["jobPayload"]["properties"])

    def test_lake_derives_missing_sink_and_runtime_config(self):
        self.copy.pop("sinkContainer")
        self.copy.pop("sinkFolder")
        self.runtime["lake"] = self.lake()
        result = self.lake_parameters(lake=None)
        self.assertTrue(result["sinkFolder"].endswith("/landing"))

    def test_lake_requires_explicit_input_and_scenario_match(self):
        for scenario in (None, {"name": "test-case", "task": "image_classification", "dataset": {"file": "images"}},
                         {"name": "test-case", "dataset": {"file": "../train.csv"}},
                         {"name": "test-case", "dataset": {"file": "folder/train.csv"}}):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                self.lake_parameters(scenario=scenario)
        with self.assertRaises(ValueError):
            self.lake_parameters(lake=self.lake(use_case="different-case"))
        self.payload["properties"].pop("inputs")
        with self.assertRaises(ValueError):
            prepare_run.build_parameters(self.runtime, self.copy, self.payload, lake=self.lake(),
                                         scenario={"name": "test-case", "dataset": {"file": "train.csv"}})

    def test_lake_rejects_credentials_without_echoing_values(self):
        for value in (
            {"account_url": "https://examplestorage.blob.core.windows.net?sig=NEVER_PRINT"},
            {"connection_string": "AccountKey=NEVER_PRINT"},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                self.lake_parameters(lake=self.lake(storage=value))
            self.assertNotIn("NEVER_PRINT", str(caught.exception))
            self.copy["sourceFolder"] = "source"
            with self.assertRaises(ValueError) as caught:
                self.lake_parameters(lake=self.lake(prefix="mlops?password=NEVER_PRINT"))
            self.assertNotIn("NEVER_PRINT", str(caught.exception))
        self.copy["sourceFolder"] = "raw?sig=NEVER_PRINT"
        with self.assertRaises(ValueError) as caught:
            self.lake_parameters()
        self.assertNotIn("NEVER_PRINT", str(caught.exception))

    def test_lake_metadata_keeps_stable_checkpoint_across_model_runs(self):
        first = self.lake_parameters(lake=self.lake(serving="streaming", model_version="1"))
        second = self.lake_parameters(lake=self.lake(serving="streaming", model_version="2", run_id="next-run"))
        self.assertEqual(first["lakeParameters"]["paths"]["checkpoint"], second["lakeParameters"]["paths"]["checkpoint"])
        self.assertNotEqual(first["lakeParameters"]["paths"]["output"], second["lakeParameters"]["paths"]["output"])


class BicepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bicep = shutil.which("bicep")
        if not bicep:
            raise RuntimeError("Preinstall Bicep CLI to run the required offline build validation")
        result = subprocess.run([bicep, "build", str(ROOT / "main.bicep"), "--stdout"],
                                capture_output=True, text=True, check=True, timeout=120)
        cls.template = json.loads(result.stdout)
        cls.source = (ROOT / "main.bicep").read_text(encoding="utf-8")

    def test_children_only(self):
        for resource in self.template["resources"]:
            self.assertIn(resource["type"], {
                "Microsoft.DataFactory/factories/linkedservices",
                "Microsoft.DataFactory/factories/datasets",
                "Microsoft.DataFactory/factories/pipelines",
            })
            self.assertEqual(resource["apiVersion"], "2018-06-01")

    def test_blob_not_dfs_and_managed_identity(self):
        self.assertEqual(self.source.count("type: 'AzureBlobStorage'"), 2)
        self.assertNotIn("AzureBlobFS", self.source)
        self.assertIn("type: 'CredentialReference'", self.source)
        self.assertIn("connectVia: ir", self.source)
        self.assertNotIn("accessToken", self.source)
        self.assertNotIn("connectionString", self.source)

    def test_arm_contract_and_fail_closed_polling(self):
        for fragment in ("api-version=2024-04-01", "method: 'PUT'", "method: 'GET'",
                         "output.properties.status", "type: 'Until'", "timeout: '0.02:00:00'",
                         "type: 'Fail'", "secureInput: true", "secureOutput: true",
                         "turnOffAsync: true"):
            self.assertIn(fragment, self.source)
        for terminal in ("Completed", "Failed", "Canceled"):
            self.assertIn(terminal, self.source)
        self.assertNotIn("AzureMLExecutePipeline", self.source)
        self.assertNotIn(".output.jobId", self.source)
        self.assertNotIn(".output.runOutput", self.source)

    def test_initial_delta_and_notebook_paths(self):
        for fragment in ("InitialCopy", "DeltaCopy", "modifiedDatetimeStart", "modifiedDatetimeEnd",
                         "DatabricksNotebook", "notebookInputPath", "artifactRoot", "scenarioPath", "experimentPath"):
            self.assertIn(fragment, self.source)

    def test_optional_lake_parameters_do_not_change_copy_processing(self):
        self.assertIn("lakeParameters: { type: 'Object', defaultValue: {} }", self.source)
        self.assertIn("lakeConfig: { type: 'String', defaultValue: '' }", self.source)
        self.assertIn("lake_config: { value: '@pipeline().parameters.lakeConfig'", self.source)
        self.assertIn("copyBehavior: 'PreserveHierarchy'", self.source)
        self.assertIn("name: 'ValidateLakeDestination'", self.source)
        self.assertIn("lakeParameters.paths.landing", self.source)
        self.assertIn("lakeParameters.storageAccountUrl", self.source)
        self.assertNotIn("type: 'ExecuteDataFlow'", self.source)


if __name__ == "__main__":
    unittest.main()
