import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from azurefactory import AzureFactoryClient
from azurefactory.client import canonical_json_hash
from azurefactory.errors import APIError, ConfigError
from azurefactory.review import load_receipt, validate_preview, write_receipt
from azurefactory.cli import confirmed_emit


def future():
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


def bootstrap_review():
    request = {
        "launcher": "GHA-create-new-aifactory-scaleset.sh", "orchestrator": "gha",
        "config": {"repo_root": r"C:\new-factory", "location": "swedencentral", "setup_hub_access": False},
    }
    preview = {
        "confirmation_id": "11111111-1111-1111-1111-111111111111", "can_execute": True,
        "expires_at": future(), "blockers": [], "effects": ["Creates infrastructure"], "warnings": [],
        "flow": "full-bootstrap", "config_format": "bootstrap-env-v1",
        "includes_common": True, "includes_initial_project": True,
        **copy.deepcopy(request),
    }
    preview["config"]["github_visibility"] = "private"
    return request, preview


def test_bootstrap_receipt_binds_repo_root_not_nonexistent_folder(tmp_path):
    request, preview = bootstrap_review()
    client = AzureFactoryClient("http://127.0.0.1:8765", "private-key")
    path = tmp_path / "bootstrap.json"
    write_receipt(str(path), client=client, purpose="bootstrap-start", operation="bootstrap",
                  request_body=request, preview=preview)
    receipt = load_receipt(str(path), client=client, purpose="bootstrap-start")
    assert receipt["folder"] == request["config"]["repo_root"]
    assert "folder" not in receipt["request"]
    assert receipt["preview"]["config"]["github_visibility"] == "private"


@pytest.mark.parametrize("field,value", [
    ("flow", "simple-mode"), ("includes_initial_project", False),
    ("includes_common", False), ("launcher", "other.sh"),
])
def test_bootstrap_requires_exact_flow_and_scope(tmp_path, field, value):
    request, preview = bootstrap_review()
    preview[field] = value
    with pytest.raises(ConfigError):
        write_receipt(str(tmp_path / "receipt.json"), client=AzureFactoryClient(),
                      purpose="bootstrap-start", operation="bootstrap", request_body=request, preview=preview)


def test_bootstrap_does_not_approve_changed_requested_config(tmp_path):
    request, preview = bootstrap_review()
    preview["config"]["setup_hub_access"] = True
    with pytest.raises(ConfigError, match="setup_hub_access"):
        write_receipt(str(tmp_path / "receipt.json"), client=AzureFactoryClient(),
                      purpose="bootstrap-start", operation="bootstrap", request_body=request, preview=preview)


def test_missing_blockers_is_not_approval():
    _, preview = bootstrap_review()
    del preview["blockers"]
    with pytest.raises(APIError):
        validate_preview(preview)


def settings_review():
    request = {"contract_version": 1, "action": "configure-settings", "folder": r"C:\factory",
               "factory_id": "factory", "scale_set_id": "scale", "project_id": "project",
               "expected_revision": "a" * 64, "settings": {"enableRedisCache": "false"}}
    preview = {"contract_version": 1, "confirmation_id": "review", "can_execute": True,
               "expires_at": future(), "blockers": [], "operation_mode": "configuration",
               "source_revision": "a" * 64, "factory_id": "factory", "scale_set_id": "scale",
               "project_id": "project", "target": {"id": "factory"}}
    return request, preview


def test_settings_receipt_roundtrip_and_tamper_detection(tmp_path):
    request, preview = settings_review()
    client = AzureFactoryClient()
    path = tmp_path / "settings.json"
    write_receipt(str(path), client=client, purpose="catalog-confirm", operation="catalog-settings",
                  request_body=request, preview=preview)
    receipt = load_receipt(str(path), client=client, purpose="catalog-confirm", operation_mode="configuration")
    assert receipt["request"] == request
    receipt["request"]["settings"]["enableRedisCache"] = "true"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ConfigError, match="request hash"):
        load_receipt(str(path), client=client, purpose="catalog-confirm")


@pytest.mark.parametrize("field,value", [
    ("contract_version", True), ("operation_mode", "runtime"), ("source_revision", "b" * 64),
    ("source_revision", None), ("factory_id", "other"), ("scale_set_id", None),
    ("project_id", "other"), ("target", {"id": "other"}), ("target", None),
])
def test_settings_receipt_rejects_changed_or_unsupported_acknowledgement(tmp_path, field, value):
    request, preview = settings_review()
    preview[field] = value
    with pytest.raises(ConfigError):
        write_receipt(str(tmp_path / "settings.json"), client=AzureFactoryClient(),
                      purpose="catalog-confirm", operation="catalog-settings", request_body=request, preview=preview)
    assert not (tmp_path / "settings.json").exists()


def test_settings_sdk_rejects_missing_acknowledgement_without_retry(monkeypatch):
    calls = []

    def prepare(self, body):
        calls.append(body)
        return {"can_execute": True}

    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", prepare)
    with pytest.raises(ConfigError, match="supporting API"):
        AzureFactoryClient().catalog_settings_prepare(r"C:\factory", "factory", {"enableRedisCache": "false"})
    assert len(calls) == 1


def automatic_project_review(action="add-project"):
    factory_id = "11111111-1111-4111-8111-111111111111"
    scale_id = "22222222-2222-4222-8222-222222222222"
    project_id = "33333333-3333-4333-8333-333333333333"
    tenant_id = "44444444-4444-4444-8444-444444444444"
    subscription_id = "55555555-5555-4555-8555-555555555555"
    placement = {"environment": "dev", "scale_set_id": "latest-successful"}
    request = {"contract_version": 1, "folder": r"C:\consumer\azurefactory",
               "factory_id": factory_id, "action": action, "expected_revision": "a" * 64}
    if action == "add-project":
        request["project"] = {"number": "002", "placements": [placement]}
    else:
        request.update(project_id=project_id, placements=[placement])
    selection = {
        "selector": "latest-successful", "environment": "dev", "scale_set_id": scale_id,
        "factory_id": factory_id, "tenant_id": tenant_id, "subscription_id": subscription_id,
        "orchestrator": "gha", "repository": "https://github.com/example/factory",
        "writer_id": "writer", "auth_namespace": "factory-dev", "deployment_object_id": None,
        "version_ref": "124", "job_id": "66666666-6666-4666-8666-666666666666",
        "completed_at": "2026-01-01T00:00:00Z", "source_commit": "b" * 40,
        "evidence_hash": "c" * 64, "evidence_kind": "recorded-verified-common-deployment",
    }
    preview = {"contract_version": 1, "confirmation_id": "review", "can_execute": True,
               "expires_at": future(), "blockers": [], "operation_mode": "configuration",
               "source_revision": "a" * 64, "factory_id": factory_id, "project_id": project_id,
               "capabilities": ["latest-successful-placement-v1"], "resolved_placements": [selection],
               "target": {"id": factory_id, "version_ref": "124", "scale_sets": [{
                   "id": scale_id, "environment": "dev", "tenant_id": tenant_id,
                   "subscription_id": subscription_id, "orchestrator": "gha"}],
                   "projects": [{"id": project_id, "number": "002", "placements": [
                       {"environment": "dev", "scale_set_id": scale_id}]}]}}
    return request, preview


@pytest.mark.parametrize("action", ["add-project", "add-project-placements"])
def test_automatic_project_receipt_binds_selector_and_resolved_target(tmp_path, action):
    request, preview = automatic_project_review(action)
    operation = "project-add" if action == "add-project" else "project-add-placements"
    path = str(tmp_path / "receipt.json")
    client = AzureFactoryClient()
    write_receipt(path, client=client, purpose="catalog-confirm", operation=operation,
                  request_body=request, preview=preview)
    receipt = load_receipt(path, client=client, purpose="catalog-confirm")
    assert receipt["request"] == request
    assert receipt["preview"]["resolved_placements"] == preview["resolved_placements"]


@pytest.mark.parametrize("change", [
    "missing", "duplicate", "capability", "factory", "project", "placement", "scale",
    "tenant", "environment", "version", "job", "time", "commit", "hash", "kind", "selector",
    "revision", "repository", "explicit-placement", "principal",
    "capability-string", "capability-object",
])
def test_automatic_project_review_rejects_unbound_resolution(tmp_path, change):
    request, preview = automatic_project_review()
    selected = preview["resolved_placements"][0]
    if change == "missing":
        preview.pop("resolved_placements")
    elif change == "duplicate":
        preview["resolved_placements"].append(copy.deepcopy(selected))
    elif change == "capability":
        preview["capabilities"] = []
    elif change == "capability-string":
        preview["capabilities"] = "latest-successful-placement-v1"
    elif change == "capability-object":
        preview["capabilities"] = {"latest-successful-placement-v1": True}
    elif change in ("factory", "project"):
        preview[change + "_id"] = "77777777-7777-4777-8777-777777777777"
    elif change == "placement":
        preview["target"]["projects"][0]["placements"][0]["scale_set_id"] = "latest-successful"
    elif change == "scale":
        preview["target"]["scale_sets"] = []
    elif change == "revision":
        preview["source_revision"] = "b" * 64
    elif change == "explicit-placement":
        request["project"]["placements"].append({"environment": "stage", "scale_set_id": selected["scale_set_id"]})
    else:
        field = {"tenant": "tenant_id", "environment": "environment", "version": "version_ref",
                 "job": "job_id", "time": "completed_at", "commit": "source_commit",
                 "hash": "evidence_hash", "kind": "evidence_kind", "selector": "selector",
                 "repository": "repository", "principal": "deployment_object_id"}[change]
        selected[field] = "invalid"
    with pytest.raises(ConfigError):
        write_receipt(str(tmp_path / "invalid.json"), client=AzureFactoryClient(),
                      purpose="catalog-confirm", operation="project-add",
                      request_body=request, preview=preview)
    assert not (tmp_path / "invalid.json").exists()


def test_review_sdk_rejects_missing_automatic_resolution_without_confirming(monkeypatch):
    request, preview = automatic_project_review()
    preview.pop("resolved_placements")
    calls = []

    def prepare(self, body):
        calls.append(body)
        return preview

    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", prepare)
    with pytest.raises(ConfigError):
        AzureFactoryClient().review_catalog_prepare(request)
    assert calls == [request]


def test_receipt_modes_cannot_be_relabelled(tmp_path):
    request = {"folder": r"C:\azurefactory", "contract_version": 1, "action": "deploy",
               "factory_id": "factory", "scale_set_id": "scale", "project_id": "project"}
    preview = {"contract_version": 1, "confirmation_id": "id", "can_execute": True,
               "expires_at": future(), "blockers": [], "operation_mode": "runtime"}
    client = AzureFactoryClient()
    path = tmp_path / "receipt.json"
    receipt = write_receipt(str(path), client=client, purpose="catalog-confirm", operation="runtime-deploy",
                            request_body=request, preview=preview)
    receipt["operation_mode"] = "configuration"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ConfigError, match="operation_mode"):
        load_receipt(str(path), client=client, purpose="catalog-confirm", operation_mode="configuration")


def test_parameter_receipt_omits_values_but_keeps_factory_key(tmp_path):
    request = {"folder": "folder", "contract_version": 1, "factory_key": "customer-ai",
               "templates": [{"template": "t", "parameters": {"customField": "sensitive-value"}}]}
    preview = {"contract_version": 1, "confirmation_id": "id", "can_execute": True, "expires_at": future(),
               "operation_mode": "configuration", "blockers": [], "target": {"key": "customer-ai"}}
    path = tmp_path / "receipt.json"
    receipt = write_receipt(str(path), client=AzureFactoryClient(), purpose="parameters-confirm",
                            operation="parameters", request_body=request, preview=preview)
    assert "sensitive-value" not in path.read_text()
    assert receipt["request"]["factory_key"] == "customer-ai"
    assert receipt["preview"]["target"]["key"] == "customer-ai"


def test_receipt_hash_detects_changed_preview(tmp_path):
    request, preview = bootstrap_review()
    client = AzureFactoryClient()
    path = tmp_path / "receipt.json"
    receipt = write_receipt(str(path), client=client, purpose="bootstrap-start",
                            operation="bootstrap", request_body=request, preview=preview)
    receipt["preview"]["config"]["location"] = "westeurope"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ConfigError, match="hash"):
        load_receipt(str(path), client=client, purpose="bootstrap-start")
    receipt["preview_hash"] = canonical_json_hash(receipt["preview"])
    path.write_text(json.dumps(receipt))
    with pytest.raises(ConfigError, match="location"):
        load_receipt(str(path), client=client, purpose="bootstrap-start")


def test_confirmed_runtime_failure_is_not_success(capsys):
    assert confirmed_emit({"contract_version": 1, "catalog": None, "job": {"id": "job", "status": "failed"}}, runtime=True) == 5
    assert json.loads(capsys.readouterr().out)["job"]["status"] == "failed"
    with pytest.raises(APIError):
        confirmed_emit({"contract_version": 1, "job": None, "catalog": {}}, runtime=True)


@pytest.mark.parametrize("changed", ["scope", "revision", "workflow", "effects", "review", "confirmation"])
def test_workflow_receipt_rejects_changed_or_incomplete_binding(tmp_path, changed):
    identifier = "33333333-3333-4333-8333-333333333333"
    scope = {"folder": r"C:\consumer\azurefactory", "factory_id": "factory", "scale_set_id": "scale"}
    request = {"scope": scope, "expected_revision": "a" * 64}
    preview = {"contract_version": 1, "workflow_id": identifier,
               "confirmation_id": "11111111-1111-4111-8111-111111111111", "scope": copy.deepcopy(scope),
               "stage": "repository-initialization", "source_revision": "a" * 64, "input_hash": "b" * 64,
               "effects": ["reviewed effect"], "review": {"mode": "single-writer"},
               "can_execute": True, "blockers": [], "expires_at": future()}
    if changed == "scope":
        preview["scope"]["factory_id"] = "another"
    elif changed == "revision":
        preview["source_revision"] = "c" * 64
    elif changed == "workflow":
        request = {"folder": scope["folder"], "workflow_id": "44444444-4444-4444-8444-444444444444"}
    elif changed in ("effects", "review"):
        preview[changed] = [] if changed == "effects" else {}
    else:
        preview["confirmation_id"] = "invalid"
    with pytest.raises(ConfigError):
        write_receipt(str(tmp_path / "workflow.json"), client=AzureFactoryClient(),
                      purpose="creation-workflow-start", operation="creation-workflow",
                      request_body=request, preview=preview)
