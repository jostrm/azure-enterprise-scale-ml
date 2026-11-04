"""Offline browser fixture only. No credential, SDK, or external service is used.

Run explicitly with --serve for Playwright, or --self-test for fixture checks.
This module is not imported by any production entrypoint.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from contextlib import asynccontextmanager

from fastapi import Request

from sales_agent.config import Settings
from sales_agent.contracts import SalesError
from sales_agent.web import create_app

PORT = 18765
ORIGIN = f"http://127.0.0.1:{PORT}"
SETTINGS = Settings(
    tenant_id="11111111-1111-4111-8111-111111111111",
    subscription_id="22222222-2222-4222-8222-222222222222",
    project_endpoint="https://offline.invalid/api/projects/browser-test",
    agent_name="offline-browser-test",
    agent_version="1",
    fabric_url="https://offline.invalid/mcp",
    voice_enabled=True,
    voice_endpoint="https://offline.invalid",
    voice_model="gpt-realtime",
    voice_name="alloy",
)
METRICS = {"resets": 0, "answers": 0, "mic_frames": 0, "mic_bytes": 0,
           "connections": 0, "closed": 0, "rounds": [], "truncations": []}
ACTIVE = set()


class FixtureConversation:
    def __init__(self):
        self.turn = 0

    async def answer(self, text, on_event=None):
        if text == "fixture error":
            raise SalesError("service_unavailable", "Offline fixture error.", 503)
        self.turn += 1
        METRICS["answers"] += 1
        if on_event:
            await on_event({"type": "tool", "name": "fabric_mcp", "status": "running"})
        result = {
            "answer": f"Offline fixture answer {self.turn}: sales increased by 5%. [F1]\n"
                      "<img src=x onerror=window.fixtureInjected=true>",
            "provenance": [{
                "id": "F1", "tool": "fabric_mcp", "endpoint": "https://example.invalid/sales",
                "content": [{"type": "text", "text": "Fixture only. <script>window.fixtureInjected=true</script>"}],
                "structured_content": {"region": "North", "sales_change_percent": 5},
            }],
            "agent_annotations": [{"type": "url_citation", "url": "javascript:alert('fixture')",
                                   "title": "<img onerror=window.fixtureInjected=true>"}],
            "response_id": f"fixture-answer-{METRICS['answers']}",
            "grounding": "sources_attached",
        }
        if on_event:
            await on_event({"type": "tool", "name": "fabric_mcp", "status": "completed"})
        return result

    def reset(self):
        self.turn = 0
        METRICS["resets"] += 1


class FixtureUpstream:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.round = 0
        self.started = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.queue.get())

    async def emit(self, event):
        await self.queue.put(event)

    async def utterance(self):
        await self.emit({"type": "input_audio_buffer.speech_started"})
        await self.emit({"type": "conversation.item.input_audio_transcription.completed",
                         "transcript": "What changed in fixture sales?"})
        await self.emit({"type": "input_audio_buffer.committed"})

    async def send(self, raw):
        event = json.loads(raw)
        kind = event["type"]
        if kind == "session.update":
            await self.emit({"type": "session.updated"})
        elif kind == "input_audio_buffer.append":
            METRICS["mic_frames"] += 1
            METRICS["mic_bytes"] += len(base64.b64decode(event["audio"]))
            if not self.started:
                self.started = True
                await self.utterance()
        elif kind == "response.create":
            self.round += 1
            identifier = f"fixture-response-{self.round}"
            speech = "audio" in event["response"]["modalities"]
            METRICS["rounds"].append("speech" if speech else "query")
            await self.emit({"type": "response.created", "response": {"id": identifier}})
            if not speech:
                output = [{"type": "function_call", "name": "ask_sales_agent",
                           "call_id": f"fixture-call-{self.round}",
                           "arguments": '{"question":"What changed in fixture sales?"}'}]
            else:
                output = []
                item = f"fixture-audio-{self.round}"
                for delta in ("Fixture sales ", "increased by 5%."):
                    await self.emit({"type": "response.audio_transcript.delta", "response_id": identifier,
                                     "item_id": item, "delta": delta})
                # Silent PCM still exercises the real playback/worklet clock; no speaker sound is required.
                await self.emit({"type": "response.audio.delta", "response_id": identifier,
                                 "item_id": item, "delta": base64.b64encode(bytes(24000 * 2 * 8)).decode()})
                await self.emit({"type": "response.audio_transcript.done", "response_id": identifier,
                                 "item_id": item, "transcript": "Fixture sales increased by 5%."})
            await self.emit({"type": "response.done",
                             "response": {"id": identifier, "status": "completed", "output": output}})
        elif kind == "conversation.item.truncate":
            METRICS["truncations"].append({"item_id": event["item_id"], "audio_end_ms": event["audio_end_ms"]})
            await self.emit({"type": "conversation.item.truncated", "item_id": event["item_id"]})


@asynccontextmanager
async def fixture_voice_connector():
    upstream = FixtureUpstream()
    ACTIVE.add(upstream)
    METRICS["connections"] += 1
    try:
        yield upstream
    finally:
        ACTIVE.discard(upstream)
        METRICS["closed"] += 1


app = create_app(SETTINGS, FixtureConversation, fixture_voice_connector, port=PORT)


@app.get("/__fixture/metrics")
async def metrics():
    return {**METRICS, "active": len(ACTIVE)}


@app.post("/__fixture/control")
async def control(request: Request):
    body = await request.json()
    if body.get("action") == "barge":
        for upstream in tuple(ACTIVE):
            await upstream.utterance()
    elif body.get("action") == "error":
        for upstream in tuple(ACTIVE):
            await upstream.emit({"type": "error", "error": {"code": "offline_fixture_error"}})
    else:
        return {"error": "unknown_fixture_action"}
    return {"status": "ok"}


def self_test():
    from fastapi.testclient import TestClient

    with TestClient(app, base_url=ORIGIN) as client:
        headers = {"Origin": ORIGIN}
        assert client.get("/api/health").json()["cloud_verified"] is False
        assert client.post("/api/session", json={}, headers=headers).json()["voice_enabled"] is True
        answer = client.post("/api/chat", json={"text": "Sales?"}, headers=headers).json()
        assert answer["grounding"] == "sources_attached" and answer["agent_annotations"]
        assert client.post("/api/conversation/reset", json={}, headers=headers).status_code == 200
        assert client.post("/api/chat", json={"text": "fixture error"}, headers=headers).status_code == 503
    print("Offline UI fixture self-test passed; no cloud calls.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
