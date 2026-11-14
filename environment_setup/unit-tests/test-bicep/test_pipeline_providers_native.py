"""Provider integration through real transports, approval, CAS and admission.

Only provider HTTP/OIDC responses and native workload effects are faked. This
proves provider orchestration, not Azure deployment or six-scenario acceptance.
"""
import copy
import io
import json
import re
import socket
import subprocess
from types import SimpleNamespace
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest

import test_pipeline_approvals as native_review
from test_pipeline_providers_export import export_state
from unit.test_single_writer_coordination import Provider, te
import lifecycle_admission as shared
import pipeline_approvals as approvals
import pipeline_credentials as credentials
import pipeline_dispatch as dispatch
import pipeline_inputs as inputs
import pipeline_lifecycle as lifecycle
from pipeline_lifecycle_adapters import RepositoryJournal
from pipeline_lifecycle_admission import NativeAdmission
from pipeline_lifecycle_cloud import PipelineEnrollmentCloud
import pipeline_observer as observer
import pipeline_provider as provider
from provider_repository_state import ProviderState


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live provider call forbidden"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("Live command forbidden"))
    monkeypatch.setattr(lifecycle, "now", lambda: native_review.stamp(native_review.NOW - 120))


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class ProviderHTTP:
    def __init__(self, kind, repository):
        self.kind, self.repository = kind, repository
        self.durable = Provider(repository)
        self.runs, self.contexts, self.calls = {}, {}, []
        self.parameters = {}
        self.receipts = {}

    def install_jobs(self, record, key, *, finalizing=False):
        run_id = record["plan"]["provider_context"]["run_id"]
        if finalizing:
            traffic, environment, oidc = native_review.finalizer(self.kind, key)
        else:
            traffic = native_review.Provider(self.kind)
            environment, oidc = native_review.environ(self.kind), native_review.OIDC(key)
        traffic.run.update(id=run_id)
        if self.kind == "gha":
            traffic.run.update(workflow_id=9, head_branch="main", conclusion=None,
                               display_title=f"pipelines-only [{self.parameters[run_id]['correlation_id']}]")
            for row in traffic.jobs:
                row["run_id"] = run_id
                row["name"] = row["name"].replace(native_review.OPERATION, record["operation_id"]).replace(
                    native_review.HASH, record["plan_hash"])
            if finalizing:
                traffic.jobs.append({"id": 43, "name": "complete", "run_id": run_id, "run_attempt": 1,
                                     "head_sha": native_review.COMMIT, "status": "queued", "conclusion": None,
                                     "labels": ["ubuntu-latest"]})
            environment["GITHUB_RUN_ID"] = str(run_id)
        else:
            traffic.run["result"] = None
            traffic.definition["repository"]["url"] = self.repository
            for row in traffic.records:
                row["name"] = row["name"].replace(native_review.OPERATION, record["operation_id"]).replace(
                    native_review.HASH, record["plan_hash"])
                if row["type"] == "Stage":
                    row.update(state="completed", result="succeeded")
            if finalizing:
                traffic.records.extend([
                    {"id": "complete-stage", "name": "Complete", "type": "Stage", "attempt": 1,
                     "state": "inProgress", "result": None},
                    {"id": "complete-job", "name": "ObserveScenarioCompletion", "type": "Job",
                     "identifier": "ObserveScenarioCompletion", "parentId": "complete-stage", "attempt": 1,
                     "state": "inProgress", "result": None},
                ])
            environment["BUILD_BUILDID"] = str(run_id)
        oidc.claims.update(run_id=str(run_id))
        def signed(audience):
            claims = dict(oidc.claims, aud=audience)
            data = (native_review.encode(json.dumps(oidc.header).encode()) + "." +
                    native_review.encode(json.dumps(claims).encode())).encode()
            return data.decode() + "." + native_review.encode(
                key.sign(data, padding.PKCS1v15(), hashes.SHA256()))
        oidc.token = signed
        self.runs[run_id], self.contexts[run_id] = traffic, (environment, oidc)

    def finish_finalizer(self, run_id):
        traffic = self.runs[run_id]
        if self.kind == "gha":
            traffic.jobs[-2].update(status="completed", conclusion="success",
                                    completed_at=native_review.stamp(native_review.NOW - 1))
            traffic.jobs[-1]["status"] = "in_progress"
        else:
            traffic.records[-3].update(state="completed", result="succeeded",
                                       finishTime=native_review.stamp(native_review.NOW - 1))

    def open(self, request, **_):
        assert request.get_header("Authorization") == "Bearer offline-scoped-provider-token"
        url, method = request.full_url, request.get_method()
        assert url.startswith(("https://api.github.com/repos/acme/factory", "https://dev.azure.com/acme"))
        body = json.loads(request.data) if request.data else None
        self.calls.append((method, url))
        status, headers, value = self.response(method, url, body)
        return te.Response(status, value, headers)

    def response(self, method, url, body):
        artifact = re.search(r"/(?:actions/artifacts|build/builds)/([0-9]+)/(?:zip|artifacts)", url)
        if artifact and ("/zip" in url or "artifactName=" in url):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("receipt.json", json.dumps(self.receipts[int(artifact[1])]))
            return 200, {}, output.getvalue()
        artifact = re.search(r"/(?:actions/runs|build/builds)/([0-9]+)/artifacts", url)
        if artifact:
            run_id = int(artifact[1])
            row = {"id": run_id, "name": f"esaf-receipt-{self.parameters[run_id]['correlation_id']}-1",
                   "expired": False}
            return 200, {}, {"artifacts" if self.kind == "gha" else "value": [row]}
        if "/dispatches" in url or "/pipelines/9/runs?" in url:
            assert method == "POST"
            run_id = 7 + len(self.parameters)
            self.parameters[run_id] = body["inputs"] if self.kind == "gha" else body["templateParameters"]
            return (204, {}, None) if self.kind == "gha" else (200, {}, self.pipeline_run(run_id))
        if "/actions/workflows/" in url and "/runs?" in url:
            return 200, {}, {"workflow_runs": [self.queued_run(run_id) for run_id in self.parameters]}
        if "/actions/workflows/" in url:
            return 200, {}, {"id": 9, "path": dispatch.GHA_WORKFLOW, "state": "active"}
        if "/commits/refs" in url or "/commits/refs%2F" in url:
            return 200, {}, {"sha": native_review.COMMIT}
        if "/build/definitions/9" in url:
            return 200, {}, {"id": 9, "revision": 2, "repository": {
                "id": native_review.REPOSITORY, "url": self.repository},
                "process": {"yamlFilename": dispatch.ADO_WORKFLOW}}
        if "/actions/runs?" in url:
            runs = [row.run for row in self.runs.values()] if "status=in_progress" in url else []
            return 200, {}, {"total_count": len(runs), "workflow_runs": runs}
        if "/build/builds?" in url:
            runs = [row.run for row in self.runs.values()]
            return 200, {}, {"count": len(runs), "value": runs}
        match = re.search(r"/(?:actions/runs|build/builds)/([0-9]+)(?:[/?]|$)", url)
        if match:
            traffic = self.runs[int(match[1])]
            status, headers, value = traffic.request(method, url, body)
            if "/jobs?" in url:
                value["total_count"] = len(value["jobs"])
            return status, headers, value
        if "/contents/" in url or "/distributedtask/tasks/" in url or (
                "/items?" in url and "pipelines-only-ado.yml" in url):
            traffic = next(iter(self.runs.values()))
            return traffic.request(method, url, body)
        if "/environments/" in url:
            return next(iter(self.runs.values())).request(method, url, body)
        path = url.removeprefix("https://api.github.com/")
        status, headers, value = self.durable.call(self.kind, method, path, body, (200, 201, 404))
        if self.kind == "ado" and "/git/repositories/factory?" in url:
            value["id"] = native_review.REPOSITORY
        return status, headers, value

    def queued_run(self, run_id):
        return {"id": run_id, "workflow_id": 9, "event": "workflow_dispatch", "run_attempt": 1,
                "head_sha": native_review.COMMIT, "repository": {"full_name": "acme/factory"},
                "display_title": f"pipelines-only [{self.parameters[run_id]['correlation_id']}]"}

    def pipeline_run(self, run_id):
        return {"id": run_id, "pipeline": {"id": 9},
                "resources": {"repositories": {"self": {"version": native_review.COMMIT}}},
                "templateParameters": self.parameters[run_id]}


@pytest.mark.parametrize("kind", ["gha", "ado"])
@pytest.mark.parametrize("outcome_mode", [
    "completed", "unapproved-child", "failed-child", "partial-child", "cancelled-child",
    "missing-finalizer-evidence", "failed-after-finalizer",
])
def test_native_provider_chain_dispatch_review_admission_and_final_receipt(kind, outcome_mode, signing_key, monkeypatch):
    canonical, binding, _, document = export_state(kind)
    original = inputs.resolve_document(document, {**canonical["request"], "scenario": 3}, operational=binding)
    repository = binding["repository"]
    http = ProviderHTTP(kind, repository)
    monkeypatch.setattr(dispatch, "build_opener", lambda *_: http)
    base = dispatch.validate_binding(original, binding)
    transport = dispatch.ProviderTransport(kind, base, opener=http)
    review_transport = dispatch.ProviderTransport(
        kind, "https://dev.azure.com/acme" if kind == "ado" else base, opener=http)
    child_env = credentials.provider_environment(kind, environ={"ESAF_PROVIDER_TOKEN": "offline-scoped-provider-token"})
    for name, value in child_env.items():
        monkeypatch.setenv(name, value)
    route = {"kind": kind, "repository": repository, "ref": "refs/heads/main"}
    factory_id, scale_id = original["factory"]["id"], original["scales"][0]["id"]
    scopes = document["factories"][0]["scale_sets"][0]["owned_resource_ids"]
    outer = shared.new_record({"repository": repository, "factories": {factory_id: {
        "all_writers": shared.PROTOCOL, "shared_scopes": [], "operations": sorted(shared.OPERATIONS),
        "routes": ["api", "pipeline"], "scopes": scopes}}}, {factory_id: document})
    http.durable.set_state({"schema": 1, "repository": repository, "enrollment": None,
                            "active": None, "records": {shared.RECORD: outer, "unrelated": {"preserved": True}}})
    current = {"request_path": "request.json", "request_digest": dispatch.digest(original),
               "consumer_commit": binding["consumer_commit"], "source_commit": original["source"]["commit"],
               "correlation_id": "e" * 32, "provider": kind, "repository": repository,
               "run_id": 7, "run_attempt": 1, "scenario": 3}
    def origin():
        return {"provider": kind, "repository": "acme/factory" if kind == "gha" else repository,
                "run_id": str(current["run_id"]), "attempt": 1, "commit": binding["consumer_commit"],
                "ref": "refs/heads/main"}
    cloud = PipelineEnrollmentCloud({"route": route, "coordination_mode": "single-writer"},
                                    origin(), opener=http, environ=child_env)
    cloud.read_only = False
    state = ProviderState(cloud, route, lifecycle.PipelineError)
    reader = dispatch.ProviderReceiptReader(current, transport=transport)

    class Review:
        def origin(self, _):
            return origin()

        def verify(self, record):
            environment, oidc = http.contexts[current["run_id"]]
            return approvals.verify_review(record, transport=review_transport, environ=environment,
                                           oidc=oidc, clock=lambda: native_review.NOW)

        def verify_finalizer(self, record):
            environment, oidc = http.contexts[current["run_id"]]
            return approvals.verify_finalizer(record, transport=review_transport, environ=environment,
                                              oidc=oidc, clock=lambda: native_review.NOW)

        def get(self, path):
            url = "https://api.github.com/" + path if kind == "gha" else path
            return transport.request("GET", url)[2]

    effects = []
    def outcome(stage, record):
        partial = record["plan"]["provider_context"]["run_id"] == 7
        return {"verified": True, "status": "continuation-required" if partial else "succeeded",
                "runtime_ready": not partial, "continuation": {"requires_fresh_review": True},
                "children": [{"worker": {"status": "succeeded", "run_id": record["operation_id"],
                             "target": {"factory_id": factory_id, "scaleset_id": scale_id},
                             "resource_groups": [], "ownership": []}, "native": {}}]}
    def execute(stage, record):
        cloud.assert_no_active_runs()
        effects.append(record["operation_id"])
        if current["run_id"] == 8 and outcome_mode in ("failed-child", "partial-child", "cancelled-child"):
            return {"verified": False, "status": "reconciliation-required"}
        return outcome(stage, record)
    executor = SimpleNamespace(execute=execute, observe=outcome)
    review = Review()
    admission = NativeAdmission(state, review, executor)
    def prepare(snapshot, operation_id, **_):
        cloud.origin = origin()
        cloud.assert_no_active_runs()
        return {"origin": origin(), "provider_context": copy.deepcopy(current),
                "stages": [{"id": "native-work", "kind": "lifecycle", "manifests": [{
                    "run_id": operation_id, "locks": {"scopes": scopes, "common_dependencies": []}}]}]}
    engine = lifecycle.LifecycleService(store=RepositoryJournal(state), planner=SimpleNamespace(prepare=prepare),
                                        executor=executor, review=review, admission=admission, configuration=admission)
    parameters = {key: current[key] for key in ("request_path", "request_digest", "consumer_commit",
                                               "source_commit", "correlation_id")}
    if kind == "ado":
        binding["pipeline_id"] = 9
    assert dispatch.dispatch_run(parameters, original, binding, transport=transport, max_polls=1)[0] == 7
    parent = engine.prepare(original)
    http.install_jobs(parent, signing_key)
    executed = engine.execute(parent["operation_id"], original, parent["plan_hash"])
    assert executed["status"] == "continuation-required"
    assert executed["admission"]["status"] == "provider-completion-pending"
    assert http.durable.state()["records"][shared.RECORD]["claim"] is not None
    http.install_jobs(parent, signing_key, finalizing=True)
    parent = engine.finalize(parent["operation_id"], original, parent["plan_hash"])
    assert http.durable.state()["records"][shared.RECORD]["claim"] is None
    scheduled = provider.schedule_continuation(
        engine, parent["operation_id"], parent["plan_hash"], current, binding, canonical=original,
        verify=review.verify_finalizer,
        launch=lambda args, canonical, selected: dispatch.dispatch_run(
            args, canonical, selected, transport=transport, max_polls=1))
    assert type(scheduled["run_id"]) is int and scheduled["run_id"] == 8
    http.receipts[7] = {"operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"],
                        "status": "continuation-required", "provider_context": copy.deepcopy(current),
                        "provider_continuation": scheduled}
    http.finish_finalizer(7)
    parent_context = copy.deepcopy(current)
    current.update(run_id=8, correlation_id=scheduled["correlation_id"])
    provider.wait_for_predecessor(parent["operation_id"], parent["plan_hash"], current,
                                  reader=reader, transport=transport, max_polls=1,
                                  sleep=lambda _: pytest.fail("Must not wait for parent Complete"))
    child = engine.prepare_continuation(parent["operation_id"], original, parent["plan_hash"])
    http.install_jobs(child, signing_key)
    assert child["operation_id"] != parent["operation_id"]
    assert engine.status(parent["operation_id"])["status"] == "continuation-required"
    if outcome_mode == "unapproved-child":
        if kind == "gha":
            http.runs[8].reviews[0]["state"] = "rejected"
        else:
            http.runs[8].records[4]["result"] = "failed"
        with pytest.raises(approvals.ApprovalError):
            engine.execute(child["operation_id"], original, child["plan_hash"])
        assert effects == [parent["operation_id"]]
        assert http.durable.state()["records"][shared.RECORD]["claim"] is None
    else:
        result = engine.execute(child["operation_id"], original, child["plan_hash"])
        assert result["status"] == ("reconciliation-required" if outcome_mode in (
            "failed-child", "partial-child", "cancelled-child") else "succeeded")
    if outcome_mode in ("failed-child", "partial-child", "cancelled-child"):
        assert http.durable.state()["records"][shared.RECORD]["claim"]["operation_id"] == child["operation_id"]
        http.runs[8].run.update(status="completed", conclusion={
            "failed-child": "failure", "partial-child": "neutral", "cancelled-child": "cancelled"}[outcome_mode],
            result={"failed-child": "failed", "partial-child": "partiallySucceeded",
                    "cancelled-child": "canceled"}[outcome_mode])
    if outcome_mode in ("unapproved-child", "failed-child", "partial-child",
                        "cancelled-child", "missing-finalizer-evidence"):
        assert engine.status(parent["operation_id"])["status"] == "continuation-required"
        before = len(http.calls)
        with pytest.raises(dispatch.DispatchError, match="scenario-provider-run-unsuccessful|completion-timeout"):
            observer.wait_for_completion(parent["operation_id"], parent["plan_hash"], parent_context,
                                         reader=reader, transport=transport, max_polls=1, sleep=lambda _: None)
        assert all(method == "GET" for method, _ in http.calls[before:])
        return
    http.install_jobs(child, signing_key, finalizing=True)
    finalized = engine.finalize(child["operation_id"], original, child["plan_hash"])
    http.receipts[8] = {"operation_id": child["operation_id"], "plan_hash": child["plan_hash"],
                        "status": finalized["status"], "provider_context": copy.deepcopy(current),
                        "continuation_of": child["plan"]["continuation_of"]}
    http.finish_finalizer(8)
    if outcome_mode == "failed-after-finalizer":
        http.runs[8].run.update(status="completed", conclusion="failure", result="failed")
        with pytest.raises(dispatch.DispatchError, match="scenario-provider-run-unsuccessful"):
            observer.wait_for_completion(parent["operation_id"], parent["plan_hash"], parent_context,
                                         reader=reader, transport=transport, max_polls=1, sleep=lambda _: None)
        return
    before = len(http.calls)
    receipt = observer.wait_for_completion(parent["operation_id"], parent["plan_hash"], parent_context,
                                           reader=reader, transport=transport, max_polls=1,
                                           sleep=lambda _: pytest.fail("Complete waiter deadlock"))
    assert receipt["outcome"] == "completed" and receipt["operation_id"] == parent["operation_id"]
    parent_artifact = dispatch._receipt(transport, base, kind, 7, parent_context["correlation_id"])
    pending = dispatch.verify_lifecycle_receipt(parent_artifact, parent_context)
    assert pending["outcome"] == "continuation-required" and pending["continuation"]["run_id"] == 8
    child_artifact = dispatch._receipt(transport, base, kind, 8, current["correlation_id"])
    completed = dispatch.verify_lifecycle_receipt(child_artifact, current)
    assert completed["outcome"] == "completed" and completed["continuation_of"] == {
        "operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"]}
    assert dispatch.verify_lifecycle_receipt(dict(parent_artifact, status="succeeded"), parent_context)[
        "outcome"] == "completed"
    assert all(method == "GET" for method, _ in http.calls[before:])
    saved = http.durable.state()
    assert saved["records"]["unrelated"] == {"preserved": True}
    assert saved["records"][shared.RECORD]["claim"] is None
    assert len(saved["records"][shared.RECORD]["history"]) == 2
    assert effects == [parent["operation_id"], child["operation_id"]], "No completed workload replay"
    for operation in (parent, child):
        proof = engine.status(operation["operation_id"])["approval"]
        assert proof["plan_hash"] == operation["plan_hash"] and proof["operation_id"] == operation["operation_id"]
    assert len([url for method, url in http.calls if method == "POST" and (
        "/dispatches" in url or "/pipelines/9/runs?" in url)]) == 2
