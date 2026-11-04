"""SDK exceptions with CLI exit-code mappings."""

from __future__ import annotations


class APIError(Exception):
    exit_code = 1

    def __init__(self, message: str, *, status: int | None = None, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details


class ConfigError(APIError):
    exit_code = 2


class AuthError(APIError):
    exit_code = 6


class RedirectError(APIError):
    exit_code = 2


class RequestTimeout(APIError):
    exit_code = 4


class BlockedError(APIError):
    exit_code = 3


class FailureError(APIError):
    exit_code = 5

