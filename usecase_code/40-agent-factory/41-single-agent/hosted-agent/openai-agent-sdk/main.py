from agents import Agent, ModelSettings, OpenAIResponsesModel, Runner, set_tracing_disabled

from hosted_common import credential, model_name, openai_client, serve

set_tracing_disabled(True)


async def run(spec, messages):
    async with credential() as identity, openai_client(identity) as client:
        agent = Agent(
            name=spec["name"], instructions=spec["instructions"],
            model=OpenAIResponsesModel(model=model_name(spec), openai_client=client),
            model_settings=ModelSettings(store=False, max_tokens=2048),
        )
        result = await Runner.run(agent, input=messages, max_turns=4)
        return str(result.final_output)


if __name__ == "__main__":
    serve(run)
