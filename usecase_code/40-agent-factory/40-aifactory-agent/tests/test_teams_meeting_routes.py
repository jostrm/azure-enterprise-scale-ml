import asyncio
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlencode
from uuid import UUID

import pytest
from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError
from fastapi.testclient import TestClient

from aifactory_agent import security
from aifactory_agent.teams_meeting_routes import (
    AcsTokenService, JoinRequest, MeetingIdentity, TokenServiceError, _issue_identity, _reclaim_identity,
    bind_meeting_voice_session, constrain_meeting_principal,
    consume_meeting_session, end_meeting_session, meeting_session_seconds,
    register_teams_meetings,
)
from aifactory_agent.teams_meeting_settings import TeamsMeetingSettings
from test_teams_meeting_settings import (
    EXTERNAL_LISTENERS, EXTERNAL_TENANT, HOST, URL, enabled_config, external_policy,
)
from test_voice_routes import (
    GOOD, OTHER, PCM, Conversation, FakeGateway, build, collect, ended, finish, got, hello, make_settings, states,
)


class TokenService:
    def __init__(self):
        self.issued = []
        self.deleted = []

    def issue(self):
        identity = MeetingIdentity(f"user-{len(self.issued)}", "acs-secret", time.time() + 3600)
        self.issued.append(identity)
        return identity

    def revoke(self, identity):
        self.deleted.append(identity.user_id)

    def close(self):
        pass


def app_for_meetings(**changes):
    meeting = TeamsMeetingSettings.model_validate(enabled_config(**changes))
    settings = make_settings().model_copy(update={"teams_meetings": meeting})
    conversation = Conversation()
    app = build(settings, conversation, FakeGateway())
    app.state.test_meeting_conversation = conversation
    if not hasattr(app.state, "teams_meeting_registry"):
        register_teams_meetings(app)
    app.state.teams_meeting_token_service = TokenService()
    return app


def request_body(**changes):
    return {"meeting_url": URL, "scope_key": "project001-dev", "audience": "project",
            "consent_acknowledged": True, **changes}


def create(client, token=GOOD, **changes):
    return client.post("/api/teams-meetings/sessions", json=request_body(**changes),
                       headers={"Authorization": "Bearer " + token})


def reset_voice(client, session_id, generation=0, token=GOOD, **extra):
    return client.post("/api/teams-meetings/sessions/" + session_id + "/voice-reset",
                       json={"voice_generation": generation, **extra},
                       headers={"Authorization": "Bearer " + token})


def long_meeting_url(tenant):
    return ("https://teams.microsoft.com/l/meetup-join/19%3ameeting_approved%40thread.v2/0?"
            + urlencode({"context": json.dumps({"Tid": tenant})}))


@pytest.mark.parametrize("long_url", [False, True])
def test_external_disclosure_admits_only_exact_policy_and_returns_effective_tenant_metadata(long_url):
    url = long_meeting_url(EXTERNAL_TENANT) if long_url else URL
    app = app_for_meetings(policies=[external_policy(meeting_url=url)])
    original_auth = app.state.settings.auth.model_dump(mode="json")
    with TestClient(app) as client:
        assert create(client, meeting_url=url + "&other=meeting").status_code == 403
        response = create(client, meeting_url=url)
        assert response.status_code == 201
        body = response.json()
        assert body["meeting_tenant_id"] == EXTERNAL_TENANT
        assert body["external_audience_disclosure_approved"] is True
        assert body["allowed_participant_object_ids"] == EXTERNAL_LISTENERS
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        assert entry.meeting_tenant_id == EXTERNAL_TENANT
        assert entry.external_audience_disclosure_approved is True
        assert entry.allowed_participant_object_ids == frozenset(EXTERNAL_LISTENERS)
        principal = consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                            body["meeting_session"], "project001-dev", "project")
        security.authorize(app.state.settings, principal, "project001-dev", "knowledge.read")
        assert principal.tenant_id == app.state.settings.tenant_id != EXTERNAL_TENANT
        status = client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD})
        assert status.json()["policies"] == [{
            "id": "review", "scope_key": "project001-dev", "meeting_tenant_id": EXTERNAL_TENANT,
            "external_audience_disclosure_approved": True,
        }]
        assert "meeting_url" not in status.text and url not in status.text
        assert status.headers["cache-control"] == "no-store"
        assert app.state.settings.auth.model_dump(mode="json") == original_auth


@pytest.mark.parametrize("explicit_tenant", [False, True])
def test_same_tenant_admission_and_status_report_effective_tenant_without_external_approval(explicit_tenant):
    policy = enabled_config()["policies"][0]
    tenant = make_settings().tenant_id
    if explicit_tenant:
        policy["meeting_tenant_id"] = tenant
    app = app_for_meetings(policies=[policy])
    with TestClient(app) as client:
        body = create(client).json()
        status = client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD}).json()
        for metadata in [body, status["policies"][0]]:
            assert metadata["meeting_tenant_id"] == tenant
            assert metadata["external_audience_disclosure_approved"] is False


@pytest.mark.parametrize("tenant", [None, EXTERNAL_TENANT])
def test_foreign_listener_ids_without_external_disclosure_are_rejected(tenant):
    policy = external_policy(meeting_tenant_id=tenant, external_audience_disclosure_approved=False)
    app = app_for_meetings(policies=[policy])
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD}).json()["policies"] == []
        assert not app.state.teams_meeting_token_service.issued


def test_external_disclosure_flag_is_rejected_for_deployment_tenant_even_with_listener_grants():
    policy = {**enabled_config()["policies"][0], "meeting_tenant_id": make_settings().tenant_id,
              "external_audience_disclosure_approved": True}
    app = app_for_meetings(policies=[policy])
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert not app.state.teams_meeting_token_service.issued


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("context", ["mismatch", "missing", "empty", "duplicate", "invalid", "non_string"])
def test_long_meeting_url_requires_context_tenant_matching_effective_policy(external, context):
    policy = external_policy() if external else enabled_config()["policies"][0]
    tenant = EXTERNAL_TENANT if external else make_settings().tenant_id
    url = long_meeting_url(tenant)
    if context == "mismatch":
        url = long_meeting_url(make_settings().tenant_id if external else EXTERNAL_TENANT)
    elif context == "missing":
        url = url.split("?")[0]
    elif context == "empty":
        url = url.split("?")[0] + "?context="
    elif context == "duplicate":
        url += "&" + url.split("?")[1]
    elif context == "invalid":
        url = url.split("?")[0] + "?context=invalid-json"
    else:
        url = long_meeting_url(123)
    policy["meeting_url"] = url
    app = app_for_meetings(policies=[policy])
    with TestClient(app) as client:
        assert create(client, meeting_url=url).status_code == 403
        assert not app.state.teams_meeting_token_service.issued


def test_same_tenant_long_meeting_url_keeps_existing_listener_authorization():
    url = long_meeting_url(make_settings().tenant_id)
    policy = {**enabled_config()["policies"][0], "meeting_url": url}
    app = app_for_meetings(policies=[policy])
    with TestClient(app) as client:
        assert create(client, meeting_url=url).status_code == 201


@pytest.mark.parametrize("change", ["tenant", "approval"])
def test_external_disclosure_change_during_identity_issue_reclaims_without_admitting(change):
    app = app_for_meetings(policies=[external_policy()])
    issue = app.state.teams_meeting_token_service.issue

    def raced():
        identity = issue()
        current = app.state.settings
        policy = current.teams_meetings.policies[0].model_copy(update=(
            {"meeting_tenant_id": UUID("99999999-9999-4999-8999-999999999999")} if change == "tenant"
            else {"external_audience_disclosure_approved": False}))
        app.state.settings = current.model_copy(update={"teams_meetings": current.teams_meetings.model_copy(
            update={"policies": [policy]})})
        return identity

    app.state.teams_meeting_token_service.issue = raced
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions


@pytest.mark.parametrize("external", [False, True])
def test_voice_reset_rotates_ticket_and_generation_without_extending_identity_or_duration(external):
    app = app_for_meetings(**({"policies": [external_policy()]} if external else {}))
    with TestClient(app) as client:
        body = create(client).json()
        assert body["voice_generation"] == 0
        host = app.state.services.authenticate(GOOD)
        principal = consume_meeting_session(app, host, body["meeting_session"], "project001-dev", "project")
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        identity, expiry, timer = entry.identity, entry.expires_at, entry.timer
        voice = AsyncMock()
        bind_meeting_voice_session(app, principal, voice)
        response = reset_voice(client, entry.id)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        rotated = response.json()
        assert set(rotated) == {"session_id", "meeting_session", "voice_generation"}
        assert rotated["session_id"] == entry.id and rotated["voice_generation"] == 1
        assert rotated["meeting_session"] != body["meeting_session"]
        assert entry.generation == 1 and not entry.consumed and entry.voice_session is None
        assert entry.identity is identity and entry.expires_at == expiry and entry.timer is timer
        assert len(app.state.teams_meeting_token_service.issued) == 1
        assert app.state.teams_meeting_token_service.deleted == []
        voice.end.assert_awaited_once_with("meeting_voice_reset")
        for operation in (
            lambda: security.authorize(app.state.settings, principal, "project001-dev", "knowledge.read"),
            lambda: meeting_session_seconds(app, principal),
            lambda: bind_meeting_voice_session(app, principal, AsyncMock()),
            lambda: consume_meeting_session(app, host, body["meeting_session"], "project001-dev", "project"),
        ):
            with pytest.raises(PermissionError):
                operation()
        current = consume_meeting_session(app, host, rotated["meeting_session"], "project001-dev", "project")
        assert current.meeting_generation == 1
        security.authorize(app.state.settings, current, "project001-dev", "knowledge.read")
        assert 0 < meeting_session_seconds(app, current) <= 900
        with pytest.raises(PermissionError):
            consume_meeting_session(app, host, rotated["meeting_session"], "project001-dev", "project")


@pytest.mark.parametrize("consumed", [False, True])
def test_stale_generation_cleanup_cannot_revoke_rotated_meeting(consumed):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        if consumed:
            consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                    body["meeting_session"], "project001-dev", "project")
        rotated = reset_voice(client, body["session_id"]).json()
        assert rotated.get("voice_generation") == 1
        assert client.portal.call(
            lambda: end_meeting_session(app, body["session_id"], expected_generation=0)) == "complete"
        assert body["session_id"] in app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == []
        assert client.delete("/api/teams-meetings/sessions/" + body["session_id"],
                             headers={"Authorization": "Bearer " + GOOD}).status_code == 204
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


@pytest.mark.parametrize("body", [
    {}, {"voice_generation": -1}, {"voice_generation": True}, {"voice_generation": "0"},
    {"voice_generation": 0.0}, {"voice_generation": 0, "scope_key": "other"},
    {"voice_generation": 0, "meeting_session": "caller-selected-ticket"},
])
def test_voice_reset_body_is_strict_and_server_selects_everything_else(body):
    app = app_for_meetings()
    with TestClient(app) as client:
        session = create(client).json()
        response = client.post("/api/teams-meetings/sessions/" + session["session_id"] + "/voice-reset",
                               json=body, headers={"Authorization": "Bearer " + GOOD})
        assert response.status_code == 422
        entry = app.state.teams_meeting_registry.sessions[session["session_id"]]
        assert not entry.consumed
        consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                session["meeting_session"], "project001-dev", "project")


def test_voice_reset_is_authenticated_host_owned_and_stale_or_future_generation_is_conflict():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        session_id = body["session_id"]
        assert reset_voice(client, session_id, token="invalid-token").status_code == 401
        assert reset_voice(client, session_id, token=OTHER).status_code == 403
        assert reset_voice(client, session_id, generation=1).status_code == 409
        assert reset_voice(client, session_id).status_code == 200
        assert reset_voice(client, session_id).status_code == 409
        assert reset_voice(client, session_id, generation=2).status_code == 409
        assert reset_voice(client, session_id, generation=1).json()["voice_generation"] == 2
        assert reset_voice(client, "unknown-session").status_code == 404


def test_failed_old_voice_stop_during_reset_invalidates_entire_meeting_and_propagates(caplog):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        principal = consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                            body["meeting_session"], "project001-dev", "project")
        voice = AsyncMock()
        voice.end.side_effect = RuntimeError("PRIVATE provider detail")
        bind_meeting_voice_session(app, principal, voice)
        with pytest.raises(RuntimeError, match="PRIVATE provider detail"):
            reset_voice(client, body["session_id"])
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, principal, "project001-dev", "knowledge.read")
    assert "PRIVATE provider detail" not in caplog.text


def test_reset_in_progress_rejects_another_rotation_and_keeps_new_ticket_unusable():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        principal = consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                            body["meeting_session"], "project001-dev", "project")
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        entered, release = threading.Event(), threading.Event()

        async def stop(_):
            entered.set()
            await asyncio.to_thread(release.wait, 5)

        bind_meeting_voice_session(app, principal, SimpleNamespace(end=stop))
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            request = pool.submit(reset_voice, client, entry.id)
            try:
                assert entered.wait(5)
                assert reset_voice(client, entry.id).status_code == 409
                assert reset_voice(client, entry.id, generation=1).status_code == 409
                assert entry.generation == 1 and entry.resetting
                with pytest.raises(PermissionError):
                    security.authorize(app.state.settings, principal, "project001-dev", "knowledge.read")
            finally:
                release.set()
            assert request.result(5).status_code == 200
        assert entry.generation == 1 and not entry.resetting
        assert not app.state.teams_meeting_token_service.deleted


def test_cancelled_voice_reset_invalidates_current_generation_and_reclaims_identity():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        principal = consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                            body["meeting_session"], "project001-dev", "project")
        voice = AsyncMock()
        voice.end.side_effect = asyncio.CancelledError
        bind_meeting_voice_session(app, principal, voice)
        route = next(route for route in app.routes if getattr(route, "path", "").endswith("/voice-reset"))

        async def run():
            from aifactory_agent.teams_meeting_routes import VoiceResetRequest
            with pytest.raises(asyncio.CancelledError):
                await route.endpoint(body["session_id"], VoiceResetRequest(voice_generation=0),
                                     app.state.services.authenticate(GOOD))

        client.portal.call(run)
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, principal, "project001-dev", "knowledge.read")


def test_voice_reset_old_websocket_cleanup_preserves_identity_and_uses_fresh_provider():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as old_socket:
            old_socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(old_socket, got("ready"))
            previous = app.state.voice_gateway.upstreams[0]
            previous.utterance_after = 2
            old_socket.send_bytes(PCM)
            old_socket.send_text('{"type":"ping"}')
            collect(old_socket, got("pong"))
            assert previous.appends == 1
            response = reset_voice(client, body["session_id"])
            assert response.status_code == 200
            rotated = response.json()
            tail = collect(old_socket, ended)
            assert {"type": "closed", "reason": "meeting_voice_reset"} in tail
        assert previous.closed
        assert body["session_id"] in app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == []
        with client.websocket_connect("/api/voice/ws") as new_socket:
            new_socket.send_text(hello(meeting_session=rotated["meeting_session"]))
            collect(new_socket, got("ready"))
            current = app.state.voice_gateway.upstreams[1]
            assert current is not previous and current.appends == 0
            current.transcript = "Current input"

            def delayed_provider_events():
                previous.push({"type": "input_audio_buffer.speech_started", "item_id": "old-input"})
                previous.push({"type": "input_audio_buffer.speech_stopped", "item_id": "old-input"})
                previous.push({"type": "conversation.item.input_audio_transcription.completed",
                               "item_id": "old-input", "transcript": "STALE PRE-PAUSE INPUT"})

            client.portal.call(delayed_provider_events)
            new_socket.send_text('{"type":"ping"}')
            assert not any("audio" in frame or frame.get("type") == "transcript"
                           for frame in collect(new_socket, got("pong")))
            assert not app.state.test_meeting_conversation.calls
            new_socket.send_bytes(PCM)
            collect(new_socket, lambda values: states(values)[-2:] == ["speaking", "listening"])
            assert [call[0] for call in app.state.test_meeting_conversation.calls] == ["Current input"]
            finish(new_socket)
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


def test_native_voice_reset_isolates_delayed_provider_input_from_new_generation():
    from test_conversation import injected
    from voice_fakes import ReactiveUpstream

    class NativeUpstream(ReactiveUpstream):
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
                    "content": [{"type": "audio", "transcript": "New native answer [S1]."}],
                }]
            super().push(event)

    class NativeGateway(FakeGateway):
        async def connect(self, settings):
            upstream = NativeUpstream(transcript="Current native input")
            self.upstreams.append(upstream)
            return upstream

    settings = make_settings(mode="realtime", model="gpt-realtime-mini").model_copy(update={
        "teams_meetings": TeamsMeetingSettings.model_validate(enabled_config()),
    })
    harness, gateway = injected(settings), NativeGateway()
    app = build(settings, harness.conversation, gateway)
    app.state.teams_meeting_token_service = TokenService()
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as old_socket:
            old_socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(old_socket, got("ready"))
            previous = gateway.upstreams[0]
            previous.utterance_after = 2
            old_socket.send_bytes(PCM)
            old_socket.send_text('{"type":"ping"}')
            collect(old_socket, got("pong"))
            assert previous.appends == 1
            rotated = reset_voice(client, body["session_id"]).json()
            assert rotated["voice_generation"] == 1
            collect(old_socket, ended)
        assert previous.closed and not app.state.teams_meeting_token_service.deleted
        with client.websocket_connect("/api/voice/ws") as new_socket:
            new_socket.send_text(hello(meeting_session=rotated["meeting_session"]))
            collect(new_socket, got("ready"))

            def late_input():
                previous.push({"type": "input_audio_buffer.speech_started", "item_id": "stale-input"})
                previous.push({"type": "input_audio_buffer.speech_stopped", "item_id": "stale-input"})
                previous.push({"type": "conversation.item.input_audio_transcription.completed",
                               "item_id": "stale-input", "transcript": "STALE NATIVE INPUT"})

            client.portal.call(late_input)
            new_socket.send_text('{"type":"ping"}')
            assert not any("audio" in frame or frame.get("type") == "transcript"
                           for frame in collect(new_socket, got("pong")))
            assert harness.knowledge.searches == []
            new_socket.send_bytes(PCM)
            seen = collect(new_socket, got("answer"))
            assert any("audio" in frame for frame in seen)
            assert harness.knowledge.searches == [("Current native input", "project001-dev")]
            assert harness.gateway.sessions == []
            finish(new_socket)
        assert len(app.state.teams_meeting_token_service.issued) == 1
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


@pytest.mark.parametrize("external", [False, True])
def test_requires_auth_exact_host_policy_and_consent_before_issuing_identity(external):
    app = app_for_meetings(**({"policies": [external_policy()]} if external else {}))
    with TestClient(app) as client:
        assert create(client, token="invalid-token").status_code == 401
        assert create(client, token=OTHER).status_code == 403
        assert create(client, consent_acknowledged=False).status_code == 422
        assert create(client, consent_acknowledged=1).status_code == 422
        assert create(client, meeting_url=URL + "wrong").status_code == 403
        assert create(client, scope_key="platform-dev").status_code == 403
        assert create(client, extra="arbitrary").status_code == 422
        assert not app.state.teams_meeting_token_service.issued


@pytest.mark.parametrize("external", [False, True])
def test_token_is_no_store_single_use_and_bound_to_host_scope_audience(external):
    app = app_for_meetings(**({"policies": [external_policy()]} if external else {}))
    with TestClient(app) as client:
        result = create(client)
        assert result.status_code == 201
        assert result.headers["cache-control"] == "no-store"
        body = result.json()
        assert body["meeting_url"] == URL
        assert body["acs_token"] == "acs-secret"
        assert body["expires_at"] <= body["acs_expires_at"]
        principal = app.state.services.authenticate(GOOD)
        ticket = body["meeting_session"]
        for wrong, scope, audience in [
            (replace(principal, object_id="44444444-4444-4444-8444-444444444444"), "project001-dev", "project"),
            (replace(principal, client_id=EXTERNAL_LISTENERS[0]), "project001-dev", "project"),
            (replace(principal, tenant_id=EXTERNAL_TENANT), "project001-dev", "project"),
            (principal, "platform-dev", "project"),
            (principal, "project001-dev", "platform"),
        ]:
            with pytest.raises(PermissionError):
                consume_meeting_session(app, wrong, ticket, scope, audience)
        restricted = consume_meeting_session(app, principal, ticket, "project001-dev", "project")
        assert restricted.permission_ceiling == frozenset({"knowledge.read"})
        assert restricted.scope_ceiling == frozenset({"project001-dev"})
        assert meeting_session_seconds(app, restricted) <= 900
        security.authorize(app.state.settings, restricted, "project001-dev", "knowledge.read")
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, restricted, "project001-dev", "factory.read")
        with pytest.raises(PermissionError):
            consume_meeting_session(app, principal, ticket, "project001-dev", "project")


def test_end_is_host_bound_and_revokes_identity_and_voice_ticket():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        path = "/api/teams-meetings/sessions/" + body["session_id"]
        assert client.delete(path, headers={"Authorization": "Bearer " + OTHER}).status_code == 403
        assert client.delete(path, headers={"Authorization": "Bearer " + GOOD}).status_code == 204
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        with pytest.raises(PermissionError):
            consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                    body["meeting_session"], "project001-dev", "project")


def test_one_active_session_per_host_and_shutdown_cleans_up():
    app = app_for_meetings()
    with TestClient(app) as client:
        assert create(client).status_code == 201
        assert create(client).status_code == 409
        assert len(app.state.teams_meeting_token_service.issued) == 1
    assert app.state.teams_meeting_token_service.deleted == ["user-0"]


def test_status_discloses_only_policy_approved_for_current_host():
    app = app_for_meetings()
    with TestClient(app) as client:
        result = client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD})
        assert result.status_code == 200 and result.json()["policies"][0]["scope_key"] == "project001-dev"
        result = client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + OTHER})
        assert result.json()["policies"] == []


@pytest.mark.parametrize("change", ["hosts", "policy", "grants", "disabled", "expiry"])
def test_every_authorization_rechecks_live_meeting_policy_and_grants(change):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        principal = app.state.services.authenticate(GOOD)
        restricted = consume_meeting_session(app, principal, body["meeting_session"], "project001-dev", "project")
        current = app.state.settings
        meeting = current.teams_meetings
        if change == "hosts":
            app.state.settings = current.model_copy(update={"teams_meetings": meeting.model_copy(
                update={"allowed_host_object_ids": []})})
        elif change == "policy":
            app.state.settings = current.model_copy(update={"teams_meetings": meeting.model_copy(
                update={"policies": []})})
        elif change == "grants":
            app.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={"grants": []})})
        elif change == "disabled":
            app.state.settings = current.model_copy(update={"teams_meetings": meeting.model_copy(update={"enabled": False})})
        else:
            app.state.teams_meeting_registry.sessions[body["session_id"]].expires_at = time.time() - 1
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, restricted, "project001-dev", "knowledge.read")


def test_revoking_consumed_ticket_denies_next_tool_authorization():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        restricted = consume_meeting_session(
            app, app.state.services.authenticate(GOOD), body["meeting_session"], "project001-dev", "project")
        voice_session = AsyncMock()
        bind_meeting_voice_session(app, restricted, voice_session)
        assert client.delete("/api/teams-meetings/sessions/" + body["session_id"],
                             headers={"Authorization": "Bearer " + GOOD}).status_code == 204
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, restricted, "project001-dev", "knowledge.read")
        voice_session.end.assert_awaited_once_with("meeting_ended")


def test_acs_failure_is_redacted_and_releases_admission_reservation(caplog):
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    with TestClient(app) as client:
        issue = service.issue

        def broken():
            raise TokenServiceError("acs_issue_failed", "ServiceRequestError")

        service.issue = broken
        response = create(client)
        assert response.status_code == 503
        assert "SECRET" not in response.text and "acs-sensitive" not in response.text
        assert not app.state.teams_meeting_registry.pending
        assert "acs_issue_failed" in caplog.text
        service.issue = issue
        assert create(client).status_code == 201


def test_policy_revocation_during_acs_creation_revokes_new_identity():
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    issue = service.issue

    def raced():
        result = issue()
        app.state.settings = app.state.settings.model_copy(update={
            "teams_meetings": app.state.settings.teams_meetings.model_copy(update={"enabled": False})})
        return result

    service.issue = raced
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions


def test_failed_identity_deletion_keeps_session_revoked_and_bounded(caplog):
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    with TestClient(app) as client:
        body = create(client).json()
        restricted = consume_meeting_session(
            app, app.state.services.authenticate(GOOD), body["meeting_session"], "project001-dev", "project")
        revoke = service.revoke
        service.revoke = lambda identity: (_ for _ in ()).throw(TokenServiceError("acs_delete_failed", "ServiceRequestError"))
        response = client.delete("/api/teams-meetings/sessions/" + body["session_id"],
                                 headers={"Authorization": "Bearer " + GOOD})
        assert response.status_code == 202
        assert response.json() == {"relay_invalidated": True, "acs_cleanup": "pending"}
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        assert entry.revoked and entry.timer is not None and not entry.cleaning
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, restricted, "project001-dev", "knowledge.read")
        assert create(client).status_code == 409
        assert "acs_delete_failed" in caplog.text and "acs-secret" not in caplog.text and URL not in caplog.text
        service.revoke = revoke
    assert service.deleted == ["user-0"]


def test_cancelled_admission_reclaims_identity_created_by_background_thread():
    service = TokenService()
    entered, release = threading.Event(), threading.Event()
    issue = service.issue

    def blocked_issue():
        entered.set()
        assert release.wait(5)
        return issue()

    service.issue = blocked_issue

    async def run():
        async def reclaim(identity):
            service.revoke(identity)

        pending = asyncio.create_task(_issue_identity(service, reclaim))
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(run())
    assert service.deleted == ["user-0"]


def test_repeated_cancellation_cannot_abandon_an_identity_still_being_created():
    service = TokenService()
    entered, release = threading.Event(), threading.Event()
    issue = service.issue

    def blocked_issue():
        entered.set()
        assert release.wait(5)
        return issue()

    service.issue = blocked_issue

    async def run():
        async def reclaim(identity):
            service.revoke(identity)

        pending = asyncio.create_task(_issue_identity(service, reclaim))
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(run())
    assert service.deleted == ["user-0"]


def test_shared_voice_relay_receives_only_restricted_meeting_principal_and_cleans_up(caplog):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            seen = collect(socket, lambda values: states(values)[-2:] == ["speaking", "listening"])
            assert {"audio": PCM} in seen
            principal = app.state.test_meeting_conversation.calls[0][2]
            assert principal.authorization_context == "teams_meeting"
            assert principal.permission_ceiling == frozenset({"knowledge.read"})
            for permission in ["cost.read", "factory.read", "graph.read", "config.write", "knowledge.refresh"]:
                with pytest.raises(PermissionError):
                    security.authorize(app.state.settings, principal, "project001-dev", permission)
            finish(socket)
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
    assert body["meeting_session"] not in caplog.text
    assert URL not in caplog.text and "How do I add a project?" not in caplog.text


def test_http_leave_stops_already_running_governed_voice_session():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            response = client.delete("/api/teams-meetings/sessions/" + body["session_id"],
                                     headers={"Authorization": "Bearer " + GOOD})
            assert response.status_code == 204
            tail = collect(socket, ended)
            assert {"type": "closed", "reason": "meeting_ended"} in tail


def test_invalid_meeting_ticket_never_opens_upstream_voice():
    app = app_for_meetings()
    with TestClient(app) as client, client.websocket_connect("/api/voice/ws") as socket:
        socket.send_text(hello(meeting_session="A" * 64))
        assert collect(socket, got("error"))[-1]["code"] == "forbidden"
        assert not app.state.voice_gateway.upstreams


def test_constrain_helper_requires_server_admission_and_preserves_bound_guard():
    app = app_for_meetings()
    with TestClient(app) as client:
        host = app.state.services.authenticate(GOOD)
        with pytest.raises(PermissionError):
            constrain_meeting_principal(app.state.settings, host, "project001-dev")
        body = create(client).json()
        admitted = consume_meeting_session(app, host, body["meeting_session"], "project001-dev", "project")
        constrained = constrain_meeting_principal(app.state.settings, admitted, "project001-dev")
        assert constrained is not admitted
        assert constrained.authorization_guard is admitted.authorization_guard
        assert constrained.permission_ceiling == frozenset({"knowledge.read"})
        assert constrained.scope_ceiling == frozenset({"project001-dev"})
        assert constrained.authorization_context == "teams_meeting"
        with pytest.raises(PermissionError):
            constrain_meeting_principal(app.state.settings, admitted, "other")


def test_unexpected_issue_exception_propagates_instead_of_becoming_an_sdk_outage():
    app = app_for_meetings()
    app.state.teams_meeting_token_service.issue = Mock(side_effect=AssertionError("programming fault"))
    with TestClient(app) as client, pytest.raises(AssertionError, match="programming fault"):
        create(client)
    assert not app.state.teams_meeting_registry.pending


def test_voice_end_failure_still_deletes_acs_identity_and_propagates(caplog):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        entry.voice_session = SimpleNamespace(end=AsyncMock(side_effect=RuntimeError("SECRET transcript")))
        with pytest.raises(RuntimeError, match="SECRET"):
            client.delete("/api/teams-meetings/sessions/" + entry.id, headers={"Authorization": "Bearer " + GOOD})
        assert entry.revoked and not entry.cleaning
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions
    assert "meeting_relay_cleanup_failed" in caplog.text and "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text


def test_unexpected_delete_exception_propagates_but_identity_remains_tracked(caplog):
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    with TestClient(app) as client:
        body = create(client).json()
        revoke = service.revoke
        service.revoke = Mock(side_effect=AssertionError("SECRET URL token"))
        with pytest.raises(AssertionError):
            client.delete("/api/teams-meetings/sessions/" + body["session_id"],
                          headers={"Authorization": "Bearer " + GOOD})
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        assert entry.revoked and not entry.cleaning and entry.timer is not None
        assert "meeting_cleanup_unexpected" in caplog.text and "SECRET" not in caplog.text
        service.revoke = revoke


def test_failed_creation_cleanup_is_tracked_and_reported(caplog):
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    identity = MeetingIdentity("partially-created-user", "secret-token", time.time() + 3600)
    service.issue = Mock(side_effect=TokenServiceError("acs_issue_failed", "ServiceRequestError", identity=identity))
    revoke = service.revoke
    service.revoke = Mock(side_effect=TokenServiceError("acs_delete_failed", "ServiceRequestError"))
    with TestClient(app) as client:
        response = create(client)
        assert response.status_code == 503
        assert response.json()["detail"]["cleanup_pending"] is True
        entry = next(iter(app.state.teams_meeting_registry.sessions.values()))
        assert entry.identity is identity and entry.revoked and entry.timer is not None
        assert create(client).status_code == 409
        service.revoke = revoke
    assert service.deleted == ["partially-created-user"]
    assert "secret-token" not in caplog.text


def test_cancelled_creation_cleanup_failure_is_tracked_for_retry(caplog):
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    entered, release = threading.Event(), threading.Event()
    issue, revoke = service.issue, service.revoke
    principal = app.state.services.authenticate(GOOD)
    policy = app.state.settings.teams_meetings.policies[0]
    body = JoinRequest.model_validate(request_body())

    def blocked_issue():
        entered.set()
        assert release.wait(5)
        return issue()

    async def run():
        service.issue = blocked_issue
        service.revoke = Mock(side_effect=TokenServiceError("acs_delete_failed", "ServiceRequestError"))
        pending = asyncio.create_task(_issue_identity(
            service, lambda identity: _reclaim_identity(app, principal, policy, body, identity)))
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        entry = next(iter(app.state.teams_meeting_registry.sessions.values()))
        assert entry.revoked and entry.timer is not None
        service.revoke = revoke
        from aifactory_agent.teams_meeting_routes import end_meeting_session
        await end_meeting_session(app, entry.id)

    asyncio.run(run())
    assert service.deleted == ["user-0"]
    assert "acs_delete_failed" in caplog.text


def test_expired_unconfirmed_cleanup_does_not_retry_forever_or_report_complete(caplog):
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    with TestClient(app) as client:
        body = create(client).json()
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        entry.identity = replace(entry.identity, expires_at=time.time() - 1)
        service.revoke = Mock(side_effect=TokenServiceError("acs_delete_failed", "ServiceRequestError"))
        response = client.delete("/api/teams-meetings/sessions/" + entry.id, headers={"Authorization": "Bearer " + GOOD})
        assert response.status_code == 202
        assert response.json()["acs_cleanup"] == "expired_unconfirmed"
        assert not app.state.teams_meeting_registry.sessions
        assert "acs_cleanup_expired_unconfirmed" in caplog.text


@pytest.fixture
def sdk_boundary(monkeypatch):
    import azure.communication.identity._communication_identity_client as sdk_module
    import azure.core.pipeline.transport
    import azure.identity

    credential = Mock()
    managed = Mock(return_value=credential)
    transport = Mock()
    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", managed)
    monkeypatch.setattr(azure.core.pipeline.transport, "RequestsTransport", Mock(return_value=transport))
    generated = Mock()
    generated.communication_identity.create.return_value = SimpleNamespace(
        identity=SimpleNamespace(id="8:acs:created-user"),
        access_token=SimpleNamespace(token="SECRET ACS TOKEN", expires_on="2030-01-02T03:04:05Z"),
    )
    monkeypatch.setattr(sdk_module, "CommunicationIdentityClientGen", Mock(return_value=generated))
    return SimpleNamespace(credential=credential, managed=managed, transport=transport, generated=generated)


def test_real_sdk_boundary_uses_uami_voip_one_hour_and_iso_expiry_without_nonexistent_client_close(sdk_boundary):
    from datetime import datetime, timezone
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config()), managed_identity_client_id=HOST)
    identity = service.issue()
    assert identity.user_id == "8:acs:created-user"
    assert identity.expires_at == datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp()
    sdk_boundary.managed.assert_called_once_with(client_id=HOST)
    assert sdk_boundary.generated.communication_identity.create.call_args.kwargs["body"] == {
        "createTokenWithScopes": ["voip"], "expiresInMinutes": 60,
    }
    sdk_boundary.transport.close.assert_called_once()
    sdk_boundary.credential.close.assert_called_once()


def test_explicit_meeting_identity_overrides_root_uami(sdk_boundary):
    override = "33333333-3333-4333-8333-333333333333"
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config(managed_identity_client_id=override)),
                              managed_identity_client_id=HOST)
    service.issue()
    sdk_boundary.managed.assert_called_once_with(client_id=override)


def test_registration_inherits_the_app_managed_identity_without_changing_shared_settings():
    settings = make_settings()
    settings = settings.model_copy(update={
        "teams_meetings": TeamsMeetingSettings.model_validate(enabled_config()),
        "azure": settings.azure.model_copy(update={"managed_identity_client_id": HOST}),
    })
    app = build(settings, Conversation(), FakeGateway())
    assert app.state.teams_meeting_token_service.managed_identity_client_id == HOST
    assert app.state.settings.teams_meetings.managed_identity_client_id is None


def test_sdk_delete_not_found_is_idempotent_and_resources_are_closed(sdk_boundary):
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config()))
    sdk_boundary.generated.communication_identity.delete.side_effect = ResourceNotFoundError("SECRET deleted-id")
    service.revoke(MeetingIdentity("8:acs:created-user", "SECRET", time.time() + 3600))
    sdk_boundary.generated.communication_identity.delete.assert_called_once_with("8:acs:created-user")
    sdk_boundary.transport.close.assert_called_once()
    sdk_boundary.credential.close.assert_called_once()


def test_sdk_azure_errors_are_typed_and_never_include_raw_message(sdk_boundary):
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config()))
    sdk_boundary.generated.communication_identity.create.side_effect = ServiceRequestError("SECRET endpoint")
    with pytest.raises(TokenServiceError) as failure:
        service.issue()
    assert failure.value.code == "acs_issue_failed"
    assert failure.value.source_type == "ServiceRequestError"
    assert "SECRET" not in str(failure.value)
    sdk_boundary.transport.close.assert_called_once()
    sdk_boundary.credential.close.assert_called_once()


def test_sdk_post_creation_transport_failure_preserves_identity_for_recovery(sdk_boundary):
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config()))
    sdk_boundary.transport.close.side_effect = ServiceRequestError("SECRET close failure")
    with pytest.raises(TokenServiceError) as failure:
        service.issue()
    assert failure.value.identity.user_id == "8:acs:created-user"
    sdk_boundary.credential.close.assert_called_once()


def test_sdk_invalid_expiry_keeps_known_identity_and_uses_a_bounded_safe_error(sdk_boundary):
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config()))
    sdk_boundary.generated.communication_identity.create.return_value.access_token.expires_on = "SECRET invalid date"
    with pytest.raises(TokenServiceError) as failure:
        service.issue()
    assert failure.value.code == "acs_invalid_response"
    assert failure.value.identity.user_id == "8:acs:created-user"
    assert "SECRET" not in str(failure.value)
    sdk_boundary.transport.close.assert_called_once()
    sdk_boundary.credential.close.assert_called_once()


def test_sdk_programming_exception_is_not_reclassified_as_cloud_unavailability(sdk_boundary):
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config()))
    sdk_boundary.generated.communication_identity.create.side_effect = AttributeError("broken adapter")
    with pytest.raises(AttributeError, match="broken adapter"):
        service.issue()
    sdk_boundary.transport.close.assert_called_once()
    sdk_boundary.credential.close.assert_called_once()
