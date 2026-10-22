"""Ports (interfaces) between the lifecycle service and its adapters, plus the shared catalog model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .domain.operation import Operation, Preview, Run, StepKind
from .domain.scenarios import Scenario


class StoreConflict(Exception):
    """The key already exists (insert) or changed since it was read (replace)."""


class StoreMissing(Exception):
    """The key does not exist."""


class Deferred(Exception):
    """The backend handed the call to the runner; its signed result finishes the step later (apply_runner_result)."""

    def __init__(self, action: str, nonce: str):
        super().__init__(f"{action} handed to the runner")
        self.action = action
        self.nonce = nonce


class StateStore(Protocol):
    """Small key-value store with optimistic concurrency (ETags). `value["status"]` is queryable."""

    def get(self, partition: str, key: str) -> tuple[dict[str, Any], str] | None: ...
    def insert(self, partition: str, key: str, value: dict[str, Any]) -> str: ...
    def replace(self, partition: str, key: str, value: dict[str, Any], etag: str) -> str: ...
    def upsert(self, partition: str, key: str, value: dict[str, Any]) -> str: ...
    def delete(self, partition: str, key: str) -> None: ...
    def query(self, partition: str, *, status: str | None = None) -> list[tuple[str, dict[str, Any], str]]: ...


@dataclass(frozen=True)
class CatalogScaleset:
    id: str
    environment: str
    suffix: str
    status: str = "configured"


@dataclass(frozen=True)
class CatalogProject:
    id: str
    number: str
    key: str
    placements: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CatalogFactory:
    id: str
    key: str
    prefix: str
    region: str
    region_short_name: str | None
    scale_sets: tuple[CatalogScaleset, ...]
    projects: tuple[CatalogProject, ...]


@dataclass(frozen=True)
class Catalog:
    """The Factory API's `GET /api/v1/factory-catalog` answer, reduced to what IDs resolve against."""

    revision: str
    factories: tuple[CatalogFactory, ...]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Catalog":
        factories = []
        for item in payload.get("factories") or []:
            scale_sets = tuple(CatalogScaleset(id=s["id"], environment=s["environment"], suffix=str(s["suffix"]),
                                               status=s.get("status") or "configured")
                               for s in item.get("scale_sets") or [])
            projects = tuple(CatalogProject(id=p["id"], number=str(p["number"]), key=p.get("key") or "",
                                            placements=tuple((pl["environment"], pl["scale_set_id"])
                                                             for pl in p.get("placements") or []
                                                             if pl.get("scale_set_id")))
                             for p in item.get("projects") or [])
            factories.append(CatalogFactory(id=item["id"], key=item.get("key") or "", prefix=item.get("prefix") or "",
                                            region=item.get("region") or "",
                                            region_short_name=item.get("region_short_name"),
                                            scale_sets=scale_sets, projects=projects))
        return cls(revision=str(payload.get("revision") or payload.get("source_revision") or ""),
                   factories=tuple(factories))


@dataclass(frozen=True)
class StepRequest:
    """Everything a backend needs to prepare or confirm one step."""

    operation_id: str
    scenario: Scenario
    step_index: int
    step_name: str
    kind: StepKind
    target: str
    resolved: dict[str, Any]
    settings: dict[str, Any]
    options: dict[str, Any]


@dataclass(frozen=True)
class ConfirmResult:
    job: dict[str, Any]
    targets: list[str]
    resolved_updates: dict[str, Any] = field(default_factory=dict)


class FactoryBackend(Protocol):
    """Strategy: mock, REST (option 1) or SDK (option 2) access to the Factory API."""

    name: str
    delete_mode: str  # "mock", "refuse" (real API, the default), "simulate" or "allow"

    def catalog(self) -> Catalog: ...
    def prepare(self, request: StepRequest) -> Preview: ...
    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult: ...
    def finalize(self, request: StepRequest, succeeded: bool) -> None: ...


class ExecutionTracker(Protocol):
    """Strategy: how a confirmed step's runs execute and are observed."""

    name: str

    def advance(self, operation: Operation, now: datetime) -> None: ...
    def poll(self, operation: Operation, run: Run, now: datetime) -> dict[str, Any] | None: ...
    def observe(self, status: dict[str, Any]) -> dict[str, Any] | None: ...
    def failure_excerpt(self, run_id: int | None) -> str: ...


class GitHubPort(Protocol):
    def dispatch(self, workflow: str, ref: str, inputs: dict[str, Any]) -> None: ...
    def find_run(self, workflow: str, marker: str, created_after: datetime) -> dict[str, Any] | None: ...
    def get_run(self, run_id: int) -> dict[str, Any]: ...
    def failure_excerpt(self, run_id: int) -> str: ...
