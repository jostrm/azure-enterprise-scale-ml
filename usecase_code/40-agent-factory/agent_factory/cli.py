from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .azure import ARM, AzureSession
from .catalog import agent_catalog
from .config import FactoryConfig
from .discovery import discover, select_one
from .network import private_endpoint_checks, repair_foundry_dns


def load_selection(path: Path, key: str | None, *, variables_file: Path | None = None) -> tuple[dict, FactoryConfig, dict]:
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    targets = settings.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("Configuration requires a nonempty targets array.")
    keys = [item["key"] for item in targets]
    if len(set(keys)) != len(keys):
        raise ValueError("Target keys must be unique.")
    candidates = [item for item in targets if key is None or item["key"] == key]
    if len(candidates) != 1:
        raise ValueError(f"Select exactly one --target from: {', '.join(keys)}. Fleet-wide writes are disabled.")
    selected = candidates[0]
    variables = variables_file.resolve() if variables_file is not None else (path.parent / selected["variables_file"]).resolve()
    environment = selected.get("environment", "dev")
    config = FactoryConfig.load(variables, environment, selected.get("selection"))
    document = json.loads(variables.read_text(encoding="utf-8-sig"))
    values = document[environment] if environment in document else document["stage_prod"]
    return settings, config, values


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def summarize_response(response, spec: dict) -> dict:
    if response.status != "completed" or not response.output_text:
        raise RuntimeError("The agent did not complete with an answer; inspect tool approval or invocation status.")
    calls = []
    for item in response.output:
        if item.type != "mcp_call":
            continue
        if getattr(item, "error", None):
            raise RuntimeError("An agent MCP tool failed; the response is not accepted as successful grounding.")
        calls.append({"name": item.name, "server_label": item.server_label})
    accepted = {"knowledge_base_retrieve"}
    if spec.get("azure_inventory"):
        accepted.add("group_resource_list")
    if spec.get("grounding") and not any(item["name"] in accepted for item in calls):
        raise RuntimeError("The grounded agent answered without a successful Foundry IQ tool call.")
    return {"agent": spec["name"], "response_id": response.id, "text": response.output_text,
            "tool_calls": calls}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="OAuth-only, single-target AI Factory agent provisioning.")
    result.add_argument("command", choices=[
        "plan", "discover", "preflight", "repair-dns", "ingest",
        "configure-knowledge", "deploy", "invoke", "configure-datafactory",
        "start-datafactory", "poll-datafactory", "verify-datafactory",
        "approve-datafactory-link",
        "configure-azure-mcp",
    ])
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--target")
    result.add_argument("--agent", action="append", help="Exact catalog agent name; repeat for a subset.")
    result.add_argument("--include-hosted", action="store_true")
    result.add_argument("--apply", action="store_true", help="Authorize mutations for the selected command.")
    result.add_argument("--output", type=Path, help="Save the result as JSON.")
    result.add_argument("--input", help="Invocation text (never sent to external model providers).")
    result.add_argument("--timeout-seconds", type=int, default=900)
    result.add_argument("--data-factory", help="Explicit Data Factory name when more than one exists in the selected group.")
    result.add_argument("--run-id", help="Resume a specific existing Data Factory ingestion run.")
    result.add_argument("--connection-id", help="Exact pending private connection ID under the selected 2001 storage.")
    result.add_argument("--private-endpoint-id", help="Exact requester private endpoint ID read from that connection.")
    return result


def run(args: argparse.Namespace) -> dict | list:
    settings, config, values = load_selection(args.config.resolve(), args.target)
    tool_profile = settings.get("tool_profile", "default")
    if tool_profile not in {"default", "expanded-readonly"}:
        raise ValueError("tool_profile must be default or expanded-readonly.")
    catalog = agent_catalog(settings.get("agent_prefix", "aif"), expanded_tools=tool_profile == "expanded-readonly")
    for item in catalog:
        model = settings.get("model_overrides", {}).get(item["framework"])
        if model:
            item["model"] = model
    if args.agent:
        unknown = set(args.agent) - {item["name"] for item in catalog}
        if unknown:
            raise ValueError(f"Unknown catalog agents: {', '.join(sorted(unknown))}")
        catalog = [item for item in catalog if item["name"] in args.agent]
    if args.command == "plan":
        return {"target": config.__dict__, "agents": catalog, "mutations": False}
    if args.command in {
        "ingest", "configure-knowledge", "deploy", "configure-datafactory",
        "start-datafactory", "poll-datafactory",
        "approve-datafactory-link",
        "configure-azure-mcp",
    } and not args.apply:
        raise ValueError(f"{args.command} requires --apply. Use plan/discover/preflight first.")
    session = AzureSession(config.subscription_id, config.tenant_id)
    target = discover(config, session)
    if args.command == "discover":
        return target.to_dict()
    if args.command == "repair-dns":
        return repair_foundry_dns(
            session, target, dns_subscription_id=values["privDnsSubscription_param"],
            dns_resource_group=values["privDnsResourceGroup_param"], apply=args.apply,
        )
    state = args.config.parent / ".agent-factory" / target.account_name / target.project_name
    azure_tool = None
    if args.command == "configure-azure-mcp" or (args.command == "deploy" and tool_profile == "expanded-readonly"):
        from .mcp_control import build_mcp_plan
        from .mcp_connection import configure_mcp_connection
        identity = json.loads((args.config.parent / "azure-mcp-identity.json").read_text(encoding="utf-8"))
        mcp = configure_mcp_connection(
            session, target, build_mcp_plan(target, settings.get("azure_mcp", {})), identity,
            apply=args.command == "configure-azure-mcp",
        )
        if args.command == "configure-azure-mcp":
            write_json(state / "azure-mcp-connection.json", mcp)
            return mcp
        if not mcp["connection_ready"]:
            raise RuntimeError("Run configure-azure-mcp --apply before deploying expanded agents.")
        azure_tool = mcp["tool"]
    if args.command == "approve-datafactory-link":
        from .datafactory import approve_storage_connection
        if not args.connection_id or not args.private_endpoint_id:
            raise ValueError("Approval requires explicit --connection-id and --private-endpoint-id.")
        return approve_storage_connection(
            session, target, connection_id=args.connection_id, expected_private_endpoint_id=args.private_endpoint_id,
        )
    if args.command.endswith("-datafactory"):
        from .datafactory import (
            ADF_API, configure_datafactory_ingestion, poll_datafactory_ingestion,
            start_datafactory_ingestion, verify_datafactory_index,
        )
        if args.command == "verify-datafactory":
            return verify_datafactory_index(session, target)
        resources = session.pages(f"{ARM}{target.group_id}/resources?api-version=2021-04-01")
        factory = select_one(
            [item for item in resources if item["type"].lower() == "microsoft.datafactory/factories"],
            "Data Factory", args.data_factory or "",
        )
        factory_name = factory["name"]
        if args.command == "configure-datafactory":
            result = configure_datafactory_ingestion(session, target, factory_name=factory_name)
            write_json(state / "datafactory.json", {"target": target.to_dict(), **result})
            return result
        ingestion_path = state / "ingestion.json"
        saved = json.loads(ingestion_path.read_text(encoding="utf-8")) if ingestion_path.exists() else {}
        if saved and (saved.get("target") != target.to_dict() or saved.get("factory_name") != factory_name):
            raise RuntimeError("Saved ingestion run belongs to a different target or Data Factory.")
        if args.command == "start-datafactory":
            if saved.get("status") == "running":
                existing = session.arm("GET", f"{factory['id']}/pipelineruns/{saved['run_id']}", api_version=ADF_API)
                if existing.get("status") not in {"Succeeded", "Failed", "Cancelled"}:
                    raise RuntimeError(f"Ingestion run {saved['run_id']} is not terminal; resume polling instead.")
            result = start_datafactory_ingestion(session, target, factory_name=factory_name)
        else:
            run_id = args.run_id or saved.get("run_id")
            if not run_id:
                raise ValueError("No ingestion run is recorded. Start once, then poll that run ID.")
            result = poll_datafactory_ingestion(
                session, target, factory_name=factory_name, run_id=run_id, timeout_seconds=args.timeout_seconds,
            )
        write_json(ingestion_path, {"target": target.to_dict(), **result})
        return result
    checks = private_endpoint_checks(target)
    if not all(item["private"] and item["reachable"] for item in checks):
        raise RuntimeError("Private endpoint preflight failed. Reconnect the VPN if it stopped; "
                           "otherwise repair hub DNS. No public-network fallback.\n" + json.dumps(checks, indent=2))
    if args.command == "preflight":
        # Explicit audience/subscription token handling is essential in multi-tenant CLI sessions.
        agents = session.request("GET", f"{target.project_endpoint}/agents?api-version=v1",
                                 audience="https://ai.azure.com")
        indexes = session.request("GET", f"{target.search_endpoint}/indexes?api-version=2025-09-01",
                                  audience="https://search.azure.com")
        return {"target": target.to_dict(), "network": checks, "foundry_access": True,
                "search_indexes": [item["name"] for item in indexes["value"]],
                "agent_count_on_page": len(agents.get("data", agents.get("value", [])))}
    if args.command == "ingest":
        from .data import ingest
        return ingest(target)
    if args.command == "configure-knowledge":
        from .knowledge import configure_knowledge, verify_retrieval
        knowledge_kwargs = {}
        if settings.get("ingestion", {}).get("mode") == "datafactory":
            ingestion_path = state / "ingestion.json"
            if not ingestion_path.exists():
                raise RuntimeError("Run and verify Data Factory ingestion before configuring Foundry IQ.")
            ingestion = json.loads(ingestion_path.read_text(encoding="utf-8"))
            if (ingestion.get("target") != target.to_dict() or ingestion.get("status") != "ingested"
                    or ingestion.get("corpus_sha256_verified") is not True):
                raise RuntimeError("Data Factory ingestion is not verified for the selected target.")
            knowledge_kwargs = ingestion["knowledge_kwargs"]
        result = configure_knowledge(session, target, **knowledge_kwargs)
        result.update(verify_retrieval(session, target, args.input or "How do I reset my password?"))
        write_json(state / "knowledge.json", result)
        return result
    from .prompt import deploy_prompt, project_client
    with project_client(session, target) as project:
        if args.command == "invoke":
            if len(catalog) != 1 or not args.input:
                raise ValueError("invoke requires exactly one --agent and --input.")
            with project.get_openai_client(agent_name=catalog[0]["name"]) as client:
                response = client.responses.create(input=args.input, store=False)
                return summarize_response(response, catalog[0])
        if args.command == "deploy":
            selected = [item for item in catalog
                        if item["kind"] == "prompt" or args.include_hosted or args.agent]
            knowledge_path = state / "knowledge.json"
            knowledge = json.loads(knowledge_path.read_text(encoding="utf-8")) if knowledge_path.exists() else {}
            if any(spec.get("grounding") or spec.get("knowledge_tool") for spec in selected):
                if not knowledge.get("retrieval_verified") or not str(knowledge.get("connection_id", "")).startswith(
                    target.project_id + "/connections/"
                ):
                    raise RuntimeError("Configure and verify Foundry IQ for this exact target before deploying its grounded agent.")
            deployment_path = state / "deployment.json"
            previous = json.loads(deployment_path.read_text(encoding="utf-8")) if deployment_path.exists() else {}
            if previous and previous.get("target") != target.to_dict():
                raise RuntimeError("Deployment state belongs to a different target or resource configuration.")
            inventory = {item["name"]: item for item in previous.get("completed", [])}
            results = []
            for spec in selected:
                if spec["kind"] == "prompt":
                    result = deploy_prompt(project, target, spec, knowledge.get("tool"), azure_tool)
                else:
                    from .hosted import deploy_hosted
                    result = deploy_hosted(project, target, spec, output_dir=state / "packages",
                                           timeout_seconds=args.timeout_seconds)
                results.append(result)
                inventory[result["name"]] = result
                write_json(deployment_path, {
                    "target": target.to_dict(), "completed": list(inventory.values()),
                    "completed_this_run": results,
                    "requested": [item["name"] for item in selected],
                })
            return {"target": target.to_dict(), "agents": results}
    raise ValueError(f"Unsupported command: {args.command}")


def main() -> int:
    if sys.argv[1:2] == ["monitoring-export"]:
        from .monitoring import main as monitoring_main
        return monitoring_main(sys.argv[2:])
    args = parser().parse_args()
    result = run(args)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
