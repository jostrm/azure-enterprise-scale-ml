from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from azurefactory import APIError, AuthError, AzureFactoryClient, ConfigError, RedirectError


class Handler(BaseHTTPRequestHandler):
    records = []
    responses = {}

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_HEAD(self):
        self._handle(head=True)

    def log_message(self, *_):
        pass

    def _handle(self, head=False):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        parsed = json.loads(body.decode()) if body else None
        type(self).records.append({
            "method": self.command,
            "path": self.path,
            "key": self.headers.get("X-API-Key"),
            "body": parsed,
        })
        status, payload, headers = type(self).responses.get((self.command, self.path), (200, {"ok": True}, {}))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if not head:
            self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())


@pytest.fixture()
def server():
    Handler.records = []
    Handler.responses = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_rejects_unsafe_base_urls_and_endpoint_escape(server):
    with pytest.raises(ConfigError):
        AzureFactoryClient("http://example.com", "k")
    with pytest.raises(ConfigError):
        AzureFactoryClient("http://user:pass@127.0.0.1:1", "k")
    with pytest.raises(ConfigError):
        AzureFactoryClient("http://[::10]:1", "k")
    client = AzureFactoryClient(server, "k")
    with pytest.raises(ConfigError):
        client.request("GET", "https://evil.example/api")
    with pytest.raises(ConfigError):
        client.request("GET", "/api/../escape")
    with pytest.raises(ConfigError):
        client.request("GET", "/api/%2e%2e/escape")
    with pytest.raises(ConfigError):
        client.request("GET", "/api\\escape")


def test_key_required_for_secured_paths_but_not_health(server):
    Handler.responses[("GET", "/health")] = (200, {"status": "ok"}, {})
    assert AzureFactoryClient(server).health()["status"] == "ok"
    with pytest.raises(AuthError):
        AzureFactoryClient(server).schema()


def test_rejects_redirects_before_following(server):
    Handler.responses[("GET", "/health")] = (302, {"detail": "moved"}, {"Location": "http://127.0.0.1/other"})
    with pytest.raises(RedirectError):
        AzureFactoryClient(server).health()


def test_auth_status_payload_and_key(server):
    client = AzureFactoryClient(server, "secret")
    client.auth_status(aifactory_folder="C:\\factory", factory_id="f", scale_set_id=None)
    record = Handler.records[-1]
    assert record["path"] == "/api/v1/azure/auth/status"
    assert record["key"] == "secret"
    assert record["body"] == {"aifactory_folder": "C:\\factory", "factory_id": "f"}


def test_api_key_repr_and_error_redaction(server):
    assert "secret" not in repr(AzureFactoryClient(server, "secret"))
    Handler.responses[("GET", "/api/v1/schema")] = (500, {"detail": "bad secret", "api_key": "secret"}, {})
    with pytest.raises(APIError) as error:
        AzureFactoryClient(server, "secret").schema()
    assert "secret" not in error.value.message
    assert error.value.details["api_key"] == "<redacted>"
    assert error.value.details["detail"] == "bad <redacted>"


@pytest.mark.parametrize("value", [
    {"_json_source": {"path": "private-source-marker"}, "password": "private-value"},
    '{"_json_source":{"path":"private-source-marker"},"password":"private-value"}',
    "private-value",
])
def test_validation_errors_do_not_echo_opaque_state_or_credentials(server, value):
    Handler.responses[("POST", "/api/v1/validation")] = (422, {"detail": [{
        "loc": ["body", "state"], "msg": "Invalid state", "type": "value_error",
        "input": value, "ctx": {"value": "private-value"},
    }]}, {})
    with pytest.raises(APIError) as exc:
        AzureFactoryClient(server, "secret").configuration_validate({})
    assert str(exc.value) == "Invalid state"
    assert "private-source-marker" not in json.dumps(exc.value.details)
    assert "private-value" not in json.dumps(exc.value.details)
    assert "input" not in exc.value.details["detail"][0]
    assert "ctx" not in exc.value.details["detail"][0]


def test_non_json_and_malformed_api_objects(server):
    Handler.responses[("GET", "/plain")] = (200, b"hello", {"Content-Type": "text/plain"})
    with pytest.raises(APIError, match="non-JSON"):
        AzureFactoryClient(server, "k").request("GET", "/plain")
    Handler.responses[("GET", "/api/v1/schema")] = (200, [], {})
    with pytest.raises(APIError):
        AzureFactoryClient(server, "k").schema()
