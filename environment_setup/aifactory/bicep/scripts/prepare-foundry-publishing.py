"""Plan or prepare a native Foundry agent for M365 without publishing it."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "usecase_code" / "40-agent-factory"))

from agent_factory.azure import AzureSession  # noqa: E402
from agent_factory.foundry_publishing import (  # noqa: E402
    INPUTS, FoundryPublishingPreparation, PreparationRequest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=["plan", "apply"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reviewed-plan", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "apply" and (not args.apply or args.reviewed_plan is None):
            raise ValueError("apply requires --apply and --reviewed-plan from a prior plan.")
        if args.command == "plan" and (args.apply or args.reviewed_plan):
            raise ValueError("plan does not accept apply options.")
        reviewed = json.loads(args.reviewed_plan.read_text(encoding="utf-8-sig")) if args.reviewed_plan else None
        request = PreparationRequest.from_values({key: os.environ.get(key) for key in INPUTS})
        service = FoundryPublishingPreparation(AzureSession(request.subscription_id, request.tenant_id))
        result = service.run(request, apply=args.command == "apply", reviewed_plan=reviewed)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Foundry publishing preparation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
