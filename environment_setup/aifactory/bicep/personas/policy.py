"""Validated, declarative persona policy. No Azure or directory operations."""

from copy import deepcopy
import json
from pathlib import Path
import re
from uuid import UUID, uuid5


SCHEMA = "aifactory.persona-access/v1"
CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
PERSONA_IDS = tuple(CATALOG["personas"])
CORE_PERSONAS = ("persona200", "persona201")
PROJECT_PERSONAS = tuple(persona for persona in PERSONA_IDS if persona not in CORE_PERSONAS)
NAMESPACE = UUID("cf916f48-aefd-5f72-929d-f9df85318fb4")
SECURITY_REVIEWS = (
    "workload_identities_and_secrets_reviewed",
    "transitive_membership_reviewed",
    "legacy_credentials_reviewed",
)
SECURITY_REVIEW_REQUIREMENTS = {
    "workload_identities_and_secrets_reviewed": (
        "Confirm no ordinary project deployer can obtain lake-authorized identities or credentials through "
        "project-controllable workloads, deployment outputs, Key Vault secrets, workspace connections/keys "
        "or app settings. Isolate ingestion identities outside those deployers' control. Foundry agent authors "
        "can execute tools with service identities; those projects must not expose source-lake ingestion identities."
    ),
    "transitive_membership_reviewed": (
        "Review direct/transitive Entra memberships, eligible/PIM grants and legacy human principals. "
        "Runtime does not query Graph; privileges from group memberships are additive."
    ),
    "legacy_credentials_reviewed": (
        "Revoke or rotate historical lake keys, SAS, workspace connection credentials and cached access "
        "as appropriate. An RBAC/ACL change does not invalidate previously obtained credentials."
    ),
}
_RG = r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}"
_ARM = re.compile(rf"/subscriptions/([^/]+)/resourceGroups/({_RG})(/providers/[^?#%\\\s]+)?", re.I)


def guid(value, field="GUID"):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a GUID string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"Invalid {field}: expected a GUID") from error
    if not parsed.int or str(parsed) != value.lower():
        raise ValueError(f"Invalid {field}: use the hyphenated GUID form")
    return str(parsed)


def arm_id(value, *, resource_group=False):
    if not isinstance(value, str) or not (match := _ARM.fullmatch(value)):
        raise ValueError(f"Invalid resource-group ARM ID: {value!r}")
    guid(match[1], "ARM subscription")
    if match[2].endswith("."):
        raise ValueError("Resource group cannot end in a period")
    suffix = match[3]
    if resource_group and suffix:
        raise ValueError("Expected a resource-group scope, not a resource")
    if suffix:
        parts = suffix.split("/")[1:]
        if len(parts) < 4 or len(parts) % 2 or parts[0].lower() != "providers":
            raise ValueError("Malformed resource ARM ID")
        if any(not part or part in (".", "..") for part in parts):
            raise ValueError("Malformed resource ARM ID component")
    return value.lower()


def arm_scope_parts(value):
    match = _ARM.fullmatch(arm_id(value))
    return match[1], match[2]


def rg_scope(value):
    subscription, group = arm_scope_parts(value)
    return f"/subscriptions/{subscription}/resourcegroups/{group}"


def within(value, scope):
    value, scope = value.lower(), scope.lower()
    if scope == "/":
        return value.startswith("/")
    return value == scope or value.startswith(scope + "/")


def resource_type(value):
    suffix = arm_id(value).rsplit("/providers/", 1)
    if len(suffix) != 2:
        return None
    parts = suffix[1].split("/")
    return "/".join([parts[0], *parts[1::2]])


def _list(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _unique(values, field):
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {field}")
    return values


def validate_scope(scope):
    if scope not in ("common", "project"):
        raise ValueError("scope must be 'common' or 'project'")
    return scope


def validate_manifest(manifest, *, require_lake=False):
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError(f"Manifest schema must be {SCHEMA}")
    value = deepcopy(manifest)
    value["tenant_id"] = guid(value.get("tenant_id"), "tenant_id")
    for name, pattern in (("factory", r"[a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?"),
                          ("scaleset", r"[a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?"),
                          ("project", r"project[0-9]{3}")):
        if (not isinstance(value.get(name), str) or not re.fullmatch(pattern, value[name])
                or "--" in value[name]):
            raise ValueError(f"Invalid {name}")
    if value.get("environment") not in ("dev", "test", "prod"):
        raise ValueError("environment must be dev, test or prod")
    for field in ("common_scope", "project_scope"):
        value[field] = arm_id(value.get(field), resource_group=True)
    if value["common_scope"] == value["project_scope"]:
        raise ValueError("common_scope and project_scope must be distinct")
    seeding = value.get("seeding")
    if not isinstance(seeding, dict):
        raise ValueError("seeding must be an object")
    seeding["subscription_id"] = guid(seeding.get("subscription_id"), "seeding.subscription_id")
    for field, pattern in (("resource_group", _RG), ("vault_name", r"[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]")):
        if not isinstance(seeding.get(field), str) or not re.fullmatch(pattern, seeding[field]):
            raise ValueError(f"Invalid seeding.{field}")
    if "--" in seeding["vault_name"] or seeding["resource_group"].endswith("."):
        raise ValueError("Invalid seeding resource name")
    connectivity = _list(value.get("connectivity_scopes", []), "connectivity_scopes")
    value["connectivity_scopes"] = _unique([arm_id(item, resource_group=True) for item in connectivity],
                                         "connectivity_scopes")
    if set(value["connectivity_scopes"]) & {value["common_scope"], value["project_scope"]}:
        raise ValueError("Connectivity scopes must not duplicate common/project scopes")
    networks = _list(value.get("project_network_scopes", []), "project_network_scopes")
    value["project_network_scopes"] = _unique([arm_id(item) for item in networks], "network scopes")
    for item in value["project_network_scopes"]:
        if rg_scope(item) not in (value["common_scope"], value["project_scope"]) or resource_type(item) not in (
            "microsoft.network/virtualnetworks", "microsoft.network/virtualnetworks/subnets",
            "microsoft.network/networksecuritygroups",
        ):
            raise ValueError("Network scope must be an explicit VNet/subnet/NSG in the common or project RG")
        if rg_scope(item) == value["common_scope"] and resource_type(item) == "microsoft.network/virtualnetworks":
            raise ValueError("Whole common-RG VNet access is forbidden; select project-exclusive subnets or NSGs")
    workspace = arm_id(value.get("log_analytics_resource_id"))
    if rg_scope(workspace) != value["common_scope"] or resource_type(workspace) != "microsoft.operationalinsights/workspaces":
        raise ValueError("log_analytics_resource_id must be the exact common workspace")
    value["log_analytics_resource_id"] = workspace
    dashboards = _list(value.get("dashboard_resource_ids", []), "dashboard_resource_ids")
    value["dashboard_resource_ids"] = _unique([arm_id(item) for item in dashboards], "dashboard IDs")
    for item in value["dashboard_resource_ids"]:
        if rg_scope(item) != value["project_scope"] or resource_type(item) not in (
            "microsoft.portal/dashboards", "microsoft.insights/workbooks",
        ):
            raise ValueError("Dashboard must be an exact project dashboard/workbook resource")
    adoption = value.setdefault("adoption", {})
    if not isinstance(adoption, dict):
        raise ValueError("adoption must be an object")
    adoption["legacy_principal_ids"] = _unique(
        [guid(item, "legacy principal") for item in _list(adoption.get("legacy_principal_ids", []), "legacy_principal_ids")],
        "legacy principals")
    adoption["trusted_lake_admin_principal_ids"] = _unique(
        [guid(item, "trusted lake administrator")
         for item in _list(adoption.get("trusted_lake_admin_principal_ids", []), "trusted_lake_admin_principal_ids")],
        "trusted lake administrators")
    adoption["approved_acl_principal_ids"] = _unique(
        [guid(item, "approved ACL principal")
         for item in _list(adoption.get("approved_acl_principal_ids", []), "approved_acl_principal_ids")],
        "approved ACL principals")
    if set(adoption["approved_acl_principal_ids"]) - set(adoption["legacy_principal_ids"]):
        raise ValueError("approved_acl_principal_ids must be a subset of legacy_principal_ids")
    approvals = []
    for item in _list(adoption.get("approved_role_assignment_ids", []), "approved_role_assignment_ids"):
        item = arm_id(item)
        if not re.search(r"/providers/microsoft.authorization/roleassignments/[0-9a-f-]+$", item):
            raise ValueError("Approval must be an exact role-assignment ARM ID")
        guid(item.rsplit("/", 1)[1], "role assignment")
        if rg_scope(item) not in (value["common_scope"], value["project_scope"]):
            raise ValueError("Approval must belong to the explicitly owned common/project RG")
        approvals.append(item)
    adoption["approved_role_assignment_ids"] = _unique(approvals, "assignment approvals")
    if type(adoption.setdefault("execute_migration", False)) is not bool:
        raise ValueError("adoption.execute_migration must be a boolean")
    groups = value.get("groups", {})
    if not isinstance(groups, dict) or set(groups) - set(PERSONA_IDS):
        raise ValueError("groups contains an unknown persona")
    value["groups"] = {persona: guid(oid, f"groups.{persona}") for persona, oid in groups.items()}
    _unique(list(value["groups"].values()), "group object IDs")
    reviews = value.setdefault("security_review", {})
    if not isinstance(reviews, dict) or set(reviews) - set(SECURITY_REVIEWS):
        raise ValueError("security_review contains unknown checks")
    for name in SECURITY_REVIEWS:
        if type(reviews.setdefault(name, False)) is not bool:
            raise ValueError(f"security_review.{name} must be boolean")
    lake = value.get("lake")
    if require_lake and not lake:
        raise ValueError("groups-v1 project access requires an explicit HNS lake configuration")
    if lake is not None:
        if not isinstance(lake, dict):
            raise ValueError("lake must be an object")
        forbidden = {"users", "groups", "managed_identities", "readers", "temporary_data_owner", "execute"}
        if forbidden.intersection(lake):
            raise ValueError("Persona lake inputs cannot supply principals, execution flags or temporary privileges")
        max_paths = lake.get("max_audit_paths", 100000)
        if type(max_paths) is not int or not 1 <= max_paths <= 1000000:
            raise ValueError("max_audit_paths must be an integer from 1 to 1000000")
        for name in ("tenant_id", "subscription_id"):
            lake[name] = guid(lake.get(name), f"lake.{name}")
        for name in ("tenant_id", "project", "environment"):
            if lake.get(name) != value[name]:
                raise ValueError(f"lake.{name} must match the manifest")
        for field, pattern in (("resource_group", _RG), ("storage_account", r"[a-z0-9]{3,24}"),
                               ("filesystem", r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")):
            if not isinstance(lake.get(field), str) or not re.fullmatch(pattern, lake[field]):
                raise ValueError(f"Invalid lake.{field}")
        lake_scope = arm_id(f"/subscriptions/{lake['subscription_id']}/resourceGroups/{lake['resource_group']}",
                            resource_group=True)
        if lake_scope not in (value["common_scope"], value["project_scope"]):
            raise ValueError("Lake must belong to the explicit common/project RG and subscription")
        if type(lake.setdefault("legacy_layout", False)) is not bool:
            raise ValueError("lake.legacy_layout must be boolean")
    return value


def lake_authorized_path(lake):
    if lake.get("legacy_layout", False):
        return f"projects/{lake['project']}"
    return f"mlops/v1/projects/{lake['project']}/environments/{lake['environment']}"


def role_permissions(key):
    """Logical additive blocks; compile with role_definitions before deployment."""
    definition = CATALOG["roles"][key]
    exclusions = []
    if definition.get("management_exclusions"):
        exclusions.extend(CATALOG["management_exclusions"])
    permissions = [{
        "actions": definition["actions"], "notActions": exclusions,
        "dataActions": definition.get("dataActions", []), "notDataActions": [],
    }]
    if definition.get("metadata_read"):
        # Separate block restores metadata reads, not secret values or keys.
        permissions.append({"actions": ["*/read"], "notActions": [
            "Microsoft.OperationalInsights/workspaces/sharedKeys/read",
        ], "dataActions": [], "notDataActions": []})
    if definition.get("additional_actions"):
        permissions.append({"actions": definition["additional_actions"], "notActions": [],
                            "dataActions": [], "notDataActions": []})
    return deepcopy(permissions)


def role_definitions(key, scope):
    """Compile each additive block into one Azure role; assign the entire bundle."""
    if key not in CATALOG["roles"]:
        raise ValueError(f"Unknown custom role: {key}")
    scope = arm_id(scope, resource_group=True)
    components = [key] + [
        f"{key}-{suffix}" for field, suffix in (
            ("metadata_read", "metadata-read"), ("additional_actions", "additional-actions")
        ) if CATALOG["roles"][key].get(field)
    ]
    definitions = []
    for component, permission in zip(components, role_permissions(key), strict=True):
        # Keep the primary GUID/name; sidecars must not merge NotActions across blocks.
        name = str(uuid5(NAMESPACE, f"role|{scope}|{component}"))
        definitions.append({
            "name": name,
            "id": scope + "/providers/Microsoft.Authorization/roleDefinitions/" + name,
            "key": component,
            "properties": {
                "roleName": f"AI Factory {component} {name}",
                "description": f"{SCHEMA} owned role {component} {scope}",
                "type": "CustomRole",
                "assignableScopes": [scope],
                "permissions": [permission],
            },
        })
    return definitions


def assignment(persona, principal, role_id, scope):
    if persona not in PERSONA_IDS:
        raise ValueError(f"Unknown persona: {persona}")
    scope, principal, role_id = arm_id(scope), guid(principal), role_id.lower()
    name = str(uuid5(NAMESPACE, f"assignment|{scope}|{principal}|{role_id}"))
    return {
        "id": scope + "/providers/Microsoft.Authorization/roleAssignments/" + name,
        "name": name, "scope": scope, "principalId": principal, "principalType": "Group",
        "persona": persona, "roleDefinitionId": role_id,
        "description": f"{SCHEMA} owned assignment {name} {persona}",
    }
