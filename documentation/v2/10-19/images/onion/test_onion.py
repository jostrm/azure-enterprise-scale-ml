"""Checks for the onion generator (standard library only): python -m unittest test_onion.py"""
from __future__ import annotations

import colorsys
import json
import re
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
        self.data = onion.load()

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


class OnionColors(unittest.TestCase):
    """Colors carry meaning: green fastest, red slowest, blue neutral, no purple in the onion."""

    def setUp(self):
        self.raw = json.loads(onion.DATA.read_text(encoding="utf-8"))
        self.data = onion.load()
        self.scale = {band["name"]: band["hex"] for band in self.raw["colors"]["time_scale"]}

    def test_no_layer_color_is_hard_coded_in_the_data(self):
        for item in [self.raw["consumer"]] + self.raw["layers"]:
            self.assertNotIn("color", item, item["id"])

    def test_the_slowest_layer_is_red_and_the_fastest_green(self):
        average = {layer["id"]: onion.average_minutes(self.data, layer["id"]) for layer in self.data["layers"]}
        colors = {layer["id"]: layer["color"] for layer in self.data["layers"]}
        self.assertEqual(colors[max(average, key=average.get)], self.scale["red"])
        self.assertEqual(colors[min(average, key=average.get)], self.scale["green"])
        self.assertEqual(colors["l5"], self.scale["red"], "the core (ARM) takes the most time today")

    def test_a_slower_layer_never_gets_a_better_color(self):
        order = list(self.scale.values())
        layers = sorted(self.data["layers"], key=lambda layer: onion.average_minutes(self.data, layer["id"]))
        ranks = [order.index(layer["color"]) for layer in layers]
        self.assertEqual(ranks, sorted(ranks))

    def test_the_consumer_is_neutral_blue(self):
        self.assertEqual(self.data["consumer"]["color"], self.raw["colors"]["neutral"])

    def test_no_purple_anywhere_in_the_pictures(self):
        for key in ("poster_svg", "animated_svg"):
            content = (HERE / self.raw["outputs"][key]).resolve().read_text(encoding="utf-8")
            for color in set(re.findall(r"#[0-9A-Fa-f]{6}\b", content)):
                r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
                hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
                purple = 250 <= hue * 360 <= 300 and saturation > .25 and .08 < lightness < .95
                self.assertFalse(purple, f"{color} in {key} reads as purple")


class OnionOutputs(unittest.TestCase):
    def setUp(self):
        self.data = onion.load()
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
