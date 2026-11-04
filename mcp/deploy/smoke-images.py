"""Exercise the real Linux images locally; never request Azure tokens or change Azure."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def docker(*args: str, env=None) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=90, env=env)
    if result.returncode:
        raise RuntimeError("A local Docker smoke-test command failed; inspect the named test image.")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-image", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    scope = next(iter(config["scopes"]))
    caller = "22222222-2222-4222-8222-222222222222"
    app_caller = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    config["factory"]["writes_enabled"] = False
    config["actions"] = {"enabled_skills": []}
    config["workloads"] = {}
    config["auth"].update(
        client_id="33333333-3333-4333-8333-333333333333",
        audience="33333333-3333-4333-8333-333333333333",
        grants=[{"object_id": identity, "scopes": [scope], "permissions": ["factory.read"]}
                for identity in (caller, app_caller)],
    )
    auth = {
        "audience": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "required_role": "AiFactory.Mcp.Read",
        "identities": [{
            "object_id": app_caller, "client_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            "scope_keys": [scope],
            "allowed_tools": ["factory_health", "factory_capabilities", "factory_skills"],
        }],
    }
    env = {**os.environ, "AIFACTORY_API_KEY": secrets.token_hex(32)}
    api_id = mcp_id = None
    try:
        api_id = docker("run", "--detach", "--publish", "127.0.0.1::8080",
                        "--env", "AIFACTORY_API_KEY", args.api_image, env=env)
        port = docker("port", api_id, "8080/tcp").rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"
        env.update({
            "AIFACTORY_PILOT_CONFIG_JSON": json.dumps(config),
            "AIFACTORY_APPLICATION_AUTH_JSON": json.dumps(auth),
            "AIFACTORY_MCP_SCOPE": scope, "AIFACTORY_MCP_RESOURCE_URL": base + "/mcp",
            "AZURE_CLIENT_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        })
        variables = [part for name in (
            "AIFACTORY_API_KEY", "AIFACTORY_PILOT_CONFIG_JSON", "AIFACTORY_APPLICATION_AUTH_JSON",
            "AIFACTORY_MCP_SCOPE", "AIFACTORY_MCP_RESOURCE_URL", "AZURE_CLIENT_ID",
        ) for part in ("--env", name)]
        mcp_id = docker("run", "--detach", "--network", "container:" + api_id,
                        *variables, args.mcp_image, env=env)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 60
        while True:
            try:
                with opener.open(base + "/health/ready", timeout=3) as response:
                    readiness = json.load(response)
                if readiness["status"] == "ready":
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("The local MCP/API pair did not become ready.") from None
            if time.monotonic() >= deadline:
                raise RuntimeError("The local MCP/API pair did not become ready.")
            time.sleep(0.5)
        request = urllib.request.Request(base + "/mcp", data=b"{}", headers={"Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=3):
                raise RuntimeError("Unauthenticated MCP request was unexpectedly accepted.")
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise RuntimeError("MCP authentication challenge was not 401.") from None
        command = (
            "import pathlib,subprocess,sys;"
            "config=next(pathlib.Path('/tmp').glob('aifactory-mcp-*/agent.json'));"
            "p=subprocess.run([sys.executable,'-m','aifactory_mcp','call',sys.argv[1],"
            "'--config',str(config),'--repository-root','/opt/repository','--scope',sys.argv[2],"
            "'--object-id',sys.argv[3]],check=True,capture_output=True,text=True);print(p.stdout)"
        )
        health = json.loads(docker("exec", mcp_id, "python", "-c", command, "factory_health", scope, caller))
        capabilities = json.loads(docker("exec", mcp_id, "python", "-c", command, "factory_capabilities", scope, caller))
        if health.get("ok") is not True or capabilities.get("ok") is not True:
            raise RuntimeError("The actual MCP/agent/API path did not confirm read-only results.")
        print(json.dumps({
            "status": "passed", "unauthenticated_mcp": 401, "health": health,
            "capabilities_ok": True, "readiness": readiness,
            "api_user": docker("image", "inspect", args.api_image, "--format", "{{.Config.User}}"),
            "mcp_user": docker("image", "inspect", args.mcp_image, "--format", "{{.Config.User}}"),
            "azure_calls": False,
        }, indent=2))
    finally:
        try:
            if mcp_id:
                docker("rm", "--force", mcp_id)
        finally:
            if api_id:
                docker("rm", "--force", api_id)


if __name__ == "__main__":
    main()
