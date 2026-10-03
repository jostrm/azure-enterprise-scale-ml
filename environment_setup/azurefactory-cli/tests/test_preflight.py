from __future__ import annotations

import io
import json
import subprocess
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from azurefactory import AzureFactoryClient
from azurefactory.cli import build_parser, client, main
from azurefactory.errors import FailureError


ENDPOINT = "/api/v1/creation/preflight"
API_KEY = "private-api-key"
COMMANDS = [("preflight",), ("bootstrap", "workflow", "prepare", "--preflight")]


def report():
    return {
        "contract_version": 1, "kind": "deployment-preflight", "read_only": True,
        "authorization": False, "status": "ready", "ready": True,
        "generated_at": "2026-10-03T15:00:00Z", "input_hash": "a" * 64,
        "source": {}, "target": {},
        "checks": [{"id": "configuration", "category": "inputs", "status": "passed",
                    "blocking": False, "message": "Valid", "evidence": {}, "remediation": ""}],
        "cost_preview": None, "limitations": ["Readiness is not deployment approval."],
    }


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(records=[], report=report(), error=None, raw=None, content_type="application/json")

    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(state.raw if state.raw is not None else json.dumps(state.report).encode())
            self.headers = Message()
            self.headers["Content-Type"] = state.content_type

    class Opener:
        def open(self, req, timeout):
            state.records.append({
                "method": req.method, "url": req.full_url, "headers": dict(req.header_items()),
                "body": json.loads(req.data) if req.data else None, "timeout": timeout,
            })
            if state.error:
                raise state.error
            return Response()

    def no_process(*args, **kwargs):
        pytest.fail("Preflight must not run local az/gh or any subprocess.")

    monkeypatch.setattr("azurefactory.client.build_opener", lambda *args: Opener())
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    return state


def invoke(tmp_path, body=None, command=COMMANDS[0], extra=(), global_args=()):
    request = tmp_path / "request.json"
    request.write_text(json.dumps(body if body is not None else {
        "contract_version": 1, "bootstrap_config": {},
    }), encoding="utf-8")
    return main(["--api-url", "http://127.0.0.1:8765", "--api-key", API_KEY,
                 *global_args, *command, "--request-json", str(request), *extra])


def assert_single_post(transport):
    assert len(transport.records) == 1
    assert transport.records[0]["method"] == "POST"
    assert transport.records[0]["url"] == "http://127.0.0.1:8765" + ENDPOINT
    assert transport.records[0]["headers"]["X-api-key"] == API_KEY


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("orchestrator", [None, "gha", "ado"])
def test_readiness_only_uses_one_authenticated_post(tmp_path, transport, capsys, command, orchestrator):
    body = {"contract_version": 1, "bootstrap_config": {"custom_nested_setting": {"enabled": True}}}
    if orchestrator:
        body["orchestrator"] = orchestrator
    assert invoke(tmp_path, body, command) == 0
    assert json.loads(capsys.readouterr().out) == transport.report
    assert_single_post(transport)
    assert transport.records[0]["body"] == {"orchestrator": orchestrator or "gha", **body}


@pytest.mark.parametrize("command", COMMANDS)
def test_workflow_prepare_shape_is_forwarded_without_approval(tmp_path, transport, capsys, command):
    body = {
        "contract_version": 1, "orchestrator": "ado", "bootstrap_config": {},
        "settings": {"custom_setting": False},
        "scope": {"folder": "C:\\consumer\\azurefactory", "factory_id": "factory",
                  "scale_set_id": "scale", "project_id": None},
        "expected_revision": "b" * 64, "operation": "create-factory",
        "execution_mode": "privileged-bootstrap", "creation_mode": "full-bootstrap",
        "mode": "full", "approval_mode": "whole-workflow",
        "authorization_valid_for_seconds": 3600, "bootstrap_public_ipv4": "192.0.2.1",
    }
    assert invoke(tmp_path, body, command) == 0
    assert_single_post(transport)
    assert transport.records[0]["body"] == body
    assert json.loads(capsys.readouterr().out)["authorization"] is False


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("policy", [
    {"approval_scope": "whole-workflow"},
    {"approval_scope": "per-stage", "approval_mode": "per-stage"},
    {"approval_scope": "whole-workflow", "approval_mode": "per-stage"},
])
def test_known_approval_scope_alias_is_forwarded_but_never_authorizes(tmp_path, transport, capsys, command, policy):
    body = {"contract_version": 1, "bootstrap_config": {}, **policy}
    assert invoke(tmp_path, body, command) == 0
    assert transport.records[0]["body"] == {"orchestrator": "gha", **body}
    assert json.loads(capsys.readouterr().out)["authorization"] is False
    assert_single_post(transport)


@pytest.mark.parametrize("status", ["blocked", "incomplete"])
@pytest.mark.parametrize("command", COMMANDS)
def test_not_ready_preserves_json_saves_report_and_exits_nonzero(tmp_path, transport, capsys, status, command):
    transport.report.update(status=status, ready=False)
    transport.report["checks"][0].update(status="unknown", blocking=True)
    target = tmp_path / "preflight.json"
    assert invoke(tmp_path, command=command, extra=("--save-report", str(target))) == 3
    assert json.loads(capsys.readouterr().out) == transport.report
    assert json.loads(target.read_text(encoding="utf-8")) == transport.report
    assert_single_post(transport)


@pytest.mark.parametrize("status", ["passed", "warning", "unknown", "skipped"])
def test_nonblocking_check_can_be_ready(tmp_path, transport, capsys, status):
    transport.report["checks"][0]["status"] = status
    transport.report["future_optional"] = {"retained": True}
    transport.report["cost_preview"] = {"available": False, "currency": "USD"}
    assert invoke(tmp_path) == 0
    assert json.loads(capsys.readouterr().out) == transport.report


@pytest.mark.parametrize("field", sorted(report()))
def test_missing_required_report_fields_fail_closed(tmp_path, transport, capsys, field):
    del transport.report[field]
    assert invoke(tmp_path) == 5
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["details"] == transport.report
    assert_single_post(transport)


@pytest.mark.parametrize(("field", "value"), [
    ("contract_version", True), ("contract_version", 2), ("kind", "workflow-preview"),
    ("read_only", False), ("authorization", True), ("ready", "true"),
    ("status", "success"), ("status", []), ("status", "blocked"),
    ("source", []), ("target", None), ("checks", {}), ("cost_preview", []),
    ("limitations", [None]), ("input_hash", ""), ("generated_at", "not-a-date"),
    ("generated_at", "2026-10-03T15:00:00"), ("generated_at", None),
])
def test_incompatible_report_fields_fail_closed(tmp_path, transport, field, value):
    transport.report[field] = value
    assert invoke(tmp_path) == 5
    assert_single_post(transport)


@pytest.mark.parametrize("fingerprint", [
    "", "unbound", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n",
    " " + "a" * 64, 123, None,
])
def test_invalid_input_fingerprint_fails_closed(tmp_path, transport, fingerprint):
    transport.report["input_hash"] = fingerprint
    assert invoke(tmp_path) == 5
    assert_single_post(transport)


def test_ready_without_checks_fails_closed(tmp_path, transport):
    transport.report["checks"] = []
    assert invoke(tmp_path) == 5
    assert_single_post(transport)


@pytest.mark.parametrize("ready", [True, False])
def test_duplicate_check_ids_fail_closed(tmp_path, transport, ready):
    transport.report.update(ready=ready, status="ready" if ready else "incomplete")
    transport.report["checks"].append({
        **transport.report["checks"][0], "category": "different-category", "status": "warning",
    })
    assert invoke(tmp_path) == 5
    assert_single_post(transport)


def test_missing_defaults_are_normalized_without_changing_bootstrap_input(tmp_path, transport):
    body = {"contract_version": 1, "bootstrap_config": {"location": ""}}
    assert invoke(tmp_path, body) == 0
    assert transport.records[0]["body"] == {**body, "orchestrator": "gha"}
    assert set(transport.report) == set(report())
    assert_single_post(transport)


@pytest.mark.parametrize("field", ["id", "category", "status", "blocking", "message", "evidence", "remediation"])
def test_missing_required_check_fields_fail_closed(tmp_path, transport, field):
    del transport.report["checks"][0][field]
    assert invoke(tmp_path) == 5
    assert_single_post(transport)


@pytest.mark.parametrize("update", [
    {"status": "new-required-status"}, {"status": []}, {"blocking": "false"},
    {"status": "unknown", "blocking": True}, {"status": "warning", "blocking": True},
    {"status": "passed", "blocking": True}, {"status": "blocked", "blocking": False},
    {"evidence": []}, {"id": ""}, {"category": None}, {"message": {}},
])
def test_unknown_or_contradictory_checks_are_not_success(tmp_path, transport, update):
    transport.report["checks"][0].update(update)
    assert invoke(tmp_path) == 5
    assert_single_post(transport)


@pytest.mark.parametrize("body", [
    [], {}, {"bootstrap_config": {}}, {"contract_version": 1},
    {"contract_version": True, "bootstrap_config": {}},
    {"contract_version": 2, "bootstrap_config": {}},
    {"contract_version": 1, "bootstrap_config": []},
    {"contract_version": 1, "bootstrap_config": {}, "unknown_required": True},
    {"contract_version": 1, "bootstrap_config": {}, "orchestrator": "other"},
    {"contract_version": 1, "bootstrap_config": {}, "settings": []},
    {"contract_version": 1, "bootstrap_config": {}, "scope": []},
    {"contract_version": 1, "bootstrap_config": {}, "scope": {"unknown": True}},
    {"contract_version": 1, "bootstrap_config": {}, "scope": {"folder": False}},
    {"contract_version": 1, "bootstrap_config": {}, "expected_revision": {}},
    {"contract_version": 1, "bootstrap_config": {}, "approval_mode": True},
    {"contract_version": 1, "bootstrap_config": {}, "approval_scope": True},
    {"contract_version": 1, "bootstrap_config": {}, "authorization_valid_for_seconds": True},
    {"contract_version": 1, "bootstrap_config": {"value": float("nan")}},
])
def test_invalid_request_never_calls_transport(tmp_path, transport, body):
    assert invoke(tmp_path, body) == 2
    assert not transport.records


@pytest.mark.parametrize("status", [401, 403, 404, 405, 422, 500])
def test_http_errors_never_fallback_or_emit_success(tmp_path, transport, capsys, status):
    transport.error = HTTPError("http://127.0.0.1:8765" + ENDPOINT, status, "failure", {},
                                io.BytesIO(json.dumps({"detail": "rejected " + API_KEY}).encode()))
    assert invoke(tmp_path) != 0
    output = capsys.readouterr()
    assert not output.out
    assert API_KEY not in output.err
    error = json.loads(output.err)["error"]
    assert error["status"] == status
    if status in (404, 405):
        assert "newer API" in error["message"]
    assert_single_post(transport)


@pytest.mark.parametrize("raw", [b"", b"<html>error</html>", b"{", b"null", b"[]"])
def test_malformed_json_response_is_nonzero(tmp_path, transport, raw):
    transport.raw = raw
    assert invoke(tmp_path) != 0
    assert_single_post(transport)


def test_non_json_response_is_nonzero(tmp_path, transport):
    transport.content_type = "text/html"
    assert invoke(tmp_path) != 0
    assert_single_post(transport)


@pytest.mark.parametrize("error", [TimeoutError(), URLError(TimeoutError()), URLError("connection refused")])
def test_network_errors_are_nonzero_without_retry(tmp_path, transport, error):
    transport.error = error
    assert invoke(tmp_path) != 0
    assert_single_post(transport)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("timeout", [None, 180, 30, 5])
def test_preserves_default_and_explicit_timeout(tmp_path, transport, command, timeout):
    global_args = ("--timeout", str(timeout)) if timeout is not None else ()
    assert invoke(tmp_path, command=command, global_args=global_args) == 0
    assert transport.records[0]["timeout"] == (timeout if timeout is not None else 180)
    assert_single_post(transport)


@pytest.mark.parametrize("command", [
    ("health",), ("doctor",), ("schema",), ("bootstrap", "capabilities"),
    ("bootstrap", "workflow", "prepare", "--request-json", "request.json"),
])
@pytest.mark.parametrize("timeout", [None, 180, 30, 5])
def test_other_commands_keep_standard_timeout(command, timeout):
    global_args = ["--timeout", str(timeout)] if timeout is not None else []
    args = build_parser().parse_args([*global_args, *command])
    assert client(args).timeout == (timeout if timeout is not None else 30)


@pytest.mark.parametrize("command", COMMANDS)
def test_cancellation_never_retries_or_creates_workflow(tmp_path, transport, command):
    transport.error = KeyboardInterrupt()
    assert invoke(tmp_path, command=command) == 130
    assert_single_post(transport)


def test_requires_api_key_before_transport(tmp_path, transport):
    request = tmp_path / "request.json"
    request.write_text('{"contract_version":1,"bootstrap_config":{}}', encoding="utf-8")
    assert main(["preflight", "--request-json", str(request)]) == 6
    assert not transport.records


@pytest.mark.parametrize("command", COMMANDS)
def test_redacted_report_is_not_a_receipt_and_never_overwritten(tmp_path, transport, capsys, command):
    transport.report["source"] = {"api_key": "another-secret", "message": API_KEY}
    transport.report["checks"][0]["evidence"] = {"access_token": "token-value"}
    target = tmp_path / "preflight.json"
    assert invoke(tmp_path, command=command, extra=("--save-report", str(target))) == 0
    saved = target.read_text(encoding="utf-8")
    assert json.loads(saved) == json.loads(capsys.readouterr().out)
    assert all(secret not in saved for secret in (API_KEY, "another-secret", "token-value"))
    assert not {"format", "confirmation_id", "workflow_id", "can_execute"} & json.loads(saved).keys()
    assert invoke(tmp_path, command=command, extra=("--save-report", str(target))) == 2
    assert target.read_text(encoding="utf-8") == saved
    assert_single_post(transport)


@pytest.mark.parametrize("extra", [("--save-receipt", "receipt.json"), ("--whole-workflow",)])
def test_preflight_alias_rejects_approval_flags_before_transport(tmp_path, transport, extra):
    assert invoke(tmp_path, command=COMMANDS[1], extra=extra) == 2
    assert not transport.records


def test_workflow_prepare_rejects_report_without_preflight(tmp_path, transport):
    assert invoke(tmp_path, command=("bootstrap", "workflow", "prepare"),
                  extra=("--save-report", str(tmp_path / "report.json"))) == 2
    assert not transport.records


def test_report_cannot_overwrite_receipt_or_request(tmp_path, transport):
    request = tmp_path / "request.json"
    assert invoke(tmp_path, extra=("--save-report", str(request))) == 2
    assert json.loads(request.read_text(encoding="utf-8")) == {"contract_version": 1, "bootstrap_config": {}}
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"format":"azurefactory-review-receipt-v1"}', encoding="utf-8")
    assert invoke(tmp_path, extra=("--save-report", str(receipt))) == 2
    assert receipt.read_text(encoding="utf-8") == '{"format":"azurefactory-review-receipt-v1"}'
    assert not transport.records


def test_report_write_failure_is_actionable(tmp_path, transport, capsys):
    assert invoke(tmp_path, extra=("--save-report", str(tmp_path / "missing" / "report.json"))) == 2
    assert "Cannot write" in capsys.readouterr().err
    assert_single_post(transport)


@pytest.mark.parametrize("content", ['{"contract_version":', "\xff"])
def test_invalid_request_file_has_no_transport(tmp_path, transport, content):
    request = tmp_path / "invalid.json"
    request.write_bytes(content.encode("latin-1"))
    assert main(["preflight", "--request-json", str(request)]) == 2
    assert not transport.records


def test_sdk_preserves_request_and_report(transport):
    body = {"contract_version": 1, "bootstrap_config": {}}
    assert AzureFactoryClient(api_key=API_KEY).preflight(body) == transport.report
    assert body == {"contract_version": 1, "bootstrap_config": {}}
    assert_single_post(transport)


def test_sdk_malformed_report_redacts_explicit_api_key(transport):
    transport.report["kind"] = "old-preview"
    transport.report["source"] = {"message": API_KEY, "password": "private"}
    with pytest.raises(FailureError) as exc:
        AzureFactoryClient(api_key=API_KEY).preflight({"contract_version": 1, "bootstrap_config": {}})
    assert exc.value.details["source"] == {"message": "<redacted>", "password": "<redacted>"}
    assert_single_post(transport)
