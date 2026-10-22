"""AIF_DELETES=simulate: delete scenarios get their real review, but the Function never confirms one."""

import pytest

from aif_lifecycle.domain import errors
from aif_lifecycle.domain.operation import Status

from support import confirm_current, make_service, run_to_completion

FACTORY = "aif-121-sdc-dev"
SCALESET_2 = "aif-121-sdc-dev-002"


@pytest.fixture
def service(clock):
    return make_service(clock, simulate_deletes=True)


def test_a_simulated_delete_is_reviewed_but_its_confirmation_is_refused(service):
    run_to_completion(service, service.prepare("init-factory", {"factoryId": FACTORY}))
    run_to_completion(service, service.prepare("add-scaleset", {"scalesetId": SCALESET_2}))
    operation = service.prepare("delete-scaleset", {"scalesetId": SCALESET_2})
    assert operation.status is Status.AWAITING_CONFIRMATION and operation.step.preview.affected_resource_groups
    with pytest.raises(errors.DeletesSimulated) as refused:
        confirm_current(service, operation)
    assert (refused.value.status, refused.value.code) == (403, "deletes-simulated")
    unchanged = service.get(operation.id)
    assert unchanged.status is Status.AWAITING_CONFIRMATION and unchanged.steps[0].runs == []


def test_creating_scenarios_still_run_when_deletes_are_simulated(service):
    operation = run_to_completion(service, service.prepare("init-factory", {"factoryId": FACTORY}))
    assert operation.status is Status.SUCCEEDED


def test_health_reports_the_delete_mode(service, clock):
    assert service.health()["deletes"] == "simulate"
    assert make_service(clock).health()["deletes"] == "allow"
