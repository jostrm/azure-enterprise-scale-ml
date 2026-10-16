import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.support import consumer

from ml_agent.agent import agent_name, dispatch, invoke_agent, tool_definitions
from ml_agent.configuration import fingerprint
from ml_agent.runtime import ApprovalRequired, MLRuntime
from ml_agent.usecases import AIR, CHURN


class FakeResponses:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return self.replies.pop(0)


class FakeClient:
    def __init__(self, replies):
        self.responses = FakeResponses(replies)
        self.closed = False

    def close(self):
        self.closed = True


def response(output, text=""):
    return SimpleNamespace(status="completed", output=output, output_text=text)


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = consumer(Path(cls.temporary.name), instantiate=False)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_tools_are_strict_and_allowlisted(self):
        tools = {tool["name"]: tool for tool in tool_definitions()}
        self.assertEqual(set(tools), {"list_usecases", "get_usecase_status", "create_usecase_from_template",
                                      "start_training", "start_retraining", "run_batch_inference",
                                      "get_predictions_summary"})
        for tool in tools.values():
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["parameters"]["additionalProperties"])
        self.assertEqual(tools["create_usecase_from_template"]["parameters"]["properties"]["usecase"]["enum"], [CHURN])
        self.assertEqual(tools["start_retraining"]["parameters"]["properties"]["usecase"]["enum"], [AIR])

    def test_dispatch_rejects_unknown_input_and_reports_approval_needs(self):
        runtime = MLRuntime(self.config)
        with self.assertRaises(ValueError):
            dispatch(runtime, "delete_everything", {})
        with self.assertRaises(ValueError):
            dispatch(runtime, "start_training", {"usecase": CHURN, "path": "C:/"})
        with self.assertRaises(ValueError):
            dispatch(runtime, "start_training", {"usecase": "titanic"})
        denied = dispatch(runtime, "start_training", {"usecase": CHURN})
        self.assertFalse(denied["ok"])
        self.assertIn("approved plan", denied["error"])
        listed = dispatch(runtime, "list_usecases", {})
        self.assertTrue(listed["ok"])
        self.assertEqual([item["name"] for item in listed["result"]["usecases"]], [CHURN, AIR])

    def test_conversation_executes_tools_locally_and_returns_the_answer(self):
        runtime = MLRuntime(self.config)
        call = {"type": "function_call", "call_id": "call-1", "name": "list_usecases", "arguments": "{}"}
        message = {"type": "message", "role": "assistant", "content": []}
        client = FakeClient([response([call]), response([message], "Two use cases are available.")])
        name = agent_name(self.config)
        record = SimpleNamespace(metadata={"aifactory.managed_by": "40-agent-factory",
                                           "aif49.owner": self.config["owner"],
                                           "aif49.config_sha256": fingerprint(self.config),
                                           "aifactory.definition_hash": "abc"})
        project = SimpleNamespace(agents=SimpleNamespace(get_version=lambda **_: record),
                                  get_openai_client=lambda **_: client)
        deployment = {"name": name, "version": "1", "config_sha256": fingerprint(self.config),
                      "definition_sha256": "abc"}
        result = invoke_agent(project, runtime, "What can you do?", deployment=deployment, allow_paid=True)
        self.assertEqual(result["answer"], "Two use cases are available.")
        self.assertEqual(result["function_calls"], [{"name": "list_usecases", "arguments": {}, "ok": True}])
        self.assertTrue(client.closed)
        second = client.responses.requests[1]["input"]
        output = json.loads(second[-1]["output"])
        self.assertTrue(output["ok"])
        self.assertEqual(client.responses.requests[0]["extra_body"]["agent_reference"]["name"], name)
        with self.assertRaises(ApprovalRequired):
            invoke_agent(project, runtime, "hi", deployment=deployment, allow_paid=False)
        with self.assertRaises(ValueError):
            invoke_agent(project, runtime, "hi", deployment={**deployment, "config_sha256": "0"}, allow_paid=True)


if __name__ == "__main__":
    unittest.main()
