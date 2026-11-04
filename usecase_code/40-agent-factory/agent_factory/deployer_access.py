"""The deploying identity's own data-plane access for the late agent steps (70 chat agent, 72 live voice).

Contributor and User Access Administrator do not include data actions, so a pipeline identity can deploy the Foundry
account, the Search service and the storage account and still get 403 reading an agent, an index or a blob. These
steps therefore grant their service principal the documented least-privilege data roles on the exact scopes they use,
once (deterministic assignment names), and wait for RBAC propagation only after a new grant. A signed-in user is never
granted roles here: the report says which role to request instead.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from .azure import ARM

ROLE_API = "2022-04-01"
PROPAGATION_SECONDS = 120

FOUNDRY_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"  # formerly "Azure AI User"
COGNITIVE_SERVICES_USER = "a97b65f3-24c7-4388-baec-2e87135dc908"
COGNITIVE_SERVICES_DATA_CONTRIBUTOR = "19c28022-e58e-450d-a464-0b2a53034789"
STORAGE_BLOB_DATA_CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
STORAGE_BLOB_DATA_OWNER = "b7e6dc6d-f1e8-4753-8033-0f276bb0955b"
SEARCH_INDEX_DATA_CONTRIBUTOR = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"


@dataclass(frozen=True)
class Need:
    scope: str
    role: str
    role_name: str
    satisfied_by: frozenset[str]


def foundry_user(account_id: str) -> Need:
    """Agents, embeddings and Voice Live on the project Foundry account (all Microsoft.CognitiveServices/* data actions)."""
    return Need(account_id, FOUNDRY_USER, "Foundry User",
                frozenset({FOUNDRY_USER, COGNITIVE_SERVICES_USER, COGNITIVE_SERVICES_DATA_CONTRIBUTOR}))


def blob_container_contributor(storage_id: str, container: str) -> Need:
    return Need(f"{storage_id}/blobServices/default/containers/{container}", STORAGE_BLOB_DATA_CONTRIBUTOR,
                "Storage Blob Data Contributor", frozenset({STORAGE_BLOB_DATA_CONTRIBUTOR, STORAGE_BLOB_DATA_OWNER}))


def search_index_contributor(search_id: str) -> Need:
    return Need(search_id, SEARCH_INDEX_DATA_CONTRIBUTOR, "Search Index Data Contributor",
                frozenset({SEARCH_INDEX_DATA_CONTRIBUTOR}))


class ArmPort(Protocol):
    def arm(self, method: str, resource_id: str, body: dict | None = None, api_version: str = ...) -> dict: ...

    def pages(self, url: str, *, audience: str = ARM, field: str = "value") -> list[dict]: ...


def caller_principal(token: str) -> tuple[str, bool]:
    """Object ID and whether it is a service principal, from the ARM access token (no Microsoft Graph call)."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, binascii.Error) as error:
        raise ValueError("The Azure access token is not a readable JWT; cannot identify the deploying principal.") from error
    object_id = claims.get("oid")
    if not isinstance(object_id, str) or not object_id:
        raise ValueError("The Azure access token has no object ID (oid); cannot identify the deploying principal.")
    application = claims.get("idtyp") == "app" or not ({"upn", "unique_name", "scp"} & set(claims))
    return object_id, application


def _covers(assignment_scope: str, needed_scope: str) -> bool:
    granted, needed = assignment_scope.rstrip("/").lower(), needed_scope.rstrip("/").lower()
    return needed == granted or needed.startswith(granted + "/")


class DeployerAccess:
    """Ensures the deploying service principal holds each needed data role (Strategy: the principal source is injected)."""

    def __init__(self, session: ArmPort, principal: Callable[[], tuple[str, bool]], *,
                 sleep: Callable[[float], None] = time.sleep, propagation_seconds: float = PROPAGATION_SECONDS):
        self.session, self.principal = session, principal
        self.sleep, self.propagation_seconds = sleep, propagation_seconds

    @classmethod
    def for_session(cls, session) -> "DeployerAccess":
        return cls(session, lambda: caller_principal(session.token(ARM)))

    def ensure(self, needs: Iterable[Need], *, apply: bool) -> list[dict]:
        principal_id, service_principal = self.principal()
        rows, created = [], False
        for need in needs:
            row = {"role": need.role_name, "scope": need.scope}
            existing = self.session.pages(
                f"{ARM}{need.scope}/providers/Microsoft.Authorization/roleAssignments"
                f"?api-version={ROLE_API}&$filter=principalId%20eq%20'{principal_id}'")
            if any((item.get("properties") or {}).get("roleDefinitionId", "").lower().rsplit("/", 1)[-1] in need.satisfied_by
                   and _covers((item.get("properties") or {}).get("scope", ""), need.scope) for item in existing):
                rows.append({**row, "status": "unchanged"})
            elif not service_principal:
                rows.append({**row, "status": "missing", "detail": (
                    f"The signed-in user needs {need.role_name} on this scope; this step only grants roles to the "
                    "pipeline's service principal.")})
            elif not apply:
                rows.append({**row, "status": "would_create"})
            else:
                subscription = need.scope.split("/")[2]
                name = uuid.uuid5(uuid.NAMESPACE_URL, f"{need.scope}|{principal_id}|{need.role}".lower())
                self.session.arm("PUT", f"{need.scope}/providers/Microsoft.Authorization/roleAssignments/{name}", {
                    "properties": {
                        "roleDefinitionId": f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{need.role}",
                        "principalId": principal_id, "principalType": "ServicePrincipal",
                    }}, api_version=ROLE_API)
                rows.append({**row, "status": "created"})
                created = True
        if created:
            # Data-plane RBAC takes effect after the assignment is written; a first call right away can still get 403.
            self.sleep(self.propagation_seconds)
        return rows
