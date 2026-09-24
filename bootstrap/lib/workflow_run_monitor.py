"""Shared, read-only github.com Actions observations with durable scoped replay.

WorkflowRunMonitor.status() and subscribe() share polling and persisted rate limits.
Subscriptions must be closed by their consumer; closing never cancels a workflow.
Only the Python standard library and an already authenticated GitHub CLI are used.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from uuid import uuid4


class MonitorError(Exception):
    def __init__(self, message, status_code=503, retry_after=15):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = max(15, retry_after)


def validate_identity(repository, run_id):
    if (not isinstance(repository, str) or len(repository) > 140
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}", repository)
            or repository.split("/")[1] in (".", "..")
            or isinstance(run_id, bool) or not isinstance(run_id, int)
            or not 0 < run_id < 2**63):
        raise MonitorError("Use a github.com OWNER/REPO and a positive integer run_id.", 422)
    return repository.lower(), run_id


def _observation(repository, run_id, data):
    statuses = {"requested", "queued", "pending", "waiting", "in_progress", "completed"}
    conclusions = {None, "success", "failure", "neutral", "cancelled", "skipped",
                   "timed_out", "action_required", "stale", "startup_failure"}
    expected = f"https://github.com/{repository}/actions/runs/{run_id}"
    if (not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] != run_id
            or type(data.get("run_attempt")) is not int or data["run_attempt"] < 1
            or not isinstance(data.get("repository"), dict)
            or str(data["repository"].get("full_name", "")).lower() != repository
            or data.get("status") not in statuses or data.get("conclusion") not in conclusions
            or (data.get("status") == "completed" and data.get("conclusion") is None)
            or not isinstance(data.get("html_url"), str) or data["html_url"].lower() != expected
            or not isinstance(data.get("head_sha"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", data["head_sha"])):
        raise MonitorError("GitHub returned an invalid or differently scoped run observation.", 502)
    return {"repository": repository, "run_id": run_id, "run_attempt": data["run_attempt"],
            "status": data["status"], "conclusion": data.get("conclusion"),
            "html_url": expected, "head_sha": data["head_sha"]}


class GhRunReader:
    """GET only, fixed public GitHub host, using the host's existing gh sign-in."""

    def __init__(self, *, run=subprocess.run, executable=None, clock=time.time):
        self.run = run
        self.executable = executable
        self.clock = clock

    def __call__(self, repository, run_id):
        repository, run_id = validate_identity(repository, run_id)
        executable = self.executable or shutil.which("gh.exe" if os.name == "nt" else "gh")
        if not executable:
            raise MonitorError("GitHub CLI is unavailable. Install gh and sign in to github.com.")
        env = {key: value for key, value in os.environ.items()
               if key not in {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN",
                              "GITHUB_ENTERPRISE_TOKEN", "GH_HOST", "GH_DEBUG"}}
        env.update({"GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1",
                    "GH_PAGER": "cat", "GH_DEBUG": ""})
        try:
            result = self.run(
                [executable, "api", "--hostname", "github.com", "--method", "GET",
                 "--include", "-H", "Accept: application/vnd.github+json",
                 "-H", "X-GitHub-Api-Version: 2022-11-28",
                 f"repos/{repository}/actions/runs/{run_id}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, shell=False, env=env,
            )
        except (OSError, subprocess.SubprocessError):
            raise MonitorError("GitHub observation unavailable; check gh sign-in and connectivity.") from None
        # Never expose gh stderr or error bodies: either may contain credential material.
        output = (result.stdout or "").replace("\r\n", "\n")
        header, separator, body = output.partition("\n\n")
        match = re.match(r"HTTP/\S+\s+(\d{3})", header)
        status = int(match.group(1)) if match else 0
        headers = {}
        for line in header.splitlines()[1:]:
            name, colon, value = line.partition(":")
            if colon:
                headers[name.lower()] = value.strip()
        if status in (403, 429):
            delay = 60
            retry = headers.get("retry-after", "")
            try:
                delay = max(delay, float(retry))
            except ValueError:
                try:
                    delay = max(delay, parsedate_to_datetime(retry).timestamp() - self.clock())
                except (ValueError, TypeError, OverflowError):
                    pass
            try:
                delay = max(delay, float(headers.get("x-ratelimit-reset", "0")) - self.clock())
            except ValueError:
                pass
            raise MonitorError("GitHub access is denied or rate limited; monitoring will retry.", status, delay)
        if result.returncode or status != 200 or not separator:
            raise MonitorError("GitHub observation unavailable; verify Actions read access and the exact run.", 503)
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            raise MonitorError("GitHub returned an unreadable run observation.", 502) from None
        return _observation(repository, run_id, data)


class _Entry:
    def __init__(self, key, repository, run_id, now):
        self.key, self.repository, self.run_id = key, repository, run_id
        self.users, self.touched, self.busy = 0, now, False
        self.failure = None
        self.verified = False
        self.lock = threading.Lock()


class WorkflowRunMonitor:
    def __init__(self, database, *, reader=None, poll_interval=15, idle_ttl=300,
                 max_workers=4, max_entries=128, retention=256, clock=time.time,
                 sleeper=time.sleep, background=True):
        self.database = str(database)
        self.reader = reader or GhRunReader(clock=clock)
        self.interval = max(15, poll_interval)
        self.idle_ttl, self.max_entries = idle_ttl, max_entries
        self.retention, self.clock, self.sleeper = max(2, retention), clock, sleeper
        self.condition = threading.Condition(threading.RLock())
        self.entries, self.stopped = {}, False
        self.slots = threading.BoundedSemaphore(max_workers)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gha-status")
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    key TEXT PRIMARY KEY, payload TEXT, error INTEGER NOT NULL DEFAULT 0,
                    next_poll REAL NOT NULL DEFAULT 0, lease TEXT, lease_until REAL NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0, touched REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, cursor TEXT UNIQUE NOT NULL,
                    key TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS workflow_events_scope ON workflow_events(key, sequence);
            """)
        self.thread = None
        if background:
            self.thread = threading.Thread(target=self._schedule, name="gha-status-scheduler", daemon=True)
            self.thread.start()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _acquire(self, repository, run_id, owner):
        repository, run_id = validate_identity(repository, run_id)
        if not isinstance(owner, str) or not owner or len(owner) > 256:
            raise MonitorError("Invalid monitor owner.", 422)
        key = hashlib.sha256(json.dumps([owner, repository, run_id]).encode()).hexdigest()
        with self.condition:
            if self.stopped:
                raise MonitorError("Workflow monitor is closed.")
            now = self.clock()
            self._evict(now)
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= self.max_entries:
                    unused = [item for item in self.entries.values() if not item.users and not item.busy]
                    if unused:
                        del self.entries[min(unused, key=lambda item: item.touched).key]
                    else:
                        raise MonitorError("Workflow monitor capacity reached; retry later.", 503)
                entry = self.entries[key] = _Entry(key, repository, run_id, now)
            entry.users += 1
            entry.touched = now
            return entry

    def _release(self, entry):
        with self.condition:
            entry.users = max(0, entry.users - 1)
            entry.touched = self.clock()
            self.condition.notify_all()

    def _evict(self, now):
        for key, entry in list(self.entries.items()):
            if not entry.users and not entry.busy and now - entry.touched >= self.idle_ttl:
                del self.entries[key]

    def _row(self, key):
        with self._db() as db:
            return db.execute("SELECT * FROM workflow_runs WHERE key=?", (key,)).fetchone()

    def _event(self, db, entry, observation, kind, message=None):
        payload = dict(observation or {
            "repository": entry.repository, "run_id": entry.run_id, "run_attempt": 0,
            "status": None, "conclusion": None, "head_sha": None,
            "html_url": f"https://github.com/{entry.repository}/actions/runs/{entry.run_id}",
        })
        payload.update(schema_version=1, event_id=uuid4().hex, event_type=kind,
                       monitor_status="error" if kind == "monitor_error" else "ok",
                       stale=kind == "monitor_error",
                       observed_at=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat().replace("+00:00", "Z"))
        payload.pop("message", None)
        if message:
            payload["message"] = message
        encoded = json.dumps(payload, separators=(",", ":"))
        db.execute("INSERT INTO workflow_events(cursor,key,payload) VALUES(?,?,?)",
                   (payload["event_id"], entry.key, encoded))
        db.execute("UPDATE workflow_runs SET payload=? WHERE key=?", (encoded, entry.key))
        db.execute("""DELETE FROM workflow_events WHERE key=? AND sequence NOT IN
                   (SELECT sequence FROM workflow_events WHERE key=? ORDER BY sequence DESC LIMIT ?)""",
                   (entry.key, entry.key, self.retention))
        return payload

    def _refresh(self, entry, *, reconnect=False):
        with entry.lock:
            row = self._row(entry.key)
            # A completed run can be rerun with the same ID. Reconnect revalidates it,
            # but must not bypass the central 15-second minimum or rate-limit delay.
            if reconnect and row and row["payload"]:
                old = json.loads(row["payload"])
                if old["status"] == "completed" and not row["error"] and not entry.verified:
                    delay = row["next_poll"] - self.clock()
                    if delay > 0:
                        self.sleeper(delay)
            with self.slots:
                now, lease = self.clock(), uuid4().hex
                with self._db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("INSERT OR IGNORE INTO workflow_runs(key,touched) VALUES(?,?)", (entry.key, now))
                    row = db.execute("SELECT * FROM workflow_runs WHERE key=?", (entry.key,)).fetchone()
                    if row["next_poll"] > now or row["lease_until"] > now:
                        return
                    db.execute("UPDATE workflow_runs SET lease=?,lease_until=?,touched=? WHERE key=?",
                               (lease, now + 60, now, entry.key))
                observation, failure = None, None
                try:
                    observation = self.reader(entry.repository, entry.run_id)
                    # Reader injection does not bypass field validation or secret filtering.
                    observation = _observation(entry.repository, entry.run_id, {
                        **observation, "id": observation.get("run_id"),
                        "repository": {"full_name": observation.get("repository")},
                    })
                except MonitorError as exc:
                    failure = exc
                except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
                    failure = MonitorError("GitHub observation unavailable; monitoring will retry.")
                with self._db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT * FROM workflow_runs WHERE key=?", (entry.key,)).fetchone()
                    if row["lease"] != lease:
                        return
                    previous = json.loads(row["payload"]) if row["payload"] else None
                    failures = row["failures"] + 1 if failure else 0
                    delay = max(self.interval, failure.retry_after, min(900, 15 * 2**min(failures, 6))) if failure else self.interval
                    if failure:
                        if not row["error"]:
                            self._event(db, entry, previous, "monitor_error",
                                        "GitHub observation unavailable; the last observed workflow state is unchanged.")
                    else:
                        if row["error"]:
                            self._event(db, entry, observation, "monitor_recovered", "GitHub monitoring recovered.")
                        changed = previous is None or any(
                            previous.get(field) != observation.get(field)
                            for field in ("run_attempt", "status", "conclusion", "head_sha"))
                        if changed:
                            status = observation["status"]
                            kind = status if status in {"requested", "in_progress", "completed"} else "status_changed"
                            self._event(db, entry, observation, kind)
                        elif not row["error"]:
                            previous["observed_at"] = datetime.fromtimestamp(
                                self.clock(), timezone.utc).isoformat().replace("+00:00", "Z")
                            db.execute("UPDATE workflow_runs SET payload=? WHERE key=?",
                                       (json.dumps(previous, separators=(",", ":")), entry.key))
                    db.execute("""UPDATE workflow_runs SET error=?,failures=?,next_poll=?,
                               lease=NULL,lease_until=0,touched=? WHERE key=?""",
                               (int(failure is not None), failures, self.clock() + delay, self.clock(), entry.key))
                    # Bound durable identities as well as events; expired cursors fail explicitly.
                    db.execute("""DELETE FROM workflow_runs WHERE key IN
                               (SELECT key FROM workflow_runs WHERE lease_until=0 AND key!=?
                                ORDER BY touched DESC LIMIT -1 OFFSET 2047)""", (entry.key,))
                    db.execute("DELETE FROM workflow_events WHERE key NOT IN (SELECT key FROM workflow_runs)")
                if failure is None:
                    entry.verified = True
            with self.condition:
                self.condition.notify_all()

    def _ensure(self, entry, reconnect=False):
        self._refresh(entry, reconnect=reconnect)
        deadline = time.monotonic() + 35
        while True:
            row = self._row(entry.key)
            if row and row["payload"] and not row["lease"]:
                return dict(json.loads(row["payload"]),
                            monitor_status="error" if row["error"] else "ok", stale=bool(row["error"]))
            if time.monotonic() >= deadline:
                raise MonitorError("Another observation is still in progress; retry later.", 503)
            with self.condition:
                self.condition.wait(0.1)
            self._refresh(entry)

    def status(self, repository, run_id, *, owner="local"):
        entry = self._acquire(repository, run_id, owner)
        try:
            payload = self._ensure(entry)
            return dict(payload, event_type="monitor_error" if payload["event_type"] == "monitor_error" else "snapshot")
        finally:
            self._release(entry)

    def subscribe(self, repository, run_id, *, after=None, follow=True, owner="local"):
        entry = self._acquire(repository, run_id, owner)
        try:
            if after is not None:
                self._cursor(entry.key, after)
            payload = self._ensure(entry, reconnect=True)
            # Validate again: retention can move while a reconnect waits for freshness.
            sequence = self._cursor(entry.key, after if after is not None else payload["event_id"])
            snapshot = dict(payload, event_type="snapshot") if after is None else None
            return Subscription(self, entry, sequence, snapshot, follow)
        except BaseException:
            self._release(entry)
            raise

    def _cursor(self, key, cursor):
        if not isinstance(cursor, str) or not re.fullmatch(r"[a-f0-9]{32}", cursor):
            raise MonitorError("Invalid workflow event cursor.", 409)
        with self._db() as db:
            row = db.execute("SELECT sequence FROM workflow_events WHERE key=? AND cursor=?", (key, cursor)).fetchone()
        if not row:
            raise MonitorError("Workflow cursor belongs to another scope or is outside retained history; start a new subscription.", 409)
        return row["sequence"]

    def poll_once(self):
        """Poll currently subscribed identities; also supports deterministic host tests."""
        with self.condition:
            entries = [entry for entry in self.entries.values() if entry.users and not entry.busy]
        for entry in entries:
            row = self._row(entry.key)
            payload = json.loads(row["payload"]) if row and row["payload"] else {}
            if payload.get("status") != "completed" or (row and row["error"]):
                self._refresh(entry)

    def _work(self, entry):
        try:
            with self.condition:
                if self.stopped or not entry.users:
                    return
            self._refresh(entry)
            entry.failure = None
        except (MonitorError, OSError, sqlite3.Error):
            entry.failure = MonitorError("Workflow monitor storage or observation is unavailable.")
        finally:
            with self.condition:
                entry.busy = False
                self.condition.notify_all()

    def _schedule(self):
        while True:
            with self.condition:
                if self.stopped:
                    return
                now = self.clock()
                self._evict(now)
                entries = [entry for entry in self.entries.values() if entry.users and not entry.busy]
                for entry in entries:
                    try:
                        row = self._row(entry.key)
                    except (OSError, sqlite3.Error):
                        entry.failure = MonitorError("Workflow monitor storage is unavailable.")
                        continue
                    payload = json.loads(row["payload"]) if row and row["payload"] else {}
                    if (row and row["next_poll"] <= now and row["lease_until"] <= now
                            and (payload.get("status") != "completed" or row["error"])):
                        entry.busy = True
                        self.executor.submit(self._work, entry)
                self.condition.wait(0.5)

    def close(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2)
        self.executor.shutdown(wait=True, cancel_futures=True)


class Subscription:
    def __init__(self, monitor, entry, sequence, snapshot, follow):
        self.monitor, self.entry, self.sequence = monitor, entry, sequence
        self.snapshot, self.follow, self.closed = snapshot, follow, False
        with monitor._db() as db:
            self.boundary = db.execute("SELECT MAX(sequence) FROM workflow_events WHERE key=?", (entry.key,)).fetchone()[0]

    def next_event(self, timeout=15):
        deadline = time.monotonic() + max(0, min(timeout, 15))
        while not self.closed:
            if self.entry.failure:
                self.close()
                raise self.entry.failure
            if self.monitor.stopped:
                self.close()
                return None
            if self.snapshot is not None:
                event, self.snapshot = self.snapshot, None
                return event
            with self.monitor._db() as db:
                # Replay exhaustion and terminal health must describe one DB snapshot.
                db.execute("BEGIN")
                # A slow subscriber must not silently lose events to retention.
                if not db.execute("SELECT 1 FROM workflow_events WHERE key=? AND sequence=?",
                                  (self.entry.key, self.sequence)).fetchone():
                    self.close()
                    raise MonitorError("Workflow event history expired; reconnect without a cursor.", 409)
                row = db.execute("""SELECT sequence,payload FROM workflow_events
                                  WHERE key=? AND sequence>? AND (? OR sequence<=?)
                                  ORDER BY sequence LIMIT 1""",
                                 (self.entry.key, self.sequence, int(self.follow), self.boundary)).fetchone()
                if row:
                    self.sequence = row["sequence"]
                    return json.loads(row["payload"])
                latest = db.execute("SELECT payload,error FROM workflow_runs WHERE key=?", (self.entry.key,)).fetchone()
            payload = json.loads(latest["payload"]) if latest and latest["payload"] else {}
            if not self.follow or (payload.get("status") == "completed" and not latest["error"]):
                self.close()
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with self.monitor.condition:
                self.monitor.condition.wait(min(remaining, 0.5))
        return None

    def close(self):
        with self.monitor.condition:
            if not self.closed:
                self.closed = True
                self.monitor._release(self.entry)
