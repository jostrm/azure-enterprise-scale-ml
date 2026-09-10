import copy
import asyncio
import json
import hashlib
import os
import re
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src import api, operations, project_deployments as pd, simple_mode, wizard
from src.deployment_terminal import OwnedPty, TerminalBuffer, TerminalSessions
from src.ticket_connectors import TicketError


SUB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "azure:" + TENANT + ":22222222-2222-4222-8222-222222222222"


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("No real CLI calls")))
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=AssertionError("No real deployment launches")))
    root = tmp_path / "consumer"
    folder = root / "aifactory"
    folder.mkdir(parents=True)
    chosen = {
        "route": "gha", "script_path": str(root / pd.SCRIPTS["gha"]), "working_directory": str(root),
        "config_path": str(folder / "config-wizard" / "project-017" / "variables.json"),
        "hashes": {"script": "original"}, "scope": {"subscriptions": {"stage": SUB}},
        "subscription_id": SUB, "tenant_id": TENANT, "blockers": [],
        "installed_version": "124",
    }
    state = {"owner": OWNER}
    work = []
    clock = [1800000000]
    process = SimpleNamespace(
        read=Mock(side_effect=["\x1b[32msecret-only-in-terminal\x1b[0m", ""]),
        write=Mock(), resize=Mock(), close=Mock(), wait=lambda: 0,
    )
    factory = Mock(return_value=process)
    factory.available = lambda: True
    cli = SimpleNamespace(tools=lambda: {name: name for name in ("az", "gh", "bash", "git", "python")})
    service = pd.ProjectDeploymentService(
        store=operations.OperationsStore(tmp_path / "operations.db"), cli=cli,
        identity=lambda: state["owner"], observe=Mock(), select=lambda *args: copy.deepcopy(chosen),
        pty_factory=factory, dispatch=work.append, clock=lambda: clock[0],
    )
    service._context = Mock(return_value={"github_login": "tester", "repository": "org/consumer"})
    monkeypatch.setattr(pd.release_version, "project_selection",
                        lambda root, requested, patch, cli, route=None: {
                            **pd.release_version.select(requested, saved=chosen["installed_version"]), "resolved_ref": "a" * 40,
                        })
    return SimpleNamespace(service=service, root=root, folder=pd._folder(str(folder)), chosen=chosen, state=state,
                           work=work, clock=clock, factory=factory, process=process)


def plan(c):
    return c.service.plan(c.folder, "017", "dev", "stage")


def prepared(c):
    draft = plan(c)
    preview = c.service.prepare(c.folder, draft["id"])
    assert preview["can_execute"], preview["blockers"]
    return draft, preview


def test_plan_local_idempotent_persistent_and_scoped(context):
    c = context
    before = set(c.root.rglob("*"))
    first = plan(c)
    assert plan(c) == first
    assert c.service.list(c.folder)["drafts"] == [first]
    assert set(c.root.rglob("*")) == before
    assert not c.work
    c.factory.assert_not_called()
    c.service.observe.assert_called_once_with(c.folder, "017", "dev", "stage", False)
    second = pd.ProjectDeploymentService(c.service.store, identity=lambda: OWNER)
    assert second.list(c.folder)["drafts"] == [first]
    c.state["owner"] = "other"
    assert c.service.list(c.folder)["drafts"] == []


def test_plan_concurrent_idempotence(context):
    with ThreadPoolExecutor(max_workers=4) as pool:
        drafts = list(pool.map(lambda _: plan(context), range(4)))
    assert len({d["id"] for d in drafts}) == 1


def test_list_exposes_inherited_installed_version_before_first_draft(context):
    c = context
    c.chosen["installed_version"] = "1.100"
    result = c.service.list(c.folder)
    assert result == {"drafts": [], "version_selection": {
        "requested_version": "1.100", "branch": "release/v1.100", "resolved_ref": "a" * 40,
    }, "version_blockers": [], "requested_version": "1.100", "branch": "release/v1.100", "resolved_ref": "a" * 40}
    c.factory.assert_not_called()
    c.service.observe.assert_not_called()


def test_list_keeps_drafts_visible_when_installed_version_is_unknown(context, monkeypatch):
    c = context
    draft = plan(c)
    monkeypatch.setattr(pd.release_version, "project_selection",
                        Mock(side_effect=TicketError("Existing factory version is unknown.", 409)))
    result = c.service.list(c.folder)
    assert result["drafts"] == [draft]
    assert result["version_selection"] is None
    assert result["version_blockers"] == ["Existing factory version is unknown."]
    assert not any(result[key] for key in ("requested_version", "branch", "resolved_ref"))


@pytest.mark.parametrize("source,target", [("stage", "stage"), ("prod", "dev"), ("dev", "dev"), ("dev", "test")])
def test_plan_rejects_invalid_targets(context, source, target):
    with pytest.raises(TicketError):
        context.service.plan(context.folder, "017", source, target)


def test_plan_requires_observed_source_absent_target(context):
    context.service.observe.side_effect = TicketError("Source not observed", 409)
    with pytest.raises(TicketError):
        plan(context)
    assert not context.service.list(context.folder)["drafts"]


def test_plan_inherits_saved_version_and_prepare_retains_explicit_selection(context):
    c = context
    c.chosen["installed_version"] = "125"
    draft = plan(c)
    assert draft["requested_version"] == "125"
    preview = c.service.prepare(c.folder, draft["id"], patch=True, aifactory_version="1.100")
    assert preview["can_execute"], preview["blockers"]
    assert preview["requested_version"] == "1.100"
    assert preview["branch"] == "release/v1.100"
    assert preview["resolved_ref"] == "a" * 40
    again = c.service.prepare(c.folder, draft["id"], patch=True)
    assert again["requested_version"] == "1.100"
    assert c.service.list(c.folder)["drafts"][0]["requested_version"] == "1.100"


def test_version_choice_change_invalidates_previous_confirmation(context):
    c = context
    draft, preview = prepared(c)
    c.service.prepare(c.folder, draft["id"], patch=True, aifactory_version="125")
    with pytest.raises(TicketError):
        c.service.start(c.folder, preview["confirmation_id"])
    c.factory.assert_not_called()


def test_prepared_acknowledgement_binds_exact_release_tuple(context):
    c = context
    draft = c.service.plan(c.folder, "017", "dev", "stage", patch=True, aifactory_version="125")
    preview = c.service.prepare(c.folder, draft["id"], patch=True)
    ack = preview["deployment_contract"]
    assert ack == {"version": 2, "draft_id": draft["id"], "operation": "deploy", "patch": True,
                   "aifactory_version": "125",
                   "requested_version": "125", "branch": "release/v1.25", "resolved_ref": "a" * 40}
    assert all(ack[key] == preview[key] for key in ("requested_version", "branch", "resolved_ref"))
    with c.service.store._connect() as db:
        row = db.execute("SELECT payload FROM project_deployment_plans WHERE id=?", (preview["confirmation_id"],)).fetchone()
        payload = json.loads(row["payload"])
        payload["preview"]["deployment_contract"]["resolved_ref"] = "b" * 40
        db.execute("UPDATE project_deployment_plans SET payload=? WHERE id=?", (json.dumps(payload), preview["confirmation_id"]))
    with pytest.raises(TicketError, match="acknowledgement"):
        c.service.start(c.folder, preview["confirmation_id"])
    c.factory.assert_not_called()


@pytest.mark.parametrize("key,value", [
    ("aifactory_version", "124"), ("requested_version", "125"),
    ("branch", "release/v1.25"), ("resolved_ref", "b" * 40),
])
@pytest.mark.parametrize("remove", [False, True])
def test_consent_rejects_changed_or_missing_preview_version_metadata(context, key, value, remove):
    c = context
    draft = c.service.plan(c.folder, "017", "dev", "stage", patch=True, aifactory_version="1.24")
    preview = c.service.prepare(c.folder, draft["id"], patch=True)
    with c.service.store._connect() as db:
        row = db.execute("SELECT payload FROM project_deployment_plans WHERE id=?", (preview["confirmation_id"],)).fetchone()
        payload = json.loads(row["payload"])
        if remove:
            del payload["preview"][key]
        else:
            payload["preview"][key] = value
        db.execute("UPDATE project_deployment_plans SET payload=? WHERE id=?", (json.dumps(payload), preview["confirmation_id"]))
    with pytest.raises(TicketError) as error:
        c.service.start(c.folder, preview["confirmation_id"])
    assert error.value.status_code == 409
    assert not c.work
    c.factory.assert_not_called()


def test_consent_rejects_execution_version_changed_without_acknowledgement(context):
    c = context
    draft = c.service.plan(c.folder, "017", "dev", "stage", patch=True, aifactory_version="124")
    preview = c.service.prepare(c.folder, draft["id"], patch=True)
    with c.service.store._connect() as db:
        row = db.execute("SELECT payload FROM project_deployment_plans WHERE id=?", (preview["confirmation_id"],)).fetchone()
        payload = json.loads(row["payload"])
        payload["version"] = {"requested_version": "125", "branch": "release/v1.25", "resolved_ref": "b" * 40}
        payload["environment"].update(pd.release_version.environment(payload["version"]))
        db.execute("UPDATE project_deployment_plans SET payload=? WHERE id=?", (json.dumps(payload), preview["confirmation_id"]))
    with pytest.raises(TicketError) as error:
        c.service.start(c.folder, preview["confirmation_id"])
    assert error.value.status_code == 409
    assert not c.work
    c.factory.assert_not_called()


def test_raw_version_echo_binds_equivalent_dotted_input_without_client_parser(context):
    c = context
    draft = c.service.plan(c.folder, "017", "dev", "stage", patch=True, aifactory_version="1.25")
    preview = c.service.prepare(c.folder, draft["id"], patch=True)
    assert preview["deployment_contract"]["aifactory_version"] == "1.25"
    assert preview["deployment_contract"]["requested_version"] == "125"
    assert c.service.list(c.folder)["drafts"][0]["aifactory_version"] == "1.25"
    changed = c.service.prepare(c.folder, draft["id"], patch=True, aifactory_version="125")
    assert changed["deployment_contract"]["aifactory_version"] == "125"
    with pytest.raises(TicketError):
        c.service.start(c.folder, preview["confirmation_id"])


def test_literal_explicit_125_echoes_in_draft_preview_and_consent(context):
    c = context
    draft = c.service.plan(c.folder, "017", "dev", "stage", patch=True, aifactory_version="125")
    assert draft["aifactory_version"] == "125"
    result = c.service.prepare(c.folder, draft["id"], patch=True, aifactory_version="125")
    assert result["aifactory_version"] == "125"
    assert result["deployment_contract"]["aifactory_version"] == "125"
    assert result["requested_version"] == result["deployment_contract"]["requested_version"] == "125"
    assert result["can_execute"], result["blockers"]


def test_blocked_prepare_preserves_raw_echo_and_selection_without_claiming_ref(context):
    c = context
    draft = c.service.plan(c.folder, "017", "dev", "stage", patch=True, aifactory_version="1.25")
    c.service.select = Mock(side_effect=TicketError("Selected configuration is unavailable.", 409))
    preview = c.service.prepare(c.folder, draft["id"], patch=True)
    assert preview["can_execute"] is False
    assert preview["blockers"] == ["Selected configuration is unavailable."]
    assert preview["requested_version"] == "125" and preview["branch"] == "release/v1.25"
    assert preview["resolved_ref"] == ""
    ack = preview["deployment_contract"]
    assert ack["aifactory_version"] == "1.25"
    assert all(ack[key] == preview[key] for key in ("requested_version", "branch", "resolved_ref"))
    with pytest.raises(TicketError):
        c.service.start(c.folder, preview["confirmation_id"])


def test_prepare_explicit_environment_effects_no_execution(context):
    c = context
    _, preview = prepared(c)
    assert "AIFACTORY_TARGET_ENVIRONMENT=stage" in preview["command"]
    assert "AIFACTORY_PROJECT_NUMBER=017" in preview["command"]
    assert pd.SCRIPTS["gha"] in preview["command"]
    assert "git" in " ".join(preview["effects"]).lower()
    assert not c.work
    c.factory.assert_not_called()


@pytest.mark.parametrize("route", ["ado", "gha"])
@pytest.mark.parametrize("operation,source,target", [
    ("deploy", "dev", "stage"), ("deploy", "dev", "prod"),
    ("update", "dev", "dev"), ("update", "stage", "stage"), ("update", "prod", "prod"),
])
@pytest.mark.parametrize("patch", [False, True])
def test_deploy_and_update_exact_root_launcher_and_patch_worker(context, monkeypatch, route, operation, source, target, patch):
    c = context
    monkeypatch.setenv("AIFACTORY_PROJECT_ONLY", "true")
    c.chosen.update(route=route, script_path=str(c.root / pd.SCRIPTS[route]))
    if route == "ado":
        c.service._context.return_value = {"organization": "https://dev.azure.com/org", "project": "project", "repository": "consumer"}
    draft = c.service.plan(c.folder, "017", source, target, patch=patch, operation=operation)
    assert draft["operation"] == operation and draft["patch"] is patch
    c.service.observe.assert_called_once_with(c.folder, "017", source, target, False)
    preview = c.service.prepare(c.folder, draft["id"], patch=patch)
    assert preview["can_execute"], preview["blockers"]
    assert f"AIFACTORY_TARGET_ENVIRONMENT={target}" in preview["command"]
    assert ("--project-only" in preview["command"]) is (not patch)
    assert f"AIFACTORY_PROJECT_ONLY={'false' if patch else 'true'}" in preview["command"]
    assert pd.SCRIPTS[route] in preview["command"]
    assert f"Patch {'checked' if patch else 'unchecked'}" in preview["summary"]
    assert c.service.list(c.folder)["drafts"][0]["patch"] is patch
    c.service.start(c.folder, preview["confirmation_id"])
    c.work.pop()()
    argv = c.factory.call_args.args[0]
    environment = c.factory.call_args.kwargs["env"]
    assert argv[:4] == ["bash", "--noprofile", "--norc", pd.bash_path(c.root / pd.SCRIPTS[route])]
    assert Path(c.factory.call_args.kwargs["cwd"]) == Path(c.folder).parent
    assert ("--project-only" in argv) is (not patch)
    assert environment["AIFACTORY_PROJECT_ONLY"] == ("false" if patch else "true")
    assert environment["AIFACTORY_TARGET_ENVIRONMENT"] == target
    assert environment["AIFACTORY_PROJECT_NUMBER"] == "017"
    assert environment["AIFACTORY_PROJECT_CONFIG"] == pd.bash_path(c.chosen["config_path"])
    assert c.service.observe.call_args.args == (c.folder, "017", source, target, True)
    assert c.service.list(c.folder)["drafts"][0]["status"] == "submitted"


@pytest.mark.parametrize("operation,source,target", [
    ("update", "dev", "stage"), ("update", "stage", "prod"), ("update", "bad", "bad"),
    ("retry", "dev", "dev"), ("deploy", "prod", "prod"),
])
def test_invalid_update_pair_and_operation_never_persist(context, operation, source, target):
    with pytest.raises(TicketError):
        context.service.plan(context.folder, "017", source, target, operation=operation)
    assert not context.service.list(context.folder)["drafts"]
    context.factory.assert_not_called()


def test_pending_update_resumes_after_reload_and_patch_change_revokes_old_consent(context):
    c = context
    draft = c.service.plan(c.folder, "017", "stage", "stage", operation="update")
    original = c.service.prepare(c.folder, draft["id"], patch=False)
    changed = c.service.prepare(c.folder, draft["id"], patch=True)
    assert changed["can_execute"]
    c.service.prepare(c.folder, draft["id"], patch=False)
    with pytest.raises(TicketError, match="expired"):
        c.service.start(c.folder, original["confirmation_id"])
    with pytest.raises(TicketError, match="expired"):
        c.service.start(c.folder, changed["confirmation_id"])
    resumed = c.service.plan(c.folder, "017", "stage", "stage", patch=True, operation="update")
    assert resumed["id"] == draft["id"]
    assert resumed["patch"]
    restarted = pd.ProjectDeploymentService(c.service.store, identity=lambda: OWNER)
    assert restarted.list(c.folder)["drafts"] == [resumed]
    assert not c.work


def test_completed_updates_create_distinct_drafts_without_erasing_reconciled_failure(context):
    c = context
    first = c.service.plan(c.folder, "017", "dev", "dev", operation="update")
    preview = c.service.prepare(c.folder, first["id"])
    c.service.start(c.folder, preview["confirmation_id"])
    c.process.wait = lambda: 1
    c.work.pop()()
    failed = c.service.list(c.folder)["drafts"][0]
    assert c.service.plan(c.folder, "017", "dev", "dev", operation="update") == failed
    review = c.service.prepare_reconciliation(c.folder, failed["job_id"])
    acknowledged = c.service.reconcile(c.folder, review["confirmation_id"])
    assert acknowledged["status"] == "failed" and acknowledged["reconciled_at"]
    with pytest.raises(TicketError, match="cannot be retried"):
        c.service.prepare(c.folder, first["id"])
    second = c.service.plan(c.folder, "017", "dev", "dev", operation="update")
    assert second["id"] != first["id"]
    c.process.read.side_effect = [""]
    c.process.wait = lambda: 0
    c.service.start(c.folder, c.service.prepare(c.folder, second["id"])["confirmation_id"])
    c.work.pop()()
    third = c.service.plan(c.folder, "017", "dev", "dev", operation="update")
    assert len({first["id"], second["id"], third["id"]}) == 3
    drafts = c.service.list(c.folder)["drafts"]
    assert [draft["status"] for draft in drafts] == ["failed", "submitted", "draft"]
    assert drafts[0] == acknowledged
    assert c.service.start(c.folder, preview["confirmation_id"]) == acknowledged


def test_concurrent_update_planning_returns_single_pending_draft(context):
    c = context
    with ThreadPoolExecutor(max_workers=4) as pool:
        drafts = list(pool.map(lambda _: c.service.plan(c.folder, "017", "prod", "prod", operation="update"), range(4)))
    assert len({draft["id"] for draft in drafts}) == 1


@pytest.mark.parametrize("moment", ["start", "worker"])
def test_patch_choice_rechecked_against_persisted_draft(context, moment):
    c = context
    draft, preview = prepared(c)
    if moment == "worker":
        c.service.start(c.folder, preview["confirmation_id"])
    with c.service.store._connect() as db:
        row = db.execute("SELECT * FROM project_deployment_drafts WHERE id=?", (draft["id"],)).fetchone()
        c.service._update_row(db, row, row["status"], "changed test fixture", patch=True)
    if moment == "start":
        with pytest.raises(TicketError, match="patch"):
            c.service.start(c.folder, preview["confirmation_id"])
    else:
        c.work.pop()()
        assert c.service.list(c.folder)["drafts"][0]["status"] == "failed"
    c.factory.assert_not_called()


def test_legacy_database_migration_preserves_draft_receipts_and_reconciliation(tmp_path):
    folder = tmp_path / "consumer" / "aifactory"
    folder.mkdir(parents=True)
    store = operations.OperationsStore(tmp_path / "legacy.db")
    draft = {"id": "legacy", "project_number": "017", "source_environment": "dev",
             "target_environment": "stage", "status": "failed", "job_id": "job",
             "message": "Original failed outcome", "route": "ado", "script_path": "script",
             "created_at": "created", "updated_at": "updated", "reconciled_at": "reviewed"}
    with store._connect() as db:
        db.executescript("""
            CREATE TABLE project_deployment_drafts(
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, folder TEXT NOT NULL, project TEXT NOT NULL,
                source TEXT NOT NULL,target TEXT NOT NULL,status TEXT NOT NULL,job_id TEXT,payload TEXT NOT NULL,
                UNIQUE(owner,folder,project,source,target));
            CREATE TABLE project_deployment_plans(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,folder TEXT NOT NULL,draft_id TEXT NOT NULL,
                expires REAL NOT NULL,payload TEXT NOT NULL,job_id TEXT,
                FOREIGN KEY(draft_id) REFERENCES project_deployment_drafts(id));
            CREATE TABLE project_deployment_reconciliations(
                draft_id TEXT PRIMARY KEY,owner TEXT NOT NULL,folder TEXT NOT NULL,job_id TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,confirmation_id TEXT NOT NULL,
                FOREIGN KEY(draft_id) REFERENCES project_deployment_drafts(id));
        """)
        scope = pd._folder(str(folder))
        db.execute("INSERT INTO project_deployment_drafts VALUES(?,?,?,?,?,?,?,?,?)",
                   ("legacy", OWNER, scope, "017", "dev", "stage", "failed", "job", json.dumps(draft)))
        db.execute("INSERT INTO project_deployment_plans VALUES(?,?,?,?,?,?,?)",
                   ("consent", OWNER, scope, "legacy", 0, '{"kind":"deployment","argv":["bash","script"],"environment":{}}', "job"))
        db.execute("INSERT INTO project_deployment_reconciliations VALUES(?,?,?,?,?,?)",
                   ("legacy", OWNER, scope, "job", "reviewed", "reconcile-consent"))
    service = pd.ProjectDeploymentService(store, identity=lambda: OWNER)
    assert service.list(scope)["drafts"] == [{**draft, "operation": "deploy", "patch": True}]
    assert service.start(scope, "consent")["status"] == "failed"
    with store._connect() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("SELECT confirmed_at FROM project_deployment_reconciliations").fetchone()[0] == "reviewed"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM project_deployment_drafts WHERE id='legacy'")


@pytest.mark.skipif(os.name != "nt", reason="Current-user Windows DPAPI")
def test_derived_export_is_encrypted_in_consent_and_runtime_only(context, monkeypatch):
    c = context
    document = {"dev": {"project_number_000": "017"}, "stage_prod": {"project_number_000": "017",
                "servicePrincipalSecret": "synthetic-derived-secret-not-a-credential"}}
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    c.chosen["derived_config_hash"] = hashlib.sha256(canonical).hexdigest()
    c.chosen["config_path"] = ""
    monkeypatch.setattr(pd, "derived_document", lambda *args: copy.deepcopy(document))
    _, preview = prepared(c)
    assert ".dpapi" in preview["command"]
    assert "DPAPI" in " ".join(preview["effects"])
    assert not list(c.service.store.db_path.parent.rglob("*.dpapi"))
    assert b"synthetic-derived-secret" not in c.service.store.db_path.read_bytes()
    assert "synthetic-derived-secret" not in json.dumps(preview)
    original = c.factory.side_effect

    def spawn(*args, **kwargs):
        files = list(c.service.store.db_path.parent.rglob("*.dpapi"))
        assert len(files) == 1
        assert b"synthetic-derived-secret" not in files[0].read_bytes()
        return c.process

    c.factory.side_effect = spawn
    c.service.start(c.folder, preview["confirmation_id"])
    c.work.pop()()
    assert c.service.list(c.folder)["drafts"][0]["status"] == "submitted"
    assert not list(c.service.store.db_path.parent.rglob("*.dpapi"))
    c.factory.side_effect = original


def test_derived_config_changed_during_prepare_never_launches(context, monkeypatch):
    c = context
    c.chosen["derived_config_hash"] = "changed"
    c.chosen["config_path"] = ""
    monkeypatch.setattr(pd, "derived_document", lambda *args: {})
    draft = plan(c)
    preview = c.service.prepare(c.folder, draft["id"])
    assert not preview["can_execute"]
    assert "changed" in " ".join(preview["blockers"])
    c.factory.assert_not_called()


def test_ado_preview_uses_stage_and_bound_repository_context(context):
    c = context
    c.chosen.update(route="ado", script_path=str(c.root / pd.SCRIPTS["ado"]))
    c.service._context.return_value = {
        "organization": "https://dev.azure.com/organization", "project": "Bound Project", "repository": "consumer",
    }
    _, preview = prepared(c)
    assert pd.SCRIPTS["ado"] in preview["command"]
    assert "AIFACTORY_TARGET_ENVIRONMENT=stage" in preview["command"]
    assert "ADO_PROJECT='Bound Project'" in preview["command"]
    assert "ADO_AUTH_METHOD=aad" in preview["command"]


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_context_verifies_target_identity_and_origin(context, monkeypatch, route):
    c = context
    chosen = copy.deepcopy(c.chosen)
    chosen.update(route=route, github_repository="org/consumer")
    c.service.cli.accounts = lambda: [{"subscription_id": SUB, "tenant_id": TENANT}]
    c.service.cli.github = lambda: ("tester", {"repo"})
    monkeypatch.setattr(pd, "AzureTicketIdentity", lambda *args, **kwargs: lambda: OWNER)
    origin = ["https://github.com/org/consumer.git" if route == "gha" else "https://dev.azure.com/org/Project/_git/consumer"]

    def read(tool, args, **kwargs):
        if tool == "git":
            assert args[2:] == ["remote", "get-url", "origin"]
            return origin[0]
        if tool == "gh":
            return {"id": 123, "full_name": "org/consumer", "permissions": {"push": True}}
        assert args[:2] == ["repos", "show"]
        assert "--organization" in args and "--project" in args and "--repository" in args
        return {"id": "repository-id"}

    c.service.cli.read = read
    bound = pd.ProjectDeploymentService._context(c.service, chosen, OWNER)
    assert bound["origin"] == origin[0]
    assert bound["repository"] == ("org/consumer" if route == "gha" else "consumer")
    if route == "gha":
        chosen["github_repository"] = "different/destination"
    else:
        origin[0] = "https://password-as-user@dev.azure.com/org/Project/_git/consumer"
    with pytest.raises(TicketError):
        pd.ProjectDeploymentService._context(c.service, chosen, OWNER)


@pytest.mark.parametrize("change", ["hash", "route", "config", "owner", "target", "expired"])
def test_start_rechecks_immutable_consent(context, change):
    c = context
    _, preview = prepared(c)
    if change == "hash":
        c.chosen["hashes"]["script"] = "changed"
    elif change == "route":
        c.chosen["route"] = "ado"
    elif change == "config":
        c.chosen["config_path"] = "changed"
    elif change == "owner":
        c.state["owner"] = "different"
    elif change == "target":
        c.service.observe.side_effect = TicketError("Target exists", 409)
    else:
        c.clock[0] += 601
    with pytest.raises(TicketError):
        c.service.start(c.folder, preview["confirmation_id"])
    c.factory.assert_not_called()
    assert not c.work


def test_no_execution_without_confirmation_or_crossfolder(context):
    c = context
    _, preview = prepared(c)
    with pytest.raises(TicketError):
        c.service.start(c.folder, str(uuid4()))
    other = Path(c.folder).parent.parent / "other" / "aifactory"
    other.mkdir(parents=True)
    with pytest.raises(TicketError):
        c.service.start(str(other), preview["confirmation_id"])
    c.factory.assert_not_called()


def test_script_blockers_are_explicit_and_nonexecutable(context):
    c = context
    c.chosen["blockers"] = ["Installed script only deploys Dev."]
    draft = plan(c)
    preview = c.service.prepare(c.folder, draft["id"])
    assert not preview["can_execute"]
    assert "Dev" in preview["blockers"][0]
    with pytest.raises(TicketError):
        c.service.start(c.folder, preview["confirmation_id"])


def test_start_double_click_single_worker_and_repo_lock(context):
    c = context
    _, preview = prepared(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: c.service.start(c.folder, preview["confirmation_id"]), range(2)))
    assert results[0]["job_id"] == results[1]["job_id"]
    assert len(c.work) == 1
    other = c.service.plan(c.folder, "018", "dev", "stage")
    second = c.service.prepare(c.folder, other["id"])
    with pytest.raises(TicketError, match="active"):
        c.service.start(c.folder, second["confirmation_id"])


def test_success_is_submitted_raw_output_only_in_memory(context):
    c = context
    _, preview = prepared(c)
    draft = c.service.start(c.folder, preview["confirmation_id"])
    c.work.pop()()
    assert c.service.list(c.folder)["drafts"][0]["status"] == "submitted"
    assert c.service.start(c.folder, preview["confirmation_id"])["job_id"] == draft["job_id"]
    terminal = c.service.terminal(c.folder, draft["job_id"])
    assert "\x1b[32msecret-only-in-terminal" in terminal["output"]
    assert terminal["status"] == "submitted"
    c.process.close.assert_called_once()
    args, kwargs = c.factory.call_args
    assert args[0][1:3] == ["--noprofile", "--norc"]
    assert kwargs["env"]["TERM"] == "xterm-256color"
    assert "BASH_ENV" not in kwargs["env"]
    with c.service.store._connect() as db:
        for table in ("project_deployment_drafts", "project_deployment_plans"):
            assert all("secret-only-in-terminal" not in row[0] for row in db.execute(f"SELECT payload FROM {table}"))
    with pytest.raises(TicketError):
        c.service.input(c.folder, draft["job_id"], "unexpected\n")


def test_terminal_owner_binding_and_input_active_only(context):
    c = context
    _, preview = prepared(c)
    draft = c.service.start(c.folder, preview["confirmation_id"])
    job = draft["job_id"]
    session = c.service.terminals.get(job)
    with pytest.raises(TicketError):
        c.service.input(c.folder, job, "hello")
    c.service._update(draft["id"], "running", "running")
    session.update(pty=c.process, accepting=True)
    c.service.input(c.folder, job, "\x1b[A\x03")
    c.process.write.assert_called_once_with("\x1b[A\x03")
    c.service.resize(c.folder, job, 140, 40)
    c.process.resize.assert_called_once_with(140, 40)
    c.state["owner"] = "other"
    for action in (lambda: c.service.terminal(c.folder, job), lambda: c.service.input(c.folder, job, "a"),
                   lambda: c.service.resize(c.folder, job, 80, 24)):
        with pytest.raises(TicketError):
            action()


def test_restart_marks_running_interrupted_and_no_retry(context):
    c = context
    _, preview = prepared(c)
    job = c.service.start(c.folder, preview["confirmation_id"])
    pd._INITIALIZED.discard(str(c.service.store.db_path.resolve()))
    restarted = pd.ProjectDeploymentService(c.service.store, identity=lambda: OWNER)
    assert restarted.list(c.folder)["drafts"][0]["status"] == "interrupted"
    with pytest.raises(TicketError) as error:
        restarted.terminal(c.folder, job["job_id"])
    assert error.value.status_code == 410
    with pytest.raises(TicketError):
        restarted.prepare(c.folder, job["id"])


def test_failure_no_retry_and_shutdown_owned_only(context):
    c = context
    _, preview = prepared(c)
    draft = c.service.start(c.folder, preview["confirmation_id"])
    c.process.wait = lambda: 1
    c.work.pop()()
    assert c.service.list(c.folder)["drafts"][0]["status"] == "failed"
    with pytest.raises(TicketError):
        c.service.prepare(c.folder, draft["id"])
    other = c.service.plan(c.folder, "018", "dev", "stage")
    second = c.service.prepare(c.folder, other["id"])
    with pytest.raises(TicketError, match="unreconciled"):
        c.service.start(c.folder, second["confirmation_id"])
    c.service.shutdown()
    c.process.close.assert_called_once()


def test_failed_status_survives_partial_target_resource_group(context):
    c = context
    _, preview = prepared(c)
    draft = c.service.start(c.folder, preview["confirmation_id"])
    c.process.wait = lambda: 1
    c.work.pop()()
    c.service.observe.side_effect = TicketError("The target environment is already observed.", 409)
    assert c.service.list(c.folder)["drafts"][0]["status"] == "failed"
    assert c.service.terminal(c.folder, draft["job_id"])["status"] == "failed"
    assert c.service.start(c.folder, preview["confirmation_id"])["status"] == "failed"
    c.factory.assert_called_once()


def failed_job(c):
    _, preview = prepared(c)
    draft = c.service.start(c.folder, preview["confirmation_id"])
    c.process.wait = lambda: 1
    c.work.pop()()
    return draft, preview


def test_acknowledged_failed_promotion_allows_new_same_target_update_preserving_history(context):
    c = context
    failed, _ = failed_job(c)
    update = c.service.plan(c.folder, "017", "stage", "stage", operation="update")
    assert update["id"] != failed["id"]
    preview = c.service.prepare(c.folder, update["id"], patch=False)
    with pytest.raises(TicketError, match="unreconciled"):
        c.service.start(c.folder, preview["confirmation_id"])
    acknowledged = c.service.reconcile(
        c.folder, c.service.prepare_reconciliation(c.folder, failed["job_id"])["confirmation_id"])
    c.process.read.side_effect = [""]
    c.process.wait = lambda: 0
    c.service.start(c.folder, preview["confirmation_id"])
    c.work.pop()()
    drafts = c.service.list(c.folder)["drafts"]
    assert drafts[0] == acknowledged
    assert drafts[1]["status"] == "submitted" and drafts[1]["target_environment"] == "stage"
    assert plan(c) == acknowledged


def test_reviewed_reconciliation_releases_only_hold_without_retry(context):
    c = context
    failed, deployment_preview = failed_job(c)
    other = c.service.plan(c.folder, "018", "dev", "stage")
    next_preview = c.service.prepare(c.folder, other["id"])
    with pytest.raises(TicketError, match="unreconciled"):
        c.service.start(c.folder, next_preview["confirmation_id"])
    preview = c.service.prepare_reconciliation(c.folder, failed["job_id"])
    assert preview["can_execute"]
    assert "no command" in preview["command"]
    with pytest.raises(TicketError, match="cannot execute"):
        c.service.start(c.folder, preview["confirmation_id"])
    with pytest.raises(TicketError, match="cannot acknowledge"):
        c.service.reconcile(c.folder, deployment_preview["confirmation_id"])
    acknowledged = c.service.reconcile(c.folder, preview["confirmation_id"])
    assert acknowledged["status"] == "failed" and acknowledged["reconciled_at"]
    assert c.service.reconcile(c.folder, preview["confirmation_id"]) == acknowledged
    assert plan(c)["id"] == failed["id"]
    with pytest.raises(TicketError, match="cannot be retried"):
        c.service.prepare(c.folder, failed["id"])
    new_job = c.service.start(c.folder, next_preview["confirmation_id"])
    assert new_job["status"] == "queued" and new_job["job_id"] != failed["job_id"]
    restarted = pd.ProjectDeploymentService(c.service.store, identity=lambda: OWNER)
    assert next(item for item in restarted.list(c.folder)["drafts"] if item["id"] == failed["id"])["reconciled_at"]


def test_reconciliation_consent_is_owner_folder_expiry_and_outcome_bound(context):
    c = context
    failed, _ = failed_job(c)
    preview = c.service.prepare_reconciliation(c.folder, failed["job_id"])
    c.state["owner"] = "other"
    with pytest.raises(TicketError, match="not found"):
        c.service.reconcile(c.folder, preview["confirmation_id"])
    c.state["owner"] = OWNER
    different = c.root / "other" / "aifactory"
    different.mkdir(parents=True)
    with pytest.raises(TicketError, match="not found"):
        c.service.reconcile(str(different), preview["confirmation_id"])
    c.clock[0] += 601
    with pytest.raises(TicketError, match="expired"):
        c.service.reconcile(c.folder, preview["confirmation_id"])
    preview = c.service.prepare_reconciliation(c.folder, failed["job_id"])
    c.service._update(failed["id"], "failed", "Outcome changed during review")
    with pytest.raises(TicketError, match="changed"):
        c.service.reconcile(c.folder, preview["confirmation_id"])


def test_reconciliation_concurrent_confirmation_is_single_and_persistent(context):
    c = context
    failed, _ = failed_job(c)
    preview = c.service.prepare_reconciliation(c.folder, failed["job_id"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: c.service.reconcile(c.folder, preview["confirmation_id"]), range(4)))
    assert all(result == results[0] for result in results)
    with c.service.store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM project_deployment_reconciliations").fetchone()[0] == 1


def test_reconciliation_api_requires_auth_and_exposes_acknowledgement(context, monkeypatch):
    c = context
    failed, _ = failed_job(c)
    monkeypatch.setenv("AIFACTORY_API_KEY", "reconciliation-test")
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    route = "/api/v1/operations/project-deployments/reconcile"
    body = {"folder": c.folder, "job_id": failed["job_id"]}
    assert client.post(route + "/prepare", json=body).status_code in (401, 403)
    headers = {"X-API-Key": "reconciliation-test"}
    preview = client.post(route + "/prepare", json=body, headers=headers)
    assert preview.status_code == 200 and preview.json()["can_execute"]
    result = client.post(route, json={"folder": c.folder, "confirmation_id": preview.json()["confirmation_id"]}, headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "failed" and result.json()["reconciled_at"]


def test_reconciliation_rejects_active_or_unclosed_workers(context):
    c = context
    _, preview = prepared(c)
    queued = c.service.start(c.folder, preview["confirmation_id"])
    blocked = c.service.prepare_reconciliation(c.folder, queued["job_id"])
    assert not blocked["can_execute"]
    with pytest.raises(TicketError, match="blocked"):
        c.service.reconcile(c.folder, blocked["confirmation_id"])
    c.process.close.side_effect = OSError("secret=synthetic-private-cleanup-value")
    c.work.pop()()
    assert c.service.list(c.folder)["drafts"][0]["status"] == "interrupted"
    blocked = c.service.prepare_reconciliation(c.folder, queued["job_id"])
    assert any("terminal" in value for value in blocked["blockers"])
    terminal = c.service.terminal(c.folder, queued["job_id"])["output"]
    assert "cleanup failed" in terminal and "[redacted]" in terminal
    assert "synthetic-private-cleanup-value" not in terminal
    c.process.close.side_effect = None
    c.service.shutdown()


def test_shutdown_attempts_every_owned_terminal_and_reports_failures():
    sessions = TerminalSessions()
    first, second = sessions.create("one"), sessions.create("two")
    first["pty"] = SimpleNamespace(close=Mock(side_effect=OSError("synthetic-error")))
    second["pty"] = SimpleNamespace(close=Mock())
    with pytest.raises(RuntimeError, match="cleanup failed"):
        sessions.shutdown()
    first["pty"].close.assert_called_once()
    second["pty"].close.assert_called_once()
    assert "owned child cleanup failed" in first["buffer"].read(0)["output"]


@pytest.mark.skipif(os.name != "nt", reason="Windows-owned PTY cleanup")
def test_owned_pty_close_can_retry_failed_cleanup():
    process = OwnedPty.__new__(OwnedPty)
    process.lock = threading.RLock()
    process.closed = False
    process.job = SimpleNamespace(close=Mock())
    process.process = SimpleNamespace(close=Mock(side_effect=[OSError("synthetic-close-failure"), None]))
    with pytest.raises(OSError):
        process.close()
    assert not process.closed
    process.close()
    process.close()
    assert process.closed and process.process.close.call_count == 2


def test_worker_known_error_explains_failure_only_in_memory(context):
    c = context
    _, preview = prepared(c)
    queued = c.service.start(c.folder, preview["confirmation_id"])
    c.chosen["hashes"]["script"] = "changed"
    c.work.pop()()
    output = c.service.terminal(c.folder, queued["job_id"])["output"]
    assert "Saved configuration, scripts" in output and "changed" in output
    assert b"Saved configuration, scripts" not in c.service.store.db_path.read_bytes()
    c.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["dispatch", "worker", "cleanup"])
def test_unexpected_errors_record_failure_and_rethrow_without_private_details(context, stage):
    c = context
    _, preview = prepared(c)
    private = "synthetic-private-programming-error"
    if stage == "dispatch":
        c.service.dispatch = Mock(side_effect=TypeError(private))
        with pytest.raises(RuntimeError, match="Unexpected") as caught:
            c.service.start(c.folder, preview["confirmation_id"])
    else:
        c.service.start(c.folder, preview["confirmation_id"])
        if stage == "worker":
            c.factory.side_effect = TypeError(private)
        else:
            c.process.close.side_effect = TypeError(private)
        with pytest.raises(RuntimeError, match="Unexpected") as caught:
            c.work.pop()()
    assert private not in str(caught.value)
    draft = c.service.list(c.folder)["drafts"][0]
    assert draft["status"] in ("failed", "interrupted")
    assert private not in draft["message"]
    assert private in c.service.terminal(c.folder, draft["job_id"])["output"]
    assert private.encode() not in c.service.store.db_path.read_bytes()
    c.process.close.side_effect = None


def test_shutdown_queued_job_is_interrupted_without_starting(context):
    c = context
    _, preview = prepared(c)
    c.service.start(c.folder, preview["confirmation_id"])
    c.service.shutdown()
    assert c.service.list(c.folder)["drafts"][0]["status"] == "interrupted"
    c.work.pop()()
    c.factory.assert_not_called()


def test_terminal_lease_cache_changes_invalidate(context, monkeypatch):
    c = context
    root = c.root / "azure-cache"
    root.mkdir()
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(root))
    c.service._injected_identity = False
    identity = Mock(return_value=OWNER)
    c.service.identity = identity
    assert c.service._terminal_owner() == OWNER
    assert c.service._terminal_owner() == OWNER
    identity.assert_called_once()
    (root / "azureProfile.json").write_text("{}", encoding="utf-8")
    identity.return_value = "new-owner"
    assert c.service._terminal_owner() == "new-owner"
    assert identity.call_count == 2
    c.clock[0] += 6
    c.service._terminal_owner()
    assert identity.call_count == 3


def test_observation_stage_alias_scope_and_fresh_reads(context, monkeypatch):
    c = context
    local = {"subscriptions": {"dev": SUB, "stage": SUB}, "subscription_ids": [SUB], "monitoring_targets": []}
    monkeypatch.setattr(operations.LocalFactoryDiscovery, "discover", lambda *args: local)
    monkeypatch.setattr(operations.AzureInventoryProvider, "_is_relevant_group", lambda *args: True)
    groups = [{"name": "gh-esml-project017-eus2-dev-001", "subscriptionId": SUB}]
    c.service.store.save_snapshot(c.folder, "azure", {
        "configuration_scope": {"monitoring_targets": [], "subscriptions": [SUB]}, "resource_groups": groups,
    })
    c.service._observe(c.folder, "017", "dev", "stage", False)
    c.service.cli.read = Mock(return_value=groups)
    c.service._observe(c.folder, "017", "dev", "stage", True)
    assert c.service.cli.read.call_args[0][1][:2] == ["group", "list"]
    groups.append({"name": "gh-esml-project017-eus2-test-001", "subscriptionId": SUB})
    with pytest.raises(TicketError, match="already observed"):
        c.service._observe(c.folder, "017", "dev", "stage", True)


@pytest.mark.parametrize("target,alias", [("dev", "dev"), ("stage", "test"), ("prod", "prod")])
def test_update_observation_requires_exact_existing_target(context, monkeypatch, target, alias):
    c = context
    local = {"subscriptions": {environment: SUB for environment in ("dev", "stage", "prod")},
             "subscription_ids": [SUB], "monitoring_targets": []}
    monkeypatch.setattr(operations.LocalFactoryDiscovery, "discover", lambda *args: local)
    monkeypatch.setattr(operations.AzureInventoryProvider, "_is_relevant_group", lambda name, *_: name.startswith("gh-"))
    groups = [{"name": f"other-esml-project017-eus2-{alias}-001", "subscriptionId": SUB},
              {"name": f"gh-esml-project018-eus2-{alias}-001", "subscriptionId": SUB}]
    c.service.cli.read = Mock(return_value=groups)
    with pytest.raises(TicketError, match="not observed"):
        c.service._observe(c.folder, "017", target, target, True)
    groups.append({"name": f"gh-esml-project017-eus2-{alias}-001", "subscriptionId": SUB})
    c.service._observe(c.folder, "017", target, target, True)
    c.service.store.save_snapshot(c.folder, "azure", {
        "configuration_scope": {"monitoring_targets": [], "subscriptions": [SUB]}, "resource_groups": groups,
    })
    c.service._observe(c.folder, "017", target, target, False)


def test_buffer_bounds_cursor_reset_and_retention():
    buffer = TerminalBuffer(10)
    buffer.append("12345")
    assert buffer.read(0) == {"output": "12345", "next_cursor": 5, "reset": False}
    buffer.append("67890abc")
    assert buffer.text == "4567890abc"
    assert buffer.read(0)["reset"]
    assert buffer.read(10)["output"] == "abc"
    assert buffer.read(50)["reset"]
    sessions = TerminalSessions(retained=2, maximum=10)
    sessions.create("one")["complete"] = True
    sessions.create("two")
    sessions.create("three")
    assert sessions.get("one") is None


def test_terminal_output_pages_are_bounded_and_cursors_are_opaque():
    buffer = TerminalBuffer(maximum=200_000)
    text = "😀" * 150_000
    buffer.append(text)
    cursor, pages = 0, []
    while True:
        page = buffer.read(cursor)
        assert len(page["output"]) <= 65_536
        assert len(page["output"].encode("utf-8")) <= 65_536
        if not page["output"]:
            break
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
        pages.append(page["output"])
    assert "".join(pages) == text
    assert cursor == len(text)
    buffer.append("next" * 40_000)
    reset = buffer.read(0)
    assert reset["reset"]
    assert len(reset["output"]) <= 65_536
    assert reset["next_cursor"] < buffer.end
    assert not buffer.read(reset["next_cursor"])["reset"]


@pytest.mark.parametrize("route", ["ado", "gha"])
@pytest.mark.parametrize("patch", [False, True])
def test_api_auth_loopback_models_and_contract(context, monkeypatch, route, patch):
    c = context
    c.chosen.update(route=route, script_path=str(c.root / pd.SCRIPTS[route]))
    monkeypatch.setenv("AIFACTORY_API_KEY", "deployment-test")
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    # Avoid lifecycle shutdown since the replaced factory is intentionally not lru_cached.
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    path = "/api/v1/operations/project-deployments"
    body = {"folder": c.folder, "project_number": "017", "source_environment": "dev",
            "target_environment": "stage", "patch": patch}
    assert client.post(path + "/plan", json=body).status_code in (401, 403)
    headers = {"X-API-Key": "deployment-test"}
    assert client.post(path + "/plan", json={**body, "command": "arbitrary"}, headers=headers).status_code == 422
    rejected = client.post(path + "/terminal/input", json={"folder": c.folder, "job_id": str(uuid4()), "data": "private-secret", "extra": 1}, headers=headers)
    assert rejected.status_code == 422
    assert "private-secret" not in rejected.text
    result = client.post(path + "/plan", json=body, headers=headers)
    assert result.status_code == 200, result.text
    draft = result.json()
    assert draft["status"] == "draft" and draft["target_environment"] == "stage"
    assert draft["route"] == route and draft["patch"] is patch
    assert Path(draft["script_path"]) == c.root / pd.SCRIPTS[route]
    restarted = pd.ProjectDeploymentService(c.service.store, identity=lambda: OWNER, select=c.service.select)
    monkeypatch.setattr(api, "_project_deployment_service", lambda: restarted)
    assert client.get(path, params={"folder": c.folder}, headers=headers).json()["drafts"] == [draft]
    assert not c.work
    c.factory.assert_not_called()
    remote = TestClient(api.app, client=("203.0.113.5", 54321))
    assert remote.get(path, params={"folder": c.folder}, headers=headers).status_code == 403


def test_http_version_echo_ack_and_inherited_default_survive_api_models(context, monkeypatch):
    c = context
    c.chosen["installed_version"] = "125"
    monkeypatch.setenv("AIFACTORY_API_KEY", "deployment-test")
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    path = "/api/v1/operations/project-deployments"
    headers = {"X-API-Key": "deployment-test"}
    inherited = client.get(path, params={"folder": c.folder}, headers=headers)
    assert inherited.status_code == 200
    assert inherited.json()["requested_version"] == "125"
    assert inherited.json()["branch"] == "release/v1.25"
    assert inherited.json()["resolved_ref"] == "a" * 40
    result = client.post(path + "/plan", headers=headers, json={
        "folder": c.folder, "project_number": "017", "source_environment": "dev",
        "target_environment": "stage", "patch": True, "aifactory_version": "1.25",
    })
    assert result.status_code == 200, result.text
    draft = result.json()
    assert draft["aifactory_version"] == "1.25"
    assert draft["requested_version"] == "125"
    assert draft["deployment_contract"]["aifactory_version"] == "1.25"
    response = client.post(path + "/prepare", headers=headers, json={
        "folder": c.folder, "draft_id": draft["id"], "patch": True,
    })
    assert response.status_code == 200, response.text
    preview = response.json()
    ack = preview["deployment_contract"]
    assert preview["aifactory_version"] == ack["aifactory_version"] == "1.25"
    assert preview["resolved_ref"] == "a" * 40
    assert all(preview[key] == ack[key] for key in ("requested_version", "branch", "resolved_ref"))
    c.factory.assert_not_called()


def test_api_update_patch_models_are_strict_and_durable(context, monkeypatch):
    c = context
    monkeypatch.setenv("AIFACTORY_API_KEY", "deployment-test")
    monkeypatch.setattr(api, "_project_deployment_service", lambda: c.service)
    client = TestClient(api.app, client=("127.0.0.1", 54321))
    path = "/api/v1/operations/project-deployments"
    headers = {"X-API-Key": "deployment-test"}
    body = {"folder": c.folder, "project_number": "017", "source_environment": "prod",
            "target_environment": "prod", "operation": "update", "patch": True}
    for invalid in ({"patch": "false"}, {"patch": 1}, {"operation": "retry"}, {"target_environment": "stage"}):
        assert client.post(path + "/plan", json={**body, **invalid}, headers=headers).status_code == 422
    result = client.post(path + "/plan", json=body, headers=headers)
    assert result.status_code == 200, result.text
    draft = result.json()
    assert draft["operation"] == "update" and draft["patch"] is True
    assert draft["reconciled_at"] is None
    assert draft.get("aifactory_version") is None
    assert {"aifactory_version": None, **draft["deployment_contract"]} == pd.deployment_acknowledgement(draft)
    prepare = {"folder": c.folder, "draft_id": draft["id"], "patch": False}
    assert client.post(path + "/prepare", json={**prepare, "patch": "false"}, headers=headers).status_code == 422
    preview = client.post(path + "/prepare", json=prepare, headers=headers).json()
    assert preview["can_execute"] and "--project-only" in preview["command"]
    assert preview.get("aifactory_version") is None
    assert {"aifactory_version": None, **preview["deployment_contract"]} == pd.deployment_acknowledgement({
        **draft, **preview, "id": draft["id"], "operation": "update", "patch": False,
    })
    assert client.get(path, params={"folder": c.folder}, headers=headers).json()["drafts"][0]["patch"] is False
    assert not c.work


def test_pre_acknowledgement_consent_is_rejected_but_old_draft_can_prepare_safely(context):
    c = context
    draft, preview = prepared(c)
    with c.service.store._connect() as db:
        row = db.execute("SELECT payload FROM project_deployment_plans WHERE id=?", (preview["confirmation_id"],)).fetchone()
        payload = json.loads(row["payload"])
        payload["preview"].pop("deployment_contract")
        db.execute("UPDATE project_deployment_plans SET payload=? WHERE id=?", (json.dumps(payload), preview["confirmation_id"]))
    with pytest.raises(TicketError, match="acknowledgement"):
        c.service.start(c.folder, preview["confirmation_id"])
    current = c.service.prepare(c.folder, draft["id"], patch=False)
    assert current["deployment_contract"]["patch"] is False
    assert c.service.start(c.folder, current["confirmation_id"])["status"] == "queued"
    assert len(c.work) == 1
    c.factory.assert_not_called()


def test_checked_in_project_deployment_openapi_matches_runtime():
    contract = json.loads((Path(__file__).resolve().parents[1] / "docs" / "openapi.json").read_text(encoding="utf-8"))
    generated = api.app.openapi()
    for path, value in generated["paths"].items():
        if path.startswith("/api/v1/operations/project-deployments"):
            assert contract["paths"][path] == value
    for name, value in generated["components"]["schemas"].items():
        if name.startswith(("ProjectDeployment", "ProjectTerminal")):
            assert contract["components"]["schemas"][name] == value


def test_api_lifespan_closes_owned_jobs_even_on_error(monkeypatch):
    shutdown = Mock()
    monkeypatch.setattr(api, "_shutdown_project_deployments", shutdown)

    async def run():
        with pytest.raises(RuntimeError):
            async with api._api_lifespan(api.app):
                raise RuntimeError("synthetic lifecycle failure")

    asyncio.run(run())
    shutdown.assert_called_once()


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_real_selection_uses_configuration_not_both_script_files(tmp_path, monkeypatch, route):
    folder = tmp_path / "consumer" / "aifactory"
    project = folder / "config-wizard" / "project-017"
    project.mkdir(parents=True)
    (folder.parent / ".git").mkdir()
    state = copy.deepcopy(wizard.DEFAULT_STATE)
    subscriptions = {"dev": SUB, "stage": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                     "prod": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    state.update(orchestrator=route, project_number_000="017", dev_sub_id=subscriptions["dev"],
                 test_sub_id=subscriptions["stage"], prod_sub_id=subscriptions["prod"],
                 tenantId=TENANT, _save_folder=str(folder), admin_location="swedencentral",
                 admin_aifactoryPrefixRG="aif-", admin_aifactorySuffixRG="001")
    (project / "project_state.json").write_text(json.dumps(state), encoding="utf-8")
    (folder / "config-wizard" / "factory_state.json").write_text(json.dumps(state), encoding="utf-8")
    effective = wizard._load_project_state(str(project / "project_state.json"), str(folder))
    (project / "variables.json").write_text(json.dumps(wizard._render_variables_json(effective)), encoding="utf-8")
    for script in pd.SCRIPTS.values():
        (folder.parent / script).write_text("#!/usr/bin/env bash\nreadonly ENVIRONMENT=dev\n", encoding="utf-8")
    result = pd.selection(str(folder), "017", "stage")
    assert result["route"] == route
    assert Path(result["script_path"]).name == pd.SCRIPTS[route]
    assert any("Dev only" in blocker for blocker in result["blockers"])
    assert result["config_path"] == str(project / "variables.json")
    assert "project_state.json" in " ".join(result["hashes"])
    script = Path(result["script_path"])
    script.write_text(pd.CONTRACT + "\n# AIFACTORY_TARGET_ENVIRONMENT AIFACTORY_PROJECT_NUMBER AIFACTORY_PROJECT_CONFIG\n", encoding="utf-8")
    changed = pd.selection(str(folder), "017", "stage")
    assert changed["hashes"] != result["hashes"]
    assert not any("Dev only" in blocker for blocker in changed["blockers"])
    assert any("helper" in blocker for blocker in changed["blockers"])
    assert any("pipeline file" in blocker for blocker in changed["blockers"])
    assert any("patch choice" in blocker for blocker in changed["blockers"])
    script.write_text(script.read_text(encoding="utf-8") + "# --project-only AIFACTORY_PROJECT_ONLY\n# AIFACTORY_VERSION_CONTRACT=1\n", encoding="utf-8")
    helper = folder.parent / "lib" / "project_deployment.py"
    helper.parent.mkdir()
    helper.write_text(pd.CONTRACT + "\n# AIFACTORY_VERSION_CONTRACT=1\n# synthetic reviewed helper", encoding="utf-8")
    helper.with_name("release_version.py").write_text("# AIFACTORY_VERSION_CONTRACT=1", encoding="utf-8")
    helper.with_name("release_version.sh").write_text("# AIFACTORY_VERSION_CONTRACT=1", encoding="utf-8")
    terminal = folder.parent / "ui" / "terminal.sh"
    terminal.parent.mkdir()
    terminal.write_text("# synthetic terminal helper", encoding="utf-8")
    templates = (
        [folder.parent / ".github" / "workflows" / name for name in ("infra-project.yml", "infra-project-phase.yml")]
        if route == "gha" else [
            folder / "esml-infra/azure-devops/bicep/yaml/esml-infra-project" / name
            for name in ("infra-project-genai.yaml", "jobs/job-0-reviewed-project-config.yaml")
        ]
    )
    for path in templates:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pd.CONTRACT, encoding="utf-8")
    ready = pd.selection(str(folder), "017", "stage")
    assert not ready["blockers"]
    assert Path(ready["script_path"]) == folder.parent / pd.SCRIPTS[route]
    assert Path(ready["working_directory"]) == folder.parent
    if route == "gha":
        launcher_source = script.read_text(encoding="utf-8")
        implementation = folder.parent / pd.GITHUB_LEGACY_SCRIPT
        script.rename(implementation)
        missing = pd.selection(str(folder), "017", "stage")
        assert Path(missing["script_path"]) == script
        assert any("exact root script GHA-" in blocker for blocker in missing["blockers"])
        script.write_text(pd.GITHUB_ALIAS + '\nexec bash "$SCRIPT_DIR/GH-update-aifactory-and-run-project.sh" "$@"\n',
                          encoding="utf-8")
        alias = pd.selection(str(folder), "017", "stage")
        assert not alias["blockers"]
        assert Path(alias["script_path"]) == script
        assert str(implementation) in alias["hashes"]
        implementation.unlink()
        assert any("alias requires GH-" in blocker for blocker in pd.selection(str(folder), "017", "stage")["blockers"])
        script.write_text(launcher_source, encoding="utf-8")
    for target in ("dev", "stage", "prod"):
        selected = pd.selection(str(folder), "017", target)
        assert not selected["blockers"]
        assert selected["subscription_id"] == subscriptions[target]
        assert selected["tenant_id"] == TENANT
    helper.write_text(pd.CONTRACT + "\n# updated synthetic helper", encoding="utf-8")
    assert pd.selection(str(folder), "017", "stage")["hashes"] != ready["hashes"]
    (project / "variables.json").unlink()
    derived = pd.selection(str(folder), "017", "stage")
    assert derived["config_path"] == ""
    assert derived["derived_config_hash"]
    assert pd.derived_document(str(folder), "017")["dev"]["project_number_000"] == "017"
    assert not any("export" in blocker.lower() for blocker in derived["blockers"]) if os.name == "nt" else True
    if route == "ado":
        variables = folder / "esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
        variables.parent.mkdir(parents=True, exist_ok=True)
        variables.write_text("variables:\n  azureDevOpsTenantId: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\n", encoding="utf-8")
        assert any("cross-tenant" in blocker for blocker in pd.selection(str(folder), "017", "stage")["blockers"])
        variables.write_text("variables: [", encoding="utf-8")
        with pytest.raises(TicketError, match="malformed"):
            pd.selection(str(folder), "017", "stage")
        variables.unlink()
    state["_save_folder"] = str(tmp_path / "different" / "aifactory")
    (project / "project_state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(TicketError, match="different factory"):
        pd.selection(str(folder), "017", "stage")


@pytest.mark.parametrize("child", [False, True])
def test_real_conpty_interactive_fixture_only(child):
    tools = simple_mode.ReadOnlyCLI().tools()
    if not OwnedPty.available() or "bash" not in tools:
        pytest.skip("Platform PTY or Git Bash unavailable")
    script = Path(__file__).parent / "fixtures" / "interactive_deployment.sh"
    environment = simple_mode.launch_environment({"TERM": "xterm-256color", "SYNTHETIC_CHILD": "yes" if child else "no"}, tools)
    process = OwnedPty([tools["bash"], "--noprofile", "--norc", pd.bash_path(script.resolve())],
                       str(script.parent.resolve()), environment)
    output = []
    errors = []

    def read():
        answered_device_attributes = False
        try:
            while True:
                value = process.read()
                if not value:
                    break
                output.append(value)
                if not answered_device_attributes and "\x1b[c" in "".join(output):
                    process.write("\x1b[?1;2c")
                    answered_device_attributes = True
        except Exception as exc:
            errors.append(type(exc).__name__)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 20
        while "Synthetic input:" not in "".join(output) and time.monotonic() < deadline:
            time.sleep(.05)
        assert "Synthetic input:" in "".join(output), "".join(output)
        assert "\x1b[" in "".join(output)
        process.resize(100, 35)
        process.write("fixture-answer\r")
        while "Single key:" not in "".join(output) and time.monotonic() < deadline:
            time.sleep(.05)
        assert "Single key:" in "".join(output)
        process.write("Z")
        reader.join(timeout=10)
        assert not reader.is_alive()
        assert not errors
        assert "RECEIVED:fixture-answer" in "".join(output)
        assert "KEY:Z" in "".join(output)
        assert process.wait() == 0
    finally:
        process.close()
    assert not process.alive()
    if child:
        match = re.search(r"SYNTHETIC_CHILD_PID:(\d+)", "".join(output))
        assert match
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, False, int(match[1]))
            if handle:
                try:
                    code = ctypes.c_ulong()
                    assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                    assert code.value != 259, "Owned synthetic descendant survived terminal close"
                finally:
                    kernel.CloseHandle(handle)
