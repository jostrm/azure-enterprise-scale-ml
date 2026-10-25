"""Scenario 2 (add-scaleset) end to end against a fake with pink's catalog semantics, no IDs injected.

Pink's `create-scale-set` adds a draft scale set and no project, and a project has one placement per environment,
so project001 on the new scale set is a new logical project (`add-project`), not a second placement of the existing
one. Without that step, deploy-project001 had no project_id (KeyError, reported as "runner-error").
"""

import pytest

from aif_lifecycle.adapters.rest_backend import RestFactoryBackend, RestTransport
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import InstantTracker
from aif_lifecycle.application.guard import SelfProtection
from aif_lifecycle.application.service import LifecycleService
from aif_lifecycle.domain.errors import ValidationFailed
from aif_lifecycle.domain.operation import Status, StepKind
from aif_lifecycle.domain.scenarios import Scenario
from aif_lifecycle.ports import StepRequest
from aif_lifecycle.settings import RUNNER_TIMEOUT_SECONDS

from fake_factory_api import FACTORY_ID, PROJECT_ID, SCALESET_ID, FakeFactoryApi
from support import run_to_completion, sequential_ids, step_names

FOLDER = r"C:\repos\azure-enterprise-scale-byor-121\azurefactory"
SCALE_SET = {"subscriptionId": "f0fe8b33-73bf-41e4-9997-e3920d793c06", "tenantId": "c157e61b-4a1e-488c-9a0c-d9a23e864a65",
             "orchestrator": "gha", "vnetCidr": "10.121.64.0/18", "maxProjects": 7}


def api_service(api, clock):
    backend = RestFactoryBackend(RestTransport(api.url, api.api_key), FOLDER)
    return LifecycleService(backend=backend, tracker=InstantTracker(), store=MemoryStore(), guard=SelfProtection(()),
                            clock=clock, ids=sequential_ids(), github_repository="jostrm/byor",
                            runner_timeout_seconds=RUNNER_TIMEOUT_SECONDS)


def prepares(api):
    return [call["body"] for call in api.calls if call["path"] == "/api/v1/factory-catalog/prepare"]


def test_scenario_2_places_a_new_project001_on_the_new_scale_set_before_deploying_it(clock):
    with FakeFactoryApi(stateful=True) as api:
        service = api_service(api, clock)
        operation = run_to_completion(service, service.prepare(
            "add-scaleset", {"scalesetId": "aif-121-sdc-dev-002", "scaleSet": SCALE_SET}))
        factory = api.state.factory
        bodies = prepares(api)

    assert operation.status is Status.SUCCEEDED, operation.to_public()
    assert step_names(operation) == ["configure", "deploy-common", "add-project001", "deploy-project001"]
    new_scale = next(s for s in factory["scale_sets"] if s["suffix"] == "002")
    placed = [p for p in factory["projects"] if p["number"] == "001"]
    # The bootstrap's project001 keeps its one dev placement; the new scale set gets its own logical project001.
    assert [p["placements"] for p in placed] == [[{"environment": "dev", "scale_set_id": SCALESET_ID}],
                                                 [{"environment": "dev", "scale_set_id": new_scale["id"]}]]
    new_project = placed[1]
    assert new_project["id"] != PROJECT_ID and new_project["key"] != placed[0]["key"]

    assert [body["action"] for body in bodies] == ["create-scale-set", "deploy", "add-project", "deploy"]
    assert bodies[1]["scale_set_id"] == new_scale["id"] and "project_id" not in bodies[1]  # common only
    assert bodies[2]["project"] == {"number": "001", "display_name": "Project 001",
                                    "placements": [{"environment": "dev", "scale_set_id": new_scale["id"]}]}
    assert (bodies[3]["scale_set_id"], bodies[3]["project_id"]) == (new_scale["id"], new_project["id"])
    assert operation.resolved["project_id"] == new_project["id"]


def test_a_project_deploy_without_a_placed_project_is_refused_clearly_not_with_a_key_error():
    request = StepRequest(operation_id="00000000-0000-0000-0000-000000000001", scenario=Scenario.ADD_SCALESET,
                          step_index=3, step_name="deploy-project001", kind=StepKind.DEPLOY,
                          target="aif-121-sdc-dev-002", resolved={"factory_id": FACTORY_ID, "scale_set_id": SCALESET_ID,
                                                                  "environment": "dev", "project_number": "001"},
                          settings={}, options={})
    with FakeFactoryApi(stateful=True) as api, pytest.raises(ValidationFailed, match="project 001"):
        RestFactoryBackend(RestTransport(api.url, api.api_key), FOLDER).prepare(request)
