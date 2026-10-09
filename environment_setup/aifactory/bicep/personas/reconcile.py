"""Read-only RBAC inventory, ownership checks and explicitly reviewed migration."""

from fnmatch import fnmatchcase

from .cli import AzureCLIError
from .policy import arm_scope_parts, guid, within


def role_guid(value):
    if not isinstance(value, str):
        raise ValueError("Missing roleDefinitionId")
    return guid(value.rsplit("/", 1)[-1], "roleDefinitionId")


def assignment_content(item):
    properties = item.get("properties", item)
    scope = properties.get("scope")
    if not isinstance(scope, str) or not scope.startswith("/"):
        raise ValueError("Role assignment is missing its scope")
    identity = item.get("id", properties.get("id"))
    if not isinstance(identity, str):
        raise ValueError("Role assignment is missing its ID")
    name = guid(identity.rsplit("/", 1)[-1], "role assignment ID")
    if identity.lower() != f"{scope.rstrip('/')}/providers/Microsoft.Authorization/roleAssignments/{name}".lower():
        raise ValueError("Role-assignment ID does not match its scope")
    return {
        "id": identity.lower(), "scope": scope.lower(),
        "principalId": guid(properties.get("principalId"), "role principal"),
        "principalType": properties.get("principalType"),
        "roleDefinitionId": role_guid(properties.get("roleDefinitionId")),
        "condition": properties.get("condition") or None,
        "conditionVersion": properties.get("conditionVersion") or None,
        "delegatedManagedIdentityResourceId": properties.get("delegatedManagedIdentityResourceId") or None,
        "description": properties.get("description") or "",
    }


def inventory(cli, scopes):
    assignments = {}
    scopes = sorted(set(scopes))

    def collect(result, include_inherited=False):
        if not isinstance(result, list):
            raise ValueError("Azure role assignment list did not return an array")
        for item in result:
            current = assignment_content(item)
            if not include_inherited and not any(
                within(current["scope"], scope) or within(scope, current["scope"]) for scope in scopes
            ):
                continue
            existing = assignments.get(current["id"])
            if existing is not None and existing != current:
                raise ValueError("Role assignment changed during inventory; retry the review")
            assignments[current["id"]] = current

    flags = ("--fill-principal-name", "false", "--fill-role-definition-name", "false")
    # --all and --scope are mutually exclusive. atScope() (the CLI's --scope
    # implementation) excludes descendants, so both inventories are necessary.
    for subscription in sorted({arm_scope_parts(scope)[0] for scope in scopes}):
        collect(cli("role", "assignment", "list", "--all", *flags, "--subscription", subscription))
    for scope in scopes:
        subscription, _ = arm_scope_parts(scope)
        collect(cli("role", "assignment", "list", "--scope", scope, "--include-inherited",
                    *flags, "--subscription", subscription), include_inherited=True)
    return list(assignments.values())


def equivalent(existing, desired):
    return (
        existing["principalId"] == desired["principalId"]
        and existing["scope"] == desired["scope"]
        and existing["roleDefinitionId"] == role_guid(desired["roleDefinitionId"])
        and not existing["condition"]
        and not existing["delegatedManagedIdentityResourceId"]
    )


def audit_assignments(manifest, scope, groups, desired, existing):
    blockers, removals, receipt = [], [], []
    approvals = set(manifest["adoption"]["approved_role_assignment_ids"])
    legacy = set(manifest["adoption"]["legacy_principal_ids"])
    if legacy & set(groups.values()):
        blockers.append("Legacy principals must not reuse any seeded persona group")
    relevant = set(groups.values()) | legacy
    by_id = {item["id"]: item for item in existing}
    for target in desired:
        collision = by_id.get(target["id"].lower())
        if collision and not equivalent(collision, target):
            blockers.append(f"Deterministic assignment ID collision: {target['id']}")
        matches = [item for item in existing if equivalent(item, target)]
        owned = [item for item in matches
                 if item["id"] == target["id"].lower() and item["description"] == target["description"]]
        adopted = [item for item in matches if item not in owned]
        receipt.append({
            **target, "status": "owned" if owned else "adopted" if adopted else "create",
            "existing_assignment_ids": [item["id"] for item in matches],
            "owned_assignment_ids": [item["id"] for item in owned],
            "adopted_assignment_ids": [item["id"] for item in adopted],
        })
    for item in existing:
        if item["principalId"] not in relevant:
            continue
        intended = any(
            target["principalId"] == item["principalId"]
            and role_guid(target["roleDefinitionId"]) == item["roleDefinitionId"]
            and within(item["scope"], target["scope"])
            and not item["condition"] and not item["delegatedManagedIdentityResourceId"]
            for target in desired
        )
        if intended:
            continue
        approved = item["id"] in approvals
        # Common resources are shared across projects. Even a reviewed ID cannot
        # authorize deleting an inherited/shared grant from a project reconciliation.
        removable = (scope == "project" and within(item["scope"], manifest["project_scope"])
                     and item["principalId"] in legacy and approved)
        if removable:
            removals.append(item)
            if not manifest["adoption"]["execute_migration"]:
                blockers.append(f"Explicit adoption.execute_migration required: {item['id']}")
        else:
            blockers.append(
                f"Unresolved grant {item['id']} for {item['principalId']}; "
                "unknown/custom and inherited/shared grants require manual review"
            )
    for approval in approvals:
        item = by_id.get(approval)
        if item is None:
            # A completed migration stays idempotent; absent approvals do not delete anything.
            continue
        if item["principalId"] not in legacy or scope != "project" or not within(item["scope"], manifest["project_scope"]):
            blockers.append(f"Approval is not an exact project-owned legacy assignment: {approval}")
    return receipt, removals, blockers


def migrate(cli, removals):
    checked = []
    for item in removals:
        subscription, _ = arm_scope_parts(item["scope"])
        current = cli("rest", "--method", "get", "--url",
                      f"https://management.azure.com{item['id']}?api-version=2022-04-01",
                      "--subscription", subscription)
        if assignment_content(current) != item:
            raise ValueError(f"Approved assignment content changed; refusing migration: {item['id']}")
        checked.append(item)
    for item in checked:
        subscription, _ = arm_scope_parts(item["scope"])
        cli("role", "assignment", "delete", "--ids", item["id"], "--subscription", subscription)


def _permissions(value):
    return sorted(
        tuple(tuple(sorted(operation.lower() for operation in permission.get(field, [])))
              for field in ("actions", "notActions", "dataActions", "notDataActions"))
        for permission in value
    )


def definition_matches(existing, desired):
    current = existing.get("properties", existing)
    expected = desired["properties"]
    return (
        current.get("roleName") == expected["roleName"]
        and current.get("description") == expected["description"]
        and sorted(item.lower() for item in current.get("assignableScopes", [])) == expected["assignableScopes"]
        and _permissions(current.get("permissions", [])) == _permissions(expected["permissions"])
    )


def definition_inventory(cli, definitions):
    result = {}
    for desired in definitions:
        subscription, _ = arm_scope_parts(desired["id"])
        try:
            item = cli("rest", "--method", "get", "--url",
                       f"https://management.azure.com{desired['id']}?api-version=2022-04-01",
                       "--subscription", subscription)
        except AzureCLIError as error:
            # A scope-filtered list can hide this GUID if somebody else gave it
            # descendant-only assignableScopes. Only an exact missing-role GET
            # permits creation; authorization/network/resource-group errors fail.
            if error.status_code == 404 and error.error_code in (
                "RoleDefinitionDoesNotExist", "RoleDefinitionNotFound",
            ):
                continue
            raise
        if not isinstance(item, dict):
            raise ValueError("Azure role definition GET did not return an object")
        identity = role_guid(item.get("name") or item.get("id"))
        if identity != desired["name"]:
            raise ValueError("Azure role definition GET returned a different GUID")
        result[identity] = item
    return result


def audit_definitions(definitions, existing):
    blockers = []
    for desired in definitions:
        current = existing.get(desired["name"])
        if current is None:
            desired["status"] = "create"
            continue
        properties = current.get("properties", current)
        expected = desired["properties"]
        if (properties.get("description") != expected["description"]
                or sorted(scope.lower() for scope in properties.get("assignableScopes", [])) != expected["assignableScopes"]):
            blockers.append(f"Custom role ID is not owned by this policy: {desired['id']}")
        desired["status"] = "unchanged" if definition_matches(current, desired) else "update"
    return blockers


def check_privileges(cli, required):
    blockers = []
    for scope, operations in sorted(required.items()):
        subscription, _ = arm_scope_parts(scope)
        response = cli("rest", "--method", "get", "--url",
                       f"https://management.azure.com{scope}/providers/Microsoft.Authorization/permissions?api-version=2022-04-01",
                       "--subscription", subscription)
        if not isinstance(response, dict) or not isinstance(response.get("value"), list):
            raise ValueError("Caller permissions endpoint returned invalid content")
        permissions = list(response["value"])
        seen = set()
        while response.get("nextLink"):
            link = response["nextLink"]
            if not isinstance(link, str) or not link.startswith("https://management.azure.com/") or link in seen:
                raise ValueError("Invalid/repeating caller permissions continuation")
            seen.add(link)
            response = cli("rest", "--method", "get", "--url", link, "--subscription", subscription)
            if not isinstance(response, dict) or not isinstance(response.get("value"), list):
                raise ValueError("Invalid caller permissions page")
            permissions.extend(response["value"])
        for operation in operations:
            if not any(
                any(fnmatchcase(operation.lower(), pattern.lower()) for pattern in permission.get("actions", []))
                and not any(fnmatchcase(operation.lower(), pattern.lower()) for pattern in permission.get("notActions", []))
                for permission in permissions
            ):
                blockers.append(f"Executor prerequisite: {operation} at {scope}")
    return blockers
