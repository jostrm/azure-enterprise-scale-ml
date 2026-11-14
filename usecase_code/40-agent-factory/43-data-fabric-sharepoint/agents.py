# Create one Foundry prompt agent whose tools are the data sources enabled in data-sources.json

import os
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FabricIQPreviewTool,
    MCPTool,
    PromptAgentDefinition,
    SharepointGroundingToolParameters,
    SharepointPreviewTool,
    ToolProjectConnection,
)

from data_sources import agent_instructions, build_tools, enabled_sources, load_data_sources

HERE = Path(__file__).resolve().parent
REQUIRED = ("endpoint", "model_deployment_name", "agent_name")


class FoundryToolFactory:
    """Adapter: implements the data_sources.ToolFactory port with azure-ai-projects 2.4 tool types."""

    def sharepoint(self, connection_id):
        return SharepointPreviewTool(sharepoint_grounding_preview=SharepointGroundingToolParameters(
            project_connections=[ToolProjectConnection(project_connection_id=connection_id)]))

    def knowledge_base(self, server_label, server_url, connection_id):
        # Foundry IQ knowledge base (Azure AI Search) exposed as an MCP endpoint
        return MCPTool(server_label=server_label, server_url=server_url,
                       project_connection_id=connection_id, require_approval="never")

    def fabric_iq(self, connection_id):
        return FabricIQPreviewTool(project_connection_id=connection_id, require_approval="never")


def load_settings(path=HERE / "parameters.env"):
    # Load environment variables and fail fast on the ones that are missing
    load_dotenv(path)
    settings = {name: os.getenv(name, "").strip() for name in REQUIRED + ("data_sources_file",)}
    missing = [name for name in REQUIRED if not settings[name]]
    if missing:
        raise SystemExit(f"Missing in {Path(path).name}: {', '.join(missing)} (see parameters.env.template)")
    settings["data_sources_file"] = HERE / (settings["data_sources_file"] or "data-sources.json")
    return settings


def main():
    settings = load_settings()
    sources = load_data_sources(settings["data_sources_file"])
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=settings["endpoint"], credential=credential, allow_preview=True) as project_client,
    ):
        tools = build_tools(sources, FoundryToolFactory(),
                            resolve_connection=lambda name: project_client.connections.get(name).id)
        agent = project_client.agents.create_version(
            agent_name=settings["agent_name"],
            definition=PromptAgentDefinition(model=settings["model_deployment_name"],
                                             instructions=agent_instructions(sources), tools=tools),
        )
        kinds = ", ".join(source.kind for source in enabled_sources(sources)) or "none"
        print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version}); data sources: {kinds}")


if __name__ == "__main__":
    main()
