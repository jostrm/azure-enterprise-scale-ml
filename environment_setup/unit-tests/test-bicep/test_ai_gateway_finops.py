"""Credential-free contracts for the log-based AI gateway FinOps workbook."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
FINOPS = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops"
GATEWAY = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/common/providers/Microsoft.ApiManagement/service/gateway"
COMPONENT = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/apps/providers/Microsoft.Insights/components/app"


def load_helper():
    spec = importlib.util.spec_from_file_location("ai_gateway_finops", FINOPS / "ai_gateway_finops.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config():
    return {
        "applications": [{
            "gatewayResourceId": GATEWAY, "apimSubscriptionId": "consumer-17",
            "applicationId": "app-17", "teamId": "team-3",
        }],
        "trustedTelemetryResourceIds": [COMPONENT],
        "rates": [{
            "gatewayResourceId": GATEWAY, "backendHost": "example.openai.azure.com",
            "deployment": "deployment-a", "model": "model-version-a",
            "validFrom": "2026-01-01T00:00:00Z", "validTo": "2027-01-01T00:00:00Z",
            "currency": "USD", "meter": "openai-text-tokens", "billingMode": "consumption",
            "inputPerMillion": 2, "cachedInputPerMillion": 0.5, "outputPerMillion": 6,
        }],
    }


class FinOpsTests(unittest.TestCase):
    def setUp(self):
        self.module = load_helper()

    def event(self, **overrides):
        kwargs = dict(
            gateway_resource_id=GATEWAY, correlation_id="request-1",
            apim_subscription_id="consumer-17", backend_host="example.openai.azure.com",
            deployment="deployment-a", model="model-version-a", api_kind="chat",
            usage={"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
                   "prompt_tokens_details": {"cached_tokens": 400},
                   "completion_tokens_details": {"reasoning_tokens": 70}},
            completed=True, text_only=True, observed_at="2026-06-01T12:00:00Z",
        )
        kwargs.update(overrides)
        return self.module.make_usage_event(**kwargs)

    def payload(self, **overrides):
        return json.loads(self.event(**overrides)["properties"]["finops"])

    def test_static_workbook_is_current_and_has_no_resource_bindings(self):
        path = FINOPS / "ai-gateway-finops.workbook.json"
        workbook = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(workbook, self.module.build_workbook())
        self.assertEqual(workbook["version"], "Notebook/1.0")
        self.assertEqual(workbook["fallbackResourceIds"], ["Azure Monitor"])
        self.assertNotIn(GATEWAY, json.dumps(workbook))
        params = {p["name"]: p for item in workbook["items"] if item["type"] == 9
                  for p in item["content"]["parameters"]}
        self.assertEqual(params["Workspaces"]["type"], 5)
        self.assertTrue(params["Workspaces"]["multiSelect"])
        self.assertIn("microsoft.operationalinsights/workspaces",
                      params["Workspaces"]["typeSettings"]["resourceTypeFilter"])
        self.assertEqual(params["Workspaces"]["queryType"], 1)
        self.assertIn("Resources", params["Workspaces"]["query"])
        self.assertEqual(params["TimeRange"]["value"]["durationMs"], 604800000)
        self.assertTrue(params["Configuration"]["typeSettings"]["multiLineText"])
        self.assertEqual(json.loads(params["Configuration"]["value"])["rates"], [])
        groups = {v["value"] for v in json.loads(params["GroupBy"]["jsonData"])}
        self.assertEqual(groups, {"Application", "APIM subscription", "User", "Team", "Deployment", "Model", "Day"})
        queries = [item["content"] for item in workbook["items"] if item["type"] == 3]
        self.assertGreaterEqual(len(queries), 4)
        for content in queries:
            self.assertEqual(content["crossComponentResources"], ["{Workspaces}"])
            self.assertEqual(content["timeContextFromParameter"], "TimeRange")
            self.assertIn("base64_decode_tostring('{Configuration:base64}')", content["query"])
            self.assertNotIn("{Configuration}", content["query"])
            self.assertEqual(content["resourceType"], "microsoft.operationalinsights/workspaces")

    def test_queries_reduce_chunks_and_join_cardinality_before_pricing(self):
        query = (FINOPS / "ai-gateway-finops.kql").read_text(encoding="utf-8")
        for token in ("ApiManagementGatewayLlmLog", "ApiManagementGatewayLogs",
                      "AppEvents", "AppTraces", "datatable(",
                      "make_set_if", "NativeUsageVariants", "GatewayVariants",
                      "EventVariants", "RateMatches", "ApplicationMatches",
                      "leftouter", "fullouter", "real(null)",
                      "MissingCacheSplit", "UsageConflict", "TrustedSources"):
            self.assertIn(token, query)
        for forbidden in ("RequestMessages", "ResponseMessages", "RequestHeaders",
                          "ResponseHeaders", "CallerIpAddress", "best_effort", "customMetrics",
                          "sum(PromptTokens)", "sum(CompletionTokens)", "UserId"):
            self.assertNotIn(forbidden, query)
        self.assertIn("union isfuzzy=true", query)
        self.assertIn("CachedInputTokens", query)
        self.assertIn("InputTokens - CachedInputTokens", query)
        self.assertEqual(query.count("CorrelationId=tolower(CorrelationId)"), 2)
        self.assertIn("CorrelationId=tolower(tostring(E.correlation_id))", query)

    def test_gateway_correlation_ids_are_case_normalized(self):
        self.assertEqual(self.payload(correlation_id="AABBCCDD-0000-1111-2222-1234567890AB")["correlation_id"],
                         "aabbccdd-0000-1111-2222-1234567890ab")

    def test_cache_subset_and_reasoning_are_not_double_counted(self):
        payload = self.payload()
        self.assertEqual(payload["input_tokens"], 1000)
        self.assertEqual(payload["output_tokens"], 100)
        estimate = self.module.estimate_cost(payload, config())
        self.assertEqual(str(estimate["amount"]), "0.002")
        self.assertEqual(estimate["currency"], "USD")

    def test_responses_usage_supported(self):
        payload = self.payload(api_kind="responses", usage={
            "input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100,
            "input_tokens_details": {"cached_tokens": 400},
            "output_tokens_details": {"reasoning_tokens": 70},
        })
        self.assertEqual(self.module.estimate_cost(payload, config())["amount"],
                         self.module.estimate_cost(self.payload(), config())["amount"])

    def test_missing_cache_is_unknown_not_zero_unless_rates_identical(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}
        payload = self.payload(usage=usage)
        self.assertIsNone(payload["cached_input_tokens"])
        self.assertIsNone(self.module.estimate_cost(payload, config())["amount"])
        uniform = config()
        uniform["rates"][0]["cachedInputPerMillion"] = 2
        self.assertEqual(str(self.module.estimate_cost(payload, uniform)["amount"]), "0.0026")

    def test_partial_stream_does_not_become_zero(self):
        payload = self.payload(completed=False, usage=None)
        self.assertFalse(payload["usage_complete"])
        self.assertIsNone(payload["input_tokens"])
        self.assertIsNone(self.module.estimate_cost(payload, config())["amount"])

    def test_pool_backend_may_be_resolved_only_by_correlated_gateway_log(self):
        payload = self.payload(backend_host="")
        self.assertEqual(payload["backend_host"], "")
        self.assertIsNone(self.module.estimate_cost(payload, config())["amount"])

    def test_missing_rate_wrong_model_and_exclusive_valid_to(self):
        for payload, card in [
            (self.payload(), {"applications": [], "rates": [], "trustedTelemetryResourceIds": []}),
            (self.payload(model="model-other"), config()),
            (self.payload(observed_at="2027-01-01T00:00:00Z"), config()),
            (self.payload(backend_host="other.openai.azure.com"), config()),
        ]:
            self.assertIsNone(self.module.estimate_cost(payload, card)["amount"])

    def test_invalid_usage_and_nontext_are_never_priced(self):
        usages = [
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 11},
            {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
            {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
             "prompt_tokens_details": {"cached_tokens": 11}},
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
             "prompt_tokens_details": {"audio_tokens": 1}},
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
             "prompt_tokens_details": []},
        ]
        for usage in usages:
            with self.subTest(usage=usage):
                payload = self.payload(usage=usage)
                self.assertIsNone(self.module.estimate_cost(payload, config())["amount"])
        self.assertIsNone(self.module.estimate_cost(self.payload(text_only=False), config())["amount"])

    def test_metadata_only_pseudonymous_end_user_contract(self):
        event = self.event(authenticated_subject="tenant-1:opaque-object-1",
                           pseudonym_key=b"k" * 32, identity_validated=True,
                           validated_application_id="validated-app-1")
        payload = json.loads(event["properties"]["finops"])
        self.assertEqual(len(payload["user_id"]), 64)
        self.assertNotIn("tenant-1:opaque-object-1", json.dumps(event))
        self.assertNotIn("k" * 32, json.dumps(event))
        self.assertEqual(payload["validated_application_id"], "validated-app-1")
        self.assertEqual(payload["user_id"], self.payload(
            authenticated_subject="tenant-1:opaque-object-1", pseudonym_key=b"k" * 32,
            identity_validated=True, validated_application_id="validated-app-1")["user_id"])
        self.assertEqual(self.payload()["user_id"], "")
        with self.assertRaises(ValueError):
            self.event(authenticated_subject="caller-header", pseudonym_key=b"k" * 32)
        with self.assertRaises(ValueError):
            self.event(identity_validated=True, authenticated_subject="subject", pseudonym_key=b"short")

    def test_producer_does_not_emit_input_payload_or_unknown_keys(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
                 "messages": "PRIVATE PROMPT", "api_key": "SECRET"}
        serialized = json.dumps(self.event(usage=usage))
        self.assertNotIn("PRIVATE PROMPT", serialized)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("messages", serialized)

    def test_emit_uses_existing_logger_no_exporter_or_network_setup(self):
        class Logger:
            def info(self, message, *, extra):
                self.message, self.extra = message, extra
        logger = Logger()
        self.module.emit_usage_event(logger, self.event())
        self.assertEqual(logger.extra["microsoft.custom_event.name"], self.module.EVENT_NAME)
        self.assertIn("finops", logger.extra)

    def test_reject_ambiguous_mappings_overlapping_rates_and_ptu(self):
        for mutation in ("duplicate-map", "overlap", "ptu", "currency", "negative", "nan", "date"):
            card = config()
            if mutation == "duplicate-map":
                card["applications"].append(copy.deepcopy(card["applications"][0]))
            elif mutation == "overlap":
                card["rates"].append(copy.deepcopy(card["rates"][0]))
            elif mutation == "ptu":
                card["rates"][0]["billingMode"] = "PTU"
            elif mutation == "currency":
                card["rates"][0]["currency"] = "usd"
            elif mutation == "negative":
                card["rates"][0]["inputPerMillion"] = -1
            elif mutation == "nan":
                card["rates"][0]["inputPerMillion"] = float("nan")
            else:
                card["rates"][0]["validTo"] = card["rates"][0]["validFrom"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.module.validate_config(card)

    def test_nonoverlapping_rate_changes_and_multiple_currencies_supported(self):
        card = config()
        future = copy.deepcopy(card["rates"][0])
        future.update(validFrom="2027-01-01T00:00:00Z", validTo="2028-01-01T00:00:00Z", currency="EUR")
        card["rates"].append(future)
        self.module.validate_config(card)
        self.assertEqual(self.module.estimate_cost(
            self.payload(observed_at="2027-01-01T00:00:00Z"), card)["currency"], "EUR")
        query = (FINOPS / "ai-gateway-finops.kql").read_text(encoding="utf-8")
        self.assertIn("Currency", query)
        workbook = self.module.build_workbook(card)
        costs = next(i["content"]["query"] for i in workbook["items"] if i["name"] == "cost-by-currency")
        self.assertIn("by Currency", costs)

    def test_generated_configuration_is_not_interpolated_into_kql(self):
        card = config()
        card["applications"][0]["applicationId"] = "app'\\\n| union secrets //"
        workbook = self.module.build_workbook(card)
        for item in workbook["items"]:
            if item["type"] == 3:
                self.assertNotIn(card["applications"][0]["applicationId"], item["content"]["query"])

    def test_redeployment_preserves_saved_configuration_without_explicit_file(self):
        existing = self.module.build_workbook(config())
        parameters = {p["name"]: p for p in existing["items"][1]["content"]["parameters"]}
        parameters["GroupBy"]["value"] = "User"
        parameters["TimeRange"]["value"] = {"durationMs": 86400000}
        parameters["Workspaces"]["value"] = [
            "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/common/providers/Microsoft.OperationalInsights/workspaces/logs"
        ]
        rendered = self.module.render_workbook(existing_serialized_data=json.dumps(existing))
        self.assertEqual(rendered, existing)
        self.assertEqual(self.module.render_workbook(), self.module.build_workbook())

    def test_integration_keyword_aliases_accept_parsed_or_serialized_existing(self):
        existing = self.module.build_workbook(config())
        self.assertEqual(self.module.render_workbook(config=None, existing=existing), existing)
        self.assertEqual(self.module.render_workbook(config=None, existing=json.dumps(existing)), existing)
        self.assertEqual(self.module.render_workbook(config=self.module.EMPTY_CONFIG, existing=existing),
                         self.module.build_workbook())
        with self.assertRaises(ValueError):
            self.module.render_workbook(configuration=config(), config=config())
        with self.assertRaises(ValueError):
            self.module.render_workbook(existing=existing, existing_serialized_data=json.dumps(existing))

    def test_saved_resource_time_and_group_parameters_are_validated(self):
        for name, value in [
            ("Workspaces", ["' | union secret"]),
            ("Workspaces", COMPONENT),
            ("TimeRange", {"durationMs": -1}),
            ("TimeRange", {"startTime": "2026-06-02T00:00:00Z", "endTime": "2026-06-01T00:00:00Z"}),
            ("GroupBy", "injected group"),
        ]:
            existing = self.module.build_workbook(config())
            next(p for p in existing["items"][1]["content"]["parameters"]
                 if p["name"] == name)["value"] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.module.render_workbook(existing_serialized_data=json.dumps(existing))

    def test_explicit_config_is_authoritative_even_when_empty(self):
        existing = json.dumps(self.module.build_workbook(config()))
        rendered = self.module.render_workbook(
            configuration=self.module.EMPTY_CONFIG, existing_serialized_data=existing)
        self.assertEqual(rendered, self.module.build_workbook())
        self.assertEqual(self.module.render_workbook(
            configuration=config(), existing_serialized_data="malformed legacy content"),
            self.module.build_workbook(config()))

    def test_existing_missing_invalid_or_duplicate_configuration_fails_closed(self):
        existing = self.module.build_workbook(config())
        missing = copy.deepcopy(existing)
        missing["items"][1]["content"]["parameters"] = []
        duplicate = copy.deepcopy(existing)
        duplicate["items"].append(copy.deepcopy(duplicate["items"][1]))
        invalid = copy.deepcopy(existing)
        parameter = next(p for p in invalid["items"][1]["content"]["parameters"]
                         if p["name"] == "Configuration")
        parameter["value"] = '{"applications":[],"applications":[],"rates":[],"trustedTelemetryResourceIds":[]}'
        null_value = copy.deepcopy(existing)
        next(p for p in null_value["items"][1]["content"]["parameters"]
             if p["name"] == "Configuration")["value"] = "null"
        for content in ("", "not-json", "null", json.dumps(missing), json.dumps(duplicate),
                        json.dumps(invalid), json.dumps(null_value)):
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                self.module.render_workbook(existing_serialized_data=content)

    def test_load_config_rejects_duplicate_json_keys(self):
        with patch.object(Path, "read_text", return_value=json.dumps(config())) as read:
            self.assertEqual(self.module.load_config("reviewed.json"), self.module.validate_config(config()))
            read.assert_called_once_with(encoding="utf-8-sig")
        with patch.object(Path, "read_text", return_value='{"rates": [], "rates": []}'):
            with self.assertRaises(ValueError):
                self.module.load_config("duplicate.json")


if __name__ == "__main__":
    unittest.main()
