"""Inspect a persona manifest offline; no Azure authentication or writes."""

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from personas import groups, policy
else:
    from . import groups, policy


def inspect_manifest(manifest):
    value = policy.validate_manifest(manifest, require_lake=True)
    return {
        "schema": "aifactory.persona-inspection/v1",
        "state": "offline-validated", "cloud_checked": False, "writes_performed": False,
        "scope": {key: value[key] for key in ("tenant_id", "factory", "scaleset", "environment", "project",
                                             "common_scope", "project_scope", "connectivity_scopes")},
        "groups": groups.group_specs(value),
        "personas": policy.CATALOG["personas"],
        "built_in_role_ids": policy.CATALOG["builtins"],
        "custom_roles": {
            definition["key"]: definition
            for key in policy.CATALOG["roles"]
            for definition in policy.role_definitions(
                key, value["common_scope"] if key == "workspace-observer" else value["project_scope"]
            )
        },
        "lake": {
            "authorized_path": policy.lake_authorized_path(value["lake"]),
            "persona": "persona213",
            "permissions": {"directories": "r-x", "files": "r--", "ancestors": "--x"},
        },
        "missing_security_reviews": [
            key for key in policy.SECURITY_REVIEWS if not value["security_review"][key]
        ],
        "limitations": [
            "Group names and role definitions are calculated, not discovered or assigned.",
            "Only live preflight can inspect seeded IDs, existing resources, inherited grants, vaults and ACLs.",
            "Displayed custom roles describe the catalogue; actual grants depend on discovered eligible resources.",
            "This output is not deployment approval or evidence of effective Azure authorization.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        print(json.dumps(inspect_manifest(manifest), indent=2))
    except (ValueError, OSError) as error:
        print(f"Persona manifest: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
