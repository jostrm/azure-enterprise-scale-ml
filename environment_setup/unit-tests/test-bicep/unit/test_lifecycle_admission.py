"""Offline cross-route admission uses the actual provider-state CAS transport."""

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from unit.test_single_writer_coordination import Provider, en, ps, ROOT


spec = importlib.util.spec_from_file_location("lifecycle_admission", ROOT / "bootstrap/lib/lifecycle_admission.py")
admission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admission)

REPOSITORY = "https://github.com/org/repo"
FACTORY = "11111111-1111-4111-8111-111111111111"
SCOPE = "/subscriptions/22222222-2222-4222-8222-222222222222/resourcegroups/factory"


class Authority:
    """Trusted test authority stands for authenticated provider/identity queries."""

    def authenticate(self, request, policy):
        return {"subject": "verified-provider-principal", "run_id": request["operation_id"],
                "repository": REPOSITORY, "route": request["route"],
                "operation_id": request["operation_id"], "review_digest": request["review_digest"],
                "authorization_id": "provider-approved-review-123"}

    def observe(self, claim, evidence):
        return {"run_id": claim["identity"]["run_id"], "repository": REPOSITORY,
                "terminal": True, "inventory_complete": True, "active_operations": [],
                "evidence_id": "remote-observation-123"}


@pytest.fixture
def shared():
    provider = Provider(REPOSITORY)
    policy = {"repository": REPOSITORY, "factories": {FACTORY: {
        "scopes": [SCOPE], "routes": ["api", "pipeline"],
        "operations": sorted(admission.OPERATIONS),
        "all_writers": admission.PROTOCOL, "shared_scopes": []}}}
    store = lambda: ps.ProviderState(SimpleNamespace(state_request=provider.call),
                                    {"kind": "gha", "repository": REPOSITORY}, en.EnrollmentError)
    state = store().empty()
    state["records"][admission.RECORD] = admission.new_record(policy, {FACTORY: {"value": 1}})
    provider.set_state(state)
    return provider, store


def request(route="api", operation_id="api-job"):
    return {"factory_id": FACTORY, "operation_id": operation_id, "route": route,
            "operation": "execute", "scopes": [SCOPE],
            "configuration_revision": admission.revision({"value": 1}), "review_digest": "a" * 64}


def test_real_provider_cas_race_admits_one_route_only(shared):
    provider, store = shared
    api = admission.Admission(store(), Authority())
    pipeline = admission.Admission(store(), Authority())
    winner = []
    provider.contender = lambda: winner.append(pipeline.acquire(request("pipeline", "pipeline-job")))
    with pytest.raises(en.EnrollmentError, match="non-fast-forward"):
        api.acquire(request())
    assert provider.state()["records"][admission.RECORD]["claim"] == winner[0]
    assert provider.state()["active"] is None
    assert set(provider.state()) == {"schema", "repository", "enrollment", "active", "records"}
    assert sum(method == "PATCH" for method, _, _ in provider.calls) == 2
    with pytest.raises(admission.AdmissionError, match="reconciliation-required"):
        api.acquire(request())


def test_uncertain_write_retains_claim_and_does_not_retry(shared):
    provider, store = shared
    coordinator = admission.Admission(store(), Authority())
    provider.uncertain = True
    with pytest.raises(en.EnrollmentError, match="write-uncertain"):
        coordinator.acquire(request())
    assert provider.state()["records"][admission.RECORD]["claim"]["operation_id"] == "api-job"
    calls = len(provider.calls)
    with pytest.raises(admission.AdmissionError, match="reconciliation-required"):
        coordinator.acquire(request())
    assert len(provider.calls) == calls
    with pytest.raises(admission.AdmissionError, match="busy"):
        admission.Admission(store(), Authority()).acquire(request("pipeline", "new-run"))


@pytest.mark.parametrize("change", [
    {"terminal": False}, {"inventory_complete": False}, {"active_operations": ["deployment"]},
    {"run_id": "another-run"}, {"repository": "https://github.com/other/repo"},
])
def test_reconciliation_requires_remote_terminal_identity_and_complete_inventory(shared, change):
    provider, store = shared
    authority = Authority()
    coordinator = admission.Admission(store(), authority)
    claim = coordinator.acquire(request())
    valid = authority.observe(claim, None)
    authority.observe = lambda *args: valid | change
    with pytest.raises(admission.AdmissionError, match="reconciliation"):
        coordinator.complete(claim, {"local_status": "succeeded"})
    assert provider.state()["records"][admission.RECORD]["claim"] == claim


def test_authenticated_release_records_durable_evidence(shared):
    provider, store = shared
    coordinator = admission.Admission(store(), Authority())
    claim = coordinator.acquire(request())
    coordinator.complete(claim, {"lookup": "provider-run"})
    record = provider.state()["records"][admission.RECORD]
    assert record["claim"] is None
    assert record["history"][claim["id"]]["observation"]["evidence_id"] == "remote-observation-123"
    assert admission.Admission(store(), Authority()).acquire(request("pipeline", "pipeline-job"))


def test_inner_claim_does_not_deadlock_outer_but_must_finish_before_release(shared):
    provider, store = shared
    coordinator = admission.Admission(store(), Authority())
    claim = coordinator.acquire(request())
    state = provider.state()
    state["active"] = {"inner": "runtime"}
    provider.set_state(state)
    coordinator.assert_owned(claim)
    with pytest.raises(admission.AdmissionError, match="inner-claim"):
        coordinator.complete(claim, {})


def test_canonical_configuration_cas_never_overwrites_newer_revision(shared):
    provider, store = shared
    coordinator = admission.Admission(store(), Authority())
    claim = coordinator.acquire(request())
    old = coordinator.canonical_configuration(FACTORY)
    new = coordinator.commit_configuration(claim, old["revision"], {"value": 2})
    assert new["revision"] != old["revision"]
    with pytest.raises(admission.AdmissionError, match="configuration-changed"):
        coordinator.commit_configuration(claim, old["revision"], {"value": 3})
    assert coordinator.canonical_configuration(FACTORY)["document"] == {"value": 2}
    coordinator.complete(claim, {})
    with pytest.raises(admission.AdmissionError, match="configuration-changed"):
        admission.Admission(store(), Authority()).acquire(request("pipeline", "new-run"))


def test_missing_coordinator_policy_fails_closed(shared):
    provider, store = shared
    state = provider.state()
    state["records"].pop(admission.RECORD)
    provider.set_state(state)
    with pytest.raises(admission.AdmissionError, match="not-enrolled"):
        admission.Admission(store(), Authority()).acquire(request())


@pytest.mark.parametrize("policy_change", [
    {"all_writers": "legacy"}, {"operations": ["execute"]},
    {"shared_scopes": [SCOPE]}, {"routes": ["pipeline"]},
])
def test_incomplete_writer_coverage_and_cross_repository_scopes_are_unsupported(shared, policy_change):
    provider, store = shared
    state = provider.state()
    state["records"][admission.RECORD]["policy"]["factories"][FACTORY].update(policy_change)
    provider.set_state(state)
    with pytest.raises(admission.AdmissionError, match="unsupported"):
        admission.Admission(store(), Authority()).acquire(request())


def test_caller_supplied_identity_is_not_authority(shared):
    provider, store = shared
    with pytest.raises(admission.AdmissionError, match="authority-required"):
        admission.Admission(store(), {"authenticated": True})
    authority = Authority()
    authority.authenticate = lambda request, policy: {"subject": "caller"}
    with pytest.raises(admission.AdmissionError, match="identity"):
        admission.Admission(store(), authority).acquire(request())
    assert provider.state()["records"][admission.RECORD]["claim"] is None


def test_existing_inner_claim_blocks_new_outer_claim(shared):
    provider, store = shared
    state = provider.state()
    state["active"] = {"legacy": "active"}
    provider.set_state(state)
    with pytest.raises(admission.AdmissionError, match="inner-claim"):
        admission.Admission(store(), Authority()).acquire(request())


def test_owned_claim_requires_full_identity_and_is_not_reentrant(shared):
    provider, store = shared
    coordinator = admission.Admission(store(), Authority())
    claim = coordinator.acquire(request())
    changed = copy.deepcopy(claim)
    changed["identity"]["run_id"] = "stolen"
    with pytest.raises(admission.AdmissionError, match="ownership"):
        coordinator.assert_owned(changed)
    with pytest.raises(admission.AdmissionError, match="busy"):
        coordinator.acquire(request())


def test_terminal_operation_cannot_be_replayed_as_new_claim(shared):
    _, store = shared
    coordinator = admission.Admission(store(), Authority())
    claim = coordinator.acquire(request())
    coordinator.complete(claim, {})
    with pytest.raises(admission.AdmissionError, match="already-completed"):
        admission.Admission(store(), Authority()).acquire(request())


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_each_provider_retains_outer_claim_after_lost_remote_cas_response(kind):
    repository = REPOSITORY if kind == "gha" else "https://dev.azure.com/org/project/_git/repo"
    provider = Provider(repository)
    store = ps.ProviderState(SimpleNamespace(state_request=provider.call),
                             {"kind": kind, "repository": repository}, en.EnrollmentError)
    state = store.empty()
    state["records"][admission.RECORD] = admission.new_record({
        "repository": repository, "factories": {FACTORY: {
            "scopes": [SCOPE], "routes": ["api", "pipeline"], "operations": sorted(admission.OPERATIONS),
            "all_writers": admission.PROTOCOL, "shared_scopes": []}}}, {FACTORY: {"value": 1}})
    provider.set_state(state)
    authority = Authority()
    authority.authenticate = lambda req, policy: {
        "subject": "verified-provider-principal", "run_id": req["operation_id"],
        "repository": repository, "route": req["route"], "operation_id": req["operation_id"],
        "review_digest": req["review_digest"], "authorization_id": "provider-approved-review-123"}
    coordinator = admission.Admission(store, authority)
    provider.uncertain = True
    with pytest.raises(en.EnrollmentError, match="write-uncertain"):
        coordinator.acquire(request("pipeline", "provider-run"))
    assert provider.state()["records"][admission.RECORD]["claim"]["operation_id"] == "provider-run"
    count = len(provider.calls)
    with pytest.raises(admission.AdmissionError, match="reconciliation"):
        coordinator.acquire(request("pipeline", "provider-run"))
    assert len(provider.calls) == count


@pytest.mark.parametrize("change", [{"review_digest": "b" * 64}, {"authorization_id": ""}])
def test_authenticated_review_must_bind_exact_prepared_operation(shared, change):
    provider, store = shared
    authority = Authority()
    authenticate = authority.authenticate
    authority.authenticate = lambda req, policy: authenticate(req, policy) | change
    with pytest.raises(admission.AdmissionError, match="identity"):
        admission.Admission(store(), authority).acquire(request())
    assert provider.state()["records"][admission.RECORD]["claim"] is None


def test_whole_catalog_revision_advances_for_every_factory_in_same_repository(shared):
    provider, store = shared
    other = "33333333-3333-4333-8333-333333333333"
    state = provider.state()
    outer = state["records"][admission.RECORD]
    outer["policy"]["factories"][other] = copy.deepcopy(outer["policy"]["factories"][FACTORY])
    outer["canonical"][other] = copy.deepcopy(outer["canonical"][FACTORY])
    provider.set_state(state)
    coordinator = admission.Admission(store(), Authority())
    claim = coordinator.acquire(request())
    coordinator.commit_configuration(claim, request()["configuration_revision"], {"value": 2})
    coordinator.complete(claim, {})
    assert coordinator.canonical_configuration(other)["document"] == {"value": 2}
    stale = request("pipeline", "other-factory-job") | {"factory_id": other}
    with pytest.raises(admission.AdmissionError, match="configuration-changed"):
        admission.Admission(store(), Authority()).acquire(stale)


def test_enrollment_cannot_seed_conflicting_whole_catalog_snapshots():
    with pytest.raises(admission.AdmissionError, match="canonical-catalog"):
        admission.new_record({}, {"factory-one": {"value": 1}, "factory-two": {"value": 2}})
