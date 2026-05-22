"""
Prompt Agent (Responses API) + AI Search RAG
============================================

This script mirrors the RAG behavior in agent_01_rag_test.py but uses:
- AIProjectClient.agents.create_version(...)
- PromptAgentDefinition
- OpenAI Responses API via project_client.get_openai_client()
"""

import argparse
import base64
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI

from azure.core.exceptions import ResourceNotFoundError
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)


_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR.parent / ".env")


def _env(key: str, default: str | None = None) -> str | None:
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


FOUNDRY_ACCOUNT_ENDPOINT = _env("FOUNDRY_ACCOUNT_ENDPOINT", "<TODO>")
FOUNDRY_PROJECT_ENDPOINT = _env("FOUNDRY_PROJECT_ENDPOINT", "<TODO>")
AI_SEARCH_NAME = _env("AI_SEARCH_NAME", "<TODO>")
AI_SEARCH_INDEX_NAME = _env("AI_SEARCH_INDEX_NAME", "<TODO>")
CHAT_MODEL = _env("CHAT_MODEL", "<TODO>")
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "<TODO>")
EMBEDDING_DIMENSIONS = _env_int("EMBEDDING_DIMENSIONS", "<TODO>")
AGENT_NAME = _env("AGENT_NAME", "<TODO>")
AGENT_INSTRUCTIONS = _env("AGENT_INSTRUCTIONS", "You are a helpful assistant.")
FIRST_PROMPT = _env("FIRST_PROMPT", "How to reset Robot-Joakim?")

AI_SEARCH_ENDPOINT = f"https://{AI_SEARCH_NAME}.search.windows.net"
DATA_FILE = _BASE_DIR.parent / "data" / "Joakim.md"


def _is_truthy(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_credential():
    auth_mode = os.getenv("AUTH_MODE", "").lower()

    if auth_mode in ["uami", "mi"]:
        managed_identity_client_id = os.getenv("AZURE_CLIENT_ID")
        allow_user_fallback = _is_truthy(os.getenv("UAMI_FALLBACK_TO_USER"), default=True)
        if not managed_identity_client_id:
            raise ValueError("AZURE_CLIENT_ID environment variable required for UAMI authentication mode")

        if allow_user_fallback:
            print("AUTH_MODE=uami: managed identity preferred; user credential fallback enabled")
            return DefaultAzureCredential(
                managed_identity_client_id=managed_identity_client_id,
                exclude_environment_credential=True,
                exclude_workload_identity_credential=True,
            )

        print("AUTH_MODE=uami: managed identity only (no user fallback)")
        return DefaultAzureCredential(
            managed_identity_client_id=managed_identity_client_id,
            exclude_cli_credential=True,
            exclude_powershell_credential=True,
            exclude_developer_cli_credential=True,
            exclude_interactive_browser_credential=True,
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_environment_credential=True,
            exclude_workload_identity_credential=True,
        )

    if auth_mode in ["user", "interactive"]:
        return DefaultAzureCredential(
            exclude_managed_identity_credential=True,
            exclude_workload_identity_credential=True,
            exclude_environment_credential=True,
        )

    return DefaultAzureCredential()


def log_resolved_identity(credential, scope="https://management.azure.com/.default"):
    try:
        token = credential.get_token(scope).token
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))

        print("Resolved Azure identity from DefaultAzureCredential:")
        print(f"  oid: {claims.get('oid')}")
        print(f"  upn: {claims.get('upn')}")
        print(f"  tid: {claims.get('tid')}")
        print(f"  appid: {claims.get('appid')}")
    except Exception as ex:
        print("Resolved Azure identity from DefaultAzureCredential: <unavailable>")
        print(f"  reason: {ex}")


def parse_markdown_chunks(filepath: Path) -> list[dict]:
    text = filepath.read_text(encoding="utf-8")
    chunks: list[dict] = []
    current_title = filepath.stem
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("# "):
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


def create_or_replace_search_index(index_client: SearchIndexClient, index_name: str) -> None:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
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
                vectorizer_name="openai-vectorizer",
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=FOUNDRY_ACCOUNT_ENDPOINT,
                    deployment_name=EMBEDDING_MODEL,
                    model_name=EMBEDDING_MODEL,
                ),
            )
        ],
    )

    index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)

    try:
        index_client.delete_index(index_name)
        print(f"Deleted existing index '{index_name}'")
    except Exception:
        pass

    index_client.create_index(index)
    print(f"Created index '{index_name}'")


def upload_chunks_with_embeddings(chunks: list[dict], openai_client: AzureOpenAI, search_client: SearchClient) -> None:
    documents = []
    for chunk in chunks:
        print(f"Embedding: [{chunk['id']}] '{chunk['title']}'")
        response = openai_client.embeddings.create(
            input=chunk["content"],
            model=EMBEDDING_MODEL,
        )
        documents.append(
            {
                "id": chunk["id"],
                "title": chunk["title"],
                "content": chunk["content"],
                "source": chunk["source"],
                "contentVector": response.data[0].embedding,
            }
        )

    results = search_client.upload_documents(documents=documents)
    succeeded = sum(1 for r in results if r.succeeded)
    print(f"Uploaded {len(documents)} docs - {succeeded} succeeded")


def ensure_search_index_ready(credential, force_reindex: bool) -> None:
    index_client = SearchIndexClient(endpoint=AI_SEARCH_ENDPOINT, credential=credential)

    should_reindex = force_reindex
    if not force_reindex:
        try:
            index_client.get_index(AI_SEARCH_INDEX_NAME)
            print(f"Using existing AI Search index '{AI_SEARCH_INDEX_NAME}'.")
        except ResourceNotFoundError:
            should_reindex = True
            print(
                f"AI Search index '{AI_SEARCH_INDEX_NAME}' not found. "
                "Creating and populating it now."
            )

    if not should_reindex:
        return

    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    embedding_client = AzureOpenAI(
        azure_endpoint=FOUNDRY_ACCOUNT_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version="2024-10-21",
    )

    chunks = parse_markdown_chunks(DATA_FILE)
    print(f"Found {len(chunks)} chunks in {DATA_FILE.name}")

    create_or_replace_search_index(index_client, AI_SEARCH_INDEX_NAME)

    search_client = SearchClient(
        endpoint=AI_SEARCH_ENDPOINT,
        index_name=AI_SEARCH_INDEX_NAME,
        credential=credential,
    )
    upload_chunks_with_embeddings(chunks, embedding_client, search_client)
    print("Waiting 15s for index to settle...")
    time.sleep(15)


def resolve_search_connection(project_client: AIProjectClient):
    for conn in project_client.connections.list():
        target = (getattr(conn, "target", "") or "").lower()
        conn_type = (getattr(conn, "type", "") or "").lower()
        if AI_SEARCH_NAME.lower() in target or "cognitivesearch" in conn_type:
            print(f"Matched AI Search connection name: {conn.name}")
            return conn
    raise RuntimeError(
        "No Azure AI Search connection found in project. "
        f"Expected one targeting '{AI_SEARCH_NAME}'."
    )


def run_ai_search_health_checks(search_connection, credential) -> None:
    print("Running AI Search health checks...")
    print(f"  connection_name: {getattr(search_connection, 'name', '<unknown>')}")
    print(f"  connection_type: {getattr(search_connection, 'type', '<unknown>')}")
    print(f"  connection_target: {getattr(search_connection, 'target', '<unknown>')}")
    print(f"  search_endpoint: {AI_SEARCH_ENDPOINT}")
    print(f"  index_name: {AI_SEARCH_INDEX_NAME}")

    index_client = SearchIndexClient(endpoint=AI_SEARCH_ENDPOINT, credential=credential)
    search_client = SearchClient(
        endpoint=AI_SEARCH_ENDPOINT,
        index_name=AI_SEARCH_INDEX_NAME,
        credential=credential,
    )

    try:
        index_client.get_index(AI_SEARCH_INDEX_NAME)
        print("  index_exists: yes")
    except Exception as exc:
        raise RuntimeError(
            f"AI Search index '{AI_SEARCH_INDEX_NAME}' could not be read at '{AI_SEARCH_ENDPOINT}'."
        ) from exc

    try:
        stats = index_client.get_index_statistics(AI_SEARCH_INDEX_NAME)
        print(f"  document_count: {getattr(stats, 'document_count', '<unknown>')}")
        print(f"  storage_size: {getattr(stats, 'storage_size', '<unknown>')}")
    except Exception as exc:
        print(f"  index_statistics: unavailable ({exc})")

    try:
        results = search_client.search(search_text="*", top=1)
        first_result = next(iter(results), None)
        if first_result is None:
            print("  query_smoke_test: ok (index reachable, no documents returned)")
        else:
            print(f"  query_smoke_test: ok (sample id={first_result.get('id', '<unknown>')})")
    except Exception as exc:
        raise RuntimeError(
            "Direct Azure AI Search query failed. The index may exist, but the current credential or service configuration is not healthy for search queries."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reindex", dest="reindex", action="store_true")
    parser.add_argument("--no-reindex", dest="reindex", action="store_false")
    parser.set_defaults(reindex=False)
    args = parser.parse_args()

    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Data file missing: {DATA_FILE}")

    credential = get_credential()
    log_resolved_identity(credential)

    project_client = AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=credential,
    )

    if args.reindex:
        print("Reindex enabled")
    else:
        print("Reindex not requested. Will reuse the configured index if it exists.")

    ensure_search_index_ready(credential, force_reindex=args.reindex)

    search_connection = resolve_search_connection(project_client)
    run_ai_search_health_checks(search_connection, credential)
    search_connection_name = search_connection.name

    ai_search_tool = AzureAISearchTool(
        azure_ai_search=AzureAISearchToolResource(
            indexes=[
                AISearchIndexResource(
                    project_connection_id=search_connection_name,
                    index_name=AI_SEARCH_INDEX_NAME,
                    query_type=AzureAISearchQueryType.VECTOR,
                    top_k=3,
                )
            ]
        )
    )

    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=CHAT_MODEL,
            instructions=AGENT_INSTRUCTIONS,
            tools=[ai_search_tool],
        ),
    )
    print(f"Created/updated agent version: name={agent.name} version={agent.version}")

    responses_client = project_client.get_openai_client()
    response = responses_client.responses.create(
        input=[{"role": "user", "content": FIRST_PROMPT}],
        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
    )

    print("Response output:")
    print(response.output_text)


if __name__ == "__main__":
    main()