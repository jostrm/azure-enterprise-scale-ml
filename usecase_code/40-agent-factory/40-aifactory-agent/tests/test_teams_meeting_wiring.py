import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aifactory_agent.config import Settings
from test_teams_meeting_routes import app_for_meetings
from test_teams_meeting_settings import enabled_config
from test_voice_routes import GOOD, Conversation, FakeGateway, build, make_settings


def test_default_disabled_has_no_meeting_routes_registry_or_acs_csp():
    app = build(make_settings(), Conversation(), FakeGateway())
    with TestClient(app) as client:
        assert client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD}).status_code == 404
        assert client.post("/api/teams-meetings/sessions", json={}).status_code == 404
        policy = client.get("/").headers["content-security-policy"]
        assert "connect-src 'self' https://login.microsoftonline.com;" in policy
        assert "worker-src" not in policy and "media-src" not in policy
    assert not hasattr(app.state, "teams_meeting_registry")


def test_enabled_csp_uses_only_exact_reviewed_origins_and_remains_unframeable():
    app = app_for_meetings()
    with TestClient(app) as client:
        policy = client.get("/").headers["content-security-policy"]
        directives = {parts[0]: parts[1:] for raw in policy.split(";") if (parts := raw.split())}
        assert directives["connect-src"] == [
            "'self'", "https://login.microsoftonline.com", "https://calling.example.com", "wss://calling.example.com",
        ]
        assert directives["worker-src"] == ["'self'", "blob:"]
        assert directives["media-src"] == ["'self'", "blob:"]
        assert directives["frame-ancestors"] == ["'none'"]
        assert directives["object-src"] == ["'none'"]
        assert "https:" not in directives["script-src"] and "*" not in policy


def test_meetings_require_voice_and_known_scope_without_changing_auth_clients():
    config = make_settings().model_dump(mode="json")
    config["teams_meetings"] = enabled_config()
    validated = Settings.model_validate(config)
    assert validated.auth == make_settings().auth
    config["voice"]["enabled"] = False
    with pytest.raises(ValidationError, match="live voice relay"):
        Settings.model_validate(config)
    config["voice"]["enabled"] = True
    config["teams_meetings"]["policies"][0]["scope_key"] = "not-configured"
    with pytest.raises(ValidationError, match="unknown application scope"):
        Settings.model_validate(config)
    assert "teams_client_id" not in type(validated.auth).model_fields
