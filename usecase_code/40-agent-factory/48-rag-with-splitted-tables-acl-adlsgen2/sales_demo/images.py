"""Independent synthetic-only image-serving branch; never inherits sales ACL data."""

from __future__ import annotations

import copy
import re

from .search import (API_VERSION, SEARCH_AUDIENCE, _container, _marker, _path, endpoint,
                     check_resource, ensure_resource, scoped_name, storage_id)


def _contains_permission_options(value):
    if isinstance(value, dict):
        return "ingestionPermissionOptions" in value or any(_contains_permission_options(v) for v in value.values())
    return isinstance(value, list) and any(_contains_permission_options(v) for v in value)


def build_image_definitions(config):
    if _contains_permission_options(config):
        raise ValueError("Image serving does not support ingestionPermissionOptions; use isolated synthetic data.")
    if config.get("synthetic_only") is not True:
        raise ValueError("The image branch requires an explicit synthetic-only declaration.")
    protected = config.get("protected_storage_resource_ids")
    if not isinstance(protected, list) or not protected:
        raise ValueError("Explicit protected sales/master storage account IDs are required.")
    protected = {storage_id(value).casefold() for value in protected}
    source = storage_id(config["source_storage_resource_id"])
    assets = storage_id(config["asset_storage_resource_id"])
    if source.casefold() in protected or assets.casefold() in protected:
        raise ValueError("Image source and assets must not reuse any protected sales/master storage account.")
    source_container = _container(config["source_container"])
    asset_container = _container(config["asset_container"])
    if source.casefold() == assets.casefold() and source_container == asset_container:
        raise ValueError("Source and generated asset containers must be distinct.")
    prefix = _path(config["source_prefix"]) + "/"
    if not prefix.startswith("synthetic/images/") or any(
        term in prefix.casefold().split("/") for term in ("sales", "ingestion", "retail", "excel", "json")
    ):
        raise ValueError("Only an explicit synthetic/images directory is accepted.")
    input_kind = config.get("input_kind")
    if input_kind not in ("docx", "png-derivative", "png", "pdf"):
        raise ValueError("Label the actual input kind; a PNG derivative is not a DOCX pass.")
    search_endpoint = endpoint(config["search_endpoint"], ".search.windows.net")
    ai_endpoint = endpoint(config["ai_services_endpoint"], ".services.ai.azure.com")
    model_endpoint = endpoint(config["model_endpoint"], ".services.ai.azure.com")
    if ai_endpoint != model_endpoint:
        raise ValueError("Standard extraction requires the explicitly selected Foundry resource's models.")
    for key in ("chat_deployment", "chat_model", "embedding_deployment"):
        if not isinstance(config.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", config[key]):
            raise ValueError("Explicit model and deployment names are required.")
    names = {kind: scoped_name(config["owner"], config["version"], "images", role) for kind, role in
             (("knowledge_source", "source"), ("knowledge_base", "knowledge"))}
    description = _marker(config)
    chat = {"kind": "azureOpenAI", "azureOpenAIParameters": {
        "resourceUri": model_endpoint, "deploymentId": config["chat_deployment"], "modelName": config["chat_model"]}}
    source_definition = {
        "name": names["knowledge_source"], "description": description, "kind": "azureBlob",
        "azureBlobParameters": {
            "connectionString": f"ResourceId={source};", "containerName": source_container, "folderPath": prefix,
            "ingestionParameters": {
                "contentExtractionMode": "standard",
                "assetStore": {"connectionString": f"ResourceId={assets};", "containerName": asset_container},
                "aiServices": {"uri": ai_endpoint}, "chatCompletionModel": chat,
                "embeddingModel": {"kind": "azureOpenAI", "azureOpenAIParameters": {
                    "resourceUri": model_endpoint, "deploymentId": config["embedding_deployment"],
                    "modelName": "text-embedding-3-large"}},
            },
        },
    }
    base = {
        "name": names["knowledge_base"], "description": description,
        "knowledgeSources": [{"name": names["knowledge_source"], "enableImageServing": True}],
        "outputMode": "answerSynthesis", "models": [copy.deepcopy(chat)],
    }
    return {"api_version": API_VERSION, "search_endpoint": search_endpoint, "names": names,
            "input_kind": input_kind, "mutations": False,
            "resources": {"knowledge_source": source_definition, "knowledge_base": base},
            "limitations": ["Image-serving asset stores do not inherit sales document permissions.",
                            "Direct DOCX extraction is not assured; PNG derivative evidence is labeled separately.",
                            "Activity reports aggregate images sent, not which individual image caused an answer."]}


def verify_image_evidence(response, *, input_kind, knowledge_source=None):
    if input_kind not in ("docx", "png-derivative", "png", "pdf"):
        raise ValueError("The actual indexed input format must be explicit.")
    activities = [a for a in response.get("activity", []) if isinstance(a, dict)
                  and (knowledge_source is None or
                       (a.get("knowledgeSourceName") == knowledge_source and a.get("type") == "azureBlob"))]
    if any(a.get("error") or a.get("errors") for a in activities):
        raise ValueError("Image-serving activity reported a service error.")
    counts = [a.get("imageServing", {}).get("imagesSentToModel") for a in activities]
    if any(value is not None and (type(value) is not int or value < 0) for value in counts):
        raise ValueError("Invalid service-reported image-serving counters.")
    total = sum(value for value in counts if value is not None)
    if total <= 0:
        raise ValueError("No service evidence that images reached the model; answer text is not proof.")
    evidence = {"input_kind": input_kind, "images_sent_to_model": total,
                "image_serving_verified": True, "docx_pass": False,
                "direct_docx_status": "Not established by aggregate image counters alone.",
                "activity": copy.deepcopy(response["activity"]), "raw_response": copy.deepcopy(response)}
    if "servedImages" in response:
        evidence["servedImages"] = copy.deepcopy(response["servedImages"])
    return evidence


class ImageClient:
    def __init__(self, config, transport):
        self._plan = build_image_definitions(config)
        self.transport = transport

    def plan(self):
        return copy.deepcopy(self._plan)

    def _url(self, path):
        return f"{self._plan['search_endpoint']}/{path}?api-version={API_VERSION}"

    def configure(self, *, apply=False):
        if apply is not True:
            return self.plan()
        for key, collection in (("knowledge_source", "knowledgesources"), ("knowledge_base", "knowledgebases")):
            resource = self._plan["resources"][key]
            ensure_resource(self.transport, self._url(f"{collection}/{resource['name']}"), resource)
        return {**self.plan(), "mutations": True}

    def retrieve(self, question, *, execute=False):
        if execute is not True:
            raise ValueError("Image retrieval invokes answer synthesis and requires execute=True.")
        if not isinstance(question, str) or not question.strip() or len(question) > 8000:
            raise ValueError("A nonempty image question of at most 8000 characters is required.")
        for key, collection in (("knowledge_source", "knowledgesources"), ("knowledge_base", "knowledgebases")):
            resource = self._plan["resources"][key]
            check_resource(self.transport, self._url(f"{collection}/{resource['name']}"), resource)
        response = self.transport.request(
            "POST", self._url(f"knowledgebases/{self._plan['names']['knowledge_base']}/retrieve"), {
                "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
                "retrievalReasoningEffort": {"kind": "medium"},
                "includeActivity": True, "outputMode": "answerSynthesis",
                "knowledgeSourceParams": [{"knowledgeSourceName": self._plan["names"]["knowledge_source"],
                                           "kind": "azureBlob", "enableImageServing": True}],
            }, audience=SEARCH_AUDIENCE)
        return verify_image_evidence(response, input_kind=self._plan["input_kind"],
                                     knowledge_source=self._plan["names"]["knowledge_source"])
