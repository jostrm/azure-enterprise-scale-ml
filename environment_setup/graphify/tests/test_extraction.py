import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "generate.py"
spec = importlib.util.spec_from_file_location("aifactory_graph_generate", MODULE)
generator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = generator
spec.loader.exec_module(generator)


def fixture(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def relations(graph):
    return {(edge["source"], edge["relation"], edge["target"]) for edge in graph["links"]}


def test_selection_excludes_sensitive_generated_and_nonallowlisted_config(tmp_path):
    for path in [
        "bootstrap/main.py", "bootstrap/config.local.json", "bootstrap/.env",
        "bootstrap/.venv/secret.py", "bootstrap/.workload-test-42/private.py",
        "bootstrap/customer.json", "bootstrap/data/data.py", "meta/graphify/graph.json",
        "usecase_code/model/mlruns/code.py", "bootstrap/example.schema.json",
    ]:
        fixture(tmp_path, path, "{}")
    selected, excluded = generator.select_inputs(tmp_path)
    assert set(selected) == {"bootstrap/main.py", "bootstrap/example.schema.json"}
    assert excluded


def test_notebook_outputs_and_metadata_never_enter_staging_or_input_identity(tmp_path):
    notebook = {"cells": [{"cell_type": "code", "source": ["from train import run\n", "run()"],
                           "outputs": [{"text": ["PRIVATE-DATA"]}], "metadata": {"token": "PRIVATE"}},
                          {"cell_type": "markdown", "source": ["PRIVATE MARKDOWN"]}],
                "metadata": {"credentials": "PRIVATE"}}
    path = fixture(tmp_path, "usecase_code/sample.ipynb", json.dumps(notebook))
    selected, _ = generator.select_inputs(tmp_path)
    assert "PRIVATE" not in selected[path.relative_to(tmp_path).as_posix()]
    before = generator.input_digest(path, selected[path.relative_to(tmp_path).as_posix()])
    notebook["cells"][0]["outputs"] = [{"text": ["CHANGED PRIVATE DATA"]}]
    path.write_text(json.dumps(notebook), encoding="utf-8")
    selected2, _ = generator.select_inputs(tmp_path)
    assert generator.input_digest(path, selected2[path.relative_to(tmp_path).as_posix()]) == before


def test_bicep_parameters_modules_outputs_and_dependency_direction(tmp_path):
    fixture(tmp_path, "environment_setup/main.bicep", """
param location string = 'swedencentral'
module store './storage.bicep' = {
  name: 'storage'
  params: { location: location }
}
resource app 'Microsoft.Web/sites@2024-01-01' = {
  name: 'web'
  location: location
  dependsOn: [store]
}
output endpoint string = app.properties.defaultHostName
""")
    fixture(tmp_path, "environment_setup/storage.bicep", "param location string\n")
    graph, report = generator.extract_adapters(tmp_path)
    edges = relations(graph)
    p = "environment_setup/main.bicep"
    assert (f"{p}::module:store", "references", f"{p}::param:location") in edges
    assert (f"{p}::module:store", "module_source", "environment_setup/storage.bicep") in edges
    assert (f"{p}::resource:app", "depends_on", f"{p}::module:store") in edges
    assert (f"{p}::output:endpoint", "references", f"{p}::resource:app") in edges
    assert report["limitations"]


def test_workflows_preserve_conditions_and_do_not_claim_acyclic(tmp_path):
    fixture(tmp_path, ".github/workflows/build.yml", """
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: python bootstrap/main.py
  deploy:
    needs: [build]
    if: github.ref == 'refs/heads/main'
    steps:
      - run: az deployment group create --template-file environment_setup/main.bicep
""")
    fixture(tmp_path, "bootstrap/main.py", "pass\n")
    fixture(tmp_path, "environment_setup/main.bicep", "param scope string\n")
    graph, _ = generator.extract_adapters(tmp_path)
    p = ".github/workflows/build.yml"
    assert (f"{p}::job:deploy", "depends_on", f"{p}::job:build") in relations(graph)
    node = next(node for node in graph["nodes"] if node["id"] == f"{p}::job:deploy")
    assert node["conditional"] is True
    assert node["topology"] == "declared_workflow"
    assert any(e["target"] == "environment_setup/main.bicep" and e["relation"] == "invokes" for e in graph["links"])


def test_ado_template_dependency_and_parameter_binding(tmp_path):
    fixture(tmp_path, "environment_setup/pipeline.yml", """
stages:
  - stage: Build
    jobs:
      - job: Train
        steps:
          - template: steps.yml
            parameters:
              projectNumber: $(PROJECT)
  - stage: Deploy
    dependsOn: Build
    condition: succeeded()
""")
    fixture(tmp_path, "environment_setup/steps.yml", "parameters:\n  - name: projectNumber\n    type: string\n")
    graph, _ = generator.extract_adapters(tmp_path)
    p = "environment_setup/pipeline.yml"
    assert (f"{p}::stage:Deploy", "depends_on", f"{p}::stage:Build") in relations(graph)
    assert any(e["relation"] == "template" and e["target"] == "environment_setup/steps.yml" for e in graph["links"])
    assert any(e["relation"] == "passes_parameter" and e["target"].endswith("::parameter:projectNumber") for e in graph["links"])


def test_json_schema_and_literal_configuration_consumers(tmp_path):
    fixture(tmp_path, "bootstrap/deployment.schema.json",
            '{"properties":{"scope":{"type":"object","properties":{"project":{"type":"string"}}}}}')
    fixture(tmp_path, "bootstrap/deploy.py",
            "from pathlib import Path\nimport json\ncfg = json.loads(Path('deployment.schema.json').read_text())\n")
    graph, _ = generator.extract_adapters(tmp_path)
    assert any(n["kind"] == "config_key" and n["label"] == "scope.project" for n in graph["nodes"])
    assert any(e["target"] == "bootstrap/deployment.schema.json" and e["relation"] == "references_file" for e in graph["links"])


def test_stable_output_and_deleted_inputs(tmp_path):
    path = fixture(tmp_path, "bootstrap/run.py", "def run():\n    dynamic = globals()\n")
    first, report = generator.extract_adapters(tmp_path)
    second, _ = generator.extract_adapters(tmp_path)
    assert first == second
    assert report["unresolved_references"] >= 0
    path.unlink()
    third, _ = generator.extract_adapters(tmp_path)
    assert not third["nodes"]


def test_escape_and_symlink_not_followed(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.py")
    outside.write_text("PRIVATE = 1")
    try:
        (tmp_path / "bootstrap").mkdir()
        (tmp_path / "bootstrap" / "link.py").symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit creating test symlinks")
    selected, _ = generator.select_inputs(tmp_path)
    assert selected == {}


def test_static_runner_rejects_network_and_semantic_flags():
    assert generator.graphify_commands(Path("stage"), Path("out")) == [
        ["extract", "stage", "--code-only", "--no-dedup", "--no-cluster", "--out", "out"],
        ["cluster-only", "out", "--no-label"],
    ]


def test_forward_parameter_node_keeps_source_line(tmp_path):
    fixture(tmp_path, "environment_setup/a.bicep",
            "param location string\nmodule target './z.bicep' = { params: { location: location } }\n")
    fixture(tmp_path, "environment_setup/z.bicep",
            "param location string\noutput region string = location\n")
    graph, _ = generator.extract_adapters(tmp_path)
    parameter = next(n for n in graph["nodes"] if n["id"] == "environment_setup/z.bicep::param:location")
    assert parameter["line"] == 1


def test_python_methods_are_qualified_and_config_citations_are_real_lines(tmp_path):
    fixture(tmp_path, "bootstrap/main.py",
            "class One:\n    def run(self): pass\nclass Two:\n    def run(self): pass\n\nCONFIG = 'schema.schema.json'\n")
    fixture(tmp_path, "bootstrap/schema.schema.json", "{}")
    graph, _ = generator.extract_adapters(tmp_path)
    assert {"bootstrap/main.py::function:One.run", "bootstrap/main.py::function:Two.run"} <= {n["id"] for n in graph["nodes"]}
    edges = [e for e in graph["links"] if e["relation"] == "references_file" and e["source_file"] == "bootstrap/main.py"]
    assert edges and all(e["line"] == 6 for e in edges)


def test_upstream_parallel_edges_direction_and_portable_ids():
    def imported(root):
        graph = {"nodes": [{"id": "bootstrap/a.py", "kind": "file"}], "links": []}
        raw = {"nodes": [{"id": str(root / "bootstrap" / "a.py") + ":A", "label": "A", "source_file": str(root / "bootstrap" / "a.py")},
                         {"id": "B", "label": "B", "source_file": str(root / "bootstrap" / "a.py")}],
               "edges": [{"source": str(root / "bootstrap" / "a.py") + ":A", "target": "B", "relation": "calls", "confidence": "EXTRACTED"},
                         {"source": str(root / "bootstrap" / "a.py") + ":A", "target": "B", "relation": "imports", "confidence": "INFERRED"}]}
        generator.merge_upstream(graph, raw, root)
        return graph
    first = imported(Path("C:\\one") if sys.platform == "win32" else Path("/one"))
    second = imported(Path("C:\\two") if sys.platform == "win32" else Path("/two"))
    assert first == second
    assert {"calls", "imports"} <= {e["relation"] for e in first["links"]}
    assert any(e["evidence"] == "inferred" for e in first["links"])


def test_input_hash_refuses_concurrent_code_edit(tmp_path):
    path = fixture(tmp_path, "bootstrap/code.py", "before = 1\n")
    selected, _ = generator.select_inputs(tmp_path)
    path.write_text("after = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed"):
        generator.input_digest(path, selected["bootstrap/code.py"])


def test_injected_protocol_reference_has_resolved_source(tmp_path):
    fixture(tmp_path, "bootstrap/ports.py", "from typing import Protocol\nclass KnowledgePort(Protocol): pass\n")
    fixture(tmp_path, "bootstrap/service.py", "from .ports import KnowledgePort\ndef compose(knowledge: KnowledgePort): pass\n")
    graph, _ = generator.extract_adapters(tmp_path)
    assert ("bootstrap/service.py::function:compose", "uses_interface",
            "bootstrap/ports.py::class:KnowledgePort") in relations(graph)


def test_generated_notebook_links_to_generator_and_scenario(tmp_path):
    base = "usecase_code/50-ml-model-factory"
    fixture(tmp_path, base + "/accelerator/src/ml_model_factory/examples.py", "pass\n")
    fixture(tmp_path, base + "/accelerator/src/ml_model_factory/usecases.py", "pass\n")
    fixture(tmp_path, base + "/user-config/model/scenarios/demo.json", '{"task":"classification"}')
    fixture(tmp_path, base + "/usecase-type/batch/notebook/demo.ipynb",
            json.dumps({"cells": [{"cell_type": "code", "source":
                'SCENARIO = ROOT / "user-config" / "model" / "scenarios" / "demo.json"\n'}]}))
    graph, _ = generator.extract_adapters(tmp_path)
    assert any(e["relation"] == "generated_from" and e["target"].endswith("examples.py") for e in graph["links"])
    assert any(e["relation"] == "configured_by" and e["target"].endswith("demo.json") for e in graph["links"])


def test_html_view_groups_by_source_without_mutating_structural_graph():
    graph = {"nodes": [{"id": "a", "source_file": "bootstrap/main.py"},
                       {"id": "b", "source_file": "mcp/server.py"}], "links": [], "graph": {}}
    view, labels = generator.html_projection(graph)
    assert "community" not in graph["nodes"][0]
    assert view["nodes"][0]["community"] != view["nodes"][1]["community"]
    assert set(labels.values()) == {"bootstrap", "mcp"}


def test_bicep_interpolation_is_reference_but_object_keys_are_not(tmp_path):
    fixture(tmp_path, "environment_setup/main.bicep", """
param location string
param suffix string
resource app 'Microsoft.Web/sites@2024-01-01' = {
  name: 'web-${suffix}'
  location: 'swedencentral'
}
""")
    graph, _ = generator.extract_adapters(tmp_path)
    p = "environment_setup/main.bicep"
    assert (f"{p}::resource:app", "references", f"{p}::param:suffix") in relations(graph)
    assert (f"{p}::resource:app", "references", f"{p}::param:location") not in relations(graph)
    assert next(n for n in graph["nodes"] if n["id"] == f"{p}::param:location")["line"] == 2


def test_real_selection_contract_is_fresh_and_detects_new_code(tmp_path):
    sys.path.insert(0, str(MODULE.parents[2] / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"))
    from aifactory_agent.dual_graph import DualGraphStore, publish_snapshot
    fixture(tmp_path, "00-start.sh", "echo starting\n")
    fixture(tmp_path, "bootstrap/app.py", "def main(): pass\n")
    fixture(tmp_path, "bootstrap/requirements.txt", "httpx==0.28.1\n")
    fixture(tmp_path, "bootstrap/private.local.json", '{"token":"private"}')
    fixture(tmp_path, "bootstrap/extra.md", "not in structural corpus")
    note = "# Architecture\n"
    fixture(tmp_path, "documentation/architecture/Index.md", note)
    selected, excluded = generator.select_inputs(tmp_path)
    graph, _ = generator.Builder(selected).build()
    metadata = {"source": {"revision": "fixture", "dirty": False},
                "tools": {}, "settings": {}, "exclusions": excluded, "coverage": {},
                "inputs": [{"path": p, "sha256": generator.input_digest(tmp_path / p, content)}
                           for p, content in selected.items()] + [
                               {"path": "documentation/architecture/Index.md",
                                "sha256": generator.digest((tmp_path / "documentation/architecture/Index.md").read_bytes())}],
                "selection": generator.selection_metadata(excluded)}
    root = tmp_path / "meta" / "graphify"
    publish_snapshot(root, graph, {"Index.md": note}, metadata)
    store = DualGraphStore(root, repository_root=tmp_path)
    assert store.query("status")["freshness"]["status"] == "fresh"
    fixture(tmp_path, "bootstrap/new.py", "pass\n")
    assert store.query("status")["freshness"]["status"] == "stale"


def test_upstream_slugged_temporary_module_paths_are_portable():
    def imported(directory):
        stage = Path(directory)
        files = ["bootstrap/main.py", "bootstrap/__init__.py"]
        graph = {"graph": {}, "nodes": [
            {"id": path, "label": Path(path).name, "kind": "file", "source_file": path}
            for path in files], "links": []}
        slug = generator.re.sub(r"[^a-z0-9]+", "_", str(stage / "bootstrap" / "__init__.py").casefold()).strip("_")
        raw = {"nodes": [{"id": "main", "label": "main.py", "source_file": "bootstrap/main.py"}],
               "edges": [{"source": "main", "target": slug, "relation": "imports_from", "confidence": "EXTRACTED"}]}
        generator.merge_upstream(graph, raw, stage)
        return graph
    first = imported("C:\\first\\source" if sys.platform == "win32" else "/first/source")
    second = imported("C:\\second\\source" if sys.platform == "win32" else "/second/source")
    assert first == second
    assert any(e["target"] == "bootstrap/__init__.py" and e["relation"] == "imports_from"
               for e in first["links"])


def test_upstream_ambiguous_import_hashes_do_not_define_snapshot_identity():
    def imported(opaque):
        graph = {"graph": {}, "nodes": [
            {"id": "bootstrap/main.py", "label": "main.py", "kind": "file", "source_file": "bootstrap/main.py"}],
                 "links": []}
        raw = {"nodes": [{"id": "main", "label": "main.py", "source_file": "bootstrap/main.py"}],
               "edges": [{"source": "main", "target": "ambiguous_python_import_" + opaque,
                          "relation": "imports_from", "source_location": "L10", "confidence": "EXTRACTED"}]}
        generator.merge_upstream(graph, raw, Path("stage"))
        return graph
    first, second = imported("112233445566"), imported("aabbccddeeff")
    assert first == second
    edge = next(e for e in first["links"] if e["relation"] == "imports_from")
    assert edge["resolution"] == "unresolved"
    assert edge["line"] == 10
