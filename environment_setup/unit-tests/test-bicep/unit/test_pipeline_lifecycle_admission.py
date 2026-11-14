import copy
from unittest.mock import Mock

import pytest

from .test_pipeline_lifecycle_adapters import ProviderStore, FACTORY, COMMON, GROUP, snapshot


def admitted():
    import lifecycle_admission as shared
    from pipeline_lifecycle_admission import NativeAdmission
    provider = ProviderStore()
    provider.route = {"kind": "gha", "repository": provider.value["repository"]}
    data = snapshot()
    policy = {"repository": provider.value["repository"], "factories": {FACTORY: {
        "all_writers": shared.PROTOCOL, "shared_scopes": [], "operations": sorted(shared.OPERATIONS),
        "routes": ["api", "pipeline"], "scopes": [COMMON, GROUP]}}}
    provider.value["records"][shared.RECORD] = shared.new_record(policy, {FACTORY: data["document"]})
    review, executor = Mock(), Mock()
    review.verify.return_value = {"provider": "gha", "run_id": "42", "attempt": 1}
    review.get.return_value = {"id": 42, "run_attempt": 1, "head_sha": "b" * 40,
                              "status": "in_progress", "conclusion": None}
    executor.observe.return_value = {"status": "succeeded", "verified": True}
    record = {"operation_id": "11111111-1111-1111-1111-111111111111", "plan_hash": "d" * 64,
              "snapshot": data, "plan": {
                  "origin": {"provider": "gha", "repository": "org/repo", "run_id": "42",
                             "attempt": 1, "commit": "b" * 40},
                  "stages": [{"manifests": [{"locks": {"scopes": [GROUP], "common_dependencies": [COMMON]}}]}]}}
    return NativeAdmission(provider, review, executor), provider, review, executor, record


def test_native_outer_admission_requires_existing_all_writer_policy():
    import lifecycle_admission as shared
    adapter, provider, _, _, record = admitted()
    del provider.value["records"][shared.RECORD]
    with pytest.raises(shared.AdmissionError, match="not-enrolled"):
        adapter.acquire(record)


def test_cross_route_claim_is_retained_until_provider_terminal_and_inventory_verified():
    import lifecycle_admission as shared
    adapter, provider, review, executor, record = admitted()
    claim = adapter.acquire(record)
    record["admission_claim"] = claim
    adapter.assert_owned(record)
    assert adapter.release(record)["status"] == "provider-completion-pending"
    executor.observe.assert_not_called()
    assert provider.value["records"][shared.RECORD]["claim"] == claim
    review.get.return_value.update(status="completed", conclusion="success")
    assert adapter.release(record)["status"] == "released"
    executor.observe.assert_called_once()
    assert provider.value["records"][shared.RECORD]["claim"] is None


def test_changed_configuration_cannot_acquire_new_claim():
    adapter, _, _, _, record = admitted()
    record["snapshot"]["document"]["revision"] = 2
    with pytest.raises(ValueError, match="canonical-configuration-changed"):
        record["admission_claim"] = adapter.acquire(record)


def test_provider_success_cannot_clear_an_unverified_native_outcome():
    import lifecycle_admission as shared
    adapter, provider, review, executor, record = admitted()
    record["admission_claim"] = adapter.acquire(record)
    review.get.return_value.update(status="completed", conclusion="success")
    executor.observe.return_value = {"status": "reconciliation-required", "verified": False}
    with pytest.raises(ValueError, match="native-outcome-unverified"):
        adapter.release(record)
    assert provider.value["records"][shared.RECORD]["claim"] is not None


def test_replacement_claim_with_same_operation_cannot_be_adopted():
    import lifecycle_admission as shared
    adapter, provider, _, _, record = admitted()
    record["admission_claim"] = adapter.acquire(record)
    provider.value["records"][shared.RECORD]["claim"]["id"] = "99999999-9999-9999-9999-999999999999"
    with pytest.raises(ValueError, match="claim"):
        adapter.assert_owned(record)
    with pytest.raises(ValueError, match="claim"):
        adapter.release(record)


def test_native_finalizer_releases_after_terminal_mutator_while_workflow_is_running():
    import lifecycle_admission as shared
    adapter, provider, review, executor, record = admitted()
    record["admission_claim"] = adapter.acquire(record)
    review.verify_finalizer.return_value = {
        "operation_id": record["operation_id"], "plan_hash": record["plan_hash"],
        "execution_job_id": "verified-terminal-job", "proof_kind": "github-rs256-native-finalizer"}
    assert adapter.finalize(record) == {"status": "released"}
    assert provider.value["records"][shared.RECORD]["claim"] is None
    assert review.get.return_value["status"] == "in_progress"
    executor.observe.assert_called_once()


def test_invalid_finalizer_keeps_native_admission_claim():
    import lifecycle_admission as shared
    adapter, provider, review, executor, record = admitted()
    record["admission_claim"] = adapter.acquire(record)
    review.verify_finalizer.side_effect = ValueError("unverified-finalizer")
    with pytest.raises(ValueError, match="unverified"):
        adapter.finalize(record)
    assert provider.value["records"][shared.RECORD]["claim"] == record["admission_claim"]
    executor.observe.assert_not_called()
