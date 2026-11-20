"""Delegated native voice contracts; all dependencies are in-process fakes."""
import asyncio
import base64
import json

import pytest

from aifactory_agent.voice import VoiceProtocolError, connection_url
from aifactory_agent.voice_settings import VoiceSettings
from voice_fakes import FakeChannel, FakeUpstream, PCM


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settings(**overrides):
    return VoiceSettings(mode="delegated", model="gpt-realtime", greeting=None, **overrides)


async def tick():
    for _ in range(100):
        await asyncio.sleep(0)


class Upstream(FakeUpstream):
    async def send(self, event):
        await super().send(event)
        if event["type"] == "conversation.item.create":
            await self.session._handle_upstream({"type": "conversation.item.created", "item": event["item"]})
        elif event["type"] == "conversation.item.delete":
            await self.session._handle_upstream({"type": "conversation.item.deleted", "item_id": event["item_id"]})
        elif event["type"] == "conversation.item.truncate" and self.ack_truncate:
            await self.session._handle_upstream({**event, "type": "conversation.item.truncated"})


def setup(answer=None, authorize=None, **options):
    from aifactory_agent.voice_delegated import DelegatedVoiceSession
    up, channel, calls = Upstream(), FakeChannel(), []

    async def backend(question):
        calls.append(question)
        return {"answer": "Approved answer [S1].", "citations": [{"citation_id": "S1"}]}

    session = DelegatedVoiceSession(settings(), up, channel, answer or backend,
                                   authorize=authorize or (lambda: None), **options)
    up.session, up.ack_truncate = session, True
    return session, up, channel, calls


async def begin(session):
    await session._handle_upstream({"type": "input_audio_buffer.speech_started", "item_id": "user1"})
    await session._handle_upstream({"type": "conversation.item.input_audio_transcription.completed",
                                    "item_id": "user1", "transcript": "Original question"})
    await tick()
    await session._handle_upstream({"type": "response.created", "response": {"id": "tool1"}})


def call(**overrides):
    return {"id": "callitem1", "type": "function_call", "status": "completed", "call_id": "call1",
            "name": "ask_specialist", "arguments": '{"question":"Original question"}', **overrides}


async def done(session, response_id="tool1", output=None, status="completed"):
    await session._handle_upstream({"type": "response.done", "response": {
        "id": response_id, "status": status, "output": [call()] if output is None else output}})
    await tick()


async def speaking(session):
    await begin(session)
    await done(session)
    await session._handle_upstream({"type": "response.created", "response": {"id": "speech1"}})
    await session._handle_upstream({"type": "response.output_item.added", "response_id": "speech1",
                                    "item": {"id": "spoken1", "type": "message", "role": "assistant"}})


async def audio(session, kind="response.audio.delta", **overrides):
    await session._handle_upstream({"type": kind, "response_id": "speech1", "item_id": "spoken1",
                                    "content_index": 0, "delta": base64.b64encode(PCM).decode(), **overrides})


def test_delegated_is_opt_in_and_july_does_not_change_old_default():
    assert VoiceSettings().mode == "speech_shell"
    assert VoiceSettings().api_version == "2026-04-10"
    voice = settings(api_version="2026-07-15", multilingual=True, input_languages=["sv-SE", "en-US"])
    assert "api-version=2026-07-15" in connection_url(voice, "resource")
    assert voice.for_language("sv-SE").native_turn_detection() == "azure_semantic_vad_multilingual"


@pytest.mark.anyio
async def test_backend_is_mandatory_and_authoritative_before_any_native_speech():
    session, up, channel, calls = setup()
    try:
        await begin(session)
        first = up.of("response.create")[0]["response"]
        assert first["modalities"] == ["text"]
        assert first["tool_choice"] == {"type": "function", "name": "ask_specialist"}
        assert not calls and not channel.audio and not channel.of("answer")
        await done(session)
        assert calls == ["Original question"]
        assert channel.of("answer")[0]["answer"] == "Approved answer [S1]."
        assert channel.of("answer")[0]["authoritative"] is True
        output = up.of("conversation.item.create")[-1]["item"]
        assert output["type"] == "function_call_output"
        assert json.loads(output["output"])["citations"] == [{"citation_id": "S1"}]
        second = up.of("response.create")[1]["response"]
        assert second["tool_choice"] == "none"
        assert second["modalities"] == ["text", "audio"]
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("outputs", [
    [], [call(), call(id="callitem2", call_id="call2")],
    [call(name="raw_agent")], [call(arguments='{"question":42}')],
    [call(arguments='{"question":"Different invented question"}')],
    [call(arguments='{"question":"Original question","scope_key":"other"}')],
    [call(arguments='{"question":"Original question","question":"Original question"}')],
    [{"id": "message1", "type": "message", "role": "assistant", "content": []}],
])
async def test_absent_multiple_invalid_calls_never_execute_backend(outputs):
    session, up, channel, calls = setup()
    try:
        await begin(session)
        await done(session, output=outputs)
        assert not calls and not channel.audio and not channel.of("answer")
        assert session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_premature_audio_or_unknown_response_ends_without_speaking():
    session, up, channel, calls = setup()
    try:
        await begin(session)
        await audio(session, response_id="tool1")
        assert not channel.audio and not calls and session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_cancelled_backend_cannot_publish_even_if_work_ignores_cancellation():
    entered, finish = asyncio.Event(), asyncio.Event()

    async def answer(text):
        entered.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            await finish.wait()
        return {"answer": "Late answer", "citations": []}

    session, up, channel, calls = setup(answer=answer)
    try:
        await begin(session)
        await done(session)
        await entered.wait()
        await session._barge_in()
        finish.set()
        await tick()
        assert not channel.of("answer") and not channel.audio
        assert not up.of("conversation.item.create")
    finally:
        finish.set()
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_grant_rechecked_after_backend_before_publication():
    allowed = True

    def authorize():
        if not allowed:
            raise PermissionError

    async def answer(text):
        nonlocal allowed
        allowed = False
        return {"answer": "Revoked", "citations": []}

    session, up, channel, calls = setup(answer=answer, authorize=authorize)
    try:
        await begin(session)
        await done(session)
        assert not channel.of("answer") and not channel.audio
        assert not up.of("conversation.item.create")
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["response.audio.delta", "response.output_audio.delta"])
async def test_receipts_bind_to_emitted_audio_and_truncate_only_played_position(kind):
    clock = [0.0]
    session, up, channel, calls = setup(audio_clock=lambda: clock[0])
    try:
        await speaking(session)
        await audio(session, kind)
        metadata = channel.of("audio_chunk")[-1]
        assert metadata["end_sample"] == 480
        clock[0] = 0.02
        await session.handle_control({"type": "playback", "item_id": "spoken1",
                                      "playback_id": metadata["playback_id"], "played_samples": 240})
        await session._barge_in()
        await tick()
        truncate = up.of("conversation.item.truncate")[-1]
        assert truncate["item_id"] == "spoken1" and truncate["audio_end_ms"] == 10
        assert channel.of("interrupted")
        await audio(session)
        assert len(channel.audio) == 1
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["fabricated", "overreported", "backwards", "too_fast"])
async def test_invalid_receipts_rejected(fault):
    clock = [0.0]
    session, up, channel, calls = setup(audio_clock=lambda: clock[0])
    try:
        await speaking(session)
        await audio(session)
        metadata = channel.of("audio_chunk")[-1]
        clock[0] = 0.02
        receipt = {"type": "playback", "item_id": "spoken1",
                   "playback_id": metadata["playback_id"], "played_samples": 240}
        await session.handle_control(receipt)
        if fault == "fabricated":
            receipt["item_id"] = "invented"
        elif fault == "overreported":
            receipt["played_samples"] = 481
        elif fault == "backwards":
            receipt["played_samples"] = 120
        else:
            clock[0], receipt["played_samples"] = 0.01, 480
        with pytest.raises(VoiceProtocolError):
            await session.handle_control(receipt)
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_missing_truncate_ack_requires_fresh_connection():
    session, up, channel, calls = setup(handshake_timeout=0.01)
    try:
        await speaking(session)
        await audio(session)
        up.ack_truncate = False
        await session._barge_in()
        await asyncio.sleep(0.03)
        assert session._ended.is_set()
        assert not up.of("response.create")[2:]
    finally:
        await session._shutdown("test", 0)


def test_worklet_receipts_exclude_unrendered_or_flushed_audio():
    from test_voice_frontend import WORKLET_HARNESS, STATIC, node
    node(WORKLET_HARNESS + r"""
const processors = load(process.argv[2], 24000);
const player = new processors["voice-playback"]();
player.port.onmessage({data: {audio: new Int16Array(480).buffer, playback_id: "p1",
  item_id: "s1", start_sample: 0}});
assert.equal(player.port.posts.length, 0);
player.process([], [[new Float32Array(120)]]);
const receipt = player.port.posts.find(x => x && x.playback_id);
assert.equal(receipt.played_samples, 120);
player.port.onmessage({data: null});
player.process([], [[new Float32Array(480)]]);
assert.equal(player.port.posts.filter(x => x && x.playback_id).length, 1);
""", STATIC / "voice-playback-worklet.js")


@pytest.mark.anyio
async def test_tool_output_waiting_for_socket_lock_is_never_written_after_barge_in():
    entered, finish = asyncio.Event(), asyncio.Event()

    async def answer(text):
        entered.set()
        await finish.wait()
        return {"answer": "Valid but abandoned", "citations": []}

    session, up, channel, calls = setup(answer=answer)
    try:
        await begin(session)
        await done(session)
        await entered.wait()
        await session._write_lock.acquire()
        finish.set()
        await tick()
        assert channel.of("answer")
        await session._barge_in()
        session._write_lock.release()
        await tick()
        assert not up.of("conversation.item.create")
    finally:
        if session._write_lock.locked():
            session._write_lock.release()
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_replayed_done_never_calls_specialist_twice_and_unknown_audio_fails_closed():
    session, up, channel, calls = setup()
    try:
        await begin(session)
        await done(session)
        await done(session)
        assert calls == ["Original question"]
        assert session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_permission_revocation_during_speech_closes_without_more_audio():
    allowed = True

    def authorize():
        if not allowed:
            raise PermissionError

    session, up, channel, calls = setup(authorize=authorize)
    try:
        await speaking(session)
        allowed = False
        await audio(session)
        assert session._ended.is_set()
        assert not channel.audio
    finally:
        await session._shutdown("test", 0)


def test_browser_waits_for_device_clock_and_drops_old_callbacks_and_inflight_audio():
    from test_voice_frontend import CLIENT_HARNESS, STATIC, node
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  rig.socket.json({type: "ready", mode: "delegated", playback_receipts: true});
  let audible = 0;
  rig.context.getOutputTimestamp = () => ({contextTime: audible});
  const metadata = {type: "audio_chunk", playback_id: "p1", item_id: "s1", start_sample: 0, end_sample: 480};
  rig.socket.json(metadata);
  rig.socket.audio(new Uint8Array(960));
  const tagged = rig.playback.port.posts.at(-1);
  assert.equal(tagged.playback_id, "p1");
  const receipt = {playback_id: "p1", item_id: "s1", epoch: tagged.epoch, played_samples: 240, context_time: 0.01};
  rig.playback.port.onmessage({data: receipt});
  assert.equal(rig.socket.sent.length, 1, "rendered but not yet at device is not played");
  audible = 0.01;
  rig.env.intervals[0].callback();
  assert.equal(JSON.parse(rig.socket.sent.at(-1)).played_samples, 240);
  rig.client.interrupt();
  assert.equal(rig.playback.port.posts.at(-1), null);
  const count = rig.playback.port.posts.length;
  rig.socket.json({...metadata, start_sample: 480, end_sample: 960});
  rig.socket.audio(new Uint8Array(960));
  assert.equal(rig.playback.port.posts.length, count, "audio already in-flight is not restarted after local stop");
  audible = 1;
  rig.playback.port.onmessage({data: {...receipt, played_samples: 480}});
  rig.env.intervals[0].callback();
  assert.equal(rig.socket.sent.filter(x => typeof x === "string" && JSON.parse(x).type === "playback").length, 1);
  rig.socket.json({type: "interrupted"});
  rig.socket.json({type: "answer", answer: "Authoritative [S1]", citations: [{citation_id: "S1"}], authoritative: true});
  rig.socket.json({type: "transcript", role: "assistant", text: "Rephrased", final: true, provisional: true});
  assert.equal(rig.log.answers[0].answer, "Authoritative [S1]");
  assert.equal(rig.log.transcripts.at(-1)[3], true);
  await rig.client.stop();
})().catch(error => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


class RouteUpstream(FakeUpstream):
    def __init__(self):
        super().__init__()
        self.push({"type": "session.created"})
        self.responses = 0
        self.heard = False

    async def send(self, event):
        await super().send(event)
        kind = event["type"]
        if kind == "session.update":
            self.push({"type": "session.updated"})
        elif kind == "input_audio_buffer.append" and not self.heard:
            self.heard = True
            self.push({"type": "input_audio_buffer.speech_started", "item_id": "user1"})
            self.push({"type": "conversation.item.input_audio_transcription.completed",
                       "item_id": "user1", "transcript": "Original question"})
        elif kind == "conversation.item.create":
            self.push({"type": "conversation.item.created", "item": event["item"]})
        elif kind == "response.create":
            self.responses += 1
            rid = f"resp{self.responses}"
            self.push({"type": "response.created", "response": {"id": rid}})
            if self.responses == 1:
                output = [call()]
            else:
                output = [{"id": "spoken1", "type": "message", "role": "assistant",
                           "content": [{"type": "audio", "transcript": "Spoken rephrasing"}]}]
                self.push({"type": "response.output_item.added", "response_id": rid, "item": output[0]})
                self.push({"type": "response.output_audio.delta", "response_id": rid, "item_id": "spoken1",
                           "content_index": 0, "delta": base64.b64encode(PCM).decode()})
            self.push({"type": "response.done", "response": {"id": rid, "status": "completed", "output": output}})


def test_real_route_binds_exact_conversation_and_delivers_authoritative_then_native_audio():
    from fastapi.testclient import TestClient
    from test_voice_routes import Conversation, GOOD, build, collect, ended, finish, got, hello, make_settings

    class Gateway:
        async def connect(self, current):
            self.upstream = RouteUpstream()
            return self.upstream

    gateway, conversation = Gateway(), Conversation()
    app = build(make_settings(mode="delegated", model="gpt-realtime", api_version="2026-07-15"),
                conversation, gateway)
    with TestClient(app) as client:
        status = client.get("/api/voice/status", headers={"Authorization": "Bearer " + GOOD}).json()
        assert status["mode"] == "delegated" and status["embedded_voice_version"] == 1
        with client.websocket_connect("/api/voice/ws") as socket:
            socket.send_text(hello())
            collect(socket, got("ready"))
            socket.send_bytes(PCM)
            seen = collect(socket, lambda events: events[-1].get("type") == "transcript"
                           and events[-1].get("role") == "assistant")
            answer_index = next(i for i, event in enumerate(seen) if event.get("type") == "answer")
            audio_index = next(i for i, event in enumerate(seen) if "audio" in event)
            assert answer_index < audio_index
            assert seen[answer_index]["authoritative"] is True
            assert seen[-1]["provisional"] is True
            assert conversation.calls[0][0] == "Original question"
            assert conversation.calls[0][1] == "project"
            assert conversation.calls[0][3] == "project001-dev"
            assert len(conversation.calls) == 1
            finish(socket)


@pytest.mark.anyio
async def test_active_tool_output_send_is_cancelled_and_uncertain_connection_not_reused():
    session, up, channel, calls = setup()
    entered, finish = asyncio.Event(), asyncio.Event()
    send = up.send

    async def blocked(event):
        if event["type"] == "conversation.item.create":
            entered.set()
            await finish.wait()
        await send(event)

    up.send = blocked
    try:
        await begin(session)
        await done(session)
        await entered.wait()
        await session._barge_in()
        finish.set()
        await tick()
        assert not up.of("conversation.item.create")
        assert session._ended.is_set()
    finally:
        finish.set()
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_completed_but_unheard_speech_truncation_ack_blocks_next_turn():
    session, up, channel, calls = setup()
    try:
        await speaking(session)
        await audio(session)
        await done(session, "speech1", [{"id": "spoken1", "type": "message", "role": "assistant",
                                        "content": [{"type": "audio", "transcript": "Provisional reply"}]}])
        assert len(channel.of("answer")) == 1
        up.ack_truncate = False
        await session._handle_upstream({"type": "input_audio_buffer.speech_started", "item_id": "user2"})
        await session._handle_upstream({"type": "conversation.item.input_audio_transcription.completed",
                                       "item_id": "user2", "transcript": "Next question"})
        await tick()
        assert len(up.of("response.create")) == 2
        truncation = up.of("conversation.item.truncate")[-1]
        assert truncation["audio_end_ms"] == 0
        await session._handle_upstream({**truncation, "type": "conversation.item.truncated"})
        await tick()
        assert "spoken1" in [event["item_id"] for event in up.of("conversation.item.delete")]
        assert len(up.of("response.create")) == 3
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_backend_timeout_closes_without_model_fallback():
    never = asyncio.Event()

    async def answer(text):
        await never.wait()

    session, up, channel, calls = setup(answer=answer, answer_timeout=0.2)
    try:
        await begin(session)
        await done(session)
        await asyncio.sleep(0.25)
        assert session._ended.is_set()
        assert not channel.of("answer") and not channel.audio
        assert len(up.of("response.create")) == 1
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_stale_user_transcription_and_replayed_call_id_cannot_start_backend():
    session, up, channel, calls = setup()
    try:
        await begin(session)
        session._completed_calls.add("call1")
        await done(session)
        assert not calls and session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_wrong_truncate_ack_and_stale_receipt_never_advance_history():
    clock = [0.0]
    session, up, channel, calls = setup(audio_clock=lambda: clock[0])
    try:
        await speaking(session)
        await audio(session)
        metadata = channel.of("audio_chunk")[-1]
        up.ack_truncate = False
        await session._barge_in()
        await tick()
        clock[0] = 1.0
        await session.handle_control({"type": "playback", "item_id": "spoken1",
                                      "playback_id": metadata["playback_id"], "played_samples": 480})
        assert session._playbacks["spoken1"].played == 0
        await session._handle_upstream({"type": "conversation.item.truncated", "item_id": "spoken1",
                                       "content_index": 0, "audio_end_ms": 20})
        assert session._ended.is_set()
    finally:
        await session._shutdown("test", 0)


@pytest.mark.anyio
async def test_idle_interrupt_is_acknowledged_so_client_can_play_the_next_turn():
    session, up, channel, calls = setup()
    try:
        await session.handle_control({"type": "interrupt"})
        assert channel.of("interrupted")
    finally:
        await session._shutdown("test", 0)
