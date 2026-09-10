"""
AIFactory Config Wizard  -  v046
Changes from v045:
    Quick setup and configuration file workflow:
        - Added Export variable file actions for YAML, .env, and JSON.
        - Export dialogs start in the active project's aifactory folder.
        - Startup folder detection selects GHA when the parent contains .env;
            otherwise it selects ADO and imports the pipeline variables.yaml.
        - A clean project-level variables.json takes precedence when available.
        - Added Recent projects grouped by ADO/GHA with Project-list-style labels.
        - Fixed stale project snapshots overriding the configured startup folder.
        - Fixed BYO ASE false values appearing enabled and requiring an ASE ID.
        - Fixed JSON export when mapped values contain embedded JSON quotes.
Changes from v044:
  SKU page (page 6) reworked into per-environment SKUs:
    - Renamed nav label "Foundry SKUs" -> "SKUs".
    - Two tabs "Dev" and "Stage & Prod" (test == Stage) exposing every service
      SKU (AI Search tier + Semantic Search tier as radios, all others as
      combos/entries) backed by sku<Name>Dev / sku<Name>StageProd variables
      (variables.yaml) and SKU_<NAME>_DEV / SKU_<NAME>_STAGEPROD (.env).
    - OpenAI model deployment settings moved to page 9 (GenAI & ML), shown in
      both simple and advanced mode.
Changes from v043:
  New variable (both Azure DevOps variables.yaml and GitHub Actions .env routes):
    - disableLocalAuth: "Disable Local Auth (AAD-only, no API keys)" checkbox in
      Security/Cost -> RBAC. Disables local API-key auth on Cognitive/AI Services
      & Foundry, enforcing AAD-only. Default true. Maps to variables.disableLocalAuth
      (ADO) / DISABLE_LOCAL_AUTH (GHA).
Changes from v040 (validation):
  - Window title now reads v040 (the build workflow extracts the version from
    this line, so v039 was previously released by mistake).
  - <todo> placeholder validation is now conditional on the enabling checkbox:
    cmkKeyName is only required when CMK is true; byoAseFullResourceId and
    byoAseAppServicePlanResourceId only when byoASEv3 is true.
  - Removed email validation for technical_admins_email (PROJECT_MEMBERS_EMAILS):
    AD groups do not require an email, and its <todo> placeholder is never flagged.
Changes from v039:
  GitHub Actions (.env) save fix:
    - ENV_MAP auto-derived keys dropped underscores, so save_github_actions()
      appended junk duplicate lines instead of updating the real .env key.
      UX toggles therefore never reached the .env (e.g. "Enable Databricks"
      stayed ENABLE_DATABRICKS="false").
    - Added overrides for 26 affected keys: enableDatabricks, enableDatafactory,
      enableFunction, functionRuntime/Version, webAppRuntime, cosmosKind,
      foundryDeploymentType, aseSku/Code/Workers, projectPrefix/Suffix,
      commonResourceGroup_param, datalakeName_param, kvNameFromCOMMON_param,
      and all subnetCommon*/subnetProj* BYO subnet names.
    - Corrected vnetResourceGroup_param/vnetNameFull_param to the real template
      keys VNET_RESOURCE_GROUP_PARAM / VNET_NAME_FULL_PARAM.
Changes from v038:
  - subnetProjWebapp: confirmed GitHub Actions .env sync (SUBNET_PROJ_WEBAPP)
    matches the Azure DevOps variables.yaml route when edited via the UX.
Changes from v037:
  New variables (both Azure DevOps variables.yaml and GitHub Actions .env routes):
    - subnetProjWebapp: BYO App Service/Function VNet integration subnet.
      Shown in Advanced Networking -> BYO Subnets (advanced mode).
    - deleteKeyvaultAlso: "Also delete the project Key Vault" checkbox in the
      Project Setup danger frame (enabled only when "Delete all services" is set).
    - skipDiag* (AOAI, AISearch, AIServices, ContentSafety, Vision, Speech,
      DocIntelligence): saved with default "true"; no UX (skip AIFactory-managed
      diagnostic settings when an Azure Policy already creates them).
Changes from v035:
  Scale set management:
    Left panel: new "Scale sets" collapsible menu above "Projects".
      Click a scale set to load its page-2 fields and filter Projects list.
      "Show all projects" link clears the active filter.
    Page 2 (Scale set & Vnets): "Saved Scale Sets" section at the top.
      List of previously saved scale sets — click any to reload its fields.
      "Save current as Scale Set" button persists page-2 fields to
        {save_folder}/config-wizard/scalesets/scaleset_{ID}.json.
      "Create new Scale Set" button resets page-2 fields to defaults.
    Projects menu: labels now show prefix+scaleset, e.g. "Project 002 (mrvel-1-007)".
    Import (variables.yaml / .env): automatically selects the matching scale set
      in the left panel and filters the Projects list after import.
  Window height increased to 1260x1110 to better accommodate page 2 scroll content.
  Window enlarged (1260x920) — all pages fit without scrolling.
  Scrollbars made wider (14 px) — easier to grab.
  Left panel: "Created Projects" collapsible section above Advanced Mode toggle.
    Saves a JSON snapshot per project_number_000 on every SAVE.
    Click any entry to instantly reload that project's settings.
  Summary page (page 13): colour-coded values
    Red     = invalid value
    Green   = default value unchanged
    Magenta = value changed by user
  Simple/Advanced mode toggle button (bottom-left navigator).
  Default: Simple mode.

  Simple mode hides per-page:
    Page 10 (GenAI/ML):
      - "Add AI Foundry", "Update AI Foundry", "Enable AI Foundry Capability Host"
      - "Enable AIFactory Created Default Project for AIFv2"
      - "Foundry Deployment Type" section
      - "Add Azure Machine Learning"
      - AKS: aksOutboundType, aksPrivateDNSZone, aksAzureFirewallPrivateIp
        (only enableAksForAzureML checkbox remains visible)
    Page 11 (Cognitive/DB):
      - "Add AI Search"
      - CosmosDB Kind selector
    Page 12 (App/Integration):
      - Function runtime/version selectors
      - WebApp runtime/version/ASE selectors
      - enableAppInsightsDashboard checkbox

Pages (13 total):
  1  Orchestrator           2  Scale set & Vnets
  3  Version                4  Adv. Networking
  5  Project team           6  AI Factory features
  7  Foundry SKUs           8  Security/Cost
  9  Project & Core         10 ON/OFF: GenAI & ML
  11 ON/OFF: Cognitive & DB 12 ON/OFF: App & Integration
  13 Summary
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import copy, json, os, sys, re, stat, webbrowser
from pathlib import Path

import yaml
try:
    from .scaling_policy import (
        SCALING_MODE_KEY, DEFAULT_SCALING_MODE, SCALING_MODES, SCALING_NETWORK_PROFILES,
        apply_scaling_mode, scaling_validation_issues, require_scaling_configuration, vnet_format_help,
    )
    from .network_placement import PLACEMENT_KEYS, preview_network_placement
except ImportError:
    from scaling_policy import (
        SCALING_MODE_KEY, DEFAULT_SCALING_MODE, SCALING_MODES, SCALING_NETWORK_PROFILES,
        apply_scaling_mode, scaling_validation_issues, require_scaling_configuration, vnet_format_help,
    )
    from network_placement import PLACEMENT_KEYS, preview_network_placement

# ---------------------------------------------------------------------------
# Resource resolver
# ---------------------------------------------------------------------------
def _res(relative_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)

# ---------------------------------------------------------------------------
# Theme engine  (light / dark)
# ---------------------------------------------------------------------------
# sv-ttk gives modern Sun-Valley-styled ttk widgets.  It is OPTIONAL and gets
# bundled into the PyInstaller .exe, so the shipped app stays a single,
# fully-offline, self-contained download.  If the import fails (e.g. running
# from source without it) the app still works with a manual clam fallback.
try:
    import sv_ttk as _sv_ttk
except Exception:
    _sv_ttk = None

# Authored (light) colour  ->  dark-mode colour.  Split by widget-option type
# so the SAME hex can map differently as a background vs a foreground
# (e.g. #1a1a1a is dark *text* in the content but a dark *fill* in the sidebar,
#  which must stay dark in both modes — VS Code keeps its activity bar dark).
_THEME_BG_MAP = {
    "#f5f5f5": "#1e1e1e",   # page / content background
    "#ffffff": "#252526",   # entry / text-widget / card fields
    "#ececec": "#2a2a2c",   # light panel
    "#e8e8e8": "#2b2b2d",   # root / light panel
    "#f3f3f3": "#262628",   # inline code background
    "#dcdcdc": "#2d2d30",   # nav bar
    "#e0e0e0": "#37373a",   # buttons / chips
    "#d0d0d0": "#3a3a3c",   # scrollbar trough
    "#fdecea": "#3a1e1e",   # danger light-red panel
    "#ffe0e0": "#3a1e1e",   # error entry fill
    "#e3f2fd": "#0e2b3d",   # highlight light-blue
    "#deeeff": "#0e2b3d",   # highlight field
    "#fff8e1": "#3a341e",   # warn light-amber panel
}
_THEME_FG_MAP = {
    "#1a1a1a": "#e8e8e8",   # strong text
    "#222222": "#dcdcdc",
    "#333333": "#cfcfcf",   # body text
    "#444444": "#b8b8b8",   # dim text
    "#555555": "#9a9a9a",
    "#666666": "#8a8a8a",
    "#000000": "#e8e8e8",
}
_THEME_BG_OPTS = ("background", "activebackground", "highlightbackground",
                  "highlightcolor", "troughcolor", "readonlybackground",
                  "disabledbackground")
_THEME_FG_OPTS = ("foreground", "activeforeground", "insertbackground",
                  "disabledforeground")

# Foundry-inspired accents (used for the sidebar / headers — kept consistent in
# both modes because they read well on dark).
THEME_ACCENT_BLUE = "#0078d4"
THEME_ACCENT_TURQ = "#4ec9b0"

def _theme_map_color(opt: str, value: str):
    v = (str(value) or "").lower()
    if opt in _THEME_BG_OPTS:
        return _THEME_BG_MAP.get(v)
    if opt in _THEME_FG_OPTS:
        return _THEME_FG_MAP.get(v)
    return None

def _retheme_widget(w, dark: bool) -> None:
    """Recolour one tk widget: remember its authored (light) colours once, then
    either apply the dark mapping (dark=True) or restore the originals."""
    try:
        store = w.__dict__.setdefault("_theme_orig", {})
    except Exception:
        return
    for opt in _THEME_BG_OPTS + _THEME_FG_OPTS:
        try:
            cur = w.cget(opt)
        except Exception:
            continue          # ttk widgets / unsupported option -> skip
        if cur in (None, ""):
            continue
        cur = str(cur)
        if opt not in store:
            store[opt] = cur  # capture authored value on first touch
        orig = store[opt]
        if dark:
            mapped = _theme_map_color(opt, orig)
            if mapped and mapped != cur:
                try:
                    w.configure(**{opt: mapped})
                except Exception:
                    pass
        elif orig != cur:
            try:
                w.configure(**{opt: orig})
            except Exception:
                pass

def _retheme_tree(root, dark: bool) -> None:
    """Walk the whole widget tree applying the dark/light recolour."""
    stack = [root]
    while stack:
        w = stack.pop()
        _retheme_widget(w, dark)
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass

def _apply_theme_styles(style, dark: bool) -> None:
    """(Re)apply custom named ttk styles.  Must run AFTER sv_ttk.set_theme(),
    which resets the style database."""
    if dark:
        style.configure("Error.TEntry",           fieldbackground="#5a1f1f")
        style.configure("Highlight.TCheckbutton",  background="#0e2b3d")
        style.configure("Highlight.TEntry",        fieldbackground="#10384d")
        style.configure("Highlight.TCombobox",     fieldbackground="#10384d")
    else:
        style.configure("Error.TEntry",           fieldbackground="#ffe0e0")
        style.configure("Highlight.TCheckbutton",  background="#e3f2fd")
        style.configure("Highlight.TEntry",        fieldbackground="#deeeff")
        style.configure("Highlight.TCombobox",     fieldbackground="#deeeff")
    style.configure("Vertical.TScrollbar",   arrowsize=14, width=14)
    style.configure("Horizontal.TScrollbar", arrowsize=14, width=14)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

def _is_uuid(s): return bool(_UUID_RE.match(s.strip()))
def _is_email(s): return bool(_EMAIL_RE.match(s.strip()))

def _validate_uuid_field(label, value, allow_empty=True):
    v = value.strip()
    if not v:
        return "" if allow_empty else f"{label}: required"
    if not _is_uuid(v):
        return f"{label}: must be a UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"
    return ""

def _validate_csv_emails(label, value, allow_empty=True):
    v = value.strip()
    if not v:
        return "" if allow_empty else f"{label}: required"
    parts = [p.strip() for p in v.split(",") if p.strip()]
    bad = [p for p in parts if not _is_email(p)]
    return f"{label}: invalid email(s): {', '.join(bad)}" if bad else ""

def _validate_obj_id_field(label, value, allow_empty=True):
    v = value.strip()
    if not v:
        return "" if allow_empty else f"{label}: required (at least one UUID)"
    if v.endswith(","):
        return f"{label}: must not end with a comma"
    parts = [p.strip() for p in v.split(",") if p.strip()]
    bad = [p for p in parts if not _is_uuid(p)]
    return f"{label}: invalid UUID(s): {', '.join(bad)}" if bad else ""

def _validate_int_range(label, value, lo, hi):
    try:
        n = int(value.strip())
        return "" if lo <= n <= hi else f"{label}: must be between {lo} and {hi}"
    except ValueError:
        return f"{label}: must be an integer"

_IPV4_RE = re.compile(
    r'^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.(25[0-5]|2[0-4]\d|[01]?\d\d?)\.'
    r'(25[0-5]|2[0-4]\d|[01]?\d\d?)\.(25[0-5]|2[0-4]\d|[01]?\d\d?))'
    r'(/([0-9]|[1-2][0-9]|3[0-2]))?$'
)

def _validate_ip_whitelist(label, value, allow_empty=True):
    """Validate comma-separated IPv4 addresses / CIDR blocks, no spaces."""
    v = value.strip()
    if not v:
        return "" if allow_empty else f"{label}: required"
    if " " in v:
        return f"{label}: must not contain spaces"
    if v.endswith(","):
        return f"{label}: must not end with a comma"
    parts = [p for p in v.split(",") if p]
    bad = [p for p in parts if not _IPV4_RE.match(p)]
    return f"{label}: invalid entry(s): {', '.join(bad)}" if bad else ""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# NAV_ITEMS used only as documentation; nav is built directly in WizardApp.__init__
# Page order: 0 Orchestrator, 1 ScaleSet, 2 Version, 3 AdvNet, 4 SeedingKV, 5 SKU,
#             6 SecurityCost, 7 ProjectCore, 8 Prefix(team), 9 GenAIML,
#             10 CognitiveDB, 11 Integration, 12 Other, 13 Summary

NETWORK_MODE_FLAGS = {
    "private": {"allowPublicAccessWhenBehindVnet":"false","enablePublicGenAIAccess":"false","enablePublicAccessWithPerimeter":"false"},
    "hybrid":  {"allowPublicAccessWhenBehindVnet":"true", "enablePublicGenAIAccess":"true", "enablePublicAccessWithPerimeter":"false"},
    "public":  {"allowPublicAccessWhenBehindVnet":"true", "enablePublicGenAIAccess":"true", "enablePublicAccessWithPerimeter":"true"},
}

VERSION_BRANCH = {
    "1.24": "release/v.1.24",
    "1.23": "release/v.1.23",
    "1.22": "release/v.1.22",
    "1.21": "release/v.1.21",
}

AI_SEARCH_SKUS   = ["free","basic","standard","standard2","standard3","storage_optimized_l1","storage_optimized_l2"]
SEMANTIC_SKUS    = ["disabled","free","standard"]
DIAG_LEVELS      = ["gold","silver","bronze"]
ACR_SKUS         = ["Premium","Standard","Basic"]
MODEL_SKUS       = ["Standard","DataZoneStandard","GlobalStandard"]
COSMOS_KINDS     = ["GlobalDocumentDB","MongoDB"]
FUNC_RUNTIMES    = ["python","dotnet","node","java"]
FUNC_VERSIONS    = {"python":["3.11","3.10","3.9"],"dotnet":["v8.0","v7.0"],"node":["18","20"],"java":["11","17"]}
WEBAPP_RUNTIMES  = ["python","dotnet","node","java"]
WEBAPP_VERSIONS  = {"python":["3.11","3.10"],"dotnet":["v8.0","v7.0"],"node":["18","20"],"java":["11","17"]}
ASE_SKUS         = ["IsolatedV2","Isolated"]
ASE_SKU_CODES    = ["I1v2","I2v2","I3v2","I1","I2","I3"]
AKS_OUTBOUND     = ["loadBalancer","userDefinedRouting"]
AKS_DNS_ZONES    = ["system","none"]

# ---------------------------------------------------------------------------
# Per-environment service SKUs (Dev vs Stage/Prod) — shown on the SKU page's
# two tabs. Each entry maps 1:1 to variables.yaml (sku<Name>Dev / sku<Name>StageProd)
# and, where a matching .env line exists, to SKU_<NAME>_DEV / SKU_<NAME>_STAGEPROD.
#   (base, label, group, default, choices, env_base)
#   choices=None → free-text entry ; choices=[...] → combo/radio
#   env_base=None → variable exists only in variables.yaml (no .env line)
# ---------------------------------------------------------------------------
SKU_FIELDS = [
    ("skuStorageAccount",  "Storage Account",       "Core Infrastructure", "Standard_LRS",
        ["Standard_LRS","Standard_GRS","Standard_RAGRS","Standard_ZRS","Premium_LRS","Premium_ZRS","Standard_GZRS","Standard_RAGZRS"], "SKU_STORAGEACCOUNT"),
    ("skuAISearch",        "AI Search tier",        "Cognitive Services",  "standard", AI_SEARCH_SKUS, None),
    ("skuAIServices",      "AI Services",           "Cognitive Services",  "S0", None, "SKU_AISERVICES"),
    ("skuOpenAI",          "Azure OpenAI",          "Cognitive Services",  "S0", None, "SKU_OPENAI"),
    ("skuContentSafety",   "Content Safety",        "Cognitive Services",  "S0", None, "SKU_CONTENTSAFETY"),
    ("skuVision",          "AI Vision",             "Cognitive Services",  "S1", None, "SKU_VISION"),
    ("skuSpeech",          "AI Speech",             "Cognitive Services",  "S0", None, "SKU_SPEECH"),
    ("skuDocIntelligence", "Document Intelligence", "Cognitive Services",  "S0", None, "SKU_DOCINTELLIGENCE"),
    ("skuBing",            "Bing Custom Search",    "Cognitive Services",  "G2", ["G2"], "SKU_BING"),
    ("skuPostgreSQL",      "PostgreSQL compute",    "Databases",           "Standard_B1ms", None, "SKU_POSTGRESQL"),
    ("skuTierPostgreSQL",  "PostgreSQL tier",       "Databases",           "Burstable", ["Burstable","GeneralPurpose","MemoryOptimized"], "SKU_TIER_POSTGRESQL"),
    ("skuRedis",           "Redis Cache",           "Databases",           "Standard", ["Basic","Standard","Premium"], "SKU_REDIS"),
    ("skuSQLDatabase",     "SQL Database",          "Databases",           "S0", None, "SKU_SQLDATABASE"),
    ("skuTierSQLDatabase", "SQL Database tier",     "Databases",           "Standard", ["Basic","Standard","Premium"], "SKU_TIER_SQLDATABASE"),
    ("skuElastic",         "Elastic Cloud",         "Databases",           "ess-consumption-2024_Monthly", None, None),
    ("skuWebApp",          "Web App plan",          "Compute",             "P1v3", None, "SKU_WEBAPP"),
    ("skuTierWebApp",      "Web App plan tier",     "Compute",             "PremiumV3", None, "SKU_TIER_WEBAPP"),
    ("skuFunction",        "Function plan",         "Compute",             "EP1", None, "SKU_FUNCTION"),
    ("skuTierFunction",    "Function plan tier",    "Compute",             "ElasticPremium", None, "SKU_TIER_FUNCTION"),
    ("skuAks",             "AKS node VM size",      "Compute",             "", None, "SKU_AKS"),
    ("skuTierAks",         "AKS tier",              "Compute",             "Standard", ["Free","Standard","Premium"], "SKU_TIER_AKS"),
    ("skuAzureML",         "Azure ML workspace",    "ML / Data platform",  "Basic", ["Basic"], "SKU_AZUREML"),
    ("skuTierAzureML",     "Azure ML tier",         "ML / Data platform",  "basic", None, "SKU_TIER_AZUREML"),
    ("skuDatabricks",      "Databricks",            "ML / Data platform",  "premium", ["standard","premium","trial"], "SKU_DATABRICKS"),
    ("skuLogicApps",       "Logic Apps plan",       "Integration",         "WS1", None, "SKU_LOGICAPPS"),
    ("skuEventHubs",       "Event Hubs",            "Integration",         "Basic", ["Basic","Standard","Premium"], "SKU_EVENTHUBS"),
    ("skuBotService",      "Bot Service",           "Integration",         "S1", ["F0","S1"], "SKU_BOTSERVICE"),
]

# ---------------------------------------------------------------------------
# YAML / ENV mappings
# ---------------------------------------------------------------------------
DASHBOARD_KEY = "aifactory-dash-01"

YAML_MAP = {
    SCALING_MODE_KEY:       "variables.scaling-mode",
    DASHBOARD_KEY:          "variables.aifactory-dash-01",
    "version_minor":        "variables.aifactory_version_minor",
    "version_major":        "variables.aifactory_version_major",
    "version_branch":       "variables.aifactory_branch_chosen",
    "allowPublicAccessWhenBehindVnet":   "variables.allowPublicAccessWhenBehindVnet",
    "enablePublicGenAIAccess":           "variables.enablePublicGenAIAccess",
    "enablePublicAccessWithPerimeter":   "variables.enablePublicAccessWithPerimeter",
    "dev_sub_id":           "variables.dev_sub_id",
    "test_sub_id":          "variables.test_sub_id",
    "prod_sub_id":          "variables.prod_sub_id",
    "tenantId":             "variables.tenantId",
    "dev_cidr_range":       "variables.dev_cidr_range",
    "test_cidr_range":      "variables.test_cidr_range",
    "prod_cidr_range":      "variables.prod_cidr_range",
    "common_vnet_cidr":              "variables.common_vnet_cidr",
    "common_subnet_cidr":            "variables.common_subnet_cidr",
    "common_subnet_scoring_cidr":    "variables.common_subnet_scoring_cidr",
    "common_pbi_subnet_name":        "variables.common_pbi_subnet_name",
    "common_pbi_subnet_cidr":        "variables.common_pbi_subnet_cidr",
    "common_bastion_subnet_name":    "variables.common_bastion_subnet_name",
    "common_bastion_subnet_cidr":    "variables.common_bastion_subnet_cidr",
    "centralDnsZoneByPolicyInHub":   "variables.centralDnsZoneByPolicyInHub",
    "enableAIFactoryHub":           "variables.enableAIFactoryHub",
    "privDnsSubscription_param":     "variables.privDnsSubscription_param",
    "privDnsResourceGroup_param":    "variables.privDnsResourceGroup_param",
    "vnetResourceGroup_param":       "variables.vnetResourceGroup_param",
    "vnetNameFull_param":            "variables.vnetNameFull_param",
    "disableAgentNetworkInjection":  "variables.disableAgentNetworkInjection",
    "policyExemptionAssignmentIds":  "variables.policyExemptionAssignmentIds",
    "policyExemptionDefinitionReferenceIds": "variables.policyExemptionDefinitionReferenceIds",
    "enableAISearchSharedPrivateLink":"variables.enableAISearchSharedPrivateLink",
    "admin_location":       "variables.admin_location",
    "admin_locationSuffix": "variables.admin_locationSuffix",
    "admin_aifactoryPrefixRG":      "variables.admin_aifactoryPrefixRG",
    "aifactory_salt":               "variables.aifactory_salt",
    "tag_costceter_common":         "variables.tag_costceter_common",
    "technical_admins_email":       "variables.technical_admins_email",
    "technical_admins_ad_object_id":"variables.technical_admins_ad_object_id",
    "use_ad_groups":                "variables.use_ad_groups",
    "dev_admin_bicep_input_keyvault_subscription":  "variables.dev_admin_bicep_input_keyvault_subscription",
    "dev_admin_bicep_kv_fw_rg":     "variables.dev_admin_bicep_kv_fw_rg",
    "dev_admin_bicep_kv_fw":        "variables.dev_admin_bicep_kv_fw",
    "test_admin_bicep_input_keyvault_subscription": "variables.test_admin_bicep_input_keyvault_subscription",
    "test_admin_bicep_kv_fw_rg":    "variables.test_admin_bicep_kv_fw_rg",
    "test_admin_bicep_kv_fw":       "variables.test_admin_bicep_kv_fw",
    "prod_admin_bicep_input_keyvault_subscription": "variables.prod_admin_bicep_input_keyvault_subscription",
    "prod_admin_bicep_kv_fw_rg":    "variables.prod_admin_bicep_kv_fw_rg",
    "prod_admin_bicep_kv_fw":       "variables.prod_admin_bicep_kv_fw",
    "cmk":                          "variables.cmk",
    "admin_keyvaultSoftDeleteDays": "variables.admin_keyvaultSoftDeleteDays",
    "useCommonACR":                     "variables.useCommonACR",
    "enableDeleteForDisabledResources": "variables.enableDeleteForDisabledResources",
    "deleteAllServicesForProject":       "variables.deleteAllServicesForProject",
    "deleteKeyvaultAlso":                "variables.deleteKeyvaultAlso",
    "deleteAllForProject":               "variables.deleteAllForProject",
    "admin_aiSearchTier":       "variables.admin_aiSearchTier",
    "admin_semanticSearchTier": "variables.admin_semanticSearchTier",
    "deployModel_gpt_X":            "variables.deployModel_gpt_X",
    "modelGPTXName":                "variables.modelGPTXName",
    "modelGPTXVersion":             "variables.modelGPTXVersion",
    "modelGPTXSku":                 "variables.modelGPTXSku",
    "modelGPTXCapacity":            "variables.modelGPTXCapacity",
    "deployModel_text_embedding_ada_002":  "variables.deployModel_text_embedding_ada_002",
    "deployModel_text_embedding_3_large":  "variables.deployModel_text_embedding_3_large",
    "deployModel_text_embedding_3_small":  "variables.deployModel_text_embedding_3_small",
    "default_embedding_capacity":   "variables.default_embedding_capacity",
    "deployModel_gpt_54_mini":      "variables.deployModel_gpt_54_mini",
    "default_gpt_54_mini_version":  "variables.default_gpt_54_mini_version",
    "deployModel_gpt_4o":           "variables.deployModel_gpt_4o",
    "default_gpt_4o_version":       "variables.default_gpt_4o_version",
    "default_gpt_capacity":         "variables.default_gpt_capacity",
    "default_model_sku":            "variables.default_model_sku",
    "enableDefenderforAISubLevel":      "variables.enableDefenderforAISubLevel",
    "enableDefenderforAIResourceLevel": "variables.enableDefenderforAIResourceLevel",
    "addBastionHost":               "variables.addBastionHost",
    "enableAdminVM":                "variables.enableAdminVM",
    "useSelfHostedBuildAgent":      "variables.useSelfHostedBuildAgent",
    "selfHostedRunnerLabel":        "variables.selfHostedRunnerLabel",
    "adminVMBuildAgentPool":        "variables.adminVMBuildAgentPool",
    "adminVMBuildAgentName":        "variables.adminVMBuildAgentName",
    "admin_username":               "variables.admin_username",
    "tag_costcenter":               "variables.tag_costcenter",
    "diagnosticSettingLevel":       "variables.diagnosticSettingLevel",
    "skipDiagAOAI":                 "variables.skipDiagAOAI",
    "skipDiagAISearch":             "variables.skipDiagAISearch",
    "skipDiagAIServices":           "variables.skipDiagAIServices",
    "skipDiagContentSafety":        "variables.skipDiagContentSafety",
    "skipDiagVision":               "variables.skipDiagVision",
    "skipDiagSpeech":               "variables.skipDiagSpeech",
    "skipDiagDocIntelligence":      "variables.skipDiagDocIntelligence",
    "acr_adminUserEnabled":         "variables.acr_adminUserEnabled",
    "acr_dedicated":                "variables.acr_dedicated",
    "acr_SKU":                      "variables.acr_SKU",
    "admin_hybridBenefit":          "variables.admin_hybridBenefit",
    "enableProjectVM":              "variables.enableProjectVM",
    "project_number_000":           "variables.project_number_000",
    "runNetworkingVar":             "variables.runNetworkingVar",
    "enableAIFoundry":              "variables.enableAIFoundry",
    "addAIFoundry":                 "variables.addAIFoundry",
    "enableAFoundryCaphost":        "variables.enableAFoundryCaphost",
    "cleanFoundryCaphost":          "variables.cleanFoundryCaphost",
    "updateAIFoundry":              "variables.updateAIFoundry",
    "foundryDeploymentType":        "variables.foundryDeploymentType",
    "enableAIFactoryCreatedDefaultProjectForAIFv2": "variables.enableAIFactoryCreatedDefaultProjectForAIFv2",
    "enableAzureMachineLearning":   "variables.enableAzureMachineLearning",
    "addAzureMachineLearning":      "variables.addAzureMachineLearning",
    "enableDatabricks":             "variables.enableDatabricks",
    "enableDatafactory":            "variables.enableDatafactory",
    "enableAksForAzureML":          "variables.enableAksForAzureML",
    "enableAKS":                    "variables.enableAKS",
    "aksSkuName":                   "variables.aksSkuName",
    "aksSkuTier":                   "variables.aksSkuTier",
    "aksEnablePrivateCluster":      "variables.aksEnablePrivateCluster",
    "aksOutboundType":              "variables.aksOutboundType",
    "aksPrivateDNSZone":            "variables.aksPrivateDNSZone",
    "aksAzureFirewallPrivateIp":    "variables.aksAzureFirewallPrivateIp",
    "enableAISearch":               "variables.enableAISearch",
    "addAISearch":                  "variables.addAISearch",
    "enableAzureOpenAI":            "variables.enableAzureOpenAI",
    "enableAzureAIVision":          "variables.enableAzureAIVision",
    "enableAzureSpeech":            "variables.enableAzureSpeech",
    "enableAIDocIntelligence":      "variables.enableAIDocIntelligence",
    "enableContentSafety":          "variables.enableContentSafety",
    "enableCosmosDB":               "variables.enableCosmosDB",
    "cosmosKind":                   "variables.cosmosKind",
    "enablePostgreSQL":             "variables.enablePostgreSQL",
    "enableRedisCache":             "variables.enableRedisCache",
    "enableSQLDatabase":            "variables.enableSQLDatabase",
    "enableElasticsearch":          "variables.enableElasticsearch",
    "elasticType":                  "variables.elasticType",
    "elasticEmail":                 "variables.elasticEmail",
    "elasticFirstName":             "variables.elasticFirstName",
    "elasticLastName":              "variables.elasticLastName",
    "elasticCompanyName":           "variables.elasticCompanyName",
    "elasticDeploymentSize":        "variables.elasticDeploymentSize",
    "elasticSku":                   "variables.elasticSku",
    "enableFunction":               "variables.enableFunction",
    "functionRuntime":              "variables.functionRuntime",
    "functionVersion":              "variables.functionVersion",
    "enableWebApp":                 "variables.enableWebApp",
    "webAppRuntime":                "variables.webAppRuntime",
    "webAppRuntimeVersion":         "variables.webAppRuntimeVersion",
    "aseSku":                       "variables.aseSku",
    "aseSkuCode":                   "variables.aseSkuCode",
    "aseSkuWorkers":                "variables.aseSkuWorkers",
    "enableContainerApps":          "variables.enableContainerApps",
    "enableAppInsightsDashboard":   "variables.enableAppInsightsDashboard",
    "enableLogicApps":              "variables.enableLogicApps",
    "enableEventHubs":              "variables.enableEventHubs",
    "enableBotService":             "variables.enableBotService",
    "enableAIServices":             "variables.enableAIServices",
    "enableAIFoundryHub":           "variables.enableAIFoundryHub",
    "addAIFoundryHub":              "variables.addAIFoundryHub",
    "foundryApiManagementResourceId": "variables.foundryApiManagementResourceId",
    "enableBing":                   "variables.enableBing",
    "enableBingCustomSearch":       "variables.enableBingCustomSearch",
    "bingCustomSearchSku":          "variables.bingCustomSearchSku",
    "postGresAdminEmails":          "variables.postGresAdminEmails",
    "enableDatafactoryCommon":      "variables.enableDatafactoryCommon",
    "updateRbac":                   "variables.updateRbac",
    "debugEnableCleaning":          "variables.debugEnableCleaning",
    "enableRetries":                "variables.enableRetries",
    "retryMinutes":                 "variables.retryMinutes",
    "retryMinutesExtended":         "variables.retryMinutesExtended",
    "maxRetryAttempts":             "variables.maxRetryAttempts",
    "debug_disable_validation_tasks": "variables.debug_disable_validation_tasks",
    "cmkKeyName":                   "variables.cmkKeyName",
    "cmkKeyVersion":                "variables.cmkKeyVersion",
    "cmkDisableForAISearch":         "variables.cmkDisableForAISearch",
    "cmkDisableForFoundry":          "variables.cmkDisableForFoundry",
    "updateKeyvaultRbac":           "variables.updateKeyvaultRbac",
    "project_IP_whitelist":        "variables.project_IP_whitelist",
    "admin_aifactorySuffixRG":      "variables.admin_aifactorySuffixRG",
    "projectPrefix":                "variables.projectPrefix",
    "projectSuffix":                "variables.projectSuffix",
    # ADO service connections (page 2 — visible only when orchestrator == ado)
    "dev_service_connection":               "variables.dev_service_connection",
    "test_service_connection":              "variables.test_service_connection",
    "prod_service_connection":              "variables.prod_service_connection",
    "dev_seeding_kv_service_connection":    "variables.dev_seeding_kv_service_connection",
    "test_seeding_kv_service_connection":   "variables.test_seeding_kv_service_connection",
    "prod_seeding_kv_service_connection":   "variables.prod_seeding_kv_service_connection",
    # Common service principal seeding-KV key names (page 4 / global)
    "inputCommonSPIDKey":           "variables.inputCommonSPIDKey",
    "inputCommonSPSecretKey":       "variables.inputCommonSPSecretKey",
    "commonServicePrincipleOIDKey": "variables.commonServicePrincipleOIDKey",
    # Project service principal KV names (page 9)
    "project_service_principal_AppID_seeding_kv_name":  "variables.project_service_principal_AppID_seeding_kv_name",
    "project_service_principal_OID_seeding_kv_name":    "variables.project_service_principal_OID_seeding_kv_name",
    "project_service_principal_Secret_seeding_kv_name": "variables.project_service_principal_Secret_seeding_kv_name",
    # Other page (page 13)
    "azure_machinelearning_sp_oid": "variables.azure_machinelearning_sp_oid",
    "enableAMPLS":                  "variables.enableAMPLS",
    "databricksOID":                "variables.databricksOID",
    # Security (page 7) — missing from original YAML_MAP
    "disableContributorAccessForUsers": "variables.disableContributorAccessForUsers",
    "disableRBACAdminOnRGForUsers":     "variables.disableRBACAdminOnRGForUsers",
    "disableSubnetJoinAction":          "variables.disableSubnetJoinAction",
    "disableLocalAuth":                 "variables.disableLocalAuth",
    "acrIpWhitelist":                  "variables.acrIpWhitelist",
    # Tags (page 2/global)
    "tag_repository":       "variables.tag_repository",
    "tag_repository_branch":"variables.tag_repository_branch",
    # BYO vNet/Subnets (page 4 Advanced Networking — BYO Subnets section)
    "BYO_subnets":                  "variables.BYO_subnets",
    "network_env_dev":              "variables.network_env_dev",
    "network_env_stage":            "variables.network_env_stage",
    "network_env_prod":             "variables.network_env_prod",
    "subnetCommon":                 "variables.subnetCommon",
    "subnetCommonScoring":          "variables.subnetCommonScoring",
    "subnetCommonPowerbiGw":        "variables.subnetCommonPowerbiGw",
    "subnetProjGenAI":              "variables.subnetProjGenAI",
    "subnetProjAKS":                "variables.subnetProjAKS",
    "subnetProjAKS2":               "variables.subnetProjAKS2",
    "subnetProjACA":                "variables.subnetProjACA",
    "subnetProjACA2":               "variables.subnetProjACA2",
    "subnetProjWebapp":             "variables.subnetProjWebapp",
    "subnetProjDatabricksPublic":   "variables.subnetProjDatabricksPublic",
    "subnetProjDatabricksPrivate":  "variables.subnetProjDatabricksPrivate",
    "byoASEv3":                     "variables.byoASEv3",
    "byoAseFullResourceId":         "variables.byoAseFullResourceId",
    "byoAseAppServicePlanResourceId": "variables.byoAseAppServicePlanResourceId",
    "commonResourceGroup_param":    "variables.commonResourceGroup_param",
    "datalakeName_param":           "variables.datalakeName_param",
    "kvNameFromCOMMON_param":       "variables.kvNameFromCOMMON_param",
    "disable_whitelisting_for_build_agents": "variables.disable_whitelisting_for_build_agents",
}

ENV_MAP = {k: v.split(".")[-1].upper() for k, v in YAML_MAP.items()}
_ENV_OVERRIDES = {
    SCALING_MODE_KEY:         "SCALING_MODE",
    DASHBOARD_KEY:            "AIFACTORY_DASHBOARD_URL",
    # Existing fields: auto-derived key differs from .env template key
    "version_major":          "AIFACTORY_VERSION_MAJOR",
    "version_minor":          "AIFACTORY_VERSION_MINOR",
    "dev_sub_id":             "DEV_SUBSCRIPTION_ID",
    "test_sub_id":            "STAGE_SUBSCRIPTION_ID",
    "prod_sub_id":            "PROD_SUBSCRIPTION_ID",
    "tenantId":               "TENANT_ID",
    "dev_cidr_range":         "DEV_CIDR_RANGE",
    "test_cidr_range":        "STAGE_CIDR_RANGE",
    "prod_cidr_range":        "PROD_CIDR_RANGE",
    "admin_location":         "AIFACTORY_LOCATION",
    "admin_locationSuffix":   "AIFACTORY_LOCATION_SHORT",
    "admin_aifactoryPrefixRG": "AIFACTORY_PREFIX",
    "admin_aifactorySuffixRG": "AIFACTORY_SUFFIX",
    "aifactory_salt":         "AIFACTORY_SALT",
    "useCommonACR":           "USE_COMMON_ACR_FOR_PROJECTS",
    "use_ad_groups":          "USE_AD_GROUPS",
    "admin_keyvaultSoftDeleteDays": "KEYVAULT_SOFT_DELETE",
    "technical_admins_ad_object_id": "PROJECT_MEMBERS",
    "technical_admins_email": "PROJECT_MEMBERS_EMAILS",
    "project_number_000":     "PROJECT_NUMBER",
    "project_IP_whitelist":   "PROJECT_MEMBERS_IP_ADDRESS",
    "runNetworkingVar":       "RUN_JOB1_NETWORKING",
    "enableDeleteForDisabledResources": "ENABLE_DELETE_FOR_DISABLED_RESOURCES",
    "deleteAllServicesForProject":       "DELETE_ALL_SERVICES_FOR_PROJECT",
    "deleteKeyvaultAlso":                "DELETE_KEYVAULT_ALSO",
    "deleteAllForProject":                "DELETE_ALL_FOR_PROJECT",
    # Skip AIFactory-managed diagnostic settings (policy already creates them)
    "skipDiagAOAI":            "SKIP_DIAG_AOAI",
    "skipDiagAISearch":        "SKIP_DIAG_AI_SEARCH",
    "skipDiagAIServices":      "SKIP_DIAG_AI_SERVICES",
    "skipDiagContentSafety":   "SKIP_DIAG_CONTENT_SAFETY",
    "skipDiagVision":          "SKIP_DIAG_VISION",
    "skipDiagSpeech":          "SKIP_DIAG_SPEECH",
    "skipDiagDocIntelligence": "SKIP_DIAG_DOC_INTELLIGENCE",
    "enableDefenderforAISubLevel":      "ENABLE_DEFENDER_FOR_AI_SUB_LEVEL",
    "enableDefenderforAIResourceLevel": "ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL",
    "enableAIFoundry":        "ENABLE_AI_FOUNDRY",
    "addAIFoundry":           "ADD_AI_FOUNDRY",
    "updateAIFoundry":        "UPDATE_AI_FOUNDRY",
    "enableAFoundryCaphost":  "ENABLE_FOUNDRY_CAPHOST",
    "cleanFoundryCaphost":    "CLEAN_FOUNDRY_CAPHOST",
    "enableAIFactoryCreatedDefaultProjectForAIFv2": "ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2",
    "disableAgentNetworkInjection": "DISABLE_AGENT_NETWORK_INJECTION",
    "policyExemptionAssignmentIds": "POLICY_EXEMPTION_ASSIGNMENT_IDS",
    "policyExemptionDefinitionReferenceIds": "POLICY_EXEMPTION_DEFINITION_REFERENCE_IDS",
    "enableAzureMachineLearning": "ENABLE_AZURE_MACHINE_LEARNING",
    "addAzureMachineLearning": "ADD_AZURE_MACHINE_LEARNING",
    "enableAksForAzureML":    "ENABLE_AKS_FOR_AZURE_ML",
    "enableAKS":              "ENABLE_AKS",
    "aksSkuName":             "AKS_SKU_NAME",
    "aksSkuTier":             "AKS_SKU_TIER",
    "aksEnablePrivateCluster": "AKS_ENABLE_PRIVATE_CLUSTER",
    "aksOutboundType":        "AKS_OUTBOUND_TYPE",
    "aksPrivateDNSZone":      "AKS_PRIVATE_DNS_ZONE",
    "aksAzureFirewallPrivateIp": "AKS_AZURE_FIREWALL_PRIVATE_IP",
    "enableAISearch":         "ENABLE_AI_SEARCH",
    "addAISearch":            "ADD_AI_SEARCH",
    "enableAISearchSharedPrivateLink": "ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK",
    "enableAzureOpenAI":      "ENABLE_AZURE_OPENAI",
    "enableAzureAIVision":    "ENABLE_AZURE_AI_VISION",
    "enableAzureSpeech":      "ENABLE_AZURE_SPEECH",
    "enableAIDocIntelligence": "ENABLE_AI_DOC_INTELLIGENCE",
    "enableContentSafety":    "ENABLE_CONTENT_SAFETY",
    "enableCosmosDB":         "ENABLE_COSMOS_DB",
    "enablePostgreSQL":       "ENABLE_POSTGRESQL",
    "enableRedisCache":       "ENABLE_REDIS_CACHE",
    "enableSQLDatabase":      "ENABLE_SQL_DATABASE",
    "enableElasticsearch":    "ENABLE_ELASTICSEARCH",
    "elasticType":            "ELASTIC_TYPE",
    "elasticEmail":           "ELASTIC_EMAIL",
    "elasticFirstName":       "ELASTIC_FIRST_NAME",
    "elasticLastName":        "ELASTIC_LAST_NAME",
    "elasticCompanyName":     "ELASTIC_COMPANY_NAME",
    "elasticDeploymentSize":  "ELASTIC_DEPLOYMENT_SIZE",
    "elasticSku":             "ELASTIC_SKU",
    "enableWebApp":           "ENABLE_WEBAPP",
    "webAppRuntimeVersion":   "WEBAPP_RUNTIME_VERSION",
    "enableContainerApps":    "ENABLE_CONTAINER_APPS",
    "enableAppInsightsDashboard": "ENABLE_APPINSIGHTS_DASHBOARD",
    "enableLogicApps":        "ENABLE_LOGIC_APPS",
    "enableEventHubs":        "ENABLE_EVENT_HUBS",
    "enableBotService":       "ENABLE_BOT_SERVICE",
    "BYOContributorRoleID":   "BYO_CONTRIBUTOR_ROLE_ID",
    "disableSubnetJoinAction": "DISABLE_SUBNET_JOIN_ACTION",
    "vnetResourceGroup_param": "VNET_RESOURCE_GROUP_PARAM",
    "vnetNameFull_param":     "VNET_NAME_FULL_PARAM",
    "BYO_subnets":            "BYO_SUBNETS",
    # Auto-derived ENV keys dropped the underscores in the template .env key.
    # Without these overrides save_github_actions() appends a junk duplicate
    # line (e.g. ENABLEDATABRICKS="true") instead of updating the real key.
    "enableDatabricks":       "ENABLE_DATABRICKS",
    "enableDatafactory":      "ENABLE_DATAFACTORY",
    "enableFunction":         "ENABLE_FUNCTION",
    "functionRuntime":        "FUNCTION_RUNTIME",
    "functionVersion":        "FUNCTION_VERSION",
    "webAppRuntime":          "WEBAPP_RUNTIME",
    "cosmosKind":             "COSMOS_KIND",
    "foundryDeploymentType":  "FOUNDRY_DEPLOYMENT_TYPE",
    "aseSku":                 "ASE_SKU",
    "aseSkuCode":             "ASE_SKU_CODE",
    "aseSkuWorkers":          "ASE_SKU_WORKERS",
    "projectPrefix":          "PROJECT_PREFIX",
    "projectSuffix":          "PROJECT_SUFFIX",
    "commonResourceGroup_param": "COMMON_RESOURCE_GROUP_PARAM",
    "datalakeName_param":     "DATALAKE_NAME_PARAM",
    "kvNameFromCOMMON_param": "KV_NAME_FROM_COMMON_PARAM",
    "subnetCommon":           "SUBNET_COMMON",
    "subnetCommonScoring":    "SUBNET_COMMON_SCORING",
    "subnetCommonPowerbiGw":  "SUBNET_COMMON_POWERBI_GW",
    "subnetProjGenAI":        "SUBNET_PROJ_GENAI",
    "subnetProjAKS":          "SUBNET_PROJ_AKS",
    "subnetProjAKS2":         "SUBNET_PROJ_AKS2",
    "subnetProjACA":          "SUBNET_PROJ_ACA",
    "subnetProjACA2":         "SUBNET_PROJ_ACA2",
    "subnetProjDatabricksPublic":  "SUBNET_PROJ_DATABRICKS_PUBLIC",
    "subnetProjDatabricksPrivate": "SUBNET_PROJ_DATABRICKS_PRIVATE",
    "network_env_dev":        "DEV_NETWORK_ENV",
    "network_env_stage":      "STAGE_NETWORK_ENV",
    "network_env_prod":       "PROD_NETWORK_ENV",
    "subnetProjWebapp":       "SUBNET_PROJ_WEBAPP",
    "byoASEv3":               "BYO_ASEV3",
    "byoAseFullResourceId":   "BYO_ASE_FULL_RESOURCE_ID",
    "byoAseAppServicePlanResourceId": "BYO_ASE_APP_SERVICE_PLAN_RESOURCE_ID",
    "azure_machinelearning_sp_oid": "TENANT_AZUREML_OID",
    "project_service_principal_AppID_seeding_kv_name": "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID",
    "project_service_principal_OID_seeding_kv_name":   "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID",
    "project_service_principal_Secret_seeding_kv_name": "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S",
    "cmkKeyName":             "CMK_KEY_NAME",
    "cmkKeyVersion":          "CMK_KEY_VERSION",
    "cmkDisableForAISearch":  "CMK_DISABLE_FOR_AI_SEARCH",
    "cmkDisableForFoundry":   "CMK_DISABLE_FOR_FOUNDRY",
    "updateKeyvaultRbac":     "UPDATE_KEYVAULT_RBAC",
    # Model deployment keys — auto-derived keys miss underscores
    "deployModel_gpt_X":                   "DEPLOY_MODEL_GPT_X",
    "modelGPTXName":                       "MODEL_GPTX_NAME",
    "modelGPTXVersion":                    "MODEL_GPTX_VERSION",
    "modelGPTXSku":                        "MODEL_GPTX_SKU",
    "modelGPTXCapacity":                   "MODEL_GPTX_CAPACITY",
    "deployModel_text_embedding_ada_002":  "DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002",
    "deployModel_text_embedding_3_large":  "DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE",
    "deployModel_text_embedding_3_small":  "DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL",
    "default_embedding_capacity":          "DEFAULT_EMBEDDING_CAPACITY",
    "deployModel_gpt_54_mini":             "DEPLOY_MODEL_GPT_54_MINI",
    "default_gpt_54_mini_version":         "DEFAULT_GPT_54_MINI_VERSION",
    "deployModel_gpt_4o":                  "DEPLOY_MODEL_GPT_4O",
    "default_gpt_4o_version":              "DEFAULT_GPT_4O_VERSION",
    "default_gpt_capacity":                "DEFAULT_GPT_CAPACITY",
    "default_model_sku":                   "DEFAULT_MODEL_SKU",
    # Seeding KeyVault — .env uses AIFACTORY_SEEDING_KEYVAULT_* naming
    "dev_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "dev_admin_bicep_kv_fw":    "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "dev_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
    # New fields
    "enableAIServices":       "ENABLE_AI_SERVICES",
    "enableAIFoundryHub":     "ENABLE_AI_FOUNDRY_HUB",
    "addAIFoundryHub":        "ADD_AI_FOUNDRY_HUB",
    "foundryApiManagementResourceId": "FOUNDRY_API_MANAGEMENT_RESOURCE_ID",
    "enableBing":             "ENABLE_BING",
    "enableBingCustomSearch": "ENABLE_BING_CUSTOM_SEARCH",
    "bingCustomSearchSku":    "BING_CUSTOM_SEARCH_SKU",
    "postGresAdminEmails":    "POSTGRES_ADMIN_EMAILS",
    "enableDatafactoryCommon": "ENABLE_DATAFACTORY_COMMON",
    "updateRbac":             "UPDATE_RBAC",
    "debugEnableCleaning":    "DEBUG_ENABLE_CLEANING",
    "enableRetries":          "ENABLE_RETRIES",
    "retryMinutes":           "RETRY_MINUTES",
    "retryMinutesExtended":   "RETRY_MINUTES_EXTENDED",
    "maxRetryAttempts":       "MAX_RETRY_ATTEMPTS",
    "debug_disable_validation_tasks": "DEBUG_DISABLE_VALIDATION_TASKS",
    # Databricks managed identity
    "databricksOID":          "DATABRICKS_OID",
    # Networking flags — auto-derived keys miss underscores
    "allowPublicAccessWhenBehindVnet":  "ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET",
    "enablePublicGenAIAccess":          "ENABLE_PUBLIC_GENAI_ACCESS",
    "enablePublicAccessWithPerimeter":  "ENABLE_PUBLIC_ACCESS_WITH_PERIMETER",
    "centralDnsZoneByPolicyInHub":      "CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB",
    "enableAIFactoryHub":              "ENABLE_AI_FACTORY_HUB",
    "privDnsSubscription_param":        "PRIV_DNS_SUBSCRIPTION_PARAM",
    "privDnsResourceGroup_param":       "PRIV_DNS_RESOURCE_GROUP_PARAM",
    # Monitoring / ACR / Security — auto-derived keys miss underscores
    "diagnosticSettingLevel":           "DIAGNOSTIC_SETTING_LEVEL",
    "acr_adminUserEnabled":             "ACR_ADMIN_USER_ENABLED",
    "addBastionHost":                   "ADD_BASTION_HOST",
    "enableAdminVM":                    "ENABLE_ADMIN_VM",
    "useSelfHostedBuildAgent":          "USE_SELF_HOSTED_BUILD_AGENT",
    "selfHostedRunnerLabel":            "SELF_HOSTED_RUNNER_LABEL",
    "adminVMBuildAgentPool":            None,
    "adminVMBuildAgentName":            None,
    "enableAMPLS":                      "ENABLE_AMPLS",
    "disableContributorAccessForUsers": "DISABLE_CONTRIBUTOR_ACCESS_FORUSERS",
    "disableRBACAdminOnRGForUsers":     "DISABLE_RBAC_ADMIN_ON_RG_FORUSERS",
    "disableLocalAuth":                 "DISABLE_LOCAL_AUTH",
    "acrIpWhitelist":                   "ACR_IP_WHITELIST",
    # Azure ML SP OID — renamed from TENANT_AZUREML_OID in v1.24+ workflows
    "azure_machinelearning_sp_oid":     "AZURE_MACHINELEARNING_SP_OID",
    # Tags
    "tag_repository":                   "TAG_REPOSITORY",
    "tag_repository_branch":            "TAG_REPOSITORY_BRANCH",
    # Admin VM
    "admin_username":         "ADMIN_USERNAME",
    "admin_hybridBenefit":    "ADMIN_HYBRID_BENEFIT",   # was auto-deriving to ADMIN_HYBRIDBENEFIT
    "disable_whitelisting_for_build_agents": "DISABLE_WHITELISTING_FOR_BUILD_AGENTS",
    # BYO network base names (GHA-only, no YAML equivalent)
    "vnet_resource_group_base": "VNET_RESOURCE_GROUP_BASE",
    "vnet_name_base":           "VNET_NAME_BASE",
    "subnet_common_base":       "SUBNET_COMMON_BASE",
    # Project VM enable flag maps to GHA key
    "enableProjectVM":          "SERVICE_SETTING_DEPLOY_PROJECT_VM",
    # Common service principal seeding-KV key names
    "inputCommonSPIDKey":           "INPUT_COMMON_SPID_KEY",
    "inputCommonSPSecretKey":       "INPUT_COMMON_SP_SECRET_KEY",
    "commonServicePrincipleOIDKey": "COMMON_SERVICE_PRINCIPLE_OID_KEY",
    # AI Search overrides — update to the newer env-key names used in v1.24+ workflows
    "admin_aiSearchTier":       "ADMIN_AI_SEARCH_TIER",
    "admin_semanticSearchTier": "ADMIN_SEMANTIC_SEARCH_TIER",
    # GitHub Actions – repository setup (GHA orchestrator only, not in YAML_MAP)
    "github_username":            "GITHUB_USERNAME",
    "github_use_ssh":             "GITHUB_USE_SSH",
    "github_template_repo":       "GITHUB_TEMPLATE_REPO",
    "github_new_repo":            "GITHUB_NEW_REPO",
    "github_new_repo_visibility": "GITHUB_NEW_REPO_VISIBILITY",
}
ENV_MAP.update(_ENV_OVERRIDES)

_GITHUB_REPOSITORY_STATE_KEYS = (
    "github_username",
    "github_use_ssh",
    "github_template_repo",
    "github_new_repo",
    "github_new_repo_visibility",
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_STATE: dict = {
    SCALING_MODE_KEY: DEFAULT_SCALING_MODE,
    DASHBOARD_KEY: "",
    "orchestrator": "ado",
    "_hub_topology": "",
    "_save_folder": "",           # base folder chosen by user for project file output
    "_also_update_git": True,     # if True, also write to actual pipeline vars location
    # GitHub Actions fields (GHA orchestrator only)
    "github_username": "",
    "github_use_ssh": "false",
    "github_template_repo": "azure/enterprise-scale-aifactory",
    "github_new_repo": "",
    "github_new_repo_visibility": "public",
    "admin_aifactorySuffixRG": "-001",
    "projectPrefix": "",  "projectSuffix": "",
    "version_minor": "24", "version_major": "1",
    "version_branch": "release/v.1.24",
    "network_mode": "public",
    "allowPublicAccessWhenBehindVnet": "true",
    "enablePublicGenAIAccess": "true",
    "enablePublicAccessWithPerimeter": "true",
    "dev_sub_id": "", "test_sub_id": "", "prod_sub_id": "",
    "tenantId": "",
    "dev_cidr_range": "0", "test_cidr_range": "64", "prod_cidr_range": "128",
    "common_vnet_cidr": "172.16.XX.0/18",
    "common_subnet_cidr": "172.16.XX.0/26",
    "common_subnet_scoring_cidr": "172.16.XX.64/26",
    "common_pbi_subnet_name": "snet-esml-cmn-pbi-001",
    "common_pbi_subnet_cidr": "172.16.XX.128/26",
    "common_bastion_subnet_name": "AzureBastionSubnet",
    "common_bastion_subnet_cidr": "172.16.XX.192/26",
    "centralDnsZoneByPolicyInHub": "false",
    "enableAIFactoryHub": "false",
    "privDnsSubscription_param": "", "privDnsResourceGroup_param": "",
    "vnetResourceGroup_param": "", "vnetNameFull_param": "",
    "disableAgentNetworkInjection": "true",
    "policyExemptionAssignmentIds": "[]",
    "policyExemptionDefinitionReferenceIds": "[]",
    "enableAISearchSharedPrivateLink": "true",
    "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
    "admin_aifactoryPrefixRG": "mrvel-1-",
    "aifactory_salt": "",
    "tag_costceter_common": "9999",
    "technical_admins_email": "", "technical_admins_ad_object_id": "",
    "use_ad_groups": "true",
    "dev_admin_bicep_input_keyvault_subscription": "",
    "dev_admin_bicep_kv_fw_rg": "", "dev_admin_bicep_kv_fw": "",
    "test_admin_bicep_input_keyvault_subscription": "",
    "test_admin_bicep_kv_fw_rg": "", "test_admin_bicep_kv_fw": "",
    "prod_admin_bicep_input_keyvault_subscription": "",
    "prod_admin_bicep_kv_fw_rg": "", "prod_admin_bicep_kv_fw": "",
    "cmk": "false",
    "cmkKeyName": "aifactory-cmk-key",
    "cmkKeyVersion": "",
    "cmkDisableForAISearch": "true",
    "cmkDisableForFoundry": "true",
    "updateKeyvaultRbac": "false",
    "disable_whitelisting_for_build_agents": "false",
    "admin_keyvaultSoftDeleteDays": "7",
    "useCommonACR": "true",
    "enableDeleteForDisabledResources": "true",
    "deleteAllServicesForProject": "false",
    "deleteKeyvaultAlso": "false",
    "deleteAllForProject": "false",
    "disableSubnetJoinAction": "false",
    "admin_aiSearchTier": "basic",
    "admin_semanticSearchTier": "free",
    "deployModel_gpt_X": "false",
    "modelGPTXName": "gpt-5-mini", "modelGPTXVersion": "",
    "modelGPTXSku": "DataZoneStandard", "modelGPTXCapacity": "30",
    "deployModel_text_embedding_ada_002": "true",
    "deployModel_text_embedding_3_large": "true",
    "deployModel_text_embedding_3_small": "false",
    "default_embedding_capacity": "25",
    "deployModel_gpt_54_mini": "false",
    "default_gpt_54_mini_version": "2026-03-17",
    "deployModel_gpt_4o": "false",
    "default_gpt_4o_version": "2024-11-20",
    "default_gpt_capacity": "40", "default_model_sku": "Standard",
    "enableDefenderforAISubLevel": "false",
    "enableDefenderforAIResourceLevel": "false",
    "addBastionHost": "false", "enableAdminVM": "false",
    "useSelfHostedBuildAgent": "false",
    "selfHostedRunnerLabel": "aifactory-admin-vm",
    "adminVMBuildAgentPool": "Default",
    "adminVMBuildAgentName": "",
    "admin_username": "adminuser",
    "tag_costcenter": "1234", "diagnosticSettingLevel": "gold",
    "skipDiagAOAI": "true",
    "skipDiagAISearch": "true",
    "skipDiagAIServices": "true",
    "skipDiagContentSafety": "true",
    "skipDiagVision": "true",
    "skipDiagSpeech": "true",
    "skipDiagDocIntelligence": "true",
    "tag_repository": "aifactory", "tag_repository_branch": "aifactory-001",
    "acr_adminUserEnabled": "false", "acr_dedicated": "true",
    "acr_SKU": "Premium", "admin_hybridBenefit": "true",
    "acrIpWhitelist": "",
    "disableContributorAccessForUsers": "false",
    "disableRBACAdminOnRGForUsers": "false",
    "disableLocalAuth": "true",
    "enableProjectVM": "false",
    # Common SP seeding-KV key names (defaults match template)
    "inputCommonSPIDKey":           "esml-common-sp-id",
    "inputCommonSPSecretKey":       "esml-common-sp-secret",
    "commonServicePrincipleOIDKey": "esml-common-sp-oid",
    # BYO network base names
    "vnet_resource_group_base": "esml-common",
    "vnet_name_base": "vnt-esmlcmn",
    "subnet_common_base": "snet-esml-cmn-001",
    # BYO Subnets (page 4 Advanced Networking)
    "BYO_subnets":                  "false",
    "network_env_dev":              "dev-",
    "network_env_stage":            "tst2-",
    "network_env_prod":             "prd-",
    "subnetCommon":                 "snet-dev-esml-cmn-001",
    "subnetCommonScoring":          "snet-<network_env>esml-cmn-001-scoring",
    "subnetCommonPowerbiGw":        "snet-esml-cmn-pbi-001",
    "subnetProjGenAI":              "snt-dev-prj<xxx>-genai",
    "subnetProjAKS":                "snt-prj<xxx>-aks",
    "subnetProjAKS2":               "snt-<network_env>prj<xxx>-aks2",
    "subnetProjACA":                "snt-prj<xxx>-aca",
    "subnetProjACA2":               "snt-prj<xxx>-aca2",
    "subnetProjWebapp":             "snt-prj<xxx>-webapp",
    "subnetProjDatabricksPublic":   "snt-prj001-dbxpub",
    "subnetProjDatabricksPrivate":  "snt-prj<xxx>-dbxpriv",
    "byoASEv3":                     "false",
    "byoAseFullResourceId":         "/subscriptions/...yourASEnameS2",
    "byoAseAppServicePlanResourceId": "",
    "commonResourceGroup_param":    "",
    "datalakeName_param":           "",
    "kvNameFromCOMMON_param":       "",
    "project_number_000": "001", "runNetworkingVar": "true",
    "enableAIFoundry": "true", "addAIFoundry": "false",
    "enableAFoundryCaphost": "true", "cleanFoundryCaphost": "true", "updateAIFoundry": "false",
    "foundryDeploymentType": "2",
    "enableAIFactoryCreatedDefaultProjectForAIFv2": "true",
    "enableAzureMachineLearning": "false",
    "addAzureMachineLearning": "false",
    "enableDatabricks": "false", "enableDatafactory": "false",
    "enableAksForAzureML": "true",
    "enableAKS": "false",
    "aksSkuName": "Base",
    "aksSkuTier": "Standard",
    "aksEnablePrivateCluster": "true",
    "aksOutboundType": "loadBalancer",
    "aksPrivateDNSZone": "system",
    "aksAzureFirewallPrivateIp": "",
    "enableAISearch": "true", "addAISearch": "false",
    "enableAzureOpenAI": "false", "enableAzureAIVision": "false",
    "enableAzureSpeech": "false", "enableAIDocIntelligence": "false",
    "enableContentSafety": "false",
    "enableCosmosDB": "true", "cosmosKind": "GlobalDocumentDB",
    "enablePostgreSQL": "true",
    "enableRedisCache": "false", "enableSQLDatabase": "false",
    "enableElasticsearch": "false",
    "elasticType": "ElasticCloud",
    "elasticEmail": "admin@example.com",
    "elasticFirstName": "AI",
    "elasticLastName": "Factory",
    "elasticCompanyName": "Organization",
    "elasticDeploymentSize": "small",
    "elasticSku": "ess-consumption-2024_Monthly",
    "enableFunction": "true",
    "functionRuntime": "python", "functionVersion": "3.11",
    "enableWebApp": "true",
    "webAppRuntime": "python", "webAppRuntimeVersion": "3.11",
    "aseSku": "IsolatedV2", "aseSkuCode": "I1v2", "aseSkuWorkers": "1",
    "enableContainerApps": "true",
    "enableAppInsightsDashboard": "true",
    "enableLogicApps": "true",
    "enableEventHubs": "false", "enableBotService": "true",
    # New fields
    "enableAIServices": "false", "enableAIFoundryHub": "false", "addAIFoundryHub": "false",
    "foundryApiManagementResourceId": "",
    "enableBing": "false", "enableBingCustomSearch": "false", "bingCustomSearchSku": "G2",
    "postGresAdminEmails": "",
    "enableDatafactoryCommon": "false",
    "updateRbac": "false",
    "debugEnableCleaning": "true",
    "enableRetries": "false", "retryMinutes": "5", "retryMinutesExtended": "15", "maxRetryAttempts": "1",
    "debug_disable_validation_tasks": "false",
    "project_IP_whitelist": "",
    # ADO service connections
    "dev_service_connection": "", "test_service_connection": "", "prod_service_connection": "",
    "dev_seeding_kv_service_connection": "", "test_seeding_kv_service_connection": "",
    "prod_seeding_kv_service_connection": "",
    # Project service principal KV names
    "project_service_principal_AppID_seeding_kv_name":  "esml-project001-sp-id",
    "project_service_principal_OID_seeding_kv_name":    "esml-project001-sp-oid",
    "project_service_principal_Secret_seeding_kv_name": "esml-project001-sp-secret",
    # Other
    "azure_machinelearning_sp_oid": "b6b19655-d941-419f-abe6-8378b92cb8d2",
    "enableAMPLS":   "false",
    "databricksOID": "6f63d607-fdce-426d-8f92-1235074fbeac",
}

# ---------------------------------------------------------------------------
# Register per-environment SKU fields (Dev / Stage&Prod) into the maps.
# NOTE: YAML keys are added *after* ENV_MAP auto-derivation (above) on purpose,
# so YAML-only SKUs (AI Search, Elastic — no .env line) are never written as
# junk lines into the .env file.  Only SKUs with an env_base get an ENV_MAP
# entry; the rest are persisted to variables.yaml only.
# ---------------------------------------------------------------------------
for _base, _label, _group, _default, _choices, _env_base in SKU_FIELDS:
    for _suffix, _env_suffix in (("Dev", "_DEV"), ("StageProd", "_STAGEPROD")):
        _sk = f"{_base}{_suffix}"
        YAML_MAP[_sk] = f"variables.{_sk}"
        DEFAULT_STATE[_sk] = _default
        if _env_base:
            ENV_MAP[_sk] = f"{_env_base}{_env_suffix}"


# ---------------------------------------------------------------------------
# Template pre-loader
# ---------------------------------------------------------------------------
def _find_template_yaml():
    rel = os.path.join("template-files", "variables.yaml")
    candidates = [
        _res(rel),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), rel),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel),
    ]
    for p in candidates:
        if os.path.isfile(p): return p
    return candidates[0]

def _load_template_defaults():
    try:
        with open(_find_template_yaml(), "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}
    result = {}
    for state_key, dotpath in YAML_MAP.items():
        yaml_key = dotpath.split(".")[-1]
        pat = re.compile(
            r'^\s{0,8}' + re.escape(yaml_key) +
            r'\s*:\s*(?:"([^"#\n]*)"|\'([^\'#\n]*)\'|((?:[^#\n\'"]\S*)?[^#\n\s\'"]+?[^#\n]*))\s*(?:#.*)?$',
            re.MULTILINE)
        m = pat.search(content)
        if m:
            val = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if val: result[state_key] = val
    aP  = result.get("allowPublicAccessWhenBehindVnet","").lower()
    eP  = result.get("enablePublicGenAIAccess","").lower()
    ePP = result.get("enablePublicAccessWithPerimeter","").lower()
    if aP=="false" and eP=="false":     result["network_mode"]="private"
    elif aP=="true" and eP=="true" and ePP=="false": result["network_mode"]="hybrid"
    elif aP=="true" and eP=="true" and ePP=="true":  result["network_mode"]="public"
    major = result.get("version_major","1")
    minor = result.get("version_minor","24")
    result["_version_str"] = f"{major}.{minor}"
    return result


HUB_FLAG_KEYS = ("centralDnsZoneByPolicyInHub", "enableAIFactoryHub")


def hub_configuration(values):
    """Normalize intent, migrating legacy own-hub metadata before merging defaults."""
    result = dict(values)
    result.setdefault("centralDnsZoneByPolicyInHub", "false")
    result.setdefault("enableAIFactoryHub",
                      "true" if values.get("_hub_topology") == "own-hub" else "false")
    for key in HUB_FLAG_KEYS:
        value = result[key]
        if isinstance(value, bool):
            result[key] = str(value).lower()
        elif isinstance(value, str) and value.strip().lower() in ("true", "false"):
            result[key] = value.strip().lower()
    return result


def hub_validation_issues(state):
    values = hub_configuration(state)
    return [{"field": key, "code": "invalid_boolean", "message": f"{key} must be true or false"}
            for key in HUB_FLAG_KEYS
            if not isinstance(values[key], str) or values[key] not in ("true", "false")]


def require_hub_configuration(state):
    issues = hub_validation_issues(state)
    if issues:
        raise ValueError("; ".join(issue["message"] for issue in issues))


def _restore_hub_flags(state, supplied):
    values = hub_configuration(supplied)
    state.update({key: values[key] for key in HUB_FLAG_KEYS})


def new_configuration_defaults():
    """Use the selected preset for fresh drafts, never rewrite imported addressing."""
    state = copy.deepcopy(DEFAULT_STATE)
    state.update(_load_template_defaults())
    mode = state.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE)
    if mode in SCALING_MODES and any(
        all(state.get(key) == value for key, value in profile.items())
        for profile in SCALING_NETWORK_PROFILES
    ):
        apply_scaling_mode(state, mode, apply_defaults=True)
    return state

# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------
def _bool_str(val): return str(val).lower() in ("true","1","yes")

# Global registry of (state_key, tk_var, is_bool, state_dict)
# Populated by _make_entry / _make_entry_w / _make_checkbox / _make_combo.
# Used by _sync_vars_from_state() to push loaded state back into all widgets.
_VAR_REGISTRY: list = []
_WIDGET_REGISTRY: dict = {}   # state_key → list of (widget, display_label)


def _friendly_label(key: str) -> str:
    """Convert snake_case / camelCase to readable Title Case."""
    import re as _re
    s = _re.sub(r'([A-Z])', r' \1', key)
    words = _re.sub(r'[_\s]+', ' ', s).strip().split()
    return ' '.join(w.capitalize() for w in words)


def _sync_vars_from_state(state: dict) -> None:
    """Push every value in *state* into the registered tk vars so that
    the UI reflects a freshly-loaded snapshot."""
    for state_key, var, is_bool, reg_state in _VAR_REGISTRY:
        # Only sync vars that belong to the same state dict
        if reg_state is not state:
            continue
        val = state.get(state_key)
        if val is None:
            continue
        try:
            if is_bool:
                var.set(_bool_str(str(val)))
            else:
                var.set(str(val))
        except Exception:
            pass


def _make_checkbox(parent, text, state_key, state, row, col=0, columnspan=2):
    """Returns (BooleanVar, Checkbutton widget)."""
    var = tk.BooleanVar(value=_bool_str(state.get(state_key,"false")))
    cb  = ttk.Checkbutton(parent, text=text, variable=var,
                          command=lambda: state.update({state_key:"true" if var.get() else "false"}))
    cb.grid(row=row, column=col, columnspan=columnspan, sticky="w", padx=4, pady=2)
    _VAR_REGISTRY.append((state_key, var, True, state))
    _WIDGET_REGISTRY.setdefault(state_key, []).append((cb, text))
    return var, cb

def _make_entry(parent, label, state_key, state, row, placeholder="", width=42):
    lbl = ttk.Label(parent, text=label)
    lbl.grid(row=row, column=0, sticky="w", padx=4, pady=2)
    var = tk.StringVar(value=state.get(state_key,""))
    ent = ttk.Entry(parent, textvariable=var, width=width)
    ent.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
    if placeholder and not var.get():
        ent.insert(0, placeholder); ent.configure(foreground="grey")
        def _fin(e,_e=ent,_p=placeholder):
            if _e.get()==_p: _e.delete(0,tk.END); _e.configure(foreground="black")
        def _fout(e,_e=ent,_p=placeholder):
            if not _e.get(): _e.insert(0,_p); _e.configure(foreground="grey")
        ent.bind("<FocusIn>", _fin); ent.bind("<FocusOut>", _fout)
    var.trace_add("write", lambda *a,k=state_key,v=var: state.update({k:v.get()}))
    _VAR_REGISTRY.append((state_key, var, False, state))
    _WIDGET_REGISTRY.setdefault(state_key, []).append((ent, label))
    return var, lbl, ent

def _set_field_state(widget, error):
    widget.configure(style="Error.TEntry" if error else "TEntry")

def _make_entry_w(parent, label, state_key, state, row, placeholder="", width=42):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=2)
    var = tk.StringVar(value=state.get(state_key,""))
    ent = ttk.Entry(parent, textvariable=var, width=width)
    ent.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
    if placeholder and not var.get():
        ent.insert(0, placeholder); ent.configure(foreground="grey")
        def _fin(e,_e=ent,_p=placeholder):
            if _e.get()==_p: _e.delete(0,tk.END); _e.configure(foreground="black")
        def _fout(e,_e=ent,_p=placeholder):
            if not _e.get(): _e.insert(0,_p); _e.configure(foreground="grey")
        ent.bind("<FocusIn>", _fin); ent.bind("<FocusOut>", _fout)
    def _on_write(*a):
        state.update({state_key:var.get()}); _set_field_state(ent, False)
    var.trace_add("write", _on_write)
    _VAR_REGISTRY.append((state_key, var, False, state))
    _WIDGET_REGISTRY.setdefault(state_key, []).append((ent, state_key))
    return var, ent

def _make_combo(parent, label, state_key, state, row, values, width=20):
    lbl = ttk.Label(parent, text=label)
    lbl.grid(row=row, column=0, sticky="w", padx=4, pady=2)
    var = tk.StringVar(value=state.get(state_key, values[0] if values else ""))
    cb  = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=width)
    cb.grid(row=row, column=1, sticky="w", padx=4, pady=2)
    var.trace_add("write", lambda *a,k=state_key,v=var: state.update({k:v.get()}))
    _VAR_REGISTRY.append((state_key, var, False, state))
    _WIDGET_REGISTRY.setdefault(state_key, []).append((cb, label))
    return var, cb, lbl

def _hint(parent, text, row, col=1, colspan=3):
    lbl = ttk.Label(parent, text=text, foreground="#888888", font=("Segoe UI", 8))
    lbl.grid(row=row, column=col, columnspan=colspan, sticky="w", padx=4)
    return lbl

def _hint_nw(parent, text, row, col=0, colspan=3):
    """Hint from col 0."""
    lbl = ttk.Label(parent, text=text, foreground="#888888", font=("Segoe UI", 8))
    lbl.grid(row=row, column=col, columnspan=colspan, sticky="w", padx=4)
    return lbl

# ---------------------------------------------------------------------------
# Tooltips / contextual help
# ---------------------------------------------------------------------------
# Curated help text keyed by state_key.  Fields without an entry fall back to
# showing their pipeline-variable name (see _Tooltip attach logic).  Keep each
# entry short (1-3 lines) so the popup stays compact.
HELP_TEXT = {
    DASHBOARD_KEY:
        "Existing Azure Portal AI Factory dashboard URL; never deploys a dashboard. "
        "Leave empty when not configured.",
    "orchestrator":
        "Pipeline target. ADO writes variables.yaml for Azure DevOps; "
        "GHA writes a .env for GitHub Actions.",
    "network_mode":
        "private  = no public access (most secure)\n"
        "hybrid   = public GenAI + VNet\n"
        "public   = public access with network perimeter",
    "project_number_000":
        "Three-digit project id (e.g. 001). Drives the resource-group suffix "
        "and the name of the saved variables file.",
    "admin_aifactorySuffixRG":
        "Resource-group suffix that identifies this scale set (e.g. -001).",
    "aifactory_salt":
        "Short random salt used to make global resource names unique. "
        "Never reuse a salt across scale sets; left blank by design on load.",
    "deleteAllServicesForProject":
        "DESTRUCTIVE. When the pipeline runs it deletes all services in the "
        "project resource group (except storage/keyvault/logs) and purges "
        "soft-deleted resources. Leave unchecked unless you mean it.",
    "_save_folder":
        "Base folder for generated files. The wizard writes to "
        "<folder>/config-wizard/project-<id>/.",
    "_also_update_git":
        "Also write the variables file straight into the pipeline's GIT path "
        "(esml-infra/... for ADO, ../.env for GHA) when saving.",
    "enableAISearchSharedPrivateLink":
        "Create a shared private link from AI Search to dependent services "
        "(needed for private-network indexing).",
    "admin_aiSearchTier":
        "Azure AI Search SKU. 'free' has no SLA; pick 'basic'+ for production.",
    "admin_semanticSearchTier":
        "Semantic ranker tier for AI Search. 'disabled' turns it off.",
    "inputCommonSPIDKey":
        "Optional. Seeding KV secret name holding the common SP App ID.",
    "inputCommonSPSecretKey":
        "Optional. Seeding KV secret name holding the common SP secret.",
    "commonServicePrincipleOIDKey":
        "Optional. Seeding KV secret name holding the common SP Object ID.",
    "project_service_principal_AppID_seeding_kv_name":
        "Optional. Seeding KV secret name holding the project SP App ID.",
    "project_service_principal_OID_seeding_kv_name":
        "Optional. Seeding KV secret name holding the project SP Object ID.",
    "project_service_principal_Secret_seeding_kv_name":
        "Optional. Seeding KV secret name holding the project SP secret.",
}
class _Tooltip:
    """Lightweight hover tooltip for any Tk/ttk widget. Fully offline."""
    _DELAY_MS = 550

    def __init__(self, widget, text, delay=None):
        self.widget = widget
        self.text = text
        self.delay = delay if delay is not None else self._DELAY_MS
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _evt=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.attributes("-topmost", True)
        except Exception:
            pass
        frm = tk.Frame(tw, bg="#2b2b2b", bd=1, relief="solid")
        frm.pack()
        tk.Label(frm, text=self.text, bg="#2b2b2b", fg="#f0f0f0",
                 font=("Segoe UI", 8), justify="left",
                 wraplength=320, padx=8, pady=5).pack()

    def _hide(self, _evt=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def _attach_tooltips_from_registry():
    """Bind a hover tooltip to every registered widget.  Uses curated
    HELP_TEXT where available, otherwise shows the pipeline-variable name."""
    for state_key, entries in _WIDGET_REGISTRY.items():
        help_txt = HELP_TEXT.get(state_key)
        if not help_txt:
            env_name = ENV_MAP.get(state_key, state_key)
            help_txt = f"Pipeline variable:\n{env_name}"
        for (widget, _label) in entries:
            if getattr(widget, "_has_tooltip", False):
                continue
            try:
                _Tooltip(widget, help_txt)
                widget._has_tooltip = True
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Scrollable frame
# ---------------------------------------------------------------------------
class _ScrollFrame(tk.Frame):
    def __init__(self, parent, bg="#f5f5f5", **kw):
        super().__init__(parent, bg=bg, **kw)
        self._canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg=bg)
        # Use classic tk.Scrollbar so we can set an explicit pixel width
        vbar = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview,
                            width=14, troughcolor="#d0d0d0", bg="#a0a0a0")
        self._canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win_id = self._canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._win_id, width=e.width))
        self.inner.bind_all("<MouseWheel>", lambda e: self._canvas.yview_scroll(int(-1*(e.delta/120)),"units"))

    def refresh_scroll(self):
        self.inner.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))


# ---------------------------------------------------------------------------
# Base page — advanced mode support
# ---------------------------------------------------------------------------
class WizardPage(tk.Frame):
    def __init__(self, parent, state):
        super().__init__(parent, bg="#f5f5f5")
        self.state = state
        self.columnconfigure(1, weight=1)
        self._adv_only: list = []   # widgets shown only in advanced mode
        self._sf: "_ScrollFrame | None" = None  # set by scroll pages

    def on_enter(self): pass
    def on_leave(self): return True

    def set_advanced_mode(self, advanced: bool):
        """Show or hide advanced-only widgets.  Called by WizardApp on toggle."""
        for w in self._adv_only:
            if advanced:
                w.grid()
            else:
                w.grid_remove()
        if self._sf:
            self._sf.refresh_scroll()

    def _section(self, text, row, parent=None):
        p = parent or self
        ttk.Separator(p, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=(10,2))
        ttk.Label(p, text=text, font=("Segoe UI",9,"bold")).grid(row=row+1, column=0, columnspan=4, sticky="w", padx=4)
        return row+2

    def _hint(self, text, row, col=1, colspan=3, parent=None):
        return _hint(parent or self, text, row, col, colspan)


# ---------------------------------------------------------------------------
# HOW-TO guides (shown as tabs on the Intro page)
# ---------------------------------------------------------------------------
# Colored terminal transcript: each item is (role, text) where role is
# "plain" (light grey), "prompt" (yellow — what the script asks), or
# "answer" (red — what the user types).
TERMINAL_GH_VARS = [
    ("plain",  "$ bash 10-GH-create-or-update-github-variables.sh\n"),
    ("prompt", "Select environment to run (d=DEV, s=STAGE, p=PROD, a=ALL). Default is DEV:\n"),
    ("plain",  "env [d/s/p/a]: "), ("answer", "d"), ("plain", "\n"),
    ("prompt", "Do you want to update a single parameter only?\n"),
    ("prompt", "Enter the parameter name (e.g., ENABLE_ELASTICSEARCH) or press Enter to update all:\n"),
    ("plain",  "parameter name:\n"),
    ("plain",  "Will update all parameters.\n"),
    ("prompt", "Optional: resume from operation number (1-based). Leave empty to start from 1.\n"),
    ("plain",  "TIP: Set to 82 to update Project number and ENABLE_ flags.\n"),
    ("plain",  "start_from_op:\n"),
    ("prompt", "Do you want to overwrite AZURE_CREDENTIALS with dummy value? Usually only the "
               "1st time this is needed, to create the variable in Github (Enter 'y' or 'n')\n"),
    ("plain",  "overwrite_azure_credential: "), ("answer", "n"), ("plain", "\n"),
    ("plain",  "Bootstraps config from .env as Github environment variables and secrets.\n"),
    ("plain",  "================================================\n"),
    ("plain",  "GitHub Variables Update Script\n"),
    ("plain",  "================================================"),
]

HOWTO_FIRST_TIME = [
    ("h1", "Set it up the first time (import settings)"),
    ("body", "Do this once per AI Factory. After the first person imports and saves the "
             "settings, everyone else simply fetches the correct state from your GIT repo."),
    ("h2", "Prerequisites"),
    ("bullet", "Role: Developer with the repo cloned and the submodule activated "
               "(see the 'Update AI Factory' instructions)."),
    ("bullet", "Installed on your laptop: Bash terminal, Azure CLI, GitHub CLI, Python."),
    ("bullet", "Allow your OS to run the downloaded wizard (macOS/Windows may block "
               "'insecure' applications)."),
    ("link", "Prerequisites - AI Factory configuration Wizard",
             "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/install_config_wizard/readme.md"),
    ("h2", "1) Download the wizard and run it"),
    ("bullet", "Download the wizard executable and start it."),
    ("h2", "2) Import settings (Orchestrator & destination page)"),
    ("bullet", "On the 'Orchestrator & destination' page, open the 'Import File' section."),
    ("bullet", "Browse to an existing .env (GitHub Actions) or variables.yaml (Azure DevOps) "
               "and import it."),
    ("bullet", "This loads ~100 parameters at once, so you do not have to set them by hand."),
    ("bullet", "If the settings already exist in GIT, someone did this before you — just "
               "import them and continue to step 'Add a project'."),
    ("h2", "3) Save"),
    ("bullet", "Save 'State' — stores the project + scale set locally and under the wizard's "
               "metadata folder in GIT (for all users to fetch)."),
    ("bullet", "Save '.env' (or 'variables.yaml' for Azure DevOps) — overwrites the actual "
               "file that your pipeline uses."),
    ("h2", "4) Apply it to your pipeline"),
    ("bullet", "Back in VS Code you will see the edited .env file at the repo root."),
    ("bullet", "Update the GitHub Action variables by running the root '10-' script in a "
               "Bash terminal:"),
    ("code", "bash 10-GH-create-or-update-github-variables.sh"),
    ("body", "The script is interactive. Example answers you can choose from:"),
    ("bullet", "env [d/s/p/a]: d = DEV, s = STAGE, p = PROD, a = ALL  (default DEV)."),
    ("bullet", "parameter name: press Enter to update ALL, or type one key "
               "(e.g. ENABLE_ELASTICSEARCH) to update just that parameter."),
    ("bullet", "start_from_op: press Enter to start from 1, or set an operation number "
               "(e.g. 82 to update the Project number and ENABLE_ flags)."),
    ("bullet", "overwrite_azure_credential: y / n  (usually only 'y' the first time, to "
               "create the AZURE_CREDENTIALS variable in GitHub)."),
    ("terminal", TERMINAL_GH_VARS),
]

HOWTO_ADD_PROJECT = [
    ("h1", "Add a project (2nd time / 2nd person)"),
    ("body", "Once settings are imported, adding another project is quick. Choose the "
             "branching model that fits how your team works."),
    ("h2", "Quick steps"),
    ("bullet", "Load an existing project — you can see its number (e.g. '003') on "
               "'Page 9 - Project'."),
    ("bullet", "Change the project number from 003 to 004."),
    ("bullet", "Save the State, and save the .env (or variables.yaml)."),
    ("bullet", "Done — you now have an identical project 004 based on 003. Edit it to "
               "enable/disable the services that 004 should have."),
    ("h2", "Option 1 — One main branch (recommended)"),
    ("bullet", "All AI Factory projects are saved as metadata with their states and checked "
               "in to your GIT repo."),
    ("bullet", "Every user fetches the correct state from the single main branch."),
    ("h2", "Option 2 — One branch per project setting"),
    ("bullet", "Besides keeping wizard state locally and in GIT, you can instead (or also) "
               "create one branch per project setting that you manage on your own."),
    ("bullet", "Use this when teams want to manage their project configuration in isolation."),
    ("h2", "Apply the project to your pipeline"),
    ("bullet", "Back in VS Code you will see the edited .env file at the repo root."),
    ("bullet", "Update the GitHub Action variables by running the root script starting with "
               "'10-' in a Bash terminal:"),
    ("code", "bash 10-GH-create-or-update-github-variables.sh"),
]

HOWTO_ADD_SCALESET = [
    ("h1", "Add a Scale set"),
    ("body", "A scale set groups the shared VNet, subnets and common resources that your "
             "projects build on."),
    ("h2", "Prerequisites"),
    ("bullet", "Role: Developer with the repo cloned and the submodule activated "
               "(see 'Update AI Factory')."),
    ("bullet", "Installed on your laptop: Bash terminal, Azure CLI, GitHub CLI, Python."),
    ("link", "Prerequisites - AI Factory configuration Wizard",
             "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/install_config_wizard/readme.md"),
    ("link", "Prerequisites & Developer laptop (Update AI Factory)",
             "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/26-update-AIFactory.md"),
    ("h2", "1) Download the wizard and run it"),
    ("bullet", "Download and run the wizard (allow your OS to run the app if it is blocked)."),
    ("h2", "2) Configure the scale set"),
    ("bullet", "Open the 'Scale set & VNets' page and define the VNet, subnets and common "
               "resources."),
    ("bullet", "Save the State to store the scale set locally and under the wizard's metadata "
               "folder in GIT."),
    ("h2", "3) Apply it"),
    ("bullet", "Save the .env (or variables.yaml) to overwrite the real pipeline file at the "
               "repo root."),
    ("bullet", "Run the root '10-' script in a Bash terminal to update the pipeline variables:"),
    ("code", "bash 10-GH-create-or-update-github-variables.sh"),
]


def _make_howto_tab(notebook, tab_title, blocks):
    """Build a single read-only, scrollable HOW-TO tab inside a Notebook."""
    frame = ttk.Frame(notebook)
    notebook.add(frame, text=tab_title)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    txt = tk.Text(frame, wrap="word", height=30, width=98,
                  font=("Segoe UI", 9), bg="#ffffff", fg="#222222",
                  relief="flat", padx=12, pady=8, cursor="arrow",
                  borderwidth=0, highlightthickness=0)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=vsb.set)
    txt.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    txt.tag_configure("h1", font=("Segoe UI", 11, "bold"), foreground="#0078d4",
                      spacing1=6, spacing3=6)
    txt.tag_configure("h2", font=("Segoe UI", 10, "bold"), foreground="#1a1a1a",
                      spacing1=8, spacing3=2)
    txt.tag_configure("body", font=("Segoe UI", 9), foreground="#333333", spacing3=3)
    txt.tag_configure("bullet", font=("Segoe UI", 9), foreground="#333333",
                      lmargin1=22, lmargin2=36, spacing3=3)
    txt.tag_configure("code", font=("Consolas", 9), foreground="#9a3b00",
                      background="#f3f3f3", lmargin1=22, lmargin2=22, spacing1=2, spacing3=4)
    link_idx = 0
    for block in blocks:
        kind = block[0]
        if kind == "bullet":
            txt.insert("end", "\u2022  " + block[1] + "\n", "bullet")
        elif kind == "code":
            txt.insert("end", "  " + block[1] + "\n", "code")
        elif kind == "link":
            display, url = block[1], block[2]
            tag = f"link{link_idx}"
            link_idx += 1
            txt.tag_configure(tag, font=("Segoe UI", 9, "underline"),
                              foreground="#0078d4", lmargin1=22, lmargin2=36, spacing3=3)
            txt.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            txt.tag_bind(tag, "<Enter>", lambda e, w=txt: w.configure(cursor="hand2"))
            txt.tag_bind(tag, "<Leave>", lambda e, w=txt: w.configure(cursor="arrow"))
            txt.insert("end", "\U0001f517  " + display + "\n", tag)
        elif kind == "terminal":
            segments = block[1]
            term = tk.Text(txt, wrap="word", bg="#1e1e1e", fg="#d4d4d4",
                           font=("Consolas", 9), relief="flat", padx=10, pady=8,
                           borderwidth=0, highlightthickness=0,
                           height=18, width=84, cursor="arrow")
            term.tag_configure("plain",  foreground="#d4d4d4")
            term.tag_configure("prompt", foreground="#e5c07b")  # yellow — what the script asks
            term.tag_configure("answer", foreground="#ff5f56",  # red — what the user types
                               font=("Consolas", 9, "bold"))
            for role, seg in segments:
                term.insert("end", seg, role)
            term.configure(state="disabled")
            txt.insert("end", "\n")
            txt.window_create("end", window=term)
            txt.insert("end", "\n")
        else:
            txt.insert("end", block[1] + "\n", kind)
    txt.configure(state="disabled")
    return frame


# ===========================================================================
# PAGE 0: Intro
# ===========================================================================
class _ScalingModeSelector(ttk.LabelFrame):
    def __init__(self, parent, state):
        super().__init__(parent, text="Start configuration: scaling-mode", padding=8)
        self.state = state
        self.mode = tk.StringVar(value=state.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE))
        self.description = tk.StringVar()
        _VAR_REGISTRY.append((SCALING_MODE_KEY, self.mode, False, state))
        for row, (mode, profile) in enumerate(SCALING_MODES.items()):
            ttk.Radiobutton(self, text=profile["label"], value=mode, variable=self.mode,
                            command=self._choose).grid(row=row, column=0, sticky="w")
        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="w", pady=4)
        ttk.Button(actions, text="Apply network defaults", command=self._apply_defaults).grid(
            row=0, column=0, sticky="w")
        self.optimize_button = ttk.Button(actions, text="Optimize space", command=self._optimize)
        self.optimize_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(actions, text="Supported VNet formats", command=self._show_formats).grid(
            row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(self, textvariable=self.description, wraplength=760, justify="left").grid(
            row=3, column=0, sticky="ew")
        self.mode.trace_add("write", self._describe)
        self._describe()
        self._refresh_timer = self.after(250, self._watch_draft)
        self.bind("<Destroy>", self._stop_watching, add="+")

    def _describe(self, *_):
        self.refresh()

    def _show_formats(self):
        help_content = vnet_format_help()
        examples = ["Mode | VNet template | Dev / Stage / Prod"]
        examples.extend(f"{row['mode']} | {row['template']} | {row['ranges']}"
                        for row in help_content["examples"])
        messagebox.showinfo("Supported VNet formats",
                            "\n".join(examples) + "\n\n" + "\n\n".join(help_content["notes"]), parent=self)

    def _draft(self):
        return {key: self.state[key] for key in PLACEMENT_KEYS if key in self.state}

    def refresh(self):
        self._last_draft = self._draft()
        preview = preview_network_placement(self._last_draft)
        self.description.set(preview["guidance"])
        self.optimize_button.configure(state="normal" if preview["can_optimize"] else "disabled")

    def _watch_draft(self):
        if self._draft() != self._last_draft:
            self.refresh()
        self._refresh_timer = self.after(250, self._watch_draft)

    def _stop_watching(self, event):
        if event.widget is self:
            self.after_cancel(self._refresh_timer)

    def _choose(self):
        apply_scaling_mode(self.state, self.mode.get())
        _sync_vars_from_state(self.state)
        self.refresh()

    def _apply_defaults(self):
        if self.mode.get() not in SCALING_MODES:
            return
        apply_scaling_mode(self.state, self.mode.get(), apply_defaults=True)
        _sync_vars_from_state(self.state)
        self.refresh()

    def _optimize(self):
        draft = self._draft()
        preview = preview_network_placement(draft)
        if not preview["can_optimize"]:
            self.refresh()
            return
        if not messagebox.askyesno(
            "Optimize space — draft only",
            "Apply these start ranges to this draft?\n\n" + preview["optimization_description"],
            parent=self,
        ):
            return
        if self._draft() != draft:
            messagebox.showwarning(
                "Draft changed", "Network fields changed while confirming. Review a fresh preview.",
                parent=self,
            )
            self.refresh()
            return
        self.state.update(preview["optimization_changes"])
        _sync_vars_from_state(self.state)
        self.refresh()


class PageIntro(WizardPage):
    """Welcome / landing page with project description, images and a link."""

    def __init__(self, parent, state):
        super().__init__(parent, state)
        sf = _ScrollFrame(self)
        sf.place(relx=0, rely=0, relwidth=1, relheight=1)
        inn = sf.inner
        inn.columnconfigure(0, weight=1)

        row = 0

        # ── Main header ─────────────────────────────────────────────────────
        tk.Label(inn, text="Enterprise Scale AI Factory on Azure",
                 font=("Segoe UI", 13, "bold"),
                 fg="#0078d4", bg="#f5f5f5", anchor="w",
                 wraplength=820, justify="left").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(10, 1))
        row += 1

        tk.Label(inn,
                 text="AI Ready landingzones automation and DataOps, MLOps, GenAIOps templates",
                 font=("Segoe UI", 9), fg="#444444", bg="#f5f5f5",
                 anchor="w", wraplength=820, justify="left").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(0, 2))
        row += 1

        # ── GitHub link (top) ─────────────────────────────────────────────
        _url = "https://github.com/jostrm/azure-enterprise-scale-ml"
        link = tk.Label(inn,
                        text="\U0001f517  Azure/enterprise-scale-aifactory \u2014 GITHUB",
                        font=("Segoe UI", 9, "underline"),
                        fg="#0078d4", bg="#f5f5f5", cursor="hand2", anchor="w")
        link.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8))
        link.bind("<Button-1>", lambda e, u=_url: webbrowser.open(u))
        link.bind("<Enter>", lambda e: link.config(fg="#005fa3"))
        link.bind("<Leave>", lambda e: link.config(fg="#0078d4"))
        row += 1

        # ── Body paragraph ────────────────────────────────────────────────
        tk.Label(inn,
                 text=("Welcome to the AI Factory Configuration Wizard.  The goal is to help "
                       "generate the variables needed for the Enterprise Scale AI Factory "
                       "automation.  Think of it like an \u2018Install Wizard\u2019 for any "
                       "application."),
                 font=("Segoe UI", 9), fg="#333333", bg="#f5f5f5",
                 anchor="w", wraplength=820, justify="left").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(0, 6))
        row += 1

        # ── Section: landingzone automation ──────────────────────────────
        _ScalingModeSelector(inn, state).grid(
            row=row, column=0, sticky="ew", padx=20, pady=(4, 8))
        row += 1

        tk.Label(inn, text="AI Factory landingzone automation",
                 font=("Segoe UI", 10, "bold"), fg="#1a1a1a", bg="#f5f5f5",
                 anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(4, 1))
        row += 1

        tk.Label(inn,
                 text=("With the automation you can get the architectures below, fully automated, "
                       "executed as Azure DevOps or GitHub Actions pipelines.  "
                       "You get Dev, Stage and Prod environments / landingzones."),
                 font=("Segoe UI", 9), fg="#333333", bg="#f5f5f5",
                 anchor="w", wraplength=820, justify="left").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(0, 4))
        row += 1

        # ── Sub-section: Automation explained ────────────────────────────
        tk.Label(inn, text="AI Factory Automation explained",
                 font=("Segoe UI", 9, "bold"), fg="#1a1a1a", bg="#f5f5f5",
                 anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(2, 1))
        row += 1

        tk.Label(inn,
                 text="For each use case you can start small and grow your solution:",
                 font=("Segoe UI", 9), fg="#333333", bg="#f5f5f5",
                 anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 1))
        row += 1

        for bullet_title, bullet_text in [
            ("Add:",
             "You can start with just 1 service, then enable more services and run the "
             "pipeline again in an \u2018additive\u2019 way."),
            ("Remove:",
             "You can also disable services \u2014 running the pipeline again will remove "
             "them and do a proper cleaning of related artifacts.  The AI Factory also has "
             "an intelligent dependency graph to avoid removing a resource that is needed "
             "by another."),
             ("Standalone or Platform-integrated:",
             "Choose between deploying as: Standalone AI Factory (default), Platform-integrated workload, with centralized Private DNS zones."),
             ("BYO Resources",
             "Choose between having the AI Factory creating everytthing for you, or bringing your own existing resources like VNet, Subnet, ASA, etc"),
        ]:
            frm = tk.Frame(inn, bg="#f5f5f5")
            frm.grid(row=row, column=0, sticky="ew", padx=30, pady=1)
            frm.columnconfigure(1, weight=1)
            tk.Label(frm, text=f"\u2022  {bullet_title}",
                     font=("Segoe UI", 9, "bold"), fg="#0078d4", bg="#f5f5f5",
                     anchor="nw").grid(row=0, column=0, sticky="nw", padx=(0, 4))
            tk.Label(frm, text=bullet_text,
                     font=("Segoe UI", 9), fg="#333333", bg="#f5f5f5",
                     anchor="nw", wraplength=760, justify="left").grid(
                row=0, column=1, sticky="ew")
            row += 1

        # ── Section: Features ─────────────────────────────────────────────
        tk.Label(inn, text="AI Factory Configuration Wizard \u2014 Features",
                 font=("Segoe UI", 10, "bold"), fg="#1a1a1a", bg="#f5f5f5",
                 anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(4, 1))
        row += 1

        for feat_title, feat_desc in [
            ("UX Simple / Advanced mode:",
             "Advanced mode exposes more variables.  You get most fields pre-set with "
             "default values."),
            ("Color-coded review summary:",
             "Shows which variables were changed from their default values."),
            ("Portable:",
             "Runs on Windows, Linux and macOS."),
            ("Logical Wizard Workflow:",
             "Ensures you do not set invalid combinations of values.  Example: Container "
             "Registry SKU must be \u2018Premium\u2019 when private networking or CMK is "
             "selected."),
        ]:
            frm = tk.Frame(inn, bg="#f5f5f5")
            frm.grid(row=row, column=0, sticky="ew", padx=30, pady=1)
            frm.columnconfigure(1, weight=1)
            tk.Label(frm, text=f"\u2022  {feat_title}",
                     font=("Segoe UI", 9, "bold"), fg="#0078d4", bg="#f5f5f5",
                     anchor="nw").grid(row=0, column=0, sticky="nw", padx=(0, 4))
            tk.Label(frm, text=feat_desc,
                     font=("Segoe UI", 9), fg="#333333", bg="#f5f5f5",
                     anchor="nw", wraplength=760, justify="left").grid(
                row=0, column=1, sticky="ew")
            row += 1

        # ── Section: HOW-TO guides (tabs) ─────────────────────────────────
        tk.Label(inn, text="HOW-TO Guides",
                 font=("Segoe UI", 10, "bold"), fg="#1a1a1a", bg="#f5f5f5",
                 anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(8, 1))
        row += 1
        tk.Label(inn,
                 text=("Step-by-step guides for the most common tasks. "
                       "Scroll inside a tab to read the full guide."),
                 font=("Segoe UI", 9), fg="#444444", bg="#f5f5f5",
                 anchor="w", wraplength=820, justify="left").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(0, 4))
        row += 1

        howto_nb = ttk.Notebook(inn)
        howto_nb.grid(row=row, column=0, sticky="nsew", padx=20, pady=(2, 16))
        _make_howto_tab(howto_nb, "1 \u00b7 First-time setup", HOWTO_FIRST_TIME)
        _make_howto_tab(howto_nb, "2 \u00b7 Add a project", HOWTO_ADD_PROJECT)
        _make_howto_tab(howto_nb, "3 \u00b7 Add a Scale set", HOWTO_ADD_SCALESET)
        row += 1



# ===========================================================================
# PAGE 1: Orchestrator + Network Mode
# ===========================================================================
class PageOrchestratorNetwork(WizardPage):
    def __init__(self, parent, state, on_import=None):
        super().__init__(parent, state)
        self._on_import = on_import
        ttk.Label(self, text="\u2699  CI/CD Orchestrator & Network Mode",
                  font=("Segoe UI",11,"bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))
        r = self._section("CI/CD Orchestrator", 1)
        self._orch_var = tk.StringVar(value=state.get("orchestrator","ado"))
        ttk.Radiobutton(self, text="Azure DevOps (ADO)  →  saves variables.yaml",
                        variable=self._orch_var, value="ado", command=self._upd_orch).grid(row=r, column=0, columnspan=3, sticky="w", padx=16, pady=2)
        ttk.Radiobutton(self, text="GitHub Actions (GHA)  →  saves .env",
                        variable=self._orch_var, value="gha", command=self._upd_orch).grid(row=r+1, column=0, columnspan=3, sticky="w", padx=16, pady=2)

        # ── GitHub Actions Configuration (visible only when GHA selected) ─
        self._gha_frame = ttk.LabelFrame(self, text="GitHub Actions Configuration", padding=(8, 4))
        self._gha_frame.grid(row=r+2, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 4))
        self._gha_frame.columnconfigure(1, weight=1)
        _hint_nw(self._gha_frame,
                 "These fields are saved to .env only (not written to variables.yaml).",
                 0, col=0, colspan=3)
        _make_entry(self._gha_frame, "GitHub username:", "github_username", state, 1)
        _make_checkbox(self._gha_frame,
                       "Use SSH  (git@github.com:… instead of https://)",
                       "github_use_ssh", state, 2, col=0, columnspan=3)
        _make_entry(self._gha_frame, "Template repo:", "github_template_repo", state, 3)
        _make_entry(self._gha_frame, "New repo:", "github_new_repo", state, 4)
        _make_combo(self._gha_frame, "Repo visibility:", "github_new_repo_visibility",
                    state, 5, ["public", "private", "internal"])
        # Hide on startup if ADO is selected
        if state.get("orchestrator", "ado") != "gha":
            self._gha_frame.grid_remove()

        r2 = self._section("Network Mode", r+3)
        DESC = {"private":"Private UI + private backend  (Bastion / VPN required)",
                "hybrid": "Public UI (IP-whitelisted) + private backend",
                "public": "Public UI + private backend with perimeter access"}
        self._mode_var = tk.StringVar(value=state.get("network_mode","public"))
        self._flag_lbls = {}
        for i, mode in enumerate(["private","hybrid","public"]):
            ttk.Radiobutton(self, text=f"{mode.capitalize()}  —  {DESC[mode]}",
                            variable=self._mode_var, value=mode,
                            command=self._upd_mode).grid(row=r2+i, column=0, columnspan=3, sticky="w", padx=16, pady=3)
        r3 = self._section("Resulting Flag Values", r2+4)
        for j, flag in enumerate(["allowPublicAccessWhenBehindVnet","enablePublicGenAIAccess","enablePublicAccessWithPerimeter"]):
            ttk.Label(self, text=flag+":").grid(row=r3+j, column=0, sticky="w", padx=4)
            lbl = ttk.Label(self, text="", width=8)
            lbl.grid(row=r3+j, column=1, sticky="w", padx=4)
            self._flag_lbls[flag] = lbl
        self._upd_mode()

        # ── File Saving Location ─────────────────────────────────────────
        r4 = self._section("File Saving Location", r3+4)
        ttk.Label(self, text="Variable folder location:",
                  font=("Segoe UI",9)).grid(
            row=r4, column=0, sticky="w", padx=(16,4), pady=3)
        self._folder_var = tk.StringVar(value=state.get("_save_folder", ""))
        self._folder_var.trace_add("write",
            lambda *_: (
                state.update({"_save_folder": self._folder_var.get()}),
                _save_app_settings({"_save_folder": self._folder_var.get()}),
                self._also_update_git_var.set(True)
                    if "aifactory" in self._folder_var.get().lower() else None,
            ))
        folder_ent = ttk.Entry(self, textvariable=self._folder_var)
        folder_ent.grid(row=r4, column=1, sticky="ew", padx=4, pady=3)
        ttk.Button(self, text="Browse…", width=8,
                   command=self._browse_folder).grid(
            row=r4, column=2, sticky="w", padx=(2,8), pady=3)
        _hint(self,
              "Pipeline files are saved under config-wizard; variables.json is saved at <aifactory-root>/variables.json\n"
              "Set the folder below to your aifactory root folder (e.g. …/git/aifactory)",
              r4+1, col=0, colspan=3)
        self._also_update_git_var = tk.BooleanVar(
            value=state.get("_also_update_git", True))
        self._also_update_git_var.trace_add("write",
            lambda *_: state.update({"_also_update_git": self._also_update_git_var.get()}))
        ttk.Checkbutton(
            self,
            text="Also update actual variable file under your GIT 'aifactory' folder",
            variable=self._also_update_git_var,
        ).grid(row=r4+2, column=0, columnspan=3, sticky="w", padx=16, pady=(2, 0))
        _hint(self,
              "When checked, clicking SAVE will also write to the actual pipeline variables file:\n"
              "  ADO → <aifactory-root>/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml\n"
              "  GHA → <parent of aifactory-root>/.env",
              r4+3, col=0, colspan=3)

        # ── Import File ───────────────────────────────────────────────────
        r5 = self._section("Import File", r4+5)
        _hint(self,
              "Browse to variables.yaml (loads ADO), .env (loads GHA), or variables.json (keeps current mode).\n"
              "All matching field values will be applied to the wizard.",
              r5, col=0, colspan=3)
        ttk.Label(self, text="File to import:",
                  font=("Segoe UI", 9)).grid(
            row=r5+1, column=0, sticky="w", padx=(16, 4), pady=3)
        self._import_path_var = tk.StringVar()
        import_ent = ttk.Entry(self, textvariable=self._import_path_var, state="readonly")
        import_ent.grid(row=r5+1, column=1, sticky="ew", padx=4, pady=3)
        ttk.Button(self, text="Browse…", width=8,
                   command=self._browse_import).grid(
            row=r5+1, column=2, sticky="w", padx=(2, 8), pady=3)
        self._import_status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._import_status_var,
                  font=("Segoe UI", 9, "italic"), foreground="#555555").grid(
            row=r5+2, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 4))

        self.columnconfigure(1, weight=1)

    def _browse_folder(self):
        chosen = filedialog.askdirectory(
            title="Select base folder for project files",
            initialdir=self._folder_var.get() or os.path.expanduser("~"))
        if chosen:
            self._folder_var.set(chosen)
            self._import_from_startup_folder(chosen)

    def _import_from_startup_folder(self, folder: str):
        self.state["_save_folder"] = folder
        if self._folder_var.get() != folder:
            self._folder_var.set(folder)
        else:
            _save_app_settings({"_save_folder": folder})
        path, orchestrator = _startup_import_candidate(folder, self.state)
        self.state["orchestrator"] = orchestrator
        if path:
            self._import_path_var.set(path)
            self._do_import(path)
        else:
            mode_label = "GHA" if orchestrator == "gha" else "ADO"
            self._import_status_var.set(
                f"No variable file found for the detected {mode_label} route.")
            if self._on_import:
                self._on_import()

    def _browse_import(self):
        path = filedialog.askopenfilename(
            title="Import variables.yaml, .env, or variables.json",
            filetypes=[
                ("Variable files", "*.yaml *.yml *.env *.json"),
                ("YAML files", "*.yaml"),
                ("env files", "*.env"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
            initialdir=self._folder_var.get() or os.path.expanduser("~"),
        )
        if path:
            app = self.winfo_toplevel()
            if getattr(app, "_is_dirty", None) and app._is_dirty():
                if not messagebox.askyesno(
                    "Discard unsaved changes?",
                    "Importing will overwrite the current settings.\n"
                    "You have unsaved changes that aren't saved yet.\n\n"
                    "Continue with the import?"):
                    return
            self._import_path_var.set(path)
            self._do_import(path)

    def _do_import(self, path: str):
        """Load a .yaml, .env, or .json file into wizard state and refresh all UI."""
        ext = os.path.splitext(path)[1].lower()
        if ext in (".yaml", ".yml"):
            count = _import_yaml_to_state(path, self.state)
            mode_label = "ADO (variables.yaml)"
        elif ext == ".env" or os.path.basename(path) == ".env":
            count = _import_env_to_state(path, self.state)
            mode_label = "GHA (.env | .json)"
        elif ext == ".json":
            count = _import_json_to_state(path, self.state)
            orch_label = "GHA" if self.state.get("orchestrator") == "gha" else "ADO"
            mode_label = f"{orch_label} (.json; mode unchanged)"
        else:
            # Try to auto-detect from content
            try:
                with open(path, "r", encoding="utf-8") as f:
                    first = f.read(512)
            except Exception:
                first = ""
            if "variables:" in first:
                count = _import_yaml_to_state(path, self.state)
                mode_label = "ADO (variables.yaml)"
            else:
                count = _import_env_to_state(path, self.state)
                mode_label = "GHA (.env | .json)"

        if count == 0:
            self._import_status_var.set(
                f"⚠  No matching fields found in selected file.")
            return

        # Push loaded state values into all registered tk vars
        _sync_vars_from_state(self.state)

        # Re-sync Page 1 widgets that are not in _VAR_REGISTRY
        orch = self.state.get("orchestrator", "ado")
        self._orch_var.set(orch)
        if orch == "gha":
            self._gha_frame.grid()
        else:
            self._gha_frame.grid_remove()
        mode = self.state.get("network_mode", "public")
        self._mode_var.set(mode)
        self._upd_mode()
        folder = self.state.get("_save_folder", "")
        if self._folder_var.get() != folder:
            self._folder_var.set(folder)
        _also_fallback = True if "aifactory" in folder.lower() else True
        self._also_update_git_var.set(self.state.get("_also_update_git", _also_fallback))

        self._import_status_var.set(
            f"✓  Imported {count} fields — mode set to {mode_label}")
        network_issues = scaling_validation_issues(self.state)
        if network_issues:
            self._import_status_var.set(
                f"⚠  Imported {count} fields unchanged; repair network before saving. "
                + network_issues[0]["message"])

        # Notify app so it can match & select the correct scale set
        if self._on_import:
            self._on_import()

    def on_enter(self):
        # Re-sync radio vars from state so loaded snapshot is reflected
        orch = self.state.get("orchestrator", "ado")
        self._orch_var.set(orch)
        if orch == "gha":
            self._gha_frame.grid()
        else:
            self._gha_frame.grid_remove()
        mode = self.state.get("network_mode", "public")
        self._mode_var.set(mode)
        self._upd_mode()
        # Always push folder — no equality guard so switching projects always updates
        self._folder_var.set(self.state.get("_save_folder", ""))
        # Sync also-update checkbox; default True
        self._also_update_git_var.set(self.state.get("_also_update_git", True))
        super().on_enter()

    def _upd_orch(self):
        orch = self._orch_var.get()
        self.state["orchestrator"] = orch
        if orch == "gha":
            self._gha_frame.grid()
        else:
            self._gha_frame.grid_remove()

    def _upd_mode(self):
        mode = self._mode_var.get()
        self.state["network_mode"] = mode
        flags = NETWORK_MODE_FLAGS[mode]
        self.state.update(flags)
        for flag, val in flags.items():
            self._flag_lbls[flag].config(text=val)


# ===========================================================================
# PAGE 2: Scale set & Vnets
# ===========================================================================
class PageScaleSet(WizardPage):
    REGIONS = [
        # Americas
        ("East US",                 "eastus",               "eus"),
        ("East US 2",               "eastus2",              "eus2"),
        ("West US",                 "westus",               "wus"),
        ("West US 2",               "westus2",              "wus2"),
        ("West US 3",               "westus3",              "wus3"),
        ("Central US",              "centralus",            "cus"),
        ("North Central US",        "northcentralus",       "ncus"),
        ("South Central US",        "southcentralus",       "scus"),
        ("West Central US",         "westcentralus",        "wcus"),
        ("Canada Central",          "canadacentral",        "cac"),
        ("Canada East",             "canadaeast",           "cae"),
        ("Brazil South",            "brazilsouth",          "brs"),
        ("Brazil Southeast",        "brazilsoutheast",      "brse"),
        ("Mexico Central",          "mexicocentral",        "mxc"),
        # Europe
        ("North Europe",            "northeurope",          "neu"),
        ("West Europe",             "westeurope",           "weu"),
        ("Sweden Central",          "swedencentral",        "sdc"),
        ("UK South",                "uksouth",              "uks"),
        ("UK West",                 "ukwest",               "ukw"),
        ("France Central",          "francecentral",        "frc"),
        ("France South",            "francesouth",          "frs"),
        ("Germany West Central",    "germanywestcentral",   "gwc"),
        ("Germany North",           "germanynorth",         "gno"),
        ("Switzerland North",       "switzerlandnorth",     "swn"),
        ("Switzerland West",        "switzerlandwest",      "sww"),
        ("Norway East",             "norwayeast",           "noe"),
        ("Norway West",             "norwaywest",           "now"),
        ("Poland Central",          "polandcentral",        "plc"),
        ("Italy North",             "italynorth",           "itn"),
        ("Spain Central",           "spaincentral",         "esc"),
        # Middle East & Africa
        ("UAE North",               "uaenorth",             "uan"),
        ("UAE Central",             "uaecentral",           "uac"),
        ("Qatar Central",           "qatarcentral",         "qac"),
        ("Israel Central",          "israelcentral",        "ilc"),
        ("South Africa North",      "southafricanorth",     "san"),
        ("South Africa West",       "southafricawest",      "saw"),
        # Asia Pacific
        ("East Asia",               "eastasia",             "ea"),
        ("Southeast Asia",          "southeastasia",        "sea"),
        ("Japan East",              "japaneast",            "jpe"),
        ("Japan West",              "japanwest",            "jpw"),
        ("Australia East",          "australiaeast",        "aue"),
        ("Australia Southeast",     "australiasoutheast",   "ause"),
        ("Australia Central",       "australiacentral",     "auc"),
        ("Australia Central 2",     "australiacentral2",    "auc2"),
        ("Korea Central",           "koreacentral",         "krc"),
        ("Korea South",             "koreasouth",           "krs"),
        ("India Central",           "centralindia",         "cin"),
        ("India South",             "southindia",           "sin"),
        ("India West",              "westindia",            "win"),
        ("China East",              "chinaeast",            "ce"),
        ("China East 2",            "chinaeast2",           "ce2"),
        ("China North",             "chinanorth",           "cn"),
        ("China North 2",           "chinanorth2",          "cn2"),
        ("China North 3",           "chinanorth3",          "cn3"),
        ("New Zealand North",       "newzealandnorth",      "nzn"),
        ("Malaysia West",           "malaysiawest",         "myw"),
        ("Indonesia Central",       "indonesiacentral",     "idc"),
        ("Taiwan North",            "taiwannorth",          "twn"),
    ]

    def __init__(self, parent, state, on_scaleset_saved=None):
        super().__init__(parent, state)
        self._on_scaleset_saved = on_scaleset_saved
        sf = _ScrollFrame(self); sf.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._sf = sf
        inn = sf.inner; inn.columnconfigure(1, weight=1)

        ttk.Label(inn, text="\U0001f310  Scale set & Vnets", font=("Segoe UI",11,"bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))
        _hint(inn, "Values pre-populated from template-files/variables.yaml", 1, col=0, colspan=3)

        # ── Saved Scale Sets section (top) ─────────────────────────────
        ttk.Separator(inn, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(6, 2))
        ttk.Label(inn, text="\U0001f5c2  Saved Scale Sets",
                  font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, columnspan=4, sticky="w", padx=4)
        _hint(inn, "Click a scale set below to load its settings into this page.",
              4, col=0, colspan=4)
        self._page_ss_outer = tk.Frame(inn, bg="#e8e8e8", bd=1, relief="sunken")
        self._page_ss_outer.grid(row=5, column=0, columnspan=4,
                                  sticky="ew", padx=8, pady=4)
        self._page_ss_inner = tk.Frame(self._page_ss_outer, bg="#ececec")
        self._page_ss_inner.pack(fill="x", expand=True)
        btn_row_frame_top = tk.Frame(inn, bg="#f5f5f5")
        btn_row_frame_top.grid(row=6, column=0, columnspan=4,
                               sticky="w", padx=8, pady=(0, 6))
        ttk.Button(btn_row_frame_top, text="Create new Scale Set",
                   command=self._create_new_scaleset).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row_frame_top, text="Save current as Scale Set",
                   command=self._save_scaleset).pack(side="left")

        r = self._section("Scale Set Identity", 7, inn)
        _make_entry(inn, "Suffix RG  (e.g. -001, -007):", "admin_aifactorySuffixRG", state, r)
        _hint(inn, "Unique suffix for this AIFactory scale set", r+1)
        _make_entry(inn, "Prefix RG  (e.g. mrvel-1-):", "admin_aifactoryPrefixRG", state, r+2, placeholder="mrvel-1-")
        _hint(inn, "Unique prefix for this AIFactory scale set (max 6 chars)", r+3)

        r2 = self._section("Project Naming (optional)", r+5, inn)
        _make_entry(inn, "Project Prefix  (e.g. esml-):", "projectPrefix", state, r2)
        _make_entry(inn, "Project Suffix  (e.g. -rg):",   "projectSuffix", state, r2+1)
        _hint(inn, "Leave blank for default: mrvel-1-project001-sdc-dev-007", r2+2)

        r3 = self._section("Subscriptions & Tenant", r2+4, inn)
        self._dev_sub_var, self._dev_sub_ent = _make_entry_w(inn, "Dev Subscription ID *:", "dev_sub_id", state, r3)
        self._test_sub_var, self._test_sub_ent = _make_entry_w(inn, "Test Subscription ID:", "test_sub_id", state, r3+1)
        _hint(inn, "Optional — leave empty or use the same as Dev Subscription ID", r3+2)
        self._prod_sub_var, self._prod_sub_ent = _make_entry_w(inn, "Prod Subscription ID:", "prod_sub_id", state, r3+3)
        _hint(inn, "Optional — leave empty or use the same as Dev Subscription ID", r3+4)
        self._tenant_var, self._tenant_ent = _make_entry_w(inn, "Tenant ID *:", "tenantId", state, r3+5)
        _hint(inn, "Required — UUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", r3+6)

        r4 = self._section("Environment CIDR Ranges", r3+8, inn)
        _hint(inn, "Each number replaces XX in the subnet template 172.16.XX.0/24", r4, col=0, colspan=4)
        self._dev_cidr_var, self._dev_cidr_ent = _make_entry_w(inn, "Dev CIDR range * (replaces XX):", "dev_cidr_range", state, r4+1, placeholder="0", width=10)
        self._test_cidr_var, self._test_cidr_ent = _make_entry_w(inn, "Stage CIDR range (replaces XX):", "test_cidr_range", state, r4+2, placeholder="64", width=10)
        _hint(inn, "Optional — leave empty or reuse Dev CIDR range", r4+3)
        self._prod_cidr_var, self._prod_cidr_ent = _make_entry_w(inn, "Prod CIDR range (replaces XX):", "prod_cidr_range", state, r4+4, placeholder="128", width=10)
        _hint(inn, "Optional — leave empty or reuse Dev CIDR range", r4+5)

        # Advanced-only: Common Scaleset Vnet and Subnets
        _r5 = r4 + 7
        _sep5 = ttk.Separator(inn, orient="horizontal")
        _sep5.grid(row=_r5, column=0, columnspan=4, sticky="ew", pady=(10,2))
        _lbl5 = ttk.Label(inn, text="Common Scaleset Vnet and Subnets", font=("Segoe UI",9,"bold"))
        _lbl5.grid(row=_r5+1, column=0, columnspan=4, sticky="w", padx=4)
        r5 = _r5 + 2
        _, _l_vnet,  _e_vnet  = _make_entry(inn, "Common vNet CIDR:",                   "common_vnet_cidr",             state, r5,   placeholder="172.16.XX.0/18")
        _, _l_sub,   _e_sub   = _make_entry(inn, "Common Subnet CIDR (XX=cidr range):",  "common_subnet_cidr",           state, r5+1, placeholder="172.16.XX.0/26")
        _, _l_scr,   _e_scr   = _make_entry(inn, "Common Scoring Subnet CIDR:",          "common_subnet_scoring_cidr",   state, r5+2, placeholder="172.16.XX.64/26")
        _, _l_pbin,  _e_pbin  = _make_entry(inn, "PBI Subnet Name:",                    "common_pbi_subnet_name",       state, r5+3, placeholder="snet-esml-cmn-pbi-001")
        _, _l_pbic,  _e_pbic  = _make_entry(inn, "PBI Subnet CIDR:",                    "common_pbi_subnet_cidr",       state, r5+4, placeholder="172.16.XX.128/26")
        _, _l_basn,  _e_basn  = _make_entry(inn, "Bastion Subnet Name:",                "common_bastion_subnet_name",   state, r5+5, placeholder="AzureBastionSubnet")
        _, _l_basc,  _e_basc  = _make_entry(inn, "Bastion Subnet CIDR:",                "common_bastion_subnet_cidr",   state, r5+6, placeholder="172.16.XX.192/26")
        self._adv_only.extend([
            _sep5, _lbl5,
            _l_vnet, _e_vnet, _l_sub, _e_sub, _l_scr, _e_scr,
            _l_pbin, _e_pbin, _l_pbic, _e_pbic, _l_basn, _e_basn, _l_basc, _e_basc,
        ])

        r6 = self._section("Azure Region", r5+8, inn)
        all_names = [reg[0] for reg in self.REGIONS]
        self._rgn_var = tk.StringVar()
        self._rgn_combo = ttk.Combobox(inn, textvariable=self._rgn_var, values=all_names, width=34)
        self._rgn_combo.grid(row=r6, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self._rgn_combo.bind("<<ComboboxSelected>>", lambda e: self._upd_region())
        # Filter list as user types
        def _rgn_keyup(event):
            typed = self._rgn_var.get().lower()
            if typed:
                filtered = [n for n in all_names if typed in n.lower()]
            else:
                filtered = all_names
            self._rgn_combo["values"] = filtered
            if filtered:
                self._rgn_combo.event_generate("<Down>")
        self._rgn_combo.bind("<KeyRelease>", _rgn_keyup)
        self._rgn_combo.bind("<FocusOut>", lambda e: self._upd_region())
        loc = state.get("admin_location","swedencentral")
        matched = False
        for name, az, _ in self.REGIONS:
            if az==loc: self._rgn_var.set(name); matched=True; break
        if not matched:
            sdc = next((n for n, a, _ in self.REGIONS if a == "swedencentral"), all_names[0])
            self._rgn_var.set(sdc)
        ttk.Label(inn, text="Location Suffix (max 4 chars):").grid(row=r6+1, column=0, sticky="w", padx=4, pady=2)
        self._suf_var = tk.StringVar(value=state.get("admin_locationSuffix","sdc"))
        suf_ent = ttk.Entry(inn, textvariable=self._suf_var, width=8)
        suf_ent.grid(row=r6+1, column=1, sticky="w", padx=4, pady=2)
        _hint(inn, "Auto-filled from region; edit if needed (max 4 chars)", r6+2)
        def _suf_changed(*a):
            v = self._suf_var.get()
            if len(v)>4: self._suf_var.set(v[:4])
            state["admin_locationSuffix"] = self._suf_var.get()
        self._suf_var.trace_add("write", _suf_changed)
        self._upd_region()

        # --- ADO Service Connections (visible only when orchestrator == ado) ---
        ado_row = r6 + 3
        self._ado_sep = ttk.Separator(inn, orient="horizontal")
        self._ado_sep.grid(row=ado_row, column=0, columnspan=4, sticky="ew", pady=(10,2))
        self._ado_sec_lbl = ttk.Label(inn, text="Azure DevOps Service Connections", font=("Segoe UI",9,"bold"))
        self._ado_sec_lbl.grid(row=ado_row+1, column=0, columnspan=4, sticky="w", padx=4)
        ar = ado_row + 2
        self._ado_hint = _hint(inn, "Only used when orchestrator = Azure DevOps (ADO)", ar, col=0, colspan=4)
        _, self._ado_lbl_dev_sc, self._ado_ent_dev_sc = _make_entry(inn, "Dev service connection:",  "dev_service_connection",  state, ar+1)
        _, self._ado_lbl_tst_sc, self._ado_ent_tst_sc = _make_entry(inn, "Test service connection:", "test_service_connection", state, ar+2)
        _, self._ado_lbl_prd_sc, self._ado_ent_prd_sc = _make_entry(inn, "Prod service connection:", "prod_service_connection", state, ar+3)
        _, self._ado_lbl_dev_kv, self._ado_ent_dev_kv = _make_entry(inn, "Dev seeding KV service connection:",  "dev_seeding_kv_service_connection",  state, ar+4)
        _, self._ado_lbl_tst_kv, self._ado_ent_tst_kv = _make_entry(inn, "Test seeding KV service connection:", "test_seeding_kv_service_connection", state, ar+5)
        _, self._ado_lbl_prd_kv, self._ado_ent_prd_kv = _make_entry(inn, "Prod seeding KV service connection:", "prod_seeding_kv_service_connection", state, ar+6)
        self._ado_widgets = [
            self._ado_sep, self._ado_sec_lbl, self._ado_hint,
            self._ado_lbl_dev_sc, self._ado_ent_dev_sc,
            self._ado_lbl_tst_sc, self._ado_ent_tst_sc,
            self._ado_lbl_prd_sc, self._ado_ent_prd_sc,
            self._ado_lbl_dev_kv, self._ado_ent_dev_kv,
            self._ado_lbl_tst_kv, self._ado_ent_tst_kv,
            self._ado_lbl_prd_kv, self._ado_ent_prd_kv,
        ]
        if state.get("orchestrator", "ado") != "ado":
            for w in self._ado_widgets:
                w.grid_remove()

        # (Saved Scale Sets section moved to top of page — see row 2-6 above)

    def on_enter(self):
        # Re-sync the region dropdown from state (e.g. after snapshot load)
        loc = self.state.get("admin_location", "swedencentral")
        for name, az, suf in self.REGIONS:
            if az == loc:
                self._rgn_var.set(name)
                break
        suf_state = self.state.get("admin_locationSuffix", "sdc")
        if self._suf_var.get() != suf_state:
            self._suf_var.set(suf_state)
        is_ado = self.state.get("orchestrator", "ado") == "ado"
        for w in self._ado_widgets:
            if is_ado:
                w.grid()
            else:
                w.grid_remove()
        self._refresh_page_scalesets()
        if self._sf:
            self._sf.refresh_scroll()

    def _refresh_page_scalesets(self):
        """Rebuild the saved-scale-sets list inside the page."""
        for w in self._page_ss_inner.winfo_children():
            w.destroy()
        base_folder = self.state.get("_save_folder", "").strip()
        scalesets = _list_scalesets(base_folder)
        if not scalesets:
            tk.Label(self._page_ss_inner, text="  (no saved scale sets)",
                     bg="#ececec", fg="#888888",
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=4, pady=2)
            return
        for ss_id, path in sorted(scalesets.items()):
            # Peek at the file for location label
            loc_label = ""
            try:
                with open(path, "r", encoding="utf-8") as _f:
                    _d = _json.load(_f)
                _loc = _d.get("admin_location", "")
                if _loc:
                    loc_label = f"  \u2014  {_loc}"
            except Exception:
                pass
            def _load(p=path, sid=ss_id):
                self._load_scaleset_on_page(p, sid)
            tk.Button(
                self._page_ss_inner,
                text=f"  \u25cf  Scale set {ss_id}{loc_label}",
                bg="#ececec", fg="#6a3f8a",
                activebackground="#d8d0e8", activeforeground="#3a1a5a",
                relief="flat", bd=0,
                font=("Segoe UI", 9),
                anchor="w", padx=6, pady=2,
                cursor="hand2",
                command=_load,
            ).pack(fill="x")

    def _load_scaleset_on_page(self, path: str, ss_id: str):
        """Load a scaleset snapshot into current state and refresh page 2 widgets."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            data = hub_configuration(data)
            data.setdefault(SCALING_MODE_KEY, DEFAULT_SCALING_MODE)
            self.state.update(data)
            _sync_vars_from_state(self.state)
            self.on_enter()
            messagebox.showinfo("Scale Set Loaded",
                                f"Scale set {ss_id} loaded into this page.")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _save_scaleset(self):
        """Save the current page-2 fields as a scale-set snapshot."""
        suffix = self.state.get("admin_aifactorySuffixRG", "").strip()
        if not suffix:
            messagebox.showerror("Missing Suffix",
                                 "Set the Suffix RG (e.g. -001) before saving a scale set.")
            return
        try:
            path = _save_scaleset_snapshot(self.state)
            self._refresh_page_scalesets()
            if self._on_scaleset_saved:
                self._on_scaleset_saved()
            messagebox.showinfo("Scale Set Saved",
                                f"Scale set '{_scaleset_id_from_suffix(suffix)}' saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    def _create_new_scaleset(self):
        """Clear the page-2 fields to defaults, ready for a new scale set."""
        ans = messagebox.askyesno(
            "Create new Scale Set",
            "This will clear the current Scale Set fields to defaults.\n"
            "Unsaved changes to the current scale set will be lost.\n\nContinue?",
        )
        if not ans:
            return
        # Reset only the scaleset-specific keys to DEFAULT_STATE values
        for k in SCALESET_KEYS:
            if k in DEFAULT_STATE and not k.startswith("_"):
                self.state[k] = DEFAULT_STATE[k]
        # Clear the scale-set identity so the user must enter a new one
        self.state["admin_aifactorySuffixRG"] = ""
        _sync_vars_from_state(self.state)
        self.on_enter()

    def _upd_region(self):
        sel = self._rgn_var.get().strip()
        # Exact match first
        for name, az, suf in self.REGIONS:
            if name == sel:
                self.state["admin_location"] = az
                self.state["admin_locationSuffix"] = suf
                self._suf_var.set(suf)
                self._rgn_combo["values"] = [r[0] for r in self.REGIONS]  # restore full list
                return
        # Case-insensitive / partial fallback — pick first unique match
        sel_l = sel.lower()
        matches = [(n, a, s) for n, a, s in self.REGIONS if sel_l in n.lower()]
        if len(matches) == 1:
            name, az, suf = matches[0]
            self._rgn_var.set(name)
            self.state["admin_location"] = az
            self.state["admin_locationSuffix"] = suf
            self._suf_var.set(suf)
            self._rgn_combo["values"] = [r[0] for r in self.REGIONS]  # restore full list

    def on_leave(self):
        checks = [
            (self._dev_sub_ent,  "Dev Subscription ID",  self.state.get("dev_sub_id",""),  False),
            (self._test_sub_ent, "Test Subscription ID", self.state.get("test_sub_id",""), True),
            (self._prod_sub_ent, "Prod Subscription ID", self.state.get("prod_sub_id",""), True),
            (self._tenant_ent,   "Tenant ID",            self.state.get("tenantId",""),    False),
        ]
        errs = []
        for ent, lbl, val, allow_empty in checks:
            err = _validate_uuid_field(lbl, val, allow_empty=allow_empty)
            _set_field_state(ent, bool(err))
            if err: errs.append(err)
        dev_cidr_err = ""
        dc = self.state.get("dev_cidr_range","").strip()
        if not dc:
            dev_cidr_err = "Dev CIDR range: required"
        else:
            try: int(dc)
            except ValueError: dev_cidr_err = "Dev CIDR range: must be an integer"
        _set_field_state(self._dev_cidr_ent, bool(dev_cidr_err))
        if dev_cidr_err: errs.append(dev_cidr_err)
        if not self.state.get("admin_aifactorySuffixRG","").strip():
            errs.append("Suffix RG: required (e.g. -001)")
        if errs:
            messagebox.showerror("Validation Error", "\n".join(errs))
            return False
        return True


def azure_region_suffixes() -> dict[str, str]:
    """Expose the same region naming defaults used by the Tkinter selector."""
    return dict(sorted((region, suffix) for _, region, suffix in PageScaleSet.REGIONS))


# ===========================================================================
# PAGE 3: Version
# ===========================================================================
class PageVersion(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\U0001f4e6  AIFactory Submodule Version",
                  font=("Segoe UI",11,"bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))
        init_ver = state.get("_version_str","1.24")
        if init_ver not in VERSION_BRANCH: init_ver = "1.24"
        self._ver_var = tk.StringVar(value=init_ver)
        CURRENT = "1.24"
        for i, ver in enumerate(VERSION_BRANCH):
            is_current = (ver == CURRENT)
            label_text = f"v{ver}  ({VERSION_BRANCH[ver]})" + ("" if is_current else "  [deprecated — not supported via Wizard]")
            rb = ttk.Radiobutton(self, text=label_text, variable=self._ver_var, value=ver, command=self._upd)
            rb.grid(row=1+i, column=0, columnspan=2, sticky="w", padx=16, pady=2)
            if not is_current: rb.configure(state="disabled")
        self._upd()

    def _upd(self):
        ver = self._ver_var.get()
        major, minor = ver.split(".")
        self.state["version_major"]=major; self.state["version_minor"]=minor
        self.state["version_branch"]=VERSION_BRANCH[ver]

    def on_enter(self):
        # Re-sync version radio from state after snapshot load
        loaded_ver = f"{self.state.get('version_major','1')}.{self.state.get('version_minor','24')}"
        if loaded_ver in VERSION_BRANCH and self._ver_var.get() != loaded_ver:
            self._ver_var.set(loaded_ver)


# ===========================================================================
# PAGE 4: Advanced Networking
# ===========================================================================
class PageAdvancedNetworking(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\U0001f517  Advanced Networking",
                  font=("Segoe UI",11,"bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))
        r = self._section("Hub intent & DNS", 1)
        self._own_hub_var, _ = _make_checkbox(
            self, "Enable AI Factory's own Hub (configuration intent only)",
            "enableAIFactoryHub", state, r, columnspan=3)
        self._hint("Both flags off: standalone. Central DNS on: external Hub takes precedence. "
                   "These settings do not deploy resources.", r+1)
        r += 2
        self._dns_var = tk.BooleanVar(value=_bool_str(state.get("centralDnsZoneByPolicyInHub","false")))
        ttk.Checkbutton(self, text="Central DNS zones by Azure Policy in Hub",
                        variable=self._dns_var, command=self._upd_dns).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        self._dns_sub_var, self._dns_sub_ent = _make_entry_w(self, "Central DNS Subscription ID:", "privDnsSubscription_param", state, r+1)
        self._dns_rg_var,  self._dns_rg_ent  = _make_entry_w(self, "Central DNS Resource Group:",  "privDnsResourceGroup_param", state, r+2)
        self._upd_dns()
        r2 = self._section("BYO vNet  (leave blank to let AIFactory create vNet)", r+4)
        _make_entry(self, "vNet Resource Group:", "vnetResourceGroup_param", state, r2)
        _make_entry(self, "vNet Full Name:",      "vnetNameFull_param",      state, r2+1)
        r3 = self._section("Agent & AI Search Networking", r2+3)
        _make_checkbox(self, "Disable Agent Network Injection", "disableAgentNetworkInjection", state, r3)
        _make_entry(self, "Policy Exemption Assignment IDs:", "policyExemptionAssignmentIds", state, r3+1, placeholder="[]")
        _make_entry(self, "Policy Exemption Def Reference IDs:", "policyExemptionDefinitionReferenceIds", state, r3+2, placeholder="[]")
        _make_checkbox(self, "Use Shared Private Link for AI Search", "enableAISearchSharedPrivateLink", state, r3+3)
        self._hint("Shared private link: Basic tier+;  skillsets require Standard S1+", r3+4)
        # --- BYO Subnets (advanced mode only) ---
        r4 = r3+6
        _byos_sep = ttk.Separator(self, orient="horizontal")
        _byos_sep.grid(row=r4, column=0, columnspan=4, sticky="ew", pady=(10,2))
        _byos_hdr = ttk.Label(self, text="BYO Subnets", font=("Segoe UI",9,"bold"))
        _byos_hdr.grid(row=r4+1, column=0, columnspan=4, sticky="w", padx=4)
        r4 = r4+2
        _, cb_byos          = _make_checkbox(self, "Use BYO Subnets",              "BYO_subnets",                state, r4)
        _, lbl_dev,  ent_dev   = _make_entry(self, "Network env DEV prefix:",      "network_env_dev",            state, r4+1,  placeholder="dev-")
        _, lbl_stg,  ent_stg   = _make_entry(self, "Network env Stage prefix:",    "network_env_stage",          state, r4+2,  placeholder="test-")
        _, lbl_prd,  ent_prd   = _make_entry(self, "Network env Prod prefix:",     "network_env_prod",           state, r4+3,  placeholder="prod-")
        _, lbl_sc,   ent_sc    = _make_entry(self, "Subnet Common:",               "subnetCommon",               state, r4+4,  placeholder="snet-esml-cmn-001")
        _, lbl_scs,  ent_scs   = _make_entry(self, "Subnet Common Scoring:",       "subnetCommonScoring",        state, r4+5,  placeholder="snet-esml-cmn-001-scoring")
        _, lbl_pbgw, ent_pbgw  = _make_entry(self, "Subnet Common PowerBI GW:",   "subnetCommonPowerbiGw",      state, r4+6,  placeholder="snet-esml-cmn-pbi-001")
        _, lbl_sga,  ent_sga   = _make_entry(self, "Subnet Proj GenAI:",           "subnetProjGenAI",            state, r4+7,  placeholder="snt-prj<xxx>-genai")
        _, lbl_aks,  ent_aks   = _make_entry(self, "Subnet Proj AKS:",             "subnetProjAKS",              state, r4+8,  placeholder="snt-prj<xxx>-aks")
        _, lbl_aks2, ent_aks2  = _make_entry(self, "Subnet Proj AKS 2:",           "subnetProjAKS2",             state, r4+9,  placeholder="snt-prj<xxx>-aks-002")
        _, lbl_aca,  ent_aca   = _make_entry(self, "Subnet Proj ACA:",             "subnetProjACA",              state, r4+10, placeholder="snt-prj<xxx>-aca")
        _, lbl_aca2, ent_aca2  = _make_entry(self, "Subnet Proj ACA 2:",           "subnetProjACA2",             state, r4+11, placeholder="snt-prj<xxx>-aca-002")
        _, lbl_wapp, ent_wapp  = _make_entry(self, "Subnet Proj WebApp/Func:",     "subnetProjWebapp",           state, r4+12, placeholder="snt-prj<xxx>-webapp")
        _, lbl_dbxp, ent_dbxp  = _make_entry(self, "Subnet Proj DBX Public:",     "subnetProjDatabricksPublic", state, r4+13, placeholder="snt-prj001-dbxpub")
        _, lbl_dbxpr,ent_dbxpr = _make_entry(self, "Subnet Proj DBX Private:",    "subnetProjDatabricksPrivate",state, r4+14, placeholder="snt-prj<xxx>-dbxpriv")
        self._adv_only.extend([
            _byos_sep, _byos_hdr, cb_byos,
            lbl_dev,  ent_dev,   lbl_stg,   ent_stg,   lbl_prd,  ent_prd,
            lbl_sc,   ent_sc,    lbl_scs,   ent_scs,   lbl_pbgw, ent_pbgw,
            lbl_sga,  ent_sga,   lbl_aks,   ent_aks,   lbl_aks2, ent_aks2,
            lbl_aca,  ent_aca,   lbl_aca2,  ent_aca2,  lbl_wapp, ent_wapp,
            lbl_dbxp, ent_dbxp,  lbl_dbxpr, ent_dbxpr,
        ])

    def _upd_dns(self):
        checked = self._dns_var.get()
        self.state["centralDnsZoneByPolicyInHub"]="true" if checked else "false"
        ns = "normal" if checked else "disabled"
        self._dns_sub_ent.configure(state=ns); self._dns_rg_ent.configure(state=ns)

    def on_enter(self):
        # Re-sync checkbox from state after snapshot load
        self._own_hub_var.set(_bool_str(self.state.get("enableAIFactoryHub", "false")))
        self._dns_var.set(_bool_str(self.state.get("centralDnsZoneByPolicyInHub", "false")))
        self._upd_dns()


# ===========================================================================
# PAGE 5: Project team & Cost center tag
# ===========================================================================
class PagePrefix(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\U0001f465  Project team & Cost center tag",
                  font=("Segoe UI",11,"bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))
        r = self._section("Tags & Cost", 1)
        ttk.Label(self, text="AI Factory Salt  (5 chars):").grid(row=r, column=0, sticky="w", padx=4, pady=2)
        self._salt_var = tk.StringVar(value="")
        state["aifactory_salt"] = ""
        salt_ent = ttk.Entry(self, textvariable=self._salt_var, width=42)
        salt_ent.grid(row=r, column=1, sticky="ew", padx=4, pady=2)
        self._hint("Leave blank — will be set automatically on first deploy", r+1)
        self._salt_var.trace_add("write", lambda *a: state.update({"aifactory_salt": self._salt_var.get()}))
        _make_entry(self, "Common Cost Center tag:", "tag_costceter_common", state, r+2)
        r2 = self._section("Project team members", r+4)
        self._email_var, self._email_ent = _make_entry_w(self, "Entra email (comma-separated):", "technical_admins_email", state, r2)
        self._oid_var,   self._oid_ent   = _make_entry_w(self, "Entra ObjectID * (UUID or comma-sep UUIDs):", "technical_admins_ad_object_id", state, r2+1)
        self._hint("Required — single UUID or comma-separated UUIDs, must not end with comma", r2+2)
        self._adgrp_var = tk.StringVar(value=state.get("use_ad_groups","true"))
        ttk.Radiobutton(self, text="Use AD Groups (recommended)",
                        variable=self._adgrp_var, value="true",
                        command=lambda: state.update({"use_ad_groups":"true"})).grid(row=r2+3, column=0, columnspan=2, sticky="w", padx=16, pady=2)
        ttk.Radiobutton(self, text="Use individual user ObjectIDs",
                        variable=self._adgrp_var, value="false",
                        command=lambda: state.update({"use_ad_groups":"false"})).grid(row=r2+4, column=0, columnspan=2, sticky="w", padx=16, pady=2)

        # --- IP whitelist (Hybrid mode only) ---
        self._ip_sep = ttk.Separator(self, orient="horizontal")
        self._ip_sep.grid(row=r2+5, column=0, columnspan=3, sticky="ew", padx=4, pady=(8,2))
        self._ip_lbl_hdr = ttk.Label(self, text="Hybrid Network IP Whitelist",
                                     font=("Segoe UI",9,"bold"), foreground="#0078d4")
        self._ip_lbl_hdr.grid(row=r2+6, column=0, columnspan=3, sticky="w", padx=4, pady=(0,2))
        self._ip_var, self._ip_lbl, self._ip_ent = _make_entry(
            self, "project_IP_whitelist:", "project_IP_whitelist", state, r2+7,
            placeholder="10.0.0.1,172.16.0.0/24")
        self._ip_hint = self._hint(
            "IPv4 addresses / CIDR blocks, comma-separated, no spaces  e.g. 10.1.2.3,192.168.0.0/24",
            r2+8)
        # hide by default; on_enter will show when mode == hybrid
        for w in (self._ip_sep, self._ip_lbl_hdr, self._ip_lbl, self._ip_ent, self._ip_hint):
            w.grid_remove()

    def on_enter(self):
        # Re-sync radio after snapshot load; show/hide IP whitelist for hybrid mode
        self._adgrp_var.set(self.state.get("use_ad_groups", "true"))
        is_hybrid = self.state.get("network_mode","public") == "hybrid"
        for w in (self._ip_sep, self._ip_lbl_hdr, self._ip_lbl, self._ip_ent, self._ip_hint):
            if is_hybrid:
                w.grid()
            else:
                w.grid_remove()
                self.state["project_IP_whitelist"] = ""

    def on_leave(self):
        # Email validation intentionally removed: AD groups do not require an email address.
        oid_err   = _validate_obj_id_field("Admin OID", self.state.get("technical_admins_ad_object_id",""), allow_empty=False)
        _set_field_state(self._oid_ent,   bool(oid_err))
        errs = [e for e in [oid_err] if e]
        if self.state.get("network_mode","public") == "hybrid":
            ip_err = _validate_ip_whitelist("project_IP_whitelist", self.state.get("project_IP_whitelist",""))
            _set_field_state(self._ip_ent, bool(ip_err))
            if ip_err:
                errs.append(ip_err)
        if errs:
            messagebox.showerror("Validation Error", "\n".join(errs))
            return False
        return True


# ===========================================================================
# PAGE 6: AI Factory features
# ===========================================================================
class PageSeedingKV(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        sf = _ScrollFrame(self); sf.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._sf = sf
        inn = sf.inner; inn.columnconfigure(1, weight=1)
        ttk.Label(inn, text="\U0001f511  AI Factory Extras", font=("Segoe UI",11,"bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))

        r = self._section("DEV Seeding KeyVault", 1, inn)
        self._kv_dev_sub_var, self._kv_dev_sub_ent = _make_entry_w(inn, "KV Subscription ID:", "dev_admin_bicep_input_keyvault_subscription", state, r)
        _make_entry(inn, "KV Resource Group:", "dev_admin_bicep_kv_fw_rg", state, r+1)
        _make_entry(inn, "KV Name:",           "dev_admin_bicep_kv_fw",    state, r+2)
        _hint(inn, "Subscription UUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", r+3)

        r2 = self._section("Stage Seeding KeyVault", r+5, inn)
        self._same_stage_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(inn, text="Use same values as Dev for Stage",
                        variable=self._same_stage_var, command=self._copy_to_stage).grid(
            row=r2, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        self._kv_test_sub_var, self._kv_test_sub_ent = _make_entry_w(inn, "KV Subscription ID:", "test_admin_bicep_input_keyvault_subscription", state, r2+1)
        self._kv_test_rg_var, _, _ = _make_entry(inn, "KV Resource Group:", "test_admin_bicep_kv_fw_rg", state, r2+2)
        self._kv_test_kv_var, _, _ = _make_entry(inn, "KV Name:",           "test_admin_bicep_kv_fw",    state, r2+3)

        r3 = self._section("Prod Seeding KeyVault", r2+5, inn)
        self._same_prod_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(inn, text="Use same values as Dev for Prod",
                        variable=self._same_prod_var, command=self._copy_to_prod).grid(
            row=r3, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        self._kv_prod_sub_var, self._kv_prod_sub_ent = _make_entry_w(inn, "KV Subscription ID:", "prod_admin_bicep_input_keyvault_subscription", state, r3+1)
        self._kv_prod_rg_var, _, _ = _make_entry(inn, "KV Resource Group:", "prod_admin_bicep_kv_fw_rg", state, r3+2)
        self._kv_prod_kv_var, _, _ = _make_entry(inn, "KV Name:",           "prod_admin_bicep_kv_fw",    state, r3+3)

        r5 = self._section("AI Factory Intelligence", r3+5, inn)
        _make_checkbox(inn, "Use Common ACR  (save cost — shared across all projects)", "useCommonACR", state, r5)
        _hint(inn, "Recommended: true, unless projects need isolated container registries", r5+1)
        _make_checkbox(inn, "Enable Delete For Disabled Resources  (Complete mode)", "enableDeleteForDisabledResources", state, r5+2)
        _hint(inn, 'Services set to "false" will be DELETED if they already exist', r5+3)

        r_sp = self._section("Common Service Principal Key Names  (optional)", r5+5, inn)
        _hint_nw(inn,
                 "Optional — names of secrets in the SEEDING KeyVault that hold the common (infra) SP credentials.",
                 r_sp, col=0, colspan=3)
        _make_entry(inn, "AppId KV secret name (optional):",  "inputCommonSPIDKey",           state, r_sp+1)
        _make_entry(inn, "Secret KV secret name (optional):", "inputCommonSPSecretKey",       state, r_sp+2)
        _make_entry(inn, "OID KV secret name (optional):",    "commonServicePrincipleOIDKey", state, r_sp+3)

    def _copy_to_stage(self):
        if self._same_stage_var.get():
            for src, dst in [("dev_admin_bicep_input_keyvault_subscription","test_admin_bicep_input_keyvault_subscription"),
                             ("dev_admin_bicep_kv_fw_rg","test_admin_bicep_kv_fw_rg"),
                             ("dev_admin_bicep_kv_fw","test_admin_bicep_kv_fw")]:
                self.state[dst] = self.state.get(src,"")
            self._kv_test_sub_var.set(self.state["test_admin_bicep_input_keyvault_subscription"])
            self._kv_test_rg_var.set(self.state["test_admin_bicep_kv_fw_rg"])
            self._kv_test_kv_var.set(self.state["test_admin_bicep_kv_fw"])

    def _copy_to_prod(self):
        if self._same_prod_var.get():
            for src, dst in [("dev_admin_bicep_input_keyvault_subscription","prod_admin_bicep_input_keyvault_subscription"),
                             ("dev_admin_bicep_kv_fw_rg","prod_admin_bicep_kv_fw_rg"),
                             ("dev_admin_bicep_kv_fw","prod_admin_bicep_kv_fw")]:
                self.state[dst] = self.state.get(src,"")
            self._kv_prod_sub_var.set(self.state["prod_admin_bicep_input_keyvault_subscription"])
            self._kv_prod_rg_var.set(self.state["prod_admin_bicep_kv_fw_rg"])
            self._kv_prod_kv_var.set(self.state["prod_admin_bicep_kv_fw"])

    def on_leave(self):
        kv_err = _validate_uuid_field("DEV KV Subscription ID", self.state.get("dev_admin_bicep_input_keyvault_subscription",""))
        _set_field_state(self._kv_dev_sub_ent, bool(kv_err))
        if kv_err:
            messagebox.showerror("Validation Error", kv_err)
            return False
        return True


# ===========================================================================
# PAGE 7: Foundry SKUs
# ===========================================================================
class PageSKU(WizardPage):
    """Service SKUs, split into a Dev tab and a Stage & Prod tab.

    test == Stage, so both 'test' and 'prod' environments use the *StageProd
    values while 'dev' uses the *Dev values.
    """
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\U0001f4ca  Service SKUs (per environment)",
                  font=("Segoe UI",11,"bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(10,4))
        self._hint("Set SKUs separately for Dev and for Stage & Prod. "
                   "test = Stage, so 'test' and 'prod' both use the Stage & Prod values.",
                   1, col=0, colspan=4)

        self._nb = ttk.Notebook(self)
        self._nb.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=4, pady=4)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        # Semantic Search tier has no per-environment template field, so the
        # same value is shared (and shown) on both tabs.
        self._sem_var = tk.StringVar(value=state.get("admin_semanticSearchTier","free"))
        self._sem_var.trace_add("write",
            lambda *a: state.update({"admin_semanticSearchTier": self._sem_var.get()}))
        _VAR_REGISTRY.append(("admin_semanticSearchTier", self._sem_var, False, state))

        # Per-tab AI Search radio widgets/vars (for network-mode free-tier logic)
        self._search_radios = {}   # suffix -> {sku: radiobutton}
        self._search_vars   = {}   # suffix -> StringVar
        self._build_tab("Dev",          "Dev")
        self._build_tab("Stage & Prod", "StageProd")

    # -- tab builder --------------------------------------------------------
    def _build_tab(self, title, suffix):
        state = self.state
        tab = _ScrollFrame(self)
        self._nb.add(tab, text=f"  {title}  ")
        inn = tab.inner
        inn.columnconfigure(1, weight=1)

        # groups in template order
        order = []
        for f in SKU_FIELDS:
            if f[2] not in order:
                order.append(f[2])

        row = 0
        for group in order:
            row = self._section(group, row, inn)
            for base, label, g, default, choices, env_base in SKU_FIELDS:
                if g != group:
                    continue
                sk = f"{base}{suffix}"
                if base == "skuAISearch":
                    row = self._add_search_radios(inn, row, sk, label, default, suffix)
                    row = self._add_semantic_radios(inn, row)
                elif choices:
                    _make_combo(inn, label + ":", sk, state, row, choices, width=26)
                    row += 1
                else:
                    _make_entry(inn, label + ":", sk, state, row,
                                placeholder=default or "", width=28)
                    row += 1

    def _add_search_radios(self, inn, row, sk, label, default, suffix):
        state = self.state
        ttk.Label(inn, text=label + ":").grid(row=row, column=0, sticky="nw", padx=4, pady=2)
        rf = tk.Frame(inn, bg="#f5f5f5")
        rf.grid(row=row, column=1, columnspan=3, sticky="w", padx=4, pady=2)
        var = tk.StringVar(value=state.get(sk, default))
        radios = {}
        for idx, opt in enumerate(AI_SEARCH_SKUS):
            rb = ttk.Radiobutton(rf, text=opt, variable=var, value=opt)
            rb.grid(row=idx // 4, column=idx % 4, sticky="w", padx=6, pady=1)
            radios[opt] = rb
        var.trace_add("write", lambda *a, k=sk, v=var: state.update({k: v.get()}))
        _VAR_REGISTRY.append((sk, var, False, state))
        self._search_radios[suffix] = radios
        self._search_vars[suffix]   = var
        return row + 1

    def _add_semantic_radios(self, inn, row):
        ttk.Label(inn, text="Semantic Search tier:").grid(
            row=row, column=0, sticky="w", padx=4, pady=2)
        sf = tk.Frame(inn, bg="#f5f5f5")
        sf.grid(row=row, column=1, columnspan=3, sticky="w", padx=4, pady=2)
        for i, opt in enumerate(SEMANTIC_SKUS):
            ttk.Radiobutton(sf, text=opt, variable=self._sem_var, value=opt).grid(
                row=0, column=i, sticky="w", padx=8, pady=2)
        return row + 1

    def on_enter(self):
        # AI Search 'free' tier is not allowed when private endpoints are used.
        mode = self.state.get("network_mode", "public")
        for suffix in ("Dev", "StageProd"):
            radios = self._search_radios.get(suffix, {})
            rb = radios.get("free")
            if not rb:
                continue
            sk  = f"skuAISearch{suffix}"
            var = self._search_vars.get(suffix)
            if mode != "public":
                rb.config(state="disabled")
                if var is not None and var.get() == "free":
                    var.set("standard")
            else:
                rb.config(state="normal")


# ===========================================================================
# PAGE 8: Security / Logging / Cost
# ===========================================================================
class PageSecurityCost(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\U0001f6e1  Security, Logging & Cost Optimization",
                  font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=4,sticky="w",padx=8,pady=(10,4))
        r = self._section("Security / Defender for AI", 1)
        _make_checkbox(self, "Enable Defender for AI — Subscription Level", "enableDefenderforAISubLevel", state, r)
        _make_checkbox(self, "Enable Defender for AI — Resource Level", "enableDefenderforAIResourceLevel", state, r+1)
        _make_checkbox(self, "Add Bastion Host (COMMON resource group)", "addBastionHost", state, r+2)
        _make_checkbox(self, "Enable Admin VM (COMMON resource group)", "enableAdminVM", state, r+3)
        _make_entry(self, "Admin VM username:", "admin_username", state, r+4, placeholder="adminuser")
        r_agent = self._section("Build Agent / Runner", r+6)
        _make_checkbox(self, "Use self-hosted build agent / runner", "useSelfHostedBuildAgent", state, r_agent)
        _make_entry(self, "GitHub runner label:", "selfHostedRunnerLabel", state, r_agent+1, placeholder="aifactory-admin-vm")
        _make_entry(self, "Azure DevOps agent pool:", "adminVMBuildAgentPool", state, r_agent+2, placeholder="Default")
        _make_entry(self, "Azure DevOps agent name:", "adminVMBuildAgentName", state, r_agent+3)
        r2 = self._section("Logging & Cost Centers", r_agent+5)
        _make_entry(self, "Project Cost Center tag:", "tag_costcenter", state, r2)
        ttk.Label(self, text="Diagnostic Setting Level:").grid(row=r2+1, column=0, sticky="w", padx=4, pady=2)
        self._diag_var = tk.StringVar(value=state.get("diagnosticSettingLevel","gold"))
        _diag_frame = tk.Frame(self, bg="#f5f5f5")
        _diag_frame.grid(row=r2+1, column=1, columnspan=3, sticky="w")
        for lvl in DIAG_LEVELS:
            ttk.Radiobutton(_diag_frame, text=lvl, variable=self._diag_var, value=lvl,
                            command=lambda l=lvl: state.update({"diagnosticSettingLevel":l})).pack(
                side="left", padx=(0,8))
        r3 = self._section("Container Registry", r2+3)
        _make_checkbox(self, "ACR Admin User Enabled", "acr_adminUserEnabled", state, r3)
        self._acr_ded_var = tk.BooleanVar(value=_bool_str(state.get("acr_dedicated","true")))
        ttk.Checkbutton(self, text="ACR Dedicated (Premium)  — required for private endpoints or CMK",
                        variable=self._acr_ded_var, command=self._acr_toggle).grid(
            row=r3+1, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        self._hint("Cannot uncheck if network mode ≠ Public or CMK encryption is enabled", r3+2, col=0, colspan=4)
        ttk.Label(self, text="ACR SKU:").grid(row=r3+3, column=0, sticky="w", padx=4, pady=2)
        self._acr_sku_var = tk.StringVar(value=state.get("acr_SKU","Premium"))
        _acr_sku_frame = tk.Frame(self, bg="#f5f5f5")
        _acr_sku_frame.grid(row=r3+3, column=1, columnspan=3, sticky="w")
        for sku in ACR_SKUS:
            ttk.Radiobutton(_acr_sku_frame, text=sku, variable=self._acr_sku_var, value=sku,
                            command=lambda s=sku: state.update({"acr_SKU":s})).pack(
                side="left", padx=(0,8))
        r4 = self._section("RBAC", r3+5)
        _, lbl_brid, ent_brid = _make_entry(self, "BYO Contributor Role ID:", "BYOContributorRoleID", state, r4, placeholder="b24988ac-6180-42a0-ab88-20f7382dd24c")
        _make_checkbox(self, "Disable Contributor Access for Users", "disableContributorAccessForUsers", state, r4+1)
        _make_checkbox(self, "Disable RBAC Admin on RG for Users",   "disableRBACAdminOnRGForUsers",     state, r4+2)
        _make_checkbox(self, "Disable Subnet Join Action",           "disableSubnetJoinAction",          state, r4+3)
        _make_checkbox(self, "Disable Local Auth (AAD-only, no API keys)", "disableLocalAuth",            state, r4+4)
        r_kv = self._section("Keyvault & Encryption", r4+5)
        _make_checkbox(self, "Enable Customer Managed Key (CMK)", "cmk", state, r_kv)
        _make_checkbox(self, "CMK Disabled for AI Search", "cmkDisableForAISearch", state, r_kv+1)
        _make_checkbox(self, "CMK Disabled for Foundry",   "cmkDisableForFoundry",  state, r_kv+2)
        self._softdel_var, self._softdel_ent = _make_entry_w(self, "Key vault Soft delete  (7–90 days):", "admin_keyvaultSoftDeleteDays", state, r_kv+3)
        _make_checkbox(self, "Enable Keyvault RBAC update", "updateKeyvaultRbac", state, r_kv+4)
        r_cmk = self._section("CMK Key Details", r_kv+6)
        _make_entry(self, "CMK Key Name:", "cmkKeyName", state, r_cmk, placeholder="aifactory-cmk-key")
        _make_entry(self, "CMK Key Version  (leave blank for latest):", "cmkKeyVersion", state, r_cmk+1)
        r5 = self._section("Other", r_cmk+3)
        _make_checkbox(self, "Admin Hybrid Benefit", "admin_hybridBenefit", state, r5)
        _make_checkbox(self, "Enable Project VM",    "enableProjectVM",     state, r5+1)

    def _acr_toggle(self):
        if not self._acr_ded_var.get():
            cmk  = self.state.get("cmk","false").lower()=="true"
            mode = self.state.get("network_mode","public")
            if cmk or mode!="public":
                reason = "CMK encryption is enabled" if cmk else f"network mode is '{mode}'"
                messagebox.showwarning("Cannot uncheck",
                    f"ACR Dedicated (Premium) cannot be disabled because {reason}.")
                self._acr_ded_var.set(True); self.state["acr_dedicated"]="true"; return
        self.state["acr_dedicated"]="true" if self._acr_ded_var.get() else "false"

    def on_enter(self):
        if self.state.get("cmk","false").lower()=="true" or self.state.get("network_mode","public")!="public":
            self._acr_ded_var.set(True); self.state["acr_dedicated"]="true"

    def on_leave(self):
        sd_err = _validate_int_range("Key vault Soft delete", self.state.get("admin_keyvaultSoftDeleteDays","7"), 7, 90)
        _set_field_state(self._softdel_ent, bool(sd_err))
        if sd_err:
            messagebox.showerror("Validation Error", sd_err)
            return False
        return True


# ===========================================================================
# PAGE 9: Project & Core
# ===========================================================================
class PageProjectCore(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\U0001f4c1  Project Setup",
                  font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",padx=8,pady=(10,4))
        r = self._section("Project Number", 1)
        _make_entry(self, "Project Number  (3 digits):", "project_number_000", state, r, placeholder="001")
        r_del = r + 2
        # ── Danger-highlighted frame ───────────────────────────────────
        self._danger_frame = tk.Frame(self, bg="#f5f5f5",
                                      highlightthickness=2,
                                      highlightbackground="#f5f5f5")
        self._danger_frame.grid(row=r_del, column=0, columnspan=3,
                                sticky="ew", padx=2, pady=2)
        self._danger_frame.columnconfigure(0, weight=1)
        del_var, del_cb = _make_checkbox(
            self._danger_frame, "Delete all services for project",
            "deleteAllServicesForProject", state, 0)
        self._del_var = del_var

        del_kv_var, del_kv_cb = _make_checkbox(
            self._danger_frame, "  └ Also delete the project Key Vault",
            "deleteKeyvaultAlso", state, 1)
        self._del_kv_var = del_kv_var

        del_all_var, del_all_cb = _make_checkbox(
            self._danger_frame, "Delete all, including networking and logs",
            "deleteAllForProject", state, 2)
        self._del_all_var = del_all_var

        def _update_danger(*_):
            is_set = del_var.get() or del_all_var.get()
            border = "#e74c3c" if is_set else "#f5f5f5"
            bg     = "#fdecea" if is_set else "#f5f5f5"
            self._danger_frame.config(highlightbackground=border, bg=bg)
            # "Also delete Key Vault" only applies when deleting all services
            del_kv_cb.config(state="normal" if del_var.get() else "disabled")

        del_var.trace_add("write", _update_danger)
        del_all_var.trace_add("write", _update_danger)
        _update_danger()   # apply initial state
        self._hint(
            "Delete all services for project:\n"
            "  \u2022 Deletes all AI Factory created services in the project resource group\n"
            "  \u2022 Removes project subnets in the common resource group\n"
            "  \u2022 Purges soft-deleted resources (Foundry, Azure ML, etc.)\n"
            "  \u2022 Key Vault is retained by default; tick 'Also delete the project Key Vault'\n"
            "    to also delete it (secrets, CMK keys, RBAC)\n"
            "Delete all (including networking and logs) - ULTRA DELETE MODE:\n"
            "  \u2022 Deletes the entire project resource group, including resources NOT created\n"
            "    by AI Factory\n"
            "  \u2022 Use with extreme caution!",
            r_del + 1)
        r2 = self._section("Pipeline Networking", r_del + 4)
        _make_checkbox(self, "Run Networking step  (true for new project; false to update only)", "runNetworkingVar", state, r2)
        self._hint("Set true when creating a new project, false when updating existing services", r2+1)
        r3 = self._section("Service Principal KV Names  (optional)", r2+3)
        _make_entry(self, "SP App ID KV Name (optional):", "project_service_principal_AppID_seeding_kv_name", state, r3)
        _make_entry(self, "SP OID KV Name (optional):",    "project_service_principal_OID_seeding_kv_name",   state, r3+1)
        _make_entry(self, "SP Secret KV Name (optional):", "project_service_principal_Secret_seeding_kv_name", state, r3+2)
        self._hint("Optional — secret name stored in Azure Key Vault used by the pipeline", r3+3)

    def on_leave(self):
        pn = self.state.get("project_number_000","").strip()
        if pn and not re.match(r'^\d{3}$', pn):
            messagebox.showerror("Validation Error", "Project Number must be 3 digits (e.g. 001, 007, 042)")
            return False
        return True


# ===========================================================================
# PAGE 10: ON/OFF: GenAI & ML
# ===========================================================================
class PageGenAIML(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        sf = _ScrollFrame(self); sf.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._sf = sf
        inn = sf.inner; inn.columnconfigure(1, weight=1)
        ttk.Label(inn, text="\U0001f916  ON/OFF: GenAI & ML", font=("Segoe UI",11,"bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10,4))

        # --- AI Foundry section ---
        r = self._section("AI Foundry 2025 Flags", 1, inn)
        # Always visible
        _make_checkbox(inn, "Enable AI Foundry 2025 (enterprise-grade, GA)", "enableAIFoundry", state, r)

        # Advanced-only Foundry flags
        _, cb_add  = _make_checkbox(inn, "Add AI Foundry (new random name — use for re-deploy/debug)", "addAIFoundry", state, r+1)
        _, cb_cap  = _make_checkbox(inn, "Enable AI Foundry Capability Host (Agents — CosmosDB+Storage)", "enableAFoundryCaphost", state, r+2)
        _, cb_clean = _make_checkbox(inn, "Clean Foundry Caphost (remove capability host resources on delete)", "cleanFoundryCaphost", state, r+3)
        _, cb_upd  = _make_checkbox(inn, "Update AI Foundry (RBAC update mode — run pipeline twice)", "updateAIFoundry", state, r+4)
        _, cb_defp = _make_checkbox(inn, "Enable AIFactory Created Default Project (for AIFv2)", "enableAIFactoryCreatedDefaultProjectForAIFv2", state, r+5)

        lbl_fdt = ttk.Label(inn, text="Foundry Deployment Type:")
        lbl_fdt.grid(row=r+6, column=0, sticky="w", padx=4, pady=2)
        self._fdt_var = tk.StringVar(value=state.get("foundryDeploymentType","2"))
        desc = {"1":"PG-based","2":"AVM-based (recommended)","3":"Both"}
        fdt_frame = tk.Frame(inn, bg="#f5f5f5")
        fdt_frame.grid(row=r+7, column=0, columnspan=3, sticky="w", padx=16, pady=1)
        for i, val in enumerate(["1","2","3"]):
            ttk.Radiobutton(fdt_frame, text=f"{val} — {desc[val]}",
                            variable=self._fdt_var, value=val,
                            command=lambda v=val: state.update({"foundryDeploymentType":v})).grid(
                row=0, column=i, sticky="w", padx=12, pady=1)

        self._adv_only.extend([cb_add, cb_cap, cb_clean, cb_upd, cb_defp, lbl_fdt, fdt_frame])

        # AI Foundry v1 / AI Services flags (advanced)
        _, cb_ais    = _make_checkbox(inn, "Enable AI Services (standalone OpenAI/model endpoint)",     "enableAIServices",   state, r+8)
        _, cb_hub    = _make_checkbox(inn, "Enable AI Foundry Hub (legacy v1 Hub — requires AI Svcs)", "enableAIFoundryHub",  state, r+9)
        _, cb_addhub = _make_checkbox(inn, "Add AI Foundry Hub (new random name — re-deploy/debug)",   "addAIFoundryHub",    state, r+10)
        self._adv_only.extend([cb_ais, cb_hub, cb_addhub])

        # --- OpenAI Model SKUs section (shown in BOTH simple and advanced mode) ---
        rmods = self._add_models_section(inn, r + 11)

        # --- ML section ---
        r2 = self._section("ML Flags", rmods + 1, inn)
        _make_checkbox(inn, "Enable Azure Machine Learning", "enableAzureMachineLearning", state, r2)
        _, cb_add_aml = _make_checkbox(inn, "Add Azure Machine Learning (new random name)", "addAzureMachineLearning", state, r2+1)
        self._adv_only.append(cb_add_aml)
        _make_checkbox(inn, "Enable Databricks",         "enableDatabricks",  state, r2+2)
        _make_checkbox(inn, "Enable Azure Data Factory", "enableDatafactory", state, r2+3)
        _, cb_dtfc = _make_checkbox(inn, "Enable Azure Data Factory (Common RG)", "enableDatafactoryCommon", state, r2+4)
        self._adv_only.append(cb_dtfc)

        # --- AKS section ---
        r3 = self._section("AKS for Azure ML", r2+6, inn)
        _make_checkbox(inn, "Enable AKS for Azure ML", "enableAksForAzureML", state, r3)
        _make_checkbox(inn, "Enable Standalone AKS cluster", "enableAKS", state, r3+1)
        _make_entry(inn, "  AKS SKU Name:", "aksSkuName", state, r3+2, placeholder="Base")
        _make_entry(inn, "  AKS SKU Tier:", "aksSkuTier", state, r3+3, placeholder="Standard")
        _make_checkbox(inn, "  Enable Private AKS cluster", "aksEnablePrivateCluster", state, r3+4)

        hint_aks = _hint(inn, "AKS private networking — disabled in Public network mode", r3+5)

        lbl_out = ttk.Label(inn, text="AKS Outbound Type:")
        lbl_out.grid(row=r3+6, column=0, sticky="w", padx=4, pady=2)
        self._aks_out_var = tk.StringVar(value=state.get("aksOutboundType","loadBalancer"))
        aks_out_f = tk.Frame(inn, bg="#f5f5f5"); aks_out_f.grid(row=r3+6, column=1, columnspan=2, sticky="w")
        for i, v in enumerate(AKS_OUTBOUND):
            ttk.Radiobutton(aks_out_f, text=v, variable=self._aks_out_var, value=v,
                            command=lambda x=v: state.update({"aksOutboundType":x})).grid(row=0,column=i,sticky="w",padx=8)

        lbl_dns = ttk.Label(inn, text="AKS Private DNS Zone:")
        lbl_dns.grid(row=r3+7, column=0, sticky="w", padx=4, pady=2)
        self._aks_dns_var = tk.StringVar(value=state.get("aksPrivateDNSZone","system"))
        aks_dns_f = tk.Frame(inn, bg="#f5f5f5"); aks_dns_f.grid(row=r3+7, column=1, columnspan=2, sticky="w")
        for i, v in enumerate(AKS_DNS_ZONES):
            ttk.Radiobutton(aks_dns_f, text=v, variable=self._aks_dns_var, value=v,
                            command=lambda x=v: state.update({"aksPrivateDNSZone":x})).grid(row=0,column=i,sticky="w",padx=8)

        hint_dns_byo = _hint(inn, "Or enter a full resource ID for BYO private DNS zone", r3+8)
        self._aks_fw_var, self._aks_fw_ent = _make_entry_w(inn, "AKS Azure Firewall Private IP:", "aksAzureFirewallPrivateIp", state, r3+9)
        hint_fw = _hint(inn, "Only needed if aksOutboundType = userDefinedRouting", r3+10)

        # Store for network-mode toggling
        self._aks_out_f = aks_out_f
        self._aks_dns_f = aks_dns_f

        # Advanced-only AKS detail widgets
        self._adv_only.extend([hint_aks, lbl_out, aks_out_f, lbl_dns, aks_dns_f,
                                hint_dns_byo, self._aks_fw_ent, hint_fw])

    # -- OpenAI model deployment section (moved from the SKU page) -----------
    def _add_models_section(self, inn, start_row):
        """Build the OpenAI model deployment widgets. Returns the next free row.

        These widgets are intentionally NOT added to self._adv_only, so they
        are visible in both simple and advanced mode.
        """
        state = self.state
        r3 = self._section("OpenAI Model SKUs", start_row, inn)
        _hint(inn, "Deploy language and embedding models for AI Foundry", r3, col=0, colspan=4)

        # Embedding models
        re_ = r3 + 1
        ttk.Label(inn, text="Embedding models:", font=("Segoe UI",9,"bold")).grid(
            row=re_, column=0, columnspan=2, sticky="w", padx=4, pady=(6,2))
        _make_checkbox(inn, "text-embedding-ada-002", "deployModel_text_embedding_ada_002", state, re_+1)
        _make_checkbox(inn, "text-embedding-3-large", "deployModel_text_embedding_3_large", state, re_+2)
        _make_checkbox(inn, "text-embedding-3-small", "deployModel_text_embedding_3_small", state, re_+3)
        _make_entry(inn, "Embedding capacity (K TPM):", "default_embedding_capacity", state, re_+4, placeholder="25", width=8)

        # Other models
        rg = re_ + 6
        ttk.Label(inn, text="Other models:", font=("Segoe UI",9,"bold")).grid(
            row=rg, column=0, columnspan=2, sticky="w", padx=4, pady=(6,2))
        _make_checkbox(inn, "Deploy GPT-5.4o mini", "deployModel_gpt_54_mini", state, rg+1)
        _make_entry(inn, "  GPT-5.4o-mini version:", "default_gpt_54_mini_version", state, rg+2, placeholder="2026-03-17", width=20)
        _hint(inn, "2026-03-17 (GPT-5.4o-mini)", rg+3, col=1, colspan=3)
        _make_checkbox(inn, "Deploy GPT-4o", "deployModel_gpt_4o", state, rg+4)
        _make_entry(inn, "  GPT-4o version:", "default_gpt_4o_version", state, rg+5, placeholder="2024-11-20", width=20)

        # Custom model
        rc = rg + 7
        self._custom_var, self._custom_cb = _make_checkbox(inn, "Custom model", "deployModel_gpt_X", state, rc)
        _, self._cx_name_lbl, self._cx_name_ent = _make_entry(inn, "  Model name:", "modelGPTXName", state, rc+1, placeholder="gpt-5-mini", width=28)
        _, self._cx_ver_lbl, self._cx_ver_ent = _make_entry(inn, "  Version:", "modelGPTXVersion", state, rc+2, placeholder="(latest)", width=16)
        self._cx_sku_lbl = ttk.Label(inn, text="  Model SKU:")
        self._cx_sku_lbl.grid(row=rc+3, column=0, sticky="w", padx=4, pady=2)
        self._gptx_sku_var = tk.StringVar(value=state.get("modelGPTXSku","DataZoneStandard"))
        gf = tk.Frame(inn, bg="#f5f5f5"); gf.grid(row=rc+3, column=1, columnspan=3, sticky="w")
        self._cx_sku_radios = []
        for i, sku in enumerate(MODEL_SKUS):
            rb = ttk.Radiobutton(gf, text=sku, variable=self._gptx_sku_var, value=sku,
                            command=lambda s=sku: state.update({"modelGPTXSku":s}))
            rb.grid(row=0, column=i, sticky="w", padx=6)
            self._cx_sku_radios.append(rb)
        _VAR_REGISTRY.append(("modelGPTXSku", self._gptx_sku_var, False, state))
        _, self._cx_cap_lbl, self._cx_cap_ent = _make_entry(inn, "  Capacity (K TPM):", "modelGPTXCapacity", state, rc+4, placeholder="30", width=8)
        self._custom_var.trace_add("write", lambda *a: self._toggle_custom_fields())
        self._toggle_custom_fields()

        # Default GPT settings
        rh = rc + 6
        _make_entry(inn, "Default GPT capacity (K TPM):", "default_gpt_capacity", state, rh, placeholder="40", width=8)
        ttk.Label(inn, text="Default model SKU:").grid(row=rh+1, column=0, sticky="w", padx=4, pady=2)
        self._def_sku_var = tk.StringVar(value=state.get("default_model_sku","Standard"))
        dsf = tk.Frame(inn, bg="#f5f5f5"); dsf.grid(row=rh+1, column=1, columnspan=3, sticky="w")
        for i, sku in enumerate(MODEL_SKUS):
            ttk.Radiobutton(dsf, text=sku, variable=self._def_sku_var, value=sku,
                            command=lambda s=sku: state.update({"default_model_sku":s})).grid(row=0,column=i,sticky="w",padx=6)
        _VAR_REGISTRY.append(("default_model_sku", self._def_sku_var, False, state))
        return rh + 2

    def _toggle_custom_fields(self):
        enabled = self._custom_var.get()
        st = "normal" if enabled else "disabled"
        for w in (self._cx_name_ent, self._cx_ver_ent, self._cx_cap_ent):
            w.configure(state=st)
        for rb in self._cx_sku_radios:
            rb.configure(state=st)
        fg = "black" if enabled else "grey"
        for lbl in (self._cx_name_lbl, self._cx_ver_lbl, self._cx_sku_lbl, self._cx_cap_lbl):
            lbl.configure(foreground=fg)

    def on_enter(self):
        mode = self.state.get("network_mode","public")
        is_public = (mode == "public")
        new_state = "disabled" if is_public else "normal"
        for rb in self._aks_out_f.winfo_children():
            rb.configure(state=new_state)
        for rb in self._aks_dns_f.winfo_children():
            rb.configure(state=new_state)
        self._aks_fw_ent.configure(state=new_state)


# ===========================================================================
# PAGE 11: ON/OFF: Cognitive & DB
# ===========================================================================
class PageCognitiveDatabases(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        sf = _ScrollFrame(self); sf.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._sf = sf
        inn = sf.inner; inn.columnconfigure(1, weight=1)
        ttk.Label(inn, text="\U0001f9e0  ON/OFF: Cognitive Services & Databases",
                  font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",padx=8,pady=(10,4))

        r = self._section("AI Search", 1, inn)
        _make_checkbox(inn, "Enable AI Search", "enableAISearch", state, r)
        _, cb_add_search = _make_checkbox(inn, "Add AI Search (new random name)", "addAISearch", state, r+1)
        self._adv_only.append(cb_add_search)

        r2 = self._section("Azure AI Services", r+3, inn)
        _make_checkbox(inn, "Enable Azure OpenAI",             "enableAzureOpenAI",       state, r2)
        _make_checkbox(inn, "Enable Azure AI Vision",          "enableAzureAIVision",     state, r2+1)
        _make_checkbox(inn, "Enable Azure Speech",             "enableAzureSpeech",       state, r2+2)
        _make_checkbox(inn, "Enable AI Document Intelligence", "enableAIDocIntelligence", state, r2+3)
        _make_checkbox(inn, "Enable Content Safety",           "enableContentSafety",     state, r2+4)

        r3 = self._section("Databases", r2+6, inn)
        _make_checkbox(inn, "Enable CosmosDB  (needed for Agents)", "enableCosmosDB", state, r3)

        lbl_ck = ttk.Label(inn, text="  CosmosDB Kind:")
        lbl_ck.grid(row=r3+1, column=0, sticky="w", padx=20, pady=2)
        self._cosmos_kind_var = tk.StringVar(value=state.get("cosmosKind","GlobalDocumentDB"))
        ck_f = tk.Frame(inn, bg="#f5f5f5"); ck_f.grid(row=r3+1, column=1, columnspan=2, sticky="w")
        for i, k in enumerate(COSMOS_KINDS):
            ttk.Radiobutton(ck_f, text=k, variable=self._cosmos_kind_var, value=k,
                            command=lambda x=k: state.update({"cosmosKind":x})).grid(row=0,column=i,sticky="w",padx=8)
        self._adv_only.extend([lbl_ck, ck_f])

        _make_checkbox(inn, "Enable PostgreSQL",   "enablePostgreSQL",  state, r3+2)
        _make_entry(inn, "  PostgreSQL Admin Emails:", "postGresAdminEmails", state, r3+3, placeholder="admin@domain.com")
        _make_checkbox(inn, "Enable Redis Cache",  "enableRedisCache",  state, r3+4)
        _make_checkbox(inn, "Enable SQL Database", "enableSQLDatabase", state, r3+5)
        
        _make_checkbox(inn, "Enable Elasticsearch", "enableElasticsearch", state, r3+6)
        _, lbl_elastic_email, ent_elastic_email = _make_entry(inn, "  Elastic Cloud Email:", "elasticEmail", state, r3+7, placeholder="admin@example.com")
        _, lbl_elastic_first, ent_elastic_first = _make_entry(inn, "  Elastic First Name:", "elasticFirstName", state, r3+8, placeholder="AI")
        _, lbl_elastic_last, ent_elastic_last = _make_entry(inn, "  Elastic Last Name:", "elasticLastName", state, r3+9, placeholder="Factory")
        _, lbl_elastic_company, ent_elastic_company = _make_entry(inn, "  Elastic Company Name:", "elasticCompanyName", state, r3+10, placeholder="Organization")
        _, lbl_elastic_size, ent_elastic_size = _make_entry(inn, "  Elastic Deployment Size:", "elasticDeploymentSize", state, r3+11, placeholder="small")
        _, lbl_elastic_sku, ent_elastic_sku = _make_entry(inn, "  Elastic SKU:", "elasticSku", state, r3+12, placeholder="ess-consumption-2024_Monthly")
        
        # Hide Elasticsearch detail fields in Simple mode
        self._adv_only.extend([
            lbl_elastic_email, ent_elastic_email,
            lbl_elastic_first, ent_elastic_first,
            lbl_elastic_last, ent_elastic_last,
            lbl_elastic_company, ent_elastic_company,
            lbl_elastic_size, ent_elastic_size,
            lbl_elastic_sku, ent_elastic_sku
        ])

        r4 = self._section("Bing Search", r3+14, inn)
        _make_checkbox(inn, "Enable Bing",               "enableBing",            state, r4)
        _make_checkbox(inn, "Enable Bing Custom Search", "enableBingCustomSearch", state, r4+1)
        _, lbl_bsku, ent_bsku = _make_entry(inn, "  Bing Custom Search SKU:", "bingCustomSearchSku", state, r4+2, placeholder="G2")


# ===========================================================================
# PAGE 12: ON/OFF: App & Integration
# ===========================================================================
class PageIntegrationCompute(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        sf = _ScrollFrame(self); sf.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._sf = sf
        inn = sf.inner; inn.columnconfigure(1, weight=1)
        ttk.Label(inn, text="\U0001f50c  ON/OFF: App & Integration",
                  font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",padx=8,pady=(10,4))

        # --- Azure Functions ---
        r = self._section("Azure Functions", 1, inn)
        _make_checkbox(inn, "Enable Azure Functions", "enableFunction", state, r)

        lbl_frt = ttk.Label(inn, text="  Runtime:")
        lbl_frt.grid(row=r+1, column=0, sticky="w", padx=20, pady=2)
        self._func_rt_var = tk.StringVar(value=state.get("functionRuntime","python"))
        func_rt_f = tk.Frame(inn, bg="#f5f5f5"); func_rt_f.grid(row=r+1, column=1, columnspan=3, sticky="w")
        for i, rt in enumerate(FUNC_RUNTIMES):
            ttk.Radiobutton(func_rt_f, text=rt, variable=self._func_rt_var, value=rt,
                            command=lambda x=rt: self._upd_func_rt(x)).grid(row=0,column=i,sticky="w",padx=8)
        self._func_ver_var, self._func_ver_combo, lbl_fv = _make_combo(
            inn, "  Version:", "functionVersion", state, r+2,
            FUNC_VERSIONS.get(state.get("functionRuntime","python"),["3.11"]), width=12)
        self._adv_only.extend([lbl_frt, func_rt_f, lbl_fv, self._func_ver_combo])

        # --- Web App ---
        r2 = self._section("Web App", r+4, inn)
        _make_checkbox(inn, "Enable Web App", "enableWebApp", state, r2)

        lbl_wrt = ttk.Label(inn, text="  Runtime:")
        lbl_wrt.grid(row=r2+1, column=0, sticky="w", padx=20, pady=2)
        self._webapp_rt_var = tk.StringVar(value=state.get("webAppRuntime","python"))
        wa_rt_f = tk.Frame(inn, bg="#f5f5f5"); wa_rt_f.grid(row=r2+1, column=1, columnspan=3, sticky="w")
        for i, rt in enumerate(WEBAPP_RUNTIMES):
            ttk.Radiobutton(wa_rt_f, text=rt, variable=self._webapp_rt_var, value=rt,
                            command=lambda x=rt: self._upd_webapp_rt(x)).grid(row=0,column=i,sticky="w",padx=8)
        self._webapp_ver_var, self._webapp_ver_combo, lbl_wv = _make_combo(
            inn, "  Version:", "webAppRuntimeVersion", state, r2+2,
            WEBAPP_VERSIONS.get(state.get("webAppRuntime","python"),["3.11"]), width=12)
        self._ase_sku_var,  ase_sku_cb,  lbl_as = _make_combo(inn, "  ASE SKU:",      "aseSku",      state, r2+3, ASE_SKUS,      width=14)
        self._ase_code_var, ase_code_cb, lbl_ac = _make_combo(inn, "  ASE SKU Code:", "aseSkuCode",  state, r2+4, ASE_SKU_CODES, width=12)
        _aw_var, lbl_aw, ent_aw = _make_entry(inn, "  ASE Workers:", "aseSkuWorkers", state, r2+5, placeholder="1", width=6)
        self._adv_only.extend([lbl_wrt, wa_rt_f, lbl_wv, self._webapp_ver_combo,
                                lbl_as,  ase_sku_cb,
                                lbl_ac,  ase_code_cb,
                                lbl_aw,  ent_aw])

        # --- Container Apps ---
        r3 = self._section("Container Apps", r2+7, inn)
        _make_checkbox(inn, "Enable Container Apps", "enableContainerApps", state, r3)
        _, cb_aidash = _make_checkbox(inn, "Enable App Insights Dashboard", "enableAppInsightsDashboard", state, r3+1)
        self._adv_only.append(cb_aidash)

        # --- Integration ---
        r4 = self._section("Integration", r3+3, inn)
        _make_checkbox(inn, "Enable Logic Apps",   "enableLogicApps",  state, r4)
        _make_checkbox(inn, "Enable Event Hubs",   "enableEventHubs",  state, r4+1)
        _make_checkbox(inn, "Enable Bot Service  (Microsoft Foundry)", "enableBotService", state, r4+2)
        _, lbl_apim, ent_apim = _make_entry(inn, "Foundry API Mgmt Resource ID (optional):", "foundryApiManagementResourceId", state, r4+3, placeholder="/subscriptions/...")
        self._adv_only.extend([lbl_apim, ent_apim])
        # --- BYO App Service Environment ---
        r5 = self._section("BYO App Service Environment", r4+5, inn)
        _ase_cb_var, _ase_cb = _make_checkbox(inn, "BYO App Service Environment (ASE v3)", "byoASEv3", state, r5)
        _ase_var, _, _ase_ent = _make_entry(inn, "ASE Resource ID:", "byoAseFullResourceId", state, r5+1)
        _hint(inn, "Resource ID must start with a forward slash, such as /subscriptions/", r5+2, col=0, colspan=3)
        def _validate_ase(*_):
            v = _ase_var.get().strip()
            bad = _ase_cb_var.get() and bool(v) and not v.startswith("/")
            _ase_ent.configure(style="Error.TEntry" if bad else "TEntry")
        def _ase_cb_changed(*_):
            state["byoASEv3"] = "true" if _ase_cb_var.get() else "false"
            _validate_ase()
            if _ase_cb_var.get():
                v = _ase_var.get().strip()
                if not v or not v.startswith("/"):
                    messagebox.showwarning(
                        "ASE Resource ID required",
                        "BYO App Service Environment is enabled.\n\n"
                        "ASE Resource ID must start with a forward slash:\n"
                        "  /subscriptions/<sub-id>/resourceGroups/...")
        _ase_var.trace_add("write", _validate_ase)
        _ase_cb.configure(command=_ase_cb_changed)
        _validate_ase()

    def _upd_func_rt(self, rt):
        self.state["functionRuntime"] = rt
        versions = FUNC_VERSIONS.get(rt, ["3.11"])
        self._func_ver_combo.configure(values=versions)
        if self._func_ver_var.get() not in versions:
            self._func_ver_var.set(versions[0])
            self.state["functionVersion"] = versions[0]

    def _upd_webapp_rt(self, rt):
        self.state["webAppRuntime"] = rt
        versions = WEBAPP_VERSIONS.get(rt, ["3.11"])
        self._webapp_ver_combo.configure(values=versions)
        if self._webapp_ver_var.get() not in versions:
            self._webapp_ver_var.set(versions[0])
            self.state["webAppRuntimeVersion"] = versions[0]


# ===========================================================================
# PAGE 13: Architecture Preview — REMOVED in v017
# ===========================================================================
# class PageArchitecture removed (page deleted per v017 requirements)


# ===========================================================================
# PAGE 14: Other Settings
# ===========================================================================
class PageOther(WizardPage):
    def __init__(self, parent, state):
        super().__init__(parent, state)
        ttk.Label(self, text="\u2699  Other Settings",
                  font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",padx=8,pady=(10,4))

        r = self._section("Azure Machine Learning Service Principal", 1)
        _make_entry(self, "AzureML SP Object ID:", "azure_machinelearning_sp_oid", state, r)
        self._hint("Find in Entra ID > Enterprise apps: 'Azure Machine Learning'  (AppId: 0736f41a-...)", r+1)

        r2 = self._section("Monitoring (AMPLS)", r+3)
        _make_checkbox(self, "Enable AMPLS (Azure Monitor Private Link Scope)", "enableAMPLS", state, r2)
        self._hint("Creates AMPLS in Hub subscription; configures AppInsights in private/private mode", r2+1)

        r3 = self._section("Databricks", r2+3)
        _make_entry(self, "Databricks OID:", "databricksOID", state, r3)
        self._hint("Object ID of the Databricks service principal (e.g. 6f63d607-fdce-...)", r3+1)

        r4 = self._section("Debug & Retry Settings", r3+3)
        _make_checkbox(self, "Debug: Enable Cleaning on Error (delete failed resources)", "debugEnableCleaning", state, r4)
        _make_checkbox(self, "Update RBAC (updateRbac — run pipeline twice to update roles)", "updateRbac", state, r4+1)
        _make_checkbox(self, "Disable Validation Tasks (debug — skip subnet/DNS checks)", "debug_disable_validation_tasks", state, r4+2)
        _make_checkbox(self, "Enable Retries on Failure", "enableRetries", state, r4+3)
        _make_entry(self, "  Retry wait minutes (1st):", "retryMinutes", state, r4+4, placeholder="5")
        _make_entry(self, "  Retry wait minutes (extended):", "retryMinutesExtended", state, r4+5, placeholder="15")
        _make_entry(self, "  Max retry attempts:", "maxRetryAttempts", state, r4+6, placeholder="1")


# ===========================================================================
# PAGE 15: Summary
# ===========================================================================
class PageSummary(WizardPage):
    """Summary page with two tabs.

    Tab 1 – Summary (colour-coded):
      Red     = invalid value
      Green   = value equals DEFAULT_STATE (unchanged)
      Magenta = value differs from DEFAULT_STATE (user-changed)

    Tab 2 – Full File:
      Shows the complete variables.yaml (ADO) or .env (GitHub) that will be
      written.  Wizard-managed lines are highlighted; template-only lines are
      shown in grey.
    """

    # ── static validators keyed by state-key ──────────────────────────────
    _VALIDATORS: dict = {}   # populated in __init__ after class body

    def __init__(self, parent, state):
        super().__init__(parent, state)

        # ── top bar: title + legend ────────────────────────────────────────
        top = tk.Frame(self, bg="#f5f5f5")
        top.grid(row=0, column=0, columnspan=4, sticky="ew", padx=8, pady=(8,2))
        tk.Label(top, text="Summary — review before saving",
                 font=("Segoe UI",11,"bold"), bg="#f5f5f5").pack(side="left")
        leg = tk.Frame(top, bg="#f5f5f5")
        leg.pack(side="right")
        for txt, col in (("invalid","#f44747"),("default","#4ec994"),("changed","#c586c0")):
            tk.Label(leg, text=f"● {txt}", fg=col, bg="#f5f5f5",
                     font=("Segoe UI",8)).pack(side="left", padx=4)

        # ── notebook ──────────────────────────────────────────────────────
        self._nb = ttk.Notebook(self)
        self._nb.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=4, pady=2)
        self.rowconfigure(1, weight=1); self.columnconfigure(2, weight=1)

        # ── Tab 1: Summary ────────────────────────────────────────────────
        t1 = tk.Frame(self._nb, bg="#1e1e1e")
        self._nb.add(t1, text="  Summary  ")
        self._text = tk.Text(t1, wrap="none",
                             font=("Consolas",9), bg="#1e1e1e", fg="#d4d4d4",
                             insertbackground="white", selectbackground="#264f78",
                             relief="flat", bd=0)
        sb1v = ttk.Scrollbar(t1, orient="vertical",   command=self._text.yview)
        sb1h = ttk.Scrollbar(t1, orient="horizontal",  command=self._text.xview)
        self._text.configure(yscrollcommand=sb1v.set, xscrollcommand=sb1h.set)
        sb1v.pack(side="right",  fill="y")
        sb1h.pack(side="bottom", fill="x")
        self._text.pack(side="left", fill="both", expand=True)

        for tag, col in (("hdr","#888888"),("lbl","#9cdcfe"),
                         ("red","#f44747"),("green","#4ec994"),("magenta","#c586c0"),
                         ("dark_gray","#585858"),("dim_hdr","#404040")):
            self._text.tag_configure(tag, foreground=col)

        # ── Tab 2: Full File ──────────────────────────────────────────────
        t2 = tk.Frame(self._nb, bg="#1e1e1e")
        self._nb.add(t2, text="  Full variables.yaml  ")
        self._text2 = tk.Text(t2, wrap="none",
                              font=("Consolas",9), bg="#1e1e1e", fg="#d4d4d4",
                              insertbackground="white", selectbackground="#264f78",
                              relief="flat", bd=0)
        sb2v = ttk.Scrollbar(t2, orient="vertical",   command=self._text2.yview)
        sb2h = ttk.Scrollbar(t2, orient="horizontal",  command=self._text2.xview)
        self._text2.configure(yscrollcommand=sb2v.set, xscrollcommand=sb2h.set)
        sb2v.pack(side="right",  fill="y")
        sb2h.pack(side="bottom", fill="x")
        self._text2.pack(side="left", fill="both", expand=True)

        for tag, col in (("sec_hdr","#569cd6"),("managed_ch","#c586c0"),
                         ("managed_ok","#4ec994"),("managed_err","#f44747"),
                         ("tmpl","#6a9955"),("dim","#555555")):
            self._text2.tag_configure(tag, foreground=col)

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _is_invalid(keys: list, s: dict) -> bool:
        """Return True if any key/value pair fails its validator."""
        for k in keys:
            v = str(s.get(k, ""))
            if k in ("dev_sub_id", "tenantId",
                     "privDnsSubscription_param",
                     "dev_admin_bicep_input_keyvault_subscription",
                     "test_admin_bicep_input_keyvault_subscription",
                     "prod_admin_bicep_input_keyvault_subscription"):
                if v and not _is_uuid(v): return True
            elif k == "test_sub_id" or k == "prod_sub_id":
                if v and not _is_uuid(v): return True
            elif k == "technical_admins_email":
                if not v: return True   # required
                if _validate_csv_emails(k, v): return True
            elif k == "technical_admins_ad_object_id":
                if not v: return True   # required
                if _validate_obj_id_field(k, v): return True
        return False

    @staticmethod
    def _value_tag(keys: list, s: dict) -> str:
        """Return 'red', 'green', or 'magenta' for the given state keys."""
        if PageSummary._is_invalid(keys, s):
            return "red"
        all_default = all(
            str(s.get(k, "")) == str(DEFAULT_STATE.get(k, ""))
            for k in keys
        )
        return "green" if all_default else "magenta"

    def _ins_row(self, label: str, keys: list, value_str: str):
        """Insert one data row: label in lbl-colour, value in semantic colour."""
        tag = PageSummary._value_tag(keys, self.state)
        self._text.insert(tk.END, f"  {label:<20}: ", "lbl")
        self._text.insert(tk.END, value_str + "\n", tag)

    def _ins_sep(self, text: str):
        """Insert a section separator / header line."""
        self._text.insert(tk.END, text + "\n", "hdr")

    # ── main render ───────────────────────────────────────────────────────
    def on_enter(self):
        s = self.state
        # update tab 2 label based on orchestrator
        fname = ".env" if s.get("orchestrator","ado") == "gha" else "variables.yaml"
        self._nb.tab(1, text=f"  Full {fname}  ")

        # ── Tab 1: colour-coded summary ───────────────────────────────────
        self._text.configure(state="normal")
        self._text.delete("1.0", tk.END)
        R = self._ins_row
        S = self._ins_sep

        S("=" * 62)
        R("Orchestrator",      ["orchestrator"],             s.get("orchestrator","?"))
        R("Network Mode",      ["network_mode"],              s.get("network_mode","?"))
        if s.get("network_mode","public") == "hybrid":
            R("IP Whitelist",     ["project_IP_whitelist"],      s.get("project_IP_whitelist","") or "(none)")
        S("--- Scale set & Vnets ---")
        R("Suffix RG",         ["admin_aifactorySuffixRG"],   s.get("admin_aifactorySuffixRG","?"))
        R("Dev Sub ID",        ["dev_sub_id"],                s.get("dev_sub_id","?"))
        R("Test Sub ID",       ["test_sub_id"],               s.get("test_sub_id","") or "(same as Dev)")
        R("Prod Sub ID",       ["prod_sub_id"],               s.get("prod_sub_id","") or "(same as Dev)")
        R("Tenant ID",         ["tenantId"],                  s.get("tenantId","?"))
        R("CIDR dev/tst/prd",  ["dev_cidr_range","test_cidr_range","prod_cidr_range"],
                                f"{s.get('dev_cidr_range','?')} / {s.get('test_cidr_range','?')} / {s.get('prod_cidr_range','?')}")
        R("Region",            ["admin_location","admin_locationSuffix"],
                                f"{s.get('admin_location','?')} ({s.get('admin_locationSuffix','?')})")
        S("--- Version ---")
        R("Version",           ["version_major","version_minor","version_branch"],
                                f"{s.get('version_major','?')}.{s.get('version_minor','?')}  ({s.get('version_branch','?')})")
        S("--- Project team ---")
        R("Admin email",       ["technical_admins_email"],    s.get("technical_admins_email","?"))
        R("Admin OID",         ["technical_admins_ad_object_id"], s.get("technical_admins_ad_object_id","?"))
        S("--- AI Factory features ---")
        R("CMK",               ["cmk"],                       s.get("cmk","?"))
        R("CMK Disable Search",["cmkDisableForAISearch"],     s.get("cmkDisableForAISearch","?"))
        R("CMK Disable Foundry",["cmkDisableForFoundry"],     s.get("cmkDisableForFoundry","?"))
        R("Use Common ACR",    ["useCommonACR"],              s.get("useCommonACR","?"))
        S("--- SKUs ---")
        R("AI Search Tier",    ["admin_aiSearchTier"],        s.get("admin_aiSearchTier","?"))
        R("GPT-5.4o-mini",      ["deployModel_gpt_54_mini"],   s.get("deployModel_gpt_54_mini","?"))
        R("GPT-4o",            ["deployModel_gpt_4o"],        s.get("deployModel_gpt_4o","?"))
        S("--- Build agent / runner ---")
        R("Use self-hosted",    ["useSelfHostedBuildAgent"],   s.get("useSelfHostedBuildAgent","?"))
        R("GitHub runner label",["selfHostedRunnerLabel"],     s.get("selfHostedRunnerLabel","?"))
        R("ADO agent pool",     ["adminVMBuildAgentPool"],     s.get("adminVMBuildAgentPool","?"))
        R("ADO agent name",     ["adminVMBuildAgentName"],     s.get("adminVMBuildAgentName","") or "(generated name)")
        S("--- Security / Cost ---")
        R("Diag Level",        ["diagnosticSettingLevel"],    s.get("diagnosticSettingLevel","?"))
        R("ACR SKU",           ["acr_SKU"],                   s.get("acr_SKU","?"))
        S("--- Project & Core ---")
        R("Project #",         ["project_number_000"],        s.get("project_number_000","?"))
        R("runNetworkingVar",  ["runNetworkingVar"],          s.get("runNetworkingVar","?"))
        S("--- GenAI / ML ---")
        R("enableAIFoundry",   ["enableAIFoundry"],           s.get("enableAIFoundry","?"))
        R("addAIFoundry",      ["addAIFoundry"],              s.get("addAIFoundry","?"))
        R("enableCaphost",     ["enableAFoundryCaphost"],     s.get("enableAFoundryCaphost","?"))
        R("cleanCaphost",      ["cleanFoundryCaphost"],       s.get("cleanFoundryCaphost","?"))
        R("FoundryType",       ["foundryDeploymentType"],     s.get("foundryDeploymentType","?"))
        R("enableAML",         ["enableAzureMachineLearning"],s.get("enableAzureMachineLearning","?"))
        R("enableAKS",         ["enableAksForAzureML"],       s.get("enableAksForAzureML","?"))
        R("AKS outbound",      ["aksOutboundType"],           s.get("aksOutboundType","?"))
        S("--- Cognitive / DB ---")
        R("enableAISearch",    ["enableAISearch"],            s.get("enableAISearch","?"))
        R("enableOpenAI",      ["enableAzureOpenAI"],         s.get("enableAzureOpenAI","?"))
        R("enableCosmosDB",    ["enableCosmosDB","cosmosKind"],
                                f"{s.get('enableCosmosDB','?')}  ({s.get('cosmosKind','?')})")
        R("enablePostgreSQL",  ["enablePostgreSQL"],          s.get("enablePostgreSQL","?"))
        S("--- App & Integration ---")
        R("enableFunction",    ["enableFunction","functionRuntime","functionVersion"],
                                f"{s.get('enableFunction','?')}  ({s.get('functionRuntime','?')} {s.get('functionVersion','?')})")
        R("enableWebApp",      ["enableWebApp","webAppRuntime","webAppRuntimeVersion"],
                                f"{s.get('enableWebApp','?')}  ({s.get('webAppRuntime','?')} {s.get('webAppRuntimeVersion','?')})")
        R("enableContainerApp",["enableContainerApps"],       s.get("enableContainerApps","?"))
        R("enableLogicApps",   ["enableLogicApps"],           s.get("enableLogicApps","?"))
        R("enableBotService",  ["enableBotService"],          s.get("enableBotService","?"))
        S("=" * 62)

        self._text.configure(state="disabled")

        # ── Tab 2: full file preview ──────────────────────────────────────
        self._render_full_file()

    def _ins_tmpl_defaults(self):
        """Append template variables not editable in the wizard, in dark gray."""
        managed_yaml_keys: set = {dp.split(".")[-1] for dp in YAML_MAP.values()}

        try:
            with open(_find_template_yaml(), "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return

        self._text.insert(tk.END,
            "\n--- Remaining template defaults (read-only in wizard) ---\n",
            "dim_hdr")

        for line in lines:
            stripped = line.strip()
            # blank lines
            if not stripped:
                continue
            # comment-only or section header lines
            if stripped.startswith("#"):
                # show top-level section headers (=== blocks) as dim headers
                if stripped.startswith("# ===") or stripped.startswith("## ==="):
                    self._text.insert(tk.END, line.rstrip() + "\n", "dim_hdr")
                # skip detail comment lines to keep this section compact
                continue
            # key: value lines
            yaml_key = stripped.split(":")[0].strip()
            if yaml_key not in managed_yaml_keys:
                # extract just key: value, strip inline comment for brevity
                kv = stripped.split("#")[0].rstrip()
                self._text.insert(tk.END, f"  {kv}\n", "dark_gray")

    def _render_full_file(self):
        """Render Tab 2 – complete variables.yaml or .env with colour-coding."""
        s = self.state
        t = self._text2
        t.configure(state="normal")
        t.delete("1.0", tk.END)

        orch = s.get("orchestrator", "ado")

        # Build the set of yaml key-names managed by the wizard
        managed_yaml_keys: dict = {}   # yaml_key -> state_key  (1:1)
        for sk, dp in YAML_MAP.items():
            managed_yaml_keys[dp.split(".")[-1]] = sk

        if orch == "gha":
            self._render_full_env(s, t, managed_yaml_keys)
        else:
            self._render_full_yaml_file(s, t, managed_yaml_keys)

        t.configure(state="disabled")

    # ── colour helpers for tab 2 ──────────────────────────────────────────
    def _managed_tag(self, state_key: str) -> str:
        """Return the appropriate tag for a wizard-managed key."""
        if PageSummary._is_invalid([state_key], self.state):
            return "managed_err"
        val = str(self.state.get(state_key, ""))
        default = str(DEFAULT_STATE.get(state_key, ""))
        return "managed_ok" if val == default else "managed_ch"

    def _render_full_yaml_file(self, s, t, managed_yaml_keys):
        # 1. Load template
        try:
            with open(_find_template_yaml(), "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as exc:
            t.insert(tk.END, f"# Could not load template: {exc}\n", "managed_err")
            return

        # 2. Apply state
        lines_applied = list(lines)
        for sk, dp in YAML_MAP.items():
            if sk in s:
                lines_applied = _yaml_set(lines_applied, dp, s[sk])
        for flag, val in NETWORK_MODE_FLAGS[s.get("network_mode","public")].items():
            lines_applied = _yaml_set(lines_applied, f"variables.{flag}", val)

        # 3. § A – configured variables (wizard-managed only, in YAML order)
        t.insert(tk.END,
            "# ═══════════════════════════════════════════════════════════\n"
            "# § A  Wizard-configured variables\n"
            "#      ● magenta = changed from default   ● green = at default\n"
            "# ═══════════════════════════════════════════════════════════\n",
            "sec_hdr")

        shown: set = set()
        for line in lines_applied:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            yaml_key = stripped.split(":")[0].strip()
            if yaml_key in managed_yaml_keys and yaml_key not in shown:
                shown.add(yaml_key)
                sk = managed_yaml_keys[yaml_key]
                t.insert(tk.END, line, self._managed_tag(sk))

        # 4. § B – full file in original order (wizard lines highlighted, rest dim)
        t.insert(tk.END,
            "\n"
            "# ═══════════════════════════════════════════════════════════\n"
            "# § B  Complete variables.yaml  (with state applied)\n"
            "#      ● dim grey = template-only (not touched by wizard)\n"
            "# ═══════════════════════════════════════════════════════════\n",
            "sec_hdr")

        for line in lines_applied:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                t.insert(tk.END, line, "dim")
                continue
            yaml_key = stripped.split(":")[0].strip()
            if yaml_key in managed_yaml_keys:
                sk = managed_yaml_keys[yaml_key]
                t.insert(tk.END, line, self._managed_tag(sk))
            else:
                t.insert(tk.END, line, "tmpl")

    def _render_full_env(self, s, t, managed_yaml_keys):
        # managed ENV keys
        managed_env: dict = {}   # ENV_KEY -> state_key
        for sk, env_key in ENV_MAP.items():
            managed_env[env_key] = sk

        # Load template .env
        rel_env = os.path.join("template-files", ".env")
        candidates = [
            _res(rel_env),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_env),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel_env),
        ]
        lines_applied = []
        for p in candidates:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    lines_applied = f.readlines()
                break
        for sk, env_key in ENV_MAP.items():
            if sk in s:
                lines_applied = _env_set(lines_applied, env_key, s[sk])

        # § A
        t.insert(tk.END,
            "# ═══════════════════════════════════════════════════════════\n"
            "# § A  Wizard-configured .env variables\n"
            "# ═══════════════════════════════════════════════════════════\n",
            "sec_hdr")
        shown: set = set()
        for line in lines_applied:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            env_key = stripped.split("=")[0].strip()
            if env_key in managed_env and env_key not in shown:
                shown.add(env_key)
                sk = managed_env[env_key]
                t.insert(tk.END, line, self._managed_tag(sk))

        # § B
        t.insert(tk.END,
            "\n"
            "# ═══════════════════════════════════════════════════════════\n"
            "# § B  Complete .env  (with state applied)\n"
            "# ═══════════════════════════════════════════════════════════\n",
            "sec_hdr")
        for line in lines_applied:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                t.insert(tk.END, line, "dim")
                continue
            env_key = stripped.split("=")[0].strip()
            if env_key in managed_env:
                sk = managed_env[env_key]
                t.insert(tk.END, line, self._managed_tag(sk))
            else:
                t.insert(tk.END, line, "tmpl")


# ---------------------------------------------------------------------------
# YAML / .env save helpers
# ---------------------------------------------------------------------------
def _yaml_set(lines, dotpath, value):
    key = dotpath.split(".")[-1]
    pattern = re.compile(r"^(\s*)" + re.escape(key) + r"\s*:(.*)$")
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            indent = m.group(1); v = str(value)
            # preserve any trailing inline comment (YAML: whitespace + #)
            comment = ""
            cm = re.search(r"(\s+#.*)$", m.group(2).rstrip("\n"))
            if cm:
                comment = cm.group(1)
            # JSON string syntax is also valid YAML and safely escapes embedded quotes.
            v_str = json.dumps(v, ensure_ascii=False)
            lines[i] = f"{indent}{key}: {v_str}{comment}\n"
            return lines
    return lines

def _env_set(lines, key, value):
    v = str(value).replace('"','\\"')
    for i, line in enumerate(lines):
        if re.match(r"^"+re.escape(key)+r"\s*=", line):
            # preserve any trailing inline comment (.env: whitespace + #)
            comment = ""
            cm = re.search(r"(\s+#.*)$", line.rstrip("\n"))
            if cm:
                comment = cm.group(1)
            lines[i] = f'{key}="{v}"{comment}\n'
            return lines
    lines.append(f'{key}="{v}"\n'); return lines

def _render_azure_devops(state):
    state = hub_configuration(state)
    require_hub_configuration(state)
    require_scaling_configuration(state)
    template = _find_template_yaml()
    with open(template,"r",encoding="utf-8") as f: lines=f.readlines()
    for state_key, dotpath in YAML_MAP.items():
        if state_key in state and not state_key.startswith("_"):
            lines=_yaml_set(lines,dotpath,state[state_key])
    for flag, val in NETWORK_MODE_FLAGS[state.get("network_mode","public")].items():
        lines=_yaml_set(lines,f"variables.{flag}",val)
    lines = _yaml_set(lines, YAML_MAP[SCALING_MODE_KEY],
                      state.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE))
    # Older templates may predate these settings; keep them inside variables.
    for key in (SCALING_MODE_KEY, *HUB_FLAG_KEYS):
        if not any(re.match(r"^\s+" + re.escape(key) + r"\s*:", line) for line in lines):
            for index, line in enumerate(lines):
                if re.match(r"^variables:\s*(?:#.*)?$", line.rstrip("\n")):
                    lines.insert(index + 1, f"  {key}: " + json.dumps(
                        state.get(key, DEFAULT_STATE[key])) + "\n")
                    break
    return lines

def _render_github_actions(state):
    state = hub_configuration(state)
    require_hub_configuration(state)
    require_scaling_configuration(state)
    rel_env = os.path.join("template-files",".env")
    candidates = [_res(rel_env),
                  os.path.join(os.path.dirname(os.path.abspath(__file__)),rel_env),
                  os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),rel_env)]
    template = next((p for p in candidates if os.path.isfile(p)),candidates[0])
    try:
        with open(template,"r",encoding="utf-8") as f: lines=f.readlines()
    except FileNotFoundError: lines=[]
    for state_key, env_key in ENV_MAP.items():
        if env_key and state_key in state and not state_key.startswith("_"):
            lines=_env_set(lines,env_key,state[state_key])
    lines = _env_set(lines, "SCALING_MODE", state.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE))
    return lines

def _render_variables_json(state):
    variables = yaml.safe_load("".join(_render_azure_devops(state))).get("variables", {})
    for key in HUB_FLAG_KEYS:
        variables[key] = _bool_str(variables[key])
    document = {"dev": variables, "stage_prod": copy.deepcopy(variables)}
    if state.get("orchestrator") == "gha":
        for state_key in _GITHUB_REPOSITORY_STATE_KEYS:
            for section in ("dev", "stage_prod"):
                document[section][ENV_MAP[state_key]] = state.get(state_key, DEFAULT_STATE[state_key])
        document["_wizard"] = {"orchestrator": "gha"}
    return document

def _save_variables_json(state, folder, filename="variables.json"):
    document = _render_variables_json(state)
    dest_path = os.path.join(folder, filename)
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return dest_path

def save_azure_devops(state, dest_path):
    lines = _render_azure_devops(state)
    with open(dest_path,"w",encoding="utf-8") as f: f.writelines(lines)
    json_folder = state.get("_save_folder", "").strip() or os.path.dirname(os.path.abspath(dest_path))
    _save_variables_json(state, json_folder)

def save_github_actions(state, dest_path):
    lines = _render_github_actions(state)
    with open(dest_path,"w",encoding="utf-8") as f: f.writelines(lines)
    json_folder = state.get("_save_folder", "").strip() or os.path.dirname(os.path.abspath(dest_path))
    _save_variables_json(state, json_folder)


# ---------------------------------------------------------------------------
# File import helpers  (reverse of save_azure_devops / save_github_actions)
# ---------------------------------------------------------------------------

def _import_yaml_to_state(path: str, state: dict) -> int:
    """Parse a variables.yaml and write matching key values into *state*.

    A line like ``  admin_location: swedencentral`` is matched by the leaf key
    (last segment of the YAML_MAP dotpath).  Returns the count of fields loaded.
    """
    # reverse: leaf-key → state_key,  e.g. "admin_location" → "admin_location"
    reverse = {v.split(".")[-1]: k for k, v in YAML_MAP.items()}
    pat = re.compile(r"^\s+([\w-]+)\s*:\s*(.*)$")
    loaded = 0
    imported_scaling_mode = DEFAULT_SCALING_MODE
    imported_flags = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = pat.match(line)
                if not m:
                    continue
                yaml_key = m.group(1)
                raw_val  = m.group(2).strip()
                if yaml_key == "_hub_topology":
                    imported_flags["_hub_topology"] = yaml.safe_load(raw_val)
                state_key = reverse.get(yaml_key)
                if state_key:
                    if state_key == DASHBOARD_KEY:
                        # Portal dashboard routes live in the URL fragment, not a YAML comment.
                        raw_val = yaml.safe_load(raw_val)
                        raw_val = raw_val if isinstance(raw_val, str) else ""
                    else:
                        raw_val = raw_val.split("#")[0].strip()
                        if len(raw_val) >= 2 and raw_val[0] in ('"', "'") and raw_val[-1] == raw_val[0]:
                            raw_val = raw_val[1:-1]
                    state[state_key] = raw_val
                    imported_flags[state_key] = raw_val
                    if state_key == SCALING_MODE_KEY:
                        imported_scaling_mode = raw_val
                    loaded += 1
    except Exception:
        pass
    state["orchestrator"] = "ado"
    if loaded:
        state[SCALING_MODE_KEY] = imported_scaling_mode
        _restore_hub_flags(state, imported_flags)
    # Derive network_mode from the individual networking flag values
    aP  = state.get("allowPublicAccessWhenBehindVnet", "").lower()
    eP  = state.get("enablePublicGenAIAccess", "").lower()
    ePP = state.get("enablePublicAccessWithPerimeter", "").lower()
    if aP and eP and ePP:  # only override if all three flags were loaded
        if aP == "false" and eP == "false":
            state["network_mode"] = "private"
        elif aP == "true" and eP == "true" and ePP == "false":
            state["network_mode"] = "hybrid"
        elif aP == "true" and eP == "true" and ePP == "true":
            state["network_mode"] = "public"
    return loaded


def _restore_network_mode(state: dict, supplied: dict) -> None:
    """Derive a mode only from a complete, exact set of imported flags."""
    for mode, flags in NETWORK_MODE_FLAGS.items():
        if all(key in supplied and str(supplied[key]).lower() == expected
               for key, expected in flags.items()):
            state["network_mode"] = mode
            return


def _json_orchestrator(document: dict) -> str | None:
    """Recognize explicit routing or populated repository identity, not template defaults."""
    metadata = document.get("_wizard", {})
    route = metadata.get("orchestrator") if isinstance(metadata, dict) else None
    if route in ("ado", "gha"):
        return route
    for section in ("dev", "variables", "stage_prod"):
        values = document.get(section, {})
        if not isinstance(values, dict):
            continue
        for key in ("GITHUB_USERNAME", "GITHUB_NEW_REPO"):
            value = values.get(key)
            if isinstance(value, str) and value.strip() and "<todo>" not in value.lower():
                return "gha"
    return None


def _import_json_to_state(path: str, state: dict) -> int:
    """Import a factory snapshot or mapped ``dev``/legacy ``variables`` values.

    The wizard has one editable state, so JSON import loads the pipeline's Dev
    configuration, falling back to ``stage_prod`` for Stage/Prod-only documents.
    Explicit wizard routing or populated
    GitHub repository identity overrides the caller's route; otherwise it is kept.
    """
    reverse = {v.split(".")[-1]: k for k, v in YAML_MAP.items()}
    reverse.update({ENV_MAP[key]: key for key in _GITHUB_REPOSITORY_STATE_KEYS})
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            document = json.load(f)
    except (OSError, ValueError):
        return 0
    if os.path.basename(path) == "factory_state.json":
        if not isinstance(document, dict) or document.get("orchestrator") not in ("ado", "gha"):
            return 0
        restored = copy.deepcopy(DEFAULT_STATE)
        restored.update({key: value for key, value in hub_configuration(document).items() if key in restored})
        restored["_save_folder"] = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        if DASHBOARD_KEY not in document:
            restored[DASHBOARD_KEY] = _current_dashboard_url(restored["_save_folder"])
        restored["_also_update_git"] = False
        state.clear()
        state.update(restored)
        return len(restored)
    variables = (document.get("dev", document.get("variables", document.get("stage_prod")))
                 if isinstance(document, dict) else None)
    if not isinstance(variables, dict):
        return 0
    route = _json_orchestrator(document)
    if route:
        state["orchestrator"] = route
    loaded = 0
    imported_flags = {}
    metadata = document.get("_wizard", {})
    imported_flags["_hub_topology"] = variables.get(
        "_hub_topology", document.get("_hub_topology",
        metadata.get("_hub_topology", "") if isinstance(metadata, dict) else ""))
    for json_key, value in variables.items():
        state_key = reverse.get(json_key)
        if not state_key:
            continue
        if isinstance(value, bool):
            state[state_key] = str(value).lower()
        elif value is None:
            state[state_key] = ""
        elif isinstance(value, (dict, list)):
            state[state_key] = json.dumps(value, separators=(",", ":"))
        else:
            state[state_key] = str(value)
        imported_flags[state_key] = state[state_key]
        loaded += 1
    _restore_network_mode(state, imported_flags)
    if loaded:
        state[SCALING_MODE_KEY] = imported_flags.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE)
        _restore_hub_flags(state, imported_flags)
    return loaded


def _clean_env_value(raw: str) -> str:
    """Strip inline comments and surrounding quotes from a raw .env value.

    Handles the common patterns found in aifactory .env files:
      "value"            → value
      "value" # comment  → value
      value # comment    → value
      'value'            → value
    """
    raw = raw.strip()
    if not raw:
        return raw

    # If the value starts with a quote, find its matching closing quote and
    # discard everything after it (including inline comments).
    if raw[0] in ('"', "'"):
        q = raw[0]
        end = raw.find(q, 1)          # first closing quote
        if end != -1:
            return raw[1:end]         # content between the quotes
        # Unmatched opening quote — fall through to comment-strip path
        raw = raw[1:]

    # No quotes: strip a trailing comment (space + # …)
    # Only split on ' #' so a bare '#' inside a value is preserved.
    idx = raw.find(" #")
    if idx != -1:
        raw = raw[:idx]
    return raw.strip()


def _import_env_to_state(path: str, state: dict) -> int:
    """Parse a .env file and write matching key values into *state*.

    Handles lines like:
      KEY="value"
      KEY="value" # comment
      KEY=value # comment
      export KEY=value
    Returns the count of fields loaded.
    """
    # reverse: ENV_KEY → state_key,  e.g. "AIFACTORY_LOCATION" → "admin_location"
    reverse = {v: k for k, v in ENV_MAP.items()}
    pat = re.compile(r"^(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$")
    loaded = 0
    imported_flags = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                # skip blank lines and pure comment lines
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                m = pat.match(line)
                if not m:
                    continue
                env_key = m.group(1)
                raw_val = _clean_env_value(m.group(2))
                if env_key == "_HUB_TOPOLOGY":
                    imported_flags["_hub_topology"] = raw_val
                state_key = reverse.get(env_key)
                if state_key:
                    state[state_key] = raw_val
                    imported_flags[state_key] = raw_val
                    loaded += 1
    except Exception:
        pass
    state["orchestrator"] = "gha"
    _restore_network_mode(state, imported_flags)
    if loaded:
        state[SCALING_MODE_KEY] = imported_flags.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE)
        _restore_hub_flags(state, imported_flags)
    return loaded


def _contains_todo_value(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_todo_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_todo_value(item) for item in value)
    return isinstance(value, str) and "<todo>" in value.lower()


def _startup_import_candidate(base_folder: str, state: dict):
    """Return (path, orchestrator) for an aifactory startup folder."""
    base_folder = base_folder.strip()
    if not base_folder:
        return None, None

    factory_path = os.path.join(base_folder, "config-wizard", "factory_state.json")
    if os.path.isfile(factory_path):
        try:
            with open(factory_path, "r", encoding="utf-8") as source:
                factory_state = json.load(source)
            route = factory_state.get("orchestrator", "ado") if isinstance(factory_state, dict) else "ado"
        except (OSError, ValueError):
            route = "ado"
        return factory_path, route

    parent_folder = os.path.dirname(base_folder.rstrip("/\\"))
    env_candidates = (os.path.join(parent_folder, ".env"), os.path.join(base_folder, ".env"))
    env_path = next((path for path in env_candidates if os.path.isfile(path)), env_candidates[0])
    orchestrator = "gha" if os.path.isfile(env_path) else "ado"

    json_path = os.path.join(base_folder, "variables.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8-sig") as import_file:
                variables = json.load(import_file)
            if isinstance(variables, dict) and not _contains_todo_value(variables):
                return json_path, _json_orchestrator(variables) or orchestrator
        except (OSError, ValueError):
            pass

    if orchestrator == "gha":
        return env_path, orchestrator

    yaml_path = os.path.join(
        base_folder, "esml-infra", "azure-devops", "bicep", "yaml",
        "variables", "variables.yaml")
    return (yaml_path if os.path.isfile(yaml_path) else None), orchestrator


def _current_dashboard_url(base_folder: str) -> str:
    """Read only this factory's current dashboard, never a historical snapshot."""
    def read_json(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as source:
                value = json.load(source)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def text(value):
        return value.strip() if isinstance(value, str) else ""

    full = read_json(os.path.join(base_folder, "config-wizard", "factory_state.json"))
    if DASHBOARD_KEY in full:
        return text(full[DASHBOARD_KEY])
    variables_path = os.path.join(base_folder, "variables.json")
    if os.path.isfile(variables_path):
        variables = read_json(variables_path)
        for section in ("dev", "stage_prod"):
            values = variables.get(section)
            if isinstance(values, dict) and text(values.get(DASHBOARD_KEY)):
                return text(values[DASHBOARD_KEY])
        return ""

    parent = os.path.dirname(base_folder.rstrip("/\\"))
    for candidate in (os.path.join(parent, ".env"), os.path.join(base_folder, ".env")):
        if os.path.isfile(candidate):
            values = {}
            _import_env_to_state(candidate, values)
            return text(values.get(DASHBOARD_KEY))
    values = {}
    _import_yaml_to_state(os.path.join(
        base_folder, "esml-infra", "azure-devops", "bicep", "yaml",
        "variables", "variables.yaml"), values)
    return text(values.get(DASHBOARD_KEY))


def _load_project_state(path: str, base_folder: str = "") -> dict:
    """Restore a snapshot, then overlay current variables for the same project."""
    with open(path, "r", encoding="utf-8") as source:
        saved = json.load(source)
    if not isinstance(saved, dict):
        raise ValueError("Project snapshot must contain an object")
    if not base_folder:
        config_folder = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        base_folder = (os.path.dirname(config_folder)
                       if os.path.basename(config_folder) == "config-wizard"
                       else saved.get("_save_folder", ""))

    state = copy.deepcopy(DEFAULT_STATE)
    state.update(_load_template_defaults())
    state.update(hub_configuration(saved))
    source_path, route = _startup_import_candidate(base_folder, state)
    if source_path:
        current = {}
        extension = os.path.splitext(source_path)[1].lower()
        if extension in (".yaml", ".yml"):
            _import_yaml_to_state(source_path, current)
        elif extension == ".json":
            _import_json_to_state(source_path, current)
        else:
            _import_env_to_state(source_path, current)
        # A factory may currently deploy a different project than the one opened
        # from history. Never replace that project's settings with another's.
        project = str(saved.get("project_number_000", "")).strip()
        current_project = str(current.get("project_number_000", "")).strip()
        if project and current_project and project.zfill(3) == current_project.zfill(3):
            state.update(current)
        # The route belongs to the selected factory folder, not an old snapshot.
        state["orchestrator"] = route
        state[DASHBOARD_KEY] = _current_dashboard_url(base_folder)
    state["_save_folder"] = base_folder
    _restore_network_mode(state, state)
    return state


# ---------------------------------------------------------------------------
# Project snapshot helpers  (saved-projects/ folder next to template-files/)
# ---------------------------------------------------------------------------
import json as _json, glob as _glob

# ---------------------------------------------------------------------------
# App settings  (persists _save_folder across sessions)
# ---------------------------------------------------------------------------
_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".aifactory_wizard.json")

def _load_app_settings() -> dict:
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_app_settings(data: dict) -> None:
    try:
        existing = _load_app_settings()
        existing.update(data)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            _json.dump(existing, f, indent=2)
    except Exception:
        pass


def _record_recent_project(folder: str, project: str, orchestrator: str,
                           prefix_rg: str, suffix_rg: str) -> None:
    if not folder or orchestrator not in ("ado", "gha"):
        return
    project = str(project).strip() or "000"
    normalized_folder = os.path.normcase(os.path.normpath(folder))
    recent = _load_app_settings().get("recent_projects", [])
    recent = [item for item in recent if not (
        os.path.normcase(os.path.normpath(item.get("folder", ""))) == normalized_folder
        and str(item.get("project", "")) == project
    )]
    recent.insert(0, {
        "folder": folder,
        "project": project,
        "orchestrator": orchestrator,
        "prefix_rg": str(prefix_rg).strip(),
        "suffix_rg": str(suffix_rg).strip(),
    })
    _save_app_settings({"recent_projects": recent[:12]})


def _recent_project_label(project: str, prefix_rg: str, suffix_rg: str) -> str:
    prefix = str(prefix_rg).strip().rstrip("-")
    project = str(project).strip() or "000"
    scale_set = str(suffix_rg).strip().lstrip("-")
    if prefix and scale_set:
        return f"Project {project} ({prefix}-{scale_set})"
    if scale_set:
        return f"Project {project} ({scale_set})"
    return f"Project {project}"


def _snapshot_dir(*, create: bool = True) -> str:
    """Return the saved-projects directory, creating it unless disabled."""
    candidates = [
        _res("saved-projects"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saved-projects"),
        os.path.join(os.getcwd(), "saved-projects"),
    ]
    for c in candidates:
        if os.path.isdir(c): return c
    d = candidates[1]
    if not create:
        return d
    try: os.makedirs(d, exist_ok=True); return d
    except Exception: pass
    os.makedirs(candidates[2], exist_ok=True); return candidates[2]

def _list_project_snapshots(base_folder: str = "", *, create_legacy_dir: bool = True) -> dict:
    """Returns {project_number: filepath}.
    Scans {base_folder}/config-wizard/project-{NNN}/project_state.json first,
    then falls back to saved-projects/project_{NNN}.json."""
    result = {}
    # New-style: <base_folder>/config-wizard/project-NNN/project_state.json
    wiz_dir = os.path.join(base_folder, "config-wizard") if base_folder else ""
    if wiz_dir and os.path.isdir(wiz_dir):
        try:
            for entry in os.scandir(wiz_dir):
                if entry.is_dir():
                    m = re.match(r"^project-(\d+)$", entry.name)
                    if m:
                        snap = os.path.join(entry.path, "project_state.json")
                        if os.path.isfile(snap):
                            result[m.group(1)] = snap
        except OSError:
            pass
    if base_folder and os.path.isfile(os.path.join(base_folder, "config-wizard", "factory_state.json")):
        return result
    # Legacy: saved-projects/project_{NNN}.json
    d = _snapshot_dir() if create_legacy_dir else _snapshot_dir(create=False)
    for f in _glob.glob(os.path.join(d, "project_*.json")):
        m = re.match(r".*[/\\]project_(\d+)\.json$", f)
        if m and m.group(1) not in result:
            result[m.group(1)] = f
    return result

def _save_project_snapshot(state) -> str:
    """Persist current state as project_state.json.
    Location: {_save_folder}/config-wizard/project-{NNN}/ if configured,
    otherwise saved-projects/project_{NNN}.json (legacy)."""
    state = hub_configuration(state)
    require_hub_configuration(state)
    require_scaling_configuration(state)
    proj = state.get("project_number_000", "000")
    base_folder = state.get("_save_folder", "").strip()
    if base_folder:
        proj_dir = os.path.join(base_folder, "config-wizard", f"project-{proj}")
        os.makedirs(proj_dir, exist_ok=True)
        path = os.path.join(proj_dir, "project_state.json")
    else:
        path = os.path.join(_snapshot_dir(), f"project_{proj}.json")
    # Include _save_folder and _also_update_git so they round-trip through load
    snap = {k: v for k, v in state.items() if not k.startswith("_")}
    snap["_save_folder"] = base_folder
    snap["_also_update_git"] = state.get("_also_update_git", False)
    snap["_hub_topology"] = state.get("_hub_topology", "")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(snap, f, indent=2, ensure_ascii=False)
    return path


class ConfigDeleteError(ValueError):
    """A refused or failed local snapshot deletion, safe to display to callers."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


ProjectConfigDeleteError = ConfigDeleteError


def _delete_saved_snapshot(base_folder: str, snapshot_id: str, path: str, *,
                           list_snapshots, local_parts, kind: str,
                           identity_matches, identity_error: str) -> str:
    """Unlink only the listed saved snapshot; never load/export state or call Azure."""
    def absolute_path(value, field):
        if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
            raise ConfigDeleteError(f"{field} must be an absolute, ordinary path")
        parts = value.replace("\\", "/").split("/")
        candidate = Path(value)
        if (not candidate.is_absolute() or ".." in parts
                or value.startswith(("\\\\?\\", "\\\\.\\"))
                or any(":" in part or part != part.rstrip(" .")
                       for part in candidate.parts[1:])):
            raise ConfigDeleteError(f"{field} must be an absolute path without traversal or special components")
        return os.path.abspath(value)

    def normalized(value):
        return os.path.normcase(os.path.normpath(value))

    def checked_path(value, *, directory=False):
        candidate = Path(value)
        identities = []
        for component in (*reversed(candidate.parents), candidate):
            info = os.lstat(component)
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ConfigDeleteError("Snapshot deletion does not allow symbolic links or reparse points")
            is_directory = component != candidate or directory
            if not (stat.S_ISDIR(info.st_mode) if is_directory else stat.S_ISREG(info.st_mode)):
                raise ConfigDeleteError("The factory must be a directory and the snapshot an ordinary file")
            identities.append((info.st_dev, info.st_ino, info.st_mode))
        return identities, info

    folder = absolute_path(base_folder, "aifactory_folder")
    target = absolute_path(path, "path")
    label = kind.capitalize()
    try:
        folder_identities, _ = checked_path(folder, directory=True)
        # Check the exact requested file before resolving legacy fallback, so a
        # repeated request cannot delete a second snapshot of the same identity.
        identities, initial = checked_path(target)

        def check_listing():
            current = list_snapshots(folder, create_legacy_dir=False).get(snapshot_id)
            if not current:
                raise ConfigDeleteError(f"{label} snapshot not found; refresh the {kind} list", 404)
            if normalized(os.path.abspath(current)) != normalized(target):
                raise ConfigDeleteError(f"{label} snapshot path changed or does not match; refresh the {kind} list", 409)

        check_listing()
        with open(target, "r", encoding="utf-8") as source:
            if not os.path.samestat(initial, os.fstat(source.fileno())):
                raise ConfigDeleteError(f"{label} snapshot changed; refresh the {kind} list", 409)
            try:
                saved = _json.load(source)
            except (ValueError, UnicodeError):
                raise ConfigDeleteError(f"{label} snapshot must contain valid JSON") from None
        if not isinstance(saved, dict):
            raise ConfigDeleteError(f"{label} snapshot must contain a JSON object")
        if not identity_matches(saved):
            raise ConfigDeleteError(identity_error, 409)

        local_path = os.path.join(folder, *local_parts)
        if normalized(target) != normalized(local_path) and saved.get("_save_folder"):
            try:
                saved_folder = absolute_path(saved["_save_folder"], "Saved snapshot folder")
            except ConfigDeleteError:
                raise ConfigDeleteError("Legacy snapshot belongs to a different or invalid factory folder", 409) from None
            if normalized(saved_folder) != normalized(folder):
                raise ConfigDeleteError("Legacy snapshot belongs to a different factory folder", 409)

        check_listing()
        final_folder_identities, _ = checked_path(folder, directory=True)
        final_identities, final = checked_path(target)
        if (folder_identities != final_folder_identities or identities != final_identities
                or initial.st_size != final.st_size
                or initial.st_mtime_ns != final.st_mtime_ns):
            raise ConfigDeleteError(f"{label} snapshot changed; refresh the {kind} list", 409)
        os.unlink(target)
    except (FileNotFoundError, NotADirectoryError):
        raise ConfigDeleteError(f"{label} snapshot or factory folder not found; refresh the {kind} list", 404) from None
    except PermissionError:
        raise ConfigDeleteError(f"Permission denied while accessing or deleting the saved {kind} snapshot") from None
    except OSError:
        raise ConfigDeleteError(f"Unable to delete the saved {kind} snapshot because of a filesystem error", 500) from None
    return target


def _delete_project_snapshot(base_folder: str, project_number: str, path: str) -> str:
    if not isinstance(project_number, str) or not re.fullmatch(r"\d+", project_number):
        raise ProjectConfigDeleteError("project_number must contain only digits")

    def identity_matches(saved):
        number = str(saved.get("project_number_000", "")).strip()
        return re.fullmatch(r"\d+", number) and number.zfill(3) == project_number.zfill(3)

    return _delete_saved_snapshot(
        base_folder, project_number, path, list_snapshots=_list_project_snapshots,
        local_parts=("config-wizard", f"project-{project_number}", "project_state.json"),
        kind="project", identity_matches=identity_matches,
        identity_error="Saved snapshot project number does not match the selected project",
    )


# ---------------------------------------------------------------------------
# Scale-set snapshot helpers
# ---------------------------------------------------------------------------

# Keys captured from the wizard state when saving a scale-set snapshot
# (everything visible on Page 2 "Scale set & Vnets" plus orchestrator context).
SCALESET_KEYS = [
    SCALING_MODE_KEY,
    DASHBOARD_KEY,
    "orchestrator",
    "_hub_topology",
    *HUB_FLAG_KEYS,
    "admin_aifactorySuffixRG", "admin_aifactoryPrefixRG",
    "projectPrefix", "projectSuffix",
    "dev_sub_id", "test_sub_id", "prod_sub_id",
    "tenantId",
    "dev_cidr_range", "test_cidr_range", "prod_cidr_range",
    "common_vnet_cidr", "common_subnet_cidr", "common_subnet_scoring_cidr",
    "common_pbi_subnet_name", "common_pbi_subnet_cidr",
    "common_bastion_subnet_name", "common_bastion_subnet_cidr",
    "admin_location", "admin_locationSuffix",
    "dev_service_connection", "test_service_connection", "prod_service_connection",
    "dev_seeding_kv_service_connection", "test_seeding_kv_service_connection",
    "prod_seeding_kv_service_connection",
    "_save_folder",
]

def _scaleset_id_from_suffix(suffix: str) -> str:
    """Normalise admin_aifactorySuffixRG (e.g. '-001') to a safe file/display ID '001'."""
    return suffix.strip().lstrip("-").strip() or "000"

def _list_scalesets(base_folder: str = "", *, create_legacy_dir: bool = True) -> dict:
    """Returns {scaleset_id: filepath}.
    Scans {base_folder}/config-wizard/scalesets/ first,
    then saved-projects/scaleset_*.json as legacy fallback."""
    result = {}
    if base_folder:
        ss_dir = os.path.join(base_folder, "config-wizard", "scalesets")
        if os.path.isdir(ss_dir):
            try:
                for f in _glob.glob(os.path.join(ss_dir, "scaleset_*.json")):
                    m = re.match(r".*[/\\]scaleset_(.+)\.json$", f)
                    if m:
                        result[m.group(1)] = f
            except OSError:
                pass
    if base_folder and os.path.isfile(os.path.join(base_folder, "config-wizard", "factory_state.json")):
        return result
    # Legacy fallback: saved-projects/scaleset_{ID}.json
    d = _snapshot_dir() if create_legacy_dir else _snapshot_dir(create=False)
    for f in _glob.glob(os.path.join(d, "scaleset_*.json")):
        m = re.match(r".*[/\\]scaleset_(.+)\.json$", f)
        if m and m.group(1) not in result:
            result[m.group(1)] = f
    return result


def _delete_scaleset_snapshot(base_folder: str, scale_set_id: str, path: str) -> str:
    if (not isinstance(scale_set_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", scale_set_id)
            or ".." in scale_set_id or scale_set_id.endswith(".")):
        raise ConfigDeleteError("scale_set_id must be an exact safe scale-set listing ID")

    def identity_matches(saved):
        suffix = saved.get("admin_aifactorySuffixRG")
        return (isinstance(suffix, str) and bool(suffix.strip())
                and _scaleset_id_from_suffix(suffix) == scale_set_id)

    return _delete_saved_snapshot(
        base_folder, scale_set_id, path, list_snapshots=_list_scalesets,
        local_parts=("config-wizard", "scalesets", f"scaleset_{scale_set_id}.json"),
        kind="scale set", identity_matches=identity_matches,
        identity_error="Saved snapshot scale-set identity does not match the selected scale set",
    )


def _save_scaleset_snapshot(state: dict, *, create_only: bool = False,
                            base_folder: str | None = None, extra_keys=()) -> str:
    """Persist page-2 fields as a scale-set config file.
    Location: {_save_folder}/config-wizard/scalesets/scaleset_{ID}.json
    or saved-projects/scaleset_{ID}.json (legacy).
    create_only refuses replacement; base_folder permits transactional staging
    without changing the persisted state's final folder."""
    state = hub_configuration(state)
    require_hub_configuration(state)
    require_scaling_configuration(state)
    suffix = state.get("admin_aifactorySuffixRG", "-000")
    ss_id = _scaleset_id_from_suffix(suffix)
    base_folder = state.get("_save_folder", "").strip() if base_folder is None else base_folder
    if base_folder:
        ss_dir = os.path.join(base_folder, "config-wizard", "scalesets")
        os.makedirs(ss_dir, exist_ok=True)
        path = os.path.join(ss_dir, f"scaleset_{ss_id}.json")
    else:
        path = os.path.join(_snapshot_dir(), f"scaleset_{ss_id}.json")
    snap = {k: state[k] for k in (*SCALESET_KEYS, *extra_keys) if k in state}
    target = open(path, "x" if create_only else "w", encoding="utf-8")
    try:
        with target as f:
            _json.dump(snap, f, indent=2, ensure_ascii=False)
    except (OSError, TypeError, ValueError):
        if create_only:
            os.remove(path)
        raise
    return path


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class WizardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AIFactory Config Wizard  v046")
        self.geometry("1260x1110")
        self.minsize(1050, 800)
        self.resizable(True, True)
        self.configure(bg="#e8e8e8")

        # Window icon
        try:
            icon_candidates = [
                _res(os.path.join("images","aifactory-house.png")),
                os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","images","aifactory-house.png"),
            ]
            for ic in icon_candidates:
                ic = os.path.normpath(ic)
                if os.path.isfile(ic):
                    img = tk.PhotoImage(file=ic)
                    self.iconphoto(True, img)
                    break
        except Exception:
            pass

        # ── Theme (off / light / dark) ─────────────────────────────────
        self._style = ttk.Style(self)
        # Remember the native ttk theme so "off" can fully restore it.
        try:
            self._default_ttk_theme = self._style.theme_use()
        except Exception:
            self._default_ttk_theme = "default"
        if sys.platform == "darwin":
            self._default_ttk_theme = "clam"   # aqua ignores bg= colours
        self._themed_once = False
        _app_settings = _load_app_settings()
        # Default OFF (original experience); remember the user's choice afterwards.
        self._theme_mode = _app_settings.get("theme", "off")
        if self._theme_mode not in ("off", "light", "dark"):
            self._theme_mode = "off"
        self._apply_theme(walk=False)   # set ttk styling before widgets are built

        # State
        self.state = new_configuration_defaults()
        self.state["aifactory_salt"] = ""  # never pre-populate salt
        # Restore last-used save folder from per-user settings
        if _app_settings.get("_save_folder") and not self.state.get("_save_folder","").strip():
            self.state["_save_folder"] = _app_settings["_save_folder"]

        self._cur = 0
        self._advanced = False  # default: simple mode
        self._api_host = None

        # ── Layout ────────────────────────────────────────────────────────
        left = tk.Frame(self, bg="#2d2d2d", width=200)
        left.pack(side="left", fill="y"); left.pack_propagate(False)

        # ── Global search bar ─────────────────────────────────────────
        _sf = tk.Frame(left, bg="#1e1e1e")
        _sf.pack(fill="x", padx=0, pady=0)
        tk.Label(_sf, text="🔍  Search", bg="#1e1e1e", fg="#888888",
                 font=("Segoe UI", 8)).pack(side="left", padx=(6,2), pady=4)
        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(
            _sf, textvariable=self._search_var,
            bg="#333333", fg="#cccccc", insertbackground="#cccccc",
            relief="flat", font=("Segoe UI", 9), bd=0)
        self._search_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self._search_results = tk.Frame(left, bg="#1a1a1a")
        self._search_var.trace_add("write", lambda *_: self._do_search())
        # ── END search bar ──────────────────────────────────────────

        self._quick_setup_btn = tk.Button(
            left, text="Quick setup  ▸",
            bg="#2d2d2d", fg="#cccccc",
            activebackground="#3a3a3a", activeforeground="white",
            relief="flat", bd=0, font=("Segoe UI", 9, "bold"),
            anchor="w", padx=10, pady=6, cursor="hand2",
            command=self._show_quick_setup_menu,
        )
        self._quick_setup_btn.pack(fill="x")
        self._quick_setup_menu = tk.Menu(self, tearoff=False)
        self._quick_setup_menu.add_command(
            label='Set startup "aifactory" folder',
            command=self._shortcut_browse_folder,
        )
        self._quick_setup_menu.add_command(
            label="Import variable file (.yaml | .env | .json)",
            command=self._shortcut_browse_import,
        )
        self._quick_export_menu = tk.Menu(self._quick_setup_menu, tearoff=False)
        self._quick_export_menu.add_command(
            label="YAML (.yaml)",
            command=lambda: self._shortcut_export("yaml"),
        )
        self._quick_export_menu.add_command(
            label="Environment (.env)",
            command=lambda: self._shortcut_export("env"),
        )
        self._quick_export_menu.add_command(
            label="JSON (.json)",
            command=lambda: self._shortcut_export("json"),
        )
        self._quick_setup_menu.add_cascade(
            label="Export variable file",
            menu=self._quick_export_menu,
        )
        self._quick_setup_menu.add_separator()
        self._api_host_menu_index = self._quick_setup_menu.index("end") + 1
        self._quick_setup_menu.add_command(
            label="Start API host",
            command=self._start_api_host,
        )
        self._recent_projects_menu = tk.Menu(self._quick_setup_menu, tearoff=False)
        self._quick_setup_menu.add_cascade(
            label="Recent projects",
            menu=self._recent_projects_menu,
        )
        self._refresh_recent_projects_menu()

        right = tk.Frame(self, bg="#f5f5f5")
        right.pack(side="left", fill="both", expand=True)

        # ── Step labels (hierarchical nav) ─────────────────────────
        self._step_lbls = []   # one entry per page index
        self._proj_core_expanded = True

        # Page 0: Intro
        l = tk.Label(left, text="0  Intro", bg="#2d2d2d", fg="#aaaaaa",
                     font=("Segoe UI",9), anchor="w", padx=10, pady=4)
        l.pack(fill="x")
        self._step_lbls.append(l)   # index 0

        # Pages 1–7: flat top-level labels
        for txt in [
            "1  Orchestrator",
            "2  Scale set & Vnets",
            "3  Version",
            "4  Adv. Networking",
            "5  AI Factory Extras",
            "6  SKUs",
            "7  Security/Cost",
        ]:
            l = tk.Label(left, text=txt, bg="#2d2d2d", fg="#aaaaaa",
                         font=("Segoe UI",9), anchor="w", padx=10, pady=4)
            l.pack(fill="x")
            self._step_lbls.append(l)

        # Page 8: "Project & Core" — collapsible parent button
        self._proj_core_btn = tk.Button(
            left, text="\u25be  9  Project & Core",
            bg="#2d2d2d", fg="#aaaaaa",
            activebackground="#3a3a3a", activeforeground="#cccccc",
            relief="flat", bd=0, font=("Segoe UI",9,"bold"),
            anchor="w", padx=10, pady=4, cursor="hand2",
            command=self._toggle_proj_core,
        )
        self._proj_core_btn.pack(fill="x")
        self._step_lbls.append(self._proj_core_btn)   # index 8

        # Pages 9–13: sub-items inside a collapsible frame (starts expanded)
        self._proj_core_frame = tk.Frame(left, bg="#252525")
        self._proj_core_frame.pack(fill="x")
        for txt in [
            "   \u251c Project team",
            "   \u251c GenAI & ML",
            "   \u251c Cognitive & DB",
            "   \u251c App & Integration",
            "   \u2514 Other",
        ]:
            l = tk.Label(self._proj_core_frame, text=txt, bg="#252525", fg="#aaaaaa",
                         font=("Segoe UI",8), anchor="w", padx=12, pady=3)
            l.pack(fill="x")
            self._step_lbls.append(l)   # indices 9..13

        # Page 14: Summary
        l = tk.Label(left, text="10  Summary", bg="#2d2d2d", fg="#aaaaaa",
                     font=("Segoe UI",9), anchor="w", padx=10, pady=4)
        l.pack(fill="x")
        self._step_lbls.append(l)   # index 14

        # ── Make every nav entry directly clickable ────────────────────
        for _i, _w in enumerate(self._step_lbls):
            _base_bg = "#252525" if 9 <= _i <= 13 else "#2d2d2d"
            if isinstance(_w, tk.Button):
                # Project & Core parent button: click navigates to its page
                _w.config(command=lambda _idx=_i: self._show(_idx))
            else:
                _w.config(cursor="hand2")
                _w.bind("<Button-1>", lambda e, _idx=_i: self._show(_idx))
                _w.bind("<Enter>",    lambda e, w=_w, bb=_base_bg:
                    w.config(bg="#3a3a3a") if w.cget("bg") not in ("#0078d4","#1a5276") else None)
                _w.bind("<Leave>",    lambda e, w=_w, bb=_base_bg:
                    w.config(bg=bb) if w.cget("bg") == "#3a3a3a" else None)

        # ── spacer pushes sections to bottom ──────────────────────────
        tk.Frame(left, bg="#2d2d2d").pack(fill="both", expand=True)

        # ── Scale sets section ─────────────────────────────────────────
        tk.Frame(left, bg="#555555", height=1).pack(fill="x", pady=(0,2))

        self._ss_expanded = False
        self._filter_scaleset_id = None   # None = show all projects
        self._ss_hdr_btn = tk.Button(
            left,
            text="▸  Scale sets",
            bg="#2d2d2d", fg="#888888",
            activebackground="#3a3a3a", activeforeground="#aaaaaa",
            relief="flat", bd=0,
            font=("Segoe UI", 9),
            anchor="w", padx=10, pady=4,
            cursor="hand2",
            command=self._toggle_scalesets
        )
        self._ss_hdr_btn.pack(fill="x")
        self._ss_list_frame = tk.Frame(left, bg="#252525")
        # not packed until expanded

        # ── Created Projects section ───────────────────────────────────
        tk.Frame(left, bg="#555555", height=1).pack(fill="x", pady=(0,2))

        self._proj_expanded = False
        self._proj_hdr_btn = tk.Button(
            left,
            text="▸  Projects",
            bg="#2d2d2d", fg="#888888",
            activebackground="#3a3a3a", activeforeground="#aaaaaa",
            relief="flat", bd=0,
            font=("Segoe UI", 9),
            anchor="w", padx=10, pady=4,
            cursor="hand2",
            command=self._toggle_projects
        )
        self._proj_hdr_btn.pack(fill="x")
        self._proj_list_frame = tk.Frame(left, bg="#252525")
        # not packed until expanded

        # ── Dashboards section ─────────────────────────────────────────
        tk.Frame(left, bg="#555555", height=1).pack(fill="x", pady=(0,2))

        self._dash_expanded = False
        self._dash_hdr_btn = tk.Button(
            left,
            text="▸  Dashboards",
            bg="#2d2d2d", fg="#888888",
            activebackground="#3a3a3a", activeforeground="#aaaaaa",
            relief="flat", bd=0,
            font=("Segoe UI", 9),
            anchor="w", padx=10, pady=4,
            cursor="hand2",
            command=self._toggle_dashboards
        )
        self._dash_hdr_btn.pack(fill="x")
        self._dash_list_frame = tk.Frame(left, bg="#252525")
        self._build_dashboards_list()
        # not packed until expanded

        # ── Advanced/Simple toggle ─────────────────────────────────────
        tk.Frame(left, bg="#555555", height=1).pack(fill="x", pady=(4,4))

        self._adv_btn = tk.Button(
            left,
            text="☰  Advanced Mode",
            bg="#3a3a3a", fg="#cccccc",
            activebackground="#555555", activeforeground="white",
            relief="flat", bd=0,
            font=("Segoe UI", 9),
            anchor="w", padx=10, pady=6,
            cursor="hand2",
            command=self._toggle_advanced
        )
        self._adv_btn.pack(fill="x", padx=4, pady=(0,8))

        # ── Status bar (very bottom of right panel) ───────────────────
        status = tk.Frame(right, bg="#eaeaea", height=24)
        status.pack(side="bottom", fill="x"); status.pack_propagate(False)
        tk.Frame(status, bg="#cccccc", height=1).pack(side="top", fill="x")
        self._status_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self._status_var, bg="#eaeaea",
                 fg="#555555", font=("Segoe UI", 8), anchor="w").pack(
            side="left", fill="x", padx=10)
        self._api_status_var = tk.StringVar(
            value="No API Host running. Go to Quicksetup to START it"
        )
        self._api_status_label = tk.Label(
            status, textvariable=self._api_status_var, bg="#eaeaea",
            fg="#a4262c", font=("Segoe UI", 8, "bold"), anchor="e"
        )
        self._api_status_label.pack(side="right", padx=10)
        self._status_bar = status

        # ── Nav bar (bottom of right panel) ───────────────────────────
        nav = tk.Frame(right, bg="#dcdcdc", height=48)
        nav.pack(side="bottom", fill="x"); nav.pack_propagate(False)
        self._back_btn = ttk.Button(nav, text="Back", command=self._back)
        self._back_btn.pack(side="left", padx=8, pady=8)
        self._next_btn = ttk.Button(nav, text="Next", command=self._next)
        self._next_btn.pack(side="left", padx=4, pady=8)
        # Theme selector: off (original) / light / dark
        self._theme_box = tk.Frame(nav, bg="#dcdcdc")
        self._theme_box.pack(side="left", padx=(24, 4), pady=8)
        tk.Label(self._theme_box, text="Theme", bg="#dcdcdc", fg="#444444",
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self._theme_var = tk.StringVar(value=self._theme_mode)
        self._theme_combo = ttk.Combobox(
            self._theme_box, textvariable=self._theme_var,
            values=["off", "light", "dark"], state="readonly", width=6)
        self._theme_combo.pack(side="left")
        self._theme_combo.bind("<<ComboboxSelected>>", self._on_theme_select)
        self._save_btn = ttk.Button(nav, text="SAVE (.yaml)", command=self._save)
        self._save_btn.pack(side="right", padx=12, pady=8)
        self._save_state_btn = ttk.Button(nav, text="Save State", command=self._save_state)
        self._save_state_btn.pack(side="right", padx=4, pady=8)
        self._new_proj_btn = ttk.Button(nav, text="New Project", command=self._new_project)
        self._new_proj_btn.pack(side="right", padx=4, pady=8)

        # ── Page container ────────────────────────────────────────────
        page_container = tk.Frame(right, bg="#f5f5f5")
        page_container.pack(side="top", fill="both", expand=True)

        self.pages = [
            PageIntro(page_container, self.state),                   # 0
            PageOrchestratorNetwork(page_container, self.state,
                                     on_import=self._on_import_done),  # 1
            PageScaleSet(page_container, self.state,
                         on_scaleset_saved=self._on_scaleset_saved),  # 2
            PageVersion(page_container, self.state),                 # 3
            PageAdvancedNetworking(page_container, self.state),      # 4
            PageSeedingKV(page_container, self.state),               # 5
            PageSKU(page_container, self.state),                     # 6
            PageSecurityCost(page_container, self.state),            # 7
            PageProjectCore(page_container, self.state),             # 8
            PagePrefix(page_container, self.state),                  # 9  (sub-item)
            PageGenAIML(page_container, self.state),                 # 10
            PageCognitiveDatabases(page_container, self.state),      # 11
            PageIntegrationCompute(page_container, self.state),      # 12
            PageOther(page_container, self.state),                   # 13
            PageSummary(page_container, self.state),                  # 14
        ]
        for p in self.pages:
            p.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Apply initial simple-mode state (hide advanced widgets on all pages)
        for p in self.pages:
            p.set_advanced_mode(False)

        self._show(0)
        self.after(100, self._build_search_index)  # after pages rendered
        _attach_tooltips_from_registry()            # hover help on every field
        self.after(300, self._hydrate_from_startup_folder)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_shortcuts()
        if self._theme_mode != "off":
            self._retheme_all()   # recolour built tk widgets for light/dark
        # Dirty tracking: snapshot the state once startup (incl. the after(300)
        # silent project restore) has settled, so closing without any user edit
        # does NOT prompt to save.
        self._baseline_sig = None
        self.after(900, self._mark_clean)
        # Status bar + per-page badges
        self._last_save_str = ""
        self.after(150, self._refresh_nav_badges)
        self.after(1000, self._tick_status)

    # ── Theme (off / light / dark) ──────────────────────────────────────
    def _apply_manual_light_styles(self):
        """The original (pre-theme) ttk styling — used for the 'off' mode."""
        s = self._style
        _BG, _FG, _FBG = "#f5f5f5", "#1a1a1a", "#ffffff"
        s.configure("TFrame",            background=_BG)
        s.configure("TLabel",            background=_BG, foreground=_FG)
        s.configure("TLabelframe",       background=_BG, foreground=_FG)
        s.configure("TLabelframe.Label", background=_BG, foreground=_FG)
        s.configure("TCheckbutton",      background=_BG, foreground=_FG)
        s.configure("TRadiobutton",      background=_BG, foreground=_FG)
        s.configure("TEntry",            fieldbackground=_FBG, foreground=_FG)
        s.configure("TCombobox",         fieldbackground=_FBG, foreground=_FG)
        s.configure("TSeparator",        background="#cccccc")
        s.configure("TButton",           background="#e0e0e0", foreground=_FG)
        s.map("TCheckbutton", background=[("active", _BG)])
        s.map("TRadiobutton", background=[("active", _BG)])
        s.configure("Error.TEntry",           fieldbackground="#ffe0e0")
        s.configure("Highlight.TCheckbutton",  background="#e3f2fd")
        s.configure("Highlight.TEntry",        fieldbackground="#deeeff")
        s.configure("Highlight.TCombobox",     fieldbackground="#deeeff")
        s.configure("Vertical.TScrollbar",   arrowsize=14, width=14)
        s.configure("Horizontal.TScrollbar", arrowsize=14, width=14)

    def _apply_theme(self, walk: bool = True):
        """Apply the active theme.
          off   -> native ttk + original light styling, no recolour (fast).
          light -> sv-ttk light  (or manual fallback) + custom styles.
          dark  -> sv-ttk dark   + recolour of raw tk widgets.
        """
        mode  = self._theme_mode
        style = self._style

        if mode == "off":
            try:
                style.theme_use(self._default_ttk_theme)
            except tk.TclError:
                pass
            self._apply_manual_light_styles()
            # Only restore widgets if a non-off theme was previously applied.
            if walk and self._themed_once:
                _retheme_tree(self, False)
                try:
                    self.configure(bg="#e8e8e8")
                except Exception:
                    pass
            return

        dark = (mode == "dark")
        self._themed_once = True
        if _sv_ttk is not None:
            try:
                _sv_ttk.set_theme("dark" if dark else "light")
            except Exception:
                pass
        else:
            # Manual fallback (keeps the app usable without sv-ttk installed).
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            _bg  = "#1e1e1e" if dark else "#f5f5f5"
            _fg  = "#e8e8e8" if dark else "#1a1a1a"
            _fbg = "#252526" if dark else "#ffffff"
            style.configure("TFrame",            background=_bg)
            style.configure("TLabel",            background=_bg, foreground=_fg)
            style.configure("TLabelframe",       background=_bg, foreground=_fg)
            style.configure("TLabelframe.Label", background=_bg, foreground=_fg)
            style.configure("TCheckbutton",      background=_bg, foreground=_fg)
            style.configure("TRadiobutton",      background=_bg, foreground=_fg)
            style.configure("TEntry",            fieldbackground=_fbg, foreground=_fg)
            style.configure("TCombobox",         fieldbackground=_fbg, foreground=_fg)
            style.configure("TSeparator",        background="#3c3c3c" if dark else "#cccccc")
            style.configure("TButton",           background="#37373a" if dark else "#e0e0e0",
                            foreground=_fg)
            style.map("TCheckbutton", background=[("active", _bg)])
            style.map("TRadiobutton", background=[("active", _bg)])
        _apply_theme_styles(style, dark)
        if walk:
            self._retheme_all()

    def _retheme_all(self):
        # In 'off' mode (and never themed) there is nothing to recolour — skip
        # the tree walk entirely so the original experience stays fast.
        if self._theme_mode == "off" and not self._themed_once:
            return
        dark = (self._theme_mode == "dark")
        _retheme_tree(self, dark)
        try:
            self.configure(bg=("#1e1e1e" if dark else "#e8e8e8"))
        except Exception:
            pass

    def _on_theme_select(self, _evt=None):
        mode = self._theme_var.get()
        if mode not in ("off", "light", "dark"):
            mode = "off"
        self._theme_mode = mode
        _save_app_settings({"theme": mode})
        self._apply_theme(walk=True)

    # ── Toggle ──────────────────────────────────────────────────────────
    # ── Created-Projects panel ─────────────────────────────────────────
    # ── Dashboards panel ────────────────────────────────────────────────
    _DASH_ITEMS = [
        ("\U0001f4b0  Cost Chart",  "cost"),
        ("\U0001f6aa  AI GW",        "aigw"),
        ("\U0001f916  Agents",       "agents"),
        ("\U0001f9e9  MCPs",         "mcps"),
        ("\U0001f6e1  Admin",        "admin"),
    ]

    def _toggle_dashboards(self):
        self._dash_expanded = not self._dash_expanded
        if self._dash_expanded:
            self._dash_hdr_btn.config(text="\u25be  Dashboards", fg="#aaaaaa")
            self._dash_list_frame.pack(fill="x", after=self._dash_hdr_btn)
        else:
            self._dash_hdr_btn.config(text="\u25b8  Dashboards", fg="#888888")
            self._dash_list_frame.pack_forget()

    def _build_dashboards_list(self):
        for label, key in self._DASH_ITEMS:
            def _click(k=key):
                self._open_dashboard(k)
            btn = tk.Button(
                self._dash_list_frame,
                text=f"  {label}",
                bg="#252525", fg="#ce9178",
                activebackground="#333333", activeforeground="white",
                relief="flat", bd=0,
                font=("Segoe UI", 9),
                anchor="w", padx=8, pady=3,
                cursor="hand2",
                command=_click
            )
            btn.pack(fill="x")

    def _open_dashboard(self, key: str):
        sub = self.state.get("dev_sub_id", "")
        suffix = self.state.get("admin_aifactorySuffixRG", "-001").lstrip("-")
        prefix = self.state.get("admin_aifactoryPrefixRG", "").rstrip("-")
        loc = self.state.get("admin_locationSuffix", "")
        env = "dev"
        base = "https://portal.azure.com"
        sub_scope = f"%2Fsubscriptions%2F{sub}" if sub else ""
        rg_common = f"{prefix}-esml-common-{loc}-{env}-{suffix}" if (prefix and loc and suffix) else ""
        urls = {
            "cost":   (f"{base}/#view/Microsoft_Azure_CostManagement/Menu/~/costanalysis/scope/{sub_scope}"
                       if sub else f"{base}/#view/Microsoft_Azure_CostManagement/Menu/~/costanalysis"),
            "aigw":   f"{base}/#browse/Microsoft.ApiManagement%2Fservice",
            "agents": "https://ai.azure.com/",
            "mcps":   "https://github.com/modelcontextprotocol",
            "admin":  (f"{base}/#resource/subscriptions/{sub}/resourceGroups/{rg_common}/overview"
                       if rg_common else f"{base}/#home"),
        }
        url = urls.get(key, base)
        try:
            webbrowser.open(url)
        except Exception as exc:
            messagebox.showerror("Browser Error", str(exc))

    def _toggle_proj_core(self):
        self._proj_core_expanded = not self._proj_core_expanded
        if self._proj_core_expanded:
            self._proj_core_btn.config(text="\u25be  9  Project & Core")
            self._proj_core_frame.pack(fill="x", after=self._proj_core_btn)
        else:
            self._proj_core_btn.config(text="\u25b8  9  Project & Core")
            self._proj_core_frame.pack_forget()

    def _toggle_projects(self):
        self._proj_expanded = not self._proj_expanded
        if self._proj_expanded:
            self._proj_hdr_btn.config(text="\u25be  Projects", fg="#aaaaaa")
            self._proj_list_frame.pack(fill="x", after=self._proj_hdr_btn)
            self._refresh_projects_list()
        else:
            self._proj_hdr_btn.config(text="\u25b8  Projects", fg="#888888")
            self._proj_list_frame.pack_forget()

    # ── Scale sets panel ────────────────────────────────────────────────
    def _toggle_scalesets(self):
        self._ss_expanded = not self._ss_expanded
        if self._ss_expanded:
            self._ss_hdr_btn.config(text="\u25be  Scale sets", fg="#aaaaaa")
            self._ss_list_frame.pack(fill="x", after=self._ss_hdr_btn)
            self._refresh_scalesets_list()
        else:
            self._ss_hdr_btn.config(text="\u25b8  Scale sets", fg="#888888")
            self._ss_list_frame.pack_forget()

    def _refresh_scalesets_list(self):
        for w in self._ss_list_frame.winfo_children():
            w.destroy()
        base_folder = self.state.get("_save_folder", "").strip()
        scalesets = _list_scalesets(base_folder)
        if not scalesets:
            tk.Label(self._ss_list_frame, text="  (no saved scale sets)",
                     bg="#252525", fg="#666666",
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=4, pady=2)
            return
        # "Show all projects" link when a filter is active
        if self._filter_scaleset_id:
            def _clear_filter():
                self._filter_scaleset_id = None
                self._refresh_scalesets_list()
                if self._proj_expanded:
                    self._refresh_projects_list()
            tk.Button(
                self._ss_list_frame,
                text="  \u2715  Show all projects",
                bg="#252525", fg="#888888",
                activebackground="#333333", activeforeground="white",
                relief="flat", bd=0,
                font=("Segoe UI", 8, "italic"),
                anchor="w", padx=8, pady=2,
                cursor="hand2",
                command=_clear_filter,
            ).pack(fill="x")
        for ss_id, path in sorted(scalesets.items()):
            is_active = (ss_id == self._filter_scaleset_id)
            def _load(p=path, sid=ss_id):
                self._load_scaleset_from_menu(p, sid)
            fg_col = "#ffffff" if is_active else "#c586c0"
            bg_col = "#4a2060" if is_active else "#252525"
            tk.Button(
                self._ss_list_frame,
                text=f"  \u25cf  Scale set {ss_id}",
                bg=bg_col, fg=fg_col,
                activebackground="#333333", activeforeground="white",
                relief="flat", bd=0,
                font=("Segoe UI", 9),
                anchor="w", padx=8, pady=3,
                cursor="hand2",
                command=_load,
            ).pack(fill="x")

    def _load_scaleset_from_menu(self, path: str, ss_id: str):
        """Load scaleset into state, set project filter, refresh Projects list."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            data = hub_configuration(data)
            data.setdefault(SCALING_MODE_KEY, DEFAULT_SCALING_MODE)
            self.state.update(data)
            _sync_vars_from_state(self.state)
            for p in self.pages:
                p.set_advanced_mode(self._advanced)
                try:
                    p.on_enter()
                except Exception:
                    pass
            # Filter Projects list to this scale set and refresh it
            self._filter_scaleset_id = ss_id
            self._refresh_scalesets_list()
            if self._proj_expanded:
                self._refresh_projects_list()
            self._retheme_all()
            self._mark_clean()
            # Navigate to page 2 so user can see the loaded values
            self._show(2)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _on_scaleset_saved(self):
        """Called by PageScaleSet when a scale set is saved; refreshes left menu."""
        if self._ss_expanded:
            self._refresh_scalesets_list()

    def _on_import_done(self):
        """Called after a variables.yaml / .env import.
        Finds the matching saved scale set (by admin_aifactorySuffixRG),
        sets _filter_scaleset_id, and refreshes both panels."""
        suffix = self.state.get("admin_aifactorySuffixRG", "").strip()
        base_folder = self.state.get("_save_folder", "").strip()
        scalesets = _list_scalesets(base_folder)
        # Update filter regardless of whether a file exists
        ss_id = _scaleset_id_from_suffix(suffix) if suffix else None
        self._filter_scaleset_id = ss_id if ss_id in scalesets else None
        if self._ss_expanded:
            self._refresh_scalesets_list()
        if self._proj_expanded:
            self._refresh_projects_list()
        _record_recent_project(
            base_folder,
            self.state.get("project_number_000", "000"),
            self.state.get("orchestrator", "ado"),
            self.state.get("admin_aifactoryPrefixRG", ""),
            self.state.get("admin_aifactorySuffixRG", ""),
        )
        self._refresh_recent_projects_menu()

    def _refresh_projects_list(self):
        for w in self._proj_list_frame.winfo_children():
            w.destroy()
        base_folder = self.state.get("_save_folder", "").strip()
        if not base_folder:
            tk.Label(self._proj_list_frame,
                     text="  Set File Saving Location\n  on the Orchestrator page first",
                     bg="#252525", fg="#888888",
                     font=("Segoe UI", 8), anchor="w", justify="left").pack(fill="x", padx=4, pady=2)
            return
        snaps = _list_project_snapshots(base_folder)
        if not snaps:
            tk.Label(self._proj_list_frame, text="  (no saved projects)",
                     bg="#252525", fg="#666666",
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=4)
            return

        # Filter by active scale set if one is selected
        if self._filter_scaleset_id:
            filtered = {}
            for pnum, ppath in snaps.items():
                try:
                    with open(ppath, "r", encoding="utf-8") as _f:
                        _pdata = _json.load(_f)
                    _suf = _scaleset_id_from_suffix(_pdata.get("admin_aifactorySuffixRG", ""))
                    if _suf == self._filter_scaleset_id:
                        filtered[pnum] = ppath
                except Exception:
                    filtered[pnum] = ppath  # include if snapshot unreadable
            snaps = filtered
            # Show which scale set is active as a header hint
            tk.Label(self._proj_list_frame,
                     text=f"  [Scale set {self._filter_scaleset_id}]",
                     bg="#252525", fg="#c586c0",
                     font=("Segoe UI", 7, "italic"), anchor="w").pack(fill="x", padx=4)
            if not snaps:
                tk.Label(self._proj_list_frame, text="  (no projects for this scale set)",
                         bg="#252525", fg="#666666",
                         font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=4)
                return

        for proj_num, path in sorted(snaps.items()):
            # Read scale-set prefix+suffix from the snapshot for the label
            ss_label = ""
            try:
                with open(path, "r", encoding="utf-8") as _f:
                    _snap = _json.load(_f)
                _suf = _snap.get("admin_aifactorySuffixRG", "")
                _pfx = _snap.get("admin_aifactoryPrefixRG", "").rstrip("-")
                _sid = _scaleset_id_from_suffix(_suf)
                if _pfx and _sid:
                    ss_label = f" ({_pfx}-{_sid})"
                elif _sid:
                    ss_label = f" ({_sid})"
            except Exception:
                pass
            def _load(p=path, n=proj_num):
                self._load_project_snapshot(p, n)
            btn = tk.Button(
                self._proj_list_frame,
                text=f"  \u25cf  Project {proj_num}{ss_label}",
                bg="#252525", fg="#9cdcfe",
                activebackground="#333333", activeforeground="white",
                relief="flat", bd=0,
                font=("Segoe UI", 9),
                anchor="w", padx=8, pady=3,
                cursor="hand2",
                command=_load
            )
            btn.pack(fill="x")

    def _load_project_snapshot(self, path: str, proj_num: str, *, notify: bool = True):
        try:
            data = _load_project_state(path)
            self.state.clear()
            self.state.update(data)
            # Push all state values into every registered tk widget var
            _sync_vars_from_state(self.state)
            # Call on_enter() on ALL pages so page-level vars (radios, combos)
            # also re-sync.  set_advanced_mode calls are harmless duplicates.
            for p in self.pages:
                p.set_advanced_mode(self._advanced)
                try:
                    p.on_enter()
                except Exception:
                    pass
            # Refresh project list with potentially-updated base folder
            if self._proj_expanded:
                self._refresh_projects_list()
            self._retheme_all()
            self._mark_clean()
            if notify:
                messagebox.showinfo("Project Loaded",
                                    f"Loaded settings for project {proj_num}.")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _toggle_advanced(self):
        self._advanced = not self._advanced
        if self._advanced:
            self._adv_btn.config(
                text="✦  Advanced Mode  (ON)",
                bg="#0078d4", fg="white",
                activebackground="#005fa3"
            )
        else:
            self._adv_btn.config(
                text="☰  Advanced Mode",
                bg="#3a3a3a", fg="#cccccc",
                activebackground="#555555"
            )
        for p in self.pages:
            p.set_advanced_mode(self._advanced)
        # Re-trigger on_enter so any mode-dependent logic refreshes
        self.pages[self._cur].on_enter()
        self._retheme_all()

    # ── Navigation ──────────────────────────────────────────────────────
    def _show_quick_setup_menu(self):
        self._refresh_recent_projects_menu()
        self._quick_setup_menu.post(
            self._quick_setup_btn.winfo_rootx() + self._quick_setup_btn.winfo_width(),
            self._quick_setup_btn.winfo_rooty(),
        )

    def _shortcut_browse_folder(self):
        self._show(1)
        self.pages[1]._browse_folder()

    def _shortcut_browse_import(self):
        self._show(1)
        self.pages[1]._browse_import()

    def _start_api_host(self):
        self._set_api_status("starting")
        self.update_idletasks()
        try:
            from src.api import ApiHost

            if not os.environ.get("AIFACTORY_API_KEY"):
                api_key = simpledialog.askstring(
                    "API Host Authentication",
                    "Enter the API key clients must send in the X-API-Key header:",
                    show="*",
                    parent=self,
                )
                if not api_key:
                    self._set_api_status("stopped")
                    return
                os.environ["AIFACTORY_API_KEY"] = api_key
            if self._api_host is None:
                self._api_host = ApiHost()
            if not self._api_host.start():
                self._set_api_status("running")
                messagebox.showinfo(
                    "API Host", "The API host is already running at http://127.0.0.1:8765"
                )
                return
            self.after(100, self._monitor_api_host_start)
        except RuntimeError as exc:
            self._set_api_status("stopped")
            messagebox.showerror("API Host", str(exc))
        except OSError as exc:
            self._set_api_status("stopped")
            messagebox.showerror(
                "API Host", f"Could not start http://127.0.0.1:8765\n\n{exc}"
            )
        except Exception as exc:
            self._set_api_status("stopped")
            messagebox.showerror("API Host", f"Could not start the API host.\n\n{exc}")

    def _monitor_api_host_start(self):
        status = self._api_host.status if self._api_host is not None else "stopped"
        self._set_api_status(status)
        if status == "starting":
            self.after(100, self._monitor_api_host_start)
            return
        if status == "running":
            self._quick_setup_menu.entryconfig(
                self._api_host_menu_index,
                label="API host running on 127.0.0.1:8765",
                state="disabled",
            )
            messagebox.showinfo(
                "API Host Started",
                "API host: http://127.0.0.1:8765\n"
                "Swagger UI: http://127.0.0.1:8765/docs",
            )
            return
        error = self._api_host.error if self._api_host is not None else None
        messagebox.showerror("API Host", f"The API host stopped during startup.\n\n{error or ''}")

    def _shortcut_export(self, file_format):
        options = {
            "yaml": {
                "title": "Export variables.yaml",
                "extension": ".yaml",
                "filetypes": [("YAML files", "*.yaml"), ("All files", "*.*")],
                "initialfile": "variables.yaml",
            },
            "env": {
                "title": "Export .env",
                "extension": "",
                "filetypes": [("env files", "*.env"), ("All files", "*.*")],
                "initialfile": ".env",
            },
            "json": {
                "title": "Export variables.json",
                "extension": ".json",
                "filetypes": [("JSON files", "*.json"), ("All files", "*.*")],
                "initialfile": "variables.json",
            },
        }
        selected = options[file_format]
        initialdir = self.state.get("_save_folder", "").strip() or os.path.expanduser("~")
        dest = filedialog.asksaveasfilename(
            title=selected["title"],
            defaultextension=selected["extension"],
            filetypes=selected["filetypes"],
            initialfile=selected["initialfile"],
            initialdir=initialdir,
        )
        if not dest:
            return
        try:
            if file_format == "yaml":
                with open(dest, "w", encoding="utf-8") as export_file:
                    export_file.writelines(_render_azure_devops(self.state))
            elif file_format == "env":
                with open(dest, "w", encoding="utf-8") as export_file:
                    export_file.writelines(_render_github_actions(self.state))
            else:
                _save_variables_json(
                    self.state, os.path.dirname(os.path.abspath(dest)), os.path.basename(dest))
            messagebox.showinfo("Exported", f"Variable file exported to:\n{dest}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _refresh_recent_projects_menu(self):
        self._recent_projects_menu.delete(0, "end")
        recent = _load_app_settings().get("recent_projects", [])
        for orchestrator, label in (("ado", "ADO"), ("gha", "GHA")):
            route_menu = tk.Menu(self._recent_projects_menu, tearoff=False)
            route_entries = [item for item in recent
                             if item.get("orchestrator") == orchestrator]
            if route_entries:
                for item in route_entries:
                    project = str(item.get("project", "000"))
                    folder = item.get("folder", "")
                    prefix_rg = item.get("prefix_rg", "")
                    suffix_rg = item.get("suffix_rg", "")
                    route_menu.add_command(
                        label=_recent_project_label(project, prefix_rg, suffix_rg),
                        command=lambda f=folder, p=project, o=orchestrator:
                            self._open_recent_project(f, p, o),
                    )
            else:
                route_menu.add_command(label="(none)", state="disabled")
            self._recent_projects_menu.add_cascade(label=label, menu=route_menu)

    def _open_recent_project(self, folder, project, orchestrator):
        snapshot = _list_project_snapshots(folder).get(project)
        if snapshot:
            self._load_project_snapshot(snapshot, project, notify=False)
            self._show(1)
            return
        self.state["project_number_000"] = project
        self.state["orchestrator"] = orchestrator
        orchestrator_page = self.pages[1]
        orchestrator_page._folder_var.set(folder)
        orchestrator_page._import_from_startup_folder(folder)
        self._show(1)

    def _show(self, idx):
        # Auto-expand Project & Core sub-section when navigating to a sub-page
        if 9 <= idx <= 13 and not self._proj_core_expanded:
            self._proj_core_expanded = True
            self._proj_core_btn.config(text="\u25be  9  Project & Core")
            self._proj_core_frame.pack(fill="x", after=self._proj_core_btn)
        self._cur = idx
        self.pages[idx].tkraise()
        self.pages[idx].on_enter()
        for i, lbl in enumerate(self._step_lbls):
            is_sub = (9 <= i <= 13)
            base_bg = "#252525" if is_sub else "#2d2d2d"
            if i == idx:
                lbl.config(bg="#0078d4", fg="white")
            elif i < idx:
                lbl.config(bg=base_bg, fg="#66bb6a")
            else:
                lbl.config(bg=base_bg, fg="#aaaaaa")
        # Tint the parent "Project & Core" button when a sub-page is active
        if 9 <= idx <= 13:
            self._step_lbls[8].config(bg="#1a5276", fg="#aed6f1")
        self._back_btn.config(state="normal" if idx > 0 else "disabled")
        is_last = (idx == len(self.pages) - 1)
        self._next_btn.config(text="Finish" if is_last else "Next",
                              command=self._finish if is_last else self._next)
        orch = self.state.get("orchestrator", "ado")
        self._save_btn.config(text="SAVE (.yaml)" if orch == "ado" else "SAVE (.env)")
        self._refresh_nav_badges()
        self._update_status()

    def _next(self):
        if self.pages[self._cur].on_leave() and self._cur < len(self.pages)-1:
            self._show(self._cur+1)

    def _back(self):
        if self._cur>0: self._show(self._cur-1)

    def _finish(self): self._save()

    def _finish_and_run(self):
        """Save the wizard project file, then also write to the actual pipeline
        variables location (and optionally run the GHA shell script)."""
        orch       = self.state.get("orchestrator", "ado")
        save_folder = self.state.get("_save_folder", "").strip()

        if not save_folder:
            messagebox.showerror("No Folder",
                "Set the aifactory root folder on Page 1 first, then try again.")
            return

        # Step 1 – always save the wizard project snapshot first
        self._save()

        # Step 2 – write to the actual pipeline variables location
        if orch == "ado":
            dest = os.path.join(
                save_folder, "esml-infra", "azure-devops",
                "bicep", "yaml", "variables", "variables.yaml")
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                save_azure_devops(self.state, dest)
                messagebox.showinfo(
                    "Pipeline Updated",
                    f"variables.yaml written to:\n{dest}")
            except Exception as exc:
                messagebox.showerror("Error", str(exc))
        else:
            # GHA: .env goes one level above the aifactory root
            parent_folder = os.path.dirname(save_folder.rstrip("/\\"))
            dest = os.path.join(parent_folder, ".env")
            try:
                save_github_actions(self.state, dest)
            except Exception as exc:
                messagebox.showerror("Error", str(exc))
                return
            # Optionally run the GHA setup script
            script = os.path.join(
                parent_folder, "10-GH-create-or-update-github-variables.sh")
            if os.path.isfile(script):
                try:
                    import subprocess
                    proc = subprocess.Popen(
                        ["bash", script],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=parent_folder,
                    )
                    out, err = proc.communicate(input=b"d\n\nn\n", timeout=120)
                    msg = out.decode("utf-8", "replace") or "(no output)"
                    messagebox.showinfo(
                        "Pipeline Script",
                        f".env written and script completed:\n{msg[:800]}")
                except Exception as exc:
                    messagebox.showerror("Script Error", str(exc))
            else:
                messagebox.showinfo(
                    "GHA .env Updated",
                    f".env written to:\n{dest}\n\n"
                    f"Script not found (skipped):\n{script}")

    def _also_update_git_vars(self, orch: str, save_folder: str) -> str:
        """Write pipeline variable file to actual GIT repo path.
        Returns a short status string to embed in the success messagebox."""
        if orch == "ado":
            dest = os.path.join(
                save_folder, "esml-infra", "azure-devops",
                "bicep", "yaml", "variables", "variables.yaml")
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                save_azure_devops(self.state, dest)
                return f"GIT pipeline file updated:\n{dest}"
            except Exception as exc:
                messagebox.showerror("GIT Update Error", str(exc))
                return ""
        else:
            parent_folder = os.path.dirname(save_folder.rstrip("/\\"))
            dest = os.path.join(parent_folder, ".env")
            try:
                save_github_actions(self.state, dest)
                return f"GIT .env updated:\n{dest}"
            except Exception as exc:
                messagebox.showerror("GIT Update Error", str(exc))
                return ""

    def _build_search_index(self):
        """Walk every page's widget tree, match against _WIDGET_REGISTRY,
        and build self._search_index = [(display_label, state_key, page_idx)]."""
        def _descendants(widget):
            result = {widget}
            try:
                for child in widget.winfo_children():
                    result |= _descendants(child)
            except Exception:
                pass
            return result

        key_to_page: dict = {}
        for pidx, page in enumerate(self.pages):
            desc = _descendants(page)
            for state_key, entries in _WIDGET_REGISTRY.items():
                if state_key not in key_to_page:
                    for (w, _lbl) in entries:
                        if w in desc:
                            key_to_page[state_key] = pidx
                            break

        index = []
        for state_key, pidx in key_to_page.items():
            entries = _WIDGET_REGISTRY.get(state_key, [])
            label = entries[0][1] if entries else _friendly_label(state_key)
            index.append((str(label), state_key, pidx))
        index.sort(key=lambda x: x[0].lower())
        self._search_index = index
        self._key_page_map = key_to_page

    def _do_search(self):
        term = self._search_var.get().strip().lower()
        # Clear results list
        for w in self._search_results.winfo_children():
            w.destroy()
        if not term:
            self._search_results.pack_forget()
            return
        si = getattr(self, "_search_index", [])
        matches = [
            (lbl, key, pidx) for (lbl, key, pidx) in si
            if term in key.lower() or term in lbl.lower()
        ][:9]
        if not matches:
            self._search_results.pack_forget()
            return
        for lbl, key, pidx in matches:
            page_name = ""
            if 0 <= pidx < len(self._step_lbls):
                try:
                    page_name = self._step_lbls[pidx].cget("text").strip()
                except Exception:
                    pass
            display = f"{lbl}\n[{page_name}]"
            btn = tk.Button(
                self._search_results,
                text=display,
                bg="#2a2a2a", fg="#dddddd",
                activebackground="#0078d4", activeforeground="white",
                relief="flat", anchor="w", justify="left",
                font=("Segoe UI", 8),
                wraplength=170,
                command=lambda p=pidx, k=key: self._search_navigate(p, k))
            btn.pack(fill="x", padx=2, pady=1)
        # Position the results frame just below the search entry
        self._search_results.pack(fill="x", before=self._step_lbls[0])

    def _search_navigate(self, page_idx, state_key):
        self._search_var.set("")
        self._search_results.pack_forget()
        self._show(page_idx)
        page = self.pages[page_idx] if 0 <= page_idx < len(self.pages) else None
        def _do():
            for (w, _) in _WIDGET_REGISTRY.get(state_key, []):
                self._flash_widget(w, page)
        self.after(100, _do)

    def _flash_widget(self, widget, page=None):
        """Apple-style: blue ring behind widget + scroll into view."""
        if page is not None and getattr(page, "_sf", None):
            self.after(60, lambda: self._scroll_to_widget(page._sf, widget))

        def _do():
            try:
                widget.update_idletasks()
                widget.focus_set()
                x = widget.winfo_x()
                y = widget.winfo_y()
                w = widget.winfo_width()
                h = widget.winfo_height()
                parent = widget.master
                ring = tk.Frame(parent, bg="#0078d4", bd=0)
                ring.place(x=x-3, y=y-3, width=w+6, height=h+6)
                ring.lower(widget)
                widget.after(2200, lambda: ring.destroy() if ring.winfo_exists() else None)
            except Exception:
                pass
        self.after(120, _do)

    def _scroll_to_widget(self, sf, widget):
        """Scroll _ScrollFrame sf so widget is vertically centred in view."""
        try:
            inner = sf.inner
            canvas = sf._canvas
            inner.update_idletasks()
            wy = widget.winfo_rooty() - inner.winfo_rooty()
            wh = widget.winfo_height()
            ch = canvas.winfo_height()
            total = inner.winfo_height()
            if total <= ch:
                return
            frac = max(0.0, min(1.0, (wy - (ch - wh) / 2) / total))
            canvas.yview_moveto(frac)
        except Exception:
            pass


    def _new_project(self):
        """Reset wizard state to template defaults for a fresh project."""
        orch = self.state.get("orchestrator", "ado")
        src_label = ".env template" if orch == "gha" else "variables.yaml template"
        ans = messagebox.askyesno(
            "New Project",
            f"This will reset ALL fields to the {src_label} defaults.\n"
            "Unsaved changes to the current project will be lost.\n\n"
            "Continue?",
        )
        if not ans:
            return
        # Start from a clean DEFAULT_STATE copy
        import copy as _copy
        self.state.clear()
        self.state.update(_copy.deepcopy(DEFAULT_STATE))
        # Load template file values on top
        if orch == "gha":
            rel_env = os.path.join("template-files", ".env")
            candidates = [
                _res(rel_env),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_env),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel_env),
            ]
            tpl_path = next((p for p in candidates if os.path.isfile(p)), None)
            if tpl_path:
                _import_env_to_state(tpl_path, self.state)
                # _import_env_to_state sets orchestrator="gha" — keep it
            else:
                messagebox.showwarning("New Project", "Could not find template-files\\.env")
        else:
            tpl_path = _find_template_yaml()
            if os.path.isfile(tpl_path):
                _import_yaml_to_state(tpl_path, self.state)
                # _import_yaml_to_state sets orchestrator="ado" — keep it
            else:
                messagebox.showwarning("New Project", "Could not find template-files\\variables.yaml")
        # Clear per-session / per-project values not in template
        self.state["orchestrator"] = orch
        self.state["_save_folder"] = ""
        self.state["_also_update_git"] = True
        _sync_vars_from_state(self.state)
        for p in self.pages:
            p.set_advanced_mode(self._advanced)
            try:
                p.on_enter()
            except Exception:
                pass
        self._retheme_all()
        self._mark_clean()

    # ── <todo> validation ────────────────────────────────────────────────
    _TODO_PAGE_HINTS = {
        "github_username":    "Page 1 — Orchestrator  |  GitHub Username",
        "github_new_repo":    "Page 1 — Orchestrator  |  New Repo (org/repo-name)",
        "tenantId":           "Page 2 — Scale Set     |  Tenant ID",
        "dev_sub_id":         "Page 2 — Scale Set     |  DEV Subscription ID",
        "test_sub_id":        "Page 2 — Scale Set     |  STAGE Subscription ID",
        "prod_sub_id":        "Page 2 — Scale Set     |  PROD Subscription ID",
        "technical_admins_ad_object_id": "Page 2 — Scale Set     |  Project Members (Object IDs)",
        "privDnsSubscription_param": "Page 4 — Adv. Networking |  Hub DNS Subscription ID",
        "privDnsResourceGroup_param": "Page 4 — Adv. Networking |  Hub DNS Resource Group",
        "dev_admin_bicep_input_keyvault_subscription": "Page 5 — AI Factory Extras |  DEV KV Subscription ID",
        "dev_admin_bicep_kv_fw":    "Page 5 — AI Factory Extras |  DEV KV Name",
        "dev_admin_bicep_kv_fw_rg": "Page 5 — AI Factory Extras |  DEV KV Resource Group",
        "inputCommonSPIDKey":  "Page 5 — AI Factory Extras |  Common SP AppId KV secret name",
        "inputCommonSPSecretKey": "Page 5 — AI Factory Extras |  Common SP Secret KV secret name",
        "commonServicePrincipleOIDKey": "Page 5 — AI Factory Extras |  Common SP OID KV secret name",
        "cmkKeyName":         "Page 7 — Security / CMK  |  CMK Key Name",
        "project_service_principal_AppID_seeding_kv_name": "Page 9 — Project & Core  |  Project SP AppID KV secret name",
        "project_service_principal_OID_seeding_kv_name":   "Page 9 — Project & Core  |  Project SP OID KV secret name",
        "project_service_principal_Secret_seeding_kv_name": "Page 9 — Project & Core  |  Project SP secret KV secret name",
        "azure_machinelearning_sp_oid": "Page 13 — Other  |  Azure ML Service Principal OID",
        "databricksOID":      "Page 13 — Other  |  Databricks OID",
    }

    # Fields whose <todo> placeholder is only required when an enabling flag is set.
    # Maps state_key -> (gate_state_key, required_value). If the gate is not met,
    # the <todo> placeholder is ignored (the field is not needed).
    _TODO_CONDITIONAL_GATES = {
        "cmkKeyName":                     ("cmk", "true"),
        "byoAseFullResourceId":          ("byoASEv3", "true"),
        "byoAseAppServicePlanResourceId": ("byoASEv3", "true"),
    }

    # Fields whose <todo> placeholder is never validated (optional by design).
    _TODO_SKIP_ALWAYS = {
        "technical_admins_email",
    }

    def _is_active_todo(self, state_key, value, is_gha) -> bool:
        """True if *state_key* is an in-scope required field still holding a
        <todo> placeholder.  Shared by the save check and the nav badges so
        both stay in sync."""
        if state_key.startswith("_"):
            return False
        if is_gha and "service_connection" in state_key:
            return False
        if state_key in self._TODO_SKIP_ALWAYS:
            return False
        gate = self._TODO_CONDITIONAL_GATES.get(state_key)
        if gate:
            gate_key, gate_val = gate
            if str(self.state.get(gate_key, "")).strip().lower() != gate_val:
                return False
        return isinstance(value, str) and "<todo>" in value.lower()

    def _check_todo_fields(self) -> bool:
        """Scan state for any value containing '<todo>'. Returns True if clean."""
        is_gha = self.state.get("orchestrator", "ado") == "gha"
        problems = []
        for state_key, value in sorted(self.state.items()):
            if not self._is_active_todo(state_key, value, is_gha):
                continue
            env_key = ENV_MAP.get(state_key, state_key.upper())
            hint = self._TODO_PAGE_HINTS.get(state_key)
            if hint:
                problems.append(f"  * {hint}\n      {env_key} = \"{value}\"")
            else:
                widget_info = _WIDGET_REGISTRY.get(state_key)
                label = widget_info[0][1] if widget_info else state_key
                problems.append(f"  * {label}\n      {env_key} = \"{value}\"")
        if not problems:
            return True
        messagebox.showwarning(
            "Required Fields Incomplete  (⚠ <todo> values found)",
            "The following variables still contain placeholder values (<todo>).\n"
            "Please fill them in before saving.\n\n"
            + "\n\n".join(problems)
        )
        return False

    # ── Per-page completion badges + status bar ─────────────────────────
    def _page_todo_counts(self) -> dict:
        """Return {page_idx: count_of_active_todo_fields}."""
        kmap = getattr(self, "_key_page_map", {})
        is_gha = self.state.get("orchestrator", "ado") == "gha"
        counts: dict = {}
        for state_key, value in self.state.items():
            if not self._is_active_todo(state_key, value, is_gha):
                continue
            pidx = kmap.get(state_key)
            if pidx is not None:
                counts[pidx] = counts.get(pidx, 0) + 1
        return counts

    def _nav_base_text(self, idx) -> str:
        """The label text without any trailing status badge."""
        try:
            t = self._step_lbls[idx].cget("text")
        except Exception:
            return ""
        i = t.find("   ⚠")
        return t[:i] if i != -1 else t

    def _refresh_nav_badges(self):
        """Append ⚠N to pages that still have required <todo> fields."""
        try:
            counts = self._page_todo_counts()
        except Exception:
            counts = {}
        for idx, lbl in enumerate(self._step_lbls):
            base = self._nav_base_text(idx)
            n = counts.get(idx, 0)
            text = f"{base}   ⚠{n}" if n else base
            try:
                lbl.config(text=text)
            except Exception:
                pass

    def _update_status(self):
        if not hasattr(self, "_status_var"):
            return
        orch = self.state.get("orchestrator", "ado")
        target = "Azure DevOps · variables.yaml" if orch == "ado" else "GitHub Actions · .env"
        folder = self.state.get("_save_folder", "").strip() or "(no folder set)"
        proj = self.state.get("project_number_000", "000")
        dirty = "●  unsaved" if self._is_dirty() else "○  saved"
        last = f"   ·   last save {self._last_save_str}" if getattr(self, "_last_save_str", "") else ""
        self._status_var.set(
            f"Project {proj}   ·   {target}   ·   {folder}   ·   {dirty}{last}")
        api_status = self._api_host.status if self._api_host is not None else "stopped"
        self._set_api_status(api_status)

    def _set_api_status(self, status):
        if status == "running":
            self._api_status_var.set("Running API host at http://127.0.0.1:8765")
            self._api_status_label.config(fg="#107c10")
        elif status == "starting":
            self._api_status_var.set("Starting API host at http://127.0.0.1:8765...")
            self._api_status_label.config(fg="#986f0b")
        else:
            self._api_status_var.set(
                "No API Host running. Go to Quicksetup to START it"
            )
            self._api_status_label.config(fg="#a4262c")

    def _tick_status(self):
        try:
            self._update_status()
            self._refresh_nav_badges()
        except Exception:
            pass
        self.after(1000, self._tick_status)

    def _save_state(self):
        """Save current wizard state (project snapshot + app settings) without writing output files."""
        try:
            proj = self.state.get("project_number_000", "000")
            snap_path = _save_project_snapshot(self.state)
            _save_app_settings({"last_project": proj})
            self._mark_clean()
            messagebox.showinfo("State Saved", f"Project {proj} state saved to:\n{snap_path}")
        except Exception as exc:
            messagebox.showerror("Save State Error", str(exc))

    # ── Dirty tracking ──────────────────────────────────────────────────
    def _state_signature(self) -> str:
        """A stable string fingerprint of the current settings."""
        try:
            return _json.dumps(self.state, sort_keys=True, default=str)
        except Exception:
            return repr(sorted((str(k), str(v)) for k, v in self.state.items()))

    def _mark_clean(self):
        """Record the current state as the 'saved' baseline (no unsaved edits)."""
        self._baseline_sig = self._state_signature()
        self._baseline_state = copy.deepcopy(self.state)
        try:
            import time as _time
            self._last_save_str = _time.strftime("%H:%M:%S")
        except Exception:
            pass
        try:
            self._update_status()
            self._refresh_nav_badges()
        except Exception:
            pass

    _CHANGE_IGNORE = {"_version_str"}

    def _compute_changes(self):
        """List of (state_key, old, new) differing from the saved baseline."""
        base = getattr(self, "_baseline_state", None)
        if not base:
            return []
        changes = []
        for k in sorted(set(self.state) | set(base)):
            if k in self._CHANGE_IGNORE:
                continue
            old = base.get(k, "")
            new = self.state.get(k, "")
            if str(old) != str(new):
                changes.append((k, old, new))
        return changes

    def _review_changes_dialog(self) -> bool:
        """Show a modal 'what changed since last save' review. Returns True to
        proceed with the save, False to cancel. No dialog when nothing changed."""
        if not self._is_dirty():
            return True
        changes = self._compute_changes()
        if not changes:
            return True
        win = tk.Toplevel(self)
        win.title("Review changes before saving")
        win.transient(self)
        win.grab_set()
        win.configure(bg="#f5f5f5")
        tk.Label(win,
                 text=f"{len(changes)} setting(s) changed since the last save / load:",
                 bg="#f5f5f5", fg="#1a1a1a",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        frame = tk.Frame(win, bg="#ffffff", bd=1, relief="solid")
        frame.pack(fill="both", expand=True, padx=12, pady=4)
        txt = tk.Text(frame, width=86, height=18, wrap="word",
                      bg="#ffffff", fg="#1a1a1a", font=("Consolas", 9), bd=0,
                      padx=8, pady=6)
        vs = tk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.tag_config("h", font=("Segoe UI", 9, "bold"), foreground="#0a5c2e")
        txt.tag_config("old", foreground="#b00020")
        txt.tag_config("new", foreground="#0a5c2e")
        for k, old, new in changes:
            txt.insert("end", _friendly_label(k.lstrip("_")) + "\n", "h")
            txt.insert("end", "    ")
            txt.insert("end", f"{old!s}", "old")
            txt.insert("end", "  →  ")
            txt.insert("end", f"{new!s}\n\n", "new")
        txt.configure(state="disabled")
        result = {"ok": False}
        btns = tk.Frame(win, bg="#f5f5f5")
        btns.pack(fill="x", padx=12, pady=(4, 12))
        def _ok():
            result["ok"] = True
            win.destroy()
        def _cancel():
            result["ok"] = False
            win.destroy()
        ttk.Button(btns, text="Save", command=_ok).pack(side="right", padx=4)
        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right", padx=4)
        win.bind("<Escape>", lambda e: _cancel())
        win.bind("<Return>", lambda e: _ok())
        try:
            win.geometry("+%d+%d" % (self.winfo_rootx() + 120,
                                     self.winfo_rooty() + 120))
        except Exception:
            pass
        self.wait_window(win)
        return result["ok"]

    def _is_dirty(self) -> bool:
        """True only if the user changed a setting since the last save/load."""
        if getattr(self, "_baseline_sig", None) is None:
            return False   # baseline not captured yet → treat as clean
        return self._state_signature() != self._baseline_sig

    # ── Keyboard shortcuts ──────────────────────────────────────────────
    def _bind_shortcuts(self):
        """Global keyboard accelerators. Ctrl combos are entry-safe; page
        navigation uses Alt+Arrow to avoid clobbering text editing."""
        self.bind_all("<Control-s>",        lambda e: (self._save(), "break")[1])
        self.bind_all("<Control-S>",        lambda e: (self._save(), "break")[1])
        self.bind_all("<Control-Shift-S>",  lambda e: (self._save_state(), "break")[1])
        self.bind_all("<Control-n>",        lambda e: (self._new_project(), "break")[1])
        self.bind_all("<Control-N>",        lambda e: (self._new_project(), "break")[1])
        self.bind_all("<Control-f>",        self._focus_search)
        self.bind_all("<Control-F>",        self._focus_search)
        self.bind_all("<Alt-Right>",        lambda e: (self._next(), "break")[1])
        self.bind_all("<Alt-Left>",         lambda e: (self._back(), "break")[1])
        self.bind_all("<F1>",               self._show_help)
        self.bind("<Escape>",               lambda e: self._on_close())

    def _focus_search(self, _evt=None):
        try:
            self._search_entry.focus_set()
            self._search_entry.select_range(0, "end")
        except Exception:
            pass
        return "break"

    def _show_help(self, _evt=None):
        messagebox.showinfo(
            "Keyboard Shortcuts & Help",
            "Navigation\n"
            "  Alt + →            Next page\n"
            "  Alt + ←            Previous page\n"
            "  Click a step in the left rail to jump\n\n"
            "Actions\n"
            "  Ctrl + S           Save output file (.yaml/.env)\n"
            "  Ctrl + Shift + S   Save project state only\n"
            "  Ctrl + N           New project\n"
            "  Ctrl + F           Jump to the search box\n"
            "  Esc                Close (prompts if unsaved)\n"
            "  F1                 This help\n\n"
            "Tips\n"
            "  • Hover any field for a description / variable name.\n"
            "  • ⚠ in the left rail marks pages with required <todo> fields.\n"
            "  • The status bar shows folder, target and unsaved state.")
        return "break"

    def _on_close(self):
        """Ask whether to save state before closing — only when there are
        unsaved changes.  A pristine session closes immediately."""
        if not self._is_dirty():
            self._shutdown_and_destroy()
            return
        ans = messagebox.askyesnocancel(
            "Save before closing?",
            "You have unsaved changes.\n"
            "Do you want to save the current project state before closing?",
        )
        if ans is True:
            self._save_state()
            self._shutdown_and_destroy()
        elif ans is False:
            self._shutdown_and_destroy()
        # ans is None → Cancel: do nothing

    def _shutdown_and_destroy(self):
        if self._api_host is not None:
            self._api_host.stop()
        self.destroy()

    def _load_last_project_silent(self):
        """Silently restore the last-used project on startup (no popup)."""
        app_settings = _load_app_settings()
        last = app_settings.get("last_project", "")
        if not last:
            return
        base = self.state.get("_save_folder", "").strip()
        snaps = _list_project_snapshots(base)
        path = snaps.get(last)
        if not path:
            return
        try:
            data = _load_project_state(path, base)
            self.state.clear()
            self.state.update(data)
            self.state["_save_folder"] = base
            _sync_vars_from_state(self.state)
            for p in self.pages:
                p.set_advanced_mode(self._advanced)
                try:
                    p.on_enter()
                except Exception:
                    pass
            if self._proj_expanded:
                self._refresh_projects_list()
            self._retheme_all()
        except Exception:
            pass

    def _hydrate_from_startup_folder(self):
        """Restore project identity, then load authoritative folder variables."""
        configured_folder = _load_app_settings().get("_save_folder", "").strip()
        self._load_last_project_silent()
        if not configured_folder:
            return

        self.state["_save_folder"] = configured_folder
        orchestrator_page = self.pages[1]
        if orchestrator_page._folder_var.get() != configured_folder:
            orchestrator_page._folder_var.set(configured_folder)
        orchestrator_page._import_from_startup_folder(configured_folder)

    def _save(self):
        # ── <todo> placeholder guard ──────────────────────────────────────
        if not self._check_todo_fields():
            return
        # ── Destructive-operation guard ───────────────────────────────────
        if self.state.get("deleteAllServicesForProject", "false") == "true":
            proj = self.state.get("project_number_000", "?")
            ok = messagebox.askokcancel(
                "⚠  Destructive Operation — Confirm Save",
                f"deleteAllServicesForProject is set to TRUE.\n\n"
                f"When you next run the pipeline for project {proj}, it will:\n"
                f"  • Delete all services in the project resource group\n"
                f"    (except storage, keyvault, and logs)\n"
                f"  • Purge soft-deleted resources (Foundry, AML, etc.)\n\n"
                f"Do you really want to save with this setting?\n"
                f"If not, uncheck 'Delete all services for project' first.")
            if not ok:
                return
        # ── Review what changed since the last save / load ────────────────
        if not self._review_changes_dialog():
            return
        orch = self.state.get("orchestrator", "ado")
        save_folder = self.state.get("_save_folder", "").strip()
        proj = self.state.get("project_number_000", "000")

        if save_folder:
            # Auto-determine destination from configured base folder
            proj_dir = os.path.join(save_folder, "config-wizard", f"project-{proj}")
            try:
                os.makedirs(proj_dir, exist_ok=True)
            except Exception as exc:
                messagebox.showerror("Folder Error",
                    f"Cannot create folder:\n{proj_dir}\n\n{exc}")
                return
            dest = os.path.join(proj_dir,
                                "variables.yaml" if orch == "ado" else ".env")
            try:
                if orch == "ado":
                    save_azure_devops(self.state, dest)
                else:
                    save_github_actions(self.state, dest)
                snap_path = _save_project_snapshot(self.state)
                _save_app_settings({"last_project": proj})
                if self._proj_expanded:
                    self._refresh_projects_list()

                # ── Also update actual pipeline vars when checkbox is set ──
                git_msg = ""
                if self.state.get("_also_update_git", False):
                    git_msg = self._also_update_git_vars(orch, save_folder)

                self._mark_clean()
                messagebox.showinfo("Saved",
                    f"Project {proj} saved to:\n{dest}\n\nState: {snap_path}"
                    + (f"\n\n" + git_msg if git_msg else ""))
            except Exception as exc:
                messagebox.showerror("Error", str(exc))
        else:
            # Fall back to file dialog when no base folder configured
            if orch == "ado":
                dest = filedialog.asksaveasfilename(
                    title="Save ADO variables.yaml", defaultextension=".yaml",
                    filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
                    initialfile="variables.yaml")
                if dest:
                    try:
                        save_azure_devops(self.state, dest)
                        _save_project_snapshot(self.state)
                        if self._proj_expanded: self._refresh_projects_list()
                        self._mark_clean()
                        messagebox.showinfo("Saved", f"variables.yaml saved to:\n{dest}")
                    except Exception as exc:
                        messagebox.showerror("Error", str(exc))
            else:
                dest = filedialog.asksaveasfilename(
                    title="Save GitHub Actions .env", defaultextension="",
                    filetypes=[("env files", "*.env"), ("All files", "*.*")],
                    initialfile=".env")
                if dest:
                    try:
                        save_github_actions(self.state, dest)
                        _save_project_snapshot(self.state)
                        if self._proj_expanded: self._refresh_projects_list()
                        self._mark_clean()
                        messagebox.showinfo("Saved", f".env saved to:\n{dest}")
                    except Exception as exc:
                        messagebox.showerror("Error", str(exc))


def _run_packaged_api_smoke_test() -> int:
    """Start and probe the embedded API for build/runtime validation."""
    import time
    from urllib.request import urlopen

    host = None
    try:
        from src.api import API_KEY_ENV, ApiHost

        port = int(os.environ.get("AIFACTORY_API_SMOKE_PORT", "18765"))
        os.environ.setdefault(API_KEY_ENV, "packaged-smoke-test-key")
        host = ApiHost(port=port)
        host.start()
        deadline = time.monotonic() + 10
        while host.status == "starting" and time.monotonic() < deadline:
            time.sleep(0.05)
        if host.status != "running":
            raise RuntimeError(f"API startup failed: {host.error or host.status}")
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            payload = json.load(response)
        if payload.get("status") != "ok":
            raise RuntimeError(f"Unexpected health response: {payload}")
        return 0
    except Exception as exc:
        try:
            error_path = os.environ.get(
                "AIFACTORY_API_SMOKE_ERROR", "aifactory-api-smoke-error.txt"
            )
            with open(error_path, "w", encoding="utf-8") as error_file:
                error_file.write(f"{type(exc).__name__}: {exc}\n")
        except Exception:
            pass
        return 1
    finally:
        if host is not None:
            host.stop()


if __name__ == "__main__":
    if "--api-smoke-test" in sys.argv:
        raise SystemExit(_run_packaged_api_smoke_test())
    app = WizardApp()
    app.mainloop()
