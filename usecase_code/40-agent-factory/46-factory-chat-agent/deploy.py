"""Late project-pipeline deployment of the opt-in Factory Chat Agent in Foundry."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.azure import AzureSession  # noqa: E402
from agent_factory.factory_chat_agent import (  # noqa: E402
    FactoryChatAgentIntegration, FactoryChatAgentRequest, decide,
)

INPUTS = (
    "enableFactoryChatAgent", "enableAIFoundry", "deleteAllServicesForProject",
    "deleteAllForProject", "dev_test_prod_sub_id", "tenantId", "dev_test_prod",
    "project_number_000", "admin_aifactoryPrefixRG", "projectPrefix",
    "admin_locationSuffix", "admin_aifactorySuffixRG", "projectSuffix",
    "modelGPTXName",
)


def run(args, environ=os.environ, session_factory=AzureSession) -> dict:
    request = FactoryChatAgentRequest.from_values(
        {name: environ.get(name) for name in INPUTS}
    )
    decision = decide(request)
    if args.command == "apply" and not args.apply:
        raise ValueError("apply requires --apply.")
    if not decision.act:
        return {
            "mode": "skipped",
            "reason": decision.reason,
            "mutations": False,
        }
    if args.command == "validate":
        return {
            "mode": "validated",
            "reason": decision.reason,
            "mutations": False,
        }
    session = session_factory(request.subscription_id, request.tenant_id)
    return FactoryChatAgentIntegration(session).run(
        request, apply=args.command == "apply"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=["validate", "plan", "apply"])
    parser.add_argument("--apply", action="store_true", help="Required with apply.")
    try:
        result = run(parser.parse_args())
    except (RuntimeError, ValueError) as error:
        print(f"Factory Chat Agent deployment error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
