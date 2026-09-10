from fastapi.testclient import TestClient
import json
from pydantic import ValidationError
import pytest

from src import api, factory_catalog as catalog
from src.factory_catalog_models import CatalogFactorySummary, CatalogPrepare
from tests.test_factory_catalog import OWNER, root, service, request, migrate
from tests.test_factory_catalog_setup import create_request, scale_input


def assert_persisted_version(root, factory):
    stored = json.loads((root / "config-wizard" / "catalog.json").read_text(encoding="utf-8"))
    persisted = next(item for item in stored["factories"] if item["id"] == factory["id"])
    projection = json.loads((root / "config-wizard" / "factories" / factory["key"] / "factory_state.json").read_text(encoding="utf-8"))
    for value in (persisted, projection):
        assert value["version_ref"] == factory["version_ref"]
        assert value["aifactory_version"] == factory["aifactory_version"]


@pytest.mark.parametrize("selected,expected", [(None, "124"), ("1.25", "125"), ("main", "main")])
def test_saved_version_alias_survives_http_clone_and_new_scale(tmp_path, service, monkeypatch, selected, expected):
    root = tmp_path / "aifactory"
    root.mkdir()
    body = create_request(root)
    if selected is not None:
        body["aifactory_version"] = selected
    preview = service.prepare(body, OWNER)
    assert preview["can_execute"], preview["blockers"]
    factory = service.confirm(str(root), preview["confirmation_id"], OWNER)["catalog"]["factories"][0]
    assert factory["version_ref"] == expected
    assert factory["aifactory_version"] == (selected or "124")
    assert_persisted_version(root, factory)
    monkeypatch.setenv(api.API_KEY_ENV, "catalog-version-alias")
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    result = client.get("/api/v1/factory-catalog", headers={"X-API-Key": "catalog-version-alias"},
                        params={"folder": str(root)})
    assert result.status_code == 200, result.text
    assert result.json()["factories"][0]["version_ref"] == expected

    clone = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="copied-"), OWNER)
    copied = service.confirm(str(root), clone["confirmation_id"], OWNER)["catalog"]["factories"][-1]
    assert copied["version_ref"] == expected
    assert_persisted_version(root, copied)
    overridden = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="updated-",
                                         aifactory_version="1.100"), OWNER)
    updated = service.confirm(str(root), overridden["confirmation_id"], OWNER)["catalog"]["factories"][-1]
    assert updated["version_ref"] == "1.100"
    assert_persisted_version(root, updated)

    scale = {**scale_input(), "suffix": "004", "network": {"vnet_cidr": "172.24.0.0/18", "max_projects": 7}}
    added = service.prepare(request(root, "create-scale-set", factory_id=factory["id"], scale_sets=[scale]), OWNER)
    assert added["can_execute"], added["blockers"]
    result = service.confirm(str(root), added["confirmation_id"], OWNER)["catalog"]
    assert next(item for item in result["factories"] if item["id"] == factory["id"])["version_ref"] == expected
    assert_persisted_version(root, factory)


def test_legacy_unknown_version_alias_is_null_and_conflicts_are_rejected(root, service):
    migrate(root, service)
    document = catalog.load_document(root)
    document["factories"][0].update(aifactory_version=None, version_ref=None)
    catalog.commit_document(root, document)
    factory = service.list(str(root))["factories"][0]
    assert factory["version_ref"] is None and factory["aifactory_version"] is None
    assert_persisted_version(root, factory)
    with pytest.raises(ValidationError, match="version_ref"):
        CatalogFactorySummary.model_validate({**factory, "aifactory_version": "1.25", "version_ref": "126"})


@pytest.mark.parametrize("matching_raw_alias", [False, True])
def test_configuration_version_ref_roundtrips_http_and_persisted_state(tmp_path, service, monkeypatch, matching_raw_alias):
    root = tmp_path / "aifactory"
    root.mkdir()
    monkeypatch.setenv(api.API_KEY_ENV, "catalog-config-version")
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    headers = {"X-API-Key": "catalog-config-version"}

    def save(body):
        response = client.post("/api/v1/factory-catalog/prepare", headers=headers, json=body)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["can_execute"], preview["blockers"]
        response = client.post("/api/v1/factory-catalog/confirm", headers=headers, json={
            "folder": str(root), "contract_version": 1, "confirmation_id": preview["confirmation_id"]})
        assert response.status_code == 200, response.text
        return response.json()["catalog"]["factories"][-1]

    body = {**create_request(root), "version_ref": "1.25"}
    if matching_raw_alias:
        body["aifactory_version"] = "125"
    factory = save(body)
    assert factory["version_ref"] == "125"
    assert factory["aifactory_version"] == ("125" if matching_raw_alias else "1.25")
    assert_persisted_version(root, factory)
    copied = save(request(root, "clone", factory_id=factory["id"], target_prefix="inherited-"))
    assert copied["version_ref"] == "125"
    assert_persisted_version(root, copied)
    changed = save(request(root, "clone", factory_id=factory["id"], target_prefix="changed-", version_ref="1.26"))
    assert changed["version_ref"] == "126" and changed["aifactory_version"] == "1.26"
    assert_persisted_version(root, changed)
    scale = {**scale_input(), "suffix": "004", "network": {"vnet_cidr": "172.24.0.0/18", "max_projects": 7}}
    save(request(root, "create-scale-set", factory_id=factory["id"], scale_sets=[scale], version_ref="125"))
    assert_persisted_version(root, factory)
    response = client.get("/api/v1/factory-catalog", headers=headers, params={"folder": str(root)})
    assert response.status_code == 200, response.text
    assert next(item for item in response.json()["factories"] if item["id"] == factory["id"])["version_ref"] == "125"

    before = catalog.source_revision(root)
    conflict = client.post("/api/v1/factory-catalog/prepare", headers=headers, json=request(
        root, "clone", factory_id=factory["id"], target_prefix="conflict-", aifactory_version="125", version_ref="126"))
    assert conflict.status_code == 422
    blocked = client.post("/api/v1/factory-catalog/prepare", headers=headers, json=request(
        root, "create-scale-set", factory_id=factory["id"], scale_sets=[{**scale, "suffix": "005"}], version_ref="126"))
    assert blocked.status_code == 200 and not blocked.json()["can_execute"]
    assert "inherit" in " ".join(blocked.json()["blockers"])
    assert catalog.source_revision(root) == before


@pytest.mark.parametrize("value", ["../other", "125; echo unsafe", "1.25.3"])
def test_configuration_version_alias_rejects_invalid_selectors(tmp_path, value):
    with pytest.raises(ValidationError):
        CatalogPrepare.model_validate({**create_request(tmp_path), "version_ref": value})


def test_migration_version_override_stays_forbidden(root):
    with pytest.raises(ValidationError, match="Migration preserves"):
        CatalogPrepare.model_validate(request(root, "migrate", version_ref="124"))
