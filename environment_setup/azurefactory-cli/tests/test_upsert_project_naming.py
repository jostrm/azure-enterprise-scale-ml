"""Canonical project naming against the thin L1 HTTP contract, without live services."""

import inspect
from unittest.mock import Mock, call

import pytest

from azurefactory import AzureFactoryClient, esaf
from azurefactory.errors import ConfigError

FOLDER = r"C:\repos\consumer\azurefactory"


def test_upsert_project_is_the_canonical_public_definition():
    assert esaf.upsert_project.__name__ == "upsert_project"
    assert inspect.getsource(esaf.upsert_project).startswith("def upsert_project(")
    assert esaf.apply_project is esaf.upsert_project
    assert {"upsert_project", "apply_project"} <= set(esaf.__all__)
    assert 'esaf.upsert_project("002", "dev")' in esaf.__doc__
    assert "esaf.apply_project(" not in esaf.__doc__


@pytest.mark.parametrize("method", ["upsert_project", "apply_project"])
def test_project_spellings_submit_one_http_request_and_poll_outer_job(method, monkeypatch):
    client = AzureFactoryClient("http://127.0.0.1:1", "offline-key")
    request = Mock(side_effect=[
        {"job_id": "job-1"},
        *[{"status": state, "child": {"status": "failed"}} for state in
          ("accepted", "preparing", "confirming", "running", "retrying")],
        {"status": "succeeded"},
    ])
    monkeypatch.setattr(AzureFactoryClient, "request", request)
    pause = Mock()
    monkeypatch.setattr(esaf.time, "sleep", pause)
    selected = esaf.Session(FOLDER, client, "factory-1")
    job = getattr(esaf, method)(
        "003", "stage", scale_set="002", settings={"tag_costcenter": "unit"}, display_name="Project 003",
        version_ref="unit-version", retries=1, session=selected)
    assert (job.scenario, job.kind, job.id, job.session) == ("upsert_project", "esaf", "job-1", selected)
    client.request.assert_called_once_with("POST", "/api/v1/esaf/upsert-project", body={
        "folder": FOLDER, "approved": True, "factory": "factory-1", "project": "003", "environment": "stage",
        "scale_set": "002", "settings": {"tag_costcenter": "unit"}, "display_name": "Project 003",
        "version_ref": "unit-version", "retries": 1})
    assert job.wait() == {"status": "succeeded"}
    assert client.request.call_args_list[1:] == [
        call("GET", "/api/v1/esaf/jobs/job-1", query={"folder": FOLDER})] * 6
    assert pause.call_args_list == [call(1)] * 5


@pytest.mark.parametrize("method", ["add_scale_set", "upsert_project", "delete_project", "delete_scale_set"])
def test_scoped_scenarios_require_a_catalog_environment_before_http(method, monkeypatch):
    client = AzureFactoryClient("http://127.0.0.1:1", "offline-key")
    monkeypatch.setattr(AzureFactoryClient, "request", Mock())
    selected = esaf.Session(FOLDER, client)
    with pytest.raises(TypeError):
        getattr(esaf, method)("003", session=selected)
    with pytest.raises(ConfigError, match="dev, stage or prod"):
        getattr(esaf, method)("003", "test", session=selected)
    client.request.assert_not_called()
