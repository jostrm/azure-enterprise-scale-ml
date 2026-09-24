"""Bounded, read-only GitHub workflow observation over the local API's SSE feed."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import replace
from datetime import datetime
from http.client import HTTPException
from typing import Any, Generator, Iterator, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .errors import APIError, AuthError, ConfigError, RedirectError, RequestTimeout

MAX_FRAME_BYTES = 64 * 1024
MAX_CURSOR_BYTES = 512
MAX_SEEN_EVENTS = 4096
EVENT_TYPES = frozenset({
    "snapshot", "requested", "in_progress", "completed", "status_changed",
    "monitor_error", "monitor_recovered",
})
RUN_STATUSES = frozenset({"queued", "requested", "waiting", "pending", "in_progress", "completed"})
CONCLUSIONS = frozenset({
    "success", "failure", "cancelled", "timed_out", "neutral", "skipped",
    "action_required", "stale", "startup_failure",
})


class _WorkflowEventFields(TypedDict):
    schema_version: int
    event_id: str
    event_type: str
    repository: str
    run_id: int
    run_attempt: int
    status: str | None
    conclusion: str | None
    html_url: str
    head_sha: str | None
    observed_at: str


class WorkflowRunEvent(_WorkflowEventFields, total=False):
    message: str
    monitor_status: str
    stale: bool


class WorkflowMonitorError(APIError):
    """Observation failed; this says nothing about the workflow's outcome."""

    exit_code = 2


def monitoring_unavailable(event: WorkflowRunEvent) -> bool:
    return (event["event_type"] == "monitor_error"
            or event.get("monitor_status") == "error" or event.get("stale") is True)


def validate_scope(repository: str, run_id: int) -> str:
    if (not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", repository)
            or any(part in {".", ".."} for part in repository.split("/"))
            or len(repository) > 256):
        raise ConfigError("Workflow repository must be an exact OWNER/REPO, not a URL.")
    if type(run_id) is not int or run_id <= 0:
        raise ConfigError("Workflow run ID must be a positive integer.")
    return repository.lower()


def validate_cursor(cursor: str | None) -> None:
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_BYTES
        or any(ord(char) < 33 or ord(char) > 126 for char in cursor)
    ):
        raise ConfigError("Workflow cursor must be a nonempty bounded printable ASCII event ID.")


def validate_event(value: Any, repository: str, run_id: int) -> WorkflowRunEvent:
    def invalid() -> None:
        raise WorkflowMonitorError("Workflow API returned an invalid or out-of-scope event.")

    if not isinstance(value, dict):
        invalid()
    required = _WorkflowEventFields.__annotations__
    if any(key not in value for key in required):
        invalid()
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        invalid()
    if value["repository"] != repository or type(value["run_id"]) is not int or value["run_id"] != run_id:
        invalid()
    if not isinstance(value["event_type"], str) or value["event_type"] not in EVENT_TYPES:
        invalid()
    if "monitor_status" in value and (
        not isinstance(value["monitor_status"], str) or value["monitor_status"] not in {"ok", "error"}
    ):
        invalid()
    if "stale" in value and type(value["stale"]) is not bool:
        invalid()
    monitor_error = monitoring_unavailable(value)
    if monitor_error and value["event_type"] not in {"snapshot", "monitor_error"}:
        invalid()
    if value["event_type"] == "snapshot" and monitor_error and (
        value.get("monitor_status") != "error" or value.get("stale") is not True
    ):
        invalid()
    initial_error = monitor_error and value["status"] is None
    if (type(value["run_attempt"]) is not int
            or (value["run_attempt"] != 0 if initial_error else value["run_attempt"] < 1)):
        invalid()
    if not (monitor_error and value["status"] is None) and (
        not isinstance(value["status"], str)
        or value["status"] not in RUN_STATUSES
    ):
        invalid()
    conclusion = value["conclusion"]
    if initial_error and conclusion is not None:
        invalid()
    if conclusion is not None and (not isinstance(conclusion, str) or conclusion not in CONCLUSIONS):
        invalid()
    if not monitor_error and (
        (value["status"] != "completed" and conclusion is not None)
        or (value["event_type"] == "completed" and value["status"] != "completed")
    ):
        invalid()
    try:
        validate_cursor(value["event_id"])
        if value["event_id"] is None:
            invalid()
    except ConfigError:
        invalid()
    if not isinstance(value["html_url"], str):
        invalid()
    try:
        url = urlsplit(value["html_url"])
        if (url.scheme != "https" or url.netloc != "github.com"
                or url.path != f"/{repository}/actions/runs/{run_id}"
                or url.query or url.fragment
                or any(ord(char) < 33 or ord(char) == 127 for char in value["html_url"])):
            invalid()
    except ValueError:
        invalid()
    if initial_error:
        if value["head_sha"] is not None:
            invalid()
    elif not isinstance(value["head_sha"], str) or not value["head_sha"] or len(value["head_sha"]) > 128:
        invalid()
    if not isinstance(value["observed_at"], str) or len(value["observed_at"]) > 64:
        invalid()
    try:
        observed = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            invalid()
    except ValueError:
        invalid()
    result = {key: value[key] for key in required}
    for key in ("monitor_status", "stale"):
        if key in value:
            result[key] = value[key]
    if "message" in value:
        if not isinstance(value["message"], str) or len(value["message"]) > 8192:
            invalid()
        result["message"] = value["message"]
    return result


def get_status(client, repository: str, run_id: int) -> WorkflowRunEvent:
    from .client import redact_secrets

    repository = validate_scope(repository, run_id)
    try:
        result = client.request("GET", "/api/v1/workflow-runs/status",
                                query={"repository": repository, "run_id": run_id})
    except (AuthError, ConfigError, RedirectError, RequestTimeout):
        raise
    except APIError as exc:
        raise WorkflowMonitorError(exc.message, status=exc.status, details=exc.details) from None
    except (OSError, HTTPException):
        raise WorkflowMonitorError("Workflow monitoring disconnected; workflow outcome is unknown.") from None
    return redact_secrets(validate_event(result, repository, run_id), client.api_key)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RequestTimeout("Workflow monitoring timed out; workflow outcome is unknown.")
    return remaining


def _current_status(client, repository: str, run_id: int, deadline: float, attempt: int) -> WorkflowRunEvent:
    bounded_client = replace(client, timeout=min(float(client.timeout), _remaining(deadline)))
    current = get_status(bounded_client, repository, run_id)
    _remaining(deadline)
    if current["run_attempt"] < attempt:
        raise WorkflowMonitorError("Workflow run attempt moved backwards.")
    return current


def _same_terminal(event: WorkflowRunEvent, current: WorkflowRunEvent) -> bool:
    return (current["status"] == "completed" and not monitoring_unavailable(current)
            and all(event[key] == current[key] for key in
                    ("event_id", "run_attempt", "status", "conclusion", "head_sha")))


def _frames(response, deadline: float, read_timeout: float) -> Iterator[tuple[str, str, Any]]:
    buffer = bytearray()
    size = 0
    data: list[str] = []
    event_id = event_type = None
    while True:
        remaining = _remaining(deadline)
        # urllib's HTTPResponse exposes the socket through its buffered reader.
        # Refresh its timeout so heartbeats cannot extend the overall deadline.
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(min(read_timeout, remaining))
        chunk = response.read1(4096)
        _remaining(deadline)
        if not chunk:
            if buffer or data or event_id is not None or event_type is not None:
                raise ConnectionError("Incomplete workflow event stream.")
            return
        buffer.extend(chunk)
        while b"\n" in buffer:
            raw, _, rest = buffer.partition(b"\n")
            buffer = bytearray(rest)
            size += len(raw) + 1
            if size > MAX_FRAME_BYTES:
                raise WorkflowMonitorError("Workflow event exceeded the frame size limit.")
            try:
                line = raw.removesuffix(b"\r").decode("utf-8")
            except UnicodeDecodeError:
                raise WorkflowMonitorError("Workflow event is not UTF-8.") from None
            if not line:
                if data:
                    if event_id is None or event_type is None:
                        raise WorkflowMonitorError("Workflow SSE event is missing its ID or type.")
                    try:
                        payload = json.loads("\n".join(data))
                    except (ValueError, RecursionError):
                        raise WorkflowMonitorError("Workflow SSE event is not valid JSON.") from None
                    yield event_id, event_type, payload
                data = []
                event_id = event_type = None
                size = 0
                continue
            if line.startswith(":"):
                continue
            field, _, text = line.partition(":")
            if text.startswith(" "):
                text = text[1:]
            if field == "data":
                data.append(text)
            elif field == "id":
                event_id = text
            elif field == "event":
                event_type = text
        if size + len(buffer) > MAX_FRAME_BYTES:
            raise WorkflowMonitorError("Workflow event exceeded the frame size limit.")


def watch(
    client, repository: str, run_id: int, after: str | None = None, follow: bool = True,
    *, timeout: float = 300.0, max_retries: int = 3,
    backoff_initial: float = 0.5, backoff_max: float = 8.0,
) -> Generator[WorkflowRunEvent, None, WorkflowRunEvent | None]:
    """Yield validated SSE events, retrying observation only, never a workflow."""
    from .client import _NoRedirect, redact_secrets, validate_endpoint

    repository = validate_scope(repository, run_id)
    validate_cursor(after)
    if type(follow) is not bool:
        raise ConfigError("Workflow follow must be a boolean.")
    for name, value in (("timeout", timeout), ("backoff_initial", backoff_initial), ("backoff_max", backoff_max)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ConfigError(f"Workflow {name} must be a finite positive number.")
    if type(max_retries) is not int or not 0 <= max_retries <= 100:
        raise ConfigError("Workflow max_retries must be an integer from 0 to 100.")
    if not client.api_key:
        raise AuthError("AIFACTORY_API_KEY is required for workflow monitoring.")
    endpoint = validate_endpoint("/api/v1/workflow-runs/events")
    deadline = time.monotonic() + timeout
    cursor = after
    seen = {after} if after else set()
    attempt = 0
    retries = 0
    opener = build_opener(ProxyHandler({}), _NoRedirect)
    while True:
        query = {"repository": repository, "run_id": run_id, "follow": str(follow).lower()}
        headers = {"Accept": "text/event-stream", "X-API-Key": client.api_key, "Cache-Control": "no-cache"}
        if cursor is not None:
            query["after"] = cursor
            headers["Last-Event-ID"] = cursor
        req = Request(str(client.base_url) + endpoint + "?" + urlencode(query), method="GET", headers=headers)
        latest = None
        try:
            with opener.open(req, timeout=min(float(client.timeout), _remaining(deadline))) as response:
                if response.headers.get_content_type() != "text/event-stream":
                    raise WorkflowMonitorError("Workflow monitor did not return text/event-stream.")
                for event_id, event_type, payload in _frames(response, deadline, float(client.timeout)):
                    event = validate_event(payload, repository, run_id)
                    if event_id != event["event_id"] or event_type != event["event_type"]:
                        raise WorkflowMonitorError("Workflow SSE ID/type does not match its envelope.")
                    latest = redact_secrets(event, client.api_key)
                    if event_id in seen:
                        continue
                    if event["run_attempt"] < attempt:
                        raise WorkflowMonitorError("Workflow run attempt moved backwards.")
                    attempt = event["run_attempt"]
                    if len(seen) >= MAX_SEEN_EVENTS:
                        raise WorkflowMonitorError("Workflow observation event limit reached; resume with its last cursor.")
                    seen.add(event_id)
                    cursor = event_id
                    yield latest
                if not follow and latest is not None:
                    if latest["status"] == "completed" and not monitoring_unavailable(latest):
                        current = _current_status(client, repository, run_id, deadline, attempt)
                        if current["event_id"] not in seen:
                            yield current
                        latest = current
                    return latest
                if latest is not None and latest["status"] == "completed" and not monitoring_unavailable(latest):
                    if latest["event_id"] == cursor and _same_terminal(
                        latest, _current_status(client, repository, run_id, deadline, attempt),
                    ):
                        return latest
            if cursor is not None and latest is None:
                # An exhausted replay can legitimately be empty. Confirm through
                # the status endpoint instead of treating EOF as workflow success.
                confirmed = _current_status(client, repository, run_id, deadline, attempt)
                if not follow or (
                    confirmed["event_id"] == cursor and confirmed["status"] == "completed"
                    and not monitoring_unavailable(confirmed)
                ):
                    if confirmed["event_id"] not in seen:
                        yield confirmed
                    return confirmed
        except HTTPError as exc:
            try:
                payload = exc.read(MAX_FRAME_BYTES + 1)
            except (OSError, HTTPException):
                payload = b""
            finally:
                exc.close()
            details = None
            if len(payload) <= MAX_FRAME_BYTES:
                try:
                    details = redact_secrets(json.loads(payload), client.api_key)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    pass
            if 300 <= exc.code < 400:
                raise RedirectError("Refusing to follow workflow API redirect.", status=exc.code) from None
            raise WorkflowMonitorError(
                f"Workflow monitoring returned HTTP {exc.code}; workflow outcome is unknown.",
                status=exc.code, details=details,
            ) from None
        except (URLError, OSError, HTTPException):
            pass
        _remaining(deadline)
        if retries >= max_retries:
            raise WorkflowMonitorError("Workflow monitoring disconnected; workflow outcome is unknown. Retry limit reached.")
        delay = min(backoff_initial * (2 ** retries), backoff_max, _remaining(deadline))
        retries += 1
        time.sleep(delay)
