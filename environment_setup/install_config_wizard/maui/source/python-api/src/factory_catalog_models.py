"""Versioned, closed request and response contracts for opt-in factory catalogs."""

from typing import Literal
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src import release_version
from src.ticket_connectors import TicketError


Environment = Literal["dev", "stage", "prod"]
Route = Literal["ado", "gha"]
Action = Literal["migrate", "create-factory", "clone", "create-scale-set", "add-project", "add-project-placements",
                 "configure-binding", "configure-settings", "deploy", "delete-factory", "delete-scale-set"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LockEnrollment(ClosedModel):
    account_url: str = Field(pattern=r"^https://[a-z0-9]{3,24}\.blob\.core\.windows\.net$")
    container: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    coordination_blob: str = Field(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_./-]{0,255}$")
    coordination_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(strict=True, ge=1)


class BindingTarget(ClosedModel):
    scale_set_id: UUID
    resource_group_ids: list[str] = Field(min_length=1, max_length=24)
    common_dependency_ids: list[str] = Field(default_factory=list, max_length=24)
    execution: "TargetExecution | None" = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def exact_scopes(self):
        values = [*self.resource_group_ids, *self.common_dependency_ids]
        for value in values:
            match = re.fullmatch(r"/subscriptions/([a-f0-9-]{36})/resourceGroups/([A-Za-z0-9_.()-]{1,90})", value, re.I)
            if not match or not UUID(match[1]).int or match[2] in (".", ".."):
                raise ValueError("Lock scopes must be exact resource-group ARM IDs.")
        if len({value.lower() for value in values}) != len(values):
            raise ValueError("Writable scopes and shared dependencies must be unique and disjoint.")
        return self


class HostedRunner(ClosedModel):
    kind: Literal["hosted"]
    os: Literal["linux"]
    image: Literal["ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"]


class GitHubSelfHostedRunner(ClosedModel):
    kind: Literal["self-hosted"]
    os: Literal["linux"]
    labels: list[str] = Field(min_length=2, max_length=16)

    @model_validator(mode="after")
    def explicit_labels(self):
        if (any(not re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", label) for label in self.labels)
                or not {"self-hosted", "linux"} <= {label.lower() for label in self.labels}):
            raise ValueError("Self-hosted GitHub runners require explicit self-hosted and linux labels.")
        return self


class AdoSelfHostedRunner(ClosedModel):
    kind: Literal["self-hosted"]
    os: Literal["linux"]
    pool: str = Field(pattern=r"^[A-Za-z0-9_. -]{1,128}$")
    agent_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_. -]{0,128}$",
                                  exclude_if=lambda value: value is None)


class TargetExecution(ClosedModel):
    writer_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    auth_namespace: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    deployment_object_id: UUID
    runner: HostedRunner | GitHubSelfHostedRunner | AdoSelfHostedRunner

    @model_validator(mode="after")
    def concrete_principal(self):
        if not self.deployment_object_id.int:
            raise ValueError("A concrete deployment principal object ID is required.")
        return self


class RuntimeBinding(ClosedModel):
    contract_version: int = Field(strict=True, ge=1, le=1)
    orchestrator: Route
    writer_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    repository: str = Field(min_length=1, max_length=1024)
    ref: str = Field(pattern=r"^refs/(heads|tags)/[A-Za-z0-9_./-]+$")
    shared_remote: bool = Field(strict=True)
    auth_namespace: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    deployment_object_id: UUID | None = None
    runner: HostedRunner | GitHubSelfHostedRunner | AdoSelfHostedRunner | None = Field(
        default=None, exclude_if=lambda value: value is None)
    locks: LockEnrollment
    targets: list[BindingTarget] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def safe_binding(self):
        pattern = (r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" if self.orchestrator == "gha" else
                   r"https://dev\.azure\.com/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+/_git/[A-Za-z0-9_.%-]+")
        if (not re.fullmatch(pattern, self.repository) or any(part in (".", "..") for part in self.repository.split("/"))
                or ".." in self.ref or ".." in self.locks.coordination_blob):
            raise ValueError("Repository, ref and lock enrollment must use supported safe addresses.")
        if bool(self.auth_namespace) != bool(self.deployment_object_id):
            raise ValueError("Namespaced execution requires both auth_namespace and deployment_object_id.")
        if self.deployment_object_id is not None and not self.deployment_object_id.int:
            raise ValueError("A concrete deployment principal object ID is required.")
        if self.runner is not None:
            if not self.auth_namespace:
                raise ValueError("An explicit runner requires a namespaced scoped binding, not a legacy pipeline.")
            if ((isinstance(self.runner, GitHubSelfHostedRunner) and self.orchestrator != "gha")
                    or (isinstance(self.runner, AdoSelfHostedRunner) and self.orchestrator != "ado")):
                raise ValueError("Self-hosted runner selection must match the binding orchestrator.")
        for target in self.targets:
            if target.execution is None:
                continue
            if not self.shared_remote:
                raise ValueError("Per-target execution overrides require a namespaced shared remote.")
            runner = target.execution.runner
            if ((isinstance(runner, GitHubSelfHostedRunner) and self.orchestrator != "gha")
                    or (isinstance(runner, AdoSelfHostedRunner) and self.orchestrator != "ado")):
                raise ValueError("Per-target runner selection must match the binding orchestrator.")
        if len({target.scale_set_id for target in self.targets}) != len(self.targets):
            raise ValueError("Each scale set requires exactly one binding target.")
        return self


class CatalogBindingState(ClosedModel):
    orchestrator: Route
    configuration: RuntimeBinding | None = None
    error: str | None = None
    verified: Literal[False] = False


class CatalogCommonSubnets(ClosedModel):
    common: str
    scoring: str
    powerbi: str
    bastion: str


class CatalogNetwork(ClosedModel):
    vnet_cidr: str = Field(min_length=9, max_length=32)
    max_projects: int = Field(default=1, strict=True, ge=1, le=8)
    common_subnets: CatalogCommonSubnets | None = None


class CatalogScaleSetInput(ClosedModel):
    environment: Environment
    suffix: str = Field(pattern=r"^[0-9]{3}$")
    subscription_id: UUID
    tenant_id: UUID
    orchestrator: Route
    network: CatalogNetwork

    @model_validator(mode="after")
    def concrete_identity(self):
        if not self.subscription_id.int or not self.tenant_id.int:
            raise ValueError("A concrete nonzero tenant and subscription UUID are required.")
        return self


class CatalogScaleSet(CatalogScaleSetInput):
    id: UUID
    status: Literal["draft", "configured"] = "draft"
    owned_resource_ids: list[str] = Field(default_factory=list)


class CatalogPlacement(ClosedModel):
    environment: Environment
    scale_set_id: UUID


class CatalogProjectInput(ClosedModel):
    number: str = Field(pattern=r"^[0-9]{3}$")
    display_name: str = Field(strict=True, min_length=1, max_length=128, pattern=r"\S")
    placements: list[CatalogPlacement] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def nonzero_number(self):
        if self.number == "000":
            raise ValueError("New project numbers must be between 001 and 999.")
        if (any(ord(character) < 32 for character in self.display_name)
                or "$(" in self.display_name or "${{" in self.display_name):
            raise ValueError("Project display name must be literal single-line text.")
        if len({placement.environment for placement in self.placements}) != len(self.placements):
            raise ValueError("A logical project requires at most one placement per environment.")
        return self


class CatalogProject(ClosedModel):
    id: UUID
    key: str
    number: str = Field(pattern=r"^[0-9]{3}$")
    display_name: str
    status: Literal["draft", "configured"] = "draft"
    placements: list[CatalogPlacement] = Field(default_factory=list)


class CatalogFactory(ClosedModel):
    id: UUID
    key: str
    prefix: str = Field(pattern=r"^[a-z][a-z0-9-]{1,19}$")
    region: str
    default_orchestrator: Route
    status: Literal["draft", "configured"] = "draft"
    aifactory_version: str | None = None
    version_ref: str | None = Field(
        default=None, json_schema_extra={"readOnly": True},
        description="Normalized saved factory version, persisted alongside aifactory_version; null for unknown legacy.")
    scale_sets: list[CatalogScaleSet] = Field(default_factory=list)
    projects: list[CatalogProject] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalized_version_alias(self):
        expected = release_version.normalize(self.aifactory_version) if self.aifactory_version is not None else None
        if self.version_ref is not None and self.version_ref != expected:
            raise ValueError("version_ref must match the normalized saved factory version.")
        self.version_ref = expected
        return self

    @field_validator("aifactory_version")
    @classmethod
    def valid_saved_version(cls, value):
        if value is not None:
            try:
                release_version.normalize(value)
            except TicketError as error:
                raise ValueError(str(error)) from None
        return value


class CatalogFactorySummary(CatalogFactory):
    bindings: list[CatalogBindingState] = Field(default_factory=list)


class CatalogSummary(ClosedModel):
    contract_version: Literal[1] = 1
    mode: Literal["legacy", "catalog"]
    revision: str
    factories: list[CatalogFactorySummary]
    warnings: list[str] = Field(default_factory=list)
    requires_selection: bool


class CatalogPrepare(ClosedModel):
    folder: str = Field(min_length=1, max_length=1024)
    contract_version: Literal[1]
    action: Action
    factory_id: UUID | None = None
    scale_set_id: UUID | None = None
    target_prefix: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,19}$")
    target_region: str | None = Field(default=None, min_length=2, max_length=50)
    include_projects: Literal["none", "all"] = "none"
    scale_sets: list[CatalogScaleSetInput] = Field(default_factory=list, max_length=24)
    version_ref: str | None = Field(
        default=None, min_length=1, max_length=100,
        description="Runtime selection, create/clone saved-version alias, or matching parent-version assertion for a new scale set.")
    aifactory_version: str | None = Field(default=None, strict=True, min_length=1, max_length=100)
    project_id: UUID | None = None
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    binding: RuntimeBinding | None = None
    project: CatalogProjectInput | None = None
    placements: list[CatalogPlacement] = Field(default_factory=list, max_length=3)
    settings: dict[str, str | bool | int | float | None] | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_version(cls, value):
        if isinstance(value, dict) and type(value.get("contract_version")) is not int:
            raise ValueError("contract_version must be the integer 1.")
        return value

    @model_validator(mode="after")
    def action_fields(self):
        if self.aifactory_version is not None:
            if self.action not in ("create-factory", "clone"):
                raise ValueError("A saved factory version can only be selected when creating or cloning a factory.")
            try:
                release_version.normalize(self.aifactory_version)
            except TicketError as error:
                raise ValueError(str(error)) from None
        if self.version_ref is not None and self.action in ("create-factory", "clone", "create-scale-set"):
            try:
                normalized = release_version.normalize(self.version_ref)
                if self.aifactory_version is not None and release_version.normalize(self.aifactory_version) != normalized:
                    raise ValueError("aifactory_version and version_ref must select the same code version.")
            except TicketError as error:
                raise ValueError(str(error)) from None
        if self.action not in ("migrate", "create-factory") and self.factory_id is None:
            raise ValueError("An explicit factory_id is required.")
        if self.action == "create-factory" and (self.factory_id or not self.target_prefix or not self.target_region):
            raise ValueError("New factories require a prefix and region, not an existing factory_id.")
        if self.action == "migrate" and any((self.factory_id, self.scale_set_id, self.project_id, self.version_ref,
                                            self.target_prefix, self.target_region)):
            raise ValueError("Migration preserves existing identity and does not accept runtime selectors or overrides.")
        if self.action in ("deploy", "delete-scale-set") and self.scale_set_id is None:
            raise ValueError("An explicit scale_set_id is required.")
        if self.action == "clone" and not (self.target_prefix or self.target_region):
            raise ValueError("Clone requires a new prefix and/or region.")
        if self.action in ("create-factory", "create-scale-set") and not self.scale_sets:
            raise ValueError("At least one explicit environment, suffix and subscription is required.")
        if self.action in ("create-factory", "create-scale-set") and any(scale.suffix == "000" for scale in self.scale_sets):
            raise ValueError("New scale-set suffix must be between 001 and 999.")
        if self.action != "clone" and self.include_projects != "none":
            raise ValueError("include_projects is only supported for clone; migration always preserves existing definitions.")
        if self.action not in ("clone", "migrate", "create-factory") and (self.target_prefix or self.target_region):
            raise ValueError("This action cannot change factory identity.")
        if self.action not in ("create-factory", "create-scale-set") and self.scale_sets:
            raise ValueError("Explicit new scale sets require create-factory or create-scale-set.")
        if self.action not in ("create-factory", "clone", "create-scale-set", "deploy", "delete-factory", "delete-scale-set") and self.version_ref:
            raise ValueError("This action does not accept a code-version selection.")
        if self.action not in ("deploy", "add-project-placements", "configure-settings") and self.project_id:
            raise ValueError("project_id only applies to deployment or adding explicit project placements.")
        if self.action not in ("deploy", "delete-scale-set", "clone", "configure-settings") and self.scale_set_id:
            raise ValueError("This action does not accept a scale-set selector.")
        if (self.action == "configure-binding") != (self.binding is not None):
            raise ValueError("A typed binding is required only for configure-binding.")
        if (self.action == "add-project") != (self.project is not None):
            raise ValueError("A typed new project definition is required only for add-project.")
        if (self.action == "configure-settings") != (self.settings is not None):
            raise ValueError("Only configure-settings accepts scoped configuration values.")
        if self.settings is not None:
            from src.catalog_settings import editable_keys
            if not self.settings or set(self.settings) - set(editable_keys()):
                raise ValueError("Only listed non-secret settings can be reviewed; immutable identity and credential fields are forbidden.")
        if self.action == "add-project-placements":
            if not self.project_id or not self.placements:
                raise ValueError("An exact project_id and explicit placements are required.")
            if len({placement.environment for placement in self.placements}) != len(self.placements):
                raise ValueError("Provide at most one added placement per environment.")
        elif self.placements:
            raise ValueError("Top-level placements are only accepted by add-project-placements.")
        return self


class CatalogConfirm(ClosedModel):
    folder: str = Field(min_length=1, max_length=1024)
    contract_version: Literal[1]
    confirmation_id: UUID

    @model_validator(mode="before")
    @classmethod
    def explicit_version(cls, value):
        if isinstance(value, dict) and type(value.get("contract_version")) is not int:
            raise ValueError("contract_version must be the integer 1.")
        return value


class CatalogInventoryItem(ClosedModel):
    resource_id: str
    dependencies: list[str] = Field(default_factory=list)


class CatalogSourceVersion(ClosedModel):
    aifactory_version: str | None = Field(default=None, exclude_if=lambda value: value is None)
    requested_version: str
    branch: str
    resolved_ref: str


class CatalogPreview(ClosedModel):
    contract_version: Literal[1] = 1
    confirmation_id: UUID
    can_execute: bool
    summary: str
    effects: list[str]
    warnings: list[str]
    blockers: list[str]
    expires_at: str
    source_revision: str
    operation_mode: Literal["configuration", "runtime"]
    target: CatalogFactory | None
    inventory: list[CatalogInventoryItem] = Field(default_factory=list)
    source_version: CatalogSourceVersion | None = None
    binding: RuntimeBinding | None = None


class CatalogJob(ClosedModel):
    id: UUID
    action: Action
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    message: str
    factory_id: UUID
    scale_set_id: UUID | None = None
    created_at: str
    updated_at: str
    exit_code: int | None = None
    terminal_available: bool = False
    source_version: CatalogSourceVersion | None = None


class CatalogConfirmed(ClosedModel):
    contract_version: Literal[1] = 1
    catalog: CatalogSummary | None = None
    job: CatalogJob | None = None


class CatalogJobs(ClosedModel):
    contract_version: Literal[1] = 1
    jobs: list[CatalogJob]


class CatalogSettings(ClosedModel):
    contract_version: Literal[1] = 1
    revision: str
    factory_id: UUID
    scale_set_id: UUID | None = None
    project_id: UUID | None = None
    state: dict[str, str | bool | int | float | None]
    field_keys: list[str]
    message: str
