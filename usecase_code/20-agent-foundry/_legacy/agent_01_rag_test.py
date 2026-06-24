"""
AI Foundry V2 Agent with AI Search Tool
========================================

Architecture: AI Foundry V2 (account + project, no Hub)
  Resource type : Microsoft.CognitiveServices/accounts
    Account       : <account-name-from-env>
    Project       : <project-name-from-env>
    Account URL   : <account-endpoint-from-env>
    Project URL   : <project-endpoint-from-env>

Two-phase workflow
------------------
Phase 1 – Index ./data/Joakim.md into Azure AI Search
  • Parses the markdown into per-header chunks
  • Generates vector embeddings with text-embedding-3-large
    (deployed on the AI Foundry account – RBAC, no key)
  • Creates / recreates the search index with HNSW vector support
  • Uploads the chunks + embeddings to AI Search

Phase 2 – Create an AI Foundry Agent backed by AI Search
  • Creates the agent with system instructions:
      "If asked about Robot-Joakim, always use the AI Search tool"
  • Attaches the AI Search tool (vector-semantic-hybrid queries)
  • Sends the query "How to reset Robot-Joakim?" and prints the answer
  • Cleans up (deletes agent + thread)

Authentication: DefaultAzureCredential (RBAC only – no account keys).
  RBAC scope for inference: https://cognitiveservices.azure.com/.default
  (AI Foundry V2 accounts are Microsoft.CognitiveServices resources)

Required packages
-----------------
  pip install azure-ai-agents azure-ai-projects azure-search-documents azure-identity openai
"""

import argparse
import os
import random
import string
import sys
import time
from pathlib import Path

from azure.identity import DefaultAzureCredential

# Agent Service SDK  (threads / messages / runs)
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    AzureAISearchTool,
    AzureAISearchQueryType,
    AgentsNamedToolChoice,
    AgentsNamedToolChoiceType,
    MessageRole,
)

# AI Foundry project client  (connections + OpenAI inference)
from azure.ai.projects import AIProjectClient
from azure.identity import get_bearer_token_provider
from openai import AzureOpenAI
from dotenv import load_dotenv

# AI Search SDK
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
)

# ============================================================================
# Configuration  (sourced from aifactory-usecase-config.yaml)
# ============================================================================

_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR.parent / ".env")


def _env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    return None if value == "<TODO>" else value


def _env_int(key: str, default: str | None = None) -> int | None:
    value = _env(key, default)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {key} must be an integer; got '{value}'") from exc


SUBSCRIPTION_ID        = _env("SUBSCRIPTION_ID", "<TODO>")
TENANT_ID              = _env("TENANT_ID", "<TODO>")
RESOURCE_GROUP         = _env("RESOURCE_GROUP", "<TODO>")

# AI Foundry V2 –  account endpoint  (Microsoft.CognitiveServices/accounts)
# Models are deployed at the account level; no Hub in V2.
FOUNDRY_ACCOUNT_ENDPOINT = _env("FOUNDRY_ACCOUNT_ENDPOINT", "<TODO>")

# AI Foundry V2 – project endpoint  (child of the account)
FOUNDRY_PROJECT_ENDPOINT = _env("FOUNDRY_PROJECT_ENDPOINT", "<TODO>")

# Azure AI Search
AI_SEARCH_NAME         = _env("AI_SEARCH_NAME", "<TODO>")
AI_SEARCH_ENDPOINT     = f"https://{AI_SEARCH_NAME}.search.windows.net"
AI_SEARCH_INDEX_NAME   = _env("AI_SEARCH_INDEX_NAME", "<TODO>")

# Models
EMBEDDING_MODEL        = _env("EMBEDDING_MODEL", "<TODO>")
EMBEDDING_DIMENSIONS   = _env_int("EMBEDDING_DIMENSIONS", "<TODO>")
CHAT_MODEL             = _env("CHAT_MODEL", "<TODO>")

# Agent
AGENT_NAME             = _env("AGENT_NAME", "<TODO>")
AGENT_INSTRUCTIONS     = _env(
    "AGENT_INSTRUCTIONS",
    "<TODO>",
)
FIRST_PROMPT           = _env("FIRST_PROMPT", "<TODO>")

# Data file (this script lives in usecase_code/agent_foundry/)
DATA_FILE = Path(__file__).parent.parent / "data" / "Joakim.md"


# ============================================================================
# Phase 1 helpers: markdown parsing, index creation, document upload
# ============================================================================

def parse_markdown_chunks(filepath: Path) -> list[dict]:
    """Split markdown into chunks at every H1 / H2 heading."""
    text = filepath.read_text(encoding="utf-8")
    chunks: list[dict] = []
    current_title = filepath.stem
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("# "):
            # Flush previous chunk
            content = "\n".join(current_lines).strip()
            if content:
                chunks.append(
                    {
                        "id": f"chunk-{len(chunks)}",
                        "title": current_title,
                        "content": content,
                        "source": filepath.name,
                    }
                )
            current_title = line.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush final chunk
    content = "\n".join(current_lines).strip()
    if content:
        chunks.append(
            {
                "id": f"chunk-{len(chunks)}",
                "title": current_title,
                "content": content,
                "source": filepath.name,
            }
        )

    return chunks


def create_or_replace_search_index(
    index_client: SearchIndexClient, index_name: str
) -> None:
    """Delete (if exists) and create an AI Search index with vector support."""
    fields = [
        SimpleField(
            name="id", type=SearchFieldDataType.String, key=True, filterable=True
        ),
        SimpleField(
            name="source", type=SearchFieldDataType.String, filterable=True
        ),
        SearchableField(name="title",   type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="contentVector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="hnsw-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-algo")],
        profiles=[
            VectorSearchProfile(
                name="hnsw-profile",
                algorithm_configuration_name="hnsw-algo",
                # Tie the profile to the vectorizer so AI Search can vectorize
                # at query-time without a separate embedding call.
                vectorizer_name="openai-vectorizer",
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    # V2: account endpoint, no Hub path
                    resource_url=FOUNDRY_ACCOUNT_ENDPOINT,
                    deployment_name=EMBEDDING_MODEL,
                    model_name=EMBEDDING_MODEL,
                ),
            )
        ],
    )

    index = SearchIndex(
        name=index_name, fields=fields, vector_search=vector_search
    )

    try:
        index_client.delete_index(index_name)
        print(f"    Deleted existing index '{index_name}'")
    except Exception:
        pass  # Index didn't exist yet – that's fine

    index_client.create_index(index)
    print(f"    Created index '{index_name}'")


def upload_chunks_with_embeddings(chunks: list[dict], openai_client, search_client: SearchClient) -> None:
    """Embed each chunk and batch-upload to AI Search."""
    documents = []
    for chunk in chunks:
        print(f"    Embedding: [{chunk['id']}] '{chunk['title']}'")
        response = openai_client.embeddings.create(
            input=chunk["content"],
            model=EMBEDDING_MODEL,
        )
        documents.append(
            {
                "id":            chunk["id"],
                "title":         chunk["title"],
                "content":       chunk["content"],
                "source":        chunk["source"],
                "contentVector": response.data[0].embedding,
            }
        )

    results = search_client.upload_documents(documents=documents)
    succeeded = sum(1 for r in results if r.succeeded)
    print(f"    Uploaded {len(documents)} docs – {succeeded} succeeded")


# ============================================================================
# Phase 2 helpers: resolve AI Search connection inside the AI Foundry project
# ============================================================================

def resolve_search_connection_name(project_client: AIProjectClient) -> str:
    """
    Return the AI Search connection *name* registered in the AI Foundry project.
    The azure-ai-agents AzureAISearchTool expects the connection *name*
    (Connection.name), not the full resource ID.
    Falls back to AI_SEARCH_NAME if no matching connection is found.
    """
    try:
        for conn in project_client.connections.list():
            # conn.type == 'CognitiveSearch' for Azure AI Search connections
            # conn.target holds the endpoint URL, e.g. https://<name>.search.windows.net
            target = getattr(conn, "target", "") or ""
            conn_type = getattr(conn, "type", "") or ""
            if AI_SEARCH_NAME in target.lower() or "cognitivesearch" in conn_type.lower():
                print(f"    Matched connection: name='{conn.name}' type='{conn_type}' target='{target}'")
                return conn.name
    except Exception as exc:
        print(f"    Warning – could not list connections: {exc}")

    print(f"    Falling back to connection name: {AI_SEARCH_NAME}")
    return AI_SEARCH_NAME


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    print("=" * 64)
    print("  AI Foundry Agent  ×  AI Search Tool")
    print("  Data: Joakim.md   |  Query: How to reset Robot-Joakim?")
    print("=" * 64)

    # ------------------------------------------------------------------
    # 1. Credential – RBAC only, no account keys
    # ------------------------------------------------------------------
    print("\n[1] Building DefaultAzureCredential (RBAC, no keys)…")
    credential = DefaultAzureCredential(
        additionally_allowed_tenants=[TENANT_ID],
        exclude_interactive_browser_credential=False,
    )

    # ------------------------------------------------------------------
    # Reindex prompt  (--reindex / --no-reindex flags, or interactive)
    # ------------------------------------------------------------------
    _parser = argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--reindex", dest="reindex", action="store_true", default=None)
    _parser.add_argument("--no-reindex", dest="reindex", action="store_false")
    _args, _ = _parser.parse_known_args()

    if _args.reindex is None:
        # Interactive fallback (used when run directly from a real terminal)
        try:
            reindex = input("\nReindex? (y/n): ").strip().lower()
            do_reindex = reindex == "y"
        except (EOFError, KeyboardInterrupt):
            do_reindex = False
            print("\nReindex: no (non-interactive, defaulting to skip)")
    else:
        do_reindex = _args.reindex
        print(f"\nReindex: {'yes' if do_reindex else 'no'} (CLI flag)")

    # ------------------------------------------------------------------
    # 2. AI Foundry project client  (used for connections + OpenAI client)
    # ------------------------------------------------------------------
    print(f"\n[2] Connecting to AI Foundry project…")
    print(f"    {FOUNDRY_PROJECT_ENDPOINT}")
    project_client = AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=credential,
    )

    # ------------------------------------------------------------------
    # 3. Azure OpenAI client (RBAC) – for embedding generation
    #    AI Foundry V2: models are deployed at the *account* level.
    #    Scope: https://cognitiveservices.azure.com/.default
    #    (the account is a Microsoft.CognitiveServices resource, not AML)
    # ------------------------------------------------------------------
    if do_reindex:
        print("\n[3] Building AzureOpenAI client for embeddings…")
        print(f"    Account endpoint: {FOUNDRY_ACCOUNT_ENDPOINT}")
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        openai_client = AzureOpenAI(
            azure_endpoint=FOUNDRY_ACCOUNT_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version="2024-10-21",
        )

        # ------------------------------------------------------------------
        # 4. Parse Joakim.md
        # ------------------------------------------------------------------
        print(f"\n[4] Parsing {DATA_FILE.name}…")
        if not DATA_FILE.exists():
            raise FileNotFoundError(f"Data file missing: {DATA_FILE}")
        chunks = parse_markdown_chunks(DATA_FILE)
        print(f"    {len(chunks)} chunk(s) found:")
        for c in chunks:
            print(f"      [{c['id']}] {c['title']}")

        # ------------------------------------------------------------------
        # 5. Create / replace AI Search index
        # ------------------------------------------------------------------
        print(f"\n[5] Setting up AI Search index '{AI_SEARCH_INDEX_NAME}'…")
        index_client = SearchIndexClient(
            endpoint=AI_SEARCH_ENDPOINT,
            credential=credential,
        )
        create_or_replace_search_index(index_client, AI_SEARCH_INDEX_NAME)

        # ------------------------------------------------------------------
        # 6. Generate embeddings and upload documents
        # ------------------------------------------------------------------
        print(f"\n[6] Indexing chunks with '{EMBEDDING_MODEL}'…")
        search_client = SearchClient(
            endpoint=AI_SEARCH_ENDPOINT,
            index_name=AI_SEARCH_INDEX_NAME,
            credential=credential,
        )
        upload_chunks_with_embeddings(chunks, openai_client, search_client)

        print("    Waiting 15 s for the indexer to settle…")
        time.sleep(15)
    else:
        print("\n[3-6] Skipping reindex – using existing index.")

    # ------------------------------------------------------------------
    # 7. Resolve AI Search connection name in project
    # ------------------------------------------------------------------
    print("\n[7] Resolving AI Search connection in AI Foundry project…")
    search_connection_name = resolve_search_connection_name(project_client)

    # ------------------------------------------------------------------
    # 8. Create AI Foundry Agent with AI Search tool
    #    Uses AgentsClient (azure-ai-agents) – the dedicated agent SDK
    # ------------------------------------------------------------------
    _salt = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    agent_name = f"{AGENT_NAME}-{_salt}"
    print(f"\n[8] Creating agent '{agent_name}'…")
    agents_client = AgentsClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=credential,
    )

    ai_search_tool = AzureAISearchTool(
        index_connection_id=search_connection_name,
        index_name=AI_SEARCH_INDEX_NAME,
        query_type=AzureAISearchQueryType.VECTOR,  # Basic tier compatible (no semantic ranker needed)
        top_k=3,
    )

    agent = agents_client.create_agent(
        model=CHAT_MODEL,
        name=agent_name,
        instructions=AGENT_INSTRUCTIONS,
        tools=ai_search_tool.definitions,
        tool_resources=ai_search_tool.resources,
    )
    print(f"    Agent id: {agent.id}")

    # ------------------------------------------------------------------
    # 9. Create thread + send user message
    # ------------------------------------------------------------------
    print("\n[9] Creating conversation thread…")
    thread = agents_client.threads.create()
    print(f"    Thread id: {thread.id}")

    print(f"\n[10] Sending: '{FIRST_PROMPT}'")
    agents_client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=FIRST_PROMPT,
    )

    # ------------------------------------------------------------------
    # 10. Run agent (blocking – create_and_process polls until terminal)
    # ------------------------------------------------------------------
    print("    Running agent…")
    run = agents_client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id,
        tool_choice=AgentsNamedToolChoice(type=AgentsNamedToolChoiceType.AZURE_AI_SEARCH),
    )
    print(f"    Run status: {run.status}")

    # ------------------------------------------------------------------
    # 10b. Diagnostic – print run steps to see if the tool was called
    # ------------------------------------------------------------------
    print("\n    Run steps:")
    for step in agents_client.run_steps.list(thread_id=thread.id, run_id=run.id):
        step_detail = getattr(step.step_details, "tool_calls", None)
        if step_detail:
            for tc in step_detail:
                tc_type = getattr(tc, "type", "?")
                tc_id   = getattr(tc, "id", "?")
                print(f"      tool_call [{tc_type}] id={tc_id}")
                if hasattr(tc, "azure_ai_search"):
                    print(f"        input : {getattr(tc.azure_ai_search, 'input', '?')}")
                    print(f"        output: {str(getattr(tc.azure_ai_search, 'output', '?'))[:300]}")
        else:
            print(f"      step type={step.type} status={step.status}")

    # ------------------------------------------------------------------
    # 11. Print agent response + citations
    # ------------------------------------------------------------------
    print("\n[11] Agent answer:")
    print("-" * 64)

    # Get the full last agent message (includes content parts + annotations)
    last_msg = agents_client.messages.get_last_message_text_by_role(
        thread_id=thread.id,
        role=MessageRole.AGENT,
    )

    if last_msg:
        print(last_msg.text.value)

        # ---- Citations -----------------------------------------------
        annotations = getattr(last_msg.text, "annotations", []) or []
        if annotations:
            print()
            print("Sources:")
            seen: set[str] = set()
            for ann in annotations:
                marker  = getattr(ann, "text", "")          # e.g. 【3:0†source】
                ann_type = type(ann).__name__

                # AI Search citations come back as URL citations
                url_cit = getattr(ann, "url_citation", None)
                if url_cit:
                    url   = getattr(url_cit, "url",   "") or ""
                    title = getattr(url_cit, "title", "") or url
                    entry = f"  {marker}  {title}  {url}"
                    if entry not in seen:
                        seen.add(entry)
                        print(entry)
                    continue

                # File citations (vector store / file search)
                file_cit = getattr(ann, "file_citation", None)
                if file_cit:
                    file_id = getattr(file_cit, "file_id", "?") or "?"
                    quote   = getattr(file_cit, "quote",   "") or ""
                    entry   = f"  {marker}  file_id={file_id}"
                    if quote:
                        entry += f'  quote="{quote[:120]}"'
                    if entry not in seen:
                        seen.add(entry)
                        print(entry)
                    continue

                # Fallback – print raw annotation
                entry = f"  {marker}  [{ann_type}] {ann}"
                if entry not in seen:
                    seen.add(entry)
                    print(entry)
        else:
            print("\n(no citations returned)")
    else:
        print("(no response)")

    print("-" * 64)

    # ------------------------------------------------------------------
    # 12. Cleanup (optional)
    # ------------------------------------------------------------------
    try:
        cleanup = input("\nWould you like to delete the agent and clean up the thread? (y/n): ").strip().lower()
        do_cleanup = cleanup == "y"
    except (EOFError, KeyboardInterrupt):
        do_cleanup = True
        print("\nCleanup: yes (non-interactive default)")

    if do_cleanup:
        print("\n[12] Cleaning up…")
        agents_client.delete_agent(agent.id)
        print(f"    Deleted agent  : {agent.id}")
        agents_client.threads.delete(thread.id)
        print(f"    Deleted thread : {thread.id}")
    else:
        print(f"\n[12] Skipping cleanup.")
        print(f"    Agent  : {agent.id}  ({agent_name})")
        print(f"    Thread : {thread.id}")

    print("\nDone ✓")


if __name__ == "__main__":
    main()
