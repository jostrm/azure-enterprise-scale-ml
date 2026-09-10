import copy
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src import api, factory_catalog as catalog
from src.catalog_frozen_plan import FrozenPlanner
from src.catalog_storage import CatalogError
from tests.test_factory_catalog import OWNER, root, service, request, migrate
from tests.test_factory_catalog_setup import scale_input


def project_body(root, factory, number, scale=None):
    scale = scale or factory["scale_sets"][0]
    return request(root, "add-project", factory_id=factory["id"], project={
        "number": number, "display_name": "Forecasting", "placements": [
            {"environment": scale["environment"], "scale_set_id": scale["id"]}]})


def confirm(root, service, body):
    preview = service.prepare(body, OWNER)
    assert preview["can_execute"], preview["blockers"]
    return service.confirm(str(root), preview["confirmation_id"], OWNER)["catalog"]


def add_scale(root, service, factory, environment="dev", suffix="002"):
    item = {**scale_input(), "environment": environment, "suffix": suffix}
    result = confirm(root, service, request(root, "create-scale-set", factory_id=factory["id"], scale_sets=[item]))
    return result["factories"][0]["scale_sets"][-1]


def test_add_project_creates_a_new_logical_definition_without_deployment(root, service):
    factory = migrate(root, service)
    original = copy.deepcopy(factory["projects"][0])
    before = (root / "variables.json").read_bytes()
    result = confirm(root, service, project_body(root, factory, "002"))
    project = result["factories"][0]["projects"][-1]
    assert project["id"] != original["id"]
    assert project["number"] == "002" and project["status"] == "draft"
    assert result["factories"][0]["projects"][0] == original
    assert (root / "variables.json").read_bytes() == before
    document = catalog.load_document(root)
    assert document["configurations"][factory["id"]]["projects"][project["id"]] == {
        "project_number_000": "002", "projectName": "Forecasting"}
    assert (root / "config-wizard" / "factories" / factory["key"] / "projects" / project["key"] / "placements.json").is_file()


def test_project_numbers_are_unique_per_physical_scope_not_globally(root, service):
    factory = migrate(root, service)
    blocked = service.prepare(project_body(root, factory, "001"), OWNER)
    assert not blocked["can_execute"]
    assert "Project number conflicts" in " ".join(blocked["blockers"])
    scale = add_scale(root, service, factory)
    result = confirm(root, service, project_body(root, factory, "001", scale))
    projects = result["factories"][0]["projects"]
    assert len({project["id"] for project in projects}) == 2
    assert {project["number"] for project in projects} == {"001"}


def test_adding_project_placements_preserves_identity_and_detects_promotion_conflicts(root, service):
    factory = migrate(root, service)
    dev = add_scale(root, service, factory)
    result = confirm(root, service, project_body(root, factory, "001", dev))
    project = result["factories"][0]["projects"][-1]
    original = copy.deepcopy(project["placements"])
    body = request(root, "add-project-placements", factory_id=factory["id"], project_id=project["id"],
                   placements=[{"environment": "stage", "scale_set_id": factory["scale_sets"][1]["id"]}])
    blocked = service.prepare(body, OWNER)
    assert not blocked["can_execute"]
    assert "Project number conflicts" in " ".join(blocked["blockers"])
    stage = add_scale(root, service, factory, "stage")
    body["placements"][0]["scale_set_id"] = stage["id"]
    result = confirm(root, service, body)
    updated = next(item for item in result["factories"][0]["projects"] if item["id"] == project["id"])
    assert updated["placements"] == [*original, {"environment": "stage", "scale_set_id": stage["id"]}]
    assert updated["number"] == project["number"]


def test_existing_project_placement_cannot_be_silently_retargeted(root, service):
    factory = migrate(root, service)
    dev = add_scale(root, service, factory)
    before = catalog.source_revision(root)
    preview = service.prepare(request(root, "add-project-placements", factory_id=factory["id"],
        project_id=factory["projects"][0]["id"], placements=[{"environment": "dev", "scale_set_id": dev["id"]}]), OWNER)
    assert not preview["can_execute"]
    assert "cannot be silently retargeted" in " ".join(preview["blockers"])
    assert catalog.source_revision(root) == before


@pytest.mark.parametrize("change", ["environment", "unknown-scale", "capacity"])
def test_project_placements_require_exact_scope_and_capacity(root, service, change):
    factory = migrate(root, service)
    body = project_body(root, factory, "002")
    if change == "environment":
        body["project"]["placements"][0]["environment"] = "prod"
    elif change == "unknown-scale":
        body["project"]["placements"][0]["scale_set_id"] = str(uuid4())
    else:
        document = catalog.load_document(root)
        document["factories"][0]["scale_sets"][0]["network"]["max_projects"] = 1
        catalog.commit_document(root, document)
    assert not service.prepare(body, OWNER)["can_execute"]


@pytest.mark.parametrize("change", ["zero", "empty", "duplicate-env", "caller-id", "macro"])
def test_new_project_schema_rejects_ambiguous_identity(root, service, change):
    factory = migrate(root, service)
    body = project_body(root, factory, "002")
    if change == "zero":
        body["project"]["number"] = "000"
    elif change == "empty":
        body["project"]["placements"] = []
    elif change == "duplicate-env":
        body["project"]["placements"] *= 2
    elif change == "caller-id":
        body["project"]["id"] = str(uuid4())
    else:
        body["project"]["display_name"] = "$(System.AccessToken)"
    with pytest.raises(ValidationError):
        service.prepare(body, OWNER)


def test_http_project_creation_and_placement_actions_use_same_review_contract(root, service, monkeypatch):
    factory = migrate(root, service)
    monkeypatch.setenv(api.API_KEY_ENV, "catalog-project-test")
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    headers = {"X-API-Key": "catalog-project-test"}
    endpoint = "/api/v1/factory-catalog"
    preview = client.post(endpoint + "/prepare", headers=headers, json=project_body(root, factory, "002"))
    assert preview.status_code == 200 and preview.json()["can_execute"], preview.text
    saved = client.post(endpoint + "/confirm", headers=headers, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": preview.json()["confirmation_id"]})
    assert saved.status_code == 200 and saved.json()["job"] is None
    project = saved.json()["catalog"]["factories"][0]["projects"][-1]
    preview = client.post(endpoint + "/prepare", headers=headers, json=request(root, "add-project-placements",
        factory_id=factory["id"], project_id=project["id"],
        placements=[{"environment": "stage", "scale_set_id": factory["scale_sets"][1]["id"]}]))
    assert preview.status_code == 200 and preview.json()["can_execute"], preview.text


def test_frozen_project_tags_preserve_custom_metadata_and_bind_logical_identity():
    logical, factory, scale = str(uuid4()), str(uuid4()), str(uuid4())
    target = {"environment": "dev", "region": "swedencentral", "prefix": "new-", "suffix": "001",
              "factory_id": factory, "scaleset_id": scale, "project_ids": ["002"]}
    variables = {"tagsProject": json.dumps({"cost-center": "analytics", "aifactory.logical_project_id": logical})}
    values = FrozenPlanner.parameters({"tags": {"type": "object"}}, variables, {}, target, "002")
    assert values["tags"] == {"cost-center": "analytics", "aifactory.logical_project_id": logical,
                              "aifactory.factory_id": factory, "aifactory.scaleset_id": scale, "aifactory.project_id": "002"}
    overridden = FrozenPlanner.parameters({"tags": {"type": "object"}}, variables,
                                          {"tags": {"cost-center": "reviewed"}}, target, "002")
    assert overridden["tags"]["cost-center"] == "reviewed"
    assert overridden["tags"]["aifactory.logical_project_id"] == logical
    with pytest.raises(CatalogError, match="ownership"):
        FrozenPlanner.parameters({"tags": {"type": "object"}}, variables,
                                 {"tags": {"AIFACTORY.FACTORY_ID": "wrong"}}, target, "002")
