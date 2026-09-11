"""Command line entry points shared by notebooks, CI, and Azure ML jobs."""

import argparse
import json
import sys
from pathlib import Path

from .config import load_json, validate_runtime, validate_scenario, write_json


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Kaggle-backed Azure Machine Learning model factory (v2)")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate scenario and optional resolved runtime")
    validate.add_argument("--scenario", required=True, type=Path)
    validate.add_argument("--runtime", type=Path)
    ingest = commands.add_parser("ingest", help="Download the selected Kaggle dataset without accepting terms")
    ingest.add_argument("--scenario", required=True, type=Path)
    ingest.add_argument("--output", required=True, type=Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--scenario", required=True, type=Path)
    prepare.add_argument("--input", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    train = commands.add_parser("train")
    train.add_argument("--scenario", required=True, type=Path)
    train.add_argument("--prepared", required=True, type=Path)
    train.add_argument("--model-output", required=True, type=Path)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--scenario", required=True, type=Path)
    evaluate.add_argument("--prepared", required=True, type=Path)
    evaluate.add_argument("--model", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    render = commands.add_parser("render", help="Render SDK-loadable Azure ML v2 YAML")
    render.add_argument("--scenario", required=True, type=Path)
    render.add_argument("--runtime", required=True, type=Path)
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    render.add_argument("--mode", choices=("automl", "custom"), default="automl")
    submit = commands.add_parser("submit", help="Submit an explicit Azure ML v2 job; incurs compute charges")
    submit.add_argument("--runtime", required=True, type=Path)
    submit.add_argument("--job", required=True, type=Path)
    notebooks = commands.add_parser("notebooks")
    notebooks.add_argument("--scenario", required=True, type=Path)
    notebooks.add_argument("--output", required=True, type=Path)
    notebooks.add_argument("--mode", choices=("automl", "custom"), default="custom")
    notebooks.add_argument("--runtime", default="runtime.json")
    discover = commands.add_parser("discover", help="Read-only factory resource discovery; creates no Azure resources")
    discover.add_argument("--project", required=True, type=Path)
    discover.add_argument("--output", required=True, type=Path)
    instantiate = commands.add_parser("instantiate", help="Copy templates without overwriting consumer edits")
    instantiate.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    instantiate.add_argument("--destination", required=True, type=Path)
    lake_plan = commands.add_parser("lake-plan", help="Resolve a versioned lake layout without creating folders or Azure resources")
    lake_plan.add_argument("--scenario", required=True, type=Path)
    lake_plan.add_argument("--config", required=True, type=Path)
    lake_plan.add_argument("--output", type=Path)
    lake_train = commands.add_parser("lake-train", help="Publish immutable source/snapshot/training artifacts in a local lake")
    lake_train.add_argument("--scenario", required=True, type=Path)
    lake_train.add_argument("--config", required=True, type=Path)
    lake_train.add_argument("--root", required=True, type=Path)
    lake_train.add_argument("--input", required=True, type=Path)
    lake_infer = commands.add_parser("lake-infer", help="Score unlabeled requests into model-versioned lake outputs")
    lake_infer.add_argument("--scenario", required=True, type=Path)
    lake_infer.add_argument("--config", required=True, type=Path)
    lake_infer.add_argument("--root", required=True, type=Path)
    lake_infer.add_argument("--input", required=True, type=Path)
    lake_infer.add_argument("--model", required=True, type=Path)
    lake_publish = commands.add_parser("lake-publish", help="Preview or explicitly publish committed artifacts to an existing Blob container")
    lake_publish.add_argument("--scenario", required=True, type=Path)
    lake_publish.add_argument("--config", required=True, type=Path)
    lake_publish.add_argument("--root", required=True, type=Path)
    lake_publish.add_argument("--area", required=True, choices=("dataset_root", "training_snapshot", "training_run", "inference_root"))
    lake_publish.add_argument("--execute", action="store_true")
    lake_publish.add_argument("--tenant-id")
    feedback = commands.add_parser("lake-feedback", help="Store observed labels separately without retraining")
    feedback.add_argument("--scenario", required=True, type=Path)
    feedback.add_argument("--config", required=True, type=Path)
    feedback.add_argument("--root", required=True, type=Path)
    feedback.add_argument("--input", required=True, type=Path)
    return root


def execute(args):
    scenario = validate_scenario(load_json(args.scenario)) if hasattr(args, "scenario") else None
    if args.command == "validate":
        if args.runtime:
            validate_runtime(load_json(args.runtime))
        return {"valid": True, "scenario": scenario["name"],
                "dataset_status": scenario["dataset"].get("status", "configured")}
    if args.command == "ingest":
        from .data import ingest
        return {"input": str(ingest(scenario, args.output))}
    if args.command == "prepare":
        if scenario["task"].startswith("image_"):
            from .vision import prepare_vision
            return prepare_vision(scenario, args.input, args.output)
        from .data import prepare
        return prepare(scenario, args.input, args.output)
    if args.command == "train":
        if scenario["task"].startswith("image_"):
            from .vision import train_vision
            return train_vision(scenario, args.prepared, args.model_output)
        from .training import train
        train(scenario, args.prepared, args.model_output)
        return {"model": str(args.model_output)}
    if args.command == "evaluate":
        if scenario["task"].startswith("image_"):
            from .vision import evaluate_vision
            return evaluate_vision(scenario, args.prepared, args.model, args.output)
        from .evaluation import evaluate
        return evaluate(scenario, args.prepared, args.model, args.output)
    if args.command == "render":
        from .azureml import render
        return render(scenario, validate_runtime(load_json(args.runtime)), args.output, args.source, args.mode)
    if args.command == "submit":
        from .azureml import submit
        return {"job": submit(args.job, validate_runtime(load_json(args.runtime)))}
    if args.command == "notebooks":
        from .notebooks import render_notebooks
        return render_notebooks(scenario, args.output, args.mode, args.runtime)
    if args.command == "discover":
        from .project import discover
        runtime = discover(args.project)
        write_json(args.output, runtime)
        return runtime
    if args.command == "instantiate":
        from .templates import instantiate
        return instantiate(args.source, args.destination)
    if args.command == "lake-plan":
        from .lake import LakeLayout, lake_manifest
        result = lake_manifest(LakeLayout.from_config(load_json(args.config), scenario), scenario)
        if args.output:
            write_json(args.output, result)
        return result
    if args.command == "lake-train":
        from .lake_flow import train_in_lake
        return train_in_lake(scenario, load_json(args.config), args.input, args.root)
    if args.command == "lake-infer":
        from .lake_flow import infer_in_lake
        return infer_in_lake(scenario, load_json(args.config), args.input, args.model, args.root)
    if args.command == "lake-publish":
        from .lake import LakeLayout
        from .lake_storage import publication_plan, publish
        layout = LakeLayout.from_config(load_json(args.config), scenario)
        if not args.execute:
            return publication_plan(layout, args.root, args.area)
        if not args.tenant_id:
            raise ValueError("--tenant-id is required for explicit Azure CLI authentication")
        from uuid import UUID
        from azure.identity import AzureCliCredential
        credential = AzureCliCredential(tenant_id=str(UUID(args.tenant_id)))
        return publish(layout, args.root, args.area, credential)
    if args.command == "lake-feedback":
        from .lake_flow import feedback_in_lake
        return feedback_in_lake(scenario, load_json(args.config), args.input, args.root)
    raise ValueError(f"Unhandled command: {args.command}")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except (ValueError, FileNotFoundError, ModuleNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
    return 0
