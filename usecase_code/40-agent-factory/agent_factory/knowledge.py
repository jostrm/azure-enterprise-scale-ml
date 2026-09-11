"""Basic-compatible Foundry IQ over an existing, privately ingested text index."""

from __future__ import annotations

import hashlib
import json

from .azure import AzureError, AzureSession
from .config import Target
from .data import (
    OWNER, SEARCH_AUDIENCE, SEMANTIC_CONFIGURATION,
    require_private_endpoint, search_name, search_url, validate_index, validate_target,
)

CONNECTION_API = "2025-10-01-preview"


def _compatible(actual, expected) -> bool:
    """Ignore only service metadata and empty defaults, never extra active configuration."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        if any(not _compatible(actual.get(key), value) for key, value in expected.items()):
            return False
        return all(
            key in expected or key.startswith("@odata.") or value is None or value == [] or value == {}
            or (key in {"enableFreshness", "enableImageServing"} and value is False)
            or (key == "resultsProcessing" and value == "rerank")
            for key, value in actual.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _compatible(left, right) for left, right in zip(actual, expected)
        )
    return type(actual) is type(expected) and actual == expected


def _ensure_search_resource(session: AzureSession, url: str, body: dict) -> None:
    created = False
    try:
        current = session.request("GET", url, audience=SEARCH_AUDIENCE)
    except AzureError as exc:
        if exc.status != 404:
            raise
        session.request("PUT", url, body, audience=SEARCH_AUDIENCE,
                        headers={"If-None-Match": "*", "Prefer": "return=representation"})
        created = True
        current = session.request("GET", url, audience=SEARCH_AUDIENCE)
    expected_credentials = body.get("credentials", {})
    hidden_credentials = (
        current.get("credentials") == {"connectionString": None}
        and set(expected_credentials) == {"connectionString"}
        and str(expected_credentials["connectionString"]).startswith("ResourceId=")
    )
    visible = {**current, "credentials": expected_credentials} if hidden_credentials else current
    if not _compatible(visible, body):
        raise ValueError(f"Existing Search resource {body['name']} is incompatible; not updating or deleting it.")
    if hidden_credentials and not created:
        # Search redacts this field even for ResourceId authentication. Reassert
        # MI under an ETag rather than assuming a hidden credential is still keyless.
        etag = current.get("@odata.etag")
        if not etag:
            raise RuntimeError("Cannot safely reassert a redacted Search data source credential without an ETag.")
        session.request("PUT", url, body, audience=SEARCH_AUDIENCE,
                        headers={"If-Match": etag, "Prefer": "return=representation"})
        verified = session.request("GET", url, audience=SEARCH_AUDIENCE)
        if verified.get("credentials") == {"connectionString": None}:
            verified = {**verified, "credentials": expected_credentials}
        if not _compatible(verified, body):
            raise RuntimeError("Search data source changed while reasserting its managed-identity connection.")


def _connection_body(endpoint: str) -> dict:
    return {
        "properties": {
            "authType": "ProjectManagedIdentity", "category": "RemoteTool",
            "target": endpoint, "isSharedToAll": False, "audience": f"{SEARCH_AUDIENCE}/",
            "metadata": {"ApiType": "Azure"},
        },
    }


def _source_definition(index_name: str, knowledge_source_name: str) -> dict:
    return {
        "name": knowledge_source_name, "description": OWNER, "kind": "searchIndex",
        "searchIndexParameters": {
            "searchIndexName": index_name, "semanticConfigurationName": SEMANTIC_CONFIGURATION,
            "searchFields": [{"name": "topic"}, {"name": "content"}],
            "sourceDataFields": [{"name": name} for name in (
                "id", "topic", "content", "source_url", "source_version", "license", "attribution", "document_url",
            )],
        },
    }


def _base_definition(knowledge_source_name: str, knowledge_base_name: str) -> dict:
    return {
        "name": knowledge_base_name, "description": OWNER,
        "knowledgeSources": [{"name": knowledge_source_name}],
        "outputMode": "extractiveData", "retrievalReasoningEffort": {"kind": "minimal"},
    }


def configure_knowledge(session: AzureSession, target: Target, *,
                        index_name: str = "aif-kaggle-rag-v1",
                        knowledge_source_name: str = "aif-kaggle-source",
                        knowledge_base_name: str = "aif-kaggle-knowledge",
                        connection_name: str = "aif-knowledge-mcp") -> dict:
    validate_target(target)
    for name in (index_name, knowledge_source_name, knowledge_base_name, connection_name):
        search_name(name)
    require_private_endpoint(target.search_endpoint)
    service_id = (
        f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
        f"/providers/Microsoft.Search/searchServices/{target.search_name}"
    )
    service = session.arm("GET", service_id, api_version="2025-05-01")
    properties = service.get("properties", {})
    if properties.get("publicNetworkAccess", "").lower() != "disabled":
        raise ValueError("Search public network access must already be disabled; no infrastructure changes are made.")
    if properties.get("semanticSearch", "").lower() not in {"free", "standard"}:
        raise ValueError("Search semantic ranking must already be enabled; no paid upgrade is performed.")
    index = session.request("GET", search_url(target, f"indexes/{index_name}"), audience=SEARCH_AUDIENCE)
    validate_index(index, index_name)
    document_probe = session.request(
        "POST", search_url(target, f"indexes/{index_name}/docs/search"),
        {"search": "*", "select": "id,topic,content", "top": 1, "count": True}, audience=SEARCH_AUDIENCE,
    )
    rows = document_probe.get("value", [])
    count = document_probe.get("@odata.count")
    if (type(count) is not int or count < 1 or not rows
            or not rows[0].get("content", "").strip() or not rows[0].get("topic", "").strip()):
        raise RuntimeError("Index has no searchable knowledge documents; complete managed-identity ingestion first.")
    semantic_probe = session.request(
        "POST", search_url(target, f"indexes/{index_name}/docs/search"),
        {"search": rows[0]["topic"], "queryType": "semantic",
         "semanticConfiguration": SEMANTIC_CONFIGURATION, "select": "id", "top": 1}, audience=SEARCH_AUDIENCE,
    )
    if not semantic_probe.get("value") or semantic_probe["value"][0].get("@search.rerankerScore") is None:
        raise RuntimeError("Semantic ranking is unavailable or quota-exhausted; no knowledge resources were wired.")
    source = _source_definition(index_name, knowledge_source_name)
    base = _base_definition(knowledge_source_name, knowledge_base_name)
    _ensure_search_resource(session, search_url(target, f"knowledgesources/{knowledge_source_name}"), source)
    _ensure_search_resource(session, search_url(target, f"knowledgebases/{knowledge_base_name}"), base)
    endpoint = search_url(target, f"knowledgebases/{knowledge_base_name}/mcp")
    connection_id = f"{target.project_id}/connections/{connection_name}"
    connection = _connection_body(endpoint)
    try:
        current = session.arm("GET", connection_id, api_version=CONNECTION_API)
    except AzureError as exc:
        if exc.status != 404:
            raise
        session.arm("PUT", connection_id, connection, api_version=CONNECTION_API)
        current = session.arm("GET", connection_id, api_version=CONNECTION_API)
    # ARM owns timestamps/status, but all auth, destination and sharing properties must match.
    current_properties = current.get("properties", {})
    for key, expected in connection["properties"].items():
        if not _compatible(current_properties.get(key), expected):
            raise ValueError("Existing project MCP connection has incompatible authentication, target, or sharing; refusing overwrite.")
    if current_properties.get("credentials") or current_properties.get("sharedUserList"):
        raise ValueError("Existing connection contains unexpected credentials or sharing restrictions.")
    return {
        "tool": {
            "type": "mcp", "server_label": knowledge_base_name, "server_url": endpoint,
            "project_connection_id": connection_name,
            "allowed_tools": ["knowledge_base_retrieve"], "require_approval": "never",
        },
        "knowledge_base_name": knowledge_base_name, "knowledge_source_name": knowledge_source_name,
        "connection_name": connection_name, "connection_id": connection_id,
        "document_count": document_probe["@odata.count"], "embeddings_required": False,
        "retrieval_verified": False,
    }


def verify_retrieval(session: AzureSession, target: Target, query: str, *,
                     knowledge_base_name: str = "aif-kaggle-knowledge",
                     knowledge_source_name: str = "aif-kaggle-source") -> dict:
    """Check real grounding via private Search; never invoke a third-party MCP server."""
    validate_target(target)
    search_name(knowledge_base_name)
    search_name(knowledge_source_name)
    require_private_endpoint(target.search_endpoint)
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ValueError("Provide a nonempty retrieval query of at most 4000 characters.")
    # Prevent a same-name KB from routing this query to an unrelated/external source.
    base = session.request("GET", search_url(target, f"knowledgebases/{knowledge_base_name}"), audience=SEARCH_AUDIENCE)
    if not _compatible(base, _base_definition(knowledge_source_name, knowledge_base_name)):
        raise ValueError("Retrieval requires the factory's minimal, single-source knowledge base.")
    source = session.request("GET", search_url(target, f"knowledgesources/{knowledge_source_name}"), audience=SEARCH_AUDIENCE)
    if source.get("description") != OWNER or source.get("kind") != "searchIndex":
        raise ValueError("Retrieval is restricted to the owned local Search index source.")
    index_name = search_name(source.get("searchIndexParameters", {}).get("searchIndexName"))
    if not _compatible(source, _source_definition(index_name, knowledge_source_name)):
        raise ValueError("Retrieval requires the factory's exact text-only knowledge source.")
    index = session.request("GET", search_url(target, f"indexes/{index_name}"), audience=SEARCH_AUDIENCE)
    validate_index(index, index_name)
    response = session.request(
        "POST", search_url(target, f"knowledgebases/{knowledge_base_name}/retrieve"),
        {
            "intents": [{"type": "semantic", "search": query.strip()}],
            "includeActivity": True,
            "knowledgeSourceParams": [{
                "knowledgeSourceName": knowledge_source_name, "kind": "searchIndex",
                "alwaysQuerySource": True, "includeReferences": True,
            }],
        }, audience=SEARCH_AUDIENCE,
    )
    if response.get("error") or any(activity.get("error") for activity in response.get("activity", [])):
        raise RuntimeError("Knowledge retrieval reported source/activity errors; grounding is not verified.")
    references = response.get("references", [])
    texts = [
        part.get("text", "") for message in response.get("response", [])
        for part in message.get("content", []) if part.get("type") == "text"
    ]
    grounded = [reference for reference in references if reference.get("type") == "searchIndex" and reference.get("docKey")]
    chunks = []
    for text in texts:
        try:
            decoded = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(decoded, list):
            chunks.extend(chunk for chunk in decoded if isinstance(chunk, dict))
    if not grounded or not any(isinstance(chunk.get("content"), str) and chunk["content"].strip() for chunk in chunks):
        raise RuntimeError("Knowledge retrieval returned no grounded Search references/content; HTTP success is insufficient.")
    # Return only a verification summary, never query text, raw CSV, or evaluation answers.
    return {
        "retrieval_verified": True, "knowledge_base_name": knowledge_base_name,
        "reference_count": len(grounded), "response_sha256": hashlib.sha256(
            json.dumps(texts, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
