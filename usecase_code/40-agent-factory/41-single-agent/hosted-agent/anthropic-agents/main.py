import os

from anthropic import AsyncAnthropicFoundry
from azure.identity.aio import get_bearer_token_provider

from hosted_common import TOKEN_SCOPE, credential, model_name, resource_endpoint, serve


async def run(spec, messages):
    # This is the Anthropic Python Messages SDK, not Claude Code/Agent SDK.
    # The latter has a different runtime/licensing contract and is not substituted here.
    if any(os.environ.get(key) for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY")):
        raise ValueError("Remove Anthropic API keys; this worker accepts Entra identity only.")
    async with credential() as identity:
        async with AsyncAnthropicFoundry(
            base_url=resource_endpoint() + "/anthropic",
            azure_ad_token_provider=get_bearer_token_provider(identity, TOKEN_SCOPE),
            timeout=60, max_retries=1,
        ) as client:
            response = await client.messages.create(
                model=model_name(spec), system=spec["instructions"],
                messages=messages, max_tokens=2048,
            )
            if response.stop_reason not in {"end_turn", "stop_sequence"}:
                raise RuntimeError(f"Claude response did not complete: {response.stop_reason}")
            return "\n".join(part.text for part in response.content if part.type == "text")


if __name__ == "__main__":
    serve(run)
