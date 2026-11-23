"""Meeting link posting uses fake identities, authoritative frames and fake ACS; never live services."""
import asyncio
import threading
import time
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from azure.core.exceptions import AzureError, HttpResponseError, ServiceRequestError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aifactory_agent import teams_meeting_chat as chat, web
from aifactory_agent.teams_meeting_routes import (
    AcsTokenService, MeetingIdentity, bind_meeting_voice_session, consume_meeting_session,
)
from aifactory_agent.teams_meeting_settings import MeetingPolicy, TeamsMeetingSettings
from test_teams_meeting_routes import app_for_meetings, create, reset_voice
from test_teams_meeting_settings import enabled_config
from test_voice_routes import GOOD, OTHER, PCM, collect, finish, got, hello


THREAD = "19:meeting_Abc-123_XYZ@thread.v2"
HEADERS = {"Authorization": "Bearer " + GOOD}
SOURCE = "https://learn.microsoft.com/en-us/azure/communication-services/#chat"


def chat_config(**changes):
    return {
        "chat_enabled": True, "chat_allowed_link_hosts": ["learn.microsoft.com", "github.com"],
        "policies": [{**enabled_config()["policies"][0], "chat_thread_id": THREAD,
                      "chat_disclosure_approved": True}], **changes,
    }


def answer(**changes):
    return {"type": "answer", "scope_key": "project001-dev", "audience": "project",
            "answer": "Private answer text must never be stored or posted.",
            "citations": [{"source_url": SOURCE, "heading": "ACS documentation"}], **changes}


@contextmanager
def admitted(**changes):
    app = app_for_meetings(**chat_config(**changes))
    app.state.teams_meeting_token_service.chat_token = Mock(return_value="server-only-chat-token")
    app.state.teams_meeting_chat_sender = Mock()
    app.state.teams_meeting_chat_sender.send.return_value = "actual-message-123"
    with TestClient(app) as client:
        response = create(client)
        assert response.status_code == 201, response.text
        admission = response.json()
        entry = app.state.teams_meeting_registry.sessions[admission["session_id"]]
        principal = consume_meeting_session(app, entry.principal, admission["meeting_session"],
                                            entry.scope_key, entry.audience)
        bind_meeting_voice_session(app, principal, AsyncMock())
        yield app, client, entry, principal, admission


def capture(app, entry, principal, message=None):
    return chat.capture_meeting_links(app, principal, entry.voice_session, message or answer())


def preview(client, entry, offer, **changes):
    return client.post(f"/api/teams-meetings/sessions/{entry.id}/links/preview", headers=HEADERS, json={
        "voice_generation": entry.generation, "thread_id": THREAD,
        "offer_id": offer["chat_links"]["offer_id"], **changes,
    })


def send(client, entry, draft, **changes):
    return client.post(f"/api/teams-meetings/sessions/{entry.id}/links/send", headers=HEADERS, json={
        "voice_generation": draft["voice_generation"], "thread_id": THREAD,
        "draft_id": draft["draft_id"], "confirmed": True, **changes,
    })


def change_settings(app, **changes):
    current = app.state.settings
    app.state.settings = current.model_copy(update={
        "teams_meetings": current.teams_meetings.model_copy(update=changes),
    })


def test_disabled_defaults_and_chat_consent_are_separate_from_audio_consent():
    settings = TeamsMeetingSettings.model_validate(enabled_config())
    assert settings.chat_enabled is False and settings.chat_allowed_link_hosts == []
    assert settings.policies[0].chat_thread_id is None
    assert settings.policies[0].chat_disclosure_approved is False


@pytest.mark.parametrize("changes", [
    {"chat_enabled": "true"}, {"chat_enabled": 1}, {"chat_allowed_link_hosts": []},
    {"chat_allowed_link_hosts": ["*.github.com"]}, {"chat_allowed_link_hosts": ["https://github.com"]},
    {"chat_allowed_link_hosts": ["GitHub.com"]}, {"chat_allowed_link_hosts": ["github.com:443"]},
    {"chat_allowed_link_hosts": ["github.com."]}, {"chat_allowed_link_hosts": ["127.0.0.1"]},
    {"chat_allowed_link_hosts": ["github.com", "github.com"]},
    {"policies": [enabled_config()["policies"][0]]},
])
def test_chat_configuration_fails_closed(changes):
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(enabled_config(**chat_config(**changes)))


@pytest.mark.parametrize("thread", ["", "19:x@thread.v2/other", "19:x@thread.v2?x=y",
                                    "19:x\n@thread.v2", "https://teams.microsoft.com",
                                    "19:" + "x" * 500 + "@thread.v2"])
def test_thread_ids_are_bounded_and_not_urls(thread):
    with pytest.raises(ValidationError):
        MeetingPolicy.model_validate({**enabled_config()["policies"][0], "chat_thread_id": thread})


@pytest.mark.parametrize("approved", [False, "true", 1])
def test_chat_disclosure_must_be_explicit_strict_true(approved):
    config = chat_config()
    config["policies"][0]["chat_disclosure_approved"] = approved
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(enabled_config(**config))


def test_preview_is_exact_server_owned_bounded_and_never_sends_automatically():
    with admitted() as (app, client, entry, principal, admission):
        assert admission["chat_enabled"] is True and admission["chat_thread_id"] == THREAD
        assert admission["acs_token"] == "acs-secret"
        status = client.get("/api/teams-meetings/status", headers=HEADERS)
        assert status.json()["chat_enabled"] is True
        assert THREAD not in status.text and SOURCE not in status.text
        offer = capture(app, entry, principal)
        assert offer["chat_links"]["count"] == 1
        response = preview(client, entry, offer)
        assert response.status_code == 200, response.text
        draft = response.json()
        assert draft["thread_id"] == THREAD and draft["voice_generation"] == 0
        assert draft["links"] == [{"title": "Source 1", "url": SOURCE}]
        assert draft["content"] == f"ESAF Agent Chat sources:\n1. Source 1\n{SOURCE}"
        assert time.time() < draft["expires_at"] <= time.time() + 300
        assert response.headers["cache-control"] == "no-store"
        assert preview(client, entry, offer).json() == draft
        assert "Private answer" not in repr(entry.chat_offer) + repr(entry.chat_draft)
        app.state.teams_meeting_token_service.chat_token.assert_not_called()
        app.state.teams_meeting_chat_sender.send.assert_not_called()


@pytest.mark.parametrize("url", [
    "http://github.com/a", "https://evil.example/a", "https://sub.github.com/a",
    "https://github.com.evil.example/a", "https://user:secret@github.com/a",
    "https://github.com:443/a", "https://github.com/a?sig=secret", "https://github.com/a?",
    "https://github.com\\@evil.example/a", "https://github.com/a\n",
    "https://github.com/a%0Aevil", "https://github.com/a%5cevil",
    "https://github.com/a#%0dsecret", "https://github.com/" + "x" * 2048,
    "https://github.com/a#sig=secret", "https://github.com/a#sig%3Dsecret",
    "javascript:alert(1)", 123, None,
])
def test_unsafe_or_unsupported_sources_do_not_offer_links(url):
    with admitted() as (app, client, entry, principal, _):
        result = capture(app, entry, principal, answer(citations=[{"source_url": url}],
                         answer="Use https://github.com/model-invented instead."))
        assert "chat_links" not in result and entry.chat_offer is None
        app.state.teams_meeting_token_service.chat_token.assert_not_called()


def test_only_final_grounded_citation_urls_are_used_and_latest_empty_answer_invalidates():
    with admitted() as (app, client, entry, principal, _):
        first = capture(app, entry, principal)
        for frame in [
            answer(type="transcript", final=True), answer(type="assistant_transcript", final=False),
            answer(authoritative=False), answer(citation_validation="failed"),
            answer(citations=[], answer=SOURCE),
        ]:
            assert "chat_links" not in capture(app, entry, principal, frame)
        assert preview(client, entry, first).status_code == 409


def test_links_titles_and_count_are_bounded_and_deduplicated():
    with admitted() as (app, client, entry, principal, _):
        citations = [{"source_url": SOURCE, "heading": "\n\u202e\t" + "a" * 300}]
        citations += [{"source_url": SOURCE}]
        citations += [{"source_url": f"https://github.com/org/repo/{i}", "source_path": f"guides/setup-{i}"}
                      for i in range(12)]
        offer = capture(app, entry, principal, answer(citations=citations))
        draft = preview(client, entry, offer).json()
        assert len(draft["links"]) == 5 and offer["chat_links"]["count"] == 5
        assert [link["title"] for link in draft["links"]] == [f"Source {i}" for i in range(1, 6)]
        assert "guides/setup" not in draft["content"] and "a" * 160 not in draft["content"]


@pytest.mark.parametrize("change", ["scope", "audience", "generation", "voice", "unconsumed", "host"])
def test_offer_requires_current_admitted_scope_generation_and_voice(change):
    with admitted() as (app, client, entry, principal, _):
        frame = answer()
        voice = entry.voice_session
        if change in {"scope", "audience"}:
            frame["scope_key" if change == "scope" else "audience"] = "other"
        elif change == "generation":
            principal = replace(principal, meeting_generation=99)
        elif change == "voice":
            voice = AsyncMock()
        elif change == "unconsumed":
            entry.consumed = False
        else:
            principal = entry.principal
        assert "chat_links" not in chat.capture_meeting_links(app, principal, voice, frame)


@pytest.mark.parametrize("changes", [
    {"voice_generation": "0"}, {"voice_generation": True}, {"voice_generation": -1},
    {"thread_id": None}, {"thread_id": ""}, {"content": "untrusted"}, {"offer_id": "x" * 300},
])
def test_preview_rejects_invalid_or_client_authored_input(changes):
    with admitted() as (app, client, entry, principal, _):
        assert preview(client, entry, capture(app, entry, principal), **changes).status_code == 422


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
def test_send_requires_strict_confirmation(confirmed):
    with admitted() as (app, client, entry, principal, _):
        draft = preview(client, entry, capture(app, entry, principal)).json()
        assert send(client, entry, draft, confirmed=confirmed).status_code == 422
        app.state.teams_meeting_token_service.chat_token.assert_not_called()


@pytest.mark.parametrize("change", ["host", "tenant", "client", "delegate", "scope_ceiling", "permission_ceiling"])
def test_commands_require_original_authenticated_host_client_and_current_channel(change):
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal)
        draft = preview(client, entry, offer).json()
        user = entry.principal
        if change == "host":
            user = app.state.services.authenticate(OTHER)
        elif change == "tenant":
            user = replace(user, tenant_id="88888888-8888-4888-8888-888888888888")
        elif change == "client":
            user = replace(user, client_id="11111111-1111-4111-8111-111111111111")
        elif change == "delegate":
            user = principal
        else:
            user = replace(user, **{change: frozenset()})
        app.dependency_overrides[web.get_principal] = lambda: user
        assert preview(client, entry, offer).status_code == 403
        assert send(client, entry, draft).status_code == 403
        app.state.teams_meeting_token_service.chat_token.assert_not_called()


@pytest.mark.parametrize("change", ["disabled", "thread", "disclosure", "hosts", "endpoint", "grant", "listeners"])
def test_policy_revocations_invalidate_preview_send_and_reset(change):
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal)
        draft = preview(client, entry, offer).json()
        app.dependency_overrides[web.get_principal] = lambda: entry.principal
        if change == "disabled":
            change_settings(app, chat_enabled=False)
        elif change == "hosts":
            change_settings(app, chat_allowed_link_hosts=["github.com"])
        elif change == "endpoint":
            change_settings(app, acs_endpoint="https://other.communication.azure.com")
        elif change == "grant":
            app.state.settings = app.state.settings.model_copy(update={
                "auth": app.state.settings.auth.model_copy(update={"grants": []})})
        else:
            update = {"chat_thread_id": "19:other@thread.v2"} if change == "thread" else (
                {"chat_disclosure_approved": False} if change == "disclosure" else
                {"allowed_participant_object_ids": []})
            policy = app.state.settings.teams_meetings.policies[0].model_copy(update=update)
            change_settings(app, policies=[policy])
        assert preview(client, entry, offer).status_code == 403
        assert send(client, entry, draft).status_code == 403
        assert reset_voice(client, entry.id).status_code == 403


def test_thread_generation_latest_offer_expiry_reset_and_leave_are_enforced(monkeypatch):
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal)
        draft = preview(client, entry, offer).json()
        assert preview(client, entry, offer, thread_id="19:other@thread.v2").status_code == 403
        assert send(client, entry, draft, thread_id="19:other@thread.v2").status_code == 403
        assert send(client, entry, draft, voice_generation=1).status_code == 409
        capture(app, entry, principal)
        assert preview(client, entry, offer).status_code == 409
        assert send(client, entry, draft).status_code == 409
        offer = capture(app, entry, principal)
        draft = preview(client, entry, offer).json()
        now = time.time()
        with monkeypatch.context() as patch:
            patch.setattr(chat.time, "time", lambda: now + 301)
            assert preview(client, entry, offer).status_code == 410
            assert send(client, entry, draft).status_code == 410
        assert reset_voice(client, entry.id).status_code == 200
        assert entry.chat_offer is None and entry.chat_draft is None
        assert send(client, entry, draft).status_code == 409
        assert client.delete(f"/api/teams-meetings/sessions/{entry.id}", headers=HEADERS).status_code == 204
        assert send(client, entry, draft).status_code == 410


def test_confirmed_send_uses_same_identity_exact_preview_and_preserves_actual_id_on_duplicate():
    with admitted() as (app, client, entry, principal, _):
        draft = preview(client, entry, capture(app, entry, principal)).json()
        response = send(client, entry, draft)
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "sent", "message_id": "actual-message-123", "thread_id": THREAD}
        assert send(client, entry, draft).json() == response.json()
        app.state.teams_meeting_token_service.chat_token.assert_called_once_with(entry.identity)
        app.state.teams_meeting_chat_sender.send.assert_called_once_with(
            entry.chat_acs_endpoint, "server-only-chat-token", THREAD, draft["content"], entry.chat_display_name)
        assert "server-only-chat-token" not in response.text


@pytest.mark.parametrize("code", [401, 403, 429])
def test_sdk_rejections_are_explicit_terminal_and_never_retried(code):
    with admitted() as (app, client, entry, principal, _):
        error = HttpResponseError("sensitive response and token")
        error.status_code = code
        app.state.teams_meeting_chat_sender.send.side_effect = error
        draft = preview(client, entry, capture(app, entry, principal)).json()
        result = send(client, entry, draft)
        assert result.status_code == 502
        assert result.json()["detail"]["code"] == f"chat_rejected_{code}"
        assert "sensitive" not in result.text
        assert send(client, entry, draft).status_code == 409
        assert app.state.teams_meeting_chat_sender.send.call_count == 1


def test_ambiguous_network_failure_is_uncertain_and_no_retry():
    with admitted() as (app, client, entry, principal, _):
        app.state.teams_meeting_chat_sender.send.side_effect = ServiceRequestError("secret")
        draft = preview(client, entry, capture(app, entry, principal)).json()
        result = send(client, entry, draft)
        assert result.status_code == 502 and result.json()["detail"]["code"] == "delivery_unknown"
        assert send(client, entry, draft).status_code == 409
        assert entry.chat_operation.status == "uncertain"
        assert app.state.teams_meeting_chat_sender.send.call_count == 1


def test_policy_is_rechecked_after_obtaining_chat_token():
    with admitted() as (app, client, entry, principal, _):
        draft = preview(client, entry, capture(app, entry, principal)).json()

        def token(identity):
            change_settings(app, chat_enabled=False)
            return "server-only-chat-token"

        app.state.teams_meeting_token_service.chat_token.side_effect = token
        assert send(client, entry, draft).status_code == 403
        app.state.teams_meeting_chat_sender.send.assert_not_called()
        assert entry.chat_operation.status == "failed"


def test_concurrent_send_and_timeout_do_not_release_inflight_or_resend(monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(chat, "SEND_TIMEOUT_SECONDS", 0.05)
    with admitted() as (app, client, entry, principal, _):
        def blocked(*args):
            started.set()
            assert release.wait(5)
            return "late-actual-message"

        app.state.teams_meeting_chat_sender.send.side_effect = blocked
        draft = preview(client, entry, capture(app, entry, principal)).json()
        try:
            result = send(client, entry, draft)
            assert started.is_set()
            assert result.status_code == 502 and result.json()["detail"]["code"] == "delivery_unknown"
            assert send(client, entry, draft).status_code == 409
            assert app.state.teams_meeting_chat_sender.send.call_count == 1
            operation = entry.chat_operation
            assert reset_voice(client, entry.id).status_code == 200
            assert entry.chat_operation is operation
        finally:
            release.set()
            if entry.chat_operation.task is not None:
                client.portal.call(lambda: asyncio.shield(entry.chat_operation.task))
        assert operation.message_id == "late-actual-message"


def test_voice_channel_captures_only_server_answer_and_does_not_send_to_chat():
    app = app_for_meetings(**chat_config())
    app.state.teams_meeting_token_service.chat_token = Mock()
    app.state.teams_meeting_chat_sender = Mock()
    app.state.test_meeting_conversation.answer = Mock(return_value={key: value for key, value in answer().items()
                                                                   if key != "type"})
    with TestClient(app) as client:
        admission = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=admission["meeting_session"]))
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            frames = collect(socket, got("answer"))
            assert frames[-1]["chat_links"]["count"] == 1
            app.state.teams_meeting_chat_sender.send.assert_not_called()
            app.state.teams_meeting_token_service.chat_token.assert_not_called()
            finish(socket)


def test_chat_token_is_separate_chat_only_same_identity_and_never_creates_another_user(monkeypatch):
    from azure.communication.identity import CommunicationTokenScope
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config(**chat_config())))
    client = Mock()
    client.get_token.return_value = SimpleNamespace(token="chat-only")

    @contextmanager
    def fake_client(**kwargs):
        assert kwargs["retry_total"] == 0
        yield client

    monkeypatch.setattr(service, "_client", fake_client)
    identity = MeetingIdentity("8:acs:existing-admitted", "voip-only", time.time() + 3600)
    assert service.chat_token(identity) == "chat-only"
    args, kwargs = client.get_token.call_args
    assert args[0].properties["id"] == identity.user_id
    assert kwargs["scopes"] == [CommunicationTokenScope.CHAT]
    client.create_user_and_token.assert_not_called()


def test_chat_sdk_sets_options_on_both_clients_owns_resources_and_sends_plain_text(monkeypatch):
    import azure.communication.chat
    from azure.communication.chat import ChatMessageType, CommunicationTokenCredential
    token_credential = Mock(spec=CommunicationTokenCredential)
    monkeypatch.setattr(azure.communication.chat, "CommunicationTokenCredential", Mock(return_value=token_credential))
    thread = Mock()
    thread.send_message.return_value = SimpleNamespace(id="sdk-id")
    client = Mock()
    client.get_chat_thread_client.return_value = thread
    factory = Mock(return_value=client)
    monkeypatch.setattr(azure.communication.chat, "ChatClient", factory)
    assert chat.AcsChatSender().send("https://example.communication.azure.com", "secret", THREAD,
                                     "preview", "ESAF") == "sdk-id"
    assert factory.call_args.args[1] is token_credential
    for kwargs in [factory.call_args.kwargs, client.get_chat_thread_client.call_args.kwargs]:
        assert kwargs["retry_total"] == 0 and kwargs["redirect_max"] == 0
        assert kwargs["connection_timeout"] == 10 and kwargs["read_timeout"] == 20
        assert kwargs["logging_enable"] is False
        assert kwargs["transport"].connection_config.timeout == 10
        assert kwargs["transport"].connection_config.read_timeout == 20
    thread.send_message.assert_called_once_with("preview", sender_display_name="ESAF",
                                                chat_message_type=ChatMessageType.TEXT)
    thread.close.assert_called_once()
    client.close.assert_called_once()
    token_credential.close.assert_called_once()


def test_disabled_chat_keeps_admission_voice_only_and_never_offers_or_issues_chat_token():
    with admitted(chat_enabled=False) as (app, client, entry, principal, admission):
        assert admission["chat_enabled"] is False and "chat_thread_id" not in admission
        assert admission["acs_token"] == "acs-secret"
        assert "chat_links" not in capture(app, entry, principal)
        response = client.post(f"/api/teams-meetings/sessions/{entry.id}/links/preview", headers=HEADERS,
                               json={"voice_generation": 0, "thread_id": THREAD, "offer_id": "a" * 32})
        assert response.status_code == 403
        app.state.teams_meeting_token_service.chat_token.assert_not_called()
        app.state.teams_meeting_chat_sender.send.assert_not_called()


def test_preview_and_send_require_authentication_and_reject_missing_thread_confirmation_and_content():
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal)
        base = f"/api/teams-meetings/sessions/{entry.id}/links/"
        assert client.post(base + "preview", json={}).status_code == 401
        assert client.post(base + "send", json={}).status_code == 401
        assert client.post(base + "preview", headers=HEADERS, json={
            "voice_generation": 0, "offer_id": offer["chat_links"]["offer_id"],
        }).status_code == 422
        draft = preview(client, entry, offer).json()
        assert client.post(base + "send", headers=HEADERS, json={
            "voice_generation": 0, "draft_id": draft["draft_id"], "thread_id": THREAD,
        }).status_code == 422
        assert send(client, entry, draft, content="do not accept browser content").status_code == 422


@pytest.mark.parametrize("mutation", ["answer", "reset", "leave"])
def test_offer_reset_or_leave_during_token_acquisition_prevents_send(mutation):
    with admitted() as (app, client, entry, principal, _):
        draft = preview(client, entry, capture(app, entry, principal)).json()

        def token(identity):
            if mutation == "answer":
                capture(app, entry, principal)
            elif mutation == "reset":
                assert reset_voice(client, entry.id).status_code == 200
            else:
                assert client.delete(f"/api/teams-meetings/sessions/{entry.id}", headers=HEADERS).status_code == 204
            return "server-only-chat-token"

        app.state.teams_meeting_token_service.chat_token.side_effect = token
        assert send(client, entry, draft).status_code in {409, 410}
        app.state.teams_meeting_chat_sender.send.assert_not_called()


def test_timeout_before_token_finishes_cannot_later_send(monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(chat, "SEND_TIMEOUT_SECONDS", 0.05)
    with admitted() as (app, client, entry, principal, _):
        def blocked(identity):
            started.set()
            assert release.wait(5)
            return "server-only-chat-token"

        app.state.teams_meeting_token_service.chat_token.side_effect = blocked
        draft = preview(client, entry, capture(app, entry, principal)).json()
        try:
            result = send(client, entry, draft)
            assert started.is_set()
            assert result.status_code == 502 and result.json()["detail"]["code"] == "chat_token_unavailable"
            assert send(client, entry, draft).status_code == 409
        finally:
            release.set()
            client.portal.call(lambda: asyncio.shield(entry.chat_operation.task))
        app.state.teams_meeting_chat_sender.send.assert_not_called()


def test_concurrent_confirmation_and_cancelled_waiter_do_not_cancel_or_repeat_write():
    started, release = threading.Event(), threading.Event()
    with admitted() as (app, client, entry, principal, _):
        def blocked(*args):
            started.set()
            assert release.wait(5)
            return "delivered-after-disconnect"

        app.state.teams_meeting_chat_sender.send.side_effect = blocked
        draft = preview(client, entry, capture(app, entry, principal)).json()
        route = next(route for route in app.routes if route.path.endswith("/{session_id}/links/send"))
        body = chat.SendRequest(voice_generation=0, thread_id=THREAD, draft_id=draft["draft_id"], confirmed=True)
        waiter = client.portal.start_task_soon(route.endpoint, entry.id, body, entry.principal)
        try:
            assert started.wait(5)
            duplicate = send(client, entry, draft)
            assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "sending"
            assert waiter.cancel()
            with pytest.raises(CancelledError):
                waiter.result(5)
            assert send(client, entry, draft).status_code == 409
        finally:
            release.set()
            client.portal.call(lambda: asyncio.shield(entry.chat_operation.task))
        assert send(client, entry, draft).json()["message_id"] == "delivered-after-disconnect"
        assert app.state.teams_meeting_chat_sender.send.call_count == 1


@pytest.mark.parametrize("status", [201, 401, 403, 429, 500, 307])
def test_real_sdk_pipeline_makes_only_one_transport_attempt_and_never_follows_redirect(status):
    import json
    import jwt
    from azure.core.pipeline.transport import HttpResponse, HttpTransport

    attempts = []

    class FakeResponse(HttpResponse):
        def __init__(self, request):
            super().__init__(request, None)
            self.status_code, self.reason = status, "Fake ACS"
            self.headers = {"Content-Type": "application/json", "Location": "https://never-follow.example"}
            self.content_type = "application/json"

        def body(self):
            return json.dumps({"id": "sdk-actual-id"} if status == 201 else
                              {"error": {"code": "Rejected", "message": "sensitive"}}).encode()

    transports = []

    class FakeTransport(HttpTransport):
        def __init__(self):
            self.closed = False
            transports.append(self)

        def open(self):
            pass

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def send(self, request, **kwargs):
            attempts.append(request)
            return FakeResponse(request)

    token = jwt.encode({"exp": int(time.time()) + 600}, "fake-test-key-that-is-long-enough")
    sender = chat.AcsChatSender(transport_factory=FakeTransport)
    if status == 201:
        assert sender.send("https://example.communication.azure.com", token, THREAD, "exact preview", "ESAF") == "sdk-actual-id"
    else:
        with pytest.raises(AzureError):
            sender.send("https://example.communication.azure.com", token, THREAD, "exact preview", "ESAF")
    assert len(attempts) == 1
    assert attempts[0].method == "POST"
    assert "never-follow" not in attempts[0].url
    assert json.loads(attempts[0].body)["content"] == "exact preview"
    assert json.loads(attempts[0].body)["type"] == "text"
    assert len(transports) == 2 and all(transport.closed for transport in transports)


def test_chat_identity_client_and_managed_identity_are_no_retry_bounded_and_closed(monkeypatch):
    import azure.communication.identity
    import azure.core.pipeline.transport
    import azure.identity

    client = Mock()
    client.get_token.return_value = SimpleNamespace(token="server-only")
    factory = Mock(return_value=client)
    credential, transport = Mock(), Mock()
    managed = Mock(return_value=credential)
    transport_factory = Mock(return_value=transport)
    monkeypatch.setattr(azure.communication.identity, "CommunicationIdentityClient", factory)
    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", managed)
    monkeypatch.setattr(azure.core.pipeline.transport, "RequestsTransport", transport_factory)
    service = AcsTokenService(TeamsMeetingSettings.model_validate(enabled_config(**chat_config())))
    identity = MeetingIdentity("8:acs:existing", "browser-voip", time.time() + 3600)
    assert service.chat_token(identity) == "server-only"
    for options in [factory.call_args.kwargs, managed.call_args.kwargs]:
        assert options["retry_total"] == 0 and options["redirect_max"] == 0
        assert options["connection_timeout"] == 10 and options["read_timeout"] == 20
    assert factory.call_args.kwargs["transport"] is transport
    transport_factory.assert_called_once_with(connection_timeout=10, read_timeout=20)
    credential.close.assert_called_once()
    transport.close.assert_called_once()


@pytest.mark.parametrize("heading", [
    "See https://evil.example/phishing or www.evil.example", "Read (evil.example) now",
])
def test_same_scope_citation_does_not_make_unsafe_title_urls_eligible(heading):
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal, answer(citations=[{
            "source_url": SOURCE, "heading": heading,
        }]))
        draft = preview(client, entry, offer).json()
        assert "evil.example" not in draft["content"]
        assert draft["links"] == [{"title": "Source 1", "url": SOURCE}]


def test_admission_pins_deep_chat_settings_before_identity_issue():
    app = app_for_meetings(**chat_config())
    issue = app.state.teams_meeting_token_service.issue

    def raced():
        identity = issue()
        app.state.settings.teams_meetings.chat_allowed_link_hosts.append("new.example")
        return identity

    app.state.teams_meeting_token_service.issue = raced
    with TestClient(app) as client:
        assert create(client).status_code == 403
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
        assert not app.state.teams_meeting_registry.sessions


def test_restricted_original_admission_cannot_be_elevated_by_unrestricted_command():
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal)
        draft = preview(client, entry, offer).json()
        entry.principal = replace(entry.principal, scope_ceiling=frozenset())
        assert send(client, entry, draft).status_code == 403
        app.state.teams_meeting_token_service.chat_token.assert_not_called()


def test_offer_failure_has_no_chat_credentials_and_does_not_break_voice():
    with admitted() as (app, client, entry, principal, _):
        change_settings(app, chat_enabled=False)
        original = answer()
        assert capture(app, entry, principal, original) == original
        assert entry.chat_offer is None
        app.state.teams_meeting_token_service.chat_token.assert_not_called()


def test_public_source_url_never_discloses_private_heading_or_source_path_in_chat_preview_or_send():
    with admitted() as (app, client, entry, principal, _):
        offer = capture(app, entry, principal, answer(citations=[{
            "source_url": SOURCE, "heading": "Confidential customer revenue",
            "source_path": "Private acquisition plan",
        }]))
        draft = preview(client, entry, offer).json()
        assert draft["links"] == [{"title": "Source 1", "url": SOURCE}]
        assert "Confidential" not in draft["content"] and "Private" not in draft["content"]
        assert send(client, entry, draft).status_code == 200
        content = app.state.teams_meeting_chat_sender.send.call_args.args[3]
        assert content == f"ESAF Agent Chat sources:\n1. Source 1\n{SOURCE}"


@pytest.mark.parametrize("stage,error", [
    ("token", ImportError("private import failure")),
    ("token", ServiceRequestError("private token service failure")),
    ("send", ServiceRequestError("private delivery failure")),
    ("send", RuntimeError("private unexpected failure")),
])
def test_chat_preparation_and_send_failures_leave_voice_running(stage, error):
    with admitted() as (app, client, entry, principal, _):
        voice = entry.voice_session
        offer = capture(app, entry, principal)
        assert preview(client, entry, offer, thread_id="19:wrong@thread.v2").status_code == 403
        draft = preview(client, entry, offer).json()
        target = (app.state.teams_meeting_token_service.chat_token if stage == "token"
                  else app.state.teams_meeting_chat_sender.send)
        target.side_effect = error
        response = send(client, entry, draft)
        assert response.status_code == 502 and "private" not in response.text
        assert entry.voice_session is voice and entry.consumed and not entry.revoked
        voice.end.assert_not_awaited()
        assert capture(app, entry, principal)["chat_links"]["count"] == 1
        assert target.call_count == 1


def test_chat_disabled_answer_hook_works_when_optional_sdk_is_not_installed(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "azure.communication.chat", None)
    with admitted(chat_enabled=False) as (app, client, entry, principal, _):
        frame = answer()
        assert capture(app, entry, principal, frame) == frame
        assert entry.chat_offer is None
        entry.voice_session.end.assert_not_awaited()
        app.state.teams_meeting_token_service.chat_token.assert_not_called()


@pytest.mark.parametrize("validation", ["passed", "sources_attached"])
def test_completed_native_answers_offer_server_citations_without_requiring_spoken_markers(validation):
    with admitted() as (app, client, entry, principal, _):
        frame = answer(citation_validation=validation, audio_provisional=True)
        offer = capture(app, entry, principal, frame)
        assert offer["chat_links"]["count"] == 1
        draft = preview(client, entry, offer).json()
        assert draft["links"] == [{"title": "Source 1", "url": SOURCE}]
        app.state.teams_meeting_token_service.chat_token.assert_not_called()
        app.state.teams_meeting_chat_sender.send.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"citation_validation": "failed"}, {"citation_validation": "unknown"},
    {"citation_validation": "provisional"}, {"citation_validation": None},
    {"type": "assistant_transcript", "final": False},
    {"type": "assistant_transcript", "final": True},
    {"authoritative": False}, {"scope_key": "other-scope"}, {"audience": "platform"},
    {"citations": [{"source_url": "https://unapproved.example/source"}]},
])
def test_sources_attached_does_not_bypass_completed_authoritative_scope_and_url_gates(changes):
    with admitted() as (app, client, entry, principal, _):
        frame = answer(**{"citation_validation": "sources_attached", **changes})
        assert "chat_links" not in capture(app, entry, principal, frame)
        assert entry.chat_offer is None
