import importlib.util
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get("AIF48_SERVICE_TESTS") == "1", "Real Azure service tests are opt-in.")
class RealTextSplitTests(unittest.TestCase):
    def test_actual_chunks_reconstruct_both_complete_table_inputs(self):
        source = Path(__file__).resolve().parents[2] / "main.py"
        spec = importlib.util.spec_from_file_location("sales_service_entry", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = Path(os.environ["AIF48_CONFIG"])
        args = module.parser().parse_args(["verify", "--config", str(config)])
        if os.environ.get("AIF48_USER_PROFILE"):
            args.user_profile = Path(os.environ["AIF48_USER_PROFILE"])
        result = module.run(args)
        self.assertEqual(result["state"], "verified")
        self.assertEqual(set(result["service_evidence"]), {"json", "excel"})
        for source in result["service_evidence"].values():
            self.assertEqual(source["chunk_count"], 3)
            self.assertGreater(source["input_tokens"], 9000)
            self.assertEqual(source["input_sha256"], source["reconstructed_sha256"])
            self.assertTrue(any(source["split_inside_record"]))
            self.assertTrue(all(chunk["tokens"] <= 6000 for chunk in source["chunks"]))


if __name__ == "__main__":
    unittest.main()
