"""The GitHub REST client: dispatch, run lookup by run-name marker, and log excerpts without leaking the token."""

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import pytest

from aif_lifecycle.adapters.github import GitHubClient
from aif_lifecycle.domain.errors import UpstreamError, ValidationFailed

TOKEN = "ghp_test_token"


class FakeGitHubApi:
    def __init__(self):
        self.calls = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, payload=None, headers=None, text=None):
                data = text.encode() if text is not None else (json.dumps(payload).encode() if payload is not None else b"")
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.calls.append({"method": self.command, "path": parts.path, "query": dict(parse_qsl(parts.query)),
                                    "auth": self.headers.get("Authorization"), "body": body})
                path = parts.path
                if path.endswith("/dispatches"):
                    return self._send(204)
                if path.endswith("/workflows/aif-dummy-step.yml/runs"):
                    return self._send(200, {"workflow_runs": [
                        {"id": 2, "display_title": "aif-step [op/1/other] success", "status": "completed"},
                        {"id": 3, "display_title": "aif-step [op/1/target-rg] failure", "status": "completed",
                         "conclusion": "failure", "html_url": "https://github.com/o/r/actions/runs/3"}]})
                if path.endswith("/actions/runs/3"):
                    return self._send(200, {"id": 3, "status": "completed", "conclusion": "failure"})
                if path.endswith("/actions/runs/3/jobs"):
                    return self._send(200, {"jobs": [{"id": 30, "conclusion": "success"}, {"id": 31, "conclusion": "failure"}]})
                if path.endswith("/actions/jobs/31/logs"):
                    return self._send(302, headers={"Location": outer.url + "/blob/log.txt"})
                if path == "/blob/log.txt":
                    lines = "\n".join(f"2026-10-21T12:00:{i:02d}Z line {i}" for i in range(60))
                    return self._send(200, text=lines)
                if path.endswith("/actions/runs/4/jobs"):
                    return self._send(200, {"jobs": [{"id": 41, "conclusion": "failure"}]})
                if path.endswith("/actions/jobs/41/logs"):
                    return self._send(302, headers={"Location": outer.url + "/blob/ansi.txt"})
                if path == "/blob/ansi.txt":  # shape of a real Actions job log (byor-121, 2026-10-21)
                    return self._send(200, text="\r\n".join([
                        '2026-10-21T21:28:40.4446752Z \x1b[36;1msleep "$DURATION"\x1b[0m',
                        "2026-10-21T21:28:40.4504286Z shell: /usr/bin/bash --noprofile --norc -e -o pipefail {0}",
                        "2026-10-21T21:30:00.3243176Z ##[error]target-rg failed (simulated)",
                        "2026-10-21T21:30:00.3249985Z \x1b[1;31mSimulated failure for target-rg\x1b[0m"]))
                if path.endswith("/actions/runs/404"):
                    return self._send(404, {"message": "Not Found"})
                return self._send(500, {"message": "boom"})

            do_GET = do_POST = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def api():
    fake = FakeGitHubApi()
    yield fake
    fake.close()


@pytest.fixture
def client(api):
    return GitHubClient("jostrm/azure-enterprise-scale-byor-121", TOKEN, api_url=api.url)


def test_dispatch_posts_ref_and_string_inputs_with_the_token(client, api):
    client.dispatch("aif-dummy-step.yml", "main", {"operation_id": "op", "step": "1"})
    call = api.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/repos/jostrm/azure-enterprise-scale-byor-121/actions/workflows/aif-dummy-step.yml/dispatches"
    assert call["body"] == {"ref": "main", "inputs": {"operation_id": "op", "step": "1"}}
    assert call["auth"] == f"Bearer {TOKEN}"


def test_find_run_matches_the_run_name_marker(client, api):
    run = client.find_run("aif-dummy-step.yml", "[op/1/target-rg]", datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
    assert run["id"] == 3
    assert api.calls[0]["query"]["event"] == "workflow_dispatch"
    assert api.calls[0]["query"]["created"] == ">=2026-10-21T12:00:00Z"


def test_failure_excerpt_reads_the_failed_job_log_tail_without_sending_the_token_to_storage(client, api):
    excerpt = client.failure_excerpt(3)
    assert excerpt.splitlines()[-1].endswith("line 59")
    assert len(excerpt.splitlines()) == 40
    blob = [call for call in api.calls if call["path"] == "/blob/log.txt"][0]
    assert blob["auth"] is None


def test_failure_excerpt_strips_terminal_colour_codes(client):
    excerpt = client.failure_excerpt(4)
    assert "\x1b" not in excerpt and "\r" not in excerpt
    assert 'sleep "$DURATION"' in excerpt.splitlines()[0]
    assert excerpt.splitlines()[-1].endswith("Z Simulated failure for target-rg")


def test_errors_become_upstream_errors_without_the_token(client):
    with pytest.raises(UpstreamError) as error:
        client.get_run(404)
    assert TOKEN not in str(error.value.detail)


def test_the_repository_and_token_are_validated():
    with pytest.raises(ValidationFailed):
        GitHubClient("not a repo", TOKEN)
    with pytest.raises(ValidationFailed):
        GitHubClient("o/r", "")
