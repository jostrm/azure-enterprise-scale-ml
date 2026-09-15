"""Build a single-field typed parameter prepare request from a current API schema response."""

import argparse
import json
from pathlib import Path
import sys


def build_patch(snapshot, folder, template, parameter, value):
    if not isinstance(snapshot, dict):
        raise ValueError("The API parameter response must be a JSON object.")
    if type(snapshot.get("contract_version")) is not int or snapshot["contract_version"] != 1:
        raise ValueError("Refresh the schema from a catalog contract v1 server.")
    if snapshot.get("requires_profile_reset") is not False:
        raise ValueError("Profile reset needs a separate explicit review; this example will not reset it.")
    if not folder:
        raise ValueError("Supply the same server-local folder used to read the parameters.")
    required = ("factory_id", "scale_set_id", "source_revision", "schema_revision", "templates")
    if any(not snapshot.get(key) for key in required):
        raise ValueError("The API parameter response is incomplete.")
    if not isinstance(snapshot["templates"], list):
        raise ValueError("The API parameter response must contain a template list.")
    matches = [item for item in snapshot["templates"] if isinstance(item, dict) and item.get("template") == template]
    if len(matches) != 1:
        raise ValueError("Choose an exact template returned by the API.")
    fields = [item for item in matches[0]["fields"] if item["name"] == parameter]
    if len(fields) != 1 or parameter not in matches[0]["parameter_schema"].get("properties", {}):
        raise ValueError("Choose an exact parameter returned by the API.")
    if fields[0].get("sensitive") is not False:
        raise ValueError("This example does not write sensitive values to request files.")
    if matches[0]["parameter_schema"]["properties"][parameter].get("readOnly") is True:
        raise ValueError("This parameter is read-only.")
    json.dumps(value, allow_nan=False)
    return {
        "folder": folder,
        "contract_version": 1,
        "factory_id": snapshot["factory_id"],
        "scale_set_id": snapshot["scale_set_id"],
        "project_id": snapshot.get("project_id"),
        "expected_revision": snapshot["source_revision"],
        "schema_revision": snapshot["schema_revision"],
        "reset_profile": False,
        "templates": [{"template": template, "parameters": {parameter: value}}],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--parameter", required=True)
    parser.add_argument("--value-json", required=True, help="JSON literal: true, 3, or a JSON-quoted string.")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
        body = build_patch(snapshot, args.folder, args.template, args.parameter, json.loads(args.value_json))
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(body, output, indent=2, allow_nan=False)
            output.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Parameter request failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
