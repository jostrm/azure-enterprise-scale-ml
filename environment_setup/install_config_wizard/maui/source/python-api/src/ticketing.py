"""Private Azure-user tickets, connection references, and immutable sync consent."""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src import azure_auth
from src.factory_scope import current_factory_scope
from src.operations import AzureInventoryProvider, LocalFactoryDiscovery, OperationsStore, parse_resource_group_name
from src.ticket_connectors import TicketConnector, TicketError, SyncError, sync_plan, validate_origin


STATUSES = ("New", "Active", "Solved")
TYPES = ("Request Azure service", "Bug report", "Blocker")
SEVERITIES = ("minor", "major", "blocker")
IDENTITY_FIELDS = (
    "resource_group", "environment", "project_number", "region", "ai_factory_prefix", "ai_factory_suffix",
)
PUBLIC_TICKET_FIELDS = (
    "id", "title", "description", "type", "status", "owner", "project_number",
    "aifactory_folder", "requested_service", "created_at", "updated_at", "external_url", "sync_state",
    "severity", "resource_group", "environment", "region", "ai_factory_prefix", "ai_factory_suffix",
    "cost_center", "department_name",
)
PUBLIC_CONNECTION_FIELDS = (
    "id", "name", "provider", "base_url", "project_key", "username", "credential_env",
    "owner", "created_at", "updated_at",
)


def now_iso(clock=time.time):
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def factory_folder(value):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TicketError("An existing absolute AI Factory folder is required.")
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise TicketError("An existing absolute AI Factory folder is required.")
    return OperationsStore._folder(path)


def metadata_text(value, field, limit=200):
    if value is None:
        return ""
    if (
        not isinstance(value, str) or len(value) > limit
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    ):
        raise TicketError(f"{field} must be text of at most {limit} characters without controls.")
    return value.strip()


def parse_ticket_resource_group(value):
    """Extract naming metadata only; no configuration, Azure identity or ARM lookup."""
    name = metadata_text(value, "resource_group", 90).casefold()
    invalid = "Use a complete project resource-group name with factory prefix, region, environment and factory suffix."
    if not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", name):
        raise TicketError(invalid)
    parsed = parse_resource_group_name(name)
    matches = list(LocalFactoryDiscovery._PROJECT_RE.finditer(name))
    if len(matches) != 1 or not parsed["project_number"] or len(parsed["project_number"]) > 6:
        raise TicketError(invalid)
    project = matches[0]
    prefix = name[:project.start()]
    # "esml-project" is the optional workload marker, not part of "gh-" / "mrvel-1-".
    if prefix.endswith("-esml-"):
        prefix = prefix[:-5]
    tail = name[project.end():].removesuffix("-rg").split("-")
    if (
        not prefix or not prefix.endswith("-") or not prefix[:-1]
        or len(tail) != 4 or tail[0] != "" or not re.fullmatch(r"[a-z][a-z0-9]*", tail[1])
        or tail[2] not in {"dev", "test", "stage", "prod"} or not re.fullmatch(r"[0-9]+", tail[3])
        or parsed["environment"] != ("stage" if tail[2] == "test" else tail[2])
    ):
        raise TicketError(invalid)
    return {
        "resource_group": name, "environment": parsed["environment"],
        "project_number": parsed["project_number"], "region": tail[1],
        "ai_factory_prefix": prefix, "ai_factory_suffix": "-" + tail[3],
    }


def ticket_in_factory_scope(ticket, folder, scope):
    if not ticket["resource_group"]:
        return ticket["aifactory_folder"] == folder
    targets = [
        target for target in scope["monitoring_targets"]
        if target["prefix"].strip("-_").casefold() == ticket["ai_factory_prefix"].strip("-_")
        and target["suffix"].strip("-_").casefold() == ticket["ai_factory_suffix"].strip("-_")
        and target["location_suffix"].casefold() == ticket["region"]
        and target["environment"] == ticket["environment"]
    ]
    return bool(targets) and AzureInventoryProvider._is_relevant_group(
        ticket["resource_group"], {"monitoring_targets": targets}
    )


class AzureTicketIdentity:
    """Authenticate directly via CLI token acquisition, never cached status/user input."""

    def __init__(self, auth=None, clock=time.time):
        self.auth = auth or azure_auth.azure_auth_service
        self.clock = clock

    def __call__(self, folder=None):
        try:
            context = azure_auth._context(folder)
            accounts = self.auth._accounts()
            defaults = [item for item in accounts if item["is_default"]]
            if len(defaults) != 1:
                raise TicketError("Select a default Azure CLI account and sign in before opening private tickets.", 401)
            account = defaults[0]
            tenant = account["tenant_id"]
            if context.subscription_ids and account["id"] not in context.subscription_ids:
                raise TicketError("The default Azure CLI subscription is outside this factory. Select a factory subscription.", 403)
            if context.tenant_ids and tenant not in context.tenant_ids:
                raise TicketError("The default Azure CLI tenant is outside this factory. Select the factory account.", 403)
            if folder:
                expected = current_factory_scope(folder)["subscription_tenants"].get(account["id"])
                if expected and expected.casefold() != tenant:
                    raise TicketError("The factory subscription's configured tenant does not match Azure CLI.", 403)
            if not account["id"]:
                raise TicketError("A default Azure subscription is required for private tickets.", 401)
            raw = self.auth._run([
                "account", "get-access-token", "--subscription", account["id"],
                "--resource", "https://management.azure.com/",
                "--query", "{accessToken:accessToken,tenant:tenant}", "--output", "json",
            ])
            if not isinstance(raw, dict) or azure_auth._guid(raw.get("tenant")) != tenant:
                raise ValueError
            token = raw.get("accessToken")
            if not isinstance(token, str) or len(token) > 32768 or len(token.split(".")) != 3:
                raise ValueError
            encoded = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            oid = azure_auth._guid(claims.get("oid"))
            expiry, not_before = float(claims.get("exp", 0)), float(claims.get("nbf", 0))
            if (
                not oid or azure_auth._guid(claims.get("tid")) != tenant
                or not math.isfinite(expiry) or not math.isfinite(not_before)
                or expiry <= self.clock() or not_before > self.clock() + 60
                or claims.get("aud") not in {
                    "https://management.azure.com", "https://management.azure.com/",
                    "https://management.core.windows.net/", "797f4846-ba00-4fd7-ba43-dac1f8f63013",
                }
            ):
                raise ValueError
            # Tokens originate from the local authenticated CLI, not an HTTP request.
            # Only the stable tenant/object tuple leaves this method.
            return f"azure:{tenant}:{oid}"
        except azure_auth.AuthRequestError as exc:
            raise TicketError(str(exc), exc.status_code) from None
        except (
            azure_auth._CliUnavailable, azure_auth._CliError, azure_auth._LoginRequired,
            ValueError, TypeError, AttributeError, binascii.Error, OverflowError,
        ) as exc:
            if isinstance(exc, TicketError):
                raise
            raise TicketError("Could not verify the current Azure user. Sign in to Azure CLI and retry.", 401) from None


class TicketService:
    def __init__(self, store=None, identity=None, connector=None, clock=time.time):
        self.store = store or OperationsStore()
        self.identity = identity or AzureTicketIdentity()
        self.connector = connector or TicketConnector()
        self.clock = clock
        self._migrate()

    def _migrate(self):
        with self.store._connect() as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS ticketing_schema (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS private_tickets (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, aifactory_folder TEXT NOT NULL,
                    project_number TEXT NOT NULL DEFAULT '', type TEXT NOT NULL,
                    title TEXT NOT NULL, description TEXT NOT NULL, requested_service TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('New','Active','Solved')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    external_id TEXT NOT NULL DEFAULT '', external_url TEXT NOT NULL DEFAULT '',
                    connection_id TEXT NOT NULL DEFAULT '', sync_state TEXT NOT NULL DEFAULT 'local',
                    CHECK(type IN ('Request Azure service','Bug report','Blocker'))
                );
                CREATE INDEX IF NOT EXISTS idx_private_tickets_owner_folder
                    ON private_tickets(owner,aifactory_folder,created_at);
                CREATE TABLE IF NOT EXISTS private_ticket_connections (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    provider TEXT NOT NULL CHECK(provider IN ('Jira','ServiceNow')),
                    base_url TEXT NOT NULL, project_key TEXT NOT NULL, username TEXT NOT NULL,
                    credential_env TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_private_connections_owner ON private_ticket_connections(owner);
                CREATE TABLE IF NOT EXISTS private_ticket_confirmations (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, ticket_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL, ticket_version INTEGER NOT NULL,
                    connection_version INTEGER NOT NULL, plan_json TEXT NOT NULL,
                    expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    FOREIGN KEY(ticket_id) REFERENCES private_tickets(id),
                    FOREIGN KEY(connection_id) REFERENCES private_ticket_connections(id)
                );
                CREATE INDEX IF NOT EXISTS idx_private_confirmations_owner
                    ON private_ticket_confirmations(owner,expires_at);
            """)
            db.execute("INSERT OR IGNORE INTO ticketing_schema VALUES (1,?)", (now_iso(self.clock),))
            columns = {row["name"] for row in db.execute("PRAGMA table_info(private_tickets)")}
            if "severity" not in columns:
                db.execute(
                    "ALTER TABLE private_tickets ADD COLUMN severity TEXT NOT NULL DEFAULT 'minor' "
                    "CHECK(severity IN ('minor','major','blocker'))"
                )
                db.execute("UPDATE private_tickets SET severity='blocker' WHERE type='Blocker'")
            for field in (*IDENTITY_FIELDS, "cost_center", "department_name"):
                if field not in columns:
                    db.execute(f"ALTER TABLE private_tickets ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
            db.execute("INSERT OR IGNORE INTO ticketing_schema VALUES (2,?)", (now_iso(self.clock),))

    @staticmethod
    def _public(row, fields=PUBLIC_TICKET_FIELDS):
        return {key: row[key] for key in fields}

    def _ticket(self, db, ticket_id, owner):
        row = db.execute("SELECT * FROM private_tickets WHERE id=? AND owner=?", (ticket_id, owner)).fetchone()
        if row is None:
            raise TicketError("Ticket not found for the current Azure user.", 404)
        return dict(row)

    def _connection(self, db, connection_id, owner):
        row = db.execute(
            "SELECT * FROM private_ticket_connections WHERE id=? AND owner=?", (connection_id, owner)
        ).fetchone()
        if row is None:
            raise TicketError("Connection not found for the current Azure user.", 404)
        return dict(row)

    def list_tickets(self, folder=None):
        folder = factory_folder(folder) if folder is not None else None
        owner = self.identity(folder)
        with self.store._connect() as db:
            rows = db.execute(
                "SELECT * FROM private_tickets WHERE owner=? ORDER BY created_at DESC,id", (owner,)
            ).fetchall()
        if folder:
            scope = current_factory_scope(folder)
            rows = [row for row in rows if ticket_in_factory_scope(row, folder, scope)]
        # Local lists are deliberately untruncated; the native client can display every record.
        tickets = [self._public(row) for row in rows]
        return {
            "owner": owner, "tickets": tickets,
            "counts": {status.lower(): sum(row["status"] == status for row in rows) for status in STATUSES},
        }

    def create(self, values):
        if any(field in values for field in IDENTITY_FIELDS[1:] if field != "project_number"):
            raise TicketError("Resource-group identity fields are derived by the server, not accepted as input.")
        identity = dict.fromkeys(IDENTITY_FIELDS, "")
        if values.get("resource_group") is not None:
            if values.get("project_number") is not None:
                raise TicketError("project_number must be omitted when resource_group is supplied; it is derived by the server.")
            identity = parse_ticket_resource_group(values["resource_group"])
            # Never bind user-supplied naming metadata to an arbitrary wizard folder.
            folder = ""
        else:
            folder = factory_folder(values.get("aifactory_folder"))
            project = values.get("project_number") or ""
            if not isinstance(project, str) or (project and not re.fullmatch(r"\d{1,6}", project)):
                raise TicketError("project_number must contain 1–6 digits.")
            identity["project_number"] = project
        owner = self.identity(folder or None)
        timestamp = now_iso(self.clock)
        if values["type"] not in TYPES:
            raise TicketError("Unsupported ticket type.")
        severity = values.get("severity")
        if severity is None:
            severity = "blocker" if values["type"] == "Blocker" else "minor"
        if severity not in SEVERITIES:
            raise TicketError("Unsupported ticket severity.")
        cost_center = metadata_text(values.get("cost_center"), "cost_center")
        department = metadata_text(values.get("department_name"), "department_name")
        if values["type"] == "Request Azure service" and not str(values.get("requested_service") or "").strip():
            raise TicketError("requested_service is required for an Azure service request.")
        ticket_id = str(uuid4())
        with self.store._connect() as db:
            db.execute("""
                INSERT INTO private_tickets
                (id,owner,aifactory_folder,project_number,type,title,description,requested_service,status,created_at,updated_at,
                 severity,resource_group,environment,region,ai_factory_prefix,ai_factory_suffix,cost_center,department_name)
                VALUES (?,?,?,?,?,?,?,?,'New',?,?,?,?,?,?,?,?,?,?)
            """, (ticket_id, owner, folder, identity["project_number"], values["type"], values["title"].strip(),
                  values["description"], values.get("requested_service") or "", timestamp, timestamp,
                  severity, identity["resource_group"], identity["environment"], identity["region"],
                  identity["ai_factory_prefix"], identity["ai_factory_suffix"], cost_center, department))
            return self._public(self._ticket(db, ticket_id, owner))

    def update(self, ticket_id, status, severity=None):
        owner = self.identity()
        if status not in STATUSES:
            raise TicketError("Unsupported ticket status.")
        if severity is not None and severity not in SEVERITIES:
            raise TicketError("Unsupported ticket severity.")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ticket = self._ticket(db, ticket_id, owner)
            if ticket["sync_state"] == "syncing":
                raise TicketError("Synchronization is in progress; the ticket cannot be changed.", 409)
            db.execute("""
                UPDATE private_tickets SET status=?,severity=?,updated_at=?,version=version+1,
                sync_state=CASE WHEN sync_state='synced' THEN 'pending' ELSE sync_state END
                WHERE id=? AND owner=?
            """, (status, severity if severity is not None else ticket["severity"], now_iso(self.clock), ticket_id, owner))
            return self._public(self._ticket(db, ticket_id, owner))

    def list_connections(self):
        owner = self.identity()
        with self.store._connect() as db:
            rows = db.execute(
                "SELECT * FROM private_ticket_connections WHERE owner=? ORDER BY name,id", (owner,)
            ).fetchall()
        return {"connections": [self._public(row, PUBLIC_CONNECTION_FIELDS) for row in rows]}

    def save_connection(self, values):
        owner = self.identity()
        origin = validate_origin(values["provider"], values["base_url"])
        reference = values["credential_env"]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", reference):
            raise TicketError("credential_env must be an environment-variable name, not a credential.")
        username = values.get("username") or ""
        project = values.get("project_key") or ""
        if ":" in username or any(ord(char) < 32 for char in username):
            raise TicketError("username contains unsupported characters.")
        if values["provider"] == "Jira" and (
            not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", project) or not username
        ):
            raise TicketError("Jira requires an uppercase project_key and username (account email).")
        connection_id = values.get("id") or str(uuid4())
        timestamp = now_iso(self.clock)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if values.get("id"):
                old = self._connection(db, connection_id, owner)
                active = db.execute(
                    "SELECT 1 FROM private_tickets WHERE connection_id=? AND owner=? AND "
                    "(external_id<>'' OR sync_state IN ('syncing','uncertain')) LIMIT 1",
                    (connection_id, owner),
                ).fetchone()
                if active and any(old[key] != new for key, new in (
                    ("provider", values["provider"]), ("base_url", origin), ("project_key", project),
                )):
                    raise TicketError("A bound connection's provider/target/project cannot change. Create a new connection.", 409)
                if db.execute(
                    "SELECT 1 FROM private_tickets WHERE connection_id=? AND owner=? AND sync_state='syncing'",
                    (connection_id, owner),
                ).fetchone():
                    raise TicketError("This connection is currently synchronizing.", 409)
                db.execute("""
                    UPDATE private_ticket_connections SET name=?,provider=?,base_url=?,project_key=?,
                    username=?,credential_env=?,updated_at=?,version=version+1 WHERE id=? AND owner=?
                """, (values["name"].strip(), values["provider"], origin, project, username,
                      reference, timestamp, connection_id, owner))
            else:
                db.execute("""
                    INSERT INTO private_ticket_connections
                    (id,owner,name,provider,base_url,project_key,username,credential_env,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (connection_id, owner, values["name"].strip(), values["provider"], origin,
                      project, username, reference, timestamp, timestamp))
            return self._public(self._connection(db, connection_id, owner), PUBLIC_CONNECTION_FIELDS)

    @staticmethod
    def _can_sync(ticket, connection):
        if ticket["sync_state"] in {"syncing", "uncertain"}:
            raise TicketError(
                "The previous sync is in progress or its result is uncertain. Verify remotely; "
                "automatic re-creation is blocked to prevent duplicate tickets.", 409,
            )
        if ticket["external_id"] and ticket["connection_id"] != connection["id"]:
            raise TicketError("This ticket is already bound to a different connection.", 409)

    def preview(self, ticket_id, connection_id):
        owner = self.identity()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ticket = self._ticket(db, ticket_id, owner)
            connection = self._connection(db, connection_id, owner)
            self._can_sync(ticket, connection)
            validate_origin(connection["provider"], connection["base_url"])
            plan = sync_plan(ticket, connection)
            confirmation_id = str(uuid4())
            db.execute("DELETE FROM private_ticket_confirmations WHERE expires_at<? AND state<>'sending'", (self.clock() - 86400,))
            db.execute("""
                INSERT INTO private_ticket_confirmations
                (id,owner,ticket_id,connection_id,ticket_version,connection_version,plan_json,expires_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (confirmation_id, owner, ticket_id, connection_id, ticket["version"], connection["version"],
                  json.dumps(plan, ensure_ascii=False, sort_keys=True), self.clock() + 300))
        credential_note = "configured" if os.environ.get(connection["credential_env"]) else "NOT SET; synchronization will fail"
        status_note = (
            f"Allowed Jira destination status names: {', '.join(plan['status_mapping'])}\n"
            if "status_mapping" in plan else ""
        )
        return {
            "confirmation_id": confirmation_id,
            "recipient": f"{connection['provider']}: {connection['base_url']}{plan['path']}",
            "content": (
                f"{plan['method']} {connection['base_url']}{plan['path']}\n"
                f"Connection: {connection['name']}\nCredential environment reference: {connection['credential_env']} "
                f"({credential_note}; secret never displayed)\n"
                f"Authentication account: {connection['username'] or 'Bearer credential'}\n"
                f"{plan['field_mapping']}\nStatus requested: {ticket['status']}\n"
                f"{status_note}"
                f"Outbound JSON:\n{json.dumps(plan['payload'], ensure_ascii=False, indent=2)}\n"
                "Confirmation expires in 5 minutes. No outbound request has been sent."
            ),
        }

    def sync(self, confirmation_id):
        owner = self.identity()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM private_ticket_confirmations WHERE id=? AND owner=?", (confirmation_id, owner)
            ).fetchone()
            if row is None:
                raise TicketError("Confirmation not found for the current Azure user.", 404)
            ticket = self._ticket(db, row["ticket_id"], owner)
            if row["state"] == "done":
                return self._public(ticket)
            if row["state"] != "pending" or row["expires_at"] <= self.clock():
                raise TicketError("Confirmation expired or was already attempted. Preview again if the prior outcome is known.", 409)
            connection = self._connection(db, row["connection_id"], owner)
            self._can_sync(ticket, connection)
            if ticket["version"] != row["ticket_version"] or connection["version"] != row["connection_version"]:
                raise TicketError("Ticket or connection changed after preview. Preview again.", 409)
            validate_origin(connection["provider"], connection["base_url"])
            credential = os.environ.get(connection["credential_env"], "")
            if not credential or len(credential) > 16384 or "\r" in credential or "\n" in credential:
                raise TicketError("The API-host credential environment variable is unset or invalid; no request was sent.", 409)
            plan = json.loads(row["plan_json"])
            if plan != sync_plan(ticket, connection):
                raise TicketError("The outbound payload changed after preview. Preview again.", 409)
            db.execute("UPDATE private_ticket_confirmations SET state='sending' WHERE id=? AND owner=?", (confirmation_id, owner))
            db.execute(
                "UPDATE private_tickets SET sync_state='syncing',connection_id=? WHERE id=? AND owner=?",
                (connection["id"], ticket["id"], owner),
            )

        def on_created(external_id, external_url):
            # Persist before a second network call, so a workflow failure cannot duplicate creation.
            with self.store._connect() as db:
                db.execute(
                    "UPDATE private_tickets SET external_id=?,external_url=? WHERE id=? AND owner=?",
                    (external_id, external_url, ticket["id"], owner),
                )

        try:
            self.connector.send(connection, ticket, plan, credential, on_created)
        except SyncError as exc:
            with self.store._connect() as db:
                db.execute(
                    "UPDATE private_tickets SET sync_state=?,updated_at=?,version=version+1 WHERE id=? AND owner=?",
                    ("uncertain" if exc.uncertain else "failed", now_iso(self.clock), ticket["id"], owner),
                )
                db.execute("UPDATE private_ticket_confirmations SET state='failed' WHERE id=? AND owner=?", (confirmation_id, owner))
            raise
        with self.store._connect() as db:
            db.execute(
                "UPDATE private_tickets SET sync_state='synced',updated_at=?,version=version+1 WHERE id=? AND owner=?",
                (now_iso(self.clock), ticket["id"], owner),
            )
            db.execute("UPDATE private_ticket_confirmations SET state='done' WHERE id=? AND owner=?", (confirmation_id, owner))
            return self._public(self._ticket(db, ticket["id"], owner))
