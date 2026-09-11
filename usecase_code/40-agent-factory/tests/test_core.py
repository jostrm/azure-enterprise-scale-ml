from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.azure import AzureSession
from agent_factory.catalog import EVIDENCE_SCOPE_INSTRUCTIONS, agent_catalog, validate_agent_name
from agent_factory.config import FactoryConfig
from agent_factory.discovery import select_one


class ConfigurationTests(unittest.TestCase):
    def values(self):
        return {
            "tenantId": "11111111-1111-1111-1111-111111111111",
            "dev_sub_id": "22222222-2222-2222-2222-222222222222",
            "test_sub_id": "33333333-3333-3333-3333-333333333333",
            "project_number_000": "001", "admin_aifactoryPrefixRG": "demo-",
            "admin_aifactorySuffixRG": "-001", "admin_locationSuffix": "sdc",
            "projectPrefix": "esml-", "projectSuffix": "-rg", "vnetResourceGroupBase": "esml-common",
        }

    def load(self, document, environment="dev", overrides=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "variables.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return FactoryConfig.load(path, environment, overrides)

    def test_scoped_names_and_subscription(self):
        config = self.load({"dev": self.values()})
        self.assertEqual("demo-esml-project001-sdc-dev-001-rg", config.resource_group)
        self.assertEqual("demo-esml-common-sdc-dev-001", config.common_resource_group)
        self.assertEqual(self.values()["dev_sub_id"], config.subscription_id)

    def test_explicit_empty_naming_segments(self):
        values = {**self.values(), "projectPrefix": "", "projectSuffix": "", "admin_aifactoryPrefixRG": ""}
        self.assertEqual("project001-sdc-dev-001", self.load({"dev": values}).resource_group)

    def test_shared_stage_prod_section_uses_selected_environment(self):
        config = self.load({"dev": self.values(), "stage_prod": self.values()}, "test")
        self.assertEqual(self.values()["test_sub_id"], config.subscription_id)
        self.assertIn("-test-", config.resource_group)

    def test_no_fallback_to_dev_or_unknown_override(self):
        with self.assertRaises(ValueError):
            self.load({"dev": self.values()}, "prod")
        with self.assertRaises(ValueError):
            self.load({"dev": self.values()}, overrides={"subscrption_id": "other"})

    def test_ambiguity_is_never_first_match(self):
        with self.assertRaises(ValueError):
            select_one([{"name": "first"}, {"name": "second"}], "project")
        self.assertEqual({"name": "second"}, select_one([{"name": "first"}, {"name": "second"}], "project", "second"))


class SafetyTests(unittest.TestCase):
    def test_knowledge_scope_gate_excludes_conditional_workarounds(self):
        knowledge = next(item for item in agent_catalog() if item.get("grounding"))
        self.assertIn("Do not include procedural steps", knowledge["instructions"])
        self.assertIn("even as a generic alternative or conditional suggestion", knowledge["instructions"])
        self.assertIn("within the documented scope", knowledge["instructions"])
        self.assertIn("retrieved document titles and citations only, not a procedure summary",
                      knowledge["instructions"])

    def test_evidence_scope_is_preserved_by_grounded_workers_and_reviewers(self):
        for item in agent_catalog():
            if item.get("grounding") or item.get("members") or item["metadata"]["aifactory.role"] == "reviewer":
                with self.subTest(agent=item["name"]):
                    self.assertIn(EVIDENCE_SCOPE_INSTRUCTIONS, item["instructions"])

    def test_catalog_has_all_frameworks_and_real_participant_names(self):
        catalog = agent_catalog()
        self.assertEqual(
            {"prompt", "agent-framework", "langgraph", "openai-agent-sdk",
             "anthropic-agents", "github-copilot-sdk", "custom", "multi-agent"},
            {item["framework"] for item in catalog},
        )
        names = {item["name"] for item in catalog}
        for item in catalog:
            for member in item.get("members", []):
                self.assertIn(member["name"], names)
            self.assertLessEqual(len(item["metadata"]) + 3, 16)

    def test_invalid_names(self):
        for name in ("-bad", "bad-", "../escape", "a" * 64, ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_agent_name(name)

    def test_continuations_never_forward_token_to_other_origin(self):
        session = AzureSession("sub", "tenant")
        with patch.object(session, "request", return_value={
            "value": [], "nextLink": "https://attacker.invalid/steal",
        }) as request:
            with self.assertRaises(RuntimeError):
                session.pages("https://management.azure.com/resources")
            self.assertEqual(1, request.call_count)

    def test_token_has_explicit_subscription_and_tenant_guard(self):
        session = AzureSession("expected-sub", "expected-tenant")
        completed = type("Completed", (), {"returncode": 0, "stdout": json.dumps({
            "tenant": "other-tenant", "expires_on": 9999999999, "accessToken": "not-a-real-token",
        })})()
        with patch("agent_factory.azure.shutil.which", return_value="az"), \
             patch("agent_factory.azure.subprocess.run", return_value=completed) as run:
            with self.assertRaises(RuntimeError):
                session.token("https://ai.azure.com")
            self.assertIn("expected-sub", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
