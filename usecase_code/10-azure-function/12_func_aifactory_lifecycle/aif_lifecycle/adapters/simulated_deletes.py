"""AIF_DELETES=simulate: scenarios 4-6 rehearsed end to end without ever reaching the real Factory API.

- CatalogMirror: a read-only view of the real catalog in the mock backend's store format; writes are dropped.
- DeleteSimulation (Decorator): the real backend for every scenario except deletes, which the mock backend reviews and
  confirms over the mirror. A simulated delete leaves the real catalog unchanged.
- DeleteRoutingTracker (Strategy): a simulated delete's runs are dummy workflows (or instant runs without GitHub);
  everything else runs on the real tracker.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Callable

from ..domain.operation import Operation, Preview, Run
from ..ports import Catalog, ConfirmResult, StepRequest

SIMULATED = "Simulated: nothing is deleted and the Factory API is not called."


class CatalogMirror:
    """The StateStore calls MockFactoryBackend makes, answered from the real catalog and never written."""

    def __init__(self, payload: Callable[[], dict[str, Any]]):
        self._payload = payload

    def get(self, partition: str, key: str) -> tuple[dict[str, Any], str]:
        return {"factories": list(self._payload().get("factories") or [])}, "mirror"

    def insert(self, partition: str, key: str, value: dict[str, Any]) -> str:
        return "mirror"

    def replace(self, partition: str, key: str, value: dict[str, Any], etag: str) -> str:
        return "mirror"


class DeleteSimulation:
    delete_mode = "simulate"

    def __init__(self, real, simulator):
        self._real = real
        self._simulator = simulator
        self.name = real.name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)  # runner-only calls (status, refresh_catalog, accept_catalog, job_status)

    def catalog(self) -> Catalog:
        return self._real.catalog()

    def prepare(self, request: StepRequest) -> Preview:
        if not request.scenario.destructive:
            return self._real.prepare(request)
        preview = self._simulator.prepare(request)
        preview.plan = [SIMULATED, *(f"Would {line[0].lower()}{line[1:]}" for line in preview.plan)]
        preview.warnings = [*preview.warnings, "AIF_DELETES=simulate: the runs are dummy workflows."]
        return preview

    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult:
        if not request.scenario.destructive:
            return self._real.confirm(request, preview, phrase)
        result = self._simulator.confirm(request, preview, phrase)
        return replace(result, job={**result.job, "simulated": True})

    def finalize(self, request: StepRequest, succeeded: bool) -> None:
        if not request.scenario.destructive:
            self._real.finalize(request, succeeded)


class DeleteRoutingTracker:
    def __init__(self, real, simulated):
        self._real = real
        self._simulated = simulated
        self.name = real.name

    def _tracker(self, operation: Operation):
        return self._simulated if operation.scenario.destructive else self._real

    def advance(self, operation: Operation, now: datetime) -> None:
        self._tracker(operation).advance(operation, now)

    def poll(self, operation: Operation, run: Run, now: datetime) -> dict[str, Any] | None:
        return self._tracker(operation).poll(operation, run, now)

    def observe(self, status: dict[str, Any]) -> dict[str, Any] | None:
        return self._real.observe(status)  # status observations come from the real API's jobs only

    def failure_excerpt(self, run_id: int | None) -> str:
        return self._simulated.failure_excerpt(run_id) or self._real.failure_excerpt(run_id)
