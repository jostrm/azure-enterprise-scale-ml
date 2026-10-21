"""Wire contract between the Function and the runner entry point (aif-ops.yml on the Factory API host).

The Function dispatches aif-ops.yml with one request in the `request` input: base64url JSON, a dot, and an
HMAC-SHA256 of that JSON with the event secret. The request expires (`exp`) when the Function stops waiting for it, so
a re-run or a copied request can't act later. The runner checks both, calls the Factory API through the REST or SDK
adapter and POSTs one signed result to the Function's /api/v1/runner/results. Both hosts import this module, so the
contract lives in one place. Requests travel as workflow inputs, which anyone with read access to the ops repository
can see: they carry reviews and IDs, never secrets.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from ..domain.errors import LifecycleError, UpstreamError, UpstreamTimeout, UpstreamUnavailable, ValidationFailed
from ..domain.operation import Preview, StepKind
from ..domain.scenarios import Scenario
from ..ports import ConfirmResult, StepRequest

VERSION = 1
ACTIONS = ("catalog", "prepare", "confirm", "status")
OUTCOMES = ("ok", "error", "uncertain")
BACKENDS = ("rest", "sdk")
CATALOG_OPERATION = "00000000-0000-4000-8000-000000000000"  # run-name marker of catalog refreshes
MAX_REQUEST_CHARS = 60000  # GitHub caps a workflow_dispatch payload's inputs at 65,535 characters


@dataclass(frozen=True)
class RunnerRequest:
    action: str
    nonce: str
    backend: str
    operation_id: str | None
    step: int | None
    request: StepRequest | None = None
    preview: Preview | None = None
    phrase: str | None = None
    job: dict[str, Any] | None = None
    expires: int = 0  # epoch seconds; set from the signed payload


@dataclass(frozen=True)
class RunnerResult:
    action: str
    nonce: str
    operation_id: str | None
    step: int | None
    outcome: str
    run_id: str | None = None
    preview: Preview | None = None
    confirm: ConfirmResult | None = None
    status: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    catalog: dict[str, Any] | None = None


def classify_confirm_failure(error: BaseException) -> str:
    """'error' when the Factory API refused the confirmation before acting; otherwise 'uncertain' (never retried)."""
    if isinstance(error, (UpstreamTimeout, UpstreamUnavailable, UpstreamError)):
        return "uncertain"
    return "error" if isinstance(error, LifecycleError) else "uncertain"


def encode_request(request: RunnerRequest, secret: bytes, *, expires: int) -> str:
    if request.action not in ACTIONS or request.backend not in BACKENDS:
        raise ValidationFailed(f"A runner request needs an action in {ACTIONS} and a backend in {BACKENDS}.")
    if not secret:
        raise ValidationFailed("Runner requests are signed with the event secret; configure AIF_EVENT_SECRET_NAME.")
    payload: dict[str, Any] = {"v": VERSION, "action": request.action, "nonce": request.nonce,
                               "backend": request.backend, "operationId": request.operation_id, "step": request.step,
                               "exp": int(expires)}
    if request.request is not None:
        step = request.request
        payload["request"] = {"operation_id": step.operation_id, "scenario": step.scenario.value,
                              "step_index": step.step_index, "step_name": step.step_name, "kind": step.kind.value,
                              "target": step.target, "resolved": step.resolved, "settings": step.settings,
                              "options": step.options}
    if request.preview is not None:
        payload["preview"] = asdict(request.preview)
    if request.phrase is not None:
        payload["phrase"] = request.phrase
    if request.job is not None:
        payload["job"] = request.job
    body = base64.urlsafe_b64encode(_canonical(payload)).decode("ascii")
    text = f"{body}.{_seal(secret, body)}"
    if len(text) > MAX_REQUEST_CHARS:
        raise ValidationFailed("The runner request is too large for a workflow input; send fewer settings.")
    return text


def decode_request(text: str, secrets: Iterable[bytes], *, now: float | None) -> RunnerRequest:
    """Check the Function's signature (any configured secret, constant time) and, unless now is None, the expiry."""
    body, _, seal = (text or "").partition(".")
    if not body or not any(secret and hmac.compare_digest(_seal(secret, body), seal) for secret in secrets):
        raise ValidationFailed("The runner request is not signed by the Function.", code="invalid-runner-request")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        if payload.get("v") != VERSION or payload.get("action") not in ACTIONS or payload.get("backend") not in BACKENDS:
            raise ValueError("unsupported request")
        expires = int(payload["exp"])
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error, UnicodeEncodeError):
        raise ValidationFailed("The runner request is not valid.", code="invalid-runner-request") from None
    if now is not None and now > expires:
        raise ValidationFailed("The runner request expired; the Function no longer waits for it.",
                               code="runner-request-expired")
    try:
        step = payload.get("request")
        return RunnerRequest(
            action=payload["action"], nonce=str(payload["nonce"]), backend=payload["backend"],
            operation_id=payload.get("operationId"), step=payload.get("step"),
            request=None if step is None else StepRequest(
                operation_id=step["operation_id"], scenario=Scenario(step["scenario"]), step_index=int(step["step_index"]),
                step_name=step["step_name"], kind=StepKind(step["kind"]), target=step["target"],
                resolved=dict(step["resolved"]), settings=dict(step["settings"]), options=dict(step["options"])),
            preview=_preview(payload.get("preview")), phrase=payload.get("phrase"), job=payload.get("job"),
            expires=expires)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValidationFailed("The runner request is not valid.", code="invalid-runner-request") from None


def result_body(request: RunnerRequest, *, outcome: str, run_id: str | int | None = None,
                preview: Preview | None = None, confirm: ConfirmResult | dict[str, Any] | None = None,
                status: dict[str, Any] | None = None, error: dict[str, Any] | None = None,
                catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    body: dict[str, Any] = {"v": VERSION, "resultId": f"{request.nonce}-{request.action}", "action": request.action,
                            "nonce": request.nonce, "operationId": request.operation_id, "step": request.step,
                            "outcome": outcome, "runId": None if run_id is None else str(run_id)}
    if preview is not None:
        body["preview"] = asdict(preview)
    if confirm is not None:
        body["confirm"] = confirm if isinstance(confirm, dict) else {
            "job": confirm.job, "targets": confirm.targets, "resolvedUpdates": confirm.resolved_updates}
    for key, value in (("status", status), ("error", error), ("catalog", catalog)):
        if value is not None:
            body[key] = value
    return body


def parse_result(body: Any) -> RunnerResult:
    try:
        if body.get("v") != VERSION or body.get("action") not in ACTIONS or body.get("outcome") not in OUTCOMES:
            raise ValueError("unsupported result")
        confirm = body.get("confirm")
        return RunnerResult(
            action=body["action"], nonce=str(body["nonce"]), operation_id=body.get("operationId"),
            step=body.get("step"), outcome=body["outcome"], run_id=body.get("runId"),
            preview=_preview(body.get("preview")),
            confirm=None if confirm is None else ConfirmResult(job=dict(confirm.get("job") or {}),
                                                               targets=[str(t) for t in confirm.get("targets") or []],
                                                               resolved_updates=dict(confirm.get("resolvedUpdates") or {})),
            status=body.get("status"), error=body.get("error"), catalog=body.get("catalog"))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValidationFailed("The body is not a runner result.", code="invalid-runner-result") from None


def _preview(value: Any) -> Preview | None:
    return None if value is None else Preview(**value)


def _seal(secret: bytes, body: str) -> str:
    digest = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
