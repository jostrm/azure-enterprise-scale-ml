"""Single-writer ordered factory deletion and selective project deletion, offline.

The repository state ref replaces every Blob lease and run blob; the fakes fail any storage call.
"""

import copy
import json
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, RESOURCE, seal, workspace, no_real_services
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import prepared, SUBNET, SHARED_SUBNET, VNET
from .test_single_writer_coordination import Provider, ps

REPOSITORIES = {"gha": "https://github.com/org/consumer",
                "ado": "https://dev.azure.com/org/project/_git/consumer"}
COMMON_IP = COMMON + "/providers/Microsoft.Network/publicIPAddresses/common-ip"


def single_writer(document, cloud, kind="ado"):
    """Re-enroll a Blob fixture as one private repository writer and return its provider."""
    route = {**document["route"], "kind": kind, "repository": REPOSITORIES[kind]}
    enrolled = copy.deepcopy(cloud.enrollment)
    enrolled.update(protocol="aifactory-single-writer-v1", enforcement="repository-exclusive-writer")
    writer = enrolled["writers"][route["writer_id"]]
    enrolled["writers"] = {route["writer_id"]: {**writer, "kind": kind, "repository": route["repository"]}}
    for scope in enrolled["scopes"].values():
        scope["writers"] = [route["writer_id"]]
    provider = Provider(route["repository"])
    provider.set_state({"schema": 1, "repository": route["repository"], "enrollment": enrolled,
                        "active": None, "records": copy.deepcopy(cloud.runs)})
    cloud.state_request = provider.call
    original = cloud.request

    def request(method, url, audience, *args, **kwargs):
        assert ".blob.core.windows.net" not in url and "/factory-locks/" not in url, url
        return original(method, url, audience, *args, **kwargs)
    cloud.request = request
    document["route"] = route
    document["locks"] = ps.coordinates(route["repository"]) | {
        "coordination_hash": fl.digest(enrolled), "revision": enrolled["revision"],
        "scopes": document["locks"]["scopes"], "common_dependencies": document["locks"]["common_dependencies"]}
    return provider


def factory_single_writer(kind="ado"):
    document, cloud, projects = factory_prepared()
    provider = single_writer(document, cloud, kind)
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    return seal(document), cloud, provider


def worker_dispatch(monkeypatch, before_worker=lambda: None):
    dispatches = []

    def dispatch(cloud, locks, document, source_root, receipt, persist):
        dispatches.append(document["run_id"])
        receipt["mutation_started"] = True
        receipt["remote_run"] = ({"kind": "gha", "run_id": 44} if document["route"]["kind"] == "gha"
                                 else {"kind": "ado", "pipeline_id": 8, "run_id": 44})
        persist()
        before_worker()
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)), source_root,
                                          document["run_id"], document["manifest_hash"], cloud=cloud,
                                          sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    monkeypatch.setattr(fl, "github_scoped", dispatch)
    return dispatches


def run(workspace, monkeypatch, documents, cloud):
    source = workspace / "source"
    source.mkdir(exist_ok=True)
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)
    execution = workspace / "execution"
    return fl.execute_cohort(documents, source, execution, execution / "receipt.json", cloud_factory=lambda _: cloud)


def test_published_runtime_advertises_single_writer_ordered_factory_deletion():
    assert fl.capabilities()["factory_deletion_pipeline_coordination_modes"] == ["blob", "single-writer"]
    assert fl.capabilities()["single_writer_deletion_inventories"] == [
        "arm-provider-closure-v1", "ordered-project-pipelines-v1", fl.SELECTIVE_PROJECT_DELETE]


def test_single_writer_selective_inventory_requires_its_project_scope():
    document, _, _ = project_single_writer()
    document.pop("deletion_scope")
    with pytest.raises(fl.Blocked, match="single-writer-whole-owned-groups-required"):
        fl.validate_manifest(seal(document))


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_single_writer_factory_deletion_runs_project_worker_before_common_and_releases(workspace, monkeypatch, kind):
    document, cloud, provider = factory_single_writer(kind)
    assert all(method == "GET" for method, _, _ in provider.calls)
    dispatches = worker_dispatch(monkeypatch)
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "succeeded", result
    assert dispatches == [document["run_id"]]
    assert cloud.deleted.index(RESOURCE) < cloud.deleted.index(GROUP) < cloud.deleted.index(COMMON_IP)
    assert SHARED_SUBNET.lower() in cloud.bodies and VNET.lower() in cloud.bodies
    state = provider.state()
    assert state["active"] is None and not result["lock_retained"]
    assert state["records"]["cohorts/" + result["cohort_hash"] + ".json"]["status"] == "succeeded"
    receipt = state["records"]["runs/" + document["run_id"] + ".json"]
    assert receipt["status"] == "succeeded" and receipt["lock_retained"] is False
    assert {value.lower() for value in receipt["deleted_resources"]} == {
        row["id"].lower() for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]
        if row["delete"]}
    assert state["records"]["runs/" + document["run_id"] + ".worker.json"]["status"] == "succeeded"
    assert not cloud.leases


def test_single_writer_factory_worker_rejects_a_cohort_claim_it_is_not_part_of(workspace, monkeypatch):
    document, cloud, provider = factory_single_writer()

    def foreign():
        state = provider.state()
        state["active"]["manifests"] = ["f" * 64]
        provider.set_state(state)
    worker_dispatch(monkeypatch, before_worker=foreign)
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "reconciliation-required", result
    assert "active-claim-changed" in result["error_code"]
    assert not cloud.deleted and provider.state()["active"]


def test_single_writer_failed_project_pipeline_retains_claim_and_never_deletes_common(workspace, monkeypatch):
    document, cloud, provider = factory_single_writer()
    monkeypatch.setattr(fl, "ado_scoped", Mock(side_effect=fl.Blocked("scoped-ado-run-failed")))
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "reconciliation-required", result
    assert result["lock_retained"] is True
    assert provider.state()["active"]["kind"] == "deletion-cohort"
    assert not cloud.deleted


def test_single_writer_partial_common_failure_resumes_its_own_claim_without_redispatch(workspace, monkeypatch):
    document, cloud, provider = factory_single_writer()
    dispatches = worker_dispatch(monkeypatch)
    original_request = cloud.request

    def request(method, url, audience, *args, **kwargs):
        if "dev.azure.com" in url:
            assert method == "GET" and "/pipelines/8/runs/44?" in url
            return 200, {}, {"id": 44, "pipeline": {"id": 8}, "state": "completed", "result": "succeeded",
                             "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}}
        return original_request(method, url, audience, *args, **kwargs)
    cloud.request = request

    def fail_common(identifier):
        if identifier.endswith("/common-ip"):
            raise fl.Blocked("remote-request-failed-403")
    cloud.before_delete = fail_common
    first = run(workspace, monkeypatch, [document], cloud)
    assert first["status"] == "reconciliation-required", first
    assert first["lock_retained"] is True and provider.state()["active"]["kind"] == "deletion-cohort"
    cloud.before_delete = lambda _: None
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "succeeded", result
    assert dispatches == [document["run_id"]]
    assert provider.state()["active"] is None and COMMON_IP.lower() not in cloud.bodies


def test_single_writer_preclaim_failure_clears_the_reservation_without_azure_writes(workspace, monkeypatch):
    document, cloud, provider = factory_single_writer()
    worker_dispatch(monkeypatch)
    cloud.active_run = True
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "blocked", result
    assert provider.state()["active"] is None and not cloud.deleted


def test_single_writer_factory_freeze_refuses_an_active_repository_claim():
    document, cloud, projects = factory_prepared()
    provider = single_writer(document, cloud)
    state = provider.state()
    state["active"] = {"kind": "run", "run_id": document["run_id"]}
    provider.set_state(state)
    with pytest.raises(fl.Blocked, match="single-writer-repository-active-claim"):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)


def project_single_writer(kind="ado"):
    document, cloud = prepared(True, True)
    provider = single_writer(document, cloud, kind)
    document["deletion"] = fl.freeze_project_deletion(cloud, document, {})
    return seal(document), cloud, provider


def test_single_writer_selective_project_manifest_is_valid():
    document, _, _ = project_single_writer()
    assert fl.validate_manifest(document) == document


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_single_writer_selective_project_deletion_keeps_shared_inventory_and_releases(workspace, monkeypatch, kind):
    document, cloud, provider = project_single_writer(kind)
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "succeeded", result
    deleted = {row["id"].lower() for row in document["deletion"]["resource_groups"] + document["deletion"]["resources"]
               if row["delete"]}
    assert GROUP.lower() in deleted and SUBNET.lower() in deleted
    assert {SHARED_SUBNET.lower(), VNET.lower(), COMMON.lower()} <= set(cloud.bodies)
    state = provider.state()
    assert state["active"] is None
    receipt = state["records"]["runs/" + document["run_id"] + ".json"]
    assert receipt["status"] == "succeeded" and {value.lower() for value in receipt["deleted_resources"]} == deleted
    assert not cloud.leases


def test_single_writer_direct_project_delete_uses_the_repository_cohort(workspace, monkeypatch):
    document, cloud, provider = project_single_writer()
    monkeypatch.setattr(fl, "verify_source", lambda *args: workspace / "source")
    receipt = workspace / "execution" / "single.json"
    result = fl.execute(document, workspace / "source", receipt.parent, receipt, cloud=cloud)
    assert result["status"] == "succeeded", result
    assert provider.state()["active"] is None
    assert GROUP.lower() not in cloud.bodies and VNET.lower() in cloud.bodies


def test_single_writer_project_deletion_still_honours_the_enrollment_delete_denial(workspace, monkeypatch):
    document, cloud, provider = project_single_writer()
    state = provider.state()
    state["enrollment"]["scopes"][GROUP.lower()]["allow_delete"] = False
    provider.set_state(state)
    document["locks"]["coordination_hash"] = fl.digest(state["enrollment"])
    seal(document)
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["error_code"] == "physical-target-deletion-not-enrolled"
    assert not cloud.deleted and provider.state()["active"] is None
