"""A loopback fake of the Factory API that records every call (the faked transport for the parity test)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

REVISION = "a" * 64
FACTORY_ID = "11111111-1111-4111-8111-111111111111"
SCALESET_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
JOB_ID = "44444444-4444-4444-8444-444444444444"
WORKFLOW_ID = "55555555-5555-4555-8555-555555555555"
CONFIRMATION_ID = "66666666-6666-4666-8666-666666666666"

CATALOG = {"contract_version": 1, "mode": "catalog", "revision": REVISION, "factories": [{
    "id": FACTORY_ID, "key": "aif-121-swedencentral", "kind": "ai", "prefix": "aif-121-", "region": "swedencentral",
    "region_short_name": "sdc",
    "scale_sets": [{"id": SCALESET_ID, "environment": "dev", "suffix": "001", "status": "configured"}],
    "projects": [{"id": PROJECT_ID, "key": "project-001-001", "number": "001", "display_name": "Project 001",
                  "placements": [{"environment": "dev", "scale_set_id": SCALESET_ID}]}],
}]}

PREVIEW = {"contract_version": 1, "confirmation_id": CONFIRMATION_ID, "can_execute": False, "summary": "Review",
           "effects": ["Deploy aif-121-esml-common-sdc-dev-001"], "warnings": [], "blockers": ["Fake API"],
           "expires_at": "2026-10-21T12:10:00Z", "source_revision": REVISION, "operation_mode": "runtime",
           "preview_hash": "b" * 64, "confirmation_phrase": "DELETE aif-121-swedencentral",
           "workflow_id": WORKFLOW_ID,
           "deletion_targets": [{"resource_group": "aif-121-esml-common-sdc-dev-001"}]}

JOB = {"id": JOB_ID, "action": "deploy", "status": "queued", "message": "", "factory_id": FACTORY_ID,
       "created_at": "2026-10-21T12:00:00Z", "updated_at": "2026-10-21T12:00:00Z", "pipeline_runs": []}

OPENAPI = {"openapi": "3.1.0", "components": {"schemas": {"CatalogPrepare": {"properties": {
    "initial_project": {}, "target_region_short_name": {}}}}}}


def _response(method: str, path: str):
    if path == "/openapi.json":
        return OPENAPI
    if method == "GET" and path == "/api/v1/factory-catalog":
        return CATALOG
    if method == "GET" and path.startswith("/api/v1/factory-catalog/jobs/"):
        return JOB
    if method == "GET" and path.startswith("/api/v1/creation/workflows/"):
        return {"workflow_id": WORKFLOW_ID, "status": "running"}
    if path in ("/api/v1/factory-catalog/prepare", "/api/v1/operations/delete-aifactory/prepare",
                "/api/v1/creation/workflows/prepare"):
        return PREVIEW
    if path in ("/api/v1/factory-catalog/confirm", "/api/v1/operations/delete-aifactory/confirm"):
        return {"contract_version": 1, "catalog": CATALOG, "job": JOB}
    if path == "/api/v1/creation/workflows/start":
        return {"workflow_id": WORKFLOW_ID, "status": "running"}
    return None


class FakeFactoryApi:
    def __init__(self, api_key: str = "test-key"):
        self.api_key = api_key
        self.calls: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _handle(self):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                outer.calls.append({"method": self.command, "path": parts.path,
                                    "query": sorted(parse_qsl(parts.query, keep_blank_values=True)),
                                    "body": json.loads(raw) if raw else None,
                                    "key": self.headers.get("X-API-Key") == outer.api_key})
                payload = _response(self.command, parts.path)
                status = 200 if payload is not None else 404
                data = json.dumps(payload if payload is not None else {"detail": "not found"}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
