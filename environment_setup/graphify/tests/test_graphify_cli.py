import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "generate.py"
spec = importlib.util.spec_from_file_location("aifactory_graph_generate_cli", MODULE)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_installed_graphify_static_cli_preserves_calls_and_inheritance(tmp_path):
    stage = tmp_path / "source"
    (stage / "bootstrap").mkdir(parents=True)
    source = ("from pathlib import Path\nclass Base: pass\nclass Child(Base): pass\n"
              "def leaf(): return Path('.')\ndef caller(): return leaf()\n"
              "class Worker:\n    def execute(self): return leaf()\n")
    (stage / "bootstrap" / "example.py").write_text(source, encoding="utf-8")
    out = tmp_path / "result"
    generator.run_graphify(generator.graphify_commands(stage, out)[0], tmp_path)
    raw = json.loads((out / "graphify-out" / "graph.json").read_text(encoding="utf-8"))
    assert raw["nodes"]
    relations = {edge["relation"] for edge in raw.get("edges", raw.get("links", []))}
    assert "calls" in relations
    assert any("inherit" in relation or "extend" in relation for relation in relations)
    graph, _ = generator.extract_adapters(stage)
    assert generator.merge_upstream(graph, raw, stage) > 0
    assert any(edge["source"] == "bootstrap/example.py::function:caller"
               and edge["target"] == "bootstrap/example.py::function:leaf"
               and edge["relation"] == "calls" for edge in graph["links"])
    assert any(edge["source"] == "bootstrap/example.py::function:Worker.execute"
               and edge["target"] == "bootstrap/example.py::function:leaf"
               and edge["relation"] == "calls" for edge in graph["links"])
    assert all(not str(tmp_path).replace("\\", "/") in json.dumps(item).replace("\\\\", "/")
               for item in graph["nodes"])
