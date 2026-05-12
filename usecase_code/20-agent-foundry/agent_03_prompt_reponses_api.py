# Before running the sample:
#    pip install azure-ai-projects>=2.0.0

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition

load_dotenv()
user_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
agent_name = os.getenv("AGENT_NAME", "<TODO>")
model_deployment_name = os.getenv("CHAT_MODEL", "<TODO>")

def get_credential():
    """
    Get Azure credential based on AUTH_MODE environment variable.
    
    AUTH_MODE options:
    - 'uami' or 'mi': Use User-Assigned Managed Identity (requires AZURE_CLIENT_ID)
    - 'user' or 'interactive': Use user credentials (CLI, browser, PowerShell)
    - default (not set): Standard DefaultAzureCredential chain
    
    Environment variables:
    - AUTH_MODE: Authentication mode ('uami', 'mi', 'user', 'interactive')
    - AZURE_CLIENT_ID: Client ID of the User-Assigned Managed Identity (required for UAMI)
    """
    auth_mode = os.getenv("AUTH_MODE", "").lower()
    
    if auth_mode in ["uami", "mi"]:
        # UAMI mode: Only use managed identity, exclude user credentials
        managed_identity_client_id = os.getenv("AZURE_CLIENT_ID")
        if not managed_identity_client_id:
            raise ValueError("AZURE_CLIENT_ID environment variable required for UAMI authentication mode")
        
        return DefaultAzureCredential(
            managed_identity_client_id=managed_identity_client_id,
            exclude_cli_credential=True,
            exclude_powershell_credential=True,
            exclude_developer_cli_credential=True,
            exclude_interactive_browser_credential=True,
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_environment_credential=True,
            exclude_workload_identity_credential=True,
        )
    
    elif auth_mode in ["user", "interactive"]:
        # User mode: Exclude managed identity, prefer CLI/PowerShell/interactive
        return DefaultAzureCredential(
            exclude_managed_identity_credential=True,
            exclude_workload_identity_credential=True,
            exclude_environment_credential=True,
        )
    
    else:
        # Default mode: Standard credential chain (tries everything)
        return DefaultAzureCredential()

project_client = AIProjectClient(
    endpoint=user_endpoint,
    credential=get_credential(),
)

# Creates an agent, bumps the agent version if parameters have changed
agent = project_client.agents.create_version(  
    agent_name=agent_name,
    definition=PromptAgentDefinition(
            model=model_deployment_name,
            instructions="You are a storytelling agent. You craft engaging one-line stories based on user prompts and context.",
        ),
)

openai_client = project_client.get_openai_client()

# Reference the agent to get a response
response = openai_client.responses.create(
    input=[{"role": "user", "content": "Tell me a one line story"}],
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)

print(f"Response output: {response.output_text}")