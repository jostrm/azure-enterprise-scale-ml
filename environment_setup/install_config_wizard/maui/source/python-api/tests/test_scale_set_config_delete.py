import copy
import json
import os
import socket
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import api, wizard


ENDPOINT = "/api/v1/scale-sets/delete"
LIST_ENDPOINT = "/api/v1/scale-sets"
HEADERS = {"X-API-Key": "scale-set-delete-tests"}


def forbidden(*args, **kwargs):
    pytest.fail("Snapshot listing/deletion must not access Azure, settings, defaults, or import/export state")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(legacy))
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("AIFACTORY_OPERATIONS_DB", str(tmp_path / "operations.db"))
    monkeypatch.setenv(api.API_KEY_ENV, HEADERS["X-API-Key"])
    for name in ("_save_app_settings", "_record_recent_project", "_load_project_state",
                 "_load_template_defaults", "_import_yaml_to_state", "_import_json_to_state",
                 "_import_env_to_state", "save_azure_devops", "save_github_actions"):
        monkeypatch.setattr(wizard, name, forbidden)
    monkeypatch.setattr(api, "_state", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    connect = socket.socket.connect

    def local_connect(sock, address):
        # Windows asyncio implements its internal socketpair over loopback.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        forbidden()

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    return legacy


@pytest.fixture
def client():
    with TestClient(api.app) as result:
        yield result


@pytest.fixture
def scale_set(tmp_path):
    root = tmp_path / "factory"
    root.mkdir()
    snapshot = Path(wizard._save_scaleset_snapshot({
        "_save_folder": str(root), "admin_aifactorySuffixRG": "-007",
        "admin_aifactoryPrefixRG": "saved-", "admin_location": "swedencentral",
        "dev_sub_id": "sub-dev", "test_sub_id": "sub-stage", "prod_sub_id": "sub-dev",
    }))
    return root, snapshot


def body(scale_set, **changes):
    root, snapshot = scale_set
    return {"aifactory_folder": str(root), "scale_set_id": "007", "path": str(snapshot), **changes}


def write_json(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def fallback(legacy, folder=""):
    return write_json(legacy / "scaleset_007.json", {
        "admin_aifactorySuffixRG": "-007", "_save_folder": folder,
    })


def files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_authentication_required(client, scale_set, headers):
    assert client.post(ENDPOINT, json=body(scale_set), headers=headers).status_code == 401
    assert scale_set[1].is_file()


def test_api_key_must_be_configured(client, scale_set, monkeypatch):
    monkeypatch.delenv(api.API_KEY_ENV)
    assert client.post(ENDPOINT, json=body(scale_set), headers=HEADERS).status_code == 503
    assert scale_set[1].is_file()


@pytest.mark.parametrize("orchestrator", ["ado", "gha"])
def test_only_exact_listed_snapshot_is_deleted(client, scale_set, tmp_path, orchestrator):
    root, snapshot = scale_set
    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    saved["orchestrator"] = orchestrator
    write_json(snapshot, saved)
    protected = [
        root / "variables.json", root / "variables.yaml", root / ".env",
        root / "config-wizard" / "factory_state.json",
        root / "config-wizard" / "project-007" / "project_state.json",
        snapshot.parent / "variables.json", snapshot.parent / "variables.yaml",
        snapshot.parent / ".env", root / ".github" / "workflows" / "deploy.yaml",
        root / "pipelines" / "deploy.yaml", tmp_path / "settings.json",
    ]
    for path in protected:
        write_json(path, {})
    other = write_json(snapshot.parent / "scaleset_008.json", {"admin_aifactorySuffixRG": "-008"})
    before = files(tmp_path)
    directories = {p for p in tmp_path.rglob("*") if p.is_dir()}
    listed = client.post(LIST_ENDPOINT, headers=HEADERS, json={"aifactory_folder": str(root)})
    assert listed.status_code == 200
    selected = next(item for item in listed.json()["scale_sets"] if item["scale_set_id"] == "007")
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=selected["path"]))

    assert response.status_code == 200, response.text
    assert response.json()["deleted_path"] == str(snapshot)
    assert "Azure resources were not changed" in response.json()["message"]
    assert other.is_file()
    assert files(tmp_path) == {key: value for key, value in before.items()
                               if key != str(snapshot.relative_to(tmp_path))}
    assert {p for p in tmp_path.rglob("*") if p.is_dir()} == directories
    remaining = client.post(LIST_ENDPOINT, headers=HEADERS, json={"aifactory_folder": str(root)})
    assert [item["scale_set_id"] for item in remaining.json()["scale_sets"]] == ["008"]


def test_shared_helper_does_not_mutate_or_save_state(scale_set, monkeypatch):
    original = copy.deepcopy(wizard.DEFAULT_STATE)
    monkeypatch.setattr(wizard, "_save_scaleset_snapshot", forbidden)
    assert wizard._delete_scaleset_snapshot(str(scale_set[0]), "007", str(scale_set[1])) == str(scale_set[1])
    assert wizard.DEFAULT_STATE == original
    assert wizard.ProjectConfigDeleteError is wizard.ConfigDeleteError


def test_repeated_delete_cannot_switch_to_legacy_fallback(client, scale_set, isolated, monkeypatch):
    legacy = fallback(isolated, str(scale_set[0]))
    assert client.post(ENDPOINT, headers=HEADERS, json=body(scale_set)).status_code == 200
    monkeypatch.setattr(wizard, "_list_scalesets", forbidden)
    assert client.post(ENDPOINT, headers=HEADERS, json=body(scale_set)).status_code == 404
    assert legacy.is_file()


def test_legacy_selection_cannot_delete_current_local_snapshot(client, scale_set, isolated):
    legacy = fallback(isolated, str(scale_set[0]))
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=str(legacy)))
    assert response.status_code == 409
    assert legacy.is_file() and scale_set[1].is_file()


@pytest.mark.parametrize("ownership", ["same", "empty", "absent"])
def test_current_legacy_selection_can_be_deleted(client, scale_set, isolated, ownership):
    root, snapshot = scale_set
    snapshot.unlink()
    legacy = fallback(isolated, str(root) if ownership == "same" else "")
    if ownership == "absent":
        write_json(legacy, {"admin_aifactorySuffixRG": "-007"})
    listed = client.post(LIST_ENDPOINT, headers=HEADERS, json={"aifactory_folder": str(root)})
    assert listed.status_code == 200
    selected = listed.json()["scale_sets"][0]
    assert selected["path"] == str(legacy)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=selected["path"]))
    assert response.status_code == 200
    assert response.json()["deleted_path"] == str(legacy)
    assert not legacy.exists() and snapshot.parent.is_dir()


@pytest.mark.parametrize("owner", ["other", "relative", {"invalid": True}])
def test_nonempty_legacy_ownership_must_match_factory(client, scale_set, isolated, owner):
    root, snapshot = scale_set
    snapshot.unlink()
    legacy = fallback(isolated, str(root.parent / "other") if owner == "other" else owner)
    before = legacy.read_bytes()
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=str(legacy)))
    assert response.status_code == 409
    assert legacy.read_bytes() == before


def test_current_local_snapshot_uses_selected_folder_not_obsolete_metadata(client, scale_set):
    root, snapshot = scale_set
    write_json(snapshot, {"admin_aifactorySuffixRG": "-007", "_save_folder": str(root.parent / "previous")})
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 200


def test_factory_manifest_disables_legacy_fallback(client, scale_set, isolated):
    root, snapshot = scale_set
    snapshot.unlink()
    write_json(root / "config-wizard" / "factory_state.json", {})
    legacy = fallback(isolated, str(root))
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=str(legacy)))
    assert response.status_code == 404
    assert legacy.is_file()


@pytest.mark.parametrize("identity", [
    "", "../007", "..\\007", "007/../008", "007\\008", "007..008", ".", "..",
    "007.", "007 ", " 007", "-007", "007:stream", "007\0", "007\n", 7, True, None, {}, [],
])
def test_invalid_identity_is_rejected_before_lookup(client, scale_set, monkeypatch, identity):
    monkeypatch.setattr(wizard, "_list_scalesets", forbidden)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, scale_set_id=identity))
    assert response.status_code == 422
    assert scale_set[1].is_file()


@pytest.mark.parametrize("identity", ["7", "008", "scaleset_007"])
def test_identity_is_exact_listing_key_not_zero_padded_or_slugged(client, scale_set, identity):
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, scale_set_id=identity))
    assert response.status_code == 404
    assert scale_set[1].is_file()


@pytest.mark.parametrize("suffix", ["007", "-007", " --007 "])
def test_saved_suffix_normalization_matches_wizard(client, scale_set, suffix):
    write_json(scale_set[1], {"admin_aifactorySuffixRG": suffix})
    assert client.post(ENDPOINT, headers=HEADERS, json=body(scale_set)).status_code == 200


def test_named_scale_set_uses_exact_filename_and_identity(client, scale_set):
    root, snapshot = scale_set
    named = snapshot.with_name("scaleset_Region-A_002.json")
    snapshot.rename(named)
    write_json(named, {"admin_aifactorySuffixRG": "-Region-A_002"})
    response = client.post(ENDPOINT, headers=HEADERS, json=body(
        scale_set, path=str(named), scale_set_id="Region-A_002",
    ))
    assert response.status_code == 200


@pytest.mark.parametrize("suffix", ["-008", "-7", "", " ", None, 7, {}, "-007/../008"])
def test_saved_identity_must_match(client, scale_set, suffix):
    write_json(scale_set[1], {"admin_aifactorySuffixRG": suffix})
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 409
    assert scale_set[1].is_file()


def test_missing_identity_does_not_inherit_default_000(client, scale_set):
    root, snapshot = scale_set
    default = snapshot.with_name("scaleset_000.json")
    snapshot.rename(default)
    write_json(default, {})
    response = client.post(ENDPOINT, headers=HEADERS, json=body(
        scale_set, path=str(default), scale_set_id="000",
    ))
    assert response.status_code == 409
    assert default.is_file()


@pytest.mark.parametrize("content", [b"not-json", b"[]", b"null", b'"config"', b'{"broken":', b"\xff"])
@pytest.mark.parametrize("endpoint", [ENDPOINT, LIST_ENDPOINT])
def test_malformed_snapshot_returns_clear_sanitized_error(client, scale_set, content, endpoint):
    scale_set[1].write_bytes(content)
    response = client.post(endpoint, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Scale set snapshot must contain")
    assert scale_set[1].read_bytes() == content


@pytest.mark.parametrize("field", ["aifactory_folder", "path"])
@pytest.mark.parametrize("invalid", [
    "", "relative", "traversal", "null-byte", "trailing-dot", "stream", None, 7, True, {}, [],
])
def test_invalid_paths_are_rejected_before_lookup(client, scale_set, monkeypatch, field, invalid):
    payload = body(scale_set)
    value = payload[field]
    if isinstance(invalid, str):
        invalid = {
            "": "", "relative": "relative", "traversal": str(Path(value).parent / ".." / Path(value).name),
            "null-byte": value + "\0", "trailing-dot": value + ".", "stream": value + ":alternate",
        }[invalid]
    payload[field] = invalid
    monkeypatch.setattr(wizard, "_list_scalesets", forbidden)
    assert client.post(ENDPOINT, headers=HEADERS, json=payload).status_code == 422
    assert scale_set[1].is_file()


@pytest.mark.parametrize("field", ["aifactory_folder", "path"])
def test_missing_path_returns_not_found(client, scale_set, field):
    response = client.post(ENDPOINT, headers=HEADERS, json=body(
        scale_set, **{field: str(scale_set[0] / "missing")},
    ))
    assert response.status_code == 404
    assert scale_set[1].is_file()


def test_directory_cannot_be_deleted_even_if_listed(client, scale_set):
    scale_set[1].unlink()
    scale_set[1].mkdir()
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 422
    assert scale_set[1].is_dir()


@pytest.mark.parametrize("target", ["variables", "factory-state", "project", "other-scale-set", "outside-folder"])
def test_arbitrary_existing_file_cannot_be_deleted(client, scale_set, tmp_path, target):
    root, snapshot = scale_set
    wrong = {
        "variables": root / "variables.json",
        "factory-state": root / "config-wizard" / "factory_state.json",
        "project": root / "config-wizard" / "project-007" / "project_state.json",
        "other-scale-set": snapshot.parent / "scaleset_008.json",
        "outside-folder": tmp_path / "unrelated" / "scaleset_007.json",
    }[target]
    write_json(wrong, {"admin_aifactorySuffixRG": "-007"})
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=str(wrong)))
    assert response.status_code == 409
    assert wrong.is_file() and snapshot.is_file()


def test_normalized_absolute_path_is_accepted(client, scale_set):
    payload = body(scale_set)
    payload["aifactory_folder"] += os.sep
    if os.name == "nt":
        payload["path"] = payload["path"].upper()
    response = client.post(ENDPOINT, headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert os.path.normcase(response.json()["deleted_path"]) == os.path.normcase(str(scale_set[1]))


@pytest.mark.parametrize("location", ["file", "scale-set-directory", "factory-directory"])
@pytest.mark.parametrize("link_kind", ["symlink", "reparse"])
def test_linked_path_components_are_rejected(client, scale_set, monkeypatch, location, link_kind):
    original = os.lstat
    link = {"file": scale_set[1], "scale-set-directory": scale_set[1].parent,
            "factory-directory": scale_set[0]}[location]

    def linked(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if Path(path) == link:
            return SimpleNamespace(
                st_mode=stat.S_IFLNK | 0o777 if link_kind == "symlink" else info.st_mode,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT if link_kind == "reparse" else 0,
            )
        return info

    monkeypatch.setattr(os, "lstat", linked)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 422
    assert scale_set[1].is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
@pytest.mark.parametrize("location", ["scale-set-directory", "factory-directory"])
def test_real_windows_junctions_are_rejected(client, scale_set, tmp_path, location):
    import _winapi

    link = scale_set[1].parent if location == "scale-set-directory" else scale_set[0]
    outside = tmp_path / "junction-target"
    link.rename(outside)
    _winapi.CreateJunction(str(outside), str(link))
    try:
        response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set))
        assert response.status_code == 422
        assert list(outside.rglob("scaleset_007.json"))
    finally:
        os.rmdir(link)


@pytest.mark.parametrize(("error", "status"), [(PermissionError, 422), (OSError, 500), (FileNotFoundError, 404)])
def test_unlink_errors_are_sanitized_without_fallback(client, scale_set, isolated, monkeypatch, error, status):
    legacy = fallback(isolated, str(scale_set[0]))
    original = os.unlink

    def failed(path, *args, **kwargs):
        if Path(path) == scale_set[1]:
            raise error("private OS path and secret detail")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", failed)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == status
    assert "private OS path" not in response.text
    assert legacy.is_file() and scale_set[1].is_file()


@pytest.mark.parametrize("change", ["removed", "replaced", "listing", "factory"])
def test_changed_snapshot_or_listing_is_not_deleted(client, scale_set, isolated, monkeypatch, change):
    root, snapshot = scale_set
    if change in ("listing", "factory"):
        snapshot.unlink()
        target = fallback(isolated, str(root))
    else:
        target = snapshot
    original = wizard._list_scalesets
    calls = 0

    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if change == "removed":
                target.unlink()
            elif change == "replaced":
                write_json(target, {"admin_aifactorySuffixRG": "-008", "new": True})
            elif change == "listing":
                write_json(snapshot, {"admin_aifactorySuffixRG": "-007"})
            else:
                root.rename(root.parent / "original-factory")
                root.mkdir()
        return original(*args, **kwargs)

    monkeypatch.setattr(wizard, "_list_scalesets", changing)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(scale_set, path=str(target)))
    assert response.status_code == (404 if change == "removed" else 409)
    if change != "removed":
        assert target.is_file()


def test_list_and_delete_never_create_legacy_directory(client, scale_set, tmp_path, monkeypatch):
    missing = tmp_path / "missing-legacy"
    calls = []

    def snapshot_dir(*, create=True):
        calls.append(create)
        if create:
            forbidden()
        return str(missing)

    monkeypatch.setattr(wizard, "_snapshot_dir", snapshot_dir)
    assert client.post(LIST_ENDPOINT, headers=HEADERS, json=body(scale_set)).status_code == 200
    assert client.post(ENDPOINT, headers=HEADERS, json=body(scale_set)).status_code == 200
    assert client.post(LIST_ENDPOINT, headers=HEADERS, json=body(scale_set)).json() == {"scale_sets": []}
    assert calls == [False, False, False, False]
    assert not missing.exists()


@pytest.mark.parametrize(("subscriptions", "expected"), [
    (("sub-z", "sub-a", "sub-z"), ["sub-a", "sub-z"]),
    (("", None, " "), []),
    ((" sub-a ", "", "sub-a"), ["sub-a"]),
    ((None, 123, {}), []),
])
@pytest.mark.parametrize("legacy", [False, True])
def test_listing_exposes_only_raw_saved_deployment_scope(
    client, scale_set, isolated, subscriptions, expected, legacy,
):
    root, snapshot = scale_set
    saved = {
        "admin_aifactoryPrefixRG": "saved-", "admin_aifactorySuffixRG": "-007",
        "admin_location": "swedencentral",
        **dict(zip(("dev_sub_id", "test_sub_id", "prod_sub_id"), subscriptions)),
        "private_credential": "never-disclose", "tenantId": "private-tenant",
        "_save_folder": str(root.parent / "obsolete-owner"),
    }
    if legacy:
        snapshot.unlink()
        snapshot = isolated / snapshot.name
    write_json(snapshot, saved)
    before = snapshot.read_bytes()
    response = client.post(LIST_ENDPOINT, headers=HEADERS, json={"aifactory_folder": str(root)})
    assert response.status_code == 200
    assert response.json() == {"scale_sets": [{
        "scale_set_id": "007", "path": str(snapshot),
        "deployment_scope": {
            "prefix_rg": "saved-", "suffix_rg": "-007", "region": "swedencentral",
            "subscription_ids": expected,
        },
    }]}
    assert snapshot.read_bytes() == before


def test_missing_scope_is_unknown_not_hydrated_from_active_factory(client, scale_set):
    root, snapshot = scale_set
    write_json(snapshot, {})
    write_json(root / "config-wizard" / "factory_state.json", {
        "admin_aifactoryPrefixRG": "active-", "admin_aifactorySuffixRG": "-001",
        "admin_location": "westeurope", "dev_sub_id": "active-sub",
    })
    response = client.post(LIST_ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 200
    assert response.json()["scale_sets"][0]["deployment_scope"] == {
        "prefix_rg": "", "suffix_rg": "", "region": "", "subscription_ids": [],
    }


@pytest.mark.parametrize("field", ["admin_aifactoryPrefixRG", "admin_aifactorySuffixRG", "admin_location"])
def test_malformed_scope_is_not_silently_replaced_with_defaults(client, scale_set, field):
    write_json(scale_set[1], {field: {"credential": "never-disclose"}})
    response = client.post(LIST_ENDPOINT, headers=HEADERS, json=body(scale_set))
    assert response.status_code == 422
    assert "never-disclose" not in response.text
    assert "text values" in response.json()["detail"]


def test_openapi_documents_secured_delete_and_metadata(client):
    contract = client.get("/openapi.json").json()
    operation = contract["paths"][ENDPOINT]["post"]
    assert operation["security"] == [{"APIKeyHeader": []}]
    assert {"200", "404", "409", "422", "500"} <= operation["responses"].keys()
    schemas = contract["components"]["schemas"]
    assert set(schemas["ScaleSetDeleteBody"]["required"]) == {"aifactory_folder", "scale_set_id", "path"}
    assert set(schemas["ScaleSetDeleted"]["required"]) == {"deleted_path", "message"}
    assert set(schemas["ScaleSetSummary"]["required"]) == {"scale_set_id", "path", "deployment_scope"}
    assert set(schemas["ScaleSetDeploymentScope"]["required"]) == {
        "prefix_rg", "suffix_rg", "region", "subscription_ids",
    }
