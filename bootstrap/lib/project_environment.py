"""Read-only, exact-project Azure evidence for environment promotion."""

from __future__ import annotations

import re


CONTRACT = "AIFACTORY_ENVIRONMENT_CONTRACT=1"
GUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
SUBSCRIPTION_KEYS = {"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}
AZURE_ENVIRONMENTS = {"dev": "dev", "stage": "test", "prod": "prod"}


def scope(values, environment, project):
    """Match 01-foundation.bicep and the explicit JSON inputs of both pipelines."""
    if environment not in SUBSCRIPTION_KEYS or not isinstance(values, dict):
        raise ValueError("Complete predecessor environment configuration is required.")
    number = values.get("project_number_000")
    if (type(number) not in (str, int) or not re.fullmatch(r"[0-9]{1,3}", str(number))
            or str(number).zfill(3) != project or project == "000"):
        raise ValueError("Predecessor project identity differs from the selected project.")
    subscription, tenant = (str(values.get(key, "")) for key in (SUBSCRIPTION_KEYS[environment], "tenantId"))
    if not re.fullmatch(GUID, subscription) or not re.fullmatch(GUID, tenant):
        raise ValueError(f"Exact {environment} subscription and tenant are required; unknown blocks promotion.")
    parts = {}
    for key, default in (("admin_aifactoryPrefixRG", None), ("admin_aifactorySuffixRG", None),
                         ("admin_locationSuffix", None), ("projectPrefix", "esml-"), ("projectSuffix", "-rg")):
        value = values.get(key, default)
        if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.()-]*", value)
                or (key == "admin_locationSuffix" and not value)):
            raise ValueError(f"Exact predecessor resource-group naming requires a literal {key} in project JSON.")
        parts[key] = value
    # Pipelines serialize the JSON value directly; Bicep does not zero-pad it.
    name = (f"{parts['admin_aifactoryPrefixRG']}{parts['projectPrefix']}project{number}-"
            f"{parts['admin_locationSuffix']}-{AZURE_ENVIRONMENTS[environment]}"
            f"{parts['admin_aifactorySuffixRG']}{parts['projectSuffix']}")
    if len(name) > 90 or name.endswith("."):
        raise ValueError("Configured predecessor resource-group name is invalid.")
    location = values.get("admin_location")
    if location is not None and (not isinstance(location, str) or not re.fullmatch(r"[A-Za-z0-9]+", location)):
        raise ValueError("Predecessor admin_location must be a literal Azure region.")
    return {"subscription": subscription.lower(), "tenant": tenant.lower(),
            "name": name, "location": location.lower() if location else None}


def verify_account(selected, read_json):
    account = read_json(["az", "account", "show", "--subscription", selected["subscription"], "--output", "json"])
    if (not isinstance(account, dict)
            or str(account.get("id", "")).lower() != selected["subscription"]
            or str(account.get("tenantId", "")).lower() != selected["tenant"]
            or ("state" in account and account["state"] != "Enabled")):
        raise ValueError("Cannot verify predecessor Azure subscription and tenant metadata; promotion is blocked.")


def project_exists(selected, read_json):
    verify_account(selected, read_json)
    rows = read_json(["az", "group", "list", "--subscription", selected["subscription"], "--output", "json"])
    if not isinstance(rows, list):
        raise ValueError("Invalid Azure resource-group inventory; predecessor verification failed.")
    matches = []
    expected_id = f"/subscriptions/{selected['subscription']}/resourceGroups/{selected['name']}".casefold()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not isinstance(row.get("id"), str)):
            raise ValueError("Invalid Azure resource-group inventory; predecessor verification failed.")
        if row["name"].casefold() == selected["name"].casefold() and row["id"].casefold() == expected_id:
            matches.append(row)
    if len(matches) > 1:
        raise ValueError("Ambiguous Azure project resource-group response.")
    if not matches:
        return False
    row = matches[0]
    if selected["location"] is not None and str(row.get("location", "")).lower() != selected["location"]:
        raise ValueError("Azure project representation is in a different or unverified region.")
    properties = row.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("Invalid Azure resource-group provisioning state.")
    if "provisioningState" in properties:
        state = properties["provisioningState"]
        if not isinstance(state, str):
            raise ValueError("Invalid Azure resource-group provisioning state.")
        return state.lower() == "succeeded"
    return True


def require_prerequisite(target, project, values_for, read_json):
    if target == "dev":
        return None
    if target not in ("stage", "prod"):
        raise ValueError("Environment must be dev, stage or prod.")
    for source in (("dev",) if target == "stage" else ("dev", "stage")):
        selected = scope(values_for(source), source, project)
        # Failed reads are unknown, not absence: never fall through on auth/network errors.
        if project_exists(selected, read_json):
            print(f"Promotion prerequisite verified: {source} project RG {selected['name']}", flush=True)
            return source
    requirement = "Dev" if target == "stage" else "Dev or Stage"
    raise ValueError(f"{target.title()} requires an existing deployed {requirement} resource group for this same project/factory. "
                     "Local configuration alone does not qualify; no predecessor is deployed automatically.")
