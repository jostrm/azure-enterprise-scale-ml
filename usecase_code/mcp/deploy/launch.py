"""Container entry point with a fail-closed read-only pilot configuration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile


PILOT_TOOLS = frozenset({"factory_health", "factory_capabilities", "factory_skills"})


def configure_graph(config: dict, release: dict, *, repository_root: Path = Path("/opt/repository")) -> None:
    graph = config.get("dual_graph")
    if graph is None:
        return
    packaged = release.get("metadata", {}).get("dual_graph", {})
    snapshot_id = packaged.get("snapshot_id")
    if (not isinstance(snapshot_id, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_id)
            or graph.get("expected_snapshot_id") != snapshot_id
            or graph.get("allow_source_access", False) is not False):
        raise ValueError("An enabled graph must match the immutable packaged snapshot with source access disabled.")
    graph["snapshot_root"] = str(repository_root / "meta" / "graphify" / "snapshots" / snapshot_id)


def validate_pilot(config: dict, application_auth: dict) -> None:
    if (config.get("factory", {}).get("writes_enabled") is not False
            or config.get("actions", {}).get("enabled_skills")
            or config.get("workloads", {}).get("enabled_skills")):
        raise ValueError("The connectivity pilot cannot enable action skills or writes.")
    grants = config.get("auth", {}).get("grants")
    graph_enabled = config.get("dual_graph") is not None
    permissions = {"factory.read", "graph.read"} if graph_enabled else {"factory.read"}
    if not isinstance(grants, list) or not grants or any(
        not isinstance(grant, dict) or "factory.read" not in grant.get("permissions", [])
        or not set(grant.get("permissions", [])) <= permissions for grant in grants
    ):
        raise ValueError("The pilot requires explicit read-only grants.")
    identities = application_auth.get("identities")
    tools = PILOT_TOOLS
    if graph_enabled:
        from aifactory_mcp.policy import GRAPH_APPLICATION_TOOLS
        tools = tools | GRAPH_APPLICATION_TOOLS
    if not isinstance(identities, list) or not identities or any(
        not isinstance(identity, dict) or not identity.get("allowed_tools")
        or not set(identity["allowed_tools"]) <= tools for identity in identities
    ):
        raise ValueError("Only approved pilot reads and separately opted-in graph tools can be exposed to Foundry.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode == "api":
        if not os.environ.get("AIFACTORY_API_KEY"):
            raise ValueError("The shared API credential is required.")
        os.chdir("/opt/api")
        sys.path.insert(0, "/opt/api")
        import uvicorn
        from src.api import app
        uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning", access_log=False)
        return
    if mode != "mcp":
        raise ValueError("Select the mcp or api container mode.")
    config = json.loads(os.environ["AIFACTORY_PILOT_CONFIG_JSON"])
    application_auth = json.loads(os.environ["AIFACTORY_APPLICATION_AUTH_JSON"])
    configure_graph(config, json.loads(Path("/opt/release.json").read_text(encoding="utf-8")))
    validate_pilot(config, application_auth)
    if not os.environ.get("AIFACTORY_API_KEY"):
        raise ValueError("The shared API credential is required.")
    config["factory"]["api_url"] = "http://127.0.0.1:8765"
    config["factory"]["folder"] = "/tmp/unused-pilot-catalog"
    config["factory"]["api_key_secret_url"] = None
    config["knowledge"]["repository_root"] = "/opt/repository"
    config["azure"]["credential"] = "managed_identity"
    config["azure"]["managed_identity_client_id"] = os.environ["AZURE_CLIENT_ID"]
    with tempfile.TemporaryDirectory(prefix="aifactory-mcp-") as directory:
        root = Path(directory)
        config_path, auth_path = root / "agent.json", root / "application-auth.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        auth_path.write_text(json.dumps(application_auth), encoding="utf-8")
        from aifactory_mcp.__main__ import main as serve
        raise SystemExit(serve([
            "serve", "--config", str(config_path), "--repository-root", "/opt/repository",
            "--scope", os.environ["AIFACTORY_MCP_SCOPE"], "--transport", "streamable-http",
            "--host", "0.0.0.0", "--port", "8080",
            "--resource-url", os.environ["AIFACTORY_MCP_RESOURCE_URL"],
            "--application-auth", str(auth_path),
        ]))


if __name__ == "__main__":
    main()
