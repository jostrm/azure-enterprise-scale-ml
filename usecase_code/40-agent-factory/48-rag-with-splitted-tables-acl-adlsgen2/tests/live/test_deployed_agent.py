import importlib.util
import os
from pathlib import Path
import unittest


@unittest.skipUnless(
    os.environ.get("AIF48_LIVE_EVALUATIONS") == "1" and os.environ.get("AIF48_ALLOW_PAID") == "1",
    "Deployed-agent evaluations require explicit paid-call opt-in.",
)
class DeployedAgentTests(unittest.TestCase):
    def test_exact_prompts_numeric_answers_cross_index_evidence_and_restricted_user(self):
        source = Path(__file__).resolve().parents[2] / "main.py"
        spec = importlib.util.spec_from_file_location("sales_live_entry", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = module.parser().parse_args([
            "evaluate", "--config", os.environ["AIF48_CONFIG"], "--allow-paid",
            "--oracle", os.environ["AIF48_ORACLE"], "--restricted-profile", os.environ["AIF48_RESTRICTED_PROFILE"],
        ])
        if os.environ.get("AIF48_USER_PROFILE"):
            args.user_profile = Path(os.environ["AIF48_USER_PROFILE"])
        result = module.run(args)
        self.assertTrue(result["live"])
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["restricted_identity"]["state"], "passed")


if __name__ == "__main__":
    unittest.main()
