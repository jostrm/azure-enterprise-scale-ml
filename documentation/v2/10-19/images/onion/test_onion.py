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


V2 = HERE / "onion-layers-v2.json"

# The verified rows of the aif-138 timing table (handover 2026-10-31 23:45 CET): API time in seconds, pipeline and
# job wall clock in minutes. Scenario 5 comes from the 2026-11-01 16:00 CET update (attempt m, job db2fa13d): prepare
# 148 s, then the deletion worker on the API host (no GitHub run, about 9 min), 11.5 min in total.
VERIFIED = {
    "deploy-001": (None, 51.7, None, "41140735956"),
    "enroll-002": (138, 10.1, 13.9, "41171926400"),
    "deploy-002": (13, 29.5, 30.1, "41179463357"),
    "settings-002": (13, 24.4, 25.0, "41181519894"),
    "delete-002-services": (14, 23.6, 25.0, "41196230976"),
    "delete-002-full": (24, 30.5, 31.3, "41216080228"),
    "delete-scaleset-002": (148, 9, 11.5, None),
}


class OnionV2(unittest.TestCase):
    """Onion V2: PROJECT mode API-2-Pipelines, drawn from measured runs instead of per-layer estimates."""

    def setUp(self):
        self.raw = json.loads(V2.read_text(encoding="utf-8"))
        self.data = onion.load(V2)
        self.out = {key: (V2.parent / value).resolve() for key, value in self.data["outputs"].items()}
        self.scale = {band["name"]: band["hex"] for band in self.raw["colors"]["time_scale"]}

    def test_every_run_is_a_verified_row_of_the_handover_table(self):
        runs = {run["id"]: (run.get("api_seconds"), run.get("pipeline_minutes"), run.get("job_minutes"), run.get("run_id"))
                for run in self.data["runs"]}
        self.assertEqual(runs, VERIFIED)
        scenario5 = next(run for run in self.data["runs"] if run["id"] == "delete-scaleset-002")
        self.assertEqual(scenario5["route"], "worker")
        self.assertTrue(scenario5["approximate"], "the worker time is only known as about 9 min")
        self.assertAlmostEqual(scenario5["api_seconds"] / 60 + scenario5["pipeline_minutes"], scenario5["job_minutes"], delta=.1)

    def test_the_message_ranges_come_from_the_runs(self):
        self.assertEqual(onion.fill("{api_range}", self.data), "13-24 s")
        self.assertEqual(onion.fill("{pipeline_range}", self.data), "24-52 min")
        self.assertEqual(onion.fill("{worker_api}", self.data), "2 min 18 s")
        self.assertEqual(onion.fill("{worker_pipeline}", self.data), "10.1 min")
        self.assertEqual(onion.fill("/operations/{id}/confirm", self.data), "/operations/{id}/confirm")

    def test_each_layer_has_its_own_fixed_colour_and_only_the_core_is_red(self):
        """Joakim 2026-11-02: L1 green, L2 blue like the consumer, L3 purple, L4 orange, L5 (ARM) red."""
        colors = {layer["id"]: layer["color"] for layer in self.data["layers"]}
        purple = self.raw["colors"]["extra"]["purple"]
        self.assertEqual(colors, {"l1": self.scale["green"], "l2": self.raw["colors"]["neutral"], "l3": purple,
                                  "l4": self.scale["orange"], "l5": self.scale["red"]})
        self.assertEqual(self.data["consumer"]["color"], colors["l2"])
        self.assertEqual([layer_id for layer_id, color in colors.items() if color == self.scale["red"]], ["l5"])
        for item in [self.raw["consumer"]] + self.raw["layers"]:
            self.assertNotIn("color", item, item["id"])

    def test_the_legend_names_every_layer_colour_and_the_time_bars(self):
        legend = onion.color_legend(self.data)
        for words in ("green L1", "blue L2", "purple L3", "orange L4", "red L5", "green fastest"):
            self.assertIn(words, legend)

    def test_the_poster_labels_every_measured_number(self):
        poster = onion.poster(self.data)[0]
        for api, pipeline, _, _ in VERIFIED.values():
            if api is not None:
                self.assertIn(f">{onion.seconds_text(api)}<", poster)
        for run in self.data["runs"]:
            if run.get("pipeline_minutes") is not None:
                label = f'~{run["pipeline_minutes"]:g} min' if run.get("approximate") else f'{run["pipeline_minutes"]:.1f} min'
                self.assertIn(f">{label}<", poster)
        self.assertIn(">~9 min<", poster)

    def test_public_text_never_says_esaif(self):
        for path in (V2, self.out["poster_svg"], self.out["animated_svg"], self.out["doc"]):
            self.assertNotIn("esaif", path.read_text(encoding="utf-8").lower(), path.name)

    def test_purple_is_used_only_for_the_pipeline_layer(self):
        purple = self.raw["colors"]["extra"]["purple"]
        self.assertNotIn(purple, [band["hex"] for band in self.raw["colors"]["time_scale"]], "time bars never purple")
        for key in ("poster_svg", "animated_svg"):
            self.assertIn(purple, self.out[key].read_text(encoding="utf-8"), key)

    def test_committed_v2_svgs_and_doc_tables_are_regenerated_from_the_json(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = Path(folder) / "doc.md"
            shutil.copy(self.out["doc"], doc)
            onion.update_doc(doc, self.data)
            self.assertEqual(doc.read_text(encoding="utf-8"), self.out["doc"].read_text(encoding="utf-8"),
                             "Run make_onion_svg.py --data onion-layers-v2.json --update-doc")
        self.assertEqual(onion.poster(self.data)[0], self.out["poster_svg"].read_text(encoding="utf-8"),
                         "Run make_onion_svg.py --data onion-layers-v2.json")
        self.assertEqual(onion.animation(self.data, None)[0], self.out["animated_svg"].read_text(encoding="utf-8"))

    def test_the_ranges_in_the_hand_written_prose_match_the_runs(self):
        doc = self.out["doc"].read_text(encoding="utf-8")
        v1 = (HERE / onion.load()["outputs"]["doc"]).resolve().read_text(encoding="utf-8")
        for token in ("api_range", "pipeline_range"):
            for page in (doc, v1):
                self.assertIn(onion.fill("{" + token + "}", self.data), page, token)
        self.assertIn(onion.fill("{worker_api}", self.data), doc)

    def test_the_v1_page_links_to_the_v2_page(self):
        v1 = (HERE / onion.load()["outputs"]["doc"]).resolve().read_text(encoding="utf-8")
        self.assertIn("10-factory-onion-architecture-v2.md", v1)


if __name__ == "__main__":
    unittest.main()
