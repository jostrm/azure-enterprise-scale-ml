"""Read-only Python SDK example: resolve one factory/scale/project before calling scoped APIs."""

import argparse
import json
import sys


def exactly_one(items, label):
    matches = list(items)
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {label}; found {len(matches)}. Refresh and select explicitly.")
    return matches[0]


def inspect_factory(client, folder, factory_key, environment, suffix, project_number=None,
                    *, parameters=False, auth_status=False):
    catalog = client.catalog_list(folder)
    if type(catalog.get("contract_version")) is not int or catalog["contract_version"] != 1:
        raise ValueError("Catalog contract v1 is required.")
    if catalog.get("mode") != "catalog":
        raise ValueError("This example requires an explicitly configured Azure Factory register, not a legacy root.")
    factory = exactly_one((item for item in catalog["factories"] if item["key"] == factory_key), "factory key")
    scale = exactly_one(
        (item for item in factory["scale_sets"] if item["environment"] == environment and item["suffix"] == suffix),
        "environment/scale-set suffix",
    )
    project = None
    if project_number:
        project = exactly_one(
            (item for item in factory["projects"] if item["number"] == project_number), "project number",
        )
        exactly_one(
            (item for item in project["placements"]
             if item["environment"] == environment and item["scale_set_id"] == scale["id"]),
            "project placement in the selected scale set",
        )
    result = {
        "folder": folder,
        "catalog_revision": catalog["revision"],
        "factory_id": factory["id"],
        "factory_key": factory["key"],
        "scale_set_id": scale["id"],
        "environment": scale["environment"],
        "suffix": scale["suffix"],
        "tenant_id": scale["tenant_id"],
        "subscription_id": scale["subscription_id"],
        "project_id": project["id"] if project else None,
    }
    if auth_status:
        result["authentication"] = client.auth_status(
            aifactory_folder=folder, factory_id=factory["id"], scale_set_id=scale["id"],
            expected_tenant_id=scale["tenant_id"], expected_subscription_id=scale["subscription_id"],
        )
    if parameters:
        result["parameters"] = client.catalog_parameters(
            folder, factory["id"], scale["id"], project["id"] if project else None,
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--factory-key", required=True)
    parser.add_argument("--environment", choices=("dev", "stage", "prod"), required=True)
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--project-number")
    parser.add_argument("--parameters", action="store_true")
    parser.add_argument("--auth-status", action="store_true")
    args = parser.parse_args()
    try:
        from azurefactory import APIError, AzureFactoryClient
    except ImportError:
        print("Install the sibling azurefactory-cli package first; see the readme.", file=sys.stderr)
        return 2
    try:
        result = inspect_factory(
            AzureFactoryClient(), args.folder, args.factory_key, args.environment, args.suffix,
            args.project_number, parameters=args.parameters, auth_status=args.auth_status,
        )
        print(json.dumps(result, indent=2, allow_nan=False))
    except APIError as error:
        print(str(error), file=sys.stderr)
        return error.exit_code
    except (ValueError, KeyError, TypeError) as error:
        print(f"Cannot inspect the selected scope: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
