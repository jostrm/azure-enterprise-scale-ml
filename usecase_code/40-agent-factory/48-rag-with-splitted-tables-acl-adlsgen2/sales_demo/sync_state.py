"""Durable change queue, opaque delta checkpoint and fail-closed publication gate."""
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from .identity import SalesUnavailable


class SyncConflict(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(config):
    return hashlib.sha256(_json(config).encode()).hexdigest()


class SyncState:
    def __init__(self, database: Path):
        self.path = Path(database).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scopes (
                    scope_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, drive_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT NOT NULL DEFAULT 'initial-sync-required',
                    cursor TEXT, inventory TEXT NOT NULL DEFAULT '{}', candidate TEXT,
                    publication_hash TEXT, reconciled_at REAL, changed_at REAL NOT NULL,
                    lifecycle_hold INTEGER NOT NULL DEFAULT 0,
                    repair_required INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
                    tenant_id TEXT NOT NULL, resource TEXT NOT NULL,
                    client_state_sha256 TEXT NOT NULL, expires_at REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS subscription_attempts (
                    scope_id TEXT PRIMARY KEY REFERENCES scopes(scope_id),
                    operation TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL
                );
            """)
            for table, column in (("scopes", "lifecycle_hold"), ("scopes", "repair_required"),
                                  ("subscriptions", "active")):
                if column not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
                    default = 1 if column == "active" else 0
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}")

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=1.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self, scope_id, tenant_id, drive_id):
        if any(not isinstance(value, str) or not value for value in (scope_id, tenant_id, drive_id)):
            raise ValueError("Explicit scope, tenant and drive identities are required.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM scopes WHERE scope_id=?", (scope_id,)).fetchone()
            if row:
                if row["tenant_id"] != tenant_id or row["drive_id"] != drive_id:
                    raise ValueError("Existing sync state belongs to another tenant or drive.")
                return
            db.execute(
                "INSERT INTO scopes(scope_id,tenant_id,drive_id,changed_at) VALUES (?,?,?,?)",
                (scope_id, tenant_id, drive_id, time.time()),
            )

    def scope(self, scope_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM scopes WHERE scope_id=?", (scope_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown synchronization scope.")
        result = dict(row)
        result["inventory"] = json.loads(result["inventory"])
        result["candidate"] = json.loads(result["candidate"]) if result["candidate"] else None
        return result

    def status(self, scope_id):
        current = self.scope(scope_id)
        return {key: current[key] for key in (
            "scope_id", "state", "epoch", "reason", "changed_at", "reconciled_at",
            "lifecycle_hold", "repair_required",
        )}

    @contextmanager
    def apply_lock(self, scope_id):
        """Serialize external writes without blocking short webhook SQLite transactions."""
        self.scope(scope_id)
        suffix = hashlib.sha256(scope_id.encode()).hexdigest()[:24]
        path = self.path.with_name(self.path.name + ".apply-" + suffix + ".lock")
        stream = path.open("a+b")
        locked = False
        try:
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                raise SyncConflict("Another publication worker owns this scope; retry after it exits.") from None
            yield
        finally:
            if locked:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def mark_repair_required(self, scope_id, epoch):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE scopes SET repair_required=1,state='pending' WHERE scope_id=? AND epoch=?",
                (scope_id, epoch),
            ).rowcount
            if changed != 1:
                raise SyncConflict("New changes invalidated this worker before its first side effect.")

    def signal_many(self, signals):
        selected = {}
        for scope_id, reason in signals:
            if not isinstance(reason, str) or not reason or len(reason) > 128:
                raise ValueError("A bounded synchronization reason is required.")
            selected[scope_id] = reason
        if not selected:
            raise ValueError("At least one configured scope must be signaled.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._signal(db, selected)

    @staticmethod
    def _signal(db, selected):
        for scope_id in selected:
            if db.execute("SELECT 1 FROM scopes WHERE scope_id=?", (scope_id,)).fetchone() is None:
                raise ValueError("Unknown synchronization scope.")
        for scope_id, reason in selected.items():
            hold = reason.startswith(("graph-reauthorization", "graph-unsupported-lifecycle",
                                      "graph-subscription-expired", "subscription-recreation"))
            db.execute(
                "UPDATE scopes SET epoch=epoch+1,state='pending',candidate=NULL,reason=?,changed_at=?,"
                "lifecycle_hold=MAX(lifecycle_hold,?) WHERE scope_id=?",
                (reason, time.time(), int(hold), scope_id),
            )

    def signal_notifications(self, notifications):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            selected = {}
            for notification in notifications:
                row = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?",
                                 (notification["subscription_id"],)).fetchone()
                if row is None or not row["active"]:
                    continue
                if (row["scope_id"] != notification["scope_id"]
                        or not hmac.compare_digest(row["client_state_sha256"], notification["client_state_sha256"])):
                    raise ValueError("Subscription changed during notification validation.")
                rank, reason = notification["priority"], notification["reason"]
                if row["expires_at"] != notification["expires_at"] and rank > 1:
                    rank, reason = 1, "graph-notification"
                if row["scope_id"] not in selected or selected[row["scope_id"]][0] < rank:
                    selected[row["scope_id"]] = (rank, reason)
            self._signal(db, {scope: value[1] for scope, value in selected.items()})

    def begin(self, scope_id):
        self.signal_many([(scope_id, "reconciling")])
        return self.scope(scope_id)

    def stage(self, scope_id, epoch, candidate):
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("delta_link"), str)
                or not candidate["delta_link"] or not isinstance(candidate.get("inventory"), dict)
                or not isinstance(candidate.get("plan"), dict)):
            raise ValueError("A complete delta round and durable work plan are required.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE scopes SET candidate=?,state='pending',reason='publication-required' WHERE scope_id=? AND epoch=?",
                (_json(candidate), scope_id, epoch),
            ).rowcount
            if changed != 1:
                raise SyncConflict("Another notification or worker invalidated this reconciliation.")

    def candidate(self, scope_id, epoch):
        current = self.scope(scope_id)
        if current["epoch"] != epoch or current["candidate"] is None:
            raise SyncConflict("The candidate was invalidated or was not staged.")
        return current["candidate"]

    def complete(self, scope_id, epoch, config, proof):
        fingerprint = _fingerprint(config)
        if (proof.get("state") != "verified" or proof.get("config_sha256") != fingerprint
                or any(proof.get(key) != config[key] for key in ("owner", "dataset", "version"))
                or proof.get("structured_coverage_verified") is not True
                or any(proof.get("claims", {}).get(key) is not True for key in (
                    "real_text_split", "exact_three_chunks_per_table", "all_source_bytes_preserved"))
                or set(proof.get("service_evidence", {})) != {"json", "excel"}
                or any(item.get("verified") is not True or item.get("ingestion_succeeded") is not True
                       or item.get("chunk_count") != 3 for item in proof["service_evidence"].values())):
            raise ValueError("Only complete native service and structured-source evidence can open the gate.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM scopes WHERE scope_id=?", (scope_id,)).fetchone()
            if row is None or row["epoch"] != epoch or row["candidate"] is None:
                raise SyncConflict("New changes arrived before publication; serving remains blocked.")
            if row["lifecycle_hold"]:
                raise SyncConflict("Repair the subscription lifecycle before reopening publication.")
            if row["tenant_id"] != config["tenant_id"]:
                raise ValueError("Publication tenant differs from the synchronization scope.")
            candidate = json.loads(row["candidate"])
            db.execute(
                "UPDATE scopes SET cursor=?,inventory=?,candidate=NULL,state='ready',reason='verified',"
                "publication_hash=?,reconciled_at=?,repair_required=0 WHERE scope_id=? AND epoch=?",
                (candidate["delta_link"], _json(candidate["inventory"]), fingerprint, time.time(), scope_id, epoch),
            )

    def register_subscription(self, subscription_id, scope_id, tenant_id, resource, client_state, expires_at):
        if not isinstance(client_state, str) or not client_state or len(client_state) > 128:
            raise ValueError("A bounded client-state secret is required.")
        if type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at <= time.time():
            raise ValueError("Subscription expiration must be in the future.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            scope = db.execute("SELECT * FROM scopes WHERE scope_id=?", (scope_id,)).fetchone()
            if scope is None or scope["tenant_id"] != tenant_id or resource != f"/drives/{scope['drive_id']}/root":
                raise ValueError("Subscription differs from the configured tenant/drive root.")
            existing = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (subscription_id,)).fetchone()
            if existing and (existing["scope_id"] != scope_id or existing["tenant_id"] != tenant_id
                             or existing["resource"] != resource):
                raise ValueError("An existing subscription cannot change scope.")
            db.execute(
                "INSERT INTO subscriptions(subscription_id,scope_id,tenant_id,resource,client_state_sha256,expires_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(subscription_id) DO UPDATE SET "
                "client_state_sha256=excluded.client_state_sha256,expires_at=excluded.expires_at,active=1",
                (subscription_id, scope_id, tenant_id, resource,
                 hashlib.sha256(client_state.encode()).hexdigest(), expires_at),
            )
            db.execute("UPDATE subscriptions SET active=0 WHERE scope_id=? AND subscription_id!=?",
                       (scope_id, subscription_id))
            db.execute("UPDATE scopes SET lifecycle_hold=0 WHERE scope_id=?", (scope_id,))
            db.execute("DELETE FROM subscription_attempts WHERE scope_id=?", (scope_id,))

    def subscription(self, subscription_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (subscription_id,)).fetchone()
        return dict(row) if row else None

    def update_subscription_expiry(self, subscription_id, expires_at):
        if type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at <= time.time():
            raise ValueError("Renewed expiration must be in the future.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE subscriptions SET expires_at=? WHERE subscription_id=? AND active=1", (expires_at, subscription_id),
            ).rowcount
            if changed != 1:
                raise ValueError("Unknown subscription; a missing subscription must be recreated explicitly.")
            db.execute(
                "DELETE FROM subscription_attempts WHERE operation='renew' AND "
                "scope_id=(SELECT scope_id FROM subscriptions WHERE subscription_id=?)",
                (subscription_id,),
            )
            db.execute(
                "UPDATE scopes SET lifecycle_hold=0 WHERE "
                "scope_id=(SELECT scope_id FROM subscriptions WHERE subscription_id=?)",
                (subscription_id,),
            )

    def mark_subscription_attempt(self, scope_id, operation):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM subscription_attempts WHERE scope_id=?", (scope_id,)).fetchone()
            if prior and prior["state"] == "attempted":
                raise SyncConflict("An uncertain subscription operation requires operator reconciliation.")
            db.execute(
                "INSERT OR REPLACE INTO subscription_attempts VALUES (?,?,?,?)",
                (scope_id, operation, "attempted", time.time()),
            )


def guard_snapshot(config, *, now=None):
    guard = config.get("graph_sync")
    if guard is None:
        return None
    try:
        if not isinstance(guard, dict) or set(guard) != {"database", "scope_id", "max_age_seconds"}:
            raise SalesUnavailable()
        database = Path(guard["database"])
        maximum = guard["max_age_seconds"]
        if (not database.is_absolute() or not database.is_file() or type(maximum) is not int
                or not 30 <= maximum <= 86400):
            raise SalesUnavailable()
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1.0)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM scopes WHERE scope_id=?", (guard["scope_id"],)).fetchone()
            expires = db.execute(
                "SELECT MIN(expires_at) FROM subscriptions WHERE scope_id=? AND active=1", (guard["scope_id"],),
            ).fetchone()[0]
        current_time = time.time() if now is None else now
        if (row is None or row["state"] != "ready" or row["lifecycle_hold"]
                or row["tenant_id"] != config["tenant_id"]
                or row["publication_hash"] != _fingerprint(config) or row["reconciled_at"] is None
                or not 0 <= current_time - row["reconciled_at"] <= maximum
                or (expires is not None and current_time >= expires)):
            raise SalesUnavailable()
        return (guard["scope_id"], row["epoch"], row["publication_hash"])
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        raise SalesUnavailable() from None


def assert_guard_unchanged(config, snapshot):
    if guard_snapshot(config) != snapshot:
        raise SalesUnavailable()
