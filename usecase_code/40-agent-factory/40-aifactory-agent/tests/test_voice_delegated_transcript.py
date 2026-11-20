"""Transcript-triggered delegation against a provider that ignores forced tool choice."""
import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from aifactory_agent.voice import VoiceAnswerError
from aifactory_agent.voice_settings import VoiceSettings
from test_voice_delegated import Upstream, audio, done, tick
from test_voice_routes import (
    ANSWER, OBJECT_ID, Conversation, build, collect, ended, finish, got, hello, make_settings,
)
from voice_fakes import FakeChannel, FakeUpstream, PCM


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TextInsteadOfToolUpstream(FakeUpstream):
    """Reproduce the live provider's completed assistant text instead of a forced call."""

    def __init__(self):
        super().__init__()
        self.push({"type": "session.created"})
        self.heard = False

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
            if event["response"]["modalities"] == ["text", "audio"]:
                self.push({"type": "error", "error": {
                    "code": "invalid_value", "param": "response.output_modalities",
                }})
                return
            self.push({"type": "response.created", "response": {"id": "speech1"}})
            speaking = "audio" in event["response"]["modalities"]
            output = {"id": "spoken1", "type": "message", "status": "completed", "role": "assistant",
                      "content": [{"type": "audio", "transcript": "Provisional reply"}] if speaking else
                                 [{"type": "text", "text": "Model-authored business answer, not evidence."}]}
            self.push({"type": "response.output_item.added", "response_id": "speech1", "item": output})
            if speaking:
                self.push({"type": "response.output_audio.delta", "response_id": "speech1", "item_id": "spoken1",
                           "content_index": 0, "delta": base64.b64encode(PCM).decode()})
            self.push({"type": "response.done", "response": {
                "id": "speech1", "status": "completed", "output": [output]}})


def test_transcript_route_calls_same_backend_even_when_provider_ignores_forced_tool_choice():
    class Gateway:
        async def connect(self, current):
            self.upstream = TextInsteadOfToolUpstream()
            return self.upstream

    gateway, conversation = Gateway(), Conversation()
    current = make_settings(mode="delegated", model="gpt-realtime-mini", api_version="2026-07-15",
                            delegation_trigger="transcript")
    app = build(current, conversation, gateway)
    with TestClient(app) as client:
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello())
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            seen = collect(socket, lambda events: ended(events) or
                           (events[-1].get("type") == "transcript"
                            and events[-1].get("role") == "assistant"))
            assert len(conversation.calls) == 1
            question, audience, principal, scope = conversation.calls[0]
            assert (question, audience, principal.object_id, scope) == (
                "Original question", "project", OBJECT_ID, "project001-dev")
            answer_index = next(i for i, event in enumerate(seen) if event.get("type") == "answer")
            audio_index = next(i for i, event in enumerate(seen) if "audio" in event)
            assert answer_index < audio_index
            assert seen[answer_index]["authoritative"] is True
            assert seen[answer_index]["answer"] == ANSWER["answer"]
            assert seen[answer_index]["citations"] == ANSWER["citations"]
            assert seen[-1]["provisional"] is True
            assert len(gateway.upstream.of("response.create")) == 1
            assert gateway.upstream.of("response.create")[0]["response"]["tool_choice"] == "none"
            assert all(event["item"]["type"] != "function_call_output"
                       for event in gateway.upstream.of("conversation.item.create"))
            finish(socket)


def transcript_setup(answer=None, authorize=None, **options):
    from aifactory_agent.voice_delegated import TranscriptDelegatedVoiceSession
    up, channel, calls = Upstream(), FakeChannel(), []

    async def backend(question):
        calls.append(question)
        return {"answer": "Approved answer [S1].", "citations": [{"citation_id": "S1"}]}

    voice = VoiceSettings(mode="delegated", model="gpt-realtime-mini", greeting=None,
                          delegation_trigger="transcript")
    session = TranscriptDelegatedVoiceSession(voice, up, channel, answer or backend,
                                             authorize=authorize or (lambda: None), **options)
    up.session, up.ack_truncate = session, True
    return session, up, channel, calls


async def transcribe(session, identifier="user1", text="Original question"):
    await session._handle_upstream({"type": "input_audio_buffer.speech_started", "item_id": identifier})
    await session._handle_upstream({"type": "conversation.item.input_audio_transcription.completed",
                                   "item_id": identifier, "transcript": text})
    await tick()


async def speech_created(session):
    await session._handle_upstream({"type": "response.created", "response": {"id": "speech1"}})
    await session._handle_upstream({"type": "response.output_item.added", "response_id": "speech1",
                                   "item": {"id": "spoken1", "type": "message", "role": "assistant"}})


@pytest.mark.anyio
async def test_backend_then_untrusted_context_ack_then_single_speech_response():
    entered, finish_backend = asyncio.Event(), asyncio.Event()

    async def answer(question):
        entered.set()
        await finish_backend.wait()
        return {"answer": "Approved answer [S1].", "citations": [{"citation_id": "S1"}]}

    session, up, channel, calls = transcript_setup(answer=answer)
    send = up.send

    async def hold_context_ack(event):
        if event["type"] == "conversation.item.create":
            await FakeUpstream.send(up, event)
        else:
            await send(event)

    up.send = hold_context_ack
    try:
        policy = session._session_event()["session"]
        assert policy["tools"] == [] and policy["tool_choice"] == "none"
        assert policy["turn_detection"]["create_response"] is False
        assert policy["turn_detection"]["interrupt_response"] is False
        assert "untrusted" in policy["instructions"].lower()
        assert "en-US" in policy["instructions"]
        await transcribe(session)
        assert entered.is_set() and not up.of("response.create") and not channel.of("answer")
        finish_backend.set()
        await tick()
        assert channel.of("answer")[0]["authoritative"] is True
        assert not up.of("response.create") and not channel.audio
        context = up.of("conversation.item.create")[0]["item"]
        assert context["type"] == "message" and context["role"] == "user"
        assert context["content"][0]["type"] == "input_text" and "call_id" not in context
        label, encoded = context["content"][0]["text"].split("\n", 1)
        assert "untrusted" in label.lower() and "not" in label.lower()
        result = json.loads(encoded)
        assert result["answer"] == channel.of("answer")[0]["answer"]
        assert result["citations"] == [{"citation_id": "S1"}]
        await session._handle_upstream({"type": "conversation.item.created", "item": context})
        await tick()
        assert [event["response"] for event in up.of("response.create")] == [{
            "modalities": ["audio"], "tool_choice": "none", "max_output_tokens": 1024}]
        await speech_created(session)
        await audio(session)
        assert channel.audio == [PCM]
    finally:
        finish_backend.set()
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("event", [
    {"type": "response.created", "response": {"id": "unsolicited"}},
    {"type": "response.output_audio.delta", "response_id": "unsolicited", "item_id": "spoken1",
     "content_index": 0, "delta": base64.b64encode(PCM).decode()},
    {"type": "response.text.delta", "response_id": "unsolicited", "delta": "Independent answer"},
])
async def test_no_provider_response_or_audio_is_accepted_before_backend_completes(event):
    gate = asyncio.Event()

    async def answer(question):
        await gate.wait()
        return ANSWER

    session, up, channel, calls = transcript_setup(answer=answer)
    try:
        await transcribe(session)
        await session._handle_upstream(event)
        assert session._ended.is_set()
        assert not channel.audio and not channel.of("answer") and not up.of("response.create")
    finally:
        gate.set()
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("when", ["before_backend", "after_backend", "before_audio"])
async def test_transcript_reauthorizes_at_each_trust_boundary(when):
    allowed = when != "before_backend"
    calls = []

    def authorize():
        if not allowed:
            raise PermissionError

    async def answer(question):
        nonlocal allowed
        calls.append(question)
        if when == "after_backend":
            allowed = False
        return ANSWER

    session, up, channel, _ = transcript_setup(answer=answer, authorize=authorize)
    try:
        await transcribe(session)
        if when == "before_audio":
            await speech_created(session)
            allowed = False
            await audio(session)
        else:
            assert not channel.of("answer") and not up.of("response.create")
        assert len(calls) == (0 if when == "before_backend" else 1)
        assert session._ended.is_set() and not channel.audio
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("stop", ["interrupt", "end"])
async def test_cancelled_transcript_backend_cannot_publish_late_completion(stop):
    gate, entered, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def answer(question):
        entered.set()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await gate.wait()
        return ANSWER

    session, up, channel, calls = transcript_setup(answer=answer)
    try:
        await transcribe(session)
        assert entered.is_set()
        await session.handle_control({"type": stop})
        await asyncio.wait_for(cancelled.wait(), 1)
        gate.set()
        await tick()
        assert not channel.of("answer") and not channel.audio
        assert not up.of("conversation.item.create") and not up.of("response.create")
    finally:
        gate.set()
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["send", "missing_ack", "provider_error"])
async def test_context_creation_failure_never_requests_speech(failure):
    session, up, channel, calls = transcript_setup(handshake_timeout=0.01)
    send = up.send

    async def fail_context(event):
        if event["type"] != "conversation.item.create":
            return await send(event)
        if failure == "send":
            raise RuntimeError("context send failed")
        await FakeUpstream.send(up, event)
        if failure == "provider_error":
            await session._handle_upstream({"type": "error", "error": {"code": "invalid_request_error"}})

    up.send = fail_context
    try:
        await transcribe(session)
        await asyncio.wait_for(session._ended.wait(), 1)
        assert calls == ["Original question"]
        assert channel.of("answer")[0]["answer"] == "Approved answer [S1]."
        assert not up.of("response.create") and not channel.audio
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [
    VoiceAnswerError("forbidden", "Read permission denied"),
    VoiceAnswerError("dependency_unavailable", "Backend unavailable"),
    RuntimeError("backend failed"),
    {"answer": "Missing evidence"},
    {"answer": "", "citations": []},
])
async def test_backend_failures_close_without_model_fallback_or_self_cancellation(failure):
    async def answer(question):
        if isinstance(failure, Exception):
            raise failure
        return failure

    session, up, channel, calls = transcript_setup(answer=answer)
    try:
        await transcribe(session)
        await asyncio.wait_for(session._ended.wait(), 1)
        await tick()
        assert session._answer_task.done() and not session._answer_task.cancelled()
        assert not channel.of("answer") and not channel.audio
        assert not up.of("conversation.item.create") and not up.of("response.create")
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["backend", "speech"])
async def test_transcript_first_answer_and_speech_deadlines_close(stage):
    gate = asyncio.Event()

    async def answer(question):
        if stage == "backend":
            await gate.wait()
        return ANSWER

    session, up, channel, calls = transcript_setup(answer=answer, answer_timeout=0.02)
    try:
        await transcribe(session)
        await asyncio.wait_for(session._ended.wait(), 1)
        assert not channel.audio
        assert len(up.of("response.create")) == (1 if stage == "speech" else 0)
    finally:
        gate.set()
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_repeated_question_waits_for_playback_truncation_and_deletes_old_context():
    clock = [0.0]
    session, up, channel, calls = transcript_setup(audio_clock=lambda: clock[0])
    try:
        await transcribe(session)
        await speech_created(session)
        await audio(session)
        await done(session, "speech1", [{"id": "spoken1", "type": "message", "role": "assistant",
                                        "content": [{"type": "audio", "transcript": "Provisional reply"}]}])
        first_context = up.of("conversation.item.create")[0]["item"]["id"]
        metadata = channel.of("audio_chunk")[-1]
        clock[0] = 0.02
        await session.handle_control({"type": "playback", "item_id": "spoken1",
                                      "playback_id": metadata["playback_id"], "played_samples": 240})
        up.ack_truncate = False
        await transcribe(session, "user2")
        assert calls == ["Original question"] and len(up.of("response.create")) == 1
        truncation = up.of("conversation.item.truncate")[-1]
        assert truncation["audio_end_ms"] == 10
        await session._handle_upstream({**truncation, "type": "conversation.item.truncated"})
        await tick()
        assert calls == ["Original question", "Original question"]
        assert len(up.of("response.create")) == 2
        assert {"user1", "spoken1", first_context} <= {
            event["item_id"] for event in up.of("conversation.item.delete")}
        assert len(channel.of("answer")) == 2 and not session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_barge_in_during_context_ack_wait_cannot_approve_abandoned_answer():
    session, up, channel, calls = transcript_setup()
    send = up.send

    async def hold_context_ack(event):
        if event["type"] == "conversation.item.create":
            return await FakeUpstream.send(up, event)
        await send(event)

    up.send = hold_context_ack
    try:
        await transcribe(session)
        old_context = up.of("conversation.item.create")[0]["item"]
        assert not up.of("response.create")
        await session._barge_in()
        await session._handle_upstream({"type": "conversation.item.created", "item": old_context})
        await tick()
        assert not up.of("response.create") and session._approved_turn is None
        up.send = send
        await transcribe(session, "user2", "New question")
        assert calls == ["Original question", "New question"]
        assert old_context["id"] in [event["item_id"] for event in up.of("conversation.item.delete")]
        assert len(up.of("response.create")) == 1 and not session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_transcript_session_uses_selected_multilingual_policy():
    session, up, channel, calls = transcript_setup()
    try:
        from aifactory_agent.voice_delegated import TranscriptDelegatedVoiceSession
        voice = session.voice.model_copy(update={"multilingual": True, "input_languages": ["sv-SE", "en-US"]})
        session = TranscriptDelegatedVoiceSession(voice, up, channel, session._answer, authorize=lambda: None)
        policy = session._session_event()["session"]
        assert "latest user's language" in policy["instructions"] and "sv-SE" in policy["instructions"]
        assert "language" not in policy["input_audio_transcription"]
        assert policy["turn_detection"]["type"] == "azure_semantic_vad_multilingual"
        assert policy["tools"] == [] and policy["tool_choice"] == "none"
    finally:
        await session._shutdown("test", 0)
