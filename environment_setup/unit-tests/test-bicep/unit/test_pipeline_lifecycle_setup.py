"""Initial cross-route policy needs native review, not an API installation call."""

import copy
import importlib
import socket
from unittest.mock import Mock

import pytest

from .test_pipeline_inputs import FACTORY, SCALE, SUB, register, request, inputs
from .test_pipeline_lifecycle_adapters import ProviderStore


@pytest.fixture
def setup():
    return importlib.import_module("pipeline_lifecycle_setup")


@pytest.fixture(autouse=True)
def forbid_factory_api(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("Factory API forbidden")))


def fixture(module, provider_kind="gha"):
    from pipeline_lifecycle import bound_plan, digest
    store = ProviderStore()
    repo = "https://github.com/org/repo" if provider_kind == "gha" else "https://dev.azure.com/org/proj/_git/repo"
    store.value.update(repository=repo, enrollment=None)
    store.route = {"kind": provider_kind, "repository": repo}
    store.private = Mock()
    snapshot = inputs.resolve_document(register(provider_kind), request(1, provider_kind), operational={
        "schema": 1, "provider": provider_kind, "repository": repo, "consumer_ref": "refs/heads/main",
        "admission": {"writer_governance": module.GOVERNANCE}})
    scopes = [f"/subscriptions/{SUB}/resourceGroups/common", f"/subscriptions/{SUB}/resourceGroups/project007"]
    review, evidence = Mock(), Mock()
    origin = {"provider": provider_kind, "run_id": "42", "attempt": 1, "repository": repo, "ref": "refs/heads/main"}
    review.origin.return_value = origin
    review.verify.return_value = origin | {"proof_kind": "native-protected-review"}
    evidence.return_value = {"verified": True, "factory_id": FACTORY, "repository": repo,
                             "scopes": sorted(map(str.lower, scopes)), "active_operations": [],
                             "identity": {"tenant_id": snapshot["scales"][0]["tenant_id"]}}
    service = module.AdmissionSetup(store, review=review, evidence=evidence)
    operation = "11111111-1111-4111-8111-111111111111"
    plan = service.prepare(snapshot, operation, scopes)
    record = {"schema": 1, "operation_id": operation, "snapshot": snapshot, "snapshot_hash": digest(snapshot),
              "prepared_at": "2026-11-13T19:06:00+01:00", "status": "prepared", "plan": plan,
              "stages": [{"id": "install-admission", "status": "pending"}]}
    record["plan_hash"] = digest(bound_plan(record))
    return service, store, review, evidence, record


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
def test_install_and_claim_are_one_authenticated_cas(setup, provider_kind):
    import lifecycle_admission as shared
    service, store, review, evidence, record = fixture(setup, provider_kind)
    before = copy.deepcopy(store.value)
    claim = service.acquire(record)
    record["admission_claim"] = claim
    policy = store.value["records"][shared.RECORD]
    assert policy["claim"] == claim
    assert claim["review_digest"] == record["plan_hash"]
    assert policy["canonical"][FACTORY]["document"] == record["snapshot"]["document"]
    assert store.value["enrollment"] == before["enrollment"]
    assert store.value["records"]["other"] == before["records"]["other"]
    assert any(key.startswith("pipeline-admission-installations/") for key in store.value["records"])
    assert review.verify.call_count == 1
    assert evidence.call_count == 2
    observation = service.observe(record["plan"]["stages"][0], record)
    assert observation["verified"] and observation["requires_reprepare"]
    assert observation["canonical"] == policy["canonical"][FACTORY]


def test_configuration_opt_in_is_not_review_authorization(setup):
    service, store, review, _, record = fixture(setup)
    before = copy.deepcopy(store.value)
    review.verify.side_effect = ValueError("native-review-required")
    with pytest.raises(ValueError, match="native-review"):
        service.acquire(record)
    assert store.value == before


def test_no_implicit_install_without_governance_opt_in(setup):
    service, store, _, _, record = fixture(setup)
    record["snapshot"]["binding"].pop("admission")
    with pytest.raises(ValueError, match="governance"):
        service.prepare(record["snapshot"], record["operation_id"], [f"/subscriptions/{SUB}/resourceGroups/common"])
    assert "lifecycle_admission_v1" not in store.value["records"]


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(active={"uncertain": True}),
    lambda s: s["records"].update(lifecycle_admission_v1={"installed": True}),
    lambda s: s.update(enrollment={"scopes": {"/subscriptions/x/resourcegroups/foreign": {
        "target": {"factory_id": "foreign"}, "scope_kind": "aifactory-owned"}}}),
])
def test_existing_or_active_or_foreign_state_is_never_replaced(setup, mutation):
    service, store, _, _, record = fixture(setup)
    mutation(store.value)
    before = copy.deepcopy(store.value)
    with pytest.raises(ValueError):
        service.acquire(record)
    assert store.value == before


def test_uncertain_installation_reconciles_exact_audit_without_second_write(setup):
    service, store, _, _, record = fixture(setup)
    replace = store.replace
    writes = []
    def lost_reply(head, state):
        writes.append(state)
        replace(head, state)
        raise OSError("response lost")
    store.replace = lost_reply
    with pytest.raises(OSError):
        service.acquire(record)
    recovered = setup.AdmissionSetup(store, review=service.review, evidence=service.evidence)
    claim = recovered.acquire(record)
    assert len(writes) == 1
    assert claim["operation_id"] == record["operation_id"]


def test_new_live_activity_prevents_installation(setup):
    service, store, _, evidence, record = fixture(setup)
    evidence.return_value["active_operations"] = ["other-job"]
    with pytest.raises(ValueError, match="live"):
        service.acquire(record)
    assert "lifecycle_admission_v1" not in store.value["records"]


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
def test_service_installs_without_api_and_stops_for_fresh_lifecycle_review(setup, provider_kind):
    import lifecycle_admission as shared
    from pipeline_lifecycle import LifecycleService
    from pipeline_lifecycle_adapters import RepositoryJournal
    from pipeline_lifecycle_admission import NativeAdmission
    installer, provider, review, _, prepared = fixture(setup, provider_kind)
    review.get.return_value = {"id": 42, "run_attempt": 1, "head_sha": "b" * 40, "sourceVersion": "b" * 40,
                              "status": "in_progress", "conclusion": None}
    review.origin.return_value.update(commit="b" * 40)
    planner = Mock()
    scopes = prepared["plan"]["stages"][0]["setup"]["policy"]["factories"][FACTORY]["scopes"]
    planner.prepare.side_effect = lambda value, operation: installer.prepare(value, operation, scopes)
    admission = NativeAdmission(provider, review, installer, setup=installer)
    engine = LifecycleService(store=RepositoryJournal(provider), planner=planner, executor=installer,
                              review=review, admission=admission, configuration=admission)
    record = engine.prepare(prepared["snapshot"])
    result = engine.execute(record["operation_id"], record["snapshot"], record["plan_hash"])
    assert result["status"] == "continuation-required"
    assert result["configuration"]["document"] == record["snapshot"]["document"]
    assert provider.value["records"][shared.RECORD]["claim"] is not None
    review.verify_finalizer.return_value = {"operation_id": record["operation_id"], "plan_hash": record["plan_hash"]}
    finalized = engine.finalize(record["operation_id"], record["snapshot"], record["plan_hash"])
    assert finalized["admission"]["status"] == "released"
    from pipeline_lifecycle_recovery import continuation_snapshot
    next_snapshot = continuation_snapshot(finalized, record["snapshot"])
    assert not next_snapshot["document"]["bindings"]
    assert next_snapshot["binding"]["admission"]["writer_governance"] == setup.GOVERNANCE
    assert next_snapshot["binding"]["repository"] == record["snapshot"]["binding"]["repository"]


@pytest.mark.parametrize("error_code", ["ResourceGroupNotFound", "AuthorizationFailed", "NotFound"])
def test_native_setup_does_not_confuse_arbitrary_404_with_group_absence(setup, monkeypatch, error_code):
    import pipeline_lifecycle_adapters as adapters
    _, _, review, _, record = fixture(setup)
    scope = f"/subscriptions/{SUB}/resourcegroups/common"
    cloud = Mock(spec=["arm", "verify_identity", "assert_no_active_runs", "assert_no_active_deployments"])
    cloud.arm.return_value = (404, {}, {"error": {"code": error_code}})
    monkeypatch.setattr(adapters, "operation_identity", lambda *_: "cccccccc-cccc-cccc-cccc-cccccccccccc")
    evidence = adapters.NativeSetupEvidence(review, cloud_factory=lambda *_: cloud)
    if error_code == "ResourceGroupNotFound":
        assert evidence(record["snapshot"], [scope])["verified"]
    else:
        with pytest.raises(ValueError, match="absence"):
            evidence(record["snapshot"], [scope])
