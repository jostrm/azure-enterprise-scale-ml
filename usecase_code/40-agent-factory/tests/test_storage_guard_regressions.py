import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from agent_factory.cli import validate_invocation_storage
from agent_factory import datafactory, knowledge
from test_storage_selection import selected_target
from test_knowledge import FakeSession


def test_invocation_rejects_changed_or_unverified_storage_journals(tmp_path):
    target = selected_target(True)
    spec = {"name": "my-agent", "grounding": True}
    with pytest.raises(RuntimeError, match="Deploy"):
        validate_invocation_storage(tmp_path, target, spec)
    deployment = {"target": selected_target(False).to_dict(), "completed": [{"name": "my-agent"}]}
    (tmp_path / "deployment.json").write_text(json.dumps(deployment))
    with pytest.raises(RuntimeError, match="another storage"):
        validate_invocation_storage(tmp_path, target, spec)
    deployment["target"] = target.to_dict()
    (tmp_path / "deployment.json").write_text(json.dumps(deployment))
    evidence = {"retrieval_verified": True, "storage": selected_target(False).storage_summary(),
                "connection_id": target.project_id + "/connections/knowledge"}
    (tmp_path / "knowledge.json").write_text(json.dumps(evidence))
    with pytest.raises(RuntimeError, match="Knowledge journal"):
        validate_invocation_storage(tmp_path, target, spec)
    evidence["storage"] = target.storage_summary()
    (tmp_path / "knowledge.json").write_text(json.dumps(evidence))
    validate_invocation_storage(tmp_path, target, spec)


def test_mixed_storage_index_is_rejected_before_retrieval_resources_are_created():
    target = selected_target(True)
    session = FakeSession()
    original = session.request
    def request(method, url, body=None, **kwargs):
        if "/docs/search?" in url and not body.get("queryType"):
            prefix = f"https://{target.storage_name}.blob.core.windows.net/{target.storage_container}/"
            return {"@odata.count": 2, "value": [
                {"id": "one", "topic": "VPN", "content": "selected", "document_url": prefix + "knowledge/items.json"},
                {"id": "two", "topic": "VPN", "content": "stale", "document_url": "https://old.blob.core.windows.net/old/items.json"},
            ]}
        return original(method, url, body, **kwargs)
    with patch.object(knowledge, "require_private_endpoint"), patch.object(session, "request", side_effect=request):
        with pytest.raises(ValueError, match="another storage"):
            knowledge.configure_knowledge(session, target)
    assert not session.resources


def test_selected_adf_paths_cannot_overwrite_worker_raw_blob_or_other_projects():
    first = selected_target(True)
    second = replace(first, project_name="other-project")
    assert datafactory.storage_prefix(first) != datafactory.PREFIX
    assert datafactory.storage_prefix(first) != datafactory.storage_prefix(second)
    definitions = datafactory.build_datafactory_definitions(first, factory_name="existing-adf")
    assert definitions["document_url"].endswith(datafactory.storage_prefix(first) + "/knowledge/items.json")
    assert definitions["prefix"] == datafactory.storage_prefix(first)
