"""Read-only preflight: signed-in scope, private DNS and Azure ML prerequisites."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from .configuration import read_json
from .usecases import AIR, CHURN, model_name


def resolve(host: str) -> dict:
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except OSError as error:
        return {"host": host, "addresses": [], "private": False, "error": type(error).__name__}
    private = bool(addresses) and all(ipaddress.ip_address(address).is_private for address in addresses)
    return {"host": host, "addresses": addresses, "private": private}


def hosts(config: dict) -> list[str]:
    blob = urlsplit(config["shared_lake"]["account_url"]).netloc
    return [blob, blob.replace(".blob.", ".dfs."), urlsplit(config["project_endpoint"]).netloc]


def preflight(config: dict, *, azure: bool = True, ml_client=None) -> dict:
    """Never creates, changes or deletes anything; reports gaps instead of fixing them."""
    result = {"dns": [resolve(host) for host in hosts(config)], "azure_written": False}
    gaps = [f"{item['host']} does not resolve to a private address" for item in result["dns"] if not item["private"]]
    if azure:
        from ml_model_factory.project import azure_cli

        account = azure_cli("account", "show", "--subscription", config["subscription_id"])
        tenant_ok = str(account.get("tenantId", "")).lower() == config["tenant_id"].lower()
        result["account"] = {"user": account.get("user", {}).get("name"), "tenant_matches": tenant_ok}
        if not tenant_ok:
            gaps.append("Azure CLI is signed in to a different tenant")
        runtime = read_json(config["reviewed_rollout"])["runtime"]
        if ml_client is None:
            from azure.ai.ml import MLClient
            from azure.identity import AzureCliCredential

            ml_client = MLClient(AzureCliCredential(subscription=config["subscription_id"], process_timeout=60),
                                 config["subscription_id"], runtime["resource_group"], runtime["workspace_name"])
        workspace = ml_client.workspaces.get(runtime["workspace_name"])
        result["workspace"] = {"name": workspace.name,
                               "public_network_access": getattr(workspace, "public_network_access", None)}
        computes = {}
        for name in sorted({config["usecases"][CHURN]["compute"], config["usecases"][AIR]["compute"]}):
            try:
                compute = ml_client.compute.get(name)
                computes[name] = {"exists": True, "state": getattr(compute, "provisioning_state", None),
                                  "size": getattr(compute, "size", None),
                                  "min_nodes": getattr(compute, "min_instances", None),
                                  "max_nodes": getattr(compute, "max_instances", None)}
            except Exception as error:  # noqa: BLE001 - report, never create
                computes[name] = {"exists": False, "error": type(error).__name__}
                gaps.append(f"Compute {name} is unavailable; it is never created by this example")
        result["computes"] = computes
        models = {}
        for name in (model_name(CHURN), model_name(AIR)):
            try:
                models[name] = sorted(int(item.version) for item in ml_client.models.list(name=name))
            except Exception as error:  # noqa: BLE001
                models[name] = {"error": type(error).__name__}
        result["models"] = models
        champion = config["usecases"][AIR]["champion_model_id"].rsplit(":", 1)[1]
        if not isinstance(models[model_name(AIR)], list) or int(champion) not in models[model_name(AIR)]:
            gaps.append("The configured air-passengers champion version is not visible")
        environment = runtime["environment"].removeprefix("azureml:")
        try:
            name, version = environment.split(":")
            ml_client.environments.get(name, version=version)
            result["environment"] = {"name": environment, "exists": True}
        except Exception as error:  # noqa: BLE001
            result["environment"] = {"name": environment, "exists": False, "error": type(error).__name__}
            gaps.append(f"Environment {environment} is unavailable")
        try:
            next(iter(ml_client.jobs.list(max_results=1)), None)
            result["aml_data_plane"] = "reachable"
        except Exception as error:  # noqa: BLE001
            result["aml_data_plane"] = type(error).__name__
            gaps.append("The Azure ML data plane is unreachable from this workstation")
    result["gaps"] = gaps
    result["ready"] = not gaps
    return result
