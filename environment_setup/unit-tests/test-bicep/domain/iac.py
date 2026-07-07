"""Domain layer: offline IaC validation of the bicep templates.

Cheap, no-deploy checks: `az bicep build`, lint, bicepparam parse, and
`what-if` drift. Each function returns a bool/result so unit tests can mock
the CLI seam and integration tests run them live. Pure orchestration; the only
external dependency is base.cli (single mock seam).
"""
from __future__ import annotations

import re
from pathlib import Path

from base import cli, config


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


# --- Static (offline) template analysis -----------------------------------
# Some template defects compile cleanly with `az bicep build` yet fail at ARM
# deployment validation. The classic one: two conditionally-deployed resources
# that share the same ARM name under the same parent. Bicep serializes them
# with an implicit dependsOn, so a run that excludes one twin still references
# it -> "The resource '<name>' is not defined in the template." These helpers
# parse the bicep source to guard against that regression without a live deploy.

def _top_level_decl_starts(source: str) -> list[int]:
    """Offsets of every column-0 resource/module/output/var/param declaration."""
    starts = [m.start() for m in re.finditer(r"(?m)^(resource|module|output|var|param)\s", source)]
    starts.append(len(source))
    return starts


def resource_declarations(template: Path, type_substr: str) -> list[dict[str, str]]:
    """Parse resources of a given ARM type from a bicep file.

    Returns one dict per matching resource with its symbolic name, the raw
    `name:` and `parent:` expressions, and the declaration body. Pure string
    analysis (stdlib only) so it runs offline in unit tests.
    """
    source = template.read_text(encoding="utf-8")
    type_re = re.compile(
        r"resource\s+(\w+)\s+'(" + re.escape(type_substr) + r")@[^']+'\s*=",
    )
    starts = _top_level_decl_starts(source)
    decls: list[dict[str, str]] = []
    for i in range(len(starts) - 1):
        segment = source[starts[i]:starts[i + 1]]
        match = type_re.match(segment)
        if not match:
            continue
        name_m = re.search(r"(?m)^\s*name:\s*(.+?)\s*$", segment)
        parent_m = re.search(r"(?m)^\s*parent:\s*(.+?)\s*$", segment)
        decls.append({
            "symbol": match.group(1),
            "name": name_m.group(1) if name_m else "",
            "parent": parent_m.group(1) if parent_m else "",
            "body": segment,
        })
    return decls


def duplicate_named_resources(template: Path, type_substr: str) -> list[tuple[str, str]]:
    """(parent, name) pairs declared more than once for a given resource type.

    A non-empty result means ARM will hit "resource is not defined in the
    template" whenever one same-named twin is condition-excluded.
    """
    seen: set[tuple[str, str]] = set()
    dups: list[tuple[str, str]] = []
    for decl in resource_declarations(template, type_substr):
        key = (decl["parent"], decl["name"])
        if key in seen:
            dups.append(key)
        else:
            seen.add(key)
    return dups

