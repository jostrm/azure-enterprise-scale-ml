"""Graph release packaging is explicit, pinned, and part of the existing release."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_release_scaffold import DEPLOY, load
from test_runtime import AGENT, artifacts
from test_dual_graph import graph_snapshot


@pytest.fixture
def release_inputs(artifacts):
    wheels = artifacts / "wheels"
    wheels.mkdir()
    (wheels / "offline-test.whl").write_bytes(b"test")
    source = SimpleNamespace(commit="a" * 40, files=lambda prefixes: {"src/test.py": b"pass\n"})
    return source, source, DEPLOY.parent, artifacts / "release", wheels


def test_disabled_graph_release_packages_no_corpus(release_inputs):
    release = load("release")
    result = release.prepare_release(*release_inputs, graph_config=None)
    assert not any("graphify" in name for name in result["files"])
    assert "dual_graph" not in result["metadata"]
    assert release.verify_release(release_inputs[3]) == result


@pytest.mark.parametrize("config", [
    {},
    {"snapshot_root": "missing", "expected_snapshot_id": "main"},
    {"snapshot_root": "missing", "expected_snapshot_id": "a" * 64},
    {"snapshot_root": "missing", "expected_snapshot_id": "a" * 64,
     "allowed_scopes": ["scope"], "allow_source_access": True},
])
def test_graph_release_requires_enabled_valid_pinned_immutable_corpus(release_inputs, config):
    release = load("release")
    with pytest.raises(ValueError):
        release.prepare_release(*release_inputs, graph_config=config)
    assert not release_inputs[3].exists()


def test_launcher_does_not_enable_graph_from_release_metadata():
    launcher = load("launch")
    config = {}
    launcher.configure_graph(config, {"metadata": {"dual_graph": {"snapshot_id": "a" * 64}}})
    assert "dual_graph" not in config


def test_launcher_binds_explicit_graph_to_packaged_pin_only():
    launcher = load("launch")
    config = {"dual_graph": {
        "snapshot_root": "untrusted-local-override",
        "expected_snapshot_id": "a" * 64, "allowed_scopes": ["scope"], "allow_source_access": False,
    }}
    manifest = {"metadata": {"dual_graph": {"snapshot_id": "a" * 64}}}
    launcher.configure_graph(config, manifest, repository_root=Path("packaged"))
    assert Path(config["dual_graph"]["snapshot_root"]) == (
        Path("packaged") / "meta" / "graphify" / "snapshots" / ("a" * 64)
    )
    with pytest.raises(ValueError):
        launcher.configure_graph(config, {"metadata": {"dual_graph": {"snapshot_id": "b" * 64}}})
    with pytest.raises(ValueError):
        launcher.configure_graph(config, {"metadata": {}})


@pytest.fixture
def snapshot_release_inputs(release_inputs, graph_snapshot):
    source, api, mcp_root, output, wheels = release_inputs
    module_path = "usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/dual_graph.py"
    source = SimpleNamespace(
        commit=source.commit,
        files=lambda prefixes: {module_path: (AGENT / "aifactory_agent" / "dual_graph.py").read_bytes()},
    )
    root, _, snapshot_id = graph_snapshot
    config = {"snapshot_root": str(root), "expected_snapshot_id": snapshot_id,
              "allowed_scopes": ["scope"], "allow_source_access": False}
    return (source, api, mcp_root, output, wheels), config


def test_release_exports_only_verified_pinned_snapshot_and_runs_without_source(snapshot_release_inputs, graph_snapshot):
    from aifactory_agent.dual_graph import DualGraphStore

    inputs, config = snapshot_release_inputs
    root, _, snapshot_id = graph_snapshot
    (root / "snapshots" / snapshot_id / "private.txt").write_text("must not be packaged")
    release = load("release")
    result = release.prepare_release(*inputs, graph_config=config)
    packaged = inputs[3] / "repository" / "meta" / "graphify" / "snapshots" / snapshot_id
    assert not (packaged / "private.txt").exists()
    assert not (packaged.parent.parent / "current.json").exists()
    assert not (inputs[3] / "repository" / "src" / "code.py").exists()
    assert result["metadata"]["dual_graph"]["snapshot_id"] == snapshot_id
    assert DualGraphStore(packaged, expected_snapshot_id=snapshot_id).query("symbols")["results"]
    assert release.verify_release(inputs[3]) == result
    (packaged / "graph.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        release.verify_release(inputs[3])


def test_corrupt_graph_never_produces_a_release(snapshot_release_inputs, graph_snapshot):
    inputs, config = snapshot_release_inputs
    root, _, snapshot_id = graph_snapshot
    (root / "snapshots" / snapshot_id / "graph.json").write_text("{}")
    with pytest.raises(ValueError, match="validation"):
        load("release").prepare_release(*inputs, graph_config=config)
    assert not inputs[3].exists()


def test_pilot_graph_opt_in_does_not_broaden_legacy_identity_defaults():
    launcher = load("launch")
    config = {
        "factory": {"writes_enabled": False}, "actions": {"enabled_skills": []},
        "auth": {"grants": [{"permissions": ["factory.read", "graph.read"]}]},
    }
    policy = {"identities": [{"allowed_tools": ["graph_status"]}]}
    with pytest.raises(ValueError):
        launcher.validate_pilot(config, policy)
    config["dual_graph"] = {"snapshot_root": "reviewed", "allowed_scopes": ["scope"]}
    launcher.validate_pilot(config, policy)
    assert launcher.PILOT_TOOLS == {"factory_health", "factory_capabilities", "factory_skills"}
    policy["identities"][0]["allowed_tools"] = ["factory_execute_operation"]
    with pytest.raises(ValueError):
        launcher.validate_pilot(config, policy)


def test_graph_release_config_resolves_paths_relative_to_explicit_config(artifacts):
    release = load("release")
    path = artifacts / "agent.json"
    path.write_text(json.dumps({"dual_graph": {
        "snapshot_root": "snapshot", "expected_snapshot_id": "a" * 64, "allowed_scopes": ["scope"],
    }}))
    assert release.load_graph_config(path)["snapshot_root"] == str((artifacts / "snapshot").resolve())
