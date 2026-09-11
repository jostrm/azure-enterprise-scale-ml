import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ml_model_factory.config import boolean, quality_gate, safe_relative, validate_scenario
from ml_model_factory.data import prepare, read_frame
from ml_model_factory.project import select_one


SCENARIO = {
    "name": "titanic", "task": "classification", "target": "Survived",
    "features": ["Pclass", "Sex", "Age"], "categorical_features": ["Sex"],
    "sensitive_features": ["Sex"],
    "dataset": {"provider": "kaggle", "kind": "competition", "slug": "titanic", "file": "train.csv"},
    "split": {"seed": 42, "test_size": 0.2, "validation_size": 0.2},
    "quality": {"min_accuracy": 0.0},
}


class ConfigTests(unittest.TestCase):
    def test_false_string_is_false(self):
        self.assertFalse(boolean("false"))
        with self.assertRaises(ValueError):
            boolean("maybe")

    def test_no_label_leakage(self):
        invalid = copy.deepcopy(SCENARIO)
        invalid["features"].append("Survived")
        with self.assertRaises(ValueError):
            validate_scenario(invalid)

    def test_unsafe_dataset_paths(self):
        for path in ("../token", "C:\\secret", "/tmp/token", "nested\\..\\token"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_relative(path)

    def test_quality_failures_are_explicit(self):
        with self.assertRaises(ValueError):
            quality_gate({"accuracy": 0.4}, {"min_accuracy": 0.7})
        with self.assertRaises(ValueError):
            quality_gate({}, {"max_rmse": 4})
        with self.assertRaises(ValueError):
            quality_gate({"rmse": float("nan")}, {"max_rmse": 4})

    def test_resource_ambiguity_is_not_silently_resolved(self):
        with self.assertRaises(ValueError):
            select_one([{"name": "one"}, {"name": "two"}], "workspace")


class PipelineTests(unittest.TestCase):
    def test_tabular_local_lifecycle(self):
        import pandas as pd
        from ml_model_factory.training import train
        from ml_model_factory.evaluation import evaluate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.csv"
            pd.DataFrame({
                "Pclass": [1, 2, 3, 1] * 25, "Sex": ["female", "male"] * 50,
                "Age": list(range(100)), "Survived": [1, 0] * 50,
            }).to_csv(source, index=False)
            manifest = prepare(SCENARIO, source, root / "prepared")
            self.assertEqual(manifest["split_rows"], {"train": 60, "validation": 20, "test": 20})
            self.assertTrue((root / "prepared" / "titanic.parquet").is_file())
            train(SCENARIO, root / "prepared", root / "model")
            report = evaluate(SCENARIO, root / "prepared", root / "model", root / "report")
            self.assertIn("Sex", report["cohorts"])
            self.assertIn("permutation_importance", report["responsible_ai"])
            self.assertTrue(json.loads((root / "report" / "quality-gate.json").read_text())["passed"])

    def test_prepare_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned").write_text("keep")
            with patch("ml_model_factory.data.read_frame") as reader:
                import pandas as pd
                reader.return_value = pd.DataFrame({
                    "Pclass": [1] * 30, "Sex": ["f", "m"] * 15,
                    "Age": range(30), "Survived": [0, 1] * 15,
                })
                with self.assertRaises(ValueError):
                    prepare(SCENARIO, root / "unused.csv", root)
            self.assertEqual((root / "owned").read_text(), "keep")

    def test_chronological_split(self):
        import pandas as pd

        scenario = {
            "name": "forecast", "task": "forecasting", "target": "sales",
            "features": ["date"], "dataset": SCENARIO["dataset"],
            "forecast": {"time_column": "date", "series_columns": [], "frequency": "D", "horizon": 3},
            "custom": {"algorithm": "seasonal_naive", "seasonal_period": 1},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame({"date": pd.date_range("2024-01-01", periods=20), "sales": range(20)}).to_csv(root / "raw.csv", index=False)
            prepare(scenario, root / "raw.csv", root / "prepared")
            train_frame = read_frame(root / "prepared" / "train")
            test = read_frame(root / "prepared" / "test")
            self.assertLess(train_frame.date.max(), test.date.min())
            from ml_model_factory.training import train
            from ml_model_factory.evaluation import evaluate
            train(scenario, root / "prepared", root / "model")
            report = evaluate(scenario, root / "prepared", root / "model", root / "report")
            self.assertGreater(report["metrics"]["mae"], 0)


class TemplateTests(unittest.TestCase):
    def test_copy_excludes_local_data_and_preserves_consumer_edits(self):
        from ml_model_factory.templates import instantiate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "consumer"
            (source / "ml_model_factory").mkdir(parents=True)
            (source / "pyproject.toml").write_text("name = 'test'")
            module = source / "ml_model_factory" / "example.py"
            module.write_text("value = 1")
            (source / "data").mkdir()
            (source / "data" / "private.csv").write_text("not copied")
            (source / "runtime.local.json").write_text("{}")
            instantiate(source, destination)
            self.assertFalse((destination / "data").exists())
            self.assertFalse((destination / "runtime.local.json").exists())
            module.write_text("value = 2")
            instantiate(source, destination)
            consumer = destination / "ml_model_factory" / "example.py"
            self.assertEqual(consumer.read_text(), "value = 2")
            consumer.write_text("user edit")
            module.write_text("value = 3")
            with self.assertRaisesRegex(ValueError, "local edits"):
                instantiate(source, destination)
            self.assertEqual(consumer.read_text(), "user edit")


if __name__ == "__main__":
    unittest.main()
