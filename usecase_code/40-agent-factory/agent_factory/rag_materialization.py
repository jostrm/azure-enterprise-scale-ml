"""Private, binary materialization of an operator-validated, hash-pinned RAG source.

The destination is approved for the project's shared readers, not per-user ACLs.
Source blobs are never written. ADF checks binary consistency, not SHA-256: callers
must verify_destination before indexing and journal createRun's ID before polling.
"""

from __future__ import annotations

from datetime import datetime
import re
import time
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from .azure import AzureError
from . import datafactory as adf, rag_sources
from .data import sha256, validate_target
from .knowledge import _compatible
from .rag_sources import MAX_BYTES, RagSource

CONTAINER = "agent-factory-rag"
OWNER = "45-rag-agent"
ROLE_API = "2022-04-01"
READER_ROLE = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"


def destination(source: RagSource) -> dict:
    validate_target(source.target)
    folder = f"sources/{source.binding_fingerprint}/knowledge"
    path = f"{folder}/items.{'jsonl' if source.location == 'common' else 'json'}"
    return {"storage_id": source.target.storage_id, "storage_name": source.target.storage_name,
            "container": CONTAINER, "blob_path": path, "query": folder + "/",
            "blob_url": f"https://{source.target.storage_name}.blob.core.windows.net/{CONTAINER}/{path}"}


def definitions(source: RagSource, factory_name: str) -> dict:
    """Immutable ARM definitions; only the exact selected file can be copied."""
    dest = destination(source)
    prefix = f"aif_rag_{source.binding_fingerprint}"
    names = {key: f"{prefix}_{key}" for key in ("source_blob", "destination_blob", "source", "destination", "copy")}
    owned = {"description": f"{OWNER};binding_fingerprint={source.binding_fingerprint}", "annotations": [OWNER]}
    services, datasets = {}, {}
    for side, storage, container, path in (
        ("source", source.storage_name, source.container, source.blob_path),
        ("destination", dest["storage_name"], dest["container"], dest["blob_path"]),
    ):
        services[names[side + "_blob"]] = {"properties": {
            **owned, "type": "AzureBlobStorage", "connectVia": adf._reference(adf.INTEGRATION_RUNTIME, "IntegrationRuntimeReference"),
            "typeProperties": {"serviceEndpoint": f"https://{storage}.blob.core.windows.net/",
                               "accountKind": "StorageV2", "credential": adf._reference(adf.CREDENTIAL, "CredentialReference")},
        }}
        folder, filename = path.rsplit("/", 1)
        datasets[names[side]] = {"properties": {
            **owned, "type": "Binary",
            "linkedServiceName": adf._reference(names[side + "_blob"], "LinkedServiceReference"),
            "typeProperties": {"location": {"type": "AzureBlobStorageLocation", "container": container,
                                            "folderPath": folder, "fileName": filename}},
        }}
    read = {"type": "AzureBlobStorageReadSettings", "recursive": False}

    def inspect(name, side, *dependencies):
        return {"name": name, "type": "GetMetadata", "dependsOn": adf._depends(*dependencies),
                # Only byte sizes are observable; content and Copy output stay secured.
                "policy": {**adf._policy(), "secureOutput": False},
                "typeProperties": {"dataset": adf._reference(names[side]), "fieldList": ["size"],
                                   "storeSettings": read}}

    pipeline = {"properties": {**owned, "concurrency": 1, "activities": [
        inspect("InspectPinnedSource", "source"),
        {"name": "CopyPinnedDocuments", "type": "Copy", "dependsOn": adf._depends("InspectPinnedSource"),
         "policy": adf._policy(), "inputs": [adf._reference(names["source"])],
         "outputs": [adf._reference(names["destination"])],
         "typeProperties": {"source": {"type": "BinarySource", "storeSettings": read},
                            "sink": {"type": "BinarySink", "storeSettings": {"type": "AzureBlobStorageWriteSettings"}},
                            "parallelCopies": 1, "enableStaging": False, "validateDataConsistency": True}},
        inspect("InspectMaterialized", "destination", "CopyPinnedDocuments"),
    ]}}
    return {"factory_id": adf._factory_id(source.target, factory_name), "factory_name": factory_name,
            "pipeline_name": names["copy"], "linked_services": services, "datasets": datasets,
            "pipeline": pipeline, "artifact_names": names, "destination": dest, "source": source.as_dict(),
            "target": source.target.to_dict(), "binding_fingerprint": source.binding_fingerprint}


def _validate(session, target, source):
    if not isinstance(source, RagSource) or source.target != target:
        raise ValueError("Materialization must retain the source's original project target.")
    validate_target(target)
    if (session.subscription_id.lower() != target.subscription_id.lower()
            or session.tenant_id.lower() != target.tenant_id.lower()):
        raise ValueError("Materialization session must match the selected subscription and tenant.")


def _optional(session, resource_id, api):
    try:
        return session.arm("GET", resource_id, api_version=api)
    except AzureError as exc:
        if exc.status != 404:
            raise
        return None


def _child(resource_id, collection):
    return (isinstance(resource_id, str) and resource_id.lower().startswith(collection.lower() + "/")
            and re.fullmatch(r"[A-Za-z0-9_.-]+", resource_id[len(collection) + 1:]) is not None)


def _link(session, factory_id, storage_id, location, apply=False):
    collection = factory_id + "/managedVirtualNetworks/default/managedPrivateEndpoints"
    rows = adf._arm_collection(session, collection, adf.ADF_API)
    matches = [row for row in rows if row.get("properties", {}).get("privateLinkResourceId", "").lower() == storage_id.lower()
               and row.get("properties", {}).get("groupId") == "blob"]
    name = f"aif-rag-{location}-{sha256(storage_id.lower().encode())[:8]}-blob"
    resource_id = f"{collection}/{name}"
    if len(matches) > 1:
        raise ValueError("Ambiguous ADF Blob managed private endpoints for the exact storage.")
    if not matches:
        if any(row.get("id", "").lower() == resource_id.lower() or row.get("name", "").split("/")[-1] == name for row in rows):
            raise ValueError("ADF managed private endpoint name belongs to a different target.")
        if apply and location == "common":
            session.arm("PUT", resource_id, {"properties": {
                "privateLinkResourceId": storage_id, "groupId": "blob",
            }}, api_version=adf.ADF_API)
            matches = [session.arm("GET", resource_id, api_version=adf.ADF_API)]
        else:
            return None
    link = matches[0]
    if (not _child(link.get("id"), collection)
            or link.get("properties", {}).get("privateLinkResourceId", "").lower() != storage_id.lower()
            or link["properties"].get("groupId") != "blob"):
        raise ValueError("ADF endpoint does not match the selected factory/storage/blob tuple.")
    return link


def reader_assignment(target, source, principal):
    """Allow exact content reads and list metadata only in this pinned version."""
    if source.location != "common":
        raise ValueError("No new project-source reader role is permitted.")
    UUID(principal)
    scope = f"{source.storage_id}/blobServices/default/containers/{source.container}"
    attribute = "Microsoft.Storage/storageAccounts/blobServices/containers"
    action, listing = f"ActionMatches{{'{attribute}/blobs/read'}}", "SubOperationMatches{'Blob.List'}"
    path = f"@Resource[{attribute}/blobs:path] StringEquals '{source.blob_path}'"
    container = f"@Resource[{attribute}:name] StringEquals '{source.container}'"
    # ADF may list the parent with a trailing slash or request the literal filename.
    prefixes = [source.blob_path.rsplit("/", 1)[0] + "/", source.blob_path]
    prefix = " OR ".join(f"@Request[{attribute}/blobs:prefix] StringEquals '{value}'" for value in prefixes)
    condition = f"((!({action} AND NOT {listing})) OR ({container} AND {path})) AND ((!({action} AND {listing})) OR ({container} AND ({prefix})))"
    name = uuid5(NAMESPACE_URL, f"{scope.lower()}|{principal.lower()}|{READER_ROLE}|{condition}")
    return scope, f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}", {"properties": {
        "principalId": principal, "principalType": "ServicePrincipal",
        "roleDefinitionId": f"/subscriptions/{target.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{READER_ROLE}",
        "conditionVersion": "2.0", "condition": condition,
    }}


def _reader(session, target, source, principal, grant):
    scope, resource_id, body = reader_assignment(target, source, principal)
    current = _optional(session, resource_id, ROLE_API)
    if current is None and grant:
        session.arm("PUT", resource_id, body, api_version=ROLE_API)
        current = session.arm("GET", resource_id, api_version=ROLE_API)
    if current is not None:
        props = current.get("properties", {})
        if (any(props.get(key) != value for key, value in body["properties"].items())
                or props.get("scope", "").lower() != scope.lower() or props.get("delegatedManagedIdentityResourceId")):
            raise ValueError("Existing reader assignment has changed principal, scope or condition; refusing downgrade.")
    return {"scope": scope, "role_assignment_id": resource_id, "verified": current is not None}


def _artifacts(session, source, bodies, apply):
    factory = bodies["factory_id"]
    resources = [(f"{source.target.storage_id}/blobServices/default/containers/{CONTAINER}", {
        "properties": {"publicAccess": "None", "metadata": {"owner": OWNER}},
    }, adf.STORAGE_API)]
    for kind, key in (("linkedservices", "linked_services"), ("datasets", "datasets")):
        resources.extend((f"{factory}/{kind}/{name}", body, adf.ADF_API) for name, body in bodies[key].items())
    resources.append((f"{factory}/pipelines/{bodies['pipeline_name']}", bodies["pipeline"], adf.ADF_API))
    missing = []
    for resource_id, body, api in resources:
        current = _optional(session, resource_id, api)
        if current is None and not apply:
            missing.append(resource_id)
            continue
        if not apply:
            actual = dict(current.get("properties", {}))
            if api == adf.STORAGE_API:
                actual["publicAccess"] = actual.get("publicAccess") or "None"
                compatible = adf._contains_expected(actual, body["properties"])
            else:
                for key in ("provisioningState", "lastPublishTime"):
                    actual.pop(key, None)
                compatible = _compatible(actual, body["properties"])
            if not compatible:
                raise ValueError("Existing materialization artifact drift; refusing execution.")
        else:
            adf._ensure_owned_arm(session, resource_id, body, api)
    return missing


def _correlated(connection, link, source, factory_name):
    props = connection.get("properties", {})
    endpoint = props.get("privateEndpoint", {}).get("id", "")
    if (not _child(connection.get("id"), source.storage_id + "/privateEndpointConnections")
            or not re.fullmatch(r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Network/privateEndpoints/[^/]+",
                                endpoint, re.I)):
        return False
    prefix = factory_name + "." + link["id"].rsplit("/", 1)[1]
    leaf = endpoint.rsplit("/", 1)[1]
    return re.fullmatch(re.escape(prefix) + r"(?:[.-][0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?", leaf, re.I) is not None


def configure_materialization(session, target, source, factory_name, *, apply=False, grant_read=False):
    """Plan by default. Applying creates metadata only, never starts a copy."""
    _validate(session, target, source)
    bodies = definitions(source, factory_name)
    adf._preflight(session, target, bodies)
    identity = session.arm("GET", target.identity_id, api_version="2023-01-31").get("properties", {})
    principal = str(UUID(identity["principalId"]))
    if identity.get("clientId", "").lower() != target.identity_client_id.lower():
        raise ValueError("Project UAMI client ID changed.")
    if source.location == "common":
        storage = session.arm("GET", source.storage_id, api_version=adf.STORAGE_API).get("properties", {})
        if (storage.get("publicNetworkAccess", "").lower() != "disabled" or storage.get("allowBlobPublicAccess") is not False
                or storage.get("isHnsEnabled") is not True):
            raise ValueError("Common storage must already be private HNS storage without anonymous access.")
    reader = (_reader(session, target, source, principal, apply and grant_read) if source.location == "common"
              else {"verified": None, "status": "existing-project-role-required"})
    link = _link(session, bodies["factory_id"], source.storage_id, source.location, apply)
    sink_link = link if source.location == "project" else _link(session, bodies["factory_id"], target.storage_id, "project")
    prerequisites = []
    for label, endpoint in (("source", link), ("destination", sink_link)):
        props = endpoint.get("properties", {}) if endpoint else {}
        if props.get("connectionState", {}).get("status") != "Approved" or props.get("provisioningState") != "Succeeded":
            prerequisites.append(f"Exact ADF {label} Blob endpoint must be Approved/Succeeded.")
    if source.location == "common" and not reader["verified"]:
        prerequisites.append("Explicitly grant the project UAMI the conditional common pinned-blob reader role.")
    missing = _artifacts(session, source, bodies, apply)
    if missing:
        prerequisites.append("Apply the missing owned materialization definitions.")
    pending = []
    if link:
        pending = [{"connection_id": row["id"], "private_endpoint_id": row["properties"]["privateEndpoint"]["id"]}
                   for row in adf._arm_collection(session, source.storage_id + "/privateEndpointConnections", adf.STORAGE_API)
                   if _correlated(row, link, source, factory_name)
                   and row["properties"].get("privateLinkServiceConnectionState", {}).get("status") == "Pending"]
    return {key: value for key, value in {
        **bodies, "status": "needs-setup" if prerequisites else "configured" if apply else "ready",
        "prerequisites": prerequisites, "project_identity_id": target.identity_id,
        "project_identity_principal_id": principal, "reader_permission": reader,
        "private_endpoints": [link, sink_link], "pending_storage_connections": pending, "content_verified": False,
    }.items() if key not in {"linked_services", "datasets", "pipeline"}}


def approve_materialization_link(session, target, source, factory_name, connection_id, expected_private_endpoint_id):
    _validate(session, target, source)
    if not _child(connection_id, source.storage_id + "/privateEndpointConnections"):
        raise ValueError("Approve only the selected source storage's exact connection.")
    link = _link(session, adf._factory_id(target, factory_name), source.storage_id, source.location)
    current = session.arm("GET", connection_id, api_version=adf.STORAGE_API)
    endpoint = current.get("properties", {}).get("privateEndpoint", {}).get("id", "")
    if (not expected_private_endpoint_id or endpoint.lower() != expected_private_endpoint_id.lower()
            or not link or not _correlated(current, link, source, factory_name)):
        raise ValueError("Requester is not the selected factory's exact Blob managed private endpoint.")
    status = current["properties"]["privateLinkServiceConnectionState"]["status"]
    if status == "Pending":
        session.arm("PUT", connection_id, {"properties": {"privateLinkServiceConnectionState": {
            "status": "Approved", "description": f"{OWNER}:{factory_name}.{link['id'].rsplit('/', 1)[1]}",
        }}}, api_version=adf.STORAGE_API)
        current = session.arm("GET", connection_id, api_version=adf.STORAGE_API)
    if (current["properties"]["privateLinkServiceConnectionState"]["status"] != "Approved"
            or current["properties"].get("privateEndpoint", {}).get("id", "").lower() != endpoint.lower()):
        raise RuntimeError("The exact selected connection is not Approved with its expected requester.")
    return {"connection_id": connection_id, "private_endpoint_id": endpoint, "status": "Approved"}


def start_materialization(session, target, source, factory_name):
    """Start once explicitly; persist run_id and resume polling instead of retrying."""
    configured = configure_materialization(session, target, source, factory_name)
    if configured["status"] != "ready":
        raise RuntimeError("Materialization is not configured with approved private endpoints and reader permission.")
    response = session.arm("POST", f"{configured['factory_id']}/pipelines/{configured['pipeline_name']}/createRun",
                           {}, api_version=adf.ADF_API)
    return {**configured, "status": "running", "run_id": str(UUID(response["runId"]))}


def verify_destination(session, target, source):
    """Bounded, private operator read of only staged bytes, checked against the source pin."""
    _validate(session, target, source)
    dest = destination(source)
    pinned = SimpleNamespace(config=source.config, storage_name=dest["storage_name"], container=dest["container"],
                             blob_path=dest["blob_path"], sha256=source.sha256, manifest_path="")
    raw = rag_sources.read_blob(session, pinned)
    if not raw or len(raw) > MAX_BYTES or sha256(raw) != source.sha256:
        raise ValueError("Materialized bytes are empty, oversized or differ from the approved source SHA-256.")
    return {"destination": dest, "binding_fingerprint": source.binding_fingerprint,
            "source": source.as_dict(), "target": target.to_dict(),
            "bytes": len(raw), "sha256": source.sha256, "content_verified": True}


def poll_materialization(session, target, source, factory_name, run_id, *, timeout_seconds=600, poll_interval=10):
    """Poll this exact run, never restart; reject zero/missing/failed copy evidence."""
    _validate(session, target, source)
    if type(timeout_seconds) is not int or type(poll_interval) is not int or min(timeout_seconds, poll_interval) < 1:
        raise ValueError("Polling timeout and interval must be positive integers.")
    run_id = str(UUID(run_id))
    bodies = definitions(source, factory_name)
    if _artifacts(session, source, bodies, False):
        raise ValueError("Pinned materialization definitions are missing.")
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = session.arm("GET", f"{bodies['factory_id']}/pipelineruns/{run_id}", api_version=adf.ADF_API)
        if run.get("runId") != run_id or run.get("pipelineName") != bodies["pipeline_name"] or run.get("parameters"):
            raise ValueError("Run does not belong to this exact pinned materialization pipeline.")
        if run.get("status") == "Succeeded":
            break
        if run.get("status") not in {"Queued", "InProgress"}:
            raise RuntimeError("ADF copy failed or has an unexpected status; inspect secured ADF monitoring.")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"ADF copy still running: {run_id}; resume polling this run, do not restart.")
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    try:
        start = datetime.fromisoformat(run["runStart"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError):
        raise RuntimeError("ADF run lacks timestamp evidence.") from None
    rows = adf._run_activities(session, bodies["factory_id"], run_id, run["runStart"])
    names = {"InspectPinnedSource", "CopyPinnedDocuments", "InspectMaterialized"}
    if len(rows) != 3 or {row.get("activityName") for row in rows} != names:
        raise RuntimeError("ADF run lacks unique source, copy and destination activity evidence.")
    def failed(row):
        error = row.get("error") or {}
        error = any(error.get(key) for key in ("errorCode", "message", "failureType", "details")) if isinstance(error, dict) else error
        output = row.get("output") or {}
        return (row.get("status") != "Succeeded" or error or output.get("errors") or output.get("warnings")
                or any(detail.get("errors") or detail.get("warnings") or detail.get("status") not in (None, "Succeeded")
                       for detail in output.get("executionDetails", [])))

    if any(failed(row) for row in rows):
        raise RuntimeError("ADF activity failed, warned or has missing success evidence.")
    outputs = {row["activityName"]: row.get("output", {}) for row in rows}
    sizes = [outputs[name].get("size") for name in ("InspectPinnedSource", "InspectMaterialized")]
    copy = outputs["CopyPinnedDocuments"]
    if (any(type(size) is not int or not 0 < size <= MAX_BYTES for size in sizes) or sizes[0] != sizes[1]
            or any(key in copy and (type(copy[key]) is not int or copy[key] != sizes[0]) for key in ("dataRead", "dataWritten"))
            or any(copy.get(key, 0) != 0 for key in ("filesSkipped", "rowsSkipped"))):
        raise RuntimeError("ADF binary copy byte counts are empty, missing, oversized or inconsistent.")
    verified = verify_destination(session, target, source)
    if verified["bytes"] != sizes[1]:
        raise RuntimeError("Verified staged size differs from ADF persistence evidence.")
    return {**verified, "factory_id": bodies["factory_id"], "factory_name": factory_name,
            "pipeline_name": bodies["pipeline_name"], "artifact_names": bodies["artifact_names"],
            "run_id": run_id, "status": "succeeded",
            "byte_evidence": "copy-output-and-metadata" if {"dataRead", "dataWritten"} <= copy.keys() else "metadata-with-sha256",
            "data_read": sizes[0], "data_written": sizes[1]}
