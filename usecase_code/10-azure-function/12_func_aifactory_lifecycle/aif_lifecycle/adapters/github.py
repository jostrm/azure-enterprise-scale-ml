"""GitHub REST client for workflow dispatch, run status and failure log excerpts.

The token (a fine-grained token or GitHub App token limited to the factory repo's Actions) comes from Key Vault
through an app setting reference; it is only sent to the GitHub API host, never to the log storage redirect.
"""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..domain.errors import UpstreamError, UpstreamTimeout, UpstreamUnavailable, ValidationFailed

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_WORKFLOW = re.compile(r"[A-Za-z0-9_.-]+\.ya?ml")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")  # terminal colour codes that Actions keeps in job logs
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
EXCERPT_LINES = 40


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubClient:
    def __init__(self, repository: str, token: str, *, api_url: str = "https://api.github.com", timeout: float = 15.0):
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
            raise ValidationFailed("AIF_GITHUB_REPOSITORY must be owner/repo.")
        if not token:
            raise ValidationFailed("AIF_GITHUB_TOKEN is required for the GitHub executors.")
        if urlparse(api_url).scheme not in ("https", "http"):
            raise ValidationFailed("AIF_GITHUB_API_URL must be an http(s) URL.")
        self._repo = repository
        self._token = token
        self._api = api_url.rstrip("/")
        self._timeout = timeout

    # ----- GitHubPort -----

    def dispatch(self, workflow: str, ref: str, inputs: dict[str, Any]) -> None:
        self._call("POST", f"/actions/workflows/{_workflow(workflow)}/dispatches",
                   body={"ref": ref, "inputs": {key: str(value) for key, value in inputs.items()}})

    def find_run(self, workflow: str, marker: str, created_after: datetime) -> dict[str, Any] | None:
        since = created_after.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._call("GET", f"/actions/workflows/{_workflow(workflow)}/runs",
                          query={"event": "workflow_dispatch", "created": f">={since}", "per_page": 50})
        for run in data.get("workflow_runs") or []:
            if marker in (run.get("display_title") or ""):
                return run
        return None

    def get_run(self, run_id: int) -> dict[str, Any]:
        return self._call("GET", f"/actions/runs/{int(run_id)}")

    def failure_excerpt(self, run_id: int) -> str:
        jobs = self._call("GET", f"/actions/runs/{int(run_id)}/jobs", query={"filter": "latest"}).get("jobs") or []
        failed = next((job for job in jobs if job.get("conclusion") not in (None, "success", "skipped")), None)
        if failed is None:
            return ""
        location = self._redirect(f"/actions/jobs/{int(failed['id'])}/logs")
        if not location:
            return ""
        try:
            with build_opener(ProxyHandler({})).open(Request(location, method="GET"), timeout=self._timeout) as response:
                text = response.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError, socket.timeout):
            return ""
        return "\n".join(_CONTROL.sub("", _ANSI.sub("", line)) for line in text.splitlines()[-EXCERPT_LINES:])

    # ----- transport -----

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "aif-lifecycle-function"}

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        suffix = ("?" + urlencode(query)) if query else ""
        return f"{self._api}/repos/{self._repo}{path}{suffix}"

    def _call(self, method: str, path: str, *, query=None, body=None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        opener = build_opener(ProxyHandler({}), _NoRedirect)
        try:
            with opener.open(Request(self._url(path, query), data=data, method=method, headers=headers),
                             timeout=self._timeout) as response:
                payload = response.read()
        except HTTPError as error:
            raise self._error(error) from None
        except (TimeoutError, socket.timeout):
            raise UpstreamTimeout("GitHub did not answer in time.") from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise UpstreamTimeout("GitHub did not answer in time.") from None
            raise UpstreamUnavailable("GitHub could not be reached.") from None
        return json.loads(payload) if payload else {}

    def _redirect(self, path: str) -> str | None:
        opener = build_opener(ProxyHandler({}), _NoRedirect)
        try:
            with opener.open(Request(self._url(path), method="GET", headers=self._headers()), timeout=self._timeout):
                return None
        except HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                return error.headers.get("Location")
            return None
        except (URLError, TimeoutError, socket.timeout):
            return None

    def _error(self, error: HTTPError) -> UpstreamError:
        try:
            message = json.loads(error.read()).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        detail = f"GitHub answered HTTP {error.code}" + (f": {message}" if message else ".")
        return UpstreamError(detail.replace(self._token, "***"))


def _workflow(name: str) -> str:
    if not _WORKFLOW.fullmatch(name):
        raise ValidationFailed(f"'{name}' is not a workflow file name.")
    return name
