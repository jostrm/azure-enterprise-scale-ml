"""Persistent project deployment/update drafts, reviewed execution and local terminals."""

from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import shlex
import sqlite3
import subprocess
import threading
import time
import sys
import yaml
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from src import operations, project_verification, simple_mode, wizard, release_version
from src.deployment_terminal import OwnedPty, TerminalSessions
from src.factory_scope import current_factory_scope
from src.ticket_connectors import TicketError
from src.ticketing import AzureTicketIdentity
from src.deployment_config import protect
from src.scaling_policy import network_validation_issues


SCRIPTS = {"ado": "ADO-update-aifactory-and-run-project.sh", "gha": "GHA-update-aifactory-and-run-project.sh"}
GITHUB_LEGACY_SCRIPT = "GH-update-aifactory-and-run-project.sh"
GITHUB_ALIAS = "# AIFACTORY_PROJECT_DEPLOYMENT_ALIAS=" + GITHUB_LEGACY_SCRIPT
CONTRACT = "# AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1"
API_DEPLOYMENT_CONTRACT_VERSION = 2
ACTIVE = ("queued", "running")
KNOWN_EXECUTION_ERRORS = (TicketError, OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError)
_LOCK = threading.RLock()
_INITIALIZED = set()
EFFECTS = [
    "Run the exact root update-and-run script in Git Bash with an interactive terminal.",
    "The script can stash tracked/untracked work, switch branches, pull Git changes, refresh the shared submodule and copy bootstrap/templates.",
    "Refresh preserves the reviewed project configuration; its commit prompt can stage, commit and push allowlisted deployment code and the submodule pointer, not project exports.",
    "GitHub creates a unique run-specific environment secret and deletes it after verified completion; Azure DevOps receives the configuration as a protected per-run secret variable.",
    "Queue the selected project/environment pipeline, potentially creating or changing billable Azure resources and role assignments.",
    "Raw terminal output may contain secrets and is shown only in the authenticated local terminal, never stored by this API.",
]
WARNINGS = [
    "Review every script prompt. Terminal input is sent once and cannot be undone.",
    "Do not change shared host CLI identities or repository configuration while a job runs.",
    "The reviewed script watches the exact pipeline run. Exit zero still means submitted, not deployed; Azure inventory alone establishes Active.",
    "Failure, interruption or a submitted run may have changed local/cloud resources. Reconcile manually; there is no automatic retry.",
    "Template refresh uses only the exact published AI Factory commit reviewed here; consumer main is a separate branch.",
    "If dispatch or pipeline completion is uncertain, reconcile the run and its run-specific GitHub secret before retrying; no automatic retry occurs.",
]


def patch_disclosure(patch):
    if patch:
        return {
            "effects": [
                "Patch checked: no --project-only flag; AIFACTORY_PROJECT_ONLY=false. Refresh AI Factory/templates before running the exact selected project/environment.",
                *EFFECTS,
            ],
            "warnings": list(WARNINGS),
        }
    return {
        "effects": [
            "Patch unchecked: pass --project-only and AIFACTORY_PROJECT_ONLY=true. Skip checkout, stash, pull, submodule/template updates, commit and push; run the existing project pipeline.",
            EFFECTS[0], *EFFECTS[3:],
        ],
        "warnings": [warning for warning in WARNINGS if not warning.startswith("Template refresh")],
    }


def deployment_acknowledgement(draft):
    return {"version": API_DEPLOYMENT_CONTRACT_VERSION, "draft_id": draft["id"],
            "operation": draft["operation"], "patch": draft["patch"],
            "aifactory_version": draft.get("aifactory_version"),
            **{key: draft.get(key) or "" for key in ("requested_version", "branch", "resolved_ref")}}


def _folder(value):
    if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise TicketError("An absolute local aifactory folder is required.")
    path = Path(value)
    if not path.is_absolute() or value.startswith(("\\\\", "//")) or ".." in path.parts:
        raise TicketError("Select an absolute local aifactory folder without traversal.")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise TicketError("Deployment paths cannot traverse links or junctions.", 409)
    if path.name.casefold() != "aifactory" or not path.is_dir():
        raise TicketError("Select the existing aifactory folder, not its parent.", 404)
    return os.path.normcase(str(path.resolve()))


def bash_path(value):
    # Drive-qualified paths work with both /c and /cygdrive/c Git Bash mounts.
    return str(value).replace("\\", "/")


def _json(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise TicketError("Configuration exceeds the supported size.", 409)
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TicketError("Configuration must be a JSON object.", 409)
    return value


def _hashes(paths):
    result = {}
    for path in sorted(set(paths)):
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                raise TicketError("Reviewed deployment inputs cannot traverse links or junctions.", 409)
        if path.exists():
            if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise TicketError("A deployment input is not a bounded ordinary file.", 409)
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            result[str(path)] = None
    return result


def derived_document(folder, number):
    snapshots = wizard._list_project_snapshots(folder, create_legacy_dir=False)
    matches = [path for key, path in snapshots.items() if key.lstrip("0") == number.lstrip("0")]
    if len(matches) != 1:
        raise TicketError("Saved project selection is missing or ambiguous.", 409)
    try:
        _, saved = project_verification._saved_selection(folder, number, matches[0])
    except project_verification.VerificationRequestError as exc:
        raise TicketError(str(exc), exc.status_code) from None
    return wizard._render_variables_json(saved["effective"])


def ado_organization_tenant(root):
    path = root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"
    if not path.is_file():
        return ""
    if path.stat().st_size > 4 * 1024 * 1024:
        raise TicketError("ADO variables exceed the supported configuration size.", 409)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (yaml.YAMLError, UnicodeError):
        raise TicketError("ADO organization configuration is malformed.", 409) from None
    if not isinstance(document, dict):
        raise TicketError("ADO organization configuration must be an object.", 409)
    values = document.get("variables", {})
    if isinstance(values, dict):
        return str(values.get("azureDevOpsTenantId", "")).strip()
    if isinstance(values, list):
        matches = [str(item.get("value", "")).strip() for item in values
                   if isinstance(item, dict) and item.get("name") == "azureDevOpsTenantId"]
        if len(matches) > 1:
            raise TicketError("ADO organization tenant is ambiguous.", 409)
        return matches[0] if matches else ""
    return ""


def selection(folder, number, target):
    root = Path(folder)
    snapshots = wizard._list_project_snapshots(folder, create_legacy_dir=False)
    matches = [(key, path) for key, path in snapshots.items() if key.lstrip("0") == number.lstrip("0")]
    if len(matches) != 1:
        raise TicketError("Select one unambiguous saved project configuration.", 409)
    try:
        _, saved = project_verification._saved_selection(folder, number, matches[0][1])
    except project_verification.VerificationRequestError as exc:
        raise TicketError(str(exc), exc.status_code) from None
    state = saved["effective"]
    source, route = wizard._startup_import_candidate(folder, {})
    if not source:
        raise TicketError("The factory has no authoritative current configuration.", 409)
    source = Path(source)
    if source.name == "factory_state.json":
        route = _json(source).get("orchestrator")
    if route not in SCRIPTS:
        raise TicketError("The factory configuration must explicitly resolve to ADO or GitHub.", 409)
    scope = current_factory_scope(folder)
    subscription = scope["subscriptions"].get(target, "")
    tenant = scope["subscription_tenants"].get(subscription, "")
    if not re.fullmatch(simple_mode.GUID, subscription) or not re.fullmatch(simple_mode.GUID, tenant):
        raise TicketError("The selected target needs a valid subscription and tenant in current factory configuration.", 409)
    expected = wizard._render_variables_json(state)
    if target not in ("dev", "stage", "prod"):
        raise TicketError("An exact Dev, Stage or Prod target is required.", 409)
    target_state = expected.get("dev" if target == "dev" else "stage_prod", {})
    config_subscription = target_state.get({"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[target])
    config_tenant = target_state.get("tenantId")
    github_repository = ""
    if route == "gha" and (root.parent / ".env").is_file():
        github = {}
        wizard._import_env_to_state(str(root.parent / ".env"), github)
        github_repository = str(github.get("github_new_repo") or "").removeprefix("https://github.com/").removesuffix(".git")
    config = None
    for candidate in (Path(matches[0][1]).parent / "variables.json", root / "variables.json"):
        if not candidate.is_file():
            continue
        actual = _json(candidate)
        if all(
            isinstance(actual.get(section), dict)
            and all(actual[section].get(key) == value for key, value in expected.get(section, {}).items())
            for section in ("dev", "stage_prod")
        ):
            config = candidate
            break
    script = root.parent / SCRIPTS[route]
    paths = {source, script, Path(matches[0][1]), root / "variables.json",
             root / "config-wizard" / "factory_state.json", root.parent / ".env",
             root.parent / ".gitmodules", root.parent / release_version.STATE_PATH}
    paths.update(Path(item[0]) for item in saved["sources"])
    if config:
        paths.add(config)
    paths.update(root.parent.glob("*.sh"))
    paths.update(root.parent.glob("ui/*.sh"))
    paths.update(root.parent.glob("lib/*.py"))
    paths.update(root.parent.glob("lib/*.sh"))
    shared = root.parent / "azure-enterprise-scale-ml"
    paths.add(shared / "00-start.sh")
    for subtree in (shared / "bootstrap", root.parent / ".github" / "workflows",
                    root / "esml-infra" / "azure-devops" / "bicep" / "yaml"):
        if subtree.is_dir():
            paths.update(p for p in subtree.rglob("*") if p.suffix in (".sh", ".py", ".json", ".yaml", ".yml"))
    if len(paths) > 4096:
        raise TicketError("Too many deployment dependencies to review safely.", 409)
    hashes = _hashes(paths)
    blockers = []
    installed_version = None
    try:
        installed_version = release_version.saved_version(root.parent)
    except TicketError as exc:
        blockers.append(str(exc))
    if route == "ado":
        organization_tenant = ado_organization_tenant(root) or str(expected.get("dev", {}).get("azureDevOpsTenantId", "")).strip()
        if organization_tenant and (not re.fullmatch(simple_mode.GUID, organization_tenant)
                                    or organization_tenant.lower() != tenant.lower()):
            blockers.append("The reviewed ADO launcher currently requires the organization tenant to match the target Azure tenant; cross-tenant or invalid azureDevOpsTenantId needs a separately reviewed authentication flow.")
    if str(config_subscription).lower() != subscription.lower() or str(config_tenant).lower() != tenant.lower():
        blockers.append("Saved project target subscription/tenant differs from the current factory. Review and save the correct project context.")
    if not (root.parent / ".git").exists():
        blockers.append("The aifactory parent must be the selected consumer Git repository.")
    if config is None:
        if sys.platform != "win32":
            blockers.append("Export matching project JSON on this platform; protected derived configuration requires Windows current-user DPAPI.")
        blockers.extend(issue["message"] for issue in network_validation_issues(state))
    if any(str(target_state.get(key, "")).lower() in ("true", "yes", "1") for key in (
        "deleteAllForProject", "deleteAllServicesForProject",
    )):
        blockers.append("Project deployment or update cannot use deletion configuration.")
    text = script.read_text(encoding="utf-8-sig") if script.is_file() else ""
    if route == "gha" and GITHUB_ALIAS in text:
        implementation = root.parent / GITHUB_LEGACY_SCRIPT
        text = implementation.read_text(encoding="utf-8-sig") if implementation.is_file() else ""
        if not text:
            blockers.append(f"The GHA alias requires {GITHUB_LEGACY_SCRIPT} in the same consumer root.")
    if not text:
        blockers.append(f"Install the exact root script {SCRIPTS[route]} one level above aifactory.")
    elif CONTRACT not in text or any(name not in text for name in (
        "AIFACTORY_TARGET_ENVIRONMENT", "AIFACTORY_PROJECT_NUMBER", "AIFACTORY_PROJECT_CONFIG",
    )):
        blockers.append(
            f"The installed {script.name} does not support the reviewed project/environment contract. "
            "Its legacy implementation deploys Dev only. Copy the updated shared PURPLE launcher and helpers into this consumer root; no fallback is allowed."
        )
    else:
        if "--project-only" not in text or "AIFACTORY_PROJECT_ONLY" not in text:
            blockers.append("Install the reviewed root launcher with explicit --project-only and AIFACTORY_PROJECT_ONLY support; patch choice must not be ignored.")
        helper_paths = (root.parent / "lib" / "project_deployment.py", shared / "bootstrap" / "lib" / "project_deployment.py")
        helper = next((path for path in helper_paths if path.is_file()), None)
        if helper is None or "AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1" not in helper.read_text(encoding="utf-8-sig"):
            blockers.append("Install the reviewed lib/project_deployment.py helper with the root launcher.")
        version_directory = root.parent / "lib"
        if not (version_directory / "release_version.py").is_file():
            version_directory = shared / "bootstrap" / "lib"
        version_helpers = [version_directory / name for name in ("release_version.py", "release_version.sh")]
        if (release_version.CONTRACT not in text or helper is None
                or release_version.CONTRACT not in helper.read_text(encoding="utf-8-sig")
                or any(not path.is_file() or release_version.CONTRACT not in path.read_text(encoding="utf-8-sig")
                       for path in version_helpers)):
            blockers.append("Install the version-aware PURPLE root launcher, project_deployment.py, release_version.py and release_version.sh together. No legacy fallback.")
        if not any(path.is_file() for path in (root.parent / "ui" / "terminal.sh", shared / "bootstrap" / "ui" / "terminal.sh")):
            blockers.append("Install bootstrap/ui/terminal.sh alongside the root launcher or in the shared bootstrap folder.")
        required_templates = (
            (root.parent / ".github" / "workflows" / "infra-project.yml",
             root.parent / ".github" / "workflows" / "infra-project-phase.yml")
            if route == "gha" else (
                root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "esml-infra-project" / "infra-project-genai.yaml",
                root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "esml-infra-project" / "jobs" / "job-0-reviewed-project-config.yaml",
            )
        )
        for path in required_templates:
            if not path.is_file() or "AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1" not in path.read_text(encoding="utf-8-sig"):
                blockers.append(f"Install the reviewed target-selection pipeline file: {path}")
    return {
        "route": route, "script_path": str(script), "working_directory": str(root.parent),
        "config_path": str(config) if config else "", "hashes": hashes, "scope": scope,
        "subscription_id": subscription.lower(), "tenant_id": tenant.lower(), "blockers": blockers,
        "github_repository": github_repository,
        "installed_version": installed_version,
        "derived_config_hash": hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest() if config is None else "",
    }


class ProjectDeploymentService:
    def __init__(self, store=None, cli=None, identity=None, observe=None, select=None,
                 pty_factory=None, dispatch=None, clock=time.time, timeout=8 * 3600):
        self.store = store or operations.OperationsStore()
        self.cli = cli or simple_mode.ReadOnlyCLI()
        self.identity = identity or AzureTicketIdentity(self.cli, clock=clock)
        self._injected_identity = identity is not None
        self._terminal_identity_cache = None
        self._identity_lock = threading.RLock()
        self.observe = observe or self._observe
        self.select = select or selection
        self.pty_factory = pty_factory or OwnedPty
        self.dispatch = dispatch or self._dispatch
        self.clock = clock
        self.timeout = timeout
        self.terminals = TerminalSessions()
        self.stopping = False
        self.workers = set()
        self._migrate()

    def _migrate(self):
        key = str(self.store.db_path.resolve())
        with _LOCK, self.store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS project_deployment_drafts(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, folder TEXT NOT NULL,
                    project TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
                    status TEXT NOT NULL, job_id TEXT, payload TEXT NOT NULL,
                    operation TEXT NOT NULL DEFAULT 'deploy');
                CREATE UNIQUE INDEX IF NOT EXISTS project_deployment_one_active
                    ON project_deployment_drafts(folder) WHERE status IN ('queued','running');
                CREATE TABLE IF NOT EXISTS project_deployment_plans(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, folder TEXT NOT NULL,
                    draft_id TEXT NOT NULL, expires REAL NOT NULL, payload TEXT NOT NULL,
                    job_id TEXT, FOREIGN KEY(draft_id) REFERENCES project_deployment_drafts(id));
                CREATE TABLE IF NOT EXISTS project_deployment_reconciliations(
                    draft_id TEXT PRIMARY KEY, owner TEXT NOT NULL, folder TEXT NOT NULL,
                    job_id TEXT NOT NULL, confirmed_at TEXT NOT NULL, confirmation_id TEXT NOT NULL,
                    FOREIGN KEY(draft_id) REFERENCES project_deployment_drafts(id));
            """)
            if "operation" not in {row["name"] for row in db.execute("PRAGMA table_info(project_deployment_drafts)")}:
                # Replace the legacy lifetime uniqueness constraint without changing IDs,
                # consent receipts or reconciliation foreign keys.
                db.execute("PRAGMA foreign_keys=OFF")
                try:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("""CREATE TABLE project_deployment_drafts_new(
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL, folder TEXT NOT NULL,
                        project TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
                        status TEXT NOT NULL, job_id TEXT, payload TEXT NOT NULL,
                        operation TEXT NOT NULL DEFAULT 'deploy')""")
                    db.execute("""INSERT INTO project_deployment_drafts_new
                        SELECT id,owner,folder,project,source,target,status,job_id,payload,'deploy'
                        FROM project_deployment_drafts ORDER BY rowid""")
                    db.execute("DROP TABLE project_deployment_drafts")
                    db.execute("ALTER TABLE project_deployment_drafts_new RENAME TO project_deployment_drafts")
                    for row in db.execute("SELECT id,payload FROM project_deployment_drafts").fetchall():
                        draft = json.loads(row["payload"])
                        draft.update(operation="deploy", patch=False)
                        if draft.get("job_id"):
                            receipt = db.execute(
                                "SELECT payload FROM project_deployment_plans WHERE draft_id=? AND job_id=? ORDER BY rowid LIMIT 1",
                                (row["id"], draft["job_id"]),
                            ).fetchone()
                            consent = json.loads(receipt["payload"]) if receipt else {}
                            if isinstance(consent.get("argv"), list):
                                project_only = "--project-only" in consent["argv"] or str(
                                    consent.get("environment", {}).get("AIFACTORY_PROJECT_ONLY", "false")
                                ).lower() in ("true", "yes", "1")
                                draft["patch"] = not project_only
                        draft.setdefault("reconciled_at", None)
                        db.execute("UPDATE project_deployment_drafts SET payload=? WHERE id=?", (json.dumps(draft), row["id"]))
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                finally:
                    db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS project_deployment_one_active
                    ON project_deployment_drafts(folder) WHERE status IN ('queued','running');
                CREATE UNIQUE INDEX IF NOT EXISTS project_deployment_deploy_scope
                    ON project_deployment_drafts(owner,folder,project,source,target,operation) WHERE operation='deploy';
                CREATE UNIQUE INDEX IF NOT EXISTS project_deployment_pending_update
                    ON project_deployment_drafts(owner,folder,project,source,target,operation)
                    WHERE operation='update' AND status IN ('draft','queued','running');
            """)
            if key not in _INITIALIZED:
                for row in db.execute("SELECT * FROM project_deployment_drafts WHERE status IN ('queued','running')").fetchall():
                    self._update_row(db, row, "interrupted", "API host restarted; outcome unknown. Reconcile manually. No automatic retry.")
                _INITIALIZED.add(key)

    def _update_row(self, db, row, status, message, **changes):
        draft = json.loads(row["payload"])
        draft.update(status=status, message=message, updated_at=simple_mode.iso(self.clock()), **changes)
        db.execute("UPDATE project_deployment_drafts SET status=?,job_id=?,payload=? WHERE id=?",
                   (status, draft["job_id"], json.dumps(draft), row["id"]))
        return draft

    def _update(self, draft_id, status, message):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM project_deployment_drafts WHERE id=?", (draft_id,)).fetchone()
            if row["status"] == "interrupted":
                return json.loads(row["payload"])
            return self._update_row(db, row, status, message)

    def _observe(self, folder, number, source, target, refresh):
        local = operations.LocalFactoryDiscovery().discover(folder)
        if refresh:
            groups = []
            for sub in sorted({local["subscriptions"].get(source), local["subscriptions"].get(target)} - {None}):
                raw = self.cli.read("az", ["group", "list", "--subscription", sub, "--output", "json", "--only-show-errors"])
                if not isinstance(raw, list):
                    raise TicketError("Could not verify fresh Azure resource-group inventory.", 409)
                groups.extend({**g, "subscriptionId": sub} for g in raw if isinstance(g, dict))
        else:
            cached = self.store.latest_snapshot(folder, ("azure",))
            if not cached:
                raise TicketError("Refresh Azure inventory before planning; no observed source environment is available.", 409)
            payload = cached["payload"]
            scope = payload.get("configuration_scope", {})
            if (scope.get("monitoring_targets") != local["monitoring_targets"]
                    or scope.get("subscriptions") != local["subscription_ids"]):
                raise TicketError("Cached inventory belongs to a different factory configuration. Refresh first.", 409)
            groups = payload.get("resource_groups", [])
        observed = set()
        for group in groups:
            name = group.get("name", "")
            parsed = operations.parse_resource_group_name(name)
            sub = group.get("subscriptionId") or group.get("subscription_id")
            if (str(parsed.get("project_number", "")).lstrip("0") == number.lstrip("0")
                    and not parsed.get("is_common")
                    and operations.AzureInventoryProvider._is_relevant_group(name, local, sub)):
                observed.add(parsed.get("environment"))
        if source not in observed:
            raise TicketError("The source environment is not observed in this factory's Azure inventory.", 409)
        if source != target and target in observed:
            raise TicketError("The target environment is already observed. Refresh the board; no deployment draft may execute.", 409)

    def list(self, folder):
        folder = _folder(folder)
        owner = self.identity()
        with self.store._connect() as db:
            rows = db.execute("SELECT payload FROM project_deployment_drafts WHERE owner=? AND folder=? ORDER BY rowid",
                              (owner, folder)).fetchall()
        version, blockers = None, []
        try:
            version = release_version.project_selection(Path(folder).parent, None, False, self.cli)
        except TicketError as exc:
            blockers.append(str(exc))
        return {"drafts": [json.loads(row["payload"]) for row in rows],
                "version_selection": version, "version_blockers": blockers,
                **{key: version[key] if version else "" for key in ("requested_version", "branch", "resolved_ref")}}

    def plan(self, folder, project_number, source_environment, target_environment, patch=False, operation="deploy", aifactory_version=None):
        folder = _folder(folder)
        if not re.fullmatch(r"[0-9]{1,3}", project_number) or int(project_number) < 1:
            raise TicketError("project_number must be a saved project number from 001 to 999.")
        number = project_number.zfill(3)
        if type(patch) is not bool:
            raise TicketError("patch must be an explicit boolean.")
        if operation == "deploy":
            valid = (source_environment, target_environment) in (("dev", "stage"), ("stage", "prod"), ("dev", "prod"))
        elif operation == "update":
            valid = source_environment == target_environment and target_environment in ("dev", "stage", "prod")
        else:
            valid = False
        if not valid:
            raise TicketError("Deploy requires a later environment; Update requires the same observed Dev, Stage or Prod environment.")
        owner = self.identity()
        query = """SELECT * FROM project_deployment_drafts d
            WHERE owner=? AND folder=? AND project=? AND source=? AND target=? AND operation=?
            AND (operation='deploy' OR status IN ('draft','queued','running') OR
                (status IN ('failed','interrupted') AND NOT EXISTS
                 (SELECT 1 FROM project_deployment_reconciliations r WHERE r.draft_id=d.id)))
            ORDER BY rowid DESC LIMIT 1"""
        parameters = (owner, folder, number, source_environment, target_environment, operation)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(query, parameters).fetchone()
            if existing:
                if (existing["status"] != "draft" and aifactory_version is not None
                        and release_version.normalize(aifactory_version) != json.loads(existing["payload"]).get("requested_version")):
                    raise TicketError("An executed draft cannot change AI Factory version. Reconcile and create a new draft.", 409)
                return self._set_patch(db, existing, patch, aifactory_version) if existing["status"] == "draft" else json.loads(existing["payload"])
        self.observe(folder, number, source_environment, target_environment, False)
        chosen = self.select(folder, number, target_environment)
        version = release_version.select(aifactory_version, saved=chosen.get("installed_version"))
        now = simple_mode.iso(self.clock())
        draft = {
            "id": str(uuid4()), "project_number": number, "source_environment": source_environment,
            "target_environment": target_environment, "status": "draft",
            "operation": operation, "patch": patch, "reconciled_at": None,
            "message": f"Local {operation} draft only. Review and explicitly confirm to execute.",
            "route": chosen["route"], "script_path": chosen["script_path"], "job_id": None,
            "created_at": now, "updated_at": now,
            "aifactory_version": aifactory_version,
            **version,
        }
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO project_deployment_drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (draft["id"], owner, folder, number, source_environment, target_environment, "draft", None, json.dumps(draft), operation))
            row = db.execute(query, parameters).fetchone()
        return json.loads(row["payload"])

    def _set_patch(self, db, row, patch, aifactory_version=None):
        draft = json.loads(row["payload"])
        saved = draft.get("requested_version")
        if not saved:
            saved = release_version.saved_version(Path(row["folder"]).parent)
        version = release_version.select(aifactory_version, saved=saved)
        raw = aifactory_version if aifactory_version is not None else draft.get("aifactory_version")
        if (draft["patch"] != patch or version["requested_version"] != draft.get("requested_version")
                or raw != draft.get("aifactory_version")):
            db.execute("UPDATE project_deployment_plans SET expires=0 WHERE draft_id=? AND job_id IS NULL", (row["id"],))
            draft = self._update_row(db, row, row["status"], draft["message"], patch=patch, aifactory_version=raw, **version)
        return draft

    @staticmethod
    def _request(draft):
        return {key: draft.get(key) for key in ("id", "project_number", "source_environment", "target_environment", "operation", "patch", "requested_version", "aifactory_version")}

    def _get(self, folder, owner, draft_id=None, job_id=None):
        with self.store._connect() as db:
            row = db.execute(
                "SELECT * FROM project_deployment_drafts WHERE owner=? AND folder=? AND " + ("id=?" if draft_id else "job_id=?"),
                (owner, folder, draft_id or job_id),
            ).fetchone()
        if not row:
            raise TicketError("Deployment draft or terminal not found for this owner and folder.", 404)
        return row

    def _context(self, chosen, owner):
        accounts = self.cli.accounts()
        account = next((a for a in accounts if a["subscription_id"].lower() == chosen["subscription_id"]), None)
        if not account or account["tenant_id"].lower() != chosen["tenant_id"]:
            raise TicketError("Target subscription/tenant is not an enabled host Azure CLI account.", 403)
        scoped = AzureTicketIdentity(simple_mode.ScopedIdentityAuth(self.cli, account), clock=self.clock)()
        if scoped != owner:
            raise TicketError("Target subscription has a different authenticated Azure identity.", 403)
        root = chosen["working_directory"]
        remote = self.cli.read("git", ["-C", root, "remote", "get-url", "origin"], raw=True).strip()
        if chosen["route"] == "gha":
            match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", remote)
            if not match:
                raise TicketError("Origin must identify the selected GitHub consumer repository without embedded credentials.", 409)
            repository = match[1]
            if chosen.get("github_repository", "").casefold() != repository.casefold():
                raise TicketError("GITHUB_NEW_REPO in the consumer .env does not match the reviewed GitHub origin.", 409)
            login, scopes = self.cli.github()
            data = self.cli.read("gh", ["api", "--hostname", "github.com", "repos/" + repository])
            if data.get("full_name", "").casefold() != repository.casefold() or data.get("archived") or not data.get("permissions", {}).get("push"):
                raise TicketError("GitHub identity cannot push to the selected consumer repository.", 403)
            return {"github_login": login, "repository": repository, "repository_id": data.get("id"), "origin": remote}
        parsed = urlsplit(remote)
        match = re.fullmatch(r"/([^/]+)/([^/]+)/_git/([^/]+)", parsed.path.rstrip("/"))
        if parsed.scheme != "https" or parsed.hostname != "dev.azure.com" or parsed.username or parsed.password or not match:
            raise TicketError("ADO requires a credential-free HTTPS dev.azure.com organization/project/_git/repository origin.", 409)
        organization, project, repository = (unquote(part) for part in match.groups())
        if any(not re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", item) for item in (organization, project, repository)):
            raise TicketError("The Azure DevOps origin contains unsupported target identifiers.", 409)
        data = self.cli.read("az", [
            "repos", "show", "--organization", "https://dev.azure.com/" + organization,
            "--project", project, "--repository", repository, "--output", "json", "--only-show-errors",
        ])
        if not data.get("id"):
            raise TicketError("Azure DevOps CLI access to the selected repository could not be verified.", 403)
        return {"organization": "https://dev.azure.com/" + organization, "project": project,
                "repository": repository, "repository_id": data["id"], "origin": remote}

    def _preview(self, folder, draft, owner):
        chosen = self.select(folder, draft["project_number"], draft["target_environment"])
        blockers = list(chosen["blockers"])
        version = release_version.select(draft.get("requested_version"), saved=chosen.get("installed_version"))
        try:
            version = release_version.project_selection(chosen["working_directory"], version["requested_version"], draft["patch"], self.cli, route=chosen["route"])
        except TicketError as exc:
            blockers.append(str(exc))
        tools = self.cli.tools()
        required = {"bash", "git", "python", "az"} | ({"gh"} if chosen["route"] == "gha" else set())
        if required - tools.keys():
            blockers.append("Install host tools: " + ", ".join(sorted(required - tools.keys())) + ".")
        if not self.pty_factory.available():
            blockers.append("Interactive PTY support is unavailable. Install pywinpty/Windows ConPTY (or a supported Unix PTY).")
        context = {}
        try:
            context = self._context(chosen, owner)
            self.observe(folder, draft["project_number"], draft["source_environment"], draft["target_environment"], True)
        except TicketError as exc:
            blockers.append(str(exc))
        environment = {
            **release_version.environment(version),
            "TERM": "xterm-256color", "AIFACTORY_REPO_ROOT": bash_path(chosen["working_directory"]),
            "AIFACTORY_TARGET_ENVIRONMENT": draft["target_environment"],
            "AIFACTORY_PROJECT_NUMBER": draft["project_number"],
            "AIFACTORY_PROJECT_CONFIG": bash_path(chosen["config_path"]),
            "AIFACTORY_USE_JSON_OVERRIDE": "yes",
            "AIFACTORY_PROJECT_ONLY": "false" if draft["patch"] else "true",
        }
        protected_config = None
        if chosen.get("derived_config_hash") and not blockers:
            document = derived_document(folder, draft["project_number"])
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != chosen["derived_config_hash"]:
                raise TicketError("Saved project changed while deriving the reviewed configuration.", 409)
            envelope = {
                "schema": 1, "folder": folder, "project": draft["project_number"],
                "target": draft["target_environment"], "document": document,
            }
            try:
                sealed = protect(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
            except ValueError as exc:
                raise TicketError(str(exc), 409) from None
            artifact = self.store.db_path.resolve().parent / "deployment-configs" / (str(uuid4()) + ".dpapi")
            protected_config = {"path": str(artifact), "ciphertext": base64.b64encode(sealed).decode("ascii"),
                                "sha256": hashlib.sha256(sealed).hexdigest()}
            environment["AIFACTORY_PROJECT_CONFIG"] = bash_path(artifact)
        if chosen["route"] == "ado" and context:
            environment.update(ADO_ORGANIZATION=context["organization"], ADO_PROJECT=context["project"],
                               ADO_REPOSITORY_NAME=context["repository"], ADO_TENANT=chosen["tenant_id"], ADO_AUTH_METHOD="aad")
        argv = [tools.get("bash", "bash"), "--noprofile", "--norc", bash_path(chosen["script_path"])]
        if not draft["patch"]:
            argv.append("--project-only")
        command = " ".join(f"{key}={shlex.quote(value)}" for key, value in environment.items()) + " " + shlex.join(argv)
        preview = {
            "confirmation_id": str(uuid4()), "can_execute": not blockers, "expires_at": simple_mode.iso(self.clock() + 600),
            "summary": f"{draft['operation'].title()} saved project {draft['project_number']}: {draft['source_environment']} → {draft['target_environment']} using {chosen['route'].upper()}. Patch {'checked: refresh AI Factory/templates before running the project' if draft['patch'] else 'unchecked: project-only, no AI Factory/template refresh'}.",
            "command": command, "working_directory": chosen["working_directory"],
            "aifactory_version": draft.get("aifactory_version"),
            **version,
            **patch_disclosure(draft["patch"]), "blockers": blockers,
        }
        if protected_config:
            preview["effects"].append(
                "Use an immutable current-user-DPAPI-encrypted export of this saved project. After confirmation an encrypted local artifact is created, read in memory and removed; no plaintext configuration or advanced-editor state is overwritten."
            )
        return {"preview": preview, "selection": chosen, "context": context, "tools": tools,
                "environment": environment, "argv": argv, "protected_config": protected_config, "request": self._request(draft),
                "version": version}

    def prepare(self, folder, draft_id, patch=False, aifactory_version=None):
        if type(patch) is not bool:
            raise TicketError("patch must be an explicit boolean.")
        folder, owner = _folder(folder), self.identity()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM project_deployment_drafts WHERE id=? AND owner=? AND folder=?", (draft_id, owner, folder)).fetchone()
            if not row:
                raise TicketError("Deployment draft not found for this owner and folder.", 404)
            if row["status"] != "draft":
                raise TicketError("This draft already executed or needs manual reconciliation; it cannot be retried.", 409)
            draft = self._set_patch(db, row, patch, aifactory_version)
        try:
            plan = self._preview(folder, draft, owner)
        except (TicketError, OSError, ValueError) as exc:
            message = str(exc) if isinstance(exc, TicketError) else "Configuration is malformed or unreadable. Review and save the selected project."
            version = {key: draft.get(key) or "" for key in ("requested_version", "branch")}
            version["resolved_ref"] = ""
            plan = {"version": version, "preview": {
                **version,
                "aifactory_version": draft.get("aifactory_version"),
                "confirmation_id": str(uuid4()), "can_execute": False,
                "summary": f"{draft['operation'].title()} is blocked. Patch {'checked' if patch else 'unchecked (project-only)'}.",
                "command": "", "working_directory": str(Path(folder).parent), **patch_disclosure(patch),
                "blockers": [message], "expires_at": simple_mode.iso(self.clock() + 600),
            }}
        plan["preview"]["deployment_contract"] = deployment_acknowledgement({**draft, **plan.get("version", {})})
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM project_deployment_drafts WHERE id=?", (draft_id,)).fetchone()
            if current["status"] != "draft" or self._request(json.loads(current["payload"])) != self._request(draft):
                raise TicketError("Draft or patch choice changed during preparation. Review again.", 409)
            if plan.get("version"):
                self._update_row(db, current, "draft", draft["message"], **plan["version"])
            db.execute("INSERT INTO project_deployment_plans VALUES(?,?,?,?,?,?,NULL)",
                       (plan["preview"]["confirmation_id"], owner, folder, draft_id, self.clock() + 600, json.dumps(plan)))
        return plan["preview"]

    def _recheck(self, plan, folder, draft, owner):
        current = json.loads(self._get(folder, owner, draft_id=draft["id"])["payload"])
        acknowledgement = deployment_acknowledgement(current)
        if plan["preview"].get("deployment_contract") != acknowledgement:
            raise TicketError("Deployment consent lacks the current explicit operation/patch acknowledgement. Prepare again.", 409)
        version_keys = ("requested_version", "branch", "resolved_ref")
        if (any(plan["preview"].get(key) != acknowledgement[key] for key in ("aifactory_version", *version_keys))
                or not isinstance(plan.get("version"), dict)
                or any(plan["version"].get(key) != acknowledgement[key] for key in version_keys)):
            raise TicketError("Reviewed version metadata differs from the deployment acknowledgement. Prepare again.", 409)
        if plan.get("request") != self._request(current) or self._request(draft) != self._request(current):
            raise TicketError("Draft operation, target or patch choice changed or uses legacy consent. Prepare again.", 409)
        if (("--project-only" in plan["argv"]) != (not current["patch"])
                or plan["environment"].get("AIFACTORY_PROJECT_ONLY") != ("false" if current["patch"] else "true")):
            raise TicketError("Reviewed patch command differs from the selected behavior. Prepare again.", 409)
        if self.identity() != owner:
            raise TicketError("Host Azure identity changed after confirmation.", 409)
        chosen = self.select(folder, draft["project_number"], draft["target_environment"])
        if chosen != plan["selection"] or chosen["blockers"] or self.cli.tools() != plan["tools"]:
            raise TicketError("Saved configuration, scripts, dependencies, scope or host tools changed. Prepare again.", 409)
        if not plan.get("version") or any(plan["environment"].get(key) != value for key, value in release_version.environment(plan["version"]).items()):
            raise TicketError("Version selection differs from the immutable reviewed command. Prepare again.", 409)
        if not draft["patch"] and release_version.project_selection(
                chosen["working_directory"], draft.get("requested_version"), False, self.cli) != plan["version"]:
            raise TicketError("Installed AI Factory commit changed after preview. Prepare again.", 409)
        if self._context(chosen, owner) != plan["context"]:
            raise TicketError("Host CLI identity or destination repository changed. Prepare again.", 409)
        self.observe(folder, draft["project_number"], draft["source_environment"], draft["target_environment"], True)

    def _reconciliation_blockers(self, db, row):
        blockers = []
        if row["status"] not in ("failed", "interrupted"):
            blockers.append("Only failed or interrupted outcomes can be acknowledged.")
        if db.execute("SELECT 1 FROM project_deployment_drafts WHERE folder=? AND status IN ('queued','running')", (row["folder"],)).fetchone():
            blockers.append("Wait for every local deployment in this repository to stop.")
        session = self.terminals.get(row["job_id"])
        if session is not None and not session["complete"]:
            blockers.append("The owned terminal is still closing; finish local process cleanup first.")
        return blockers

    def prepare_reconciliation(self, folder, job_id):
        folder, owner = _folder(folder), self.identity()
        row = self._get(folder, owner, job_id=job_id)
        draft = json.loads(row["payload"])
        with _LOCK, self.store._connect() as db:
            blockers = self._reconciliation_blockers(db, row)
            if db.execute("SELECT 1 FROM project_deployment_reconciliations WHERE draft_id=?", (row["id"],)).fetchone():
                blockers.append("This outcome was already acknowledged.")
            preview = {
                "confirmation_id": str(uuid4()), "can_execute": not blockers,
                "summary": f"Acknowledge reviewed {draft['status']} outcome for project {draft['project_number']} → {draft['target_environment']}.",
                "command": "Local reconciliation acknowledgement only; no command is executed.",
                "working_directory": str(Path(folder).parent),
                "effects": [
                    "Record that you inspected this exact job's local Git/configuration changes and Azure/pipeline outcome.",
                    "Confirm only after any remote pipeline has finished or been cancelled and its partial changes are understood.",
                    "Remove this job's repository-wide safety hold. Other unreconciled failures still block new deployments.",
                    "Keep the failed/interrupted status, terminal history and original draft. This does not retry or reset that draft.",
                    "No Git, pipeline or Azure resources are changed or automatically verified by this acknowledgement.",
                ],
                "warnings": ["You are attesting to manual review, not reporting deployment success. Use a separate new draft for any other deployment."],
                "blockers": blockers, "expires_at": simple_mode.iso(self.clock() + 600),
            }
            payload = {"kind": "reconciliation", "preview": preview,
                       "failure_hash": hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()}
            db.execute("INSERT INTO project_deployment_plans VALUES(?,?,?,?,?,?,NULL)",
                       (preview["confirmation_id"], owner, folder, row["id"], self.clock() + 600, json.dumps(payload)))
        return preview

    def reconcile(self, folder, confirmation_id):
        folder, owner = _folder(folder), self.identity()
        with _LOCK, self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            plan_row = db.execute("SELECT * FROM project_deployment_plans WHERE id=? AND owner=? AND folder=?",
                                  (confirmation_id, owner, folder)).fetchone()
            if not plan_row:
                raise TicketError("Reconciliation confirmation not found for this owner and factory.", 404)
            plan = json.loads(plan_row["payload"])
            if plan.get("kind") != "reconciliation":
                raise TicketError("Deployment consent cannot acknowledge a failed outcome.", 409)
            row = db.execute("SELECT * FROM project_deployment_drafts WHERE id=? AND owner=? AND folder=?",
                             (plan_row["draft_id"], owner, folder)).fetchone()
            if plan_row["job_id"]:
                return json.loads(row["payload"])
            if self.stopping or plan_row["expires"] <= self.clock() or not plan["preview"]["can_execute"]:
                raise TicketError("Reconciliation consent expired or is blocked; review the outcome again.", 409)
            if self._reconciliation_blockers(db, row) or hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != plan["failure_hash"]:
                raise TicketError("The outcome or local worker changed after review; prepare reconciliation again.", 409)
            confirmed_at = simple_mode.iso(self.clock())
            db.execute("INSERT INTO project_deployment_reconciliations VALUES(?,?,?,?,?,?)",
                       (row["id"], owner, folder, row["job_id"], confirmed_at, confirmation_id))
            result = self._update_row(
                db, row, row["status"],
                "Outcome manually reviewed and acknowledged. Repository safety hold released for this job; original draft is not retryable.",
                reconciled_at=confirmed_at,
            )
            db.execute("UPDATE project_deployment_plans SET job_id=? WHERE id=?", (row["job_id"], confirmation_id))
            return result

    def start(self, folder, confirmation_id):
        folder, owner = _folder(folder), self.identity()
        with _LOCK, self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM project_deployment_plans WHERE id=? AND owner=? AND folder=?",
                             (confirmation_id, owner, folder)).fetchone()
            if not row:
                raise TicketError("Confirmation not found for this owner and factory.", 404)
            saved = db.execute("SELECT * FROM project_deployment_drafts WHERE id=?", (row["draft_id"],)).fetchone()
            draft = json.loads(saved["payload"])
            plan = json.loads(row["payload"])
            if plan.get("kind", "deployment") != "deployment":
                raise TicketError("Reconciliation consent cannot execute a deployment.", 409)
            if row["job_id"]:
                return draft
            if self.stopping or saved["status"] != "draft" or row["expires"] <= self.clock() or not plan["preview"]["can_execute"]:
                raise TicketError("Confirmation is expired, blocked or already used. Review the draft and reconcile prior outcomes.", 409)
            if db.execute("""SELECT 1 FROM project_deployment_drafts d WHERE folder=? AND
                          (status IN ('queued','running') OR
                           (status IN ('failed','interrupted') AND NOT EXISTS
                            (SELECT 1 FROM project_deployment_reconciliations r WHERE r.draft_id=d.id)))""",
                          (folder,)).fetchone():
                raise TicketError("This repository has an active or unreconciled deployment. Inspect its outcome before another launch.", 409)
            self._recheck(plan, folder, draft, owner)
            job_id = str(uuid4())
            draft = self._update_row(
                db, saved, "queued", "Confirmed deployment queued.", job_id=job_id,
                route=plan["selection"]["route"], script_path=plan["selection"]["script_path"],
            )
            db.execute("UPDATE project_deployment_plans SET job_id=? WHERE id=?", (job_id, confirmation_id))
        dispatched = False
        handled = False
        try:
            self.terminals.create(job_id)
            self.dispatch(lambda: self._work(folder, draft, plan, owner))
            dispatched = True
        except KNOWN_EXECUTION_ERRORS as exc:
            handled = True
            session = self.terminals.get(job_id)
            self._terminal_error(session, exc, "worker startup failed")
            if session:
                session["complete"] = session["pty"] is None
            return self._update(draft["id"], "failed", f"The deployment worker could not start ({type(exc).__name__}). Inspect terminal/prerequisites; no automatic retry.")
        finally:
            if not dispatched and not handled:
                unexpected = sys.exc_info()[1]
                session = self.terminals.get(job_id)
                if unexpected is not None:
                    self._terminal_error(session, unexpected, "unexpected worker startup failure")
                    self._update(draft["id"], "failed", f"Unexpected worker startup failure ({type(unexpected).__name__}); inspect terminal and reconcile.")
                    if session:
                        session["complete"] = session["pty"] is None
                    if not isinstance(unexpected, (KeyboardInterrupt, SystemExit)):
                        raise RuntimeError(f"Unexpected deployment startup failure ({type(unexpected).__name__}); details are confined to the local terminal.") from None
        return draft

    def _dispatch(self, action):
        thread = threading.Thread(target=action, name="project-deployment-pty", daemon=True)
        self.workers.add(thread)
        thread.start()

    @staticmethod
    def _terminal_error(session, error, phase):
        if session is None:
            return
        text = " ".join("".join(character if character.isprintable() else " " for character in str(error)).split())[:2048]
        text = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [redacted]", text)
        text = re.sub(r'''(?i)((?:access[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret)\s*[:=]\s*)("[^"]*"|'[^']*'|\S+)''',
                      r"\1[redacted]", text)
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted token]", text)
        text = re.sub(r"(https?://)[^/\s@]+:[^/\s@]+@", r"\1[redacted]@", text)
        session["buffer"].append(f"\r\n[deployment {phase}] {type(error).__name__}: {text}\r\n")

    def _work(self, folder, draft, plan, owner):
        process = None
        timer = None
        session = self.terminals.get(draft["job_id"])
        timed_out = threading.Event()
        protected_artifact = None
        try:
            self._recheck(plan, folder, draft, owner)
            with _LOCK:
                if self.stopping:
                    raise TicketError("API host is shutting down.", 409)
                protected = plan.get("protected_config")
                if protected:
                    raw = base64.b64decode(protected["ciphertext"], validate=True)
                    if hashlib.sha256(raw).hexdigest() != protected["sha256"]:
                        raise TicketError("Encrypted deployment configuration changed after review.", 409)
                    path = Path(protected["path"])
                    for ancestor in (path, *path.parents):
                        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                            raise TicketError("Encrypted configuration path traverses a link.", 409)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(raw)
                    protected_artifact = path
                environment = simple_mode.launch_environment(plan["environment"], plan["tools"])
                # Unlike unattended Simple Mode, let CLI tools use their own terminal prompts.
                for key in ("GIT_TERMINAL_PROMPT", "GCM_INTERACTIVE", "GH_PROMPT_DISABLED"):
                    environment.pop(key, None)
                process = self.pty_factory(plan["argv"], cwd=plan["selection"]["working_directory"], env=environment)
                session["pty"] = process
                session["accepting"] = True
            self._update(draft["id"], "running", "Root deployment script is running in the interactive terminal.")

            def timeout():
                timed_out.set()
                session["accepting"] = False
                try:
                    process.close()
                except KNOWN_EXECUTION_ERRORS as exc:
                    self._terminal_error(session, exc, "timeout cleanup failed")
                    self._update(draft["id"], "interrupted", "Owned terminal timeout cleanup failed; verify child processes stopped before reconciliation.")

            timer = threading.Timer(self.timeout, timeout)
            timer.daemon = True
            timer.start()
            while True:
                text = process.read()
                if not text:
                    break
                session["buffer"].append(text)
            session["accepting"] = False
            code = process.wait()
            if self.stopping or timed_out.is_set():
                self._update(draft["id"], "interrupted", "Owned script stopped during API shutdown or timeout. Reconcile local/cloud outcome before retry.")
            else:
                self._update(draft["id"], "submitted" if code == 0 else "failed",
                             "Script exited zero; submission is not deployment evidence. Refresh Azure inventory." if code == 0 else
                             "Script failed. Inspect terminal and reconcile partial local/cloud changes; no automatic retry.")
        except KNOWN_EXECUTION_ERRORS as exc:
            self._terminal_error(session, exc, "execution failed")
            self._update(draft["id"], "interrupted" if self.stopping or timed_out.is_set() else "failed",
                         f"Deployment stopped or could not execute safely ({type(exc).__name__}). Inspect the terminal and reconcile local/cloud state.")
        finally:
            unexpected = sys.exc_info()[1]
            if unexpected is not None:
                self._terminal_error(session, unexpected, "unexpected worker failure")
                self._update(draft["id"], "failed", f"Unexpected deployment worker failure ({type(unexpected).__name__}); inspect terminal and reconcile.")
            if timer:
                timer.cancel()
            session["accepting"] = False
            close_failed = False
            if process:
                try:
                    process.close()
                except KNOWN_EXECUTION_ERRORS as exc:
                    close_failed = True
                    self._terminal_error(session, exc, "owned process cleanup failed")
                    self._update(draft["id"], "interrupted", "Owned terminal cleanup failed. Stop the API host, verify its child processes stopped, then reconcile.")
                finally:
                    close_error = sys.exc_info()[1]
                    if close_error is not None and not close_failed:
                        self._terminal_error(session, close_error, "unexpected owned process cleanup failure")
                        session["pty"], session["complete"] = process, False
                        self._update(draft["id"], "interrupted", "Unexpected owned terminal cleanup failure; stop the API and reconcile its child processes.")
                        self.workers.discard(threading.current_thread())
                        raise RuntimeError("Unexpected owned process cleanup failure; details are confined to the local terminal.") from None
            session["pty"] = process if close_failed else None
            session["complete"] = not close_failed
            if protected_artifact:
                try:
                    if hashlib.sha256(protected_artifact.read_bytes()).hexdigest() == plan["protected_config"]["sha256"]:
                        protected_artifact.unlink()
                except OSError as exc:
                    self._terminal_error(session, exc, "encrypted artifact cleanup failed")
                    self._update(draft["id"], "interrupted", "Encrypted deployment artifact cleanup failed; review local artifact ownership before reconciliation.")
            self.workers.discard(threading.current_thread())
            if unexpected is not None and not isinstance(unexpected, (KeyboardInterrupt, SystemExit)):
                raise RuntimeError(f"Unexpected deployment worker failure ({type(unexpected).__name__}); details are confined to the local terminal.") from None

    def _terminal_owner(self):
        if self._injected_identity:
            return self.identity()
        # A short authenticated lease avoids spawning two Azure CLIs per keystroke.
        # Any normal CLI sign-in/account-switch/logout changes these cache files.
        root = Path(os.environ.get("AZURE_CONFIG_DIR") or Path.home() / ".azure")
        signature = []
        for name in ("azureProfile.json", "msal_token_cache.bin", "msal_token_cache.json", "service_principal_entries.json"):
            path = root / name
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                signature.append((str(path), None, None))
        with self._identity_lock:
            cached = self._terminal_identity_cache
            if cached and cached[0] == signature and self.clock() < cached[1]:
                return cached[2]
            owner = self.identity()
            self._terminal_identity_cache = (signature, self.clock() + 5, owner)
            return owner

    def terminal(self, folder, job_id, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise TicketError("Terminal cursor must be a nonnegative integer.")
        folder, owner = _folder(folder), self._terminal_owner()
        draft = json.loads(self._get(folder, owner, job_id=job_id)["payload"])
        session = self.terminals.get(job_id)
        if session is None:
            raise TicketError("Terminal history expired or the API host restarted. Raw output is unavailable; inspect the durable deployment status.", 410)
        result = session["buffer"].read(cursor)
        return {"job_id": job_id, **result, "status": draft["status"]}

    def _input_session(self, folder, job_id):
        folder, owner = _folder(folder), self._terminal_owner()
        row = self._get(folder, owner, job_id=job_id)
        session = self.terminals.get(job_id)
        if row["status"] != "running" or not session or not session["accepting"] or session["pty"] is None:
            raise TicketError("Input is accepted only by this owner's active deployment PTY.", 409)
        return session["pty"]

    def input(self, folder, job_id, data):
        if not isinstance(data, str) or not 1 <= len(data) <= 8192:
            raise TicketError("Terminal input must contain 1 to 8192 characters.")
        process = self._input_session(folder, job_id)
        process.write(data)
        return {}

    def resize(self, folder, job_id, columns, rows):
        if type(columns) is not int or type(rows) is not int or not 20 <= columns <= 500 or not 5 <= rows <= 200:
            raise TicketError("Terminal dimensions must be 20–500 columns and 5–200 rows.")
        process = self._input_session(folder, job_id)
        process.resize(columns, rows)
        return {}

    def shutdown(self):
        try:
            with _LOCK:
                self.stopping = True
                self.terminals.shutdown()
        finally:
            for thread in list(self.workers):
                thread.join(timeout=5)
            with self.store._connect() as db:
                for job_id in list(self.terminals.sessions):
                    row = db.execute("SELECT * FROM project_deployment_drafts WHERE job_id=? AND status IN ('queued','running')", (job_id,)).fetchone()
                    if row:
                        self._update_row(db, row, "interrupted", "API host shut down. Verify owned terminal cleanup and reconcile deployment outcome.")
