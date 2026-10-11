"""Native Voice Live streaming: offline protocol and governed turn tests."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketState

from aifactory_agent.voice import VoiceAnswerError
from aifactory_agent.voice_realtime import RealtimeVoiceSession
from aifactory_agent.voice_routes import StarletteChannel
from aifactory_agent.voice_settings import VoiceSettings
from test_voice_session import Harness, run
from voice_fakes import PCM, FakeUpstream


class NativeUpstream(FakeUpstream):
    def __init__(self, *, ack_creations=True, ack_deletions=True):
        super().__init__()
        self.ack_creations, self.ack_deletions = ack_creations, ack_deletions

    async def send(self, event):
        await super().send(event)
        if event["type"] == "conversation.item.create" and self.ack_creations:
            self.push({"type": "conversation.item.created", "item": event["item"]})
        elif event["type"] == "conversation.item.delete" and self.ack_deletions:
            self.push({"type": "conversation.item.deleted", "item_id": event["item_id"]})


class BlockedNativeSocket:
    application_state = WebSocketState.CONNECTED

    def __init__(self, harness):
        self.harness = harness
        self.kind = None
        self.entered, self.release, self.cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.sender = None
        self.delivered_after_failure = []

    async def _block(self):
        self.sender = asyncio.current_task()
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def send_text(self, text):
        message = json.loads(text)
        assistant = message["type"] == "transcript" and message.get("role") == "assistant"
        if ((self.kind == "transcript" and assistant)
                or (self.kind == "fatal" and message["type"] == "error" and message.get("fatal"))):
            await self._block()
        if assistant:
            self.delivered_after_failure.append(
                not self.harness.session._live_turn(self.harness.session._turn))
        await self.harness.channel.send_json(message)

    async def send_bytes(self, data):
        if self.kind == "audio":
            await self._block()
        self.delivered_after_failure.append(
            not self.harness.session._live_turn(self.harness.session._turn))
        await self.harness.channel.send_audio(data)


class NativeHarness(Harness):
    def __init__(self, *, ack_creations=True, ack_deletions=True, **kwargs):
        super().__init__(VoiceSettings(mode="realtime", model="gpt-realtime-mini", greeting=None,
                                       voice_type="openai", voice_name="coral"))
        self.upstream = NativeUpstream(ack_creations=ack_creations, ack_deletions=ack_deletions)
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
        response = {
            "id": identifier, "status": "completed", "output": [
                {"type": "message", "role": "assistant", "content": [{"type": "audio", "transcript": text}]}
            ], **extra}
        for index, item in enumerate(response["output"]):
            item.setdefault("id", f"{identifier}-output-{index}")
        self.upstream.push({"type": "response.done", "response": response})


@pytest.mark.parametrize("kind", ["audio", "transcript"])
def test_failed_turn_cancels_pending_output_through_production_channel(kind):
    async def scenario():
        harness = NativeHarness(answer_timeout=0.12, handshake_timeout=1)
        socket = BlockedNativeSocket(harness)
        harness.session.channel = StarletteChannel(socket)
        await harness.start()
        try:
            harness.hear("First", item="first")
            await harness.until(lambda: harness.upstream.of("response.create"))
            harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
            socket.kind = kind
            harness.upstream.push({
                "type": "response.audio.delta" if kind == "audio" else "response.text.delta",
                "response_id": "r1",
                "delta": base64.b64encode(PCM).decode() if kind == "audio" else "Expired [S1]",
            })
            await socket.entered.wait()
            await harness.until(lambda: harness.session._failed_turn == harness.session._turn)
            socket.release.set()
            await harness.until(lambda: harness.channel.of("error"))
            assert not any(socket.delivered_after_failure)
            assert socket.cancelled.is_set()
            assert not harness.channel.audio and not harness.channel.of("answer")
            assert not [entry for entry in harness.channel.of("transcript") if entry["role"] == "assistant"]
            assert harness.channel.of("error")[-1]["code"] == "answer_timeout"
        finally:
            socket.release.set()
            await harness.finish()
    run(scenario)


def test_history_shutdown_survives_interrupted_fatal_notification_through_production_channel():
    async def scenario():
        harness = NativeHarness(handshake_timeout=0.1, ack_deletions=False)
        socket = BlockedNativeSocket(harness)
        harness.session.channel = StarletteChannel(socket)
        await harness.start()
        try:
            harness.hear("First", item="first")
            await harness.until(lambda: harness.upstream.of("response.create"))
            harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
            harness.response()
            await harness.until(lambda: harness.channel.of("answer"))
            socket.kind = "fatal"
            harness.hear("Second", item="second")
            await socket.entered.wait()
            sender = socket.sender
            assert sender is harness.session._answer_task
            await harness.session.handle_control({"type": "interrupt"})
            await asyncio.gather(sender, return_exceptions=True)
            await harness.session._abort_history()
            assert harness.session._ended.is_set()
            await harness.until(lambda: harness.task.done())
            assert harness.upstream.closed
            assert await harness.finish() == "voice_unavailable"
        finally:
            socket.release.set()
            await harness.finish()
    run(scenario)


@pytest.mark.parametrize("created_order", ["before_output", "after_output", "after_done", "after_delete"])
@pytest.mark.parametrize("output_event", ["response.output_item.added", "response.output_item.done"])
@pytest.mark.parametrize("status", ["cancelled", "incomplete"])
def test_cancelled_response_late_history_cannot_cross_the_new_turn_purge(created_order, output_event, status):
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        barrier_entered, update_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        resolve, send = harness.session._resolve_prior_creations, harness.upstream.send

        async def resolve_history(turn):
            barrier_entered.set()
            return await resolve(turn)

        async def block_new_policy(event):
            if event["type"] == "session.update":
                update_entered.set()
                await release.wait()
            await send(event)

        harness.session._resolve_prior_creations = resolve_history
        harness.upstream.send = block_new_policy
        harness.hear("Second", item="second")
        await barrier_entered.wait()
        old_item = {"id": "late-old", "type": "message", "role": "assistant",
                    "content": [{"type": "text", "text": "First evidence [S1]"}]}
        created_event = {"type": "conversation.item.created", "item": old_item}
        if created_order == "before_output":
            await harness.session._handle_upstream(created_event)
        await harness.session._handle_upstream(
            {"type": output_event, "response_id": "r1", "item": old_item})
        if created_order == "after_output":
            await harness.session._handle_upstream(created_event)
        await harness.session._handle_upstream(
            {"type": "response.done", "response": {"id": "r1", "status": status, "output": [old_item]}})
        if created_order == "after_done":
            await harness.session._handle_upstream(created_event)
        await update_entered.wait()
        if created_order == "after_delete":
            await harness.session._handle_upstream(created_event)
        release.set()
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        assert "late-old" not in harness.session._conversation_items
        sent = harness.upstream.sent
        deleted = next(i for i, event in enumerate(sent)
                       if event["type"] == "conversation.item.delete" and event["item_id"] == "late-old")
        created = max(i for i, event in enumerate(sent) if event["type"] == "response.create")
        assert deleted < created
        assert not harness.channel.of("answer") and not harness.executions
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r2"}})
        await harness.session._handle_upstream(created_event)
        await harness.session._handle_upstream(
            {"type": "response.output_item.done", "response_id": "r1", "item": old_item})
        assert "late-old" not in harness.session._conversation_items
        harness.response(identifier="r2")
        await harness.until(lambda: harness.channel.of("answer"))
        assert [answer["response_id"] for answer in harness.channel.of("answer")] == ["r2"]
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("item", [
    {"id": "unowned-input", "type": "message", "role": "user",
     "content": [{"type": "input_audio", "transcript": "Another utterance"}]},
    {"id": "unowned-tool", "type": "function_call_output", "call_id": "unknown", "output": "Old [S1]"},
])
def test_conversation_item_arrival_during_pinned_response_does_not_establish_ownership(item):
    async def scenario():
        harness = await NativeHarness(handshake_timeout=0.03).start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        await harness.session._handle_upstream({"type": "conversation.item.created", "item": item})
        record = harness.session._items[item["id"]]
        assert record.turn is None and record.response_id is None
        await harness.session._handle_upstream({"type": "response.audio.delta", "response_id": "r1",
                                              "delta": base64.b64encode(PCM).decode()})
        await harness.session._handle_upstream({"type": "response.text.delta", "response_id": "r1",
                                              "delta": "Possibly rebound [S1]"})
        await harness.until(lambda: harness.task.done())
        assert not harness.channel.audio and not harness.channel.of("answer") and not harness.executions
        assert not [entry for entry in harness.channel.of("transcript") if entry["role"] == "assistant"]
        assert len(harness.upstream.of("response.create")) == 1
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


def test_unowned_item_during_response_send_cannot_leak_provisional_or_final_output():
    async def scenario():
        harness = await NativeHarness().start()
        entered, release = asyncio.Event(), asyncio.Event()
        send = harness.upstream.send

        async def block_response(event):
            if event["type"] == "response.create":
                entered.set()
                await release.wait()
            await send(event)

        harness.upstream.send = block_response
        harness.hear("Current", item="current")
        await entered.wait()
        await harness.session._handle_upstream({"type": "conversation.item.created", "item": {
            "id": "unattributed", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "Old [S1]"}]}})
        release.set()
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        await harness.session._handle_upstream({"type": "response.output_item.added", "response_id": "r1",
                                              "item": {"id": "r1-output-0", "type": "message", "role": "assistant"}})
        await harness.session._handle_upstream({"type": "response.audio.delta", "response_id": "r1",
                                              "delta": base64.b64encode(PCM).decode()})
        await harness.session._handle_upstream({"type": "response.text.delta", "response_id": "r1",
                                              "delta": "Possibly rebound [S1]"})
        harness.response()
        await harness.until(lambda: harness.task.done())
        assert not harness.channel.audio
        assert not [entry for entry in harness.channel.of("transcript") if entry["role"] == "assistant"]
        assert not harness.channel.of("answer") and not harness.executions
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


@pytest.mark.parametrize("delivery", ["before_cancel", "after_cancel"])
def test_interrupted_history_delete_keeps_its_ack_barrier(delivery):
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        harness.response()
        await harness.until(lambda: harness.channel.of("answer"))
        entered, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        send = harness.upstream.send
        blocked_item = []

        async def block_first_delete(event):
            if event["type"] == "conversation.item.delete" and not blocked_item:
                blocked_item.append(event["item_id"])
                if delivery == "before_cancel":
                    await FakeUpstream.send(harness.upstream, event)
                    delivered.set()
                entered.set()
                await release.wait()
                if delivery == "after_cancel":
                    await FakeUpstream.send(harness.upstream, event)
                    delivered.set()
                return
            await send(event)

        harness.upstream.send = block_first_delete
        harness.hear("Second", item="second")
        await entered.wait()
        await harness.session.handle_control({"type": "interrupt"})
        release.set()
        await delivered.wait()
        harness.hear("Third", item="third")
        await harness.until(lambda: len(harness.prepared) == 3)
        assert len(harness.upstream.of("response.create")) == 1
        assert not harness.session._items[blocked_item[0]].deleted.is_set()
        await harness.session._handle_upstream({"type": "conversation.item.deleted", "item_id": blocked_item[0]})
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        assert sum(event["item_id"] == blocked_item[0]
                   for event in harness.upstream.of("conversation.item.delete")) == 1
        assert harness.session._conversation_items == {
            "third", harness.upstream.of("conversation.item.create")[-1]["item"]["id"]}
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("kind", ["audio", "transcript", "answer"])
def test_interrupt_cancels_inflight_native_publication_without_killing_event_pump(kind):
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        entered, release = asyncio.Event(), asyncio.Event()
        send_audio, send_json = harness.channel.send_audio, harness.channel.send_json

        async def blocked_audio(data):
            entered.set()
            await release.wait()
            await send_audio(data)

        async def blocked_json(message):
            if message["type"] == kind and (kind != "transcript" or message["role"] == "assistant"):
                entered.set()
                await release.wait()
            await send_json(message)

        if kind == "audio":
            harness.channel.send_audio = blocked_audio
            event = {"type": "response.audio.delta", "response_id": "r1",
                     "delta": base64.b64encode(PCM).decode()}
        elif kind == "transcript":
            harness.channel.send_json = blocked_json
            event = {"type": "response.text.delta", "response_id": "r1", "delta": "Old [S1]"}
        else:
            harness.channel.send_json = blocked_json
            event = {"type": "response.done", "response": {"id": "r1", "status": "completed", "output": [
                {"id": "r1-output-0", "type": "message", "role": "assistant",
                 "content": [{"type": "text", "text": "Old [S1]"}]}]}}
        event_task = asyncio.create_task(harness.session._handle_upstream(event))
        await entered.wait()
        await harness.session.handle_control({"type": "interrupt"})
        release.set()
        await event_task
        assert not harness.task.done()
        assert not harness.channel.audio and not harness.channel.of("answer")
        assert not [entry for entry in harness.channel.of("transcript") if entry["role"] == "assistant"]
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("delivery", ["before_cancel", "after_cancel"])
def test_cancelled_response_create_must_be_identified_and_completed_before_retry(delivery):
    async def scenario():
        harness = await NativeHarness().start()
        sent_create, release = asyncio.Event(), asyncio.Event()
        send = harness.upstream.send

        async def delivered_but_waiting(event):
            if event["type"] == "response.create":
                if delivery == "before_cancel":
                    await send(event)
                sent_create.set()
                await release.wait()
                if delivery == "after_cancel":
                    await send(event)
                return
            await send(event)

        harness.upstream.send = delivered_but_waiting
        harness.hear("First", item="first")
        await sent_create.wait()
        interrupted = asyncio.create_task(harness.session.handle_control({"type": "interrupt"}))
        await harness.until(lambda: not harness.session._response_active)
        release.set()
        await interrupted
        harness.upstream.send = send
        harness.hear("Second", item="second")
        await harness.until(lambda: len(harness.prepared) == 2)
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "old"}})
        await harness.session._handle_upstream({"type": "response.audio.delta", "response_id": "old",
                                              "delta": base64.b64encode(PCM).decode()})
        await harness.session._handle_upstream({"type": "response.text.delta", "response_id": "old",
                                              "delta": "Old [S1]"})
        assert len(harness.upstream.of("response.create")) == 1
        harness.response(identifier="old", output=[{"id": "old-call", "type": "function_call",
                         "name": "knowledge_search", "call_id": "old-call", "arguments": "{}"}])
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "current"}})
        harness.response(identifier="current")
        await harness.until(lambda: harness.channel.of("answer"))
        assert not harness.channel.audio and not harness.executions
        assert [answer["response_id"] for answer in harness.channel.of("answer")] == ["current"]
        assert not [entry for entry in harness.channel.of("transcript")
                    if entry["role"] == "assistant" and entry["text"] == "Old [S1]"]
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("missing", ["created", "done", "deleted"])
def test_unresolved_native_history_ack_ends_only_voice(missing):
    async def scenario():
        harness = await NativeHarness(handshake_timeout=0.03, ack_deletions=missing != "deleted").start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        if missing != "created":
            await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        if missing == "deleted":
            harness.response()
            await harness.until(lambda: harness.channel.of("answer"))
        harness.hear("Second", item="second")
        await harness.until(lambda: harness.task.done())
        assert len(harness.upstream.of("response.create")) == 1
        assert harness.channel.of("error")[-1]["fatal"] is True
        assert "Typing still works" in harness.channel.of("error")[-1]["message"]
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


@pytest.mark.parametrize("delivery", ["before_cancel", "after_cancel"])
def test_interrupted_tool_output_send_cannot_resume_an_old_turn(delivery):
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        entered, release = asyncio.Event(), asyncio.Event()
        send = harness.upstream.send

        async def blocked_output(event):
            if event["type"] == "conversation.item.create" and event["item"]["type"] == "function_call_output":
                if delivery == "before_cancel":
                    await send(event)
                entered.set()
                await release.wait()
                if delivery == "after_cancel":
                    await send(event)
                return
            await send(event)

        harness.upstream.send = blocked_output
        harness.response(output=[{"id": "call-item", "type": "function_call", "name": "knowledge_search",
                                  "call_id": "c1", "arguments": "{}"}])
        await entered.wait()
        tool_task = harness.session._answer_task
        await harness.session.handle_control({"type": "interrupt"})
        release.set()
        await asyncio.gather(tool_task, return_exceptions=True)
        harness.hear("Second", item="second")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        result_id = next(event["item"]["id"] for event in harness.upstream.of("conversation.item.create")
                         if event["item"]["type"] == "function_call_output")
        assert harness.session._items[result_id].deleted.is_set()
        assert harness.session._request.turn == harness.session._turn
        assert harness.prepared == ["First", "Second"] and len(harness.executions) == 1
        await harness.finish()
    run(scenario)


def test_delayed_duplicate_created_cannot_steal_a_new_response_request():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "old"}})
        harness.response(identifier="old")
        await harness.until(lambda: harness.channel.of("answer"))
        old_turn = harness.session._responses["old"].turn
        harness.hear("Second", item="second")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "old"}})
        assert harness.session._current_response is None
        assert harness.session._responses["old"].turn == old_turn
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "current"}})
        harness.response(identifier="current")
        await harness.until(lambda: len(harness.channel.of("answer")) == 2)
        assert harness.channel.of("answer")[-1]["response_id"] == "current"
        await harness.finish()
    run(scenario)


@pytest.mark.parametrize("ambiguity", ["created", "unknown_output", "unknown_done", "omitted_output",
                                     "new_output_after_done", "new_output_item_done", "duplicate_output",
                                     "nonterminal_done", "reused_item", "unowned_item"])
def test_ambiguous_response_history_is_fatal_not_an_answer_or_tool(ambiguity):
    async def scenario():
        harness = await NativeHarness(handshake_timeout=0.03).start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        if ambiguity == "created":
            event = {"type": "response.created", "response": {"id": "unsolicited"}}
        elif ambiguity == "unknown_output":
            event = {"type": "response.output_item.added", "response_id": "unknown", "item": {"id": "out"}}
        elif ambiguity == "unknown_done":
            event = {"type": "response.done", "response": {"id": "unknown", "status": "completed", "output": []}}
        elif ambiguity == "nonterminal_done":
            event = {"type": "response.done", "response": {"id": "r1", "status": "in_progress", "output": []}}
        elif ambiguity == "omitted_output":
            await harness.session._handle_upstream({"type": "response.output_item.added", "response_id": "r1",
                                                  "item": {"id": "omitted"}})
            event = {"type": "response.done", "response": {"id": "r1", "status": "completed", "output": []}}
        elif ambiguity in {"new_output_after_done", "new_output_item_done"}:
            await harness.session.handle_control({"type": "interrupt"})
            await harness.session._handle_upstream({"type": "response.done", "response": {
                "id": "r1", "status": "cancelled", "output": []}})
            event = {"type": "response.output_item.done" if ambiguity == "new_output_item_done"
                     else "response.output_item.added", "response_id": "r1", "item": {"id": "not-in-done"}}
        elif ambiguity == "duplicate_output":
            event = {"type": "response.done", "response": {"id": "r1", "status": "completed", "output": [
                {"id": "duplicate", "type": "function_call", "name": "knowledge_search", "call_id": "c1",
                 "arguments": "{}"}, {"id": "duplicate", "type": "function_call",
                                     "name": "knowledge_search", "call_id": "c2", "arguments": "{}"}]}}
        elif ambiguity == "reused_item":
            event = {"type": "response.output_item.added", "response_id": "r1",
                     "item": {"id": harness.upstream.of("conversation.item.create")[0]["item"]["id"]}}
        else:
            await harness.session.handle_control({"type": "interrupt"})
            await harness.session._handle_upstream({"type": "response.done", "response": {
                "id": "r1", "status": "cancelled", "output": []}})
            event = {"type": "conversation.item.created", "item": {"id": "unowned"}}
        await harness.session._handle_upstream(event)
        if ambiguity == "unowned_item":
            harness.hear("Retry", item="retry")
        await harness.until(lambda: harness.task.done())
        assert not harness.channel.of("answer") and not harness.executions
        assert len(harness.upstream.of("response.create")) == 1
        assert harness.channel.of("error")[-1]["fatal"] is True
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


def test_streamed_text_is_not_a_substitute_for_complete_final_response_content():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        await harness.session._handle_upstream({"type": "response.text.delta", "response_id": "r1",
                                              "delta": "Provisional [S1]"})
        harness.response(output=[])
        await harness.until(lambda: harness.channel.of("error"))
        assert not harness.channel.of("answer")
        assert harness.channel.of("error")[-1]["code"] == "citation_validation_failed"
        await harness.finish()
    run(scenario)


def test_native_history_tombstones_are_bounded_and_never_evicted_for_id_reuse(monkeypatch):
    async def scenario():
        harness = await NativeHarness().start()
        monkeypatch.setattr("aifactory_agent.voice_realtime.MAX_HISTORY_RECORDS", 3)
        for number in range(5):
            await harness.session._handle_upstream(
                {"type": "conversation.item.created", "item": {"id": f"unknown-{number}"}})
        await harness.until(lambda: harness.task.done())
        assert len(harness.session._items) == 3
        assert harness.channel.of("error")[-1]["fatal"] is True
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


@pytest.mark.parametrize("missing", ["response_created", "response_done", "item_created"])
def test_cancelled_protocol_ack_has_a_deadline_even_without_another_utterance(missing):
    async def scenario():
        harness = await NativeHarness(handshake_timeout=0.03, ack_creations=missing != "item_created").start()
        harness.hear("First", item="first")
        expected = "conversation.item.create" if missing == "item_created" else "response.create"
        await harness.until(lambda: harness.upstream.of(expected))
        if missing == "response_done":
            await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        await harness.session.handle_control({"type": "interrupt"})
        await harness.session._handle_upstream({"type": "error", "error": {"code": "response_cancel_not_active"}})
        await harness.until(lambda: harness.task.done())
        assert not harness.channel.of("answer")
        assert harness.channel.of("error")[-1]["fatal"] is True
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


def test_unattributed_conversation_item_has_a_deadline_without_another_utterance():
    async def scenario():
        harness = await NativeHarness(handshake_timeout=0.03).start()
        await harness.session._handle_upstream({"type": "conversation.item.created", "item": {"id": "unowned"}})
        await harness.until(lambda: harness.task.done())
        assert not harness.upstream.of("response.create")
        assert harness.channel.of("error")[-1]["fatal"] is True
        assert await harness.finish() == "voice_unavailable"
    run(scenario)


@pytest.mark.parametrize("phase", ["prepare", "tool"])
def test_timed_out_turn_cannot_resume_when_backend_suppresses_cancellation(phase):
    async def scenario():
        harness = await NativeHarness(answer_timeout=0.03).start()
        entered = asyncio.Event()

        async def prepare(text):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return harness.context

        async def execute(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return {"evidence": []}

        if phase == "prepare":
            harness.session._prepare = prepare
        else:
            harness.session._execute = execute
        harness.hear("First", item="first")
        if phase == "tool":
            await harness.until(lambda: harness.upstream.of("response.create"))
            await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
            harness.response(output=[{"id": "call-item", "type": "function_call", "name": "knowledge_search",
                                      "call_id": "c1", "arguments": "{}"}])
        await entered.wait()
        await harness.until(lambda: harness.channel.of("error"))
        await harness.until(lambda: harness.session._answer_task.done())
        assert len(harness.upstream.of("response.create")) == (0 if phase == "prepare" else 1)
        assert not [event for event in harness.upstream.of("conversation.item.create")
                    if event["item"]["type"] == "function_call_output"]
        assert not harness.channel.of("answer")
        await harness.finish()
    run(scenario)


def test_cancel_during_tool_dispatch_state_change_does_not_schedule_old_tools():
    async def scenario():
        harness = await NativeHarness().start()
        harness.hear("First", item="first")
        await harness.until(lambda: harness.upstream.of("response.create"))
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r1"}})
        await harness.session._handle_upstream({"type": "response.audio.delta", "response_id": "r1",
                                              "delta": base64.b64encode(PCM).decode()})
        entered, release = asyncio.Event(), asyncio.Event()
        send = harness.channel.send_json

        async def blocked(message):
            if message == {"type": "state", "state": "thinking"}:
                entered.set()
                await release.wait()
            await send(message)

        harness.channel.send_json = blocked
        dispatch = asyncio.create_task(harness.session._handle_upstream({"type": "response.done", "response": {
            "id": "r1", "status": "completed", "output": [{"id": "call", "type": "function_call",
            "name": "knowledge_search", "call_id": "c1", "arguments": "{}"}]}}))
        await entered.wait()
        await harness.session.handle_control({"type": "interrupt"})
        release.set()
        await dispatch
        assert not harness.executions and not harness.channel.of("answer")
        assert len(harness.upstream.of("response.create")) == 1
        await harness.finish()
    run(scenario)


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


def test_native_vad_never_creates_or_cancels_responses_implicitly():
    async def scenario():
        harness = await NativeHarness().start()
        detection = harness.upstream.of("session.update")[0]["session"]["turn_detection"]
        assert detection["type"] == "server_vad"
        assert detection["create_response"] is False
        assert detection["interrupt_response"] is False
        harness.hear("Explain setup")
        await harness.until(lambda: harness.upstream.of("response.create"))
        for update in harness.upstream.of("session.update")[1:]:
            assert "turn_detection" not in update["session"]
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
        tool_task = harness.session._answer_task
        await harness.session.handle_control({"type": "interrupt"})
        harness.hold_tool.set()
        await asyncio.gather(tool_task, return_exceptions=True)
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


def test_revoked_finish_authorization_reports_forbidden_without_publishing():
    async def scenario():
        harness = await NativeHarness().start()

        def forbidden(*args):
            raise PermissionError("SECRET authorization details")

        harness.context.finish = forbidden
        harness.hear("Explain setup")
        await harness.until(lambda: harness.upstream.of("response.create"))
        harness.upstream.push({"type": "response.created", "response": {"id": "r1"}})
        harness.response()
        await harness.until(lambda: harness.channel.of("error"))
        error = harness.channel.of("error")[-1]
        assert error["code"] == "forbidden" and error["fatal"] is False
        assert "Typing still works" in error["message"] and "SECRET" not in error["message"]
        assert not harness.channel.of("answer")
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
        await harness.until(lambda: len(harness.prepared) == 2)
        harness.response(identifier="r1")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        await harness.session._handle_upstream({"type": "response.created", "response": {"id": "r2"}})
        await harness.session._handle_upstream({"type": "response.audio.delta", "response_id": "r1",
                                               "delta": base64.b64encode(PCM).decode()})
        await harness.session._handle_upstream({"type": "response.done", "response": {
            "id": "r1", "status": "completed", "output": [
                {"id": "r1-output-0", "type": "message", "role": "assistant",
                 "content": [{"type": "text", "text": "Old [S1]"}]}]}})
        await harness.session._handle_upstream({"type": "response.audio.delta", "response_id": "r1",
                                               "delta": base64.b64encode(PCM).decode()})
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
        await harness.until(lambda: harness.prepared)
        harness.upstream.push({"type": "conversation.item.input_audio_transcription.completed",
                               "item_id": "old", "transcript": "Old question"})
        await harness.until(lambda: harness.upstream.of("response.create"))
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
            release.set()
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
        harness = await NativeHarness(ack_creations=False).start()
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
        release.set()
        harness.upstream.send = send
        harness.upstream.ack_creations = True
        harness.hear("Current", item="current")
        await harness.until(lambda: len(harness.prepared) == 2)
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
        harness.upstream.push({"type": "conversation.item.created",
                              "item": {"id": "old-tool-call", "type": "function_call"}})
        harness.response(output=[{"id": "old-tool-call", "type": "function_call", "call_id": "c1",
                                  "name": "knowledge_search", "arguments": "{}"}])
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 2)
        result_id = harness.upstream.of("conversation.item.create")[-1]["item"]["id"]
        assert not harness.upstream.of("conversation.item.delete")
        harness.upstream.push({"type": "response.created", "response": {"id": "r2"}})
        harness.upstream.push({"type": "response.output_item.added", "response_id": "r2",
                              "item": {"id": "old-assistant", "type": "message", "role": "assistant"}})
        harness.response(identifier="r2", output=[{"id": "old-assistant", "type": "message", "role": "assistant",
                                                  "content": [{"type": "text", "text": "Grounded [S1]"}]}])
        await harness.until(lambda: harness.channel.of("answer"))
        harness.hear("Second", item="current-user")
        await harness.until(lambda: len(harness.upstream.of("response.create")) == 3)
        deleted = {event["item_id"] for event in harness.upstream.of("conversation.item.delete")}
        assert {context_id, "old-user", "old-assistant", "old-tool-call", result_id} <= deleted
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
