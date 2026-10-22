"""Real deletes need an explicit opt-in; AIF_DELETES=simulate runs scenarios 4-6 on the mock and dummy workflows.

A Function next to a real factory must never delete anything (decided 2026-10-22): the real REST, SDK and runner
executors refuse every delete prepare and confirm unless AIF_DELETES=allow, and a simulated delete never calls the
real Factory API, not even for its review.
"""

import json

import pytest

from aif_lifecycle.adapters.mock_backend import MockFactoryBackend
from aif_lifecycle.adapters.rest_backend import RestFactoryBackend, RestTransport
from aif_lifecycle.adapters.runner_backend import RunnerBackend
from aif_lifecycle.adapters.sdk_backend import SdkFactoryBackend
from aif_lifecycle.adapters.simulated_deletes import CatalogMirror, DeleteRoutingTracker, DeleteSimulation
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import ApiJobTracker, DummyWorkflowTracker, RunnerJobTracker
from aif_lifecycle.application.guard import SelfProtection
from aif_lifecycle.application.service import LifecycleService
from aif_lifecycle.domain.errors import DeletesDisabled
from aif_lifecycle.domain.operation import Preview, Status, StepKind
from aif_lifecycle.domain.scenarios import Scenario
from aif_lifecycle.http_api import ApiRequest, LifecycleHttpApi
from aif_lifecycle.ports import StepRequest
from aif_lifecycle.signatures import sign

from fake_factory_api import FACTORY_ID, PROJECT_ID, SCALESET_ID, FakeFactoryApi
from support import FakeGitHub, confirm_current, sequential_ids

FOLDER = r"C:\repos\azure-enterprise-scale-byor-121\azurefactory"
SECRET = b"relay-secret"
PROJECT = "aif-121-esml-project001-sdc-dev-001-rg"
IDS = {"factory_id": FACTORY_ID, "factory_key": "aif-121-swedencentral", "scale_set_id": SCALESET_ID,
       "environment": "dev"}


def delete_step(scenario, name, target, resolved):
    return StepRequest(operation_id="00000000-0000-4000-8000-000000000001", scenario=scenario, step_index=0,
                       step_name=name, kind=StepKind.DELETE, target=target, resolved=resolved, settings={}, options={})


DELETES = [
    delete_step(Scenario.DELETE_PROJECT, "delete-project", PROJECT,
                {**IDS, "project_id": PROJECT_ID, "include_project_subnets": True,
                 "include_keyvault_and_resource_group": True}),
    delete_step(Scenario.DELETE_SCALESET, "delete-scaleset", "aif-121-sdc-dev-001", IDS),
    delete_step(Scenario.DELETE_FACTORY, "delete-factory", "aif-121-sdc-dev", IDS),
]
REVIEW = Preview(plan=["Delete"], affected_resource_groups=[PROJECT], blockers=[], can_execute=True, expires_at=0.0,
                 backend_ref={"confirmation_id": "66666666-6666-4666-8666-666666666666"})


def real_backend(option, api, **options):
    if option == "rest":
        return RestFactoryBackend(RestTransport(api.url, api.api_key), FOLDER, **options)
    return SdkFactoryBackend(api.url, api.api_key, FOLDER, **options)


@pytest.mark.parametrize("option", ["rest", "sdk"])
@pytest.mark.parametrize("request_", DELETES, ids=lambda request_: request_.step_name)
def test_the_real_rest_and_sdk_backends_refuse_every_delete_by_default(option, request_):
    with FakeFactoryApi() as api:
        backend = real_backend(option, api)
        with pytest.raises(DeletesDisabled):
            backend.prepare(request_)
        with pytest.raises(DeletesDisabled):
            backend.confirm(request_, REVIEW, "DELETE aif-121-swedencentral")
    assert backend.delete_mode == "refuse"
    assert not [call for call in api.calls if call["method"] == "POST"], "a refused delete never reaches the API"


def test_an_explicit_opt_in_lets_the_real_backends_delete():
    with FakeFactoryApi() as api:
        backend = real_backend("rest", api, allow_deletes=True)
        backend.prepare(DELETES[0])
    assert backend.delete_mode == "allow"
    assert "/api/v1/factory-catalog/prepare" in [call["path"] for call in api.calls]


def runner_backend(clock, github, store=None):
    return RunnerBackend(github, store or MemoryStore(), clock, workflow="aif-ops.yml", ref="main", backend="rest",
                         secret=SECRET, request_ttl_seconds=900)


def test_the_runner_executor_refuses_deletes_without_dispatching_anything(clock):
    github = FakeGitHub()
    backend = runner_backend(clock, github)
    for request_ in DELETES:
        with pytest.raises(DeletesDisabled):
            backend.prepare(request_)
        with pytest.raises(DeletesDisabled):
            backend.confirm(request_, REVIEW, None)
    assert github.dispatches == [] and backend.delete_mode == "refuse"


def test_a_refused_delete_is_a_403_problem_before_any_operation_or_dispatch_exists(clock):
    github, store = FakeGitHub(), MemoryStore()
    backend = runner_backend(clock, github, store)
    service = LifecycleService(backend=backend, tracker=RunnerJobTracker(backend, github), store=store,
                               guard=SelfProtection([]), clock=clock, ids=sequential_ids())
    api = LifecycleHttpApi(service, event_secrets=[SECRET])
    response = api.prepare(ApiRequest(method="POST", path="/api/v1/lifecycle/delete-project/prepare",
                                      route_params={"scenario": "delete-project"}, headers={},
                                      body=json.dumps({"projectId": PROJECT}).encode()))
    problem = json.loads(response.body)
    assert response.status == 403 and problem["code"] == "deletes-disabled"
    assert response.headers["Content-Type"] == "application/problem+json"
    assert service.list() == [] and github.dispatches == []
    assert service.health()["deletes"] == "refuse"


def test_a_simulated_delete_runs_end_to_end_on_the_mock_and_a_dummy_workflow_without_calling_the_api(clock):
    github, store = FakeGitHub(), MemoryStore()
    with FakeFactoryApi() as api:
        real = real_backend("rest", api)
        backend = DeleteSimulation(real, MockFactoryBackend(CatalogMirror(real.catalog_payload), clock=clock,
                                                            ids=sequential_ids()))
        tracker = DeleteRoutingTracker(ApiJobTracker(real), DummyWorkflowTracker(
            github, workflow="aif-dummy-step.yml", ref="main", duration_seconds=60))
        service = LifecycleService(backend=backend, tracker=tracker, store=store, guard=SelfProtection([]),
                                   clock=clock, ids=sequential_ids())
        http = LifecycleHttpApi(service, event_secrets=[SECRET])
        operation = service.prepare("delete-project", {"projectId": PROJECT})
        assert operation.status is Status.AWAITING_CONFIRMATION
        assert operation.step.preview.plan[0].startswith("Simulated")
        assert operation.step.preview.affected_resource_groups == [PROJECT]
        assert service.health()["deletes"] == "simulate"
        confirm_current(service, operation)
        assert [(item["workflow"], item["inputs"]["target"]) for item in github.dispatches] == [
            ("aif-dummy-step.yml", PROJECT)]
        raw = json.dumps(github.complete(0)).encode()
        response = http.github_events(ApiRequest(method="POST", path="/api/v1/github/events", route_params={},
                                                 headers={"x-hub-signature-256": sign(SECRET, raw),
                                                          "x-github-delivery": "d-1", "x-github-event": "workflow_run"},
                                                 body=raw))
        assert response.status == 202
        assert service.get(operation.id).status is Status.SUCCEEDED
    posts = [call["path"] for call in api.calls if call["method"] == "POST"]
    assert posts == [], "the simulation never sends a delete prepare or confirm to the Factory API"


def test_a_simulated_delete_factory_still_asks_for_the_exact_phrase(clock):
    with FakeFactoryApi() as api:
        real = real_backend("sdk", api)
        simulator = MockFactoryBackend(CatalogMirror(real.catalog_payload), clock=clock, ids=sequential_ids())
        preview = DeleteSimulation(real, simulator).prepare(DELETES[2])
    assert preview.confirmation_phrase == "DELETE aif-121-swedencentral"
    assert preview.affected_resource_groups == [PROJECT, "aif-121-esml-common-sdc-dev-001"]
    assert not [call for call in api.calls if call["method"] == "POST"]
