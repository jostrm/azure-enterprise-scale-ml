"""GitHub `workflow_run` payloads: parse what the Function needs and correlate through the run name.

Runs dispatched by this Function carry `[<operationId>/<step>/<target>]` in their run name (`run-name:`), the way
byor-120's `factory-lifecycle [<run_id>]` does. See
https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..domain.errors import ValidationFailed

_MARKER = re.compile(
    r"\[(?P<operation>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(?P<step>\d{1,3})/(?P<target>[a-z0-9-]{1,90})\]")


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


def parse_workflow_run(payload: Any) -> WorkflowRunObservation:
    run = payload.get("workflow_run") if isinstance(payload, dict) else None
    try:
        return WorkflowRunObservation(
            action=str(payload.get("action") or ""), run_id=int(run["id"]), workflow=str(run.get("name") or ""),
            title=str(run.get("display_title") or run.get("name") or ""), status=str(run["status"]),
            conclusion=run.get("conclusion"), html_url=str(run.get("html_url") or ""),
            attempt=int(run.get("run_attempt") or 1))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValidationFailed("The payload is not a GitHub workflow_run event.", code="invalid-event") from None


def run_marker(operation_id: str, step: int, target: str) -> str:
    return f"[{operation_id}/{step}/{target}]"


def correlate(title: str) -> tuple[str, int, str] | None:
    match = _MARKER.search(title or "")
    if match is None:
        return None
    return match["operation"], int(match["step"]), match["target"]
