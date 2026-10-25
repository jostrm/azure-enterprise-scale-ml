#!/usr/bin/env python3
"""Generate the "Deploy to Azure" portal package for the v1.25 Simple Mode full bootstrap.

Offline and deterministic. The Simple Mode preset (bootstrap/lib/aifactory_scaleset_config.py), the
canonical environment_setup/aifactory/variables.json and the GitHub Actions workflows stay the source
of truth: this script replays the GitHub route of the bootstrap (apply_gha -> .env/GitHub variables ->
workflow job env -> variables.json override -> stage --parameters) with sentinel tokens for the values
only known at deployment time, and never hand-copies a flag value.

No Azure, GitHub or network calls. Bicep is invoked only with --compile.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

BICEP_VERSION = "0.37.4"
PUBLISH_REPOSITORY = "jostrm/azure-enterprise-scale-ml"
PUBLISH_BRANCH = "portal-125"
WORKFLOWS = "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
BICEP = "environment_setup/aifactory/bicep"
RELEASE = "v1.25"
REGION_PAGE = "documentation/regions/aifactory-v125-region-availability.md"
BASTION_REGIONS = "portal/data/bastion-developer-regions.json"
SAME_REGION = "same-as-factory-region"  # form sentinel; main.bicep maps it (and "") to location
DEFAULT_PROJECT_RESOURCES = ["foundry", "foundry-capability-host", "ai-search", "cosmos-db", "application-insights"]

# Values only known at deployment time. main.bicep replaces every __P_<name>__ token.
TOKENS = (
    "location", "locationShort", "prefix", "scalesetNumber", "subscriptionId", "tenantId",
    "teamGroupObjectId", "teamGroupName", "teamMemberEmail", "costCenter", "seedingKeyVaultName",
    "bootstrapResourceGroup", "commonResourceGroup", "searchLocation", "deploymentRandom", "prefixBare",
)


def token(name: str) -> str:
    return f"__P_{name}__"


# Portal-only stages compiled beside the pipeline stages.
PORTAL_MODULES = {
    "stages/portal-bootstrap.json": "portal/modules/bootstrap.bicep",
    "stages/portal-hub-access.json": "portal/modules/hub-access.bicep",
    "stages/portal-vpn-gateway.json": "portal/modules/vpn-gateway.bicep",
    "stages/portal-seeding-endpoint.json": "portal/modules/seeding-endpoint.bicep",
    "stages/portal-private-dns-policy.json": "portal/modules/private-dns-policy.bicep",
    "stages/portal-foundry-injection-rbac.json": "portal/modules/foundry-injection-rbac.bicep",
    "stages/portal-cosmos-foundry-rbac.json": "portal/modules/cosmos-foundry-rbac.bicep",
    "stages/portal-app-gateway-certificate-rbac.json": "portal/modules/app-gateway-certificate-rbac.bicep",
}
SOURCE_TEMPLATES = {
    "11-rgCommon": f"{BICEP}/esml-common/main/11-rgCommon.bicep",
    "12-networkCommon": f"{BICEP}/esml-common/main/12-networkCommon.bicep",
    "13-rgLevel": f"{BICEP}/esml-common/main/13-rgLevel.bicep",
    "createPrivateDnsZones": f"{BICEP}/modules/createPrivateDnsZones.bicep",
    "28-Initiatives": f"{BICEP}/esml-util/28-Initiatives.bicep",
    "simple-app-gateway-network": "bootstrap/lib/simple-app-gateway-network.bicep",
    "simple-app-gateway": "bootstrap/lib/simple-app-gateway.bicep",
    "31-network": f"{BICEP}/esml-genai-1/31-network.bicep",
    "03b-ai-search": f"{BICEP}/esml-genai-1/03b-ai-search.bicep",
    **{name: f"{BICEP}/esml-genai-1/{name}.bicep" for name in (
        "01-foundation", "02-core-infrastructure", "03-cognitive-services", "04-databases",
        "05-compute-services", "06-ai-platform", "07-ml-data-platform", "11-integration",
        "08-rbac-security", "08b-rbac-common-rg", "09-ai-foundry-2025-v4")},
}

# Network plan replacing subnetCalc_v2.ps1 (projectType "all", genaiSubnetCidrAll defaults) and
# simple_mode_hub_subnets: name -> (prefix length, index) for cidrSubnet(vnetCidr, prefix, index).
NETWORK = {
    "vnetCidr": "172.16.0.0/20",
    "subnets": {
        "common": (26, 0), "scoring": (26, 1), "powerbi": (26, 2), "bastion": (26, 3),
        "GatewaySubnet": (27, 8), "snet-dns-private-resolver": (28, 18), "snet-application-gateway": (24, 2),
        "aca": (23, 2), "aca2": (23, 3), "aks2": (24, 8), "genai": (25, 18),
        "aks": (26, 38), "dbxpub": (26, 39), "dbxpriv": (26, 40), "webapp": (27, 82),
    },
}
# subnetParameters.json (subnetCalc_v2.ps1, projectType all) -> network plan entry.
SUBNET_PARAMETERS = {
    "genaiSubnetCidr": "genai", "aksSubnetCidr": "aks", "aks2SubnetCidr": "aks2", "acaSubnetCidr": "aca",
    "aca2SubnetCidr": "aca2", "webappSubnetCidr": "webapp", "dbxPubSubnetCidr": "dbxpub",
    "dbxPrivSubnetCidr": "dbxpriv",
}
# dynamicNetworkParams.json (genDynamicNetworkParamFile.ps1, projectType all) -> 31-network outputs.
DYNAMIC_NETWORK_PARAMETERS = (
    "genaiSubnetId", "aksSubnetId", "aks2SubnetId", "acaSubnetId", "aca2SubnetId", "webappSubnetId",
    "dbxPubSubnetName", "dbxPrivSubnetName",
)
# Pipeline values computed by shell at run time; main.bicep sets them explicitly.
SHELL_WIRED = {"adminPassword"}
# Step-local shell variables passed as stage parameters: (step, parameter, raw text) -> value from the
# job env, mirroring the step's own bash. An unknown shell value fails generation instead of guessing.
SHELL_VALUES = {
    ("62-core-infrastructure", "updateCommonACR", "$UPDATE_COMMON_ACR"):
        lambda env: env.get("updateCommonACR") or "true",
    ("63-cognitive-services", "skuAISearchDev", "$searchSkuDev"):
        lambda env: env["AIF_AISEARCH_PROVISIONED_SKU"] if env.get("AIF_AISEARCH_STATE") == "provisioned" else env["skuAISearchDev"],
    ("63-cognitive-services", "skuAISearchStageProd", "$searchSkuStageProd"):
        lambda env: env["AIF_AISEARCH_PROVISIONED_SKU"] if env.get("AIF_AISEARCH_STATE") == "provisioned" else env["skuAISearchStageProd"],
    ("100-rbac-security", "enableAzureMachineLearning", "$AML_RBAC"):
        lambda env: "true" if env.get("enableAzureMachineLearning") == "true" and env.get("amlExists") == "true" else "false",
    ("100-rbac-security", "aksExists", "$AKS_RBAC_EXISTS"):
        lambda env: env.get("aksExists", "false") if env.get("enableAksForAzureML") == "true" else "false",
    ("101-rbac-common-rg", "enableAzureMachineLearning", "$AML_RBAC"):
        lambda env: "true" if env.get("enableAzureMachineLearning") == "true" and env.get("amlExists") == "true" else "false",
    # admin-vm-exists.sh prints false when enableAdminVM is not true (Simple Mode disables the admin VM).
    ("03_az_bicep_deploy_resources", "adminVmExists", "$adminVmExists"):
        lambda env: _greenfield(env.get("enableAdminVM") != "true", "false", "adminVmExists needs an Azure read"),
    # discover-aml-aks-attachment.py runs only for AML with AKS; nothing is attached in a new project.
    ("67-data_ml_platform", "aksComputeExists", "$_aksComputeExists"): lambda env: "false",
}


def _greenfield(condition: bool, value: str, message: str) -> str:
    if not condition:
        raise ValueError(message)
    return value
# Preset values that the form may change (SIMPLE_MODE_RESOURCE_CATALOG optional items); main.bicep sets them.
FORM_WIRED = {"enableApplicationInsights"}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_config(root: Path):
    return load_module(root / "bootstrap/lib/aifactory_scaleset_config.py", "portal_simple_config")


# --- GitHub Actions expression subset --------------------------------------------------------------

_EXPRESSION_TOKEN = re.compile(r"\s*(\|\||&&|==|!=|!|\(|\)|'(?:[^']|'')*'|[A-Za-z_][\w.\-]*(?:\(\))?)")


def evaluate(expression: str, context: dict) -> str:
    """Evaluate the GitHub Actions expression forms used by the AI Factory workflows."""
    tokens, position, text = [], 0, expression.strip()
    while position < len(text):
        match = _EXPRESSION_TOKEN.match(text, position)
        if not match:
            raise ValueError(f"Unsupported workflow expression: {expression!r}")
        tokens.append(match[1])
        position = match.end()
    index = 0

    def peek():
        return tokens[index] if index < len(tokens) else None

    def take():
        nonlocal index
        index += 1
        return tokens[index - 1]

    def atom():
        item = take()
        if item == "(":
            value = either()
            if take() != ")":
                raise ValueError(f"Unbalanced workflow expression: {expression!r}")
            return value
        if item == "!":
            return "" if truthy(atom()) else "true"
        if item.startswith("'"):
            return item[1:-1].replace("''", "'")
        if item in ("true", "false"):
            return item
        if item in ("success()", "always()"):
            return "true"
        if item in ("failure()", "cancelled()"):
            return ""
        head, _, rest = item.partition(".")
        if head in context:
            return context[head](rest)
        raise ValueError(f"Unknown workflow identifier {item!r} in {expression!r}")

    def compare():
        value = atom()
        while peek() in ("==", "!="):
            operator, other = take(), atom()
            equal = str(value).lower() == str(other).lower()
            value = "true" if equal == (operator == "==") else ""
        return value

    def both():
        value = compare()
        while peek() == "&&":
            take()
            other = compare()
            value = other if truthy(value) else value
        return value

    def either():
        value = both()
        while peek() == "||":
            take()
            other = both()
            value = value if truthy(value) else other
        return value

    result = either()
    if index != len(tokens):
        raise ValueError(f"Trailing workflow expression tokens: {expression!r}")
    return result


def truthy(value) -> bool:
    return value not in ("", None)


def interpolate(text: str, context: dict) -> str:
    return re.sub(r"\$\{\{(.*?)\}\}", lambda match: str(evaluate(match[1], context)), text, flags=re.S)


# --- Workflow parsing ------------------------------------------------------------------------------

def _block(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    """Collect a YAML block scalar or folded continuation lines deeper than indent."""
    collected = []
    index = start
    while index < len(lines) and (not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > indent):
        collected.append(lines[index].strip())
        index += 1
    return " ".join(part for part in collected if part), index


def job_env(text: str, job: str) -> tuple[dict[str, str], int]:
    lines = text.splitlines()
    start = next(n for n, line in enumerate(lines) if re.fullmatch(rf"  {re.escape(job)}:\s*", line))
    env_line = next(n for n in range(start, len(lines)) if re.fullmatch(r"    env:\s*", lines[n]))
    env: dict[str, str] = {}
    index = env_line + 1
    while index < len(lines):
        line = lines[index]
        if re.match(r"^    \S", line):
            break
        match = re.match(r"^      ([A-Za-z_]\w*):\s*(.*)$", line)
        index += 1
        if not match:
            continue
        value = match[2].strip()
        if value in (">-", "|", ">"):
            value, index = _block(lines, index, 6)
        env[match[1]] = value
    return env, index


def steps(text: str, start: int) -> list[dict]:
    lines = text.splitlines()
    found: list[dict] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if re.match(r"^  [A-Za-z]", line):
            break
        match = re.match(r"^      - name:\s*(.+)$", line)
        if match:
            found.append({"name": match[1].strip(), "if": "", "body": []})
        elif found:
            condition = re.match(r"^        if:\s*(.*)$", line)
            if condition:
                value = condition[1].strip()
                if value in ("|", ">", ">-"):
                    value, index = _block(lines, index + 1, 8)
                    found[-1]["if"] = value
                    continue
                found[-1]["if"] = value
            found[-1]["body"].append(line)
        index += 1
    return found


def stage_calls(text: str, job: str) -> tuple[dict[str, str], list[dict]]:
    env, start = job_env(text, job)
    calls = []
    for step in steps(text, start):
        body = "\n".join(step["body"])
        template = re.search(r'--template-file\s+"?[^"\n]*/([\w.-]+)\.bicep', body)
        if not template:
            continue
        files, parameters = [], {}
        for match in re.finditer(r"--parameters\s+([^\n\\]+)", body):
            argument = match[1].strip()
            if argument.startswith("@"):
                files.append(re.search(r"([\w.-]+\.json)", argument)[1])
                continue
            name, _, value = argument.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            parameters[name] = value
        capacity = re.search(r"deploy-capacity-resource\.py[^\n]*\n?[^\n]*--service\s+(\S+)\s+--attempt\s+(\d+)", body)
        if capacity:
            files.append(re.search(r"--parameters-file\s+\"?[^\"\n]*?([\w.-]+\.json)", body)[1])
        calls.append({"step": step["name"], "template": template[1], "if": step["if"],
                      "files": files, "parameters": parameters, "body": body,
                      "capacity": {"service": capacity[1], "attempt": int(capacity[2]),
                                   "regional": "--search-region-fallback" in body} if capacity else None})
    return env, calls


def search_parameter_mapping(root: Path) -> dict[str, str]:
    """The Search script's own template-parameter -> environment mapping (search-region-fallback.py)."""
    tree = ast.parse((root / BICEP / "scripts/search-region-fallback.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "parameters")
    assignment = next(node for node in ast.walk(function) if isinstance(node, ast.Assign)
                      and getattr(node.targets[0], "id", "") == "mappings")
    return ast.literal_eval(assignment.value)


# --- Simple Mode replay ----------------------------------------------------------------------------

def portal_state() -> dict:
    """The CLI's state file (aif_write_state_and_configure) for a Simple Mode GHA run, with tokens."""
    subscription = token("subscriptionId")
    return {
        "topology": "s", "access_hub_mode": "integrated", "network_mode": "priv",
        "tenant_id": token("tenantId"), "dev_subscription_id": subscription,
        "stage_subscription_id": subscription, "prod_subscription_id": subscription,
        "location": token("location"), "location_short": token("locationShort"),
        "dev_vnet_cidr": NETWORK["vnetCidr"], "prefix": token("prefix"),
        "scaleset_suffix": "-" + token("scalesetNumber"), "project_number": "001",
        "team_group_id": token("teamGroupObjectId"), "team_group_name": token("teamGroupName"),
        "ip_allowlist": "", "seeding_subscription_id": subscription,
        "seeding_resource_group": token("bootstrapResourceGroup"),
        "seeding_keyvault_name": token("seedingKeyVaultName"),
        "enable_public_genai_access": "false", "allow_public_access_behind_vnet": "false",
        "enable_public_perimeter": "false", "add_bastion": "false",
        "hub_subscription_id": subscription, "hub_resource_group": token("commonResourceGroup"),
        "project_sp_secret_names": {"app_id": "", "object_id": "", "secret": ""},
        "azure_ml_principal_id": "", "databricks_principal_id": "",
        "github_repository": "portal/deploy-to-azure", "oidc_client_id": "",
        "runner_mode": "github-hosted", "admin_vm_size": "Standard_D2s_v5", "simple_mode": "true",
        "cost_center": token("costCenter"), "team_member_email": token("teamMemberEmail"),
        "simple_project_resources_json": json.dumps(DEFAULT_PROJECT_RESOURCES),
        "github_repository_visibility": "private",
    }


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return json.loads(value)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def _yaml_scalar(value: str) -> str:
    """Plain, single- or double-quoted YAML scalar text before expression interpolation."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def replay_bootstrap(root: Path, config) -> tuple[dict[str, str], dict]:
    """Run apply_gha on a scratch consumer layout; return GitHub variables and variables.json dev."""
    with tempfile.TemporaryDirectory() as scratch:
        consumer = Path(scratch)
        (consumer / "aifactory").mkdir()
        shutil.copyfile(root / WORKFLOWS / ".env.template", consumer / ".env")
        shutil.copyfile(root / "environment_setup/aifactory/variables.json", consumer / "aifactory/variables.json")
        config.apply_gha(consumer, portal_state())
        dotenv = {}
        for line in (consumer / ".env").read_text(encoding="utf-8").splitlines():
            match = config.ENV_ASSIGNMENT.match(line)
            if match and not line.lstrip().startswith("#"):
                dotenv[match["key"]] = _unquote(config.split_comment(match["rest"])[0])
        variables = json.loads((consumer / "aifactory/variables.json").read_text(encoding="utf-8"))["dev"]
    # Environment-level variables set by 03a-GH-create-or-update-github-variables.sh for dev.
    dotenv.update({
        "AZURE_ENV_NAME": "dev", "AZURE_LOCATION": dotenv["AIFACTORY_LOCATION"],
        "AZURE_SUBSCRIPTION_ID": dotenv["DEV_SUBSCRIPTION_ID"], "CIDR_RANGE": dotenv["DEV_CIDR_RANGE"],
        "AIFACTORY_CIDR_XX": dotenv["DEV_CIDR_RANGE"], "NETWORK_ENV": dotenv["DEV_NETWORK_ENV"],
    })
    return {key: value for key, value in dotenv.items() if value != ""}, variables


def serialize(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def resolved_environment(raw_env: dict[str, str], variables: dict, github: dict, inputs: dict,
                         json_override: bool) -> dict[str, str]:
    context = {
        "vars": lambda name: github.get(name, ""), "secrets": lambda name: github.get(name, ""),
        "inputs": lambda name: inputs.get(name, ""), "github": lambda name: "",
        "runner": lambda name: "", "steps": lambda name: "",
    }
    env = {}
    for name, value in raw_env.items():
        if "secrets[" in value:
            env[name] = ""
            continue
        env[name] = interpolate(_yaml_scalar(value), context)
    if json_override:  # 00_Apply_JSON_Config_Override (apply-json-config-overrides.py)
        aliases = {"aifactory-dash-01": "AIFACTORY_DASHBOARD_URL", "scaling-mode": "SCALING_MODE"}
        for name, value in variables.items():
            env[aliases.get(name, name)] = serialize(value)
    return env


def project_dynamic_env(env: dict[str, str]) -> dict[str, str]:
    """GITHUB_ENV writes of the project workflow, replayed for a greenfield Simple Mode run."""
    dynamic = {
        # 00_Initialize_Derived_Variables
        "deployment_random_value": token("deploymentRandom"),
        "project_IP_whitelist": "" if env.get("project_IP_whitelist") in ("-", "<todo_ip>", None) else env["project_IP_whitelist"],
        # 00_Resolve_Network_Env_Placeholders (vnetResourceGroup_param and vnetNameFull_param are empty)
        "vnetResourceGroup_resolved": (env["admin_aifactoryPrefixRG"] + env["vnetResourceGroupBase"] + "-"
                                       + env["admin_locationSuffix"] + "-" + env["dev_test_prod"]
                                       + env["admin_aifactorySuffixRG"]),
        "vnetNameFull_resolved": (env["vnetNameBase"] + "-" + env["admin_locationSuffix"] + "-"
                                  + env["dev_test_prod"] + env["admin_commonResourceSuffix"]),
        # 16_Check_Resource_Existence / 10_Check_Subnet_Existence on an empty subscription
        "sntLogicappExists": "false",
        # 17_Extract_aifactory_salt_random (resolve_managed_identities.py, no identities yet)
        "resolvedManagedIdentityNames": "{}", "miPrjExists": "false", "miACAExists": "false",
        "aifactory_salt_random": "",
        # 63a Search handoff (search-region-fallback.py publish_provisioned), region chosen in the form
        "AIF_AISEARCH_MODE": "normal", "AIF_AISEARCH_STATE": "provisioned", "aiSearchProvisioned": "true",
        "AIF_AISEARCH_PROVISIONED_LOCATION": token("searchLocation"),
        "AIF_AISEARCH_PROVISIONED_SKU": env.get("skuAISearchDev", "standard"),
        # v1.25: 63 and the 63b capacity attempt read aiSearchLocation (AI_SEARCH_LOCATION); the form sets it.
        "aiSearchLocation": token("searchLocation"),
        # 99_check_acr_role_assignments on a new registry
        "skipACRAssignments": "false", "existingAcrPushUserPrincipals": "", "existingAcrPushSPPrincipals": "",
    }
    return dynamic


# --- Typing ----------------------------------------------------------------------------------------

def typed(value, parameter_type: str):
    kind = parameter_type.lower()
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text not in ("true", "false"):
            raise ValueError(f"Expected a boolean, got {value!r}")
        return text == "true"
    if kind == "int":
        return value if isinstance(value, int) else int(str(value).strip())
    if kind in ("object", "array", "secureobject"):
        return value if isinstance(value, (dict, list)) else json.loads(value)
    return value if isinstance(value, str) else serialize(value)


def _has_token(value) -> bool:
    return "__P_" in json.dumps(value)


def classify(stage: dict, parameter: str, value, declared: dict) -> None:
    kind = declared[parameter]["type"].lower()
    if parameter in FORM_WIRED:
        stage["wired"].append(parameter)
        return
    if isinstance(value, str) and "__P_" in value:
        if kind in ("string", "securestring"):
            stage["templated"][parameter] = value
            return
        if kind in ("object", "array"):
            stage["templatedJson"][parameter] = value
            return
        raise ValueError(f"{stage['template']}: token in non-string parameter {parameter}")
    if isinstance(value, str) and value == "" and kind not in ("string", "securestring"):
        if "defaultValue" not in declared[parameter]:
            raise ValueError(f"{stage['template']}: empty value for required {kind} parameter {parameter}")
        stage["omitted"].append(parameter)
        return
    converted = typed(value, kind)
    if _has_token(converted):
        raise ValueError(f"{stage['template']}: token inside typed parameter {parameter}")
    if isinstance(converted, str) and converted.startswith("["):
        raise ValueError(f"{stage['template']}: literal {parameter} would be read as an ARM expression")
    stage["constants"][parameter] = converted


def _template_parameters(root: Path, name: str) -> dict:
    return json.loads((root / "portal/stages" / f"{name}.json").read_text(encoding="utf-8"))["parameters"]


def _new_stage(template: str, step: str, phase: str, scope: str, resource_group: str = "") -> dict:
    return {"template": f"stages/{template}.json", "step": step, "phase": phase, "scope": scope,
            "resourceGroup": resource_group, "constants": {}, "templated": {}, "templatedJson": {},
            "wired": [], "omitted": [], "sources": {}, "types": {}}


def _finish(stage: dict) -> dict:
    for key in ("constants", "templated", "templatedJson", "sources", "types"):
        stage[key] = dict(sorted(stage[key].items()))
    stage["wired"] = sorted(set(stage["wired"]))
    stage["omitted"] = sorted(set(stage["omitted"]))
    return stage


def pipeline_stage(root: Path, call: dict, env: dict[str, str], github: dict, inputs: dict, key_phase: str) -> dict:
    name = call["template"]
    declared = _template_parameters(root, name)
    scope = "resourceGroup" if name == "31-network" else "subscription"
    stage = _new_stage(name, call["step"], key_phase, scope, env.get("vnetResourceGroup_resolved", "") if scope == "resourceGroup" else "")
    context = {
        "vars": lambda key: github.get(key, ""), "secrets": lambda key: github.get(key, ""),
        "inputs": lambda key: inputs.get(key, ""), "github": lambda key: "",
        "env": lambda key: env.get(key, ""), "steps": lambda key: "",
    }
    values: dict[str, object] = {}
    for parameter_file in call["files"]:  # applied first; explicit --parameters win
        if parameter_file == "subnetParameters.json":
            stage["wired"].extend(SUBNET_PARAMETERS)
        elif parameter_file == "dynamicNetworkParams.json":
            # az --parameters @file passes every key; the capacity script keeps only declared ones.
            stage["wired"].extend(key for key in DYNAMIC_NETWORK_PARAMETERS
                                  if not call.get("capacity") or key in declared)
        elif parameter_file == "10-esml-globals-1.json":
            values.update({"aifactorySuffixRG": env["admin_aifactorySuffixRG"], "commonRGNamePrefix": env["admin_aifactoryPrefixRG"],
                           "locationSuffix": env["admin_locationSuffix"], "location": env["admin_location"]})
        elif parameter_file == "10-esml-globals-override.json":
            values.update({"vnetResourceGroup_param": env["vnetResourceGroup_resolved"],
                           "vnetNameFull_param": env["vnetNameFull_resolved"], "subnetProjLogicapp": ""})
            values.update({key: "" for key in ("subnetProjGenAI", "subnetProjAKS", "subnetProjAKS2", "subnetProjACA",
                                               "subnetProjACA2", "subnetProjWebapp", "subnetProjDatabricksPublic",
                                               "subnetProjDatabricksPrivate")})
        else:
            raise ValueError(f"Unknown parameter file {parameter_file} in {call['step']}")
    if call.get("capacity"):
        if call["capacity"]["attempt"] != 1 or call["capacity"]["regional"]:
            raise ValueError(f"{call['step']}: only the primary capacity attempt is replayed")
        values.update(capacity_values(root, call, env, declared))
    for parameter, raw in call["parameters"].items():
        if parameter in SHELL_WIRED or "$(" in raw:
            stage["wired"].append(parameter)
            values.pop(parameter, None)
            continue
        if "$" in raw.replace("${{", ""):
            raw = shell_value(call["step"], parameter, raw, env, call.get("body", ""))
        referenced = re.findall(r"env\.(\w+)", raw)
        if len(referenced) == 1 and raw.strip() == "${{ env.%s }}" % referenced[0]:
            stage["sources"][parameter] = referenced[0]
        values[parameter] = interpolate(raw, context)
    for parameter in list(values):
        if parameter in stage["wired"]:
            values.pop(parameter)
    for parameter, value in values.items():
        if parameter not in declared:
            raise ValueError(f"{call['step']} passes {parameter}, which {name} does not declare")
        stage["types"][parameter] = declared[parameter]["type"]
        classify(stage, parameter, value, declared)
    for parameter in stage["wired"]:
        if parameter not in declared:
            raise ValueError(f"{call['step']} wires {parameter}, which {name} does not declare")
    return _finish(stage)


def shell_value(step: str, parameter: str, raw: str, env: dict[str, str], body: str = "") -> str:
    match = re.fullmatch(r"\$\{(\w+):-\}|\$(\w+)", raw.strip())
    name = match and (match[1] or match[2])
    if name and name in env and not re.search(rf"(?m)^\s*(?:export\s+|local\s+)?{name}=", body):
        return env[name]  # job env variable read by bash and not reassigned in the step
    if (step, parameter, raw) in SHELL_VALUES:
        return SHELL_VALUES[(step, parameter, raw)](env)
    raise ValueError(f"{step}: unmapped shell value {raw!r} for {parameter}")


def capacity_contract(root: Path) -> tuple[dict, dict]:
    """PARAMETER_ALIASES and SERVICES of deploy-capacity-resource.py (v1.25+), read without importing it."""
    tree = ast.parse((root / BICEP / "scripts/deploy-capacity-resource.py").read_text(encoding="utf-8"))
    aliases, services = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PARAMETER_ALIASES":
            aliases = ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "SERVICES":
            for key, call in zip(node.value.keys, node.value.values):
                fields = ("sku", "array", "retry", "state", "default_dev", "default_stage_prod", "default_array")
                services[ast.literal_eval(key)] = dict(zip(fields, (ast.literal_eval(arg) for arg in call.args)))
    return aliases, services


def capacity_values(root: Path, call: dict, env: dict[str, str], declared: dict) -> dict[str, str]:
    """deployment_parameters() of deploy-capacity-resource.py for the first (primary) attempt."""
    aliases, services = capacity_contract(root)
    service = services[call["capacity"]["service"]]
    upper = {name.upper(): value for name, value in env.items()}
    values = {}
    for name in declared:
        for candidate in (*aliases.get(name, ()), name):
            if candidate.upper() in upper:
                values[name] = upper[candidate.upper()]
                break
    selected = upper.get((service["sku"] + "Dev").upper()) or service["default_dev"]
    values.update({"env": "dev", "location": env["admin_location"], service["sku"] + "Dev": selected,
                   "subscriptionIdDevTestProd": env["dev_test_prod_sub_id"]})
    if call["capacity"]["service"] == "ai-search":
        values["capacityIdentityOnly"] = "false"
    return {name: value for name, value in values.items() if name in declared}


def search_stage(root: Path, env: dict[str, str]) -> dict:
    """63a: search-region-fallback.py deploys 03b-ai-search.bicep with its own mapping."""
    declared = _template_parameters(root, "03b-ai-search")
    stage = _new_stage("03b-ai-search", "63a-search-provisioning", "infra", "subscription")
    stage["wired"].extend(key for key in ("genaiSubnetId", "aksSubnetId", "acaSubnetId", "aca2SubnetId", "aks2SubnetId")
                          if key in declared)
    values = {}
    for parameter, source in search_parameter_mapping(root).items():
        if source in env:
            values[parameter] = env[source]
            stage["sources"][parameter] = source
    values["aiSearchLocation"] = token("searchLocation")
    values["skuAISearchDev"] = env.get("skuAISearchDev", "standard")
    for parameter, value in values.items():
        if parameter not in declared:
            raise ValueError(f"03b-ai-search does not declare {parameter}")
        stage["types"][parameter] = declared[parameter]["type"]
        classify(stage, parameter, value, declared)
    return _finish(stage)


def private_dns_stage(root: Path) -> dict:
    """aif_prepare_hub_dns: createPrivateDnsZones.bicep with aifactory_private_dns.py zones."""
    dns = load_module(root / "bootstrap/lib/aifactory_private_dns.py", "portal_private_dns")
    configuration = dns.configuration(token("subscriptionId"), token("commonResourceGroup"),
                                      token("location"), token("locationShort"))
    declared = _template_parameters(root, "createPrivateDnsZones")
    stage = _new_stage("createPrivateDnsZones", "aif_prepare_hub_dns", "hub", "resourceGroup", token("commonResourceGroup"))
    values = {
        "location": token("location"), "privDnsSubscription": token("subscriptionId"),
        "privDnsResourceGroup": token("commonResourceGroup"), "vNetName": "vnt-esmlcmn-" + token("locationShort") + "-dev-001",
        "vNetResourceGroup": token("commonResourceGroup"), "allGlobal": "true",
        "privateLinksDnsZones": json.dumps(configuration["zones"]),
    }
    for parameter, value in values.items():
        stage["types"][parameter] = declared[parameter]["type"]
        classify(stage, parameter, value, declared)
    stage["policyAssignmentParameters"] = configuration["assignmentParameters"]
    return _finish(stage)


def portal_stage(root: Path, name: str, step: str, phase: str, scope: str, resource_group: str,
                 values: dict, wired: tuple[str, ...] = ()) -> dict:
    """A portal-only linked deployment; values use the same token rules as pipeline stages."""
    declared = _template_parameters(root, name)
    stage = _new_stage(name, step, phase, scope, resource_group)
    stage["wired"].extend(wired)
    for parameter, value in values.items():
        if parameter not in declared:
            raise ValueError(f"{name} does not declare {parameter}")
        stage["types"][parameter] = declared[parameter]["type"]
        classify(stage, parameter, value, declared)
    missing = {key for key, spec in declared.items() if "defaultValue" not in spec} - set(values) - set(wired)
    if missing:
        raise ValueError(f"{name} lacks values for {sorted(missing)}")
    return _finish(stage)


def derived_values(source: dict, template_parameters: dict) -> dict:
    """Copy the values a pipeline stage resolved for every parameter the portal template also declares."""
    values = {}
    for bucket in ("constants", "templated", "templatedJson"):
        for key, value in source[bucket].items():
            if key in template_parameters:
                values[key] = serialize(value) if bucket == "constants" else value
    return values


def hub_stages(root: Path, dns: dict) -> dict[str, dict]:
    common_rg, bootstrap_rg = token("commonResourceGroup"), token("bootstrapResourceGroup")
    vnet = "vnt-esmlcmn-" + token("locationShort") + "-dev-001"
    return {
        "bootstrap-seeding-vault": portal_stage(
            root, "portal-bootstrap", "aif_ensure_seeding_keyvault", "identity", "resourceGroup", bootstrap_rg,
            {"location": token("location"), "keyVaultName": token("seedingKeyVaultName"), "costCenter": token("costCenter")}),
        "hub-private-dns-initiative": portal_stage(
            root, "28-Initiatives", "aif_ensure_private_dns_policy_assignment", "hub", "subscription", "",
            {"location": token("location"), "includeCostOptimization": "false"}),
        "hub-private-dns-policy": portal_stage(
            root, "portal-private-dns-policy", "aif_ensure_private_dns_policy_assignment", "hub", "subscription", "",
            {"location": token("location"), "assignmentParameters": json.dumps(dns["policyAssignmentParameters"])}),
        "hub-access": portal_stage(
            root, "portal-hub-access", "aif_ensure_private_network_access", "hub", "resourceGroup", common_rg,
            {"location": token("location"), "vnetName": vnet, "vnetCidr": NETWORK["vnetCidr"],
             "namePrefix": token("prefixBare"), "locationShort": token("locationShort"),
             "scalesetNumber": token("scalesetNumber"), "costCenter": token("costCenter")},
            wired=("resolverSubnetCidr", "vpnClientCidr", "enableBastion")),
        "hub-vpn-gateway": portal_stage(
            root, "portal-vpn-gateway", "aif_ensure_vpn_access_hub", "hub", "resourceGroup", common_rg,
            {"location": token("location"), "vnetName": vnet, "vnetCidr": NETWORK["vnetCidr"],
             "locationShort": token("locationShort"), "scalesetNumber": token("scalesetNumber"),
             "costCenter": token("costCenter")},
            wired=("gatewaySubnetCidr", "vpnClientCidr")),
        "hub-app-gateway-network": portal_stage(
            root, "simple-app-gateway-network", "aif_prepare_simple_application_gateway", "hub", "resourceGroup", common_rg,
            {"location": token("location"), "gatewayName": "agw-" + token("prefix") + token("locationShort") + "-" + token("scalesetNumber"),
             "vnetName": vnet, "costCenter": token("costCenter"),
             "vaultDnsZoneId": "/subscriptions/" + token("subscriptionId") + "/resourceGroups/" + common_rg
                               + "/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"},
            wired=("vpnClientCidr", "certificateVaultId")),
        "hub-app-gateway-certificate-rbac": portal_stage(
            root, "portal-app-gateway-certificate-rbac", "aif_prepare_simple_application_gateway", "hub",
            "resourceGroup", "", {}, wired=("certificateVaultId", "principalId")),
        "hub-seeding-endpoint": portal_stage(
            root, "portal-seeding-endpoint", "aif_ensure_private_network_access", "hub", "resourceGroup", common_rg,
            {"location": token("location"), "vnetName": vnet}, wired=("keyVaultId",)),
    }


def foundry_stages(root: Path, stages: dict[str, dict]) -> dict[str, dict]:
    account = stages["project-09-ai-foundry-2025-v4"]
    cosmos_parameters = _template_parameters(root, "portal-cosmos-foundry-rbac")
    values = derived_values(account, cosmos_parameters)
    values["commonResourceGroup"] = token("commonResourceGroup")  # 09: empty commonResourceGroup_param default
    wired = [key for key in account["wired"] if key in cosmos_parameters] + ["accountName"]
    return {
        "foundry-injection-rbac": portal_stage(
            root, "portal-foundry-injection-rbac", "69a-Grant-NetworkContributor-For-Injection", "foundry",
            "resourceGroup", token("commonResourceGroup"),
            {"vnetName": "vnt-esmlcmn-" + token("locationShort") + "-dev-001"},
            wired=("accountResourceId", "agentSubnetId")),
        "foundry-cosmos-rbac": portal_stage(
            root, "portal-cosmos-foundry-rbac", "69c_cosmosdb_data_contributor_for_foundry_project", "foundry",
            "subscription", "", values, wired=tuple(wired)),
        "hub-app-gateway": portal_stage(
            root, "simple-app-gateway", "aif_deploy_simple_application_gateway", "completed", "resourceGroup",
            token("commonResourceGroup"),
            {"location": token("location"),
             "gatewayName": "agw-" + token("prefix") + token("locationShort") + "-" + token("scalesetNumber"),
             "vnetName": "vnt-esmlcmn-" + token("locationShort") + "-dev-001", "costCenter": token("costCenter")},
            wired=("hostname", "backendFqdn", "certificateSecretId")),
    }


def should_run(condition: str, env: dict[str, str], inputs: dict, github: dict) -> bool:
    if not condition:
        return True
    context = {
        "vars": lambda key: github.get(key, ""), "secrets": lambda key: github.get(key, ""),
        "inputs": lambda key: inputs.get(key, ""), "env": lambda key: env.get(key, ""),
        "steps": lambda key: "success" if key.endswith(".outcome") and key.split(".")[0] in (
            "search_mode_63a", "search_provisioning_63a") else "",
        "github": lambda key: "",
    }
    return truthy(evaluate(condition.removeprefix("${{").removesuffix("}}"), context))


def build_plan(root: Path) -> dict:
    root = Path(root)
    config = load_config(root)
    github, variables = replay_bootstrap(root, config)
    workflows = root / WORKFLOWS
    stages: dict[str, dict] = {}

    common_text = (workflows / "infra-common.yml").read_text(encoding="utf-8-sig")
    raw, calls = stage_calls(common_text, "common-dev")
    inputs = {"deploy_dev": "true", "deploy_stage": "false", "deploy_prod": "false"}
    env = resolved_environment(raw, variables, github, inputs, json_override=False)
    env["network_env"] = env["network_env"] or "dev"  # Initialize derived variables
    for call in calls:
        if should_run(call["if"], env, inputs, github):
            stages[f"common-{call['template']}"] = pipeline_stage(root, call, env, github, inputs, "common")

    dns = private_dns_stage(root)
    hub = hub_stages(root, dns)
    stages = {"bootstrap-seeding-vault": hub.pop("bootstrap-seeding-vault"), **stages}
    stages["hub-private-dns"] = dns
    stages.update(hub)

    project_text = (workflows / "infra-project-phase.yml").read_text(encoding="utf-8-sig")
    raw, calls = stage_calls(project_text, "deploy-project")
    for phase in ("infra", "foundry"):
        inputs = {"environment": "dev", "phase": phase, "deployment_id": "", "config_hash": "",
                  "config_file": "aifactory/variables.json", "use_self_hosted": "false", "runner_label": "",
                  "config_secret": "AIFACTORY_CONFIG_JSON"}
        env = resolved_environment(raw, variables, github, inputs, json_override=True)
        env.update(project_dynamic_env(env))
        seen: dict[str, int] = {}
        for call in calls:
            if (call["template"] == "03-cognitive-services" and phase == "infra"
                    and (root / BICEP / "scripts/search-region-fallback.py").is_file()):
                stages["project-03b-ai-search"] = search_stage(root, env)  # v1.24: Search before 63
            if not should_run(call["if"], env, inputs, github):
                continue
            seen[call["template"]] = seen.get(call["template"], 0) + 1
            suffix = "" if seen[call["template"]] == 1 else f"-pass{seen[call['template']]}"
            stages[f"project-{call['template']}{suffix}"] = pipeline_stage(root, call, env, github, inputs, phase)
            if call["template"] == "09-ai-foundry-2025-v4" and seen[call["template"]] == 1:
                stages["foundry-injection-rbac"] = None  # placeholder keeps pipeline order
    portal = foundry_stages(root, stages)
    for key in ("foundry-injection-rbac", "foundry-cosmos-rbac", "hub-app-gateway"):
        stages[key] = portal[key]

    regions = allowed_regions(root)
    return {
        "bicepVersion": BICEP_VERSION, "tokens": list(TOKENS), "network": NETWORK,
        "regions": regions, "locationShort": {region: cli_regions(root)[region] for region in regions},
        "stages": stages,
        "searchSku": stages["project-03b-ai-search"]["constants"].get("skuAISearchDev", "standard"),
        "privateDnsZones": sorted({zone["name"] for zone in json.loads(dns["templatedJson"]["privateLinksDnsZones"])}),
    }


# --- Regions ---------------------------------------------------------------------------------------

def cli_regions(root: Path) -> dict[str, str]:
    """Region -> short code accepted by aif_collect_answers (the CLI's case table)."""
    script = (root / "bootstrap/lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    regions = {}
    for match in re.finditer(r'AIF_LOCATION="([a-z0-9]+)";?\s*\n?\s*AIF_LOCATION_SHORT="([a-z0-9]+)"', script):
        regions[match[1]] = match[2]
    return regions


def bastion_developer_regions(root: Path) -> list[str]:
    return json.loads((root / BASTION_REGIONS).read_text(encoding="utf-8"))["regions"]


def region_page_regions(root: Path) -> list[str] | None:
    """Section 1 of the release region page (default bootstrap ✅ or ⚠️), when the page exists."""
    page = root / REGION_PAGE
    if not page.is_file():
        return None
    text = page.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)
    section = next(part for part in sections if part.startswith("1"))
    found = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) > 1 and ("✅" in line or "⚠️" in line):
            name = re.sub(r"[`*]", "", cells[0]).replace(" ", "").lower()
            if re.fullmatch(r"[a-z0-9]+", name):
                found.append(name)
    return found


def allowed_regions(root: Path) -> list[str]:
    cli = cli_regions(root)
    allowed = set(cli) & set(bastion_developer_regions(root))
    page = region_page_regions(root)
    if page is not None:
        allowed &= set(page)
    return sorted(allowed)


# --- Form --------------------------------------------------------------------------------------------

def toggle(name: str, label: str, default: bool, tool_tip: str = "") -> dict:
    """Yes/No boolean choice; Microsoft.Common.CheckBox has no defaultValue in the 0.1.2-preview schema."""
    element = {"name": name, "type": "Microsoft.Common.OptionsGroup", "label": label,
               "defaultValue": "Yes" if default else "No",
               "constraints": {"allowedValues": [{"label": "Yes", "value": True}, {"label": "No", "value": False}],
                               "required": True}}
    if tool_tip:
        element["toolTip"] = tool_tip
    return element


def build_form(plan: dict) -> dict:
    regions = plan["regions"]
    basics = [
        {"name": "prefix", "type": "Microsoft.Common.TextBox", "label": "Naming prefix", "defaultValue": "aif",
         "toolTip": "2-16 lowercase letters, digits or hyphens. Resource groups become <prefix>-esml-common-<region>-dev-<nnn>.",
         "constraints": {"required": True, "regex": "^[a-z0-9-]{2,16}$",
                         "validationMessage": "Use 2-16 lowercase letters, digits or hyphens."}},
        {"name": "scalesetNumber", "type": "Microsoft.Common.TextBox", "label": "Scale set number", "defaultValue": "001",
         "constraints": {"required": True, "regex": "^(00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})$",
                         "validationMessage": "Use three digits, 001-999."}},
        {"name": "costCenter", "type": "Microsoft.Common.TextBox", "label": "Cost center tag", "defaultValue": "123456",
         "constraints": {"required": True, "regex": "^[A-Za-z0-9_-]{1,64}$",
                         "validationMessage": "1-64 letters, digits, underscores or hyphens."}},
    ]
    team = [
        {"name": "teamInfo", "type": "Microsoft.Common.InfoBox",
         "options": {"icon": "Info", "text": "The deployment never writes to Microsoft Entra ID. Create the team security group first and paste its object ID."}},
        {"name": "teamGroupObjectId", "type": "Microsoft.Common.TextBox", "label": "Team Entra group object ID",
         "constraints": {"required": True, "regex": "^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$",
                         "validationMessage": "Paste the group's object ID (GUID)."}},
        {"name": "teamGroupName", "type": "Microsoft.Common.TextBox", "label": "Team Entra group display name",
         "defaultValue": "aif-prj001-team",
         "constraints": {"required": True, "regex": "^.{1,120}$", "validationMessage": "1-120 characters."}},
        {"name": "teamMemberEmail", "type": "Microsoft.Common.TextBox", "label": "Technical contact e-mail",
         "constraints": {"required": True, "regex": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", "validationMessage": "Enter an e-mail address."}},
    ]
    services = [
        {"name": "aiSearchLocation", "type": "Microsoft.Common.DropDown", "label": "AI Search region",
         "defaultValue": "Same as the AI Factory region",
         "toolTip": "Pick another region only if AI Search has no capacity in the main region. There is no automatic retry.",
         "constraints": {"allowedValues": [{"label": "Same as the AI Factory region", "value": SAME_REGION}]
                         + [{"label": region, "value": region} for region in regions]}},
        toggle("enableApplicationInsights", "Project Application Insights", True,
               "Workspace-based. Not private-only, because AMPLS is not enabled in Simple Mode."),
    ]
    hub = [
        {"name": "hubInfo", "type": "Microsoft.Common.InfoBox",
         "options": {"icon": "Info", "text": "Private networking is fixed: VNet 172.16.0.0/20, private endpoints, private DNS zones and a DNS Private Resolver inbound endpoint. The options below are billable or take 30-45 minutes and are off by default."}},
        toggle("enableBastion", "Bastion Developer", True, "Free shared Bastion; no admin VM is deployed."),
        toggle("enablePrivateDnsPolicy", "Private DNS initiative", True,
               "Assign Deploy-Private-DNS-Zones to this subscription, as the Simple Mode CLI does."),
        toggle("enableVpnGateway", "Point-to-site VPN Gateway", False,
               "VpnGw1AZ with Entra authentication. Billable; adds 30-45 minutes."),
        {"name": "vpnClientCidr", "type": "Microsoft.Common.TextBox", "label": "VPN client address pool",
         "defaultValue": "172.31.240.0/24", "visible": "[steps('hub').enableVpnGateway]",
         "constraints": {"required": True, "regex": "^([0-9]{1,3}\\.){3}[0-9]{1,3}/(1[6-9]|2[0-9])$",
                         "validationMessage": "IPv4 CIDR /16-/29 outside 172.16.0.0/20."}},
        toggle("enableApplicationGateway", "Private Application Gateway WAF_v2", False,
               "Billable. Needs a hostname, a private HTTPS backend and a Key Vault certificate."),
        {"name": "appGatewayHostname", "type": "Microsoft.Common.TextBox", "label": "Gateway HTTPS hostname",
         "visible": "[steps('hub').enableApplicationGateway]",
         "constraints": {"required": True, "regex": "^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.){2,}[a-z][a-z0-9-]{1,62}$",
                         "validationMessage": "Use a custom FQDN such as ai.contoso.com."}},
        {"name": "appGatewayBackendFqdn", "type": "Microsoft.Common.TextBox", "label": "Private HTTPS backend FQDN",
         "visible": "[steps('hub').enableApplicationGateway]",
         "constraints": {"required": True, "regex": "^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z][a-z0-9-]{1,62}$",
                         "validationMessage": "Use an FQDN, not an IP address or URL."}},
        {"name": "appGatewayCertificateSecretId", "type": "Microsoft.Common.TextBox",
         "label": "Versionless Key Vault certificate secret URI", "visible": "[steps('hub').enableApplicationGateway]",
         "constraints": {"required": True, "regex": "^https://[a-z0-9-]{3,24}\\.vault\\.azure\\.net/secrets/[A-Za-z0-9-]{1,127}$",
                         "validationMessage": "Versionless https://<vault>.vault.azure.net/secrets/<name> URI."}},
        {"name": "appGatewayCertificateVaultId", "type": "Microsoft.Common.TextBox",
         "label": "Certificate Key Vault resource ID", "visible": "[steps('hub').enableApplicationGateway]",
         "constraints": {"required": True, "regex": "^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.KeyVault/vaults/[^/]+$",
                         "validationMessage": "Key Vault resource ID in this subscription."}},
    ]
    outputs = {
        "location": "[location()]", "prefix": "[basics('prefix')]",
        "scalesetNumber": "[basics('scalesetNumber')]", "costCenter": "[basics('costCenter')]",
        "teamGroupObjectId": "[steps('team').teamGroupObjectId]", "teamGroupName": "[steps('team').teamGroupName]",
        "teamMemberEmail": "[steps('team').teamMemberEmail]",
        "aiSearchLocation": "[steps('services').aiSearchLocation]",
        "enableApplicationInsights": "[steps('services').enableApplicationInsights]",
        "enableBastion": "[steps('hub').enableBastion]", "enablePrivateDnsPolicy": "[steps('hub').enablePrivateDnsPolicy]",
        "enableVpnGateway": "[steps('hub').enableVpnGateway]", "vpnClientCidr": "[steps('hub').vpnClientCidr]",
        "enableApplicationGateway": "[steps('hub').enableApplicationGateway]",
        "appGatewayHostname": "[steps('hub').appGatewayHostname]",
        "appGatewayBackendFqdn": "[steps('hub').appGatewayBackendFqdn]",
        "appGatewayCertificateSecretId": "[steps('hub').appGatewayCertificateSecretId]",
        "appGatewayCertificateVaultId": "[steps('hub').appGatewayCertificateVaultId]",
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/0.1.2-preview/CreateUIDefinition.MultiVm.json#",
        "handler": "Microsoft.Azure.CreateUIDef",
        "version": "0.1.2-preview",
        "parameters": {
            "config": {"basics": {
                "description": f"AI Factory {RELEASE} Simple Mode full bootstrap: private networking, standalone topology with a dedicated integrated hub, bootstrap, common and project001 resource groups. Not registered with the Factory API. Requires Owner (or Contributor plus User Access Administrator) on the subscription. Generated by portal/generate_portal.py; do not edit by hand.",
                "location": {"label": "AI Factory region",
                             "toolTip": f"Regions supported by the {RELEASE} Simple Mode CLI and by Bastion Developer.",
                             "allowedValues": regions}}},
            "basics": basics,
            "steps": [
                {"name": "team", "label": "Team", "elements": team},
                {"name": "services", "label": "Services", "elements": services},
                {"name": "hub", "label": "Networking options", "elements": hub},
            ],
            "outputs": outputs,
        },
    }


# --- Outputs -----------------------------------------------------------------------------------------

def dump(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def render_outputs(root: Path, plan: dict) -> dict[str, str]:
    return {
        "generated/stage-parameters.json": dump(plan),
        "form.json": dump(build_form(plan)),
    }


def compiled_sources(root: Path) -> dict[str, Path]:
    sources = {f"stages/{name}.json": root / path for name, path in SOURCE_TEMPLATES.items()}
    sources.update({relative: root / path for relative, path in PORTAL_MODULES.items()})
    sources["azuredeploy.json"] = root / "portal/main.bicep"
    return sources


def compile_templates(root: Path, bicep: str, only: tuple[str, ...] = ()) -> None:
    version = subprocess.run([bicep, "--version"], capture_output=True, text=True, check=True).stdout
    if BICEP_VERSION not in version:
        raise SystemExit(f"Bicep {BICEP_VERSION} is required; found: {version.strip()}")
    for relative, source in compiled_sources(root).items():
        if only and relative not in only:
            continue
        output = root / "portal" / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([bicep, "build", str(source), "--outfile", str(output)], check=True)


def button_url(kind: str) -> str:
    raw = f"https://raw.githubusercontent.com/{PUBLISH_REPOSITORY}/{PUBLISH_BRANCH}/portal/"
    template, form = quote(raw + "azuredeploy.json", safe=""), quote(raw + "form.json", safe="")
    return (f"https://portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/uri/{template}"
            f"/uiFormDefinitionUri/{form}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--bicep", help=f"Bicep {BICEP_VERSION} binary; compiles stages and main before generating")
    parser.add_argument("--check", action="store_true", help="Fail when generated files differ from the working tree")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if args.bicep:
        compile_templates(root, args.bicep, only=tuple(key for key in compiled_sources(root) if key != "azuredeploy.json"))
    plan = build_plan(root)
    outputs = render_outputs(root, plan)
    drift = []
    for relative, content in outputs.items():
        path = root / "portal" / relative
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                drift.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if args.bicep and not args.check:
        compile_templates(root, args.bicep, only=("azuredeploy.json",))
    if drift:
        print("Generated portal files drifted: " + ", ".join(drift), file=sys.stderr)
        return 1
    print(json.dumps({"stages": len(plan["stages"]), "regions": plan["regions"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
