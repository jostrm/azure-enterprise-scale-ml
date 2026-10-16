"""Example 49 CLI: plan-bound, agent-driven ML training, retraining and batch inference.

Generated configuration, data, receipts and agent state are consumer-owned and stay outside
this template. Every Azure write needs an approved plan (--approved-plan, --plan-sha256) plus
--apply; charged operations also need --allow-paid.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_agent.configuration import external, load_config, make_config, paths, read_json, write_json  # noqa: E402
from ml_agent.usecases import AIR, CHURN  # noqa: E402

LIVE = {"create-usecase", "train", "retrain", "infer", "deploy", "ask"}
DEMOS = {
    "uc1": (f"Create the telco churn prediction use case {CHURN} from scratch as model M49 in project001 using "
            "synthetic data, train it with the custom pipeline, then score the new synthetic customers and "
            "summarize who is predicted to churn."),
    "uc2": (f"Retrain the existing {AIR} model, tell me whether the new model replaced the champion, then run "
            "batch inference and summarize the forecasts."),
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("command", choices=[
        "init-config", "plan", "prepare-local", "offline", "status", "preflight",
        "create-usecase", "train", "retrain", "infer", "deploy", "ask",
    ])
    result.add_argument("--config", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--factory-config", type=Path)
    result.add_argument("--target")
    result.add_argument("--orange-root", type=Path)
    result.add_argument("--reviewed-rollout", type=Path)
    result.add_argument("--champion-receipts", type=Path)
    result.add_argument("--project-endpoint")
    result.add_argument("--model-deployment")
    result.add_argument("--state-root", type=Path)
    result.add_argument("--usecase", choices=[CHURN, AIR])
    result.add_argument("--fresh", action="store_true", help="Plan the next synthetic data version.")
    result.add_argument("--work", type=Path, help="New or empty folder for the offline reproduction.")
    result.add_argument("--approved-plan", type=Path)
    result.add_argument("--plan-sha256")
    result.add_argument("--apply", action="store_true")
    result.add_argument("--allow-paid", action="store_true")
    result.add_argument("--question")
    result.add_argument("--demo", choices=sorted(DEMOS))
    return result


def _plan_from_args(args, config: dict) -> dict:
    from ml_agent.plan import approved_plan

    if not args.approved_plan or not args.plan_sha256:
        raise PermissionError(f"{args.command} needs --approved-plan and --plan-sha256 from an approved `plan`.")
    return approved_plan(args.approved_plan, args.plan_sha256, config)


def _project_client(config: dict):
    from agent_factory.azure import AzureSession
    from agent_factory.cli import load_selection
    from agent_factory.discovery import discover
    from agent_factory.prompt import project_client

    _, factory, _ = load_selection(Path(config["factory_config"]), config["target"])
    if factory.tenant_id != config["tenant_id"] or factory.subscription_id != config["subscription_id"]:
        raise ValueError("The factory target changed scope; refusing to contact Foundry.")
    session = AzureSession(factory.subscription_id, factory.tenant_id)
    target = discover(factory, session)
    if target.project_endpoint != config["project_endpoint"]:
        raise ValueError("Discovered project endpoint differs from the pinned consumer configuration.")
    return project_client(session, target)


def run(args) -> dict:
    if args.command == "init-config":
        from agent_factory.cli import load_selection

        required = (args.factory_config, args.target, args.orange_root, args.reviewed_rollout,
                    args.champion_receipts, args.project_endpoint, args.model_deployment, args.state_root, args.output)
        if not all(required):
            raise ValueError("init-config needs factory-config, target, orange-root, reviewed-rollout, "
                             "champion-receipts, project-endpoint, model-deployment, state-root and output.")
        destination = external(args.output)
        if destination.exists():
            raise ValueError("Consumer configuration already exists; review it rather than replacing it.")
        _, factory, _ = load_selection(args.factory_config.resolve(), args.target)
        config = make_config(factory, factory_config=args.factory_config, target=args.target,
                             orange_root=args.orange_root, reviewed_rollout=args.reviewed_rollout,
                             project_endpoint=args.project_endpoint, model_deployment=args.model_deployment,
                             state_root=external(args.state_root), champion_receipts=args.champion_receipts)
        write_json(destination, config)
        return {"config": str(destination), "owner": config["owner"], "cloud_mutations": False}
    if not args.config:
        raise ValueError(f"{args.command} requires --config.")
    config = load_config(args.config)
    location = paths(config)
    if args.command == "plan":
        from ml_agent.plan import build_plan, save_plan

        plan = build_plan(config, fresh=args.fresh)
        path, digest = save_plan(config, plan)
        return {"plan": str(path), "plan_sha256": digest, "azure_writes": plan["azure_writes"],
                "usecases": {name: {key: entry[key] for key in ("model_name", "data_version", "train_run_id",
                                                               "inference_run_id", "compute")}
                             for name, entry in plan["usecases"].items()},
                "approve_with": f"--approved-plan \"{path}\" --plan-sha256 {digest} --apply --allow-paid"}
    if args.command == "prepare-local":
        from ml_agent.plan import build_plan
        from ml_agent.runtime import MLRuntime, redact

        plan = _plan_from_args(args, config) if args.approved_plan else build_plan(config)
        return redact(MLRuntime(config).prepare_local(plan))
    if args.command == "offline":
        from ml_agent.factory import offline_demo
        from ml_agent.runtime import redact

        if not args.work:
            raise ValueError("offline requires --work with a new or empty folder.")
        settings = config["usecases"][CHURN]
        return redact(offline_demo(location, external(args.work), rows=settings["inference_rows"],
                                   seed=settings["inference_seed"]))
    if args.command == "preflight":
        from ml_agent.connectivity import preflight
        from ml_agent.runtime import redact

        return redact(preflight(config))
    from ml_agent.runtime import MLRuntime, redact

    plan = _plan_from_args(args, config) if (args.command in LIVE or args.approved_plan) else None
    runtime = MLRuntime(config, plan=plan, apply=args.apply, allow_paid=args.allow_paid)
    if args.command == "status":
        names = [args.usecase] if args.usecase else [CHURN, AIR]
        return {name: runtime.status(name) for name in names}
    if args.command in {"create-usecase", "train", "retrain", "infer"}:
        if not args.usecase:
            raise ValueError(f"{args.command} requires --usecase.")
        method = {"create-usecase": runtime.create_usecase, "train": runtime.train,
                  "retrain": runtime.retrain, "infer": runtime.infer}[args.command]
        return method(args.usecase)
    from ml_agent.agent import deploy_agent, invoke_agent

    deployed_path = location.state / "agent.json"
    with _project_client(config) as project:
        if args.command == "deploy":
            result = deploy_agent(project, config, apply=args.apply, allow_paid=args.allow_paid)
            write_json(deployed_path, result)
            return result
        question = DEMOS[args.demo] if args.demo else args.question
        result = invoke_agent(project, runtime, question, deployment=read_json(deployed_path),
                              allow_paid=args.allow_paid)
        transcripts = location.state / "transcripts"
        write_json(transcripts / f"{args.demo or 'ask'}-{len(list(transcripts.glob('*.json'))) + 1:03d}.json",
                   {"question": question, **redact(result)})
        return redact(result)


def main(argv=None) -> int:
    try:
        print(json.dumps(run(parser().parse_args(argv)), indent=2, default=str))
        return 0
    except (ValueError, PermissionError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
