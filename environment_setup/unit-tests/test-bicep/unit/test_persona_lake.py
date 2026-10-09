"""Credential-free ADLS authorization contracts and executor behavior."""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "environment_setup/aifactory/bicep"))
from personas import lake as MODULE
TENANT = "11111111-1111-1111-1111-111111111111"
SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"
ADMIN = "33333333-3333-3333-3333-333333333333"
LEGACY = "44444444-4444-4444-4444-444444444444"
GROUPS = {f"persona{i}": f"00000000-0000-0000-0000-{i:012d}" for i in [200, 201, *range(210, 217)]}
LEAF = "mlops/v1/projects/project001/environments/dev"
BASE = "user::rwx,group::---,other::---"


def manifest():
    common = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/common"
    return {
        "tenant_id": TENANT, "environment": "dev", "project": "project001",
        "common_scope": common, "project_scope": common.replace("/common", "/project001"),
        "lake": {
            "tenant_id": TENANT, "subscription_id": SUBSCRIPTION, "resource_group": "common",
            "storage_account": "isolatedlake", "filesystem": "lake3",
            "project": "project001", "environment": "dev",
        },
        "adoption": {"trusted_lake_admin_principal_ids": [ADMIN]},
    }


class FakeLake:
    def __init__(self):
        ancestors = ["/".join(LEAF.split("/")[:i]) for i in range(1, 7)]
        self.values = {path: BASE for path in ["", *ancestors]}
        self.values[LEAF + "/data.txt"] = "user::rw-,group::---,other::---"
        self.values["mlops/v1/projects/project002"] = BASE
        self.writes = []

    def paths(self, prefix):
        assert prefix == ""
        return [(path, not path.endswith(".txt")) for path in self.values if path]

    def acl(self, path):
        return {
            "x-ms-acl": self.values[path], "x-ms-owner": ADMIN, "x-ms-group": ADMIN,
            "x-ms-resource-type": "file" if path.endswith(".txt") else "directory", "ETag": "v1",
        }

    def mkdir(self, path):
        self.writes.append(("mkdir", path))
        self.values.setdefault(path, BASE)

    def request(self, method, path="", query=None, headers=None):
        assert method == "PATCH" and headers["If-Match"] == "v1"
        self.writes.append(("acl", path))
        self.values[path] = headers["x-ms-acl"]


def harness(monkeypatch, *, assignments=None, permissions=None, storage_changes=None, workload_identity=None):
    lake, calls = FakeLake(), []
    monkeypatch.setattr(MODULE, "Lake", lambda config, cli_runner: lake)

    def cli(*args):
        calls.append(args)
        assert args[0] != "ad"
        if args[:2] == ("account", "show"):
            return {"tenantId": TENANT}
        if args[:3] == ("storage", "account", "show"):
            return {
                "id": manifest()["common_scope"] + "/providers/Microsoft.Storage/storageAccounts/isolatedlake",
                "isHnsEnabled": True, "allowSharedKeyAccess": False, "allowBlobPublicAccess": False,
                **(storage_changes or {}),
            }
        if args[:3] == ("role", "assignment", "list"):
            assert "--include-inherited" in args and "--all" not in args
            assert args[args.index("--fill-principal-name") + 1] == "false"
            return assignments or []
        if args[:3] == ("role", "definition", "list"):
            return [{"permissions": permissions}]
        if args[:2] == ("resource", "list"):
            return [{"id": manifest()["project_scope"] + "/providers/Microsoft.App/containerApps/app",
                     "type": "Microsoft.App/containerApps"}] if workload_identity else []
        if args[:2] == ("resource", "show"):
            return {"identity": workload_identity}
        if args[:2] == ("identity", "show"):
            return {"principalId": ADMIN}
        raise AssertionError(args)

    return lake, calls, cli


def test_preview_reads_actual_permissions_without_mutation(monkeypatch):
    lake, calls, cli = harness(monkeypatch)
    report = MODULE.provision_lake(manifest(), GROUPS, False, cli)
    assert report["state"] == "preview" and report["authorized_path"] == LEAF
    assert report["data_role_assignments"] == [] and not lake.writes
    assert all(call[:3] != ("role", "assignment", "create") for call in calls)


def test_ai_only_read_access_environment_boundary_idempotence(monkeypatch):
    lake, _, cli = harness(monkeypatch)
    MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert f"group:{GROUPS['persona213']}:--x" in lake.values[""]
    assert f"group:{GROUPS['persona213']}:r-x" in lake.values[LEAF]
    assert f"default:group:{GROUPS['persona213']}:r-x" in lake.values[LEAF]
    assert f"group:{GROUPS['persona213']}:r--" in lake.values[LEAF + "/data.txt"]
    assert "default:" not in lake.values["mlops/v1/projects/project001"]
    assert lake.values["mlops/v1/projects/project002"] == BASE
    for persona, group in GROUPS.items():
        if persona != "persona213":
            assert not any(group in acl for acl in lake.values.values())
    lake.writes.clear()
    MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert lake.writes == []


@pytest.mark.parametrize("changes", [
    {"isHnsEnabled": False}, {"allowSharedKeyAccess": True},
    {"allowSharedKeyAccess": None}, {"allowBlobPublicAccess": True},
])
def test_storage_bypass_prerequisites_fail_without_writes(monkeypatch, changes):
    lake, _, cli = harness(monkeypatch, storage_changes=changes)
    with pytest.raises(ValueError):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not lake.writes


@pytest.mark.parametrize("permissions", [
    [{"actions": ["*"], "notActions": ["Microsoft.Authorization/*/write"], "dataActions": []}],
    [{"actions": [], "dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"]}],
    [{"actions": ["Microsoft.Storage/storageAccounts/listKeys/action"], "dataActions": []}],
    [{"actions": ["Microsoft.Authorization/roleAssignments/write"], "dataActions": []}],
])
def test_even_ai_cannot_have_bypass_rbac_including_inherited(monkeypatch, permissions):
    lake, _, cli = harness(monkeypatch, assignments=[{
        "id": "/inherited/assignment", "roleDefinitionId": "/role/1",
        "principalId": GROUPS["persona213"], "condition": "review me",
    }], permissions=permissions)
    with pytest.raises(ValueError, match="bypass-capable"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not lake.writes


def test_privileged_administrator_exception_is_explicit(monkeypatch):
    _, _, cli = harness(monkeypatch, assignments=[{
        "id": "/privileged/assignment", "roleDefinitionId": "/role/1",
        "principalId": ADMIN,
    }], permissions=[{"actions": ["*"], "dataActions": ["*"]}])
    assert MODULE.provision_lake(manifest(), GROUPS, False, cli)["state"] == "preview"
    value = manifest()
    value["adoption"]["trusted_lake_admin_principal_ids"].append(GROUPS["persona216"])
    with pytest.raises(ValueError, match="ordinary groups"):
        MODULE.provision_lake(value, GROUPS, True, cli)


@pytest.mark.parametrize("identity", [
    {"type": "SystemAssigned", "principalId": ADMIN},
    {"type": "UserAssigned", "userAssignedIdentities": {
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/common/providers/Microsoft.ManagedIdentity/userAssignedIdentities/ingestion": {}
    }},
])
def test_ordinary_deployers_cannot_inherit_trusted_lake_identity(monkeypatch, identity):
    lake, _, cli = harness(monkeypatch, workload_identity=identity)
    with pytest.raises(ValueError, match="project-controllable"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not lake.writes


@pytest.mark.parametrize("path,acl", [
    (LEAF, BASE + f",group:{GROUPS['persona216']}:r-x"),
    (LEAF, "user::rwx,group::---,other::r-x"),
    ("mlops/v1/projects/project002", BASE + f",group:{GROUPS['persona213']}:r-x"),
    ("mlops/v1/projects/project001", BASE + f",default:group:{GROUPS['persona213']}:r-x"),
])
def test_acl_bypass_fails_before_any_write(monkeypatch, path, acl):
    lake, _, cli = harness(monkeypatch)
    lake.values[path] = acl
    with pytest.raises(ValueError, match="adoption blocked"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not lake.writes


def test_acl_migration_is_reviewed_and_only_inside_owned_leaf(monkeypatch):
    lake, _, cli = harness(monkeypatch)
    lake.values[LEAF] += f",group:{LEGACY}:rwx,default:group:{LEGACY}:rwx"
    value = manifest()
    value["adoption"]["legacy_principal_ids"] = [LEGACY]
    with pytest.raises(ValueError):
        MODULE.provision_lake(value, GROUPS, True, cli)
    assert not lake.writes
    value["adoption"]["approved_acl_principal_ids"] = [LEGACY]
    preview = MODULE.provision_lake(value, GROUPS, False, cli)
    assert preview["legacy_acl_removals"][0]["path"] == LEAF
    with pytest.raises(ValueError, match="execute_migration"):
        MODULE.provision_lake(value, GROUPS, True, cli)
    assert not lake.writes
    value["adoption"]["execute_migration"] = True
    MODULE.provision_lake(value, GROUPS, True, cli)
    assert LEGACY not in lake.values[LEAF]


def test_acl_owner_bypass_must_be_migrated(monkeypatch):
    lake, _, cli = harness(monkeypatch)
    read = lake.acl
    lake.acl = lambda path: {**read(path), "x-ms-owner": GROUPS["persona210"]}
    with pytest.raises(ValueError, match="owner"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not lake.writes


def test_notactions_are_subtraction_not_a_deny():
    operation = "Microsoft.Storage/storageAccounts/write"
    restrictive = {"actions": ["*"], "notActions": ["Microsoft.Storage/*"]}
    assert not MODULE.allows([restrictive], operation)
    assert MODULE.allows([restrictive, {"actions": ["Microsoft.Storage/*"]}], operation)


def test_missing_lake_wrong_environment_or_user_principals_fail(monkeypatch):
    _, _, cli = harness(monkeypatch)
    for changes in ({"lake": None}, {"environment": "prod"},
                    {"lake": {**manifest()["lake"], "users": [ADMIN]}}):
        with pytest.raises(ValueError):
            MODULE.provision_lake({**manifest(), **changes}, GROUPS, False, cli)


def test_insufficient_access_propagates(monkeypatch):
    lake, _, _ = harness(monkeypatch)
    def denied(*args):
        raise PermissionError("AuthorizationPermissionMismatch")
    with pytest.raises(PermissionError):
        MODULE.provision_lake(manifest(), GROUPS, True, denied)
    assert not lake.writes


def test_bounded_audit_fails_before_writes(monkeypatch):
    lake, _, cli = harness(monkeypatch)
    value = manifest()
    value["lake"]["max_audit_paths"] = 2
    with pytest.raises(ValueError, match="path limit"):
        MODULE.provision_lake(value, GROUPS, True, cli)
    assert not lake.writes


def test_approved_role_cleanup_is_previewed_but_cannot_be_skipped_on_execute(monkeypatch):
    assignment = {
        "id": manifest()["common_scope"] + "/providers/Microsoft.Authorization/roleAssignments/legacy",
        "roleDefinitionId": "/role/1", "principalId": LEGACY, "scope": manifest()["common_scope"],
    }
    lake, _, cli = harness(monkeypatch, assignments=[assignment],
                           permissions=[{"actions": ["*"], "dataActions": []}])
    value = manifest()
    value["adoption"].update(legacy_principal_ids=[LEGACY], approved_role_assignment_ids=[assignment["id"]])
    report = MODULE.provision_lake(value, GROUPS, False, cli)
    assert report["requires_prior_role_removal"] == [assignment["id"]]
    with pytest.raises(ValueError, match="bypass-capable"):
        MODULE.provision_lake(value, GROUPS, True, cli)
    assert not lake.writes


@pytest.mark.parametrize("path,directory", [
    ("../project002/data", False), ("/absolute", True), ("project//data", True),
    ("project\\data", True), ("data\nname", True), ("valid", "true"), ("", True),
    (LEAF, False), ("mlops", False),
])
def test_invalid_inventory_fails_before_acl_writes(monkeypatch, path, directory):
    filesystem, _, cli = harness(monkeypatch)
    filesystem.paths = lambda prefix: [(path, directory)]
    with pytest.raises(ValueError, match="inventory|not a directory"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not filesystem.writes


def test_duplicate_inventory_fails_before_acl_writes(monkeypatch):
    filesystem, _, cli = harness(monkeypatch)
    filesystem.paths = lambda prefix: [("mlops", True), ("mlops", True)]
    with pytest.raises(ValueError, match="duplicate paths"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not filesystem.writes


def test_path_type_changed_since_inventory_fails_before_writes(monkeypatch):
    filesystem, _, cli = harness(monkeypatch)
    read = filesystem.acl
    filesystem.acl = lambda path: {**read(path), "x-ms-resource-type": "file"}
    with pytest.raises(ValueError, match="type changed"):
        MODULE.provision_lake(manifest(), GROUPS, True, cli)
    assert not filesystem.writes
