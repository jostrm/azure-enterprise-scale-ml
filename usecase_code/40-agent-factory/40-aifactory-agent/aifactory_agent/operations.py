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
    plan = {key: operation[key] for key in _PLAN_FIELDS}
    if "agent_namespace" in operation:
        plan["agent_namespace"] = operation["agent_namespace"]
    return hashlib.sha256(_json(plan).encode("utf-8")).hexdigest()


def observation_hash(operation: dict) -> str:
    return hashlib.sha256(_json(operation.get("observation") or operation.get("outcome")).encode("utf-8")).hexdigest()


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
    def __init__(self, settings: Settings, cred=None, *, backend=None, clock=None, ttl_seconds=900, namespace=None):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError("Approval lifetime must be between 1 and 900 seconds.")
        self.settings = settings
        self.backend = backend if backend is not None else BlobOperationBackend(settings, cred)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ttl_seconds = ttl_seconds
        namespace = settings.agent_name if namespace is None else namespace
        if namespace != settings.agent_name:
            raise ValueError("Operation namespace must match the configured agent name.")
        self.namespace = namespace

    def ensure_ready(self):
        self.backend.ensure_ready()

    def _now(self):
        result = self.clock()
        if not isinstance(result, datetime) or result.tzinfo is None:
            raise ValueError("The approval clock must return a timezone-aware datetime.")
        return result.astimezone(timezone.utc)

    def _prefix(self, principal):
        prefix = f"operations/{principal.tenant_id}/{principal.object_id}/"
        return prefix + f"agents/{self.namespace}/"

    def _key(self, principal, operation_id):
        try:
            identifier = str(UUID(str(operation_id)))
        except (ValueError, TypeError, AttributeError):
            raise OperationError("operation_not_found", "The operation was not found.", 404) from None
        return self._prefix(principal) + identifier + ".json"

    @staticmethod
    def _permission(tool_name):
        if tool_name == CONFIGURE_TOOL:
            return "config.write"
        from .skills import ACTION_SKILLS, WORKLOAD_SKILLS, SKILL_PERMISSIONS
        if tool_name not in (*ACTION_SKILLS, *WORKLOAD_SKILLS):
            raise OperationError("unsupported_operation", "Select a supported, reviewed Factory operation.", 400)
        return SKILL_PERMISSIONS[tool_name]

    def _writes(self, principal, scope_key, tool_name=CONFIGURE_TOOL):
        scope = authorize(self.settings, principal, scope_key, self._permission(tool_name))
        if scope.environment not in self.settings.factory.allowed_write_environments:
            raise OperationError("environment_not_enabled", "Writes are not enabled for this environment.", 403)
        authorize(self.settings, principal, scope_key, "factory.read")
        if not self.settings.factory.writes_enabled:
            raise OperationError("writes_disabled", "Factory configuration writes are disabled.", 503)
        from .skills import WORKLOAD_SKILLS
        enabled = (self.settings.workloads.enabled_skills if tool_name in WORKLOAD_SKILLS
                   else self.settings.actions.enabled_skills)
        if tool_name != CONFIGURE_TOOL and tool_name not in enabled:
            raise OperationError("skill_disabled", "This action is disabled by the deployment operator.", 503)

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
        if record.get("agent_namespace") != self.namespace:
            raise OperationError("agent_mismatch", "The operation belongs to another agent; prepare a new plan.", 403)
        authorize(self.settings, principal, record["scope_key"], "factory.read")
        authorize(self.settings, principal, record["scope_key"], self._permission(record["tool_name"]))
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
            "agent_namespace": record.get("agent_namespace"),
            "event": event, "status": record["status"], "timestamp": self._now().isoformat(),
        })

    def _transition(self, principal, record, etag, status, *, outcome=None, observation=None):
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
        if observation is not None:
            updated["observation"] = redact_secrets(observation, None)
        updated["progress"] = self._progress(updated)
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
        self._writes(principal, scope_key, tool_name)
        self.ensure_ready()
        try:
            if tool_name == CONFIGURE_TOOL:
                validate_configuration_plan(self.settings, scope_key, request, preview)
            else:
                from .skills import WORKLOAD_SKILLS
                if tool_name in WORKLOAD_SKILLS:
                    from .workloads import validate_workload_plan
                    validate_workload_plan(self.settings, scope_key, tool_name, request, preview)
                else:
                    from .actions import validate_action_plan
                    validate_action_plan(self.settings, scope_key, tool_name, request, preview)
        except ValidationError:
            raise OperationError("invalid_plan", "The plan does not match the closed schema.", 400) from None
        now = self._now()
        expires = min(_deadline(preview["expires_at"]), now + timedelta(seconds=self.ttl_seconds))
        if expires <= now:
            raise OperationError("plan_expired", "The underlying Factory review has already expired.")
        if tool_name == CONFIGURE_TOOL:
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
            affected_resources = [{
                "kind": "project-department-configuration", "factory_id": request["factory_id"],
                "scale_set_id": request["scale_set_id"], "project_id": request["project_id"],
                "tenant_id": str(self.settings.scopes[scope_key].tenant_id),
                "subscription_id": str(self.settings.scopes[scope_key].subscription_id),
                "resource_group": self.settings.scopes[scope_key].resource_group,
                "environment": self.settings.scopes[scope_key].environment,
                "settings_keys": sorted(request["settings"]),
            }]
        else:
            from .skills import WORKLOAD_SKILLS
            if tool_name in WORKLOAD_SKILLS:
                from .workloads import plan_details
            else:
                from .actions import plan_details
            review, affected_resources = plan_details(self.settings, scope_key, tool_name, request, preview)
        scope = self.settings.scopes[scope_key].model_dump(mode="json")
        record = {
            "id": str(uuid4()), "correlation_id": str(uuid4()),
            "tenant_id": principal.tenant_id, "object_id": principal.object_id,
            "scope_key": scope_key, "scope": scope, "tool_name": tool_name,
            "factory_api_url": validate_base_url(self.settings.factory.api_url),
            "request": copy.deepcopy(request), "preview": review,
            "created_at": now.isoformat(), "expires_at": expires.isoformat(), "updated_at": now.isoformat(),
            "affected_resources": affected_resources,
            "status": "pending", "approval": None, "outcome": None,
        }
        if self.namespace is not None:
            record["agent_namespace"] = self.namespace
        record["plan_hash"] = plan_hash(record)
        record["progress"] = self._progress(record)
        try:
            self.backend.create(self._key(principal, record["id"]), record)
        except _Conflict:
            raise OperationError("operation_conflict", "The operation identifier already exists.") from None
        self._audit(record, "proposed")
        return self._public(record)

    def read(self, principal, operation_id) -> dict:
        record, etag = self._load(principal, operation_id)
        if record["status"] in ("pending", "approved") and _deadline(record["expires_at"]) <= self._now():
            record, _ = self._transition(principal, record, etag, "expired")
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

    def approve(self, principal, operation_id, plan_hash, *, confirmation_phrase=None) -> dict:
        record, etag = self._load(principal, operation_id)
        self._writes(principal, record["scope_key"], record["tool_name"])
        self._unexpired(principal, record, etag)
        if not isinstance(plan_hash, str) or plan_hash != record["plan_hash"]:
            raise OperationError("plan_hash_mismatch", "Approval must reference the exact reviewed plan hash.")
        if record["status"] != "pending":
            raise OperationError("operation_conflict", "Only pending, unused plans can be approved.")
        if record["tool_name"] != CONFIGURE_TOOL:
            from .skills import WORKLOAD_SKILLS
            if record["tool_name"] in WORKLOAD_SKILLS:
                from .workloads import validate_workload_plan
                validate_workload_plan(self.settings, record["scope_key"], record["tool_name"],
                                       record["request"], record["preview"])
                if confirmation_phrase is not None:
                    raise OperationError("invalid_approval", "Workload creation does not accept a deletion phrase.", 400)
            else:
                from .actions import validate_action_plan, validate_destructive_approval
                validate_action_plan(self.settings, record["scope_key"], record["tool_name"],
                                     record["request"], record["preview"])
                validate_destructive_approval(record, confirmation_phrase)
        elif confirmation_phrase is not None:
            raise OperationError("invalid_approval", "This operation does not accept a deletion confirmation phrase.", 400)
        record, _ = self._transition(principal, record, etag, "approved")
        return self._public(record)

    def execute(self, principal, operation_id, callback: Callable[[dict], dict]) -> dict:
        record, etag = self._load(principal, operation_id)
        self._writes(principal, record["scope_key"], record["tool_name"])
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
            status = result.get("execution_status", "succeeded")
            if status not in ("running", "awaiting_continuation", "succeeded"):
                raise OperationError("uncertain_result", "The callback returned an unsupported execution state.",
                                     uncertain=True)
            outcome = result
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

    def observe(self, principal, operation_id, callback: Callable[[dict], dict]) -> dict:
        """Observe an already-started job without re-confirming or continuing it."""
        record, etag = self._load(principal, operation_id)
        if record["status"] not in ("running", "awaiting_continuation"):
            return self._public(record)
        result = callback(copy.deepcopy(record))
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise OperationError("status_unavailable", "The existing Factory job status could not be confirmed.", 503)
        status = result.get("execution_status")
        if status not in ("running", "awaiting_continuation", "succeeded", "failed", "uncertain"):
            raise OperationError("status_unavailable", "The existing Factory job returned an unsupported status.", 502)
        record, _ = self._transition(principal, record, etag, status, observation=result)
        return self._public(record)

    def continue_operation(self, principal, operation_id, expected_plan_hash, expected_observation_hash,
                           callback: Callable[[dict], dict]) -> dict:
        from .actions import CREATE
        record, etag = self._load(principal, operation_id)
        self._writes(principal, record["scope_key"], record["tool_name"])
        if record["tool_name"] != CREATE or record["status"] != "awaiting_continuation":
            raise OperationError("continuation_required", "Only a paused approved Full bootstrap can be continued.")
        if (expected_plan_hash != record["plan_hash"] or expected_observation_hash != observation_hash(record)):
            raise OperationError("continuation_changed", "Review the exact current plan and paused-stage observation.")
        record, etag = self._transition(principal, record, etag, "continuing")
        try:
            result = callback(copy.deepcopy(record))
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise OperationError("uncertain_result", "Workflow continuation could not be confirmed.", uncertain=True)
            status = result.get("execution_status")
            if status not in ("running", "awaiting_continuation", "succeeded"):
                raise OperationError("uncertain_result", "Workflow continuation returned an unsupported state.", uncertain=True)
        except OperationError as exc:
            status = "uncertain" if exc.uncertain else "failed"
            result = {"ok": False, "error": {"code": exc.code, "message": str(exc), "status_code": exc.status_code}}
        except PermissionError:
            status, result = "failed", {"ok": False, "error": {"code": "forbidden", "status_code": 403}}
        except (RequestTimeout, TimeoutError, ConnectionError, OSError, APIError):
            status, result = "uncertain", {
                "ok": False, "error": {"code": "completion_unknown", "status_code": 503,
                                      "message": "Continuation completion is unknown; do not replay it."},
            }
        record, _ = self._transition(principal, record, etag, status, observation=result)
        return self._public(record)

    def cancel(self, principal, operation_id) -> dict:
        record, etag = self._load(principal, operation_id)
        authorize(self.settings, principal, record["scope_key"], self._permission(record["tool_name"]))
        if record["status"] not in ("pending", "approved"):
            raise OperationError("cannot_cancel", "Only unexecuted plans can be cancelled; underlying jobs cannot be cancelled.")
        record, _ = self._transition(principal, record, etag, "cancelled")
        return self._public(record)

    @staticmethod
    def _progress(record):
        progress = {
            "phase": record["status"],
            "completion_known": record["status"] not in ("executing", "continuing", "running", "awaiting_continuation", "uncertain"),
            "retry_allowed": False,
            "underlying_job_cancellation_supported": False,
        }
        if record["status"] == "awaiting_continuation":
            progress["observation_hash"] = observation_hash(record)
            data = (record.get("observation") or record.get("outcome") or {}).get("data") or {}
            progress["continuation_allowed"] = (
                data.get("status") == "awaiting-review" and data.get("requires_new_approval") is not True
            )
        return progress

    def _public(self, record):
        # Signed responses remain byte-for-byte equivalent to the persisted record.
        return copy.deepcopy(record)
