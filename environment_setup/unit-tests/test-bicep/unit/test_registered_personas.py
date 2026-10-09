"""Registered bootstrap/worker persona integration; all transports are fakes."""
import copy
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
import registered_creation
import registered_personas as core
import aifactory_scaleset_config as serializer
sys.path.insert(0, str(ROOT / "environment_setup" / "aifactory" / "bicep"))
from personas import pipeline
from .test_registered_prerequisites import workspace, dns_arguments, core as prerequisites

TENANT = "22222222-2222-4222-8222-222222222222"
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"


def inputs(environment="dev"):
    return {"persona_access_mode": "groups-v1", "persona_access_manifest": "access/personas.json",
            "tenantId": TENANT, environment + "_sub_id": SUBSCRIPTION,
            "admin_aifactoryPrefixRG": "acme-", "admin_aifactorySuffixRG": "-001",
            "admin_locationSuffix": "weu", "project_number_000": "001"}


def manifest_file(root, values, environment="dev"):
    scopes = pipeline.deployment_scopes(values, environment)
    manifest = {
        "schema": "aifactory.persona-access/v1", "tenant_id": TENANT, "factory": "acme",
        "scaleset": "001", "environment": environment, "project": "project001",
        "seeding": {"subscription_id": SUBSCRIPTION, "resource_group": "seed-rg", "vault_name": "seed-vault"},
        "common_scope": scopes["common"], "project_scope": scopes["project"],
        "log_analytics_resource_id": scopes["common"] + "/providers/Microsoft.OperationalInsights/workspaces/common-log",
        "lake": {"tenant_id": TENANT, "subscription_id": SUBSCRIPTION,
                 "resource_group": scopes["common"].split("/")[-1],
                 "storage_account": "isolatedlake", "filesystem": "lake3",
                 "project": "project001", "environment": environment},
    }
    path = root / "access" / "personas.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(manifest))
    return manifest


def deployment(tmp_path, environment="dev"):
    values = inputs(environment)
    manifest = manifest_file(tmp_path, values, environment)
    scopes = pipeline.deployment_scopes(values, environment)
    document = {
        "config": {"dev": values}, "operation": "deploy-project",
        "target": {"environment": environment, "tenant_id": TENANT, "subscription_id": SUBSCRIPTION,
                   "prefix": "acme-", "suffix": "001", "project_ids": ["001"]},
        "locks": {"scopes": [scopes["project"]], "common_dependencies": [scopes["common"]]},
        "route": {"kind": "gha", "repository": "https://github.com/org/repo", "commit": "a" * 40},
        "deployment": {"steps": [
            {"template": "project.bicep", "parameters": {
                "technicalAdminsObjectID": "legacy", "technicalAdminsEmail": "old@example.test",
                "projectMembers": ["old"], "locationSuffix": "weu", "tags": {"owner": "kept"}}},
            {"template": "esml-genai-1/08b-rbac-common-rg.bicep",
             "parameters": {"personaAccessMode": "legacy", "technicalContactId": "legacy"}}]},
    }
    return document, manifest


@pytest.fixture
def offline(monkeypatch):
    seed = Mock(return_value={"persona" + str(x): str(x) for x in (200, 201, *range(210, 217))})
    access = Mock(return_value={"state": "preview", "blockers": []})
    cli = Mock(return_value=False)
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", seed)
    monkeypatch.setattr(pipeline.access, "provision", access)
    monkeypatch.setattr(pipeline, "azure_cli", cli)
    return seed, access, cli


def test_registered_freeze_consumes_seeds_before_sanitizing_and_freezes_policy(tmp_path, monkeypatch, offline):
    document, manifest = deployment(tmp_path)
    original = copy.deepcopy(document["config"])
    monkeypatch.setattr(core, "remote_manifest", Mock(return_value=manifest))
    core.freeze(Mock(), document, document["deployment"], ROOT)
    assert document["config"] == original
    frozen = document["deployment"]["persona_access"]
    assert frozen["manifest"]["project"] == "project001" and frozen["path"] == "access/personas.json"
    assert offline[0].call_args.args[1] == "project"
    offline[1].assert_not_called()
    parameters = document["deployment"]["steps"][0]["parameters"]
    assert parameters["technicalAdminsObjectID"] == parameters["technicalAdminsEmail"] == ""
    assert parameters["projectMembers"] == []
    assert parameters["tags"] == {"owner": "kept", core.MARKER: "groups-v1"}
    assert document["deployment"]["steps"][1]["parameters"]["personaAccessMode"] == "groups-v1"
    core.worker(document, ROOT, cli=offline[2])
    core.worker(document, ROOT, execute=True, cli=offline[2])
    assert [call.kwargs["scope"] for call in offline[1].call_args_list] == ["common", "project"]
    assert all(call.kwargs["execute"] for call in offline[1].call_args_list)


def test_registered_existing_project_blocked_before_parameters_change(tmp_path, monkeypatch, offline):
    document, manifest = deployment(tmp_path)
    original = copy.deepcopy(document)
    monkeypatch.setattr(core, "remote_manifest", Mock(return_value=manifest))
    offline[2].side_effect = [True, {"tags": {}}, True, {"tags": {}}]
    offline[1].return_value = {"state": "blocked", "blockers": ["legacy vault policy"]}
    with pytest.raises(ValueError, match="before deployment"):
        core.freeze(Mock(), document, document["deployment"], ROOT)
    assert document == original
    assert offline[1].call_args.kwargs["execute"] is False


def test_registered_connectivity_grants_require_their_own_scope_lock(tmp_path, monkeypatch, offline):
    document, manifest = deployment(tmp_path)
    manifest["connectivity_scopes"] = [f"/subscriptions/{SUBSCRIPTION}/resourceGroups/connectivity"]
    monkeypatch.setattr(core, "remote_manifest", Mock(return_value=manifest))
    with pytest.raises(ValueError, match="connectivity grants"):
        core.freeze(Mock(), document, document["deployment"], ROOT)
    offline[0].assert_not_called()
    offline[1].assert_not_called()


@pytest.mark.parametrize("change", ["mode", "parameters", "path", "scope"])
def test_worker_rejects_missing_or_changed_frozen_policy(tmp_path, monkeypatch, offline, change):
    document, manifest = deployment(tmp_path)
    monkeypatch.setattr(core, "remote_manifest", Mock(return_value=manifest))
    core.freeze(Mock(), document, document["deployment"], ROOT)
    if change == "mode":
        document["config"]["dev"]["persona_access_mode"] = "legacy"
    elif change == "parameters":
        document["deployment"]["steps"][0]["parameters"]["projectMembers"] = ["legacy"]
    elif change == "path":
        document["config"]["dev"]["persona_access_manifest"] = "other.json"
    else:
        document["locks"]["common_dependencies"] = []
    with pytest.raises(ValueError):
        core.worker(document, ROOT, execute=True, cli=offline[2])
    offline[1].assert_not_called()


def test_registered_creation_forwards_opt_in_without_team_prompts(tmp_path, monkeypatch, offline):
    manifest_file(tmp_path, inputs())
    monkeypatch.setattr(registered_creation.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("No human group prompt in groups-v1"))
    args = registered_creation.parser().parse_args(["gha"])
    request = registered_creation.creation_input(args, tmp_path, "main", {
        "AIF_TENANT_ID": TENANT, "AIF_DEV_SUBSCRIPTION_ID": SUBSCRIPTION,
        "AIF_PREFIX": "acme-", "AIF_LOCATION": "westeurope", "GITHUB_REPOSITORY": "org/repo",
        "AIF_PERSONA_ACCESS_MODE": "groups-v1", "AIF_PERSONA_ACCESS_MANIFEST": "access\\personas.json",
        "AIF_TEAM_GROUP_ID": "must-not-be-forwarded",
    })
    assert request["config"]["persona_access_manifest"] == "access/personas.json"
    assert all(request["config"][key] == "" for key in ("team_group_id", "team_member_email", "team_group_name"))
    offline[0].assert_not_called()  # Configure-input validation is offline.


@pytest.mark.parametrize("environment,expected", [("dev", "dev"), ("stage", "test"), ("test", "test"), ("prod", "prod")])
def test_exact_config_selection_and_serialization(tmp_path, environment, expected):
    document = {"dev": {"persona_access_mode": "groups-v1", "persona_access_manifest": "dev.json"},
                "stage_prod": {"shared": "kept"},
                "test": {"persona_access_manifest": "test.json"},
                "prod": {"persona_access_manifest": "prod.json"}}
    active, template = tmp_path / "active.json", tmp_path / "template.json"
    active.write_text(json.dumps(document))
    template.write_text(json.dumps({"dev": {"new": 1}, "stage_prod": {"other": 2}}))
    serializer.merge_json_template(template, active)
    serializer.update_json(active, {"project_number_000": "001"})
    result = json.loads(active.read_text())
    selected = core.selected_config(result, environment)
    assert selected["persona_access_manifest"] == expected + ".json"
    assert result["test"] == document["test"] and result["prod"] == document["prod"]


def test_remote_manifest_is_bound_to_reviewed_commit(tmp_path):
    document, manifest = deployment(tmp_path)
    import base64
    cloud = Mock()
    cloud.command.return_value = json.dumps({
        "type": "file", "encoding": "base64", "content": base64.b64encode(json.dumps(manifest).encode()).decode()})
    assert core.remote_manifest(cloud, document["route"], inputs()) == manifest
    assert cloud.command.call_args.args[0][-1].endswith("?ref=" + "a" * 40)


@pytest.mark.parametrize("path", ["", "../manifest.json", "/manifest.json", "C:\\manifest.json"])
def test_registered_relative_path_rejects_unsafe_paths(path):
    with pytest.raises(ValueError, match="repository-relative"):
        core.relative_manifest({"persona_access_manifest": path})


def test_legacy_worker_does_not_import_or_call_persona_engine(monkeypatch):
    monkeypatch.setattr(core, "pipeline_module", Mock(side_effect=AssertionError("legacy engine call")))
    document = {"config": {}, "target": {"environment": "dev"}, "deployment": {}}
    assert core.worker(document, ROOT) is None
    assert core.worker(document, ROOT, execute=True) is None


def test_registered_prerequisites_use_nine_seeds_and_never_graph(workspace, monkeypatch, offline):
    args, runtime, _, _ = dns_arguments(workspace)
    context = args["context"]
    target, _ = prerequisites._read_target(workspace[0], args["scope"])
    values = {**inputs(), "tenantId": target["tenant_id"], "dev_sub_id": target["subscription_id"],
              "admin_aifactoryPrefixRG": target["prefix"], "admin_locationSuffix": context["location_short"]}
    manifest = manifest_file(workspace[0], values)
    manifest["tenant_id"] = target["tenant_id"]
    manifest["seeding"]["subscription_id"] = target["subscription_id"]
    manifest["lake"].update(tenant_id=target["tenant_id"], subscription_id=target["subscription_id"])
    (workspace[0] / "access" / "personas.json").write_text(json.dumps(manifest))
    args["bootstrap_config"].update(persona_access_mode="groups-v1", persona_access_manifest="access/personas.json")
    monkeypatch.setattr(core, "pipeline_module", lambda *args: pipeline)
    runtime.graph = Mock(side_effect=AssertionError("groups-v1 must never call Graph"))
    runtime.persona_cli = offline[2]
    plan = prerequisites.prepare(**args, runtime=runtime)
    assert plan["can_execute"]
    assert len(plan["bindings"]["persona_groups"]) == 9
    assert plan["bindings"]["team_group_id"] is None
    assert len(plan["bindings"]["persona_manifest_sha256"]) == 64
    assert not any(row["service"] == "graph" for row in plan["auth_scopes"])
    assert not any("/groups/" in scope for scope in plan["lock_scopes"])
    assert not runtime.writes
    runtime.graph.assert_not_called()


def test_creation_refuses_api_that_cannot_preserve_persona_settings(tmp_path, monkeypatch, offline):
    manifest_file(tmp_path, inputs())
    request = {"config": {"persona_access_mode": "groups-v1", "persona_access_manifest": "access/personas.json"}}
    monkeypatch.setattr(registered_creation, "creation_input", lambda *args: request)
    client = Mock()
    client.request.return_value = {"operation_mode": "configuration", "capabilities": ["initial-project-v1"]}
    write_receipt = Mock()
    monkeypatch.setattr(registered_creation, "load_sdk", lambda: (lambda: client, write_receipt))
    monkeypatch.delenv("AIF_DRY_RUN", raising=False)
    args = registered_creation.parser().parse_args(["gha", "--save-receipt", str(tmp_path / "review.json")])
    with pytest.raises(ValueError, match="persona-groups-v1"):
        registered_creation.prepare(args, tmp_path, "main")
    assert len(offline[0].call_args_list) == 1
    write_receipt.assert_not_called()


def test_project_adapter_uses_exact_test_manifest_without_dev_identity_fallback():
    import project_deployment
    identity = {"tenantId": TENANT, "test_sub_id": SUBSCRIPTION, "project_number_000": "001"}
    document = {"dev": {**identity, "persona_access_mode": "groups-v1", "persona_access_manifest": "dev.json"},
                "stage_prod": identity, "test": {"persona_access_manifest": "test.json"}}
    result = project_deployment.validate_config(document, "001", "stage")
    assert result["values"]["persona_access_manifest"] == "test.json"
    del document["stage_prod"]["tenantId"]
    with pytest.raises(ValueError, match="Exact target"):
        project_deployment.validate_config(document, "001", "stage")


def test_copied_registered_launcher_finds_installed_persona_package(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import importlib.util
    helper = tmp_path / "lib" / "registered_personas.py"
    helper.parent.mkdir()
    helper.write_bytes(Path(core.__file__).read_bytes())
    spec = importlib.util.spec_from_file_location("copied_registered_personas", helper)
    copied = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copied)
    package = tmp_path / ".azurefactory-tools" / "persona-engine" / "personas" / "pipeline.py"
    package.parent.mkdir(parents=True)
    package.write_text("")
    expected = SimpleNamespace(__file__=str(package))
    monkeypatch.setattr(copied.importlib, "import_module", Mock(return_value=expected))
    assert copied.pipeline_module() is expected


@pytest.mark.parametrize("blocked", [False, True])
def test_protected_worker_runs_preflight_before_arm_and_apply_afterward(monkeypatch, blocked):
    from .test_factory_lifecycle import fl, scoped_manifest, PlanCloud, seal, simple_plan_closure
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    calls = []

    def persona_worker(document, root, execute=False):
        calls.append((execute, len(cloud.arm_writes)))
        if blocked:
            raise ValueError("Seed prerequisite missing")
        return {"common": {"state": "applied"}} if execute else None

    helper = Mock()
    helper.worker = persona_worker
    helper.selected_config = core.selected_config
    monkeypatch.setattr(fl, "persona_helper", lambda _: helper)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                     ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    if blocked:
        assert result["error_code"] == "persona-access-preflight-failed"
        assert calls == [(False, 0)] and not cloud.arm_writes
    else:
        assert result["status"] == "succeeded" and result["persona_access"]["common"]["state"] == "applied"
        assert calls == [(False, 0), (True, 1)]
