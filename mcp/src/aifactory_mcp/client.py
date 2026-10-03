"""Small MCP client helpers; a failed write is never retried."""

from __future__ import annotations

import ipaddress
import json
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


class ClientToolError(RuntimeError):
    def __init__(self, message: str, result: dict | None = None):
        super().__init__(message)
        self.result = result


def validate_http_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTP endpoint without credentials, query or fragment.")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("HTTPS is required except for a local loopback endpoint.")
    return url.rstrip("/")


@contextmanager
def _normalize_connection_errors():
    try:
        yield
    except BaseExceptionGroup as error:
        # SDK task groups wrap caller errors on exit. Strip single-error wrappers
        # without dropping concurrent failures, cancellation, or the tool's result.
        while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
            error = error.exceptions[0]
        raise error from None


@asynccontextmanager
async def connect_stdio(command: str, args: list[str], env: dict[str, str] | None = None):
    parameters = StdioServerParameters(command=command, args=args, env=env)
    with _normalize_connection_errors():
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
                await session.initialize()
                yield session


@asynccontextmanager
async def connect_http(url: str, token: str):
    url = validate_http_url(url)
    if not token or any(char.isspace() for char in token):
        raise ValueError("A bearer access token is required.")
    with _normalize_connection_errors():
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(180, connect=15), follow_redirects=False, trust_env=False,
        ) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
                    await session.initialize()
                    yield session


async def invoke(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    data = result.structuredContent
    if data is None:
        text = [block.text for block in result.content if block.type == "text"]
        if len(text) == 1:
            try:
                data = json.loads(text[0])
            except json.JSONDecodeError:
                data = None
    if result.isError:
        error = data.get("error") if isinstance(data, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise ClientToolError(message or "The MCP tool failed; do not retry writes.", data)
    if not isinstance(data, dict):
        raise ClientToolError("The MCP tool did not return a structured object.")
    if data.get("ok") is False or ("error" in data and data["error"] is not None):
        raise ClientToolError("The backend did not confirm success; inspect its result.", data)
    return data
