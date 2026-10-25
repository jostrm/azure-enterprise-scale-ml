"""Map Factory API HTTP statuses to lifecycle errors (shared by the REST and SDK adapters)."""

from __future__ import annotations

from ..domain.errors import (Conflict, ConfirmationExpired, LifecycleError, RevisionMismatch, UnknownId,
                             UpstreamError, ValidationFailed)


class UpstreamRefused(LifecycleError):
    """The Factory API refused the call before doing anything (auth or loopback rule): a definite rejection."""

    status, code, title = 502, "upstream-refused", "The Factory API refused the call"


class UpstreamTooOld(LifecycleError):
    """The Factory API has no route for the operation (an older version): nothing was done, a definite rejection."""

    status, code, title = 502, "factory-api-too-old", "The Factory API is too old for this operation"


def error_for_status(status: int, detail: str) -> LifecycleError:
    error = _error_for_status(status, detail)
    error.upstream_status = status  # lets an operation tell a missing route from its own 404
    return error


def _error_for_status(status: int, detail: str) -> LifecycleError:
    text = detail or f"The Factory API answered HTTP {status}."
    if status in (400, 422):
        return ValidationFailed(text, code="upstream-validation-failed")
    if status in (401, 403):
        return UpstreamRefused(text)
    if status == 404:
        return UnknownId(text)
    if status == 409:
        return RevisionMismatch(text) if "revision" in text.lower() else Conflict(text)
    if status == 410:
        return ConfirmationExpired(text)
    return UpstreamError(text)
