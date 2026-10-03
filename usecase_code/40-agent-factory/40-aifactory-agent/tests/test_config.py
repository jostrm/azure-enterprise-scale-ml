import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aifactory_agent.config import Settings, load_settings
from aifactory_agent.foundry import function, knowledge_tools, retrieval_query


EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def test_configuration_is_portable_without_code_edits():
    config = json.loads(EXAMPLE.read_text())
    config["scopes"]["project001-dev"]["tenant_id"] = "11111111-1111-4111-8111-111111111111"
    config["scopes"]["project001-dev"]["subscription_id"] = "22222222-2222-4222-8222-222222222222"
    config["scopes"]["project001-dev"]["resource_group"] = "another-dev-rg"
    config["azure"]["project_endpoint"] = "https://another.services.ai.azure.com/api/projects/project"
    loaded = Settings.model_validate(config)
    assert loaded.tenant_id == "11111111-1111-4111-8111-111111111111"
    assert loaded.scopes["project001-dev"].resource_group == "another-dev-rg"


def test_relative_repository_root_is_config_relative():
    settings = load_settings(EXAMPLE)
    assert (settings.knowledge.repository_root / "RELEASE_125.md").is_file()


def test_unknown_scope_grant_rejected():
    config = json.loads(EXAMPLE.read_text())
    config["auth"]["grants"][0]["scopes"] = ["other-project"]
    with pytest.raises(ValidationError):
        Settings.model_validate(config)


def test_non_https_credentials_endpoint_rejected():
    config = json.loads(EXAMPLE.read_text())
    config["azure"]["search_endpoint"] = "https://user:password@example.com"
    with pytest.raises(ValidationError):
        Settings.model_validate(config)


def test_tool_schema_cannot_receive_shell_or_scope_override():
    assert function("read", "Read")["parameters"]["additionalProperties"] is False
    assert all("scope" not in tool["parameters"]["properties"] for tool in knowledge_tools())


def test_retrieval_query_preserves_valid_unicode_within_embedding_cap():
    settings = load_settings(EXAMPLE)
    question = "\U0001f642" * 4000
    limited = retrieval_query(question, settings)
    assert len(limited.encode("utf-8")) <= settings.knowledge.max_embedding_tokens
    assert len(limited) <= 4000
    assert limited in question
