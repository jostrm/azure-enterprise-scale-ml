from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Annotated, Callable
from urllib.parse import urlsplit
from uuid import UUID

from azurefactory.client import AzureFactoryClient, redact_secrets, validate_base_url
from azurefactory.errors import APIError, AuthError, ConfigError, RequestTimeout
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .config import Settings, credential
from .security import Principal, authorize
from .ports import CostPort, FactoryApiPort, OperationStorePort, WorkloadPort


CONFIGURE_TOOL = "factory_prepare_settings"
TIMEOUT_CAP_SECONDS = 60


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SettingsChanges(NoArguments):
    department_name: Annotated[str | None, Field(max_length=200)]
    department_id: Annotated[str | None, Field(max_length=128)]

    @field_validator("department_name", "department_id")
    @classmethod
    def literal_text(cls, value):
        if value is not None and (
            any(unicodedata.category(char) in ("Cc", "Cs", "Zl", "Zp") for char in value)
            or any(marker in value for marker in ("$(", "${", "{{", "}}"))
        ):
            raise ValueError("Department metadata must be literal single-line text.")
        return value

    @model_validator(mode="after")
    def nonempty_patch(self):
        if self.department_name is None and self.department_id is None:
            raise ValueError("At least one department metadata field must be supplied.")
        return self

    def factory_values(self):
        return {
            key: value for key, value in (
                ("org-department-name", self.department_name),
                ("org-department-id", self.department_id),
            ) if value is not None
        }


class ConfigureArguments(NoArguments):
    settings: SettingsChanges


def _uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ToolError("invalid_factory_contract", "The Factory API returned an invalid resource ID.", 502) from None


def _revision(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ToolError("invalid_factory_contract", "An exact Factory source revision is required.", 502)
    return value


def _deadline(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ToolError("invalid_factory_contract", "The Factory confirmation expiry is invalid.", 502) from None


def validate_configuration_plan(settings, scope_key, request, preview):
    """Check the persisted request as well as the API's actual configuration-only review."""
    required = {
        "folder", "contract_version", "action", "factory_id", "scale_set_id",
        "project_id", "expected_revision", "settings",
    }
    factory = settings.factory
    if not isinstance(request, dict) or set(request) != required:
        raise ToolError("invalid_plan", "The configuration request has unsupported fields.")
    if (
        request["folder"] != factory.folder or request["contract_version"] != 1
        or type(request["contract_version"]) is not int or request["action"] != "configure-settings"
        or any(getattr(factory, key) is None or request[key] != str(getattr(factory, key))
               for key in ("factory_id", "scale_set_id", "project_id"))
    ):
        raise ToolError("invalid_plan", "The request differs from the server-configured target.")
    values = request["settings"]
    if not isinstance(values, dict) or not values or set(values) - {"org-department-name", "org-department-id"}:
        raise ToolError("invalid_plan", "Only project department display metadata is supported.")
    SettingsChanges(
        department_name=values.get("org-department-name"),
        department_id=values.get("org-department-id"),
    )
    if any(value is None for value in values.values()):
        raise ToolError("invalid_plan", "Null is not a supported metadata value.")
    _revision(request["expected_revision"])
    if not isinstance(preview, dict) or (
        type(preview.get("contract_version")) is not int or preview["contract_version"] != 1
        or preview.get("operation_mode") != "configuration"
        or preview.get("can_execute") is not True or preview.get("blockers") != []
        or preview.get("source_revision") != request["expected_revision"]
        or preview.get("deletion_targets") not in (None, [])
        or preview.get("inventory") not in (None, [])
        or preview.get("binding") is not None
        or preview.get("action") not in (None, "configure-settings")
    ):
        raise ToolError("unsupported_factory_contract", "The API did not return an executable configuration-only review.", 503)
    if any(
        not isinstance(preview.get(key), list)
        or any(not isinstance(item, str) for item in preview[key])
        for key in ("effects", "warnings")
    ):
        raise ToolError("unsupported_factory_contract", "The API review omitted its effects or warnings.", 503)
    for key in ("factory_id", "scale_set_id", "project_id"):
        if _uuid(preview.get(key)) != request[key]:
            raise ToolError("invalid_plan", "The reviewed target differs from the configured target.")
    _uuid(preview.get("confirmation_id"))
    _deadline(preview.get("expires_at"))
    target = preview.get("target")
    if not isinstance(target, dict):
        raise ToolError("unsupported_factory_contract", "The API review must identify the exact affected project.", 503)
    _select_scope(settings, scope_key, {"factories": [target]}, single_placement=True)


def _select_scope(settings, scope_key, catalog, *, single_placement=False):
    scope = settings.scopes[scope_key]
    refs = settings.factory
    if not all(getattr(refs, key) for key in ("factory_id", "scale_set_id", "project_id")):
        raise ToolError("factory_target_unconfigured", "Configure exact factory, scale-set and project IDs on the server.", 503)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("factories"), list):
        raise ToolError("invalid_factory_contract", "Factory catalog did not contain a factories list.", 502)
    factories = [item for item in catalog["factories"] if isinstance(item, dict)
                 and item.get("id") == str(refs.factory_id)]
    if len(factories) != 1:
        raise ToolError("factory_scope_mismatch", "The configured factory is absent or ambiguous.", 403)
    factory = factories[0]
    if factory.get("prefix") != scope.factory:
        raise ToolError("factory_scope_mismatch", "The configured factory is outside the authorized scope.", 403)
    if not isinstance(factory.get("scale_sets"), list) or not isinstance(factory.get("projects"), list):
        raise ToolError("invalid_factory_contract", "Factory membership lists are missing.", 502)
    scales = [item for item in factory["scale_sets"] if isinstance(item, dict)
              and item.get("id") == str(refs.scale_set_id)]
    projects = [item for item in factory["projects"] if isinstance(item, dict)
                and item.get("id") == str(refs.project_id)]
    if len(scales) != 1 or len(projects) != 1:
        raise ToolError("factory_scope_mismatch", "The configured scale set or project is not part of this factory.", 403)
    scale, project = scales[0], projects[0]
    if (
        scale.get("tenant_id") != str(scope.tenant_id)
        or scale.get("subscription_id") != str(scope.subscription_id)
        or scale.get("environment") != scope.environment or project.get("number") != scope.project
    ):
        raise ToolError("factory_scope_mismatch", "The API target does not match the exact authorized scope.", 403)
    placements = project.get("placements")
    selected = {"environment": scope.environment, "scale_set_id": str(refs.scale_set_id)}
    if not isinstance(placements, list) or sum(
        isinstance(item, dict) and all(item.get(key) == value for key, value in selected.items())
        for item in placements
    ) != 1:
        raise ToolError("factory_scope_mismatch", "The project is not placed in the authorized environment.", 403)
    if single_placement and len(placements) != 1:
        raise ToolError("cross_scope_write", "Project metadata affects every placement; multi-environment projects are not writable by this scoped adapter.", 403)
    return factory, scale, project, selected


def _scoped_catalog(settings, scope_key, catalog):
    if not isinstance(catalog, dict) or type(catalog.get("contract_version")) is not int or catalog["contract_version"] != 1:
        raise ToolError("invalid_factory_contract", "Unsupported Factory catalog version.", 502)
    factory, scale, project, placement = _select_scope(settings, scope_key, catalog)
    return {
        "contract_version": catalog.get("contract_version"),
        "revision": _revision(catalog.get("revision")),
        "factory": {key: factory.get(key) for key in ("id", "key", "prefix", "kind", "status", "aifactory_version")},
        "scale_set": {key: scale.get(key) for key in ("id", "environment", "tenant_id", "subscription_id", "status")},
        "project": {**{key: project.get(key) for key in ("id", "key", "number", "display_name", "status")},
                    "placements": [placement]},
    }


class FactoryTools:
    """Backend grants constrain a shared API key, not an OBO/per-user Factory credential."""

    def __init__(self, settings: Settings, principal: Principal, scope_key: str, cred=None, *,
                 operation_store: OperationStorePort | None = None,
                 client_factory: Callable[[str, str, int], FactoryApiPort] | None = None,
                 key_provider: Callable[[], str | None] | None = None,
                 cost_factory: Callable[[Settings, Principal, str, object], CostPort] | None = None,
                 workload_factory: Callable[[Settings, Principal, str, OperationStorePort], WorkloadPort] | None = None):
        self.settings, self.principal, self.scope_key = settings, principal, scope_key
        self.cred = cred
        self.operation_store = operation_store
        self._api_key = None
        self.client_factory, self.key_provider, self.cost_factory = client_factory, key_provider, cost_factory
        self.workload_factory = workload_factory

    def descriptors(self) -> list[dict]:
        definitions = []
        reads = {
            "factory_health": "Read health of the configured Factory API.",
            "factory_capabilities": "Read the configured Factory API creation capabilities; never provision.",
            "factory_catalog": "Read only the server-configured factory/project/environment selection.",
            "factory_settings": "Read non-secret settings of the server-configured selection.",
            "factory_cli_health": "Run the fixed AzureFactory CLI health command without a shell.",
        }
        try:
            authorize(self.settings, self.principal, self.scope_key, "factory.read")
        except PermissionError:
            reads = {}
        for name, description in reads.items():
            definitions.append(self._descriptor(name, description, NoArguments))
        if reads:
            from .skills import OperationStatusArguments
            definitions.append(self._descriptor("factory_operation_status",
                                                "Read this caller's persisted operation and bound job status in the active scope.",
                                                OperationStatusArguments))
        try:
            authorize(self.settings, self.principal, self.scope_key, "factory.read")
            authorize(self.settings, self.principal, self.scope_key, "cost.read")
        except PermissionError:
            pass
        else:
            from .costs import cost_descriptors
            definitions.extend(cost_descriptors())
        return definitions

    @staticmethod
    def _descriptor(name, description, model):
        parameters = model.model_json_schema()
        parameters.setdefault("required", [])
        return {"type": "function", "name": name, "description": description,
                "parameters": parameters, "strict": True}

    def _client(self, *, authenticated=True) -> FactoryApiPort:
        if authenticated:
            if self._api_key is None:
                self._api_key = self.key_provider() if self.key_provider is not None else self._load_key()
            if not self._api_key:
                raise ToolError("factory_auth_unconfigured", "Configure a Factory API key secret reference or process environment key.", 503)
        if self.client_factory is not None:
            return self.client_factory(self.settings.factory.api_url, self._api_key or "",
                                       min(self.settings.factory.timeout_seconds, TIMEOUT_CAP_SECONDS))
        return AzureFactoryClient(
            base_url=self.settings.factory.api_url,
            api_key=self._api_key or "",
            timeout=min(self.settings.factory.timeout_seconds, TIMEOUT_CAP_SECONDS),
        )

    def _load_key(self):
        reference = self.settings.factory.api_key_secret_url
        if not reference:
            return os.environ.get("AIFACTORY_API_KEY")
        try:
            parsed = urlsplit(reference)
            port = parsed.port
        except ValueError:
            raise ToolError("invalid_secret_reference", "Configure an exact Azure Key Vault secret URL.", 503) from None
        if (
            parsed.scheme != "https" or not parsed.hostname
            or not re.fullmatch(r"[a-zA-Z0-9-]{3,24}\.vault\.azure\.net", parsed.hostname)
            or parsed.username or parsed.password or port or parsed.query or parsed.fragment
            or not re.fullmatch(r"/secrets/[A-Za-z0-9-]{1,127}(?:/[a-fA-F0-9]{32})?", parsed.path)
        ):
            raise ToolError("invalid_secret_reference", "Configure an exact Azure Key Vault secret URL.", 503)
        from azure.core.exceptions import AzureError
        try:
            from azure.keyvault.secrets import SecretClient
        except ImportError:
            raise ToolError("factory_auth_unavailable", "The required Key Vault SDK is not installed.", 503) from None
        parts = parsed.path.strip("/").split("/")
        vault = SecretClient(vault_url=f"https://{parsed.hostname}", credential=self.cred or credential(self.settings))
        try:
            return vault.get_secret(parts[1], parts[2] if len(parts) == 3 else None).value
        except AzureError:
            raise ToolError("factory_auth_unavailable", "The configured Factory API credential is unavailable.", 503) from None

    def _read_catalog(self, client):
        if not self.settings.factory.folder:
            raise ToolError("factory_target_unconfigured", "A server-configured catalog folder is required.", 503)
        if not all(getattr(self.settings.factory, key) for key in ("factory_id", "scale_set_id", "project_id")):
            raise ToolError("factory_target_unconfigured", "Configure exact factory, scale-set and project IDs on the server.", 503)
        result = client.catalog_list(self.settings.factory.folder)
        _select_scope(self.settings, self.scope_key, result)
        return result

    def _read_settings(self, client):
        refs = self.settings.factory
        self._read_catalog(client)
        result = client.catalog_settings(
            refs.folder, str(refs.factory_id), str(refs.scale_set_id), str(refs.project_id),
        )
        if not isinstance(result, dict) or type(result.get("contract_version")) is not int or result["contract_version"] != 1:
            raise ToolError("invalid_factory_contract", "Unsupported Factory settings response.", 502)
        for key in ("factory_id", "scale_set_id", "project_id"):
            if result.get(key) != str(getattr(refs, key)):
                raise ToolError("factory_scope_mismatch", "The settings response belongs to another target.", 403)
        _revision(result.get("revision"))
        if (
            not isinstance(result.get("state"), dict) or not isinstance(result.get("field_keys"), list)
            or any(not isinstance(key, str) for key in result["field_keys"])
        ):
            raise ToolError("invalid_factory_contract", "The API did not return a settings schema.", 502)
        return result

    def execute(self, name: str, args: dict) -> dict:
        from .costs import COST_TOOL_TO_SKILL, CostSkills
        if name == "factory_operation_status":
            try:
                from .operations import OperationStore
                from .skills import OperationStatusArguments
                authorize(self.settings, self.principal, self.scope_key, "factory.read")
                arguments = OperationStatusArguments.model_validate(args)
                if self.operation_store is None:
                    self.operation_store = OperationStore(self.settings, self.cred)
                record = self.operation_store.read(self.principal, arguments.operation_id)
                if record["scope_key"] != self.scope_key:
                    raise PermissionError("The operation belongs to another active scope.")
                observed = self.operation_store.observe(self.principal, arguments.operation_id, self.status_operation)
                return {"ok": True, "data": observed}
            except PermissionError:
                return self._error("forbidden", "The saved operation is not authorized in this exact scope.", 403)
            except ValidationError:
                return self._error("invalid_arguments", "An exact saved operation ID is required.", 400)
            except ToolError as exc:
                return self._error(exc.code, str(exc), exc.status_code)
        if isinstance(name, str) and name in COST_TOOL_TO_SKILL:
            try:
                costs = (self.cost_factory(self.settings, self.principal, self.scope_key, self.cred)
                         if self.cost_factory is not None else
                         CostSkills(self.settings, self.principal, self.scope_key, cred=self.cred))
                authorize(self.settings, self.principal, self.scope_key, "factory.read")
                authorize(self.settings, self.principal, self.scope_key, "cost.read")
                return costs.execute(COST_TOOL_TO_SKILL[name], args)
            except PermissionError:
                return self._error("forbidden", "The caller lacks cost access for this exact scope.", 403)
            except ValidationError:
                return self._error("invalid_arguments", "Arguments do not match the closed cost schema.", 400)
            except ToolError as exc:
                return self._error(exc.code, str(exc), exc.status_code)
        return self._execute(name, args, allow_prepare=False)

    def prepare_skill(self, name: str, args: dict) -> dict:
        """Explicit authenticated user request only; never part of model dispatch."""
        from .actions import ActionSkills
        from .skills import ACTION_SKILLS, WORKLOAD_SKILLS, SKILL_PERMISSIONS, argument_model, normalize_skill
        name = normalize_skill(name)
        if name not in (*ACTION_SKILLS, *WORKLOAD_SKILLS):
            raise ToolError("unsupported_operation", "Monitoring skills cannot prepare Factory actions.", 400)
        authorize(self.settings, self.principal, self.scope_key, "factory.read")
        authorize(self.settings, self.principal, self.scope_key, SKILL_PERMISSIONS[name])
        if not self.settings.factory.writes_enabled:
            raise ToolError("writes_disabled", "Factory actions are disabled.", 503)
        enabled = (self.settings.workloads.enabled_skills if name in WORKLOAD_SKILLS
                   else self.settings.actions.enabled_skills)
        if name not in enabled:
            raise ToolError("skill_disabled", "This Factory action is disabled by the deployment operator.", 503)
        try:
            argument_model(name).model_validate(args)
        except ValidationError:
            raise ToolError("invalid_arguments", "Arguments do not match the closed action schema.", 400) from None
        if self.operation_store is None:
            from .operations import OperationStore
            self.operation_store = OperationStore(self.settings, self.cred)
        self.operation_store.ensure_ready()
        if name in WORKLOAD_SKILLS:
            return self._workloads().prepare(name, args)
        return ActionSkills(self.settings, self.principal, self.scope_key,
                            self._client(), self.operation_store).prepare(name, args)

    def _workloads(self) -> WorkloadPort:
        if self.operation_store is None:
            from .operations import OperationStore
            self.operation_store = OperationStore(self.settings, self.cred)
        if self.workload_factory is not None:
            return self.workload_factory(self.settings, self.principal, self.scope_key, self.operation_store)
        from .workloads import WorkloadSkills
        return WorkloadSkills(self.settings, self.principal, self.scope_key, self.operation_store)

    def status_operation(self, operation: dict) -> dict:
        from .actions import ActionSkills
        from .skills import ACTION_SKILLS, WORKLOAD_SKILLS, SKILL_PERMISSIONS
        if operation.get("tool_name") not in (*ACTION_SKILLS, *WORKLOAD_SKILLS):
            raise ToolError("unsupported_operation", "This operation has no asynchronous Factory job.", 400)
        authorize(self.settings, self.principal, self.scope_key, "factory.read")
        authorize(self.settings, self.principal, self.scope_key, SKILL_PERMISSIONS[operation["tool_name"]])
        if operation["tool_name"] in WORKLOAD_SKILLS:
            return self._workloads().status(operation)
        return ActionSkills(self.settings, self.principal, self.scope_key,
                            self._client(), self.operation_store).status(operation)

    def continue_operation(self, operation: dict) -> dict:
        from .actions import CREATE, ActionSkills
        if operation.get("tool_name") != CREATE:
            raise ToolError("unsupported_operation", "Only a paused approved Full bootstrap can be continued.", 400)
        authorize(self.settings, self.principal, self.scope_key, "factory.read")
        authorize(self.settings, self.principal, self.scope_key, "factory.create")
        from .operations import OperationError
        try:
            client = self._client()
        except ToolError as exc:
            raise OperationError(exc.code, str(exc), exc.status_code) from None
        return ActionSkills(self.settings, self.principal, self.scope_key,
                            client, self.operation_store).continue_operation(operation)

    def prepare_settings(self, args: dict) -> dict:
        """Authenticated backend proposal endpoint only; not a model-callable tool."""
        return self._execute(CONFIGURE_TOOL, args, allow_prepare=True)

    def _execute(self, name: str, args: dict, *, allow_prepare: bool) -> dict:
        supported = {"factory_health", "factory_capabilities", "factory_catalog",
                     "factory_settings", "factory_cli_health"}
        if allow_prepare:
            supported.add(CONFIGURE_TOOL)
        if not isinstance(name, str) or name not in supported:
            return self._error("unsupported_tool", "This tool is not in the backend allowlist.", 400)
        try:
            authorize(self.settings, self.principal, self.scope_key, "factory.read")
            if name == CONFIGURE_TOOL:
                authorize(self.settings, self.principal, self.scope_key, "config.write")
                if self.settings.scopes[self.scope_key].environment not in self.settings.factory.allowed_write_environments:
                    raise ToolError("environment_not_enabled", "Writes are not enabled for this environment.", 403)
                if not self.settings.factory.writes_enabled:
                    raise ToolError("writes_disabled", "Factory configuration writes are disabled.", 503)
            parsed = (ConfigureArguments if name == CONFIGURE_TOOL else NoArguments).model_validate(args)
            if name == "factory_cli_health":
                return self._cli_health()
            client = self._client(authenticated=name != "factory_health")
            if name == "factory_health":
                result = client.health()
            elif name == "factory_capabilities":
                # The current SDK names this creation_capabilities, not bootstrap_capabilities.
                capabilities = getattr(client, "bootstrap_capabilities", None)
                result = capabilities() if capabilities is not None else client.creation_capabilities()
            elif name == "factory_catalog":
                result = _scoped_catalog(self.settings, self.scope_key, self._read_catalog(client))
            elif name == "factory_settings":
                raw = self._read_settings(client)
                result = {key: raw[key] for key in ("contract_version", "revision", "factory_id",
                                                    "scale_set_id", "project_id", "state", "field_keys")}
            else:
                result = self._prepare(client, parsed)
            return {"ok": True, "data": redact_secrets(result, self._api_key)}
        except PermissionError:
            return self._error("forbidden", "The caller lacks permission for this exact scope.", 403)
        except ValidationError:
            return self._error("invalid_arguments", "Arguments do not match the closed tool schema.", 400)
        except ToolError as exc:
            return self._error(exc.code, str(exc), exc.status_code)
        except RequestTimeout:
            return self._error("factory_timeout", "The Factory API timed out; no automatic retry was attempted.", 503)
        except (AuthError, ConfigError) as exc:
            return self._error("factory_configuration", str(exc), 503)
        except APIError as exc:
            return self._error("factory_api_error", str(exc), exc.status or 503)

    def _error(self, code, message, status_code):
        return {"ok": False, "error": {"code": code, "message": redact_secrets(message, self._api_key),
                                     "status_code": status_code}}

    def _cli_health(self):
        url = validate_base_url(self.settings.factory.api_url)
        timeout = min(self.settings.factory.timeout_seconds, TIMEOUT_CAP_SECONDS)
        argv = [sys.executable, "-m", "azurefactory", "--api-url", url, "--timeout", str(timeout), "health"]
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "PYTHONPATH", "LANG", "LC_ALL"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = subprocess.run(argv, shell=False, capture_output=True, text=True,
                                     timeout=timeout + 5, check=False, env=env)
        except subprocess.TimeoutExpired:
            return self._error("factory_timeout", "The fixed Factory CLI health request timed out.", 503)
        except OSError:
            return self._error("factory_cli_unavailable", "The fixed Factory CLI could not be started.", 503)
        if process.returncode != 0:
            # Do not reflect arbitrary stderr or environment diagnostics.
            return self._error("factory_cli_failed", f"Factory CLI health failed with exit code {process.returncode}.", 503)
        try:
            result = json.loads(process.stdout)
        except (ValueError, TypeError):
            return self._error("invalid_factory_contract", "Factory CLI health did not return JSON.", 502)
        if not isinstance(result, dict):
            return self._error("invalid_factory_contract", "Factory CLI health did not return an object.", 502)
        return {"ok": True, "data": redact_secrets(result, self._api_key)}

    def _prepare(self, client, arguments):
        if self.operation_store is None:
            from .operations import OperationStore
            self.operation_store = OperationStore(self.settings, self.cred)
        self.operation_store.ensure_ready()
        catalog = self._read_catalog(client)
        _select_scope(self.settings, self.scope_key, catalog, single_placement=True)
        current = self._read_settings(client)
        values = arguments.settings.factory_values()
        if self._api_key and any(self._api_key in value for value in values.values()):
            raise ToolError("secret_in_arguments", "Factory credentials cannot be persisted as display metadata.", 400)
        if set(values) - set(current["field_keys"]):
            raise ToolError("unsupported_factory_contract", "The running API does not support the requested metadata settings.", 503)
        schema = client.openapi()
        if not isinstance(schema, dict) or not isinstance(schema.get("components"), dict):
            raise ToolError("unsupported_factory_contract", "The running API did not return its supported schemas.", 503)
        schemas = schema["components"].get("schemas")
        prepare_schema = schemas.get("CatalogPrepare") if isinstance(schemas, dict) else None
        properties = prepare_schema.get("properties") if isinstance(prepare_schema, dict) else None
        action_schema = properties.get("action") if isinstance(properties, dict) else None
        if not isinstance(action_schema, dict):
            raise ToolError("unsupported_factory_contract", "The running API omitted its configure-settings action schema.", 503)
        if (
            prepare_schema.get("additionalProperties") is not False
            or "configure-settings" not in action_schema.get("enum", [])
            or not {"settings", "expected_revision", "factory_id", "scale_set_id", "project_id"}
            <= properties.keys()
        ):
            raise ToolError("unsupported_factory_contract", "The running API lacks the closed configure-settings contract.", 503)
        refs = self.settings.factory
        request = {
            "folder": refs.folder, "contract_version": 1, "action": "configure-settings",
            "factory_id": str(refs.factory_id), "scale_set_id": str(refs.scale_set_id),
            "project_id": str(refs.project_id), "expected_revision": current["revision"], "settings": values,
        }
        preview = redact_secrets(client.catalog_prepare(request), self._api_key)
        validate_configuration_plan(self.settings, self.scope_key, request, preview)
        return self.operation_store.propose(self.principal, self.scope_key, CONFIGURE_TOOL, request, preview)

    def execute_operation(self, operation: dict) -> dict:
        """Only the authenticated approval endpoint supplies a persisted approved operation."""
        from .operations import OperationError, plan_hash
        from .skills import ACTION_SKILLS, WORKLOAD_SKILLS
        if operation.get("tool_name") in WORKLOAD_SKILLS:
            try:
                return self._workloads().execute_operation(operation)
            except OperationError:
                raise
            except ToolError as exc:
                raise OperationError(exc.code, str(exc), exc.status_code) from None
        if operation.get("tool_name") in ACTION_SKILLS:
            from .actions import ActionSkills
            try:
                client = self._client()
            except ToolError as exc:
                raise OperationError(exc.code, str(exc), exc.status_code) from None
            return ActionSkills(self.settings, self.principal, self.scope_key,
                                client, self.operation_store).execute_operation(operation)
        if (
            operation.get("status") != "executing" or operation.get("tool_name") != CONFIGURE_TOOL
            or operation.get("tenant_id") != self.principal.tenant_id
            or operation.get("object_id") != self.principal.object_id
            or operation.get("scope_key") != self.scope_key
            or operation.get("plan_hash") != plan_hash(operation)
            or operation.get("scope") != self.settings.scopes[self.scope_key].model_dump(mode="json")
        ):
            raise OperationError("invalid_execution", "Execution requires the exact persisted, claimed approval.", 403)
        authorize(self.settings, self.principal, self.scope_key, "config.write")
        authorize(self.settings, self.principal, self.scope_key, "factory.read")
        if not self.settings.factory.writes_enabled:
            raise OperationError("writes_disabled", "Factory configuration writes are disabled.", 503)
        request, preview = operation["request"], operation["preview"]
        try:
            validate_configuration_plan(self.settings, self.scope_key, request, preview)
            client = self._client()
            catalog = self._read_catalog(client)
            _select_scope(self.settings, self.scope_key, catalog, single_placement=True)
            current = self._read_settings(client)
            if current["revision"] != request["expected_revision"]:
                raise ToolError("revision_changed", "The reviewed Factory source revision changed; prepare again.")
            now = datetime.now(timezone.utc)
            if min(_deadline(preview["expires_at"]), _deadline(operation["expires_at"])) <= now:
                raise ToolError("plan_expired", "The underlying Factory confirmation expired.")
        except ToolError as exc:
            raise OperationError("plan_blocked", str(exc), exc.status_code) from None
        except ValidationError:
            raise OperationError("plan_blocked", "The persisted metadata plan does not match the closed schema.") from None
        # No retry: this confirmation consumes an underlying, revision-bound Factory approval.
        result = client.catalog_confirm(request["folder"], preview["confirmation_id"])
        if (
            not isinstance(result, dict) or type(result.get("contract_version")) is not int
            or result["contract_version"] != 1 or result.get("job") is not None
        ):
            raise OperationError("uncertain_result", "The API confirmation result was not configuration-only.", 502,
                                 uncertain=True)
        catalog = result.get("catalog")
        if not isinstance(catalog, dict):
            raise OperationError("uncertain_result", "The API confirmation omitted the resulting catalog.", 502,
                                 uncertain=True)
        try:
            scoped = _scoped_catalog(self.settings, self.scope_key, catalog)
        except ToolError:
            raise OperationError("uncertain_result", "The API confirmation returned a mismatched target.", 502,
                                 uncertain=True) from None
        return {"ok": True, "data": redact_secrets(scoped, self._api_key),
                "correlation_id": operation["correlation_id"]}
