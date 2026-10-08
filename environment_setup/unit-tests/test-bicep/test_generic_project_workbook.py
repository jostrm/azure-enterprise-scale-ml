"""Offline compiled contracts for the output-only native project workbook items.

These tests inspect emitted ARM, not live billing, metric availability or Portal
rendering. The shared workbook evaluator deliberately implements only ARM.
"""
from __future__ import annotations

import json
import re

import pytest

from test_my_project_workbook import Arm, BICEP, COMPONENT, RG, compile_bicep


MODULE = BICEP / "modules" / "genericProjectWorkbookItems.bicep"
DAY_MS = 24 * 60 * 60 * 1000


def flatten(items):
    for item in items:
        yield item
        if item["type"] == 12:
            yield from flatten(item["content"]["items"])


@pytest.fixture(scope="module")
def compiled_generic():
    return compile_bicep(MODULE)


def materialize(template, resource_group=RG, component=COMPONENT):
    evaluator = Arm(template, {
        "projectResourceGroupId": resource_group,
        "applicationInsightsResourceId": component,
        "projectNumber": "001",
    })
    return evaluator.value(template["outputs"]["items"]["value"])


@pytest.fixture(scope="module")
def items(compiled_generic):
    return {item["name"]: item for item in materialize(compiled_generic)}


def test_module_is_output_only_with_explicit_public_inputs(compiled_generic):
    assert compiled_generic.get("resources", []) == []
    assert set(compiled_generic["parameters"]) == {
        "projectResourceGroupId", "applicationInsightsResourceId", "projectNumber", "env",
    }
    assert compiled_generic["parameters"]["env"]["defaultValue"] == ""
    assert set(compiled_generic["outputs"]) == {"items"}
    assert compiled_generic["outputs"]["items"]["type"] == "array"


def test_every_item_is_namespaced_and_navigation_scoped(items, compiled_generic):
    assert len(items) == len(materialize(compiled_generic))
    assert items
    for name, item in items.items():
        assert name.startswith("generic-")
        assert item["conditionalVisibility"] == {
            "parameterName": "Navigation",
            "comparison": "isEqualTo",
            "value": "cost" if name.startswith("generic-cost-") else "usage",
        }


def test_generic_data_sources_do_not_require_business_events_or_configuration(items):
    payload = json.dumps(items)
    for forbidden in (
        "AppEvents", "aifactory.chat", "aifactory.chat.meter", "QuestionsComplete",
        "BookingsComplete", "Coverage", "FactoryId", "ScaleSetId",
        "{Template", "{TimeZone", "{StartDate", "{EndDate", "{ChartCurrency",
        "Microsoft.Insights/diagnosticSettings", "Microsoft.Authorization/roleAssignments",
        "listKeys(", "apiKey", "connectionString",
    ):
        assert forbidden not in payload


def test_native_model_tokens_are_independent_of_application_telemetry(items):
    names = list(items)
    assert names.index("generic-native-tokens") < names.index("generic-http-optional")
    selectors = items["generic-native-selectors"]["content"]["parameters"]
    account = next(parameter for parameter in selectors if parameter["name"] == "GenericAccount")
    assert account["type"] == 2
    assert account["queryType"] == 1
    assert account["crossComponentResources"] == [RG]
    assert account["multiSelect"] is False
    assert account["value"] == ""
    assert f"startswith '{RG.lower()}/providers/microsoft.cognitiveservices/accounts/'" in account["query"]
    assert "array_length(split(id, '/')) == 9" in account["query"]
    assert "array_length(Accounts) == 1" in account["query"]
    assert "Select one discovered account" in account["query"]
    validated = next(parameter for parameter in selectors if parameter["name"] == "GenericMetricAccount")
    assert validated["type"] == 1
    assert validated["queryType"] == 1
    assert validated["crossComponentResources"] == [RG]
    assert validated["isHiddenWhenLocked"] is True
    assert validated["value"] == ""
    assert f"startswith '{RG.lower()}/providers/microsoft.cognitiveservices/accounts/'" in validated["query"]
    assert 'id =~ "{GenericAccount:escapejson}"' in validated["query"]
    assert "{GenericAccount}" not in validated["query"]
    assert "array_length(Selected) == 1" in validated["query"]
    assert "tostring(Selected[0]), '')" in validated["query"]
    profile = next(parameter for parameter in selectors if parameter["name"] == "GenericMetricProfile")
    assert profile["value"] == "foundry"
    assert {option["value"] for option in json.loads(profile["jsonData"])} == {"foundry", "openai"}
    groups = items["generic-native-tokens"]["content"]["items"]
    detail_items = items["generic-native-details"]["content"]["items"]
    assert len(groups) == 2
    for group in groups:
        assert group["conditionalVisibility"]["parameterName"] == "GenericMetricProfile"
        family = group["conditionalVisibility"]["value"]
        metrics = [
            child["content"] for child in flatten(group["content"]["items"])
            if child["type"] == 10
        ]
        metrics.append(next(
            item["content"] for item in detail_items
            if item["conditionalVisibility"]["value"] == family
        ))
        assert {content["chartType"] for content in metrics} == {0, 3}
        for content in metrics:
            assert content["version"] == "MetricsItem/2.0"
            assert content["resourceIds"] == ["{GenericMetricAccount}"]
            assert content["resourceLimit"] == 1
            assert content["timeContext"] == {"durationMs": 30 * DAY_MS}
            assert all(metric["aggregation"] == 1 for metric in content["metrics"])
            ids = {metric["metric"].split("-")[-1] for metric in content["metrics"]}
            assert ids == (
                {"InputTokens", "OutputTokens"} if family == "foundry"
                else {"ProcessedPromptTokens", "GeneratedTokens"}
            )
            assert not any("cached" in metric["metric"].lower() for metric in content["metrics"])


def test_http_request_metrics_use_native_count_and_fixed_thirty_days(items):
    group = items["generic-http-optional"]["content"]
    assert group["loadType"] == "explicit"
    assert "optional" in group["loadButtonText"].lower()
    nested = {item["name"]: item for item in group["items"]}
    trend = nested["generic-http-trend"]["content"]
    totals = nested["generic-http-totals"]["content"]
    assert trend["chartType"] == 2
    assert totals["chartType"] == 0
    for content in (trend, totals):
        assert content["version"] == "MetricsItem/2.0"
        assert content["resourceType"] == "microsoft.insights/components"
        assert content["resourceIds"] == [COMPONENT]
        assert content["resourceLimit"] == 1
        assert content["timeContext"] == {"durationMs": 30 * DAY_MS}
        assert "timeContextFromParameter" not in content
        assert "HTTP requests" in content["title"]
        assert content["metrics"] == [
            {
                "namespace": "microsoft.insights/components",
                "metric": "microsoft.insights/components-Server-requests/count",
                "aggregation": 7,
                "columnName": "HTTP requests",
            },
            {
                "namespace": "microsoft.insights/components",
                "metric": "microsoft.insights/components-Failures-requests/failed",
                "aggregation": 7,
                "columnName": "Failed HTTP requests (subset)",
            },
        ]


@pytest.mark.parametrize(
    "selection",
    [
        "",
        RG + "-other/providers/Microsoft.CognitiveServices/accounts/elsewhere",
        RG.replace("11111111", "aaaaaaaa") + "/providers/Microsoft.CognitiveServices/accounts/elsewhere",
        '["/subscriptions/other/resourceGroups/other/providers/Microsoft.CognitiveServices/accounts/other"]',
        '" or true //',
        '"\n| union Resources\n| project id //',
        "\\\" | union Resources //",
    ],
)
def test_account_revalidation_keeps_untrusted_selection_inside_one_literal(items, selection):
    parameters = items["generic-native-selectors"]["content"]["parameters"]
    validator = next(parameter for parameter in parameters if parameter["name"] == "GenericMetricAccount")
    query = validator["query"]
    # Documented escapejson expansion; not a substitute for a live ARG/Portal execution.
    expanded = query.replace("{GenericAccount:escapejson}", json.dumps(selection)[1:-1])
    assert len(expanded.splitlines()) == len(query.splitlines())
    equality = next(line for line in expanded.splitlines() if line.startswith("| where id =~ "))
    assert json.loads(equality.removeprefix("| where id =~ ")) == selection
    assert f"| where tolower(id) startswith '{RG.lower()}/providers/microsoft.cognitiveservices/accounts/'" in expanded
    assert "array_length(split(id, '/')) == 9" in expanded
    assert "{GenericAccount}" not in json.dumps(items["generic-native-tokens"])


def test_inventory_is_exact_rg_scoped_and_projects_only_public_metadata(items):
    inventory = [
        item["content"] for item in flatten(items.values())
        if item["content"].get("queryType") == 1
    ]
    assert len(inventory) >= 3
    for content in inventory:
        assert content["version"] == "KqlItem/1.0"
        assert content["resourceType"] == "microsoft.resourcegraph/resources"
        assert content["crossComponentResources"] == [RG]
        query = content["query"]
        assert f"| where tolower(id) startswith '{RG.lower()}/providers/'" in query
        assert "properties" not in query
        assert "tags" not in query
    nested = {item["name"]: item for item in flatten(items.values())}
    grid = nested["generic-inventory"]["content"]
    assert "| project Resource=name, Type=type, Kind=kind, Location=location, id" in grid["query"]
    assert {"categoricalbar", "piechart"}.issubset({content["visualization"] for content in inventory})


def test_kpis_and_paired_charts_precede_all_optional_details(items):
    names = list(items)
    chart_names = [
        "generic-native-tokens", "generic-inventory-map",
        "generic-inventory-types", "generic-inventory-locations",
    ]
    assert names.index("generic-inventory-summary") < names.index(chart_names[0])
    assert names[names.index(chart_names[0]):names.index(chart_names[-1]) + 1] == chart_names
    heading = items["generic-usage-heading"]["content"]["json"]
    assert len(heading.splitlines()) == 2
    assert len(heading.splitlines()[1]) < 150
    summary = items["generic-inventory-summary"]["content"]
    assert summary["visualization"] == "tiles"
    assert summary["size"] == 4
    assert summary["tileSettings"]["leftContent"]["formatter"] == 12
    assert summary["tileSettings"]["titleContent"]["columnMatch"] == "Label"
    assert summary["tileSettings"]["leftContent"]["columnMatch"] == "Value"
    for label in ("Resources", "Service types", "Locations", "Foundry / OpenAI accounts"):
        assert label in summary["query"]
    for name in chart_names:
        assert items[name]["customWidth"] == "50"
    assert items["generic-inventory-map"]["content"]["visualization"] == "map"
    assert "generic-inventory" not in items, "Large inventory is not a primary-viewport item"
    details = items["generic-inventory-details"]["content"]
    assert details["loadType"] == "explicit"
    assert {item["name"] for item in details["items"]} == {"generic-inventory", "generic-health-details"}
    for name in ("generic-native-details", "generic-inventory-details", "generic-http-optional"):
        assert names.index(name) > names.index(chart_names[-1])
        assert items[name]["content"]["loadType"] == "explicit"
    for group in items["generic-native-tokens"]["content"]["items"]:
        visible_metrics = [item for item in group["content"]["items"] if item["type"] == 10]
        assert len(visible_metrics) == 1
        assert visible_metrics[0]["content"]["chartType"] == 3
        assert len(group["content"]["items"]) == 1
    assert all(item["content"]["chartType"] == 0 for item in items["generic-native-details"]["content"]["items"])


def test_native_region_and_composition_visuals_keep_all_locations(items):
    nested = {item["name"]: item["content"] for item in flatten(items.values())}
    region_map = nested["generic-inventory-map"]
    settings = region_map["mapSettings"]
    assert settings["locInfo"] == "AzureLoc"
    assert settings["locInfoColumn"] == "Location"
    assert settings["sizeSettings"] == settings["legendMetric"] == "Resources"
    assert settings["sizeAggregation"] == settings["legendAggregation"] == "Sum"
    assert "where isnotempty(location) and location !~ 'global'" in region_map["query"]
    assert "health" in region_map["title"]
    types = nested["generic-inventory-types"]
    assert "by Provider, Location=location" in types["query"]
    assert "split(type, '/')[0]" in types["query"]
    assert types["visualization"] == "categoricalbar"
    assert types["chartSettings"]["group"] == "Location"
    for name in ("generic-inventory-types", "generic-inventory-locations"):
        assert nested[name]["size"] == 1
        assert nested[name]["chartSettings"]["createOtherGroup"] == 0
        assert "where location" not in nested[name]["query"].lower()
    assert "global / unmapped" in nested["generic-inventory-locations"]["title"]


def test_health_map_separates_health_sources_and_never_assumes_empty_is_healthy(items):
    parameters = items["generic-health-sources"]["content"]["parameters"]
    assert {parameter["name"] for parameter in parameters} == {"GenericResourceHealth", "GenericRegionalHealth"}
    for parameter in parameters:
        assert parameter["isRequired"] and parameter["isHiddenWhenLocked"]
        assert parameter["value"] == ""
        assert parameter["queryType"] == 1
        assert parameter["crossComponentResources"] == [RG.split("/resourceGroups/")[0]]
    assert "HealthResources" in parameters[0]["query"]
    assert "ServiceHealthResources" not in parameters[0]["query"]
    assert "ServiceHealthResources" in parameters[1]["query"]
    assert "properties.Status" in parameters[1]["query"]
    assert "ImpactedRegions" in parameters[1]["query"]
    query = items["generic-inventory-map"]["content"]["query"]
    assert 'parse_json("{GenericResourceHealth:escapejson}")' in query
    assert 'parse_json("{GenericRegionalHealth:escapejson}")' in query
    assert "ResourceIssues > 0 or RegionalEvents > 0, 2" in query
    assert "SourcesComplete and AvailableResources == Resources and UnknownResources == 0, 0, 1" in query
    assert "complete reported resource coverage" in query
    assert "green does not guarantee SKU capacity" in items["generic-health-legend"]["content"]["json"]
    colors = items["generic-inventory-map"]["content"]["mapSettings"]["itemColorSettings"]
    assert colors == {
        "type": "thresholds", "nodeColorField": "HealthCode", "colorAggregation": "Max",
        "thresholdsGrid": [
            {"operator": "==", "thresholdValue": "2", "representation": "redBright"},
            {"operator": "==", "thresholdValue": "0", "representation": "green"},
            {"operator": "Default", "thresholdValue": None, "representation": "gray"},
        ],
    }


def test_billing_is_native_actual_cost_at_exact_rg_scope(items):
    billing = {
        name: item["content"] for name, item in items.items()
        if item["content"].get("queryType") == 12
    }
    assert {
        "generic-cost-total", "generic-cost-daily", "generic-cost-services",
        "generic-cost-daily-services",
    } <= billing.keys()
    for content in billing.values():
        assert content["version"] == "KqlItem/1.0"
        assert "unavailable" in content["noDataMessage"].lower()
        assert "resultFormat" not in content
        endpoint = json.loads(content["query"])
        assert endpoint["version"] == "ARMEndpoint/1.0"
        assert endpoint["method"] == "POST"
        assert endpoint["path"] == RG + "/providers/Microsoft.CostManagement/query"
        assert endpoint["headers"] == []
        assert endpoint["urlParams"] == [{"key": "api-version", "value": "2025-03-01"}]
        assert endpoint["batchDisabled"] is False
        body = json.loads(endpoint["data"])
        assert body["type"] == "ActualCost"
        assert body["timeframe"] == "MonthToDate"
        assert body["dataset"]["aggregation"] == {
            "totalCost": {"name": "Cost", "function": "Sum"},
        }
        assert "timePeriod" not in body
        assert len(endpoint["transformers"]) == 1
        assert endpoint["transformers"][0]["type"] == "jsonpath"
    daily = json.loads(json.loads(billing["generic-cost-daily"]["query"])["data"])
    assert daily["dataset"]["granularity"] == "Daily"
    services = json.loads(json.loads(billing["generic-cost-services"]["query"])["data"])
    assert services["dataset"]["grouping"] == [{"type": "Dimension", "name": "ServiceName"}]
    daily_services = json.loads(json.loads(billing["generic-cost-daily-services"]["query"])["data"])
    assert daily_services["dataset"]["granularity"] == "Daily"
    assert daily_services["dataset"]["grouping"] == [{"type": "Dimension", "name": "ServiceName"}]


@pytest.mark.parametrize(
    ("name", "rows", "expected"),
    [
        (
            "generic-cost-total",
            [[135.111382, "USD"], [10.25, "EUR"], [None, "USD"], [0, "GBP"], [-2.5, "CHF"], [3, None], [4, ""]],
            [
                {"Cost": 135.111382, "Currency": "USD"},
                {"Cost": 10.25, "Currency": "EUR"},
                {"Cost": None, "Currency": "USD"},
                {"Cost": 0, "Currency": "GBP"},
                {"Cost": -2.5, "Currency": "CHF"},
                {"Cost": 3, "Currency": None},
                {"Cost": 4, "Currency": ""},
            ],
        ),
        (
            "generic-cost-daily",
            [[14.4480369999062, 20261001, "USD"], [None, 20261002, "EUR"]],
            [
                {"Cost": 14.4480369999062, "UsageDate": "2026-10-01", "Currency": "USD"},
                {"Cost": None, "UsageDate": "2026-10-02", "Currency": "EUR"},
            ],
        ),
        (
            "generic-cost-services",
            [[30.25, "Azure OpenAI", "EUR"], [20.5, "Azure OpenAI", "USD"]],
            [
                {"Cost": 30.25, "ServiceName": "Azure OpenAI", "Currency": "EUR"},
                {"Cost": 20.5, "ServiceName": "Azure OpenAI", "Currency": "USD"},
            ],
        ),
        (
            "generic-cost-daily-services",
            [
                [30.25, 20261001, "Azure OpenAI", "EUR"],
                [-2.5, 20261001, "Virtual Machines", "EUR"],
                [20.5, 20261002, "Azure OpenAI", "USD"],
                [None, 20261003, "Azure OpenAI", "USD"],
            ],
            [
                {"Cost": 30.25, "UsageDate": "2026-10-01", "ServiceName": "Azure OpenAI", "Currency": "EUR"},
                {"Cost": -2.5, "UsageDate": "2026-10-01", "ServiceName": "Virtual Machines", "Currency": "EUR"},
                {"Cost": 20.5, "UsageDate": "2026-10-02", "ServiceName": "Azure OpenAI", "Currency": "USD"},
                {"Cost": None, "UsageDate": "2026-10-03", "ServiceName": "Azure OpenAI", "Currency": "USD"},
            ],
        ),
    ],
)
def test_billing_column_contract_preserves_source_values(items, name, rows, expected):
    settings = json.loads(items[name]["content"]["query"])["transformers"][0]["settings"]
    assert settings["tablePath"] == (
        '$.properties.rows[?(@[2] == "{GenericCostCurrency:escapejson}")]'
        if name == "generic-cost-services" else
        '$.properties.rows[?(@[3] == "{GenericCostCurrency:escapejson}")]'
        if name == "generic-cost-daily-services" else "$.properties.rows"
    )
    columns = settings["columns"]
    results = []
    for row in rows:
        result = {}
        for column in columns:
            # Exercise only the emitted positional/date contract, not the Portal's JSONPath engine.
            match = re.fullmatch(r"\$\[(\d+)\]", column["path"])
            assert match
            value = row[int(match[1])]
            assert "defaultValue" not in column
            if column["columnid"] == "UsageDate":
                assert column["columnType"] == "datetime"
                assert column["substringRegexMatch"] == "([0-9]{4})([0-9]{2})([0-9]{2})"
                assert column["substringReplace"] == "$1-$2-$3"
                value = re.sub(column["substringRegexMatch"], r"\1-\2-\3", str(value))
            else:
                assert set(column) == {"path", "columnid"}, "Never coerce or default money/currency fields"
            result[column["columnid"]] = value
        results.append(result)
    assert results == expected


def test_currencies_stay_separate_and_fallback_is_display_only(items):
    total = items["generic-cost-total"]["content"]
    assert total["tileSettings"]["titleContent"]["columnMatch"] == "Currency"
    assert total["tileSettings"]["leftContent"] == {
        "columnMatch": "Cost",
        "formatter": 12,
        "numberFormat": {
            "unit": 0,
            "options": {
                "style": "decimal",
                "useGrouping": True,
                "minimumFractionDigits": 2,
                "maximumFractionDigits": 2,
            },
        },
    }
    for name in ("generic-cost-daily", "generic-cost-services", "generic-cost-daily-services"):
        content = items[name]["content"]
        assert content["chartSettings"].get("group") == (
            "Currency" if name == "generic-cost-daily" else
            "ServiceName" if name == "generic-cost-daily-services" else None
        )
        assert content["chartSettings"]["yAxis"] == ["Cost"]
        assert content["chartSettings"]["showMetrics"] is False
        assert "USD" not in content["query"], "Returned currency must not be replaced"
    assert "USD display fallback when no currency is emitted" in items["generic-cost-heading"]["content"]["json"]
    assert "missing amounts remain unavailable" in items["generic-cost-heading"]["content"]["json"]


def test_cost_visuals_select_one_returned_currency_and_retain_unfiltered_details(items):
    currency = items["generic-cost-currency"]["content"]["parameters"][0]
    assert currency["name"] == "GenericCostCurrency"
    assert currency["type"] == 2
    assert currency["multiSelect"] is False
    assert "value" not in currency, "An explicit empty selection overrides the native default"
    assert currency["defaultValue"] == "value::1"
    assert currency["typeSettings"]["additionalResourceOptions"] == ["value::1"]
    assert "value::all" not in json.dumps(currency)
    assert "USD" not in json.dumps(currency), "The default must come from returned billing rows"
    endpoint = json.loads(currency["query"])
    assert endpoint["path"] == RG + "/providers/Microsoft.CostManagement/query"
    assert json.loads(endpoint["data"])["dataset"]["granularity"] == "None"
    assert endpoint["transformers"][0]["settings"]["columns"] == [
        {"path": "$[1]", "columnid": "value"}, {"path": "$[1]", "columnid": "label"},
    ]
    for name in ("generic-cost-services", "generic-cost-daily-services"):
        content = items[name]["content"]
        assert "{GenericCostCurrency}" in content["title"]
        path = json.loads(content["query"])["transformers"][0]["settings"]["tablePath"]
        assert "{GenericCostCurrency:escapejson}" in path
        assert "@[0]" not in path, "Credits, null amounts, and zeros must not be filtered out"
        assert content["chartSettings"]["createOtherGroup"] == 0
        assert content["visualization"] != "piechart", "Signed cost is not a pie share"
    assert items["generic-cost-daily-services"]["content"]["visualization"] == "areachart"
    assert items["generic-cost-total"]["customWidth"] == "30"
    assert items["generic-cost-services"]["customWidth"] == "70"
    assert items["generic-cost-daily"]["customWidth"] == "50"
    assert items["generic-cost-daily-services"]["customWidth"] == "50"
    details = items["generic-cost-details"]["content"]
    assert details["loadType"] == "explicit"
    assert len(details["items"]) == 2
    for item in details["items"]:
        assert item["content"]["visualization"] == "table"
        path = json.loads(item["content"]["query"])["transformers"][0]["settings"]["tablePath"]
        assert path == "$.properties.rows", "All billing currencies and credits remain inspectable"


def test_response_schema_and_pagination_are_inspectable_without_default_extra_calls(items):
    inspector = items["generic-cost-response-inspection"]["content"]
    assert inspector["loadType"] == "explicit"
    assert "schema" in inspector["loadButtonText"]
    expected_schemas = {
        "total": "Cost:Number, Currency:String",
        "daily": "Cost:Number, UsageDate:Number, Currency:String",
        "services": "Cost:Number, ServiceName:String, Currency:String",
        "daily-services": "Cost:Number, UsageDate:Number, ServiceName:String, Currency:String",
    }
    assert len(inspector["items"]) == 4
    for item in inspector["items"]:
        key = item["name"].removeprefix("generic-cost-schema-")
        content = item["content"]
        assert expected_schemas[key] in content["title"]
        endpoint = json.loads(content["query"])
        assert endpoint["data"] == json.loads(items[f"generic-cost-{key}"]["content"]["query"])["data"]
        assert endpoint["transformers"] == [{
            "type": "jsonpath",
            "settings": {
                "tablePath": "$.properties",
                "columns": [
                    {"path": "$.columns", "columnid": "ReturnedSchema"},
                    {"path": "$.nextLink", "columnid": "NextPage"},
                ],
            },
        }]
    note = items["generic-cost-response-note"]["content"]["json"]
    assert "unexpected order/type is unsupported" in note
    assert "nonempty **NextPage** means a partial response" in note


def test_scope_and_metrics_follow_caller_inputs(compiled_generic):
    other_rg = "/subscriptions/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/resourceGroups/Other-Project"
    other_component = other_rg + "/providers/Microsoft.Insights/components/other-insights"
    emitted = materialize(compiled_generic, other_rg, other_component)
    all_items = list(flatten(emitted))
    assert len({item["name"] for item in all_items}) == len(all_items)
    for item in all_items:
        content = item["content"]
        if content.get("queryType") == 1:
            assert f"'{other_rg.lower()}/providers/'" in content["query"]
            assert content["crossComponentResources"] == [other_rg]
        if content.get("version") == "MetricsItem/2.0":
            assert content["resourceIds"] == (
                [other_component] if content["resourceType"] == "microsoft.insights/components"
                else ["{GenericMetricAccount}"]
            )
        if content.get("queryType") == 12:
            assert json.loads(content["query"])["path"] == other_rg + "/providers/Microsoft.CostManagement/query"
    assert RG not in json.dumps(emitted)
