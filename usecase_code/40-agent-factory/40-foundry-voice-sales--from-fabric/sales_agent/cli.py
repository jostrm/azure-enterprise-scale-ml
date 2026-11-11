from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .config import ROOT, ConfigurationError, Settings
from .contracts import SalesError

CLOUD_ACTIONS = {"diagnose", "connectivity", "discover", "publish", "text", "smoke", "serve"}


def parser():
    result = argparse.ArgumentParser(description="Local DSVM workflow; Azure actions require --allow-azure.")
    result.add_argument("--env-file", type=Path, default=ROOT / ".env")
    actions = result.add_subparsers(dest="action", required=True)
    actions.add_parser("check", help="Validate configuration without obtaining credentials or contacting services.")
    for action in sorted(CLOUD_ACTIONS):
        command = actions.add_parser(action)
        command.add_argument("--allow-azure", action="store_true")
        if action in {"text", "smoke"}:
            command.add_argument("--question", required=True)
        if action == "connectivity":
            command.add_argument("--require-private", action="store_true")
        if action == "serve":
            command.add_argument("--port", type=int, default=8765)
    return result


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=True))


def connectivity_report(host, addresses, *, tls, require_private):
    private = bool(addresses) and all(
        ipaddress.ip_address(value).is_private
        and not ipaddress.ip_address(value).is_loopback
        and not ipaddress.ip_address(value).is_link_local for value in addresses
    )
    return {
        "host": host, "addresses": addresses, "private_addresses": private,
        "tls": tls, "require_private": require_private, "scope": "dns_tcp_tls_only",
        "status": "passed" if tls and addresses and (not require_private or private) else "failed",
    }


async def connectivity(settings, *, require_private):
    targets = [("foundry", settings.project_endpoint), ("fabric_mcp", settings.fabric_url)]
    if settings.voice_enabled:
        targets.append(("voice", settings.voice_endpoint))
    reports = []
    for name, url in targets:
        host = urlsplit(url).hostname
        addresses, tls = [], False
        try:
            async with asyncio.timeout(15):
                resolved = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                addresses = sorted({entry[4][0] for entry in resolved})
                _, writer = await asyncio.open_connection(host, 443, ssl=ssl.create_default_context(),
                                                          server_hostname=host)
                writer.close()
                await writer.wait_closed()
                tls = True
        except (OSError, TimeoutError):
            tls = False
        reports.append({"service": name, **connectivity_report(
            host, addresses, tls=tls, require_private=require_private
        )})
    return reports


async def run_cloud(args, settings):
    # No Azure adapter is imported or instantiated on the offline check path.
    from .fabric import FabricDataAgent
    from .gateway import FoundryGateway
    from .identity import UserIdentity
    from .service import SalesConversation

    identity = UserIdentity(settings)
    gateway = FoundryGateway(settings, identity.credential)
    fabric = FabricDataAgent(settings, identity.credential)
    try:
        if args.action == "serve":
            import uvicorn
            from .voice import connect_voice
            from .web import create_app

            app = create_app(
                settings, lambda: SalesConversation(gateway, fabric),
                lambda: connect_voice(settings, identity.credential),
                port=args.port, verify_identity=identity.verify,
            )
            server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning",
                ws_max_size=32768, ws_ping_interval=20, ws_ping_timeout=20,
            ))
            await server.serve()
            return 0
        profile = await identity.verify()
        if args.action == "connectivity":
            reports = await connectivity(settings, require_private=args.require_private)
            emit({"checks": reports, "service_authorization": "not run"})
            return 0 if all(item["status"] == "passed" for item in reports) else 1
        if args.action == "diagnose":
            checks = []
            for name, scope in (("foundry_token", "https://ai.azure.com/.default"),
                                ("fabric_token", "https://api.fabric.microsoft.com/.default")):
                await identity.credential.get_token(scope)
                checks.append({"check": name, "status": "passed"})
            emit({"identity": profile, "checks": checks,
                  "note": "Token acquisition is not proof of resource authorization or data access."})
        elif args.action == "publish":
            version = await gateway.publish()
            emit({"status": "passed", "published": version,
                  "next": "Set FOUNDRY_AGENT_VERSION to the returned version and run Validate."})
        elif args.action == "discover":
            emit({"status": "passed", "mcp": await fabric.discover(), "query_invocation": "not run"})
        elif args.action == "text":
            emit(await SalesConversation(gateway, fabric).answer(args.question))
        elif args.action == "smoke":
            results = [
                {"check": "user_identity", "status": "passed"},
                {"check": "mcp_discovery", "status": "not run"},
                {"check": "foundry_and_fabric_query", "status": "not run"},
                {"check": "live_voice_and_interruption", "status": "not run"},
                {"check": "fabric_iq", "status": "not run", "reason": "Not included in this baseline."},
            ]
            stage = 1
            try:
                await fabric.discover()
                results[stage]["status"] = "passed"
                stage = 2
                answer = await SalesConversation(gateway, fabric).answer(args.question)
                results[stage]["status"] = "passed"
            except SalesError as exc:
                results[stage].update(status="failed", code=exc.code, message=exc.message)
                emit({"checks": results})
                return 1
            emit({"checks": results, "answer": answer})
        return 0
    finally:
        try:
            await gateway.close()
        finally:
            await identity.close()


def main(argv=None):
    args = parser().parse_args(argv)
    if args.action in CLOUD_ACTIONS and not args.allow_azure:
        print("Not run: this action requires --allow-azure and must run in your private environment.",
              file=sys.stderr)
        return 2
    if args.action == "serve" and not 1024 <= args.port <= 65535:
        print("Port must be between 1024 and 65535.", file=sys.stderr)
        return 2
    try:
        settings = Settings.load(
            args.env_file, publication=args.action == "publish",
            allow_unpublished=args.action in {"diagnose", "connectivity", "discover"},
        )
        if args.action == "check":
            emit({"status": "passed", "check": "configuration", "azure": "not run",
                  "voice_enabled": settings.voice_enabled})
            return 0
        return asyncio.run(run_cloud(args, settings))
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except SalesError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": exc.message}), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
