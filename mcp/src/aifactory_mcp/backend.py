"""MCP-shaped adapter over the existing authorization, skills and durable approvals."""
from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .health import AgentHealthProbe, HealthModel, HealthRegistry


_LOG = logging.getLogger(__name__)
_PREPARES = ("factory_prepare_create", "factory_prepare_delete", "factory_prepare_add_project")
_READS = {"factory_health", "factory_capabilities", "factory_catalog", "factory_settings", "factory_cli_health"}
_HEALTH_NAMES = {"factory_health", "factory_cli_health"}
_MESSAGES = {
    "forbidden": "The caller lacks permission for this exact configured scope.",
    "invalid_arguments": "Arguments do not match the closed tool schema.",
    "unsupported_tool": "This tool is not in the backend allowlist.",
    "writes_disabled": "Factory actions are disabled by the deployment operator.",
    "skill_disabled": "This Factory action is disabled by the deployment operator.",
    "environment_not_enabled": "Writes are not enabled for this environment.",
    "approval_required": "Execution requires an approved, unused plan; obtain explicit human CLI approval first.",
    "plan_hash_mismatch": "Approval must reference the exact reviewed plan hash.",
    "confirmation_phrase_required": "Type the exact reviewed DELETE factory-key phrase to approve deletion.",
    "operation_scope_mismatch": "The operation does not belong to this connection's configured scope.",
    "operation_not_found": "The operation was not found.",
    "operation_conflict": "Another request changed this plan, or the plan is no longer pending and unused.",
    "cannot_cancel": "Only unexecuted plans can be cancelled; underlying jobs cannot be cancelled.",
    "plan_expired": "The reviewed approval expired; prepare again.",
    "plan_changed": "The reviewed plan or scope changed; prepare again.",
    "revision_changed": "The reviewed Factory source changed; prepare again.",
    "factory_scope_mismatch": "The Factory API target does not match the exact authorized scope.",
    "factory_auth_unconfigured": "Configure a Factory API key secret reference or process environment key.",
    "factory_auth_unavailable": "The configured Factory API credential is unavailable.",
    "factory_target_unconfigured": "Configure exact Factory, scale-set and project IDs on the server.",
    "operation_signing_unconfigured": "Configure a Key Vault operation-signing secret for durable approvals.",
    "store_unavailable": "Durable operation storage is unavailable.",
    "audit_unavailable": "The durable audit event could not be persisted.",
    "factory_timeout": "The Factory API timed out; no automatic retry was attempted.",
    "factory_api_error": "The Factory API request failed; consult the service logs.",
    "factory_configuration": "The configured Factory API connection is unavailable.",
    "invalid_factory_contract": "The Factory API returned an unsupported or invalid response.",
    "unsupported_factory_contract": "The running Factory API does not support the required reviewed contract.",
    "completion_unknown": "Factory completion is unknown; do not retry this confirmation.",
    "uncertain_result": "Factory completion could not be confirmed; do not retry this confirmation.",
    "operation_failed": "The Factory operation failed; review its persisted state before preparing another plan.",
    "operation_uncertain": "Factory completion is uncertain; do not retry this confirmation.",
    "internal_error": "The Factory backend request failed; consult the operator logs.",
}


class BackendError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _error(code, status_code=409):
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
        code = "internal_error"
    if type(status_code) is not int or not 400 <= status_code <= 599:
        status_code = 503
    return BackendError(code, _MESSAGES.get(code, "The Factory request was rejected by the configured policy or service."), status_code)


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _OperationArguments(_NoArguments):
    operation_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        json_schema_extra={"format": "uuid"},
    )

    @field_validator("operation_id")
    @classmethod
    def nonzero_uuid(cls, value):
        identifier = UUID(value)
        if not identifier.int:
            raise ValueError("A nonzero operation UUID is required.")
        return str(identifier)


class _ApprovalArguments(_OperationArguments):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_phrase: str | None = Field(default=None, min_length=1, max_length=512)


class _LazyStore:
    def __init__(self, backend):
        self.backend = backend

    def __getattr__(self, name):
        return getattr(self.backend.operation_store, name)


class AgentBackend:
    def __init__(
        self, runtime, principal, scope_key, *, operation_store=None, tools_factory=None,
        health_models: Iterable[HealthModel] | None = None,
    ):
        from azure.core.exceptions import AzureError
        from httpx import HTTPError

        self.runtime, self.principal, self.scope_key = runtime, principal, scope_key
        self._dependency_errors = (AzureError, HTTPError, runtime.sdk.APIError, OSError)
        self._store = operation_store
        self._lock = threading.RLock()
        self._tools = None
        with self._boundary():
            self._authorize()
            factory = tools_factory if tools_factory is not None else runtime.tools.FactoryTools
            self._tools = factory(runtime.settings, principal, scope_key,
                                  operation_store=operation_store if operation_store is not None else _LazyStore(self))
            self._health = HealthRegistry(
                health_models if health_models is not None
                else runtime.health_models_factory(AgentHealthProbe(self._tools))
            )

    @property
    def operation_store(self):
        with self._lock:
            if self._store is None:
                self._store = self.runtime.operations.OperationStore(self.runtime.settings)
            return self._store

    def _authorize(self):
        if not isinstance(self.scope_key, str):
            raise _error("forbidden", 403)
        self.runtime.security.authorize(self.runtime.settings, self.principal, self.scope_key, "factory.read")

    @contextmanager
    def _boundary(self):
        try:
            yield
        except BackendError:
            raise
        except PermissionError:
            raise _error("forbidden", 403) from None
        except ValidationError:
            raise _error("invalid_arguments", 400) from None
        except self.runtime.tools.ToolError as exc:
            raise _error(exc.code, exc.status_code) from None
        except self._dependency_errors:
            # Dependency failures are sanitized; programmer errors deliberately propagate.
            _LOG.error("Factory backend request failed; credential-bearing exception details suppressed.")
            raise _error("internal_error", 503) from None

    @staticmethod
    def _descriptor(name, description, schema, *, readonly=True, destructive=False, idempotent=True):
        return {
            "name": name, "description": description, "inputSchema": schema,
            "annotations": {"readOnlyHint": readonly, "destructiveHint": destructive,
                            "idempotentHint": idempotent, "openWorldHint": True},
        }

    def list_tools(self) -> list[dict]:
        with self._lock, self._boundary():
            self._authorize()
            definitions, seen = [], set()
            accepted = _READS | set(self.runtime.costs.COST_TOOL_TO_SKILL)
            # Only audited reads inherit upstream descriptors; operation contracts below are authoritative.
            for item in self._tools.descriptors():
                name = item["name"]
                if name not in accepted:
                    continue
                if name in seen:
                    raise _error("invalid_factory_contract", 502)
                seen.add(name)
                if name not in _HEALTH_NAMES:
                    definitions.append(self._descriptor(name, item["description"], item["parameters"]))
            definitions.extend(self._health.descriptors())
            for name, skill in zip(_PREPARES, self.runtime.skills.ACTION_SKILLS):
                definitions.append(self._descriptor(
                    name, f"Prepare and persist a reviewed plan: {self.runtime.skills.SKILL_LABELS[skill]}. "
                    "Never executes or approves. Requires separate explicit human approval in the local CLI.",
                    self.runtime.skills.argument_model(skill).model_json_schema(),
                    readonly=False, destructive=name == "factory_prepare_delete", idempotent=False,
                ))
            extras = (
                ("factory_skills", "List actual Factory skills, argument schemas and deployment blockers.", _NoArguments, True, False, True),
                ("factory_operations", "List persisted snapshots in this connection's scope without state/audit updates. Check expires_at; pending or approved does not extend the deadline.", _NoArguments, True, False, True),
                ("factory_operation", "Read one persisted snapshot in this connection's scope without state/audit updates. Check expires_at before requesting approval or execution.", _OperationArguments, True, False, True),
                ("factory_operation_status", "Observe an existing job and persist its status/audit; never confirm or continue it.", _OperationArguments, False, False, False),
                ("factory_execute_operation", "Execute a previously human-approved, unused plan exactly once; never approve or retry.", _OperationArguments, False, True, False),
                ("factory_cancel_operation", "Cancel only an unexecuted plan; cannot cancel an underlying Factory job.", _OperationArguments, False, False, False),
            )
            for name, description, model, readonly, destructive, idempotent in extras:
                definitions.append(self._descriptor(name, description, model.model_json_schema(), readonly=readonly,
                                                    destructive=destructive, idempotent=idempotent))
            return definitions

    def _arguments(self, name, arguments):
        if not isinstance(arguments, dict):
            raise _error("invalid_arguments", 400)
        if name in _PREPARES:
            model = self.runtime.skills.argument_model(self.runtime.skills.ACTION_SKILLS[_PREPARES.index(name)])
        elif name in self.runtime.costs.COST_TOOL_TO_SKILL:
            model = self.runtime.costs.argument_model(self.runtime.costs.COST_TOOL_TO_SKILL[name])
        elif name in {"factory_operation", "factory_operation_status", "factory_execute_operation", "factory_cancel_operation"}:
            model = _OperationArguments
        else:
            model = _NoArguments
        return model.model_validate(arguments).model_dump(mode="json")

    def _read_operation(self, operation_id):
        # The shared read/list methods persist expiry. Use their verified, non-mutating
        # loader instead, preserving signature, ownership, grant and plan-integrity checks.
        record, _ = self.operation_store._load(self.principal, operation_id)
        if record.get("scope_key") != self.scope_key:
            raise _error("operation_scope_mismatch", 403)
        return self.operation_store._public(record)

    def _list_operations(self):
        store = self.operation_store
        records = []
        for key in store.backend.list_keys(store._prefix(self.principal)):
            identifier = key.rsplit("/", 1)[-1].removesuffix(".json")
            try:
                records.append(self._read_operation(identifier))
            except PermissionError:
                # Match the shared store's handling of grants revoked since preparation.
                continue
            except BackendError as exc:
                if exc.code != "operation_scope_mismatch":
                    raise
        return sorted(records, key=lambda record: record["created_at"], reverse=True)

    def _sanitize(self, result):
        # Also cover unauthenticated health/CLI responses before FactoryTools loads its key.
        result = self.runtime.sdk.redact_secrets(result, getattr(self._tools, "_api_key", None))
        return self.runtime.sdk.redact_secrets(result, os.environ.get("AIFACTORY_API_KEY"))

    def _read_result(self, result):
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("error") is not None:
            failure = result.get("error") if isinstance(result, dict) else None
            if not isinstance(failure, dict):
                raise _error("invalid_factory_contract", 502)
            raise _error(failure.get("code", "invalid_factory_contract"), failure.get("status_code", 502))
        return self._sanitize(result)

    def _record_result(self, record):
        result = {"ok": True, "operation": record}
        if record.get("status") in {"failed", "uncertain"}:
            error = _error("operation_" + record["status"], 503 if record["status"] == "uncertain" else 409)
            result.update(ok=False, error={"code": error.code, "message": str(error), "status_code": error.status_code})
        # Persisted errors are not necessarily safe to reflect, even after keyed redaction.
        record = dict(record)
        for field in ("outcome", "observation"):
            value = record.get(field)
            if isinstance(value, dict) and isinstance(value.get("error"), dict):
                failure = _error(value["error"].get("code"), value["error"].get("status_code", 503))
                record[field] = {**value, "error": {"code": failure.code, "message": str(failure),
                                                 "status_code": failure.status_code}}
        result["operation"] = record
        return self._sanitize(result)

    def _execute(self, record):
        try:
            return self._tools.execute_operation(record)
        except self.runtime.operations.OperationError:
            raise
        except self.runtime.tools.ToolError as exc:
            raise self.runtime.operations.OperationError(exc.code, str(_error(exc.code)), exc.status_code) from None
        except PermissionError:
            raise
        except self._dependency_errors:
            _LOG.error("Factory execution completion unknown; credential-bearing exception details suppressed.")
            raise self.runtime.operations.OperationError(
                "completion_unknown", _MESSAGES["completion_unknown"], 503, uncertain=True,
            ) from None

    def call_tool(self, name: str, arguments: dict) -> dict:
        with self._lock, self._boundary():
            self._authorize()
            if not isinstance(name, str) or name not in {item["name"] for item in self.list_tools()}:
                raise _error("unsupported_tool", 400)
            if name in self._health:
                return self._read_result(self._health.evaluate(name, arguments))
            args = self._arguments(name, arguments)
            if name in _READS - _HEALTH_NAMES or name in self.runtime.costs.COST_TOOL_TO_SKILL:
                return self._read_result(self._tools.execute(name, args))
            if name in _PREPARES:
                skill = self.runtime.skills.ACTION_SKILLS[_PREPARES.index(name)]
                return self._record_result(self._tools.prepare_skill(skill, args))
            if name == "factory_skills":
                return self._sanitize({"ok": True, "data": self.runtime.skills.skill_catalog(
                    self.runtime.settings, self.principal, self.scope_key,
                )})
            if name == "factory_operations":
                return self._sanitize({"ok": True, "data": [
                    self._record_result(record)["operation"] for record in self._list_operations()
                ]})
            operation_id = args["operation_id"]
            record = self._read_operation(operation_id)
            if name == "factory_operation_status":
                record = self.operation_store.observe(self.principal, operation_id, self._tools.status_operation)
            elif name == "factory_execute_operation":
                record = self.operation_store.execute(self.principal, operation_id, self._execute)
            elif name == "factory_cancel_operation":
                record = self.operation_store.cancel(self.principal, operation_id)
            return self._record_result(record)

    def approve(self, operation_id, plan_hash, confirmation_phrase=None) -> dict:
        """Explicit local human CLI only; deliberately absent from MCP tool dispatch."""
        with self._lock, self._boundary():
            self._authorize()
            args = _ApprovalArguments.model_validate({
                "operation_id": operation_id, "plan_hash": plan_hash, "confirmation_phrase": confirmation_phrase,
            })
            self._read_operation(args.operation_id)
            return self._record_result(self.operation_store.approve(
                self.principal, args.operation_id, args.plan_hash, confirmation_phrase=args.confirmation_phrase,
            ))
