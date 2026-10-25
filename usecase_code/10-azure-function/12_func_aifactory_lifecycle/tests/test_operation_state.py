import pytest

from aif_lifecycle.domain.errors import ConfirmationExpired, InvalidState, ValidationFailed
from aif_lifecycle.domain.operation import Operation, Preview, Status, Step, StepKind
from aif_lifecycle.domain.scenarios import Scenario

OPERATION_ID = "0f3b1c2a-4d5e-4f60-8a9b-0c1d2e3f4a5b"


def preview(*, can_execute=True, blockers=(), phrase=None, ttl=600, clock=None, groups=("aif-121-esml-common-sdc-dev-002",)):
    return Preview(
        plan=["Deploy the common resource group"], affected_resource_groups=list(groups),
        blockers=list(blockers), can_execute=can_execute,
        expires_at=clock.now().timestamp() + ttl, confirmation_phrase=phrase,
        backend_ref={"confirmation_id": "c-1"},
    )


def new_operation(clock, *steps):
    steps = steps or (Step.new("configure", StepKind.CONFIGURE), Step.new("deploy-common", StepKind.DEPLOY))
    return Operation.create(
        operation_id=OPERATION_ID, scenario=Scenario.ADD_SCALESET, target="aif-121-sdc-dev-002",
        settings={}, steps=list(steps), backend="mock", executor="inprocess", now=clock.now(),
    )


def awaiting(clock, *steps, **preview_args):
    operation = new_operation(clock, *steps)
    operation.review_ready(preview(clock=clock, **preview_args), clock.now())
    return operation


def test_a_new_operation_prepares_its_first_step(clock):
    operation = new_operation(clock)
    assert operation.status is Status.PREPARING
    assert operation.current == 0
    assert operation.steps[0].status is Status.PREPARING
    assert operation.steps[1].status is Status.PENDING


def test_an_executable_preview_waits_for_confirmation_with_a_plan_bound_token(clock):
    operation = awaiting(clock)
    step = operation.steps[0]
    assert operation.status is Status.AWAITING_CONFIRMATION
    assert len(step.plan_hash) == 64
    view = operation.to_public()
    assert view["steps"][0]["preview"]["confirmationToken"] == step.plan_hash
    assert "confirmation_id" not in str(view)


def test_a_preview_with_blockers_blocks_the_operation(clock):
    operation = awaiting(clock, can_execute=False, blockers=["Hub link missing"])
    assert operation.status is Status.BLOCKED and operation.is_terminal


def test_confirm_requires_the_exact_token(clock):
    operation = awaiting(clock)
    with pytest.raises(ValidationFailed) as error:
        operation.confirm("0" * 64, None, clock.now())
    assert error.value.code == "confirmation-mismatch"
    assert operation.status is Status.AWAITING_CONFIRMATION


def test_confirm_after_the_review_expired_is_gone(clock):
    operation = awaiting(clock, ttl=60)
    clock.advance(61)
    with pytest.raises(ConfirmationExpired):
        operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    assert operation.status is Status.EXPIRED and operation.is_terminal


def test_a_review_is_confirmed_once(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    assert operation.status is Status.CONFIRMING
    with pytest.raises(InvalidState):
        operation.confirm(operation.steps[0].plan_hash, None, clock.now())


def test_deletes_require_the_exact_confirmation_phrase(clock):
    operation = awaiting(clock, Step.new("delete-project", StepKind.DELETE), phrase="DELETE aif-121-esml-project002-sdc-dev-001-rg")
    token = operation.steps[0].plan_hash
    for phrase in (None, "delete aif-121-esml-project002-sdc-dev-001-rg", "DELETE something-else"):
        with pytest.raises(ValidationFailed) as error:
            operation.confirm(token, phrase, clock.now())
        assert error.value.code == "confirmation-phrase-mismatch"
    operation.confirm(token, "DELETE aif-121-esml-project002-sdc-dev-001-rg", clock.now())
    assert operation.status is Status.CONFIRMING


def test_a_configuration_step_without_runs_succeeds_and_the_next_step_starts(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    operation.confirm_accepted({"job_id": None}, [], clock.now())
    assert operation.steps[0].status is Status.SUCCEEDED
    assert operation.current == 1
    assert operation.status is Status.PREPARING
    assert operation.steps[1].status is Status.PREPARING


def test_runs_execute_in_order_and_the_last_success_completes_the_operation(clock):
    operation = awaiting(clock, Step.new("delete-scaleset", StepKind.DELETE), phrase="DELETE aif-121-sdc-dev-002")
    operation.confirm(operation.steps[0].plan_hash, "DELETE aif-121-sdc-dev-002", clock.now())
    operation.confirm_accepted({"job_id": "j-1"}, ["project-rg", "common-rg"], clock.now())
    assert operation.status is Status.RUNNING
    assert operation.next_dispatchable_run().target == "project-rg"
    operation.run_dispatched("project-rg", clock.now())
    assert operation.next_dispatchable_run() is None
    operation.run_update(target="project-rg", status="completed", conclusion="success", run_id=11,
                         html_url="https://github.com/o/r/actions/runs/11", source="relay", now=clock.now())
    assert operation.next_dispatchable_run().target == "common-rg"
    operation.run_dispatched("common-rg", clock.now())
    operation.run_update(target="common-rg", status="completed", conclusion="success", run_id=12,
                         html_url="https://github.com/o/r/actions/runs/12", source="poller", now=clock.now())
    assert operation.status is Status.SUCCEEDED and operation.is_terminal


def test_a_failed_run_fails_the_step_with_the_run_link_and_stops(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    operation.confirm_accepted({"job_id": "j-1"}, ["common-rg"], clock.now())
    operation.run_dispatched("common-rg", clock.now())
    change = operation.run_update(target="common-rg", status="completed", conclusion="failure", run_id=21,
                                  html_url="https://github.com/o/r/actions/runs/21", source="relay", now=clock.now())
    assert change == "step-failed"
    assert operation.status is Status.FAILED
    assert operation.steps[0].failure["runUrl"] == "https://github.com/o/r/actions/runs/21"
    assert operation.steps[1].status is Status.PENDING


def test_late_or_regressing_run_events_are_ignored(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    operation.confirm_accepted({"job_id": "j-1"}, ["common-rg", "project-rg"], clock.now())
    operation.run_dispatched("common-rg", clock.now())
    operation.run_update(target="common-rg", status="completed", conclusion="success", run_id=31,
                         html_url="u", source="relay", now=clock.now())
    assert operation.run_update(target="common-rg", status="in_progress", conclusion=None, run_id=31,
                                html_url="u", source="relay", now=clock.now()) == "ignored"


def test_an_uncertain_confirmation_is_terminal_and_never_retried(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    operation.confirm_uncertain("Factory API timed out", clock.now())
    assert operation.status is Status.UNCERTAIN and operation.is_terminal
    with pytest.raises(InvalidState):
        operation.confirm(operation.steps[0].plan_hash, None, clock.now())


def test_a_rejected_confirmation_fails_the_operation(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    operation.confirm_rejected("revision-mismatch", "The catalog changed.", clock.now())
    assert operation.status is Status.FAILED
    assert operation.steps[0].failure["code"] == "revision-mismatch"


def test_expire_if_due_only_touches_unconfirmed_reviews(clock):
    operation = awaiting(clock, ttl=30)
    assert not operation.expire_if_due(clock.now())
    clock.advance(31)
    assert operation.expire_if_due(clock.now())
    assert operation.status is Status.EXPIRED


def test_terminal_steps_cannot_be_restarted(clock):
    operation = awaiting(clock, can_execute=False, blockers=["x"])
    with pytest.raises(InvalidState):
        operation.review_ready(preview(clock=clock), clock.now())


def test_records_round_trip_without_losing_state(clock):
    operation = awaiting(clock)
    operation.confirm(operation.steps[0].plan_hash, None, clock.now())
    operation.confirm_accepted({"job_id": "j-1"}, ["common-rg"], clock.now())
    restored = Operation.from_record(operation.to_record())
    assert restored.to_public() == operation.to_public()
    assert restored.steps[0].preview.backend_ref == {"confirmation_id": "c-1"}


def test_a_step_the_api_reports_as_not_needed_succeeds_without_a_confirmation(clock):
    operation = new_operation(clock, Step.new("enroll-scaleset", StepKind.ENROLL),
                              Step.new("deploy-common", StepKind.DEPLOY))
    review = preview(clock=clock, can_execute=False, groups=())
    operation.step_not_needed(review, "Blob-coordinated factories need no single-writer enrollment.", clock.now())
    assert operation.steps[0].status is Status.SUCCEEDED and operation.steps[0].plan_hash is None
    assert operation.steps[0].preview is review
    assert operation.current == 1 and operation.status is Status.PREPARING
    assert operation.history[-1]["event"] == "step-not-needed"
    assert operation.to_public()["steps"][0]["preview"]["confirmationToken"] is None
    with pytest.raises(InvalidState):
        operation.step_not_needed(review, "again", clock.now())
