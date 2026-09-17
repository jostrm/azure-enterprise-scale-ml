"""Provider-pinned shell adapter for the canonical enrollment implementation."""

import argparse
from pathlib import Path
import re
import sys

import factory_enrollment as core


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    provider = argv.pop(0) if argv else None
    parser = argparse.ArgumentParser(description=core.__doc__)
    if provider not in ("ado", "gha"):
        parser.error("The adapter requires the launcher's fixed ado or gha provider.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "ensure"):
        command = sub.add_parser(name, help="Read-only review." if name == "plan" else "Reviewed add-only enrollment.")
        command.add_argument("--consumer-root", required=True)
        command.add_argument("--factory-id", required=True)
        command.add_argument("--scale-set-id", required=True)
        command.add_argument("--environment", choices=("dev", "stage", "prod"), required=True)
        command.add_argument("--options", required=True, help="Closed, non-secret enrollment options JSON file.")
        command.add_argument("--acknowledge-exclusive-writer-governance", action="store_true",
                             help="Actual administrator attestation that ALL writers enforce physical leases.")
        if name == "ensure":
            command.add_argument("--expected-plan", required=True, help="plan_hash from the separate approved plan.")
            command.add_argument("--yes", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        with Path(args.options).open("rb") as handle:
            options = core.parse_json(handle.read(core.MAX_BYTES + 1))
        request = core.load_request(args.consumer_root, args.factory_id, args.scale_set_id, args.environment, options)
        # Check the SAME request passed to the core; its fresh-request guard covers races.
        core.require(request["route"]["kind"] == provider, "orchestrator-mismatch")
        kwargs = {"acknowledge_exclusive_writer_governance": args.acknowledge_exclusive_writer_governance}
        result = (core.plan(request, **kwargs) if args.command == "plan" else
                  core.ensure(request, args.expected_plan, yes=args.yes, **kwargs))
        print(core.canonical(result).decode("utf-8"))
        ready = result.get("can_ensure") if args.command == "plan" else result.get("enrollment_complete")
        return 0 if ready and not result.get("blockers") else 3
    except (core.EnrollmentError, OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        code = exc.code if isinstance(exc, core.EnrollmentError) else "invalid-input-or-unavailable-file"
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9-]{1,120}", code):
            code = "enrollment-failed"
        print(core.canonical({"status": "blocked", "enrollment_complete": False, "error": code}).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
