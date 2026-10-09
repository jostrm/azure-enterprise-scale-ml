"""Use case 5 - expose health as read-only MCP tools.

``aifactory_healthmodel.tools.TOOLS`` uses the Model Context Protocol tool shape, so an MCP
server (for example the AI Factory MCP package) can list them and forward calls to
``call_tool``. This script prints the tool list and calls one tool the way a server would.

    python 05_mcp_tools.py --model-id <id>
"""
import argparse
import json

from _common import add_model_arguments, client_from
from aifactory_healthmodel.tools import TOOLS, call_tool

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
add_model_arguments(parser)
parser.add_argument("--tool", default="healthmodel_summary", choices=[t["name"] for t in TOOLS])
args = parser.parse_args()
model = client_from(args, read_only=True)

print("tools/list ->", json.dumps([{"name": t["name"], "title": t["title"]} for t in TOOLS], indent=1))

# A server would authorize the caller, then build a client for the requested model ID.
result = call_tool(lambda model_id: model, args.tool, {"modelId": model.model_id})
print(f"tools/call {args.tool} ->")
print(json.dumps(result, indent=1)[:4000])
