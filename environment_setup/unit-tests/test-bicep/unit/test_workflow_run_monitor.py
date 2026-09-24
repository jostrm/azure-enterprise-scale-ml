"""No-cloud contract tests for the shared read-only workflow monitor."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import json
import multiprocessing
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("workflow_run_monitor", ROOT / "bootstrap" / "lib" / "workflow_run_monitor.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class Clock:
    def __init__(self):
        self.now = 1_800_000_000

    def __call__(self):
        return self.now

    def advance(self, seconds=15):
        self.now += seconds


def observed(status="queued", conclusion=None, attempt=1, repository="owner/repo", run_id=42):
    return {"repository": repository, "run_id": run_id, "run_attempt": attempt, "status": status,
            "conclusion": conclusion, "head_sha": "a" * 40,
            "html_url": f"https://github.com/{repository}/actions/runs/{run_id}"}


def raw_observed(**kwargs):
    data = observed(**kwargs)
    return {**data, "id": data["run_id"], "repository": {"full_name": data["repository"]}}


class Reader:
    def __init__(self):
        self.data, self.calls = observed(), []

    def __call__(self, repository, run_id):
        self.calls.append((repository, run_id))
        if isinstance(self.data, Exception):
            raise self.data
        return {**self.data, "repository": repository, "run_id": run_id,
                "html_url": f"https://github.com/{repository}/actions/runs/{run_id}"}


@pytest.fixture
def harness(tmp_path):
    clock, reader = Clock(), Reader()
    monitor = core.WorkflowRunMonitor(tmp_path / "events.db", reader=reader, clock=clock,
                                     sleeper=clock.advance, background=False)
    yield monitor, clock, reader
    monitor.close()


@pytest.mark.parametrize("repository,run_id", [
    ("https://github.com/a/b", 1), ("a/b?x=1", 1), ("a/..", 1), ("a/b/c", 1),
    ("a/b", 0), ("a/b", -1), ("a/b", True), ("a/b", "42"), ("a/b", 2**63),
    ("-flag/repo", 42), ("owner/repo\nsecret", 1),
])
def test_identity_is_fixed_and_strict(repository, run_id):
    with pytest.raises(core.MonitorError):
        core.validate_identity(repository, run_id)


def test_consumers_share_snapshot_polling_and_stop_when_unused(harness):
    monitor, clock, reader = harness
    a = monitor.subscribe("Owner/Repo", 42)
    b = monitor.subscribe("owner/repo", 42)
    assert a.next_event(0)["event_type"] == b.next_event(0)["event_type"] == "snapshot"
    monitor.status("owner/repo", 42)
    for _ in range(3):
        monitor.poll_once()
    assert len(reader.calls) == 1
    reader.data = observed("in_progress")
    clock.advance()
    monitor.poll_once()
    event = a.next_event(0)
    assert event == b.next_event(0)
    assert event["event_type"] == "in_progress"
    a.close()
    b.close()
    clock.advance()
    monitor.poll_once()
    assert len(reader.calls) == 2
    assert all(entry.users == 0 for entry in monitor.entries.values())


@pytest.mark.parametrize("conclusion", ["success", "failure", "neutral", "skipped", "cancelled", "timed_out", "action_required"])
def test_terminal_conclusions_are_not_rewritten(harness, conclusion):
    monitor, clock, reader = harness
    subscription = monitor.subscribe("owner/repo", 42)
    subscription.next_event(0)
    reader.data = observed("completed", conclusion)
    clock.advance()
    monitor.poll_once()
    final = subscription.next_event(0)
    assert final["status"] == "completed" and final["conclusion"] == conclusion
    assert subscription.next_event(0) is None and subscription.closed
    clock.advance()
    monitor.poll_once()
    assert len(reader.calls) == 2


def test_restart_completed_run_rechecks_for_new_attempt(harness, tmp_path):
    monitor, clock, reader = harness
    reader.data = observed("completed", "neutral")
    old = monitor.status("owner/repo", 42)
    monitor.close()
    reader.data = observed("queued", attempt=2)
    restarted = core.WorkflowRunMonitor(tmp_path / "events.db", reader=reader, clock=clock,
                                       sleeper=clock.advance, background=False)
    try:
        subscription = restarted.subscribe("owner/repo", 42, after=old["event_id"])
        event = subscription.next_event(0)
        assert event["run_attempt"] == 2 and event["status"] == "queued"
        assert event["conclusion"] is None and event["event_id"] != old["event_id"]
        assert len(reader.calls) == 2
        subscription.close()
    finally:
        restarted.close()


def test_persisted_ordered_replay_deduplicates_and_is_owner_scoped(harness):
    monitor, clock, reader = harness
    sub = monitor.subscribe("owner/repo", 42)
    first = sub.next_event(0)
    clock.advance()
    monitor.poll_once()
    assert sub.next_event(0) is None
    reader.data = observed("in_progress")
    clock.advance()
    monitor.poll_once()
    second = sub.next_event(0)
    replay = monitor.subscribe("owner/repo", 42, after=first["event_id"], follow=False)
    assert replay.next_event(0) == second
    assert replay.next_event(0) is None and replay.closed
    with pytest.raises(core.MonitorError, match="another scope"):
        monitor.subscribe("owner/repo", 43, after=first["event_id"])
    with pytest.raises(core.MonitorError, match="another scope"):
        monitor.subscribe("owner/repo", 42, owner="another", after=first["event_id"])
    with pytest.raises(core.MonitorError, match="Invalid"):
        monitor.subscribe("owner/repo", 42, after="secret\n")
    sub.close()


def test_network_failure_preserves_state_and_recovers_with_backoff(harness):
    monitor, clock, reader = harness
    sub = monitor.subscribe("owner/repo", 42)
    first = sub.next_event(0)
    reader.data = core.MonitorError("token ghp_should_never_be_saved", 429, 120)
    clock.advance()
    monitor.poll_once()
    failure = sub.next_event(0)
    assert failure["event_type"] == "monitor_error"
    assert failure["monitor_status"] == "error" and failure["stale"] is True
    assert failure["status"] == first["status"] and failure["conclusion"] is None
    assert "ghp_" not in json.dumps(failure)
    clock.advance(119)
    monitor.poll_once()
    assert len(reader.calls) == 2
    reader.data = observed("in_progress")
    clock.advance(1)
    monitor.poll_once()
    recovery = sub.next_event(0)
    assert recovery["event_type"] == "monitor_recovered"
    assert recovery["monitor_status"] == "ok" and recovery["stale"] is False
    assert sub.next_event(0)["status"] == "in_progress"
    assert "ghp_" not in Path(monitor.database).read_bytes().decode("latin1")
    sub.close()


def test_initial_error_does_not_fabricate_workflow_status(harness):
    monitor, clock, reader = harness
    reader.data = OSError("private-token")
    event = monitor.status("owner/repo", 42)
    assert event["event_type"] == "monitor_error"
    assert event["status"] is None and event["conclusion"] is None
    assert "private-token" not in json.dumps(event)
    subscription = monitor.subscribe("owner/repo", 42)
    snapshot = subscription.next_event(0)
    assert snapshot["event_type"] == "snapshot" and snapshot["status"] is None
    assert snapshot["monitor_status"] == "error" and snapshot["stale"] is True
    assert snapshot["message"]
    reader.data = observed("in_progress")
    clock.advance(30)
    monitor.poll_once()
    recovered = subscription.next_event(0)
    assert recovered["event_type"] == "monitor_recovered"
    assert recovered["monitor_status"] == "ok" and recovered["stale"] is False
    assert recovered["status"] == "in_progress" and recovered["run_attempt"] == 1
    subscription.close()


def test_retention_rejects_lost_cursor_explicitly(harness):
    monitor, clock, reader = harness
    monitor.retention = 2
    sub = monitor.subscribe("owner/repo", 42)
    first = sub.next_event(0)
    for status in ("in_progress", "queued", "in_progress"):
        reader.data = observed(status)
        clock.advance()
        monitor.poll_once()
    with pytest.raises(core.MonitorError, match="expired"):
        sub.next_event(0)
    assert sub.closed
    with pytest.raises(core.MonitorError, match="retained history"):
        monitor.subscribe("owner/repo", 42, after=first["event_id"])


def test_follow_false_and_capacity_eviction(harness):
    monitor, clock, reader = harness
    monitor.max_entries = 1
    sub = monitor.subscribe("owner/repo", 42, follow=False)
    with pytest.raises(core.MonitorError, match="capacity"):
        monitor.status("owner/repo", 43)
    assert sub.next_event(0)["event_type"] == "snapshot"
    assert sub.next_event(0) is None and sub.closed
    assert monitor.status("owner/repo", 43)["run_id"] == 43
    assert len(monitor.entries) == 1
    clock.advance(301)
    monitor._evict(clock())
    assert not monitor.entries


def test_two_instances_coordinate_the_same_sqlite_lease(tmp_path):
    clock, reader = Clock(), Reader()
    entered, release = threading.Event(), threading.Event()

    def blocked(repository, run_id):
        entered.set()
        assert release.wait(5)
        return reader(repository, run_id)

    a = core.WorkflowRunMonitor(tmp_path / "shared.db", reader=blocked, clock=clock, background=False)
    b = core.WorkflowRunMonitor(tmp_path / "shared.db", reader=blocked, clock=clock, background=False)
    try:
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(a.status, "owner/repo", 42)
            assert entered.wait(3)
            second = pool.submit(b.status, "owner/repo", 42)
            release.set()
            assert first.result(5)["event_id"] == second.result(5)["event_id"]
        assert len(reader.calls) == 1
    finally:
        release.set()
        a.close()
        b.close()


def test_gh_transport_uses_only_fixed_read_arguments_and_host_signin(monkeypatch):
    calls = []
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GH_HOST", "evil.invalid")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr="private", stdout="HTTP/2.0 200 OK\n\n" + json.dumps(raw_observed()))

    event = core.GhRunReader(run=run, executable="gh.exe")("Owner/Repo", 42)
    args, kwargs = calls[0]
    assert args[:7] == ["gh.exe", "api", "--hostname", "github.com", "--method", "GET", "--include"]
    assert args[-1] == "repos/owner/repo/actions/runs/42"
    assert kwargs["shell"] is False and kwargs["timeout"] == 30
    assert kwargs["env"]["GH_PROMPT_DISABLED"] == "1"
    assert not any(argument in ("auth", "login") for argument in args)
    assert "GH_TOKEN" not in kwargs["env"] and kwargs["env"]["GH_HOST"] == "github.com"
    assert event["status"] == "queued" and "private" not in json.dumps(event)


@pytest.mark.parametrize("status", [403, 429])
def test_gh_rate_limit_retry_after_and_reset(status):
    clock = Clock()
    response = f"HTTP/2.0 {status} denied\nRetry-After: 90\nX-RateLimit-Reset: {clock()+180}\n\nsecret"
    reader = core.GhRunReader(clock=clock, executable="gh", run=lambda *a, **k:
                             SimpleNamespace(returncode=1, stdout=response, stderr="token"))
    with pytest.raises(core.MonitorError) as caught:
        reader("owner/repo", 42)
    assert caught.value.retry_after == 180
    assert "secret" not in str(caught.value) and "token" not in str(caught.value)


def test_gh_rejects_untrusted_response_urls_and_timeout():
    data = raw_observed()
    data["html_url"] = "https://evil.invalid/token"
    reader = core.GhRunReader(executable="gh", run=lambda *a, **k:
                             SimpleNamespace(returncode=0, stdout="HTTP/2 200\n\n" + json.dumps(data), stderr=""))
    with pytest.raises(core.MonitorError, match="differently scoped"):
        reader("owner/repo", 42)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret", 30)

    with pytest.raises(core.MonitorError, match="connectivity"):
        core.GhRunReader(executable="gh", run=timeout)("owner/repo", 42)


def _process_status(database, start, result):
    def reader(repository, run_id):
        result.put(("read", run_id))
        return observed()

    monitor = core.WorkflowRunMonitor(database, reader=reader, background=False)
    try:
        start.wait(10)
        result.put(("event", monitor.status("owner/repo", 42)["event_id"]))
    finally:
        monitor.close()


def test_separate_processes_share_durable_poll_lease(tmp_path):
    database = str(tmp_path / "processes.db")
    core.WorkflowRunMonitor(database, reader=Reader(), background=False).close()
    context = multiprocessing.get_context("spawn")
    start, result = context.Event(), context.Queue()
    processes = [context.Process(target=_process_status, args=(database, start, result)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        start.set()
        messages = [result.get(timeout=15) for _ in range(3)]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert sum(kind == "read" for kind, _ in messages) == 1
        assert len({value for kind, value in messages if kind == "event"}) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        result.close()


def test_cancellation_wakes_waiter_without_remote_actions(harness):
    monitor, _, reader = harness
    sub = monitor.subscribe("owner/repo", 42)
    sub.next_event(0)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(sub.next_event, 15)
        sub.close()
        assert future.result(2) is None
    assert sub.closed and len(reader.calls) == 1


def test_poll_interval_cannot_be_reduced(tmp_path):
    clock, reader = Clock(), Reader()
    monitor = core.WorkflowRunMonitor(tmp_path / "minimum.db", reader=reader,
                                     poll_interval=0, clock=clock, background=False)
    try:
        monitor.status("owner/repo", 42)
        clock.advance(14)
        monitor.status("owner/repo", 42)
        assert len(reader.calls) == 1
        clock.advance(1)
        monitor.status("owner/repo", 42)
        assert len(reader.calls) == 2
    finally:
        monitor.close()


@pytest.mark.parametrize("status", ["queued", "pending", "waiting", "requested", "in_progress", "completed"])
def test_poll_events_preserve_status_without_fabricating_stages(harness, status):
    monitor, _, reader = harness
    reader.data = observed(status, "success" if status == "completed" else None)
    subscription = monitor.subscribe("owner/repo", 42, follow=False)
    snapshot = subscription.next_event(0)
    assert snapshot["event_type"] == "snapshot" and snapshot["status"] == status
    assert snapshot["monitor_status"] == "ok" and snapshot["stale"] is False
    with monitor._db() as db:
        rows = db.execute("SELECT payload FROM workflow_events").fetchall()
    assert len(rows) == 1
    expected_type = status if status in ("requested", "in_progress", "completed") else "status_changed"
    assert json.loads(rows[0]["payload"])["event_type"] == expected_type
    subscription.close()


def test_completed_without_conclusion_is_not_a_trustworthy_terminal_observation(harness):
    monitor, clock, reader = harness
    reader.data = observed("in_progress")
    subscription = monitor.subscribe("owner/repo", 42)
    subscription.next_event(0)
    reader.data = observed("completed", None)
    clock.advance()
    monitor.poll_once()
    event = subscription.next_event(0)
    assert event["event_type"] == "monitor_error" and event["monitor_status"] == "error"
    assert event["status"] == "in_progress" and event["conclusion"] is None
    assert not subscription.closed
    subscription.close()


def test_fresh_terminal_replay_does_not_sleep_or_repoll(harness):
    monitor, clock, reader = harness
    initial = monitor.status("owner/repo", 42)
    reader.data = observed("in_progress")
    clock.advance()
    monitor.status("owner/repo", 42)
    reader.data = observed("completed", "failure")
    clock.advance()
    monitor.status("owner/repo", 42)

    def unexpected_sleep(seconds):
        raise AssertionError("Fresh same-process terminal replay must not wait for a polling interval")

    monitor.sleeper = unexpected_sleep
    subscription = monitor.subscribe("owner/repo", 42, after=initial["event_id"], follow=False)
    assert subscription.next_event(0)["status"] == "in_progress"
    assert subscription.next_event(0)["conclusion"] == "failure"
    assert subscription.next_event(0) is None and subscription.closed
    assert len(reader.calls) == 3


@pytest.mark.parametrize("latest", ["monitor_error", "rerun"])
def test_historical_completion_does_not_end_replay_before_current_state(harness, latest):
    monitor, clock, reader = harness
    initial = monitor.status("owner/repo", 42)
    reader.data = observed("completed", "failure")
    clock.advance()
    monitor.status("owner/repo", 42)
    reader.data = core.MonitorError("offline") if latest == "monitor_error" else observed("queued", attempt=2)
    clock.advance()
    monitor.status("owner/repo", 42)
    subscription = monitor.subscribe("owner/repo", 42, after=initial["event_id"])
    historical = subscription.next_event(0)
    assert historical["status"] == "completed" and historical["conclusion"] == "failure"
    current = subscription.next_event(0)
    if latest == "monitor_error":
        assert current["monitor_status"] == "error" and current["stale"] is True
    else:
        assert current["status"] == "queued" and current["run_attempt"] == 2
    assert subscription.next_event(0) is None and not subscription.closed
    subscription.close()


def test_replay_exhaustion_and_latest_health_share_a_read_transaction(harness):
    monitor, _, _ = harness
    subscription = monitor.subscribe("owner/repo", 42)
    subscription.next_event(0)
    original_db, checks = monitor._db, []

    @contextmanager
    def traced_db():
        with original_db() as db:
            db.set_trace_callback(lambda statement: checks.append(db.in_transaction)
                                  if statement.startswith("SELECT payload,error") else None)
            yield db

    monitor._db = traced_db
    assert subscription.next_event(0) is None and not subscription.closed
    assert checks == [True]
    subscription.close()


def test_initial_completed_snapshot_is_not_itself_the_stream_boundary(harness):
    monitor, clock, reader = harness
    reader.data = observed("completed", "success")
    subscription = monitor.subscribe("owner/repo", 42)
    reader.data = observed("queued", attempt=2)
    clock.advance()
    monitor.status("owner/repo", 42)
    assert subscription.next_event(0)["status"] == "completed"
    current = subscription.next_event(0)
    assert current["status"] == "queued" and current["run_attempt"] == 2
    assert subscription.next_event(0) is None and not subscription.closed
    subscription.close()
