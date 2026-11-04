"""Preview, then opt in to a paid Foundry model-to-MCP read-only conversation.

Run with the MCP environment's Python. The default is a local preview: add
--live-read-only to send the supplied question and discovered read-tool results
to the existing configured model deployment. No Azure agent is created or changed.
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

from aifactory_mcp.client import ClientToolError, connect_stdio
from aifactory_mcp.host import run_host
from aifactory_mcp.runtime import load_runtime


def _question(value):
    if not value.strip() or len(value) > 8000:
        raise argparse.ArgumentTypeError("A question of 1-8000 characters is required.")
    return value


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Existing Factory agent configuration JSON.")
    parser.add_argument("--scope", required=True, help="Exact scope key from the existing configuration.")
    parser.add_argument("--object-id", required=True, help="Authorized local operator Entra object ID.")
    parser.add_argument("--repository-root", help="Factory repository root, if not inferred from configuration.")
    parser.add_argument("--question", required=True, type=_question)
    parser.add_argument(
        "--live-read-only", action="store_true",
        help="Opt in to paid model inference and authorized read-only MCP calls (no Azure changes).",
    )
    return parser


async def _run(options):
    runtime = await asyncio.to_thread(
        load_runtime, options.config, repository_root=options.repository_root,
    )
    if not options.live_read_only:
        return {
            "status": "preview",
            "model_request_sent": False,
            "model_deployment": runtime.settings.azure.model_deployment,
            "scope": options.scope,
            "agent_name": runtime.settings.agent_name,
            "instructions_source": "aifactory_agent.foundry.INSTRUCTIONS",
            "deployment_modified": False,
            "next_step": "Add --live-read-only to make a paid model request using read-only MCP tools.",
            "data_sent_on_opt_in": "Only the question, existing agent instructions, MCP tool schemas and tool results.",
        }
    args = [
        "-m", "aifactory_mcp", "serve",
        "--config", str(Path(options.config).resolve()),
        "--scope", options.scope,
        "--object-id", options.object_id,
    ]
    if options.repository_root:
        args.extend(["--repository-root", str(Path(options.repository_root).resolve())])
    # MCP's stdio environment is intentionally minimal; forward only local backend needs.
    env = {name: os.environ[name] for name in ("AIFACTORY_API_KEY", "AZURE_CONFIG_DIR") if name in os.environ}
    async with connect_stdio(sys.executable, args, env=env) as session:
        return await run_host(session, runtime, options.question)


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
            "error_code": "readonly_example_failed",
            "error": "The read-only example failed. Check the existing configuration, authorization and connectivity.",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"preview", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
