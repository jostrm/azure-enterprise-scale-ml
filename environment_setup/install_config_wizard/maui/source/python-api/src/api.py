"""Authenticated HTTP API for AIFactory configuration operations."""

from __future__ import annotations

import copy
import errno
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import tempfile
import threading
from functools import lru_cache
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from src import operations as operations_backend
from src import wizard
from src import factory_configuration
from src import azure_auth
from src import project_verification, scale_set_verification
from src import ticketing, factory_analytics
from src import simple_mode
from src import project_deployments
from src import factory_catalog
from src.factory_catalog_models import (
    CatalogConfirm, CatalogConfirmed, CatalogJob, CatalogJobs, CatalogPrepare, CatalogPreview, CatalogSummary, CatalogSettings,
)
from src.catalog_parameter_models import CatalogParameters, CatalogParameterPrepare
from src.project_metadata import owner_from_project_state, planned_environments_from_project_state
from src.region_findings import MAX_CONTENT_BYTES
from src.network_placement import preview_network_placement


FormatName = Literal["yaml", "env", "json"]
API_KEY_ENV = "AIFACTORY_API_KEY"


class StateBody(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)


class NetworkPlacementEnvironment(BaseModel):
    environment: str
    range_key: str
    start_octet: str
    vnet_cidr: str
    common_subnets: dict[str, str]
    common_range: str
    estimated_full_projects: int | None = Field(
        description="Append-only allocator estimate, or null when capacity is unsupported (for example /24)."
    )


class NetworkPlacementPreview(BaseModel):
    guidance: str
    is_peerable: bool = Field(
        default=False,
        description="True only when all three resolved IPv4 VNets and common subnets are valid and non-overlapping. "
                    "Address intent only; actual Azure peering is not verified.",
    )
    can_optimize: bool
    optimization_changes: dict[str, str]
    optimization_description: str
    environments: list[NetworkPlacementEnvironment]


class ImportBody(StateBody):
    format: FormatName
    content: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.content is None) == (self.path is None):
            raise ValueError("Provide exactly one of content or path")
        return self


class ExportBody(StateBody):
    format: FormatName
    path: str | None = None


class FolderBody(BaseModel):
    aifactory_folder: str


class DeploymentFolderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder: str = Field(min_length=1, max_length=1024)


class ProjectDeploymentPlanBody(DeploymentFolderBody):
    project_number: str = Field(pattern=r"^[0-9]{1,3}$")
    source_environment: Literal["dev", "stage", "prod"]
    target_environment: Literal["dev", "stage", "prod"]
    patch: bool = Field(default=False, strict=True)
    operation: Literal["deploy", "update"] = "deploy"
    aifactory_version: str | None = Field(default=None, strict=True, min_length=1, max_length=32)

    @model_validator(mode="after")
    def valid_operation_target(self):
        if self.operation == "update":
            valid = self.source_environment == self.target_environment
        else:
            valid = (self.source_environment, self.target_environment) in (("dev", "stage"), ("stage", "prod"), ("dev", "prod"))
        if not valid:
            raise ValueError("Deploy requires a later environment; Update requires the same environment.")
        return self


class ProjectDeploymentPrepareBody(DeploymentFolderBody):
    draft_id: str = Field(pattern="^" + simple_mode.GUID + "$")
    patch: bool = Field(default=False, strict=True)
    aifactory_version: str | None = Field(default=None, strict=True, min_length=1, max_length=32)


class ProjectDeploymentStartBody(DeploymentFolderBody):
    confirmation_id: str = Field(pattern="^" + simple_mode.GUID + "$")


class ProjectTerminalBody(DeploymentFolderBody):
    job_id: str = Field(pattern="^" + simple_mode.GUID + "$")


class ProjectTerminalInputBody(ProjectTerminalBody):
    data: str = Field(strict=True, min_length=1, max_length=8192)


class ProjectTerminalResizeBody(ProjectTerminalBody):
    columns: int = Field(strict=True, ge=20, le=500)
    rows: int = Field(strict=True, ge=5, le=200)


class ProjectDeploymentAcknowledgement(BaseModel):
    version: Literal[2]
    draft_id: str
    operation: Literal["deploy", "update"]
    patch: bool = Field(strict=True)
    aifactory_version: str | None = Field(default=None, exclude_if=lambda value: value is None)
    requested_version: str = ""
    branch: str = ""
    resolved_ref: str = ""


class ProjectDeploymentDraft(BaseModel):
    id: str
    project_number: str
    source_environment: str
    target_environment: str
    operation: Literal["deploy", "update"] = "deploy"
    patch: bool = False
    status: Literal["draft", "queued", "running", "submitted", "failed", "interrupted"]
    message: str
    route: Literal["ado", "gha"]
    script_path: str
    job_id: str | None
    created_at: str
    updated_at: str
    reconciled_at: str | None = None
    aifactory_version: str | None = Field(default=None, exclude_if=lambda value: value is None)
    requested_version: str = ""
    branch: str = ""
    resolved_ref: str = ""

    @computed_field
    @property
    def deployment_contract(self) -> ProjectDeploymentAcknowledgement:
        return ProjectDeploymentAcknowledgement(**project_deployments.deployment_acknowledgement({
            "id": self.id, "operation": self.operation, "patch": self.patch,
            "aifactory_version": self.aifactory_version, "requested_version": self.requested_version,
            "branch": self.branch, "resolved_ref": self.resolved_ref,
        }))


class ProjectDeploymentVersionSelection(BaseModel):
    requested_version: str
    branch: str
    resolved_ref: str


class ProjectDeploymentDrafts(BaseModel):
    drafts: list[ProjectDeploymentDraft]
    requested_version: str = ""
    branch: str = ""
    resolved_ref: str = ""
    version_selection: ProjectDeploymentVersionSelection | None = None
    version_blockers: list[str] = Field(default_factory=list)


class ProjectDeploymentPreview(BaseModel):
    confirmation_id: str
    can_execute: bool
    summary: str
    command: str
    working_directory: str
    effects: list[str]
    warnings: list[str]
    blockers: list[str]
    expires_at: str
    deployment_contract: ProjectDeploymentAcknowledgement | None = None
    aifactory_version: str | None = Field(default=None, exclude_if=lambda value: value is None)
    requested_version: str = ""
    branch: str = ""
    resolved_ref: str = ""


class ProjectTerminalOutput(BaseModel):
    job_id: str
    output: str
    next_cursor: int
    reset: bool
    status: str


class AzureAuthBody(BaseModel):
    aifactory_folder: str | None = Field(
        default=None, description="Optional server-local factory folder; omitted uses the cached default Azure CLI account.",
    )


class AzureLoginBody(AzureAuthBody):
    tenant_id: str | None = Field(
        default=None, description="Tenant UUID belonging to the selected factory/account context.",
    )


class PrivateTicketBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TicketListBody(PrivateTicketBody):
    aifactory_folder: str | None = Field(default=None, min_length=1, max_length=4096)


TicketType = Literal["Request Azure service", "Bug report", "Blocker"]
TicketStatus = Literal["New", "Active", "Solved"]
TicketSeverity = Literal["minor", "major", "blocker"]


class TicketResourceGroupBody(PrivateTicketBody):
    resource_group: str = Field(strict=True, min_length=1, max_length=90)


class TicketResourceGroupIdentity(BaseModel):
    resource_group: str
    environment: str
    project_number: str
    region: str
    ai_factory_prefix: str
    ai_factory_suffix: str


class TicketCreateBody(PrivateTicketBody):
    aifactory_folder: str | None = Field(default=None, min_length=1, max_length=4096)
    project_number: str | None = Field(default=None, pattern=r"^\d{1,6}$")
    resource_group: str | None = Field(default=None, strict=True, min_length=1, max_length=90)
    severity: TicketSeverity | None = None
    cost_center: str | None = Field(default=None, strict=True, max_length=200)
    department_name: str | None = Field(default=None, strict=True, max_length=200)
    type: TicketType
    title: str = Field(min_length=1, max_length=255, pattern=r"\S")
    description: str = Field(min_length=1, max_length=16000, pattern=r"\S")
    requested_service: str | None = Field(default=None, max_length=200)


class TicketUpdateBody(PrivateTicketBody):
    id: str = Field(min_length=1, max_length=64)
    status: TicketStatus
    severity: TicketSeverity | None = None


class TicketConnectionBody(PrivateTicketBody):
    id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128, pattern=r"\S")
    provider: Literal["Jira", "ServiceNow"]
    base_url: str = Field(min_length=1, max_length=2048)
    project_key: str | None = Field(default=None, max_length=64)
    username: str | None = Field(default=None, max_length=254)
    credential_env: str = Field(min_length=1, max_length=128)


class TicketPreviewBody(PrivateTicketBody):
    ticket_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)


class TicketSyncBody(PrivateTicketBody):
    confirmation_id: str = Field(min_length=1, max_length=64)


class SimpleModePrepareBody(PrivateTicketBody):
    aifactory_version: str | None = Field(default=None, strict=True, min_length=1, max_length=32)
    subscription_id: str = Field(strict=True, min_length=36, max_length=36, pattern="^" + simple_mode.GUID + "$")
    tenant_id: str = Field(strict=True, min_length=36, max_length=36, pattern="^" + simple_mode.GUID + "$")
    location: str = Field(default="swedencentral", strict=True, min_length=2, max_length=40,
                          pattern="^" + simple_mode.FIELDS["location"][1] + "$")
    factory_prefix: str = Field(default="aif-", strict=True, min_length=3, max_length=12,
                                pattern="^" + simple_mode.FIELDS["factory_prefix"][1] + "$")
    github_repository: str = Field(strict=True, min_length=3, max_length=140,
                                   pattern="^" + simple_mode.FIELDS["github_repository"][1] + "$")
    team_member_email: str = Field(strict=True, min_length=3, max_length=254,
                                   pattern="^" + simple_mode.FIELDS["team_member_email"][1] + "$")
    team_group_name: str = Field(strict=True, min_length=1, max_length=120,
                                 pattern="^" + simple_mode.FIELDS["team_group_name"][1] + "$")
    cost_center: str = Field(default="123456", strict=True, min_length=1, max_length=32,
                             pattern="^" + simple_mode.FIELDS["cost_center"][1] + "$")
    repo_root: str = Field(strict=True, min_length=1, max_length=240)
    github_visibility: Literal["private", "public"] = "private"
    project_resources: list[str] = Field(
        default_factory=list, max_length=50,
        description="Optional project resource IDs only. Omit for catalog defaults; [] disables all optional resources. Required foundations remain included.",
    )
    app_gateway_backend_fqdn: str = Field(default="", strict=True, max_length=253)
    app_gateway_hostname: str = Field(default="", strict=True, max_length=253)
    app_gateway_certificate_secret_id: str = Field(
        default="", strict=True, max_length=2048,
        description="Existing Key Vault TLS certificate secret URI, never a certificate or secret value.",
    )

class SimpleModeStartBody(PrivateTicketBody):
    confirmation_id: str = Field(strict=True, min_length=36, max_length=36, pattern="^" + simple_mode.GUID + "$")


class SimpleModeAccount(BaseModel):
    subscription_id: str
    subscription_name: str
    tenant_id: str
    account_name: str


class SimpleModeResource(BaseModel):
    id: str
    label: str
    description: str
    required: bool
    default_selected: bool
    dependencies: list[str]


class SimpleModeResourceCatalog(BaseModel):
    hub: list[SimpleModeResource]
    common: list[SimpleModeResource]
    project: list[SimpleModeResource]


class SimpleModeOptions(BaseModel):
    defaults: dict[str, str | list[str]]
    azure_accounts: list[SimpleModeAccount]
    github_account: str
    regions: list[str]
    requirements: list[str]
    warnings: list[str]
    script_path: str
    github_visibilities: list[Literal["private", "public"]]
    resource_catalog: SimpleModeResourceCatalog


class SimpleModePreview(BaseModel):
    confirmation_id: str
    can_execute: bool
    summary: str
    script_path: str
    command: str
    environment: dict[str, str]
    effects: list[str]
    requirements: list[str]
    warnings: list[str]
    blockers: list[str]
    expires_at: str
    github_visibility: Literal["private", "public"]
    project_resources: list[str]
    resource_catalog: SimpleModeResourceCatalog
    aifactory_version: str | None = Field(default=None, exclude_if=lambda value: value is None)
    requested_version: str = ""
    branch: str = ""
    resolved_ref: str = ""


class SimpleModeJob(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    stage: str
    message: str
    created_at: str
    updated_at: str
    exit_code: int | None
    repository_url: str
    repo_root: str
    events: list[str]


class Ticket(BaseModel):
    id: str
    title: str
    description: str
    type: TicketType
    status: TicketStatus
    severity: TicketSeverity
    owner: str
    project_number: str
    resource_group: str
    environment: str
    region: str
    ai_factory_prefix: str
    ai_factory_suffix: str
    cost_center: str
    department_name: str
    aifactory_folder: str
    requested_service: str
    created_at: str
    updated_at: str
    external_url: str = ""
    sync_state: str = "local"


class TicketCounts(BaseModel):
    new: int
    active: int
    solved: int


class TicketsListed(BaseModel):
    owner: str
    tickets: list[Ticket]
    counts: TicketCounts
    warning: str = ""


class TicketConnection(BaseModel):
    id: str
    name: str
    provider: Literal["Jira", "ServiceNow"]
    base_url: str
    project_key: str
    username: str
    credential_env: str
    owner: str
    created_at: str
    updated_at: str


class TicketConnectionsListed(BaseModel):
    connections: list[TicketConnection]


class TicketSyncPreview(BaseModel):
    confirmation_id: str
    recipient: str
    content: str


class FactoryAnalyticsSection(BaseModel):
    title: str
    description: str
    columns: list[str]
    rows: list[list[str]]
    source: str


class CurrentFactoryAnalytics(BaseModel):
    title: Literal["Current AI Factory"]
    source: str
    generated_at: str
    warning: str
    sections: list[FactoryAnalyticsSection]


class ProjectBody(FolderBody):
    project_number: str = Field(pattern=r"^\d+$")


class ProjectSaveBody(StateBody):
    write_variables: bool = True


class ProjectDeleteBody(ProjectBody):
    aifactory_folder: str = Field(min_length=1, max_length=4096)
    path: str = Field(
        min_length=1, max_length=4096,
        description="Exact server-local snapshot path returned by POST /api/v1/projects; not a directory.",
    )


class ProjectDeleted(BaseModel):
    deleted_path: str
    message: str


class ScaleSetBody(FolderBody):
    scale_set_id: str


class ScaleSetDeleteBody(ScaleSetBody):
    aifactory_folder: str = Field(strict=True, min_length=1, max_length=4096)
    scale_set_id: str = Field(strict=True, min_length=1, max_length=255)
    path: str = Field(
        strict=True, min_length=1, max_length=4096,
        description="Exact server-local snapshot path returned by POST /api/v1/scale-sets; not a directory.",
    )


class ScaleSetDeleted(BaseModel):
    deleted_path: str
    message: str


class ScaleSetVerifyBody(ScaleSetDeleteBody):
    pass


class ResourceGroupVerification(BaseModel):
    resource_id: str
    http_status: int | None
    verified: bool
    message: str


class ProjectVerifyBody(ProjectBody):
    aifactory_folder: str = Field(strict=True, min_length=1, max_length=4096)
    project_number: str = Field(strict=True, min_length=1, max_length=255, pattern=r"^[0-9]+$")
    path: str = Field(
        strict=True, min_length=1, max_length=4096,
        description="Exact server-local snapshot path returned by POST /api/v1/projects; not a directory.",
    )


class ProjectVerified(BaseModel):
    project_number: str
    checked_at: str
    message: str
    checks: list[ResourceGroupVerification]


class ScaleSetVerified(BaseModel):
    scale_set_id: str
    checked_at: str
    message: str
    checks: list[ResourceGroupVerification]


class ScaleSetDeploymentScope(BaseModel):
    prefix_rg: str
    suffix_rg: str
    region: str
    subscription_ids: list[str]


class ScaleSetSummary(BaseModel):
    scale_set_id: str
    path: str
    deployment_scope: ScaleSetDeploymentScope


class ScaleSetsListed(BaseModel):
    scale_sets: list[ScaleSetSummary]


class ProjectSummary(BaseModel):
    project_number: str
    path: str
    label: str
    owner: str
    planned_environments: list[Literal["dev", "stage", "prod"]]
    deployment_scope: ScaleSetDeploymentScope


class ProjectsListed(BaseModel):
    projects: list[ProjectSummary]


class RecentProjectBody(ProjectBody):
    orchestrator: Literal["ado", "gha"]
    prefix_rg: str = ""
    suffix_rg: str = ""


EnvironmentName = Literal["dev", "stage", "prod"]
OperationKind = Literal["dataops", "mlops", "rag", "finetuning"]


class OperationsOverviewBody(FolderBody):
    aifactory_folder: str = Field(
        min_length=1, description="Server-local AIFactory folder."
    )
    include_azure: bool = Field(
        default=True, description="Include read-only Azure inventory and telemetry."
    )
    force_refresh: bool = Field(
        default=False, description="Bypass a cached Azure snapshot."
    )


class RegionFindingsReportBody(FolderBody):
    aifactory_folder: str = Field(min_length=1, max_length=4096)
    report: dict[str, Any]


class RegionFindingsImportBody(FolderBody):
    aifactory_folder: str = Field(min_length=1, max_length=4096)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_BYTES)


class RegionFindingsRecorded(BaseModel):
    recorded: int
    message: str


class OperationsConfigBody(FolderBody):
    aifactory_folder: str = Field(min_length=1)
    project_number: str = Field(pattern=r"^\d{1,6}$")
    environment: EnvironmentName
    kind: OperationKind


class OperationsConfigSaveBody(OperationsConfigBody):
    config: dict[str, Any] = Field(
        default_factory=dict, description="Partial configuration merged with defaults."
    )


class FactoryActionBody(FolderBody):
    aifactory_folder: str = Field(min_length=1)
    action: Literal["create", "clone", "delete"]
    target_region: str = Field(pattern=r"^[a-z0-9]+$")
    source_region: str | None = Field(default=None, pattern=r"^[a-z0-9]+$")

    @model_validator(mode="after")
    def clone_has_source(self):
        if self.action == "clone" and not self.source_region:
            raise ValueError("source_region is required for clone")
        return self


class FactoryConfigurationPrepareBody(BaseModel):
    kind: Literal["factory", "scale-set", "clone"]
    target_region: str = Field(min_length=1)
    source_folder: str | None = None


class FactoryConfigurationSaveBody(FactoryConfigurationPrepareBody):
    destination_folder: str = Field(min_length=1)
    state: dict[str, Any]


class FactoryConfigurationPrepared(BaseModel):
    state: dict[str, Any]
    field_keys: list[str]
    message: str


class FactoryConfigurationSaved(BaseModel):
    state: dict[str, Any]
    path: str
    message: str


class ProjectActionBody(FolderBody):
    aifactory_folder: str = Field(min_length=1)
    project_number: str = Field(pattern=r"^\d{1,6}$")
    source_environment: EnvironmentName
    target_environment: EnvironmentName
    action: Literal["promote", "deploy", "promotion", "deployment"]

    @model_validator(mode="after")
    def environments_differ(self):
        if self.source_environment == self.target_environment:
            raise ValueError("source_environment and target_environment must differ")
        return self


class PromptSearchBody(FolderBody):
    aifactory_folder: str = Field(min_length=1)
    project_number: str | None = Field(default=None, pattern=r"^\d{1,6}$")
    environment: EnvironmentName | None = None
    model: str | None = Field(default=None, max_length=200)
    category: Literal[
        "Coding", "Data/Analytics", "MLOps", "Operations",
        "Security/Governance", "Search/RAG", "Content/Communication",
        "Planning", "General",
    ] | None = None
    search: str | None = Field(default=None, max_length=500)
    success: bool | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def authenticate(x_api_key: str | None = Depends(api_key_header)) -> None:
    expected = os.environ.get(API_KEY_ENV, "")
    if not expected:
        raise HTTPException(503, f"Set {API_KEY_ENV} on the API process")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid API key")


@asynccontextmanager
async def _api_lifespan(application):
    try:
        yield
    finally:
        _shutdown_project_deployments()
        if getattr(_catalog_service, "cache_info", lambda: None)() and _catalog_service.cache_info().currsize:
            _catalog_service().runtime.shutdown()
            _catalog_service.cache_clear()


app = FastAPI(
    title="AIFactory Config API",
    version="1.0.0",
    description="API equivalent of the AIFactory Config Wizard workflows.",
    lifespan=_api_lifespan,
    openapi_tags=[
        {"name": "Setup", "description": "Defaults, schema, and startup-folder loading."},
        {"name": "Import / Export", "description": "YAML, .env, and JSON conversion."},
        {"name": "Project Variables", "description": "Project configuration persistence."},
        {"name": "Scale Set Variables", "description": "Scale-set configuration persistence."},
        {"name": "Factory Configuration", "description": "Local-only Add and Clone workflows; no Azure changes."},
        {"name": "Validation", "description": "Wizard-compatible state validation."},
        {"name": "Recent Projects", "description": "Recently opened ADO and GHA projects."},
        {"name": "Azure Authentication", "description": "Shared OS-user Azure CLI authentication; not an application-specific token cache."},
        {
            "name": "Operations",
            "description": (
                "Local factory discovery, read-only Azure telemetry, operations "
                "configuration, prompt exploration, and draft actions."
            ),
        },
    ],
)
secured = [Depends(authenticate)]


@app.exception_handler(factory_catalog.CatalogError)
async def catalog_scope_error(request: Request, exc: factory_catalog.CatalogError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def private_ticket_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/v1/factory-catalog"):
        return JSONResponse(status_code=422, content={
            "detail": "Invalid catalog request. Contract version 1 and explicit typed scope are required; unknown fields are rejected."
        })
    if request.url.path.startswith("/api/v1/operations/project-deployments"):
        return JSONResponse(status_code=422, content={
            "detail": "Invalid deployment request. Check the documented fields, input limits and terminal dimensions."
        })
    if request.url.path.startswith("/api/v1/simple-mode/"):
        return JSONResponse(status_code=422, content={
            "detail": "Invalid Simple Mode request. Check the documented fields and lengths. "
                      "Credentials, arbitrary scripts, environment variables and advanced state are not accepted."
        })
    if request.url.path.startswith("/api/v1/tickets/"):
        # Pydantic's default response echoes rejected inputs, including accidental credentials.
        return JSONResponse(status_code=422, content={
            "detail": "Invalid ticket request. Check required fields, allowed values and lengths. "
                      "Client-provided owners or credential values are not accepted."
        })
    return await request_validation_exception_handler(request, exc)


def _require_auth_loopback(request: Request) -> None:
    try:
        address = ipaddress.ip_address(request.client.host if request.client else "")
        mapped = getattr(address, "ipv4_mapped", None)
        allowed = (mapped or address).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(403, "Azure browser sign-in and shared CLI logout require a loopback client.")


def _azure_auth_call(action, *args) -> azure_auth.AzureAuthStatus:
    try:
        return action(*args)
    except azure_auth.AuthRequestError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@app.post(
    "/api/v1/azure/auth/status", tags=["Azure Authentication"], dependencies=secured,
    response_model=azure_auth.AzureAuthStatus,
    summary="Check usable Azure CLI authentication without interactive login",
    description="Checks token expiry metadata for all known factory tenants. Status is cached for 20 seconds by folder and tenant/subscription context; resource RBAC is not tested.",
)
def azure_auth_status(body: AzureAuthBody) -> azure_auth.AzureAuthStatus:
    return _azure_auth_call(azure_auth.azure_auth_service.status, body.aifactory_folder)


@app.post(
    "/api/v1/azure/auth/login", tags=["Azure Authentication"],
    dependencies=[*secured, Depends(_require_auth_loopback)],
    response_model=azure_auth.AzureAuthStatus,
    summary="Start explicit browser login on the API host machine",
    description="Returns a pending operation immediately. Only call following a user click. Uses the shared Azure CLI cache without global config changes.",
    responses={403: {"description": "Non-loopback client"}, 409: {"description": "Another authentication operation is active"}},
)
def azure_auth_login(body: AzureLoginBody) -> azure_auth.AzureAuthStatus:
    return _azure_auth_call(azure_auth.azure_auth_service.login, body.aifactory_folder, body.tenant_id)


@app.post(
    "/api/v1/azure/auth/logout", tags=["Azure Authentication"],
    dependencies=[*secured, Depends(_require_auth_loopback)],
    response_model=azure_auth.AzureAuthStatus,
    summary="Sign out the OS user's shared Azure CLI cache",
    description="Returns a pending operation immediately. Client must confirm that other Azure CLI tooling is also signed out. Does not sign out browser, Microsoft 365, or Scout.",
    responses={403: {"description": "Non-loopback client"}, 409: {"description": "Another authentication operation is active"}},
)
def azure_auth_logout(body: AzureAuthBody) -> azure_auth.AzureAuthStatus:
    return _azure_auth_call(azure_auth.azure_auth_service.logout, body.aifactory_folder)


@app.get(
    "/api/v1/azure/auth/operations/{operation_id}", tags=["Azure Authentication"],
    dependencies=secured, response_model=azure_auth.AzureAuthStatus,
    summary="Read a pending or completed Azure authentication operation",
    description="Retains the most recent 32 operations in API process memory. Poll until state is no longer signing_in/signing_out, then refresh status for the current folder.",
    responses={404: {"description": "Unknown or evicted operation"}},
)
def azure_auth_operation(operation_id: str) -> azure_auth.AzureAuthStatus:
    result = azure_auth.azure_auth_service.operation(operation_id)
    if result is None:
        raise HTTPException(404, "Azure authentication operation not found.")
    return result


def _operations_service() -> operations_backend.OperationsService:
    """Create a facade against the currently configured operations database."""
    return operations_backend.OperationsService()


def _ticket_service() -> ticketing.TicketService:
    return ticketing.TicketService()


@lru_cache(maxsize=1)
def _simple_mode_service() -> simple_mode.SimpleModeService:
    return simple_mode.SimpleModeService()


@lru_cache(maxsize=1)
def _project_deployment_service() -> project_deployments.ProjectDeploymentService:
    return project_deployments.ProjectDeploymentService()


@lru_cache(maxsize=1)
def _catalog_service() -> factory_catalog.CatalogService:
    return factory_catalog.CatalogService()


def _catalog_owner(request: Request) -> str:
    import hashlib
    host_owner = os.environ.get("AIFACTORY_CATALOG_OWNER")
    if host_owner:
        return hashlib.sha256(("host:" + host_owner).encode("utf-8")).hexdigest()
    return hashlib.sha256(request.headers["X-API-Key"].encode("utf-8")).hexdigest()


def _catalog_call(action):
    try:
        return action()
    except (ticketing.TicketError, factory_configuration.ConfigurationError) as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Catalog storage is unavailable; no unverified operation is reported as successful.") from None


_catalog_security = [*secured, Depends(_require_auth_loopback)]


@app.get("/api/v1/factory-catalog", tags=["Factory Catalog"], dependencies=_catalog_security,
         response_model=CatalogSummary)
def catalog_list(folder: str):
    return _catalog_call(lambda: _catalog_service().list(folder))


@app.get("/api/v1/factory-catalog/settings", tags=["Factory Catalog"], dependencies=_catalog_security,
         response_model=CatalogSettings)
def catalog_settings_read(folder: str, factory_id: str, scale_set_id: str | None = None, project_id: str | None = None):
    from src import catalog_settings
    return _catalog_call(lambda: CatalogSettings.model_validate(
        catalog_settings.read(folder, factory_id, scale_set_id, project_id)).model_dump(mode="json"))


def _catalog_parameter_service():
    from src.catalog_parameters import ParameterService
    return ParameterService(_catalog_service())


@app.get("/api/v1/factory-catalog/parameters", tags=["Factory Catalog"], dependencies=_catalog_security,
         response_model=CatalogParameters)
def catalog_parameters_read(folder: str, factory_id: str, scale_set_id: str,
                            project_id: str | None = None, version_ref: str | None = None):
    return _catalog_call(lambda: _catalog_parameter_service().read(folder, factory_id, scale_set_id, project_id, version_ref))


@app.post("/api/v1/factory-catalog/parameters/prepare", tags=["Factory Catalog"], dependencies=_catalog_security,
          response_model=CatalogPreview)
def catalog_parameters_prepare(body: CatalogParameterPrepare, request: Request):
    return _catalog_call(lambda: _catalog_parameter_service().prepare(body.model_dump(mode="json"), _catalog_owner(request)))


@app.post("/api/v1/factory-catalog/parameters/confirm", tags=["Factory Catalog"], dependencies=_catalog_security,
          response_model=CatalogConfirmed)
def catalog_parameters_confirm(body: CatalogConfirm, request: Request):
    return _catalog_call(lambda: _catalog_parameter_service().confirm(body.folder, str(body.confirmation_id), _catalog_owner(request)))


@app.post("/api/v1/factory-catalog/prepare", tags=["Factory Catalog"], dependencies=_catalog_security,
          response_model=CatalogPreview)
def catalog_prepare(body: CatalogPrepare, request: Request):
    return _catalog_call(lambda: _catalog_service().prepare(body.model_dump(mode="json"), _catalog_owner(request)))


@app.post("/api/v1/factory-catalog/confirm", tags=["Factory Catalog"], dependencies=_catalog_security,
          response_model=CatalogConfirmed)
def catalog_confirm(body: CatalogConfirm, request: Request):
    return _catalog_call(lambda: _catalog_service().confirm(body.folder, str(body.confirmation_id), _catalog_owner(request)))


@app.get("/api/v1/factory-catalog/jobs", tags=["Factory Catalog"], dependencies=_catalog_security,
         response_model=CatalogJobs)
def catalog_jobs(folder: str, request: Request):
    return _catalog_call(lambda: {"jobs": _catalog_service().jobs(folder, _catalog_owner(request))})


@app.get("/api/v1/factory-catalog/jobs/{job_id}", tags=["Factory Catalog"], dependencies=_catalog_security,
         response_model=CatalogJob)
def catalog_job(job_id: str, folder: str, request: Request):
    return _catalog_call(lambda: _catalog_service().job(folder, job_id, _catalog_owner(request)))


@app.get("/api/v1/factory-catalog/terminal", tags=["Factory Catalog"], dependencies=_catalog_security,
         response_model=ProjectTerminalOutput)
def catalog_terminal(folder: str, job_id: str, request: Request, cursor: int = 0):
    return _catalog_call(lambda: _catalog_service().runtime.terminal(
        factory_catalog.root_folder(folder), job_id, _catalog_owner(request), cursor))


@app.post("/api/v1/factory-catalog/terminal/input", tags=["Factory Catalog"], dependencies=_catalog_security)
def catalog_terminal_input(body: ProjectTerminalInputBody, request: Request):
    return _catalog_call(lambda: _catalog_service().runtime.input(
        factory_catalog.root_folder(body.folder), body.job_id, _catalog_owner(request), body.data))


@app.post("/api/v1/factory-catalog/terminal/resize", tags=["Factory Catalog"], dependencies=_catalog_security)
def catalog_terminal_resize(body: ProjectTerminalResizeBody, request: Request):
    return _catalog_call(lambda: _catalog_service().runtime.resize(
        factory_catalog.root_folder(body.folder), body.job_id, _catalog_owner(request), body.columns, body.rows))


@app.post("/api/v1/factory-catalog/terminal/stop", tags=["Factory Catalog"], dependencies=_catalog_security,
          response_model=CatalogJob)
def catalog_terminal_stop(body: ProjectTerminalBody, request: Request):
    return _catalog_call(lambda: _catalog_service().runtime.stop(
        factory_catalog.root_folder(body.folder), body.job_id, _catalog_owner(request)))


def _require_legacy_root(folder):
    if isinstance(folder, (str, os.PathLike)) and folder and factory_catalog.has_catalog(folder):
        raise HTTPException(409, "Catalog roots require explicit factory/scale-set selection through /api/v1/factory-catalog; legacy root operations are not allowed.")


def _project_deployment_call(action):
    try:
        return action()
    except ticketing.TicketError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except sqlite3.Error:
        raise HTTPException(503, "Deployment storage is unavailable; check the local operations database.") from None
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(409, "Deployment configuration or terminal is unavailable; inspect the selected factory and prepare again.") from None


def _shutdown_project_deployments():
    if getattr(_project_deployment_service, "cache_info", lambda: None)() and _project_deployment_service.cache_info().currsize:
        _project_deployment_service().shutdown()
        _project_deployment_service.cache_clear()


_deployment_security = [*secured, Depends(_require_auth_loopback)]


@app.get("/api/v1/operations/project-deployments", tags=["Operations"], dependencies=_deployment_security,
         response_model=ProjectDeploymentDrafts)
def list_project_deployments(folder: str):
    _require_legacy_root(folder)
    return _project_deployment_call(lambda: _project_deployment_service().list(folder))


@app.post("/api/v1/operations/project-deployments/plan", tags=["Operations"], dependencies=_deployment_security,
          response_model=ProjectDeploymentDraft)
def plan_project_deployment(body: ProjectDeploymentPlanBody):
    """Persist an idempotent local draft; never execute a script or change Azure."""
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().plan(**body.model_dump()))


@app.post("/api/v1/operations/project-deployments/prepare", tags=["Operations"], dependencies=_deployment_security,
          response_model=ProjectDeploymentPreview)
def prepare_project_deployment(body: ProjectDeploymentPrepareBody):
    """Review the exact command/environment, immutable inputs, effects and blockers."""
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().prepare(**body.model_dump()))


@app.post("/api/v1/operations/project-deployments/start", tags=["Operations"], dependencies=_deployment_security,
          response_model=ProjectDeploymentDraft)
def start_project_deployment(body: ProjectDeploymentStartBody):
    """Consume explicitly confirmed owner-bound consent; never retry failed or interrupted jobs."""
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().start(**body.model_dump()))


@app.post("/api/v1/operations/project-deployments/reconcile/prepare", tags=["Operations"], dependencies=_deployment_security,
          response_model=ProjectDeploymentPreview)
def prepare_project_deployment_reconciliation(body: ProjectTerminalBody):
    """Review manual acknowledgement of a failed job; never retry or change cloud resources."""
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().prepare_reconciliation(**body.model_dump()))


@app.post("/api/v1/operations/project-deployments/reconcile", tags=["Operations"], dependencies=_deployment_security,
          response_model=ProjectDeploymentDraft)
def reconcile_project_deployment(body: ProjectDeploymentStartBody):
    """Consume explicit outcome-review consent and release only this job's repository safety hold."""
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().reconcile(**body.model_dump()))


@app.get("/api/v1/operations/project-deployments/terminal", tags=["Operations"], dependencies=_deployment_security,
         response_model=ProjectTerminalOutput)
def project_deployment_terminal(folder: str, job_id: str, cursor: int = 0):
    _require_legacy_root(folder)
    result = _project_deployment_call(lambda: _project_deployment_service().terminal(folder, job_id, cursor))
    return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@app.post("/api/v1/operations/project-deployments/terminal/input", tags=["Operations"], dependencies=_deployment_security)
def project_deployment_terminal_input(body: ProjectTerminalInputBody):
    """Send input once to the active owned PTY. Clients must never automatically retry input."""
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().input(**body.model_dump()))


@app.post("/api/v1/operations/project-deployments/terminal/resize", tags=["Operations"], dependencies=_deployment_security)
def project_deployment_terminal_resize(body: ProjectTerminalResizeBody):
    _require_legacy_root(body.folder)
    return _project_deployment_call(lambda: _project_deployment_service().resize(**body.model_dump()))


def _simple_mode_call(action):
    try:
        return action()
    except ticketing.TicketError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except sqlite3.Error:
        raise HTTPException(503, "Simple Mode storage is unavailable. Check the API host operations database.") from None
    except OSError:
        raise HTTPException(503, "Simple Mode could not inspect the host filesystem. Check host access and prepare again.") from None


@app.get("/api/v1/simple-mode/options", tags=["Simple Mode"], dependencies=secured,
         response_model=SimpleModeOptions)
def simple_mode_options():
    """Read host account metadata and form defaults; never create a workspace."""
    return _simple_mode_call(lambda: _simple_mode_service().options())


@app.post("/api/v1/simple-mode/prepare", tags=["Simple Mode"], dependencies=secured,
          response_model=SimpleModePreview)
def prepare_simple_mode(body: SimpleModePrepareBody):
    """Read-only preflight and an immutable ten-minute owner-bound confirmation; no bootstrap execution."""
    data = body.model_dump()
    if "project_resources" not in body.model_fields_set:
        data.pop("project_resources")
    return _simple_mode_call(lambda: _simple_mode_service().prepare(data))


@app.post("/api/v1/simple-mode/start", tags=["Simple Mode"], dependencies=secured,
          response_model=SimpleModeJob)
def start_simple_mode(body: SimpleModeStartBody):
    """Execute only after explicit user confirmation of the preview; duplicate IDs return the same durable job."""
    return _simple_mode_call(lambda: _simple_mode_service().start(body.confirmation_id))


@app.get("/api/v1/simple-mode/jobs/{job_id}", tags=["Simple Mode"], dependencies=secured,
         response_model=SimpleModeJob)
def simple_mode_job(job_id: str):
    """Poll bounded high-level events; only the current authenticated Azure owner can read the job."""
    return _simple_mode_call(lambda: _simple_mode_service().get_job(job_id))


def _private_data_call(action):
    try:
        return action()
    except ticketing.TicketError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except sqlite3.Error:
        raise HTTPException(503, "Local analytics/ticket storage is unavailable. Check the API host database access.") from None
    except (OSError, ValueError):
        raise HTTPException(422, "Current factory configuration or ticket request could not be read or validated.") from None


@app.post("/api/v1/analytics/current-factory", tags=["Analytics"], dependencies=secured,
          response_model=CurrentFactoryAnalytics)
def current_factory_analytics(body: FolderBody):
    _require_legacy_root(body.aifactory_folder)
    return _private_data_call(lambda: factory_analytics.FactoryAnalytics(_operations_service()).current(body.aifactory_folder))


@app.post("/api/v1/tickets/list", tags=["Tickets"], dependencies=secured, response_model=TicketsListed)
def list_private_tickets(body: TicketListBody):
    return _private_data_call(lambda: _ticket_service().list_tickets(body.aifactory_folder))


@app.post("/api/v1/tickets/resource-group/parse", tags=["Tickets"], dependencies=secured,
          response_model=TicketResourceGroupIdentity)
def parse_ticket_resource_group(body: TicketResourceGroupBody):
    """Preview naming metadata only; no Azure sign-in, deployment or access verification."""
    return _private_data_call(lambda: ticketing.parse_ticket_resource_group(body.resource_group))


@app.post("/api/v1/tickets/create", tags=["Tickets"], dependencies=secured, response_model=Ticket)
def create_private_ticket(body: TicketCreateBody):
    return _private_data_call(lambda: _ticket_service().create(body.model_dump()))


@app.post("/api/v1/tickets/update", tags=["Tickets"], dependencies=secured, response_model=Ticket)
def update_private_ticket(body: TicketUpdateBody):
    return _private_data_call(lambda: _ticket_service().update(body.id, body.status, body.severity))


@app.post("/api/v1/tickets/connections/list", tags=["Tickets"], dependencies=secured,
          response_model=TicketConnectionsListed)
def list_ticket_connections(body: PrivateTicketBody):
    return _private_data_call(lambda: _ticket_service().list_connections())


@app.post("/api/v1/tickets/connections/save", tags=["Tickets"], dependencies=secured,
          response_model=TicketConnection)
def save_ticket_connection(body: TicketConnectionBody):
    return _private_data_call(lambda: _ticket_service().save_connection(body.model_dump()))


@app.post("/api/v1/tickets/sync/preview", tags=["Tickets"], dependencies=secured,
          response_model=TicketSyncPreview)
def preview_ticket_sync(body: TicketPreviewBody):
    return _private_data_call(lambda: _ticket_service().preview(body.ticket_id, body.connection_id))


@app.post("/api/v1/tickets/sync", tags=["Tickets"], dependencies=secured, response_model=Ticket)
def confirm_ticket_sync(body: TicketSyncBody):
    return _private_data_call(lambda: _ticket_service().sync(body.confirmation_id))


class ApiHost:
    """Run the API in a background thread owned by the desktop application."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._server = None
        self._thread = None
        self._error = None

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def status(self) -> str:
        if self._error is not None:
            return "failed"
        if self._thread is None or not self._thread.is_alive():
            return "stopped"
        if self._server is not None and self._server.started:
            return "running"
        return "starting"

    @property
    def error(self) -> Exception | None:
        return self._error

    def start(self) -> bool:
        if self.is_running:
            return False
        if not os.environ.get(API_KEY_ENV):
            raise RuntimeError(f"Set {API_KEY_ENV} before starting the API host")

        import uvicorn

        self._error = None
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            config = uvicorn.Config(
                app, host=self.host, port=self.port, log_level="info", log_config=None
            )
            self._server = uvicorn.Server(config)
            def run_server():
                try:
                    self._server.run(sockets=[listener])
                except Exception as exc:
                    self._error = exc

            self._thread = threading.Thread(
                target=run_server,
                name="aifactory-api-host",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            listener.close()
            self._server = None
            self._thread = None
            raise
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        self._error = None


def _state(values: dict[str, Any] | None = None) -> dict[str, Any]:
    result = wizard.new_configuration_defaults()
    if values:
        result.update(wizard.hub_configuration(values))
    return result


def _import(path: str, format_name: FormatName, state: dict[str, Any]) -> int:
    if format_name == "yaml":
        return wizard._import_yaml_to_state(path, state)
    if format_name == "env":
        return wizard._import_env_to_state(path, state)
    return wizard._import_json_to_state(path, state)


def _render(format_name: FormatName, state: dict[str, Any]) -> str:
    if format_name == "yaml":
        return "".join(wizard._render_azure_devops(state))
    if format_name == "env":
        return "".join(wizard._render_github_actions(state))
    return json.dumps(wizard._render_variables_json(state), indent=2,
                      ensure_ascii=False) + "\n"


def _project(folder: str, number: str) -> tuple[str, dict[str, Any]]:
    _require_legacy_root(folder)
    path = wizard._list_project_snapshots(folder).get(number)
    if not path:
        raise HTTPException(404, "Project not found")
    state = wizard._load_project_state(path, folder)
    return path, state


@app.get("/health", tags=["Setup"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/v1/schema", tags=["Setup"], dependencies=secured)
def schema() -> dict[str, Any]:
    scale_set = set(wizard.SCALESET_KEYS)
    keys = sorted(set(wizard.DEFAULT_STATE) | set(wizard.YAML_MAP) | set(wizard.ENV_MAP))
    return {
        "formats": ["yaml", "env", "json"],
        "orchestrators": ["ado", "gha"],
        "defaults": _state(),
        "mappings": {"yaml": wizard.YAML_MAP, "env": wizard.ENV_MAP},
        "sections": {
            "scale_set_variables": sorted(scale_set),
            "project_variables": [key for key in keys if key not in scale_set],
        },
        "options": {
            "azure_regions": sorted(region["name"] for region in operations_backend.azure_region_catalog()),
            "azure_region_suffixes": wizard.azure_region_suffixes(),
            "network_modes": wizard.NETWORK_MODE_FLAGS,
            "scaling_modes": copy.deepcopy(wizard.SCALING_MODES),
            "scaling_network_profiles": copy.deepcopy(wizard.SCALING_NETWORK_PROFILES),
            "vnet_format_help": wizard.vnet_format_help(),
            "versions": wizard.VERSION_BRANCH,
            "ai_search_skus": wizard.AI_SEARCH_SKUS,
            "semantic_skus": wizard.SEMANTIC_SKUS,
            "diagnostic_levels": wizard.DIAG_LEVELS,
            "acr_skus": wizard.ACR_SKUS,
        },
    }


@app.post("/api/v1/state/defaults", tags=["Setup"], dependencies=secured)
def defaults(body: StateBody) -> dict[str, Any]:
    return {"state": _state(body.state)}


@app.post(
    "/api/v1/network/placement/preview", tags=["Setup"], dependencies=secured,
    response_model=NetworkPlacementPreview,
    summary="Preview draft network capacity and earliest common subnet placement",
    description=(
        "API-key only; no Azure identity, inventory, persistence or deployment. Analyze raw state "
        "without merging defaults: scaling-mode, common_vnet_cidr, dev_cidr_range, test_cidr_range, "
        "prod_cidr_range and the four common subnet CIDRs. Validates strict IPv4 alignment, subnet containment "
        "and pairwise Dev/Stage/Prod VNet non-overlap. is_peerable describes address intent, not live peering. "
        "Capacity estimates support /16 through /23; a valid /24 can be peerable with null capacity. "
        "Invalid/overlapping drafts return is_peerable=false, can_optimize=false and no changes; explicitly "
        "Apply network defaults to repair legacy addressing. Optimization preserves every resolved VNet "
        "and validates the combined plan. Confirm optimization_changes before applying only those start ranges."
    ),
)
def network_placement_preview(body: StateBody) -> dict[str, Any]:
    return preview_network_placement(body.state)


@app.post("/api/v1/validation", tags=["Validation"], dependencies=secured)
def validate(body: StateBody) -> dict[str, Any]:
    state = _state(body.state)
    gates = {
        "cmkKeyName": ("cmk", "true"),
        "byoAseFullResourceId": ("byoASEv3", "true"),
        "byoAseAppServicePlanResourceId": ("byoASEv3", "true"),
    }
    issues = wizard.scaling_validation_issues(state) + wizard.hub_validation_issues(state)
    for key, value in state.items():
        if not isinstance(value, str) or "<todo>" not in value.lower():
            continue
        gate = gates.get(key)
        if gate and str(state.get(gate[0], "")).lower() != gate[1]:
            continue
        if key.startswith("_") or key == "technical_admins_email":
            continue
        if state.get("orchestrator") == "gha" and "service_connection" in key:
            continue
        issues.append({"field": key, "code": "todo", "message": "Value contains <todo>"})
    return {"valid": not issues, "issues": issues}


@app.post("/api/v1/import", tags=["Import / Export"], dependencies=secured)
def import_config(body: ImportBody) -> dict[str, Any]:
    state = _state(body.state)
    temp_path = ""
    try:
        path = body.path
        if body.content is not None:
            suffix = {"yaml": ".yaml", "env": ".env", "json": ".json"}[body.format]
            with tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8",
                                             delete=False) as temp:
                temp.write(body.content)
                temp_path = temp.name
            path = temp_path
        count = _import(path or "", body.format, state)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
    if count == 0:
        raise HTTPException(422, "No matching variables found")
    return {"format": body.format, "fields_loaded": count, "state": state,
            "warnings": wizard.scaling_validation_issues(state)}


@app.post("/api/v1/export", tags=["Import / Export"], dependencies=secured)
def export_config(body: ExportBody) -> dict[str, Any]:
    try:
        content = _render(body.format, _state(body.state))
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if body.path:
        destination = Path(body.path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return {"format": body.format, "path": body.path, "content": content}


@app.post("/api/v1/startup/load", tags=["Setup"], dependencies=secured)
def startup_load(body: ProjectBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    state = _state({"_save_folder": body.aifactory_folder,
                    "project_number_000": body.project_number})
    path, route = wizard._startup_import_candidate(body.aifactory_folder, state)
    state["orchestrator"] = route
    count = 0
    if path:
        name = Path(path).name
        format_name: FormatName = "env" if name == ".env" else Path(path).suffix[1:]  # type: ignore[assignment]
        count = _import(path, format_name, state)
        route = state["orchestrator"]
    return {"source_path": path, "orchestrator": route,
            "fields_loaded": count, "state": state,
            "warnings": wizard.scaling_validation_issues(state)}


@app.post("/api/v1/projects", tags=["Project Variables"], dependencies=secured, response_model=ProjectsListed)
def projects(body: FolderBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    result = []
    for number, path in sorted(wizard._list_project_snapshots(body.aifactory_folder).items()):
        _, state = _project(body.aifactory_folder, number)
        metadata_state = state if Path(path).resolve().is_relative_to(Path(body.aifactory_folder).resolve()) else {}
        subscriptions = (state.get(key) for key in ("dev_sub_id", "test_sub_id", "prod_sub_id"))
        result.append({"project_number": number, "path": path,
                       "owner": owner_from_project_state(metadata_state, number),
                       "planned_environments": planned_environments_from_project_state(metadata_state, number),
                       "label": wizard._recent_project_label(
                           number, state.get("admin_aifactoryPrefixRG", ""),
                           state.get("admin_aifactorySuffixRG", "")),
                       "deployment_scope": {
                           "prefix_rg": state.get("admin_aifactoryPrefixRG", ""),
                           "suffix_rg": state.get("admin_aifactorySuffixRG", ""),
                           "region": state.get("admin_location", ""),
                           "subscription_ids": sorted({
                               value.strip() for value in subscriptions
                               if isinstance(value, str) and value.strip()
                           }),
                       }})
    return {"projects": result}


@app.post(
    "/api/v1/projects/verify-resource-groups", tags=["Project Variables"], dependencies=secured,
    response_model=ProjectVerified,
    summary="Verify fresh authenticated ARM access to a saved project's observed resource groups",
    description=(
        "Validates the exact listed path and numeric project_number, then hydrates saved state "
        "using only the same project's current variables. Matches prefix, suffix, region, environment "
        "and subscription to the active factory's observed project resource-group references. "
        "Never substitutes common groups, guessed names or Portal URLs. Each unique group requires "
        "a fresh ARM GET returning exactly HTTP 200 and a matching JSON resource ID. "
        "Redirects are not followed and credentials never leave the backend. "
        "At most 12 groups; CLI timeout 30 seconds and GET timeout 20 seconds. "
        "Configuration changes invalidate results. Empty checks or any unverified check must not "
        "indicate successful access. No Azure resources or configuration files are changed."
    ),
    responses={
        400: {"description": "Invalid local path, saved state, or project identity"},
        401: {"description": "Missing or invalid API key"},
        404: {"description": "Factory folder or saved snapshot no longer exists"},
        409: {"description": "Snapshot path, identity, owner, or hydrated state conflicts with the selection"},
    },
)
def project_verify_resource_groups(body: ProjectVerifyBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    try:
        return project_verification.verify_resource_groups(
            body.aifactory_folder, body.project_number, body.path,
        )
    except project_verification.VerificationRequestError as error:
        raise HTTPException(error.status_code, str(error)) from None


@app.post("/api/v1/projects/load", tags=["Project Variables"], dependencies=secured)
def project_load(body: ProjectBody) -> dict[str, Any]:
    path, state = _project(body.aifactory_folder, body.project_number)
    return {"path": path, "state": state}


@app.post("/api/v1/projects/save", tags=["Project Variables"], dependencies=secured)
def project_save(body: ProjectSaveBody) -> dict[str, Any]:
    state = _state(body.state)
    _require_legacy_root(state.get("_save_folder"))
    try:
        snapshot = wizard._save_project_snapshot(state)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    variables = None
    if body.write_variables:
        folder = Path(state["_save_folder"]) / "config-wizard" / f"project-{state['project_number_000']}"
        folder.mkdir(parents=True, exist_ok=True)
        variables = folder / (".env" if state.get("orchestrator") == "gha" else "variables.yaml")
        if state.get("orchestrator") == "gha":
            wizard.save_github_actions(state, str(variables))
        else:
            wizard.save_azure_devops(state, str(variables))
    return {"snapshot_path": snapshot, "variables_path": str(variables) if variables else None}


@app.post(
    "/api/v1/projects/delete", tags=["Project Variables"], dependencies=secured,
    response_model=ProjectDeleted,
    summary="Delete only the selected saved local project snapshot",
    description=(
        "Requires the exact path and project number from the current project listing. "
        "Unlinks only the saved snapshot, never its directory, exported variables, pipelines, "
        "app settings, or Azure resources. Clients must ask for confirmation before calling."
    ),
    responses={
        404: {"description": "Snapshot or factory folder no longer exists"},
        409: {"description": "Path, project identity, or legacy factory ownership does not match"},
        422: {"description": "Invalid path, symbolic link/reparse point, malformed snapshot, or permission denied"},
        500: {"description": "Filesystem failure; OS details are not exposed"},
    },
)
def project_delete(body: ProjectDeleteBody) -> ProjectDeleted:
    _require_legacy_root(body.aifactory_folder)
    try:
        deleted_path = wizard._delete_project_snapshot(
            body.aifactory_folder, body.project_number, body.path,
        )
    except wizard.ProjectConfigDeleteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return ProjectDeleted(
        deleted_path=deleted_path,
        message="Saved project snapshot deleted. Exported variables, pipelines, and Azure resources were not changed.",
    )


@app.post(
    "/api/v1/scale-sets", tags=["Scale Set Variables"], dependencies=secured,
    response_model=ScaleSetsListed,
    description="List saved snapshots and deployment scope from saved state only, without factory/template defaults.",
)
def scale_sets(body: FolderBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    result = []
    for key, path in sorted(wizard._list_scalesets(
            body.aifactory_folder, create_legacy_dir=False).items()):
        try:
            with open(path, "r", encoding="utf-8") as source:
                state = json.load(source)
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Scale set snapshot must contain valid JSON") from None
        except FileNotFoundError:
            raise HTTPException(404, "Scale set snapshot not found; refresh the scale set list") from None
        except (PermissionError, IsADirectoryError):
            raise HTTPException(422, "Scale set snapshot must be a readable ordinary file") from None
        except OSError:
            raise HTTPException(500, "Unable to read the saved scale set snapshot because of a filesystem error") from None
        if not isinstance(state, dict):
            raise HTTPException(422, "Scale set snapshot must contain a JSON object")
        scope = {}
        for field, state_key in (("prefix_rg", "admin_aifactoryPrefixRG"),
                                 ("suffix_rg", "admin_aifactorySuffixRG"),
                                 ("region", "admin_location")):
            value = state.get(state_key)
            if value is not None and not isinstance(value, str):
                raise HTTPException(422, "Saved scale set deployment scope must contain text values")
            scope[field] = value if value is not None else ""
        subscriptions = (state.get(name) for name in ("dev_sub_id", "test_sub_id", "prod_sub_id"))
        scope["subscription_ids"] = sorted({
            value.strip() for value in subscriptions
            if isinstance(value, str) and value.strip()
        })
        result.append({"scale_set_id": key, "path": path, "deployment_scope": scope})
    return {"scale_sets": result}


@app.post(
    "/api/v1/scale-sets/verify-resource-groups", tags=["Scale Set Variables"], dependencies=secured,
    response_model=ScaleSetVerified,
    summary="Verify fresh authenticated ARM access to a saved scale set's observed common resource groups",
    description=(
        "Uses the exact path and scale_set_id from the current listing. Matches saved scope to "
        "the active factory and reuses scoped inventory only to identify common resource groups. "
        "Each group requires a fresh ARM GET returning exactly HTTP 200 and a matching JSON resource ID. "
        "Never requests Portal URLs, follows redirects, returns credentials, or changes Azure resources. "
        "At most 12 groups; CLI timeout 30 seconds and GET timeout 20 seconds. "
        "Empty checks or any unverified check must not indicate successful access."
    ),
    responses={
        400: {"description": "Invalid local path, saved state, or scale-set identity"},
        401: {"description": "Missing or invalid API key"},
        404: {"description": "Factory folder or saved snapshot no longer exists"},
        409: {"description": "Snapshot path, identity, or owner conflicts with the selection"},
    },
)
def scale_set_verify_resource_groups(body: ScaleSetVerifyBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    try:
        return scale_set_verification.verify_resource_groups(
            body.aifactory_folder, body.scale_set_id, body.path,
        )
    except scale_set_verification.VerificationRequestError as error:
        raise HTTPException(error.status_code, str(error)) from None


@app.post("/api/v1/scale-sets/load", tags=["Scale Set Variables"], dependencies=secured)
def scale_set_load(body: ScaleSetBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    path = wizard._list_scalesets(body.aifactory_folder).get(body.scale_set_id)
    if not path:
        raise HTTPException(404, "Scale set not found")
    with open(path, "r", encoding="utf-8") as source:
        state = json.load(source)
    state = wizard.hub_configuration(state)
    state.setdefault(wizard.SCALING_MODE_KEY, wizard.DEFAULT_SCALING_MODE)
    state["_save_folder"] = body.aifactory_folder
    return {"path": path, "state": state}


@app.post("/api/v1/scale-sets/save", tags=["Scale Set Variables"], dependencies=secured)
def scale_set_save(body: StateBody) -> dict[str, Any]:
    _require_legacy_root(body.state.get("_save_folder"))
    try:
        return {"path": wizard._save_scaleset_snapshot(_state(body.state))}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post(
    "/api/v1/scale-sets/delete", tags=["Scale Set Variables"], dependencies=secured,
    response_model=ScaleSetDeleted,
    summary="Delete only the selected saved local scale-set snapshot",
    description=(
        "Requires the exact path and scale_set_id from the current scale-set listing. "
        "Unlinks only that scaleset_*.json snapshot, never directories, factory state, "
        "exported variables, projects, app settings, or Azure resources. "
        "Clients must ask for confirmation before calling."
    ),
    responses={
        404: {"description": "Snapshot or factory folder no longer exists"},
        409: {"description": "Path, scale-set identity, or legacy factory ownership does not match"},
        422: {"description": "Invalid identity/path, symbolic link/reparse point, malformed snapshot, or permission denied"},
        500: {"description": "Filesystem failure; OS details are not exposed"},
    },
)
def scale_set_delete(body: ScaleSetDeleteBody) -> ScaleSetDeleted:
    _require_legacy_root(body.aifactory_folder)
    try:
        deleted_path = wizard._delete_scaleset_snapshot(
            body.aifactory_folder, body.scale_set_id, body.path,
        )
    except wizard.ConfigDeleteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return ScaleSetDeleted(
        deleted_path=deleted_path,
        message="Saved scale-set snapshot deleted. Exported variables, projects, and Azure resources were not changed.",
    )


@app.get("/api/v1/recent-projects", tags=["Recent Projects"], dependencies=secured)
def recent_projects() -> dict[str, Any]:
    return {"recent_projects": wizard._load_app_settings().get("recent_projects", [])}


@app.post("/api/v1/recent-projects", tags=["Recent Projects"], dependencies=secured)
def recent_project_record(body: RecentProjectBody) -> dict[str, Any]:
    wizard._record_recent_project(
        body.aifactory_folder, body.project_number, body.orchestrator,
        body.prefix_rg, body.suffix_rg)
    return recent_projects()


def _configuration_result(operation, **kwargs):
    try:
        return operation(**kwargs)
    except factory_configuration.ConfigurationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Configuration folder or source file not found") from exc
    except PermissionError as exc:
        raise HTTPException(400, "Configuration folder is not accessible") from exc
    except (NotADirectoryError, IsADirectoryError) as exc:
        raise HTTPException(409, "A configuration path conflicts with an existing file or folder") from exc
    except OSError as exc:
        status = 409 if exc.errno in (errno.EEXIST, errno.ENOTEMPTY) else 400
        raise HTTPException(status, f"Unable to access or save configuration: {exc}") from exc
    except UnicodeError as exc:
        raise HTTPException(422, "Configuration files must be valid UTF-8 text") from exc


@app.post(
    "/api/v1/factories/configuration/prepare", tags=["Factory Configuration"],
    dependencies=secured, response_model=FactoryConfigurationPrepared,
    summary="Prepare a configuration-only factory, scale set, or clone",
)
def factory_configuration_prepare(body: FactoryConfigurationPrepareBody) -> dict[str, Any]:
    return _configuration_result(
        factory_configuration.prepare_configuration, **body.model_dump()
    )


@app.post(
    "/api/v1/factories/configuration/save", tags=["Factory Configuration"],
    dependencies=secured, response_model=FactoryConfigurationSaved,
    summary="Save a new local configuration without overwriting existing files",
)
def factory_configuration_save(body: FactoryConfigurationSaveBody) -> dict[str, Any]:
    return _configuration_result(
        factory_configuration.save_configuration, **body.model_dump()
    )


@app.post(
    "/api/v1/operations/overview",
    tags=["Operations"],
    dependencies=secured,
    summary="Get the operations overview",
    description=(
        "Combines local AIFactory discovery with read-only Azure inventory, "
        "telemetry charts, saved configuration, and prompt aggregates."
    ),
)
def operations_overview(body: OperationsOverviewBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    return _operations_service().overview(
        body.aifactory_folder, body.include_azure, body.force_refresh
    )


@app.get(
    "/api/v1/operations/regions",
    tags=["Operations"],
    dependencies=secured,
    summary="List Azure public-cloud regions",
)
def operations_regions() -> dict[str, Any]:
    regions = operations_backend.azure_region_catalog()
    return {"regions": regions, "count": len(regions)}


@app.post(
    "/api/v1/operations/region-findings/report", tags=["Operations"],
    dependencies=secured, response_model=RegionFindingsRecorded,
    summary="Record scoped historical regional findings",
    description=(
        "Persist a schema-version-1 pipeline_artifact or explicitly entered "
        "user_reported report. Scope must match the selected current factory. "
        "No Azure or pipeline calls are made."
    ),
)
def operations_region_findings_report(body: RegionFindingsReportBody) -> dict[str, Any]:
    try:
        return _operations_service().report_region_findings(body.aifactory_folder, body.report)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.post(
    "/api/v1/operations/region-findings/import", tags=["Operations"],
    dependencies=secured, response_model=RegionFindingsRecorded,
    summary="Import a downloaded historical region-findings JSON report",
    description=(
        "Accepts at most 1 MiB of JSON content with at most 200 observations. "
        "Does not download artifacts or accept remote paths."
    ),
)
def operations_region_findings_import(body: RegionFindingsImportBody) -> dict[str, Any]:
    try:
        return _operations_service().import_region_findings(body.aifactory_folder, body.content)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.post(
    "/api/v1/operations/config/load",
    tags=["Operations"],
    dependencies=secured,
    summary="Load operations configuration",
)
def operations_config_load(body: OperationsConfigBody) -> dict[str, Any]:
    return _operations_service().load_config(
        body.aifactory_folder, body.project_number, body.environment, body.kind
    )


@app.post(
    "/api/v1/operations/config/save",
    tags=["Operations"],
    dependencies=secured,
    summary="Save operations configuration",
    description="Persists configuration locally in SQLite; it does not mutate Azure.",
)
def operations_config_save(body: OperationsConfigSaveBody) -> dict[str, Any]:
    return _operations_service().save_config(
        body.aifactory_folder, body.project_number, body.environment,
        body.kind, body.config,
    )


@app.post(
    "/api/v1/operations/factory-actions",
    tags=["Operations"],
    dependencies=secured,
    summary="Create a draft factory action",
    description=(
        "Stores a create, clone, or delete request as a local draft. "
        "No Azure mutation is performed."
    ),
)
def operations_factory_action(body: FactoryActionBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    return _operations_service().create_factory_action(
        body.aifactory_folder, body.action, body.target_region, body.source_region
    )


@app.post(
    "/api/v1/operations/project-actions",
    tags=["Operations"],
    dependencies=secured,
    summary="Create a draft project action",
    description=(
        "Stores a promotion or deployment request as a local draft. "
        "No deployment or Azure mutation is performed."
    ),
)
def operations_project_action(body: ProjectActionBody) -> dict[str, Any]:
    _require_legacy_root(body.aifactory_folder)
    return _operations_service().create_project_action(
        body.aifactory_folder, body.project_number, body.source_environment,
        body.target_environment, body.action,
    )


@app.post(
    "/api/v1/operations/prompts/search",
    tags=["Operations"],
    dependencies=secured,
    summary="Search local prompt telemetry",
    description=(
        "Searches prompt records stored only in local SQLite. Supports filters "
        "and paging and never sends prompt content to an external service."
    ),
)
def operations_prompt_search(body: PromptSearchBody) -> dict[str, Any]:
    return _operations_service().prompts(
        body.aifactory_folder, body.project_number, body.environment, body.model,
        body.category, body.search, body.success, body.limit, body.offset,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8765)