"""Azure-free provisioning, migration, collision and idempotency contracts."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest


BICEP = Path(__file__).resolve().parents[3] / "aifactory" / "bicep"
sys.path.insert(0, str(BICEP))
from personas import access, groups, lake, policy, reconcile
from personas import cli as cli_module
from personas.cli import AzureCLIError


TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
COMMON = f"/subscriptions/{SUB}/resourceGroups/common-rg"
PROJECT = f"/subscriptions/{SUB}/resourceGroups/project-rg"
GROUPS = {persona: f"00000000-0000-0000-0000-{index:012d}" for index, persona in enumerate(policy.PERSONA_IDS, 1)}
VAULT = (PROJECT + "/providers/Microsoft.KeyVault/vaults/project-vault").lower()
WORKSPACE = (COMMON + "/providers/Microsoft.OperationalInsights/workspaces/logs").lower()


def manifest():
    return {
        "schema": policy.SCHEMA, "tenant_id": TENANT, "factory": "factory", "scaleset": "001",
        "environment": "dev", "project": "project001",
        "seeding": {"subscription_id": SUB, "resource_group": "seed-rg", "vault_name": "factory-seed"},
        "common_scope": COMMON, "project_scope": PROJECT, "log_analytics_resource_id": WORKSPACE,
        "lake": {"tenant_id": TENANT, "subscription_id": SUB, "resource_group": "common-rg",
                 "storage_account": "isolatedlake", "filesystem": "lake3",
                 "project": "project001", "environment": "dev"},
        "security_review": {name: True for name in policy.SECURITY_REVIEWS},
    }


class Azure:
    def __init__(self):
        self.calls = []
        self.assignments = []
        self.definitions = []
        self.resources = [
            {"id": VAULT, "type": "Microsoft.KeyVault/vaults"},
            {"id": WORKSPACE, "type": "Microsoft.OperationalInsights/workspaces"},
        ]
        self.rbac = True
        self.policies = []
        self.permissions = [{"actions": ["*"], "notActions": []}]
        self.tenant = TENANT
        self.changed_assignment = None
        self.fail_create = False
        self.vault_overrides = {}
        self.role_get_error = None
        self.recreate_on_create = None
        self.ignore_deletes = False

    def __call__(self, *args):
        self.calls.append(args)
        def arg(key):
            return args[args.index(key) + 1]
        if args[:2] == ("account", "show"):
            return {"id": arg("--subscription"), "tenantId": self.tenant, "state": "Enabled"}
        if args[:2] == ("resource", "list"):
            return [item for item in self.resources if policy.arm_scope_parts(item["id"])[1] == arg("--resource-group")]
        if args[:2] == ("resource", "show"):
            return {"id": arg("--ids"), "type": policy.resource_type(arg("--ids"))}
        if args[:2] == ("keyvault", "show"):
            return {"id": arg("--id"), "properties": {"enableRbacAuthorization": self.rbac,
                    "accessPolicies": self.policies, "tenantId": TENANT,
                    **self.vault_overrides.get(arg("--id"), {})}}
        if args[:3] == ("role", "definition", "list"):
            return deepcopy([item for item in self.definitions
                             if any(policy.within(arg("--scope"), scope)
                                    for scope in item.get("assignableScopes", []))])
        if args[:3] == ("role", "assignment", "list"):
            raise AssertionError("Use ARM REST inventory without CLI Graph name resolution")
        if args[:1] == ("rest",):
            url = arg("--url")
            parsed = urlsplit(url)
            if parsed.path.lower().endswith("/providers/microsoft.authorization/roleassignments"):
                assert arg("--method") == "get"
                assert parse_qs(parsed.query)["api-version"] == ["2022-04-01"]
                scope = parsed.path.rsplit("/providers/", 1)[0]
                if "$filter" not in parse_qs(parsed.query):
                    assert scope.lower() == f"/subscriptions/{arg('--subscription')}"
                    items = [item for item in self.assignments if policy.within(item["scope"], scope)]
                else:
                    assert parse_qs(parsed.query)["$filter"] == ["atScope()"]
                    items = [item for item in self.assignments
                             if policy.within(scope, item["scope"])
                             or item["scope"].lower().startswith("/providers/microsoft.management/managementgroups/")]
                return {"value": [{"id": item["id"], "properties": deepcopy(item)} for item in items]}
            if "/roledefinitions/" in url.lower():
                if self.role_get_error is not None:
                    raise self.role_get_error
                name = url.split("?", 1)[0].rsplit("/", 1)[1]
                item = next((item for item in self.definitions if item["name"] == name), None)
                if item is None:
                    raise AzureCLIError("missing role", status_code=404, error_code="RoleDefinitionDoesNotExist")
                return deepcopy(item)
            if "/permissions?" in url:
                return {"value": self.permissions}
            if "/roleassignments/" in url:
                identity = url.removeprefix("https://management.azure.com").split("?", 1)[0]
                item = next(item for item in self.assignments if item["id"].lower() == identity.lower())
                return deepcopy(self.changed_assignment or item)
            raise AssertionError(args)
        if args[:3] == ("deployment", "group", "create"):
            assert Path(arg("--template-file")).name == "custom-roles.bicep"
            definitions = json.loads(arg("--parameters").removeprefix("roles="))
            for definition in definitions:
                self.definitions = [item for item in self.definitions if item["name"] != definition["name"]]
                self.definitions.append({"name": definition["name"], "id": definition["id"], **definition["properties"]})
            return {"properties": {"provisioningState": "Succeeded"}}
        if args[:3] == ("role", "assignment", "create"):
            if self.fail_create:
                raise RuntimeError("AuthorizationFailed")
            identity = arg("--scope") + "/providers/Microsoft.Authorization/roleAssignments/" + arg("--name")
            item = {"id": identity, "scope": arg("--scope"), "principalId": arg("--assignee-object-id"),
                    "roleDefinitionId": arg("--role"), "description": arg("--description"), "principalType": "Group"}
            assert arg("--assignee-principal-type") == "Group"
            self.assignments.append(item)
            if self.recreate_on_create:
                self.assignments.append(deepcopy(self.recreate_on_create))
                self.recreate_on_create = None
            return deepcopy(item)
        if args[:3] == ("role", "assignment", "delete"):
            if not self.ignore_deletes:
                self.assignments = [item for item in self.assignments if item["id"].lower() != arg("--ids").lower()]
            return None
        raise AssertionError(f"Unexpected command: {args}")

    @property
    def mutations(self):
        return [call for call in self.calls if call[:3] in (
            ("deployment", "group", "create"), ("role", "assignment", "create"),
            ("role", "assignment", "delete"))]


@pytest.fixture
def azure(monkeypatch):
    transport = Azure()
    monkeypatch.setattr(groups, "resolve_seeded_groups",
                        lambda manifest, scope, cli: {key: value for key, value in GROUPS.items()
                                                     if scope == "project" or key in policy.CORE_PERSONAS})
    monkeypatch.setattr(lake, "provision_lake",
                        lambda manifest, groups, execute, cli: {"state": "complete" if execute else "preview",
                                                                "blockers": [], "warnings": []})
    return transport


def legacy_assignment(principal=TENANT, scope=PROJECT, role=None):
    return {"id": scope + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid4()),
            "scope": scope, "principalId": principal, "principalType": "Group",
            "roleDefinitionId": role or policy.CATALOG["builtins"]["contributor"], "description": "legacy"}


def test_preview_reads_only_and_plans_nine_personas(azure):
    result = access.provision(manifest(), cli=azure)
    assert result["state"] == "preview"
    assert not azure.mutations
    assert set(result["groups"]) == set(policy.PERSONA_IDS)
    assert set(item["persona"] for item in result["assignments"]) == set(policy.PERSONA_IDS)
    assert all(item["status"] == "create" for item in result["assignments"])
    assert any("not isolation" in warning for warning in result["warnings"])
    assert not any("No lake configuration" in warning for warning in result["warnings"])
    assert any("read-only" in warning and "ADLS writers" in warning for warning in result["warnings"])
    assert "app settings" in result["prerequisites"]["security_review_requirements"]["workload_identities_and_secrets_reviewed"]
    assert "never implicitly trusted" in result["prerequisites"]["lake_trust"]
    assert not any(call[:1] == ("ad",) for call in azure.calls)


def test_exact_network_vault_manager_and_core_scopes(azure):
    value = manifest()
    network = (COMMON + "/providers/Microsoft.Network/virtualNetworks/shared/subnets/project001").lower()
    connection = f"/subscriptions/{SUB}/resourceGroups/connectivity"
    value.update(project_network_scopes=[network], connectivity_scopes=[connection])
    report = access.provision(value, cli=azure)
    assert any("project-exclusive" in warning and "NSGs" in warning for warning in report["warnings"])
    assert "project-exclusive" in report["prerequisites"]["project_network_scopes"]
    assignments = report["assignments"]
    network_roles = [item for item in assignments if item["roleDefinitionId"].endswith(policy.CATALOG["builtins"]["network-contributor"])]
    assert [(item["persona"], item["scope"]) for item in network_roles] == [("persona215", network)]
    vault_admin = [item for item in assignments if item["roleDefinitionId"].endswith(policy.CATALOG["builtins"]["key-vault-administrator"])]
    assert [(item["persona"], item["scope"]) for item in vault_admin] == [("persona215", VAULT)]
    assert {item["scope"] for item in assignments if item["persona"] == "persona201"} == {COMMON.lower(), PROJECT.lower(), VAULT}
    assert {item["scope"] for item in assignments if item["persona"] == "persona200"} == {
        COMMON.lower(), PROJECT.lower(), connection.lower(), VAULT}
    for persona in policy.CORE_PERSONAS:
        assert any(item["persona"] == persona and item["role_key"] == "admin"
                   and item["scope"] == PROJECT.lower() for item in assignments)
    pm = [item for item in assignments if item["persona"] == "persona216"]
    assert {item["scope"] for item in pm} == {PROJECT.lower(), WORKSPACE}
    assert all(item["scope"] != COMMON.lower() for item in pm)
    assert not any(item["scope"] == VAULT for item in pm)


def test_shared_data_bundle_is_assigned_only_to_discovered_project_services(azure):
    project_search = (PROJECT + "/providers/Microsoft.Search/searchServices/project-search").lower()
    project_cognitive = (PROJECT + "/providers/Microsoft.CognitiveServices/accounts/project-ai").lower()
    for root in (COMMON, PROJECT):
        azure.resources.extend([
            {"id": (root + "/providers/Microsoft.Search/searchServices/project-search").lower(),
             "type": "Microsoft.Search/searchServices"},
            {"id": (root + "/providers/Microsoft.CognitiveServices/accounts/project-ai").lower(),
             "type": "Microsoft.CognitiveServices/accounts", "kind": "AIServices"},
        ])
    report = access.provision(manifest(), cli=azure)
    grants = report["service_data"]
    assert len(grants) == 15
    assert {item["persona"] for item in grants} == {"persona200", "persona201", "persona210", "persona211", "persona213"}
    for persona in ("persona200", "persona201", "persona210", "persona211", "persona213"):
        assert {item["role_key"] for item in grants if item["persona"] == persona} == {
            "search-index-data-contributor", "cognitive-inference", "foundry-agent-author",
        }
    assert {item["scope"] for item in grants} == {project_search, project_cognitive}
    search = next(item for item in grants if item["scope"] == project_search)
    assert search["roleDefinitionId"].endswith("/8ebe5a00-799e-43f5-93ac-243d3dce84a7")
    assert search["data_actions"] == policy.CATALOG["builtin_data_actions"]["search-index-data-contributor"]
    cognitive = next(item for item in grants if item["role_key"] == "cognitive-inference")
    assert cognitive["roleDefinitionId"] == policy.role_definition("cognitive-inference", PROJECT)["id"].lower()
    assert cognitive["resource_kind"] == "AIServices"
    assert "no connection secrets" in cognitive["service_capabilities"]
    foundry = next(item for item in grants if item["role_key"] == "foundry-agent-author")
    assert foundry["roleDefinitionId"] == policy.role_definition("foundry-agent-author", PROJECT)["id"].lower()
    assert "managed-agent identity blueprints" in foundry["service_capabilities"]
    cognitive["data_actions"].append("changed report only")
    assert "changed report only" not in policy.CATALOG["roles"]["cognitive-inference"]["dataActions"]
    assert not azure.mutations


def test_service_data_roles_apply_idempotently_and_return_exact_owned_ids(azure):
    azure.resources.extend([
        {"id": (PROJECT + "/providers/Microsoft.Search/searchServices/project-search").lower(),
         "type": "Microsoft.Search/searchServices"},
        {"id": (PROJECT + "/providers/Microsoft.CognitiveServices/accounts/project-ai").lower(),
         "type": "Microsoft.CognitiveServices/accounts", "kind": "OpenAI"},
    ])
    first = access.provision(manifest(), execute=True, cli=azure)
    assert len(first["service_data"]) == 15
    assert all(item["status"] == "owned" and item["owned_assignment_ids"] for item in first["service_data"])
    before = len(azure.mutations)
    second = access.provision(manifest(), execute=True, cli=azure)
    assert second["state"] == "applied"
    assert len(azure.mutations) == before
    assert first["service_data"] == second["service_data"]


def test_missing_project_services_are_reported_without_claiming_data_access(azure):
    report = access.provision(manifest(), cli=azure)
    assert report["service_data"] == []
    assert any("no cognitive-inference data grant" in warning for warning in report["warnings"])
    assert any("no search-index-data-contributor data grant" in warning for warning in report["warnings"])
    assert any("no foundry-agent-author data grant" in warning for warning in report["warnings"])
    assert any("No dataset/storage authorization is implied" in warning for warning in report["warnings"])
    assert any("Storage Blob/File/Queue data RBAC" in warning for warning in report["warnings"])
    assert any("separate trust boundary" in warning for warning in report["warnings"])


@pytest.mark.parametrize("kind", ["SpeechServices", "FormRecognizer", None])
def test_agent_role_is_not_claimed_for_non_foundry_or_unknown_account_kinds(azure, kind):
    azure.resources.append({
        "id": (PROJECT + "/providers/Microsoft.CognitiveServices/accounts/project-ai").lower(),
        "type": "Microsoft.CognitiveServices/accounts", "kind": kind,
    })
    report = access.provision(manifest(), cli=azure)
    assert len(report["service_data"]) == 5
    assert {item["role_key"] for item in report["service_data"]} == {"cognitive-inference"}
    assert any("no foundry-agent-author data grant" in warning for warning in report["warnings"])


def test_common_resolves_core_only_and_does_not_touch_project_lake(azure, monkeypatch):
    monkeypatch.setattr(lake, "provision_lake", lambda *args: pytest.fail("Common must not provision lake"))
    result = access.provision(manifest(), scope="common", cli=azure)
    assert set(result["groups"]) == set(policy.CORE_PERSONAS)
    assert not result["definitions"]
    assert {item["scope"] for item in result["assignments"]} == {COMMON.lower()}


def test_apply_consumes_bicep_and_rerun_has_no_rbac_mutations(azure):
    first = access.provision(manifest(), execute=True, cli=azure)
    assert first["state"] == "applied"
    assert any(call[:3] == ("deployment", "group", "create") for call in azure.calls)
    assert all(item["owned_assignment_ids"] and not item["adopted_assignment_ids"] for item in first["assignments"])
    count = len(azure.mutations)
    second = access.provision(manifest(), execute=True, cli=azure)
    assert second["state"] == "applied"
    assert len(azure.mutations) == count
    assert {item["id"] for item in second["assignments"]} == {item["id"] for item in first["assignments"]}


def test_equivalent_preexisting_grant_is_adopted_not_owned(azure):
    desired = access.provision(manifest(), cli=azure)["assignments"][0]
    prior = {**desired, "id": desired["scope"] + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid4()),
             "description": "owned by another system"}
    azure.assignments.append(prior)
    report = access.provision(manifest(), execute=True, cli=azure)
    item = next(item for item in report["assignments"] if item["id"] == desired["id"])
    assert item["status"] == "adopted"
    assert item["owned_assignment_ids"] == []
    assert item["adopted_assignment_ids"] == [prior["id"].lower()]
    assert len([item for item in azure.assignments if item["principalId"] == prior["principalId"]
                and item["scope"] == prior["scope"] and item["roleDefinitionId"] == prior["roleDefinitionId"]]) == 1


@pytest.mark.parametrize("role", ["b24988ac-6180-42a0-ab88-20f7382dd24c", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])
def test_unresolved_ordinary_broad_or_unknown_role_blocks_before_mutation(azure, role):
    azure.assignments.append(legacy_assignment(principal=GROUPS["persona210"], role=role))
    with pytest.raises(access.ProvisioningBlocked, match="Unresolved grant"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_unknown_inherited_role_blocks_and_is_never_deleted(azure):
    inherited = legacy_assignment(scope=f"/subscriptions/{SUB}")
    azure.assignments.append(inherited)
    value = {**manifest(), "adoption": {"legacy_principal_ids": [TENANT]}}
    report = access.provision(value, cli=azure)
    assert report["state"] == "blocked"
    assert not report["migration"]["approved_removals"]
    assert not azure.mutations


@pytest.mark.parametrize("scope", ["/", "/providers/Microsoft.Management/managementGroups/platform"])
def test_tenant_and_management_group_inheritance_is_not_missed(azure, scope):
    item = legacy_assignment(principal=GROUPS["persona210"], scope=scope)
    item["id"] = scope.rstrip("/") + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid4())
    azure.assignments.append(item)
    with pytest.raises(access.ProvisioningBlocked, match="Unresolved grant"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_descendant_legacy_assignments_are_not_missed_by_at_scope_inventory(azure):
    item = legacy_assignment(principal=GROUPS["persona210"], scope=VAULT)
    azure.assignments.append(item)
    with pytest.raises(access.ProvisioningBlocked, match="Unresolved grant"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


@pytest.mark.parametrize("inherited", [False, True])
def test_arm_assignment_inventory_follows_every_page_without_name_resolution(inherited):
    item = legacy_assignment()
    calls = []
    endpoint = f"https://management.azure.com{PROJECT}/providers/Microsoft.Authorization/roleAssignments"
    next_link = endpoint + "?api-version=2022-04-01&$skiptoken=second"

    def cli(*args):
        calls.append(args)
        assert args[:3] == ("rest", "--method", "get")
        assert args[args.index("--subscription") + 1] == SUB
        url = args[args.index("--url") + 1]
        if len(calls) == 1:
            assert url == endpoint + "?api-version=2022-04-01" + ("&$filter=atScope()" if inherited else "")
            return {"value": [], "nextLink": next_link}
        assert url == next_link
        return {"value": [{"id": item["id"], "properties": {k: v for k, v in item.items() if k != "id"}}]}

    assert cli_module.role_assignments(cli, PROJECT, SUB, include_inherited=inherited) == [item]
    assert len(calls) == 2


@pytest.mark.parametrize("failure_on", ["descendants", "inherited", "next-page"])
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_inventory_read_failures_propagate_before_any_mutation(azure, failure_on, status):
    error = AzureCLIError("inventory failed", status_code=status)
    next_link = (f"https://management.azure.com/subscriptions/{SUB}"
                 "/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01&$skiptoken=next")

    def cli(*args):
        if args[:1] == ("rest",):
            url = args[args.index("--url") + 1]
            if urlsplit(url).path.lower().endswith("/roleassignments"):
                inherited = "$filter=" in url
                if (failure_on == "descendants" and not inherited
                        or failure_on == "inherited" and inherited
                        or failure_on == "next-page" and url == next_link):
                    raise error
                if failure_on == "next-page":
                    return {"value": [], "nextLink": next_link}
        return azure(*args)

    with pytest.raises(AzureCLIError) as caught:
        access.provision(manifest(), execute=True, cli=cli)
    assert caught.value is error
    assert not azure.mutations


@pytest.mark.parametrize("response", [
    None, [], {}, {"value": None}, {"value": {}}, {"value": [None]},
    {"value": [{"id": "assignment", "properties": None}]},
    {"value": [], "nextLink": 1}, {"value": [], "nextLink": ""},
    {"value": [], "nextLink": "https://graph.microsoft.com/v1.0/users"},
])
def test_arm_assignment_inventory_rejects_incomplete_responses(response):
    with pytest.raises(ValueError, match="inventory|assignment"):
        cli_module.role_assignments(lambda *args: response, PROJECT, SUB)


def test_arm_assignment_inventory_rejects_pagination_cycles():
    calls = []

    def cli(*args):
        calls.append(args)
        return {"value": [], "nextLink": args[args.index("--url") + 1]}

    with pytest.raises(ValueError, match="inventory"):
        cli_module.role_assignments(cli, PROJECT, SUB)
    assert len(calls) == 1


def test_inventory_keeps_descendants_and_inherited_grants_across_subscriptions():
    other_sub = "33333333-3333-3333-3333-333333333333"
    other_scope = f"/subscriptions/{other_sub}/resourceGroups/network"
    azure = Azure()
    descendant = legacy_assignment(scope=VAULT)
    inherited = legacy_assignment(scope="/providers/Microsoft.Management/managementGroups/platform")
    other = legacy_assignment(scope=other_scope + "/providers/Microsoft.Network/virtualNetworks/network")
    unrelated = legacy_assignment(scope=f"/subscriptions/{SUB}/resourceGroups/unrelated")
    azure.assignments = [descendant, inherited, other, unrelated]
    result = reconcile.inventory(azure, [PROJECT, PROJECT, other_scope])
    assert {item["id"] for item in result} == {item["id"].lower() for item in (descendant, inherited, other)}
    assert len(azure.calls) == 4


def test_migration_is_explicit_exact_and_idempotent(azure):
    legacy = legacy_assignment()
    azure.assignments.append(legacy)
    value = {**manifest(), "adoption": {"legacy_principal_ids": [TENANT],
                                      "approved_role_assignment_ids": [legacy["id"]]}}
    with pytest.raises(access.ProvisioningBlocked, match="execute_migration"):
        access.provision(value, execute=True, cli=azure)
    assert not azure.mutations
    value["adoption"]["execute_migration"] = True
    report = access.provision(value, execute=True, cli=azure)
    assert report["migration"]["removed_assignment_ids"] == [legacy["id"].lower()]
    deleted = [call for call in azure.calls if call[:3] == ("role", "assignment", "delete")]
    assert len(deleted) == 1 and legacy["id"].lower() in deleted[0]
    assert azure.mutations[0][:3] == ("role", "assignment", "delete")
    before = len(azure.mutations)
    assert access.provision(value, execute=True, cli=azure)["state"] == "applied"
    assert len(azure.mutations) == before


def test_migration_refuses_current_content_change_before_any_delete(azure):
    item = legacy_assignment()
    azure.assignments.append(item)
    azure.changed_assignment = {**item, "principalId": GROUPS["persona200"]}
    value = {**manifest(), "adoption": {"legacy_principal_ids": [TENANT], "execute_migration": True,
                                      "approved_role_assignment_ids": [item["id"]]}}
    with pytest.raises(ValueError, match="content changed"):
        access.provision(value, execute=True, cli=azure)
    assert not azure.mutations


@pytest.mark.parametrize("scope", [COMMON, COMMON + "/providers/Microsoft.Network/virtualNetworks/shared"])
def test_migration_refuses_shared_common_grants_even_when_approved(azure, scope):
    item = legacy_assignment(scope=scope)
    azure.assignments.append(item)
    value = {**manifest(), "adoption": {"legacy_principal_ids": [TENANT], "execute_migration": True,
                                      "approved_role_assignment_ids": [item["id"]]}}
    with pytest.raises(access.ProvisioningBlocked, match="project-owned"):
        access.provision(value, execute=True, cli=azure)
    assert not azure.mutations


def test_only_listed_legacy_principal_may_be_removed(azure):
    item = legacy_assignment(principal=GROUPS["persona210"])
    azure.assignments.append(item)
    value = {**manifest(), "adoption": {"legacy_principal_ids": [TENANT], "execute_migration": True,
                                      "approved_role_assignment_ids": [item["id"]]}}
    with pytest.raises(access.ProvisioningBlocked):
        access.provision(value, execute=True, cli=azure)
    assert not azure.mutations


@pytest.mark.parametrize("rbac", [False, None, "true"])
def test_vault_rbac_mode_must_be_explicit_true(azure, rbac):
    azure.rbac = rbac
    with pytest.raises(access.ProvisioningBlocked, match="explicitly use Azure RBAC"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_dormant_vault_policies_must_be_remediated_not_automatically_deleted(azure):
    azure.policies = [{"objectId": TENANT, "permissions": {"secrets": ["all"]}}]
    with pytest.raises(access.ProvisioningBlocked, match="access policies"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


@pytest.mark.parametrize("principal", [TENANT, GROUPS["persona210"], GROUPS["persona216"]])
@pytest.mark.parametrize("rbac", [False, True])
def test_project_reconciliation_blocks_affected_common_vault_policies(azure, principal, rbac):
    common_vault = (COMMON + "/providers/Microsoft.KeyVault/vaults/common-vault").lower()
    azure.resources.append({"id": common_vault, "type": "Microsoft.KeyVault/vaults"})
    azure.vault_overrides[common_vault] = {
        "enableRbacAuthorization": rbac,
        "accessPolicies": [{"objectId": principal, "permissions": {"secrets": ["get"]}}],
    }
    value = {**manifest(), "adoption": {"legacy_principal_ids": [TENANT]}}
    with pytest.raises(access.ProvisioningBlocked, match="access policies") as caught:
        access.provision(value, execute=True, cli=azure)
    inventory = next(item for item in caught.value.report["vaults"] if item["id"] == common_vault)
    assert inventory["affected_access_policies"][0]["objectId"] == principal
    assert not inventory["requires_rbac"]
    assert not azure.mutations


def test_unaffected_common_policy_vault_does_not_require_conversion(azure):
    common_vault = (COMMON + "/providers/Microsoft.KeyVault/vaults/common-vault").lower()
    azure.resources.append({"id": common_vault, "type": "Microsoft.KeyVault/vaults"})
    azure.vault_overrides[common_vault] = {
        "enableRbacAuthorization": False,
        "accessPolicies": [{"objectId": TENANT, "permissions": {"secrets": ["get"]}}],
    }
    report = access.provision(manifest(), execute=True, cli=azure)
    assert report["state"] == "applied"
    inventory = next(item for item in report["vaults"] if item["id"] == common_vault)
    assert not inventory["requires_rbac"]
    assert not inventory["affected_access_policies"]


def test_missing_seeds_duplicates_and_wrong_persona_scope_fail(azure, monkeypatch):
    for resolved in ({}, {"persona999": TENANT}, {key: TENANT for key in GROUPS}):
        monkeypatch.setattr(groups, "resolve_seeded_groups", lambda *args: resolved)
        with pytest.raises(ValueError):
            access.provision(manifest(), cli=azure)
    with pytest.raises(ValueError, match="scope"):
        access.provision(manifest(), scope="all", cli=azure)
    assert not azure.mutations


def test_seed_authorization_errors_are_not_swallowed(azure, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("Forbidden: seed secret get")
    monkeypatch.setattr(groups, "resolve_seeded_groups", unavailable)
    with pytest.raises(RuntimeError, match="Forbidden"):
        access.provision(manifest(), cli=azure)
    assert not azure.calls


def test_subscription_and_discovery_scope_are_verified(azure):
    azure.tenant = SUB
    with pytest.raises(ValueError, match="subscription/tenant"):
        access.provision(manifest(), cli=azure)
    azure.tenant = TENANT
    azure.resources.append({"id": f"/subscriptions/{TENANT}/resourceGroups/project-rg/providers/Microsoft.Web/sites/wrong",
                            "type": "Microsoft.Web/sites"})
    with pytest.raises(ValueError, match="wrong subscription"):
        access.provision(manifest(), cli=azure)
    assert not azure.mutations


def test_privilege_and_security_reviews_are_preconditions(azure):
    azure.permissions = [{"actions": ["*/read"], "notActions": []}]
    report = access.provision(manifest(), cli=azure)
    assert report["state"] == "blocked"
    assert any("Executor prerequisite" in reason for reason in report["blockers"])
    azure.permissions = [{"actions": ["*"], "notActions": []}]
    value = manifest()
    value.pop("security_review")
    with pytest.raises(access.ProvisioningBlocked, match="security_review"):
        access.provision(value, execute=True, cli=azure)
    assert not azure.mutations


def test_lake_blocks_before_any_rbac_mutation(azure, monkeypatch):
    monkeypatch.setattr(lake, "provision_lake", lambda *args: {"state": "blocked", "blockers": ["Shared key enabled"]})
    with pytest.raises(access.ProvisioningBlocked, match="Shared key"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_lake_acl_migration_requires_explicit_flag_before_arm_writes(azure, monkeypatch):
    removals = [{"path": "mlops/v1/projects/project001/environments/dev/source.csv",
                 "entries": [f"user:{TENANT}:r--"]}]
    lake_calls = []
    def preview(manifest, groups, execute, cli):
        lake_calls.append(execute)
        return {"state": "preview", "legacy_acl_removals": removals}
    monkeypatch.setattr(lake, "provision_lake", preview)
    with pytest.raises(access.ProvisioningBlocked, match="legacy lake ACL removals") as caught:
        access.provision(manifest(), execute=True, cli=azure)
    assert caught.value.report["lake"]["legacy_acl_removals"] == removals
    assert caught.value.report["migration"]["legacy_acl_removals"] == removals
    assert not azure.mutations
    assert lake_calls == [False]


def test_explicit_lake_acl_migration_can_reconcile(azure, monkeypatch):
    removals = [{"path": "mlops/v1/projects/project001/environments/dev", "entries": [f"group:{TENANT}:r-x"]}]
    monkeypatch.setattr(lake, "provision_lake",
                        lambda manifest, groups, execute, cli: {
                            "state": "complete" if execute else "preview", "legacy_acl_removals": removals,
                        })
    value = {**manifest(), "adoption": {"execute_migration": True}}
    assert access.provision(value, execute=True, cli=azure)["state"] == "applied"


def test_runtime_write_failure_propagates(azure):
    azure.fail_create = True
    with pytest.raises(RuntimeError, match="AuthorizationFailed"):
        access.provision(manifest(), execute=True, cli=azure)


def test_custom_role_collision_is_not_adopted_or_overwritten(azure):
    role = policy.role_definition("member", PROJECT)
    azure.definitions.append({"name": role["name"], **role["properties"], "description": "somebody else's role"})
    with pytest.raises(access.ProvisioningBlocked, match="not owned"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_descendant_only_unowned_role_guid_is_found_by_direct_get(azure):
    role = policy.role_definition("member", PROJECT)
    azure.definitions.append({"name": role["name"], **role["properties"],
                              "assignableScopes": [VAULT], "description": "another owner's role"})
    assert azure("role", "definition", "list", "--scope", PROJECT.lower(), "--subscription", SUB) == []
    azure.calls.clear()
    with pytest.raises(access.ProvisioningBlocked, match="not owned"):
        access.provision(manifest(), execute=True, cli=azure)
    assert any(call[:1] == ("rest",) and role["name"] in call[call.index("--url") + 1] for call in azure.calls)
    assert not any(call[:3] == ("role", "definition", "list") for call in azure.calls)
    assert not azure.mutations


@pytest.mark.parametrize("error", [
    AzureCLIError("forbidden", status_code=403, error_code="AuthorizationFailed"),
    AzureCLIError("unauthorized", status_code=401, error_code="InvalidAuthenticationToken"),
    AzureCLIError("throttled", status_code=429, error_code="TooManyRequests"),
    AzureCLIError("server failure", status_code=500, error_code="InternalServerError"),
    AzureCLIError("resource group absent", status_code=404, error_code="ResourceGroupNotFound"),
    AzureCLIError("unstructured 404", status_code=404),
    AzureCLIError("wrong status", status_code=403, error_code="RoleDefinitionDoesNotExist"),
    RuntimeError("RoleDefinitionDoesNotExist without verified HTTP status"),
])
def test_role_get_failures_are_not_interpreted_as_an_available_guid(azure, error):
    azure.role_get_error = error
    with pytest.raises(RuntimeError) as caught:
        access.provision(manifest(), execute=True, cli=azure)
    assert caught.value is error
    assert not azure.mutations


@pytest.mark.parametrize("stderr,status,code", [
    ('ERROR: Not Found({"error":{"code":"RoleDefinitionDoesNotExist"}})', 404, "RoleDefinitionDoesNotExist"),
    ('ERROR: Not Found\r\n{"error":{"code":"RoleDefinitionNotFound"}}', 404, "RoleDefinitionNotFound"),
    ('ERROR: Forbidden({"error":{"code":"AuthorizationFailed"}})', None, "AuthorizationFailed"),
    ('ERROR: Request failed; the message mentions 404', None, None),
])
def test_cli_preserves_precise_error_metadata(monkeypatch, stderr, status, code):
    from types import SimpleNamespace
    monkeypatch.setattr(cli_module.shutil, "which", lambda _: "az")
    monkeypatch.setattr(cli_module.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=stderr, stdout=""))
    with pytest.raises(AzureCLIError) as caught:
        cli_module.azure_cli("rest", "--method", "get")
    assert caught.value.status_code == status
    assert caught.value.error_code == code


def test_unrelated_assignments_are_never_removed_or_claimed(azure):
    unrelated = legacy_assignment()
    azure.assignments.append(unrelated)
    report = access.provision(manifest(), execute=True, cli=azure)
    assert unrelated in azure.assignments
    assert unrelated["id"].lower() not in {
        identity for item in report["assignments"]
        for identity in item["owned_assignment_ids"] + item["adopted_assignment_ids"]
    }
    assert not any(call[:3] == ("role", "assignment", "delete") for call in azure.calls)


def test_conditioned_assignment_is_not_silently_replaced_with_unconditional_grant(azure):
    target = access.provision(manifest(), cli=azure)["assignments"][0]
    azure.assignments.append({**target, "condition": "restrict access", "conditionVersion": "2.0"})
    with pytest.raises(access.ProvisioningBlocked):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_deterministic_assignment_collision_is_not_overwritten(azure):
    desired = access.provision(manifest(), cli=azure)["assignments"][0]
    azure.assignments.append({**desired, "principalId": TENANT})
    with pytest.raises(access.ProvisioningBlocked, match="collision"):
        access.provision(manifest(), execute=True, cli=azure)
    assert not azure.mutations


def test_owned_custom_role_drift_is_reconciled(azure):
    role = policy.role_definition("member", PROJECT)
    azure.definitions.append({"name": role["name"], **role["properties"], "permissions": []})
    assert access.provision(manifest(), execute=True, cli=azure)["state"] == "applied"
    restored = next(item for item in azure.definitions if item["name"] == role["name"])
    assert restored["permissions"] == role["properties"]["permissions"]


@pytest.mark.parametrize("initially_present", [False, True])
def test_final_audit_refuses_recreated_approved_legacy_grant(azure, monkeypatch, initially_present):
    item = legacy_assignment()
    if initially_present:
        azure.assignments.append(item)
    azure.recreate_on_create = item
    lake_calls = []
    monkeypatch.setattr(lake, "provision_lake",
                        lambda manifest, groups, execute, cli: lake_calls.append(execute) or {"state": "preview"})
    value = {**manifest(), "adoption": {
        "legacy_principal_ids": [TENANT], "approved_role_assignment_ids": [item["id"]],
        "execute_migration": True,
    }}
    with pytest.raises(access.ProvisioningBlocked, match="remains or was recreated") as caught:
        access.provision(value, execute=True, cli=azure)
    report = caught.value.report
    assert report["state"] == "incomplete"
    assert [pending["id"] for pending in report["migration"]["pending_removals"]] == [item["id"].lower()]
    assert lake_calls == [False]


def test_unpropagated_legacy_removal_is_reported_incomplete(azure):
    item = legacy_assignment()
    azure.assignments.append(item)
    azure.ignore_deletes = True
    value = {**manifest(), "adoption": {
        "legacy_principal_ids": [TENANT], "approved_role_assignment_ids": [item["id"]],
        "execute_migration": True,
    }}
    with pytest.raises(access.ProvisioningBlocked, match="not yet visible") as caught:
        access.provision(value, execute=True, cli=azure)
    assert caught.value.report["state"] == "incomplete"
    assert caught.value.report["migration"]["pending_removals"]
    assert not caught.value.report["migration"]["removed_assignment_ids"]
