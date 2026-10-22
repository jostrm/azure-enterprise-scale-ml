# Creates the Foundry IQ knowledge base that agents.py connects to, from data/*.json:
# search index + documents -> knowledge source -> knowledge base -> Foundry project connection (RemoteTool).
# Re-runnable: every call is a create-or-update.

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import requests
from azure.identity import DefaultAzureCredential

from agents import HERE, load_settings

SETUP = ("project_resource_id",)
SEARCH_API = "2026-08-01-preview"
ARM_API = "2025-10-01-preview"
SEARCH = "https://search.azure.com"
ARM = "https://management.azure.com"
FIELDS = ("id", "ProductId", "ProductName", "Category", "ProductDescription", "FormattedPrice")


def search_names(server_url):
    # https://<search>.search.windows.net/knowledgebases/<kb>/mcp?... -> endpoint, kb, index, knowledge source
    parts = urlsplit(server_url)
    knowledge_base = parts.path.split("/")[2]
    return f"{parts.scheme}://{parts.netloc}", knowledge_base, f"{knowledge_base}-index", f"{knowledge_base}-source"


def documents():
    return [doc for name in ("products.json", "rewards.json")
            for doc in json.loads((HERE / "data" / name).read_text(encoding="utf-8"))]


def index_definition(index):
    return {
        "name": index,
        "fields": [{"name": name, "type": "Edm.String", "key": name == "id", "retrievable": True,
                    "searchable": name != "id", "filterable": name in ("ProductId", "Category")} for name in FIELDS],
        "semantic": {
            "defaultConfiguration": "zava-semantic",
            "configurations": [{
                "name": "zava-semantic",
                "prioritizedFields": {
                    "titleField": {"fieldName": "ProductName"},
                    "prioritizedContentFields": [{"fieldName": "ProductDescription"}],
                    "prioritizedKeywordsFields": [{"fieldName": "Category"}],
                },
            }],
        },
    }


def knowledge_source_definition(source, index):
    return {"name": source, "kind": "searchIndex",
            "searchIndexParameters": {"searchIndexName": index, "sourceDataFields": [{"name": name} for name in FIELDS]}}


def knowledge_base_definition(knowledge_base, source):
    # Minimal effort + extractive output: the agent's model writes the answer, Search needs no model of its own
    return {"name": knowledge_base, "knowledgeSources": [{"name": source}],
            "outputMode": "extractiveData", "retrievalReasoningEffort": {"kind": "minimal"}}


def connection_definition(server_url):
    return {"properties": {"category": "RemoteTool", "authType": "ProjectManagedIdentity", "target": server_url,
                           "audience": f"{SEARCH}/", "isSharedToAll": False, "metadata": {"ApiType": "Azure"}}}


def main():
    settings = load_settings()
    project_resource_id = os.getenv("project_resource_id", "").strip()
    if not project_resource_id:
        raise SystemExit("Missing in parameters.env: project_resource_id (see parameters.env.template)")
    search, knowledge_base, index, source = search_names(settings["server_url"])
    credential = DefaultAzureCredential()

    def call(method, url, audience, body):
        token = credential.get_token(f"{audience}/.default").token
        response = requests.request(method, url, json=body, timeout=120,
                                    headers={"Authorization": f"Bearer {token}"})
        if not response.ok:
            raise SystemExit(f"{method} {url} -> {response.status_code}: {response.text[:500]}")
        print(f"{method} {url.split('?')[0]} -> {response.status_code}")

    call("PUT", f"{search}/indexes/{index}?api-version={SEARCH_API}", SEARCH, index_definition(index))
    call("POST", f"{search}/indexes/{index}/docs/index?api-version={SEARCH_API}", SEARCH,
         {"value": [{"@search.action": "mergeOrUpload", **doc} for doc in documents()]})
    call("PUT", f"{search}/knowledgesources/{source}?api-version={SEARCH_API}", SEARCH,
         knowledge_source_definition(source, index))
    call("PUT", f"{search}/knowledgebases/{knowledge_base}?api-version={SEARCH_API}", SEARCH,
         knowledge_base_definition(knowledge_base, source))
    call("PUT", f"{ARM}{project_resource_id}/connections/{settings['project_connection_id']}?api-version={ARM_API}",
         ARM, connection_definition(settings["server_url"]))


if __name__ == "__main__":
    main()
