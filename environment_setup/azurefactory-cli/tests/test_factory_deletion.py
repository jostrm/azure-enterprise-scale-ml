from __future__ import annotations

import copy
import io
import json
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from azurefactory.cli import build_parser, main
from azurefactory.client import canonical_json_hash


API_KEY = "private-api-key"
BASE = "http://127.0.0.1:8765"
ENDPOINT = "/api/v1/operations/delete-aifactory"
FOLDER = r"C:\consumer\azurefactory"
FACTORY = "11111111-1111-4111-8111-111111111111"
SCALE = "22222222-2222-4222-8222-222222222222"
SUBSCRIPTION = "33333333-3333-4333-8333-333333333333"
TENANT = "44444444-4444-4444-8444-444444444444"
CONFIRMATION = "55555555-5555-4555-8555-555555555555"
JOB = "66666666-6666-4666-8666-666666666666"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-factory-dev"
RESOURCE = GROUP + "/providers/Microsoft.Storage/storageAccounts/factorystore"
PHRASE = "DELETE ai-demo"


PROJECT_ID = "77777777-7777-4777-8777-777777777777"
PROJECT_GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-project001-dev"
HUB = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/aifactory-connectivity"
FLAGS = {"enableDeleteForDisabledResources": True, "deleteAllServicesForProject": True,
         "deleteKeyvaultAlso": True, "deleteAllForProject": True}
ORDER = ["foundry-capability-hosts", "target-project-search-shared-private-links",
         "service-managed-lifecycle", "project-resources", "project-network"]


def deletion_plan():
    identity = {"factory_id": FACTORY, "scale_set_id": SCALE, "environment": "dev",
                "subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "run_id": JOB}
    project = {"id": f"project:{SCALE}:{PROJECT_ID}", "kind": "project", **identity,
               "resource_group_id": PROJECT_GROUP, "delete": [PROJECT_GROUP], "depends_on": [],
               "project_id": PROJECT_ID, "project_number": "001",
               "pipeline": {"provider": "gha", "repository": "https://github.com/org/repo", "ref": "refs/heads/main",
                            "commit": "d" * 40, "definition": ".github/workflows/factory-lifecycle.yml",
                            "run_scope": "environment"},
               "inputs": dict(FLAGS), "lifecycle_order": list(ORDER)}
    common = {"id": f"common:{SCALE}:0123456789abcdef", "kind": "common", **identity,
              "resource_group_id": GROUP, "delete": [GROUP, RESOURCE], "depends_on": [project["id"]]}
    plan = {"contract": "ordered-project-pipelines-v1", "factory_id": FACTORY,
            "source_commit": "b" * 40, "policy": "all-projects-before-common",
            "stages": [project, common], "protected_resources": [HUB], "retained_resources": []}
    plan["plan_hash"] = canonical_json_hash(plan)
    return plan


def rehash(plan):
    plan.pop("plan_hash", None)
    plan["plan_hash"] = canonical_json_hash(plan)
    return plan


def preview():
    plan = deletion_plan()
    return {
        "contract_version": 1, "capabilities": ["delete-aifactory-v1"],
        "confirmation_id": CONFIRMATION, "can_execute": True, "blockers": [],
        "summary": "delete-factory: ai-demo", "effects": ["Delete only reviewed Azure resources."],
        "warnings": ["Entra groups, repositories and subscription metadata are retained; "
                     "local catalog configuration is removed after verified success."],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "source_revision": "a" * 64, "operation_mode": "runtime",
        "action": "delete-factory", "folder": FOLDER,
        "factory_id": FACTORY, "scale_set_id": None, "project_id": None,
        "target": {"id": FACTORY, "key": "ai-demo", "scale_sets": [
            {"id": SCALE, "environment": "dev", "subscription_id": SUBSCRIPTION, "tenant_id": TENANT},
        ], "projects": [{"id": PROJECT_ID, "number": "001",
                         "placements": [{"scale_set_id": SCALE, "environment": "dev"}]}]},
        "source_version": {"aifactory_version": "main", "requested_version": "main",
                           "branch": "main", "resolved_ref": "b" * 40},
        "inventory": [{"resource_id": item, "dependencies": []} for item in (PROJECT_GROUP, GROUP, RESOURCE)],
        "deletion_targets": [{
            "resource_group": "rg-factory-dev", "name": "rg-factory-dev", "resource_id": GROUP,
            "environment": "dev", "subscription_id": SUBSCRIPTION, "tenant_id": TENANT,
            "factory_id": FACTORY, "scale_set_id": SCALE, "project_id": None,
            "delete": [GROUP, RESOURCE], "retain": [],
        }, {
            "resource_group": "rg-project001-dev", "name": "rg-project001-dev", "resource_id": PROJECT_GROUP,
            "environment": "dev", "subscription_id": SUBSCRIPTION, "tenant_id": TENANT,
            "factory_id": FACTORY, "scale_set_id": SCALE, "project_id": None,
            "delete": [PROJECT_GROUP], "retain": [],
        }],
        "deletion_options": None, "deletion_scope": "whole-factory",
        "preserve_entra_groups": True, "retain_saved_configuration": False,
        "retained_resources": [HUB], "preview_hash": "c" * 64, "confirmation_phrase": PHRASE,
        "deletion_plan": plan,
    }


def job():
    return {"id": JOB, "action": "delete-factory", "factory_id": FACTORY,
            "scale_set_id": None, "project_id": None, "status": "queued", "message": "Queued."}


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(records=[], preview=preview(), job=job(), error=None, raw=None)

    class Response(io.BytesIO):
        def __init__(self, value):
            super().__init__(state.raw if state.raw is not None else json.dumps(value).encode())
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

    class Opener:
        def open(self, req, timeout):
            state.records.append({"url": req.full_url, "method": req.method,
                                  "body": json.loads(req.data) if req.data else None,
                                  "headers": dict(req.header_items())})
            if state.error:
                raise state.error
            if req.full_url.endswith("/prepare"):
                return Response(state.preview)
            if req.full_url.endswith("/confirm"):
                return Response({"contract_version": 1, "job": state.job, "catalog": None})
            return Response(state.job)

    def no_process(*args, **kwargs):
        pytest.fail("Factory deletion must not invoke any local process, az or gh.")

    monkeypatch.setattr("azurefactory.client.build_opener", lambda *args: Opener())
    monkeypatch.setattr("azurefactory.cli.sys.stdin", io.StringIO())
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    return state


def invoke(*args):
    return main(["--api-url", BASE, "--api-key", API_KEY, "delete-aifactory", *args])


def prepare(tmp_path, *args):
    return invoke("prepare", "--folder", FOLDER, "--factory-id", FACTORY,
                  "--expected-revision", "a" * 64, "--save-receipt", str(tmp_path / "receipt.json"), *args)


def confirm(tmp_path, *args):
    return invoke("confirm", "--receipt", str(tmp_path / "receipt.json"), *args)


def make_receipt(tmp_path, transport, capsys):
    assert prepare(tmp_path) == 0
    transport.records.clear()
    capsys.readouterr()


def test_prepare_saves_bound_review_and_never_confirms(tmp_path, transport, capsys):
    assert prepare(tmp_path, "--version-ref", "main") == 0
    assert len(transport.records) == 1
    record = transport.records[0]
    assert record["url"] == BASE + ENDPOINT + "/prepare"
    assert record["headers"]["X-api-key"] == API_KEY
    assert record["body"] == {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY,
                              "expected_revision": "a" * 64, "version_ref": "main"}
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["preview"]["preview_hash"] == "c" * 64
    assert receipt["preview_hash"] == canonical_json_hash(receipt["preview"])
    assert receipt["purpose"] == "delete-aifactory-confirm"
    output = capsys.readouterr()
    assert json.loads(output.out) == transport.preview
    assert "Are you sure" in output.err
    for value in (GROUP, RESOURCE, SUBSCRIPTION, TENANT):
        assert value in output.err
    assert "all-projects-before-common" in output.err
    assert "deleteAllForProject" in output.err and HUB in output.err
    assert ".github/workflows/factory-lifecycle.yml" in output.err


@pytest.mark.parametrize("defect", ["missing", "hash", "false-flag", "order", "common-first", "protected",
                                    "uncovered", "foreign-scale", "lifecycle"])
def test_unsafe_or_legacy_deletion_plan_is_rejected_before_confirmation(tmp_path, transport, capsys, defect):
    plan = transport.preview["deletion_plan"]
    project, common = plan["stages"]
    if defect == "missing":
        transport.preview.pop("deletion_plan")
    elif defect == "hash":
        plan["plan_hash"] = "0" * 64
    else:
        if defect == "false-flag":
            project["inputs"]["deleteKeyvaultAlso"] = False
        elif defect == "order":
            common["depends_on"] = []
        elif defect == "common-first":
            plan["stages"] = [common, project]
        elif defect == "protected":
            plan["protected_resources"].append(GROUP)
        elif defect == "uncovered":
            common["delete"] = [GROUP]
        elif defect == "foreign-scale":
            project["scale_set_id"] = "88888888-8888-4888-8888-888888888888"
        elif defect == "lifecycle":
            project["lifecycle_order"] = ORDER[::-1]
        plan.pop("plan_hash")
        plan["plan_hash"] = canonical_json_hash(plan)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()
    assert len(transport.records) == 1


def test_reconcile_uses_existing_job_only_and_never_dispatches(transport, capsys):
    transport.job["status"] = "succeeded"
    assert invoke("reconcile", "--folder", FOLDER, "--job-id", JOB) == 0
    assert len(transport.records) == 1
    assert transport.records[0]["url"] == BASE + ENDPOINT + "/reconcile"
    assert transport.records[0]["method"] == "POST"
    assert transport.records[0]["body"] == {"contract_version": 1, "folder": FOLDER, "job_id": JOB}
    assert json.loads(capsys.readouterr().out)["id"] == JOB


def test_nontty_exact_phrase_and_yes_sends_one_bound_confirmation(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 0
    assert len(transport.records) == 1
    assert transport.records[0]["url"] == BASE + ENDPOINT + "/confirm"
    assert transport.records[0]["body"] == {
        "contract_version": 1, "folder": FOLDER, "confirmation_id": CONFIRMATION,
        "preview_hash": "c" * 64, "confirmation_phrase": PHRASE,
    }
    assert json.loads(capsys.readouterr().out)["job"]["id"] == JOB


@pytest.mark.parametrize("flags", [
    (), ("--yes",), ("--confirmation-phrase", PHRASE),
    ("--yes", "--confirmation-phrase", "yes"),
    ("--yes", "--confirmation-phrase", PHRASE.lower()),
    ("--yes", "--confirmation-phrase", PHRASE + " "),
])
def test_nontty_missing_or_wrong_approval_never_sends(tmp_path, transport, capsys, flags):
    make_receipt(tmp_path, transport, capsys)
    assert confirm(tmp_path, *flags) == 2
    assert not transport.records


@pytest.mark.parametrize(("answers", "expected"), [
    (["no"], 3), ([""], 3), ([], 3), (["yes"], 3),
    (["yes", "yes"], 2), (["yes", PHRASE], 0),
])
def test_interactive_review_before_questions_and_eof_cancel(tmp_path, transport, capsys, monkeypatch, answers, expected):
    make_receipt(tmp_path, transport, capsys)
    monkeypatch.setattr("azurefactory.cli.sys.stdin", SimpleNamespace(isatty=lambda: True))
    responses = iter(answers)
    prompts = []

    def answer():
        output = capsys.readouterr()
        prompts.append(output.err)
        if len(prompts) == 1:
            assert "Are you sure" in output.err
            assert GROUP in output.err and SUBSCRIPTION in output.err and TENANT in output.err
            assert "preserved" in output.err and "retained" in output.err
            assert not transport.records
        else:
            assert "Type the exact confirmation phrase" in output.err
        try:
            return next(responses)
        except StopIteration:
            raise EOFError()

    monkeypatch.setattr("builtins.input", answer)
    assert confirm(tmp_path, "--yes") == expected
    assert len(transport.records) == (1 if expected == 0 else 0)


@pytest.mark.parametrize(("field", "value"), [
    ("contract_version", True), ("capabilities", []), ("operation_mode", "configuration"),
    ("action", "delete-project"), ("action", None), ("folder", r"C:\another-factory"),
    ("folder", None),
    ("factory_id", SCALE), ("scale_set_id", SCALE), ("project_id", JOB),
    ("deletion_options", {}), ("source_revision", "d" * 64),
    ("confirmation_id", "not-a-uuid"), ("preview_hash", ""),
    ("preview_hash", "x" * 64), ("deletion_scope", "scale-set"),
    ("preserve_entra_groups", False), ("preserve_entra_groups", "true"),
    ("retain_saved_configuration", None), ("retain_saved_configuration", "false"),
    ("retain_saved_configuration", True), ("retain_saved_configuration", 0),
    ("confirmation_phrase", "yes"),
    ("confirmation_phrase", "DELETE another-factory"), ("target", None),
    ("source_version", {}), ("effects", None), ("warnings", None),
    ("retained_resources", [RESOURCE]), ("deletion_targets", []), ("inventory", []),
])
def test_unsafe_preview_never_saves_approvable_receipt(tmp_path, transport, field, value):
    transport.preview[field] = value
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()
    assert len(transport.records) == 1


@pytest.mark.parametrize("field", [
    "factory_id", "scale_set_id", "subscription_id", "tenant_id", "project_id",
    "environment", "name", "resource_group", "resource_id",
])
def test_changed_target_scope_fails_closed(tmp_path, transport, field):
    transport.preview["deletion_targets"][0][field] = JOB
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize("change", [
    "empty-delete", "outside-group", "subscription", "duplicate-target", "duplicate-resource",
    "overlap", "retained-under-deleted-group", "missing-scale", "extra-inventory", "duplicate-inventory",
    "duplicate-scale", "missing-retained-manifest",
])
def test_incomplete_or_broadened_manifest_fails_closed(tmp_path, transport, change):
    p = transport.preview
    target = p["deletion_targets"][0]
    if change == "empty-delete":
        target["delete"] = []
    elif change == "outside-group":
        target["delete"].append(GROUP + "-other/providers/Microsoft.Storage/storageAccounts/other")
    elif change == "subscription":
        target["delete"] = [f"/subscriptions/{SUBSCRIPTION}"]
    elif change == "duplicate-target":
        p["deletion_targets"].append(copy.deepcopy(target))
    elif change == "duplicate-resource":
        target["delete"].append(RESOURCE.upper())
    elif change == "overlap":
        target["retain"] = [RESOURCE]
        p["retained_resources"] = [RESOURCE]
    elif change == "retained-under-deleted-group":
        target["delete"].remove(RESOURCE)
        target["retain"] = [RESOURCE]
        p["retained_resources"] = [RESOURCE]
    elif change == "missing-scale":
        p["target"]["scale_sets"].append({**p["target"]["scale_sets"][0], "id": JOB})
    elif change == "extra-inventory":
        p["inventory"].append({"resource_id": GROUP + "-other"})
    elif change == "duplicate-inventory":
        p["inventory"].append(copy.deepcopy(p["inventory"][0]))
    elif change == "duplicate-scale":
        p["target"]["scale_sets"].append(copy.deepcopy(p["target"]["scale_sets"][0]))
    else:
        target["delete"] = [RESOURCE]
        target["retain"] = [GROUP]
        p["inventory"] = [p["inventory"][1]]
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_retained_group_with_deleted_child_is_rendered_and_bound(tmp_path, transport, capsys):
    p = transport.preview
    p["deletion_targets"][0].update(delete=[RESOURCE], retain=[GROUP])
    p["retained_resources"] = [GROUP, HUB]
    p["inventory"] = [item for item in p["inventory"] if item["resource_id"] != GROUP]
    p["deletion_plan"]["stages"][1]["delete"] = [RESOURCE]
    rehash(p["deletion_plan"])
    assert prepare(tmp_path) == 0
    assert '"retain": [' in capsys.readouterr().err


def test_saved_configuration_handling_is_backend_sourced(tmp_path, transport, capsys):
    transport.preview["retain_saved_configuration"] = False
    assert prepare(tmp_path) == 0
    output = capsys.readouterr()
    assert "REMOVED after verified success; retained on failure" in output.err
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["preview"]["retain_saved_configuration"] is False


def test_whole_factory_includes_multiple_environments_and_tenants(tmp_path, transport, capsys):
    p = transport.preview
    other_subscription = "77777777-7777-4777-8777-777777777777"
    other_tenant = "88888888-8888-4888-8888-888888888888"
    other_group = f"/subscriptions/{other_subscription}/resourceGroups/rg-factory-prod"
    p["target"]["scale_sets"].append({
        "id": JOB, "environment": "prod", "subscription_id": other_subscription, "tenant_id": other_tenant,
    })
    p["deletion_targets"].append({
        **p["deletion_targets"][0], "scale_set_id": JOB, "environment": "prod",
        "subscription_id": other_subscription, "tenant_id": other_tenant,
        "name": "rg-factory-prod", "resource_group": "rg-factory-prod",
        "resource_id": other_group, "delete": [other_group],
    })
    p["inventory"].append({"resource_id": other_group, "dependencies": []})
    plan = p["deletion_plan"]
    plan["stages"].append({**plan["stages"][1], "id": f"common:{JOB}:fedcba9876543210", "scale_set_id": JOB,
                           "environment": "prod", "subscription_id": other_subscription, "tenant_id": other_tenant,
                           "resource_group_id": other_group, "delete": [other_group]})
    rehash(plan)
    assert prepare(tmp_path) == 0
    output = capsys.readouterr()
    for value in (SUBSCRIPTION, TENANT, other_subscription, other_tenant, "prod", other_group):
        assert value in output.err
    transport.records.clear()
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 0
    assert len(transport.records) == 1


@pytest.mark.parametrize(("flag", "value"), [
    ("--factory-id", ""), ("--factory-id", "0" * 32), ("--factory-id", "invalid"),
    ("--folder", ""), ("--expected-revision", "latest"), ("--expected-revision", "A" * 64),
    ("--version-ref", ""),
])
def test_invalid_request_never_reaches_api(tmp_path, transport, flag, value):
    assert prepare(tmp_path, flag, value) == 2
    assert not transport.records


@pytest.mark.parametrize("change", [
    "invalid-json", "not-object", "missing-preview", "preview-hash", "request-hash", "server-hash",
    "purpose", "operation", "api-url", "expired", "missing-file",
])
def test_invalid_receipt_never_calls_api(tmp_path, transport, capsys, change):
    make_receipt(tmp_path, transport, capsys)
    path = tmp_path / "receipt.json"
    receipt = json.loads(path.read_text())
    if change == "invalid-json":
        path.write_text("{invalid")
    elif change == "not-object":
        path.write_text("[]")
    elif change == "missing-file":
        path.unlink()
    else:
        if change == "missing-preview":
            del receipt["preview"]
        elif change == "preview-hash":
            receipt["preview"]["target"]["key"] = "changed"
        elif change == "request-hash":
            receipt["request"]["factory_id"] = JOB
        elif change == "server-hash":
            receipt["preview"]["preview_hash"] = ""
            receipt["preview_hash"] = canonical_json_hash(receipt["preview"])
        elif change == "purpose":
            receipt["purpose"] = "catalog-confirm"
        elif change == "operation":
            receipt["operation"] = "runtime-deploy"
        elif change == "api-url":
            receipt["base_url"] = "http://localhost:9999"
        else:
            receipt["expires_at"] = receipt["preview"]["expires_at"] = "2020-01-01T00:00:00Z"
            receipt["preview_hash"] = canonical_json_hash(receipt["preview"])
        path.write_text(json.dumps(receipt))
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) in (2, 3)
    assert not transport.records


@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 422, 500])
@pytest.mark.parametrize("action", ["prepare", "confirm"])
def test_http_errors_never_fallback_or_retry(tmp_path, transport, capsys, status, action):
    if action == "confirm":
        make_receipt(tmp_path, transport, capsys)
    transport.error = HTTPError(BASE + ENDPOINT + "/" + action, status, "failed", {},
                                io.BytesIO(json.dumps({"detail": API_KEY}).encode()))
    code = prepare(tmp_path) if action == "prepare" else confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE)
    assert code != 0
    assert len(transport.records) == 1
    output = capsys.readouterr()
    assert API_KEY not in output.out + output.err
    if status in (404, 405):
        assert "no catalog or legacy fallback" in output.err


def test_timeout_confirmation_is_unknown_and_never_retried(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    transport.error = TimeoutError()
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 4
    assert len(transport.records) == 1
    assert "outcome is unknown" in capsys.readouterr().err


def test_private_key_never_printed_or_persisted(tmp_path, transport, capsys):
    transport.preview["warnings"].append("Diagnostic: " + API_KEY)
    transport.preview["private_api_key"] = API_KEY
    assert prepare(tmp_path) == 0
    output = capsys.readouterr()
    assert API_KEY not in output.out + output.err + (tmp_path / "receipt.json").read_text()
    transport.job["message"] = API_KEY
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 0
    output = capsys.readouterr()
    assert API_KEY not in output.out + output.err


def test_private_key_in_receipt_error_is_redacted(tmp_path, transport, capsys):
    make_receipt(tmp_path, transport, capsys)
    path = tmp_path / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["expires_at"] = receipt["preview"]["expires_at"] = API_KEY
    receipt["preview_hash"] = canonical_json_hash(receipt["preview"])
    path.write_text(json.dumps(receipt))
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 2
    assert not transport.records
    output = capsys.readouterr()
    assert API_KEY not in output.out + output.err


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed", "interrupted", "unknown"])
def test_status_is_read_only_and_reports_failures(transport, capsys, status):
    transport.job["status"] = status
    expected = 0 if status in ("queued", "running", "succeeded") else 5
    assert invoke("status", "--folder", FOLDER, "--job-id", JOB) == expected
    assert len(transport.records) == 1
    assert transport.records[0]["method"] == "GET"
    assert transport.records[0]["url"].startswith(BASE + ENDPOINT + "/status?")


@pytest.mark.parametrize(("field", "value"), [
    ("action", "deploy"), ("factory_id", SCALE), ("scale_set_id", SCALE), ("project_id", JOB),
    ("status", "unknown"), ("id", ""),
])
def test_confirmation_rejects_wrong_job_without_retry(tmp_path, transport, capsys, field, value):
    make_receipt(tmp_path, transport, capsys)
    transport.job[field] = value
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 5
    assert len(transport.records) == 1


def test_existing_receipt_prevents_prepare_call(tmp_path, transport):
    (tmp_path / "receipt.json").write_text("existing")
    assert prepare(tmp_path) == 2
    assert not transport.records


def test_blocked_preview_is_not_saved(tmp_path, transport, capsys):
    transport.preview.update(can_execute=False, blockers=["Ownership is unknown."])
    assert prepare(tmp_path) == 3
    assert json.loads(capsys.readouterr().out)["can_execute"] is False
    assert not (tmp_path / "receipt.json").exists()


def test_command_help_uses_plain_language():
    parser = build_parser()
    command = parser._subparsers._group_actions[0].choices["delete-aifactory"]
    help_text = " ".join(command.format_help().split())
    assert "runtime" not in help_text.lower()
    assert ("Deletes Azure resources and removes the saved factory only after confirmed success; "
            "Entra security groups and Git history are kept.") in help_text
    for child in command._subparsers._group_actions[0].choices.values():
        assert "runtime" not in child.format_help().lower()
