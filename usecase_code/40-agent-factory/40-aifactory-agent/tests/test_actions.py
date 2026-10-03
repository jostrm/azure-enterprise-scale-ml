import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from azurefactory.client import canonical_json_hash, validate_base_url
from azurefactory.errors import RequestTimeout
from pydantic import ValidationError

from aifactory_agent.actions import (
    ACTION_SKILLS, ADD_PROJECT, CREATE, DELETE, ActionSettings, ActionSkills, BootstrapConfig,
    BootstrapProfile, ProjectArguments, SourceDefinition, _ALLOWED_CHANGES, _ENV_CONSTRAINTS,
    _HALT_POLICY, _STAGE_EFFECTS, argument_model, plan_details, required_permission,
    validate_action_plan, validate_destructive_approval,
)
from aifactory_agent.operations import MemoryOperationBackend, OperationError, OperationStore, plan_hash
from aifactory_agent.tools import ToolError
from test_security import CALLER, CLIENT, FACTORY, PROJECT, SCALE, SCOPE, SUBSCRIPTION, TENANT, principal, settings


REVISION = "a" * 64
CONFIRMATION = "88888888-8888-4888-8888-888888888888"
WORKFLOW = "99999999-9999-4999-8999-999999999999"
NEW_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
COMMON = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/factory-common-dev-rg"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/factory-project001-dev-rg"
HUB = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/factory-own-hub-rg"
IDENTITY = COMMON + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/deployer"
SEARCH = GROUP + "/providers/Microsoft.Search/services/project-search"
LINK = SEARCH + "/sharedPrivateLinkResources/blob"


def expiry():
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def profile_values():
    return {
        "bootstrap_config": {
            "subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "location": "swedencentral",
            "factory_prefix": "factory-", "scale_set_number": "001", "repo_root": "C:\\state",
            "github_repository": "example/factory", "team_member_email": "owner@example.test",
            "team_group_name": "factory-team", "dev_vnet_cidr": "172.16.0.0/18",
            "vpn_client_cidr": "172.31.240.0/24", "access_hub_lock_resource_group": "factory-own-hub-rg",
            "bootstrap_public_ipv4": "8.8.8.8",
        },
        "source": {
            "url": "https://github.com/jostrm/azure-enterprise-scale-ml", "ref": "main", "sha": "a" * 40,
            "verification": "published-remote-ref",
            "assets": {"bootstrap/templates/factory-lifecycle-gha.yml": "b" * 40},
        },
        "program_fingerprint": "e" * 64, "workflow_input_hash": "f" * 64,
        "resource_groups": [COMMON, GROUP, HUB], "deployment_identity_id": IDENTITY,
        "repository_environments": ["factory-dev"], "auth_namespace": "factory-dev",
    }


@pytest.fixture
def action_settings(settings):
    actions = ActionSettings(enabled_skills=list(ACTION_SKILLS), bootstrap_profiles={SCOPE: BootstrapProfile(**profile_values())},
                             deletion_resource_groups={SCOPE: [GROUP]})
    grants = [SimpleNamespace(object_id=CALLER, scopes=[SCOPE], permissions=["factory.create", "factory.delete", "project.add"])]
    return settings.model_copy(update={"actions": actions, "auth": settings.auth.model_copy(update={"grants": grants})})


def factory_target(*, existing_project=True):
    return {
        "id": FACTORY, "key": "factory-sweden-ai", "prefix": "factory", "region": "swedencentral",
        "scale_sets": [{
            "id": SCALE, "environment": "dev", "tenant_id": TENANT, "subscription_id": SUBSCRIPTION,
            "suffix": "001", "orchestrator": "gha", "network": {"vnet_cidr": "172.16.0.0/18"},
        }],
        "projects": ([{
            "id": PROJECT, "number": "001", "display_name": "Default",
            "placements": [{"environment": "dev", "scale_set_id": SCALE}],
        }] if existing_project else []),
    }


def base_preview():
    return {"contract_version": 1, "confirmation_id": CONFIRMATION, "can_execute": True,
            "expires_at": expiry(), "source_revision": REVISION, "effects": ["Reviewed exact effects"],
            "warnings": [], "blockers": []}


def project_preview(request):
    target = factory_target(existing_project=False)
    target["projects"].append({"id": NEW_PROJECT, **copy.deepcopy(request["project"])})
    return {**base_preview(), "operation_mode": "configuration", "factory_id": FACTORY, "scale_set_id": SCALE,
            "project_id": NEW_PROJECT, "target": target, "inventory": [], "deletion_targets": [], "binding": None}


def delete_preview():
    return {
        **base_preview(), "capabilities": ["delete-aifactory-v1"], "operation_mode": "runtime", "action": "delete-factory",
        "folder": "C:\\state\\factory", "factory_id": FACTORY, "scale_set_id": None, "project_id": None,
        "preview_hash": "c" * 64, "confirmation_phrase": "DELETE factory-sweden-ai", "target": factory_target(),
        "deletion_scope": "whole-factory", "preserve_entra_groups": True, "retain_saved_configuration": False,
        "source_version": {"requested_version": "main", "branch": "main", "resolved_ref": "a" * 40},
        "retained_resources": [], "deletion_targets": [{
            "scale_set_id": SCALE, "factory_id": FACTORY, "project_id": None, "environment": "dev",
            "tenant_id": TENANT, "subscription_id": SUBSCRIPTION, "name": "factory-project001-dev-rg",
            "resource_group": "factory-project001-dev-rg", "resource_id": GROUP, "delete": [SEARCH, LINK], "retain": [],
        }],
        "inventory": [{"resource_id": SEARCH, "dependencies": [LINK]}, {"resource_id": LINK, "dependencies": []}],
    }


def workflow_preview(request, profile):
    config = profile.bootstrap_config
    repository = "https://github.com/" + config.github_repository
    environments = {
        "repository": repository, "auth_namespace": profile.auth_namespace, "constraints": _ENV_CONSTRAINTS,
        "environments": [{"name": "factory-dev", "action": "create-if-missing",
                          "observed_snapshot_sha256": canonical_json_hash(None)}],
    }
    stages = [{"stage": name, "effects": effect} for name, effect in _STAGE_EFFECTS.items()]
    stages[1]["effects"] += (
        " GitHub environments: factory-dev (create-if-missing). Selected deployment authentication namespace: factory-dev. "
        + " ".join(_ENV_CONSTRAINTS))
    authorization = {
        "contract": "bounded-full-bootstrap-v1", "authorization_id": CLIENT, "workflow_id": WORKFLOW,
        "approval_mode": "whole-workflow", "scope": copy.deepcopy(request["scope"]),
        # The API hashes its normalized saved body, not the incoming JSON request.
        "input_hash": profile.workflow_input_hash, "source_revision": REVISION,
        "target": {
            "tenant_id": TENANT, "subscription_id": SUBSCRIPTION, "location": "swedencentral",
            "resource_groups": profile.resource_groups, "deployment_identity_id": IDENTITY, "vnet_cidr": config.dev_vnet_cidr,
            "subscription_operations": ["required resource-provider registration", "deployment records",
                                        "narrow deployment-record custom role definition/assignment"],
            "directory_operations": "Only configured team group/members and selected first-party service principals",
            "role_definition_ids": ["b24988ac-6180-42a0-ab88-20f7382dd24c", "f58310d9-a9f6-439a-9e8d-f62e7b41a168"],
        },
        "source": profile.source.model_dump(mode="json"), "program_fingerprint": profile.program_fingerprint,
        "template_fingerprint": canonical_json_hash(profile.source.model_dump(mode="json")),
        "repository": repository, "branch": "main", "repository_environments": environments,
        "coordination_mode": "blob", "governance_warnings": [], "stages": stages,
        "expires_at": expiry(), "allowed_changes": _ALLOWED_CHANGES, "halt_policy": _HALT_POLICY,
    }
    authorization["authorization_hash"] = canonical_json_hash(authorization)
    return {**base_preview(), "workflow_id": WORKFLOW, "scope": request["scope"], "stage": "hub-lock-foundation",
            "input_hash": "d" * 64, "review": {"workflow_authorization": authorization, "secret": "not-persisted"}}


class RecordingStore:
    """The adapter's injected store boundary, with real persisted CAS records."""

    def __init__(self, settings):
        self.settings = settings
        self.backend = MemoryOperationBackend()
        self.ready_calls = 0

    def ensure_ready(self):
        self.ready_calls += 1

    def propose(self, principal, scope_key, tool_name, request, preview):
        review, affected = plan_details(self.settings, scope_key, tool_name, request, preview)
        record = {
            "id": str(uuid4()), "correlation_id": str(uuid4()), "tenant_id": principal.tenant_id,
            "object_id": principal.object_id, "scope_key": scope_key,
            "scope": self.settings.scopes[scope_key].model_dump(mode="json"), "tool_name": tool_name,
            "factory_api_url": validate_base_url(self.settings.factory.api_url),
            "request": copy.deepcopy(request), "preview": review, "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": preview["expires_at"], "affected_resources": affected,
            "status": "pending", "approval": None, "outcome": None,
        }
        record["plan_hash"] = plan_hash(record)
        self.backend.create(record["id"], record)
        return copy.deepcopy(record)

    def approve(self, record, phrase=None):
        current, etag = self.backend.read(record["id"])
        validate_destructive_approval(current, phrase)
        assert current["status"] == "pending"
        current["status"] = "approved"
        current["approval"] = {key: current[key] for key in ("tenant_id", "object_id", "plan_hash")}
        current["approval"]["approved_at"] = datetime.now(timezone.utc).isoformat()
        self.backend.replace(current["id"], current, etag)

    def execute(self, record, adapter):
        current, etag = self.backend.read(record["id"])
        if current["status"] != "approved":
            raise ToolError("approval_required", "Already claimed or unapproved.")
        current["status"] = "executing"
        etag = self.backend.replace(current["id"], current, etag)
        outcome = adapter.execute_operation(copy.deepcopy(current))
        current["status"], current["outcome"] = outcome["execution_status"], outcome
        self.backend.replace(current["id"], current, etag)
        return current


class FakeAPI:
    api_key = "credential-never-persist"

    def __init__(self, settings):
        self.settings, self.calls = settings, []
        self.catalog = {"contract_version": 1, "revision": REVISION, "factories": [factory_target()]}
        self.preview = None
        self.result = None
        self.workflow_state = None
        self.private_state = {
            "enableAIFactoryHub": "true", "allowPublicAccessWhenBehindVnet": "false",
            "enablePublicGenAIAccess": "false", "enablePublicAccessWithPerimeter": "false", "network_mode": "private",
        }
        closed = lambda fields: {"additionalProperties": False, "properties": {name: {} for name in fields}}
        self.schemas = {
            "CreationWorkflowPrepare": closed({"scope", "bootstrap_config", "creation_mode", "approval_mode",
                                               "expected_revision", "authorization_valid_for_seconds"}),
            "WorkflowBootstrapConfig": closed(set(BootstrapConfig.model_fields)),
            "DeleteFactoryPrepare": closed({"folder", "factory_id", "expected_revision", "contract_version"}),
            "CatalogPrepare": closed({"factory_id", "project", "expected_revision", "action"}),
            "CatalogProjectInput": closed({"number", "display_name", "placements"}),
        }
        self.schemas["CatalogPrepare"]["properties"]["action"] = {"enum": ["add-project"]}

    def openapi(self):
        self.calls.append(("openapi",))
        return {"components": {"schemas": copy.deepcopy(self.schemas)}}

    def catalog_list(self, folder):
        self.calls.append(("catalog_list", folder))
        return copy.deepcopy(self.catalog)

    def catalog_settings(self, folder, factory_id, scale_set_id, project_id):
        self.calls.append(("catalog_settings", folder, factory_id, scale_set_id, project_id))
        return {"contract_version": 1, "revision": REVISION, "factory_id": factory_id,
                "scale_set_id": scale_set_id, "project_id": project_id, "state": copy.deepcopy(self.private_state)}

    def creation_workflow_prepare(self, request):
        self.calls.append(("creation_workflow_prepare", copy.deepcopy(request)))
        return copy.deepcopy(self.preview or workflow_preview(request, self.settings.actions.bootstrap_profiles[SCOPE]))

    def delete_aifactory_prepare(self, request):
        self.calls.append(("delete_aifactory_prepare", copy.deepcopy(request)))
        return copy.deepcopy(self.preview or delete_preview())

    def catalog_prepare(self, request):
        self.calls.append(("catalog_prepare", copy.deepcopy(request)))
        return copy.deepcopy(self.preview or project_preview(request))

    def creation_workflow_start(self, folder, workflow_id, confirmation_id, *, authorization_hash):
        self.calls.append(("creation_workflow_start", folder, workflow_id, confirmation_id, authorization_hash))
        return copy.deepcopy(self.result)

    def delete_aifactory_confirm(self, **kwargs):
        self.calls.append(("delete_aifactory_confirm", kwargs))
        return copy.deepcopy(self.result or {"contract_version": 1, "catalog": None, "job": self.job("delete-factory")})

    def catalog_confirm(self, folder, confirmation_id):
        self.calls.append(("catalog_confirm", folder, confirmation_id))
        return copy.deepcopy(self.result)

    def creation_workflow_status(self, folder, workflow_id):
        self.calls.append(("creation_workflow_status", folder, workflow_id))
        return copy.deepcopy(self.workflow_state)

    def creation_workflow_continue(self, folder, workflow_id, authorization_hash):
        self.calls.append(("creation_workflow_continue", folder, workflow_id, authorization_hash))
        return copy.deepcopy(self.result)

    def delete_aifactory_status(self, folder, job_id):
        self.calls.append(("delete_aifactory_status", folder, job_id))
        return copy.deepcopy(self.job("delete-factory", status="succeeded"))

    def catalog_job(self, folder, job_id):
        self.calls.append(("catalog_job", folder, job_id))
        return copy.deepcopy(self.job("add-project", status="succeeded"))

    @staticmethod
    def job(action, status="queued"):
        return {"id": JOB, "action": action, "status": status, "factory_id": FACTORY, "scale_set_id": None,
                "project_id": NEW_PROJECT if action == "add-project" else None}


@pytest.fixture
def setup(action_settings, principal):
    store = RecordingStore(action_settings)
    api = FakeAPI(action_settings)
    return ActionSkills(action_settings, principal, SCOPE, api, store), api, store


def workflow_status(record, status="queued", *, stage="hub-lock-foundation", completed=None):
    auth = record["preview"]["review"]["workflow_authorization"]
    return {
        "contract_version": 1, "workflow_id": WORKFLOW, "mode": "full", "stage": stage,
        "scope": copy.deepcopy(record["preview"]["scope"]), "status": status,
        "requires_review": status == "awaiting-review", "is_terminal": status in ("succeeded", "failed", "uncertain"),
        "source_revision": REVISION, "authorization": {
            "approval_mode": "whole-workflow", "authorization_hash": auth["authorization_hash"],
            "expires_at": auth["expires_at"], "consumed": True, "invalidated": False, "completed_stages": completed or [],
        },
    }


def test_exact_skill_names_and_independent_permissions():
    assert ACTION_SKILLS == (CREATE, DELETE, ADD_PROJECT)
    assert [required_permission(name) for name in ACTION_SKILLS] == ["factory.create", "factory.delete", "project.add"]
    for name in ("/delete-aifactory", "shell", "factory-create"):
        with pytest.raises(ToolError):
            required_permission(name)
    assert ActionSettings().enabled_skills == []


@pytest.mark.parametrize("skill,args", [
    (CREATE, {"folder": "elsewhere"}), (CREATE, {"bootstrap_config": {}}), (DELETE, {"force": True}),
    (DELETE, {"factory_id": CLIENT}), (ADD_PROJECT, {"project_number": "001", "display_name": "Example", "deploy": True}),
    (ADD_PROJECT, {"project_number": 1, "display_name": "Example"}),
    (ADD_PROJECT, {"project_number": "000", "display_name": "Example"}),
    (ADD_PROJECT, {"project_number": "01", "display_name": "Example"}),
    (ADD_PROJECT, {"project_number": "001", "display_name": "$(execute)"}),
    (ADD_PROJECT, {"project_number": "001", "display_name": "line\nbreak"}),
])
def test_argument_schemas_are_closed_and_strict(skill, args):
    assert argument_model(skill).model_json_schema()["additionalProperties"] is False
    with pytest.raises(ValidationError):
        argument_model(skill).model_validate(args)


@pytest.mark.parametrize("changes", [
    {"vpn_client_cidr": "172.16.1.0/24"}, {"vpn_client_cidr": "172.31.240.1/24"},
    {"dev_vnet_cidr": "192.168.0.0/24"}, {"bootstrap_public_ipv4": "10.0.0.1"},
    {"vpn_client_cidr": None}, {"access_hub_mode": "external"}, {"github_visibility": "public"},
    {"setup_hub_access": False}, {"project_number": "002"}, {"runner_mode": "hosted"},
    {"coordination_mode": "single-writer"}, {"api_key": "secret"}, {"password": "secret"},
])
def test_bootstrap_profile_cannot_weaken_requested_contract(changes):
    value = profile_values()
    value["bootstrap_config"].update(changes)
    with pytest.raises(ValidationError):
        BootstrapProfile.model_validate(value)


def test_configuration_rejects_unknown_skills_raw_profile_and_deletion_wildcards():
    for value in ({"enabled_skills": ["shell"]}, {"command": "run"}, {"bootstrap_profiles": {SCOPE: {"config": {}}}},
                  {"deletion_resource_groups": {SCOPE: ["*"]}},
                  {"deletion_resource_groups": {SCOPE: [GROUP, GROUP.lower()]}}):
        with pytest.raises(ValidationError):
            ActionSettings.model_validate(value)
    value = profile_values()
    value["source"]["url"] = "https://token@github.com/owner/repository"
    with pytest.raises(ValidationError):
        BootstrapProfile.model_validate(value)


@pytest.mark.parametrize("skill,permission", [(CREATE, "factory.create"), (DELETE, "factory.delete"), (ADD_PROJECT, "project.add")])
def test_write_grants_are_not_inferred_from_read_or_other_actions(setup, action_settings, principal, skill, permission):
    adapter, api, store = setup
    for grants in ([], [SimpleNamespace(object_id=CALLER, scopes=[SCOPE], permissions=["factory.read", "config.write"])],
                   [SimpleNamespace(object_id=CALLER, scopes=["project002-dev"], permissions=[permission])]):
        adapter.settings = action_settings.model_copy(update={"auth": action_settings.auth.model_copy(update={"grants": grants})})
        with pytest.raises(PermissionError):
            adapter.prepare(skill, {})
    assert api.calls == [] and store.ready_calls == 0


@pytest.mark.parametrize("gate", ["writes", "environment", "skill"])
def test_disabled_gates_precede_api_and_store_calls(setup, action_settings, gate):
    adapter, api, store = setup
    if gate == "writes":
        adapter.settings = action_settings.model_copy(update={"factory": action_settings.factory.model_copy(update={"writes_enabled": False})})
    elif gate == "environment":
        adapter.settings = action_settings.model_copy(update={"factory": action_settings.factory.model_copy(update={"allowed_write_environments": ["prod"]})})
    else:
        adapter.settings = action_settings.model_copy(update={"actions": ActionSettings()})
    with pytest.raises(ToolError):
        adapter.prepare(DELETE, {})
    assert api.calls == [] and store.ready_calls == 0


def test_no_argument_full_bootstrap_prepares_only_approved_private_workflow(setup):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    assert record["status"] == "pending" and record["approval"] is None
    assert len(record["plan_hash"]) == 64 and store.ready_calls == 1
    request = record["request"]
    assert request["scope"] == {"folder": "C:\\state\\factory", "factory_id": FACTORY, "scale_set_id": SCALE, "project_id": PROJECT}
    assert request["creation_mode"] == "full-bootstrap" and request["approval_mode"] == "whole-workflow"
    assert request["bootstrap_config"]["vpn_client_cidr"] == "172.31.240.0/24"
    assert list(record["preview"]["review"]) == ["workflow_authorization"]
    assert "credential-never-persist" not in repr(record) and "not-persisted" not in repr(record)
    assert [item["resource_id"] for item in record["affected_resources"]] == [COMMON, GROUP, HUB]
    assert not any(call[0].endswith(("start", "confirm")) for call in api.calls)


@pytest.mark.parametrize("kind", ["profile", "saved_factory", "private", "closed_schema", "region", "network"])
def test_missing_bootstrap_prerequisites_do_not_provision(setup, kind):
    adapter, api, _ = setup
    if kind == "profile":
        adapter.settings = adapter.settings.model_copy(update={"actions": adapter.settings.actions.model_copy(update={"bootstrap_profiles": {}})})
    elif kind == "saved_factory":
        api.catalog["factories"] = []
    elif kind == "private":
        api.private_state["enablePublicGenAIAccess"] = "true"
    elif kind == "closed_schema":
        api.schemas["CreationWorkflowPrepare"]["additionalProperties"] = True
    elif kind == "region":
        api.catalog["factories"][0]["region"] = "eastus"
    else:
        api.catalog["factories"][0]["scale_sets"][0]["network"]["vnet_cidr"] = "10.0.0.0/18"
    with pytest.raises(ToolError):
        adapter.prepare(CREATE, {})
    assert not any(call[0] == "creation_workflow_prepare" for call in api.calls)


@pytest.mark.parametrize("drift", ["source", "definition", "hash", "groups", "input", "stages", "environments", "scope"])
def test_workflow_receipt_rejects_expansion_or_unpinned_definition(setup, drift):
    adapter, api, _ = setup
    safe = adapter.prepare(CREATE, {})
    raw = copy.deepcopy(safe["preview"])
    auth = raw["review"]["workflow_authorization"]
    if drift == "source":
        auth["source"]["sha"] = "b" * 40
    elif drift == "definition":
        auth["program_fingerprint"] = "b" * 64
    elif drift == "hash":
        auth["authorization_hash"] = "b" * 64
    elif drift == "groups":
        auth["target"]["resource_groups"].append("/subscriptions/" + CLIENT + "/resourceGroups/outside")
    elif drift == "input":
        auth["input_hash"] = "b" * 64
    elif drift == "stages":
        auth["stages"] = auth["stages"][:-1]
    elif drift == "environments":
        auth["repository_environments"]["environments"][0]["name"] = "prod"
    else:
        raw["scope"]["project_id"] = CLIENT
    if drift != "hash":
        auth["authorization_hash"] = canonical_json_hash({key: value for key, value in auth.items() if key != "authorization_hash"})
    with pytest.raises(ToolError):
        validate_action_plan(adapter.settings, SCOPE, CREATE, safe["request"], raw)


def test_add_project_is_real_configuration_action_not_resource_deployment(setup):
    adapter, api, store = setup
    api.catalog["factories"] = [factory_target(existing_project=False)]
    record = adapter.prepare(ADD_PROJECT, {"project_number": "001", "display_name": "Research"})
    request = record["request"]
    assert request["action"] == "add-project" and "project_id" not in request and "deploy" not in request
    assert request["project"]["placements"] == [{"environment": "dev", "scale_set_id": SCALE}]
    assert record["preview"]["operation_mode"] == "configuration"
    assert record["affected_resources"][0]["project_id"] == NEW_PROJECT
    api.result = {"contract_version": 1, "catalog": {"contract_version": 1, "revision": "b" * 64,
                  "factories": [record["preview"]["target"]]}, "job": None}
    store.approve(record)
    completed = store.execute(record, adapter)
    assert completed["status"] == "succeeded" and completed["outcome"]["data"]["resources_deployed"] is False
    assert adapter.status(completed) == completed["outcome"]
    assert api.calls[-1] == ("catalog_confirm", "C:\\state\\factory", CONFIRMATION)
    with pytest.raises(ToolError):
        store.execute(record, adapter)
    assert sum(call[0] == "catalog_confirm" for call in api.calls) == 1


def test_project_add_rejects_other_scope_existing_project_and_credential(setup):
    adapter, api, _ = setup
    with pytest.raises(ToolError, match="exact configured"):
        adapter.prepare(ADD_PROJECT, {"project_number": "002", "display_name": "Other"})
    with pytest.raises(ToolError, match="already exists"):
        adapter.prepare(ADD_PROJECT, {"project_number": "001", "display_name": "Existing"})
    api.catalog["factories"] = [factory_target(existing_project=False)]
    with pytest.raises(ToolError, match="Credentials"):
        adapter.prepare(ADD_PROJECT, {"project_number": "001", "display_name": api.api_key})
    assert not any(call[0] == "catalog_prepare" for call in api.calls)


def test_delete_uses_named_validator_and_exact_human_phrase(setup):
    adapter, api, store = setup
    record = adapter.prepare(DELETE, {})
    assert record["request"] == {"contract_version": 1, "folder": "C:\\state\\factory",
                                 "factory_id": FACTORY, "expected_revision": REVISION}
    for phrase in (None, "", "DELETE factory", "delete factory-sweden-ai", "DELETE factory-sweden-ai "):
        with pytest.raises(ToolError):
            store.approve(record, phrase)
    store.approve(record, "DELETE factory-sweden-ai")
    running = store.execute(record, adapter)
    assert running["status"] == "running" and running["outcome"]["data"]["status"] == "queued"
    confirm = [call for call in api.calls if call[0] == "delete_aifactory_confirm"]
    assert confirm == [("delete_aifactory_confirm", {
        "folder": "C:\\state\\factory", "confirmation_id": CONFIRMATION, "preview_hash": "c" * 64,
        "confirmation_phrase": "DELETE factory-sweden-ai",
    })]
    status = adapter.status(running)
    assert status["execution_status"] == "succeeded"
    assert api.calls[-1] == ("delete_aifactory_status", "C:\\state\\factory", JOB)
    assert not any(call[0] == "catalog_confirm" for call in api.calls)


@pytest.mark.parametrize("change", [
    "preserve_entra", "manifest", "inventory", "hash", "phrase", "search_order", "cycle", "cross_env", "resource_groups",
])
def test_unsafe_deletion_receipts_fail_closed(setup, change):
    adapter, api, store = setup
    value = delete_preview()
    if change == "preserve_entra":
        value["preserve_entra_groups"] = False
    elif change == "manifest":
        value["deletion_targets"][0]["delete"].append(COMMON)
    elif change == "inventory":
        value["inventory"].pop()
    elif change == "hash":
        value["preview_hash"] = "not-a-hash"
    elif change == "phrase":
        value["confirmation_phrase"] = "DELETE someone-else"
    elif change == "search_order":
        value["inventory"][0]["dependencies"] = []
    elif change == "cycle":
        value["inventory"][1]["dependencies"] = [SEARCH]
    elif change == "cross_env":
        value["target"]["scale_sets"][0]["environment"] = "prod"
        value["deletion_targets"][0]["environment"] = "prod"
    else:
        adapter.settings = adapter.settings.model_copy(update={"actions": adapter.settings.actions.model_copy(
            update={"deletion_resource_groups": {SCOPE: [GROUP, COMMON]}})})
    api.preview = value
    with pytest.raises(ToolError):
        adapter.prepare(DELETE, {})
    assert not store.backend._records
    assert not any(call[0].endswith("confirm") for call in api.calls)


def test_delete_needs_server_breadth_not_project_access(setup):
    adapter, api, _ = setup
    adapter.settings = adapter.settings.model_copy(update={"actions": adapter.settings.actions.model_copy(
        update={"deletion_resource_groups": {}})})
    with pytest.raises(ToolError) as error:
        adapter.prepare(DELETE, {})
    assert error.value.code == "deletion_scope_required" and api.calls == []


@pytest.mark.parametrize("field,value", [
    ("status", "approved"), ("object_id", CLIENT), ("tenant_id", CLIENT), ("scope_key", "project002-dev"),
    ("factory_api_url", "https://other.test"), ("plan_hash", "b" * 64), ("approval", None),
])
def test_execution_requires_exact_claimed_persisted_approval(setup, field, value):
    adapter, api, store = setup
    record = adapter.prepare(DELETE, {})
    store.approve(record, "DELETE factory-sweden-ai")
    claimed, _ = store.backend.read(record["id"])
    claimed["status"] = "executing"
    claimed[field] = value
    with pytest.raises(ToolError):
        adapter.execute_operation(claimed)
    assert not any(call[0].endswith("confirm") for call in api.calls)


def test_revision_drift_stops_confirmation_and_missing_sdk_is_explicit(setup):
    adapter, api, store = setup
    record = adapter.prepare(DELETE, {})
    store.approve(record, "DELETE factory-sweden-ai")
    api.catalog["revision"] = "b" * 64
    with pytest.raises(ToolError) as error:
        store.execute(record, adapter)
    assert error.value.code == "revision_changed"
    assert not any(call[0].endswith("confirm") for call in api.calls)
    api.catalog["revision"] = REVISION
    api.delete_aifactory_prepare = None
    with pytest.raises(ToolError) as error:
        adapter.prepare(DELETE, {})
    assert error.value.code == "unsupported_factory_sdk"


def test_uncertain_write_is_not_retried_and_bad_job_is_never_success(setup):
    adapter, api, store = setup
    record = adapter.prepare(DELETE, {})
    store.approve(record, "DELETE factory-sweden-ai")
    def timeout(**kwargs):
        api.calls.append(("delete_aifactory_confirm", kwargs))
        raise RequestTimeout("unknown completion")
    api.delete_aifactory_confirm = timeout
    with pytest.raises(RequestTimeout):
        store.execute(record, adapter)
    with pytest.raises(ToolError):
        store.execute(record, adapter)
    assert sum(call[0] == "delete_aifactory_confirm" for call in api.calls) == 1


def test_incompatible_job_is_marked_uncertain_after_write(setup):
    adapter, api, store = setup
    record = adapter.prepare(DELETE, {})
    store.approve(record, "DELETE factory-sweden-ai")
    api.result = {"job": {**api.job("delete-factory"), "factory_id": CLIENT}}
    with pytest.raises(OperationError) as error:
        store.execute(record, adapter)
    assert error.value.uncertain is True and error.value.code == "completion_unknown"


def test_workflow_async_status_uses_only_persisted_binding(setup):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    api.result = workflow_status(record)
    store.approve(record)
    running = store.execute(record, adapter)
    assert running["status"] == "running"
    api.workflow_state = workflow_status(record, status="running", stage="runner", completed=list(_STAGE_EFFECTS)[:5])
    result = adapter.status(running)
    assert result["execution_status"] == "running"
    assert api.calls[-1] == ("creation_workflow_status", "C:\\state\\factory", WORKFLOW)
    api.workflow_state = workflow_status(record, status="succeeded", stage="complete", completed=list(_STAGE_EFFECTS))
    assert adapter.status(running)["execution_status"] == "succeeded"
    assert sum(call[0] == "creation_workflow_start" for call in api.calls) == 1


@pytest.mark.parametrize("kind", ["workflow", "scope", "auth", "partial_success", "order"])
def test_workflow_status_rejects_binding_and_completion_drift(setup, kind):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    store.approve(record)
    api.result = workflow_status(record)
    running = store.execute(record, adapter)
    value = workflow_status(record, status="running")
    if kind == "workflow":
        value["workflow_id"] = CLIENT
    elif kind == "scope":
        value["scope"]["factory_id"] = CLIENT
    elif kind == "auth":
        value["authorization"]["authorization_hash"] = "b" * 64
    elif kind == "partial_success":
        value.update(status="succeeded", is_terminal=True)
    else:
        value["authorization"]["completed_stages"] = ["runner"]
    api.workflow_state = value
    with pytest.raises(ToolError):
        adapter.status(running)


def test_paused_workflow_requires_explicit_claimed_continuation(setup):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    store.approve(record)
    api.result = workflow_status(record)
    running = store.execute(record, adapter)
    api.workflow_state = workflow_status(record, status="awaiting-review", stage="repository-initialization",
                                        completed=["hub-lock-foundation"])
    paused = adapter.status(running)
    assert paused["execution_status"] == "awaiting_continuation" and paused["data"]["continuation"]["automatic_retry_allowed"] is False
    assert not any(call[0] == "creation_workflow_continue" for call in api.calls)
    with pytest.raises(ToolError):
        adapter.continue_operation(running)
    claimed = {**running, "status": "continuing", "observation": paused}
    api.result = workflow_status(record, status="running", stage="repository-initialization", completed=["hub-lock-foundation"])
    continued = adapter.continue_operation(claimed)
    assert continued["execution_status"] == "running"
    assert api.calls[-1] == ("creation_workflow_continue", "C:\\state\\factory", WORKFLOW,
                             record["preview"]["review"]["workflow_authorization"]["authorization_hash"])


@pytest.mark.parametrize("drift", ["invalidated", "unconsumed", "recovery", "new_stage", "backwards", "blocked"])
def test_continuation_never_expands_original_approval_or_retries_recovery(setup, drift):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    store.approve(record)
    api.result = workflow_status(record)
    running = store.execute(record, adapter)
    value = workflow_status(record, status="awaiting-review", stage="repository-initialization", completed=["hub-lock-foundation"])
    api.workflow_state = copy.deepcopy(value)
    prior = adapter.status(running)
    if drift == "invalidated":
        value["authorization"]["invalidated"] = True
    elif drift == "unconsumed":
        value["authorization"]["consumed"] = False
    elif drift == "recovery":
        value["recovery"] = {"new_effects": True}
    elif drift == "new_stage":
        value["stage"] = "network-source-adoption"
    elif drift == "backwards":
        value["authorization"]["completed_stages"] = []
    else:
        value["status"] = "blocked"
    api.workflow_state = value
    with pytest.raises(ToolError):
        adapter.continue_operation({**running, "status": "continuing", "observation": prior})
    assert not any(call[0] == "creation_workflow_continue" for call in api.calls)


def test_status_rejects_mutated_persisted_job_binding(setup):
    adapter, api, store = setup
    record = adapter.prepare(DELETE, {})
    store.approve(record, "DELETE factory-sweden-ai")
    running = store.execute(record, adapter)
    running["outcome"]["data"]["binding"]["folder"] = "C:\\other"
    before = len(api.calls)
    with pytest.raises(ToolError):
        adapter.status(running)
    assert len(api.calls) == before


def paused_workflow(setup):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    store.approve(record)
    api.result = workflow_status(record)
    running = store.execute(record, adapter)
    api.workflow_state = workflow_status(record, status="awaiting-review", stage="repository-initialization",
                                        completed=["hub-lock-foundation"])
    observed = adapter.status(running)
    return {**running, "status": "continuing", "observation": observed}


def test_observations_cannot_regress_beyond_initial_outcome(setup):
    adapter, api, _ = setup
    claimed = paused_workflow(setup)
    api.workflow_state = workflow_status(claimed, status="running")
    with pytest.raises(ToolError, match="backwards"):
        adapter.status(claimed)
    assert claimed["outcome"]["data"]["authorization"]["completed_stages"] == []
    assert claimed["observation"]["data"]["authorization"]["completed_stages"] == ["hub-lock-foundation"]


@pytest.mark.parametrize("mutation", ["approval", "observation", "binding", "advanced_stage", "advanced_history"])
def test_continuation_requires_approved_exact_observed_pause(setup, mutation):
    adapter, api, _ = setup
    claimed = paused_workflow(setup)
    if mutation == "approval":
        claimed["approval"] = None
    elif mutation == "observation":
        claimed["observation"] = None
    elif mutation == "binding":
        claimed["observation"]["data"]["binding"]["id"] = CLIENT
    elif mutation == "advanced_stage":
        api.workflow_state["stage"] = "minimum-foundation"
    else:
        api.workflow_state.update(stage="minimum-foundation")
        api.workflow_state["authorization"]["completed_stages"] += ["repository-initialization"]
    with pytest.raises(ToolError):
        adapter.continue_operation(claimed)
    assert not any(call[0] == "creation_workflow_continue" for call in api.calls)


def test_continuation_response_regression_is_uncertain_not_retryable(setup):
    adapter, api, _ = setup
    claimed = paused_workflow(setup)
    api.result = workflow_status(claimed, status="running")
    with pytest.raises(OperationError) as error:
        adapter.continue_operation(claimed)
    assert error.value.uncertain and error.value.code == "completion_unknown"
    assert sum(call[0] == "creation_workflow_continue" for call in api.calls) == 1


@pytest.mark.parametrize("field,value", [("folder", "C:\\other"), ("factory_id", CLIENT), ("scale_set_id", CLIENT), ("project_id", CLIENT)])
def test_workflow_status_never_uses_changed_server_target(setup, field, value):
    adapter, api, _ = setup
    claimed = paused_workflow(setup)
    adapter.settings = adapter.settings.model_copy(update={"factory": adapter.settings.factory.model_copy(update={field: value})})
    before = len(api.calls)
    with pytest.raises(ToolError, match="binding changed"):
        adapter.status(claimed)
    assert len(api.calls) == before


def test_project_confirmation_cannot_start_an_unreviewed_deployment_job(setup):
    adapter, api, store = setup
    api.catalog["factories"] = [factory_target(existing_project=False)]
    record = adapter.prepare(ADD_PROJECT, {"project_number": "001", "display_name": "Research"})
    store.approve(record)
    api.result = {"contract_version": 1, "catalog": {"factories": [record["preview"]["target"]]},
                  "job": api.job("add-project")}
    with pytest.raises(OperationError) as error:
        store.execute(record, adapter)
    assert error.value.uncertain and error.value.code == "completion_unknown"


@pytest.mark.parametrize("state,uncertain", [("failed", False), ("uncertain", True)])
def test_initial_terminal_failure_never_returns_an_ok_start(setup, state, uncertain):
    adapter, api, store = setup
    record = adapter.prepare(CREATE, {})
    store.approve(record)
    api.result = workflow_status(record, status=state)
    with pytest.raises(OperationError) as error:
        store.execute(record, adapter)
    assert error.value.uncertain is uncertain
    assert sum(call[0] == "creation_workflow_start" for call in api.calls) == 1


def real_store_setup(action_settings, principal):
    grants = [SimpleNamespace(object_id=CALLER, scopes=[SCOPE],
                              permissions=["factory.read", "factory.create", "factory.delete", "project.add"])]
    current = action_settings.model_copy(update={"auth": action_settings.auth.model_copy(update={"grants": grants})})
    store = OperationStore(current, backend=MemoryOperationBackend())
    api = FakeAPI(current)
    return ActionSkills(current, principal, SCOPE, api, store), api, store


def test_real_store_marks_preconfirmation_drift_failed_not_executing(action_settings, principal):
    adapter, api, store = real_store_setup(action_settings, principal)
    record = adapter.prepare(DELETE, {})
    store.approve(principal, record["id"], record["plan_hash"], confirmation_phrase="DELETE factory-sweden-ai")
    api.catalog["revision"] = "b" * 64
    result = store.execute(principal, record["id"], adapter.execute_operation)
    assert result["status"] == "failed"
    assert result["outcome"]["error"]["code"] == "revision_changed"
    assert not any(call[0] == "delete_aifactory_confirm" for call in api.calls)


def test_unconfigured_factory_credential_persists_failed_before_confirmation(action_settings, principal):
    from aifactory_agent.tools import FactoryTools
    adapter, api, store = real_store_setup(action_settings, principal)
    record = adapter.prepare(DELETE, {})
    store.approve(principal, record["id"], record["plan_hash"], confirmation_phrase="DELETE factory-sweden-ai")
    tools = FactoryTools(adapter.settings, principal, SCOPE, operation_store=store, key_provider=lambda: None)
    result = store.execute(principal, record["id"], tools.execute_operation)
    assert result["status"] == "failed"
    assert result["outcome"]["error"]["code"] == "factory_auth_unconfigured"
    assert not any(call[0] == "delete_aifactory_confirm" for call in api.calls)


def test_whole_workflow_verified_restart_boundary_is_continuable(action_settings, principal):
    adapter, api, store = real_store_setup(action_settings, principal)
    record = adapter.prepare(CREATE, {})
    store.approve(principal, record["id"], record["plan_hash"])
    api.result = workflow_status(record)
    running = store.execute(principal, record["id"], adapter.execute_operation)
    boundary = workflow_status(record, status="awaiting-review", stage="hub-lock-foundation",
                               completed=["hub-lock-foundation"])
    boundary["requires_review"] = False
    boundary["execution_diagnostic"] = {
        "contract_version": 1, "stage": "hub-lock-foundation", "phase": "stage-returned",
        "outcome": "verified", "code": "stage-execution-verified", "action": "Verified stage boundary.",
    }
    api.workflow_state = boundary
    paused = store.observe(principal, record["id"], adapter.status)
    assert paused["progress"]["continuation_allowed"]
    api.result = workflow_status(record, status="running", stage="repository-initialization",
                                 completed=["hub-lock-foundation"])
    continued = store.continue_operation(principal, record["id"], record["plan_hash"],
                                         paused["progress"]["observation_hash"], adapter.continue_operation)
    assert continued["status"] == "running"
    assert continued["outcome"] == running["outcome"]
    assert continued["approval"] == running["approval"]
    assert sum(call[0] == "creation_workflow_continue" for call in api.calls) == 1
    with pytest.raises(OperationError):
        store.continue_operation(principal, record["id"], record["plan_hash"],
                                 paused["progress"]["observation_hash"], adapter.continue_operation)


def test_continuation_cannot_use_stale_observation_hash(action_settings, principal):
    adapter, api, store = real_store_setup(action_settings, principal)
    record = adapter.prepare(CREATE, {})
    store.approve(principal, record["id"], record["plan_hash"])
    api.result = workflow_status(record)
    store.execute(principal, record["id"], adapter.execute_operation)
    api.workflow_state = workflow_status(record, status="awaiting-review", stage="repository-initialization",
                                         completed=["hub-lock-foundation"])
    store.observe(principal, record["id"], adapter.status)
    with pytest.raises(OperationError):
        store.continue_operation(principal, record["id"], record["plan_hash"], "0" * 64, adapter.continue_operation)
    assert store.read(principal, record["id"])["status"] == "awaiting_continuation"
    assert not any(call[0] == "creation_workflow_continue" for call in api.calls)


def test_real_store_observations_preserve_original_workflow_binding(action_settings, principal):
    adapter, api, store = real_store_setup(action_settings, principal)
    record = adapter.prepare(CREATE, {})
    store.approve(principal, record["id"], record["plan_hash"])
    api.result = workflow_status(record)
    running = store.execute(principal, record["id"], adapter.execute_operation)
    api.workflow_state = workflow_status(record, status="awaiting-review", stage="repository-initialization",
                                        completed=["hub-lock-foundation"])
    paused = store.observe(principal, record["id"], adapter.status)
    assert paused["status"] == "awaiting_continuation" and paused["outcome"] == running["outcome"]
    assert paused["observation"]["data"]["authorization"]["completed_stages"] == ["hub-lock-foundation"]
    api.workflow_state = workflow_status(record, status="running")
    with pytest.raises(ToolError, match="backwards"):
        store.observe(principal, record["id"], adapter.status)
    assert store.read(principal, record["id"])["observation"] == paused["observation"]
