"""GitHub `workflow_run` payloads: parse what the Function needs and correlate through the run name.

Runs dispatched by this Function are named `aif-step [<operationId>/<step>/<target>] <outcome>[ no-relay]` (and
`aif-ops [...]` for the runner executor), the way byor-120's `factory-lifecycle [<run_id>]` carries its id. The marker
is anchored to the start of the run name so a title that merely contains it (a PR title, an injected input) never
correlates. See https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..domain.errors import ValidationFailed

WORKFLOW_FILES = ("aif-dummy-step.yml", "aif-ops.yml")
_MARKER = re.compile(
    r"(?:aif-step|aif-ops) \[(?P<operation>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"/(?P<step>\d{1,3})/(?P<target>[a-z0-9-]{1,90})\](?: [a-z0-9-]{1,40})?(?: no-relay)?")


@dataclass(frozen=True)
class WorkflowRunObservation:
    action: str
    run_id: int
    workflow: str
    title: str
    status: str
    conclusion: str | None
    html_url: str
    attempt: int
    event: str = ""
    path: str = ""
    repository: str = ""


def parse_workflow_run(payload: Any) -> WorkflowRunObservation:
    run = payload.get("workflow_run") if isinstance(payload, dict) else None
    try:
        repository = payload.get("repository") or {}
        return WorkflowRunObservation(
            action=str(payload.get("action") or ""), run_id=int(run["id"]), workflow=str(run.get("name") or ""),
            title=str(run.get("display_title") or run.get("name") or ""), status=str(run["status"]),
            conclusion=run.get("conclusion"), html_url=str(run.get("html_url") or ""),
            attempt=int(run.get("run_attempt") or 1), event=str(run.get("event") or ""),
            path=str(run.get("path") or ""), repository=str(repository.get("full_name") or ""))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValidationFailed("The payload is not a GitHub workflow_run event.", code="invalid-event") from None


def from_this_function(observed: WorkflowRunObservation, repository: str | None) -> bool:
    """Only runs this Function dispatched count: workflow_dispatch, one of its workflow files, its repository."""
    if observed.event and observed.event != "workflow_dispatch":
        return False
    if observed.path and observed.path.rsplit("/", 1)[-1].split("@", 1)[0] not in WORKFLOW_FILES:
        return False
    return not (repository and observed.repository and observed.repository.lower() != repository.lower())


def run_marker(operation_id: str, step: int, target: str) -> str:
    return f"[{operation_id}/{step}/{target}]"


def correlate(title: str) -> tuple[str, int, str] | None:
    match = _MARKER.fullmatch(title or "")
    if match is None:
        return None
    return match["operation"], int(match["step"]), match["target"]
