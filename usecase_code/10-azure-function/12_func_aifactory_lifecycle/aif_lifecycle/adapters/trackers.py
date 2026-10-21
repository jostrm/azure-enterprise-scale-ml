"""Execution trackers (Strategy): how a confirmed step's runs execute and are observed.

- InstantTracker (AIF_EXECUTOR=inprocess with the mock): runs finish at once; the fast local loop.
- ApiJobTracker (AIF_EXECUTOR=inprocess with rest/sdk): the Factory API started the job; the poller reads its status.
- DummyWorkflowTracker (AIF_EXECUTOR=github-dummy): one `aif-dummy-step.yml` run per resource group, dispatched in
  order; workflow_run events (relay or webhook) advance them, and the poller recovers lost events.
- RunnerJobTracker (AIF_EXECUTOR=github-runner): the Factory API started the job at confirm; status checks are handed
  to aif-ops.yml on the API host, one at a time, and their results update the run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..application.events import run_marker
from ..domain.operation import Operation, Run
from ..ports import GitHubPort
from .factory_api import job_observation


def planned_outcome(operation: Operation, run: Run) -> str:
    fail_at = (operation.options.get("simulate") or {}).get("failAt")
    if fail_at and (fail_at == run.target or (fail_at == operation.step.name and run is operation.step.runs[0])):
        return "failure"
    return "success"


def relayed(operation: Operation, run: Run) -> bool:
    drop_at = (operation.options.get("simulate") or {}).get("dropEventAt")
    return not drop_at or drop_at not in (run.target, operation.step.name)


class InstantTracker:
    name = "inprocess"

    def advance(self, operation: Operation, now: datetime) -> None:
        while (run := operation.next_dispatchable_run()) is not None:
            operation.run_dispatched(run.target, now)
            change = operation.run_update(target=run.target, status="completed", conclusion=planned_outcome(operation, run),
                                          run_id=None, html_url=None, source="inprocess", now=now)
            if change != "progressed":
                return

    def poll(self, operation: Operation, run: Run, now: datetime) -> dict[str, Any] | None:
        return None

    def observe(self, status: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def failure_excerpt(self, run_id: int | None) -> str:
        return ""


class ApiJobTracker:
    """The Factory API already dispatched the work at confirm; observe its job (or creation workflow) status."""

    name = "inprocess"

    def __init__(self, backend):
        self._backend = backend

    def advance(self, operation: Operation, now: datetime) -> None:
        run = operation.next_dispatchable_run()
        if run is not None:
            operation.run_dispatched(run.target, now)

    def poll(self, operation: Operation, run: Run, now: datetime) -> dict[str, Any] | None:
        return self.observe(self._backend.job_status(operation.step.job))

    def observe(self, status: dict[str, Any]) -> dict[str, Any] | None:
        return job_observation(status)

    def failure_excerpt(self, run_id: int | None) -> str:
        return ""


class DummyWorkflowTracker:
    name = "github-dummy"

    def __init__(self, github: GitHubPort, *, workflow: str, ref: str, duration_seconds: int):
        self._github = github
        self._workflow = workflow
        self._ref = ref
        self._duration = duration_seconds

    def advance(self, operation: Operation, now: datetime) -> None:
        run = operation.next_dispatchable_run()
        if run is None:
            return
        self._github.dispatch(self._workflow, self._ref, {
            "operation_id": operation.id, "step": str(operation.current), "target": run.target,
            "outcome": planned_outcome(operation, run), "duration_seconds": str(self._duration),
            "relay": "true" if relayed(operation, run) else "false"})
        operation.run_dispatched(run.target, now)

    def poll(self, operation: Operation, run: Run, now: datetime) -> dict[str, Any] | None:
        if run.run_id:
            data = self._github.get_run(run.run_id)
        else:
            created = datetime.strptime(operation.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            data = self._github.find_run(self._workflow, run_marker(operation.id, operation.current, run.target), created)
        if not data:
            return None
        return {"status": data.get("status"), "conclusion": data.get("conclusion"), "run_id": data.get("id"),
                "html_url": data.get("html_url")}

    def observe(self, status: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def failure_excerpt(self, run_id: int | None) -> str:
        return self._github.failure_excerpt(run_id) if run_id else ""


class RunnerJobTracker:
    name = "github-runner"

    def __init__(self, backend, github: GitHubPort):
        self._backend = backend
        self._github = github

    def advance(self, operation: Operation, now: datetime) -> None:
        run = operation.next_dispatchable_run()
        if run is not None:
            operation.run_dispatched(run.target, now)

    def poll(self, operation: Operation, run: Run, now: datetime) -> dict[str, Any] | None:
        """Ask the runner for the job status (one check at a time); the result arrives on the results route."""
        if operation.handoff is None:
            operation.hand_off("status", self._backend.status(operation), now)
        return None

    def observe(self, status: dict[str, Any]) -> dict[str, Any] | None:
        return job_observation(status)

    def failure_excerpt(self, run_id: int | None) -> str:
        return self._github.failure_excerpt(run_id) if run_id else ""
