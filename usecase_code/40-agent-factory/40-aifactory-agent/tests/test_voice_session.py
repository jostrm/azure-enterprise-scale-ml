"""Voice session tests: fake Voice Live upstream and fake browser channel. No audio device, Azure or network."""

import asyncio
import base64
import json

import pytest

from aifactory_agent.voice import (
    VoiceAnswerError, VoiceProtocolError, VoiceSession, connection_url, session_update_event,
)
from aifactory_agent.voice_settings import VoiceSettings
from voice_fakes import PCM, FakeChannel, FakeUpstream

ANSWER = {
    "answer": "Open the **Config Wizard** [S1]. Then run `azurefactory status`.\n\n```powershell\nGet-Date\n```",
    "citations": [{"citation_id": "S1", "heading": "Wizard"}], "scope_key": "project001-dev", "audience": "project",
    "correlation_id": "c-1", "tool_activity": [],
}


class Harness:
    def __init__(self, voice=None, answer=None, **timing):
        self.voice = voice or VoiceSettings(greeting=None)
        self.upstream, self.channel = FakeUpstream(), FakeChannel()
        self.questions = []
        self.release = asyncio.Event()
        self.hold = False
        self._answer = answer
        self.session = VoiceSession(self.voice, self.upstream, self.channel, self.answer, session_id="s-1", **timing)
        self.task = None

    async def answer(self, text):
        self.questions.append(text)
        if self.hold:
            await self.release.wait()
        if self._answer is not None:
            return await self._answer(text)
        return dict(ANSWER)

    async def start(self, ready=True):
        self.task = asyncio.create_task(self.session.run())
        if ready:
            self.upstream.push({"type": "session.created", "session": {"id": "sess_1"}})
            await self.until(lambda: self.upstream.of("session.update"))
            self.upstream.push({"type": "session.updated", "session": {}})
            await self.until(lambda: self.channel.of("ready"))
        return self

    async def until(self, predicate, timeout=3.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("condition not reached; client=%s upstream=%s" % (self.channel.json, self.upstream.sent))
            await asyncio.sleep(0.002)

    async def finish(self):
        if self.task and not self.task.done():
            await self.upstream.close()
        return await asyncio.wait_for(self.task, 3)

    def hear(self, text, item="item_1"):
        self.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": item})
        self.upstream.push({"type": "input_audio_buffer.speech_stopped", "item_id": item})
        self.upstream.push({"type": "conversation.item.input_audio_transcription.completed",
                            "item_id": item, "transcript": text})


def run(scenario):
    async def guarded():
        return await asyncio.wait_for(scenario(), 10)
    return asyncio.run(guarded())


def test_session_update_is_built_only_from_server_settings_as_a_speech_shell():
    event = session_update_event(VoiceSettings(
        input_languages=["sv-SE", "en-US"], voice_name="en-US-AvaMultilingualNeural", voice_temperature=0.6,
        turn_detection="azure_semantic_vad_multilingual", silence_duration_ms=700), "s-9")
    session = event["session"]
    assert event["type"] == "session.update"
    assert session["turn_detection"] == {
        "type": "azure_semantic_vad_multilingual", "silence_duration_ms": 700,
        "create_response": False, "interrupt_response": True,
    }
    assert session["voice"] == {"type": "azure-standard", "name": "en-US-AvaMultilingualNeural", "temperature": 0.6}
    assert session["input_audio_transcription"] == {"model": "azure-speech", "language": "sv-SE,en-US"}
    assert session["input_audio_noise_reduction"] == {"type": "azure_deep_noise_suppression"}
    assert session["input_audio_echo_cancellation"] == {"type": "server_echo_cancellation"}
    assert session["input_audio_format"] == session["output_audio_format"] == "pcm16"
    assert session["input_audio_sampling_rate"] == 24000
    assert "tools" not in session and "never generate" in session["instructions"].lower()
    assert session["metadata"] == {"app": "aifactory-agent-voice", "session": "s-9"}


def test_noise_and_echo_processing_can_be_disabled():
    session = session_update_event(VoiceSettings(noise_suppression=False, echo_cancellation=False), "s")["session"]
    assert "input_audio_noise_reduction" not in session and "input_audio_echo_cancellation" not in session
    assert "temperature" not in session["voice"]


def test_connection_url_targets_the_voice_live_realtime_path_without_credentials():
    voice = VoiceSettings(endpoint="https://acct.services.ai.azure.com", api_version="2026-04-10", model="gpt-4.1-nano")
    url = connection_url(voice, "ignored")
    assert url == "wss://acct.services.ai.azure.com/voice-live/realtime?api-version=2026-04-10&model=gpt-4.1-nano"
    derived = connection_url(VoiceSettings(), "AIF2Account001")
    assert derived.startswith("wss://aif2account001.services.ai.azure.com/voice-live/realtime?")
    assert "token" not in url.lower() and "key" not in url.lower()


def test_handshake_configures_the_shell_then_reports_ready_and_listening():
    async def scenario():
        harness = await Harness().start()
        sent = harness.upstream.sent
        assert sent[0]["type"] == "session.update"
        assert sent[0] == session_update_event(harness.voice, "s-1")
        ready = harness.channel.of("ready")[0]
        assert ready["session_id"] == "s-1"
        assert ready["audio"] == {"encoding": "pcm16", "sample_rate": 24000, "channels": 1}
        assert ready["limits"] == {"max_session_seconds": 900, "idle_timeout_seconds": 120}
        assert ready["voice"] == {"name": "en-US-Ava:DragonHDLatestNeural", "languages": ["en-US"]}
        assert harness.channel.states() == ["listening"]
        assert await harness.finish() == "upstream_closed"
    run(scenario)


def test_the_greeting_is_spoken_through_a_pre_generated_message():
    async def scenario():
        harness = await Harness(VoiceSettings(greeting="Factory Agent online.")).start()
        await harness.until(lambda: harness.upstream.of("response.create"))
        assert harness.upstream.of("response.create")[0] == {
            "type": "response.create", "response": {"pre_generated_assistant_message": {
                "type": "message", "role": "assistant", "content": [{"type": "text", "text": "Factory Agent online."}]}}}
        assert {"type": "transcript", "role": "assistant", "text": "Factory Agent online.", "final": True} in harness.channel.json
        await harness.finish()
    run(scenario)


def test_handshake_failure_is_reported_as_a_fatal_voice_error():
    async def scenario():
        harness = Harness(handshake_timeout=0.05)
        reason = await asyncio.wait_for(harness.session.run(), 3)
        assert reason == "handshake_failed"
        error = harness.channel.of("error")[0]
        assert error["code"] == "voice_unavailable" and error["fatal"] is True
        assert harness.upstream.closed
    run(scenario)


def test_client_audio_is_forwarded_as_base64_pcm_and_bad_frames_are_rejected():
    async def scenario():
        harness = await Harness().start()
        await harness.session.handle_audio(PCM)
        assert harness.upstream.of("input_audio_buffer.append") == [
            {"type": "input_audio_buffer.append", "audio": base64.b64encode(PCM).decode()}]
        for bad in (b"", b"\x01", b"\x00" * 16386):
            with pytest.raises(VoiceProtocolError):
                await harness.session.handle_audio(bad)
        assert len(harness.upstream.of("input_audio_buffer.append")) == 1
        await harness.finish()
    run(scenario)


def test_audio_faster_than_the_real_time_budget_is_a_protocol_violation():
    async def scenario():
        now = [0.0]
        harness = Harness(audio_clock=lambda: now[0])
        await harness.start()
        chunk = b"\x00\x00" * 8192
        with pytest.raises(VoiceProtocolError):
            for _ in range(40):
                await harness.session.handle_audio(chunk)
        now[0] += 60
        await harness.session.handle_audio(chunk)
        await harness.finish()
    run(scenario)


def test_a_spoken_question_is_answered_by_the_backend_and_read_back_as_clean_speech():
    async def scenario():
        harness = await Harness().start()
        harness.hear("How do I add a project?")
        await harness.until(lambda: harness.upstream.of("response.create"))
        assert harness.questions == ["How do I add a project?"]
        assert {"type": "transcript", "role": "user", "text": "How do I add a project?", "final": True} in harness.channel.json
        answer = harness.channel.of("answer")[0]
        assert answer["answer"] == ANSWER["answer"] and answer["citations"] == ANSWER["citations"]
        assert answer["correlation_id"] == "c-1" and answer["spoken_truncated"] is False
        spoken = harness.upstream.of("response.create")[0]["response"]["pre_generated_assistant_message"]["content"][0]["text"]
        assert spoken == "Open the Config Wizard. Then run azurefactory status. The code is on screen."
        assert answer["spoken"] == spoken
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_1", "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: harness.channel.audio)
        assert harness.channel.audio == [PCM]
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_1", "status": "completed"}})
        await harness.until(lambda: harness.channel.states()[-1] == "listening" and "speaking" in harness.channel.states())
        assert harness.channel.states() == ["listening", "thinking", "speaking", "listening"]
        await harness.finish()
    run(scenario)


def test_interim_transcripts_are_streamed_to_the_screen_before_the_final_one():
    async def scenario():
        harness = await Harness().start()
        harness.upstream.push({"type": "conversation.item.input_audio_transcription.delta", "item_id": "i", "delta": "How do "})
        harness.upstream.push({"type": "conversation.item.input_audio_transcription.delta", "item_id": "i", "delta": "I start"})
        await harness.until(lambda: len(harness.channel.of("transcript")) == 2)
        assert [m["text"] for m in harness.channel.of("transcript")] == ["How do", "How do I start"]
        assert all(m["final"] is False for m in harness.channel.of("transcript"))
        await harness.finish()
    run(scenario)


def test_barge_in_while_speaking_cancels_speech_and_drops_late_audio():
    async def scenario():
        harness = await Harness().start()
        harness.hear("Question one")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_1", "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: harness.channel.audio)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        assert harness.upstream.of("response.cancel") == [{"type": "response.cancel"}]
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_1", "delta": base64.b64encode(PCM).decode()})
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_1", "status": "cancelled"}})
        await asyncio.sleep(0.05)
        assert harness.channel.states()[-1] == "listening"
        assert harness.channel.audio == [PCM]
        assert not harness.channel.of("error")
        await harness.finish()
    run(scenario)


def test_barge_in_while_thinking_discards_the_pending_answer():
    async def scenario():
        harness = Harness()
        harness.hold = True
        await harness.start()
        harness.hear("Slow question")
        await harness.until(lambda: harness.questions)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        harness.release.set()
        await asyncio.sleep(0.05)
        assert not harness.channel.of("answer") and not harness.upstream.of("response.create")
        assert harness.channel.states()[-1] == "listening"
        await harness.finish()
    run(scenario)


def test_barge_in_cancels_the_pending_answer_so_no_work_keeps_running():
    async def scenario():
        cancelled = []

        async def slow(text):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(text)
                raise

        harness = Harness(answer=slow)
        await harness.start()
        harness.hear("slow question")
        await harness.until(lambda: harness.questions)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: cancelled)
        assert cancelled == ["slow question"]
        await harness.finish()
    run(scenario)


def test_a_stale_answer_is_dropped_even_when_the_answer_path_ignores_cancellation():
    async def scenario():
        gate = asyncio.Event()

        async def stubborn(text):
            try:
                await gate.wait()
            except asyncio.CancelledError:
                pass
            return {**ANSWER, "answer": "A stale answer."}

        harness = Harness(answer=stubborn)
        await harness.start()
        harness.hear("question")
        await harness.until(lambda: harness.questions)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        gate.set()
        await asyncio.sleep(0.05)
        assert not harness.channel.of("answer") and not harness.upstream.of("response.create")
        await harness.finish()
    run(scenario)


def test_late_audio_of_an_earlier_response_never_leaks_into_the_next_one():
    async def scenario():
        first, stale, second = PCM, b"\x02\x00" * 480, b"\x03\x00" * 480
        delta = lambda response, data: {"type": "response.audio.delta", "response_id": response,
                                        "delta": base64.b64encode(data).decode()}
        harness = await Harness().start()
        harness.hear("one", "item_1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 1)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push(delta("resp_1", first))
        await harness.until(lambda: harness.channel.audio)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        harness.hear("two", "item_3")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_2"}})
        harness.upstream.push(delta("resp_1", stale))
        harness.upstream.push(delta("resp_2", second))
        await harness.until(lambda: len(harness.channel.audio) == 2)
        await asyncio.sleep(0.05)
        assert harness.channel.audio == [first, second]
        await harness.finish()
    run(scenario)


def test_a_late_done_of_a_cancelled_response_does_not_silence_the_next_response():
    async def scenario():
        delta = lambda response, data: {"type": "response.audio.delta", "response_id": response,
                                        "delta": base64.b64encode(data).decode()}
        second = b"\x03\x00" * 480
        harness = await Harness().start()
        harness.hear("one", "item_1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 1)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push(delta("resp_1", PCM))
        await harness.until(lambda: harness.channel.audio)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        harness.hear("two", "item_3")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_2"}})
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_1", "status": "cancelled"}})
        harness.upstream.push(delta("resp_2", second))
        await harness.until(lambda: len(harness.channel.audio) == 2)
        assert harness.channel.audio == [PCM, second]
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_2", "status": "completed"}})
        await harness.until(lambda: harness.channel.states()[-1] == "listening")
        await harness.finish()
    run(scenario)


def test_a_rejected_spoken_answer_does_not_stall_the_screen_or_silence_the_next_answer():
    async def scenario():
        harness = await Harness().start()
        harness.hear("one", "item_1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 1)
        await asyncio.sleep(0.02)
        harness.upstream.push({"type": "error", "error": {"type": "invalid_request_error", "code": "invalid_value",
                                                          "message": "internal detail that must not reach the browser"}})
        await harness.until(lambda: harness.channel.of("error") and harness.channel.states()[-1] == "listening")
        assert harness.channel.of("error")[0] == {"type": "error", "code": "voice_error", "fatal": False,
                                                  "message": "The speech service reported a problem. Typing still works."}
        harness.hear("two", "item_2")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        assert harness.upstream.of("response.cancel") == []
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_2"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_2",
                               "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: harness.channel.audio)
        assert harness.channel.audio == [PCM] and harness.channel.states()[-1] == "speaking"
        await harness.finish()
    run(scenario)


def test_a_failed_spoken_answer_without_audio_returns_to_listening():
    async def scenario():
        harness = await Harness().start()
        harness.hear("one", "item_1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 1)
        await asyncio.sleep(0.02)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_1", "status": "failed"}})
        await harness.until(lambda: harness.channel.of("error") and harness.channel.states()[-1] == "listening")
        assert harness.channel.of("error")[0]["code"] == "voice_error" and harness.channel.audio == []
        await harness.finish()
    run(scenario)


def test_the_finish_of_a_cancelled_response_does_not_end_thinking_before_the_newer_answer_is_spoken():
    async def scenario():
        harness = await Harness().start()
        harness.hear("one", "item_1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 1)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_1", "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: harness.channel.audio)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        harness.hear("two", "item_3")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        await asyncio.sleep(0.02)
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_1", "status": "cancelled"}})
        await asyncio.sleep(0.05)
        assert harness.channel.states()[-1] == "thinking"
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_2"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_2", "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: len(harness.channel.audio) == 2)
        assert harness.channel.states()[-1] == "speaking"
        await harness.finish()
    run(scenario)


def test_interrupting_again_before_the_newer_response_exists_still_cancels_it_when_a_third_answer_follows():
    async def scenario():
        harness = await Harness().start()
        harness.hear("one", "item_1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 1)
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_1"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_1", "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: harness.channel.audio)
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_2"})
        await harness.until(lambda: harness.channel.of("interrupted"))
        harness.hear("two", "item_3")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        await asyncio.sleep(0.02)
        harness.upstream.push({"type": "response.done", "response": {"id": "resp_1", "status": "cancelled"}})
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "item_4"})
        await harness.until(lambda: len(harness.upstream.of("response.cancel")) == 2)
        harness.hear("three", "item_5")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 3)
        third = b"\x04\x00" * 480
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_2"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_2", "delta": base64.b64encode(b"\x03\x00" * 480).decode()})
        harness.upstream.push({"type": "response.created", "response": {"id": "resp_3"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "resp_3", "delta": base64.b64encode(third).decode()})
        await harness.until(lambda: len(harness.channel.audio) == 2)
        await asyncio.sleep(0.05)
        assert harness.channel.audio == [PCM, third]
        await harness.finish()
    run(scenario)


def test_a_stall_that_flushes_several_seconds_of_audio_is_absorbed_but_a_flood_is_still_refused():
    async def scenario():
        harness = Harness(audio_clock=lambda: 0.0)
        await harness.start()
        message = b"\x00\x00" * 1440  # the 60 ms message the browser sends
        for _ in range(160):  # 9.6 seconds of audio arriving at once
            await harness.session.handle_audio(message)
        with pytest.raises(VoiceProtocolError):
            for _ in range(20):
                await harness.session.handle_audio(message)
        await harness.finish()
    run(scenario)


def test_a_newer_question_supersedes_an_older_pending_answer():
    async def scenario():
        gates = {}

        async def answer(text):
            await gates.setdefault(text, asyncio.Event()).wait()
            return {**ANSWER, "answer": f"Answer to {text}."}

        harness = Harness(answer=answer)
        await harness.start()
        harness.hear("first", "item_1")
        await harness.until(lambda: "first" in gates)
        harness.upstream.push({"type": "conversation.item.input_audio_transcription.completed",
                               "item_id": "item_2", "transcript": "second"})
        await harness.until(lambda: "second" in gates)
        gates["first"].set()
        gates["second"].set()
        await harness.until(lambda: harness.channel.of("answer"))
        await asyncio.sleep(0.05)
        assert [m["answer"] for m in harness.channel.of("answer")] == ["Answer to second."]
        assert len(harness.upstream.of("response.create")) == 1
        await harness.finish()
    run(scenario)


def test_an_empty_transcript_returns_to_listening_without_asking_the_backend():
    async def scenario():
        harness = await Harness().start()
        harness.hear("   ")
        await harness.until(lambda: harness.channel.states()[-1] == "listening" and "thinking" in harness.channel.states())
        assert harness.questions == [] and not harness.upstream.of("response.create")
        await harness.finish()
    run(scenario)


def test_a_failed_answer_is_reported_safely_and_apologised_for_in_speech():
    async def scenario():
        async def failing(text):
            raise VoiceAnswerError("knowledge_unavailable", "Knowledge is unavailable. Ask an operator to check ingestion.")

        harness = Harness(answer=failing)
        await harness.start()
        harness.hear("Anything")
        await harness.until(lambda: harness.upstream.of("response.create"))
        error = harness.channel.of("error")[0]
        assert error == {"type": "error", "code": "knowledge_unavailable", "fatal": False,
                         "message": "Knowledge is unavailable. Ask an operator to check ingestion."}
        spoken = harness.upstream.of("response.create")[0]["response"]["pre_generated_assistant_message"]["content"][0]["text"]
        assert spoken == "Sorry, I could not complete that. The details are on screen."
        await harness.finish()
    run(scenario)


def test_unexpected_answer_exceptions_never_leak_their_text():
    async def explode(text):
        raise RuntimeError("SECRET-TOKEN-123 internal detail")

    async def scenario():
        harness = Harness(answer=explode)
        await harness.start()
        harness.hear("Anything")
        await harness.until(lambda: harness.channel.of("error"))
        assert harness.channel.of("error")[0]["code"] == "answer_failed"
        assert "SECRET" not in json.dumps(harness.channel.json) + json.dumps(harness.upstream.sent)
        await harness.finish()
    run(scenario)


def test_a_slow_answer_times_out_with_a_clear_code():
    async def scenario():
        harness = Harness(VoiceSettings(greeting=None, answer_timeout_seconds=10), answer_timeout=0.05)
        harness.hold = True
        await harness.start()
        harness.hear("Slow")
        await harness.until(lambda: harness.channel.of("error"))
        assert harness.channel.of("error")[0]["code"] == "answer_timeout"
        await harness.finish()
    run(scenario)


def test_voice_service_errors_are_sanitised_and_benign_ones_ignored():
    async def scenario():
        harness = await Harness().start()
        harness.upstream.push({"type": "error", "error": {"code": "response_cancel_not_active", "message": "nothing to cancel"}})
        harness.upstream.push({"type": "error", "error": {"code": "internal", "message": "SECRET upstream detail"}})
        await harness.until(lambda: harness.channel.of("error"))
        assert harness.channel.of("error") == [{"type": "error", "code": "voice_error", "fatal": False,
                                                "message": "The speech service reported a problem. Typing still works."}]
        await harness.finish()
    run(scenario)


def test_transcription_failures_are_reported_and_listening_resumes():
    async def scenario():
        harness = await Harness().start()
        harness.upstream.push({"type": "input_audio_buffer.speech_stopped", "item_id": "i"})
        harness.upstream.push({"type": "conversation.item.input_audio_transcription.failed", "item_id": "i", "error": {"code": "x"}})
        await harness.until(lambda: harness.channel.of("error"))
        assert harness.channel.of("error")[0]["code"] == "transcription_failed"
        await harness.until(lambda: harness.channel.states()[-1] == "listening")
        await harness.finish()
    run(scenario)


def test_unknown_service_events_are_ignored():
    async def scenario():
        harness = await Harness().start()
        harness.upstream.push({"type": "rate_limits.updated", "rate_limits": []})
        harness.upstream.push({"type": "something.new", "payload": 1})
        harness.upstream.push({"no_type": True})
        await asyncio.sleep(0.05)
        assert not harness.channel.of("error") and harness.channel.states() == ["listening"]
        await harness.finish()
    run(scenario)


def test_manual_interrupt_stops_speech_and_pending_work():
    async def scenario():
        harness = Harness()
        harness.hold = True
        await harness.start()
        harness.hear("Slow")
        await harness.until(lambda: harness.questions)
        await harness.session.handle_control({"type": "interrupt"})
        assert harness.channel.of("interrupted") and harness.channel.states()[-1] == "listening"
        harness.release.set()
        await asyncio.sleep(0.05)
        assert not harness.channel.of("answer")
        await harness.finish()
    run(scenario)


def test_the_client_can_end_the_session_and_unknown_controls_are_rejected():
    async def scenario():
        harness = await Harness().start()
        with pytest.raises(VoiceProtocolError):
            await harness.session.handle_control({"type": "run_tool", "name": "x"})
        with pytest.raises(VoiceProtocolError):
            await harness.session.handle_control({"no": "type"})
        await harness.session.handle_control({"type": "end"})
        assert await asyncio.wait_for(harness.task, 3) == "ended"
        assert harness.upstream.closed and harness.channel.of("closed") == [{"type": "closed", "reason": "ended"}]
    run(scenario)


def test_idle_sessions_close_to_stop_billing():
    async def scenario():
        harness = Harness(idle_timeout=0.1, max_duration=5)
        await harness.start()
        assert await asyncio.wait_for(harness.task, 3) == "idle"
        assert harness.channel.of("closed") == [{"type": "closed", "reason": "idle"}]
    run(scenario)


def test_speech_activity_resets_the_idle_clock_and_the_hard_limit_still_applies():
    async def scenario():
        harness = Harness(idle_timeout=0.2, max_duration=0.5)
        await harness.start()
        for _ in range(4):
            await asyncio.sleep(0.1)
            harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "i"})
        assert await asyncio.wait_for(harness.task, 3) == "timeout"
    run(scenario)


def test_losing_the_voice_service_is_fatal_and_visible():
    async def scenario():
        harness = await Harness().start()
        await harness.upstream.close()
        assert await asyncio.wait_for(harness.task, 3) == "upstream_closed"
        assert harness.channel.of("error")[-1]["code"] == "voice_unavailable"
        assert harness.channel.of("error")[-1]["fatal"] is True
        assert harness.channel.of("closed")[-1]["reason"] == "upstream_closed"
    run(scenario)
