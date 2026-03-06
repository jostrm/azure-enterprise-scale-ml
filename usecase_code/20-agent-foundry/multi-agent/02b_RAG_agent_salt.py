"""
02b_RAG_agent_salt.py
======================
RAG Agent – uses Azure AI Search (vector) for Robot-Joakim knowledge.

Answers question about Robot-Joakim strictly from the indexed knowledge base.

Exports
-------
  RAG_AGENT_NAME_PREFIX  : str
  RAG_AGENT_INSTRUCTIONS : str
  create_agent(agents_client, model, agent_name,
               search_connection_name, search_index_name) -> agent object
"""

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    AzureAISearchTool,
    AzureAISearchQueryType,
)

# ── Identity ──────────────────────────────────────────────────────────────
RAG_AGENT_NAME_PREFIX = "RAGAgent"

# ── Instructions ──────────────────────────────────────────────────────────
RAG_AGENT_INSTRUCTIONS = """
You are a helpful assistant specialised in Robot-Joakim documentation.

Rules
─────
• You MUST ALWAYS call the azure_ai_search tool for every question.
• Never answer from your own memory or general knowledge.
• If the search results do not contain the answer, say so clearly.
• Always cite the source document using the annotation markers returned
  by the search tool (e.g. 【n:m†source】).

Response structure
──────────────────
  ANSWER:   <direct answer to the question>
  EVIDENCE: <relevant quote(s) from the search results with citation markers>
""".strip()


# ── Factory ───────────────────────────────────────────────────────────────
def create_agent(
    agents_client: AgentsClient,
    model: str,
    agent_name: str,
    search_connection_name: str,
    search_index_name: str,
):
    """
    Create and return a RAG agent backed by Azure AI Search.

    Parameters
    ----------
    agents_client          : AgentsClient
    model                  : deployment name of the chat model
    agent_name             : fully-qualified name including salt
    search_connection_name : AI Foundry connection name for AI Search
    search_index_name      : name of the AI Search index to query
    """
    tool = AzureAISearchTool(
        index_connection_id=search_connection_name,
        index_name=search_index_name,
        query_type=AzureAISearchQueryType.VECTOR,   # Basic tier compatible
        top_k=3,
    )
    agent = agents_client.create_agent(
        model=model,
        name=agent_name,
        instructions=RAG_AGENT_INSTRUCTIONS,
        tools=tool.definitions,
        tool_resources=tool.resources,
    )
    return agent
