from datetime import datetime, timezone
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.support import air_passengers_csv, consumer

from ml_agent import esml
from ml_agent.configuration import paths, read_json, write_json
from ml_agent.lake import LakeIO
from ml_agent.plan import build_plan, published_versions
from ml_agent.runtime import ApprovalRequired, MLRuntime
from ml_agent.usecases import AIR, CHURN, CHURN_LEAF

NOW = datetime(2026, 10, 16, 15, 30, tzinfo=timezone.utc)
DATASTORE = "azureml://datastores/esml_shared_lake/paths/"


class FakeContainer:
    """In-memory blob container with create-only uploads."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def list_blobs(self, name_starts_with=""):
        return [SimpleNamespace(name=name) for name in sorted(self.blobs) if name.startswith(name_starts_with)]

    def upload_blob(self, name, data, overwrite=False):
        if name in self.blobs and not overwrite:
            raise ValueError("exists")
        self.blobs[name] = data.read() if hasattr(data, "read") else data

    def download_blob(self, name):
        return SimpleNamespace(readall=lambda: self.blobs[name])


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = consumer(Path(cls.temporary.name))
        cls.location = paths(cls.config)
        cls.plan = build_plan(cls.config, now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.container = FakeContainer()
        self.lake = LakeIO(self.config, container_client=self.container)
        self.projects = {}

    # ---- fakes ----------------------------------------------------------------------
    def project(self, name):
        if name in self.projects:
            return self.projects[name]
        project = esml.build_project(self.config, self.location, name)

        def execute(plan):
            kind = "inference" if "GOLD_INFERENCE" in plan.document["experiment_name"] else "training"
            return {"name": f"{kind}-job-{name}", "status": "Running"}

        def wait(job, **_):
            if job.startswith("inference"):
                self.publish_predictions(name)
            return {"name": job, "status": "Completed"}

        project.execute_pipeline = MagicMock(side_effect=execute)
        project.wait_for_completion = MagicMock(side_effect=wait)
        project.register_outputs = MagicMock(return_value=[])
        project.register_model = MagicMock(return_value=f"azureml:{self.plan['usecases'][name]['model_name']}:1")
        project.download_output = MagicMock(side_effect=lambda job, output, destination: write_json(
            Path(destination) / "report" / "comparison.json", {"schema": "champion", "model_id": "sha256:champion"}))
        self.projects[name] = project
        return project

    def publish_predictions(self, name):
        entry = self.plan["usecases"][name]
        planned = read_json(self.location.esml(name) / entry["train_run_id"] / "inference-request.json")
        gold = planned["input"][len(DATASTORE):].rstrip("/") + "/data.parquet"
        requests = pd.read_parquet(io.BytesIO(self.container.blobs[gold]))
        values = (["Yes", "No"] * len(requests))[:len(requests)] if name == CHURN else [400.0] * len(requests)
        buffer = io.BytesIO()
        pd.DataFrame({"request_id": requests["request_id"], "prediction": values}).to_parquet(buffer, index=False)
        self.container.blobs[planned["output"][len(DATASTORE):].rstrip("/") + "/predictions.parquet"] = buffer.getvalue()

    def runtime(self, **flags):
        options = {"plan": self.plan, "apply": True, "allow_paid": True, **flags}
        return MLRuntime(self.config, project_factory=self.project, lake_io=self.lake,
                         publisher=lambda config, staged: {"written": staged["plan"]["files"], "reused": 0},
                         **options)

    @staticmethod
    def definitions(rollout, run_id, *, component_version):
        return write_json(rollout.output / run_id / "registered-definitions.json", {"version": component_version})

    # ---- tests ----------------------------------------------------------------------
    def test_01_live_operations_require_the_approved_plan_and_flags(self):
        with self.assertRaises(ApprovalRequired):
            MLRuntime(self.config).create_usecase(CHURN)
        with self.assertRaises(ApprovalRequired):
            self.runtime(apply=False).create_usecase(CHURN)
        with self.assertRaises(ApprovalRequired):
            self.runtime(allow_paid=False).train(CHURN)
        with self.assertRaisesRegex(ValueError, "Create the use case first"):
            self.runtime().train(CHURN)  # never train M49 before its synthetic data is published
        with self.assertRaises(ValueError):
            self.runtime().train(AIR)
        with self.assertRaises(ValueError):
            self.runtime().retrain(CHURN)
        with self.assertRaises(ValueError):
            self.runtime().create_usecase(AIR)

    def test_02_create_usecase_writes_the_m49_copy_and_publishes_synthetic_data(self):
        result = self.runtime().create_usecase(CHURN)
        self.assertEqual(result["model"], "M49_49_agent_training_ml_churn_prediction")
        self.assertEqual(result["rows"], 7043)
        self.assertEqual(result["data_version"], "aif49-synth-v1")
        self.assertIn("aif49-synth-v1", published_versions(self.location.state))
        notebook = self.location.ml_root / CHURN_LEAF / f"{CHURN}-custom-pipeline.ipynb"
        self.assertTrue(notebook.is_file())
        self.assertIn("RUN_SYNTHESIZE", notebook.read_text(encoding="utf-8"))
        rollout = read_json(self.location.rollout)
        self.assertEqual(rollout["model_numbers"], {CHURN: 49})
        self.assertEqual(rollout["scenarios"][CHURN]["input_path"],
                         self.plan["usecases"][CHURN]["lake"]["project_in"])
        self.assertEqual(rollout["scenarios"][AIR]["data_version"], "bootstrap-v2-20260913-r2")
        again = self.runtime().prepare_local(self.plan)
        self.assertEqual(again["scenario"]["status"], "unchanged")
        self.assertEqual(again["notebook"]["written"], [])
        self.assertEqual(again["data"]["status"], "unchanged")

    def test_03_training_registers_m49_once_and_resumes_from_receipts(self):
        from azure_esml.domain_layer.rollout import AzureMLRollout

        with patch.object(AzureMLRollout, "register_definitions", autospec=True, side_effect=self.definitions):
            result = self.runtime().train(CHURN)
            again = self.runtime().train(CHURN)
        self.assertEqual(result["state"], "registered")
        self.assertEqual(result["model_id"], "azureml:M49_49_agent_training_ml_churn_prediction:1")
        self.assertEqual(again["state"], "registered")
        project = self.projects[CHURN]
        project.execute_pipeline.assert_called_once()
        project.register_model.assert_called_once()
        self.assertIs(project.register_model.call_args.kwargs["no_champion"], True)
        request = read_json(self.location.esml(CHURN) / self.plan["usecases"][CHURN]["train_run_id"] / "request.json")
        self.assertEqual(request["experiment_name"], f"M49_{CHURN}_IN_2_GOLD_TRAINING_MANUAL")
        self.assertTrue(request["compute"].endswith("m02-cpu-dev"))

    def test_04_churn_inference_uploads_unlabeled_gold_once_and_reads_lake_predictions(self):
        summary = self.runtime().infer(CHURN)
        self.assertEqual(summary["scored"], 50)
        self.assertEqual(summary["predicted_churn"], 25)
        self.assertEqual(summary["model_source"], "trained")
        gold = [name for name in self.container.blobs if name.endswith("/gold/data.parquet")]
        self.assertEqual(len(gold), 1)
        self.assertTrue(gold[0].startswith(self.plan["usecases"][CHURN]["lake"]["use_case_root"] + "/"))
        uploaded = pd.read_parquet(io.BytesIO(self.container.blobs[gold[0]]))
        self.assertNotIn("Churn", uploaded)
        self.assertTrue(uploaded["request_id"].is_unique)
        lineage = [name for name in self.container.blobs if name.endswith("/gold/lineage.json")]
        self.assertEqual(len(lineage), 1)
        self.assertEqual(self.runtime().predictions_summary(CHURN)["scored"], 50)

    def test_05_retraining_keeps_the_champion_and_scores_with_it(self):
        from azure_esml.domain_layer.rollout import AzureMLRollout
        from ml_model_factory.azureml import ModelSelectionRejected

        project = self.project(AIR)

        def reject(job, **options):
            decision = {"decision": "champion_kept", "reasons": ["Candidate and champion identify the same model"],
                        "comparisons": []}
            write_json(options["decision_path"], decision)
            raise ModelSelectionRejected(decision)

        project.register_model = MagicMock(side_effect=reject)
        csv = air_passengers_csv(Path(self.temporary.name) / "AirPassengers.csv")
        self.container.blobs[self.plan["usecases"][AIR]["input_path"] + "/AirPassengers.csv"] = csv.read_bytes()
        with patch.object(AzureMLRollout, "register_definitions", autospec=True, side_effect=self.definitions):
            result = self.runtime().retrain(AIR)
        self.assertEqual((result["state"], result["decision"]), ("not_promoted", "champion_kept"))
        self.assertEqual(project.register_model.call_args.kwargs["champion_evaluation"]["model_id"],
                         "sha256:champion")
        project.download_output.assert_called_once()
        summary = self.runtime().infer(AIR)
        self.assertEqual(summary["model_id"], "azureml:M05_air_passengers:2")
        self.assertEqual(summary["model_source"], "retained_champion")
        self.assertEqual(len(summary["forecasts"]), summary["rows"])
        self.assertTrue(all(item["passengers"] == 400.0 for item in summary["forecasts"]))
        status = self.runtime().status(AIR)
        self.assertEqual(status["training"]["decision"], "champion_kept")


if __name__ == "__main__":
    unittest.main()
