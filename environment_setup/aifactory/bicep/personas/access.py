"""Fail-closed persona provisioning. Preview performs reads; apply requires review."""

from collections import defaultdict
import json
from pathlib import Path

from .cli import azure_cli
from .policy import (
    CATALOG, CORE_PERSONAS, PERSONA_IDS, SCHEMA, SECURITY_REVIEWS, SECURITY_REVIEW_REQUIREMENTS, arm_id, arm_scope_parts,
    assignment, guid, resource_type, rg_scope, role_definition, validate_manifest, validate_scope, within,
)
from .reconcile import (
    assignment_content, audit_assignments, audit_definitions, check_privileges,
    definition_inventory, definition_matches, equivalent, inventory, migrate,
)


class ProvisioningBlocked(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__("Persona provisioning blocked: " + "; ".join(report["blockers"]))


def _incomplete(report, blockers, pending=()):
    report["state"] = "incomplete"
    report["blockers"] = list(blockers)
    report["migration"]["pending_removals"] = list(pending)
    raise ProvisioningBlocked(report)


def _resources(manifest, scope, cli):
    result = {}
    roots = [manifest["common_scope"]]
    if scope == "project":
        roots.append(manifest["project_scope"])
    for root in roots:
        subscription, group = arm_scope_parts(root)
        items = cli("resource", "list", "--resource-group", group, "--subscription", subscription)
        if not isinstance(items, list):
            raise ValueError("Resource discovery must return an array")
        for item in items:
            identity = arm_id(item.get("id"))
            if rg_scope(identity) != root or item.get("type", "").lower() != resource_type(identity):
                raise ValueError("Discovered resource belongs to the wrong subscription/RG or has an inconsistent type")
            result[identity] = item
    if scope == "project":
        exact = [manifest["log_analytics_resource_id"], *manifest["dashboard_resource_ids"],
                 *manifest["project_network_scopes"]]
        for identity in exact:
            if identity not in result:
                subscription, _ = arm_scope_parts(identity)
                item = cli("resource", "show", "--ids", identity, "--subscription", subscription)
                if not isinstance(item, dict) or arm_id(item.get("id")) != identity:
                    raise ValueError(f"Configured resource was not found at its exact scope: {identity}")
                if item.get("type", "").lower() != resource_type(identity):
                    raise ValueError(f"Configured resource type mismatch: {identity}")
                result[identity] = item
    return result


def _plan(manifest, scope, groups, resources):
    definitions, assignments = {}, []

    def grant(persona, key, target, definition_scope=None):
        subscription, _ = arm_scope_parts(target)
        if key in CATALOG["builtins"]:
            role_id = f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{CATALOG['builtins'][key]}"
        else:
            definition = role_definition(key, definition_scope or rg_scope(target))
            definitions[definition["id"]] = definition
            role_id = definition["id"]
        planned = {**assignment(persona, groups[persona], role_id, target), "role_key": key}
        assignments.append(planned)
        return planned

    for root in (manifest["common_scope"], *manifest["connectivity_scopes"]):
        grant("persona200", "owner", root)
    grant("persona201", "contributor", manifest["common_scope"])
    if scope == "common":
        return list(definitions.values()), assignments
    project = manifest["project_scope"]
    for persona in PERSONA_IDS:
        key = CATALOG["personas"][persona]["management"]
        if persona == "persona215":
            for target in manifest["project_network_scopes"]:
                grant(persona, key, target)
        else:
            grant(persona, key, project)
        if persona in CORE_PERSONAS:
            grant(persona, "admin", project)
        vault_role = CATALOG["personas"][persona].get("vault")
        if vault_role:
            for identity in resources:
                if rg_scope(identity) == project and resource_type(identity) == "microsoft.keyvault/vaults":
                    grant(persona, vault_role, identity)
        bundle = CATALOG["personas"][persona].get("service_data")
        for service in CATALOG["service_data_bundles"].get(bundle, []):
            for identity, resource in resources.items():
                if rg_scope(identity) != project or resource_type(identity) != service["resource_type"].lower():
                    continue
                if service.get("kinds") and str(resource.get("kind") or "").lower() not in {
                    kind.lower() for kind in service["kinds"]
                }:
                    continue
                key = service["role"]
                target = grant(persona, key, identity)
                target.update({
                    "service_data": True, "service_capabilities": service["capabilities"],
                    "resource_kind": resource.get("kind"),
                    "data_actions": list(CATALOG["builtin_data_actions"][key] if key in CATALOG["builtins"]
                                         else CATALOG["roles"][key]["dataActions"]),
                })
    # Core groups share the project-admin data baseline, not only management RBAC.
    grant("persona216", "cost-reader", project)
    grant("persona216", "workspace-observer", manifest["log_analytics_resource_id"])
    for identity in manifest["dashboard_resource_ids"]:
        grant("persona216", "reader", identity)
    return list(definitions.values()), assignments


def _vault_checks(manifest, scope, resources, groups, cli):
    blockers, vaults = [], []
    roots = {manifest["common_scope"]}
    if scope == "project":
        roots.add(manifest["project_scope"])
    affected = set(manifest["adoption"]["legacy_principal_ids"])
    affected.update(oid for persona, oid in groups.items() if persona not in CORE_PERSONAS)
    for identity in sorted(resources):
        root = rg_scope(identity)
        if root not in roots or resource_type(identity) != "microsoft.keyvault/vaults":
            continue
        subscription, group = arm_scope_parts(identity)
        vault = cli("keyvault", "show", "--name", identity.rsplit("/", 1)[1],
                    "--resource-group", group, "--subscription", subscription)
        if not isinstance(vault, dict) or arm_id(vault.get("id")) != identity:
            raise ValueError("Vault preflight returned a different resource")
        properties = vault.get("properties", {})
        if guid(properties.get("tenantId"), "vault tenant") != manifest["tenant_id"]:
            raise ValueError("Project/common vault belongs to a different tenant")
        policies = properties.get("accessPolicies")
        if not isinstance(policies, list):
            raise ValueError("Vault access-policy inventory is missing")
        affected_policies = []
        for policy in policies:
            if not isinstance(policy, dict):
                raise ValueError("Vault access policy must be an object")
            if guid(policy.get("objectId"), "vault access-policy principal") in affected:
                affected_policies.append(policy)
        rbac_enabled = properties.get("enableRbacAuthorization") is True
        requires_rbac = scope == "project" and root == manifest["project_scope"]
        vaults.append({"id": identity, "rbac_enabled": rbac_enabled, "requires_rbac": requires_rbac,
                       "legacy_access_policies": policies, "affected_access_policies": affected_policies})
        if requires_rbac and not rbac_enabled:
            blockers.append(f"Key Vault must explicitly use Azure RBAC before provisioning: {identity}")
        if (requires_rbac and policies) or affected_policies:
            blockers.append(f"Legacy/dormant Key Vault access policies require reviewed manual remediation: {identity}")
    return vaults, blockers


def _required_operations(definitions, assignments, removals):
    required = defaultdict(set)
    for definition in definitions:
        if definition["status"] != "unchanged":
            root = definition["properties"]["assignableScopes"][0]
            required[root].update(("Microsoft.Authorization/roleDefinitions/write", "Microsoft.Resources/deployments/write"))
    for target in assignments:
        if target["status"] == "create":
            required[target["scope"]].add("Microsoft.Authorization/roleAssignments/write")
    for target in removals:
        required[target["scope"]].add("Microsoft.Authorization/roleAssignments/delete")
    return required


def _deploy_definitions(definitions, cli):
    by_scope = defaultdict(list)
    for definition in definitions:
        if definition["status"] != "unchanged":
            by_scope[definition["properties"]["assignableScopes"][0]].append(definition)
    for root, roles in sorted(by_scope.items()):
        subscription, group = arm_scope_parts(root)
        parameters = [{key: value for key, value in role.items() if key != "status"} for role in roles]
        cli("deployment", "group", "create", "--name", "aifactory-persona-roles-v1",
            "--resource-group", group, "--subscription", subscription,
            "--template-file", str(Path(__file__).with_name("custom-roles.bicep")),
            "--parameters", "roles=" + json.dumps(parameters, separators=(",", ":")))
    actual = definition_inventory(cli, definitions)
    for desired in definitions:
        if desired["name"] not in actual or not definition_matches(actual[desired["name"]], desired):
            raise RuntimeError(f"Custom role verification failed: {desired['id']}")


def provision(manifest, scope="project", execute=False, cli=None):
    """Resolve seeded groups, inventory, gate migration, then reconcile exact grants.

    ``cli(*args)`` returns parsed Azure CLI JSON and must raise on failure.
    A missing role GET must raise AzureCLIError with explicit 404 status and a
    missing-role code; generic transport/authorization failures are never absence.
    ``execute=False`` never writes. Blocking previews return a report; blocked
    execution raises ProvisioningBlocked with the same report in ``.report``.
    """
    scope = validate_scope(scope)
    manifest = validate_manifest(manifest, require_lake=scope == "project")
    if type(execute) is not bool:
        raise ValueError("execute must be a boolean")
    cli = azure_cli if cli is None else cli
    if not callable(cli):
        raise ValueError("cli must be a callable returning parsed JSON")
    from .groups import resolve_seeded_groups

    groups = resolve_seeded_groups(manifest, scope, cli)
    expected = set(CORE_PERSONAS if scope == "common" else PERSONA_IDS)
    if not isinstance(groups, dict) or set(groups) != expected:
        raise ValueError("Missing seeded group or unknown persona in resolved scope")
    groups = {persona: guid(oid, f"seeded {persona}") for persona, oid in groups.items()}
    if len(set(groups.values())) != len(groups):
        raise ValueError("Duplicate seeded group object IDs")
    roots = [manifest["common_scope"], *manifest["connectivity_scopes"]]
    if scope == "project":
        roots.append(manifest["project_scope"])
    subscriptions = {arm_scope_parts(root)[0] for root in roots}
    for subscription in sorted(subscriptions):
        account = cli("account", "show", "--subscription", subscription)
        if (not isinstance(account, dict) or guid(account.get("id"), "account subscription") != subscription
                or guid(account.get("tenantId"), "account tenant") != manifest["tenant_id"]):
            raise ValueError("Selected subscription/tenant does not match the manifest")
        if account.get("state") != "Enabled":
            raise ValueError("Selected subscription must be Enabled")
    resources = _resources(manifest, scope, cli)
    definitions, desired = _plan(manifest, scope, groups, resources)
    existing_roles = definition_inventory(cli, definitions)
    blockers = audit_definitions(definitions, existing_roles)
    existing = inventory(cli, roots)
    assignments, removals, assignment_blockers = audit_assignments(
        manifest, scope, groups, desired, existing)
    blockers.extend(assignment_blockers)
    vaults, vault_blockers = _vault_checks(manifest, scope, resources, groups, cli)
    blockers.extend(vault_blockers)
    report = {
        "schema": SCHEMA, "state": "preview", "scope": scope, "groups": groups,
        "definitions": definitions, "assignments": assignments, "vaults": vaults,
        "service_data": [item for item in assignments if item.get("service_data")],
        "migration": {"explicit_execution": manifest["adoption"]["execute_migration"],
                      "approved_removals": removals, "removed_assignment_ids": []},
        "blockers": blockers, "warnings": [
            "Permissions from memberships are additive; NotActions is not an Azure deny assignment.",
            "Deployable workload administrators can execute code, obtain workload identity tokens and read workload secrets. "
            "This model is not isolation from those administrators; review identities and secret isolation.",
            "No Graph is used at runtime. Transitive memberships, PIM eligibility and cached credentials require operator review.",
            "The reviewed legacy_principal_ids list must be complete; unrelated principal assignments are not automatically removed.",
            "Core Contributor is deliberately trusted: storage keys, workload identities and Key Vault management remain available.",
            "No subscription-level resource-group creation/bootstrap or connectivity rights are granted to core-team.",
            "Assignment ownership receipts do not claim ownership of equivalent pre-existing grants.",
            "ARM and ACL writes are not transactional. Avoid concurrent reconciliation; errors propagate and deterministic IDs support review/retry.",
            "Member/admin/core/AI service data grants cover only discovered project Search/Cognitive resources and the reported operations. "
            "Endpoint feature availability, networking and Entra authentication support must be validated separately.",
            "Compatibility: safe non-lake Search, inference and Foundry agent capabilities are retained for member/admin/core. "
            "Storage Blob/File/Queue data RBAC, lake credentials and connection-secret extraction are intentionally not retained.",
            "Foundry agent authors can execute tools using service identities and access derived service data. "
            "Those identities must not carry source-lake ingestion privileges; derived Search/model/agent data is a separate trust boundary.",
            "AzureML uses the custom AI management role, including job/endpoint operations. AzureML Data Scientist and "
            "Azure AI Developer are not assigned; datastore/connection secrets and workspace storage-key calls are excluded. "
            "No dataset/storage authorization is implied by an AML management or endpoint-scoring permission.",
        ],
        "prerequisites": {"security_review": manifest["security_review"],
                          "security_review_requirements": dict(SECURITY_REVIEW_REQUIREMENTS),
                          "project_network_scopes": "Every approved subnet/NSG must be project-exclusive, including NSGs "
                                                    "in the common RG. Whole-VNet grants are allowed only in the owned project RG.",
                          "lake_trust": "Only core groups and explicitly reviewed trusted_lake_admin_principal_ids; "
                                        "the deployment SP and project MIs are never implicitly trusted",
                          "subscription_bootstrap": "Existing RGs and a separately authorized RBAC/role-definition executor",
                          "deny_assignments": "Azure deny assignments and concurrent policy changes can still reject writes"},
    }
    if manifest["project_network_scopes"]:
        report["warnings"].append(
            "Review each approved network scope for project-exclusive use, especially common-RG NSGs. "
            "Whole common-RG VNets are rejected; a shared NSG must not confer administration over unrelated projects."
        )
    if scope == "project":
        for service in CATALOG["service_data_bundles"][CATALOG["personas"]["persona213"]["service_data"]]:
            if not any(item["role_key"] == service["role"] for item in report["service_data"]):
                report["warnings"].append(
                    f"No eligible project {service['resource_type']} discovered; no {service['role']} data grant was assigned."
                )
        for review in SECURITY_REVIEWS:
            if not manifest["security_review"][review]:
                blockers.append(f"Explicit security_review.{review} is required")
        from .lake import provision_lake

        report["lake"] = provision_lake(manifest, groups, False, cli)
        report["warnings"].append(
            "AI human lake access is read-only (directories r-x, files r--), with traversal only above the environment. "
            "Trusted ingestion identities own/write data: ADLS writers can own new files and change their ACLs."
        )
        if not isinstance(report["lake"], dict):
            raise ValueError("Lake preflight must return a report")
        acl_removals = report["lake"].get("legacy_acl_removals", [])
        if not isinstance(acl_removals, list):
            raise ValueError("Lake legacy_acl_removals must be an array")
        report["migration"]["legacy_acl_removals"] = acl_removals
        if acl_removals and not manifest["adoption"]["execute_migration"]:
            blockers.append("Explicit adoption.execute_migration required for legacy lake ACL removals")
        blockers.extend(report["lake"].get("blockers", []))
        report["warnings"].extend(report["lake"].get("warnings", []))
        if report["lake"].get("state") == "blocked" and not report["lake"].get("blockers"):
            blockers.append("Lake preflight is blocked")
    blockers.extend(check_privileges(cli, _required_operations(definitions, assignments, removals)))
    report["blockers"] = sorted(set(blockers))
    if report["blockers"]:
        report["state"] = "blocked"
        if execute:
            raise ProvisioningBlocked(report)
        return report
    if not execute:
        return report
    if removals:
        migrate(cli, removals)
        after = inventory(cli, roots)
        expected_removed = {target["id"] for target in removals}
        surviving = [item for item in after if item["id"] in expected_removed]
        report["migration"]["removed_assignment_ids"] = sorted(expected_removed - {item["id"] for item in surviving})
        if surviving:
            _incomplete(report, ["Legacy role-assignment removal is not yet visible; stop and retry after propagation"], surviving)
        _, pending, remaining = audit_assignments(manifest, scope, groups, desired, after)
        if pending or remaining:
            _incomplete(report, ["Grants changed during migration", *remaining], pending)
    _deploy_definitions(definitions, cli)
    for target in assignments:
        if target["status"] != "create":
            continue
        subscription, _ = arm_scope_parts(target["scope"])
        created = cli("role", "assignment", "create", "--assignee-object-id", target["principalId"],
                      "--assignee-principal-type", "Group", "--role", target["roleDefinitionId"],
                      "--scope", target["scope"], "--name", target["name"], "--description", target["description"],
                      "--subscription", subscription)
        current = assignment_content(created)
        if (not equivalent(current, target) or current["id"] != target["id"].lower()
                or current["description"] != target["description"]):
            raise RuntimeError(f"Created assignment does not match the ownership receipt: {target['id']}")
        target.update(status="owned", existing_assignment_ids=[current["id"]], owned_assignment_ids=[current["id"]])
    after = inventory(cli, roots)
    verified, pending, changed = audit_assignments(manifest, scope, groups, desired, after)
    report["assignments"] = verified
    report["service_data"] = [item for item in verified if item.get("service_data")]
    if changed or pending or any(item["status"] == "create" for item in verified):
        _incomplete(report, [
            *changed,
            *(f"Approved legacy grant remains or was recreated: {item['id']}" for item in pending),
            *(f"Expected assignment is missing: {item['id']}" for item in verified if item["status"] == "create"),
        ], pending)
    if scope == "project":
        report["lake"] = provision_lake(manifest, groups, True, cli)
        if report["lake"].get("blockers") or report["lake"].get("state") == "blocked":
            raise RuntimeError("Lake apply did not complete successfully")
    report["state"] = "applied"
    return report
