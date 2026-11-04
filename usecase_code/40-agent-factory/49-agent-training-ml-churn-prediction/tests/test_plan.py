from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from tests.support import consumer

from ml_agent.configuration import paths, write_json
from ml_agent.plan import approved_plan, build_plan, record_publication, require, save_plan
from ml_agent.usecases import AIR, CHURN

NOW = datetime(2026, 10, 16, 15, 30, tzinfo=timezone.utc)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = consumer(Path(self.temporary.name), instantiate=False)

    def tearDown(self):
        self.temporary.cleanup()

    def test_plan_names_every_run_path_and_write_before_execution(self):
        plan = build_plan(self.config, now=NOW)
        churn, air = plan["usecases"][CHURN], plan["usecases"][AIR]
        self.assertEqual((churn["train_run_id"], churn["inference_run_id"]),
                         ("aif49-m49-train-2610161530", "aif49-m49-inf-2610161530"))
        self.assertEqual(air["train_run_id"], "aif49-m05-retrain-2610161530")
        self.assertEqual(churn["data_version"], "aif49-synth-v1")
        self.assertEqual(churn["lake"]["project_in"], "mlops/v1/projects/project001/environments/dev/datasets/"
                                                      f"{CHURN}/versions/aif49-synth-v1/in")
        self.assertEqual(churn["lake"]["use_case_root"],
                         f"mlops/v1/projects/project001/environments/dev/usecases/{CHURN}")
        self.assertEqual(churn["model_name"], "M49_49_agent_training_ml_churn_prediction")
        self.assertEqual(air["data_version"], "bootstrap-v2-20260913-r2")
        self.assertEqual(air["champion_model_id"], "azureml:M05_air_passengers:2")
        self.assertEqual(churn["operations"], ["create-usecase", "train", "infer"])
        self.assertEqual(air["operations"], ["retrain", "infer"])
        self.assertIn("role assignments", plan["never"])
        self.assertEqual(plan["scope"]["workspace"], "aml-test")
        self.assertIn("One owned Foundry prompt-agent version and paid model responses for the conversations.",
                      plan["azure_writes"])

    def test_a_plan_approves_only_the_selected_use_cases(self):
        plan = build_plan(self.config, now=NOW, usecases=[CHURN], hosted=True)
        churn, air = plan["usecases"][CHURN], plan["usecases"][AIR]
        self.assertEqual((churn["selected"], air["selected"]), (True, False))
        self.assertEqual(air["operations"], [])
        self.assertEqual(air["train_run_id"], "aif49-m05-retrain-2610161530")  # still bound in the rollout
        self.assertFalse([line for line in plan["azure_writes"] if "M05" in line])
        self.assertTrue(plan["azure_writes"][-1].startswith("Paid model responses"))
        with self.assertRaises(PermissionError):
            require(plan, AIR, "retrain")
        record_publication(paths(self.config).state, "aif49-synth-v1")
        air_only = build_plan(self.config, now=NOW, usecases=[AIR], fresh=True)
        self.assertEqual(air_only["usecases"][CHURN]["data_version"], "aif49-synth-v1")  # no new churn data
        self.assertEqual(air_only["usecases"][CHURN]["operations"], [])
        for invalid in ([], [CHURN, CHURN], ["titanic"]):
            with self.assertRaises(ValueError):
                build_plan(self.config, now=NOW, usecases=invalid)

    def test_fresh_reproductions_use_the_next_immutable_data_version(self):
        state = paths(self.config).state
        record_publication(state, "aif49-synth-v1")
        self.assertEqual(build_plan(self.config, now=NOW)["usecases"][CHURN]["data_version"], "aif49-synth-v1")
        self.assertEqual(build_plan(self.config, now=NOW, fresh=True)["usecases"][CHURN]["data_version"],
                         "aif49-synth-v2")

    def test_approval_is_bound_to_plan_bytes_and_configuration(self):
        path, digest = save_plan(self.config, build_plan(self.config, now=NOW))
        plan = approved_plan(path, digest, self.config)
        self.assertEqual(require(plan, CHURN, "train")["model_number"], 49)
        with self.assertRaises(PermissionError):
            require(plan, CHURN, "retrain")
        with self.assertRaises(ValueError):
            approved_plan(path, "0" * 64, self.config)
        changed = {**self.config, "model_deployment": "another-model"}
        with self.assertRaises(ValueError):
            approved_plan(path, digest, changed)
        write_json(path, {**plan, "owner": "tampered"})
        with self.assertRaises(ValueError):
            approved_plan(path, digest, self.config)


if __name__ == "__main__":
    unittest.main()
