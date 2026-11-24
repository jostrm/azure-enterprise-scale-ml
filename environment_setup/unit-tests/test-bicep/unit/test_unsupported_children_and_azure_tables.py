"""Two narrow rules for the aif68 project001 continuation (ADO run 2526, approved 2026-11-24).

Rule U (Prepare and the Execute re-preview): ARM what-if lists a role assignment whose name needs a principal the
same deployment creates as `Unsupported`, with an unevaluated id. Such a row passes only when its id sits strictly
under a resource the same preview reports as Create inside the plan's own locked groups. Every other Unsupported
row still blocks and is named on stderr.

Rule T (Execute ownership walk): Azure creates Log Analytics tables (AzureDiagnostics) in a workspace after the
receipt that deployed the workspace, untagged. Such a table is owned only through its parent workspace's verified
receipt; no other child type and no table of a workspace without that evidence.
"""

import json
import sys
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import fl, ROOT, GROUP, COMMON, SUB, scoped_manifest

sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))

OWN = {GROUP.lower()}
STORAGE = GROUP + "/providers/Microsoft.Storage/storageAccounts/saprj001"
SEARCH = GROUP + "/providers/Microsoft.Search/searchServices/search-prj001"
ACR = GROUP + "/providers/Microsoft.ContainerRegistry/registries/acrcommon"
FOUNDRY = GROUP + "/providers/Microsoft.CognitiveServices/accounts/aif2foundry"
COSMOS = GROUP + "/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-prj001"
COMMON_VAULT = COMMON + "/providers/Microsoft.KeyVault/vaults/kv-common"
FOREIGN_VAULT = "/subscriptions/" + SUB + "/resourceGroups/someone-else/providers/Microsoft.KeyVault/vaults/kv-other"
IDENTITY = GROUP + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi-prj001"
ROLE = "/subscriptions/" + SUB + "/providers/Microsoft.Authorization/roleDefinitions/7f951dda-4ed3-4680-a7ca-43fe172d538d"


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    monkeypatch.setattr(fl.subprocess, "run", Mock(side_effect=AssertionError("Real commands forbidden")))
    monkeypatch.setattr(fl, "build_opener", Mock(side_effect=AssertionError("Real HTTP forbidden")))


def role_assignment(scope, function="extensionResourceId"):
    """An Unsupported row exactly as what-if lists a role assignment for a principal the deployment creates."""
    expression = (f"[{function}('{scope}', 'Microsoft.Authorization/roleAssignments', guid('rbac', "
                  f"reference('{IDENTITY}', '2024-11-30').principalId, '{ROLE}'))]")
    return {"resourceId": expression, "changeType": "Unsupported",
            "unsupportedReason": "Changes to the resource declared at 'properties.template.resources[3]' on line 1 "
                                 "and column 9 cannot be analyzed because its resource ID or API version cannot be "
                                 "calculated until the deployment is under way.",
            "after": {"id": expression, "type": "Microsoft.Authorization/roleAssignments", "apiVersion": "2022-04-01"}}


def change(identifier, change_type, after=None):
    return {"resourceId": identifier, "changeType": change_type, "before": None if change_type == "Create" else {},
            "after": {"id": identifier} if after is None else after}


def preview(*rows):
    return {"properties": {"changes": list(rows)}}


def unsupported_events(capsys):
    return [event for event in (json.loads(line) for line in capsys.readouterr().err.splitlines()
                                if line.startswith("{")) if event.get("event") == "unsupported-resource-unproven"]


# Rule U -------------------------------------------------------------------------------------------------------------

def test_role_assignment_on_a_resource_the_same_preview_creates_is_accepted_and_kept_out_of_the_reviewed_rows():
    rows = fl.arm_changes(preview(change(STORAGE, "Create"), role_assignment(STORAGE), role_assignment(SEARCH),
                                  change(SEARCH, "Create")), None, OWN)
    assert [row["resource_id"] for row in rows] == sorted([STORAGE.lower(), SEARCH.lower()])
    assert {row["change_type"] for row in rows} == {"Create"}


def test_literal_unsupported_child_strictly_under_a_created_resource_is_accepted():
    child = STORAGE + "/blobServices/default/containers/data"
    rows = fl.arm_changes(preview(change(STORAGE, "Create"), {"resourceId": child, "changeType": "Unsupported",
                                                              "unsupportedReason": "unknown"}), None, OWN)
    assert [row["resource_id"] for row in rows] == [STORAGE.lower()]


@pytest.mark.parametrize("rows", [
    # The two common-registry rows of run 2526: the registry is Modify, it exists before the run.
    [change(ACR, "Modify"), role_assignment(ACR)],
    [change(ACR, "NoChange"), role_assignment(ACR)],
    # The Foundry account is not a row of this preview at all.
    [change(STORAGE, "Create"), role_assignment(FOUNDRY)],
    # Created, but outside the plan's own locked groups.
    [change(COMMON_VAULT, "Create"), role_assignment(COMMON_VAULT)],
    [change(FOREIGN_VAULT, "Create"), role_assignment(FOREIGN_VAULT)],
    # A name prefix is not a parent.
    [change(STORAGE, "Create"), role_assignment(STORAGE + "x")],
    # The created resource itself, not strictly under it.
    [change(STORAGE, "Create"), {"resourceId": STORAGE + "/x/y", "changeType": "Create"},
     {"resourceId": STORAGE, "changeType": "Unsupported", "unsupportedReason": "unknown"}],
], ids=["parent-modify", "parent-nochange", "parent-absent", "common-group", "foreign-group", "name-prefix", "self"])
def test_unsupported_row_without_a_created_parent_in_the_plans_groups_still_blocks_and_is_named(rows, capsys):
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(*rows), None, OWN)
    events = unsupported_events(capsys)
    assert len(events) == 1 and events[0]["count"] == 1
    assert events[0]["rows"][0]["reason"] == "no-created-parent"


@pytest.mark.parametrize("identifier", [
    # Computed names (the Cosmos sqlRoleAssignment of run 2526) and wrapped expressions are never parsed.
    f"[resourceId('{SUB}', 'reviewed', 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments', "
    f"split(format('{{0}}/{{1}}', 'cosmos-prj001', guid('x')), '/')[0], 'y')]",
    f"[concat(extensionResourceId('{STORAGE}', 'Microsoft.Authorization/roleAssignments', 'x'), '/../../other')]",
    f"[extensionResourceId(parameters('scope'), 'Microsoft.Authorization/roleAssignments', 'x')]",
    "not-an-arm-id",
], ids=["computed-resource-id", "wrapped-expression", "non-literal-scope", "garbage"])
def test_unsupported_row_with_an_unparsed_id_still_blocks(identifier, capsys):
    rows = [change(STORAGE, "Create"), change(COSMOS, "Create"),
            {"resourceId": identifier, "changeType": "Unsupported", "unsupportedReason": "unknown"}]
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(*rows), None, OWN)
    assert unsupported_events(capsys)[0]["rows"][0]["reason"] == "unparsed-resource-id"


def test_refusal_names_every_unaccepted_row_with_its_parent_and_type_but_never_an_accepted_one(capsys):
    rows = [change(STORAGE, "Create"), role_assignment(STORAGE), change(ACR, "Modify"), role_assignment(ACR),
            role_assignment(FOUNDRY)]
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(*rows), None, OWN)
    event = unsupported_events(capsys)[0]
    assert event["count"] == 2
    assert [(row["under"], row["type"]) for row in event["rows"]] == [
        (ACR.lower(), "microsoft.authorization/roleassignments"),
        (FOUNDRY.lower(), "microsoft.authorization/roleassignments")]
    assert {row["declared"] for row in event["rows"]} == {"properties.template.resources[3]"}


def test_without_the_plans_groups_every_unsupported_row_blocks_as_before():
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(change(STORAGE, "Create"), role_assignment(STORAGE)))
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(change(STORAGE, "Create"), role_assignment(STORAGE)), None, set())


def test_delete_and_deploy_rows_still_block_under_a_created_parent():
    for kind in ("Delete", "Deploy", "None"):
        with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
            fl.arm_changes(preview(change(STORAGE, "Create"), change(STORAGE + "/fileServices/default", kind)),
                           None, OWN)


def test_unsupported_row_with_an_error_still_blocks():
    row = {**role_assignment(STORAGE), "error": {"code": "InvalidTemplate"}}
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(change(STORAGE, "Create"), row), None, OWN)


def test_evaluate_what_if_applies_rule_u_with_the_plans_own_groups():
    document, _ = scoped_manifest()
    document["deployment"] = {"steps": [{"id": "s", "resource_groups": [GROUP]}]}
    accepted = fl.evaluate_what_if(None, document, {"id": "factory", "scope": "subscription"}, None,
                                   response=preview(change(STORAGE, "Create"), role_assignment(STORAGE)))
    assert [row["resource_id"] for row in accepted] == [STORAGE.lower()]
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.evaluate_what_if(None, document, {"id": "factory", "scope": "subscription"}, None,
                            response=preview(change(COMMON_VAULT, "Create"), role_assignment(COMMON_VAULT)))


# Rule T -------------------------------------------------------------------------------------------------------------

RUN = "11111111-2222-4333-8444-555555555555"
WORKSPACE = (COMMON + "/providers/Microsoft.OperationalInsights/workspaces/la-common").lower()
TABLE = WORKSPACE + "/tables/azurediagnostics"
VAULT = (COMMON + "/providers/Microsoft.KeyVault/vaults/kv-common").lower()
SECRET = VAULT + "/secrets/created-later"
TARGET = {"factory_id": "factory-a", "scaleset_id": "Stage001"}


def receipt(rows, target=TARGET):
    return {"schema": 1, "run_id": RUN, "status": "succeeded", "manifest_hash": fl.digest({"m": 1}),
            "target": dict(target), "ownership": rows}


class Receipts:
    def __init__(self, body):
        self.body, self.reads = body, 0

    def request(self, method, name, data=None, headers=None, allowed=(200,), query=""):
        assert method == "GET" and name == "runs/" + RUN + ".worker.json"
        self.reads += 1
        return 200, {}, json.loads(json.dumps(self.body))


def walk(rows, known_ids, closure_ids, target=TARGET):
    body = receipt(rows, target)
    evidence = {"run_id": RUN, "receipt_hash": fl.digest(body)}
    known = {key: dict(evidence) for key in known_ids}
    resources = {key: {"body_hash": fl.digest({"id": key})} for key in closure_ids}
    return Receipts(body), known, resources


def owned(identifier, owner=TARGET):
    return {"resource_id": identifier, "owner": dict(owner), "body_hash": fl.digest({"id": identifier})}


def test_untagged_azure_created_table_is_owned_through_its_workspaces_verified_receipt():
    locks, known, resources = walk([owned(WORKSPACE)], [WORKSPACE], [WORKSPACE, TABLE])
    cache = {}
    assert fl.existing_receipt_owner(locks, known, TABLE, resources, cache) == TARGET
    assert fl.existing_receipt_owner(locks, known, WORKSPACE, resources, cache) == TARGET
    assert locks.reads == 1


def test_a_table_with_evidence_of_its_own_uses_its_own_receipt_row():
    locks, known, resources = walk([owned(TABLE)], [TABLE], [WORKSPACE, TABLE])
    assert fl.existing_receipt_owner(locks, known, TABLE, resources, {}) == TARGET


def test_table_of_a_workspace_without_receipt_evidence_still_blocks():
    locks, known, resources = walk([owned(WORKSPACE)], [], [WORKSPACE, TABLE])
    with pytest.raises(fl.Blocked, match="child-ownership-evidence-required"):
        fl.existing_receipt_owner(locks, known, TABLE, resources, {})


def test_table_whose_workspace_is_not_in_the_closure_still_blocks():
    locks, known, resources = walk([owned(WORKSPACE)], [WORKSPACE], [TABLE])
    with pytest.raises(fl.Blocked, match="child-ownership-evidence-required"):
        fl.existing_receipt_owner(locks, known, TABLE, resources, {})


def test_table_of_a_workspace_changed_since_its_receipt_still_blocks():
    locks, known, resources = walk([owned(WORKSPACE)], [WORKSPACE], [WORKSPACE, TABLE])
    resources[WORKSPACE]["body_hash"] = fl.digest({"changed": True})
    with pytest.raises(fl.Blocked, match="child-instance-ownership-unverified"):
        fl.existing_receipt_owner(locks, known, TABLE, resources, {})


def test_table_of_a_workspace_another_receipt_target_owns_still_blocks():
    foreign = {"factory_id": "factory-b", "scaleset_id": "Stage001"}
    locks, known, resources = walk([owned(WORKSPACE, foreign)], [WORKSPACE], [WORKSPACE, TABLE])
    with pytest.raises(fl.Blocked, match="child-receipt-target-mismatch"):
        fl.existing_receipt_owner(locks, known, TABLE, resources, {})


def test_other_untagged_child_types_never_inherit_their_parents_receipt():
    locks, known, resources = walk([owned(VAULT)], [VAULT], [VAULT, SECRET])
    with pytest.raises(fl.Blocked, match="child-ownership-evidence-required"):
        fl.existing_receipt_owner(locks, known, SECRET, resources, {})


def test_execute_ownership_walk_calls_the_single_rule_t_helper():
    source = (ROOT / "bootstrap" / "lib" / "factory_lifecycle.py").read_text(encoding="utf-8")
    walk_start = source.index('evidence = document["deployment"].get("known_ownership", {}).get(key, {})')
    walk = source[walk_start:walk_start + 900]
    assert "existing_receipt_owner(locks, document[\"deployment\"].get(\"known_ownership\", {}), key," in walk
    assert source.count("AZURE_CREATED_TABLE_TYPE") == 2
