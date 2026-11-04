import asyncio
import json
import unittest

from sales_agent.contracts import SalesError
from sales_agent.service import SalesConversation


class FakeGateway:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.conversations = 0

    async def create_conversation(self):
        self.conversations += 1
        return f"conv_{self.conversations}"

    async def respond(self, conversation, items, *, force_tool):
        self.requests.append((conversation, items, force_tool))
        return self.responses.pop(0)


def call(name="query_sales_data", arguments='{"question":"Sales this month?"}', call_id="call1"):
    return {"status": "completed", "output": [
        {"type": "function_call", "name": name, "arguments": arguments, "call_id": call_id}
    ]}


def answer(text="Verified sales were 12 [F1]."):
    return {"id": "resp1", "status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": text}]}
    ]}


class FakeFabric:
    def __init__(self):
        self.questions = []

    async def query(self, question):
        self.questions.append(question)
        return {"tool": "published_sales_tool", "endpoint": "https://api.fabric.microsoft.com",
                "content": [{"type": "text", "text": '{"sales":12}'}],
                "structured_content": {"sales": 12}}


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_ids_do_not_alias_previous_turns(self):
        gateway = FakeGateway([call(), answer(), call(call_id="c2"), answer("Sales 12 [F2].")])
        service = SalesConversation(gateway, FakeFabric())
        await service.answer("First period")
        result = await service.answer("Second period")
        self.assertEqual(result["provenance"][0]["id"], "F2")

    async def test_retains_annotations_on_foundry_answer_blocks(self):
        final = answer()
        annotation = {"type": "url_citation", "url": "https://example.invalid/report", "title": "Source"}
        final["output"][0]["content"][0]["annotations"] = [annotation]
        result = await SalesConversation(FakeGateway([call(), final]), FakeFabric()).answer("Sales?")
        self.assertEqual(result["agent_annotations"], [annotation])

    async def test_requires_real_function_grounding_and_preserves_provenance(self):
        gateway, fabric = FakeGateway([call(), answer()]), FakeFabric()
        service = SalesConversation(gateway, fabric)
        result = await service.answer("Sales this month?")
        self.assertEqual(fabric.questions, ["Sales this month?"])
        self.assertTrue(gateway.requests[0][2])
        self.assertEqual(result["provenance"][0]["structured_content"], {"sales": 12})
        output = json.loads(gateway.requests[1][1][0]["output"])
        self.assertEqual(output["provenance"]["id"], "F1")
        self.assertEqual(result["grounding"], "sources_attached")

    async def test_no_grounding_is_not_a_successful_answer(self):
        with self.assertRaises(SalesError):
            await SalesConversation(FakeGateway([answer()]), FakeFabric()).answer("Sales?")

    async def test_tool_name_and_closed_arguments_are_enforced(self):
        for response in (call("delete_data"), call(arguments='{"question":"x","url":"evil"}'),
                         call(arguments='{"question":""}'), call(arguments="not JSON"),
                         call(arguments='{"question":"a","question":"b"}')):
            fabric = FakeFabric()
            with self.subTest(response=response), self.assertRaises(SalesError):
                await SalesConversation(FakeGateway([response]), fabric).answer("Sales?")
            self.assertEqual(fabric.questions, [])

    async def test_error_incomplete_and_fabric_failure_do_not_fallback(self):
        for status in ("incomplete", "failed", "cancelled"):
            with self.subTest(status=status), self.assertRaises(SalesError):
                await SalesConversation(FakeGateway([{"status": status, "output": []}]),
                                        FakeFabric()).answer("Sales?")

    async def test_invented_provenance_is_rejected(self):
        with self.assertRaises(SalesError):
            await SalesConversation(FakeGateway([call(), answer("Sales 12 [F99].")]),
                                    FakeFabric()).answer("Sales?")

    async def test_bounds_tool_rounds_and_rejects_duplicate_call_ids(self):
        fabric = FakeFabric()
        with self.assertRaises(SalesError):
            await SalesConversation(FakeGateway([call(), call()]), fabric).answer("Sales?")
        self.assertEqual(len(fabric.questions), 1)

    async def test_failed_turn_does_not_reuse_poisoned_conversation(self):
        gateway = FakeGateway([answer(), call(), answer()])
        service = SalesConversation(gateway, FakeFabric())
        with self.assertRaises(SalesError):
            await service.answer("No source")
        await service.answer("Retry")
        self.assertEqual(gateway.conversations, 2)

    async def test_concurrent_turn_is_rejected_without_extra_service_calls(self):
        entered, release = asyncio.Event(), asyncio.Event()
        fabric = FakeFabric()

        async def wait_query(question):
            entered.set()
            await release.wait()
            return {"tool": "t", "content": [], "structured_content": {"sales": 1}}

        fabric.query = wait_query
        service = SalesConversation(FakeGateway([call(), answer()]), fabric)
        task = asyncio.create_task(service.answer("Sales?"))
        await entered.wait()
        with self.assertRaises(SalesError):
            await service.answer("Concurrent")
        release.set()
        await task


if __name__ == "__main__":
    unittest.main()
