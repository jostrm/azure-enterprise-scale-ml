"""Prepare the secretless caller identity or deploy the private MCP infrastructure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.azure import AzureSession
from agent_factory.cli import load_selection, write_json
from agent_factory.discovery import discover
from agent_factory.mcp_control import (
    build_mcp_parameters, build_mcp_plan, preflight_mcp, prepare_mcp_identity,
)


def enabled(value) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false" or value is None:
        return False
    raise ValueError("Enable and DNS ownership settings must be true or false.")


def run(args):
    settings, config, values = load_selection(
        args.config.resolve(), args.target, variables_file=args.variables_file,
    )
    for expected, actual, label in (
        (args.expected_subscription, config.subscription_id, "subscription"),
        (args.expected_project, config.project_number, "project"),
        (args.expected_environment, config.environment, "environment"),
    ):
        if expected is not None and (expected.zfill(3) if label == "project" else expected).lower() != actual.lower():
            raise ValueError(f"MCP configuration does not match the pipeline's selected {label}.")
    if args.command in {"prepare-identity", "deploy"} and not args.apply:
        raise ValueError(f"{args.command} requires --apply.")
    if args.command in {"validate", "deploy"} and not enabled(values.get("enableAzureMcpServer")):
        raise ValueError("The selected environment must explicitly enable enableAzureMcpServer.")
    session = AzureSession(config.subscription_id, config.tenant_id)
    target = discover(config, session)
    plan = build_mcp_plan(target, settings.get("azure_mcp", {}))
    checked = preflight_mcp(session, target, plan)
    identity_path = args.identity_file or args.config.resolve().parent / "azure-mcp-identity.json"
    if args.command == "plan":
        return {"plan": plan, "preflight": checked, "mutations": False}
    if args.command == "prepare-identity":
        identity = prepare_mcp_identity(session, target, plan, apply=True)
        write_json(identity_path, identity)
        return {"identity_file": str(identity_path), **identity}
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if identity.get("project_principal_id", "").lower() != checked["project_principal_id"].lower():
        raise ValueError("The prepared identity belongs to a different Foundry project identity.")
    parameters = build_mcp_parameters(
        target, plan, identity,
        central_dns_zone_by_policy_in_hub=enabled(values.get("centralDnsZoneByPolicyInHub")),
    )
    root = args.repository_root or Path(__file__).resolve().parents[3]
    template = root / "environment_setup" / "aifactory" / "bicep" / "esml-genai-1" / "08-azure-mcp.bicep"
    if not template.is_file():
        raise ValueError("Use --repository-root to select the central repository containing 08-azure-mcp.bicep.")
    az = shutil.which("az")
    if not az:
        raise RuntimeError("Azure CLI is required for the reviewed Bicep deployment.")
    with tempfile.TemporaryDirectory(prefix="aif-mcp-parameters-") as directory:
        parameter_path = Path(directory) / "parameters.json"
        write_json(parameter_path, parameters)
        command = [
            az, "deployment", "sub", "validate" if args.command == "validate" else "create",
            "--subscription", target.subscription_id,
            "--location", target.location, "--name", f"{plan['name']}-private-mcp",
            "--template-file", str(template), "--parameters", f"@{parameter_path}",
            "--only-show-errors", "--output", "json",
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=3600, check=False,
        )
        if completed.returncode:
            raise RuntimeError("Private MCP deployment failed:\n" + completed.stderr.strip())
        deployment = json.loads(completed.stdout)
    if args.command == "validate":
        if deployment.get("error") or deployment.get("properties", {}).get("error"):
            raise RuntimeError("ARM validation returned a deployment error: " + json.dumps(deployment))
        return {"target": target.to_dict(), "arm_validation": deployment, "mutations": False}
    if deployment.get("properties", {}).get("provisioningState") != "Succeeded":
        raise RuntimeError("Private MCP deployment did not report Succeeded.")
    result = {
        "target": target.to_dict(), "plan": plan, "identity": identity,
        "deployment_id": deployment["id"],
        "outputs": {key: item["value"] for key, item in deployment["properties"]["outputs"].items()},
        "status": "infrastructure-deployed-not-yet-validated",
    }
    state = args.config.resolve().parent / ".agent-factory" / target.account_name / target.project_name
    write_json(state / "azure-mcp.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "prepare-identity", "validate", "deploy"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--target")
    parser.add_argument("--identity-file", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--variables-file", type=Path, help="Exact reviewed variables JSON materialized by the pipeline.")
    parser.add_argument("--expected-subscription")
    parser.add_argument("--expected-project")
    parser.add_argument("--expected-environment")
    parser.add_argument("--apply", action="store_true")
    print(json.dumps(run(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
