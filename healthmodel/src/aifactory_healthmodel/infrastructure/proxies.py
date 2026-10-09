"""Protection proxies: guarantee read-only behaviour (plan, MCP tools) independent of the caller."""
from __future__ import annotations

from .resilience import is_read_only_call


class ReadOnlyViolation(RuntimeError):
    pass


class ReadOnlyTransport:
    """Forwards GET and read-only POST actions; refuses every write."""

    def __init__(self, inner, reason: str = "this operation is read-only"):
        self.inner = inner
        self.reason = reason

    def request(self, method: str, url: str, body: dict | None = None):
        if not is_read_only_call(method, url):
            raise ReadOnlyViolation(f"Blocked {method.upper()} request: {self.reason}.")
        return self.inner.request(method, url, body)


class ReadOnlyDeployer:
    def __init__(self, inner, reason: str = "plan never deploys"):
        self.inner = inner
        self.reason = reason

    def what_if(self, resource_group, template, parameters):
        return self.inner.what_if(resource_group, template, parameters)

    def deploy(self, *args, **kwargs):
        raise ReadOnlyViolation(f"Blocked deployment: {self.reason}.")


class ReadOnlyProviders:
    def __init__(self, inner, reason: str = "plan never registers resource providers"):
        self.inner = inner
        self.reason = reason

    def provider(self) -> dict:
        return self.inner.provider()

    def register_provider(self, *args, **kwargs):
        raise ReadOnlyViolation(f"Blocked provider registration: {self.reason}.")
