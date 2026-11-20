"""A run whose durable receipt proves it never dispatched a worker can be reconciled and released (aif-163 run 2478)."""

import copy

import pytest

from .test_factory_lifecycle import fl, scoped_manifest, PlanCloud, seal, GROUP, no_real_services, workspace  # noqa: F401
from .test_single_writer_deletion import single_writer
from .test_pipeline_lifecycle_reconciliation import (  # noqa: F401
    reconciliation, fixture, install_native_evidence, reprepare, acquire_and_execute,
)


def never_dispatched(store, document):
    """Execute stopped before ado_scoped/github_scoped set mutation_started: no remote run, no worker receipt."""
    prefix = "runs/" + document["run_id"]
    run = store.value["records"][prefix + ".json"]
    run.pop("remote_run", None)
    run.update(status="blocked", mutation_started=False, error_code="active-or-queued-remote-run")
    store.value["records"].pop(prefix + ".worker.json", None)
    return run


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", [1, 2, 3])
def test_never_dispatched_run_reconciles_from_live_evidence_without_a_worker_poll(
        reconciliation, monkeypatch, provider, scenario):
    case = fixture(reconciliation, scenario, provider)
    service, store, _, _, stage, record, *_ = case
    never_dispatched(store, stage["manifests"][0])
    _, calls = install_native_evidence(reconciliation, case, monkeypatch)
    stage = reprepare(case)
    result = acquire_and_execute(service, stage, record)
    assert result["verified"] is True and result["status"] == "succeeded"
    assert any("/42" in path for path in calls)
    assert not any("/44" in path for path in calls)
    assert store.value["active"] is None and len(store.writes) == 1


@pytest.mark.parametrize("defect", ["mutation", "pending", "worker", "status", "remote"])
def test_dispatch_proof_is_still_required_unless_the_receipt_proves_no_dispatch(reconciliation, monkeypatch, defect):
    case = fixture(reconciliation, 3)
    service, store, _, _, stage, *_ = case
    document = stage["manifests"][0]
    run = never_dispatched(store, document)
    if defect == "mutation":
        run["mutation_started"] = True
    elif defect == "pending":
        run["pending_dispatch"] = {"kind": "ado", "pipeline_id": 8}
    elif defect == "worker":
        store.value["records"]["runs/" + document["run_id"] + ".worker.json"] = {
            "schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
            "source_commit": document["source"]["commit"], "target": document["target"], "status": "blocked"}
    elif defect == "status":
        run["status"] = "running"
    else:
        run["remote_run"] = {"kind": "ado", "pipeline_id": 8, "run_id": 44}
        run["mutation_started"] = True
    install_native_evidence(reconciliation, case, monkeypatch)
    with pytest.raises(ValueError, match="reconciliation-"):
        reprepare(case)
    assert store.writes == []


def claimed(provider="ado"):
    manifest, templates = scoped_manifest(("017",), operation="create-factory")
    cloud = PlanCloud(manifest, templates)
    manifest["locks"]["common_dependencies"] = []
    cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
    remote = single_writer(manifest, cloud, provider)
    seal(manifest)
    locks = fl.coordination(cloud, manifest)
    assert isinstance(locks, fl.RepositoryCoordination)
    locks.acquire()
    locks.claim_run()
    receipt = {"schema": 1, "run_id": manifest["run_id"], "manifest_hash": manifest["manifest_hash"],
               "manifest_revision": manifest["manifest_revision"], "operation": manifest["operation"],
               "target": manifest["target"], "source_commit": manifest["source"]["commit"],
               "status": "running", "mutation_started": False, "deleted_resources": [], "locks_retained": []}
    locks.store_receipt(copy.deepcopy(receipt))
    receipt.update(status="blocked", error_code="worker-pipeline-missing")
    return manifest, remote, locks, receipt


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_single_writer_claim_is_released_when_execute_stops_before_any_effect(provider):
    manifest, remote, locks, receipt = claimed(provider)
    locks.abort(receipt)
    state = remote.state()
    stored = state["records"]["runs/" + manifest["run_id"] + ".json"]
    assert state["active"] is None and not locks.held
    assert stored["status"] == "blocked" and stored["error_code"] == "worker-pipeline-missing"
    assert stored["mutation_started"] is False and stored["locks_retained"] == []
    assert stored["execution_claim"] == state["records"]["runs/" + manifest["run_id"] + ".claim.json"]
    locks.store_receipt(dict(receipt))  # execute's final persist after the release is a no-op, not an error


@pytest.mark.parametrize("defect", ["mutation", "pending", "remote", "worker", "stored-mutation", "succeeded"])
def test_single_writer_claim_is_kept_when_any_effect_may_have_started(defect):
    manifest, remote, locks, receipt = claimed()
    name = "runs/" + manifest["run_id"]
    if defect == "mutation":
        receipt["mutation_started"] = True
    elif defect == "pending":
        receipt["pending_dispatch"] = {"kind": "ado", "pipeline_id": 8}
    elif defect == "remote":
        receipt["remote_run"] = {"kind": "ado", "pipeline_id": 8, "run_id": 44}
    elif defect == "worker":
        state = remote.state()
        state["records"][name + ".worker.json"] = {"run_id": manifest["run_id"], "status": "running"}
        remote.set_state(state)
    elif defect == "stored-mutation":
        state = remote.state()
        state["records"][name + ".json"]["mutation_started"] = True
        remote.set_state(state)
    else:
        receipt["status"] = "succeeded"
    before = copy.deepcopy(remote.state())
    with pytest.raises(fl.Blocked, match="single-writer-claim-retained-reconciliation-required"):
        locks.abort(receipt)
    assert remote.state() == before and locks.held
