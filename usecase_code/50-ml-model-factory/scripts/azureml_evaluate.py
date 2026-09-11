"""Fail-closed pipeline evaluation, including the AutoML forecast API adapter."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_model_factory.config import quality_gate, write_json


def evaluate_forecast(scenario: dict, prepared: Path, model: Path, output: Path):
    import pandas as pd

    from ml_model_factory.data import read_frame
    from ml_model_factory.evaluation import metrics_for
    from ml_model_factory.serving import forecast_predictions

    test = read_frame(prepared / "test")
    history = read_frame(prepared / "validation")
    predictions = forecast_predictions(model, test, history, scenario)
    metrics = metrics_for("forecasting", test[scenario["target"]], predictions)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"actual": test[scenario["target"]].to_numpy(), "prediction": predictions}).to_parquet(
        output / "predictions.parquet", index=False,
    )
    write_json(output / "metrics.json", metrics)
    cohorts = {}
    for column in dict.fromkeys(scenario["forecast"].get("series_columns", []) + scenario.get("sensitive_features", [])):
        cohorts[column] = {
            str(value): {"rows": len(rows), "small_sample_warning": len(rows) < 30,
                         **metrics_for("forecasting", rows[scenario["target"]], predictions[rows.index])}
            for value, rows in test.reset_index(drop=True).groupby(column, dropna=False)
        }
    write_json(output / "responsible-ai.json", {
        "scenario": scenario["name"], "task": "forecasting", "metrics": metrics, "cohorts": cohorts,
        "responsible_ai": {
            "tooling": "Held-out temporal and series errors; MLflow sklearn forecast adapter",
            "azure_dashboard": "Not generated for forecasting",
            "limitations": ["Uses validation observations as known history, never test targets.",
                           "Cohort error differences are observational, not proof of fairness.",
                           "TCN/PyTorch forecast models are not supported by this adapter."],
        },
    })
    try:
        quality_gate(metrics, scenario.get("quality", {}))
    except ValueError as exc:
        write_json(output / "quality-gate.json", {"passed": False, "reason": str(exc)})
        raise
    write_json(output / "quality-gate.json", {"passed": True, "limits": scenario.get("quality", {})})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["automl", "custom"], required=True)
    for name in ("scenario", "prepared", "model", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--lake-config", type=Path)
    parser.add_argument("--model-tags", type=Path)
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    lake = None
    if args.lake_config is not None:
        from ml_model_factory.azureml import LAKE_LINEAGE_FIELDS, _lake_context

        lake = _lake_context(scenario, {"lake": json.loads(args.lake_config.read_text(encoding="utf-8"))})
        if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
            raise ValueError("Lake evaluation output must be empty; use a new run_id")
        prepared = json.loads((args.prepared / "manifest.json").read_text(encoding="utf-8"))
        recorded = prepared.get("lake", {}).get("config", {})
        if (prepared.get("scenario") != scenario["name"] or prepared.get("task") != scenario["task"]
                or any(recorded.get(key) != lake["config"][key] for key in LAKE_LINEAGE_FIELDS)):
            raise ValueError("Prepared lake lineage does not match this training scenario/snapshot/run")
    if args.mode == "automl" and scenario["task"].startswith("image_"):
        raise ValueError("AutoML image quality evaluation is not implemented; no registration is permitted")
    if args.mode == "automl" and scenario["task"] == "forecasting":
        evaluate_forecast(scenario, args.prepared, args.model, args.output)
    else:
        subprocess.run([
            sys.executable, "-m", "ml_model_factory", "evaluate",
            "--scenario", str(args.scenario), "--prepared", str(args.prepared),
            "--model", str(args.model), "--output", str(args.output),
        ], check=True)
    gate = json.loads((args.output / "quality-gate.json").read_text(encoding="utf-8"))
    if gate.get("passed") is not True:
        raise ValueError("Evaluator did not emit a passing quality gate")
    model_tags = None
    if args.model_tags:
        from ml_model_factory.tags import validate_tags
        model_tags = validate_tags(json.loads(args.model_tags.read_text(encoding="utf-8")))
        if (model_tags["use_case"] != scenario["name"] or model_tags["task_type"] != scenario["task"]
                or model_tags["training_mode"] != args.mode):
            raise ValueError("Model identity tags disagree with the evaluated scenario/task/mode")
        if args.mode == "custom":
            import yaml
            stored = yaml.safe_load((args.model / "MLmodel").read_text(encoding="utf-8"))
            if stored.get("metadata", {}).get("model_factory_tags") != model_tags:
                raise ValueError("Custom model artifact tags disagree with the evaluated job metadata")
        if lake is not None:
            if lake["config"].get("aifactory") and model_tags.get("aifactory") != lake["config"]["aifactory"]:
                raise ValueError("Model factory tag disagrees with evaluated lake scope")
            for key in ("project", "environment", "use_case", "dataset", "data_version", "snapshot_id", "run_id"):
                if model_tags.get(key) != lake["config"].get(key):
                    raise ValueError("Model tags disagree with evaluated lake paths")
    lineage = {
        "scenario": scenario["name"], "task": scenario["task"], "mode": args.mode,
        "model_output": "model",
        "mlmodel_sha256": hashlib.sha256((args.model / "MLmodel").read_bytes()).hexdigest(),
    }
    if lake is not None:
        lineage["lake"] = lake
        gate["lake"] = {key: lake["config"][key] for key in LAKE_LINEAGE_FIELDS}
        gate["task"] = scenario["task"]
        write_json(args.output / "quality-gate.json", gate)
    if model_tags is not None:
        lineage["model_tags"] = model_tags
        write_json(args.output / "model-tags.json", model_tags)
    write_json(args.output / "lineage.json", lineage)


if __name__ == "__main__":
    main()
