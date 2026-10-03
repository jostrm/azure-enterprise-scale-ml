import copy
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aifactory_agent.operations import plan_hash
from aifactory_agent.security import Principal
from aifactory_agent.tools import ToolError
from aifactory_agent.workloads import (
    AGENT_CREATE, MODEL_CREATE, WORKLOAD_SKILLS, AdapterPlan, AdapterResult,
    FileSystemTemplateCatalog, ModelArgs, WorkloadAdapter, WorkloadArgs,
    WorkloadProfile, WorkloadRegistry, WorkloadSettings, WorkloadSkills,
    argument_model, package_sources, plan_details, required_permission,
    validate_workload_plan,
)


TENANT = "11111111-1111-4111-8111-111111111111"
SUBSCRIPTION = "22222222-2222-4222-8222-222222222222"
CALLER = "33333333-3333-4333-8333-333333333333"
SCOPE = "project001-dev"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/project001-dev"
PROJECT = GROUP + "/providers/Microsoft.CognitiveServices/accounts/foundry/projects/project001"
WORKSPACE = GROUP + "/providers/Microsoft.MachineLearningServices/workspaces/workspace001"
NOW = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)


class FakeAdapter(WorkloadAdapter):
    def __init__(self, status="running", blockers=()):
        self.state, self.blockers = status, blockers
        self.planned, self.executed, self.observed = [], [], []

    def plan(self, context):
        self.planned.append(context)
        return AdapterPlan(
            effects=("Create only the exact approved workload.",),
            blockers=self.blockers,
            details={"phase": "training_submission" if context.profile.kind == "model" else "version_creation"},
        )

    def execute(self, context, plan):
        self.executed.append((context, plan))
        return AdapterResult(
            self.state, {"phase": plan.details["phase"], "api_key": "never-expose",
                         "type": context.arguments.type, "project_resource_id": context.arguments.project_resource_id},
        )

    def status(self, context, receipt):
        self.observed.append((context, receipt))
        return AdapterResult(self.state, {"phase": "training_submission", "password": "never-expose"})


class Store:
    def __init__(self, settings, principal):
        self.settings, self.principal, self.records = settings, principal, []
        self.ready = 0

    def ensure_ready(self):
        self.ready += 1

    def propose(self, principal, scope_key, tool_name, request, preview):
        validate_workload_plan(self.settings, scope_key, tool_name, request, preview)
        clean, affected = plan_details(self.settings, scope_key, tool_name, request, preview)
        record = {
            "id": str(uuid4()), "correlation_id": str(uuid4()), "tenant_id": principal.tenant_id,
            "object_id": principal.object_id, "scope_key": scope_key,
            "scope": self.settings.scopes[scope_key].model_dump(mode="json"), "tool_name": tool_name,
            "factory_api_url": self.settings.factory.api_url, "request": copy.deepcopy(request),
            "preview": clean, "created_at": NOW.isoformat(), "expires_at": preview["expires_at"],
            "affected_resources": affected, "status": "pending", "approval": None, "outcome": None,
        }
        record["plan_hash"] = plan_hash(record)
        self.records.append(record)
        return copy.deepcopy(record)


def claim(record):
    result = copy.deepcopy(record)
    result["status"] = "executing"
    result["approval"] = {key: result[key] for key in ("tenant_id", "object_id", "plan_hash")}
    result["approval"]["approved_at"] = NOW.isoformat()
    return result


@pytest.fixture
def repo():
    # Test artifacts stay in the project, never the OS temporary directory.
    root = Path(__file__).resolve().parents[1] / (".workload-test-" + uuid4().hex)
    agent = root / "usecase_code" / "40-agent-factory"
    model = root / "usecase_code" / "50-ml-model-factory"
    for path in (agent / "41-single-agent", agent / "42-multi-agent",
                 model / "batch" / "classification", model / "online" / "classification",
                 model / "streaming" / "regression", agent / "agent_factory",
                 model / "ml_model_factory", root / "profiles"):
        path.mkdir(parents=True, exist_ok=True)
        (path / "source.py").write_text("SOURCE = 1\n", encoding="utf-8")
    (agent / "agent_factory" / "__init__.py").write_text("", encoding="utf-8")
    (agent / "agent_factory" / "prompt.py").write_text("PROMPT = 1\n", encoding="utf-8")
    (model / "ml_model_factory" / "__init__.py").write_text("", encoding="utf-8")
    (model / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (root / "profiles" / "agent.json").write_text(json.dumps({
        "tenant_id": TENANT, "subscription_id": SUBSCRIPTION, "resource_group": "project001-dev",
        "common_resource_group": "common", "account_name": "foundry", "project_name": "project001",
        "project_endpoint": "https://foundry.services.ai.azure.com/api/projects/project001",
        "location": "swedencentral", "model_deployment": "approved-gpt",
        "embedding_deployment": "", "search_name": "", "storage_name": "",
        "identity_id": "", "identity_client_id": "",
    }), encoding="utf-8")
    (root / "profiles" / "runtime.json").write_text(json.dumps({
        "subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "resource_group": "project001-dev",
        "workspace_name": "workspace001", "compute": "approved-cpu", "environment": "azureml:approved:1",
        "credential": "managed_identity", "project_number": "001", "environment_name": "dev",
        "input_data": "azureml:approved-data:1",
        "serving": {"instance_type": "Standard_DS3_v2", "instance_count": 1, "batch_instance_count": 1},
        "aifactory": "factory",
    }), encoding="utf-8")
    scenario = model / "scenarios" / "classification.json"
    scenario.parent.mkdir()
    scenario.write_text(json.dumps({
        "name": "titanic", "task": "classification", "target": "label", "features": ["feature"],
        "dataset": {"provider": "lake", "kind": "dataset"},
        "custom": {"algorithm": "logistic_regression"}, "quality": {"min_accuracy": 0.65},
    }), encoding="utf-8")
    try:
        yield root
    finally:
        shutil.rmtree(root)


@pytest.fixture
def configured(repo):
    agent = WorkloadProfile(
        profile_id="approved-prompt", kind="agent", type="41-single-agent", family="prompt",
        project_resource_id=PROJECT, config_path="profiles\\agent.json",
        catalog_selection="approved-reviewer", agent_prefix="approved",
    )
    model = WorkloadProfile(
        profile_id="approved-model", kind="model", type="classification", family="azureml",
        serving_mode="batch", project_resource_id=WORKSPACE, config_path="profiles\\runtime.json",
        scenario_path="usecase_code\\50-ml-model-factory\\scenarios\\classification.json",
        training_mode="custom", output_directory="outputs",
    )
    workloads = WorkloadSettings(repository_root=str(repo), enabled_skills=list(WORKLOAD_SKILLS),
                                 profiles={SCOPE: [agent, model]})

    class Scope(SimpleNamespace):
        def model_dump(self, **kwargs):
            return vars(self).copy()

    scope = Scope(tenant_id=TENANT, subscription_id=SUBSCRIPTION, resource_group="project001-dev",
                  factory="factory", project="001", environment="dev")
    settings = SimpleNamespace(
        workloads=workloads, scopes={SCOPE: scope}, location="swedencentral",
        factory=SimpleNamespace(writes_enabled=True, allowed_write_environments=["dev"],
                                api_url="http://127.0.0.1:8765"),
        auth=SimpleNamespace(grants=[SimpleNamespace(object_id=CALLER, scopes=[SCOPE],
                                                    permissions=["factory.read", "agent.create", "model.create"])]),
    )
    principal = Principal(TENANT, CALLER)
    adapter = FakeAdapter()
    store = Store(settings, principal)
    registry = WorkloadRegistry({"prompt": adapter, "azureml": adapter})
    skills = WorkloadSkills(settings, principal, SCOPE, store, registry=registry, clock=lambda: NOW)
    return settings, principal, adapter, store, skills


def args(name=AGENT_CREATE, target=None):
    values = {"type": "41-single-agent" if name == AGENT_CREATE else "classification",
              "project_resource_id": target or (PROJECT if name == AGENT_CREATE else WORKSPACE)}
    if name == MODEL_CREATE:
        values["serving_mode"] = "batch"
    return values


def test_closed_import_safe_public_contract():
    assert required_permission(AGENT_CREATE) == "agent.create"
    assert required_permission(MODEL_CREATE) == "model.create"
    assert argument_model(AGENT_CREATE) is WorkloadArgs
    assert argument_model(MODEL_CREATE) is ModelArgs
    assert WorkloadSettings().enabled_skills == []
    with pytest.raises(ValidationError):
        WorkloadSettings(unknown=True)
    with pytest.raises(ValidationError):
        WorkloadArgs(**{**args(), "subscription_id": SUBSCRIPTION})
    with pytest.raises(ValidationError):
        ModelArgs(type="classification", project_resource_id=WORKSPACE, serving_mode="all")


@pytest.mark.parametrize("value", ["../41-single-agent", "x\\41-single-agent", "/41-single-agent",
                                  "C:\\types", ".", "..", "classification/online", "x:y", "a%2fb"])
def test_type_cannot_be_a_path(value):
    with pytest.raises(ValidationError):
        WorkloadArgs(type=value, project_resource_id=PROJECT)


@pytest.mark.parametrize("target", [GROUP, PROJECT + "/agents/a", GROUP + "/providers/Microsoft.Storage/storageAccounts/a",
                                   PROJECT + "?secret=a", PROJECT + "/../else"])
def test_agent_arguments_require_real_project_arm_id(target):
    with pytest.raises(ValidationError):
        WorkloadArgs(type="41-single-agent", project_resource_id=target)


def test_discovery_is_actual_immediate_folders_and_mode(configured, repo):
    settings, _, _, _, skills = configured
    root = repo / "usecase_code" / "40-agent-factory"
    (root / "empty").mkdir()
    (root / "docs-only").mkdir()
    (root / "docs-only" / "readme.md").write_text("not deployable", encoding="utf-8")
    catalog = FileSystemTemplateCatalog(settings)
    agent_types = catalog.types("agent")
    assert {record["type"] for record in agent_types} == {"41-single-agent", "42-multi-agent"}
    assert all(record["family"] != record["type"] for record in agent_types)
    model_types = catalog.types("model")
    assert {(record["type"], record["mode"]) for record in model_types} == {
        ("classification", "batch"), ("classification", "online"), ("regression", "streaming"),
    }
    public = skills.templates()
    assert next(record for record in public if record["type"] == "41-single-agent")["available"]
    assert not next(record for record in public if record["type"] == "42-multi-agent")["available"]
    assert "source.py" not in json.dumps(public)


@pytest.mark.parametrize("name", [AGENT_CREATE, MODEL_CREATE])
def test_prepare_and_execute_exact_type_target_without_cloud_constructors(configured, name, monkeypatch):
    settings, principal, adapter, store, skills = configured
    monkeypatch.setattr("aifactory_agent.config.credential", lambda *_: pytest.fail("cloud credential constructed"))
    record = skills.prepare(name, args(name))
    assert store.ready == 1 and record["status"] == "pending"
    assert record["preview"]["expires_at"] == (NOW + timedelta(seconds=900)).isoformat()
    assert record["preview"]["target"]["project_resource_id"] == args(name)["project_resource_id"]
    result = skills.execute_operation(claim(record))
    assert result["ok"] and result["execution_status"] == "running"
    assert adapter.executed[0][0].arguments.model_dump() == args(name)
    assert adapter.executed[0][0].target["resource_group_id"] == GROUP
    assert "never-expose" not in json.dumps(result)
    assert record["request"]["source_artifact_hash"]
    assert any(item["path"].endswith("prompt.py" if name == AGENT_CREATE else "pyproject.toml")
               for item in record["request"]["source_manifest"])


@pytest.mark.parametrize("change", ["target", "type", "mode", "profile", "artifact", "artifact_added", "provider"])
def test_drift_is_rejected_before_write_even_with_rehashed_record(configured, repo, change):
    settings, _, adapter, _, skills = configured
    name = MODEL_CREATE if change == "mode" else AGENT_CREATE
    record = claim(skills.prepare(name, args(name)))
    if change == "target":
        record["request"]["arguments"]["project_resource_id"] = PROJECT.replace("project001", "other")
    elif change == "type":
        record["request"]["arguments"]["type"] = "42-multi-agent"
    elif change == "mode":
        record["request"]["arguments"]["serving_mode"] = "online"
    elif change == "profile":
        profile = settings.workloads.profiles[SCOPE][0]
        settings.workloads.profiles[SCOPE][0] = profile.model_copy(update={"catalog_selection": "different-reviewer"})
    elif change == "provider":
        (repo / "usecase_code" / "40-agent-factory" / "agent_factory" / "prompt.py").write_text("CHANGED=1")
    elif change == "artifact_added":
        (repo / "usecase_code" / "40-agent-factory" / "41-single-agent" / "new.py").write_text("CHANGED=1")
    else:
        (repo / "profiles" / "agent.json").write_text("{}")
    record["plan_hash"] = plan_hash(record)
    record["approval"]["plan_hash"] = record["plan_hash"]
    with pytest.raises((ToolError, ValidationError)):
        skills.execute_operation(record)
    assert not adapter.executed


@pytest.mark.parametrize("gate,code", [
    ("disabled", "skill_disabled"), ("writes", "writes_disabled"), ("environment", "environment_not_enabled"),
    ("profile", "workload_profile_required"), ("unknown", "unsupported_workload_type"),
])
def test_missing_server_configuration_explicitly_blocks(configured, gate, code):
    settings, _, adapter, _, skills = configured
    request = args()
    if gate == "disabled":
        settings.workloads = settings.workloads.model_copy(update={"enabled_skills": []})
    elif gate == "writes":
        settings.factory.writes_enabled = False
    elif gate == "environment":
        settings.factory.allowed_write_environments = []
    elif gate == "profile":
        settings.workloads.profiles[SCOPE].clear()
    else:
        request["type"] = "prompt"
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, request)
    assert exc.value.code == code
    assert not adapter.executed


@pytest.mark.parametrize("permission", ["factory.read", "agent.create"])
def test_current_exact_scoped_permissions_required(configured, permission):
    settings, _, adapter, _, skills = configured
    settings.auth.grants[0].permissions.remove(permission)
    with pytest.raises(PermissionError):
        skills.prepare(AGENT_CREATE, args())
    assert not adapter.planned


@pytest.mark.parametrize("target", [
    PROJECT.replace(SUBSCRIPTION, "44444444-4444-4444-8444-444444444444"),
    PROJECT.replace("resourceGroups/project001-dev", "resourceGroups/else"),
    PROJECT.replace("projects/project001", "projects/other"),
])
def test_arbitrary_valid_arm_target_is_denied(configured, target):
    _, _, adapter, _, skills = configured
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, args(target=target))
    assert exc.value.code == "workload_target_mismatch"
    assert not adapter.planned


def test_workspace_or_exact_configured_rg_only_for_model(configured):
    settings, _, _, _, skills = configured
    with pytest.raises(ToolError):
        skills.prepare(MODEL_CREATE, args(MODEL_CREATE, GROUP))
    profile = settings.workloads.profiles[SCOPE][1]
    settings.workloads.profiles[SCOPE][1] = profile.model_copy(update={"project_resource_id": GROUP})
    assert skills.prepare(MODEL_CREATE, args(MODEL_CREATE, GROUP))["preview"]["target"]["project_resource_id"] == GROUP
    with pytest.raises(ValidationError):
        ModelArgs(type="classification", project_resource_id=PROJECT, serving_mode="batch")


@pytest.mark.parametrize("tamper", ["pending", "approval", "caller", "expiry", "hash"])
def test_persisted_approval_single_use_claim_required(configured, tamper):
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))
    if tamper == "pending":
        record["status"] = "pending"
    elif tamper == "approval":
        record["approval"] = None
    elif tamper == "caller":
        record["object_id"] = TENANT
    elif tamper == "expiry":
        record["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        record["plan_hash"] = plan_hash(record)
        record["approval"]["plan_hash"] = record["plan_hash"]
    else:
        record["request"]["family"] = "hosted"
    with pytest.raises(ToolError):
        skills.execute_operation(record)
    assert not adapter.executed


def test_registries_are_instance_owned(configured):
    settings, principal, original, _, _ = configured
    first = FakeAdapter("succeeded")
    second = FakeAdapter("running")
    left = WorkloadRegistry({"prompt": first})
    right = WorkloadRegistry({"prompt": second})
    assert left.resolve("prompt") is first and right.resolve("prompt") is second
    skills = WorkloadSkills(settings, principal, SCOPE, Store(settings, principal),
                           registry=left, clock=lambda: NOW)
    result = skills.execute_operation(claim(skills.prepare(AGENT_CREATE, args())))
    assert result["execution_status"] == "succeeded"
    assert not second.executed and not original.executed


def test_blocked_adapter_never_proposes_or_writes(configured):
    settings, principal, _, _, _ = configured
    adapter = FakeAdapter(blockers=("dependency_missing",))
    store = Store(settings, principal)
    skills = WorkloadSkills(settings, principal, SCOPE, store,
                           registry=WorkloadRegistry({"prompt": adapter}), clock=lambda: NOW)
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, args())
    assert exc.value.code == "dependency_missing"
    assert not store.records and not adapter.executed


def test_status_is_safe_read_not_a_write_and_preserves_async(configured):
    settings, _, adapter, _, skills = configured
    record = claim(skills.prepare(MODEL_CREATE, args(MODEL_CREATE)))
    record["outcome"] = skills.execute_operation(record)
    record["status"] = "running"
    settings.factory.writes_enabled = False
    result = skills.status(record)
    assert result["ok"] and result["execution_status"] == "running"
    assert len(adapter.executed) == 1 and len(adapter.observed) == 1
    assert "never-expose" not in json.dumps(result)


def test_package_sources_contains_provider_and_all_referenced_configs(configured, repo):
    settings, *_ = configured
    packaged = list(package_sources(settings))
    sources = {Path(local).relative_to(repo).as_posix() for local, _ in packaged if Path(local).is_relative_to(repo)}
    assert "profiles/agent.json" in sources and "profiles/runtime.json" in sources
    assert "usecase_code/40-agent-factory/agent_factory/prompt.py" in sources
    assert "usecase_code/50-ml-model-factory/pyproject.toml" in sources
    assert all(not Path(relative).is_absolute() and ".." not in Path(relative).parts for _, relative in packaged)


def test_symlink_or_junction_escape_is_not_a_template(configured, repo):
    settings, *_ = configured
    root = repo / "usecase_code" / "40-agent-factory"
    try:
        (root / "linked-agent").symlink_to(repo / "profiles", target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links is not permitted on this Windows host.")
    assert "linked-agent" not in {item["type"] for item in FileSystemTemplateCatalog(settings).types("agent")}


def test_bounded_manifest_rejects_oversized_inputs(configured, repo):
    settings, _, adapter, _, skills = configured
    settings.workloads = settings.workloads.model_copy(update={"max_file_bytes": 16})
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, args())
    assert exc.value.code == "source_limit_exceeded"
    assert not adapter.executed


def copy_provider_sources(repo, kind):
    purple = Path(__file__).resolve().parents[4]
    family = "40-agent-factory" if kind == "agent" else "50-ml-model-factory"
    origin, destination = purple / "usecase_code" / family, repo / "usecase_code" / family
    package = "agent_factory" if kind == "agent" else "ml_model_factory"
    shutil.copytree(origin / package, destination / package, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in (("41-single-agent", "42-multi-agent") if kind == "agent" else ("scripts", "environments")):
        shutil.copytree(origin / name, destination / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("requirements.txt", "pyproject.toml"):
        if (origin / name).exists():
            shutil.copy2(origin / name, destination / name)


def default_skills(configured, repo, kind, monkeypatch):
    settings, principal, _, _, _ = configured
    copy_provider_sources(repo, kind)
    registry = WorkloadRegistry()
    family = "prompt" if kind == "agent" else "azureml"
    adapter = registry.resolve(family)
    monkeypatch.setattr(adapter, "_dependencies", lambda *names: None)
    store = Store(settings, principal)
    skills = WorkloadSkills(settings, principal, SCOPE, store, registry=registry, clock=lambda: NOW)
    return settings, adapter, skills


def test_real_prompt_strategy_reuses_one_server_selected_spec_never_routes(configured, repo, monkeypatch):
    settings, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)
    record = skills.prepare(AGENT_CREATE, args())
    observed = []
    client = SimpleNamespace(
        agents=SimpleNamespace(update_details=lambda **_: pytest.fail("unapproved routing")),
        deployments=SimpleNamespace(), close=lambda: None,
    )
    monkeypatch.setattr(adapter, "_client", lambda *args: client)
    execution_context = validate_workload_plan(settings, SCOPE, AGENT_CREATE, record["request"], record["preview"])
    provider = adapter._module(execution_context, "prompt")

    def deploy(project, target, spec, knowledge_tool=None, azure_tool=None):
        observed.append((target.project_id, spec["name"], knowledge_tool, azure_tool))
        project.agents.update_details(agent_name=spec["name"], agent_endpoint=object())
        return {"version": "1", "id": "version-1", "status": "created"}

    monkeypatch.setattr(provider, "deploy_prompt", deploy)
    result = skills.execute_operation(claim(record))
    assert observed == [(PROJECT, "approved-reviewer", None, None)]
    assert result["data"]["routing"] == "not_requested"
    assert result["execution_status"] == "succeeded"


def test_real_azureml_strategy_renders_canonical_pipeline_and_returns_running(configured, repo, monkeypatch):
    # JSON is a YAML subset. Inject only serialization for the optional absent PyYAML
    # dependency; exercise the actual purple renderer without installing anything.
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(
        safe_dump=lambda value, **kwargs: json.dumps(value), safe_load=json.loads,
    ))
    settings, adapter, skills = default_skills(configured, repo, "model", monkeypatch)
    record = skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    context = validate_workload_plan(settings, SCOPE, MODEL_CREATE, record["request"], record["preview"])
    provider = adapter._module(context, "azureml")
    submitted = []

    def submit(path, runtime):
        import yaml
        job = yaml.safe_load(path.read_text(encoding="utf-8"))
        submitted.append((job, runtime))
        return "approved-training-job"

    monkeypatch.setattr(provider, "submit", submit)
    result = skills.execute_operation(claim(record))
    assert result["execution_status"] == "running"
    assert result["data"]["model_created"] is False
    assert result["data"]["registration_status"] == "not_requested"
    assert result["data"]["serving_status"] == "not_requested"
    job, runtime = submitted[0]
    assert set(job["jobs"]) == {"prepare", "train", "evaluate"}
    assert job["tags"]["task_type"] == "classification"
    assert runtime["workspace_name"] == "workspace001"
    assert runtime["resource_group"] == "project001-dev"
    assert result["data"]["job_resource_id"] == WORKSPACE + "/jobs/approved-training-job"
    record["outcome"] = result
    record["status"] = "running"
    monkeypatch.setattr(provider, "_client", lambda runtime: SimpleNamespace(
        jobs=SimpleNamespace(get=lambda name: SimpleNamespace(status="Completed", id=WORKSPACE + "/jobs/" + name)),
    ))
    observation = skills.status(record)
    assert observation["data"]["phase"] == "training_complete"
    assert observation["data"]["model_created"] is False
    assert observation["data"]["registration_status"] == "not_requested"


@pytest.mark.parametrize("change,code", [
    ("compute", "workload_runtime_required"), ("environment", "workload_runtime_required"),
    ("scenario", "workload_selection_invalid"), ("workspace", "workload_target_mismatch"),
    ("credentials", "secret_in_workload_config"),
])
def test_real_model_strategy_unconfigured_inputs_never_submit(configured, repo, monkeypatch, change, code):
    _, adapter, skills = default_skills(configured, repo, "model", monkeypatch)
    path = repo / "profiles" / "runtime.json"
    runtime = json.loads(path.read_text())
    if change == "compute":
        runtime.pop("compute")
    elif change == "environment":
        runtime["environment"] = "azureml:latest"
    elif change == "scenario":
        scenario = repo / "usecase_code" / "50-ml-model-factory" / "scenarios" / "classification.json"
        scenario.write_text(json.dumps({"name": "bad", "task": "regression"}))
    elif change == "workspace":
        runtime["workspace_name"] = "arbitrary"
    else:
        runtime["api_key"] = "no-secret-in-profile"
    path.write_text(json.dumps(runtime))
    with pytest.raises(ToolError) as exc:
        skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    assert exc.value.code == code


def test_default_strategy_missing_dependency_is_structured_not_install_or_success(configured, repo, monkeypatch):
    _, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)
    from aifactory_agent import workloads
    original = workloads.importlib.import_module

    def missing(name):
        if name == "azure.ai.projects.models":
            raise ModuleNotFoundError("absent-sdk")
        return original(name)

    # Restore only the dependency check replaced by the helper.
    from aifactory_agent.workloads import PromptWorkloadAdapter
    monkeypatch.setattr(adapter, "_dependencies", PromptWorkloadAdapter._dependencies)
    monkeypatch.setattr(workloads.importlib, "import_module", missing)
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, args())
    assert exc.value.code == "dependency_missing"


def test_hosted_multiagent_hashes_shared_runtime_sources(configured, repo, monkeypatch):
    settings, principal, _, _, _ = configured
    copy_provider_sources(repo, "agent")
    runtime_path = repo / "profiles" / "hosted.json"
    runtime_path.write_text(json.dumps({
        "cpu": "0.5", "memory": "1Gi", "runtime": "python_3_13", "protocol": "responses/2.0.0",
        "dependency_resolution": "remote_build", "approved_source_upload": True, "timeout_seconds": 900,
    }))
    profile = WorkloadProfile(
        profile_id="approved-team", kind="agent", type="42-multi-agent", family="hosted",
        project_resource_id=PROJECT, config_path="profiles\\agent.json",
        agent_prefix="approved", catalog_selection="approved-helpdesk-team",
        output_directory="outputs", hosted_runtime_path="profiles\\hosted.json",
    )
    settings.workloads.profiles[SCOPE] = [profile]
    registry = WorkloadRegistry()
    monkeypatch.setattr(registry.resolve("hosted"), "_dependencies", lambda *names: None)
    skills = WorkloadSkills(settings, principal, SCOPE, Store(settings, principal),
                           registry=registry, clock=lambda: NOW)
    record = skills.prepare(AGENT_CREATE, {"type": "42-multi-agent", "project_resource_id": PROJECT})
    paths = {item["path"] for item in record["request"]["source_manifest"]}
    assert any(path.endswith("hosted_common.py") for path in paths)
    common = repo / "usecase_code" / "40-agent-factory" / "41-single-agent" / "hosted-agent" / "hosted_common.py"
    common.write_text("# changed shared runtime\n")
    with pytest.raises(ToolError) as exc:
        skills.execute_operation(claim(record))
    assert exc.value.code == "plan_changed"


def test_async_submission_can_never_claim_completed_model(configured):
    settings, principal, _, _, _ = configured
    adapter = FakeAdapter("succeeded")
    skills = WorkloadSkills(settings, principal, SCOPE, Store(settings, principal),
                           registry=WorkloadRegistry({"azureml": adapter}), clock=lambda: NOW)
    with pytest.raises(ToolError) as exc:
        skills.execute_operation(claim(skills.prepare(MODEL_CREATE, args(MODEL_CREATE))))
    assert exc.value.code == "invalid_workload_receipt"


def test_source_manifest_includes_actual_execution_authorization_code(configured):
    _, _, _, _, skills = configured
    manifest = skills.prepare(AGENT_CREATE, args())["request"]["source_manifest"]
    assert any(item["path"].endswith("security.py") for item in manifest)
    assert any(item["path"].endswith("operations.py") for item in manifest)


def test_catalog_availability_exposes_missing_dependency_before_approval(configured, repo, monkeypatch):
    _, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)

    def missing(*names):
        raise ToolError("dependency_missing", "absent", 503)

    monkeypatch.setattr(adapter, "_dependencies", missing)
    template = next(item for item in skills.templates() if item["type"] == "41-single-agent")
    assert template["available"] is False
    assert "dependency_missing" in template["blockers"]


def test_output_directory_cannot_overlap_sources_before_proposal(configured):
    settings, _, adapter, store, skills = configured
    profile = settings.workloads.profiles[SCOPE][1]
    settings.workloads.profiles[SCOPE][1] = profile.model_copy(update={"output_directory": "usecase_code"})
    with pytest.raises(ToolError) as exc:
        skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    assert exc.value.code == "unsafe_source_path"
    assert not store.records and not adapter.planned


def test_injected_junction_attribute_blocks_discovery_and_config_paths(configured, repo, monkeypatch):
    from aifactory_agent import workloads
    settings, _, adapter, _, skills = configured
    original = workloads._linked
    blocked = repo / "usecase_code" / "40-agent-factory" / "41-single-agent"
    monkeypatch.setattr(workloads, "_linked", lambda path: path == blocked or original(path))
    assert "41-single-agent" not in {item["type"] for item in skills.catalog.types("agent")}
    monkeypatch.setattr(workloads, "_linked", lambda path: path == repo / "profiles" or original(path))
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, args())
    assert exc.value.code == "unsafe_source_path"
    assert not adapter.executed


def test_invalid_provider_runtime_has_safe_structured_blocker(configured, repo, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(safe_dump=json.dumps, safe_load=json.loads))
    _, _, skills = default_skills(configured, repo, "model", monkeypatch)
    path = repo / "profiles" / "runtime.json"
    value = json.loads(path.read_text())
    value["project_number"] = "another-project"
    path.write_text(json.dumps(value))
    with pytest.raises(ToolError) as exc:
        skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    assert exc.value.code == "workload_config_invalid"


def test_failed_job_observation_is_successful_read_not_completed_model(configured):
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(MODEL_CREATE, args(MODEL_CREATE)))
    record["outcome"] = skills.execute_operation(record)
    record["status"] = "running"
    adapter.state = "failed"
    result = skills.status(record)
    assert result["ok"] is True and result["execution_status"] == "failed"


def test_provider_transport_error_is_sanitized_uncertain_without_replay(configured):
    from azure.core.exceptions import AzureError
    from aifactory_agent.operations import OperationError
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))

    def failure(context, plan):
        raise AzureError("credential=do-not-expose")

    adapter.execute = failure
    with pytest.raises(OperationError) as exc:
        skills.execute_operation(record)
    assert exc.value.uncertain is True
    assert "do-not-expose" not in str(exc.value)
    assert exc.value.code == "workload_submission_uncertain"


def test_backend_record_cannot_extend_the_review_expiry(configured):
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))
    record["expires_at"] = (NOW + timedelta(hours=1)).isoformat()
    record["plan_hash"] = plan_hash(record)
    record["approval"]["plan_hash"] = record["plan_hash"]
    with pytest.raises(ToolError) as exc:
        skills.execute_operation(record)
    assert exc.value.code == "plan_expired"
    assert not adapter.executed


def test_strategy_replanning_cannot_change_inputs_before_write(configured, repo):
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))
    original = adapter.plan

    def change_source(context):
        plan = original(context)
        (repo / "profiles" / "agent.json").write_text("{}")
        return plan

    adapter.plan = change_source
    with pytest.raises(ToolError) as exc:
        skills.execute_operation(record)
    assert exc.value.code == "plan_changed"
    assert not adapter.executed


@pytest.mark.parametrize("change,code", [
    ("lake", "workload_output_scope_unapproved"), ("latest", "workload_runtime_required"),
])
def test_model_never_guesses_output_scope_or_mutable_environment(configured, repo, monkeypatch, change, code):
    _, _, skills = default_skills(configured, repo, "model", monkeypatch)
    path = repo / "profiles" / "runtime.json"
    runtime = json.loads(path.read_text())
    if change == "lake":
        runtime["lake"] = {"project": "999", "resource_group": "another-project"}
    else:
        runtime["environment"] = "azureml:approved:latest"
    path.write_text(json.dumps(runtime))
    with pytest.raises(ToolError) as exc:
        skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    assert exc.value.code == code


def test_discover_returns_serving_modes_closed_schemas_and_configuration_blockers(configured):
    _, _, _, _, skills = configured
    records = skills.discover()
    agent = next(item for item in records if item["type"] == "41-single-agent")
    assert agent["family"] == "prompt" and agent["serving_mode"] is None
    assert agent["available"] and agent["blockers"] == []
    model = next(item for item in records if item["type"] == "classification" and item["serving_mode"] == "batch")
    assert model["family"] == "azureml" and model["available"]
    unconfigured = next(item for item in records if item["type"] == "classification" and item["serving_mode"] == "online")
    assert not unconfigured["available"] and "workload_profile_required" in unconfigured["blockers"]
    assert agent["arguments_schema"]["additionalProperties"] is False
    assert set(agent["arguments_schema"]["properties"]) == {"type", "project_resource_id"}
    assert set(model["arguments_schema"]["properties"]) == {"type", "project_resource_id", "serving_mode"}


def test_discovery_requires_factory_read_and_uses_injected_catalog(configured):
    settings, principal, _, store, _ = configured

    class TrackingCatalog:
        def __init__(self):
            self.delegate = FileSystemTemplateCatalog(settings)
            self.reads = 0

        def types(self, kind=None, serving_mode=None):
            self.reads += 1
            return self.delegate.types(kind, serving_mode)

        def resolve(self, kind, type, serving_mode=None):
            return self.delegate.resolve(kind, type, serving_mode)

    catalog = TrackingCatalog()
    adapter = FakeAdapter()
    skills = WorkloadSkills(settings, principal, SCOPE, store,
                           registry=WorkloadRegistry({"prompt": adapter, "azureml": adapter}),
                           catalog=catalog, clock=lambda: NOW)
    assert skills.discover() and catalog.reads == 1
    settings.auth.grants[0].permissions.remove("factory.read")
    with pytest.raises(PermissionError):
        skills.discover()
    assert catalog.reads == 1


def test_namespaced_operation_uses_shared_hash_function_and_exact_store_namespace(configured, monkeypatch):
    from aifactory_agent import operations
    _, _, adapter, store, skills = configured
    store.namespace = "agent-one"
    record = claim(skills.prepare(AGENT_CREATE, args()))
    record["agent_namespace"] = store.namespace
    record["plan_hash"] = plan_hash(record)
    record["approval"]["plan_hash"] = record["plan_hash"]
    seen = []
    original = operations.plan_hash

    def shared_hash(value):
        seen.append(value.get("agent_namespace"))
        return original(value)

    monkeypatch.setattr(operations, "plan_hash", shared_hash)
    assert skills.execute_operation(record)["ok"]
    assert seen == ["agent-one"]
    record["agent_namespace"] = "agent-two"
    record["plan_hash"] = original(record)
    record["approval"]["plan_hash"] = record["plan_hash"]
    with pytest.raises(ToolError) as exc:
        skills.execute_operation(record)
    assert exc.value.code == "invalid_execution"
    assert len(adapter.executed) == 1


def test_pure_workload_paths_never_construct_factory_api_client_or_require_api_key(configured, monkeypatch):
    import azurefactory.client
    settings, _, _, _, skills = configured
    settings.factory.api_key_secret_url = None

    def forbidden(*args, **kwargs):
        pytest.fail("Pure purple workload integration constructed a Factory API client.")

    monkeypatch.setattr(azurefactory.client, "AzureFactoryClient", forbidden)
    record = claim(skills.prepare(AGENT_CREATE, args()))
    assert skills.discover()
    record["outcome"] = skills.execute_operation(record)
    record["status"] = "running"
    assert skills.status(record)["ok"]


def test_packaging_is_profile_bounded_without_agent_recursion_private_or_generated_inputs(configured, repo):
    settings, *_ = configured
    agent = repo / "usecase_code" / "40-agent-factory"
    current = agent / "40-aifactory-agent"
    (current / ".venv").mkdir(parents=True)
    (current / "app.py").write_text("APP = 1")
    (current / ".venv" / "do-not-bundle.py").write_text("PRIVATE = 1")
    template = agent / "41-single-agent"
    (template / "private.json").write_text('{"api_key":"private-value"}')
    (template / ".env").write_text("PRIVATE=private-value")
    (template / "training-data.csv").write_text("private-value")
    (template / "generated").mkdir()
    (template / "generated" / "do-not-bundle.py").write_text("PRIVATE = 1")
    packaged = list(package_sources(settings))
    destinations = [str(relative).replace("\\", "/") for _, relative in packaged]
    assert destinations and all(path.startswith("workload_sources/") for path in destinations)
    assert not any("aifactory_agent/" in path or "azurefactory/" in path for path in destinations)
    assert not any("40-aifactory-agent/" in path or ".venv/" in path or "generated/" in path for path in destinations)
    assert not any(path.endswith(("private.json", ".env", ".csv")) for path in destinations)
    assert not any("42-multi-agent/" in path or "/online/" in path for path in destinations)
    assert "40-aifactory-agent" not in {
        item["type"] for item in FileSystemTemplateCatalog(settings).types("agent")
    }


def test_packaged_immediate_types_are_discoverable_with_only_approved_family_present(configured, repo):
    settings, *_ = configured
    settings.workloads.profiles[SCOPE] = [settings.workloads.profiles[SCOPE][0]]
    output = repo / "bundle"
    for local, relative in package_sources(settings):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, destination)
    settings.workloads = settings.workloads.model_copy(update={
        "repository_root": str(output / "workload_sources"),
    })
    discovered = FileSystemTemplateCatalog(settings).types()
    assert [(item["kind"], item["type"]) for item in discovered] == [("agent", "41-single-agent")]


def test_packaging_never_copies_credentials_from_explicit_profile_configs(configured, repo):
    settings, *_ = configured
    (repo / "profiles" / "agent.json").write_text('{"api_key":"private-value"}')
    with pytest.raises(ToolError) as exc:
        list(package_sources(settings))
    assert exc.value.code == "secret_in_workload_config"


@pytest.mark.parametrize("material", [
    {"connection_string": "DefaultEndpointsProtocol=https;AccountName=account;AccountKey=private-value"},
    {"connectionString": "AccountKey=private-value"},
    {"account_key": "private-value"},
    {"nested": {"storage": {"shared_access_key": "private-value"}}},
    {"nested": [{"client_secret": "private-value"}]},
    {"image_base_uri": "https://account.blob.core.windows.net/data?sv=2026&sig=private-value"},
    {"image_base_uri": "https://account.blob.core.windows.net/data?%73%69%67=private-value"},
    {"notes": "Use AccountKey=private-value;EndpointSuffix=core.windows.net"},
    {"endpoint": "https://user:private-value@example.test/data"},
    {"source_url": "https://example.test/object?X-Amz-Signature=private-value"},
    {"authorization": "Bearer private-value"},
    {"credential": {"account_key": "private-value"}},
])
def test_recursive_credentials_are_blocked_before_packaging_or_provider_reads(configured, repo, material):
    settings, _, adapter, _, skills = configured
    path = repo / "profiles" / "agent.json"
    value = json.loads(path.read_text())
    value.update(material)
    path.write_text(json.dumps(value))
    with pytest.raises(ToolError) as prepare:
        skills.prepare(AGENT_CREATE, args())
    assert prepare.value.code == "secret_in_workload_config"
    assert prepare.value.status_code == 503 and "private-value" not in str(prepare.value)
    assert not adapter.planned
    with pytest.raises(ToolError) as packaged:
        list(package_sources(settings))
    assert packaged.value.code == "secret_in_workload_config"


def test_nonsecret_tenant_identity_and_client_resource_ids_remain_allowed(configured, repo):
    _, _, _, _, skills = configured
    path = repo / "profiles" / "agent.json"
    value = json.loads(path.read_text())
    value["identity_id"] = GROUP + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/approved"
    value["identity_client_id"] = CALLER
    path.write_text(json.dumps(value))
    assert skills.prepare(AGENT_CREATE, args())["status"] == "pending"


def test_private_ancestor_filter_is_identical_for_snapshot_and_packaging(configured, repo):
    settings, _, _, _, skills = configured
    package = repo / "usecase_code" / "40-agent-factory" / "agent_factory"
    for relative in ("private\\customer.py", "secrets\\values.json", "credentials\\config.yml",
                     "nested\\private-assets\\customer.py", ".env.production", "training-data.csv"):
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"customer":"private-value"}' if path.suffix == ".json" else "PRIVATE = 'private-value'")
    record = skills.prepare(AGENT_CREATE, args())
    artifact_paths = [item["path"].replace("\\", "/") for item in record["request"]["source_manifest"]]
    packaged_paths = [str(relative).replace("\\", "/") for _, relative in package_sources(settings)]
    for paths in (artifact_paths, packaged_paths):
        assert not any("/private/" in path or "/secrets/" in path or "/credentials/" in path
                       or "/private-assets/" in path or path.endswith((".env.production", ".csv")) for path in paths)


def test_actual_aml_renderer_uses_only_immutable_staged_approved_sources(configured, repo, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(
        safe_dump=lambda value, **kwargs: json.dumps(value), safe_load=json.loads,
    ))
    settings, adapter, skills = default_skills(configured, repo, "model", monkeypatch)
    source = repo / "usecase_code" / "50-ml-model-factory"
    package = source / "ml_model_factory"
    for relative in (".env.production", "private.json", "training-data.csv", ".git\\config",
                     "generated\\extra.py", "outputs\\extra.py", "private\\customer.py",
                     "secrets\\values.json", "credentials\\config.yml"):
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private-value")
    original_code = (package / "training.py").read_bytes()
    record = skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    context = validate_workload_plan(settings, SCOPE, MODEL_CREATE, record["request"], record["preview"])
    provider = adapter._module(context, "azureml")
    render = provider.render
    staged = []
    submitted = []

    def render_from_approved_bytes(scenario, runtime, output, staged_source, mode):
        assert staged_source.resolve() != source.resolve()
        assert (staged_source / "ml_model_factory" / "training.py").read_bytes() == original_code
        assert not any("private-value" in path.read_text(errors="ignore")
                       for path in staged_source.rglob("*") if path.is_file())
        staged.append(staged_source)
        # A checkout change after capture cannot alter rendered/uploaded approved bytes.
        (package / "training.py").write_text("UNAPPROVED_CHECKOUT_CHANGE = 1")
        return render(scenario, runtime, output, staged_source, mode=mode)

    def submit(path, runtime):
        code = path.parent / "code"
        assert (code / "ml_model_factory" / "training.py").read_bytes() == original_code
        assert not any("private-value" in item.read_text(errors="ignore")
                       for item in code.rglob("*") if item.is_file())
        submitted.append(path)
        return "approved-training-job"

    monkeypatch.setattr(provider, "render", render_from_approved_bytes)
    monkeypatch.setattr(provider, "submit", submit)
    result = skills.execute_operation(claim(record))
    assert result["execution_status"] == "running" and len(submitted) == 1
    assert result["data"]["uploaded_source_artifact_hash"] == record["request"]["source_artifact_hash"]
    assert result["data"]["code_bundle_hash"]
    assert staged and all(not path.exists() for path in staged)
    assert all(not path.exists() for path in submitted)


@pytest.mark.parametrize("tamper", ["extra", "changed", "code_path"])
def test_rendered_upload_must_exactly_match_approved_code_before_submit(configured, repo, monkeypatch, tamper):
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(
        safe_dump=lambda value, **kwargs: json.dumps(value), safe_load=json.loads,
    ))
    settings, adapter, skills = default_skills(configured, repo, "model", monkeypatch)
    record = skills.prepare(MODEL_CREATE, args(MODEL_CREATE))
    context = validate_workload_plan(settings, SCOPE, MODEL_CREATE, record["request"], record["preview"])
    provider = adapter._module(context, "azureml")
    render = provider.render
    work = []

    def corrupt(scenario, runtime, output, source, mode):
        files = render(scenario, runtime, output, source, mode=mode)
        work.append(output)
        if tamper == "extra":
            (output / "code" / ".env.production").write_text("PRIVATE = 1")
        elif tamper == "changed":
            path = output / "code" / "ml_model_factory" / "training.py"
            path.chmod(0o600)
            path.write_text("UNAPPROVED = 1")
        else:
            path = Path(files["pipeline_job"])
            job = json.loads(path.read_text())
            job["jobs"]["prepare"]["code"] = str(repo)
            path.write_text(json.dumps(job))
        return files

    monkeypatch.setattr(provider, "render", corrupt)
    monkeypatch.setattr(provider, "submit", lambda *_: pytest.fail("Unapproved bundle reached SDK submission."))
    with pytest.raises(ToolError) as exc:
        skills.execute_operation(claim(record))
    assert exc.value.code == "invalid_workload_bundle"
    assert work and all(not path.exists() for path in work)


def test_duplicate_json_fields_cannot_hide_credentials_in_packaged_bytes(configured, repo):
    settings, *_ = configured
    path = repo / "profiles" / "agent.json"
    body = path.read_text()
    path.write_text(body[:-1] + ', "notes":"AccountKey=private-value", "notes":"clean"}')
    with pytest.raises(ToolError) as exc:
        list(package_sources(settings))
    assert exc.value.code == "workload_config_invalid"
    assert "private-value" not in str(exc.value)


@pytest.mark.parametrize("material", [
    "account_key: private-value\n", "connection_string: AccountKey=private-value\n",
    "image_base_uri: https://account.blob.core.windows.net/data?sig=private-value\n",
])
def test_yaml_config_sources_cannot_bypass_recursive_credential_policy(configured, repo, material):
    settings, *_ = configured
    path = repo / "usecase_code" / "40-agent-factory" / "agent_factory" / "settings.yml"
    path.write_text(material)
    with pytest.raises(ToolError) as exc:
        list(package_sources(settings))
    assert exc.value.code == "secret_in_workload_config"


def test_approved_vision_renderer_normalization_is_verified_without_false_drift(configured, repo, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(
        safe_dump=lambda value, **kwargs: json.dumps(value), safe_load=json.loads,
    ))
    settings, adapter, skills = default_skills(configured, repo, "model", monkeypatch)
    source = repo / "usecase_code" / "50-ml-model-factory"
    template = source / "batch" / "computer-vision"
    template.mkdir()
    (template / "source.py").write_text("SOURCE = 1")
    scenario = source / "scenarios" / "image.json"
    scenario.write_text(json.dumps({
        "name": "approved-image", "task": "image_classification",
        "dataset": {"provider": "lake", "kind": "dataset"},
        "vision": {"device": "cpu", "image_size": 64, "epochs": 1},
        "quality": {"min_accuracy": 0.5},
    }))
    profile = settings.workloads.profiles[SCOPE][1]
    settings.workloads.profiles[SCOPE][1] = profile.model_copy(update={
        "type": "computer-vision", "scenario_path": str(scenario.relative_to(repo)),
    })
    request = {**args(MODEL_CREATE), "type": "computer-vision"}
    record = skills.prepare(MODEL_CREATE, request)
    context = validate_workload_plan(settings, SCOPE, MODEL_CREATE, record["request"], record["preview"])
    provider = adapter._module(context, "azureml")

    def submit(path, runtime):
        assert json.loads((path.parent / "code" / "scenario.json").read_text())["target"] == "label"
        return "approved-image-job"

    monkeypatch.setattr(provider, "submit", submit)
    assert skills.execute_operation(claim(record))["execution_status"] == "running"


def test_workload_provider_does_not_mix_preloaded_shared_factory_modules(configured, repo, monkeypatch):
    settings, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)
    shared = repo / "shared" / "agent_factory"
    shared.mkdir(parents=True)
    approved = repo / "usecase_code" / "40-agent-factory" / "agent_factory" / "prompt.py"
    (shared / "prompt.py").write_bytes(approved.read_bytes())
    public = ModuleType("agent_factory")
    public.__path__ = [str(shared)]
    prompt = ModuleType("agent_factory.prompt")
    prompt.__file__ = str(shared / "prompt.py")
    prompt.deploy_prompt = lambda *_: pytest.fail("A workload mixed shared provider source.")
    monkeypatch.setitem(sys.modules, "agent_factory", public)
    monkeypatch.setitem(sys.modules, "agent_factory.prompt", prompt)
    before = list(sys.path)
    record = skills.prepare(AGENT_CREATE, args())
    context = validate_workload_plan(settings, SCOPE, AGENT_CREATE, record["request"], record["preview"])
    loaded = adapter._module(context, "prompt")
    assert Path(loaded.__file__) == repo / "usecase_code" / "40-agent-factory" / "agent_factory" / "prompt.py"
    assert loaded is not prompt and loaded.__name__.startswith("_aifactory_workload_")
    assert sys.path == before


@pytest.mark.parametrize("tamper", ["origin", "fingerprint", "package_path"])
def test_provider_cache_is_verified_against_approved_origin_and_source_hash(configured, repo, monkeypatch, tamper):
    settings, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)
    record = skills.prepare(AGENT_CREATE, args())
    context = validate_workload_plan(settings, SCOPE, AGENT_CREATE, record["request"], record["preview"])
    loaded = adapter._module(context, "prompt")
    if tamper == "origin":
        shared = repo / "shared" / "prompt.py"
        shared.parent.mkdir()
        shared.write_bytes(Path(loaded.__file__).read_bytes())
        monkeypatch.setattr(loaded, "__file__", str(shared))
    elif tamper == "fingerprint":
        monkeypatch.setattr(loaded, "__workload_source_sha256__", "0" * 64, raising=False)
    else:
        monkeypatch.setattr(sys.modules[loaded.__package__], "__path__", [str(repo / "shared")])
    with pytest.raises(ToolError) as exc:
        adapter._module(context, "prompt")
    assert exc.value.code == "workload_provider_source_mismatch"
    assert exc.value.status_code == 503


def test_provider_code_is_compiled_from_verified_immutable_source_not_late_file_reads(configured, repo, monkeypatch):
    settings, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)
    record = skills.prepare(AGENT_CREATE, args())
    context = validate_workload_plan(settings, SCOPE, AGENT_CREATE, record["request"], record["preview"])
    loaded = adapter._module(context, "prompt")
    expected = next(item["sha256"] for item in context.source_manifest if item["path"].endswith("agent_factory\\prompt.py"))
    assert loaded.__workload_source_sha256__ == expected
    assert loaded.__loader__.source_sha256 == expected


def test_distinct_public_provider_source_version_blocks_without_swapping_modules(configured, repo, monkeypatch):
    _, adapter, skills = default_skills(configured, repo, "agent", monkeypatch)
    shared = repo / "shared" / "agent_factory"
    shared.mkdir(parents=True)
    (shared / "catalog.py").write_text("DISTINCT_SOURCE_VERSION = 1")
    public = ModuleType("agent_factory")
    public.__path__ = [str(shared)]
    catalog = ModuleType("agent_factory.catalog")
    catalog.__file__ = str(shared / "catalog.py")
    monkeypatch.setitem(sys.modules, "agent_factory", public)
    monkeypatch.setitem(sys.modules, "agent_factory.catalog", catalog)
    before = list(sys.path)
    with pytest.raises(ToolError) as exc:
        skills.prepare(AGENT_CREATE, args())
    assert exc.value.code == "workload_provider_source_mismatch"
    assert exc.value.status_code == 503
    assert sys.modules["agent_factory"] is public and sys.modules["agent_factory.catalog"] is catalog
    assert sys.path == before and adapter._modules == {}


@pytest.mark.parametrize("receipt", ["untyped", "unsupported_status", "changed_target", "changed_type",
                                    "value_error", "type_error", "key_error", "attribute_error"])
def test_accepted_write_with_unknown_or_malformed_receipt_is_uncertain_never_success(configured, receipt):
    from aifactory_agent.operations import OperationError
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))
    accepted = []

    def execute(context, plan):
        accepted.append(context.arguments.project_resource_id)
        if receipt == "untyped":
            return {"ok": True, "execution_status": "succeeded"}
        if receipt == "unsupported_status":
            return AdapterResult("unsupported", {})
        if receipt == "changed_target":
            return AdapterResult("running", {"project_resource_id": PROJECT.replace("projects/project001", "projects/other")})
        if receipt == "changed_type":
            return AdapterResult("running", {"type": "42-multi-agent"})
        error = {"value_error": ValueError, "type_error": TypeError,
                 "key_error": KeyError, "attribute_error": AttributeError}[receipt]
        raise error("accepted-job-private-value")

    adapter.execute = execute
    with pytest.raises(OperationError) as exc:
        skills.execute_operation(record)
    assert exc.value.uncertain is True
    assert "accepted-job-private-value" not in str(exc.value)
    assert accepted == [PROJECT]


def test_known_prevalidation_failure_stays_failed_without_provider_invocation(configured):
    from aifactory_agent.operations import OperationError
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))

    def plan(context):
        raise ToolError("dependency_missing", "A known prevalidation blocker.", 503)

    adapter.plan = plan
    with pytest.raises(OperationError) as exc:
        skills.execute_operation(record)
    assert exc.value.uncertain is False and exc.value.code == "dependency_missing"
    assert not adapter.executed


@pytest.mark.parametrize("failure", ["typed_result", "operation_error"])
def test_confirmed_provider_failure_is_not_reclassified_as_uncertain(configured, failure):
    from aifactory_agent.operations import OperationError
    _, _, adapter, _, skills = configured
    record = claim(skills.prepare(AGENT_CREATE, args()))

    def execute(context, plan):
        if failure == "typed_result":
            return AdapterResult("failed", {"provider_status": "failed"})
        raise OperationError("confirmed_provider_failure", "The provider confirmed failure.", 502, uncertain=False)

    adapter.execute = execute
    with pytest.raises(OperationError) as exc:
        skills.execute_operation(record)
    assert exc.value.uncertain is False
