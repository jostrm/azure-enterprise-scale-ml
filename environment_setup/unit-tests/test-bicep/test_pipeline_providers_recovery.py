"""Provider wiring for explicit, freshly reviewed retained-claim recovery."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_dispatch as dispatch
import pipeline_provider as provider
from test_pipeline_providers_continuations import PARENT, CHILD, HASH, context, record, PredecessorTraffic
from test_pipeline_providers import Traffic, request, binding, CORRELATION


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live recovery call forbidden"))


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("status", ["running", "cancel-pending", "reconciliation-required"])
def test_recovery_wait_accepts_failed_terminal_prior_with_retained_unfinalized_claim(provider_name, status):
    prior = record(provider_name)
    prior.update(status=status, admission={"status": "held"})
    prior.pop("finalization")
    reader = Mock()
    reader._load.return_value = ("rev", prior)
    provider.wait_for_predecessor(PARENT, HASH, dict(context(provider_name, 8), correlation_id="f" * 32),
                                  recovery=True, reader=reader,
                                  transport=PredecessorTraffic(prior, mutation="failed"))
    reader.observe.assert_not_called()


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("mutation", ["active", "wrong-commit", "wrong-request", "prepared", "cancelled", "recovered"])
def test_recovery_predecessor_gate_cannot_bypass_identity_or_terminal_state(provider_name, mutation):
    prior = record(provider_name)
    prior.update(status="reconciliation-required", admission={"status": "held"})
    prior.pop("finalization")
    if mutation in ("prepared", "cancelled", "recovered"):
        prior["status"] = mutation
    ctx = dict(context(provider_name, 8), correlation_id="f" * 32)
    if mutation == "wrong-request":
        ctx["request_digest"] = "f" * 64
    reader = Mock()
    reader._load.return_value = ("rev", prior)
    with pytest.raises(dispatch.DispatchError):
        provider.wait_for_predecessor(PARENT, HASH, ctx, recovery=True, reader=reader,
                                      transport=PredecessorTraffic(prior, ["in_progress"] if mutation == "active" else None,
                                                                   mutation=mutation),
                                      max_polls=2, sleep=lambda _: None)
    reader.observe.assert_not_called()


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("status", ["succeeded", "continuation-required"])
def test_completed_recovery_candidate_reaches_native_review_only_after_provider_terminal(provider_name, status):
    prior = record(provider_name)
    prior.update(status=status, admission={"status": "provider-completion-pending"})
    prior.pop("finalization")
    reader = Mock()
    reader._load.return_value = ("rev", prior)
    traffic = PredecessorTraffic(prior)
    provider.wait_for_predecessor(PARENT, HASH, dict(context(provider_name, 8), correlation_id="f" * 32),
                                  recovery=True, reader=reader, transport=traffic)
    assert traffic.calls
    reader.observe.assert_not_called()
    reader.state_request.assert_not_called()
    active = PredecessorTraffic(prior, ["in_progress" if provider_name == "gha" else "inProgress"])
    with pytest.raises(dispatch.DispatchError, match="recovery-predecessor-wait-timeout"):
        provider.wait_for_predecessor(PARENT, HASH, dict(context(provider_name, 8), correlation_id="f" * 32),
                                      recovery=True, reader=reader, transport=active,
                                      max_polls=1, sleep=lambda _: None)


def test_helper_calls_prepare_recovery_with_original_request_and_a_new_reviewed_operation(tmp_path, monkeypatch):
    (tmp_path / "context.json").write_text(json.dumps(context(run=8)))
    gate = Mock()
    monkeypatch.setattr(provider, "wait_for_predecessor", gate)
    calls = []
    def invoke(command, output, **kwargs):
        calls.append(command)
        result = {"operation_id": CHILD, "plan_hash": "b" * 64, "status": "prepared",
                  "provider_context": context(run=8)}
        output.write_text(json.dumps(result))
        return result
    monkeypatch.setattr(provider, "invoke", invoke)
    assert provider.main(["prepare", "--repo-root", str(tmp_path), "--source-root", str(ROOT),
                          "--request", "request.json", "--provider-context", "context.json", "--output", "prepared.json",
                          "--recovery-operation-id", PARENT, "--recovery-plan-hash", HASH]) == 0
    assert calls[0][2] == "prepare-recovery"
    assert calls[0][calls[0].index("--operation-id") + 1] == PARENT
    assert calls[0][calls[0].index("--expected-plan-hash") + 1] == HASH
    gate.assert_called_once_with(PARENT, HASH, context(run=8), recovery=True)
    prepared = json.loads((tmp_path / "prepared.json").read_text())
    assert prepared["recovery_of"] == {"operation_id": PARENT, "plan_hash": HASH}
    assert "continuation_of" not in prepared and prepared["operation_id"] != PARENT


@pytest.mark.parametrize("fields", [
    {"recovery_operation_id": PARENT}, {"recovery_plan_hash": HASH},
    {"recovery_operation_id": "not-an-id", "recovery_plan_hash": HASH},
    {"recovery_operation_id": PARENT, "recovery_plan_hash": "not-a-hash"},
    {"parent_operation_id": PARENT, "parent_plan_hash": HASH,
     "recovery_operation_id": PARENT, "recovery_plan_hash": HASH},
])
def test_recovery_selection_invalid_or_ambiguous_never_dispatches(fields):
    traffic = Traffic("gha")
    with pytest.raises((dispatch.DispatchError, ValueError)):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"),
                                   transport=traffic, **fields)
    assert traffic.calls == []


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_recovery_dispatch_uses_new_root_context_without_selection_fields_in_context(provider_name, monkeypatch):
    traffic = Traffic(provider_name, "success" if provider_name == "gha" else "succeeded")
    monkeypatch.setattr(dispatch, "_receipt", lambda *_: {
        "operation_id": CHILD, "plan_hash": "b" * 64, "status": "succeeded"})
    checked = []
    def verify(receipt, expected):
        checked.append(expected)
        return {"outcome": "completed", "operation_id": CHILD, "plan_hash": "b" * 64,
                "recovery_of": {"operation_id": PARENT, "plan_hash": HASH}}
    result = dispatch.dispatch_and_wait("request.json", request(provider_name), binding(provider_name),
                                        transport=traffic, verify=verify, correlation_id=CORRELATION,
                                        recovery_operation_id=PARENT, recovery_plan_hash=HASH,
                                        max_polls=2, sleep=lambda _: None)
    posted = next(row[2] for row in traffic.calls if row[0] == "POST")
    parameters = posted["inputs" if provider_name == "gha" else "templateParameters"]
    assert parameters["recovery_operation_id"] == PARENT and parameters["recovery_plan_hash"] == HASH
    assert "parent_operation_id" not in parameters
    assert result["operation_id"] == CHILD and result["run_id"] == 7
    assert all("recovery_operation_id" not in row and "recovery_plan_hash" not in row for row in checked)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_recovery_dispatch_rejects_unrelated_fresh_operation(provider_name, monkeypatch):
    traffic = Traffic(provider_name, "success" if provider_name == "gha" else "succeeded")
    monkeypatch.setattr(dispatch, "_receipt", lambda *_: {})
    with pytest.raises(dispatch.DispatchError, match="selected-predecessor-binding-mismatch"):
        dispatch.dispatch_and_wait("request.json", request(provider_name), binding(provider_name),
                                   transport=traffic, verify=lambda *_: {"outcome": "completed", "operation_id": CHILD},
                                   correlation_id=CORRELATION, recovery_operation_id=PARENT, recovery_plan_hash=HASH,
                                   max_polls=2, sleep=lambda _: None)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_recovery_completion_follows_residual_child_but_returns_new_recovery_root(provider_name, monkeypatch):
    traffic = Traffic(provider_name, "success" if provider_name == "gha" else "succeeded")
    original = traffic.request
    residual = "33333333-3333-4333-8333-333333333333"
    child_correlation = "f" * 32
    def request_api(method, url, body=None, raw=False):
        if "/runs/8" in url:
            row = traffic.run()
            row.update(id=8, display_title=f"pipelines-only [{child_correlation}]")
            row["templateParameters"] = {"correlation_id": child_correlation,
                                         "request_digest": dispatch.digest(request(provider_name))}
            traffic.calls.append((method, url, body))
            return 200, {}, row
        return original(method, url, body, raw)
    traffic.request = request_api
    monkeypatch.setattr(dispatch, "_receipt", lambda t, base, provider, run, corr: {
        "operation_id": CHILD if run == 7 else residual, "plan_hash": "b" * 64 if run == 7 else "c" * 64,
        "status": "continuation-required" if run == 7 else "succeeded"})
    checked = []
    def verify(receipt, expected):
        checked.append((receipt["operation_id"], expected))
        if expected["run_id"] == 7:
            return {"outcome": "completed" if receipt["status"] == "succeeded" else "continuation-required",
                    "operation_id": CHILD, "plan_hash": "b" * 64,
                    "recovery_of": {"operation_id": PARENT, "plan_hash": HASH},
                    "continuation": {"run_id": 8, "correlation_id": child_correlation}}
        return {"outcome": "completed", "operation_id": residual, "plan_hash": "c" * 64,
                "continuation_of": {"operation_id": CHILD, "plan_hash": "b" * 64}}
    result = dispatch.dispatch_and_wait("request.json", request(provider_name), binding(provider_name),
                                        transport=traffic, verify=verify, correlation_id=CORRELATION,
                                        recovery_operation_id=PARENT, recovery_plan_hash=HASH,
                                        max_polls=3, sleep=lambda _: None)
    assert result["operation_id"] == CHILD and result["run_id"] == 7
    assert [operation for operation, _ in checked] == [CHILD, residual, CHILD]
    assert [ctx["run_id"] for _, ctx in checked] == [7, 8, 7]
    assert len([row for row in traffic.calls if row[0] == "POST"]) == 1


def test_helper_refuses_continuation_and_recovery_before_any_gate_or_native_command(tmp_path, monkeypatch):
    gate, invoke = Mock(), Mock()
    monkeypatch.setattr(provider, "wait_for_predecessor", gate)
    monkeypatch.setattr(provider, "invoke", invoke)
    assert provider.main(["prepare", "--repo-root", str(tmp_path), "--request", "request.json",
                          "--provider-context", "context.json", "--output", "prepared.json",
                          "--parent-operation-id", PARENT, "--parent-plan-hash", HASH,
                          "--recovery-operation-id", CHILD, "--recovery-plan-hash", "b" * 64]) == 2
    gate.assert_not_called()
    invoke.assert_not_called()


def test_helper_rejects_rebinding_the_prior_operation(tmp_path, monkeypatch):
    (tmp_path / "context.json").write_text(json.dumps(context(run=8)))
    monkeypatch.setattr(provider, "wait_for_predecessor", Mock())
    def invoke(command, output, **kwargs):
        result = {"operation_id": PARENT, "plan_hash": HASH, "status": "prepared",
                  "provider_context": context(run=8)}
        output.write_text(json.dumps(result))
        return result
    monkeypatch.setattr(provider, "invoke", invoke)
    assert provider.main(["prepare", "--repo-root", str(tmp_path), "--request", "request.json",
                          "--provider-context", "context.json", "--output", "prepared.json",
                          "--recovery-operation-id", PARENT, "--recovery-plan-hash", HASH]) == 2


def test_recovery_relationship_is_read_from_durable_plan_not_artifact_json(monkeypatch):
    parent = record()
    parent["plan"]["recovery_of"] = {"operation_id": CHILD, "plan_hash": "b" * 64}
    parent["provider_continuation"] = {"status": "dispatched", "run_id": 8, "correlation_id": "f" * 32}
    reader = Mock()
    reader._load.return_value = ("rev", parent)
    monkeypatch.setattr(dispatch, "ProviderReceiptReader", lambda _: reader)
    receipt = {"operation_id": PARENT, "plan_hash": HASH, "provider_context": context(),
               "status": "continuation-required", "provider_continuation": parent["provider_continuation"],
               "recovery_of": {"operation_id": PARENT, "plan_hash": HASH}}
    checked = dispatch.verify_lifecycle_receipt(receipt, context())
    assert checked["recovery_of"] == parent["plan"]["recovery_of"]


def test_cli_validates_recovery_pair_and_passes_selection_without_provider_writes(tmp_path, monkeypatch):
    canonical = {"request": request("gha"), "binding": {"repository": binding("gha")["repository"]}}
    monkeypatch.setattr(dispatch, "load_request", lambda *_: canonical)
    monkeypatch.setattr(dispatch, "operational_binding", lambda *_: binding("gha"))
    monkeypatch.setattr(dispatch, "verify_checkout", lambda *_: None)
    launch = Mock(return_value={"outcome": "completed"})
    monkeypatch.setattr(dispatch, "dispatch_and_wait", launch)
    args = ["--repo-root", str(tmp_path), "--request", "request.json",
            "--recovery-operation-id", PARENT, "--recovery-plan-hash", HASH]
    assert dispatch.main(args + ["--validate-only"]) == 0
    launch.assert_not_called()
    assert dispatch.main(args) == 0
    assert launch.call_args.kwargs["recovery_operation_id"] == PARENT
    assert launch.call_args.kwargs["recovery_plan_hash"] == HASH
