"""ADF project-UAMI copies and private, skillset-free Search indexing on Basic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from uuid import UUID

from .azure import ARM, AzureError, AzureSession
from .config import Target
from .data import (
    ATTRIBUTION, CSV_COLUMNS, DATASET_FILE, DATASET_URL, DATASET_VERSION, DOWNLOAD_URL,
    SEARCH_AUDIENCE, SEMANTIC_CONFIGURATION, index_schema, json_bytes,
    require_private_endpoint, search_url, sha256, validate_index, validate_target,
)
from .knowledge import _compatible, _ensure_search_resource

ADF_API = "2018-06-01"
STORAGE_API = "2023-05-01"
SEARCH_ARM_API = "2025-05-01"
ADF_OWNER = "agent-factory:kaggle-rag:adf:v1"
CREDENTIAL = "ls_cred_project_uami"
INTEGRATION_RUNTIME = "AutoResolveIntegrationRuntime"
PIPELINE_NAME = "aif_kaggle_rag_v1"
CONTAINER = "agent-factory-adf"
PREFIX = "kaggle-rag-v1"
INDEX_NAME = "aif-kaggle-rag-adf-v1"
DATA_SOURCE_NAME = "aif-kaggle-adf-blob"
INDEXER_NAME = "aif-kaggle-adf-indexer"


def integrity_reference() -> dict:
    path = Path(__file__).resolve().parents[1] / "43-data" / "kaggle-v1.integrity.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _factory_id(target: Target, factory_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", factory_name) or not 3 <= len(factory_name) <= 63:
        raise ValueError("Invalid Azure Data Factory name.")
    return f"{target.group_id}/providers/Microsoft.DataFactory/factories/{factory_name}"


def _search_id(target: Target) -> str:
    return f"{target.group_id}/providers/Microsoft.Search/searchServices/{target.search_name}"


def _expression(value: str) -> dict:
    return {"value": value, "type": "Expression"}


def _reference(name: str, kind: str = "DatasetReference") -> dict:
    return {"referenceName": name, "type": kind}


def _depends(*names: str) -> list[dict]:
    return [{"activity": name, "dependencyConditions": ["Succeeded"]} for name in names]


def _all(*expressions: str) -> str:
    result = expressions[0]
    for expression in expressions[1:]:
        result = f"and({result},{expression})"
    return f"@{result}"


def _guard(name: str, condition: str, message: str, *dependencies: str) -> dict:
    return {
        "name": name, "type": "IfCondition", "dependsOn": _depends(*dependencies),
        "typeProperties": {
            "expression": _expression(condition), "ifTrueActivities": [],
            "ifFalseActivities": [{
                "name": f"Fail_{name}", "type": "Fail",
                "typeProperties": {"message": message, "errorCode": name},
            }],
        },
    }


def _policy(*, secure: bool = True) -> dict:
    return {
        "timeout": "0.00:10:00", "retry": 0, "retryIntervalInSeconds": 30,
        "secureInput": secure, "secureOutput": secure,
    }


def build_datafactory_definitions(target: Target, *, factory_name: str) -> dict:
    """Pure ARM/REST definitions. Does not authenticate, read private data, or deploy."""
    validate_target(target)
    factory_id = _factory_id(target, factory_name)
    pin = integrity_reference()
    blob_endpoint = f"https://{target.storage_name}.blob.core.windows.net"
    document_url = f"{blob_endpoint}/{CONTAINER}/{PREFIX}/knowledge/items.json"
    ir = _reference(INTEGRATION_RUNTIME, "IntegrationRuntimeReference")
    metadata = [
        {"name": "owner", "value": ADF_OWNER},
        {"name": "source_url", "value": DATASET_URL},
        {"name": "dataset_version", "value": DATASET_VERSION},
        {"name": "license", "value": "MIT"},
        {"name": "attribution", "value": ATTRIBUTION},
        {"name": "expected_raw_sha256", "value": pin["raw_sha256"]},
        {"name": "expected_raw_md5", "value": pin["raw_md5_base64"]},
    ]
    linked_services = {
        "aif_kaggle_http": {"properties": {
            "description": ADF_OWNER, "annotations": [ADF_OWNER], "type": "HttpServer",
            "typeProperties": {"url": DOWNLOAD_URL, "authenticationType": "Anonymous",
                               "enableServerCertificateValidation": True},
            "connectVia": ir,
        }},
        "aif_kaggle_blob": {"properties": {
            "description": ADF_OWNER, "annotations": [ADF_OWNER], "type": "AzureBlobStorage",
            "typeProperties": {
                "serviceEndpoint": f"{blob_endpoint}/", "accountKind": "StorageV2",
                "credential": _reference(CREDENTIAL, "CredentialReference"),
            }, "connectVia": ir,
        }},
    }
    datasets = {}

    def dataset(name, kind, folder=None, filename=None, http=False):
        location = {"type": "HttpServerLocation"} if http else {
            "type": "AzureBlobStorageLocation", "container": CONTAINER,
            "folderPath": f"{PREFIX}/{folder}", "fileName": filename,
        }
        properties = {
            "description": ADF_OWNER, "annotations": [ADF_OWNER], "type": kind,
            "linkedServiceName": _reference("aif_kaggle_http" if http else "aif_kaggle_blob", "LinkedServiceReference"),
            "typeProperties": {"location": location},
        }
        if kind == "DelimitedText":
            properties["typeProperties"].update({
                "columnDelimiter": ",", "quoteChar": '"', "escapeChar": '"',
                "firstRowAsHeader": True, "encodingName": "UTF-8",
            })
        if kind == "Json":
            properties["typeProperties"]["encodingName"] = "UTF-8"
        datasets[name] = {"properties": properties}

    dataset("aif_kaggle_http_binary", "Binary", http=True)
    dataset("aif_kaggle_download", "Binary", "incoming", DATASET_FILE)
    dataset("aif_kaggle_raw_binary", "Binary", "raw", DATASET_FILE)
    dataset("aif_kaggle_raw_csv", "DelimitedText", "raw", DATASET_FILE)
    dataset("aif_kaggle_stage_knowledge", "Json", "staging", "knowledge.json")
    dataset("aif_kaggle_stage_knowledge_binary", "Binary", "staging", "knowledge.json")
    dataset("aif_kaggle_stage_evaluation", "Json", "staging", "evaluation.json")
    dataset("aif_kaggle_stage_evaluation_binary", "Binary", "staging", "evaluation.json")
    dataset("aif_kaggle_knowledge_binary", "Binary", "knowledge", "items.json")
    dataset("aif_kaggle_evaluation_binary", "Binary", "evaluation", "samples.json")
    read_settings = {"type": "AzureBlobStorageReadSettings", "recursive": False}
    write_settings = {"type": "AzureBlobStorageWriteSettings", "copyBehavior": "PreserveHierarchy", "metadata": metadata}

    def binary_copy(name, source, sink, *dependencies, http=False):
        settings = {
            "type": "HttpReadSettings", "requestMethod": "Get", "httpRequestTimeout": "00:01:00",
            "additionalHeaders": "Accept: text/csv,application/octet-stream\n",
        } if http else read_settings
        properties = {
            "source": {"type": "BinarySource", "storeSettings": settings},
            "sink": {"type": "BinarySink", "storeSettings": write_settings},
            "parallelCopies": 1, "enableStaging": False,
        }
        # HTTP does not support ADF consistency verification. Blob-to-Blob does,
        # and records Content-MD5 on the destination; never pretend HTTP verified it.
        if not http:
            properties["validateDataConsistency"] = True
        return {
            "name": name, "type": "Copy", "dependsOn": _depends(*dependencies), "policy": _policy(),
            "inputs": [_reference(source)], "outputs": [_reference(sink)], "typeProperties": properties,
        }

    def metadata_activity(name, source, fields, *dependencies):
        return {
            "name": name, "type": "GetMetadata", "dependsOn": _depends(*dependencies),
            "policy": _policy(secure=False),
            "typeProperties": {"dataset": _reference(source), "fieldList": fields, "storeSettings": read_settings},
        }

    constants = {
        "source_url": DATASET_URL, "source_version": DATASET_VERSION, "license": "MIT",
        "attribution": ATTRIBUTION, "dataset_sha256": pin["raw_sha256"], "document_url": document_url,
    }

    def project_copy(name, sink, field_pairs):
        return {
            "name": name, "type": "Copy", "dependsOn": _depends("ValidateCSVHeader"), "policy": _policy(),
            "inputs": [_reference("aif_kaggle_raw_csv")], "outputs": [_reference(sink)],
            "typeProperties": {
                "source": {
                    "type": "DelimitedTextSource", "storeSettings": read_settings,
                    "formatSettings": {"type": "DelimitedTextReadSettings"},
                    "additionalColumns": [{"name": key, "value": value} for key, value in constants.items()],
                },
                "sink": {
                    "type": "JsonSink", "storeSettings": write_settings,
                    "formatSettings": {"type": "JsonWriteSettings", "filePattern": "arrayOfObjects"},
                },
                "translator": {"type": "TabularTranslator", "mappings": [
                    {"source": {"name": source}, "sink": {"path": f"$['{destination}']"}}
                    for source, destination in field_pairs
                ]},
                "parallelCopies": 1, "enableStaging": False, "enableSkipIncompatibleRow": False,
                "validateDataConsistency": True,
            },
        }

    activities = [
        binary_copy("DownloadRaw", "aif_kaggle_http_binary", "aif_kaggle_download", http=True),
        metadata_activity("InspectDownload", "aif_kaggle_download", ["size"], "DownloadRaw"),
        _guard("ValidateDownloadSize", f"@equals(activity('InspectDownload').output.size,{pin['bytes']})",
               "Pinned CSV size mismatch; possible HTML/auth challenge or unexpected download. No indexing.",
               "InspectDownload"),
        binary_copy("SealRaw", "aif_kaggle_download", "aif_kaggle_raw_binary", "ValidateDownloadSize"),
        metadata_activity("InspectRaw", "aif_kaggle_raw_binary", ["size", "contentMD5"], "SealRaw"),
        _guard("ValidateRawIntegrity", _all(
            f"equals(activity('InspectRaw').output.size,{pin['bytes']})",
            f"equals(activity('InspectRaw').output.contentMD5,'{pin['raw_md5_base64']}')",
        ), "Pinned CSV size/Content-MD5 mismatch or missing checksum. No indexing.", "InspectRaw"),
        metadata_activity("InspectCSV", "aif_kaggle_raw_csv", ["columnCount", "structure"], "ValidateRawIntegrity"),
        _guard("ValidateCSVHeader", _all(
            "equals(activity('InspectCSV').output.columnCount,4)",
            *(f"equals(activity('InspectCSV').output.structure[{i}].name,'{name}')" for i, name in enumerate(CSV_COLUMNS)),
        ), "Malformed CSV header; the four pinned Kaggle columns are required.", "InspectCSV"),
        project_copy("CopyKnowledge", "aif_kaggle_stage_knowledge",
                     [("ki_topic", "topic"), ("ki_text", "content")] + [(name, name) for name in constants]),
        project_copy("CopyEvaluation", "aif_kaggle_stage_evaluation",
                     [("ki_topic", "ki_topic"), ("sample_question", "sample_question"),
                      ("sample_ground_truth", "sample_ground_truth"),
                      ("source_url", "source_url"), ("source_version", "source_version")]),
        {
            "name": "ReadKnowledge", "type": "Lookup", "dependsOn": _depends("CopyKnowledge"),
            "policy": _policy(), "typeProperties": {
                "dataset": _reference("aif_kaggle_stage_knowledge"), "firstRowOnly": False,
                "source": {"type": "JsonSource", "storeSettings": read_settings,
                           "formatSettings": {"type": "JsonReadSettings"}},
            },
        },
        _guard("ValidateKnowledge", _all(
            f"equals(int(activity('ReadKnowledge').output.count),{pin['row_count']})",
            f"equals(length(union(activity('ReadKnowledge').output.value,activity('ReadKnowledge').output.value)),{pin['row_count']})",
            f"equals(activity('CopyKnowledge').output.rowsCopied,{pin['row_count']})",
            f"equals(activity('CopyEvaluation').output.rowsCopied,{pin['row_count']})",
        ), "Unexpected row count or duplicate knowledge items; Copy does not silently deduplicate.",
               "ReadKnowledge", "CopyEvaluation"),
        binary_copy("PublishKnowledge", "aif_kaggle_stage_knowledge_binary", "aif_kaggle_knowledge_binary", "ValidateKnowledge"),
        binary_copy("SealEvaluation", "aif_kaggle_stage_evaluation_binary", "aif_kaggle_evaluation_binary", "ValidateKnowledge"),
        metadata_activity("InspectPublished", "aif_kaggle_knowledge_binary", ["size", "contentMD5"], "PublishKnowledge"),
        metadata_activity("InspectEvaluation", "aif_kaggle_evaluation_binary", ["size", "contentMD5"], "SealEvaluation"),
        _guard("ValidateArtifacts", _all(
            "greater(activity('InspectPublished').output.size,0)",
            "greater(activity('InspectEvaluation').output.size,0)",
            "not(empty(activity('InspectPublished').output.contentMD5))",
            "not(empty(activity('InspectEvaluation').output.contentMD5))",
        ), "Knowledge/evaluation Blob persistence or checksum verification failed.", "InspectPublished", "InspectEvaluation"),
    ]
    pipeline = {"properties": {
        "description": ADF_OWNER, "annotations": [ADF_OWNER], "concurrency": 1, "activities": activities,
    }}
    return {
        "factory_id": factory_id, "pipeline_name": PIPELINE_NAME, "container": CONTAINER,
        "prefix": PREFIX, "index_name": INDEX_NAME, "document_url": document_url,
        "linked_services": linked_services, "datasets": datasets, "pipeline": pipeline,
        "data_source": {
            "name": DATA_SOURCE_NAME, "description": ADF_OWNER, "type": "azureblob",
            "credentials": {"connectionString": f"ResourceId={target.storage_id};"},
            "container": {"name": CONTAINER, "query": f"{PREFIX}/knowledge/"},
        },
        "indexer": {
            "name": INDEXER_NAME, "description": ADF_OWNER, "dataSourceName": DATA_SOURCE_NAME,
            "targetIndexName": INDEX_NAME, "disabled": False,
            "parameters": {
                "maxFailedItems": 0, "maxFailedItemsPerBatch": 0,
                "configuration": {
                    "parsingMode": "jsonArray", "executionEnvironment": "private",
                    "indexedFileNameExtensions": ".json", "failOnUnsupportedContentType": True,
                    "failOnUnprocessableDocument": True,
                },
            },
            "fieldMappings": [
                {"sourceFieldName": "AzureSearch_DocumentKey", "targetFieldName": "id",
                 "mappingFunction": {"name": "base64Encode"}},
                *({"sourceFieldName": f"/{field}", "targetFieldName": field} for field in (
                    "topic", "content", "source_url", "source_version", "license", "attribution",
                    "dataset_sha256", "document_url",
                )),
            ],
        },
    }


def _required_arm(session, resource_id, api_version):
    try:
        return session.arm("GET", resource_id, api_version=api_version)
    except AzureError as exc:
        if exc.status == 404:
            raise RuntimeError(f"Prerequisite not deployed: {resource_id}. Enable Data Factory in the existing project pipeline.") from None
        raise


def _contains_expected(actual, expected) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(_contains_expected(actual.get(key), value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _contains_expected(left, right) for left, right in zip(actual, expected)
        )
    return type(actual) is type(expected) and actual == expected


def _ensure_owned_arm(session, resource_id, body, api_version) -> dict:
    try:
        current = session.arm("GET", resource_id, api_version=api_version)
    except AzureError as exc:
        if exc.status != 404:
            raise
        session.arm("PUT", resource_id, body, api_version=api_version)
        current = session.arm("GET", resource_id, api_version=api_version)
    actual = dict(current.get("properties", {}))
    if "/blobServices/default/containers/" in resource_id:
        # ARM can omit the default private-access enum on a container read.
        if actual.get("publicAccess") is None:
            actual["publicAccess"] = "None"
        compatible = _contains_expected(actual, body["properties"])
    else:
        actual.pop("provisioningState", None)
        actual.pop("lastPublishTime", None)
        compatible = _compatible(actual, body["properties"])
    if not compatible:
        raise ValueError(f"Incompatible existing factory artifact: {resource_id}; refusing overwrite.")
    if any(actual.get(key) for key in ("parameters", "variables")):
        raise ValueError("Existing pipeline has unexpected parameters/variables; refusing changed execution.")
    for key in ("connectionString", "accountKey", "sasUri", "sasToken", "userName", "password", "authHeaders",
                "servicePrincipalId", "servicePrincipalKey", "clientSecret", "encryptedCredential"):
        if actual.get("typeProperties", {}).get(key):
            raise ValueError("Factory artifact contains unexpected authentication; refusing credentials fallback.")
    return current


def _arm_collection(session, resource_id, api_version):
    page = session.arm("GET", resource_id, api_version=api_version)
    rows = list(page.get("value", []))
    seen = set()
    while page.get("nextLink"):
        url = page["nextLink"]
        if url in seen or not url.startswith(f"{ARM}{resource_id}?") or len(seen) >= 20:
            raise RuntimeError("Unexpected ARM continuation while checking private endpoints.")
        seen.add(url)
        page = session.request("GET", url)
        rows.extend(page.get("value", []))
    return rows


def _private_link(session, collection_id, name, target: Target, *, search: bool) -> dict:
    api_version = SEARCH_ARM_API if search else ADF_API
    existing = _arm_collection(session, collection_id, api_version)
    matches = [item for item in existing if
               item.get("properties", {}).get("privateLinkResourceId", "").lower() == target.storage_id.lower()
               and item.get("properties", {}).get("groupId") == "blob"]
    if len(matches) > 1:
        raise ValueError("More than one Blob private link exists for the selected storage; resolve the ambiguity.")
    if matches:
        resource = matches[0]
    else:
        resource_id = f"{collection_id}/{name}"
        if any(item.get("name", "").split("/")[-1] == name for item in existing):
            raise ValueError("The desired private endpoint name belongs to another resource.")
        properties = {"privateLinkResourceId": target.storage_id, "groupId": "blob"}
        if search:
            properties["requestMessage"] = "Agent factory Kaggle ingestion: private Blob indexing without skillsets."
        session.arm("PUT", resource_id, {"properties": properties}, api_version=api_version)
        resource = session.arm("GET", resource_id, api_version=api_version)
    properties = resource.get("properties", {})
    status = properties.get("status") if search else properties.get("connectionState", {}).get("status")
    return {
        "resource_id": resource.get("id", f"{collection_id}/{name}"),
        "status": status or "Pending", "provisioning_state": properties.get("provisioningState", "Unknown"),
        "approved": str(status).lower() == "approved" and properties.get("provisioningState", "").lower() == "succeeded",
        "storage_id": target.storage_id, "group_id": "blob",
    }


def _preflight(session, target, definitions):
    factory_id = definitions["factory_id"]
    factory = _required_arm(session, factory_id, ADF_API)
    if factory.get("properties", {}).get("publicNetworkAccess", "").lower() != "disabled":
        raise ValueError("ADF public network access must already be disabled; no public-access changes are made.")
    identities = factory.get("identity", {}).get("userAssignedIdentities", {})
    if target.identity_id.lower() not in {key.lower() for key in identities}:
        raise ValueError("ADF must already have the selected project UAMI attached by the project deployment.")
    credential = _required_arm(session, f"{factory_id}/credentials/{CREDENTIAL}", ADF_API)
    credential_properties = credential.get("properties", {})
    credential_identity = credential_properties.get("typeProperties", {}).get("resourceId", "")
    if (credential_properties.get("type") != "ManagedIdentity"
            or credential_identity.lower() != target.identity_id.lower()):
        raise ValueError("ls_cred_project_uami does not select the required project UAMI.")
    runtime = _required_arm(session, f"{factory_id}/integrationRuntimes/{INTEGRATION_RUNTIME}", ADF_API)
    if not _contains_expected(runtime.get("properties"), {
        "type": "Managed", "managedVirtualNetwork": {"referenceName": "default"},
    }):
        raise ValueError("AutoResolveIntegrationRuntime must run in ADF managed VNet default.")
    lake = _required_arm(session, f"{factory_id}/linkedservices/ls_storage_lake", ADF_API)
    if not _contains_expected(lake.get("properties"), {
        "type": "AzureBlobFS", "typeProperties": {
            "url": f"https://{target.storage_name}.dfs.core.windows.net",
            "credential": _reference(CREDENTIAL, "CredentialReference"),
        },
    }):
        raise ValueError("Project storage linked service does not use the selected 2001 account and UAMI.")
    storage = _required_arm(session, target.storage_id, STORAGE_API)
    if (storage.get("properties", {}).get("publicNetworkAccess", "").lower() != "disabled"
            or storage.get("properties", {}).get("allowBlobPublicAccess") is not False):
        raise ValueError("Storage public network and anonymous Blob access must already be disabled.")
    service = _required_arm(session, _search_id(target), SEARCH_ARM_API)
    if service.get("properties", {}).get("publicNetworkAccess", "").lower() != "disabled":
        raise ValueError("Search public network access must already be disabled.")
    if service.get("properties", {}).get("semanticSearch", "").lower() not in {"free", "standard"}:
        raise ValueError("Search semantic ranking must already be enabled; no paid-plan upgrade is performed.")
    identity = service.get("identity", {})
    principal = identity.get("principalId")
    if "SystemAssigned" not in identity.get("type", "") or not principal:
        raise ValueError("This ADF path requires Search system-assigned MI with Storage Blob Data Reader; no identity is attached automatically.")
    return principal


def approve_storage_connection(session: AzureSession, target: Target, *,
                               connection_id: str, expected_private_endpoint_id: str) -> dict:
    """Approve one explicitly identified connection, never every pending storage request."""
    validate_target(target)
    prefix = target.storage_id + "/privateEndpointConnections/"
    if not connection_id.lower().startswith(prefix.lower()) or "/" in connection_id[len(prefix):]:
        raise ValueError("The connection must be an immediate child of the selected 2001 storage account.")
    connection = session.arm("GET", connection_id, api_version=STORAGE_API)
    properties = connection["properties"]
    endpoint_id = properties.get("privateEndpoint", {}).get("id", "")
    if not expected_private_endpoint_id or endpoint_id.lower() != expected_private_endpoint_id.lower():
        raise ValueError("The storage request does not match the explicitly selected private endpoint.")
    status = properties["privateLinkServiceConnectionState"]["status"]
    if status == "Pending":
        session.arm("PUT", connection_id, {"properties": {"privateLinkServiceConnectionState": {
            "status": "Approved", "description": "Approved for the selected AI Factory private ingestion path.",
        }}}, api_version=STORAGE_API)
        connection = session.arm("GET", connection_id, api_version=STORAGE_API)
        status = connection["properties"]["privateLinkServiceConnectionState"]["status"]
    if status != "Approved":
        raise RuntimeError(f"Storage connection is {status}, not Approved; no rejected request is overridden.")
    return {"connection_id": connection_id, "private_endpoint_id": endpoint_id, "status": status}


def configure_datafactory_ingestion(session: AzureSession, target: Target, *, factory_name: str) -> dict:
    """Deploy only task-owned definitions; return pending network approval explicitly."""
    definitions = build_datafactory_definitions(target, factory_name=factory_name)
    require_private_endpoint(target.search_endpoint)
    search_principal = _preflight(session, target, definitions)
    factory_id = definitions["factory_id"]
    container_id = f"{target.storage_id}/blobServices/default/containers/{CONTAINER}"
    _ensure_owned_arm(session, container_id, {
        "properties": {"publicAccess": "None", "metadata": {"owner": ADF_OWNER}},
    }, STORAGE_API)
    adf_link = _private_link(
        session, f"{factory_id}/managedVirtualNetworks/default/managedPrivateEndpoints",
        "aif-kaggle-storage-blob", target, search=False,
    )
    search_link = _private_link(
        session, f"{_search_id(target)}/sharedPrivateLinkResources",
        "aif-kaggle-storage-blob", target, search=True,
    )
    for name, body in definitions["linked_services"].items():
        _ensure_owned_arm(session, f"{factory_id}/linkedservices/{name}", body, ADF_API)
    for name, body in definitions["datasets"].items():
        _ensure_owned_arm(session, f"{factory_id}/datasets/{name}", body, ADF_API)
    _ensure_owned_arm(session, f"{factory_id}/pipelines/{PIPELINE_NAME}", definitions["pipeline"], ADF_API)
    ready = adf_link["approved"] and search_link["approved"]
    if ready:
        index_url = search_url(target, f"indexes/{INDEX_NAME}")
        try:
            current = session.request("GET", index_url, audience=SEARCH_AUDIENCE)
        except AzureError as exc:
            if exc.status != 404:
                raise
            session.request("PUT", index_url, index_schema(INDEX_NAME), audience=SEARCH_AUDIENCE,
                            headers={"If-None-Match": "*", "Prefer": "return=representation"})
            current = session.request("GET", index_url, audience=SEARCH_AUDIENCE)
        validate_index(current, INDEX_NAME)
        inventory = session.request(
            "POST", search_url(target, f"indexes/{INDEX_NAME}/docs/search"),
            {"search": "*", "select": "id,document_url", "count": True, "top": 1000}, audience=SEARCH_AUDIENCE,
        )
        if (type(inventory.get("@odata.count")) is not int or inventory["@odata.count"] > integrity_reference()["row_count"]
                or inventory["@odata.count"] != len(inventory.get("value", []))
                or any(row.get("document_url") != definitions["document_url"] for row in inventory.get("value", []))):
            raise ValueError("Existing index contains unrelated/unexpected documents; refusing ADF ownership.")
        _ensure_search_resource(session, search_url(target, f"datasources/{DATA_SOURCE_NAME}"), definitions["data_source"])
    return {
        "status": "configured" if ready else "awaiting-private-endpoint-approval",
        "factory_name": factory_name, "factory_id": factory_id, "pipeline_name": PIPELINE_NAME,
        "index_name": INDEX_NAME, "container": CONTAINER, "prefix": PREFIX,
        "project_identity_id": target.identity_id, "search_identity_principal_id": search_principal,
        "private_endpoints": [adf_link, search_link], "embeddings_required": False,
        "indexer_deferred_until_pipeline_success": True,
        "prerequisites": [
            "Project deployment must enable Data Factory with project UAMI, ls_cred_project_uami and managed VNet IR.",
            "Approve ADF Blob managed private endpoint on project storage; approve the existing DFS endpoint if other lake workloads need it.",
            "Approve Search Blob shared private link on project storage (Basic supports indexers WITHOUT skillsets).",
            f"Search system-assigned MI {search_principal} needs Storage Blob Data Reader on {target.storage_id}.",
            "Project UAMI needs Storage Blob Data Contributor; operator needs ADF/artifact and Search configuration permissions.",
            "Managed IR needs outbound public HTTPS to Kaggle and its signed download redirect; Azure services stay private.",
            "Foundry project MI needs Search Index Data Reader and an independent private runtime path for MCP.",
        ],
    }


def start_datafactory_ingestion(session: AzureSession, target: Target, *, factory_name: str) -> dict:
    configured = configure_datafactory_ingestion(session, target, factory_name=factory_name)
    if configured["status"] != "configured":
        raise RuntimeError("Private endpoints are not Approved/Succeeded; approve them and rerun configuration before starting ingestion.")
    response = session.arm(
        "POST", f"{configured['factory_id']}/pipelines/{PIPELINE_NAME}/createRun", {}, api_version=ADF_API,
    )
    run_id = str(UUID(response["runId"]))
    return {**configured, "status": "running", "run_id": run_id}


def _run_activities(session, factory_id, run_id, start_time):
    request = {
        "lastUpdatedAfter": start_time,
        "lastUpdatedBefore": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    rows = []
    seen = set()
    for _ in range(20):
        page = session.arm("POST", f"{factory_id}/pipelineruns/{run_id}/queryActivityruns", request, api_version=ADF_API)
        rows.extend(page.get("value", []))
        token = page.get("continuationToken")
        if not token:
            return rows
        if token in seen:
            raise RuntimeError("Repeated ADF activity continuation token.")
        seen.add(token)
        request["continuationToken"] = token
    raise RuntimeError("ADF activity result exceeded the page limit.")


def _verify_activity_evidence(activities):
    by_name = {row["activityName"]: row for row in activities}
    required = {
        "DownloadRaw", "SealRaw", "ValidateDownloadSize", "ValidateRawIntegrity", "ValidateCSVHeader",
        "CopyKnowledge", "CopyEvaluation", "ValidateKnowledge", "PublishKnowledge", "SealEvaluation",
        "InspectRaw", "InspectPublished", "InspectEvaluation", "ValidateArtifacts",
    }
    if any(by_name.get(name, {}).get("status") != "Succeeded" for name in required):
        raise RuntimeError("ADF run is missing successful integrity, projection, or publication activities.")
    pin = integrity_reference()
    raw = by_name["InspectRaw"].get("output", {})
    if raw.get("size") != pin["bytes"] or raw.get("contentMD5") != pin["raw_md5_base64"]:
        raise RuntimeError("ADF did not verify the pinned raw CSV size and Content-MD5.")
    metadata = {"raw": {"bytes": raw["size"], "md5_base64": raw["contentMD5"]}}
    for label, activity in (("knowledge", "InspectPublished"), ("evaluation", "InspectEvaluation")):
        output = by_name[activity].get("output", {})
        if not isinstance(output.get("size"), int) or output["size"] <= 0 or not output.get("contentMD5"):
            raise RuntimeError(f"ADF {label} Blob persistence/checksum evidence is missing.")
        metadata[label] = {"bytes": output["size"], "md5_base64": output["contentMD5"]}
    return metadata


def verify_datafactory_index(session: AzureSession, target: Target) -> dict:
    """Read only Search text (never raw/evaluation blobs) and verify the pinned corpus."""
    validate_target(target)
    require_private_endpoint(target.search_endpoint)
    validate_index(session.request("GET", search_url(target, f"indexes/{INDEX_NAME}"),
                                   audience=SEARCH_AUDIENCE), INDEX_NAME)
    response = session.request(
        "POST", search_url(target, f"indexes/{INDEX_NAME}/docs/search"),
        {"search": "*", "count": True, "top": 1000,
         "select": "id,topic,content,source_url,source_version,license,attribution,dataset_sha256,document_url"},
        audience=SEARCH_AUDIENCE,
    )
    pin = integrity_reference()
    expected = {item["id"]: item for item in pin["documents"]}
    rows = response.get("value", [])
    if response.get("@odata.count") != len(expected) or len(rows) != len(expected):
        raise RuntimeError("Search does not contain the complete pinned knowledge corpus; not ready for IQ.")
    document_url = f"https://{target.storage_name}.blob.core.windows.net/{CONTAINER}/{PREFIX}/knowledge/items.json"
    seen = set()
    document_hashes = []
    keys = set()
    for row in rows:
        if not row.get("id") or row["id"] in keys or not isinstance(row.get("topic"), str) or not isinstance(row.get("content"), str):
            raise RuntimeError("Search returned invalid or duplicate document keys/content.")
        keys.add(row["id"])
        topic = row["topic"].strip()
        content = row["content"].replace("\r\n", "\n").replace("\r", "\n").strip()
        canonical_id = sha256(json_bytes([topic, content]))
        content_hash = sha256(content.encode("utf-8"))
        if (canonical_id not in expected or canonical_id in seen
                or expected[canonical_id]["content_sha256"] != content_hash):
            raise RuntimeError("Indexed knowledge content differs from the pinned corpus or contains duplicates.")
        for field, value in (
            ("document_url", document_url), ("source_url", DATASET_URL), ("source_version", DATASET_VERSION),
            ("license", "MIT"), ("attribution", ATTRIBUTION), ("dataset_sha256", pin["raw_sha256"]),
        ):
            if row.get(field) != value:
                raise RuntimeError(f"Indexed provenance field {field} is missing or incompatible.")
        seen.add(canonical_id)
        document_hashes.append({"search_id": row["id"], "canonical_id": canonical_id, "content_sha256": content_hash})
    probe = session.request(
        "POST", search_url(target, f"indexes/{INDEX_NAME}/docs/search"),
        {"search": rows[0]["topic"], "queryType": "semantic",
         "semanticConfiguration": SEMANTIC_CONFIGURATION, "select": "id", "top": 1}, audience=SEARCH_AUDIENCE,
    )
    if not probe.get("value") or probe["value"][0].get("@search.rerankerScore") is None:
        raise RuntimeError("Semantic ranking failed or its quota is exhausted; no paid upgrade is performed.")
    return {"index_name": INDEX_NAME, "document_count": len(rows), "corpus_sha256_verified": True,
            "documents": document_hashes, "embeddings_required": False}


def poll_datafactory_ingestion(session: AzureSession, target: Target, *, factory_name: str,
                               run_id: str, timeout_seconds: int = 3600, poll_interval: int = 15) -> dict:
    """Wait for verified ADF publication, then run/poll the private Search indexer."""
    if timeout_seconds < 1 or poll_interval < 1:
        raise ValueError("Polling timeout and interval must be positive.")
    run_id = str(UUID(run_id))
    definitions = build_datafactory_definitions(target, factory_name=factory_name)
    factory_id = definitions["factory_id"]
    require_private_endpoint(target.search_endpoint)
    _preflight(session, target, definitions)
    current_pipeline = session.arm("GET", f"{factory_id}/pipelines/{PIPELINE_NAME}", api_version=ADF_API)
    pipeline_properties = dict(current_pipeline.get("properties", {}))
    pipeline_properties.pop("provisioningState", None)
    pipeline_properties.pop("lastPublishTime", None)
    if not _compatible(pipeline_properties, definitions["pipeline"]["properties"]):
        raise ValueError("ADF pipeline definition changed; refusing to accept an unrelated run.")
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = session.arm("GET", f"{factory_id}/pipelineruns/{run_id}", api_version=ADF_API)
        if run.get("pipelineName") != PIPELINE_NAME or run.get("parameters"):
            raise ValueError("Run does not belong to the pinned factory ingestion pipeline.")
        status = run.get("status")
        if status == "Succeeded":
            break
        if status in {"Failed", "Cancelled", "Canceling"}:
            # Runtime messages can include signed URLs or CSV rows. Do not echo them.
            raise RuntimeError(f"ADF ingestion {run_id} ended with status {status}; inspect secured ADF monitoring.")
        if status not in {"Queued", "InProgress"}:
            raise RuntimeError(f"Unexpected ADF ingestion status: {status}.")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"ADF ingestion still running: {run_id}; resume polling this run, do not create another.")
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    metadata = _verify_activity_evidence(_run_activities(session, factory_id, run_id, run["runStart"]))
    # Indexers run automatically on creation, so creation is deferred until data
    # passed all ADF integrity gates. Existing owned indexers run explicitly.
    _ensure_search_resource(session, search_url(target, f"datasources/{DATA_SOURCE_NAME}"), definitions["data_source"])
    indexer_url = search_url(target, f"indexers/{INDEXER_NAME}")
    try:
        existing = session.request("GET", indexer_url, audience=SEARCH_AUDIENCE)
    except AzureError as exc:
        if exc.status != 404:
            raise
        previous_start = None
        session.request("PUT", indexer_url, definitions["indexer"], audience=SEARCH_AUDIENCE,
                        headers={"If-None-Match": "*", "Prefer": "return=representation"})
    else:
        if not _compatible(existing, definitions["indexer"]):
            raise ValueError("Existing Search indexer is incompatible; refusing to run or overwrite it.")
        previous = session.request("GET", search_url(target, f"indexers/{INDEXER_NAME}/status"), audience=SEARCH_AUDIENCE)
        last = previous.get("lastResult") or {}
        if last.get("status") == "inProgress":
            # Resume the existing owned indexer; the pinned corpus is still verified below.
            previous_start = None
        else:
            previous_start = last.get("startTime")
            session.request("POST", search_url(target, f"indexers/{INDEXER_NAME}/run"), audience=SEARCH_AUDIENCE)
    while True:
        response = session.request("GET", search_url(target, f"indexers/{INDEXER_NAME}/status"), audience=SEARCH_AUDIENCE)
        result = response.get("lastResult") or {}
        fresh = result.get("startTime") and result.get("startTime") != previous_start
        if fresh and result.get("status") not in {"inProgress", "reset"}:
            if (result.get("status") != "success" or result.get("itemsFailed", 0) != 0
                    or result.get("errors") or result.get("warnings") or not result.get("endTime")):
                raise RuntimeError("Private Search indexer failed or reported errors/warnings; ingestion is incomplete.")
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Search indexer has not completed for ADF run {run_id}.")
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    # Search document visibility can lag the successful indexer result briefly.
    for attempt in range(5):
        try:
            verified = verify_datafactory_index(session, target)
            break
        except RuntimeError as exc:
            if "complete pinned knowledge corpus" not in str(exc) or attempt == 4:
                raise
            time.sleep(3)
    return {
        "status": "ingested", "factory_name": factory_name, "pipeline_name": PIPELINE_NAME, "run_id": run_id,
        "container": CONTAINER, "prefix": PREFIX, "blob_integrity": metadata,
        "expected_raw_sha256": integrity_reference()["raw_sha256"],
        "raw_integrity_method": "pinned-byte-count-and-content-md5",
        "raw_sha256_computed_by_adf": False, "knowledge_kwargs": {"index_name": INDEX_NAME},
        **verified,
    }


def run_datafactory_ingestion(session: AzureSession, target: Target, *, factory_name: str,
                              timeout_seconds: int = 3600, poll_interval: int = 15) -> dict:
    started = start_datafactory_ingestion(session, target, factory_name=factory_name)
    return poll_datafactory_ingestion(
        session, target, factory_name=factory_name, run_id=started["run_id"],
        timeout_seconds=timeout_seconds, poll_interval=poll_interval,
    )
