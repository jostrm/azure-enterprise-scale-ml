import copy
import importlib
import json
import sys
from types import SimpleNamespace
from urllib.error import URLError
from unittest.mock import Mock
import hashlib
from uuid import uuid4

import pytest

from .test_factory_lifecycle import manifest, enrollment, ROOT
from . import test_single_writer_coordination as native

sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))


def ancestor_cloud(provider, *, current_record=False, transport="lifecycle"):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    core = importlib.import_module("pipeline_lifecycle")
    shared = importlib.import_module("lifecycle_admission")
    approvals = importlib.import_module("pipeline_approvals")
    repository = "https://github.com/org/repo" if provider == "gha" else "https://dev.azure.com/org/project/_git/repo"
    origin = {"provider": provider, "repository": "org/repo" if provider == "gha" else repository,
              "run_id": "99", "attempt": 1, "commit": "b" * 40, "ref": "refs/heads/main"}
    parent_origin = {**origin, "run_id": "42"}
    parent = {"schema": 1, "operation_id": str(uuid4()), "snapshot": {"factory": {"id": "factory-a"}},
              "plan": {"origin": parent_origin, "stages": [], "continuation_required": True},
              "prepared_at": "2026-11-13T10:00:00Z", "status": "continuation-required",
              "admission": {"status": "released"},
              "provider_continuation": {"status": "dispatched", "run_id": "99", "correlation_id": str(uuid4())}}
    parent["snapshot_hash"] = core.digest(parent["snapshot"])
    parent["plan_hash"] = core.digest(core.bound_plan(parent))
    proof = {**parent_origin, "operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"],
             "environment": approvals.ENVIRONMENT,
             "workflow_sha256": hashlib.sha256((approvals.TEMPLATES / f"pipelines-only-{provider}.yml")
                                                .read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
             "proof_kind": "github-rs256-native-finalizer" if provider == "gha" else "ado-native-server-finalizer",
             "job_id": 3 if provider == "gha" else "finalize-job", "execution_job_id": 2 if provider == "gha" else "execute-job",
             "execution_result": "success" if provider == "gha" else "succeeded"}
    parent["finalization"] = {"status": "succeeded", "proof": proof}
    claim = {"id": str(uuid4()), "protocol": shared.PROTOCOL, "route": "pipeline",
             "operation_id": parent["operation_id"], "review_digest": parent["plan_hash"],
             "identity": {"run_id": "42", "repository": repository}}
    parent["admission_claim"] = claim
    observation = {"run_id": "42", "repository": repository, "terminal": True,
                   "inventory_complete": True, "active_operations": [], "evidence_id": "native-observed"}
    records = {f"pipeline-lifecycle/{parent['operation_id']}.json": parent,
               shared.RECORD: {"claim": None, "history": {claim["id"]: {"claim": claim, "observation": observation}}}}
    if current_record:
        child = {"schema": 1, "operation_id": str(uuid4()), "snapshot": parent["snapshot"],
                 "plan": {"origin": origin, "continuation_of": {
                     "operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"]}},
                 "prepared_at": parent["prepared_at"], "snapshot_hash": parent["snapshot_hash"]}
        child["plan_hash"] = core.digest(core.bound_plan(child))
        parent["continuation_child"] = child["operation_id"]
        records[f"pipeline-lifecycle/{child['operation_id']}.json"] = child
    state = {"schema": 1, "repository": repository, "enrollment": None, "active": None, "records": records}
    durable = native.Provider(repository)
    if provider == "gha":
        run = {"id": 42, "run_attempt": 1, "head_sha": origin["commit"], "head_branch": "main",
               "repository": {"full_name": "org/repo"}, "status": "in_progress", "conclusion": None,
               "event": "workflow_dispatch", "path": ".github/workflows/pipelines-only-gha.yml"}
        names = ["prepare", f"Execute reviewed {parent['operation_id']} / {parent['plan_hash']}",
                 f"Finalize reviewed {parent['operation_id']} / {parent['plan_hash']}", "complete"]
        jobs = [{"id": number, "name": name, "run_id": 42, "run_attempt": 1, "head_sha": origin["commit"],
                 "status": "completed", "conclusion": "success", "labels": ["ubuntu-latest"]}
                for number, name in enumerate(names, 1)]
        jobs[-1].update(status="in_progress", conclusion=None)
    else:
        run = {"id": 42, "sourceVersion": origin["commit"], "sourceBranch": origin["ref"],
               "repository": {"id": native.te.PROJECT, "type": "TfsGit", "url": repository},
               "status": "inProgress", "result": None, "definition": {"id": 7, "revision": 1}}
        jobs = []
        for stage, name in [("Prepare", "PrepareOperation"), ("Review", "ReviewPipelinesLifecycle"),
                            ("Execute", "ExecuteReviewedOperation"), ("Finalize", "FinalizeReviewedOperation"),
                            ("Complete", "ObserveScenarioCompletion")]:
            jobs.extend([{"id": stage, "name": stage, "type": "Stage", "attempt": 1,
                          "state": "completed", "result": "succeeded"},
                         {"id": stage.lower() + "-job", "identifier": name, "type": "Job",
                          "parentId": stage, "attempt": 1, "state": "completed", "result": "succeeded"}])
        for row in jobs[-2:]:
            row.update(state="inProgress", result=None)
    calls = []

    def open_request(request, **kwargs):
        assert request.method == "GET"
        path = request.full_url.removeprefix("https://api.github.com/")
        calls.append(path)
        if "/actions/runs?" in path:
            data = {"total_count": 1, "workflow_runs": [run]} if "status=in_progress" in path else {
                "total_count": 0, "workflow_runs": []}
        elif "/actions/runs/42/jobs" in path:
            data = {"total_count": len(jobs), "jobs": jobs}
        elif "/actions/runs/42" in path:
            data = run
        elif "/build/builds?" in path:
            data = {"count": 1, "value": [run]}
        elif "/build/builds/42/timeline" in path:
            data = {"records": jobs}
        elif "/build/builds/42" in path:
            data = run
        elif "/build/definitions/7" in path:
            data = {"id": 7, "revision": 1, "repository": {"id": native.te.PROJECT},
                    "process": {"yamlFilename": "pipelines-only-ado.yml"}}
        else:
            _, _, data = durable.call(provider, "GET", path, None, (200,))
            if provider == "ado" and "/git/repositories/repo?" in path:
                data["id"] = native.te.PROJECT
        return native.te.Response(200, data)

    document = manifest()
    document["locks"]["coordination_mode"] = "single-writer"
    document["route"].update(kind=provider, repository=repository)
    cloud_type = module.PipelineCloud if transport == "lifecycle" else module.PipelineEnrollmentCloud
    value = document if transport == "lifecycle" else {
        "route": document["route"], "coordination_mode": "single-writer"}
    cloud = cloud_type(value, origin, opener=SimpleNamespace(open=open_request),
                       environ={"GH_TOKEN": "provider-only", "AIFACTORY_STATE_TOKEN": "provider-only"})
    registered = enrollment()
    registered["writers"]["writer-a"].update(kind=provider, repository=repository)
    return cloud, registered, durable, state, parent, run, jobs, calls


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("current_record", [False, True])
@pytest.mark.parametrize("transport", ["lifecycle", "enrollment"])
def test_authenticated_readonly_ancestor_waiter_does_not_deadlock_child(provider, current_record, transport):
    cloud, registered, durable, state, _, _, _, calls = ancestor_cloud(
        provider, current_record=current_record, transport=transport)
    durable.set_state(state)
    cloud.assert_no_active_runs(registered) if transport == "lifecycle" else cloud.assert_no_active_runs()
    assert any("/jobs" in path or "/timeline" in path for path in calls)
    assert durable.calls and all(call[0] == "GET" for call in durable.calls)


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("change", ["unrelated", "unreleased", "unfinalized", "wrong-proof", "tampered-plan",
                                    "wrong-source", "wrong-ref", "rerun", "failed", "cancelled",
                                    "mutating", "unknown-job", "missing-job", "retained-claim", "no-native-history",
                                    "wrong-template", "queued", "self-hosted-waiter", "native-active-ancestor"])
def test_ancestor_exception_fails_closed(provider, change):
    cloud, registered, durable, state, parent, run, jobs, _ = ancestor_cloud(provider)
    shared = importlib.import_module("lifecycle_admission")
    if change == "unrelated":
        parent["provider_continuation"]["run_id"] = "100"
    elif change == "unreleased":
        parent["admission"]["status"] = "provider-completion-pending"
    elif change == "unfinalized":
        parent["finalization"]["status"] = "pending"
    elif change == "wrong-proof":
        parent["finalization"]["proof"]["run_id"] = "41"
    elif change == "tampered-plan":
        parent["plan"]["origin"]["commit"] = "c" * 40
    elif change == "wrong-source":
        run["head_sha" if provider == "gha" else "sourceVersion"] = "c" * 40
    elif change == "wrong-ref":
        run["head_branch" if provider == "gha" else "sourceBranch"] = "other"
    elif change == "rerun":
        jobs[0]["run_attempt" if provider == "gha" else "attempt"] = 2
    elif change in ("failed", "cancelled"):
        jobs[0]["conclusion" if provider == "gha" else "result"] = (
            {"failed": "failure", "cancelled": "cancelled"}[change] if provider == "gha"
            else {"failed": "failed", "cancelled": "canceled"}[change])
    elif change == "mutating":
        jobs[0]["status" if provider == "gha" else "state"] = "in_progress" if provider == "gha" else "inProgress"
    elif change == "unknown-job":
        jobs.append({**jobs[-1], "id": "unknown", "name": "unknown", "identifier": "unknown"})
    elif change == "missing-job":
        del jobs[0]
    elif change == "retained-claim":
        state["records"][shared.RECORD]["claim"] = parent["admission_claim"]
    elif change == "native-active-ancestor":
        state["active"] = {"operation_id": parent["operation_id"]}
    elif change == "no-native-history":
        state["records"][shared.RECORD]["history"] = {}
    elif change == "wrong-template":
        parent["finalization"]["proof"]["workflow_sha256"] = "0" * 64
    elif change == "queued":
        run["status"] = "queued" if provider == "gha" else "notStarted"
    else:
        if provider == "gha":
            jobs[-1]["labels"] = ["self-hosted", "esaf-lifecycle-external"]
        else:
            jobs[-1]["identifier"] = "ExecuteReviewedOperation"
    durable.set_state(state)
    with pytest.raises(ValueError):
        cloud.assert_no_active_runs(registered)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_optional_provider_observation_preserves_blob_coordination(provider):
    cloud, _, durable, state, _, _, _, _ = ancestor_cloud(provider)
    cloud.document["locks"]["coordination_mode"] = "blob-lease"
    prior = copy.deepcopy(cloud.document)
    durable.set_state(state)
    store = native.ps.ProviderState(cloud, cloud.document["route"], ValueError)
    assert store.read()[1] == state
    assert cloud.document == prior


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_ancestor_chain_validates_every_link_without_trusting_origin_hints(provider):
    helper = importlib.import_module("pipeline_ancestor_runs")
    core = importlib.import_module("pipeline_lifecycle")
    shared = importlib.import_module("lifecycle_admission")
    cloud, _, durable, state, parent, _, _, _ = ancestor_cloud(provider)
    middle = copy.deepcopy(parent)
    middle["operation_id"] = str(uuid4())
    middle["plan"]["origin"]["run_id"] = "77"
    middle["plan"]["continuation_of"] = {"operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"]}
    middle["plan_hash"] = core.digest(core.bound_plan(middle))
    middle["finalization"]["proof"].update(operation_id=middle["operation_id"], plan_hash=middle["plan_hash"], run_id="77")
    middle["admission_claim"].update(id=str(uuid4()), operation_id=middle["operation_id"], review_digest=middle["plan_hash"])
    middle["admission_claim"]["identity"]["run_id"] = "77"
    parent["provider_continuation"]["run_id"] = "77"
    parent["continuation_child"] = middle["operation_id"]
    state["records"][f"pipeline-lifecycle/{middle['operation_id']}.json"] = middle
    observation = copy.deepcopy(state["records"][shared.RECORD]["history"][parent["admission_claim"]["id"]]["observation"])
    observation["run_id"] = "77"
    state["records"][shared.RECORD]["history"][middle["admission_claim"]["id"]] = {
        "claim": middle["admission_claim"], "observation": observation}
    durable.set_state(state)
    visited = []

    def request(kind, method, path, body, allowed):
        visited.append(path)
        if "/77" not in path:
            return cloud.state_request(kind, method, path, body, allowed)
        status, headers, data = cloud.state_request(kind, method, path.replace("/77", "/42"), body, allowed)
        data = copy.deepcopy(data)
        if data.get("id") == 42:
            data["id"] = 77
        for job in data.get("jobs", []):
            job["run_id"] = 77
            job["name"] = job["name"].replace(parent["operation_id"], middle["operation_id"]).replace(
                parent["plan_hash"], middle["plan_hash"])
        return status, headers, data

    assert helper.quiescent_ancestors(cloud.origin, state=state, request=request) == {"42", "77"}
    assert any("/42" in path for path in visited) and any("/77" in path for path in visited)
    parent["continuation_child"] = str(uuid4())
    with pytest.raises(ValueError, match="continuation-binding"):
        helper.quiescent_ancestors(cloud.origin, state=state, request=request)
    cloud.origin["ancestor_runs"] = ["42", "77"]
    assert helper.quiescent_ancestors(cloud.origin, state={**state, "records": {}}, request=request) == set()


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("change", ["truncated", "provider-pagination", "wrong-definition", "wrong-execution-id",
                                    "wrong-finalizer-id", "failed-workflow", "cancelled-workflow"])
def test_finalized_run_requires_complete_fresh_provider_evidence(provider, change):
    helper = importlib.import_module("pipeline_ancestor_runs")
    cloud, _, durable, state, parent, run, _, _ = ancestor_cloud(provider)
    if change == "wrong-execution-id":
        parent["finalization"]["proof"]["execution_job_id"] = "unrelated"
    if change == "wrong-finalizer-id":
        parent["finalization"]["proof"]["job_id"] = "unrelated"
    if change in ("failed-workflow", "cancelled-workflow"):
        run["status"] = "completed"
        run["conclusion" if provider == "gha" else "result"] = (
            "failure" if provider == "gha" else "failed") if change == "failed-workflow" else (
                "cancelled" if provider == "gha" else "canceled")
    durable.set_state(state)

    def request(kind, method, path, body, allowed):
        status, headers, data = cloud.state_request(kind, method, path, body, allowed)
        data = copy.deepcopy(data)
        if change == "truncated":
            if "jobs" in data:
                data["total_count"] += 1
            if "records" in data:
                data["records"].pop()
        if change == "provider-pagination":
            headers = {"Link": 'rel="next"'} if provider == "gha" else {"X-MS-ContinuationToken": "more"}
        if change == "wrong-definition":
            if provider == "gha":
                data["path"] = "other.yml"
            elif "process" in data:
                data["process"]["yamlFilename"] = "other.yml"
        return status, headers, data

    with pytest.raises(ValueError):
        helper.assert_finalized_run(parent, state=state, request=request)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_successful_terminal_ancestor_supported_by_shared_finalizer_predicate(provider):
    helper = importlib.import_module("pipeline_ancestor_runs")
    cloud, _, durable, state, parent, run, jobs, _ = ancestor_cloud(provider)
    run["status"] = "completed"
    run["conclusion" if provider == "gha" else "result"] = "success" if provider == "gha" else "succeeded"
    for row in jobs:
        row["status" if provider == "gha" else "state"] = "completed"
        row["conclusion" if provider == "gha" else "result"] = "success" if provider == "gha" else "succeeded"
    durable.set_state(state)
    assert helper.assert_finalized_run(parent, state=state, request=cloud.state_request)["status"] == "completed"


def bound_cloud():
    module = importlib.import_module("pipeline_lifecycle_cloud")
    document = manifest()
    document["locks"]["coordination_mode"] = "single-writer"
    document["route"].update(kind="gha", repository="https://github.com/org/repo")
    registered = enrollment()
    registered["writers"]["writer-a"].update(kind="gha", repository="https://github.com/org/repo")
    origin = {"provider": "gha", "repository": "org/repo", "run_id": "42", "attempt": 1, "commit": "b" * 40,
              "ref": "refs/heads/main"}
    cloud = module.PipelineCloud(document, origin, opener=Mock())
    return cloud, registered


def test_only_authenticated_parent_run_is_excluded_from_active_run_inventory():
    cloud, registered = bound_cloud()
    parent = {"id": 42, "run_attempt": 1, "head_sha": "b" * 40,
              "repository": {"full_name": "org/repo"}, "status": "in_progress"}
    cloud.state_request = Mock(return_value=(200, {}, {"total_count": 1, "workflow_runs": [parent]}))
    cloud.assert_no_active_runs(registered)
    assert cloud.state_request.call_count == 5


@pytest.mark.parametrize("change", ["other-run", "other-commit", "rerun", "truncated"])
def test_parent_exclusion_never_hides_another_writer(change):
    cloud, registered = bound_cloud()
    parent = {"id": 42, "run_attempt": 1, "head_sha": "b" * 40,
              "repository": {"full_name": "org/repo"}, "status": "in_progress"}
    page = {"total_count": 1, "workflow_runs": [parent]}
    if change == "other-run":
        parent["id"] = 43
    elif change == "other-commit":
        parent["head_sha"] = "c" * 40
    elif change == "rerun":
        parent["run_attempt"] = 2
    else:
        page["total_count"] = 2
    cloud.state_request = Mock(return_value=(200, {}, page))
    with pytest.raises(ValueError):
        cloud.assert_no_active_runs(registered)


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("transport", ["lifecycle", "enrollment"])
def test_provider_token_transport_never_changes_arm_identity(provider, transport, monkeypatch, capsys):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    document = manifest()
    document["locks"]["coordination_mode"] = "single-writer"
    repository = "https://github.com/org/repo" if provider == "gha" else "https://dev.azure.com/org/project/_git/repo"
    document["route"].update(kind=provider, repository=repository)
    origin = {"provider": provider, "repository": "org/repo" if provider == "gha" else repository,
              "run_id": "42", "attempt": 1, "commit": "b" * 40, "ref": "refs/heads/main"}
    token = "seeded-provider-only-token"
    monkeypatch.setenv("GH_TOKEN" if provider == "gha" else "AIFACTORY_STATE_TOKEN", token)
    commands, outgoing = [], []

    def command(*args, **kwargs):
        commands.append(args)
        raise AssertionError("Provider access must not mint another Azure token or call gh")

    def open_request(request, **kwargs):
        outgoing.append(request)
        return native.te.Response(200, {"ok": True})

    if transport == "lifecycle":
        cloud = module.PipelineCloud(document, origin, command_runner=command,
                                     opener=SimpleNamespace(open=open_request))
        assert cloud.expected_object_id == document["identity"]["object_id"]
        assert cloud.pipeline_identity is False
    else:
        request = {"route": document["route"], "coordination_mode": "single-writer"}
        cloud = module.PipelineEnrollmentCloud(request, origin, command_runner=command,
                                               opener=SimpleNamespace(open=open_request))
        assert cloud.operator_id is None
    endpoint = "repos/org/repo" if provider == "gha" else repository.split("/_git/")[0] + "/_apis/git/repositories/repo"
    assert cloud.state_request(provider, "GET", endpoint, None, (200,))[2] == {"ok": True}
    assert outgoing[0].get_header("Authorization") == "Bearer " + token
    assert not commands and not cloud.tokens
    assert token not in repr(cloud)
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.parametrize("token", ["", "bad\nsecret", "$(AIFACTORY_STATE_TOKEN)"])
def test_pipeline_provider_token_failure_is_explicit_and_never_falls_back(token, monkeypatch, capsys):
    cloud, _ = bound_cloud()
    monkeypatch.setenv("GH_TOKEN", token)
    cloud.command = Mock(side_effect=AssertionError("No CLI fallback"))
    with pytest.raises(ValueError, match="provider-token"):
        cloud.state_request("gha", "GET", "repos/org/repo", None, (200,))
    cloud.opener.open.assert_not_called()
    cloud.command.assert_not_called()
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.parametrize("endpoint", ["https://evil.test/repo", "//evil.test/repo", "repos/other/repo",
                                     "repos/org/repo/../other", "repos/org/repo?secret=bad%0A"])
def test_provider_token_cannot_escape_repository(endpoint, monkeypatch):
    cloud, _ = bound_cloud()
    monkeypatch.setenv("GH_TOKEN", "provider-token")
    with pytest.raises(ValueError):
        cloud.state_request("gha", "GET", endpoint, None, (200,))
    cloud.opener.open.assert_not_called()


def test_provider_failure_never_prints_secret_response_or_exception(monkeypatch, capsys):
    cloud, _ = bound_cloud()
    monkeypatch.setenv("GH_TOKEN", "seeded-provider-secret")
    cloud.opener.open.side_effect = URLError("seeded-provider-secret")
    with pytest.raises(ValueError) as error:
        cloud.state_request("gha", "POST", "repos/org/repo/git/blobs", {}, (201,))
    assert "seeded-provider-secret" not in str(error.value)
    assert cloud.opener.open.call_count == 1
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.parametrize("change", ["none", "other-run", "other-commit", "other-ref", "other-repository", "truncated"])
def test_ado_active_inventory_excludes_only_exact_authenticated_run(change):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    document = manifest()
    repository = "https://dev.azure.com/org/project/_git/repo"
    document["route"].update(kind="ado", repository=repository)
    registered = enrollment()
    registered["writers"]["writer-a"].update(kind="ado", repository=repository)
    origin = {"provider": "ado", "repository": repository, "run_id": "42", "attempt": 1,
              "commit": "b" * 40, "ref": "refs/heads/main"}
    cloud = module.PipelineCloud(document, origin, opener=Mock())
    run = {"id": 42, "sourceVersion": "b" * 40, "sourceBranch": "refs/heads/main",
           "repository": {"id": native.te.PROJECT}}
    page = {"count": 1, "value": [run]}
    if change == "other-run":
        run["id"] = 43
    elif change == "other-commit":
        run["sourceVersion"] = "c" * 40
    elif change == "other-ref":
        run["sourceBranch"] = "refs/heads/other"
    elif change == "other-repository":
        run["repository"]["id"] = native.te.FACTORY
    elif change == "truncated":
        page["count"] = 2
    cloud.state_request = Mock(side_effect=[(200, {}, {"id": native.te.PROJECT}), (200, {}, page)])
    if change == "none":
        cloud.assert_no_active_runs(registered)
    else:
        with pytest.raises(ValueError):
            cloud.assert_no_active_runs(registered)


@pytest.mark.parametrize("endpoint", [
    "http://dev.azure.com/org/project/_apis/git/repositories/repo",
    "https://dev.azure.com.evil.test/org/project/_apis/git/repositories/repo",
    "https://dev.azure.com/other/project/_apis/git/repositories/repo",
    "https://dev.azure.com/org/../other/_apis/git/repositories/repo",
    "https://user:password@dev.azure.com/org/project/_apis/git/repositories/repo",
])
def test_ado_token_cannot_escape_authenticated_organization(endpoint):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    request = {"coordination_mode": "single-writer",
               "route": {"kind": "ado", "repository": "https://dev.azure.com/org/project/_git/repo"}}
    cloud = module.PipelineEnrollmentCloud(
        request, opener=Mock(), environ={"AIFACTORY_STATE_TOKEN": "provider-secret"})
    with pytest.raises(ValueError):
        cloud.state_request("ado", "GET", endpoint, None, (200,))
    cloud.opener.open.assert_not_called()


def test_original_native_provider_auth_defaults_are_not_changed(monkeypatch):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    monkeypatch.setenv("AIFACTORY_STATE_TOKEN", "seeded-not-for-native-default")
    document = manifest()
    document["locks"]["coordination_mode"] = "single-writer"
    document["route"]["kind"] = "ado"
    response = native.te.Response(200, {})
    response.code = 200
    opener = SimpleNamespace(open=Mock(return_value=response))
    cloud = module.fl.Cloud(document, opener=opener)
    cloud.token = Mock(return_value="original-native-token")
    cloud.state_request("ado", "GET", "https://dev.azure.com/org/project/_apis/git/repositories/repo",
                        None, (200,))
    cloud.token.assert_called_once_with(native.en.ADO_AUDIENCE)
    assert opener.open.call_args.args[0].get_header("Authorization") == "Bearer original-native-token"
    request = {"coordination_mode": "single-writer", "ado_tenant_id": native.te.ADO_TENANT}
    original = module.en.Cloud(request, opener=Mock())
    original.http = Mock(return_value=(200, {}, {}))
    original.state_request("ado", "GET", "https://dev.azure.com/org/project", None, (200,))
    assert original.http.call_args.args[2] == native.en.ADO_AUDIENCE
    assert original.http.call_args.kwargs["tenant"] == native.te.ADO_TENANT


@pytest.mark.parametrize("audience", [native.en.ADO_AUDIENCE, "https://app.vssps.visualstudio.com/"])
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
def test_native_ado_request_uses_provider_token_without_cli_auth(audience, method):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    document = manifest()
    document["route"].update(kind="ado", repository="https://dev.azure.com/org/project/_git/repo")
    outgoing = []

    def open_request(request, **kwargs):
        outgoing.append(request)
        return native.te.Response(200, {"id": 43})

    cloud = module.PipelineCloud(document, None, opener=SimpleNamespace(open=open_request),
                                 environ={"AIFACTORY_STATE_TOKEN": "seeded-provider-token"})
    cloud.token = Mock(side_effect=AssertionError("Must not use ARM/login actor for ADO"))
    payload = {"status": "cancelling"} if method == "PATCH" else {"resources": {}} if method == "POST" else None
    result = cloud.request(method, "https://dev.azure.com/org/project/_apis/build/builds/43?api-version=7.1",
                           audience, data=payload, headers={"x-test": "preserved"}, allowed=(200,))
    assert result[2] == {"id": 43}
    assert outgoing[0].get_header("Authorization") == "Bearer seeded-provider-token"
    assert outgoing[0].get_header("X-test") == "preserved"
    assert outgoing[0].data == (module.canonical(payload) if payload is not None else None)
    cloud.token.assert_not_called()
    assert cloud.expected_object_id == document["identity"]["object_id"] and not cloud.pipeline_identity


def test_pipeline_request_still_uses_original_arm_transport(monkeypatch):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    cloud, _ = bound_cloud()
    original = Mock(return_value=(200, {}, {"operator": "unchanged"}))
    monkeypatch.setattr(module.fl.Cloud, "request", original)
    endpoint = module.fl.ARM + "/subscriptions/example?api-version=2022-12-01"
    assert cloud.request("GET", endpoint, module.fl.ARM) == (200, {}, {"operator": "unchanged"})
    original.assert_called_once_with("GET", endpoint, module.fl.ARM, None, None, (200,))


def test_actual_native_ado_scoped_dispatch_and_poll_use_seeded_token(capsys):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    document, _ = native.tl.scoped_manifest()
    document["locks"]["coordination_mode"] = "single-writer"
    native.tl.seal(document)
    origin = {"provider": "ado", "repository": document["route"]["repository"], "run_id": "42", "attempt": 1,
              "commit": document["route"]["commit"], "ref": document["route"]["ref"]}
    template = (ROOT / "bootstrap" / "templates" / "factory-lifecycle-ado.yml").read_text().strip()
    calls = []

    def open_request(request, **kwargs):
        method, url = request.get_method(), request.full_url
        assert request.get_header("Authorization") == "Bearer seeded-dispatch-token"
        body = json.loads(request.data) if request.data else None
        calls.append((method, url, body))
        if "/serviceendpoint/endpoints?" in url:
            result = {"value": [{"name": document["route"]["auth_namespace"],
                                 "authorization": {"scheme": "WorkloadIdentityFederation",
                                                   "parameters": {"tenantid": document["target"]["tenant_id"]}},
                                 "data": {"subscriptionId": document["target"]["subscription_id"]}}]}
        elif "/items?" in url:
            result = {"content": template}
        elif "/build/definitions?" in url:
            result = {"value": [{"id": 7, "repository": {"name": "consumer"},
                                 "process": {"yamlFilename": module.fl.SCOPED_ADO}}]}
        elif "/git/repositories/" in url:
            result = {"id": native.te.PROJECT}
        elif "/build/builds?" in url:
            result = {"count": 1, "value": [{"id": 42, "sourceVersion": origin["commit"],
                       "sourceBranch": origin["ref"], "repository": {"id": native.te.PROJECT}}]}
        elif method == "POST":
            result = {"id": 43}
        else:
            assert "/pipelines/7/runs/43?" in url
            result = {"state": "completed", "result": "succeeded",
                      "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}}
        return native.te.Response(200, result)

    cloud = module.PipelineCloud(document, origin, opener=SimpleNamespace(open=open_request),
                                 environ={"AIFACTORY_STATE_TOKEN": "seeded-dispatch-token"})
    cloud.token = Mock(side_effect=AssertionError("ADO dispatch must not mint another identity token"))
    cloud.command = Mock(return_value=template)
    locks = SimpleNamespace(held={"scope": "synthetic-lease"}, enrollment=native.tl.scoped_enrollment(document),
                            assert_held=Mock(), authorize=Mock(),
                            request=Mock(return_value=(200, {}, native.tl.successful_worker_receipt(document))))
    receipt, saved = {}, []
    module.fl.ado_scoped(cloud, locks, document, ROOT, receipt,
                         lambda: saved.append(copy.deepcopy(receipt)), sleep=Mock())
    assert receipt["remote_run"] == {"kind": "ado", "pipeline_id": 7, "run_id": 43}
    assert receipt["remote_terminal"] and receipt["worker_receipt"]["status"] == "succeeded"
    payload = next(body for method, _, body in calls if method == "POST")
    assert payload["resources"]["repositories"]["self"]["version"] == document["route"]["commit"]
    assert payload["variables"]["AIFACTORY_ENVELOPE_JSON"]["isSecret"] is True
    cloud.token.assert_not_called()
    assert all(call.args[0][:2] == ["git", "show"] for call in cloud.command.call_args_list)
    assert "seeded-dispatch-token" not in json.dumps(saved)
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
