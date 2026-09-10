import copy
import ipaddress
import json
from itertools import combinations
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src import api, factory_configuration, scaling_policy as policy, wizard


OWN = "own-subscriptions"
SHARED = "shared-subscriptions"
KEY = "scaling-mode"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv(api.API_KEY_ENV, "scaling-test")
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(tmp_path / "snapshots"))
    with TestClient(api.app, headers={"X-API-Key": "scaling-test"}) as test_client:
        yield test_client


def test_schema_profiles_and_existing_defaults(client):
    schema = client.get("/api/v1/schema").json()
    modes = schema["options"]["scaling_modes"]
    assert list(modes) == [OWN, SHARED]
    assert modes[OWN]["label"] == "A) Own subscriptions per project"
    assert modes[SHARED]["label"] == "B) Common subscriptions for up to 8 projects"
    for mode, prefix in ((OWN, 20), (SHARED, 18)):
        assert modes[mode]["cidr_prefix"] == prefix
        assert modes[mode]["description"]
        assert modes[mode]["capacity_description"]
        assert set(modes[mode]["network_defaults"]) == set(policy.SCALING_NETWORK_KEYS)
    assert modes[SHARED]["address_budget_project_capacity"] == 9
    assert modes[SHARED]["current_allocator_full_project_capacity_by_environment"] == {
        "dev": 7, "stage": 7, "prod": 7,
    }
    assert modes[OWN]["current_allocator_full_project_capacity"] == 1
    assert "Dev: 6, Stage: 5, Prod: 4" not in modes[SHARED]["capacity_description"]
    assert "current draft" in modes[SHARED]["capacity_description"]
    assert "non-overlapping" in modes[SHARED]["description"]
    assert "7 full allocator profiles" in modes[SHARED]["capacity_description"]
    assert len(modes[SHARED]["capacity_description"]) < 250
    assert "not two" in modes[OWN]["capacity_description"]
    assert modes[SHARED]["ten_project_minimum_prefix"] == 17
    assert wizard.DEFAULT_STATE[KEY] == schema["defaults"][KEY] == SHARED
    assert wizard.YAML_MAP[KEY] == "variables.scaling-mode"
    assert wizard.ENV_MAP[KEY] == "SCALING_MODE"
    assert KEY in wizard.SCALESET_KEYS
    profiles = schema["options"]["scaling_network_profiles"]
    assert {key: wizard.DEFAULT_STATE[key] for key in policy.SCALING_NETWORK_KEYS} in profiles
    assert {key: schema["defaults"][key] for key in policy.SCALING_NETWORK_KEYS} in profiles
    assert modes[OWN]["network_defaults"] in profiles
    assert schema["defaults"]["common_vnet_cidr"] == "172.16.XX.0/18"


def test_format_help_matches_presets_and_distinguishes_ipv4_from_current_support(client):
    help_content = client.get("/api/v1/schema").json()["options"]["vnet_format_help"]
    assert help_content["examples"] == [
        {"mode": "Shared", "template": "172.16.XX.0/18", "ranges": "0 / 64 / 128"},
        {"mode": "Own", "template": "172.16.XX.0/20", "ranges": "0 / 16 / 32"},
    ]
    notes = "\n".join(help_content["notes"])
    assert "XX in the third octet" in notes
    assert "10.61.0.0/18" in notes
    assert "second-octet placeholders are NOT yet supported" in notes
    assert "172.16 through 172.31" in notes
    assert "third octet must be 0" in notes
    assert str(ipaddress.IPv4Network("10.61.0.0/18", strict=True)) == "10.61.0.0/18"
    with pytest.raises(ValueError):
        ipaddress.IPv4Network("172.16.61.0/16", strict=True)
    with pytest.raises(ValueError, match="third octet"):
        policy.resolve_network({"common_vnet_cidr": "10.XX.0.0/18"}, "common_vnet_cidr", "61")


def test_format_help_returns_independent_data_and_does_not_mutate_configuration():
    help_content = policy.vnet_format_help()
    help_content["examples"][0]["template"] = "changed"
    assert policy.vnet_format_help()["examples"][0]["template"] == "172.16.XX.0/18"


def test_fresh_defaults_use_shared_preset_but_custom_templates_and_imports_are_preserved(monkeypatch):
    legacy = policy.SCALING_NETWORK_PROFILES[2]
    monkeypatch.setattr(wizard, "_load_template_defaults", lambda: dict(legacy))
    assert wizard.new_configuration_defaults()["common_vnet_cidr"] == "172.16.XX.0/18"
    assert factory_configuration._default_state()["common_vnet_cidr"] == "172.16.XX.0/18"
    restored = api._state({KEY: SHARED, **legacy})
    assert all(restored[key] == value for key, value in legacy.items())
    custom = {**legacy, "common_vnet_cidr": "10.0.0.0/16"}
    monkeypatch.setattr(wizard, "_load_template_defaults", lambda: custom)
    defaults = wizard.new_configuration_defaults()
    assert all(defaults[key] == value for key, value in custom.items())


@pytest.mark.parametrize("prefixes,total,doubled", [
    (policy.SCREENSHOT_PROJECT_PREFIXES, 1856, 3712),
    (policy.PROJECT_PREFIXES, 1888, 3776),
])
def test_minimum_network_doubles_address_budget_not_each_subnet(prefixes, total, doubled):
    assert policy.address_budget(policy.COMMON_PREFIXES) == 256
    assert policy.address_budget(policy.COMMON_PREFIXES) + policy.address_budget(prefixes) == total
    assert 2 * total == doubled
    assert policy.smallest_ipv4_prefix(doubled) == 20
    assert 2**11 < doubled <= 2**12


def test_shared_capacity_reserves_common_addresses_and_ten_require_larger_cidr():
    assert policy.address_budget(policy.PROJECT_PREFIXES) == 1632
    assert 2**14 - policy.address_budget(policy.COMMON_PREFIXES) == 16128
    assert policy.project_capacity(18) == 9
    assert 9 * 1632 + 256 <= 2**14
    assert 8 * 1632 + 256 <= 2**14
    assert 10 * 1632 + 256 == 16576 > 2**14
    assert policy.smallest_ipv4_prefix(16576) == 17


@pytest.mark.parametrize("profile", policy.SCALING_NETWORK_PROFILES[:2])
@pytest.mark.parametrize("range_key", policy.ENVIRONMENT_RANGE_KEYS)
def test_profiles_have_aligned_common_subnets_within_each_environment(profile, range_key):
    vnet, subnets = policy.resolved_common_networks(profile, range_key)
    assert sum(subnet.num_addresses for subnet in subnets.values()) == 256
    assert all(subnet.subnet_of(vnet) for subnet in subnets.values())
    assert all(not left.overlaps(right) for left, right in combinations(subnets.values(), 2))
    assert policy.scaling_validation_issues({KEY: OWN, **profile}) == []


def test_own_environment_vnets_are_distinct_and_aligned():
    profile = policy.SCALING_MODES[OWN]["network_defaults"]
    networks = [policy.resolved_common_networks(profile, key)[0]
                for key in policy.ENVIRONMENT_RANGE_KEYS]
    assert list(map(str, networks)) == ["172.16.0.0/20", "172.16.16.0/20", "172.16.32.0/20"]
    assert all(not left.overlaps(right) for left, right in combinations(networks, 2))


@pytest.mark.parametrize("profile", policy.SCALING_NETWORK_PROFILES)
@pytest.mark.parametrize("mode", [OWN, SHARED])
def test_switching_an_untouched_profile_applies_whole_new_profile(profile, mode):
    state = {KEY: SHARED if mode == OWN else OWN, **profile, "unrelated": "keep"}
    result = policy.apply_scaling_mode(state, mode)
    assert result is state
    assert state == {KEY: mode, **policy.SCALING_MODES[mode]["network_defaults"], "unrelated": "keep"}


@pytest.mark.parametrize("key", policy.SCALING_NETWORK_KEYS)
@pytest.mark.parametrize("custom", ["", "custom"])
def test_one_custom_or_empty_network_value_prevents_all_automatic_replacement(key, custom):
    state = {KEY: SHARED, **policy.SCALING_MODES[SHARED]["network_defaults"]}
    state[key] = custom
    before = copy.deepcopy(state)
    policy.apply_scaling_mode(state, OWN)
    assert state == {**before, KEY: OWN}
    policy.apply_scaling_mode(state, SHARED)
    assert state == before


@pytest.mark.parametrize("mode", [OWN, SHARED])
def test_reselecting_same_mode_does_not_reset_network(mode):
    state = {KEY: mode, **policy.SCALING_MODES[SHARED]["network_defaults"]}
    before = copy.deepcopy(state)
    policy.apply_scaling_mode(state, mode)
    assert state == before


def test_incomplete_network_is_not_assumed_untouched_and_explicit_apply_is_atomic():
    state = {"common_vnet_cidr": "", "unrelated": "keep"}
    policy.apply_scaling_mode(state, OWN)
    assert state == {"common_vnet_cidr": "", "unrelated": "keep", KEY: OWN}
    policy.apply_scaling_mode(state, OWN, apply_defaults=True)
    assert state == {**policy.SCALING_MODES[OWN]["network_defaults"], "unrelated": "keep", KEY: OWN}


@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
@pytest.mark.parametrize("mode", [OWN, SHARED])
def test_api_import_export_roundtrip_preserves_mode_and_custom_network(client, format_name, mode):
    network = {key: value.replace("172.16", "10.80")
               for key, value in policy.SCALING_MODES[SHARED]["network_defaults"].items()}
    network["dev_cidr_range"] = "192"
    state = {KEY: mode, **network}
    exported = client.post("/api/v1/export", json={"format": format_name, "state": state})
    assert exported.status_code == 200, exported.text
    content = exported.json()["content"]
    if format_name == "json":
        document = json.loads(content)
        assert document["dev"][KEY] == document["stage_prod"][KEY] == mode
    elif format_name == "yaml":
        assert yaml.safe_load(content)["variables"][KEY] == mode
    else:
        assert f'SCALING_MODE="{mode}"' in content
        assert "SCALING-MODE=" not in content
    imported = client.post("/api/v1/import", json={
        "format": format_name, "content": content, "state": {KEY: SHARED if mode == OWN else OWN},
    })
    assert imported.status_code == 200, imported.text
    result = imported.json()["state"]
    assert result[KEY] == mode
    assert {key: result[key] for key in network} == network


@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
def test_import_missing_legacy_mode_uses_shared_without_resetting_any_cidr(client, format_name):
    content = {
        "yaml": 'variables:\n  common_vnet_cidr: "172.16.0.0/16"\n',
        "env": f'{wizard.ENV_MAP["common_vnet_cidr"]}="172.16.0.0/16"\n',
        "json": json.dumps({"dev": {"common_vnet_cidr": "172.16.0.0/16"}}),
    }[format_name]
    state = {KEY: OWN, **policy.SCALING_MODES[OWN]["network_defaults"],
             "common_subnet_cidr": "172.16.86.0/26", "prod_cidr_range": ""}
    imported = client.post("/api/v1/import", json={
        "format": format_name, "content": content, "state": state,
    }).json()["state"]
    assert imported[KEY] == SHARED
    assert {key: imported[key] for key in policy.SCALING_NETWORK_KEYS} == {
        **{key: state[key] for key in policy.SCALING_NETWORK_KEYS},
        "common_vnet_cidr": "172.16.0.0/16",
    }


def test_stage_prod_only_json_import(client):
    state = {KEY: OWN, **policy.SCALING_MODES[OWN]["network_defaults"]}
    response = client.post("/api/v1/import", json={
        "format": "json", "content": json.dumps({"stage_prod": state}),
    })
    assert response.status_code == 200
    assert all(response.json()["state"][key] == value for key, value in state.items())


@pytest.mark.parametrize("mode", ["invalid", "", None, False, [], {}])
def test_invalid_explicit_modes_are_rejected_without_replacing_export_file(client, tmp_path, mode):
    state = {KEY: mode}
    validation = client.post("/api/v1/validation", json={"state": state}).json()
    assert not validation["valid"]
    assert any(issue["field"] == KEY and issue["code"] == "invalid_scaling_mode"
               for issue in validation["issues"])
    for format_name in ("json", "yaml", "env"):
        path = tmp_path / f"existing.{format_name}"
        path.write_text("untouched", encoding="utf-8")
        response = client.post("/api/v1/export", json={
            "format": format_name, "path": str(path), "state": state,
        })
        assert response.status_code == 422
        assert path.read_text(encoding="utf-8") == "untouched"
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="scaling-mode"):
        policy.apply_scaling_mode(state, mode, apply_defaults=True)
    assert state == before


def test_invalid_direct_json_export_does_not_truncate_existing_file(tmp_path):
    path = tmp_path / "variables.json"
    path.write_text("untouched", encoding="utf-8")
    with pytest.raises(ValueError, match="scaling-mode"):
        wizard._save_variables_json({KEY: ""}, str(tmp_path))
    assert path.read_text(encoding="utf-8") == "untouched"


def test_factory_configuration_rejects_invalid_mode_before_creating_files(tmp_path):
    destination = tmp_path / "new-factory"
    with pytest.raises(factory_configuration.ConfigurationError, match="scaling-mode"):
        factory_configuration.save_configuration(
            kind="factory", target_region="swedencentral",
            destination_folder=str(destination), state={KEY: ""},
        )
    assert not destination.exists()


def test_new_template_validates_environment_alignment_and_subnet_containment(client):
    state = {KEY: OWN, **policy.SCALING_MODES[OWN]["network_defaults"]}
    state["prod_cidr_range"] = "25"
    issues = policy.scaling_validation_issues(state)
    assert any(issue["field"] == "prod_cidr_range" for issue in issues)
    state["prod_cidr_range"] = "32"
    state["common_subnet_cidr"] = "172.16.120.0/26"
    issues = policy.scaling_validation_issues(state)
    assert any(issue["code"] == "subnet_outside_vnet" for issue in issues)
    response = client.post("/api/v1/export", json={"format": "json", "state": state})
    assert response.status_code == 422


@pytest.mark.parametrize("mode", [OWN, SHARED])
def test_defaults_normalization_never_applies_profile_to_custom_network(client, mode):
    values = {KEY: mode, "common_vnet_cidr": "172.16.0.0/16", "prod_cidr_range": "",
              "common_bastion_subnet_cidr": "172.16.120.192/26"}
    response = client.post("/api/v1/state/defaults", json={"state": values}).json()["state"]
    assert all(response[key] == value for key, value in values.items())
    assert policy.scaling_validation_issues(response)


@pytest.mark.parametrize("mode", [OWN, SHARED])
def test_project_factory_and_scale_set_snapshots_roundtrip_mode_and_network(client, tmp_path, mode):
    state = {**wizard.DEFAULT_STATE, KEY: mode, "_save_folder": str(tmp_path),
             "dev_cidr_range": "192"}
    project_path = wizard._save_project_snapshot(state)
    project = wizard._load_project_state(project_path, str(tmp_path))
    scale_path = wizard._save_scaleset_snapshot(state)
    response = client.post("/api/v1/scale-sets/load", json={
        "aifactory_folder": str(tmp_path), "scale_set_id": "001",
    })
    assert response.status_code == 200
    scale_set = response.json()["state"]
    factory_path = tmp_path / "config-wizard" / "factory_state.json"
    factory_path.write_text(json.dumps(state), encoding="utf-8")
    factory = {}
    assert wizard._import_json_to_state(str(factory_path), factory)
    for restored in (project, scale_set, factory):
        assert restored[KEY] == mode
        assert all(restored[key] == state[key] for key in policy.SCALING_NETWORK_KEYS)
    assert json.loads(Path(scale_path).read_text(encoding="utf-8"))[KEY] == mode


def test_legacy_scale_set_snapshot_load_defaults_only_mode_and_hub_intent(client, tmp_path):
    state = {"_save_folder": str(tmp_path), "admin_aifactorySuffixRG": "-001",
             "common_vnet_cidr": "172.16.0.0/16", "dev_cidr_range": ""}
    wizard._save_scaleset_snapshot(state)
    response = client.post("/api/v1/scale-sets/load", json={
        "aifactory_folder": str(tmp_path), "scale_set_id": "001",
    }).json()["state"]
    assert response == {**state, KEY: SHARED,
                        "centralDnsZoneByPolicyInHub": "false", "enableAIFactoryHub": "false"}


def test_legacy_defaults_and_project_factory_snapshots_retain_custom_cidrs(client, tmp_path):
    values = {"common_vnet_cidr": "172.16.0.0/16", "dev_cidr_range": "",
              "common_subnet_cidr": "172.16.86.0/26", "orchestrator": "ado"}
    normalized = client.post("/api/v1/state/defaults", json={"state": values}).json()["state"]
    project_path = tmp_path / "project_state.json"
    project_path.write_text(json.dumps(values), encoding="utf-8")
    project = wizard._load_project_state(str(project_path), str(tmp_path))
    factory_path = tmp_path / "factory_state.json"
    factory_path.write_text(json.dumps(values), encoding="utf-8")
    factory = {KEY: OWN}
    assert wizard._import_json_to_state(str(factory_path), factory)
    for restored in (normalized, project, factory):
        assert restored[KEY] == SHARED
        assert all(restored[key] == value for key, value in values.items())


@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
def test_invalid_imported_mode_is_preserved_for_validation_not_silently_defaulted(client, format_name):
    content = {
        "yaml": 'variables:\n  scaling-mode: ""\n',
        "env": 'SCALING_MODE=""\n',
        "json": '{"dev": {"scaling-mode": ""}}',
    }[format_name]
    response = client.post("/api/v1/import", json={"format": format_name, "content": content})
    assert response.status_code == 200
    assert response.json()["state"][KEY] == ""
    validation = client.post("/api/v1/validation", json={"state": response.json()["state"]}).json()
    assert any(issue["code"] == "invalid_scaling_mode" for issue in validation["issues"])


def test_tkinter_scaling_radios_apply_only_on_user_action(monkeypatch):
    root = wizard.tk.Tk()
    root.withdraw()
    monkeypatch.setattr(wizard, "_VAR_REGISTRY", [])
    try:
        state = copy.deepcopy(wizard.DEFAULT_STATE)
        selector = wizard._ScalingModeSelector(root, state)
        original = copy.deepcopy(state)
        selector.mode.set(OWN)
        assert state == original  # Loading/synchronizing widgets must not apply defaults.
        selector._choose()
        assert state[KEY] == OWN
        assert state["common_vnet_cidr"] == "172.16.XX.0/20"
        state["common_vnet_cidr"] = ""
        selector.mode.set(SHARED)
        selector._choose()
        assert state["common_vnet_cidr"] == ""
        selector._apply_defaults()
        assert state["common_vnet_cidr"] == "172.16.XX.0/18"
    finally:
        root.destroy()


@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
@pytest.mark.parametrize("change", [
    {"common_vnet_cidr": "172.16.0.0/16", "dev_cidr_range": "61",
     "test_cidr_range": "62", "prod_cidr_range": "63"},
    {"common_vnet_cidr": "172.16.XX.0/18", "dev_cidr_range": "61",
     "test_cidr_range": "62", "prod_cidr_range": "63"},
    {"test_cidr_range": "0"},
    {"common_subnet_scoring_cidr": "172.16.XX.0/26"},
    {"common_pbi_subnet_cidr": ""},
])
def test_invalid_network_import_preserved_warned_and_every_write_blocked(client, tmp_path, format_name, change):
    values = {**wizard.DEFAULT_STATE, **change, "_save_folder": str(tmp_path)}
    network = {key: values[key] for key in policy.SCALING_NETWORK_KEYS}
    if format_name == "json":
        content = json.dumps({"dev": network})
    elif format_name == "yaml":
        content = yaml.safe_dump({"variables": network})
    else:
        content = "\n".join(f'{wizard.ENV_MAP[key]}="{value}"' for key, value in network.items())
    imported = client.post("/api/v1/import", json={"format": format_name, "content": content})
    assert imported.status_code == 200
    assert imported.json()["warnings"]
    assert {key: imported.json()["state"][key] for key in network} == network
    assert not client.post("/api/v1/validation", json={"state": values}).json()["valid"]
    for kind in ("json", "yaml", "env"):
        output = tmp_path / f"existing.{kind}"
        output.write_text("unchanged", encoding="utf-8")
        response = client.post("/api/v1/export", json={"format": kind, "state": values, "path": str(output)})
        assert response.status_code == 422
        assert output.read_text(encoding="utf-8") == "unchanged"
    project = tmp_path / "config-wizard" / f"project-{values['project_number_000']}" / "project_state.json"
    scale = tmp_path / "config-wizard" / "scalesets" / "scaleset_001.json"
    for path in (project, scale):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values), encoding="utf-8")
    original = {path: path.read_bytes() for path in (project, scale)}
    # Reading old invalid snapshots is supported; re-saving requires explicit repair.
    restored = wizard._load_project_state(str(project), str(tmp_path))
    assert all(restored[key] == value for key, value in network.items())
    loaded = client.post("/api/v1/scale-sets/load", json={"aifactory_folder": str(tmp_path), "scale_set_id": "001"})
    assert loaded.status_code == 200
    assert all(loaded.json()["state"][key] == value for key, value in network.items())
    for saver in (wizard._save_project_snapshot, wizard._save_scaleset_snapshot):
        with pytest.raises(ValueError, match="Cannot peer"):
            saver(values)
    for route in ("projects", "scale-sets"):
        assert client.post(f"/api/v1/{route}/save", json={"state": values}).status_code == 422
    assert {path: path.read_bytes() for path in original} == original
    destination = tmp_path / "new-factory"
    with pytest.raises(factory_configuration.ConfigurationError, match="Cannot peer"):
        factory_configuration.save_configuration("factory", "swedencentral", str(destination), values)
    assert not destination.exists()


@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
def test_direct_export_invalid_complete_network_does_not_truncate(tmp_path, format_name):
    values = {**wizard.DEFAULT_STATE, "test_cidr_range": "0"}
    path = tmp_path / ("variables.json" if format_name == "json" else f"existing.{format_name}")
    path.write_text("unchanged", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot peer"):
        if format_name == "json":
            wizard._save_variables_json(values, str(tmp_path))
        elif format_name == "yaml":
            wizard.save_azure_devops(values, str(path))
        else:
            wizard.save_github_actions(values, str(path))
    assert path.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize("repository", ["python", "purple"])
@pytest.mark.parametrize("format_name", ["yaml", "env", "json"])
def test_raw_template_defaults_are_peerable_without_fresh_default_normalization(repository, format_name):
    root = Path(__file__).resolve().parents[1]
    if repository == "python":
        path = root / "template-files" / {"yaml": "variables.yaml", "env": ".env", "json": "variables.json"}[format_name]
    else:
        root = root.parent / "003_aifactory_sub" / "azure-enterprise-scale-ml" / "environment_setup" / "aifactory"
        path = {
            "yaml": root / "bicep" / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines" / "variables" / "variables.yaml",
            "env": root / "bicep" / "copy_to_local_settings" / "github-actions" / ".env.template",
            "json": root / "variables.json",
        }[format_name]
    text = path.read_text(encoding="utf-8")
    if format_name == "json":
        document = json.loads(text)
        assert set(document) == ({"dev", "stage_prod"} if repository == "python" else {"dev"})
        states = list(document.values())
    elif format_name == "yaml":
        states = [yaml.safe_load(text)["variables"]]
    else:
        state = {}
        assert wizard._import_env_to_state(str(path), state)
        states = [state]
    for state in states:
        assert state[KEY] == SHARED
        assert all(str(state[key]).lower() == "false" for key in wizard.HUB_FLAG_KEYS)
        assert {key: str(state[key]) for key in policy.SCALING_NETWORK_KEYS} == policy.SCALING_MODES[SHARED]["network_defaults"]
        assert policy.network_validation_issues(state) == []
        networks = [policy.resolved_common_networks(state, key)[0] for key in policy.ENVIRONMENT_RANGE_KEYS]
        assert all(not a.overlaps(b) for a, b in combinations(networks, 2))
