"""AIF_EXECUTOR=github-runner on the Function side: every Factory API call is handed to aif-ops.yml on the API host and
finished by the runner's signed result (Asynchronous Request-Reply), never by a synchronous call."""

import json
import uuid

import pytest

from aif_lifecycle.adapters.runner_backend import RunnerBackend
from aif_lifecycle.application.runner_protocol import (CATALOG_OPERATION, decode_request, result_body)
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import RunnerJobTracker
from aif_lifecycle.application.guard import SelfProtection
from aif_lifecycle.application.service import LifecycleService
from aif_lifecycle.domain.errors import UpstreamUnavailable, ValidationFailed
from aif_lifecycle.domain.operation import Preview, Status
from aif_lifecycle.http_api import ApiRequest, LifecycleHttpApi
from aif_lifecycle.signatures import sign

from fake_factory_api import CATALOG, JOB, JOB_ID, PREVIEW
from support import FakeGitHub, sequential_ids

SECRET = b"runner-secret"
SCALESET = "aif-121-sdc-dev-002"


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def runner(clock, github):
    store = MemoryStore()
    backend = RunnerBackend(github, store, clock, workflow="aif-ops.yml", ref="main", backend="rest", secret=SECRET,
                            request_ttl_seconds=900, nonces=lambda: uuid.uuid4().hex)
    service = LifecycleService(backend=backend, tracker=RunnerJobTracker(backend, github), store=store,
                               guard=SelfProtection(["aif-121-sdc-dev-001"]), clock=clock, ids=sequential_ids(),
                               poll_after_seconds=120, runner_timeout_seconds=900, github_repository="jostrm/byor")
    return service


def last_request(github):
    """The last dispatched request as the runner reads it (signature checked; expiry not, this is inspection)."""
    return decode_request(github.dispatches[-1]["inputs"]["request"], [SECRET], now=None)


def answer(service, github, outcome="ok", **payload):
    """Act as the runner for the last dispatch: post the result the runner entry point would post."""
    request = last_request(github)
    return service.apply_runner_result(result_body(request, outcome=outcome, run_id=777, catalog=CATALOG, **payload))


def api_preview(**changes):
    """The fake API's review as the API sends it for a non-destructive step (no confirmation phrase)."""
    preview = {**PREVIEW, "can_execute": True, "blockers": [], "expires_at": "2026-10-21T12:10:00Z",
               "confirmation_phrase": None, **changes}
    from aif_lifecycle.adapters.factory_api import preview_from_api
    return preview_from_api(preview)


def seed_catalog(service, github):
    with pytest.raises(UpstreamUnavailable) as waiting:
        service.prepare("add-scaleset", {"scalesetId": SCALESET})
    assert waiting.value.code == "catalog-pending"
    answer(service, github)


def test_prepare_waits_for_the_catalog_snapshot_and_dispatches_one_refresh(runner, github):
    for _ in range(2):
        with pytest.raises(UpstreamUnavailable):
            runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    assert len(github.dispatches) == 1
    dispatch = github.dispatches[0]
    assert dispatch["workflow"] == "aif-ops.yml" and dispatch["inputs"]["action"] == "catalog"
    assert dispatch["inputs"]["operation_id"] == CATALOG_OPERATION
    assert runner.apply_runner_result(result_body(last_request(github), outcome="ok", catalog=CATALOG))["result"] == "applied"


def test_prepare_hands_the_review_to_the_runner_and_applies_its_result(runner, github):
    seed_catalog(runner, github)
    operation = runner.prepare("add-scaleset", {"scalesetId": SCALESET, "scaleSet": {"vnetCidr": "10.1.0.0/18"}})
    assert operation.status is Status.PREPARING
    inputs = github.dispatches[-1]["inputs"]
    assert (inputs["operation_id"], inputs["step"], inputs["action"]) == (operation.id, "0", "prepare")
    request = last_request(github)
    assert inputs["nonce"] == request.nonce
    assert request.backend == "rest" and request.request.step_name == "configure"
    assert request.request.options["scaleSet"] == {"vnetCidr": "10.1.0.0/18"}
    assert operation.to_public()["steps"][0]["waitingFor"]["action"] == "prepare"

    runner.get(operation.id)
    runner.reconcile()
    assert len(github.dispatches) == 2, "a pending hand-off is never dispatched twice"

    result = answer(runner, github, preview=api_preview())
    assert result == {"result": "applied", "operationId": operation.id, "status": "awaiting_confirmation"}
    view = runner.get(operation.id).to_public()["steps"][0]
    assert view["preview"]["confirmationToken"] and view["waitingFor"] is None


def test_a_result_for_another_dispatch_is_ignored(runner, github):
    seed_catalog(runner, github)
    operation = runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    stale = result_body(last_request(github), outcome="ok", preview=api_preview())
    stale["nonce"] = "not-the-nonce"
    assert runner.apply_runner_result(stale)["result"] == "ignored"
    assert runner.get(operation.id).status is Status.PREPARING


def confirmed(runner, github):
    seed_catalog(runner, github)
    operation = runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    answer(runner, github, preview=api_preview())
    view = runner.get(operation.id).to_public()["steps"][0]
    return runner.confirm(operation.id, {"confirmationToken": view["preview"]["confirmationToken"]})


def test_confirm_is_handed_off_once_and_its_result_starts_tracking(runner, github):
    operation = confirmed(runner, github)
    assert operation.status is Status.CONFIRMING
    request = last_request(github)
    assert request.action == "confirm" and request.preview.backend_ref["confirmation_id"] == PREVIEW["confirmation_id"]
    dispatches = len(github.dispatches)
    runner.reconcile()
    assert len(github.dispatches) == dispatches, "a confirm is submitted exactly once"

    answer(runner, github, confirm={"job": {"kind": "catalog"}, "targets": [], "resolvedUpdates": {"scale_set_id": "s-2"}})
    operation = runner.get(operation.id)
    assert operation.steps[0].status is Status.SUCCEEDED and operation.resolved["scale_set_id"] == "s-2"
    assert operation.current == 1 and last_request(github).action == "prepare"


@pytest.mark.parametrize("outcome,status,code", [("error", Status.FAILED, "revision-mismatch"),
                                                 ("uncertain", Status.UNCERTAIN, "completion-unknown")])
def test_confirm_errors_reject_and_transport_failures_stay_uncertain(runner, github, outcome, status, code):
    operation = confirmed(runner, github)
    answer(runner, github, outcome=outcome, error={"code": "revision-mismatch", "detail": "The catalog changed."})
    operation = runner.get(operation.id)
    assert operation.status is status and operation.step.failure["code"] == code


def ops_run_event(github, conclusion, nonce=None):
    inputs = github.dispatches[-1]["inputs"]
    title = f"aif-ops [{inputs['operation_id']}/{inputs['step']}/{inputs['action']}-{nonce or inputs['nonce']}]"
    return {"action": "completed", "repository": {"full_name": "jostrm/byor"}, "workflow_run": {
        "id": 4242, "name": "aif-ops", "display_title": title, "status": "completed", "conclusion": conclusion,
        "html_url": "https://github.com/jostrm/byor/actions/runs/4242", "run_attempt": 1,
        "event": "workflow_dispatch", "path": ".github/workflows/aif-ops.yml"}}


def test_a_failed_ops_run_without_a_result_makes_a_confirm_uncertain(runner, github):
    operation = confirmed(runner, github)
    result = runner.handle_event("workflow_run", "d-1", ops_run_event(github, "failure"))
    assert result["result"] == "applied"
    operation = runner.get(operation.id)
    assert operation.status is Status.UNCERTAIN
    assert "actions/runs/4242" in operation.step.failure["detail"]


def test_only_the_run_of_the_pending_dispatch_can_end_a_hand_off(runner, github):
    operation = confirmed(runner, github)
    other = runner.handle_event("workflow_run", "d-3", ops_run_event(github, "failure", nonce="0" * 32))
    assert other["result"] == "ignored"
    assert runner.get(operation.id).status is Status.CONFIRMING


def test_dispatched_requests_are_signed_and_expire(runner, github, clock):
    with pytest.raises(UpstreamUnavailable):
        runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    text = github.dispatches[-1]["inputs"]["request"]
    assert decode_request(text, [SECRET], now=clock.now().timestamp()).action == "catalog"
    with pytest.raises(ValidationFailed):
        decode_request(text, [b"another-secret"], now=clock.now().timestamp())
    with pytest.raises(ValidationFailed):
        decode_request(text, [SECRET], now=clock.now().timestamp() + 901)
    payload, signature = text.split(".")
    with pytest.raises(ValidationFailed):
        decode_request(payload[:-4] + "AAAA." + signature, [SECRET], now=clock.now().timestamp())


def test_a_failed_ops_run_without_a_result_fails_a_prepare(runner, github):
    seed_catalog(runner, github)
    operation = runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    runner.handle_event("workflow_run", "d-2", ops_run_event(github, "cancelled"))
    operation = runner.get(operation.id)
    assert operation.status is Status.FAILED and operation.step.failure["code"] == "runner-failed"


def running(runner, github, clock):
    operation = confirmed(runner, github)
    answer(runner, github, confirm={"job": {"kind": "catalog"}, "targets": [], "resolvedUpdates": {}})
    answer(runner, github, preview=api_preview())          # step 1's review (faked runner answers)
    view = runner.get(operation.id).to_public()["steps"][1]
    runner.confirm(operation.id, {"confirmationToken": view["preview"]["confirmationToken"]})
    answer(runner, github, confirm={"job": {"kind": "job", "job_id": JOB_ID, "status": "queued"},
                                    "targets": [f"api-job-{JOB_ID}"], "resolvedUpdates": {}})
    return runner.get(operation.id)


def test_status_checks_go_through_the_runner_one_at_a_time(runner, github, clock):
    operation = running(runner, github, clock)
    assert operation.step.status is Status.RUNNING and operation.step.runs[0].status == "queued"
    dispatches = len(github.dispatches)
    clock.advance(121)
    runner.reconcile()
    runner.reconcile()
    assert len(github.dispatches) == dispatches + 1
    request = last_request(github)
    assert request.action == "status" and request.job == {"kind": "job", "job_id": JOB_ID, "status": "queued"}

    run = {"id": 9001, "html_url": "https://github.com/jostrm/byor/actions/runs/9001", "status": "completed",
           "conclusion": "success"}
    answer(runner, github, status=dict(JOB, status="succeeded", pipeline_runs=[run]))
    operation = runner.get(operation.id)
    assert operation.steps[1].status is Status.SUCCEEDED
    assert operation.steps[1].runs[0].html_url.endswith("/9001") and operation.steps[1].runs[0].source == "runner"
    assert operation.current == 2 and last_request(github).action == "prepare"


def test_runner_timeouts_fail_a_prepare_and_leave_a_confirm_uncertain(runner, github, clock):
    seed_catalog(runner, github)
    waiting_review = runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    clock.advance(901)
    assert runner.reconcile()["timedOut"] == 1
    failed = runner.get(waiting_review.id)
    assert failed.status is Status.FAILED and failed.step.failure["code"] == "runner-timeout"

    github.dispatches.clear()
    other = runner.prepare("add-scaleset", {"scalesetId": "aif-121-sdc-dev-003"})
    answer(runner, github, preview=api_preview(expires_at="2026-10-21T13:00:00Z"))
    view = runner.get(other.id).to_public()["steps"][0]
    runner.confirm(other.id, {"confirmationToken": view["preview"]["confirmationToken"]})
    clock.advance(901)
    runner.reconcile()
    assert runner.get(other.id).status is Status.UNCERTAIN


def test_the_results_route_checks_the_signature_before_applying(runner, github):
    api = LifecycleHttpApi(runner, event_secrets=[SECRET])
    with pytest.raises(UpstreamUnavailable):
        runner.prepare("add-scaleset", {"scalesetId": SCALESET})
    body = json.dumps(result_body(last_request(github), outcome="ok", catalog=CATALOG)).encode()
    bad = api.runner_results(ApiRequest("POST", "/api/v1/runner/results", body=body,
                                        headers={"x-hub-signature-256": sign(b"wrong", body)}))
    assert bad.status == 401
    good = api.runner_results(ApiRequest("POST", "/api/v1/runner/results", body=body,
                                         headers={"x-hub-signature-256": sign(SECRET, body)}))
    assert good.status == 202 and json.loads(good.body)["result"] == "applied"


def test_catalog_refresh_route_dispatches_a_refresh(runner, github):
    api = LifecycleHttpApi(runner, event_secrets=[SECRET])
    response = api.refresh_catalog(ApiRequest("POST", "/api/v1/catalog/refresh"))
    assert response.status == 202 and github.dispatches[-1]["inputs"]["action"] == "catalog"


def test_runner_requests_round_trip_the_review_for_the_confirm(runner, github, clock):
    operation = confirmed(runner, github)
    request = last_request(github)
    assert isinstance(request.preview, Preview) and request.preview.can_execute
    assert request.operation_id == operation.id and request.step == 0 and request.nonce
    assert request.expires == int(clock.now().timestamp()) + 900
