import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import TEMPLATE, consumer

import main
from ml_agent.configuration import write_json
from ml_agent.usecases import CHURN


def run(*argv):
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        code = main.main(list(argv))
    return code, (json.loads(output.getvalue()) if output.getvalue() else json.loads(errors.getvalue()))


class CommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.config_path = write_json(cls.root / "config.json", consumer(cls.root, instantiate=False))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_plan_prints_the_hash_to_approve(self):
        code, result = run("plan", "--config", str(self.config_path))
        self.assertEqual(code, 0)
        self.assertRegex(result["plan_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("--plan-sha256", result["approve_with"])
        self.assertEqual(result["usecases"][CHURN]["model_name"], "M49_49_agent_training_ml_churn_prediction")

    def test_live_commands_need_an_approved_plan(self):
        for command in ("create-usecase", "train", "retrain", "infer"):
            with self.subTest(command):
                code, result = run(command, "--config", str(self.config_path), "--usecase", CHURN, "--apply",
                                   "--allow-paid")
                self.assertEqual(code, 2)
                self.assertIn("--approved-plan", result["error"])

    def test_generated_state_cannot_be_written_inside_the_template(self):
        code, result = run("offline", "--config", str(self.config_path), "--work", str(TEMPLATE / "work"))
        self.assertEqual(code, 2)
        self.assertIn("outside the replaceable template", result["error"])


if __name__ == "__main__":
    unittest.main()
