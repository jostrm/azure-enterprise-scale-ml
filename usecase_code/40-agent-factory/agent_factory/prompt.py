from __future__ import annotations

import hashlib
import json

from .azure import AzureSession
from .catalog import OWNER, validate_agent_name
from .config import Target


class SessionCredential:
    def __init__(self, session: AzureSession):
        self.session = session

    def get_token(self, *scopes: str, **kwargs):
        from azure.core.credentials import AccessToken
        if len(scopes) != 1:
            raise ValueError("Exactly one Azure OAuth scope is required.")
        audience = scopes[0].removesuffix("/.default")
        token = self.session.token(audience)
        return AccessToken(token, int(self.session._tokens[audience][0]))

    def close(self):
        pass


def project_client(session: AzureSession, target: Target):
    from azure.ai.projects import AIProjectClient
    return AIProjectClient(endpoint=target.project_endpoint, credential=SessionCredential(session))


def definition_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def route_version(project, name: str, version: str) -> None:
    from azure.ai.projects.models import (
        AgentEndpointConfig, FixedRatioVersionSelectionRule, ProtocolConfiguration,
        ResponsesProtocolConfiguration, VersionSelector,
    )
    project.agents.update_details(
        agent_name=name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(version_selection_rules=[
                FixedRatioVersionSelectionRule(agent_version=version, traffic_percentage=100),
            ]),
            protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
        ),
    )


def deploy_prompt(project, target: Target, spec: dict, knowledge_tool: dict | None = None) -> dict:
    from azure.ai.projects.models import MCPTool, PromptAgentDefinition
    from azure.core.exceptions import ResourceNotFoundError

    name = validate_agent_name(spec["name"])
    tools = []
    if spec.get("grounding"):
        if not knowledge_tool:
            raise ValueError(f"{name} requires successfully ingested and configured Foundry IQ knowledge.")
        if (knowledge_tool.get("type") != "mcp"
                or not str(knowledge_tool.get("server_url", "")).startswith(target.search_endpoint + "/knowledgebases/")
                or knowledge_tool.get("allowed_tools") != ["knowledge_base_retrieve"]
                or knowledge_tool.get("require_approval") != "never"):
            raise ValueError("Grounding must use the selected project's private read-only Foundry IQ tool.")
        tools.append(knowledge_tool)
    if spec.get("microsoft_docs"):
        tools.append({
            "type": "mcp", "server_label": "microsoft-learn",
            "server_url": "https://learn.microsoft.com/api/mcp",
            "allowed_tools": ["microsoft_docs_search", "microsoft_docs_fetch"],
            "require_approval": "always",
        })
    definition = {"kind": "prompt", "model": spec.get("model") or target.model_deployment,
                  "instructions": spec["instructions"], "tools": tools}
    desired_metadata = {
        **spec["metadata"], "aifactory.execution_kind": "prompt",
        "aifactory.definition_hash": definition_hash({
            "definition": definition, "metadata": spec["metadata"], "description": spec["description"],
        }),
    }
    try:
        existing = project.agents.get(agent_name=name)
    except ResourceNotFoundError:
        existing = None
    if existing is not None:
        latest = existing.versions.latest
        if (latest.metadata or {}).get("aifactory.managed_by") != OWNER:
            raise RuntimeError(f"Agent '{name}' already exists and is not owned by this starter.")
        persisted_definition = latest.definition.as_dict()
        matches_definition = all(persisted_definition.get(key) == value for key, value in definition.items())
        if (latest.metadata.get("aifactory.definition_hash") == desired_metadata["aifactory.definition_hash"]
                and matches_definition and latest.description == spec["description"]):
            route_version(project, name, latest.version)
            return {"name": name, "version": latest.version, "id": latest.id,
                    "status": "unchanged", "framework": "prompt"}
    version = project.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(
            model=definition["model"], instructions=definition["instructions"],
            tools=[MCPTool(tool) for tool in tools],
        ),
        description=spec["description"], metadata=desired_metadata,
    )
    route_version(project, name, version.version)
    return {"name": name, "version": version.version, "id": version.id,
            "status": "created", "framework": "prompt"}
