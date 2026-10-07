"""Credential-free project ACL contracts; never grant data roles to test identities."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
PATH = ROOT / "environment_setup" / "aifactory" / "bicep" / "esml-util" / "project_lake_access.py"
SPEC = importlib.util.spec_from_file_location("project_lake_access", PATH)
ACCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCESS)


USER = "11111111-1111-1111-1111-111111111111"
GROUP = "22222222-2222-2222-2222-222222222222"
MI = "33333333-3333-3333-3333-333333333333"


@pytest.mark.parametrize("acl", [None, "user::rwx,group::---,other::---"])
def test_directory_creation_acl_is_explicit_and_does_not_replace_existing_paths(acl):
    lake = ACCESS.Lake({})
    calls = []
    lake.request = lambda *args: calls.append(args)
    if acl is None:
        lake.mkdir("mlops")
    else:
        lake.mkdir("mlops", acl=acl)
    headers = {"If-None-Match": "*", "Content-Length": "0"}
    if acl is not None:
        headers["x-ms-acl"] = acl
    assert calls == [("PUT", "mlops", {"resource": "directory"}, headers)]


def test_ancestor_acl_is_traversal_only_and_preserves_unrelated_entries():
    source = "user::rwx,group::r-x,other::---"
    result = ACCESS.merge_acl(source, [("user", USER, "--x"), ("group", GROUP, "--x")],
                              directory=True, defaults=False)
    assert "user::rwx" in result and "group::r-x" in result and "other::---" in result
    assert f"user:{USER}:--x" in result and f"group:{GROUP}:--x" in result
    assert "default:" not in result
    assert ACCESS.merge_acl(result, [("user", USER, "--x"), ("group", GROUP, "--x")],
                            directory=True, defaults=False) == result


def test_project_access_and_inheritance_use_correct_principal_types():
    result = ACCESS.merge_acl("user::rwx,group::r-x,other::---",
                              [("user", USER, "rwx"), ("group", GROUP, "rwx"), ("user", MI, "rwx")],
                              directory=True, defaults=True)
    for kind, identity in (("user", USER), ("group", GROUP), ("user", MI)):
        assert f"{kind}:{identity}:rwx" in result.split(",")
        assert f"default:{kind}:{identity}:rwx" in result.split(",")
    assert "mask::rwx" in result and "default:mask::rwx" in result
    assert "default:other::---" in result


def test_files_get_readwrite_not_execute_and_no_default_acls():
    result = ACCESS.merge_acl("user::rw-,group::r--,other::---",
                              [("user", MI, "rw-")], directory=False, defaults=True)
    assert f"user:{MI}:rw-" in result and "default:" not in result


def test_mask_changes_must_not_expand_other_principals():
    with pytest.raises(ValueError, match="unrelated"):
        ACCESS.merge_acl(f"user::rwx,group::rwx,mask::r-x,other::---",
                          [("user", MI, "rwx")], directory=True, defaults=True)


def test_validation_rejects_ambiguous_scope_or_duplicates():
    config = {"tenant_id": USER, "subscription_id": MI, "storage_account": "examplelake",
              "resource_group": "common-rg", "filesystem": "lake3", "project": "project001",
              "environment": "dev", "users": [USER], "groups": [GROUP], "managed_identities": [MI]}
    validated, principals = ACCESS.validate(config)
    assert principals == {USER: "User", GROUP: "Group", MI: "ServicePrincipal"}
    for changed in ({"project": "../project002"}, {"execute": "true"}, {"managed_identities": [USER]}):
        with pytest.raises(ValueError):
            ACCESS.validate({**config, **changed})


def test_preview_does_not_create_roles_or_contact_storage(monkeypatch):
    calls = []
    def cli(*args):
        calls.append(args)
        if args[:2] == ("account", "show"):
            return {"tenantId": USER}
        if args[:3] == ("storage", "account", "show"):
            return {"isHnsEnabled": True, "id": "/subscriptions/sub/resourceGroups/common/providers/Microsoft.Storage/storageAccounts/examplelake"}
        raise AssertionError("Unexpected mutation")
    monkeypatch.setattr(ACCESS, "cli", cli)
    result = ACCESS.apply({"tenant_id": USER, "subscription_id": MI, "storage_account": "examplelake",
                           "resource_group": "common-rg", "filesystem": "lake3", "project": "project001",
                           "environment": "dev", "users": [USER], "execute": False})
    assert result["state"] == "preview"
    assert result["project_root"] == "mlops/v1/projects/project001"
    assert "not Storage Blob Data Reader" in result["reader_role"]
    assert len(calls) == 2


def test_cli_json_transport_forces_utf8_for_non_ascii_display_names(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(ACCESS.shutil, "which", lambda _: "az")
    def run(command, **kwargs):
        assert kwargs["encoding"] == kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        return SimpleNamespace(returncode=0, stdout='{"displayName":"\\u00c5"}', stderr="")
    monkeypatch.setattr(ACCESS.subprocess, "run", run)
    assert ACCESS.cli("ad", "signed-in-user", "show")["displayName"] == "\u00c5"


@pytest.mark.parametrize("name", ["machineLearning.bicep", "machineLearningv2.bicep"])
def test_image_build_compute_uses_cluster_name_not_workspace_qualified_name(name):
    template = (ROOT / "environment_setup" / "aifactory" / "bicep" / "modules" / name).read_text()
    assert "imageBuildCompute: '${name}/" not in template
    assert template.count("imageBuildCompute: 'p${projectNumber}-m01${locationSuffix}-${env}'") == 2


def test_temporary_executor_role_is_removed_and_other_projects_are_not_touched(monkeypatch, tmp_path):
    calls, acls, folders = [], {"": "user::rwx,group::r-x,other::---"}, []
    role_id = "/scoped/role/created-by-this-run"
    def cli(*args):
        calls.append(args)
        if args[:2] == ("account", "show"):
            return {"tenantId": USER, "user": {"name": "owner@example.com"}}
        if args[:3] == ("storage", "account", "show"):
            return {"isHnsEnabled": True, "id": "/storage"}
        if args[:3] == ("ad", "signed-in-user", "show"):
            return {"id": USER, "userPrincipalName": "owner@example.com"}
        if args[:3] == ("role", "assignment", "list"):
            return []
        if args[:3] == ("role", "assignment", "create"):
            return {"id": role_id}
        if args[:3] == ("role", "assignment", "delete"):
            assert args[args.index("--ids") + 1] == role_id
            return None
        raise AssertionError(args)
    class Lake:
        def __init__(self, config):
            pass
        def acl(self, path):
            return {"x-ms-acl": acls.setdefault(path, "user::rwx,group::r-x,other::---"), "ETag": "v1"}
        def request(self, method, path="", query=None, headers=None):
            assert method == "PATCH"
            acls[path] = headers["x-ms-acl"]
            return {}, None
        def mkdir(self, path):
            folders.append(path)
        def paths(self, prefix):
            assert prefix == "mlops/v1/projects/project001"
            return [(prefix + "/data.csv", False)]
    monkeypatch.setattr(ACCESS, "cli", cli)
    monkeypatch.setattr(ACCESS, "Lake", Lake)
    result = ACCESS.apply({"tenant_id": USER, "subscription_id": MI, "storage_account": "examplelake",
                           "resource_group": "common-rg", "filesystem": "lake3", "project": "project001",
                           "environment": "dev", "users": [USER], "groups": [GROUP],
                           "managed_identities": [MI], "execute": True, "temporary_data_owner": True,
                           "receipt_path": str(tmp_path / "receipt.json")})
    assert result["state"] == "complete" and result["temporary_role_removed"] is True
    assert f"group:{GROUP}:rwx" in acls["mlops/v1/projects/project001"]
    assert f"user:{MI}:rw-" in acls["mlops/v1/projects/project001/data.csv"]
    assert f"user:{MI}:--x" in acls[""]
    assert not any("project002" in value or "/master" in value for value in acls)
    created_roles = [args[args.index("--role") + 1] for args in calls if args[:3] == ("role", "assignment", "create")]
    assert created_roles.count(ACCESS.DATA_OWNER) == 1
    assert all(role in (ACCESS.DATA_OWNER, ACCESS.READER) for role in created_roles)
