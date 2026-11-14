"""Canonical transitions require a bounded proposal and verified native outcomes."""

import copy
import importlib
import socket
from unittest.mock import Mock

import pytest

from .test_pipeline_inputs import FACTORY, PROJECT, SCALE, SUB, register, request, inputs
from .test_pipeline_lifecycle_adapters import ProviderStore


@pytest.fixture(autouse=True)
def forbid_factory_api(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Canonical transitions must not call the Factory API or any network service")
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def transitions():
    return importlib.import_module("pipeline_lifecycle_configuration")


def snapshot(document, scenario=3):
    return inputs.resolve_document(document, request(scenario))


def canonical(document):
    from lifecycle_admission import revision
    return {"revision": revision(document), "document": copy.deepcopy(document)}


def record(document, scenario=3):
    from pipeline_lifecycle import digest
    resolved = snapshot(document, scenario)
    target = {"factory_id": FACTORY, "scaleset_id": SCALE}
    worker = {"status": "succeeded", "run_id": "native", "target": target,
              "resource_groups": [{"resource_id": f"/subscriptions/{SUB}/resourceGroups/project007",
                                   "owner": target | {"project_id": "007"}}], "ownership": []}
    native = {"status": "succeeded", "target": target, "deleted_resources": [], "deleted_resource_groups": []}
    receipt = {"status": "succeeded", "verified": True, "children": [{"native": native, "worker": worker}]}
    return {"operation_id": "11111111-1111-4111-8111-111111111111", "status": "succeeded",
            "snapshot": resolved, "plan_hash": "d" * 64, "snapshot_hash": digest(resolved),
            "plan": {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": []}]},
            "stages": [{"id": "lifecycle", "status": "succeeded", "observation": receipt}]}


def test_durable_document_uses_the_same_resolver_without_local_projection(tmp_path):
    from .test_pipeline_inputs import save
    document = register()
    save(tmp_path, document)
    assert inputs.resolve_document(document, request()) == inputs.resolve_request(tmp_path, request())


def test_generation_only_drift_is_review_evidence_not_a_gate(transitions):
    baseline = register()
    proposal = copy.deepcopy(baseline)
    proposal["generation"] = "different"
    change = transitions.prepare_change(snapshot(proposal), canonical(baseline))
    assert change["baseline"] == canonical(baseline)
    assert change["warnings"] == ["canonical-generation-drift"]
    assert change["changes"] == []


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_review_allows_selected_project_variables_not_silent_overrides(transitions, provider):
    baseline = register(provider)
    proposal = copy.deepcopy(baseline)
    proposal["configurations"][FACTORY]["variables"][PROJECT]["dev"]["enableAzureOpenAI"] = "true"
    resolved = inputs.resolve_document(proposal, request(provider=provider))
    change = transitions.prepare_change(resolved, canonical(baseline))
    assert change["changes"]
    assert change["proposal"] == proposal
    assert baseline["configurations"][FACTORY]["variables"][PROJECT]["dev"].get("enableAzureOpenAI") is None


@pytest.mark.parametrize("mutation", [
    lambda d: d["configurations"][FACTORY]["factory"].update(enableAzureOpenAI="true"),
    lambda d: d["configurations"][FACTORY]["variables"][PROJECT]["stage_prod"].update(enableAzureOpenAI="true"),
    lambda d: d["factories"][0].update(prefix="other-"),
    lambda d: d.update(ownership_evidence={"invented": {}}),
])
def test_project_proposal_cannot_change_other_scope_or_ownership(transitions, mutation):
    baseline = register()
    proposal = copy.deepcopy(baseline)
    mutation(proposal)
    with pytest.raises(ValueError):
        transitions.prepare_change(snapshot(proposal), canonical(baseline))


def test_added_scale_proposal_preserves_existing_projects_and_configuration(transitions):
    from pipeline_configuration import add_scale
    baseline = register()
    proposal = add_scale(baseline, "acme-ai", {
        "environment": "dev", "scale_set": "002", "tenant": baseline["factories"][0]["scale_sets"][0]["tenant_id"],
        "subscription": SUB, "provider": "gha", "cidr": "10.141.0.0/18", "max_projects": 7})
    resolved = inputs.resolve_document(proposal, request(2) | {"scale_set": "002"})
    assert transitions.prepare_change(resolved, canonical(baseline))["changes"]
    proposal["configurations"][FACTORY]["variables"][PROJECT]["dev"]["enableAzureOpenAI"] = "true"
    with pytest.raises(ValueError, match="outside-reviewed-scope"):
        transitions.prepare_change(inputs.resolve_document(proposal, resolved["request"]), canonical(baseline))


def test_project_placement_move_is_not_an_upsert(transitions):
    baseline = register()
    proposal = copy.deepcopy(baseline)
    proposal["factories"][0]["projects"][0]["storage_suffix"] = "002"
    with pytest.raises(ValueError, match="project-identity"):
        transitions.prepare_change(snapshot(proposal), canonical(baseline))


@pytest.mark.parametrize("scenario", [4, 5, 6])
def test_deletion_proposal_must_not_change_configuration(transitions, scenario):
    baseline = register()
    proposal = copy.deepcopy(baseline)
    proposal["configurations"][FACTORY]["variables"][PROJECT]["dev"]["enableAzureOpenAI"] = "false"
    with pytest.raises(ValueError, match="outside-reviewed-scope"):
        transitions.prepare_change(snapshot(proposal, scenario), canonical(baseline))


def test_deployment_promotion_records_verified_ownership_and_preserves_input(transitions):
    original = register()
    operation = record(original)
    promoted = transitions.completed_document(operation)
    assert promoted["factories"][0]["projects"][0]["status"] == "configured"
    assert promoted["factories"][0]["scale_sets"][0]["owned_resource_ids"] == [
        f"/subscriptions/{SUB}/resourceGroups/project007"]
    assert promoted["ownership_evidence"]
    assert original["factories"][0]["projects"][0]["status"] == "draft"
    assert promoted["generation"] != original["generation"]
    assert transitions.completed_document(operation) == promoted
    inputs.validate_register(promoted)


@pytest.mark.parametrize("verified,status", [(False, "succeeded"), (True, "reconciliation-required")])
def test_uncertain_receipt_cannot_promote_configuration(transitions, verified, status):
    operation = record(register())
    operation["stages"][0]["observation"].update(verified=verified, status=status)
    with pytest.raises(ValueError, match="verified"):
        transitions.completed_document(operation)


def test_service_only_project_delete_retains_definition_and_configuration(transitions):
    operation = record(register(), 4)
    operation["snapshot"]["request"]["include_keyvault_and_resource_group"] = False
    operation["stages"][0]["observation"]["children"][0]["worker"] = None
    promoted = transitions.completed_document(operation)
    assert promoted["factories"][0]["projects"] == register()["factories"][0]["projects"]
    assert promoted["configurations"] == register()["configurations"]


def test_project_group_delete_removes_only_the_selected_placement(transitions):
    operation = record(register(), 4)
    child = operation["stages"][0]["observation"]["children"][0]
    child["worker"] = None
    group = f"/subscriptions/{SUB}/resourceGroups/project007"
    child["native"]["deleted_resource_groups"] = [group]
    operation["plan"]["stages"][0]["manifests"] = [{
        "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "deletion": {"project_resource_group": group,
                     "resource_groups": [{"id": group, "delete": True}], "resources": []}}]
    promoted = transitions.completed_document(operation)
    assert promoted["factories"][0]["projects"] == []
    assert promoted["configurations"][FACTORY]["projects"] == {}
    assert promoted["configurations"][FACTORY]["variables"] == {}
    assert promoted["factories"][0]["scale_sets"]
    inputs.validate_register(promoted)


def test_project_definition_is_not_removed_without_verified_group_absence(transitions):
    operation = record(register(), 4)
    operation["stages"][0]["observation"]["children"][0]["worker"] = None
    with pytest.raises(ValueError, match="project-group-absence"):
        transitions.completed_document(operation)


@pytest.mark.parametrize("scenario", [5, 6])
def test_verified_scale_or_factory_delete_removes_only_its_definitions(transitions, scenario):
    document = register()
    operation = record(document, scenario)
    operation["stages"][0]["observation"]["children"][0]["worker"] = None
    group = f"/subscriptions/{SUB}/resourceGroups/common"
    operation["stages"][0]["observation"]["children"][0]["native"]["deleted_resource_groups"] = [group]
    operation["plan"]["stages"][0]["manifests"] = [{
        "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "deletion": {"resource_groups": [{"id": group, "delete": True}], "resources": []}}]
    result = transitions.completed_document(operation)
    if scenario == 5:
        assert result["factories"][0]["scale_sets"] == []
        assert result["factories"][0]["projects"] == []
        assert result["configurations"][FACTORY]["scale_sets"] == {}
    else:
        assert result["factories"] == []
        assert result["configurations"] == {}
        assert result["bindings"] == {}
    inputs.validate_register(result)


def test_provider_claim_uses_reviewed_baseline_and_promotes_atomically(transitions):
    import lifecycle_admission as shared
    from pipeline_lifecycle_admission import NativeAdmission
    document = register()
    provider = ProviderStore()
    provider.route = {"kind": "gha", "repository": provider.value["repository"]}
    scope = f"/subscriptions/{SUB}/resourceGroups/project007"
    policy = {"repository": provider.value["repository"], "factories": {FACTORY: {
        "all_writers": shared.PROTOCOL, "shared_scopes": [], "operations": sorted(shared.OPERATIONS),
        "routes": ["api", "pipeline"], "scopes": [scope]}}}
    provider.value["records"][shared.RECORD] = shared.new_record(policy, {FACTORY: document})
    proposal = copy.deepcopy(document)
    proposal["configurations"][FACTORY]["variables"][PROJECT]["dev"]["enableAzureOpenAI"] = "true"
    operation = record(proposal)
    operation["plan"]["stages"][0]["manifests"] = [{"locks": {"scopes": [scope], "common_dependencies": []}}]
    review, executor = Mock(), Mock()
    review.verify.return_value = {"provider": "gha", "run_id": "42", "attempt": 1}
    adapter = NativeAdmission(provider, review, executor)
    operation["plan"]["configuration"] = adapter.prepare(operation["snapshot"])
    operation["admission_claim"] = adapter.acquire(operation)
    committed = adapter.persist(operation)
    assert committed["document"] == transitions.completed_document(operation)
    assert adapter.guard.canonical_configuration(FACTORY) == committed
    assert provider.value["records"][shared.RECORD]["claim"] == operation["admission_claim"]
    fresh = NativeAdmission(provider, review, executor)
    assert fresh.persist(operation) == committed


def test_changed_live_baseline_does_not_overwrite_other_writers(transitions):
    baseline = register()
    change = transitions.prepare_change(snapshot(baseline), canonical(baseline))
    competing = copy.deepcopy(baseline)
    competing["configurations"][FACTORY]["factory"]["network_mode"] = "private"
    with pytest.raises(ValueError, match="canonical-configuration-changed"):
        transitions.assert_baseline(change, canonical(competing))


def test_reviewed_new_scope_extends_policy_in_the_same_claim_cas():
    import lifecycle_admission as shared
    from .test_pipeline_lifecycle_admission import admitted
    adapter, provider, review, _, operation = admitted()
    scope = f"/subscriptions/{SUB}/resourceGroups/new"
    original = copy.deepcopy(provider.value)
    policy = provider.value["records"][shared.RECORD]["policy"]["factories"][operation["snapshot"]["factory"]["id"]]
    request_value = {
        "factory_id": operation["snapshot"]["factory"]["id"], "operation_id": operation["operation_id"],
        "route": "pipeline", "operation": "bootstrap", "scopes": policy["scopes"],
        "configuration_revision": shared.revision(operation["snapshot"]["document"]),
        "review_digest": operation["plan_hash"]}
    authority = Mock()
    authority.authenticate.return_value = {
        "subject": "approved", "run_id": "42", "authorization_id": "native-review",
        "repository": provider.value["repository"], "route": "pipeline",
        "operation_id": operation["operation_id"], "review_digest": operation["plan_hash"],
        "scope_extension": [scope.lower()]}
    claim = shared.Admission(provider, authority).acquire(request_value, scope_extension=[scope])
    assert scope.lower() in claim["scopes"]
    assert provider.value["records"][shared.RECORD]["policy"]["factories"][claim["factory_id"]]["scopes"] == claim["scopes"]
    assert provider.value["enrollment"] == original["enrollment"]
    shared.Admission(provider, authority).assert_owned(claim)


def test_unapproved_scope_extension_never_writes_policy():
    import lifecycle_admission as shared
    from .test_pipeline_lifecycle_admission import admitted
    adapter, provider, _, _, operation = admitted()
    before = copy.deepcopy(provider.value)
    policy = before["records"][shared.RECORD]["policy"]["factories"][operation["snapshot"]["factory"]["id"]]
    request_value = {
        "factory_id": operation["snapshot"]["factory"]["id"], "operation_id": operation["operation_id"],
        "route": "pipeline", "operation": "bootstrap", "scopes": policy["scopes"],
        "configuration_revision": shared.revision(operation["snapshot"]["document"]),
        "review_digest": operation["plan_hash"]}
    authority = Mock()
    authority.authenticate.return_value = {
        "subject": "approved", "run_id": "42", "authorization_id": "native-review",
        "repository": provider.value["repository"], "route": "pipeline",
        "operation_id": operation["operation_id"], "review_digest": operation["plan_hash"]}
    with pytest.raises(shared.AdmissionError, match="scope-extension-authorization"):
        shared.Admission(provider, authority).acquire(
            request_value, scope_extension=[f"/subscriptions/{SUB}/resourceGroups/new"])
    assert provider.value == before


def test_uncoordinated_dependency_is_not_promoted_to_owned_scope():
    from .test_pipeline_lifecycle_admission import admitted
    adapter, provider, _, _, operation = admitted()
    before = copy.deepcopy(provider.value)
    operation["plan"]["stages"][0]["manifests"][0]["locks"]["common_dependencies"].append(
        f"/subscriptions/{SUB}/resourceGroups/shared-hub")
    with pytest.raises(ValueError, match="dependency"):
        adapter.acquire(operation)
    assert provider.value == before


def test_retained_owned_resources_keep_scale_inventory(transitions):
    operation = record(register(), 5)
    child = operation["stages"][0]["observation"]["children"][0]
    child["worker"] = None
    group = f"/subscriptions/{SUB}/resourceGroups/common"
    child["native"]["deleted_resource_groups"] = [group]
    retained = f"/subscriptions/{SUB}/resourceGroups/retained"
    operation["snapshot"]["document"]["factories"][0]["scale_sets"][0]["owned_resource_ids"] = [group, retained]
    operation["plan"]["stages"][0]["manifests"] = [{
        "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "deletion": {"resource_groups": [{"id": group, "delete": True},
                     {"id": retained, "delete": False, "owner": {"factory_id": FACTORY, "scaleset_id": SCALE}}],
                     "resources": []}}]
    result = transitions.completed_document(operation)
    assert result["factories"][0]["scale_sets"][0]["id"] == SCALE
    assert result["factories"][0]["scale_sets"][0]["owned_resource_ids"] == [retained]


def test_factory_deletion_can_complete_resource_deletions_with_all_groups_retained(transitions):
    operation = record(register(), 6)
    group = f"/subscriptions/{SUB}/resourceGroups/common"
    resource = group + "/providers/Microsoft.Storage/storageAccounts/removed"
    operation["stages"][0]["observation"]["children"][0].update(worker=None)
    operation["stages"][0]["observation"]["children"][0]["native"]["deleted_resources"] = [resource]
    operation["snapshot"]["document"]["factories"][0]["scale_sets"][0]["owned_resource_ids"] = [group, resource]
    operation["plan"]["stages"][0]["manifests"] = [{
        "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "deletion": {"resource_groups": [{"id": group, "delete": False,
                     "owner": {"factory_id": FACTORY, "scaleset_id": SCALE}}],
                     "resources": [{"id": resource, "delete": True}]}}]
    result = transitions.completed_document(operation)
    assert result["factories"][0]["scale_sets"][0]["owned_resource_ids"] == [group]


def test_deleted_project_placement_is_removed_even_when_common_scale_resources_survive(transitions):
    operation = record(register(), 6)
    project_group = f"/subscriptions/{SUB}/resourceGroups/project007"
    common = f"/subscriptions/{SUB}/resourceGroups/common"
    operation["stages"][0]["observation"]["children"][0].update(worker=None)
    operation["stages"][0]["observation"]["children"][0]["native"]["deleted_resource_groups"] = [project_group]
    operation["snapshot"]["document"]["factories"][0]["scale_sets"][0]["owned_resource_ids"] = [common, project_group]
    operation["plan"]["stages"][0]["manifests"] = [{
        "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "deletion": {"resource_groups": [
            {"id": common, "delete": False, "owner": {"factory_id": FACTORY, "scaleset_id": SCALE}},
            {"id": project_group, "delete": True,
             "owner": {"factory_id": FACTORY, "scaleset_id": SCALE, "project_id": "007"}}], "resources": []}}]
    result = transitions.completed_document(operation)
    assert result["factories"][0]["scale_sets"][0]["owned_resource_ids"] == [common]
    assert result["factories"][0]["projects"] == []
    assert result["configurations"][FACTORY]["variables"] == {}


def test_stage_configuration_cannot_silently_change_existing_prod_placement(transitions):
    from uuid import uuid4
    baseline = register()
    factory = baseline["factories"][0]
    scale = factory["scale_sets"][0]
    scale["environment"] = "stage"
    prod = copy.deepcopy(scale)
    prod.update(id=str(uuid4()), environment="prod")
    factory["scale_sets"].append(prod)
    project = factory["projects"][0]
    project["placements"] = [{"environment": "stage", "scale_set_id": SCALE},
                             {"environment": "prod", "scale_set_id": prod["id"]}]
    baseline["configurations"][FACTORY]["scale_sets"][prod["id"]] = {}
    values = copy.deepcopy(baseline["configurations"][FACTORY]["variables"][PROJECT]["dev"])
    values.update(test_sub_id=SUB, prod_sub_id=SUB)
    baseline["configurations"][FACTORY]["variables"][PROJECT]["stage_prod"] = values
    proposal = copy.deepcopy(baseline)
    proposal["configurations"][FACTORY]["variables"][PROJECT]["stage_prod"]["enableAzureOpenAI"] = "true"
    selected = inputs.resolve_document(proposal, request() | {"environment": "stage"})
    with pytest.raises(ValueError, match="shared-stage-prod"):
        transitions.prepare_change(selected, canonical(baseline))


def test_factory_deletion_preserves_unrelated_factory_exactly(transitions):
    from uuid import uuid4
    document = register()
    other = copy.deepcopy(document["factories"][0])
    ids = {old: str(uuid4()) for old in (FACTORY, PROJECT, SCALE)}
    other.update(id=ids[FACTORY], key="other-ai", prefix="other-")
    other["scale_sets"][0]["id"] = ids[SCALE]
    other["projects"][0]["id"] = ids[PROJECT]
    other["projects"][0]["placements"][0]["scale_set_id"] = ids[SCALE]
    cfg = copy.deepcopy(document["configurations"][FACTORY])
    cfg["scale_sets"][ids[SCALE]] = cfg["scale_sets"].pop(SCALE)
    cfg["projects"][ids[PROJECT]] = cfg["projects"].pop(PROJECT)
    cfg["variables"][ids[PROJECT]] = cfg["variables"].pop(PROJECT)
    cfg["variables"][ids[PROJECT]]["dev"]["admin_aifactoryPrefixRG"] = "other-"
    document["factories"].append(other)
    document["configurations"][ids[FACTORY]] = cfg
    operation = record(document, 6)
    child = operation["stages"][0]["observation"]["children"][0]
    child["worker"] = None
    group = f"/subscriptions/{SUB}/resourceGroups/common"
    child["native"]["deleted_resource_groups"] = [group]
    operation["plan"]["stages"][0]["manifests"] = [{
        "target": {"factory_id": FACTORY, "scaleset_id": SCALE},
        "deletion": {"resource_groups": [{"id": group, "delete": True}], "resources": []}}]
    result = transitions.completed_document(operation)
    assert result["factories"] == [other]
    assert result["configurations"] == {ids[FACTORY]: cfg}


@pytest.mark.parametrize("provider_kind", ["gha", "ado"])
def test_authorization_only_persistence_observes_its_atomic_canonical_write(provider_kind):
    import lifecycle_admission as shared
    import pipeline_lifecycle_authorization as authorization
    from pipeline_lifecycle import bound_plan, digest
    from pipeline_lifecycle_admission import NativeAdmission
    from .test_pipeline_lifecycle_authorization import fixture
    service, provider, _, stage, operation, _, _, review, _ = fixture(authorization, provider_kind)
    operation["plan"]["configuration"] = {
        "contract": "pipeline-configuration-v1",
        "baseline": stage["deletion_authorization"]["canonical"]["before"],
        "proposal": operation["snapshot"]["document"], "changes": [], "warnings": []}
    operation["plan_hash"] = digest(bound_plan(operation))
    operation["admission_claim"]["review_digest"] = operation["plan_hash"]
    provider.value["records"][shared.RECORD]["claim"] = copy.deepcopy(operation["admission_claim"])
    receipt = service.execute(stage, operation)
    operation["stages"][0].update(status="succeeded", receipt=receipt)
    executor = Mock()
    executor.observe.side_effect = service.observe
    adapter = NativeAdmission(provider, review, executor)
    writes = len(provider.writes)
    assert adapter.persist(operation) == receipt["canonical"]
    assert len(provider.writes) == writes
    executor.observe.assert_called_once_with(stage, operation)


def test_bootstrap_persists_binding_and_group_ownership_not_runtime_success(transitions):
    from .test_pipeline_lifecycle_adapters import snapshot as native_snapshot
    operation = record(register(), 1)
    binding = copy.deepcopy(native_snapshot()["binding"])
    group = f"/subscriptions/{SUB}/resourceGroups/project007"
    binding["targets"] = [{"scale_set_id": SCALE, "resource_group_ids": [group], "common_dependency_ids": []}]
    operation["status"] = "continuation-required"
    operation["plan"]["stages"] = [{
        "id": "bootstrap-enrollment", "kind": "bootstrap-enrollment",
        "enrollment": {"target": {"factory_id": FACTORY, "scaleset_id": SCALE},
                       "scopes": [group], "common_dependencies": [],
                       "route": {"kind": "gha", "repository": binding["repository"]}}}]
    operation["stages"] = [{"id": "bootstrap-enrollment", "status": "continuation-required", "receipt": {
        "status": "continuation-required", "verified": True, "runtime_ready": False,
        "enrollment_complete": True, "binding_candidate": binding,
        "continuation": {"requires_fresh_review": True, "stage": "common-and-project",
                         "factory_id": FACTORY, "scale_set_id": SCALE, "provider": "gha"}}}]
    result = transitions.completed_document(operation)
    assert result["bindings"][FACTORY]["gha"] == binding
    factory = result["factories"][0]
    assert factory["status"] == factory["scale_sets"][0]["status"] == factory["projects"][0]["status"] == "draft"
    assert factory["scale_sets"][0]["owned_resource_ids"] == [group]
    assert transitions.completed_document(operation) == result
    inputs.validate_register(result)


def test_identity_only_receipt_promotes_ownership_without_claiming_project_ready(transitions):
    operation = record(register())
    operation["status"] = operation["stages"][0]["status"] = "continuation-required"
    receipt = operation["stages"][0]["observation"]
    receipt.update(status="continuation-required", runtime_ready=False,
                   continuation={"requires_fresh_review": True, "stage": "foundry-project"})
    child = receipt["children"][0]
    for row in (child["native"], child["worker"]):
        row.update(continuation_required=True, completion="identity-only")
    result = transitions.completed_document(operation)
    factory = result["factories"][0]
    assert factory["projects"][0]["status"] == factory["status"] == "draft"
    assert factory["scale_sets"][0]["status"] == "draft"
    assert factory["scale_sets"][0]["owned_resource_ids"]


def test_verified_continuation_can_release_outer_claim_for_fresh_review():
    import lifecycle_admission as shared
    from .test_pipeline_lifecycle_admission import admitted
    adapter, provider, review, executor, operation = admitted()
    operation["admission_claim"] = adapter.acquire(operation)
    operation["status"] = "continuation-required"
    executor.observe.return_value = {"status": "continuation-required", "verified": True, "runtime_ready": False,
                                     "continuation": {"requires_fresh_review": True}}
    review.verify_finalizer.return_value = {"operation_id": operation["operation_id"],
                                           "plan_hash": operation["plan_hash"]}
    assert adapter.finalize(operation) == {"status": "released"}
    assert provider.value["records"][shared.RECORD]["claim"] is None
