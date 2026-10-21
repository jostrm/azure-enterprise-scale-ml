"""LifecycleService: the Facade the Function and the runner CLI call.

prepare -> (review) -> confirm -> runs -> events/poller -> next review ... -> succeeded | failed | uncertain.
Every confirm is saved as CONFIRMING (compare-and-swap) before the non-idempotent Factory API call, and an
uncertain outcome is terminal: it is never retried.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from .. import __version__
from ..domain.errors import (ConfirmationExpired, InProgress, LifecycleError, OperationNotFound, UpstreamError,
                             UpstreamTimeout, UpstreamUnavailable, ValidationFailed)
from ..domain.ids import FactoryId, ProjectId, ScalesetId
from ..domain.operation import Operation, Status, iso
from ..domain.scenarios import Scenario
from ..ports import ExecutionTracker, FactoryBackend, StateStore, StepRequest, StoreConflict
from .events import WorkflowRunObservation, correlate, from_this_function, parse_workflow_run
from .guard import SelfProtection
from .planner import plan

OPERATIONS, TARGETS, DELIVERIES = "operation", "target", "delivery"
SIMULATION_KEYS = {"failAt", "uncertainAt", "rejectAt", "dropEventAt"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PARSERS = {"factory": FactoryId.parse, "scaleset": ScalesetId.parse, "project": ProjectId.parse}
_SAFE_KEY = re.compile(r"[A-Za-z0-9._-]{1,128}")

log = logging.getLogger("aif_lifecycle")


class LifecycleService:
    def __init__(self, *, backend: FactoryBackend, tracker: ExecutionTracker, store: StateStore,
                 guard: SelfProtection, clock, ids: Callable[[], str] | None = None, poll_after_seconds: int = 120,
                 github_repository: str | None = None):
        self._backend = backend
        self._tracker = tracker
        self._store = store
        self._guard = guard
        self._clock = clock
        self._ids = ids or (lambda: str(uuid.uuid4()))
        self._poll_after = poll_after_seconds
        self._repository = github_repository

    # ----- queries -----

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "backend": self._backend.name, "executor": self._tracker.name}

    def get(self, operation_id: str) -> Operation:
        operation = self._load(operation_id)
        if operation.expire_if_due(self._clock.now()):
            self._save(operation)
        return operation

    def list(self, limit: int = 50) -> list[Operation]:
        operations = [Operation.from_record(value) for _, value, _ in self._store.query(OPERATIONS)]
        return sorted(operations, key=lambda item: (item.created_at, item.id), reverse=True)[:limit]

    # ----- commands -----

    def prepare(self, scenario_slug: str, body: Any) -> Operation:
        scenario = Scenario.parse(scenario_slug)
        body = _object(body)
        target = self._target(scenario, body)
        settings = body.get("settings", {})
        if not isinstance(settings, dict) or not all(isinstance(key, str) for key in settings):
            raise ValidationFailed("settings must be a JSON object of catalog setting names to values.")
        options = self._options(body)
        self._guard.check(target)
        steps, resolved = plan(scenario, target, self._backend.catalog(), options)
        operation = Operation.create(operation_id=self._ids(), scenario=scenario, target=str(target), settings=settings,
                                     steps=steps, backend=self._backend.name, executor=self._tracker.name,
                                     now=self._clock.now(), options=options, resolved=resolved)
        self._claim(operation)
        operation.etag = self._store.insert(OPERATIONS, operation.id, operation.to_record())
        _info(operation, f"prepared {scenario.value} for {operation.target}")
        self._drive(operation)
        self._save(operation)
        return operation

    def confirm(self, operation_id: str, body: Any) -> Operation:
        body = _object(body)
        operation = self._load(operation_id)
        now = self._clock.now()
        phrase = body.get("confirmationPhrase")
        try:
            operation.confirm(body.get("confirmationToken"), phrase, now)
        except ConfirmationExpired:
            self._save(operation)
            raise
        try:
            self._save(operation)
        except StoreConflict:
            raise InProgress("Another request is confirming this operation.") from None
        _info(operation, f"confirming step {operation.current} ({operation.step.name}); submitted once")
        request = self._request(operation, operation.current)
        try:
            result = self._backend.confirm(request, operation.step.preview, phrase)
        except (UpstreamTimeout, UpstreamUnavailable, UpstreamError) as error:
            operation.confirm_uncertain(error.detail, now)
        except LifecycleError as error:
            operation.confirm_rejected(error.code, error.detail, now)
        except Exception:  # noqa: BLE001 - an unknown transport outcome must be uncertain, never retried
            log.exception("operationId=%s confirmation outcome unknown", operation.id)
            operation.confirm_uncertain("The confirmation outcome is unknown; reconcile before any new operation.", now)
        else:
            operation.resolved.update(result.resolved_updates)
            operation.confirm_accepted(result.job, result.targets, now)
        self._drive(operation)
        self._save(operation)
        _info(operation, f"after confirm: {operation.status.value}")
        return operation

    def handle_event(self, event: str, delivery_id: str | None, payload: Any, *, source: str = "relay") -> dict[str, Any]:
        """Receive and apply one GitHub event in the same call (inline processing)."""
        received = self.receive_event(event, delivery_id, payload)
        if received["result"] != "accepted":
            return received
        result = self.apply_event(received["message"], source=source)
        self.record_delivery(received["message"]["delivery"])
        return result

    def receive_event(self, event: str, delivery_id: str | None, payload: Any) -> dict[str, Any]:
        """The fast part: validate and check the delivery ID. Returns the message to apply.

        The delivery is recorded only after it was applied or queued (record_delivery), so a delivery whose
        processing failed can be redelivered instead of being answered as a duplicate.
        """
        if event == "ping":
            return {"result": "pong"}
        if event != "workflow_run":
            return {"result": "ignored"}
        observed = parse_workflow_run(payload)
        if not delivery_id:
            raise ValidationFailed("The X-GitHub-Delivery header is required.")
        key = _delivery_key(delivery_id)
        if self._store.get(DELIVERIES, key) is not None:
            return {"result": "duplicate"}
        return {"result": "accepted", "message": {"event": event, "delivery": key, "run": asdict(observed)}}

    def record_delivery(self, key: str) -> bool:
        try:
            self._store.insert(DELIVERIES, key, {"receivedAt": iso(self._clock.now())})
            return True
        except StoreConflict:
            return False

    def apply_event(self, message: dict[str, Any], *, source: str = "relay") -> dict[str, Any]:
        """Correlate through the run name and advance the operation (inline or from the queue)."""
        observed = WorkflowRunObservation(**message["run"])
        if not from_this_function(observed, self._repository):
            return {"result": "ignored"}
        marker = correlate(observed.title)
        if marker is None:
            return {"result": "uncorrelated"}
        operation_id, step_index, target = marker
        for _ in range(3):
            operation = self._load_or_none(operation_id)
            if operation is None:
                return {"result": "uncorrelated"}
            if operation.current != step_index:
                return {"result": "ignored", "operationId": operation.id}
            change = operation.run_update(target=target, status=observed.status, conclusion=observed.conclusion,
                                          run_id=observed.run_id, html_url=observed.html_url, source=source,
                                          now=self._clock.now())
            if change == "ignored":
                return {"result": "ignored", "operationId": operation.id}
            if change == "step-failed":
                operation.attach_failure_excerpt(self._excerpt(observed.run_id))
            self._drive(operation)
            try:
                self._save(operation)
            except StoreConflict:
                continue
            _info(operation, f"event {observed.status}/{observed.conclusion} for {target}: {change}")
            return {"result": "applied", "operationId": operation.id, "change": change}
        raise InProgress("The operation kept changing; the poller will apply this run state.")

    def reconcile(self) -> dict[str, int]:
        """Timer work: expire unconfirmed reviews, poll runs whose events are late, retry failed dispatches."""
        now = self._clock.now()
        summary = {"expired": 0, "polled": 0, "updated": 0}
        for _, value, etag in self._store.query(OPERATIONS, status=Status.AWAITING_CONFIRMATION.value):
            operation = Operation.from_record(value)
            operation.etag = etag
            if operation.expire_if_due(now) and self._save_quietly(operation):
                summary["expired"] += 1
        for _, value, etag in self._store.query(OPERATIONS, status=Status.RUNNING.value):
            operation = Operation.from_record(value)
            operation.etag = etag
            before = operation.to_record()
            for run in list(operation.step.runs):
                if operation.step.status is not Status.RUNNING:
                    break
                if run.status in ("pending", "completed") or not self._stale(run.updated_at, now):
                    continue
                summary["polled"] += 1
                try:
                    observed = self._tracker.poll(operation, run, now)
                except LifecycleError as error:
                    log.warning("operationId=%s poll failed: %s", operation.id, error.code)
                    continue
                if observed and observed.get("status"):
                    change = operation.run_update(target=run.target, status=observed["status"],
                                                  conclusion=observed.get("conclusion"), run_id=observed.get("run_id"),
                                                  html_url=observed.get("html_url"), source="poller", now=now)
                    if change == "step-failed":
                        operation.attach_failure_excerpt(self._excerpt(observed.get("run_id")))
            self._drive(operation)
            if operation.to_record() != before and self._save_quietly(operation):
                summary["updated"] += 1
        return summary

    # ----- driving the state machine -----

    def _drive(self, operation: Operation) -> None:
        now = self._clock.now()
        for _ in range(64):
            self._finalize(operation)
            if operation.is_terminal:
                return
            step = operation.step
            if step.status is Status.PREPARING:
                self._prepare_step(operation, now)
                continue
            if step.status is Status.RUNNING:
                before = _fingerprint(operation)
                try:
                    self._tracker.advance(operation, now)
                except LifecycleError as error:
                    log.warning("operationId=%s dispatch failed (%s); the reconciler retries", operation.id, error.code)
                    return
                if _fingerprint(operation) == before:
                    return
                continue
            return

    def _prepare_step(self, operation: Operation, now: datetime) -> None:
        try:
            preview = self._backend.prepare(self._request(operation, operation.current))
        except LifecycleError as error:
            operation.prepare_failed(error.code, error.detail, now)
            return
        if operation.scenario.destructive and not preview.confirmation_phrase:
            preview.confirmation_phrase = f"DELETE {operation.target}"
        operation.review_ready(preview, now)
        _info(operation, f"step {operation.current} ({operation.step.name}) is {operation.step.status.value}")

    def _finalize(self, operation: Operation) -> None:
        for index, step in enumerate(operation.steps):
            if index in operation.finalized or step.status not in (Status.SUCCEEDED, Status.FAILED):
                continue
            self._backend.finalize(self._request(operation, index), step.status is Status.SUCCEEDED)
            operation.finalized.append(index)

    def _request(self, operation: Operation, index: int) -> StepRequest:
        step = operation.steps[index]
        return StepRequest(operation_id=operation.id, scenario=operation.scenario, step_index=index,
                           step_name=step.name, kind=step.kind, target=operation.target,
                           resolved=dict(operation.resolved), settings=dict(operation.settings),
                           options=dict(operation.options))

    # ----- persistence -----

    def _claim(self, operation: Operation) -> None:
        found = self._store.get(TARGETS, operation.target)
        claim = {"operationId": operation.id, "status": "claimed"}
        try:
            if found is None:
                self._store.insert(TARGETS, operation.target, claim)
                return
            holder = self._load_or_none(found[0]["operationId"])
            if holder is not None:
                if holder.expire_if_due(self._clock.now()):
                    self._save_quietly(holder)
                if not holder.is_terminal:
                    raise InProgress(f"Operation {holder.id} is {holder.status.value} for {operation.target}.",
                                     extra={"operationId": holder.id})
            self._store.replace(TARGETS, operation.target, claim, found[1])
        except StoreConflict:
            raise InProgress(f"Another operation was just started for {operation.target}.") from None

    def _load(self, operation_id: str) -> Operation:
        operation = self._load_or_none(operation_id)
        if operation is None:
            raise OperationNotFound(f"Operation {operation_id} was not found.")
        return operation

    def _load_or_none(self, operation_id: str) -> Operation | None:
        if not isinstance(operation_id, str) or not _UUID.fullmatch(operation_id):
            return None
        found = self._store.get(OPERATIONS, operation_id)
        if found is None:
            return None
        operation = Operation.from_record(found[0])
        operation.etag = found[1]
        return operation

    def _save(self, operation: Operation) -> None:
        operation.etag = self._store.replace(OPERATIONS, operation.id, operation.to_record(), operation.etag)

    def _save_quietly(self, operation: Operation) -> bool:
        try:
            self._save(operation)
            return True
        except StoreConflict:
            return False

    # ----- helpers -----

    def _target(self, scenario: Scenario, body: dict[str, Any]):
        text = body.get(scenario.id_field)
        if not isinstance(text, str):
            raise ValidationFailed(f"Send {scenario.id_field} for {scenario.value}.")
        return _PARSERS[scenario.target_kind](text)

    def _options(self, body: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {}
        for flag in ("wholeWorkflow", "includeProjectSubnets", "includeKeyvaultAndResourceGroup"):
            if flag in body:
                if type(body[flag]) is not bool:
                    raise ValidationFailed(f"{flag} must be true or false.")
                options[flag] = body[flag]
        if "simulate" in body:
            simulate = body["simulate"]
            if self._backend.name != "mock":
                raise ValidationFailed("simulate is only accepted by the mock backend.")
            if not isinstance(simulate, dict) or set(simulate) - SIMULATION_KEYS or \
                    not all(isinstance(value, str) for value in simulate.values()):
                raise ValidationFailed(f"simulate takes string values for: {', '.join(sorted(SIMULATION_KEYS))}.")
            options["simulate"] = dict(simulate)
        if "ttlSeconds" in body:
            ttl = body["ttlSeconds"]
            if self._backend.name != "mock" or type(ttl) is not int or not 5 <= ttl <= 3600:
                raise ValidationFailed("ttlSeconds (5-3600) is only accepted by the mock backend.")
            options["ttlSeconds"] = ttl
        return options

    def _stale(self, updated_at: str | None, now: datetime) -> bool:
        if not updated_at:
            return True
        moment = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (now - moment).total_seconds() >= self._poll_after

    def _excerpt(self, run_id: int | None) -> str:
        try:
            return self._tracker.failure_excerpt(run_id)
        except LifecycleError:
            return ""


def _object(body: Any) -> dict[str, Any]:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ValidationFailed("The request body must be a JSON object.")
    return body


def _delivery_key(delivery_id: str) -> str:
    if _SAFE_KEY.fullmatch(delivery_id):
        return delivery_id
    return hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()


def _fingerprint(operation: Operation) -> tuple:
    step = operation.step
    return operation.current, step.status, tuple((run.status, run.conclusion) for run in step.runs)


def _info(operation: Operation, message: str) -> None:
    log.info("operationId=%s %s", operation.id, message)
