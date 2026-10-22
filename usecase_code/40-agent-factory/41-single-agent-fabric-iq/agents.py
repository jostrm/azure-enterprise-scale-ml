# Imports

import os
from pathlib import Path
from dotenv import load_dotenv

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    WorkflowAgentDefinition,
    FabricIQPreviewTool,
    MCPTool,
)

HERE = Path(__file__).resolve().parent
REQUIRED = ("endpoint", "model_deployment_name", "server_label", "server_url", "project_connection_id")
OPTIONAL = ("fabric_connection_name",)  # empty: skip the Fabric IQ Inventory-Agent


def load_settings(path=HERE / "parameters.env"):
    # Load environment variables and fail fast on the ones that are missing
    load_dotenv(path)
    settings = {name: os.getenv(name, "").strip() for name in REQUIRED + OPTIONAL}
    missing = [name for name in REQUIRED if not settings[name]]
    if missing:
        raise SystemExit(f"Missing in {Path(path).name}: {', '.join(missing)} (see parameters.env.template)")
    return settings


def created(agent):
    print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")


def main():
    settings = load_settings()
    model = settings["model_deployment_name"]

    # Initialize the AI Project client
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=settings["endpoint"], credential=credential, allow_preview=True) as project_client,
    ):
        # Define MCP tool for knowledge retrieval (Foundry IQ knowledge base)
        mcp_tool = MCPTool(
            server_label=settings["server_label"],
            server_url=settings["server_url"],
            project_connection_id=settings["project_connection_id"],
            require_approval="never",
        )

        # Create Reward Campaign Agent
        created(project_client.agents.create_version(
            agent_name="Rewards-Campaign-Agent",
            definition=PromptAgentDefinition(
                model=model,
                instructions="""Apply personalized discounts to customers based on their loyalty information and explain the applicable Black Friday promotional tiers using the provided knowledge.
                ________________________________________
                Response Behavior
                •	Generate responses only from the retrieved knowledge and tool outputs. Do not assume or invent any values.
                •	When a customer name is included, respond in a friendly first-person tone and include celebratory emojis such as 🎉, 😊, or 🛍️.
                •	When the internal team asks about discount tiers, provide an average discount range instead of listing every individual percentage.
                •	Ensure the response clearly reflects the loyalty information and discount values retrieved from the knowledge source or tools.
                ________________________________________
                Response Format
                Always return the response in the following JSON format:
                {
                "answer": "<response generated using the knowledge and tool results>",
                "discount_percentage": "<discount value retrieved from the knowledge or tool>"
                }
                ________________________________________
                Content Handling Guidelines
                •	Do not summarize, filter, or remove any important information from the knowledge source.
                •	Responses must strictly follow the information retrieved from the given knowledge only.
                •	If the required information is not available in the knowledge or tool output, clearly state that the data could not be found.""",
                tools=[mcp_tool],
            ),
        ))

        # Create Sales Associate Agent
        created(project_client.agents.create_version(
            agent_name="Sales-Associate-Agent",
            definition=PromptAgentDefinition(
                model=model,
                instructions="""Interior Design Agent Guidelines:

                ========================================

                - You are an Interior Designer salesperson working for Zava and helps customers with DIY Projects and interior design queries.
                - Your main tasks are the following: recommending and upselling products, creating images
                - You will get user query
                - You will always recommend product from in given Azure AI Search tool only.
                - You will keep asking questions to the user and keep recommending.
                - When you get video or image, reply saying "I see you uploaded..."
                - If asked to change/modify/style an object, only then use create_image, otherwise keep recommending and upselling as usual.

                Your response should only come from the given knowledge and with following details like ProductId, ProductName, Category, ProductDescription, FormattedPrice

                Example Conversation

                ========================================

                User: Want paint recommendation for my living room
                You: Give some paints options, ask dimension, ask image
                User: Gives dimensions, image (maybe)
                You: Recommends based on the color, calculate how much paint maybe required, upsell for sprayer, tape (saying its good)""",
                tools=[mcp_tool],
            ),
        ))

        # Create Inventory Agent (Fabric IQ tool over a published Microsoft Fabric data agent)
        inventory_instructions = """You are Inventory check agent,
            •	Your task is to check the inventory status.
            •	When a user asks to check the inventory for a product, send the product name to the Fabric IQ tool.
            •	Return the response including inventory levels, inventory status, and location.
        Content Handling Guidelines
            •	Do not generate summaries or remove any data from the response.
            •	The response must come only from the Fabric IQ tool output.

        Important Rule:
        Use these products ids as risk of stockout:
        Products currently at risk of stockout include:
        PROD000030
        PROD000281
        PROD000222
        PROD000262
        PROD000302
        PROD000375
        PROD000478
        PROD000486
        PROD000145
        PROD000511"""
        inventory_tools = []
        if settings["fabric_connection_name"]:
            fabric_connection = project_client.connections.get(settings["fabric_connection_name"])
            inventory_tools = [FabricIQPreviewTool(project_connection_id=fabric_connection.id, require_approval="never")]
        else:
            # Keeps the workflow route working until Fabric IQ is connected, without guessing stock levels
            inventory_instructions = """The Fabric IQ inventory connection is not configured yet.
            Say that you cannot check stock levels right now and suggest asking a Zava store associate.
            Never guess inventory levels, status or locations."""
            print("Inventory-Agent has no Fabric IQ tool: fabric_connection_name is empty in parameters.env")
        created(project_client.agents.create_version(
            agent_name="Inventory-Agent",
            definition=PromptAgentDefinition(model=model, instructions=inventory_instructions, tools=inventory_tools),
        ))

        # Create Supervisor Agent: answers with the name of the agent the workflow routes to
        created(project_client.agents.create_version(
            agent_name="Supervisor-Agent",
            definition=PromptAgentDefinition(
                model=model,
                instructions="""You route Zava customer questions. Reply with exactly one agent name and nothing else:
                Sales-Associate-Agent: product recommendations, interior design, DIY projects, prices.
                Rewards-Campaign-Agent: loyalty tiers, member discounts, Black Friday promotions.
                Inventory-Agent: stock levels, stock status, availability or location of a product.""",
            ),
        ))

        # Create the workflow that calls the supervisor and routes to one of the agents above
        created(project_client.agents.create_version(
            agent_name="FoundryIQ-Workflow",
            definition=WorkflowAgentDefinition(workflow=(HERE / "workflow.yaml").read_text(encoding="utf-8")),
        ))


if __name__ == "__main__":
    main()
