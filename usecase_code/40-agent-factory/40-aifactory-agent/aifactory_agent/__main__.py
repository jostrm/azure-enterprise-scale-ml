from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import load_settings


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--config", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("deploy-agent")
    sub.add_parser("ingest")
    sub.add_parser("knowledge-status")
    query = sub.add_parser("ask")
    query.add_argument("--scope", required=True)
    query.add_argument("--audience", choices=["platform", "project"], required=True)
    query.add_argument("--question", required=True)
    sub.add_parser("serve").add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    settings = load_settings(args.config)
    sys.path.insert(0, str(settings.knowledge.repository_root / "environment_setup" / "azurefactory-cli" / "src"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    if args.command == "deploy-agent":
        from .foundry import deploy
        result = deploy(settings)
    elif args.command in {"ingest", "knowledge-status", "ask"}:
        from .knowledge import Knowledge
        knowledge = Knowledge(settings)
        if args.command == "ingest":
            knowledge.ensure_resources()
            result = knowledge.refresh()
        elif args.command == "knowledge-status":
            result = knowledge.status()
        else:
            if settings.azure.credential != "cli":
                raise ValueError("Operator ask requires explicit Azure CLI user credentials; a service cannot impersonate a user.")
            import subprocess
            import shutil
            executable = shutil.which("az")
            if not executable:
                raise RuntimeError("Azure CLI is unavailable.")
            response = subprocess.run(
                [executable, "ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"],
                check=True, capture_output=True, text=True, timeout=60)
            from .security import Principal
            from .foundry import Conversation
            principal = Principal(settings.tenant_id, response.stdout.strip())
            result = Conversation(settings, knowledge).answer(args.question, args.audience, principal, args.scope)
    else:
        import uvicorn
        from .telemetry import configure
        from .web import create_app
        configure(settings)
        uvicorn.run(create_app(settings), host="0.0.0.0", port=args.port, proxy_headers=False)
        return
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
