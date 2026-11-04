"""Trackers that observe work the Factory API started itself."""

import pytest

from aif_lifecycle.adapters.trackers import ApiJobTracker
from aif_lifecycle.domain.operation import Operation, Preview, Status, Step, StepKind
from aif_lifecycle.domain.scenarios import Scenario


class FakeJobs:
    def __init__(self, status):
        self.status = status
        self.asked = []

    def job_status(self, job):
        self.asked.append(job)
        return {"status": self.status}


def running(clock):
    operation = Operation.create(operation_id="00000000-0000-0000-0000-000000000007", scenario=Scenario.DELETE_SCALESET,
                                 target="aif-121-sdc-dev-002", settings={}, steps=[Step.new("delete-scaleset", StepKind.DELETE)],
                                 backend="rest", executor="inprocess", now=clock.now())
    operation.review_ready(Preview(plan=[], affected_resource_groups=[], blockers=[], can_execute=True,
                                   expires_at=clock.now().timestamp() + 600, confirmation_phrase="DELETE x"), clock.now())
    operation.confirm(operation.steps[0].plan_hash, "DELETE x", clock.now())
    operation.confirm_accepted({"kind": "job", "job_id": "j-9"}, ["api-job-j-9"], clock.now())
    return operation


@pytest.mark.parametrize("api_status, status, conclusion", [
    ("queued", "queued", None), ("running", "in_progress", None), ("succeeded", "completed", "success"),
    ("failed", "completed", "failure"), ("interrupted", "completed", "failure"),
])
def test_api_job_status_maps_to_run_states(clock, api_status, status, conclusion):
    jobs = FakeJobs(api_status)
    tracker = ApiJobTracker(jobs)
    operation = running(clock)
    tracker.advance(operation, clock.now())
    observed = tracker.poll(operation, operation.step.runs[0], clock.now())
    assert (observed["status"], observed["conclusion"]) == (status, conclusion)
    assert jobs.asked == [{"kind": "job", "job_id": "j-9"}]


def test_an_unknown_api_status_is_not_an_observation(clock):
    tracker = ApiJobTracker(FakeJobs("mystery"))
    operation = running(clock)
    assert tracker.poll(operation, operation.step.runs[0], clock.now()) is None
    assert operation.status is Status.RUNNING
