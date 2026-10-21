"""Operation state machine (State pattern as an explicit transition table).

An operation runs a scenario as ordered steps. Each step is reviewed (prepare -> preview), confirmed once with the
token bound to that exact preview, then executed as zero or more GitHub runs that complete in order. The model mirrors
the Agent Factory's reviewed operations: one confirm per Factory API confirmation, CAS-saved before the
non-idempotent call, and an uncertain confirm is terminal - never retried.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .errors import ConfirmationExpired, InvalidState, ValidationFailed
from .scenarios import Scenario

HISTORY_LIMIT = 100
EXCERPT_LIMIT = 2000


class Status(str, Enum):
    PENDING = "pending"
    PREPARING = "preparing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMING = "confirming"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    EXPIRED = "expired"
    BLOCKED = "blocked"


TERMINAL = frozenset({Status.SUCCEEDED, Status.FAILED, Status.UNCERTAIN, Status.EXPIRED, Status.BLOCKED})

_TRANSITIONS = {
    Status.PENDING: {Status.PREPARING},
    Status.PREPARING: {Status.AWAITING_CONFIRMATION, Status.BLOCKED, Status.FAILED},
    Status.AWAITING_CONFIRMATION: {Status.CONFIRMING, Status.EXPIRED},
    Status.CONFIRMING: {Status.RUNNING, Status.SUCCEEDED, Status.FAILED, Status.UNCERTAIN},
    Status.RUNNING: {Status.SUCCEEDED, Status.FAILED, Status.UNCERTAIN},
}

_RUN_RANK = {"pending": 0, "requested": 1, "queued": 1, "waiting": 1, "in_progress": 2, "completed": 3}


class StepKind(str, Enum):
    CONFIGURE = "configure"
    BOOTSTRAP = "bootstrap"
    DEPLOY = "deploy"
    DELETE = "delete"


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_epoch(epoch: float) -> str:
    return iso(datetime.fromtimestamp(epoch, timezone.utc))


@dataclass
class Preview:
    plan: list[str]
    affected_resource_groups: list[str]
    blockers: list[str]
    can_execute: bool
    expires_at: float
    confirmation_phrase: str | None = None
    backend_ref: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "plan": list(self.plan),
            "affectedResourceGroups": list(self.affected_resource_groups),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "canExecute": self.can_execute,
            "expiresAt": _iso_epoch(self.expires_at),
            "confirmationPhrase": self.confirmation_phrase,
        }


@dataclass
class Run:
    target: str
    status: str = "pending"
    conclusion: str | None = None
    run_id: int | None = None
    html_url: str | None = None
    source: str | None = None
    updated_at: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"

    def public(self) -> dict[str, Any]:
        return {"target": self.target, "status": self.status, "conclusion": self.conclusion, "runId": self.run_id,
                "url": self.html_url, "source": self.source, "updatedAt": self.updated_at}


@dataclass
class Step:
    name: str
    kind: StepKind
    status: Status = Status.PENDING
    preview: Preview | None = None
    plan_hash: str | None = None
    runs: list[Run] = field(default_factory=list)
    job: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    handoff: dict[str, Any] | None = None  # the runner call this step waits for: action, nonce, since

    @classmethod
    def new(cls, name: str, kind: StepKind) -> "Step":
        return cls(name=name, kind=kind)


def plan_hash(operation_id: str, index: int, step: Step) -> str:
    """The confirmation token: binds a confirm to this operation, step and exact preview (incl. the API's review)."""
    payload = {"operationId": operation_id, "step": index, "name": step.name, "kind": step.kind.value,
               "preview": step.preview.public() if step.preview else None,
               "backendRef": step.preview.backend_ref if step.preview else None}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Operation:
    id: str
    scenario: Scenario
    target: str
    settings: dict[str, Any]
    steps: list[Step]
    backend: str
    executor: str
    status: Status
    current: int
    created_at: str
    updated_at: str
    history: list[dict[str, Any]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    resolved: dict[str, Any] = field(default_factory=dict)
    finalized: list[int] = field(default_factory=list)
    etag: str | None = field(default=None, compare=False)

    # ----- creation and queries -----

    @classmethod
    def create(cls, *, operation_id: str, scenario: Scenario, target: str, settings: dict[str, Any],
               steps: list[Step], backend: str, executor: str, now: datetime,
               options: dict[str, Any] | None = None, resolved: dict[str, Any] | None = None) -> "Operation":
        if not steps:
            raise ValueError("An operation needs at least one step.")
        stamp = iso(now)
        operation = cls(id=operation_id, scenario=scenario, target=target, settings=dict(settings), steps=steps,
                        backend=backend, executor=executor, status=Status.PREPARING, current=0,
                        created_at=stamp, updated_at=stamp, options=dict(options or {}), resolved=dict(resolved or {}))
        operation._move(steps[0], Status.PREPARING, now)
        operation._log(now, "created", f"{scenario.value} for {target}")
        return operation

    @property
    def step(self) -> Step:
        return self.steps[self.current]

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    # ----- review -----

    def review_ready(self, preview: Preview, now: datetime) -> None:
        step = self.step
        executable = preview.can_execute and not preview.blockers
        self._move(step, Status.AWAITING_CONFIRMATION if executable else Status.BLOCKED, now)
        step.preview = preview
        step.plan_hash = plan_hash(self.id, self.current, step)
        self._sync(now)
        self._log(now, "review-ready" if executable else "review-blocked", "; ".join(preview.blockers) or step.name)

    def prepare_failed(self, code: str, detail: str, now: datetime) -> None:
        step = self.step
        self._move(step, Status.FAILED, now)
        step.failure = {"code": code, "detail": detail}
        self._sync(now)
        self._log(now, "prepare-failed", f"{step.name}: {code}")

    def expire_if_due(self, now: datetime) -> bool:
        step = self.step
        if step.status is Status.AWAITING_CONFIRMATION and step.preview and now.timestamp() >= step.preview.expires_at:
            self._move(step, Status.EXPIRED, now)
            self._sync(now)
            self._log(now, "review-expired", step.name)
            return True
        return False

    # ----- confirmation -----

    def confirm(self, token: str | None, phrase: str | None, now: datetime) -> None:
        step = self.step
        if step.status is not Status.AWAITING_CONFIRMATION:
            raise InvalidState(f"Step '{step.name}' is {step.status.value}; only a step awaiting confirmation can be confirmed.")
        if self.expire_if_due(now):
            raise ConfirmationExpired(f"The review of step '{step.name}' expired; prepare the operation again.")
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), (step.plan_hash or "").encode()):
            raise ValidationFailed("The confirmation token does not match the current review.", code="confirmation-mismatch")
        expected = step.preview.confirmation_phrase if step.preview else None
        if expected and phrase != expected:
            raise ValidationFailed(f"Type the exact confirmation phrase: {expected}", code="confirmation-phrase-mismatch")
        self._move(step, Status.CONFIRMING, now)
        self._sync(now)
        self._log(now, "confirming", step.name)

    def confirm_accepted(self, job: dict[str, Any], targets: list[str], now: datetime) -> None:
        step = self.step
        step.job = dict(job or {})
        if targets:
            self._move(step, Status.RUNNING, now)
            step.runs = [Run(target=target) for target in targets]
            self._sync(now)
            self._log(now, "running", f"{step.name}: {', '.join(targets)}")
        else:
            self._move(step, Status.SUCCEEDED, now)
            self._log(now, "step-succeeded", step.name)
            self._advance(now)

    def confirm_rejected(self, code: str, detail: str, now: datetime) -> None:
        step = self.step
        self._move(step, Status.FAILED, now)
        step.failure = {"code": code, "detail": detail}
        self._sync(now)
        self._log(now, "confirm-rejected", f"{step.name}: {code}")

    def confirm_uncertain(self, detail: str, now: datetime) -> None:
        step = self.step
        self._move(step, Status.UNCERTAIN, now)
        step.failure = {"code": "completion-unknown", "detail": detail}
        self._sync(now)
        self._log(now, "confirm-uncertain", f"{step.name}: never retried; reconcile the API job first")

    # ----- runs -----

    def next_dispatchable_run(self) -> Run | None:
        step = self.step
        if step.status is not Status.RUNNING:
            return None
        for run in step.runs:
            if run.succeeded:
                continue
            return run if run.status == "pending" else None
        return None

    def run_dispatched(self, target: str, now: datetime, *, run_id: int | None = None, html_url: str | None = None) -> None:
        run = self._find_run(target=target)
        if run is None or run.status != "pending":
            raise InvalidState(f"Run '{target}' cannot be dispatched now.")
        run.status, run.run_id, run.html_url, run.updated_at = "queued", run_id, html_url, iso(now)
        self.updated_at = iso(now)
        self._log(now, "run-dispatched", target)

    def run_update(self, *, status: str, conclusion: str | None, run_id: int | None, html_url: str | None,
                   source: str, now: datetime, target: str | None = None) -> str:
        """Apply one observed run state (relay, webhook or poller). Returns what changed."""
        step = self.step
        run = self._find_run(target=target, run_id=run_id)
        if step.status is not Status.RUNNING or run is None:
            return "ignored"
        old_rank, new_rank = _RUN_RANK.get(run.status, 0), _RUN_RANK.get(status, 0)
        if new_rank < old_rank or (new_rank == old_rank and run.status == "completed"):
            return "ignored"
        run.status, run.conclusion, run.source, run.updated_at = status, conclusion, source, iso(now)
        run.run_id = run_id if run_id is not None else run.run_id
        run.html_url = html_url or run.html_url
        self.updated_at = iso(now)
        if status != "completed":
            self._log(now, "run-" + status, run.target)
            return "progressed"
        if conclusion != "success":
            self._move(step, Status.FAILED, now)
            step.failure = {"code": "run-failed", "target": run.target, "conclusion": conclusion,
                            "runUrl": run.html_url, "runId": run.run_id}
            self._sync(now)
            self._log(now, "step-failed", f"{step.name}: {run.target} {conclusion}")
            return "step-failed"
        self._log(now, "run-succeeded", run.target)
        if all(item.succeeded for item in step.runs):
            self._move(step, Status.SUCCEEDED, now)
            self._log(now, "step-succeeded", step.name)
            self._advance(now)
            return "step-succeeded"
        return "progressed"

    # ----- runner hand-off (AIF_EXECUTOR=github-runner) -----

    @property
    def handoff(self) -> dict[str, Any] | None:
        return self.step.handoff

    def hand_off(self, action: str, nonce: str, now: datetime) -> None:
        self.step.handoff = {"action": action, "nonce": nonce, "since": iso(now)}
        self.updated_at = iso(now)
        self._log(now, "handed-off", f"{self.step.name}: {action} on the runner")

    def take_handoff(self, action: str, nonce: str, step: int | None) -> bool:
        """Accept a runner result only for the hand-off this step is waiting for; clears it."""
        pending = self.step.handoff
        if not pending or step != self.current or pending["action"] != action or \
                not hmac.compare_digest(str(pending["nonce"]).encode(), str(nonce).encode()):
            return False
        self.step.handoff = None
        return True

    def attach_failure_excerpt(self, excerpt: str) -> None:
        if self.step.failure is not None and excerpt:
            self.step.failure["logExcerpt"] = excerpt[-EXCERPT_LIMIT:]

    def add_step(self, step: Step) -> None:
        """Append a step the API announced after a confirm (for example the next bootstrap stage)."""
        self.steps.append(step)

    # ----- serialization -----

    def to_public(self) -> dict[str, Any]:
        steps = []
        for index, step in enumerate(self.steps):
            preview = None
            if step.preview is not None:
                preview = step.preview.public()
                preview["confirmationToken"] = step.plan_hash if step.status is Status.AWAITING_CONFIRMATION else None
            waiting = {"action": step.handoff["action"], "since": step.handoff["since"]} if step.handoff else None
            steps.append({"index": index, "name": step.name, "kind": step.kind.value, "status": step.status.value,
                          "preview": preview, "runs": [run.public() for run in step.runs],
                          "failure": copy.deepcopy(step.failure), "startedAt": step.started_at,
                          "finishedAt": step.finished_at, "waitingFor": waiting})
        return {"operationId": self.id, "scenario": self.scenario.value, "scenarioNumber": self.scenario.number,
                "target": self.target, "status": self.status.value, "backend": self.backend,
                "executor": self.executor, "currentStep": self.current, "createdAt": self.created_at,
                "updatedAt": self.updated_at, "steps": steps, "history": copy.deepcopy(self.history)}

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record.pop("etag", None)
        return json.loads(json.dumps(record, default=_enum_value))

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Operation":
        data = copy.deepcopy(record)
        steps = []
        for item in data.pop("steps"):
            preview = Preview(**item.pop("preview")) if item.get("preview") else None
            item.pop("preview", None)
            runs = [Run(**run) for run in item.pop("runs", [])]
            steps.append(Step(kind=StepKind(item.pop("kind")), status=Status(item.pop("status")),
                              preview=preview, runs=runs, **item))
        return cls(scenario=Scenario(data.pop("scenario")), status=Status(data.pop("status")), steps=steps, **data)

    # ----- internals -----

    def _move(self, step: Step, status: Status, now: datetime) -> None:
        if status not in _TRANSITIONS.get(step.status, set()):
            raise InvalidState(f"Step '{step.name}' cannot move from {step.status.value} to {status.value}.")
        step.status = status
        if status is Status.PREPARING:
            step.started_at = iso(now)
        if status in TERMINAL:
            step.finished_at = iso(now)

    def _sync(self, now: datetime) -> None:
        self.status = self.step.status
        self.updated_at = iso(now)

    def _advance(self, now: datetime) -> None:
        if self.current + 1 < len(self.steps):
            self.current += 1
            self._move(self.step, Status.PREPARING, now)
            self._sync(now)
        else:
            self.status = Status.SUCCEEDED
            self.updated_at = iso(now)
            self._log(now, "operation-succeeded", self.target)

    def _find_run(self, *, target: str | None = None, run_id: int | None = None) -> Run | None:
        """A run is matched by its bound run id; by target only while no other run id is bound to it."""
        runs = self.step.runs
        if run_id is not None:
            for run in runs:
                if run.run_id == run_id:
                    return run
        if target is not None:
            for run in runs:
                if run.target == target:
                    if run_id is not None and run.run_id is not None and run.run_id != run_id:
                        return None
                    return run
        return None

    def _log(self, now: datetime, event: str, detail: str) -> None:
        self.history.append({"at": iso(now), "event": event, "step": self.current, "detail": detail})
        del self.history[:-HISTORY_LIMIT]


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")
