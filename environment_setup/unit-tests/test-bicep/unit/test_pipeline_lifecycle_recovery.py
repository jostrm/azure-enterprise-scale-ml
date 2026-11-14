"""Pipeline recovery uses a new review and preserves the historical failed operation."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .test_pipeline_lifecycle_reconciliation import fixture, reconciliation


def canonical_completed_case(module, monkeypatch, scenario, provider_kind):
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest
    from .test_pipeline_lifecycle_native import production_fixture, COMMON
    from .test_pipeline_lifecycle_reconciliation import completed_case, install_completed_evidence
    from .test_single_writer_deletion import single_writer
    from .test_pipeline_inputs import register, request, inputs
    from .test_factory_lifecycle import seal

    data, cloud, _, planner, _ = production_fixture(monkeypatch, scenario, COMMON.rsplit("/", 1)[1], provider_kind)
    manifest = planner.prepare(data, "11111111-1111-4111-8111-111111111111")["stages"][0]["manifests"][0]
    remote = single_writer(manifest, cloud, provider_kind)
    if scenario == 6:
        manifest["deletion"] = module.fl.freeze_factory_deletion_pipeline(cloud, manifest, {}, [
            {"project_id": project["id"], "project_number": project["number"],
             "registered_resource_ids": data["scales"][0]["owned_resource_ids"]} for project in data["projects"]])
    seal(manifest)
    case = completed_case(module, scenario, provider_kind, native_case=(manifest, cloud, remote))
    helper, store, _, prior, *_ = case
    document = register(provider_kind)
    factory = document["factories"][0]
    original_factory, original_scale, original_project = factory["id"], factory["scale_sets"][0]["id"], factory["projects"][0]["id"]
    factory.update({key: data["factory"][key] for key in ("id", "prefix", "region")})
    scale = factory["scale_sets"][0]
    scale.update(data["scales"][0])
    project = factory["projects"][0]
    project.update(id=data["projects"][0]["id"] if data["projects"] else original_project, number="001",
                   placements=[{"environment": "dev", "scale_set_id": scale["id"]}])
    config = document["configurations"].pop(original_factory)
    config["scale_sets"] = {scale["id"]: config["scale_sets"].pop(original_scale)}
    config["projects"] = {project["id"]: config["projects"].pop(original_project)}
    config["variables"] = {project["id"]: {"dev": {
        "admin_aifactoryPrefixRG": factory["prefix"], "admin_location": factory["region"],
        "admin_locationSuffix": factory["region_short_name"], "tenantId": scale["tenant_id"],
        "dev_sub_id": scale["subscription_id"], "admin_aifactorySuffixRG": "-" + scale["suffix"],
        "project_number_000": project["number"]}, "stage_prod": {}}}
    document["configurations"] = {factory["id"]: config}
    selected = request(scenario, provider_kind)
    if "project" in selected:
        selected["project"] = "001"
    snapshot = inputs.resolve_document(document, selected)
    from pipeline_lifecycle_configuration import prepare_change
    prior.update(snapshot=snapshot, snapshot_hash=digest(snapshot))
    prior["plan"]["configuration"] = prepare_change(snapshot, {"document": document, "revision": digest(document)})
    prior["plan_hash"] = digest(bound_plan(prior))
    prior["admission_claim"].update(review_digest=prior["plan_hash"], configuration_revision=digest(document))
    store.value["records"][module._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    envelope = store.value["records"][outer.RECORD]
    envelope["canonical"] = {factory["id"]: {"document": document, "revision": digest(document)}}
    envelope["claim"] = copy.deepcopy(prior["admission_claim"])
    case = (*case[:2], snapshot, *case[3:])
    install_completed_evidence(module, case, monkeypatch)
    if scenario < 4:
        worker = store.value["records"]["runs/" + manifest["run_id"] + ".worker.json"]
        for row in worker["resource_groups"] + worker["ownership"]:
            tags = cloud.bodies[row["resource_id"].lower()]["tags"]
            row["owner"] = {name: tags[tag] for name, tag in module.fl.TAG_KEYS.items() if tag in tags}
    return case


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
@pytest.mark.parametrize("publication", ["before", "published", "response-lost"])
@pytest.mark.parametrize("released", [False, True])
@pytest.mark.parametrize("generation_drift", [False, True])
def test_completed_recovery_integrates_native_evidence_and_canonical_promotion(
        reconciliation, monkeypatch, provider_kind, scenario, publication, released, generation_drift):
    import lifecycle_admission as outer
    from pipeline_lifecycle import LifecycleService, digest
    from pipeline_lifecycle_adapters import RepositoryJournal, RuntimeAdapters
    from pipeline_lifecycle_admission import NativeAdmission
    from pipeline_lifecycle_configuration import completed_document

    helper, provider, data, prior, _, _, _, _, cloud, review, _ = canonical_completed_case(
        reconciliation, monkeypatch, scenario, provider_kind)
    envelope = provider.value["records"][outer.RECORD]
    if generation_drift:
        from uuid import uuid4
        current = copy.deepcopy(data["document"])
        current["generation"] = str(uuid4())
        envelope["canonical"] = {data["factory"]["id"]: {"document": current, "revision": digest(current)}}
        envelope["claim"] = None
        review.verify.return_value = prior["plan"]["origin"]
        prior["admission_claim"] = NativeAdmission(provider, review, Mock()).acquire(prior)
        assert prior["admission_claim"]["configuration_revision"] != prior["plan"]["configuration"]["baseline"]["revision"]
        review.verify.return_value = review.origin.return_value
        envelope = provider.value["records"][outer.RECORD]
        provider.value["records"][reconciliation._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    if publication != "before":
        stage = prior["plan"]["stages"][0]
        children = [{"native": provider.value["records"]["runs/" + doc["run_id"] + ".json"],
                     "worker": provider.value["records"].get("runs/" + doc["run_id"] + ".worker.json")}
                    for doc in stage["manifests"]]
        prior["stages"] = [{"id": stage["id"], "status": "succeeded", "receipt": {
            "status": "succeeded", "verified": True, "children": copy.deepcopy(children)}}]
        published = completed_document(prior)
        canonical = {"document": published, "revision": digest(published)}
        publisher = NativeAdmission(provider, review, Mock())
        if publication == "response-lost":
            from .test_pipeline_lifecycle_authorization import Provider
            provider.fail = "after"
            with pytest.raises(OSError, match="response lost"):
                publisher.persist(prior)
            provider = Provider(provider.value, provider_kind)
            helper.provider = provider
        else:
            prior["configuration"] = publisher.persist(prior)
        envelope = provider.value["records"][outer.RECORD]
        assert envelope["canonical"][data["factory"]["id"]] == canonical
        provider.value["records"][reconciliation._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    if released:
        envelope["history"][prior["admission_claim"]["id"]] = {
            "claim": copy.deepcopy(prior["admission_claim"]), "observation": {
                "run_id": prior["plan"]["origin"]["run_id"], "repository": provider.value["repository"],
                "terminal": True, "inventory_complete": True, "active_operations": [], "evidence_id": "finalized"}}
        envelope["claim"] = None
    native = Mock()
    native.provider_context = None
    adapters = RuntimeAdapters(native, Mock(), Mock(), reconciliation=helper)
    admission = NativeAdmission(provider, review, adapters, reconciliation=helper)
    helper.admission = admission
    engine = LifecycleService(store=RepositoryJournal(provider), planner=adapters, executor=adapters,
                              admission=admission, review=review, configuration=admission)
    review.get.return_value = {"id": 43, "run_attempt": 1, "head_sha": prior["plan"]["origin"]["commit"],
                              "sourceVersion": prior["plan"]["origin"]["commit"], "status": "in_progress"}
    prepared = engine.prepare_recovery(prior["operation_id"], data, prior["plan_hash"])
    assert prepared["snapshot"] == data
    assert prepared["plan"]["input_snapshot_hash"] == digest(data)
    assert prepared["plan"]["continuation_required"] is False
    completed = engine.execute(prepared["operation_id"], data, prepared["plan_hash"])
    assert completed["status"] == "succeeded", completed.get("error_code")
    expected = completed_document(completed)
    assert completed["configuration"]["document"] == expected
    assert expected != data["document"]
    review.verify_finalizer.return_value = {"operation_id": completed["operation_id"], "plan_hash": completed["plan_hash"]}
    finalized = engine.finalize(completed["operation_id"], data, completed["plan_hash"])
    assert finalized["admission"]["status"] == "released"
    assert engine.status(prior["operation_id"])["status"] == "recovered"
    assert engine.observe(completed["operation_id"])["configuration"]["document"] == expected
    native.prepare.assert_not_called()
    adapters.native_executor.execute.assert_not_called()
    assert not cloud.deleted and not cloud.arm_writes


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
def test_acquisition_rejects_semantic_drift_even_with_fresh_generation(reconciliation, monkeypatch, provider_kind):
    import lifecycle_admission as outer
    from uuid import uuid4
    from pipeline_lifecycle import digest
    from pipeline_lifecycle_admission import NativeAdmission
    _, provider, data, prior, _, _, _, _, _, review, _ = canonical_completed_case(
        reconciliation, monkeypatch, 3, provider_kind)
    changed = copy.deepcopy(data["document"])
    changed["generation"] = str(uuid4())
    changed["factories"][0]["prefix"] = "foreign-"
    envelope = provider.value["records"][outer.RECORD]
    envelope["canonical"] = {data["factory"]["id"]: {"document": changed, "revision": digest(changed)}}
    envelope["claim"] = None
    before = copy.deepcopy(provider.value)
    with pytest.raises(ValueError, match="canonical-configuration-changed"):
        NativeAdmission(provider, review, Mock()).acquire(prior)
    assert provider.value == before and not provider.writes


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
@pytest.mark.parametrize("defect", ["foreign-canonical", "other-operation", "claim", "native-source",
                                  "worker-target", "worker-source", "live-group"])
def test_published_recovery_rejects_unlinked_or_unverified_outcome(reconciliation, monkeypatch, provider_kind, defect):
    import lifecycle_admission as outer
    from uuid import uuid4
    from pipeline_lifecycle import LifecycleService, digest
    from pipeline_lifecycle_adapters import RepositoryJournal, RuntimeAdapters
    from pipeline_lifecycle_admission import NativeAdmission
    from pipeline_lifecycle_configuration import completed_document
    collect = reconciliation.fl.collect_resource_closure
    helper, provider, data, prior, _, _, _, _, cloud, review, _ = canonical_completed_case(
        reconciliation, monkeypatch, 3, provider_kind)
    monkeypatch.setattr(reconciliation.fl, "collect_resource_closure", collect)
    stage = prior["plan"]["stages"][0]
    document = stage["manifests"][0]
    prefix = "runs/" + document["run_id"]
    native = provider.value["records"][prefix + ".json"]
    worker = provider.value["records"][prefix + ".worker.json"]
    prior["stages"] = [{"id": stage["id"], "status": "succeeded", "receipt": {
        "status": "succeeded", "verified": True, "children": [{"native": native, "worker": worker}]}}]
    published_record = copy.deepcopy(prior)
    if defect == "other-operation":
        published_record["operation_id"] = str(uuid4())
    published = completed_document(published_record)
    if defect == "foreign-canonical":
        published["factories"][0]["prefix"] = "foreign-"
    envelope = provider.value["records"][outer.RECORD]
    envelope["canonical"] = {data["factory"]["id"]: {"document": published, "revision": digest(published)}}
    if defect == "claim":
        envelope["claim"]["operation_id"] = str(uuid4())
    elif defect == "native-source":
        native["source_commit"] = "f" * 40
    elif defect == "worker-target":
        worker["target"] = {**worker["target"], "scaleset_id": str(uuid4())}
    elif defect == "worker-source":
        worker["source_commit"] = "f" * 40
    elif defect == "live-group":
        cloud.bodies.pop(document["locks"]["scopes"][0].lower())
    provider.value["records"][reconciliation._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    planner = Mock()
    planner.provider_context = None
    adapters = RuntimeAdapters(planner, Mock(), Mock(), reconciliation=helper)
    admission = NativeAdmission(provider, review, adapters, reconciliation=helper)
    helper.admission = admission
    engine = LifecycleService(store=RepositoryJournal(provider), planner=adapters, executor=adapters,
                              admission=admission, review=review, configuration=admission)
    before = copy.deepcopy(provider.value)
    with pytest.raises((ValueError, reconciliation.fl.Blocked)):
        engine.prepare_recovery(prior["operation_id"], data, prior["plan_hash"])
    assert provider.value == before and not provider.writes


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
def test_shared_service_recovery_hands_over_exact_claim_before_residual_review(
        reconciliation, provider_kind, scenario, monkeypatch):
    from pipeline_lifecycle import LifecycleService
    from pipeline_lifecycle_adapters import RepositoryJournal
    from pipeline_lifecycle_admission import NativeAdmission
    from . import test_pipeline_lifecycle_reconciliation as fixtures
    original = fixtures.scoped_manifest
    def credential_free_manifest(*args, **kwargs):
        manifest, templates = original(*args, **kwargs)
        for section in ("dev", "stage_prod"):
            if section in manifest["config"]:
                manifest["config"][section]["servicePrincipalSecret"] = ""
        manifest["deployment"]["configuration_hash"] = fixtures.fl.digest(manifest["config"])
        fixtures.seal(manifest)
        return manifest, templates
    monkeypatch.setattr(fixtures, "scoped_manifest", credential_free_manifest)
    helper, provider, data, prior, _, _, _, _, cloud, review, _ = fixture(reconciliation, scenario, provider_kind)
    review.get.return_value = {"id": 43, "run_attempt": 1, "head_sha": prior["plan"]["origin"]["commit"],
                              "sourceVersion": prior["plan"]["origin"]["commit"], "status": "in_progress"}
    planner = Mock()
    def prepare(value, previous, operation_id, **kwargs):
        stage = helper.prepare(value, previous, operation_id)
        return {"stages": [stage], "origin": review.origin(value), "continuation_required": True}
    planner.prepare_recovery.side_effect = prepare
    admission = NativeAdmission(provider, review, helper, reconciliation=helper)
    helper.admission = admission
    configuration = SimpleNamespace(
        prepare=lambda value: {"baseline": {"document": value["document"]}, "proposal": value["document"]},
        persist=admission.persist)
    engine = LifecycleService(store=RepositoryJournal(provider), planner=planner, executor=helper,
                              admission=admission, review=review, configuration=configuration)
    prepared = engine.prepare_recovery(prior["operation_id"], data, prior["plan_hash"])
    assert prepared["plan"]["recovery_of"] == {"operation_id": prior["operation_id"], "plan_hash": prior["plan_hash"]}
    assert prepared["operation_id"] != prior["operation_id"]
    assert not cloud.deleted
    result = engine.execute(prepared["operation_id"], data, prepared["plan_hash"])
    assert result["status"] == "continuation-required"
    assert provider.value["active"] is None
    assert result["admission_claim"] != prior["admission_claim"]
    assert result["configuration"]["document"] == data["document"]
    review.verify_finalizer.return_value = {"operation_id": result["operation_id"], "plan_hash": result["plan_hash"]}
    finalized = engine.finalize(result["operation_id"], data, result["plan_hash"])
    assert finalized["admission"]["status"] == "released"
    historical = engine.status(prior["operation_id"])
    assert historical["status"] == "reconciliation-required"
    assert historical["recovery_child"] == result["operation_id"]
    assert not cloud.deleted


def test_recovery_rejects_changed_original_input_before_native_preparation(reconciliation):
    from pipeline_lifecycle import LifecycleService, PipelineError
    from pipeline_lifecycle_adapters import RepositoryJournal
    helper, provider, data, prior, *_ = fixture(reconciliation)
    planner = Mock()
    engine = LifecycleService(store=RepositoryJournal(provider), planner=planner, executor=helper,
                              admission=Mock(), review=Mock())
    changed = copy.deepcopy(data)
    changed["request"]["scenario"] = 6
    with pytest.raises(PipelineError, match="snapshot-changed"):
        engine.prepare_recovery(prior["operation_id"], changed, prior["plan_hash"])
    planner.prepare_recovery.assert_not_called()


def test_residual_continuation_keeps_reviewed_requested_settings_not_old_baseline(monkeypatch):
    import pipeline_lifecycle_recovery as recovery
    from pipeline_lifecycle import digest
    from .test_pipeline_inputs import register, request, inputs, FACTORY, PROJECT
    baseline = register()
    proposal = copy.deepcopy(baseline)
    proposal["configurations"][FACTORY]["variables"][PROJECT]["dev"]["enableAzureOpenAI"] = "true"
    data = inputs.resolve_document(proposal, request())
    record = {"snapshot": data, "snapshot_hash": digest(data), "status": "continuation-required",
              "plan": {"stages": [{"kind": "retained-claim-reconciliation"}]},
              "admission": {"status": "released"}, "finalization": {"status": "succeeded"},
              "configuration": {"document": baseline, "revision": digest(baseline)}}
    resolver = Mock(wraps=inputs.resolve_document)
    monkeypatch.setattr(inputs, "resolve_document", resolver)
    result = recovery.continuation_snapshot(record, data)
    assert result["variables"][PROJECT]["dev"]["enableAzureOpenAI"] == "true"
    resolver.assert_called_once()


def test_completed_identity_recovery_continuation_keeps_published_ownership():
    from pipeline_lifecycle import digest
    from pipeline_lifecycle_configuration import completed_document, prepare_change
    from pipeline_lifecycle_recovery import continuation_snapshot
    from .test_pipeline_lifecycle_configuration import record, register
    recovered = record(register())
    recovered["status"] = "continuation-required"
    recovered["plan"]["stages"][0].update(kind="retained-claim-reconciliation", reconciliation={
        "completed_outcome": True, "continuation_required": True, "requires_reprepare": True})
    published = completed_document(recovered)
    recovered.update(configuration={"document": published, "revision": digest(published)},
                     admission={"status": "released"}, finalization={"status": "succeeded"})
    original = copy.deepcopy(recovered["snapshot"])
    child = continuation_snapshot(recovered, original)
    change = prepare_change(child, recovered["configuration"])
    assert child["document"] == published
    assert child["document"]["ownership_evidence"]
    assert change["changes"] == []
    assert recovered["snapshot"] == original


def canonical_identity_case(module, monkeypatch, provider_kind):
    import json
    import lifecycle_admission as outer
    from uuid import uuid4
    from pipeline_lifecycle import bound_plan, digest
    from pipeline_lifecycle_configuration import prepare_change
    from .test_native_foundry_lifecycle import identity_source_case, IdentityProducerCloud, identity_closure, ROOT
    from .test_pipeline_inputs import FACTORY, SCALE, PROJECT, register, request, inputs
    from .test_pipeline_lifecycle_reconciliation import completed_case, install_native_evidence
    from .test_single_writer_deletion import single_writer
    from .test_factory_lifecycle import fl, seal
    document, templates = identity_source_case()
    document = json.loads(json.dumps(document).replace('"factory-a"', json.dumps(FACTORY))
                          .replace('"Stage001"', json.dumps(SCALE)))
    document["run_id"] = str(uuid4())
    for section in ("dev", "stage_prod"):
        document["config"][section]["servicePrincipalSecret"] = ""
    document["deployment"]["configuration_hash"] = digest(document["config"])
    foundry = document["deployment"]["foundry_lifecycle"]
    foundry["full_parameters_hash"] = digest(next(step["parameters"] for step in document["deployment"]["steps"]
                                                 if step["id"] == foundry["full_step"]))
    cloud = IdentityProducerCloud(document, templates)
    monkeypatch.setattr(fl, "collect_resource_closure", identity_closure)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    remote = single_writer(document, cloud, provider_kind)
    document["deployment"] = fl._freeze_deployment_contents(cloud, document, ROOT)
    seal(document)
    case = completed_case(module, 3, provider_kind, native_case=(document, cloud, remote))
    helper, provider, _, prior, *_ = case
    worker = fl.run_deployment_worker({"manifest": document, "lease_context": remote.state()["active"]["context"]},
                                     ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert worker["status"] == "succeeded", worker
    assert worker["completion"] == "identity-only"
    for scope in document["locks"]["common_dependencies"]:
        cloud.bodies[scope.lower()] = {"id": scope, "properties": {"provisioningState": "Succeeded"}}
    prefix = "runs/" + document["run_id"]
    provider.value["records"][prefix + ".worker.json"] = copy.deepcopy(worker)
    provider.value["records"][prefix + ".json"].update(completion="identity-only", continuation_required=True)
    canonical = register(provider_kind)
    factory, target = canonical["factories"][0], document["target"]
    factory.update(prefix=target["prefix"], region=target["region"])
    factory["scale_sets"][0].update(environment=target["environment"], tenant_id=target["tenant_id"],
                                    subscription_id=target["subscription_id"])
    factory["projects"][0].update(number="017", placements=[{"environment": target["environment"], "scale_set_id": SCALE}])
    canonical["configurations"][FACTORY]["variables"][PROJECT] = copy.deepcopy(document["config"])
    for section in ("dev", "stage_prod"):
        canonical["configurations"][FACTORY]["variables"][PROJECT][section].pop("servicePrincipalSecret")
        canonical["configurations"][FACTORY]["variables"][PROJECT][section]["admin_locationSuffix"] = factory["region_short_name"]
    snapshot = inputs.resolve_document(canonical, request(3, provider_kind) | {
        "environment": target["environment"], "project": "017"})
    prior.update(snapshot=snapshot, snapshot_hash=digest(snapshot), status="continuation-required")
    prior["plan"]["configuration"] = prepare_change(snapshot, {"document": canonical, "revision": digest(canonical)})
    prior["plan_hash"] = digest(bound_plan(prior))
    prior["admission_claim"].update(review_digest=prior["plan_hash"], configuration_revision=digest(canonical))
    provider.value["records"][module._journal_key(prior["operation_id"])] = copy.deepcopy(prior)
    envelope = provider.value["records"][outer.RECORD]
    envelope["canonical"] = {FACTORY: {"document": canonical, "revision": digest(canonical)}}
    envelope["claim"] = copy.deepcopy(prior["admission_claim"])
    case = (*case[:2], snapshot, *case[3:])
    runs, _ = install_native_evidence(module, case, monkeypatch)
    runs["44"].update(result="succeeded", conclusion="success")
    monkeypatch.setattr(fl, "collect_resource_closure", identity_closure)
    return case


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
@pytest.mark.parametrize("defect", [None, "historical-input", "target", "ownership", "finalization", "live-identity"])
def test_real_identity_recovery_finalization_can_prepare_bound_residual(
        reconciliation, monkeypatch, provider_kind, defect):
    from uuid import uuid4
    from pipeline_lifecycle import LifecycleService, digest
    from pipeline_lifecycle_adapters import RepositoryJournal, RuntimeAdapters
    from pipeline_lifecycle_admission import NativeAdmission
    from pipeline_lifecycle_recovery import continuation_snapshot
    from .test_factory_lifecycle import seal
    helper, provider, data, prior, _, _, _, _, cloud, review, _ = canonical_identity_case(
        reconciliation, monkeypatch, provider_kind)
    native = Mock()
    native.provider_context = None
    adapters = RuntimeAdapters(native, Mock(), Mock(), reconciliation=helper)
    admission = NativeAdmission(provider, review, adapters, reconciliation=helper)
    helper.admission = admission
    engine = LifecycleService(store=RepositoryJournal(provider), planner=adapters, executor=adapters,
                              admission=admission, review=review, configuration=admission)
    review.get.return_value = {"id": 43, "run_attempt": 1, "head_sha": prior["plan"]["origin"]["commit"],
                              "sourceVersion": prior["plan"]["origin"]["commit"], "status": "in_progress"}
    prepared = engine.prepare_recovery(prior["operation_id"], data, prior["plan_hash"])
    recovered = engine.execute(prepared["operation_id"], data, prepared["plan_hash"])
    assert recovered["status"] == "continuation-required", recovered.get("error_code")
    review.verify_finalizer.return_value = {"operation_id": recovered["operation_id"], "plan_hash": recovered["plan_hash"]}
    finalized = engine.finalize(recovered["operation_id"], data, recovered["plan_hash"])
    assert finalized["configuration"]["document"]["ownership_evidence"]
    writes = copy.deepcopy(cloud.arm_writes)
    if defect:
        candidate = continuation_snapshot(finalized, data)
        if defect == "historical-input":
            candidate = copy.deepcopy(data)
        elif defect == "target":
            candidate["factory"]["id"] = str(uuid4())
        elif defect == "ownership":
            candidate["document"]["ownership_evidence"] = {}
        elif defect == "finalization":
            finalized["finalization"]["status"] = "pending"
        else:
            from .test_native_foundry_lifecycle import UAMI
            cloud.bodies[UAMI]["properties"]["principalId"] = str(uuid4())
        before = copy.deepcopy(provider.value)
        with pytest.raises((ValueError, reconciliation.fl.Blocked)):
            helper.prepare_residual(candidate, finalized, str(uuid4()), planner=native)
        native.prepare.assert_not_called()
        assert provider.value == before
        assert cloud.arm_writes == writes
        return
    fresh = copy.deepcopy(prior["plan"]["stages"][0]["manifests"][0])
    fresh["run_id"] = str(uuid4())
    seal(fresh)
    native.prepare.return_value = {"origin": review.origin.return_value, "stages": [
        {"id": "lifecycle", "kind": "lifecycle", "manifests": [fresh]}]}
    child = engine.prepare_continuation(finalized["operation_id"], data, finalized["plan_hash"])
    assert child["snapshot"]["document"] == finalized["configuration"]["document"]
    assert child["plan"]["input_snapshot_hash"] == digest(data)
    assert child["plan"]["residual_of"]["operation_id"] == finalized["operation_id"]
    assert child["status"] == "prepared"
    assert native.prepare.call_args.args[0] == child["snapshot"]
    adapters.native_executor.execute.assert_not_called()
    assert cloud.arm_writes == writes
