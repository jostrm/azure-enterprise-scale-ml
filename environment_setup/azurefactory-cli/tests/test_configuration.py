from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from azurefactory import APIError, AzureFactoryClient, BlockedError, ConfigurationDraft, ConfigError, FailureError
from azurefactory import cli


class FakeAPI(AzureFactoryClient):
    def __init__(self):
        super().__init__("http://127.0.0.1:8765", "test-key")
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "responses", {
            "/api/v1/projects/load": {
                "state": {
                    "project_number_000": "001", "enableFunction": "false",
                    "_save_folder": r"C:\aifactory",
                    "_json_source": {"opaque": ["never-print-origin", {"future": True}]},
                    "_future_metadata": {"retain": [False, None, 9]},
                    "unrelated": "preserve",
                },
                "warnings": [{"field": "network", "message": "Review address space.", "severity": "warning"}],
            },
            "/api/v1/validation": {"valid": True, "issues": []},
            "/api/v1/export": {
                "format": "json", "path": None, "content": '{"dev":{"unknown":"never-print-content"}}',
                "warnings": [],
            },
            "/api/v1/projects/save": {"snapshot_path": "snapshot.json", "variables_path": "variables.yaml", "warnings": []},
        })

    def request(self, method, endpoint, *, body=None, **kwargs):
        self.calls.append((method, endpoint, copy.deepcopy(body)))
        response = self.responses[endpoint]
        if isinstance(response, Exception):
            raise response
        response = copy.deepcopy(response)
        if endpoint == "/api/v1/projects/save" and not body["write_variables"]:
            response["variables_path"] = None
        return response


def load(client, changes=None):
    return ConfigurationDraft.load(client, r"C:\aifactory", "001", changes=changes)


def test_review_and_save_preserve_complete_state_and_opaque_origin():
    client = FakeAPI()
    original = copy.deepcopy(client.responses["/api/v1/projects/load"]["state"])
    patch = {"enableFunction": True}
    draft = load(client, patch)
    patch["enableFunction"] = False
    review = draft.review()
    assert review["can_save"] is True
    assert review["changed_fields"] == ["enableFunction"]
    assert review["warnings"][0]["severity"] == "warning"
    assert client.calls[0] == ("POST", "/api/v1/projects/load", {
        "aifactory_folder": r"C:\aifactory", "project_number": "001",
    })
    assert client.calls[-1][2].keys() == {"state", "format"}
    assert not any(path.endswith("/save") for _, path, _ in client.calls)
    assert "never-print" not in json.dumps(review) + repr(draft)
    draft.save(review["review_id"])
    saved = client.calls[-1]
    assert saved[1] == "/api/v1/projects/save"
    assert saved[2] == {"state": {**original, "enableFunction": True}, "write_variables": True}
    assert client.responses["/api/v1/projects/load"]["state"] == original


@pytest.mark.parametrize("changes", [
    {"_json_source": {}}, {"_save_folder": "other"}, {"_future_metadata": {}},
    {"project_number_000": "002"}, {"guessed_field": "value"}, [], {"enableFunction": float("nan")},
])
def test_rejects_unsafe_or_unknown_field_replacements(changes):
    with pytest.raises(ConfigError):
        load(FakeAPI(), changes)


@pytest.mark.parametrize("source", [None, {}, "", []])
def test_requires_persistent_json_reference(source):
    client = FakeAPI()
    client.responses["/api/v1/projects/load"]["state"]["_json_source"] = source
    with pytest.raises(BlockedError, match="persistent"):
        load(client)


def test_rejects_wrong_project_from_server():
    client = FakeAPI()
    client.responses["/api/v1/projects/load"]["state"]["project_number_000"] = "002"
    with pytest.raises(FailureError, match="selected project"):
        load(client)


def test_missing_project_identity_is_not_project_zero():
    client = FakeAPI()
    del client.responses["/api/v1/projects/load"]["state"]["project_number_000"]
    with pytest.raises(FailureError, match="selected project"):
        ConfigurationDraft.load(client, r"C:\aifactory", "000")


@pytest.mark.parametrize("change", ["state", "patch", "output", "warnings", "host", "write-choice"])
def test_stale_review_or_changed_write_scope_never_saves(change):
    client = FakeAPI()
    receipt = load(client, {"enableFunction": True}).review()["review_id"]
    patch = {"enableFunction": True}
    write_variables = True
    if change == "state":
        client.responses["/api/v1/projects/load"]["state"]["unrelated"] = "modified"
    elif change == "patch":
        patch["enableFunction"] = "false"
    elif change == "output":
        client.responses["/api/v1/export"]["content"] = '{"changed":true}'
    elif change == "warnings":
        client.responses["/api/v1/export"]["warnings"] = [{"message": "New warning", "severity": "warning"}]
    elif change == "host":
        object.__setattr__(client, "base_url", "http://127.0.0.1:8766")
    else:
        write_variables = False
    with pytest.raises(BlockedError, match="review again"):
        load(client, patch).save(receipt, write_variables=write_variables)
    assert not any(path.endswith("/save") for _, path, _ in client.calls)


def test_invalid_validation_is_reviewable_but_never_exported_or_saved():
    client = FakeAPI()
    client.responses["/api/v1/validation"] = {
        "valid": False, "issues": [{"field": "tenant", "message": "Required", "severity": "error"}],
    }
    draft = load(client)
    review = draft.review()
    assert review["can_save"] is False
    with pytest.raises(BlockedError, match="validation failed"):
        draft.save(review["review_id"])
    assert {path for _, path, _ in client.calls} == {"/api/v1/projects/load", "/api/v1/validation"}


@pytest.mark.parametrize("validation", [
    {"valid": "true", "issues": []},
    {"valid": True, "issues": [{"message": "Error", "severity": "error"}]},
    {"valid": True, "issues": None},
])
def test_malformed_or_contradictory_validation_fails_closed(validation):
    client = FakeAPI()
    client.responses["/api/v1/validation"] = validation
    with pytest.raises(FailureError):
        load(client).review()


def test_changed_source_server_error_is_propagated_without_retry_or_save():
    client = FakeAPI()
    draft = load(client)
    approved = draft.review()["review_id"]
    client.responses["/api/v1/export"] = APIError("Source changed; re-import", status=422)
    with pytest.raises(APIError, match="Source changed"):
        draft.save(approved)
    assert not any(path.endswith("/save") for _, path, _ in client.calls)


def test_save_returns_only_safe_metadata_and_checks_variable_write_result():
    client = FakeAPI()
    response = client.responses["/api/v1/projects/save"]
    response["state"] = {"_json_source": "do-not-display"}
    draft = load(client)
    approved = draft.review()["review_id"]
    assert "state" not in draft.save(approved)
    response["variables_path"] = None
    with pytest.raises(FailureError, match="inspect server state"):
        draft.save(approved)


def test_cli_requires_approval_and_matching_review_without_printing_state(monkeypatch, tmp_path, capsys):
    client = FakeAPI()
    monkeypatch.setattr(cli, "client", lambda args: client)
    patch = tmp_path / "changes.json"
    patch.write_text('{"enableFunction":true}', encoding="utf-8")
    scope = ["--folder", r"C:\aifactory", "--project-number", "001", "--changes-json", str(patch), "--snapshot-only"]
    assert cli.main(["config", "save", *scope, "--expected-review", "a" * 64]) == 2
    assert not client.calls
    assert cli.main(["config", "review", *scope]) == 0
    output = capsys.readouterr()
    review = json.loads(output.out)
    assert "never-print" not in output.out + output.err
    assert cli.main(["config", "save", *scope, "--expected-review", review["review_id"], "--yes"]) == 0
    assert client.calls[-1][2]["write_variables"] is False


@pytest.mark.parametrize("invalid_file", ["directory", "non-utf8"])
def test_cli_patch_read_errors_are_structured_before_contacting_api(monkeypatch, tmp_path, capsys, invalid_file):
    client = FakeAPI()
    monkeypatch.setattr(cli, "client", lambda args: client)
    path = tmp_path
    if invalid_file == "non-utf8":
        path = tmp_path / "changes.json"
        path.write_bytes(b"\xff")
    assert cli.main([
        "config", "review", "--folder", r"C:\aifactory", "--project-number", "001",
        "--changes-json", str(path),
    ]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["type"] == "ConfigError"
    assert not client.calls


@pytest.mark.skipif(not os.environ.get("AIFACTORY_API_SOURCE"), reason="Optional canonical source contract validation")
def test_sdk_configuration_requests_match_canonical_routes_and_models(monkeypatch):
    monkeypatch.syspath_prepend(os.environ["AIFACTORY_API_SOURCE"])
    from src import api

    client = FakeAPI()
    draft = load(client)
    draft.save(draft.review()["review_id"])
    client.responses["/api/v1/import"] = {"state": {}}
    client.configuration_import(r"C:\aifactory\variables.json")
    client.configuration_export({"example": "state"}, "yaml", r"C:\exports\variables.yaml")
    for method, path, body in client.calls:
        operation = api.app.openapi()["paths"][path][method.lower()]
        model_name = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        getattr(api, model_name).model_validate(body)


@pytest.mark.skipif(not os.environ.get("AIFACTORY_API_SOURCE"), reason="Optional canonical source roundtrip")
def test_configuration_roundtrip_against_canonical_api_preserves_unknown_json(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(os.environ["AIFACTORY_API_SOURCE"])
    monkeypatch.setenv("AIFACTORY_API_KEY", "roundtrip-test-key")
    monkeypatch.setenv("AIFACTORY_OPERATIONS_DB", str(tmp_path / "operations.db"))
    from fastapi.testclient import TestClient
    from src import api, wizard

    root = tmp_path / "aifactory"
    root.mkdir()
    state = wizard.new_configuration_defaults()
    for key, value in list(state.items()):
        if isinstance(value, str) and "<todo>" in value.lower():
            state[key] = "11111111-1111-4111-8111-111111111111" if "id" in key.lower() or "subscription" in key else "sample"
    state.update(project_number_000="001", orchestrator="ado", enableFunction="false")
    assert api.validate(api.StateBody(state=state))["valid"]
    original = wizard._render_variables_json(state)
    original["dev"]["custom_not_in_wizard"] = {"keep": [None, False, 17]}
    original["stage_prod"]["custom_future_setting"] = ["leave", "untouched"]
    original["customer_metadata"] = {"unchanged": True}
    source = root / "variables.json"
    source.write_text(json.dumps(original), encoding="utf-8")

    with TestClient(api.app) as server:
        class LocalAPI(AzureFactoryClient):
            def request(self, method, endpoint, *, body=None, **kwargs):
                result = server.request(method, endpoint, json=body, headers={"X-API-Key": self.api_key})
                if result.is_error:
                    raise APIError(result.json()["detail"], status=result.status_code)
                return result.json()

        client = LocalAPI("http://127.0.0.1:8765", "roundtrip-test-key")
        draft = ConfigurationDraft.load(client, str(root), "001", changes={"enableFunction": "true"})
        review = draft.review()
        assert review["can_save"], review["validation"]
        assert not (root / "config-wizard").exists()
        result = draft.save(review["review_id"])
        exported = Path(result["variables_path"]).with_suffix(".json")
        expected = copy.deepcopy(original)
        expected["dev"]["enableFunction"] = "true"
        assert json.loads(exported.read_text(encoding="utf-8")) == expected
        assert json.loads(source.read_text(encoding="utf-8")) == original
        source.write_text(json.dumps({**original, "changed": True}), encoding="utf-8")
        with pytest.raises(APIError, match="changed"):
            draft.save(review["review_id"])
