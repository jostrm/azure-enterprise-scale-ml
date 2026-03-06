"""
01_router_agent_salt.py
========================
Router Agent – first responder to the user query.

Decides which specialist to call:
  • CODING_AGENT  – data analysis, calculations, code, charts, visualisations
  • RAG_AGENT     – Robot-Joakim questions (resets, hardware, manual)

Exports
-------
  ROUTER_AGENT_NAME_PREFIX  : str
  ROUTER_AGENT_INSTRUCTIONS : str
  create_agent(agents_client, model, agent_name) -> agent object
"""

from azure.ai.agents import AgentsClient

# ── Identity ──────────────────────────────────────────────────────────────
ROUTER_AGENT_NAME_PREFIX = "RouterAgent"

# ── Instructions ──────────────────────────────────────────────────────────
ROUTER_AGENT_INSTRUCTIONS = """
You are a routing orchestrator. Your ONLY job is to read the user query and
decide which specialist agent should handle it.

Routing rules
─────────────
• Route to CODING_AGENT for:
    - Data analysis, statistics, math or calculations
    - Generating charts, plots, visualisations (bar chart, pie chart, etc.)
    - Writing, running or explaining Python / any programming code
    - Any request that benefits from executing code

• Route to RAG_AGENT for:
    - Anything about Robot-Joakim (resets, factory reset, hardware, manual,
      battery, specifications, troubleshooting, behaviour)
    - Questions best answered by looking up a document or knowledge base

Response format – STRICT
─────────────────────────
Respond with ONLY a single JSON object, no markdown fences, no extra text:

{"route": "CODING_AGENT", "reason": "<one sentence>"}
  – or –
{"route": "RAG_AGENT",    "reason": "<one sentence>"}
""".strip()


# ── Factory ───────────────────────────────────────────────────────────────
def create_agent(agents_client: AgentsClient, model: str, agent_name: str):
    """
    Create and return a router agent.

    Parameters
    ----------
    agents_client : AgentsClient
    model         : deployment name of the chat model
    agent_name    : fully-qualified name including salt, e.g. 'RouterAgent-abc12'
    """
    agent = agents_client.create_agent(
        model=model,
        name=agent_name,
        instructions=ROUTER_AGENT_INSTRUCTIONS,
    )
    return agent
