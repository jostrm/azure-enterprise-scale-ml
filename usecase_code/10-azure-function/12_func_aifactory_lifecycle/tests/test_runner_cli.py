"""The runner entry point (aif-ops.yml on the Factory API host): one Factory API call through the REST or SDK adapter,
reported to the Function as one signed result."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aif_lifecycle import runner
from aif_lifecycle.application.runner_protocol import (RunnerRequest, classify_confirm_failure, encode_request,
                                                     parse_result)
from aif_lifecycle.domain.errors import (RevisionMismatch, UpstreamError, UpstreamTimeout, UpstreamUnavailable,
                                         ValidationFailed)
from aif_lifecycle.domain.operation import StepKind
from aif_lifecycle.domain.scenarios import Scenario
from aif_lifecycle.ports import StepRequest
from aif_lifecycle.signatures import verify

from fake_factory_api import CATALOG, CONFIRMATION_ID, FACTORY_ID, PREVIEW, SCALESET_ID, FakeFactoryApi

SECRET = "runner-secret"


class FakeFunction:
    """Records the results the runner posts; answers 503 for the first `failures` posts."""

    def __init__(self, failures=0):
        self.posts, self.failures = [], failures
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.posts.append({"path": self.path, "body": body,
                                    "signature": self.headers.get("X-Hub-Signature-256")})
                status = 503 if len(outer.posts) <= outer.failures else 202
                self.send_response(status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/api/v1/runner/results"
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()

    def result(self, index=-1):
        post = self.posts[index]
        assert verify([SECRET.encode()], post["body"], post["signature"])
        return json.loads(post["body"])


@pytest.fixture
def function():
    fake = FakeFunction()
    yield fake
    fake.close()


def step_request(name="deploy-common", kind=StepKind.DEPLOY):
    return StepRequest(operation_id="00000000-0000-4000-8000-000000000001", scenario=Scenario.ADD_SCALESET,
                       step_index=1, step_name=name, kind=kind, target="aif-121-sdc-dev-002",
                       resolved={"factory_id": FACTORY_ID, "scale_set_id": SCALESET_ID, "environment": "dev",
                                 "suffix": "002", "project_number": "001"},
                       settings={}, options={})


def env_for(api_url, function, request, backend="rest", *, secret=SECRET, expires_in=600):
    """The environment aif-ops.yml gives the runner: the signed request plus the workflow inputs that must match it."""
    runner_request = RunnerRequest(action=request.pop("action"), nonce="n1", backend=backend,
                                   operation_id="00000000-0000-4000-8000-000000000001", step=1, **request)
    text = encode_request(runner_request, secret.encode(), expires=int(time.time()) + expires_in)
    return {"AIF_RUNNER_REQUEST": text, "AIF_OPERATION_ID": runner_request.operation_id, "AIF_STEP": "1",
            "AIF_ACTION": runner_request.action, "AIF_NONCE": "n1", "AIF_FACTORY_API_URL": api_url,
            "AIF_FACTORY_API_KEY": "test-key", "AIF_FACTORY_FOLDER": "C:/aif/byor-121",
            "AIF_RESULTS_URL": function.url, "AIF_EVENT_SECRET": SECRET, "GITHUB_RUN_ID": "555",
            "GITHUB_RUN_ATTEMPT": "1"}


def test_prepare_goes_through_rest_and_posts_a_signed_result_with_the_catalog(function):
    with FakeFactoryApi() as api:
        code = runner.main(env_for(api.url, function, {"action": "prepare", "request": step_request()}))
    assert code == 0
    result = function.result()
    assert result["outcome"] == "ok" and result["runId"] == "555" and result["nonce"] == "n1"
    assert result["preview"]["backend_ref"]["confirmation_id"] == CONFIRMATION_ID
    assert result["catalog"] == CATALOG
    assert all(call["key"] for call in api.calls if call["path"] != "/openapi.json")
    assert parse_result(result).preview.plan[0] == PREVIEW["summary"]


@pytest.mark.parametrize("backend", ["rest", "sdk"])
def test_the_runner_waits_for_a_slow_factory_api_call_as_long_as_its_setting_allows(function, backend):
    # A real runtime review takes minutes; AIF_FACTORY_API_TIMEOUT_SECONDS (runner.json or environment) bounds the call.
    with FakeFactoryApi(slow={"/api/v1/factory-catalog/prepare": 1.5}) as api:
        env = env_for(api.url, function, {"action": "prepare", "request": step_request()}, backend)
        runner.main({**env, "AIF_FACTORY_API_TIMEOUT_SECONDS": "1"})
        timed_out = function.result()
        env = env_for(api.url, function, {"action": "prepare", "request": step_request()}, backend)
        runner.main({**env, "AIF_FACTORY_API_TIMEOUT_SECONDS": "10"})
        answered = function.result()
    assert timed_out["outcome"] == "error" and timed_out["error"]["code"] == "upstream-timeout"
    assert answered["outcome"] == "ok" and answered["preview"]["backend_ref"]["confirmation_id"] == CONFIRMATION_ID


def test_sdk_and_rest_report_the_same_review(function):
    bodies = {}
    for backend in ("rest", "sdk"):
        with FakeFactoryApi() as api:
            runner.main(env_for(api.url, function, {"action": "prepare", "request": step_request()}, backend))
        bodies[backend] = {key: value for key, value in function.result().items() if key != "resultId"}
    assert bodies["rest"]["preview"] == bodies["sdk"]["preview"]


@pytest.mark.parametrize("backend", ["rest", "sdk"])
def test_the_runner_reviews_and_confirms_a_scale_set_enrollment_once_with_its_phrase(function, backend):
    request = step_request("enroll-scaleset", StepKind.ENROLL)
    with FakeFactoryApi() as api:
        runner.main(env_for(api.url, function, {"action": "prepare", "request": request}, backend))
        review = parse_result(function.result()).preview
        assert review.confirmation_phrase == "ENROLL SCALE SET aif-121 002" and review.can_execute
        runner.main(env_for(api.url, function, {"action": "confirm", "request": request, "preview": review,
                                                "phrase": review.confirmation_phrase}, backend))
        confirmed = parse_result(function.result())
        confirms = [call["body"] for call in api.calls if call["path"].endswith("/enroll-scale-set/confirm")]
    assert confirmed.outcome == "ok" and confirmed.confirm.targets == []
    assert confirmed.confirm.job["kind"] == "enrollment" and confirmed.confirm.job["status"] == "enrolled"
    assert confirms == [{"contract_version": 1, "folder": "C:/aif/byor-121", "confirmation_id": CONFIRMATION_ID,
                         "preview_hash": "e" * 64, "confirmation_phrase": "ENROLL SCALE SET aif-121 002"}]


def delete_request():
    return StepRequest(operation_id="00000000-0000-4000-8000-000000000001", scenario=Scenario.DELETE_SCALESET,
                       step_index=1, step_name="delete-scaleset", kind=StepKind.DELETE, target="aif-121-sdc-dev-001",
                       resolved={"factory_id": FACTORY_ID, "scale_set_id": SCALESET_ID, "environment": "dev"},
                       settings={}, options={})


@pytest.mark.parametrize("allowed, outcome", [(None, "error"), ("false", "error"), ("true", "ok")])
def test_the_runner_refuses_a_signed_delete_request_unless_its_settings_allow_deletes(function, allowed, outcome):
    with FakeFactoryApi() as api:
        env = env_for(api.url, function, {"action": "prepare", "request": delete_request()})
        if allowed is not None:
            env["AIF_ALLOW_REAL_DELETES"] = allowed
        assert runner.main(env) == 0
    result = function.result()
    assert result["outcome"] == outcome
    posts = [call["path"] for call in api.calls if call["method"] == "POST"]
    if outcome == "error":
        assert result["error"]["code"] == "deletes-disabled" and posts == []
    else:
        assert posts == ["/api/v1/factory-catalog/prepare"]


def test_confirm_is_submitted_once_and_reports_the_job(function):
    preview = parse_result({"v": 1, "action": "prepare", "nonce": "x", "operationId": None, "step": None,
                            "outcome": "ok", "preview": _preview_dict()}).preview
    with FakeFactoryApi() as api:
        runner.main(env_for(api.url, function, {"action": "confirm", "request": step_request(), "preview": preview}))
    confirms = [call for call in api.calls if call["path"] == "/api/v1/factory-catalog/confirm"]
    assert len(confirms) == 1 and confirms[0]["body"]["confirmation_id"] == CONFIRMATION_ID
    result = function.result()
    assert result["outcome"] == "ok" and result["confirm"]["targets"][0].startswith("api-job-")


def test_an_unreachable_api_on_confirm_is_uncertain_not_retried(function):
    preview = parse_result({"v": 1, "action": "prepare", "nonce": "x", "operationId": None, "step": None,
                            "outcome": "ok", "preview": _preview_dict()}).preview
    port = _closed_port()
    runner.main(env_for(f"http://127.0.0.1:{port}", function,
                        {"action": "confirm", "request": step_request(), "preview": preview}))
    result = function.result()
    assert result["outcome"] == "uncertain" and result["error"]["code"] == "upstream-unavailable"


def test_a_new_consumer_folder_reports_an_empty_catalog_so_init_factory_can_be_planned(function):
    with FakeFactoryApi(missing_catalog=True) as api:
        assert runner.main(env_for(api.url, function, {"action": "catalog"})) == 0
    result = function.result()
    assert result["outcome"] == "ok" and result["catalog"] == {"revision": "", "factories": []}


def test_status_reports_the_api_job(function):
    with FakeFactoryApi() as api:
        runner.main(env_for(api.url, function, {"action": "status", "job": {"kind": "job", "job_id": "j-1"}}))
    assert function.result()["status"]["status"] == "queued"


def test_results_are_posted_again_after_a_server_error_and_a_lost_post_fails_the_job(monkeypatch):
    monkeypatch.setattr(runner, "_pause", lambda seconds: None)
    flaky = FakeFunction(failures=1)
    try:
        with FakeFactoryApi() as api:
            assert runner.main(env_for(api.url, flaky, {"action": "catalog"})) == 0
        assert len(flaky.posts) == 2
    finally:
        flaky.close()
    down = FakeFunction(failures=99)
    try:
        with FakeFactoryApi() as api:
            assert runner.main(env_for(api.url, down, {"action": "catalog"})) == 1
    finally:
        down.close()


def test_a_rerun_never_submits_a_confirmation_again(function):
    preview = parse_result({"v": 1, "action": "prepare", "nonce": "x", "operationId": None, "step": None,
                            "outcome": "ok", "preview": _preview_dict()}).preview
    with FakeFactoryApi() as api:
        env = env_for(api.url, function, {"action": "confirm", "request": step_request(), "preview": preview})
        env["GITHUB_RUN_ATTEMPT"] = "2"
        assert runner.main(env) == 3
    assert api.calls == [] and function.posts == []


@pytest.mark.parametrize("change", ["foreign-signature", "expired", "inputs"])
def test_requests_the_function_did_not_sign_for_this_run_are_refused(function, change):
    with FakeFactoryApi() as api:
        if change == "foreign-signature":
            env = env_for(api.url, function, {"action": "catalog"}, secret="someone-else")
        elif change == "expired":
            env = env_for(api.url, function, {"action": "catalog"}, expires_in=-1)
        else:
            env = env_for(api.url, function, {"action": "catalog"})
            env["AIF_STEP"] = "2"
        with pytest.raises(ValidationFailed):
            runner.main(env)
    assert api.calls == [] and function.posts == []


def test_the_results_url_must_be_https_unless_loopback(function):
    with FakeFactoryApi() as api:
        env = env_for(api.url, function, {"action": "catalog"})
        env["AIF_RESULTS_URL"] = "http://func.example.com/api/v1/runner/results"
        with pytest.raises(ValidationFailed):
            runner.main(env)


@pytest.mark.parametrize("error,kind", [(UpstreamTimeout("t"), "uncertain"), (UpstreamUnavailable("u"), "uncertain"),
                                        (UpstreamError("e"), "uncertain"), (RevisionMismatch("r"), "error"),
                                        (ValidationFailed("v"), "error"), (RuntimeError("?"), "uncertain")])
def test_confirm_failures_are_classified_once_for_both_hosts(error, kind):
    assert classify_confirm_failure(error) == kind


def test_oversized_requests_are_refused():
    big = step_request()
    big = StepRequest(**{**big.__dict__, "settings": {"blob": "x" * 70000}})
    with pytest.raises(ValidationFailed):
        encode_request(RunnerRequest(action="prepare", nonce="n", backend="rest", operation_id=None, step=0, request=big),
                       SECRET.encode(), expires=int(time.time()) + 60)


def _preview_dict():
    from dataclasses import asdict
    from aif_lifecycle.adapters.factory_api import preview_from_api
    return asdict(preview_from_api(dict(PREVIEW, can_execute=True, blockers=[])))


def _closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
