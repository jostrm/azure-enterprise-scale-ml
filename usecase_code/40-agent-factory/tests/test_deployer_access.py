"""The late agent steps (70 chat agent, 72 live voice) grant the deploying service principal its own data-plane roles."""
from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_factory import deployer_access as access  # noqa: E402
from agent_factory.azure import ARM  # noqa: E402

SUB = "11111111-1111-4111-8111-111111111111"
GROUP_ID = f"/subscriptions/{SUB}/resourceGroups/aif-esml-project007-sdc-dev-001-rg"
ACCOUNT_ID = f"{GROUP_ID}/providers/Microsoft.CognitiveServices/accounts/aifacct007"
STORAGE_ID = f"{GROUP_ID}/providers/Microsoft.Storage/storageAccounts/saprj007"
SEARCH_ID = f"{GROUP_ID}/providers/Microsoft.Search/searchServices/aisearchprj007"
PRINCIPAL = "33333333-3333-4333-8333-333333333333"


def assignment(scope, role):
    return {"properties": {"scope": scope, "principalId": PRINCIPAL,
                           "roleDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{role}"}}


class FakeArm:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.calls = []

    def pages(self, url, *, audience=ARM, field="value"):
        self.calls.append(("LIST", url))
        assert f"principalId eq '{PRINCIPAL}'" in url.replace("%20", " ")
        return copy.deepcopy(self.existing)

    def arm(self, method, resource_id, body=None, api_version="x"):
        self.calls.append((method, resource_id, copy.deepcopy(body)))
        return {"id": resource_id, **(body or {})}

    def puts(self):
        return [call for call in self.calls if call[0] == "PUT"]


def deployer(arm, *, service_principal=True, sleeps=None):
    return access.DeployerAccess(arm, lambda: (PRINCIPAL, service_principal),
                                 sleep=(sleeps.append if sleeps is not None else lambda _: None))


def test_missing_roles_are_granted_to_the_service_principal_then_propagation_is_awaited_once():
    arm, sleeps = FakeArm(), []
    needs = [access.foundry_user(ACCOUNT_ID), access.blob_container_contributor(STORAGE_ID, "aifactory-agent"),
             access.search_index_contributor(SEARCH_ID)]
    rows = deployer(arm, sleeps=sleeps).ensure(needs, apply=True)
    puts = arm.puts()
    assert [row["status"] for row in rows] == ["created", "created", "created"]
    assert [put[1].split("/providers/Microsoft.Authorization/")[0] for put in puts] == [
        ACCOUNT_ID, f"{STORAGE_ID}/blobServices/default/containers/aifactory-agent", SEARCH_ID]
    assert {put[2]["properties"]["roleDefinitionId"].rsplit("/", 1)[1] for put in puts} == {
        access.FOUNDRY_USER, access.STORAGE_BLOB_DATA_CONTRIBUTOR, access.SEARCH_INDEX_DATA_CONTRIBUTOR}
    assert all(put[2]["properties"]["principalType"] == "ServicePrincipal"
               and put[2]["properties"]["principalId"] == PRINCIPAL for put in puts)
    assert sleeps == [access.PROPAGATION_SECONDS]


def test_assignment_names_are_deterministic_so_reruns_never_duplicate():
    first, second = FakeArm(), FakeArm()
    deployer(first).ensure([access.foundry_user(ACCOUNT_ID)], apply=True)
    deployer(second).ensure([access.foundry_user(ACCOUNT_ID)], apply=True)
    assert first.puts()[0][1] == second.puts()[0][1]


@pytest.mark.parametrize("scope,role", [
    (ACCOUNT_ID, access.FOUNDRY_USER),
    (GROUP_ID, access.FOUNDRY_USER),                                   # inherited from the resource group
    (f"/subscriptions/{SUB}", access.COGNITIVE_SERVICES_DATA_CONTRIBUTOR),  # an equivalent data role counts
    (ACCOUNT_ID, access.COGNITIVE_SERVICES_USER),
])
def test_an_existing_covering_role_is_kept_and_nothing_is_written_or_awaited(scope, role):
    arm, sleeps = FakeArm([assignment(scope, role)]), []
    rows = deployer(arm, sleeps=sleeps).ensure([access.foundry_user(ACCOUNT_ID)], apply=True)
    assert rows[0]["status"] == "unchanged" and not arm.puts() and sleeps == []


def test_a_role_on_a_child_scope_does_not_cover_the_parent():
    child = f"{STORAGE_ID}/blobServices/default/containers/other"
    arm = FakeArm([assignment(child, access.STORAGE_BLOB_DATA_CONTRIBUTOR)])
    rows = deployer(arm).ensure([access.blob_container_contributor(STORAGE_ID, "aifactory-agent")], apply=True)
    assert rows[0]["status"] == "created" and len(arm.puts()) == 1


def test_plan_reports_what_it_would_grant_and_writes_nothing():
    arm, sleeps = FakeArm(), []
    rows = deployer(arm, sleeps=sleeps).ensure([access.search_index_contributor(SEARCH_ID)], apply=False)
    assert rows[0]["status"] == "would_create" and not arm.puts() and sleeps == []


def test_a_signed_in_user_is_never_granted_roles_and_is_told_what_to_ask_for():
    arm, sleeps = FakeArm(), []
    rows = deployer(arm, service_principal=False, sleeps=sleeps).ensure([access.foundry_user(ACCOUNT_ID)], apply=True)
    assert rows[0]["status"] == "missing" and "Foundry User" in rows[0]["detail"]
    assert not arm.puts() and sleeps == []


def _token(claims):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'RS256'})}.{encode(claims)}.signature"


def test_the_caller_is_read_from_the_arm_token_without_microsoft_graph():
    assert access.caller_principal(_token({"oid": PRINCIPAL, "idtyp": "app", "appid": "x"})) == (PRINCIPAL, True)
    assert access.caller_principal(_token({"oid": PRINCIPAL, "idtyp": "user", "upn": "a@b.c"})) == (PRINCIPAL, False)
    assert access.caller_principal(_token({"oid": PRINCIPAL, "upn": "a@b.c", "scp": "user_impersonation"})) == (
        PRINCIPAL, False)
    with pytest.raises(ValueError):
        access.caller_principal("not-a-token")
