import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from azurefactory import enrollment
from azurefactory.cli import main
from azurefactory.client import AzureFactoryClient


ROOT = Path(__file__).resolve().parents[3]
BASH = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
IDS = {name: str(uuid5(NAMESPACE_URL, "https://example.invalid/enrollment/" + name))
       for name in ("factory", "scale", "tenant", "subscription", "role", "client", "principal")}
SCOPE = f"/subscriptions/{IDS['subscription']}/resourcegroups/owned"
CORE = enrollment.core()
ACK = "--acknowledge-exclusive-writer-governance"


@pytest.fixture(autouse=True)
def no_cloud(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Cloud/provider calls are forbidden in integration tests.")
    monkeypatch.setattr(CORE, "Cloud", fail)


@pytest.fixture
def selected(tmp_path, monkeypatch):
    consumer = tmp_path / "consumer"
    (consumer / "azurefactory").mkdir(parents=True)
    document = {"schema_version": 2, "bindings": {}, "factories": [
        {"id": IDS["factory"], "kind": "ai", "prefix": "example-ai", "region": "swedencentral", "scale_sets": [
            {"id": IDS["scale"], "environment": "stage", "suffix": "002", "tenant_id": IDS["tenant"],
             "subscription_id": IDS["subscription"], "orchestrator": "gha"}]}]}
    register = consumer / "azurefactory" / "register.json"
    register.write_bytes(CORE.canonical(document))
    options = {
        "repository": "https://github.com/example/consumer", "ref": "refs/heads/main", "shared_remote": False,
        "writer_id": "example-stage", "auth_namespace": "example-stage",
        "runner": {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"},
        "resource_group_ids": [SCOPE], "common_dependency_ids": [], "public_network_access": "Disabled",
        "deployment_roles": [{"scope": SCOPE, "role_definition_id": IDS["role"]}],
    }
    options_file = tmp_path / "options.json"
    options_file.write_bytes(CORE.canonical(options))
    flags = ["--consumer-root", str(consumer), "--factory-id", IDS["factory"], "--scale-set-id", IDS["scale"],
             "--environment", "stage", "--options", str(options_file)]
    calls = []

    def plan(request, *, acknowledge_exclusive_writer_governance=False):
        calls.append(("plan", request))
        return CORE._review(request, {"blockers": [], "actions": [], "identity": None},
                            acknowledge_exclusive_writer_governance)

    def ensure(request, expected, *, yes, acknowledge_exclusive_writer_governance=False):
        calls.append(("ensure", request, expected, yes, acknowledge_exclusive_writer_governance))
        assert expected == plan(request, acknowledge_exclusive_writer_governance=acknowledge_exclusive_writer_governance)["plan_hash"]
        identity = {"id": request["identity_id"], "tenant_id": IDS["tenant"],
                    "client_id": IDS["client"], "principal_id": IDS["principal"]}
        return {"status": "unchanged", "changed": False, "enrollment_complete": True,
                "publication_required": True, "runtime_ready": False, "identity": identity,
                "binding_candidate": CORE.binding_candidate(request, identity, {"revision": 1})}
    monkeypatch.setattr(CORE, "plan", plan)
    monkeypatch.setattr(CORE, "ensure", ensure)
    return SimpleNamespace(consumer=consumer, register=register, options_file=options_file, options=options,
                           flags=flags, calls=calls, folder=tmp_path)


def save_plan(selected, capsys):
    path = selected.folder / "plan.json"
    assert main(["enrollment", "plan", *selected.flags, ACK, "--save-plan", str(path)]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["acknowledge_exclusive_writer_governance"] is True
    return path


def save_result(selected, capsys):
    plan = save_plan(selected, capsys)
    result = selected.folder / "result.json"
    assert main(["enrollment", "ensure", "--plan", str(plan), "--yes", ACK, "--save-result", str(result)]) == 0
    capsys.readouterr()
    return result


def test_plan_ensure_offline_api_free_and_scope_bound(selected, capsys):
    plan = save_plan(selected, capsys)
    artifact = json.loads(plan.read_text())
    assert artifact["reference_hash"] == artifact["request"]["consumer_hash"]
    assert artifact["consumer_root"] == str(selected.consumer.resolve())
    assert artifact["request_hash"] == artifact["review"]["scope_hash"]
    assert "configurations" not in artifact["request"]
    assert main(["enrollment", "ensure", "--plan", str(plan), "--yes", ACK]) == 0
    call = next(item for item in selected.calls if item[0] == "ensure")
    assert call[2] == artifact["review"]["plan_hash"] and call[3:] == (True, True)
    assert json.loads(capsys.readouterr().out)["runtime_ready"] is False


@pytest.mark.parametrize("extra", [[], ["--yes"], ["--yes", ACK, "--environment", "prod"],
                                  ["--yes", ACK, "--expected-orchestrator", "ado"],
                                  ["--yes", ACK, "--expected-plan", "f" * 64]])
def test_ensure_rejects_missing_consent_or_inconsistent_flags(selected, capsys, extra):
    path = save_plan(selected, capsys)
    assert main(["enrollment", "ensure", "--plan", str(path), *extra]) == 2
    assert not any(call[0] == "ensure" for call in selected.calls)


@pytest.mark.parametrize("change", ["digest", "reference", "scope", "review", "unknown", "secret", "source"])
def test_review_integrity_and_source_changes_block_ensure(selected, capsys, change):
    path = save_plan(selected, capsys)
    artifact = json.loads(path.read_text())
    if change == "digest":
        artifact["artifact_hash"] = "f" * 64
    elif change == "reference":
        artifact["reference_hash"] = "f" * 64
    elif change == "scope":
        artifact["request"]["target"]["environment"] = "prod"
    elif change == "review":
        artifact["review"]["actions"].append("unreviewed-action")
    elif change == "unknown":
        artifact["unrecognized"] = True
    elif change == "secret":
        artifact["token"] = "must-never-be-printed"
    else:
        document = json.loads(selected.register.read_text())
        document["generation"] = "concurrently-changed"
        selected.register.write_bytes(CORE.canonical(document))
    path.write_bytes(CORE.canonical(artifact))
    assert main(["enrollment", "ensure", "--plan", str(path), "--yes", ACK]) in (2, 3)
    assert not any(call[0] == "ensure" for call in selected.calls)
    assert "must-never-be-printed" not in capsys.readouterr().err


@pytest.mark.parametrize("raw", ['{"access_token":"must-never-be-printed"}', '{"unknown":true}',
                               '{"value":NaN}', '{"value":Infinity}', '{"x":1,"x":2}'])
def test_core_rejects_unsafe_options_before_plan(selected, capsys, raw):
    selected.options_file.write_text(raw)
    assert main(["enrollment", "plan", *selected.flags]) == 2
    assert selected.calls == []
    output = capsys.readouterr()
    assert "must-never-be-printed" not in output.out + output.err


def test_acknowledgment_is_not_automatic_and_artifacts_are_not_overwritten(selected, capsys):
    path = selected.folder / "plan.json"
    assert main(["enrollment", "plan", *selected.flags, "--save-plan", str(path)]) == 3
    assert json.loads(capsys.readouterr().out)["acknowledge_exclusive_writer_governance"] is False
    before = path.read_bytes()
    selected.calls.clear()
    assert main(["enrollment", "plan", *selected.flags, "--save-plan", str(path)]) == 2
    assert selected.calls == [] and path.read_bytes() == before


def test_direct_hash_ensure_supported_without_api(selected, capsys):
    assert main(["enrollment", "plan", *selected.flags, ACK]) == 0
    review = json.loads(capsys.readouterr().out)
    assert main(["enrollment", "ensure", *selected.flags, ACK, "--expected-plan", review["plan_hash"], "--yes"]) == 0


def test_partial_failure_uses_failure_code_and_preserves_result(selected, capsys, monkeypatch):
    plan = save_plan(selected, capsys)
    result = selected.folder / "partial.json"
    monkeypatch.setattr(CORE, "ensure", lambda *a, **kw: {
        "status": "blocked", "enrollment_complete": False, "changed": True, "reconciliation_required": True,
        "binding_candidate": None, "error": "final-verification-failed"})
    assert main(["enrollment", "ensure", "--plan", str(plan), ACK, "--yes", "--save-result", str(result)]) == 5
    assert json.loads(result.read_text())["result"]["reconciliation_required"] is True


def test_result_path_errors_block_before_ensure_or_report_reconciliation_after(selected, capsys, monkeypatch):
    plan = save_plan(selected, capsys)
    result = selected.folder / "missing" / "result.json"
    assert main(["enrollment", "ensure", "--plan", str(plan), ACK, "--yes", "--save-result", str(result)]) == 2
    assert not any(call[0] == "ensure" for call in selected.calls)

    def fail(*args):
        raise OSError("must-never-be-printed")
    monkeypatch.setattr(enrollment, "write_document", fail)
    assert main(["enrollment", "ensure", "--plan", str(plan), ACK, "--yes",
                 "--save-result", str(selected.folder / "result.json")]) == 5
    output = capsys.readouterr().err
    assert "resources may have changed" in output and "must-never-be-printed" not in output


def test_binding_exact_api_receipt_then_separate_confirm(selected, capsys, monkeypatch):
    from azurefactory import cli
    result = save_result(selected, capsys)
    calls = []
    client = AzureFactoryClient()

    def prepare(body):
        calls.append(("prepare", copy.deepcopy(body)))
        return {"contract_version": 1, "confirmation_id": IDS["factory"], "expires_at": "2099-01-01T00:00:00Z",
                "can_execute": True, "blockers": [], "operation_mode": "configuration",
                "source_revision": body["expected_revision"], "binding": body["binding"],
                "target": {"id": body["factory_id"]}}

    def confirm(folder, confirmation_id):
        calls.append(("confirm", folder, confirmation_id))
        return {"contract_version": 1, "catalog": {}, "job": None}

    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", lambda self, body: prepare(body))
    monkeypatch.setattr(AzureFactoryClient, "catalog_confirm", lambda self, folder, ident: confirm(folder, ident))
    monkeypatch.setattr(cli, "client", lambda args: client)
    receipt = selected.folder / "binding.receipt.json"
    assert main(["enrollment", "prepare-binding", "--result", str(result), "--expected-revision", "a" * 64,
                 "--save-receipt", str(receipt)]) == 0
    assert [call[0] for call in calls] == ["prepare"]
    assert calls[0][1]["action"] == "configure-binding"
    assert calls[0][1]["folder"] == str(selected.consumer / "azurefactory")
    assert json.loads(receipt.read_text())["request"]["binding"] == json.loads(result.read_text())["result"]["binding_candidate"]
    assert main(["enrollment", "publish", "--receipt", str(receipt)]) == 2
    assert main(["enrollment", "publish", "--receipt", str(receipt), "--yes"]) == 0
    assert [call[0] for call in calls] == ["prepare", "confirm"]
    assert main(["catalog", "confirm", "--receipt", str(receipt), "--yes"]) == 0
    assert json.loads(selected.register.read_text())["bindings"] == {}


def test_candidate_scope_tampering_even_with_recomputed_digest_is_rejected(selected, capsys):
    result = save_result(selected, capsys)
    artifact = json.loads(result.read_text())
    artifact["result"]["binding_candidate"]["targets"][0]["resource_group_ids"] = [SCOPE + "-other"]
    artifact = enrollment.seal({k: v for k, v in artifact.items() if k != "artifact_hash"})
    result.write_bytes(CORE.canonical(artifact))
    assert main(["enrollment", "prepare-binding", "--result", str(result), "--expected-revision", "a" * 64,
                 "--save-receipt", str(selected.folder / "receipt.json")]) == 2
    assert not (selected.folder / "receipt.json").exists()


@pytest.mark.parametrize("mutation", ["binding", "factory", "revision"])
def test_binding_preview_must_acknowledge_exact_candidate(selected, capsys, monkeypatch, mutation):
    result = save_result(selected, capsys)
    calls = []

    def prepare(self, body):
        calls.append(body)
        preview = {"contract_version": 1, "confirmation_id": IDS["factory"],
                   "expires_at": "2099-01-01T00:00:00Z", "can_execute": True, "blockers": [],
                   "operation_mode": "configuration", "source_revision": body["expected_revision"],
                   "binding": copy.deepcopy(body["binding"]), "target": {"id": body["factory_id"]}}
        if mutation == "binding":
            preview["binding"]["writer_id"] = "different-writer"
        elif mutation == "factory":
            preview["target"]["id"] = IDS["scale"]
        else:
            preview["source_revision"] = "f" * 64
        return preview
    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", prepare)
    receipt = selected.folder / "receipt.json"
    assert main(["enrollment", "prepare-binding", "--result", str(result), "--expected-revision", "a" * 64,
                 "--save-receipt", str(receipt)]) == 2
    assert len(calls) == 1 and not receipt.exists()


def test_core_error_content_never_leaks(selected, capsys, monkeypatch):
    def fail(*args, **kwargs):
        raise CORE.EnrollmentError("secret-response-body: must-never-be-printed")
    monkeypatch.setattr(CORE, "plan", fail)
    assert main(["enrollment", "plan", *selected.flags]) == 2
    output = capsys.readouterr()
    assert "must-never-be-printed" not in output.out + output.err


@pytest.mark.skipif(not BASH.is_file(), reason="Git Bash is unavailable")
@pytest.mark.parametrize("provider", ["ADO", "GHA"])
@pytest.mark.parametrize("suffix", ["azurefactory.sh", "create-new-aifactory-scaleset.sh"])
def test_all_four_wrappers_help_dispatch_before_registered_guard(selected, provider, suffix):
    wrapper = ROOT / "bootstrap" / (provider + "-" + suffix)
    result = subprocess.run([str(BASH), str(wrapper), "enroll", "ensure", "--help"], cwd=selected.consumer,
                            env=dict(os.environ, AIFACTORY_PYTHON=sys.executable), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--expected-plan" in result.stdout and "--consumer-root" in result.stdout


@pytest.mark.skipif(not BASH.is_file(), reason="Git Bash is unavailable")
@pytest.mark.parametrize("suffix", ["azurefactory.sh", "create-new-aifactory-scaleset.sh"])
@pytest.mark.parametrize("override", [[], ["--provider", "gha"], ["--expected-orchestrator", "gha"]])
def test_ado_wrapper_cannot_enroll_gha_or_override_provider(selected, suffix, override):
    before = selected.register.read_bytes()
    result = subprocess.run([str(BASH), str(ROOT / "bootstrap" / ("ADO-" + suffix)), "enroll", "plan",
                             *selected.flags, *override], cwd=selected.consumer,
                            env=dict(os.environ, AIFACTORY_PYTHON=sys.executable), capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    if not override:
        assert json.loads(result.stdout)["error"] == "orchestrator-mismatch"
    assert before == selected.register.read_bytes()


def test_bundle_and_copy_rules_include_all_helpers():
    router = (ROOT / "bootstrap" / "lib" / "layout_router.sh").read_text()
    ignore = (ROOT / "bootstrap" / ".gitignore.template").read_text()
    assert "\n!/lib/\n" in ignore and '"!/lib/"' in router
    for name in ("factory_enrollment.py", "factory_enrollment_entry.py", "github_environments.py", "project_environment.py", "runner-prerequisites.ps1",
                 "runner-prerequisites.sh", "runner-registration.ps1", "runner-registration.sh",
                 "runner_bootstrap.py", "runner-only-registration.sh"):
        assert "\n  " + name + "\n" in router
        assert '"!/lib/' + name + '"' in router
        assert "\n!/lib/" + name + "\n" in ignore
    copier = (ROOT / "bootstrap" / "01-aif-copy-aifactory-templates.sh").read_text()
    assert '"azurefactory-cli/setup.py"' in copier


@pytest.fixture
def convenience(selected, monkeypatch):
    selected.options.pop("public_network_access")
    selected.options_file.write_bytes(CORE.canonical(selected.options))
    document = json.loads(selected.register.read_text())
    document["configurations"] = {IDS["factory"]: {"factory": {"coordination_mode": "single-writer"}}}
    selected.register.write_bytes(CORE.canonical(document))
    selected.artifacts = selected.folder / "run"
    selected.combined = ["enrollment", "plan-and-publish", *selected.flags,
                         "--artifact-dir", str(selected.artifacts)]
    selected.api_calls = []

    def listing(self, folder):
        selected.api_calls.append("list")
        return {"contract_version": 1, "mode": "catalog", "revision": "a" * 64, "factories": []}

    def prepare(self, body):
        selected.api_calls.append("prepare")
        assert (selected.artifacts / "result.json").is_file()
        return {"contract_version": 1, "confirmation_id": IDS["factory"],
                "expires_at": "2099-01-01T00:00:00Z", "can_execute": True, "blockers": [],
                "operation_mode": "configuration", "source_revision": body["expected_revision"],
                "binding": body["binding"], "target": {"id": body["factory_id"]}}

    def confirm(self, folder, confirmation):
        selected.api_calls.append("confirm")
        assert (selected.artifacts / "publication-intent.json").is_file()
        return {"contract_version": 1, "catalog": {}, "job": None}

    monkeypatch.setattr(AzureFactoryClient, "catalog_list", listing)
    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", prepare)
    monkeypatch.setattr(AzureFactoryClient, "catalog_confirm", confirm)
    return selected


def test_plan_and_publish_one_consent_exact_scope_and_offline_cost(convenience, capsys):
    before = convenience.register.read_bytes()
    assert main([*convenience.combined, ACK, "--yes"]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["published"] is True and result["runtime_ready"] is False
    assert convenience.api_calls == ["list", "prepare", "confirm"]
    plan = json.loads((convenience.artifacts / "plan.json").read_text())
    request = plan["request"]
    assert request["coordination_mode"] == "single-writer"
    assert request["create_resource_group_ids"] == [SCOPE]
    assert request["approved_group_creation_scope"] == "/subscriptions/" + IDS["subscription"]
    assert request["deployment_roles"][0]["scope"] == SCOPE
    assert "account_id" not in request
    cost = json.loads((convenience.artifacts / "cost-preview.json").read_text())
    assert cost["status"] == "unpriced" and cost["estimated_total"] is None
    assert cost["region"] == "swedencentral"
    assert cost["services"][1]["enabled"] is False and cost["services"][1]["sku"] is None
    assert output.err.index("cost_preview") < output.err.index("enrollment_plan")
    assert before == convenience.register.read_bytes()
    assert json.loads((convenience.artifacts / "outcome.json").read_text())["published"] is True


@pytest.mark.parametrize("flags, status", [([ACK], "approval-required"), (["--yes"], "blocked")])
def test_wrapper_never_invents_approval_or_governance(convenience, capsys, flags, status):
    assert main([*convenience.combined, *flags]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert convenience.api_calls == []
    assert not any(call[0] == "ensure" for call in convenience.calls)
    assert (convenience.artifacts / "plan.json").exists()


def test_wrapper_cost_and_intent_are_saved_before_mutation(convenience, monkeypatch):
    original = CORE.ensure

    def check(*args, **kwargs):
        assert (convenience.artifacts / "cost-preview.json").is_file()
        assert (convenience.artifacts / "plan.json").is_file()
        assert (convenience.artifacts / "ensure-intent.json").is_file()
        return original(*args, **kwargs)
    monkeypatch.setattr(CORE, "ensure", check)
    assert main([*convenience.combined, ACK, "--yes"]) == 0


@pytest.mark.parametrize("explicit", [{"coordination_mode": "blob"}, {"public_network_access": "Disabled"}])
def test_wrapper_preserves_explicit_blob_options(convenience, capsys, explicit):
    document = json.loads(convenience.register.read_text())
    document["configurations"][IDS["factory"]]["factory"] = {"coordination_mode": "blob"}
    convenience.register.write_bytes(CORE.canonical(document))
    convenience.options_file.write_bytes(CORE.canonical(convenience.options | explicit))
    assert main([*convenience.combined, ACK]) == 3
    capsys.readouterr()
    request = json.loads((convenience.artifacts / "plan.json").read_text())["request"]
    assert request["options"]["coordination_mode"] == "blob"
    assert request["create_resource_group_ids"] == [SCOPE]
    assert request["account_id"].split("/providers/")[0] not in request["create_resource_group_ids"]
    cost = json.loads((convenience.artifacts / "cost-preview.json").read_text())
    assert cost["services"][1]["enabled"] is True and cost["services"][1]["sku"] == "Standard_LRS"


def test_wrapper_preserves_existing_blob_binding_without_mode_option(convenience):
    request = CORE.load_request(convenience.consumer, IDS["factory"], IDS["scale"], "stage",
                                convenience.options | {"public_network_access": "Disabled"})
    identity = {"id": request["identity_id"], "principal_id": IDS["principal"], "client_id": IDS["client"],
                "tenant_id": IDS["tenant"]}
    binding = CORE.binding_candidate(request, identity, {"revision": 1})
    doc = json.loads(convenience.register.read_text())
    doc["bindings"] = {IDS["factory"]: {"gha": binding}}
    doc["configurations"][IDS["factory"]]["factory"] = {"coordination_mode": "blob"}
    convenience.register.write_bytes(CORE.canonical(doc))
    assert main([*convenience.combined, ACK]) == 3
    request = json.loads((convenience.artifacts / "plan.json").read_text())["request"]
    assert request["options"]["coordination_mode"] == "blob"


@pytest.mark.parametrize("reuse", [True, False])
def test_auto_creation_excludes_dependencies_and_reused_identity_groups(convenience, reuse):
    dependency, identity_group = SCOPE + "-shared", SCOPE + "-identity"
    extra = {"common_dependency_ids": [dependency]}
    if reuse:
        extra["identity_id"] = identity_group + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/reused"
    else:
        extra["identity_resource_group_id"] = identity_group
    convenience.options_file.write_bytes(CORE.canonical(convenience.options | extra))
    assert main([*convenience.combined, ACK]) == 3
    request = json.loads((convenience.artifacts / "plan.json").read_text())["request"]
    assert request["create_resource_group_ids"] == ([SCOPE] if reuse else [SCOPE, identity_group])
    assert dependency not in request["create_resource_group_ids"]


def test_auto_creation_never_turns_shared_identity_dependency_into_owned_group(convenience):
    dependency = SCOPE + "-shared"
    convenience.options_file.write_bytes(CORE.canonical(convenience.options | {
        "common_dependency_ids": [dependency], "identity_resource_group_id": dependency}))
    assert main([*convenience.combined, ACK]) == 3
    request = json.loads((convenience.artifacts / "plan.json").read_text())["request"]
    assert request["create_resource_group_ids"] == [SCOPE]


@pytest.mark.parametrize("settings", [{}, {"coordination_mode": "blob"}, {"coordination_mode": "invalid"}])
def test_wrapper_rejects_saved_coordination_mismatch_before_cloud(convenience, settings):
    document = json.loads(convenience.register.read_text())
    document["configurations"][IDS["factory"]]["factory"] = settings
    convenience.register.write_bytes(CORE.canonical(document))
    assert main([*convenience.combined, ACK, "--yes"]) in (2, 3)
    assert convenience.calls == [] and convenience.api_calls == []
    assert not convenience.artifacts.exists()


def test_wrapper_rejects_register_drift_between_convenience_and_plan(convenience, monkeypatch):
    original = enrollment.plan

    def changed(args):
        document = json.loads(convenience.register.read_text())
        document["configurations"][IDS["factory"]]["factory"]["coordination_mode"] = "blob"
        convenience.register.write_bytes(CORE.canonical(document))
        return original(args)

    monkeypatch.setattr(enrollment, "plan", changed)
    assert main([*convenience.combined, ACK, "--yes"]) == 3
    assert not any(call[0] == "ensure" for call in convenience.calls)
    assert convenience.api_calls == []


@pytest.mark.parametrize("other_factory", [False, True])
@pytest.mark.parametrize("identity_only", [False, True])
@pytest.mark.parametrize("explicit_creation", [False, True])
def test_wrapper_rejects_unbound_registered_group_ownership(
        convenience, other_factory, identity_only, explicit_creation):
    document = json.loads(convenience.register.read_text())
    group = SCOPE + "-identity" if identity_only else SCOPE
    owner = copy.deepcopy(document["factories"][0])
    owner["scale_sets"][0]["id"] = str(uuid5(NAMESPACE_URL, "other-scale"))
    # Inventory can contain a nested resource rather than an RG.
    owner["scale_sets"][0]["owned_resource_ids"] = [
        group.replace("/resourcegroups/", "/resourceGroups/") + "/providers/Microsoft.Network/virtualNetworks/owned"]
    if other_factory:
        owner["id"] = str(uuid5(NAMESPACE_URL, "other-factory"))
        document["factories"].append(owner)
    else:
        document["factories"][0]["scale_sets"].extend(owner["scale_sets"])
    convenience.register.write_bytes(CORE.canonical(document))
    options = {**convenience.options}
    if identity_only:
        options["identity_resource_group_id"] = group
    if explicit_creation:
        options.update(create_resource_group_ids=[group],
                       approved_group_creation_scope="/subscriptions/" + IDS["subscription"])
    convenience.options_file.write_bytes(CORE.canonical(options))
    assert main([*convenience.combined, ACK, "--yes"]) == 3
    assert convenience.calls == [] and convenience.api_calls == []


def test_wrapper_respects_explicit_empty_creation_and_rejects_broad_roles(convenience):
    convenience.options_file.write_bytes(CORE.canonical(convenience.options | {"create_resource_group_ids": []}))
    assert main([*convenience.combined, ACK]) == 3
    request = json.loads((convenience.artifacts / "plan.json").read_text())["request"]
    assert request["create_resource_group_ids"] == []
    assert request["approved_group_creation_scope"] is None
    convenience.options_file.write_bytes(CORE.canonical(convenience.options | {
        "deployment_roles": [{"scope": "/subscriptions/" + IDS["subscription"], "role_definition_id": IDS["role"]}]}))
    flags = [*convenience.combined[:-1], str(convenience.folder / "invalid"), ACK, "--yes"]
    assert main(flags) == 2
    assert not any(call[0] == "ensure" for call in convenience.calls)


def test_wrapper_refuses_existing_artifact_directory(convenience):
    convenience.artifacts.mkdir()
    assert main([*convenience.combined, ACK, "--yes"]) == 2
    assert convenience.calls == [] and convenience.api_calls == []


def test_catalog_revision_preflight_blocks_before_ensure(convenience):
    assert main([*convenience.combined, ACK, "--yes", "--expected-revision", "f" * 64]) == 3
    assert convenience.api_calls == ["list"]
    assert not any(call[0] == "ensure" for call in convenience.calls)
    outcome = json.loads((convenience.artifacts / "outcome.json").read_text())
    assert outcome["phase"] == "catalog-preflight" and outcome["reconciliation_required"] is False


def test_wrapper_requires_catalog_revision_not_preview_revision(convenience, monkeypatch):
    monkeypatch.setattr(AzureFactoryClient, "catalog_list", lambda *args: {"source_revision": "a" * 64})
    assert main([*convenience.combined, ACK, "--yes"]) == 2
    assert not any(call[0] == "ensure" for call in convenience.calls)


@pytest.mark.parametrize("phase", ["ensure", "prepare", "confirm"])
def test_wrapper_persists_partial_or_uncertain_failure_without_retry(convenience, monkeypatch, phase):
    from azurefactory.errors import RequestTimeout

    def fail(*args, **kwargs):
        if phase != "ensure":
            convenience.api_calls.append(phase)
        raise RequestTimeout("must-never-be-printed")
    if phase == "ensure":
        monkeypatch.setattr(CORE, "ensure", lambda *a, **kw: {
            "status": "blocked", "changed": True, "enrollment_complete": False,
            "reconciliation_required": True, "error": "post-create-rights-not-verified"})
    else:
        monkeypatch.setattr(AzureFactoryClient, "catalog_" + phase, fail)
    assert main([*convenience.combined, ACK, "--yes"]) == 5
    outcome = json.loads((convenience.artifacts / "outcome.json").read_text())
    assert outcome["published"] is False and outcome["reconciliation_required"] is True
    assert convenience.api_calls.count("confirm") == (1 if phase == "confirm" else 0)
    if phase == "confirm":
        assert outcome["publication_uncertain"] is True
        assert (convenience.artifacts / "publication-intent.json").is_file()
        assert not (convenience.artifacts / "publication.json").exists()
    if phase == "ensure":
        assert json.loads((convenience.artifacts / "result.json").read_text())["result"]["changed"] is True


def test_wrapper_blocked_binding_receipt_never_publishes(convenience, monkeypatch):
    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", lambda *a: {
        "can_execute": False, "blockers": ["protected-source-not-ready"]})
    assert main([*convenience.combined, ACK, "--yes"]) == 3
    assert "confirm" not in convenience.api_calls
    assert (convenience.artifacts / "binding.receipt.json").is_file()


def test_wrapper_rejects_changed_binding_preview(convenience, monkeypatch):
    original = AzureFactoryClient.catalog_prepare

    def changed(self, body):
        result = original(self, copy.deepcopy(body))
        result["binding"]["writer_id"] = "different"
        return result
    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", changed)
    assert main([*convenience.combined, ACK, "--yes"]) == 5
    assert "confirm" not in convenience.api_calls
    assert not (convenience.artifacts / "publication-intent.json").exists()
