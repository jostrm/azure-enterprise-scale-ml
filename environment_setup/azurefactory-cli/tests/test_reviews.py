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
