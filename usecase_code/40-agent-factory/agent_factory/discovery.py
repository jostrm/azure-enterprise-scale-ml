"""Resolve actual ARM resources instead of attempting to reproduce Bicep salt generation."""

from __future__ import annotations

from urllib.parse import urlsplit

from .azure import ARM, AzureSession
from .config import FactoryConfig, Target


def select_one(resources: list[dict], label: str, name: str = "") -> dict:
    candidates = [item for item in resources if not name or item["name"].split("/")[-1] == name]
    if len(candidates) != 1:
        names = ", ".join(item["name"] for item in candidates) or "(none)"
        raise ValueError(f"Expected exactly one {label}; found {len(candidates)}: {names}. Set an explicit target.")
    return candidates[0]


def discover(config: FactoryConfig, session: AzureSession) -> Target:
    if (config.subscription_id, config.tenant_id) != (session.subscription_id, session.tenant_id):
        raise ValueError("Discovery session must match the configured tenant and subscription.")
    group_id = f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}"
    resources = session.pages(f"{ARM}{group_id}/resources?api-version=2021-04-01")

    def of_type(kind: str) -> list[dict]:
        return [item for item in resources if item["type"].lower() == kind.lower()]

    accounts = [item for item in of_type("Microsoft.CognitiveServices/accounts")
                if item.get("kind") == "AIServices"]
    account = select_one(accounts, "Foundry account", config.account_name)
    projects = session.pages(f"{ARM}{account['id']}/projects?api-version=2025-06-01")
    project = select_one(projects, "Foundry project", config.project_name)
    project_name = project["name"].split("/")[-1]
    project = session.arm("GET", f"{account['id']}/projects/{project_name}")
    endpoint = project["properties"]["endpoints"]["AI Foundry API"].rstrip("/")
    endpoint_parts = urlsplit(endpoint)
    if endpoint_parts.scheme != "https" or endpoint_parts.hostname != f"{account['name']}.services.ai.azure.com":
        raise ValueError("Unexpected Foundry endpoint. Only Azure public-cloud project endpoints are supported.")
    deployments = session.pages(f"{ARM}{account['id']}/deployments?api-version=2025-06-01")
    ready = [item for item in deployments if item["properties"].get("provisioningState") == "Succeeded"]
    chat = select_one(
        [item for item in ready if item["properties"]["model"]["format"] == "OpenAI"
         and not item["properties"]["model"]["name"].startswith("text-embedding")],
        "chat model deployment", config.model_deployment,
    )
    embeddings = [item for item in ready if item["properties"]["model"]["name"].startswith("text-embedding")]
    embedding = select_one(embeddings, "embedding deployment", config.embedding_deployment) if (
        embeddings or config.embedding_deployment
    ) else None
    search = select_one(of_type("Microsoft.Search/searchServices"), "AI Search service", config.search_name)
    storage = select_one(
        [item for item in of_type("Microsoft.Storage/storageAccounts") if "2001" in item["name"]],
        "2001 project data storage (1001 is reserved for Foundry)", config.storage_name,
    )
    identity = select_one(
        [item for item in of_type("Microsoft.ManagedIdentity/userAssignedIdentities")
         if item["name"].startswith(f"mi-prj{config.project_number}-")],
        "project user-assigned managed identity", config.identity_name,
    )
    identity = session.arm("GET", identity["id"], api_version="2023-01-31")
    return Target(
        config.tenant_id, config.subscription_id, config.resource_group, config.common_resource_group,
        account["name"], project_name, endpoint, account["location"], chat["name"].split("/")[-1],
        embedding["name"].split("/")[-1] if embedding else "", search["name"], storage["name"],
        identity["id"], identity["properties"]["clientId"],
    )
