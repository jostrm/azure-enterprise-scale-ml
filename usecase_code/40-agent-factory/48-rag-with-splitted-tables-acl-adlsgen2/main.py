"""Approval-gated split-table sales demo. All generated state is consumer-owned."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.azure import AzureSession
from agent_factory.cli import load_selection, write_json
from sales_demo.configuration import load_config, make_config, read_json, readiness
from sales_demo.deployment import preflight, publication_plan, publish, StorageWriter


MUTATIONS = {"publish", "configure", "ingest", "deploy", "resync", "images-configure"}
PAID = {"configure", "ingest", "deploy", "ask", "evaluate", "images-configure", "images-ask"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=[
        "generate", "init-config", "plan", "discover", "publish", "configure", "ingest",
        "verify", "deploy", "ask", "evaluate", "resync", "images-plan", "images-configure", "images-ask",
    ])
    result.add_argument("--config", type=Path)
    result.add_argument("--factory-config", type=Path)
    result.add_argument("--source-bindings", type=Path)
    result.add_argument("--source-key")
    result.add_argument("--target")
    result.add_argument("--artifacts-root", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--version", default="v1")
    result.add_argument("--seed", type=int, default=48)
    result.add_argument("--input")
    result.add_argument("--oracle", type=Path)
    result.add_argument("--user-profile", type=Path, help="Existing separately signed-in Azure CLI profile.")
    result.add_argument("--restricted-profile", type=Path, help="Distinct restricted user's existing Azure CLI profile.")
    result.add_argument("--apply", action="store_true")
    result.add_argument("--allow-paid", action="store_true")
    result.add_argument("--update-config", action="store_true")
    result.add_argument("--timeout-seconds", type=int, default=900)
    return result


def external_output(path: Path) -> Path:
    path = path.resolve()
    template = Path(__file__).resolve().parent
    if path == template or path.is_relative_to(template):
        raise ValueError("Keep generated data, configuration and state outside the replaceable template.")
    return path


def operator(config: dict):
    _, factory, _ = load_selection(Path(config["factory_config"]), config["target"])
    if (factory.tenant_id != config["tenant_id"] or factory.subscription_id != config["subscription_id"]
            or f"project{factory.project_number}" != config["project"] or factory.environment != config["environment"]):
        raise ValueError("Factory configuration changed scope; refusing this publication.")
    return AzureSession(factory.subscription_id, factory.tenant_id), factory


def state_path(config_path: Path, config: dict, name: str) -> Path:
    return external_output(config_path.resolve().parent / ".agent-factory" / config["owner"] / config["version"] / name)


def run(args) -> dict:
    if args.command in MUTATIONS and not args.apply:
        raise ValueError(f"{args.command} requires --apply after explicit approval of the plan.")
    if args.command in PAID and not args.allow_paid:
        raise ValueError(f"{args.command} may incur charges; explicit --allow-paid approval is required.")
    if args.command == "evaluate" and (not args.oracle or not args.restricted_profile):
        raise ValueError("evaluate requires --oracle and a separately authenticated --restricted-profile before paid calls.")
    if args.command == "generate":
        if not args.output:
            raise ValueError("generate requires --output outside the template.")
        from sales_demo.dataset import generate
        return generate(external_output(args.output), version=args.version, seed=args.seed)
    if args.command == "init-config":
        if not all((args.factory_config, args.target, args.source_bindings, args.source_key,
                    args.artifacts_root, args.output)):
            raise ValueError("init-config requires factory-config, target, source-bindings, source-key, artifacts-root and output.")
        destination = external_output(args.output)
        if destination.exists():
            raise ValueError("Consumer configuration already exists; review it rather than replacing it.")
        _, factory, _ = load_selection(args.factory_config.resolve(), args.target)
        sources = read_json(args.source_bindings)["sources"]
        if args.source_key not in sources:
            raise ValueError("Select one exact existing common-lake binding.")
        value = make_config(
            factory, sources[args.source_key]["binding"], external_output(args.artifacts_root),
            args.factory_config, args.target,
        )
        write_json(destination, value)
        return {"config": str(destination), "state": "draft", "cloud_mutations": False}
    if not args.config:
        raise ValueError(f"{args.command} requires --config.")
    config = load_config(args.config.resolve())
    if config.get("graph_sync") and args.command in {"publish", "configure", "ingest", "resync"}:
        raise ValueError("Graph-bound publications must be changed through sync.py's serialized reconciliation.")
    if args.command == "plan":
        from sales_demo.search import build_definitions
        result = {
            "owner": config["owner"], "dataset": config["dataset"], "version": config["version"],
            "storage": publication_plan(config), "remaining": readiness(config),
            "search": build_definitions(config) if config.get("embedding_endpoint") else None,
            "image": "Separate isolated storage account/configuration required; no sales content.",
            "cloud_mutations": False, "paid_calls": False, "live_success": False,
        }
        if args.output:
            write_json(external_output(args.output), result)
        return result
    if args.command == "discover":
        session, factory = operator(config)
        report = preflight(config, session, factory)
        if args.update_config:
            value = read_json(args.config)
            for key in ("search_endpoint", "embedding_endpoint", "project_endpoint", "search_identity_object_id"):
                value[key] = report[key]
            value["factory_target"] = report["target"]
            write_json(args.config.resolve(), value)
        if args.output:
            write_json(external_output(args.output), report)
        return report
    if args.command == "publish":
        session, factory = operator(config)
        report = preflight(config, session, factory)
        if not report["acl_test_ready"]:
            raise ValueError("Broad-role/identity preflight did not establish a valid ACL test boundary.")
        result = publish(config, StorageWriter(config, session), apply=args.apply)
        write_json(state_path(args.config, config, "publication-copy.json"), result)
        return result
    return run_services(args, config)


def run_services(args, config: dict) -> dict:
    from sales_demo.search import SearchClient
    from sales_demo.identity import AzureCliTokenProvider, DelegatedAuthorization, ManagedIdentitySearchTransport
    from sales_demo.runtime import DelegatedRowStore, SalesRuntime

    def authorization(profile=None):
        return DelegatedAuthorization(config["tenant_id"], AzureCliTokenProvider(
            config["tenant_id"], config["subscription_id"], config_dir=profile,
        ))

    def runtime(profile=None):
        return SalesRuntime(
            config, read_json(external_output(Path(config["publication_state"]))),
            authorization(profile), DelegatedRowStore(config),
            SearchClient(config, ManagedIdentitySearchTransport(config)),
        )

    if args.command.startswith("images-"):
        from sales_demo.images import ImageClient, build_image_definitions
        image = config.get("image")
        if not isinstance(image, dict):
            raise ValueError("Configure an approved isolated synthetic image branch first.")
        if (config["storage_resource_id"].casefold() not in {
            value.casefold() for value in image.get("protected_storage_resource_ids", [])
        } or image.get("search_endpoint") != config["search_endpoint"]
                or image.get("owner") != config["owner"] or image.get("version") != config["version"]):
            raise ValueError("The image branch must preserve task ownership and explicitly exclude this protected lake.")
        if args.command == "images-plan":
            return build_image_definitions(image)
        session, _ = operator(config)
        from agent_factory.data import require_private_endpoint
        require_private_endpoint(image["search_endpoint"])
        client = ImageClient(image, session)
        result = client.configure(apply=args.apply) if args.command == "images-configure" else client.retrieve(
            args.input, execute=args.allow_paid,
        )
        write_json(state_path(args.config, config, args.command + ".json"), result)
        return result

    unresolved = readiness(config)
    if unresolved:
        raise ValueError("Service prerequisites unresolved: " + " ".join(unresolved))
    if not 1 <= args.timeout_seconds <= 3600:
        raise ValueError("--timeout-seconds must be between 1 and 3600.")
    poll_seconds = min(30, max(1, (args.timeout_seconds + 119) // 120))
    polls = max(1, args.timeout_seconds // poll_seconds)

    if args.command in {"configure", "ingest", "resync"}:
        session, factory = operator(config)
        report = preflight(config, session, factory)
        if not report["acl_test_ready"]:
            raise ValueError("Broad-role/identity preflight did not establish the ACL test boundary.")
        if not report["outbound_private_links_ready"] or not report["backend_permissions_ready"]:
            raise ValueError("Approve the missing outbound private links and read-only backend permissions before indexing.")
        client = SearchClient(config, session)
        # Invalidate old evidence BEFORE a possible mutation or uncertain network result.
        write_json(external_output(Path(config["publication_state"])), {
            "state": "pending", "operation": args.command, "owner": config["owner"],
            "dataset": config["dataset"], "version": config["version"],
        })
        if args.command == "configure":
            result = client.configure(apply=args.apply)
            # Creating a Search indexer may run it automatically and incur embedding charges.
            result["indexing"] = client.wait(max_polls=polls, poll_seconds=poll_seconds)
        else:
            if args.command == "resync":
                client.resync_permissions(apply=args.apply)
            else:
                client.run_indexers(apply=args.apply)
            result = {"indexing": client.wait(max_polls=polls, poll_seconds=poll_seconds)}
        write_json(state_path(args.config, config, args.command + ".json"), result)
        return result

    if args.command == "verify":
        from sales_demo.verification import verify_publication
        output = external_output(args.output or state_path(args.config, config, "chunk-evidence"))
        result = verify_publication(
            config, authorization(args.user_profile), DelegatedRowStore(config),
            SearchClient(config, ManagedIdentitySearchTransport(config)), output,
        )
        write_json(external_output(Path(config["publication_state"])), result)
        return result

    from agent_factory.prompt import project_client
    from agent_factory.discovery import discover
    from sales_demo.agent import deploy_agent, invoke_agent
    from sales_demo.evaluation import evaluate_live
    session, factory = operator(config)
    target = discover(factory, session)
    if target.project_endpoint != config["project_endpoint"]:
        raise ValueError("Discovered project endpoint differs from the pinned consumer configuration.")
    deployed_path = state_path(args.config, config, "agent.json")
    with project_client(session, target) as project:
        if args.command == "deploy":
            service = runtime(args.user_profile)
            service.aggregate_sales("all")
            result = deploy_agent(
                project, config, name=f"{config['owner']}-{config['version']}-sales",
                model=config["model_deployment"], apply=args.apply, allow_paid=args.allow_paid,
            )
            write_json(deployed_path, result)
            return result
        deployed = read_json(deployed_path)
        service = runtime(args.user_profile)
        if args.command == "ask":
            return invoke_agent(project, service, args.input, deployment=deployed, allow_paid=args.allow_paid)
        if args.command == "evaluate":
            restricted = runtime(args.restricted_profile)
            full_identity, restricted_identity = service.authorization.authorize(), restricted.authorization.authorize()
            if restricted_identity.oid not in config["denied_test_user_ids"]:
                raise ValueError("Restricted profile does not identify an explicitly configured ACL-test principal.")
            principals = {
                full_identity.oid, restricted_identity.oid,
                *full_identity.group_ids, *restricted_identity.group_ids,
            }
            report = preflight({**config, "acl_test_principal_ids": sorted(principals)}, session, factory)
            if not report["acl_test_ready"]:
                raise ValueError("Live principals have broad Storage data roles; native ACL evaluation is blocked.")
            result = evaluate_live(
                project, service, deployed, args.oracle, allow_paid=args.allow_paid,
                restricted_runtime=restricted,
                restricted_deployment=deployed, restricted_project=project,
            )
            write_json(external_output(args.output or state_path(args.config, config, "evaluation.json")), result)
            return result
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2))
