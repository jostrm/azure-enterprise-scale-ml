#!/usr/bin/env python3
"""Search-only v1.24 provisioning recovery; never moves or deletes an existing service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

SEARCH_SKUS = {
    "free", "basic", "standard", "standard2", "standard3",
    "storage_optimized_l1", "storage_optimized_l2",
}
WRAPPERS = {"DeploymentFailed", "ResourceDeploymentFailure", "DeploymentOperationFailed"}


class CapacityExhausted(RuntimeError):
    """All candidates failed only with verified Search capacity errors."""


def region(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ]{1,49}", value.strip()):
        raise ValueError("Search regions must be Azure region names, not macros, punctuation or objects.")
    return value.strip().replace(" ", "").lower()


def list_input(value, label, limit=3):
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{label}: expected a JSON list or comma-separated names.") from exc
        else:
            value = text.split(",")
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label}: provide a list of at most {limit} unique values.")
    return value


def regions(value):
    result = [region(item) for item in list_input(value, "Search fallback regions", limit=5)]
    if len(result) != len(set(result)):
        raise ValueError("Search fallback regions: duplicate normalized names; remove duplicates.")
    return result


def skus(value):
    values = list_input(value, "Search SKU candidates")
    if any(not isinstance(item, str) or item.strip().lower() not in SEARCH_SKUS for item in values):
        raise ValueError("Search SKU candidates must contain supported Search SKU names.")
    result = [item.strip().lower() for item in values]
    if len(result) != len(set(result)):
        raise ValueError("Search SKU candidates must be unique.")
    return result


def candidates(primary, selected, configured, retry_sku, fallbacks):
    primary = region(primary)
    fallbacks = regions(fallbacks)
    if selected not in SEARCH_SKUS:
        raise ValueError("Selected Search SKU is invalid.")
    remaining = [sku for sku in configured if sku != selected] if retry_sku else []
    ordered_skus = [selected, *remaining]
    if len(ordered_skus) > 3:
        raise ValueError("Selected Search SKU plus remaining candidates must total at most three.")
    ordered_regions = [primary, *[item for item in fallbacks if item != primary]]
    return [(location, sku) for location in ordered_regions for sku in ordered_skus]


def is_capacity(node, depth=0):
    """Only exact, exclusively Search capacity leaves under known ARM wrappers."""
    if not isinstance(node, dict) or depth > 12:
        return False
    target = node.get("target", "")
    if isinstance(target, str) and "/providers/" in target.lower():
        resource_type = target.lower().rsplit("/providers/", 1)[1]
        if not (re.fullmatch(r"microsoft\.resources/deployments/[^/]+", resource_type)
                or re.fullmatch(r"microsoft\.search/searchservices/[^/]+", resource_type)):
            return False
    code = node.get("code")
    if code and code not in WRAPPERS | {"InsufficientResourcesAvailable"}:
        return False
    children = []
    for key in ("error", "innererror", "innerError"):
        if key in node:
            if not isinstance(node[key], dict):
                return False
            children.append(node[key])
    if "details" in node:
        if not isinstance(node["details"], list):
            return False
        children.extend(node["details"])
    if children:
        return all(is_capacity(child, depth + 1) for child in children)
    return code == "InsufficientResourcesAvailable"


def deployment_error(deployment_name, search_id):
    """Resolve truncated ARM deployment wrappers only within the exact Search RG."""
    scope = search_id.rsplit("/providers/", 1)[0]
    seen = set()

    def expand(node, depth=0):
        if not isinstance(node, dict) or depth > 12:
            return node
        expanded = dict(node)
        for key in ("error", "innererror", "innerError"):
            if key in node:
                expanded[key] = expand(node[key], depth + 1)
        if isinstance(node.get("details"), list):
            expanded["details"] = [expand(child, depth + 1) for child in node["details"]]
        target = node.get("target", "")
        has_children = any(node.get(key) for key in ("error", "innererror", "innerError", "details"))
        if node.get("code") in WRAPPERS and not has_children and isinstance(target, str):
            match = re.fullmatch(
                re.escape(scope) + r"/providers/Microsoft\.Resources/deployments/([^/]+)",
                target, re.IGNORECASE,
            )
            if match and target.lower() not in seen:
                seen.add(target.lower())
                _, nested = az("deployment", "group", "show",
                               "--subscription", scope.split("/")[2],
                               "--resource-group", scope.split("/")[4], "--name", match[1],
                               "--query", "properties.error")
                expanded["error"] = expand(nested, depth + 1)
        return expanded

    _, error = az("deployment", "sub", "show", "--name", deployment_name, "--query", "properties.error")
    return expand(error)


def fallback_fingerprint(search_id, environment, sequence):
    payload = [search_id.lower(), environment, sequence]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def existing_candidate(resource):
    state = str(resource.get("properties", {}).get("provisioningState", "")).lower()
    if state != "succeeded":
        raise RuntimeError(
            "Search already exists in a non-Succeeded or unknown provisioning state. "
            "Never delete or relocate it automatically. Inspect the named service and failed deployment; "
            "recover it explicitly in its bound region before retrying."
        )
    location = region(resource.get("location"))
    sku = resource.get("sku", {}).get("name", "").lower()
    if sku not in SEARCH_SKUS:
        raise RuntimeError("Cannot establish the existing Search SKU; refusing to modify it.")
    return location, sku


def az(*arguments, check=True):
    result = subprocess.run([shutil.which("az") or "az", *arguments, "--only-show-errors", "-o", "json"],
                            capture_output=True, text=True)
    if result.returncode:
        if check:
            raise RuntimeError(f"Azure CLI read/deployment failed ({arguments[0]} {arguments[1]}): {result.stderr}")
        return result, None
    try:
        return result, json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Azure CLI returned invalid JSON; refusing to infer resource absence.") from exc


def resource_not_found(message):
    """Only an explicit not-found response from the exact resource GET establishes absence."""
    text = message.strip()
    try:
        payload = json.loads(re.sub(r"^ERROR:\s*", "", text))
    except json.JSONDecodeError:
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


def read_service(resource_id):
    result, resource = az("resource", "show", "--ids", resource_id,
                          "--api-version", "2025-05-01", check=False)
    if result.returncode:
        if resource_not_found(result.stderr):
            return None
        raise RuntimeError(f"Exact Search resource GET failed; refusing to infer absence: {result.stderr}")
    if not isinstance(resource, dict):
        raise RuntimeError("Invalid Search resource read.")
    return resource


def enabled(value):
    if str(value).lower() not in {"true", "false"}:
        raise ValueError("Search enable/retry settings must be true or false, not unresolved macros.")
    return str(value).lower() == "true"


def parameters(network_file):
    mappings = {
        "env": "dev_test_prod", "projectNumber": "project_number_000",
        "location": "admin_location", "locationSuffix": "admin_locationSuffix",
        "commonResourceSuffix": "admin_commonResourceSuffix", "resourceSuffix": "admin_prjResourceSuffix",
        "randomValue": "deployment_random_value", "aifactorySalt10char": "aifactory_salt_random",
        "aifactorySuffixRG": "admin_aifactorySuffixRG", "commonRGNamePrefix": "admin_aifactoryPrefixRG",
        "commonResourceName": "vnetResourceGroupBase", "commonResourceGroup_param": "commonResourceGroup_param",
        "projectPrefix": "projectPrefix", "projectSuffix": "projectSuffix",
        "resolvedManagedIdentityNames": "resolvedManagedIdentityNames", "tagsProject": "tagsProject",
        "addAISearch": "addAISearch", "skuAISearchDev": "skuAISearchDev",
        "skuAISearchStageProd": "skuAISearchStageProd", "semanticSearchTier": "admin_semanticSearchTier",
        "enablePublicGenAIAccess": "enablePublicGenAIAccess",
        "enablePublicAccessWithPerimeter": "enablePublicAccessWithPerimeter",
        "IPwhiteList": "project_IP_whitelist", "cmk": "cmk", "cmkDisableForAISearch": "cmkDisableForAISearch",
    }
    network = json.loads(Path(network_file).read_text(encoding="utf-8-sig"))["parameters"]
    result = {key: network[key] for key in
              ("genaiSubnetId", "aksSubnetId", "acaSubnetId", "aca2SubnetId", "aks2SubnetId") if key in network}
    for key, source in mappings.items():
        value = os.environ.get(source)
        if value is None:
            continue
        if key in {"resolvedManagedIdentityNames", "tagsProject"}:
            value = json.loads(value)
        elif key in {"addAISearch", "enablePublicGenAIAccess", "enablePublicAccessWithPerimeter",
                     "cmk", "cmkDisableForAISearch"}:
            value = enabled(value)
        result[key] = {"value": value}
    return result


def publish(values):
    if os.environ.get("GITHUB_ENV"):
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    else:
        for key, value in values.items():
            print(f"##vso[task.setvariable variable={key}]{value}")


def publish_provisioned(location, sku, provisioned=True, existed=None):
    values = {"AIF_AISEARCH_PROVISIONED_LOCATION": location, "AIF_AISEARCH_PROVISIONED_SKU": sku,
              "AIF_AISEARCH_STATE": "provisioned" if provisioned else "disabled",
              "AIF_AISEARCH_READY": "false", "AIF_AISEARCH_NETWORK_SUCCEEDED": "false",
              "aiSearchProvisioned": str(provisioned).lower(),
              "AIF_AISEARCH_FALLBACK_PENDING": "false"}
    if existed is not None:
        # DNS and CMK gates describe pre-provisioning existence, not the post-create state.
        values["aiSearchExists"] = str(existed).lower()
    publish(values)


def finalize(environment):
    if (os.environ.get("AIF_AISEARCH_STATE") != "provisioned"
            or not enabled(os.environ.get("aiSearchProvisioned", "false"))
            or not enabled(os.environ.get("AIF_AISEARCH_NETWORK_SUCCEEDED", "false"))):
        raise ValueError("Search readiness requires provisional provisioning and actual successful cognitive task 63.")
    location = region(os.environ["AIF_AISEARCH_PROVISIONED_LOCATION"])
    sku = os.environ["AIF_AISEARCH_PROVISIONED_SKU"]
    if sku not in SEARCH_SKUS:
        raise ValueError("Invalid provisioned Search SKU.")
    publish({"aiSearchLocation": location, "effectiveAiSearchLocation": location,
             "effectiveAiSearchSku": sku,
             ("skuAISearchDev" if environment == "dev" else "skuAISearchStageProd"): sku,
             "AIF_AISEARCH_STATE": "ready", "AIF_AISEARCH_READY": "true",
             "AIF_AISEARCH_NETWORK_SUCCEEDED": "true"})


def recover(sequence, existing, attempt, lookup, delay=5):
    if existing:
        actual_location, _ = existing_candidate(existing)
        sequence = [(actual_location, sku) for sku in dict.fromkeys(sku for _, sku in sequence)]
    def validate_binding(partial):
        if partial is not None:
            if not existing:
                raise RuntimeError(
                    "Failed Search attempt left the named service bound to a region. Never delete or move it; "
                    "inspect/recover the service and deployment explicitly before rerunning."
                )
            if existing_candidate(partial)[0] != actual_location:
                raise RuntimeError("Existing Search location changed unexpectedly; refusing further updates.")
        elif existing:
            raise RuntimeError("Previously existing Search is now absent; refusing automatic recreation or relocation.")

    for index, (location, sku) in enumerate(sequence):
        print(f"Search provisioning attempt {index + 1}/{len(sequence)}: location={location}, sku={sku}", flush=True)
        success, error = attempt(location, sku, index)
        if success:
            actual = lookup()
            if not actual or existing_candidate(actual) != (location, sku):
                raise RuntimeError("Search deployment returned success without the expected healthy service.")
            return location, sku
        # Resource reads must never be converted into an absence or retry signal.
        validate_binding(lookup())
        if not is_capacity(error):
            raise RuntimeError("Search deployment failed with a fatal/non-capacity or mixed error; no fallback permitted.")
        if index + 1 < len(sequence):
            time.sleep(delay)
            # ARM can bind a failed creation while the retry delay is running.
            validate_binding(lookup())
    raise CapacityExhausted("Search provisioning exhausted all approved region/SKU candidates; downstream deployment blocked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-parameters")
    parser.add_argument("--template", default=str(Path(__file__).resolve().parents[1] / "esml-genai-1/03b-ai-search.bicep"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true", help="Validate and print candidates without Azure calls.")
    modes.add_argument("--finalize", action="store_true", help="Publish readiness after successful cognitive task 63; local only.")
    modes.add_argument("--select-mode", action="store_true", help="Select normal/regional/disabled CI tasks; local only.")
    parser.add_argument("--provisioning-mode", choices=("normal", "regional"),
                        help="normal tries the primary; regional consumes a verified capacity handoff and tries only fallback regions.")
    args = parser.parse_args()
    environment = os.environ.get("dev_test_prod", "dev")
    if environment not in {"dev", "test", "prod"}:
        raise ValueError("Search deployment environment must be dev, test or prod.")
    if args.finalize:
        finalize(environment)
        return
    suffix = "Dev" if environment == "dev" else "StageProd"
    primary = os.environ.get("aiSearchLocation", "") or os.environ["admin_location"]
    selected = os.environ.get(f"skuAISearch{suffix}", "standard").strip().lower()
    fallback_regions = regions(os.environ.get(f"aiSearchFallbackLocationArray{suffix}", "[]"))
    if region(primary) in fallback_regions:
        print("Search fallback list repeats the primary region; omitting that redundant regional attempt.", file=sys.stderr)
    configured = skus(os.environ.get(f"skuAISearch{suffix}Array", "[]"))
    all_candidates = candidates(primary, selected, configured,
                                enabled(os.environ.get("aisearchRetryCapcityArray", "false")), fallback_regions)
    primary = region(primary)
    primary_candidates = [candidate for candidate in all_candidates if candidate[0] == primary]
    regional_candidates = [candidate for candidate in all_candidates if candidate[0] != primary]
    sequence = regional_candidates if args.provisioning_mode == "regional" else primary_candidates
    if args.plan:
        print(json.dumps(sequence if args.provisioning_mode else all_candidates))
        return
    needs_search = enabled(os.environ.get("enableAISearch", "true")) or (
        enabled(os.environ.get("enableAFoundryCaphost", "false")) and
        enabled(os.environ.get("enableAIFoundry", "false")))
    mode = "normal" if needs_search else "disabled"
    if args.select_mode:
        publish({"AIF_AISEARCH_MODE": mode, "AIF_AISEARCH_STATE": "pending",
                 "AIF_AISEARCH_READY": "false", "AIF_AISEARCH_NETWORK_SUCCEEDED": "false",
                 "aiSearchProvisioned": "false", "AIF_AISEARCH_FALLBACK_PENDING": "false",
                 "AIF_AISEARCH_REGIONAL_FALLBACK_ENABLED": str(bool(regional_candidates)).lower(),
                 "AIF_AISEARCH_FALLBACK_RESOURCE_ID": "", "AIF_AISEARCH_FALLBACK_CONFIG_SHA256": ""})
        if not needs_search:
            publish_provisioned(region(primary), selected, provisioned=False)
        return
    if args.provisioning_mode == "regional" and (
            not needs_search or not regional_candidates
            or os.environ.get("AIF_AISEARCH_FALLBACK_PENDING") != "true"
            or os.environ.get("AIF_AISEARCH_STATE") != "fallback_pending"):
        raise ValueError("Regional provisioning mode requires nonempty fallback regions and a verified primary capacity handoff.")
    if not needs_search:
        print("Search disabled and not required by the Foundry capability host.")
        publish_provisioned(region(primary), selected, provisioned=False)
        return
    if not args.network_parameters:
        parser.error("--network-parameters is required for Search provisioning.")
    params = parameters(args.network_parameters)
    directory = Path(".aifactory-search") / uuid.uuid4().hex
    directory.mkdir(parents=True)
    parameter_file = directory / "parameters.json"
    parameter_file.write_text(json.dumps({"parameters": params}), encoding="utf-8")
    base = ["deployment", "sub", "create", "--location", os.environ["admin_location"],
            "--template-file", args.template, "--parameters", f"@{parameter_file}"]
    name = f"search-{os.environ['project_number_000']}-{environment}-{uuid.uuid4().hex[:10]}"
    try:
        _, context = az(*base, "--name", name + "-context", "--parameters", "contextOnly=true")
        outputs = context["properties"]["outputs"]
        search_id = outputs["aiSearchResourceId"]["value"]
        existing = read_service(search_id)
        fingerprint = fallback_fingerprint(search_id, environment, all_candidates)
        if args.provisioning_mode == "regional":
            if (os.environ.get("AIF_AISEARCH_FALLBACK_RESOURCE_ID", "").lower() != search_id.lower()
                    or os.environ.get("AIF_AISEARCH_FALLBACK_CONFIG_SHA256") != fingerprint):
                raise ValueError("Primary capacity handoff identity/configuration changed; rerun primary provisioning.")
            if existing is not None:
                raise RuntimeError("Search became bound after primary provisioning; refusing regional relocation.")
            publish({"AIF_AISEARCH_FALLBACK_PENDING": "false", "AIF_AISEARCH_STATE": "pending"})
            time.sleep(5)
            if read_service(search_id) is not None:
                raise RuntimeError("Search became bound before regional fallback; refusing regional relocation.")
        else:
            publish({"AIF_AISEARCH_FALLBACK_PENDING": "false"})
        sku_parameter = f"skuAISearch{suffix}"

        def attempt(location, sku, index):
            deployment_name = f"{name}-{index + 1}"
            result, _ = az(*base, "--name", deployment_name, "--parameters",
                           f"aiSearchLocation={location}", f"{sku_parameter}={sku}", check=False)
            if not result.returncode:
                return True, None
            print(result.stderr, file=sys.stderr)
            return False, deployment_error(deployment_name, search_id)

        try:
            location, sku = recover(sequence, existing, attempt, lambda: read_service(search_id))
        except CapacityExhausted:
            if args.provisioning_mode != "normal" or existing is not None or not regional_candidates:
                raise
            publish({"AIF_AISEARCH_FALLBACK_PENDING": "true", "AIF_AISEARCH_STATE": "fallback_pending",
                     "AIF_AISEARCH_FALLBACK_RESOURCE_ID": search_id,
                     "AIF_AISEARCH_FALLBACK_CONFIG_SHA256": fingerprint,
                     "AIF_AISEARCH_READY": "false", "AIF_AISEARCH_NETWORK_SUCCEEDED": "false",
                     "aiSearchProvisioned": "false"})
            print("Primary Search capacity exhausted; regional fallback is pending, not provisioned.", flush=True)
            return
        publish_provisioned(location, sku, existed=existing is not None)
    finally:
        parameter_file.unlink(missing_ok=True)
        directory.rmdir()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print(f"Search provisioning blocked: {exc}", file=sys.stderr)
        sys.exit(1)
