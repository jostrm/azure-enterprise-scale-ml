import copy
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import factory_catalog as catalog
from src.catalog_runtime import CatalogRuntime
from src import catalog_protocol as protocol
from src import catalog_worker
from src.catalog_storage import CatalogError, digest, encode, read_json, catalog_lock
from tests.test_factory_catalog import OWNER, SUB, TENANT, root, request, migrate


VERSION = {"requested_version": "124", "branch": "release/v1.24", "resolved_ref": "a" * 40,
           "repository": "unused", "helper_sha256": "b" * 64}
RG = f"/subscriptions/{SUB}/resourceGroups/catalog-owned"
RESOURCE = RG + "/providers/Microsoft.Network/publicIPAddresses/ownedip"


class Pty:
    def __init__(self, argv, cwd, env, result):
        self.closed = False
        self.argv, self.cwd, self.env = argv, cwd, env
        self.output = ["safe output\r\n", ""]
        self.exit_code = 0
        manifest_path = Path(argv[argv.index("--protected-manifest") + 1])
        manifest = json.loads(manifest_path.read_bytes().removeprefix(b"protected:"))
        value = {"schema": 1, "run_id": manifest["run_id"], "manifest_hash": manifest["manifest_hash"],
                 "target": manifest["target"], "source_commit": manifest["source"]["commit"],
                 "status": "succeeded", **result(manifest)}
        receipt = Path(argv[argv.index("--receipt") + 1])
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(encode(value))

    def read(self):
        return self.output.pop(0)

    def wait(self):
        return self.exit_code

    def close(self):
        self.closed = True

    def write(self, data):
        pass

    def resize(self, columns, rows):
        pass


@pytest.fixture
def harness(root):
    queue = []
    records = []
    def result(manifest):
        records.append({"resource_id": RESOURCE, "factory_id": manifest["target"]["factory_id"],
                        "scale_set_id": manifest["target"]["scaleset_id"], "shared": False})
        return {}
    def binding(root, factory, scale):
        return {"_delete_authorized": True,
                "route": {"kind": "ado", "writer_id": "unit-writer", "repository": "https://dev.azure.com/org/project/_git/repo",
                          "ref": "refs/heads/main", "commit": "c" * 40, "shared_remote": False},
                "locks": {"provider": "azure-blob-lease", "account_url": "https://unitlocks.blob.core.windows.net",
                          "container": "locks", "coordination_blob": "enrollment.json",
                          "coordination_hash": "d" * 64, "revision": 1, "scopes": [RG], "common_dependencies": []}}
    runtime = CatalogRuntime(
        inventory=lambda root, factory, scales: {"complete": True, "observed_at": 100, "records": copy.deepcopy(records),
                                                "accounts": [{"identity": "test", "object_id": TENANT,
                                                              "subscription_id": SUB, "tenant_id": TENANT}]},
        resolver=lambda root, version: copy.deepcopy(VERSION),
        materialize=lambda root, version, run: (run / "fake.py", run / "execution"),
        pty_factory=lambda argv, cwd, env: Pty(argv, cwd, env, result),
        dispatch=queue.append, clock=lambda: 100, protector=lambda data: b"protected:" + data, binding=binding,
        unprotector=lambda data: data.removeprefix(b"protected:"))
    service = catalog.CatalogService(runtime=runtime, clock=lambda: 100)
    factory = migrate(root, service)
    document = catalog.load_document(root)
    document["factories"][0]["scale_sets"][0]["orchestrator"] = "ado"
    catalog.commit_document(root, document)
    factory = document["factories"][0]
    # Freshly migrated resources have deliberately no registered ownership.
    return service, runtime, factory, queue, records


def deploy_request(root, factory):
    return request(root, "deploy", factory_id=factory["id"], scale_set_id=factory["scale_sets"][0]["id"],
                   project_id=factory["projects"][0]["id"], version_ref="124")


def test_runtime_jobs_are_durable_owned_and_protected(root, harness):
    service, runtime, factory, queue, records = harness
    before = (root / "variables.json").read_bytes()
    preview = service.prepare(deploy_request(root, factory), OWNER)
    assert preview["can_execute"], preview["blockers"]
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    job = result["job"]
    assert job["status"] == "queued"
    assert len(queue) == 1
    with pytest.raises(CatalogError, match="caller"):
        runtime.job(root, job["id"], "other")
    artifact = root / "config-wizard" / "catalog-runs" / job["id"] / "configuration.dpapi"
    assert artifact.read_bytes().startswith(b"protected:")
    manifest = json.loads(artifact.read_bytes().removeprefix(b"protected:"))
    assert manifest["run_id"] == preview["confirmation_id"]
    queue.pop()()
    done = runtime.job(root, job["id"], OWNER)
    assert done["status"] == "succeeded", done["message"]
    assert not artifact.exists()
    assert (root / "variables.json").read_bytes() == before
    assert RESOURCE in catalog.load_document(root)["factories"][0]["scale_sets"][0]["owned_resource_ids"]
    assert runtime.terminal(root, job["id"], OWNER)["output"] == "safe output\r\n"
    with pytest.raises(CatalogError, match="already used"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)


def test_failed_runtime_retains_catalog_and_evidence(root, harness):
    service, runtime, factory, queue, _ = harness
    runtime.materialize = lambda *args: (_ for _ in ()).throw(CatalogError("Published lifecycle runtime unavailable.", 409))
    revision = catalog.source_revision(root)
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    queue.pop()()
    assert runtime.job(root, job["id"], OWNER)["status"] == "failed"
    assert catalog.source_revision(root) == revision
    run = root / "config-wizard" / "catalog-runs" / job["id"]
    assert (run / "manifest.json").is_file()
    assert not (run / "configuration.dpapi").exists()


def test_inventory_changed_or_incomplete_requires_new_confirmation(root, harness):
    service, runtime, factory, queue, records = harness
    preview = service.prepare(deploy_request(root, factory), OWNER)
    records.append({"resource_id": RESOURCE, "factory_id": "unrelated", "scale_set_id": "unrelated", "shared": True,
                    "dependencies": []})
    with pytest.raises(CatalogError, match="inventory changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert not queue
    runtime.inventory = lambda *args: {"complete": False, "records": [], "observed_at": 100}
    blocked = service.prepare(deploy_request(root, factory), OWNER)
    assert not blocked["can_execute"]
    assert "complete inventory" in " ".join(blocked["blockers"])


def test_old_runtime_version_and_legacy_ownership_are_actionable_blockers(root, harness):
    service, runtime, factory, _, _ = harness
    deletion = request(root, "delete-scale-set", factory_id=factory["id"],
                       scale_set_id=factory["scale_sets"][0]["id"], version_ref="124")
    preview = service.prepare(deletion, OWNER)
    assert not preview["can_execute"]
    assert "prefix deletion is never authorized" in " ".join(preview["blockers"])
    runtime.resolver = lambda *args: (_ for _ in ()).throw(CatalogError("Install published lifecycle contract 1.", 409))
    preview = service.prepare(deploy_request(root, factory), OWNER)
    assert not preview["can_execute"]
    assert "Install published" in " ".join(preview["blockers"])


def register_owned(root, factory, records):
    document = catalog.load_document(root)
    ss = document["factories"][0]["scale_sets"][0]
    ss["owned_resource_ids"] = [RESOURCE]
    catalog.commit_document(root, document)
    records.extend([{"resource_id": resource, "factory_id": factory["id"] if resource == RESOURCE else None,
                     "scale_set_id": ss["id"] if resource == RESOURCE else None, "shared": False,
                     "dependencies": [], "etag": "test-etag", "body_hash": "e" * 64,
                     "type": "Microsoft.Network/publicIPAddresses" if resource == RESOURCE else "Microsoft.Resources/resourceGroups"}
                    for resource in [RG, RESOURCE]])


def test_delete_allowlist_exact_dependencies_and_no_foreign_children(root, harness):
    service, runtime, factory, queue, records = harness
    register_owned(root, factory, records)
    deletion = request(root, "delete-scale-set", factory_id=factory["id"],
                       scale_set_id=factory["scale_sets"][0]["id"], version_ref="124")
    preview = service.prepare(deletion, OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert {item["resource_id"] for item in preview["inventory"]} == {RESOURCE}
    records.append({"resource_id": RG + "/providers/Microsoft.KeyVault/vaults/shared",
                    "factory_id": "other", "scale_set_id": "other", "shared": True})
    blocked = service.prepare(deletion, OWNER)
    assert not blocked["can_execute"]
    assert "foreign/shared children" in " ".join(blocked["blockers"])


def test_verified_delete_removes_only_selected_registered_scope(root, harness):
    service, runtime, factory, queue, records = harness
    register_owned(root, factory, records)
    runtime.pty_factory = lambda argv, cwd, env: Pty(argv, cwd, env,
        lambda manifest: {"deleted_resources": [item["id"] for item in manifest["deletion"]["resources"] if item["delete"]]})
    deletion = request(root, "delete-scale-set", factory_id=factory["id"],
                       scale_set_id=factory["scale_sets"][0]["id"], version_ref="124")
    preview = service.prepare(deletion, OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    assert len(catalog.load_document(root)["factories"][0]["scale_sets"]) == 3
    queue.pop()()
    done = runtime.job(root, job["id"], OWNER)
    assert done["status"] == "succeeded", done["message"]
    target = catalog.load_document(root)["factories"][0]
    assert [ss["environment"] for ss in target["scale_sets"]] == ["stage", "prod"]
    assert all(p["environment"] != "dev" for p in target["projects"][0]["placements"])


def test_manifest_tampering_blocks_runtime(root, harness):
    service, runtime, factory, queue, _ = harness
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    manifest_path = root / "config-wizard" / "catalog-runs" / job["id"] / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["target"]["prefix"] = "foreign"
    manifest_path.write_bytes(encode(manifest))
    queue.pop()()
    assert runtime.job(root, job["id"], OWNER)["status"] == "failed"


def test_common_creation_and_shared_dispatch_are_visible_capability_blockers(root, harness):
    service, runtime, factory, _, _ = harness
    common = deploy_request(root, factory)
    common.pop("project_id")
    preview = service.prepare(common, OWNER)
    assert not preview["can_execute"]
    assert "common-only" in " ".join(preview["blockers"])
    original = runtime.binding
    def shared(*args):
        binding = original(*args)
        binding["route"]["shared_remote"] = True
        return binding
    runtime.binding = shared
    preview = service.prepare(deploy_request(root, factory), OWNER)
    assert not preview["can_execute"]
    assert "namespaced" in " ".join(preview["blockers"])


def test_protected_worker_rejects_reencrypted_manifest_swap_before_execution(root):
    helper = root / "test-helper.py"
    source = (
        "import hashlib,json\nfrom pathlib import Path\n"
        "def unprotect(raw): return raw\n"
        "def manifest_digest(doc): return hashlib.sha256(json.dumps({k:v for k,v in doc.items() if k!='manifest_hash'},sort_keys=True,separators=(',',':')).encode()).hexdigest()\n"
        "def validate_manifest(doc): pass\n"
        "def execute(doc,source,execution,receipt):\n Path(receipt).write_text('mutation-called'); return {'status':'succeeded'}\n"
    )
    helper.write_text(source, encoding="utf-8")
    document = {"schema": 1, "run_id": "original", "config": {"sensitive": "never-print"}}
    expected = protocol.fingerprint(document)
    document["run_id"] = "replaced"
    document["manifest_hash"] = protocol.fingerprint(document)
    artifact = root / "manifest.dpapi"
    artifact.write_bytes(protocol.canonical(document))
    receipt = root / "receipt.json"
    args = SimpleNamespace(helper=str(helper), helper_sha256=hashlib.sha256(source.encode()).hexdigest(),
                           expected_hash=expected, protected_manifest=str(artifact), source_root=str(root),
                           execution_root=str(root / "execution"), receipt=str(receipt))
    with pytest.raises(ValueError, match="consented-manifest-changed"):
        catalog_worker.execute(args)
    assert not receipt.exists()


def test_per_target_rendering_preserves_explicit_network_and_subscription(root, harness):
    service, runtime, factory, _, _ = harness
    request_body = deploy_request(root, factory)
    request_body.update(scale_set_id=factory["scale_sets"][1]["id"])
    document = catalog.load_document(root)
    target = document["factories"][0]["scale_sets"][1]
    target["subscription_id"] = "33333333-3333-3333-3333-333333333333"
    rendered = runtime._configuration(document["factories"][0], [target], document, request_body)
    config = rendered["targets"][target["id"]]
    assert config["stage_prod"]["test_sub_id"] == target["subscription_id"]
    assert config["stage_prod"]["common_vnet_cidr"] == target["network"]["vnet_cidr"]
    assert config["stage_prod"]["common_bastion_subnet_cidr"] == target["network"]["common_subnets"]["bastion"]
    tags = json.loads(config["stage_prod"]["tagsProject"])
    assert tags["aifactory.scaleset_id"] == target["id"]
    assert tags["aifactory.logical_project_id"] == factory["projects"][0]["id"]


def test_stop_queued_job_is_owned_and_does_not_wait_for_catalog_lock(root, harness):
    service, runtime, factory, queue, _ = harness
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    with pytest.raises(CatalogError, match="caller"):
        runtime.stop(root, job["id"], "other")
    with catalog_lock(root):
        runtime.stop(root, job["id"], OWNER)
        assert runtime.terminal(root, job["id"], OWNER)["status"] == "queued"
    runtime.materialize = lambda *args: pytest.fail("A stopped queued job must not start")
    queue.pop()()
    assert runtime.job(root, job["id"], OWNER)["status"] == "interrupted"


def test_missing_owned_resource_outside_enrollment_still_blocks_complete_delete(root, harness):
    service, runtime, factory, _, records = harness
    register_owned(root, factory, records)
    document = catalog.load_document(root)
    document["factories"][0]["scale_sets"][0]["owned_resource_ids"].append(
        f"/subscriptions/{SUB}/resourceGroups/other/providers/Microsoft.Compute/disks/old")
    catalog.commit_document(root, document)
    preview = service.prepare(request(root, "delete-scale-set", factory_id=factory["id"],
                                       scale_set_id=factory["scale_sets"][0]["id"], version_ref="124"), OWNER)
    assert not preview["can_execute"]
    assert "registered ownership" in " ".join(preview["blockers"])


def test_runtime_merges_its_target_without_clobbering_another_factory(root, harness):
    service, runtime, factory, queue, _ = harness
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    clone = service.prepare(request(root, "clone", factory_id=factory["id"], target_prefix="other-"), OWNER)
    assert clone["can_execute"]
    service.confirm(str(root), clone["confirmation_id"], OWNER)
    queue.pop()()
    done = runtime.job(root, job["id"], OWNER)
    assert done["status"] == "succeeded", done["message"]
    assert len(catalog.load_document(root)["factories"]) == 2
