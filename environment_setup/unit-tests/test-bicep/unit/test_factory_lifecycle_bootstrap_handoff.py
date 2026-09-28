"""Exact bootstrap receipts never grant ownership through an RG prefix."""

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from .test_factory_lifecycle import (
    fl, ClosureCloud, CORE_OWNER, GROUP, NSG, RULE, scoped_manifest, no_real_services,
    PlanCloud, RESOURCE, ROOT, simple_plan_closure, seal,
)


def exact_document(cloud):
    document, _ = scoped_manifest()
    plan_id, plan_hash = str(uuid4()), "c" * 64
    proof = {"contract": fl.EXACT_BOOTSTRAP_CONTRACT, "source_commit": document["source"]["commit"],
             "workflow_id": str(uuid4()), "evidence_hash": "d" * 64,
             "groups": {GROUP.lower(): {"plan_id": plan_id, "plan_hash": plan_hash}}, "resources": {}}
    for identifier, body in cloud.bodies.items():
        proof["resources"][identifier] = {
            "type": "microsoft.resources/resourcegroups" if identifier == GROUP.lower() else body["type"].lower(),
            "api_version": fl.RG_API if identifier == GROUP.lower() else "2024-05-01",
            "scope": GROUP.lower(), "body_hash": fl.digest(body), "etag": body.get("etag"),
            "disposition": "owned", "owner": copy.deepcopy(CORE_OWNER),
            "receipt": {"plan_id": plan_id, "plan_hash": plan_hash,
                        "receipt_hash": "e" * 64, "resource_id": identifier}}
    document["deployment"]["bootstrap_foundation"] = proof
    return document


def test_exact_bootstrap_untagged_child_requires_its_own_receipt():
    cloud = ClosureCloud()
    document = exact_document(cloud)
    proof = document["deployment"]["bootstrap_foundation"]
    snapshot = fl.bootstrap_ownership_snapshot(cloud, document)
    assert set(snapshot) == set(proof["resources"])
    assert snapshot[RULE.lower()]["owner"] == CORE_OWNER
    proof["resources"][RULE.lower()]["receipt"]["resource_id"] = NSG.lower()
    with pytest.raises(fl.Blocked, match="exact-bootstrap-resource-owner-required"):
        fl.bootstrap_ownership_snapshot(cloud, document)


@pytest.mark.parametrize("defect", ["missing-proof", "body", "etag", "type", "scope", "owner", "receipt", "source", "shared"])
def test_exact_bootstrap_instance_and_source_changes_block(defect):
    cloud = ClosureCloud()
    document = exact_document(cloud)
    proof = document["deployment"]["bootstrap_foundation"]
    row = proof["resources"][RULE.lower()]
    if defect == "missing-proof":
        del proof["resources"][RULE.lower()]
    elif defect == "body":
        cloud.bodies[RULE.lower()]["properties"]["priority"] = 200
    elif defect == "etag":
        cloud.bodies[RULE.lower()]["etag"] = '"recreated"'
    elif defect == "type":
        row["type"] = "microsoft.network/publicipaddresses"
    elif defect == "scope":
        row["scope"] = GROUP.lower() + "-other"
    elif defect == "owner":
        row["owner"]["factory_id"] = "foreign"
    elif defect == "receipt":
        row["receipt"]["receipt_hash"] = ""
    elif defect == "source":
        proof["source_commit"] = "f" * 40
    else:
        cloud.bodies[RULE.lower()]["tags"] = {"aifactory.shared": "true"}
        row["body_hash"] = fl.digest(cloud.bodies[RULE.lower()])
    with pytest.raises(fl.Blocked):
        fl.bootstrap_ownership_snapshot(cloud, document)


def test_preserved_prerequisite_never_has_an_owner_or_accepts_writes():
    cloud = ClosureCloud()
    document = exact_document(cloud)
    row = document["deployment"]["bootstrap_foundation"]["resources"][RULE.lower()]
    row.pop("owner")
    row.update(disposition="preserve", preservation="bootstrap-prerequisite")
    snapshot = fl.bootstrap_ownership_snapshot(cloud, document)
    assert snapshot[RULE.lower()] == {"body_hash": row["body_hash"], "preserve": True}
    for change in ("Create", "Modify"):
        with pytest.raises(fl.Blocked, match="bootstrap-prerequisite-write-forbidden"):
            fl.verify_bootstrap_preservation(document, [{"resource_id": RULE, "change_type": change}])
    fl.verify_bootstrap_preservation(document, [{"resource_id": RULE, "change_type": "NoChange"}])
    row["owner"] = CORE_OWNER
    with pytest.raises(fl.Blocked, match="cannot-authorize-ownership"):
        fl.bootstrap_ownership_snapshot(cloud, document)


def test_legacy_group_proof_does_not_inherit_untagged_children():
    cloud = ClosureCloud()
    document = exact_document(cloud)
    proof = document["deployment"]["bootstrap_foundation"]
    document["deployment"]["bootstrap_foundation"] = {
        "contract": "created-group-ownership-v1", "groups": proof["groups"]}
    with pytest.raises(fl.Blocked, match="exact-bootstrap-resource-proof-required"):
        fl.bootstrap_ownership_snapshot(cloud, document)
    del document["deployment"]["bootstrap_foundation"]
    assert fl.bootstrap_ownership_snapshot(cloud, document) == {}


class MetadataCloud(ClosureCloud):
    action_type = "networkSecurityGroups/listDnsForwardingRulesets"

    def provider_schema(self, namespace):
        result = super().provider_schema(namespace)
        result["resourceTypes"].append({"resourceType": self.action_type, "apiVersions": ["2024-05-01"]})
        return result

    def provider_operations(self, namespace):
        return [namespace.lower() + "/" + kind.lower() + "/" + action
                for kind in ("networkSecurityGroups", "networkSecurityGroups/securityRules")
                for action in ("read", "write", "delete")] + [
                    namespace.lower() + "/" + self.action_type.lower() + "/action"]


def test_resource_closure_excludes_proven_action_metadata_not_actual_dependencies():
    cloud = MetadataCloud()
    external = GROUP.replace("reviewed", "retained-hub") + "/providers/Microsoft.Network/virtualNetworks/hub"
    cloud.bodies[NSG.lower()]["properties"]["linkedResource"] = {"id": external}
    closure, _ = fl.collect_resource_closure(cloud, [GROUP])
    assert set(closure["resources"]) == {NSG.lower(), RULE.lower()}
    assert external.lower() in closure["references"][NSG.lower()]
    assert closure["collections"][NSG.lower() + "/listdnsforwardingrulesets"]["non_resource_metadata"]
    assert external.lower() not in closure["resources"]


@pytest.mark.parametrize("reference", [
    NSG + "/listDnsForwardingRulesets/not-a-resource",
    GROUP + "/providers/Unknown.Provider/resources/foreign",
    NSG + "/malformed-resource-id",
])
def test_unknown_actual_resource_references_fail_closed(reference):
    cloud = MetadataCloud()
    cloud.bodies[NSG.lower()]["properties"]["actualDependency"] = {"id": reference}
    with pytest.raises(fl.Blocked):
        fl.collect_resource_closure(cloud, [GROUP])


@pytest.mark.parametrize("change", ["Delete", "Deploy", "Unsupported"])
def test_exact_bootstrap_never_relaxes_destructive_or_unresolved_what_if(change):
    proof = {RULE.lower(): {"body_hash": "a" * 64}}
    with pytest.raises(fl.Blocked):
        fl.arm_changes({"changes": [{"resourceId": RULE, "changeType": change}]}, proof)


@pytest.mark.parametrize("defect", [None, "unknown", "changed-after", "delta", "error", "unsupported"])
def test_ignored_incremental_resources_require_exact_fresh_proof(defect):
    row = {"resourceId": RULE, "changeType": "Ignore", "before": {"id": RULE}, "after": {"id": RULE}}
    proof = {RULE.lower(): {"body_hash": "a" * 64}}
    if defect == "unknown":
        proof.clear()
    elif defect == "changed-after":
        row["after"]["changed"] = True
    elif defect == "delta":
        row["delta"] = [{"propertyChangeType": "Delete"}]
    elif defect == "error":
        row["error"] = {"code": "ReadFailed"}
    elif defect == "unsupported":
        row["unsupportedReason"] = "Resource expansion failed"
    if defect:
        with pytest.raises(fl.Blocked, match="exact-instance-proof"):
            fl.arm_changes({"changes": [row]}, proof)
    else:
        assert fl.arm_changes({"changes": [row]}, proof) == [{
            "resource_id": RULE.lower(), "change_type": "NoChange",
            "before_hash": "a" * 64, "after_hash": "a" * 64}]


@pytest.mark.parametrize("scope,wrong", [("subscription", False), ("resource-group", False),
                                       ("subscription", True), ("resource-group", True)])
def test_preserved_network_supports_real_subscription_template_scope(monkeypatch, scope, wrong):
    document, _ = scoped_manifest()
    step = document["deployment"]["steps"][1]
    step.update(scope=scope, resource_group=GROUP if not wrong else GROUP + "-foreign")
    vnet = GROUP + "/providers/Microsoft.Network/virtualNetworks/vnet"
    template = {"parameters": {}}
    parameters = {"commonNetworkProfile": "preserve-v1", "preservationPlan": {
        "createVnet": False, "createSubnets": [], "createNetworkSecurityGroups": []}}
    desired = {"factory_id": document["target"]["factory_id"], "vnet_id": vnet, "parameters": {},
               "approved_address_prefixes": ["10.0.0.0/24"]}
    helper = SimpleNamespace(
        digest=fl.digest, _source_files=lambda root: {}, validate_compiled_capability=lambda template: None,
        _canonical=lambda desired: (None, vnet, [], None), required_resource_ids=lambda desired: [vnet],
        _validate_existing=lambda body, identifier: None, API_VERSION="2023-11-01")
    step.update(template_hash=fl.digest(template), parameters=parameters, network_preservation={
        "contract": "preserve-v1-runtime-proof", "source_payload_sha256": fl.digest({}),
        "desired": desired, "expected_resource_ids": [vnet]})
    if wrong and scope == "subscription":
        step["resource_groups"] = [GROUP + "-foreign"]
    cloud = SimpleNamespace(arm=lambda *args, **kwargs: (200, {}, {
        "properties": {"subnets": [], "virtualNetworkPeerings": [],
                       "addressSpace": {"addressPrefixes": ["10.0.0.0/24"]}}}))
    monkeypatch.setattr(fl, "_network_preservation_helper", lambda root: helper)
    if wrong:
        with pytest.raises(fl.Blocked, match="target-mismatch"):
            fl.verify_preserved_network(cloud, document, step, ROOT, template=template, freeze=True)
    else:
        fl.verify_preserved_network(cloud, document, step, ROOT, template=template, freeze=True)
        fl.verify_preserved_network(cloud, document, step, ROOT, template=template)


@pytest.mark.parametrize("valid", [True, False])
def test_keyvault_encoded_collection_exception_is_narrow(valid):
    cloud = fl.Cloud({"identity": {"object_id": str(uuid4())}}, opener=Mock())
    cloud.request = lambda *args, **kwargs: (200, {}, "[]")
    provider = "Microsoft.KeyVault/vaults" if valid else "Foreign.Provider/resources"
    path = GROUP + "/providers/" + provider + "/vault/eventGridFilters"
    if valid:
        assert cloud.collection(path, "2024-11-01") == ([], None)
    else:
        with pytest.raises(fl.Blocked, match="incomplete-child-inventory"):
            cloud.collection(path, "2024-11-01")


def test_worker_preserves_exact_bootstrap_resources_without_claiming_ownership(monkeypatch):
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    document["deployment"]["bootstrap_foundation"] = exact_document(cloud)["deployment"]["bootstrap_foundation"]
    row = document["deployment"]["bootstrap_foundation"]["resources"][RESOURCE.lower()]
    row.pop("owner")
    row.update(disposition="preserve", preservation="bootstrap-prerequisite")

    def closure(cloud, scopes, resource_versions=None):
        result, bodies = simple_plan_closure(cloud, scopes, resource_versions)
        result["groups"][GROUP.lower()] = {"body_hash": fl.digest(bodies[GROUP.lower()]), "etag": None}
        return result, bodies

    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    document["deployment"]["bootstrap_ownership"] = fl.bootstrap_ownership_snapshot(cloud, document)
    unchanged = {"resourceId": RESOURCE, "changeType": "Ignore",
                 "before": cloud.bodies[RESOURCE.lower()], "after": cloud.bodies[RESOURCE.lower()]}
    original_request = cloud.request
    cloud.request = lambda method, url, *args, **kwargs: (
        (200, {}, {"changes": [unchanged]}) if "/whatIf?" in url
        else original_request(method, url, *args, **kwargs))
    document["deployment"]["changes"] = fl.arm_changes(
        {"changes": [unchanged]}, document["deployment"]["bootstrap_foundation"]["resources"])
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert result["status"] == "succeeded"
    assert result["ownership"] == []
    assert result["bootstrap_preserved"] == {RESOURCE.lower(): row}
    assert len(cloud.arm_writes) == 1


def test_inline_delegations_and_external_provider_owned_references_are_not_owned():
    vnet = GROUP + "/providers/Microsoft.Network/virtualNetworks/vnet"
    subnet = vnet + "/subnets/delegated"
    delegation = subnet + "/delegations/app"
    external = "/subscriptions/" + str(uuid4()) + "/resourceGroups/provider/providers/Microsoft.App/environments/managed"

    class NetworkCloud(ClosureCloud):
        def __init__(self):
            super().__init__()
            self.bodies = {GROUP.lower(): self.bodies[GROUP.lower()],
                vnet.lower(): {"id": vnet, "type": "Microsoft.Network/virtualNetworks",
                              "properties": {"subnets": [{"id": subnet}]}},
                subnet.lower(): {"id": subnet, "type": "Microsoft.Network/virtualNetworks/subnets",
                    "properties": {"delegations": [{"id": delegation}], "serviceAssociationLinks": [{"linkedResourceId": external}]}}}

        def list_resources(self, scope):
            return [self.bodies[vnet.lower()]]

        def provider_schema(self, namespace):
            return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2023-11-01"]}
                                     for kind in ("virtualNetworks", "virtualNetworks/subnets", "virtualNetworks/subnets/delegations")]}

        def collection(self, path, api_version, extension=False):
            if path.lower() == vnet.lower() + "/subnets":
                return [self.bodies[subnet.lower()]], None
            assert extension
            return [], None

    cloud = NetworkCloud()
    closure, bodies = fl.collect_resource_closure(cloud, [GROUP])
    assert set(bodies) == {GROUP.lower(), vnet.lower(), subnet.lower()}
    assert closure["inline"][delegation.lower()] == {
        "parent_id": subnet.lower(), "parent_body_hash": fl.digest(bodies[subnet.lower()])}
    assert external.lower() in closure["references"][subnet.lower()]
    assert external.lower() not in closure["resources"]


def test_schema_tag_support_does_not_silently_omit_unknown_writable_children():
    class TaggedCloud(MetadataCloud):
        def provider_schema(self, namespace):
            result = super().provider_schema(namespace)
            result["resourceTypes"].append({"resourceType": "networkSecurityGroups/extra",
                "apiVersions": ["2024-05-01"], "capabilities": "SupportsTags"})
            return result

        def collection(self, path, api_version, extension=False):
            if path.lower().endswith("/extra"):
                self.enumerated = True
                return [], None
            return super().collection(path, api_version, extension=extension)

    cloud = TaggedCloud()
    fl.collect_resource_closure(cloud, [GROUP])
    assert cloud.enumerated


@pytest.fixture
def reviewed_children(monkeypatch):
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    document["deployment"]["bootstrap_foundation"] = exact_document(cloud)["deployment"]["bootstrap_foundation"]
    proof = document["deployment"]["bootstrap_foundation"]
    vm = GROUP.lower() + "/providers/microsoft.compute/virtualmachines/runner"
    extension = vm + "/extensions/mde.linux"
    command = vm + "/runcommands/register-aifactory-gha-20260927202821-19519"
    script = (Path(fl.__file__).parent / "runner-registration.sh").read_text(encoding="utf-8").strip()
    additions = {
        vm: {"id": vm, "type": "Microsoft.Compute/virtualMachines", "properties": {"provisioningState": "Succeeded"}},
        extension: {"id": extension, "type": "Microsoft.Compute/virtualMachines/extensions", "properties": {
            "publisher": "Microsoft.Azure.AzureDefenderForServers", "type": "MDE.Linux",
            "provisioningState": "Failed", "settings": {"azureResourceId": vm}}},
        command: {"id": command, "type": "Microsoft.Compute/virtualMachines/runCommands", "properties": {
            "provisioningState": "Succeeded", "source": {"script": script}}},
    }
    cloud.bodies.update(additions)
    metadata = {key: {"type": body["type"].lower(), "api_version": "2024-03-01", "scope": GROUP.lower(),
                      "body_hash": fl.digest(body), "etag": None} for key, body in additions.items()}
    vm_receipt = {"plan_id": str(uuid4()), "plan_hash": "1" * 64, "receipt_hash": "2" * 64, "resource_id": vm}
    proof["resources"][vm] = {**metadata[vm], "disposition": "preserve", "preservation": "bootstrap-prerequisite",
                              "receipt": vm_receipt}
    proposal = {
        "owner_hash": "3" * 64, "workflow_id": proof["workflow_id"], "source_commit": document["source"]["commit"],
        "bootstrap_hash": proof["evidence_hash"], "operator_id": document["identity"]["object_id"],
        "deployment_object_id": document["identity"]["deployment_object_id"], "scopes": sorted(proof["groups"]),
        "target": {key: document["target"][key] for key in
                   ("factory_id", "scaleset_id", "tenant_id", "subscription_id", "region")},
        "runner": {"resource_id": vm, "body_hash": metadata[vm]["body_hash"],
                   "receipt_hash": fl.digest(vm_receipt), "request_hash": "4" * 64},
        "resources": {
            extension: {**metadata[extension], "provisioning_state": "Failed",
                        "publisher": "Microsoft.Azure.AzureDefenderForServers", "extension_type": "MDE.Linux"},
            command: {**metadata[command], "provisioning_state": "Succeeded", "execution_state": "Succeeded",
                      "exit_code": 0, "script_sha256": hashlib.sha256(script.encode()).hexdigest()}},
        "writes": [], "deletes": [], "ownership_grants": [],
        "warnings": [{"code": "defender-security-readiness-unverified", "resource_id": extension,
                      "provisioning_state": "Failed"}]}
    permit = {"contract": fl.PRESERVATION_PERMIT_CONTRACT, "approved": True, "review_id": str(uuid4()),
              "owner_hash": proposal["owner_hash"], "workflow_id": proof["workflow_id"],
              "proposal_hash": fl.digest(proposal), "proposal": proposal}
    permit["approval_hash"] = fl.digest(permit)
    proof["preservation_permit"] = permit
    for key in (extension, command):
        proof["resources"][key] = {**metadata[key], "disposition": "preserve", "preservation": "reviewed-instance",
                                    "permit_hash": permit["approval_hash"]}

    def closure(cloud, scopes, resource_versions=None):
        resources = {key: body for key, body in cloud.bodies.items() if key != GROUP.lower()}
        return ({"groups": {GROUP.lower(): {"body_hash": fl.digest(cloud.bodies[GROUP.lower()]), "etag": None}},
                 "resources": {key: {"type": fl.resource_type_from_id(key), "api_version": "2024-03-01",
                                    "body_hash": fl.digest(body), "etag": body.get("etag")}
                               for key, body in resources.items()}}, copy.deepcopy(cloud.bodies))

    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    execution = {"executionState": "Succeeded", "exitCode": 0}
    original_request = cloud.request

    def request(method, url, *args, **kwargs):
        if "%24expand=instanceView" in url:
            result = copy.deepcopy(cloud.bodies[command])
            result["properties"]["instanceView"] = execution
            return 200, {}, result
        if "/whatIf?" in url:
            return 200, {}, {"changes": [{"resourceId": key, "changeType": "NoChange"}
                                        for key in sorted(cloud.bodies)]}
        return original_request(method, url, *args, **kwargs)

    cloud.request = request
    return SimpleNamespace(**locals())


def test_native_exact_permit_keeps_failed_defender_visible_without_ownership(reviewed_children):
    case = reviewed_children
    snapshot = fl.bootstrap_ownership_snapshot(case.cloud, case.document)
    for key in (case.extension, case.command):
        assert snapshot[key] == {"body_hash": case.metadata[key]["body_hash"], "preserve": True}
        assert "receipt" not in case.proof["resources"][key]
        for action in ("Create", "Modify", "Delete"):
            with pytest.raises(fl.Blocked, match="write-forbidden"):
                fl.verify_bootstrap_preservation(case.document, [{"resource_id": key, "change_type": action}])
    assert case.proposal["warnings"][0]["provisioning_state"] == "Failed"


@pytest.mark.parametrize("defect", ["unapproved", "source", "principal", "warning", "scope", "body",
                                   "running", "ownership", "receipt", "unknown", "delete-operation"])
def test_native_preservation_permit_fails_closed(reviewed_children, defect):
    case = reviewed_children
    if defect == "unapproved":
        case.permit["approved"] = False
    elif defect == "source":
        case.document["source"]["commit"] = "f" * 40
    elif defect == "principal":
        case.document["identity"]["object_id"] = str(uuid4())
    elif defect == "warning":
        case.proposal["warnings"] = []
    elif defect == "scope":
        case.proof["resources"][case.extension]["scope"] = GROUP.lower() + "-foreign"
    elif defect == "body":
        case.cloud.bodies[case.extension]["properties"]["provisioningState"] = "Updating"
    elif defect == "running":
        case.execution["executionState"] = "Running"
    elif defect == "ownership":
        case.proof["resources"][case.extension].update(disposition="owned", owner=CORE_OWNER)
    elif defect == "receipt":
        case.proof["resources"][case.command]["receipt"] = case.vm_receipt
    elif defect == "unknown":
        case.cloud.bodies[case.vm + "/extensions/unknown"] = {"id": case.vm + "/extensions/unknown"}
    elif defect == "delete-operation":
        case.document["operation"] = "delete"
    with pytest.raises(fl.Blocked):
        fl.bootstrap_ownership_snapshot(case.cloud, case.document)


def _execute_reviewed_worker(case, monkeypatch, *, after_apply=None, creates=()):
    document, cloud = case.document, case.cloud
    document["deployment"]["bootstrap_ownership"] = fl.bootstrap_ownership_snapshot(cloud, document)
    changes = [{"resourceId": key, "changeType": "NoChange"} for key in sorted(cloud.bodies)]
    changes += [{"resourceId": body["id"], "changeType": "Create", "after": body} for body in creates]
    document["deployment"]["changes"] = fl.arm_changes({"changes": changes})
    original_request = cloud.request

    def request(method, url, *args, **kwargs):
        if "/whatIf?" in url:
            return 200, {}, {"changes": copy.deepcopy(changes)}
        result = original_request(method, url, *args, **kwargs)
        if method == "PUT" and url.startswith(fl.ARM):
            for body in creates:
                cloud.bodies[body["id"].lower()] = copy.deepcopy(body)
            if after_apply:
                after_apply()
        return result

    cloud.request = request
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    return fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())


def test_worker_carries_exact_permit_to_later_project_without_ownership(reviewed_children, monkeypatch):
    case = reviewed_children
    result = _execute_reviewed_worker(case, monkeypatch)
    assert result["status"] == "succeeded", result
    assert not {case.extension, case.command} & {row["resource_id"] for row in result["ownership"]}
    assert result["bootstrap_preservation_permit"] == case.permit
    assert all(result["bootstrap_preserved"][key]["permit_hash"] == case.permit["approval_hash"]
               for key in (case.extension, case.command))
    assert fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document) == result


@pytest.mark.parametrize("tagged", [False, True])
@pytest.mark.parametrize("boundary", ["runner", "nsg"])
def test_worker_rejects_late_unreviewed_preserved_descendants_before_adoption(reviewed_children, monkeypatch, tagged, boundary):
    case = reviewed_children
    parent = case.vm
    kind = "Microsoft.Compute/virtualMachines/extensions"
    if boundary == "nsg":
        parent = GROUP.lower() + "/providers/microsoft.network/networksecuritygroups/retained"
        body = {"id": parent, "type": "Microsoft.Network/networkSecurityGroups", "properties": {}}
        case.cloud.bodies[parent] = body
        case.proof["resources"][parent] = {
            "type": body["type"].lower(), "api_version": "2024-03-01", "scope": GROUP.lower(),
            "body_hash": fl.digest(body), "etag": None, "disposition": "preserve",
            "preservation": "bootstrap-prerequisite", "receipt": {**case.vm_receipt, "resource_id": parent}}
        kind = "Microsoft.Network/networkSecurityGroups/securityRules"
    child = parent + ("/extensions/unreviewed" if boundary == "runner" else "/securityrules/unreviewed")
    body = {"id": child, "type": kind, "properties": {"provisioningState": "Succeeded"}}
    if tagged:
        body["tags"] = {fl.TAG_KEYS[key]: value for key, value in CORE_OWNER.items()}
    result = _execute_reviewed_worker(case, monkeypatch, after_apply=lambda: case.cloud.bodies.update({child: body}))
    assert len(case.cloud.arm_writes) == 1
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "bootstrap-preserved-descendant-unreviewed"
    assert not result["ownership"]
    with pytest.raises(fl.Blocked, match="scoped-worker-receipt-unverified"):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)


@pytest.mark.parametrize("missing", ["vm", "extension", "command"])
def test_worker_rejects_preserved_instances_missing_from_final_closure(reviewed_children, monkeypatch, missing):
    case = reviewed_children
    identifier = getattr(case, missing)
    result = _execute_reviewed_worker(case, monkeypatch, after_apply=lambda: case.cloud.bodies.pop(identifier))
    assert len(case.cloud.arm_writes) == 1
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "bootstrap-preserved-resource-missing-after-deployment"
    assert not result["ownership"] and "bootstrap_preserved" not in result
    with pytest.raises(fl.Blocked, match="scoped-worker-receipt-unverified"):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)


@pytest.mark.parametrize("changed", ["body", "etag", "type", "api_version"])
def test_worker_requires_approved_final_preserved_fingerprints(reviewed_children, monkeypatch, changed):
    case = reviewed_children
    original = fl.collect_resource_closure

    def closure(cloud, scopes, resource_versions=None):
        result, bodies = original(cloud, scopes, resource_versions)
        if cloud.arm_writes:
            if changed == "body":
                bodies[case.extension]["properties"]["changed"] = True
                result["resources"][case.extension]["body_hash"] = fl.digest(bodies[case.extension])
            else:
                result["resources"][case.extension][changed] = "changed"
        return result, bodies

    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    result = _execute_reviewed_worker(case, monkeypatch)
    assert len(case.cloud.arm_writes) == 1
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "bootstrap-preserved-resource-changed-during-deployment"
    assert not result["ownership"]
    with pytest.raises(fl.Blocked, match="scoped-worker-receipt-unverified"):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)


def test_worker_keeps_reviewed_ordinary_new_workload_ownership(reviewed_children, monkeypatch):
    case = reviewed_children
    identifier = GROUP.lower() + "/providers/microsoft.compute/disks/workload"
    body = {"id": identifier, "type": "Microsoft.Compute/disks", "properties": {"provisioningState": "Succeeded"}}
    result = _execute_reviewed_worker(case, monkeypatch, creates=[body])
    assert result["status"] == "succeeded", result
    assert next(row for row in result["ownership"] if row["resource_id"] == identifier)["owner"] == CORE_OWNER
    assert fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document) == result


@pytest.mark.parametrize("defect", ["new-descendant", "missing-child", "changed-child", "no-final-closure",
                                  "closure-hash", "ownership-only-descendant", "preserved-owned"])
def test_receipt_verifier_rejects_unproven_final_preservation(reviewed_children, monkeypatch, defect):
    case = reviewed_children
    result = _execute_reviewed_worker(case, monkeypatch)
    assert result["status"] == "succeeded"
    closure, _ = case.closure(case.cloud, [GROUP])
    result["bootstrap_final_closure"] = closure
    child = case.vm + "/extensions/unreviewed"
    metadata = {"type": "microsoft.compute/virtualmachines/extensions", "api_version": "2024-03-01",
                "body_hash": "f" * 64, "etag": None}
    if defect in ("new-descendant", "ownership-only-descendant"):
        result["ownership"].append({"resource_id": child, "owner": CORE_OWNER, **metadata})
        if defect == "new-descendant":
            closure["resources"][child] = metadata
    elif defect == "missing-child":
        del closure["resources"][case.extension]
    elif defect == "changed-child":
        closure["resources"][case.extension]["body_hash"] = "f" * 64
    elif defect == "preserved-owned":
        result["ownership"].append({"resource_id": case.extension, "owner": CORE_OWNER,
                                    **closure["resources"][case.extension]})
    result["inventory_closure_hash"] = fl.digest(closure)
    if defect == "no-final-closure":
        result.pop("bootstrap_final_closure")
    elif defect == "closure-hash":
        result["inventory_closure_hash"] = "f" * 64
    case.cloud.runs["runs/" + case.document["run_id"] + ".worker.json"] = result
    with pytest.raises(fl.Blocked):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)


@pytest.mark.parametrize("field,value", [("target", None), ("runner", []), ("warnings", ["invalid"]),
                                       ("resources", []), ("writes", ["unauthorized"])])
def test_native_resealed_malformed_permits_fail_closed(reviewed_children, field, value):
    case = reviewed_children
    case.proposal[field] = value
    case.permit["proposal_hash"] = fl.digest(case.proposal)
    case.permit["approval_hash"] = fl.digest({key: value for key, value in case.permit.items()
                                            if key != "approval_hash"})
    with pytest.raises(fl.Blocked):
        fl.validate_preservation_permit(case.document)
