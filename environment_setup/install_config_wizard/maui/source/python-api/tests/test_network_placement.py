import copy
import importlib.util
import ipaddress
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, network_placement as placement, scaling_policy as policy, wizard


URL = "/api/v1/network/placement/preview"
SHARED = "shared-subscriptions"
OWN = "own-subscriptions"


def draft(mode=SHARED, **changes):
    return {
        policy.SCALING_MODE_KEY: mode,
        **policy.SCALING_MODES[mode]["network_defaults"],
        **changes,
    }


def capacities(preview):
    return [environment["estimated_full_projects"] for environment in preview["environments"]]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv(api.API_KEY_ENV, "placement-test")
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    with TestClient(api.app, headers={"X-API-Key": "placement-test"}) as test_client:
        yield test_client


@pytest.mark.parametrize("vnet,starts,expected", [
    ("172.16.XX.0/18", ("0", "64", "128"), [7, 7, 7]),
    ("172.16.XX.0/20", ("0", "16", "32"), [1, 1, 1]),
    ("172.16.XX.0/24", ("61", "62", "63"), [None, None, None]),
])
def test_guidance_is_based_on_actual_network_and_all_starts(vnet, starts, expected):
    state = draft(common_vnet_cidr=vnet, **dict(zip(policy.ENVIRONMENT_RANGE_KEYS, starts)))
    result = placement.preview_network_placement(state)
    assert capacities(result) == expected
    for environment, start in zip(result["environments"], starts):
        assert environment["vnet_cidr"] == vnet.replace("XX", start)
        assert environment["start_octet"] == start
        assert environment["common_range"] == f"172.16.{start}.0-172.16.{start}.255"
        assert environment["common_range"] in result["guidance"]
    assert "1632 addresses" in result["guidance"]
    assert "highest end" in result["guidance"]
    assert "Not live inventory" in result["guidance"]
    assert "other deployed subnets may reduce capacity" in result["guidance"]
    assert result["is_peerable"]
    assert placement.PEERING_GUIDANCE in result["guidance"]
    assert placement.DRAFT_WARNING in result["guidance"]


@pytest.mark.parametrize("range_key", policy.ENVIRONMENT_RANGE_KEYS)
def test_changing_each_start_recomputes_its_guidance_and_capacity(range_key):
    baseline = placement.preview_network_placement(draft())
    changed = placement.preview_network_placement(draft(**{range_key: "192"}))
    assert changed["guidance"] != baseline["guidance"]
    for old, new in zip(baseline["environments"], changed["environments"]):
        if new["range_key"] == range_key:
            assert new["estimated_full_projects"] == 7
            assert new["start_octet"] == "192"
        else:
            assert new == old


def test_changing_fixed_common_subnet_outside_other_environments_is_invalid():
    result = placement.preview_network_placement(draft(common_bastion_subnet_cidr="172.16.63.192/26"))
    assert not result["is_peerable"]
    assert capacities(result) == []
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}
    assert "Stage" in result["guidance"] and "outside" in result["guidance"]


@pytest.mark.parametrize("profile", policy.SCALING_NETWORK_PROFILES[:2])
def test_aligned_profiles_are_already_optimal_without_address_changes(profile):
    state = draft(**profile, unrelated_secret="must-not-be-returned")
    before = copy.deepcopy(state)
    result = placement.preview_network_placement(state)
    assert state == before
    assert result["is_peerable"]
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}
    optimized = placement.preview_network_placement({**state, **result["optimization_changes"]})
    assert [e["vnet_cidr"] for e in optimized["environments"]] == [e["vnet_cidr"] for e in result["environments"]]
    assert not optimized["can_optimize"]
    assert optimized["optimization_changes"] == {}
    assert "Already optimal for non-overlapping" in optimized["optimization_description"]
    assert placement.PEERING_GUIDANCE in result["optimization_description"]
    assert placement.DRAFT_WARNING in result["optimization_description"]
    assert "must-not-be-returned" not in json.dumps(result)


def test_own_xx_networks_cannot_collapse_to_one_vnet():
    result = placement.preview_network_placement(draft(OWN))
    assert capacities(result) == [1, 1, 1]
    assert [e["vnet_cidr"] for e in result["environments"]] == [
        "172.16.0.0/20", "172.16.16.0/20", "172.16.32.0/20",
    ]
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}
    assert "Already optimal for non-overlapping" in result["optimization_description"]


@pytest.mark.parametrize("network_prefix", ["172.16", "10.80", "192.168"])
def test_concrete_offset_network_cannot_be_optimized_into_overlapping_vnets(network_prefix):
    state = draft(common_vnet_cidr=f"{network_prefix}.64.0/18",
                  dev_cidr_range="79", test_cidr_range="84", prod_cidr_range="89")
    for key in policy.COMMON_SUBNET_KEYS:
        state[key] = state[key].replace("172.16", network_prefix)
    result = placement.preview_network_placement(state)
    assert not result["is_peerable"]
    assert capacities(result) == []
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}
    assert f"Dev ({network_prefix}.64.0/18) overlaps Stage ({network_prefix}.64.0/18)" in result["guidance"]
    assert "fixed common_vnet_cidr ignores" in result["guidance"]
    assert "Apply network defaults" in result["guidance"]


@pytest.mark.parametrize("change,reason", [
    ({"scaling-mode": None}, "scaling-mode"),
    ({"scaling-mode": []}, "scaling-mode"),
    ({"scaling-mode": "other"}, "scaling-mode"),
    ({"dev_cidr_range": ""}, "dev_cidr_range"),
    ({"test_cidr_range": 20}, "test_cidr_range"),
    ({"prod_cidr_range": "256"}, "prod_cidr_range"),
    ({"prod_cidr_range": "²"}, "prod_cidr_range"),
    ({"dev_cidr_range": "000"}, "not network-aligned"),
    ({"common_vnet_cidr": "172.16.1.0/18"}, "not network-aligned"),
    ({"common_vnet_cidr": "172.16.64.0/18", "dev_cidr_range": "61",
      "test_cidr_range": "62", "prod_cidr_range": "63"}, "outside"),
    ({"common_vnet_cidr": "10.0.0.0/8"}, "overlaps"),
    ({"common_vnet_cidr": "172.16.0.0/15"}, "overlaps"),
    ({"common_vnet_cidr": "172.16.15.0/24"}, "overlaps"),
    ({"common_vnet_cidr": "2001:db8::/32"}, "IPv4"),
    ({"common_vnet_cidr": "172.XX.0.0/16"}, "third octet"),
    ({"common_subnet_cidr": "172.16.XX.0/25"}, "overlap"),
    ({"common_subnet_scoring_cidr": "172.16.XX.65/26"}, "not network-aligned"),
    ({"common_bastion_subnet_cidr": {}}, "IPv4"),
    ({"common_subnet_cidr": None}, "IPv4"),
])
def test_invalid_or_unsupported_draft_is_unknown_and_never_mutated(change, reason):
    state = draft(**change)
    before = copy.deepcopy(state)
    result = placement.preview_network_placement(state)
    assert state == before
    assert not result["is_peerable"]
    assert "Capacity unknown; optimization unavailable" in result["guidance"]
    assert reason in result["guidance"]
    assert result["environments"] == []
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}


@pytest.mark.parametrize("key", placement.PLACEMENT_KEYS)
def test_every_missing_network_input_is_unknown_without_merging_defaults(key):
    state = draft()
    del state[key]
    result = placement.preview_network_placement(state)
    assert "unknown" in result["guidance"]
    assert key in result["guidance"]
    assert result["optimization_changes"] == {}
    assert not result["can_optimize"]


def test_fixed_common_cidrs_are_not_reused_across_distinct_vnets():
    state = draft()
    for key in policy.COMMON_SUBNET_KEYS:
        state[key] = state[key].replace("XX", "15")
    result = placement.preview_network_placement(state)
    assert capacities(result) == []
    assert not result["is_peerable"]
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}
    assert "outside" in result["optimization_description"]


@pytest.mark.parametrize("prefix", [16, 18])
def test_legacy_xx_consecutive_starts_are_not_silently_masked(prefix):
    state = draft(common_vnet_cidr=f"172.16.XX.0/{prefix}",
                  dev_cidr_range="61", test_cidr_range="62", prod_cidr_range="63")
    result = placement.preview_network_placement(state)
    assert not result["is_peerable"]
    assert not result["can_optimize"]
    assert result["optimization_changes"] == {}
    assert f"172.16.61.0/{prefix}" in result["guidance"]
    assert "not network-aligned" in result["guidance"]


@pytest.mark.parametrize("profile", policy.SCALING_NETWORK_PROFILES[2:])
def test_legacy_fixed_overlapping_profiles_remain_visible_until_explicit_repair(profile):
    state = draft(**profile)
    original = copy.deepcopy(state)
    result = placement.preview_network_placement(state)
    assert not result["is_peerable"]
    assert result["optimization_changes"] == {}
    assert "Cannot peer: Dev" in result["guidance"]
    assert "overlaps Stage" in result["guidance"]
    assert state == original
    policy.apply_scaling_mode(state, SHARED)
    assert state == original
    policy.apply_scaling_mode(state, SHARED, apply_defaults=True)
    repaired = placement.preview_network_placement(state)
    assert repaired["is_peerable"]
    assert capacities(repaired) == [7, 7, 7]


def test_capacity_support_is_separate_from_peerability(client):
    state = draft(common_vnet_cidr="172.16.XX.0/24",
                  dev_cidr_range="61", test_cidr_range="62", prod_cidr_range="63")
    response = client.post(URL, json={"state": state})
    assert response.status_code == 200
    result = response.json()
    assert result["is_peerable"]
    assert capacities(result) == [None] * 3
    assert not result["can_optimize"]
    assert "A /24 cannot fit" in result["guidance"]
    assert "capacity unknown" in result["guidance"]
    assert policy.scaling_validation_issues(state) == []
    # The pure helper must not count huge unsupported address spaces either.
    vnet = ipaddress.IPv4Network("172.16.0.0/15")
    subnets = policy.resolved_common_networks(draft(), "dev_cidr_range")[1]
    assert placement.estimate_full_projects(vnet, subnets) is None


def test_narrow_common_subnet_capacity_is_unknown_without_claiming_vnet_overlap():
    result = placement.preview_network_placement(draft(common_pbi_subnet_cidr="172.16.XX.128/30"))
    assert result["is_peerable"]
    assert capacities(result) == [None] * 3
    assert not result["can_optimize"]


def test_followup_overlap_is_not_hidden_by_previous_success(client):
    state = draft()
    assert client.post(URL, json={"state": state}).json()["is_peerable"]
    state["test_cidr_range"] = "0"
    invalid = client.post(URL, json={"state": state}).json()
    assert not invalid["is_peerable"]
    assert not invalid["can_optimize"] and invalid["optimization_changes"] == {}
    assert "Dev (172.16.0.0/18) overlaps Stage (172.16.0.0/18)" in invalid["guidance"]


def test_unexpected_programming_errors_propagate(monkeypatch):
    monkeypatch.setattr(placement, "estimate_full_projects", Mock(side_effect=RuntimeError("defect")))
    with pytest.raises(RuntimeError, match="defect"):
        placement.preview_network_placement(draft())


def test_api_auth_raw_state_and_no_identity_or_persistence(client, monkeypatch):
    assert client.post(URL, json={"state": draft()}, headers={"X-API-Key": ""}).status_code == 401
    assert client.post(URL, json={"state": draft()}, headers={"X-API-Key": "wrong"}).status_code == 401
    monkeypatch.setattr(api, "_state", Mock(side_effect=AssertionError("Do not merge defaults")))
    monkeypatch.setattr(api.azure_auth.azure_auth_service, "status",
                        Mock(side_effect=AssertionError("No Azure identity required")))
    monkeypatch.setattr(wizard, "_save_project_snapshot",
                        Mock(side_effect=AssertionError("No persistence")))
    state = draft(unrelated_secret="never-return-this")
    response = client.post(URL, json={"state": state})
    assert response.status_code == 200
    assert response.json() == placement.preview_network_placement(state)
    assert "never-return-this" not in response.text
    unknown = client.post(URL, json={})
    assert unknown.status_code == 200
    assert not unknown.json()["can_optimize"]
    assert "unknown" in unknown.json()["guidance"]
    monkeypatch.delenv(api.API_KEY_ENV)
    assert client.post(URL, json={"state": state}).status_code == 503


def test_api_response_serialization_filters_unexpected_extra_fields(client, monkeypatch):
    result = placement.preview_network_placement(draft())
    result["unrelated_secret"] = "do-not-serialize"
    result["environments"][0]["unrelated_secret"] = "do-not-serialize"
    monkeypatch.setattr(api, "preview_network_placement", lambda state: result)
    response = client.post(URL, json={"state": draft()})
    assert response.status_code == 200
    assert "do-not-serialize" not in response.text
    assert response.json()["environments"][0]["estimated_full_projects"] == 7


@pytest.mark.parametrize("format_name", ["json", "yaml", "env"])
def test_optimized_state_roundtrips_without_an_extra_profile_flag(client, format_name):
    state = draft(dev_cidr_range="192")
    state.update(placement.preview_network_placement(state)["optimization_changes"])
    before = copy.deepcopy(state)
    for mode in [OWN, SHARED]:
        policy.apply_scaling_mode(state, mode)
        assert state == {**before, policy.SCALING_MODE_KEY: mode}
    exported = client.post("/api/v1/export", json={"format": format_name, "state": state})
    assert exported.status_code == 200, exported.text
    imported = client.post("/api/v1/import", json={
        "format": format_name, "content": exported.json()["content"],
    })
    assert imported.status_code == 200
    restored = imported.json()["state"]
    assert {key: restored[key] for key in state} == state
    assert capacities(placement.preview_network_placement(restored)) == [7, 7, 7]
    assert {key: state[key] for key in policy.SCALING_NETWORK_KEYS} not in policy.SCALING_NETWORK_PROFILES


def test_optimized_project_factory_and_scale_set_snapshots_roundtrip(client, monkeypatch, tmp_path):
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(tmp_path / "snapshots"))
    state = {**wizard.DEFAULT_STATE, **draft(), "_save_folder": str(tmp_path)}
    state.update(placement.preview_network_placement(state)["optimization_changes"])
    project_path = wizard._save_project_snapshot(state)
    project = wizard._load_project_state(project_path, str(tmp_path))
    wizard._save_scaleset_snapshot(state)
    scale_set_response = client.post("/api/v1/scale-sets/load", json={
        "aifactory_folder": str(tmp_path), "scale_set_id": "001",
    })
    assert scale_set_response.status_code == 200
    factory_path = tmp_path / "factory_state.json"
    factory_path.write_text(json.dumps(state), encoding="utf-8")
    factory = {}
    assert wizard._import_json_to_state(str(factory_path), factory)
    for restored in (project, factory, scale_set_response.json()["state"]):
        assert all(restored[key] == state[key] for key in placement.PLACEMENT_KEYS)
        assert capacities(placement.preview_network_placement(restored)) == [7, 7, 7]


def test_checked_in_openapi_exposes_api_key_only_preview(client):
    contract = json.loads((Path(__file__).resolve().parents[1] / "docs" / "openapi.json").read_text(encoding="utf-8"))
    operation = contract["paths"][URL]["post"]
    assert operation == client.get("/openapi.json").json()["paths"][URL]["post"]
    assert operation["security"] == [{"APIKeyHeader": []}]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/StateBody")
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/NetworkPlacementPreview")
    live_schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("NetworkPlacementPreview", "NetworkPlacementEnvironment"):
        assert contract["components"]["schemas"][name] == live_schemas[name]


def test_estimate_matches_existing_offline_real_allocator_fixture():
    fixture_path = (
        Path(__file__).resolve().parents[2] / "003_aifactory_sub" / "azure-enterprise-scale-ml"
        / "environment_setup" / "unit-tests" / "test-bicep" / "unit" / "test_subnet_scaling_capacity.py"
    )
    if not fixture_path.is_file():
        pytest.skip("Optional sibling repository's existing offline allocator fixture is unavailable.")
    spec = importlib.util.spec_from_file_location("offline_allocator_capacity", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Reuse the existing AST-only fixture; never source or execute the full PS script.
    results = module.allocation_results.__wrapped__()
    for (prefix, octet, gateway), actual in results.items():
        if gateway:
            continue
        state = draft(common_vnet_cidr=f"172.16.0.0/{prefix}",
                      **dict.fromkeys(policy.ENVIRONMENT_RANGE_KEYS, str(octet)))
        vnet, subnets = policy.resolved_common_networks(state, "dev_cidr_range")
        assert placement.estimate_full_projects(vnet, subnets) == len(actual["profiles"])
        assert not placement.preview_network_placement(state)["is_peerable"]
        assert all(sum(ipaddress.IPv4Network(cidr).num_addresses for cidr in profile.values()) == 1632
                   for profile in actual["profiles"])


@pytest.fixture(scope="module")
def tk_root():
    root = wizard.tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def selector(monkeypatch, tk_root):
    monkeypatch.setattr(wizard, "_VAR_REGISTRY", [])
    widget = wizard._ScalingModeSelector(tk_root, draft())
    try:
        yield widget
    finally:
        widget.destroy()


def test_tkinter_overlap_disables_optimize_until_explicit_defaults(selector, monkeypatch):
    state = selector.state
    state["common_vnet_cidr"] = "172.16.0.0/16"
    state.update(dict(zip(policy.ENVIRONMENT_RANGE_KEYS, ("61", "62", "63"))))
    selector.refresh()
    assert "Cannot peer: Dev (172.16.0.0/16) overlaps Stage" in selector.description.get()
    assert selector.optimize_button.instate(["disabled"])
    assert selector.optimize_button.grid_info()["column"] == 1
    before = copy.deepcopy(state)
    confirm = Mock(return_value=False)
    monkeypatch.setattr(wizard.messagebox, "askyesno", confirm)
    selector._optimize()
    assert state == before
    confirm.assert_not_called()
    selector._apply_defaults()
    assert state == draft()
    assert "estimated full projects: 7" in selector.description.get()
    assert selector.optimize_button.instate(["disabled"])


def test_tkinter_draft_watcher_updates_without_mode_selection(selector):
    selector.state["dev_cidr_range"] = "40"
    selector.after_cancel(selector._refresh_timer)
    selector._watch_draft()
    assert selector.description.get() == placement.preview_network_placement(selector.state)["guidance"]


def test_tkinter_confirmation_cannot_apply_a_stale_preview(selector, monkeypatch):
    # All representable peerable presets are optimal; simulate a proposed future
    # optimization to retain coverage of the UI's confirmation/race guard.
    preview = placement.preview_network_placement(draft())
    preview.update(can_optimize=True, optimization_changes={"dev_cidr_range": "192"})
    monkeypatch.setattr(wizard, "preview_network_placement", lambda state: preview)
    def change_while_confirming(*args, **kwargs):
        selector.state["common_vnet_cidr"] = "172.16.0.0/16"
        return True
    monkeypatch.setattr(wizard.messagebox, "askyesno", change_while_confirming)
    warning = Mock()
    monkeypatch.setattr(wizard.messagebox, "showwarning", warning)
    selector._optimize()
    assert selector.state["dev_cidr_range"] == "0"
    warning.assert_called_once()


@pytest.mark.parametrize("format_name", ["json", "yaml", "env"])
def test_peerable_consecutive_24_roundtrips_without_claiming_project_capacity(client, format_name):
    state = draft(common_vnet_cidr="172.16.XX.0/24",
                  dev_cidr_range="61", test_cidr_range="62", prod_cidr_range="63")
    exported = client.post("/api/v1/export", json={"format": format_name, "state": state})
    assert exported.status_code == 200
    imported = client.post("/api/v1/import", json={"format": format_name, "content": exported.json()["content"]})
    assert imported.status_code == 200 and imported.json()["warnings"] == []
    assert all(imported.json()["state"][key] == value for key, value in state.items())
    result = placement.preview_network_placement(imported.json()["state"])
    assert result["is_peerable"] and not result["can_optimize"]
    assert capacities(result) == [None, None, None]


@pytest.mark.parametrize("prefix", [16, 17, 18, 19, 20, 23, 24])
@pytest.mark.parametrize("starts", [("0", "0", "0"), ("0", "64", "128"),
                                   ("0", "16", "32"), ("61", "62", "63")])
def test_optimizer_never_recommends_overlap_or_changes_a_resolved_vnet(prefix, starts):
    state = draft(common_vnet_cidr=f"172.16.XX.0/{prefix}",
                  **dict(zip(policy.ENVIRONMENT_RANGE_KEYS, starts)))
    result = placement.preview_network_placement(state)
    if not result["is_peerable"]:
        assert not result["can_optimize"] and result["optimization_changes"] == {}
        return
    planned = {**state, **result["optimization_changes"]}
    assert not policy.network_validation_issues(planned)
    for key in policy.ENVIRONMENT_RANGE_KEYS:
        assert policy.resolved_common_networks(state, key)[0] == policy.resolved_common_networks(planned, key)[0]
