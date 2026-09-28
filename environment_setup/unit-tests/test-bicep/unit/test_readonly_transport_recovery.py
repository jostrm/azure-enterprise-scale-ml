"""Offline transport retries and coherent provider snapshots; no live services."""

import base64
import copy
import errno
import importlib.util
import io
import json
import socket
import ssl
from http.client import IncompleteRead
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[4]


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_recovery_tests", ROOT / "bootstrap/lib" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fl = load("factory_lifecycle")
ps = load("provider_repository_state")
ARM_URL = fl.ARM + "/subscriptions/reviewed/providers/Microsoft.Resources/deployments/reviewed/whatIf?api-version=2022-09-01"


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live commands and HTTP are forbidden")
    monkeypatch.setattr(fl.subprocess, "run", forbidden)
    monkeypatch.setattr(fl, "build_opener", forbidden)


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(fl.time, "monotonic", lambda: value.now)
    monkeypatch.setattr(fl.time, "sleep", value.sleep)
    return value


class Response(io.BytesIO):
    def __init__(self, body=b'{"ok":true}', error=None, code=200):
        super().__init__(body)
        self.code, self.headers, self.error = code, {"ETag": "reviewed"}, error

    def read(self, size=-1):
        if self.error is not None:
            super().read(3)
            raise self.error
        return super().read(size)


def cloud_with(*results):
    opener = Mock()
    opener.open.side_effect = results
    cloud = fl.Cloud({
        "identity": {"object_id": "reviewed-identity"},
        "target": {"tenant_id": "reviewed-tenant", "subscription_id": "reviewed-subscription"},
        "locks": {"coordination_mode": "single-writer"},
    }, command_runner=Mock(), opener=opener)
    cloud.token = Mock(return_value="synthetic-private-token")
    return cloud, opener


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_read_retries_proven_errno101_after_60_seconds(clock, capsys, method):
    response = Response(body=b"" if method == "HEAD" else b'{"ok":true}')
    cloud, opener = cloud_with()
    def send(request, timeout):
        assert timeout <= 60
        if opener.open.call_count == 1:
            clock.now += 60
            raise URLError(OSError(errno.ENETUNREACH, "Network is unreachable"))
        return response
    opener.open.side_effect = send
    assert cloud.request(method, ARM_URL, fl.ARM)[2] == (None if method == "HEAD" else {"ok": True})
    assert opener.open.call_count == 2
    assert cloud.token.call_count == 2
    assert clock.sleeps == [0.25]
    assert response.closed
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["errno"] == errno.ENETUNREACH
    assert diagnostic["reason_type"] == "OSError"
    assert diagnostic["elapsed_seconds"] == 60
    assert diagnostic["retrying"] is True


@pytest.mark.parametrize("failure", [
    TimeoutError("timed out"), URLError(socket.timeout("timed out")),
    ConnectionResetError(errno.ECONNRESET, "reset"),
    ConnectionAbortedError(errno.ECONNABORTED, "aborted"),
    ConnectionRefusedError(errno.ECONNREFUSED, "refused"),
    BrokenPipeError(errno.EPIPE, "broken pipe"),
    URLError(socket.gaierror(socket.EAI_AGAIN, "temporary resolution failure")),
    OSError(errno.EHOSTUNREACH, "host unreachable"), OSError(errno.ENETDOWN, "network down"),
])
def test_specific_transient_read_errors_retry(clock, failure):
    response = Response()
    cloud, opener = cloud_with(failure, response)
    assert cloud.request("GET", ARM_URL, fl.ARM)[2] == {"ok": True}
    assert opener.open.call_count == 2 and response.closed


def test_read_exhaustion_keeps_stable_error_code(clock, capsys):
    cloud, opener = cloud_with(*[URLError(OSError(errno.ENETUNREACH, "unreachable")) for _ in range(3)])
    with pytest.raises(fl.Blocked, match="^remote-request-unverified$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert opener.open.call_count == 3
    assert clock.sleeps == [0.25, 0.5]
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [row["attempt"] for row in entries] == [1, 2, 3]
    assert [row["retrying"] for row in entries] == [True, True, False]


@pytest.mark.parametrize("failure", [
    URLError(ssl.SSLCertVerificationError(1, "certificate invalid")),
    ssl.SSLError(1, "TLS protocol invalid"),
    URLError(socket.gaierror(socket.EAI_NONAME, "permanent DNS failure")),
    PermissionError(errno.EACCES, "denied"), OSError(errno.EINVAL, "invalid"),
    URLError("unknown transport problem"), OSError("unknown transport problem"),
])
def test_permanent_or_unknown_transport_failure_is_not_retried(clock, failure):
    cloud, opener = cloud_with(failure, Response())
    with pytest.raises(fl.Blocked, match="^remote-request-unverified$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert opener.open.call_count == 1
    assert not clock.sleeps


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("during_body", [False, True])
def test_mutations_including_what_if_post_remain_single_attempt(clock, method, during_body):
    failure = TimeoutError("response lost")
    first = Response(error=failure) if during_body else failure
    cloud, opener = cloud_with(first, Response())
    with pytest.raises(fl.Blocked, match="^remote-request-unverified$"):
        cloud.request(method, ARM_URL, fl.ARM, data={"private": "payload"})
    assert opener.open.call_count == 1 and not clock.sleeps
    if during_body:
        assert first.closed


@pytest.mark.parametrize("failure", [
    TimeoutError("body timed out"), ConnectionResetError(errno.ECONNRESET, "body reset"),
    IncompleteRead(b"private partial response", 300),
])
def test_read_body_failure_discards_partial_bytes_and_closes_response(clock, failure):
    partial, complete = Response(error=failure), Response()
    cloud, opener = cloud_with(partial, complete)
    assert cloud.request("GET", ARM_URL, fl.ARM)[2] == {"ok": True}
    assert partial.closed and complete.closed and opener.open.call_count == 2


def test_allowed_http_error_body_transport_failure_retries_and_closes(clock):
    partial = Response(error=ConnectionResetError(errno.ECONNRESET, "reset"))
    error = HTTPError(ARM_URL, 400, "unsupported", {}, partial)
    complete = Response(b'{"code":"ResourceTypeNotSupported"}', code=400)
    cloud, opener = cloud_with(error, complete)
    assert cloud.request("GET", ARM_URL, fl.ARM, allowed=(200, 400))[0] == 400
    assert partial.closed and complete.closed and opener.open.call_count == 2


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_http_status_is_not_a_transport_retry(clock, status):
    response = Response(code=status)
    cloud, opener = cloud_with(HTTPError(ARM_URL, status, "private message", {}, response), Response())
    with pytest.raises(fl.Blocked, match="^remote-request-failed-" + str(status) + "$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert response.closed and opener.open.call_count == 1 and not clock.sleeps


def test_error_response_close_failure_cannot_retry_rejected_http_status(clock):
    response = Response(code=403)
    error = HTTPError(ARM_URL, 403, "denied", {}, response)
    def close():
        response.close()
        raise TimeoutError("close failed")
    error.close = close
    cloud, opener = cloud_with(error, Response())
    with pytest.raises(fl.Blocked, match="^remote-request-failed-403$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert response.closed and opener.open.call_count == 1 and not clock.sleeps


@pytest.mark.parametrize("body,code", [
    (b'{"bad":', "invalid-remote-json"), (b"x" * 40, "remote-response-too-large"),
])
def test_response_json_and_size_guards_do_not_retry(clock, monkeypatch, body, code):
    monkeypatch.setattr(fl, "MAX_DOCUMENT", 32)
    response = Response(body)
    cloud, opener = cloud_with(response, Response())
    with pytest.raises(fl.Blocked, match="^" + code + "$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert response.closed and opener.open.call_count == 1 and not clock.sleeps


def test_unknown_exception_is_not_caught_or_retried(clock):
    cloud, opener = cloud_with(RuntimeError("unknown"), Response())
    with pytest.raises(RuntimeError, match="unknown"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert opener.open.call_count == 1 and not clock.sleeps


def test_retry_admission_window_stops_further_attempts(clock):
    cloud, opener = cloud_with()
    def timed_out(*args, **kwargs):
        clock.now += fl.READ_TRANSPORT_RETRY_WINDOW_SECONDS
        raise TimeoutError("timed out")
    opener.open.side_effect = timed_out
    with pytest.raises(fl.Blocked, match="^remote-request-unverified$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert opener.open.call_count == 1 and not clock.sleeps


def test_next_socket_timeout_is_capped_by_remaining_retry_window(clock):
    response = Response()
    cloud, opener = cloud_with()
    def send(*args, **kwargs):
        if opener.open.call_count == 1:
            clock.now += fl.READ_TRANSPORT_RETRY_WINDOW_SECONDS - 0.4
            raise TimeoutError("timed out")
        assert kwargs["timeout"] == pytest.approx(0.15)
        return response
    opener.open.side_effect = send
    assert cloud.request("GET", ARM_URL, fl.ARM)[2] == {"ok": True}
    assert opener.open.call_count == 2


@pytest.mark.parametrize("api", ["2022-09-01", "secret-query-value"])
def test_transport_log_redacts_all_non_api_query_headers_body_and_error_text(clock, capsys, api):
    secret = "private-synthetic-secret"
    cloud, opener = cloud_with(URLError(OSError(errno.EINVAL, secret)))
    url = ARM_URL.split("?")[0] + "?api-version=" + api + "&sig=" + secret + "&$filter=" + secret
    with pytest.raises(fl.Blocked):
        cloud.request("GET", url, fl.ARM, data={"secret": secret}, headers={"X-Private": secret})
    captured = capsys.readouterr()
    assert not captured.out and secret not in captured.err and "synthetic-private-token" not in captured.err
    assert "secret-query-value" not in captured.err
    row = json.loads(captured.err)
    assert set(row) == {"event", "method", "host", "path", "api_version", "attempt",
                        "exception_type", "reason_type", "errno", "elapsed_seconds", "retrying"}
    assert row["path"] == urlsplit(ARM_URL).path
    assert row["api_version"] == (api if api == "2022-09-01" else None)


def test_non_numeric_oserror_errno_cannot_leak_into_diagnostics(clock, capsys):
    secret = "private-errno-text"
    cloud, opener = cloud_with(OSError(secret, secret))
    with pytest.raises(fl.Blocked, match="^remote-request-unverified$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    text = capsys.readouterr().err
    assert secret not in text and json.loads(text)["errno"] is None
    assert opener.open.call_count == 1


def jwt(oid, expiry):
    claims = {"oid": oid, "tid": "reviewed-tenant", "exp": expiry}
    return "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"


@pytest.mark.parametrize("after_transport_failure", [False, True])
def test_identity_mismatch_is_never_retried(clock, monkeypatch, after_transport_failure):
    cloud, opener = cloud_with(TimeoutError("timed out"), Response())
    cloud.token = fl.Cloud.token.__get__(cloud)
    cloud.command = Mock(return_value=json.dumps({"accessToken": jwt("wrong-identity", 999999)}))
    if after_transport_failure:
        cloud.tokens[fl.ARM] = jwt("reviewed-identity", 1060.1)
        cloud.token_expiries[fl.ARM] = 1060.1
    monkeypatch.setattr(fl.time, "time", lambda: clock.now)
    with pytest.raises(fl.Blocked, match="^authenticated-identity-mismatch$"):
        cloud.request("GET", ARM_URL, fl.ARM)
    assert opener.open.call_count == int(after_transport_failure)
    assert cloud.command.call_count == 1


def test_expiring_token_is_refreshed_and_revalidated_before_retry(clock, monkeypatch):
    cloud, opener = cloud_with()
    first, second = jwt("reviewed-identity", 1061), jwt("reviewed-identity", 999999)
    cloud.token = fl.Cloud.token.__get__(cloud)
    cloud.command = Mock(side_effect=[json.dumps({"accessToken": first}), json.dumps({"accessToken": second})])
    monkeypatch.setattr(fl.time, "time", lambda: clock.now)
    response = Response()
    def send(request, timeout):
        if opener.open.call_count == 1:
            assert request.get_header("Authorization") == "Bearer " + first
            clock.now += 2
            raise TimeoutError("timed out")
        assert request.get_header("Authorization") == "Bearer " + second
        return response
    opener.open.side_effect = send
    cloud.request("GET", ARM_URL, fl.ARM)
    assert cloud.command.call_count == 2 and opener.open.call_count == 2


def test_untrusted_host_fails_before_auth_or_request(clock):
    cloud, opener = cloud_with(Response())
    with pytest.raises(fl.Blocked, match="^untrusted-service-endpoint$"):
        cloud.request("GET", "https://untrusted.invalid/path?api-version=2022-09-01", fl.ARM)
    cloud.token.assert_not_called()
    opener.open.assert_not_called()


class Snapshots:
    """Immutable Git objects with optional ref movement only after a content GET."""

    def __init__(self, kind="gha", advances=0, corrupt=None):
        self.route = {"kind": kind, "repository": (
            "https://github.com/org/repo" if kind == "gha" else "https://dev.azure.com/org/project/_git/repo")}
        self.head, self.advances, self.corrupt = 1, advances, corrupt
        self.calls, self.private_reads = [], 0
        self.cloud = SimpleNamespace(state_request=self.request)
        self.store = ps.ProviderState(self.cloud, self.route, fl.Blocked)

    def value(self, revision):
        return self.store.empty() | {"active": {"run_id": "run-" + str(revision)},
                                     "records": {"worker": {"revision": revision}}}

    def request(self, kind, method, endpoint, body, allowed):
        self.calls.append((method, endpoint, copy.deepcopy(body)))
        assert method == "GET", "Snapshot reads must never write"
        suffix = endpoint.removeprefix(self.store.base)
        if suffix in ("", "?api-version=7.1"):
            self.private_reads += 1
            if kind == "gha":
                return 200, {}, {"private": self.corrupt != "public",
                                 "full_name": "foreign/repo" if self.corrupt == "foreign" else "org/repo"}
            return 200, {}, {"project": {"visibility": "public" if self.corrupt == "public" else "private"},
                             "remoteUrl": "foreign" if self.corrupt == "foreign" else self.route["repository"]}
        if suffix.startswith("/git/ref/") or suffix.startswith("/refs?"):
            if self.corrupt == "missing":
                return (404, {}, {}) if kind == "gha" else (200, {}, {"value": []})
            if kind == "gha":
                return 200, {}, {"ref": ps.STATE_REF if self.corrupt != "ref" else "refs/heads/other",
                                 "object": {"type": "commit", "sha": f"{self.head:040x}"}}
            rows = [{"name": ps.STATE_REF, "objectId": f"{self.head:040x}"}]
            return 200, {}, {"value": rows * (2 if self.corrupt == "ref" else 1)}
        if suffix.startswith("/git/commits/"):
            return 200, {}, {"tree": {"sha": suffix.rsplit("/", 1)[1]}}
        if suffix.startswith("/git/trees/"):
            return 200, {}, {"truncated": self.corrupt == "tree",
                             "tree": [{"path": "state.json", "type": "blob", "sha": suffix.rsplit("/", 1)[1]}]}
        if suffix.startswith("/git/blobs/") or suffix.startswith("/items?"):
            revision = int(suffix.rsplit("/", 1)[1], 16) if kind == "gha" else int(
                parse_qs(urlsplit(endpoint).query)["versionDescriptor.version"][0], 16)
            value = self.value(revision)
            if self.corrupt == "state":
                value["repository"] = "foreign"
            raw = ps.canonical(value)
            if self.corrupt == "json":
                raw = b"{"
            elif self.corrupt == "duplicate":
                raw = raw[:-1] + b',"schema":1}'
            elif self.corrupt == "oversize":
                raw = b" " * (ps.MAX_BYTES + 1)
            if self.advances:
                self.head += 1
                self.advances -= 1
            if kind == "gha":
                return 200, {}, {"encoding": "base64", "content": base64.b64encode(raw).decode()}
            return 200, {}, {"content": raw.decode()}
        raise AssertionError(endpoint)


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_provider_snapshot_one_ref_advance_returns_only_latest_coherent_state(kind):
    fake = Snapshots(kind, advances=1)
    head, value = fake.store.read()
    assert head == f"{2:040x}" and value == fake.value(2)
    assert fake.private_reads == 2
    assert all(method == "GET" for method, _, _ in fake.calls)
    assert fake.store.write_failed is False


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_provider_snapshot_continual_ref_advance_blocks_after_three_attempts(kind):
    fake = Snapshots(kind, advances=10)
    with pytest.raises(fl.Blocked, match="^single-writer-state-changed$"):
        fake.store.read()
    assert fake.private_reads == 3 and fake.head == 4
    assert all(method == "GET" for method, _, _ in fake.calls)


@pytest.mark.parametrize("kind", ["gha", "ado"])
@pytest.mark.parametrize("corrupt,code", [
    ("public", "single-writer-private-repository-required"),
    ("foreign", "single-writer-private-repository-required"),
    ("json", "single-writer-state-json-invalid"),
    ("duplicate", "single-writer-state-json-invalid"),
    ("state", "single-writer-state-invalid"),
    ("oversize", "single-writer-state-too-large"),
])
def test_invalid_provider_snapshot_never_retries_even_when_ref_advances(kind, corrupt, code):
    fake = Snapshots(kind, advances=10, corrupt=corrupt)
    with pytest.raises(fl.Blocked, match="^" + code + "$"):
        fake.store.read()
    assert fake.private_reads == 1


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_missing_provider_ref_retains_existing_return_type(kind):
    fake = Snapshots(kind, corrupt="missing")
    assert fake.store.read() == (None, None)
    assert fake.private_reads == 1


def test_provider_transport_error_named_state_changed_is_not_a_ref_restart():
    fake = Snapshots()
    fake.cloud.state_request = Mock(side_effect=fl.Blocked("single-writer-state-changed"))
    with pytest.raises(fl.Blocked, match="^single-writer-state-changed$"):
        fake.store.read()
    assert fake.cloud.state_request.call_count == 1


@pytest.mark.parametrize("corrupt,code", [
    ("tree", "single-writer-state-tree-invalid"), ("ref", "single-writer-state-ref-invalid"),
])
def test_provider_shape_guards_remain_immediate(corrupt, code):
    fake = Snapshots(corrupt=corrupt)
    with pytest.raises(fl.Blocked, match="^" + code + "$"):
        fake.store.read()
    assert fake.private_reads == 1


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_provider_cas_conflict_is_not_retried_and_latches_write_failed(kind):
    fake = Snapshots(kind)
    with pytest.raises(fl.Blocked, match="^single-writer-state-cas-conflict$"):
        fake.store.replace("0" * 40, fake.store.empty())
    calls = len(fake.calls)
    assert fake.store.write_failed is True and fake.private_reads == 1
    with pytest.raises(fl.Blocked, match="^single-writer-write-reconciliation-required$"):
        fake.store.replace(f"{fake.head:040x}", fake.store.empty())
    assert len(fake.calls) == calls


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_provider_write_transport_failure_is_one_attempt_and_latches_write_failed(kind):
    fake = Snapshots(kind)
    read_request = fake.request
    mutations = []
    def send(provider, method, endpoint, body, allowed):
        if method != "GET":
            mutations.append((method, endpoint))
            raise fl.Blocked("single-writer-provider-write-or-read-uncertain")
        return read_request(provider, method, endpoint, body, allowed)
    fake.cloud.state_request = send
    with pytest.raises(fl.Blocked, match="^single-writer-provider-write-or-read-uncertain$"):
        fake.store.replace(f"{fake.head:040x}", fake.store.empty())
    assert len(mutations) == 1 and fake.store.write_failed is True
    with pytest.raises(fl.Blocked, match="^single-writer-write-reconciliation-required$"):
        fake.store.replace(f"{fake.head:040x}", fake.store.empty())
    assert len(mutations) == 1
