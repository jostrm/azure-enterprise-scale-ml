"""New project operations use upsert_project; persisted compatibility jobs remain readable."""

import json
from unittest.mock import Mock

import pytest
from azurefactory import esaf

from aif_lifecycle.adapters.sdk_backend import SdkFactoryBackend
from aif_lifecycle.http_api import ApiRequest
from support import confirm_current
from test_esaf_scenarios import FACTORY, FOLDER, ReadClient, finish_handoff, harness


@pytest.mark.parametrize("executor", ["inprocess", "github-runner"])
def test_project_route_approves_dispatches_and_persists_upsert_project(clock, monkeypatch, executor):
    h = harness(clock, monkeypatch, executor=executor)
    h.facade.upsert_project = Mock(side_effect=lambda *args, **kwargs: esaf.EsafJob(
        "upsert_project", "esaf", "canonical-project-job", kwargs["session"]))
    h.facade.apply_project = Mock(side_effect=AssertionError("Function must dispatch upsert_project"))
    body = {"projectId": "sample-esml-project001-sdc-dev-001-rg",
            "settings": {"enableAISearch": "true"}}
    response = h.api.prepare(ApiRequest(
        "POST", "/api/v1/lifecycle/add-or-update-project/prepare",
        route_params={"scenario": "add-or-update-project"}, body=json.dumps(body).encode()))
    assert response.status == 202
    if executor == "github-runner":
        finish_handoff(h, clock)
    operation = h.service.get(json.loads(response.body)["operationId"])
    assert operation.status.value == "awaiting_confirmation"
    assert operation.step.preview.backend_ref["method"] == "upsert_project"
    assert any("esaf.upsert_project" in line for line in operation.step.preview.plan)
    h.facade.upsert_project.assert_not_called()
    h.facade.apply_project.assert_not_called()

    operation = confirm_current(h.service, operation)
    if executor == "github-runner":
        finish_handoff(h, clock)
        operation = h.service.get(operation.id)
    assert operation.status.value == "running"
    h.facade.upsert_project.assert_called_once_with(
        "001", scale_set="001", environment="dev", settings=body["settings"], display_name="Project 001",
        session=esaf.Session(FOLDER, h.client, FACTORY))
    h.facade.apply_project.assert_not_called()
    assert operation.step.job == {
        "kind": "esaf", "scenario": "upsert_project", "job_kind": "esaf",
        "job_id": "canonical-project-job", "factory_id": FACTORY}
    restarted = SdkFactoryBackend("http://127.0.0.1:8765", None, FOLDER, client=h.client, facade=h.facade)
    assert restarted.job_status(operation.step.job)["status"] == "succeeded"
    h.facade.upsert_project.assert_called_once()
    h.facade.apply_project.assert_not_called()


def test_persisted_apply_project_job_remains_readable_without_redispatch():
    client = ReadClient()
    facade = Mock(Session=esaf.Session, EsafJob=esaf.EsafJob)
    backend = SdkFactoryBackend("http://127.0.0.1:8765", None, FOLDER, client=client, facade=facade)
    saved = {"kind": "esaf", "scenario": "apply_project", "job_kind": "catalog",
             "job_id": "legacy-project-job", "factory_id": FACTORY}

    assert backend.job_status(saved) == {"status": "succeeded"}
    assert client.reads == [("catalog-job", FOLDER, "legacy-project-job")]
    facade.upsert_project.assert_not_called()
    facade.apply_project.assert_not_called()


@pytest.mark.parametrize("saved,read", [
    ({"kind": "esaf", "scenario": "apply_project", "job_kind": "esaf", "job_id": "old-job"}, "esaf-job"),
    ({"kind": "esaf", "scenario": "apply_project", "job_kind": "catalog", "job_id": "old-job"}, "catalog-job"),
    ({"kind": "esaf", "scenario": "init_factory", "job_kind": "workflow", "job_id": "old-job"}, "workflow"),
    ({"kind": "esaf", "scenario": "delete_factory", "job_kind": "factory-deletion", "job_id": "old-job"},
     "factory-deletion"),
    ({"kind": "job", "job_id": "old-job"}, "catalog-job"),
    ({"kind": "workflow", "workflow_id": "old-job"}, "workflow"),
])
def test_legacy_job_formats_are_read_without_new_submission(saved, read):
    client = ReadClient()
    facade = Mock(Session=esaf.Session, EsafJob=esaf.EsafJob)
    backend = SdkFactoryBackend("http://127.0.0.1:1", None, FOLDER, client=client, facade=facade)
    assert backend.job_status(json.loads(json.dumps(saved))) == {"status": "succeeded"}
    assert client.reads == [(read, FOLDER, "old-job")]
    assert facade.method_calls == []
