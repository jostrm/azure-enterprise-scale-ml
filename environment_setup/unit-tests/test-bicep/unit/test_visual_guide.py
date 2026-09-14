"""Check the committed VisualLearner export without requiring the external .NET library."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from base.config import REPO_ROOT


DOCS = Path(__file__).resolve().parents[1] / "docs"


class Page(HTMLParser):
    def __init__(self, source: str):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


def scene():
    return json.loads((DOCS / "ci-scene.json").read_text(encoding="utf-8"))


def test_html_embeds_the_exact_portable_visuallearner_scene():
    source = (DOCS / "ci-visual-guide.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="scene-data" type="application/json">([\s\S]*?)</script>', source)
    assert match
    assert json.loads(match[1]) == scene()
    assert "VisualLearnerPresentation.Normalize" in source
    assert "VisualLearnerMotion.FlowAt" in source
    assert "C:\\Users\\" not in source and "/mnt/c/Users/" not in source
    assert 'prefers-reduced-motion' in source
    assert "<noscript>" in source
    assert 'data-theme' in source


def test_export_counts_and_pair_examples_are_internally_consistent():
    export = scene()
    snapshot = export["snapshot"]
    templates = snapshot["templates"]
    counts = snapshot["counts"]
    assert snapshot["mode"] == "offline-validation"
    assert snapshot["status"] == "passed"
    assert re.fullmatch(r"[a-f0-9]{64}", snapshot["reportSha256"])
    assert counts["entrypoints"] == len(templates)
    assert counts["flagOccurrences"] == sum(item["flags"] for item in templates)
    assert counts["boundCases"] == sum(item["cases"] for item in templates)
    assert counts["pairStates"] == sum(2 * item["flags"] * (item["flags"] - 1) for item in templates)
    pair = export["pairDemo"]
    assert int(pair["fullAssignments"]) == 2 ** pair["flagCount"]
    assert {example["state"] for example in pair["examples"]} == {0, 1, 2, 3}
    assert "not every 2**N" in " ".join(snapshot["limits"])


def test_motion_export_has_real_nodes_bounded_progress_and_schematic_coordinates():
    export = scene()
    nodes = {node["id"]: node for node in export["nodes"]}
    assert len(nodes) == 5
    assert export["provenance"]["library"] == "AsomRecordsAB.VisualLearner"
    assert "NOT geographic" in export["provenance"]["coordinateSystem"]
    assert len(export["motionSamples"]) == 128
    for sample in export["motionSamples"]:
        assert 0 <= sample["progress"] <= 1
        assert sample["from"] in nodes and sample["to"] in nodes
        assert 0 <= sample["seconds"] < export["cycleSeconds"]


def test_visual_guide_has_no_external_runtime_dependencies_or_broken_local_links():
    page = Page((DOCS / "ci-visual-guide.html").read_text(encoding="utf-8"))
    ids = [attributes["id"] for _, attributes in page.elements if "id" in attributes]
    assert len(ids) == len(set(ids))
    for tag, attributes in page.elements:
        if tag == "script":
            assert "src" not in attributes
        if tag == "link":
            assert attributes.get("rel") != "stylesheet"
        address = attributes.get("href", attributes.get("src"))
        if not address:
            continue
        parsed = urlsplit(address)
        if parsed.scheme == "data":
            assert tag == "img" or tag == "link" and attributes.get("rel") == "icon"
            continue
        if parsed.scheme or parsed.netloc:
            assert tag == "a", "The guide must not load remote images, scripts or styles."
            continue
        if not parsed.path:
            assert not parsed.fragment or unquote(parsed.fragment) in ids
            continue
        path = (DOCS / unquote(parsed.path)).resolve()
        assert path.is_relative_to(REPO_ROOT)
        assert path.is_file(), address
    svg = ET.parse(DOCS / "ci-flow.svg")
    assert svg.getroot().tag == "{http://www.w3.org/2000/svg}svg"


def test_ci_does_not_require_the_optional_external_visuallearner_generator():
    for path in (REPO_ROOT / ".github" / "workflows" / "infrastructure-tests.yml",
                 DOCS.parent / "azure-pipelines.yml"):
        source = path.read_text(encoding="utf-8")
        assert "VisualLearnerProject" not in source
        assert "dotnet" not in source
    project = (DOCS / "generator" / "VisualGuide.csproj").read_text(encoding="utf-8")
    assert 'Include="$(VisualLearnerProject)"' in project
