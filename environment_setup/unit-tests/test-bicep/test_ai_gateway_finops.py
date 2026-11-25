"""Credential-free contracts for the log-based AI gateway FinOps workbook."""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
FINOPS = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops"
GATEWAY = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/common/providers/Microsoft.ApiManagement/service/gateway"
COMPONENT = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/apps/providers/Microsoft.Insights/components/app"
FOUNDRY = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/ai/providers/Microsoft.CognitiveServices/accounts/foundry"
TENANT = "22222222-2222-2222-2222-222222222222"
OBJECT = "33333333-3333-3333-3333-333333333333"


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
        self.assertIn("microsoft.operationalinsights/workspaces", params["Workspaces"]["query"])
        self.assertEqual(params["Workspaces"]["queryType"], 1)
        self.assertIn("Resources", params["Workspaces"]["query"])
        self.assertEqual(params["TimeRange"]["value"]["durationMs"], 2592000000)
        self.assertTrue(params["Configuration"]["typeSettings"]["multiLineText"])
        self.assertEqual(json.loads(params["Configuration"]["value"])["rates"], [])
        groups = {v["value"] for v in json.loads(params["GroupBy"]["jsonData"])}
        self.assertEqual(groups, {"Application", "APIM subscription", "User", "Team", "Deployment", "Model", "Day"})
        queries = [item["content"] for item in workbook["items"]
                   if item["type"] == 3 and item["content"].get("queryType") == 0]
        self.assertGreaterEqual(len(queries), 4)
        for content in queries:
            self.assertEqual(content["crossComponentResources"], ["{Workspaces}"])
            self.assertEqual(content["timeContextFromParameter"], "TimeRange")
            self.assertIn("base64_decode_tostring('{Configuration:base64}')", content["query"])
            self.assertNotIn("{Configuration}", content["query"])
            self.assertEqual(content["resourceType"], "microsoft.operationalinsights/workspaces")

    def test_generated_workbook_includes_independent_live_billing_drilldown(self):
        workbook = self.module.build_workbook()
        parameters = {p["name"]: p for p in workbook["items"][1]["content"]["parameters"]}
        self.assertIn("BillingSubscription", parameters)
        self.assertIn("BillingResource", parameters)
        billing = next(item for item in workbook["items"] if item["name"] == "billing-deployments")
        self.assertEqual(billing["content"]["queryType"], 12)
        endpoint = json.loads(billing["content"]["query"])
        self.assertEqual(endpoint["method"], "POST")
        self.assertEqual(json.loads(endpoint["data"])["type"], "ActualCost")
        self.assertNotIn("{Workspaces}", json.dumps(billing))
        names = [item["name"] for item in workbook["items"]]
        self.assertLess(names.index("billing-heading"), names.index("requester-totals"))

    def test_query_resource_pickers_follow_native_serialized_contract(self):
        parameters = self.module.build_workbook()["items"][1]["content"]["parameters"]
        for parameter in parameters:
            self.assertEqual(parameter["version"], "KqlParameterItem/1.0")
            if parameter["type"] == 5:
                self.assertNotIn("resourceTypeFilter", parameter["typeSettings"])

    def test_billing_selection_is_preserved_and_validated(self):
        workbook = self.module.build_workbook()
        parameters = {p["name"]: p for p in workbook["items"][1]["content"]["parameters"]}
        subscription = "11111111-1111-1111-1111-111111111111"
        resource = f"/subscriptions/{subscription}/resourceGroups/apps/providers/Microsoft.CognitiveServices/accounts/foundry"
        parameters["BillingSubscription"]["value"] = subscription
        parameters["BillingResource"]["value"] = resource
        rendered = self.module.render_workbook(existing=workbook)
        saved = {p["name"]: p for p in rendered["items"][1]["content"]["parameters"]}
        self.assertEqual(saved["BillingSubscription"]["value"], subscription)
        self.assertEqual(saved["BillingResource"]["value"], resource)
        for name in ("BillingSubscription", "BillingResource"):
            bad = copy.deepcopy(workbook)
            next(p for p in bad["items"][1]["content"]["parameters"] if p["name"] == name)["value"] = "'bad\""
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.module.render_workbook(existing=bad)

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

    def test_workspace_resource_graph_picker_has_independent_subscription_scope(self):
        workbook = self.module.build_workbook()
        workspace = next(p for p in workbook["items"][1]["content"]["parameters"] if p["name"] == "Workspaces")
        self.assertEqual(workspace["queryType"], 1)
        self.assertEqual(workspace["crossComponentResources"], ["value::all"])
        self.assertNotIn("{Workspaces}", workspace["crossComponentResources"])
        selected = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/common/providers/Microsoft.OperationalInsights/workspaces/logs"
        workspace["value"] = [selected]
        rendered = self.module.render_workbook(existing=workbook)
        restored = next(p for p in rendered["items"][1]["content"]["parameters"] if p["name"] == "Workspaces")
        self.assertEqual(restored["value"], [selected])
        self.assertEqual(restored["crossComponentResources"], ["value::all"])
        for item in rendered["items"]:
            if item["type"] == 3 and item["content"].get("queryType") == 0:
                self.assertEqual(item["content"]["crossComponentResources"], ["{Workspaces}"])
                self.assertIn("noDataMessage", item["content"])

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

    def test_fractional_rates_accept_kusto_dynamic_double_type(self):
        query = (FINOPS / "ai-gateway-finops.kql").read_text(encoding="utf-8")
        for field in ("inputPerMillion", "cachedInputPerMillion", "outputPerMillion"):
            self.assertIn(f"gettype(R.{field}) in ('long', 'double')", query)

    def test_separate_cost_categories_add_to_subtotal_without_reasoning_double_count(self):
        estimate = self.module.estimate_cost(self.payload(), config())
        self.assertEqual(estimate["input_cost"], Decimal("0.0012"))
        self.assertEqual(estimate["cached_input_cost"], Decimal("0.0002"))
        self.assertEqual(estimate["output_cost"], Decimal("0.0006"))
        self.assertEqual(estimate["combined_input_cost"], Decimal("0.0014"))
        self.assertEqual(sum(estimate[key] for key in ("input_cost", "cached_input_cost", "output_cost")),
                         estimate["amount"])

    def test_equal_rates_allow_subtotal_but_never_invent_cache_categories(self):
        card = config()
        card["rates"][0]["cachedInputPerMillion"] = 2
        estimate = self.module.estimate_cost(self.payload(usage={
            "prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}), card)
        self.assertEqual(estimate["amount"], Decimal("0.0026"))
        self.assertEqual(estimate["combined_input_cost"], Decimal("0.002"))
        self.assertIsNone(estimate["input_cost"])
        self.assertIsNone(estimate["cached_input_cost"])
        self.assertEqual(estimate["category_coverage"], "Unknown cache split")

    def test_entra_identity_is_explicit_validated_tid_oid_kind_not_email(self):
        payload = self.payload(entra_tenant_id=TENANT, entra_object_id=OBJECT,
                               requester_kind="user", identity_validated=True)
        identity = self.module.requester_identity(payload)
        self.assertEqual(identity["kind"], "user")
        self.assertIn(TENANT, identity["key"])
        self.assertIn(OBJECT, identity["key"])
        self.assertEqual(payload["user_id"], "")
        for overrides in (
            {"entra_tenant_id": TENANT},
            {"entra_object_id": OBJECT},
            {"entra_tenant_id": TENANT, "entra_object_id": OBJECT},
            {"entra_tenant_id": TENANT, "entra_object_id": OBJECT, "requester_kind": "user"},
            {"entra_tenant_id": "someone@example.com", "entra_object_id": OBJECT,
             "requester_kind": "user", "identity_validated": True},
            {"entra_tenant_id": TENANT, "entra_object_id": OBJECT,
             "requester_kind": "managed-identity-owner", "identity_validated": True},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.event(**overrides)

    def test_entra_namespace_separates_tenant_and_principal_kind(self):
        base = dict(entra_tenant_id=TENANT, entra_object_id=OBJECT,
                    requester_kind="user", identity_validated=True)
        first = self.module.requester_identity(self.payload(**base))
        service = self.module.requester_identity(self.payload(**{**base, "requester_kind": "serviceprincipal"}))
        tenant = self.module.requester_identity(self.payload(**{**base, "entra_tenant_id": OBJECT}))
        self.assertEqual(len({first["key"], service["key"], tenant["key"]}), 3)
        for broken in ({"identity_validated": False}, {"entra_object_id": ""}, {"requester_kind": ""}):
            payload = {**self.payload(**base), **broken}
            self.assertEqual(self.module.requester_identity(payload)["kind"], "unknown")

    def test_pseudonyms_remain_gateway_scoped_and_v1_payloads_work(self):
        kwargs = dict(authenticated_subject="private subject", pseudonym_key=b"k" * 32,
                      identity_validated=True)
        first = self.payload(**kwargs)
        second = self.payload(**kwargs, gateway_resource_id=GATEWAY + "-two")
        self.assertNotEqual(first["user_id"], second["user_id"])
        second["user_id"] = first["user_id"]
        self.assertNotEqual(self.module.requester_identity(first)["key"],
                            self.module.requester_identity(second)["key"])
        legacy = {key: value for key, value in first.items()
                  if key not in {"identity_validated", "requester_kind", "entra_tenant_id", "entra_object_id",
                                 "foundry_resource_id", "target_validated"}}
        self.assertEqual(self.module.requester_identity(legacy)["key"],
                         self.module.requester_identity(first)["key"])
        self.assertEqual(self.module.estimate_cost(legacy, config())["amount"], Decimal("0.002"))

    def test_foundry_target_requires_trusted_producer_or_reviewed_exact_mapping(self):
        unknown = self.module.estimate_cost(self.payload(), config())
        self.assertEqual(unknown["foundry_resource_id"], "Unknown")
        with self.assertRaises(ValueError):
            self.event(foundry_resource_id=FOUNDRY)
        with self.assertRaises(ValueError):
            self.event(foundry_resource_id=GATEWAY, target_validated=True)
        direct_target = self.payload(foundry_resource_id=FOUNDRY, target_validated=True)
        self.assertEqual(self.module.estimate_cost(direct_target, config())["foundry_resource_id"], FOUNDRY.lower())
        card = config()
        card["rates"][0]["foundryResourceId"] = FOUNDRY
        self.assertEqual(self.module.estimate_cost(self.payload(), card)["foundry_resource_id"], FOUNDRY.lower())
        conflict = self.module.estimate_cost(
            self.payload(foundry_resource_id=FOUNDRY + "-other", target_validated=True), card)
        self.assertIsNone(conflict["amount"])
        self.assertEqual(conflict["foundry_resource_id"], "Unknown")

    def test_direct_foundry_usage_is_not_disguised_as_apim(self):
        payload = self.payload(gateway_resource_id=None, apim_subscription_id="",
                               foundry_resource_id=FOUNDRY, target_validated=True)
        self.assertEqual(payload["gateway_resource_id"], "")
        card = config()
        card["rates"][0].pop("gatewayResourceId")
        card["rates"][0]["foundryResourceId"] = FOUNDRY
        self.assertEqual(self.module.estimate_cost(payload, card)["amount"], Decimal("0.002"))
        self.assertIsNone(self.module.estimate_cost(self.payload(), card)["amount"])
        with self.assertRaises(ValueError):
            self.event(gateway_resource_id=None)
        with self.assertRaises(ValueError):
            self.event(gateway_resource_id=None, foundry_resource_id=FOUNDRY,
                       target_validated=True, apim_subscription_id="not-an-apim-call")
        for invalid_gateway in (False, 0, []):
            with self.subTest(gateway=invalid_gateway), self.assertRaises(ValueError):
                self.event(gateway_resource_id=invalid_gateway, foundry_resource_id=FOUNDRY,
                           target_validated=True, apim_subscription_id="")

    def test_new_rate_contract_is_optional_and_validated(self):
        original = config()
        self.assertEqual(set(self.module.validate_config(original)["rates"][0]), set(original["rates"][0]))
        for change in ({"foundryResourceId": GATEWAY}, {"gatewayResourceId": ""},
                       {"foundryResourceId": FOUNDRY, "unreviewed": True}):
            card = config()
            card["rates"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.validate_config(card)
        card = config()
        card["rates"][0]["foundryResourceId"] = FOUNDRY
        second = copy.deepcopy(card["rates"][0])
        second["foundryResourceId"] = FOUNDRY + "-other"
        card["rates"].append(second)
        with self.assertRaises(ValueError):
            self.module.validate_config(card)

    def test_scoped_pseudonyms_never_become_cross_gateway_totals(self):
        card = config()
        second_rate = copy.deepcopy(card["rates"][0])
        second_rate["gatewayResourceId"] = GATEWAY + "-two"
        card["rates"].append(second_rate)
        first = self.payload(authenticated_subject="private subject", pseudonym_key=b"k" * 32,
                             identity_validated=True)
        second = {**first, "gateway_resource_id": (GATEWAY + "-two").lower()}
        totals = self.module.summarize_requesters([first, second], card)["totals"]
        self.assertEqual(len(totals), 2)
        self.assertTrue(all(row["Requests"] == 1 for row in totals))
        self.assertEqual(len({row["RequesterKey"] for row in totals}), 2)

    def test_hierarchy_identifiers_roundtrip_scopes_and_delimiters(self):
        card = config()
        card["rates"][0]["deployment"] = "name|with:delimiters,\"and quotes\""
        payload = self.payload(deployment=card["rates"][0]["deployment"])
        tree = self.module.summarize_requesters([payload], card)["tree"]
        self.assertEqual(len(tree), 4)
        for row in tree:
            parts = json.loads(row["Id"])
            if row["ParentId"]:
                self.assertEqual(json.loads(row["ParentId"]), parts[:-1])
        self.assertEqual(next(row["Name"] for row in tree if row["Kind"] == "Deployment"),
                         card["rates"][0]["deployment"])

    def test_requester_hierarchy_deduplicates_and_rolls_up_leaves_once(self):
        card = config()
        card["rates"][0]["foundryResourceId"] = FOUNDRY
        second_rate = copy.deepcopy(card["rates"][0])
        second_rate.update(gatewayResourceId=GATEWAY + "-two", foundryResourceId=FOUNDRY + "-two")
        card["rates"].append(second_rate)
        identity = dict(entra_tenant_id=TENANT, entra_object_id=OBJECT,
                        requester_kind="user", identity_validated=True)
        first = self.payload(**identity)
        second = self.payload(**identity, gateway_resource_id=GATEWAY + "-two",
                              observed_at="2026-06-02T12:00:00Z")
        summary = self.module.summarize_requesters([first, copy.deepcopy(first), second], card)
        self.assertEqual(len(summary["totals"]), 1)
        self.assertEqual(summary["totals"][0]["Requests"], 2)
        self.assertEqual(summary["totals"][0]["EstimatedSubtotal"], Decimal("0.004"))
        self.assertEqual(len(summary["daily"]), 2)
        tree = summary["tree"]
        self.assertEqual(len(tree), 7)
        self.assertEqual(len({row["Id"] for row in tree}), len(tree))
        self.assertEqual(sum(row["EstimatedSubtotal"] for row in tree if row["Kind"] == "Day"),
                         summary["totals"][0]["EstimatedSubtotal"])
        for parent in (row for row in tree if row["Kind"] != "Day"):
            children = [row for row in tree if row["ParentId"] == parent["Id"]]
            self.assertEqual(sum(row["EstimatedSubtotal"] for row in children), parent["EstimatedSubtotal"])

    def test_requester_summary_keeps_currencies_unknowns_and_missing_categories(self):
        card = config()
        card["rates"][0]["cachedInputPerMillion"] = 2
        second = copy.deepcopy(card["rates"][0])
        second.update(gatewayResourceId=GATEWAY + "-two", currency="EUR")
        card["rates"].append(second)
        identity = dict(entra_tenant_id=TENANT, entra_object_id=OBJECT,
                        requester_kind="user", identity_validated=True)
        rows = [self.payload(**identity),
                self.payload(**identity, correlation_id="request-2", usage={
                    "prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}),
                self.payload(**identity, gateway_resource_id=GATEWAY + "-two"),
                self.payload(**identity, correlation_id="request-3", model="not-reviewed")]
        summary = self.module.summarize_requesters(rows, card)
        self.assertEqual({row["Currency"] for row in summary["totals"]}, {"USD", "EUR", "Unpriced"})
        usd = next(row for row in summary["totals"] if row["Currency"] == "USD")
        self.assertEqual(usd["EstimatedSubtotal"], Decimal("0.0052"))
        self.assertIsNone(usd["InputCost"])
        self.assertIsNone(usd["CachedInputCost"])
        self.assertEqual(usd["UnknownCategoryRequests"], 1)
        self.assertEqual(sum(row["UnpricedRequests"] for row in summary["totals"]), 1)
        self.assertTrue(all(row["FoundryResourceId"] == "Unknown" for row in summary["daily"]))

    def test_conflicting_copies_are_not_arbitrarily_assigned_or_charged(self):
        first = self.payload()
        conflicting = {**first, "user_id": "b" * 64}
        summary = self.module.summarize_requesters([first, conflicting], config())
        self.assertEqual(len(summary["totals"]), 1)
        self.assertEqual(summary["totals"][0]["RequesterKind"], "unknown")
        self.assertEqual(summary["totals"][0]["Requests"], 1)
        self.assertEqual(summary["totals"][0]["UnpricedRequests"], 1)
        self.assertIsNone(summary["totals"][0]["EstimatedSubtotal"])

    def test_requester_workbook_has_native_tree_and_explicit_no_data_coverage(self):
        workbook = self.module.build_workbook()
        sections = {item["name"]: item["content"] for item in workbook["items"]}
        for name in ("requester-coverage", "requester-totals", "requester-daily",
                     "requester-daily-trend", "requester-hierarchy"):
            self.assertIn(name, sections)
        tree = sections["requester-hierarchy"]
        self.assertEqual(tree["visualization"], "table")
        self.assertEqual(tree["gridSettings"]["hierarchySettings"], {
            "treeType": 0, "idColumn": "Id", "parentColumn": "ParentId",
            "expanderColumn": "Name", "expandTopLevel": True})
        for column in ("InputCost", "OutputCost", "CachedInputCost", "EstimatedSubtotal", "UnpricedRequests"):
            self.assertIn(column, tree["query"])
        self.assertIn("pack_array", tree["query"])
        self.assertIn("NO TRUSTED REQUESTER DATA", sections["requester-coverage"]["query"])
        self.assertIn("not an invoice", sections["overview"]["json"])

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
