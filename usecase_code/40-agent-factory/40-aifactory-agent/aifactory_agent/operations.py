from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.storage.blob import ContainerClient
from azurefactory.client import redact_secrets, validate_base_url
from azurefactory.errors import APIError, RequestTimeout
from pydantic import ValidationError

from .config import Settings, credential
from .security import Principal, authorize
from .signing import KeyVaultRecordSigner, SigningError
from .tools import CONFIGURE_TOOL, ToolError, _deadline, _select_scope, validate_configuration_plan


class OperationError(ToolError):
    def __init__(self, code, message, status_code=409, *, uncertain=False):
        super().__init__(code, message, status_code)
        self.uncertain = uncertain


class _Conflict(Exception):
    pass


class _Missing(Exception):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


_PLAN_FIELDS = (
    "id", "correlation_id", "tenant_id", "object_id", "scope_key", "scope",
    "tool_name", "factory_api_url", "request", "preview", "created_at", "expires_at", "affected_resources",
)


def plan_hash(operation: dict) -> str:
    return hashlib.sha256(_json({key: operation[key] for key in _PLAN_FIELDS}).encode("utf-8")).hexdigest()


class MemoryOperationBackend:
    """Explicit test injection only; production never falls back to this backend."""

    def __init__(self):
        self._lock = threading.Lock()
        self._records = {}
        self.events = []

    def ensure_ready(self):
        pass

    def create(self, key, record):
        with self._lock:
            if key in self._records:
                raise _Conflict
            self._records[key] = (copy.deepcopy(record), 1)
            return 1

    def read(self, key):
        with self._lock:
            if key not in self._records:
                raise _Missing
            return copy.deepcopy(self._records[key])

    def replace(self, key, record, etag):
        with self._lock:
            if key not in self._records:
                raise _Missing
            if self._records[key][1] != etag:
                raise _Conflict
            self._records[key] = (copy.deepcopy(record), etag + 1)
            return etag + 1

    def list_keys(self, prefix):
        with self._lock:
            return sorted(key for key in self._records if key.startswith(prefix))

    def audit(self, event):
        with self._lock:
            self.events.append(copy.deepcopy(event))


class BlobOperationBackend:
    """Uses an IaC-owned container, operation ETags and separate immutable audit blobs."""

    def __init__(self, settings, cred=None, *, container=None, signer=None):
        self.signer = signer if signer is not None else KeyVaultRecordSigner(settings, cred)
        self.container = container if container is not None else ContainerClient(
            account_url=settings.azure.storage_endpoint,
            container_name=settings.azure.storage_container,
            credential=cred or credential(settings),
        )

    def ensure_ready(self):
        try:
            self.signer.ensure_ready()
        except SigningError as exc:
            raise OperationError(exc.code, str(exc), exc.status_code) from None

    def _signed(self, record):
        try:
            return self.signer.sign(record)
        except SigningError as exc:
            raise OperationError(exc.code, str(exc), exc.status_code) from None

    def create(self, key, record):
        signed = self._signed(record)
        try:
            response = self.container.get_blob_client(key).upload_blob(_json(signed), overwrite=False)
            record.clear()
            record.update(signed)
            return response["etag"]
        except ResourceExistsError:
            raise _Conflict from None
        except AzureError:
            raise OperationError("store_unavailable", "Durable operation storage is unavailable.", 503) from None

    def read(self, key):
        try:
            download = self.container.get_blob_client(key).download_blob()
            record = json.loads(download.readall())
            self.signer.verify(record)
            return record, download.properties.etag
        except SigningError as exc:
            raise OperationError(exc.code, str(exc), exc.status_code) from None
        except ResourceNotFoundError:
            raise _Missing from None
        except (AzureError, ValueError, UnicodeDecodeError):
            raise OperationError("store_unavailable", "The durable operation record could not be read.", 503) from None

    def replace(self, key, record, etag):
        signed = self._signed(record)
        try:
            response = self.container.get_blob_client(key).upload_blob(
                _json(signed), overwrite=True, etag=etag, match_condition=MatchConditions.IfNotModified,
            )
            record.clear()
            record.update(signed)
            return response["etag"]
        except (ResourceModifiedError, ResourceExistsError):
            raise _Conflict from None
        except ResourceNotFoundError:
            raise _Missing from None
        except AzureError:
            raise OperationError("store_unavailable", "The durable operation update could not be confirmed.", 503,
                                 uncertain=True) from None

    def list_keys(self, prefix):
        try:
            return [blob.name for blob in self.container.list_blobs(name_starts_with=prefix)]
        except AzureError:
            raise OperationError("store_unavailable", "Durable operations could not be listed.", 503) from None

    def audit(self, event):
        key = f"audit/{event['tenant_id']}/{event['object_id']}/{event['operation_id']}/{uuid4()}.json"
        signed = self._signed(event)
        try:
            self.container.get_blob_client(key).upload_blob(_json(signed), overwrite=False)
        except AzureError:
            raise OperationError("audit_unavailable", "The durable audit event could not be persisted.", 503) from None


class OperationStore:
    def __init__(self, settings: Settings, cred=None, *, backend=None, clock=None, ttl_seconds=900):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError("Approval lifetime must be between 1 and 900 seconds.")
        self.settings = settings
        self.backend = backend if backend is not None else BlobOperationBackend(settings, cred)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ttl_seconds = ttl_seconds

    def ensure_ready(self):
        self.backend.ensure_ready()

    def _now(self):
        result = self.clock()
        if not isinstance(result, datetime) or result.tzinfo is None:
            raise ValueError("The approval clock must return a timezone-aware datetime.")
        return result.astimezone(timezone.utc)

    @staticmethod
    def _prefix(principal):
        return f"operations/{principal.tenant_id}/{principal.object_id}/"

    def _key(self, principal, operation_id):
        try:
            identifier = str(UUID(str(operation_id)))
        except (ValueError, TypeError, AttributeError):
            raise OperationError("operation_not_found", "The operation was not found.", 404) from None
        return self._prefix(principal) + identifier + ".json"

    def _writes(self, principal, scope_key):
        scope = authorize(self.settings, principal, scope_key, "config.write")
        if scope.environment not in self.settings.factory.allowed_write_environments:
            raise OperationError("environment_not_enabled", "Writes are not enabled for this environment.", 403)
        authorize(self.settings, principal, scope_key, "factory.read")
        if not self.settings.factory.writes_enabled:
            raise OperationError("writes_disabled", "Factory configuration writes are disabled.", 503)

    def _load(self, principal, operation_id):
        try:
            record, etag = self.backend.read(self._key(principal, operation_id))
        except _Missing:
            raise OperationError("operation_not_found", "The operation was not found.", 404) from None
        if not isinstance(record, dict) or any(key not in record for key in (*_PLAN_FIELDS, "plan_hash", "status")):
            raise OperationError("invalid_operation_record", "The durable operation record is incomplete.", 503)
        if (
            record.get("tenant_id") != principal.tenant_id or record.get("object_id") != principal.object_id
            or record.get("id") != str(UUID(str(operation_id)))
        ):
            raise PermissionError("An approval belongs to another authenticated caller.")
        authorize(self.settings, principal, record["scope_key"], "factory.read")
        if (
            record["scope"] != self.settings.scopes[record["scope_key"]].model_dump(mode="json")
            or record["factory_api_url"] != validate_base_url(self.settings.factory.api_url)
            or record.get("plan_hash") != plan_hash(record)
        ):
            raise OperationError("plan_changed", "The reviewed plan or scope has changed; prepare again.")
        return record, etag

    def _audit(self, record, event):
        self.backend.audit({
            "operation_id": record["id"], "correlation_id": record["correlation_id"],
            "tenant_id": record["tenant_id"], "object_id": record["object_id"],
            "scope_key": record["scope_key"], "plan_hash": record["plan_hash"],
            "event": event, "status": record["status"], "timestamp": self._now().isoformat(),
        })

    def _transition(self, principal, record, etag, status, *, outcome=None):
        updated = copy.deepcopy(record)
        updated["status"] = status
        updated["updated_at"] = self._now().isoformat()
        if status == "approved":
            updated["approval"] = {
                "tenant_id": principal.tenant_id, "object_id": principal.object_id,
                "plan_hash": updated["plan_hash"], "approved_at": updated["updated_at"],
            }
        if outcome is not None:
            updated["outcome"] = redact_secrets(outcome, None)
        try:
            version = self.backend.replace(self._key(principal, record["id"]), updated, etag)
        except _Conflict:
            raise OperationError("operation_conflict", "Another request already changed this operation.") from None
        except _Missing:
            raise OperationError("operation_not_found", "The operation was not found.", 404) from None
        self._audit(updated, status)
        return updated, version

    def _unexpired(self, principal, record, etag):
        if _deadline(record["expires_at"]) <= self._now():
            if record["status"] in ("pending", "approved"):
                self._transition(principal, record, etag, "expired")
            raise OperationError("plan_expired", "The reviewed approval expired; prepare again.")

    def propose(self, principal, scope_key, tool_name, request, preview) -> dict:
        self._writes(principal, scope_key)
        self.ensure_ready()
        if tool_name != CONFIGURE_TOOL:
            raise OperationError("unsupported_operation", "Only reviewed department metadata configuration is supported.")
        try:
            validate_configuration_plan(self.settings, scope_key, request, preview)
        except ValidationError:
            raise OperationError("invalid_plan", "The metadata plan does not match the closed schema.", 400) from None
        now = self._now()
        expires = min(_deadline(preview["expires_at"]), now + timedelta(seconds=self.ttl_seconds))
        if expires <= now:
            raise OperationError("plan_expired", "The underlying Factory review has already expired.")
        factory, scale, project, placement = _select_scope(
            self.settings, scope_key, {"factories": [preview["target"]]}, single_placement=True,
        )
        # Persist only the reviewed target, never the surrounding catalog or credential-bearing settings.
        review = {key: preview[key] for key in (
            "contract_version", "confirmation_id", "can_execute", "source_revision", "operation_mode",
            "expires_at", "factory_id", "scale_set_id", "project_id", "blockers", "effects", "warnings",
        )}
        review["summary"] = "Configure project department display metadata only; no Azure deployment."
        review["target"] = {
            "id": factory["id"], "prefix": factory["prefix"],
            "scale_sets": [{key: scale[key] for key in ("id", "environment", "tenant_id", "subscription_id")}],
            "projects": [{"id": project["id"], "number": project["number"], "placements": [placement]}],
        }
        scope = self.settings.scopes[scope_key].model_dump(mode="json")
        record = {
            "id": str(uuid4()), "correlation_id": str(uuid4()),
            "tenant_id": principal.tenant_id, "object_id": principal.object_id,
            "scope_key": scope_key, "scope": scope, "tool_name": tool_name,
            "factory_api_url": validate_base_url(self.settings.factory.api_url),
            "request": copy.deepcopy(request), "preview": review,
            "created_at": now.isoformat(), "expires_at": expires.isoformat(), "updated_at": now.isoformat(),
            "affected_resources": [{
                "kind": "project-department-configuration", "factory_id": request["factory_id"],
                "scale_set_id": request["scale_set_id"], "project_id": request["project_id"],
                "tenant_id": scope["tenant_id"], "subscription_id": scope["subscription_id"],
                "resource_group": scope["resource_group"], "environment": scope["environment"],
                "settings_keys": sorted(request["settings"]),
            }],
            "status": "pending", "approval": None, "outcome": None,
        }
        record["plan_hash"] = plan_hash(record)
        try:
            self.backend.create(self._key(principal, record["id"]), record)
        except _Conflict:
            raise OperationError("operation_conflict", "The operation identifier already exists.") from None
        self._audit(record, "proposed")
        return self._public(record)

    def read(self, principal, operation_id) -> dict:
        record, _ = self._load(principal, operation_id)
        return self._public(record)

    def list(self, principal) -> list[dict]:
        result = []
        for key in self.backend.list_keys(self._prefix(principal)):
            identifier = key.rsplit("/", 1)[-1].removesuffix(".json")
            try:
                result.append(self.read(principal, identifier))
            except PermissionError:
                # A revoked scope must not appear in a caller's operation list.
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def approve(self, principal, operation_id, plan_hash) -> dict:
        record, etag = self._load(principal, operation_id)
        self._writes(principal, record["scope_key"])
        self._unexpired(principal, record, etag)
        if not isinstance(plan_hash, str) or plan_hash != record["plan_hash"]:
            raise OperationError("plan_hash_mismatch", "Approval must reference the exact reviewed plan hash.")
        if record["status"] != "pending":
            raise OperationError("operation_conflict", "Only pending, unused plans can be approved.")
        record, _ = self._transition(principal, record, etag, "approved")
        return self._public(record)

    def execute(self, principal, operation_id, callback: Callable[[dict], dict]) -> dict:
        record, etag = self._load(principal, operation_id)
        self._writes(principal, record["scope_key"])
        self._unexpired(principal, record, etag)
        if record["status"] != "approved":
            raise OperationError("approval_required", "Execution requires an approved, unused plan.")
        # CAS and durable audit precede the non-idempotent call. A crash here cannot cause replay.
        record, etag = self._transition(principal, record, etag, "executing")
        try:
            result = callback(copy.deepcopy(record))
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise OperationError("uncertain_result", "The callback did not confirm successful completion.",
                                     uncertain=True)
            status, outcome = "succeeded", result
        except OperationError as exc:
            status = "uncertain" if exc.uncertain else "failed"
            outcome = {"ok": False, "error": {"code": exc.code, "message": str(exc), "status_code": exc.status_code}}
        except PermissionError:
            status, outcome = "failed", {"ok": False, "error": {"code": "forbidden", "status_code": 403}}
        except (RequestTimeout, TimeoutError, ConnectionError, OSError, APIError):
            status, outcome = "uncertain", {
                "ok": False, "error": {"code": "completion_unknown", "status_code": 503,
                                      "message": "Factory completion is unknown; do not retry this confirmation."},
            }
        record, _ = self._transition(principal, record, etag, status, outcome=outcome)
        return self._public(record)

    def cancel(self, principal, operation_id) -> dict:
        record, etag = self._load(principal, operation_id)
        authorize(self.settings, principal, record["scope_key"], "config.write")
        if record["status"] not in ("pending", "approved"):
            raise OperationError("cannot_cancel", "Only unexecuted plans can be cancelled; underlying jobs cannot be cancelled.")
        record, _ = self._transition(principal, record, etag, "cancelled")
        return self._public(record)

    def _public(self, record):
        result = copy.deepcopy(record)
        expired = _deadline(record["expires_at"]) <= self._now()
        if expired and result["status"] in ("pending", "approved"):
            result["status"] = "expired"
        result["progress"] = {
            "phase": result["status"],
            "completion_known": result["status"] not in ("executing", "uncertain"),
            "retry_allowed": False,
            "underlying_job_cancellation_supported": False,
        }
        return result
