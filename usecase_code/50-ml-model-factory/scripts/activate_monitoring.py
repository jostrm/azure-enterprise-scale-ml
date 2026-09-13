"""Idempotent control-plane prerequisites for explicitly approved monitoring.

Preview is the default. This does not change networking, register untested models,
or create schedules without observations. Run from an identity allowed to create
the named container, credentialless datastore, role definition and assignments.
"""

import argparse
import json
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_model_factory.config import load_json, validate_runtime, write_json
from ml_model_factory.project import azure_cli
from ml_model_factory.tags import scope_tags


ACTIONS = [
    "Microsoft.MachineLearningServices/workspaces/read",
    "Microsoft.MachineLearningServices/workspaces/models/read",
    "Microsoft.MachineLearningServices/workspaces/models/versions/read",
    "Microsoft.MachineLearningServices/workspaces/models/versions/write",
]
DATA_CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
DATA_READER = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
MONITORING_ROLE = "custom:model-monitoring-writer"


def plan(runtime: dict, storage_account: str, container: str, datastore: str) -> dict:
    from ml_model_factory.lake import LakeLayout

    validate_runtime(runtime)
    scope = scope_tags(runtime, require=True)
    if scope["environment"] != "dev":
        raise ValueError("This activation entry point is limited to an explicitly approved Dev pilot")
    layout = LakeLayout.from_config({
        **scope, "use_case": "monitoring", "dataset": "observations", "data_version": "v1",
        "snapshot_id": "baseline", "run_id": "activation",
        "storage": {"account_url": f"https://{storage_account}.blob.core.windows.net",
                    "container": container, "datastore": datastore},
    })
    account = azure_cli("account", "show", "--subscription", runtime["subscription_id"])
    if account["tenantId"] != runtime["tenant_id"]:
        raise ValueError("Authenticated subscription tenant differs from the target")
    group = f"/subscriptions/{runtime['subscription_id']}/resourceGroups/{runtime['resource_group']}"
    storage_id = group + "/providers/Microsoft.Storage/storageAccounts/" + storage_account
    workspace_id = group + "/providers/Microsoft.MachineLearningServices/workspaces/" + runtime["workspace_name"]
    workspace = azure_cli("ml", "workspace", "show", "--subscription", runtime["subscription_id"],
                          "--resource-group", runtime["resource_group"], "--name", runtime["workspace_name"])
    compute = azure_cli("ml", "compute", "show", "--subscription", runtime["subscription_id"],
                        "--resource-group", runtime["resource_group"], "--workspace-name", runtime["workspace_name"],
                        "--name", runtime["compute"])
    storage = azure_cli("storage", "account", "show", "--subscription", runtime["subscription_id"],
                        "--resource-group", runtime["resource_group"], "--name", storage_account)
    if storage.get("publicNetworkAccess") != "Disabled":
        raise ValueError("Expected the project's existing private storage account; no network changes are performed")
    compute_identity = compute.get("identity", {}).get("principal_id")
    workspace_identity = workspace.get("identity", {}).get("principal_id")
    if not compute_identity or not workspace_identity or compute.get("provisioning_state") != "Succeeded":
        raise ValueError("Ready compute and its existing managed identities are required")
    container_id = storage_id + "/blobServices/default/containers/" + layout.container
    return {
        "scope": scope, "subscription": runtime["subscription_id"], "storage_account": storage_account,
        "container": container, "container_id": container_id, "datastore": datastore,
        "workspace_id": workspace_id, "compute_principal": compute_identity,
        "workspace_principal": workspace_identity,
        "role_definition": {
            "Name": f"AI Factory ML monitoring writer - {scope['aifactory']}-p{scope['project']}-{scope['environment']}",
            "IsCustom": True,
            "Description": "Read and update Azure ML model-version monitoring metadata; no job, endpoint, deletion or role-assignment rights.",
            "Actions": ACTIONS, "NotActions": [], "DataActions": [], "NotDataActions": [],
            "AssignableScopes": [group],
        },
        "assignments": [
            {"principal": compute_identity, "role": DATA_CONTRIBUTOR, "scope": container_id},
            {"principal": workspace_identity, "role": DATA_READER, "scope": container_id},
            {"principal": compute_identity, "role": MONITORING_ROLE, "scope": workspace_id},
        ],
        "network_changes": False, "models_registered": False, "schedules_enabled": False,
    }


def execute(runtime: dict, planned: dict, output: Path) -> dict:
    import tempfile

    sub = runtime["subscription_id"]
    containers = azure_cli("storage", "container-rm", "list", "--subscription", sub,
                           "--storage-account", planned["storage_account"], "--resource-group", runtime["resource_group"])
    existing = next((item for item in containers if item["name"] == planned["container"]), None)
    if existing and existing.get("publicAccess") not in (None, "None"):
        raise ValueError("An existing public container cannot be adopted as private monitoring storage")
    if not existing:
        azure_cli("storage", "container-rm", "create", "--subscription", sub, "--resource-group", runtime["resource_group"],
                  "--storage-account", planned["storage_account"], "--name", planned["container"], "--public-access", "off")
    roles = azure_cli("role", "definition", "list", "--subscription", sub, "--name", planned["role_definition"]["Name"])
    if roles:
        permissions = roles[0].get("permissions", [])
        if (len(roles) != 1 or len(permissions) != 1 or set(permissions[0].get("actions", [])) != set(ACTIONS)
                or permissions[0].get("notActions") or permissions[0].get("dataActions")
                or permissions[0].get("notDataActions")
                or roles[0].get("assignableScopes") != planned["role_definition"]["AssignableScopes"]):
            raise ValueError("Existing monitoring role differs; refusing to widen or replace it")
        actual_role_id = roles[0]["id"]
    else:
        with tempfile.TemporaryDirectory(prefix="monitoring-role-") as directory:
            path = Path(directory) / "role.json"
            write_json(path, planned["role_definition"])
            created = azure_cli("role", "definition", "create", "--subscription", sub, "--role-definition", str(path))
            actual_role_id = created["id"]
    if not actual_role_id.startswith(f"/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/"):
        raise ValueError("Created/reused role does not belong to the approved subscription")
    for original in planned["assignments"]:
        assignment = {**original, "role": actual_role_id if original["role"] == MONITORING_ROLE else original["role"]}
        name = str(uuid5(NAMESPACE_URL, assignment["scope"].lower() + assignment["principal"] + assignment["role"].lower()))
        rows = azure_cli("role", "assignment", "list", "--subscription", sub, "--scope", assignment["scope"])
        if any(row.get("principalId") == assignment["principal"] and
               row.get("roleDefinitionId", "").lower().endswith(assignment["role"].split("/")[-1].lower())
               and row.get("scope", "").lower() == assignment["scope"].lower() for row in rows):
            continue
        azure_cli("role", "assignment", "create", "--subscription", sub, "--assignee-object-id", assignment["principal"],
                  "--assignee-principal-type", "ServicePrincipal", "--role", assignment["role"], "--scope", assignment["scope"],
                  "--name", name)
    target = ("--subscription", sub, "--resource-group", runtime["resource_group"],
              "--workspace-name", runtime["workspace_name"])
    stores = [item for item in azure_cli("ml", "datastore", "list", *target) if item["name"] == planned["datastore"]]
    if stores:
        existing = stores[0]
        credentials = existing.get("credentials")
        if (existing.get("account_name") != planned["storage_account"] or
                existing.get("container_name") != planned["container"] or
                credentials is not None and str(credentials.get("type", "")).lower() != "none"):
            raise ValueError("Existing datastore target or credentials differ; refusing to overwrite")
    else:
        with tempfile.TemporaryDirectory(prefix="monitoring-datastore-") as directory:
            path = Path(directory) / "datastore.json"
            write_json(path, {
                "type": "azure_blob", "name": planned["datastore"], "account_name": planned["storage_account"],
                "container_name": planned["container"],
                "description": "Private project model monitoring data; managed-identity access, no stored credentials",
            })
            azure_cli("ml", "datastore", "create", "--file", str(path), *target)
    updated = dict(runtime)
    updated["datastore"] = planned["datastore"]
    write_json(output, updated)
    return {"container": planned["container"], "datastore": planned["datastore"],
            "role_definition_id": actual_role_id,
            "runtime": str(output), "model_registration_pending": True, "schedules_enabled": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--container", default="ml-model-factory")
    parser.add_argument("--datastore", default="ml_model_factory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    runtime = load_json(args.runtime)
    planned = plan(runtime, args.storage_account, args.container, args.datastore)
    result = execute(runtime, planned, args.output) if args.execute else {"preview": True, **planned}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
