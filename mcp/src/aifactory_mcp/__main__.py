from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import anyio
import httpx
from mcp import McpError

from .backend import BackendError
from .client import ClientToolError, connect_http, connect_stdio, invoke
from .runtime import load_runtime
from .readiness import ApiReadinessProbe
from .server import create_http_app, create_server, run_stdio


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Governed Enterprise Scale AI Factory MCP")
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("serve", "tools", "call", "approve"):
        sub = commands.add_parser(command)
        sub.add_argument("--config", required=True, help="Existing agent settings JSON.")
        sub.add_argument("--repository-root", help="Purple checkout, required for an external wheel installation.")
        sub.add_argument("--scope", required=True, help="One exact configured scope key.")
        sub.add_argument("--object-id", help="Explicit trusted local operator identity; never used for HTTP.")
        if command != "approve":
            sub.add_argument("--graph-only", action="store_true",
                             help="Expose only the five corpus read tools; requires explicit graph.read, not factory.read.")
        if command == "serve":
            sub.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
            sub.add_argument("--host", default="127.0.0.1", help="Bind address; use a TLS proxy for remote access.")
            sub.add_argument("--port", type=int, default=8899)
            sub.add_argument("--resource-url", help="External HTTPS resource URL ending in /mcp.")
            sub.add_argument("--application-auth", help="Explicit read-only Foundry application identity policy JSON.")
        elif command in ("tools", "call"):
            sub.add_argument("--url", help="Connect to an existing authenticated HTTP MCP endpoint.")
            sub.add_argument("--token-env", default="AIFACTORY_MCP_TOKEN",
                             help="Environment variable holding the MCP access token.")
            if command == "call":
                sub.add_argument("tool")
                sub.add_argument("--arguments", default="{}", help="Tool arguments as a JSON object; never put secrets here.")
        else:
            sub.add_argument("--operation-id", required=True)
    return result


def approve_interactively(backend, operation_id: str, *, input_stream=None, output_stream=None) -> dict:
    input_stream = input_stream if input_stream is not None else sys.stdin
    output_stream = output_stream if output_stream is not None else sys.stdout
    if not input_stream.isatty():
        raise ValueError("Approval requires an interactive human terminal; piped approvals are not accepted.")
    result = backend.call_tool("factory_operation", {"operation_id": operation_id})
    record = result["operation"]
    if result.get("ok") is not True or record.get("status") != "pending":
        raise ValueError("Only a pending plan can be approved.")
    output_stream.write(json.dumps(record, indent=2) + "\n")
    output_stream.write("Review the complete plan above. Type its exact plan_hash to approve, or Enter to stop:\n")
    output_stream.flush()
    reviewed_hash = input_stream.readline().strip()
    if not reviewed_hash or reviewed_hash != record["plan_hash"]:
        raise ValueError("Approval did not match the reviewed plan hash; nothing was approved.")
    phrase = (record.get("preview") or {}).get("confirmation_phrase")
    confirmed_phrase = None
    if phrase:
        output_stream.write("Type the exact deletion confirmation phrase shown in the plan:\n")
        output_stream.flush()
        confirmed_phrase = input_stream.readline().strip()
        if confirmed_phrase != phrase:
            raise ValueError("Confirmation did not match the deletion phrase; nothing was approved.")
    return backend.approve(operation_id, reviewed_hash, confirmed_phrase)


def _child_arguments(options) -> list[str]:
    if not options.object_id:
        raise ValueError("An explicit --object-id is required for a local stdio client.")
    args = [
        "-m", "aifactory_mcp", "serve", "--config", str(Path(options.config).resolve()),
        "--scope", options.scope, "--object-id", options.object_id,
    ]
    if options.repository_root:
        args.extend(["--repository-root", str(Path(options.repository_root).resolve())])
    if options.graph_only:
        args.append("--graph-only")
    return args


async def _client(options) -> dict:
    if options.url:
        if options.graph_only:
            raise ValueError("--graph-only is a server policy; remote clients cannot override server tools.")
        if options.object_id:
            raise ValueError("HTTP uses the verified access token identity, not --object-id.")
        connection = connect_http(options.url, os.environ.get(options.token_env, ""))
    else:
        connection = connect_stdio(sys.executable, _child_arguments(options), env=dict(os.environ))
    async with connection as session:
        if options.command == "tools":
            result = await session.list_tools()
            return result.model_dump(mode="json", exclude_none=True)
        arguments = json.loads(options.arguments)
        if not isinstance(arguments, dict):
            raise ValueError("--arguments must be a JSON object.")
        return await invoke(session, options.tool, arguments)


def main(argv=None) -> int:
    options = parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(name)s: %(levelname)s: %(message)s")
    try:
        if options.command in ("tools", "call"):
            result = asyncio.run(_client(options))
        else:
            application_auth = getattr(options, "application_auth", None)
            if application_auth and options.transport != "streamable-http":
                raise ValueError("--application-auth is only supported by the authenticated HTTP server.")
            runtime = load_runtime(
                options.config, options.repository_root, application_auth=application_auth,
                graph_only=getattr(options, "graph_only", False),
            )
            if options.command == "approve":
                if not options.object_id:
                    raise ValueError("An explicit --object-id is required for local approval.")
                backend = runtime.backend(runtime.local_principal(options.object_id), options.scope)
                result = approve_interactively(backend, options.operation_id)
            elif options.transport == "stdio":
                server = create_server(runtime, options.scope, object_id=options.object_id)
                asyncio.run(run_stdio(server))
                return 0
            else:
                if options.object_id:
                    raise ValueError("A network server must not use --object-id.")
                if not options.resource_url:
                    raise ValueError("--resource-url is required for authenticated HTTP.")
                if not 1 <= options.port <= 65535:
                    raise ValueError("The HTTP port must be between 1 and 65535.")
                import uvicorn
                app = create_http_app(
                    runtime, options.scope, resource_url=options.resource_url,
                    readiness=None if options.graph_only else ApiReadinessProbe(runtime.settings.factory.api_url),
                )
                uvicorn.run(app, host=options.host, port=options.port, log_level="warning", access_log=False)
                return 0
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except BackendError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}), file=sys.stderr)
        return 1
    except ClientToolError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "result": exc.result}), file=sys.stderr)
        return 1
    except (
        ValueError, RuntimeError, OSError, McpError, httpx.HTTPError,
        anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream,
    ):
        print("AI Factory MCP failed. Check configuration, identity, dependencies and connectivity. "
              "Do not retry uncertain writes.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
