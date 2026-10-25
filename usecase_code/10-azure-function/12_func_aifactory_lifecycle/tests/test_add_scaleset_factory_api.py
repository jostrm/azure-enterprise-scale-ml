"""Scenario 2 (add-scaleset) end to end against a fake with pink's catalog semantics, no IDs injected.

Pink's `create-scale-set` adds a draft scale set and no project, and a project has one placement per environment,
so project001 on the new scale set is a new logical project (`add-project`), not a second placement of the existing
one. Without that step, deploy-project001 had no project_id (KeyError, reported as "runner-error").

A single-writer factory's binding and live enrollment cover only what was enrolled, so the API refuses to deploy the
added scale set until the reviewed `enroll-scale-set` operation extends them. It enrolls only the projects placed on
the scale set when it is prepared, so project001 is placed first: configure -> add-project001 -> enroll-scaleset ->
deploy-common -> deploy-project001. A Blob-coordinated factory has no enrollment to extend: the API blocks its review
with one exact message, and the Function records the step as not needed and continues.
"""

import pytest

from aif_lifecycle.adapters.rest_backend import RestFactoryBackend, RestTransport
from aif_lifecycle.adapters.sdk_backend import SdkFactoryBackend
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import InstantTracker
from aif_lifecycle.application.guard import SelfProtection
from aif_lifecycle.application.service import LifecycleService
from aif_lifecycle.domain.errors import ValidationFailed
from aif_lifecycle.domain.operation import Status, StepKind
from aif_lifecycle.domain.scenarios import Scenario
from aif_lifecycle.ports import StepRequest
from aif_lifecycle.settings import RUNNER_TIMEOUT_SECONDS

from fake_factory_api import (BLOB_BLOCKER, ENROLL_CONFIRM, ENROLL_PREPARE, FACTORY_ID, PROJECT_ID, SCALESET_ID,
                              FakeFactoryApi, group_id)
from support import confirm_current, run_to_completion, sequential_ids, step_names

FOLDER = r"C:\repos\azure-enterprise-scale-byor-121\azurefactory"
SCALE_SET = {"subscriptionId": "f0fe8b33-73bf-41e4-9997-e3920d793c06", "tenantId": "c157e61b-4a1e-488c-9a0c-d9a23e864a65",
             "orchestrator": "gha", "vnetCidr": "10.121.64.0/18", "maxProjects": 7}
STEPS = ["configure", "add-project001", "enroll-scaleset", "deploy-common", "deploy-project001"]
BODY = {"scalesetId": "aif-121-sdc-dev-002", "scaleSet": SCALE_SET}


def backend(option, api):
    if option == "rest":
        return RestFactoryBackend(RestTransport(api.url, api.api_key), FOLDER)
    return SdkFactoryBackend(api.url, api.api_key, FOLDER)


def api_service(api, clock, option="rest"):
    return LifecycleService(backend=backend(option, api), tracker=InstantTracker(), store=MemoryStore(),
                            guard=SelfProtection(()), clock=clock, ids=sequential_ids(),
                            github_repository="jostrm/byor", runner_timeout_seconds=RUNNER_TIMEOUT_SECONDS)


def prepares(api):
    return [call["body"] for call in api.calls if call["path"] == "/api/v1/factory-catalog/prepare"]


def calls(api, path):
    return [call["body"] for call in api.calls if call["path"] == path]


@pytest.mark.parametrize("option", ["rest", "sdk"])
def test_scenario_2_places_project001_enrolls_the_scale_set_then_deploys_it(clock, option):
    with FakeFactoryApi(stateful=True) as api:
        service = api_service(api, clock, option)
        operation = run_to_completion(service, service.prepare("add-scaleset", BODY))
        factory = api.state.factory
        bodies = prepares(api)
        enroll_prepares, enroll_confirms = calls(api, ENROLL_PREPARE), calls(api, ENROLL_CONFIRM)

    assert operation.status is Status.SUCCEEDED, operation.to_public()
    assert step_names(operation) == STEPS
    new_scale = next(s for s in factory["scale_sets"] if s["suffix"] == "002")
    placed = [p for p in factory["projects"] if p["number"] == "001"]
    # The bootstrap's project001 keeps its one dev placement; the new scale set gets its own logical project001.
    assert [p["placements"] for p in placed] == [[{"environment": "dev", "scale_set_id": SCALESET_ID}],
                                                 [{"environment": "dev", "scale_set_id": new_scale["id"]}]]
    new_project = placed[1]
    assert new_project["id"] != PROJECT_ID and new_project["key"] != placed[0]["key"]

    # add-project001 is configuration only and needs no deployed common part: it names the new scale set explicitly.
    assert [body["action"] for body in bodies] == ["create-scale-set", "add-project", "deploy", "deploy"]
    assert bodies[1]["project"] == {"number": "001", "display_name": "Project 001",
                                    "placements": [{"environment": "dev", "scale_set_id": new_scale["id"]}]}
    assert enroll_prepares == [{"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY_ID,
                                "scale_set_id": new_scale["id"]}]
    review = operation.steps[2].preview
    assert review.affected_resource_groups == [group_id("aif-121-esml-common-sdc-dev-002"),
                                               group_id("aif-121-esml-project001-sdc-dev-002-rg")]
    assert review.confirmation_phrase == "ENROLL SCALE SET aif-121 002"
    assert enroll_confirms == [{"contract_version": 1, "folder": FOLDER,
                                "confirmation_id": review.backend_ref["confirmation_id"], "preview_hash": "e" * 64,
                                "confirmation_phrase": "ENROLL SCALE SET aif-121 002"}]
    assert operation.steps[2].job["status"] == "enrolled"
    assert bodies[2]["scale_set_id"] == new_scale["id"] and "project_id" not in bodies[2]  # common only
    assert (bodies[3]["scale_set_id"], bodies[3]["project_id"]) == (new_scale["id"], new_project["id"])
    assert operation.resolved["project_id"] == new_project["id"]


def test_the_enrollment_review_is_confirmed_like_every_other_step_with_its_phrase(clock):
    with FakeFactoryApi(stateful=True) as api:
        service = api_service(api, clock)
        operation = service.prepare("add-scaleset", BODY)
        operation = confirm_current(service, confirm_current(service, operation))
        view = operation.to_public()["steps"][2]
        assert (view["name"], view["kind"], view["status"]) == ("enroll-scaleset", "enroll", "awaiting_confirmation")
        assert view["preview"]["confirmationPhrase"] == "ENROLL SCALE SET aif-121 002"
        assert view["preview"]["canExecute"] and view["preview"]["confirmationToken"]
        assert any("Contributor" in line or "role" in line.lower() for line in view["preview"]["plan"])
        with pytest.raises(ValidationFailed) as wrong:
            service.confirm(operation.id, {"confirmationToken": view["preview"]["confirmationToken"],
                                           "confirmationPhrase": "ENROLL SCALE SET aif-121 001"})
        assert wrong.value.code == "confirmation-phrase-mismatch"
        assert calls(api, ENROLL_CONFIRM) == []


def test_without_the_enrollment_the_single_writer_api_refuses_the_common_deploy():
    request = StepRequest(operation_id="00000000-0000-0000-0000-000000000001", scenario=Scenario.ADD_SCALESET,
                          step_index=3, step_name="deploy-common", kind=StepKind.DEPLOY, target="aif-121-sdc-dev-002",
                          resolved={"factory_id": FACTORY_ID, "scale_set_id": "x", "environment": "dev"},
                          settings={}, options={})
    with FakeFactoryApi(stateful=True) as api:
        api.state.factory["scale_sets"].append({"id": "x", "environment": "dev", "suffix": "002", "status": "draft"})
        with pytest.raises(Exception, match="do not cover aif-121-esml-common-sdc-dev-002"):
            backend("rest", api).prepare(request)


@pytest.mark.parametrize("option", ["rest", "sdk"])
def test_a_blob_coordinated_factory_needs_no_enrollment_and_keeps_working(clock, option):
    with FakeFactoryApi(stateful=True, coordination="blob") as api:
        service = api_service(api, clock, option)
        operation = run_to_completion(service, service.prepare("add-scaleset", BODY))
        confirms = calls(api, ENROLL_CONFIRM)

    assert operation.status is Status.SUCCEEDED, operation.to_public()
    assert step_names(operation) == STEPS
    enroll = operation.to_public()["steps"][2]
    assert enroll["status"] == "succeeded" and enroll["preview"]["confirmationToken"] is None
    assert any(BLOB_BLOCKER in line for line in enroll["preview"]["plan"])
    assert confirms == []
    assert any(item["event"] == "step-not-needed" for item in operation.history)


@pytest.mark.parametrize("option", ["rest", "sdk"])
def test_any_other_enrollment_blocker_stops_the_operation_with_the_blocker_shown(clock, option):
    blocker = "Scale-set enrollment blocked: the saved binding is not the live single-writer enrollment."
    with FakeFactoryApi(stateful=True, enroll_blockers=[blocker]) as api:
        service = api_service(api, clock, option)
        operation = run_to_completion(service, service.prepare("add-scaleset", BODY))

    assert operation.status is Status.BLOCKED and operation.step.name == "enroll-scaleset"
    assert operation.to_public()["steps"][2]["preview"]["blockers"] == [blocker]


@pytest.mark.parametrize("option", ["rest", "sdk"])
def test_an_api_without_the_operation_is_reported_as_too_old(clock, option):
    with FakeFactoryApi(stateful=True, enroll_routes=False) as api:
        service = api_service(api, clock, option)
        operation = run_to_completion(service, service.prepare("add-scaleset", BODY))

    assert operation.status is Status.FAILED and operation.step.name == "enroll-scaleset"
    assert operation.step.failure["code"] == "factory-api-too-old"
    assert "Factory API too old for enroll-scale-set" in operation.step.failure["detail"]


def test_a_review_for_another_scale_set_suffix_is_refused_before_it_can_be_confirmed(clock, monkeypatch):
    with FakeFactoryApi(stateful=True) as api:
        original = api.state.enroll_prepare
        monkeypatch.setattr(api.state, "enroll_prepare",
                            lambda body: {**original(body), "confirmation_phrase": "ENROLL SCALE SET aif-121 003"})
        service = api_service(api, clock)
        operation = run_to_completion(service, service.prepare("add-scaleset", BODY))

    assert operation.status is Status.FAILED and operation.step.name == "enroll-scaleset"
    assert "confirmation phrase" in operation.step.failure["detail"]


def test_a_project_deploy_without_a_placed_project_is_refused_clearly_not_with_a_key_error():
    request = StepRequest(operation_id="00000000-0000-0000-0000-000000000001", scenario=Scenario.ADD_SCALESET,
                          step_index=4, step_name="deploy-project001", kind=StepKind.DEPLOY,
                          target="aif-121-sdc-dev-002", resolved={"factory_id": FACTORY_ID, "scale_set_id": SCALESET_ID,
                                                                  "environment": "dev", "project_number": "001"},
                          settings={}, options={})
    with FakeFactoryApi(stateful=True) as api, pytest.raises(ValidationFailed, match="project 001"):
        RestFactoryBackend(RestTransport(api.url, api.api_key), FOLDER).prepare(request)
