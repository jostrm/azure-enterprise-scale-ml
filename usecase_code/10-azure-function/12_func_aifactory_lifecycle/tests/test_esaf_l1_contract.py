"""Function -> real L1 SDK -> ephemeral HTTP fake of L2; no Azure, GitHub or live API calls."""

import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from azurefactory import client as sdk_client
from aif_lifecycle import composition, runner
from aif_lifecycle.adapters.factory_api import job_observation
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.application.runner_protocol import decode_request
from aif_lifecycle.domain.errors import InvalidState
from aif_lifecycle.http_api import ApiRequest
from aif_lifecycle.signatures import sign
from fake_factory_api import CATALOG, FACTORY_ID, FakeFactoryApi
from support import FakeGitHub, confirm_current

FOLDER = r"C:\repos\consumer\azurefactory"
SECRET = b"offline-event-secret"
JOB_ID = "esaf-job-1"
PROJECT = "aif-121-esml-project001-sdc-dev-001-rg"
CASES = (
    ("init-factory", {"factoryId": "new-sdc-dev", "bootstrapConfig": {"subscription_id": "subscription"}},
     "init_factory", {"creation_request": {
         "contract_version": 1, "mode": "full-bootstrap", "folder": r"C:\repos\consumer", "orchestrator": "gha",
         "config": {"subscription_id": "subscription", "factory_prefix": "new-", "location": "swedencentral",
                    "scale_set_number": "001"}, "region_short_name": "sdc"}}),
    ("add-scaleset", {"scalesetId": "aif-121-sdc-dev-002", "scaleSet": {"vnetCidr": "10.20.0.0/16"}},
     "add_scale_set", {"scale_set": "002", "environment": "dev", "cidr": "10.20.0.0/16", "max_projects": 7}),
    ("add-or-update-project", {"projectId": PROJECT, "settings": {"enableAISearch": "true"}},
     "upsert_project", {"project": "001", "environment": "dev", "scale_set": "001",
                        "settings": {"enableAISearch": "true"}, "display_name": "Project 001"}),
    ("delete-project", {"projectId": PROJECT, "includeProjectSubnets": False},
     "delete_project", {"project": "001", "environment": "dev", "scale_set": "001",
                        "include_project_subnets": False, "include_keyvault_and_resource_group": True}),
    ("delete-scaleset", {"scalesetId": "aif-121-sdc-dev-001"},
     "delete_scale_set", {"scale_set": "001", "environment": "dev"}),
    ("delete-factory", {"factoryId": "aif-121-sdc-dev"}, "delete_factory", {}),
)


class EsafServer:
    def __init__(self):
        self.accepted = (202, {"contract_version": 1, "job_id": JOB_ID})
        self.state = {"job_id": JOB_ID, "status": "accepted"}

    def respond(self, method, path, body):
        if method == "GET" and path == "/api/v1/factory-catalog":
            return 200, CATALOG
        if method == "POST" and path in {"/api/v1/esaf/" + case[2].replace("_", "-") for case in CASES}:
            return self.accepted
        if method == "GET" and path == "/api/v1/esaf/jobs/" + JOB_ID:
            return 200, self.state
        return 404, {"detail": "No legacy orchestration endpoint in this fake"}


def runtime(http, clock, monkeypatch, executor, *, saved=None):
    store, github = MemoryStore(), FakeGitHub()
    if saved is not None:
        # Round-trip JSON records, not live adapters or SDK handles, just as a durable store would.
        for partition, key, value in json.loads(json.dumps([
            (p, k, v) for (p, k), (v, _) in saved._items.items()
        ])):
            store.insert(partition, key, value)
    monkeypatch.setattr(composition, "SystemClock", lambda: clock)
    monkeypatch.setattr(composition, "_store", lambda settings: store)
    monkeypatch.setattr(composition, "_github", lambda settings: github)
    env = {"AIF_BACKEND": "sdk", "AIF_EXECUTOR": executor, "AIF_STORE": "memory",
           "AIF_FACTORY_API_URL": http.url, "AIF_FACTORY_API_KEY": http.api_key, "AIF_FACTORY_FOLDER": FOLDER,
           "AIF_DELETES": "allow", "AIF_ALLOW_REAL_DELETES": "true", "AIF_POLL_AFTER_SECONDS": "15",
           "AIF_EVENT_SECRET": SECRET.decode(), "AIF_GITHUB_REPOSITORY": "offline/ops",
           "AIF_GITHUB_TOKEN": "offline-token"}
    built = composition.build_runtime(env)
    return SimpleNamespace(service=built.service, api=built.api, store=store, github=github, env=env,
                           executor=executor, clock=clock)


def finish(h):
    request = decode_request(h.github.dispatches[-1]["inputs"]["request"], [SECRET],
                             now=h.clock.now().timestamp())
    result = runner.execute(request, h.env, None)
    data = json.dumps(result).encode()
    response = h.api.runner_results(ApiRequest(
        "POST", "/api/v1/runner/results", headers={"x-hub-signature-256": sign(SECRET, data)}, body=data))
    assert response.status == 202
    return request, result


def prepare(h, slug, body):
    if h.executor == "github-runner":
        h.service.refresh_catalog()
        finish(h)
    response = h.api.prepare(ApiRequest(
        "POST", f"/api/v1/lifecycle/{slug}/prepare", route_params={"scenario": slug}, body=json.dumps(body).encode()))
    assert response.status == 202
    identifier = json.loads(response.body)["operationId"]
    if h.executor == "github-runner":
        finish(h)
    operation = h.service.get(identifier)
    assert operation.status.value == "awaiting_confirmation"
    return operation


def confirm(h, operation):
    operation = confirm_current(h.service, operation)
    if h.executor == "github-runner":
        finish(h)
    return h.service.get(operation.id)


def poll(h, identifier):
    h.clock.advance(15)
    h.service.reconcile()
    if h.executor == "github-runner":
        request, _ = finish(h)
        assert request.action == "status"
        assert request.job["job_kind"] == "esaf"
    return h.service.get(identifier)


@pytest.mark.parametrize("executor", ["inprocess", "github-runner"])
@pytest.mark.parametrize("slug,body,method,fields", CASES, ids=[case[0] for case in CASES])
def test_six_scenarios_submit_once_and_resume_durable_outer_status(clock, monkeypatch, executor,
                                                                 slug, body, method, fields):
    server = EsafServer()
    with FakeFactoryApi(responder=server.respond) as http:
        h = runtime(http, clock, monkeypatch, executor)
        operation = prepare(h, slug, body)
        assert operation.step.preview.backend_ref["method"] == method
        assert not [call for call in http.calls if call["method"] == "POST"]
        operation = confirm(h, operation)
        assert operation.status.value == "running"
        factory = None if method == "init_factory" else FACTORY_ID
        expected_job = {"kind": "esaf", "scenario": method, "job_kind": "esaf", "job_id": JOB_ID,
                        "factory_id": factory}
        assert operation.step.job == expected_job
        posts = [call for call in http.calls if call["method"] == "POST"]
        assert posts == [{"method": "POST", "path": "/api/v1/esaf/" + method.replace("_", "-"), "query": [],
                          "body": {"folder": FOLDER, "approved": True,
                                   **({"factory": factory} if factory else {}), **fields}, "key": True}]
        h = runtime(http, clock, monkeypatch, executor, saved=h.store)
        assert h.service.get(operation.id).step.job == expected_job
        for state in ("accepted", "preparing", "confirming", "running", "retrying"):
            server.state = {"job_id": JOB_ID, "status": state, "child": {"status": "failed"},
                            "message": "L2 owns retry decisions"}
            operation = poll(h, operation.id)
            assert operation.status.value == "running"
            assert operation.step.runs[0].status == ("queued" if state == "accepted" else "in_progress")
        server.state = {"job_id": JOB_ID, "status": "succeeded"}
        operation = poll(h, operation.id)
        assert operation.status.value == "succeeded"
        assert operation.step.job == expected_job
        with pytest.raises(InvalidState):
            confirm_current(h.service, operation)
        assert [call for call in http.calls if call["method"] == "POST"] == posts
        assert all(call["key"] for call in http.calls)
        reads = [call for call in http.calls if call["path"].startswith("/api/v1/esaf/jobs/")]
        assert [call["query"] for call in reads] == [[("folder", FOLDER)]] * 6


@pytest.mark.parametrize("executor", ["inprocess", "github-runner"])
@pytest.mark.parametrize("state", ["blocked", "failed", "interrupted"])
def test_terminal_outer_status_persists_server_diagnostics_after_restart(clock, monkeypatch, executor, state):
    server = EsafServer()
    with FakeFactoryApi(responder=server.respond) as http:
        h = runtime(http, clock, monkeypatch, executor)
        operation = confirm(h, prepare(h, CASES[2][0], CASES[2][1]))
        assert operation.status.value == "running"
        h = runtime(http, clock, monkeypatch, executor, saved=h.store)
        server.state = {"job_id": JOB_ID, "status": state, "message": "L2 stopped: scope review needs attention",
                        "child": {"status": "succeeded"}}
        operation = poll(h, operation.id)
        assert operation.status.value == "failed"
        assert "L2 stopped: scope review needs attention" in json.dumps(operation.step.failure)
        restarted = runtime(http, clock, monkeypatch, executor, saved=h.store)
        assert restarted.service.get(operation.id).step.failure == operation.step.failure
        assert len([call for call in http.calls if call["method"] == "POST"]) == 1


@pytest.mark.parametrize("executor", ["inprocess", "github-runner"])
@pytest.mark.parametrize("status,payload,expected", [
    (400, {"code": "config", "detail": "invalid environment"}, "failed"),
    (403, {"code": "auth", "detail": "not authorized"}, "failed"),
    (409, {"code": "blocked", "detail": "review refused"}, "failed"),
    (409, {"code": "conflict", "detail": "scope conflict"}, "failed"),
    (404, {"detail": "Not Found"}, "failed"),
    (405, {"detail": "Method Not Allowed"}, "failed"),
    (503, {"code": "storage-unavailable", "detail": "no durable receipt"}, "uncertain"),
    (500, {"code": "failure", "detail": "unexpected submission failure"}, "uncertain"),
    (202, {"contract_version": 1}, "uncertain"),
])
def test_submit_refusals_and_unknown_receipts_never_retry_or_fallback(clock, monkeypatch, executor,
                                                                   status, payload, expected):
    server = EsafServer()
    server.accepted = status, payload
    with FakeFactoryApi(responder=server.respond) as http:
        h = runtime(http, clock, monkeypatch, executor)
        operation = confirm(h, prepare(h, CASES[2][0], CASES[2][1]))
        assert operation.status.value == expected
        h.clock.advance(15)
        h.service.reconcile()
        assert [call["path"] for call in http.calls if call["method"] == "POST"] == ["/api/v1/esaf/upsert-project"]
        assert not operation.step.job


@pytest.mark.parametrize("state,expected", [
    ("accepted", "queued"), ("pending", "queued"), ("preparing", "in_progress"),
    ("confirming", "in_progress"), ("retrying", "in_progress"),
])
def test_outer_active_states_do_not_inherit_terminal_child_state(state, expected):
    observed = job_observation({"status": state, "child": {"status": "failed", "message": "earlier attempt"}})
    assert observed is not None
    assert (observed["status"], observed["conclusion"]) == (expected, None)


@pytest.mark.parametrize("executor", ["inprocess", "github-runner"])
@pytest.mark.parametrize("error", [TimeoutError("lost response"), URLError("connection lost")])
def test_submission_transport_failure_is_uncertain_without_resubmission(clock, monkeypatch, executor, error):
    server, attempts = EsafServer(), []
    opener = sdk_client.build_opener(sdk_client.ProxyHandler({}), sdk_client._NoRedirect)

    def open_request(request, **kwargs):
        if request.get_method() == "POST":
            attempts.append(request.full_url)
            raise error
        return opener.open(request, **kwargs)

    monkeypatch.setattr(sdk_client, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    with FakeFactoryApi(responder=server.respond) as http:
        h = runtime(http, clock, monkeypatch, executor)
        operation = confirm(h, prepare(h, CASES[2][0], CASES[2][1]))
        assert operation.status.value == "uncertain"
        h = runtime(http, clock, monkeypatch, executor, saved=h.store)
        h.clock.advance(15)
        h.service.reconcile()
        with pytest.raises(InvalidState):
            confirm_current(h.service, operation)
        assert attempts == [http.url + "/api/v1/esaf/upsert-project"]
        assert not operation.step.job
