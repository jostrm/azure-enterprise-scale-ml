"""Explicit common/project data storage selection; never provisions or migrates data."""

from copy import deepcopy
import re
from urllib.parse import urlsplit


FLAG = "use_common_datalake_storage"
PROFILES = "storage_targets"


def _profile(value: dict, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"storage_targets.{name} must be an explicit storage profile")
    unknown = set(value) - {"account_name", "account_url", "resource_group", "container", "datastore"}
    if unknown:
        raise ValueError(f"Unsupported storage profile fields: {sorted(unknown)}")
    result = dict(value)
    account = result.get("account_name")
    if not isinstance(account, str) or not re.fullmatch(r"[a-z0-9]{3,24}", account):
        raise ValueError(f"storage_targets.{name}.account_name must name an existing account")
    url = result.get("account_url", f"https://{account}.blob.core.windows.net")
    parsed = urlsplit(url)
    if (not re.fullmatch(rf"https://{account}\.blob\.core\.(windows\.net|usgovcloudapi\.net|chinacloudapi\.cn)/?", url)
            or parsed.query or parsed.fragment):
        raise ValueError("Storage account URL must match account_name and contain no credentials")
    result["account_url"] = url.rstrip("/")
    for key in ("resource_group", "container", "datastore"):
        item = result.get(key)
        pattern = (r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]" if key == "container"
                   else r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}")
        if not isinstance(item, str) or not re.fullmatch(pattern, item) or (key == "container" and "--" in item):
            raise ValueError(f"storage_targets.{name}.{key} must be explicitly configured")
    return result


def selection(value: dict) -> tuple[bool, dict[str, dict]] | None:
    contexts = [value]
    for name in ("runtime", "lake"):
        if name in value:
            if not isinstance(value[name], dict):
                raise ValueError(f"{name} must be a JSON object")
            contexts.append(value[name])
    flags = [context[FLAG] for context in contexts if FLAG in context]
    if not flags:
        return None
    if any(type(flag) is not bool for flag in flags):
        raise ValueError(f"{FLAG} must be a JSON boolean, not a string or number")
    if len(set(flags)) != 1:
        raise ValueError("Conflicting common/project storage choices in configuration")
    profiles = [context[PROFILES] for context in contexts if PROFILES in context]
    if not profiles:
        raise ValueError("Storage selection requires one consistent storage_targets object")
    normalized = []
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) - {"common", "project"}:
            raise ValueError("storage_targets accepts only common and project profiles")
        normalized.append({name: _profile(item, name) for name, item in profile.items()})
    if any(profile != normalized[0] for profile in normalized):
        raise ValueError("Storage selection requires one consistent storage_targets object")
    chosen = "common" if flags[0] else "project"
    if chosen not in profiles[0]:
        raise ValueError(f"No {chosen} storage target is configured; no fallback is permitted")
    resolved = normalized[0]
    if len(resolved) == 2:
        left, right = resolved["common"], resolved["project"]
        if left["account_name"] == right["account_name"] or left["datastore"] == right["datastore"]:
            raise ValueError("Common and project profiles need distinct accounts and datastore bindings")
    return flags[0], resolved


def selected_profile(value: dict) -> dict | None:
    result = selection(value)
    return result[1]["common" if result[0] else "project"] if result else None


def resolve_location(location: str, value: dict) -> str:
    """Retarget only a known storage profile, keeping its complete object key."""
    selected = selection(value)
    if selected is None or not isinstance(location, str):
        return location
    chosen = selected[1]["common" if selected[0] else "project"]
    if "?" in location or "#" in location:
        raise ValueError("Selected lake inputs must not contain SAS/query credentials or fragments")
    for profile in selected[1].values():
        host = urlsplit(profile["account_url"]).netloc
        prefixes = (
            (f"azureml://datastores/{profile['datastore']}/paths/", f"azureml://datastores/{chosen['datastore']}/paths/"),
            (profile["account_url"] + "/" + profile["container"] + "/", chosen["account_url"] + "/" + chosen["container"] + "/"),
            (f"wasbs://{profile['container']}@{host}/", f"wasbs://{chosen['container']}@{urlsplit(chosen['account_url']).netloc}/"),
            (f"abfss://{profile['container']}@{host.replace('.blob.', '.dfs.')}/",
             f"abfss://{chosen['container']}@{urlsplit(chosen['account_url']).netloc.replace('.blob.', '.dfs.')}/"),
        )
        for old, new in prefixes:
            if location.startswith(old):
                return new + location[len(old):]
    if location.startswith(("azureml:", "https://", "http://", "wasb:", "wasbs:", "abfs:", "abfss:")):
        raise ValueError("Storage-selected data URI does not match a configured profile; use a selected datastore path or input_path")
    return location


def resolve_storage_selection(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Storage configuration must be a JSON object")
    result = deepcopy(value)
    choice = selection(result)
    if choice is None:
        return result
    common, profiles = choice
    profile = profiles["common" if common else "project"]
    runtime = result.get("runtime", result)
    expected_group = runtime.get("common_resource_group") if common else runtime.get("resource_group")
    expected_group = expected_group or (result.get("common_resource_group") if common else result.get("resource_group"))
    if expected_group and profile["resource_group"].casefold() != expected_group.casefold():
        raise ValueError("Selected storage resource group differs from the common/project scope")
    if common and runtime.get("resource_group") and profile["resource_group"].casefold() == runtime["resource_group"].casefold():
        raise ValueError("Common lake must be in the common resource group, not the project resource group")
    result[FLAG], result[PROFILES] = common, profiles
    storage = result.get("storage", {})
    if not isinstance(storage, dict):
        raise ValueError("storage must be an object")
    result["storage"] = {**storage, **profile}
    result["datastore"] = profile["datastore"]
    if "input_path" in result:
        from .lake import relative_key
        key = relative_key(result["input_path"].rstrip("/"))
        result["input_data"] = f"azureml://datastores/{profile['datastore']}/paths/{key}" + ("/" if result["input_path"].endswith("/") else "")
    for key in ("input_data", "input_uri"):
        if key in result:
            result[key] = resolve_location(result[key], result)
    if "lake" in result:
        lake = result["lake"]
        if not isinstance(lake.get("storage", {}), dict):
            raise ValueError("lake.storage must be an object")
        lake["storage"] = {**lake.get("storage", {}), **profile}
    if "runtime" in result:
        runtime = result["runtime"]
        runtime["datastore"] = profile["datastore"]
        runtime["storage"] = deepcopy(result["storage"])
        for key in (FLAG, PROFILES):
            runtime[key] = deepcopy(result[key])
        for key in ("input_data", "input_uri"):
            if key in runtime:
                runtime[key] = resolve_location(runtime[key], result)
    return result


def verify_datastore(storage: dict, actual) -> None:
    def field(key):
        return actual.get(key) if isinstance(actual, dict) else getattr(actual, key, None)
    if (field("account_name") != storage["account_name"]
            or (field("container_name") or field("filesystem")) != storage["container"]
            or field("type") not in ("azure_blob", "azure_data_lake_gen2")):
        raise ValueError("Existing AML datastore does not bind the selected storage account/container; provision the correct binding explicitly")


def validate_job_storage(document: dict, runtime: dict) -> None:
    resolved = resolve_storage_selection(runtime)
    if selection(resolved) is None:
        return
    selected = resolved["storage"]
    cloud = ("azureml:", "https://", "http://", "wasb://", "wasbs://", "abfs://", "abfss://")
    def visit(value, data_inputs=False):
        if isinstance(value, dict):
            if value.get("type") in ("string", "integer", "number", "boolean"):
                return
            for key, item in value.items():
                if key in ("path", "uri", "default_datastore", "training_data", "validation_data", "test_data") and isinstance(item, str):
                    if key == "default_datastore":
                        if item.removeprefix("azureml:") != selected["datastore"]:
                            raise ValueError("Rendered job uses a different default datastore; render again after switching storage")
                    elif item.startswith(cloud):
                        model_type = value.get("type", value.get("jobInputType"))
                        if model_type in ("mlflow_model", "custom_model", "triton_model") and (
                            re.fullmatch(r"azureml:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", item)
                            or (item.startswith("azureml://") and "/models/" in item and "/versions/" in item)
                        ):
                            continue
                        if resolve_location(item, resolved) != item:
                            raise ValueError("Rendered job still targets the other storage profile; render again")
                else:
                    visit(item, data_inputs or key == "inputs")
        elif isinstance(value, list):
            for item in value:
                visit(item, data_inputs)
        elif data_inputs and isinstance(value, str) and value.startswith(cloud):
            if resolve_location(value, resolved) != value:
                raise ValueError("Rendered job still targets the other storage profile; render again")
    visit(document)
