import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from aifactory_agent import security, voice_routes
from aifactory_agent.config import DualGraphSettings, Grant
from aifactory_agent.teams_meeting_routes import consume_meeting_session
from aifactory_agent.voice import ClientGone, VoiceAnswerError
from test_conversation import FakeKnowledge, injected
from test_teams_meeting_routes import app_for_meetings, create, reset_voice
from test_teams_meeting_settings import EXTERNAL_LISTENERS, EXTERNAL_TENANT, HOST, LISTENER, external_policy
from test_voice_routes import GOOD, PCM, collect, ended, got, hello


SCOPE = "project001-dev"


def revoke_listener(app):
    current = app.state.settings
    app.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={
        "grants": [grant for grant in current.auth.grants if str(grant.object_id) != LISTENER],
    })})


def admitted(app, client):
    body = create(client).json()
    return consume_meeting_session(app, app.state.services.authenticate(GOOD),
                                   body["meeting_session"], SCOPE, "project")


@pytest.mark.parametrize("explicit_tenant", [False, True])
@pytest.mark.parametrize("grant_kind", ["missing", "other_scope", "other_permission", "split_grants"])
def test_every_listener_needs_existing_exact_scope_knowledge_grant(grant_kind, explicit_tenant):
    app = app_for_meetings()
    if explicit_tenant:
        replace_external_policy(app, meeting_tenant_id=UUID(app.state.settings.tenant_id))
    revoke_listener(app)
    current = app.state.settings
    if grant_kind != "missing":
        scope = current.scopes[SCOPE].model_copy(update={"project": "other"})
        app.state.settings = current = current.model_copy(update={"scopes": {**current.scopes, "other": scope}})
        grants = [
            Grant(object_id=LISTENER, scopes=["other" if grant_kind != "other_permission" else SCOPE],
                  permissions=["knowledge.read" if grant_kind != "other_permission" else "factory.read"]),
        ]
        if grant_kind == "split_grants":
            grants.append(Grant(object_id=LISTENER, scopes=[SCOPE], permissions=["factory.read"]))
        app.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={
            "grants": [*current.auth.grants, *grants],
        })})
    before = app.state.settings.auth.grants[:]
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD}).json()["policies"] == []
        assert not app.state.teams_meeting_token_service.issued
    assert app.state.settings.auth.grants == before


def test_admission_discloses_only_explicit_listener_allowlist():
    app = app_for_meetings()
    with TestClient(app) as client:
        response = create(client)
        assert response.status_code == 201
        assert response.json()["allowed_participant_object_ids"] == [HOST, LISTENER]


@pytest.mark.parametrize("operation", ["consume", "authorize", "prepare", "execute", "finish", "answer"])
def test_listener_revocation_blocks_all_subsequent_work_even_with_stale_conversation(operation):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        host = app.state.services.authenticate(GOOD)
        if operation != "consume":
            principal = consume_meeting_session(app, host, body["meeting_session"], SCOPE, "project")
            harness = injected(app.state.settings)
            prepared = harness.conversation.prepare("Setup?", "project", principal, SCOPE)
        original_settings = app.state.settings
        revoke_listener(app)
        with pytest.raises(PermissionError):
            if operation == "consume":
                consume_meeting_session(app, host, body["meeting_session"], SCOPE, "project")
            elif operation == "authorize":
                security.authorize(original_settings, principal, SCOPE, "knowledge.read")
            elif operation == "prepare":
                harness.conversation.prepare("Setup again?", "project", principal, SCOPE)
            elif operation == "execute":
                prepared.execute("knowledge_search", "read-again", '{"query":"More"}')
            elif operation == "finish":
                prepared.finish("Evidence [S1].", "response")
            else:
                harness.conversation.answer("Setup again?", "project", principal, SCOPE)


def test_listener_revocation_during_identity_issue_reclaims_without_admitting():
    app = app_for_meetings()
    service = app.state.teams_meeting_token_service
    issue = service.issue

    def raced():
        identity = issue()
        revoke_listener(app)
        return identity

    service.issue = raced
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions


def test_changing_listener_roster_policy_invalidates_existing_ticket():
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        current = app.state.settings
        policy = current.teams_meetings.policies[0].model_copy(update={
            "allowed_participant_object_ids": [UUID(HOST)],
        })
        app.state.settings = current.model_copy(update={"teams_meetings": current.teams_meetings.model_copy(
            update={"policies": [policy]})})
        with pytest.raises(PermissionError):
            security.authorize(current, principal, SCOPE, "knowledge.read")


@pytest.mark.parametrize("external", [False, True])
def test_broad_host_grants_never_widen_meeting_tools_or_authorizations(external):
    app = app_for_meetings(**({"policies": [external_policy()]} if external else {}))
    current = app.state.settings
    permissions = ["knowledge.read", "factory.read", "cost.read", "graph.read", "config.write",
                   "knowledge.refresh", "factory.create", "factory.delete", "project.add", "agent.create", "model.create"]
    app.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={
        "grants": [*current.auth.grants, Grant(object_id=HOST, scopes=[SCOPE], permissions=permissions)],
    }), "dual_graph": DualGraphSettings(snapshot_root=Path("."), allowed_scopes=[SCOPE])})
    with TestClient(app) as client:
        principal = admitted(app, client)
        harness = injected(app.state.settings)
        graph = harness.conversation.dual_graph = Mock()
        prepared = harness.conversation.prepare("Explain code dependencies", "project", principal, SCOPE)
        assert {tool["name"] for tool in prepared.tools} == {"knowledge_search", "knowledge_status"}
        for permission in permissions[1:]:
            with pytest.raises(PermissionError):
                security.authorize(app.state.settings, principal, SCOPE, permission)
        for tool in ["factory_health", "cost_summary", "graph_query", "azure_live_state"]:
            with pytest.raises(PermissionError):
                prepared.execute(tool, "forbidden", "{}")
        with pytest.raises(PermissionError):
            security.authorize(app.state.settings, principal, "other", "knowledge.read")
        graph.query.assert_not_called()
        assert not harness.tools.executions and not harness.live_requests


def replace_external_policy(app, **changes):
    current = app.state.settings
    policy = current.teams_meetings.policies[0].model_copy(update=changes)
    app.state.settings = current.model_copy(update={"teams_meetings": current.teams_meetings.model_copy(
        update={"policies": [policy]})})


@pytest.mark.parametrize("change", ["tenant", "approval", "safe", "roster", "host"])
@pytest.mark.parametrize("operation", ["consume", "authorize", "prepare", "execute", "finish", "reset"])
def test_external_disclosure_revocation_blocks_active_sessions_and_reset_even_with_stale_settings(change, operation):
    app = app_for_meetings(policies=[external_policy()])
    with TestClient(app) as client:
        body = create(client).json()
        host = app.state.services.authenticate(GOOD)
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        digest = entry.ticket_hash
        if operation != "consume":
            principal = consume_meeting_session(app, host, body["meeting_session"], SCOPE, "project")
            harness = injected(app.state.settings)
            prepared = harness.conversation.prepare("Setup?", "project", principal, SCOPE)
        original_settings = app.state.settings
        if change == "host":
            app.state.settings = original_settings.model_copy(update={"auth": original_settings.auth.model_copy(update={
                "grants": [grant for grant in original_settings.auth.grants if str(grant.object_id) != HOST],
            })})
        else:
            updates = {
                "tenant": {"meeting_tenant_id": UUID("99999999-9999-4999-8999-999999999999")},
                "approval": {"external_audience_disclosure_approved": False},
                "safe": {"meeting_safe_knowledge": False},
                "roster": {"allowed_participant_object_ids": [UUID(EXTERNAL_LISTENERS[0])]},
            }
            replace_external_policy(app, **updates[change])
        if operation == "reset":
            if change == "safe":
                # This unvalidated model_copy is rejected by service configuration reload before the route.
                with pytest.raises(ValidationError, match="shared-knowledge approval"):
                    reset_voice(client, entry.id)
            else:
                assert reset_voice(client, entry.id).status_code == 403
            assert entry.ticket_hash == digest and entry.generation == 0
        else:
            with pytest.raises(PermissionError):
                if operation == "consume":
                    consume_meeting_session(app, host, body["meeting_session"], SCOPE, "project")
                elif operation == "authorize":
                    security.authorize(original_settings, principal, SCOPE, "knowledge.read")
                elif operation == "prepare":
                    harness.conversation.prepare("Setup again?", "project", principal, SCOPE)
                elif operation == "execute":
                    prepared.execute("knowledge_search", "read-again", '{"query":"More"}')
                else:
                    prepared.finish("Evidence [S1].", "response")
        assert len(app.state.teams_meeting_token_service.issued) == 1


def test_external_disclosure_mode_is_pinned_even_when_replacement_policy_is_independently_valid():
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        original = app.state.settings
        replace_external_policy(app, meeting_tenant_id=UUID(EXTERNAL_TENANT),
                                external_audience_disclosure_approved=True)
        assert client.get("/api/teams-meetings/status", headers={"Authorization": "Bearer " + GOOD}).json()["policies"]
        with pytest.raises(PermissionError):
            security.authorize(original, principal, SCOPE, "knowledge.read")
        assert reset_voice(client, principal.meeting_session_id).status_code == 403


def test_external_disclosure_does_not_change_auth_clients_or_create_listener_app_grants():
    app = app_for_meetings(policies=[external_policy()])
    before = app.state.settings.auth.model_dump(mode="json")
    with TestClient(app) as client:
        principal = admitted(app, client)
        host = app.state.services.authenticate(GOOD)
        assert (principal.tenant_id, principal.object_id, principal.client_id) == (
            host.tenant_id, host.object_id, host.client_id)
        for object_id in EXTERNAL_LISTENERS:
            listener = security.Principal(EXTERNAL_TENANT, object_id)
            with pytest.raises(PermissionError):
                security.authorize(app.state.settings, listener, SCOPE, "knowledge.read")
            with pytest.raises(PermissionError):
                security.authorize(app.state.settings, replace(listener, tenant_id=host.tenant_id),
                                   SCOPE, "knowledge.read")
        assert app.state.settings.auth.model_dump(mode="json") == before


@pytest.mark.parametrize("change", ["approval", "tenant"])
def test_external_disclosure_revoked_during_voice_reset_cannot_return_reusable_ticket(change):
    app = app_for_meetings(policies=[external_policy()])
    with TestClient(app) as client:
        principal = admitted(app, client)
        entry = app.state.teams_meeting_registry.sessions[principal.meeting_session_id]

        async def stop(_):
            replace_external_policy(app, **(
                {"external_audience_disclosure_approved": False} if change == "approval"
                else {"meeting_tenant_id": UUID("99999999-9999-4999-8999-999999999999")}))

        entry.voice_session = SimpleNamespace(end=stop)
        assert reset_voice(client, entry.id).status_code == 403
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        assert reset_voice(client, entry.id, generation=1).status_code == 404


def test_live_relay_stops_before_audio_after_external_disclosure_approval_revocation():
    app = app_for_meetings(policies=[external_policy()])
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            replace_external_policy(app, external_audience_disclosure_approved=False)
            socket.send_bytes(PCM)
            seen = collect(socket, ended)
            assert not any("audio" in frame or frame.get("type") in {"answer", "transcript"} for frame in seen)
            assert app.state.voice_gateway.upstreams[0].appends == 0
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


def test_even_replaced_delegate_fields_cannot_widen_server_bound_guard():
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        for changed, permission in (
            (replace(principal, permission_ceiling=None), "factory.read"),
            (replace(principal, object_id=LISTENER), "knowledge.read"),
            (replace(principal, client_id=HOST), "knowledge.read"),
        ):
            with pytest.raises(PermissionError):
                security.authorize(app.state.settings, changed, SCOPE, permission)


def test_meeting_marker_without_server_bound_admission_never_authorizes():
    app = app_for_meetings()
    host = app.state.services.authenticate(GOOD)
    forged = replace(host, authorization_context="teams_meeting")
    with pytest.raises(PermissionError):
        security.authorize(app.state.settings, forged, SCOPE, "knowledge.read")


@pytest.mark.parametrize("permission_ceiling,scope_ceiling", [
    (frozenset(), None), (None, frozenset({"other"})),
])
def test_ceiling_is_an_intersection_not_a_grant(permission_ceiling, scope_ceiling):
    app = app_for_meetings()
    host = replace(app.state.services.authenticate(GOOD),
                   permission_ceiling=permission_ceiling, scope_ceiling=scope_ceiling)
    with pytest.raises(PermissionError):
        security.authorize(app.state.settings, host, SCOPE, "knowledge.read")


def test_meeting_tool_permissions_are_shared_with_regular_read_only_calls():
    assert security.read_tool_permissions("graph_query") == ("graph.read",)
    assert security.read_tool_permissions("knowledge_search") == ("knowledge.read",)
    assert security.read_tool_permissions("knowledge_status") == ("knowledge.read",)
    assert security.read_tool_permissions("cost_summary") == ("factory.read", "cost.read")
    assert security.read_tool_permissions("factory_health") == ("factory.read",)


@pytest.mark.parametrize("stage", ["readiness", "retrieval", "tool"])
def test_revocation_during_knowledge_dependency_blocks_next_operation_or_result(stage):
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        knowledge = FakeKnowledge()
        harness = injected(app.state.settings, knowledge=knowledge)
        if stage == "tool":
            prepared = harness.conversation.prepare("Setup?", "project", principal, SCOPE)
        original = knowledge.status if stage == "readiness" else knowledge.search

        def revoked(*args):
            result = original(*args)
            revoke_listener(app)
            return result

        if stage == "readiness":
            knowledge.status = revoked
        else:
            knowledge.search = revoked
        with pytest.raises(PermissionError):
            if stage == "tool":
                prepared.execute("knowledge_search", "read-again", '{"query":"More"}')
            else:
                harness.conversation.prepare("Setup?", "project", principal, SCOPE)
        if stage == "readiness":
            assert knowledge.searches == []


@pytest.mark.parametrize("kind", ["audio", "answer", "transcript"])
def test_meeting_response_channel_rechecks_each_frame_and_still_allows_cleanup(kind):
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        socket = SimpleNamespace(application_state=WebSocketState.CONNECTED,
                                 send_bytes=AsyncMock(), send_text=AsyncMock())
        channel = voice_routes.StarletteChannel(socket)
        channel.policy_guard = lambda: security.authorize(app.state.settings, principal, SCOPE, "knowledge.read")
        channel.on_policy_denied = AsyncMock()

        async def run():
            async def send():
                if kind == "audio":
                    await channel.send_audio(PCM)
                else:
                    await channel.send_json({"type": kind, "text": "PRIVATE"})
            await send()
            revoke_listener(app)
            with pytest.raises(ClientGone):
                await send()
            await channel.send_json({"type": "closed", "reason": "meeting_policy_changed"})

        asyncio.run(run())
        assert socket.send_bytes.await_count == (1 if kind == "audio" else 0)
        assert socket.send_text.await_count == (1 if kind == "audio" else 2)
        channel.on_policy_denied.assert_awaited_once()


@pytest.mark.parametrize("mode", ["answer", "prepare", "execute"])
def test_voice_callbacks_recheck_listener_grants_after_dependency_returns(mode):
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        conversation = app.state.test_meeting_conversation
        if mode == "answer":
            original = conversation.answer

            def work(*args):
                result = original(*args)
                revoke_listener(app)
                return result

            conversation.answer = work
            call = voice_routes._answerer(app, principal, SCOPE, "project")("Question?")
        elif mode == "prepare":
            prepared = injected(app.state.settings).conversation.prepare("Setup?", "project", principal, SCOPE)

            def work(*args):
                revoke_listener(app)
                return prepared

            conversation.prepare = work
            prepare, _ = voice_routes._native_handlers(app, principal, SCOPE, "project")
            call = prepare("Question?")
        else:
            def work(*args):
                revoke_listener(app)
                return {"evidence": "PRIVATE"}

            _, execute = voice_routes._native_handlers(app, principal, SCOPE, "project")
            call = execute(SimpleNamespace(execute=work), "knowledge_search", "read", '{"query":"More"}')
        with pytest.raises(VoiceAnswerError) as error:
            asyncio.run(call)
        assert error.value.code == "forbidden"


def test_live_relay_stops_before_forwarding_audio_after_listener_revocation():
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            revoke_listener(app)
            socket.send_bytes(PCM)
            seen = collect(socket, ended)
            assert not any("audio" in frame or frame.get("type") in {"answer", "transcript"} for frame in seen)
            assert app.state.voice_gateway.upstreams[0].appends == 0
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


def test_revocation_during_voice_connect_closes_upstream_and_reclaims_identity():
    app = app_for_meetings()
    connect = app.state.voice_gateway.connect

    async def raced(settings):
        upstream = await connect(settings)
        revoke_listener(app)
        return upstream

    app.state.voice_gateway.connect = raced
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            seen = collect(socket, ended)
            assert any(frame.get("code") == "forbidden" for frame in seen)
        assert app.state.voice_gateway.upstreams[0].closed
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


@pytest.mark.parametrize("change", ["listener", "host", "policy", "expired"])
def test_voice_reset_rechecks_all_admission_policy_and_grants(change):
    app = app_for_meetings()
    with TestClient(app) as client:
        body = create(client).json()
        entry = app.state.teams_meeting_registry.sessions[body["session_id"]]
        digest = entry.ticket_hash
        if change == "listener":
            revoke_listener(app)
        elif change == "host":
            current = app.state.settings
            app.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={
                "grants": [grant for grant in current.auth.grants if str(grant.object_id) != HOST],
            })})
        elif change == "policy":
            current = app.state.settings
            policy = current.teams_meetings.policies[0].model_copy(update={"id": "replacement"})
            app.state.settings = current.model_copy(update={"teams_meetings": current.teams_meetings.model_copy(
                update={"policies": [policy]})})
        else:
            entry.expires_at = 0
        assert reset_voice(client, entry.id).status_code == 403
        assert entry.ticket_hash == digest
        assert not entry.consumed
        assert len(app.state.teams_meeting_token_service.issued) == 1


def test_voice_reset_rechecks_revoked_grants_after_stopping_old_voice():
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        entry = app.state.teams_meeting_registry.sessions[principal.meeting_session_id]

        async def stop(_):
            revoke_listener(app)

        entry.voice_session = SimpleNamespace(end=stop)
        assert reset_voice(client, entry.id).status_code == 403
        assert not app.state.teams_meeting_registry.sessions
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


def test_voice_reset_generation_blocks_old_content_frames_even_with_current_grants():
    app = app_for_meetings()
    with TestClient(app) as client:
        principal = admitted(app, client)
        socket = SimpleNamespace(application_state=WebSocketState.CONNECTED,
                                 send_bytes=AsyncMock(), send_text=AsyncMock())
        channel = voice_routes.StarletteChannel(socket)
        channel.policy_guard = lambda: security.authorize(app.state.settings, principal, SCOPE, "knowledge.read")
        channel.on_policy_denied = AsyncMock()
        response = reset_voice(client, principal.meeting_session_id)
        assert response.status_code == 200
        with pytest.raises(ClientGone):
            asyncio.run(channel.send_audio(PCM))
        with pytest.raises(ClientGone):
            asyncio.run(channel.send_json({"type": "answer", "answer": "STALE"}))
        socket.send_bytes.assert_not_called()
        socket.send_text.assert_not_called()
