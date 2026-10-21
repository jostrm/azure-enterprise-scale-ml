"""Option 1 (REST) and option 2 (SDK) must make exactly the same Factory API calls for every scenario."""

import pytest

from aif_lifecycle.adapters.rest_backend import RestFactoryBackend, RestTransport
from aif_lifecycle.adapters.sdk_backend import SdkFactoryBackend
from aif_lifecycle.domain.operation import StepKind
from aif_lifecycle.domain.scenarios import Scenario
from aif_lifecycle.ports import StepRequest

from fake_factory_api import FACTORY_ID, JOB_ID, PROJECT_ID, SCALESET_ID, WORKFLOW_ID, FakeFactoryApi

FOLDER = r"C:\repos\azure-enterprise-scale-byor-121\azurefactory"
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
              "suffix": "001", "project_number": "001"}, options={"scaleSet": SCALE_SET}),
        step(Scenario.INIT_FACTORY, "bootstrap", StepKind.BOOTSTRAP, "aif-121-sdc-dev", {**IDS, "project_id": PROJECT_ID},
             options={"bootstrapConfig": {"coordination_mode": "single-writer"}}),
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
    "1-init-factory": ["GET /api/v1/factory-catalog", "GET /openapi.json", "POST /api/v1/factory-catalog/prepare",
                       "POST /api/v1/factory-catalog/confirm", "GET /api/v1/factory-catalog",
                       "POST /api/v1/creation/workflows/prepare", "POST /api/v1/creation/workflows/start"],
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


def test_delete_factory_confirm_sends_the_reviewed_hash_and_phrase_once():
    calls = record("sdk", SCENARIOS["6-delete-factory"])
    confirms = [call for call in calls if call["path"].endswith("/delete-aifactory/confirm")]
    assert len(confirms) == 1
    assert confirms[0]["body"]["preview_hash"] == "b" * 64
    assert confirms[0]["body"]["confirmation_phrase"] == "DELETE aif-121-swedencentral"
