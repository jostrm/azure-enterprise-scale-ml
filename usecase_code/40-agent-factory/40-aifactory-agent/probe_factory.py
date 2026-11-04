"""Read-only integration probe against the original API source, not a mock API."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

from aifactory_agent.config import load_settings
from aifactory_agent.security import Principal


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--api-source", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    args = parser.parse_args()
    source = args.api_source.resolve()
    if not (source / "src" / "api.py").is_file():
        raise ValueError("Supply the approved original Factory API source checkout.")
    settings = load_settings(args.config)
    sys.path.insert(0, str(settings.knowledge.repository_root / "environment_setup" / "azurefactory-cli" / "src"))
    from aifactory_agent.tools import FactoryTools
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required.")
    caller = subprocess.run(
        [executable, "ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"],
        check=True, text=True, capture_output=True, timeout=60).stdout.strip()
    principal = Principal(settings.tenant_id, caller)
    # This isolated process key is never persisted, logged, or put in arguments.
    os.environ["AIFACTORY_API_KEY"] = secrets.token_urlsafe(48)
    sys.path.insert(0, str(source))
    original = importlib.import_module("src.api")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen(128)
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(original.app, log_level="warning", access_log=False))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 20
    try:
        while not server.started:
            if not worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The original API did not become responsive.")
            time.sleep(0.05)
        configured = settings.model_copy(update={"factory": settings.factory.model_copy(update={"api_url": url})})
        # Preserve only the trusted existing CLI package path for the fixed subprocess.
        os.environ["PYTHONPATH"] = str(settings.knowledge.repository_root / "environment_setup" / "azurefactory-cli" / "src")
        tools = FactoryTools(configured, principal, args.scope)
        result = {name: tools.execute(name, {}) for name in
                  ("factory_health", "factory_capabilities", "factory_cli_health")}
        if any(value.get("ok") is not True for value in result.values()):
            raise RuntimeError(json.dumps(result))
        print(json.dumps({"api_source": str(source), "api_title": original.app.title,
                          "mode": "original-loopback-api-read-only", "results": result}, indent=2))
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        os.environ.pop("AIFACTORY_API_KEY", None)


if __name__ == "__main__":
    main()
