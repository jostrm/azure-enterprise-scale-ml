"""Checks for the onion generator (standard library only): python -m unittest test_onion.py"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import make_onion_svg as onion

HERE = Path(__file__).resolve().parent
SVG = "{http://www.w3.org/2000/svg}"


class OnionData(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(onion.DATA.read_text(encoding="utf-8"))

    def test_every_scenario_has_a_time_for_every_layer_with_a_known_kind(self):
        ids = ["consumer"] + [layer["id"] for layer in self.data["layers"]]
        for scenario in self.data["scenarios"]:
            self.assertEqual(sorted(scenario["times"]), sorted(ids), scenario["id"])
            for time in scenario["times"].values():
                self.assertIn(time["kind"], onion.KIND)
                self.assertLessEqual(time["min"], time["max"])
                for key in (time.get("evidence") or "").split():
                    self.assertIn(key, self.data["evidence"])

    def test_animation_steps_reference_known_nodes_and_paths(self):
        nodes = onion.nodes(self.data)
        paths = {path["id"] for path in self.data["paths"]}
        for step in self.data["animation"]["steps"]:
            self.assertTrue(set(step["active"]) <= set(nodes), step["id"])
            for link in step["links"]:
                self.assertIn(link["from"], nodes)
                self.assertIn(link["to"], nodes)
                self.assertIn(link["path"], paths)

    def test_timeline_matches_the_lesson_duration_at_the_export_speed(self):
        info = self.data["animation"]
        frames = onion.timeline(info["steps"], info["speed"], info["end_hold_seconds"])
        expected = sum(step["seconds"] for step in info["steps"]) / info["speed"] + info["end_hold_seconds"]
        self.assertAlmostEqual(sum(frame["delay"] for frame in frames) / 100, expected, delta=.01)
        self.assertEqual([frame["start"] for frame in frames[1:]], [f["start"] + f["delay"] for f in frames[:-1]])


class OnionOutputs(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(onion.DATA.read_text(encoding="utf-8"))
        self.out = {key: (HERE / value).resolve() for key, value in self.data["outputs"].items()}

    def test_svgs_are_vector_only_and_self_contained(self):
        for key in ("poster_svg", "animated_svg"):
            content = self.out[key].read_text(encoding="utf-8")
            root = ET.fromstring(content)
            self.assertFalse(root.findall(f".//{SVG}image"), key)
            self.assertNotIn("http://", content.replace("http://www.w3.org/2000/svg", ""))
            self.assertNotIn("https://", content)
        self.assertTrue(ET.fromstring(self.out["animated_svg"].read_text(encoding="utf-8")).findall(f".//{SVG}animate"))

    def test_committed_svgs_and_doc_tables_are_regenerated_from_the_json(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = Path(folder) / "doc.md"
            shutil.copy(self.out["doc"], doc)
            onion.update_doc(doc, self.data)
            self.assertEqual(doc.read_text(encoding="utf-8"), self.out["doc"].read_text(encoding="utf-8"),
                             "Run make_onion_svg.py --update-doc")
        self.assertEqual(onion.poster(self.data)[0], self.out["poster_svg"].read_text(encoding="utf-8"),
                         "Run make_onion_svg.py")


if __name__ == "__main__":
    unittest.main()
