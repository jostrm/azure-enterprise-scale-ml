"""Real authorization/CAS service; provider and authenticated read transports are offline."""

import copy
from datetime import datetime, timezone
import importlib
from unittest.mock import Mock

import pytest

from .test_pipeline_lifecycle_adapters import FACTORY, SCALE, GROUP, COMMON, OBJECT, snapshot


OPERATION = "11111111-1111-1111-1111-111111111111"
OTHER = GROUP.lower() + "-unselected"
HASH = "a" * 64


class Provider:
    def __init__(self, value, provider):
        self.value = copy.deepcopy(value)
        self.route = {"kind": provider, "repository": value["repository"]}
        self.head = 1
        self.writes = []
        self.fail = None
        self.before_write = None
        self.write_failed = False

    def read(self):
        return str(self.head), copy.deepcopy(self.value)

    def replace(self, expected, value):
        assert not self.write_failed
        self.writes.append(copy.deepcopy(value))
        if self.before_write:
            self.before_write(self)
        if expected != str(self.head):
            self.write_failed = True
            raise RuntimeError("provider-cas-conflict")
        if self.fail != "before":
            self.value = copy.deepcopy(value)
            self.head += 1
        if self.fail:
            self.write_failed = True
            raise OSError("provider response lost")
        return str(self.head)


@pytest.fixture
def authorization(monkeypatch):
    module = importlib.import_module("pipeline_lifecycle_authorization")
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("real subprocess forbidden")))
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=AssertionError("Factory API forbidden")))
    monkeypatch.setattr("urllib.request.build_opener", Mock(side_effect=AssertionError("real HTTP forbidden")))
    monkeypatch.setattr(module.fl, "build_opener", Mock(side_effect=AssertionError("Factory API forbidden")))
    return module


def fixture(module, provider="gha"):
    import factory_enrollment as enrollment
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest

    data = snapshot(5)
    repository = "https://github.com/org/repo" if provider == "gha" else "https://dev.azure.com/org/project/_git/repo"
    data["request"]["provider"] = provider
    binding = data["binding"]
    binding.update(orchestrator=provider, repository=repository)
    if provider == "ado":
        binding["runner"] = {"os": "linux", "kind": "hosted", "image": "ubuntu-latest"}
    binding["locks"]["repository"] = repository
    binding["targets"][0].update(resource_group_ids=[GROUP], common_dependency_ids=[COMMON])
    data["document"]["bindings"] = {FACTORY: {provider: binding}}
    data["document"]["generation"] = "22222222-2222-2222-2222-222222222222"
    scale = data["scales"][0]
    target = {"factory_id": FACTORY, "scaleset_id": SCALE, "prefix": data["factory"]["prefix"],
              "region": data["factory"]["region"],
              **{key: scale[key] for key in ("environment", "tenant_id", "subscription_id", "suffix")}}
    enrolled = {
        "schema": 1, "protocol": "aifactory-single-writer-v1", "enforcement": "repository-exclusive-writer",
        "revision": 1,
        "writers": {"writer": {"kind": provider, "repository": repository, "shared_remote": False,
                               "auth_namespace": binding["auth_namespace"], "runner": binding["runner"],
                               "deployment_object_id": OBJECT}},
        "scopes": {
            GROUP.lower(): {"scope_kind": "aifactory-owned", "allow_delete": False, "writers": ["writer"],
                            "target": target, "common_dependencies": [COMMON.lower()]},
            COMMON.lower(): {"scope_kind": "shared", "allow_delete": False, "writers": ["writer"],
                             "target": target, "common_dependencies": []},
            OTHER: {"scope_kind": "aifactory-owned", "allow_delete": False, "writers": ["writer"],
                    "target": target, "common_dependencies": []},
        },
    }
    binding["locks"]["coordination_hash"] = enrollment.digest(enrolled)
    manifest = {
        "operation": "delete", "target": target, "source": data["source"],
        "route": {"kind": provider, **{key: binding[key] for key in (
            "repository", "writer_id", "auth_namespace", "shared_remote", "runner", "ref")}},
        "identity": {"object_id": OBJECT, "deployment_object_id": OBJECT},
        "locks": {**binding["locks"], "scopes": [GROUP], "common_dependencies": [COMMON]},
    }
    policy = {"repository": repository, "factories": {FACTORY: {
        "all_writers": outer.PROTOCOL, "shared_scopes": [], "operations": sorted(outer.OPERATIONS),
        "routes": ["api", "pipeline"], "scopes": [GROUP, COMMON, OTHER]}}}
    state = {"schema": 1, "repository": repository, "enrollment": enrolled, "active": None,
             "records": {outer.RECORD: outer.new_record(policy, {FACTORY: data["document"]}),
                         "runs/unrelated.json": {"status": "succeeded"}}}
    store = Provider(state, provider)
    review, admission = Mock(), Mock(spec=["assert_owned"])
    origin = {"provider": provider, "run_id": "42", "attempt": 1, "commit": "b" * 40,
              "repository": "org/repo" if provider == "gha" else repository}
    review.verify.return_value = {**origin, "proof_kind": "native-protected-review"}
    observation = {
        "repository": repository, "factory_id": FACTORY,
        "scopes": [GROUP.lower()], "common_dependencies": [COMMON.lower()],
        "owner_hash": HASH, "identity_hash": HASH, "permission_hash": HASH,
        "inventory_hash": HASH, "dependency_hash": HASH, "inventory_complete": True,
        "active_operations": [], "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    evidence = Mock(side_effect=lambda *_: copy.deepcopy(observation))
    service = module.DeletionAuthorization(store, review=review, admission=admission, evidence=evidence)
    stage = service.prepare(data, OPERATION, [manifest])
    record = {"schema": 1, "operation_id": OPERATION, "snapshot": data, "snapshot_hash": digest(data),
              "prepared_at": datetime.now(timezone.utc).isoformat(), "status": "running",
              "plan": {"origin": origin, "stages": [stage]},
              "stages": [{"id": stage["id"], "status": "running"}]}
    record["plan_hash"] = digest(bound_plan(record))
    claim = {"protocol": outer.PROTOCOL, "id": "test-outer-claim", "operation_id": OPERATION,
             "factory_id": FACTORY, "route": "pipeline", "review_digest": record["plan_hash"],
             "scopes": sorted([GROUP.lower(), COMMON.lower(), OTHER]),
             "configuration_revision": digest(data["document"])}
    record["admission_claim"] = claim
    store.value["records"][outer.RECORD]["claim"] = copy.deepcopy(claim)
    return service, store, data, stage, record, evidence, observation, review, admission


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_authorizes_exact_owned_scopes_and_repins_canonical_in_one_cas(authorization, provider):
    import factory_enrollment
    import lifecycle_admission as outer
    service, store, data, stage, record, evidence, _, review, admission = fixture(authorization, provider)
    before = copy.deepcopy(store.value)
    assert store.writes == []
    assert "operation" not in stage["manifests"][0]
    assert stage["deletion_authorization"]["scopes"] == [GROUP.lower()]
    result = service.execute(stage, record)
    assert result["status"] == "succeeded" and result["verified"] is True
    assert result["requires_reprepare"] is True
    assert len(store.writes) == 1
    after = store.value
    assert after["enrollment"]["scopes"][GROUP.lower()]["allow_delete"] is True
    assert after["enrollment"]["revision"] == 2
    for scope in (COMMON.lower(), OTHER):
        assert after["enrollment"]["scopes"][scope] == before["enrollment"]["scopes"][scope]
    canonical = after["records"][outer.RECORD]["canonical"][FACTORY]
    assert result["canonical"] == canonical
    result["canonical"]["document"]["revision"] = -1
    assert store.value["records"][outer.RECORD]["canonical"][FACTORY] == canonical
    assert canonical["document"]["revision"] == data["document"]["revision"]
    pins = canonical["document"]["bindings"][FACTORY][provider]["locks"]
    assert pins["coordination_hash"] == factory_enrollment.digest(after["enrollment"])
    assert pins["revision"] == 2
    assert canonical["document"]["generation"] != data["document"]["generation"]
    assert after["records"][outer.RECORD]["claim"] == record["admission_claim"]
    assert after["active"] is None
    assert after["records"]["runs/unrelated.json"] == before["records"]["runs/unrelated.json"]
    audit = after["records"][result["audit_record"]]
    assert audit["operation_id"] == OPERATION and audit["plan_hash"] == record["plan_hash"]
    assert audit["approval"] == review.verify.return_value
    assert evidence.call_count == 2
    admission.assert_owned.assert_called()
    assert service.observe(stage, record)["verified"] is True
    assert len(store.writes) == 1


def test_review_failure_cannot_be_replaced_by_human_flag_or_hash(authorization):
    service, store, _, stage, record, _, _, review, _ = fixture(authorization)
    record["approved"] = True
    record["approval"] = {"approved": True, "plan_hash": record["plan_hash"]}
    review.verify.side_effect = ValueError("protected-review-required")
    with pytest.raises(ValueError, match="protected-review-required"):
        service.execute(stage, record)
    assert store.writes == []


@pytest.mark.parametrize("field,value", [
    ("inventory_complete", False), ("active_operations", ["foreign-run"]),
    ("scopes", [OTHER]), ("common_dependencies", []), ("factory_id", "another-factory"),
])
def test_fresh_authenticated_evidence_is_required_again_before_write(authorization, field, value):
    service, store, _, stage, record, _, observation, _, _ = fixture(authorization)
    observation[field] = value
    with pytest.raises(ValueError, match="authorization-"):
        service.execute(stage, record)
    assert store.writes == []


@pytest.mark.parametrize("change", ["active", "claim", "enrollment", "canonical", "policy"])
def test_stale_authority_or_active_native_claim_blocks_all_writes(authorization, change):
    import lifecycle_admission as outer
    service, store, _, stage, record, *_ = fixture(authorization)
    if change == "active":
        store.value["active"] = {"kind": "run"}
    elif change == "claim":
        store.value["records"][outer.RECORD]["claim"]["id"] = "other-claim"
    elif change == "enrollment":
        store.value["enrollment"]["scopes"][OTHER]["allow_delete"] = True
    elif change == "canonical":
        store.value["records"][outer.RECORD]["canonical"][FACTORY]["document"]["revision"] = 2
    else:
        store.value["records"][outer.RECORD]["policy"]["factories"][FACTORY]["scopes"].remove(OTHER)
    with pytest.raises((ValueError, RuntimeError), match="authorization-|lifecycle-admission-|lock-"):
        service.execute(stage, record)
    assert store.writes == []


def test_authorization_and_deletion_cannot_share_one_review(authorization):
    from pipeline_lifecycle import bound_plan, digest
    service, store, _, stage, record, *_ = fixture(authorization)
    record["plan"]["stages"].append({"id": "delete", "kind": "lifecycle", "manifests": []})
    record["plan_hash"] = digest(bound_plan(record))
    with pytest.raises(ValueError, match="authorization-only"):
        service.execute(stage, record)
    assert store.writes == []


@pytest.mark.parametrize("outcome", ["before", "after"])
def test_lost_cas_response_observes_audit_and_never_blindly_replays(authorization, outcome):
    service, store, _, stage, record, evidence, _, review, admission = fixture(authorization)
    store.fail = outcome
    result = service.execute(stage, record)
    assert result["status"] == ("succeeded" if outcome == "after" else "reconciliation-required")
    fresh = authorization.DeletionAuthorization(store, review=review, admission=admission, evidence=evidence)
    recovered = fresh.observe(stage, record)
    assert recovered["verified"] is (outcome == "after")
    if outcome == "after":
        assert fresh.execute(stage, record)["verified"] is True
    else:
        with pytest.raises(ValueError, match="reconciliation-required"):
            service.execute(stage, record)
        record["status"] = "reconciliation-required"
        with pytest.raises(ValueError, match="reconciliation-required"):
            fresh.execute(stage, record)
    assert len(store.writes) == 1


def test_competing_cas_writer_is_not_overwritten(authorization):
    service, store, _, stage, record, *_ = fixture(authorization)
    def compete(remote):
        remote.head += 1
        remote.value["records"]["competing"] = {"preserve": True}
    store.before_write = compete
    result = service.execute(stage, record)
    assert result["verified"] is False
    assert len(store.writes) == 1
    assert store.value["enrollment"]["revision"] == 1
    assert store.value["records"]["competing"] == {"preserve": True}


def test_audit_without_matching_live_canonical_cannot_report_success(authorization):
    import lifecycle_admission as outer
    service, store, _, stage, record, *_ = fixture(authorization)
    assert service.execute(stage, record)["verified"] is True
    store.value["records"][outer.RECORD]["canonical"][FACTORY]["document"]["revision"] = 99
    with pytest.raises(ValueError, match="authorization-"):
        service.observe(stage, record)
    assert len(store.writes) == 1


@pytest.mark.parametrize("defect", ["scope", "dependency", "owner", "identity", "binding-pin", "writer"])
def test_prepare_refuses_unbound_or_nonowned_selection(authorization, defect):
    service, store, data, stage, *_ = fixture(authorization)
    manifest = copy.deepcopy(stage["manifests"][0])
    if defect == "scope":
        manifest["locks"]["scopes"] = [OTHER]
    elif defect == "dependency":
        manifest["locks"]["scopes"].append(COMMON)
    elif defect == "owner":
        manifest["target"]["factory_id"] = "99999999-9999-9999-9999-999999999999"
    elif defect == "identity":
        manifest["identity"]["deployment_object_id"] = "99999999-9999-9999-9999-999999999999"
    elif defect == "binding-pin":
        manifest["locks"]["coordination_hash"] = "b" * 64
    else:
        manifest["route"]["writer_id"] = "another-writer"
    with pytest.raises((ValueError, RuntimeError), match="authorization-|lock-|writer-|identity-|scope-"):
        service.prepare(data, OPERATION, [manifest])
    assert store.writes == []


def test_evidence_json_is_not_an_authority_adapter(authorization):
    with pytest.raises(ValueError, match="authorization-evidence-adapter-required"):
        authorization.DeletionAuthorization(Mock(), review=Mock(), admission=Mock(), evidence={"approved": True})


def test_authority_observations_are_read_again_even_if_caller_reuses_approval(authorization):
    service, store, _, stage, record, evidence, _, review, _ = fixture(authorization)
    record["approval"] = copy.deepcopy(review.verify.return_value)
    evidence.side_effect = ValueError("authenticated-owner-read-failed")
    with pytest.raises(ValueError, match="authenticated-owner-read-failed"):
        service.execute(stage, record)
    review.verify.assert_called_once_with(record)
    assert store.writes == []


def test_native_claim_arriving_during_evidence_read_blocks_write(authorization):
    service, store, _, stage, record, evidence, observation, *_ = fixture(authorization)
    def observe(*_):
        store.value["active"] = {"kind": "run", "run_id": "unexpected"}
        return observation
    evidence.side_effect = observe
    with pytest.raises(ValueError, match="authorization-native-claim-active"):
        service.execute(stage, record)
    assert store.writes == []


def test_all_canonical_aliases_advance_and_target_execution_is_preserved(authorization):
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest
    service, store, data, stage, record, *_ = fixture(authorization)
    binding = data["document"]["bindings"][FACTORY]["gha"]
    binding["targets"][0]["execution"] = {
        key: copy.deepcopy(binding[key])
        for key in ("writer_id", "auth_namespace", "deployment_object_id", "runner")
    }
    canonical = {"revision": digest(data["document"]), "document": copy.deepcopy(data["document"])}
    stored = store.value["records"][outer.RECORD]
    stored["canonical"] = {FACTORY: copy.deepcopy(canonical), "another-factory": copy.deepcopy(canonical)}
    stage = service.prepare(data, OPERATION, stage["manifests"])
    record["plan"]["stages"] = [stage]
    record["snapshot_hash"] = digest(data)
    record["plan_hash"] = digest(bound_plan(record))
    record["admission_claim"]["review_digest"] = record["plan_hash"]
    record["admission_claim"]["configuration_revision"] = canonical["revision"]
    stored["claim"] = copy.deepcopy(record["admission_claim"])
    result = service.execute(stage, record)
    assert result["verified"] is True and len(store.writes) == 1
    values = store.value["records"][outer.RECORD]["canonical"]
    assert values[FACTORY] == values["another-factory"]
    changed = values[FACTORY]["document"]["bindings"][FACTORY]["gha"]
    assert changed["targets"][0]["execution"] == binding["targets"][0]["execution"]
    assert changed["locks"]["revision"] == 2


def test_live_dependency_of_an_unselected_target_is_never_authorized(authorization):
    import factory_enrollment
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    service, store, data, stage, *_ = fixture(authorization)
    store.value["enrollment"]["scopes"][OTHER]["common_dependencies"] = [GROUP.lower()]
    pin = factory_enrollment.digest(store.value["enrollment"])
    data["document"]["bindings"][FACTORY]["gha"]["locks"]["coordination_hash"] = pin
    stage["manifests"][0]["locks"]["coordination_hash"] = pin
    store.value["records"][outer.RECORD]["canonical"][FACTORY] = {
        "revision": digest(data["document"]), "document": copy.deepcopy(data["document"])}
    with pytest.raises(ValueError, match="authorization-common-scope-retained"):
        service.prepare(data, OPERATION, stage["manifests"])
    assert store.writes == []


def test_input_documents_remain_unchanged_during_preparation(authorization):
    service, store, data, stage, *_ = fixture(authorization)
    manifests = copy.deepcopy(stage["manifests"])
    manifests[0]["operation"] = "delete"
    original = copy.deepcopy((data, manifests, store.value))
    service.prepare(data, OPERATION, manifests)
    assert (data, manifests, store.value) == original


def test_observation_after_verified_outer_finalization_remains_read_only(authorization):
    import lifecycle_admission as outer
    service, store, _, stage, record, *_ = fixture(authorization)
    assert service.execute(stage, record)["verified"] is True
    stored = store.value["records"][outer.RECORD]
    stored["history"]["completed"] = {"claim": copy.deepcopy(stored["claim"])}
    stored["claim"] = None
    assert service.observe(stage, record)["verified"] is True
    assert len(store.writes) == 1


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_real_lifecycle_journal_and_outer_admission_authorization_pass(authorization, provider):
    import lifecycle_admission as outer
    from pipeline_lifecycle import LifecycleService
    from pipeline_lifecycle_adapters import RepositoryJournal
    from pipeline_lifecycle_admission import NativeAdmission
    service, store, data, stage, template, _, _, review, _ = fixture(authorization, provider)
    store.value["records"][outer.RECORD]["claim"] = None
    admission = NativeAdmission(store, review, service)
    service.admission = admission
    review.get.return_value = {"id": 42, "head_sha": "b" * 40, "run_attempt": 1,
                              "sourceVersion": "b" * 40, "status": "in_progress"}
    planner = Mock()
    planner.prepare.side_effect = lambda value, operation: {
        "origin": template["plan"]["origin"],
        "stages": [service.prepare(value, operation, stage["manifests"])],
    }
    lifecycle = LifecycleService(store=RepositoryJournal(store), planner=planner,
                                 executor=service, review=review, admission=admission)
    prepared = lifecycle.prepare(data)
    result = lifecycle.execute(prepared["operation_id"], data, prepared["plan_hash"])
    assert result["status"] == "succeeded", result.get("error_code")
    assert result["stages"][0]["receipt"]["requires_reprepare"] is True
    assert store.value["records"][outer.RECORD]["claim"] == result["admission_claim"]
    assert store.value["active"] is None
    assert store.value["enrollment"]["scopes"][GROUP.lower()]["allow_delete"] is True
    assert len([value for value in store.writes if value["enrollment"]["revision"] == 2]) >= 1


@pytest.mark.parametrize("approval", [True, {"approved": True},
                                    {"provider": "gha", "run_id": "unreviewed-run", "attempt": 1}])
def test_unbound_review_adapter_result_cannot_authorize(authorization, approval):
    service, store, _, stage, record, _, _, review, _ = fixture(authorization)
    review.verify.return_value = approval
    with pytest.raises(ValueError, match="authorization-protected-review-required"):
        service.execute(stage, record)
    assert store.writes == []


def test_outer_claim_must_pin_the_reviewed_canonical_baseline(authorization):
    import lifecycle_admission as outer
    service, store, _, stage, record, *_ = fixture(authorization)
    record["admission_claim"]["configuration_revision"] = "b" * 64
    store.value["records"][outer.RECORD]["claim"] = copy.deepcopy(record["admission_claim"])
    with pytest.raises(ValueError, match="authorization-owned-outer-claim-required"):
        service.execute(stage, record)
    assert store.writes == []


@pytest.mark.parametrize("changed", ["none", "generation", "body"])
def test_parent_configuration_contract_and_stage_share_semantic_baseline(authorization, changed):
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest
    service, store, data, stage, record, *_ = fixture(authorization)
    baseline = copy.deepcopy(stage["deletion_authorization"]["canonical"]["before"])
    if changed == "generation":
        baseline["document"]["generation"] = "99999999-9999-9999-9999-999999999999"
        baseline["revision"] = digest(baseline["document"])
    elif changed == "body":
        baseline["document"]["ownership_evidence"] = {"unreviewed": {"owner": "other"}}
        baseline["revision"] = digest(baseline["document"])
    record["plan"]["configuration"] = {
        "contract": "pipeline-configuration-v1", "baseline": baseline,
        "proposal": copy.deepcopy(data["document"]), "changes": [],
    }
    record["plan_hash"] = digest(bound_plan(record))
    record["admission_claim"]["review_digest"] = record["plan_hash"]
    store.value["records"][outer.RECORD]["claim"] = copy.deepcopy(record["admission_claim"])
    if changed == "body":
        with pytest.raises(ValueError, match="authorization-configuration-baseline-mismatch"):
            service.execute(stage, record)
        assert store.writes == []
    else:
        result = service.execute(stage, record)
        assert result["canonical"] == stage["deletion_authorization"]["canonical"]["after"]
        assert result["canonical"] == service.observe(stage, record)["canonical"]
        if changed == "generation":
            assert "authorization-canonical-generation-drift" in result["warnings"]


@pytest.mark.parametrize("field,value", [
    ("owner_hash", "b" * 64), ("identity_hash", "b" * 64), ("permission_hash", "b" * 64),
    ("inventory_hash", "b" * 64), ("dependency_hash", "b" * 64),
    ("observed_at", "2000-01-01T00:00:00+00:00"), ("observed_at", "2100-01-01T00:00:00+00:00"),
    ("inventory_hash", None),
])
def test_fresh_native_checks_allow_fingerprint_and_clock_drift_with_audit_warnings(authorization, field, value):
    service, store, _, stage, record, evidence, observation, *_ = fixture(authorization)
    observation[field] = value
    result = service.execute(stage, record)
    assert result["status"] == "succeeded" and result["verified"] is True
    assert evidence.call_count == 2
    expected = ("authorization-evidence-time-drift" if field == "observed_at"
                else "authorization-evidence-fingerprint-" + ("unavailable:" if value is None else "drift:") + field)
    assert expected in result["warnings"]
    assert expected in store.value["records"][result["audit_record"]]["warnings"]
    assert len(store.writes) == 1


@pytest.mark.parametrize("failure", ["owner", "identity", "scope", "permissions", "inventory", "dependencies"])
def test_hash_and_clock_warnings_never_override_failed_actual_native_checks(authorization, failure):
    service, store, _, stage, record, evidence, observation, *_ = fixture(authorization)
    observation.update(inventory_hash="b" * 64, observed_at="2000-01-01T00:00:00+00:00")
    evidence.side_effect = ValueError("actual-native-" + failure + "-unsafe")
    with pytest.raises(ValueError, match="actual-native-" + failure + "-unsafe"):
        service.execute(stage, record)
    assert store.writes == []


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_generation_only_drift_uses_current_owned_claim_and_cas_baseline(authorization, provider):
    import lifecycle_admission as outer
    from pipeline_lifecycle import bound_plan, digest
    service, store, data, stage, record, *_ = fixture(authorization, provider)
    original = copy.deepcopy(stage["deletion_authorization"]["canonical"]["before"])
    record["plan"]["configuration"] = {
        "contract": "pipeline-configuration-v1", "baseline": original,
        "proposal": copy.deepcopy(data["document"]), "changes": [],
    }
    record["plan_hash"] = digest(bound_plan(record))
    current = copy.deepcopy(original)
    current["document"]["generation"] = "99999999-9999-9999-9999-999999999999"
    current["revision"] = digest(current["document"])
    stored = store.value["records"][outer.RECORD]
    stored["canonical"][FACTORY] = current
    record["admission_claim"].update(configuration_revision=current["revision"],
                                     review_digest=record["plan_hash"])
    stored["claim"] = copy.deepcopy(record["admission_claim"])
    result = service.execute(stage, record)
    assert result["verified"] is True
    assert result["canonical"] == stage["deletion_authorization"]["canonical"]["after"]
    assert "authorization-canonical-generation-drift" in result["warnings"]
    assert store.value["records"][outer.RECORD]["claim"] == record["admission_claim"]
    assert len(store.writes) == 1


def test_generation_only_drift_after_commit_is_observed_without_replaying(authorization):
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    service, store, _, stage, record, *_ = fixture(authorization)
    assert service.execute(stage, record)["verified"] is True
    current = store.value["records"][outer.RECORD]["canonical"][FACTORY]
    current["document"]["generation"] = "99999999-9999-9999-9999-999999999999"
    current["revision"] = digest(current["document"])
    result = service.observe(stage, record)
    assert result["canonical"] == current
    assert "authorization-canonical-generation-drift" in result["warnings"]
    assert len(store.writes) == 1


def test_rehashed_real_canonical_body_change_remains_a_hard_gate(authorization):
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    service, store, _, stage, record, *_ = fixture(authorization)
    stored = store.value["records"][outer.RECORD]
    current = stored["canonical"][FACTORY]
    current["document"]["ownership_evidence"] = {"unreviewed": {"owner": "another-owner"}}
    current["revision"] = digest(current["document"])
    record["admission_claim"]["configuration_revision"] = current["revision"]
    stored["claim"] = copy.deepcopy(record["admission_claim"])
    with pytest.raises(ValueError, match="authorization-canonical-proposal-changed"):
        service.execute(stage, record)
    assert store.writes == []


def test_prepare_reports_old_evidence_time_and_generation_without_blocking_native_checks(authorization):
    service, store, data, stage, _, evidence, observation, *_ = fixture(authorization)
    original = copy.deepcopy(data["document"])
    original["generation"] = "99999999-9999-9999-9999-999999999999"
    observation["observed_at"] = "2000-01-01T00:00:00+00:00"
    prepared = service.prepare(data, OPERATION, stage["manifests"], canonical_document=original)
    assert prepared["deletion_authorization"]["canonical"]["before"]["document"] == data["document"]
    assert "authorization-evidence-time-drift" in prepared["deletion_authorization"]["warnings"]
    assert "authorization-canonical-generation-drift" in prepared["deletion_authorization"]["warnings"]
    assert evidence.call_count == 2
    assert store.writes == []


def test_real_body_change_after_commit_cannot_be_hidden_by_rehashed_revision(authorization):
    import lifecycle_admission as outer
    from pipeline_lifecycle import digest
    service, store, _, stage, record, *_ = fixture(authorization)
    assert service.execute(stage, record)["verified"] is True
    current = store.value["records"][outer.RECORD]["canonical"][FACTORY]
    current["document"]["ownership_evidence"] = {"unreviewed": {"owner": "another-owner"}}
    current["revision"] = digest(current["document"])
    with pytest.raises(ValueError, match="authorization-live-result-changed"):
        service.observe(stage, record)
    assert len(store.writes) == 1
