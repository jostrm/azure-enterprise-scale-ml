"""The six scenarios end to end against the persistent mock catalog (in-process executor)."""

import pytest

from aif_lifecycle.domain import errors
from aif_lifecycle.domain.operation import Status

from support import confirm_current, make_service, run_to_completion, step_names

FACTORY = "aif-121-sdc-dev"
SCALESET_2 = "aif-121-sdc-dev-002"
PROJECT_2 = "aif-121-esml-project002-sdc-dev-001-rg"


@pytest.fixture
def service(clock):
    return make_service(clock)


def init_factory(service, **body):
    return run_to_completion(service, service.prepare("init-factory", {"factoryId": FACTORY, **body}))


def test_scenario_1_creates_connectivity_common_and_project001_with_one_review_per_stage(service):
    operation = service.prepare("init-factory", {"factoryId": FACTORY})
    assert step_names(operation) == ["configure", "deploy-connectivity", "deploy-common", "deploy-project001"]
    assert operation.status is Status.AWAITING_CONFIRMATION
    operation = confirm_current(service, operation)
    assert operation.current == 1 and operation.status is Status.AWAITING_CONFIRMATION
    operation = run_to_completion(service, operation)
    assert operation.status is Status.SUCCEEDED
    groups = [run.target for step in operation.steps for run in step.runs]
    assert groups == ["aif-121-connectivity-sdc-dev", "aif-121-esml-common-sdc-dev-001",
                      "aif-121-esml-project001-sdc-dev-001-rg"]


def test_scenario_1_whole_workflow_mirrors_bounded_bootstrap_approval(service):
    operation = service.prepare("init-factory", {"factoryId": FACTORY, "wholeWorkflow": True})
    assert step_names(operation) == ["configure", "bootstrap"]
    operation = run_to_completion(service, operation)
    assert operation.status is Status.SUCCEEDED
    assert [run.target for run in operation.steps[1].runs][0] == "aif-121-connectivity-sdc-dev"


def test_add_then_409_then_delete_then_404_behaves_sensibly(service):
    init_factory(service)
    with pytest.raises(errors.AlreadyExists):
        service.prepare("init-factory", {"factoryId": FACTORY})

    added = run_to_completion(service, service.prepare("add-scaleset", {"scalesetId": SCALESET_2}))
    assert step_names(added) == ["configure", "deploy-common", "deploy-project001"]
    assert added.status is Status.SUCCEEDED
    with pytest.raises(errors.AlreadyExists):
        service.prepare("add-scaleset", {"scalesetId": SCALESET_2})

    deleted = run_to_completion(service, service.prepare("delete-scaleset", {"scalesetId": SCALESET_2}))
    assert deleted.status is Status.SUCCEEDED
    assert [run.target for run in deleted.steps[0].runs] == ["aif-121-esml-project001-sdc-dev-002-rg",
                                                             "aif-121-esml-common-sdc-dev-002"]
    with pytest.raises(errors.UnknownId):
        service.prepare("delete-scaleset", {"scalesetId": SCALESET_2})


def test_scenario_3_adds_a_new_project_number_and_updates_an_existing_one(service):
    init_factory(service)
    added = service.prepare("add-or-update-project", {"projectId": PROJECT_2})
    assert added.steps[0].preview.backend_ref["action"] == "add-project"
    assert run_to_completion(service, added).status is Status.SUCCEEDED

    updated = service.prepare("add-or-update-project", {"projectId": PROJECT_2, "settings": {"enableAISearch": "true"}})
    assert updated.steps[0].preview.backend_ref["action"] == "configure-settings"
    assert step_names(updated) == ["configure", "deploy-project"]
    assert run_to_completion(service, updated).status is Status.SUCCEEDED


def test_scenario_4_deletes_one_project_after_the_exact_phrase(service):
    init_factory(service)
    run_to_completion(service, service.prepare("add-or-update-project", {"projectId": PROJECT_2}))
    operation = service.prepare("delete-project", {"projectId": PROJECT_2})
    preview = operation.to_public()["steps"][0]["preview"]
    assert preview["confirmationPhrase"] == f"DELETE {PROJECT_2}"
    with pytest.raises(errors.ValidationFailed):
        service.confirm(operation.id, {"confirmationToken": preview["confirmationToken"]})
    operation = confirm_current(service, operation)
    assert operation.status is Status.SUCCEEDED
    with pytest.raises(errors.UnknownId):
        service.prepare("delete-project", {"projectId": PROJECT_2})


def test_scenario_6_deletes_all_scale_sets_of_a_single_environment_factory(service):
    init_factory(service)
    run_to_completion(service, service.prepare("add-scaleset", {"scalesetId": SCALESET_2}))
    operation = service.prepare("delete-factory", {"factoryId": FACTORY})
    assert operation.to_public()["steps"][0]["preview"]["confirmationPhrase"] == "DELETE aif-121-swedencentral"
    operation = confirm_current(service, operation)
    assert operation.status is Status.SUCCEEDED
    assert operation.steps[0].runs[-1].target == "aif-121-esml-common-sdc-dev-002"
    with pytest.raises(errors.UnknownId):
        service.prepare("delete-factory", {"factoryId": FACTORY})


def test_scenario_6_refuses_a_factory_that_spans_other_environments(service):
    init_factory(service)
    run_to_completion(service, service.prepare("add-scaleset", {"scalesetId": "aif-121-sdc-test-001"}))
    with pytest.raises(errors.ScopeNotSupported) as error:
        service.prepare("delete-factory", {"factoryId": FACTORY})
    assert error.value.extra["environments"] == ["dev", "stage"]


def test_unknown_parents_are_404(service):
    with pytest.raises(errors.UnknownId):
        service.prepare("add-scaleset", {"scalesetId": SCALESET_2})
    with pytest.raises(errors.UnknownId):
        service.prepare("add-or-update-project", {"projectId": PROJECT_2})


def test_the_functions_own_scope_and_the_management_runner_are_protected(clock):
    service = make_service(clock, protected=["spider-esml-project001-sdc-dev-001-rg", "spider-sdc-dev-001"])
    for scenario, body in [("delete-factory", {"factoryId": "spider-sdc-dev"}),
                           ("delete-scaleset", {"scalesetId": "spider-sdc-dev-001"}),
                           ("add-or-update-project", {"projectId": "spider-esml-project001-sdc-dev-001-rg"}),
                           ("delete-project", {"projectId": "spider-esml-project001-sdc-dev-001-rg"})]:
        with pytest.raises(errors.ProtectedTarget):
            service.prepare(scenario, body)
    with pytest.raises(errors.UnknownId):
        service.prepare("delete-project", {"projectId": "spider-esml-project002-sdc-dev-001-rg"})


def test_a_second_operation_on_a_busy_target_is_in_progress_until_the_first_ends(service, clock):
    init_factory(service)
    first = service.prepare("add-scaleset", {"scalesetId": SCALESET_2})
    with pytest.raises(errors.InProgress):
        service.prepare("add-scaleset", {"scalesetId": SCALESET_2})
    clock.advance(601)
    service.reconcile()
    assert service.get(first.id).status is Status.EXPIRED
    assert service.prepare("add-scaleset", {"scalesetId": SCALESET_2}).status is Status.AWAITING_CONFIRMATION


def test_an_expired_review_is_410_and_the_operation_records_it(service, clock):
    operation = service.prepare("init-factory", {"factoryId": FACTORY})
    clock.advance(601)
    with pytest.raises(errors.ConfirmationExpired):
        confirm_current(service, operation)
    assert service.get(operation.id).status is Status.EXPIRED


def test_a_failed_stage_stops_the_chain_with_the_failure(service):
    operation = init_factory(service, simulate={"failAt": "deploy-common"})
    assert operation.status is Status.FAILED
    failed = operation.steps[2]
    assert failed.name == "deploy-common" and failed.failure["target"] == "aif-121-esml-common-sdc-dev-001"
    assert operation.steps[3].status is Status.PENDING


def test_an_uncertain_confirm_is_never_retried(service):
    operation = init_factory(service, simulate={"uncertainAt": "deploy-common"})
    assert operation.status is Status.UNCERTAIN
    with pytest.raises(errors.InvalidState):
        service.confirm(operation.id, {"confirmationToken": "x"})


@pytest.mark.parametrize("scenario, body, error", [
    ("init-factory", {}, errors.ValidationFailed),
    ("init-factory", {"factoryId": "AIF-121"}, errors.InvalidId),
    ("rebuild", {"factoryId": FACTORY}, errors.ValidationFailed),
    ("add-or-update-project", {"projectId": PROJECT_2, "settings": "not-an-object"}, errors.ValidationFailed),
])
def test_bad_requests_are_400(service, scenario, body, error):
    with pytest.raises(error):
        service.prepare(scenario, body)


def test_unknown_operation_is_404(service):
    with pytest.raises(errors.OperationNotFound):
        service.get("00000000-0000-0000-0000-00000000dead")


def test_operations_are_listed_newest_first(service, clock):
    first = service.prepare("init-factory", {"factoryId": FACTORY})
    clock.advance(1)
    second = service.prepare("init-factory", {"factoryId": "aif-122-sdc-dev"})
    assert [item.id for item in service.list()] == [second.id, first.id]
