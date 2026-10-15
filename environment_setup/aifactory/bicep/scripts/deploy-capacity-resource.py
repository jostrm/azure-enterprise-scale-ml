#!/usr/bin/env python3
"""Run a capacity CI step; Search regional mode allows at most 18 combinations."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping


@dataclass(frozen=True)
class Service:
    sku: str
    array: str
    retry: str
    state: str
    default_dev: str
    default_stage_prod: str
    default_array: str


SERVICES = {
    "ai-search": Service(
        "skuAISearch", "skuArrayAISearch", "aisearchRetryCapcityArray",
        "AIF_AISEARCH_CAPACITY_NEXT", "basic", "standard", "basic,standard,standard2",
    ),
    "postgresql": Service(
        "skuPostgreSQL", "skuArrayPostgreSQL", "postgreSQLRetryCapacityArray",
        "AIF_POSTGRESQL_CAPACITY_NEXT", "Standard_B1ms", "Standard_B1ms",
        "Standard_B1ms,Standard_B2s,Standard_B2ms",
    ),
    "container-apps": Service(
        "skuContainerApps", "skuArrayContainerApps", "containerAppsRetryCapacityArray",
        "AIF_CONTAINERAPPS_CAPACITY_NEXT", "Consumption", "Consumption", "Consumption,D4,D8",
    ),
}

PARAMETER_ALIASES = {
    "env": ("dev_test_prod",),
    "projectNumber": ("project_number_000",),
    "location": ("admin_location",),
    "locationSuffix": ("admin_locationSuffix",),
    "commonResourceSuffix": ("admin_commonResourceSuffix",),
    "resourceSuffix": ("admin_prjResourceSuffix",),
    "randomValue": ("deployment_random_value",),
    "aifactorySuffixRG": ("admin_aifactorySuffixRG",),
    "commonRGNamePrefix": ("admin_aifactoryPrefixRG",),
    "vnetResourceGroup_param": ("vnetResourceGroup_resolved",),
    "vnetNameFull_param": ("vnetNameFull_resolved",),
    "commonResourceName": ("vnetResourceGroupBase",),
    "aifactorySalt10char": ("aifactory_salt_random",),
    "IPwhiteList": ("project_IP_whitelist",),
    "inputKeyvault": ("admin_bicep_kv_fw",),
    "inputKeyvaultResourcegroup": ("admin_bicep_kv_fw_rg",),
    "inputKeyvaultSubscription": ("admin_bicep_input_keyvault_subscription",),
    "projectServicePrincipleOID_SeedingKeyvaultName": ("project_service_principal_OID_seeding_kv_name",),
    "technicalAdminsObjectID": ("technical_admins_ad_object_id",),
    "technicalAdminsEmail": ("technical_admins_email",),
    "useCommonACR": ("useCommonACR_override",),
    "semanticSearchTier": ("admin_semanticSearchTier", "AISEARCH_SEMANTIC_TIER"),
    "useAdGroups": ("use_ad_groups", "use_groups"),
    "subscriptionIdDevTestProd": ("dev_test_prod_sub_id",),
    "enableBingSearch": ("enableBing",),
    "enableAISearch": ("enableAISearch", "ENABLE_AI_SEARCH"),
    "enableAIFoundry": ("enableAIFoundry", "ENABLE_AI_FOUNDRY"),
    "enablePublicGenAIAccess": ("enablePublicGenAIAccess", "ENABLE_PUBLIC_GENAI_ACCESS"),
}

CAPACITY_ERROR = re.compile(
    r"\b(?:SkuNotAvailable(?:ForSubscription)?|InsufficientCapacity|CapacityUnavailable|"
    r"AllocationFailed|ZonalAllocationFailed|InsufficientResourcesAvailable)\b|"
    r"\bcapacity\s+(?:is\s+)?not\s+available\b|\binsufficient\s+capacity\b",
    re.IGNORECASE,
)
TERMINAL_ERROR = re.compile(
    r"\b(?:AuthorizationFailed|AuthenticationFailed|InvalidAuthenticationToken|"
    r"Unauthorized|Forbidden|AccessDenied|PolicyViolation|RequestDisallowedByPolicy|InvalidTemplate|"
    r"InvalidParameterValue|ResourceNotFound|MissingSubscriptionRegistration|"
    r"QuotaExceeded|QuotaLimitExceeded|SubscriptionIsOverQuota)\b|\b(?:401|403)\b",
    re.IGNORECASE,
)
DEPLOYMENT_WRAPPERS = {
    "deploymentfailed", "resourcedeploymentfailure", "invalidtemplatedeployment",
    "badrequest", "conflict", "internalservererror", "managedenvironmentprovisioningfailed",
}


def is_capacity_failure(output: str) -> bool:
    if TERMINAL_ERROR.search(output):
        return False

    def leaves(value: object) -> list[Mapping]:
        if isinstance(value, list):
            return [leaf for item in value for leaf in leaves(item)]
        if not isinstance(value, dict):
            return []
        children = [
            leaf for name in ("error", "details", "innererror", "innerError")
            for leaf in leaves(value.get(name))
        ]
        code = value.get("code")
        if children and isinstance(code, str) and code.lower() not in DEPLOYMENT_WRAPPERS and not CAPACITY_ERROR.fullmatch(code):
            return [value, *children]
        return children or ([value] if isinstance(value.get("code"), str) else [])

    decoder = json.JSONDecoder()
    errors = []
    consumed_until = 0
    for match in re.finditer(r"[\{\[]", output):
        if match.start() < consumed_until:
            continue
        try:
            value, length = decoder.raw_decode(output[match.start():])
        except json.JSONDecodeError:
            continue
        consumed_until = match.start() + length
        errors.extend(leaves(value))
    if errors:
        return all(
            bool(CAPACITY_ERROR.fullmatch(error["code"])) or (
                error["code"].lower() in DEPLOYMENT_WRAPPERS
                and bool(CAPACITY_ERROR.search(str(error.get("message", ""))))
            )
            for error in errors
        )
    codes = re.findall(r'\bCode\s*[:=]\s*([A-Za-z][A-Za-z0-9]+)', output, re.IGNORECASE)
    if any(code.lower() not in DEPLOYMENT_WRAPPERS and not CAPACITY_ERROR.fullmatch(code) for code in codes):
        return False
    return bool(CAPACITY_ERROR.search(output))


def env_value(environment: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = environment.get(name.upper())
        if value is not None:
            if re.fullmatch(r"\$\([A-Za-z_][A-Za-z0-9_.]*\)", value):
                raise ValueError(f"Unresolved pipeline variable {name}.")
            return value
    return None


def retry_enabled(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise ValueError("Capacity retry switch must be true or false.")


def normalize_capacity_array(configured: str) -> list[str]:
    if not isinstance(configured, str):
        raise ValueError("Capacity array must be a CSV or JSON array string.")
    try:
        parsed = json.loads(configured)
    except json.JSONDecodeError:
        if configured.lstrip().startswith(("[", "{", '"')):
            raise ValueError("Capacity array must be valid JSON containing only strings.") from None
        candidates = configured.split(",")
    else:
        if not isinstance(parsed, list) or any(not isinstance(value, str) for value in parsed):
            raise ValueError("Capacity array must be a JSON list of strings.")
        candidates = parsed
    candidates = [value.strip() for value in candidates]
    if not 1 <= len(candidates) <= 3 or any(
        not re.fullmatch(r"[A-Za-z0-9_]+", value) for value in candidates
    ):
        raise ValueError("Capacity array must contain one to three nonempty SKU names.")
    normalized = [value.lower() for value in candidates]
    if len(set(normalized)) != len(candidates):
        raise ValueError("Capacity array must not repeat a SKU.")
    return candidates


def resolve_search_array(primary: str | None = None, legacy: str | None = None) -> str:
    # Older pipeline bindings supply an empty alias when it is not configured.
    if legacy == "":
        legacy = None
    primary_values = None if primary is None else normalize_capacity_array(primary)
    legacy_values = None if legacy is None else normalize_capacity_array(legacy)
    defaults = normalize_capacity_array(SERVICES["ai-search"].default_array)
    if primary_values is None:
        chosen = defaults if legacy_values is None else legacy_values
    elif legacy_values is None:
        chosen = primary_values
    else:
        primary_normalized = [value.lower() for value in primary_values]
        legacy_normalized = [value.lower() for value in legacy_values]
        if primary_normalized == legacy_normalized or legacy_normalized == defaults:
            chosen = primary_values
        elif primary_normalized == defaults:
            chosen = legacy_values
        else:
            raise ValueError(
                "Conflicting AI Search capacity arrays: skuArrayAISearchDev/StageProd and "
                "skuAISearchDevArray/StageProdArray contain different nondefault ordered SKUs."
            )
    return ",".join(chosen)


def candidate_order(selected: str, configured: str, retry: str) -> list[str]:
    selected = selected.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", selected):
        raise ValueError("Selected capacity SKU must be a nonempty SKU name.")
    if not retry_enabled(retry):
        return [selected]
    candidates = normalize_capacity_array(configured)
    normalized = [value.lower() for value in candidates]
    if selected.lower() not in normalized:
        raise ValueError(f"Selected SKU {selected} is not in its capacity array.")
    return [selected] + [
        value for value in candidates if value.lower() != selected.lower()
    ]


def normalize_search_location(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ]{1,49}", value.strip()):
        raise ValueError("Search location must be an Azure region name, without macros or punctuation.")
    return value.strip().replace(" ", "").lower()


def normalize_search_regions(configured: object) -> list[str]:
    if isinstance(configured, str):
        if not configured.strip():
            return []
        try:
            configured = json.loads(configured)
        except json.JSONDecodeError:
            if configured.lstrip().startswith(("[", "{", '"')):
                raise ValueError("Search fallback locations must be valid JSON or CSV.") from None
            configured = configured.split(",")
    if not isinstance(configured, list) or len(configured) > 5:
        raise ValueError("Search fallback locations must be a list of at most five region names.")
    regions = [normalize_search_location(value) for value in configured]
    if len(set(regions)) != len(regions):
        raise ValueError("Search fallback locations must not repeat a region.")
    return regions


def search_regions_from_environment(environment: Mapping) -> list[str]:
    target = env_value(environment, "dev_test_prod", "env")
    if target not in ("dev", "test", "prod"):
        raise ValueError("Deployment environment must be dev, test, or prod.")
    return normalize_search_regions(env_value(
        environment, "aiSearchFallbackLocationArray" + ("Dev" if target == "dev" else "StageProd"),
        "AI_SEARCH_FALLBACK_LOCATION_ARRAY_" + ("DEV" if target == "dev" else "STAGEPROD"),
    ) or "")


def search_candidate_order(primary: str, regions: object, selected: str,
                           configured: str, retry: str) -> list[tuple[str, str]]:
    primary = normalize_search_location(primary)
    locations = [primary] + [region for region in normalize_search_regions(regions) if region != primary]
    skus = candidate_order(selected, configured, retry)
    return [(location, sku.lower()) for location in locations for sku in skus]


def is_search_capacity_failure(output: str, resource_id: str) -> bool:
    # A Search deployment also owns private networking. Never relocate Search for
    # an allocation failure on a downstream endpoint/shared link/other resource.
    if re.search(r"Microsoft\.Network/|private[\s_-]*endpoint|shared[\s_-]*private[\s_-]*link",
                 output, re.IGNORECASE):
        return False
    for target in re.findall(r'"target"\s*:\s*"([^"]+)"', output, re.IGNORECASE):
        if "/providers/" in target.lower():
            target_type = target.lower().rsplit("/providers/", 1)[-1]
            search_target = (target.lower() == resource_id.lower()) if resource_id else (
                target_type.startswith("microsoft.search/searchservices/") and len(target_type.split("/")) == 3
            )
            if not target_type.startswith("microsoft.resources/deployments/") and not search_target:
                return False
    return is_capacity_failure(output)


def execute_deployment(args: argparse.Namespace, az: str, parameters: dict,
                       *, identity_only: bool = False) -> subprocess.CompletedProcess:
    # Keep generated parameters inside the caller's worktree, not an OS temp
    # directory, and remove them even on errors. Never log parameter values.
    with tempfile.TemporaryDirectory(prefix=".aif-capacity-", dir=Path.cwd()) as directory:
        parameter_path = Path(directory) / "parameters.json"
        parameter_path.write_text(json.dumps(parameters), encoding="utf-8")
        return subprocess.run(
            [az, "deployment", "sub", "create",
             "--name", args.deployment_name[:55] + "-identity" if identity_only else args.deployment_name,
             "--subscription", args.subscription, "--location", args.location,
             "--template-file", args.template_file, "--parameters", "@" + str(parameter_path),
             "--only-show-errors"],
            capture_output=True, text=True, check=False,
        )


def search_identity(args: argparse.Namespace, az: str, parameters: dict) -> str:
    identity = {**parameters, "parameters": {**parameters["parameters"],
                                           "capacityIdentityOnly": {"value": True}}}
    result = execute_deployment(args, az, identity, identity_only=True)
    if result.returncode:
        raise ValueError("Search identity resolution failed; no capacity deployment attempted. " + result.stderr)
    resource_id = json.loads(result.stdout)["properties"]["outputs"]["aiSearchResourceId"]["value"]
    if not isinstance(resource_id, str) or not re.fullmatch(
            r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Search/searchServices/[^/]+",
            resource_id, re.IGNORECASE):
        raise ValueError("Search identity resolution returned an invalid resource ID.")
    return resource_id


def resource_not_found(message: str) -> bool:
    text = message.strip()
    try:
        payload = json.loads(re.sub(r"^ERROR:\s*", "", text))
    except json.JSONDecodeError:
        # Never recover a code fragment from a truncated or mixed JSON response.
        if re.search(r"[\{\}\[\]]", text):
            return False
        codes = [code for match in re.findall(
            r"(?m)^\s*(?:ERROR:\s*)?(?:\(([A-Za-z][A-Za-z0-9]+)\)|Code:\s*([A-Za-z][A-Za-z0-9]+))", text
        ) for code in match if code]
        statuses = re.findall(r"\b(?:HTTP(?:/\d(?:\.\d)?)?\s+|[Ss]tatus(?:\s+[Cc]ode|_code)?\s*[:=]\s*)(\d{3})\b", text)
    else:
        if not isinstance(payload, dict):
            return False
        codes, statuses = [], []

        def visit(node):
            if isinstance(node, dict):
                if node.get("code") is not None:
                    codes.append(str(node["code"]))
                for key, value in node.items():
                    if key in {"status", "statusCode", "status_code", "httpStatusCode"}:
                        statuses.append(str(value))
                    elif isinstance(value, (dict, list)):
                        visit(value)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(payload)
    return bool(codes) and set(codes) == {"ResourceNotFound"} and (not statuses or set(statuses) == {"404"})


def read_search(az: str, resource_id: str) -> dict | None:
    result = subprocess.run(
        [az, "rest", "--method", "get", "--url",
         f"https://management.azure.com{resource_id}?api-version=2025-05-01", "--only-show-errors"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        error = result.stdout + "\n" + result.stderr
        # Only an explicit resource-not-found response proves absence. Denials,
        # timeouts, missing subscriptions and malformed responses are terminal.
        non_absence_error = re.sub("ResourceNotFound", "", error, flags=re.IGNORECASE)
        if resource_not_found(error) and not TERMINAL_ERROR.search(non_absence_error):
            return None
        raise ValueError("Cannot read the named Search service; refusing regional fallback. " + error)
    service = json.loads(result.stdout)
    if not isinstance(service, dict) or not isinstance(service.get("properties"), dict):
        raise ValueError("Search resource read returned an invalid service response.")
    normalize_search_location(service.get("location"))
    actual_id = service.get("id", resource_id)
    if not isinstance(actual_id, str) or actual_id.lower() != resource_id.lower():
        raise ValueError("Search resource read returned a different resource identity.")
    return service


def run_search_regions(args: argparse.Namespace, az: str, template: dict, dynamic: dict,
                       environment: Mapping, overrides: dict, regions: list[str],
                       selected: str, configured: str, retry: str, suffix: str) -> int:
    primary = env_value(environment, "aiSearchLocation", "AI_SEARCH_LOCATION") or args.location
    candidates = search_candidate_order(primary, regions, selected, configured, retry)
    if normalize_search_location(primary) in regions:
        print("Primary Search region is also in the fallback list; omitting its redundant regional attempt.", flush=True)
    initial_parameters = deployment_parameters(template, dynamic, environment, overrides)
    resource_id = search_identity(args, az, initial_parameters)
    existing = read_search(az, resource_id)
    bound_location = normalize_search_location(existing["location"]) if existing else None
    if existing:
        actual = normalize_search_location(existing["location"])
        print(f"Existing Search service retained in {actual}; relocation is disabled.", flush=True)
        candidates = search_candidate_order(actual, [], selected, configured, retry)
    for index, (location, sku) in enumerate(candidates):
        if index:
            print("Previous capacity attempt failed; waiting 240 seconds before retry.", flush=True)
            time.sleep(240)
            current = read_search(az, resource_id)
            if current:
                bound_location = normalize_search_location(current["location"])
                state = str(current["properties"].get("provisioningState", "")).lower()
                if bound_location != location or (not existing and state not in ("failed", "canceled")):
                    print(f"Search name is now bound to {bound_location} ({state or 'unknown state'}). "
                          "Safe stop: inspect the service and failed deployment; never delete indexed services "
                          "to enable fallback.", file=sys.stderr)
                    return deployment.returncode
        print(f"ai-search: attempt {index + 1}/{len(candidates)}, region {location}, SKU {sku}.", flush=True)
        attempt_overrides = {**overrides, "aiSearchLocation": location, "skuAISearch" + suffix: sku}
        parameters = deployment_parameters(template, dynamic, environment, attempt_overrides)
        deployment = execute_deployment(args, az, parameters)
        if deployment.stdout:
            print(deployment.stdout, end="", flush=True)
        if deployment.stderr:
            print(deployment.stderr, file=sys.stderr, end="", flush=True)
        if deployment.returncode == 0:
            publish(args.provider, SERVICES["ai-search"].state, "0")
            publish(args.provider, "skuAISearch" + suffix, sku)
            publish(args.provider, "aiSearchLocation", location)
            return 0
        publish(args.provider, SERVICES["ai-search"].state, "failed")
        if not is_search_capacity_failure(deployment.stdout + "\n" + deployment.stderr, resource_id):
            return deployment.returncode
        bound = existing or read_search(az, resource_id)
        if bound:
            actual = normalize_search_location(bound["location"])
            bound_location = actual
            state = str(bound["properties"].get("provisioningState", "")).lower()
            moving = index + 1 < len(candidates) and candidates[index + 1][0] != actual
            if moving or (not existing and state not in ("failed", "canceled")):
                print(f"Search name is bound to {actual} ({state or 'unknown state'}). "
                      "Safe stop: inspect the named service and failed deployment, then rerun in its actual region; "
                      "never delete an existing indexed service to enable fallback.", file=sys.stderr)
                return deployment.returncode
        if bound_location and index + 1 < len(candidates) and candidates[index + 1][0] != bound_location:
            print(f"Search name was observed bound to {bound_location}; refusing relocation even if a later read "
                  "reports absence. Inspect the deployment and rerun safely; never delete indexed services.",
                  file=sys.stderr)
            return deployment.returncode
        if index + 1 == len(candidates):
            print("AI Search capacity candidates exhausted; no downstream deployment is allowed.", file=sys.stderr)
            if bound_location:
                print(f"The Search name remains bound to {bound_location}; inspect the failed deployment and rerun "
                      "in that region. Never delete an indexed service to enable fallback.", file=sys.stderr)
            return deployment.returncode
    raise ValueError("No Search capacity candidates were configured.")


def postgresql_tier(sku: str) -> str:
    if re.fullmatch(r"Standard_B[0-9]+[A-Za-z0-9_]*", sku, re.IGNORECASE):
        return "Burstable"
    if re.fullmatch(r"Standard_D[0-9]+[A-Za-z0-9_]*", sku, re.IGNORECASE):
        return "GeneralPurpose"
    if re.fullmatch(r"Standard_E[0-9]+[A-Za-z0-9_]*", sku, re.IGNORECASE):
        return "MemoryOptimized"
    raise ValueError(f"Cannot determine PostgreSQL tier for SKU {sku}.")


def parameter_value(name: str, value: str, declaration: Mapping) -> object:
    kind = declaration["type"].lower()
    if kind == "bool":
        if value.lower() not in ("true", "false"):
            raise ValueError(f"Parameter {name} must be true or false.")
        return value.lower() == "true"
    if kind == "int":
        return int(value)
    if kind in ("object", "array"):
        parsed = json.loads(value)
        if not isinstance(parsed, dict if kind == "object" else list):
            raise ValueError(f"Parameter {name} must be a JSON {kind}.")
        return parsed
    if kind in ("string", "securestring"):
        return value
    raise ValueError(f"Unsupported parameter type {kind} for {name}.")


def deployment_parameters(
    template: Mapping, dynamic: Mapping, environment: Mapping[str, str],
    overrides: Mapping[str, str],
) -> dict:
    declarations = template["parameters"]
    values = {
        key: value for key, value in dynamic["parameters"].items() if key in declarations
    }
    for name, declaration in declarations.items():
        value = env_value(environment, *PARAMETER_ALIASES.get(name, ()), name)
        if value is not None:
            values[name] = {"value": parameter_value(name, value, declaration)}
        if name in overrides:
            values[name] = {"value": parameter_value(name, overrides[name], declaration)}
        if name not in values and "defaultValue" not in declaration:
            raise ValueError(f"Required deployment parameter {name} is missing.")
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": values,
    }


def publish(provider: str, name: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError(f"CI state {name} must be a single line.")
    if provider == "ado":
        escaped = value.replace("%", "%AZP25").replace(";", "%3B").replace("]", "%5D")
        print(f"##vso[task.setvariable variable={name}]{escaped}", flush=True)
    else:
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"{name}={value}\n")


def run_attempt(args: argparse.Namespace) -> int:
    service = SERVICES[args.service]
    environment = {name.upper(): value for name, value in os.environ.items()}
    if args.service == "ai-search":
        enabled = env_value(environment, "enableAISearch", "ENABLE_AI_SEARCH")
        private_foundry = (
            retry_enabled(env_value(environment, "enableAIFoundry", "ENABLE_AI_FOUNDRY") or "false")
            and not retry_enabled(env_value(environment, "enablePublicGenAIAccess", "ENABLE_PUBLIC_GENAI_ACCESS") or "false")
        )
        if enabled is not None and not retry_enabled(enabled) and not private_foundry:
            print("ai-search is disabled; no capacity deployment is needed.", flush=True)
            return 0
    target_env = env_value(environment, "dev_test_prod", "env")
    if target_env not in ("dev", "test", "prod"):
        raise ValueError("Deployment environment must be dev, test, or prod.")
    suffix = "Dev" if target_env == "dev" else "StageProd"
    selected = env_value(environment, service.sku + suffix)
    if selected is None:
        selected = service.default_dev if target_env == "dev" else service.default_stage_prod
    retry = env_value(environment, service.retry)
    retry = "true" if retry is None else retry
    configured = None
    if args.service == "ai-search":
        if retry_enabled(retry):
            public_suffix = "DEV" if target_env == "dev" else "STAGE_PROD"
            configured = resolve_search_array(
                env_value(environment, service.array + suffix,
                          "SKU_ARRAY_AISEARCH_" + public_suffix.replace("_", "")),
                env_value(environment, service.sku + suffix + "Array",
                          "SKU_AI_SEARCH_" + public_suffix + "_ARRAY"),
            )
    else:
        configured = env_value(environment, service.array + suffix)
    candidates = candidate_order(
        selected, service.default_array if configured is None else configured,
        retry,
    )
    regions = []
    if args.service == "ai-search":
        regions = search_regions_from_environment(environment)
        if regions and args.attempt != 1:
            raise ValueError("Search regional mode runs only in its first CI step; later attempts are not armed.")
    if args.attempt > len(candidates):
        raise ValueError("Attempt exceeds the configured capacity candidates.")
    if args.attempt > 1 and env_value(environment, service.state) != str(args.attempt):
        raise ValueError("Capacity attempt is not armed by a previous capacity failure.")
    candidate = candidates[args.attempt - 1]
    if args.service == "ai-search":
        candidate = candidate.lower()
    if args.service == "container-apps" and candidate not in ("Consumption", "D4", "D8"):
        raise ValueError("Container Apps SKU must be Consumption, D4, or D8.")
    overrides = {
        "env": target_env, "location": args.location, service.sku + suffix: candidate,
        "subscriptionIdDevTestProd": args.subscription,
    }
    if args.service == "ai-search":
        overrides["capacityIdentityOnly"] = "false"
    if args.service == "postgresql":
        tier_name = "skuTierPostgreSQL" + suffix
        tier = postgresql_tier(candidate)
        configured_tier = env_value(environment, tier_name)
        if args.attempt == 1 and configured_tier is not None and configured_tier != tier:
            raise ValueError(f"Selected PostgreSQL SKU {candidate} requires tier {tier}.")
        overrides[tier_name] = tier
    if args.provider == "github" and not os.environ.get("GITHUB_ENV"):
        raise ValueError("GITHUB_ENV is required for GitHub capacity attempt state.")
    az = shutil.which("az")
    if az is None:
        raise ValueError("Azure CLI is required for a capacity deployment.")

    build = subprocess.run(
        [az, "bicep", "build", "--file", args.template_file, "--stdout"],
        capture_output=True, text=True, check=False,
    )
    if build.stderr:
        print(build.stderr, file=sys.stderr, end="", flush=True)
    if build.returncode:
        return build.returncode
    template = json.loads(build.stdout)
    dynamic = json.loads(Path(args.parameters_file).read_text(encoding="utf-8-sig"))
    if regions:
        return run_search_regions(args, az, template, dynamic, environment, overrides, regions,
                                  selected, service.default_array if configured is None else configured,
                                  retry, suffix)
    parameters = deployment_parameters(template, dynamic, environment, overrides)
    search_id = None
    if args.service == "ai-search":
        search_id = search_identity(args, az, parameters)
        existing = read_search(az, search_id)
        primary = env_value(environment, "aiSearchLocation", "AI_SEARCH_LOCATION") or args.location
        overrides["aiSearchLocation"] = normalize_search_location(existing["location"] if existing else primary)
        parameters = deployment_parameters(template, dynamic, environment, overrides)
    if args.attempt > 1:
        print("Previous capacity attempt failed; waiting 240 seconds before retry.", flush=True)
        time.sleep(240)
    print(f"{args.service}: attempt {args.attempt}/{len(candidates)}, SKU {candidate}.", flush=True)
    deployment = execute_deployment(args, az, parameters)
    if deployment.stdout:
        print(deployment.stdout, end="", flush=True)
    if deployment.stderr:
        print(deployment.stderr, file=sys.stderr, end="", flush=True)
    if deployment.returncode == 0:
        publish(args.provider, service.state, "0")
        publish(args.provider, service.sku + suffix, candidate)
        if args.service == "ai-search":
            publish(args.provider, "aiSearchLocation", overrides["aiSearchLocation"])
        if args.service == "postgresql":
            publish(args.provider, "skuTierPostgreSQL" + suffix, overrides["skuTierPostgreSQL" + suffix])
        return 0
    output = deployment.stdout + "\n" + deployment.stderr
    capacity_failure = is_search_capacity_failure(output, search_id) if search_id else is_capacity_failure(output)
    if capacity_failure and args.attempt < len(candidates):
        print(f"Capacity unavailable for {candidate}; next configured SKU will be attempted.", flush=True)
        publish(args.provider, service.state, str(args.attempt + 1))
        return 0
    publish(args.provider, service.state, "failed")
    print(f"{args.service} deployment failed; no further capacity attempt is allowed.", file=sys.stderr)
    return deployment.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    if "--publish-search-region-gate" in sys.argv[1:]:
        parser.add_argument("--publish-search-region-gate", action="store_true", required=True)
        parser.add_argument("--provider", choices=("ado", "github"), required=True)
        args = parser.parse_args()
        try:
            regions = search_regions_from_environment({name.upper(): value for name, value in os.environ.items()})
            publish(args.provider, "AIF_AISEARCH_REGION_FALLBACK_ENABLED", str(bool(regions)).lower())
            return 0
        except (OSError, ValueError, KeyError) as error:
            print(f"AI Search region configuration error: {error}", file=sys.stderr)
            return 2
    if "--classify-search-error" in sys.argv[1:]:
        parser.add_argument("--classify-search-error", type=Path, required=True)
        parser.add_argument("--resource-id", default="")
        args = parser.parse_args()
        try:
            return 0 if is_search_capacity_failure(
                args.classify_search_error.read_text(encoding="utf-8-sig"), args.resource_id,
            ) else 1
        except (OSError, ValueError) as error:
            print(f"AI Search error classification failed: {error}", file=sys.stderr)
            return 2
    if "--resolve-search-regions" in sys.argv[1:]:
        parser.add_argument("--resolve-search-regions", action="store_true", required=True)
        parser.add_argument("--primary", required=True)
        parser.add_argument("--regions", default="", help="Up to five fallback regions (JSON or CSV); empty disables fallback.")
        args = parser.parse_args()
        try:
            primary = normalize_search_location(args.primary)
            regions = normalize_search_regions(args.regions)
            print("\n".join([primary] + [region for region in regions if region != primary]))
            return 0
        except ValueError as error:
            print(f"AI Search region configuration error: {error}", file=sys.stderr)
            return 2
    if "--resolve-search-array" in sys.argv[1:]:
        parser.add_argument("--resolve-search-array", action="store_true", required=True)
        parser.add_argument("--primary")
        parser.add_argument("--legacy")
        args = parser.parse_args()
        try:
            print(resolve_search_array(args.primary, args.legacy))
            return 0
        except ValueError as error:
            print(f"AI Search capacity array configuration error: {error}", file=sys.stderr)
            return 2
    parser.add_argument("--service", choices=SERVICES, required=True)
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3), required=True,
                        help="CI SKU step; Search regional retries complete inside step 1.")
    parser.add_argument("--provider", choices=("ado", "github"), required=True)
    parser.add_argument("--template-file", required=True)
    parser.add_argument("--parameters-file", required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--deployment-name", required=True)
    args = parser.parse_args()
    try:
        return run_attempt(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"Capacity deployment configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
