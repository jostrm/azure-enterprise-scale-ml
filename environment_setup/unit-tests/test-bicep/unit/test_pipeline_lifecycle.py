"""Offline contract tests for the API-independent pipeline coordinator."""

import copy
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))


@pytest.fixture
def runtime():
    return importlib.import_module("pipeline_lifecycle")


class Store:
    def __init__(self):
        self.revision = 0
        self.records = {}
        self.fail = False

    def read(self, identifier):
        return self.revision, copy.deepcopy(self.records.get(identifier))

    def write(self, identifier, expected, record):
        if self.fail:
            raise RuntimeError("CAS response lost")
        assert expected == self.revision
        self.records[identifier] = copy.deepcopy(record)
        self.revision += 1
        return self.revision


def resolved(scenario=3):
    return {
        "request": {"schema": 1, "scenario": scenario, "provider": "gha"},
        "document": {"schema_version": 2, "revision": 1},
        "factory": {"id": "factory-uuid"},
        "scales": [{"id": "scale-uuid"}], "projects": [{"id": "project-uuid"}],
        "source": {"ref": "refs/heads/main", "commit": "a" * 40},
        "binding": {"repository": "https://github.com/org/repo"},
        "variables": {}, "configuration": {}, "azurefactory_root": "azurefactory",
    }


@pytest.fixture
def ports():
    return {
        "store": Store(),
        "planner": Mock(),
        "executor": Mock(),
        "review": Mock(),
        "admission": Mock(spec=["acquire", "assert_owned", "release", "finalize"]),
    }


def service(runtime, ports):
    ports["planner"].prepare.return_value = {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": []}]}
    ports["executor"].execute.return_value = {"status": "succeeded", "verified": True}
    ports["executor"].observe.return_value = {"status": "succeeded", "verified": True}
    ports["review"].verify.return_value = {"provider": "gha", "run_id": "42", "attempt": 1}
    ports["admission"].acquire.return_value = {"id": "test-authenticated-claim"}
    return runtime.LifecycleService(**ports)


@pytest.mark.parametrize("scenario", range(1, 7))
def test_six_scenarios_share_prepare_review_execute_persist(runtime, ports, scenario):
    engine = service(runtime, ports)
    record = engine.prepare(resolved(scenario))
    assert record["status"] == "prepared"
    assert record["snapshot"] == resolved(scenario)
    result = engine.execute(record["operation_id"], resolved(scenario), record["plan_hash"])
    assert result["status"] == "succeeded"
    ports["review"].verify.assert_called_once()
    ports["admission"].acquire.assert_called_once()
    ports["admission"].release.assert_called_once()
    assert ports["store"].records[record["operation_id"]]["stages"][0]["status"] == "succeeded"


def test_configuration_drift_blocks_before_auth_or_execution(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    changed = resolved()
    changed["document"]["revision"] = 2
    with pytest.raises(runtime.PipelineError, match="snapshot-changed"):
        engine.execute(record["operation_id"], changed, record["plan_hash"])
    ports["review"].verify.assert_not_called()
    ports["executor"].execute.assert_not_called()


def test_uncertain_effect_is_not_replayed(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["executor"].execute.side_effect = TimeoutError("write response lost")
    result = engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    assert result["status"] == "reconciliation-required"
    with pytest.raises(runtime.PipelineError, match="reconciliation-required"):
        engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    assert ports["executor"].execute.call_count == 1
    ports["admission"].release.assert_not_called()


def test_durable_checkpoint_must_precede_effect(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["store"].fail = True
    with pytest.raises(RuntimeError, match="CAS response lost"):
        engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["executor"].execute.assert_not_called()


def test_unverified_or_incomplete_result_is_never_success(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["executor"].execute.return_value = {"status": "succeeded"}
    result = engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    assert result["status"] == "reconciliation-required"
    ports["admission"].release.assert_not_called()


def test_observation_recovers_durable_receipt_without_reexecution(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["executor"].execute.side_effect = TimeoutError()
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    result = engine.observe(record["operation_id"])
    assert result["status"] == "succeeded"
    assert ports["executor"].execute.call_count == 1


def test_cancel_is_pending_until_verified_remote_terminal(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["executor"].execute.side_effect = TimeoutError()
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["executor"].cancel.return_value = {"requested": True}
    result = engine.cancel(record["operation_id"])
    assert result["status"] == "cancel-pending"
    ports["admission"].release.assert_not_called()
    ports["executor"].observe.return_value = {"status": "running", "verified": False}
    assert engine.observe(record["operation_id"])["status"] == "cancel-pending"


def test_caller_cannot_supply_approval_boolean(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["review"].verify.side_effect = runtime.PipelineError("protected-job-required")
    with pytest.raises(runtime.PipelineError, match="protected-job-required"):
        engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["executor"].execute.assert_not_called()


def test_plan_tampering_is_rejected(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    ports["store"].records[record["operation_id"]]["plan"]["stages"][0]["kind"] = "evil"
    with pytest.raises(runtime.PipelineError, match="plan-hash-mismatch"):
        engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["executor"].execute.assert_not_called()


def test_provider_artifact_success_is_not_authoritative(runtime):
    with pytest.raises(runtime.PipelineError, match="receipt-context"):
        runtime.verify_receipt({"status": "succeeded", "provider_context": {}}, {"run_id": 42})


def test_receipt_requires_durable_operation_and_released_admission(runtime):
    expected = {"run_id": 42}
    receipt = {"status": "succeeded", "provider_context": expected,
               "operation_id": "11111111-1111-1111-1111-111111111111", "plan_hash": "d" * 64}
    engine = Mock()
    durable = {"plan_hash": "d" * 64, "status": "succeeded", "plan": {"provider_context": expected},
               "admission": {"status": "provider-completion-pending"}}
    engine._load.return_value = (1, durable)
    engine.observe.side_effect = AssertionError("The client must not observe Azure or release claims")
    with pytest.raises(runtime.PipelineError, match="admission-reconciliation"):
        runtime.verify_receipt(receipt, expected, service=engine)
    durable["admission"]["status"] = "released"
    with pytest.raises(runtime.PipelineError, match="finaliz"):
        runtime.verify_receipt(receipt, expected, service=engine)
    durable["finalization"] = {"status": "succeeded", "proof": {
        "operation_id": receipt["operation_id"], "plan_hash": receipt["plan_hash"],
        "proof_kind": "github-rs256-native-finalizer"}}
    assert runtime.verify_receipt(receipt, expected, service=engine)["outcome"] == "completed"
    engine.observe.assert_not_called()


def test_pipeline_finalizer_authenticates_observes_and_releases_without_replay(runtime, ports):
    engine = service(runtime, ports)
    ports["admission"].release.return_value = {"status": "provider-completion-pending"}
    record = engine.prepare(resolved())
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    proof = {"operation_id": record["operation_id"], "plan_hash": record["plan_hash"],
             "proof_kind": "github-rs256-native-finalizer"}
    ports["review"].verify_finalizer.return_value = proof
    ports["admission"].finalize.return_value = {"status": "released"}
    result = engine.finalize(record["operation_id"], resolved(), record["plan_hash"])
    assert result["finalization"]["proof"] == proof
    assert result["finalization"]["status"] == "succeeded"
    assert result["admission"]["status"] == "released"
    assert ports["executor"].execute.call_count == 1
    ports["executor"].observe.assert_called()


def test_finalizer_rejects_unverified_job_before_native_reads(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["review"].verify_finalizer.side_effect = runtime.PipelineError("unverified-finalizer")
    with pytest.raises(runtime.PipelineError, match="unverified-finalizer"):
        engine.finalize(record["operation_id"], resolved(), record["plan_hash"])
    ports["executor"].observe.assert_not_called()


def test_finalizer_retry_after_release_before_proof_reobserves_without_owned_claim(runtime, ports):
    engine = service(runtime, ports)
    ports["admission"].release.return_value = {"status": "provider-completion-pending"}
    record = engine.prepare(resolved())
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    released = []

    def finalize(observed):
        released.append(True)
        if len(released) == 1:
            ports["store"].fail = True
        return {"status": "released"}

    ports["admission"].finalize.side_effect = finalize
    with pytest.raises(RuntimeError, match="CAS response lost"):
        engine.finalize(record["operation_id"], resolved(), record["plan_hash"])
    ports["store"].fail = False
    ports["admission"].assert_owned.side_effect = runtime.PipelineError("claim-already-released")
    ports["executor"].observe.reset_mock()
    result = engine.finalize(record["operation_id"], resolved(), record["plan_hash"])
    assert result["finalization"]["status"] == "succeeded"
    assert ports["review"].verify_finalizer.call_count == 2
    assert ports["executor"].observe.call_count == 1
    assert ports["executor"].execute.call_count == 1


def test_verified_bootstrap_is_continuation_not_parent_success(runtime, ports):
    engine = service(runtime, ports)
    ports["planner"].prepare.return_value = {
        "continuation_required": True, "stages": [{"id": "bootstrap-enrollment", "kind": "bootstrap-enrollment"}]}
    receipt = {"status": "continuation-required", "verified": True, "runtime_ready": False,
               "binding_candidate": {"targets": []},
               "continuation": {"requires_fresh_review": True, "stage": "common-and-project"}}
    ports["executor"].execute.return_value = receipt
    ports["executor"].observe.return_value = receipt
    record = engine.prepare(resolved(1))
    result = engine.execute(record["operation_id"], resolved(1), record["plan_hash"])
    assert result["status"] == "continuation-required"
    assert result["stages"][0]["status"] == "continuation-required"
    assert engine.reconcile(record["operation_id"])["status"] == "continuation-required"
    assert ports["executor"].execute.call_count == 1
    assert "finalization" not in result


def test_authorization_only_success_never_means_deletion_succeeded(runtime, ports):
    engine = service(runtime, ports)
    ports["planner"].prepare.return_value = {"continuation_required": True, "stages": [
        {"id": "authorize-deletion", "kind": "deletion-authorization"}]}
    ports["executor"].execute.return_value = {
        "status": "succeeded", "verified": True, "requires_reprepare": True, "azure_writes": False}
    record = engine.prepare(resolved(5))
    result = engine.execute(record["operation_id"], resolved(5), record["plan_hash"])
    assert result["status"] == "continuation-required"
    assert result["stages"][0]["status"] == "succeeded"
    assert engine.reconcile(record["operation_id"])["status"] == "continuation-required"


def test_canonical_baseline_and_promotion_are_bound_before_release(runtime, ports):
    engine = service(runtime, ports)
    configuration = Mock(spec=["prepare", "persist"])
    baseline = {"document": resolved()["document"], "revision": runtime.digest(resolved()["document"])}
    configuration.prepare.return_value = {"baseline": baseline}
    configuration.persist.return_value = baseline
    engine.configuration = configuration
    record = engine.prepare(resolved())
    assert record["plan"]["configuration"]["baseline"] == baseline

    def release(completed):
        stored = ports["store"].records[completed["operation_id"]]
        assert stored["configuration"] == baseline
        configuration.persist.assert_called_once()
        return {"status": "released"}

    ports["admission"].release.side_effect = release
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["admission"].finalize.return_value = {"status": "released"}
    engine.finalize(record["operation_id"], resolved(), record["plan_hash"])
    configuration.persist.assert_called_once()


def test_parent_link_is_durable_before_continuation_takes_native_state_snapshot(runtime, ports, monkeypatch):
    import pipeline_lifecycle_recovery
    engine = service(runtime, ports)
    ports["planner"].prepare.return_value["continuation_required"] = True
    ports["admission"].finalize.return_value = {"status": "released"}
    original = resolved(1)
    parent = engine.prepare(original)
    engine.execute(parent["operation_id"], original, parent["plan_hash"])
    engine.finalize(parent["operation_id"], original, parent["plan_hash"])
    monkeypatch.setattr(pipeline_lifecycle_recovery, "continuation_snapshot", lambda *_: original)
    def prepare_child(snapshot, operation_id, **kwargs):
        stored = engine.status(parent["operation_id"])
        assert stored.get("continuation_child") == operation_id, "parent changed after frozen native state"
        return {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": []}]}
    ports["planner"].prepare.side_effect = prepare_child
    child = engine.prepare_continuation(parent["operation_id"], original, parent["plan_hash"])
    assert engine.status(parent["operation_id"])["continuation_child"] == child["operation_id"]


def test_bootstrap_child_requires_fresh_review_and_only_finalized_child_completes_parent(runtime, ports, monkeypatch):
    from .test_pipeline_inputs import register, request, inputs, SUB
    from .test_pipeline_lifecycle_adapters import snapshot as native_snapshot
    operational = {"schema": 1, "provider": "gha", "consumer_ref": "refs/heads/main",
                   "bootstrap": {"auth_namespace": "external"}}
    data = inputs.resolve_document(register(), request(1), operational=operational)
    resolver = Mock(wraps=inputs.resolve_document)
    monkeypatch.setattr(inputs, "resolve_document", resolver)
    engine = service(runtime, ports)
    origin = {"provider": "gha", "run_id": "42", "attempt": 1}
    context = {"run_id": 42}
    bootstrap = {"id": "bootstrap-enrollment", "kind": "bootstrap-enrollment"}
    native = {"id": "lifecycle", "kind": "lifecycle", "manifests": []}
    ports["planner"].prepare.side_effect = [
        {"origin": origin, "provider_context": context, "stages": [bootstrap]},
        {"origin": origin, "provider_context": context, "stages": [native]}]
    continuation = {"status": "continuation-required", "verified": True, "binding_candidate": {"targets": []}}
    complete = {"status": "succeeded", "verified": True}
    ports["executor"].execute.side_effect = [continuation, complete]
    ports["executor"].observe.side_effect = lambda stage, _: continuation if stage == bootstrap else complete
    ports["review"].origin.return_value = origin
    ports["review"].verify_finalizer.side_effect = lambda record: {
        "operation_id": record["operation_id"], "plan_hash": record["plan_hash"],
        "proof_kind": "github-rs256-native-finalizer"}
    configuration = Mock(spec=["prepare", "persist"])
    configuration.prepare.return_value = {"baseline": {"document": data["document"]}}
    promoted = copy.deepcopy(data["document"])
    binding = copy.deepcopy(native_snapshot()["binding"])
    binding["targets"][0].update(scale_set_id=data["scales"][0]["id"],
                                 resource_group_ids=[f"/subscriptions/{SUB}/resourceGroups/common"])
    promoted["bindings"] = {data["factory"]["id"]: {"gha": binding}}
    configuration.persist.return_value = {"document": promoted, "revision": runtime.digest(promoted)}
    engine.configuration = configuration
    ports["admission"].release.return_value = {"status": "provider-completion-pending"}
    ports["admission"].finalize.return_value = {"status": "released"}
    parent = engine.prepare(data)
    engine.execute(parent["operation_id"], data, parent["plan_hash"])
    with pytest.raises(runtime.PipelineError, match="continuation-finalization-required"):
        engine.prepare_continuation(parent["operation_id"], data, parent["plan_hash"])
    engine.finalize(parent["operation_id"], data, parent["plan_hash"])
    child = engine.prepare_continuation(parent["operation_id"], data, parent["plan_hash"])
    assert child["status"] == "prepared"
    assert child["snapshot"]["document"] == promoted
    resolver.assert_called_once_with(promoted, data["request"], operational=operational)
    assert child["snapshot"]["binding"]["bootstrap"] == operational["bootstrap"]
    assert child["plan"]["input_snapshot_hash"] == runtime.digest(data)
    assert child["plan_hash"] != parent["plan_hash"]
    assert ports["executor"].execute.call_count == 1
    repeated = engine.prepare_continuation(parent["operation_id"], data, parent["plan_hash"])
    assert repeated["operation_id"] == child["operation_id"]
    assert ports["planner"].prepare.call_count == 2
    revision, stopped = ports["store"].read(parent["operation_id"])
    stopped["status"] = "cancel-pending"
    ports["store"].write(parent["operation_id"], revision, stopped)
    with pytest.raises(runtime.PipelineError, match="continuation-parent-not-ready"):
        engine.execute(child["operation_id"], data, child["plan_hash"])
    revision, stopped = ports["store"].read(parent["operation_id"])
    stopped["status"] = "continuation-required"
    ports["store"].write(parent["operation_id"], revision, stopped)
    ports["review"].verify.side_effect = runtime.PipelineError("fresh-protected-review-required")
    with pytest.raises(runtime.PipelineError, match="fresh-protected"):
        engine.execute(child["operation_id"], data, child["plan_hash"])
    assert engine.status(parent["operation_id"])["status"] == "continuation-required"
    ports["review"].verify.side_effect = None
    engine.execute(child["operation_id"], data, child["plan_hash"])
    assert engine.status(parent["operation_id"])["status"] == "continuation-required"
    engine.finalize(child["operation_id"], data, child["plan_hash"])
    completed = engine.status(parent["operation_id"])
    assert completed["status"] == "succeeded"
    assert completed["completion"]["operation_id"] == child["operation_id"]
    assert engine.observe(parent["operation_id"])["status"] == "succeeded"
    assert ports["executor"].execute.call_count == 2
    receipt = {"operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"],
               "provider_context": context, "status": "succeeded"}
    assert runtime.verify_receipt(receipt, context, service=engine)["outcome"] == "completed"
    revision, unverified = ports["store"].read(child["operation_id"])
    unverified.pop("finalization")
    ports["store"].write(child["operation_id"], revision, unverified)
    with pytest.raises(runtime.PipelineError, match="continuation-finalization-required"):
        runtime.verify_receipt(receipt, context, service=engine)


@pytest.mark.parametrize("command", ["prepare", "execute", "status", "reconcile"])
def test_requested_cli_aliases_use_same_repository_input(runtime, command):
    args = runtime.parser().parse_args([command, "--request", "request.json", "--repository-root", "."])
    assert args.repo_root == "."
    assert args.request == "request.json"


def test_status_is_read_only_while_reconcile_observes_native_effects(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    revision = ports["store"].revision
    assert engine.status(record["operation_id"])["status"] == "prepared"
    assert ports["store"].revision == revision
    ports["executor"].observe.assert_not_called()
    ports["executor"].execute.side_effect = TimeoutError()
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    assert engine.reconcile(record["operation_id"])["status"] == "succeeded"
    assert ports["executor"].execute.call_count == 1


def test_failed_fresh_observation_is_durably_reconciliation_required(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())
    engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    ports["executor"].observe.side_effect = runtime.PipelineError("retained-resource-missing")
    result = engine.reconcile(record["operation_id"])
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "retained-resource-missing"
    assert engine.status(record["operation_id"])["status"] == "reconciliation-required"
    assert ports["executor"].execute.call_count == 1


def test_exact_outer_claim_is_durable_before_first_native_effect(runtime, ports):
    engine = service(runtime, ports)
    record = engine.prepare(resolved())

    def effect(stage, executing):
        stored = ports["store"].records[record["operation_id"]]
        assert stored["admission_claim"] == {"id": "test-authenticated-claim"}
        return {"status": "succeeded", "verified": True}

    ports["executor"].execute.side_effect = effect
    result = engine.execute(record["operation_id"], resolved(), record["plan_hash"])
    assert result["status"] == "succeeded"
    assert result["admission_claim"] == {"id": "test-authenticated-claim"}


@pytest.mark.parametrize("status,exit_code", [
    ("prepared", 2), ("running", 2), ("cancelled", 2), ("reconciliation-required", 2), ("succeeded", 0)])
def test_status_receipt_exit_code_only_succeeds_for_completed_native_outcome(runtime, monkeypatch, capsys, status, exit_code):
    import pipeline_inputs
    import pipeline_lifecycle_adapters
    from .test_pipeline_lifecycle_adapters import snapshot
    data = snapshot()
    engine = Mock()
    engine.status.return_value = {"operation_id": "11111111-1111-1111-1111-111111111111",
                                  "plan_hash": "d" * 64, "status": status, "snapshot": data,
                                  "plan": {}, "stages": [{"id": "lifecycle", "status": status}]}
    monkeypatch.setattr(pipeline_inputs, "read_json", Mock(return_value={}))
    monkeypatch.setattr(pipeline_inputs, "resolve_request", Mock(return_value=data))
    monkeypatch.setattr(pipeline_lifecycle_adapters, "build_service", Mock(return_value=engine))
    assert runtime.main(["status", "--request", "request.json", "--operation-id",
                         "11111111-1111-1111-1111-111111111111"]) == exit_code
    assert json.loads(capsys.readouterr().out)["status"] == status
    engine.observe.assert_not_called()
