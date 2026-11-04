from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Protocol

from .contracts import MAX_QUESTION, SalesError, question_arguments


class AgentGateway(Protocol):
    async def create_conversation(self) -> str: ...
    async def respond(self, conversation: str, items: str | list, *, force_tool: bool) -> dict: ...


class DataAgent(Protocol):
    async def query(self, question: str) -> dict: ...


class SalesConversation:
    def __init__(self, gateway: AgentGateway, fabric: DataAgent):
        self.gateway, self.fabric = gateway, fabric
        self.conversation_id: str | None = None
        self._lock = asyncio.Lock()
        self._source_index = 0

    def reset(self):
        if self._lock.locked():
            raise SalesError("busy", "Wait for the current request before starting a new conversation.", 409)
        self.conversation_id = None

    async def answer(self, question: str, activity: Callable[[dict], Awaitable[None]] | None = None):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= MAX_QUESTION:
            raise SalesError("invalid_question", "Enter a question of 1 to 6000 characters.", 400)
        if self._lock.locked():
            raise SalesError("busy", "A request is already running in this conversation.", 409)
        async with self._lock:
            succeeded = False
            try:
                async with asyncio.timeout(240):
                    result = await self._answer(question.strip(), activity)
                    succeeded = True
                    return result
            except TimeoutError as exc:
                raise SalesError("answer_timeout", "The grounded answer timed out. Try a narrower question.", 504) from exc
            finally:
                # A cancelled/failed tool turn must not poison the next Responses continuation.
                if not succeeded:
                    self.conversation_id = None

    async def _answer(self, question, activity):
        if self.conversation_id is None:
            self.conversation_id = await self.gateway.create_conversation()
            self._source_index = 0
        items: str | list = question
        provenance = []
        seen = set()
        for round_number in range(5):
            response = await self.gateway.respond(self.conversation_id, items, force_tool=round_number == 0)
            if response.get("status") != "completed":
                raise SalesError("agent_incomplete", "Foundry did not complete the response. No answer was accepted.")
            outputs = response.get("output", [])
            if not isinstance(outputs, list):
                raise SalesError("agent_protocol", "Foundry returned an unexpected response format.")
            calls = [item for item in outputs if item.get("type") == "function_call"]
            if calls:
                if len(calls) != 1 or round_number == 4:
                    raise SalesError("tool_budget", "The agent exceeded the read-only tool budget.")
                call = calls[0]
                call_id = call.get("call_id")
                if (call.get("name") != "query_sales_data" or not isinstance(call_id, str)
                        or not call_id or call_id in seen):
                    raise SalesError("unapproved_tool", "Foundry requested an unapproved or repeated tool call.")
                seen.add(call_id)
                text = question_arguments(call.get("arguments"))
                if activity:
                    await activity({"type": "tool", "name": "fabric_mcp", "status": "running"})
                evidence = await self.fabric.query(text)
                self._source_index += 1
                entry = {**evidence, "id": f"F{self._source_index}"}
                provenance.append(entry)
                if activity:
                    await activity({"type": "tool", "name": "fabric_mcp", "status": "completed"})
                items = [{
                    "type": "function_call_output", "call_id": call_id,
                    "output": json.dumps({"untrusted_data": True, "provenance": entry}, ensure_ascii=True),
                }]
                continue
            if not provenance:
                raise SalesError("ungrounded_answer", "No Fabric evidence was returned. No sales answer was accepted.")
            answer = "\n".join(
                block["text"] for item in outputs if item.get("type") == "message"
                for block in item.get("content", [])
                if block.get("type") == "output_text" and isinstance(block.get("text"), str)
            ).strip()
            if not answer:
                raise SalesError("empty_answer", "The agent returned no written answer.")
            allowed = {source["id"] for source in provenance}
            if set(re.findall(r"\[(F[0-9]+)\]", answer)) - allowed:
                raise SalesError("invalid_citation", "The answer cited evidence that was not returned by Fabric.")
            annotations = [
                annotation for item in outputs if item.get("type") == "message"
                for block in item.get("content", []) if block.get("type") == "output_text"
                for annotation in block.get("annotations", [])
            ]
            return {"answer": answer, "provenance": provenance, "response_id": response.get("id", ""),
                    "grounding": "sources_attached", "agent_annotations": annotations}
        raise SalesError("tool_budget", "The agent exceeded the read-only tool budget.")
