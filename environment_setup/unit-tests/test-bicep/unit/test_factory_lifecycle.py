"""Offline lifecycle tests: no real CLI, authentication, HTTP or deployment."""

import base64
import copy
import ctypes
import importlib.util
import io
import json
import re
import shutil
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("factory_lifecycle_offline", ROOT / "bootstrap/lib/factory_lifecycle.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
IDENTITY = "cccccccc-cccc-cccc-cccc-cccccccccccc"
GROUP = f"/subscriptions/{SUB}/resourceGroups/reviewed"
COMMON = f"/subscriptions/{SUB}/resourceGroups/common"
RESOURCE = GROUP + "/providers/Microsoft.Network/publicIPAddresses/reviewed-ip"
OWNER = {"factory_id": "factory-a", "scaleset_id": "Stage001", "project_id": "017"}
RESOURCE_BODY = {
    "id": RESOURCE, "type": "Microsoft.Network/publicIPAddresses", "etag": '"resource-version"',
    "tags": {fl.TAG_KEYS[key]: value for key, value in OWNER.items()},
    "properties": {"provisioningState": "Succeeded", "publicIPAllocationMethod": "Static"},
}
GROUP_BODY = {"id": GROUP, "name": "reviewed", "properties": {"provisioningState": "Succeeded"}}


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    monkeypatch.setattr(fl.subprocess, "run", Mock(side_effect=AssertionError("Real commands forbidden")))
    monkeypatch.setattr(fl, "build_opener", Mock(side_effect=AssertionError("Real HTTP forbidden")))


@pytest.fixture
def workspace():
    path = ROOT / (".lifecycle-offline-" + str(uuid4()))
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def seal(document):
    document["manifest_hash"] = fl.manifest_digest(document)
    return document


def enrollment():
    return {
        "schema": 1, "protocol": "aifactory-physical-lock-v1", "enforcement": "all-writers-exclusive", "revision": 4,
        "writers": {"writer-a": {"kind": "ado", "repository": "https://dev.azure.com/org/project/_git/consumer",
                                "shared_remote": False}},
        "scopes": {GROUP.lower(): {
                      "writers": ["writer-a"], "common_dependencies": [COMMON.lower()],
                      "scope_kind": "aifactory-owned", "allow_delete": True,
                      "target": {"factory_id": "factory-a", "scaleset_id": "Stage001", "environment": "stage",
                                 "tenant_id": TENANT, "subscription_id": SUB, "prefix": "acme-ai-",
                                 "region": "eastus2", "suffix": "001"}},
                   COMMON.lower(): {"writers": ["writer-a"], "common_dependencies": []}},
    }


def manifest(operation="delete"):
    now = time.time()
    result = {
        "schema": 1, "operation": operation, "run_id": str(uuid4()), "manifest_revision": 3,
        "prepared_at": datetime.fromtimestamp(now - 5, timezone.utc).isoformat(),
        "expires_at": datetime.fromtimestamp(now + 1800, timezone.utc).isoformat(),
        "source": {"commit": "a" * 40, "ref": "refs/tags/v1.25.0", "version": "v1.25.0"},
        "target": {"factory_id": "factory-a", "scaleset_id": "Stage001", "environment": "stage",
                   "tenant_id": TENANT, "subscription_id": SUB, "prefix": "acme-ai-",
                   "region": "eastus2", "suffix": "001", "project_ids": ["017"]},
        "identity": {"object_id": IDENTITY},
        "route": {"kind": "ado", "writer_id": "writer-a", "repository": "https://dev.azure.com/org/project/_git/consumer",
                  "ref": "refs/heads/main", "commit": "b" * 40, "shared_remote": False},
        "config": {"secret": "synthetic-not-a-credential"},
        "locks": {"provider": "azure-blob-lease", "account_url": "https://lockstore.blob.core.windows.net",
                  "container": "factory-locks", "coordination_blob": "coordination.json",
                  "coordination_hash": fl.digest(enrollment()), "revision": 4,
                  "scopes": [GROUP], "common_dependencies": [COMMON]},
    }
    if operation == "delete":
        resources = [{"id": RESOURCE, "type": "Microsoft.Network/publicIPAddresses",
                      "api_version": "2024-05-01", "etag": RESOURCE_BODY["etag"],
                      "body_hash": fl.digest(RESOURCE_BODY), "owner": copy.deepcopy(OWNER),
                      "depends_on": [], "delete": True}]
        result["deletion"] = {
            "inventory_complete": True, "revision": 3, "resources": resources, "inventory_hash": fl.digest(resources),
            "resource_groups": [{"id": GROUP, "body_hash": fl.digest(GROUP_BODY), "etag": None, "delete": False}],
        }
    if operation == "deploy-project":
        values = {"project_number_000": "017", "tenantId": TENANT, "test_sub_id": SUB, "dev_sub_id": SUB,
                  "admin_location": "eastus2", "admin_aifactoryPrefixRG": "acme-ai-", "admin_aifactorySuffixRG": "-001",
                  "servicePrincipalSecret": "synthetic-not-a-credential"}
        result["config"] = {"dev": copy.deepcopy(values), "stage_prod": values}
    return seal(result)


@pytest.mark.parametrize("factory_type", ["ai", "data", "integration", "app", "", None])
def test_register_factory_type_is_not_silently_executed_as_ai(factory_type):
    document = manifest("deploy-project")
    document["target"]["factory_type"] = factory_type
    seal(document)
    if factory_type == "ai":
        assert fl.validate_manifest(document) == document
    else:
        with pytest.raises(fl.Blocked, match="unsupported-factory-type"):
            fl.validate_manifest(document)


@pytest.mark.parametrize("field,value", [
    ("admin_location", "swedencentral"), ("test_sub_id", TENANT),
    ("tenantId", SUB), ("project_number_000", "001"),
    ("admin_aifactorySuffixRG", "-002"), ("admin_aifactoryPrefixRG", "other-ai-"),
])
def test_register_generated_config_matches_scoped_manifest_before_execution(field, value):
    document = manifest("deploy-project")
    document["target"]["factory_type"] = "ai"
    document["config"]["stage_prod"][field] = value
    with pytest.raises(fl.Blocked, match="config-target-mismatch"):
        fl.validate_manifest(seal(document))


def test_register_export_is_consumed_as_exact_manifest_without_layout_writes(workspace, monkeypatch, capsys):
    document = manifest("deploy-project")
    document["target"]["factory_type"] = "ai"
    leaf = workspace / "azurefactory/factories/ai-marvel/scalesets/stage/001/projects/project017/variables.json"
    leaf.parent.mkdir(parents=True)
    export = {"generation": "c" * 64, "factory_id": document["target"]["factory_id"],
              "project_id": "logical-project-id", "scale_set_id": document["target"]["scaleset_id"],
              "environment": "stage", "number": "017", "generated": True, "variables": document["config"]}
    leaf.write_text(json.dumps(export), encoding="utf-8")
    register = workspace / "azurefactory/register.json"
    register.write_text('{"schema": 2}', encoding="utf-8")
    document["config"] = json.loads(leaf.read_text(encoding="utf-8"))["variables"]
    before = {str(p): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    monkeypatch.setattr(fl.sys, "stdin", SimpleNamespace(
        isatty=lambda: False, buffer=io.BytesIO(fl.canonical(seal(document)))))
    assert fl.main(["inspect", "--stdin-manifest"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["manifest_valid"]
    assert before == {str(p): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert not (workspace / "aifactory").exists()


class FakeStorage:
    def __init__(self):
        self.enrollment = enrollment()
        self.leases = {}
        self.runs = {}
        self.calls = []
        self.tokens = {}

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        self.calls.append((method, url, copy.deepcopy(data), copy.deepcopy(headers)))
        blob = url.split("/factory-locks/", 1)[1].split("?", 1)[0]
        if blob == "coordination.json":
            return 200, {}, copy.deepcopy(self.enrollment)
        if "?comp=lease" in url:
            action = headers["x-ms-lease-action"]
            if action == "acquire":
                fl.require(blob not in self.leases, "remote-request-failed-409")
                assert headers["x-ms-lease-duration"] == "-1"
                self.leases[blob] = headers["x-ms-proposed-lease-id"]
                return 201, {}, None
            fl.require(self.leases.get(blob) == headers["x-ms-lease-id"], "remote-request-failed-412")
            if action == "release":
                del self.leases[blob]
            return 200, {}, None
        if blob.startswith("runs/"):
            if method == "GET":
                fl.require(blob in self.runs, "remote-request-failed-404")
                return 200, {}, copy.deepcopy(self.runs[blob])
            if headers.get("If-None-Match") == "*":
                fl.require(blob not in self.runs, "remote-request-failed-412")
            self.runs[blob] = copy.deepcopy(data)
            return 201, {}, None
        raise AssertionError("Unexpected storage operation")


class FakeCloud(FakeStorage):
    def __init__(self):
        super().__init__()
        self.bodies = {RESOURCE.lower(): copy.deepcopy(RESOURCE_BODY), GROUP.lower(): copy.deepcopy(GROUP_BODY)}
        self.deleted = []
        self.identity_checks = 0
        self.active = False
        self.active_run = False
        self.extra_inventory = []
        self.fail_delete = False
        self.delete_response_uncertain = False

    def verify_identity(self, require_default=False):
        self.identity_checks += 1

    def assert_no_active_deployments(self, scope):
        fl.require(not self.active, "active-or-unknown-deployment")

    def assert_no_active_runs(self, enrollment):
        fl.require(not self.active_run, "active-or-queued-remote-run")

    def list_resources(self, scope):
        return [copy.deepcopy(body) for resource_id, body in self.bodies.items()
                if resource_id != scope.lower() and fl.arm_scope(resource_id) == scope.lower()] + self.extra_inventory

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        key = resource_id.lower()
        if method == "DELETE":
            fl.require(not self.fail_delete, "remote-request-failed-409")
            self.deleted.append(resource_id)
            del self.bodies[key]
            fl.require(not self.delete_response_uncertain, "remote-request-unverified")
            return 202, {}, None
        if key not in self.bodies:
            assert 404 in allowed
            return 404, {}, None
        return 200, {}, copy.deepcopy(self.bodies[key])


def test_read_only_capabilities_are_honest():
    result = fl.capabilities()
    assert result["creation"] == "frozen-arm-deployment-plan-v1"
    assert result["shared_remote_namespaced_auth"] is True
    assert result["delete_owned_resource_groups"] == "arm-provider-closure-v1"
    assert result["project_routes"] == ["ado", "gha"]
    assert result["factory_cohort"] == "physical-lease-cohort-v1"


@pytest.mark.parametrize("operation", ["create-factory", "create-scaleset"])
def test_zero_projects_is_valid_but_no_fabricated_creation(operation):
    document = manifest(operation)
    document["target"]["project_ids"] = []
    fl.validate_manifest(seal(document))
    assert fl.operation_blockers(document) == ["frozen-scoped-deployment-plan-required"]
    assert document["target"]["project_ids"] == []


@pytest.mark.parametrize("change,code", [
    (lambda d: d["target"].update(subscription_id="wrong"), "invalid-azure-target"),
    (lambda d: d["source"].update(commit="main"), "exact-published-version-required"),
    (lambda d: d["target"].update(project_ids=["000"]), "invalid-project-identities"),
    (lambda d: d["locks"].update(provider="in-memory"), "distributed-lock-provider-required"),
    (lambda d: d["locks"].update(account_url="https://example.com"), "unsupported-lock-endpoint"),
    (lambda d: d["locks"].update(common_dependencies=None), "physical-lock-scopes-required"),
    (lambda d: d["locks"].update(scopes=["/subscriptions/" + SUB]), "resource-group-lock-required"),
    (lambda d: d["deletion"].update(inventory_complete=False), "complete-inventory-required"),
    (lambda d: d["deletion"].update(revision=2), "inventory-revision-mismatch"),
    (lambda d: d["deletion"]["resource_groups"][0].update(delete=True),
     "resource-group-extension-inventory-collector-required"),
])
def test_invalid_manifests_block_before_any_cloud(change, code):
    document = manifest()
    change(document)
    with pytest.raises(fl.Blocked, match=code):
        fl.validate_manifest(seal(document))


def test_frozen_hash_expiry_and_revision():
    document = manifest()
    document["config"]["secret"] = "changed"
    with pytest.raises(fl.Blocked, match="manifest-hash-mismatch"):
        fl.validate_manifest(document)
    seal(document)
    with pytest.raises(fl.Blocked, match="manifest-expired"):
        fl.validate_manifest(document, now=time.time() + 7200)


@pytest.mark.parametrize("key", ["tenantId", "test_sub_id", "project_number_000", "admin_location",
                                "admin_aifactoryPrefixRG", "admin_aifactorySuffixRG"])
def test_selected_project_config_is_not_silently_remapped(key):
    document = manifest("deploy-project")
    fl.validate_manifest(document)
    del document["config"]["stage_prod"][key]
    with pytest.raises(fl.Blocked, match="config-target-mismatch"):
        fl.validate_manifest(seal(document))


def test_unknown_and_nested_resources_cannot_be_approved_by_assertion():
    for resource_id, resource_type in [
        (GROUP + "/providers/Microsoft.Storage/storageAccounts/data", "Microsoft.Storage/storageAccounts"),
        (RESOURCE + "/providers/Microsoft.Authorization/roleAssignments/role", "Microsoft.Authorization/roleAssignments"),
    ]:
        document = manifest()
        resource = document["deletion"]["resources"][0]
        resource.update(id=resource_id, type=resource_type)
        document["deletion"]["inventory_hash"] = fl.digest(document["deletion"]["resources"])
        with pytest.raises(fl.Blocked, match="unsupported"):
            fl.validate_manifest(seal(document))


def test_dependency_order_and_retained_dependency_block():
    first = {"id": "one", "depends_on": ["two"], "delete": True}
    second = {"id": "two", "depends_on": [], "delete": True}
    assert [item["id"] for item in fl.deletion_order([second, first])] == ["one", "two"]
    second["depends_on"] = ["one"]
    with pytest.raises(fl.Blocked, match="cyclic"):
        fl.deletion_order([first, second])


def test_real_provider_protocol_uses_shared_physical_keys_and_no_local_mutex():
    document = manifest()
    storage = FakeStorage()
    one, two = fl.BlobLocks(storage, document), fl.BlobLocks(storage, document)
    one.acquire()
    assert set(one.held) == {GROUP.lower(), COMMON.lower()}
    assert fl.BlobLocks.blob_name(GROUP.upper()) == fl.BlobLocks.blob_name(GROUP)
    with pytest.raises(fl.Blocked, match="409"):
        two.acquire()
    one.assert_held()
    one.release()
    two.acquire()
    assert len(two.held) == 2
    assert all("synthetic-not-a-credential" not in json.dumps(call) for call in storage.calls)


def test_cross_machine_replay_claim_is_conditional_and_not_retryable():
    document, storage = manifest(), FakeStorage()
    locks = fl.BlobLocks(storage, document)
    locks.acquire()
    locks.claim_run()
    with pytest.raises(fl.Blocked, match="412"):
        locks.claim_run()
    locks.release()
    another_machine = fl.BlobLocks(storage, document)
    another_machine.acquire()
    with pytest.raises(fl.Blocked, match="412"):
        another_machine.claim_run()
    another_machine.release()


def test_lost_acquire_response_releases_only_our_proposed_lease():
    class ResponseLost(FakeStorage):
        def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
            result = super().request(method, url, audience, data, headers, allowed)
            if headers.get("x-ms-lease-action") == "acquire":
                raise fl.Blocked("remote-request-unverified")
            return result

    storage = ResponseLost()
    locks = fl.BlobLocks(storage, manifest())
    with pytest.raises(fl.Blocked, match="remote-request-unverified"):
        locks.acquire()
    assert not storage.leases and not locks.held


def test_different_factories_and_orchestrators_share_common_physical_lock():
    first, second, storage = manifest(), manifest(), FakeStorage()
    other_group = GROUP + "-other"
    second["route"].update(kind="gha", writer_id="writer-b", repository="https://github.com/org/consumer", shared_remote=True)
    second["target"].update(factory_id="factory-b")
    second["locks"]["scopes"] = [other_group]
    storage.enrollment["writers"]["writer-b"] = {key: second["route"][key] for key in ("kind", "repository", "shared_remote")}
    binding = copy.deepcopy(storage.enrollment["scopes"][GROUP.lower()])
    binding["writers"], binding["target"]["factory_id"] = ["writer-b"], "factory-b"
    storage.enrollment["scopes"][other_group.lower()] = binding
    storage.enrollment["scopes"][COMMON.lower()]["writers"] = ["writer-a", "writer-b"]
    for document in (first, second):
        document["locks"]["coordination_hash"] = fl.digest(storage.enrollment)
    one, two = fl.BlobLocks(storage, first), fl.BlobLocks(storage, second)
    one.acquire()
    with pytest.raises(fl.Blocked, match="409"):
        two.acquire()
    assert not two.held
    assert fl.BlobLocks.blob_name(COMMON) in storage.leases
    one.release()


@pytest.mark.parametrize("change,code", [
    (lambda e: e.update(revision=5), "lock-enrollment-changed"),
    (lambda e: e["scopes"][GROUP.lower()].update(writers=["writer-a", "writer-b"]), "one-designated"),
    (lambda e: e["scopes"][GROUP.lower()].update(common_dependencies=[]), "common-dependency-locks-mismatch"),
    (lambda e: e.update(enforcement="advisory"), "invalid-lock-enrollment"),
    (lambda e: e["scopes"][GROUP.lower()].update(scope_kind="external-hub"), "physical-target-enrollment"),
    (lambda e: e["scopes"][GROUP.lower()].update(allow_delete=False), "physical-target-deletion-not-enrolled"),
    (lambda e: e["scopes"][GROUP.lower()]["target"].update(suffix="002"), "physical-target-enrollment"),
])
def test_enrollment_prerequisites_are_live_verified(change, code):
    document, storage = manifest(), FakeStorage()
    change(storage.enrollment)
    if code != "lock-enrollment-changed":
        document["locks"]["coordination_hash"] = fl.digest(storage.enrollment)
    with pytest.raises(fl.Blocked, match=code):
        fl.BlobLocks(storage, document).acquire()
    assert not storage.leases


def test_changed_inventory_ownership_and_active_runs_block():
    document = manifest()
    for change, code in [
        (lambda c: c.extra_inventory.append({"id": GROUP + "/providers/Unknown/newResource/unrelated"}), "allowlist"),
        (lambda c: c.bodies[RESOURCE.lower()]["tags"].update({"aifactory.factory_id": "other"}), "inventory-changed"),
        (lambda c: setattr(c, "active", True), "active-or-unknown"),
    ]:
        cloud = FakeCloud()
        change(cloud)
        with pytest.raises(fl.Blocked, match=code):
            fl.verify_inventory(cloud, document)
        assert not cloud.deleted


def test_missing_live_ownership_even_with_matching_body_hash_blocks():
    document, cloud = manifest(), FakeCloud()
    cloud.bodies[RESOURCE.lower()]["tags"] = {}
    document["deletion"]["resources"][0]["body_hash"] = fl.digest(cloud.bodies[RESOURCE.lower()])
    with pytest.raises(fl.Blocked, match="ownership"):
        fl.verify_inventory(cloud, document)


def setup_execute(monkeypatch, workspace):
    monkeypatch.setattr(fl, "verify_source", lambda cloud, root, source: root)
    source = workspace / "version"
    source.mkdir()
    execution = workspace / "run"
    return source, execution, execution / "receipt.json"


def test_exact_delete_persists_receipt_and_preserves_group_and_source(monkeypatch, workspace):
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    original = source / "customer-settings.json"
    original.write_text("untouched", encoding="utf-8")
    document, cloud = manifest(), FakeCloud()
    result = fl.execute(document, source, execution, receipt, cloud=cloud)
    assert result["status"] == "succeeded"
    assert cloud.deleted == [RESOURCE]
    assert GROUP.lower() in cloud.bodies
    assert not cloud.leases
    assert json.loads(receipt.read_text())["deleted_resources"] == [RESOURCE]
    assert original.read_text() == "untouched"
    assert "synthetic-not-a-credential" not in receipt.read_text()
    assert list(execution.iterdir()) == [receipt]
    assert list(source.iterdir()) == [original]
    assert list(cloud.runs.values())[0]["status"] == "succeeded"


def test_partial_failure_retains_distributed_lock_and_no_retry(monkeypatch, workspace):
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    document, cloud = manifest(), FakeCloud()
    cloud.delete_response_uncertain = True
    result = fl.execute(document, source, execution, receipt, cloud=cloud)
    assert result["status"] == "reconciliation-required"
    assert result["pending_resource"] == RESOURCE
    assert len(result["locks_retained"]) == 2 and len(cloud.leases) == 2
    assert result["deleted_resources"] == []
    assert cloud.deleted == [RESOURCE]
    with pytest.raises(fl.Blocked, match="new-isolated-execution"):
        fl.execute(document, source, execution, receipt, cloud=cloud)
    assert cloud.deleted == [RESOURCE]


def test_pre_mutation_failure_releases_locks(monkeypatch, workspace):
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    cloud = FakeCloud()
    cloud.active = True
    result = fl.execute(manifest(), source, execution, receipt, cloud=cloud)
    assert result["status"] == "blocked"
    assert not result["mutation_started"] and not cloud.deleted and not cloud.leases
    assert list(cloud.runs.values())[0]["status"] == "blocked"


def test_queued_remote_run_blocks_before_arm_mutation(monkeypatch, workspace):
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    cloud = FakeCloud()
    cloud.active_run = True
    result = fl.execute(manifest(), source, execution, receipt, cloud=cloud)
    assert result["status"] == "blocked" and result["error_code"] == "active-or-queued-remote-run"
    assert not cloud.deleted and not cloud.leases


def test_ado_active_run_inventory_is_repository_scoped():
    cloud = fl.Cloud(manifest(), command_runner=Mock(), opener=Mock())
    cloud.request = Mock(side_effect=[(200, {}, {"id": IDENTITY}), (200, {}, {"count": 1, "value": [{"id": 7}]})])
    with pytest.raises(fl.Blocked, match="active-or-queued-remote-run"):
        cloud.assert_no_active_runs(enrollment())
    assert "repositoryId=" + IDENTITY in cloud.request.call_args.args[1]
    assert "notStarted" in cloud.request.call_args.args[1]


def test_source_and_execution_cannot_overlap(workspace):
    with pytest.raises(fl.Blocked, match="execution-source-isolation"):
        fl.execute(manifest(), workspace, workspace / "run", workspace / "run/receipt.json", cloud=FakeCloud())


@pytest.mark.parametrize("defect,code", [
    ("dirty", "version-source-dirty"), ("commit", "version-source-commit-mismatch"),
    ("unpublished", "version-no-longer-published"), ("origin", "untrusted-version-source"),
])
def test_source_must_be_clean_exact_published_vendor_commit(workspace, defect, code):
    cloud = Mock()

    def command(argv, cwd=None):
        if argv[1:] == ["rev-parse", "--show-toplevel"]:
            return str(workspace)
        if argv[1] == "rev-parse":
            return "b" * 40 if defect == "commit" else "a" * 40
        if argv[1] == "status":
            return " M bootstrap/lib/helper.py" if defect == "dirty" else ""
        if argv[1] == "remote":
            return "https://example.com/repo" if defect == "origin" else fl.SOURCE_ORIGIN
        if argv[1] == "ls-remote":
            return ("b" if defect == "unpublished" else "a") * 40 + "\trefs/tags/v1.25.0"
        raise AssertionError(argv)

    cloud.command = command
    with pytest.raises(fl.Blocked, match=code):
        fl.verify_source(cloud, workspace, manifest()["source"])


def test_tokens_are_bound_to_expected_object_not_only_subscription(monkeypatch):
    document = manifest()

    def result(oid):
        claims = base64.urlsafe_b64encode(json.dumps({"oid": oid, "tid": TENANT,
                                                     "exp": time.time() + 3600}).encode()).decode().rstrip("=")
        return json.dumps({"accessToken": "header." + claims + ".signature"})

    cloud = fl.Cloud(document, command_runner=Mock(), opener=Mock())
    cloud.command = Mock(return_value=result("dddddddd-dddd-dddd-dddd-dddddddddddd"))
    with pytest.raises(fl.Blocked, match="authenticated-identity-mismatch"):
        cloud.token(fl.ARM)
    assert cloud.tokens == {}
    cloud.command.return_value = result(IDENTITY)
    assert cloud.token(fl.ARM).startswith("header.")
    assert "get-access-token" in cloud.command.call_args.args[0]


def test_inspect_does_not_authenticate_write_or_echo_config(monkeypatch, capsys):
    document = manifest("create-factory")
    pipe = io.TextIOWrapper(io.BytesIO(fl.canonical(document)))
    monkeypatch.setattr(sys, "stdin", pipe)
    assert fl.main(["inspect", "--stdin-manifest"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["manifest_valid"] and not result["execution_supported"]
    assert "config" not in result
    assert "synthetic-not-a-credential" not in str(result)


def test_duplicate_json_keys_are_rejected(monkeypatch):
    pipe = io.TextIOWrapper(io.BytesIO(b'{"schema":1,"schema":2}'))
    monkeypatch.setattr(sys, "stdin", pipe)
    with pytest.raises(fl.Blocked, match="invalid-manifest-json"):
        fl.read_manifest(SimpleNamespace(stdin_manifest=True, protected_manifest=None))


def test_untrusted_service_url_cannot_receive_cached_token():
    cloud = fl.Cloud(manifest(), command_runner=Mock(), opener=Mock())
    cloud.token = Mock(return_value="not-a-real-token")
    with pytest.raises(fl.Blocked, match="untrusted-service"):
        cloud.request("GET", "https://example.com/collect", fl.ARM)
    cloud.token.assert_not_called()
    cloud.opener.open.assert_not_called()


def test_ado_project_exact_commit_secret_and_returned_run(monkeypatch):
    document = manifest("deploy-project")
    calls, receipts = [], []
    receipt = {"mutation_started": False}
    helper = ROOT / "bootstrap/lib/project_deployment.py"
    template_text = {relative: (ROOT / relative).read_text(encoding="utf-8").strip()
                     for relative in fl.ADO_FILES.values()}
    cloud = FakeCloud()
    cloud.command = Mock(side_effect=lambda args, cwd=None:
                         helper.read_text(encoding="utf-8").strip() if args[2].endswith(":bootstrap/lib/project_deployment.py")
                         else template_text[args[2].split(":", 1)[1]])

    def request(method, url, audience, data=None, **kwargs):
        calls.append((method, url, data))
        if "items?path=%2Fazure-enterprise-scale-ml" in url:
            result = {"gitObjectType": "commit", "objectId": document["source"]["commit"]}
        elif "/items?" in url:
            from urllib.parse import parse_qs, urlsplit
            path = parse_qs(urlsplit(url).query)["path"][0].lstrip("/")
            result = {"content": template_text[fl.ADO_FILES[path]]}
        elif "/build/definitions?" in url:
            result = {"value": [{"id": 7, "repository": {"name": "consumer"},
                                 "process": {"yamlFilename": fl.ADO_PIPELINE}}]}
        elif method == "POST":
            result = {"id": 13}
        else:
            assert "/pipelines/7/runs/13?" in url
            result = {"state": "completed", "result": "succeeded",
                      "resources": {"repositories": {"self": {"version": "b" * 40}}}}
        return 200, {}, result

    cloud.request = request
    locks = Mock(spec=fl.BlobLocks)
    locks.enrollment = enrollment()
    fl.ado_project(cloud, locks, document, ROOT, receipt, lambda: receipts.append(copy.deepcopy(receipt)),
                   sleep=Mock(side_effect=AssertionError("Unexpected poll")))
    posted = next(data for method, _, data in calls if method == "POST")
    assert posted["resources"]["repositories"]["self"] == {"refName": "refs/heads/main", "version": "b" * 40}
    assert posted["variables"]["AIFACTORY_CONFIG_JSON"]["isSecret"] is True
    assert posted["templateParameters"]["deploymentTarget"] == "stage"
    assert posted["stagesToSkip"] == ["Dev_GenAI_Project", "Prod_GenAI_Project"]
    assert receipt["remote_run"] == {"kind": "ado", "pipeline_id": 7, "run_id": 13}
    assert receipt["remote_terminal"]
    assert all("synthetic-not-a-credential" not in json.dumps(row) for row in receipts)
    assert all("synthetic-not-a-credential" not in str(args) for args in cloud.command.call_args_list)


def scoped_manifest(projects=(), route="ado", environment="stage", operation="create-scaleset"):
    document = manifest(operation)
    document["target"].update(project_ids=list(projects), environment=environment)
    document["identity"]["deployment_object_id"] = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    document["route"].update(scoped_contract=1, auth_namespace="factory-a-Stage001-" + environment,
                             kind=route, shared_remote=True, runner={"kind": "hosted", "os": "linux", "image": "ubuntu-latest"})
    if route == "gha":
        document["route"].update(repository="https://github.com/org/consumer", github_user_id=71)
    steps = []
    templates = {}
    selected = [(name, path, None) for name, path in fl.COMMON_TEMPLATES.items()]
    if operation == "deploy-project":
        selected = []
    for project in projects:
        selected.append(("project" + project, "environment_setup/aifactory/bicep/esml-genai-1/01-foundation.bicep", project))
    for name, path, project in selected:
        tags = {fl.TAG_KEYS[key]: document["target"][key] for key in ("factory_id", "scaleset_id")}
        parameters = {"env": "test" if environment == "stage" else environment, "location": "eastus2",
                      "commonRGNamePrefix": "acme-ai-", "aifactorySuffixRG": "-001", "tags": tags}
        if project:
            parameters["projectNumber"] = project
            tags[fl.TAG_KEYS["project_id"]] = project
        compiled = {"$schema": "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentTemplate.json#",
                    "parameters": {key: {"type": "object" if key == "tags" else "string"} for key in parameters},
                    "resources": []}
        templates[path] = compiled
        step = {"id": name, "kind": "project" if project else "common", "template": path,
                "template_hash": fl.digest(compiled), "parameters": parameters,
                "scope": "subscription", "resource_groups": [GROUP],
                "depends_on": [steps[-1]["id"]] if steps else [],
                "changes": [{"resource_id": RESOURCE.lower(), "change_type": "Modify",
                             "before_hash": fl.digest(RESOURCE_BODY), "after_hash": fl.digest(RESOURCE_BODY)}]}
        if project:
            step["project_id"] = project
        steps.append(step)
    document["deployment"] = {"contract": 1, "configuration_hash": fl.digest(document["config"]),
                               "network_mode": "managed", "steps": steps, "changes": copy.deepcopy(steps[0]["changes"])}
    return seal(document), templates


def scoped_enrollment(document):
    result = enrollment()
    route, identity = document["route"], document["identity"]
    result["writers"][route["writer_id"]] = {key: route[key] for key in (
        "kind", "repository", "shared_remote", "auth_namespace", "runner")}
    result["writers"][route["writer_id"]]["deployment_object_id"] = identity["deployment_object_id"]
    result["scopes"][GROUP.lower()]["target"] = {key: value for key, value in document["target"].items() if key != "project_ids"}
    return result


@pytest.mark.parametrize("environment", ["dev", "stage", "prod"])
@pytest.mark.parametrize("projects", [(), ("017",), ("017", "019")])
def test_scoped_creation_supports_selected_environment_and_exact_project_set(environment, projects):
    document, _ = scoped_manifest(projects, environment=environment)
    fl.validate_manifest(document)
    assert fl.operation_blockers(document) == []
    common = [step for step in document["deployment"]["steps"] if step["kind"] == "common"]
    assert len(common) == 3 and all("projectNumber" not in step["parameters"] for step in common)
    assert [step["project_id"] for step in document["deployment"]["steps"] if step["kind"] == "project"] == list(projects)


@pytest.mark.parametrize("change,code", [
    (lambda d: d["deployment"]["steps"][0]["parameters"].update(env="dev"), "arm-plan-target-mismatch"),
    (lambda d: d["deployment"]["steps"][0]["parameters"].update(projectNumber="001"), "common-only-project-leak"),
    (lambda d: d["deployment"]["steps"].pop(), "common-foundation-plan-incomplete"),
    (lambda d: d["config"].update(changed=True), "frozen-deployment-plan-required"),
    (lambda d: d["deployment"]["steps"][0].update(template="../other.bicep"), "canonical-deployment-template"),
    (lambda d: d["deployment"]["steps"][0]["changes"][0].update(change_type="Delete"), "destructive-or-unknown"),
    (lambda d: d["target"].update(project_ids=["019"]), "selected-project-plan-incomplete"),
])
def test_scoped_plan_does_not_drop_settings_or_fabricate_projects(change, code):
    document, _ = scoped_manifest()
    change(document)
    with pytest.raises(fl.Blocked, match=code):
        fl.validate_manifest(seal(document))


class PlanCloud(FakeCloud):
    def __init__(self, document, templates):
        super().__init__()
        self.enrollment = scoped_enrollment(document)
        self.templates = templates
        self.document = document
        self.arm_writes = []
        self.bodies[GROUP.lower()]["tags"] = {fl.TAG_KEYS[key]: document["target"][key] for key in ("factory_id", "scaleset_id")}
        self.bodies[RESOURCE.lower()]["tags"] = {fl.TAG_KEYS[key]: document["target"][key] for key in ("factory_id", "scaleset_id")}
        self.what_if_changed = False

    def compile_template(self, root, template):
        return copy.deepcopy(self.templates[template])

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if url.startswith(fl.ARM):
            if "/whatIf?" in url:
                change = {"resourceId": RESOURCE, "changeType": "Modify", "before": RESOURCE_BODY, "after": RESOURCE_BODY}
                if self.what_if_changed:
                    change["resourceId"] = GROUP + "/providers/Unrelated/resource/outside"
                return 200, {}, {"properties": {"changes": [change]}}
            if method == "PUT":
                self.arm_writes.append((url, copy.deepcopy(data)))
                for project in self.document["target"]["project_ids"]:
                    body = copy.deepcopy(self.bodies[RESOURCE.lower()])
                    body["id"] = RESOURCE + "-" + project
                    body["tags"][fl.TAG_KEYS["project_id"]] = project
                    self.bodies[body["id"].lower()] = body
                return 201, {}, {}
            return 200, {}, {"properties": {"provisioningState": "Succeeded"}}
        return super().request(method, url, audience, data, headers, allowed)


def simple_plan_closure(cloud, scopes):
    resources = {key: body for key, body in cloud.bodies.items() if key != GROUP.lower()}
    return ({"providers": {}, "collections": {}, "groups": {GROUP.lower(): {}},
             "resources": {key: {"type": "microsoft.network/publicipaddresses", "api_version": "2024-05-01",
                                 "body_hash": fl.digest(body), "etag": body["etag"]} for key, body in resources.items()}},
            {GROUP.lower(): cloud.bodies[GROUP.lower()], **resources})


@pytest.mark.parametrize("projects", [(), ("017", "019")])
def test_worker_executes_common_only_or_exact_selected_projects_under_shared_leases(monkeypatch, projects):
    document, templates = scoped_manifest(projects)
    cloud = PlanCloud(document, templates)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                     ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert result["status"] == "succeeded"
    assert len(cloud.arm_writes) == 1
    assert len(cloud.arm_writes[0][1]["properties"]["template"]["resources"]) == 3 + len(projects)
    assert [step["step_id"] for step in result["deployments"]] == [step["id"] for step in document["deployment"]["steps"]]
    assert result["resource_groups"] == [{
        "resource_id": GROUP.lower(), "owner": {key: document["target"][key] for key in ("factory_id", "scaleset_id")},
        "body_hash": fl.digest(cloud.bodies[GROUP.lower()]), "etag": None,
    }]
    for url, payload in cloud.arm_writes:
        assert payload["properties"]["mode"] == "Incremental"
        assert document["target"]["subscription_id"] in url
    assert not any("synthetic-not-a-credential" in str(value) for value in result.values())
    assert cloud.leases  # Only the coordinator releases after verifying the remote receipt.


def test_worker_blocks_changed_what_if_before_any_arm_write(monkeypatch):
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    cloud.what_if_changed = True
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                     ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "arm-what-if-changed-since-prepare"
    assert not cloud.arm_writes


def test_parameter_completeness_is_checked_against_compiled_canonical_template():
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    step = document["deployment"]["steps"][0]
    template = templates[step["template"]]
    template["parameters"]["newRequiredSetting"] = {"type": "string"}
    step["template_hash"] = fl.digest(template)
    with pytest.raises(fl.Blocked, match="parameters-not-fully-resolved"):
        fl.compiled_plan_step(cloud, document, step, ROOT)


NSG = GROUP + "/providers/Microsoft.Network/networkSecurityGroups/owned-nsg"
RULE = NSG + "/securityRules/owned-rule"
CORE_OWNER = {key: OWNER[key] for key in ("factory_id", "scaleset_id")}


class ClosureCloud(FakeCloud):
    def __init__(self):
        super().__init__()
        self.bodies = {
            GROUP.lower(): {**GROUP_BODY, "tags": {fl.TAG_KEYS[key]: value for key, value in CORE_OWNER.items()}},
            NSG.lower(): {"id": NSG, "type": "Microsoft.Network/networkSecurityGroups", "etag": '"nsg"',
                          "tags": {fl.TAG_KEYS[key]: value for key, value in CORE_OWNER.items()}, "properties": {}},
            RULE.lower(): {"id": RULE, "type": "Microsoft.Network/networkSecurityGroups/securityRules",
                           "etag": '"rule"', "properties": {"priority": 100}},
        }

    def provider_schema(self, namespace):
        return {"resourceTypes": [
            {"resourceType": "networkSecurityGroups", "apiVersions": ["2024-05-01"]},
            {"resourceType": "networkSecurityGroups/securityRules", "apiVersions": ["2024-05-01"]},
        ]}

    def list_resources(self, scope):
        return [copy.deepcopy(self.bodies[NSG.lower()])] + self.extra_inventory

    def collection(self, path, api_version, extension=False):
        if path.lower() == NSG.lower() + "/securityrules":
            return [copy.deepcopy(self.bodies[RULE.lower()])], None
        assert extension
        return [], None

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "DELETE" and resource_id.lower() == GROUP.lower():
            fl.require(not self.fail_delete, "remote-request-failed-409")
            self.deleted.append(resource_id)
            self.bodies = {key: body for key, body in self.bodies.items() if fl.arm_scope(key) != GROUP.lower()}
            return 202, {}, None
        return super().arm(method, resource_id, api_version, allowed, headers)


class CohortCloud(ClosureCloud):
    """The real closure collector and BlobLocks protocol over multiple fake RGs."""

    def __init__(self):
        super().__init__()
        self.before_delete = lambda resource_id: None
        self.after_delete = lambda resource_id: None

    def list_resources(self, scope):
        return [copy.deepcopy(body) for key, body in self.bodies.items()
                if fl.arm_scope(key) == scope.lower()
                and body.get("type", "").lower() == "microsoft.network/networksecuritygroups"]

    def collection(self, path, api_version, extension=False):
        if path.lower().endswith("/securityrules"):
            return [copy.deepcopy(body) for key, body in self.bodies.items()
                    if key.startswith(path.lower() + "/")], None
        assert extension
        return [], None

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "DELETE" and fl.RG_ID.fullmatch(resource_id):
            self.before_delete(resource_id)
            fl.require(not self.fail_delete, "remote-request-failed-409")
            self.deleted.append(resource_id)
            self.bodies = {key: body for key, body in self.bodies.items()
                           if fl.arm_scope(key) != resource_id.lower()}
            self.after_delete(resource_id)
            fl.require(not self.delete_response_uncertain, "remote-request-unverified")
            return 202, {}, None
        return super().arm(method, resource_id, api_version, allowed, headers)


def refresh_cohort(documents, cloud):
    for document in documents:
        document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
        document["deletion"] = fl.freeze_deletion_inventory(cloud, document, {})
        seal(document)
    cloud.calls.clear()


def cohort_fixture(other_subscription=False):
    cloud = CohortCloud()
    cloud.bodies[RULE.lower()]["tags"] = copy.deepcopy(cloud.bodies[NSG.lower()]["tags"])
    other_group = GROUP + "-two"
    if other_subscription:
        other_group = other_group.replace(SUB, "dddddddd-dddd-dddd-dddd-dddddddddddd")
    for body in list(cloud.bodies.values()):
        clone = json.loads(json.dumps(body).replace(GROUP, other_group).replace("Stage001", "Prod002"))
        cloud.bodies[clone["id"].lower()] = clone
    first, second = manifest(), manifest()
    second["target"].update(scaleset_id="Prod002", environment="prod", suffix="002",
                            subscription_id=fl.arm_scope(other_group).split("/")[2])
    second["route"].update(kind="gha", writer_id="writer-b", repository="https://github.com/org/consumer",
                           shared_remote=True)
    second["locks"]["scopes"] = [other_group]
    cloud.enrollment["writers"]["writer-b"] = {
        key: second["route"][key] for key in ("kind", "repository", "shared_remote")}
    binding = copy.deepcopy(cloud.enrollment["scopes"][GROUP.lower()])
    binding["target"] = {key: second["target"][key] for key in binding["target"]}
    binding["writers"] = ["writer-b"]
    cloud.enrollment["scopes"][other_group.lower()] = binding
    cloud.enrollment["scopes"][COMMON.lower()]["writers"] = ["writer-a", "writer-b"]
    documents = [first, second]
    refresh_cohort(documents, cloud)
    return documents, cloud


def owned_group_manifest(cloud):
    document = manifest()
    closure, bodies = fl.collect_resource_closure(cloud, [GROUP])
    evidence_run = str(uuid4())
    evidence = {"schema": 1, "status": "succeeded", "run_id": evidence_run, "manifest_hash": "e" * 64,
                "target": CORE_OWNER, "ownership": [{"resource_id": RULE, "owner": CORE_OWNER,
                                                    "body_hash": fl.digest(cloud.bodies[RULE.lower()])}]}
    cloud.runs["runs/" + evidence_run + ".worker.json"] = evidence
    resources = []
    for resource_id, row in closure["resources"].items():
        item = {"id": resource_id, **row, "delete": True, "owner": copy.deepcopy(CORE_OWNER),
                "depends_on": [NSG.lower()] if resource_id == RULE.lower() else []}
        if resource_id == RULE.lower():
            item.update(ownership_source="deployment-receipt",
                        ownership_evidence={"run_id": evidence_run, "receipt_hash": fl.digest(evidence)})
        resources.append(item)
    document["deletion"] = {"inventory_mode": "arm-provider-closure-v1", "inventory_complete": True, "revision": 3,
                             "resources": resources, "inventory_hash": fl.digest(resources),
                             "resource_groups": [{"id": GROUP, **closure["groups"][GROUP.lower()],
                                                  "delete": True, "owner": CORE_OWNER}],
                             "closure": closure, "closure_hash": fl.digest(closure)}
    return seal(document)


def test_cohort_holds_union_and_all_claims_before_first_delete_and_releases_once(monkeypatch, workspace):
    documents, cloud = cohort_fixture(other_subscription=True)
    original = copy.deepcopy(documents)
    source, execution, path = setup_execute(monkeypatch, workspace)
    scopes = sorted({scope.lower() for document in documents for scope in
                     document["locks"]["scopes"] + document["locks"]["common_dependencies"]})

    def before_delete(resource_id):
        assert set(cloud.leases) == {fl.BlobLocks.blob_name(scope) for scope in scopes}
        assert all("runs/" + document["run_id"] + ".claim.json" in cloud.runs for document in documents)
        assert all(cloud.runs["runs/" + document["run_id"] + ".json"]["status"] in ("running", "succeeded")
                   for document in documents)

    cloud.before_delete = before_delete
    result = fl.execute_cohort(list(reversed(documents)), source, execution, path, cloud_factory=lambda d: cloud)
    assert result["status"] == "succeeded" and not result["lock_retained"] and not cloud.leases
    assert result["cohort_hash"] == fl.digest(sorted(document["manifest_hash"] for document in documents))
    assert [child["manifest_hash"] for child in result["children"]] == sorted(d["manifest_hash"] for d in documents)
    for action in ("acquire", "release"):
        requests = [url for _, url, _, headers in cloud.calls if headers.get("x-ms-lease-action") == action]
        expected = scopes if action == "acquire" else list(reversed(scopes))
        assert requests == ["https://lockstore.blob.core.windows.net/factory-locks/" +
                            fl.BlobLocks.blob_name(scope) + "?comp=lease" for scope in expected]
    assert json.loads(path.read_text()) == result
    assert documents == original and not cloud.bodies
    for child in result["children"]:
        assert child["status"] == "succeeded" and child["source_commit"] == documents[0]["source"]["commit"]
        assert json.loads((execution / (child["run_id"] + ".receipt.json")).read_text()) == child
        assert cloud.runs["runs/" + child["run_id"] + ".json"] == child
    assert all("synthetic-not-a-credential" not in item.read_text() for item in execution.iterdir())


def test_cohort_deletes_dependents_first_even_after_all_consent_deadlines(monkeypatch, workspace):
    documents, cloud = cohort_fixture()
    other_group = documents[1]["locks"]["scopes"][0]
    documents[0]["locks"]["common_dependencies"].append(other_group)
    cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"].append(other_group.lower())
    cloud.bodies[NSG.lower()]["properties"]["peer"] = other_group + "/providers/Microsoft.Network/networkSecurityGroups/owned-nsg"
    refresh_cohort(documents, cloud)
    frozen = copy.deepcopy(documents)
    future = max(fl.timestamp(d["expires_at"]) for d in documents) + 60
    cloud.after_delete = lambda resource_id: monkeypatch.setattr(fl.time, "time", lambda: future)
    source, execution, path = setup_execute(monkeypatch, workspace)
    result = fl.execute_cohort(documents[::-1], source, execution, path, cloud_factory=lambda d: cloud)
    assert result["status"] == "succeeded"
    assert cloud.deleted == [GROUP, other_group]
    assert documents == frozen
    with pytest.raises(fl.Blocked, match="manifest-expired"):
        fl.validate_manifest(documents[1])
    assert all(child["execution_claim"]["accepted_at"] < documents[0]["expires_at"] for child in result["children"])


@pytest.mark.parametrize("defect,code", [
    ("expired", "manifest-expired"), ("hash", "manifest-hash-mismatch"),
    ("factory", "cohort-factory-mismatch"), ("source", "cohort-source-mismatch"),
    ("ref", "cohort-source-mismatch"), ("duplicate", "cohort-duplicate-child"),
    ("duplicate-scope", "cohort-duplicate-writable-scope"), ("operation", "cohort-whole-owned-groups-required"),
    ("shared-store", "cohort-shared-scope-authority-mismatch"),
    ("cross-tenant-shared", "cohort-shared-scope-cross-tenant-auth-unsupported"),
])
def test_invalid_cohort_never_acquires_or_deletes(monkeypatch, workspace, defect, code):
    documents, cloud = cohort_fixture()
    if defect == "expired":
        end = time.time() - 1
        documents[1]["prepared_at"] = datetime.fromtimestamp(end - 100, timezone.utc).isoformat()
        documents[1]["expires_at"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
    elif defect == "hash":
        documents[1]["config"]["secret"] = "tampered"
    elif defect == "factory":
        documents[1]["target"]["factory_id"] = "another"
        for row in documents[1]["deletion"]["resources"] + documents[1]["deletion"]["resource_groups"]:
            row["owner"]["factory_id"] = "another"
        documents[1]["deletion"]["inventory_hash"] = fl.digest(documents[1]["deletion"]["resources"])
    elif defect == "source":
        documents[1]["source"]["commit"] = "d" * 40
    elif defect == "ref":
        documents[1]["source"]["ref"] = "refs/heads/advanced"
    elif defect == "duplicate":
        documents[1] = copy.deepcopy(documents[0])
    elif defect == "duplicate-scope":
        documents[1] = copy.deepcopy(documents[0])
        documents[1]["run_id"] = str(uuid4())
    elif defect == "operation":
        documents[1]["operation"] = "create-factory"
    elif defect == "shared-store":
        documents[1]["locks"]["account_url"] = "https://otherstore.blob.core.windows.net"
    else:
        documents[1]["target"]["tenant_id"] = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    if defect != "hash":
        seal(documents[1])
    source, execution, path = setup_execute(monkeypatch, workspace)
    with pytest.raises(fl.Blocked, match=code):
        fl.execute_cohort(documents, source, execution, path, cloud_factory=lambda d: cloud)
    assert not cloud.deleted and not cloud.leases and not cloud.runs
    assert not any(headers.get("x-ms-lease-action") == "acquire" for _, _, _, headers in cloud.calls)


@pytest.mark.parametrize("defect", ["enrollment", "inventory", "source", "identity"])
def test_cohort_checks_every_child_before_claim_or_resource_write(monkeypatch, workspace, defect):
    documents, cloud = cohort_fixture()
    source, execution, path = setup_execute(monkeypatch, workspace)
    if defect == "enrollment":
        cloud.enrollment["scopes"][documents[1]["locks"]["scopes"][0].lower()]["allow_delete"] = False
    elif defect == "inventory":
        cloud.bodies[documents[1]["locks"]["scopes"][0].lower()]["tags"][fl.TAG_KEYS["factory_id"]] = "changed"
    elif defect == "source":
        monkeypatch.setattr(fl, "verify_source", Mock(side_effect=fl.Blocked("source-unavailable")))
    else:
        cloud.verify_identity = Mock(side_effect=[None, fl.Blocked("authenticated-identity-mismatch")])
    result = fl.execute_cohort(documents, source, execution, path, cloud_factory=lambda d: cloud)
    assert result["status"] == "blocked" and not result["lock_retained"]
    assert not cloud.deleted and not cloud.runs and not cloud.leases


@pytest.mark.parametrize("failure", ["uncertain", "claim-lost", "lease-lost", "tamper"])
def test_cohort_partial_failure_retains_union_and_all_child_receipts(monkeypatch, workspace, failure):
    documents, cloud = cohort_fixture()
    source, execution, path = setup_execute(monkeypatch, workspace)
    originals = {}

    def factory(document):
        originals[document["run_id"]] = document
        return cloud

    def fail_after_first(resource_id):
        pending = next(d for d in originals.values() if d["locks"]["scopes"][0] != resource_id)
        if failure == "uncertain":
            cloud.delete_response_uncertain = True
        elif failure == "claim-lost":
            del cloud.runs["runs/" + pending["run_id"] + ".claim.json"]
        elif failure == "lease-lost":
            cloud.leases[fl.BlobLocks.blob_name(COMMON)] = str(uuid4())
        else:
            pending["config"]["secret"] = "tampered-after-claim"
            seal(pending)

    cloud.after_delete = fail_after_first
    result = fl.execute_cohort(documents, source, execution, path, cloud_factory=factory)
    assert result["status"] == "reconciliation-required" and result["lock_retained"]
    assert len(cloud.deleted) == 1 and len(cloud.leases) == 3 and len(result["locks_retained"]) == 3
    assert not any(headers.get("x-ms-lease-action") == "release" for _, _, _, headers in cloud.calls)
    assert len(result["children"]) == 2
    for child in result["children"]:
        assert child["lock_retained"] and len(child["locks_retained"]) == 3
        assert json.loads((execution / (child["run_id"] + ".receipt.json")).read_text()) == child
    assert json.loads(path.read_text()) == result
    with pytest.raises(fl.Blocked, match="new-isolated-execution"):
        fl.execute_cohort(documents, source, execution, path, cloud_factory=lambda d: cloud)


def test_cohort_claim_replay_blocks_all_mutations_and_preserves_existing_claim(monkeypatch, workspace):
    documents, cloud = cohort_fixture()
    document = documents[1]
    cloud.runs["runs/" + document["run_id"] + ".json"] = {"state": "existing-authority"}
    source, execution, path = setup_execute(monkeypatch, workspace)
    result = fl.execute_cohort(documents, source, execution, path, cloud_factory=lambda d: cloud)
    assert result["status"] == "reconciliation-required" and result["lock_retained"]
    assert not cloud.deleted and len(cloud.leases) == 3
    assert cloud.runs["runs/" + document["run_id"] + ".json"] == {"state": "existing-authority"}


def test_cohort_dependency_cycle_blocks_before_any_claim_or_lease(monkeypatch, workspace):
    documents, cloud = cohort_fixture()
    for document, other in zip(documents, documents[::-1]):
        document["locks"]["common_dependencies"].append(other["locks"]["scopes"][0])
        cloud.enrollment["scopes"][document["locks"]["scopes"][0].lower()]["common_dependencies"] = [
            scope.lower() for scope in document["locks"]["common_dependencies"]]
    refresh_cohort(documents, cloud)
    source, execution, path = setup_execute(monkeypatch, workspace)
    with pytest.raises(fl.Blocked, match="cyclic-deletion-dependencies"):
        fl.execute_cohort(documents, source, execution, path, cloud_factory=lambda d: cloud)
    assert not cloud.leases and not cloud.runs and not cloud.deleted


def test_cohort_expiry_during_preclaim_has_no_resource_writes(monkeypatch, workspace):
    documents, cloud = cohort_fixture()
    source, execution, path = setup_execute(monkeypatch, workspace)
    request = cloud.request
    future = max(fl.timestamp(d["expires_at"]) for d in documents) + 60

    def slow_claim(method, url, audience, data=None, headers=None, allowed=(200,)):
        result = request(method, url, audience, data, headers, allowed)
        if method == "PUT" and url.endswith(".claim.json"):
            monkeypatch.setattr(fl.time, "time", lambda: future)
        return result

    cloud.request = slow_claim
    result = fl.execute_cohort(documents, source, execution, path, cloud_factory=lambda d: cloud)
    assert result["status"] == "reconciliation-required" and result["lock_retained"]
    assert not cloud.deleted and len(cloud.leases) == 3


def test_disjoint_tenants_use_independently_verified_scope_and_store_contexts(monkeypatch, workspace):
    documents, cloud = cohort_fixture(other_subscription=True)
    second = documents[1]
    second["target"]["tenant_id"] = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    second["identity"]["object_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    second["locks"]["account_url"] = "https://otherstore.blob.core.windows.net"
    dependency = second["locks"]["scopes"][0] + "-common"
    second["locks"]["common_dependencies"] = [dependency]
    binding = cloud.enrollment["scopes"][second["locks"]["scopes"][0].lower()]
    binding["target"]["tenant_id"] = second["target"]["tenant_id"]
    binding["common_dependencies"] = [dependency.lower()]
    cloud.enrollment["scopes"][dependency.lower()] = {"writers": ["writer-b"], "common_dependencies": []}
    refresh_cohort(documents, cloud)
    contexts = []
    source, execution, path = setup_execute(monkeypatch, workspace)

    def factory(document):
        contexts.append((document["target"]["tenant_id"], document["target"]["subscription_id"],
                         document["identity"]["object_id"]))
        return cloud

    result = fl.execute_cohort(documents, source, execution, path, cloud_factory=factory)
    assert result["status"] == "succeeded"
    assert set(contexts) == {(d["target"]["tenant_id"], d["target"]["subscription_id"], d["identity"]["object_id"])
                             for d in documents}
    acquisitions = [url for _, url, _, headers in cloud.calls if headers.get("x-ms-lease-action") == "acquire"]
    assert len(acquisitions) == 4
    assert sum(url.startswith(second["locks"]["account_url"]) for url in acquisitions) == 2


def test_whole_group_absence_polling_outlasts_the_leaf_budget():
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    arm = cloud.arm
    polls = 0

    def delayed_absence(method, resource_id, *args, **kwargs):
        nonlocal polls
        polls += 1
        if polls == 131:
            del cloud.bodies[resource_id.lower()]
        return arm(method, resource_id, *args, **kwargs)

    cloud.arm = delayed_absence
    pause = Mock()
    fl.wait_absent(cloud, locks, GROUP, fl.RG_API, pause)
    assert polls == 131 and pause.call_count == 130
    assert cloud.leases


@pytest.mark.parametrize("changed", [False, True])
def test_accepted_source_keeps_exact_checkout_without_reresolving_a_moving_ref(workspace, changed):
    source = manifest()["source"]
    cloud = FakeCloud()
    commands = []

    def command(argv, cwd=None):
        commands.append(argv)
        if argv[1:] == ["rev-parse", "--show-toplevel"]:
            return str(workspace)
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "b" * 40 if changed else source["commit"]
        if argv[1] == "status":
            return ""
        if argv[1] == "remote":
            return fl.SOURCE_ORIGIN
        if argv[1] == "show":
            return Path(fl.__file__).read_text(encoding="utf-8").strip()
        raise AssertionError("Accepted source must not fetch, checkout, or query its moving ref")

    cloud.command = command
    if changed:
        with pytest.raises(fl.Blocked, match="version-source-commit-mismatch"):
            fl._verify_source(cloud, workspace, source, published=False)
    else:
        assert fl._verify_source(cloud, workspace, source, published=False) == workspace
    assert not any(argv[1] in ("ls-remote", "fetch", "checkout") for argv in commands)


def test_single_delete_claim_survives_deadline_between_resource_writes(monkeypatch, workspace):
    document, cloud = manifest(), FakeCloud()
    second = copy.deepcopy(document["deletion"]["resources"][0])
    second["id"] += "-second"
    body = copy.deepcopy(RESOURCE_BODY)
    body["id"] = second["id"]
    second["body_hash"] = fl.digest(body)
    cloud.bodies[second["id"].lower()] = body
    document["deletion"]["resources"].append(second)
    document["deletion"]["inventory_hash"] = fl.digest(document["deletion"]["resources"])
    seal(document)
    arm = cloud.arm
    future = fl.timestamp(document["expires_at"]) + 60

    def slow_delete(method, *args, **kwargs):
        result = arm(method, *args, **kwargs)
        if method == "DELETE":
            monkeypatch.setattr(fl.time, "time", lambda: future)
        return result

    cloud.arm = slow_delete
    source, execution, path = setup_execute(monkeypatch, workspace)
    result = fl.execute(document, source, execution, path, cloud=cloud)
    assert result["status"] == "succeeded" and len(cloud.deleted) == 2
    assert not cloud.leases


def test_single_delete_rejects_document_changed_during_last_mutation(monkeypatch, workspace):
    document, cloud = manifest(), FakeCloud()
    source, execution, path = setup_execute(monkeypatch, workspace)
    holders = []

    def lock_factory(cloud, document):
        locks = fl.BlobLocks(cloud, document)
        holders.append(locks)
        return locks

    arm = cloud.arm

    def tamper_after_write(method, *args, **kwargs):
        result = arm(method, *args, **kwargs)
        if method == "DELETE":
            holders[0].document["config"]["secret"] = "changed-after-final-write"
            seal(holders[0].document)
        return result

    cloud.arm = tamper_after_write
    result = fl.execute(document, source, execution, path, cloud=cloud, lock_factory=lock_factory)
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "claimed-manifest-changed" and len(cloud.leases) == 2


def test_execution_claim_is_frozen_live_and_not_a_timestamp_override(monkeypatch):
    document, cloud = manifest(), FakeCloud()
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    future = fl.timestamp(document["expires_at"]) + 60
    monkeypatch.setattr(fl.time, "time", lambda: future)
    locks.authorize(document)
    with pytest.raises(fl.Blocked, match="manifest-expired"):
        fl.validate_manifest(document)
    changed = copy.deepcopy(document)
    changed["config"]["secret"] = "changed"
    with pytest.raises(fl.Blocked, match="claimed-manifest-changed"):
        locks.authorize(seal(changed))
    fresh_locks = fl.BlobLocks(cloud, document)
    fresh_locks.held = copy.deepcopy(locks.held)
    with pytest.raises(fl.Blocked, match="manifest-expired"):
        fresh_locks.authorize(document)
    fresh_locks.execution_claim = {"accepted_at": document["prepared_at"], "status": "succeeded"}
    with pytest.raises(fl.Blocked, match="verified-execution-claim-required"):
        fresh_locks.authorize(document)
    cloud.runs["runs/" + document["run_id"] + ".json"]["state"] = "cancelled"
    with pytest.raises(fl.Blocked, match="execution-claim-not-active"):
        locks.authorize(document)


def test_root_execute_cannot_echo_a_past_approval_time(monkeypatch, workspace):
    document, cloud = manifest(), FakeCloud()
    document["accepted_at"] = document["prepared_at"]
    document["execution_claim"] = {"accepted_at": document["prepared_at"]}
    seal(document)
    source, execution, path = setup_execute(monkeypatch, workspace)
    monkeypatch.setattr(fl.time, "time", lambda: fl.timestamp(document["expires_at"]) + 60)
    with pytest.raises(fl.Blocked, match="manifest-expired"):
        fl.execute(document, source, execution, path, cloud=cloud)
    with pytest.raises(TypeError):
        fl.execute(document, source, execution, path, cloud=cloud, now=fl.timestamp(document["prepared_at"]))
    assert not cloud.calls and not cloud.deleted


@pytest.mark.parametrize("defect", [None, "missing", "lease", "manifest", "completed", "timestamp"])
def test_queued_worker_requires_live_parent_claim_not_envelope_assertions(monkeypatch, defect):
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    if defect != "missing":
        locks.claim_run()
    envelope = json.loads(fl.protected_worker_envelope(document, locks))
    envelope["accepted_at"] = document["prepared_at"]
    envelope["execution_claim"] = {"accepted_at": document["prepared_at"], "status": "succeeded"}
    if defect == "lease":
        cloud.leases[fl.BlobLocks.blob_name(GROUP)] = str(uuid4())
    elif defect == "manifest":
        envelope["manifest"]["config"]["secret"] = "modified"
        seal(envelope["manifest"])
    elif defect == "completed":
        cloud.runs["runs/" + document["run_id"] + ".json"] = {"status": "succeeded"}
    elif defect == "timestamp":
        cloud.runs["runs/" + document["run_id"] + ".claim.json"]["accepted_at"] = document["expires_at"]
    monkeypatch.setattr(fl.time, "time", lambda: fl.timestamp(document["expires_at"]) + 60)
    verifier = Mock(side_effect=lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "_verify_source", verifier)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    if defect:
        with pytest.raises(fl.Blocked):
            fl.run_deployment_worker(envelope, ROOT, document["run_id"], envelope["manifest"]["manifest_hash"],
                                     cloud=cloud, sleep=Mock())
        assert not cloud.arm_writes and not verifier.called
    else:
        result = fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"],
                                         cloud=cloud, sleep=Mock())
        assert result["status"] == "succeeded" and len(cloud.arm_writes) == 1
        verifier.assert_called_once_with(cloud, ROOT, document["source"], published=False)
        with pytest.raises(fl.Blocked, match="412"):
            fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"],
                                     cloud=cloud, sleep=Mock())
        assert len(cloud.arm_writes) == 1


def test_full_resource_group_deletion_covers_owned_parent_child_and_extensions(monkeypatch, workspace):
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    fl.validate_manifest(document)
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    result = fl.execute(document, source, execution, receipt, cloud=cloud)
    assert result["status"] == "succeeded"
    assert cloud.deleted == [GROUP]
    assert {value.lower() for value in result["deleted_resources"]} == {GROUP.lower(), NSG.lower(), RULE.lower()}
    assert not cloud.bodies and not cloud.leases


@pytest.mark.parametrize("change,code", [
    (lambda d, c: c.bodies[RULE.lower()]["properties"].update(priority=200), "closure-changed"),
    (lambda d, c: c.bodies[NSG.lower()]["tags"].update({"aifactory.factory_id": "unrelated"}), "closure-changed"),
    (lambda d, c: d["deletion"]["resources"].pop(), "unlisted-child"),
    (lambda d, c: c.runs.clear(), "404"),
    (lambda d, c: d["deletion"]["resource_groups"][0].update(owner={"factory_id": "other", "scaleset_id": "Stage001"}),
     "owned-resource-group-required"),
])
def test_full_group_delete_rejects_changed_unrelated_or_unowned_children(change, code):
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    change(document, cloud)
    document["deletion"]["inventory_hash"] = fl.digest(document["deletion"]["resources"])
    seal(document)
    with pytest.raises(fl.Blocked, match=code):
        fl.validate_manifest(document)
        fl.verify_full_inventory(cloud, document)
    assert not cloud.deleted


def test_scoped_templates_guard_commits_and_use_protected_input():
    for route in ("gha", "ado"):
        text = (ROOT / "bootstrap/templates" / ("factory-lifecycle-" + route + ".yml")).read_text()
        data = yaml.safe_load(text)
        assert fl.SCOPED_CONTRACT in text
        assert "--expected-manifest-hash" in text and "input=raw" in text
        assert "persist-credentials: false" in text or "persistCredentials: false" in text
        assert "print(raw)" not in text and "set -x" not in text
        if route == "gha":
            steps = data["jobs"]["scoped-deployment"]["steps"]
            assert "WORKFLOW_COMMIT" in steps[0]["run"]
            assert any(step.get("uses") == "azure/login@v2" for step in steps)
            worker_step = next(step for step in steps if "AIFACTORY_ENVELOPE_15" in step.get("env", {}))
            assert worker_step["env"]["AIFACTORY_ENVELOPE_15"].endswith("}}")
            assert "AZURE_CONFIG_DIR" in data["jobs"]["scoped-deployment"]["env"]
            assert "always()" in steps[-1]["if"]
            script = worker_step["run"]
            for step in steps:
                if step.get("run", "").startswith("python3 - <<'PY'"):
                    compile(step["run"].split("\n", 1)[1].rsplit("\nPY", 1)[0], "isolated-auth-profile", "exec")
        else:
            script = data["steps"][-1]["inputs"]["inlineScript"]
        compile(script.split("\n", 1)[1].rsplit("\nPY", 1)[0], "protected-worker-transport", "exec")


def successful_worker_receipt(document):
    return {"schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
            "source_commit": document["source"]["commit"], "target": document["target"], "status": "succeeded",
            "deployments": [{"step_id": step["id"], "status": "succeeded"} for step in document["deployment"]["steps"]],
            "ownership": [{"resource_id": RESOURCE, "owner": CORE_OWNER}],
            "resource_groups": [{"resource_id": scope.lower(),
                                 "owner": {key: document["target"][key] for key in ("factory_id", "scaleset_id")},
                                 "body_hash": "f" * 64, "etag": None} for scope in document["locks"]["scopes"]],
            "inventory_closure_hash": "e" * 64}


@pytest.mark.parametrize("defect", ["missing", "empty", "duplicate", "foreign", "hash"])
def test_worker_receipt_requires_exact_verified_resource_groups(defect):
    document, _ = scoped_manifest()
    receipt = successful_worker_receipt(document)
    if defect == "missing":
        receipt.pop("resource_groups")
    elif defect == "empty":
        receipt["resource_groups"] = []
    elif defect == "duplicate":
        receipt["resource_groups"].append(copy.deepcopy(receipt["resource_groups"][0]))
    elif defect == "foreign":
        receipt["resource_groups"][0]["owner"]["factory_id"] = "different"
    else:
        receipt["resource_groups"][0]["body_hash"] = ""
    cloud = FakeCloud()
    cloud.runs["runs/" + document["run_id"] + ".worker.json"] = receipt
    with pytest.raises(fl.Blocked, match="group-ownership"):
        fl.verify_worker_receipt(fl.BlobLocks(cloud, document), document)


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_github_scoped_dispatch_pins_unique_tag_namespaces_secrets_and_exact_run(conclusion):
    document, _ = scoped_manifest(route="gha")
    cloud = FakeCloud()
    cloud.enrollment = scoped_enrollment(document)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    cloud.runs["runs/" + document["run_id"] + ".worker.json"] = successful_worker_receipt(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    template = (ROOT / "bootstrap/templates/factory-lifecycle-gha.yml").read_text().strip()
    calls = []

    def command(argv, cwd=None, data=None):
        calls.append((argv, data))
        if argv[:2] == ["git", "show"]:
            return template
        if argv == ["gh", "api", "user", "--hostname", "github.com"]:
            return json.dumps({"id": 71})
        if argv[:3] in (["gh", "secret", "set"], ["gh", "secret", "delete"]):
            return ""
        method, endpoint = argv[3:5]
        if "/contents/" in endpoint:
            return json.dumps({"encoding": "base64", "content": base64.b64encode(template.encode()).decode()})
        if "/git/trees/" in endpoint:
            return json.dumps({"tree": [{"path": "azure-enterprise-scale-ml", "mode": "160000", "sha": "a" * 40}]})
        if "/workflow" in endpoint and "/runs?" in endpoint:
            return json.dumps({"workflow_runs": [{"id": 12, "display_title": "unrelated", "head_sha": "f" * 40},
                                                {"id": 42, "display_title": "factory-lifecycle [" + document["run_id"] + "]",
                                                 "head_sha": "b" * 40}]})
        if "/actions/runs/" in endpoint:
            assert endpoint.endswith("/42")
            return json.dumps({"status": "completed", "conclusion": conclusion, "head_sha": "b" * 40})
        if "/git/ref/tags/" in endpoint:
            return json.dumps({"object": {"sha": "b" * 40}})
        assert method in ("POST", "DELETE")
        return ""

    cloud.command = command
    receipt, saved = {}, []
    if conclusion == "failure":
        with pytest.raises(fl.Blocked, match="scoped-github-run-failed"):
            fl.github_scoped(cloud, locks, document, ROOT, receipt, lambda: saved.append(copy.deepcopy(receipt)), sleep=Mock())
    else:
        fl.github_scoped(cloud, locks, document, ROOT, receipt, lambda: saved.append(copy.deepcopy(receipt)), sleep=Mock())
        assert receipt["worker_receipt"]["status"] == "succeeded"
    assert receipt["remote_run"] == {"kind": "gha", "run_id": 42}
    assert receipt["remote_artifacts_cleaned"]
    secrets = [(args, data) for args, data in calls if args[:3] == ["gh", "secret", "set"]]
    envelope = json.loads(zlib.decompress(base64.b64decode("".join(data for _, data in secrets))))
    assert envelope["manifest"] == document and envelope["lease_context"] == locks.held
    assert all(document["route"]["auth_namespace"] in args for args, _ in secrets)
    assert all("github.com/org/consumer" in args for args, _ in secrets)
    assert all("github.com" in args for args, _ in calls if args[:2] == ["gh", "api"])
    assert all("synthetic-not-a-credential" not in str(args) for args, _ in calls)
    posted = [json.loads(data) for args, data in calls if len(args) > 4 and args[3] == "POST" and "/git/refs" in args[4]]
    assert posted == [{"ref": "refs/tags/aifactory-runs/" + document["run_id"], "sha": "b" * 40}]
    assert all("synthetic-not-a-credential" not in json.dumps(row) for row in saved)


def test_new_ado_scoped_template_uses_namespaced_connection_exact_commit_and_worker_evidence():
    document, _ = scoped_manifest()
    cloud = FakeCloud()
    cloud.enrollment = scoped_enrollment(document)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    cloud.runs["runs/" + document["run_id"] + ".worker.json"] = successful_worker_receipt(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    template = (ROOT / "bootstrap/templates/factory-lifecycle-ado.yml").read_text().strip()
    cloud.command = Mock(return_value=template)
    original = cloud.request
    calls = []

    def request(method, url, audience, data=None, **kwargs):
        if not url.startswith("https://dev.azure.com/"):
            return original(method, url, audience, data, **kwargs)
        calls.append((method, url, data))
        if "/serviceendpoint/endpoints?" in url:
            result = {"value": [{"name": document["route"]["auth_namespace"],
                                 "authorization": {"scheme": "WorkloadIdentityFederation", "parameters": {"tenantid": TENANT}},
                                 "data": {"subscriptionId": SUB}}]}
        elif "/items?" in url:
            result = {"content": template}
        elif "/build/definitions?" in url:
            result = {"value": [{"id": 7, "repository": {"name": "consumer"}, "process": {"yamlFilename": fl.SCOPED_ADO}}]}
        elif method == "POST":
            result = {"id": 43}
        else:
            assert "/pipelines/7/runs/43?" in url
            result = {"state": "completed", "result": "succeeded",
                      "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}}
        return 200, {}, result

    cloud.request = request
    receipt = {}
    fl.ado_scoped(cloud, locks, document, ROOT, receipt, lambda: None, sleep=Mock())
    payload = next(data for method, _, data in calls if method == "POST")
    assert payload["resources"]["repositories"]["self"]["version"] == document["route"]["commit"]
    assert payload["templateParameters"]["serviceConnection"] == document["route"]["auth_namespace"]
    assert payload["templateParameters"]["vmImage"] == "ubuntu-latest"
    assert payload["variables"]["AIFACTORY_ENVELOPE_JSON"]["isSecret"]
    assert receipt["worker_receipt"]["status"] == "succeeded"


def test_combined_template_keeps_secret_values_out_of_template_and_orders_nested_phases():
    document, templates = scoped_manifest(("017",))
    cloud = PlanCloud(document, templates)
    payload = fl.combined_plan_payload(cloud, document, ROOT)
    nested = payload["properties"]["template"]["resources"]
    assert len(nested) == 4
    assert nested[0]["dependsOn"] == []
    assert nested[-1]["dependsOn"] == [fl.deployment_endpoint(document, document["deployment"]["steps"][-2]).removeprefix(fl.ARM)]
    assert all(item["type"] == "secureObject" for item in payload["properties"]["template"]["parameters"].values())
    assert payload["properties"]["parameters"]["step_3"]["value"]["projectNumber"] == "017"


def test_inherited_factory_lock_is_verified_but_never_released_by_child():
    document, cloud = manifest(), FakeCloud()
    parent = fl.BlobLocks(cloud, document)
    parent.acquire()
    document["locks"]["inherited_leases"] = {COMMON.lower(): parent.held[COMMON.lower()]}
    parent.request("PUT", parent.blob_name(GROUP), headers={"x-ms-lease-action": "release",
                   "x-ms-lease-id": parent.held.pop(GROUP.lower())}, query="?comp=lease", allowed=(200,))
    child = fl.BlobLocks(cloud, document)
    child.acquire()
    child.release()
    assert set(child.held) == {COMMON.lower()}
    assert set(cloud.leases) == {parent.blob_name(COMMON)}
    parent.release()
    assert not cloud.leases


def test_full_delete_blocks_implicit_external_managed_group_and_active_resource():
    for properties, code in [
        ({"managedResourceGroupId": COMMON}, "implicit-managed-group-not-authorized"),
        ({"nodeResourceGroup": "unreviewed-nodes"}, "implicit-managed-group-not-authorized"),
        ({"provisioningState": "Updating"}, "active-or-unknown-resource-operation"),
    ]:
        cloud = ClosureCloud()
        cloud.bodies[NSG.lower()]["properties"].update(properties)
        document = owned_group_manifest(cloud)
        with pytest.raises(fl.Blocked, match=code):
            fl.verify_full_inventory(cloud, document)
        assert not cloud.deleted


def test_read_only_whole_plan_prepare_does_not_deploy(monkeypatch):
    document, templates = scoped_manifest(("017",))
    cloud = PlanCloud(document, templates)
    monkeypatch.setattr(fl, "verify_source", lambda cloud, root, source: root)
    result = fl.freeze_deployment_plan(cloud, document, ROOT)
    assert result["configuration_hash"] == fl.digest(document["config"])
    assert result["changes"] == document["deployment"]["changes"]
    assert not cloud.arm_writes
    assert cloud.identity_checks == 1


def test_read_only_full_delete_prepare_uses_actual_tags_and_verified_child_receipt():
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    child = next(item for item in document["deletion"]["resources"] if item["id"] == RULE.lower())
    records = {RULE.lower(): {key: child[key] for key in ("owner", "ownership_source", "ownership_evidence")}}
    result = fl.freeze_deletion_inventory(cloud, document, records)
    assert result["inventory_mode"] == "arm-provider-closure-v1"
    assert set(row["id"] for row in result["resources"]) == {NSG.lower(), RULE.lower()}
    assert result["resource_groups"][0]["owner"] == CORE_OWNER
    assert not cloud.deleted and not cloud.leases


@pytest.mark.parametrize("status", ["Failed", "Running", "Canceled"])
def test_partial_what_if_response_never_authorizes_deployment(status):
    with pytest.raises(fl.Blocked, match="arm-what-if-failed-or-incomplete"):
        fl.arm_changes({"status": status, "properties": {"changes": [
            {"resourceId": RESOURCE, "changeType": "Create", "after": RESOURCE_BODY}]}})


class ArmResponse(io.BytesIO):
    def __init__(self, code, body=None, headers=None):
        super().__init__(b"" if body is None else fl.canonical(body))
        self.code = code
        self.headers = headers or {}


def test_what_if_accepts_empty_202_polls_before_final_changes():
    document, _ = scoped_manifest()
    location = fl.ARM + f"/subscriptions/{SUB}/providers/Microsoft.Resources/operationresults/reviewed"
    change = {"resourceId": RESOURCE, "changeType": "Create", "after": RESOURCE_BODY}
    opener = Mock()
    opener.open.side_effect = [
        ArmResponse(202, headers={"Location": location}),
        ArmResponse(202),
        ArmResponse(200, {"status": "Running"}),
        ArmResponse(200, {"status": "Succeeded", "properties": {"changes": [change]}}),
    ]
    cloud = fl.Cloud(document, command_runner=Mock(), opener=opener)
    cloud.token = Mock(return_value="synthetic-token")
    pause = Mock()
    changes = fl.evaluate_what_if(cloud, document, {"id": "factory", "scope": "subscription"},
                                  {"properties": {}}, sleep=pause)
    assert changes == fl.arm_changes({"properties": {"changes": [change]}})
    assert pause.call_count == 3
    assert [call.args[0].method for call in opener.open.call_args_list] == ["POST", "GET", "GET", "GET"]
    assert all(call.args[0].full_url == location for call in opener.open.call_args_list[1:])


@pytest.mark.parametrize("status", ["Failed", "Canceled", "Cancelled"])
@pytest.mark.parametrize("http_status", [200, 202])
def test_what_if_terminal_failure_is_not_treated_as_pending(status, http_status):
    document, _ = scoped_manifest()
    opener = Mock()
    opener.open.side_effect = [
        ArmResponse(202, headers={"Location": fl.ARM + f"/subscriptions/{SUB}/operationresults/reviewed"}),
        ArmResponse(http_status, {"status": status}),
    ]
    cloud = fl.Cloud(document, command_runner=Mock(), opener=opener)
    cloud.token = Mock(return_value="synthetic-token")
    with pytest.raises(fl.Blocked, match="arm-what-if-failed"):
        fl.evaluate_what_if(cloud, document, {"id": "factory", "scope": "subscription"},
                           {"properties": {}}, sleep=Mock())
    assert opener.open.call_count == 2


def test_what_if_perpetually_pending_is_bounded():
    document, _ = scoped_manifest()
    opener = Mock()
    opener.open.side_effect = lambda *args, **kwargs: ArmResponse(
        202, headers={"Location": fl.ARM + f"/subscriptions/{SUB}/operationresults/reviewed"})
    cloud = fl.Cloud(document, command_runner=Mock(), opener=opener)
    cloud.token = Mock(return_value="synthetic-token")
    with pytest.raises(fl.Blocked, match="arm-what-if-incomplete"):
        fl.evaluate_what_if(cloud, document, {"id": "factory", "scope": "subscription"},
                           {"properties": {}}, sleep=Mock())
    assert opener.open.call_count == 121


def test_foundry_ownership_uses_actual_canonical_tags_project_parameter():
    document, templates = scoped_manifest(("017",), operation="deploy-project")
    path = "environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v4.bicep"
    declared = dict(re.findall(r"(?m)^param\s+(\w+)\s+(string|bool|int|object|array)\b",
                               (ROOT / path).read_text(encoding="utf-8")))
    assert declared["tagsProject"] == "object" and "tags" not in declared
    step = document["deployment"]["steps"][0]
    original = step["parameters"]
    values = {"string": "", "bool": False, "int": 0, "object": {}, "array": []}
    parameters = {name: copy.deepcopy(original.get(name, values[kind])) for name, kind in declared.items()}
    parameters["tagsProject"] = original["tags"]
    template = {"$schema": templates[step["template"]]["$schema"],
                "parameters": {name: {"type": kind} for name, kind in declared.items()}, "resources": []}
    templates[path] = template
    step.update(template=path, parameters=parameters, template_hash=fl.digest(template))
    fl.validate_manifest(seal(document))
    payload = fl.compiled_plan_step(PlanCloud(document, templates), document, step, ROOT)
    assert set(payload["properties"]["parameters"]) == set(declared)
    assert "tags" not in payload["properties"]["parameters"]
    parameters["tags"] = parameters.pop("tagsProject")
    with pytest.raises(fl.Blocked, match="deployment-ownership-tags-required"):
        fl.validate_manifest(seal(document))


@pytest.mark.parametrize("scope", ["subscription", "resource-group"])
def test_all_canonical_phase_deployment_names_fit_arm_limit(scope):
    document, _ = scoped_manifest()
    step_ids = ["step-" + Path(path).stem for path in [*fl.COMMON_TEMPLATES.values(), *sorted(fl.PROJECT_TEMPLATES)]]
    step_ids.extend(["factory", "x" * 40])
    names = []
    for step_id in step_ids:
        step = {"id": step_id, "scope": scope, "resource_group": GROUP}
        endpoint = fl.deployment_endpoint(document, step)
        name = endpoint.rsplit("/", 1)[-1]
        assert len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_.()-]+", name)
        assert endpoint == fl.deployment_endpoint(document, step)
        other_run = {**document, "run_id": str(uuid4())}
        assert endpoint != fl.deployment_endpoint(other_run, step)
        names.append(name)
    assert len(names) == len(set(names))


def test_bounded_names_are_shared_by_nested_dependencies_and_receipt_endpoints():
    document, templates = scoped_manifest(("017",))
    steps = document["deployment"]["steps"]
    identifiers = ["step-11-rgCommon", "step-12-networkCommon", "step-13-rgLevel", "step-02-core-infrastructure"]
    for index, step in enumerate(steps):
        step["id"] = identifiers[index]
        step["depends_on"] = identifiers[index - 1:index] if index else []
    cloud = PlanCloud(document, templates)
    nested = fl.combined_plan_payload(cloud, document, ROOT)["properties"]["template"]["resources"]
    for index, resource in enumerate(nested):
        assert resource["name"] == fl.deployment_endpoint(document, steps[index]).rsplit("/", 1)[-1]
        assert len(resource["name"]) <= 64
        assert resource["dependsOn"] == ([fl.deployment_endpoint(document, steps[index - 1]).removeprefix(fl.ARM)] if index else [])


def test_full_group_failure_keeps_receipt_and_physical_locks(monkeypatch, workspace):
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    cloud.fail_delete = True
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    result = fl.execute(document, source, execution, receipt, cloud=cloud)
    assert result["status"] == "reconciliation-required"
    assert result["pending_resource_group"] == GROUP
    assert result["deleted_resources"] == []
    assert len(cloud.leases) == 2 and not cloud.deleted
    assert json.loads(receipt.read_text())["status"] == "reconciliation-required"


@pytest.mark.parametrize("tags,code", [
    ({"aifactory.factory_id": "unrelated", "aifactory.scaleset_id": "Stage001"}, "existing-resource-owner-mismatch"),
    ({"aifactory.factory_id": "factory-a", "aifactory.scaleset_id": "Stage001", "aifactory.project_id": "019"},
     "existing-other-project-resource-write-forbidden"),
])
def test_worker_cannot_overwrite_unrelated_existing_resources(monkeypatch, tags, code):
    document, templates = scoped_manifest(("017",))
    cloud = PlanCloud(document, templates)
    cloud.bodies[RESOURCE.lower()]["tags"] = tags
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                     ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert result["error_code"] == code
    assert not cloud.arm_writes


def test_old_ownership_receipt_cannot_authorize_replaced_resource_at_same_id():
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    cloud.bodies[RULE.lower()]["etag"] = '"replacement-instance"'
    cloud.bodies[RULE.lower()]["properties"]["priority"] = 200
    closure, _ = fl.collect_resource_closure(cloud, [GROUP])
    document["deletion"]["closure"] = closure
    document["deletion"]["closure_hash"] = fl.digest(closure)
    for item in document["deletion"]["resources"]:
        item.update(closure["resources"][item["id"]])
    document["deletion"]["inventory_hash"] = fl.digest(document["deletion"]["resources"])
    fl.validate_manifest(seal(document))
    with pytest.raises(fl.Blocked, match="child-instance-ownership-unverified"):
        fl.verify_full_inventory(cloud, document)
    assert not cloud.deleted


def test_pure_parameter_preparation_reports_unused_settings_and_published_defaults():
    template = {"parameters": {"env": {"type": "string"}, "enabled": {"type": "bool"},
                                "count": {"type": "int", "defaultValue": 3}}}
    result = fl.resolve_template_parameters(template, {"environment": "test", "flag": "false", "unmapped": "keep"},
                                             {"env": "environment", "enabled": "flag"})
    assert result["parameters"] == {"env": "test", "enabled": False, "count": 3}
    assert result["unused_configuration_keys"] == ["unmapped"]
    assert result["published_defaults"] == ["count"]
    with pytest.raises(fl.Blocked, match="explicit-parameter-value-required"):
        fl.resolve_template_parameters({"parameters": {"projectNumber": {"type": "string", "defaultValue": "001"}}}, {}, {})


def test_managed_group_ownership_requires_reciprocal_owned_parent_not_name():
    cluster = GROUP + "/providers/Microsoft.ContainerService/managedClusters/cluster"
    nodes = GROUP + "-nodes"
    bodies = {
        cluster.lower(): {"id": cluster, "tags": {fl.TAG_KEYS[key]: value for key, value in CORE_OWNER.items()},
                          "properties": {"nodeResourceGroup": "reviewed-nodes"}},
        nodes.lower(): {"id": nodes, "managedBy": cluster},
    }
    assert fl.verify_group_ownership(bodies[nodes.lower()], CORE_OWNER, bodies) == cluster.lower()
    child = nodes + "/providers/Microsoft.Compute/virtualMachines/node"
    assert fl.inherited_new_resource_owner(child.lower(), bodies) == CORE_OWNER
    bodies[cluster.lower()]["properties"]["nodeResourceGroup"] = "unrelated"
    with pytest.raises(fl.Blocked, match="managed-group-parent-link-unverified"):
        fl.verify_group_ownership(bodies[nodes.lower()], CORE_OWNER, bodies)
    bodies[nodes.lower()]["tags"] = {"aifactory.factory_id": "different", "aifactory.scaleset_id": "Stage001"}
    with pytest.raises(fl.Blocked, match="live-resource-ownership-mismatch"):
        fl.verify_group_ownership(bodies[nodes.lower()], CORE_OWNER, bodies)


@pytest.mark.skipif(sys.platform != "win32", reason="Current-user DPAPI is Windows-only")
def test_windows_dpapi_roundtrip_uses_whole_manifest_without_plaintext_file(workspace):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    crypt, kernel = ctypes.WinDLL("crypt32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    document = manifest()
    raw = fl.canonical(document)
    buffer = ctypes.create_string_buffer(raw)
    source, output = Blob(len(raw), ctypes.cast(buffer, ctypes.c_void_p)), Blob()
    assert crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    try:
        encrypted = ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)
    path = workspace / "prepared.dpapi"
    path.write_bytes(encrypted)
    assert b"synthetic-not-a-credential" not in encrypted
    assert fl.read_manifest(SimpleNamespace(stdin_manifest=False, protected_manifest=str(path))) == document
    assert list(workspace.iterdir()) == [path]


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_private_runner_selection_is_explicit_and_matches_frozen_configuration(route):
    document, _ = scoped_manifest(route=route)
    document["config"].update(useSelfHostedBuildAgent=True, BYO_subnets=False)
    document["deployment"]["configuration_hash"] = fl.digest(document["config"])
    runner = {"kind": "self-hosted", "os": "linux"}
    if route == "gha":
        runner["labels"] = ["self-hosted", "linux", "factory-a-private"]
        document["config"]["selfHostedRunnerLabel"] = "factory-a-private"
    else:
        runner.update(pool="factory-a-private", agent_name="linux-01")
        document["config"].update(adminVMBuildAgentPool="factory-a-private", adminVMBuildAgentName="linux-01")
    document["route"]["runner"] = runner
    document["deployment"]["configuration_hash"] = fl.digest(document["config"])
    fl.validate_manifest(seal(document))
    document["route"]["runner"] = {"kind": "hosted", "os": "linux", "image": "ubuntu-latest"}
    with pytest.raises(fl.Blocked, match="runner-selection-conflicts-with-frozen-config"):
        fl.validate_manifest(seal(document))


def test_sovereign_or_unknown_azure_cloud_cannot_send_tokens_to_public_endpoints():
    cloud = fl.Cloud(manifest(), command_runner=Mock(), opener=Mock())
    cloud.command = Mock(return_value=json.dumps({"id": SUB, "tenantId": TENANT, "environmentName": "AzureUSGovernment"}))
    cloud.token = Mock()
    with pytest.raises(fl.Blocked, match="public-azure-cloud-required"):
        cloud.verify_identity()
    cloud.token.assert_not_called()


def test_github_workload_refresh_is_job_bound_and_never_puts_tokens_in_argv(monkeypatch):
    document, _ = scoped_manifest(route="gha")
    cloud = fl.Cloud(document, opener=Mock(), command_runner=Mock(),
                     expected_object_id=document["identity"]["deployment_object_id"])
    cloud.command = Mock(return_value=json.dumps({"id": SUB, "tenantId": TENANT, "environmentName": "AzureCloud",
                                                  "user": {"type": "servicePrincipal", "name": IDENTITY}}))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", "https://pipelines.actions.githubusercontent.com/oidctoken?api-version=2")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "synthetic-platform-token")

    def jwt(claims):
        return "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"

    oidc = jwt({"iss": "https://token.actions.githubusercontent.com", "aud": "api://AzureADTokenExchange",
                "repository": "org/consumer", "sha": document["route"]["commit"], "run_id": "42",
                "ref": "refs/tags/aifactory-runs/" + document["run_id"],
                "environment": document["route"]["auth_namespace"],
                "sub": "repo:org/consumer:environment:" + document["route"]["auth_namespace"]})
    token = jwt({"tid": TENANT, "oid": document["identity"]["deployment_object_id"], "exp": time.time() + 3600})
    requests = []

    def identity(request):
        requests.append(request)
        if request.full_url.startswith("https://pipelines.actions.githubusercontent.com/"):
            return {"value": oidc}
        assert request.full_url == "https://login.microsoftonline.com/" + TENANT + "/oauth2/v2.0/token"
        assert b"client_assertion=" in request.data
        return {"access_token": token}

    cloud.identity_json = identity
    cloud.verify_identity(require_default=True)
    assert cloud.token(fl.ARM) == token and len(requests) == 2
    cloud.token_expiries[fl.ARM] = 0
    assert cloud.token(fl.ARM) == token and len(requests) == 4
    assert all("synthetic-platform-token" not in str(call) and oidc not in str(call) for call in cloud.command.call_args_list)
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", "https://example.com/steal")
    cloud.token_expiries[fl.ARM] = 0
    with pytest.raises(fl.Blocked, match="trusted-github-oidc-context-required"):
        cloud.token(fl.ARM)
    assert len(requests) == 4
