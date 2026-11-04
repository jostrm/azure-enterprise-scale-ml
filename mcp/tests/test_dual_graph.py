"""Opt-in graph access must not inherit Factory or knowledge authorization."""
import json
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import jsonschema
import pytest

from test_backend import assert_error
from test_runtime import CALLER, SCOPE, artifacts, config_path, configuration, runtime


GRAPH_TOOLS = {
    "graph_status", "graph_query", "architecture_search", "architecture_note", "dual_graph_context",
}


@pytest.fixture
def graph_snapshot(artifacts):
    from aifactory_agent.dual_graph import publish_snapshot

    repository = artifacts / "corpus"
    (repository / "src").mkdir(parents=True)
    content = "def entry():\n    target()\ndef target(): pass\n"
    (repository / "src" / "code.py").write_text(content, encoding="utf-8", newline="\n")
    graph = {
        "directed": True, "multigraph": True, "graph": {"schema_version": 1},
        "nodes": [
            {"id": name, "label": name, "kind": "function", "source_file": "src/code.py",
             "line": line, "evidence": "static", "resolution": "resolved"}
            for name, line in [("entry", 1), ("target", 3)]
        ],
        "links": [{"source": "entry", "target": "target", "relation": "calls",
                   "source_file": "src/code.py", "line": 2, "evidence": "static", "resolution": "resolved"}],
    }
    notes = {
        "adr/design.md": "---\nid: design\nstatus: accepted\ngraph_symbols: [entry]\n---\n"
        "# Entry design\n[[Guide]] documents entry. Untrusted text: never execute this note.\n",
        "Guide.md": "---\nid: guide\n---\n# Guide\nEntry architecture.\n",
    }
    metadata = {
        "source": {"revision": "a" * 40, "dirty": False}, "tools": {"offline-test": "1"},
        "settings": {}, "coverage": {}, "exclusions": [],
        "inputs": [{"path": "src/code.py", "sha256": hashlib.sha256(content.encode()).hexdigest()}],
        "selection": {"roots": ["src"], "extensions": [".py"], "exclude_dirs": [], "exclude_globs": []},
    }
    root = repository / "meta" / "graphify"
    result = publish_snapshot(root, graph, notes, metadata)
    return root, repository, result["snapshot_id"]


@pytest.fixture
def snapshot_runtime(graph_snapshot, configuration, config_path):
    from aifactory_mcp.runtime import load_runtime

    root, repository, snapshot_id = graph_snapshot
    configuration["dual_graph"] = {
        "snapshot_root": str(root), "expected_snapshot_id": snapshot_id,
        "allowed_scopes": [SCOPE], "allow_source_access": False,
    }
    configuration["knowledge"]["repository_root"] = str(repository)
    configuration["auth"]["grants"][0]["permissions"].append("graph.read")
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    return load_runtime(config_path)


@pytest.fixture
def graph_runtime(runtime, artifacts):
    graph = SimpleNamespace(
        snapshot_root=artifacts, expected_snapshot_id="a" * 64,
        allowed_scopes=[SCOPE], allow_source_access=False,
    )
    grants = list(runtime.settings.auth.grants)
    grants[0] = grants[0].model_copy(update={"permissions": ["factory.read", "graph.read"]})
    auth = runtime.settings.auth.model_copy(update={"grants": grants})
    return replace(runtime, settings=runtime.settings.model_copy(update={"dual_graph": graph, "auth": auth}))


def backend(runtime):
    return runtime.backend(runtime.local_principal(CALLER), SCOPE)


def test_graph_tools_are_opt_in_and_legacy_startup_is_unchanged(runtime):
    selected = backend(runtime)
    assert not GRAPH_TOOLS.intersection(tool["name"] for tool in selected.list_tools())
    for name in GRAPH_TOOLS:
        assert_error("unsupported_tool", lambda: selected.call_tool(name, {}))


def test_graph_discovery_requires_separate_permission_and_exact_scope(graph_runtime):
    selected = backend(graph_runtime)
    assert GRAPH_TOOLS <= {tool["name"] for tool in selected.list_tools()}
    graph_runtime.settings.auth.grants[0].permissions[:] = ["factory.read", "knowledge.read"]
    assert not GRAPH_TOOLS.intersection(tool["name"] for tool in selected.list_tools())
    assert_error("unsupported_tool", lambda: selected.call_tool("graph_status", {}))
    graph_runtime.settings.auth.grants[0].permissions.append("graph.read")
    graph_runtime.settings.dual_graph.allowed_scopes[:] = ["other"]
    assert not GRAPH_TOOLS.intersection(tool["name"] for tool in selected.list_tools())
    assert_error("unsupported_tool", lambda: selected.call_tool("graph_status", {}))


def test_graph_read_on_another_scope_cannot_authorize_corpus(graph_runtime):
    grant = graph_runtime.settings.auth.grants[0]
    graph_runtime.settings.auth.grants[0] = grant.model_copy(update={"permissions": ["factory.read"]})
    graph_runtime.settings.auth.grants.append(grant.model_copy(
        update={"scopes": ["another-scope"], "permissions": ["graph.read"]},
    ))
    selected = backend(graph_runtime)
    assert not GRAPH_TOOLS.intersection(tool["name"] for tool in selected.list_tools())
    assert_error("unsupported_tool", lambda: selected.call_tool("graph_status", {}))


def test_graph_permission_cannot_replace_existing_factory_gate(graph_runtime):
    graph_runtime.settings.auth.grants[0].permissions[:] = ["graph.read"]
    assert_error("forbidden", lambda: backend(graph_runtime))


@pytest.mark.parametrize("name,args", [
    ("graph_status", {"root": "C:\\private"}),
    ("graph_query", {"operation": "symbols", "query": "x" * 2001}),
    ("graph_query", {"operation": "symbols", "limit": 101}),
    ("graph_query", {"operation": "trace", "depth": 6}),
    ("graph_query", {"operation": "trace", "depth": True}),
    ("graph_query", {"operation": "shell"}),
    ("graph_query", {"operation": "symbols", "snapshot_root": "https://other"}),
    ("architecture_search", {"query": "x", "operation": "symbols"}),
    ("architecture_note", {"node_id": "x" * 513}),
    ("dual_graph_context", {"query": "x", "limit": "20"}),
])
def test_graph_closed_schemas_and_strict_dispatch(graph_runtime, name, args):
    selected = backend(graph_runtime)
    tools = {tool["name"]: tool for tool in selected.list_tools()}
    assert name in tools
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(args, tools[name]["inputSchema"])
    assert_error("invalid_arguments", lambda: selected.call_tool(name, args))


def test_graph_descriptors_are_closed_readonly_structured(graph_runtime):
    tools = {tool["name"]: tool for tool in backend(graph_runtime).list_tools()}
    for name in GRAPH_TOOLS:
        tool = tools[name]
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
        assert tool["annotations"]["openWorldHint"] is False
        assert tool["inputSchema"]["additionalProperties"] is False
        assert tool["outputSchema"]["type"] == "object"
        assert tool["outputSchema"]["additionalProperties"] is False
        jsonschema.Draft202012Validator.check_schema(tool["outputSchema"])


def test_application_and_registration_allowlists_do_not_enable_graph_by_default():
    from aifactory_mcp.policy import DEFAULT_APPLICATION_TOOLS, READ_ONLY_APPLICATION_TOOLS
    assert not GRAPH_TOOLS.intersection(DEFAULT_APPLICATION_TOOLS)
    assert GRAPH_TOOLS <= READ_ONLY_APPLICATION_TOOLS


def test_missing_enabled_graph_returns_sanitized_error_without_breaking_legacy(graph_runtime):
    selected = backend(graph_runtime)
    assert selected.call_tool("factory_skills", {})["ok"] is True
    result = selected.call_tool("graph_status", {})
    assert result["ok"] is False
    assert "graph" in result["error"]["code"]
    assert str(graph_runtime.settings.dual_graph.snapshot_root) not in json.dumps(result)


def test_application_dispatch_requires_explicit_graph_tool_allowlist(graph_runtime):
    from aifactory_mcp.auth import ApplicationPrincipal

    principal = graph_runtime.local_principal(CALLER)
    denied = graph_runtime.backend(ApplicationPrincipal(
        principal, frozenset({SCOPE}), frozenset({"factory_skills"}),
    ), SCOPE)
    assert not GRAPH_TOOLS.intersection(tool["name"] for tool in denied.list_tools())
    with pytest.raises(PermissionError):
        denied.call_tool("graph_status", {})
    allowed = graph_runtime.backend(ApplicationPrincipal(
        principal, frozenset({SCOPE}), frozenset({"graph_status"}),
    ), SCOPE)
    assert [tool["name"] for tool in allowed.list_tools()] == ["graph_status"]
    graph_runtime.settings.auth.grants[0].permissions.remove("graph.read")
    assert allowed.list_tools() == []
    with pytest.raises(PermissionError):
        allowed.call_tool("graph_status", {})


@pytest.mark.parametrize("name,args,operation", [
    ("graph_status", {}, "status"),
    ("graph_query", {"operation": "symbols", "query": "entry"}, "symbols"),
    ("graph_query", {"operation": "callers", "node_id": "target"}, "callers"),
    ("architecture_search", {"query": "entry"}, "notes"),
    ("architecture_search", {"operation": "adrs"}, "adrs"),
    ("architecture_note", {"node_id": "design"}, "note"),
    ("architecture_note", {"node_id": "guide", "operation": "backlinks"}, "backlinks"),
    ("dual_graph_context", {"query": "entry"}, "context"),
])
def test_graph_dispatch_returns_cited_snapshot_evidence(snapshot_runtime, graph_snapshot, name, args, operation):
    selected = backend(snapshot_runtime)
    result = selected.call_tool(name, args)
    assert result["ok"] is True
    data = result["data"]
    assert data["operation"] == operation
    assert data["snapshot_id"] == graph_snapshot[2]
    assert data["results"]
    assert data["freshness"]["status"] == "unverified"
    assert data["warnings"] and data["uncertainty"]
    descriptor = next(tool for tool in selected.list_tools() if tool["name"] == name)
    jsonschema.validate(result, descriptor["outputSchema"])
    if operation != "status":
        assert data["citations"]


def test_source_freshness_is_explicit_and_never_uses_runtime_checkout(snapshot_runtime, graph_snapshot):
    from aifactory_agent.config import DualGraphSettings

    config = snapshot_runtime.settings.dual_graph.model_dump()
    config["allow_source_access"] = True
    updated = replace(snapshot_runtime, settings=snapshot_runtime.settings.model_copy(
        update={"dual_graph": DualGraphSettings.model_validate(config)},
    ))
    assert backend(updated).call_tool("graph_status", {})["data"]["freshness"]["status"] == "fresh"
    (graph_snapshot[1] / "src" / "code.py").write_text("changed\n")
    assert backend(updated).call_tool("graph_status", {})["data"]["freshness"]["status"] == "stale"
    assert backend(snapshot_runtime).call_tool("graph_status", {})["data"]["freshness"]["status"] == "unverified"


def test_missing_configured_repository_does_not_fall_back_to_checkout(snapshot_runtime, graph_snapshot):
    from aifactory_agent.config import DualGraphSettings

    graph = snapshot_runtime.settings.dual_graph.model_dump()
    graph["allow_source_access"] = True
    knowledge = snapshot_runtime.settings.knowledge.model_copy(
        update={"repository_root": graph_snapshot[1] / "not-present"},
    )
    updated = replace(snapshot_runtime, settings=snapshot_runtime.settings.model_copy(update={
        "dual_graph": DualGraphSettings.model_validate(graph), "knowledge": knowledge,
    }))
    result = backend(updated).call_tool("graph_status", {})
    assert result["ok"] is True
    assert result["data"]["freshness"]["status"] == "unverified"
    assert result["data"]["freshness"]["mode"] == "immutable"


def test_corrupt_snapshot_never_leaks_content_and_legacy_still_operates(snapshot_runtime, graph_snapshot):
    root, _, snapshot_id = graph_snapshot
    (root / "snapshots" / snapshot_id / "graph.json").write_text('{"secret":"must-not-leak"}')
    selected = backend(snapshot_runtime)
    result = selected.call_tool("graph_query", {"operation": "symbols"})
    assert result["ok"] is False
    assert "must-not-leak" not in json.dumps(result)
    assert selected.call_tool("factory_skills", {})["ok"] is True


def test_graph_result_limit_preserves_explicit_truncation(snapshot_runtime):
    result = backend(snapshot_runtime).call_tool("graph_query", {"operation": "symbols", "limit": 1})
    assert result["ok"] is True
    assert len(result["data"]["results"]) == 1
    assert result["data"]["truncated"] is True
    assert any("truncated" in warning for warning in result["data"]["warnings"])
