"""Read-only ARM billing analytics and explicitly partial public-retail idle estimates."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


ARM = "https://management.azure.com"
RETAIL = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2025-03-01"
HOURS = Decimal(730)
DEFAULT_VARIABLES_RELATIVE_PATH = Path("environment_setup") / "aifactory" / "variables.json"
DEFAULT_VARIABLES_SHA256 = "c753b65634f80e9dc4f55323fb917448e3f57c11311e73bad6f09b748e4f3ec6"
COST_SKILLS = (
    "/get-default-project-estimated-azure-idle-running-cost",
    "/get-aifactory-common-estimated-azure-idle-running-cost",
    "/get-monthtly-forecasted-project-estimated-azure-cost",
)
COST_TOOL_TO_SKILL = {
    "cost_default_project_idle": COST_SKILLS[0],
    "cost_common_idle": COST_SKILLS[1],
    "cost_monthly_project_forecast": COST_SKILLS[2],
}
_MONTHLY_ALIAS = "/get-monthly-forecasted-project-estimated-azure-cost"
_CURRENCIES = frozenset(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB "
    "BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP "
    "DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF "
    "IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK "
    "LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN "
    "NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF "
    "SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND "
    "TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF "
    "YER ZAR ZMW ZWG".split()
)
_RG = r"^[A-Za-z0-9_.()-]{1,90}$"
_MAX_BYTES = 2_000_000
_MAX_ITEMS = 2000


def _fail(code, message, status=409):
    # Lazy imports let config.Settings import CostSettings without a config/tools cycle.
    from .tools import ToolError
    raise ToolError(code, message, status) from None


class CostSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    default_variables_path: Path | None = None
    default_variables_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    common_resource_groups: dict[str, list[str]] = Field(default_factory=dict, max_length=100)
    currency: str = "USD"
    max_pages: int = Field(default=5, ge=1, le=20, strict=True)

    @field_validator("currency")
    @classmethod
    def iso_currency(cls, value):
        if value not in _CURRENCIES:
            raise ValueError("Use an uppercase ISO 4217 currency code.")
        return value

    @field_validator("common_resource_groups")
    @classmethod
    def exact_common_groups(cls, value):
        for scope, groups in value.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", scope):
                raise ValueError("Common resource groups must be keyed by an exact scope key.")
            if not 1 <= len(groups) <= 20 or any(not re.fullmatch(_RG, group) for group in groups):
                raise ValueError("Configure between one and twenty literal resource-group names per scope.")
            if len({group.casefold() for group in groups}) != len(groups):
                raise ValueError("Duplicate common resource groups are not allowed.")
        return value


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RGArguments(NoArguments):
    resource_group: str = Field(pattern=_RG)


def default_template_source(repository_root: Path, options: CostSettings) -> tuple[Path, str]:
    path = options.default_variables_path
    if path is None:
        return repository_root / DEFAULT_VARIABLES_RELATIVE_PATH, options.default_variables_sha256 or DEFAULT_VARIABLES_SHA256
    if not options.default_variables_sha256:
        _fail("cost_template_unpinned", "A configured default template requires its trusted SHA-256 pin.", 503)
    return (path if path.is_absolute() else repository_root / path), options.default_variables_sha256


def _skill(name):
    if not isinstance(name, str):
        _fail("unknown_skill", "Unknown cost skill.", 400)
    name = COST_TOOL_TO_SKILL.get(name, name)
    if not name.startswith("/"):
        name = "/" + name
    if name == _MONTHLY_ALIAS:
        name = COST_SKILLS[2]
    if name not in COST_SKILLS:
        _fail("unknown_skill", "Unknown cost skill.", 400)
    return name


def argument_model(skill_name):
    return NoArguments if _skill(skill_name) == COST_SKILLS[0] else RGArguments


def cost_descriptors():
    descriptions = (
        "Estimate enabled canonical default project SKUs at public retail prices (730 hours); "
        "show gaps and separate actual MTD billing for the exact configured project.",
        "Discover deployed resources in one explicitly allowed common resource group; "
        "estimate provisioned idle fixed components and separately report actual MTD billing.",
        "Read Azure Cost Management actual MTD and Azure's full-month forecast for the exact "
        "configured project resource group. Never extrapolate or add actual costs twice.",
    )
    result = []
    for (name, skill), description in zip(COST_TOOL_TO_SKILL.items(), descriptions):
        schema = argument_model(skill).model_json_schema()
        schema.setdefault("required", [])
        result.append({"type": "function", "name": name, "description": description,
                       "parameters": schema, "strict": True})
    return result


def _decimal(value, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Not a numeric amount.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Not a numeric amount.") from None
    if not number.is_finite() or abs(number) > Decimal("1e15") or (nonnegative and number < 0):
        raise ValueError("Invalid amount.")
    return number


def _quantity(value):
    try:
        result = _decimal(value, nonnegative=True)
        return result if result <= 1000000 and result == result.to_integral_value() else None
    except ValueError:
        return None


def _on(value):
    return value is True or (type(value) in (str, int) and str(value).lower() in {"true", "1", "yes"})


def _dimension(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_. /()-]{1,120}", value) else None


@dataclass(frozen=True)
class RateSelector:
    service: str
    sku: str
    sku_field: str = "skuName"
    meters: tuple[str, ...] = ()
    product: str | None = None
    os: str | None = None


def _selector(service, sku, os=None):
    if not _dimension(sku):
        return None
    if service == "ai-search":
        labels = {
            "basic": ("Basic", ("Basic Search Unit", "Basic Unit")),
            "standard": ("Standard", ("Standard Search Unit", "S1 Search Unit")),
            "standard2": ("Standard S2", ("S2 Search Unit", "Standard S2 Search Unit")),
            "standard3": ("Standard S3", ("S3 Search Unit", "Standard S3 Search Unit")),
            "storage_optimized_l1": ("Storage Optimized L1", ("L1 Search Unit",)),
            "storage_optimized_l2": ("Storage Optimized L2", ("L2 Search Unit",)),
        }
        if sku.lower() in labels:
            label, meters = labels[sku.lower()]
            return RateSelector("Azure Cognitive Search", label, meters=meters)
    if service == "container-registry" and sku in {"Basic", "Standard", "Premium"}:
        return RateSelector("Container Registry", sku, meters=(f"{sku} Registry Unit",))
    if service in {"virtual-machine", "aks-nodes"} and sku.startswith("Standard_") and os in {"Linux", "Windows"}:
        return RateSelector("Virtual Machines", sku, "armSkuName", os=os)
    if service == "web-app-plan" and sku in {"P0v3", "P1v3", "P2v3", "P3v3"} and os in {"Linux", "Windows"}:
        label = sku[:-2] + " v3"
        return RateSelector("Azure App Service", label, meters=(label,),
                            product=f"Azure App Service Premium v3 Plan - {os}")
    if service == "private-endpoint":
        return RateSelector("Azure Private Link", "Standard",
                            meters=("Standard Private Endpoint", "Private Endpoint"))
    return None


@dataclass
class Component:
    service: str
    sku: str | None
    region: str | None
    quantity: Decimal | None = Decimal(1)
    usage: str = ""
    assumption: str = ""
    selector: RateSelector | None = None
    resource_id: str | None = None
    fixed_expected: bool = False
    dimensions: dict | None = None


# Inventory follows the repository's project Bicep defaults without private pricing catalogs.
_FEATURES = (
    ("enableAIServices", "ai-services", "AIServices", "S0", "API transactions"),
    ("enableAzureOpenAI", "openai", "OpenAI", "S0", "model input/output tokens; provisioned throughput if configured"),
    ("enableContentSafety", "content-safety", "ContentSafety", "S0", "text/image transactions"),
    ("enableAzureAIVision", "vision", "Vision", "S1", "image/video transactions"),
    ("enableAzureSpeech", "speech", "Speech", "S0", "audio hours; characters"),
    ("enableAIDocIntelligence", "document-intelligence", "DocIntelligence", "S0", "document pages by model"),
    ("enablePostgreSQL", "postgresql", "PostgreSQL", "Standard_B1ms", "32 GiB provisioned storage; backups; IOPS"),
    ("enableRedisCache", "redis", "Redis", "Standard", "capacity 2; replica/shard-specific cache meters"),
    ("enableSQLDatabase", "sql-database", "SQLDatabase", "S0", "database compute; storage; backups; replicas"),
    ("enableElasticsearch", "elasticsearch", "Elastic", "ess-consumption-2024_Monthly", "marketplace deployment size; storage"),
    ("enableWebApp", "web-app-plan", "WebApp", "P1v3", "scale-out; bandwidth"),
    ("enableFunction", "function-plan", "Function", "EP1", "premium minimum vCPU/GiB hours; executions; scale-out"),
    ("enableContainerApps", "container-apps", "ContainerApps", "Consumption", "minimum replicas; vCPU/GiB seconds; requests; workload profiles"),
    ("enableAzureMachineLearning", "machine-learning", "AzureML", "basic", "compute; endpoints; node disks"),
    ("enableDatabricks", "databricks", "Databricks", "premium", "DBUs plus driver/worker VM hours; disks; serverless usage"),
    ("enableDatafactory", "data-factory", None, None, "activity runs; integration runtime; data movement"),
    ("enableLogicApps", "logic-apps-plan", "LogicApps", "WS1", "plan compute; connector actions"),
    ("enableEventHubs", "event-hubs", "EventHubs", "Basic", "throughput units; ingress; retention; capture"),
    ("enableBotService", "bot-service", "BotService", "S1", "premium channel messages"),
    ("enableAIFoundryHub", "foundry-hub", None, None, "hub compute; endpoints; associated storage"),
)
_MODELS = (
    "deployModel_gpt_X", "deployModel_gpt_54_mini", "deployModel_gpt_4o",
    "deployModel_text_embedding_ada_002", "deployModel_text_embedding_3_large",
    "deployModel_text_embedding_3_small",
)
_KNOWN_FLAGS = frozenset({
    "enablePublicGenAIAccess", "enablePublicAccessWithPerimeter", "enableDeleteForDisabledResources",
    "enableAIFactoryCreatedDefaultProjectForAIFv2", "enableAppInsightsDashboard", "enableApplicationInsights",
    "enableAFoundryCaphost", "enableAISearchSharedPrivateLink", "enableRetries", "enableDebugging",
    "enableLogAnalyticsQueries", "enableDatafactoryLinkedServices", "enableDatafactoryManagedVnet",
    "enableLogicAppSystemMiRoleAssignment", "enableAIFactoryHub", "enableAMPLS", "enableAksForAzureML",
    "enableAKS", "enableAISearch", "enableCosmosDB", "enableAIFoundry", "enableProjectVM",
    "enableAdminVM", "enableDatafactoryCommon", "enableBing", "enableBingCustomSearch",
    "enableDefenderforAISubLevel", "enableDefenderforAIResourceLevel", "ENABLE_APIM", "ENABLE_KONG",
}) | {feature[0] for feature in _FEATURES} | set(_MODELS)


def template_components(document, environment):
    """Select canonical defaults; candidate SKU arrays are alternatives, not replicas."""
    if not isinstance(document, dict) or not isinstance(document.get("dev"), dict):
        _fail("invalid_cost_template", "The canonical variables template must contain a dev defaults object.", 503)
    env = "test" if environment == "stage" else environment
    if env not in {"dev", "test", "prod"}:
        _fail("invalid_cost_template", "The canonical cost environment must be dev, stage/test, or prod.", 503)
    values = {**document["dev"], **document.get(env, {})} if isinstance(document.get(env, {}), dict) else None
    if values is None:
        _fail("invalid_cost_template", "The canonical environment defaults are malformed.", 503)
    suffix = "Dev" if env == "dev" else "StageProd"
    region = values.get("admin_location")
    region = region if isinstance(region, str) and re.fullmatch(r"[a-z0-9]{2,40}", region) else None
    selected = lambda stem, default: _dimension(values.get("sku" + stem + suffix) or default)
    rows = []

    def add(service, sku=None, *, quantity=1, usage="", assumption="", location=None, fixed=False,
            os=None, dimensions=None):
        actual_region = location or region
        actual_region = actual_region if isinstance(actual_region, str) and re.fullmatch(r"[a-z0-9]{2,40}", actual_region) else None
        rows.append(Component(service, _dimension(sku), actual_region, _quantity(quantity), usage, assumption,
                              _selector(service, sku, os), fixed_expected=fixed, dimensions=dimensions))

    for service in ("project-storage", "search-storage"):
        add(service, selected("StorageAccount", "Standard_LRS"),
            usage="stored GiB-month; reads/writes; snapshots; replication; egress",
            assumption="03-cognitive-services creates search storage independently of enableAISearch."
            if service == "search-storage" else "02-core-infrastructure project storage.")
    add("key-vault", "Standard", usage="operations; certificates; key types")
    add("project-identities", quantity=2, usage="control-plane identities; no separate compute meter",
        assumption="Foundation creates project and container-app managed identities; not a complete workload bill.")
    add("private-networking", usage="private endpoint hours; processed GB; DNS zones/queries; peering/egress",
        fixed=True, assumption="Endpoint counts and reused DNS resources are not inferred from feature flags.")
    add("shared-common-dependencies", usage="common ACR; Log Analytics; shared network/storage; Defender allocations",
        assumption="Shared infrastructure is not charged once per project; query an explicitly configured common RG separately.")
    if not _on(values.get("useCommonACR_override", values.get("useCommonACR", True))):
        add("container-registry", values.get("acr_SKU", "Premium"), fixed=True,
            usage="stored GiB; builds; geo-replication; transfer")
    for flag in ("enableApplicationInsights", "enableAppInsightsDashboard"):
        if _on(values.get(flag)):
            add(flag, usage="telemetry ingestion/retention in shared Log Analytics; not counted twice")
    private_foundry = _on(values.get("enableAIFoundry")) and not _on(values.get("enablePublicGenAIAccess"))
    if _on(values.get("enableAISearch")) or private_foundry:
        replicas = _quantity(values.get("aiSearchReplicaCount", 1))
        partitions = _quantity(values.get("aiSearchPartitionCount", 1))
        units = replicas * partitions if replicas is not None and partitions is not None else None
        add("ai-search", selected("AISearch", "standard"), quantity=units,
            location=values.get("aiSearchLocation"), fixed=True,
            usage="semantic queries; vectorization tokens; enrichment",
            assumption="Search units = replicas × partitions; private Foundry requires Search even if its switch is off.",
            dimensions={"replicas": str(replicas) if replicas is not None else None,
                        "partitions": str(partitions) if partitions is not None else None})
    if _on(values.get("enableCosmosDB")) or private_foundry:
        add("cosmos-db", "Serverless", usage="request units; indexed/stored GiB-month; backups; replication",
            assumption="Private Foundry requires Cosmos DB even if its optional switch is off.")
    shared_plan = bool(values.get("byoAseAppServicePlanResourceId"))
    for flag, service, stem, default, usage in _FEATURES:
        if not _on(values.get(flag)):
            continue
        sku = selected(stem, default) if stem else None
        quantity, os, assumption = 1, None, ""
        fixed = service in {"postgresql", "redis", "sql-database", "web-app-plan",
                            "function-plan", "logic-apps-plan", "event-hubs", "elasticsearch"}
        dimensions = {}
        tiers = {"PostgreSQL": "Burstable", "SQLDatabase": "Standard",
                 "WebApp": "PremiumV3", "Function": "ElasticPremium"}
        if stem in tiers:
            dimensions["tier"] = selected("Tier" + stem, tiers[stem])
        if service == "redis":
            dimensions["capacity"] = 2
        if service == "web-app-plan":
            os = {"python": "Linux", "node": "Linux", "dotnet": "Windows"}.get(values.get("webAppRuntime", "python"))
        if service in {"web-app-plan", "function-plan"} and _on(values.get("byoASEv3")):
            sku, quantity, os = _dimension(values.get("aseSkuCode", "I1v2")), values.get("aseSkuWorkers", 1), None
            dimensions["tier"] = _dimension(values.get("aseSku", "IsolatedV2"))
            assumption = "ASE workers are provisioned; exact isolated-plan/ASE overhead meters require review."
        if service in {"web-app-plan", "function-plan", "logic-apps-plan"} and shared_plan:
            os, fixed = None, False
            assumption = "Existing shared App Service plan: SKU/OS/worker count require discovery; do not charge per app."
        if service == "logic-apps-plan":
            dimensions["workflow_type"] = _dimension(values.get("logiAppType", "Standard"))
            assumption = "Integration Bicep creates a plan even for Consumption when no existing plan is supplied."
        if service == "container-apps":
            assumption = "Candidate arrays are alternatives; minimum replicas and profile sizing are not guessed."
        add(service, sku, quantity=quantity, usage=usage, assumption=assumption, fixed=fixed, os=os,
            location=values.get("serviceSettingOverrideRegionAzureAIVision") if service == "vision" else None,
            dimensions=dimensions)
        if service == "machine-learning":
            cluster = values.get("admin_aml_cluster_sku_dev_override" if env == "dev" else "admin_aml_cluster_sku_testProd_override")
            add("aml-training-clusters", cluster or ("Standard_DS3_v2" if env == "dev" else "Standard_D4_v2"),
                quantity=1, usage="active node hours; node disks; endpoints",
                assumption="machineLearningv2 provisions one cluster per environment with minNodeCount=0; maximum nodes are not idle usage.")
    if _on(values.get("enableAIFoundry")):
        add("foundry", "S0", usage="model tokens; tools/sessions; hosted agents; evaluation",
            dimensions={"deployment_type": _dimension(str(values.get("foundryDeploymentType", "2")))})
        if _on(values.get("enableAIFactoryCreatedDefaultProjectForAIFv2", True)):
            add("foundry-default-project", usage="project workloads billed by underlying services, not a separate assumed rate")
        if _on(values.get("enableAFoundryCaphost", True)) or private_foundry:
            add("foundry-capability-host", usage="agent tools; thread/vector storage; underlying services",
                assumption="Capability-host configuration is not a measured idle workload.")
        if not _on(values.get("disableAgentNetworkInjection")):
            add("foundry-network-injection", usage="container-app environment/profiles; private endpoints; DNS",
                fixed=True, assumption="Subnet prerequisites and compute minima require deployment inspection.")
    model_defaults = {
        "deployModel_gpt_X": (values.get("modelGPTXName", "gpt-5.4-mini"), values.get("modelGPTXVersion", "2026-03-17")),
        "deployModel_gpt_54_mini": ("gpt-5.4-mini", values.get("default_gpt_54_mini_version", "2026-03-17")),
        "deployModel_gpt_4o": ("gpt-4o", values.get("default_gpt_4o_version", "2024-11-20")),
        "deployModel_text_embedding_ada_002": ("text-embedding-ada-002", "2"),
        "deployModel_text_embedding_3_large": ("text-embedding-3-large", "1"),
        "deployModel_text_embedding_3_small": ("text-embedding-3-small", "1"),
    }
    for flag in _MODELS:
        if not _on(values.get(flag)):
            continue
        custom, embedding = flag == "deployModel_gpt_X", "embedding" in flag
        targets = []
        if _on(values.get("enableAIFoundry")):
            targets.append("foundry")
        if _on(values.get("enableAIServices")) and flag != "deployModel_gpt_4o":
            targets.append("ai-services")
        model_name, version = model_defaults[flag]
        versions = {target: None if target == "ai-services" and flag in {
            "deployModel_text_embedding_3_large", "deployModel_text_embedding_3_small"
        } else _dimension(version) for target in targets}
        sku = "DataZoneStandard" if flag == "deployModel_gpt_54_mini" else values.get(
            "modelGPTXSku" if custom else "default_model_sku", "DataZoneStandard",
        )
        add(flag, sku, quantity=len(targets) if targets else None,
            usage="model/version input, cached and output tokens; provisioned throughput if selected",
            assumption="TPM capacity is quota, not token usage; only applicable Bicep accounts are counted. "
            "An unspecified AI Services embedding version requires deployment discovery."
            if targets else "The enabled model flag has no applicable enabled account in the Bicep template.",
            dimensions={"model_name": _dimension(model_name), "model_versions_by_account": versions,
                        "account_types": targets, "quota_capacity": values.get("modelGPTXCapacity", 30) if custom else
                        values.get("default_embedding_capacity", 25) if embedding else values.get("default_gpt_capacity", 40)})
    if _on(values.get("enableAzureOpenAI")):
        add("openai-default-embedding", "Standard", usage="input tokens",
            assumption="csOpenAI always deploys this embedding independently of deployModel flags; it does not apply other model flags.",
            dimensions={"model_name": "text-embedding-ada-002", "model_versions_by_account": {"openai": "2"},
                        "account_types": ["openai"], "quota_capacity": 25})
    for flag, service, sku in (("enableBing", "bing-grounding", "G1"),
                               ("enableBingCustomSearch", "bing-custom-grounding",
                                selected("Bing", values.get("bingCustomSearchSku", "G2")))):
        if _on(values.get(flag)):
            add(service, sku, location="global", usage="grounding/search transactions")
    aks = _on(values.get("enableAKS"))
    aml_aks = _on(values.get("enableAzureMachineLearning")) and _on(values.get("enableAksForAzureML"))
    if aks or aml_aks:
        add("aks-management", selected("TierAks", values.get("aksSkuTier", "Standard")) if aks else
            values.get("aksSkuTier", "Standard"), fixed=True, usage="cluster management; load balancer; IP; node disks")
        node_key = "aks_dev_nodes_override" if env == "dev" else "aks_test_prod_nodes_override"
        node_sku = selected("Aks", values.get("aks_dev_sku_override" if env == "dev" else "aks_test_prod_sku_override"))
        if not aks:
            node_key = "admin_aks_nodes_dev_override" if env == "dev" else "admin_aks_nodes_testProd_override"
            node_sku = _dimension(values.get("admin_aks_gpu_sku_dev_override" if env == "dev" else "admin_aks_gpu_sku_test_prod_override"))
        nodes = values.get(node_key, -1)
        nodes = (1 if env == "dev" else 3) if nodes in (-1, "-1") else nodes
        add("aks-nodes", node_sku or ("Standard_B4ms" if env == "dev" else "Standard_DS13-2_v2"),
            quantity=nodes, os="Linux", fixed=True, usage="OS disks; autoscale; load balancer",
            assumption="Provisioned node count, not maximum autoscale capacity; subnet prerequisites are assumed satisfied.")
    if _on(values.get("enableProjectVM")) or _on(values.get("serviceSettingDeployProjectVM")):
        add("virtual-machine", "Standard_D2as_v5", fixed=True,
            os="Linux" if _on(values.get("admin_hybridBenefit")) else "Windows",
            usage="OS/data disks; backup; network; licensing",
            assumption="02-core-infrastructure selects VM SKU index 2; Hybrid Benefit excludes supplied Windows licenses.")
    if _on(values.get("ENABLE_APIM")):
        add("api-management", values.get("apimGatewaySku", "StandardV2"),
            quantity=values.get("apimGatewaySkuCapacity", 1), fixed=True, usage="gateway units; requests; network",
            assumption="Named existing gateways need deployed SKU/region/capacity discovery." if values.get("apimGatewayServiceName") else "")
    if _on(values.get("ENABLE_KONG")):
        add("kong-gateway", usage="proxy compute; replicas; network; license", fixed=True)
    if _on(values.get("cmk")):
        add("customer-managed-keys", usage="key operations; rotation; key types; external vault allocation")
    for flag in ("enableDefenderforAISubLevel", "enableDefenderforAIResourceLevel", "enableAMPLS"):
        if _on(values.get(flag)):
            add(flag, usage="protected resources/tokens; or Monitor private endpoints/processed GB/DNS", fixed=True)
    for key, value in values.items():
        if key.lower().startswith(("enable", "deploymodel_")) and key not in _KNOWN_FLAGS and _on(value):
            add("unmapped-enabled-feature", usage="manual Bicep/pricing review required", fixed=True,
                dimensions={"flag": key})
    return rows


class CostSkills:
    def __init__(self, settings, principal, scope_key, cred=None, http_client=None, clock=None):
        self.settings, self.principal, self.scope_key = settings, principal, scope_key
        configured = getattr(settings, "costs", None)
        self.options = configured if isinstance(configured, CostSettings) else CostSettings.model_validate(configured or {})
        self.cred, self.http_client = cred, http_client
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def descriptors(self):
        try:
            self._authorize()
        except PermissionError:
            return []
        return cost_descriptors()

    def _authorize(self):
        from .security import authorize
        scope = authorize(self.settings, self.principal, self.scope_key, "factory.read")
        authorize(self.settings, self.principal, self.scope_key, "cost.read")
        return scope

    def execute(self, skill_name, args):
        name = _skill(skill_name)
        scope = self._authorize()
        try:
            arguments = argument_model(name).model_validate(args)
        except ValidationError:
            _fail("invalid_arguments", "Cost skills accept only their declared literal arguments.", 400)
        rg = scope.resource_group if name == COST_SKILLS[0] else arguments.resource_group
        allowed = self.options.common_resource_groups.get(self.scope_key, []) if name == COST_SKILLS[1] else [scope.resource_group]
        if rg not in allowed:
            raise PermissionError("The resource group is not explicitly allowed in this exact scope.")
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            _fail("invalid_cost_clock", "Cost reporting requires an aware UTC clock.", 503)
        now = now.astimezone(timezone.utc)
        path = f"/subscriptions/{scope.subscription_id}/resourceGroups/{rg}"
        if self.http_client is not None:
            data = self._execute(name, path, now, self.http_client)
        else:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                data = self._execute(name, path, now, client)
        return {"ok": True, "data": {"skill": name, "scope_key": self.scope_key,
                                  "subscription_id": str(scope.subscription_id), "resource_group": rg, **data}}

    def _request(self, client, method, url, *, body=None, arm=False):
        headers = {"Accept": "application/json"}
        if arm:
            from azure.core.exceptions import AzureError
            if self.cred is None:
                from .config import credential
                self.cred = credential(self.settings)
            try:
                headers["Authorization"] = "Bearer " + self.cred.get_token(ARM + "/.default").token
            except AzureError:
                _fail("cost_auth_unavailable", "The configured Azure identity could not obtain an ARM token.", 503)
        try:
            with client.stream(method, url, headers=headers, json=body,
                               timeout=30, follow_redirects=False) as response:
                if response.status_code in (401, 403):
                    message = ("Azure denied billing/resource read access. Review Cost Management Reader "
                               "and resource Reader permissions for this exact RG; no permissions were changed."
                               if arm else "Azure's public retail pricing endpoint denied this read-only request.")
                    _fail("cost_access_denied", message, 403)
                if response.status_code == 204:
                    _fail("cost_data_unavailable", "Azure returned no cost data; absence is not zero spend.")
                if response.status_code != 200:
                    _fail("cost_service_unavailable", "Azure cost/resource/pricing data is unavailable "
                          f"(HTTP {response.status_code}); no extrapolation or zero was substituted.", 503)
                payload = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    payload.extend(chunk)
                    if len(payload) > _MAX_BYTES:
                        _fail("cost_response_limit", "Azure cost/pricing response exceeded the bounded response limit.", 502)
        except (httpx.HTTPError, OSError):
            _fail("cost_service_unavailable", "The read-only Azure cost/pricing request failed; no estimate was substituted.", 503)
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeError):
            _fail("invalid_cost_response", "Azure returned invalid JSON.", 502)
        if not isinstance(result, dict):
            _fail("invalid_cost_response", "Azure returned an invalid cost/resource object.", 502)
        return result

    @staticmethod
    def _continuation(url, initial, *, retail=False):
        if not isinstance(url, str) or len(url) > 16000 or any(ord(char) < 32 for char in url):
            _fail("unsafe_cost_pagination", "Invalid Azure continuation link.", 502)
        try:
            parsed, target = urlsplit(url), urlsplit(initial)
            port = parsed.port
        except ValueError:
            _fail("unsafe_cost_pagination", "Invalid Azure continuation authority.", 502)
        if (parsed.scheme != "https" or parsed.hostname != target.hostname or port not in (None, 443)
                or parsed.username or parsed.password or parsed.fragment
                or parsed.path.casefold() != target.path.casefold()):
            _fail("unsafe_cost_pagination", "Azure continuation changed host, scope, or operation.", 502)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        keys = [key.casefold() for key, _ in pairs]
        allowed = {"api-version", "$skiptoken"} if not retail else {
            "api-version", "$skip", "$skiptoken", "$filter", "currencycode", "$orderby"
        }
        if not pairs or len(keys) != len(set(keys)) or set(keys) - allowed:
            _fail("unsafe_cost_pagination", "Azure continuation changed the allowed query contract.", 502)
        if not retail and dict(pairs).get("api-version") != dict(parse_qsl(target.query)).get("api-version"):
            _fail("unsafe_cost_pagination", "ARM continuation changed the API version.", 502)
        if retail:
            original = dict(parse_qsl(target.query))
            current = dict(pairs)
            if any(current.get(key) != value for key, value in original.items()):
                _fail("unsafe_cost_pagination", "Retail continuation changed region/SKU/currency filters.", 502)
        return url

    def _pages(self, client, method, initial, body=None, *, retail=False):
        url, seen = initial, set()
        for _ in range(self.options.max_pages):
            if url in seen:
                _fail("cost_pagination_cycle", "Azure returned a repeated continuation; partial totals are not used.", 502)
            seen.add(url)
            page = self._request(client, method, url, body=body, arm=not retail)
            yield page
            properties = page.get("properties", {})
            if not isinstance(properties, dict):
                _fail("invalid_cost_response", "Invalid Azure response properties.", 502)
            next_url = page.get("NextPageLink") if retail else properties.get("nextLink", page.get("nextLink"))
            if next_url is None or next_url == "":
                return
            url = self._continuation(next_url, initial, retail=retail)
        _fail("cost_pagination_limit", "Azure exceeded max_pages; partial totals are not presented as complete.", 502)

    def _billing(self, client, path, now, *, forecast=False):
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        finish = next_month - timedelta(seconds=1) if forecast else now.replace(microsecond=0)
        body = {
            "type": "ActualCost", "timeframe": "Custom",
            "timePeriod": {"from": start.isoformat(), "to": finish.isoformat()},
            "dataset": {"granularity": "Daily", "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}},
        }
        operation = "forecast" if forecast else "query"
        if forecast:
            body.update(includeActualCost=True, includeFreshPartialCost=False)
        else:
            body["dataset"]["grouping"] = [{"type": "Dimension", "name": "ServiceName"}]
        url = f"{ARM}{path}/providers/Microsoft.CostManagement/{operation}?api-version={API_VERSION}"
        totals, actual, predicted, services, row_count = {}, {}, {}, {}, 0
        actual_cutoffs, forecast_starts = {}, {}
        seen_rows = set()
        for page in self._pages(client, "POST", url, body):
            columns = page.get("properties", {}).get("columns")
            rows = page.get("properties", {}).get("rows")
            if not isinstance(columns, list) or not isinstance(rows, list):
                _fail("invalid_cost_response", "Cost Management omitted named columns or rows.", 502)
            names = [column.get("name") if isinstance(column, dict) else None for column in columns]
            if any(not isinstance(name, str) for name in names) or len(names) != len(set(names)):
                _fail("invalid_cost_response", "Cost Management column names are missing or duplicated.", 502)
            amounts = [name for name in names if name in {"Cost", "PreTaxCost", "totalCost"}]
            required = {"Currency", "UsageDate", "CostStatus" if forecast else "ServiceName"}
            if len(amounts) != 1 or not required <= set(names):
                _fail("invalid_cost_response", "Cost Management omitted an unambiguous cost, currency, or forecast status/date.", 502)
            for row in rows:
                row_count += 1
                if row_count > _MAX_ITEMS or not isinstance(row, list) or len(row) != len(names):
                    _fail("invalid_cost_response", "Cost Management rows are malformed or exceed the bound.", 502)
                record = dict(zip(names, row))
                currency = record["Currency"]
                try:
                    amount = _decimal(record[amounts[0]])
                    if currency not in _CURRENCIES:
                        raise ValueError
                    date_text = str(record["UsageDate"])
                    if re.fullmatch(r"\d{8}", date_text):
                        date = datetime.strptime(date_text, "%Y%m%d").date()
                    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
                        date = datetime.strptime(date_text, "%Y-%m-%d").date()
                    else:
                        raise ValueError
                    if not start.date() <= date <= finish.date():
                        raise ValueError
                except (ValueError, TypeError):
                    _fail("invalid_cost_response", "Cost Management returned invalid amounts/currency/dates.", 502)
                totals[currency] = totals.get(currency, Decimal(0)) + amount
                if forecast:
                    status = record["CostStatus"]
                    if status in ("Actual", "ActualCost"):
                        destination = actual
                    elif status == "Forecast":
                        destination = predicted
                    else:
                        _fail("invalid_cost_response", "Unrecognized forecast cost status; costs were not combined.", 502)
                    if destination is actual:
                        if date > now.date():
                            _fail("invalid_cost_response", "Forecast actual costs have a date after the observation date.", 502)
                        actual_cutoffs[currency] = max(actual_cutoffs.get(currency, date), date)
                    else:
                        forecast_starts[currency] = min(forecast_starts.get(currency, date), date)
                    row_key = (currency, date)
                    destination[currency] = destination.get(currency, Decimal(0)) + amount
                else:
                    service = record["ServiceName"]
                    if not isinstance(service, str) or len(service) > 200:
                        _fail("invalid_cost_response", "Invalid service dimension.", 502)
                    key = (currency, service)
                    row_key = (currency, date, service)
                    services[key] = services.get(key, Decimal(0)) + amount
                if row_key in seen_rows:
                    _fail("invalid_cost_response", "Cost Management returned duplicate or overlapping daily charges.", 502)
                seen_rows.add(row_key)
        if not row_count or (forecast and (not predicted or not actual or set(actual) != set(predicted))):
            _fail("forecast_unavailable" if forecast else "cost_data_unavailable",
                  "Azure has insufficient forecast/billing data. No synthetic projection or zero-spend claim is returned.")
        if forecast and any(forecast_starts[currency] <= cutoff for currency, cutoff in actual_cutoffs.items()):
            _fail("invalid_cost_response",
                  "Forecast dates overlap or precede the last posted actual cost date for their currency.", 502)
        result = {
            "source_type": "azure_forecast" if forecast else "azure_actual_cost",
            "source": ARM, "operation": operation, "type": "ActualCost", "observed_at": now.isoformat(),
            "period": {"from": start.isoformat(), "to": finish.isoformat(), "time_zone": "UTC"},
            "totals_by_currency": {currency: str(value) for currency, value in sorted(totals.items())},
        }
        if forecast:
            result.update(
                include_actual_cost=True, include_fresh_partial_cost=False,
                actual_component_by_currency={key: str(value) for key, value in actual.items()},
                forecast_component_by_currency={key: str(value) for key, value in predicted.items()},
                actual_cutoff_by_currency={key: cutoff.isoformat() for key, cutoff in sorted(actual_cutoffs.items())},
                actual_data_lag_days_by_currency={
                    key: (now.date() - cutoff).days for key, cutoff in sorted(actual_cutoffs.items())
                },
                billing_lag_explanation=(
                    "CostStatus is authoritative; the actual cutoff is the last posted Actual/ActualCost date "
                    "for each currency. Azure billing can lag the observation date: with "
                    "includeFreshPartialCost=False, Forecast rows after that cutoff can include dates before "
                    "observed_at. No synthetic extrapolation is used."
                ),
                basis="Azure full-month forecast response includes actual costs; do not add independent actual MTD again.",
            )
        else:
            result["services"] = [{"currency": currency, "service": service, "amount": str(value)}
                                  for (currency, service), value in sorted(services.items())]
            result["basis"] = "Actual MTD billing, not measured idle usage; open-period charges can arrive late."
        return result

    def _template(self):
        path, digest = default_template_source(self.settings.knowledge.repository_root, self.options)
        try:
            if path.stat().st_size > _MAX_BYTES:
                raise ValueError
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest.lower():
                _fail("cost_template_integrity", "The canonical default variables template differs from its trusted pin.", 503)
            document = json.loads(raw.decode("utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            _fail("cost_template_unavailable", "The integrity-pinned canonical default variables template is unavailable.", 503)
        return document, {"source_type": "canonical_default_variables", "sha256": digest.lower(),
                          "template": DEFAULT_VARIABLES_RELATIVE_PATH.as_posix(),
                          "uses_applied_live_settings": False}

    def _rate(self, client, selector, region, now):
        clauses = [
            f"armRegionName eq '{region}'", f"serviceName eq '{selector.service}'",
            f"{selector.sku_field} eq '{selector.sku}'", "priceType eq 'Consumption'",
        ]
        if selector.product:
            clauses.append(f"productName eq '{selector.product}'")
        url = RETAIL + "?" + urlencode({"api-version": "2023-01-01-preview",
                                        "currencyCode": "'" + self.options.currency + "'", "$filter": " and ".join(clauses)})
        candidates, count = {}, 0
        for page in self._pages(client, "GET", url, retail=True):
            items = page.get("Items")
            if not isinstance(items, list):
                _fail("invalid_cost_response", "Retail prices omitted Items.", 502)
            for item in items:
                count += 1
                if count > _MAX_ITEMS or not isinstance(item, dict):
                    _fail("invalid_cost_response", "Retail pricing rows exceed the bound or are malformed.", 502)
                if (item.get("armRegionName") != region or item.get("currencyCode") != self.options.currency
                        or item.get("serviceName") != selector.service
                        or item.get(selector.sku_field) != selector.sku
                        or item.get("type") != "Consumption" or item.get("isPrimaryMeterRegion") is not True):
                    continue
                product, meter = item.get("productName"), item.get("meterName")
                if (not isinstance(product, str) or not 1 <= len(product) <= 200
                        or not isinstance(meter, str) or not 1 <= len(meter) <= 200
                        or not isinstance(item.get("skuName"), str)
                        or not isinstance(item.get("armSkuName", ""), str)):
                    continue
                if selector.product and product != selector.product:
                    continue
                if selector.meters and meter not in selector.meters:
                    continue
                if any(word in (product + " " + meter).lower() for word in ("spot", "low priority", "devtest")):
                    continue
                if selector.os and (not product.startswith("Virtual Machines ")
                                    or ("Windows" in product) != (selector.os == "Windows")):
                    continue
                meter_id = item.get("meterId")
                if not isinstance(meter_id, str) or not 1 <= len(meter_id) <= 200:
                    continue
                try:
                    price = _decimal(item.get("retailPrice"), nonnegative=True)
                    if _decimal(item.get("tierMinimumUnits"), nonnegative=True) != 0:
                        continue
                    effective = datetime.fromisoformat(item["effectiveStartDate"].replace("Z", "+00:00"))
                    if effective.tzinfo is None or effective > now:
                        continue
                    if item.get("effectiveEndDate"):
                        end = datetime.fromisoformat(item["effectiveEndDate"].replace("Z", "+00:00"))
                        if end.tzinfo is None or end <= now:
                            continue
                    factor = {"1 Hour": HOURS, "1/Hour": HOURS, "1 Day": HOURS / 24,
                              "1/Day": HOURS / 24, "1 Month": Decimal(1), "1/Month": Decimal(1)}[item["unitOfMeasure"]]
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
                identity = (meter_id, product, item.get("skuName"), item["unitOfMeasure"])
                previous = candidates.get(identity)
                if previous is None or previous[0] < effective:
                    candidates[identity] = (effective, price, factor, item)
                elif previous[0] == effective and previous[1] != price:
                    return None, "ambiguous_authoritative_rate"
        if len(candidates) != 1:
            return None, "missing_authoritative_rate" if not candidates else "ambiguous_authoritative_rate"
        effective, price, factor, item = next(iter(candidates.values()))
        return {"unit_price": str(price), "unit": item["unitOfMeasure"],
                "monthly_quantity_per_instance": str(factor), "currency": self.options.currency,
                "source": RETAIL, "observed_at": now.isoformat(), "effective_start": effective.isoformat(),
                "meter_id": item.get("meterId"), "meter_name": item["meterName"],
                "product_name": item["productName"], "sku_name": item.get("skuName"),
                "arm_sku_name": item.get("armSkuName"), "region": region}, None

    def _idle(self, client, components, now):
        rows, subtotal, priced, rates = [], Decimal(0), 0, {}
        for component in components:
            estimate = {"status": "unknown_fixed_component" if component.fixed_expected else "usage_required",
                        "monthly": None, "currency": self.options.currency}
            if component.selector and component.quantity is not None and component.quantity > 0 and component.region:
                key = (component.selector, component.region)
                if key not in rates:
                    rates[key] = self._rate(client, component.selector, component.region, now)
                quote, problem = rates[key]
                if quote is not None:
                    amount = _decimal(quote["unit_price"]) * _decimal(quote["monthly_quantity_per_instance"]) * component.quantity
                    subtotal += amount
                    priced += 1
                    estimate = {"status": "priced_fixed_component", "monthly": str(amount),
                                "currency": self.options.currency, "rate": quote,
                                "monthly_billed_quantity": str(_decimal(quote["monthly_quantity_per_instance"]) * component.quantity)}
                else:
                    estimate["status"], estimate["blocker"] = "unknown_fixed_component", problem
            elif component.fixed_expected:
                estimate["blocker"] = "exact_meter_sku_region_or_quantity_unresolved"
            rows.append({"service": component.service, "sku": component.sku, "region": component.region,
                         "provisioned_quantity": str(component.quantity) if component.quantity is not None else None,
                         "resource_id": component.resource_id, "dimensions": component.dimensions or {},
                         "usage_requirements": component.usage, "assumption": component.assumption,
                         "estimate": estimate})
        return {
            "source_type": "azure_retail_idle_baseline", "basis": "Provisioned fixed minima, no workload usage; not measured inactivity.",
            "monthly_hours": int(HOURS), "currency": self.options.currency, "status": "partial" if priced else "unavailable",
            "complete": False, "priced_fixed_subtotal": str(subtotal) if priced else None, "total_monthly": None,
            "components": rows, "priced_components": priced,
            "unpriced_components": len(rows) - priced,
            "assumptions": ["Continuous 730-hour advisory month; not the actual calendar month's hour count.",
                            "Public on-demand retail; excludes negotiated discounts, reservations, savings plans and tax.",
                            "Usage-dependent tokens, transactions, storage quantities, egress and telemetry require usage inputs.",
                            "Unknown meters/resources are explicit gaps, never presumed free."],
        }

    def _resources(self, client, path):
        versions = {
            "microsoft.containerregistry/registries": "2023-07-01",
            "microsoft.search/searchservices": "2023-11-01",
            "microsoft.web/serverfarms": "2023-12-01",
            "microsoft.compute/virtualmachines": "2024-07-01",
            "microsoft.network/privateendpoints": "2024-05-01",
        }
        usage = {
            "microsoft.storage/storageaccounts": "stored GiB-month; operations; replication; egress",
            "microsoft.keyvault/vaults": "key/secret operations; certificates; key types",
            "microsoft.operationalinsights/workspaces": "ingested GB; retention; export; query charges",
            "microsoft.insights/components": "telemetry ingestion/retention; shared workspace allocation",
            "microsoft.cognitiveservices/accounts": "tokens; API transactions; model deployments; provisioned throughput",
            "microsoft.documentdb/databaseaccounts": "RU/s; stored/indexed GiB; backups; replication",
            "microsoft.datafactory/factories": "activity runs; runtime hours; data movement",
        }
        components, seen = [], set()
        initial = f"{ARM}{path}/resources?api-version=2021-04-01"
        for page in self._pages(client, "GET", initial):
            resources = page.get("value")
            if not isinstance(resources, list):
                _fail("invalid_cost_response", "ARM resource inventory omitted value.", 502)
            for resource in resources:
                if not isinstance(resource, dict) or len(components) >= _MAX_ITEMS:
                    _fail("invalid_cost_response", "ARM inventory is malformed or exceeds the resource bound.", 502)
                resource_id, kind = resource.get("id"), resource.get("type")
                prefix = path + "/providers/"
                parts = resource_id[len(prefix):].split("/") if isinstance(resource_id, str) else []
                if (not isinstance(resource_id, str) or not isinstance(kind, str)
                        or not resource_id.casefold().startswith(prefix.casefold())
                        or len(parts) not in range(3, 18, 2)
                        or not re.fullmatch(r"[A-Za-z0-9.]+", parts[0])
                        or any(not part or part in (".", "..") or "\\" in part
                               or any(ord(char) < 32 for char in part) for part in parts)
                        or resource_id.casefold() in seen):
                    _fail("cost_inventory_scope_mismatch", "ARM returned duplicate resources or resources outside the exact RG.", 502)
                seen.add(resource_id.casefold())
                kind = kind.casefold()
                segments = resource_id.split("/")
                actual_type = "/".join([segments[6], *segments[7::2]]).casefold()
                if actual_type != kind:
                    _fail("cost_inventory_scope_mismatch", "ARM resource type does not match its ID.", 502)
                detail = resource
                if kind in versions:
                    detail = self._request(client, "GET",
                                           f"{ARM}{quote(resource_id, safe='/')}?api-version={versions[kind]}", arm=True)
                    if str(detail.get("id", "")).casefold() != resource_id.casefold():
                        _fail("cost_inventory_scope_mismatch", "ARM resource details changed the exact target.", 502)
                sku_object, properties = detail.get("sku") or {}, detail.get("properties") or {}
                if not isinstance(sku_object, dict) or not isinstance(properties, dict):
                    _fail("invalid_cost_response", "ARM resource SKU/properties are malformed.", 502)
                sku, region = _dimension(sku_object.get("name")), detail.get("location")
                region = region if isinstance(region, str) and re.fullmatch(r"[a-z0-9]{2,40}", region) else None
                service, quantity, os, requirements = kind, None, None, usage.get(kind, "Unmapped deployed service: meter, provisioned minimum and usage review required.")
                if kind == "microsoft.containerregistry/registries":
                    service, quantity = "container-registry", Decimal(1)
                    requirements = "stored GiB; image builds; geo-replication; transfer"
                elif kind == "microsoft.search/searchservices":
                    service = "ai-search"
                    replicas, partitions = _quantity(properties.get("replicaCount")), _quantity(properties.get("partitionCount"))
                    quantity = replicas * partitions if replicas is not None and partitions is not None else None
                    requirements = "semantic queries; vectorization tokens; enrichment"
                elif kind == "microsoft.web/serverfarms":
                    service, quantity = "web-app-plan", _quantity(sku_object.get("capacity"))
                    os = "Linux" if properties.get("reserved") is True else "Windows" if properties.get("reserved") is False else None
                    requirements = "scale-out; bandwidth; apps on a shared plan are not separately charged"
                elif kind == "microsoft.compute/virtualmachines":
                    service, quantity = "virtual-machine", Decimal(1)
                    hardware, storage = properties.get("hardwareProfile") or {}, properties.get("storageProfile") or {}
                    if not isinstance(hardware, dict) or not isinstance(storage, dict) or not isinstance(storage.get("osDisk", {}), dict):
                        _fail("invalid_cost_response", "ARM VM billing dimensions are malformed.", 502)
                    sku, os = _dimension(hardware.get("vmSize")), storage.get("osDisk", {}).get("osType")
                    if properties.get("licenseType") == "Windows_Server":
                        os = "Linux"
                    requirements = "OS/data disks; backup; network; supplied Windows Hybrid Benefit licenses"
                elif kind == "microsoft.network/privateendpoints":
                    service, sku, quantity = "private-endpoint", "Standard", Decimal(1)
                    requirements = "processed GB; DNS zones/queries"
                fixed = kind in versions or kind not in usage
                selector = _selector(service, sku, os)
                components.append(Component(service, sku, region, quantity, requirements,
                                            "Provisioned configuration only; no activity metrics or VM power state measured.",
                                            selector, resource_id, fixed))
        if not components:
            _fail("cost_inventory_unavailable", "The common RG has no discovered resources; no zero-cost claim is made.")
        return components

    def _execute(self, name, path, now, client):
        if name == COST_SKILLS[2]:
            actual = self._billing(client, path, now)
            forecast = self._billing(client, path, now, forecast=True)
            return {"source_type": "azure_cost_management", "basis": "Separate actual MTD and Azure full-month forecast.",
                    "actual_mtd": actual, "azure_forecast_full_month": forecast,
                    "forecast_total_includes_actual": True, "synthetic_extrapolation": False}
        template_source = {}
        if name == COST_SKILLS[0]:
            document, template_source = self._template()
            components = template_components(document, self.settings.scopes[self.scope_key].environment)
        else:
            components = self._resources(client, path)
            template_source = {"source_type": "deployed_arm_inventory"}
        actual = self._billing(client, path, now)
        return {"source_type": "retail_estimate_with_azure_cost_analysis", "basis": "Idle baseline and billed actual are alternatives, never summed.",
                "inventory_source": template_source, "idle_baseline": self._idle(client, components, now),
                "actual_mtd": actual}
