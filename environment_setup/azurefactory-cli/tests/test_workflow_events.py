from __future__ import annotations

import io
import json
import threading
import time
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from azurefactory import AuthError, AzureFactoryClient, ConfigError, RedirectError
from azurefactory.cli import main
from azurefactory.errors import RequestTimeout
from azurefactory import workflow_events as transport
from azurefactory.workflow_events import WorkflowMonitorError, validate_event


def event(event_id="e1", **changes):
    result = {
        "schema_version": 1, "event_id": event_id, "event_type": "snapshot",
        "repository": "owner/repo", "run_id": 42, "run_attempt": 1,
        "status": "queued", "conclusion": None,
        "html_url": "https://github.com/owner/repo/actions/runs/42",
        "head_sha": "a" * 40, "observed_at": "2026-09-24T07:00:00Z",
    }
    result.update(changes)
    return result


def completed(event_id="done", conclusion="success", **changes):
    return event(event_id, status="completed", conclusion=conclusion, **changes)


def sse(value, *, multiline=False):
    data = json.dumps(value, indent=2 if multiline else None)
    return ("id: " + value["event_id"] + "\r\nevent: " + value["event_type"] + "\r\n"
            + "".join("data: " + line + "\r\n" for line in data.splitlines()) + "\r\n").encode()


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        records = []
        streams = []
        status_event = event()

        def log_message(self, *_):
            pass

        def do_GET(self):
            self.records.append({
                "method": self.command, "url": self.path,
                "key": self.headers.get("X-API-Key"),
                "cursor": self.headers.get("Last-Event-ID"),
                "accept": self.headers.get("Accept"),
            })
            if urlsplit(self.path).path.endswith("/status"):
                status, body, headers = 200, json.dumps(self.status_event).encode(), {"Content-Type": "application/json"}
            else:
                status, body, headers = self.streams.pop(0)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if headers.get("Transfer-Encoding") == "chunked":
                for offset in range(0, len(body), 17):
                    chunk = body[offset:offset + 17]
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            else:
                self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", Handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(2)


def stream(body):
    return 200, body, {"Content-Type": "text/event-stream; charset=utf-8"}


def test_status_and_completed_snapshot_use_only_authenticated_get(server):
    base, handler = server
    client = AzureFactoryClient(base, "private-key")
    assert client.get_workflow_run_status("Owner/REPO", 42) == event()
    handler.streams = [stream(b": heartbeat\r\n\r\n" + sse(completed(), multiline=True))]
    handler.status_event = completed()
    assert list(client.watch_workflow_run("Owner/REPO", 42, timeout=2)) == [completed()]
    assert len(handler.records) == 3
    for record in handler.records:
        assert record["method"] == "GET"
        assert record["key"] == "private-key"
        assert "private-key" not in record["url"]
        assert parse_qs(urlsplit(record["url"]).query)["repository"] == ["owner/repo"]
        assert parse_qs(urlsplit(record["url"]).query)["run_id"] == ["42"]
    assert handler.records[1]["accept"] == "text/event-stream"


def test_reconnect_uses_exact_cursor_and_deduplicates(server):
    base, handler = server
    first = event("opaque:42/attempt-1+seq=2")
    handler.streams = [stream(sse(first)), stream(sse(first) + sse(completed()))]
    handler.status_event = completed()
    observed = list(AzureFactoryClient(base, "key").watch_workflow_run(
        "owner/repo", 42, after="start:1", backoff_initial=0.001,
    ))
    assert observed == [first, completed()]
    streams = [item for item in handler.records if urlsplit(item["url"]).path.endswith("/events")]
    assert [item["cursor"] for item in streams] == ["start:1", first["event_id"]]
    for record in streams:
        query = parse_qs(urlsplit(record["url"]).query)
        assert query["after"] == [record["cursor"]]
        assert query["follow"] == ["true"]


def test_no_follow_returns_current_nonterminal_event(server):
    base, handler = server
    handler.streams = [stream(sse(event()))]
    assert list(AzureFactoryClient(base, "key").watch_workflow_run("owner/repo", 42, follow=False)) == [event()]
    assert parse_qs(urlsplit(handler.records[0]["url"]).query)["follow"] == ["false"]


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_http_errors_are_structured_observation_errors_not_workflow_failure(server, status):
    base, handler = server
    handler.streams = [(status, b'{"detail":"private-key unavailable","token":"hidden"}', {"Content-Type": "application/json"})]
    with pytest.raises(WorkflowMonitorError) as caught:
        list(AzureFactoryClient(base, "private-key").watch_workflow_run("owner/repo", 42))
    assert caught.value.status == status
    assert caught.value.exit_code == 2
    assert caught.value.details == {"detail": "<redacted> unavailable", "token": "<redacted>"}
    assert "private-key" not in str(caught.value)
    assert len(handler.records) == 1


def test_redirect_does_not_forward_auth(server):
    base, handler = server
    handler.streams = [(302, b"", {"Location": base + "/escape?token=do-not-follow"})]
    with pytest.raises(RedirectError):
        list(AzureFactoryClient(base, "private-key").watch_workflow_run("owner/repo", 42))
    assert len(handler.records) == 1


@pytest.mark.parametrize("changes", [
    {"repository": "other/repo"}, {"repository": "OWNER/repo"}, {"run_id": 43},
    {"run_id": True}, {"schema_version": True}, {"schema_version": 2},
    {"run_attempt": 0}, {"run_attempt": True}, {"event_type": "dispatched"},
    {"status": "fake_failure"}, {"status": None}, {"conclusion": ""}, {"conclusion": "success"},
    {"event_type": "completed"},
    {"event_id": None}, {"event_id": ""}, {"event_id": "id\r\nX-API-Key: hidden"},
    {"observed_at": "invalid"}, {"observed_at": "2026-09-24T07:00:00"},
    {"html_url": "https://github.com/owner/repo/actions/runs/43"},
    {"html_url": "https://github.com/owner/repo/actions/runs/%34%32"},
    {"html_url": "https://github.com/owner/repo/actions/runs/42?token=secret"},
    {"html_url": "https://github.com@evil.example/owner/repo/actions/runs/42"},
    {"html_url": "https://github.com/owner/repo/actions/runs/42#secret"},
    {"html_url": "https://github.com/owner/repo/actions/runs/42\n"},
    {"html_url": "http://github.com/owner/repo/actions/runs/42"},
    {"head_sha": None}, {"message": ["invalid"]},
    {"monitor_status": "unknown"}, {"stale": "false"},
    {"monitor_status": "error"}, {"stale": True},
])
def test_invalid_envelopes_are_rejected_without_echoing_values(changes):
    with pytest.raises(WorkflowMonitorError, match="invalid or out-of-scope"):
        validate_event(event(**changes), "owner/repo", 42)


@pytest.mark.parametrize("repository,run_id", [
    ("https://github.com/owner/repo", 42), ("owner/repo?token=private", 42),
    ("owner/../repo", 42), ("owner/%2e%2e", 42), ("owner/..", 42),
    ("owner/repo", 0), ("owner/repo", True), ("owner/repo", "42"),
])
def test_bad_scope_never_opens_a_connection(monkeypatch, repository, run_id):
    monkeypatch.setattr(transport, "build_opener", lambda *_: pytest.fail("must not open"))
    client = AzureFactoryClient(api_key="key")
    with pytest.raises(ConfigError):
        list(client.watch_workflow_run(repository, run_id))
    with pytest.raises(ConfigError):
        client.get_workflow_run_status(repository, run_id)


@pytest.mark.parametrize("options", [
    {"after": "cursor\r\nX-Evil: yes"}, {"after": ""}, {"after": "x" * 513},
    {"after": "é"}, {"follow": "true"}, {"timeout": 0}, {"timeout": float("inf")},
    {"max_retries": -1}, {"max_retries": True}, {"backoff_initial": 0}, {"backoff_max": float("nan")},
])
def test_invalid_watch_options_never_connect(monkeypatch, options):
    monkeypatch.setattr(transport, "build_opener", lambda *_: pytest.fail("must not open"))
    with pytest.raises(ConfigError):
        list(AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42, **options))


def test_auth_is_required_before_opening_stream(monkeypatch):
    monkeypatch.setattr(transport, "build_opener", lambda *_: pytest.fail("must not open"))
    with pytest.raises(AuthError):
        list(AzureFactoryClient(api_key="").watch_workflow_run("owner/repo", 42))


class Response(io.BytesIO):
    def __init__(self, body, content_type="text/event-stream"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


def inject(monkeypatch, *responses):
    pending = list(responses)
    records = []

    class Opener:
        def open(self, request, timeout):
            records.append((request, timeout))
            result = pending.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(transport, "build_opener", lambda *_: Opener())
    return records


def test_stream_closes_on_generator_cancellation(monkeypatch):
    response = Response(sse(event()) + sse(completed()))
    inject(monkeypatch, response)
    events = AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42)
    assert next(events) == event()
    assert not response.closed
    events.close()
    assert response.closed


@pytest.mark.parametrize("raises", [True, False])
def test_callback_closes_subscription_on_cancel_or_exception(monkeypatch, raises):
    response = Response(sse(event()))
    inject(monkeypatch, response)
    observed = []

    def callback(item):
        observed.append(item)
        if raises:
            raise RuntimeError("consumer cancelled")
        return False

    client = AzureFactoryClient(api_key="key")
    if raises:
        with pytest.raises(RuntimeError, match="consumer cancelled"):
            client.subscribe_workflow_run("owner/repo", 42, callback)
    else:
        client.subscribe_workflow_run("owner/repo", 42, callback)
    assert observed == [event()]
    assert response.closed


@pytest.mark.parametrize("body", [
    b"id: e1\nevent: snapshot\ndata: invalid\n\n",
    b"data: {}\n\n", b"id: e1\nevent: snapshot\ndata: \xff\n\n",
    b":" + b"x" * (transport.MAX_FRAME_BYTES + 1),
    b"data: " + b"x" * (transport.MAX_FRAME_BYTES + 1) + b"\n\n",
    sse(event()).replace(b"id: e1", b"id: mismatch"),
    sse(event()).replace(b"event: snapshot", b"event: completed"),
], ids=["invalid-json", "missing-fields", "invalid-utf8", "oversize-comment",
        "oversize-data", "mismatched-id", "mismatched-type"])
def test_malformed_frames_are_bounded_and_not_retried(monkeypatch, body):
    response = Response(body)
    records = inject(monkeypatch, response)
    with pytest.raises(WorkflowMonitorError):
        list(AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42))
    assert response.closed
    assert len(records) == 1


def test_stream_rejects_json_content_type(monkeypatch):
    response = Response(b"{}", "application/json")
    inject(monkeypatch, response)
    with pytest.raises(WorkflowMonitorError, match="text/event-stream"):
        list(AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42))
    assert response.closed


def test_network_reconnects_use_bounded_exponential_backoff(monkeypatch):
    records = inject(monkeypatch, URLError("private-key"), Response(b""), Response(b""), Response(b""))
    delays = []
    monkeypatch.setattr(transport.time, "sleep", delays.append)
    with pytest.raises(WorkflowMonitorError, match="disconnected") as caught:
        list(AzureFactoryClient(api_key="private-key").watch_workflow_run(
            "owner/repo", 42, max_retries=3, backoff_initial=0.25, backoff_max=0.75,
        ))
    assert delays == [0.25, 0.5, 0.75]
    assert len(records) == 4
    assert "private-key" not in str(caught.value)


def test_heartbeat_cannot_extend_deadline(monkeypatch):
    class Heartbeats(Response):
        def read1(self, size):
            time.sleep(0.003)
            return b": heartbeat\r\n\r\n"

    response = Heartbeats(b"")
    inject(monkeypatch, response)
    with pytest.raises(RequestTimeout, match="outcome is unknown"):
        list(AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42, timeout=0.01))
    assert response.closed


def test_truncated_frame_reconnects_without_advancing_cursor(monkeypatch):
    records = inject(monkeypatch, Response(sse(event())[:-2]), Response(sse(completed())))
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: completed())
    assert list(AzureFactoryClient(api_key="key").watch_workflow_run(
        "owner/repo", 42, after="prior", backoff_initial=0.001,
    )) == [completed()]
    assert [record[0].get_header("Last-event-id") for record in records] == ["prior", "prior"]


def test_monitor_error_and_recovery_are_not_fabricated_workflow_transitions(monkeypatch):
    events = [
        event("error", event_type="monitor_error", status=None, run_attempt=0, head_sha=None, message="private-key unreachable"),
        event("recovered", event_type="monitor_recovered"),
        event("running", event_type="in_progress", status="in_progress"),
        completed(event_type="completed"),
    ]
    inject(monkeypatch, Response(b"".join(sse(item) for item in events)))
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: events[-1])
    observed = list(AzureFactoryClient(api_key="private-key").watch_workflow_run("owner/repo", 42))
    assert observed[0]["message"] == "<redacted> unreachable"
    assert [item["event_type"] for item in observed] == ["monitor_error", "monitor_recovered", "in_progress", "completed"]


def test_attempts_can_increase_but_cannot_regress(monkeypatch):
    inject(monkeypatch, Response(sse(event("first")) + sse(event("rerun", run_attempt=2)) + sse(event("stale"))))
    events = AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42)
    assert next(events)["run_attempt"] == 1
    assert next(events)["run_attempt"] == 2
    with pytest.raises(WorkflowMonitorError, match="backwards"):
        next(events)


@pytest.mark.parametrize("conclusion,expected", [
    ("success", 0), ("failure", 5), ("cancelled", 5), ("timed_out", 5),
    ("neutral", 5), ("skipped", 5), ("action_required", 5), ("stale", 5),
    (None, 2),
])
def test_cli_ndjson_has_only_events_and_preserves_outcomes(monkeypatch, capsys, conclusion, expected):
    inject(monkeypatch, Response(sse(event()) + sse(completed(conclusion=conclusion))))
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: completed(conclusion=conclusion))
    code = main(["--api-key", "private-key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json"])
    output = capsys.readouterr()
    assert code == expected
    assert [json.loads(line) for line in output.out.splitlines()] == [event(), completed(conclusion=conclusion)]
    assert ("outcome is unknown" in output.err) if conclusion is None else output.err == ""
    assert "private-key" not in output.out


def test_cli_disconnect_is_nonzero_stderr_and_never_fake_completion(monkeypatch, capsys):
    inject(monkeypatch, Response(sse(event())))
    code = main(["--api-key", "private-key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json", "--max-retries", "0"])
    output = capsys.readouterr()
    assert code == 2
    assert json.loads(output.out) == event()
    assert "disconnected" in output.err
    assert "completed" not in output.out


def test_cli_error_frame_does_not_report_success(monkeypatch, capsys):
    error = event("error", event_type="monitor_error", message="private-key inaccessible")
    inject(monkeypatch, Response(sse(error)))
    code = main(["--api-key", "private-key", "workflow", "watch", "--repository", "owner/repo",
                 "--run-id", "42", "--json", "--no-follow"])
    output = capsys.readouterr()
    assert code == 2
    assert json.loads(output.out)["event_type"] == "monitor_error"
    assert "private-key" not in output.out + output.err
    assert "monitoring" in output.err


def test_cli_status_and_no_follow_are_read_only(server, capsys):
    base, handler = server
    args = ["--api-url", base, "--api-key", "key", "workflow"]
    assert main(args + ["status", "--repository", "owner/repo", "--run-id", "42", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == event()
    handler.streams = [stream(sse(event()))]
    assert main(args + ["watch", "--repository", "owner/repo", "--run-id", "42", "--no-follow"]) == 0
    assert "snapshot queued" in capsys.readouterr().out
    assert all(item["method"] == "GET" for item in handler.records)


def test_watch_deadline_does_not_replace_request_timeout():
    from azurefactory.cli import build_parser

    args = build_parser().parse_args([
        "--timeout", "12", "workflow", "watch", "--repository", "owner/repo",
        "--run-id", "42", "--timeout", "90",
    ])
    assert args.timeout == 12
    assert args.watch_timeout == 90


@pytest.mark.parametrize("snapshot,expected", [(event(), 0), (completed(), 0), (completed(conclusion="failure"), 5)])
def test_resume_at_current_cursor_keeps_outcome_without_duplicate_output(monkeypatch, capsys, snapshot, expected):
    inject(monkeypatch, Response(sse(snapshot)))
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: snapshot)
    code = main(["--api-key", "key", "workflow", "watch", "--repository", "owner/repo",
                 "--run-id", "42", "--after", snapshot["event_id"], "--json", "--no-follow"])
    output = capsys.readouterr()
    assert code == expected
    assert output.out == output.err == ""


def test_status_redacts_api_key_and_discards_unknown_fields(monkeypatch):
    result = event(message="private-key still queued", untrusted_token="private-key")
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: result)
    observed = AzureFactoryClient(api_key="private-key").get_workflow_run_status("owner/repo", 42)
    assert observed["message"] == "<redacted> still queued"
    assert "untrusted_token" not in observed


def test_status_http_error_has_distinct_monitor_exit_code(monkeypatch):
    from azurefactory.errors import APIError

    def request(*_args, **_kwargs):
        raise APIError("Workflow unavailable.", status=403, details={"code": "permission_denied"})

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    with pytest.raises(WorkflowMonitorError) as caught:
        AzureFactoryClient(api_key="key").get_workflow_run_status("owner/repo", 42)
    assert caught.value.status == 403
    assert caught.value.exit_code == 2
    assert caught.value.details == {"code": "permission_denied"}


def test_chunk_boundaries_may_split_crlf_and_utf8(monkeypatch):
    class TinyChunks(Response):
        def read1(self, size):
            return super().read1(min(size, 3))

    snapshot = completed(message="Återansluten 日本語")
    body = sse(snapshot, multiline=True).replace(b"\\u00c5", "Å".encode())
    response = TinyChunks(b":heartbeat\r\n\r\n" + body)
    inject(monkeypatch, response)
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: snapshot)
    assert list(AzureFactoryClient(api_key="key").watch_workflow_run("owner/repo", 42)) == [snapshot]
    assert response.closed


def test_unreadable_http_error_preserves_status_and_closes_response(monkeypatch):
    from urllib.error import HTTPError

    class Unreadable(Response):
        def read(self, size=-1):
            raise ConnectionError("private-key disconnected")

    body = Unreadable(b"")
    inject(monkeypatch, HTTPError("http://127.0.0.1/api", 403, "Forbidden", body.headers, body))
    with pytest.raises(WorkflowMonitorError) as caught:
        list(AzureFactoryClient(api_key="private-key").watch_workflow_run("owner/repo", 42))
    assert caught.value.status == 403
    assert body.closed
    assert "private-key" not in str(caught.value)


@pytest.mark.parametrize("snapshot,extra,expected", [
    (event(), ["--no-follow"], 0),
    (completed(), [], 0),
    (completed(conclusion="failure"), [], 5),
    (event(event_type="monitor_error", status=None, run_attempt=0, head_sha=None), ["--no-follow"], 2),
])
def test_empty_current_replay_confirms_real_status_not_eof_success(server, capsys, snapshot, extra, expected):
    base, handler = server
    handler.status_event = snapshot
    handler.streams = [stream(b": heartbeat\n\n")]
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json",
                 "--after", snapshot["event_id"], *extra])
    output = capsys.readouterr()
    assert code == expected
    assert output.out == ""
    assert [urlsplit(item["url"]).path for item in handler.records] == [
        "/api/v1/workflow-runs/events", "/api/v1/workflow-runs/status",
    ]


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("follow", [True, False])
def test_unavailable_snapshot_preserves_metadata_and_never_implies_completion(monkeypatch, capsys, initial, follow):
    snapshot = (event("offline", status=None, run_attempt=0, head_sha=None)
                if initial else completed("offline"))
    snapshot.update(monitor_status="error", stale=True)
    observations = [snapshot]
    if follow:
        observations += [
            event("recovered", event_type="monitor_recovered", monitor_status="ok", stale=False),
            completed("fresh", event_type="completed", monitor_status="ok", stale=False),
        ]
    inject(monkeypatch, Response(b"".join(sse(item) for item in observations)))
    monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: observations[-1])
    code = main(["--api-key", "key", "workflow", "watch", "--repository", "owner/repo",
                 "--run-id", "42", "--json", *(["--no-follow"] if not follow else [])])
    output = capsys.readouterr()
    assert code == (0 if follow else 2)
    assert [json.loads(line) for line in output.out.splitlines()] == observations
    assert "monitoring error" in output.err


@pytest.mark.parametrize("offline", [True, False])
def test_sdk_consumes_actual_canonical_monitor_snapshots(monkeypatch, capsys, tmp_path, offline):
    import importlib.util
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "bootstrap" / "lib" / "workflow_run_monitor.py"
    spec = importlib.util.spec_from_file_location("canonical_workflow_contract", source)
    canonical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canonical)

    def reader(*_):
        if offline:
            raise canonical.MonitorError("GitHub unavailable.", 403)
        return completed()

    monitor = canonical.WorkflowRunMonitor(tmp_path / "workflow.sqlite3", reader=reader, background=False)
    subscription = None
    try:
        subscription = monitor.subscribe("Owner/REPO", 42, follow=False)
        snapshot = subscription.next_event(timeout=0)
        assert snapshot["event_type"] == "snapshot"
        assert validate_event(snapshot, "owner/repo", 42) == snapshot
        inject(monkeypatch, Response(sse(snapshot)))
        monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: monitor.status("owner/repo", 42))
        code = main(["--api-key", "key", "workflow", "watch", "--repository", "Owner/REPO",
                     "--run-id", "42", "--json", "--no-follow"])
        assert code == (2 if offline else 0)
        assert json.loads(capsys.readouterr().out) == snapshot
    finally:
        if subscription is not None:
            subscription.close()
        monitor.close()


def test_status_completed_without_conclusion_remains_unknown(server, capsys):
    base, handler = server
    handler.status_event = completed(conclusion=None)
    code = main(["--api-url", base, "--api-key", "key", "workflow", "status",
                 "--repository", "owner/repo", "--run-id", "42", "--json"])
    output = capsys.readouterr()
    assert code == 2
    assert json.loads(output.out) == completed(conclusion=None)
    assert "outcome is unknown" in output.err


def test_real_chunked_http_replay_finishes_with_no_follow(server, capsys):
    base, handler = server
    observations = [
        event("running", event_type="in_progress", status="in_progress"),
        completed("done", event_type="completed", conclusion="failure"),
    ]
    handler.streams = [(200, b"".join(sse(item) for item in observations), {
        "Content-Type": "text/event-stream", "Transfer-Encoding": "chunked",
    })]
    handler.status_event = observations[-1]
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json",
                 "--after", "initial", "--no-follow", "--timeout", "3"])
    output = capsys.readouterr()
    assert code == 5
    assert [json.loads(line) for line in output.out.splitlines()] == observations
    assert output.err == ""
    assert len(handler.records) == 2
    assert handler.records[0]["cursor"] == "initial"
    assert urlsplit(handler.records[1]["url"]).path.endswith("/status")


@pytest.mark.parametrize("follow", [True, False])
@pytest.mark.parametrize("newer", ["error", "rerun"])
@pytest.mark.parametrize("resuming", [True, False])
def test_replay_does_not_stop_at_historical_completed(server, capsys, follow, newer, resuming):
    base, handler = server
    observations = [completed("old", event_type="completed")]
    if newer == "error":
        observations.append(completed("error", event_type="monitor_error", monitor_status="error", stale=True))
    else:
        observations.extend([
            event("rerun", event_type="in_progress", run_attempt=2, status="in_progress"),
            completed("new", event_type="completed", run_attempt=2, conclusion="failure"),
        ])
    if not resuming:
        observations.insert(0, event("initial"))
    handler.status_event = observations[-1]
    handler.streams = [stream(b"".join(sse(item) for item in observations))]
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json",
                 "--max-retries", "0",
                 *(["--after", "before-completion"] if resuming else []),
                 *(["--no-follow"] if not follow else [])])
    output = capsys.readouterr()
    assert code == (2 if newer == "error" else 5)
    assert [json.loads(line) for line in output.out.splitlines()] == observations
    assert all(item["method"] == "GET" for item in handler.records)


def test_no_follow_reconciles_newer_health_after_bounded_replay(server, capsys):
    base, handler = server
    old = completed("old", event_type="completed")
    current = completed("error", event_type="monitor_error", monitor_status="error", stale=True)
    handler.streams = [stream(sse(old))]
    handler.status_event = current
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json",
                 "--after", "prior", "--no-follow"])
    output = capsys.readouterr()
    assert code == 2
    assert [json.loads(line) for line in output.out.splitlines()] == [old, current]


@pytest.mark.parametrize("follow", [True, False])
def test_actual_canonical_completion_then_error_replay_is_not_success(monkeypatch, capsys, tmp_path, follow):
    import importlib.util
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "bootstrap" / "lib" / "workflow_run_monitor.py"
    spec = importlib.util.spec_from_file_location("canonical_workflow_replay", source)
    canonical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canonical)
    now = [1_800_000_000.0]
    phase = ["in_progress"]

    def reader(*_):
        if phase[0] == "error":
            raise canonical.MonitorError("GitHub unavailable.", 403)
        return completed() if phase[0] == "completed" else event(status="in_progress")

    monitor = canonical.WorkflowRunMonitor(
        tmp_path / "replay.sqlite3", reader=reader, clock=lambda: now[0], background=False,
    )
    subscription = None
    try:
        first = monitor.status("owner/repo", 42)
        now[0] += 15
        phase[0] = "completed"
        monitor.status("owner/repo", 42)
        now[0] += 15
        phase[0] = "error"
        monitor.status("owner/repo", 42)
        subscription = monitor.subscribe("owner/repo", 42, after=first["event_id"], follow=False)
        replay = []
        while not subscription.closed:
            item = subscription.next_event(timeout=0)
            if item is not None:
                replay.append(item)
        assert [item["event_type"] for item in replay] == ["completed", "monitor_error"]
        inject(monkeypatch, Response(b"".join(sse(item) for item in replay)))
        monkeypatch.setattr(AzureFactoryClient, "request", lambda *_args, **_kwargs: monitor.status("owner/repo", 42))
        code = main(["--api-key", "key", "workflow", "watch", "--repository", "owner/repo",
                     "--run-id", "42", "--json", "--after", first["event_id"], "--max-retries", "0",
                     *(["--no-follow"] if not follow else [])])
        output = capsys.readouterr()
        assert code == 2
        assert [json.loads(line) for line in output.out.splitlines()] == replay
    finally:
        if subscription is not None:
            subscription.close()
        monitor.close()


def test_empty_replay_with_newer_current_cursor_reconnects_without_skipping_history(server, capsys):
    base, handler = server
    history = [
        completed("old", event_type="completed"),
        event("rerun", event_type="in_progress", status="in_progress", run_attempt=2),
        completed("new", event_type="completed", conclusion="failure", run_attempt=2),
    ]
    handler.streams = [stream(b""), stream(b"".join(sse(item) for item in history))]
    handler.status_event = history[-1]
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json",
                 "--after", "initial", "--backoff-initial", "0.001"])
    output = capsys.readouterr()
    assert code == 5
    assert [json.loads(line) for line in output.out.splitlines()] == history
    streams = [item for item in handler.records if urlsplit(item["url"]).path.endswith("/events")]
    assert [item["cursor"] for item in streams] == ["initial", "initial"]


@pytest.mark.parametrize("follow", [True, False])
@pytest.mark.parametrize("newer", ["error", "rerun"])
def test_initial_completed_snapshot_does_not_skip_newer_events_before_eof(server, capsys, follow, newer):
    base, handler = server
    history = [completed("initial")]
    if newer == "error":
        history.append(completed("error", event_type="monitor_error", monitor_status="error", stale=True))
    else:
        history.extend([
            event("rerun", run_attempt=2, event_type="in_progress", status="in_progress"),
            completed("new", run_attempt=2, event_type="completed", conclusion="failure"),
        ])
    handler.status_event = history[-1]
    handler.streams = [stream(b"".join(sse(item) for item in history))]
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json", "--max-retries", "0",
                 *(["--no-follow"] if not follow else [])])
    output = capsys.readouterr()
    assert code == (2 if newer == "error" else 5)
    assert [json.loads(line) for line in output.out.splitlines()] == history


def test_initial_completed_eof_rechecks_health_and_resumes_original_cursor(server, capsys):
    base, handler = server
    old = completed("initial")
    current = completed("error", event_type="monitor_error", monitor_status="error", stale=True)
    handler.streams = [stream(sse(old)), stream(sse(current))]
    handler.status_event = current
    code = main(["--api-url", base, "--api-key", "key", "workflow", "watch",
                 "--repository", "owner/repo", "--run-id", "42", "--json",
                 "--max-retries", "1", "--backoff-initial", "0.001"])
    output = capsys.readouterr()
    assert code == 2
    assert [json.loads(line) for line in output.out.splitlines()] == [old, current]
    streams = [item for item in handler.records if urlsplit(item["url"]).path.endswith("/events")]
    assert [item["cursor"] for item in streams] == [None, "initial"]


@pytest.mark.parametrize("newer", ["error", "rerun"])
def test_actual_captured_initial_completion_keeps_following_newer_state(monkeypatch, capsys, tmp_path, newer):
    import importlib.util
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "bootstrap" / "lib" / "workflow_run_monitor.py"
    spec = importlib.util.spec_from_file_location("canonical_initial_race", source)
    canonical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canonical)
    now = [1_800_000_000.0]
    phase = ["completed"]

    def reader(*_):
        if phase[0] == "error":
            raise canonical.MonitorError("GitHub unavailable.", 403)
        return completed() if phase[0] == "completed" else event(run_attempt=2)

    class StillOpen(Response):
        def read1(self, size):
            chunk = super().read1(size)
            if not chunk:
                raise TimeoutError("Test subscription is still open.")
            return chunk

    monitor = canonical.WorkflowRunMonitor(
        tmp_path / "initial-race.sqlite3", reader=reader, clock=lambda: now[0], background=False,
    )
    subscription = None
    try:
        subscription = monitor.subscribe("owner/repo", 42)
        now[0] += 15
        phase[0] = newer
        monitor.status("owner/repo", 42)
        observations = [subscription.next_event(timeout=0), subscription.next_event(timeout=0)]
        assert observations[0]["event_type"] == "snapshot"
        assert observations[0]["conclusion"] == "success"
        assert subscription.next_event(timeout=0) is None
        assert not subscription.closed
        inject(monkeypatch, StillOpen(b"".join(sse(item) for item in observations)))
        monkeypatch.setattr(AzureFactoryClient, "request",
                            lambda *_args, **_kwargs: pytest.fail("Do not finalize before clean EOF."))
        code = main(["--api-key", "key", "workflow", "watch", "--repository", "owner/repo",
                     "--run-id", "42", "--json", "--max-retries", "0"])
        output = capsys.readouterr()
        assert code == 2
        assert [json.loads(line) for line in output.out.splitlines()] == observations
    finally:
        if subscription is not None:
            subscription.close()
        monitor.close()


def test_actual_initial_completion_finishes_only_after_eof_and_confirmation(monkeypatch, capsys, tmp_path):
    import importlib.util
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "bootstrap" / "lib" / "workflow_run_monitor.py"
    spec = importlib.util.spec_from_file_location("canonical_initial_terminal", source)
    canonical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canonical)

    class CleanEOF(Response):
        eof_seen = False

        def read1(self, size):
            chunk = super().read1(size)
            if not chunk:
                self.eof_seen = True
            return chunk

    monitor = canonical.WorkflowRunMonitor(tmp_path / "terminal.sqlite3", reader=lambda *_: completed(), background=False)
    subscription = None
    try:
        subscription = monitor.subscribe("owner/repo", 42)
        snapshot = subscription.next_event(timeout=0)
        assert subscription.next_event(timeout=0) is None
        assert subscription.closed
        response = CleanEOF(sse(snapshot))
        inject(monkeypatch, response)
        confirmations = []

        def status(*_args, **_kwargs):
            assert response.eof_seen
            confirmations.append(True)
            return monitor.status("owner/repo", 42)

        monkeypatch.setattr(AzureFactoryClient, "request", status)
        code = main(["--api-key", "key", "workflow", "watch", "--repository", "owner/repo",
                     "--run-id", "42", "--json", "--timeout", "2"])
        assert code == 0
        assert json.loads(capsys.readouterr().out) == snapshot
        assert confirmations == [True]
        assert response.closed
    finally:
        if subscription is not None:
            subscription.close()
        monitor.close()
