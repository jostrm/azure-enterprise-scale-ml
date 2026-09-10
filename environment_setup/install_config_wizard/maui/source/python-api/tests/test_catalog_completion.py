import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src import api, api_sidecar, catalog_worker, catalog_settings, factory_catalog as catalog
from src.catalog_frozen_plan import FrozenPlanner
from src.catalog_storage import CatalogError
from src.factory_catalog_models import CatalogPrepare
from tests.test_catalog_runtime import VERSION, deploy_request, harness
from tests.test_factory_catalog import OWNER, SUB, TENANT, migrate, request, root, scale, service


def test_factory_versions_are_independent_and_clone_inherits_without_root_overwrite(root, service):
    original = (root / "variables.json").read_bytes()
    migrate(root, service)
    created = []
    for prefix, version in (("alpha-", "1.25"), ("beta-", None)):
        body = request(root, "create-factory", target_prefix=prefix, target_region="swedencentral",
                       scale_sets=[scale(suffix="001")])
        if version is not None:
            body["aifactory_version"] = version
        preview = service.prepare(body, OWNER)
        assert preview["can_execute"], preview["blockers"]
        service.confirm(str(root), preview["confirmation_id"], OWNER)
        created.append(preview["target"])
    first, second = created
    assert first["aifactory_version"] == "1.25"
    assert second["aifactory_version"] == "124"
    inherited = service.prepare(request(root, "clone", factory_id=first["id"], target_prefix="clone-"), OWNER)
    assert inherited["target"]["aifactory_version"] == "1.25"
    service.confirm(str(root), inherited["confirmation_id"], OWNER)
    changed = service.prepare(request(root, "clone", factory_id=first["id"], target_prefix="next-",
                                      aifactory_version="126", include_projects="all"), OWNER)
    assert changed["target"]["aifactory_version"] == "126"
    service.confirm(str(root), changed["confirmation_id"], OWNER)
    factories = {item["id"]: item for item in service.list(str(root))["factories"]}
    assert factories[first["id"]]["aifactory_version"] == "1.25"
    assert factories[second["id"]]["aifactory_version"] == "124"
    assert (root / "variables.json").read_bytes() == original
    assert not (root / "config-wizard" / "aifactory-version.json").exists()


@pytest.mark.parametrize("value", ["", "release/../../other", "125; echo unsafe", "1.25.3"])
def test_invalid_saved_factory_version_is_rejected_before_any_change(root, service, value):
    factory = migrate(root, service)
    before = catalog.source_revision(root)
    with pytest.raises(ValidationError):
        service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-",
                                aifactory_version=value), OWNER)
    assert catalog.source_revision(root) == before


def test_scale_set_cannot_silently_change_its_factory_version(root, service):
    factory = migrate(root, service)
    with pytest.raises(ValidationError):
        CatalogPrepare.model_validate(request(root, "create-scale-set", factory_id=factory["id"],
                                              scale_sets=[scale()], aifactory_version="125"))


def test_runtime_inheritance_uses_selected_factory_not_another_root_default(root, harness):
    service, runtime, factory, queue, _ = harness
    document = catalog.load_document(root)
    document["factories"][0].update(aifactory_version="125", version_ref="125")
    catalog.commit_document(root, document)
    seen = []

    def resolve(folder, version):
        seen.append(version)
        return {**VERSION, "requested_version": version, "branch": "release/v1." + version[1:]}

    runtime.resolver = resolve
    body = deploy_request(root, factory)
    body.pop("version_ref")
    preview = service.prepare(body, OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert preview["source_version"]["requested_version"] == "125"
    assert preview["source_version"]["aifactory_version"] is None
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert seen == ["125", "125"]
    assert len(queue) == 1


@pytest.mark.parametrize("rotate_owner,expected", [(False, 200), (True, 404)])
def test_catalog_owner_survives_transport_key_rotation_but_not_os_owner_change(root, service, monkeypatch,
                                                                            rotate_owner, expected):
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    monkeypatch.setenv("AIFACTORY_API_KEY", "first-key")
    monkeypatch.setenv("AIFACTORY_CATALOG_OWNER", "windows:S-1-5-21-test-user")
    with TestClient(api.app, client=("127.0.0.1", 50000)) as client:
        preview = client.post("/api/v1/factory-catalog/prepare", headers={"X-API-Key": "first-key"},
                              json=request(root, "migrate"))
        assert preview.status_code == 200 and preview.json()["can_execute"]
        monkeypatch.setenv("AIFACTORY_API_KEY", "rotated-key")
        if rotate_owner:
            monkeypatch.setenv("AIFACTORY_CATALOG_OWNER", "windows:S-1-5-21-other-user")
        body = {"folder": str(root), "contract_version": 1, "confirmation_id": preview.json()["confirmation_id"]}
        assert client.post("/api/v1/factory-catalog/confirm", headers={"X-API-Key": "first-key"}, json=body).status_code == 401
        response = client.post("/api/v1/factory-catalog/confirm", headers={
            "X-API-Key": "rotated-key", "X-Catalog-Owner": "windows:S-1-5-21-test-user",
        }, json=body)
        assert response.status_code == expected
        assert catalog.has_catalog(root) == (expected == 200)


def test_sidecar_worker_mode_dispatches_without_starting_http_or_requiring_api_key(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["aifactory-api.exe", "--catalog-worker", "--help"])
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    monkeypatch.setattr(catalog_worker, "main", lambda argv: calls.append(argv) or 2)
    monkeypatch.setattr(api_sidecar.uvicorn, "run", Mock(side_effect=AssertionError("No HTTP server")))
    monkeypatch.setattr(api_sidecar, "watch_parent", Mock(side_effect=AssertionError("PTY owns worker lifetime")))
    assert api_sidecar.main() == 2
    assert calls == [["--help"]]


def test_packaged_runtime_launches_same_executable_in_protected_worker_mode(root, harness, monkeypatch):
    service, runtime, factory, queue, _ = harness
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    launches = []
    original_launcher = runtime.pty_factory

    def launch(argv, cwd, env):
        launches.append((argv, env))
        return original_launcher(argv, cwd, env)

    runtime.pty_factory = launch
    runtime.cli.tools = lambda: {"python": sys.executable}
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(Path(api.__file__).parents[1]), raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\installed\aifactory-api.exe")
    monkeypatch.setenv("GITHUB_TOKEN", "not-a-real-token")
    queue.pop()()
    outcome = runtime.job(root, job["id"], OWNER)
    assert outcome["status"] == "succeeded", outcome
    argv, environment = launches[0]
    assert argv[:2] == [r"C:\installed\aifactory-api.exe", "--catalog-worker"]
    assert argv[argv.index("--parent-pid") + 1] == str(os.getpid())
    assert "--protected-manifest" in argv and "--expected-hash" in argv
    assert "GITHUB_TOKEN" not in environment
    assert not any(argument.endswith("catalog_worker.py") for argument in argv)


@pytest.mark.parametrize("parameter", ["tags", "tagsProject"])
def test_actual_tag_parameter_preserves_customer_values_and_forces_ownership(parameter):
    target = {"environment": "stage", "region": "northeurope", "prefix": "dc-", "suffix": "001",
              "factory_id": "factory", "scaleset_id": "scale"}
    schema = {parameter: {"type": "object", "defaultValue": {}}}
    variables = {"tagsProject": json.dumps({"costCenter": "123456", "aifactory.logical_project_id": "logical"})}
    result = FrozenPlanner.parameters(schema, variables, {}, target, "017")
    assert set(result) == {parameter}
    assert result[parameter] == {"costCenter": "123456", "aifactory.logical_project_id": "logical",
                                 "aifactory.factory_id": "factory", "aifactory.scaleset_id": "scale",
                                 "aifactory.project_id": "017"}
    with pytest.raises(CatalogError, match="ownership"):
        FrozenPlanner.parameters(schema, variables, {parameter: {"aifactory.factory_id": "other"}}, target, "017")


def test_unknown_version_diagnostics_survive_api_serialization():
    response = api.ProjectDeploymentDrafts.model_validate({
        "drafts": [], "version_blockers": ["Installed version is unknown; select or save it explicitly."]})
    assert response.model_dump()["version_blockers"] == ["Installed version is unknown; select or save it explicitly."]


def test_scoped_settings_can_rebind_clone_references_without_changing_source(root, service):
    original = (root / "variables.json").read_bytes()
    factory = migrate(root, service)
    clone = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-",
                                    include_projects="all"), OWNER)
    service.confirm(str(root), clone["confirmation_id"], OWNER)
    target = clone["target"]
    project = target["projects"][0]
    settings = catalog_settings.read(str(root), target["id"], project_id=project["id"])
    assert "technical_admins_ad_object_id" in settings["field_keys"]
    assert "tenantId" not in settings["field_keys"]
    assert "servicePrincipalSecret" not in settings["state"]
    source_before = catalog.load_document(root)["configurations"][factory["id"]]
    preview = service.prepare(request(
        root, "configure-settings", factory_id=target["id"], project_id=project["id"],
        expected_revision=settings["revision"], settings={"technical_admins_ad_object_id": TENANT}), OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert catalog_settings.read(str(root), target["id"], project_id=project["id"])["state"]["technical_admins_ad_object_id"] != TENANT
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert catalog_settings.read(str(root), target["id"], project_id=project["id"])["state"]["technical_admins_ad_object_id"] == TENANT
    assert catalog.load_document(root)["configurations"][factory["id"]] == source_before
    assert (root / "variables.json").read_bytes() == original


@pytest.mark.parametrize("key", ["tenantId", "dev_sub_id", "project_number_000", "servicePrincipalSecret",
                                "_save_folder", "deleteAllForProject", "not_a_wizard_field"])
def test_settings_reject_identity_credentials_paths_and_unlisted_fields(root, service, key):
    factory = migrate(root, service)
    before = catalog.source_revision(root)
    with pytest.raises(ValidationError):
        service.prepare(request(root, "configure-settings", factory_id=factory["id"], settings={key: "do-not-save"}), OWNER)
    assert catalog.source_revision(root) == before


def test_settings_endpoint_retains_exact_scope_and_revision(root, service, monkeypatch):
    factory = migrate(root, service)
    project = factory["projects"][0]
    scale_id = project["placements"][0]["scale_set_id"]
    monkeypatch.setenv("AIFACTORY_API_KEY", "test-key")
    with TestClient(api.app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/factory-catalog/settings", headers={"X-API-Key": "test-key"},
                              params={"folder": str(root), "factory_id": factory["id"], "project_id": project["id"],
                                      "scale_set_id": scale_id})
        assert response.status_code == 200
        data = response.json()
        assert data["contract_version"] == 1
        assert data["factory_id"] == factory["id"] and data["project_id"] == project["id"]
        assert data["scale_set_id"] == scale_id
        assert data["revision"] == catalog.source_revision(root)
        assert set(data["field_keys"]) == set(data["state"])
        assert client.get("/api/v1/factory-catalog/settings", params={"folder": str(root), "factory_id": factory["id"]}).status_code == 401
