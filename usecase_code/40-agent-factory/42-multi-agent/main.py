from azure.ai.projects.aio import AIProjectClient

from hosted_common import append_sources, consult_member, credential, model_name, project_endpoint, serve, with_evidence


async def run(spec, messages):
    async with credential() as identity:
        async with AIProjectClient(endpoint=project_endpoint(), credential=identity) as project:
            findings = []
            for member in spec["members"]:
                async with project.get_openai_client(timeout=60, max_retries=1) as client:
                    findings.append(
                        await consult_member(
                            client, member, with_evidence(messages, findings),
                            private_tools=spec.get("private_tools"),
                        )
                    )
            synthesis_input = with_evidence(messages, findings)
            async with project.get_openai_client(timeout=60, max_retries=1) as client:
                result = await client.responses.create(
                    model=model_name(spec), instructions=spec["instructions"],
                    input=synthesis_input, store=False, max_output_tokens=3072,
                )
                if result.status != "completed":
                    raise RuntimeError(f"Coordinator synthesis did not complete: {result.status}")
                return append_sources(result.output_text, findings)


if __name__ == "__main__":
    serve(run)
