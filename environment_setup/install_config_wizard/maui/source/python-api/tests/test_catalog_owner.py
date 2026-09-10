import hashlib

from fastapi.testclient import TestClient

from src import api, catalog_runtime, factory_catalog
from tests.test_catalog_runtime import root, harness, deploy_request


SID_A = "windows:S-1-5-21-111-222-333-1001"
SID_B = "windows:S-1-5-21-111-222-333-1002"
BASE = "/api/v1/factory-catalog"


def setup_client(monkeypatch, service, namespace):
    monkeypatch.setenv(api.API_KEY_ENV, "launch-key-one")
    if namespace is None:
        monkeypatch.delenv("AIFACTORY_CATALOG_OWNER", raising=False)
    else:
        monkeypatch.setenv("AIFACTORY_CATALOG_OWNER", namespace)
    monkeypatch.setattr(api, "_catalog_service", lambda: service)
    return TestClient(api.app, client=("127.0.0.1", 54321))


def test_trusted_same_sid_retains_consent_and_jobs_after_key_rotation_and_restart(root, harness, monkeypatch):
    service, runtime, factory, queue, _ = harness
    client = setup_client(monkeypatch, service, SID_A)
    preview = client.post(BASE + "/prepare", headers={"X-API-Key": "launch-key-one"},
                          json=deploy_request(root, factory))
    assert preview.status_code == 200 and preview.json()["can_execute"]
    monkeypatch.setenv(api.API_KEY_ENV, "launch-key-two")
    confirmed = client.post(BASE + "/confirm", headers={"X-API-Key": "launch-key-two"}, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": preview.json()["confirmation_id"]})
    assert confirmed.status_code == 200, confirmed.text
    job = confirmed.json()["job"]
    assert queue

    fresh = factory_catalog.CatalogService()
    monkeypatch.setattr(api, "_catalog_service", lambda: fresh)
    monkeypatch.setattr(catalog_runtime, "_pid_alive", lambda pid: False)
    monkeypatch.setenv(api.API_KEY_ENV, "launch-key-three")
    listed = client.get(BASE + "/jobs", headers={"X-API-Key": "launch-key-three"}, params={"folder": str(root)})
    assert listed.status_code == 200, listed.text
    assert type(listed.json()["contract_version"]) is int and listed.json()["contract_version"] == 1
    assert [item["id"] for item in listed.json()["jobs"]] == [job["id"]]
    retrieved = client.get(BASE + "/jobs/" + job["id"], headers={"X-API-Key": "launch-key-three"},
                           params={"folder": str(root)})
    assert retrieved.status_code == 200 and retrieved.json()["status"] == "interrupted"
    assert retrieved.json()["source_version"] == job["source_version"]
    assert client.get(BASE + "/jobs", headers={"X-API-Key": "launch-key-one"},
                      params={"folder": str(root)}).status_code == 401


def test_other_trusted_sid_cannot_read_jobs_or_forge_owner_in_http(root, harness, monkeypatch):
    service, _, factory, _, _ = harness
    client = setup_client(monkeypatch, service, SID_A)
    headers = {"X-API-Key": "launch-key-one"}
    prepared = client.post(BASE + "/prepare", headers=headers, json=deploy_request(root, factory)).json()
    confirmed = client.post(BASE + "/confirm", headers=headers, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": prepared["confirmation_id"]})
    assert confirmed.status_code == 200, confirmed.text
    job = confirmed.json()["job"]
    pending = client.post(BASE + "/prepare", headers=headers, json=deploy_request(root, factory)).json()
    monkeypatch.setenv("AIFACTORY_CATALOG_OWNER", SID_B)
    monkeypatch.setenv(api.API_KEY_ENV, "other-valid-key")
    forged = {"X-API-Key": "other-valid-key", "X-Catalog-Owner": SID_A, "AIFACTORY_CATALOG_OWNER": SID_A}
    listed = client.get(BASE + "/jobs", headers=forged, params={"folder": str(root), "owner": SID_A})
    assert listed.status_code == 200 and listed.json()["jobs"] == []
    assert listed.json()["contract_version"] == 1
    assert client.get(BASE + "/jobs/" + job["id"], headers=forged, params={"folder": str(root)}).status_code == 404
    body = {"folder": str(root), "contract_version": 1, "confirmation_id": pending["confirmation_id"]}
    assert client.post(BASE + "/confirm", headers=forged, json=body).status_code == 404
    assert client.post(BASE + "/confirm", headers=forged, json={**body, "owner": SID_A}).status_code == 422
    remote = TestClient(api.app, client=("203.0.113.2", 54321))
    assert remote.get(BASE + "/jobs", headers=forged, params={"folder": str(root)}).status_code == 403


def test_standalone_owner_keeps_existing_key_digest_and_rotation_isolated(root, harness, monkeypatch):
    service, _, factory, _, _ = harness
    client = setup_client(monkeypatch, service, None)
    headers = {"X-API-Key": "launch-key-one"}
    preview = client.post(BASE + "/prepare", headers=headers, json=deploy_request(root, factory))
    assert preview.status_code == 200
    request = api.Request({"type": "http", "headers": [(b"x-api-key", b"launch-key-one")]})
    assert api._catalog_owner(request) == hashlib.sha256(b"launch-key-one").hexdigest()
    monkeypatch.setenv(api.API_KEY_ENV, "launch-key-two")
    result = client.post(BASE + "/confirm", headers={"X-API-Key": "launch-key-two"}, json={
        "folder": str(root), "contract_version": 1, "confirmation_id": preview.json()["confirmation_id"]})
    assert result.status_code == 404
