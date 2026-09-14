"""Real local component execution; no Azure credentials or cloud writes."""

from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import mlflow.pyfunc
import mlflow.sklearn
import numpy as np
import pandas as pd
from pyarrow import ArrowInvalid
import pytest
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.linear_model import LinearRegression
import yaml

from azure_esml.domain_layer.runtime import FrameTransformer, read_tabular, run_operation
from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import sha256
from ml_model_factory.tags import build_tags


@pytest.fixture
def workdir(monkeypatch):
    root = Path.cwd() / ".runtime-test-artifacts"
    path = root / uuid4().hex
    path.mkdir(parents=True)
    scratch = path / "scratch"
    scratch.mkdir()
    for variable in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(variable, str(scratch))
    monkeypatch.setenv("MLFLOW_TRACKING_URI", (path / "mlruns").as_uri())
    yield path
    shutil.rmtree(path)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


def test_training_scope_names_do_not_select_inference_mode():
    from azure_esml.domain_layer.runtime import _is_inference
    assert not _is_inference({"request": {
        "pipeline_type": "IN_2_GOLD_TRAINING_MANUAL",
        "scope": {"aifactory": "inference-solutions", "project": "001", "environment": "dev"},
    }})
    assert _is_inference({"request": {"pipeline_type": "GOLD_INFERENCE"}})


def config(task="classification"):
    scenario = {
        "name": "runtime-example", "task": task, "target": "target",
        "features": ["x", "category"], "categorical_features": ["category"],
        "dataset": {"provider": "lake", "kind": "dataset"},
        "split": {"test_size": 0.2, "validation_size": 0.2, "seed": 42},
        "custom": {"algorithm": "logistic_regression" if task == "classification" else "ridge"},
        "quality": {"min_accuracy": 0.9} if task == "classification" else {"max_rmse": 0.2},
        "sensitive_features": ["category"],
    }
    scope = {"aifactory": "factory1", "project": "001", "environment": "dev"}
    return {
        "scenario": scenario,
        "table_format": "parquet", "bronze_mode": "normalized",
        "tags": {**build_tags(scenario, scope, engine="azureml", require_scope=True),
                 "dataset": "source", "data_version": "2026-09-13", "snapshot_id": "snapshot1", "run_id": "run1"},
        "request": {"run_id": "run1", "data_date_utc": "2026-09-13", "model_version": "7",
                    "data_version": "2026-09-13", "snapshot_id": "snapshot1",
                    "pipeline_type": "IN_2_GOLD_TRAINING_MANUAL", "scope": scope},
        "dataset": {"format": "parquet", "required_columns": ["x", "category", "target"]},
        "merge": {"mode": "concat"},
    }


def records(task="classification"):
    x = np.linspace(-3, 3, 180)
    return pd.DataFrame({
        "x": x, "category": np.where(np.arange(len(x)) % 2, "odd", "even"),
        "target": (x > 0).astype(int) if task == "classification" else 2.5 * x + 4,
    })


def parquet(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def prepare(config_, directory, frame):
    source = parquet(directory / "source.parquet", frame)
    silver, gold, prepared = directory / "silver", directory / "gold", directory / "prepared"
    run_operation("in2silver", config_, silver, inputs={"source": source})
    run_operation("merge", config_, gold, inputs={"silver": silver})
    splits = {name: directory / name for name in ("train", "validation", "test")}
    run_operation("split", config_, prepared, inputs={"gold": gold}, **splits)
    for name, output in splits.items():
        assert sha256(output / "data.parquet") == sha256(prepared / name / "data.parquet")
        actual, _ = read_tabular(output)
        expected = pd.read_parquet(prepared / name / "data.parquet")
        if config_["scenario"]["task"] == "forecasting":
            column = config_["scenario"]["forecast"]["time_column"]
            for frame in (actual, expected):
                frame[column] = pd.to_datetime(frame[column], utc=True).dt.tz_localize(None).astype("datetime64[ns]")
        pd.testing.assert_frame_equal(actual, expected)
        assert (output / "data.parquet").is_file()
        assert (output / "MLTable").is_file()
    return prepared


def test_ingestion_shards_metadata_lineage_and_no_implicit_cleaning(workdir):
    cfg = config()
    first, second = records().iloc[:60].copy(), records().iloc[60:100].copy()
    first.loc[first.index[0], "x"] = np.nan
    raw = workdir / "raw"
    parquet(raw / "z.parquet", second)
    parquet(raw / "a.parquet", first)
    (raw / "metadata.json").write_text('{"ignored":true}', encoding="utf-8")
    bronze, silver = workdir / "bronze", workdir / "silver"
    result = run_operation("in2bronze", cfg, bronze, inputs={"source": raw})
    expected = pd.concat([first, second], ignore_index=True)
    pd.testing.assert_frame_equal(pd.read_parquet(bronze / "data.parquet"), expected)
    assert list(result["inputs"]["source"]["files"]) == ["a.parquet", "z.parquet"]
    assert result["inputs"]["source"]["files"]["a.parquet"] == sha256(raw / "a.parquet")
    assert len(result["source_fingerprint"]) == 64
    assert result["transformation"] == "none"
    run_operation("bronze2silver", cfg, silver, inputs={"bronze": bronze})
    pd.testing.assert_frame_equal(pd.read_parquet(silver / "data.parquet"), expected)
    assert load_json(silver / "lineage.json")["learned_preprocessing"] is False
    assert (silver / "MLTable").is_file()
    with pytest.raises(ValueError, match="empty directory"):
        run_operation("in2silver", cfg, silver, inputs={"raw": raw})
    pd.testing.assert_frame_equal(pd.read_parquet(silver / "data.parquet"), expected)


def test_csv_requires_explicit_folder_format_and_recursion(workdir):
    raw = workdir / "csv"
    raw.mkdir()
    records().iloc[:5].to_csv(raw / "part.csv", index=False)
    with pytest.raises(ValueError, match="No parquet"):
        read_tabular(raw)
    frame, _ = read_tabular(raw, {"format": "csv"})
    assert len(frame) == 5
    nested = raw / "nested"
    nested.mkdir()
    records().iloc[:3].to_csv(nested / "part.csv", index=False)
    assert len(read_tabular(raw, {"file_pattern": "**/*.csv"})[0]) == 8
    assert len(read_tabular(raw, {"file_pattern": "*.csv"})[0]) == 5
    with pytest.raises(ValueError, match="disagrees"):
        read_tabular(raw, {"format": "parquet", "file_pattern": "*.csv"})
    corrupt = raw / "broken.parquet"
    corrupt.write_bytes(b"not parquet")
    with pytest.raises(ArrowInvalid):
        read_tabular(raw)


@pytest.mark.parametrize("pattern", ["../*.parquet", "/a/*.parquet", "C:\\data\\*.parquet", "a/../../*.csv"])
def test_unsafe_patterns_rejected(workdir, pattern):
    with pytest.raises(ValueError, match="traversal|absolute"):
        read_tabular(workdir, {"file_pattern": pattern})


def test_empty_unsupported_and_symlink_sources(workdir):
    with pytest.raises(ValueError, match="No parquet"):
        read_tabular(workdir)
    empty = parquet(workdir / "empty.parquet", records().iloc[:0])
    with pytest.raises(ValueError, match="contain records"):
        read_tabular(empty)
    text = workdir / "data.json"
    text.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="CSV and Parquet"):
        read_tabular(text)
    source = parquet(workdir / "real.parquet", records())
    link = workdir / "link.parquet"
    try:
        link.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"Host cannot create a symbolic link: {exc}")
    with pytest.raises(ValueError, match="links"):
        read_tabular(link)


def test_explicit_validation_and_consumer_hooks(workdir):
    cfg = config()
    raw = parquet(workdir / "raw.parquet", records().rename(columns={"x": "raw_x"}))
    with pytest.raises(ValueError, match="required columns"):
        run_operation("in2silver", cfg, workdir / "missing", inputs={"raw": raw})

    class Rename(FrameTransformer):
        def transform(self, frame, context):
            assert context["input_name"] == "raw"
            assert context["request"]["run_id"] == "run1"
            return frame.rename(columns={"raw_x": "x"})

    output = workdir / "hook"
    run_operation("in2silver", cfg, output, inputs={"raw": raw}, transformer=Rename())
    pd.testing.assert_frame_equal(pd.read_parquet(output / "data.parquet"), records())
    assert load_json(output / "lineage.json")["transformation"] == "consumer-hook"
    cfg["dataset"]["column_types"] = {"x": "int64"}
    with pytest.raises(ValueError, match="dtype"):
        run_operation("bronze2silver", cfg, workdir / "bad-type", inputs={"silver": output})
    cfg["dataset"].pop("column_types")
    hook = workdir / "consumer.py"
    hook.write_text("def transform(frame, context):\n    return frame.rename(columns={'raw_x': 'x'})\n", encoding="utf-8")
    cfg["hook"] = {"file": str(hook), "function": "transform"}
    run_operation("in2silver", cfg, workdir / "script", inputs={"raw": raw})
    assert load_json(workdir / "script" / "lineage.json")["transformer"]["sha256"] == sha256(hook)
    with pytest.raises(TypeError, match="DataFrame"):
        run_operation("in2silver", cfg, workdir / "bad-hook", inputs={"raw": raw}, transformer=lambda frame, ctx: None)
    run_operation("in2bronze", cfg, workdir / "raw-bronze", inputs={"raw": raw})
    assert "raw_x" in pd.read_parquet(workdir / "raw-bronze" / "data.parquet")
    cfg["dataset_overrides"] = {"raw": {"required_columns": ["other"]}}
    with pytest.raises(ValueError, match="other"):
        run_operation("in2silver", cfg, workdir / "override", inputs={"raw": raw})


def test_concat_fanout_and_schema_mismatches(workdir):
    cfg = config()
    first = parquet(workdir / "first.parquet", records().iloc[:80])
    second = parquet(workdir / "second.parquet", records().iloc[80:][["target", "category", "x"]])
    for name, source in {"first": first, "second": second}.items():
        run_operation("in2silver", cfg, workdir / name, inputs={name: source})
    merged = workdir / "merged"
    run_operation("merge", cfg, merged, inputs={"first": workdir / "first", "second": workdir / "second"})
    pd.testing.assert_frame_equal(pd.read_parquet(merged / "data.parquet"), records())
    different = parquet(workdir / "different.parquet", records().drop(columns="target"))
    with pytest.raises(ValueError, match="same column"):
        run_operation("merge", cfg, workdir / "bad-schema", inputs={"a": first, "b": different})
    dtype = parquet(workdir / "dtype.parquet", records().astype({"x": "int64"}))
    with pytest.raises(ValueError, match="incompatible dtypes"):
        run_operation("merge", cfg, workdir / "bad-dtypes", inputs={"a": first, "b": dtype})
    cfg["request"]["pipeline_type"] = "IN_2_GOLD_INFERENCE"
    with pytest.raises(ValueError, match="target/label"):
        run_operation("merge", cfg, workdir / "leak", inputs={"a": first})


def test_explicit_join_cardinality_and_overlap(workdir):
    cfg = config()
    cfg["merge"] = {"mode": "join", "on": ["id"], "how": "left", "validate": "many_to_one"}
    left = parquet(workdir / "left.parquet", pd.DataFrame({"id": [1, 1, 2], "a": [4, 5, 6]}))
    right = parquet(workdir / "right.parquet", pd.DataFrame({"id": [1, 2], "b": [7, 8]}))
    output = workdir / "joined"
    run_operation("merge", cfg, output, inputs={"left": left, "right": right})
    assert pd.read_parquet(output / "data.parquet")["b"].tolist() == [7, 7, 8]
    cfg["merge"]["validate"] = "one_to_one"
    with pytest.raises(pd.errors.MergeError):
        run_operation("merge", cfg, workdir / "duplicate-left", inputs={"left": left, "right": right})
    cfg["merge"]["validate"] = "many_to_one"
    duplicate = parquet(workdir / "duplicate.parquet", pd.DataFrame({"id": [1, 1], "b": [7, 8]}))
    with pytest.raises(pd.errors.MergeError):
        run_operation("merge", cfg, workdir / "cartesian", inputs={"left": left, "right": duplicate})
    overlap = parquet(workdir / "overlapping.parquet", pd.DataFrame({"id": [1, 2], "a": [7, 8]}))
    with pytest.raises(ValueError, match="overlapping"):
        run_operation("merge", cfg, workdir / "overlap", inputs={"left": left, "right": overlap})
    cfg["merge"].pop("on")
    with pytest.raises(ValueError, match="explicit"):
        run_operation("merge", cfg, workdir / "implicit-keys", inputs={"left": left, "right": right})


@pytest.mark.parametrize("task", ["classification", "regression"])
def test_real_training_evaluation_and_inference(workdir, task):
    cfg = config(task)
    prepared = prepare(cfg, workdir, records(task))
    model, reports = workdir / "model", workdir / "reports"
    tags = run_operation("training_manual", cfg, model, prepared=prepared)
    definition = yaml.safe_load((model / "MLmodel").read_text(encoding="utf-8"))
    assert definition["metadata"]["model_factory_tags"] == tags == cfg["tags"]
    report = run_operation("evaluate", cfg, reports, prepared=prepared, model=model)
    assert report["test_rows"] == 36
    assert load_json(reports / "quality-gate.json")["passed"] is True
    lineage = load_json(reports / "lineage.json")
    assert lineage == {
        "scenario": cfg["scenario"]["name"], "task": task, "mode": "custom", "model_output": "model",
        "mlmodel_sha256": sha256(model / "MLmodel"), "model_tags": cfg["tags"],
    }
    assert load_json(reports / "comparison.json")["scope"] == cfg["request"]["scope"]
    assert load_json(reports / "model-tags.json") == tags
    future = pd.read_parquet(prepared / "test" / "data.parquet").drop(columns="target")
    future.insert(0, "request_id", [f"request-{index}" for index in range(len(future))])
    source = parquet(workdir / "future.parquet", future)
    inference = workdir / "inference"
    run_operation("inference", cfg, inference, inputs={"gold": source}, model=model)
    actual = pd.read_parquet(inference / "predictions.parquet")
    expected = mlflow.pyfunc.load_model(str(model)).predict(future[cfg["scenario"]["features"]])
    np.testing.assert_array_equal(actual["prediction"], expected)
    assert actual["request_id"].tolist() == future["request_id"].tolist()
    info = load_json(inference / "runinfo.json")
    assert info["model_version"] == "7" and info["scope"] == cfg["request"]["scope"]
    assert info["run_id"] == "run1" and info["data_date_utc"] == "2026-09-13"
    assert info["inputs"]["gold"]["files"]["future.parquet"] == sha256(source)
    assert info["predictions_sha256"] == sha256(inference / "predictions.parquet")

    failed = deepcopy(cfg)
    failed["scenario"]["quality"] = {"min_accuracy": 1.1} if task == "classification" else {"max_rmse": -1}
    with pytest.raises(ValueError, match="quality gate failed"):
        run_operation("evaluate", failed, workdir / "failed", prepared=prepared, model=model)
    assert load_json(workdir / "failed" / "quality-gate.json")["passed"] is False
    assert not (workdir / "failed" / "lineage.json").exists()
    assert not (workdir / "failed" / "comparison.json").exists()

    wrong_scope = deepcopy(cfg)
    wrong_scope["tags"]["aifactory"] = "another-factory"
    with pytest.raises(ValueError, match="artifact tags"):
        run_operation("evaluate", wrong_scope, workdir / "wrong-scope", prepared=prepared, model=model)
    for invalid, message in [
        (future.assign(target=1), "target/label"),
        (future.assign(request_id="same"), "unique"),
        (future.assign(request_id=" "), "nonblank"),
        (future.assign(request_id=None), "nonmissing"),
        (future.drop(columns="request_id"), "request ID"),
    ]:
        path = parquet(workdir / "invalid.parquet", invalid)
        with pytest.raises(ValueError, match=message):
            run_operation("inference", cfg, workdir / "invalid-result", inputs={"gold": path}, model=model)
    cfg["request_id_column"] = "prediction"
    with pytest.raises(ValueError, match="distinct from prediction"):
        run_operation("inference", cfg, workdir / "bad-id-name", inputs={"gold": source}, model=model)
    cfg.pop("request_id_column")
    factory_path = model / "factory.json"
    factory = load_json(factory_path)
    write_json(factory_path, {**factory, "model_version": "8"})
    with pytest.raises(ValueError, match="artifact version"):
        run_operation("inference", cfg, workdir / "wrong-version", inputs={"gold": source}, model=model)
    write_json(factory_path, factory)
    cfg["request"]["model_version"] = "latest"
    with pytest.raises(ValueError, match="immutable"):
        run_operation("inference", cfg, workdir / "latest", inputs={"gold": source}, model=model)


def test_split_labels_groups_and_nonoverlapping_outputs(workdir):
    cfg = config()
    cfg["scenario"]["split"]["group_column"] = "entity"
    frame = records()
    frame["entity"] = np.arange(len(frame)) % 12
    prepared = prepare(cfg, workdir, frame)
    groups = {name: set(pd.read_parquet(prepared / name / "data.parquet")["entity"])
              for name in ("train", "validation", "test")}
    assert not groups["train"] & groups["validation"]
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & groups["test"]
    assert load_json(prepared / "manifest.json")["split_policy"] == "entity-group-disjoint"
    with pytest.raises(ValueError, match="overlap"):
        run_operation("split", cfg, workdir / "other", inputs={"gold": workdir / "gold"},
                      train=workdir / "other" / "train", validation=workdir / "v", test=workdir / "t")
    frame.loc[0, "target"] = np.nan
    invalid = parquet(workdir / "unlabeled.parquet", frame)
    run_operation("merge", cfg, workdir / "unlabeled-gold", inputs={"source": invalid})
    with pytest.raises(ValueError, match="complete target"):
        run_operation("split", cfg, workdir / "bad-label", inputs={"gold": workdir / "unlabeled-gold"})
    frame["target"] = frame["target"].astype(str)
    frame.loc[0, "target"] = " "
    invalid = parquet(workdir / "blank-label.parquet", frame)
    run_operation("merge", cfg, workdir / "blank-gold", inputs={"source": invalid})
    with pytest.raises(ValueError, match="complete target"):
        run_operation("split", cfg, workdir / "blank-label", inputs={"gold": workdir / "blank-gold"})
    changed = pd.read_parquet(prepared / "test" / "data.parquet").iloc[:-1]
    parquet(prepared / "test" / "data.parquet", changed)
    with pytest.raises(ValueError, match="manifest hash"):
        run_operation("training_manual", cfg, workdir / "tampered", prepared=prepared)


def forecast_config():
    cfg = config("forecasting")
    cfg["scenario"].update(
        features=["x"], categorical_features=[], sensitive_features=[],
        forecast={"time_column": "date", "series_columns": ["series"], "frequency": "D", "horizon": 3},
        custom={"algorithm": "seasonal_naive", "seasonal_period": 3}, quality={"max_rmse": 0.01},
    )
    cfg["dataset"]["required_columns"] = ["x", "date", "series", "target"]
    return cfg


def forecast_records():
    return pd.concat([
        pd.DataFrame({"x": np.arange(30, dtype=float), "date": pd.date_range("2026-01-01", periods=30),
                      "series": name, "target": offset + np.arange(30) % 3})
        for name, offset in (("a", 10.0), ("b", 20.0))
    ], ignore_index=True)


def test_real_forecast_temporal_split_training_and_inference(workdir):
    cfg = forecast_config()
    prepared = prepare(cfg, workdir, forecast_records())
    assert load_json(prepared / "manifest.json")["split_policy"] == "chronological-per-series"
    for name, expected_dates in (("train", 24), ("validation", 3), ("test", 3)):
        rows = pd.read_parquet(prepared / name / "data.parquet")
        assert rows.groupby("series").size().to_dict() == {"a": expected_dates, "b": expected_dates}
    model = workdir / "model"
    run_operation("training_manual", cfg, model, prepared=prepared)
    run_operation("evaluate", cfg, workdir / "evaluation", prepared=prepared, model=model)
    assert load_json(workdir / "evaluation" / "metrics.json")["rmse"] == 0
    future = pd.read_parquet(prepared / "test" / "data.parquet").drop(columns="target")
    future["request_id"] = np.arange(len(future))
    source = parquet(workdir / "future.parquet", future)
    run_operation("inference", cfg, workdir / "inference", model=model, inputs={"gold": source})
    output = pd.read_parquet(workdir / "inference" / "predictions.parquet")
    expected = pd.read_parquet(prepared / "test" / "data.parquet")["target"]
    np.testing.assert_array_equal(output["prediction"], expected)
    future["date"] = pd.Timestamp("2025-01-01")
    parquet(source, future)
    with pytest.raises(ValueError, match="after training"):
        run_operation("inference", cfg, workdir / "past", model=model, inputs={"gold": source})


class ForecastEstimator(RegressorMixin, BaseEstimator):
    def fit(self, frame, target):
        self.estimator_ = LinearRegression().fit(frame[["x"]], target)
        return self

    def predict(self, frame):
        return self.estimator_.predict(frame[["x"]])

    def forecast(self, frame, y_query, ignore_data_errors):
        assert ignore_data_errors is False
        assert np.isnan(y_query).any() and np.isfinite(y_query[~np.isnan(y_query)]).all()
        aligned = frame.iloc[::-1].copy()
        return self.predict(aligned), aligned


def test_automl_forecast_adapter_uses_history_and_aligns_real_model(workdir):
    cfg = forecast_config()
    cfg["mode"] = "automl"
    cfg["tags"]["training_mode"] = "automl"
    frame = forecast_records()
    frame["target"] = 2 * frame["x"] + 3
    prepared = prepare(cfg, workdir, frame)
    train = pd.read_parquet(prepared / "train" / "data.parquet")
    estimator = ForecastEstimator().fit(train, train["target"])
    model = workdir / "model"
    mlflow.sklearn.save_model(estimator, str(model), pip_requirements=["scikit-learn", "pandas"])
    run_operation("evaluate", cfg, workdir / "evaluation", prepared=prepared, model=model)
    assert load_json(workdir / "evaluation" / "quality-gate.json")["passed"] is True
    assert load_json(workdir / "evaluation" / "comparison.json")["scope"] == cfg["request"]["scope"]
    future = pd.read_parquet(prepared / "test" / "data.parquet")
    truth = future.pop("target")
    future["request_id"] = [str(i) for i in range(len(future))]
    source = parquet(workdir / "future.parquet", future)
    with pytest.raises(ValueError, match="history"):
        run_operation("inference", cfg, workdir / "no-history", model=model, inputs={"gold": source})
    run_operation("inference", cfg, workdir / "inference", model=model,
                  inputs={"gold": source, "history": prepared / "validation"})
    actual = pd.read_parquet(workdir / "inference" / "predictions.parquet")
    np.testing.assert_allclose(actual["prediction"], truth)
    assert "history" in load_json(workdir / "inference" / "runinfo.json")["inputs"]
    with pytest.raises(ValueError, match="preceding"):
        run_operation("inference", cfg, workdir / "leaky-history", model=model,
                      inputs={"gold": source, "history": prepared / "test"})


def test_cli_repeated_named_inputs_works_with_spaces(workdir):
    cfg = config()
    first = parquet(workdir / "first input.parquet", records().iloc[:90])
    second = parquet(workdir / "second input.parquet", records().iloc[90:])
    config_path = workdir / "runtime config.json"
    write_json(config_path, cfg)
    command = [
        sys.executable, "-m", "azure_esml.domain_layer.runtime", "--operation", "merge",
        "--config", str(config_path), "--output", str(workdir / "result folder"),
        "--input", "first", str(first), "--input", "second", str(second),
        "--data-date-utc", cfg["request"]["data_date_utc"], "--run-id", "run1", "--model-version", "7",
        "--data-version", "2026-09-13", "--snapshot-id", "snapshot1", "--project-name", "project001",
        "--environment", "dev",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=dict(os.environ))
    assert result.returncode == 0, result.stderr
    pd.testing.assert_frame_equal(pd.read_parquet(workdir / "result folder" / "data.parquet"), records())
    duplicate = subprocess.run(command + ["--input", "first", str(first)], capture_output=True, text=True)
    assert duplicate.returncode != 0 and "Duplicate input name" in duplicate.stderr
    hook = workdir / "transformer.py"
    hook.write_text(
        "from azure_esml.domain_layer.runtime import FrameTransformer\n"
        "class AddOne(FrameTransformer):\n"
        "    def transform(self, frame, context):\n"
        "        return frame.assign(x=frame.x + 1)\n", encoding="utf-8",
    )
    cfg["hook"] = {"file": str(hook), "function": "AddOne"}
    write_json(config_path, cfg)
    result = subprocess.run([
        sys.executable, "-m", "azure_esml.domain_layer.runtime", "--operation", "in2silver",
        "--config", str(config_path), "--output", str(workdir / "hooked"),
        "--input", "first", str(first),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    np.testing.assert_allclose(pd.read_parquet(workdir / "hooked" / "data.parquet")["x"], records().iloc[:90]["x"] + 1)


@pytest.mark.parametrize("parameter,value", [
    ("data_date_utc", "2026-09-14"), ("run_id", "other-run"), ("model_version", "8"),
    ("data_version", "other-version"), ("snapshot_id", "other-snapshot"),
])
def test_bound_request_rejects_stale_component_rebinding(workdir, parameter, value):
    cfg = config()
    unchanged = deepcopy(cfg)
    source = parquet(workdir / "input.parquet", records())
    with pytest.raises(ValueError, match="differs from the compiled request"):
        run_operation("in2silver", cfg, workdir / "stale", inputs={"data": source}, **{parameter: value})
    assert cfg == unchanged
    assert not (workdir / "stale").exists()
    cfg["request"][parameter] = value
    run_operation("in2silver", cfg, workdir / "rebuilt", inputs={"data": source}, **{parameter: value})
    assert load_json(workdir / "rebuilt" / "lineage.json")["request"][parameter] == value


def test_bound_request_accepts_absent_model_only_for_noninference(workdir):
    cfg = config()
    cfg["request"]["model_version"] = None
    source = parquet(workdir / "input.parquet", records())
    run_operation("in2silver", cfg, workdir / "training", inputs={"data": source}, model_version="none")
    cfg["request"]["pipeline_type"] = "IN_2_GOLD_INFERENCE"
    with pytest.raises(ValueError, match="compiled request"):
        run_operation("in2silver", cfg, workdir / "invalid", inputs={"data": source}, model_version="none")


@pytest.mark.parametrize("parameter,value", [("project_name", "project002"), ("environment", "prod")])
def test_bound_scope_flags_cannot_relabel_fixed_project(workdir, parameter, value):
    cfg = config()
    source = parquet(workdir / "input.parquet", records())
    with pytest.raises(ValueError, match="differs from the compiled request"):
        run_operation("in2silver", cfg, workdir / "wrong-scope", inputs={"data": source}, **{parameter: value})
    assert not (workdir / "wrong-scope").exists()
    run_operation("in2silver", cfg, workdir / "matching", inputs={"data": source},
                  project_name="project001", environment="dev")
    assert load_json(workdir / "matching" / "lineage.json")["tags"] == cfg["tags"]
