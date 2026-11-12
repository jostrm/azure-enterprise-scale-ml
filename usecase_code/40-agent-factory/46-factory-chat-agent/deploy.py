"""Late project-pipeline deployment of the opt-in Factory Chat Agent in Foundry.

An invalid or incomplete configuration is never ignored silently: the pipeline apply warns and skips (``apply --apply``:
a GitHub Actions / Azure DevOps warning, exit 0, no Azure contact); validate and plan fail on it (exit 1).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.azure import AzureSession  # noqa: E402
from agent_factory.deployer_access import DeployerAccess  # noqa: E402
from agent_factory.factory_chat_agent import (  # noqa: E402
    FactoryChatAgentIntegration, FactoryChatAgentRequest, decide,
)
from agent_factory.pipeline_warning import SKIPPED_INCOMPLETE, skipped_incomplete, warn_skipped  # noqa: E402

INPUTS = (
    "enableFactoryChatAgent", "enableAIFoundry", "deleteAllServicesForProject",
    "deleteAllForProject", "dev_test_prod_sub_id", "tenantId", "dev_test_prod",
    "project_number_000", "admin_aifactoryPrefixRG", "projectPrefix",
    "admin_locationSuffix", "admin_aifactorySuffixRG", "projectSuffix",
    "modelGPTXName", "aifactoryAgentModelDeployment",
)


def run(args, environ=os.environ, session_factory=AzureSession, *,
        access_factory=DeployerAccess.for_session, skip_incomplete=False) -> dict:
    try:
        request = FactoryChatAgentRequest.from_values(
            {name: environ.get(name) for name in INPUTS}
        )
        decision = decide(request)
    except ValueError as error:
        if not skip_incomplete:
            raise
        return skipped_incomplete(str(error))
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
    return FactoryChatAgentIntegration(session, access=access_factory(session)).run(
        request, apply=args.command == "apply"
    )


def main(argv=None, environ=os.environ, session_factory=AzureSession) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=["validate", "plan", "apply"])
    parser.add_argument("--apply", action="store_true", help="Required with apply.")
    args = parser.parse_args(argv)
    try:
        result = run(args, environ, session_factory, skip_incomplete=args.command == "apply" and args.apply)
    except (RuntimeError, ValueError) as error:
        print(f"Factory Chat Agent deployment error: {error}", file=sys.stderr)
        return 1
    if result["mode"] == SKIPPED_INCOMPLETE:
        warn_skipped("Factory Chat Agent", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
