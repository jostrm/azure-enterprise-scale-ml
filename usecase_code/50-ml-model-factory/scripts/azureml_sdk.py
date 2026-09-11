"""SDK v2 examples: submit, gated register, and no-code MLflow deployment."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_model_factory.azureml import register, submit
from ml_model_factory.serving import deploy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    submit_parser = commands.add_parser("submit")
    submit_parser.add_argument("--job", type=Path, required=True)
    register_parser = commands.add_parser("register")
    register_parser.add_argument("--job-name", required=True)
    register_parser.add_argument("--model-name", required=True)
    deploy_parser = commands.add_parser("deploy")
    deploy_parser.add_argument("--bundle", type=Path, required=True)
    deploy_parser.add_argument("--model-id", required=True)
    deploy_parser.add_argument("--kind", choices=["online", "batch"], default="online")
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text(encoding="utf-8-sig"))
    if args.action == "submit":
        result = submit(args.job, runtime)
    elif args.action == "register":
        result = register(args.job_name, runtime, args.model_name)
    else:
        result = deploy(runtime, args.bundle, args.model_id, args.kind)
    print(result)


if __name__ == "__main__":
    main()
