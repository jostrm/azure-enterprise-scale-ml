from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .actions import ActionSettings
from .costs import CostSettings
from .voice_settings import VoiceSettings
from .workloads import WorkloadSettings


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(ClosedModel):
    tenant_id: UUID
    subscription_id: UUID
    resource_group: str = Field(pattern=r"^[A-Za-z0-9_.()-]{1,90}$")
    factory: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    environment: Literal["dev", "stage", "prod"]


class Grant(ClosedModel):
    object_id: UUID
    scopes: list[str] = Field(min_length=1)
    permissions: list[Literal[
        "knowledge.read", "factory.read", "config.write", "knowledge.refresh", "graph.read",
        "factory.create", "factory.delete", "project.add", "cost.read", "agent.create", "model.create",
    ]]


class AzureSettings(ClosedModel):
    foundry_account: str
    foundry_project: str
    project_endpoint: str
    openai_endpoint: str
    model_deployment: str
    model_name: str
    model_version: str
    model_sku: str = "DataZoneStandard"
    model_capacity: int = Field(default=10, ge=1)
    embedding_deployment: str
    embedding_dimensions: int = Field(default=1536, ge=256, le=3072)
    search_endpoint: str
    search_index: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,127}$")
    storage_endpoint: str
    storage_container: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    credential: Literal["cli", "managed_identity"] = "managed_identity"
    managed_identity_client_id: str | None = None
    semantic_ranking: bool = True
    semantic_configuration: str = "aifactory-semantic"
    application_insights_connection_string: str | None = None
    application_insights_name: str | None = None

    @field_validator("project_endpoint", "openai_endpoint", "search_endpoint", "storage_endpoint")
    @classmethod
    def https_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Azure endpoints must be HTTPS without credentials, query or fragment.")
        return value.rstrip("/")


class KnowledgeSettings(ClosedModel):
    repository_root: Path
    source_base_url: str
    includes: list[str]
    excludes: list[str]
    max_file_bytes: int = Field(default=300000, ge=1024, le=2000000)
    chunk_chars: int = Field(default=4500, ge=1000, le=12000)
    max_embedding_tokens: int = Field(default=8000, ge=1000, le=8191)
    top_k: int = Field(default=6, ge=1, le=20)
    stale_after_hours: int = Field(default=48, ge=1)


class DualGraphSettings(ClosedModel):
    snapshot_root: Path
    expected_snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    allowed_scopes: list[str] = Field(min_length=1)
    allow_source_access: bool = False

    @field_validator("allowed_scopes")
    @classmethod
    def distinct_scopes(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Graph scopes must be explicit and distinct.")
        return value


class FactorySettings(ClosedModel):
    api_url: str = "http://127.0.0.1:8765"
    api_key_secret_url: str | None = None
    operation_signing_secret_url: str | None = None
    folder: str
    factory_id: UUID | None = None
    scale_set_id: UUID | None = None
    project_id: UUID | None = None
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    cli_executable: str = "python"
    writes_enabled: bool = False
    allowed_write_environments: list[Literal["dev", "stage", "prod"]] = Field(default_factory=lambda: ["dev"])


AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
# Reviewed public clients that may call this API for the same user, audience and delegated scope.
# Adding an entry is a security review decision: it also needs Entra pre-authorization (browser_auth.py).
REVIEWED_ADDITIONAL_CLIENTS = {AZURE_CLI_CLIENT_ID: "Microsoft Azure CLI"}


class AuthSettings(ClosedModel):
    client_id: str | None = None
    audience: str | None = None
    required_scope: str = "access_as_user"
    additional_client_ids: list[UUID] = Field(default_factory=list, max_length=len(REVIEWED_ADDITIONAL_CLIENTS))
    grants: list[Grant] = Field(default_factory=list)

    @model_validator(mode="after")
    def reviewed_additional_clients(self):
        clients = [str(client) for client in self.additional_client_ids]
        if len(set(clients)) != len(clients) or any(client not in REVIEWED_ADDITIONAL_CLIENTS for client in clients):
            raise ValueError("Additional API clients must be distinct, reviewed public clients.")
        try:
            primary = str(UUID(str(self.client_id))) if self.client_id else None
        except ValueError:
            primary = None
        if primary in clients:
            raise ValueError("An additional API client cannot repeat the primary registration.")
        return self


class Settings(ClosedModel):
    location: str
    scopes: dict[str, Scope]
    azure: AzureSettings
    knowledge: KnowledgeSettings
    dual_graph: DualGraphSettings | None = None
    factory: FactorySettings
    auth: AuthSettings
    actions: ActionSettings = Field(default_factory=ActionSettings)
    costs: CostSettings = Field(default_factory=CostSettings)
    workloads: WorkloadSettings = Field(default_factory=WorkloadSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    agent_name: str = Field(default="enterprise-scale-ai-factory", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$")
    agent_version: str | None = None
    agent_invocation: Literal["project_reference", "agent_endpoint"] = "project_reference"
    max_tool_rounds: int = Field(default=6, ge=1, le=12)
    max_output_tokens: int = Field(default=1800, ge=100, le=10000)
    model_throttle_wait_seconds: int = Field(default=90, ge=0, le=180)

    @model_validator(mode="after")
    def valid_grants(self):
        if self.agent_invocation == "agent_endpoint" and self.agent_version is not None:
            raise ValueError("Agent endpoint mode uses its existing version selector; an agent_version override is not supported.")
        if not self.scopes:
            raise ValueError("At least one explicitly configured scope is required.")
        tenants = {s.tenant_id for s in self.scopes.values()}
        if len(tenants) != 1:
            raise ValueError("One tenant per deployment; deploy separately for another tenant.")
        for grant in self.auth.grants:
            if any(key not in self.scopes for key in grant.scopes):
                raise ValueError("An access grant references an unknown scope.")
        if self.dual_graph and set(self.dual_graph.allowed_scopes) - self.scopes.keys():
            raise ValueError("Graph configuration references an unknown scope.")
        configured_skill_scopes = (
            set(self.actions.bootstrap_profiles) | set(self.actions.deletion_resource_groups)
            | set(self.costs.common_resource_groups)
            | set(self.workloads.profiles)
        )
        if configured_skill_scopes - self.scopes.keys():
            raise ValueError("Skill target configuration references an unknown scope.")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) for key in self.scopes):
            raise ValueError("Scope keys must be safe identifiers.")
        return self

    @property
    def tenant_id(self) -> str:
        return str(next(iter(self.scopes.values())).tenant_id)


def load_settings(path: str | Path | None = None) -> Settings:
    selected = Path(path or os.environ["AIFACTORY_AGENT_CONFIG"]).resolve()
    settings = Settings.model_validate(json.loads(selected.read_text(encoding="utf-8")))
    root = settings.knowledge.repository_root
    if not root.is_absolute():
        root = (selected.parent / root).resolve()
    knowledge = settings.knowledge.model_copy(update={"repository_root": root})
    updates = {"knowledge": knowledge}
    if settings.dual_graph:
        snapshot_root = settings.dual_graph.snapshot_root
        if not snapshot_root.is_absolute():
            snapshot_root = (selected.parent / snapshot_root).resolve()
        updates["dual_graph"] = settings.dual_graph.model_copy(update={"snapshot_root": snapshot_root})
    if settings.workloads.repository_root:
        workload_root = Path(settings.workloads.repository_root)
        if not workload_root.is_absolute():
            workload_root = (selected.parent / workload_root).resolve()
        updates["workloads"] = settings.workloads.model_copy(update={"repository_root": str(workload_root)})
    return settings.model_copy(update=updates)


def credential(settings: Settings):
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    if settings.azure.credential == "cli":
        return AzureCliCredential(tenant_id=settings.tenant_id)
    return ManagedIdentityCredential(client_id=settings.azure.managed_identity_client_id)
