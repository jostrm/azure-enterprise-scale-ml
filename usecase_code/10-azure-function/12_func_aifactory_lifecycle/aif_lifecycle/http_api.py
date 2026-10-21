"""Framework-neutral HTTP handlers; function_app.py only adapts Azure Functions requests to these.

Changes answer 202 with Location and Retry-After (Asynchronous Request-Reply); reads answer 200. Errors are RFC 9457
problems with a stable code and a correlationId. The events route checks X-Hub-Signature-256 before anything else.
With a required app role, the lifecycle routes also need the role in the principal that App Service authentication
(Easy Auth) puts in X-MS-CLIENT-PRINCIPAL; health, events and runner results stay anonymous (HMAC-checked).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .domain.errors import InvalidSignature, LifecycleError, MissingRole, Unauthenticated, ValidationFailed
from .problem import PROBLEM_MEDIA_TYPE, problem_document
from .signatures import sign, verify

log = logging.getLogger("aif_lifecycle")
JSON_MEDIA_TYPE = "application/json; charset=utf-8"


@dataclass(frozen=True)
class ApiRequest:
    method: str
    path: str
    route_params: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


@dataclass(frozen=True)
class ApiResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class LifecycleHttpApi:
    def __init__(self, service, *, event_secrets: list[bytes], base_path: str = "/api", retry_after_seconds: int = 5,
                 enqueue: Callable[[dict[str, Any]], None] | None = None, required_role: str | None = None):
        self._service = service
        self._secrets = [secret for secret in event_secrets if secret]
        self._base = base_path.rstrip("/")
        self._retry_after = str(retry_after_seconds)
        self._enqueue = enqueue
        self._role = required_role

    # ----- routes -----

    def health(self, request: ApiRequest) -> ApiResponse:
        return self._handle(request, lambda: (200, self._service.health(), {}))

    def prepare(self, request: ApiRequest) -> ApiResponse:
        def run():
            operation = self._service.prepare(request.route_params.get("scenario", ""), _json(request))
            return 202, operation.to_public(), self._accepted(operation.id)
        return self._handle(request, run, protected=True)

    def get_operation(self, request: ApiRequest) -> ApiResponse:
        return self._handle(request, lambda: (200, self._service.get(request.route_params.get("operation_id", "")).to_public(), {}),
                            protected=True)

    def list_operations(self, request: ApiRequest) -> ApiResponse:
        def run():
            summaries = [{key: item.to_public()[key] for key in ("operationId", "scenario", "target", "status",
                                                                 "currentStep", "createdAt", "updatedAt")}
                         for item in self._service.list()]
            return 200, {"operations": summaries}, {}
        return self._handle(request, run, protected=True)

    def confirm(self, request: ApiRequest) -> ApiResponse:
        def run():
            operation = self._service.confirm(request.route_params.get("operation_id", ""), _json(request))
            return 202, operation.to_public(), self._accepted(operation.id)
        return self._handle(request, run, protected=True)

    def github_events(self, request: ApiRequest) -> ApiResponse:
        def run():
            if not verify(self._secrets, request.body, request.header("x-hub-signature-256")):
                raise InvalidSignature("X-Hub-Signature-256 does not match the configured event secret.")
            payload = _json(request)
            event, delivery = request.header("x-github-event") or "", request.header("x-github-delivery")
            source = "relay" if request.header("x-aif-relay") else "webhook"
            if self._enqueue is None:
                result = self._service.handle_event(event, delivery, payload, source=source)
            else:
                result = self._service.receive_event(event, delivery, payload)
                if result.get("result") == "accepted":
                    self._enqueue(self._signed({**result["message"], "source": source}))
                    self._service.record_delivery(result["message"]["delivery"])
                    result = {"result": "queued"}
            return (202 if result.get("result") in ("applied", "queued") else 200), result, {}
        return self._handle(request, run)

    def runner_results(self, request: ApiRequest) -> ApiResponse:
        """A runner's result (aif-ops.yml), signed with the event secret like the relay's events."""
        def run():
            if not verify(self._secrets, request.body, request.header("x-hub-signature-256")):
                raise InvalidSignature("X-Hub-Signature-256 does not match the configured event secret.")
            result = self._service.apply_runner_result(_json(request))
            return (202 if result.get("result") == "applied" else 200), result, {}
        return self._handle(request, run)

    def refresh_catalog(self, request: ApiRequest) -> ApiResponse:
        return self._handle(request, lambda: (202, self._service.refresh_catalog(), {}), protected=True)

    def process_queued(self, message: dict[str, Any]) -> dict[str, Any]:
        """Apply a queued event. Queue access is not trust: only messages this Function signed are applied."""
        unsigned = {key: value for key, value in message.items() if key != "signature"}
        if not verify(self._secrets, _canonical(unsigned), message.get("signature")):
            raise InvalidSignature("The queued event was not signed by this Function.")
        source = unsigned.pop("source", "relay")
        return self._service.apply_event(unsigned, source=source)

    def _signed(self, message: dict[str, Any]) -> dict[str, Any]:
        return {**message, "signature": sign(self._secrets[0], _canonical(message))}

    # ----- helpers -----

    def _accepted(self, operation_id: str) -> dict[str, str]:
        return {"Location": f"{self._base}/v1/operations/{operation_id}", "Retry-After": self._retry_after}

    def _authorize(self, request: ApiRequest) -> None:
        """The app role from the principal App Service authentication validated (never from the caller's own claims)."""
        if not self._role:
            return
        try:
            document = json.loads(base64.b64decode(request.header("x-ms-client-principal") or "", validate=True))
            role_type = document.get("role_typ") or "roles"
            roles = {claim.get("val") for claim in document.get("claims") or []
                     if claim.get("typ") in (role_type, "roles")}
        except (ValueError, binascii.Error, AttributeError, TypeError):
            raise Unauthenticated("Call with a Microsoft Entra ID access token for this Function's app.") from None
        if self._role not in roles:
            raise MissingRole(f"The caller needs the app role {self._role}.")
        log.info("caller %s on %s %s", request.header("x-ms-client-principal-name") or "unknown", request.method,
                 request.path)

    def _handle(self, request: ApiRequest, run: Callable[[], tuple[int, Any, dict[str, str]]], *,
                protected: bool = False) -> ApiResponse:
        correlation = request.header("x-correlation-id") or str(uuid.uuid4())
        try:
            if protected:
                self._authorize(request)
            status, body, headers = run()
            return _response(status, JSON_MEDIA_TYPE, body, {**headers, "x-correlation-id": correlation})
        except LifecycleError as error:
            log.info("correlationId=%s %s %s -> %s %s", correlation, request.method, request.path, error.status, error.code)
            document = problem_document(error, correlation_id=correlation, instance=request.path)
        except Exception:  # noqa: BLE001 - never leak exception text or stack traces
            log.exception("correlationId=%s unexpected error on %s %s", correlation, request.method, request.path)
            document = problem_document(RuntimeError(), correlation_id=correlation, instance=request.path)
        return _response(document["status"], PROBLEM_MEDIA_TYPE, document, {"x-correlation-id": correlation})


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _json(request: ApiRequest) -> Any:
    if not request.body:
        return {}
    try:
        return json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailed("The request body is not valid JSON.", code="invalid-json") from None


def _response(status: int, media_type: str, body: Any, headers: dict[str, str]) -> ApiResponse:
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return ApiResponse(status=status, headers={"Content-Type": media_type, **headers}, body=data)
