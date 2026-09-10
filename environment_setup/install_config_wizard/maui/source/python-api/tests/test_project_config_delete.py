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


ENDPOINT = "/api/v1/projects/delete"
HEADERS = {"X-API-Key": "snapshot-delete-tests"}


def forbidden(*args, **kwargs):
    pytest.fail("Local snapshot deletion must not call Azure, write settings, or export/import configuration")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(legacy))
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("AIFACTORY_OPERATIONS_DB", str(tmp_path / "operations.db"))
    monkeypatch.setenv(api.API_KEY_ENV, HEADERS["X-API-Key"])
    for name in ("_save_app_settings", "_record_recent_project", "save_azure_devops", "save_github_actions"):
        monkeypatch.setattr(wizard, name, forbidden)
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
def project(tmp_path):
    root = tmp_path / "factory"
    root.mkdir()
    state = {"_save_folder": str(root), "project_number_000": "015", "orchestrator": "ado"}
    snapshot = Path(wizard._save_project_snapshot(state))
    return root, snapshot


def body(project, **changes):
    root, snapshot = project
    return {"aifactory_folder": str(root), "project_number": "015", "path": str(snapshot), **changes}


def files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def legacy_snapshot(legacy, folder="", number="015"):
    path = legacy / f"project_{number}.json"
    path.write_text(json.dumps({"project_number_000": number, "_save_folder": folder}), encoding="utf-8")
    return path


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_authentication_required(client, project, headers):
    response = client.post(ENDPOINT, json=body(project), headers=headers)
    assert response.status_code == 401
    assert project[1].is_file()


def test_api_key_must_be_configured(client, project, monkeypatch):
    monkeypatch.delenv(api.API_KEY_ENV)
    assert client.post(ENDPOINT, json=body(project), headers=HEADERS).status_code == 503
    assert project[1].is_file()


@pytest.mark.parametrize("orchestrator", ["ado", "gha"])
def test_only_listed_snapshot_is_deleted(client, project, tmp_path, orchestrator):
    root, snapshot = project
    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    saved["orchestrator"] = orchestrator
    snapshot.write_text(json.dumps(saved), encoding="utf-8")
    protected = [
        root / "variables.json", root / "variables.yaml", root / ".env",
        root / "config-wizard" / "factory_state.json",
        root / "config-wizard" / "scalesets" / "scaleset_001.json",
        snapshot.parent / "variables.yaml", snapshot.parent / "variables.json", snapshot.parent / ".env",
        root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml",
        root / "pipelines" / "deploy.yaml", root / ".github" / "workflows" / "deploy.yaml",
        tmp_path / "settings.json",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    other = Path(wizard._save_project_snapshot({**saved, "project_number_000": "016"}))
    before = files(tmp_path)
    directories = {p for p in tmp_path.rglob("*") if p.is_dir()}
    listed = client.post("/api/v1/projects", headers=HEADERS, json={"aifactory_folder": str(root)})
    assert listed.status_code == 200
    selected = next(item for item in listed.json()["projects"] if item["project_number"] == "015")

    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=selected["path"]))

    assert response.status_code == 200, response.text
    assert response.json()["deleted_path"] == str(snapshot)
    assert "Azure resources were not changed" in response.json()["message"]
    assert not snapshot.exists()
    assert other.is_file()
    assert files(tmp_path) == {key: value for key, value in before.items()
                               if key != str(snapshot.relative_to(tmp_path))}
    assert {p for p in tmp_path.rglob("*") if p.is_dir()} == directories
    remaining = client.post("/api/v1/projects", headers=HEADERS, json={"aifactory_folder": str(root)})
    assert [item["project_number"] for item in remaining.json()["projects"]] == ["016"]


def test_shared_helper_does_not_load_mutate_or_export_state(project, monkeypatch):
    original = copy.deepcopy(wizard.DEFAULT_STATE)
    for name in ("_load_project_state", "_load_template_defaults", "_import_yaml_to_state",
                 "_import_json_to_state", "_import_env_to_state", "_save_project_snapshot"):
        monkeypatch.setattr(wizard, name, forbidden)
    assert wizard._delete_project_snapshot(str(project[0]), "015", str(project[1])) == str(project[1])
    assert wizard.DEFAULT_STATE == original


def test_repeated_deletion_cannot_switch_to_legacy_fallback(client, project, isolated):
    fallback = legacy_snapshot(isolated, str(project[0]))
    payload = body(project)
    assert client.post(ENDPOINT, headers=HEADERS, json=payload).status_code == 200
    assert client.post(ENDPOINT, headers=HEADERS, json=payload).status_code == 404
    assert fallback.is_file()
    assert wizard._list_project_snapshots(str(project[0]))["015"] == str(fallback)


def test_legacy_selection_cannot_delete_new_local_snapshot(client, project, isolated):
    fallback = legacy_snapshot(isolated, str(project[0]))
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(fallback)))
    assert response.status_code == 409
    assert fallback.is_file() and project[1].is_file()


@pytest.mark.parametrize("ownership", ["same", "empty", "absent"])
def test_legacy_snapshot_can_be_deleted_only_when_currently_listed(client, project, isolated, ownership):
    root, local = project
    local.unlink()
    fallback = legacy_snapshot(isolated, str(root) if ownership == "same" else "")
    if ownership == "absent":
        fallback.write_text('{"project_number_000": "015"}', encoding="utf-8")
    selected = wizard._list_project_snapshots(str(root))["015"]
    assert selected == str(fallback)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=selected))
    assert response.status_code == 200
    assert response.json()["deleted_path"] == str(fallback)
    assert not fallback.exists()
    assert local.parent.is_dir()


@pytest.mark.parametrize("ownership", ["other", "relative", "invalid"])
def test_legacy_factory_ownership_is_checked_before_state_overlay(client, project, isolated, ownership):
    root, local = project
    local.unlink()
    owner = {"other": str(root.parent / "other-factory"), "relative": "factory", "invalid": {"x": 1}}[ownership]
    fallback = legacy_snapshot(isolated, owner)
    before = fallback.read_bytes()
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(fallback)))
    assert response.status_code == 409
    assert fallback.read_bytes() == before


def test_factory_manifest_disables_legacy_fallback(client, project, isolated):
    root, local = project
    local.unlink()
    (root / "config-wizard" / "factory_state.json").write_text("{}", encoding="utf-8")
    fallback = legacy_snapshot(isolated, str(root))
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(fallback)))
    assert response.status_code == 404
    assert fallback.is_file()


@pytest.mark.parametrize("number", ["", "../015", "015/../016", "-15", "15.0", "15 ", 15, None])
def test_invalid_project_numbers_are_rejected(client, project, number):
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, project_number=number))
    assert response.status_code == 422
    assert project[1].is_file()


def test_project_number_must_use_exact_listing_key(client, project):
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, project_number="15"))
    assert response.status_code == 404
    assert project[1].is_file()


@pytest.mark.parametrize("saved_number", ["016", "", None, "015/../016"])
def test_snapshot_identity_must_match(client, project, saved_number):
    project[1].write_text(json.dumps({"project_number_000": saved_number}), encoding="utf-8")
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 409
    assert project[1].is_file()


@pytest.mark.parametrize("content", ["not-json", "[]", "null", '"config"', '{"broken":'])
def test_malformed_snapshot_is_not_deleted(client, project, content):
    project[1].write_text(content, encoding="utf-8")
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 422
    assert project[1].read_text(encoding="utf-8") == content


@pytest.mark.parametrize("field", ["aifactory_folder", "path"])
@pytest.mark.parametrize("invalid", ["", "relative", "..", "null-byte", "traversal", "trailing-dot", "stream"])
def test_invalid_paths_are_rejected(client, project, field, invalid):
    payload = body(project)
    value = payload[field]
    payload[field] = {
        "": "", "relative": "relative", "..": "..",
        "null-byte": value + "\0", "traversal": str(Path(value).parent / ".." / Path(value).name),
        "trailing-dot": value + ".", "stream": value + ":alternate",
    }[invalid]
    response = client.post(ENDPOINT, headers=HEADERS, json=payload)
    assert response.status_code == 422
    assert project[1].is_file()


@pytest.mark.parametrize("field", ["aifactory_folder", "path"])
def test_nonexistent_paths_return_not_found(client, project, field):
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, **{field: str(project[0] / "missing")}))
    assert response.status_code == 404
    assert project[1].is_file()


def test_only_snapshot_file_not_directory_can_be_deleted(client, project):
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(project[1].parent)))
    assert response.status_code == 422
    assert project[1].is_file()


@pytest.mark.parametrize("target", ["root-variables", "export", "other-project", "outside-folder"])
def test_existing_arbitrary_file_cannot_be_deleted(client, project, tmp_path, target):
    root, snapshot = project
    wrong = {
        "root-variables": root / "variables.json",
        "export": snapshot.parent / "variables.yaml",
        "other-project": root / "config-wizard" / "project-016" / "project_state.json",
        "outside-folder": tmp_path / "unrelated" / "project_state.json",
    }[target]
    wrong.parent.mkdir(parents=True, exist_ok=True)
    wrong.write_text('{"project_number_000": "015"}', encoding="utf-8")
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(wrong)))
    assert response.status_code == 409
    assert wrong.is_file() and snapshot.is_file()


def test_normalized_absolute_path_is_accepted(client, project):
    payload = body(project)
    payload["aifactory_folder"] += os.sep
    if os.name == "nt":
        payload["path"] = payload["path"].upper()
    response = client.post(ENDPOINT, headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert os.path.normcase(response.json()["deleted_path"]) == os.path.normcase(str(project[1]))


@pytest.mark.parametrize("location", ["file", "project-directory", "factory-directory"])
def test_symlink_paths_are_rejected(client, project, tmp_path, location):
    root, snapshot = project
    outside = tmp_path / "linked-target"
    payload = body(project)
    if location == "file":
        snapshot.replace(outside)
        link, destination = snapshot, outside
    elif location == "project-directory":
        snapshot.parent.rename(outside)
        link, destination = snapshot.parent, outside
    else:
        root.rename(outside)
        link, destination = root, outside
    try:
        link.symlink_to(destination, target_is_directory=location != "file")
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable; reparse and junction guards tested separately")
        raise
    try:
        response = client.post(ENDPOINT, headers=HEADERS, json=payload)
        assert response.status_code == 422
        assert link.is_symlink()
        protected = destination if location == "file" else (
            destination / "project_state.json" if location == "project-directory"
            else destination / "config-wizard" / "project-015" / "project_state.json"
        )
        assert protected.is_file()
    finally:
        link.unlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
@pytest.mark.parametrize("location", ["project-directory", "factory-directory"])
def test_windows_junction_paths_are_rejected(client, project, tmp_path, location):
    import _winapi

    root, snapshot = project
    link = snapshot.parent if location == "project-directory" else root
    outside = tmp_path / "junction-target"
    link.rename(outside)
    _winapi.CreateJunction(str(outside), str(link))
    try:
        response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
        assert response.status_code == 422
        assert list(outside.rglob("project_state.json"))
    finally:
        os.rmdir(link)


def test_non_symlink_reparse_file_is_rejected(client, project, monkeypatch):
    original = os.lstat

    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if Path(path) == project[1]:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(os, "lstat", reparse)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 422
    assert project[1].is_file()


@pytest.mark.parametrize("location", ["file", "project-directory", "factory-directory"])
def test_symlink_mode_is_rejected_without_requiring_windows_privileges(client, project, monkeypatch, location):
    original = os.lstat
    link = {"file": project[1], "project-directory": project[1].parent, "factory-directory": project[0]}[location]

    def symlink(path, *args, **kwargs):
        if Path(path) == link:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", symlink)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 422
    assert project[1].is_file()


@pytest.mark.parametrize(
    ("error", "status"),
    [(PermissionError, 422), (OSError, 500), (FileNotFoundError, 404)],
)
def test_unlink_errors_are_sanitized_and_do_not_fallback(client, project, isolated, monkeypatch, error, status):
    fallback = legacy_snapshot(isolated, str(project[0]))
    original = os.unlink

    def failed(path, *args, **kwargs):
        if Path(path) == project[1]:
            raise error("private OS path and secret detail")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", failed)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == status
    assert "private OS path" not in response.text
    assert fallback.is_file() and project[1].is_file()


def test_disappearing_snapshot_returns_not_found(client, project, monkeypatch):
    original = wizard._list_project_snapshots

    def disappearing(*args, **kwargs):
        result = original(*args, **kwargs)
        project[1].unlink()
        return result

    monkeypatch.setattr(wizard, "_list_project_snapshots", disappearing)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 404


def test_replaced_snapshot_is_not_deleted(client, project, monkeypatch):
    original = wizard._list_project_snapshots
    calls = 0

    def replacing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            project[1].write_text('{"project_number_000": "016", "new": true}', encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(wizard, "_list_project_snapshots", replacing)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 409
    assert json.loads(project[1].read_text(encoding="utf-8"))["project_number_000"] == "016"


def test_listing_change_during_legacy_delete_is_a_conflict(client, project, isolated, monkeypatch):
    root, local = project
    local.unlink()
    fallback = legacy_snapshot(isolated, str(root))
    original = wizard._list_project_snapshots
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            wizard._save_project_snapshot({"_save_folder": str(root), "project_number_000": "015"})
        return original(*args, **kwargs)

    monkeypatch.setattr(wizard, "_list_project_snapshots", changed)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(fallback)))
    assert response.status_code == 409
    assert local.is_file() and fallback.is_file()


def test_factory_replaced_during_legacy_delete_is_a_conflict(client, project, isolated, monkeypatch):
    root, local = project
    local.unlink()
    fallback = legacy_snapshot(isolated, str(root))
    original = wizard._list_project_snapshots
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            root.rename(root.parent / "original-factory")
            root.mkdir()
        return original(*args, **kwargs)

    monkeypatch.setattr(wizard, "_list_project_snapshots", changed)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project, path=str(fallback)))
    assert response.status_code == 409
    assert fallback.is_file()


def test_delete_listing_never_creates_missing_legacy_directory(client, project, tmp_path, monkeypatch):
    missing = tmp_path / "missing-legacy"
    calls = []

    def snapshot_dir(*, create=True):
        calls.append(create)
        if create:
            forbidden()
        return str(missing)

    monkeypatch.setattr(wizard, "_snapshot_dir", snapshot_dir)
    response = client.post(ENDPOINT, headers=HEADERS, json=body(project))
    assert response.status_code == 200
    assert calls == [False, False]
    assert not missing.exists()


def test_openapi_documents_secured_delete_contract(client):
    contract = client.get("/openapi.json").json()
    operation = contract["paths"][ENDPOINT]["post"]
    assert operation["security"] == [{"APIKeyHeader": []}]
    assert {"200", "404", "409", "422", "500"} <= operation["responses"].keys()
    schemas = contract["components"]["schemas"]
    assert set(schemas["ProjectDeleteBody"]["required"]) == {"aifactory_folder", "project_number", "path"}
    assert set(schemas["ProjectDeleted"]["required"]) == {"deleted_path", "message"}
