# Ask the workflow (default) or one agent (--agent <name>) a question in a new conversation

import argparse

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

from agents import load_settings

WORKFLOW = "FoundryIQ-Workflow"


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", default=WORKFLOW, help=f"agent or workflow name (default {WORKFLOW})")
    parser.add_argument("question", nargs="+")
    args = parser.parse_args(argv)
    return args.agent, " ".join(args.question)


def answer(response):
    # A workflow returns one message per agent it ran (Supervisor-Agent first): print the last one
    last = [item for item in response.output if item.type == "message"][-1]
    agent = (getattr(last, "agent_reference", None) or {}).get("name", "")
    text = "".join(part.text for part in last.content if hasattr(part, "text"))
    return f"[{agent}] {text}" if agent else text


def main():
    agent, question = parse()
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
            extra_body={"agent_reference": {"name": agent, "type": "agent_reference"}},
        )
        print(answer(response))


if __name__ == "__main__":
    main()
