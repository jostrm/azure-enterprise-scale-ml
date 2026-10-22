"""Option 1 (REST) and option 2 (SDK) must make exactly the same Factory API calls for every scenario."""

import pytest

from aif_lifecycle.adapters.factory_api import WHOLE_WORKFLOW_SECONDS, job_observation
from aif_lifecycle.adapters.rest_backend import RestFactoryBackend, RestTransport
from aif_lifecycle.adapters.sdk_backend import SdkFactoryBackend
from aif_lifecycle.domain.errors import ValidationFailed
from aif_lifecycle.domain.operation import StepKind
from aif_lifecycle.domain.scenarios import Scenario
from aif_lifecycle.ports import StepRequest

from fake_factory_api import (AUTHORIZATION_HASH, CONFIRMATION_ID, FACTORY_ID, JOB_ID, PROJECT_ID, SCALESET_ID,
                              WORKFLOW_ID, FakeFactoryApi)

REPO = r"C:\repos\azure-enterprise-scale-byor-121"
FOLDER = REPO + r"\azurefactory"
BOOTSTRAP = {"subscription_id": "f0fe8b33-73bf-41e4-9997-e3920d793c06", "tenant_id": "c157e61b-4a1e-488c-9a0c-d9a23e864a65",
             "team_member_email": "owner@example.com", "team_group_name": "aif-121-team",
             "github_repository": "jostrm/azure-enterprise-scale-byor-121", "coordination_mode": "single-writer"}
SAVED_CONFIG = {**BOOTSTRAP, "factory_prefix": "aif-121-", "location": "swedencentral", "scale_set_number": "001"}
SCALE_SET = {"subscriptionId": "f0fe8b33-73bf-41e4-9997-e3920d793c06", "tenantId": "c157e61b-4a1e-488c-9a0c-d9a23e864a65",
             "orchestrator": "gha", "vnetCidr": "10.121.0.0/18", "maxProjects": 7}
IDS = {"factory_id": FACTORY_ID, "factory_key": "aif-121-swedencentral", "scale_set_id": SCALESET_ID,
       "environment": "dev"}


def step(scenario, name, kind, target, resolved, *, settings=None, options=None, phrase=None):
    return StepRequest(operation_id="00000000-0000-0000-0000-000000000001", scenario=scenario, step_index=0,
                       step_name=name, kind=kind, target=target, resolved=resolved, settings=settings or {},
                       options=options or {}), phrase


SCENARIOS = {
    "1-init-factory": [
        step(Scenario.INIT_FACTORY, "configure", StepKind.CONFIGURE, "aif-121-sdc-dev",
             {"prefix": "aif-121-", "region": "swedencentral", "region_code": "sdc", "environment": "dev",
              "suffix": "001", "project_number": "001"}, options={"bootstrapConfig": BOOTSTRAP}),
        step(Scenario.INIT_FACTORY, "bootstrap", StepKind.BOOTSTRAP, "aif-121-sdc-dev",
             {**IDS, "project_id": PROJECT_ID, "prefix": "aif-121-", "region": "swedencentral", "suffix": "001"},
             options={"bootstrapConfig": BOOTSTRAP, "wholeWorkflow": True}),
    ],
    "2-add-scaleset": [
        step(Scenario.ADD_SCALESET, "configure", StepKind.CONFIGURE, "aif-121-sdc-dev-002",
             {"factory_id": FACTORY_ID, "environment": "dev", "suffix": "002", "project_number": "001"},
             options={"scaleSet": SCALE_SET}),
        step(Scenario.ADD_SCALESET, "deploy-common", StepKind.DEPLOY, "aif-121-sdc-dev-002", IDS),
        step(Scenario.ADD_SCALESET, "deploy-project001", StepKind.DEPLOY, "aif-121-sdc-dev-002",
             {**IDS, "project_id": PROJECT_ID}),
    ],
    "3-add-project": [
        step(Scenario.ADD_OR_UPDATE_PROJECT, "configure", StepKind.CONFIGURE, "aif-121-esml-project002-sdc-dev-001-rg",
             {**IDS, "project_number": "002", "mode": "add"}, settings={"enableAISearch": "true"}),
        step(Scenario.ADD_OR_UPDATE_PROJECT, "deploy-project", StepKind.DEPLOY, "aif-121-esml-project002-sdc-dev-001-rg",
             {**IDS, "project_id": PROJECT_ID}),
    ],
    "3-update-project": [
        step(Scenario.ADD_OR_UPDATE_PROJECT, "configure", StepKind.CONFIGURE, "aif-121-esml-project001-sdc-dev-001-rg",
             {**IDS, "project_number": "001", "project_id": PROJECT_ID, "mode": "update"},
             settings={"enableAISearch": "false"}),
    ],
    "4-delete-project": [
        step(Scenario.DELETE_PROJECT, "delete-project", StepKind.DELETE, "aif-121-esml-project001-sdc-dev-001-rg",
             {**IDS, "project_id": PROJECT_ID, "include_project_subnets": True,
              "include_keyvault_and_resource_group": True}),
    ],
    "5-delete-scaleset": [
        step(Scenario.DELETE_SCALESET, "delete-scaleset", StepKind.DELETE, "aif-121-sdc-dev-001", IDS),
    ],
    "6-delete-factory": [
        step(Scenario.DELETE_FACTORY, "delete-factory", StepKind.DELETE, "aif-121-sdc-dev",
             {"factory_id": FACTORY_ID, "factory_key": "aif-121-swedencentral", "environment": "dev"},
             phrase="DELETE aif-121-swedencentral"),
    ],
}

EXPECTED_ROUTES = {
    "1-init-factory": ["GET /api/v1/factory-catalog", "POST /api/v1/creation/prepare", "POST /api/v1/creation/confirm",
                       "GET /api/v1/factory-catalog", "POST /api/v1/creation/workflows/prepare",
                       "POST /api/v1/creation/workflows/start"],
    "2-add-scaleset": ["GET /api/v1/factory-catalog", "POST /api/v1/factory-catalog/prepare",
                       "POST /api/v1/factory-catalog/confirm"] * 3,
    "3-add-project": ["GET /api/v1/factory-catalog", "POST /api/v1/factory-catalog/prepare",
                      "POST /api/v1/factory-catalog/confirm"] * 2,
    "3-update-project": ["GET /api/v1/factory-catalog", "POST /api/v1/factory-catalog/prepare",
                         "POST /api/v1/factory-catalog/confirm"],
    "4-delete-project": ["GET /api/v1/factory-catalog", "POST /api/v1/factory-catalog/prepare",
                         "POST /api/v1/factory-catalog/confirm"],
    "5-delete-scaleset": ["GET /api/v1/factory-catalog", "POST /api/v1/factory-catalog/prepare",
                          "POST /api/v1/factory-catalog/confirm"],
    "6-delete-factory": ["GET /api/v1/factory-catalog", "POST /api/v1/operations/delete-aifactory/prepare",
                         "POST /api/v1/operations/delete-aifactory/confirm"],
}


def backend_for(option, api):
    if option == "rest":
        return RestFactoryBackend(RestTransport(api.url, api.api_key), FOLDER)
    return SdkFactoryBackend(api.url, api.api_key, FOLDER)


def record(option, steps):
    with FakeFactoryApi() as api:
        backend = backend_for(option, api)
        for request, phrase in steps:
            preview = backend.prepare(request)
            backend.confirm(request, preview, phrase)
        backend.job_status({"kind": "job", "job_id": JOB_ID})
        backend.job_status({"kind": "workflow", "workflow_id": WORKFLOW_ID})
        return api.calls


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_rest_and_sdk_make_the_same_calls(scenario):
    rest, sdk = record("rest", SCENARIOS[scenario]), record("sdk", SCENARIOS[scenario])
    assert rest == sdk
    routes = [f"{call['method']} {call['path']}" for call in rest]
    assert routes[:-2] == EXPECTED_ROUTES[scenario]
    assert routes[-2:] == [f"GET /api/v1/factory-catalog/jobs/{JOB_ID}", f"GET /api/v1/creation/workflows/{WORKFLOW_ID}"]
    assert all(call["key"] for call in rest if call["path"] != "/openapi.json")


def test_bodies_carry_the_catalog_ids_revision_and_explicit_delete_options():
    calls = record("rest", SCENARIOS["4-delete-project"])
    prepare = calls[1]["body"]
    assert prepare == {"folder": FOLDER, "contract_version": 1, "action": "delete-project", "factory_id": FACTORY_ID,
                       "expected_revision": "a" * 64, "project_id": PROJECT_ID, "scale_set_id": SCALESET_ID,
                       "deletion_options": {"environments": ["dev"], "include_project_subnets": True,
                                            "include_keyvault_and_resource_group": True}}
    assert calls[2]["body"] == {"folder": FOLDER, "contract_version": 1,
                                "confirmation_id": "66666666-6666-4666-8666-666666666666"}


def test_init_factory_saves_through_creation_and_starts_one_whole_workflow_approval():
    calls = record("rest", SCENARIOS["1-init-factory"])
    by_route = {f"{call['method']} {call['path']}": call["body"] for call in calls}
    # No expected_revision even though the catalog has one: the API refuses a factory creation that selects an
    # existing scope or revision (observed 2026-10-22 once the consumer folder had a catalog revision).
    assert by_route["POST /api/v1/creation/prepare"] == {
        "contract_version": 1, "mode": "full-bootstrap", "folder": REPO, "orchestrator": "gha",
        "config": SAVED_CONFIG, "region_short_name": "sdc"}
    assert by_route["POST /api/v1/creation/confirm"] == {"contract_version": 1, "folder": REPO,
                                                         "confirmation_id": CONFIRMATION_ID}
    workflow = by_route["POST /api/v1/creation/workflows/prepare"]
    assert workflow["approval_mode"] == "whole-workflow"
    assert workflow["authorization_valid_for_seconds"] == WHOLE_WORKFLOW_SECONDS
    assert workflow["creation_mode"] == "full-bootstrap" and workflow["bootstrap_config"] == SAVED_CONFIG
    assert workflow["scope"] == {"folder": FOLDER, "factory_id": FACTORY_ID, "scale_set_id": SCALESET_ID,
                                 "project_id": PROJECT_ID}
    assert by_route["POST /api/v1/creation/workflows/start"]["authorization_hash"] == AUTHORIZATION_HASH


@pytest.mark.parametrize("name,resolved,message", [
    ("deploy-connectivity", {"prefix": "aif-121-", "region": "swedencentral", "environment": "dev"}, "wholeWorkflow"),
])
def test_init_factory_without_one_whole_workflow_approval_is_refused(name, resolved, message):
    request, _ = step(Scenario.INIT_FACTORY, name, StepKind.BOOTSTRAP, "aif-121-sdc-dev", resolved,
                      options={"bootstrapConfig": BOOTSTRAP})
    with FakeFactoryApi() as api, pytest.raises(ValidationFailed, match=message):
        backend_for("rest", api).prepare(request)


def test_a_full_bootstrap_creates_a_dev_factory_only():
    request, _ = step(Scenario.INIT_FACTORY, "configure", StepKind.CONFIGURE, "aif-121-sdc-prod",
                      {"prefix": "aif-121-", "region": "swedencentral", "region_code": "sdc", "environment": "prod",
                       "suffix": "001", "project_number": "001"}, options={"bootstrapConfig": BOOTSTRAP})
    with FakeFactoryApi() as api, pytest.raises(ValidationFailed, match="dev"):
        backend_for("sdk", api).prepare(request)


@pytest.mark.parametrize("status,expected", [
    ({"status": "queued"}, ("queued", None)),
    ({"status": "running"}, ("in_progress", None)),
    ({"status": "awaiting-review", "requires_review": False}, ("in_progress", None)),
    ({"status": "awaiting-review", "requires_review": True, "message": "Confirm DNS SOA preservation."},
     ("completed", "action_required")),
    ({"status": "blocked", "message": "Stage stopped before cloud writes."}, ("completed", "failure")),
    ({"status": "succeeded"}, ("completed", "success")),
    ({"status": "uncertain"}, ("completed", "failure")),
    ({"status": "superseded"}, ("completed", "failure")),
    ({"status": "interrupted"}, ("completed", "failure")),
])
def test_job_and_creation_workflow_states_map_to_run_states(status, expected):
    observed = job_observation(status)
    assert (observed["status"], observed["conclusion"]) == expected
    assert observed["message"] == status.get("message", "")


def test_delete_factory_confirm_sends_the_reviewed_hash_and_phrase_once():
    calls = record("sdk", SCENARIOS["6-delete-factory"])
    confirms = [call for call in calls if call["path"].endswith("/delete-aifactory/confirm")]
    assert len(confirms) == 1
    assert confirms[0]["body"]["preview_hash"] == "b" * 64
    assert confirms[0]["body"]["confirmation_phrase"] == "DELETE aif-121-swedencentral"
