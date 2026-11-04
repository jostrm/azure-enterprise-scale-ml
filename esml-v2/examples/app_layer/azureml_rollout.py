"""Prepare, execute and resume one reviewed Azure ML rollout; no Databricks operations."""

import argparse
import json
from pathlib import Path

from azure_esml import ESMLProject
from azure_esml.base_layer import AzureMLSDKBackend
from azure_esml.domain_layer.rollout import AzureMLRollout
from ml_model_factory.config import load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    actions = parser.add_subparsers(dest="action", required=True)
    preparation = actions.add_parser("prepare")
    preparation.add_argument("--model-number", required=True, type=int)
    preparation.add_argument("--mode", choices=("custom", "automl"), required=True)
    preparation.add_argument("--date", required=True)
    preparation.add_argument("--run-id", required=True)
    preparation.add_argument("--data-version")
    register = actions.add_parser("register-definitions")
    register.add_argument("--run-id", required=True)
    register.add_argument("--component-version", required=True)
    register.add_argument("--execute", action="store_true")
    training = actions.add_parser("training")
    training.add_argument("--run-id", required=True)
    training.add_argument("--execute", action="store_true")
    training.add_argument("--selection-policy", type=Path)
    champions = training.add_mutually_exclusive_group()
    champions.add_argument("--no-champion", action="store_true")
    champions.add_argument("--champion-evaluation", type=Path)
    inference = actions.add_parser("prepare-inference")
    inference.add_argument("--run-id", required=True)
    inference.add_argument("--inference-run-id", required=True)
    inference.add_argument("--date", required=True)
    deployment = actions.add_parser("deploy-invoke")
    deployment.add_argument("--run-id", required=True)
    deployment.add_argument("--component-version", required=True)
    deployment.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    project = ESMLProject.from_json(args.settings)
    if args.action in ("training", "deploy-invoke", "register-definitions"):
        if not args.execute:
            raise ValueError("This action incurs Azure writes/compute; review the request and explicitly pass --execute")
        project = ESMLProject(project.settings, backend=AzureMLSDKBackend.from_cli(project.target, subscription_bound=True))
    rollout = AzureMLRollout(project, args.output)
    if args.action == "prepare":
        result = rollout.prepare(model_number=args.model_number, mode=args.mode, data_date_utc=args.date,
                                 run_id=args.run_id, data_version=args.data_version)
    elif args.action == "register-definitions":
        result = rollout.register_definitions(args.run_id, component_version=args.component_version)
    elif args.action == "training":
        result = rollout.execute_training(
            args.run_id, selection_policy=load_json(args.selection_policy) if args.selection_policy else None,
            no_champion=args.no_champion, champion_evaluation=load_json(args.champion_evaluation) if args.champion_evaluation else None,
        )
    elif args.action == "prepare-inference":
        result = rollout.prepare_inference(args.run_id, inference_date_utc=args.date, inference_run_id=args.inference_run_id)
    else:
        result = rollout.deploy_and_invoke(args.run_id, component_version=args.component_version)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
