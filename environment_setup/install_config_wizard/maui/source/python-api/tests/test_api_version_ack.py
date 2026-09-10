from fastapi.testclient import TestClient
import json
import pytest

from src import api
from src.catalog_storage import database
from src.ticket_connectors import TicketError
from tests.test_simple_mode import context as simple_context
from tests.test_project_deployments import context as project_context
from tests.test_catalog_runtime import harness, root, deploy_request


def client_for(monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "version-ack-test")
    return TestClient(api.app, client=("127.0.0.1", 54321)), {"X-API-Key": "version-ack-test"}


def test_simple_inheritance_does_not_synthesize_explicit_echo(simple_context, monkeypatch):
    c = simple_context
    monkeypatch.setattr(api, "_simple_mode_service", lambda: c.service)
    client, headers = client_for(monkeypatch)
    response = client.post("/api/v1/simple-mode/prepare", json=c.data, headers=headers)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert "aifactory_version" not in preview
    assert preview["requested_version"] == "124"
    assert preview["branch"] == "release/v1.24"
    assert len(preview["resolved_ref"]) == 40
    c.popen.assert_not_called()


def test_project_inheritance_keeps_metadata_without_raw_echo(project_context, monkeypatch):
    c = project_context
    c.chosen["installed_version"] = "125"
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    client, headers = client_for(monkeypatch)
    endpoint = "/api/v1/operations/project-deployments"
    planned = client.post(endpoint + "/plan", headers=headers, json={
        "folder": c.folder, "project_number": "017", "source_environment": "dev",
        "target_environment": "stage", "patch": True})
    assert planned.status_code == 200, planned.text
    draft = planned.json()
    assert "aifactory_version" not in draft
    assert "aifactory_version" not in draft["deployment_contract"]
    prepared = client.post(endpoint + "/prepare", headers=headers, json={
        "folder": c.folder, "draft_id": draft["id"], "patch": True})
    assert prepared.status_code == 200, prepared.text
    preview = prepared.json()
    assert "aifactory_version" not in preview
    assert "aifactory_version" not in preview["deployment_contract"]
    assert preview["requested_version"] == "125"
    assert all(preview[key] == preview["deployment_contract"][key]
               for key in ("requested_version", "branch", "resolved_ref"))
    c.factory.assert_not_called()


def test_project_list_preserves_identical_flat_and_typed_nested_selection(project_context, monkeypatch):
    c = project_context
    c.chosen["installed_version"] = "1.100"
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    client, headers = client_for(monkeypatch)
    response = client.get("/api/v1/operations/project-deployments", headers=headers, params={"folder": c.folder})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["version_selection"] == {
        "requested_version": "1.100", "branch": "release/v1.100", "resolved_ref": "a" * 40}
    assert result["version_selection"] == {key: result[key] for key in ("requested_version", "branch", "resolved_ref")}
    assert result["version_blockers"] == [] and result["drafts"] == []
    c.factory.assert_not_called()


def test_project_list_preserves_unknown_version_blockers_without_hiding_drafts(project_context, monkeypatch):
    c = project_context
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    client, headers = client_for(monkeypatch)
    endpoint = "/api/v1/operations/project-deployments"
    planned = client.post(endpoint + "/plan", headers=headers, json={
        "folder": c.folder, "project_number": "017", "source_environment": "dev", "target_environment": "stage"})
    assert planned.status_code == 200, planned.text

    def unavailable(*args, **kwargs):
        raise TicketError("Existing factory version is unknown.", 409)

    monkeypatch.setattr(api.project_deployments.release_version, "project_selection", unavailable)
    response = client.get(endpoint, headers=headers, params={"folder": c.folder})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["version_selection"] is None
    assert result["version_blockers"] == ["Existing factory version is unknown."]
    assert all(result[key] == "" for key in ("requested_version", "branch", "resolved_ref"))
    assert [draft["id"] for draft in result["drafts"]] == [planned.json()["id"]]
    c.factory.assert_not_called()


def test_catalog_preserves_exact_selector_inside_source_version(root, harness, monkeypatch):
    service, runtime, factory, queue, _ = harness
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    client, headers = client_for(monkeypatch)
    body = {**deploy_request(root, factory), "version_ref": "1.24"}
    response = client.post("/api/v1/factory-catalog/prepare", json=body, headers=headers)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["can_execute"], preview["blockers"]
    assert preview["source_version"]["aifactory_version"] == "1.24"
    assert preview["source_version"]["requested_version"] == "124"
    confirmed = client.post("/api/v1/factory-catalog/confirm", headers=headers, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": preview["confirmation_id"]})
    assert confirmed.status_code == 200, confirmed.text
    job = confirmed.json()["job"]
    assert job["source_version"] == preview["source_version"]
    listed = client.get("/api/v1/factory-catalog/jobs", headers=headers, params={"folder": str(root)})
    assert listed.status_code == 200 and listed.json()["contract_version"] == 1
    assert listed.json()["jobs"][0]["id"] == job["id"]
    stopped = client.post("/api/v1/factory-catalog/terminal/stop", headers=headers,
                          json={"folder": str(root), "job_id": job["id"]})
    assert stopped.status_code == 200
    queue.pop()()


@pytest.mark.parametrize("key,value", [
    ("aifactory_version", "124"), ("requested_version", "125"),
    ("branch", "main"), ("resolved_ref", "b" * 40),
])
def test_catalog_confirmation_binds_raw_and_canonical_version_ack(root, harness, monkeypatch, key, value):
    service, _, factory, queue, _ = harness
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    client, headers = client_for(monkeypatch)
    prepared = client.post("/api/v1/factory-catalog/prepare", headers=headers,
                           json={**deploy_request(root, factory), "version_ref": "1.24"})
    assert prepared.status_code == 200
    confirmation = prepared.json()["confirmation_id"]
    with database(root) as db:
        payload = json.loads(db.execute("SELECT payload FROM confirmations WHERE id=?", (confirmation,)).fetchone()["payload"])
        payload["preview"]["source_version"][key] = value
        db.execute("UPDATE confirmations SET payload=? WHERE id=?", (json.dumps(payload), confirmation))
    result = client.post("/api/v1/factory-catalog/confirm", headers=headers, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": confirmation})
    assert result.status_code == 409
    assert "version acknowledgement" in result.text
    assert not queue
