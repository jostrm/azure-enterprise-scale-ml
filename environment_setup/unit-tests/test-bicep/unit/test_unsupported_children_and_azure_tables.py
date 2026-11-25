"""Two narrow rules for the aif68 project001 continuation (ADO run 2526, approved 2026-11-24).

Rule U (Prepare and the Execute re-preview): ARM what-if lists a role assignment whose name needs a principal the
same deployment creates as `Unsupported`, with an unevaluated id. Such a row passes only when its id sits strictly
under a resource the same preview reports as Create inside the plan's own locked groups. Every other Unsupported
row still blocks and is named on stderr.

Rule R (same place as Rule U, approved 2026-11-25): what-if cannot compute the guid()-named id of a role assignment
(Microsoft.Authorization/roleAssignments or a Cosmos sqlRoleAssignment) and lists it as `Unsupported`. Such a row
only adds access and comes from the reviewed, pinned template, so it passes when its own literal id deploys it into
one of the plan's own locked groups. Any other type, an error or delta, an unknown or contradicting group, or a group
outside the plan still blocks.

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
ROLE_ASSIGNMENT = "Microsoft.Authorization/roleAssignments"
# Not a role assignment: keeps the Rule U refusals meaningful now that Rule R accepts role assignments in own groups.
LOCK = "Microsoft.Authorization/locks"


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    monkeypatch.setattr(fl.subprocess, "run", Mock(side_effect=AssertionError("Real commands forbidden")))
    monkeypatch.setattr(fl, "build_opener", Mock(side_effect=AssertionError("Real HTTP forbidden")))


def role_assignment(scope, function="extensionResourceId", kind=ROLE_ASSIGNMENT):
    """An Unsupported row exactly as what-if lists a role assignment for a principal the deployment creates."""
    expression = (f"[{function}('{scope}', '{kind}', guid('rbac', "
                  f"reference('{IDENTITY}', '2024-11-30').principalId, '{ROLE}'))]")
    return {"resourceId": expression, "changeType": "Unsupported",
            "unsupportedReason": "Changes to the resource declared at 'properties.template.resources[3]' on line 1 "
                                 "and column 9 cannot be analyzed because its resource ID or API version cannot be "
                                 "calculated until the deployment is under way.",
            "after": {"id": expression, "type": kind, "apiVersion": "2022-04-01"}}


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
    # A non-role child (Rule R accepts role assignments in the plan's groups): the parent is Modify, it exists before.
    [change(ACR, "Modify"), role_assignment(ACR, kind=LOCK)],
    [change(ACR, "NoChange"), role_assignment(ACR, kind=LOCK)],
    # The parent is not a row of this preview at all.
    [change(STORAGE, "Create"), role_assignment(FOUNDRY, kind=LOCK)],
    # Created, but outside the plan's own locked groups (Rule R does not apply there either).
    [change(COMMON_VAULT, "Create"), role_assignment(COMMON_VAULT)],
    [change(FOREIGN_VAULT, "Create"), role_assignment(FOREIGN_VAULT)],
    # A name prefix is not a parent.
    [change(STORAGE, "Create"), role_assignment(STORAGE + "x", kind=LOCK)],
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
    rows = [change(STORAGE, "Create"), role_assignment(STORAGE), change(ACR, "Modify"), role_assignment(ACR, kind=LOCK),
            role_assignment(FOUNDRY, kind=LOCK)]
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(*rows), None, OWN)
    event = unsupported_events(capsys)[0]
    assert event["count"] == 2
    assert [(row["under"], row["type"]) for row in event["rows"]] == [
        (ACR.lower(), "microsoft.authorization/locks"), (FOUNDRY.lower(), "microsoft.authorization/locks")]
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


# Rule R -------------------------------------------------------------------------------------------------------------

OWN_WITH_COMMON = {GROUP.lower(), COMMON.lower()}
ACR_COMMON = COMMON + "/providers/Microsoft.ContainerRegistry/registries/acrcommon"
COSMOS_SQL = "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments"
OTHER_SUB = "cccccccc-cccc-cccc-cccc-cccccccccccc"
AT = "properties.template.resources[{}].properties.template.resources[{}]"


def declared_at(position):
    return (f"Changes to the resource declared at '{position}' on line 1 and column 197684 cannot be analyzed because "
            "its resource ID or API version cannot be calculated until the deployment is under way.")


def unsupported(expression, position, after):
    """The full Unsupported row shape of run 2526."""
    return {"after": after, "before": None, "changeType": "Unsupported", "delta": None, "deploymentId": None,
            "extension": None, "identifiers": None, "resourceId": expression, "symbolicName": None,
            "unsupportedReason": declared_at(position)}


def scoped_role_assignment(target, group_name, position=AT.format(14, 0), scope_expression=None, **after_fields):
    """The AcrPull rows on the common registry and the Foundry account row of run 2526."""
    principal = f"reference('{IDENTITY}', '2024-11-30').principalId"
    expression = (f"[extensionResourceId({scope_expression or repr(target)}, '{ROLE_ASSIGNMENT}', "
                  f"guid('02-miRbacCmnACR-aif', 'acrcommon', {principal}, '{ROLE}'))]")
    after = {"apiVersion": "2022-04-01", "id": expression, "name": f"[last(split(guid('x', {principal}), '/'))]",
             "properties": {"principalId": f"[{principal}]", "principalType": "ServicePrincipal",
                            "roleDefinitionId": ROLE},
             "resourceGroup": group_name, "type": ROLE_ASSIGNMENT, **after_fields}
    return unsupported(expression, position, {key: value for key, value in after.items() if value is not None})


def cosmos_role_assignment(subscription=SUB, group_name="reviewed", kind=COSMOS_SQL, head=None, **after_fields):
    """The Cosmos sqlRoleAssignment row of run 2526: resourceId with a literal subscription and group, computed name."""
    account = (f"/subscriptions/{subscription}/resourceGroups/{group_name}/providers/Microsoft.DocumentDB/"
               "databaseAccounts/cosmos-prj001")
    principal = f"reference('{FOUNDRY}/projects/p001', '2025-04-01-preview', 'full').identity.principalId"
    split = (f"split(format('{{0}}/{{1}}', 'cosmos-prj001', guid({principal}, '{account}/sqlRoleDefinitions/"
             f"00000000-0000-0000-0000-000000000001', '{account}')), '/')")
    name = f"filter({split}, lambda('x', not(empty(lambdaVariables('x')))))"
    expression = f"[resourceId({head or repr(subscription) + ', ' + repr(group_name)}, '{kind}', {name}[0], {name}[1])]"
    after = {"apiVersion": "2024-12-01-preview", "id": expression, "name": f"[last({split})]",
             "properties": {"principalId": f"[{principal}]", "scope": account,
                            "roleDefinitionId": account + "/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001"},
             "type": COSMOS_SQL, **after_fields}
    return unsupported(expression, AT.format(16, 1), {key: value for key, value in after.items() if value is not None})


def rule_r_rows(event):
    return [(row["rule_r"], row["group"]) for row in event["rows"]]


def test_rule_r_accepts_the_four_role_assignment_rows_of_run_2526_and_keeps_them_out_of_the_reviewed_rows(capsys):
    rows = fl.arm_changes(preview(
        change(ACR_COMMON, "Modify"),
        scoped_role_assignment(ACR_COMMON, "common", AT.format(14, 0)),
        scoped_role_assignment(ACR_COMMON, "common", AT.format(15, 0)),
        change(STORAGE, "Create"),
        scoped_role_assignment(FOUNDRY, "reviewed", AT.format(18, 0)),
        cosmos_role_assignment()), None, OWN_WITH_COMMON)
    assert [(row["resource_id"], row["change_type"]) for row in rows] == sorted(
        [(ACR_COMMON.lower(), "Modify"), (STORAGE.lower(), "Create")])
    assert unsupported_events(capsys) == []


@pytest.mark.parametrize("row", [
    scoped_role_assignment(ACR_COMMON, "common"),
    scoped_role_assignment(FOUNDRY, "reviewed"),
    scoped_role_assignment(FOUNDRY, None),
    cosmos_role_assignment(),
    cosmos_role_assignment(kind=ROLE_ASSIGNMENT, type=ROLE_ASSIGNMENT),
], ids=["acr-on-existing-common-registry", "foundry-account-outside-the-preview", "without-after-resource-group",
        "cosmos-sql-role-assignment", "resource-group-role-assignment"])
def test_rule_r_accepts_a_role_assignment_its_own_id_deploys_into_a_locked_group_without_any_created_parent(row):
    assert fl.arm_changes(preview(row), None, OWN_WITH_COMMON) == []


@pytest.mark.parametrize("own, row, verdict, group", [
    # The literal group is known but not one of the plan's own locked groups.
    (OWN, scoped_role_assignment(ACR_COMMON, "common"), "outside-locked-groups", COMMON.lower()),
    (OWN_WITH_COMMON, scoped_role_assignment(FOREIGN_VAULT, "someone-else"), "outside-locked-groups",
     FOREIGN_VAULT.rsplit("/providers/", 1)[0].lower()),
    (OWN_WITH_COMMON, cosmos_role_assignment(group_name="someone-else"), "outside-locked-groups",
     f"/subscriptions/{SUB}/resourcegroups/someone-else"),
    (OWN_WITH_COMMON, cosmos_role_assignment(subscription=OTHER_SUB), "outside-locked-groups",
     f"/subscriptions/{OTHER_SUB}/resourcegroups/reviewed"),
    # The deploying group cannot be determined, or the row contradicts it.
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, "common"), "no-deploying-group", None),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, "reviewed", subscriptionId=OTHER_SUB), "no-deploying-group",
     None),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, "reviewed", scope="[parameters('scope')]"), "no-deploying-group",
     None),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, "reviewed", id="[other()]"), "no-deploying-group", None),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, None, scope_expression="parameters('scope')"),
     "no-deploying-group", None),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, None, scope_expression=f"'{GROUP}'"), "no-deploying-group", None),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, None, scope_expression=f"'{FOUNDRY}'', ''x'"),
     "no-deploying-group", None),
    (OWN_WITH_COMMON, cosmos_role_assignment(head=f"'{SUB}', parameters('rg')"), "no-deploying-group", None),
    (OWN_WITH_COMMON, cosmos_role_assignment(head="'reviewed'"), "no-deploying-group", None),
    (OWN_WITH_COMMON, cosmos_role_assignment(head="subscription().subscriptionId, 'reviewed'"), "no-deploying-group",
     None),
    (OWN_WITH_COMMON, cosmos_role_assignment(resourceGroup="common"), "no-deploying-group", None),
    # Not a role assignment, or the row does not carry the same role-assignment type in its id and its body.
    (OWN_WITH_COMMON, role_assignment(STORAGE, kind=LOCK), "not-role-assignment", GROUP.lower()),
    (OWN_WITH_COMMON, cosmos_role_assignment(kind="Microsoft.DocumentDB/databaseAccounts/sqlDatabases",
                                             type="Microsoft.DocumentDB/databaseAccounts/sqlDatabases"),
     "not-role-assignment", GROUP.lower()),
    (OWN_WITH_COMMON, scoped_role_assignment(FOUNDRY, "reviewed", type=LOCK), "not-role-assignment", GROUP.lower()),
    (OWN_WITH_COMMON, cosmos_role_assignment(kind=LOCK), "not-role-assignment", GROUP.lower()),
    (OWN_WITH_COMMON, {**cosmos_role_assignment(), "after": None}, "no-deploying-group", None),
    # Errors and deltas are never accepted.
    (OWN_WITH_COMMON, {**cosmos_role_assignment(), "error": {"code": "InvalidTemplate"}}, "error-or-delta",
     GROUP.lower()),
    (OWN_WITH_COMMON, {**scoped_role_assignment(FOUNDRY, "reviewed"), "delta": [{"path": "properties"}]},
     "error-or-delta", GROUP.lower()),
], ids=["common-outside-plan", "foreign-group", "cosmos-foreign-group", "cosmos-foreign-subscription",
        "after-group-contradicts-scope", "after-subscription-contradicts-scope", "after-scope-property",
        "after-id-contradicts", "non-literal-scope", "group-scope-not-a-resource", "quoted-literal-trick",
        "non-literal-group", "group-without-subscription", "computed-subscription", "cosmos-after-group-contradicts",
        "lock-in-own-group", "cosmos-non-role-type", "after-type-contradicts", "id-type-contradicts", "no-after",
        "error", "delta"])
def test_rule_r_still_blocks_and_names_a_row_without_evidence_of_a_role_assignment_in_a_locked_group(
        own, row, verdict, group, capsys):
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(row), None, own)
    event = unsupported_events(capsys)[0]
    assert event["count"] == 1 and rule_r_rows(event) == [(verdict, group)]


@pytest.mark.parametrize("expression", [
    f"[concat(resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', 'b'), '/../../other')]",
    f"[if(true(), resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', 'b'), 'x')]",
    f"[resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', 'b'), resourceId('{OTHER_SUB}', 'x', 'y')]",
    f"[resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', 'b')",
    f"[resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', 'b)]",
    f"[resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', ['b')])]",
    f"[[resourceId('{SUB}', 'reviewed', '{COSMOS_SQL}', 'a', 'b')]",
], ids=["wrapped-concat", "wrapped-if", "call-closes-early", "unterminated", "unterminated-string",
        "mismatched-brackets", "escaped-literal"])
def test_rule_r_reads_the_group_only_from_one_whole_literal_call(expression, capsys):
    row = cosmos_role_assignment()
    row = {**row, "resourceId": expression, "after": {**row["after"], "id": expression}}
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(row), None, OWN_WITH_COMMON)
    assert rule_r_rows(unsupported_events(capsys)[0]) == [("no-deploying-group", None)]


ROLE_ID = FOUNDRY + "/providers/Microsoft.Authorization/roleAssignments/0f7b8c1e-0000-4000-8000-000000002526"
SQL_ROLE_ID = COSMOS + "/sqlRoleAssignments/0f7b8c1e-0000-4000-8000-000000002526"


@pytest.mark.parametrize("kind", ["Delete", "Deploy", "None"])
@pytest.mark.parametrize("identifier", [ROLE_ID, SQL_ROLE_ID], ids=["role-assignment", "sql-role-assignment"])
def test_destructive_or_deploy_rows_of_a_role_assignment_in_a_locked_group_still_block(identifier, kind):
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(change(identifier, kind, after={"id": identifier, "type": ROLE_ASSIGNMENT})),
                       None, OWN_WITH_COMMON)


def test_without_the_plans_groups_rule_r_rows_block_as_before():
    for row in (cosmos_role_assignment(), scoped_role_assignment(ACR_COMMON, "common")):
        for groups in (None, set()):
            with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
                fl.arm_changes(preview(row), None, groups)


def test_refusal_names_only_the_rows_rule_u_and_rule_r_both_refuse(capsys):
    rows = [change(STORAGE, "Create"), role_assignment(STORAGE), cosmos_role_assignment(),
            scoped_role_assignment(ACR_COMMON, "common"), role_assignment(FOUNDRY, kind=LOCK),
            cosmos_role_assignment(group_name="someone-else")]
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes(preview(*rows), None, OWN)
    event = unsupported_events(capsys)[0]
    assert event["count"] == 3
    assert [(row["reason"], row["type"], row["rule_r"], row["group"], row["declared"]) for row in event["rows"]] == [
        ("no-created-parent", "microsoft.authorization/roleassignments", "outside-locked-groups", COMMON.lower(),
         AT.format(14, 0)),
        ("no-created-parent", "microsoft.authorization/locks", "not-role-assignment", GROUP.lower(),
         "properties.template.resources[3]"),
        ("unparsed-resource-id", "microsoft.documentdb/databaseaccounts/sqlroleassignments", "outside-locked-groups",
         f"/subscriptions/{SUB}/resourcegroups/someone-else", AT.format(16, 1))]


def test_evaluate_what_if_applies_rule_r_with_the_plans_own_groups():
    document, _ = scoped_manifest()
    document["deployment"] = {"steps": [{"id": "s", "resource_groups": [GROUP]}]}
    step = {"id": "factory", "scope": "subscription"}
    accepted = fl.evaluate_what_if(None, document, step, None, response=preview(
        change(STORAGE, "Create"), cosmos_role_assignment(), scoped_role_assignment(FOUNDRY, "reviewed")))
    assert [row["resource_id"] for row in accepted] == [STORAGE.lower()]
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.evaluate_what_if(None, document, step, None, response=preview(
            change(STORAGE, "Create"), scoped_role_assignment(ACR_COMMON, "common")))


def test_rule_r_lives_in_the_single_unsupported_decision_of_arm_changes():
    source = (ROOT / "bootstrap" / "lib" / "factory_lifecycle.py").read_text(encoding="utf-8")
    assert source.count("ROLE_ASSIGNMENT_UNSUPPORTED_TYPES") == 2
    assert source.count("unsupported_row_accepted(") == 3
    body = source[source.index("def arm_changes("):source.index("def ", source.index("def arm_changes(") + 1)]
    assert body.count("unsupported_row_accepted(change, created, own_groups)") == 1


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
