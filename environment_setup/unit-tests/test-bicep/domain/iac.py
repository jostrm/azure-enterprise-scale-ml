"""Domain layer: offline IaC validation of the bicep templates.

Cheap, no-deploy checks: `az bicep build`, lint, bicepparam parse, and
`what-if` drift. Each function returns a bool/result so unit tests can mock
the CLI seam and integration tests run them live. Pure orchestration; the only
external dependency is base.cli (single mock seam).
"""
from __future__ import annotations

from pathlib import Path

from ..base import cli, config


def bicep_templates(directory: Path) -> list[Path]:
    """All *.bicep templates in a directory, sorted for stable test output."""
    return sorted(p for p in directory.glob("*.bicep"))


def all_templates() -> list[Path]:
    return bicep_templates(config.GENAI_BICEP_DIR) + bicep_templates(
        config.COMMON_BICEP_DIR
    )


def build_ok(template: Path) -> bool:
    """`az bicep build` compiles a template with no errors."""
    res = cli.az(["bicep", "build", "--file", str(template), "--stdout"])
    return res.ok


def lint_clean(template: Path) -> bool:
    """`az bicep lint` reports no warnings/errors for a template."""
    res = cli.az(["bicep", "lint", "--file", str(template)])
    return res.ok and not res.stderr


def bicepparam_parses(param_file: Path) -> bool:
    """A .bicepparam builds (params reference real template params)."""
    res = cli.az(["bicep", "build-params", "--file", str(param_file), "--stdout"])
    return res.ok


def what_if_clean(resource_group: str, template: Path, params: dict[str, str]) -> bool:
    """`az deployment group what-if` shows no drift (only NoChange/Ignore)."""
    args = [
        "deployment", "group", "what-if",
        "-g", resource_group,
        "-f", str(template),
        "--no-pretty-print",
    ]
    for key, value in params.items():
        args += ["-p", f"{key}={value}"]
    data = cli.az_json(args)
    if not data:
        return False
    changes = data.get("changes", [])
    return all(c.get("changeType") in ("NoChange", "Ignore") for c in changes)
