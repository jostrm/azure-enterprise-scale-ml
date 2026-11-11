"""Read-only question-tool invocation on a published Fabric Data Agent's MCP endpoint."""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

import anyio
import httpx
from azure.core.exceptions import AzureError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

from .contracts import MAX_QUESTION, SalesError


FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
REQUEST_TIMEOUT = 120
MAX_RESULT_BYTES = 256 * 1024
MAX_DISCOVERY_PAGES = 8
_LOGGER = logging.getLogger(__name__)
_EXPECTED_ERRORS = (
    AzureError, httpx.HTTPError, McpError, TimeoutError, OSError,
    anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream,
)


def _http_client(*, headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(
        headers=headers, timeout=timeout if timeout is not None else httpx.Timeout(REQUEST_TIMEOUT),
        auth=auth, follow_redirects=False,
    )


def _leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in _leaves(child)]
    return [error]


def _failure():
    return SalesError(
        "fabric_request_failed",
        "The published Fabric Data Agent request failed. Verify the user has access; "
        "interactive claims challenges and non-user identities are unsupported.",
        502,
    )


def _validate_schema(tool, settings):
    schema = tool.inputSchema
    properties = schema.get("properties", {})
    if (
        schema.get("type") != "object"
        or not isinstance(properties, dict)
        or len(properties) != 1
        or (settings.mcp_tool_name and tool.name != settings.mcp_tool_name)
        or not tool.name
    ):
        raise SalesError("fabric_tool_rejected", "Expected exactly one question-only Fabric tool.", 503)
    argument, field = next(iter(properties.items()))
    if (
        not isinstance(field, dict)
        or field.get("type") != "string"
        or schema.get("required") != [argument]
        or (settings.mcp_question_argument and argument != settings.mcp_question_argument)
    ):
        raise SalesError("fabric_tool_rejected", "The Fabric question argument schema is unsupported.", 503)

    # Accept scalar constraints, never remote schema resolution or hidden argument defaults.
    root_keys = {"type", "properties", "required", "additionalProperties", "title", "description",
                 "$schema"}
    field_keys = {"type", "title", "description", "minLength", "maxLength", "pattern", "enum", "const"}
    annotations = tool.annotations.model_dump(exclude_unset=True) if tool.annotations else {}
    if (
        set(schema) - root_keys
        or set(field) - field_keys
        or schema.get("additionalProperties", False) not in (False, True)
        or annotations.get("readOnlyHint") is False
        or annotations.get("destructiveHint") is True
    ):
        raise SalesError("fabric_tool_rejected", "The Fabric tool contains unreviewed schema or write hints.", 503)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise SalesError("fabric_tool_rejected", "The Fabric question schema is invalid.", 503) from None
    return {
        "name": tool.name, "question_argument": argument, "input_schema": schema,
        "endpoint": settings.fabric_url,
    }


class FabricDataAgent:
    def __init__(self, settings, credential):
        self.settings = settings
        self.credential = credential

    @asynccontextmanager
    async def _session(self):
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                token = await self.credential.get_token(FABRIC_SCOPE)
                if token.expires_on <= time.time() + REQUEST_TIMEOUT + 30:
                    _LOGGER.warning(
                        "The Fabric user token is near expiry; service authorization will decide "
                        "whether the bounded request can proceed."
                    )
                async with streamablehttp_client(
                    self.settings.fabric_url,
                    headers={"Authorization": "Bearer " + token.token},
                    timeout=REQUEST_TIMEOUT,
                    sse_read_timeout=REQUEST_TIMEOUT,
                    httpx_client_factory=_http_client,
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        yield session
        except _EXPECTED_ERRORS:
            raise _failure() from None
        except BaseExceptionGroup as error:
            leaves = _leaves(error)
            if all(isinstance(leaf, (*_EXPECTED_ERRORS, SalesError)) for leaf in leaves):
                existing = next((leaf for leaf in leaves if isinstance(leaf, SalesError)), None)
                raise existing if existing is not None else _failure() from None
            raise

    async def _discover(self, session):
        tools = []
        seen_cursors = set()
        cursor = None
        for _ in range(MAX_DISCOVERY_PAGES):
            result = await session.list_tools(**({"cursor": cursor} if cursor else {}))
            tools.extend(result.tools)
            if len(tools) > 1:
                raise SalesError(
                    "fabric_tool_rejected",
                    "The configured endpoint exposes extra tools, not a single published question tool.",
                    503,
                )
            cursor = result.nextCursor
            if not cursor:
                if len(tools) != 1:
                    raise SalesError("fabric_tool_rejected", "The Fabric question tool is unavailable.", 503)
                return _validate_schema(tools[0], self.settings)
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        raise SalesError("fabric_tool_rejected", "Fabric tool discovery exceeded its bounded page limit.", 503)

    async def discover(self):
        async with self._session() as session:
            return await self._discover(session)

    async def query(self, question):
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
            raise SalesError("invalid_question", "Provide a nonempty question within the configured limit.", 400)
        async with self._session() as session:
            discovery = await self._discover(session)
            arguments = {discovery["question_argument"]: question}
            try:
                Draft202012Validator(discovery["input_schema"]).validate(arguments)
            except ValidationError:
                raise SalesError(
                    "invalid_question", "The question does not satisfy the published tool's schema.", 400
                ) from None
            result = await session.call_tool(discovery["name"], arguments=arguments)
            if result.isError:
                raise SalesError("fabric_tool_failed", "The Fabric question tool reported a failure.", 502)
            content = [block.model_dump(mode="json") for block in result.content]
            structured = result.structuredContent
            usable = any(
                (block.get("type") == "text" and bool(block.get("text", "").strip()))
                or (block.get("type") != "text" and bool(block))
                for block in content
            )
            if not usable and not structured:
                raise SalesError("fabric_empty_result", "Fabric returned no usable question result.", 502)
            output = {
                "tool": discovery["name"], "endpoint": discovery["endpoint"],
                "content": content, "structured_content": structured,
            }
            if len(json.dumps(output, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
                raise SalesError(
                    "fabric_result_too_large", "Fabric returned too much data; narrow the question.", 502
                )
            return output
