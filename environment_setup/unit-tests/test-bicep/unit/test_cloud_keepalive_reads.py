"""Offline: Cloud's default opener reuses TLS connections for GET/HEAD only.

Every connection here is a fake; nothing opens a socket.
"""

import http.client
import importlib.util
import ssl
import threading
import time
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import pytest


ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("factory_lifecycle_keepalive", ROOT / "bootstrap/lib/factory_lifecycle.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)
URL = fl.ARM + "/subscriptions/reviewed/resourceGroups/reviewed?api-version=2022-09-01"


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeResponse:
    def __init__(self, connection, status, body, will_close):
        self.connection, self.status, self.body, self.will_close = connection, status, body, will_close
        self.reason = http.client.responses.get(status, "")
        self.headers = http.client.HTTPMessage()
        self.headers["ETag"] = '"reviewed"'
        self.offset = 0

    def read(self, amount=None):
        end = len(self.body) if amount is None else self.offset + amount
        chunk, self.offset = self.body[self.offset:end], min(end, len(self.body))
        if self.offset >= len(self.body):
            self.connection.busy = False
        return chunk

    def isclosed(self):
        return self.offset >= len(self.body)

    def close(self):
        self.connection.busy = False


class Server:
    """Hands out fake HTTPS connections and answers each request from `answer`."""

    def __init__(self, answer=None, latency=0.0):
        self.answer = answer or (lambda connection, method, selector, headers: (200, b'{"ok":true}', False))
        self.latency, self.connections, self.lock = latency, [], threading.Lock()

    def __call__(self, host, timeout=None, context=None):
        connection = FakeConnection(self, host, timeout, context)
        with self.lock:
            self.connections.append(connection)
        return connection


class FakeConnection:
    def __init__(self, server, host, timeout, context):
        self.server, self.host, self.timeout, self.context = server, host, timeout, context
        self.sock, self.busy, self.closed, self.requests = FakeSocket(), False, False, []

    def request(self, method, selector, body=None, headers=None):
        assert not self.busy and not self.closed, "a pooled connection was shared or reused after close"
        self.busy = True
        self.requests.append((method, selector, dict(headers or {})))

    def getresponse(self):
        time.sleep(self.server.latency)
        method, selector, headers = self.requests[-1]
        status, body, will_close = self.server.answer(self, method, selector, headers)
        return FakeResponse(self, status, body, will_close)

    def close(self):
        self.closed, self.busy, self.sock = True, False, None


def handler_for(server, **options):
    return fl.KeepAliveHTTPSHandler(connection_factory=server, **options)


def cloud_for(opener):
    cloud = fl.Cloud({"identity": {"object_id": "reviewed-identity"},
                      "target": {"tenant_id": "reviewed-tenant", "subscription_id": "reviewed-subscription"},
                      "locks": {"coordination_mode": "single-writer"}}, command_runner=Mock(), opener=opener)
    cloud.token = Mock(return_value="synthetic-private-token")
    return cloud


def test_default_cloud_opener_pools_reads_and_still_refuses_redirects():
    cloud = fl.Cloud({"identity": {"object_id": "reviewed-identity"}, "target": {}})
    kinds = [type(handler) for handler in cloud.opener.handlers]
    assert fl.KeepAliveHTTPSHandler in kinds and fl.NoRedirect in kinds
    import urllib.request
    assert urllib.request.HTTPSHandler not in kinds  # replaced, not shadowed


def test_reads_reuse_one_connection_and_never_ask_the_server_to_close():
    server = Server()
    cloud = cloud_for(build_opener(fl.NoRedirect, handler_for(server)))
    for _ in range(3):
        assert cloud.request("GET", URL, fl.ARM) == (200, {"ETag": '"reviewed"'}, {"ok": True})
    assert cloud.request("HEAD", URL, fl.ARM, allowed=(200,))[0] == 200
    assert len(server.connections) == 1
    requests = server.connections[0].requests
    assert [method for method, _, _ in requests] == ["GET", "GET", "GET", "HEAD"]
    assert all("Connection" not in headers and headers["Authorization"] == "Bearer synthetic-private-token"
               for _, _, headers in requests)
    assert requests[0][1] == "/subscriptions/reviewed/resourceGroups/reviewed?api-version=2022-09-01"


@pytest.mark.parametrize("method", ["PUT", "POST", "PATCH", "DELETE"])
def test_writes_keep_urllibs_one_connection_per_request_path(method):
    server = Server()
    handler = handler_for(server)
    seen = []

    def stdlib_open(http_class, request, **options):
        seen.append((http_class, request.get_method()))
        raise URLError("stdlib path reached")

    handler.do_open = stdlib_open
    cloud = cloud_for(build_opener(fl.NoRedirect, handler))
    with pytest.raises(fl.Blocked, match="^remote-request-unverified$"):
        cloud.request(method, URL, fl.ARM, data={"reviewed": True}, allowed=(200, 201, 202))
    assert seen == [(http.client.HTTPSConnection, method)]
    assert server.connections == []


def test_requests_through_a_proxy_tunnel_use_the_stdlib_path():
    server = Server()
    handler = handler_for(server)
    handler.do_open = Mock(return_value="stdlib-response")
    request = Request(URL, method="GET")
    request.set_proxy("proxy.example:8080", "https")
    assert handler.https_open(request) == "stdlib-response"
    assert server.connections == []


@pytest.mark.parametrize("failure", [http.client.RemoteDisconnected("idle close"), ConnectionResetError(104, "reset"),
                                     BrokenPipeError(32, "broken pipe"), ConnectionAbortedError(103, "aborted"),
                                     # A TLS peer that closed an idle session answers the next request with EOF.
                                     ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
                                     ssl.SSLZeroReturnError(6, "TLS/SSL connection has been closed (EOF)")])
def test_a_stale_reused_connection_is_replaced_once(failure):
    def answer(connection, method, selector, headers):
        if connection is server.connections[0] and len(connection.requests) == 2:
            raise failure
        return 200, b'{"ok":true}', False

    server = Server(answer)
    opener = build_opener(fl.NoRedirect, handler_for(server))
    for _ in range(2):
        with opener.open(Request(URL), timeout=30) as response:
            assert response.read() == b'{"ok":true}'
    assert len(server.connections) == 2 and server.connections[0].closed


def test_a_failure_on_a_fresh_connection_is_not_retried_by_the_pool():
    server = Server(lambda *args: (_ for _ in ()).throw(http.client.RemoteDisconnected("closed")))
    with pytest.raises(http.client.RemoteDisconnected):
        build_opener(fl.NoRedirect, handler_for(server)).open(Request(URL), timeout=30)
    assert len(server.connections) == 1 and server.connections[0].closed


def test_unread_or_closing_responses_never_return_to_the_pool():
    bodies = iter([(200, b"x" * 20, False), (200, b"{}", True), (200, b"{}", False), (200, b"{}", False)])
    server = Server(lambda *args: next(bodies))
    opener = build_opener(fl.NoRedirect, handler_for(server, max_body=10))
    with opener.open(Request(URL), timeout=30) as response:
        assert response.read() == b"x" * 10  # bounded; the caller's size check then fails closed
    for _ in range(3):
        opener.open(Request(URL), timeout=30).read()
    first, second, third = server.connections
    assert first.closed and second.closed and not third.closed
    assert len(third.requests) == 2


def test_http_errors_keep_urllib_semantics_and_drain_the_connection():
    statuses = iter([404, 500, 302, 200])
    server = Server(lambda *args: (next(statuses), b'{"error":{"code":"NotFound"}}', False))
    cloud = cloud_for(build_opener(fl.NoRedirect, handler_for(server)))
    assert cloud.request("GET", URL, fl.ARM, allowed=(200, 404)) == (
        404, {"ETag": '"reviewed"'}, {"error": {"code": "NotFound"}})
    with pytest.raises(fl.Blocked, match="^remote-request-failed-500$"):
        cloud.request("GET", URL, fl.ARM)
    with pytest.raises(fl.Blocked, match="^remote-request-failed-302$"):
        cloud.request("GET", URL, fl.ARM)
    assert cloud.request("GET", URL, fl.ARM)[0] == 200
    assert len(server.connections) == 1


def test_each_pooled_request_gets_its_own_timeout():
    server = Server()
    opener = build_opener(fl.NoRedirect, handler_for(server))
    for timeout in (12, 34):
        opener.open(Request(URL), timeout=timeout).read()
    connection = server.connections[0]
    assert connection.timeout == 34 and connection.sock.timeouts[-1] == 34


def test_concurrent_reads_never_share_a_connection_and_are_reused_afterwards():
    server = Server(latency=0.02)
    opener = build_opener(fl.NoRedirect, handler_for(server))
    errors = []

    def read():
        try:
            opener.open(Request(URL), timeout=30).read()
        except Exception as error:  # surfaced below
            errors.append(error)

    threads = [threading.Thread(target=read) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    created = len(server.connections)
    assert 1 < created <= 8
    for _ in range(4):
        read()
    assert len(server.connections) == created and not errors


def test_http_error_bodies_remain_readable_from_the_raised_error():
    server = Server(lambda *args: (409, b'{"error":{"code":"Conflict"}}', False))
    with pytest.raises(HTTPError) as raised:
        build_opener(fl.NoRedirect, handler_for(server)).open(Request(URL), timeout=30)
    with raised.value as error:
        assert error.code == 409 and error.read() == b'{"error":{"code":"Conflict"}}'


def _blob_answer(size):
    """A GitHub /git/blobs answer whose base64 content JSON is `size` bytes: Content-Length set, as GitHub does."""
    import base64, json
    content = base64.b64encode(b"s" * size).decode()
    body = json.dumps({"sha": "0b28dc89", "content": "\n".join(content[i:i + 60] for i in range(0, len(content), 60)) + "\n",
                       "encoding": "base64"}).encode()

    def answer(connection, method, selector, headers):
        return 200, body, False
    return answer, body


def test_pooled_reads_return_a_large_provider_state_blob_whole():
    """aif-138 (2026-10-28): state.json 6.4 MB -> /git/blobs answer 8.9 MB; the pool cut it at MAX_DOCUMENT + 1 and
    state_request raised single-writer-provider-response-invalid after every state read, on the worker and the poll."""
    answer, body = _blob_answer(7 * 1024 * 1024)
    assert fl.MAX_DOCUMENT + 1 < len(body) <= fl.STATE_RESPONSE_MAX
    server = Server(answer)
    cloud = cloud_for(build_opener(fl.NoRedirect, handler_for(server)))
    cloud.command = Mock(return_value="synthetic-github-token")
    status, _, parsed = cloud.state_request("gha", "GET", "repos/reviewed/private/git/blobs/0b28dc89", None, (200,))
    assert status == 200 and parsed["encoding"] == "base64" and len(parsed["content"]) > fl.MAX_DOCUMENT
    assert fl.KeepAliveHTTPSHandler()._max_body == fl.STATE_RESPONSE_MAX + 1
    # Ordinary documents keep their own bound: the caller's size check still fails closed above MAX_DOCUMENT.
    with pytest.raises(fl.Blocked, match="^remote-response-too-large$"):
        cloud.request("GET", URL, fl.ARM)


def test_an_unparseable_provider_response_is_named_before_it_blocks(capsys):
    import json
    truncated = b'{"sha":"0b28dc89","content":"c3Nz'  # a body cut short of its Content-Length

    def answer(connection, method, selector, headers):
        return 200, truncated, False
    server = Server(answer)
    cloud = cloud_for(build_opener(fl.NoRedirect, handler_for(server)))
    cloud.command = Mock(return_value="synthetic-github-token")
    with pytest.raises(fl.Blocked, match="^single-writer-provider-response-invalid$"):
        cloud.state_request("gha", "GET", "repos/reviewed/private/git/blobs/0b28dc89", None, (200,))
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    assert [e["event"] for e in events] == ["single-writer-provider-response-invalid"]
    assert events[0]["method"] == "GET" and events[0]["host"] == "api.github.com"
    assert events[0]["path"] == "/repos/reviewed/private/git/blobs/0b28dc89" and events[0]["status"] == 200
    assert events[0]["bytes"] == len(truncated) and events[0]["content_length"] is None
    assert "synthetic-github-token" not in capsys.readouterr().err
