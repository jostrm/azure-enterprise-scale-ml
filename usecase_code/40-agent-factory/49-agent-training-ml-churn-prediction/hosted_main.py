"""Foundry hosted-agent entry point for example 49 (packaged as main.py by `hosted-package`).

Serves the Responses protocol so the Foundry Playground can talk to the agent. Each turn runs
ml_agent.hosted.HostedAgent in a worker thread with the sandbox's own agent identity.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile

os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
# The package folder may be read-only; never let MLflow create ./mlruns there.
os.environ.setdefault("MLFLOW_TRACKING_URI", (Path(tempfile.gettempdir()) / "aif49-mlruns").as_uri())

SERVER_SECONDS = 300
GREETING = ("I train and score the AI Factory ML use cases: M49 synthetic telco churn (created from the factory "
            "template) and the existing M05 air-passengers model. Ask me for their status, or to plan a run.")
BUSY = "An earlier operation is still running in the background; ask me for the status in a minute."


def main() -> None:
    from azure.ai.agentserver.responses import ResponsesAgentServerHost, ResponsesServerOptions, TextResponse

    from ml_agent.hosted import MAX_HISTORY_ITEMS, HostedAgent
    from ml_agent.runtime import redact

    agent = HostedAgent.from_environment()
    serial = asyncio.Lock()
    inflight: dict = {"work": None}
    app = ResponsesAgentServerHost(options=ResponsesServerOptions(default_fetch_history_count=MAX_HISTORY_ITEMS))

    def safe_turn(text: str, history: list, user: str | None, conversation: str | None) -> str:
        try:
            return agent.turn(text, history, user=user, conversation_id=conversation)
        except Exception as error:  # surface a redacted reason instead of an opaque server error
            return redact(f"The hosted agent could not finish this turn: {type(error).__name__}: {error}")[:2000]

    @app.response_handler
    async def respond(request, context, cancellation_signal: asyncio.Event):
        current = await context.get_input_text() or ""
        if not current.strip():
            return TextResponse(context, request, text=GREETING)
        history = list(await context.get_history() or [])
        user = getattr(getattr(context, "platform_context", None), "user_id_key", None)
        conversation = getattr(context, "conversation_chain_id", None)
        async with serial:
            previous = inflight["work"]
            if previous is not None and not previous.done():
                # Never start a second worker while an earlier, timed-out turn still runs.
                await asyncio.wait({previous}, timeout=SERVER_SECONDS)
                if not previous.done():
                    return TextResponse(context, request, text=BUSY)
            work = asyncio.ensure_future(asyncio.to_thread(safe_turn, current, history, user, conversation))
            inflight["work"] = work
            done, _ = await asyncio.wait({work}, timeout=SERVER_SECONDS)
            text = work.result() if work in done else BUSY
        return TextResponse(context, request, text=text)

    app.run()


if __name__ == "__main__":
    main()
