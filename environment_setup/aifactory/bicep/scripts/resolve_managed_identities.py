#!/usr/bin/env python3
"""Read existing project identities once; publish exact names and stable naming salt."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys

from generate_hosts_file_info import Scope, az_json, env


IDENTITY_TYPE = "microsoft.managedidentity/userassignedidentities"
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}")
SALT = r"[a-z0-9_-]{10}"


@dataclass(frozen=True)
class Config:
    project_scope: Scope
    common_scope: Scope
    project_number: str
    location_suffix: str
    environment: str
    common_suffix: str

    def __post_init__(self):
        if not re.fullmatch(r"\d{3}", self.project_number):
            raise ValueError("Project number must contain exactly three digits.")
        if not re.fullmatch(r"[a-z0-9]+", self.location_suffix):
            raise ValueError("A location suffix is required.")
        if self.environment not in ("dev", "test", "prod"):
            raise ValueError("Environment must be dev, test or prod.")
        if not re.fullmatch(r"-\d{3}", self.common_suffix):
            raise ValueError("Common resource suffix must have the form -001.")

    def prefix(self, kind: str) -> str:
        stem = "mi-prj" if kind == "project" else "mi-aca-prj"
        return f"{stem}{self.project_number}-{self.location_suffix}-{self.environment}-"


def configuration() -> Config:
    def setting(key: str, default: str = "") -> str:
        return env("MI_DISCOVERY_" + key, default)

    subscription = setting("SUBSCRIPTION")
    number, location, environment = setting("PROJECT_NUMBER"), setting("LOCATION_SUFFIX"), setting("ENVIRONMENT")
    prefix, suffix = setting("RG_PREFIX"), setting("RG_SUFFIX")
    project_rg = (
        f"{prefix}{setting('PROJECT_PREFIX')}project{number}-{location}-{environment}"
        f"{suffix}{setting('PROJECT_SUFFIX')}"
    )
    common_rg = setting("COMMON_RG") or f"{prefix}{setting('COMMON_NAME', 'esml-common')}-{location}-{environment}{suffix}"
    return Config(Scope(subscription, project_rg), Scope(subscription, common_rg),
                  number, location, environment, setting("COMMON_SUFFIX", "-001"))


def resources(payload: object, label: str) -> list[dict]:
    if not isinstance(payload, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str)
        or not isinstance(item.get("type"), str) for item in payload
    ):
        raise ValueError(f"{label} did not return a resource list with names and types.")
    return payload


def parse_identity(name: str, prefix: str) -> tuple[str, str]:
    """Supported history: hash+salt, hash-salt, and the old undelimited numeric suffix."""
    tail = name[len(prefix):]
    formats = (
        rf"(?P<hash>[a-z0-9]{{5}})(?P<salt>{SALT})-\d{{3}}",
        rf"(?P<hash>[a-z0-9]{{5}})-(?P<salt>{SALT})-\d{{3}}",
        rf"(?P<hash>[a-z0-9]{{5}})(?P<salt>{SALT})\d{{3}}",
    )
    matches = {(m["hash"], m["salt"]) for pattern in formats if (m := re.fullmatch(pattern, tail))}
    if len(matches) != 1:
        raise ValueError(
            f"Cannot safely recover the naming salt from identity '{name}'. "
            "Expected a five-character hash and ten-character salt. No new salt or identity will be selected."
        )
    return matches.pop()


def resolve(config: Config, project_resources: list[dict], common_resources: list[dict]) -> dict[str, str]:
    names: dict[str, str] = {}
    salts: dict[str, tuple[str, str]] = {}
    for kind in ("project", "containerApps"):
        prefix = config.prefix(kind)
        candidates = [item for item in project_resources
                      if item["type"].lower() == IDENTITY_TYPE and item["name"].lower().startswith(prefix)]
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous {kind} identity in '{config.project_scope.resource_group}': "
                             + ", ".join(sorted(item["name"] for item in candidates)))
        if candidates:
            item = candidates[0]
            name = item["name"]
            if not NAME.fullmatch(name):
                raise ValueError(f"Unsupported managed identity name: {name!r}")
            expected_id = f"{config.project_scope.id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
            if not isinstance(item.get("id"), str) or item["id"].lower() != expected_id.lower():
                raise ValueError(f"Identity '{name}' is not in the requested project scope.")
            names[kind] = name
            salts[kind] = parse_identity(name, prefix)

    # The project MI remains authoritative. ACA-only recovery is allowed only when it is unambiguous.
    selected = salts.get("project") or salts.get("containerApps")
    if len(salts) == 2 and salts["project"] != salts["containerApps"]:
        raise ValueError("Project and Container Apps identities have conflicting naming salts; refusing to rename resources.")
    if selected:
        deterministic, random_salt = selected
    else:
        # Never silently generate a replacement salt for an existing workload whose identities were removed.
        workload = [item["name"] for item in project_resources
                    if item["type"].lower() not in ("microsoft.resources/deployments", "microsoft.authorization/roleassignments")]
        if workload:
            raise ValueError("Existing project resources have no recognizable AI Factory identity to recover their salt: "
                             + ", ".join(workload[:5]) + ". Refusing a fresh naming salt.")
        pattern = re.compile(
            rf"la-cmn-{re.escape(config.location_suffix)}-{config.environment}-(?P<hash>[a-z0-9]{{5}})"
            + re.escape(config.common_suffix)
        )
        hashes = {m["hash"] for item in common_resources
                  if item["type"].lower() == "microsoft.operationalinsights/workspaces"
                  and (m := pattern.fullmatch(item["name"]))}
        if len(hashes) > 1:
            raise ValueError("Multiple common Log Analytics naming salts found; refusing to choose the first.")
        deterministic, random_salt = next(iter(hashes), ""), ""

    return {
        "resolvedManagedIdentityNames": json.dumps(names, separators=(",", ":")),
        "miPrjExists": str("project" in names).lower(),
        "miACAExists": str("containerApps" in names).lower(),
        "aifactory_salt": deterministic,
        "aifactory_salt_random": random_salt,
    }


def discover(config: Config, az=az_json) -> dict[str, str]:
    exists = az("group", "exists", "--subscription", config.project_scope.subscription,
                "--name", config.project_scope.resource_group)
    if not isinstance(exists, bool):
        raise ValueError("Resource-group existence lookup did not return a boolean.")
    project = resources(az("resource", "list", "--subscription", config.project_scope.subscription,
                           "--resource-group", config.project_scope.resource_group), "Project discovery") if exists else []
    # No common/DNS subscription scan is needed to recover existing MI names.
    common = resources(az("resource", "list", "--subscription", config.common_scope.subscription,
                         "--resource-group", config.common_scope.resource_group), "Common discovery") if not project else []
    return resolve(config, project, common)


def publish(values: dict[str, str], output_format: str) -> None:
    if output_format == "ado":
        for name, value in values.items():
            print(f"##vso[task.setvariable variable={name}]{value}")
    elif output_format == "github":
        target = os.environ.get("GITHUB_ENV")
        if not target:
            raise ValueError("GITHUB_ENV is required for GitHub output.")
        with Path(target).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("".join(f"{name}={value}\n" for name, value in values.items()))
    else:
        print(json.dumps(values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("ado", "github", "json"), required=True)
    args = parser.parse_args()
    try:
        values = discover(configuration())
        publish(values, args.format)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Managed identity discovery failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
