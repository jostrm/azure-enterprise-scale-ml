# Ask the data-sources agent a question in a new conversation

import argparse

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

from agents import load_settings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask the data-sources agent a question")
    parser.add_argument("question", nargs="+")
    question = " ".join(parser.parse_args(argv).question)
    settings = load_settings()
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=settings["endpoint"], credential=credential, allow_preview=True) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        conversation = openai_client.conversations.create()
        response = openai_client.responses.create(
            conversation=conversation.id,
            input=question,
            extra_body={"agent_reference": {"name": settings["agent_name"], "type": "agent_reference"}},
        )
        print(response.output_text)


if __name__ == "__main__":
    main()
