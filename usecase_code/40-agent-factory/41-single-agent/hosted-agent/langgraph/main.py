from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from hosted_common import credential, model_name, openai_client, serve


class State(TypedDict):
    messages: list[dict[str, str]]
    answer: str


async def run(spec, messages):
    async with credential() as identity, openai_client(identity) as client:
        async def infer(state: State):
            response = await client.responses.create(
                model=model_name(spec), instructions=spec["instructions"],
                input=state["messages"], store=False, max_output_tokens=2048,
            )
            if response.status != "completed":
                raise RuntimeError(f"Model response did not complete: {response.status}")
            return {"answer": response.output_text}

        graph = StateGraph(State)
        graph.add_node("foundry_model", infer)
        graph.add_edge(START, "foundry_model")
        graph.add_edge("foundry_model", END)
        # Platform history is authoritative; no process-global checkpointer can leak
        # one user's conversation into another or survive a host restart reliably.
        result = await graph.compile().ainvoke(
            {"messages": messages, "answer": ""}, config={"recursion_limit": 4},
        )
        return result["answer"]


if __name__ == "__main__":
    serve(run)
