import copy
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src import api, factory_configuration, wizard


DNS, OWN = wizard.HUB_FLAG_KEYS
PAIRS = [("false", "false"), ("false", "true"), ("true", "false"), ("true", "true")]
TEMPLATES = Path(__file__).resolve().parents[1] / "template-files"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv(api.API_KEY_ENV, "hub-tests")
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    with TestClient(api.app, headers={"X-API-Key": "hub-tests"}) as result:
        yield result


def content_for(format_name, values):
    if format_name == "json":
        return json.dumps({"dev": values})
    if format_name == "yaml":
        return yaml.safe_dump({"variables": values})
    return "\n".join(
        f'{wizard.ENV_MAP.get(key, "_HUB_TOPOLOGY")}="{value}"'
        for key, value in values.items()
    )


def test_schema_preparation_and_three_physical_templates_have_false_defaults(client):
    schema = client.get("/api/v1/schema").json()
    prepared = client.post("/api/v1/factories/configuration/prepare", json={
        "kind": "factory", "target_region": "westeurope",
    }).json()
    for key in (DNS, OWN):
        assert wizard.DEFAULT_STATE[key] == schema["defaults"][key] == "false"
        assert wizard._load_template_defaults()[key] == "false"
        assert key in schema["sections"]["scale_set_variables"]
        assert key in prepared["field_keys"]
        assert prepared["state"][key] == "false"
    assert schema["mappings"]["yaml"][OWN] == f"variables.{OWN}"
    assert schema["mappings"]["env"][OWN] == "ENABLE_AI_FACTORY_HUB"
    raw_json = json.loads((TEMPLATES / "variables.json").read_text(encoding="utf-8"))
    assert set(raw_json) == {"dev", "stage_prod"}
    for section in raw_json.values():
        assert len(section) > 300
        assert section[DNS] is section[OWN] is False
        assert section["scaling-mode"] == "shared-subscriptions"
    raw_yaml = yaml.safe_load((TEMPLATES / "variables.yaml").read_text(encoding="utf-8"))["variables"]
    assert raw_yaml[DNS] == raw_yaml[OWN] == "false"
    assert raw_yaml["scaling-mode"] == "shared-subscriptions"
    state = {}
    assert wizard._import_env_to_state(str(TEMPLATES / ".env"), state) > 0
    assert state[DNS] == state[OWN] == "false"
    assert state["scaling-mode"] == "shared-subscriptions"


@pytest.mark.parametrize("dns,own", PAIRS)
@pytest.mark.parametrize("format_name", ["yaml", "json", "env"])
def test_exact_pair_roundtrips_without_changing_configuration(client, format_name, dns, own):
    state = {DNS: dns, OWN: own, "_hub_topology": "own-hub",
             "common_vnet_cidr": "172.16.XX.0/18"}
    before = copy.deepcopy(state)
    exported = client.post("/api/v1/export", json={"format": format_name, "state": state})
    assert exported.status_code == 200, exported.text
    content = exported.json()["content"]
    if format_name == "json":
        for section in json.loads(content).values():
            assert section[DNS] is (dns == "true")
            assert section[OWN] is (own == "true")
    elif format_name == "yaml":
        values = yaml.safe_load(content)["variables"]
        assert (values[DNS], values[OWN]) == (dns, own)
    else:
        assert f'ENABLE_AI_FACTORY_HUB="{own}"' in content
        assert f'CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB="{dns}"' in content
    loaded = client.post("/api/v1/import", json={
        "format": format_name, "content": content,
        "state": {DNS: "true", OWN: "true", "_hub_topology": "own-hub"},
    })
    assert loaded.status_code == 200, loaded.text
    assert (loaded.json()["state"][DNS], loaded.json()["state"][OWN]) == (dns, own)
    assert loaded.json()["state"]["common_vnet_cidr"] == state["common_vnet_cidr"]
    assert state == before


@pytest.mark.parametrize("format_name", ["yaml", "json", "env"])
@pytest.mark.parametrize("metadata", ["", "own-hub"])
@pytest.mark.parametrize("explicit", [None, "false", "true"])
def test_import_uses_only_imported_own_intent_not_edited_state(client, format_name, metadata, explicit):
    values = {DNS: "true"}
    if metadata:
        values["_hub_topology"] = metadata
    if explicit is not None:
        values[OWN] = explicit
    response = client.post("/api/v1/import", json={
        "format": format_name, "content": content_for(format_name, values),
        "state": {OWN: "true", "_hub_topology": "own-hub"},
    })
    assert response.status_code == 200, response.text
    loaded = response.json()["state"]
    assert loaded[DNS] == "true"
    assert loaded[OWN] == (explicit if explicit is not None else (
        "true" if metadata == "own-hub" else "false"))


@pytest.mark.parametrize("placement", ["root", "_wizard"])
@pytest.mark.parametrize("explicit", [None, False])
def test_json_legacy_metadata_locations_do_not_override_explicit_false(client, placement, explicit):
    document = {"dev": {DNS: False}}
    if explicit is not None:
        document["dev"][OWN] = explicit
    if placement == "root":
        document["_hub_topology"] = "own-hub"
    else:
        document["_wizard"] = {"_hub_topology": "own-hub"}
    response = client.post("/api/v1/import", json={
        "format": "json", "content": json.dumps(document),
    })
    assert response.status_code == 200
    assert response.json()["state"][OWN] == ("true" if explicit is None else "false")


@pytest.mark.parametrize("format_name", ["yaml", "json", "env"])
def test_invalid_imported_flag_stays_visible_for_validation(client, format_name):
    response = client.post("/api/v1/import", json={
        "format": format_name, "content": content_for(format_name, {OWN: "invalid"}),
    })
    assert response.status_code == 200
    state = response.json()["state"]
    assert state[OWN] == "invalid"
    issues = client.post("/api/v1/validation", json={"state": state}).json()["issues"]
    assert any(issue["field"] == OWN and issue["code"] == "invalid_boolean" for issue in issues)


def test_old_yaml_template_still_exports_both_flags(monkeypatch, tmp_path):
    path = tmp_path / "legacy.yaml"
    path.write_text('variables:\n  admin_location: "westeurope"\n', encoding="utf-8")
    monkeypatch.setattr(wizard, "_find_template_yaml", lambda: str(path))
    values = yaml.safe_load("".join(wizard._render_azure_devops({OWN: "true", DNS: "true"})))
    assert values["variables"][OWN] == values["variables"][DNS] == "true"
    assert path.read_text(encoding="utf-8") == 'variables:\n  admin_location: "westeurope"\n'


def test_same_project_current_file_without_flag_does_not_keep_snapshot_own_hub(tmp_path):
    snapshot = tmp_path / "project_state.json"
    snapshot.write_text(json.dumps({
        "project_number_000": "017", OWN: "true", "_hub_topology": "own-hub",
    }), encoding="utf-8")
    (tmp_path / "variables.json").write_text(json.dumps({
        "dev": {"project_number_000": "017", DNS: True},
    }), encoding="utf-8")
    loaded = wizard._load_project_state(str(snapshot), str(tmp_path))
    assert loaded[OWN] == "false"
    assert loaded[DNS] == "true"


@pytest.mark.parametrize("metadata,explicit,expected", [
    ("", None, "false"), ("own-hub", None, "true"),
    ("own-hub", False, "false"), ("own-hub", "false", "false"),
    ("external-hub", True, "true"),
])
def test_defaults_factory_and_snapshot_migration_precedes_default_merge(
        client, tmp_path, metadata, explicit, expected):
    supplied = {"orchestrator": "ado", DNS: True, "_hub_topology": metadata,
                "project_number_000": "017", "admin_aifactorySuffixRG": "-003"}
    if explicit is not None:
        supplied[OWN] = explicit
    original = copy.deepcopy(supplied)
    assert wizard.hub_configuration(supplied)[OWN] == expected
    assert factory_configuration._schema_state(supplied)[OWN] == expected
    response = client.post("/api/v1/state/defaults", json={"state": supplied})
    assert response.json()["state"][OWN] == expected
    assert response.json()["state"][DNS] == "true"
    root = tmp_path / "factory"
    config = root / "config-wizard"
    config.mkdir(parents=True)
    factory_path = config / "factory_state.json"
    factory_path.write_text(json.dumps(supplied), encoding="utf-8")
    restored = {OWN: "true"}
    wizard._import_json_to_state(str(factory_path), restored)
    assert restored[OWN] == expected
    project_path = config / "project-017" / "project_state.json"
    project_path.parent.mkdir()
    project_path.write_text(json.dumps(supplied), encoding="utf-8")
    assert wizard._load_project_state(str(project_path), str(root))[OWN] == expected
    scale_path = config / "scalesets" / "scaleset_003.json"
    scale_path.parent.mkdir()
    scale_path.write_text(json.dumps(supplied), encoding="utf-8")
    response = client.post("/api/v1/scale-sets/load", json={
        "aifactory_folder": str(root), "scale_set_id": "003",
    })
    assert response.status_code == 200, response.text
    assert response.json()["state"][OWN] == expected
    assert response.json()["state"][DNS] == "true"
    assert supplied == original


@pytest.mark.parametrize("dns,own", PAIRS)
def test_project_and_scale_set_save_restore_pair(client, tmp_path, dns, own):
    state = {DNS: dns, OWN: own, "_save_folder": str(tmp_path / "factory"),
             "project_number_000": "017", "admin_aifactorySuffixRG": "-003"}
    for route, path_key in (("projects", "snapshot_path"), ("scale-sets", "path")):
        response = client.post(f"/api/v1/{route}/save", json={"state": state})
        assert response.status_code == 200, response.text
        saved = json.loads(Path(response.json()[path_key]).read_text(encoding="utf-8"))
        assert (saved[DNS], saved[OWN]) == (dns, own)
    loaded = client.post("/api/v1/projects/load", json={
        "aifactory_folder": state["_save_folder"], "project_number": "017",
    })
    assert loaded.status_code == 200
    assert (loaded.json()["state"][DNS], loaded.json()["state"][OWN]) == (dns, own)


@pytest.mark.parametrize("dns,own", PAIRS)
def test_factory_save_and_clone_keep_intent_without_touching_source(tmp_path, dns, own):
    root = tmp_path / "factory"
    guid = "12345678-1234-1234-1234-123456789abc"
    state = factory_configuration.prepare_configuration("factory", "westeurope")["state"]
    state.update({DNS: dns, OWN: own, "admin_aifactoryPrefixRG": "unit-",
                  "admin_aifactorySuffixRG": "-002", "tenantId": guid,
                  "dev_sub_id": guid, "test_sub_id": guid, "prod_sub_id": guid})
    saved = factory_configuration.save_configuration("factory", "westeurope", str(root), state)
    source_files = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    for kind, region in (("clone", "swedencentral"), ("scale-set", "westeurope")):
        prepared = factory_configuration.prepare_configuration(kind, region, str(root))
        assert (prepared["state"][DNS], prepared["state"][OWN]) == (dns, own)
        assert OWN in prepared["field_keys"] and DNS in prepared["field_keys"]
    persisted = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    assert (persisted[DNS], persisted[OWN]) == (dns, own)
    assert {path: path.read_bytes() for path in source_files} == source_files


def test_legacy_factory_save_migrates_before_prepared_defaults(tmp_path):
    state = factory_configuration.prepare_configuration("factory", "westeurope")["state"]
    state.pop(OWN)
    guid = "12345678-1234-1234-1234-123456789abc"
    state.update({"_hub_topology": "own-hub", "admin_aifactoryPrefixRG": "unit-",
                  "admin_aifactorySuffixRG": "-002", "tenantId": guid,
                  "dev_sub_id": guid, "test_sub_id": guid, "prod_sub_id": guid})
    result = factory_configuration.save_configuration(
        "factory", "westeurope", str(tmp_path / "factory"), state)
    assert result["state"][OWN] == "true"
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8"))[OWN] == "true"


@pytest.mark.parametrize("key", [DNS, OWN])
@pytest.mark.parametrize("value", ["maybe", "", None, 1, [], {}])
def test_invalid_boolean_cannot_truncate_any_export_or_snapshot(client, tmp_path, key, value):
    state = {key: value, "_save_folder": str(tmp_path), "project_number_000": "017",
             "admin_aifactorySuffixRG": "-003"}
    response = client.post("/api/v1/validation", json={"state": state})
    assert any(issue["field"] == key and issue["code"] == "invalid_boolean"
               for issue in response.json()["issues"])
    for format_name in ("json", "yaml", "env"):
        path = tmp_path / f"existing.{format_name}"
        path.write_text("unchanged", encoding="utf-8")
        response = client.post("/api/v1/export", json={
            "format": format_name, "state": state, "path": str(path),
        })
        assert response.status_code == 422, response.text
        assert path.read_text(encoding="utf-8") == "unchanged"
    for route in ("projects", "scale-sets"):
        response = client.post(f"/api/v1/{route}/save", json={"state": state})
        assert response.status_code == 422, response.text
    with pytest.raises(factory_configuration.ConfigurationError, match=key):
        factory_configuration._schema_state(state)


def test_tkinter_checkbox_is_bound_and_loading_both_true_does_not_clear_own(monkeypatch):
    monkeypatch.setattr(wizard, "_VAR_REGISTRY", [])
    root = wizard.tk.Tk()
    root.withdraw()
    try:
        state = wizard.new_configuration_defaults()
        state.update({DNS: "true", OWN: "true"})
        page = wizard.PageAdvancedNetworking(root, state)
        page.on_enter()
        assert page._own_hub_var.get() is True
        assert state[OWN] == state[DNS] == "true"
        checkbox = next(widget for widget in page.winfo_children()
                        if isinstance(widget, wizard.ttk.Checkbutton)
                        and "own Hub" in widget.cget("text"))
        checkbox.invoke()
        assert state[OWN] == "false"
        assert state[DNS] == "true"
        state[OWN] = "true"
        page.on_enter()
        assert page._own_hub_var.get() is True
    finally:
        root.destroy()
