"""Single-user CLI preview. Native authorization stays on; complete ACL acceptance stays false."""
import argparse
import json
from pathlib import Path

import main as common
from agent_factory.cli import write_json
from agent_factory.discovery import discover
from agent_factory.prompt import project_client
from sales_demo.configuration import load_config, read_json, readiness
from sales_demo.deployment import StorageWriter, preflight, publication_plan, publish
from sales_demo.operator_preview import (
    PreviewSearchTransport, preview_authorization, require_preview_policy,
    summarize_preview_evaluation, verified_preview_identity,
)
from sales_demo.search import SearchClient, build_definitions

COMMANDS = {"plan", "publish", "configure", "ingest", "verify", "deploy", "ask", "evaluate", "resync"}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=sorted(COMMANDS))
    result.add_argument("--config", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--oracle", type=Path)
    result.add_argument("--input")
    result.add_argument("--apply", action="store_true")
    result.add_argument("--allow-paid", action="store_true")
    result.add_argument("--timeout-seconds", type=int, default=900)
    return result


def run(args):
    if args.command in common.MUTATIONS and not args.apply:
        raise ValueError(f"{args.command} requires --apply.")
    if args.command in common.PAID and not args.allow_paid:
        raise ValueError(f"{args.command} requires --allow-paid.")
    if not args.config:
        raise ValueError("An explicit preview --config is required.")
    config = load_config(args.config.resolve())
    user = require_preview_policy(config)
    if args.command == "plan":
        result = {
            "scope": "operator-preview", "operator_user_id": user,
            "publication": publication_plan(config), "search": build_definitions(config),
            "remaining": readiness(config, require_acl_test=False),
            "complete_acl_acceptance": False, "mutations": False, "paid_calls": False,
            "limitations": [
                "Existing operator credentials authorize the CLI backend; this does not test a managed-identity backend.",
                "Native user authorization remains enabled, but a privileged user does not prove ACL restrictions.",
                "Foundry Playground does not execute these local function tools.",
            ],
        }
        if args.output:
            write_json(common.external_output(args.output), result)
        return result
    unresolved = readiness(config, require_acl_test=False)
    if unresolved:
        raise ValueError("Preview prerequisites unresolved: " + " ".join(unresolved))
    if not 1 <= args.timeout_seconds <= 3600:
        raise ValueError("Polling timeout must be between 1 and 3600 seconds.")
    if args.command == "evaluate" and not args.oracle:
        raise ValueError("Evaluation requires the independent --oracle.")
    session, factory = common.operator(config)
    authorization = preview_authorization(config, session)
    verified_preview_identity(config, authorization)
    from sales_demo.runtime import DelegatedRowStore, SalesRuntime
    source = DelegatedRowStore(config)
    search = SearchClient(config, PreviewSearchTransport(config, session))
    state_file = common.external_output(Path(config["publication_state"]))

    def runtime():
        return SalesRuntime(config, read_json(state_file), authorization, source, search)

    if args.command in {"publish", "configure", "ingest", "resync"}:
        report = preflight(config, session, factory)
        if not report["outbound_private_links_ready"] or not report["backend_permissions_ready"]:
            raise ValueError("The existing private links and backend permissions must be ready.")
        write_json(common.state_path(args.config, config, "operator-preflight.json"), {
            **report, "evaluation_mode": "operator-preview", "complete_acl_acceptance": False,
            "operator_user_id": user,
        })
        write_json(state_file, {"state": "pending", "operation": args.command, "operator_preview": True})
        if args.command == "publish":
            result = publish(config, StorageWriter(config, session), apply=True, single_user_preview=True)
        else:
            admin = SearchClient(config, session)
            if args.command == "configure":
                admin.configure(apply=True)
            elif args.command == "ingest":
                admin.run_indexers(apply=True)
            else:
                admin.resync_permissions(apply=True)
            interval = min(30, max(1, (args.timeout_seconds + 119) // 120))
            result = {"indexing": admin.wait(max_polls=max(1, args.timeout_seconds // interval),
                                             poll_seconds=interval)}
        write_json(common.state_path(args.config, config, "preview-" + args.command + ".json"), result)
        return result
    if args.command == "verify":
        from sales_demo.verification import verify_publication
        output = common.external_output(args.output or common.state_path(args.config, config, "chunk-evidence"))
        result = verify_publication(config, authorization, source, search, output)
        result.update({"operator_preview": True, "complete_acl_acceptance": False,
                       "backend_identity_mode": "operator-not-managed-identity"})
        write_json(state_file, result)
        return result
    from sales_demo.agent import deploy_agent, invoke_agent
    from sales_demo.evaluation import evaluate_live
    target = discover(factory, session)
    if target.project_endpoint != config["project_endpoint"]:
        raise ValueError("Configured and discovered Foundry endpoints differ.")
    deployed_path = common.state_path(args.config, config, "agent.json")
    with project_client(session, target) as project:
        if args.command == "deploy":
            runtime().aggregate_sales("all")
            result = deploy_agent(
                project, config, name=f"{config['owner']}-{config['version']}-sales",
                model=config["model_deployment"], apply=True, allow_paid=True,
            )
            write_json(deployed_path, result)
            return result
        deployment = read_json(deployed_path)
        if args.command == "ask":
            return invoke_agent(project, runtime(), args.input, deployment=deployment, allow_paid=True)
        if args.command == "evaluate":
            result = summarize_preview_evaluation(evaluate_live(
                project, runtime(), deployment, args.oracle, allow_paid=True,
            ))
            output = common.external_output(args.output or common.state_path(args.config, config, "preview-evaluation.json"))
            write_json(output, result)
            return result
    raise ValueError("Unsupported preview command.")


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2))
