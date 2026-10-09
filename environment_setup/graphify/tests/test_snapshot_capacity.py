import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"))
from aifactory_agent.dual_graph import DualGraphStore, publish_snapshot


def test_repository_scale_graph_publishes_without_unbounding_runtime(tmp_path):
    # The measured repository adapters alone exceed 30 MiB before native calls/imports.
    graph = {
        "directed": True, "multigraph": True, "graph": {"schema_version": 1},
        "nodes": [{"id": f"symbol:{index}", "label": "x" * 1024, "kind": "function",
                   "source_file": "source.py", "evidence": "static", "resolution": "resolved"}
                  for index in range(30000)],
        "links": [],
    }
    metadata = {"source": {"revision": "fixture", "dirty": False}, "tools": {},
                "settings": {}, "exclusions": [], "coverage": {}, "inputs": []}
    result = publish_snapshot(tmp_path / "graph", graph, {"Index.md": "# Architecture\n"}, metadata)
    assert result["snapshot_id"]
    status = DualGraphStore(tmp_path / "graph").query("status")
    assert status["results"][0]["nodes"] == 30000
