"""Offline tests for the creation tutorial, using only mocked API calls."""

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI_SRC = ROOT.parents[1] / "azurefactory-cli" / "src"
FACTORY_ID = "11111111-1111-4111-8111-111111111111"
SCALE_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
CONFIRMATION_ID = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def example(monkeypatch):
    monkeypatch.syspath_prepend(str(CLI_SRC))
    monkeypatch.syspath_prepend(str(ROOT / "python"))
    spec = importlib.util.spec_from_file_location("creation_tutorial", ROOT / "python" / "create_factory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def artifacts():
    folder = ROOT / ".local" / ("pytest-create-" + str(uuid4()))
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


def request():
    return {
        "folder": r"C:\example-only\azurefactory", "contract_version": 1,
        "action": "create-factory", "factory_kind": "ai", "factory_key": "example-ai",
        "target_prefix": "example-", "target_region": "swedencentral", "aifactory_version": "main",
        "scale_sets": [{
            "environment": "dev", "suffix": "001",
            "tenant_id": "55555555-5555-4555-8555-555555555555",
            "subscription_id": "66666666-6666-4666-8666-666666666666",
            "orchestrator": "ado", "network": {"vnet_cidr": "172.16.0.0/18", "max_projects": 3},
        }],
    }


class Client:
    canonical_base_url = "http://127.0.0.1:8765"
    api_key = "test-private-key"

    def __init__(self):
        body = request()
        self.calls = []
        self.target = {
            "id": FACTORY_ID, "key": body["factory_key"], "kind": "ai",
            "prefix": body["target_prefix"], "region": body["target_region"],
            "default_orchestrator": "ado", "aifactory_version": "main",
            "scale_sets": [{"id": SCALE_ID, **copy.deepcopy(body["scale_sets"][0])}],
            "projects": [{"id": PROJECT_ID, "key": "project001", "number": "001", "display_name": "",
                          "placements": [{"environment": "dev", "scale_set_id": SCALE_ID}]}],
        }
        self.target["scale_sets"][0]["network"]["common_subnets"] = None
        self.preview = {
            "contract_version": 1, "confirmation_id": CONFIRMATION_ID,
            "can_execute": True, "operation_mode": "configuration",
            "target": copy.deepcopy(self.target), "blockers": [],
            "effects": ["Save local drafts only."], "warnings": ["Not Azure provision."],
            "summary": "create-factory: example-ai",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "source_revision": "a" * 64,
        }
        self.catalog = {"contract_version": 1, "mode": "catalog", "revision": "b" * 64,
                        "requires_selection": False,
                        "factories": [copy.deepcopy(self.target)]}
        self.confirmation = {"contract_version": 1, "catalog": copy.deepcopy(self.catalog), "job": None}

    def catalog_prepare(self, body):
        self.calls.append(("prepare", copy.deepcopy(body)))
        return copy.deepcopy(self.preview)

    def catalog_confirm(self, folder, confirmation_id):
        self.calls.append(("confirm", folder, confirmation_id))
        return copy.deepcopy(self.confirmation)

    def catalog_list(self, folder):
        self.calls.append(("list", folder))
        return copy.deepcopy(self.catalog)


def test_prepare_and_separately_approved_confirm_preserve_exact_default_scope(example, artifacts):
    client = Client()
    path = artifacts / "review.json"
    result, code = example.prepare_factory(client, request(), path)
    assert code == 0 and result["phase"] == "configuration-preview"
    assert [item[0] for item in client.calls] == ["prepare"]
    assert "initial_project" not in client.calls[0][1] and "project" not in client.calls[0][1]
    receipt = json.loads(path.read_text())
    assert receipt["purpose"] == "catalog-confirm" and receipt["operation"] == "factory-create"
    assert receipt["request"] == request()
    result = example.confirm_factory(client, path, approved=True)
    assert client.calls[1:] == [
        ("confirm", request()["folder"], CONFIRMATION_ID), ("list", request()["folder"]),
    ]
    assert result["factory_id"] == FACTORY_ID and result["scale_set_id"] == SCALE_ID
    assert result["project_id"] == PROJECT_ID and result["catalog_revision"] == "b" * 64
    assert result["deployment_started"] is False and result["publication_started"] is False


@pytest.mark.parametrize("change", [
    {"action": "deploy"}, {"factory_kind": "web"}, {"initial_project": None},
    {"project": None}, {"contract_version": True}, {"folder": "relative"},
    {"target_region": "${FACTORY_REGION}"}, {"aifactory_version": "124"},
    {"scale_sets": []},
])
def test_unsafe_or_unrendered_requests_never_reach_api(example, artifacts, change):
    client = Client()
    with pytest.raises(example.APIError):
        example.prepare_factory(client, {**request(), **change}, artifacts / "review.json")
    assert not client.calls


@pytest.mark.parametrize("change", [
    {"number": "002"}, {"id": "bad-id"}, {"placements": []},
    {"placements": [{"environment": "dev", "scale_set_id": FACTORY_ID}]},
])
def test_preview_rejects_missing_or_changed_default_project(example, artifacts, change):
    client = Client()
    client.preview["target"]["projects"][0].update(change)
    with pytest.raises(example.FailureError):
        example.prepare_factory(client, request(), artifacts / "review.json")
    assert [item[0] for item in client.calls] == ["prepare"]
    assert not list(artifacts.iterdir())


def test_placement_evidence_does_not_change_the_reviewed_scope(example, artifacts):
    client = Client()
    for factory in (client.preview["target"], client.catalog["factories"][0]):
        factory["projects"][0]["placements"][0].update(
            deployment_state="unknown", deployment_detail="Deployment evidence has not been evaluated.",
        )
    path = artifacts / "review.json"
    result, code = example.prepare_factory(client, request(), path)
    assert code == 0 and result["project_id"] == PROJECT_ID
    result = example.confirm_factory(client, path, approved=True)
    assert result["project_id"] == PROJECT_ID and result["deployment_started"] is False


@pytest.mark.parametrize("issue", ["runtime", "no-target", "extra-project", "subscription", "expired", "contract"])
def test_preview_safety_contract_is_required(example, artifacts, issue):
    client = Client()
    if issue == "runtime":
        client.preview["operation_mode"] = "runtime"
    elif issue == "no-target":
        client.preview["target"] = None
    elif issue == "extra-project":
        client.preview["target"]["projects"].append(copy.deepcopy(client.target["projects"][0]))
    elif issue == "subscription":
        client.preview["target"]["scale_sets"][0]["subscription_id"] = FACTORY_ID
    elif issue == "expired":
        client.preview["expires_at"] = "2000-01-01T00:00:00Z"
    else:
        client.preview["contract_version"] = True
    with pytest.raises(example.APIError):
        example.prepare_factory(client, request(), artifacts / "review.json")
    assert not list(artifacts.iterdir())


def test_blocked_preview_is_visible_without_confirmable_receipt(example, artifacts):
    client = Client()
    client.preview.update(can_execute=False, blockers=["Resolve the exact target."])
    result, code = example.prepare_factory(client, request(), artifacts / "review.json")
    assert code == 3 and result["preview"]["blockers"]
    assert not list(artifacts.iterdir())


def test_existing_receipt_is_never_overwritten_or_reprepared(example, artifacts):
    client = Client()
    path = artifacts / "review.json"
    path.write_text("preserve")
    with pytest.raises(example.ConfigError):
        example.prepare_factory(client, request(), path)
    assert not client.calls and path.read_text() == "preserve"


@pytest.mark.parametrize("change", ["approval", "expiry", "host", "tamper"])
def test_confirm_requires_exact_valid_receipt_before_any_write(example, artifacts, change):
    client = Client()
    path = artifacts / "review.json"
    example.prepare_factory(client, request(), path)
    client.calls.clear()
    approved = change != "approval"
    if change == "host":
        client.canonical_base_url = "http://127.0.0.1:8766"
    if change in ("expiry", "tamper"):
        receipt = json.loads(path.read_text())
        if change == "expiry":
            from azurefactory.client import canonical_json_hash
            receipt["expires_at"] = receipt["preview"]["expires_at"] = "2000-01-01T00:00:00Z"
            receipt["preview_hash"] = canonical_json_hash(receipt["preview"])
        else:
            receipt["request"]["target_region"] = "westeurope"
        path.write_text(json.dumps(receipt))
    with pytest.raises(example.APIError):
        example.confirm_factory(client, path, approved=approved)
    assert not client.calls


@pytest.mark.parametrize("change", [
    {"contract_version": True}, {"job": {"status": "queued"}}, {"catalog": None}, {"catalog": {}},
])
def test_configuration_confirm_rejects_runtime_or_malformed_result(example, artifacts, change):
    client = Client()
    path = artifacts / "review.json"
    example.prepare_factory(client, request(), path)
    client.confirmation.update(change)
    with pytest.raises(example.FailureError):
        example.confirm_factory(client, path, approved=True)
    assert [item[0] for item in client.calls] == ["prepare", "confirm"]


def test_configuration_confirm_requires_explicit_null_job(example, artifacts):
    client = Client()
    path = artifacts / "review.json"
    example.prepare_factory(client, request(), path)
    del client.confirmation["job"]
    with pytest.raises(example.FailureError, match="job:null"):
        example.confirm_factory(client, path, approved=True)
    assert [item[0] for item in client.calls] == ["prepare", "confirm"]


def test_fresh_read_verifies_saved_project_ids_not_just_http_success(example, artifacts):
    client = Client()
    path = artifacts / "review.json"
    example.prepare_factory(client, request(), path)
    client.catalog["factories"][0]["projects"][0]["id"] = FACTORY_ID
    with pytest.raises(example.FailureError, match="UUIDs differ"):
        example.confirm_factory(client, path, approved=True)
    assert [item[0] for item in client.calls] == ["prepare", "confirm", "list"]


def test_entrypoint_defaults_to_prepare_and_requires_separate_yes(example, artifacts, monkeypatch, capsys):
    client = Client()
    monkeypatch.setattr(example, "AzureFactoryClient", lambda: client)
    body = artifacts / "request.json"
    body.write_text(json.dumps(request()))
    receipt = artifacts / "review.json"
    assert example.main(["--request", str(body), "--receipt", str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "configuration-preview"
    assert example.main(["--confirm", "--receipt", str(receipt)]) == 2
    assert [item[0] for item in client.calls] == ["prepare"]
    assert example.main(["--confirm", "--receipt", str(receipt), "--yes"]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "configuration-saved"


def test_lost_confirmation_is_not_retried_or_logged(example, artifacts, monkeypatch, capsys):
    client = Client()
    path = artifacts / "review.json"
    example.prepare_factory(client, request(), path)
    attempts = []

    def lost(*args):
        attempts.append(args)
        raise example.APIError("test-private-key in raw error", status=409)

    monkeypatch.setattr(client, "catalog_confirm", lost)
    monkeypatch.setattr(example, "AzureFactoryClient", lambda: client)
    assert example.main(["--confirm", "--receipt", str(path), "--yes"]) == 1
    output = capsys.readouterr()
    assert len(attempts) == 1 and "409" in output.err
    assert not output.out and "test-private-key" not in output.err
    assert "do not blindly retry" in output.err


@pytest.mark.skipif(not os.environ.get("AIFACTORY_API_SOURCE"), reason="Optional authoritative model validation")
def test_example_response_checks_accept_authoritative_serialization(example, monkeypatch):
    monkeypatch.syspath_prepend(os.environ["AIFACTORY_API_SOURCE"])
    from src.factory_catalog_models import CatalogConfirmed, CatalogPrepare, CatalogPreview

    client = Client()
    parsed = CatalogPrepare.model_validate(request())
    assert parsed.initial_project.number == "001" and parsed.initial_project.placements is None
    preview = CatalogPreview.model_validate(client.preview).model_dump(mode="json")
    assert example.check_create_preview(preview, request()) == {
        "factory_id": FACTORY_ID, "scale_set_id": SCALE_ID, "project_id": PROJECT_ID,
    }
    confirmed = CatalogConfirmed.model_validate(client.confirmation).model_dump(mode="json")
    example.check_catalog(confirmed["catalog"])
    assert example.check_target(confirmed["catalog"]["factories"][0], request())["project_id"] == PROJECT_ID
