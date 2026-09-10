import copy
import errno
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, factory_configuration as configuration, wizard
from src.operations import LocalFactoryDiscovery


REGION = "westeurope"
GUID = "12345678-1234-1234-1234-123456789abc"
OTHER_GUID = "23456789-1234-1234-1234-123456789abc"
HEADERS = {"X-API-Key": "configuration-tests"}
PREPARE = "/api/v1/factories/configuration/prepare"
SAVE = "/api/v1/factories/configuration/save"


@pytest.fixture(autouse=True)
def no_global_writes(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Configuration workflows must not use global settings or legacy snapshots")

    monkeypatch.setattr(wizard, "_save_app_settings", forbidden)
    monkeypatch.setattr(wizard, "_record_recent_project", forbidden)
    monkeypatch.setattr(wizard, "_snapshot_dir", forbidden)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, HEADERS["X-API-Key"])
    with TestClient(api.app) as result:
        yield result


def valid_state(kind="factory", source=None, suffix="-002"):
    state = configuration.prepare_configuration(kind, REGION, source)["state"]
    state.update({
        "admin_aifactoryPrefixRG": state["admin_aifactoryPrefixRG"] if kind == "scale-set" else "unit-",
        "admin_aifactorySuffixRG": suffix,
        "admin_locationSuffix": "weu",
        "tenantId": GUID, "dev_sub_id": GUID, "test_sub_id": GUID, "prod_sub_id": GUID,
    })
    return state


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    state = copy.deepcopy(wizard.DEFAULT_STATE)
    state.update({
        "orchestrator": "gha", "_save_folder": str(root), "_also_update_git": True,
        "admin_aifactoryPrefixRG": "original-", "admin_aifactorySuffixRG": "-001",
        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "tenantId": GUID, "dev_sub_id": GUID, "test_sub_id": GUID, "prod_sub_id": GUID,
        "common_vnet_cidr": "10.22.XX.0/18", "enableRedisCache": "true",
        "common_subnet_cidr": "10.22.XX.0/26",
        "common_subnet_scoring_cidr": "10.22.XX.64/26",
        "common_pbi_subnet_cidr": "10.22.XX.128/26",
        "common_bastion_subnet_cidr": "10.22.XX.192/26",
        "acr_SKU": "Standard", "project_number_000": "097",
        "projectPrefix": "my-project-", "github_new_repo": "original/repository",
        "deleteAllServicesForProject": "true", "deleteAllForProject": "true",
        "foundryApiManagementResourceId": "/subscriptions/old/resourceGroups/old/providers/apim/old",
        "byoAseFullResourceId": "/subscriptions/old/ase/old",
        "technical_admins_ad_object_id": GUID,
        "dev_service_connection": "original-pipeline-connection",
        "dev_admin_bicep_kv_fw": "original-seeding-vault",
        "network_mode": "private",
        **wizard.NETWORK_MODE_FLAGS["private"],
        "unknown_secret": "do-not-copy",
    })
    path = root / configuration.FACTORY_STATE
    path.parent.mkdir()
    path.write_text(json.dumps(state), encoding="utf-8")
    (root / "variables.json").write_text('{"dev": {"unchanged": true}}', encoding="utf-8")
    project = path.parent / "project-097" / "project_state.json"
    project.parent.mkdir()
    project.write_text(json.dumps(state), encoding="utf-8")
    (root / "pipeline.yaml").write_text("do not touch", encoding="utf-8")
    return root


def files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_factory_prepare_is_pure_defaults(monkeypatch):
    original = copy.deepcopy(wizard.DEFAULT_STATE)
    monkeypatch.setattr(configuration, "_load_source", Mock(side_effect=AssertionError("read source")))
    result = configuration.prepare_configuration("factory", REGION, "ignored-source")
    assert result["state"]["admin_location"] == REGION
    assert result["state"]["admin_locationSuffix"] == "weu"
    for key in ("admin_aifactoryPrefixRG", "admin_aifactorySuffixRG",
                "tenantId", "dev_sub_id", "test_sub_id", "prod_sub_id", "_save_folder"):
        assert result["state"][key] == ""
    assert result["state"]["project_number_000"] == wizard.DEFAULT_STATE["project_number_000"]
    assert result["state"]["_also_update_git"] is False
    assert result["state"]["enableDeleteForDisabledResources"] == "false"
    assert result["field_keys"][:len(configuration.ESSENTIAL_KEYS)] == list(configuration.ESSENTIAL_KEYS)
    assert len(set(result["field_keys"])) == len(result["field_keys"])
    assert set(result["field_keys"]) <= set(wizard.DEFAULT_STATE)
    assert set(configuration.NETWORK_KEYS) <= set(result["field_keys"])
    result["state"]["common_vnet_cidr"] = "changed"
    assert wizard.DEFAULT_STATE == original


@pytest.mark.parametrize("topology", ["", "standalone", "own-hub", "external-hub"])
def test_hub_topology_is_internal_metadata_persisted_in_all_snapshot_scopes(tmp_path, topology):
    destination = tmp_path / "factory"
    state = valid_state()
    state["_hub_topology"] = topology
    result = configuration.save_configuration("factory", REGION, str(destination), state)
    assert configuration._schema_state({"_hub_topology": topology})["_hub_topology"] == topology
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8"))["_hub_topology"] == topology
    loaded = {}
    wizard._import_json_to_state(result["path"], loaded)
    assert loaded["_hub_topology"] == topology
    project = Path(wizard._save_project_snapshot(result["state"]))
    assert wizard._load_project_state(str(project), str(destination))["_hub_topology"] == topology
    scaleset = destination / "config-wizard" / "scalesets" / "scaleset_002.json"
    assert json.loads(scaleset.read_text(encoding="utf-8"))["_hub_topology"] == topology
    assert "_hub_topology" not in (destination / "variables.json").read_text(encoding="utf-8")
    assert "_hub_topology" not in "".join(wizard._render_azure_devops(state))
    assert "_hub_topology" not in "".join(wizard._render_github_actions(state))
    assert "_hub_topology" not in wizard.ENV_MAP
    assert "_hub_topology" not in wizard.YAML_MAP


def test_hub_topology_rejects_unknown_values():
    assert wizard.DEFAULT_STATE["_hub_topology"] == ""
    with pytest.raises(configuration.ConfigurationError, match="_hub_topology"):
        configuration._schema_state({"_hub_topology": "create-something"})


@pytest.mark.parametrize("metadata", [False, True])
def test_standalone_json_source_selects_gha_without_sibling_env(tmp_path, metadata):
    state = valid_state()
    state.update({"orchestrator": "gha", "github_new_repo": "example/repository"})
    document = wizard._render_variables_json(state)
    if not metadata:
        document.pop("_wizard")
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    # Source setup deliberately allows optional <todo> placeholders.
    assert configuration._load_source(str(tmp_path))[1]["orchestrator"] == "gha"
    assert LocalFactoryDiscovery().discover(str(tmp_path))["orchestrator"] == "gha"


def test_discovery_reports_primary_region_independently_of_other_snapshots(source):
    scalesets = source / "config-wizard" / "scalesets"
    scalesets.mkdir()
    (scalesets / "scaleset_002.json").write_text(
        json.dumps({"admin_location": "eastus2", "admin_aifactorySuffixRG": "-002"}),
        encoding="utf-8",
    )
    result = LocalFactoryDiscovery().discover(str(source))
    assert result["primary_region"] == "swedencentral"
    assert "eastus2" in result["active_regions"]


def test_new_factory_uses_current_python_template_defaults(monkeypatch):
    monkeypatch.setattr(wizard, "_load_template_defaults", lambda: {"enableRedisCache": "true"})
    prepared = configuration.prepare_configuration("factory", REGION)
    assert prepared["state"]["enableRedisCache"] == "true"


@pytest.mark.parametrize("kind", ["clone", "scale-set"])
def test_prepare_loads_authoritative_configuration_and_clears_unsafe_values(source, kind):
    before = files(source)
    result = configuration.prepare_configuration(kind, REGION, str(source))
    state = result["state"]
    assert state["orchestrator"] == "gha"
    assert state["admin_aifactoryPrefixRG"] == "original-"
    assert state["enableRedisCache"] == "true"
    assert state["acr_SKU"] == "Standard"
    assert state["common_vnet_cidr"] == "10.22.XX.0/18"
    assert state["network_mode"] == "private"
    assert state["admin_location"] == REGION
    assert state["admin_locationSuffix"] == "weu"
    assert state["admin_aifactorySuffixRG"] == ""
    assert state["tenantId"] == GUID
    assert state["foundryApiManagementResourceId"] == ""
    assert state["byoAseFullResourceId"] == ""
    assert state["dev_admin_bicep_kv_fw"] == ""
    assert state["technical_admins_ad_object_id"] == ""
    assert state["dev_service_connection"] == ""
    assert state["github_new_repo"] == ""
    assert state["_save_folder"] == ""
    assert state["_also_update_git"] is False
    assert state["deleteAllServicesForProject"] == state["deleteAllForProject"] == "false"
    assert "unknown_secret" not in state
    assert "network addresses" in result["message"]
    assert str(source / configuration.FACTORY_STATE) in result["message"]
    assert "primary region: swedencentral" in result["message"]
    assert f"Target region: {REGION}" in result["message"]
    assert files(source) == before


@pytest.mark.parametrize("kind", ["clone", "scale-set"])
def test_source_is_required_and_must_exist(tmp_path, kind):
    with pytest.raises(configuration.ConfigurationError, match="source_folder is required"):
        configuration.prepare_configuration(kind, REGION)
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.prepare_configuration(kind, REGION, str(tmp_path / "missing"))
    assert error.value.status_code == 404
    with pytest.raises(configuration.ConfigurationError, match="no usable factory"):
        configuration.prepare_configuration(kind, REGION, str(tmp_path))


def test_clone_rejects_same_primary_region_but_scaleset_allows_it(source):
    with pytest.raises(configuration.ConfigurationError, match="primary region"):
        configuration.prepare_configuration("clone", "swedencentral", str(source))
    assert configuration.prepare_configuration("scale-set", "swedencentral", str(source))["state"]["admin_location"] == "swedencentral"


@pytest.mark.parametrize("region", ["global", "moonbase", "West Europe", "WESTEUROPE", "", "../westeurope"])
def test_prepare_rejects_unknown_or_non_geographic_region(region):
    with pytest.raises(configuration.ConfigurationError, match="known Azure"):
        configuration.prepare_configuration("factory", region)


@pytest.mark.parametrize("content", ["{bad-json", "[]", "{}", '{"dev": []}'])
def test_malformed_source_never_silently_uses_defaults(tmp_path, content):
    (tmp_path / "variables.json").write_text(content, encoding="utf-8")
    with pytest.raises(configuration.ConfigurationError):
        configuration.prepare_configuration("clone", REGION, str(tmp_path))


@pytest.mark.parametrize("content", ["{bad-json", "[]", "{}", '{"admin_location": "swedencentral"}'])
def test_invalid_factory_state_never_falls_back_to_variables(source, content):
    (source / configuration.FACTORY_STATE).write_text(content, encoding="utf-8")
    with pytest.raises(configuration.ConfigurationError):
        configuration.prepare_configuration("clone", REGION, str(source))


@pytest.mark.parametrize("format_name", ["json", "yaml", "env"])
def test_startup_import_mapping_is_reused_for_existing_factory(tmp_path, format_name):
    root = tmp_path / "source"
    root.mkdir()
    state = valid_state()
    state.update({"admin_location": "swedencentral", "admin_aifactorySuffixRG": "-001"})
    if format_name == "json":
        wizard._save_variables_json(state, str(root))
    elif format_name == "yaml":
        path = root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("".join(wizard._render_azure_devops(state)), encoding="utf-8")
    else:
        (tmp_path / ".env").write_text("".join(wizard._render_github_actions(state)), encoding="utf-8")
    result = configuration.prepare_configuration("clone", REGION, str(root))
    assert result["state"]["admin_aifactoryPrefixRG"] == "unit-"
    assert result["state"]["orchestrator"] == ("gha" if format_name == "env" else "ado")
    assert result["state"]["tenantId"] == GUID


@pytest.mark.parametrize("empty_exists", [True, False])
def test_new_factory_saves_full_state_variables_first_scaleset_without_project(tmp_path, empty_exists):
    destination = tmp_path / "new-factory"
    if empty_exists:
        destination.mkdir()
    state = valid_state()
    state["orchestrator"] = "gha"
    state["network_mode"] = "private"
    result = configuration.save_configuration("factory", REGION, str(destination), state)
    assert result["path"] == str(destination / configuration.FACTORY_STATE)
    persisted = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert persisted == result["state"]
    assert persisted["_save_folder"] == str(destination)
    assert persisted["_also_update_git"] is False
    assert "project-001" not in "\n".join(files(destination))
    assert len(files(destination)) == 3
    scale_set = destination / "config-wizard" / "scalesets" / "scaleset_002.json"
    snapshot = json.loads(scale_set.read_text(encoding="utf-8"))
    assert snapshot["admin_location"] == REGION
    assert snapshot["_save_folder"] == str(destination)
    assert snapshot["network_mode"] == "private"
    assert persisted["enablePublicGenAIAccess"] == "false"
    variables = json.loads((destination / "variables.json").read_text(encoding="utf-8"))
    assert variables == wizard._render_variables_json(persisted)
    for section in ("dev", "stage_prod"):
        assert variables[section]["admin_location"] == REGION
        assert variables[section]["admin_locationSuffix"] == "weu"
    loaded = {"stale_editor_value": "must disappear"}
    path, route = wizard._startup_import_candidate(str(destination), loaded)
    assert route == "gha"
    assert wizard._import_json_to_state(path, loaded) > 0
    assert loaded == persisted
    discovered = LocalFactoryDiscovery().discover(str(destination))
    assert discovered["project_numbers"] == discovered["environment_cards"] == []
    assert discovered["project_snapshots"] == []
    assert discovered["active_regions"] == [REGION]
    assert discovered["orchestrator"] == "gha"
    assert discovered["name"] == "unit-002"
    assert discovered["subscription_ids"] == [GUID]
    assert not list(tmp_path.glob(".*.configuration-*"))


def test_clone_save_preserves_settings_and_source_project_repo_pipeline_files(source, tmp_path):
    before = files(source)
    destination = tmp_path / "clone"
    state = valid_state("clone", str(source))
    result = configuration.save_configuration("clone", REGION, str(destination), state, str(source))
    assert result["state"]["enableRedisCache"] == "true"
    assert result["state"]["common_vnet_cidr"] == "10.22.XX.0/18"
    assert files(source) == before
    assert len(files(destination)) == 3
    assert not (destination / "pipeline.yaml").exists()
    assert not (destination / "config-wizard" / "project-097").exists()
    assert LocalFactoryDiscovery().discover(str(destination))["project_numbers"] == []


def test_scaleset_save_writes_only_exclusive_snapshot_and_discovery_sees_region(source):
    before = files(source)
    state = valid_state("scale-set", str(source))
    state["prod_sub_id"] = OTHER_GUID
    result = configuration.save_configuration("scale-set", REGION, str(source), state, str(source))
    relative = str(Path("config-wizard") / "scalesets" / "scaleset_002.json")
    after = files(source)
    assert set(after) - set(before) == {relative}
    assert {key: after[key] for key in before} == before
    assert result["path"] == str(source / relative)
    snapshot = json.loads(after[relative])
    assert "enableRedisCache" not in snapshot
    assert snapshot["network_mode"] == "private"
    assert snapshot["admin_locationSuffix"] == "weu"
    found = LocalFactoryDiscovery().discover(str(source))
    assert found["active_regions"] == ["swedencentral", REGION]
    assert found["subscription_ids"] == [GUID]  # Saved alternate scale sets do not broaden active Azure reads.
    assert found["project_numbers"] == ["097"]
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration("scale-set", REGION, str(source), state, str(source))
    assert error.value.status_code == 409
    assert files(source) == after


@pytest.mark.parametrize("kind", ["clone", "scale-set"])
def test_suffix_must_be_unique_against_source_primary_and_snapshots(source, tmp_path, kind):
    state = valid_state(kind, str(source), suffix="001")
    destination = source if kind == "scale-set" else tmp_path / "clone"
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration(kind, REGION, str(destination), state, str(source))
    assert error.value.status_code == 409
    assert not (tmp_path / "clone").exists()


@pytest.mark.parametrize("key,value", [
    ("orchestrator", "other"), ("admin_aifactoryPrefixRG", ""),
    ("admin_aifactoryPrefixRG", "../escape"), ("admin_aifactorySuffixRG", ""),
    ("admin_aifactorySuffixRG", "..\\outside"), ("admin_aifactorySuffixRG", "-bad/name"),
    ("admin_aifactorySuffixRG", "bad:name"), ("admin_aifactorySuffixRG", "--"),
    ("admin_locationSuffix", ""), ("admin_locationSuffix", "../sdc"),
    ("admin_location", "swedencentral"), ("tenantId", "not-guid"),
    ("dev_sub_id", ""), ("test_sub_id", "<todo>"), ("prod_sub_id", "bad"),
    ("prod_sub_id", "00000000-0000-0000-0000-000000000000"),
    ("network_mode", "invalid"), ("common_vnet_cidr", {"invalid": "type"}),
])
def test_save_validates_identity_and_types_before_writing(tmp_path, key, value):
    state = valid_state()
    state[key] = value
    with pytest.raises(configuration.ConfigurationError):
        configuration.save_configuration("factory", REGION, str(tmp_path / "new"), state)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("destination", ["relative", "..\\escape", "C:\\new\\..\\escape", "C:\\new\\bad:name", "C:\\new\\CON"])
def test_destination_rejects_unsafe_paths(destination):
    with pytest.raises(configuration.ConfigurationError):
        configuration.save_configuration("factory", REGION, destination, valid_state())


def test_nonempty_folder_and_file_destinations_are_preserved(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "important.txt"
    marker.write_text("important", encoding="utf-8")
    for path in (destination, marker):
        with pytest.raises(configuration.ConfigurationError) as error:
            configuration.save_configuration("factory", REGION, str(path), valid_state())
        assert error.value.status_code == 409
    assert files(destination) == {"important.txt": b"important"}


def test_factory_duplicate_save_rejected(tmp_path):
    destination = tmp_path / "new"
    state = valid_state()
    configuration.save_configuration("factory", REGION, str(destination), state)
    before = files(destination)
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration("factory", REGION, str(destination), state)
    assert error.value.status_code == 409
    assert files(destination) == before


def test_clone_same_folder_and_scaleset_other_folder_rejected(source, tmp_path):
    before = files(source)
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration("clone", REGION, str(source), valid_state("clone", str(source)), str(source))
    assert error.value.status_code == 409
    with pytest.raises(configuration.ConfigurationError, match="exactly match"):
        configuration.save_configuration("scale-set", REGION, str(tmp_path / "other"), valid_state("scale-set", str(source)), str(source))
    assert files(source) == before
    assert not (tmp_path / "other").exists()


@pytest.mark.parametrize("empty_exists", [True, False])
def test_staging_failure_leaves_destination_unchanged_and_cleans_stage(monkeypatch, tmp_path, empty_exists):
    destination = tmp_path / "new"
    if empty_exists:
        destination.mkdir()
    monkeypatch.setattr(wizard, "_save_variables_json", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        configuration.save_configuration("factory", REGION, str(destination), valid_state())
    assert destination.exists() is empty_exists
    if empty_exists:
        assert list(destination.iterdir()) == []
    assert not list(tmp_path.glob(".*.configuration-*"))


def test_create_only_snapshot_helper_does_not_clobber(source):
    state = valid_state("scale-set", str(source))
    state["_save_folder"] = str(source)
    path = Path(wizard._save_scaleset_snapshot(state, create_only=True))
    before = path.read_bytes()
    state["admin_location"] = "eastus"
    with pytest.raises(FileExistsError):
        wizard._save_scaleset_snapshot(state, create_only=True)
    assert path.read_bytes() == before
    wizard._save_scaleset_snapshot(state)
    assert json.loads(path.read_text(encoding="utf-8"))["admin_location"] == "eastus"


@pytest.mark.parametrize("endpoint", [PREPARE, SAVE])
def test_endpoints_are_secured_and_documented(client, monkeypatch, endpoint):
    payload = {"kind": "factory", "target_region": REGION}
    assert client.post(endpoint, json=payload).status_code == 401
    assert client.post(endpoint, json=payload, headers={"X-API-Key": "wrong"}).status_code == 401
    monkeypatch.delenv(api.API_KEY_ENV)
    assert client.post(endpoint, json=payload, headers=HEADERS).status_code == 503
    operation = client.get("/openapi.json").json()["paths"][endpoint]["post"]
    assert operation["security"] == [{"APIKeyHeader": []}]


def test_api_prepare_save_and_startup_load_roundtrip(client, tmp_path):
    prepared = client.post(PREPARE, headers=HEADERS, json={"kind": "factory", "target_region": REGION})
    assert prepared.status_code == 200
    assert prepared.json()["field_keys"] == list(configuration.FIELD_KEYS)
    destination = tmp_path / "factory"
    payload = {"kind": "factory", "target_region": REGION, "destination_folder": str(destination), "state": valid_state()}
    saved = client.post(SAVE, headers=HEADERS, json=payload)
    assert saved.status_code == 200, saved.text
    loaded = client.post("/api/v1/startup/load", headers=HEADERS, json={
        "aifactory_folder": str(destination), "project_number": "999",
    })
    assert loaded.status_code == 200
    assert loaded.json()["state"] == saved.json()["state"]
    assert client.post(SAVE, headers=HEADERS, json=payload).status_code == 409


@pytest.mark.parametrize("payload,status", [
    ({"kind": "invalid", "target_region": REGION}, 422),
    ({"kind": "factory", "target_region": "global"}, 422),
    ({"kind": "clone", "target_region": REGION}, 422),
])
def test_api_prepare_validation(client, payload, status):
    assert client.post(PREPARE, headers=HEADERS, json=payload).status_code == status


def test_api_missing_and_malformed_source_have_clear_status(client, tmp_path):
    payload = {"kind": "clone", "target_region": REGION, "source_folder": str(tmp_path / "missing")}
    assert client.post(PREPARE, headers=HEADERS, json=payload).status_code == 404
    (tmp_path / "variables.json").write_text("{broken", encoding="utf-8")
    payload["source_folder"] = str(tmp_path)
    assert client.post(PREPARE, headers=HEADERS, json=payload).status_code == 422


def test_tkinter_startup_selection_reuses_full_state_import(tmp_path):
    destination = tmp_path / "factory"
    saved = configuration.save_configuration("factory", REGION, str(destination), valid_state())
    state = {"unrelated_unsaved_editor_field": "old"}
    page = SimpleNamespace(
        state=state, _folder_var=Mock(), _import_path_var=Mock(),
        _do_import=lambda path: wizard._import_json_to_state(path, state),
    )
    page._folder_var.get.return_value = ""
    wizard.PageOrchestratorNetwork._import_from_startup_folder(page, str(destination))
    assert state == saved["state"]


def test_new_factory_lists_no_legacy_projects_or_scalesets(client, tmp_path):
    destination = tmp_path / "factory"
    configuration.save_configuration("factory", REGION, str(destination), valid_state())
    payload = {"aifactory_folder": str(destination)}
    projects = client.post("/api/v1/projects", headers=HEADERS, json=payload)
    assert projects.json() == {"projects": []}
    scale_sets = client.post("/api/v1/scale-sets", headers=HEADERS, json=payload)
    assert [item["scale_set_id"] for item in scale_sets.json()["scale_sets"]] == ["002"]


def test_explicit_reviewed_network_references_can_be_saved(source):
    state = valid_state("scale-set", str(source))
    state.update({
        "privDnsSubscription_param": OTHER_GUID,
        "privDnsResourceGroup_param": "reviewed-dns-group",
        "dev_service_connection": "new-reviewed-connection",
        "_save_folder": "ignored", "_also_update_git": True,
        "deleteAllServicesForProject": "true",
    })
    result = configuration.save_configuration("scale-set", REGION, str(source), state, str(source))
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["privDnsSubscription_param"] == OTHER_GUID
    assert snapshot["privDnsResourceGroup_param"] == "reviewed-dns-group"
    assert snapshot["dev_service_connection"] == "new-reviewed-connection"
    assert result["state"]["_also_update_git"] is False
    assert result["state"]["deleteAllServicesForProject"] == "false"
    assert result["state"]["_save_folder"] == str(source)


def test_factory_prepare_api_ignores_unsaved_editor_state(client):
    response = client.post(PREPARE, headers=HEADERS, json={
        "kind": "factory", "target_region": REGION,
        "state": {"project_number_000": "777", "github_new_repo": "original/repo"},
    })
    assert response.status_code == 200
    assert response.json()["state"]["project_number_000"] == wizard.DEFAULT_STATE["project_number_000"]
    assert response.json()["state"]["github_new_repo"] == ""


def test_concurrent_destination_write_is_not_lost(monkeypatch, tmp_path):
    destination = tmp_path / "new"
    original_save = wizard._save_variables_json

    def concurrent_writer(*args, **kwargs):
        result = original_save(*args, **kwargs)
        destination.mkdir()
        (destination / "user-data.txt").write_text("keep me", encoding="utf-8")
        return result

    monkeypatch.setattr(wizard, "_save_variables_json", concurrent_writer)
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration("factory", REGION, str(destination), valid_state())
    assert error.value.status_code == 409
    assert files(destination) == {"user-data.txt": b"keep me"}
    assert not list(tmp_path.glob(".*.configuration-*"))


def test_concurrent_duplicate_scaleset_is_not_clobbered(monkeypatch, source):
    original_check = configuration._unique_suffix
    target = source / "config-wizard" / "scalesets" / "scaleset_002.json"

    def concurrent_writer(*args, **kwargs):
        original_check(*args, **kwargs)
        target.parent.mkdir()
        target.write_text("concurrent config", encoding="utf-8")

    monkeypatch.setattr(configuration, "_unique_suffix", concurrent_writer)
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration("scale-set", REGION, str(source), valid_state("scale-set", str(source)), str(source))
    assert error.value.status_code == 409
    assert target.read_text(encoding="utf-8") == "concurrent config"


def test_destination_becoming_nonempty_during_publish_returns_conflict(client, monkeypatch, tmp_path):
    destination = tmp_path / "new"
    destination.mkdir()
    original_rmdir = Path.rmdir

    def nonempty(path):
        if path == destination:
            raise OSError(errno.ENOTEMPTY, "concurrent write", str(path))
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", nonempty)
    response = client.post(SAVE, headers=HEADERS, json={
        "kind": "factory", "target_region": REGION,
        "destination_folder": str(destination), "state": valid_state(),
    })
    assert response.status_code == 409
    assert destination.is_dir()
    assert not list(tmp_path.glob(".*.configuration-*"))


def test_source_permissions_failure_is_not_a_server_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(configuration, "_load_source", Mock(side_effect=PermissionError("denied")))
    response = client.post(PREPARE, headers=HEADERS, json={
        "kind": "clone", "target_region": REGION, "source_folder": str(tmp_path),
    })
    assert response.status_code == 400


def test_invalid_utf8_source_is_validation_error(client, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (tmp_path / ".env").write_bytes(b"\xff")
    response = client.post(PREPARE, headers=HEADERS, json={
        "kind": "clone", "target_region": REGION, "source_folder": str(root),
    })
    assert response.status_code == 422


def test_snapshot_content_identity_is_also_checked(source, tmp_path):
    snapshot = source / "config-wizard" / "scalesets" / "scaleset_other.json"
    snapshot.parent.mkdir()
    snapshot.write_text('{"admin_aifactorySuffixRG":"-002"}', encoding="utf-8")
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.save_configuration("clone", REGION, str(tmp_path / "clone"), valid_state("clone", str(source)), str(source))
    assert error.value.status_code == 409


def test_links_are_not_followed_for_new_snapshot_writes(source, monkeypatch):
    target = source / "config-wizard" / "scalesets"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    before = files(source)
    with pytest.raises(configuration.ConfigurationError, match="symbolic links"):
        configuration.save_configuration("scale-set", REGION, str(source), valid_state("scale-set", str(source)), str(source))
    assert files(source) == before


def test_failed_exclusive_snapshot_does_not_leave_partial_configuration(source, monkeypatch):
    state = valid_state("scale-set", str(source))
    state["_save_folder"] = str(source)
    target = source / "config-wizard" / "scalesets" / "scaleset_002.json"
    monkeypatch.setattr(wizard._json, "dump", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        wizard._save_scaleset_snapshot(state, create_only=True)
    assert not target.exists()


def test_current_root_variables_override_stale_project_and_template_values(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    current = valid_state()
    current.update({
        "admin_location": "swedencentral", "admin_aifactoryPrefixRG": "current-",
        "admin_aifactorySuffixRG": "-015", "tenantId": OTHER_GUID,
        "dev_sub_id": OTHER_GUID, "enableRedisCache": "true",
        "common_vnet_cidr": "10.88.XX.0/18",
        "common_subnet_cidr": "10.88.XX.0/26",
        "common_subnet_scoring_cidr": "10.88.XX.64/26",
        "common_pbi_subnet_cidr": "10.88.XX.128/26",
        "common_bastion_subnet_cidr": "10.88.XX.192/26",
    })
    wizard._save_variables_json(current, str(root))
    stale = root / "config-wizard" / "project-001" / "project_state.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps(wizard.DEFAULT_STATE), encoding="utf-8")
    before = files(root)
    prepared = configuration.prepare_configuration("clone", REGION, str(root))
    for key in ("admin_aifactoryPrefixRG", "tenantId", "dev_sub_id",
                "enableRedisCache", "common_vnet_cidr"):
        assert prepared["state"][key] == current[key]
    assert str(root / "variables.json") in prepared["message"]
    assert files(root) == before


def test_scaleset_fields_exclude_existing_factory_identity(source):
    result = configuration.prepare_configuration("scale-set", REGION, str(source))
    assert "orchestrator" not in result["field_keys"]
    assert "admin_aifactoryPrefixRG" not in result["field_keys"]
    assert "admin_aifactorySuffixRG" in result["field_keys"]
    assert result["state"]["orchestrator"] == "gha"
    assert result["state"]["admin_aifactoryPrefixRG"] == "original-"
    assert result["state"]["admin_aifactorySuffixRG"] == ""


@pytest.mark.parametrize("key,value", [
    ("admin_aifactoryPrefixRG", "another-factory-"), ("orchestrator", "ado"),
])
def test_scaleset_cannot_change_factory_identity(client, source, key, value):
    state = valid_state("scale-set", str(source))
    state[key] = value
    before = files(source)
    response = client.post(SAVE, headers=HEADERS, json={
        "kind": "scale-set", "target_region": REGION, "source_folder": str(source),
        "destination_folder": str(source), "state": state,
    })
    assert response.status_code == 422
    assert key in response.json()["detail"]
    assert files(source) == before


def test_clone_may_choose_its_own_prefix_and_orchestrator(source, tmp_path):
    state = valid_state("clone", str(source))
    state.update({"orchestrator": "ado", "admin_aifactoryPrefixRG": "independent-"})
    result = configuration.save_configuration(
        "clone", REGION, str(tmp_path / "clone"), state, str(source)
    )
    assert result["state"]["orchestrator"] == "ado"
    assert result["state"]["admin_aifactoryPrefixRG"] == "independent-"
