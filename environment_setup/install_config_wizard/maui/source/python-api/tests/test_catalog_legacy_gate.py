from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from src import api


IDENTITY = "11111111-1111-4111-8111-111111111111"
DEPLOYMENTS = "/api/v1/operations/project-deployments"


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path / "aifactory"
    marker = root / "config-wizard" / "catalog.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(api.API_KEY_ENV, "catalog-gate-test")

    def forbidden(*args, **kwargs):
        pytest.fail("Legacy services must not inspect or mutate a catalog root")

    for name in ("_operations_service", "_project_deployment_service"):
        monkeypatch.setattr(api, name, forbidden)
    for name in ("_list_project_snapshots", "_list_scalesets", "_save_project_snapshot", "_save_scaleset_snapshot",
                 "_delete_project_snapshot", "_delete_scaleset_snapshot", "_startup_import_candidate"):
        monkeypatch.setattr(api.wizard, name, forbidden)
    monkeypatch.setattr(api.project_verification, "verify_resource_groups", forbidden)
    monkeypatch.setattr(api.scale_set_verification, "verify_resource_groups", forbidden)
    return SimpleNamespace(root=root, marker=marker, headers={"X-API-Key": "catalog-gate-test"},
                           client=TestClient(api.app, client=("127.0.0.1", 54321)))


@pytest.mark.parametrize("route,fields", [
    ("/projects", {}),
    ("/projects/load", {"project_number": "001"}),
    ("/projects/delete", {"project_number": "001", "path": "unused"}),
    ("/projects/verify-resource-groups", {"project_number": "001", "path": "unused"}),
    ("/scale-sets", {}),
    ("/scale-sets/load", {"scale_set_id": "dev001"}),
    ("/scale-sets/delete", {"scale_set_id": "dev001", "path": "unused"}),
    ("/scale-sets/verify-resource-groups", {"scale_set_id": "dev001", "path": "unused"}),
    ("/startup/load", {"project_number": "001"}),
    ("/analytics/current-factory", {}),
    ("/operations/overview", {"include_azure": True}),
    ("/operations/factory-actions", {"action": "create", "target_region": "swedencentral"}),
    ("/operations/project-actions", {"action": "deploy", "project_number": "001",
                                     "source_environment": "dev", "target_environment": "stage"}),
])
def test_catalog_root_rejects_legacy_folder_calls_before_services(context, route, fields):
    result = context.client.post("/api/v1" + route, headers=context.headers,
                                 json={"aifactory_folder": str(context.root), **fields})
    assert result.status_code == 409, result.text
    assert "/api/v1/factory-catalog" in result.json()["detail"]
    assert context.marker.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("route", ["/projects/save", "/scale-sets/save"])
def test_catalog_root_rejects_legacy_state_writes(context, route):
    result = context.client.post("/api/v1" + route, headers=context.headers,
                                 json={"state": {"_save_folder": str(context.root)}})
    assert result.status_code == 409, result.text


@pytest.mark.parametrize("route,fields", [
    ("/plan", {"project_number": "001", "source_environment": "dev", "target_environment": "stage"}),
    ("/prepare", {"draft_id": IDENTITY}),
    ("/start", {"confirmation_id": IDENTITY}),
    ("/reconcile/prepare", {"job_id": IDENTITY}),
    ("/reconcile", {"confirmation_id": IDENTITY}),
    ("/terminal/input", {"job_id": IDENTITY, "data": "x"}),
    ("/terminal/resize", {"job_id": IDENTITY, "columns": 80, "rows": 24}),
])
def test_catalog_root_rejects_legacy_deployment_writes(context, route, fields):
    result = context.client.post(DEPLOYMENTS + route, headers=context.headers,
                                 json={"folder": str(context.root), **fields})
    assert result.status_code == 409, result.text


@pytest.mark.parametrize("route,fields", [("", {}), ("/terminal", {"job_id": IDENTITY})])
def test_catalog_root_rejects_legacy_deployment_reads(context, route, fields):
    result = context.client.get(DEPLOYMENTS + route, headers=context.headers,
                                params={"folder": str(context.root), **fields})
    assert result.status_code == 409, result.text


def test_authentication_precedes_catalog_scope_rejection(context):
    result = context.client.post("/api/v1/projects", json={"aifactory_folder": str(context.root)})
    assert result.status_code == 401


def test_legacy_without_catalog_still_reaches_existing_handler(context, monkeypatch):
    context.marker.unlink()
    monkeypatch.setattr(api.wizard, "_list_project_snapshots", lambda folder: {})
    result = context.client.post("/api/v1/projects", headers=context.headers,
                                 json={"aifactory_folder": str(context.root)})
    assert result.status_code == 200 and result.json() == {"projects": []}
