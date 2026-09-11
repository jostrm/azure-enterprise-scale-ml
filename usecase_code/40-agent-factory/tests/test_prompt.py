from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceNotFoundError

from agent_factory.catalog import agent_catalog
from agent_factory.prompt import deploy_prompt


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.project = Mock()
        self.project.agents.get.side_effect = ResourceNotFoundError("missing")
        self.version = SimpleNamespace(name="aif-reviewer", version="1", id="aif-reviewer:1")
        self.project.agents.create_version.return_value = self.version
        self.target = SimpleNamespace(model_deployment="configured-model")
        self.spec = agent_catalog()[1]

    def test_creates_persistent_version_and_routes_it_without_deleting(self):
        result = deploy_prompt(self.project, self.target, self.spec)
        self.assertEqual("created", result["status"])
        create = self.project.agents.create_version.call_args.kwargs
        self.assertEqual("configured-model", create["definition"].model)
        self.assertEqual([], create["definition"].tools)
        self.assertEqual("40-agent-factory", create["metadata"]["aifactory.managed_by"])
        self.project.agents.update_details.assert_called_once()
        self.project.agents.delete.assert_not_called()
        self.project.agents.delete_version.assert_not_called()

    def test_idempotence_uses_current_metadata_hash(self):
        deploy_prompt(self.project, self.target, self.spec)
        created = self.project.agents.create_version.call_args.kwargs
        self.project.agents.create_version.reset_mock()
        self.project.agents.get.side_effect = None
        self.version.metadata = created["metadata"]
        self.version.definition = created["definition"]
        self.version.description = self.spec["description"]
        self.project.agents.get.return_value = SimpleNamespace(versions=SimpleNamespace(latest=self.version))
        self.assertEqual("unchanged", deploy_prompt(self.project, self.target, self.spec)["status"])
        self.project.agents.create_version.assert_not_called()

    def test_stale_metadata_hash_does_not_hide_a_changed_definition(self):
        deploy_prompt(self.project, self.target, self.spec)
        created = self.project.agents.create_version.call_args.kwargs
        self.version.metadata = created["metadata"]
        self.version.definition = created["definition"]
        self.version.definition.instructions = "Changed in the portal without changing the stored hash."
        self.version.description = self.spec["description"]
        self.project.agents.get.side_effect = None
        self.project.agents.get.return_value = SimpleNamespace(versions=SimpleNamespace(latest=self.version))
        self.project.agents.create_version.reset_mock()
        self.assertEqual("created", deploy_prompt(self.project, self.target, self.spec)["status"])
        self.project.agents.create_version.assert_called_once()

    def test_refuses_unowned_agent_name_collision(self):
        self.project.agents.get.side_effect = None
        self.project.agents.get.return_value = SimpleNamespace(
            versions=SimpleNamespace(latest=SimpleNamespace(metadata={})),
        )
        with self.assertRaisesRegex(RuntimeError, "not owned"):
            deploy_prompt(self.project, self.target, self.spec)
        self.project.agents.create_version.assert_not_called()

    def test_rag_agent_requires_completed_knowledge_configuration(self):
        with self.assertRaisesRegex(ValueError, "Foundry IQ"):
            deploy_prompt(self.project, self.target, agent_catalog()[0])
        self.project.agents.create_version.assert_not_called()

    def test_public_microsoft_docs_tool_requires_approval(self):
        deploy_prompt(self.project, self.target, agent_catalog()[2])
        tool = self.project.agents.create_version.call_args.kwargs["definition"].tools[0]
        self.assertEqual("always", tool.require_approval)
        self.assertEqual(["microsoft_docs_search", "microsoft_docs_fetch"], tool.allowed_tools)


if __name__ == "__main__":
    unittest.main()
