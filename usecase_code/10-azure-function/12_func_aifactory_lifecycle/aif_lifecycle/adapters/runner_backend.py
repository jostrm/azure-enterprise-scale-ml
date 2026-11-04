"""AIF_EXECUTOR=github-runner: the Factory API answers loopback clients only, so the Function hands every call to
aif-ops.yml on the management runner (the API host) and waits for its signed result (Asynchronous Request-Reply).

`name` is the adapter the runner uses (rest or sdk). Planning reads the catalog snapshot that every runner result
refreshes; refresh_catalog asks the runner for a new one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from ..application.runner_protocol import CATALOG_OPERATION, RunnerRequest, encode_request
from ..domain.errors import UpstreamUnavailable
from ..domain.operation import Operation, Preview, iso
from ..ports import Catalog, ConfirmResult, Deferred, GitHubPort, StateStore, StepRequest
from .factory_api import refuse_deletes

CATALOG = "catalog"


class RunnerBackend:
    def __init__(self, github: GitHubPort, store: StateStore, clock, *, workflow: str, ref: str, backend: str,
                 secret: bytes, request_ttl_seconds: int, nonces: Callable[[], str] | None = None,
                 refresh_after_seconds: int = 300, allow_deletes: bool = False):
        self.name = backend
        self.delete_mode = "allow" if allow_deletes else "refuse"
        self._github = github
        self._store = store
        self._clock = clock
        self._workflow = workflow
        self._ref = ref
        self._secret = secret
        self._ttl = request_ttl_seconds
        self._nonces = nonces or (lambda: uuid.uuid4().hex)
        self._refresh_after = refresh_after_seconds

    # ----- FactoryBackend port -----

    def catalog(self) -> Catalog:
        return Catalog.from_api(self.catalog_payload())

    def catalog_payload(self) -> dict[str, Any]:
        """The latest snapshot the runner sent, as the Factory API answered it."""
        found = self._store.get(CATALOG, "snapshot")
        if found is None:
            self.refresh_catalog(force=False)
            raise UpstreamUnavailable("The catalog snapshot is being read on the Factory API host; retry in a minute.",
                                      code="catalog-pending")
        return found[0]["payload"]

    def prepare(self, request: StepRequest) -> Preview:
        refuse_deletes(self.delete_mode, request)  # before the dispatch: a refused delete never leaves the Function
        raise Deferred("prepare", self._dispatch("prepare", request.operation_id, request.step_index, request=request))

    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult:
        refuse_deletes(self.delete_mode, request)
        raise Deferred("confirm", self._dispatch("confirm", request.operation_id, request.step_index, request=request,
                                                 preview=preview, phrase=phrase))

    def finalize(self, request: StepRequest, succeeded: bool) -> None:
        """The Factory API owns the catalog; nothing to do here."""

    # ----- runner-only calls -----

    def status(self, operation: Operation) -> str:
        return self._dispatch("status", operation.id, operation.current, job=dict(operation.step.job))

    def refresh_catalog(self, *, force: bool = True) -> str | None:
        """Dispatch a catalog read unless one went out less than refresh_after_seconds ago (and force is off)."""
        now = self._clock.now()
        found = self._store.get(CATALOG, "refresh")
        if found and not force and _age(found[0]["since"], now) < self._refresh_after:
            return None
        nonce = self._dispatch("catalog", CATALOG_OPERATION, 0)
        self._store.upsert(CATALOG, "refresh", {"nonce": nonce, "since": iso(now)})
        return nonce

    def accept_catalog(self, payload: dict[str, Any]) -> None:
        Catalog.from_api(payload)  # a snapshot that does not parse never replaces a good one
        self._store.upsert(CATALOG, "snapshot", {"payload": payload, "at": iso(self._clock.now())})

    # ----- transport -----

    def _dispatch(self, action: str, operation_id: str, step: int, **parts: Any) -> str:
        """Dispatch aif-ops.yml with a request signed for this call only: it expires when the Function stops waiting,
        and the nonce in the run name ties the run (and its events) to this hand-off."""
        nonce = self._nonces()
        expires = int(self._clock.now().timestamp()) + self._ttl
        request = encode_request(RunnerRequest(action=action, nonce=nonce, backend=self.name,
                                               operation_id=operation_id, step=step, **parts), self._secret,
                                 expires=expires)
        self._github.dispatch(self._workflow, self._ref, {"operation_id": operation_id, "step": str(step),
                                                          "action": action, "nonce": nonce, "request": request})
        return nonce


def _age(stamp: str, now: datetime) -> float:
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (now - moment).total_seconds()
