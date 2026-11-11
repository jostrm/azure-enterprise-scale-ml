"""Shared CLI behind the project-aware Teams and Copilot PowerShell wrappers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "usecase_code/40-agent-factory"))

from agent_factory.azure import AzureSession  # noqa: E402
from agent_factory.publishing_project import (  # noqa: E402
    apply_publication, load_selection, plan_publication, read_object,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=["plan", "apply"])
    parser.add_argument("--config-file", type=Path, default=Path("variables.json"))
    parser.add_argument("--environment", choices=["dev", "stage", "test", "prod"], default="dev")
    parser.add_argument("--surface", choices=["Teams", "Copilot"], required=True)
    parser.add_argument("--agent-name")
    parser.add_argument("--project-resource-id")
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--scope", choices=["Shared", "Tenant"])
    parser.add_argument("--metadata-file", type=Path)
    parser.add_argument("--retry-uncertain", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reviewed-plan", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "apply" and (not args.apply or args.reviewed_plan is None):
            raise ValueError("apply requires --apply and --reviewed-plan from the confirmed preview.")
        if args.command == "plan" and (args.apply or args.reviewed_plan):
            raise ValueError("plan does not accept apply options.")
        selection = load_selection(
            args.config_file, environment=args.environment, agent_name=args.agent_name,
            project_resource_id=args.project_resource_id, profile_file=args.profile_file,
            scope=args.scope, metadata_file=args.metadata_file,
        )
        from agent_factory.m365_publishing import M365Publisher
        publisher = M365Publisher(AzureSession(selection.request.subscription_id, selection.request.tenant_id))
        if args.command == "plan":
            result = plan_publication(selection, publisher, surface=args.surface, retry_uncertain=args.retry_uncertain)
        else:
            result = apply_publication(
                selection, publisher, read_object(args.reviewed_plan),
                surface=args.surface, retry_uncertain=args.retry_uncertain,
            )
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Foundry publication failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
