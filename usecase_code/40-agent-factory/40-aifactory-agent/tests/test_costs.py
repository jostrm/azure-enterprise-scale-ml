import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

import httpx
import pytest
from azure.core.exceptions import ClientAuthenticationError
from pydantic import ValidationError

from aifactory_agent.costs import (
    ARM, RETAIL, COST_SKILLS, COST_TOOL_TO_SKILL, DEFAULT_VARIABLES_RELATIVE_PATH,
    DEFAULT_VARIABLES_SHA256, CostSettings, CostSkills, NoArguments, RGArguments,
    argument_model, cost_descriptors, template_components,
)
from aifactory_agent.security import Principal
from aifactory_agent.tools import ToolError
from test_security import CALLER, CLIENT, SCOPE, SUBSCRIPTION, TENANT, settings as security_settings


NOW = datetime(2026, 10, 3, 18, 59, 41, tzinfo=timezone.utc)
RG = "factory-project001-dev-rg"
COMMON = "factory-common-dev-rg"
PROJECT_PATH = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RG}"
COMMON_PATH = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{COMMON}"
REPO = Path(__file__).resolve().parents[4]


class FakeCredential:
    def __init__(self):
        self.scopes = []

    def get_token(self, scope):
        self.scopes.append(scope)
        return SimpleNamespace(token="test-arm-token-never-retail")


@pytest.fixture
def settings():
    original = security_settings.__wrapped__()
    grant = original.auth.grants[0].model_copy(update={"permissions": ["factory.read", "cost.read"]})
    return original.model_copy(update={
        "auth": original.auth.model_copy(update={"grants": [grant]}),
        "knowledge": original.knowledge.model_copy(update={"repository_root": REPO}),
        "costs": CostSettings(common_resource_groups={SCOPE: [COMMON]}),
    })


@pytest.fixture
def principal():
    return Principal(TENANT, CALLER)


def actual_page(rows=None, next_link=None, columns=None):
    return {"properties": {
        "columns": columns or [{"name": name} for name in ("Currency", "UsageDate", "ServiceName", "PreTaxCost")],
        "rows": [["USD", 20261003, "Azure AI Search", 2]] if rows is None else rows,
        "nextLink": next_link,
    }}


def forecast_page(rows=None, next_link=None, columns=None):
    return {"properties": {
        "columns": columns or [{"name": name} for name in ("CostStatus", "Currency", "PreTaxCost", "UsageDate")],
        "rows": [["Actual", "USD", 20, 20261003], ["Forecast", "USD", 30, 20261031]] if rows is None else rows,
        "nextLink": next_link,
    }}


def price_item(**changes):
    return {
        "armRegionName": "eastus2", "currencyCode": "USD", "serviceName": "Azure Cognitive Search",
        "skuName": "Basic", "armSkuName": "", "type": "Consumption", "isPrimaryMeterRegion": True,
        "productName": "Azure Cognitive Search", "meterName": "Basic Search Unit", "meterId": "meter-basic",
        "tierMinimumUnits": 0, "retailPrice": 0.1, "unitOfMeasure": "1 Hour",
        "effectiveStartDate": "2026-09-01T00:00:00Z", **changes,
    }


def resource(kind="Microsoft.ContainerRegistry/registries", name="acrcommon", **changes):
    return {"id": COMMON_PATH + "/providers/" + kind + "/" + name, "type": kind,
            "location": "eastus2", "sku": {"name": "Premium"}, **changes}


class FakeAzure:
    def __init__(self, *, actual=None, forecast=None, items=None, resources=None, details=None):
        self.actual = actual_page() if actual is None else actual
        self.forecast = forecast_page() if forecast is None else forecast
        self.items = [price_item()] if items is None else items
        self.resources = [resource()] if resources is None else resources
        self.details = details or {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if request.url.host == "prices.azure.com":
            assert "authorization" not in request.headers
            assert request.method == "GET"
            return httpx.Response(200, json={"Items": self.items, "NextPageLink": None})
        assert request.url.host == "management.azure.com"
        assert request.headers["authorization"] == "Bearer test-arm-token-never-retail"
        if request.url.path.endswith("/query"):
            assert request.method == "POST"
            return httpx.Response(200, json=self.actual)
        if request.url.path.endswith("/forecast"):
            assert request.method == "POST"
            return httpx.Response(200, json=self.forecast)
        if request.url.path.endswith("/resources"):
            assert request.method == "GET"
            return httpx.Response(200, json={"value": self.resources})
        assert request.method == "GET"
        result = self.details.get(request.url.path, next(
            (item for item in self.resources if item["id"] == request.url.path), {},
        ))
        return httpx.Response(200, json=result)


def run(settings, principal, fake, skill=COST_SKILLS[0], args=None, cred=None):
    credential = cred or FakeCredential()
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        result = CostSkills(settings, principal, SCOPE, cred=credential, http_client=client,
                            clock=lambda: NOW).execute(skill, {} if args is None else args)
    return result["data"], credential


def configure(settings, **changes):
    return settings.model_copy(update={"costs": settings.costs.model_copy(update=changes)})


def test_descriptors_flat_strict_and_exact_registry():
    descriptors = cost_descriptors()
    assert len(descriptors) == 3
    assert COST_TOOL_TO_SKILL == {
        "cost_default_project_idle": "/get-default-project-estimated-azure-idle-running-cost",
        "cost_common_idle": "/get-aifactory-common-estimated-azure-idle-running-cost",
        "cost_monthly_project_forecast": "/get-monthtly-forecasted-project-estimated-azure-cost",
    }
    assert tuple(COST_TOOL_TO_SKILL.values()) == COST_SKILLS
    assert "monthtly" in COST_TOOL_TO_SKILL["cost_monthly_project_forecast"]
    for descriptor in descriptors:
        assert descriptor["type"] == "function" and descriptor["strict"]
        assert len(descriptor["name"]) <= 64
        assert "function" not in descriptor
        assert descriptor["parameters"]["additionalProperties"] is False
        schema = descriptor["parameters"]
        assert schema["required"] == ([] if descriptor["name"] == "cost_default_project_idle" else ["resource_group"])
        assert set(schema["properties"]) == set(schema["required"])
    assert argument_model(COST_SKILLS[0]) is NoArguments
    assert argument_model(COST_SKILLS[1]) is RGArguments
    assert argument_model("/get-monthly-forecasted-project-estimated-azure-cost") is RGArguments


@pytest.mark.parametrize("arguments", [
    {"scope_key": "other"}, {"tenant_id": TENANT}, {"subscription_id": SUBSCRIPTION},
    {"resource_group": RG}, {"currency": "EUR"}, {"variables_path": "live-settings.json"},
])
def test_default_arguments_forbid_scope_or_template_substitution(settings, principal, arguments):
    fake = FakeAzure()
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, args=arguments)
    assert error.value.code == "invalid_arguments"
    assert not fake.requests


@pytest.mark.parametrize("arguments", [
    {}, {"resource_group": 3}, {"resource_group": f"{RG}/providers/Microsoft.Compute"},
    {"resource_group": RG, "subscription_id": SUBSCRIPTION}, {"resource_group": "$(rg)"},
])
def test_resource_group_arguments_are_strict_and_closed(settings, principal, arguments):
    fake = FakeAzure()
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], arguments)
    assert error.value.code == "invalid_arguments" and not fake.requests


@pytest.mark.parametrize("permissions", [[], ["factory.read"], ["cost.read"]])
def test_both_exact_scope_permissions_required(settings, principal, permissions):
    grant = settings.auth.grants[0].model_copy(update={"permissions": permissions})
    settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={"grants": [grant]})})
    fake = FakeAzure()
    with pytest.raises(PermissionError):
        run(settings, principal, fake)
    assert CostSkills(settings, principal, SCOPE).descriptors() == []
    assert not fake.requests


def test_permissions_cannot_be_borrowed_from_other_scope_or_principal(settings, principal):
    grant = settings.auth.grants[0]
    split = [
        grant.model_copy(update={"permissions": ["factory.read"]}),
        grant.model_copy(update={"scopes": ["project002-dev"], "permissions": ["cost.read"]}),
    ]
    current = settings.model_copy(update={"auth": settings.auth.model_copy(update={"grants": split})})
    with pytest.raises(PermissionError):
        run(current, principal, FakeAzure())
    for forged in (Principal(CLIENT, CALLER), Principal(TENANT, CLIENT, {SCOPE}, {"factory.read", "cost.read"})):
        with pytest.raises(PermissionError):
            run(settings, forged, FakeAzure())


@pytest.mark.parametrize("skill,group", [
    (COST_SKILLS[1], RG), (COST_SKILLS[1], "unconfigured-common-rg"),
    (COST_SKILLS[2], COMMON), (COST_SKILLS[2], "unconfigured-project-rg"),
])
def test_group_allowlist_is_exact_per_skill(settings, principal, skill, group):
    fake = FakeAzure()
    with pytest.raises(PermissionError):
        run(settings, principal, fake, skill, {"resource_group": group})
    assert not fake.requests


@pytest.mark.parametrize("options", [
    {"currency": "usd"}, {"currency": "XYZ"}, {"currency": "USD' or true"},
    {"max_pages": 0}, {"max_pages": 21}, {"max_pages": "2"}, {"unknown": True},
    {"common_resource_groups": {"*": [COMMON]}},
    {"common_resource_groups": {SCOPE: [COMMON, COMMON.upper()]}},
    {"common_resource_groups": {SCOPE: ["rg/other"]}},
    {"common_resource_groups": {SCOPE: []}},
])
def test_cost_settings_closed_and_bounded(options):
    with pytest.raises(ValidationError):
        CostSettings(**options)


def test_canonical_default_is_integrity_pinned_and_live_settings_not_used(settings, principal):
    raw = (REPO / DEFAULT_VARIABLES_RELATIVE_PATH).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DEFAULT_VARIABLES_SHA256
    fake = FakeAzure()
    data, cred = run(settings, principal, fake)
    assert data["inventory_source"]["source_type"] == "canonical_default_variables"
    assert not data["inventory_source"]["uses_applied_live_settings"]
    baseline = data["idle_baseline"]
    search = next(item for item in baseline["components"] if item["service"] == "ai-search")
    assert search["sku"] == "basic" and search["region"] == "eastus2"
    assert settings.location == "swedencentral"
    assert search["estimate"]["monthly"] == "73.0"
    assert baseline["status"] == "partial" and not baseline["complete"] and baseline["total_monthly"] is None
    assert data["actual_mtd"]["totals_by_currency"] == {"USD": "2"}
    assert set(cred.scopes) == {ARM + "/.default"}
    assert not any("azurefactory" in str(request.url) for request in fake.requests)
    retail = next(request for request in fake.requests if request.url.host == "prices.azure.com")
    query = parse_qs(retail.url.query.decode())
    assert "armRegionName eq 'eastus2'" in query["$filter"][0]
    assert "skuName eq 'Basic'" in query["$filter"][0] and query["currencyCode"] == ["'USD'"]


def test_template_changed_or_unpinned_is_explicit_blocker(settings, principal, monkeypatch):
    with pytest.raises(ToolError) as error:
        run(configure(settings, default_variables_path=Path("applied.json")), principal, FakeAzure())
    assert error.value.code == "cost_template_unpinned"
    monkeypatch.setattr(Path, "read_bytes", lambda _: b'{"dev":{}}')
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure())
    assert error.value.code == "cost_template_integrity"


def test_packaged_template_path_requires_trusted_hash(settings, principal, monkeypatch):
    path = Path("bundled-default-variables.json")
    raw = json.dumps({"dev": {"admin_location": "eastus2", "enableAISearch": True}}).encode()
    read_paths = []
    def read_bytes(selected):
        read_paths.append(selected)
        return raw
    monkeypatch.setattr(Path, "stat", lambda _: SimpleNamespace(st_size=len(raw)))
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    current = configure(settings, default_variables_path=path, default_variables_sha256=hashlib.sha256(raw).hexdigest())
    data, _ = run(current, principal, FakeAzure())
    assert data["inventory_source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert read_paths == [settings.knowledge.repository_root / path]


def test_explicit_pin_for_repository_default_path_is_not_ignored(settings, principal):
    fake = FakeAzure()
    with pytest.raises(ToolError) as error:
        run(configure(settings, default_variables_sha256="0" * 64), principal, fake)
    assert error.value.code == "cost_template_integrity" and not fake.requests


def test_template_enabled_disabled_and_environment_sku_arrays():
    document = {"dev": {
        "admin_location": "eastus2", "enableAISearch": "true", "skuAISearchDev": "basic",
        "skuAISearchStageProd": "standard2", "skuAISearchDevArray": ["basic", "standard", "standard3"],
        "aiSearchReplicaCount": "2", "aiSearchPartitionCount": 3, "enableRedisCache": "false",
        "enablePostgreSQL": True, "skuPostgreSQLDev": "Standard_B1ms",
        "skuPostgreSQLStageProd": "Standard_B2ms", "skuTierPostgreSQLStageProd": "Burstable",
        "enableSomethingFuture": True,
    }}
    dev, stage = template_components(document, "dev"), template_components(document, "stage")
    search = next(row for row in dev if row.service == "ai-search")
    assert search.sku == "basic" and search.quantity == 6 and search.dimensions == {"replicas": "2", "partitions": "3"}
    assert len([row for row in dev if row.service == "ai-search"]) == 1
    assert not any(row.service == "redis" for row in dev)
    assert next(row for row in stage if row.service == "ai-search").sku == "standard2"
    assert next(row for row in stage if row.service == "postgresql").sku == "Standard_B2ms"
    assert next(row for row in stage if row.service == "postgresql").dimensions["tier"] == "Burstable"
    assert next(row for row in dev if row.service == "unmapped-enabled-feature").dimensions["flag"] == "enableSomethingFuture"
    assert len([row for row in dev if row.service.endswith("storage")]) == 2


def test_private_foundry_bicep_requirements_override_disabled_optional_switches():
    rows = template_components({"dev": {"admin_location": "eastus2", "enableAIFoundry": True,
                                       "enablePublicGenAIAccess": False, "enableAISearch": False,
                                       "enableCosmosDB": False}}, "dev")
    assert {"ai-search", "cosmos-db", "foundry", "foundry-capability-host"} <= {row.service for row in rows}


def test_all_enabled_services_models_and_quantities_are_exposed():
    values = {
        "admin_location": "eastus2", "enableWebApp": True, "webAppRuntime": "python",
        "enableAzureMachineLearning": True, "enableAksForAzureML": True,
        "admin_aks_nodes_dev_override": 2, "admin_aks_gpu_sku_dev_override": "Standard_D4s_v5",
        "enableAIServices": True, "enableAzureOpenAI": True, "enableAIFoundry": True,
        "deployModel_gpt_X": True, "modelGPTXCapacity": 30, "enableProjectVM": True,
        "enableBing": True, "enableBingCustomSearch": True, "ENABLE_APIM": True,
        "apimGatewaySkuCapacity": 2, "ENABLE_KONG": True, "useCommonACR": False,
        "enableDefenderforAISubLevel": True, "enableAMPLS": True,
    }
    for key in ("enableContentSafety", "enableAzureAIVision", "enableAzureSpeech", "enableAIDocIntelligence",
                "enableRedisCache", "enablePostgreSQL", "enableSQLDatabase", "enableElasticsearch",
                "enableFunction", "enableContainerApps", "enableDatabricks", "enableDatafactory",
                "enableLogicApps", "enableEventHubs", "enableBotService", "enableAIFoundryHub"):
        values[key] = True
    rows = template_components({"dev": values}, "dev")
    services = {row.service for row in rows}
    assert {"web-app-plan", "machine-learning", "aml-training-clusters", "aks-nodes", "virtual-machine",
            "container-registry", "bing-grounding", "bing-custom-grounding", "redis", "function-plan",
            "container-apps", "databricks", "data-factory", "bot-service", "foundry-hub",
            "content-safety", "vision", "speech", "document-intelligence", "sql-database",
            "elasticsearch", "logic-apps-plan", "event-hubs", "api-management", "kong-gateway"} <= services
    assert next(row for row in rows if row.service == "aks-nodes").quantity == 2
    assert next(row for row in rows if row.service == "deployModel_gpt_X").quantity == 2
    assert next(row for row in rows if row.service == "deployModel_gpt_X").dimensions["quota_capacity"] == 30
    assert "minNodeCount=0" in next(row for row in rows if row.service == "aml-training-clusters").assumption
    assert next(row for row in rows if row.service == "aml-training-clusters").quantity == 1


def test_shared_existing_plan_and_ase_workers_are_not_invented():
    doc = {"dev": {"admin_location": "eastus2", "enableWebApp": True, "byoASEv3": True,
                   "aseSkuCode": "I2v2", "aseSkuWorkers": 3}}
    row = next(row for row in template_components(doc, "dev") if row.service == "web-app-plan")
    assert row.sku == "I2v2" and row.quantity == 3 and row.selector is None
    doc["dev"]["byoAseAppServicePlanResourceId"] = "/subscriptions/external/plan"
    row = next(row for row in template_components(doc, "dev") if row.service == "web-app-plan")
    assert "not" not in row.assumption or "do not charge per app" in row.assumption
    assert row.selector is None and "shared" in row.assumption.lower()


@pytest.mark.parametrize("item_changes", [
    {"unitOfMeasure": "1 GB"}, {"currencyCode": "EUR"}, {"armRegionName": "westus"},
    {"skuName": "Standard"}, {"type": "Reservation"}, {"retailPrice": "NaN"},
    {"effectiveStartDate": "2030-01-01T00:00:00Z"}, {"effectiveStartDate": "invalid"},
    {"tierMinimumUnits": 1}, {"isPrimaryMeterRegion": False}, {"meterName": "Semantic Queries"},
    {"isPrimaryMeterRegion": None}, {"isPrimaryMeterRegion": "true"},
    {"tierMinimumUnits": None}, {"meterId": None}, {"meterId": {"malformed": True}},
])
def test_bad_or_wrong_dimension_rates_are_unknown_not_zero(settings, principal, item_changes):
    data, _ = run(settings, principal, FakeAzure(items=[price_item(**item_changes)]))
    baseline = data["idle_baseline"]
    search = next(row for row in baseline["components"] if row["service"] == "ai-search")
    assert search["estimate"]["monthly"] is None and search["estimate"]["status"] == "unknown_fixed_component"
    assert baseline["priced_fixed_subtotal"] is None and baseline["status"] == "unavailable"


@pytest.mark.parametrize("items,blocker", [
    ([], "missing_authoritative_rate"),
    ([price_item(), price_item(meterId="different-meter")], "ambiguous_authoritative_rate"),
    ([price_item(), price_item(retailPrice=0.2)], "ambiguous_authoritative_rate"),
])
def test_missing_and_ambiguous_prices_explicit(settings, principal, items, blocker):
    data, _ = run(settings, principal, FakeAzure(items=items))
    search = next(row for row in data["idle_baseline"]["components"] if row["service"] == "ai-search")
    assert search["estimate"]["blocker"] == blocker and search["estimate"]["monthly"] is None


def test_duplicate_identical_rate_and_latest_effective_rate_are_deterministic(settings, principal):
    data, _ = run(settings, principal, FakeAzure(items=[
        price_item(effectiveStartDate="2026-08-01T00:00:00Z", retailPrice=0.2), price_item(), price_item(),
    ]))
    assert data["idle_baseline"]["priced_fixed_subtotal"] == "73.0"


def test_search_replica_units_scale_monthly_quantity(settings, principal, monkeypatch):
    monkeypatch.setattr(CostSkills, "_template", lambda _: (
        {"dev": {"admin_location": "eastus2", "enableAISearch": True, "skuAISearchDev": "basic",
                 "aiSearchReplicaCount": 2, "aiSearchPartitionCount": 3}}, {},
    ))
    data, _ = run(settings, principal, FakeAzure())
    search = next(row for row in data["idle_baseline"]["components"] if row["service"] == "ai-search")
    assert search["estimate"]["monthly"] == "438.0"
    assert search["estimate"]["monthly_billed_quantity"] == "4380"
    assert search["estimate"]["rate"]["unit"] == "1 Hour"
    assert search["estimate"]["rate"]["source"] == RETAIL
    assert search["estimate"]["rate"]["observed_at"] == NOW.isoformat()


def test_common_discovery_uses_live_sku_and_daily_price_units(settings, principal):
    fake = FakeAzure(items=[price_item(serviceName="Container Registry", skuName="Premium",
                                       productName="Container Registry", meterName="Premium Registry Unit",
                                       unitOfMeasure="1/Day", retailPrice=2)])
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    assert data["inventory_source"]["source_type"] == "deployed_arm_inventory"
    acr = data["idle_baseline"]["components"][0]
    assert acr["sku"] == "Premium" and acr["provisioned_quantity"] == "1"
    assert float(acr["estimate"]["monthly"]) == pytest.approx(2 * 730 / 24)
    assert "metrics" in acr["assumption"]
    assert all(COMMON_PATH in request.url.path for request in fake.requests if request.url.host == "management.azure.com")


def test_common_search_capacity_requires_resource_detail_not_generic_list(settings, principal):
    listed = resource("Microsoft.Search/searchServices", "search", sku={"name": "basic"})
    detailed = {**listed, "properties": {"replicaCount": 2, "partitionCount": 3}}
    fake = FakeAzure(resources=[listed], details={listed["id"]: detailed})
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    assert data["idle_baseline"]["components"][0]["estimate"]["monthly"] == "438.0"
    detailed["properties"] = {}
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    assert data["idle_baseline"]["components"][0]["estimate"]["monthly"] is None


def test_common_unknown_and_usage_services_are_never_omitted(settings, principal):
    fake = FakeAzure(resources=[
        resource("Microsoft.Storage/storageAccounts", "lake", sku={"name": "Standard_ZRS"}),
        resource("Microsoft.Unknown/expensiveThings", "thing", sku={"name": "NewPremium"}),
    ])
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    rows = data["idle_baseline"]["components"]
    assert len(rows) == 2 and all(row["estimate"]["monthly"] is None for row in rows)
    assert "GiB" in rows[0]["usage_requirements"]
    assert "Unmapped" in rows[1]["usage_requirements"] and rows[1]["estimate"]["status"] == "unknown_fixed_component"


@pytest.mark.parametrize("mutation", ["cross-rg", "duplicate", "type-mismatch"])
def test_resource_inventory_never_substitutes_scope(settings, principal, mutation):
    item = resource()
    resources = [item]
    if mutation == "cross-rg":
        item["id"] = item["id"].replace(COMMON, RG)
    elif mutation == "duplicate":
        resources.append(item)
    else:
        item["type"] = "Microsoft.Compute/virtualMachines"
    fake = FakeAzure(resources=resources)
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    assert error.value.code == "cost_inventory_scope_mismatch"
    assert not any(request.url.path.startswith(PROJECT_PATH) for request in fake.requests)


def test_forecast_real_endpoint_type_full_month_and_no_double_count(settings, principal):
    fake = FakeAzure()
    data, _ = run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert data["actual_mtd"]["totals_by_currency"] == {"USD": "2"}
    forecast = data["azure_forecast_full_month"]
    assert forecast["totals_by_currency"] == {"USD": "50"}
    assert forecast["actual_component_by_currency"] == {"USD": "20"}
    assert forecast["forecast_component_by_currency"] == {"USD": "30"}
    assert not data["synthetic_extrapolation"] and data["forecast_total_includes_actual"]
    request = next(request for request in fake.requests if request.url.path.endswith("/forecast"))
    body = json.loads(request.content)
    assert body["type"] == "ActualCost" and body["includeActualCost"] is True
    assert body["includeFreshPartialCost"] is False and body["timeframe"] == "Custom"
    assert body["timePeriod"] == {"from": "2026-10-01T00:00:00+00:00", "to": "2026-10-31T23:59:59+00:00"}
    assert "ForecastedCost" not in request.content.decode()
    assert body["dataset"]["aggregation"]["totalCost"]["name"] == "Cost"


def test_forecast_billing_lag_uses_posted_actual_cutoff_not_observation_date(settings, principal):
    fake = FakeAzure(
        actual=actual_page([["USD", 20261001, "Search", 2]]),
        forecast=forecast_page(
            [[20, 20261001, "Actual", "USD"]]
            + [[1, 20261000 + day, "Forecast", "USD"] for day in range(2, 32)],
            columns=[{"name": name} for name in ("Cost", "UsageDate", "CostStatus", "Currency")],
        ),
    )
    data, _ = run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    forecast = data["azure_forecast_full_month"]
    assert forecast["observed_at"] == NOW.isoformat()
    assert forecast["totals_by_currency"] == {"USD": "50"}
    assert forecast["actual_component_by_currency"] == {"USD": "20"}
    assert forecast["forecast_component_by_currency"] == {"USD": "30"}
    assert forecast["actual_cutoff_by_currency"] == {"USD": "2026-10-01"}
    assert forecast["actual_data_lag_days_by_currency"] == {"USD": 2}
    assert "lag" in forecast["billing_lag_explanation"].lower()
    assert "includeFreshPartialCost=False" in forecast["billing_lag_explanation"]
    assert data["actual_mtd"]["totals_by_currency"] == {"USD": "2"}
    assert not data["synthetic_extrapolation"] and data["forecast_total_includes_actual"]


def test_forecast_cutoff_is_per_currency_across_unordered_pages(settings, principal):
    next_url = f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/forecast?api-version=2025-03-01&$skiptoken=two"
    fake = FakeAzure()
    forecast_requests = []

    def handler(request):
        if not request.url.path.endswith("/forecast"):
            return fake(request)
        forecast_requests.append(request)
        if "$skiptoken=two" in str(request.url):
            return httpx.Response(200, json=forecast_page(
                [[10, 20261001, "ActualCost", "USD"], [7, 20261003, "Forecast", "EUR"]],
                columns=[{"name": name} for name in ("Cost", "UsageDate", "CostStatus", "Currency")],
            ))
        return httpx.Response(200, json=forecast_page(
            [["Forecast", "USD", 20, 20261002], ["Actual", "EUR", 3, 20261002]], next_url,
        ))

    data, _ = run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    forecast = data["azure_forecast_full_month"]
    assert forecast["totals_by_currency"] == {"EUR": "10", "USD": "30"}
    assert forecast["actual_cutoff_by_currency"] == {"EUR": "2026-10-02", "USD": "2026-10-01"}
    assert forecast["actual_data_lag_days_by_currency"] == {"EUR": 1, "USD": 2}
    assert len(forecast_requests) == 2
    assert all(request.method == "POST" for request in forecast_requests)
    assert json.loads(forecast_requests[0].content) == json.loads(forecast_requests[1].content)


@pytest.mark.parametrize("rows", [[], [["Actual", "USD", 20, 20261003]]])
def test_forecast_insufficient_history_not_success_zero_or_extrapolation(settings, principal, rows):
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(forecast=forecast_page(rows)), COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "forecast_unavailable"


@pytest.mark.parametrize("status", [204, 400, 401, 403, 429, 503])
def test_billing_errors_explicit_and_no_synthetic_fallback(settings, principal, status):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status)
    with pytest.raises(ToolError) as error:
        run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code in {"cost_data_unavailable", "cost_access_denied", "cost_service_unavailable"}
    assert len(seen) == 1


def test_actual_empty_data_is_not_zero_but_explicit_zero_row_is_valid(settings, principal):
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(actual=actual_page([])), COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "cost_data_unavailable"
    data, _ = run(settings, principal, FakeAzure(actual=actual_page([["USD", 20261003, "Search", 0]])),
                  COST_SKILLS[2], {"resource_group": RG})
    assert data["actual_mtd"]["totals_by_currency"] == {"USD": "0"}


def test_billing_column_name_parsing_currency_separation_and_pagination(settings, principal):
    next_url = f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01&$skiptoken=two"
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/forecast"):
            return httpx.Response(200, json=forecast_page([
                ["Actual", "USD", 10, 20261003], ["Forecast", "USD", 20, 20261031],
                ["Actual", "EUR", 3, 20261003], ["Forecast", "EUR", 7, 20261031],
            ]))
        if "$skiptoken=two" in str(request.url):
            return httpx.Response(200, json=actual_page(
                [[8, "EUR", "VM", 20261003], [5, "USD", "VM", 20261003]],
                columns=[{"name": name} for name in ("Cost", "Currency", "ServiceName", "UsageDate")],
            ))
        return httpx.Response(200, json=actual_page(
            [["USD", 20261003, "Search", 2], ["EUR", 20261003, "Search", 1]], next_url,
        ))
    data, _ = run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    assert data["actual_mtd"]["totals_by_currency"] == {"EUR": "9", "USD": "7"}
    assert data["azure_forecast_full_month"]["totals_by_currency"] == {"EUR": "10", "USD": "30"}
    assert len(seen) == 3 and all(request.method == "POST" for request in seen)
    assert json.loads(seen[0].content) == json.loads(seen[1].content)


@pytest.mark.parametrize("url", [
    "https://attacker.test/page", "http://management.azure.com/page",
    f"{ARM}{COMMON_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01",
    f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/forecast?api-version=2025-03-01",
    f"https://user@management.azure.com{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01",
    f"{ARM}:444{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01",
    f"{ARM}:bad{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01",
    f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=x&scope=other",
])
def test_arm_pagination_cannot_leak_token_off_host_or_scope(settings, principal, url):
    fake = FakeAzure(actual=actual_page(next_link=url))
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "unsafe_cost_pagination"
    assert len(fake.requests) == 1


def test_redirects_not_followed(settings, principal):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.test/steal"})
    with pytest.raises(ToolError) as error:
        run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "cost_service_unavailable" and len(seen) == 1


def test_bounded_pagination_does_not_publish_partial_totals(settings, principal):
    next_url = f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01&$skiptoken=two"
    fake = FakeAzure(actual=actual_page(next_link=next_url))
    with pytest.raises(ToolError) as error:
        run(configure(settings, max_pages=1), principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "cost_pagination_limit" and len(fake.requests) == 1


def test_cycle_rejected(settings, principal):
    initial = f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01"
    fake = FakeAzure(actual=actual_page(next_link=initial))
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "cost_pagination_cycle" and len(fake.requests) == 1


def test_retail_pagination_same_dimensions_and_no_bearer_token(settings, principal):
    fake = FakeAzure()
    retail_requests = []
    def handler(request):
        if request.url.host != "prices.azure.com":
            return fake(request)
        retail_requests.append(request)
        assert "authorization" not in request.headers
        if len(retail_requests) == 1:
            return httpx.Response(200, json={"Items": [], "NextPageLink": str(request.url) + "&$skip=100"})
        return httpx.Response(200, json={"Items": [price_item()], "NextPageLink": None})
    data, _ = run(settings, principal, handler)
    assert data["idle_baseline"]["priced_fixed_subtotal"] == "73.0" and len(retail_requests) == 2


def test_retail_changed_filters_fail_without_estimate_fallback(settings, principal):
    fake = FakeAzure()
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host != "prices.azure.com":
            return fake(request)
        query = parse_qs(request.url.query.decode())
        query["currencyCode"] = ["'EUR'"]
        next_url = RETAIL + "?" + urlencode({key: values[0] for key, values in query.items()}) + "&$skip=100"
        return httpx.Response(200, json={"Items": [price_item()], "NextPageLink": next_url})
    with pytest.raises(ToolError) as error:
        run(settings, principal, handler)
    assert error.value.code == "unsafe_cost_pagination"
    assert len([request for request in seen if request.url.host == "prices.azure.com"]) == 1


@pytest.mark.parametrize("rows", [
    [["USD", 20261003, "Search", "NaN"]],
    [["XYZ", 20261003, "Search", 2]],
    [["USD", 20261101, "Search", 2]],
    [["USD", 20261003]],
])
def test_malformed_billing_fails_closed(settings, principal, rows):
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(actual=actual_page(rows)), COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_response"


def test_forecast_unknown_status_or_out_of_month_is_not_combined(settings, principal):
    for rows in ([["FreshPartial", "USD", 20, 20261003]], [["Forecast", "USD", 30, 20261101]]):
        with pytest.raises(ToolError) as error:
            run(settings, principal, FakeAzure(forecast=forecast_page(rows)), COST_SKILLS[2], {"resource_group": RG})
        assert error.value.code == "invalid_cost_response"


def test_credentials_are_lazy_and_config_credential_is_used(settings, principal, monkeypatch):
    cred = FakeCredential()
    monkeypatch.setattr("aifactory_agent.config.credential", lambda _: cred)
    fake = FakeAzure()
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        skills = CostSkills(settings, principal, SCOPE, http_client=client, clock=lambda: NOW)
        assert not cred.scopes
        skills.execute(COST_SKILLS[2], {"resource_group": RG})
    assert set(cred.scopes) == {ARM + "/.default"}


def test_credential_and_transport_errors_are_redacted_blockers(settings, principal):
    class BadCredential:
        def get_token(self, _):
            raise ClientAuthenticationError("secret token value must never be returned")
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(), COST_SKILLS[2], {"resource_group": RG}, cred=BadCredential())
    assert error.value.code == "cost_auth_unavailable" and "secret" not in str(error.value)
    def handler(request):
        raise httpx.ConnectError("secret endpoint diagnostic", request=request)
    with pytest.raises(ToolError) as error:
        run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "cost_service_unavailable" and "secret" not in str(error.value)


def test_non_utc_clock_is_normalized_and_naive_clock_rejected(settings, principal):
    fake = FakeAzure()
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        skills = CostSkills(settings, principal, SCOPE, FakeCredential(), client, clock=lambda: datetime(2026, 10, 3))
        with pytest.raises(ToolError) as error:
            skills.execute(COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_clock" and not fake.requests


def test_canonical_inventory_covers_every_enabled_default_billable_service():
    document = json.loads((REPO / DEFAULT_VARIABLES_RELATIVE_PATH).read_text(encoding="utf-8-sig"))
    rows = template_components(document, "dev")
    services = {row.service for row in rows}
    assert {
        "project-storage", "search-storage", "key-vault", "project-identities",
        "private-networking", "shared-common-dependencies", "ai-search", "cosmos-db",
        "enableApplicationInsights", "bot-service", "foundry", "foundry-default-project",
        "foundry-capability-host", "foundry-network-injection", "deployModel_gpt_X",
        "deployModel_text_embedding_3_large",
    } == services
    assert not any(row.service == "container-registry" for row in rows)


@pytest.mark.parametrize("value", [True, -1, "1.5", 1.5, 1000001, "NaN"])
def test_fractional_or_invalid_search_counts_are_unpriced(settings, principal, monkeypatch, value):
    monkeypatch.setattr(CostSkills, "_template", lambda _: (
        {"dev": {"admin_location": "eastus2", "enableAISearch": True, "skuAISearchDev": "basic",
                 "aiSearchReplicaCount": value, "aiSearchPartitionCount": 3}}, {},
    ))
    fake = FakeAzure()
    data, _ = run(settings, principal, fake)
    search = next(row for row in data["idle_baseline"]["components"] if row["service"] == "ai-search")
    assert search["estimate"]["monthly"] is None and search["provisioned_quantity"] is None
    assert not any(request.url.host == "prices.azure.com" for request in fake.requests)


def test_forecast_accepts_iso_date_rows_from_azure(settings, principal):
    fake = FakeAzure(forecast=forecast_page([
        ["Actual", "USD", 20, "2026-10-03"], ["Forecast", "USD", 30, "2026-10-31"],
    ]))
    data, _ = run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert data["azure_forecast_full_month"]["totals_by_currency"] == {"USD": "50"}


@pytest.mark.parametrize("rows", [
    [["Actual", "USD", 20, 20261003], ["Forecast", "USD", 30, 20261003]],
    [["Actual", "USD", 20, 20261031], ["Forecast", "USD", 30, 20261031]],
    [["Actual", "USD", 20, 20261003], ["Forecast", "USD", 30, 20261002]],
    [["Actual", "USD", 10, 20261001], ["Forecast", "USD", 30, 20261002],
     ["Actual", "USD", 10, 20261003]],
    [["Actual", "USD", 20, 20261003], ["Forecast", "USD", 30, 20261031],
     ["Forecast", "USD", 30, 20261031]],
    [["Actual", "USD", 20, 20261001], ["ActualCost", "USD", 20, "2026-10-01"],
     ["Forecast", "USD", 30, 20261002]],
])
def test_forecast_rejects_duplicate_or_overlapping_daily_charges(settings, principal, rows):
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(forecast=forecast_page(rows)), COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_response"


@pytest.mark.parametrize("first_rows,last_rows", [
    ([["Actual", "USD", 10, 20261001], ["Forecast", "USD", 30, 20261002]],
     [["Actual", "USD", 10, 20261003]]),
    ([["Forecast", "USD", 30, 20261002]], [["Actual", "USD", 20, 20261003]]),
    ([["Actual", "USD", 20, 20261001], ["Forecast", "USD", 30, 20261002]],
     [["Forecast", "USD", 30, "2026-10-02"]]),
    ([["Actual", "USD", 20, 20261001], ["Forecast", "USD", 30, 20261002]],
     [["ActualCost", "USD", 20, "2026-10-01"]]),
    ([["Actual", "USD", 20, 20261003]], [["Forecast", "USD", 30, "2026-10-03"]]),
])
def test_forecast_rejects_overlap_or_duplicate_currency_dates_across_pages(
        settings, principal, first_rows, last_rows):
    next_url = f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/forecast?api-version=2025-03-01&$skiptoken=two"
    fake = FakeAzure()

    def handler(request):
        if not request.url.path.endswith("/forecast"):
            return fake(request)
        rows, continuation = (last_rows, None) if "$skiptoken=two" in str(request.url) else (first_rows, next_url)
        return httpx.Response(200, json=forecast_page(rows, continuation))

    with pytest.raises(ToolError) as error:
        run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_response"


@pytest.mark.parametrize("forecast_response", [False, True])
def test_billing_rejects_actual_dates_after_observation(settings, principal, forecast_response):
    fake = (
        FakeAzure(forecast=forecast_page([
            ["Actual", "USD", 20, 20261004], ["Forecast", "USD", 30, 20261031],
        ]))
        if forecast_response else FakeAzure(actual=actual_page([["USD", 20261004, "Search", 2]]))
    )
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_response"


@pytest.mark.parametrize("response", [
    forecast_page([["Unknown", "USD", 20, 20261001], ["Forecast", "USD", 30, 20261002]]),
    forecast_page([[None, "USD", 20, 20261001], ["Forecast", "USD", 30, 20261002]]),
    forecast_page([["Actual", "USD", 20, None], ["Forecast", "USD", 30, 20261002]]),
    forecast_page(
        [["USD", 20, 20261001]],
        columns=[{"name": name} for name in ("Currency", "Cost", "UsageDate")],
    ),
])
def test_forecast_billing_lag_does_not_infer_missing_status_or_dates(settings, principal, response):
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(forecast=response), COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_response"


@pytest.mark.parametrize("rows", [
    [["Forecast", "USD", 30, 20261031]],
    [["Actual", "USD", 20, 20261003], ["Forecast", "EUR", 30, 20261031]],
    [["Actual", "USD", 20, 20261001], ["Forecast", "USD", 30, 20261002],
     ["Forecast", "EUR", 30, 20261002]],
    [["Actual", "USD", 20, 20261001], ["Actual", "EUR", 20, 20261001],
     ["Forecast", "USD", 30, 20261002]],
])
def test_forecast_missing_actual_or_currency_partition_does_not_claim_full_month(settings, principal, rows):
    with pytest.raises(ToolError) as error:
        run(settings, principal, FakeAzure(forecast=forecast_page(rows)), COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "forecast_unavailable"


def test_actual_duplicate_daily_group_across_pages_is_not_summed(settings, principal):
    fake = FakeAzure(actual=actual_page(next_link=(
        f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=2025-03-01&$skiptoken=two"
    )))
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "invalid_cost_response" and len(fake.requests) == 2


@pytest.mark.parametrize("next_link", [False, 0, [], {}])
def test_malformed_continuation_is_not_treated_as_end_of_data(settings, principal, next_link):
    fake = FakeAzure(actual=actual_page(next_link=next_link))
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "unsafe_cost_pagination" and len(fake.requests) == 1


def test_arm_continuation_cannot_switch_api_version(settings, principal):
    fake = FakeAzure(actual=actual_page(next_link=(
        f"{ARM}{PROJECT_PATH}/providers/Microsoft.CostManagement/query?api-version=old&$skiptoken=two"
    )))
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "unsafe_cost_pagination" and len(fake.requests) == 1


@pytest.mark.parametrize("host", ["prices.azure.com", "management.azure.com"])
@pytest.mark.parametrize("status", [403, 429, 503])
def test_inventory_and_retail_errors_are_surfaced_not_swallowed(settings, principal, host, status):
    fake = FakeAzure()
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host == host and not request.url.path.endswith(("/query", "/resources")):
            return httpx.Response(status, text="secret response diagnostic")
        return fake(request)
    skill = COST_SKILLS[0] if host == "prices.azure.com" else COST_SKILLS[1]
    arguments = {} if host == "prices.azure.com" else {"resource_group": COMMON}
    with pytest.raises(ToolError) as error:
        run(settings, principal, handler, skill, arguments)
    assert error.value.code == ("cost_access_denied" if status == 403 else "cost_service_unavailable")
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_streaming_response_is_bounded_and_closed(settings, principal):
    class LargeBody(httpx.SyncByteStream):
        def __init__(self):
            self.chunks = 0
            self.closed = False
        def __iter__(self):
            for _ in range(100):
                self.chunks += 1
                yield b" " * 65536
        def close(self):
            self.closed = True
    stream = LargeBody()
    def handler(request):
        return httpx.Response(200, stream=stream)
    with pytest.raises(ToolError) as error:
        run(settings, principal, handler, COST_SKILLS[2], {"resource_group": RG})
    assert error.value.code == "cost_response_limit"
    assert stream.closed and stream.chunks < 100


def test_programming_errors_are_not_broadly_caught_as_price_or_auth_unavailability(settings, principal):
    class BrokenCredential:
        def get_token(self, _):
            raise RuntimeError("internal programming error")
    with pytest.raises(RuntimeError, match="internal programming error"):
        run(settings, principal, FakeAzure(), COST_SKILLS[2], {"resource_group": RG}, cred=BrokenCredential())


def test_models_use_repository_names_versions_and_only_applicable_accounts(settings, principal, monkeypatch):
    raw = {"dev": {
        "admin_location": "eastus2", "enableAIFoundry": True, "enableAIServices": True,
        "enableAzureOpenAI": True, "deployModel_gpt_X": True,
        "modelGPTXName": "canonical-custom-model", "modelGPTXVersion": "2026-10-01",
        "modelGPTXSku": "GlobalStandard", "modelGPTXCapacity": 50,
        "deployModel_gpt_54_mini": True, "default_model_sku": "GlobalStandard",
        "deployModel_gpt_4o": True, "deployModel_text_embedding_3_large": True,
    }}
    monkeypatch.setattr(CostSkills, "_template", lambda _: (raw, {}))
    data, _ = run(settings, principal, FakeAzure())
    rows = {row["service"]: row for row in data["idle_baseline"]["components"]}
    custom = rows["deployModel_gpt_X"]
    assert custom["dimensions"] == {
        "model_name": "canonical-custom-model",
        "model_versions_by_account": {"foundry": "2026-10-01", "ai-services": "2026-10-01"},
        "account_types": ["foundry", "ai-services"], "quota_capacity": 50,
    }
    assert custom["sku"] == "GlobalStandard" and custom["provisioned_quantity"] == "2"
    assert custom["dimensions"]["model_name"] != settings.azure.model_name
    assert rows["deployModel_gpt_54_mini"]["sku"] == "DataZoneStandard"
    assert rows["deployModel_gpt_4o"]["dimensions"]["account_types"] == ["foundry"]
    assert rows["deployModel_gpt_4o"]["provisioned_quantity"] == "1"
    assert rows["deployModel_text_embedding_3_large"]["dimensions"]["model_versions_by_account"] == {
        "foundry": "1", "ai-services": None,
    }
    assert rows["openai-default-embedding"]["sku"] == "Standard"
    assert rows["openai-default-embedding"]["dimensions"]["quota_capacity"] == 25
    assert all(row["estimate"]["monthly"] is None for name, row in rows.items()
               if "deployModel" in name or name == "openai-default-embedding")


def test_unapplied_model_flag_is_visible_without_inventing_an_account():
    rows = template_components({"dev": {"admin_location": "eastus2", "deployModel_gpt_X": True}}, "dev")
    row = next(row for row in rows if row.service == "deployModel_gpt_X")
    assert row.quantity is None and row.dimensions["account_types"] == []


@pytest.mark.parametrize("unit,factor", [("1 Hour", 730), ("1 Month", 1), ("1/Month", 1)])
def test_exact_vm_meter_os_and_monthly_units(settings, principal, unit, factor):
    vm = resource("Microsoft.Compute/virtualMachines", "vm", sku=None, properties={
        "hardwareProfile": {"vmSize": "Standard_D2as_v5"},
        "storageProfile": {"osDisk": {"osType": "Windows"}},
    })
    fake = FakeAzure(resources=[vm], items=[
        price_item(serviceName="Virtual Machines", skuName="D2as v5", armSkuName="Standard_D2as_v5",
                   productName="Virtual Machines Dasv5 Series Windows", meterName="D2as v5",
                   meterId="windows-meter", unitOfMeasure=unit, retailPrice=2),
        price_item(serviceName="Virtual Machines", skuName="D2as v5", armSkuName="Standard_D2as_v5",
                   productName="Virtual Machines Dasv5 Series", meterName="D2as v5",
                   meterId="linux-meter", retailPrice=1),
        price_item(serviceName="Virtual Machines", skuName="D2as v5", armSkuName="Standard_D2as_v5",
                   productName="Virtual Machines Dasv5 Series Windows", meterName="D2as v5 Spot",
                   meterId="spot-meter", retailPrice=0.01),
    ])
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    vm_row = data["idle_baseline"]["components"][0]
    assert vm_row["estimate"]["monthly"] == str(2 * factor)
    assert vm_row["estimate"]["rate"]["meter_id"] == "windows-meter"


def test_webapp_capacity_and_private_endpoint_meter_dimensions(settings, principal):
    plan = resource("Microsoft.Web/serverfarms", "plan", sku={"name": "P1v3", "capacity": 3},
                    properties={"reserved": True})
    endpoint = resource("Microsoft.Network/privateEndpoints", "private", sku=None)
    fake = FakeAzure(resources=[plan, endpoint], items=[
        price_item(serviceName="Azure App Service", skuName="P1 v3", productName="Azure App Service Premium v3 Plan - Linux",
                   meterName="P1 v3", meterId="linux-plan", retailPrice=0.2),
        price_item(serviceName="Azure App Service", skuName="P1 v3", productName="Azure App Service Premium v3 Plan - Windows",
                   meterName="P1 v3", meterId="windows-plan", retailPrice=0.5),
        price_item(serviceName="Azure Private Link", skuName="Standard", productName="Azure Private Link",
                   meterName="Standard Private Endpoint", meterId="private-endpoint", retailPrice=0.01),
        price_item(serviceName="Azure Private Link", skuName="Standard", productName="Azure Private Link",
                   meterName="Data Processed", meterId="private-data", retailPrice=0.01, unitOfMeasure="1 GB"),
    ])
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    rows = {row["service"]: row for row in data["idle_baseline"]["components"]}
    assert rows["web-app-plan"]["estimate"]["monthly"] == "438.0"
    assert rows["private-endpoint"]["estimate"]["monthly"] == "7.30"
    assert not data["idle_baseline"]["complete"] and data["idle_baseline"]["total_monthly"] is None


@pytest.mark.parametrize("name", [None, [], {}, 123, "/unknown"])
def test_unknown_or_nonliteral_skill_name_is_a_structured_error(settings, principal, name):
    fake = FakeAzure()
    with pytest.raises(ToolError) as error:
        run(settings, principal, fake, name)
    assert error.value.code == "unknown_skill" and not fake.requests


def test_no_credentials_telemetry_configuration_or_console_output(settings, principal, capsys):
    current = settings.model_copy(update={"azure": settings.azure.model_copy(update={
        "application_insights_connection_string": "private-telemetry-connection",
        "managed_identity_client_id": "private-identity-configuration",
    })})
    data, _ = run(current, principal, FakeAzure())
    serialized = json.dumps(data)
    assert "test-arm-token-never-retail" not in serialized
    assert "private-telemetry-connection" not in serialized
    assert "private-identity-configuration" not in serialized
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("base,override,expected", [(False, True, False), (True, False, True)])
def test_dedicated_registry_uses_deployment_override(base, override, expected):
    rows = template_components({"dev": {"useCommonACR": base, "useCommonACR_override": override}}, "dev")
    assert any(row.service == "container-registry" for row in rows) is expected


def test_private_foundry_requires_capability_host_even_when_optional_flag_is_off():
    rows = template_components({"dev": {
        "enableAIFoundry": True, "enablePublicGenAIAccess": False, "enableAFoundryCaphost": False,
    }}, "dev")
    assert any(row.service == "foundry-capability-host" for row in rows)


def test_retail_non_usd_uses_documented_currency_code(settings, principal):
    configured = configure(settings, currency="EUR")
    fake = FakeAzure(items=[price_item(currencyCode="EUR")])
    data, _ = run(configured, principal, fake)
    requests = [item for item in fake.requests if item.url.host == "prices.azure.com"]
    assert requests and all(item.url.params["currencyCode"] == "'EUR'" for item in requests)
    assert "currency" not in requests[0].url.params
    search = next(row for row in data["idle_baseline"]["components"] if row["service"] == "ai-search")
    assert search["estimate"]["currency"] == "EUR" and search["estimate"]["monthly"] is not None


def test_common_inventory_accepts_valid_action_group_name_with_spaces(settings, principal):
    fake = FakeAzure(resources=[resource("Microsoft.Insights/actionGroups", "Operations alerts")])
    data, _ = run(settings, principal, fake, COST_SKILLS[1], {"resource_group": COMMON})
    rows = data["idle_baseline"]["components"]
    assert len(rows) == 1
    assert rows[0]["estimate"]["monthly"] is None
