"""Shared, fail-closed Azure ML v2 CI entry point (PowerShell or bash)."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ACTIVE = {
    "NotStarted", "Starting", "Provisioning", "Preparing", "Queued", "Running",
    "Finalizing", "CancelRequested", "Paused", "Scheduled",
}
FAILED = {"Failed", "Canceled", "Cancelled", "NotResponding"}
ML_EXTENSION_VERSION = "2.38.1"


def run(args: list[str], *, timeout: float = 300) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=True, timeout=timeout,
                            env={**os.environ, "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no"})
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.stdout.strip()


def cli(*args: str) -> str:
    return run([sys.executable, "-m", "ml_model_factory", *args])


def target(runtime: dict) -> list[str]:
    keys = ("subscription_id", "resource_group", "workspace_name")
    if not isinstance(runtime, dict) or any(
        not isinstance(runtime.get(key), str) or not runtime[key].strip() for key in keys
    ):
        raise ValueError(f"Runtime requires nonempty {', '.join(keys)}")
    return [
        "--subscription", runtime["subscription_id"], "--resource-group", runtime["resource_group"],
        "--workspace-name", runtime["workspace_name"],
    ]


def status_outcome(status: str) -> str:
    # Azure ML Jobs v2 spells successful execution Completed; ADO calls it Succeeded.
    if not isinstance(status, str):
        raise RuntimeError("Job status must be a string; refusing promotion")
    if status in {"Completed", "Succeeded"}:
        return "Succeeded"
    if status in FAILED:
        return "Failed"
    if status in ACTIVE:
        return "Running"
    raise RuntimeError(f"Missing/unknown job status {status!r}; refusing promotion")


def wait_for_job(az: str, scope: list[str], name: str, timeout: float,
                 interval: float, *, execute=run, clock=time.monotonic, sleep=time.sleep) -> dict:
    if not all(math.isfinite(x) and x > 0 for x in (timeout, interval)):
        raise ValueError("Timeout and polling interval must be finite and positive")
    deadline = clock() + timeout
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(f"Job {name} exceeded {timeout}s; job may still run; inspect/cancel explicitly")
        job = json.loads(execute(
            [az, "ml", "job", "show", "--name", name, *scope, "--output", "json"],
            timeout=min(120, remaining),
        ))
        if not isinstance(job, dict):
            raise ValueError("Job response must be a JSON object")
        status = job.get("status")
        print(f"{name}: {status}", file=sys.stderr)
        outcome = status_outcome(status)
        if outcome == "Succeeded":
            return job
        if outcome == "Failed":
            raise RuntimeError(f"Job {name} ended {status}; inspect protected Azure logs")
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(f"Job {name} exceeded {timeout}s; job may still run; inspect/cancel explicitly")
        sleep(min(interval, remaining))


def register_evaluated(name: str, runtime: dict, output: Path) -> dict:
    from ml_model_factory.azureml import register

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    model_name = manifest.get("model_name")
    if not isinstance(model_name, str) or not model_name:
        raise ValueError("Rendered manifest must contain model_name")
    # The core downloads the report, verifies its gate and lineage, then registers.
    return {"id": register(name, runtime, model_name), "job": name, "outcome": "Succeeded"}


def training_runtime(runtime: dict, scenario_path: str, run_id: str | None = None) -> dict:
    if "lake" not in runtime:
        if run_id:
            raise ValueError("--lake-run-id requires an optional runtime.lake configuration")
        return runtime
    from ml_model_factory.lake import LakeLayout

    if not isinstance(runtime["lake"], dict):
        raise ValueError("runtime.lake must be an object")
    effective = deepcopy(runtime)
    effective["lake"]["run_id"] = run_id if run_id is not None else ("ci-" + uuid4().hex)
    scenario = json.loads(Path(scenario_path).read_text(encoding="utf-8-sig"))
    LakeLayout.from_config(effective["lake"], scenario=scenario)
    return effective


def train(args) -> None:
    if not all(math.isfinite(x) and x > 0 for x in (args.timeout_seconds, args.poll_seconds)):
        raise ValueError("Timeout and polling interval must be finite and positive")
    runtime = json.loads(Path(args.runtime).read_text(encoding="utf-8-sig"))
    runtime = training_runtime(runtime, args.scenario, getattr(args, "lake_run_id", None))
    scope = target(runtime)
    az = shutil.which("az")
    if not az:
        raise RuntimeError("Azure CLI must be preinstalled on the configured self-hosted runner")
    if args.ml_extension_version != ML_EXTENSION_VERSION:
        raise ValueError(f"This template requires the tested ml extension {ML_EXTENSION_VERSION}")
    extension = run([az, "extension", "show", "--name", "ml", "--query", "version", "-o", "tsv"])
    if extension != args.ml_extension_version:
        raise RuntimeError(f"Expected ml extension {args.ml_extension_version}, found {extension}")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # A stale receipt must never be mistaken for this run's successful registration.
    receipt = output / "registered-model.json"
    receipt.unlink(missing_ok=True)
    bundle = output / ("bundle-" + uuid4().hex)
    runtime_path = args.runtime
    if "lake" in runtime:
        runtime_path = str(output / (bundle.name + "-runtime.json"))
        with Path(runtime_path).open("x", encoding="utf-8") as stream:
            json.dump(runtime, stream, indent=2, allow_nan=False)
            stream.write("\n")
    cli("validate", "--scenario", args.scenario, "--runtime", runtime_path)
    cli("render", "--scenario", args.scenario, "--runtime", runtime_path,
        "--output", str(bundle), "--mode", args.mode)
    job_path = bundle / "pipeline.yml"
    if not job_path.is_file():
        raise RuntimeError("Renderer did not produce pipeline.yml")
    name = run([az, "ml", "job", "create", "-f", str(job_path), *scope, "--query", "name", "-o", "tsv"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", name):
        raise RuntimeError(f"Azure CLI returned an invalid job name: {name!r}")
    (output / "submitted-job.json").write_text(
        json.dumps({"name": name, "bundle": str(bundle)}) + "\n", encoding="utf-8")
    wait_for_job(az, scope, name, args.timeout_seconds, args.poll_seconds)
    registered = register_evaluated(name, runtime, bundle)
    if not isinstance(registered, dict) or not registered.get("id"):
        raise RuntimeError("Register did not return a model resource id; refusing success receipt")
    receipt.write_text(json.dumps(registered, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(registered))


def deploy(args) -> None:
    from ml_model_factory.config import load_json, validate_runtime
    from ml_model_factory.serving import deploy as deploy_model

    if not args.approval_environment.strip():
        raise ValueError("An explicit preconfigured approval environment is required")
    runtime = validate_runtime(load_json(Path(args.runtime)))
    bundle = Path(args.output) / ("bundle-" + uuid4().hex)
    cli("validate", "--scenario", args.scenario, "--runtime", args.runtime)
    cli("render", "--scenario", args.scenario, "--runtime", args.runtime,
        "--output", str(bundle), "--mode", args.mode)
    endpoint = deploy_model(runtime, bundle, args.model_id, args.kind)
    print(json.dumps({"endpoint": endpoint, "model_id": args.model_id, "kind": args.kind}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--scenario", required=True)
    validate.add_argument("--runtime")
    ingestion = sub.add_parser("ingest")
    ingestion.add_argument("--scenario", required=True)
    ingestion.add_argument("--output", required=True)
    training = sub.add_parser("train")
    training.add_argument("--scenario", required=True)
    training.add_argument("--runtime", required=True)
    training.add_argument("--output", default="generated")
    training.add_argument("--mode", choices=("automl", "custom"), required=True)
    training.add_argument("--ml-extension-version", default=ML_EXTENSION_VERSION,
                          choices=(ML_EXTENSION_VERSION,))
    training.add_argument("--timeout-seconds", type=float, default=7200)
    training.add_argument("--poll-seconds", type=float, default=30)
    training.add_argument("--lake-run-id",
                          help="Intentional new lake execution ID; default generates a unique ID for every invocation")
    deployment = sub.add_parser("deploy")
    deployment.add_argument("--scenario", required=True)
    deployment.add_argument("--runtime", required=True)
    deployment.add_argument("--output", default="generated-deploy")
    deployment.add_argument("--mode", choices=("automl", "custom"), required=True)
    deployment.add_argument("--model-id", required=True)
    deployment.add_argument("--approval-environment", required=True)
    deployment.add_argument("--kind", choices=("online", "batch"), default="online")
    args = parser.parse_args()
    try:
        if args.action == "validate":
            extra = ["--runtime", args.runtime] if args.runtime else []
            print(cli("validate", "--scenario", args.scenario, *extra))
        elif args.action == "ingest":
            print(cli("ingest", "--scenario", args.scenario, "--output", args.output))
        elif args.action == "deploy":
            deploy(args)
        else:
            train(args)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr or exc.stdout or "", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
