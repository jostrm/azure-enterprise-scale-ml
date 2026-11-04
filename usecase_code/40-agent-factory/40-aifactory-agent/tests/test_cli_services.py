from pathlib import Path
from unittest.mock import Mock

import pytest

from aifactory_agent.__main__ import main
from aifactory_agent.config import load_settings
from aifactory_agent.services import AgentDependencies, AgentServices
from aifactory_agent.security import Principal


def test_operator_cli_uses_injected_conversation_and_requester(capsys):
    path = Path(__file__).parents[1] / "config.example.json"
    settings = load_settings(path)
    knowledge, conversation = Mock(), Mock()
    conversation.answer.return_value = {"answer": "test-only"}
    caller = Principal(settings.tenant_id, settings.auth.grants[0].object_id)
    services = AgentServices(settings, dependencies=AgentDependencies(
        knowledge_factory=Mock(return_value=knowledge),
        conversation_factory=Mock(return_value=conversation),
    ))
    main(["--config", str(path), "ask", "--scope", "project001-dev",
          "--audience", "platform", "--question", "Question"],
         services=services, principal_provider=lambda configured: caller)
    conversation.answer.assert_called_once_with("Question", "platform", caller, "project001-dev")
    assert '"answer": "test-only"' in capsys.readouterr().out


@pytest.mark.parametrize("status,expected_exit", [
    ("ready", 0), ("blocked", 1), ("empty", 1), ("failed", 1),
])
def test_ingest_exit_status_reports_whether_knowledge_is_ready(capsys, status, expected_exit):
    path = Path(__file__).parents[1] / "config.example.json"
    settings = load_settings(path)
    knowledge = Mock()
    knowledge.refresh.return_value = {"status": status, "indexed_document_count": 3}
    services = AgentServices(settings, dependencies=AgentDependencies(
        knowledge_factory=Mock(return_value=knowledge),
    ))
    assert main(["--config", str(path), "ingest"], services=services) == expected_exit
    knowledge.ensure_resources.assert_called_once()
    knowledge.refresh.assert_called_once()
    assert f'"status": "{status}"' in capsys.readouterr().out
