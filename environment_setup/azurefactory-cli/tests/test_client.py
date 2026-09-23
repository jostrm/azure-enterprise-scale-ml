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
    Handler.responses = {("GET", "/openapi.json"): (200, {
        "components": {"schemas": {"CatalogPrepare": {"properties": {"initial_project": {}}}}},
    }, {})}
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

def test_bootstrap_common_details_is_explicit_and_strict_remains_default(server):
    client = AzureFactoryClient(server, "test-key")
    state = {"admin_aifactoryPrefixRG": "demo-", "enableFunction": True}
    client.bootstrap_config(state)
    assert Handler.records[-1]["body"] == {"state": state}
    client.bootstrap_config(state, mapping_mode="common-details")
    assert Handler.records[-1]["body"] == {"state": state, "mapping_mode": "common-details"}
    assert state["enableFunction"] is True
    with pytest.raises(ConfigError):
        client.bootstrap_config(state, mapping_mode="discard-all")
    assert len(Handler.records) == 2


def test_factory_create_sdk_defers_defaults_and_prepares_only(server):
    client = AzureFactoryClient(server, "test-key")
    scales = [{"environment": "dev", "suffix": "001"}]
    client.factory_create_prepare("C:\\consumer\\azurefactory", prefix="example-", region="swedencentral",
                                  scale_sets=scales)
    assert [record["path"] for record in Handler.records] == ["/openapi.json", "/api/v1/factory-catalog/prepare"]
    record = Handler.records[-1]
    assert record["path"] == "/api/v1/factory-catalog/prepare"
    assert record["body"]["action"] == "create-factory"
    assert "initial_project" not in record["body"]
    assert "aifactory_version" not in record["body"]
    assert "target_region_short_name" not in record["body"]
    assert record["body"]["scale_sets"] == scales


def test_factory_create_sdk_forwards_one_explicit_project_and_version(server):
    client = AzureFactoryClient(server, "test-key")
    project = {"number": "003", "display_name": "Example project"}
    client.factory_create_prepare(
        "C:\\consumer\\azurefactory", prefix="example-", region="swedencentral",
        scale_sets=[{"environment": "dev", "suffix": "001"}],
        initial_project=project, aifactory_version="main", expected_revision="a" * 64,
    )
    assert len(Handler.records) == 2
    body = Handler.records[-1]["body"]
    assert body["initial_project"] == project
    assert body["aifactory_version"] == "main"
    assert body["expected_revision"] == "a" * 64
    assert project["number"] == "003"


def test_factory_create_sdk_preserves_explicit_common_only_and_settings(server):
    client = AzureFactoryClient(server, "test-key")
    client.factory_create_prepare(
        "C:\\consumer\\azurefactory", prefix="example-", region="swedencentral",
        scale_sets=[{"environment": "dev", "suffix": "001"}],
        initial_project=None, settings={"enableAIFactoryHub": "false"},
    )
    body = Handler.records[-1]["body"]
    assert "initial_project" in body and body["initial_project"] is None
    assert body["settings"] == {"enableAIFactoryHub": "false"}


def test_factory_create_sdk_blocks_stale_api_without_preparing(server):
    Handler.responses[("GET", "/openapi.json")] = (200, {"components": {"schemas": {}}}, {})
    with pytest.raises(ConfigError, match="initial_project"):
        AzureFactoryClient(server, "test-key").factory_create_prepare(
            "C:\\consumer\\azurefactory", prefix="example-", region="swedencentral", scale_sets=[],
        )
    assert [record["path"] for record in Handler.records] == ["/openapi.json"]


@pytest.mark.parametrize("supported", [True, False])
def test_factory_create_sdk_region_short_name_is_explicit_and_capability_checked(server, supported):
    properties = {"initial_project": {}}
    if supported:
        properties["target_region_short_name"] = {}
    Handler.responses[("GET", "/openapi.json")] = (
        200, {"components": {"schemas": {"CatalogPrepare": {"properties": properties}}}}, {},
    )
    client = AzureFactoryClient(server, "test-key")
    request = dict(prefix="example-", region="swedencentral", region_short_name="sec", scale_sets=[])
    if supported:
        client.factory_create_prepare("C:\\consumer\\azurefactory", **request)
        assert Handler.records[-1]["body"]["target_region_short_name"] == "sec"
    else:
        with pytest.raises(ConfigError, match="target_region_short_name"):
            client.factory_create_prepare("C:\\consumer\\azurefactory", **request)
        assert [record["path"] for record in Handler.records] == ["/openapi.json"]


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


def test_monitoring_csv_is_accepted_only_at_exact_export_route(server):
    body = {"source": "sample", "report_id": "showback", "rows": []}
    csv = b"project,actual_cost\r\n001,20\r\n"
    Handler.responses[("POST", "/api/v1/monitoring/export")] = (200, csv, {"Content-Type": "text/csv"})
    assert AzureFactoryClient(server, "k").monitoring_export(body) == csv.decode()
    assert Handler.records[-1]["key"] == "k"
    assert Handler.records[-1]["body"] == body
    Handler.responses[("POST", "/api/v1/monitoring/report")] = (200, csv, {"Content-Type": "text/csv"})
    with pytest.raises(APIError, match="non-JSON"):
        AzureFactoryClient(server, "k").monitoring_report(body)
    Handler.responses[("POST", "/api/v1/monitoring/export")] = (200, {"wrong": "json"}, {})
    with pytest.raises(APIError, match="text/csv"):
        AzureFactoryClient(server, "k").monitoring_export(body)
