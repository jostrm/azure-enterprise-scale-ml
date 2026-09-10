import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src import api, factory_catalog as catalog, wizard
from src.catalog_storage import CatalogError, read_json, catalog_lock
from src.factory_catalog_models import CatalogPrepare
from src.factory_scope import current_factory_scope


SUB = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
OWNER = "owner-a"


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "aifactory"
    (root / "config-wizard").mkdir(parents=True)
    state = copy.deepcopy(wizard.DEFAULT_STATE)
    state.update(orchestrator="gha", admin_aifactoryPrefixRG="demo-", admin_aifactorySuffixRG="-001",
                 admin_location="swedencentral", admin_locationSuffix="sdc", tenantId=TENANT,
                 dev_sub_id=SUB, test_sub_id=SUB, prod_sub_id=SUB,
                 common_vnet_cidr="172.16.XX.0/18", dev_cidr_range="0", test_cidr_range="64", prod_cidr_range="128",
                 common_subnet_cidr="172.16.XX.0/26", common_subnet_scoring_cidr="172.16.XX.64/26",
                 common_pbi_subnet_cidr="172.16.XX.128/26", common_bastion_subnet_cidr="172.16.XX.192/26",
                 _save_folder=str(root), project_number_000="001")
    (root / "config-wizard" / "factory_state.json").write_text(json.dumps(state), encoding="utf-8")
    (root / "variables.json").write_text('{"dev":{"original":true}}', encoding="utf-8")
    project = root / "config-wizard" / "project-001" / "project_state.json"
    project.parent.mkdir()
    project.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr("src.deployment_config.protect", lambda raw: b"protected:" + raw)
    return root


@pytest.fixture
def service():
    return catalog.CatalogService(runtime=SimpleNamespace(shutdown=lambda: None))


def request(root, action, **kwargs):
    return {"folder": str(root), "contract_version": 1, "action": action, **kwargs}


def migrate(root, service):
    preview = service.prepare(request(root, "migrate"), OWNER)
    assert preview["can_execute"], preview["blockers"]
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    return result["catalog"]["factories"][0]


def test_legacy_get_is_read_only_and_stable(root, service):
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    first = service.list(str(root))
    assert first["mode"] == "legacy"
    assert len(first["factories"]) == 1
    assert len(first["factories"][0]["scale_sets"]) == 3
    assert first == service.list(str(root))
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_migration_preserves_originals_and_has_protected_backup(root, service):
    original = (root / "variables.json").read_bytes()
    factory_original = (root / "config-wizard" / "factory_state.json").read_bytes()
    factory = migrate(root, service)
    assert (root / "variables.json").read_bytes() == original
    assert (root / "config-wizard" / "factory_state.json").read_bytes() == factory_original
    assert service.list(str(root))["mode"] == "catalog"
    assert len(factory["projects"][0]["placements"]) == 3
    assert list((root / "config-wizard" / "catalog-backups").glob("*/*.dpapi"))
    assert all(ss["owned_resource_ids"] == [] for ss in factory["scale_sets"])


def test_clone_same_region_new_name_new_identity_and_no_root_write(root, service):
    original = (root / "variables.json").read_bytes()
    factory = migrate(root, service)
    source_file = root / "config-wizard" / "factories" / factory["key"] / "factory_state.json"
    source_bytes = source_file.read_bytes()
    preview = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-"), OWNER)
    assert preview["can_execute"], preview["blockers"]
    target = preview["target"]
    assert target["id"] != factory["id"]
    assert target["projects"] == []
    assert not ({s["id"] for s in target["scale_sets"]} & {s["id"] for s in factory["scale_sets"]})
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert len(result["catalog"]["factories"]) == 2
    assert result["catalog"]["requires_selection"]
    assert source_file.read_bytes() == source_bytes
    assert (root / "variables.json").read_bytes() == original


def test_clone_all_rebinds_project_placements_and_clears_resource_references(root, service):
    factory = migrate(root, service)
    document = catalog.load_document(root)
    config = document["configurations"][factory["id"]]
    config["projects"][factory["projects"][0]["id"]]["foundryApiManagementResourceId"] = "/subscriptions/old/resource"
    catalog.commit_document(root, document)
    preview = service.prepare(request(root, "clone", factory_id=factory["id"], target_region="westeurope",
                                      include_projects="all"), OWNER)
    assert preview["can_execute"], preview["blockers"]
    target = preview["target"]
    assert target["projects"][0]["id"] != factory["projects"][0]["id"]
    ids = {ss["id"] for ss in target["scale_sets"]}
    assert all(p["scale_set_id"] in ids for p in target["projects"][0]["placements"])
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    new_config = catalog.load_document(root)["configurations"][target["id"]]
    assert "/subscriptions/old" not in json.dumps(new_config)


def scale(environment="dev", suffix="002", max_projects=7, cidr="172.20.0.0/18"):
    return {"environment": environment, "suffix": suffix, "subscription_id": SUB, "tenant_id": TENANT,
            "orchestrator": "gha", "network": {"vnet_cidr": cidr, "max_projects": max_projects}}


def test_new_scale_set_only_requested_environment_and_capacity(root, service):
    factory = migrate(root, service)
    preview = service.prepare(request(root, "create-scale-set", factory_id=factory["id"], scale_sets=[scale()]), OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert len(preview["target"]["scale_sets"]) == 4
    assert len([s for s in preview["target"]["scale_sets"] if s["environment"] == "prod"]) == 1
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert (root / "config-wizard" / "factories" / factory["key"] / "scalesets" / "dev" / "002" / "scaleset_state.json").is_file()
    blocked = service.prepare(request(root, "create-scale-set", factory_id=factory["id"],
                                      scale_sets=[scale(suffix="003", max_projects=8)]), OWNER)
    assert not blocked["can_execute"]
    assert "allocator" in " ".join(blocked["blockers"])


def test_duplicate_scope_and_project_number_rejected(root, service):
    factory = migrate(root, service)
    preview = service.prepare(request(root, "create-scale-set", factory_id=factory["id"],
                                      scale_sets=[scale(suffix="001")]), OWNER)
    assert not preview["can_execute"]
    document = catalog.load_document(root)
    duplicate = copy.deepcopy(document["factories"][0]["projects"][0])
    duplicate.update(id=str(uuid4()), key="other-project")
    document["factories"][0]["projects"].append(duplicate)
    with pytest.raises(CatalogError, match="number conflicts"):
        catalog.validate_document(document)


def test_revision_expiry_owner_and_replay_guards(root, service):
    preview = service.prepare(request(root, "migrate"), OWNER)
    with pytest.raises(CatalogError, match="caller"):
        service.confirm(str(root), preview["confirmation_id"], "other")
    (root / "variables.json").write_text('{"dev":{"changed":true}}', encoding="utf-8")
    with pytest.raises(CatalogError, match="revision changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    second = service.prepare(request(root, "migrate"), OWNER)
    service.clock = lambda: 9999999999
    with pytest.raises(CatalogError, match="expired"):
        service.confirm(str(root), second["confirmation_id"], OWNER)
    service.clock = catalog.time.time
    service.confirm(str(root), second["confirmation_id"], OWNER)
    with pytest.raises(CatalogError, match="already used"):
        service.confirm(str(root), second["confirmation_id"], OWNER)


def test_migration_rejects_foreign_snapshot(root, service):
    path = root / "config-wizard" / "project-001" / "project_state.json"
    state = read_json(path)
    state["admin_aifactoryPrefixRG"] = "foreign-"
    path.write_text(json.dumps(state), encoding="utf-8")
    preview = service.prepare(request(root, "migrate"), OWNER)
    assert not preview["can_execute"]
    assert "ownership" in " ".join(preview["blockers"])
    assert not (root / catalog.CATALOG_PATH).exists()


def test_catalog_never_silently_uses_legacy_monitoring_scope(root, service):
    factory = migrate(root, service)
    with pytest.raises(CatalogError, match="explicit factory"):
        current_factory_scope(root)
    scope = current_factory_scope(root, factory["id"], factory["scale_sets"][0]["id"])
    assert scope["subscriptions"] == {"dev": SUB}
    preview = service.prepare(request(root, "create-scale-set", factory_id=factory["id"], scale_sets=[scale()]), OWNER)
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    with pytest.raises(CatalogError, match="Multiple scale sets"):
        current_factory_scope(root, factory["id"])
    with pytest.raises(catalog.factory_configuration.ConfigurationError, match="explicit factory ID"):
        catalog.factory_configuration.prepare_configuration("clone", "westeurope", str(root))


@pytest.mark.parametrize("extra", [{"contract_version": 2}, {"contract_version": True}, {"destination_folder": "C:\\evil"},
                                  {"target_prefix": "ignored"}, {"include_projects": "all"}])
def test_contract_rejects_unknown_or_ignored_inputs(root, extra):
    with pytest.raises(ValidationError):
        CatalogPrepare.model_validate({**request(root, "migrate"), **extra})


def test_api_auth_loopback_closed_request_and_documented_shape(root, service, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "catalog-test")
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    headers = {"X-API-Key": "catalog-test"}
    client = TestClient(api.app, client=("127.0.0.1", 50000))
    assert client.get("/api/v1/factory-catalog", params={"folder": str(root)}).status_code == 401
    preview = client.post("/api/v1/factory-catalog/prepare", json=request(root, "migrate"), headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["contract_version"] == 1
    assert preview.json()["can_execute"]
    bad = client.post("/api/v1/factory-catalog/prepare",
                      json={**request(root, "migrate"), "secret": "do-not-echo"}, headers=headers)
    assert bad.status_code == 422
    assert "do-not-echo" not in bad.text
    remote = TestClient(api.app, client=("192.0.2.8", 50000))
    assert remote.post("/api/v1/factory-catalog/prepare", json=request(root, "migrate"), headers=headers).status_code == 403


def test_cross_process_lock_is_exclusive_and_released_by_os(root):
    script = ("from pathlib import Path; import sys,time; from src.catalog_storage import catalog_lock\n"
              "with catalog_lock(Path(sys.argv[1])):\n print('locked',flush=True); time.sleep(2)\n")
    child = subprocess.Popen([sys.executable, "-c", script, str(root)], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(CatalogError, match="configuration lock"):
            with catalog_lock(root, timeout=.1):
                pytest.fail("Concurrent writer acquired the catalog lock")
        child.wait(timeout=10)
        assert child.returncode == 0
        with catalog_lock(root, timeout=.1):
            pass
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def test_projection_failure_does_not_change_authoritative_revision(root, service, monkeypatch):
    factory = migrate(root, service)
    revision = catalog.source_revision(root)
    preview = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-"), OWNER)
    real_write = catalog.atomic_write
    def failed(path, data):
        if path == root / catalog.CATALOG_PATH:
            raise OSError("simulated atomic commit failure")
        return real_write(path, data)
    monkeypatch.setattr(catalog, "atomic_write", failed)
    with pytest.raises(OSError):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert catalog.source_revision(root) == revision
    assert len(service.list(str(root))["factories"]) == 1


def test_scope_binding_change_invalidates_preview(root, service):
    factory = migrate(root, service)
    preview = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-"), OWNER)
    binding = root / "config-wizard" / "factories" / factory["key"] / "orchestrators" / "gha.json"
    binding.parent.mkdir(parents=True)
    binding.write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(CatalogError, match="revision changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)


def test_same_project_number_can_exist_in_another_physical_scale_set(root, service):
    factory = migrate(root, service)
    preview = service.prepare(request(root, "create-scale-set", factory_id=factory["id"], scale_sets=[scale()]), OWNER)
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    document = catalog.load_document(root)
    target = document["factories"][0]
    new_scale = next(ss for ss in target["scale_sets"] if ss["suffix"] == "002")
    project = copy.deepcopy(target["projects"][0])
    project.update(id=str(uuid4()), key="project-001-second-scope",
                   placements=[{"environment": "dev", "scale_set_id": new_scale["id"]}])
    target["projects"].append(project)
    document["configurations"][target["id"]]["projects"][project["id"]] = {}
    catalog.validate_document(document)


def test_capacity_uses_actual_common_subnet_placement():
    network = {"vnet_cidr": "172.16.0.0/18", "max_projects": 7,
               "common_subnets": {"common": "172.16.0.0/26", "scoring": "172.16.0.64/26",
                                  "powerbi": "172.16.0.128/26", "bastion": "172.16.48.192/26"}}
    assert catalog.allocator_capacity(network) < 7


def test_legacy_variables_preserve_per_environment_tenants(root, monkeypatch):
    state = read_json(root / "config-wizard" / "factory_state.json")
    stage = {**state, "tenantId": "33333333-3333-3333-3333-333333333333",
             "test_sub_id": "44444444-4444-4444-4444-444444444444", "prod_sub_id": "44444444-4444-4444-4444-444444444444"}
    variables = root / "variables.json"
    variables.write_text(json.dumps({"dev": state, "stage_prod": stage}), encoding="utf-8")
    project = root / "config-wizard" / "project-001" / "project_state.json"
    project.write_text(json.dumps({**state, "test_sub_id": stage["test_sub_id"], "prod_sub_id": stage["prod_sub_id"]}), encoding="utf-8")
    monkeypatch.setattr(catalog.factory_configuration, "_load_source", lambda _: (root, state, variables))
    document = catalog.legacy_document(root)
    scales = {scale["environment"]: scale for scale in document["factories"][0]["scale_sets"]}
    assert scales["dev"]["tenant_id"] == TENANT
    assert scales["stage"]["tenant_id"] == stage["tenantId"]


def test_clone_does_not_rewrite_edited_source_projections(root, service):
    factory = migrate(root, service)
    source = root / "config-wizard" / "factories" / factory["key"] / "factory_state.json"
    source.write_text('{"human-edit":"preserve this non-authoritative projection"}', encoding="utf-8")
    before = source.read_bytes()
    preview = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-"), OWNER)
    assert preview["can_execute"]
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert source.read_bytes() == before
