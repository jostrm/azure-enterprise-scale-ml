from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from azurefactory.cli import compare_openapi, contract_issues, main

DRAFT_ID = "22222222-2222-2222-2222-222222222222"
CONFIRMATION_ID = "11111111-1111-1111-1111-111111111111"


def future():
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


def legacy_draft(**overrides):
    draft = {
        "id": DRAFT_ID,
        "project_number": "001",
        "source_environment": "dev",
        "target_environment": "dev",
        "operation": "update",
        "patch": True,
        "status": "draft",
        "message": "draft",
        "route": "ado",
        "script_path": "C:\\factory\\deploy.ps1",
        "job_id": None,
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
        "aifactory_version": "2506",
        "requested_version": "2506",
        "branch": "release/2506",
        "resolved_ref": "abcdef",
    }
    draft.update(overrides)
    draft["deployment_contract"] = {
        "version": 2,
        "draft_id": draft["id"],
        "operation": draft["operation"],
        "patch": draft["patch"],
        "aifactory_version": draft.get("aifactory_version"),
        "requested_version": draft.get("requested_version", ""),
        "branch": draft.get("branch", ""),
        "resolved_ref": draft.get("resolved_ref", ""),
    }
    return draft


class Handler(BaseHTTPRequestHandler):
    records = []
    status_sequence = []
    malformed_ack = False
    catalog_operation_mode = "configuration"
    saved_draft = None

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def log_message(self, *_):
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        payload = json.loads(body.decode()) if body else None
        parsed_path = urlparse(self.path).path
        type(self).records.append({"method": self.command, "path": self.path, "route": parsed_path, "body": payload})
        response = {"ok": True}
        status = 200
        if parsed_path == "/health":
            response = {"status": "ok", "version": "1.0.0"}
        elif parsed_path == "/openapi.json":
            response = valid_openapi()
        elif parsed_path == "/api/v1/factory-catalog/prepare":
            response = {
                "contract_version": 1,
                "confirmation_id": CONFIRMATION_ID,
                "can_execute": True,
                "summary": "ready",
                "effects": ["effect"],
                "warnings": [],
                "blockers": [],
                "expires_at": future(),
                "source_revision": "a" * 64,
                "operation_mode": type(self).catalog_operation_mode,
                "target": {"id": payload.get("factory_id", "33333333-3333-3333-3333-333333333333")},
            }
        elif parsed_path == "/api/v1/factory-catalog/parameters/prepare":
            response = {
                "contract_version": 1,
                "confirmation_id": CONFIRMATION_ID,
                "can_execute": True,
                "summary": "ready",
                "effects": [],
                "warnings": [],
                "blockers": [],
                "expires_at": future(),
                "source_revision": payload["expected_revision"],
                "operation_mode": "configuration",
                "target": None,
            }
        elif parsed_path == "/api/v1/creation/bootstrap/prepare":
            response = {
                "confirmation_id": CONFIRMATION_ID,
                "can_execute": True,
                "summary": "ready",
                "script_path": "C:\\script.sh",
                "command": "bootstrap",
                "environment": {},
                "effects": [],
                "requirements": [],
                "warnings": [],
                "blockers": [],
                "expires_at": future(),
                "github_visibility": "private",
                "project_resources": [],
                "resource_catalog": {},
                "flow": "full-bootstrap",
                "config_format": "bootstrap-env-v1",
                "launcher": payload["launcher"],
                "orchestrator": payload["orchestrator"],
                "config": payload["config"],
                "includes_common": True,
                "includes_initial_project": True,
            }
        elif parsed_path == "/api/v1/operations/project-deployments":
            response = {"drafts": [type(self).saved_draft]}
        elif parsed_path == "/api/v1/operations/project-deployments/plan":
            response = legacy_draft(
                id="33333333-3333-3333-3333-333333333333",
                project_number=payload["project_number"],
                source_environment=payload["source_environment"],
                target_environment=payload["target_environment"],
                operation=payload["operation"],
                patch=payload["patch"],
                aifactory_version=payload.get("aifactory_version"),
                requested_version=payload.get("aifactory_version", ""),
                branch="release/2506" if payload.get("aifactory_version") else "",
                resolved_ref="abcdef" if payload.get("aifactory_version") else "",
            )
            if type(self).malformed_ack:
                response["deployment_contract"]["version"] = 1
        elif parsed_path == "/api/v1/operations/project-deployments/prepare":
            version = payload.get("aifactory_version", type(self).saved_draft.get("aifactory_version"))
            type(self).saved_draft = legacy_draft(
                patch=payload["patch"], aifactory_version=version, requested_version=version or "main",
                branch=("release/" + version) if version and version != "main" else "main",
                resolved_ref="a" * 40,
            )
            response = {
                "confirmation_id": CONFIRMATION_ID,
                "can_execute": True,
                "summary": "ready",
                "command": "deploy",
                "working_directory": "C:\\factory",
                "effects": [],
                "warnings": [],
                "blockers": [],
                "expires_at": future(),
                "deployment_contract": type(self).saved_draft["deployment_contract"],
            }
        elif parsed_path == "/api/v1/operations/project-deployments/start":
            response = {**type(self).saved_draft, "job_id": "job", "status": "submitted", "message": "Pipeline submitted."}
        elif parsed_path == "/api/v1/creation/bootstrap/start":
            response = {"id": "bootstrap-job", "status": "queued"}
        elif parsed_path == "/api/v1/creation/bootstrap/jobs/bootstrap-job":
            response = {"id": "bootstrap-job", "status": "succeeded"}
        elif parsed_path in {"/api/v1/factory-catalog/confirm", "/api/v1/factory-catalog/parameters/confirm"}:
            response = {"contract_version": 1, "catalog": {"mode": "catalog"}, "job": None}
        elif parsed_path == "/api/v1/operations/project-deployments/terminal":
            current = type(self).status_sequence.pop(0) if type(self).status_sequence else "submitted"
            response = {"job_id": "job", "output": "", "next_cursor": 0, "reset": False, "status": current}
        elif parsed_path == "/blocked-preview":
            response = {"can_execute": False, "blockers": ["blocked"]}
        else:
            status = 404
            response = {"detail": self.path}
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


@pytest.fixture()
def server():
    Handler.records = []
    Handler.status_sequence = []
    Handler.malformed_ack = False
    Handler.catalog_operation_mode = "configuration"
    Handler.saved_draft = legacy_draft()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_cli_subprocess_help_and_json_health(server):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "azurefactory", "--api-url", server, "health"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_legacy_plan_preserves_patch_false_and_version(server, capsys):
    code = main(["--api-url", server, "--api-key", "k", "legacy", "plan", "--folder", "C:\\factory",
                 "--project-number", "001", "--source-env", "dev", "--target-env", "dev", "--operation", "update",
                 "--aifactory-version", "2506"])
    assert code == 0
    body = Handler.records[-1]["body"]
    assert body["patch"] is False
    assert body["aifactory_version"] == "2506"
    assert json.loads(capsys.readouterr().out)["deployment_contract"]["version"] == 2


def test_legacy_prepare_receipt_and_start_binding(server, tmp_path):
    receipt = tmp_path / "receipt.json"
    code = main(["--api-url", server, "--api-key", "k", "legacy", "prepare", "--folder", "C:\\factory",
                 "--draft-id", "22222222-2222-2222-2222-222222222222", "--save-receipt", str(receipt)])
    assert code == 0
    saved = json.loads(receipt.read_text())
    assert saved["purpose"] == "legacy-start"
    assert saved["contract"]["version"] == 2
    assert saved["request"]["patch"] is True
    assert "preview" in saved and saved["preview_hash"]
    code = main(["--api-url", server, "--api-key", "k", "legacy", "start", "--receipt", str(receipt), "--yes"])
    assert code == 0


def test_legacy_prepare_explicit_no_patch_can_start(server, tmp_path):
    receipt = tmp_path / "receipt-no-patch.json"
    code = main(["--api-url", server, "--api-key", "k", "legacy", "prepare", "--folder", "C:\\factory",
                 "--draft-id", DRAFT_ID, "--no-patch", "--save-receipt", str(receipt)])
    assert code == 0
    saved = json.loads(receipt.read_text())
    assert saved["patch"] is False
    assert saved["saved_patch"] is False
    assert saved["patch_override"] is True
    assert main(["--api-url", server, "--api-key", "k", "legacy", "start", "--receipt", str(receipt), "--yes"]) == 0


def test_expired_receipt_blocks_start(server, tmp_path):
    receipt = tmp_path / "expired.json"
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    receipt.write_text(json.dumps({
        "format": "azurefactory-review-receipt-v1",
        "purpose": "legacy-start",
        "base_url": server,
        "folder": "C:\\factory",
        "operation": "legacy-project-deployment",
        "confirmation_id": "11111111-1111-1111-1111-111111111111",
        "can_execute": True,
        "expires_at": expired_at,
        "request": {"folder": "C:\\factory"},
        "preview": {"confirmation_id": CONFIRMATION_ID, "can_execute": True, "blockers": [], "expires_at": expired_at},
        "request_hash": "x",
        "preview_hash": "x",
        "contract": {"version": 2, "draft_id": DRAFT_ID, "operation": "update", "patch": True},
    }))
    # Fix hashes so the expiry path is reached.
    receipt_data = json.loads(receipt.read_text())
    from azurefactory.client import canonical_json_hash
    receipt_data["request_hash"] = canonical_json_hash(receipt_data["request"])
    receipt_data["preview_hash"] = canonical_json_hash(receipt_data["preview"])
    receipt.write_text(json.dumps(receipt_data))
    code = main(["--api-url", server, "--api-key", "k", "legacy", "start", "--receipt", str(receipt), "--yes"])
    assert code == 3


def test_poll_submitted_is_terminal_not_deployed_success(server, capsys):
    Handler.status_sequence = ["running", "submitted"]
    code = main(["--api-url", server, "--api-key", "k", "legacy", "status", "--folder", "C:\\factory",
                 "--job-id", "job", "--wait", "--poll-timeout", "2", "--poll-interval", "0.01"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "submitted"


def test_poll_failure_exit(server, capsys):
    Handler.status_sequence = ["failed"]
    code = main(["--api-url", server, "--api-key", "k", "legacy", "status", "--folder", "C:\\factory",
                 "--job-id", "job", "--wait", "--poll-timeout", "2", "--poll-interval", "0.01"])
    assert code == 5
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_generic_write_requires_opt_in(server):
    assert main(["--api-url", server, "--api-key", "k", "request", "POST", "/x", "--body", "{}"]) == 2


def test_generic_write_blocked_preview_returns_blocked(server):
    assert main(["--api-url", server, "--api-key", "k", "request", "POST", "/blocked-preview", "--body", "{}", "--write", "--yes"]) == 3


def test_doctor_compare_reports_incompatible_and_additive():
    expected = {"paths": {"/a": {"get": {}}}, "components": {"schemas": {"S": {"required": ["x"], "properties": {"x": {"type": "string"}}}}}}
    actual = {"paths": {"/a": {"get": {}}, "/b": {"get": {}}}, "components": {"schemas": {"S": {"required": ["x"], "properties": {"x": {"type": "string"}, "y": {}}}}}}
    result = compare_openapi(expected, actual)
    assert not result["incompatible"]
    assert result["additive"]
    broken = compare_openapi(expected, {"paths": {}, "components": {"schemas": {}}})
    assert broken["incompatible"]


def test_legacy_plan_malformed_ack_fails(server):
    Handler.malformed_ack = True
    assert main(["--api-url", server, "--api-key", "k", "legacy", "plan", "--folder", "C:\\factory",
                 "--project-number", "001", "--source-env", "dev", "--target-env", "dev", "--operation", "update"]) == 5


def test_catalog_and_runtime_receipts_are_not_interchangeable(server, tmp_path):
    receipt = tmp_path / "catalog.json"
    assert main(["--api-url", server, "--api-key", "k", "factory", "clone", "--folder", "C:\\factory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333", "--prefix", "aif-copy",
                 "--save-receipt", str(receipt)]) == 0
    assert main(["--api-url", server, "--api-key", "k", "runtime", "confirm", "--receipt", str(receipt), "--yes"]) == 2

    Handler.catalog_operation_mode = "runtime"
    runtime_receipt = tmp_path / "runtime.json"
    assert main(["--api-url", server, "--api-key", "k", "runtime", "deploy", "--folder", "C:\\factory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333",
                 "--scale-set-id", "44444444-4444-4444-4444-444444444444",
                 "--project-id", "55555555-5555-5555-5555-555555555555",
                 "--save-receipt", str(runtime_receipt)]) == 0
    assert main(["--api-url", server, "--api-key", "k", "catalog", "confirm", "--receipt", str(runtime_receipt), "--yes"]) == 2


def test_exact_catalog_payloads_and_receipt_overwrite(server, tmp_path):
    receipt = tmp_path / "factory.receipt.json"
    assert main(["--api-url", server, "--api-key", "k", "factory", "create", "--folder", "C:\\factory",
                 "--prefix", "aif-prod", "--region", "swedencentral", "--environment", "dev", "--suffix", "001",
                 "--subscription-id", "11111111-1111-1111-1111-111111111111",
                 "--tenant-id", "22222222-2222-2222-2222-222222222222", "--orchestrator", "ado",
                 "--vnet-cidr", "172.16.0.0/18", "--save-receipt", str(receipt)]) == 0
    body = Handler.records[-1]["body"]
    assert body["action"] == "create-factory"
    assert body["contract_version"] == 1
    assert body["scale_sets"][0]["network"]["vnet_cidr"] == "172.16.0.0/18"
    assert main(["--api-url", server, "--api-key", "k", "factory", "create", "--folder", "C:\\factory",
                 "--prefix", "aif-prod", "--region", "swedencentral", "--environment", "dev", "--suffix", "001",
                 "--subscription-id", "11111111-1111-1111-1111-111111111111",
                 "--tenant-id", "22222222-2222-2222-2222-222222222222", "--orchestrator", "ado",
                 "--vnet-cidr", "172.16.0.0/18", "--save-receipt", str(receipt)]) == 2


def test_project_scaleset_parameters_bootstrap_payloads(server, tmp_path):
    scale_file = tmp_path / "scale.json"
    scale_file.write_text(json.dumps({"environment": "stage", "suffix": "002", "subscription_id": "11111111-1111-1111-1111-111111111111", "tenant_id": "22222222-2222-2222-2222-222222222222", "orchestrator": "gha", "network": {"vnet_cidr": "172.20.0.0/18", "max_projects": 2}}))
    assert main(["--api-url", server, "--api-key", "k", "scaleset", "add", "--folder", "C:\\factory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333", "--scale-set-json", str(scale_file)]) == 0
    assert Handler.records[-1]["body"]["scale_sets"][0]["orchestrator"] == "gha"

    assert main(["--api-url", server, "--api-key", "k", "project", "add", "--folder", "C:\\factory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333", "--number", "001",
                 "--placement", "dev=44444444-4444-4444-4444-444444444444"]) == 0
    assert Handler.records[-1]["body"]["project"]["placements"][0]["environment"] == "dev"

    assert main(["--api-url", server, "--api-key", "k", "project", "add-placements", "--folder", "C:\\factory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333", "--project-id", "55555555-5555-5555-5555-555555555555",
                 "--placement", "stage=44444444-4444-4444-4444-444444444444"]) == 0
    assert Handler.records[-1]["body"]["action"] == "add-project-placements"

    params = tmp_path / "params.json"
    params.write_text(json.dumps({"sku": "S0"}))
    assert main(["--api-url", server, "--api-key", "k", "parameters", "prepare", "--folder", "C:\\factory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333",
                 "--scale-set-id", "44444444-4444-4444-4444-444444444444",
                 "--expected-revision", "a" * 64, "--schema-revision", "b" * 64,
                 "--template", "portal", "--parameters-json", str(params)]) == 0
    assert Handler.records[-1]["body"]["templates"][0]["parameters"] == {"sku": "S0"}

    config = tmp_path / "boot.json"
    config.write_text(json.dumps({"subscription_id": "11111111-1111-1111-1111-111111111111"}))
    assert main(["--api-url", server, "--api-key", "k", "bootstrap", "prepare",
                 "--launcher", "ADO-create-new-aifactory-scaleset.sh", "--orchestrator", "ado",
                 "--config-json", str(config)]) == 0
    assert Handler.records[-1]["body"]["launcher"] == "ADO-create-new-aifactory-scaleset.sh"


def test_full_bootstrap_prepare_start_and_wait(server, tmp_path):
    request = tmp_path / "bootstrap-request.json"
    request.write_text(json.dumps({
        "launcher": "GHA-create-new-aifactory-scaleset.sh", "orchestrator": "gha",
        "config": {"repo_root": r"C:\new-factory", "setup_hub_access": False},
    }))
    receipt = tmp_path / "bootstrap-receipt.json"
    prefix = ["--api-url", server, "--api-key", "k", "bootstrap"]
    assert main([*prefix, "prepare", "--request-json", str(request), "--save-receipt", str(receipt)]) == 0
    assert main([*prefix, "start", "--receipt", str(receipt), "--yes", "--wait", "--poll-timeout", "2"]) == 0
    start = next(item for item in Handler.records if item["route"] == "/api/v1/creation/bootstrap/start")
    assert start["body"] == {"confirmation_id": CONFIRMATION_ID}


def test_legacy_prepare_can_resolve_new_source_and_start(server, tmp_path):
    receipt = tmp_path / "new-source.json"
    prefix = ["--api-url", server, "--api-key", "k", "legacy"]
    assert main([*prefix, "prepare", "--folder", r"C:\factory", "--draft-id", DRAFT_ID,
                 "--aifactory-version", "main", "--no-patch", "--save-receipt", str(receipt)]) == 0
    saved = json.loads(receipt.read_text())
    assert saved["contract"]["requested_version"] == "main"
    assert saved["contract"]["resolved_ref"] == "a" * 40
    assert saved["saved_aifactory_version"] == "main"
    assert main([*prefix, "start", "--receipt", str(receipt), "--yes"]) == 0


def test_catalog_configuration_confirm_roundtrip(server, tmp_path):
    receipt = tmp_path / "clone.json"
    prefix = ["--api-url", server, "--api-key", "k"]
    assert main([*prefix, "factory", "clone", "--folder", r"C:\azurefactory",
                 "--factory-id", "33333333-3333-3333-3333-333333333333",
                 "--prefix", "copy-", "--save-receipt", str(receipt)]) == 0
    assert main([*prefix, "catalog", "confirm", "--receipt", str(receipt), "--yes"]) == 0
    assert Handler.records[-1]["body"] == {
        "folder": r"C:\azurefactory", "contract_version": 1, "confirmation_id": CONFIRMATION_ID,
    }


def test_parameters_request_json_standalone_and_conflict(server, tmp_path):
    body = {
        "folder": "C:\\factory",
        "contract_version": 1,
        "factory_id": "33333333-3333-3333-3333-333333333333",
        "scale_set_id": "44444444-4444-4444-4444-444444444444",
        "expected_revision": "a" * 64,
        "schema_revision": "b" * 64,
        "templates": [{"template": "portal", "parameters": {"secretValue": "do-not-store"}}],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(body))
    receipt = tmp_path / "params.receipt.json"
    assert main(["--api-url", server, "--api-key", "k", "parameters", "prepare", "--request-json", str(path), "--save-receipt", str(receipt)]) == 0
    saved = json.loads(receipt.read_text())
    assert "parameters" not in saved["request"]["templates"][0]
    assert saved["request"]["templates"][0]["parameter_names"] == ["secretValue"]
    assert main(["--api-url", server, "--api-key", "k", "parameters", "prepare", "--request-json", str(path), "--folder", "C:\\other"]) == 2


def test_poll_timeout_and_unknown_status(server):
    Handler.status_sequence = ["running", "running", "running"]
    assert main(["--api-url", server, "--api-key", "k", "legacy", "status", "--folder", "C:\\factory",
                 "--job-id", "job", "--wait", "--poll-timeout", "0.01", "--poll-interval", "0.01"]) == 4
    Handler.status_sequence = ["mystery"]
    assert main(["--api-url", server, "--api-key", "k", "legacy", "status", "--folder", "C:\\factory",
                 "--job-id", "job", "--wait", "--poll-timeout", "1", "--poll-interval", "0.01"]) == 5


def test_compare_openapi_semantic_breaks():
    expected = {
        "paths": {"/r": {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}}, "parameters": [{"name": "folder", "in": "query", "required": False, "schema": {"type": "string"}}]}}},
        "components": {"schemas": {"A": {"required": ["x"], "properties": {"x": {"const": 1}, "kind": {"enum": ["a"]}}}}},
    }
    changed = {
        "paths": {"/r": {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/B"}}}}, "parameters": [{"name": "folder", "in": "query", "required": True, "schema": {"type": "string"}}]}}},
        "components": {"schemas": {"A": {"required": ["x", "y"], "properties": {"x": {"const": 2}, "kind": {"enum": ["b"]}, "y": {"type": "string"}}}}},
    }
    result = compare_openapi(expected, changed)
    assert any("request model changed" in item for item in result["incompatible"])
    assert any("required flag changed" in item for item in result["incompatible"])
    assert any("adds required properties" in item for item in result["incompatible"])
    assert any("changed type/enum/const" in item for item in result["incompatible"])


def test_doctor_contract_checks_validate_required_versions_and_routes():
    assert contract_issues(valid_openapi()) == []
    broken = valid_openapi()
    broken["components"]["schemas"]["ProjectDeploymentAcknowledgement"]["properties"]["version"] = {"const": 1}
    broken["components"]["schemas"]["ProjectDeploymentAcknowledgement"]["required"].remove("patch")
    broken["paths"]["/api/v1/factory-catalog/prepare"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"] = "#/components/schemas/Other"
    issues = contract_issues(broken)
    assert any("version must be const 2" in item for item in issues)
    assert any("requires patch" in item for item in issues)
    assert any("request model" in item for item in issues)


def test_comparison_rejects_existing_optional_field_becoming_required():
    expected = {"components": {"schemas": {"Body": {"properties": {"x": {"type": "string"}}}}}}
    actual = {"components": {"schemas": {"Body": {"required": ["x"], "properties": {"x": {"type": "string"}}}}}}
    assert compare_openapi(expected, actual)["incompatible"]


def test_comparison_ignores_documentation_but_detects_root_constraints():
    expected = {"components": {"schemas": {"Kind": {"enum": ["a"], "description": "old"}}}}
    actual = {"components": {"schemas": {"Kind": {"enum": ["a"], "description": "new"}}}}
    assert not compare_openapi(expected, actual)["incompatible"]
    actual["components"]["schemas"]["Kind"]["enum"] = ["b"]
    assert compare_openapi(expected, actual)["incompatible"]


def valid_openapi():
    schemas = {
        "CatalogPrepare": {"required": ["folder", "contract_version", "action"], "properties": {"contract_version": {"const": 1}, "folder": {"type": "string"}, "action": {"type": "string"}}},
        "CatalogConfirm": {"required": ["folder", "contract_version", "confirmation_id"], "properties": {"contract_version": {"const": 1}, "folder": {"type": "string"}, "confirmation_id": {"type": "string"}}},
        "CatalogPreview": {"properties": {}},
        "CatalogConfirmed": {"properties": {}},
        "CatalogParameterPrepare": {"required": ["folder", "contract_version", "factory_id", "scale_set_id", "expected_revision", "schema_revision", "templates"], "properties": {"contract_version": {"const": 1}, "folder": {"type": "string"}, "factory_id": {"type": "string"}, "scale_set_id": {"type": "string"}, "expected_revision": {"type": "string"}, "schema_revision": {"type": "string"}, "templates": {"type": "array"}}},
        "ProjectDeploymentAcknowledgement": {"required": ["version", "draft_id", "operation", "patch"], "properties": {"version": {"const": 2}, "draft_id": {"type": "string"}, "operation": {"enum": ["deploy", "update"]}, "patch": {"type": "boolean"}}},
        "ProjectDeploymentPlanBody": {"required": ["folder", "project_number", "source_environment", "target_environment"], "properties": {"folder": {"type": "string"}, "project_number": {"type": "string"}, "source_environment": {"enum": ["dev", "stage", "prod"]}, "target_environment": {"enum": ["dev", "stage", "prod"]}, "patch": {"type": "boolean"}, "operation": {"enum": ["deploy", "update"]}}},
        "ProjectDeploymentPrepareBody": {"required": ["folder", "draft_id"], "properties": {"folder": {"type": "string"}, "draft_id": {"type": "string"}, "patch": {"type": "boolean"}}},
        "ProjectDeploymentStartBody": {"properties": {}},
        "BootstrapPrepare": {"properties": {}},
    }
    paths = {
        "/health": {"get": {}},
        "/api/v1/schema": {"get": {}},
        "/api/v1/azure/auth/status": {"post": {}},
        "/api/v1/factory-catalog": {"get": {}},
        "/api/v1/factory-catalog/settings": {"get": {}},
        "/api/v1/factory-catalog/parameters": {"get": {}},
        "/api/v1/factory-catalog/parameters/confirm": {"post": {}},
        "/api/v1/factory-catalog/jobs": {"get": {}},
        "/api/v1/factory-catalog/jobs/{job_id}": {"get": {}},
        "/api/v1/creation/capabilities": {"get": {}},
        "/api/v1/creation/bootstrap/start": {"post": {}},
        "/api/v1/creation/bootstrap/jobs/{job_id}": {"get": {}},
        "/api/v1/operations/project-deployments": {"get": {}},
        "/api/v1/operations/project-deployments/terminal": {"get": {}},
    }
    refs = {
        "/api/v1/factory-catalog/prepare": "CatalogPrepare",
        "/api/v1/factory-catalog/confirm": "CatalogConfirm",
        "/api/v1/factory-catalog/parameters/prepare": "CatalogParameterPrepare",
        "/api/v1/creation/bootstrap/prepare": "BootstrapPrepare",
        "/api/v1/operations/project-deployments/plan": "ProjectDeploymentPlanBody",
        "/api/v1/operations/project-deployments/prepare": "ProjectDeploymentPrepareBody",
        "/api/v1/operations/project-deployments/start": "ProjectDeploymentStartBody",
    }
    for path, name in refs.items():
        paths[path] = {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{name}"}}}}}}
    return {"info": {"title": "AIFactory Config API", "version": "1"}, "paths": paths, "components": {"schemas": schemas}}
