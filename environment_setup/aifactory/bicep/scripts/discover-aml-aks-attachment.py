#!/usr/bin/env python3
"""Read-only preflight: skip only an exact, successful AML AKS attachment."""

import argparse
from pathlib import Path
import re
import sys
from urllib.parse import quote
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personas.cli import AzureCLIError, azure_cli


def same_id(actual, expected):
    return isinstance(actual, str) and actual.lower() == expected.lower()


def get(cli, subscription, resource_id, api_version):
    return cli(
        "rest", "--method", "get", "--url",
        f"https://management.azure.com{quote(resource_id, safe='/')}?api-version={api_version}",
        "--subscription", subscription,
    )


def discover_attachment(cli, *, subscription, resource_group, common_resource_group,
                        project_number, location_suffix, environment, resource_suffix,
                        add_workspace=False, salt="", random_value=""):
    UUID(subscription)
    for value in (resource_group, common_resource_group, project_number, location_suffix, environment):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.()-]+", value):
            raise ValueError("Invalid or unresolved attachment naming input")
    if not re.fullmatch(r"[A-Za-z0-9_-]*", resource_suffix):
        raise ValueError("Invalid resource suffix")

    scope = f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
    naming_id = f"{scope}/providers/Microsoft.Resources/deployments/{('01-naming-' + resource_group)[:64]}"
    # Recover ARM's uniqueString salt from the exact naming deployment produced
    # by earlier phases, never from a fuzzy workspace list or the AKS existence flag.
    naming = get(cli, subscription, naming_id, "2022-09-01")
    if not isinstance(naming, dict) or not same_id(naming.get("id"), naming_id):
        raise ValueError("Missing or mismatched canonical naming deployment")
    properties = naming.get("properties")
    if not isinstance(properties, dict) or properties.get("provisioningState") != "Succeeded":
        raise ValueError("Canonical naming deployment must be Succeeded")
    parameters = properties.get("parameters")
    expected = {
        "subscriptionIdDevTestProd": subscription,
        "commonResourceGroupName": common_resource_group,
        "projectNumber": project_number, "locationSuffix": location_suffix,
        "env": environment, "resourceSuffix": resource_suffix,
    }
    for key, value in expected.items():
        parameter = parameters.get(key) if isinstance(parameters, dict) else None
        if not isinstance(parameter, dict) or parameter.get("value") != value:
            raise ValueError(f"Canonical naming deployment does not match {key}")
    outputs = properties.get("outputs")
    unique = outputs.get("uniqueInAIFenv") if isinstance(outputs, dict) else None
    unique = unique.get("value") if isinstance(unique, dict) else None
    if not isinstance(unique, str) or not re.fullmatch(r"[a-z0-9]{5}", unique):
        raise ValueError("Canonical naming deployment has no valid uniqueInAIFenv output")

    # Match CmnAIfactoryNaming.bicep, including its optional random workspace name.
    random_suffix = ""
    if add_workspace:
        random_salt = salt if len(salt) > 5 else random_value[:10]
        if len(salt) <= 5 and len(random_value) < 10:
            raise ValueError("randomValue must contain at least 10 characters")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", random_salt):
            raise ValueError("Invalid workspace naming salt")
        random_suffix = random_salt.replace("-", "").replace("_", "").lower()[:2]
    workspace_name = f"aml-{project_number}-{location_suffix}-{environment}-{unique}{random_suffix}{resource_suffix}"
    if add_workspace:
        workspace_name = workspace_name[:64]
    aks_name = f"aks{project_number}-{location_suffix}-{environment}"
    workspace_id = f"{scope}/providers/Microsoft.MachineLearningServices/workspaces/{workspace_name}"
    compute_id = f"{workspace_id}/computes/{aks_name}"
    cluster_id = f"{scope}/providers/Microsoft.ContainerService/managedClusters/{aks_name}"
    try:
        compute = get(cli, subscription, compute_id, "2025-07-01-preview")
    except AzureCLIError as error:
        if error.status_code == 404:
            return False
        raise
    if not isinstance(compute, dict) or not same_id(compute.get("id"), compute_id):
        raise ValueError(f"AML attachment response does not match {compute_id}")
    if not same_id(compute.get("type"), "Microsoft.MachineLearningServices/workspaces/computes"):
        raise ValueError("AML attachment response has the wrong resource type")
    properties = compute.get("properties")
    if not isinstance(properties, dict) or properties.get("computeType") != "AKS":
        raise ValueError("Existing AML compute is not an AKS attachment")
    if not same_id(properties.get("resourceId"), cluster_id):
        raise ValueError(f"Existing AML attachment targets a different cluster than {cluster_id}")
    if properties.get("provisioningState") != "Succeeded":
        raise ValueError(f"Existing AML attachment is not Succeeded: {properties.get('provisioningState')}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subscription", "resource-group", "common-resource-group", "project-number",
                 "location-suffix", "environment", "resource-suffix"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--add-workspace", choices=("true", "false"), default="false")
    parser.add_argument("--salt", default="")
    parser.add_argument("--random-value", default="")
    args = vars(parser.parse_args(argv))
    args["add_workspace"] = args["add_workspace"] == "true"
    try:
        exists = discover_attachment(azure_cli, **args)
    except (RuntimeError, ValueError, OSError) as error:
        print(f"AML AKS attachment discovery failed: {error}", file=sys.stderr)
        return 1
    print(str(exists).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
