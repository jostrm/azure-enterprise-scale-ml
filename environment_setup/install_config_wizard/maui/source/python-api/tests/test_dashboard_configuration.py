import copy
import json
import re
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from fastapi.testclient import TestClient

from src import api, factory_configuration as configuration, wizard
from src.operations import LocalFactoryDiscovery, OperationsService, OperationsStore


KEY = "aifactory-dash-01"
ENV_KEY = "AIFACTORY_DASHBOARD_URL"
URL = "https://portal.azure.com/#@example.onmicrosoft.com/dashboard/private/11111111-1111-4111-8111-111111111111"
SHARED_URL = "https://portal.azure.com/#dashboard/arm/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/example/providers/Microsoft.Portal/dashboards/example"
OTHER_URL = "https://portal.azure.com/#dashboard/private/22222222-2222-4222-8222-222222222222"
GUID = "11111111-1111-4111-8111-111111111111"
ROOT = Path(__file__).parents[1]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def state_for(folder, dashboard=URL):
    state = copy.deepcopy(wizard.DEFAULT_STATE)
    state.update({
        KEY: dashboard, "_save_folder": str(folder),
        "admin_aifactoryPrefixRG": "example-", "admin_aifactorySuffixRG": "-001",
        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "tenantId": GUID, "dev_sub_id": GUID, "test_sub_id": GUID, "prod_sub_id": GUID,
        "project_number_000": "017", "enableRedisCache": "true",
    })
    return state


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "dashboard-tests")
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda: pytest.fail("Global snapshot access"))
    with TestClient(api.app, headers={"X-API-Key": "dashboard-tests"}) as result:
        yield result


def test_dashboard_defaults_schema_and_preparation(client, monkeypatch):
    assert wizard.DASHBOARD_KEY == KEY
    assert wizard.DEFAULT_STATE[KEY] == ""
    assert wizard.YAML_MAP[KEY] == f"variables.{KEY}"
    assert wizard.ENV_MAP[KEY] == ENV_KEY
    assert KEY in wizard.SCALESET_KEYS
    assert KEY in configuration.FIELD_KEYS
    assert configuration._schema_state({KEY: URL})[KEY] == URL
    schema = client.get("/api/v1/schema").json()
    assert schema["defaults"][KEY] == ""
    assert schema["mappings"]["yaml"][KEY] == f"variables.{KEY}"
    assert schema["mappings"]["env"][KEY] == ENV_KEY
    assert KEY in schema["sections"]["scale_set_variables"]
    assert "never deploys" in wizard.HELP_TEXT[KEY]
    monkeypatch.setattr(wizard, "_load_template_defaults", lambda: {KEY: URL})
    assert configuration.prepare_configuration("factory", "westeurope")["state"][KEY] == ""


@pytest.mark.parametrize("dashboard", ["", URL, SHARED_URL])
@pytest.mark.parametrize("format_name", ["yaml", "json", "env"])
def test_dashboard_roundtrip_preserves_exact_key_and_url_fragment(tmp_path, format_name, dashboard):
    state = state_for(tmp_path, dashboard)
    if format_name == "yaml":
        path = tmp_path / "variables.yaml"
        wizard.save_azure_devops(state, str(path))
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))["variables"]
        assert parsed[KEY] == dashboard
        loader = wizard._import_yaml_to_state
    elif format_name == "env":
        path = tmp_path / ".env"
        wizard.save_github_actions(state, str(path))
        assert f'{ENV_KEY}="{dashboard}"' in path.read_text(encoding="utf-8")
        loader = wizard._import_env_to_state
    else:
        path = Path(wizard._save_variables_json(state, str(tmp_path)))
        loader = wizard._import_json_to_state
    loaded = {}
    assert loader(str(path), loaded) > 0
    assert loaded[KEY] == dashboard
    assert loaded["project_number_000"] == "017"
    assert loaded["enableRedisCache"] == "true"
    document = json.loads((tmp_path / "variables.json").read_text(encoding="utf-8"))
    for section in ("dev", "stage_prod"):
        assert document[section][KEY] == dashboard
        assert ENV_KEY not in document[section]
    baseline = wizard._render_variables_json({**state, KEY: ""})
    for section in document:
        assert {k: v for k, v in document[section].items() if k != KEY} == {
            k: v for k, v in baseline[section].items() if k != KEY
        }


@pytest.mark.parametrize("quoted", [False, True])
def test_yaml_import_preserves_fragment_with_inline_comment(tmp_path, quoted):
    path = tmp_path / "variables.yaml"
    value = json.dumps(URL) if quoted else URL
    path.write_text(f"variables:\n  {KEY}: {value} # existing dashboard\n", encoding="utf-8")
    state = {}
    assert wizard._import_yaml_to_state(str(path), state) == 1
    assert state[KEY] == URL


@pytest.mark.parametrize("full_value", [URL, "", None, 42])
def test_full_factory_dashboard_is_authoritative_even_when_empty(tmp_path, full_value):
    write_json(tmp_path / configuration.FACTORY_STATE, {KEY: full_value})
    write_json(tmp_path / "variables.json", {"dev": {KEY: OTHER_URL}})
    found = LocalFactoryDiscovery().discover(str(tmp_path))
    assert found["dashboard_url"] == (full_value if isinstance(full_value, str) else "")


@pytest.mark.parametrize("full_state", [False, True])
@pytest.mark.parametrize("section", ["dev", "stage_prod"])
def test_current_root_fallback_never_reads_historical_dashboard(tmp_path, full_state, section):
    if full_state:
        write_json(tmp_path / configuration.FACTORY_STATE, {})
    write_json(tmp_path / "variables.json", {
        "dev": {"project_number_000": "017"},
        section: {KEY: URL, "project_number_000": "017"},
    })
    write_json(tmp_path / "config-wizard" / "project-016" / "project_state.json", {KEY: OTHER_URL})
    write_json(tmp_path / "config-wizard" / "scalesets" / "scaleset_999.json", {KEY: OTHER_URL})
    assert LocalFactoryDiscovery().discover(str(tmp_path))["dashboard_url"] == URL
    write_json(tmp_path / "variables.json", {"dev": {"project_number_000": "017"}})
    assert LocalFactoryDiscovery().discover(str(tmp_path))["dashboard_url"] == ""


def test_dev_dashboard_precedes_stage_and_stale_current_yaml(tmp_path):
    write_json(tmp_path / "variables.json", {"dev": {KEY: URL}, "stage_prod": {KEY: OTHER_URL}})
    path = tmp_path / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(f'variables:\n  {KEY}: "{OTHER_URL}"\n', encoding="utf-8")
    assert wizard._current_dashboard_url(str(tmp_path)) == URL
    write_json(tmp_path / "variables.json", {"dev": {KEY: ""}})
    assert wizard._current_dashboard_url(str(tmp_path)) == ""


@pytest.mark.parametrize("format_name", ["yaml", "env", "root-env"])
def test_dashboard_uses_current_pipeline_when_no_root_json(tmp_path, format_name):
    folder = tmp_path / "aifactory"
    folder.mkdir()
    if format_name == "yaml":
        path = folder / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(f'variables:\n  {KEY}: "{URL}"\n', encoding="utf-8")
    else:
        path = (folder if format_name == "root-env" else tmp_path) / ".env"
        path.write_text(f'{ENV_KEY}="{URL}"\n', encoding="utf-8")
    write_json(folder / "config-wizard" / "project-016" / "project_state.json", {KEY: OTHER_URL})
    assert LocalFactoryDiscovery().discover(str(folder))["dashboard_url"] == URL


@pytest.mark.parametrize("dashboard", ["", URL])
def test_factory_and_scale_set_save_load_preserve_dashboard(tmp_path, client, dashboard):
    destination = tmp_path / "factory"
    state = state_for(destination, dashboard)
    result = configuration.save_configuration("factory", "swedencentral", str(destination), state)
    persisted = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert persisted[KEY] == dashboard
    loaded = {}
    wizard._import_json_to_state(result["path"], loaded)
    assert loaded[KEY] == dashboard
    response = client.post("/api/v1/scale-sets/load", json={
        "aifactory_folder": str(destination), "scale_set_id": "001",
    })
    assert response.status_code == 200, response.text
    assert response.json()["state"][KEY] == dashboard
    assert LocalFactoryDiscovery().discover(str(destination))["dashboard_url"] == dashboard
    for section in ("dev", "stage_prod"):
        assert json.loads((destination / "variables.json").read_text(encoding="utf-8"))[section][KEY] == dashboard


@pytest.mark.parametrize("dashboard", [URL, SHARED_URL])
@pytest.mark.parametrize("legacy_full", [False, True])
def test_clone_clears_dashboard_while_scale_set_retains_and_root_stays_unchanged(
    tmp_path, dashboard, legacy_full,
):
    source = tmp_path / "source"
    original = state_for(source, dashboard)
    if legacy_full:
        original.pop(KEY)
    factory_file = write_json(source / configuration.FACTORY_STATE, original)
    write_json(source / "variables.json", {"dev": {KEY: dashboard, "unchanged": True}})
    before = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    imported = {}
    wizard._import_json_to_state(str(factory_file), imported)
    assert imported[KEY] == dashboard

    for kind in ("clone", "scale-set"):
        prepared = configuration.prepare_configuration(kind, "westeurope", str(source))["state"]
        expected = "" if kind == "clone" else dashboard
        assert prepared[KEY] == expected
        assert prepared["enableRedisCache"] == "true"
        # Partial updates must not overwrite a retained link with the default.
        partial = {"admin_aifactorySuffixRG": "-002", "admin_locationSuffix": "weu"}
        destination = tmp_path / "clone" if kind == "clone" else source
        result = configuration.save_configuration(kind, "westeurope", str(destination), partial, str(source))
        assert result["state"][KEY] == expected
        assert json.loads(Path(result["path"]).read_text(encoding="utf-8"))[KEY] == expected
        if kind == "clone":
            assert LocalFactoryDiscovery().discover(str(destination))["dashboard_url"] == ""
    after = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    assert {key: after[key] for key in before} == before
    assert set(after) - set(before) == {str(Path("config-wizard") / "scalesets" / "scaleset_002.json")}


def test_project_hydration_uses_factory_link_without_overwriting_another_project(tmp_path):
    snapshot = write_json(
        tmp_path / "config-wizard" / "project-016" / "project_state.json",
        {"project_number_000": "016", KEY: OTHER_URL, "enableRedisCache": "true"},
    )
    write_json(tmp_path / "variables.json", {"dev": {KEY: URL, "project_number_000": "017", "enableRedisCache": "false"}})
    loaded = wizard._load_project_state(str(snapshot), str(tmp_path))
    assert loaded[KEY] == URL
    assert loaded["project_number_000"] == "016"
    assert loaded["enableRedisCache"] == "true"
    write_json(tmp_path / configuration.FACTORY_STATE, {KEY: "", "orchestrator": "ado"})
    assert wizard._load_project_state(str(snapshot), str(tmp_path))[KEY] == ""


def test_operations_overview_returns_read_only_dashboard_without_azure(tmp_path, client, monkeypatch):
    write_json(tmp_path / "variables.json", {"dev": {KEY: URL}})
    inventory = Mock()
    inventory.get_inventory.side_effect = AssertionError("Dashboard metadata must not call Azure")
    service = OperationsService(OperationsStore(tmp_path / "operations.db"), inventory=inventory)
    monkeypatch.setattr(api, "_operations_service", lambda: service)
    response = client.post("/api/v1/operations/overview", json={
        "aifactory_folder": str(tmp_path), "include_azure": False,
    })
    assert response.status_code == 200, response.text
    assert response.json()["factory"]["dashboard_url"] == URL
    inventory.get_inventory.assert_not_called()


@pytest.mark.parametrize("central", [False, True])
def test_yaml_json_and_env_templates_have_one_empty_dashboard_per_section(central):
    if central:
        root = ROOT.parent / "003_aifactory_sub" / "azure-enterprise-scale-ml" / "environment_setup" / "aifactory"
        if not root.exists():
            pytest.skip("Central purple repository is not checked out alongside the wizard")
        yaml_path = root / "bicep" / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines" / "variables" / "variables.yaml"
        env_path = root / "bicep" / "copy_to_local_settings" / "github-actions" / ".env.template"
    else:
        root = ROOT / "template-files"
        yaml_path = root / "variables.yaml"
        env_path = root / ".env"
    text = yaml_path.read_text(encoding="utf-8")
    assert len(re.findall(rf"^\s+{KEY}:", text, re.MULTILINE)) == 1
    assert yaml.safe_load(text)["variables"][KEY] == ""
    assert "Existing Azure Portal AI Factory dashboard URL; never deploys" in text
    text = env_path.read_text(encoding="utf-8")
    assert len(re.findall(rf"^{ENV_KEY}=", text, re.MULTILINE)) == 1
    assert f'{ENV_KEY}=""' in text
    assert "Existing Azure Portal AI Factory dashboard URL; never deploys" in text

    def unique_keys(pairs):
        keys = [key for key, _ in pairs]
        assert keys.count(KEY) <= 1
        return dict(pairs)

    document = json.loads((root / "variables.json").read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    assert set(document) == ({"dev"} if central else {"dev", "stage_prod"})
    for section in document.values():
        assert section[KEY] == ""
