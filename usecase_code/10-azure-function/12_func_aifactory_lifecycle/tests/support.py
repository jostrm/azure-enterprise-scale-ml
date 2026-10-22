"""Builders and fakes shared by the service, event and HTTP tests."""

from __future__ import annotations

import itertools
import uuid
from typing import Any

from aif_lifecycle.adapters.mock_backend import MockFactoryBackend
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import DummyWorkflowTracker, InstantTracker
from aif_lifecycle.application.guard import SelfProtection
from aif_lifecycle.application.service import LifecycleService
from aif_lifecycle.settings import RUNNER_TIMEOUT_SECONDS


def sequential_ids():
    counter = itertools.count(1)
    return lambda: str(uuid.UUID(int=next(counter)))


class FakeGitHub:
    """Records dispatches and answers run lookups like the GitHub REST API would."""

    def __init__(self):
        self.dispatches: list[dict[str, Any]] = []
        self.runs: dict[int, dict[str, Any]] = {}
        self.excerpts: dict[int, str] = {}
        self._next_run = 1000

    def dispatch(self, workflow: str, ref: str, inputs: dict[str, Any]) -> None:
        self.dispatches.append({"workflow": workflow, "ref": ref, "inputs": dict(inputs)})

    def complete(self, dispatch_index: int, conclusion: str = "success") -> dict[str, Any]:
        """Turn a recorded dispatch into a completed run and return its workflow_run payload."""
        inputs = self.dispatches[dispatch_index]["inputs"]
        self._next_run += 1
        run_id = self._next_run
        title = f"aif-step [{inputs['operation_id']}/{inputs['step']}/{inputs['target']}] {inputs['outcome']}"
        run = {"id": run_id, "name": "aif-dummy-step", "display_title": title, "status": "completed",
               "conclusion": conclusion, "html_url": f"https://github.com/jostrm/byor/actions/runs/{run_id}",
               "run_attempt": 1, "event": "workflow_dispatch", "path": ".github/workflows/aif-dummy-step.yml"}
        self.runs[run_id] = run
        if conclusion != "success":
            self.excerpts[run_id] = "Simulated failure for " + inputs["target"]
        return {"action": "completed", "workflow_run": dict(run), "repository": {"full_name": "jostrm/byor"}}

    def find_run(self, workflow: str, marker: str, created_after) -> dict[str, Any] | None:
        for run in self.runs.values():
            if marker in run["display_title"]:
                return dict(run)
        return None

    def get_run(self, run_id: int) -> dict[str, Any]:
        return dict(self.runs[run_id])

    def failure_excerpt(self, run_id: int) -> str:
        return self.excerpts.get(run_id, "")


def make_service(clock, *, protected=(), github: FakeGitHub | None = None, review_ttl_seconds=600,
                 poll_after_seconds=120, store=None):
    store = store or MemoryStore()
    backend = MockFactoryBackend(store, clock=clock, review_ttl_seconds=review_ttl_seconds, ids=sequential_ids())
    if github is None:
        tracker = InstantTracker()
    else:
        tracker = DummyWorkflowTracker(github, workflow="aif-dummy-step.yml", ref="main", duration_seconds=60)
    service = LifecycleService(backend=backend, tracker=tracker, store=store, guard=SelfProtection(protected),
                               clock=clock, ids=sequential_ids(), poll_after_seconds=poll_after_seconds,
                               github_repository="jostrm/byor", runner_timeout_seconds=RUNNER_TIMEOUT_SECONDS)
    return service


def step_names(operation) -> list[str]:
    return [step.name for step in operation.steps]


def confirm_current(service, operation, phrase=None):
    view = operation.to_public()["steps"][operation.current]
    return service.confirm(operation.id, {"confirmationToken": view["preview"]["confirmationToken"],
                                          "confirmationPhrase": phrase or view["preview"]["confirmationPhrase"]})


def run_to_completion(service, operation, limit=10):
    """Confirm every review in turn until the operation stops waiting for confirmation."""
    for _ in range(limit):
        if operation.status.value != "awaiting_confirmation":
            return operation
        operation = confirm_current(service, operation)
    raise AssertionError("operation kept asking for confirmation")
