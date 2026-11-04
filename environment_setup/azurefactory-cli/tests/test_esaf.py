"""ESAF facade: six scenario methods over /api/v1/esaf/* (Joakim, 2026-11-02).

The connection (ESAF_FOLDER, AIFACTORY_API_URL, AIFACTORY_API_KEY or esaf.connect) is set once; calls carry only the
target. Environment is required on scale-set and project scenarios. The orchestration runs in the Factory API.
"""

import copy
import json

import pytest

from azurefactory import cli, esaf
from azurefactory.client import AzureFactoryClient
from azurefactory.errors import APIError, BlockedError, ConfigError, FailureError

FOLDER = r"C:\factory\azurefactory"
JOB = "0b7d6c84-3a52-4f05-9a27-52a1c3f8e0d1"


class Transport(AzureFactoryClient):
    """The real client with only the HTTP transport replaced."""

    def __init__(self, states=("succeeded",), error=None):
        super().__init__("http://127.0.0.1:8766", "unit-test-key")
        self.calls, self.states, self.error = [], list(states), error

    def request(self, method, path, *, body=None, query=None, **kwargs):
        self.calls.append((method, path, copy.deepcopy(body), query))
        if self.error is not None:
            raise self.error
        if method == "POST" and path.startswith("/api/v1/esaf/"):
            return {"contract_version": 1, "job_id": JOB, "status_url": f"/api/v1/esaf/jobs/{JOB}?folder=x"}
        if method == "GET" and path == f"/api/v1/esaf/jobs/{JOB}":
            status = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return {"job_id": JOB, "status": status, "child": {"kind": "catalog", "id": "run-1"}}
        if path == "/api/v1/operations/delete-aifactory/status":
            return {"id": query["job_id"], "action": "delete-factory", "status": "running"}
        raise AssertionError(f"Unexpected API call: {method} {path}")


@pytest.fixture
def api(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(esaf.time, "sleep", lambda seconds: transport.calls.append(("sleep", seconds)))
    esaf.connect(folder=FOLDER, client=transport)
    return transport


def posted(transport):
    method, path, body, _ = next(call for call in transport.calls if call[0] == "POST")
    return path, body


def test_code_completion_lists_the_six_scenarios():
    assert {"init_factory", "add_scale_set", "upsert_project", "delete_project", "delete_scale_set",
            "delete_factory"} <= set(esaf.__all__)
    assert esaf.apply_project is esaf.upsert_project


@pytest.mark.parametrize("call,route,fields", [
    (lambda: esaf.init_factory(), "init-factory", {}),
    (lambda: esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16"), "add-scale-set",
     {"scale_set": "002", "environment": "dev", "cidr": "10.141.0.0/16"}),
    (lambda: esaf.upsert_project("002", "dev"), "upsert-project", {"project": "002", "environment": "dev"}),
    (lambda: esaf.delete_project("002", "dev"), "delete-project", {"project": "002", "environment": "dev"}),
    (lambda: esaf.delete_scale_set("002", "dev"), "delete-scale-set", {"scale_set": "002", "environment": "dev"}),
    (lambda: esaf.delete_factory(), "delete-factory", {}),
], ids=["init_factory", "add_scale_set", "upsert_project", "delete_project", "delete_scale_set", "delete_factory"])
def test_each_scenario_is_one_post_with_only_its_target(api, call, route, fields):
    job = call()
    assert posted(api) == ("/api/v1/esaf/" + route, {"folder": FOLDER, "approved": True, **fields})
    assert job.id == JOB and job.kind == "esaf"


def test_environment_is_required_so_a_delete_names_exactly_what_it_removes(api):
    for call in (lambda: esaf.delete_project("002"), lambda: esaf.delete_scale_set("002"),
                 lambda: esaf.upsert_project("002"), lambda: esaf.add_scale_set("002")):
        with pytest.raises(TypeError):
            call()
    with pytest.raises(ConfigError, match="dev, stage or prod"):
        esaf.delete_project("002", "qa")
    assert not api.calls


def test_the_connection_comes_from_the_environment_and_names_the_factory(monkeypatch):
    transport = Transport()
    monkeypatch.setenv("ESAF_FOLDER", FOLDER)
    monkeypatch.setattr(esaf, "_default", None)
    monkeypatch.setattr(esaf, "AzureFactoryClient", lambda **kwargs: transport)
    esaf.upsert_project("001", "dev", settings={"tag_costcenter": "lab"})
    assert posted(transport)[1] == {"folder": FOLDER, "approved": True, "project": "001", "environment": "dev",
                                    "settings": {"tag_costcenter": "lab"}}
    esaf.connect(folder=FOLDER, factory="aif-138", client=transport)
    esaf.delete_factory()
    assert transport.calls[-1][2]["factory"] == "aif-138"


def test_the_lifecycle_functions_call_shapes_still_work(api):
    """The Azure Function's SDK adapter passes these exact shapes (aif_lifecycle/adapters/sdk_backend.py)."""
    s = esaf.Session(FOLDER, api, "unit-sdc")
    esaf.init_factory(creation_request={"mode": "full-bootstrap"}, poll=1, session=s)
    esaf.add_scale_set("002", cidr="10.20.64.0/18", environment="dev", max_projects=7,
                       subscription_id="44444444-4444-4444-8444-444444444444", session=s)
    esaf.apply_project("002", scale_set="001", environment="dev", settings={}, display_name="Project 002", session=s)
    esaf.delete_project("002", scale_set="001", environment="dev", include_project_subnets=False,
                        include_keyvault_and_resource_group=True, session=s)
    esaf.delete_scale_set("002", environment="dev", session=s)
    esaf.delete_factory(session=s)
    bodies = [(path.rsplit("/", 1)[1], body) for method, path, body, _ in api.calls if method == "POST"]
    common = {"folder": FOLDER, "approved": True, "factory": "unit-sdc"}
    assert bodies == [
        ("init-factory", {**common, "creation_request": {"mode": "full-bootstrap"}}),
        ("add-scale-set", {**common, "scale_set": "002", "environment": "dev", "cidr": "10.20.64.0/18",
                           "max_projects": 7, "subscription_id": "44444444-4444-4444-8444-444444444444"}),
        ("upsert-project", {**common, "project": "002", "environment": "dev", "scale_set": "001", "settings": {},
                            "display_name": "Project 002"}),
        ("delete-project", {**common, "project": "002", "environment": "dev", "scale_set": "001",
                            "include_project_subnets": False, "include_keyvault_and_resource_group": True}),
        ("delete-scale-set", {**common, "scale_set": "002", "environment": "dev"}),
        ("delete-factory", common)]


def test_wait_reads_the_job_every_second_until_it_ends(api):
    api.states = ["accepted", "preparing", "running", "succeeded"]
    job = esaf.delete_project("002", "dev", wait=True)
    assert job.result["status"] == "succeeded"
    reads = [call for call in api.calls if call[0] == "GET"]
    assert [call[3] for call in reads] == [{"folder": FOLDER}] * 4
    assert [call for call in api.calls if call[0] == "sleep"] == [("sleep", 1)] * 3


def test_a_job_stored_by_an_earlier_sdk_is_still_readable(api):
    s = esaf.Session(FOLDER, api, None)
    assert esaf.EsafJob("delete_factory", "factory-deletion", "teardown-1", s).status()["status"] == "running"


@pytest.mark.parametrize("code,error", [("config", ConfigError), ("blocked", BlockedError),
                                        ("conflict", BlockedError), ("failure", FailureError)])
def test_problem_json_refusals_raise_the_sdk_errors(monkeypatch, code, error):
    details = {"type": "urn:aifactory:esaf:problem:" + code, "status": 409, "code": code,
               "detail": "deploy was refused: Missing adminPassword", "blockers": ["Missing adminPassword"]}
    transport = Transport(error=APIError("deploy was refused: Missing adminPassword", status=409, details=details))
    esaf.connect(folder=FOLDER, client=transport)
    with pytest.raises(error, match="adminPassword") as raised:
        esaf.upsert_project("001", "dev")
    assert raised.value.details["blockers"] == ["Missing adminPassword"]


def test_an_api_without_the_esaf_routes_is_reported_not_worked_around():
    transport = Transport(error=APIError("Not Found", status=404, details={"detail": "Not Found"}))
    esaf.connect(folder=FOLDER, client=transport)
    with pytest.raises(ConfigError, match="/api/v1/esaf"):
        esaf.delete_factory()
    assert len(transport.calls) == 1


def test_the_cli_runs_each_scenario_and_prints_the_job(monkeypatch, capsys):
    transport = Transport(states=["running", "succeeded"])
    monkeypatch.setattr(cli, "AzureFactoryClient", lambda *args, **kwargs: transport)
    monkeypatch.setattr(esaf.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("ESAF_FOLDER", FOLDER)
    assert cli.main(["esaf", "delete-scale-set", "002", "dev"]) == 0
    assert json.loads(capsys.readouterr().out)["job_id"] == JOB
    assert cli.main(["esaf", "add-scale-set", "003", "dev", "--cidr", "10.142.0.0/16", "--wait"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"
    assert posted(transport)[1] == {"folder": FOLDER, "approved": True, "scale_set": "002", "environment": "dev"}
    second = [call for call in transport.calls if call[0] == "POST"][1]
    assert second[2] == {"folder": FOLDER, "approved": True, "scale_set": "003", "environment": "dev",
                         "cidr": "10.142.0.0/16"}
    assert cli.main(["esaf", "job", JOB]) == 0
