import asyncio
import base64
import json
import unittest

from sales_agent.config import Settings
from sales_agent.contracts import SalesError
from sales_agent.voice import VoiceRelay
from test_config import values


class Socket:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class Channel:
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


def settings():
    return Settings.from_mapping({
        **values(), "VOICE_ENABLED": "true", "VOICE_ENDPOINT": "https://voice.services.ai.azure.com",
        "VOICE_MODEL": "gpt-realtime", "VOICE_NAME": "alloy",
    })


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_before_send_lock_does_not_reserve_an_unsent_response(self):
        await self.relay._send_lock.acquire()
        try:
            self.relay.spawn(self.relay.create_round(self.relay.turn, "query"))
            await asyncio.sleep(0.01)
            await self.relay.handle_upstream({"type": "input_audio_buffer.speech_started"})
            self.assertTrue(self.relay.slot.is_set())
            self.assertFalse(any(x["type"] == "response.create" for x in self.socket.sent))
        finally:
            self.relay._send_lock.release()
        await self.relay.handle_upstream({"type": "input_audio_buffer.committed"})
        await asyncio.sleep(0.01)
        self.assertTrue(any(x["type"] == "response.create" for x in self.socket.sent))

    async def test_cancelling_after_tool_output_does_not_submit_duplicate_output(self):
        waiting = asyncio.Event()

        async def blocked_round(*args):
            waiting.set()
            await asyncio.Event().wait()

        self.relay.create_round = blocked_round
        task = asyncio.create_task(self.relay.ground(self.relay.turn, "c1", "Sales?"))
        await waiting.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        outputs = [x for x in self.socket.sent if x["type"] == "conversation.item.create"]
        self.assertEqual(len(outputs), 1)

    async def asyncSetUp(self):
        self.socket, self.channel, self.questions = Socket(), Channel(), []

        async def answer(question, activity=None):
            self.questions.append(question)
            return {"answer": "Sales 12 [F1].", "provenance": [{"id": "F1"}],
                    "response_id": "foundry1", "grounding": "sources_attached"}

        self.relay = VoiceRelay(settings(), self.socket, self.channel, answer)
        await self.relay.start()
        await self.relay.handle_upstream({"type": "session.updated"})

    async def asyncTearDown(self):
        await self.relay.close()

    async def begin(self):
        await self.relay.handle_upstream({"type": "input_audio_buffer.speech_started"})
        await self.relay.handle_upstream({"type": "input_audio_buffer.committed"})
        await asyncio.sleep(0.01)
        await self.relay.handle_upstream({"type": "response.created", "response": {"id": "r1"}})

    async def grounded(self):
        await self.begin()
        await self.relay.handle_upstream({"type": "response.done", "response": {
            "id": "r1", "status": "completed", "output": [{
                "type": "function_call", "call_id": "c1", "name": "ask_sales_agent",
                "arguments": '{"question":"Sales?"}',
            }],
        }})
        await asyncio.sleep(0.01)
        await self.relay.handle_upstream({"type": "response.created", "response": {"id": "r2"}})

    async def test_silent_session_then_forced_tool_round_before_audio(self):
        session = self.socket.sent[0]["session"]
        self.assertEqual(session["modalities"], ["text"])
        self.assertFalse(session["turn_detection"]["create_response"])
        await self.begin()
        request = next(x for x in self.socket.sent if x["type"] == "response.create")
        self.assertEqual(request["response"]["tool_choice"]["name"], "ask_sales_agent")
        await self.relay.handle_upstream({"type": "response.audio.delta", "response_id": "r1",
                                         "item_id": "a1", "delta": "AAA="})
        self.assertFalse(any(x["type"] == "audio" for x in self.channel.sent))

    async def test_grounded_round_streams_native_audio_and_keeps_authoritative_answer(self):
        await self.grounded()
        self.assertEqual(self.questions, ["Sales?"])
        native = [x for x in self.socket.sent if x["type"] == "response.create"][-1]
        self.assertEqual(native["response"]["modalities"], ["text", "audio"])
        self.assertEqual(native["response"]["tool_choice"], "none")
        await self.relay.handle_upstream({"type": "response.audio.delta", "response_id": "r2",
                                         "item_id": "a1", "delta": "AAA="})
        self.assertTrue(any(x["type"] == "answer" for x in self.channel.sent))
        self.assertTrue(any(x["type"] == "audio" for x in self.channel.sent))

    async def test_cancelled_function_done_is_never_dispatched(self):
        await self.begin()
        await self.relay.handle_upstream({"type": "response.done", "response": {
            "id": "r1", "status": "cancelled", "output": [{
                "type": "function_call", "name": "ask_sales_agent",
                "call_id": "c1", "arguments": '{"question":"Sales?"}',
            }],
        }})
        self.assertEqual(self.questions, [])

    async def test_interruption_revokes_audio_and_truncates_actual_played_position(self):
        await self.grounded()
        audio = base64.b64encode(bytes(48000)).decode()
        await self.relay.handle_upstream({"type": "response.audio.delta", "response_id": "r2",
                                         "item_id": "a1", "delta": audio})
        await self.relay.handle_upstream({"type": "input_audio_buffer.speech_started"})
        await self.relay.handle_client({"type": "interrupt", "item_id": "a1", "audio_end_ms": 120})
        self.assertIn({"type": "conversation.item.truncate", "item_id": "a1",
                       "content_index": 0, "audio_end_ms": 120}, self.socket.sent)
        count = sum(x["type"] == "audio" for x in self.channel.sent)
        await self.relay.handle_upstream({"type": "response.audio.delta", "response_id": "r2",
                                         "item_id": "a1", "delta": "AAAA"})
        self.assertEqual(count, sum(x["type"] == "audio" for x in self.channel.sent))

    async def test_audio_and_control_input_are_bounded(self):
        for invalid in (b"x", bytes(20000), {"type": "session.update", "tools": ["write"]},
                        {"type": "interrupt", "item_id": "unknown", "audio_end_ms": -1}):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaises(SalesError):
                await self.relay.handle_client(invalid)

    async def test_service_failure_cannot_enable_speech(self):
        async def failure(*args):
            raise SalesError("fabric_unavailable", "Fabric is unavailable.")

        self.relay.answer = failure
        await self.begin()
        await self.relay.handle_upstream({"type": "response.done", "response": {
            "id": "r1", "status": "completed", "output": [{
                "type": "function_call", "name": "ask_sales_agent",
                "call_id": "c1", "arguments": '{"question":"Sales?"}',
            }],
        }})
        await asyncio.sleep(0.01)
        self.assertFalse(any(x.get("response", {}).get("modalities") == ["text", "audio"]
                             for x in self.socket.sent))
        self.assertTrue(any(x["type"] == "error" for x in self.channel.sent))


if __name__ == "__main__":
    unittest.main()
