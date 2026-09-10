import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import catalog_worker
from src.catalog_frozen_plan import FrozenPlanner
from src.catalog_runtime import CatalogRuntime
from src.catalog_storage import CatalogError
from tests.test_catalog_frozen_plan import CohortPty, scoped
from tests.test_catalog_runtime import catalog, protocol, root, harness, request, OWNER, SUB, VERSION


@pytest.fixture
def cohort_setup(root, harness):
    service, runtime, factory, queue, records = harness
    document = catalog.load_document(root)
    groups = {}
    for scale in document["factories"][0]["scale_sets"]:
        group = f"/subscriptions/{SUB}/resourceGroups/cohort-{scale['environment']}"
        groups[scale["id"]] = group
        scale["owned_resource_ids"] = [group]
        records.append({"resource_id": group, "factory_id": factory["id"], "scale_set_id": scale["id"], "shared": False})
    catalog.commit_document(root, document)
    scoped(runtime, groups=groups)
    return harness


@pytest.mark.parametrize("defect", [
    "aggregate-hash", "aggregate-source", "retained-lock", "missing-child", "duplicate-child",
    "child-hash", "child-revision", "child-target", "unapproved-delete", "persisted-child",
])
def test_any_cohort_receipt_mismatch_retains_original_catalog_and_protected_inputs(root, cohort_setup, defect):
    service, runtime, factory, queue, _ = cohort_setup

    def transform(result):
        child = result["children"][0]
        if defect == "aggregate-hash":
            result["cohort_hash"] = "0" * 64
        elif defect == "aggregate-source":
            result["source_ref"] = "refs/heads/other"
        elif defect == "retained-lock":
            result["lock_retained"] = True
        elif defect == "missing-child":
            result["children"].pop()
        elif defect == "duplicate-child":
            result["children"][-1] = copy.deepcopy(child)
        elif defect == "child-hash":
            child["manifest_hash"] = "0" * 64
        elif defect == "child-revision":
            child["manifest_revision"] += 1
        elif defect == "child-target":
            child["target"]["environment"] = "other"
        elif defect == "unapproved-delete":
            child["deleted_resources"].append(f"/subscriptions/{SUB}/resourceGroups/foreign")

    launches = []

    def pty(argv, cwd, env):
        launches.append(argv)
        result = CohortPty(argv, cwd, env, lambda manifest: {
            "deleted_resources": [item["id"] for item in [
                *manifest["deletion"]["resources"], *manifest["deletion"]["resource_groups"]]]}, transform=transform)
        if defect == "persisted-child":
            receipt = Path(argv[argv.index("--receipt") + 1])
            next(receipt.parent.glob("*.receipt.json")).write_text("{}", encoding="utf-8")
        return result

    runtime.pty_factory = pty
    revision = catalog.source_revision(root)
    preview = service.prepare(request(root, "delete-factory", factory_id=factory["id"], version_ref="124"), OWNER)
    assert preview["can_execute"], preview["blockers"]
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    queue.pop()()
    assert len(launches) == 1 and "--cohort" in launches[0]
    assert runtime.job(root, job["id"], OWNER)["status"] == "failed"
    assert catalog.source_revision(root) == revision
    assert (root / "config-wizard" / "catalog-runs" / job["id"] / "configuration.dpapi").exists()


def test_old_published_runtime_cannot_fall_back_to_sequential_factory_deletion(root, cohort_setup):
    _, runtime, factory, _, _ = cohort_setup
    module = SimpleNamespace(capabilities=lambda: {
        "contract": 1, "delete_owned_resource_groups": "arm-provider-closure-v1"})
    planner = FrozenPlanner(runtime, cloud_factory=lambda *args: pytest.fail("Must block before cloud"))
    planner.module = lambda *args: (module, root)
    with pytest.raises(CatalogError, match="physical-lease-cohort-v1"):
        planner.prepare(root, request(root, "delete-factory", factory_id=factory["id"], scale_set_id=None),
                        catalog.load_document(root), VERSION, [], {}, {}, "unused", "unused")


@pytest.mark.parametrize("defect", [None, "changed-child", "resigned-child", "missing-child", "missing-capability"])
def test_protected_worker_binds_entire_cohort_before_one_runtime_call(tmp_path, defect):
    source = (
        "import hashlib,json\nfrom pathlib import Path\n"
        "def unprotect(raw): return raw\n"
        "def manifest_digest(doc): return hashlib.sha256(json.dumps({k:v for k,v in doc.items() if k!='manifest_hash'},sort_keys=True,separators=(',',':')).encode()).hexdigest()\n"
        "def validate_manifest(doc): pass\n"
        "def capabilities(): return {'factory_cohort':'physical-lease-cohort-v1'}\n"
        "def execute_cohort(docs,source,execution,receipt):\n Path(receipt).write_text(json.dumps([d['run_id'] for d in docs])); return {'status':'succeeded'}\n"
        "def execute(*args): raise RuntimeError('No individual fallback')\n"
    )
    if defect == "missing-capability":
        source = source.replace("'physical-lease-cohort-v1'", "'unsupported'")
    helper = tmp_path / "helper.py"
    helper.write_text(source, encoding="utf-8")
    documents = [{"run_id": "one", "config": {"private": "first"}}, {"run_id": "two", "config": {"private": "second"}}]
    for document in documents:
        document["manifest_hash"] = protocol.fingerprint(document)
    expected = protocol.fingerprint(sorted(item["manifest_hash"] for item in documents))
    if defect in ("changed-child", "resigned-child"):
        documents[0]["config"]["private"] = "replaced"
        if defect == "resigned-child":
            documents[0].pop("manifest_hash")
            documents[0]["manifest_hash"] = protocol.fingerprint(documents[0])
    elif defect == "missing-child":
        documents.pop()
    else:
        documents.reverse()
    artifact = tmp_path / "manifest.dpapi"
    artifact.write_bytes(protocol.canonical(documents))
    receipt = tmp_path / "receipt.json"
    args = SimpleNamespace(helper=str(helper), helper_sha256=hashlib.sha256(source.encode()).hexdigest(),
                           protected_manifest=str(artifact), expected_hash=expected, cohort=True,
                           source_root=str(tmp_path), execution_root=str(tmp_path / "execution"), receipt=str(receipt))
    if defect:
        with pytest.raises(ValueError):
            catalog_worker.execute(args)
        assert not receipt.exists()
    else:
        assert catalog_worker.execute(args)["status"] == "succeeded"
        assert json.loads(receipt.read_text(encoding="utf-8")) == ["two", "one"]


@pytest.mark.parametrize("outcome", ["success", "past-deadline", "partial-failure"])
def test_real_cohort_receipts_satisfy_backend_verification_and_catalog_removal(tmp_path, monkeypatch, outcome):
    source_root = Path(os.environ.get("AIFACTORY_LIFECYCLE_SOURCE_ROOT", str(
        Path(__file__).parents[2] / "003_aifactory_sub" / "azure-enterprise-scale-ml")))
    fixture_path = source_root / "environment_setup" / "unit-tests" / "test-bicep" / "unit" / "test_factory_lifecycle.py"
    if not fixture_path.is_file():
        pytest.skip("Set AIFACTORY_LIFECYCLE_SOURCE_ROOT for the canonical cohort receipt cross-contract test.")
    spec = importlib.util.spec_from_file_location("catalog_canonical_cohort_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    module = fixture.fl
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=AssertionError("Real commands forbidden")))
    monkeypatch.setattr(module, "build_opener", Mock(side_effect=AssertionError("Real HTTP forbidden")))
    documents, cloud = fixture.cohort_fixture(other_subscription=True)
    original = copy.deepcopy(documents)
    source, execution, receipt = fixture.setup_execute(monkeypatch, tmp_path)
    if outcome == "past-deadline":
        future = max(module.timestamp(document["expires_at"]) for document in documents) + 60
        cloud.after_delete = lambda resource_id: monkeypatch.setattr(module.time, "time", lambda: future)
    elif outcome == "partial-failure":
        cloud.after_delete = lambda resource_id: setattr(cloud, "fail_delete", True)
    result = module.execute_cohort(documents[::-1], source, execution, receipt, cloud_factory=lambda document: cloud)
    factory_id = documents[0]["target"]["factory_id"]
    job = {"factory_id": factory_id, "_manifest_hash": protocol.fingerprint(
        sorted(document["manifest_hash"] for document in documents))}
    selected = {"resolved_ref": documents[0]["source"]["commit"]}
    scale_ids = [document["target"]["scaleset_id"] for document in documents]
    catalog_document = {"factories": [{"id": factory_id, "scale_sets": [{"id": value} for value in scale_ids], "projects": []}],
                        "configurations": {factory_id: {"scale_sets": {value: {} for value in scale_ids}}}}
    if outcome == "partial-failure":
        before = copy.deepcopy(catalog_document)
        assert result["status"] == "reconciliation-required" and result["lock_retained"]
        assert any(child["status"] == "succeeded" for child in result["children"])
        assert all(child["locks_retained"] == result["locks_retained"] for child in result["children"])
        with pytest.raises(CatalogError, match="cohort success evidence"):
            CatalogRuntime._cohort_children(documents, result, job, selected, execution)
            CatalogRuntime._apply_cohort_result(catalog_document, job, documents, result)
        assert catalog_document == before and cloud.leases
    else:
        children = CatalogRuntime._cohort_children(documents, result, job, selected, execution)
        assert set(children) == {document["run_id"] for document in documents}
        CatalogRuntime._apply_cohort_result(catalog_document, job, documents, result)
        assert catalog_document == {"factories": [], "configurations": {}} and not cloud.leases
    assert documents == original
    assert json.loads(receipt.read_text(encoding="utf-8")) == result
