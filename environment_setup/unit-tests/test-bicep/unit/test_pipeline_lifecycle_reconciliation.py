"""Retained native claims: real reconciliation state machine, offline transports."""

import copy
import importlib
from unittest.mock import Mock
from uuid import uuid4

import pytest

from .test_factory_lifecycle import (
    fl, GROUP, COMMON, ClosureCloud, owned_group_manifest, scoped_manifest, PlanCloud, seal,
    no_real_services, workspace,
)
from .test_single_writer_deletion import single_writer, factory_single_writer, project_single_writer
from .test_pipeline_lifecycle_authorization import Provider
from .test_pipeline_lifecycle_native import commands


@pytest.fixture
def reconciliation(monkeypatch):
    module = importlib.import_module("pipeline_lifecycle_reconciliation")
    monkeypatch.setattr(module, "fl", fl)
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=AssertionError("Factory API forbidden")))
    monkeypatch.setattr("urllib.request.build_opener", Mock(side_effect=AssertionError("real HTTP forbidden")))
    return module


def fixture(module, scenario=5, provider="ado", native_case=None):
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest, now
    if native_case is not None:
        manifest, cloud, remote = native_case
    elif scenario < 4:
        manifest, templates = scoped_manifest(
            () if scenario == 2 else ("017",),
            operation={1: "create-factory", 2: "create-scaleset", 3: "deploy-project"}[scenario])
        cloud = PlanCloud(manifest, templates)
        manifest["locks"]["common_dependencies"] = []
        cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
        remote = single_writer(manifest, cloud, provider)
        seal(manifest)
    elif scenario == 4:
        manifest, cloud, remote = project_single_writer(kind=provider)
    elif scenario == 5:
        cloud = ClosureCloud()
        manifest = owned_group_manifest(cloud)
        manifest["locks"]["common_dependencies"] = []
        cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
        remote = single_writer(manifest, cloud, provider)
        seal(manifest)
    else:
        manifest, cloud, remote = factory_single_writer(provider)
    cloud.bodies = copy.deepcopy(cloud.bodies)
    locks = fl.coordination(cloud, manifest)
    if scenario >= 4:
        cohort = fl._RepositoryDeletionCohort([fl._RepositoryDeletionMember(cloud, manifest)])
        cohort.acquire()
        cohort.claim_runs()
    else:
        locks.acquire()
        locks.claim_run()
    state = remote.state()
    run_key = "runs/" + manifest["run_id"] + ".json"
    receipt = state["records"][run_key]
    receipt.update(status="reconciliation-required", mutation_started=True,
                   source_commit=manifest["source"]["commit"], target=manifest["target"])
    if scenario in (1, 2, 3, 6):
        receipt["remote_run"] = {"kind": provider, "run_id": 44, **({"pipeline_id": 8} if provider == "ado" else {})}
        state["records"]["runs/" + manifest["run_id"] + ".worker.json"] = {
            "schema": 1, "run_id": manifest["run_id"], "manifest_hash": manifest["manifest_hash"],
            "source_commit": manifest["source"]["commit"], "target": manifest["target"],
            "status": "reconciliation-required", "mutation_started": True, "ownership": [], "resource_groups": []}
    if scenario >= 4:
        receipt["cohort_hash"] = state["active"]["cohort_hash"]
        state["records"]["cohorts/" + state["active"]["cohort_hash"] + ".json"] = {
            "status": "reconciliation-required", "cohort_hash": state["active"]["cohort_hash"],
            "factory_id": manifest["target"]["factory_id"], "source_commit": manifest["source"]["commit"],
            "source_ref": manifest["source"]["ref"], "children": [copy.deepcopy(receipt)]}
    scopes = sorted({scope.lower() for scope in manifest["locks"]["scopes"] + manifest["locks"]["common_dependencies"]})
    factory = manifest["target"]["factory_id"]
    snapshot = {"request": {"scenario": scenario, "provider": provider}, "factory": {"id": factory},
                "scales": [{"id": manifest["target"]["scaleset_id"]}], "projects": [],
                "document": {"schema_version": 2, "ownership_evidence": {}}, "source": manifest["source"]}
    origin = {"provider": provider, "run_id": "42", "attempt": 1, "commit": manifest["route"]["commit"],
              "ref": manifest["route"]["ref"],
              "repository": "org/consumer" if provider == "gha" else manifest["route"]["repository"]}
    prior = {"schema": 1, "operation_id": str(uuid4()), "prepared_at": now(),
             "status": "reconciliation-required", "snapshot": snapshot, "snapshot_hash": digest(snapshot),
             "plan": {"origin": origin, "stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": [manifest]}]},
             "stages": [{"id": "lifecycle", "status": "reconciliation-required"}]}
    prior["plan_hash"] = digest(bound_plan(prior))
    prior["admission_claim"] = {"protocol": outer.PROTOCOL, "id": str(uuid4()),
                                "operation_id": prior["operation_id"], "factory_id": factory, "route": "pipeline",
                                "review_digest": prior["plan_hash"], "scopes": scopes,
                                "configuration_revision": digest(snapshot["document"])}
    policy = {"repository": state["repository"], "factories": {factory: {
        "all_writers": outer.PROTOCOL, "routes": ["api", "pipeline"], "operations": sorted(outer.OPERATIONS),
        "shared_scopes": [], "scopes": scopes}}}
    state["records"][outer.RECORD] = outer.new_record(policy, {factory: snapshot["document"]})
    state["records"][outer.RECORD]["claim"] = copy.deepcopy(prior["admission_claim"])
    state["records"]["pipeline-lifecycle/" + prior["operation_id"] + ".json"] = copy.deepcopy(prior)
    store = Provider(state, provider)
    review, admission = Mock(), Mock(spec=["assert_owned"])
    current = {**origin, "run_id": "43"}
    review.origin.return_value = current
    review.verify.return_value = current
    observed = {"repository": state["repository"], "factory_id": factory, "scopes": scopes,
                "inventory_complete": True, "active_operations": [],
                "parent": {**origin, "status": "completed", "result": "cancelled"},
                "children": [{"run_id": manifest["run_id"], "manifest_hash": manifest["manifest_hash"],
                              "resources": [{"id": GROUP, "owner": {"factory_id": factory}, "present": True}],
                              "dependencies": [], "permissions": [{"actions": ["*"], "notActions": []}],
                              "observer_object_id": manifest["identity"]["object_id"],
                              "worker": {"status": "completed", "result": "failed"} if "remote_run" in receipt else None}]}
    evidence = Mock(side_effect=lambda *_: copy.deepcopy(observed))
    service = module.RetainedClaimReconciliation(store, review=review, admission=admission, evidence=evidence)
    operation = str(uuid4())
    stage = service.prepare(snapshot, prior, operation)
    record = {"schema": 1, "operation_id": operation, "prepared_at": now(), "status": "prepared",
              "snapshot": copy.deepcopy(snapshot), "snapshot_hash": digest(snapshot),
              "plan": {"origin": current, "stages": [stage]},
              "stages": [{"id": stage["id"], "status": "pending"}]}
    record["plan_hash"] = digest(bound_plan(record))
    return service, store, snapshot, prior, stage, record, evidence, observed, cloud, review, admission


def acquire_and_execute(service, stage, record):
    record["admission_claim"] = service.acquire(record)
    record["status"] = "running"
    record["stages"][0]["status"] = "running"
    return service.execute(stage, record)


def completed_case(module, scenario=5, provider="ado", released=False, native_case=None):
    import lifecycle_admission as outer
    case = fixture(module, scenario, provider, native_case)
    _, store, _, prior, stage, _, _, observed, *_ = case
    document = stage["manifests"][0]
    store.value["active"] = None
    for key, receipt in store.value["records"].items():
        if key.startswith(("runs/", "cohorts/")) and "status" in receipt:
            receipt["status"] = "succeeded"
            for child in receipt.get("children", []):
                child["status"] = "succeeded"
    prior["status"] = "succeeded"
    store.value["records"][module._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    child = observed["children"][0]
    child["outcome"] = {"status": "succeeded", "verified": True}
    if child["worker"]:
        child["worker"]["result"] = "success" if provider == "gha" else "succeeded"
    if released:
        admission = store.value["records"][outer.RECORD]
        admission["claim"] = None
        admission["history"][prior["admission_claim"]["id"]] = {
            "claim": copy.deepcopy(prior["admission_claim"]), "observation": {
                "run_id": prior["plan"]["origin"]["run_id"], "repository": store.value["repository"],
                "terminal": True, "inventory_complete": True, "active_operations": [], "evidence_id": "finalized"}}
    return case


def prepare_completed(case):
    from pipeline_lifecycle import bound_plan, digest
    service, _, snapshot, prior, _, record, *_ = case
    stage = service.prepare(snapshot, prior, record["operation_id"])
    record["plan"]["stages"] = [stage]
    record["plan_hash"] = digest(bound_plan(record))
    return stage


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
@pytest.mark.parametrize("released", [False, True])
def test_completed_native_outer_recovery_is_one_cas_without_replay(reconciliation, scenario, provider, released):
    import lifecycle_admission as outer
    case = completed_case(reconciliation, scenario, provider, released)
    service, store, _, prior, _, record, *_ = case
    before = copy.deepcopy(store.value)
    stage = prepare_completed(case)
    assert stage["reconciliation"]["completed_outcome"] is True
    assert stage["reconciliation"]["requires_reprepare"] is False
    assert stage["reconciliation"]["outer_released"] is released
    result = acquire_and_execute(service, stage, record)
    assert result["completed_outcome"] is True
    assert result["requires_reprepare"] is False and result["continuation_required"] is False
    assert result["children"][0]["native"]["status"] == "succeeded"
    assert store.value["active"] is None and len(store.writes) == 1
    assert store.value["records"][outer.RECORD]["canonical"] == before["records"][outer.RECORD]["canonical"]
    if released:
        key = prior["admission_claim"]["id"]
        assert store.value["records"][outer.RECORD]["history"][key] == before["records"][outer.RECORD]["history"][key]
    for key, value in before["records"].items():
        if key.startswith(("runs/", "cohorts/")):
            assert store.value["records"][key] == value
    assert service.observe(stage, record)["completed_outcome"] is True
    assert len(store.writes) == 1


@pytest.mark.parametrize("defect", ["run", "claim", "worker", "provider", "outcome", "pending", "history", "active"])
def test_completed_native_requires_exact_success_and_audited_outer(reconciliation, defect):
    case = completed_case(reconciliation, 3, released=True)
    _, store, _, prior, old_stage, _, _, observed, *_ = case
    prefix = "runs/" + old_stage["manifests"][0]["run_id"]
    if defect in ("run", "worker"):
        suffix = ".worker.json" if defect == "worker" else ".json"
        store.value["records"][prefix + suffix]["status"] = "reconciliation-required"
    elif defect == "claim":
        store.value["records"].pop(prefix + ".claim.json")
    elif defect == "pending":
        store.value["records"][prefix + ".worker.json"]["pending_deployment"] = "/unknown"
    elif defect == "provider":
        observed["children"][0]["worker"]["result"] = "failed"
    elif defect == "outcome":
        observed["children"][0]["outcome"]["verified"] = False
    elif defect == "history":
        import lifecycle_admission as outer
        store.value["records"][outer.RECORD]["history"][prior["admission_claim"]["id"]]["claim"]["id"] = str(uuid4())
    else:
        store.value["active"] = {"kind": "foreign"}
    with pytest.raises((ValueError, fl.Blocked), match="reconciliation-"):
        prepare_completed(case)
    assert store.writes == []


def test_completed_native_still_requires_new_protected_review(reconciliation):
    case = completed_case(reconciliation)
    service, store, _, _, _, record, _, _, _, review, _ = case
    prepare_completed(case)
    review.verify.side_effect = ValueError("new-protected-review-required")
    with pytest.raises(ValueError, match="new-protected-review"):
        service.acquire(record)
    assert store.writes == []


def test_completed_native_residual_prepare_cannot_replay_effects(reconciliation):
    case = completed_case(reconciliation)
    service, _, snapshot, _, _, record, *_ = case
    stage = prepare_completed(case)
    acquire_and_execute(service, stage, record)
    planner = Mock()
    with pytest.raises(ValueError, match="completed-native-replay-forbidden"):
        service.prepare_residual(snapshot, record, str(uuid4()), planner=planner)
    planner.prepare.assert_not_called()


def install_completed_evidence(module, case, monkeypatch):
    _, store, _, _, stage, _, _, _, cloud, *_ = case
    runs, calls = install_native_evidence(module, case, monkeypatch)
    runs["44"].update(result="succeeded", conclusion="success")
    document = stage["manifests"][0]
    prefix = "runs/" + document["run_id"]
    native = store.value["records"][prefix + ".json"]
    worker = store.value["records"].get(prefix + ".worker.json")
    deployments = {}
    if "deletion" in document:
        rows = document["deletion"]["resources"] + document["deletion"]["resource_groups"]
        native["deleted_resources"] = [row["id"] for row in rows if row["delete"] and not row.get("already_absent")]
        native["observed_absent"] = [row["id"] for row in rows if row["delete"] and row.get("already_absent")]
        removed = {row["id"].lower() for row in rows if row["delete"]}
        cloud.bodies = {key: body for key, body in cloud.bodies.items()
                        if not any(key == item or key.startswith(item + "/") for item in removed)}
        if worker:
            deletion = fl.factory_deletion_module()
            worker.update(flags=document["deletion"]["flags"], project_numbers=document["target"]["project_ids"],
                          deleted_resources=[row["id"] for row in deletion.project_rows(document)],
                          projects=deletion.completed_projects(document))
        cloud.list_resources = lambda scope: [
            copy.deepcopy(body) for key, body in cloud.bodies.items()
            if not fl.RG_ID.fullmatch(key) and fl.arm_scope(key) == scope.lower()
            and len(fl.resource_type_from_id(key).split("/")) == 2]
        cloud.collection = lambda path, api_version, extension=False: (
            [copy.deepcopy(body) for key, body in cloud.bodies.items()
             if key.startswith(path.lower() + "/") and "/" not in key[len(path) + 1:]], None)
    else:
        owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
        worker.update(deployments=[{"step_id": step["id"], "status": "succeeded",
                                   "id": fl.deployment_endpoint(document, step).removeprefix(fl.ARM)}
                                  for step in document["deployment"]["steps"]],
                      resource_groups=[{"resource_id": scope, "owner": owner,
                                        "body_hash": fl.digest(cloud.bodies[scope.lower()])}
                                       for scope in document["locks"]["scopes"]],
                      ownership=[{"resource_id": key, "owner": owner, "body_hash": fl.digest(body),
                                  "api_version": "2024-05-01"}
                                 for key, body in cloud.bodies.items() if not fl.RG_ID.fullmatch(key)],
                      inventory_closure_hash="a" * 64)
        deployments.update({row["id"].lower(): {"id": row["id"], "properties": {"provisioningState": "Succeeded"}}
                            for row in worker["deployments"]})
    original_request = cloud.request

    def arm(method, resource_id, api_version, allowed=(200,), headers=None):
        assert method == "GET", "completed recovery cannot mutate Azure"
        calls.append(resource_id)
        body = cloud.bodies.get(resource_id.lower())
        if body is not None:
            return 200, {}, copy.deepcopy(body)
        code = "ResourceGroupNotFound" if fl.RG_ID.fullmatch(resource_id) else "ResourceNotFound"
        return 404, {}, {"error": {"code": code}}

    def request(method, url, audience, *args, **kwargs):
        path = url.removeprefix(fl.ARM).split("?")[0].lower()
        if path in deployments:
            assert method == "GET"
            calls.append(url)
            return 200, {}, copy.deepcopy(deployments[path])
        return original_request(method, url, audience, *args, **kwargs)

    cloud.arm, cloud.request = arm, request
    return runs, calls, deployments


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
@pytest.mark.parametrize("released", [False, True])
def test_completed_native_live_expected_effects_are_verified_without_writes(
        reconciliation, monkeypatch, provider, scenario, released):
    case = completed_case(reconciliation, scenario, provider, released)
    _, calls, _ = install_completed_evidence(reconciliation, case, monkeypatch)
    stage = prepare_completed(case)
    service, store, _, _, _, record, *_ = case
    result = acquire_and_execute(service, stage, record)
    assert result["completed_outcome"] and not result["requires_reprepare"]
    assert result["live_evidence"]["children"][0]["outcome"]["verified"]
    assert len(store.writes) == 1
    assert any("/permissions?" in path for path in calls)
    assert not case[8].deleted


@pytest.mark.parametrize("defect", ["missing-resource", "failed-resource", "failed-deployment",
                                  "worker-failed", "worker-missing-step", "owner"])
def test_completed_deployment_cannot_use_receipt_success_without_live_effects(reconciliation, monkeypatch, defect):
    case = completed_case(reconciliation, 3)
    runs, _, deployments = install_completed_evidence(reconciliation, case, monkeypatch)
    _, store, _, _, stage, _, _, _, cloud, *_ = case
    worker = store.value["records"]["runs/" + stage["manifests"][0]["run_id"] + ".worker.json"]
    resource_id = worker["ownership"][0]["resource_id"]
    if defect == "missing-resource":
        cloud.bodies.pop(resource_id)
    elif defect == "failed-resource":
        cloud.bodies[resource_id]["properties"]["provisioningState"] = "Failed"
    elif defect == "failed-deployment":
        next(iter(deployments.values()))["properties"]["provisioningState"] = "Failed"
    elif defect == "worker-failed":
        runs["44"]["result"] = "failed"
    elif defect == "worker-missing-step":
        worker["deployments"].pop()
    else:
        cloud.bodies[resource_id]["tags"][fl.TAG_KEYS["factory_id"]] = "other"
    with pytest.raises((ValueError, fl.Blocked)):
        prepare_completed(case)
    assert store.writes == []


def test_completed_delete_reappeared_resource_keeps_outer_claim(reconciliation, monkeypatch):
    case = completed_case(reconciliation)
    original = copy.deepcopy(case[8].bodies)
    install_completed_evidence(reconciliation, case, monkeypatch)
    case[8].bodies = original
    with pytest.raises(ValueError, match="reconciliation-completed-delete"):
        prepare_completed(case)
    assert case[1].writes == []


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("defect", [None, "principal", "group", "metadata"])
def test_completed_identity_only_keeps_fresh_continuation_without_replaying_producer(
        reconciliation, monkeypatch, provider, defect):
    from .test_native_foundry_lifecycle import prepare_identity_worker, identity_closure, ROOT, UAMI
    document, cloud, _ = prepare_identity_worker(monkeypatch)
    document["run_id"] = str(uuid4())
    remote = single_writer(document, cloud, provider)
    document["deployment"].pop("foundry_identity_stage")
    document["deployment"] = fl._freeze_deployment_contents(cloud, document, ROOT)
    seal(document)
    case = completed_case(reconciliation, 3, provider, native_case=(document, cloud, remote))
    service, store, _, prior, _, record, *_ = case
    receipt = fl.run_deployment_worker({
        "manifest": document, "lease_context": remote.state()["active"]["context"]},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", receipt
    for scope in document["locks"]["common_dependencies"]:
        cloud.bodies[scope.lower()] = {"id": scope, "properties": {"provisioningState": "Succeeded"}}
    prefix = "runs/" + document["run_id"]
    store.value["records"][prefix + ".worker.json"] = copy.deepcopy(receipt)
    store.value["records"][prefix + ".json"].update(completion="identity-only", continuation_required=True)
    prior["status"] = "continuation-required"
    store.value["records"][reconciliation._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    runs, _ = install_native_evidence(reconciliation, case, monkeypatch)
    runs["44"].update(result="succeeded", conclusion="success")
    monkeypatch.setattr(fl, "collect_resource_closure", identity_closure)
    writes = copy.deepcopy(cloud.arm_writes)
    if defect == "principal":
        cloud.bodies[UAMI]["properties"]["principalId"] = str(uuid4())
    elif defect == "group":
        cloud.bodies[document["deployment"]["foundry_identity_stage"]["resource_group"]]["tags"].clear()
    elif defect == "metadata":
        cloud.bodies[UAMI]["etag"] = "different-etag"
    if defect in ("principal", "group"):
        with pytest.raises((ValueError, fl.Blocked)):
            prepare_completed(case)
        assert store.writes == []
    else:
        stage = prepare_completed(case)
        result = acquire_and_execute(service, stage, record)
        assert stage["reconciliation"]["completed_outcome"] is True
        assert result["completed_outcome"] and result["continuation_required"] and result["requires_reprepare"]
        assert result["children"][0]["worker"] == receipt
        if defect == "metadata":
            assert "reconciliation-completed-receipt-diagnostic-drift" in result["warnings"]
    assert cloud.arm_writes == writes


def test_completed_canonical_transition_is_derived_from_verified_native_children(reconciliation):
    from .test_pipeline_lifecycle_configuration import record as canonical_record, register
    from pipeline_lifecycle_configuration import completed_document
    record = canonical_record(register())
    children = record["stages"][0]["observation"]["children"]
    expected = completed_document(record)
    stage = {"id": "lifecycle", "kind": reconciliation.KIND, "manifests": [],
             "reconciliation": {"continuation_required": False}}
    record["plan"]["stages"] = [stage]
    record["stages"] = [{"id": "lifecycle", "status": "running"}]
    assert reconciliation.RetainedClaimReconciliation._completed_document(stage, record, children) == expected


@pytest.mark.parametrize("foreign", [False, True])
def test_completed_observation_accepts_only_exact_canonical_promotion(reconciliation, monkeypatch, foreign):
    import lifecycle_admission as outer
    case = completed_case(reconciliation)
    service, store, _, _, _, record, *_ = case
    stage = prepare_completed(case)
    acquire_and_execute(service, stage, record)
    expected = {"schema_version": 2, "ownership_evidence": {}, "completed": True}
    monkeypatch.setattr(service, "_completed_document", lambda *_: copy.deepcopy(expected))
    replacement = {**expected, **({"foreign": True} if foreign else {})}
    store.value["records"][outer.RECORD]["canonical"][stage["reconciliation"]["factory_id"]] = {
        "document": replacement, "revision": reconciliation.digest(replacement)}
    if foreign:
        with pytest.raises(ValueError, match="reconciliation-completed-canonical-mismatch"):
            service.observe(stage, record)
    else:
        assert service.observe(stage, record)["canonical"]["document"] == replacement


@pytest.mark.parametrize("defect", ["principal", "metadata"])
def test_completed_final_observation_enforces_reviewed_identity_but_not_hash_drift(reconciliation, monkeypatch, defect):
    case = completed_case(reconciliation, 3)
    install_completed_evidence(reconciliation, case, monkeypatch)
    stage = prepare_completed(case)
    service, store, _, _, _, record, _, _, cloud, *_ = case
    acquire_and_execute(service, stage, record)
    body = next(body for key, body in cloud.bodies.items() if not fl.RG_ID.fullmatch(key))
    if defect == "principal":
        body["properties"]["principalId"] = str(uuid4())
        with pytest.raises(ValueError, match="reconciliation-completed-live-state-changed"):
            service.observe(stage, record)
    else:
        body["etag"] = "updated-metadata"
        assert service.observe(stage, record)["verified"] is True
    assert len(store.writes) == 1


@pytest.mark.parametrize("released", [False, True])
@pytest.mark.parametrize("failure", ["before", "after"])
def test_completed_outer_cas_uncertainty_never_replays_native_or_claim_write(reconciliation, monkeypatch, released, failure):
    case = completed_case(reconciliation, released=released)
    _, calls, _ = install_completed_evidence(reconciliation, case, monkeypatch)
    stage = prepare_completed(case)
    service, store, _, _, _, record, *_ = case
    store.fail = failure
    if failure == "after":
        result = acquire_and_execute(service, stage, record)
        assert result["completed_outcome"] and result["verified"]
        record["status"] = "prepared"
        assert service.acquire(record) == record["admission_claim"]
    else:
        with pytest.raises(ValueError, match="reconciliation-acquisition-outcome-uncertain"):
            service.acquire(record)
        with pytest.raises(ValueError, match="reconciliation-observe-before-reprepare-required"):
            service.acquire(record)
    assert len(store.writes) == 1
    assert sum("/permissions?" in path for path in calls) >= 2
    assert not case[8].deleted


def test_completed_released_history_change_before_acquisition_keeps_other_owner(reconciliation):
    import lifecycle_admission as outer
    case = completed_case(reconciliation, released=True)
    prepare_completed(case)
    service, store, _, prior, _, record, *_ = case
    store.value["records"][outer.RECORD]["history"][prior["admission_claim"]["id"]]["observation"]["evidence_id"] = "changed"
    with pytest.raises(ValueError, match="reconciliation-reviewed-outer-history-changed"):
        service.acquire(record)
    assert store.writes == []


def test_completed_local_delete_rejects_unexpected_remote_dispatch(reconciliation):
    case = completed_case(reconciliation)
    _, store, _, _, stage, *_ = case
    store.value["records"]["runs/" + stage["manifests"][0]["run_id"] + ".json"]["remote_run"] = {
        "kind": "ado", "run_id": 88, "pipeline_id": 8}
    with pytest.raises(ValueError, match="reconciliation-completed-unexpected-worker"):
        prepare_completed(case)
    assert store.writes == []


def test_completed_deletion_ambiguous_group_404_cannot_complete_outer(reconciliation, monkeypatch):
    case = completed_case(reconciliation)
    install_completed_evidence(reconciliation, case, monkeypatch)
    original = case[8].arm

    def ambiguous(method, resource_id, api_version, **kwargs):
        response = original(method, resource_id, api_version, **kwargs)
        return (404, {}, {}) if response[0] == 404 else response

    case[8].arm = ambiguous
    with pytest.raises(fl.Blocked, match="reconciliation-resource-group-absence-unverified"):
        prepare_completed(case)
    assert case[1].writes == []


def test_completed_deletion_must_keep_reviewed_retained_resources(reconciliation, monkeypatch):
    case = completed_case(reconciliation, 4)
    install_completed_evidence(reconciliation, case, monkeypatch)
    document = case[4]["manifests"][0]
    retained = [row for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]
                if not row["delete"]]
    assert retained
    for row in retained:
        case[8].bodies.pop(row["id"].lower(), None)
    with pytest.raises((ValueError, fl.Blocked)):
        prepare_completed(case)
    assert case[1].writes == []


def test_completed_foundry_label_cannot_replace_verified_worker_and_live_proof(reconciliation):
    case = completed_case(reconciliation, 3)
    document = copy.deepcopy(case[4]["manifests"][0])
    document["deployment"]["foundry_lifecycle"] = {"contract": "full-runtime"}
    with pytest.raises(ValueError, match="scoped-worker-steps-incomplete"):
        reconciliation.NativeReconciliationEvidence._completed_outcome(
            case[8], document, case[1].value["records"], case[8].bodies, set())
    assert case[1].writes == []


@pytest.mark.parametrize("scenario", range(1, 7))
@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_six_scenarios_review_exact_claim_without_any_resource_mutation(reconciliation, scenario, provider):
    service, store, _, _, stage, record, evidence, _, cloud, *_ = fixture(reconciliation, scenario, provider)
    before = copy.deepcopy(store.value)
    assert store.writes == []
    result = acquire_and_execute(service, stage, record)
    assert result["verified"] is True and result["status"] == "succeeded"
    assert result["requires_reprepare"] is True and result["azure_writes"] is False
    assert len(store.writes) == 1 and store.value["active"] is None
    assert store.value["enrollment"] == before["enrollment"]
    import lifecycle_admission as outer
    assert {key: store.value["records"][key] for key in before["records"] if key != outer.RECORD} == {
        key: value for key, value in before["records"].items() if key != outer.RECORD}
    assert store.value["records"][outer.RECORD]["claim"] == record["admission_claim"]
    assert store.value["records"][outer.RECORD]["canonical"] == before["records"][outer.RECORD]["canonical"]
    assert store.value["records"][result["audit_record"]]["active_before"] == before["active"]
    assert result["residual_resources"]
    assert not cloud.deleted
    assert evidence.call_count >= 2
    assert service.observe(stage, record)["verified"] is True
    assert len(store.writes) == 1


@pytest.mark.parametrize("defect", ["claim", "worker", "run", "enrollment", "policy", "canonical", "outer"])
def test_changed_reviewed_authority_or_receipts_never_release(reconciliation, defect):
    import lifecycle_admission as outer
    service, store, _, _, stage, record, *_ = fixture(reconciliation, 3)
    manifest = stage["manifests"][0]
    if defect == "claim":
        store.value["active"]["run_id"] = str(uuid4())
    elif defect in ("worker", "run"):
        suffix = ".worker.json" if defect == "worker" else ".json"
        store.value["records"]["runs/" + manifest["run_id"] + suffix]["status"] = "running"
    elif defect == "enrollment":
        store.value["enrollment"]["revision"] += 1
    elif defect == "policy":
        store.value["records"][outer.RECORD]["policy"]["factories"].clear()
    elif defect == "canonical":
        store.value["records"][outer.RECORD]["canonical"].clear()
    else:
        store.value["records"][outer.RECORD]["claim"]["id"] = str(uuid4())
    with pytest.raises((ValueError, RuntimeError), match="reconciliation-"):
        service.acquire(record)
    assert store.writes == []


def test_flags_and_hashes_never_replace_new_protected_review(reconciliation):
    service, store, _, _, stage, record, _, _, _, review, _ = fixture(reconciliation)
    record.update(approved=True, terminal=True, approval={"plan_hash": record["plan_hash"]})
    review.verify.side_effect = ValueError("protected-review-required")
    with pytest.raises(ValueError, match="protected-review-required"):
        service.acquire(record)
    assert store.writes == []


@pytest.mark.parametrize("change", ["resources", "permissions", "parent", "active_operations"])
def test_reobserve_actual_resources_and_authority_before_cas(reconciliation, change):
    service, store, _, _, stage, record, _, observed, *_ = fixture(reconciliation)
    if change == "resources":
        observed["children"][0]["resources"].append({"id": GROUP + "/unreviewed"})
    elif change == "permissions":
        observed["children"][0]["permissions"] = []
    elif change == "parent":
        observed["parent"]["status"] = "in_progress"
    else:
        observed["active_operations"] = ["other-run"]
    with pytest.raises(ValueError, match="reconciliation-"):
        service.acquire(record)
    assert store.writes == []


@pytest.mark.parametrize("failure,verified", [("after", True), ("before", False)])
def test_uncertain_cas_is_observed_never_replayed(reconciliation, failure, verified):
    service, store, _, _, stage, record, *_ = fixture(reconciliation)
    store.fail = failure
    if verified:
        assert acquire_and_execute(service, stage, record)["verified"] is True
    else:
        with pytest.raises(ValueError, match="reconciliation-acquisition-outcome-uncertain"):
            service.acquire(record)
    assert len(store.writes) == 1
    assert service.observe(stage, record)["verified"] is verified
    if verified:
        assert service.execute(stage, record)["verified"] is True
    else:
        with pytest.raises(ValueError, match="reconciliation-"):
            service.acquire(record)
    assert len(store.writes) == 1


def test_cas_conflict_preserves_concurrent_owner(reconciliation):
    service, store, _, _, stage, record, *_ = fixture(reconciliation)
    def race(provider):
        provider.head += 1
        provider.value["active"] = {"kind": "foreign"}
    store.before_write = race
    with pytest.raises(ValueError, match="reconciliation-acquisition-outcome-uncertain"):
        service.acquire(record)
    assert service.observe(stage, record)["verified"] is False
    assert store.value["active"] == {"kind": "foreign"}
    assert len(store.writes) == 1


def install_native_evidence(module, case, monkeypatch):
    """Intercept only cloud/provider transport; keep inventory and ownership helpers."""
    service, store, snapshot, prior, stage, record, _, _, cloud, review, _ = case
    document = stage["manifests"][0]
    cloud.command = commands(document)
    original_state, original_request = cloud.state_request, cloud.request
    calls = []
    runs = {
        "42": {"id": 42, "status": "completed", "result": "canceled", "conclusion": "cancelled",
               "sourceVersion": document["route"]["commit"], "head_sha": document["route"]["commit"],
               "sourceBranch": document["route"]["ref"], "head_branch": "main", "run_attempt": 1,
               "repository": {"url": document["route"]["repository"], "full_name": "org/consumer"},
               "definition": {"id": 7}},
        "44": {"id": 44, "status": "completed", "result": "failed", "conclusion": "failure",
               "sourceVersion": document["route"]["commit"], "head_sha": document["route"]["commit"],
               "sourceBranch": document["route"]["ref"], "head_branch": "aifactory-runs/" + document["run_id"],
               "run_attempt": 1, "repository": {"url": document["route"]["repository"], "full_name": "org/consumer"},
               "display_title": "factory-lifecycle [" + document["run_id"] + "]", "definition": {"id": 8}},
    }
    repository_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    for run in runs.values():
        run["repository"]["id"] = repository_id

    def provider_read(kind, method, endpoint, body, allowed):
        assert method == "GET", "cloud write forbidden"
        calls.append(endpoint)
        if "/actions/runs/" in endpoint or "/_apis/build/builds/" in endpoint:
            run = endpoint.split("?")[0].rsplit("/", 1)[1]
            return 200, {}, copy.deepcopy(runs[run])
        if "/_apis/git/repositories/consumer?" in endpoint:
            return 200, {}, {"id": repository_id, "remoteUrl": document["route"]["repository"],
                             "project": {"visibility": "private"}}
        return original_state(kind, method, endpoint, body, allowed)

    def request(method, url, audience, *args, **kwargs):
        assert method == "GET", "Azure mutation forbidden"
        calls.append(url)
        if "/providers/Microsoft.Authorization/permissions?" in url:
            return 200, {}, {"value": [{"actions": ["*"], "notActions": []}]}
        if "/providers/Microsoft.Resources/deployments?" in url and "/resourceGroups/" not in url:
            return 200, {}, {"value": []}
        return original_request(method, url, audience, *args, **kwargs)

    cloud.state_request, cloud.request = provider_read, request
    service.evidence = module.NativeReconciliationEvidence(review, cloud_factory=lambda _: cloud)
    if snapshot["request"]["scenario"] < 4:
        from .test_factory_lifecycle import simple_plan_closure
        monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    return runs, calls


def reprepare(case):
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest
    service, store, snapshot, prior, _, record, *_ = case
    store.value["records"][outer.RECORD]["claim"] = copy.deepcopy(prior["admission_claim"])
    stage = service.prepare(snapshot, prior, record["operation_id"])
    record["plan"]["stages"] = [stage]
    record["plan_hash"] = digest(bound_plan(record))
    return stage


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
def test_native_transport_proves_terminal_provider_and_live_inventory(reconciliation, monkeypatch, provider, scenario):
    case = fixture(reconciliation, scenario, provider)
    runs, calls = install_native_evidence(reconciliation, case, monkeypatch)
    stage = reprepare(case)
    service, store, _, _, _, record, *_ = case
    result = acquire_and_execute(service, stage, record)
    assert result["verified"] is True
    assert result["residual_resources"]
    assert any("/permissions?" in path for path in calls)
    assert any("/42" in path for path in calls)
    if scenario in (1, 2, 3, 6):
        assert any("/44" in path for path in calls)
    assert len(store.writes) == 1


@pytest.mark.parametrize("which,status", [("42", "in_progress"), ("44", "in_progress"), ("44", None)])
def test_native_provider_no_response_or_active_is_not_terminal(reconciliation, monkeypatch, which, status):
    case = fixture(reconciliation, 3)
    runs, _ = install_native_evidence(reconciliation, case, monkeypatch)
    runs[which]["status"] = status
    with pytest.raises(ValueError, match="reconciliation-provider-run-not-terminal"):
        reprepare(case)
    assert case[1].writes == []


@pytest.mark.parametrize("scenario", [3, 5, 6])
def test_job_killed_before_terminal_receipt_preserves_running_receipts(reconciliation, monkeypatch, scenario):
    case = fixture(reconciliation, scenario)
    service, store, _, _, _, record, *_ = case
    for key, value in store.value["records"].items():
        if key.startswith(("runs/", "cohorts/")) and "status" in value:
            value["status"] = "running"
    before = copy.deepcopy(store.value["records"])
    install_native_evidence(reconciliation, case, monkeypatch)
    stage = reprepare(case)
    assert acquire_and_execute(service, stage, record)["verified"] is True
    for key, value in before.items():
        if key.startswith(("runs/", "cohorts/")):
            assert store.value["records"][key] == value


@pytest.mark.parametrize("missing", ["worker", "run", "claim", "remote", "aggregate"])
def test_missing_durable_proof_fails_closed_even_if_provider_is_terminal(reconciliation, monkeypatch, missing):
    case = fixture(reconciliation, 6)
    service, store, _, _, stage, *_ = case
    document = stage["manifests"][0]
    prefix = "runs/" + document["run_id"]
    if missing == "remote":
        store.value["records"][prefix + ".json"].pop("remote_run")
    elif missing == "aggregate":
        store.value["records"].pop("cohorts/" + store.value["active"]["cohort_hash"] + ".json")
    else:
        store.value["records"].pop(prefix + {"worker": ".worker.json", "run": ".json", "claim": ".claim.json"}[missing])
    install_native_evidence(reconciliation, case, monkeypatch)
    with pytest.raises(ValueError, match="reconciliation-"):
        reprepare(case)
    assert store.writes == []


def test_native_live_owner_change_blocks_recovery(reconciliation, monkeypatch):
    case = fixture(reconciliation, 5)
    install_native_evidence(reconciliation, case, monkeypatch)
    cloud = case[8]
    cloud.bodies[GROUP.lower()]["tags"][fl.TAG_KEYS["factory_id"]] = "another-factory"
    with pytest.raises(ValueError):
        reprepare(case)
    assert case[1].writes == []


def test_new_native_plan_only_after_reconciliation_and_finalization(reconciliation):
    import lifecycle_admission as outer
    service, store, snapshot, _, stage, record, evidence, *_ = fixture(reconciliation, 5)
    acquire_and_execute(service, stage, record)
    planner = Mock()
    native = copy.deepcopy(stage["manifests"][0])
    native["run_id"] = str(uuid4())
    seal(native)
    planner.prepare.return_value = {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": [native]}]}
    with pytest.raises(ValueError, match="finalization-required"):
        service.prepare_residual(snapshot, record, str(uuid4()), planner=planner)
    planner.prepare.assert_not_called()
    record.update(status="continuation-required", admission={"status": "released"}, finalization={"status": "succeeded"})
    claim = store.value["records"][outer.RECORD]["claim"]
    store.value["records"][outer.RECORD]["history"][claim["id"]] = {"claim": copy.deepcopy(claim)}
    store.value["records"][outer.RECORD]["claim"] = None
    store.value["records"]["pipeline-lifecycle/" + record["operation_id"] + ".json"] = copy.deepcopy(record)
    count = evidence.call_count
    result = service.prepare_residual(snapshot, record, str(uuid4()), planner=planner)
    assert result["residual_of"]["operation_id"] == record["operation_id"]
    assert result["stages"][0]["manifests"][0]["run_id"] != stage["manifests"][0]["run_id"]
    assert evidence.call_count > count
    assert len(store.writes) == 1


def test_residual_planner_cannot_replay_previous_manifest(reconciliation):
    import lifecycle_admission as outer
    service, store, snapshot, _, stage, record, *_ = fixture(reconciliation, 5)
    acquire_and_execute(service, stage, record)
    record.update(status="continuation-required", admission={"status": "released"}, finalization={"status": "succeeded"})
    claim = store.value["records"][outer.RECORD]["claim"]
    store.value["records"][outer.RECORD]["history"][claim["id"]] = {"claim": copy.deepcopy(claim)}
    store.value["records"][outer.RECORD]["claim"] = None
    store.value["records"]["pipeline-lifecycle/" + record["operation_id"] + ".json"] = copy.deepcopy(record)
    planner = Mock()
    planner.prepare.return_value = {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": stage["manifests"]}]}
    with pytest.raises(ValueError, match="reconciliation-native-replay-forbidden"):
        service.prepare_residual(snapshot, record, str(uuid4()), planner=planner)


@pytest.mark.parametrize("state", ["Deleting", "Updating", "Accepted", "Unknown"])
def test_native_inflight_resource_is_not_quiescent(reconciliation, monkeypatch, state):
    case = fixture(reconciliation, 5)
    install_native_evidence(reconciliation, case, monkeypatch)
    case[8].bodies[GROUP.lower()]["properties"]["provisioningState"] = state
    with pytest.raises(ValueError, match="reconciliation-resource-not-terminal"):
        reprepare(case)
    assert case[1].writes == []


def test_pending_delete_without_terminal_resource_proof_is_not_retried(reconciliation, monkeypatch):
    case = fixture(reconciliation, 5)
    document = case[4]["manifests"][0]
    case[1].value["records"]["runs/" + document["run_id"] + ".json"]["pending_resource_group"] = GROUP
    install_native_evidence(reconciliation, case, monkeypatch)
    with pytest.raises(ValueError, match="reconciliation-pending-delete-unverified"):
        reprepare(case)
    assert case[1].writes == []


def test_pending_delete_is_observed_absent_without_fabricating_terminal_receipt(reconciliation, monkeypatch):
    case = fixture(reconciliation, 5)
    document = case[4]["manifests"][0]
    run_key = "runs/" + document["run_id"] + ".json"
    case[1].value["records"][run_key]["pending_resource_group"] = GROUP
    case[1].value["records"][run_key]["status"] = "running"
    for key in list(case[8].bodies):
        if key == GROUP.lower() or key.startswith(GROUP.lower() + "/"):
            del case[8].bodies[key]
    original = case[8].arm
    def arm(method, resource, api, **kwargs):
        if resource.lower() == GROUP.lower():
            return 404, {}, {"error": {"code": "ResourceGroupNotFound"}}
        return original(method, resource, api, **kwargs)
    case[8].arm = arm
    install_native_evidence(reconciliation, case, monkeypatch)
    stage = reprepare(case)
    assert acquire_and_execute(case[0], stage, case[5])["verified"] is True
    assert case[1].value["records"][run_key]["status"] == "running"
    assert case[1].value["records"][run_key]["pending_resource_group"] == GROUP


def test_native_subscription_deployment_must_be_terminal(reconciliation, monkeypatch):
    case = fixture(reconciliation, 3)
    install_native_evidence(reconciliation, case, monkeypatch)
    cloud = case[8]
    original = cloud.request
    def request(method, url, audience, *args, **kwargs):
        if "/providers/Microsoft.Resources/deployments?" in url and "/resourceGroups/" not in url:
            return 200, {}, {"value": [{"properties": {"provisioningState": "Running"}}]}
        return original(method, url, audience, *args, **kwargs)
    cloud.request = request
    with pytest.raises(ValueError, match="reconciliation-subscription-deployment-not-terminal"):
        reprepare(case)
    assert case[1].writes == []


@pytest.mark.parametrize("defect", [None, "foreign-member", "missing-member", "missing-receipt"])
def test_complete_local_cohort_membership_is_required(reconciliation, defect):
    from .test_single_writer_coordination import deletion_setup
    documents, provider, cloud = deletion_setup()
    cohort = fl._RepositoryDeletionCohort([fl._RepositoryDeletionMember(cloud, document) for document in documents])
    cohort.acquire()
    cohort.claim_runs()
    state = provider.state()
    children = []
    for document in documents:
        receipt = state["records"]["runs/" + document["run_id"] + ".json"]
        receipt.update(status="running", cohort_hash=cohort.cohort_hash, target=document["target"],
                       source_commit=document["source"]["commit"])
        children.append(copy.deepcopy(receipt))
    state["records"][cohort.record] = {
        "status": "running", "cohort_hash": cohort.cohort_hash, "factory_id": documents[0]["target"]["factory_id"],
        "source_commit": documents[0]["source"]["commit"], "source_ref": documents[0]["source"]["ref"], "children": children}
    if defect == "foreign-member":
        state["active"]["manifests"].append("e" * 64)
    elif defect == "missing-member":
        documents = documents[:1]
    elif defect == "missing-receipt":
        state["records"].pop("runs/" + documents[1]["run_id"] + ".json")
    if defect:
        with pytest.raises(ValueError, match="reconciliation-"):
            reconciliation.RetainedClaimReconciliation._native(state, documents)
    else:
        records = reconciliation.RetainedClaimReconciliation._native(state, documents)
        assert len(records) == 5
        assert all(records["runs/" + document["run_id"] + ".json"]["status"] == "running" for document in documents)


def test_observation_rejects_modified_audit_or_lost_receipt(reconciliation):
    service, store, _, _, stage, record, *_ = fixture(reconciliation)
    acquire_and_execute(service, stage, record)
    key = next(iter(stage["reconciliation"]["native_records"]))
    store.value["records"].pop(key)
    with pytest.raises(ValueError, match="reconciliation-durable-result-changed"):
        service.observe(stage, record)
    assert len(store.writes) == 1


def test_stale_host_record_is_not_prior_authority(reconciliation):
    service, store, snapshot, prior, _, _, *_ = fixture(reconciliation)
    prior["status"] = "running"
    with pytest.raises(ValueError, match="reconciliation-prior-record-not-current"):
        service.prepare(snapshot, prior, str(uuid4()))
    assert store.writes == []


def test_unknown_foundry_gate_never_invents_live_terminal_proof(reconciliation, monkeypatch):
    case = fixture(reconciliation, 3)
    document = case[4]["manifests"][0]
    key = "runs/" + document["run_id"] + ".worker.json"
    case[1].value["records"][key]["pending_foundry_gate"] = "agent-before-account"
    install_native_evidence(reconciliation, case, monkeypatch)
    with pytest.raises(ValueError, match="reconciliation-foundry-gate-proof-required"):
        reprepare(case)
    assert case[1].writes == []


def test_acquire_atomically_hands_over_outer_and_reconciles_inner(reconciliation):
    import lifecycle_admission as outer
    service, store, _, prior, stage, record, *_ = fixture(reconciliation)
    record["status"] = "prepared"
    record["stages"][0]["status"] = "pending"
    record.pop("admission_claim", None)
    store.value["records"][outer.RECORD]["claim"] = copy.deepcopy(prior["admission_claim"])
    before = copy.deepcopy(store.value)
    replacement = service.acquire(record)
    assert replacement["operation_id"] == record["operation_id"]
    assert replacement["review_digest"] == record["plan_hash"]
    assert len(store.writes) == 1
    committed = store.writes[0]
    assert committed["active"] is None
    assert committed["records"][outer.RECORD]["claim"] == replacement
    assert committed["records"][outer.RECORD]["canonical"] == before["records"][outer.RECORD]["canonical"]
    assert committed["records"][stage["reconciliation"]["audit_record"]]["claim"] == replacement
    record["admission_claim"] = replacement
    assert service.execute(stage, record)["verified"] is True
    assert len(store.writes) == 1


def test_fresh_process_adopts_only_the_exact_audited_claim(reconciliation):
    service, store, _, _, stage, record, evidence, _, _, review, admission = fixture(reconciliation)
    store.fail = "after"
    original = service.acquire(record)
    assert "admission_claim" not in record
    fresh_provider = Provider(store.value, store.route["kind"])
    fresh = reconciliation.RetainedClaimReconciliation(
        fresh_provider, review=review, admission=admission, evidence=evidence)
    count = evidence.call_count
    assert fresh.acquire(record) == original
    assert evidence.call_count > count
    assert fresh_provider.writes == []
    fresh_provider.value["records"][stage["reconciliation"]["audit_record"]]["claim"]["review_digest"] = "a" * 64
    with pytest.raises(ValueError, match="reconciliation-"):
        fresh.acquire(record)
    assert fresh_provider.writes == []


def test_read_only_execute_cannot_clear_claim_before_acquisition(reconciliation):
    service, store, _, prior, stage, record, *_ = fixture(reconciliation)
    result = service.execute(stage, record)
    assert result["verified"] is False
    assert store.value["active"] == stage["reconciliation"]["active_before"]
    import lifecycle_admission as outer
    assert store.value["records"][outer.RECORD]["claim"] == prior["admission_claim"]
    assert store.writes == []


def test_successful_worker_ownership_remains_available_to_native_residual_planner(reconciliation):
    from pipeline_lifecycle_adapters import RepositoryJournal
    case = fixture(reconciliation, 3)
    service, store, _, _, stage, record, *_ = case
    manifest = stage["manifests"][0]
    key = "runs/" + manifest["run_id"] + ".worker.json"
    worker = store.value["records"][key]
    owner = {name: manifest["target"][name] for name in ("factory_id", "scaleset_id")}
    worker.update(status="succeeded", ownership=[{
        "resource_id": GROUP + "/providers/Microsoft.Network/publicIPAddresses/residual",
        "owner": owner, "body_hash": "d" * 64}])
    stage = reprepare(case)
    result = acquire_and_execute(service, stage, record)
    record["status"] = "continuation-required"
    record["stages"][0].update(status="succeeded", receipt=result)
    store.value["records"]["pipeline-lifecycle/" + record["operation_id"] + ".json"] = copy.deepcopy(record)
    retained = RepositoryJournal(store).ownership(manifest["target"]["factory_id"], {"existing": {"keep": True}})
    resource = worker["ownership"][0]["resource_id"].lower()
    assert retained[resource]["owner"] == owner
    assert retained[resource]["ownership_evidence"] == {
        "run_id": manifest["run_id"], "receipt_hash": fl.digest(worker)}
    assert retained["existing"] == {"keep": True}
    assert store.value["records"][key] == worker


def test_partial_worker_receipt_is_preserved_but_never_forged_successful(reconciliation):
    service, store, _, _, stage, record, *_ = fixture(reconciliation, 3)
    before = copy.deepcopy(store.value["records"])
    result = acquire_and_execute(service, stage, record)
    assert result["children"] == []
    for key, value in before.items():
        if key.startswith("runs/"):
            assert store.value["records"][key] == value


def test_finalizer_observation_requires_fresh_native_quiescence(reconciliation):
    service, store, _, _, stage, record, evidence, observed, *_ = fixture(reconciliation)
    acquire_and_execute(service, stage, record)
    calls = evidence.call_count
    observed["active_operations"] = ["new-unsettled-deployment"]
    with pytest.raises(ValueError, match="reconciliation-live-evidence-incomplete"):
        service.observe(stage, record)
    assert evidence.call_count > calls
    assert len(store.writes) == 1


def test_observation_keeps_newly_observed_residuals_for_next_native_review(reconciliation):
    service, store, _, _, stage, record, _, observed, *_ = fixture(reconciliation)
    acquire_and_execute(service, stage, record)
    remaining = {"id": GROUP + "/providers/Microsoft.Network/publicIPAddresses/residual",
                 "owner": observed["children"][0]["resources"][0]["owner"], "present": True}
    observed["children"][0]["resources"].append(remaining)
    result = service.observe(stage, record)
    assert remaining in result["residual_resources"]
    assert len(store.writes) == 1


@pytest.mark.parametrize("diagnostic", ["body_hash", "etag", "observed_at"])
def test_diagnostic_drift_warns_without_replacing_live_authority(reconciliation, diagnostic):
    case = fixture(reconciliation)
    service, store, _, _, stage, record, _, observed, *_ = case
    observed["children"][0]["resources"][0][diagnostic] = "changed-diagnostic"
    result = acquire_and_execute(service, stage, record)
    assert result["verified"] is True and result["warnings"]
    assert len(store.writes) == 1


def test_native_body_and_etag_drift_warn_with_stable_identity(reconciliation, monkeypatch):
    from .test_factory_lifecycle import RULE
    case = fixture(reconciliation)
    install_native_evidence(reconciliation, case, monkeypatch)
    stage = reprepare(case)
    case[8].bodies[GROUP.lower()]["etag"] = "new-group-etag"
    case[8].bodies[RULE.lower()]["etag"] = "new-rule-etag"
    case[8].bodies[RULE.lower()]["properties"]["priority"] = 101
    result = acquire_and_execute(case[0], stage, case[5])
    assert result["verified"] is True and result["warnings"]
    assert len(case[1].writes) == 1


@pytest.mark.parametrize("field,value", [
    ("owner", {"factory_id": "foreign"}), ("references", [COMMON + "/foreign"]),
    ("resource_identity", {"id": GROUP, "principal_id": "foreign"}),
])
def test_semantic_owner_reference_or_identity_drift_still_blocks(reconciliation, field, value):
    case = fixture(reconciliation)
    case[7]["children"][0]["resources"][0][field] = value
    with pytest.raises(ValueError, match="reconciliation-live-state-changed"):
        case[0].acquire(case[5])
    assert case[1].writes == []


def test_generation_only_drift_uses_current_canonical_claim_revision(reconciliation):
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    case = fixture(reconciliation)
    service, store, _, _, stage, record, *_ = case
    current = store.value["records"][outer.RECORD]["canonical"][stage["reconciliation"]["factory_id"]]
    current["document"]["generation"] = str(uuid4())
    current["revision"] = digest(current["document"])
    result = acquire_and_execute(service, stage, record)
    assert record["admission_claim"]["configuration_revision"] == current["revision"]
    assert result["canonical"] == current and result["warnings"]
    assert len(store.writes) == 1


@pytest.mark.parametrize("error", [{}, {"error": {"code": "AuthorizationFailed"}}, "<html>proxy failure</html>"])
def test_arbitrary_group_404_is_never_absence_proof(reconciliation, monkeypatch, error):
    case = fixture(reconciliation)
    install_native_evidence(reconciliation, case, monkeypatch)
    original = case[8].arm
    def arm(method, resource, api, **kwargs):
        if resource.lower() == GROUP.lower():
            return 404, {}, error
        return original(method, resource, api, **kwargs)
    case[8].arm = arm
    with pytest.raises(ValueError, match="absence-unverified"):
        reprepare(case)
    assert case[1].writes == []


@pytest.mark.parametrize("code,accepted", [("DeploymentNotFound", True), ("AuthorizationFailed", False),
                                        ("ResourceGroupNotFound", False), ("", False)])
def test_pending_deployment_requires_specific_not_found_proof(reconciliation, code, accepted):
    document = {"target": {"subscription_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
                "locks": {"scopes": [GROUP], "common_dependencies": []}}
    endpoint = GROUP + "/providers/Microsoft.Resources/deployments/reviewed"
    cloud = Mock()
    cloud.arm.return_value = (404, {}, {"error": {"code": code}})
    if accepted:
        assert reconciliation.NativeReconciliationEvidence._pending(
            cloud, document, [{"pending_deployment": endpoint}])[0]["present"] is False
    else:
        with pytest.raises(ValueError, match="reconciliation-pending-deployment"):
            reconciliation.NativeReconciliationEvidence._pending(cloud, document, [{"pending_deployment": endpoint}])


def test_untagged_live_principal_change_is_not_hidden_by_diagnostic_hash_drift(reconciliation, monkeypatch):
    from .test_factory_lifecycle import RULE
    case = fixture(reconciliation)
    case[8].bodies[RULE.lower()]["properties"]["principalId"] = "11111111-1111-1111-1111-111111111111"
    install_native_evidence(reconciliation, case, monkeypatch)
    stage = reprepare(case)
    case[8].bodies[RULE.lower()]["properties"]["principalId"] = "22222222-2222-2222-2222-222222222222"
    with pytest.raises(ValueError, match="reconciliation-live-state-changed"):
        case[0].acquire(case[5])
    assert case[1].writes == []


@pytest.mark.parametrize("defect", ["id", "type"])
def test_resource_facts_bind_exact_live_identity_not_just_fingerprints(reconciliation, defect):
    resource = GROUP + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/reviewed"
    body = {"id": resource, "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
            "properties": {"principalId": "11111111-1111-1111-1111-111111111111"}}
    facts = reconciliation.NativeReconciliationEvidence._resource_facts(resource, body)
    assert facts["principals"]["principalId"] == body["properties"]["principalId"]
    body[defect] = resource + "-foreign" if defect == "id" else "Microsoft.Network/publicIPAddresses"
    with pytest.raises(ValueError, match="reconciliation-live-resource"):
        reconciliation.NativeReconciliationEvidence._resource_facts(resource, body)


def test_semantic_canonical_change_remains_a_hard_gate(reconciliation):
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    case = fixture(reconciliation)
    canonical = case[1].value["records"][outer.RECORD]["canonical"][case[2]["factory"]["id"]]
    canonical["document"]["unsafe_changed_configuration"] = True
    canonical["revision"] = digest(canonical["document"])
    with pytest.raises(ValueError, match="reconciliation-reviewed-authority-changed"):
        case[0].acquire(case[5])
    assert case[1].writes == []


def test_generation_drift_after_handover_preserves_exact_audited_claim(reconciliation):
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    service, store, _, _, stage, record, *_ = fixture(reconciliation)
    acquire_and_execute(service, stage, record)
    claim = copy.deepcopy(record["admission_claim"])
    canonical = store.value["records"][outer.RECORD]["canonical"][stage["reconciliation"]["factory_id"]]
    canonical["document"]["generation"] = str(uuid4())
    canonical["revision"] = digest(canonical["document"])
    result = service.observe(stage, record)
    assert result["canonical"] == canonical and result["warnings"]
    assert service.acquire(record) == claim
    assert len(store.writes) == 1
