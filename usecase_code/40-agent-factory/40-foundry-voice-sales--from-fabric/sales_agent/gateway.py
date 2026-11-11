"""Persisted, version-bound Foundry prompt-agent runtime adapter."""

import asyncio
from contextlib import asynccontextmanager

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import AgentReference, FunctionTool, PromptAgentDefinition
from azure.core.exceptions import AzureError
from openai import OpenAIError

from .contracts import BASE_INSTRUCTIONS, FUNCTION_TOOL, SalesError


@asynccontextmanager
async def _boundary():
    try:
        async with asyncio.timeout(120):
            yield
    except (AzureError, OpenAIError, TimeoutError) as error:
        status = getattr(error, "status_code", None)
        if status in (401, 403):
            raise SalesError(
                "foundry_authorization_failed",
                "Foundry denied access. Verify the signed-in user's permissions and authentication; "
                "interactive claims challenges cannot be completed by this server.",
                403,
            ) from None
        raise SalesError(
            "foundry_request_failed",
            "The Foundry agent request failed. No alternate identity or model was used.",
            502,
        ) from None


class FoundryGateway:
    def __init__(self, settings, credential):
        self.settings = settings
        self.credential = credential
        self._project = None
        self._openai = None

    def _project_client(self):
        if self._project is None:
            self._project = AIProjectClient(
                endpoint=self.settings.project_endpoint, credential=self.credential,
                retry_total=0,
            )
        return self._project

    def _runtime_client(self):
        if self._openai is None:
            self._openai = self._project_client().get_openai_client(max_retries=0)
        return self._openai

    def _instructions(self):
        return BASE_INSTRUCTIONS + "\n" + self.settings.domain_instructions()

    async def validate_agent(self):
        async with _boundary():
            version = await self._project_client().agents.get_version(
                agent_name=self.settings.agent_name, agent_version=self.settings.agent_version
            )
        definition = version.definition.as_dict()
        status = getattr(version, "status", None)
        if (
            version.name != self.settings.agent_name
            or version.version != self.settings.agent_version
            or definition.get("kind") != "prompt"
            or definition.get("tools") != [FUNCTION_TOOL]
            or definition.get("skills")
            or definition.get("harness")
            or (status is not None and status != "active")
        ):
            raise SalesError(
                "agent_definition_rejected",
                "The selected Foundry agent version must be an active prompt agent with exactly "
                "the reviewed query_sales_data function, no skills, and no custom execution harness.",
                503,
            )
        warnings = []
        if self.settings.model_deployment and definition.get("model") != self.settings.model_deployment:
            warnings.append("Published model deployment differs from the local publication setting.")
        if definition.get("instructions") != self._instructions():
            warnings.append("Published instructions differ from the local publication instructions.")
        return {
            "name": version.name, "version": version.version, "kind": "prompt",
            "tools": ["query_sales_data"], "warnings": warnings,
        }

    async def create_conversation(self):
        await self.validate_agent()
        async with _boundary():
            conversation = await self._runtime_client().conversations.create()
        return conversation.id

    async def respond(self, conversation, items, *, force_tool):
        async with _boundary():
            response = await self._runtime_client().responses.create(
                conversation=conversation,
                input=items,
                extra_body={
                    "agent_reference": AgentReference(
                        name=self.settings.agent_name, version=self.settings.agent_version
                    ).as_dict()
                },
                tool_choice=(
                    {"type": "function", "name": "query_sales_data"} if force_tool else "auto"
                ),
                parallel_tool_calls=False,
                max_output_tokens=4096,
            )
        return response.model_dump(mode="json")

    async def publish(self):
        definition = PromptAgentDefinition(
            model=self.settings.model_deployment,
            instructions=self._instructions(),
            tools=[FunctionTool(**{key: value for key, value in FUNCTION_TOOL.items() if key != "type"})],
        )
        async with _boundary():
            version = await self._project_client().agents.create_version(
                agent_name=self.settings.agent_name, definition=definition
            )
        return {"name": version.name, "version": version.version}

    async def close(self):
        try:
            if self._openai is not None:
                await self._openai.close()
        finally:
            if self._project is not None:
                await self._project.close()
