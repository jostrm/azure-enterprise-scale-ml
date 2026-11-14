"""Provider continuation orchestration, with no live credentials or provider calls."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_dispatch as dispatch

PARENT = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"
HASH = "a" * 64


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live provider call forbidden"))


def context(provider="gha", run=7):
    return {"request_path": "requests/run.json", "request_digest": "d" * 64,
            "consumer_commit": "b" * 40, "source_commit": "c" * 40, "correlation_id": "e" * 32,
            "provider": provider, "repository": "https://github.com/acme/factory" if provider == "gha"
            else "https://dev.azure.com/acme/project/_git/factory",
            "run_id": run, "run_attempt": 1, "scenario": 1}


def record(provider="gha"):
    ctx = context(provider)
    return {"operation_id": PARENT, "plan_hash": HASH, "status": "continuation-required",
            "plan": {"provider_context": ctx, "origin": {
                "provider": provider, "run_id": "7", "attempt": 1, "commit": ctx["consumer_commit"],
                "ref": "refs/heads/main", "repository": ctx["repository"]}},
            "snapshot": {"request": {"provider": provider, "source_commit": ctx["source_commit"]}},
            "admission": {"status": "released"},
            "finalization": {"status": "succeeded", "proof": {
                "operation_id": PARENT, "plan_hash": HASH,
                "job_id": 42 if provider == "gha" else "finalize-job",
                "proof_kind": "github-rs256-native-finalizer" if provider == "gha"
                else "ado-native-server-finalizer"}}}


class PredecessorTraffic:
    def __init__(self, parent, states=None, mutation=None):
        self.parent = parent
        self.states = list(states or ["completed"])
        self.mutation = mutation
        self.calls = []
        self.last_state = None

    def request(self, method, url, body=None, raw=False):
        assert method == "GET" and body is None
        self.calls.append(url)
        ctx = self.parent["plan"]["provider_context"]
        if "/workflows/pipelines-only-gha.yml" in url:
            return 200, {}, {"id": 9, "path": ".github/workflows/pipelines-only-gha.yml", "state": "active"}
        if "/build/definitions/9?" in url:
            return 200, {}, {"id": 9, "process": {"yamlFilename": "pipelines-only-ado.yml"},
                             "repository": {"url": ctx["repository"]}}
        if "/jobs?" in url:
            complete = self.last_state in ("completed", "finalizer-completed")
            rows = []
            for index, name in enumerate(("prepare",
                                         f"Execute reviewed {self.parent['operation_id']} / {self.parent['plan_hash']}",
                                         f"Finalize reviewed {self.parent['operation_id']} / {self.parent['plan_hash']}")):
                rows.append({"id": 40 + index, "name": name, "run_id": ctx["run_id"], "run_attempt": 1,
                             "head_sha": ctx["consumer_commit"], "status": "completed" if complete else "in_progress",
                             "conclusion": ("failure" if self.mutation == "failed" else "success") if complete else None})
            return 200, {}, {"jobs": rows}
        if "/timeline?" in url:
            complete = self.last_state in ("completed", "finalizer-completed")
            rows = []
            for name, stage in (("PrepareOperation", "Prepare"), ("ExecuteReviewedOperation", "Execute"),
                                ("FinalizeReviewedOperation", "Finalize")):
                rows.append({"id": stage + "-stage", "type": "Stage", "name": stage, "attempt": 1})
                rows.append({"id": "finalize-job" if stage == "Finalize" else stage + "-job",
                             "parentId": stage + "-stage", "type": "Job", "identifier": name, "attempt": 1,
                             "state": "completed" if complete else "inProgress",
                             "result": ("failed" if self.mutation == "failed" else "succeeded") if complete else None})
            return 200, {}, {"records": rows}
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        self.last_state = state
        if state == "finalizer-completed":
            state = "in_progress" if ctx["provider"] == "gha" else "inProgress"
        if ctx["provider"] == "gha":
            value = {"id": ctx["run_id"], "workflow_id": 9, "event": "workflow_dispatch",
                     "display_title": f"pipelines-only [{ctx['correlation_id']}]",
                     "head_sha": ctx["consumer_commit"], "run_attempt": 1, "status": state,
                     "conclusion": "success" if state == "completed" else None,
                     "repository": {"full_name": "acme/factory"}}
        else:
            value = {"id": ctx["run_id"], "sourceVersion": ctx["consumer_commit"],
                     "sourceBranch": "refs/heads/main", "definition": {"id": 9},
                     "repository": {"url": ctx["repository"], "type": "TfsGit"},
                     "status": state, "result": "succeeded" if state == "completed" else None}
        if self.mutation == "failed":
            value.update(conclusion="failure", result="failed")
        elif self.mutation == "wrong-commit":
            value.update(head_sha="f" * 40, sourceVersion="f" * 40)
        elif self.mutation == "rerun":
            value["run_attempt"] = 2
        elif self.mutation == "manual-title":
            value["display_title"] = "pipelines-only []"
        return 200, {}, value


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_child_prepare_waits_for_exact_parent_finalizer_success_using_provider_gets_only(provider_name):
    import pipeline_provider as provider
    parent = record(provider_name)
    reader = Mock()
    reader._load.return_value = ("rev", parent)
    transport = PredecessorTraffic(parent, ["in_progress" if provider_name == "gha" else "inProgress", "completed"])
    sleeps = []
    provider.wait_for_predecessor(PARENT, HASH, dict(context(provider_name, 8), correlation_id="f" * 32),
                                  reader=reader, transport=transport, max_polls=3, sleep=sleeps.append)
    assert len(sleeps) == 1
    assert sum(url.endswith("/actions/runs/7") or "/build/builds/7?" in url for url in transport.calls) == 2
    reader.observe.assert_not_called()


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("mutation", ["failed", "wrong-commit", "not-terminal", "wrong-input", "unfinalized"])
def test_child_prepare_blocks_before_native_effects_for_unverified_predecessor(provider_name, mutation):
    import pipeline_provider as provider
    parent = record(provider_name)
    if mutation == "unfinalized":
        parent["finalization"]["status"] = "pending"
    child_context = dict(context(provider_name, 8), correlation_id="f" * 32)
    if mutation == "wrong-input":
        child_context["request_digest"] = "f" * 64
    reader = Mock()
    reader._load.return_value = ("rev", parent)
    transport = PredecessorTraffic(parent, ["in_progress"] if mutation == "not-terminal" else None, mutation)
    with pytest.raises(dispatch.DispatchError):
        provider.wait_for_predecessor(PARENT, HASH, child_context, reader=reader, transport=transport,
                                      max_polls=2, sleep=lambda _: None)
    reader.observe.assert_not_called()


def test_child_prepare_rejects_rerun_parent():
    import pipeline_provider as provider
    reader = Mock()
    reader._load.return_value = ("rev", record())
    with pytest.raises(dispatch.DispatchError, match="identity-mismatch"):
        provider.wait_for_predecessor(PARENT, HASH, dict(context(run=8), correlation_id="f" * 32),
                                      reader=reader, transport=PredecessorTraffic(record(), mutation="rerun"))


def test_child_prepare_accepts_exact_manual_ui_predecessor_with_generated_correlation():
    import pipeline_provider as provider
    reader = Mock()
    reader._load.return_value = ("rev", record())
    provider.wait_for_predecessor(PARENT, HASH, dict(context(run=8), correlation_id="f" * 32),
                                  reader=reader, transport=PredecessorTraffic(record(), mutation="manual-title"))


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_child_prepare_does_not_wait_for_ancestor_hosted_completion_job(provider_name):
    import pipeline_provider as provider
    reader = Mock()
    reader._load.return_value = ("rev", record(provider_name))
    provider.wait_for_predecessor(PARENT, HASH, dict(context(provider_name, 8), correlation_id="f" * 32),
                                  reader=reader, transport=PredecessorTraffic(record(provider_name), ["finalizer-completed"]),
                                  max_polls=1, sleep=lambda _: pytest.fail("Must not wait for enclosing workflow"))


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("current_record", [False, True])
@pytest.mark.parametrize("transport", ["lifecycle", "enrollment"])
def test_dispatched_integer_run_id_reaches_native_ancestor_admission(provider_name, current_record, transport):
    from unit.test_pipeline_lifecycle_cloud import ancestor_cloud
    cloud, registered, durable, state, parent, _, _, calls = ancestor_cloud(
        provider_name, current_record=current_record, transport=transport)
    # dispatch_run returns JSON integer IDs; native origin uses the provider's string ID.
    parent["provider_continuation"]["run_id"] = int(cloud.origin["run_id"])
    durable.set_state(state)
    cloud.assert_no_active_runs(registered) if transport == "lifecycle" else cloud.assert_no_active_runs()
    assert any("/jobs" in path or "/timeline" in path for path in calls)
    assert durable.calls and all(call[0] == "GET" for call in durable.calls)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("result", ["failed", "cancelled", "partial"])
def test_child_prepare_rejects_failed_run_even_when_finalizer_itself_succeeded(provider_name, result):
    import pipeline_provider as provider
    parent = record(provider_name)
    reader = Mock()
    reader._load.return_value = ("rev", parent)
    traffic = PredecessorTraffic(parent)
    original = traffic.request
    def request(method, url, body=None, raw=False):
        status, headers, value = original(method, url, body, raw)
        if value.get("id") == 7:
            value["conclusion" if provider_name == "gha" else "result"] = (
                {"failed": "failure", "cancelled": "cancelled", "partial": "neutral"}[result]
                if provider_name == "gha" else
                {"failed": "failed", "cancelled": "canceled", "partial": "partiallySucceeded"}[result])
        return status, headers, value
    traffic.request = request
    with pytest.raises(dispatch.DispatchError, match="scenario-provider-run-unsuccessful"):
        provider.wait_for_predecessor(PARENT, HASH, dict(context(provider_name, 8), correlation_id="f" * 32),
                                     reader=reader, transport=traffic, max_polls=1, sleep=lambda _: None)


def test_exit_three_is_checked_continuation_not_success_or_arbitrary_failure(tmp_path):
    import pipeline_provider as provider
    output = tmp_path / "receipt.json"
    expected = {"operation_id": PARENT, "plan_hash": HASH, "provider_context": context()}
    result = dict(expected, status="continuation-required", continuation={
        "command": "prepare-continuation", "requires_fresh_review": True,
        "operation_id": PARENT, "plan_hash": HASH})
    def run(command, **kwargs):
        output.write_text(json.dumps(result))
        return SimpleNamespace(returncode=3)
    assert provider.invoke(["python", "pipeline_lifecycle.py", "execute"], output,
                           expected=expected, run=run)["status"] == "continuation-required"
    result["status"] = "succeeded"
    with pytest.raises(dispatch.DispatchError, match="lifecycle-exit-status-mismatch"):
        provider.invoke([], output, expected=expected, run=run)
    result["status"] = "continuation-required"
    result["plan_hash"] = "f" * 64
    with pytest.raises(dispatch.DispatchError, match="lifecycle-result-binding-mismatch"):
        provider.invoke([], output, expected=expected, run=run)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_finalizer_claims_once_then_dispatches_same_pinned_template(provider_name):
    import pipeline_provider as provider
    parent = record(provider_name)
    service = Mock()
    service._load.side_effect = lambda _: ("rev", copy.deepcopy(parent))
    def save(revision, value):
        parent.update(copy.deepcopy(value))
        return "next"
    service._save.side_effect = save
    review = Mock(return_value=parent["finalization"]["proof"])
    launch = Mock(return_value=(8, {}, 9))
    binding = {"schema": 1, "provider": provider_name, "repository": context(provider_name)["repository"],
               "consumer_commit": "b" * 40, "consumer_ref": "refs/heads/main"}
    result = provider.schedule_continuation(service, PARENT, HASH, context(provider_name),
                                            binding, verify=review, launch=launch)
    assert result["run_id"] == 8
    assert parent["provider_continuation"]["status"] == "dispatched"
    assert service._save.call_args_list[0].args[1]["provider_continuation"]["status"] == "dispatching"
    parameters = launch.call_args.args[0]
    assert parameters["parent_operation_id"] == PARENT and parameters["parent_plan_hash"] == HASH
    assert parameters["consumer_commit"] == "b" * 40 and parameters["source_commit"] == "c" * 40
    assert review.call_count == 1
    with pytest.raises(dispatch.DispatchError, match="continuation-dispatch-already-claimed"):
        provider.schedule_continuation(service, PARENT, HASH, context(provider_name),
                                       binding, verify=review, launch=launch)
    assert launch.call_count == 1


@pytest.mark.parametrize("mutation", ["unreleased", "unfinalized", "wrong-context", "wrong-hash", "uncertain"])
def test_continuation_never_queues_without_exact_finalized_parent(mutation):
    import pipeline_provider as provider
    parent = record()
    if mutation == "unreleased":
        parent["admission"]["status"] = "held"
    elif mutation == "unfinalized":
        parent["finalization"]["status"] = "pending"
    elif mutation == "wrong-context":
        parent["plan"]["provider_context"]["run_id"] = 9
    elif mutation == "wrong-hash":
        parent["plan_hash"] = "f" * 64
    else:
        parent["status"] = "reconciliation-required"
    service = Mock()
    service._load.return_value = ("rev", parent)
    launch = Mock()
    with pytest.raises(dispatch.DispatchError):
        provider.schedule_continuation(service, PARENT, HASH, context(), {}, verify=Mock(), launch=launch)
    launch.assert_not_called()
    service._save.assert_not_called()


def test_uncertain_dispatch_leaves_claim_and_never_retries():
    import pipeline_provider as provider
    parent = record()
    service = Mock()
    service._load.side_effect = lambda _: ("rev", copy.deepcopy(parent))
    service._save.side_effect = lambda _, value: parent.update(copy.deepcopy(value))
    launch = Mock(side_effect=dispatch.DispatchError("transport-failed"))
    with pytest.raises(dispatch.DispatchError, match="transport-failed"):
        provider.schedule_continuation(service, PARENT, HASH, context(), {},
                                       verify=Mock(), launch=launch)
    assert parent["provider_continuation"]["status"] == "dispatching"
    assert launch.call_count == 1


def test_scheduler_authenticates_native_finalizer_before_claiming(monkeypatch):
    import pipeline_provider as provider
    import pipeline_approvals as approvals
    service = Mock()
    service._load.return_value = ("rev", record())
    verify = Mock(side_effect=approvals.ApprovalError("native-finalizer-required"))
    monkeypatch.setattr(approvals, "verify_finalizer", verify)
    launch = Mock()
    with pytest.raises(approvals.ApprovalError, match="native-finalizer-required"):
        provider.schedule_continuation(service, PARENT, HASH, context(), {}, launch=launch)
    verify.assert_called_once()
    service._save.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize("exit_code", [1, 2, 4, 137])
def test_uncertain_or_failed_lifecycle_never_becomes_continuation(tmp_path, exit_code):
    import pipeline_provider as provider
    output = tmp_path / "receipt.json"
    output.write_text(json.dumps({"status": "continuation-required"}))
    with pytest.raises(dispatch.DispatchError, match="lifecycle-command-not-completed"):
        provider.invoke([], output, expected={}, run=lambda *a, **k: SimpleNamespace(returncode=exit_code))


def test_read_only_verifier_requires_durable_dispatch_binding(monkeypatch):
    parent = record()
    correlation = "f" * 32
    parent["provider_continuation"] = {"status": "dispatched", "run_id": 8, "correlation_id": correlation}
    reader = Mock()
    reader._load.return_value = ("rev", parent)
    monkeypatch.setattr(dispatch, "ProviderReceiptReader", lambda _: reader)
    receipt = {"operation_id": PARENT, "plan_hash": HASH, "provider_context": context(),
               "status": "continuation-required", "provider_continuation": parent["provider_continuation"]}
    verified = dispatch.verify_lifecycle_receipt(receipt, context())
    assert verified["outcome"] == "continuation-required"
    assert verified["continuation"]["run_id"] == 8
    receipt["provider_continuation"] = dict(receipt["provider_continuation"], run_id=99)
    with pytest.raises(dispatch.DispatchError, match="continuation-dispatch-binding-mismatch"):
        dispatch.verify_lifecycle_receipt(receipt, context())
    reader.observe.assert_not_called()


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_local_wait_follows_child_without_another_dispatch(provider_name, monkeypatch):
    from test_pipeline_providers import Traffic, request, binding, CORRELATION
    traffic = Traffic(provider_name, "success" if provider_name == "gha" else "succeeded")
    original = traffic.request
    child_correlation = "f" * 32
    def request_api(method, url, body=None, raw=False):
        if "/runs/8" in url:
            row = traffic.run()
            row["id"] = 8
            row["display_title"] = f"pipelines-only [{child_correlation}]"
            row["templateParameters"] = {"correlation_id": child_correlation,
                                          "request_digest": dispatch.digest(request(provider_name))}
            traffic.calls.append((method, url, body))
            return 200, {}, row
        return original(method, url, body, raw)
    traffic.request = request_api
    receipts = {7: {"operation_id": PARENT, "plan_hash": HASH, "status": "continuation-required"},
                8: {"operation_id": CHILD, "plan_hash": "b" * 64, "status": "succeeded"}}
    monkeypatch.setattr(dispatch, "_receipt", lambda t, base, provider, run, corr: receipts[run])
    checked = []
    def verify(receipt, expected):
        checked.append((receipt, expected))
        if expected["run_id"] == 7 and receipt["status"] != "succeeded":
            return {"outcome": "continuation-required", "operation_id": PARENT, "plan_hash": HASH,
                    "continuation": {"run_id": 8, "correlation_id": child_correlation}}
        return {"outcome": "completed", "operation_id": receipt["operation_id"],
                "plan_hash": receipt["plan_hash"],
                "continuation_of": {"operation_id": PARENT, "plan_hash": HASH}
                if expected["run_id"] == 8 else None}
    result = dispatch.dispatch_and_wait("request.json", request(provider_name), binding(provider_name),
                                        transport=traffic, verify=verify, correlation_id=CORRELATION,
                                        sleep=lambda _: None, max_polls=3)
    assert result["operation_id"] == PARENT and result["run_id"] == 7
    assert [row[1]["run_id"] for row in checked] == [7, 8, 7]
    assert len([row for row in traffic.calls if row[0] == "POST"]) == 1


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("mutation", ["failed-child", "cycle", "wrong-parent", "unfinished-root"])
def test_local_wait_cannot_report_success_for_incomplete_or_unbound_chain(provider_name, mutation, monkeypatch):
    from test_pipeline_providers import Traffic, request, binding, CORRELATION
    traffic = Traffic(provider_name, "success" if provider_name == "gha" else "succeeded")
    original = traffic.request
    correlation = "f" * 32
    def request_api(method, url, body=None, raw=False):
        if "/runs/8" in url:
            row = traffic.run()
            row.update(id=8, display_title=f"pipelines-only [{correlation}]")
            row["templateParameters"] = {"correlation_id": correlation,
                                         "request_digest": dispatch.digest(request(provider_name))}
            if mutation == "failed-child":
                row.update(conclusion="failure", result="failed")
            return 200, {}, row
        return original(method, url, body, raw)
    traffic.request = request_api
    monkeypatch.setattr(dispatch, "_receipt", lambda t, base, provider, run, corr: {
        "operation_id": PARENT if run == 7 else CHILD, "plan_hash": HASH,
        "status": "continuation-required" if run == 7 else "succeeded"})
    def verify(receipt, expected):
        if expected["run_id"] == 7:
            if receipt["status"] == "succeeded":
                return {"outcome": "waiting"}
            return {"outcome": "continuation-required", "operation_id": PARENT, "plan_hash": HASH,
                    "continuation": {"run_id": 7 if mutation == "cycle" else 8, "correlation_id": correlation}}
        return {"outcome": "completed", "operation_id": CHILD, "plan_hash": HASH,
                "continuation_of": {"operation_id": CHILD if mutation == "wrong-parent" else PARENT,
                                    "plan_hash": HASH}}
    with pytest.raises(dispatch.DispatchError, match={
        "failed-child": "provider-run-unsuccessful", "cycle": "continuation-chain-invalid",
        "wrong-parent": "continuation-parent-binding-mismatch", "unfinished-root": "root-lifecycle-not-completed",
    }[mutation]):
        dispatch.dispatch_and_wait("request.json", request(provider_name), binding(provider_name),
                                   transport=traffic, verify=verify, correlation_id=CORRELATION,
                                   sleep=lambda _: None, max_polls=3)
    assert len([row for row in traffic.calls if row[0] == "POST"]) == 1


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("scenario,phases", [
    (1, ["bootstrap-enrollment", "common-and-project", "foundry-project"]),
    (1, ["admission-installation", "bootstrap-enrollment", "foundry-identity", "foundry-project"]),
    (3, ["retained-claim-reconciliation", "native-residual"]),
    (2, ["common"]), (3, ["foundry-identity", "foundry-project"]),
    (4, ["deletion-authorization", "delete"]), (5, ["deletion-authorization", "delete"]),
    (6, ["deletion-authorization", "delete"]),
])
def test_real_cli_all_phases_share_original_request_and_new_reviewed_runs(
        tmp_path, monkeypatch, provider_name, scenario, phases):
    import pipeline_provider as provider
    import pipeline_lifecycle as lifecycle
    import pipeline_lifecycle_adapters as adapters
    import pipeline_approvals as approvals
    from unit.test_pipeline_inputs import register, request, save, inputs, FACTORY, SCALE, SUB
    from unit.test_pipeline_lifecycle import Store
    from unit.test_pipeline_lifecycle_adapters import snapshot as native_snapshot

    raw = request(scenario, provider_name)
    save(tmp_path, register(provider_name))
    (tmp_path / "request.json").write_text(json.dumps(raw))
    canonical = inputs.resolve_request(tmp_path, raw)
    current = context(provider_name)
    current.update(request_path="request.json", request_digest=dispatch.digest(canonical),
                   scenario=scenario, source_commit=raw["source_commit"])
    recovering = phases[0] == "retained-claim-reconciliation"
    route = copy.deepcopy(native_snapshot()["binding"])
    route.update(orchestrator=provider_name, repository=current["repository"])
    route.pop("runner")
    route["locks"]["repository"] = current["repository"]
    route["targets"][0].update(scale_set_id=SCALE,
                               resource_group_ids=[f"/subscriptions/{SUB}/resourceGroups/common"])
    store = Store()
    planner, executor, review, admission, configuration = [Mock() for _ in range(5)]
    admission.assert_owned = Mock()
    engine = lifecycle.LifecycleService(store=store, planner=planner, executor=executor,
                                        review=review, admission=admission, configuration=configuration)
    def origin():
        return {"provider": provider_name, "run_id": str(current["run_id"]), "attempt": 1,
                "repository": current["repository"], "commit": current["consumer_commit"], "ref": "refs/heads/main"}
    def plan(snapshot, operation_id, **kwargs):
        index = snapshot["configuration"]["factory"].get("provider_test_phase", 0)
        return {"origin": origin(), "provider_context": copy.deepcopy(current),
                "continuation_required": phases[index] in ("admission-installation", "retained-claim-reconciliation"),
                "stages": [{"id": phases[index], "kind": phases[index]}]}
    planner.prepare.side_effect = plan
    planner.prepare_recovery.side_effect = lambda snapshot, prior, operation_id, **kwargs: plan(snapshot, operation_id)
    planner.prepare_residual.side_effect = lambda snapshot, prior, operation_id, **kwargs: {
        "origin": origin(), "provider_context": copy.deepcopy(current),
        "stages": [{"id": phases[-1], "kind": phases[-1]}]}
    review.origin.side_effect = lambda _: origin()
    review.verify.side_effect = lambda record: {
        "operation_id": record["operation_id"], "plan_hash": record["plan_hash"], "run_id": str(current["run_id"])}
    def proof(record):
        assert record["plan"]["provider_context"] == current
        return {"operation_id": record["operation_id"], "plan_hash": record["plan_hash"],
                "job_id": 42 if provider_name == "gha" else "finalize-job",
                "proof_kind": "github-rs256-native-finalizer" if provider_name == "gha"
                else "ado-native-server-finalizer"}
    review.verify_finalizer.side_effect = proof
    monkeypatch.setattr(approvals, "verify_finalizer", proof)
    def native(stage, record):
        if stage["kind"] == "prior-uncertain":
            raise TimeoutError("Native write response was lost")
        if stage["kind"] in ("admission-installation", "retained-claim-reconciliation"):
            return {"verified": True, "status": "succeeded", "requires_reprepare": True}
        last = stage["id"] == phases[-1]
        return {"verified": True, "status": "succeeded" if last else "continuation-required",
                "runtime_ready": last, "continuation": {"requires_fresh_review": True}}
    executor.execute.side_effect = native
    executor.observe.side_effect = native
    admission.acquire.return_value = {"id": "test-provider-claim"}
    admission.release.return_value = {"status": "provider-completion-pending"}
    admission.finalize.return_value = {"status": "released"}
    configuration.prepare.side_effect = lambda snapshot: {"baseline": {"document": snapshot["document"]}}
    configuration.prepare_recovery.side_effect = lambda snapshot, *_: configuration.prepare(snapshot)
    def persist(record):
        document = copy.deepcopy(record["snapshot"]["document"])
        config = document["configurations"][FACTORY]["factory"]
        config["provider_test_phase"] = config.get("provider_test_phase", 0) + 1
        if record["plan"]["stages"][0]["kind"] != "admission-installation":
            document["bindings"] = {FACTORY: {provider_name: route}}
        return {"document": document, "revision": lifecycle.digest(document)}
    configuration.persist.side_effect = persist
    monkeypatch.setattr(adapters, "build_service", lambda *args, **kwargs: engine)
    monkeypatch.setattr(dispatch, "operational_binding", lambda *args: {
        "schema": 1, "provider": provider_name, "repository": current["repository"],
        "consumer_commit": current["consumer_commit"], "consumer_ref": "refs/heads/main"})
    queued = []
    def launch(parameters, resolved, binding):
        assert resolved == canonical, "continuations must never replace the original request snapshot"
        queued.append(parameters)
        return current["run_id"] + 1, binding, 9
    monkeypatch.setattr(provider, "dispatch_run", launch)
    invocations = []
    def run(command, **kwargs):
        invocations.append(command)
        return SimpleNamespace(returncode=lifecycle.main(command[2:]))
    original_invoke = provider.invoke
    monkeypatch.setattr(provider, "invoke",
                        lambda command, output, **kwargs: original_invoke(command, output, run=run, **kwargs))
    monkeypatch.setattr(dispatch, "ProviderReceiptReader", lambda _: engine)
    original_wait = provider.wait_for_predecessor
    def wait(parent_id, parent_hash, child_context, **kwargs):
        parent_record = engine.status(parent_id)
        return original_wait(parent_id, parent_hash, child_context, reader=engine,
                             transport=PredecessorTraffic(parent_record, mutation="failed" if kwargs.get("recovery") else None),
                             sleep=lambda _: None, **kwargs)
    monkeypatch.setattr(provider, "wait_for_predecessor", wait)
    recovery_prior = None
    if recovering:
        current.update(run_id=6, correlation_id="d" * 32)
        planner.prepare.side_effect = lambda *a, **k: {
            "origin": origin(), "provider_context": copy.deepcopy(current),
            "stages": [{"id": "prior-uncertain", "kind": "prior-uncertain"}]}
        recovery_prior = engine.prepare(canonical)
        failed = engine.execute(recovery_prior["operation_id"], canonical, recovery_prior["plan_hash"])
        assert failed["status"] == "reconciliation-required" and "finalization" not in failed
        planner.prepare.side_effect = plan
        current.update(run_id=7, correlation_id="e" * 32)
    root_receipt, root_context = None, copy.deepcopy(current)
    parent = {}
    for index in range(len(phases)):
        relative = f"phase-{index}"
        (tmp_path / relative).mkdir()
        context_path = f"{relative}/context.json"
        (tmp_path / context_path).write_text(json.dumps(current))
        common = ["--repo-root", str(tmp_path), "--source-root", str(ROOT), "--request", "request.json",
                  "--provider-context", context_path]
        prepared_path, receipt_path = f"{relative}/prepared.json", f"{relative}/receipt.json"
        continuation = (["--parent-operation-id", parent["operation_id"], "--parent-plan-hash", parent["plan_hash"]]
                        if parent else [])
        if recovering and index == 0:
            continuation = ["--recovery-operation-id", recovery_prior["operation_id"],
                            "--recovery-plan-hash", recovery_prior["plan_hash"]]
        assert provider.main(["prepare", *common, "--output", prepared_path, *continuation]) == 0
        prepared = json.loads((tmp_path / prepared_path).read_text())
        assert provider.main(["execute", *common, "--prepared", prepared_path,
                              "--output", f"{relative}/execution.json"]) == 0
        if root_receipt:
            assert engine.status(root_receipt["operation_id"])["status"] == "continuation-required"
        assert provider.main(["finalize", *common, "--prepared", prepared_path, "--output", receipt_path]) == 0
        receipt = json.loads((tmp_path / receipt_path).read_text())
        root_receipt = root_receipt or receipt
        checked = dispatch.verify_lifecycle_receipt(receipt, current)
        if index < len(phases) - 1:
            assert checked["outcome"] == "continuation-required"
            parent = prepared
            current.update(run_id=receipt["provider_continuation"]["run_id"],
                           correlation_id=receipt["provider_continuation"]["correlation_id"])
        else:
            assert checked["outcome"] == "completed"
    assert dispatch.verify_lifecycle_receipt(dict(root_receipt, status="succeeded"), root_context)["outcome"] == "completed"
    assert len(queued) == len(phases) - 1
    expected_operations = len(phases) + int(recovering)
    assert review.verify.call_count == expected_operations
    assert len({call.args[0]["plan"]["provider_context"]["run_id"] for call in review.verify.call_args_list}) == expected_operations
    assert [row[2] for row in invocations].count("prepare-continuation") == len(phases) - 1
    assert executor.execute.call_count == expected_operations
    if recovering:
        assert [row[2] for row in invocations].count("prepare-recovery") == 1
        original = engine.status(recovery_prior["operation_id"])
        assert original["status"] == "recovered"
        assert original["plan"]["provider_context"]["run_id"] == 6
        assert original["recovery_completion"]["operation_id"] == root_receipt["operation_id"]
