"""Fail-closed, group-only human access to project/environment ADLS paths.

AI developers read source data; trusted ingestion identities own and write it.
Writers own newly created paths in ADLS and can change their ACLs. Read-only
human ACLs deliberately avoid promising isolation that writable ACLs cannot give.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
import importlib.util
from pathlib import Path
from uuid import UUID

from .policy import lake_authorized_path

_UTILITY = Path(__file__).resolve().parent.parent / "esml-util" / "project_lake_access.py"
_SPEC = importlib.util.spec_from_file_location("persona_project_lake_access", _UTILITY)
_LEGACY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LEGACY)
Lake = _LEGACY.Lake
AI_DEVELOPER = "persona213"
CORE = {"persona200", "persona201"}
_DATA_OPERATIONS = (
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/manageOwnership/action",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/modifyPermissions/action",
)
_CONTROL_OPERATIONS = (
    "Microsoft.Storage/storageAccounts/write",
    "Microsoft.Storage/storageAccounts/listKeys/action",
    "Microsoft.Storage/storageAccounts/listAccountSas/action",
    "Microsoft.Storage/storageAccounts/listServiceSas/action",
    "Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action",
    "Microsoft.Authorization/roleAssignments/write",
)


def _ids(values):
    if not isinstance(values, list):
        raise ValueError("Lake adoption identity lists must be arrays of object IDs")
    return {str(UUID(value)) for value in values}


def allows(permissions, operation, *, data=False):
    """NotActions subtract only from the containing permission block, not others."""
    actions, exclusions = ("dataActions", "notDataActions") if data else ("actions", "notActions")
    return any(
        any(fnmatchcase(operation.lower(), pattern.lower()) for pattern in block.get(actions, []))
        and not any(fnmatchcase(operation.lower(), pattern.lower()) for pattern in block.get(exclusions, []))
        for block in permissions
    )


def _role_blockers(assignments, role_definitions, trusted):
    blockers = []
    for assignment in assignments:
        principal = str(assignment.get("principalId", "")).lower()
        if principal in trusted:
            continue
        definition = role_definitions[assignment["roleDefinitionId"].lower()]
        permissions = definition.get("permissions", definition.get("properties", {}).get("permissions"))
        if not isinstance(permissions, list):
            raise ValueError("Cannot inspect lake role permissions; privileged access review is required")
        if any(allows(permissions, operation, data=True) for operation in _DATA_OPERATIONS) or any(
            allows(permissions, operation) for operation in _CONTROL_OPERATIONS
        ):
            blockers.append(
                f"Lake bypass-capable assignment {assignment['id']} for {principal}; "
                "remove through reviewed migration or explicitly identify a trusted lake administrator. "
                "Conditional roles also require review; ACLs are not a deny."
            )
    return blockers


def _workload_blockers(manifest, trusted, cli):
    parts = manifest["project_scope"].strip("/").split("/")
    subscription_id, resource_group = parts[1], parts[3]
    resources = cli("resource", "list", "--resource-group", resource_group, "--subscription", subscription_id)
    blockers = []
    for resource in resources:
        resource_id = resource["id"]
        if not resource_id.lower().startswith(manifest["project_scope"].lower() + "/providers/"):
            raise ValueError("Workload inventory returned a resource outside the project")
        if resource.get("type", "").lower() == "microsoft.managedidentity/userassignedidentities":
            continue
        detail = cli("resource", "show", "--ids", resource_id, "--subscription", subscription_id)
        identity = detail.get("identity") or {}
        principals = {str(identity.get("principalId", "")).lower()}
        for identity_id in (identity.get("userAssignedIdentities") or {}):
            managed = cli("identity", "show", "--ids", identity_id, "--subscription", subscription_id)
            principals.add(str(managed["principalId"]).lower())
        if principals & trusted:
            blockers.append(
                f"{resource_id}: a trusted lake identity is attached to a project-controllable resource; "
                "isolate ingestion/storage administration from ordinary project deployers"
            )
    return blockers


def _entries(acl):
    result = {}
    for item in acl.split(","):
        key, permission = item.rsplit(":", 1)
        if key in result or len(permission) != 3:
            raise ValueError("Malformed or duplicate ADLS ACL entry")
        result[key] = permission
    return result


def _acl_plan(headers, *, path, inside, ancestor, ai_group, ordinary, legacy, approved, trusted):
    current = _entries(headers["x-ms-acl"])
    desired = dict(current)
    blockers = []
    owner, owning_group = headers.get("x-ms-owner", "").lower(), headers.get("x-ms-group", "").lower()
    if inside and owner not in trusted:
        blockers.append(f"{path}: owner {owner or '(unknown)'} can change ACLs; a trusted ingestion/admin identity must own source data")
    if not inside and owner in ordinary | legacy:
        blockers.append(f"{path or '/'}: a project/legacy principal owns an out-of-scope path")
    for key, permission in current.items():
        default = key.startswith("default:")
        local = key.removeprefix("default:")
        parts = local.split(":")
        if len(parts) != 2:
            raise ValueError(f"Malformed ADLS ACL at {path or '/'}")
        kind, principal = parts
        principal = principal.lower()
        if permission == "---" or kind not in ("user", "group", "other"):
            continue
        if kind == "user" and not principal:
            continue
        if kind == "other":
            if inside or any(bit in permission for bit in "rw"):
                blockers.append(f"{path or '/'}: {key} grants public-to-authenticated-user ACL access; remediate explicitly")
            continue
        if not principal:
            if inside and owning_group not in trusted:
                blockers.append(f"{path}: owning-group access must be removed or bound to a trusted ingestion/admin identity")
            elif owning_group in ordinary | legacy and not (ancestor and permission == "--x" and not default):
                blockers.append(f"{path or '/'}: owning group bypasses the persona boundary")
            continue
        if principal in trusted:
            continue
        if principal in legacy and inside and principal in approved:
            del desired[key]
            continue
        if inside:
            if principal != ai_group:
                blockers.append(f"{path}: unrelated ACL principal {principal}; remove with reviewed migration before enabling personas")
        elif principal in ordinary | legacy:
            if not (ancestor and principal == ai_group and permission == "--x" and not default):
                blockers.append(f"{path or '/'}: project/legacy ACL outside authorized environment subtree; no automatic shared-path removal")
    if inside or ancestor:
        if blockers:
            return None, blockers
        is_directory = headers.get("x-ms-resource-type", "directory") == "directory"
        permission = ("r-x" if is_directory else "r--") if inside else "--x"
        raw = ",".join(f"{key}:{value}" for key, value in desired.items())
        try:
            raw = _LEGACY.merge_acl(
                raw, [("group", ai_group, permission)], directory=is_directory, defaults=inside
            )
        except ValueError as error:
            return None, [f"{path or '/'}: {error}"]
        return raw, []
    return None, blockers


def provision_lake(manifest, groups, execute=False, cli=None):
    """Audit the complete filesystem before mutating only the authorized subtree.

    Graph membership/credential/workload review is a separate administrator
    responsibility; this checks actual direct/inherited ARM grants and ACLs.
    No temporary data-owner role, data RBAC grant, or shared-key fallback exists.
    """
    if type(execute) is not bool:
        raise ValueError("execute must be boolean")
    if not manifest.get("lake"):
        raise ValueError("groups-v1 project access requires an explicit HNS lake configuration")
    cli = cli or _LEGACY.cli
    ai_group = str(UUID(groups[AI_DEVELOPER]))
    if len(set(groups.values())) != len(groups):
        raise ValueError("Each persona must resolve to a distinct group")
    source = manifest["lake"]
    forbidden = {"users", "groups", "managed_identities", "readers", "temporary_data_owner", "execute"}
    if forbidden.intersection(source):
        raise ValueError("Persona lake inputs cannot supply principals, execution flags or temporary privileges")
    config, _ = _LEGACY.validate({**source, "groups": [ai_group]})
    max_paths = config.get("max_audit_paths", 100000)
    if type(max_paths) is not int or not 1 <= max_paths <= 1000000:
        raise ValueError("max_audit_paths must be an integer from 1 to 1000000")
    for field in ("tenant_id", "project", "environment"):
        if config[field] != manifest[field]:
            raise ValueError(f"Lake {field} must match the persona manifest")
    account_scope = (
        f"/subscriptions/{config['subscription_id']}/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.Storage/storageAccounts/{config['storage_account']}"
    )
    expected_rg = account_scope.rsplit("/providers/", 1)[0].lower()
    if expected_rg not in {manifest["common_scope"].lower(), manifest["project_scope"].lower()}:
        raise ValueError("Persona lake must be in the explicit common or project resource group")
    adoption = manifest.get("adoption", {})
    core_ids = {str(UUID(groups[key])) for key in CORE}
    trusted = core_ids | _ids(adoption.get("trusted_lake_admin_principal_ids", []))
    ordinary = {str(UUID(value)) for key, value in groups.items() if key not in CORE}
    legacy = _ids(adoption.get("legacy_principal_ids", []))
    approved = _ids(adoption.get("approved_acl_principal_ids", []))
    if not approved <= legacy or trusted & ordinary:
        raise ValueError("Only reviewed legacy ACL principals may be removed; ordinary groups cannot be trusted lake administrators")
    subscription = cli("account", "show", "--subscription", config["subscription_id"])
    if str(subscription["tenantId"]).lower() != config["tenant_id"]:
        raise ValueError("Lake subscription tenant does not match manifest")
    storage = cli("storage", "account", "show", "--name", config["storage_account"],
                  "--resource-group", config["resource_group"], "--subscription", config["subscription_id"])
    if storage["id"].lower() != account_scope.lower():
        raise ValueError("Storage resource ID does not match the explicit lake scope")
    if not storage.get("isHnsEnabled"):
        raise ValueError("Persona lake requires an existing HNS-enabled account")
    if storage.get("allowSharedKeyAccess") is not False or storage.get("allowBlobPublicAccess") is not False:
        raise ValueError("Disable lake Shared Key and public blob access explicitly before enabling personas; rotate/revoke historical credentials and SAS")
    scope = account_scope + f"/blobServices/default/containers/{config['filesystem']}"
    assignments = cli("role", "assignment", "list", "--scope", scope, "--include-inherited",
                      "--fill-principal-name", "false", "--fill-role-definition-name", "false",
                      "--subscription", config["subscription_id"])
    definitions = {}
    for assignment in assignments:
        role_id = assignment["roleDefinitionId"].lower()
        if role_id not in definitions:
            matches = cli("role", "definition", "list", "--name", role_id.rsplit("/", 1)[1],
                          "--scope", scope, "--subscription", config["subscription_id"])
            if len(matches) != 1:
                raise ValueError(f"Cannot unambiguously resolve lake role definition {role_id}")
            definitions[role_id] = matches[0]
    deferred = set(adoption.get("approved_role_assignment_ids", [])) if not execute else set()
    deferred_removals = {
        assignment["id"] for assignment in assignments
        if assignment["id"] in deferred and str(assignment.get("principalId", "")).lower() in legacy
        and any(assignment.get("scope", "").lower() == owned.lower()
                or assignment.get("scope", "").lower().startswith(owned.lower() + "/")
                for owned in (manifest["common_scope"], manifest["project_scope"]))
    }
    blockers = _role_blockers(
        [assignment for assignment in assignments if assignment["id"] not in deferred_removals],
        definitions, trusted,
    )
    blockers.extend(_workload_blockers(manifest, trusted, cli))
    leaf = lake_authorized_path(config)
    segments = leaf.split("/")
    ancestors = {"", *("/".join(segments[:index]) for index in range(1, len(segments)))}
    lake = Lake(config, cli_runner=cli)
    paths = {"": True}
    for path, directory in lake.paths(""):
        if (not isinstance(path, str) or not path or "\\" in path
                or any(part in ("", ".", "..") for part in path.split("/"))
                or any(ord(char) < 32 for char in path) or type(directory) is not bool):
            raise ValueError("Lake inventory contains an invalid path or resource type")
        if path in paths:
            raise ValueError("Lake inventory contains duplicate paths; retry a stable inventory")
        if len(paths) >= max_paths:
            raise ValueError("Lake audit path limit exceeded before any ACL writes; partition the source lake or explicitly review a larger max_audit_paths")
        if (path in ancestors or path == leaf) and not directory:
            raise ValueError(f"Authorized lake path or ancestor is a file, not a directory: {path}")
        paths[path] = directory
    planned, acl_removals = [], []
    for path, directory in paths.items():
        headers = lake.acl(path)
        actual_type = headers.get("x-ms-resource-type")
        if actual_type and actual_type != ("directory" if directory else "file"):
            raise ValueError(f"Lake path type changed during audit: {path or '/'}")
        headers["x-ms-resource-type"] = "directory" if directory else "file"
        inside = path == leaf or path.startswith(leaf + "/")
        desired, errors = _acl_plan(
            headers, path=path, inside=inside, ancestor=path in ancestors, ai_group=ai_group,
            ordinary=ordinary, legacy=legacy, approved=approved, trusted=trusted,
        )
        blockers.extend(errors)
        if desired is not None and set(desired.split(",")) != set(headers["x-ms-acl"].split(",")):
            planned.append({"path": path, "acl": desired, "etag": headers["ETag"]})
            removed = set(_entries(headers["x-ms-acl"])) - set(_entries(desired))
            if removed:
                acl_removals.append({"path": path, "entries": sorted(removed)})
    if blockers:
        raise ValueError("Persona lake adoption blocked:\n" + "\n".join(sorted(set(blockers))))
    missing = ["/".join(segments[:index]) for index in range(1, len(segments) + 1)
               if "/".join(segments[:index]) not in paths]
    report = {
        "state": "preview", "scope": scope, "authorized_path": leaf, "group": ai_group,
        "human_access": "read-only; trusted ingestion identities own/write data",
        "create_directories": missing, "acl_updates": [item["path"] or "/" for item in planned],
        "data_role_assignments": [], "audited_paths": len(paths),
        "requires_prior_role_removal": sorted(deferred_removals),
        "legacy_acl_removals": acl_removals,
        "remaining_review": "Transitive group memberships, user-owned files, workload execution/identities, credentials and SAS must be reviewed by the operator; no Graph privileges are granted to pipelines.",
    }
    if not execute:
        return report
    if acl_removals and adoption.get("execute_migration") is not True:
        raise ValueError("Legacy ACL removal requires adoption.execute_migration=true in addition to explicit principal approvals")
    for path in missing:
        lake.mkdir(path)
        headers = lake.acl(path)
        # New paths are owned by the authenticated provisioning identity. Require
        # it in the reviewed admin inventory rather than implicitly trusting it.
        desired, errors = _acl_plan(
            headers, path=path, inside=path == leaf, ancestor=path in ancestors, ai_group=ai_group,
            ordinary=ordinary, legacy=legacy, approved=approved, trusted=trusted,
        )
        if errors:
            raise ValueError("New lake directory requires ACL remediation: " + "; ".join(errors))
        planned.append({"path": path, "acl": desired, "etag": headers["ETag"]})
    for item in planned:
        lake.request("PATCH", item["path"], {"action": "setAccessControl"},
                     {"x-ms-acl": item["acl"], "If-Match": item["etag"], "Content-Length": "0"})
        if set(lake.acl(item["path"])["x-ms-acl"].split(",")) != set(item["acl"].split(",")):
            raise ValueError(f"Persona ACL verification failed at {item['path'] or '/'}")
    report["state"] = "complete"
    return report
