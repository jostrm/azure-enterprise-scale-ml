"""A failed GOLD_INFERENCE job is retried in a fresh, bounded attempt; it is never resubmitted."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests import support  # noqa: F401  (puts the template on sys.path)

from ml_agent.configuration import read_json, write_json
from ml_agent.esml import MAX_INFERENCE_ATTEMPTS, latest_inference, select_inference_attempt

ENTRY = {"train_run_id": "aif49-m49-train-1", "inference_run_id": "aif49-m49-inf-1"}


class Backend:
    def __init__(self, statuses):
        self.statuses = statuses

    def get_job(self, name):
        return {"name": name, "status": self.statuses[name]}


class InferenceAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name)
        self.base = self.output / ENTRY["train_run_id"]
        write_json(self.base / "request.json", {"model_name": "M49_example"})
        write_json(self.base / "training-completion.json", {"model_id": "azureml:M49_example:1"})
        self.statuses = {}
        self.project = SimpleNamespace(_backend=lambda: Backend(self.statuses))
        self.rollout = SimpleNamespace(output=self.output)

    def tearDown(self):
        self.temporary.cleanup()

    def test_new_plans_use_the_planned_folder_and_inference_run(self):
        self.assertEqual(select_inference_attempt(self.project, self.rollout, ENTRY),
                         (self.base, "aif49-m49-inf-1"))

    def test_failed_job_moves_to_a_fresh_attempt_with_copied_training_receipts(self):
        write_json(self.base / "inference-pipeline-job.json", {"name": "job-1"})
        self.statuses["job-1"] = "Failed"
        directory, inference_id = select_inference_attempt(self.project, self.rollout, ENTRY)
        self.assertEqual((directory.name, inference_id), ("aif49-m49-train-1-a2", "aif49-m49-inf-1-a2"))
        self.assertEqual(read_json(directory / "training-completion.json")["model_id"], "azureml:M49_example:1")
        attempt = read_json(directory / "aif49-attempt.json")
        self.assertEqual(attempt["previous"], {"folder": "aif49-m49-train-1", "inference_run_id": "aif49-m49-inf-1",
                                               "job": "job-1", "status": "Failed"})
        self.assertEqual(attempt["files"], ["request.json", "training-completion.json"])
        write_json(directory / "inference-pipeline-job.json", {"name": "job-2"})
        self.statuses["job-2"] = "Running"
        self.assertEqual(select_inference_attempt(self.project, self.rollout, ENTRY)[0], directory)
        self.statuses["job-2"] = "Completed"
        write_json(directory / "aif49-inference-result.json", {"inference_run_id": inference_id, "rows": 50})
        self.assertEqual(select_inference_attempt(self.project, self.rollout, ENTRY)[0], directory)
        self.assertEqual(latest_inference(self.output, ENTRY)["inference_run_id"], "aif49-m49-inf-1-a2")

    def test_attempts_are_bounded(self):
        for number in range(1, MAX_INFERENCE_ATTEMPTS + 1):
            folder = self.base if number == 1 else self.output / f"aif49-m49-train-1-a{number}"
            write_json(folder / "inference-pipeline-job.json", {"name": f"job-{number}"})
            self.statuses[f"job-{number}"] = "Failed"
        with self.assertRaises(ValueError):
            select_inference_attempt(self.project, self.rollout, ENTRY)


if __name__ == "__main__":
    unittest.main()
