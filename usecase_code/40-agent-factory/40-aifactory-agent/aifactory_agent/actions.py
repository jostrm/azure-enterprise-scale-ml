"""Backend-only, receipt-bound adapters for the existing AzureFactory SDK."""

from __future__ import annotations

import copy
import ipaddress
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from azurefactory.client import canonical_json_hash, redact_secrets, validate_base_url
from azurefactory.errors import BlockedError, ConfigError, FailureError
from azurefactory.factory_deletion import validate_deletion_preview, validate_job
from azurefactory.review import validate_bindings
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CREATE = "create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj"
DELETE = "delete-aifactory"
ADD_PROJECT = "add-project-to-aifactory"
ACTION_SKILLS = (CREATE, DELETE, ADD_PROJECT)
SkillName = Literal[
    "create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj",
    "delete-aifactory", "add-project-to-aifactory",
]
RG_PATTERN = r"^/subscriptions/[a-f0-9-]{36}/resourceGroups/[A-Za-z0-9_().-]{1,90}$"
ID_PATTERN = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class NoArguments(Closed):
    pass


class ProjectArguments(Closed):
    project_number: str = Field(pattern=r"^(?:00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})$")
    display_name: str = Field(min_length=1, max_length=128)

    @field_validator("display_name")
    @classmethod
    def literal_name(cls, value):
        if (value != value.strip() or any(unicodedata.category(c) in ("Cc", "Cs", "Zl", "Zp") for c in value)
                or any(marker in value for marker in ("$(", "${", "{{", "}}"))):
            raise ValueError("Project display name must be literal single-line text.")
        return value


class BootstrapConfig(Closed):
    """An intentionally closed subset of WorkflowBootstrapConfig, never model input."""

    subscription_id: str = Field(pattern=ID_PATTERN)
    tenant_id: str = Field(pattern=ID_PATTERN)
    location: str = Field(pattern=r"^[a-z][a-z0-9]{1,39}$")
    factory_prefix: str = Field(pattern=r"^[a-z][a-z0-9-]{1,10}-$")
    scale_set_number: str = Field(pattern=r"^(?:00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})$")
    project_number: Literal["001"] = "001"
    repo_root: str = Field(min_length=1, max_length=240)
    aifactory_version: str = Field(default="main", pattern=r"^(?:main|[0-9]{3})$")
    coordination_mode: Literal["blob"] = "blob"
    github_repository: str = Field(default="", max_length=140)
    github_visibility: Literal["private"] = "private"
    ado_organization: str = Field(default="", max_length=200)
    ado_project: str = Field(default="", max_length=120)
    ado_repository: str = Field(default="", max_length=120)
    ado_service_connection: str = Field(default="", max_length=120)
    ado_tenant_id: str = Field(default="", pattern=r"^(?:[a-f0-9-]{36})?$")
    identity_mode: Literal["create", "existing"] = "create"
    managed_identity_resource_id: str = Field(default="", max_length=512)
    team_group_id: str = Field(default="", pattern=r"^(?:[a-f0-9-]{36})?$")
    team_member_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    team_group_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
    cost_center: str = Field(default="123456", pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
    runner_mode: Literal["self-hosted"] = "self-hosted"
    runner_vm_name: str = Field(default="", pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63})?$")
    runner_vm_resource_group: str = Field(default="", pattern=r"^(?:[A-Za-z0-9_().-]{1,90})?$")
    admin_vm_size: str = Field(default="", pattern=r"^(?:Standard_[A-Za-z0-9_]+)?$")
    ado_agent_pool: str = Field(default="", max_length=120)
    ado_agent_name: str = Field(default="", max_length=100)
    gha_runner_name: str = Field(default="", pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,99})?$")
    gha_runner_label: str = Field(default="", pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,99})?$")
    dev_vnet_cidr: str
    vpn_client_cidr: str
    access_hub_mode: Literal["integrated"] = "integrated"
    access_hub_lock_resource_group: str = Field(pattern=r"^[A-Za-z0-9_().-]{1,90}$")
    setup_hub_access: Literal[True] = True
    bootstrap_public_ipv4: str

    @model_validator(mode="after")
    def exact_network_and_provider(self):
        spoke = ipaddress.IPv4Network(self.dev_vnet_cidr, strict=True)
        pool = ipaddress.IPv4Network(self.vpn_client_cidr, strict=True)
        address = ipaddress.IPv4Address(self.bootstrap_public_ipv4)
        if (str(spoke) != self.dev_vnet_cidr or str(pool) != self.vpn_client_cidr or spoke.overlaps(pool)
                or spoke.prefixlen > 18 or not address.is_global or address.is_multicast or address.is_reserved):
            raise ValueError("Supply explicit canonical, nonoverlapping VPN/VNet pools and an approved public bootstrap IPv4.")
        if bool(self.runner_vm_name) != bool(self.runner_vm_resource_group):
            raise ValueError("Supply both runner VM name and resource group.")
        ado = (self.ado_organization, self.ado_project, self.ado_repository, self.ado_service_connection, self.ado_tenant_id)
        if self.github_repository:
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", self.github_repository)
                    or self.github_repository.endswith(".git")
                    or any((*ado, self.ado_agent_name, self.ado_agent_pool))):
                raise ValueError("Select one exact GHA repository without ADO settings.")
        elif (not all(ado) or not re.fullmatch(r"https://dev\.azure\.com/[A-Za-z0-9][A-Za-z0-9-]*", self.ado_organization)
              or any((self.gha_runner_name, self.gha_runner_label))):
            raise ValueError("Select one exact ADO organization/project/repository/connection and tenant.")
        if (self.identity_mode == "existing") != bool(self.managed_identity_resource_id):
            raise ValueError("Existing identity requires an exact managed identity resource ID.")
        if redact_secrets(self.model_dump(mode="json"), None) != self.model_dump(mode="json"):
            raise ValueError("Bootstrap profiles cannot contain credentials.")
        return self


class SourceDefinition(Closed):
    url: str
    ref: str = Field(min_length=1, max_length=100)
    sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    verification: Literal["published-remote-ref"] = "published-remote-ref"
    assets: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def pinned_source(self):
        parsed = urlsplit(self.url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or "\\" in self.url):
            raise ValueError("Source URL must be HTTPS without credentials.")
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", path)
               or any(part in (".", "..") for part in path.split("/"))
               or not re.fullmatch(r"[a-f0-9]{40}", fingerprint)
               for path, fingerprint in self.assets.items()):
            raise ValueError("Source assets require exact safe paths and Git blob fingerprints.")
        return self


class BootstrapProfile(Closed):
    bootstrap_config: BootstrapConfig
    source: SourceDefinition
    program_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    workflow_input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    resource_groups: list[str] = Field(min_length=3)
    deployment_identity_id: str
    repository_environments: list[str] = Field(default_factory=list)
    auth_namespace: str | None = None
    authorization_valid_for_seconds: int = Field(default=14400, ge=60, le=86400)

    @model_validator(mode="after")
    def concrete_bounds(self):
        config = self.bootstrap_config
        subscription = "/subscriptions/" + config.subscription_id
        if (len({group.lower() for group in self.resource_groups}) != len(self.resource_groups)
                or any(not re.fullmatch(RG_PATTERN, group) or group.endswith(".")
                       or not group.startswith(subscription + "/resourceGroups/") for group in self.resource_groups)
                or subscription + "/resourceGroups/" + config.access_hub_lock_resource_group not in self.resource_groups):
            raise ValueError("Approve distinct explicit resource-group IDs including this factory's own hub.")
        identity_pattern = RG_PATTERN[:-1] + r"/providers/Microsoft\.ManagedIdentity/userAssignedIdentities/[A-Za-z0-9_-]+$"
        if (not re.fullmatch(identity_pattern, self.deployment_identity_id)
                or self.deployment_identity_id.split("/providers/", 1)[0] not in self.resource_groups
                or config.identity_mode == "existing" and config.managed_identity_resource_id != self.deployment_identity_id):
            raise ValueError("Approve the exact deployment identity inside the approved resource groups.")
        if (len(set(self.repository_environments)) != len(self.repository_environments)
                or any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name) for name in self.repository_environments)):
            raise ValueError("Repository environment names must be explicit and distinct.")
        if config.github_repository:
            if self.auth_namespace not in self.repository_environments:
                raise ValueError("GHA requires explicit approved environments and authentication namespace.")
        elif self.repository_environments or self.auth_namespace is not None:
            raise ValueError("ADO must not authorize GitHub environments.")
        return self


class ActionSettings(Closed):
    enabled_skills: list[SkillName] = Field(default_factory=list)
    bootstrap_profiles: dict[str, BootstrapProfile] = Field(default_factory=dict)
    deletion_resource_groups: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def closed_scopes(self):
        keys = set(self.bootstrap_profiles) | set(self.deletion_resource_groups)
        if (len(set(self.enabled_skills)) != len(self.enabled_skills)
                or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) for key in keys)):
            raise ValueError("Skills and scope keys must be explicit and distinct.")
        for groups in self.deletion_resource_groups.values():
            if (not groups or len(set(group.lower() for group in groups)) != len(groups)
                    or any(not re.fullmatch(RG_PATTERN, group) or group.endswith(".") for group in groups)):
                raise ValueError("Deletion requires distinct exact approved resource-group ARM IDs.")
        return self


def _error(code, message, status=409):
    from .tools import ToolError
    raise ToolError(code, message, status)


def _authorize(settings, principal, scope_key, permission):
    from .security import authorize
    return authorize(settings, principal, scope_key, permission)


def required_permission(skill_name):
    try:
        return {CREATE: "factory.create", DELETE: "factory.delete", ADD_PROJECT: "project.add"}[skill_name]
    except (KeyError, TypeError):
        _error("unsupported_operation", "This action is not in the backend allowlist.", 400)


def argument_model(skill_name):
    required_permission(skill_name)
    return ProjectArguments if skill_name == ADD_PROJECT else NoArguments


def _refs(settings, scope_key):
    from .tools import _uuid
    if scope_key not in settings.scopes or not settings.factory.folder:
        _error("factory_target_unconfigured", "Configure an exact Factory folder and scope.", 503)
    for key in ("factory_id", "scale_set_id", "project_id"):
        if getattr(settings.factory, key) is None:
            _error("factory_target_unconfigured", "Configure exact factory, scale-set and project UUIDs.", 503)
        _uuid(str(getattr(settings.factory, key)))
    return settings.factory, settings.scopes[scope_key]


def _profile(settings, scope_key):
    refs, scope = _refs(settings, scope_key)
    profile = settings.actions.bootstrap_profiles.get(scope_key)
    if profile is None:
        _error("bootstrap_profile_required", "A server-approved full private bootstrap profile is required for this scope.", 503)
    config = profile.bootstrap_config
    if (scope.environment != "dev" or scope.project != "001"
            or config.subscription_id != str(scope.subscription_id) or config.tenant_id != str(scope.tenant_id)
            or config.factory_prefix != scope.factory.rstrip("-") + "-"
            or config.location != settings.location
            or f"/subscriptions/{scope.subscription_id}/resourceGroups/{scope.resource_group}" not in profile.resource_groups):
        _error("bootstrap_scope_mismatch", "The approved bootstrap profile must match this Dev/default-project scope and region.", 403)
    return profile


def _workflow_request(settings, scope_key, revision):
    refs, _ = _refs(settings, scope_key)
    profile = _profile(settings, scope_key)
    return {
        "contract_version": 1, "operation": "create-factory", "execution_mode": "privileged-bootstrap",
        "creation_mode": "full-bootstrap",
        "scope": {"folder": refs.folder, **{key: str(getattr(refs, key)) for key in ("factory_id", "scale_set_id", "project_id")}},
        "expected_revision": revision, "bootstrap_config": profile.bootstrap_config.model_dump(mode="json"),
        "approval_mode": "whole-workflow", "authorization_valid_for_seconds": profile.authorization_valid_for_seconds,
    }


_STAGE_EFFECTS = {
    "hub-lock-foundation": "Create/reuse the exact coordination storage, container, writer roles and reviewed bootstrap IP rule; no lease breaking.",
    "repository-initialization": "Create/reuse the selected provider repository, pin accelerator commit, install scoped lifecycle assets and reserve the initializer ref.",
    "minimum-foundation": "Create/reuse selected common/project resource groups, common VNet, seeding vault and deployment managed identity.",
    "prerequisites": "Register required resource providers, create/reuse selected Entra group and first-party principals, scoped RBAC and selected access-hub resources; save verified generated references.",
    "network-foundation": "Create missing canonical subnets/NSGs within the selected VNet; preserve existing networks, DNS and peerings; save the preservation profile.",
    "runner": "Create/reuse the selected self-hosted runner VM, identity, disk and network attachments; register only the selected provider runner.",
    "connection": "Enroll the selected identity/runner with scoped deployment roles and repository authentication; save the verified catalog binding.",
    "provider-handoff": "Verify GitHub Actions policy or authorize only the selected ADO pipeline endpoint/queue.",
    "publication": "Commit/push only canonical generated catalog/enrollment files to the selected repository main branch; exclude unrelated/staged/private files.",
    "private-probe": "Verify the actual private runner path before common workload deployment.",
    "common-deployment": "Deploy selected common workloads from pinned templates under the zero-write network preservation guard.",
    "project-deployment": "Deploy ALL saved selected initial-project workloads from pinned templates; no project/resource selection is removed.",
    "private-transition": "Verify private connectivity then disable public access on the exact coordination account.",
    "complete": "Release only this workflow's provider initializer reservation after every selected stage verifies completion.",
}
_ENV_CONSTRAINTS = [
    "Only these exact names in this repository; create missing environments through create-or-return.",
    "Preserve existing permissions, reviewers, protection rules and deployment branch policies; no reset, rename or deletion.",
    "Preserve existing custom or hashed authentication bindings; no automatic namespace migration.",
    "Environment creation authorizes no additional factory, subscription, scale-set or project deployment, including Stage or Prod.",
]
_ALLOWED_CHANGES = ["verified generated settings", "verified network preservation profile",
                    "verified enrollment binding", "canonical generated publication files"]
_HALT_POLICY = "Stop on drift, expanded scope, unknown stage, expiry, blocked/failed/uncertain result or interrupted writer. Never retry or repair automatically."


def _validate_workflow(settings, scope_key, request, preview):
    from .tools import _deadline, _revision, _uuid
    profile = _profile(settings, scope_key)
    if request != _workflow_request(settings, scope_key, _revision(request.get("expected_revision"))):
        _error("invalid_plan", "Bootstrap inputs differ from the server-approved profile.")
    if preview.get("scope") != request["scope"] or preview.get("source_revision") != request["expected_revision"]:
        _error("invalid_plan", "The bootstrap receipt changed its exact scope or revision.")
    _uuid(preview.get("workflow_id"))
    _revision(preview.get("input_hash"))
    review = preview.get("review")
    authorization = review.get("workflow_authorization") if isinstance(review, dict) else None
    fields = {"contract", "authorization_id", "workflow_id", "approval_mode", "scope", "input_hash",
              "source_revision", "target", "program_fingerprint", "source", "template_fingerprint",
              "repository", "branch", "repository_environments", "coordination_mode", "governance_warnings",
              "stages", "expires_at", "allowed_changes", "halt_policy", "authorization_hash"}
    if (not isinstance(authorization, dict) or set(authorization) != fields
            or authorization["contract"] != "bounded-full-bootstrap-v1"
            or authorization["approval_mode"] != "whole-workflow"
            or authorization["workflow_id"] != preview["workflow_id"] or authorization["scope"] != request["scope"]
            or authorization["source_revision"] != request["expected_revision"]
            or authorization["input_hash"] != profile.workflow_input_hash
            or authorization["source"] != profile.source.model_dump(mode="json")
            or authorization["program_fingerprint"] != profile.program_fingerprint
            or authorization["template_fingerprint"] != canonical_json_hash(authorization["source"])
            or authorization["coordination_mode"] != "blob" or authorization["branch"] != "main"
            or authorization["allowed_changes"] != _ALLOWED_CHANGES or authorization["halt_policy"] != _HALT_POLICY
            or authorization["authorization_hash"] != canonical_json_hash(
                {key: value for key, value in authorization.items() if key != "authorization_hash"})):
        _error("unsupported_factory_contract", "A pinned, bounded full-bootstrap authorization is required; expanded contracts are refused.", 503)
    _uuid(authorization["authorization_id"])
    if _deadline(authorization["expires_at"]) <= datetime.now(timezone.utc):
        _error("plan_expired", "The full-workflow authorization expired.")
    config = profile.bootstrap_config
    target = {
        "tenant_id": config.tenant_id, "subscription_id": config.subscription_id, "location": config.location,
        "resource_groups": profile.resource_groups, "deployment_identity_id": profile.deployment_identity_id,
        "vnet_cidr": config.dev_vnet_cidr,
        "subscription_operations": ["required resource-provider registration", "deployment records",
                                    "narrow deployment-record custom role definition/assignment"],
        "directory_operations": "Only configured team group/members and selected first-party service principals",
        "role_definition_ids": ["b24988ac-6180-42a0-ab88-20f7382dd24c", "f58310d9-a9f6-439a-9e8d-f62e7b41a168"],
    }
    if authorization["target"] != target:
        _error("cross_scope_write", "Bootstrap resource groups, identity, region or network expanded beyond the approved profile.", 403)
    repository = ("https://github.com/" + config.github_repository if config.github_repository else
                  config.ado_organization + "/" + config.ado_project + "/_git/" + config.ado_repository)
    if authorization["repository"] != repository:
        _error("cross_scope_write", "The workflow selected a different repository.", 403)
    effects = dict(_STAGE_EFFECTS)
    environments = authorization["repository_environments"]
    if config.github_repository:
        if (not isinstance(environments, dict)
                or set(environments) != {"repository", "auth_namespace", "environments", "constraints"}
                or environments["repository"] != repository or environments["auth_namespace"] != profile.auth_namespace
                or environments["constraints"] != _ENV_CONSTRAINTS or not isinstance(environments["environments"], list)):
            _error("invalid_plan", "The workflow must preserve the approved repository authentication environment bounds.")
        entries = environments["environments"]
        if ([entry.get("name") for entry in entries if isinstance(entry, dict)] != sorted(profile.repository_environments)
                or any(set(entry) != {"name", "action", "observed_snapshot_sha256"}
                       or entry["action"] not in ("create-if-missing", "reuse-unchanged")
                       or not re.fullmatch(r"[a-f0-9]{64}", str(entry["observed_snapshot_sha256"])) for entry in entries)):
            _error("cross_scope_write", "Repository environments expanded or lost exact observation fingerprints.", 403)
        effects["repository-initialization"] += (
            " GitHub environments: " + ", ".join(item["name"] + " (" + item["action"] + ")" for item in entries)
            + ". Selected deployment authentication namespace: " + environments["auth_namespace"] + ". "
            + " ".join(environments["constraints"]))
    elif environments is not None:
        _error("cross_scope_write", "GitHub environment creation cannot be authorized for ADO.", 403)
    stages = [{"stage": stage, "effects": effect} for stage, effect in effects.items()]
    if authorization["stages"] != stages or preview.get("stage") != stages[0]["stage"]:
        _error("invalid_plan", "Bootstrap omitted, reordered or expanded a required private full-workflow stage.")
    if not isinstance(authorization["governance_warnings"], list) or any(
            not isinstance(item, str) for item in authorization["governance_warnings"]):
        _error("invalid_plan", "The authorization omitted governance warnings.")
    try:
        validate_bindings(request, preview, "creation-workflow-start", "creation-workflow")
    except (ConfigError, BlockedError, FailureError):
        _error("unsupported_factory_contract", "The SDK rejected the registered bootstrap receipt.", 503)


def _factory_scope(settings, scope_key, factory, *, whole=False):
    from .tools import _select_scope
    refs, scope = _refs(settings, scope_key)
    _select_scope(settings, scope_key, {"factories": [factory]}, single_placement=not whole)
    if whole:
        if any(scale.get("id") != str(refs.scale_set_id)
               or scale.get("tenant_id") != str(scope.tenant_id)
               or scale.get("subscription_id") != str(scope.subscription_id)
               or scale.get("environment") != scope.environment for scale in factory["scale_sets"]):
            _error("cross_scope_write", "Whole-factory deletion may not broaden the configured scale/environment/tenant/subscription.", 403)


def _validate_project(settings, scope_key, request, preview):
    from .tools import _uuid
    refs, scope = _refs(settings, scope_key)
    project = request.get("project")
    if not isinstance(project, dict) or set(project) != {"number", "display_name", "placements"}:
        _error("invalid_plan", "Only a literal project definition and the selected placement are supported.")
    ProjectArguments(project_number=project["number"], display_name=project["display_name"])
    expected = {
        "folder": refs.folder, "contract_version": 1, "action": "add-project", "factory_id": str(refs.factory_id),
        "expected_revision": request.get("expected_revision"),
        "project": {"number": scope.project, "display_name": project["display_name"],
                    "placements": [{"environment": scope.environment, "scale_set_id": str(refs.scale_set_id)}]},
    }
    if request != expected or project["number"] != scope.project:
        _error("cross_scope_write", "The new project must match the exact granted project number and server-selected placement.", 403)
    if (preview.get("factory_id") != str(refs.factory_id) or preview.get("scale_set_id") != str(refs.scale_set_id)
            or preview.get("operation_mode") != "configuration"
            or preview.get("source_revision") != request["expected_revision"]
            or preview.get("action") not in (None, "add-project")
            or any(preview.get(key) not in (None, []) for key in ("deletion_targets", "inventory", "retained_resources"))
            or any(preview.get(key) is not None for key in ("binding", "deletion_options", "migration_receipt", "execution_policy"))):
        _error("unsupported_factory_contract", "Project add must be a configuration-only catalog action, never deployment.", 503)
    target = preview.get("target")
    if not isinstance(target, dict) or target.get("id") != str(refs.factory_id) or target.get("prefix") != scope.factory:
        _error("cross_scope_write", "The project preview selected a different factory.", 403)
    scales = [item for item in target.get("scale_sets", []) if item.get("id") == str(refs.scale_set_id)]
    if (len(scales) != 1 or any(scales[0].get(key) != value for key, value in
                              (("tenant_id", str(scope.tenant_id)), ("subscription_id", str(scope.subscription_id)),
                               ("environment", scope.environment)))):
        _error("cross_scope_write", "The project preview selected a different scale set.", 403)
    projects = [item for item in target.get("projects", []) if item.get("number") == scope.project]
    if (len(projects) != 1 or projects[0].get("id") != preview.get("project_id")
            or projects[0].get("display_name") != project["display_name"]
            or _placements(projects[0].get("placements")) != project["placements"]):
        _error("cross_scope_write", "The preview must identify exactly one newly reviewed project and placement.", 403)
    _uuid(preview.get("project_id"))


def _validate_delete(settings, scope_key, request, preview):
    refs, scope = _refs(settings, scope_key)
    if request != {"contract_version": 1, "folder": refs.folder, "factory_id": str(refs.factory_id),
                   "expected_revision": request.get("expected_revision")}:
        _error("invalid_plan", "Deletion must select only the exact server-configured whole factory.")
    try:
        validate_deletion_preview(request, preview)
    except (ConfigError, BlockedError, FailureError):
        _error("unsupported_factory_contract", "The SDK rejected the whole-factory deletion manifest or preservation contract.", 503)
    _factory_scope(settings, scope_key, preview["target"], whole=True)
    approved = settings.actions.deletion_resource_groups.get(scope_key)
    if not approved:
        _error("deletion_scope_required", "An administrator must approve the complete deletion resource-group list for this scope.", 503)
    if (any(not group.startswith(f"/subscriptions/{scope.subscription_id}/resourceGroups/") for group in approved)
            or {group.lower() for group in approved} != {item["resource_id"].lower() for item in preview["deletion_targets"]}):
        _error("cross_scope_write", "The whole-factory deletion resource-group manifest differs from the server-approved breadth.", 403)
    inventory = {item["resource_id"].lower(): item for item in preview["inventory"]}
    for identifier, item in inventory.items():
        dependencies = item.get("dependencies")
        if (not isinstance(dependencies, list) or len(set(dependencies)) != len(dependencies)
                or any(not isinstance(dep, str) or dep.lower() not in inventory for dep in dependencies)):
            _error("invalid_plan", "Deletion requires an exact closed dependency inventory.")
        if re.search(r"/providers/microsoft\.search/services/[^/]+$", identifier):
            links = {child for child in inventory if child.startswith(identifier + "/sharedprivatelinkresources/")}
            if not links <= {dep.lower() for dep in dependencies}:
                _error("unsafe_deletion_order", "All Search shared private links must be deleted before their Search service.")
    remaining = {key: {dep.lower() for dep in item["dependencies"]} for key, item in inventory.items()}
    while remaining:
        ready = {key for key, dependencies in remaining.items() if not dependencies}
        if not ready:
            _error("unsafe_deletion_order", "Deletion dependency inventory contains a cycle.")
        remaining = {key: dependencies - ready for key, dependencies in remaining.items() if key not in ready}


def validate_action_plan(settings, scope_key, tool_name, request, preview):
    from .tools import _deadline, _revision, _uuid
    required_permission(tool_name)
    if tool_name not in settings.actions.enabled_skills:
        _error("action_disabled", "This Factory action is disabled on the server.", 503)
    _refs(settings, scope_key)
    if not isinstance(request, dict) or not isinstance(preview, dict):
        _error("invalid_plan", "Reviewed request and preview must be JSON objects.")
    if (type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or type(preview.get("contract_version")) is not int or preview["contract_version"] != 1
            or preview.get("can_execute") is not True or preview.get("blockers") != []):
        _error("unsupported_factory_contract", "An executable, unblocked contract-1 Factory review is required.", 503)
    _revision(request.get("expected_revision"))
    _uuid(preview.get("confirmation_id"))
    _deadline(preview.get("expires_at"))
    if any(not isinstance(preview.get(key), list) or any(not isinstance(item, str) for item in preview[key])
           for key in ("effects", "warnings")):
        _error("unsupported_factory_contract", "The exact effects and warnings must be reviewed.", 503)
    {CREATE: _validate_workflow, DELETE: _validate_delete, ADD_PROJECT: _validate_project}[tool_name](
        settings, scope_key, request, preview)


def _placements(value):
    if not isinstance(value, list) or any(
            not isinstance(item, dict) or set(item) - {"environment", "scale_set_id", "deployment_state", "deployment_detail"}
            or not {"environment", "scale_set_id"} <= item.keys() for item in value):
        _error("invalid_factory_contract", "The API returned unsupported project placement fields.", 502)
    return [{key: item[key] for key in ("environment", "scale_set_id")} for item in value]


def _target_review(target):
    return {
        **{key: target[key] for key in ("id", "key", "prefix", "region") if key in target},
        "scale_sets": [{key: item[key] for key in ("id", "environment", "tenant_id", "subscription_id")}
                       for item in target["scale_sets"]],
        "projects": [{**{key: item[key] for key in ("id", "number", "display_name")},
                      "placements": _placements(item.get("placements"))}
                     for item in target.get("projects", [])],
    }


def plan_details(settings, scope_key, tool_name, request, preview):
    validate_action_plan(settings, scope_key, tool_name, request, preview)
    keys = ("contract_version", "confirmation_id", "can_execute", "expires_at", "source_revision",
            "effects", "warnings", "blockers", "operation_mode", "factory_id", "scale_set_id", "project_id", "action")
    clean = {key: copy.deepcopy(preview[key]) for key in keys if key in preview}
    if tool_name == CREATE:
        clean.update({key: copy.deepcopy(preview[key]) for key in ("workflow_id", "scope", "stage", "input_hash")})
        clean["review"] = {"workflow_authorization": copy.deepcopy(preview["review"]["workflow_authorization"])}
        clean["summary"] = "Full private bootstrap: own integrated hub, P2S VPN, default project001 and private self-hosted runner."
        affected = [{"kind": "bootstrap-resource-group", "resource_id": group,
                     **request["scope"], "environment": settings.scopes[scope_key].environment}
                    for group in _profile(settings, scope_key).resource_groups]
    elif tool_name == DELETE:
        clean["target"] = _target_review(preview["target"])
        for key in ("capabilities", "folder", "deletion_scope", "preserve_entra_groups", "retain_saved_configuration",
                    "confirmation_phrase", "preview_hash", "source_version", "deletion_targets", "inventory", "retained_resources"):
            clean[key] = copy.deepcopy(preview[key])
        clean["summary"] = "Delete the exact approved whole-factory Azure inventory and saved catalog configuration; preserve Entra groups."
        affected = [{"kind": "delete-resource", **copy.deepcopy(item)} for item in preview["inventory"]]
        affected += [{"kind": "retain-resource", "resource_id": item} for item in preview["retained_resources"]]
    else:
        clean["target"] = _target_review(preview["target"])
        clean["summary"] = "Add one logical project and its draft settings only; no Azure resources are deployed."
        affected = [{"kind": "project-configuration", "factory_id": request["factory_id"],
                     "scale_set_id": str(settings.factory.scale_set_id), "project_id": preview["project_id"],
                     "project_number": request["project"]["number"], "environment": settings.scopes[scope_key].environment}]
    return redact_secrets(clean, None), redact_secrets(affected, None)


def validate_destructive_approval(record, confirmation_phrase):
    if record.get("tool_name") != DELETE:
        return
    preview = record.get("preview")
    if (not isinstance(preview, dict) or not isinstance(confirmation_phrase, str)
            or confirmation_phrase != preview.get("confirmation_phrase")
            or confirmation_phrase != "DELETE " + str(preview.get("target", {}).get("key"))
            or not re.fullmatch(r"[a-f0-9]{64}", str(preview.get("preview_hash")))):
        _error("confirmation_phrase_required", "Type the exact reviewed DELETE factory-key phrase to approve factory deletion.", 400)


class ActionSkills:
    def __init__(self, settings, principal, scope_key, client, operation_store):
        self.settings, self.principal, self.scope_key = settings, principal, scope_key
        self.client, self.operation_store = client, operation_store

    def _gate(self, skill_name):
        permission = required_permission(skill_name)
        scope = _authorize(self.settings, self.principal, self.scope_key, permission)
        if skill_name not in self.settings.actions.enabled_skills:
            _error("action_disabled", "This Factory action is disabled on the server.", 503)
        if not self.settings.factory.writes_enabled:
            _error("writes_disabled", "Factory writes are disabled.", 503)
        if scope.environment not in self.settings.factory.allowed_write_environments:
            _error("environment_not_enabled", "Writes are not enabled for this environment.", 403)
        _refs(self.settings, self.scope_key)

    def _method(self, name):
        method = getattr(self.client, name, None)
        if not callable(method):
            _error("unsupported_factory_sdk", "Update the AzureFactory SDK; required adapter is missing: " + name + ".", 503)
        return method

    def _schema(self, name, fields, *, action=None):
        document = self._method("openapi")()
        schema = document.get("components", {}).get("schemas", {}).get(name, {}) if isinstance(document, dict) else {}
        properties = schema.get("properties")
        if (schema.get("additionalProperties") is not False or not isinstance(properties, dict)
                or not fields <= properties.keys()
                or action and action not in properties.get("action", {}).get("enum", [])):
            _error("unsupported_factory_contract", "The running API lacks the closed " + name + " contract.", 503)

    def _catalog(self, *, allow_absent_project=False):
        from .tools import _revision
        refs, scope = _refs(self.settings, self.scope_key)
        catalog = self._method("catalog_list")(refs.folder)
        if not isinstance(catalog, dict) or type(catalog.get("contract_version")) is not int or catalog["contract_version"] != 1:
            _error("invalid_factory_contract", "The API must return a registered contract-1 catalog.", 502)
        _revision(catalog.get("revision"))
        matches = [item for item in catalog.get("factories", []) if isinstance(item, dict) and item.get("id") == str(refs.factory_id)]
        if len(matches) != 1:
            _error("saved_factory_required", "Save the exact registered schema-2 factory/scale/project configuration before bootstrap or project actions.", 503)
        factory = matches[0]
        if allow_absent_project:
            if factory.get("prefix") != scope.factory:
                _error("factory_scope_mismatch", "The factory is outside the exact scope.", 403)
            scales = [item for item in factory.get("scale_sets", []) if item.get("id") == str(refs.scale_set_id)]
            if (len(scales) != 1 or any(scales[0].get(key) != value for key, value in (
                    ("environment", scope.environment), ("subscription_id", str(scope.subscription_id)),
                    ("tenant_id", str(scope.tenant_id))))):
                _error("factory_scope_mismatch", "The selected scale set is outside the exact scope.", 403)
        else:
            _factory_scope(self.settings, self.scope_key, factory, whole=False)
        return catalog, factory

    def _secret_free(self, value):
        if redact_secrets(value, getattr(self.client, "api_key", None)) != value:
            _error("secret_in_plan", "Credentials cannot be persisted in action arguments or receipts.", 400)

    def prepare(self, skill_name, args):
        self._gate(skill_name)
        parsed = argument_model(skill_name).model_validate(args)
        if self.operation_store is None:
            _error("operation_store_required", "Signed durable operation storage is required before preparing writes.", 503)
        self.operation_store.ensure_ready()
        refs, scope = _refs(self.settings, self.scope_key)
        if skill_name == CREATE:
            profile = _profile(self.settings, self.scope_key)
            self._schema("CreationWorkflowPrepare", {"scope", "bootstrap_config", "creation_mode", "approval_mode",
                                                     "expected_revision", "authorization_valid_for_seconds"})
            self._schema("WorkflowBootstrapConfig", set(profile.bootstrap_config.model_dump()))
            catalog, factory = self._catalog()
            scales = factory["scale_sets"]
            selected = next(item for item in scales if item["id"] == str(refs.scale_set_id))
            if (factory.get("region") != profile.bootstrap_config.location
                    or selected.get("suffix") != profile.bootstrap_config.scale_set_number
                    or selected.get("network", {}).get("vnet_cidr") != profile.bootstrap_config.dev_vnet_cidr
                    or selected.get("orchestrator") != ("gha" if profile.bootstrap_config.github_repository else "ado")):
                _error("bootstrap_scope_mismatch", "The saved source region, scale, provider or network differs from the approved profile.", 403)
            saved = self._method("catalog_settings")(refs.folder, str(refs.factory_id), str(refs.scale_set_id), str(refs.project_id))
            state = saved.get("state") if isinstance(saved, dict) else None
            if (not isinstance(state, dict) or saved.get("revision") != catalog["revision"]
                    or any(saved.get(key) != str(getattr(refs, key)) for key in ("factory_id", "scale_set_id", "project_id"))
                    or str(state.get("enableAIFactoryHub")).lower() != "true"
                    or any(str(state.get(key)).lower() != "false" for key in
                           ("allowPublicAccessWhenBehindVnet", "enablePublicGenAIAccess", "enablePublicAccessWithPerimeter"))
                    or state.get("network_mode") != "private"):
                _error("private_configuration_required", "Save and verify private networking with this factory's own enabled hub before full bootstrap.", 503)
            request = _workflow_request(self.settings, self.scope_key, catalog["revision"])
            self._secret_free(request)
            preview = self._method("creation_workflow_prepare")(copy.deepcopy(request))
        elif skill_name == DELETE:
            if not self.settings.actions.deletion_resource_groups.get(self.scope_key):
                _error("deletion_scope_required", "Approve the complete whole-factory resource-group list on the server before deletion.", 503)
            self._schema("DeleteFactoryPrepare", {"folder", "factory_id", "expected_revision", "contract_version"})
            catalog, factory = self._catalog()
            _factory_scope(self.settings, self.scope_key, factory, whole=True)
            request = {"contract_version": 1, "folder": refs.folder, "factory_id": str(refs.factory_id),
                       "expected_revision": catalog["revision"]}
            preview = self._method("delete_aifactory_prepare")(copy.deepcopy(request))
        else:
            if parsed.project_number != scope.project:
                _error("cross_scope_write", "project.add authorizes only the exact configured scope's project number.", 403)
            self._schema("CatalogPrepare", {"factory_id", "project", "expected_revision"}, action="add-project")
            self._schema("CatalogProjectInput", {"number", "display_name", "placements"})
            catalog, factory = self._catalog(allow_absent_project=True)
            if any(item.get("number") == parsed.project_number for item in factory.get("projects", [])):
                _error("project_exists", "The selected project already exists; project.add will not replace it.")
            request = {"folder": refs.folder, "contract_version": 1, "action": "add-project",
                       "factory_id": str(refs.factory_id), "expected_revision": catalog["revision"],
                       "project": {"number": parsed.project_number, "display_name": parsed.display_name,
                                   "placements": [{"environment": scope.environment, "scale_set_id": str(refs.scale_set_id)}]}}
            self._secret_free(request)
            preview = self._method("catalog_prepare")(copy.deepcopy(request))
        validate_action_plan(self.settings, self.scope_key, skill_name, request, preview)
        clean, _ = plan_details(self.settings, self.scope_key, skill_name, request, preview)
        self._secret_free(clean)
        return self.operation_store.propose(self.principal, self.scope_key, skill_name, request, clean)

    def _record(self, record, *, claimed=False, continuation=False):
        from .operations import plan_hash
        if (not isinstance(record, dict) or record.get("tenant_id") != self.principal.tenant_id
                or record.get("object_id") != self.principal.object_id or record.get("scope_key") != self.scope_key
                or record.get("tool_name") not in ACTION_SKILLS
                or record.get("factory_api_url") != validate_base_url(self.settings.factory.api_url)
                or record.get("scope") != self.settings.scopes[self.scope_key].model_dump(mode="json")):
            _error("invalid_execution", "Only this caller's persisted scope-bound operation is accepted.", 403)
        if (any(key not in record for key in ("id", "correlation_id", "request", "preview", "created_at",
                                              "expires_at", "affected_resources", "plan_hash"))
                or record["plan_hash"] != plan_hash(record)):
            _error("plan_changed", "The persisted action plan changed.")
        if claimed or continuation:
            approval = record.get("approval")
            if (record.get("status") != ("continuing" if continuation else "executing") or not isinstance(approval, dict)
                    or any(approval.get(key) != record[key] for key in ("tenant_id", "object_id", "plan_hash"))
                    or not approval.get("approved_at")):
                _error("approval_required", "Execution requires the exact persisted, approved, single-use claimed plan.", 403)
        return record["tool_name"]

    def _job(self, skill_name, result, record, *, expected_id=None):
        from .tools import _uuid
        preview, refs = record["preview"], self.settings.factory
        if skill_name == CREATE:
            binding = {"kind": "creation-workflow", "id": preview["workflow_id"],
                       "scope": preview["scope"], "authorization_hash": preview["review"]["workflow_authorization"]["authorization_hash"]}
            if (not isinstance(result, dict) or type(result.get("contract_version")) is not int or result["contract_version"] != 1
                    or result.get("workflow_id") != binding["id"] or result.get("scope") != binding["scope"]
                    or result.get("mode") != "full" or result.get("stage") not in _STAGE_EFFECTS
                    or result.get("status") not in {"awaiting-review", "blocked", "queued", "running", "succeeded", "failed", "uncertain", "superseded"}
                    or type(result.get("requires_review")) is not bool or type(result.get("is_terminal")) is not bool):
                _error("invalid_factory_contract", "Workflow status changed the persisted workflow identity or bound scope.", 502)
            auth = result.get("authorization")
            stages = list(_STAGE_EFFECTS)
            completed = auth.get("completed_stages") if isinstance(auth, dict) else None
            if (not isinstance(auth, dict) or set(auth) != {"approval_mode", "authorization_hash", "expires_at",
                                                          "consumed", "invalidated", "completed_stages"}
                    or auth["authorization_hash"] != binding["authorization_hash"] or auth["approval_mode"] != "whole-workflow"
                    or auth["expires_at"] != preview["review"]["workflow_authorization"]["expires_at"]
                    or type(auth["consumed"]) is not bool or type(auth["invalidated"]) is not bool
                    or not isinstance(completed, list) or completed != stages[:len(completed)] or len(completed) > len(stages)):
                _error("invalid_factory_contract", "Workflow authorization drifted or its completion order changed.", 502)
            if result["status"] == "succeeded" and (not result["is_terminal"] or result["stage"] != "complete"
                                                    or completed != stages or auth["invalidated"]):
                _error("invalid_factory_contract", "A partial bootstrap cannot be reported as completed.", 502)
            state = result["status"]
            execution = {"queued": "running", "running": "running", "awaiting-review": "awaiting_continuation",
                         "blocked": "awaiting_continuation", "superseded": "failed"}.get(state, state)
            data = {key: copy.deepcopy(result[key]) for key in ("contract_version", "workflow_id", "mode", "scope", "stage",
                                                              "status", "requires_review", "is_terminal", "authorization")}
            # Observations do not replace the initial outcome/job binding in the durable store.
            for key in ("outcome", "observation"):
                prior = record.get(key)
                prior_data = prior.get("data") if isinstance(prior, dict) else None
                prior_auth = prior_data.get("authorization") if isinstance(prior_data, dict) else None
                prior_completed = prior_auth.get("completed_stages") if isinstance(prior_auth, dict) else None
                if prior is not None and (not isinstance(prior_data, dict) or prior_data.get("binding") != binding):
                    _error("job_binding_changed", "A persisted workflow observation changed its original binding.", 403)
                if isinstance(prior_completed, list) and completed[:len(prior_completed)] != prior_completed:
                    _error("invalid_factory_contract", "Workflow completion history moved backwards.", 502)
            diagnostic = result.get("execution_diagnostic")
            verified_boundary = (
                isinstance(diagnostic, dict)
                and set(diagnostic) <= {"contract_version", "stage", "phase", "outcome", "code", "action"}
                and type(diagnostic.get("contract_version")) is int and diagnostic["contract_version"] == 1
                and diagnostic.get("code") == "stage-execution-verified"
                and diagnostic.get("phase") == "stage-returned" and diagnostic.get("outcome") == "verified"
                and bool(completed) and diagnostic.get("stage") == completed[-1] == result["stage"]
            )
            if verified_boundary:
                data["verified_stage_boundary"] = True
            if (any(result.get(key) for key in ("recovery", "reconciliation", "supersession"))
                    or diagnostic and not verified_boundary):
                data["requires_new_approval"] = True
            for key in ("job_id", "job_kind"):
                if key in result:
                    data[key] = result[key]
            if execution == "awaiting_continuation":
                data["continuation"] = {"required": True, "automatic_retry_allowed": False,
                                        "within_original_authorization_only": True}
        else:
            job = result.get("job") if isinstance(result, dict) and "job" in result else result
            if skill_name == DELETE:
                try:
                    validate_job(job, factory_id=str(refs.factory_id), job_id=expected_id)
                except FailureError:
                    _error("invalid_factory_contract", "Deletion returned a changed or incompatible job.", 502)
            elif (not isinstance(job, dict) or job.get("action") != "add-project"
                  or job.get("factory_id") != str(refs.factory_id)
                  or job.get("scale_set_id") not in (None, str(refs.scale_set_id))
                  or job.get("project_id") != preview["project_id"]
                  or job.get("status") not in ("queued", "running", "succeeded", "failed", "interrupted")):
                _error("invalid_factory_contract", "Project action returned a changed or incompatible job.", 502)
            identifier = _uuid(job.get("id"))
            if expected_id is not None and identifier != expected_id:
                _error("invalid_factory_contract", "Status returned another job.", 502)
            binding = {"kind": "factory-deletion" if skill_name == DELETE else "catalog-project",
                       "id": identifier, "factory_id": str(refs.factory_id), "folder": refs.folder}
            if skill_name == ADD_PROJECT:
                binding.update(scale_set_id=str(refs.scale_set_id), project_id=preview["project_id"])
            execution = {"queued": "running", "interrupted": "uncertain"}.get(job["status"], job["status"])
            data = {key: job[key] for key in ("id", "action", "status", "factory_id", "scale_set_id", "project_id") if key in job}
        data["binding"] = binding
        return {"ok": True, "data": data, "execution_status": execution}

    def execute_operation(self, record):
        from .operations import OperationError
        from .tools import ToolError, _deadline
        try:
            skill_name = self._record(record, claimed=True)
            self._gate(skill_name)
            request, preview = record["request"], record["preview"]
            validate_action_plan(self.settings, self.scope_key, skill_name, request, preview)
            if min(_deadline(record["expires_at"]), _deadline(preview["expires_at"])) <= datetime.now(timezone.utc):
                _error("plan_expired", "The underlying Factory confirmation expired.")
            catalog, _ = self._catalog(allow_absent_project=skill_name == ADD_PROJECT)
            if catalog["revision"] != request["expected_revision"]:
                _error("revision_changed", "The reviewed saved Factory source changed; prepare again.")
            method = self._method({CREATE: "creation_workflow_start", DELETE: "delete_aifactory_confirm",
                                   ADD_PROJECT: "catalog_confirm"}[skill_name])
        except ToolError as exc:
            raise OperationError(exc.code, str(exc), exc.status_code) from None
        except ValidationError:
            raise OperationError("invalid_plan", "The persisted action does not match its closed schema.", 400) from None
        if skill_name == CREATE:
            result = method(
                self.settings.factory.folder, preview["workflow_id"], preview["confirmation_id"],
                authorization_hash=preview["review"]["workflow_authorization"]["authorization_hash"])
        elif skill_name == DELETE:
            result = method(
                folder=self.settings.factory.folder, confirmation_id=preview["confirmation_id"],
                preview_hash=preview["preview_hash"], confirmation_phrase=preview["confirmation_phrase"])
        else:
            result = method(self.settings.factory.folder, preview["confirmation_id"])
        try:
            if skill_name == ADD_PROJECT:
                if (not isinstance(result, dict) or type(result.get("contract_version")) is not int
                        or result["contract_version"] != 1 or result.get("job") is not None):
                    _error("invalid_factory_contract", "Project confirmation was not configuration-only.", 502)
                catalog = result.get("catalog")
                if (not isinstance(catalog, dict) or type(catalog.get("contract_version")) is not int
                        or catalog["contract_version"] != 1):
                    _error("invalid_factory_contract", "Project save omitted the updated catalog.", 502)
                from .tools import _revision
                _revision(catalog.get("revision"))
                factories = [item for item in catalog.get("factories", []) if item.get("id") == request["factory_id"]]
                if len(factories) != 1:
                    _error("invalid_factory_contract", "Project save omitted the reviewed factory.", 502)
                _validate_project(self.settings, self.scope_key, request, {**preview, "target": factories[0]})
                return {"ok": True, "data": {"operation_mode": "configuration", "resources_deployed": False,
                                           "project_id": preview["project_id"], "project_number": request["project"]["number"]},
                        "execution_status": "succeeded"}
            return self._started(self._job(skill_name, result, record))
        except OperationError:
            raise
        except (ToolError, ValidationError, KeyError, TypeError, AttributeError) as exc:
            raise OperationError("completion_unknown", str(exc), 503, uncertain=True) from None

    @staticmethod
    def _started(result):
        from .operations import OperationError
        if result["execution_status"] == "failed":
            raise OperationError("factory_operation_failed", "The bound Factory operation reported failure.")
        if result["execution_status"] == "uncertain":
            raise OperationError("completion_unknown", "Factory completion is unknown; never retry the write.",
                                 503, uncertain=True)
        return result

    def status(self, record):
        skill_name = self._record(record)
        _authorize(self.settings, self.principal, self.scope_key, required_permission(skill_name))
        outcome = record.get("outcome")
        data = outcome.get("data") if isinstance(outcome, dict) else None
        binding = data.get("binding") if isinstance(data, dict) else None
        if skill_name == ADD_PROJECT and record.get("status") == "succeeded" and isinstance(data, dict) and data.get("resources_deployed") is False:
            return copy.deepcopy(outcome)
        if not isinstance(binding, dict):
            _error("job_binding_required", "No persisted backend job binding exists; do not retry the write.", 409)
        refs = self.settings.factory
        if skill_name == CREATE:
            auth = record["preview"]["review"]["workflow_authorization"]
            expected = {"kind": "creation-workflow", "id": record["preview"]["workflow_id"],
                        "scope": record["preview"]["scope"], "authorization_hash": auth["authorization_hash"]}
            configured_scope = {"folder": refs.folder, **{key: str(getattr(refs, key))
                                                         for key in ("factory_id", "scale_set_id", "project_id")}}
            if binding != expected or binding["scope"] != configured_scope:
                _error("job_binding_changed", "The persisted workflow binding changed.", 403)
            result = self._method("creation_workflow_status")(refs.folder, binding["id"])
        else:
            from .tools import _uuid
            identifier = _uuid(binding.get("id"))
            expected = {"kind": "factory-deletion" if skill_name == DELETE else "catalog-project",
                        "id": identifier, "factory_id": str(refs.factory_id), "folder": refs.folder}
            if skill_name == ADD_PROJECT:
                expected.update(scale_set_id=str(refs.scale_set_id), project_id=record["preview"]["project_id"])
            if binding != expected:
                _error("job_binding_changed", "The persisted job binding changed.", 403)
            result = self._method("delete_aifactory_status" if skill_name == DELETE else "catalog_job")(refs.folder, identifier)
        return self._job(skill_name, result, record, expected_id=binding["id"])

    def _continuation_record(self, record):
        from .tools import _deadline
        if self._record(record, continuation=True) != CREATE:
            _error("continuation_claim_required", "The store must claim this persisted paused workflow exactly once.", 403)
        self._gate(CREATE)
        validate_action_plan(self.settings, self.scope_key, CREATE, record["request"], record["preview"])
        observed = record.get("observation") or record.get("outcome")
        observed_data = observed.get("data") if isinstance(observed, dict) else None
        observed_auth = observed_data.get("authorization") if isinstance(observed_data, dict) else None
        if (not isinstance(observed, dict) or observed.get("ok") is not True
                or observed.get("execution_status") != "awaiting_continuation"
                or not isinstance(observed_auth, dict) or observed_data.get("status") != "awaiting-review"):
            _error("continuation_claim_required", "Claim the exact persisted awaiting-review observation before continuation.", 403)
        current = self.status(record)
        data = current["data"]
        authorization = data["authorization"]
        completed = authorization["completed_stages"]
        stages = list(_STAGE_EFFECTS)
        ready_stage = len(completed) < len(stages) and data["stage"] == stages[len(completed)]
        verified_boundary = (
            bool(completed) and data["stage"] == completed[-1]
            and data.get("verified_stage_boundary") is True and data["requires_review"] is False
        )
        if (current["execution_status"] != "awaiting_continuation" or data["status"] != "awaiting-review"
                or not authorization["consumed"] or authorization["invalidated"]
                or _deadline(authorization["expires_at"]) <= datetime.now(timezone.utc)
                or data.get("requires_new_approval") is True
                or data["is_terminal"]
                or data["stage"] != observed_data.get("stage")
                or authorization["completed_stages"] != observed_auth.get("completed_stages")
                or len(completed) >= len(stages) or not (ready_stage or verified_boundary)):
            _error("continuation_blocked", "Continuation is outside the original authorization or requires recovery/new approval.")
        return current

    def continue_operation(self, record):
        """Explicit callback; CAS awaiting_continuation -> continuing before calling.

        Preserve outcome and original approval; persist the latest status as observation.
        Require caller-supplied plan and observation hashes and atomically claim that
        observation once; a stale request must not continue a later stage's pause.
        A crash/timeout is uncertain, never a replayable continuation. Persist the result
        as a new observation, not an outcome; status and execution never auto-continue.
        The original full-workflow authorization expiry, not the consumed initial
        confirmation TTL, bounds continuation; recovery requires a separately reviewed plan.
        """
        from .operations import OperationError
        from .tools import ToolError
        try:
            current = self._continuation_record(record)
            method = self._method("creation_workflow_continue")
        except ToolError as exc:
            raise OperationError(exc.code, str(exc), exc.status_code) from None
        except ValidationError:
            raise OperationError("invalid_plan", "The persisted workflow does not match its closed schema.", 400) from None
        result = method(self.settings.factory.folder, record["preview"]["workflow_id"],
                        current["data"]["authorization"]["authorization_hash"])
        try:
            return self._started(self._job(CREATE, result, {**record, "observation": current}))
        except OperationError:
            raise
        except (ToolError, ValidationError, KeyError, TypeError, AttributeError) as exc:
            raise OperationError("completion_unknown", str(exc), 503, uncertain=True) from None
