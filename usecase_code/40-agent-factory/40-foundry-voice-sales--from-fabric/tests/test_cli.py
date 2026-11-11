import contextlib
import io
import json
import unittest
from unittest.mock import patch

from sales_agent import cli


class CliTests(unittest.TestCase):
    def test_every_cloud_action_requires_explicit_opt_in_before_loading_config(self):
        for action in ("diagnose", "connectivity", "discover", "publish", "text", "smoke", "serve"):
            arguments = [action]
            if action in {"text", "smoke"}:
                arguments.extend(["--question", "Sales?"])
            with self.subTest(action=action), patch.object(cli.Settings, "load") as load:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(arguments), 2)
                load.assert_not_called()

    def test_missing_config_has_friendly_nonzero_error_without_cloud_imports(self):
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(cli.main(["--env-file", "__does_not_exist__.env", "check"]), 2)
        self.assertIn(".env", output.getvalue())

    def test_literal_question_is_one_argument_and_not_executed(self):
        parsed = cli.parser().parse_args(["text", "--allow-azure", "--question", "'; $(bad);"])
        self.assertEqual(parsed.question, "'; $(bad);")

    def test_network_report_is_not_equated_with_cloud_integration(self):
        result = cli.connectivity_report("example.invalid", ["10.1.2.3"], tls=True, require_private=True)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["scope"], "dns_tcp_tls_only")
        public = cli.connectivity_report("example.invalid", ["8.8.8.8"], tls=True, require_private=True)
        self.assertEqual(public["status"], "failed")


if __name__ == "__main__":
    unittest.main()
