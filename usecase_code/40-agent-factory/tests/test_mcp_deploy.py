from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mcp_deploy_driver", ROOT / "44-azure-mcp" / "deploy.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class McpDeploymentDriverTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(subscription_id="sub", project_number="001", environment="dev")
        self.args = SimpleNamespace(
            command="deploy", config=Path("config.json"), target=None, variables_file=Path("reviewed.json"),
            expected_subscription="sub", expected_project="001", expected_environment="dev", apply=True,
        )

    def test_enable_settings_are_strict(self):
        for value in (True, "true"):
            self.assertTrue(driver.enabled(value))
        for value in (False, "false", None):
            self.assertFalse(driver.enabled(value))
        for value in (1, 0, "yes", "", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                driver.enabled(value)

    def test_disabled_deployment_stops_before_any_azure_access(self):
        with patch.object(driver, "load_selection", return_value=({}, self.config, {})) as selection, \
                patch.object(driver, "AzureSession") as session:
            with self.assertRaisesRegex(ValueError, "enableAzureMcpServer"):
                driver.run(self.args)
            session.assert_not_called()
            self.assertEqual(Path("reviewed.json"), selection.call_args.kwargs["variables_file"])

    def test_apply_is_required_before_any_azure_access(self):
        for command in ("prepare-identity", "deploy"):
            self.args.command = command
            self.args.apply = False
            with patch.object(driver, "load_selection", return_value=({}, self.config, {})), \
                    patch.object(driver, "AzureSession") as session:
                with self.assertRaisesRegex(ValueError, "--apply"):
                    driver.run(self.args)
                session.assert_not_called()

    def test_pipeline_target_mismatches_fail_before_cloud_calls(self):
        for field in ("expected_subscription", "expected_project", "expected_environment"):
            original = getattr(self.args, field)
            setattr(self.args, field, "different")
            with self.subTest(field=field), \
                    patch.object(driver, "load_selection", return_value=({}, self.config, {})), \
                    patch.object(driver, "AzureSession") as session:
                with self.assertRaisesRegex(ValueError, "pipeline's selected"):
                    driver.run(self.args)
                session.assert_not_called()
            setattr(self.args, field, original)

    def test_numeric_project_selection_is_normalized(self):
        self.args.expected_project = "1"
        with patch.object(driver, "load_selection", return_value=({}, self.config, {})):
            with self.assertRaisesRegex(ValueError, "enableAzureMcpServer"):
                driver.run(self.args)


if __name__ == "__main__":
    unittest.main()
