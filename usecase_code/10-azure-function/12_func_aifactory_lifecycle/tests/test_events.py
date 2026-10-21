"""GitHub workflow events drive the steps; duplicates are ignored and the poller recovers lost events."""

import pytest

from aif_lifecycle.application.events import correlate, parse_workflow_run
from aif_lifecycle.domain import errors
from aif_lifecycle.domain.operation import Status

from support import FakeGitHub, confirm_current, make_service

SCALESET_2 = "aif-121-sdc-dev-002"


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def service(clock, github):
    service = make_service(clock, github=github)
    operation = service.prepare("init-factory", {"factoryId": "aif-121-sdc-dev", "wholeWorkflow": True})
    operation = confirm_current(service, operation)
    operation = confirm_current(service, operation)
    for index in range(3):
        service.handle_event("workflow_run", f"seed-{index}", github.complete(index))
    assert service.get(operation.id).status is Status.SUCCEEDED
    github.dispatches.clear()
    github.runs.clear()
    github._next_run = 1000
    return service


def running_scaleset(service, **options):
    operation = service.prepare("add-scaleset", {"scalesetId": SCALESET_2, **options})
    operation = confirm_current(service, operation)
    return confirm_current(service, operation)


def test_confirm_dispatches_one_dummy_run_with_the_correlation_inputs(service, github):
    operation = running_scaleset(service)
    assert operation.status is Status.RUNNING
    assert github.dispatches == [{"workflow": "aif-dummy-step.yml", "ref": "main", "inputs": {
        "operation_id": operation.id, "step": "1", "target": "aif-121-esml-common-sdc-dev-002",
        "outcome": "success", "duration_seconds": "60", "relay": "true"}}]


def test_a_success_event_completes_the_step_and_prepares_the_next_review(service, github):
    operation = running_scaleset(service)
    result = service.handle_event("workflow_run", "d-1", github.complete(0))
    assert result == {"result": "applied", "operationId": operation.id, "change": "step-succeeded"}
    operation = service.get(operation.id)
    assert operation.steps[1].status is Status.SUCCEEDED
    assert operation.steps[1].runs[0].html_url.endswith("/actions/runs/1001")
    assert operation.status is Status.AWAITING_CONFIRMATION and operation.current == 2


def test_a_duplicate_delivery_is_ignored(service, github):
    running_scaleset(service)
    payload = github.complete(0)
    service.handle_event("workflow_run", "d-1", payload)
    assert service.handle_event("workflow_run", "d-1", payload) == {"result": "duplicate"}


def test_a_failure_event_stops_the_chain_with_the_run_link_and_a_log_excerpt(service, github):
    operation = running_scaleset(service, simulate={"failAt": "deploy-common"})
    assert github.dispatches[0]["inputs"]["outcome"] == "failure"
    service.handle_event("workflow_run", "d-2", github.complete(0, conclusion="failure"))
    operation = service.get(operation.id)
    assert operation.status is Status.FAILED
    assert operation.steps[1].failure["runUrl"].endswith("/actions/runs/1001")
    assert operation.steps[1].failure["logExcerpt"] == "Simulated failure for aif-121-esml-common-sdc-dev-002"


def test_the_poller_recovers_a_lost_event(service, github, clock):
    operation = running_scaleset(service)
    github.complete(0)
    assert service.reconcile()["polled"] == 0
    clock.advance(121)
    summary = service.reconcile()
    assert summary["polled"] == 1
    operation = service.get(operation.id)
    assert operation.steps[1].runs[0].source == "poller"
    assert operation.status is Status.AWAITING_CONFIRMATION and operation.current == 2


def test_events_that_belong_to_no_operation_are_reported_as_uncorrelated(service):
    payload = {"action": "completed", "workflow_run": {
        "id": 5, "name": "ci", "display_title": "Some other run", "status": "completed", "conclusion": "success",
        "html_url": "https://github.com/o/r/actions/runs/5", "run_attempt": 1}}
    assert service.handle_event("workflow_run", "d-3", payload) == {"result": "uncorrelated"}


def test_other_event_types_are_ignored(service):
    assert service.handle_event("push", "d-4", {}) == {"result": "ignored"}
    assert service.handle_event("ping", "d-5", {"zen": "x"}) == {"result": "pong"}


def test_malformed_workflow_run_payloads_are_400(service):
    with pytest.raises(errors.ValidationFailed):
        service.handle_event("workflow_run", "d-6", {"action": "completed"})


def test_correlation_reads_the_run_name_marker():
    marker = correlate("aif-step [00000000-0000-0000-0000-000000000001/2/aif-121-esml-common-sdc-dev-002] success")
    assert marker == ("00000000-0000-0000-0000-000000000001", 2, "aif-121-esml-common-sdc-dev-002")
    assert correlate("factory-lifecycle [3f0c9b2e-1111-4222-8333-944455556666]") is None


def test_parse_workflow_run_keeps_only_what_the_function_needs():
    observed = parse_workflow_run({"action": "in_progress", "workflow_run": {
        "id": 7, "name": "aif-dummy-step", "display_title": "t", "status": "in_progress", "conclusion": None,
        "html_url": "https://github.com/o/r/actions/runs/7", "run_attempt": 2}})
    assert (observed.run_id, observed.status, observed.conclusion, observed.attempt) == (7, "in_progress", None, 2)
