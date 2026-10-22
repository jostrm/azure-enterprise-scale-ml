"""Offline contract tests for 41-single-agent-fabric-iq (no Azure calls)."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

EXAMPLE = Path(__file__).resolve().parents[1] / "41-single-agent-fabric-iq"
SPECIALISTS = {"Sales-Associate-Agent", "Rewards-Campaign-Agent", "Inventory-Agent"}


def _source(name: str) -> str:
    return (EXAMPLE / name).read_text(encoding="utf-8")


def _created_agents() -> set[str]:
    return set(re.findall(r'agent_name="([^"]+)"', _source("agents.py")))


def _workflow_agents() -> set[str]:
    return set(re.findall(r"^\s+name:\s*(\S+)\s*$", _source("workflow.yaml"), re.M))


def _template_keys() -> set[str]:
    lines = _source("parameters.env.template").splitlines()
    return {line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.startswith("#")}


def _load(script: str):
    try:
        sys.path.insert(0, str(EXAMPLE))
        spec = importlib.util.spec_from_file_location(f"fabric_iq_{script}", EXAMPLE / f"{script}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except ImportError as error:  # the example has its own requirements.txt
        raise unittest.SkipTest(f"example requirements not installed: {error}")
    finally:
        sys.path.remove(str(EXAMPLE))


def _load_agents_module():
    return _load("agents")


class FabricIqUseCaseTests(unittest.TestCase):
    def test_workflow_invokes_only_agents_that_agents_py_creates(self):
        self.assertEqual(_workflow_agents(), SPECIALISTS | {"Supervisor-Agent"})
        self.assertLessEqual(_workflow_agents(), _created_agents())

    def test_workflow_routes_on_each_specialist_name(self):
        routes = set(re.findall(r'Text = "([^"]+)"', _source("workflow.yaml")))
        self.assertEqual(routes, SPECIALISTS)

    def test_supervisor_instructions_name_every_route(self):
        supervisor = _source("agents.py").split('agent_name="Supervisor-Agent"', 1)[1]
        for name in SPECIALISTS:
            self.assertIn(name, supervisor)

    def test_template_lists_every_setting_the_scripts_read(self):
        module, setup, fabric = _load_agents_module(), _load("setup_knowledge"), _load("setup_fabric")
        self.assertEqual(
            set(module.REQUIRED) | set(module.OPTIONAL) | set(setup.SETUP) | set(fabric.SETUP), _template_keys(),
        )

    def _definition_files(self):
        fabric = _load("setup_fabric")
        definition = fabric.data_agent_definition("ws-id", "lh-id")
        return {part["path"]: json.loads(base64.b64decode(part["payload"])) for part in definition["parts"]}

    def test_data_agent_definition_is_published_so_its_mcp_endpoint_answers(self):
        files = self._definition_files()
        self.assertIn("Files/Config/publish_info.json", files)
        draft = {path.replace("/draft/", "/published/") for path in files if "/draft/" in path}
        self.assertLessEqual(draft, set(files))
        self.assertEqual(files["Files/Config/data_agent.json"], {"$schema": "2.1.0"})

    def test_data_agent_selects_the_inventory_table_with_every_csv_column(self):
        files = self._definition_files()
        source = next(value for path, value in files.items() if "/published/" in path and path.endswith("datasource.json"))
        self.assertEqual((source["workspaceId"], source["artifactId"], source["type"]), ("ws-id", "lh-id", "lakehouse_tables"))
        table = source["elements"][0]["children"][0]
        self.assertEqual((table["display_name"], table["is_selected"]), ("inventory", True))
        header = _source("data/inventory.csv").splitlines()[0].split(",")
        self.assertEqual([column["display_name"] for column in table["children"]], header)

    def test_fabric_iq_connection_passes_the_callers_entra_token_to_the_data_agent_mcp(self):
        fabric = _load("setup_fabric")
        properties = fabric.connection_definition("ws-id", "agent-id")["properties"]
        self.assertEqual(
            (properties["category"], properties["authType"], properties["audience"]),
            ("RemoteTool", "UserEntraToken", "https://analysis.windows.net/powerbi/api"),
        )
        self.assertEqual(
            properties["target"], "https://api.fabric.microsoft.com/v1/mcp/workspaces/ws-id/dataagents/agent-id/agent",
        )

    def test_setup_derives_search_names_from_the_agents_server_url(self):
        setup = _load("setup_knowledge")
        url = "https://srch.search.windows.net/knowledgebases/zava-kb/mcp?api-version=2026-08-01-preview"
        self.assertEqual(
            setup.search_names(url),
            ("https://srch.search.windows.net", "zava-kb", "zava-kb-index", "zava-kb-source"),
        )

    def test_index_keys_on_id_and_makes_every_sample_field_retrievable(self):
        setup = _load("setup_knowledge")
        index = setup.index_definition("zava-kb-index")
        fields = {field["name"]: field for field in index["fields"]}
        self.assertTrue(fields["id"]["key"])
        sample = {key for doc in setup.documents() for key in doc}
        self.assertLessEqual(sample, set(fields))
        self.assertTrue(all(field["retrievable"] for field in fields.values()))
        semantic = index["semantic"]
        self.assertEqual(semantic["defaultConfiguration"], semantic["configurations"][0]["name"])

    def test_knowledge_base_is_extractive_so_it_needs_no_search_side_model(self):
        setup = _load("setup_knowledge")
        base = setup.knowledge_base_definition("zava-kb", "zava-kb-source")
        self.assertEqual(base["outputMode"], "extractiveData")
        self.assertEqual(base["retrievalReasoningEffort"], {"kind": "minimal"})
        self.assertNotIn("models", base)

    def test_project_connection_reaches_the_knowledge_base_mcp_with_the_project_identity(self):
        setup = _load("setup_knowledge")
        url = "https://srch.search.windows.net/knowledgebases/zava-kb/mcp?api-version=2026-08-01-preview"
        properties = setup.connection_definition(url)["properties"]
        self.assertEqual(
            (properties["category"], properties["authType"], properties["target"]),
            ("RemoteTool", "ProjectManagedIdentity", url),
        )

    def test_missing_settings_fail_fast_with_their_names(self):
        module = _load_agents_module()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            env = Path(folder) / "parameters.env"
            env.write_text('endpoint="https://example.services.ai.azure.com/api/projects/p"\n', encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                module.load_settings(env)
        message = str(raised.exception)
        for name in set(module.REQUIRED) - {"endpoint"}:
            self.assertIn(name, message)
        self.assertNotIn("fabric_connection_name", message)

    def test_complete_settings_load_without_fabric(self):
        module = _load_agents_module()
        values = {name: f"value-{name}" for name in module.REQUIRED}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            env = Path(folder) / "parameters.env"
            env.write_text("".join(f'{k}="{v}"\n' for k, v in values.items()), encoding="utf-8")
            settings = module.load_settings(env)
        self.assertEqual({k: settings[k] for k in module.REQUIRED}, values)
        self.assertFalse(settings["fabric_connection_name"])

    def test_inventory_agent_uses_fabric_iq_not_the_deprecated_data_agent_tool(self):
        source = _source("agents.py")
        self.assertIn("FabricIQPreviewTool(", source)
        self.assertNotIn("MicrosoftFabricPreviewTool", source)  # deprecated 2026-11-06

    def _run_main(self, fabric_connection_name):
        module = _load_agents_module()
        calls = []

        def create_version(agent_name, definition):
            calls.append((agent_name, definition))
            return SimpleNamespace(id=f"{agent_name}:1", name=agent_name, version="1")

        client = MagicMock()
        client.__enter__.return_value.agents.create_version.side_effect = create_version
        client.__enter__.return_value.connections.get.return_value = SimpleNamespace(id="/connections/fabric")
        settings = {name: "x" for name in module.REQUIRED} | {"fabric_connection_name": fabric_connection_name}
        with patch.object(module, "load_settings", return_value=settings), \
                patch.object(module, "DefaultAzureCredential", MagicMock()), \
                patch.object(module, "AIProjectClient", return_value=client), \
                patch("builtins.print"):
            module.main()
        return dict(calls)

    def test_main_creates_every_agent_the_workflow_routes_to_even_without_fabric(self):
        created = self._run_main("")
        self.assertLessEqual(_workflow_agents() | {"FoundryIQ-Workflow"}, set(created))
        inventory = created["Inventory-Agent"]
        self.assertFalse(inventory.tools)
        self.assertIn("not configured", inventory.instructions)

    def test_main_grounds_inventory_on_the_fabric_iq_connection_when_configured(self):
        inventory = self._run_main("fabric-conn")["Inventory-Agent"]
        self.assertEqual([tool.type for tool in inventory.tools], ["fabric_iq_preview"])
        self.assertEqual(inventory.tools[0].project_connection_id, "/connections/fabric")

    def test_chat_asks_the_workflow_by_default_and_any_agent_on_request(self):
        chat = _load("chat")
        workflow = re.search(r"^name:\s*(\S+)", _source("workflow.yaml"), re.M).group(1)
        self.assertEqual(chat.parse(["Which", "paint?"]), (workflow, "Which paint?"))
        self.assertEqual(chat.parse(["--agent", "Sales-Associate-Agent", "Hi"]), ("Sales-Associate-Agent", "Hi"))

    def test_chat_prints_the_last_agents_answer_not_the_supervisor_route(self):
        chat = _load("chat")

        def message(agent, text):
            return SimpleNamespace(type="message", agent_reference={"name": agent},
                                   content=[SimpleNamespace(type="output_text", text=text)])

        response = SimpleNamespace(output=[
            SimpleNamespace(type="workflow_action", content=None),
            message("Supervisor-Agent", "Inventory-Agent"),
            message("Inventory-Agent", "Not configured yet."),
        ])
        self.assertEqual(chat.answer(response), "[Inventory-Agent] Not configured yet.")

    def test_real_parameters_env_is_git_ignored(self):
        self.assertIn("parameters.env", _source(".gitignore").split())

    def test_sample_products_carry_the_fields_the_sales_agent_returns(self):
        products = json.loads(_source("data/products.json"))
        self.assertGreater(len(products), 0)
        for product in products:
            self.assertLessEqual(
                {"id", "ProductId", "ProductName", "Category", "ProductDescription", "FormattedPrice"},
                set(product),
            )


if __name__ == "__main__":
    unittest.main()
