from agent_framework import Agent, Message
from agent_framework_openai import OpenAIChatClient

from hosted_common import credential, model_name, openai_client, serve


async def run(spec, messages):
    async with credential() as identity, openai_client(identity) as client:
        agent = Agent(
            client=OpenAIChatClient(model=model_name(spec), async_client=client),
            name=spec["name"], instructions=spec["instructions"],
            default_options={"store": False, "max_tokens": 2048},
        )
        result = await agent.run([
            Message(role=item["role"], contents=[item["content"]]) for item in messages
        ])
        return result.text


if __name__ == "__main__":
    serve(run)
