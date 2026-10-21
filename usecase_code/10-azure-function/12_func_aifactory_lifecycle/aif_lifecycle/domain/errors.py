"""Lifecycle errors with stable codes; the HTTP layer renders them as RFC 9457 problems."""

from __future__ import annotations

from typing import Any


class LifecycleError(Exception):
    """Base error. `code` is the stable machine-readable identifier clients branch on."""

    status = 500
    code = "internal-error"
    title = "Internal error"

    def __init__(self, detail: str, *, code: str | None = None, extra: dict[str, Any] | None = None):
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        self.extra = dict(extra or {})


class ValidationFailed(LifecycleError):
    status, code, title = 400, "validation-failed", "The request is not valid"


class InvalidId(ValidationFailed):
    code, title = "invalid-id", "The ID does not follow the AI Factory naming"


class InvalidSignature(LifecycleError):
    status, code, title = 401, "invalid-signature", "The event signature is not valid"


class ProtectedTarget(LifecycleError):
    status, code, title = 403, "protected-target", "The target is protected"


class UnknownId(LifecycleError):
    status, code, title = 404, "unknown-id", "The ID is not in the factory catalog"


class OperationNotFound(UnknownId):
    code, title = "operation-not-found", "The operation was not found"


class Conflict(LifecycleError):
    status, code, title = 409, "conflict", "The request conflicts with the current state"


class AlreadyExists(Conflict):
    code, title = "already-exists", "The target already exists"


class InProgress(Conflict):
    code, title = "in-progress", "Another operation is in progress for this target"


class RevisionMismatch(Conflict):
    code, title = "revision-mismatch", "The catalog changed since the review"


class InvalidState(Conflict):
    code, title = "invalid-state", "The operation is not in a state that allows this"


class ScopeNotSupported(Conflict):
    code, title = "scope-not-supported", "The Factory API cannot limit this operation to the requested scope"


class ReviewBlocked(Conflict):
    code, title = "review-blocked", "The review reported blockers"


class ConfirmationExpired(LifecycleError):
    status, code, title = 410, "confirmation-expired", "The review expired; prepare again"


class UpstreamError(LifecycleError):
    status, code, title = 502, "upstream-error", "The Factory API or GitHub returned an error"


class UpstreamUnavailable(LifecycleError):
    status, code, title = 503, "upstream-unavailable", "The Factory API or GitHub is unavailable"


class UpstreamTimeout(LifecycleError):
    status, code, title = 504, "upstream-timeout", "The Factory API or GitHub did not answer in time"


class ConfigurationInvalid(LifecycleError):
    status, code, title = 503, "configuration-invalid", "The Function's app settings are not valid"
