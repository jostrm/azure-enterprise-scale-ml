"""Offline contract tests for 43-data-fabric-sharepoint (no Azure calls)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "43-data-fabric-sharepoint"
KB_URL = "https://srch-demo.search.windows.net/knowledgebases/kb-docs/mcp?api-version=2026-08-01-preview"
UPLOAD_KB_URL = "https://srch-demo.search.windows.net/knowledgebases/kb-uploads/mcp?api-version=2026-08-01-preview"


def _load(module_name: str):
    try:
        sys.path.insert(0, str(EXAMPLE))
        spec = importlib.util.spec_from_file_location(f"data_fabric_sharepoint_{module_name}",
                                                      EXAMPLE / f"{module_name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
        spec.loader.exec_module(module)
        return module
    except ImportError as error:  # the example has its own requirements.txt
        raise unittest.SkipTest(f"example requirements not installed: {error}")
    finally:
        sys.path.remove(str(EXAMPLE))


def _all_enabled() -> dict:
    return {
        "sharepoint": {"enabled": True, "project_connection_name": "sharepoint-intranet"},
        "foundry_iq": {"enabled": True, "server_label": "kb-docs", "server_url": KB_URL,
                       "project_connection_name": "kb-docs-connection"},
        "fabric_iq": {"enabled": True, "project_connection_name": "fabric-sales-agent"},
        "uploaded_documents": {"enabled": True, "storage_account": "saproj2001dev",
                               "container": "agent-uploads", "folder": "users/alex",
                               "server_label": "kb-uploads", "server_url": UPLOAD_KB_URL,
                               "project_connection_name": "kb-uploads-connection"},
    }


class _RecordingFactory:
    """Test double for the ToolFactory port: records what the domain asks for."""

    def __init__(self):
        self.calls = []

    def sharepoint(self, connection_id):
        self.calls.append(("sharepoint", connection_id))
        return ("sharepoint", connection_id)

    def knowledge_base(self, server_label, server_url, connection_id):
        self.calls.append(("knowledge_base", server_label, server_url, connection_id))
        return ("knowledge_base", server_label)

    def fabric_iq(self, connection_id):
        self.calls.append(("fabric_iq", connection_id))
        return ("fabric_iq", connection_id)


class DataSourceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.ds = _load("data_sources")

    def test_example_settings_file_is_valid_and_has_all_four_kinds(self):
        raw = json.loads((EXAMPLE / "data-sources.example.json").read_text(encoding="utf-8"))
        self.assertEqual(set(raw), set(self.ds.KINDS))
        self.ds.parse_data_sources(raw)  # placeholders are syntactically valid

    def test_disabled_source_needs_no_other_fields(self):
        settings = self.ds.parse_data_sources({"fabric_iq": {"enabled": False}})
        self.assertEqual(self.ds.enabled_sources(settings), [])

    def test_enabled_sources_keep_a_stable_order(self):
        settings = self.ds.parse_data_sources(_all_enabled())
        self.assertEqual([s.kind for s in self.ds.enabled_sources(settings)], list(self.ds.KINDS))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(self.ds.DataSourceError):
            self.ds.parse_data_sources({"onedrive": {"enabled": True}})

    def test_unknown_field_is_rejected(self):
        raw = {"sharepoint": {"enabled": True, "project_connection_name": "sp", "site_url": "x"}}
        with self.assertRaises(self.ds.DataSourceError):
            self.ds.parse_data_sources(raw)

    def test_enabled_flag_must_be_boolean(self):
        with self.assertRaises(self.ds.DataSourceError):
            self.ds.parse_data_sources({"sharepoint": {"enabled": "yes", "project_connection_name": "sp"}})

    def test_enabled_source_requires_its_fields(self):
        with self.assertRaises(self.ds.DataSourceError) as caught:
            self.ds.parse_data_sources({"foundry_iq": {"enabled": True, "server_label": "kb"}})
        self.assertIn("server_url", str(caught.exception))

    def test_knowledge_base_url_must_be_https_mcp_endpoint(self):
        for url in ("http://srch.search.windows.net/knowledgebases/kb/mcp",
                    "https://srch.search.windows.net/indexes/idx/docs",
                    "https://user:pw@srch.search.windows.net/knowledgebases/kb/mcp"):
            raw = {"foundry_iq": {"enabled": True, "server_label": "kb", "server_url": url,
                                  "project_connection_name": "kb"}}
            with self.subTest(url=url), self.assertRaises(self.ds.DataSourceError):
                self.ds.parse_data_sources(raw)

    def test_storage_account_and_container_follow_azure_naming(self):
        for field, value in (("storage_account", "SA-Proj2001"), ("storage_account", "sa"),
                             ("container", "Agent_Uploads"), ("container", "a--b")):
            raw = _all_enabled()
            raw["uploaded_documents"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(self.ds.DataSourceError):
                self.ds.parse_data_sources(raw)

    def test_upload_folder_cannot_escape_its_container_prefix(self):
        for folder in ("../other", "/users/alex", "users\\alex", "users//alex"):
            raw = _all_enabled()
            raw["uploaded_documents"]["folder"] = folder
            with self.subTest(folder=folder), self.assertRaises(self.ds.DataSourceError):
                self.ds.parse_data_sources(raw)

    def test_load_reads_a_json_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data-sources.json"
            path.write_text(json.dumps(_all_enabled()), encoding="utf-8")
            settings = self.ds.load_data_sources(path)
        self.assertEqual(len(self.ds.enabled_sources(settings)), 4)


class ToolBuildingTests(unittest.TestCase):
    def setUp(self):
        self.ds = _load("data_sources")

    def test_each_enabled_source_becomes_exactly_one_tool(self):
        settings = self.ds.parse_data_sources(_all_enabled())
        factory = _RecordingFactory()
        tools = self.ds.build_tools(settings, factory, resolve_connection=lambda name: f"id/{name}")
        self.assertEqual(tools, [("sharepoint", "id/sharepoint-intranet"), ("knowledge_base", "kb-docs"),
                                 ("fabric_iq", "id/fabric-sales-agent"), ("knowledge_base", "kb-uploads")])
        self.assertIn(("knowledge_base", "kb-uploads", UPLOAD_KB_URL, "kb-uploads-connection"), factory.calls)

    def test_knowledge_base_mcp_uses_the_connection_name_not_a_resolved_id(self):
        settings = self.ds.parse_data_sources({"foundry_iq": _all_enabled()["foundry_iq"]})
        factory = _RecordingFactory()
        resolved = []
        self.ds.build_tools(settings, factory, resolve_connection=lambda name: resolved.append(name) or name)
        self.assertEqual(resolved, [])
        self.assertEqual(factory.calls, [("knowledge_base", "kb-docs", KB_URL, "kb-docs-connection")])

    def test_no_enabled_source_gives_no_tools_and_honest_instructions(self):
        settings = self.ds.parse_data_sources({})
        self.assertEqual(self.ds.build_tools(settings, _RecordingFactory(), resolve_connection=str), [])
        self.assertIn("no data source", self.ds.agent_instructions(settings).lower())

    def test_instructions_name_every_enabled_source(self):
        settings = self.ds.parse_data_sources(_all_enabled())
        text = self.ds.agent_instructions(settings)
        for label in ("SharePoint", "Foundry IQ", "Fabric IQ", "uploaded documents"):
            self.assertIn(label, text)


class UploadPathTests(unittest.TestCase):
    def setUp(self):
        self.ds = _load("data_sources")
        self.uploads = self.ds.parse_data_sources(_all_enabled()).uploaded_documents

    def test_blob_name_is_folder_plus_file_name_only(self):
        self.assertEqual(self.ds.upload_blob_name(self.uploads, Path("C:/docs/Q3 report.pdf")),
                         "users/alex/Q3 report.pdf")

    def test_unsupported_file_types_are_rejected(self):
        for name in ("setup.exe", "script.ps1", "noextension"):
            with self.subTest(name=name), self.assertRaises(self.ds.DataSourceError):
                self.ds.upload_blob_name(self.uploads, Path(name))

    def test_account_url_targets_blob_endpoint(self):
        self.assertEqual(self.ds.blob_account_url(self.uploads), "https://saproj2001dev.blob.core.windows.net")

    def test_oversized_files_are_rejected(self):
        with self.assertRaises(self.ds.DataSourceError):
            self.ds.check_upload_size(self.ds.MAX_UPLOAD_BYTES + 1)
        self.ds.check_upload_size(self.ds.MAX_UPLOAD_BYTES)


class FoundryAdapterTests(unittest.TestCase):
    """Runs only where the example's requirements (azure-ai-projects 2.4.0) are installed."""

    def setUp(self):
        self.agents = _load("agents")
        from azure.ai.projects import models
        self.models = models

    def test_adapter_builds_the_sdk_tool_types(self):
        factory = self.agents.FoundryToolFactory()
        sharepoint = factory.sharepoint("conn-sp")
        self.assertIsInstance(sharepoint, self.models.SharepointPreviewTool)
        self.assertEqual(sharepoint.sharepoint_grounding_preview.project_connections[0].project_connection_id,
                         "conn-sp")
        fabric = factory.fabric_iq("conn-fabric")
        self.assertIsInstance(fabric, self.models.FabricIQPreviewTool)
        self.assertEqual(fabric.project_connection_id, "conn-fabric")
        kb = factory.knowledge_base("kb-docs", KB_URL, "kb-docs-connection")
        self.assertIsInstance(kb, self.models.MCPTool)
        self.assertEqual((kb.server_label, kb.server_url, kb.project_connection_id, kb.require_approval),
                         ("kb-docs", KB_URL, "kb-docs-connection", "never"))


if __name__ == "__main__":
    unittest.main()
