"""Offline contracts for live, workspace-independent Cost Management workbook queries."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/foundry_billing.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("foundry_billing", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flatten(items):
    for item in items:
        yield item
        if item["type"] == 12:
            yield from flatten(item["content"]["items"])


class FoundryBillingTests(unittest.TestCase):
    def setUp(self):
        self.module = load_helper()
        self.parameters = self.module.billing_parameters()
        self.items = list(flatten(self.module.billing_items()))
        self.by_name = {item["name"]: item for item in self.items}
        self.arm = [item for item in self.items
                    if item["type"] == 3 and item["content"].get("queryType") == 12]

    def endpoint(self, name):
        return json.loads(self.by_name[name]["content"]["query"])

    def body(self, name):
        return json.loads(self.endpoint(name)["data"])

    def test_builders_are_deterministic_and_return_independent_values(self):
        original = json.dumps([self.parameters, self.module.billing_items()], sort_keys=True)
        self.parameters[0]["name"] = "modified"
        self.items[0]["content"]["json"] = "modified"
        self.assertEqual(original, json.dumps(
            [self.module.billing_parameters(), self.module.billing_items()], sort_keys=True))

    def test_billing_requires_no_workspace_configuration_rates_or_fixed_scope(self):
        serialized = json.dumps([self.parameters, self.items])
        for forbidden in ("{Workspaces", "{Configuration", "AppEvents", "EstimatedCost",
                          "f0fe8b33-", "aif2blts", "api_key", "Authorization"):
            self.assertNotIn(forbidden, serialized)
        params = {p["name"]: p for p in self.parameters}
        self.assertEqual(params["BillingSubscription"]["type"], 6)
        self.assertFalse(params["BillingSubscription"]["multiSelect"])
        self.assertNotIn("queryType", params["BillingSubscription"])
        self.assertEqual(params["BillingSubscription"]["defaultValue"], "value::1")
        account = params["BillingResource"]
        self.assertEqual(account["type"], 5)
        self.assertFalse(account["multiSelect"])
        self.assertEqual(account["queryType"], 1)
        self.assertEqual(account["crossComponentResources"], ["{BillingSubscription}"])
        self.assertIn("AIServices", account["query"])
        self.assertIn("OpenAI", account["query"])
        for parameter in self.parameters:
            if parameter.get("queryType") == 1:
                self.assertTrue(parameter.get("crossComponentResources"),
                                "Resource Graph pickers require an explicit subscription scope")

    def test_queries_are_live_synchronous_arm_post_with_custom_shared_time(self):
        self.assertGreaterEqual(len(self.arm), 8)
        for item in self.arm:
            with self.subTest(item=item["name"]):
                endpoint = json.loads(item["content"]["query"])
                self.assertEqual(endpoint["version"], "ARMEndpoint/1.0")
                self.assertEqual(endpoint["method"], "POST")
                self.assertTrue(endpoint["path"].endswith("/providers/Microsoft.CostManagement/query"))
                self.assertEqual(endpoint["headers"], [])
                self.assertEqual(endpoint["urlParams"],
                                 [{"key": "api-version", "value": "2025-03-01"}])
                body = json.loads(endpoint["data"])
                self.assertEqual(body["type"], "ActualCost")
                self.assertEqual(body["timeframe"], "Custom")
                self.assertEqual(body["timePeriod"],
                                 {"from": "{TimeRange:startISO}", "to": "{TimeRange:endISO}"})
                self.assertEqual(body["dataset"]["aggregation"],
                                 {"totalCost": {"name": "Cost", "function": "Sum"}})
                self.assertLessEqual(len(body["dataset"].get("grouping", [])), 2)

    def test_resource_overview_and_drills_have_explicit_correct_scope(self):
        overview = self.body("billing-resources")
        self.assertEqual(overview["dataset"]["grouping"],
                         [{"type": "Dimension", "name": "ResourceId"}])
        self.assertEqual(overview["dataset"]["filter"]["dimensions"]["name"], "ResourceType")
        self.assertIn("{BillingSubscription}", self.endpoint("billing-resources")["path"])
        for name in ("billing-resource-meters", "billing-deployments",
                     "billing-deployment-daily", "billing-all-deployments-daily"):
            with self.subTest(item=name):
                endpoint = self.endpoint(name)
                self.assertIn("{BillingResource:subscription}", endpoint["path"])
                body = json.loads(endpoint["data"])
                self.assertIn('"ResourceId"', json.dumps(body))
                self.assertIn("{BillingResource:escapejson}", json.dumps(body))

    def test_real_deployment_tag_drills_not_meter_or_model_name_inference(self):
        summary = self.body("billing-deployments")["dataset"]
        self.assertEqual(summary["grouping"], [{"type": "TagKey", "name": "deployment"}])
        selected = self.body("billing-deployment-daily")["dataset"]
        self.assertEqual(selected["granularity"], "Daily")
        self.assertIn({"tags": {"name": "deployment", "operator": "In",
                               "values": ["{BillingDeployment:escapejson}"]}},
                      selected["filter"]["and"])
        self.assertEqual(selected["grouping"], [{"type": "Dimension", "name": "Meter"}])
        all_rows = self.body("billing-all-deployments-daily")["dataset"]
        self.assertEqual(all_rows["grouping"], [
            {"type": "TagKey", "name": "deployment"}, {"type": "Dimension", "name": "Meter"}])
        self.assertEqual(all_rows["granularity"], "Daily")
        self.assertNotIn("tags", all_rows["filter"])
        exports = self.by_name["billing-deployments"]["content"]["exportedParameters"]
        self.assertEqual({e["parameterName"]: e["fieldName"] for e in exports},
                         {"BillingDeployment": "DeploymentTag", "BillingCurrency": "Currency"})

    def test_every_post_has_always_visible_pagination_and_column_contract(self):
        for item in self.arm:
            if item["name"].endswith("-status"):
                continue
            with self.subTest(item=item["name"]):
                status = self.by_name[item["name"] + "-status"]
                data = self.endpoint(item["name"])
                metadata = self.endpoint(status["name"])
                self.assertEqual(data["path"], metadata["path"])
                self.assertEqual(data["data"], metadata["data"])
                settings = metadata["transformers"][0]["settings"]
                self.assertEqual(settings["tablePath"], "$.properties")
                paths = {c["columnid"]: c["path"] for c in settings["columns"]}
                self.assertEqual(paths["NextPage"], "$.nextLink")
                self.assertEqual(paths["ReturnedColumns"], "$.columns")
                self.assertIn("expected", status["content"]["title"])
                self.assertEqual(item.get("conditionalVisibility"), status.get("conditionalVisibility"))
        notices = " ".join(i["content"].get("json", "") for i in self.items)
        for text in ("INCOMPLETE", "nextLink", "POST", "not an invoice", "Unattributed",
                     "input", "output", "cached", "negative", "Cost Analysis"):
            self.assertIn(text, notices)

    def test_raw_meters_unknowns_credits_and_currencies_are_not_dropped(self):
        for name in ("billing-resource-meters", "billing-all-deployments-daily",
                     "billing-deployment-daily"):
            settings = self.endpoint(name)["transformers"][0]["settings"]
            self.assertEqual(settings["tablePath"], "$.properties.rows")
            columns = {c["columnid"]: c for c in settings["columns"]}
            self.assertIn("Currency", columns)
            self.assertIn("Meter", columns)
            self.assertNotIn("substringRegexMatch", columns["Meter"])
            self.assertNotIn("columnType", columns["Cost"])
            self.assertEqual(columns["UsageDate"]["columnType"], "datetime")
            self.assertEqual(columns["UsageDate"]["substringReplace"], "$1-$2-$3")
        daily = self.endpoint("billing-all-deployments-daily")["transformers"][0]["settings"]
        columns = {c["columnid"]: c["path"] for c in daily["columns"]}
        self.assertEqual(columns, {"Cost": "$[0]", "UsageDate": "$[1]",
                                  "TagKey": "$[2]", "DeploymentTag": "$[3]",
                                  "Meter": "$[4]", "Currency": "$[5]"})
        fallback = self.body("billing-resource-meters")
        self.assertNotIn("TagKey", json.dumps(fallback))
        self.assertNotIn("tags", json.dumps(fallback))

    def test_selected_chart_is_currency_filtered_and_same_daily_scope(self):
        chart = self.by_name["billing-deployment-trend"]["content"]
        self.assertEqual(chart["queryType"], 12)
        endpoint = self.endpoint("billing-deployment-trend")
        self.assertEqual(endpoint["data"], self.endpoint("billing-deployment-daily")["data"])
        self.assertEqual(endpoint["transformers"][0]["settings"]["tablePath"],
                         '$.properties.rows[?(@[3] == "{BillingCurrency:escapejson}")]')
        self.assertIn("BillingCurrency", chart["query"])
        self.assertEqual(chart["chartSettings"]["group"], "Meter")
        self.assertEqual(chart["chartSettings"]["yAxis"], ["Cost"])
        self.assertNotEqual(chart["visualization"], "piechart")

    def test_tag_grouping_maps_tag_value_not_the_constant_tag_key_to_deployment(self):
        response = {
            "columns": [{"name": "Cost", "type": "Number"},
                        {"name": "TagKey", "type": "String"},
                        {"name": "TagValue", "type": "String"},
                        {"name": "Currency", "type": "String"}],
            "rows": [[1.25, "deployment", "model-deploy-a", "EUR"],
                     [-0.5, "deployment", None, "USD"]],
        }
        settings = self.endpoint("billing-deployments")["transformers"][0]["settings"]
        rows = [{c["columnid"]: row[int(c["path"][2:-1])] for c in settings["columns"]}
                for row in response["rows"]]
        self.assertEqual(rows[0]["DeploymentTag"], "model-deploy-a")
        self.assertEqual(rows[0]["Currency"], "EUR")
        self.assertIsNone(rows[1]["DeploymentTag"])
        self.assertEqual(rows[1]["Cost"], -0.5)
        self.assertIn("Cost, TagKey, TagValue, Currency",
                      self.by_name["billing-deployments-status"]["content"]["title"])

    def test_live_daily_column_order_keeps_cache_read_write_and_untagged_meters(self):
        # Column order and meter labels observed live on 2026-11-25; amounts are synthetic.
        meters = [
            "6.1-sol ShortCo Cd Inp Std DZ 1M Tokens",
            "6.1-sol ShortCo Cd Wr Std DZ 1M Tokens",
            "6.1-sol ShortCo Inp Std DZ 1M Tokens",
            "6.1-sol ShortCo Opt Std DZ 1M Tokens",
            "Hosted Memory Usage", "Hosted vCPU Usage", "Voice Live audio input",
        ]
        response = {
            "columns": [{"name": name, "type": kind} for name, kind in [
                ("Cost", "Number"), ("UsageDate", "Number"), ("TagKey", "String"),
                ("TagValue", "String"), ("Meter", "String"), ("Currency", "String")]],
            "rows": [[0.125 if i != 4 else -0.5, 20261124, "deployment",
                      "model-deploy-a" if i < 4 else None, meter, "EUR"]
                     for i, meter in enumerate(meters)],
            "nextLink": None,
        }
        settings = self.endpoint("billing-all-deployments-daily")["transformers"][0]["settings"]
        rows = [{c["columnid"]: row[int(c["path"][2:-1])] for c in settings["columns"]}
                for row in response["rows"]]
        self.assertEqual([row["Meter"] for row in rows], meters)
        self.assertEqual([row["DeploymentTag"] for row in rows],
                         ["model-deploy-a"] * 4 + [None] * 3)
        self.assertTrue(all(row["Currency"] == "EUR" for row in rows))
        self.assertEqual(rows[4]["Cost"], -0.5)
        self.assertIn("Cost, UsageDate, TagKey, TagValue, Meter, Currency",
                      self.by_name["billing-all-deployments-daily-status"]["content"]["title"])
        note = self.by_name["billing-meter-note"]["content"]["json"]
        self.assertIn("cache-read", note)
        self.assertIn("cache-write", note)

    def test_json_substitution_cannot_escape_selected_resource_or_tag(self):
        # ARMEndpoint.data is itself serialized JSON; substitute after decoding the envelope.
        data = self.endpoint("billing-deployment-daily")["data"]
        value = 'a"b\\c\n"}, "dimensions": {"name": "ResourceType"}'
        escaped = json.dumps(value)[1:-1]
        data = data.replace("{BillingDeployment:escapejson}", escaped)
        data = data.replace("{BillingResource:escapejson}", escaped)
        body = json.loads(data)
        self.assertEqual(body["dataset"]["filter"]["and"][1]["tags"]["values"], [value])
        self.assertEqual(body["dataset"]["filter"]["and"][0]["dimensions"]["values"], [value])


if __name__ == "__main__":
    unittest.main()
