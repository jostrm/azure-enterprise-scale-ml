import json
import socket
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, wizard


API_KEY = "unit-test-key"
EXPECTED_API_OPERATIONS = {
    ("GET", "/health"),
    ("GET", "/api/v1/schema"),
    ("GET", "/api/v1/simple-mode/options"),
    ("POST", "/api/v1/simple-mode/prepare"),
    ("POST", "/api/v1/simple-mode/start"),
    ("GET", "/api/v1/simple-mode/jobs/{job_id}"),
    ("POST", "/api/v1/state/defaults"),
    ("POST", "/api/v1/network/placement/preview"),
    ("POST", "/api/v1/validation"),
    ("POST", "/api/v1/import"),
    ("POST", "/api/v1/export"),
    ("POST", "/api/v1/startup/load"),
    ("POST", "/api/v1/projects"),
    ("POST", "/api/v1/projects/load"),
    ("POST", "/api/v1/projects/save"),
    ("POST", "/api/v1/projects/delete"),
    ("POST", "/api/v1/projects/verify-resource-groups"),
    ("POST", "/api/v1/scale-sets"),
    ("POST", "/api/v1/scale-sets/load"),
    ("POST", "/api/v1/scale-sets/save"),
    ("POST", "/api/v1/scale-sets/delete"),
    ("POST", "/api/v1/scale-sets/verify-resource-groups"),
    ("GET", "/api/v1/recent-projects"),
    ("POST", "/api/v1/recent-projects"),
    ("POST", "/api/v1/operations/overview"),
    ("POST", "/api/v1/analytics/current-factory"),
    ("POST", "/api/v1/tickets/list"),
    ("POST", "/api/v1/tickets/resource-group/parse"),
    ("POST", "/api/v1/tickets/create"),
    ("POST", "/api/v1/tickets/update"),
    ("POST", "/api/v1/tickets/connections/list"),
    ("POST", "/api/v1/tickets/connections/save"),
    ("POST", "/api/v1/tickets/sync/preview"),
    ("POST", "/api/v1/tickets/sync"),
    ("GET", "/api/v1/operations/regions"),
    ("POST", "/api/v1/operations/region-findings/report"),
    ("POST", "/api/v1/operations/region-findings/import"),
    ("POST", "/api/v1/operations/config/load"),
    ("POST", "/api/v1/operations/config/save"),
    ("POST", "/api/v1/operations/factory-actions"),
    ("POST", "/api/v1/factories/configuration/prepare"),
    ("POST", "/api/v1/factories/configuration/save"),
    ("GET", "/api/v1/factory-catalog"),
    ("GET", "/api/v1/factory-catalog/settings"),
    ("GET", "/api/v1/factory-catalog/parameters"),
    ("POST", "/api/v1/factory-catalog/parameters/prepare"),
    ("POST", "/api/v1/factory-catalog/parameters/confirm"),
    ("POST", "/api/v1/factory-catalog/prepare"),
    ("POST", "/api/v1/factory-catalog/confirm"),
    ("GET", "/api/v1/factory-catalog/jobs"),
    ("GET", "/api/v1/factory-catalog/jobs/{job_id}"),
    ("GET", "/api/v1/factory-catalog/terminal"),
    ("POST", "/api/v1/factory-catalog/terminal/input"),
    ("POST", "/api/v1/factory-catalog/terminal/resize"),
    ("POST", "/api/v1/factory-catalog/terminal/stop"),
    ("POST", "/api/v1/operations/project-actions"),
    ("GET", "/api/v1/operations/project-deployments"),
    ("POST", "/api/v1/operations/project-deployments/plan"),
    ("POST", "/api/v1/operations/project-deployments/prepare"),
    ("POST", "/api/v1/operations/project-deployments/start"),
    ("POST", "/api/v1/operations/project-deployments/reconcile/prepare"),
    ("POST", "/api/v1/operations/project-deployments/reconcile"),
    ("GET", "/api/v1/operations/project-deployments/terminal"),
    ("POST", "/api/v1/operations/project-deployments/terminal/input"),
    ("POST", "/api/v1/operations/project-deployments/terminal/resize"),
    ("POST", "/api/v1/operations/prompts/search"),
    ("POST", "/api/v1/azure/auth/status"),
    ("POST", "/api/v1/azure/auth/login"),
    ("POST", "/api/v1/azure/auth/logout"),
    ("GET", "/api/v1/azure/auth/operations/{operation_id}"),
}
GITHUB_REPOSITORY_STATE = {
    "github_username": "octocat",
    "github_use_ssh": "true",
    "github_template_repo": "example/template",
    "github_new_repo": "example/new-repo",
    "github_new_repo_visibility": "private",
}
GITHUB_REPOSITORY_ENV = {
    "GITHUB_USERNAME": "octocat",
    "GITHUB_USE_SSH": "true",
    "GITHUB_TEMPLATE_REPO": "example/template",
    "GITHUB_NEW_REPO": "example/new-repo",
    "GITHUB_NEW_REPO_VISIBILITY": "private",
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv(api.API_KEY_ENV, API_KEY)
    monkeypatch.setenv("AIFACTORY_OPERATIONS_DB", str(tmp_path / "operations.db"))
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    legacy_snapshots = tmp_path / "legacy-snapshots"
    legacy_snapshots.mkdir()
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(legacy_snapshots))
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def headers():
    return {"X-API-Key": API_KEY}


def test_all_custom_api_operations_are_accounted_for(client):
    operations = {
        (method.upper(), route.path)
        for route in api.app.routes
        for method in route.methods or set()
        if route.path == "/health" or route.path.startswith("/api/v1/")
    }

    assert operations == EXPECTED_API_OPERATIONS


def test_health_and_openapi_are_public(client):
    health = client.get("/health")
    contract = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "1.0.0"}
    assert contract.status_code == 200
    assert contract.json()["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey", "in": "header", "name": "X-API-Key"
    }


def test_secured_routes_require_configured_valid_key(client, monkeypatch):
    assert client.get("/api/v1/schema").status_code == 401
    assert client.get("/api/v1/schema", headers={"X-API-Key": "wrong"}).status_code == 401

    monkeypatch.delenv(api.API_KEY_ENV)
    response = client.get("/api/v1/schema", headers={"X-API-Key": API_KEY})
    assert response.status_code == 503
    assert api.API_KEY_ENV in response.json()["detail"]


def test_api_host_lifecycle_reports_real_readiness(monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, API_KEY)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    host = api.ApiHost(port=port)

    try:
        assert host.status == "stopped"
        assert host.start() is True
        assert host.status in {"starting", "running"}
        deadline = time.monotonic() + 5
        while host.status == "starting" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert host.status == "running"
        assert host.start() is False
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert json.load(response)["status"] == "ok"
    finally:
        host.stop()

    assert host.status == "stopped"


def test_api_host_rejects_missing_key_and_occupied_port(monkeypatch):
    monkeypatch.delenv(api.API_KEY_ENV, raising=False)
    host = api.ApiHost(port=8765)
    with pytest.raises(RuntimeError, match=api.API_KEY_ENV):
        host.start()

    monkeypatch.setenv(api.API_KEY_ENV, API_KEY)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    occupied_port = listener.getsockname()[1]
    try:
        occupied = api.ApiHost(port=occupied_port)
        with pytest.raises(OSError):
            occupied.start()
        assert occupied.status == "stopped"
    finally:
        listener.close()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("starting", "Starting API host at http://127.0.0.1:8765..."),
        ("running", "Running API host at http://127.0.0.1:8765"),
        ("stopped", "No API Host running. Go to Quicksetup to START it"),
    ],
)
def test_status_bar_reports_api_host_state(status, expected):
    status_var = Mock()
    label = Mock()
    app = SimpleNamespace(_api_status_var=status_var, _api_status_label=label)

    wizard.WizardApp._set_api_status(app, status)

    status_var.set.assert_called_once_with(expected)


def test_guarded_api_smoke_start_catches_no_error(monkeypatch, tmp_path):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    error_path = tmp_path / "api-smoke-error.txt"
    monkeypatch.setenv("AIFACTORY_API_SMOKE_PORT", str(port))
    monkeypatch.setenv("AIFACTORY_API_SMOKE_ERROR", str(error_path))

    result = wizard._run_packaged_api_smoke_test()

    assert result == 0
    assert not error_path.exists()


def test_schema_and_defaults(client, headers):
    schema = client.get("/api/v1/schema", headers=headers)
    defaults = client.post(
        "/api/v1/state/defaults",
        headers=headers,
        json={"state": {"project_number_000": "015"}},
    )

    assert schema.status_code == 200
    assert schema.json()["formats"] == ["yaml", "env", "json"]
    assert "project_variables" in schema.json()["sections"]
    assert "scale_set_variables" in schema.json()["sections"]
    assert defaults.status_code == 200
    assert defaults.json()["state"]["project_number_000"] == "015"
    assert "admin_location" in defaults.json()["state"]


def test_schema_region_options_reuse_the_complete_public_catalog(client, headers):
    schema = client.get("/api/v1/schema", headers=headers).json()
    catalog = client.get("/api/v1/operations/regions", headers=headers).json()["regions"]
    regions = schema["options"]["azure_regions"]

    assert regions == sorted({region["name"] for region in catalog})
    assert len(regions) >= 60
    assert {"swedencentral", "eastus2", "austriaeast", "newzealandnorth"} <= set(regions)
    assert "global" not in regions
    assert schema["defaults"]["admin_location"] in regions


def test_validation_honors_conditional_fields(client, headers):
    disabled = client.post(
        "/api/v1/validation",
        headers=headers,
        json={"state": {"byoASEv3": "false", "byoAseFullResourceId": "<todo>"}},
    )
    enabled = client.post(
        "/api/v1/validation",
        headers=headers,
        json={"state": {"byoASEv3": "true", "byoAseFullResourceId": "<todo>"}},
    )

    disabled_fields = {issue["field"] for issue in disabled.json()["issues"]}
    enabled_fields = {issue["field"] for issue in enabled.json()["issues"]}
    assert "byoAseFullResourceId" not in disabled_fields
    assert enabled.status_code == 200
    assert enabled.json()["valid"] is False
    assert "byoAseFullResourceId" in enabled_fields


@pytest.mark.parametrize(
    ("format_name", "content", "expected_key", "expected_value"),
    [
        ("yaml", "variables:\n  dev_sub_id: yaml-sub\n", "dev_sub_id", "yaml-sub"),
        ("env", "DEV_SUBSCRIPTION_ID=env-sub\n", "dev_sub_id", "env-sub"),
        ("json", '{"dev":{"dev_sub_id":"json-sub"},"stage_prod":{}}', "dev_sub_id", "json-sub"),
    ],
)
def test_import_inline_for_every_format(
    client, headers, format_name, content, expected_key, expected_value
):
    response = client.post(
        "/api/v1/import",
        headers=headers,
        json={"format": format_name, "content": content, "state": {}},
    )

    assert response.status_code == 200
    assert response.json()["fields_loaded"] == 1
    assert response.json()["state"][expected_key] == expected_value


def test_json_import_uses_dev_without_merging_stage_prod(client, headers):
    response = client.post(
        "/api/v1/import",
        headers=headers,
        json={
            "format": "json",
            "content": (
                '{"dev":{"dev_sub_id":"dev-sub"},'
                '"stage_prod":{"dev_sub_id":"stage-prod-sub"}}'
            ),
            "state": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["fields_loaded"] == 1
    assert response.json()["state"]["dev_sub_id"] == "dev-sub"


@pytest.mark.parametrize("initial_route", ["ado", "gha", None])
def test_json_import_restores_github_repository_settings_and_orchestrator(
    client, headers, initial_route
):
    response = client.post(
        "/api/v1/import",
        headers=headers,
        json={
            "format": "json",
            "content": json.dumps(
                {"dev": GITHUB_REPOSITORY_ENV, "stage_prod": {}}
            ),
            "state": {"orchestrator": initial_route} if initial_route else {},
        },
    )

    assert response.status_code == 200
    assert response.json()["fields_loaded"] == 5
    imported_state = response.json()["state"]
    assert imported_state["orchestrator"] == "gha"
    assert {key: imported_state[key] for key in GITHUB_REPOSITORY_STATE} == (
        GITHUB_REPOSITORY_STATE
    )


def test_gha_json_with_empty_repository_keeps_explicit_route(client, headers):
    exported = client.post("/api/v1/export", headers=headers, json={
        "format": "json", "state": {"orchestrator": "gha"},
    }).json()["content"]
    document = json.loads(exported)
    assert document["_wizard"] == {"orchestrator": "gha"}
    imported = client.post("/api/v1/import", headers=headers, json={
        "format": "json", "content": exported, "state": {"orchestrator": "ado"},
    })
    assert imported.status_code == 200
    assert imported.json()["state"]["orchestrator"] == "gha"


def test_shared_json_template_does_not_select_github(client, headers):
    path = Path(__file__).parents[1] / "template-files" / "variables.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for section in ("dev", "stage_prod"):
        assert document[section]["GITHUB_USERNAME"] == ""
        assert document[section]["GITHUB_NEW_REPO"] == ""
        assert document[section]["GITHUB_TEMPLATE_REPO"] == "azure/enterprise-scale-aifactory"
    imported = client.post("/api/v1/import", headers=headers, json={
        "format": "json", "path": str(path), "state": {"orchestrator": "ado"},
    })
    assert imported.status_code == 200
    assert imported.json()["state"]["orchestrator"] == "ado"


@pytest.mark.parametrize("evidence", [
    {"dev": {"GITHUB_NEW_REPO": "example/repository"}},
    {"dev": {"GITHUB_USERNAME": "example"}},
    {"dev": {"dev_sub_id": "test"}, "_wizard": {"orchestrator": "gha"}},
])
def test_startup_standalone_github_json_has_consistent_route(client, headers, tmp_path, evidence):
    folder = tmp_path / "aifactory"
    folder.mkdir()
    path = folder / "variables.json"
    path.write_text(json.dumps(evidence), encoding="utf-8-sig")
    response = client.post("/api/v1/startup/load", headers=headers, json={
        "aifactory_folder": str(folder), "project_number": "015",
    })
    assert response.status_code == 200
    assert response.json()["source_path"] == str(path)
    assert response.json()["orchestrator"] == response.json()["state"]["orchestrator"] == "gha"


def test_import_from_path_and_rejects_invalid_sources(client, headers, tmp_path):
    source = tmp_path / "variables.yaml"
    source.write_text("variables:\n  tenantId: tenant-from-file\n", encoding="utf-8")

    response = client.post(
        "/api/v1/import",
        headers=headers,
        json={"format": "yaml", "path": str(source), "state": {}},
    )
    empty = client.post(
        "/api/v1/import",
        headers=headers,
        json={"format": "yaml", "content": "unknown: value", "state": {}},
    )
    both = client.post(
        "/api/v1/import",
        headers=headers,
        json={"format": "yaml", "content": "x", "path": str(source), "state": {}},
    )

    assert response.status_code == 200
    assert response.json()["state"]["tenantId"] == "tenant-from-file"
    assert empty.status_code == 422
    assert both.status_code == 422


@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
def test_export_every_format_and_optional_file_write(
    client, headers, tmp_path, format_name
):
    destination = tmp_path / f"export.{format_name}"
    response = client.post(
        "/api/v1/export",
        headers=headers,
        json={
            "format": format_name,
            "path": str(destination),
            "state": {"dev_sub_id": "exported-sub"},
        },
    )

    assert response.status_code == 200
    assert destination.read_text(encoding="utf-8") == response.json()["content"]
    assert "exported-sub" in response.json()["content"]
    if format_name == "json":
        document = json.loads(response.json()["content"])
        assert set(document) == {"dev", "stage_prod"}
        assert document["dev"] == document["stage_prod"]
        assert document["dev"]["dev_sub_id"] == "exported-sub"


def test_gha_json_export_includes_github_repository_settings(client, headers):
    response = client.post(
        "/api/v1/export",
        headers=headers,
        json={
            "format": "json",
            "state": {"orchestrator": "gha", **GITHUB_REPOSITORY_STATE},
        },
    )

    assert response.status_code == 200
    document = json.loads(response.json()["content"])
    for section in ("dev", "stage_prod"):
        assert {key: document[section][key] for key in GITHUB_REPOSITORY_ENV} == (
            GITHUB_REPOSITORY_ENV
        )


def test_ado_json_export_omits_github_username(client, headers):
    response = client.post(
        "/api/v1/export",
        headers=headers,
        json={
            "format": "json",
            "state": {
                "orchestrator": "ado",
                "github_username": "must-not-be-exported",
            },
        },
    )

    assert response.status_code == 200
    document = json.loads(response.json()["content"])
    assert all(
        "GITHUB_USERNAME" not in document[section]
        for section in ("dev", "stage_prod")
    )


@pytest.mark.parametrize(
    ("save_function", "pipeline_filename"),
    [
        (wizard.save_azure_devops, "variables.yaml"),
        (wizard.save_github_actions, ".env"),
    ],
)
def test_pipeline_save_writes_one_json_at_aifactory_root(
    tmp_path, save_function, pipeline_filename
):
    root = tmp_path / "aifactory"
    pipeline_folder = root / "config-wizard" / "project-001"
    pipeline_folder.mkdir(parents=True)
    pipeline_path = pipeline_folder / pipeline_filename
    state = {"_save_folder": str(root), "dev_sub_id": "root-sub"}

    save_function(state, str(pipeline_path))

    root_json = root / "variables.json"
    assert pipeline_path.is_file()
    assert root_json.is_file()
    assert not (pipeline_folder / "variables.json").exists()
    document = json.loads(root_json.read_text(encoding="utf-8"))
    assert document["dev"]["dev_sub_id"] == "root-sub"
    assert document["stage_prod"]["dev_sub_id"] == "root-sub"


def test_github_actions_save_writes_repository_settings_to_root_json(tmp_path):
    root = tmp_path / "aifactory"
    pipeline_folder = root / "config-wizard" / "project-001"
    pipeline_folder.mkdir(parents=True)
    state = {
        "_save_folder": str(root),
        "orchestrator": "gha",
        **GITHUB_REPOSITORY_STATE,
    }

    wizard.save_github_actions(state, str(pipeline_folder / ".env"))

    document = json.loads((root / "variables.json").read_text(encoding="utf-8"))
    for section in ("dev", "stage_prod"):
        assert {key: document[section][key] for key in GITHUB_REPOSITORY_ENV} == (
            GITHUB_REPOSITORY_ENV
        )


def test_startup_load_detects_ado_yaml(client, headers, tmp_path):
    folder = tmp_path / "aifactory"
    variables = folder / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables"
    variables.mkdir(parents=True)
    source = variables / "variables.yaml"
    source.write_text("variables:\n  dev_sub_id: ado-sub\n", encoding="utf-8")

    response = client.post(
        "/api/v1/startup/load",
        headers=headers,
        json={"aifactory_folder": str(folder), "project_number": "015"},
    )

    assert response.status_code == 200
    assert response.json()["orchestrator"] == "ado"
    assert response.json()["source_path"] == str(source)
    assert response.json()["state"]["dev_sub_id"] == "ado-sub"


def test_startup_load_detects_gha_env(client, headers, tmp_path):
    folder = tmp_path / "repository" / "aifactory"
    folder.mkdir(parents=True)
    source = folder.parent / ".env"
    source.write_text("DEV_SUBSCRIPTION_ID=gha-sub\n", encoding="utf-8")

    response = client.post(
        "/api/v1/startup/load",
        headers=headers,
        json={"aifactory_folder": str(folder), "project_number": "015"},
    )

    assert response.status_code == 200
    assert response.json()["orchestrator"] == "gha"
    assert response.json()["state"]["dev_sub_id"] == "gha-sub"


def test_project_save_list_load_and_missing(client, headers, tmp_path):
    state = {
        "_save_folder": str(tmp_path),
        "project_number_000": "015",
        "orchestrator": "ado",
        "admin_aifactoryPrefixRG": "demo-",
        "admin_aifactorySuffixRG": "-007",
    }
    saved = client.post(
        "/api/v1/projects/save",
        headers=headers,
        json={"state": state, "write_variables": True},
    )
    listed = client.post(
        "/api/v1/projects", headers=headers, json={"aifactory_folder": str(tmp_path)}
    )
    loaded = client.post(
        "/api/v1/projects/load",
        headers=headers,
        json={"aifactory_folder": str(tmp_path), "project_number": "015"},
    )
    missing = client.post(
        "/api/v1/projects/load",
        headers=headers,
        json={"aifactory_folder": str(tmp_path), "project_number": "999"},
    )

    assert saved.status_code == 200
    assert Path(saved.json()["snapshot_path"]).is_file()
    assert Path(saved.json()["variables_path"]).is_file()
    project = next(item for item in listed.json()["projects"] if item["project_number"] == "015")
    assert project["label"] == "Project 015 (demo-007)"
    assert loaded.json()["state"]["project_number_000"] == "015"
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("subscriptions", "expected"),
    [
        (("subscription-z", "subscription-a", "subscription-z"), ["subscription-a", "subscription-z"]),
        (("", None, " "), []),
        ((" subscription-a ", "", "subscription-a"), ["subscription-a"]),
    ],
)
def test_project_listing_exposes_only_hydrated_deployment_scope(
    client, headers, tmp_path, monkeypatch, subscriptions, expected
):
    snapshot = wizard._save_project_snapshot({
        "_save_folder": str(tmp_path), "project_number_000": "015",
        "admin_aifactoryPrefixRG": "old-", "admin_location": "old-region",
    })
    state = {
        "admin_aifactoryPrefixRG": "hydrated-", "admin_aifactorySuffixRG": "-007",
        "admin_location": "swedencentral",
        **dict(zip(("dev_sub_id", "test_sub_id", "prod_sub_id"), subscriptions)),
        "unrelated_private_field": "must-not-be-exposed",
    }
    load = Mock(return_value=state)
    monkeypatch.setattr(wizard, "_load_project_state", load)
    monkeypatch.setattr(api, "_state", Mock(side_effect=AssertionError("Do not add API defaults")))

    response = client.post(
        "/api/v1/projects", headers=headers, json={"aifactory_folder": str(tmp_path)}
    )

    assert response.status_code == 200
    assert response.json()["projects"] == [{
        "project_number": "015", "path": snapshot, "label": "Project 015 (hydrated-007)",
        "owner": "Unknown", "planned_environments": [],
        "deployment_scope": {
            "prefix_rg": "hydrated-", "suffix_rg": "-007", "region": "swedencentral",
            "subscription_ids": expected,
        },
    }]
    load.assert_called_once_with(snapshot, str(tmp_path))


def test_scale_set_save_list_load_and_missing(client, headers, tmp_path):
    state = {
        "_save_folder": str(tmp_path),
        "admin_aifactorySuffixRG": "-007",
        "admin_aifactoryPrefixRG": "demo-",
        "orchestrator": "ado",
    }
    saved = client.post(
        "/api/v1/scale-sets/save", headers=headers, json={"state": state}
    )
    listed = client.post(
        "/api/v1/scale-sets", headers=headers, json={"aifactory_folder": str(tmp_path)}
    )
    loaded = client.post(
        "/api/v1/scale-sets/load",
        headers=headers,
        json={"aifactory_folder": str(tmp_path), "scale_set_id": "007"},
    )
    missing = client.post(
        "/api/v1/scale-sets/load",
        headers=headers,
        json={"aifactory_folder": str(tmp_path), "scale_set_id": "999"},
    )

    assert saved.status_code == 200
    assert Path(saved.json()["path"]).is_file()
    assert any(item["scale_set_id"] == "007" for item in listed.json()["scale_sets"])
    assert loaded.json()["state"]["admin_aifactorySuffixRG"] == "-007"
    assert missing.status_code == 404


def test_recent_projects_get_and_post(client, headers, tmp_path):
    initial = client.get("/api/v1/recent-projects", headers=headers)
    recorded = client.post(
        "/api/v1/recent-projects",
        headers=headers,
        json={
            "aifactory_folder": str(tmp_path),
            "project_number": "015",
            "orchestrator": "ado",
            "prefix_rg": "demo-",
            "suffix_rg": "007",
        },
    )

    assert initial.json() == {"recent_projects": []}
    assert recorded.status_code == 200
    assert recorded.json()["recent_projects"][0]["project"] == "015"
    assert json.loads(Path(wizard._SETTINGS_FILE).read_text(encoding="utf-8"))[
        "recent_projects"
    ][0]["orchestrator"] == "ado"