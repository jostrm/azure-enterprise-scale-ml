"""Meeting-only native profile: real routing and grounded turns, fake external services."""
from dataclasses import replace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import anyio
import pytest
from fastapi.testclient import TestClient

from aifactory_agent import security, teams_meeting_routes as meetings, voice_routes
from aifactory_agent.teams_meeting_settings import TeamsMeetingSettings
from aifactory_agent.voice import VoiceAnswerError, VoiceSession
from aifactory_agent.voice_delegated import DelegatedVoiceSession, TranscriptDelegatedVoiceSession
from aifactory_agent.voice_realtime import RealtimeVoiceSession
from test_conversation import FakeKnowledge, injected
from test_teams_meeting_routes import TokenService, create, reset_voice
from test_teams_meeting_settings import HOST, LISTENER, enabled_config, external_policy
from test_voice_routes import GOOD, FakeGateway, build, collect, ended, finish, got, hello, make_settings
from voice_fakes import PCM, ReactiveUpstream


class GroundedUpstream(ReactiveUpstream):
    async def send(self, event):
        await super().send(event)
        if event["type"] == "conversation.item.create":
            self.push({"type": "conversation.item.created", "item": event["item"]})
        elif event["type"] == "conversation.item.delete":
            self.push({"type": "conversation.item.deleted", "item_id": event["item_id"]})

    def push(self, event):
        if event["type"] == "response.done":
            event["response"]["output"] = [{
                "id": event["response"]["id"] + "-output", "type": "message", "role": "assistant",
                "content": [{"type": "audio", "transcript": "Grounded meeting reply [S1]."}],
            }]
        super().push(event)


class GroundedGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.settings = []

    async def connect(self, settings):
        self.settings.append(settings)
        upstream = GroundedUpstream()
        self.upstreams.append(upstream)
        return upstream


def profile_app(*, mode="inherit", full_duplex=False, voice=None, knowledge=None, **meeting):
    settings = make_settings(**(voice or {
        "mode": "delegated", "delegation_trigger": "transcript", "model": "gpt-realtime-mini",
        "voice_name": "coral", "voice_type": "openai", "turn_detection": "server_vad",
    }))
    settings = settings.model_copy(update={"teams_meetings": TeamsMeetingSettings.model_validate(
        enabled_config(voice_mode=mode, full_duplex=full_duplex, **meeting))})
    harness = injected(settings, knowledge=knowledge)
    app = build(settings, harness.conversation, GroundedGateway())
    app.state.teams_meeting_token_service = TokenService()
    return app, harness


def admit(app, body):
    return meetings.consume_meeting_session(
        app, app.state.services.authenticate(GOOD), body["meeting_session"], "project001-dev", "project")


def change_meeting(app, **changes):
    current = app.state.settings
    values = current.teams_meetings.model_dump()
    app.state.settings = current.model_copy(update={
        "teams_meetings": TeamsMeetingSettings.model_validate({**values, **changes}),
    })


@pytest.mark.parametrize("profile,browser_mode,full_duplex", [
    ("inherit", "speech_shell", False), ("inherit", "delegated", False),
    ("inherit", "realtime", True), ("realtime", "delegated", True),
    ("realtime", "delegated", False),
])
def test_authenticated_status_explains_effective_profile_without_admitting_a_session(profile, browser_mode, full_duplex):
    app, _ = profile_app(mode=profile, full_duplex=full_duplex, voice={
        "mode": browser_mode, "model": "gpt-4.1-nano" if browser_mode == "speech_shell" else "gpt-realtime-mini",
    })
    with TestClient(app) as client:
        assert client.get("/api/teams-meetings/status").status_code == 401
        response = client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        status = response.json()
        assert status["voice_mode"] == (browser_mode if profile == "inherit" else profile)
        assert status["full_duplex"] is full_duplex
        assert not app.state.teams_meeting_registry.sessions
        assert not app.state.teams_meeting_token_service.issued
        assert not app.state.voice_gateway.upstreams
        admission = create(client).json()
        assert admission["voice_mode"] == status["voice_mode"]
        assert admission["full_duplex"] is status["full_duplex"]
        entry = app.state.teams_meeting_registry.sessions[admission["session_id"]]
        assert admission["voice_generation"] == entry.generation == 0
        assert entry.voice_mode == profile and entry.full_duplex is full_duplex


@pytest.mark.parametrize("mode,trigger,model", [
    ("speech_shell", "model_tool", "gpt-4.1-nano"),
    ("delegated", "transcript", "gpt-realtime-mini"),
    ("delegated", "model_tool", "gpt-realtime"),
    ("realtime", "model_tool", "gpt-realtime-datazone"),
])
def test_inherit_preserves_exact_language_resolved_browser_voice(mode, trigger, model):
    app, _ = profile_app(voice={"mode": mode, "delegation_trigger": trigger, "model": model})
    with TestClient(app) as client:
        body = create(client).json()
        assert body["voice_mode"] == mode and body["full_duplex"] is False
        principal = admit(app, body)
        selected = app.state.settings.voice.for_language(None)
        assert meetings.meeting_voice_settings(app, principal, selected) is selected
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        assert entry.voice_mode == "inherit" and entry.full_duplex is False


@pytest.mark.parametrize("mode,trigger,session_class", [
    ("speech_shell", "model_tool", VoiceSession),
    ("delegated", "transcript", TranscriptDelegatedVoiceSession),
    ("delegated", "model_tool", DelegatedVoiceSession),
    ("realtime", "model_tool", RealtimeVoiceSession),
])
def test_inherited_meeting_dispatches_the_existing_session_class(mode, trigger, session_class, monkeypatch):
    app, _ = profile_app(voice={
        "mode": mode, "delegation_trigger": trigger,
        "model": "gpt-4.1-nano" if mode == "speech_shell" else "gpt-realtime-mini",
    })
    constructor = Mock(wraps=session_class)
    monkeypatch.setattr(voice_routes, session_class.__name__, constructor)
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            assert constructor.call_count == 1
            selected = constructor.call_args.args[0]
            assert selected.mode == mode and selected.delegation_trigger == trigger
            finish(socket)


@pytest.mark.parametrize("trigger", ["transcript", "model_tool"])
def test_native_profile_only_changes_validated_mode_and_trigger_after_language_resolution(trigger):
    app, _ = profile_app(mode="realtime", full_duplex=True, voice={
        "mode": "delegated", "delegation_trigger": trigger, "model": "gpt-realtime-mini",
        "endpoint": "https://meeting-test.services.ai.azure.com", "silence_duration_ms": 700,
        "max_session_seconds": 700, "idle_timeout_seconds": 90, "answer_timeout_seconds": 80,
        "language_profiles": {
            "en-US": {"voice_name": "en-US-Ava:DragonHDLatestNeural"},
            "sv-SE": {"voice_name": "sv-SE-SofieNeural"},
        },
    })
    original = app.state.settings.model_dump()
    with TestClient(app) as client:
        body = create(client).json()
        assert body["voice_mode"] == "realtime" and body["full_duplex"] is True
        principal = admit(app, body)
        selected = app.state.settings.voice.for_language("sv-SE")
        result = meetings.meeting_voice_settings(app, principal, selected)
        assert result.model_dump() == {**selected.model_dump(), "mode": "realtime", "delegation_trigger": "model_tool"}
        assert app.state.settings.model_dump() == original
        host = app.state.services.authenticate(GOOD)
        with pytest.raises(PermissionError):
            meetings.meeting_voice_settings(app, host, selected)
        with pytest.raises(PermissionError):
            meetings.meeting_voice_settings(app, replace(principal, meeting_generation=99), selected)


@pytest.mark.parametrize("trigger", ["transcript", "model_tool"])
def test_native_meeting_route_uses_shared_prepare_without_external_answer_and_browser_stays_delegated(trigger, monkeypatch):
    app, harness = profile_app(mode="realtime", full_duplex=True, voice={
        "mode": "delegated", "delegation_trigger": trigger, "model": "gpt-realtime-mini",
        "voice_name": "coral", "voice_type": "openai", "max_session_seconds": 600,
        "language_profiles": {
            "en-US": {"voice_name": "coral", "voice_type": "openai"},
            "sv-SE": {"voice_name": "sage", "voice_type": "openai"},
        },
    })
    original = app.state.settings
    prepare = Mock(wraps=harness.conversation.prepare)
    monkeypatch.setattr(harness.conversation, "prepare", prepare)
    constructors = {}
    for kind in (RealtimeVoiceSession, DelegatedVoiceSession, TranscriptDelegatedVoiceSession):
        constructors[kind] = Mock(wraps=kind)
        monkeypatch.setattr(voice_routes, kind.__name__, constructors[kind])
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"], language="sv-SE"))
            ready = collect(socket, got("ready"))[-1]
            assert ready["voice"]["name"] == "sage" and ready["voice"]["languages"] == ["sv-SE"]
            socket.send_bytes(PCM)
            seen = collect(socket, got("answer"))
            assert any("audio" in frame for frame in seen)
            assert seen[-1]["citation_validation"] == "passed"
            assert seen[-1]["citations"][0]["citation_id"] == "S1"
            assert prepare.call_count == 1 and not harness.gateway.sessions
            principal = prepare.call_args.args[2]
            assert principal.authorization_context == "teams_meeting"
            assert principal.permission_ceiling == frozenset({"knowledge.read"})
            assert principal.scope_ceiling == frozenset({"project001-dev"})
            for permission in ("factory.read", "cost.read", "graph.read", "factory.write"):
                with pytest.raises(PermissionError):
                    security.authorize(app.state.settings, principal, "project001-dev", permission)
            with pytest.raises(PermissionError):
                security.authorize(app.state.settings, principal, "project002-dev", "knowledge.read")
            native = constructors[RealtimeVoiceSession]
            assert native.call_count == 1
            assert 0 < native.call_args.kwargs["max_duration"] <= 600
            assert native.call_args.kwargs["max_tool_rounds"] == original.max_tool_rounds
            configured = app.state.voice_gateway.upstreams[0].of("session.update")[0]["session"]
            assert configured["turn_detection"]["create_response"] is False
            assert configured["turn_detection"]["interrupt_response"] is False
            assert configured["turn_detection"]["silence_duration_ms"] == original.voice.silence_duration_ms
            finish(socket)
        assert app.state.settings is original
        assert app.state.voice_gateway.upstreams[0].closed
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello())
            collect(socket, got("ready"))
            expected = TranscriptDelegatedVoiceSession if trigger == "transcript" else DelegatedVoiceSession
            assert constructors[expected].call_count == 1
            selected = constructors[expected].call_args.args[0]
            assert selected.mode == "delegated" and selected.delegation_trigger == trigger
            finish(socket)
        status = client.get("/api/voice/status", headers={"Authorization": "Bearer " + GOOD}).json()
        assert status["mode"] == "delegated" and status["delegation_trigger"] == trigger
        typed = client.post("/api/chat", headers={"Authorization": "Bearer " + GOOD}, json={
            "question": "Typed question", "scope_key": "project001-dev", "audience": "project",
        })
        assert typed.status_code == 200 and len(harness.gateway.sessions) == 1


def test_incompatible_native_model_fails_closed_before_upstream_without_affecting_browser():
    app, _ = profile_app(mode="realtime", voice={"mode": "speech_shell", "model": "gpt-4.1-nano"})
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            seen = collect(socket, ended)
            assert seen[0]["code"] == "voice_unavailable" and seen[-1]["closed"] == 1011
            assert not app.state.voice_gateway.upstreams
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        assert app.state.voice_registry.active == 0 and app.state.voice_pre_auth == 0
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello())
            collect(socket, got("ready"))
            finish(socket)
        assert app.state.settings.voice.model == "gpt-4.1-nano"


@pytest.mark.parametrize("initial,change", [
    ({}, {"voice_mode": "realtime"}),
    ({"mode": "realtime"}, {"voice_mode": "inherit"}),
    ({}, {"full_duplex": True}),
    ({"full_duplex": True}, {"full_duplex": False}),
])
def test_profile_or_duplex_change_invalidates_principal_prepared_turn_and_reset(initial, change):
    app, harness = profile_app(**initial)
    with TestClient(app) as client:
        body = create(client).json()
        principal = admit(app, body)
        prepare, execute = voice_routes._native_handlers(app, principal, "project001-dev", "project")
        prepared = anyio.run(prepare, "Explain setup")
        change_meeting(app, **change)
        for operation in (
            lambda: security.authorize(app.state.settings, principal, "project001-dev", "knowledge.read"),
            lambda: meetings.meeting_session_seconds(app, principal),
            lambda: meetings.meeting_voice_settings(app, principal, app.state.settings.voice),
            lambda: prepared.finish("Grounded [S1].", "after-change"),
        ):
            with pytest.raises(PermissionError):
                operation()
        with pytest.raises(VoiceAnswerError):
            anyio.run(execute, prepared, "knowledge_search", "call-1", {"query": "setup"})
        assert reset_voice(client, body["session_id"]).status_code == 403
        assert not harness.gateway.sessions


@pytest.mark.parametrize("change", [{"voice_mode": "realtime"}, {"full_duplex": True}])
def test_profile_change_during_identity_issue_reclaims_without_admitting(change):
    app, _ = profile_app()
    issue = app.state.teams_meeting_token_service.issue

    def raced():
        identity = issue()
        change_meeting(app, **change)
        return identity

    app.state.teams_meeting_token_service.issue = raced
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions


def test_reclamation_pins_original_profile_and_duplex_even_when_cleanup_needs_retry():
    app, _ = profile_app(mode="realtime", full_duplex=True)
    service = app.state.teams_meeting_token_service
    issue, revoke = service.issue, service.revoke

    def raced():
        identity = issue()
        change_meeting(app, voice_mode="inherit", full_duplex=False)
        return identity

    service.issue = raced
    service.revoke = Mock(side_effect=meetings.TokenServiceError("acs_delete_failed", "ServiceRequestError"))
    with TestClient(app) as client:
        assert create(client).status_code == 403
        entry, = app.state.teams_meeting_registry.sessions.values()
        assert entry.revoked and entry.voice_mode == "realtime" and entry.full_duplex is True
        assert entry.allowed_participant_object_ids == frozenset({HOST, LISTENER})
        service.revoke = revoke
        response = client.delete("/api/teams-meetings/sessions/" + entry.id,
                                 headers={"Authorization": "Bearer " + GOOD})
        assert response.status_code == 204 and service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions


def test_native_profile_survives_authorized_voice_reset_without_extending_lifetime():
    app, _ = profile_app(mode="realtime", full_duplex=True)
    with TestClient(app) as client:
        body = create(client).json()
        principal = admit(app, body)
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        identity, expiry = entry.identity, entry.expires_at
        voice = AsyncMock()
        meetings.bind_meeting_voice_session(app, principal, voice)
        response = reset_voice(client, entry.id)
        assert response.status_code == 200
        rotated = response.json()
        assert entry.voice_mode == "realtime" and entry.full_duplex is True
        assert entry.identity is identity and entry.expires_at == expiry
        current = admit(app, rotated)
        selected = meetings.meeting_voice_settings(app, current, app.state.settings.voice.for_language(None))
        assert selected.mode == "realtime" and selected.delegation_trigger == "model_tool"
        with pytest.raises(PermissionError):
            meetings.meeting_voice_settings(app, principal, selected)
        voice.end.assert_awaited_once_with("meeting_voice_reset")


@pytest.mark.parametrize("external,change", [
    (False, "listener"), (False, "host"), (False, "tenant"), (False, "roster"),
    (True, "host"), (True, "tenant"), (True, "approval"), (True, "roster"),
])
def test_native_profile_preserves_live_tenant_grant_and_disclosure_guards(external, change):
    app, harness = profile_app(mode="realtime", full_duplex=True,
                              **({"policies": [external_policy()]} if external else {}))
    with TestClient(app) as client:
        body = create(client).json()
        principal = admit(app, body)
        original = app.state.settings
        prepare, execute = voice_routes._native_handlers(app, principal, "project001-dev", "project")
        prepared = anyio.run(prepare, "Explain setup")
        assert {tool["name"] for tool in prepared.tools} == {"knowledge_search", "knowledge_status"}
        with pytest.raises(VoiceAnswerError):
            anyio.run(execute, prepared, "factory_health", "blocked", "{}")
        assert not harness.tools.executions
        if change in {"host", "listener"}:
            removed = HOST if change == "host" else LISTENER
            app.state.settings = original.model_copy(update={"auth": original.auth.model_copy(update={
                "grants": [grant for grant in original.auth.grants if str(grant.object_id) != removed],
            })})
        else:
            policy = original.teams_meetings.policies[0]
            edits = {
                "tenant": {"meeting_tenant_id": UUID("99999999-9999-4999-8999-999999999999")},
                "approval": {"external_audience_disclosure_approved": False},
                "roster": {"allowed_participant_object_ids": policy.allowed_participant_object_ids[:1]},
            }
            change_meeting(app, policies=[policy.model_copy(update=edits[change]).model_dump()])
        for operation in (
            lambda: security.authorize(original, principal, "project001-dev", "knowledge.read"),
            lambda: meetings.meeting_voice_settings(app, principal, original.voice),
            lambda: prepared.finish("Grounded [S1].", "after-revocation"),
        ):
            with pytest.raises(PermissionError):
                operation()
        with pytest.raises(VoiceAnswerError):
            anyio.run(execute, prepared, "knowledge_status", "after-revocation", "{}")
        assert reset_voice(client, body["session_id"]).status_code == 403
        assert not harness.gateway.sessions


@pytest.mark.parametrize("field,value", [
    ("voice_mode", "realtime"), ("full_duplex", True), ("mode", "realtime"),
    ("delegation_trigger", "model_tool"), ("model", "gpt-realtime"),
])
def test_client_cannot_select_profile_in_admission_or_hello(field, value):
    app, _ = profile_app()
    with TestClient(app) as client:
        assert create(client, **{field: value}).status_code == 422
        assert not app.state.teams_meeting_token_service.issued
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"], **{field: value}))
            assert collect(socket, got("error"))[-1]["code"] == "invalid_hello"
        assert not app.state.voice_gateway.upstreams
        assert not app.state.teams_meeting_registry.sessions[body["session_id"]].consumed


def test_native_profile_keeps_grounding_failure_closed_without_fallback():
    app, harness = profile_app(mode="realtime", knowledge=FakeKnowledge(status={"status": "blocked"}))
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            seen = collect(socket, got("error"))
            assert not any("audio" in frame for frame in seen)
            assert not app.state.voice_gateway.upstreams[0].of("response.create")
            assert not harness.gateway.sessions
            finish(socket)


def test_policy_change_while_connecting_closes_upstream_and_reclaims_identity():
    app, _ = profile_app(mode="realtime")
    gateway = app.state.voice_gateway
    connect = gateway.connect

    async def raced(settings):
        upstream = await connect(settings)
        change_meeting(app, full_duplex=True)
        return upstream

    gateway.connect = raced
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            assert collect(socket, ended)[0]["code"] == "forbidden"
        assert gateway.upstreams[0].closed
        assert not gateway.upstreams[0].sent
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.voice_registry.active == 0
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
