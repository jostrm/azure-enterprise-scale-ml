from hosted_common import credential, model_name, openai_client, serve


async def run(spec, messages):
    async with credential() as identity, openai_client(identity) as client:
        result = await client.responses.create(
            model=model_name(spec), instructions=spec["instructions"],
            input=messages, store=False, max_output_tokens=2048,
        )
        if result.status != "completed":
            raise RuntimeError(f"Model response did not complete: {result.status}")
        return result.output_text


if __name__ == "__main__":
    serve(run)
