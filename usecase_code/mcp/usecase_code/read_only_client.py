"""Discover MCP tools and read only Factory API health and capabilities.

This example uses the existing local operator configuration and the official MCP
stdio client. It does not use a model, execute the Factory CLI, or change Azure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import anyio
import httpx
from mcp import McpError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aifactory_mcp.client import ClientToolError, connect_stdio, invoke


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Existing Factory agent configuration JSON.")
    parser.add_argument("--scope", required=True, help="Exact configured scope key.")
    parser.add_argument("--object-id", required=True, help="Authorized local operator Entra object ID.")
    parser.add_argument("--repository-root", help="Factory repository root override.")
    return parser


async def _run(options):
    args = [
        "-m", "aifactory_mcp", "serve",
        "--config", str(Path(options.config).resolve()),
        "--scope", options.scope,
        "--object-id", options.object_id,
    ]
    if options.repository_root:
        args.extend(["--repository-root", str(Path(options.repository_root).resolve())])
    trace, discovered = [], []
    # Never forward the full user environment or print backend credentials.
    env = {name: os.environ[name] for name in ("AIFACTORY_API_KEY", "AZURE_CONFIG_DIR") if name in os.environ}
    async with connect_stdio(sys.executable, args, env=env) as session:
        cursor, seen = None, set()
        for _ in range(10):
            page = await session.list_tools() if cursor is None else await session.list_tools(cursor=cursor)
            discovered.extend(_field(page, "tools", []))
            cursor = _field(page, "nextCursor")
            if not cursor:
                break
            if cursor in seen:
                raise ClientToolError("MCP discovery repeated its pagination cursor.")
            seen.add(cursor)
        else:
            raise ClientToolError("MCP discovery exceeded its bounded page limit.")
        tools = [
            {"name": _field(tool, "name"),
             "read_only": _field(_field(tool, "annotations"), "readOnlyHint") is True}
            for tool in discovered
        ]
        allowed = {tool["name"] for tool in tools if tool["read_only"]}
        for name in ("factory_health", "factory_capabilities"):
            if name not in allowed:
                trace.append({"name": name, "status": "unavailable"})
                continue
            try:
                observation = await invoke(session, name, {})
                ok = isinstance(observation, dict) and observation.get("ok") is not False
                trace.append({"name": name, "status": "completed" if ok else "error", "result": observation})
            except ClientToolError:
                trace.append({"name": name, "status": "error", "error": "MCP reported a tool error."})
    completed = all(item["status"] == "completed" for item in trace)
    return {"status": "completed" if completed else "error", "tools": tools, "trace": trace}


def main(argv=None):
    options = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run(options))
    except (
        ClientToolError, McpError, httpx.HTTPError, OSError, ValueError,
        anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream,
    ):
        result = {
            "status": "error",
            "error_code": "mcp_readonly_failed",
            "error": "MCP read-only connection or discovery failed; no successful result is claimed.",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
