from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from agent_factory.cli import load_selection, parser, run, summarize_response
from agent_factory.config import Target


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        values = {
            "tenantId": "11111111-1111-1111-1111-111111111111",
            "dev_sub_id": "22222222-2222-2222-2222-222222222222",
            "project_number_000": "001", "admin_aifactoryPrefixRG": "demo-",
            "admin_aifactorySuffixRG": "-001", "admin_locationSuffix": "sdc",
            "projectPrefix": "esml-", "projectSuffix": "-rg", "vnetResourceGroupBase": "esml-common",
        }
        (self.root / "variables.json").write_text(json.dumps({"dev": values}), encoding="utf-8")
        self.path = self.root / "config.json"
        self.settings = {"targets": [{"key": "one", "variables_file": "variables.json", "environment": "dev"}]}
        self.path.write_text(json.dumps(self.settings), encoding="utf-8")
        self.target = Target(
            values["tenantId"], values["dev_sub_id"], "project", "common", "foundry", "project",
            "https://foundry.services.ai.azure.com/api/projects/project", "swedencentral",
            "model", "", "search", "storage2001", "/identity", "client",
        )

    def test_multiple_targets_require_explicit_selection(self):
        self.settings["targets"].append({**self.settings["targets"][0], "key": "two"})
        self.path.write_text(json.dumps(self.settings), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            load_selection(self.path, None)
        self.assertEqual("001", load_selection(self.path, "two")[1].project_number)

    def test_mutation_requires_apply_before_any_discovery(self):
        args = parser().parse_args(["deploy", "--config", str(self.path)])
        with patch("agent_factory.cli.discover") as discover:
            with self.assertRaisesRegex(ValueError, "--apply"):
                run(args)
            discover.assert_not_called()

    def test_plan_is_offline_and_target_bound(self):
        args = parser().parse_args(["plan", "--config", str(self.path)])
        with patch("agent_factory.cli.AzureSession") as session:
            result = run(args)
            self.assertFalse(result["mutations"])
            self.assertEqual(10, len(result["agents"]))
            session.assert_not_called()

    def test_partial_selections_preserve_prior_agent_inventory(self):
        state = self.root / ".agent-factory" / "foundry" / "project"
        state.mkdir(parents=True)
        prior = {"name": "aif-docs", "version": "1", "status": "created"}
        (state / "deployment.json").write_text(json.dumps({
            "target": self.target.to_dict(), "completed": [prior],
        }), encoding="utf-8")
        args = parser().parse_args(["deploy", "--config", str(self.path), "--agent", "aif-reviewer", "--apply"])
        project = MagicMock()
        with patch("agent_factory.cli.discover", return_value=self.target), \
             patch("agent_factory.cli.private_endpoint_checks", return_value=[{"private": True, "reachable": True}]), \
             patch("agent_factory.prompt.project_client", return_value=project), \
             patch("agent_factory.prompt.deploy_prompt", return_value={"name": "aif-reviewer", "version": "1"}):
            run(args)
        result = json.loads((state / "deployment.json").read_text(encoding="utf-8"))
        self.assertEqual({"aif-docs", "aif-reviewer"}, {item["name"] for item in result["completed"]})
        self.assertEqual(["aif-reviewer"], result["requested"])

    def test_grounded_invocation_requires_successful_knowledge_tool_call(self):
        response = SimpleNamespace(status="completed", output_text="Answer", id="response", output=[])
        spec = {"name": "aif-knowledge", "grounding": True}
        with self.assertRaisesRegex(RuntimeError, "without a successful"):
            summarize_response(response, spec)
        response.output = [SimpleNamespace(
            type="mcp_call", name="knowledge_base_retrieve", server_label="private-knowledge", error=None,
        )]
        self.assertEqual(1, len(summarize_response(response, spec)["tool_calls"]))
        response.output[0].error = "Tool failed"
        with self.assertRaisesRegex(RuntimeError, "MCP tool failed"):
            summarize_response(response, spec)


if __name__ == "__main__":
    unittest.main()
