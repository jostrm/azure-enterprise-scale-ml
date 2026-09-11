#!/usr/bin/env python3
"""Generate the public parameter inventory from shared templates; never read local settings."""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import re
import shlex
import sys


ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "environment_setup" / "aifactory"
COPY = SHARED / "bicep" / "copy_to_local_settings"
GHA = COPY / "github-actions"
YAML = COPY / "azure-devops" / "esml-yaml-pipelines" / "variables" / "variables.yaml"
PAGE = ROOT / "documentation" / "gh-io" / "docs" / "parameters" / "advanced.md"
SCHEMA = ROOT / "bootstrap" / "lib" / "aifactory_scaleset_config.py"
CREATE = ROOT / "bootstrap" / "lib" / "create-new-aifactory-scaleset.sh"
START = "<!-- BEGIN GENERATED PARAMETERS -->"
END = "<!-- END GENERATED PARAMETERS -->"

# Explicit template/backend correspondences reviewed against the shared consumers.
# Keep this finite: an absent binding must not be fabricated by case conversion.
REVIEWED_ALIASES = {
    "org-department-name": "ORG_DEPARTMENT_NAME",
    "org-department-id": "ORG_DEPARTMENT_ID",
    "aifactory-dash-01": "AIFACTORY_DASHBOARD_URL",
    "aifactory_version_minor": "AIFACTORY_VERSION_MINOR",
    "aifactory_version_major": "AIFACTORY_VERSION_MAJOR",
    "aifactory_salt": "AIFACTORY_SALT",
    "technical_admins_ad_object_id": "PROJECT_MEMBERS",
    "use_ad_groups": "USE_AD_GROUPS",
    "deleteKeyvaultAlso": "DELETE_KEYVAULT_ALSO",
    "useSelfHostedBuildAgent": "USE_SELF_HOSTED_BUILD_AGENT",
    "selfHostedRunnerLabel": "SELF_HOSTED_RUNNER_LABEL",
    "bingCustomSearchSku": "BING_CUSTOM_SEARCH_SKU",
    "postGresAdminEmails": "POSTGRES_ADMIN_EMAILS",
    "debugEnableCleaning": "DEBUG_ENABLE_CLEANING",
    "enableRetries": "ENABLE_RETRIES",
    "retryMinutes": "RETRY_MINUTES",
    "retryMinutesExtended": "RETRY_MINUTES_EXTENDED",
    "maxRetryAttempts": "MAX_RETRY_ATTEMPTS",
    "debug_disable_validation_tasks": "DEBUG_DISABLE_VALIDATION_TASKS",
    "project_IP_whitelist": "PROJECT_MEMBERS_IP_ADDRESS",
    "azure_machinelearning_sp_oid": "AZURE_MACHINELEARNING_SP_OID",
    "disableContributorAccessForUsers": "DISABLE_CONTRIBUTOR_ACCESS_FORUSERS",
    "disableRBACAdminOnRGForUsers": "DISABLE_RBAC_ADMIN_ON_RG_FORUSERS",
    "tag_repository": "TAG_REPOSITORY",
    "tag_repository_branch": "TAG_REPOSITORY_BRANCH",
    "network_env_dev": "DEV_NETWORK_ENV",
    "network_env_stage": "STAGE_NETWORK_ENV",
    "network_env_prod": "PROD_NETWORK_ENV",
    "BYOContributorRoleID": "BYO_CONTRIBUTOR_ROLE_ID",
    "admin_projectType": "PROJECT_TYPE",
    "admin_aks_gpu_sku_test_prod_override": "ADMIN_AKS_GPU_SKU_TEST_PROD_OVERRIDE",
    "apimGatewaySubscriptionId": "APIM_GATEWAY_SUBSCRIPTION_ID",
    "apimGatewayResourceGroup": "APIM_GATEWAY_RESOURCE_GROUP",
    "apimGatewayServiceName": "APIM_GATEWAY_SERVICE_NAME",
    "apimGatewaySku": "APIM_GATEWAY_SKU",
    "apimGatewaySkuCapacity": "APIM_GATEWAY_SKU_CAPACITY",
    "apimGatewayApiId": "APIM_GATEWAY_API_ID",
    "apimGatewayApiPath": "APIM_GATEWAY_API_PATH",
    "apimGatewayBackendPoolName": "APIM_GATEWAY_BACKEND_POOL_NAME",
    "apimGatewayAggregateTpm": "APIM_GATEWAY_AGGREGATE_TPM",
    "apimGatewayCallerTpm": "APIM_GATEWAY_CALLER_TPM",
    "apimGatewayRetryCount": "APIM_GATEWAY_RETRY_COUNT",
    "apimGatewayAssignOpenAIUserRole": "APIM_GATEWAY_ASSIGN_OPENAI_USER_ROLE",
    "apimGatewayManagedIdentityPrincipalId": "APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID",
    "apimGatewayBackendsJson": "APIM_GATEWAY_BACKENDS_JSON",
    "kongGatewayVnetResourceGroup": "KONG_GATEWAY_VNET_RESOURCE_GROUP",
    "kongGatewayVnetName": "KONG_GATEWAY_VNET_NAME",
    "kongGatewaySubnetCidr": "KONG_GATEWAY_SUBNET_CIDR",
    "kongGatewaySubnetName": "KONG_GATEWAY_SUBNET_NAME",
    "kongGatewayApimHost": "KONG_GATEWAY_APIM_HOST",
    "kongGatewayImage": "KONG_GATEWAY_IMAGE",
    "kongGatewayCpu": "KONG_GATEWAY_CPU",
    "kongGatewayMemoryGb": "KONG_GATEWAY_MEMORY_GB",
    "AMLStudioUIPrivate": "AML_STUDIO_UI_PRIVATE",
    "databricksPrivate": "DATABRICKS_PRIVATE",
    "admin_ip_fw": "ADMIN_IP_FW",
    "aifactory_branch_chosen": "AIFACTORY_BRANCH_CHOSEN",
    "aifactory_salt_random": "AIFACTORY_SALT_RANDOM",
    "common_bastion_subnet_name": "COMMON_BASTION_SUBNET_NAME",
    "commonLakeNamePrefixMax8chars": "LAKE_PREFIX",
    "groups_coreteam_members": "GROUPS_CORETEAM_MEMBERS",
    "groups_project_members_esml": "GROUPS_PROJECT_MEMBERS_ESML",
    "groups_project_members_genai_1": "GROUPS_PROJECT_MEMBERS_GENAI_1",
    "personas_core_team": "PERSONAS_CORE_TEAM",
    "personas_project_esml": "PERSONAS_PROJECT_ESML",
    "personas_project_genai_1": "PERSONAS_PROJECT_GENAI_1",
    "serviceSettingDeployProjectVM": "SERVICE_SETTING_DEPLOY_PROJECT_VM",
    "debug_disable_05_build_acr_image": "DEBUG_DISABLE_05_BUILD_ACR_IMAGE",
    "debug_disable_61_foundation": "DEBUG_DISABLE_61_FOUNDATION",
    "debug_disable_62_core_infrastructure": "DEBUG_DISABLE_62_CORE_INFRASTRUCTURE",
    "debug_disable_63_cognitive_services": "DEBUG_DISABLE_63_COGNITIVE_SERVICES",
    "debug_disable_64_databases": "DEBUG_DISABLE_64_DATABASES",
    "debug_disable_65_compute_services": "DEBUG_DISABLE_65_COMPUTE_SERVICES",
    "debug_disable_66_ai_platform": "DEBUG_DISABLE_66_AI_PLATFORM",
    "debug_disable_67_data_ml_platform": "DEBUG_DISABLE_67_ML_PLATFORM",
    "debug_disable_68_integration": "DEBUG_DISABLE_68_INTEGRATION",
    "debug_disable_69_aifoundry_2025": "DEBUG_DISABLE_69_AIFOUNDRY_2025",
    "debug_disable_100_rbac_security": "DEBUG_DISABLE_100_RBAC_SECURITY",
    "dev_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "test_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "prod_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "dev_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "test_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "prod_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "dev_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
    "test_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
    "prod_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
}


def load_schema():
    spec = importlib.util.spec_from_file_location("parameter_schema", SCHEMA)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cell(value):
    return str(value).replace("|", "&#124;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def code(value):
    return "`" + str(value).replace("|", "&#124;").replace("`", "&#96;").replace("\n", " ") + "`"


def literal(value):
    return code(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def parse_template(path, pattern, schema):
    entries = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        match = pattern.match(line)
        if not match:
            continue
        key, rest = match.groups()
        raw, comment = schema.split_comment(rest)
        raw = raw.strip()
        if raw.startswith(("'", '"')):
            # No environment expansion or execution of shell/YAML values.
            value = raw[1:-1]
            if raw.startswith('"'):
                try:
                    value = json.loads(raw)
                except ValueError:
                    pass
        else:
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw
        if key in entries:
            entries[key]["lines"].append(number)
            entries[key]["value"] = value
        else:
            entries[key] = {"value": value, "comment": comment.lstrip("# ").strip(), "lines": [number]}
    return entries


def sentence(key):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key).replace("_", " ").replace("-", " ").strip().capitalize()


def requirement(key, comment):
    lower = key.lower()
    if key in {"enableAIFoundry", "enableAFoundryCaphost", "enableAISearch", "enableCosmosDB",
               "ENABLE_AI_FOUNDRY", "ENABLE_FOUNDRY_CAPHOST", "ENABLE_AI_SEARCH", "ENABLE_COSMOS_DB"}:
        return "C", "Required together for the standard private-agent capability-host architecture; not universal across all deployment paths."
    if key in {"APIM_GATEWAY_RESOURCE_GROUP", "APIM_GATEWAY_SERVICE_NAME", "APIM_GATEWAY_AGGREGATE_TPM", "APIM_GATEWAY_BACKENDS_JSON",
               "apimGatewayResourceGroup", "apimGatewayServiceName", "apimGatewayAggregateTpm", "apimGatewayBackendsJson"}:
        return "C", "Required by the separate AI gateway workflow when APIM is enabled."
    if key in {"APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID", "apimGatewayManagedIdentityPrincipalId"}:
        return "C", "Required when assigning the OpenAI user role to the APIM managed identity."
    if key in {"KONG_GATEWAY_VNET_RESOURCE_GROUP", "KONG_GATEWAY_VNET_NAME", "KONG_GATEWAY_SUBNET_CIDR", "KONG_GATEWAY_APIM_HOST", "KONG_CONSUMER_API_KEY",
               "kongGatewayVnetResourceGroup", "kongGatewayVnetName", "kongGatewaySubnetCidr", "kongGatewayApimHost"}:
        return "C", "Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret."
    if lower.startswith(("test_", "prod_", "stage_")) and any(word in lower for word in ("subscription", "sub_id", "service_connection", "bicep_")):
        return "C", "Required when deploying that environment."
    if any(word in lower for word in ("inputcommonsp", "input_common_sp", "serviceprincipleoidkey", "service_principle_oid", "service_principal_kv_s", "service_principal_appid", "service_principal_oid", "service_principal_secret")):
        return "C", "Secret-name reference for the selected service-principal/seeding path; not a credential value."
    tags = re.findall(r"<(mandatory|optional)>", comment)
    conditional = ("mandatory" in tags and tags[0] == "optional") or "optional if" in comment.lower()
    if conditional:
        return "C", ""
    return ("M" if tags and tags[0] == "mandatory" else "O"), ""


DESCRIPTIONS = {
    "deployModel_gpt_54_mini": "Enable the separately named GPT-5.4-mini deployment toggle; inspect its workflow binding alongside deployModel_gpt_X.",
    "default_gpt_54_mini_version": "Version for the separately named GPT-5.4-mini deployment toggle.",
    "DEPLOY_MODEL_GPT_54_MINI": "Enable the separately named GPT-5.4-mini deployment toggle.",
    "DEFAULT_GPT_54_MINI_VERSION": "Version for the separately named GPT-5.4-mini deployment toggle.",
    "tags": "Common resource tags as a JSON string; Azure DevOps macro expressions are preserved.",
    "tagsProject": "Project resource tags as a JSON string; Azure DevOps macro expressions are preserved.",
    "scaling-mode": "Address-planning preset: own-subscriptions or shared-subscriptions. Does not create subscriptions, resize networks, or establish peering.",
    "SCALING_MODE": "Address-planning preset: own-subscriptions or shared-subscriptions; no subscription provisioning, network resizing, or peering.",
}


def description(key, entry):
    comment = entry.get("comment", "")
    text = re.sub(r"^<(?:mandatory|optional)>", "", comment).split("<default>", 1)[0]
    text = DESCRIPTIONS.get(key, text or sentence(key) + ".")
    text = re.sub(r"<(?:mandatory|optional|ensure|recommended|keep-as-is|otherwise)>", " ", text)
    text = text.replace("Wizard network preset", "Address-planning preset")
    notes = []
    for tag, value in re.findall(r"<(mandatory|otherwise|ensure|recommended|keep-as-is)>([^<]*)", comment):
        value = value.strip()
        if value:
            notes.append(f"{tag}: {value}")
    _, conditional = requirement(key, comment)
    if conditional:
        notes.append(conditional)
    # Do not repeat stale model descriptions/default claims from legacy comments.
    if key in DESCRIPTIONS:
        notes = []
    return cell(" ".join([text.strip(), *notes]))


def category(key):
    lower = key.lower()
    for title, pattern in (
        ("Models and deployments", r"model|embedding|gpt"),
        ("Per-environment SKUs and compute sizing", r"^sku|^aks|_aks_|_aml_|adminvmsize|admin_vm_size"),
        ("Networking, DNS and existing resources", r"subnet|cidr|vnet|dns|network|^byo|^priv|ip_whitelist|ip_address|allowpublic|public.*access|public_access|^scaling"),
        ("Identity, access and encryption", r"tenant|principal|principle|spid|spsecret|_sp_|service_connection|ad_groups|^use_ad|rbac|contributor|^cmk|^groups|^personas|members|technical_admin|localauth|local_auth"),
        ("Services and feature switches", r"^enable|^add|^update|^clean|^disable|^service|^apim|^kong|^elastic|^acr|^foundry|^databricks|^amlstudio"),
        ("Operations, diagnostics and lifecycle", r"^debug|^delete|^retry|^maxretry|diagnostic|^run|^policy|^self|runner|buildagent"),
    ):
        if re.search(pattern, lower):
            return title
    return "Factory, project, naming and orchestration"


def aliases(keys, schema):
    result = defaultdict(set)
    for key, env in REVIEWED_ALIASES.items():
        if key in keys:
            result[key].add(env)
    # Read actual bindings, including ordered fallback references, not case conversions.
    for path in sorted(GHA.glob("*.yml")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s+([\w-]+):\s+[\"']?\$\{\{(.*)", line)
            if match and match[1] in keys:
                expression = match[2]
                # In ternary-like expressions the left side of && is a condition,
                # not a value alias (e.g. BYO_SUBNETS must not alias subnet names).
                expression = expression.split("&&", 1)[-1]
                result[match[1]].update(re.findall(r"(?:vars|secrets)\.([A-Z][A-Z0-9_]*)", expression))
    preflight = (SHARED / "bicep" / "scripts" / "preflight.sh").read_text(encoding="utf-8-sig")
    for key, env in re.findall(r"getval\s+([\w-]+)\s+([A-Z][A-Z0-9_]*)", preflight):
        if key in keys:
            result[key].add(env)
    tree = ast.parse(SCHEMA.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name)
                        and value.value.id == "values" and isinstance(value.slice, ast.Constant)
                        and value.slice.value in keys):
                    result[value.slice.value].add(key.value)
    for key in keys:
        if key.isupper():
            result[key].add(key)
    return result


def bootstrap_inventory():
    source = CREATE.read_text(encoding="utf-8-sig")
    entries = {}
    # Explicit self-default assignments are externally supplied inputs; generated locals are excluded.
    for match in re.finditer(r'^\s*(AIF_[A-Z0-9_]+|ADO_[A-Z0-9_]+|GITHUB_[A-Z0-9_]+|AZURE_DEVOPS_EXT_PAT)="\$\{\1:-(.*)\}"', source, re.M):
        key, value = match.groups()
        entries[key] = {"value": value, "comment": "", "lines": [source[:match.start()].count("\n") + 1]}
    logical = source.replace("\\\n", "")
    for match in re.finditer(r'^\s*aif_prompt_(value|choice|yes_no|secret) ([A-Z][A-Z0-9_]+) (.+)$', logical, re.M):
        kind, key, tail = match.groups()
        args = shlex.split(tail)
        entry = entries.setdefault(key, {"value": "", "comment": "", "lines": []})
        entry["comment"] = args[0]
        default = args[1] if len(args) > 1 else ""
        if default == "$" + key:
            pass
        elif default or not entry["value"]:
            entry["value"] = default
        if kind == "choice":
            entry["comment"] += "; allowed: " + args[2]
    extras = {
        "AIFACTORY_REPO_ROOT": ("", "Repository root; --repo-root overrides it."),
        "AIFACTORY_VERSION": ("main", "Explicit template release; create/update defaults to main. --aifactory-version takes precedence."),
        "AIF_SUBMODULE_BRANCH": ("", "Legacy explicit branch selector consumed by release-version resolution."),
        "AIF_SUBMODULE_REF": ("", "Exact published commit SHA; required for the simple-mode source verification contract."),
        "AIF_CREATE_DEFAULT_VERSION": ("main", "Create launcher default when no explicit version selector is supplied."),
        "AIF_UPDATE_DEFAULT_VERSION": ("main", "Update launcher default when not project-only."),
        "AIFACTORY_TARGET_ENVIRONMENT": ("dev", "Update target: dev, test/stage, or prod; verify route/environment naming."),
        "AIFACTORY_PROJECT_CONFIG": ("", "Reviewed project JSON file; required together with explicit target environment, project number and repository root."),
        "AIFACTORY_PROJECT_NUMBER": ("", "Reviewed update/project target number; required together with target environment, project configuration and repository root."),
        "AIFACTORY_PROJECT_ONLY": ("false", "Update launcher equivalent of --project-only."),
        "AIFACTORY_COMMIT_CHANGES": ("", "Update confirmation y/yes or n/no; default No. Choosing Yes authorizes the launcher's commit/continue path."),
        "AIFACTORY_UPDATE_GITHUB_VARIABLES": ("", "GHA update confirmation y/yes or n/no for synchronization from .env; default No."),
        "AIFACTORY_USE_JSON_OVERRIDE": ("", "y/yes enables variables.json overrides; blank/n/no disables. Explicit reviewed project inputs force this to yes."),
        "ADO_BRANCH": ("main", "ADO update branch; reviewed project dispatch requires main."),
        "ADO_PIPELINE_NAME": ("infra-project-genai", "ADO legacy update pipeline name."),
        "ADO_RUNNER_SELECTION": ("from-config", "ADO legacy update runner selection."),
        "ADO_SETTINGS_FILE": ("$HOME/.aifactory-ado-settings.json", "ADO saved organization/project context path; generator never reads this file."),
        "AIF_APP_GATEWAY_HOSTNAME": ("", "Simple-mode custom frontend FQDN covered by certificate DNS SAN."),
        "AIF_APP_GATEWAY_BACKEND_FQDN": ("", "Simple-mode distinct private HTTPS backend; trusted TLS and unauthenticated GET / returning 200-399."),
        "AIF_APP_GATEWAY_CERT_SECRET_ID": ("", "Simple-mode versionless Key Vault PFX certificate-secret URI, not a secret value."),
        "AIF_SIMPLE_PROJECT_RESOURCES_JSON": (
            re.search(r"AIF_SIMPLE_PROJECT_RESOURCES_JSON='([^']+)'", source)[1],
            "Simple-mode JSON resource-ID selection. Required project dependencies cannot be removed; [] removes only optional selections."),
    }
    for key, (value, comment) in extras.items():
        entries[key] = {"value": value, "comment": comment, "lines": []}
    notes = {
        "AIF_ADD_BASTION": "Compatibility input; collection resets this to false. Access-hub Bastion is controlled separately.",
        "AIF_IP_ALLOWLIST": "IPv4 allowlist input; the current create prompt accepts private networking only.",
        "AIF_AZURE_ML_PRINCIPAL_ID": "Existing Azure Machine Learning enterprise-application object ID; otherwise discovered/ensured.",
        "AIF_DATABRICKS_PRINCIPAL_ID": "Existing Databricks enterprise-application object ID; otherwise discovered/ensured when needed.",
        "AIF_TEAM_GROUP_ID": "Reuse an existing team group by object ID; otherwise resolve/create from group name.",
        "AIF_SIMPLE_MODE": "Opt in to the GHA Dev private foundation contract.",
        "AIF_COST_CENTER": "Simple-mode common and project cost-center tag.",
        "GITHUB_REPOSITORY_VISIBILITY": "Simple-mode repository visibility: private or public; independent of Azure networking.",
    }
    for key, note in notes.items():
        entries[key]["comment"] = note
    return entries


def state_inventory():
    tree = ast.parse(SCHEMA.read_text(encoding="utf-8-sig"))
    entries = defaultdict(lambda: {"required": set(), "optional": set(), "defaults": []})
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "state" and isinstance(node.slice, ast.Constant)):
                entries[node.slice.value]["required"].add(function.name)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "state"
                  and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant)):
                entry = entries[node.args[0].value]
                entry["optional"].add(function.name)
                try:
                    default = ast.literal_eval(node.args[1]) if len(node.args) > 1 else None
                except ValueError:
                    default = "derived expression"
                if default not in entry["defaults"]:
                    entry["defaults"].append(default)
    return entries


def bootstrap_requirement(key):
    if key in {"AIF_TENANT_ID", "AIF_DEV_SUBSCRIPTION_ID", "AIF_TEAM_MEMBER_EMAIL"}:
        return "M"
    if (key.startswith(("ADO_", "AIF_HUB_", "AIF_ACCESS_HUB_", "AIF_APP_GATEWAY_"))
            or key in {"GITHUB_REPOSITORY", "AZURE_DEVOPS_EXT_PAT", "AIF_MI_RESOURCE_ID", "AIF_SP_CLIENT_ID", "AIF_SP_CLIENT_SECRET", "AIF_SUBMODULE_REF", "AIF_SEEDING_RESOURCE_GROUP", "AIF_SEEDING_KEYVAULT_NAME",
                       "AIFACTORY_PROJECT_CONFIG", "AIFACTORY_PROJECT_NUMBER", "AIFACTORY_TARGET_ENVIRONMENT"}):
        return "C"
    return "O"


def api_inventory():
    tree = ast.parse(SCHEMA.read_text(encoding="utf-8-sig"))
    entries = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            key = ast.literal_eval(node.args[0])
            kwargs = {item.arg: item.value for item in node.keywords}
            default = ast.literal_eval(kwargs["default"]) if "default" in kwargs else False if "action" in kwargs else None
            choices = ast.literal_eval(kwargs["choices"]) if "choices" in kwargs else None
            entries[key] = (default, choices)
    return entries


def generate():
    schema = load_schema()
    yaml = parse_template(YAML, re.compile(r"^  ([\w-]+):\s*(.*)$"), schema)
    env = parse_template(GHA / ".env.template", re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$"), schema)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    document = json.loads((SHARED / "variables.json").read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    keys = set(yaml) | {key for section in document.values() for key in section}
    mapping = aliases(keys, schema)
    reverse = defaultdict(set)
    for key, values in mapping.items():
        for value in values:
            reverse[value].add(key)
    bootstrap = bootstrap_inventory()
    api = api_inventory()
    state = state_inventory()
    expected = {"yaml": set(yaml), "env": set(env), "bootstrap": set(bootstrap), "helper": set(api), "state": set(state)}
    expected.update({f"json.{section}": set(values) for section, values in document.items()})
    lines = [START, "", "## Source coverage", "", "| Source | Unique public keys |", "|---|---:|"]
    lines += [f"| {code(source)} | {len(values)} |" for source, values in expected.items()]
    lines += ["", "Counts are source-qualified: a spelling present in YAML and JSON is covered in each source, not counted as two settings. Repeated template assignments are consolidated below (last assignment wins).", ""]
    for source, entries in (("yaml", yaml), ("env", env)):
        for key, entry in entries.items():
            if len(entry["lines"]) > 1:
                lines.append(f"- Source duplicate: {code(source + ':' + key)}, lines {', '.join(map(str, entry['lines']))}; one reference row.")
    lines += ["", "## YAML and variables.json reference", "", "Exact YAML keys are under `variables:`; JSON paths are `<section>.<key>`. **Y** = YAML assignment; **J.section** = JSON value. JSON quoting and scalar types are preserved. A missing source is explicitly marked. GHA names include workflow bindings/fallbacks and explicitly reviewed template counterparts; they are not automatically interchangeable and inclusion does not guarantee every workflow consumes them.", ""]

    def marker(source, key):
        return f"<!-- parameter {source}:{key} -->"

    groups = defaultdict(list)
    for key in sorted(keys):
        groups[category(key)].append(key)
    for group, members in groups.items():
        lines += [f"### {group}", "", "| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |", "|---|---|---|---|---|"]
        for key in members:
            entry = yaml.get(key) or next((env[e] for e in sorted(mapping[key]) if e in env), {"comment": ""})
            status, _ = requirement(key, entry["comment"])
            defaults = []
            marks = []
            if key in yaml:
                defaults.append("Y: " + literal(yaml[key]["value"]))
                marks.append(marker("yaml", key))
            else:
                defaults.append("Y: absent")
            for section, values in document.items():
                if key in values:
                    defaults.append(f"J.{section}: " + literal(values[key]))
                    marks.append(marker(f"json.{section}", key))
                else:
                    defaults.append(f"J.{section}: absent")
            bindings = ", ".join(code(value) + (" (not in .env template)" if value not in env else "") for value in sorted(mapping[key])) or "No verified binding"
            lines.append(f"| {''.join(marks)}{code(key)} | {bindings} | {status} | {'<br>'.join(defaults)} | {description(key, entry)} |")
        lines.append("")
    lines += ["## GitHub Actions .env reference", "", "Every unique assignment is included, including orchestrator-only and compatibility names. Values are decoded literals, not expansions; these are template values, not necessarily the workflow's effective fallback. **No verified counterpart** means no mapping was found in the inspected shared bindings, not proof that a setting is unused.", ""]
    groups = defaultdict(list)
    for key in sorted(env):
        groups[category(key)].append(key)
    for group, members in groups.items():
        lines += [f"### GHA: {group}", "", "| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |", "|---|---|---|---|---|"]
        for key in members:
            entry = env[key]
            status, _ = requirement(key, entry["comment"])
            names = ", ".join(map(code, sorted(reverse[key]))) or "No verified counterpart"
            lines.append(f"| {marker('env', key)}{code(key)} | {names} | {status} | {literal(entry['value'])} | {description(key, entry)} |")
        lines.append("")
    lines += ["## Shared-binding collisions", "", "These GHA names occur against multiple YAML/JSON keys. Follow the relevant workflow/environment rather than treating this as a one-to-one rename. All source defaults remain separate above.", "", "| GHA binding / fallback | YAML / JSON keys |", "|---|---|"]
    for key, values in sorted(reverse.items()):
        if len(values) > 1:
            lines.append(f"| {code(key)} | {', '.join(map(code, sorted(values)))} |")
    lines += ["", "## Bootstrap environment inputs", "", "Inputs are read by the create launchers, with version selectors also used by update. `M` means a value must resolve (an authenticated-context default may supply it); `C` means route/mode-specific; `O` means a default or optional override. `$...` defaults below are **literal source expressions**, not values discovered on this machine. Blank means no literal default at that point. Prompts, simple-mode fixed values, and validation can narrow them further.", "", "| Input | M/C/O | Source default / expression | Description |", "|---|---|---|---|"]
    for key, entry in sorted(bootstrap.items()):
        desc = entry["comment"] or sentence(key) + " override; see create launcher."
        lines.append(f"| {marker('bootstrap', key)}{code(key)} | {bootstrap_requirement(key)} | {literal(entry['value'])} | {cell(desc)} |")
    lines += ["", "## Configuration helper CLI inputs", "", "`bootstrap/lib/aifactory_scaleset_config.py` is a local configuration API, **not an HTTP endpoint**. `--route`, `--repo-root`, and `--state-file` are required together for the default write operation. Other switches select independent inspection/validation operations. Unspecified argparse values are `null`; boolean switches default to `false`.", "", "| Exact option | M/C/O | Parser default | Meaning / choices |", "|---|---|---|---|"]
    helper_notes = {
        "--simple-mode-manifest": "Offline read-only contract/preset preview.",
        "--verify-simple-mode-source": "Compare supplied checkout with the required shared source trees.",
        "--simple-mode-hub-subnets": "Validate existing subnet JSON and print reserved simple-mode subnets.",
        "--simple-gateway-inputs": "Validate gateway input strings and print normalized JSON; no deployment.",
        "--certificate-metadata": "Local certificate metadata JSON; validates metadata only, not private key material.",
        "--gateway-health": "Local gateway backend-health JSON; exit status indicates health.",
        "--state-file": "Bootstrap state JSON, not variables.json; consumed by the selected route writer.",
        "--repo-root": "Consumer root containing the generated .env/YAML/JSON configuration.",
        "--project-resources": "JSON array of simple-mode project resource IDs; required dependencies are retained.",
    }
    for key, (default, choices) in sorted(api.items()):
        note = helper_notes.get(key, sentence(key))
        if choices:
            note += "; choices: " + ", ".join(choices)
        lines.append(f"| {marker('helper', key)}{code(key)} | C | {literal(default)} | {cell(note)} |")
    lines += ["", "## Bootstrap state JSON fields", "", "These exact fields are consumed by the Python helper's local `--state-file` API. Normally the shell bootstrap writes this state after resolving identities and scope; it is **not** the persistent deployment `variables.json`. `C` below means required in the named function/route when invoked; `O` denotes only guarded `.get()` reads. Missing required keys are not defaulted. `project_sp_secret_names` contains the nested secret-name keys `app_id`, `object_id`, and `secret`, not secret values.", "", "| Exact state field | M/C/O | Missing-key behavior | Consumer / meaning |", "|---|---|---|---|"]
    for key, entry in sorted(state.items()):
        required = entry["required"]
        defaults = "Required lookup" if required else ", ".join(literal(value) for value in entry["defaults"])
        consumers = ", ".join(map(code, sorted(required | entry["optional"])))
        lines.append(f"| {marker('state', key)}{code(key)} | {'C' if required else 'O'} | {defaults} | {consumers}; {cell(sentence(key))} |")
    lines += ["", END]
    output = "\n".join(lines)
    found = defaultdict(list)
    for source, key in re.findall(r"<!-- parameter ([^: ]+):([^ ]+) -->", output):
        found[source].append(key)
    assert set(found) == set(expected), "Source inventory mismatch"
    for source, keys_in_source in expected.items():
        assert set(found[source]) == keys_in_source, f"Missing/extra keys in {source}"
        assert len(found[source]) == len(set(found[source])), f"Duplicate rows in {source}"
    return output, {source: len(values) for source, values in expected.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate exact source coverage and fail if the page is stale.")
    args = parser.parse_args()
    output, counts = generate()
    text = PAGE.read_text(encoding="utf-8")
    before, remainder = text.split(START, 1)
    _, after = remainder.split(END, 1)
    updated = before + output + after
    if args.check:
        if text != updated:
            print("Parameter reference is stale; run generate_parameters.py.", file=sys.stderr)
            return 1
    else:
        PAGE.write_text(updated, encoding="utf-8", newline="\n")
    print("Exact coverage, no duplicate rows: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
