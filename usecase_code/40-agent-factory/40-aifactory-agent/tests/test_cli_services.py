from pathlib import Path
from unittest.mock import Mock

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
