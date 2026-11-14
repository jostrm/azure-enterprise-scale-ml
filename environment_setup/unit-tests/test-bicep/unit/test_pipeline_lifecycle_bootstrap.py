"""Cold enrollment exercises the native helpers through offline transports."""

import copy
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from unit import test_single_writer_coordination as native

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
import pipeline_lifecycle_bootstrap as boot
from pipeline_lifecycle import PipelineError, bound_plan, digest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live commands and HTTP are forbidden")
    monkeypatch.setattr(native.en.subprocess, "run", forbidden)
    monkeypatch.setattr(native.en, "build_opener", forbidden)
    monkeypatch.setattr(boot, "enrollment", native.en)


@pytest.fixture
def workspace():
    root = ROOT / (".bootstrap-offline-" + str(uuid4()))
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


def snapshot(provider="gha", environment="dev", scenario=1):
    t = native.te
    scale = {"id": t.SCALE, "suffix": "001", "environment": environment,
             "tenant_id": t.TENANT, "subscription_id": t.SUB, "orchestrator": provider}
    project = {"id": t.PROJECT, "number": "001",
               "placements": [{"environment": environment, "scale_set_id": t.SCALE}]}
    factory = {"id": t.FACTORY, "kind": "ai", "prefix": "acme-ai", "region": "swedencentral",
               "region_short_name": "sdc", "aifactory_version": "main", "scale_sets": [scale],
               "projects": [project]}
    platform = {
        "identity_id": f"/subscriptions/{t.ADO_SUB}/resourcegroups/platform/providers/"
                       "microsoft.managedidentity/userassignedidentities/platform",
        "writer_id": "platform-writer", "auth_namespace": "esaf-pipelines-execute",
        "runner": ({"kind": "self-hosted", "os": "linux",
                    "labels": ["self-hosted", "linux", "esaf-lifecycle-external"]}
                   if provider == "gha" else
                   {"kind": "self-hosted", "os": "linux", "pool": "esaf-lifecycle-external"}),
        "deployment_role_definition_ids": [t.CONTRIBUTOR],
        **({"ado_tenant_id": t.ADO_TENANT} if provider == "ado" else {}),
    }
    config = {"factory": {"admin_locationSuffix": "sdc"},
              "scale_sets": {t.SCALE: {}}, "projects": {}}
    document = {"schema_version": 2, "generation": "reviewed", "factories": [factory],
                "configurations": {t.FACTORY: config}, "bindings": {}}
    return {"request": {"scenario": scenario, "provider": provider, "environment": environment},
            "factory": factory, "scales": [scale], "projects": [project] if scenario == 1 else [],
            "document": document, "configuration": config,
            "variables": {t.PROJECT: {"dev": {}, "stage_prod": {}}},
            "source": {"ref": "refs/heads/main", "commit": "a" * 40},
            "binding": {"schema": 1, "provider": provider, "consumer_ref": "refs/heads/main",
                        "bootstrap": platform,
                        "repository": native.te.options(provider)["repository"]}}


def harness(workspace, value):
    calls = []
    review = SimpleNamespace(
        origin=lambda snapshot: {"provider": value["request"]["provider"],
                                 "repository": (value["binding"]["repository"].removeprefix("https://github.com/")
                                                if value["request"]["provider"] == "gha" else
                                                value["binding"]["repository"]),
                                 "commit": "b" * 40, "ref": "refs/heads/main", "run_id": "42", "attempt": 1},
        verify=lambda record: calls.append("review") or {"authenticated": "test-provider"},
    )
    admission = SimpleNamespace(assert_owned=lambda record: calls.append("admission"))
    transport = None

    def cloud(request):
        nonlocal transport
        if transport is None:
            provider = native.Provider(request["route"]["repository"])
            transport = native.EnrollmentTransport(request, provider)
            transport.resources[request["identity_id"]] = {
                "id": request["identity_id"], "location": "swedencentral",
                "properties": transport.identity_properties}
            transport.identity_subscription_tenant = native.te.TENANT
        transport.request = request
        transport.cloud.request_config = request
        return transport.cloud

    adapter = boot.BootstrapAdapter(workspace, ROOT, workspace / ".esaf", review=review,
                                    admission=admission, cloud_factory=cloud)
    return adapter, calls, lambda: transport


def record_for(value, plan, operation):
    record = {"operation_id": operation, "snapshot": value, "snapshot_hash": digest(value),
              "plan": plan, "prepared_at": "2026-10-12T12:00:00+00:00"}
    record["plan_hash"] = digest(bound_plan(record))
    return record


def interrupted_bootstrap(workspace, provider):
    import lifecycle_admission as shared
    import pipeline_configuration
    import pipeline_inputs
    from pipeline_lifecycle import LifecycleService
    from pipeline_lifecycle_adapters import RepositoryJournal, RuntimeAdapters
    from pipeline_lifecycle_admission import NativeAdmission
    from pipeline_lifecycle_reconciliation import RetainedClaimReconciliation
    from pipeline_lifecycle_bootstrap_recovery import BootstrapReconciliation

    document = pipeline_configuration.initial_document(ROOT, {
        "factory": "acme-ai", "prefix": "acme-", "region": "swedencentral", "region_short": "sdc",
        "tenant": native.te.TENANT, "subscription": native.te.SUB, "provider": provider,
        "environment": "dev", "scale_set": "001", "project": "007", "cidr": "10.140.0.0/18",
        "max_projects": 7, "version": "main", "network_mode": "private"})
    data = pipeline_inputs.resolve_document(document, {
        "schema": 1, "scenario": 1, "provider": provider, "factory": "acme-ai", "environment": "dev",
        "scale_set": "001", "project": "007", "source_ref": "refs/heads/main", "source_commit": "a" * 40},
        operational=snapshot(provider)["binding"])
    bootstrap, _, transport = harness(workspace, data)
    request = bootstrap._inputs(data, str(uuid4()))
    bootstrap._cloud(request)
    state_cloud = native.en.Cloud(request, command_runner=transport().run, opener=transport())
    state_cloud.read_only = False
    store = native.ps.ProviderState(state_cloud, request["route"], PipelineError)
    factory_id = data["factory"]["id"]
    policy = {"repository": data["binding"]["repository"], "factories": {factory_id: {
        "all_writers": shared.PROTOCOL, "shared_scopes": [], "operations": sorted(shared.OPERATIONS),
        "routes": ["api", "pipeline"], "scopes": request["scopes"]}}}
    installed = store.empty()
    installed["records"][shared.RECORD] = shared.new_record(policy, {factory_id: document})
    store.replace(None, installed)
    origin = bootstrap.review.origin(data)
    bootstrap.review.origin = lambda _: copy.deepcopy(origin)
    bootstrap.review.verify = lambda record: copy.deepcopy(origin)
    bootstrap.review.verify_finalizer = lambda record: {
        "operation_id": record["operation_id"], "plan_hash": record["plan_hash"], **origin}
    bootstrap.review.get = lambda _: {
        "id": int(origin["run_id"]), "run_attempt": 1, "head_sha": origin["commit"],
        "sourceVersion": origin["commit"], "status": "in_progress"}
    planner = SimpleNamespace(provider_context=None)
    adapters = RuntimeAdapters(planner, Mock(), bootstrap)
    admission = NativeAdmission(store, bootstrap.review, adapters)
    bootstrap.admission = admission
    reconciliation = RetainedClaimReconciliation(store, review=bootstrap.review, admission=admission, evidence=Mock())
    adapters.reconciliation = admission.reconciliation = reconciliation
    adapters.bootstrap_reconciliation = admission.bootstrap_reconciliation = BootstrapReconciliation(store, bootstrap)
    engine = LifecycleService(store=RepositoryJournal(store), planner=adapters, executor=adapters,
                              review=bootstrap.review, admission=admission, configuration=admission)
    operation = engine.prepare(data)
    raw_arm = transport().cloud.arm
    def original_arm(method, resource_id, *args, **kwargs):
        status, headers, body = raw_arm(method, resource_id, *args, **kwargs)
        if status == 404 and resource_id.lower() in request["scopes"]:
            body = {"error": {"code": "ResourceGroupNotFound"}}
        return status, headers, body
    interrupted = []
    def interrupt(method, resource_id, *args, **kwargs):
        response = original_arm(method, resource_id, *args, **kwargs)
        if method == "PUT" and resource_id.lower() in request["scopes"] and not interrupted:
            interrupted.append(resource_id.lower())
            raise OSError("lost-response-after-group-created")
        return response
    transport().cloud.arm = interrupt
    failed = engine.execute(operation["operation_id"], data, operation["plan_hash"])
    assert failed["status"] == "reconciliation-required"
    assert interrupted and store.read()[1]["active"]["kind"] == "enrollment"
    transport().cloud.arm = original_arm
    origin["run_id"] = "43"
    original_state_request = transport().cloud.state_request
    original_collection = transport().cloud.collection
    def provider_read(kind, method, endpoint, body, allowed):
        if method == "GET" and ("/actions/runs/42" in endpoint or "/build/builds/42?" in endpoint):
            return 200, {}, {"id": 42, "status": "completed", "conclusion": "cancelled", "result": "canceled",
                "head_sha": origin["commit"], "sourceVersion": origin["commit"], "run_attempt": 1,
                "head_branch": "main", "sourceBranch": origin["ref"],
                "repository": {"full_name": origin["repository"],
                               "id": "11111111-1111-4111-8111-111111111111"}}
        if method == "GET" and "/_apis/git/repositories/" in endpoint and endpoint.endswith("?api-version=7.1"):
            return 200, {}, {"id": "11111111-1111-4111-8111-111111111111",
                             "remoteUrl": request["route"]["repository"], "isDisabled": False,
                             "project": {"visibility": "private"}}
        return original_state_request(kind, method, endpoint, body, allowed)
    transport().cloud.state_request = provider_read
    transport().cloud.collection = lambda path, version: (
        [] if any(path == scope + suffix for scope in request["scopes"]
                  for suffix in ("/resources", "/providers/Microsoft.Resources/deployments"))
        else original_collection(path, version))
    return SimpleNamespace(engine=engine, store=store, data=data, operation=operation, request=request,
                           transport=transport(), origin=origin, bootstrap=bootstrap, interrupted=interrupted)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_interrupted_bootstrap_requires_reviewed_claim_recovery_and_only_missing_effects(workspace, provider):
    case = interrupted_bootstrap(workspace, provider)
    engine, data, operation, origin = case.engine, case.data, case.operation, case.origin
    transport, interrupted = lambda: case.transport, case.interrupted
    recovery = engine.prepare_recovery(operation["operation_id"], data, operation["plan_hash"])
    assert recovery["plan"]["stages"][0]["kind"] == "bootstrap-reconciliation"
    before = len(transport().writes)
    recovered = engine.execute(recovery["operation_id"], data, recovery["plan_hash"])
    assert recovered["status"] == "continuation-required", recovered.get("error_code")
    engine.finalize(recovery["operation_id"], data, recovery["plan_hash"])
    assert len(transport().writes) == before
    origin["run_id"] = "44"
    child = engine.prepare_continuation(recovery["operation_id"], data, recovery["plan_hash"])
    assert child["plan"]["stages"][0]["kind"] == "bootstrap-enrollment"
    assert interrupted[0] not in {row["id"] for row in child["plan"]["stages"][0]["empty_groups"]["effects"]}
    result = engine.execute(child["operation_id"], data, child["plan_hash"])
    assert result["status"] == "continuation-required", result.get("error_code")
    assert result["configuration"]["document"]["bindings"][data["factory"]["id"]][provider]
    writes_to_created = [row for row in transport().writes if row[:2] == ("arm", "PUT")
                        and row[2].split("?", 1)[0].lower().endswith(interrupted[0])]
    assert len(writes_to_created) == 1


@pytest.mark.parametrize("defect", [
    "missing-attempt", "foreign-native-claim", "group-owner", "identity", "active-deployment",
    "unreviewed-resource", "ambiguous-absence",
])
def test_bootstrap_recovery_rejects_unproven_or_changed_effects(workspace, defect):
    from pipeline_lifecycle_bootstrap_recovery import ATTEMPTS
    case = interrupted_bootstrap(workspace, "gha")
    cloud, transport = case.transport.cloud, case.transport
    if defect in ("missing-attempt", "foreign-native-claim"):
        head, state = case.store.read()
        if defect == "missing-attempt":
            state["records"].pop(ATTEMPTS + case.operation["operation_id"] + ".json")
        else:
            state["active"]["id"] = str(uuid4())
        case.store.replace(head, state)
    elif defect == "group-owner":
        transport.resources[case.interrupted[0]]["tags"]["aifactory.factory_id"] = "foreign"
    elif defect == "identity":
        transport.identity_properties["principalId"] = str(uuid4())
    elif defect in ("active-deployment", "unreviewed-resource"):
        previous = cloud.collection
        suffix = "/providers/Microsoft.Resources/deployments" if defect == "active-deployment" else "/resources"
        cloud.collection = lambda path, version: (
            [{"id": path + "/unexpected", "properties": {"provisioningState": "Running"}}]
            if path == case.interrupted[0] + suffix else previous(path, version))
    else:
        previous = cloud.arm
        def ambiguous(method, identifier, *args, **kwargs):
            status, headers, body = previous(method, identifier, *args, **kwargs)
            return (status, headers, {}) if status == 404 else (status, headers, body)
        cloud.arm = ambiguous
    before = len(transport.writes), case.store.read()[1]
    with pytest.raises((ValueError, native.en.EnrollmentError)):
        case.engine.prepare_recovery(case.operation["operation_id"], case.data, case.operation["plan_hash"])
    assert before == (len(transport.writes), case.store.read()[1])


def test_bootstrap_recovery_adopts_exact_durable_cleanup_after_lost_cas_response(workspace, monkeypatch):
    from pipeline_lifecycle_bootstrap_recovery import AUDITS, BootstrapReconciliation
    case = interrupted_bootstrap(workspace, "gha")
    engine, operation, data = case.engine, case.operation, case.data
    recovery = engine.prepare_recovery(operation["operation_id"], data, operation["plan_hash"])
    replace = case.store.replace
    writes = len(case.transport.writes)
    audit_key = AUDITS + recovery["operation_id"] + ".json"
    lost = []
    def uncertain(head, state):
        result = replace(head, state)
        if audit_key in state["records"] and not lost:
            lost.append(state["records"][audit_key])
            raise OSError("lost-cleanup-cas-response")
        return result
    monkeypatch.setattr(case.store, "replace", uncertain)
    with pytest.raises(OSError, match="lost-cleanup"):
        engine.execute(recovery["operation_id"], data, recovery["plan_hash"])
    monkeypatch.setattr(case.store, "replace", replace)
    fresh = BootstrapReconciliation(case.store, case.bootstrap)
    engine.executor.bootstrap_reconciliation = engine.admission.bootstrap_reconciliation = fresh
    observed = engine.execute(recovery["operation_id"], data, recovery["plan_hash"])
    assert observed["status"] == "continuation-required", observed.get("error_code")
    assert observed["admission_claim"] == lost[0]["claim"]
    assert case.store.read()[1]["records"][audit_key] == lost[0]
    assert len(case.transport.writes) == writes


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("environment,scenario", [("dev", 1), ("stage", 2), ("prod", 2)])
def test_real_empty_group_enrollment_requires_new_downstream_review(workspace, provider, environment, scenario):
    value = snapshot(provider, environment, scenario)
    adapter, calls, transport = harness(workspace, value)
    operation = str(uuid4())
    plan = adapter.prepare(value, operation)
    assert adapter.needed(value)
    assert plan["continuation_required"] is True
    stage = plan["stages"][0]
    assert stage["kind"] == "bootstrap-enrollment"
    assert stage["empty_groups"]["effects"]
    assert not transport().writes
    assert all(row[0] == "GET" for row in transport().provider.calls)
    record = record_for(value, plan, operation)
    outcome = adapter.execute(stage, record)
    assert calls[0] == "review" and len(calls) > 2 and set(calls[1:]) == {"admission"}
    assert outcome["status"] == "continuation-required", outcome
    assert outcome["verified"] is True and outcome["runtime_ready"] is False
    assert outcome["binding_candidate"]["locks"]["coordination_mode"] == "single-writer"
    assert outcome["continuation"]["requires_fresh_review"] is True
    for effect in stage["empty_groups"]["effects"]:
        actual = transport().resources[effect["id"]]
        assert actual["tags"] == effect["body"]["tags"]
    if scenario == 1:
        project = transport().resources[adapter._physical(value)["project"]]
        assert project["tags"]["aifactory.project_id"] == "001"
        assert project["tags"]["aifactory.logical_project_id"] == native.te.PROJECT
    assert not (workspace / "azurefactory").exists()
    assert not any("storage" in row[2].lower() for row in transport().writes)
    before = len(transport().writes), len(transport().provider.calls)
    observed = adapter.observe(stage, record)
    assert observed["status"] == "continuation-required"
    assert len(transport().writes) == before[0]
    assert all(row[0] == "GET" for row in transport().provider.calls[before[1]:])


@pytest.mark.parametrize("field,value", [
    ("runner", {"kind": "hosted", "os": "linux", "image": "ubuntu-latest"}),
    ("identity_id", f"/subscriptions/{native.te.SUB}/resourcegroups/platform/providers/"
                    "microsoft.managedidentity/userassignedidentities/platform"),
    ("script", "curl evil"),
    ("client_secret", "must-not-be-accepted"),
])
def test_unsafe_platform_options_fail_before_auth(workspace, field, value):
    data = snapshot()
    data["binding"]["bootstrap"][field] = value
    adapter, calls, transport = harness(workspace, data)
    with pytest.raises((PipelineError, native.en.EnrollmentError, boot.pipeline_inputs.InputError)):
        adapter.prepare(data, str(uuid4()))
    assert not calls and transport() is None


def test_denied_approval_has_no_writes(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    adapter.review.verify = lambda record: (_ for _ in ()).throw(PipelineError("denied"))
    with pytest.raises(PipelineError, match="denied"):
        adapter.execute(plan["stages"][0], record_for(data, plan, operation))
    assert not transport().writes
    assert all(row[0] == "GET" for row in transport().provider.calls)


def test_own_journal_and_claim_updates_do_not_invalidate_resource_review(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    state = native.ps.ProviderState(transport().cloud, transport().request["route"], native.en.EnrollmentError).empty()
    state["records"]["pipeline-lifecycle/" + operation + ".json"] = {"status": "running"}
    transport().provider.set_state(state)
    result = adapter.execute(plan["stages"][0], record_for(data, plan, operation))
    assert result["status"] == "continuation-required"
    assert transport().provider.state()["records"]["pipeline-lifecycle/" + operation + ".json"] == {"status": "running"}


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("change", ["checkpoint-only", "scope", "role", "configuration", "native-run", "native-claim"])
def test_parent_checkpoint_drift_is_not_native_authority(workspace, provider, change):
    data = snapshot(provider)
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    request = adapter._inputs(data, operation)
    cloud = adapter._cloud(request)
    state = native.ps.ProviderState(cloud, request["route"], native.en.EnrollmentError).empty()
    parent_key = "pipeline-lifecycle/" + str(uuid4()) + ".json"
    native_key = "runs/" + str(uuid4()) + ".worker.json"
    state["records"][parent_key] = {
        "status": "continuation-required", "verified": True, "updated_at": "2026-11-13T18:00:00Z"}
    state["records"][native_key] = {"status": "succeeded", "verified": True}
    state["records"]["lifecycle_admission_v1"] = {
        "policy": {"canonical": {"generation": "reviewed"}}, "claim": None}
    transport().provider.set_state(state)
    plan = adapter.prepare(data, operation)
    state["records"][parent_key].update(
        updated_at="2026-11-13T18:30:00Z", continuation_child=operation,
        continuation_dispatch={"status": "dispatched", "run_id": "99"})
    if change == "scope":
        scope = request["scopes"][0]
        transport().resources[scope] = {"id": scope, "location": "swedencentral",
                                       "tags": {"aifactory.factory_id": "different-owner"}}
    elif change == "role":
        role = f"/subscriptions/{native.te.SUB}/providers/microsoft.authorization/roledefinitions/{native.te.CONTRIBUTOR}"
        transport().resources[role]["properties"]["permissions"] = []
    elif change == "configuration":
        state["records"]["lifecycle_admission_v1"]["policy"]["canonical"]["generation"] = "changed"
    elif change == "native-run":
        state["records"][native_key]["verified"] = False
    elif change == "native-claim":
        state["active"] = {"kind": "enrollment", "id": str(uuid4()), "plan_hash": "a" * 64}
    transport().provider.set_state(state)
    record = record_for(data, plan, operation)
    if change == "checkpoint-only":
        result = adapter.execute(plan["stages"][0], record)
        assert result["status"] == "continuation-required" and result["verified"] is True
        persisted = transport().provider.state()["records"]
        assert persisted[parent_key] == state["records"][parent_key]
        assert persisted[native_key] == state["records"][native_key]
    else:
        with pytest.raises((PipelineError, native.en.EnrollmentError)):
            adapter.execute(plan["stages"][0], record)
        assert not transport().writes
        assert all(row[0] == "GET" for row in transport().provider.calls)


def test_changed_permissions_block_before_writes(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    role = f"/subscriptions/{native.te.SUB}/providers/microsoft.authorization/roledefinitions/{native.te.CONTRIBUTOR}"
    transport().resources[role]["properties"]["permissions"] = []
    with pytest.raises((PipelineError, native.en.EnrollmentError)):
        adapter.execute(plan["stages"][0], record_for(data, plan, operation))
    assert not transport().writes


def test_native_uncertain_response_is_not_replayed(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    transport().provider.uncertain = True
    record = record_for(data, plan, operation)
    with pytest.raises((PipelineError, native.en.EnrollmentError)):
        adapter.execute(plan["stages"][0], record)
    before = len(transport().provider.calls)
    with pytest.raises((PipelineError, native.en.EnrollmentError)):
        adapter.observe(plan["stages"][0], record)
    assert all(row[0] == "GET" for row in transport().provider.calls[before:])


def test_stage_tampering_is_rejected(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    record = record_for(data, plan, operation)
    stage = copy.deepcopy(plan["stages"][0])
    stage["enrollment"]["options"]["resource_group_ids"].append(native.te.GROUP)
    with pytest.raises(PipelineError, match="stage"):
        adapter.execute(stage, record)
    assert not transport().writes


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_fresh_protected_job_may_use_another_local_working_directory(workspace, provider):
    data = snapshot(provider)
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    fresh = boot.BootstrapAdapter(workspace, ROOT, workspace / ".other-job", review=adapter.review,
                                  admission=adapter.admission, cloud_factory=adapter.cloud_factory)
    result = fresh.execute(plan["stages"][0], record_for(data, plan, operation))
    assert result["status"] == "continuation-required"
    assert transport().request["consumer_root"] != plan["stages"][0]["enrollment"]["consumer_root"]


@pytest.mark.parametrize("mutate_policy", [False, True])
def test_shared_claim_change_is_allowed_but_policy_change_is_not(workspace, mutate_policy):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    request = adapter._inputs(data, operation)
    cloud = adapter._cloud(request)
    state = native.ps.ProviderState(cloud, request["route"], native.en.EnrollmentError).empty()
    state["records"]["lifecycle_admission_v1"] = {"policy": {"version": 1}, "claim": None}
    transport().provider.set_state(state)
    plan = adapter.prepare(data, operation)
    state["records"]["lifecycle_admission_v1"]["claim"] = {"id": operation}
    if mutate_policy:
        state["records"]["lifecycle_admission_v1"]["policy"]["version"] = 2
    transport().provider.set_state(state)
    record = record_for(data, plan, operation)
    if mutate_policy:
        with pytest.raises(PipelineError, match="reviewed-native-state-changed"):
            adapter.execute(plan["stages"][0], record)
        assert not transport().writes
    else:
        result = adapter.execute(plan["stages"][0], record)
        assert result["status"] == "continuation-required"
        assert transport().provider.state()["records"]["lifecycle_admission_v1"] == state["records"]["lifecycle_admission_v1"]


def test_reviewed_exact_admission_scope_extension_does_not_invalidate_bootstrap(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    request = adapter._inputs(data, operation)
    cloud = adapter._cloud(request)
    state = native.ps.ProviderState(cloud, request["route"], native.en.EnrollmentError).empty()
    factory = data["factory"]["id"]
    prior = f"/subscriptions/{native.te.SUB}/resourcegroups/previous"
    state["records"]["lifecycle_admission_v1"] = {
        "policy": {"factories": {factory: {"scopes": [prior], "all_writers": "unchanged"}}}, "claim": None}
    transport().provider.set_state(state)
    plan = adapter.prepare(data, operation)
    record = record_for(data, plan, operation)
    additional = sorted(request["scopes"])
    claim = {"operation_id": operation, "scopes": sorted([prior, *additional]),
             "identity": {"scope_extension": additional}}
    record["admission_claim"] = claim
    state["records"]["lifecycle_admission_v1"]["claim"] = claim
    state["records"]["lifecycle_admission_v1"]["policy"]["factories"][factory]["scopes"] = claim["scopes"]
    transport().provider.set_state(state)
    assert adapter.execute(plan["stages"][0], record)["status"] == "continuation-required"


def test_admission_loss_blocks_before_first_effect(workspace):
    data = snapshot()
    adapter, calls, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)

    def held(record):
        calls.append("admission")
        if calls.count("admission") > 1:
            raise PipelineError("claim-lost")

    adapter.admission.assert_owned = held
    with pytest.raises((PipelineError, native.en.EnrollmentError)):
        adapter.execute(plan["stages"][0], record_for(data, plan, operation))
    assert not transport().writes
    assert all(row[0] == "GET" for row in transport().provider.calls)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_build_service_selects_bootstrap_before_native_binding(workspace, monkeypatch, provider):
    import pipeline_lifecycle_adapters as adapters
    import pipeline_lifecycle_cloud as clouds_module
    data = snapshot(provider)
    clouds = []

    def cloud(request):
        clouds.append(request)
        return SimpleNamespace(read_only=True)

    monkeypatch.setattr(clouds_module, "PipelineEnrollmentCloud", cloud)
    service = adapters.build_service(data, repo_root=workspace, source_root=ROOT, state_root=workspace / ".state")
    assert service.planner.bootstrap.needed(data)
    assert service.executor.bootstrap is service.planner.bootstrap
    assert service.executor.bootstrap.admission is service.admission
    assert clouds[0]["route"]["repository"] == data["binding"]["repository"]
    if provider == "ado":
        assert clouds[0]["ado_tenant_id"] == data["binding"]["bootstrap"]["ado_tenant_id"]


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", [1, 2])
def test_cold_outer_orchestration_persists_verified_binding_in_provider_cas(workspace, provider, scenario):
    import pipeline_lifecycle as runtime
    import pipeline_lifecycle_adapters as adapters
    data = snapshot(provider, scenario=scenario)
    original = copy.deepcopy(data["document"])
    adapter, _, transport = harness(workspace, data)
    request = adapter._inputs(data, str(uuid4()))
    adapter._cloud(request)
    cloud = native.en.Cloud(request, command_runner=transport().run, opener=transport())
    cloud.read_only = False
    provider_store = native.ps.ProviderState(cloud, request["route"], PipelineError)
    journal = adapters.RepositoryJournal(provider_store)
    admission = Mock(spec=["acquire", "assert_owned", "release"])
    admission.acquire.return_value = {"id": "test-authenticated-claim"}
    admission.release.return_value = {"status": "provider-completion-pending"}
    adapter.admission = admission
    engine = runtime.LifecycleService(store=journal, planner=adapter, executor=adapter,
                                      review=adapter.review, admission=admission)
    prepared = engine.prepare(data)
    assert not transport().writes
    result = engine.execute(prepared["operation_id"], data, prepared["plan_hash"])
    assert result["status"] == "continuation-required", result.get("error_code")
    _, durable = adapters.RepositoryJournal(provider_store).read(result["operation_id"])
    assert durable["snapshot"]["document"] == original
    candidate = durable["stages"][0]["receipt"]["binding_candidate"]
    assert candidate["targets"][0]["scale_set_id"] == data["scales"][0]["id"]
    assert candidate["locks"]["coordination_hash"]
    before = len(transport().writes)
    assert engine.reconcile(result["operation_id"])["status"] == "continuation-required"
    assert len(transport().writes) == before


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_additive_scale_enrollment_preserves_previous_target_and_canonical_input(workspace, provider):
    data = snapshot(provider)
    adapter, _, transport = harness(workspace, data)
    first = str(uuid4())
    plan = adapter.prepare(data, first)
    completed = adapter.execute(plan["stages"][0], record_for(data, plan, first))
    original_binding = completed["binding_candidate"]
    original_id = data["scales"][0]["id"]
    data["document"]["bindings"] = {data["factory"]["id"]: {provider: original_binding}}
    data["request"].update(scenario=2, environment="stage")
    new_scale = {**data["scales"][0], "id": str(uuid4()), "suffix": "002", "environment": "stage"}
    data["factory"]["scale_sets"].append(new_scale)
    data["scales"] = [new_scale]
    data["projects"] = []
    data["configuration"]["scale_sets"][new_scale["id"]] = {}
    second = str(uuid4())
    saved = copy.deepcopy(data)
    plan = adapter.prepare(data, second)
    completed = adapter.execute(plan["stages"][0], record_for(data, plan, second))
    assert {row["scale_set_id"] for row in completed["binding_candidate"]["targets"]} == {original_id, new_scale["id"]}
    assert data == saved


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_new_project_enrolls_only_missing_group_and_preserves_existing_target(workspace, provider):
    data = snapshot(provider)
    # The asserted non-ESML name is an explicit customer naming override.
    data["configuration"]["factory"].update(projectPrefix="-", projectSuffix="")
    adapter, _, transport = harness(workspace, data)
    first = str(uuid4())
    plan = adapter.prepare(data, first)
    prior = adapter.execute(plan["stages"][0], record_for(data, plan, first))["binding_candidate"]
    data["document"]["bindings"] = {data["factory"]["id"]: {provider: prior}}
    data["request"]["scenario"] = 3
    project = {**copy.deepcopy(data["projects"][0]), "id": str(uuid4()), "number": "002"}
    data["factory"]["projects"].append(project)
    data["projects"] = [project]
    data["variables"][project["id"]] = {"dev": {}, "stage_prod": {}}
    before = copy.deepcopy(data)
    assert adapter.needed(data)
    writes = len(transport().writes)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    assert len(transport().writes) == writes
    stage = plan["stages"][0]
    missing = f"/subscriptions/{native.te.SUB}/resourcegroups/acme-ai-project002-sdc-dev-001"
    old_scopes = set(prior["targets"][0]["resource_group_ids"])
    assert set(stage["enrollment"]["scopes"]) == old_scopes | {missing}
    assert stage["enrollment"]["create_resource_group_ids"] == [missing]
    assert {row["scope"] for row in stage["enrollment"]["deployment_roles"]} == {missing}
    outcome = adapter.execute(stage, record_for(data, plan, operation))
    assert outcome["status"] == "continuation-required" and outcome["runtime_ready"] is False
    candidate = outcome["binding_candidate"]
    assert set(candidate["targets"][0]["resource_group_ids"]) == old_scopes | {missing}
    assert transport().resources[missing]["tags"]["aifactory.logical_project_id"] == project["id"]
    assert adapter.observe(stage, record_for(data, plan, operation)) == outcome
    assert data == before
    data["document"]["bindings"][data["factory"]["id"]][provider] = candidate
    assert not adapter.needed(data)


def test_native_project_naming_defaults_are_not_changed():
    data = snapshot()
    scope = boot.BootstrapAdapter._physical(data)["project"]
    assert scope.endswith("/resourcegroups/acme-aiesml-project001-sdc-dev-001-rg")


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_project_extension_does_not_repair_lost_existing_grants(workspace, provider):
    data = snapshot(provider)
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    prior = adapter.execute(plan["stages"][0], record_for(data, plan, operation))["binding_candidate"]
    data["document"]["bindings"] = {data["factory"]["id"]: {provider: prior}}
    data["request"]["scenario"] = 3
    project = {**copy.deepcopy(data["projects"][0]), "id": str(uuid4()), "number": "002"}
    data["factory"]["projects"].append(project)
    data["projects"] = [project]
    data["variables"][project["id"]] = {"dev": {}, "stage_prod": {}}
    for key in list(transport().resources):
        if "/roleassignments/" in key:
            del transport().resources[key]
    before = len(transport().writes)
    with pytest.raises(PipelineError, match="retained-role-grant-missing"):
        adapter.prepare(data, str(uuid4()))
    assert len(transport().writes) == before


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("competing", [False, True])
def test_actual_pipeline_enrollment_uses_provider_token_and_exact_run_exclusion(
        workspace, provider, competing, monkeypatch, capsys):
    from pipeline_lifecycle_cloud import PipelineEnrollmentCloud
    data = snapshot(provider)
    adapter, _, transport = harness(workspace, data)
    original = adapter.cloud_factory
    calls, headers = [], []
    current = None
    secret = ("pipeline-seeded-github-token" if provider == "gha"
              else native.te.Fake._token(None, native.en.ADO_AUDIENCE, native.te.ADO_TENANT))
    monkeypatch.setenv("GH_TOKEN" if provider == "gha" else "AIFACTORY_STATE_TOKEN", secret)
    before_env = dict(os.environ)

    def command(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "az"
        assert native.en.ADO_AUDIENCE not in argv
        assert argv[1:3] != ["account", "list"]
        return transport().run(argv, **kwargs)

    def open_request(request, **kwargs):
        url = request.full_url
        if urlsplit(url).hostname in ("api.github.com", "dev.azure.com"):
            headers.append(request.get_header("Authorization"))
        if "/actions/runs?" in url:
            row = {"id": 43 if competing else 42, "run_attempt": 1, "head_sha": "b" * 40,
                   "repository": {"full_name": "org/repo"}}
            return native.te.Response(200, {"total_count": 1, "workflow_runs": [row]})
        if "/build/builds?" in url:
            row = {"id": 43 if competing else 42, "sourceVersion": "b" * 40,
                   "sourceBranch": "refs/heads/main", "repository": {"id": native.te.PROJECT}}
            return native.te.Response(200, {"count": 1, "value": [row]})
        if url.startswith("https://api.github.com/"):
            endpoint = url.removeprefix("https://api.github.com/")
            raw = transport().run(["gh", "api", "--hostname", "github.com", "--include",
                                   "--method", request.get_method(), endpoint],
                                  input=request.data, shell=False)
            header, text = raw.stdout.decode().replace("\r\n", "\n").split("\n\n", 1)
            return native.te.Response(int(header.split()[1]), json.loads(text))
        if "/_apis/git/repositories/repo?" in url:
            status, response_headers, body = transport().provider.call(
                "ado", request.get_method(), url, None, (200,))
            return native.te.Response(status, {**body, "id": native.te.PROJECT}, response_headers)
        return transport().open(request, **kwargs)

    def factory(request):
        nonlocal current
        original(request)
        if current is None:
            current = PipelineEnrollmentCloud(request, adapter.review.origin(data), command_runner=command,
                                              opener=SimpleNamespace(open=open_request))
        current.request_config = request
        transport().cloud = current
        return current

    adapter.cloud_factory = factory
    operation = str(uuid4())
    if competing:
        with pytest.raises(PipelineError, match="active-or-queued-remote-run"):
            adapter.prepare(data, operation)
        assert not transport().writes and not calls
    else:
        plan = adapter.prepare(data, operation)
        result = adapter.execute(plan["stages"][0], record_for(data, plan, operation))
        assert result["enrollment_complete"] and result["status"] == "continuation-required"
        assert current.operator_id == native.te.OPERATOR
        assert current.operator_id != result["binding_candidate"]["deployment_object_id"]
        assert all(key[0] != native.en.ADO_AUDIENCE for key in current.tokens)
        assert secret not in boot.canonical(plan).decode()
        assert secret not in boot.canonical(result).decode()
    assert headers and set(headers) == {"Bearer " + secret}
    assert dict(os.environ) == before_env
    assert secret not in str(calls)
    assert all(secret.encode() not in path.read_bytes() for path in workspace.rglob("*") if path.is_file())
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_observe_incomplete_enrollment_never_performs_ensure(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    with pytest.raises(PipelineError, match="not-observed"):
        adapter.observe(plan["stages"][0], record_for(data, plan, operation))
    assert not transport().writes
    assert all(row[0] == "GET" for row in transport().provider.calls)


def test_existing_unowned_group_is_not_adopted(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    request = adapter._inputs(data, operation)
    adapter._cloud(request)
    transport().resources[request["scopes"][0]] = {
        "id": request["scopes"][0], "location": "swedencentral", "tags": {}}
    with pytest.raises(PipelineError, match="prerequisites-blocked"):
        adapter.prepare(data, operation)
    assert not transport().writes


def test_provider_context_and_source_hash_are_bound(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    adapter.provider_context = {
        "request_digest": digest(data), "provider": "gha", "run_id": 42, "run_attempt": 1,
        "consumer_commit": "b" * 40, "source_commit": "wrong",
    }
    with pytest.raises(PipelineError, match="provider-context-mismatch"):
        adapter.prepare(data, operation)
    assert transport() is None
    adapter.provider_context["source_commit"] = data["source"]["commit"]
    plan = adapter.prepare(data, operation)
    hashes = adapter._source()
    hashes[boot.SOURCE_FILES[0]] = "0" * 64
    adapter._source = lambda: hashes
    with pytest.raises(PipelineError, match="executable-source-changed"):
        adapter.execute(plan["stages"][0], record_for(data, plan, operation))
    assert not transport().writes


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("expected", ["original", "omitted", "wrong"])
def test_continuation_provider_context_binds_original_input_not_transformed_snapshot(workspace, provider, expected):
    data = snapshot(provider)
    original_digest = digest(data)
    data["document"]["generation"] = "continued-after-admission-installation"
    adapter, _, transport = harness(workspace, data)
    adapter.provider_context = {
        "request_digest": original_digest, "provider": provider, "run_id": 42, "run_attempt": 1,
        "consumer_commit": "b" * 40, "source_commit": data["source"]["commit"],
    }
    kwargs = {} if expected == "omitted" else {
        "input_snapshot_hash": original_digest if expected == "original" else "0" * 64}
    if expected == "original":
        plan = adapter.prepare(data, str(uuid4()), **kwargs)
        assert plan["provider_context"]["request_digest"] == original_digest
        assert plan["stages"][0]["snapshot_hash"] == digest(data) != original_digest
        assert not transport().writes
    else:
        with pytest.raises(PipelineError, match="provider-context-mismatch"):
            adapter.prepare(data, str(uuid4()), **kwargs)
        assert transport() is None


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_cross_run_observation_uses_current_authenticated_origin_without_replaying(workspace, provider):
    data = snapshot(provider)
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    record = record_for(data, plan, operation)
    completed = adapter.execute(plan["stages"][0], record)
    current_origin = {**plan["origin"], "run_id": "99"}
    adapter.review.origin = Mock(return_value=current_origin)
    adapter.review.verify = Mock(side_effect=AssertionError("Observation does not execute old approval"))
    cloud_factory = adapter._cloud
    origins = []

    def observing_cloud(request, origin=None):
        origins.append(copy.deepcopy(origin))
        return cloud_factory(request, origin)

    adapter._cloud = observing_cloud
    writes, provider_calls = len(transport().writes), len(transport().provider.calls)
    assert adapter.observe(plan["stages"][0], record) == completed
    assert origins == [current_origin] and plan["origin"]["run_id"] == "42"
    adapter.review.origin.assert_called_once_with(record["snapshot"])
    assert len(transport().writes) == writes
    assert all(row[0] == "GET" for row in transport().provider.calls[provider_calls:])
    record["snapshot"]["source"]["commit"] = "c" * 40
    with pytest.raises(PipelineError, match="record-hash-mismatch"):
        adapter.observe(plan["stages"][0], record)
    assert len(origins) == 1


@pytest.mark.parametrize("invalid", ["", "not-a-digest", "a" * 63, 42])
def test_invalid_continuation_input_hash_is_rejected_before_cloud_reads(workspace, invalid):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    with pytest.raises(PipelineError, match="input-snapshot-hash-invalid"):
        adapter.prepare(data, str(uuid4()), input_snapshot_hash=invalid)
    assert transport() is None


def test_common_scope_expression_uses_the_canonical_resolved_name(workspace):
    data = snapshot()
    data["variables"][native.te.PROJECT]["dev"]["commonResourceGroup_param"] = "$(admin_aifactoryPrefixRG)-common-custom"
    adapter, _, _ = harness(workspace, data)
    plan = adapter.prepare(data, str(uuid4()))
    assert f"/subscriptions/{native.te.SUB}/resourcegroups/acme-ai-common-custom" in plan["stages"][0]["enrollment"]["scopes"]


def test_missing_project_ownership_on_observation_is_not_success(workspace):
    data = snapshot()
    adapter, _, transport = harness(workspace, data)
    operation = str(uuid4())
    plan = adapter.prepare(data, operation)
    record = record_for(data, plan, operation)
    adapter.execute(plan["stages"][0], record)
    project = adapter._physical(data)["project"]
    transport().resources[project]["tags"].pop("aifactory.logical_project_id")
    before = len(transport().writes)
    with pytest.raises(PipelineError, match="groups-incompatible"):
        adapter.observe(plan["stages"][0], record)
    assert len(transport().writes) == before


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_initial_schema2_native_bootstrap_persists_canonical_binding_and_fresh_continuation(workspace, provider):
    import lifecycle_admission as shared
    import pipeline_configuration as configuration
    import pipeline_inputs as inputs
    import pipeline_lifecycle as runtime
    from pipeline_lifecycle_adapters import RepositoryJournal
    from pipeline_lifecycle_admission import NativeAdmission
    from pipeline_lifecycle_recovery import continuation_snapshot, input_hash

    spec = {"factory": "acme-ai", "prefix": "acme-", "region": "swedencentral", "region_short": "sdc",
            "tenant": native.te.TENANT, "subscription": native.te.SUB, "provider": provider,
            "environment": "dev", "scale_set": "001", "project": "007", "cidr": "10.140.0.0/18",
            "max_projects": 7, "version": "main", "network_mode": "private"}
    document = configuration.initial_document(ROOT, spec)
    root = "customers/acme/azurefactory"
    (workspace / "customers" / "acme").mkdir(parents=True)
    configuration.write_new_root(workspace, root, document)
    original_register = workspace / "customers" / "acme" / "azurefactory" / "register.json"
    original_bytes = original_register.read_bytes()
    request = {"schema": 1, "scenario": 1, "provider": provider, "factory": "acme-ai",
               "environment": "dev", "scale_set": "001", "project": "007", "azurefactory_root": root,
               "source_ref": "refs/heads/main", "source_commit": "a" * 40}
    data = inputs.resolve_document(document, request, operational=snapshot(provider)["binding"])
    inputs.validate_register(data["document"])
    original_hash = digest(data)
    adapter, _, transport = harness(workspace, data)
    enrollment_request = adapter._inputs(data, str(uuid4()))
    adapter._cloud(enrollment_request)
    state_cloud = native.en.Cloud(enrollment_request, command_runner=transport().run, opener=transport())
    state_cloud.read_only = False
    provider_store = native.ps.ProviderState(state_cloud, enrollment_request["route"], PipelineError)
    factory_id, scale_id = data["factory"]["id"], data["scales"][0]["id"]
    policy = {"repository": data["binding"]["repository"], "factories": {factory_id: {
        "all_writers": shared.PROTOCOL, "shared_scopes": [], "operations": sorted(shared.OPERATIONS),
        "routes": ["api", "pipeline"], "scopes": enrollment_request["scopes"]}}}
    installed = provider_store.empty()
    installed["records"][shared.RECORD] = shared.new_record(policy, {factory_id: document})
    provider_store.replace(None, installed)
    current_origin = adapter.review.origin(data)
    adapter.review.origin = lambda _: copy.deepcopy(current_origin)
    proofs = []

    def verified_review(record):
        assert record["plan"]["origin"] == current_origin
        proofs.append((record["operation_id"], record["plan_hash"], current_origin["run_id"]))
        return {"provider": provider, "run_id": current_origin["run_id"], "attempt": 1,
                "operation_id": record["operation_id"], "plan_hash": record["plan_hash"]}

    adapter.review.verify = verified_review
    adapter.review.verify_finalizer = lambda record: {
        **verified_review(record), "proof_kind": "offline-authenticated-native-finalizer",
        "execution_job_id": "verified-terminal-execution-job"}
    adapter.review.get = lambda _: {
        "id": int(current_origin["run_id"]), "run_attempt": 1, "head_sha": current_origin["commit"],
        "sourceVersion": current_origin["commit"], "status": "in_progress", "conclusion": None, "result": None}
    journal = RepositoryJournal(provider_store)
    admission = NativeAdmission(provider_store, adapter.review, adapter)
    adapter.admission = admission
    engine = runtime.LifecycleService(store=journal, planner=adapter, executor=adapter, review=adapter.review,
                                      admission=admission, configuration=admission)
    prepared = engine.prepare(data)
    assert prepared["status"] == "prepared" and prepared["snapshot_hash"] == original_hash
    assert prepared["plan"]["configuration"]["baseline"]["document"] == document
    assert not transport().writes and not proofs
    outcome = engine.execute(prepared["operation_id"], data, prepared["plan_hash"])
    assert outcome["status"] == "continuation-required", outcome.get("error_code")
    assert outcome["admission"]["status"] == "provider-completion-pending"
    _, pending = provider_store.read()
    assert pending["records"][shared.RECORD]["claim"] == outcome["admission_claim"]
    canonical = admission.guard.canonical_configuration(factory_id)
    inputs.validate_register(canonical["document"])
    persisted_binding = canonical["document"]["bindings"][factory_id][provider]
    verified_binding = outcome["stages"][0]["receipt"]["binding_candidate"]
    assert persisted_binding == verified_binding
    scopes = set(enrollment_request["scopes"])
    persisted_scale = next(row for row in canonical["document"]["factories"][0]["scale_sets"]
                           if row["id"] == scale_id)
    assert set(map(str.lower, persisted_scale["owned_resource_ids"])) == scopes
    assert set(pending["enrollment"]["scopes"]) == scopes
    assert pending["enrollment"]["writers"]["platform-writer"]["deployment_object_id"] == native.te.PRINCIPAL
    assert canonical["revision"] == digest(canonical["document"]) != digest(document)
    assert canonical["document"]["factories"][0]["status"] == "draft"
    writes = len(transport().writes)
    finalized = engine.finalize(prepared["operation_id"], data, prepared["plan_hash"])
    assert finalized["status"] == "continuation-required"
    assert finalized["admission"]["status"] == "released"
    assert finalized["finalization"]["status"] == "succeeded"
    _, released = provider_store.read()
    assert released["active"] is None and released["records"][shared.RECORD]["claim"] is None
    assert released["records"][shared.RECORD]["history"]
    assert len(transport().writes) == writes
    assert RepositoryJournal(provider_store).read(prepared["operation_id"])[1] == finalized
    assert input_hash(finalized) == original_hash
    next_snapshot = continuation_snapshot(finalized, data)
    assert next_snapshot["document"] == canonical["document"]
    assert next_snapshot["azurefactory_root"] == next_snapshot["request"]["azurefactory_root"] == root
    assert not adapter.needed(next_snapshot)
    assert next_snapshot["source"] == data["source"]
    assert digest(next_snapshot) != original_hash

    # Native deployment compilation/execution is covered by the downstream matrix.
    # Here only stop at its preparation boundary, retaining the real bootstrap executor.
    boundary_calls = []
    current_origin["run_id"] = "99"

    def next_prepare(resolved, operation_id, *, input_snapshot_hash):
        boundary_calls.append((copy.deepcopy(resolved), operation_id, input_snapshot_hash))
        return {"origin": adapter.review.origin(resolved), "stages": [
            {"id": "downstream-compilation-boundary", "kind": "downstream-compilation-boundary"}]}

    engine.planner = SimpleNamespace(prepare=next_prepare)
    child = engine.prepare_continuation(finalized["operation_id"], data, finalized["plan_hash"])
    assert boundary_calls == [(next_snapshot, child["operation_id"], original_hash)]
    assert child["status"] == "prepared" and child["stages"][0]["status"] == "pending"
    assert child["plan"]["origin"]["run_id"] == "99" and finalized["plan"]["origin"]["run_id"] == "42"
    assert child["plan_hash"] != finalized["plan_hash"]
    assert child["plan"]["input_snapshot_hash"] == original_hash == input_hash(child)
    assert child["snapshot"]["azurefactory_root"] == root
    assert child["plan"]["configuration"]["baseline"] == canonical
    assert all(proof[0] != child["operation_id"] for proof in proofs)
    assert len(transport().writes) == writes
    assert original_register.read_bytes() == original_bytes
    assert data["document"] == document and digest(data) == original_hash
