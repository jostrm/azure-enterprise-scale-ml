"""Production adapters are tested with offline provider/ARM transports only."""

import base64
import copy
import importlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import workspace

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OBJECT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FACTORY = "dddddddd-dddd-dddd-dddd-dddddddddddd"
SCALE = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
PROJECT = "ffffffff-ffff-ffff-ffff-ffffffffffff"
COMMON = f"/subscriptions/{SUB}/resourceGroups/common"
GROUP = f"/subscriptions/{SUB}/resourceGroups/project001"


@pytest.fixture
def adapters(monkeypatch):
    module = importlib.import_module("pipeline_lifecycle_adapters")
    monkeypatch.setattr(module.fl.subprocess, "run", Mock(side_effect=AssertionError("real subprocess forbidden")))
    monkeypatch.setattr(module.fl, "build_opener", Mock(side_effect=AssertionError("real HTTP/Factory API forbidden")))
    return module


def snapshot(scenario=3):
    scale = {"id": SCALE, "environment": "dev", "tenant_id": TENANT, "subscription_id": SUB,
             "suffix": "001", "orchestrator": "gha", "owned_resource_ids": [COMMON, GROUP]}
    project = {"id": PROJECT, "number": "001", "placements": [
        {"scale_set_id": SCALE, "environment": "dev", "resource_ids": [GROUP]}]}
    binding = {
        "contract_version": 1, "orchestrator": "gha", "repository": "https://github.com/org/repo",
        "ref": "refs/heads/main", "shared_remote": False, "writer_id": "writer",
        "auth_namespace": "factory", "deployment_object_id": OBJECT,
        "runner": {"os": "linux", "kind": "hosted", "image": "ubuntu-latest"},
        "locks": {"provider": "provider-repository-cas", "coordination_mode": "single-writer",
                  "repository": "https://github.com/org/repo", "state_ref": "refs/heads/aifactory-state/single-writer-v1",
                  "coordination_hash": "d" * 64, "revision": 1},
        "targets": [{"scale_set_id": SCALE, "resource_group_ids": [COMMON, GROUP], "common_dependency_ids": []}],
    }
    return {
        "request": {"schema": 1, "scenario": scenario, "provider": "gha", "environment": "dev",
                    "include_project_subnets": False, "include_keyvault_and_resource_group": True},
        "document": {"schema_version": 2, "revision": 1, "ownership_evidence": {},
                     "bindings": {FACTORY: {"gha": binding}}},
        "factory": {"id": FACTORY, "kind": "ai", "prefix": "acme", "region": "eastus2",
                    "scale_sets": [scale], "projects": [project]},
        "scales": [scale], "projects": [project] if scenario in (1, 3, 4, 5, 6) else [],
        "source": {"ref": "refs/heads/main", "commit": "a" * 40},
        "binding": binding, "configuration": {"factory": {}},
        "variables": {PROJECT: {"dev": {}, "stage_prod": {}}}, "azurefactory_root": "azurefactory",
    }


class ProviderStore:
    def __init__(self):
        self.head = "a" * 40
        self.value = {"schema": 1, "repository": "https://github.com/org/repo",
                      "enrollment": {}, "active": None, "records": {"other": {"keep": True}}}

    def read(self):
        return self.head, copy.deepcopy(self.value)

    def replace(self, expected, value):
        assert expected == self.head
        self.value = copy.deepcopy(value)
        self.head = "b" * 40
        return self.head


def test_repository_journal_preserves_unrelated_native_records(adapters):
    remote = ProviderStore()
    store = adapters.RepositoryJournal(remote)
    expected, value = store.read("11111111-1111-1111-1111-111111111111")
    assert value is None
    remote.value["records"]["runs/native.json"] = {"status": "succeeded"}
    store.write("11111111-1111-1111-1111-111111111111", expected, {"status": "prepared"})
    assert remote.value["records"]["other"] == {"keep": True}
    assert remote.value["records"]["runs/native.json"]["status"] == "succeeded"


def test_repository_journal_rejects_competing_operation_update(adapters):
    remote = ProviderStore()
    store = adapters.RepositoryJournal(remote)
    operation = "11111111-1111-1111-1111-111111111111"
    expected, _ = store.read(operation)
    remote.value["records"][store.key(operation)] = {"status": "running"}
    with pytest.raises(ValueError, match="operation-cas-conflict"):
        store.write(operation, expected, {"status": "prepared"})


def test_plaintext_credentials_never_enter_repository_state(adapters):
    store = adapters.RepositoryJournal(ProviderStore())
    operation = "11111111-1111-1111-1111-111111111111"
    expected, _ = store.read(operation)
    with pytest.raises(ValueError, match="secret-material"):
        store.write(operation, expected, {"snapshot": {"servicePrincipalSecret": "a-real-secret"}})


def test_completed_worker_ownership_survives_fresh_process(adapters):
    from pipeline_lifecycle import bound_plan, digest
    remote = ProviderStore()
    worker = {"schema": 1, "status": "succeeded", "run_id": "11111111-1111-1111-1111-111111111111",
              "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
              "resource_groups": [{"resource_id": GROUP, "owner": {"factory_id": FACTORY, "scaleset_id": SCALE}}],
              "ownership": []}
    operation = "22222222-2222-2222-2222-222222222222"
    record = {"schema": 1, "operation_id": operation, "status": "succeeded", "prepared_at": "2026-01-01",
              "snapshot": snapshot(), "plan": {}, "stages": [{"status": "succeeded", "receipt": {
                  "status": "succeeded", "verified": True, "children": [{"worker": worker, "native": {}}]}}]}
    record["snapshot_hash"] = digest(record["snapshot"])
    record["plan_hash"] = digest(bound_plan(record))
    remote.value["records"][adapters.RepositoryJournal.key(operation)] = record
    owner = adapters.RepositoryJournal(remote).ownership(FACTORY)[GROUP.lower()]
    assert owner["ownership_source"] == "deployment-receipt"
    assert owner["ownership_evidence"]["receipt_hash"] == adapters.fl.digest(worker)
    record["status"] = "reconciliation-required"
    assert adapters.RepositoryJournal(remote).ownership(FACTORY) == {}


def token(oid=OBJECT):
    value = {"oid": oid, "tid": TENANT, "exp": time.time() + 3600, "aud": "https://management.azure.com"}
    return "header." + base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=") + ".signature"


class Cloud:
    def __init__(self):
        self.tokens = {}
        self.verify_identity = Mock()
        self.command = Mock(side_effect=self._command)

    @staticmethod
    def _command(argv, **kwargs):
        if argv[:3] == ["az", "account", "get-access-token"]:
            return json.dumps({"accessToken": token()})
        if argv[:2] == ["git", "ls-remote"]:
            return "b" * 40 + "\trefs/heads/main"
        if argv[:2] == ["git", "rev-parse"]:
            return "a" * 40
        if argv[:2] == ["gh", "api"]:
            return json.dumps({"id": 13})
        raise AssertionError(argv)

    def arm(self, method, resource, api, **kwargs):
        assert method == "GET"
        return 404, {}, None


@pytest.mark.parametrize("scenario,operation,freezer", [
    (1, "create-factory", "deployment"), (2, "create-scaleset", "deployment"),
    (3, "deploy-project", "deployment"), (4, "delete", "project"),
    (5, "delete", "scale"), (6, "delete", "factory"),
])
def test_six_native_plan_routes_use_real_adapter(adapters, monkeypatch, scenario, operation, freezer):
    cloud = Cloud()
    planner = adapters.NativePlanner(ROOT, ROOT, cloud_factory=lambda _: cloud, review=Mock())
    planner.review.origin.return_value = {"provider": "gha", "run_id": "42", "attempt": 1, "commit": "b" * 40}
    monkeypatch.setattr(planner, "deployment", Mock(return_value={"contract": 1, "steps": [], "changes": []}))
    monkeypatch.setattr(adapters.fl, "verify_source", Mock(return_value=ROOT))
    monkeypatch.setattr(adapters.fl, "coordination", Mock(return_value=Mock()))
    monkeypatch.setattr(adapters.fl, "validate_manifest", Mock())
    freezers = {}
    for kind, name in (("project", "freeze_project_deletion"), ("scale", "freeze_deletion_inventory"),
                       ("factory", "freeze_factory_deletion_pipeline")):
        freezers[kind] = Mock(return_value={"inventory_mode": kind, "resources": [], "resource_groups": []})
        monkeypatch.setattr(adapters.fl, name, freezers[kind])
    plan = planner.prepare(snapshot(scenario), "11111111-1111-1111-1111-111111111111")
    manifest = plan["stages"][0]["manifests"][0]
    assert manifest["operation"] == operation
    assert manifest["source"]["commit"] == "a" * 40
    assert manifest["identity"]["object_id"] == OBJECT
    cloud.verify_identity.assert_called()
    if freezer == "deployment":
        planner.deployment.assert_called_once()
    else:
        freezers[freezer].assert_called_once()
    if scenario == 4:
        assert manifest["deletion_scope"]["options"]["include_project_subnets"] is False
        assert manifest["deletion_scope"]["options"]["include_keyvault_and_resource_group"] is True


def test_cold_start_without_external_trust_fails_closed(adapters):
    data = snapshot(1)
    data["binding"] = {}
    planner = adapters.NativePlanner(ROOT, ROOT, cloud_factory=Mock(), review=Mock())
    with pytest.raises(ValueError, match="enrollment-and-external-trust-required"):
        planner.prepare(data, "11111111-1111-1111-1111-111111111111")
    planner.cloud_factory.assert_not_called()


def test_scenario_six_cannot_silently_drop_environment(adapters):
    data = snapshot(6)
    data["request"]["environment"] = "all"
    data["factory"]["scale_sets"].append({**data["scales"][0], "id": "99999999-9999-9999-9999-999999999999",
                                         "environment": "prod"})
    with pytest.raises(ValueError, match="complete-factory-cohort-required"):
        adapters.NativePlanner(ROOT, ROOT, cloud_factory=Mock(), review=Mock()).prepare(
            data, "11111111-1111-1111-1111-111111111111")


def test_native_executor_does_not_treat_identity_only_receipt_as_completion(adapters, monkeypatch):
    cloud = Mock()
    cloud.command.return_value = "a" * 40
    executor = adapters.NativeExecutor(ROOT, ROOT / ".pipeline-test-not-created", cloud_factory=lambda _: cloud)
    receipt = {"status": "succeeded", "completion": "identity-only", "continuation_required": True}
    monkeypatch.setattr(adapters.fl, "execute", Mock(return_value=receipt))
    monkeypatch.setattr(executor, "observe", Mock(return_value={"status": "succeeded", "verified": True}))
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [
        {"operation": "deploy-project", "source": {"commit": "a" * 40}}]}
    result = executor.execute(stage, {"operation_id": "11111111-1111-1111-1111-111111111111"})
    assert result["status"] == "continuation-required"
    assert result["verified"] is False


def test_execution_rejects_even_related_source_commit_drift_before_native_effects(adapters, monkeypatch):
    cloud = Mock()
    cloud.command.return_value = "b" * 40
    native = Mock()
    monkeypatch.setattr(adapters.fl, "execute", native)
    executor = adapters.NativeExecutor(ROOT, ROOT / ".pipeline-test-not-created", cloud_factory=lambda _: cloud)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [
        {"operation": "deploy-project", "source": {"commit": "a" * 40}}]}
    with pytest.raises(ValueError, match="exact-source-checkout-required"):
        executor.execute(stage, {"operation_id": "11111111-1111-1111-1111-111111111111"})
    native.assert_not_called()


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_runtime_routes_unapproved_delete_to_separate_authorization_review(adapters, provider):
    import pipeline_lifecycle_authorization as authorization
    from .test_pipeline_lifecycle_authorization import fixture
    service, store, data, original, _, _, _, review, _ = fixture(authorization, provider)
    store.value["records"]["lifecycle_admission_v1"]["claim"] = None
    planner, native, bootstrap = Mock(), Mock(), Mock()
    bootstrap.needed.return_value = False
    planner.prepare.return_value = {
        "origin": review.verify.return_value, "stages": [
            {"id": "lifecycle", "kind": "lifecycle", "manifests": original["manifests"]}],
        "review": {}}
    runtime = adapters.RuntimeAdapters(planner, native, bootstrap, authorization=service)
    plan = runtime.prepare(data, "22222222-2222-2222-2222-222222222222")
    assert plan["continuation_required"] is True
    assert plan["stages"][0]["kind"] == "deletion-authorization"
    assert plan["review"]["next"] == "prepare-continuation"
    assert planner.prepare.call_count == 1
    assert planner.prepare.call_args.kwargs["coordination_only"] is True
    assert store.writes == []
    native.execute.assert_not_called()


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_continuation_resolver_uses_republished_pins_not_stale_native_binding(adapters, provider):
    from .test_pipeline_inputs import register, request, inputs, SUB as selected_subscription
    from pipeline_lifecycle import digest
    from pipeline_lifecycle_recovery import continuation_snapshot
    document = register(provider)
    factory, scale = document["factories"][0], document["factories"][0]["scale_sets"][0]
    binding = copy.deepcopy(snapshot()["binding"])
    repository = "https://github.com/org/repo" if provider == "gha" else "https://dev.azure.com/org/project/_git/repo"
    binding.update(orchestrator=provider, repository=repository)
    binding["locks"]["repository"] = repository
    binding["targets"][0].update(scale_set_id=scale["id"],
                                 resource_group_ids=[f"/subscriptions/{selected_subscription}/resourceGroups/common"])
    document["bindings"] = {factory["id"]: {provider: binding}}
    operational = {"schema": 1, "provider": provider, "consumer_ref": binding["ref"],
                   "bootstrap": {"auth_namespace": "external"}}
    original = inputs.resolve_document(document, request(5, provider), operational=operational)
    published = copy.deepcopy(document)
    published["bindings"][factory["id"]][provider]["locks"]["coordination_hash"] = "e" * 64
    record = {"snapshot": original, "snapshot_hash": digest(original), "plan": {},
              "status": "continuation-required", "admission": {"status": "released"},
              "finalization": {"status": "succeeded"},
              "configuration": {"document": published, "revision": digest(published)}}
    following = continuation_snapshot(record, original)
    assert following["binding"]["locks"]["coordination_hash"] == "e" * 64
    assert following["binding"]["bootstrap"] == operational["bootstrap"]
    effective, _ = adapters.selected_binding(following, following["scales"][0])
    assert effective["locks"]["coordination_hash"] == "e" * 64
    assert original["binding"]["locks"]["coordination_hash"] == "d" * 64


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
def test_real_resolver_to_runtime_boundary_preserves_unenrolled_failure(
        adapters, workspace, monkeypatch, capsys, provider, scenario):
    import pipeline_lifecycle
    from .test_pipeline_inputs import register, request, save
    save(workspace, register(provider))
    path = workspace / "request.json"
    path.write_text(json.dumps(request(scenario, provider)), encoding="utf-8")
    before = {item.relative_to(workspace): item.read_bytes() for item in workspace.rglob("*") if item.is_file()}
    cloud = Mock(side_effect=AssertionError("Unenrolled configuration must not authenticate"))
    monkeypatch.setattr(adapters.factory_enrollment, "Cloud", cloud)
    assert pipeline_lifecycle.main([
        "prepare", "--request", "request.json", "--repository-root", str(workspace), "--source-root", str(ROOT)]) == 2
    output = json.loads(capsys.readouterr().err)
    assert output == {"status": "blocked", "error_code": "enrollment-and-external-trust-required"}
    cloud.assert_not_called()
    assert before == {item.relative_to(workspace): item.read_bytes()
                      for item in workspace.rglob("*") if item.is_file()}


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_real_starter_is_configuration_not_runtime_authority(adapters, workspace, monkeypatch, capsys, provider):
    import pipeline_configuration
    import pipeline_lifecycle
    from .test_pipeline_configuration import spec
    from .test_pipeline_inputs import request
    document = pipeline_configuration.initial_document(ROOT, spec(provider))
    pipeline_configuration.write_new_root(workspace, "azurefactory", document)
    (workspace / "request.json").write_text(json.dumps(request(1, provider)), encoding="utf-8")
    cloud = Mock(side_effect=AssertionError("A draft must never authorize authentication"))
    monkeypatch.setattr(adapters.factory_enrollment, "Cloud", cloud)
    assert pipeline_lifecycle.main([
        "prepare", "--request", "request.json", "--repository-root", str(workspace), "--source-root", str(ROOT)]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "enrollment-and-external-trust-required"
    cloud.assert_not_called()
    assert json.loads((workspace / "azurefactory" / "register.json").read_text()) == document


@pytest.mark.parametrize("field,value", [
    ("script", "untrusted.sh"), ("template", "custom.bicep"), ("arm_plan", {"steps": []}),
    ("manifest", {"operation": "delete"}), ("approval", True),
])
def test_closed_native_binding_rejects_executable_injection_before_auth(adapters, field, value):
    data = snapshot()
    data["binding"][field] = value
    planner = adapters.NativePlanner(ROOT, ROOT, cloud_factory=Mock(), review=Mock())
    with pytest.raises(ValueError, match="binding"):
        planner.prepare(data, "11111111-1111-1111-1111-111111111111")
    planner.cloud_factory.assert_not_called()


def test_operational_fields_are_closed_and_never_enter_native_binding(adapters):
    data = snapshot()
    data["binding"] = {**data["binding"], "schema": 1, "provider": "gha", "consumer_commit": "b" * 40,
                       "consumer_ref": "refs/heads/main"}
    native, target = adapters.selected_binding(data, data["scales"][0])
    assert not {"schema", "provider", "consumer_commit", "consumer_ref"} & set(native)
    assert target["scale_set_id"] == SCALE
    data["binding"]["pipeline_id"] = 4
    with pytest.raises(ValueError, match="operational-binding"):
        adapters.selected_binding(data, data["scales"][0])


def test_operational_binding_cannot_replace_register_authority(adapters):
    data = snapshot()
    data["document"]["bindings"] = {}
    with pytest.raises(ValueError, match="enrollment-and-external-trust-required"):
        adapters.selected_binding(data, data["scales"][0])


def test_native_nested_binding_schema_is_not_bypassed(adapters):
    data = snapshot()
    data["binding"]["targets"][0]["script"] = "run-anything.sh"
    with pytest.raises(ValueError, match="binding"):
        adapters.selected_binding(data, data["scales"][0])
