"""Offline first-run coverage using the existing registered transport fixtures."""

import copy
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from time import sleep as REAL_SLEEP
from types import SimpleNamespace

import pytest

from unit.test_registered_prerequisites import (
    ACCOUNT, COMMON_VNET, GROUP, OWNED, Runtime, SUB, TENANT, arguments, core, execute,
    no_live, workspace, REAL_SUBPROCESS_RUN,
)
import registered_repository as repository
import runner_bootstrap as runners


PROOF = {"repository": "https://github.com/example/factory", "ref": repository.LOCK_REF,
         "sha": "a" * 40, "owner": "11111111-1111-1111-1111-111111111111"}


class ProviderRuntime(Runtime):
    def __init__(self):
        super().__init__()
        self.resources = {key: value for key, value in self.resources.items() if ACCOUNT not in key}
        self.guard_reads = 0
        self.lose_guard = False

    def verify_provider_serialization(self, proof):
        assert proof == PROOF
        self.guard_reads += 1
        core.require(not self.lose_guard, "provider-initializer-lock-not-held")

    def blob(self, *args, **kwargs):
        pytest.fail("No-hub initialization must never access Blob or require ADLS")

    def arm(self, method, identifier, api, **kwargs):
        status, headers, value = super().arm(method, identifier, api, **kwargs)
        if method == "PUT" and "/userassignedidentities/" in identifier.lower():
            value["properties"].update(tenantId=TENANT, principalId=GROUP,
                                       clientId="55555555-5555-5555-5555-555555555555")
            self.resources[identifier.lower()] = copy.deepcopy(value)
        return status, headers, value


def provider_arguments(workspace, minimum=False):
    result = arguments(workspace, dev_vnet_cidr="172.16.0.0/20")
    result["context"].update(coordination={}, coordination_mode="provider", provider_serialization=PROOF)
    if minimum:
        result["context"].update(bootstrap_phase="minimum-foundation", deployment_identity_id=
                                 OWNED + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/reviewed-writer")
    return result


def test_first_run_no_hub_uses_provider_reservation_not_adls(workspace):
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace), runtime=runtime)
    assert plan["can_execute"]
    assert not any(item.get("id", "").startswith(ACCOUNT) for item in plan["observations"])
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded"
    assert runtime.guard_reads > 2
    assert result["leases"] == {}


def test_minimum_foundation_creates_rg_vnet_identity_without_group_or_vault(workspace):
    runtime = ProviderRuntime()
    runtime.resources.clear()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    assert [effect["id"] for effect in plan["effects"]] == [
        OWNED, COMMON_VNET, OWNED + "/providers/microsoft.managedidentity/userassignedidentities/reviewed-writer"]
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    assert result["bindings"]["deployment_principal_id"] == GROUP
    assert not any(item[0] == "graph" for item in runtime.writes)


def test_lost_provider_reservation_blocks_before_writes(workspace):
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace), runtime=runtime)
    runtime.lose_guard = True
    with pytest.raises(core.PrerequisiteError, match="provider-initializer-lock-not-held"):
        execute(plan, workspace, runtime)
    assert not runtime.writes


@pytest.mark.parametrize("failure", ["provider-initializer-lock-not-held", "remote-request-failed-401"])
def test_minimum_preflight_rejection_retains_evidence_without_cloud_writes(workspace, failure):
    runtime = ProviderRuntime()
    runtime.resources.clear()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    runtime.fail_read = failure
    with pytest.raises(core.PrerequisiteError, match=failure):
        execute(plan, workspace, runtime)
    receipt = core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"])
    assert receipt["status"] == "rejected"
    assert receipt["phase"] == "preflight" and receipt["cloud_writes_started"] is False
    assert receipt["error"] == failure and receipt["plan_hash"] == plan["plan_hash"]
    assert receipt["changed"] is False and receipt["effects_completed"] == [] and receipt["leases"] == {}
    assert receipt["reconciliation_required"] and receipt["requires_fresh_review"]
    assert runtime.read_only and not runtime.serialized_provisioning and not runtime.writes
    original = (workspace[2] / (plan["plan_id"] + ".json")).read_bytes()
    runtime.fail_read = None
    with pytest.raises(FileExistsError):
        execute(plan, workspace, runtime)
    assert (workspace[2] / (plan["plan_id"] + ".json")).read_bytes() == original
    assert not runtime.writes


def test_minimum_preflight_preserves_safe_error_not_transport_secret(workspace, monkeypatch):
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    def failed_read(*args, **kwargs):
        raise OSError("Authorization: Bearer secret-must-not-leak")
    monkeypatch.setattr(runtime, "arm", failed_read)
    with pytest.raises(OSError):
        execute(plan, workspace, runtime)
    receipt = core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"])
    assert receipt["error"] == "prerequisite-preflight-io-failed"
    assert "secret-must-not-leak" not in json.dumps(receipt)
    assert not runtime.writes and runtime.read_only


def test_minimum_execution_failure_never_claims_preflight_rejection(workspace):
    runtime = ProviderRuntime()
    runtime.resources.clear()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    runtime.fail_write = lambda _: True
    result = execute(plan, workspace, runtime)
    assert result["status"] == "uncertain"
    assert result["phase"] == "execution" and result["cloud_writes_started"] is True
    assert result["pending_effect"] == 0 and result["reconciliation_required"]
    assert core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"]) == result


def test_minimum_execution_intent_is_durable_before_transport_can_write(workspace, monkeypatch):
    runtime = ProviderRuntime()
    runtime.resources.clear()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    original = runtime.arm
    def observed(method, *args, **kwargs):
        if method != "GET":
            receipt = core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"])
            assert receipt["phase"] == "execution" and receipt["cloud_writes_started"] is True
        return original(method, *args, **kwargs)
    monkeypatch.setattr(runtime, "arm", observed)
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded"
    assert runtime.read_only and not runtime.serialized_provisioning


def test_minimum_preflight_expiring_during_discovery_never_enables_writes(workspace, monkeypatch):
    clock = [core.time.time()]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    prepare = core.prepare
    def slow_prepare(**kwargs):
        result = prepare(**kwargs)
        clock[0] += 901
        return result
    monkeypatch.setattr(core, "prepare", slow_prepare)
    with pytest.raises(core.PrerequisiteError, match="prerequisite-review-expired"):
        execute(plan, workspace, runtime)
    receipt = core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"])
    assert receipt["status"] == "rejected" and not receipt["cloud_writes_started"]
    assert not runtime.writes and runtime.read_only


def test_minimum_write_intent_persistence_failure_never_enables_writes(workspace, monkeypatch):
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    def fail_persist(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(core, "_persist", fail_persist)
    with pytest.raises(OSError, match="disk unavailable"):
        execute(plan, workspace, runtime)
    receipt = core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"])
    assert receipt["status"] == "preflight" and not receipt["cloud_writes_started"]
    assert not runtime.writes and runtime.read_only and not runtime.serialized_provisioning


def test_minimum_rejection_persistence_failure_preserves_original_error(workspace, monkeypatch):
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    runtime.fail_read = "remote-request-failed-401"
    def fail_persist(*args):
        raise PermissionError("receipt replacement denied")
    monkeypatch.setattr(core, "_persist", fail_persist)
    with pytest.raises(core.PrerequisiteError, match="remote-request-failed-401") as captured:
        execute(plan, workspace, runtime)
    assert isinstance(captured.value.__cause__, PermissionError)
    receipt = core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"])
    assert receipt["status"] == "preflight" and not receipt["cloud_writes_started"]
    assert not runtime.writes and runtime.read_only
    with pytest.raises(FileExistsError):
        execute(plan, workspace, runtime)


def test_minimum_invalid_consent_cannot_create_receipt(workspace):
    runtime = ProviderRuntime()
    plan = core.prepare(**provider_arguments(workspace, True), runtime=runtime)
    plan["effects"].clear()
    with pytest.raises(core.PrerequisiteError, match="prerequisite-plan-hash-mismatch"):
        execute(plan, workspace, runtime)
    assert not list(workspace[2].iterdir()) and not runtime.writes


def test_repo_prepare_pins_published_source_and_preserves_saved_draft(workspace):
    consumer = workspace[0]
    document = json.loads((consumer / "azurefactory" / "register.json").read_bytes())
    scope = {"factory_id": document["factories"][0]["id"], "scale_set_id": document["factories"][0]["scale_sets"][0]["id"]}
    calls = []
    fake = SimpleNamespace(discover=lambda: None, source_assets=lambda sha: {"verified": sha},
                           git=lambda root, *args, **kwargs:
                           calls.append(args) or "b" * 40 + "\trefs/heads/main")
    before = (consumer / "azurefactory" / "register.json").read_bytes()
    plan = repository.prepare(consumer_root=consumer, scope=scope, expected_revision="reviewed",
                              bootstrap_config={"github_repository": "example/factory"}, runtime=fake)
    assert plan["source"]["sha"] == "b" * 40
    assert plan["source"]["verification"] == "published-remote-ref"
    assert calls == [("ls-remote", repository.SHARED_URL, "refs/heads/main")]
    assert (consumer / "azurefactory" / "register.json").read_bytes() == before


def test_provider_guard_requires_exact_ref_and_sha():
    runtime = object.__new__(core.Cloud)
    runtime.command = lambda args: "b" * 40 + "\t" + PROOF["ref"]
    with pytest.raises(core.PrerequisiteError, match="not-held"):
        runtime.verify_provider_serialization(PROOF)


def test_minimum_existing_identity_is_reused_without_ownership_or_mutation(workspace):
    runtime = ProviderRuntime()
    args = provider_arguments(workspace, True)
    identity = "/subscriptions/" + SUB + "/resourcegroups/shared-identities/providers/microsoft.managedidentity/userassignedidentities/existing"
    args["context"].update(deployment_identity_id=identity, reuse_deployment_identity=True)
    runtime.resources[identity] = {"id": identity, "location": "swedencentral", "properties": {
        "tenantId": TENANT, "principalId": GROUP, "clientId": "55555555-5555-5555-5555-555555555555",
        "provisioningState": "Succeeded"}}
    plan = core.prepare(**args, runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    assert not any(effect.get("id") == identity for effect in plan["effects"])
    assert plan["bindings"]["deployment_identity_id"] == identity


def test_new_ado_pool_and_project_queue_are_verified_without_hosted_fallback():
    pools, queues, writes = [], [], []
    request = {"provider": "ado", "prereqs_only": False, "ado_organization": "https://dev.azure.com/example",
               "ado_tenant_id": TENANT, "pool": "factory-pool", "agent_name": "factory-agent", "vm_os": "linux"}
    def http(method, url, audience, data=None, **kwargs):
        if method == "POST":
            writes.append((url, data))
            if "/pools?" in url:
                pools.append({"id": 4, "name": request["pool"], "isHosted": False})
            else:
                queues.append({"id": 6, **data})
            return 201, {}, data
        value = queues if "/queues?" in url else [] if "/agents?" in url else pools
        return 200, {}, {"value": value}
    cloud = SimpleNamespace(http=http, read_only=True)
    assert runners.provider_action(request, cloud, allow_pool_create=True) == "create-pool-and-register"
    assert not writes
    runners.ensure_provider_pool(request, cloud, project="Exact Project")
    assert len(writes) == 2
    assert "/Exact%20Project/" in writes[-1][0]
    runners.ensure_provider_pool(request, cloud, project="Exact Project")
    assert len(writes) == 2


def test_existing_unmanageable_ado_pool_is_not_replaced():
    request = {"provider": "ado", "prereqs_only": False, "ado_organization": "https://dev.azure.com/example",
               "ado_tenant_id": TENANT, "pool": "factory-pool"}
    cloud = SimpleNamespace(http=lambda method, url, *args, **kwargs:
                            (200, {}, {"value": [] if "actionFilter" in url else [{"name": "factory-pool"}]}))
    with pytest.raises(runners.EnrollmentError, match="existing-pool-not-manageable"):
        runners.provider_action(request, cloud, allow_pool_create=True)


def test_selected_project_group_gets_exact_logical_and_physical_ownership(workspace):
    consumer = workspace[0]
    path = consumer / "azurefactory" / "register.json"
    document = json.loads(path.read_bytes())
    factory = document["factories"][0]
    project_id = "88888888-8888-8888-8888-888888888888"
    factory["projects"] = [{"id": project_id, "number": "001",
                            "placements": [{"environment": "dev", "scale_set_id": factory["scale_sets"][0]["id"]}]}]
    path.write_bytes(core.canonical(document))
    args = provider_arguments(workspace, True)
    group = "/subscriptions/" + SUB + "/resourcegroups/aif-esml-project001-sdc-dev-001-rg"
    args["scope"]["project_id"] = project_id
    args["context"]["owned_resource_group_ids"].append(group)
    args["context"]["project_resource_group_id"] = group
    plan = core.prepare(**args, runtime=ProviderRuntime())
    assert plan["can_execute"], plan["blockers"]
    effect = next(item for item in plan["effects"] if item.get("id") == group)
    assert effect["body"]["tags"]["aifactory.project_id"] == "001"
    assert effect["body"]["tags"]["aifactory.logical_project_id"] == project_id
    assert plan["bindings"]["project_resource_group_id"] == group


def test_subscription_role_is_deployment_metadata_only_not_resource_contributor(workspace):
    args = provider_arguments(workspace)
    identity = OWNED + "/providers/microsoft.managedidentity/userassignedidentities/deployer"
    args["context"].update(deployment_identity_id=identity, deployment_principal_id=GROUP)
    runtime = ProviderRuntime()
    runtime.resources[identity] = {"id": identity, "properties": {"tenantId": TENANT, "principalId": GROUP}}
    plan = core.prepare(**args, runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    role = next(item for item in plan["effects"] if "/roledefinitions/" in item.get("id", "").lower())
    permissions = role["body"]["properties"]["permissions"][0]
    assert permissions["dataActions"] == []
    assert not any("*" in item for item in permissions["actions"])
    writes = [item for item in permissions["actions"] if item.lower().endswith("/write")]
    assert writes == ["Microsoft.Resources/deployments/write"]
    assert "/subscriptions/" + SUB in plan["lock_scopes"]


def test_reviewed_workload_provider_is_registered_before_first_common(workspace):
    args = provider_arguments(workspace)
    args["bootstrap_config"]["resource_providers"] = ["Microsoft.Storage"]
    runtime = ProviderRuntime()
    identifier = "/subscriptions/" + SUB + "/providers/microsoft.storage"
    runtime.resources[identifier] = {"id": identifier, "registrationState": "NotRegistered"}
    plan = core.prepare(**args, runtime=runtime)
    assert any(item["kind"] == "provider-register" and item["id"].lower() == identifier for item in plan["effects"])
    assert execute(plan, workspace, runtime)["status"] == "succeeded"
    assert runtime.resources[identifier]["registrationState"] == "Registered"


@pytest.mark.parametrize("changed_blob", [False, True])
def test_repository_execution_retains_published_pin_and_never_stages_saved_draft(workspace, changed_blob):
    consumer, _, state = workspace
    saved = (consumer / "azurefactory" / "register.json").read_bytes()
    document = json.loads(saved)
    scope = {"factory_id": document["factories"][0]["id"], "scale_set_id": document["factories"][0]["scale_sets"][0]["id"]}
    calls, refs, remote = [], {}, {}
    assets = {"bootstrap/templates/factory-lifecycle-gha.yml": b"reviewed: workflow\n",
              "bootstrap/templates/hub_private_probe.py": b"reviewed = True\n"}
    def git(root, *args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "ls-remote":
            value = "b" * 40 if args[1] == repository.SHARED_URL else refs.get(args[2])
            return value + "\t" + args[2] if value else ""
        if args[0] == "init":
            (root / ".git").mkdir()
        elif args[0] == "clone":
            templates = Path(args[-1]) / "bootstrap" / "templates"
            templates.mkdir(parents=True)
            (templates / "factory-lifecycle-gha.yml").write_bytes(b"reviewed: workflow\n")
            (templates / "hub_private_probe.py").write_bytes(b"reviewed = True\n")
        elif args[0] == "rev-parse":
            return "b" * 40
        elif args[0] == "cat-file":
            assert kwargs["raw"] is True
            return b"changed\n" if changed_blob else assets[args[2].split(":", 1)[1]]
        elif args[0] in ("hash-object", "write-tree"):
            return "c" * 40
        elif args[0] == "commit-tree":
            return ("e" if "-p" in args else "d") * 40
        elif args[0] == "push":
            sha, ref = args[-1].split(":", 1)
            refs[ref] = sha
        return ""
    runtime = SimpleNamespace(discover=lambda: remote or None, source_assets=lambda sha: {
        name: hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        for name, data in assets.items()}, git=git,
                              create=lambda: remote.update(id=7), set_initial_default_branch=lambda: None,
                              ensure_environment=lambda name, expected: {"name": name})
    plan = repository.prepare(consumer_root=consumer, scope=scope, expected_revision="reviewed",
                              bootstrap_config={"github_repository": "example/factory"}, runtime=runtime)
    result = repository.execute(plan, state_dir=state, runtime=runtime)
    if changed_blob:
        assert result["status"] == "uncertain"
        assert result["error"].startswith("published-bootstrap-asset-hash-mismatch:")
        assert not refs
        assert not any(args[0] == "update-index" for args, _ in calls)
        assert (consumer / "azurefactory" / "register.json").read_bytes() == saved
        return
    assert result["status"] == "succeeded", result
    assert result["outputs"]["bindings"]["published_source"] == plan["source"]
    assert refs[repository.LOCK_REF] == result["outputs"]["provider_serialization"]["sha"]
    assert (consumer / "azurefactory" / "register.json").read_bytes() == saved
    assert not any("register.json" in " ".join(args) for args, _ in calls)
    assert all(kwargs.get("environment", {}).get("GIT_INDEX_FILE") for args, kwargs in calls if args[0] == "read-tree")


@pytest.fixture
def offline_git_wait(monkeypatch, no_live):
    # POSIX subprocess timeout polling must not use the shared no-live sleep guard.
    monkeypatch.setattr(repository.subprocess, "time", SimpleNamespace(sleep=REAL_SLEEP))


def test_offline_git_wait_preserves_no_live_guard(offline_git_wait):
    for blocked in (lambda: core.time.sleep(0),
                    lambda: repository.subprocess.run(["git", "--version"]),
                    core.enrollment.build_opener):
        with pytest.raises(AssertionError, match="LIVE COMMANDS/HTTP/SLEEP FORBIDDEN"):
            blocked()
    repository.subprocess.time.sleep(0)
    result = REAL_SUBPROCESS_RUN(
        [sys.executable, "-c",
         "import os,time; os.close(1); os.close(2); time.sleep(0.1); os._exit(0)"],
        capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("environment_failure", [False, True])
@pytest.mark.parametrize("dirty_source", [False, True])
def test_ignored_probe_is_committed_by_exact_path_without_private_metadata(
        workspace, tmp_path, environment_failure, dirty_source, offline_git_wait):
    consumer = tmp_path / "consumer"
    shutil.copytree(workspace[0], consumer)
    source = consumer / repository.SHARED_PATH
    state = tmp_path / "state"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_AUTHOR_NAME="Offline fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                       GIT_COMMITTER_NAME="Offline fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")

    def local_git(*args, data=None, extra_env=None, directory=consumer):
        result = REAL_SUBPROCESS_RUN(
            ["git", "-c", "core.hooksPath=" + str(hooks), "-c", "core.autocrlf=false",
             "-c", "commit.gpgsign=false", "-C", str(directory), *args],
            input=data, capture_output=True, env={**environment, **(extra_env or {})}, timeout=30)
        if result.returncode:
            pytest.fail(f"Offline git {args!r} in {directory}: {result.stderr.decode(errors='replace')}")
        return result.stdout

    local_git("init", "--initial-branch=main")
    ignore = b".azurefactory/\n"
    (consumer / ".gitignore").write_bytes(ignore)
    local_git("add", "--", ".gitignore")
    tree = local_git("write-tree").decode().strip()
    head = local_git("commit-tree", tree, data=b"Fixture baseline\n").decode().strip()
    local_git("update-ref", "refs/heads/main", head)
    (consumer / "unrelated-staged.txt").write_bytes(b"Keep staged, never publish\n")
    local_git("add", "--", "unrelated-staged.txt")
    metadata = consumer / ".azurefactory"
    metadata.mkdir()
    for name in ("receipt.json", "protected-state.json", "fixture.key"):
        (metadata / name).write_bytes(b"Private fixture data; not credentials\n")
    probe = ".azurefactory/hub_private_probe.py"
    assert local_git("check-ignore", "--no-index", "--", probe).decode().strip() == probe
    staged_before = local_git("ls-files", "--stage", "--", "unrelated-staged.txt")
    saved = (consumer / "azurefactory" / "register.json").read_bytes()
    document = json.loads(saved)
    scope = {"factory_id": document["factories"][0]["id"],
             "scale_set_id": document["factories"][0]["scale_sets"][0]["id"]}
    probe_bytes = b"reviewed_probe_asset = True\r\n"
    source.mkdir()
    local_git("init", "--initial-branch=main", directory=source)
    templates = source / "bootstrap" / "templates"
    templates.mkdir(parents=True)
    (templates / "factory-lifecycle-gha.yml").write_bytes(b"reviewed: workflow\n")
    (templates / "hub_private_probe.py").write_bytes(probe_bytes)
    local_git("add", "--", "bootstrap", directory=source)
    source_tree = local_git("write-tree", directory=source).decode().strip()
    source_sha = local_git("commit-tree", source_tree, data=b"Reviewed source\n", directory=source).decode().strip()
    local_git("update-ref", "refs/heads/main", source_sha, directory=source)
    assets = {relative: local_git("rev-parse", source_sha + ":" + relative, directory=source).decode().strip()
              for relative in ("bootstrap/templates/factory-lifecycle-gha.yml", "bootstrap/templates/hub_private_probe.py")}
    if dirty_source:
        (templates / "factory-lifecycle-gha.yml").write_bytes(b"unreviewed: workflow\n")
        (templates / "hub_private_probe.py").write_bytes(b"unreviewed_probe = True\n")
    refs, remote = {}, {}

    def git(root, *args, **kwargs):
        if args[0] == "ls-remote":
            value = source_sha if args[1] == repository.SHARED_URL else refs.get(args[2])
            return value + "\t" + args[2] if value else ""
        if Path(root) == source:
            assert args[0] in ("cat-file", "rev-parse")
            result = local_git(*args, directory=source)
            return result if kwargs.get("raw") else result.decode().strip()
        if args[0] == "push":
            sha, ref = args[-1].split(":", 1)
            refs[ref] = sha
            return ""
        assert Path(root) == consumer
        assert args[0] in ("rev-parse", "symbolic-ref", "remote", "diff", "hash-object",
                           "read-tree", "update-index", "write-tree", "commit-tree", "update-ref")
        if args[:3] == ("remote", "get-url", "origin") and not remote:
            return ""
        return local_git(*args, data=kwargs.get("data"), extra_env=kwargs.get("environment")).decode().strip()

    def ensure_environment(name, expected):
        if environment_failure:
            raise repository.enrollment.EnrollmentError("fixture-environment-response-lost")
        return {"name": name}
    runtime = SimpleNamespace(discover=lambda: remote or None, source_assets=lambda sha: dict(assets),
                              git=git, create=lambda: remote.update(id=7), set_initial_default_branch=lambda: None,
                              ensure_environment=ensure_environment)
    plan = repository.prepare(consumer_root=consumer, scope=scope, expected_revision="reviewed",
                              bootstrap_config={"github_repository": "example/factory"}, runtime=runtime)
    result = repository.execute(plan, state_dir=state, runtime=runtime)
    assert result["status"] == ("uncertain" if environment_failure else "succeeded"), result
    if environment_failure:
        assert result["error"] == "fixture-environment-response-lost", result
    committed = refs["refs/heads/main"]
    assert local_git("show", committed + ":" + probe) == probe_bytes.replace(b"\r\n", b"\n")
    assert (consumer / probe).read_bytes() == probe_bytes.replace(b"\r\n", b"\n")
    assert local_git("show", committed + ":.github/workflows/factory-lifecycle.yml") == b"reviewed: workflow\n"
    if dirty_source:
        assert (templates / "hub_private_probe.py").read_bytes() == b"unreviewed_probe = True\n"
    assert json.loads((state / (plan["plan_id"] + ".json")).read_text())["status"] == result["status"]
    assert set(local_git("ls-tree", "-r", "--name-only", committed).decode().splitlines()) == {
        ".gitignore", ".gitmodules", ".github/workflows/factory-lifecycle.yml", probe, repository.SHARED_PATH}
    assert local_git("ls-files", "--stage", "--", "unrelated-staged.txt") == staged_before
    assert local_git("diff", "--cached", "--name-only", "HEAD").decode().strip() == "unrelated-staged.txt"
    assert (consumer / ".gitignore").read_bytes() == ignore
    assert (consumer / "azurefactory" / "register.json").read_bytes() == saved
    for name in ("receipt.json", "protected-state.json", "fixture.key"):
        assert local_git("check-ignore", "--no-index", "--", ".azurefactory/" + name).strip()


@pytest.mark.parametrize("existing,race", [(False, False), (True, False), (False, True)])
def test_github_environment_create_or_return_never_overwrites_policy(existing, race):
    native = object.__new__(repository.Repository)
    native.provider = "gha"
    native.config = {"github_repository": "example/factory"}
    name = "aifactory-reviewed"
    protected = {"name": name, "node_id": "EN_reviewed", "protection_rules": [{"type": "wait_timer", "wait_timer": 30}],
                 "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}
    current, mutations = [copy.deepcopy(protected) if existing else None], []
    def get(method, path, **kwargs):
        assert method == "GET"
        if path == "repos/example/factory":
            return 200, {}, {"node_id": "R_reviewed"}
        assert path == "repos/example/factory/environments/" + name
        return (200, {}, copy.deepcopy(current[0])) if current[0] else (404, {}, {})
    def command(argv, data):
        assert argv == ["gh", "api", "--hostname", "github.com", "--method", "POST", "graphql", "--input", "-"]
        body = json.loads(data)
        assert body["variables"] == {"repository": "R_reviewed", "name": name}
        assert "createEnvironment" in body["query"] and "updateEnvironment" not in body["query"]
        mutations.append(body)
        current[0] = copy.deepcopy(protected) if race else {"name": name, "node_id": "EN_reviewed"}
        return json.dumps({"data": {"createEnvironment": {"environment": {"id": "EN_reviewed", "name": name}}}})
    native.cloud = SimpleNamespace(gh=get, command=command, read_only=True)
    actual = native.ensure_environment(name, copy.deepcopy(protected) if existing else None)
    assert len(mutations) == (0 if existing else 1)
    assert actual == (protected if existing or race else {"name": name, "node_id": "EN_reviewed"})


def test_github_environment_policy_drift_blocks_without_mutation():
    native = object.__new__(repository.Repository)
    expected = {"name": "aifactory-reviewed", "protection_rules": [{"type": "required_reviewers"}]}
    native.environment = lambda name: {"name": name, "protection_rules": []}
    with pytest.raises(repository.enrollment.EnrollmentError, match="reviewed-github-environment-changed"):
        native.ensure_environment(expected["name"], expected)
