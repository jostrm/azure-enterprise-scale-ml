from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import load_settings
from .services import AgentServices


def operator_principal(settings):
    import subprocess
    import shutil
    from .security import Principal
    if settings.azure.credential != "cli":
        raise ValueError("Operator ask requires explicit Azure CLI user credentials; a service cannot impersonate a user.")
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is unavailable.")
    response = subprocess.run(
        [executable, "ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return Principal(settings.tenant_id, response.stdout.strip())


def main(argv=None, *, services: AgentServices | None = None, principal_provider=operator_principal):
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
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    if services is not None and services.settings != settings:
        raise ValueError("Injected agent services must match the selected settings.")
    services = services if services is not None else AgentServices(settings)
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
        knowledge = services.knowledge()
        if args.command == "ingest":
            knowledge.ensure_resources()
            result = knowledge.refresh()
        elif args.command == "knowledge-status":
            result = knowledge.status()
        else:
            principal = principal_provider(settings)
            result = services.conversation(knowledge).answer(args.question, args.audience, principal, args.scope)
    else:
        import uvicorn
        from .telemetry import configure
        from .web import create_app
        configure(settings)
        uvicorn.run(create_app(settings, services=services), host="0.0.0.0", port=args.port, proxy_headers=False,
                    ws_max_size=1 << 20)
        return
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
