"""Canonical export is a provider-read-only, no-clobber local operation."""
import copy
import base64
import json
from pathlib import Path
import socket
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_dispatch as dispatch
import pipeline_lifecycle as lifecycle
from unit.test_pipeline_inputs import register, request, inputs, FACTORY, SCALE, PROJECT, SUB
from unit.test_pipeline_lifecycle_adapters import snapshot as native_snapshot
from test_pipeline_providers_continuations import PARENT, CHILD, context


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live export call forbidden"))


def export_state(provider="gha"):
    from lifecycle_admission import new_record, OPERATIONS, PROTOCOL
    proposal = register(provider)
    canonical = inputs.resolve_document(proposal, request(1, provider), operational={
        "schema": 1, "provider": provider, "repository": context(provider)["repository"],
        "consumer_ref": "refs/heads/main"})
    expected = context(provider)
    expected.update(request_path="request.json", request_digest=dispatch.digest(canonical),
                    source_commit=canonical["source"]["commit"])
    records = []
    for operation, run in ((PARENT, 7), (CHILD, 8)):
        ctx = dict(expected, run_id=run, correlation_id=("e" if run == 7 else "f") * 32)
        plan = {"provider_context": ctx, "stages": [{"id": "test-stage"}],
                "input_snapshot_hash": lifecycle.digest(canonical)}
        if operation == CHILD:
            plan["continuation_of"] = {"operation_id": PARENT, "plan_hash": records[0]["plan_hash"]}
        row = {"schema": 1, "operation_id": operation, "status": "succeeded", "prepared_at": "2026-11-13T00:00:00Z",
               "snapshot": canonical, "snapshot_hash": lifecycle.digest(canonical), "plan": plan,
               "admission": {"status": "released"}, "configuration": {
                   "revision": lifecycle.digest(proposal), "document": proposal}}
        row["plan_hash"] = lifecycle.digest(lifecycle.bound_plan(row))
        row["finalization"] = {"status": "succeeded", "proof": {
            "operation_id": operation, "plan_hash": row["plan_hash"],
            "proof_kind": "github-rs256-native-finalizer" if provider == "gha" else "ado-native-server-finalizer"}}
        records.append(row)
    records[0]["completion"] = {"operation_id": CHILD, "plan_hash": records[1]["plan_hash"]}
    current = copy.deepcopy(proposal)
    current["factories"][0]["status"] = "configured"
    group = f"/subscriptions/{SUB}/resourceGroups/verified-common"
    current["factories"][0]["scale_sets"][0].update(status="configured", owned_resource_ids=[group])
    current["ownership_evidence"] = {group.lower(): {
        "owner": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "ownership_source": "deployment-receipt",
        "ownership_evidence": {"run_id": CHILD, "receipt_hash": "9" * 64}}}
    route = copy.deepcopy(native_snapshot()["binding"])
    route.update(orchestrator=provider, repository=expected["repository"])
    route.pop("runner")
    route["locks"]["repository"] = expected["repository"]
    route["targets"][0].update(scale_set_id=SCALE, resource_group_ids=[group])
    current["bindings"] = {FACTORY: {provider: route}}
    admission = new_record({"repository": expected["repository"], "factories": {
        FACTORY: {"all_writers": PROTOCOL, "shared_scopes": [], "operations": sorted(OPERATIONS),
                  "routes": ["api", "pipeline"], "scopes": [group]}}}, {FACTORY: current})
    state = {"schema": 1, "repository": expected["repository"], "active": None, "enrollment": {},
             "records": {"lifecycle_admission_v1": admission, **{
                 "pipeline-lifecycle/" + row["operation_id"] + ".json": row for row in records}}}
    binding = {"schema": 1, "provider": provider, "repository": expected["repository"],
               "consumer_commit": expected["consumer_commit"], "consumer_ref": "refs/heads/main"}
    return canonical, binding, state, current


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_exports_current_canonical_all_projections_not_stale_operation_proposal(tmp_path, provider):
    canonical, binding, state, current = export_state(provider)
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    result = dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                           "next/azurefactory", reader=reader)
    destination = tmp_path / "next/azurefactory"
    assert json.loads((destination / "register.json").read_text()) == current
    assert (destination / "factories/acme-ai/pipelines" / f"{provider}.json").is_file()
    assert (destination / "factories/acme-ai/scalesets/001/projects/project007/variables.json").is_file()
    assert result["completed_operation_id"] == CHILD
    assert result["configuration_revision"] == dispatch.digest(current)
    assert result["provider_state_revision"] == "a" * 40
    assert result["source"] == "current-provider-canonical"
    reader.read_snapshot.assert_called_once()
    reader.observe.assert_not_called()
    reader.state_request.assert_not_called()


@pytest.mark.parametrize("mutation", ["unfinished-root", "unfinalized-child", "bad-child-hash", "busy",
                                     "inner-active", "wrong-factory", "wrong-repository", "wrong-request",
                                     "invalid-canonical", "catalog-conflict"])
def test_export_rejects_unverified_or_in_progress_authority_without_creating_output(tmp_path, mutation):
    canonical, binding, state, current = export_state()
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    child = state["records"]["pipeline-lifecycle/" + CHILD + ".json"]
    admission = state["records"]["lifecycle_admission_v1"]
    if mutation == "unfinished-root":
        root["status"] = "continuation-required"
    elif mutation == "unfinalized-child":
        child["finalization"]["status"] = "pending"
    elif mutation == "bad-child-hash":
        child["plan_hash"] = "f" * 64
    elif mutation == "busy":
        admission["claim"] = {"id": "another-unfinished-operation"}
    elif mutation == "inner-active":
        state["active"] = {"id": "active-native-worker"}
    elif mutation == "wrong-factory":
        canonical["factory"] = dict(canonical["factory"], id=PROJECT)
    elif mutation == "wrong-repository":
        state["repository"] = "https://github.com/acme/other"
    elif mutation == "wrong-request":
        canonical["request"] = dict(canonical["request"], source_commit="f" * 40)
    elif mutation == "invalid-canonical":
        admission["canonical"][FACTORY]["revision"] = "f" * 64
    else:
        admission["canonical"][PROJECT] = {"revision": "f" * 64, "document": {}}
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    with pytest.raises((dispatch.DispatchError, ValueError, RuntimeError)):
        dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                      "next/azurefactory", reader=reader)
    assert not (tmp_path / "next").exists()


def test_export_never_clobbers_existing_root(tmp_path):
    canonical, binding, state, current = export_state()
    root = tmp_path / "azurefactory"
    root.mkdir()
    (root / "register.json").write_text("keep-existing")
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    with pytest.raises((dispatch.DispatchError, ValueError)):
        dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                      "azurefactory", reader=reader)
    assert (root / "register.json").read_text() == "keep-existing"


def test_export_cli_has_no_dispatch_or_native_service_path(tmp_path, monkeypatch, capsys):
    canonical, binding, state, current = export_state()
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    monkeypatch.setattr(dispatch, "ProviderReceiptReader", lambda _: reader)
    monkeypatch.setattr(dispatch, "load_request", lambda *_: canonical)
    monkeypatch.setattr(dispatch, "operational_binding", lambda *_: binding)
    monkeypatch.setattr(dispatch, "dispatch_and_wait", lambda *_a, **_k: pytest.fail("No export dispatch"))
    monkeypatch.setattr(dispatch, "verify_checkout", lambda *_: pytest.fail("No deployment checkout needed"))
    args = ["--repo-root", str(tmp_path), "--request", "request.json", "--export-configuration",
            "--operation-id", PARENT, "--output-root", "next/azurefactory"]
    assert dispatch.main(args + ["--validate-only"]) == 0
    reader.read_snapshot.assert_not_called()
    assert not (tmp_path / "next").exists()
    assert dispatch.main(args) == 0
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["outcome"] == "configuration-exported"
    assert json.loads((tmp_path / "next/azurefactory/register.json").read_text()) == current


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_export_uses_authenticated_private_provider_gets_only(tmp_path, monkeypatch, provider):
    import provider_repository_state
    import pipeline_lifecycle_adapters
    canonical, binding, state, current = export_state(provider)
    calls = []
    class ReadOnlyHTTP:
        def request(self, method, url, body=None, raw=False):
            assert method == "GET" and body is None and "management.azure.com" not in url
            calls.append(url)
            if provider == "gha":
                if "/git/ref/" in url:
                    value = {"ref": provider_repository_state.STATE_REF,
                             "object": {"type": "commit", "sha": "a" * 40}}
                elif "/git/commits/" in url:
                    value = {"tree": {"sha": "b" * 40}}
                elif "/git/trees/" in url:
                    value = {"tree": [{"path": "state.json", "type": "blob", "sha": "c" * 40}]}
                elif "/git/blobs/" in url:
                    value = {"encoding": "base64", "content": base64.b64encode(json.dumps(state).encode()).decode()}
                else:
                    value = {"private": True, "full_name": "acme/factory"}
            elif "/refs?" in url:
                value = {"value": [{"name": provider_repository_state.STATE_REF, "objectId": "a" * 40}]}
            elif "/items?" in url:
                value = {"content": json.dumps(state)}
            else:
                value = {"project": {"visibility": "private"}, "remoteUrl": binding["repository"]}
            return 200, {}, value
    monkeypatch.setattr(pipeline_lifecycle_adapters, "build_service",
                        lambda *_a, **_k: pytest.fail("No native service during export"))
    reader = dispatch.ProviderReceiptReader(binding, transport=ReadOnlyHTTP())
    result = dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                           "next/azurefactory", reader=reader)
    assert result["configuration_revision"] == dispatch.digest(current)
    assert sum("/git/blobs/" in url or "/items?" in url for url in calls) == 1
    assert len(calls) >= 4
    frozen = dispatch.ProviderStateSnapshot("a" * 40, state)
    with pytest.raises(dispatch.DispatchError, match="read-only"):
        frozen.replace("a" * 40, {})


def test_export_preserves_current_factory_deletion_not_old_success_snapshot(tmp_path):
    canonical, binding, state, current = export_state()
    current.update(factories=[], configurations={}, bindings={}, ownership_evidence={})
    state["records"]["lifecycle_admission_v1"]["canonical"][FACTORY] = {
        "revision": dispatch.digest(current), "document": current}
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    result = dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                           "next/azurefactory", reader=reader)
    assert result["factory_present"] is False
    assert json.loads((tmp_path / "next/azurefactory/register.json").read_text()) == current
    assert not (tmp_path / "next/azurefactory/factories").exists()


def test_export_accepts_new_recovery_root_without_revalidating_failed_prior_as_success(tmp_path):
    canonical, binding, state, current = export_state()
    old = "99999999-9999-4999-8999-999999999999"
    root = state["records"]["pipeline-lifecycle/" + PARENT + ".json"]
    child = state["records"]["pipeline-lifecycle/" + CHILD + ".json"]
    root["plan"]["recovery_of"] = {"operation_id": old, "plan_hash": "f" * 64}
    root["plan_hash"] = lifecycle.digest(lifecycle.bound_plan(root))
    root["finalization"]["proof"]["plan_hash"] = root["plan_hash"]
    child["plan"]["continuation_of"]["plan_hash"] = root["plan_hash"]
    child["plan_hash"] = lifecycle.digest(lifecycle.bound_plan(child))
    child["finalization"]["proof"]["plan_hash"] = child["plan_hash"]
    root["completion"]["plan_hash"] = child["plan_hash"]
    state["records"]["pipeline-lifecycle/" + old + ".json"] = {
        "status": "recovered", "recovery_completion": {"operation_id": PARENT, "plan_hash": root["plan_hash"]}}
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    result = dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                           "next/azurefactory", reader=reader)
    assert result["operation_id"] == PARENT and result["completed_operation_id"] == CHILD
    assert result["configuration_revision"] == dispatch.digest(current)


def test_export_rejects_plaintext_secret_without_creating_output(tmp_path):
    canonical, binding, state, current = export_state()
    current["configurations"][FACTORY]["factory"]["client_secret"] = "must-not-export"
    state["records"]["lifecycle_admission_v1"]["canonical"][FACTORY] = {
        "revision": dispatch.digest(current), "document": current}
    reader = Mock()
    reader.read_snapshot.return_value = dispatch.ProviderStateSnapshot("a" * 40, state)
    with pytest.raises(ValueError):
        dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                      "next/azurefactory", reader=reader)
    assert not (tmp_path / "next").exists()


@pytest.mark.parametrize("destination", ["../outside/azurefactory", "new/not-a-register", ".env/azurefactory"])
def test_export_rejects_invalid_destination_before_provider_reads(tmp_path, destination):
    canonical, binding, state, current = export_state()
    reader = Mock()
    with pytest.raises((dispatch.DispatchError, ValueError)):
        dispatch.export_configuration(tmp_path, "request.json", canonical, binding, PARENT,
                                      destination, reader=reader)
    reader.read_snapshot.assert_not_called()
