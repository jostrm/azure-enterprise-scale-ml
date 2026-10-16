"""Offline SDK-shaped Responses tests; never counted as live evaluation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sales_demo.agent import deploy_agent, invoke_agent, tool_definitions
from sales_demo.evaluation import evaluate_result, parse_reported_total
from sales_demo.identity import SalesUnavailable
from sales_demo.runtime import config_fingerprint


CONFIG = {"owner": "aif48-project001-dev", "dataset": "car-sales", "version": "v1"}


class Responses:
    def __init__(self, output):
        self.output = list(output)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self.output.pop(0)


def response(items, text=""):
    return SimpleNamespace(id="resp", output=items, output_text=text, status="completed")


def call(name="aggregate_sales", arguments='{"source":"all"}', call_id="call-1"):
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}


class Runtime:
    def __init__(self):
        self.config = deepcopy(CONFIG)
        self.trace = []

    def aggregate_sales(self, source):
        result = {"total_minor": 12345, "currency": "USD", "scope": source,
                  "source_subtotals_minor": {"json": 10000, "excel": 2345},
                  "provenance": [{"partition": "json", "index": "idx-json"},
                                 {"partition": "excel", "index": "idx-excel"}]}
        self.trace.append({"tool": "aggregate_sales", "arguments": {"source": source},
                           "indexes": ["idx-json", "idx-excel"], "result": result})
        return result

    def retrieve_sales(self, question):
        return {"evidence": []}


def deployment():
    return {"name": "aif48-sales", "version": "7", "owner": CONFIG["owner"],
            "config_sha256": config_fingerprint(CONFIG), "definition_sha256": "definition"}


def project(outputs):
    record = SimpleNamespace(
        metadata={"aifactory.managed_by": "40-agent-factory", "aif48.owner": CONFIG["owner"],
                  "aif48.config_sha256": config_fingerprint(CONFIG),
                  "aifactory.definition_hash": "definition"}, version="7",
    )
    responses = Responses(outputs)
    return SimpleNamespace(
        agents=SimpleNamespace(get_version=lambda **kw: record),
        get_openai_client=lambda **kw: SimpleNamespace(responses=responses, close=lambda: None),
        responses=responses,
    )


class AgentTests(unittest.TestCase):
    def test_notification_during_model_round_discards_final_answer(self):
        api = project([response([call()]), response([], "Total: USD 123.45")])
        with patch("sales_demo.agent.assert_guard_unchanged",
                   side_effect=[None, None, SalesUnavailable()]):
            with self.assertRaises(SalesUnavailable):
                invoke_agent(api, Runtime(), "Give me the sum of all sales.",
                             deployment=deployment(), allow_paid=True)
    def test_sdk_function_schema_is_real_flat_functiontool_schema(self):
        from azure.ai.projects.models import FunctionTool
        tools = tool_definitions()
        self.assertEqual([t["name"] for t in tools], ["aggregate_sales", "retrieve_sales"])
        for value in tools:
            self.assertEqual(FunctionTool(**value).as_dict(), value)
            self.assertFalse(value["parameters"]["additionalProperties"])
        self.assertEqual(tools[0]["parameters"]["properties"]["source"]["enum"], ["all", "json", "excel"])

    def test_stateless_loop_preserves_exact_question_and_pinned_agent(self):
        question = "  Give me the sum of all sales.\n"
        api = project([response([call()]), response([], "Total: USD 123.45")])
        result = invoke_agent(api, Runtime(), question, deployment=deployment(), allow_paid=True)
        self.assertEqual(result["authoritative"][0]["total_minor"], 12345)
        self.assertIn("Authoritative total (all): USD 123.45", result["answer"])
        calls = api.responses.calls
        self.assertEqual(calls[0]["input"], [{"role": "user", "content": question}])
        self.assertEqual(len(calls[1]["input"]), 3)
        self.assertEqual(calls[1]["input"][1]["type"], "function_call")
        self.assertEqual(calls[1]["input"][2]["type"], "function_call_output")
        for request in calls:
            self.assertFalse(request["store"])
            self.assertNotIn("previous_response_id", request)
            self.assertEqual(request["extra_body"]["agent_reference"]["version"], "7")
            self.assertNotIn("agent", request["extra_body"])

    def test_paid_gate_before_any_cloud_access(self):
        with self.assertRaises(ValueError):
            invoke_agent(None, Runtime(), "question", deployment=deployment())
        with self.assertRaises(ValueError):
            deploy_agent(None, CONFIG, name="aif48-sales", model="model", apply=True)
        with self.assertRaises(ValueError):
            deploy_agent(None, CONFIG, name="aif48-sales", model="model", allow_paid=True)

    def test_unknown_tools_arguments_and_duplicate_keys_are_fatal(self):
        for item in [
            call("download", '{"url":"https://evil.example"}'),
            call(arguments='{"source":"all","user":"other"}'),
            call(arguments='{"source":"all","source":"json"}'),
            call(arguments='{"source":"unknown"}'),
        ]:
            api = project([response([item])])
            with self.assertRaises(SalesUnavailable):
                invoke_agent(api, Runtime(), "total", deployment=deployment(), allow_paid=True)
            self.assertEqual(len(api.responses.calls), 1)

    def test_tool_failure_never_becomes_a_model_partial_answer(self):
        api, runtime = project([response([call()])]), Runtime()
        runtime.aggregate_sales = lambda source: (_ for _ in ()).throw(PermissionError("secret"))
        with self.assertRaisesRegex(SalesUnavailable, "^Sales data unavailable\\.$"):
            invoke_agent(api, runtime, "total", deployment=deployment(), allow_paid=True)
        self.assertEqual(len(api.responses.calls), 1)

    def test_unsupported_numeric_answer_and_changed_binding_fail(self):
        api = project([response([], "Total: USD 999.00")])
        with self.assertRaises(SalesUnavailable):
            invoke_agent(api, Runtime(), "total", deployment=deployment(), allow_paid=True)
        state = deployment()
        state["config_sha256"] = "other"
        with self.assertRaises(SalesUnavailable):
            invoke_agent(project([]), Runtime(), "total", deployment=state, allow_paid=True)

    def test_deploy_checks_owner_before_mutation(self):
        existing = SimpleNamespace(versions=SimpleNamespace(latest=SimpleNamespace(
            metadata={"aifactory.managed_by": "someone-else"})))
        api = SimpleNamespace(agents=SimpleNamespace(get=lambda **kw: existing))
        with self.assertRaises(ValueError):
            deploy_agent(api, CONFIG, name="aif48-sales", model="model", apply=True, allow_paid=True)

    def test_deploy_persists_then_rechecks_before_routing_and_reuses_version(self):
        from azure.core.exceptions import ResourceNotFoundError
        class Agents:
            def __init__(self):
                self.record = None
                self.creates = 0

            def get(self, **kwargs):
                if self.record is None:
                    raise ResourceNotFoundError()
                return SimpleNamespace(versions=SimpleNamespace(latest=self.record))

            def create_version(self, **kwargs):
                self.creates += 1
                self.record = SimpleNamespace(version="1", id="persisted", **kwargs)
                return self.record

            def get_version(self, **kwargs):
                return self.record

        api = SimpleNamespace(agents=Agents())
        with patch("sales_demo.agent.route_version") as route:
            first = deploy_agent(api, CONFIG, name="aif48-sales", model="model", apply=True, allow_paid=True)
            second = deploy_agent(api, CONFIG, name="aif48-sales", model="model", apply=True, allow_paid=True)
            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(api.agents.creates, 1)
            self.assertEqual(route.call_count, 2)
            api.agents.record.metadata["aif48.config_sha256"] = "foreign"
            with self.assertRaises(ValueError):
                deploy_agent(api, CONFIG, name="aif48-sales", model="model", apply=True, allow_paid=True)
            self.assertEqual(route.call_count, 2)

    def test_evaluator_parses_decimal_not_substring(self):
        self.assertEqual(parse_reported_total("Total: USD 12,345.67"), 1234567)
        with self.assertRaises(ValueError):
            parse_reported_total("Total: USD 12345.67001")
        result = {"generated_text": "Total: USD 123.45",
                  "authoritative": [Runtime().aggregate_sales("all")],
                  "trace": [{"tool": "aggregate_sales", "arguments": {"source": "all"},
                             "indexes": ["idx-json", "idx-excel"]}]}
        self.assertTrue(evaluate_result(result, 12345, source="all", expected_indexes={"idx-json", "idx-excel"})["passed"])
        result["generated_text"] = "Total: USD 1234.50"
        self.assertFalse(evaluate_result(result, 12345, source="all", expected_indexes={"idx-json", "idx-excel"})["passed"])

    def test_numeric_answer_requires_both_index_trace_not_just_correct_text(self):
        result = {"generated_text": "Total: USD 123.45",
                  "authoritative": [Runtime().aggregate_sales("all")],
                  "trace": [{"tool": "aggregate_sales", "arguments": {"source": "all"},
                             "indexes": ["idx-json"]}]}
        self.assertFalse(evaluate_result(result, 12345, source="all")["passed"])

    def test_duplicate_function_call_id_aborts_without_reexecuting(self):
        api = project([response([call()]), response([call()])])
        runtime = Runtime()
        with self.assertRaises(SalesUnavailable):
            invoke_agent(api, runtime, "total", deployment=deployment(), allow_paid=True)
        self.assertEqual(len(runtime.trace), 1)

    def test_generated_total_cannot_contradict_the_calculator(self):
        api = project([response([call()]), response([], "Total: USD 1234.50")])
        with self.assertRaises(SalesUnavailable):
            invoke_agent(api, Runtime(), "Give me the sum of all sales.",
                         deployment=deployment(), allow_paid=True)

    def test_source_breakdown_must_match_each_deterministic_subtotal(self):
        for text in (
            "Total: USD 123.45\nSource json: USD 100.00\nSource excel: USD 23.45",
            "Total: USD 123.45\nSource json: USD 99.00\nSource excel: USD 24.45",
        ):
            api = project([response([call()]), response([], text)])
            if "99.00" in text:
                with self.assertRaises(SalesUnavailable):
                    invoke_agent(api, Runtime(), "Give me the total and break it down by source.",
                                 deployment=deployment(), allow_paid=True)
            else:
                self.assertTrue(invoke_agent(
                    api, Runtime(), "Give me the total and break it down by source.",
                    deployment=deployment(), allow_paid=True)["authoritative"])

    def test_retrieval_citations_with_digits_do_not_require_an_unrelated_sum(self):
        api = project([
            response([call("retrieve_sales", '{"question":"Which models occur?"}')]),
            response([], "Cedar EV appears in source v1, sale SALE-123."),
        ])
        result = invoke_agent(api, Runtime(), "Which models occur in both sources?",
                              deployment=deployment(), allow_paid=True)
        self.assertEqual(result["authoritative"], [])

    def test_ungrounded_tool_free_answer_fails(self):
        with self.assertRaises(SalesUnavailable):
            invoke_agent(project([response([], "Cedar EV appears.")]), Runtime(),
                         "Which models occur?", deployment=deployment(), allow_paid=True)


if __name__ == "__main__":
    unittest.main()
