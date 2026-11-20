"""Attended meeting transport must retain the deployed direct Voice Live delegation."""
import asyncio
import base64
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from aifactory_agent import security
from aifactory_agent.teams_meeting_routes import end_meeting_session
from aifactory_agent.teams_meeting_settings import TeamsMeetingSettings
from aifactory_agent.voice_settings import VoiceSettings
from test_teams_meeting_routes import TokenService, create, reset_voice
from test_teams_meeting_settings import enabled_config
from test_voice_routes import (
    ANSWER, GOOD, Conversation, build, collect, ended, finish, got, hello, make_settings,
)
from voice_fakes import FakeUpstream, PCM


class DelegatingUpstream(FakeUpstream):
    def __init__(self):
        super().__init__()
        self.push({"type": "session.created"})
        self.heard = False

    def speech(self):
        return [
            {"type": "response.created", "response": {"id": "speech1"}},
            {"type": "response.output_item.added", "response_id": "speech1", "item": {
                "id": "spoken1", "type": "message", "role": "assistant", "status": "in_progress"}},
            {"type": "response.output_audio.delta", "response_id": "speech1", "item_id": "spoken1",
             "content_index": 0, "delta": base64.b64encode(PCM).decode()},
            {"type": "response.done", "response": {"id": "speech1", "status": "completed", "output": [{
                "id": "spoken1", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "audio", "transcript": "Approved answer"}]}]}},
        ]

    async def send(self, event):
        await super().send(event)
        kind = event["type"]
        if kind == "session.update":
            self.push({"type": "session.updated", "session": event["session"]})
        elif kind == "input_audio_buffer.append" and not self.heard:
            self.heard = True
            self.push({"type": "input_audio_buffer.speech_started", "item_id": "user1"})
            self.push({"type": "conversation.item.input_audio_transcription.completed",
                       "item_id": "user1", "transcript": "Original question"})
        elif kind == "conversation.item.create":
            self.push({"type": "conversation.item.created", "item": event["item"]})
        elif kind == "response.create":
            if event["response"]["modalities"] == ["text"]:
                self.push({"type": "response.created", "response": {"id": "tool1"}})
                self.push({"type": "response.done", "response": {
                    "id": "tool1", "status": "completed", "output": [{
                        "id": "toolitem1", "type": "function_call", "status": "completed",
                        "call_id": "call1", "name": "ask_specialist",
                        "arguments": '{"question":"Original question"}'}]}})
            else:
                for frame in self.speech():
                    self.push(frame)


class Gateway:
    def __init__(self):
        self.upstreams = []

    async def connect(self, current):
        upstream = DelegatingUpstream()
        self.upstreams.append(upstream)
        return upstream


def meeting_app(trigger, conversation=None):
    settings = make_settings(mode="delegated", model="gpt-realtime-mini", delegation_trigger=trigger)
    settings = settings.model_copy(update={
        "teams_meetings": TeamsMeetingSettings.model_validate(enabled_config())})
    app = build(settings, conversation or Conversation(), Gateway())
    app.state.teams_meeting_token_service = TokenService()
    app.state.chat_events = Mock()
    return app


def spoken(seen):
    return any("audio" in frame for frame in seen) and seen[-1] == {"type": "state", "state": "listening"}


def test_delegation_does_not_change_default_or_existing_native_settings():
    assert VoiceSettings().mode == "speech_shell"
    assert VoiceSettings(mode="realtime", model="gpt-realtime-mini").mode == "realtime"
    assert VoiceSettings(mode="delegated", model="gpt-realtime-mini").delegation_trigger == "model_tool"


@pytest.mark.parametrize("trigger", ["model_tool", "transcript"])
def test_meeting_dispatches_delegation_with_exact_scope_knowledge_only_and_question_telemetry(trigger, caplog):
    from aifactory_agent.voice_delegated import DelegatedVoiceSession, TranscriptDelegatedVoiceSession

    conversation = Conversation()
    app = meeting_app(trigger, conversation)
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            ready = collect(socket, got("ready"))[-1]
            assert ready["mode"] == "delegated" and ready["playback_receipts"]
            session = app.state.teams_meeting_registry.sessions[body["session_id"]].voice_session
            assert type(session) is (TranscriptDelegatedVoiceSession if trigger == "transcript" else DelegatedVoiceSession)
            socket.send_bytes(PCM)
            seen = collect(socket, spoken)
            answers = [frame for frame in seen if frame.get("type") == "answer"]
            assert len(answers) == 1 and answers[0]["authoritative"]
            assert answers[0]["answer"] == ANSWER["answer"] and answers[0]["citations"] == ANSWER["citations"]
            assert seen.index(answers[0]) < next(i for i, frame in enumerate(seen) if "audio" in frame)
            assert len(conversation.calls) == 1
            question, audience, principal, scope = conversation.calls[0]
            assert (question, audience, scope) == ("Original question", "project", "project001-dev")
            assert principal.authorization_context == "teams_meeting"
            assert principal.scope_ceiling == frozenset({"project001-dev"})
            assert principal.permission_ceiling == frozenset({"knowledge.read"})
            security.authorize(app.state.settings, principal, scope, "knowledge.read")
            for denied_scope, permission in [
                ("other-project", "knowledge.read"), (scope, "factory.read"), (scope, "cost.read"),
                (scope, "graph.read"), (scope, "config.write"), (scope, "knowledge.refresh"),
            ]:
                with pytest.raises(PermissionError):
                    security.authorize(app.state.settings, principal, denied_scope, permission)
            app.state.chat_events.question.assert_called_once_with(session.session_id)
            finish(socket)
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]
    assert "Original question" not in caplog.text and body["meeting_session"] not in caplog.text


@pytest.mark.parametrize("trigger", ["model_tool", "transcript"])
@pytest.mark.parametrize("change", ["grant", "listener_policy", "revoked"])
def test_meeting_delegated_reauthorizes_backend_result_and_never_speaks_after_revocation(trigger, change):
    conversation = Conversation()
    app = meeting_app(trigger, conversation)
    answer = conversation.answer

    def revoke(*args):
        result = answer(*args)
        if change == "grant":
            app.state.settings = app.state.settings.model_copy(update={
                "auth": app.state.settings.auth.model_copy(update={"grants": []})})
        elif change == "listener_policy":
            app.state.settings = app.state.settings.model_copy(update={
                "teams_meetings": app.state.settings.teams_meetings.model_copy(update={"enabled": False})})
        else:
            next(iter(app.state.teams_meeting_registry.sessions.values())).revoked = True
        return result

    conversation.answer = revoke
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            seen = collect(socket, ended)
            assert not any("audio" in frame or frame.get("type") in {"answer", "audio_chunk"} for frame in seen)
            upstream = app.state.voice_gateway.upstreams[0]
            assert not any(event["type"] == "conversation.item.create" for event in upstream.sent)
            assert len(conversation.calls) == 1
            with pytest.raises(PermissionError):
                security.authorize(app.state.settings, conversation.calls[0][2], "project001-dev", "knowledge.read")
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


@pytest.mark.parametrize("trigger", ["model_tool", "transcript"])
def test_reset_isolates_inflight_delegated_backend_and_stale_provider_without_revoking_acs(trigger):
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    conversation = Conversation()
    answer = conversation.answer

    def blocked(*args):
        result = answer(*args)
        if len(conversation.calls) == 1:
            entered.set()
            assert release.wait(5)
            completed.set()
        return result

    conversation.answer = blocked
    app = meeting_app(trigger, conversation)
    with TestClient(app) as client:
        body = create(client).json()
        try:
            with client.websocket_connect("/api/voice/ws") as old_socket:
                old_socket.send_text(hello(meeting_session=body["meeting_session"]))
                collect(old_socket, got("ready"))
                old_session = app.state.teams_meeting_registry.sessions[body["session_id"]].voice_session
                old_socket.send_bytes(PCM)
                assert entered.wait(5)
                previous = app.state.voice_gateway.upstreams[0]
                rotated = reset_voice(client, body["session_id"]).json()
                assert rotated["voice_generation"] == 1
                tail = collect(old_socket, ended)
                assert not any("audio" in frame or frame.get("type") == "answer" for frame in tail)
                assert {"type": "closed", "reason": "meeting_voice_reset"} in tail
            assert previous.closed and app.state.teams_meeting_token_service.deleted == []
            with client.websocket_connect("/api/voice/ws") as new_socket:
                new_socket.send_text(hello(meeting_session=rotated["meeting_session"]))
                collect(new_socket, got("ready"))
                release.set()
                assert completed.wait(5)

                async def delayed():
                    for frame in previous.speech() + [
                        {"type": "input_audio_buffer.speech_started", "item_id": "late"},
                        {"type": "conversation.item.input_audio_transcription.completed",
                         "item_id": "late", "transcript": "STALE INPUT"},
                    ]:
                        await old_session._handle_upstream(frame)
                        previous.push(frame)
                    await end_meeting_session(app, body["session_id"], expected_generation=0)
                    await asyncio.sleep(0)

                client.portal.call(delayed)
                new_socket.send_text('{"type":"ping"}')
                seen = collect(new_socket, got("pong"))
                assert not any("audio" in frame or frame.get("type") in {"answer", "audio_chunk", "transcript"}
                               for frame in seen)
                assert len(conversation.calls) == 1 and app.state.teams_meeting_token_service.deleted == []
                assert not any(event["type"] == "conversation.item.create" for event in previous.sent)
                assert app.state.voice_gateway.upstreams[1] is not previous
                new_socket.send_bytes(PCM)
                collect(new_socket, spoken)
                assert len(conversation.calls) == 2
                finish(new_socket)
        finally:
            release.set()
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


@pytest.mark.parametrize("trigger", ["model_tool", "transcript"])
def test_delegated_meeting_uses_real_conversation_readiness_citations_and_only_knowledge_tools(trigger):
    from test_conversation import FakeGateway, FakeItem, injected, response

    conversation = Conversation()
    app = meeting_app(trigger, conversation)
    harness = injected(app.state.settings, gateway=FakeGateway([
        response(calls=[FakeItem("knowledge_search", {"query": "More evidence"})]), response(),
    ]))
    conversation.answer = harness.conversation.answer
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            seen = collect(socket, spoken)
            answer = next(frame for frame in seen if frame.get("type") == "answer")
            assert answer["authoritative"] and answer["answer"] == "An evidenced answer [S1]."
            assert answer["citations"][0]["citation_id"] == "S1"
            assert answer["scope_key"] == "project001-dev"
            assert harness.knowledge.status_calls > 0
            assert harness.knowledge.searches == [
                ("Original question", "project001-dev"), ("More evidence", "project001-dev")]
            assert not harness.tools.executions and not harness.live_requests
            assert [event["name"] for event in harness.audits[0].events] == ["knowledge_search"] * 3
            assert all(event["outcome"] == "completed" for event in harness.audits[0].events)
            assert answer["tool_activity"] == [{"name": "knowledge_search", "call_id": "call-knowledge_search"}]
            principal, scope = harness.tool_requests[0]
            assert principal.permission_ceiling == frozenset({"knowledge.read"}) and scope == "project001-dev"
            finish(socket)


@pytest.mark.parametrize("trigger", ["model_tool", "transcript"])
def test_provider_speech_after_listener_grant_revocation_is_never_delivered(trigger):
    from test_teams_meeting_security import revoke_listener

    app = meeting_app(trigger)
    with TestClient(app) as client:
        body = create(client).json()
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello(meeting_session=body["meeting_session"]))
            collect(socket, got("ready"))
            upstream = app.state.voice_gateway.upstreams[0]
            speech = upstream.speech
            upstream.speech = lambda: speech()[:-1]
            socket.send_bytes(PCM)
            collect(socket, lambda seen: "audio" in seen[-1])
            revoke_listener(app)
            client.portal.call(upstream.push, {
                "type": "response.output_audio.delta", "response_id": "speech1", "item_id": "spoken1",
                "content_index": 0, "delta": base64.b64encode(PCM).decode(),
            })
            seen = collect(socket, ended)
            assert not any("audio" in frame or frame.get("type") in {"answer", "audio_chunk"} for frame in seen)
        assert app.state.teams_meeting_token_service.deleted == ["user-0"]


@pytest.mark.parametrize("trigger", ["model_tool", "transcript"])
def test_reset_prevents_late_real_conversation_tool_execution_even_with_stale_settings(trigger):
    from test_conversation import FakeItem, injected, response

    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    conversation = Conversation()
    app = meeting_app(trigger, conversation)
    harness = injected(app.state.settings)

    @contextmanager
    def open_model(_):
        def respond(*_):
            entered.set()
            assert release.wait(5)
            return response(calls=[FakeItem("knowledge_search", {"query": "STALE TOOL"})])

        yield SimpleNamespace(respond=respond)

    harness.gateway.open = open_model

    def answer(*args):
        try:
            return harness.conversation.answer(*args)
        finally:
            completed.set()

    conversation.answer = answer
    with TestClient(app) as client:
        body = create(client).json()
        try:
            with client.websocket_connect("/api/voice/ws") as socket:
                socket.send_text(hello(meeting_session=body["meeting_session"]))
                collect(socket, got("ready"))
                socket.send_bytes(PCM)
                assert entered.wait(5)
                assert reset_voice(client, body["session_id"]).status_code == 200
                seen = collect(socket, ended)
                release.set()
                assert completed.wait(5)
                assert not any("audio" in frame or frame.get("type") == "answer" for frame in seen)
                assert harness.knowledge.searches == [("Original question", "project001-dev")]
                assert not harness.tools.executions and not harness.live_requests
                assert [(event["name"], event["call_id"], event["outcome"]) for event in harness.audits[0].events] == [
                    ("knowledge_search", None, "completed"),
                    ("knowledge_search", "call-knowledge_search", "failed"),
                ]
                assert app.state.teams_meeting_token_service.deleted == []
        finally:
            release.set()
        assert client.delete("/api/teams-meetings/sessions/" + body["session_id"],
                             headers={"Authorization": "Bearer " + GOOD}).status_code == 204
