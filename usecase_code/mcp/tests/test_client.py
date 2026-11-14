from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest

from aifactory_mcp import client
from aifactory_mcp.client import ClientToolError, invoke, validate_http_url


@pytest.mark.parametrize("url", [
    "http://untrusted.example/mcp", "https://user:password@example.com/mcp",
    "https://example.com/mcp?access_token=secret", "file:///C:/anything",
])
def test_client_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_http_url(url)


def test_client_accepts_tls_and_literal_loopback():
    assert validate_http_url("https://mcp.example.com/mcp")
    assert validate_http_url("http://127.0.0.1:8899/mcp")


@pytest.mark.anyio
async def test_invoke_propagates_mcp_errors_without_retry():
    class Session:
        count = 0

        async def call_tool(self, name, args):
            self.count += 1
            return SimpleNamespace(isError=True, structuredContent={
                "ok": False, "error": {"code": "completion_unknown", "message": "Do not retry."}
            }, content=[])
    session = Session()
    with pytest.raises(ClientToolError, match="Do not retry"):
        await invoke(session, "factory_execute_operation", {"operation_id": "example"})
    assert session.count == 1


@pytest.mark.anyio
async def test_invoke_returns_structured_content():
    class Session:
        async def call_tool(self, name, args):
            return SimpleNamespace(isError=False, structuredContent={"ok": True}, content=[])
    assert await invoke(Session(), "factory_health", {}) == {"ok": True}


@pytest.fixture
def grouped_transports(monkeypatch):
    @asynccontextmanager
    async def transport(*args, **kwargs):
        try:
            yield (None, None, None) if args and isinstance(args[0], str) else (None, None)
        except Exception as exc:
            # Reproduce the SDK's task-group wrapper, including arbitrary caller errors.
            raise ExceptionGroup("transport task group", [exc]) from None

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, kind, exc, tb):
            if exc is not None:
                raise ExceptionGroup("session task group", [exc]) from None

        async def initialize(self):
            pass

    monkeypatch.setattr(client, "stdio_client", transport)
    monkeypatch.setattr(client, "streamable_http_client", transport)
    monkeypatch.setattr(client, "ClientSession", lambda *args, **kwargs: Session())


@pytest.mark.anyio
@pytest.mark.parametrize("http", [False, True])
async def test_connection_unwraps_tool_failure_without_losing_operation(grouped_transports, http):
    result = {"ok": False, "operation": {"id": "operation", "status": "uncertain"}}
    failure = ClientToolError("Do not retry.", result)
    connection = client.connect_http("http://127.0.0.1:8899/mcp", "test-token") if http else client.connect_stdio("python", [])
    with pytest.raises(ClientToolError) as exc:
        async with connection:
            raise failure
    assert exc.value is failure
    assert exc.value.result is result


@pytest.mark.anyio
async def test_connection_keeps_multiple_failures_and_programmer_errors(grouped_transports):
    failure = TypeError("programming defect")
    with pytest.raises(TypeError) as exc:
        async with client.connect_stdio("python", []):
            raise failure
    assert exc.value is failure
    failures = ExceptionGroup("two distinct failures", [ClientToolError("tool failed"), failure])
    with pytest.raises(ExceptionGroup) as grouped:
        async with client.connect_stdio("python", []):
            raise failures
    assert grouped.value is failures
