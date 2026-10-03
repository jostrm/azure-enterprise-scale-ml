from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from azure.core.exceptions import AzureError
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import security
from .config import Settings
from .foundry import Conversation
from .knowledge import IndexingError, Knowledge, OwnershipError
from .operations import OperationStore
from .security import Principal, authorize
from .services import AgentDependencies, AgentServices
from .ports import KnowledgePort, OperationStorePort
from .tools import CONFIGURE_TOOL, FactoryTools, SettingsChanges, ToolError
from .skills import (
    ACTION_SKILLS, WORKLOAD_SKILLS, COST_SKILLS, DIAGNOSTIC_SKILLS, SKILL_PERMISSIONS,
    argument_model, normalize_skill, skill_catalog,
)

STATIC = Path(__file__).with_name("static")
PERMISSIONS = ("knowledge.read", "factory.read", "config.write", "knowledge.refresh",
               "factory.create", "factory.delete", "project.add", "cost.read", "agent.create", "model.create")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=8000)
    audience: Literal["platform", "project"]
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A nonempty question is required.")
        return value


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_phrase: str | None = Field(default=None, min_length=1, max_length=1024)


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    settings: SettingsChanges


class SkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    arguments: dict[str, object]


class ContinuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    observation_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_services(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> AgentServices:
    services = request.app.state.services
    if services.settings != settings:
        services = AgentServices(settings, dependencies=services.dependencies)
        request.app.state.services = services
    return services


def get_knowledge(services: Annotated[AgentServices, Depends(get_services)]) -> KnowledgePort:
    return services.knowledge()


def get_operation_store(services: Annotated[AgentServices, Depends(get_services)]) -> OperationStorePort:
    return services.operation_store()


def _auth_configured(settings: Settings) -> bool:
    try:
        client = UUID(settings.auth.client_id or "")
    except (ValueError, TypeError, AttributeError):
        return False
    audience = settings.auth.audience or ""
    try:
        valid_audience = bool(UUID(audience).int)
    except (ValueError, TypeError, AttributeError):
        try:
            parsed = urlsplit(audience)
            valid_audience = (
                parsed.scheme in ("api", "https") and bool(parsed.hostname)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
            )
        except ValueError:
            valid_audience = False
    return bool(
        client.int and valid_audience and audience == audience.strip()
        and not any(char.isspace() for char in audience)
        and re.fullmatch(r"[A-Za-z0-9_.-]+", settings.auth.required_scope)
    )


def get_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)],
    services: Annotated[AgentServices, Depends(get_services)],
) -> Principal:
    if not _auth_configured(settings):
        raise security.AuthenticationUnavailable("Entra registration is unconfigured.")
    headers = request.headers.getlist("authorization")
    parts = headers[0].split() if len(headers) == 1 else []
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise security.AuthenticationError("A bearer access token is required.")
    return services.authenticate(parts[1])


def _failure(code: str, message: str, status: int, *, headers=None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


def _knowledge_ready(status: dict) -> bool:
    return (
        status.get("status") == "ready" and status.get("stale") is False
        and type(status.get("indexed_document_count")) is int
        and status["indexed_document_count"] > 0
        and status.get("reconciliation_pending") is False
        and ("search_document_count" not in status
             or (type(status["search_document_count"]) is int
                 and status["search_document_count"] == status["indexed_document_count"]))
    )


def get_readiness_knowledge(
    settings: Annotated[Settings, Depends(get_settings)],
    services: Annotated[AgentServices, Depends(get_services)],
) -> KnowledgePort | None:
    return services.knowledge() if _auth_configured(settings) else None


def create_app(settings: Settings, *, services: AgentServices | None = None) -> FastAPI:
    app = FastAPI(title="Enterprise Scale AI Factory Agent", docs_url=None, redoc_url=None,
                  openapi_url=None, debug=False)
    app.state.settings = settings
    if services is not None and services.settings != settings:
        raise ValueError("Injected agent services must match this application's settings.")
    if services is None:
        from .costs import CostSkills
        from .workloads import WorkloadSkills
        cost_factory = lambda current, principal, scope: CostSkills(current, principal, scope)
        workload_factory = lambda current, principal, scope, store: WorkloadSkills(current, principal, scope, store)
        dependencies = AgentDependencies(
            knowledge_factory=lambda current: Knowledge(current),
            operation_store_factory=lambda current: OperationStore(current, namespace=current.agent_name),
            tool_factory=lambda current, principal, scope, store:
                FactoryTools(current, principal, scope, operation_store=store,
                             cost_factory=lambda configured, caller, key, cred: cost_factory(configured, caller, key),
                             workload_factory=workload_factory),
            cost_factory=cost_factory,
            workload_factory=workload_factory,
            conversation_factory=lambda current, knowledge, tools: Conversation(
                current, knowledge, tool_factory=tools),
            authenticate=lambda current, token: security.principal_from_token(current, token),
        )
        services = AgentServices(settings, dependencies=dependencies)
    app.state.services = services
    inline_scripts = re.findall(r"<script>(.*?)</script>", (STATIC / "index.html").read_text("utf-8"), re.S)
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii") + "'"
        for script in inline_scripts
    )
    csp = (
        f"default-src 'none'; script-src 'self' {hashes}; style-src 'self'; "
        "connect-src 'self' https://login.microsoftonline.com; img-src 'self'; "
        "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'none'"
    )
    headers = {"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff",
               "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(headers)
        return response

    @app.exception_handler(500)
    async def unexpected_failure(request: Request, exc):
        # Keep FastAPI's generic failure response, including when middleware is bypassed by an exception.
        return PlainTextResponse("Internal Server Error", status_code=500, headers=headers)

    @app.exception_handler(security.AuthenticationError)
    async def authentication_error(request: Request, exc):
        return _failure("authentication_required", "Sign in with an Entra delegated access token.", 401,
                        headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(security.AuthenticationUnavailable)
    async def authentication_unavailable(request: Request, exc):
        return _failure("authentication_unavailable",
                        "Entra registration or signing keys are unavailable. Ask the deployment operator to check setup.", 503)

    @app.exception_handler(PermissionError)
    async def forbidden(request: Request, exc):
        return _failure("forbidden", "The caller is not authorized for this exact scope and permission.", 403)

    @app.exception_handler(ToolError)
    async def tool_error(request: Request, exc):
        code = exc.code if re.fullmatch(r"[a-z0-9_]{1,80}", str(exc.code)) else "operation_blocked"
        messages = {
            400: "The proposed operation does not match the supported contract.",
            403: "The caller is not authorized to perform this operation.",
            404: "The operation was not found for this caller.",
            409: "The operation is blocked or changed. Review the current plan and prepare again if needed.",
            503: "The operation dependency is unavailable or writes are disabled. Contact the deployment operator.",
        }
        blockers = {
            "writes_disabled": "Factory configuration writes are disabled by the deployment operator.",
            "factory_target_unconfigured": "Exact factory, scale-set and project identifiers must be configured on the server.",
            "factory_auth_unconfigured": "The existing Factory API credential must be configured by the deployment operator.",
            "factory_configuration": "The existing Factory API configuration or credential dependency is unavailable.",
            "factory_timeout": "The existing Factory API timed out. Inspect persisted plans before submitting again.",
            "factory_api_error": "The existing Factory API request failed. No API host is provisioned by this service.",
            "skill_disabled": "This Factory action must be enabled for the exact target by the deployment operator.",
            "operation_signing_unconfigured": "A dedicated Key Vault operation-signing secret must be configured.",
            "cost_scope_mismatch": "The selected resource group is outside this scope's authorized cost targets.",
            "cost_unavailable": "Azure Cost Analysis is unavailable for this target. Check billing access and data availability.",
        }
        return _failure(code, blockers.get(code, messages.get(exc.status_code, "The operation could not be confirmed.")),
                        exc.status_code)

    async def knowledge_error(request: Request, exc):
        return _failure("knowledge_unavailable",
                        "Knowledge is unavailable. An approved operator must check ingestion and ownership.", 503)

    app.add_exception_handler(OwnershipError, knowledge_error)
    app.add_exception_handler(IndexingError, knowledge_error)

    async def dependency_error(request: Request, exc):
        return _failure("dependency_unavailable",
                        "An Azure or model dependency is unavailable. Check deployment health; do not retry writes.", 503)

    app.add_exception_handler(AzureError, dependency_error)
    app.add_exception_handler(OpenAIError, dependency_error)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc):
        # Do not echo questions, tokens, submitted plans or validator exception text.
        return JSONResponse({
            "error": {"code": "invalid_request", "message": "Check the required fields and their length.",
                      "fields": [{"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()]},
        }, status_code=422)

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def ready(
        current: Annotated[Settings, Depends(get_settings)],
        knowledge: Annotated[Knowledge | None, Depends(get_readiness_knowledge)],
    ):
        if not _auth_configured(current):
            return JSONResponse({"status": "not_ready", "checks": {
                "authentication": "unconfigured", "knowledge": "not_checked",
            }}, status_code=503)
        try:
            status = knowledge.status()
        except (OwnershipError, IndexingError, AzureError, OpenAIError):
            return JSONResponse({"status": "not_ready", "checks": {
                "authentication": "configured", "knowledge": "unavailable",
            }}, status_code=503)
        available = _knowledge_ready(status)
        return JSONResponse({
            "status": "ready" if available else "not_ready",
            "checks": {"authentication": "configured", "knowledge": "ready" if available else "unavailable"},
            "coverage": "Authentication configuration and knowledge only; Foundry and Factory execution are not verified.",
        }, status_code=200 if available else 503)

    @app.get("/api/public-config")
    def public_config(current: Annotated[Settings, Depends(get_settings)]):
        return {"tenant_id": current.tenant_id, "client_id": current.auth.client_id,
                "audience": current.auth.audience, "required_scope": current.auth.required_scope}

    @app.get("/api/context")
    def context(
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
    ):
        scopes = []
        for key, scope in current.scopes.items():
            permissions = []
            for permission in PERMISSIONS:
                try:
                    authorize(current, principal, key, permission)
                except PermissionError:
                    continue
                permissions.append(permission)
            if permissions:
                scopes.append({"key": key, "label": f"{scope.factory} / {scope.project} / {scope.environment}",
                               "scope": scope.model_dump(mode="json"), "permissions": permissions})
        proposal_blockers = []
        if not current.factory.writes_enabled:
            proposal_blockers.append("writes_disabled")
        if not all((current.factory.factory_id, current.factory.scale_set_id, current.factory.project_id)):
            proposal_blockers.append("factory_target_unconfigured")
        return {
            "principal": {"tenant_id": principal.tenant_id, "object_id": principal.object_id},
            "scopes": scopes,
            "settings": {"agent_name": current.agent_name, "location": current.location,
                         "writes_enabled": current.factory.writes_enabled},
            "capabilities": {"model_read_only": True, "proposal_creation": True,
                             "proposal_blockers": proposal_blockers,
                             "destructive_actions": "delete-aifactory" in current.actions.enabled_skills
                             and current.factory.writes_enabled,
                             "skills_supported": True, "underlying_job_cancellation": False},
        }

    @app.post("/api/chat")
    def chat(
        body: ChatRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        knowledge: Annotated[Knowledge, Depends(get_knowledge)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        authorize(current, principal, body.scope_key, "knowledge.read")
        return services.conversation(knowledge).answer(body.question, body.audience, principal, body.scope_key)

    @app.get("/api/knowledge/status")
    def knowledge_status(
        scope_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,80}$")],
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        knowledge: Annotated[Knowledge, Depends(get_knowledge)],
    ):
        authorize(current, principal, scope_key, "knowledge.read")
        status = knowledge.status()
        return {"scope_key": scope_key, "status": status,
                "refresh": "External approved operator only; no HTTP refresh endpoint is exposed."}

    @app.get("/api/operations")
    def operations(
        principal: Annotated[Principal, Depends(get_principal)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
    ):
        return {"operations": store.list(principal)}

    @app.get("/api/skills")
    def skills(
        scope_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,80}$")],
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
    ):
        return {"scope_key": scope_key, "skills": skill_catalog(current, principal, scope_key)}

    @app.get("/api/templates")
    def templates(
        scope_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,80}$")],
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        authorize(current, principal, scope_key, "factory.read")
        return {"scope_key": scope_key, "templates": services.workloads(principal, scope_key, store=store).discover(),
                "coverage": "Only source types available in the approved purple source tree/bundle are discoverable; profiles and dependencies are required for creation."}

    @app.post("/api/skills/{skill_name}/run")
    def run_monitoring_skill(
        skill_name: str, body: SkillRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        name = normalize_skill(skill_name)
        if name not in COST_SKILLS and name not in DIAGNOSTIC_SKILLS:
            raise ToolError("approval_required", "Factory actions require a separate plan, approval and execution.", 409)
        authorize(current, principal, body.scope_key, "factory.read")
        authorize(current, principal, body.scope_key, SKILL_PERMISSIONS[name])
        if name in DIAGNOSTIC_SKILLS:
            from pydantic import ValidationError
            try:
                args = argument_model(name).model_validate(body.arguments)
            except ValidationError:
                raise ToolError("invalid_arguments", "Arguments do not match the closed diagnostic schema.", 400) from None
            if name == DIAGNOSTIC_SKILLS[2]:
                record = store.read(principal, args.operation_id)
                if record["scope_key"] != body.scope_key:
                    raise PermissionError("The saved operation belongs to another active scope.")
                record = store.observe(principal, args.operation_id, lambda stored:
                    services.tools(principal, body.scope_key, store=store).status_operation(stored))
                return {"ok": True, "data": record}
            tool_name = "factory_health" if name == DIAGNOSTIC_SKILLS[0] else "factory_settings"
            result = services.tools(principal, body.scope_key, store=store).execute(tool_name, body.arguments)
            if not isinstance(result, dict) or result.get("ok") is not True:
                error = result.get("error", {}) if isinstance(result, dict) else {}
                raise ToolError(error.get("code", "factory_api_error"), "Factory diagnostics are unavailable.",
                                error.get("status_code", 503))
            return result
        result = services.costs(principal, body.scope_key).execute(name, body.arguments)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ToolError("cost_unavailable", "Azure cost analysis did not confirm a report.", 503)
        return result

    @app.post("/api/skills/{skill_name}/propose", status_code=201)
    def propose_skill(
        skill_name: str, body: SkillRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        name = normalize_skill(skill_name)
        if name not in (*ACTION_SKILLS, *WORKLOAD_SKILLS):
            raise ToolError("unsupported_operation", "Monitoring skills run read-only and do not create approval plans.", 400)
        authorize(current, principal, body.scope_key, "factory.read")
        authorize(current, principal, body.scope_key, SKILL_PERMISSIONS[name])
        tools = services.tools(principal, body.scope_key, store=store)
        record = tools.prepare_skill(name, body.arguments)
        if (
            not isinstance(record, dict) or record.get("status") != "pending"
            or record.get("scope_key") != body.scope_key or record.get("tool_name") != name
            or record.get("tenant_id") != principal.tenant_id or record.get("object_id") != principal.object_id
            or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("plan_hash", "")))
        ):
            raise RuntimeError("The skill backend did not confirm a caller-bound pending plan.")
        return record

    @app.post("/api/operations/propose", status_code=201)
    def propose_operation(
        body: ProposalRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        authorize(current, principal, body.scope_key, "config.write")
        authorize(current, principal, body.scope_key, "factory.read")
        if not current.factory.writes_enabled:
            raise ToolError("writes_disabled", "Configuration writes are disabled.", 503)
        if not all((current.factory.factory_id, current.factory.scale_set_id, current.factory.project_id)):
            raise ToolError("factory_target_unconfigured", "Exact server target identifiers are required.", 503)
        tools = services.tools(principal, body.scope_key, store=store)
        result = tools.prepare_settings({"settings": body.settings.model_dump(mode="json")})
        if not isinstance(result, dict):
            raise RuntimeError("The proposal backend returned an invalid envelope.")
        if result.get("ok") is False:
            error = result.get("error")
            if (
                not isinstance(error, dict) or not isinstance(error.get("code"), str)
                or type(error.get("status_code")) is not int or not 400 <= error["status_code"] <= 599
            ):
                raise RuntimeError("The proposal backend returned an invalid failure envelope.")
            raise ToolError(error["code"], "The proposal was not confirmed.", error["status_code"])
        record = result.get("data")
        if (
            result.get("ok") is not True or not isinstance(record, dict)
            or record.get("status") != "pending" or record.get("scope_key") != body.scope_key
            or record.get("tenant_id") != principal.tenant_id or record.get("object_id") != principal.object_id
            or record.get("tool_name") != CONFIGURE_TOOL
            or not isinstance(record.get("id"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("plan_hash", "")))
        ):
            raise RuntimeError("The proposal backend did not confirm a caller-bound pending plan.")
        return record

    @app.get("/api/operations/{operation_id}")
    def operation(
        operation_id: str, principal: Annotated[Principal, Depends(get_principal)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
    ):
        return store.read(principal, operation_id)

    @app.post("/api/operations/{operation_id}/approve")
    def approve_operation(
        operation_id: str, body: ApprovalRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
    ):
        if body.confirmation_phrase is not None:
            return store.approve(principal, operation_id, body.plan_hash,
                                 confirmation_phrase=body.confirmation_phrase)
        return store.approve(principal, operation_id, body.plan_hash)

    @app.post("/api/operations/{operation_id}/execute")
    def execute_operation(
        operation_id: str,
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        def execute_record(record):
            tools = services.tools(principal, record["scope_key"], store=store)
            return tools.execute_operation(record)

        record = store.execute(principal, operation_id, execute_record)
        if record["status"] in ("failed", "uncertain"):
            code = (record.get("outcome") or {}).get("error", {}).get("status_code", 503)
            if not isinstance(code, int) or not 400 <= code <= 599:
                code = 503
            return JSONResponse({"operation": record, "error": {
                "code": "operation_" + record["status"],
                "message": "Execution failed or completion is unknown. Read the persisted operation; do not retry.",
            }}, status_code=code)
        return record

    @app.post("/api/operations/{operation_id}/cancel")
    def cancel_operation(
        operation_id: str, principal: Annotated[Principal, Depends(get_principal)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
    ):
        return store.cancel(principal, operation_id)

    @app.get("/api/operations/{operation_id}/status")
    def operation_status(
        operation_id: str, principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        def observe_record(record):
            return services.tools(principal, record["scope_key"], store=store).status_operation(record)
        return store.observe(principal, operation_id, observe_record)

    @app.post("/api/operations/{operation_id}/continue")
    def continue_operation(
        operation_id: str, body: ContinuationRequest,
        principal: Annotated[Principal, Depends(get_principal)],
        current: Annotated[Settings, Depends(get_settings)],
        store: Annotated[OperationStore, Depends(get_operation_store)],
        services: Annotated[AgentServices, Depends(get_services)],
    ):
        def continue_record(record):
            return services.tools(principal, record["scope_key"], store=store).continue_operation(record)
        record = store.continue_operation(principal, operation_id, body.plan_hash, body.observation_hash, continue_record)
        if record["status"] in ("failed", "uncertain"):
            return JSONResponse({"operation": record, "error": {
                "code": "continuation_" + record["status"],
                "message": "Continuation could not be confirmed. Inspect the saved operation; do not retry.",
            }}, status_code=503)
        return record

    @app.get("/")
    def frontend():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
