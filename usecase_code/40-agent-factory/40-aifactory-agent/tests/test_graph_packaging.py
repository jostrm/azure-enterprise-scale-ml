import hashlib
import json
import tarfile
from unittest.mock import Mock

import pytest

import deploy
from aifactory_agent.config import Settings
from aifactory_agent.dual_graph import publish_snapshot
from test_skill_packaging import package_inputs


def snapshot(settings, *, fixed=True):
    root = settings.knowledge.repository_root
    source = root / "module.py"
    source.write_text("def pipeline(): pass\n", encoding="utf-8")
    graph_root = root / "meta" / "graphify"
    graph = {
        "directed": True, "multigraph": True, "graph": {"schema_version": 1},
        "nodes": [{"id": "pipeline", "label": "pipeline", "kind": "function",
                   "source_file": "module.py", "line": 1, "evidence": "static", "resolution": "resolved"}],
        "links": [],
    }
    metadata = {
        "source": {"revision": "a" * 40, "dirty": False},
        "tools": {}, "settings": {}, "exclusions": [], "coverage": {},
        "inputs": [{"path": "module.py", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
        "selection": {"roots": ["."], "extensions": [".py"], "exclude_dirs": ["meta"],
                      "exclude_globs": []},
    }
    published = publish_snapshot(graph_root, graph, {"design.md": "# Design\nPipeline rationale."}, metadata)
    identity = published["snapshot_id"]
    data = settings.model_dump(mode="json")
    data["dual_graph"] = {
        "snapshot_root": str(graph_root / "snapshots" / identity if fixed else graph_root),
        "expected_snapshot_id": identity, "allowed_scopes": ["project001-dev"],
    }
    return Settings.model_validate(data), identity, source


def test_enabled_graph_packages_only_verified_immutable_snapshot_no_checkout(package_inputs, monkeypatch):
    settings, destination, _ = package_inputs
    settings, identity, _ = snapshot(settings)
    (settings.dual_graph.snapshot_root / "notes" / "untracked.md").write_text("Not approved.", encoding="utf-8")
    monkeypatch.setattr(deploy.subprocess, "run", Mock(side_effect=AssertionError("No checkout or command execution")))
    deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    with tarfile.open(destination) as archive:
        names = archive.getnames()
        prefix = f"dual_graph/snapshots/{identity}/"
        assert prefix + "manifest.json" in names
        assert prefix + "graph.json" in names
        assert prefix + "notes/design.md" in names
        assert prefix + "notes/untracked.md" not in names
        assert not any(name.endswith("current.json") or "/.git/" in name for name in names)
        config = json.load(archive.extractfile("config.json"))
        assert config["dual_graph"]["snapshot_root"] == "/tmp/agent-app/" + prefix.rstrip("/")
        assert config["dual_graph"]["expected_snapshot_id"] == identity
        assert config["dual_graph"]["allow_source_access"] is False
        assert str(settings.dual_graph.snapshot_root) not in json.dumps(config)


@pytest.mark.parametrize("mutation", ["corrupt", "partial", "mismatched", "unpinned"])
def test_enabled_graph_fail_closed_before_creating_bundle(package_inputs, mutation):
    settings, destination, _ = package_inputs
    settings, _, _ = snapshot(settings)
    if mutation == "corrupt":
        (settings.dual_graph.snapshot_root / "graph.json").write_text("{}", encoding="utf-8")
    elif mutation == "partial":
        (settings.dual_graph.snapshot_root / "notes" / "design.md").unlink()
    else:
        data = settings.model_dump(mode="json")
        data["dual_graph"]["expected_snapshot_id"] = "0" * 64 if mutation == "mismatched" else None
        settings = Settings.model_validate(data)
    with pytest.raises(RuntimeError, match="[Gg]raph|snapshot"):
        deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    assert not destination.exists()


def test_moving_graph_root_must_be_fresh_but_fixed_snapshot_is_immutable(package_inputs):
    settings, destination, _ = package_inputs
    settings, identity, source = snapshot(settings, fixed=False)
    source.write_text("def changed(): pass\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="fresh|stale"):
        deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    data = settings.model_dump(mode="json")
    data["dual_graph"]["snapshot_root"] = str(settings.dual_graph.snapshot_root / "snapshots" / identity)
    deploy.package(Settings.model_validate(data), "11111111-1111-4111-8111-111111111111", destination)
    assert destination.is_file()


def test_broad_corpus_packaging_excludes_graph_and_test_material(package_inputs):
    settings, destination, _ = package_inputs
    settings, _, _ = snapshot(settings)
    root = settings.knowledge.repository_root
    for name in ("tests/guide.md", "docs/testdata/data.md", "docs/evals/cases.md", "documentation/guide.md"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Docs\nSample.", encoding="utf-8")
    settings = settings.model_copy(update={"dual_graph": None, "knowledge": settings.knowledge.model_copy(update={
        "includes": ["**/*.md"], "excludes": [],
    })})
    deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    with tarfile.open(destination) as archive:
        names = archive.getnames()
    assert "repository/documentation/guide.md" in names
    assert not any(name.startswith(("repository/meta/graphify/", "repository/tests/",
                                    "repository/docs/testdata/", "repository/docs/evals/")) for name in names)
