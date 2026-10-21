"""The HTTP contract: 202 + Location + Retry-After for changes, RFC 9457 problems, HMAC-checked events."""

import json

import pytest

from aif_lifecycle.domain.errors import InvalidSignature
from aif_lifecycle.http_api import ApiRequest, LifecycleHttpApi
from aif_lifecycle.signatures import sign

from support import FakeGitHub, make_service

SECRET = b"relay-secret"


@pytest.fixture
def api(clock):
    service = make_service(clock, protected=["spider-esml-project001-sdc-dev-001-rg"])
    return LifecycleHttpApi(service, event_secrets=[SECRET])


def call(api, handler, *, method="POST", path="/api/v1/x", params=None, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    request = ApiRequest(method=method, path=path, route_params=params or {},
                         headers={k.lower(): v for k, v in (headers or {}).items()}, body=data)
    response = getattr(api, handler)(request)
    return response, (json.loads(response.body) if response.body else None)


def prepare(api, scenario="init-factory", body=None):
    return call(api, "prepare", path=f"/api/v1/lifecycle/{scenario}/prepare", params={"scenario": scenario},
                body=body if body is not None else {"factoryId": "aif-121-sdc-dev"})


def test_health_is_small_and_has_no_secrets(api):
    response, body = call(api, "health", method="GET", path="/api/v1/health")
    assert response.status == 200
    assert body["status"] == "ok" and body["backend"] == "mock"
    assert "secret" not in response.body.decode().lower()


def test_prepare_returns_202_with_location_and_retry_after(api):
    response, body = prepare(api)
    assert response.status == 202
    assert response.headers["Location"] == f"/api/v1/operations/{body['operationId']}"
    assert response.headers["Retry-After"] == "5"
    assert response.headers["Content-Type"].startswith("application/json")
    assert body["status"] == "awaiting_confirmation"


def test_get_operation_is_200_and_unknown_is_404_problem(api):
    _, created = prepare(api)
    response, body = call(api, "get_operation", method="GET", params={"operation_id": created["operationId"]})
    assert response.status == 200 and body["operationId"] == created["operationId"]
    response, problem = call(api, "get_operation", method="GET", path="/api/v1/operations/nope",
                             params={"operation_id": "nope"})
    assert response.status == 404
    assert response.headers["Content-Type"] == "application/problem+json"
    assert problem["code"] == "operation-not-found" and problem["instance"] == "/api/v1/operations/nope"


def test_confirm_returns_202_and_wrong_token_is_400(api):
    _, created = prepare(api)
    operation_id = created["operationId"]
    response, problem = call(api, "confirm", params={"operation_id": operation_id}, body={"confirmationToken": "0" * 64})
    assert response.status == 400 and problem["code"] == "confirmation-mismatch"
    token = created["steps"][0]["preview"]["confirmationToken"]
    response, body = call(api, "confirm", params={"operation_id": operation_id}, body={"confirmationToken": token})
    assert response.status == 202
    assert response.headers["Location"] == f"/api/v1/operations/{operation_id}"
    assert body["currentStep"] == 1


def test_an_expired_confirmation_is_410(api, clock):
    _, created = prepare(api)
    clock.advance(601)
    token = created["steps"][0]["preview"]["confirmationToken"]
    response, problem = call(api, "confirm", params={"operation_id": created["operationId"]}, body={"confirmationToken": token})
    assert response.status == 410 and problem["code"] == "confirmation-expired"


@pytest.mark.parametrize("scenario, body, status, code", [
    ("init-factory", {"factoryId": "AIF"}, 400, "invalid-id"),
    ("rebuild", {"factoryId": "aif-121-sdc-dev"}, 400, "unsupported-scenario"),
    ("delete-project", {"projectId": "spider-esml-project001-sdc-dev-001-rg"}, 403, "protected-target"),
    ("delete-scaleset", {"scalesetId": "aif-121-sdc-dev-009"}, 404, "unknown-id"),
])
def test_errors_map_to_problem_statuses(api, scenario, body, status, code):
    response, problem = prepare(api, scenario, body)
    assert response.status == status and problem["code"] == code
    assert problem["type"] == f"urn:aifactory:lifecycle:problem:{code}"


def test_a_second_init_of_the_same_factory_is_409(api):
    _, created = prepare(api)
    response, problem = prepare(api)
    assert response.status == 409 and problem["code"] == "in-progress"
    assert problem["operationId"] == created["operationId"]


def test_invalid_json_is_400(api):
    response, problem = call(api, "prepare", params={"scenario": "init-factory"}, raw=b"{not json")
    assert response.status == 400 and problem["code"] == "invalid-json"


def test_the_correlation_id_is_echoed(api):
    response, problem = prepare(api, "init-factory", {"factoryId": "AIF"})
    assert response.headers["x-correlation-id"] == problem["correlationId"]
    response, _ = call(api, "health", method="GET", headers={"x-correlation-id": "abc-123"})
    assert response.headers["x-correlation-id"] == "abc-123"


def test_unexpected_errors_are_500_without_details(clock):
    class Exploding:
        def health(self):
            raise RuntimeError("password=hunter2 Traceback")

    api = LifecycleHttpApi(Exploding(), event_secrets=[SECRET])
    response, problem = call(api, "health", method="GET")
    assert response.status == 500 and problem["code"] == "internal-error"
    assert b"hunter2" not in response.body and b"Traceback" not in response.body


def signed(payload, *, secret=SECRET, delivery="d-1", event="workflow_run"):
    raw = json.dumps(payload).encode()
    return {"raw": raw, "headers": {"X-Hub-Signature-256": sign(secret, raw), "X-GitHub-Delivery": delivery,
                                    "X-GitHub-Event": event}}


RUN = {"action": "completed", "workflow_run": {"id": 9, "name": "ci", "display_title": "unrelated", "status": "completed",
                                               "conclusion": "success", "html_url": "https://github.com/o/r/actions/runs/9"}}


def test_events_with_a_bad_signature_are_401(api):
    request = signed(RUN, secret=b"wrong")
    response, problem = call(api, "github_events", raw=request["raw"], headers=request["headers"])
    assert response.status == 401 and problem["code"] == "invalid-signature"


def test_events_without_a_signature_are_401(api):
    response, problem = call(api, "github_events", body=RUN, headers={"X-GitHub-Delivery": "d", "X-GitHub-Event": "workflow_run"})
    assert response.status == 401


def test_a_signed_event_is_accepted_and_a_duplicate_is_ignored(api):
    request = signed(RUN)
    response, body = call(api, "github_events", raw=request["raw"], headers=request["headers"])
    assert response.status == 200 and body == {"result": "uncorrelated"}
    response, body = call(api, "github_events", raw=request["raw"], headers=request["headers"])
    assert response.status == 200 and body == {"result": "duplicate"}


def test_an_applied_event_is_202(clock):
    github = FakeGitHub()
    service = make_service(clock, github=github)
    api = LifecycleHttpApi(service, event_secrets=[SECRET])
    _, created = call(api, "prepare", params={"scenario": "init-factory"},
                      body={"factoryId": "aif-121-sdc-dev", "wholeWorkflow": True})
    operation_id = created["operationId"]
    for _ in range(2):
        current = service.get(operation_id).to_public()
        token = current["steps"][current["currentStep"]]["preview"]["confirmationToken"]
        call(api, "confirm", params={"operation_id": operation_id}, body={"confirmationToken": token})
    request = signed(github.complete(0), delivery="d-9")
    response, body = call(api, "github_events", raw=request["raw"], headers=request["headers"])
    assert response.status == 202 and body["result"] == "applied" and body["operationId"] == operation_id


def test_queued_events_are_signed_and_forged_queue_messages_are_rejected(clock):
    queued = []
    service = make_service(clock)
    api = LifecycleHttpApi(service, event_secrets=[SECRET], enqueue=queued.append)
    request = signed(RUN, delivery="d-q")
    response, body = call(api, "github_events", raw=request["raw"], headers=request["headers"])
    assert response.status == 202 and body == {"result": "queued"}
    message = queued[0]
    assert message["source"] == "relay" or message["source"] == "webhook"
    assert api.process_queued(message) == {"result": "uncorrelated"}
    forged = {**message, "run": {**message["run"], "conclusion": "failure"}}
    with pytest.raises(InvalidSignature):
        api.process_queued(forged)
    with pytest.raises(InvalidSignature):
        api.process_queued({key: value for key, value in message.items() if key != "signature"})


def test_list_operations(api):
    prepare(api)
    response, body = call(api, "list_operations", method="GET")
    assert response.status == 200 and len(body["operations"]) == 1
    assert set(body["operations"][0]) == {"operationId", "scenario", "target", "status", "currentStep", "createdAt",
                                          "updatedAt"}
