"""RFC 9457 problem details. Responses never carry stack traces, exception text or secrets."""

from __future__ import annotations

from typing import Any

from .domain.errors import LifecycleError

PROBLEM_MEDIA_TYPE = "application/problem+json"
_CONTRACT_FIELDS = {"type", "title", "status", "detail", "code", "correlationId", "instance"}


def problem_document(error: BaseException, *, correlation_id: str, instance: str) -> dict[str, Any]:
    if not isinstance(error, LifecycleError):
        error = LifecycleError("The request could not be completed. Use the correlationId when you report it.")
    document = {key: value for key, value in error.extra.items() if key not in _CONTRACT_FIELDS}
    document.update({
        "type": f"urn:aifactory:lifecycle:problem:{error.code}",
        "title": error.title,
        "status": error.status,
        "detail": error.detail,
        "code": error.code,
        "correlationId": correlation_id,
        "instance": instance,
    })
    return document
