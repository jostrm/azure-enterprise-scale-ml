import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from azurefactory.cli import main
from azurefactory.client import canonical_json_hash


WORKFLOW = "33333333-3333-4333-8333-333333333333"
CONFIRMATION = "11111111-1111-4111-8111-111111111111"
SCOPE = {"folder": "C:\\consumer\\azurefactory", "factory_id": "factory", "scale_set_id": "scale", "project_id": "project"}


@pytest.fixture
def server():
    records = []
    manifest = {
        "contract": "bounded-full-bootstrap-v1", "approval_mode": "whole-workflow", "workflow_id": WORKFLOW,
        "scope": SCOPE, "source_revision": "a" * 64,
        "stages": [{"stage": "common-deployment"}, {"stage": "project-deployment"}],
        "target": {"subscription_id": "selected"}, "template_fingerprint": "b" * 64,
        "program_fingerprint": "c" * 64,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
    }
    manifest["authorization_hash"] = canonical_json_hash(manifest)
    preview = {
        "contract_version": 1, "workflow_id": WORKFLOW, "confirmation_id": CONFIRMATION,
        "stage": "repository-initialization", "scope": SCOPE, "can_execute": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "effects": ["All selected stages"], "blockers": [], "source_revision": "a" * 64, "input_hash": "b" * 64,
        "review": {"workflow_authorization": manifest, "cost_preview": {
            "advisory": True, "status": "unavailable", "completeness": "partial"}},
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))) if self.command == "POST" else None
            records.append((self.command, self.path, body))
            result = preview if self.path.endswith("/prepare") else {
                "contract_version": 1, "workflow_id": WORKFLOW, "scope": SCOPE,
                "status": "queued" if self.command == "POST" else "succeeded", "requires_review": False}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", records, preview
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def prepare(server, tmp_path):
    url, records, preview = server
    args = ["--api-url", url, "--api-key", "fixture-private-key", "bootstrap", "workflow"]
    body = {"contract_version": 1, "creation_mode": "full-bootstrap", "scope": SCOPE,
            "expected_revision": "a" * 64, "bootstrap_config": {"coordination_mode": "single-writer"}}
    request, receipt = tmp_path / "request.json", tmp_path / "review.json"
    request.write_text(json.dumps(body), encoding="utf-8")
    result = main([*args, "prepare", "--whole-workflow", "--request-json", str(request), "--save-receipt", str(receipt)])
    return args, receipt, result


def test_real_http_one_upfront_start_no_client_approval_loop(server, tmp_path, monkeypatch):
    monkeypatch.setattr("azurefactory.enrollment.core", lambda: pytest.fail("No local provisioning"))
    url, records, preview = server
    args, receipt, result = prepare(server, tmp_path)
    assert result == 0
    assert records[0][2]["approval_mode"] == "whole-workflow"
    assert "cost_preview" in receipt.read_text() and "fixture-private-key" not in receipt.read_text()
    assert main([*args, "start", "--receipt", str(receipt)]) == 2
    assert len(records) == 1
    assert main([*args, "start", "--receipt", str(receipt), "--yes"]) == 0
    assert records[-1][2]["authorization_hash"] == preview["review"]["workflow_authorization"]["authorization_hash"]
    assert main([*args, "status", "--folder", SCOPE["folder"], "--workflow-id", WORKFLOW]) == 0
    assert [row[0] for row in records] == ["POST", "POST", "GET"]
    assert not any("prepare-next" in row[1] for row in records)
    assert main([*args, "continue", "--folder", SCOPE["folder"], "--workflow-id", WORKFLOW,
                 "--authorization-hash", preview["review"]["workflow_authorization"]["authorization_hash"]]) == 0
    assert records[-1][1].endswith("/continue")


@pytest.mark.parametrize("change", ["missing", "tampered", "scope", "expired"])
def test_malformed_upfront_manifest_cannot_be_saved_or_started(server, tmp_path, change):
    _, records, preview = server
    manifest = preview["review"]["workflow_authorization"]
    if change == "missing":
        del preview["review"]["workflow_authorization"]
    elif change == "tampered":
        manifest["stages"].append({"stage": "unreviewed"})
    elif change == "scope":
        manifest["scope"] = {**SCOPE, "project_id": "different"}
    else:
        manifest["expires_at"] = "2020-01-01T00:00:00Z"
    _, receipt, result = prepare(server, tmp_path)
    assert result == 2 and len(records) == 1 and not receipt.exists()
