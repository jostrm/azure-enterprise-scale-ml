import copy
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from src import api, factory_catalog as catalog
from src.catalog_storage import CatalogError, read_json
from tests.test_factory_catalog import OWNER, SUB, TENANT, root, service, request, migrate


def scale_input():
    return {"environment": "dev", "suffix": "003", "subscription_id": SUB, "tenant_id": TENANT,
            "orchestrator": "gha", "network": {"vnet_cidr": "172.20.0.0/18", "max_projects": 7}}


def create_request(root, prefix="new-"):
    return request(root, "create-factory", target_prefix=prefix, target_region="swedencentral", scale_sets=[scale_input()])


def binding_for(factory):
    scale = factory["scale_sets"][0]
    return {"contract_version": 1, "orchestrator": scale["orchestrator"], "writer_id": "catalog-writer",
            "repository": "https://github.com/org/catalog", "ref": "refs/heads/main", "shared_remote": True,
            "auth_namespace": "catalog-auth", "deployment_object_id": TENANT,
            "locks": {"account_url": "https://cataloglocks.blob.core.windows.net", "container": "locks",
                      "coordination_blob": "enrollment.json", "coordination_hash": "a" * 64, "revision": 1},
            "targets": [{"scale_set_id": scale["id"], "resource_group_ids": [
                f"/subscriptions/{SUB}/resourceGroups/catalog-owned"], "common_dependency_ids": []}]}


def prepare_binding(root, service, factory, binding):
    return service.prepare(request(root, "configure-binding", factory_id=factory["id"], binding=binding,
                                   expected_revision=service.list(str(root))["revision"]), OWNER)


def test_create_factory_is_a_local_empty_project_draft(root, service):
    source = migrate(root, service)
    before = (root / "variables.json").read_bytes()
    source_projection = root / "config-wizard" / "factories" / source["key"] / "factory_state.json"
    source_bytes = source_projection.read_bytes()
    preview = service.prepare(create_request(root), OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert preview["operation_mode"] == "configuration"
    target = preview["target"]
    assert target["id"] != source["id"] and target["status"] == "draft"
    assert target["projects"] == []
    assert [(scale["environment"], scale["suffix"]) for scale in target["scale_sets"]] == [("dev", "003")]
    assert len(service.list(str(root))["factories"]) == 1
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert result["job"] is None and len(result["catalog"]["factories"]) == 2
    assert (root / "variables.json").read_bytes() == before
    assert source_projection.read_bytes() == source_bytes
    assert (root / "config-wizard" / "factories" / target["key"] / "factory_state.json").is_file()


def test_empty_root_can_explicitly_create_without_legacy_migration(root, service, tmp_path):
    empty = tmp_path / "empty" / "aifactory"
    empty.mkdir(parents=True)
    preview = service.prepare(create_request(empty), OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert not catalog.has_catalog(empty)
    result = service.confirm(str(empty), preview["confirmation_id"], OWNER)
    assert result["catalog"]["mode"] == "catalog"
    assert result["catalog"]["factories"][0]["projects"] == []
    assert not (empty / "variables.json").exists()


def test_existing_legacy_root_cannot_be_silently_replaced(root, service):
    preview = service.prepare(create_request(root), OWNER)
    assert not preview["can_execute"]
    assert "explicit migration" in " ".join(preview["blockers"])
    assert not catalog.has_catalog(root)


@pytest.mark.parametrize("change", ["existing-identity", "capacity"])
def test_create_factory_validates_identity_and_actual_allocator(root, service, change):
    source = migrate(root, service)
    body = create_request(root)
    if change == "existing-identity":
        body["target_prefix"] = source["prefix"]
    else:
        body["scale_sets"][0]["network"]["max_projects"] = 8
    assert not service.prepare(body, OWNER)["can_execute"]


def test_prepare_rejects_stale_client_revision(root, service):
    migrate(root, service)
    with pytest.raises(CatalogError, match="revision changed"):
        service.prepare({**create_request(root), "expected_revision": "0" * 64}, OWNER)


def test_binding_is_reviewed_typed_local_state_not_verified_cloud_authority(root, service):
    factory = migrate(root, service)
    before = (root / "variables.json").read_bytes()
    binding = binding_for(factory)
    preview = prepare_binding(root, service, factory, binding)
    assert preview["can_execute"], preview["blockers"]
    assert preview["binding"] == binding
    assert preview["operation_mode"] == "configuration"
    destination = catalog.binding_path(root, factory, "gha")
    assert not destination.exists()
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    state = result["catalog"]["factories"][0]["bindings"][0]
    assert state == {"orchestrator": "gha", "configuration": binding, "error": None, "verified": False}
    assert read_json(destination) == binding
    assert result["catalog"]["revision"] != preview["source_revision"]
    assert (root / "variables.json").read_bytes() == before
    with pytest.raises(CatalogError, match="already used"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)


@pytest.mark.parametrize("change", ["scale", "subscription", "route"])
def test_binding_cannot_retarget_undeclared_physical_identity(root, service, change):
    factory = migrate(root, service)
    binding = binding_for(factory)
    if change == "scale":
        binding["targets"][0]["scale_set_id"] = str(uuid4())
    elif change == "subscription":
        binding["targets"][0]["resource_group_ids"][0] = binding["targets"][0]["resource_group_ids"][0].replace(SUB, TENANT)
    else:
        binding["orchestrator"] = "ado"
        binding["repository"] = "https://dev.azure.com/org/project/_git/repo"
    preview = prepare_binding(root, service, factory, binding)
    assert not preview["can_execute"]
    assert not catalog.binding_path(root, factory, binding["orchestrator"]).exists()


def test_binding_rejects_duplicate_physical_writers_across_factories(root, service):
    source = migrate(root, service)
    first = prepare_binding(root, service, source, binding_for(source))
    service.confirm(str(root), first["confirmation_id"], OWNER)
    preview = service.prepare(create_request(root), OWNER)
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    target = result["catalog"]["factories"][-1]
    blocked = prepare_binding(root, service, target, binding_for(target))
    assert not blocked["can_execute"]
    assert "another configured writer" in " ".join(blocked["blockers"])


def test_malformed_binding_is_visible_without_secret_echo_and_can_be_replaced(root, service):
    factory = migrate(root, service)
    destination = catalog.binding_path(root, factory, "gha")
    destination.parent.mkdir(parents=True)
    destination.write_text('{"credential": "never-echo-this",', encoding="utf-8")
    listed = service.list(str(root))
    assert "never-echo-this" not in json.dumps(listed)
    assert listed["factories"][0]["bindings"][0]["error"]
    preview = prepare_binding(root, service, factory, binding_for(factory))
    assert preview["can_execute"], preview["blockers"]
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert result["catalog"]["factories"][0]["bindings"][0]["error"] is None


def test_binding_revision_change_invalidates_confirmation(root, service):
    factory = migrate(root, service)
    preview = prepare_binding(root, service, factory, binding_for(factory))
    destination = catalog.binding_path(root, factory, "gha")
    destination.parent.mkdir(parents=True)
    destination.write_text('{"changed": true}', encoding="utf-8")
    with pytest.raises(CatalogError, match="revision changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert read_json(destination) == {"changed": True}


def test_binding_schema_rejects_extra_and_ambiguous_fields(root, service):
    factory = migrate(root, service)
    original = binding_for(factory)
    for change in ("command", "namespace", "duplicate"):
        binding = copy.deepcopy(original)
        if change == "command":
            binding["shell_command"] = "not-supported"
        elif change == "namespace":
            binding.pop("deployment_object_id")
        else:
            binding["targets"][0]["common_dependency_ids"] = binding["targets"][0]["resource_group_ids"]
        with pytest.raises(ValidationError):
            prepare_binding(root, service, factory, binding)


def test_http_local_creation_and_binding_roundtrip_are_typed_and_acknowledged(root, service, monkeypatch):
    migrate(root, service)
    monkeypatch.setenv("AIFACTORY_API_KEY", "catalog-setup-test")
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    headers = {"X-API-Key": "catalog-setup-test"}
    endpoint = "/api/v1/factory-catalog"
    preview = client.post(endpoint + "/prepare", json=create_request(root), headers=headers)
    assert preview.status_code == 200, preview.text
    response = client.post(endpoint + "/confirm", headers=headers, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": preview.json()["confirmation_id"]})
    assert response.status_code == 200, response.text
    factory = response.json()["catalog"]["factories"][-1]
    body = request(root, "configure-binding", factory_id=factory["id"], binding=binding_for(factory))
    preview = client.post(endpoint + "/prepare", json=body, headers=headers)
    assert preview.status_code == 200 and preview.json()["can_execute"], preview.text
    response = client.post(endpoint + "/confirm", headers=headers, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": preview.json()["confirmation_id"]})
    assert response.status_code == 200, response.text
    listed = client.get(endpoint, params={"folder": str(root)}, headers=headers)
    binding = listed.json()["factories"][-1]["bindings"][0]
    assert binding["verified"] is False and binding["configuration"]["targets"][0]["scale_set_id"] == factory["scale_sets"][0]["id"]
    body["binding"]["credential"] = "never-echo-credential"
    rejected = client.post(endpoint + "/prepare", json=body, headers=headers)
    assert rejected.status_code == 422
    assert "never-echo-credential" not in rejected.text
