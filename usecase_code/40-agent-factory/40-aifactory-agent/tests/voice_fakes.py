"""Test doubles for the live voice relay: a scriptable Voice Live socket and a browser channel (no network, no audio)."""

import asyncio
import base64

PCM = b"\x01\x00" * 480  # 20 ms of 24 kHz mono PCM16


class FakeUpstream:
    """A Voice Live socket the test drives by pushing server events."""

    def __init__(self):
        self.sent, self.inbox, self.closed = [], asyncio.Queue(), False

    async def send(self, event):
        self.sent.append(event)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.inbox.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self):
        self.closed = True
        await self.inbox.put(None)

    def push(self, event):
        self.inbox.put_nowait(event)

    def of(self, kind):
        return [event for event in self.sent if event["type"] == kind]


class ReactiveUpstream(FakeUpstream):
    """Behaves like a minimal Voice Live: opens a session, hears one utterance, speaks whatever it is told to."""

    def __init__(self, transcript="How do I add a project?", utterance_after=1):
        super().__init__()
        self.transcript, self.utterance_after, self.appends, self.responses = transcript, utterance_after, 0, 0
        self.push({"type": "session.created", "session": {"id": "sess_1"}})

    async def send(self, event):
        await super().send(event)
        kind = event["type"]
        if kind == "session.update":
            self.push({"type": "session.updated", "session": {}})
        elif kind == "input_audio_buffer.append":
            self.appends += 1
            if self.appends == self.utterance_after:
                self.push({"type": "input_audio_buffer.speech_started", "item_id": "item_1"})
                self.push({"type": "input_audio_buffer.speech_stopped", "item_id": "item_1"})
                self.push({"type": "conversation.item.input_audio_transcription.completed",
                           "item_id": "item_1", "transcript": self.transcript})
        elif kind == "response.create":
            self.responses += 1
            identifier = f"resp_{self.responses}"
            self.push({"type": "response.created", "response": {"id": identifier}})
            self.push({"type": "response.audio.delta", "response_id": identifier,
                       "delta": base64.b64encode(PCM).decode()})
            self.push({"type": "response.done", "response": {"id": identifier, "status": "completed"}})


class FakeChannel:
    def __init__(self):
        self.json, self.audio = [], []

    async def send_json(self, message):
        self.json.append(message)

    async def send_audio(self, data):
        self.audio.append(data)

    def of(self, kind):
        return [message for message in self.json if message["type"] == kind]

    def states(self):
        return [message["state"] for message in self.of("state")]
