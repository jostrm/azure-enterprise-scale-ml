"""Hosted read-only completion must represent verified effects, not child dispatch."""
import copy
import json
from pathlib import Path
import re
import socket
import sys
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_dispatch as dispatch
import pipeline_lifecycle as lifecycle
import pipeline_observer as observer
import pipeline_provider as provider
from test_pipeline_providers_export import export_state
from test_pipeline_providers_continuations import PARENT, CHILD, PredecessorTraffic


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live completion call forbidden"))


def observation_state(provider_name, *, finished=True):
    _, _, state, _ = export_state(provider_name)
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    child = state["records"]["pipeline-lifecycle/" + CHILD + ".json"]
    for row in (root, child):
        row["plan"]["origin"] = {"ref": "refs/heads/main"}
        if row is child:
            row["plan"]["continuation_of"]["plan_hash"] = root["plan_hash"]
        row["plan_hash"] = lifecycle.digest(lifecycle.bound_plan(row))
        row["finalization"]["proof"].update(plan_hash=row["plan_hash"],
                                            job_id=42 if provider_name == "gha" else "finalize-job")
    root["completion"]["plan_hash"] = child["plan_hash"]
    root["continuation_child"] = CHILD
    root["provider_continuation"] = {"status": "dispatched", "run_id": 8, "correlation_id": "f" * 32}
    if not finished:
        root["status"] = "continuation-required"
        root.pop("completion")
        child["status"] = "running"
        child.pop("finalization")
        child["admission"]["status"] = "held"
    return state


class ObservationTraffic:
    def __init__(self, state, *, child_state="finalizer-completed", child_mutation=None):
        rows = [state["records"]["pipeline-lifecycle/" + identifier + ".json"] for identifier in (PARENT, CHILD)]
        self.traffic = {row["plan"]["provider_context"]["run_id"]: PredecessorTraffic(
            row, [child_state if row["operation_id"] == CHILD else "finalizer-completed"],
            mutation=child_mutation if row["operation_id"] == CHILD else None) for row in rows}
        self.calls = []

    def request(self, method, url, body=None, raw=False):
        assert method == "GET" and body is None and "management.azure.com" not in url
        self.calls.append(url)
        match = re.search(r"/(?:runs|builds)/([0-9]+)(?:[/?]|$)", url)
        return self.traffic[int(match[1]) if match else 7].request(method, url, body, raw)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_hosted_observer_waits_for_durable_leaf_but_not_descendant_completion_jobs(provider_name):
    pending = observation_state(provider_name, finished=False)
    finished = observation_state(provider_name)
    root = finished["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    reader = Mock()
    reader.read_snapshot.side_effect = [dispatch.ProviderStateSnapshot("a" * 40, pending),
                                        dispatch.ProviderStateSnapshot("b" * 40, finished)]
    traffic, sleeps = ObservationTraffic(finished), []
    result = observer.wait_for_completion(PARENT, root["plan_hash"], root["plan"]["provider_context"],
                                          reader=reader, transport=traffic, max_polls=2, sleep=sleeps.append)
    assert result["outcome"] == "completed" and result["operation_id"] == PARENT
    assert len(sleeps) == 1
    assert all(item.last_state == "finalizer-completed" for item in traffic.traffic.values())
    assert any("/jobs?" in url or "/timeline?" in url for url in traffic.calls)
    reader.observe.assert_not_called()
    reader.state_request.assert_not_called()


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("mutation", ["running-finalizer", "failed-run", "bad-source", "bad-finalizer-proof", "held-leaf"])
def test_hosted_observer_never_returns_green_on_partial_or_unverified_outcomes(provider_name, mutation):
    state = observation_state(provider_name)
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    child = state["records"]["pipeline-lifecycle/" + CHILD + ".json"]
    if mutation == "bad-finalizer-proof":
        child["finalization"]["proof"]["job_id"] = "wrong-job"
    elif mutation == "held-leaf":
        child["admission"]["status"] = "held"
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    traffic = ObservationTraffic(state, child_state="in_progress" if mutation == "running-finalizer" else "finalizer-completed",
                                 child_mutation="failed" if mutation == "failed-run" else
                                 "wrong-commit" if mutation == "bad-source" else None)
    if mutation == "failed-run":
        traffic.traffic[8].states = ["completed"]
    with pytest.raises((dispatch.DispatchError, ValueError)):
        observer.wait_for_completion(PARENT, root["plan_hash"], root["plan"]["provider_context"],
                                     reader=reader, transport=traffic, max_polls=1, sleep=lambda _: None)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
@pytest.mark.parametrize("mutation", ["cancelling", "missing-status", "running-failure"])
def test_hosted_observer_requires_positive_active_or_terminal_run_evidence(provider_name, mutation):
    state = observation_state(provider_name)
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    traffic = ObservationTraffic(state)
    original = traffic.request
    def request(method, url, body=None, raw=False):
        status, headers, value = original(method, url, body, raw)
        if value.get("id") == 8:
            if mutation == "missing-status":
                value.pop("status")
            elif mutation == "cancelling":
                value["status"] = "cancelling"
            else:
                value["conclusion" if provider_name == "gha" else "result"] = (
                    "failure" if provider_name == "gha" else "failed")
        return status, headers, value
    traffic.request = request
    with pytest.raises(dispatch.DispatchError, match="scenario-provider-run-unsuccessful"):
        observer.wait_for_completion(PARENT, root["plan_hash"], root["plan"]["provider_context"],
                                     reader=reader, transport=traffic, max_polls=1, sleep=lambda _: None)


@pytest.mark.parametrize("provider_name,status", [
    ("gha", "queued"), ("gha", "in_progress"), ("gha", "waiting"), ("gha", "pending"), ("gha", "requested"),
    ("ado", "notStarted"), ("ado", "inProgress"), ("ado", "postponed"),
])
def test_scheduled_child_may_wait_for_fresh_review_without_becoming_completed(provider_name, status):
    state = observation_state(provider_name, finished=False)
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    traffic = ObservationTraffic(state, child_state=status)
    with pytest.raises(dispatch.DispatchError, match="completion-timeout-not-completed"):
        observer.wait_for_completion(PARENT, root["plan_hash"], root["plan"]["provider_context"],
                                     reader=reader, transport=traffic, max_polls=1, sleep=lambda _: None)


def test_completion_cli_never_invokes_mutating_lifecycle_or_credential_helpers(tmp_path, monkeypatch):
    state = observation_state("gha")
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    context = root["plan"]["provider_context"]
    (tmp_path / "context.json").write_text(json.dumps(context))
    (tmp_path / "prepared.json").write_text(json.dumps({
        "operation_id": PARENT, "plan_hash": root["plan_hash"], "provider_context": context}))
    wait = Mock(return_value={"outcome": "completed", "operation_id": PARENT, "plan_hash": root["plan_hash"]})
    monkeypatch.setattr(observer, "wait_for_completion", wait)
    monkeypatch.setattr(provider, "invoke", lambda *_a, **_k: pytest.fail("Read-only completion cannot invoke lifecycle"))
    assert provider.main(["complete", "--repo-root", str(tmp_path), "--request", "request.json",
                          "--provider-context", "context.json", "--prepared", "prepared.json",
                          "--output", "completed.json"]) == 0
    assert json.loads((tmp_path / "completed.json").read_text())["outcome"] == "completed"
    wait.assert_called_once_with(PARENT, root["plan_hash"], context, max_polls=1200)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_completion_job_is_exact_hosted_read_only_unprotected_observer(provider_name):
    text = (ROOT / "bootstrap/templates" / f"pipelines-only-{provider_name}.yml").read_text()
    pipeline = yaml.load(text, Loader=yaml.BaseLoader)
    if provider_name == "gha":
        job = pipeline["jobs"]["complete"]
        assert job["name"] == "complete" and job["runs-on"] == "ubuntu-latest"
        assert job["needs"] == ["prepare", "finalize"]
        assert job["permissions"] == {"contents": "read", "actions": "read"}
        assert job["env"] == {"GH_TOKEN": "${{ github.token }}"}
    else:
        stage = next(stage for stage in pipeline["stages"] if stage["stage"] == "Complete")
        assert stage["dependsOn"] == ["Prepare", "Finalize"]
        job = stage["jobs"][0]
        assert job["job"] == job["displayName"] == "ObserveScenarioCompletion"
        assert job["pool"] == {"vmImage": "ubuntu-latest"}
    serialized = json.dumps(job)
    assert "pipeline_provider.py complete" in serialized
    assert "environment" not in job
    for forbidden in ("azure/login", "AzureCLI", "pipeline_credentials.py", "ESAF_PROVIDER_TOKEN",
                      "ESAF_PROVIDER_CREDENTIAL", "AZURE_", "id-token", "--download-input"):
        assert forbidden not in serialized
