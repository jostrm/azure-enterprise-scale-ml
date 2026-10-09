from __future__ import annotations

import copy
import hashlib
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


def retention_policy():
    return {
        "mode": "preserve-reusable-infrastructure",
        "required_execution_contract": "ordered-project-pipelines-v1",
        "execution_scope": "whole-resource-groups",
        "selective_retention_supported": False,
        "limitations": ["Protected resources inside a deletable group block preparation."],
    }


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
            "retention_policy": retention_policy(),
            "stages": [project, common], "protected_resources": [HUB], "retained_resources": []}
    return rehash(plan)


def rehash(plan):
    unsigned = {key: value for key, value in plan.items() if key != "plan_hash"}
    encoded = (json.dumps(unsigned, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    plan["plan_hash"] = hashlib.sha256(encoded).hexdigest()
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
        "deletion_retention_policy": retention_policy(),
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
        rehash(plan)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()
    assert len(transport.records) == 1


@pytest.mark.parametrize("policy", ["local", "server"])
def test_protected_group_pattern_blocks_prepare(tmp_path, transport, monkeypatch, policy):
    if policy == "local":
        monkeypatch.setenv("AIFACTORY_PROTECTED_RESOURCE_GROUP_PATTERNS", '["*FACTORY*"]')
    else:
        transport.preview["deletion_plan"]["protected_resource_group_patterns"] = ["*FACTORY*"]
        rehash(transport.preview["deletion_plan"])
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_new_local_group_protection_blocks_existing_confirmation_receipt(tmp_path, transport, capsys, monkeypatch):
    make_receipt(tmp_path, transport, capsys)
    monkeypatch.setenv("AIFACTORY_PROTECTED_RESOURCE_GROUP_PATTERNS", '["*PROJECT*"]')
    assert confirm(tmp_path, "--yes", "--confirmation-phrase", PHRASE) == 2
    assert not transport.records


@pytest.mark.parametrize("value", ["not-json", '"*"', '[""]', '[null]', '["bad/pattern"]'])
def test_malformed_local_group_protection_fails_closed(tmp_path, transport, monkeypatch, value):
    monkeypatch.setenv("AIFACTORY_PROTECTED_RESOURCE_GROUP_PATTERNS", value)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize("defect", ["source", "group", "project-number", "run"])
def test_plan_execution_identities_match_review(tmp_path, transport, defect):
    plan = transport.preview["deletion_plan"]
    project = plan["stages"][0]
    if defect == "source":
        plan["source_commit"] = "e" * 40
    elif defect == "group":
        project["resource_group_id"] = HUB
    elif defect == "project-number":
        project["project_number"] = "999"
    else:
        project["run_id"] = "not-a-run-id"
    rehash(plan)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_stage_group_binding_respects_case_insensitive_arm_identity(tmp_path, transport):
    plan = transport.preview["deletion_plan"]
    plan["stages"][0]["resource_group_id"] = PROJECT_GROUP.upper()
    rehash(plan)
    assert prepare(tmp_path) == 0


@pytest.mark.parametrize("encoding", ["api", "compact", "missing-newline", "ascii", "four-spaces"])
def test_deletion_plan_hash_uses_only_api_catalog_storage_format(tmp_path, transport, encoding):
    p = transport.preview
    p["deletion_retention_policy"]["limitations"].append("Préserver l’infrastructure réutilisable.")
    plan = p["deletion_plan"]
    plan["retention_policy"] = copy.deepcopy(p["deletion_retention_policy"])
    rehash(plan)
    unsigned = {key: value for key, value in plan.items() if key != "plan_hash"}
    if encoding == "compact":
        plan["plan_hash"] = canonical_json_hash(unsigned)
    elif encoding != "api":
        encoded = json.dumps(unsigned, ensure_ascii=encoding == "ascii", sort_keys=True,
                             indent=4 if encoding == "four-spaces" else 2, allow_nan=False)
        if encoding != "missing-newline":
            encoded += "\n"
        plan["plan_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert prepare(tmp_path) == (0 if encoding == "api" else 2)
    assert (tmp_path / "receipt.json").exists() is (encoding == "api")
    assert len(transport.records) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_deletion_plan_hash_rejects_nonfinite_json_numbers(tmp_path, transport, value):
    transport.preview["deletion_plan"]["future_number"] = value
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


def test_retained_group_with_deleted_child_is_blocked_without_selective_runtime(tmp_path, transport):
    p = transport.preview
    p["deletion_targets"][0].update(delete=[RESOURCE], retain=[GROUP])
    p["retained_resources"] = [GROUP, HUB]
    p["inventory"] = [item for item in p["inventory"] if item["resource_id"] != GROUP]
    p["deletion_plan"]["stages"][1]["delete"] = [RESOURCE]
    rehash(p["deletion_plan"])
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize("change", [
    "absent", "null", "mode", "contract", "scope", "selective", "boolean",
    "limitations", "missing-plan", "mismatched-plan", "mismatched-contract",
    "plan-boolean",
])
def test_unproven_retention_policy_never_becomes_an_approval(tmp_path, transport, change):
    p = transport.preview
    policy = p["deletion_retention_policy"]
    if change == "absent":
        del p["deletion_retention_policy"]
    elif change == "null":
        p["deletion_retention_policy"] = None
    elif change == "mode":
        policy["mode"] = "delete-hub"
    elif change == "contract":
        policy["required_execution_contract"] = "unknown"
    elif change == "scope":
        policy["execution_scope"] = "individual-resources"
    elif change == "selective":
        policy["selective_retention_supported"] = True
    elif change == "boolean":
        policy["selective_retention_supported"] = 0
    elif change == "limitations":
        policy["limitations"] = []
    elif change == "missing-plan":
        del p["deletion_plan"]
    elif change == "mismatched-plan":
        p["deletion_plan"]["retention_policy"]["mode"] = "delete-hub"
    elif change == "plan-boolean":
        p["deletion_plan"]["retention_policy"]["selective_retention_supported"] = 0
        rehash(p["deletion_plan"])
    else:
        p["deletion_plan"]["contract"] = "unknown"
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()
    assert len(transport.records) == 1


def test_retention_limitations_are_rendered_and_receipt_bound(tmp_path, transport, capsys):
    assert prepare(tmp_path) == 0
    output = capsys.readouterr()
    assert "whole-resource-groups" in output.err
    assert "Protected resources inside" in output.err
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["preview"]["deletion_retention_policy"] == retention_policy()


def test_external_hub_retention_comes_from_frozen_plan(tmp_path, transport, capsys):
    hub = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/shared-hub"
    transport.preview["deletion_plan"]["protected_resources"] = [hub]
    transport.preview["retained_resources"] = [hub]
    rehash(transport.preview["deletion_plan"])
    assert prepare(tmp_path) == 0
    assert hub in capsys.readouterr().err


def test_external_retained_resource_is_bound_with_protected_resources(tmp_path, transport, capsys):
    retained = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/reusable-platform"
    transport.preview["deletion_plan"]["retained_resources"] = [retained]
    transport.preview["retained_resources"].append(retained)
    rehash(transport.preview["deletion_plan"])
    assert prepare(tmp_path) == 0
    assert retained in capsys.readouterr().err


@pytest.mark.parametrize("field", ["protected_resources", "retained_resources"])
def test_plan_retention_cannot_hide_under_a_deleted_group(tmp_path, transport, field):
    transport.preview["deletion_plan"][field] = [RESOURCE]
    transport.preview["retained_resources"] = [RESOURCE] if field == "protected_resources" else [HUB, RESOURCE]
    rehash(transport.preview["deletion_plan"])
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


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


VPN = GROUP + "/providers/Microsoft.Network/virtualNetworkGateways/vpngw-874678d6611d"
RUNNER = GROUP + "/providers/Microsoft.Compute/virtualMachines/runner-gha-sdc-dev-001"


def with_access_hub(transport, deleted=(VPN, RUNNER)):
    """aif-118 shape: the integrated hub and private runner live in the factory's own common group."""
    plan = transport.preview["deletion_plan"]
    common = plan["stages"][1]
    common["delete"] = [GROUP, RESOURCE, *deleted]
    transport.preview["deletion_targets"][0]["delete"] = list(common["delete"])
    transport.preview["inventory"] += [{"resource_id": item, "dependencies": []} for item in deleted]
    plan["access_hubs"] = [{
        "scale_set_id": SCALE, "environment": "dev", "contract": "factory-owned-access-hub-v1",
        "resource_group_ids": [GROUP.lower()], "proven_resource_ids": sorted(item.lower() for item in deleted),
        "deleted_resources": sorted(deleted, key=str.casefold),
        "evidence": {"contract": "consumed-bootstrap-stage-evidence-v1",
                     "workflow_id": "99999999-9999-4999-8999-999999999999", "record_hash": "e" * 64},
        "executor": "operator-after-project-barrier"}]
    return plan


def test_factory_owned_access_hub_is_reviewed_and_rendered(tmp_path, transport, capsys):
    rehash(with_access_hub(transport))
    assert prepare(tmp_path) == 0
    output = capsys.readouterr().err
    assert "Factory-owned access hub" in output and VPN in output
    assert "operator-after-project-barrier" in output


@pytest.mark.parametrize("defect", ["no-hub-section", "changed-deleted-list", "unknown-scale-set", "executor",
                                    "site-connection", "hub-on-project-stage"])
def test_unproven_or_changed_access_hub_is_rejected_before_confirmation(tmp_path, transport, defect):
    plan = with_access_hub(transport)
    if defect == "no-hub-section":
        plan.pop("access_hubs")
    elif defect == "changed-deleted-list":
        plan["access_hubs"][0]["deleted_resources"] = [VPN]
    elif defect == "unknown-scale-set":
        plan["access_hubs"][0]["scale_set_id"] = "88888888-8888-4888-8888-888888888888"
    elif defect == "executor":
        plan["access_hubs"][0]["executor"] = "self-hosted-runner"
    elif defect == "site-connection":
        connection = GROUP + "/providers/Microsoft.Network/connections/onprem"
        plan["stages"][1]["delete"].append(connection)
        transport.preview["deletion_targets"][0]["delete"].append(connection)
        transport.preview["inventory"].append({"resource_id": connection, "dependencies": []})
        plan["access_hubs"][0]["proven_resource_ids"] = sorted([*plan["access_hubs"][0]["proven_resource_ids"],
                                                                connection.lower()])
        plan["access_hubs"][0]["deleted_resources"] = sorted([*plan["access_hubs"][0]["deleted_resources"],
                                                              connection], key=str.casefold)
    elif defect == "hub-on-project-stage":
        plan["stages"][1]["delete"].remove(VPN)
        plan["stages"][0]["delete"].append(VPN)
        plan["access_hubs"][0]["deleted_resources"] = [RUNNER]
    rehash(plan)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


TEARDOWN = "bootstrap-operator-teardown-v1"
HUB_GROUP = "/subscriptions/abababab-abab-4bab-8bab-abababababab/resourceGroups/aifactory-connectivity"
SPOKE_VNET = GROUP + "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001"
HUB_DNS_LINK = (HUB_GROUP + "/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
                "/virtualNetworkLinks/aif-4d8896b66f23")
SPOKE_SIDE = SPOKE_VNET + "/virtualNetworkPeerings/aif-5eb3f21fdde8"
HUB_VNET_ID = HUB_GROUP + "/providers/Microsoft.Network/virtualNetworks/vnet-aifactory-access-hub-sdc-001"


def teardown_policy():
    return {**retention_policy(), "required_execution_contract": TEARDOWN,
            "limitations": ["Only this factory's own hub links are removed; the hub stays."]}


def with_teardown(transport):
    """dc-batman4 shape: a never-enrolled bootstrap draft, unlinked from the shared hub, then torn down."""
    preview = transport.preview
    deleted = [GROUP, RESOURCE, SPOKE_VNET, SPOKE_SIDE]
    identity = {"factory_id": FACTORY, "scale_set_id": SCALE, "environment": "dev",
                "subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "run_id": JOB}
    plan = {"contract": TEARDOWN, "factory_id": FACTORY, "source_commit": "b" * 40,
            "policy": "unlink-hub-then-whole-groups", "retention_policy": teardown_policy(), "executor": "operator",
            "stages": [
                {"id": "unlink:" + SCALE, "kind": "unlink-hub", **identity, "depends_on": [], "links": [
                    {"id": HUB_DNS_LINK, "side": "hub", "remote_virtual_network_id": SPOKE_VNET.lower()},
                    {"id": SPOKE_SIDE, "side": "factory", "remote_virtual_network_id": HUB_VNET_ID.lower()}]},
                {"id": "teardown:" + SCALE, "kind": "operator-teardown", **identity, "resource_group_ids": [GROUP],
                 "delete": sorted(deleted, key=str.casefold), "depends_on": ["unlink:" + SCALE]}],
            "protected_resources": [HUB_GROUP], "retained_resources": [], "access_hubs": [],
            "bootstrap_evidence": [{"scale_set_id": SCALE, "workflow_id": JOB, "record_hash": "e" * 64}]}
    preview["deletion_targets"] = [{**preview["deletion_targets"][0], "delete": sorted(deleted, key=str.casefold)}]
    preview["inventory"] = [{"resource_id": item, "dependencies": []} for item in deleted]
    preview["retained_resources"] = [HUB_GROUP]
    preview["deletion_retention_policy"] = teardown_policy()
    preview["target"]["projects"] = []
    preview["deletion_plan"] = plan
    return plan


def test_operator_teardown_plan_is_reviewed_and_rendered(tmp_path, transport, capsys):
    rehash(with_teardown(transport))
    assert prepare(tmp_path) == 0, capsys.readouterr().err
    output = capsys.readouterr().err
    assert "unlink-hub" in output and HUB_DNS_LINK in output and "operator" in output


@pytest.mark.parametrize("defect", ["hub-link-outside-hub", "factory-side-remote-foreign", "teardown-deletes-hub",
                                    "missing-unlink", "hash", "foreign-dns-link", "unknown-contract"])
def test_broadened_or_changed_operator_teardown_is_rejected(tmp_path, transport, defect):
    plan = with_teardown(transport)
    unlink, stage = plan["stages"]
    if defect == "hub-link-outside-hub":
        unlink["links"][0]["id"] = HUB_DNS_LINK.replace("aifactory-connectivity", "other-hub")
    elif defect == "factory-side-remote-foreign":
        unlink["links"][1]["remote_virtual_network_id"] = SPOKE_VNET.lower().replace("rg-factory-dev", "spider")
    elif defect == "teardown-deletes-hub":
        stage["delete"].append(HUB_GROUP)
    elif defect == "missing-unlink":
        plan["stages"] = [stage]
    elif defect == "foreign-dns-link":
        unlink["links"][0]["remote_virtual_network_id"] = "/subscriptions/x/resourcegroups/spider/providers/microsoft.network/virtualnetworks/v"
    elif defect == "unknown-contract":
        plan["contract"] = "raw-group-delete"
    if defect != "hash":
        rehash(plan)
    else:
        plan["retained_resources"] = [HUB_GROUP]
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_dns_resolver_is_connectivity_in_a_pipeline_plan(tmp_path, transport):
    resolver = GROUP + "/providers/Microsoft.Network/dnsResolvers/dnspr-874678d6611d"
    plan = with_access_hub(transport, deleted=(VPN, RUNNER))
    common = plan["stages"][1]
    common["delete"].append(resolver)
    transport.preview["deletion_targets"][0]["delete"].append(resolver)
    transport.preview["inventory"].append({"resource_id": resolver, "dependencies": []})
    rehash(plan)
    assert prepare(tmp_path) == 2


SHARED_HUB_LINKS = "shared-hub-spoke-links-v1"
HUB_PEERING = HUB_VNET_ID + "/virtualNetworkPeerings/aif-4d8896b66f23"
SPIDER_VNET = (f"/subscriptions/{SUBSCRIPTION}/resourceGroups/spider-esml-common-sdc-dev-001"
               "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")


def with_shared_hub_links(transport):
    """dc-batman4 shape: the common teardown deletes the spoke VNet, then its recorded hub links go."""
    plan = transport.preview["deletion_plan"]
    common = plan["stages"][1]
    common["delete"] = [GROUP, RESOURCE, SPOKE_VNET]
    transport.preview["deletion_targets"][0]["delete"] = list(common["delete"])
    transport.preview["inventory"].append({"resource_id": SPOKE_VNET, "dependencies": []})
    plan["shared_hub_links"] = [{
        "scale_set_id": SCALE, "environment": "dev", "contract": SHARED_HUB_LINKS,
        "executor": "operator-after-common-teardown", "hub_resource_group_ids": [HUB_GROUP.lower()],
        "links": [{"id": HUB_DNS_LINK, "type": "microsoft.network/privatednszones/virtualnetworklinks",
                   "remote_virtual_network_id": SPOKE_VNET.lower()},
                  {"id": HUB_PEERING, "type": "microsoft.network/virtualnetworks/virtualnetworkpeerings",
                   "remote_virtual_network_id": SPOKE_VNET.lower()}],
        "retained_links": [HUB_DNS_LINK.replace("aif-4d8896b66f23", "manual-batman")],
        "evidence": {"contract": "consumed-bootstrap-stage-evidence-v1",
                     "workflow_id": "99999999-9999-4999-8999-999999999999", "record_hash": "e" * 64}}]
    return plan


def test_shared_hub_link_cleanup_is_reviewed_and_rendered_last(tmp_path, transport, capsys):
    rehash(with_shared_hub_links(transport))
    assert prepare(tmp_path) == 0, capsys.readouterr().err
    output = capsys.readouterr().err
    assert "Shared connectivity hub links" in output and "operator-after-common-teardown" in output
    assert HUB_DNS_LINK in output and HUB_PEERING in output and "manual-batman" in output


@pytest.mark.parametrize("defect", ["link-outside-hub", "remote-not-deleted", "hub-group-deleted", "link-in-a-stage",
                                    "unknown-scale-set", "executor", "contract", "type-mismatch", "duplicate-link",
                                    "retained-outside-hub", "not-a-list"])
def test_broadened_or_changed_shared_hub_links_are_rejected(tmp_path, transport, defect):
    plan = with_shared_hub_links(transport)
    row = plan["shared_hub_links"][0]
    if defect == "link-outside-hub":
        row["links"][0]["id"] = HUB_DNS_LINK.replace("aifactory-connectivity", "other-hub")
    elif defect == "remote-not-deleted":
        row["links"][1]["remote_virtual_network_id"] = SPIDER_VNET.lower()
    elif defect == "hub-group-deleted":
        row["hub_resource_group_ids"] = [GROUP.lower()]
        row["links"][0]["id"] = GROUP + "/providers/Microsoft.Network/privateDnsZones/z/virtualNetworkLinks/l"
        row["links"].pop()
        row["retained_links"] = []
    elif defect == "link-in-a-stage":
        plan["stages"][1]["delete"].append(HUB_PEERING)
        transport.preview["deletion_targets"][0]["delete"].append(HUB_PEERING)
        transport.preview["inventory"].append({"resource_id": HUB_PEERING, "dependencies": []})
    elif defect == "unknown-scale-set":
        row["scale_set_id"] = "88888888-8888-4888-8888-888888888888"
    elif defect == "executor":
        row["executor"] = "operator-after-project-barrier"
    elif defect == "contract":
        row["contract"] = "unlink-everything-v1"
    elif defect == "type-mismatch":
        row["links"][0]["type"] = "microsoft.network/virtualnetworks/virtualnetworkpeerings"
    elif defect == "duplicate-link":
        row["links"].append(dict(row["links"][0]))
    elif defect == "retained-outside-hub":
        row["retained_links"] = [SPIDER_VNET]
    elif defect == "not-a-list":
        plan["shared_hub_links"] = row
    rehash(plan)
    assert prepare(tmp_path) == 2
    assert not (tmp_path / "receipt.json").exists()


def test_a_plan_without_shared_hub_links_still_reviews():
    from azurefactory.factory_deletion import describe_shared_hub_links
    assert describe_shared_hub_links({"contract": "ordered-project-pipelines-v1"}) == []
