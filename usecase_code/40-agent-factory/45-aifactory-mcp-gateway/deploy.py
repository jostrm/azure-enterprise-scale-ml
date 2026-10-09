"""Late project-pipeline step for the opt-in AI Factory MCP and AI Gateway SKU (project001 Dev).

Reads the pipeline variables by their exact names from the environment, validates them offline, and
then plans (GET only) or applies (owned writes only). Disabled flags and Stage/Prod runs exit cleanly
without contacting Azure; invalid combinations fail instead of being ignored.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.azure import AzureSession  # noqa: E402
from agent_factory.mcp_gateway import IntegrationRequest, McpGatewayIntegration, decide  # noqa: E402

INPUTS = (
    "enableAIFactoryMCP", "enableAIGatewaySKU", "addAIFactoryMCP2AIGatewaySKU",
    "enableContainerApps", "enableAIFoundry", "deleteAllServicesForProject", "deleteAllForProject",
    "dev_test_prod_sub_id", "tenantId", "dev_test_prod", "project_number_000", "admin_location",
    "admin_aifactoryPrefixRG", "projectPrefix", "admin_locationSuffix", "admin_aifactorySuffixRG",
    "projectSuffix", "projectResourceGroup", "aifactoryMcpImage", "aifactoryMcpApiImage",
    "aifactoryMcpEntraAppId", "aifactoryMcpContainerAppsEnvironment", "aiGatewaySkuResourceId",
    "aiGatewaySkuOutboundSubnetId",
)


def run(args, environ=os.environ, session_factory=AzureSession) -> dict:
    request = IntegrationRequest.from_values({name: environ.get(name) for name in INPUTS})
    decision = decide(request)
    if args.command == "apply" and not args.apply:
        raise ValueError("apply requires --apply.")
    if not decision.act:
        return {"mode": "skipped", "reason": decision.reason, "mutations": False}
    if args.command == "validate":
        return {"mode": "validated", "reason": decision.reason, "mutations": False}
    session = session_factory(request.subscription_id, request.tenant_id)
    return McpGatewayIntegration(session).run(request, apply=args.command == "apply")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "plan", "apply"])
    parser.add_argument("--apply", action="store_true", help="Required with apply; plan and validate never write.")
    try:
        result = run(parser.parse_args())
    except ValueError as error:
        print(f"MCP & AI Gateway configuration error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
