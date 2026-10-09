"""Print an offline, plan-only Foundry connection and auth proposal.

Supply all IDs explicitly, especially the separately created MCP API application
ID. This script does not discover resources, acquire tokens, mutate agents, create
infrastructure, or register a connection. There is deliberately no --apply option.
Use --help for the required arguments; review the output before any later changes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aifactory_mcp.registration import (
    DEFAULT_ALLOWED_TOOLS,
    ApplicationRole,
    RegistrationTarget,
    build_registration_plan,
)


class _PlanParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's default error can echo accidental tokens or credential-bearing URLs.
        self.exit(2, "Invalid planning arguments; use --help for required inputs. No changes were made.\n")


def _parser() -> argparse.ArgumentParser:
    parser = _PlanParser(description=__doc__, allow_abbrev=False)
    for name in (
        "subscription-id", "tenant-id", "project-principal-id", "project-client-id", "mcp-application-id",
    ):
        parser.add_argument("--" + name, required=True, type=UUID)
    for name in ("resource-group", "foundry-account", "foundry-project", "mcp-url", "scope-key"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--connection-name", default="aifactory-governed-mcp")
    parser.add_argument("--server-label", default="aifactory-governed")
    parser.add_argument("--service-name", default="aifactory-governed-mcp")
    parser.add_argument(
        "--allowed-tool", action="append",
        help="Repeat for each exact read-only tool; defaults to factory_health, factory_capabilities, factory_skills.",
    )
    parser.add_argument(
        "--existing-role-id", type=UUID,
        help="ID of an already reviewed, enabled AiFactory.Mcp.Read application-only role on the new API app.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    options = vars(parser.parse_args(argv))
    scope_key = options.pop("scope_key")
    role_id = options.pop("existing_role_id")
    options["allowed_tools"] = tuple(options.pop("allowed_tool") or DEFAULT_ALLOWED_TOOLS)
    try:
        target = RegistrationTarget(**options)
        role = ApplicationRole(id=role_id) if role_id else None
        plan = build_registration_plan(target, scope_key=scope_key, existing_application_role=role)
    except (ValueError, TypeError):
        parser.error("Invalid target.")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
