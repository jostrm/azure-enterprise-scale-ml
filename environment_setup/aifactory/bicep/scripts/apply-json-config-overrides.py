#!/usr/bin/env python3
"""Apply a non-secret AI Factory JSON configuration override to a CI pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any


VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Configuration keys can differ from the shell-safe runtime name.
VARIABLE_ALIASES = {
    "aifactory-dash-01": "AIFACTORY_DASHBOARD_URL",
    "scaling-mode": "SCALING_MODE",
}
GITHUB_IDENTITY_OUTPUTS = {
    "AZURE_CLIENT_ID": "azure_client_id",
    "tenantId": "azure_tenant_id",
}
# Project ownership metadata is not a deployment input or runtime variable.
METADATA_KEYS = frozenset({"org-department-name", "org-department-id"})
SCALING_MODES = ("own-subscriptions", "shared-subscriptions")
RESERVED_PREFIXES = {
    "azure-devops": ("AGENT_", "BUILD_", "RELEASE_", "SYSTEM_"),
    "github": ("ACTIONS_", "GITHUB_", "RUNNER_"),
}


def fail(message: str) -> None:
    print(f"Configuration override error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply an AI Factory JSON configuration override."
    )
    parser.add_argument("--file", required=True, help="Configuration JSON file path.")
    parser.add_argument(
        "--environment",
        required=True,
        choices=("dev", "stage", "test", "prod"),
        help="Deployment environment.",
    )
    parser.add_argument(
        "--format",
        required=True,
        choices=("azure-devops", "github"),
        help="CI system that receives the variables.",
    )
    parser.add_argument(
        "--github-workflow",
        help=(
            "GitHub workflow used to map .env-style configuration names to its "
            "runtime environment variables."
        ),
    )
    parser.add_argument(
        "--github-identity-output",
        action="store_true",
        help=(
            "Require JSON-provided GitHub OIDC identity selectors and write "
            "validated client, tenant, and target subscription values to GITHUB_OUTPUT."
        ),
    )
    return parser.parse_args()


def read_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{location} must be a JSON object.")
    return value


def serialize(value: Any, variable_name: str) -> str:
    if value is None:
        fail(f"Variable '{variable_name}' cannot be null.")
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"))
    fail(
        f"Variable '{variable_name}' must be a string, number, boolean, array, or object."
    )


def selected_values(config: dict[str, Any], environment: str) -> tuple[dict[str, str], str]:
    supported_keys = {"dev", "stage_prod", "_wizard"}
    unknown_keys = set(config).difference(supported_keys)
    if unknown_keys:
        fail(
            "The root object supports only 'dev', 'stage_prod' and '_wizard'; found "
            + ", ".join(sorted(unknown_keys))
            + "."
        )

    # The canonical variables.json has one "dev" section which is a shared
    # baseline for all environments. Stage/Prod applies its explicit overrides
    # on top of that baseline, so shared OIDC identity selectors and settings
    # are never accidentally omitted from the later environment deployments.
    dev_values = read_object(config.get("dev", {}), "dev")
    section = "stage_prod" if environment != "dev" and "stage_prod" in config else "dev"
    section_values = read_object(config.get(section, {}), section)
    values = {**dev_values, **section_values} if section == "stage_prod" else dev_values
    serialized: dict[str, str] = {}
    for name, value in values.items():
        if name in METADATA_KEYS:
            continue
        runtime_name = VARIABLE_ALIASES.get(name, name)
        if not VARIABLE_NAME.fullmatch(runtime_name):
            fail(f"'{name}' is not a valid pipeline variable name.")
        if runtime_name == "SCALING_MODE" and value not in SCALING_MODES:
            fail(f"Variable '{name}' must be 'own-subscriptions' or 'shared-subscriptions'.")
        serialized_value = serialize(value, name)
        if runtime_name in serialized and serialized[runtime_name] != serialized_value:
            fail(f"Conflicting configuration values map to pipeline variable '{runtime_name}'.")
        serialized[runtime_name] = serialized_value
    return serialized, section


def is_reserved(name: str, pipeline_format: str) -> bool:
    return name.startswith(RESERVED_PREFIXES[pipeline_format])


def escape_azure_devops(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def write_github_environment(name: str, value: str) -> None:
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        fail("GITHUB_ENV is not set; this command must run in GitHub Actions.")

    delimiter = f"AI_FACTORY_{uuid.uuid4().hex}"
    with Path(github_env).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def write_github_output(name: str, value: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        fail("GITHUB_OUTPUT is not set; this command must run in GitHub Actions.")
    with Path(github_output).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{name}={value}\n")


def github_identity(values: dict[str, str], environment: str) -> None:
    subscription_key = {
        "dev": "dev_sub_id",
        "stage": "test_sub_id",
        "test": "test_sub_id",
        "prod": "prod_sub_id",
    }[environment]
    required = {
        **GITHUB_IDENTITY_OUTPUTS,
        subscription_key: "azure_subscription_id",
    }
    for source, output in required.items():
        value = values.get(source, "")
        if not re.fullmatch(
            r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",
            value,
        ):
            fail(
                f"JSON OIDC identity requires '{source}' to be a valid GUID; "
                "GitHub Environment identity values are not used in this mode."
            )
        write_github_output(output, value)


def github_runtime_names(workflow_file: str | None) -> dict[str, set[str]]:
    if not workflow_file:
        return {}

    path = Path(workflow_file)
    if not path.is_file():
        fail(f"GitHub workflow file not found: {path}")

    mappings: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        target = re.match(r"^\s{6}([A-Za-z_][A-Za-z0-9_]*):\s+\$\{\{", line)
        if not target:
            continue
        for source in re.findall(r"vars\.([A-Z][A-Z0-9_]*)", line):
            mappings.setdefault(source, set()).add(target.group(1))
    return mappings


def apply(
    values: dict[str, str], pipeline_format: str, github_workflow: str | None
) -> tuple[int, list[str]]:
    runtime_mappings = github_runtime_names(github_workflow)
    skipped: list[str] = []
    applied = 0
    for name, value in values.items():
        if is_reserved(name, pipeline_format):
            if pipeline_format == "github":
                skipped.append(name)
                continue
            fail(f"'{name}' is reserved by {pipeline_format} and cannot be overridden.")
        if pipeline_format == "azure-devops":
            print(
                f"##vso[task.setvariable variable={name}]"
                f"{escape_azure_devops(value)}"
            )
        else:
            write_github_environment(name, value)
            for runtime_name in runtime_mappings.get(name, set()):
                write_github_environment(runtime_name, value)
        applied += 1
    return applied, skipped


def main() -> None:
    args = parse_args()
    config_file = Path(args.file)
    if not config_file.is_file():
        fail(f"File not found: {config_file}")

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"Invalid JSON in {config_file}: {error.msg} (line {error.lineno}).")

    environment = args.environment
    values, section = selected_values(read_object(config, "root"), environment)
    network_environment_key = {
        "dev": "network_env_dev",
        "stage": "network_env_stage",
        "test": "network_env_stage",
        "prod": "network_env_prod",
    }[environment]
    if network_environment_key in values:
        values["network_env"] = values[network_environment_key]
    if args.format == "azure-devops":
        cidr_key = {
            "dev": "dev_cidr_range",
            "stage": "test_cidr_range",
            "test": "test_cidr_range",
            "prod": "prod_cidr_range",
        }[environment]
        if cidr_key in values:
            values["cidr_range"] = values[cidr_key]
    applied, skipped = apply(values, args.format, args.github_workflow)
    if args.github_identity_output:
        if args.format != "github":
            fail("--github-identity-output requires --format github.")
        github_identity(values, environment)
    print(
        f"Applied {applied} of {len(values)} configuration variable(s) from "
        f"{config_file.name} using the {section} section."
    )
    if skipped:
        print(
            "Skipped GitHub runner-reserved bootstrap variable(s): "
            + ", ".join(skipped)
            + "."
        )


if __name__ == "__main__":
    main()
