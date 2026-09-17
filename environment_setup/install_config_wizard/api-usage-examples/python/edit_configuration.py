"""Review JSON-origin legacy configuration; save only after separate human approval."""

import argparse
import json
import sys
from pathlib import Path

from azurefactory import APIError, AzureFactoryClient, ConfigError, ConfigurationDraft
from azurefactory.client import redact_secrets


def edit_configuration(client, folder, project_number, changes=None, *,
                       snapshot_only=False, save=False, expected_review=None, yes=False):
    if save and (not expected_review or not yes):
        raise ConfigError("Saving requires --expected-review from a prior review and --yes.")
    if not save and (expected_review is not None or yes):
        raise ConfigError("--expected-review and --yes are only valid with --save.")
    draft = ConfigurationDraft.load(client, folder, project_number, changes=changes)
    if save:
        result = draft.save(expected_review, write_variables=not snapshot_only)
        result = {key: result[key] for key in ("snapshot_path", "variables_path", "warnings") if key in result}
    else:
        result = draft.review(write_variables=not snapshot_only)
    return redact_secrets(result, client.api_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, help="Exact legacy folder on the API host.")
    parser.add_argument("--project-number", required=True, help="Exact project, for example 001.")
    parser.add_argument("--changes-json", help="Local UTF-8 JSON object of intentional field replacements.")
    parser.add_argument("--snapshot-only", action="store_true", help="Do not write pipeline variable files.")
    parser.add_argument("--save", action="store_true", help="Save only after a separately approved review.")
    parser.add_argument("--expected-review", help="review_id from a separately approved review.")
    parser.add_argument("--yes", action="store_true", help="Explicit human approval of that exact review.")
    args = parser.parse_args(argv)
    try:
        changes = json.loads(Path(args.changes_json).read_text(encoding="utf-8-sig")) if args.changes_json else None
        if args.changes_json and not isinstance(changes, dict):
            raise ValueError("Changes must be a JSON object.")
        json.dumps(changes, allow_nan=False)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Cannot read changes JSON ({type(error).__name__}); check path, permissions and JSON syntax.",
              file=sys.stderr)
        return 2
    try:
        result = edit_configuration(
            AzureFactoryClient(), args.folder, args.project_number, changes,
            snapshot_only=args.snapshot_only, save=args.save,
            expected_review=args.expected_review, yes=args.yes,
        )
    except APIError as error:
        # Server error bodies may contain configuration values; do not print them.
        print(f"Configuration request failed ({type(error).__name__}, HTTP {error.status or 'n/a'}). "
              "Check approval inputs and host diagnostics securely; do not blindly retry a save.", file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, indent=2, allow_nan=False))
    return 3 if result.get("can_save") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
