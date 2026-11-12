"""Pipeline apply of an optional Foundry add-on: an incomplete configuration warns and skips, it never fails the run.

The project pipeline runs the add-on launchers (45 MCP & AI Gateway, 46 Factory Chat Agent, 47 live voice) as its last
steps with ``apply --apply``. A configuration that cannot be applied yet (the create-factory quickstart turns the MCP on
before its images and app registration exist, byor-159 run 43192891708) becomes a GitHub Actions and Azure DevOps
warning and a ``skipped-incomplete-configuration`` result without contacting Azure. validate and plan, and direct
callers of the launchers' run(), keep failing on it.
"""
from __future__ import annotations

import sys

SKIPPED_INCOMPLETE = "skipped-incomplete-configuration"


def skipped_incomplete(reason: str) -> dict:
    return {"mode": SKIPPED_INCOMPLETE, "reason": reason, "mutations": False}


def _github_message(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _github_property(text: str) -> str:
    return _github_message(text).replace(":", "%3A").replace(",", "%2C")


def warn_skipped(addon: str, result: dict) -> None:
    """Annotate the run in both orchestrators (each ignores the other's line) and keep the full reason in stderr."""
    reason = str(result["reason"])
    summary = f"{addon} skipped (incomplete configuration; the pipeline continues): {' '.join(reason.split())}"
    print(f"::warning title={_github_property(addon + ' skipped')}::{_github_message(summary)}", file=sys.stdout)
    print(f"##vso[task.logissue type=warning]{summary}", file=sys.stdout)
    print(f"WARNING: {addon} skipped; nothing was changed in Azure. Reason: {reason}", file=sys.stderr)
