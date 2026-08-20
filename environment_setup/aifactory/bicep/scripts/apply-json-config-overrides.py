#!/usr/bin/env python3
"""Apply a non-secret AI Factory JSON configuration override to a CI pipeline."""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any


VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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
    return parser.parse_args()


def read_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{location} must be a JSON object.")
    return value


def configuration_section(environment: str) -> str:
    return "dev" if environment == "dev" else "stage_prod"


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


def selected_values(config: dict[str, Any], environment: str) -> dict[str, str]:
    supported_keys = {"dev", "stage_prod"}
    unknown_keys = set(config).difference(supported_keys)
    if unknown_keys:
        fail(
            "The root object supports only 'dev' and 'stage_prod'; found "
            + ", ".join(sorted(unknown_keys))
            + "."
        )

    section = configuration_section(environment)
    values = read_object(config.get(section, {}), section)
    serialized: dict[str, str] = {}
    for name, value in values.items():
        if not VARIABLE_NAME.fullmatch(name):
            fail(f"'{name}' is not a valid pipeline variable name.")
        serialized[name] = serialize(value, name)
    return serialized


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
    values = selected_values(read_object(config, "root"), environment)
    applied, skipped = apply(values, args.format, args.github_workflow)
    print(
        f"Applied {applied} of {len(values)} configuration variable(s) from "
        f"{config_file.name} using the {configuration_section(environment)} section."
    )
    if skipped:
        print(
            "Skipped GitHub runner-reserved bootstrap variable(s): "
            + ", ".join(skipped)
            + "."
        )


if __name__ == "__main__":
    main()
