"""Native Voice Live streaming: offline protocol and governed turn tests."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from aifactory_agent.voice import VoiceAnswerError
from aifactory_agent.voice_realtime import RealtimeVoiceSession
from aifactory_agent.voice_settings import VoiceSettings
from test_voice_session import Harness, run
from voice_fakes import PCM


class NativeHarness(Harness):
    def __init__(self, **kwargs):
        super().__init__(VoiceSettings(mode="realtime", model="gpt-realtime-mini", greeting=None,
                                       voice_type="openai", voice_name="coral"))
        self.prepared, self.executions = [], []
        self.hold_tool = asyncio.Event()
        self.context = SimpleNamespace(
            messages=[{"role": "developer", "content": [{"text": "scope"}]},
                      {"role": "user", "content": [{"text": "untrusted evidence [S1]"}]}],
            tools=[{"type": "function", "name": "knowledge_search", "description": "Search",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                                   "required": ["query"], "additionalProperties": False}}],
            finish=self.finish_answer,
        )
        self.session = RealtimeVoiceSession(self.voice, self.upstream, self.channel, self.prepare,
                                            self.execute, max_tool_rounds=2, session_id="s-1", **kwargs)

    async def prepare(self, text):
        self.prepared.append(text)
        return self.context

    async def execute(self, context, name, identifier, arguments):
        self.executions.append((name, identifier, arguments))
        if name == "hold":
            await self.hold_tool.wait()
        if name == "forbidden":
            raise VoiceAnswerError("forbidden", "Tool denied.")
        return {"evidence": [{"citation_id": "S2"}]}

    def finish_answer(self, text, response_id, tokens):
        if "[S1]" not in text:
            raise RuntimeError("omitted available source citations")
        return {"answer": text, "citations": [{"citation_id": "S1"}], "response_id": response_id}

    def response(self, identifier="r1", text="Grounded [S1].", **extra):
        self.upstream.push({"type": "response.done", "response": {
            "id": identifier, "status": "completed", "output": [
                {"type": "message", "role": "assistant", "content": [{"type": "audio", "transcript": text}]}
            ], **extra}})


def test_native_stream_starts_without_external_answer_or_pre_generated_tts():
    async def scenario():
        harness = await NativeHarness().start()
        session = harness.upstream.of("session.update")[0]["session"]
        assert "never generate" not in session["instructions"].lower()
        assert session["voice"] == "coral"
        assert session["input_audio_transcription"] == {"model": "gpt-4o-mini-transcribe", "language": "en"}
        harness.hear("Explain setup")
        await harness.until(lambda: harness.upstream.of("response.create"))
        assert harness.prepared == ["Explain setup"] and not harness.questions
        assert all("pre_generated_assistant_message" not in event.get("response", {})
                   for event in harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "r1",
                               "delta": base64.b64encode(PCM).decode()})
        await harness.until(lambda: harness.channel.audio)
        assert not harness.channel.of("answer")
        harness.upstream.push({"type": "response.audio_transcript.delta", "response_id": "r1",
                               "delta": "Grounded [S1]."})
        harness.response()
        await harness.until(lambda: harness.channel.of("answer"))
        assert harness.channel.of("answer")[0]["citation_validation"] == "passed"
        assert harness.channel.of("transcript")[-1]["provisional"] is True
        await harness.finish()
    run(scenario)


def test_native_tool_output_and_continuation_are_bounded_and_cancel_safe():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("Explain setup")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        harness.response(output=[{"type": "function_call", "name": "hold", "call_id": "c1", "arguments": "{}"}])
        await harness.until(lambda: harness.executions)
        await harness.session.handle_control({"type": "interrupt"})
        harness.hold_tool.set()
        await asyncio.sleep(0.03)
        assert not harness.upstream.of("conversation.item.create")[-1].get("item", {}).get("type") == "function_call_output"
        assert len(harness.upstream.of("response.create")) == 1
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("failure", ["citations", "tools"])
def test_native_invalid_citations_or_denied_tools_never_publish_authoritative_answer(failure):
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("Explain setup")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        if failure == "citations":
            harness.response(text="Uncited.")
        else:
            harness.response(output=[{"type": "function_call", "name": "forbidden",
                                      "call_id": "c1", "arguments": "{}"}])
        await harness.until(lambda: harness.channel.of("error"))
        assert not harness.channel.of("answer")
        assert harness.channel.of("error")[-1]["fatal"] is False
        assert "Typing" in harness.channel.of("error")[-1]["message"]
        assert len(harness.upstream.of("response.create")) == 1
        await harness.finish()
    run(scenario)


def test_native_barge_in_suppresses_old_response_audio_and_completion_after_new_turn():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        await harness.until(lambda: harness.session._current_response == "r1")
        harness.hear("Second", item="item2")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        harness.upstream.push({"type": "response.created", "response": {"id": "r2"}})
        harness.upstream.push({"type": "response.audio.delta", "response_id": "r1",
                               "delta": base64.b64encode(PCM).decode()})
        harness.response(identifier="r1")
        harness.upstream.push({"type": "response.audio.delta", "response_id": "r1",
                               "delta": base64.b64encode(PCM).decode()})
        await asyncio.sleep(0.02)
        assert not harness.channel.audio and not harness.channel.of("answer")
        harness.response(identifier="r2")
        await harness.until(lambda: harness.channel.of("answer"))
        assert harness.channel.of("answer")[0]["response_id"] == "r2"
        await harness.finish()
    run(scenario)


def test_native_tool_success_continues_and_round_limit_stops_further_calls():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        harness.response(output=[{"type": "function_call", "name": "knowledge_search",
                                  "call_id": "c1", "arguments": '{"query":"more"}'}])
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        output = harness.upstream.of("conversation.item.create")[-1]["item"]
        assert output["type"] == "function_call_output" and output["call_id"] == "c1"
        assert "S2" in output["output"]
        harness.upstream.push({"type": "response.created", "response": {"id": "r2"}})
        harness.response(identifier="r2", output=[{"type": "function_call", "name": "knowledge_search",
                                                  "call_id": "c2", "arguments": '{"query":"more"}'}])
        await harness.until(lambda: harness.channel.of("error"))
        assert harness.channel.of("error")[-1]["code"] == "tool_limit"
        assert len(harness.executions) == 1 and len(harness.upstream.of("response.create")) == 2
        await harness.finish()
    run(scenario)


def test_native_discards_late_input_transcription_from_interrupted_utterance():
    async def scenario():
        harness = await NativeHarness().start()
        harness.upstream.push({"type": "input_audio_buffer.speech_started", "item_id": "old"})
        harness.hear("Newest", item="new")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "conversation.item.input_audio_transcription.completed",
                               "item_id": "old", "transcript": "Old question"})
        await asyncio.sleep(0.02)
        assert harness.prepared == ["Newest"]
        await harness.finish()
    run(scenario)


def test_explicit_interrupt_does_not_resurrect_late_transcription():
    async def scenario():
        harness = await NativeHarness().start()
        await harness.session._handle_upstream({"type": "input_audio_buffer.speech_started", "item_id": "old"})
        await harness.session._handle_upstream({"type": "input_audio_buffer.speech_stopped", "item_id": "old"})
        await harness.session.handle_control({"type": "interrupt"})
        await harness.session._handle_upstream({
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "old", "transcript": "Cancelled question"})
        await asyncio.sleep(0.02)
        assert not harness.prepared and not harness.upstream.of("response.create")
        harness.hear("New question", item="new")
        await harness.until(lambda: harness.prepared)
        assert harness.prepared == ["New question"]
        await harness.finish()
    run(scenario)


def test_interrupt_during_awaited_speech_start_cleanup_cannot_register_cancelled_input():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        entered, release = asyncio.Event(), asyncio.Event()
        send = harness.upstream.send

        async def blocked(event):
            if event["type"] == "response.cancel":
                entered.set()
                await release.wait()
            await send(event)

        harness.upstream.send = blocked
        starting = asyncio.create_task(harness.session._handle_upstream(
            {"type": "input_audio_buffer.speech_started", "item_id": "cancelled"}))
        await entered.wait()
        await harness.session.handle_control({"type": "interrupt"})
        release.set()
        await starting
        await harness.session._handle_upstream({
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "cancelled", "transcript": "Cancelled second"})
        await asyncio.sleep(0.02)
        assert harness.prepared == ["First"]
        assert len(harness.upstream.of("response.create")) == 1
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("blocked_kind", ["session.update", "conversation.item.create"])
def test_cancelled_context_send_does_not_delete_an_item_never_created(blocked_kind):
    async def scenario():
        harness = await NativeHarness(handshake_timeout=0.05).start()
        entered, release = asyncio.Event(), asyncio.Event()
        send = harness.upstream.send

        async def blocked(event):
            if event["type"] == blocked_kind:
                entered.set()
                await release.wait()
            await send(event)

        harness.upstream.send = blocked
        harness.hear("First", item="first")
        await entered.wait()
        await harness.session.handle_control({"type": "interrupt"})
        harness.upstream.send = send
        harness.hear("Current", item="current")
        if blocked_kind == "conversation.item.create":
            await harness.until(lambda: harness.task.done())
            assert not harness.upstream.of("response.create")
            assert harness.channel.of("error")[-1]["fatal"] is True
        else:
            await harness.until(lambda: harness.upstream.of("response.create"))
        created = {event["item"]["id"] for event in harness.upstream.of("conversation.item.create")}
        deleted_context = {event["item_id"] for event in harness.upstream.of("conversation.item.delete")
                           if event["item_id"].startswith("ctx_")}
        assert deleted_context <= created
        assert harness.prepared == ["First", "Current"]
        await harness.finish()
    run(scenario)


def test_next_response_waits_for_uncertain_old_creation_ack_and_deletion():
    async def scenario():
        harness = await NativeHarness().start()
        entered, release = asyncio.Event(), asyncio.Event()
        send = harness.upstream.send

        async def transmitted_then_blocked(event):
            await send(event)
            if event["type"] == "conversation.item.create":
                entered.set()
                await release.wait()

        harness.upstream.send = transmitted_then_blocked
        harness.hear("First", item="first")
        await entered.wait()
        old_item = harness.upstream.of("conversation.item.create")[-1]["item"]
        await harness.session.handle_control({"type": "interrupt"})
        harness.upstream.send = send
        harness.hear("Current", item="current")
        await harness.until(lambda: len(harness.prepared) == 2)
        await asyncio.sleep(0.02)
        assert not harness.upstream.of("response.create")
        harness.upstream.push({"type": "conversation.item.created", "item": old_item})
        await harness.until(lambda: harness.upstream.of("response.create"))
        deleted = harness.upstream.of("conversation.item.delete")
        assert any(event["item_id"] == old_item["id"] for event in deleted)
        delete_index = next(index for index, event in enumerate(harness.upstream.sent)
                            if event["type"] == "conversation.item.delete" and event["item_id"] == old_item["id"])
        response_index = next(index for index, event in enumerate(harness.upstream.sent)
                              if event["type"] == "response.create")
        assert delete_index < response_index
        await harness.finish()
    run(scenario)


def test_new_grounded_turn_removes_all_old_cited_history_and_preserves_current_audio():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="old-user")
        await harness.until(lambda: harness.upstream.of("response.create"))
        context_id = harness.upstream.of("conversation.item.create")[0]["item"]["id"]
        harness.upstream.push({"type": "conversation.item.created", "item": {"id": "old-user", "type": "message"}})
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        harness.upstream.push({"type": "response.output_item.added", "response_id": "r1",
                              "item": {"id": "old-assistant", "type": "message", "role": "assistant"}})
        harness.upstream.push({"type": "conversation.item.created",
                              "item": {"id": "old-tool-call", "type": "function_call"}})
        harness.upstream.push({"type": "conversation.item.created",
                              "item": {"id": "old-tool-result", "type": "function_call_output"}})
        harness.response()
        await harness.until(lambda: harness.channel.of("answer"))
        harness.hear("Second", item="current-user")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        deleted = {event["item_id"] for event in harness.upstream.of("conversation.item.delete")}
        assert {context_id, "old-user", "old-assistant", "old-tool-call", "old-tool-result"} <= deleted
        assert "current-user" not in deleted
        assert harness.prepared == ["First", "Second"]
        await harness.finish()
    run(scenario)


def test_native_turn_deadline_reports_failure_without_poisoning_session():
    async def scenario():
        harness = await NativeHarness(answer_timeout=0.05).start()
        harness.hear("First")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.until(lambda: harness.channel.of("error"))
        assert harness.channel.of("error")[-1]["code"] == "answer_timeout"
        assert harness.channel.states()[-1] == "listening"
        harness.hear("Retry", item="retry")
        await harness.until(lambda: len(harness.prepared) == 2)
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("code", ["model_not_supported", "invalid_value", "authentication_error"])
@pytest.mark.parametrize("event", ["error", "response_failed"])
def test_native_service_rejection_ends_only_voice_without_alternate_generation_or_auth_prompts(code, event):
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First")
        await harness.until(lambda: harness.upstream.of("response.create"))
        if event == "error":
            harness.upstream.push({"type": "error", "error": {"code": code, "message": "SECRET internal detail"}})
        else:
            harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
            harness.response(status="failed", status_details={"error": {"code": code, "message": "SECRET internal detail"}})
        await harness.until(lambda: harness.task.done())
        errors = harness.channel.of("error")
        assert errors[-1]["fatal"] is True and "Typing still works" in errors[-1]["message"]
        assert "SECRET" not in str(errors) and "Sign in" not in str(errors)
        assert not harness.questions and not harness.channel.of("answer")
        assert len(harness.upstream.of("response.create")) == 1
        assert harness.upstream.closed
        assert await harness.finish() == "voice_unavailable"
    run(scenario)
