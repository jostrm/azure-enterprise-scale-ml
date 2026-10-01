"""Exact bootstrap receipts never grant ownership through an RG prefix."""

import base64
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from .test_factory_lifecycle import (
    fl, ClosureCloud, CORE_OWNER, GROUP, NSG, RULE, scoped_manifest, no_real_services,
    PlanCloud, RESOURCE, ROOT, simple_plan_closure, seal, owned_group_manifest,
    FakeCloud, manifest, setup_execute, workspace,
    scoped_enrollment, TENANT, SUB, COMMON,
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


@pytest.mark.parametrize("fields", [["body_hash"], ["etag"], ["body_hash", "etag"]])
def test_instance_diagnostic_names_exact_comparisons_without_values(fields):
    cloud = ClosureCloud()
    document = exact_document(cloud)
    baseline = document["deployment"]["bootstrap_foundation"]["resources"][RULE.lower()]
    if "body_hash" in fields:
        cloud.bodies[RULE.lower()]["properties"]["priority"] = "sensitive-raw-property"
    if "etag" in fields:
        baseline["etag"] = "sensitive-etag-value"
    with pytest.raises(fl.Blocked) as raised:
        fl.bootstrap_ownership_snapshot(cloud, document)
    error = raised.value
    assert error.code == str(error) == "bootstrap-resource-instance-changed"
    assert fl.failure_fields(error, "unused") == {
        "error_code": error.code,
        "error_diagnostic": {"resource_id": RULE.lower(), "failed_comparisons": fields}}
    text = json.dumps(fl.failure_fields(error, "unused"))
    assert "sensitive" not in text and baseline["body_hash"] not in text


@pytest.mark.parametrize("identifier", [
    RULE + "?token=private", RULE + "#private", RULE + "\nprivate", RULE + "/../private",
    RULE + "/%61/private", "https://management.azure.com" + RULE, RULE + "K",
    "/subscriptions/not-a-guid/resourcegroups/private", RULE + "x" * 2048,
])
def test_instance_diagnostic_rejects_noncanonical_resource_identifiers(identifier):
    with pytest.raises(fl.Blocked) as raised:
        fl.require_bootstrap_instance(identifier, body_hash=False, etag=True)
    assert fl.failure_fields(raised.value, "unused") == {"error_code": "bootstrap-resource-instance-changed"}


@pytest.mark.parametrize("identifier", [
    GROUP, RULE, GROUP + "/providers/Microsoft.Network/privateDnsZones/example.internal/SOA/@",
])
def test_instance_diagnostic_accepts_group_nested_resource_and_dns_record(identifier):
    fl.require_bootstrap_instance(identifier, body_hash=True, etag=True)
    with pytest.raises(fl.Blocked) as raised:
        fl.require_bootstrap_instance(identifier, body_hash=True, etag=False)
    assert raised.value.error_diagnostic == {"resource_id": identifier, "failed_comparisons": ["etag"]}


@pytest.mark.parametrize("detail", [
    None, {"resource_id": RULE, "failed_comparisons": []},
    {"resource_id": RULE, "failed_comparisons": ["body_hash", "body_hash"]},
    {"resource_id": RULE, "failed_comparisons": ["raw-secret"]},
    {"resource_id": RULE, "failed_comparisons": "body_hash"},
    {"resource_id": RULE, "failed_comparisons": [{}]},
    {"resource_id": RULE, "failed_comparisons": ["etag"], "body": "private"},
])
def test_instance_diagnostic_is_closed_and_revalidated_before_serialization(detail):
    error = fl.Blocked("bootstrap-resource-instance-changed")
    error.error_diagnostic = detail
    assert fl.failure_fields(error, "unused") == {"error_code": error.code}
    unrelated = fl.Blocked("other-code", error_diagnostic={
        "resource_id": RULE, "failed_comparisons": ["etag"]})
    assert fl.failure_fields(unrelated, "unused") == {"error_code": "other-code"}


def _instance_failure(*args, **kwargs):
    fl.require_bootstrap_instance(RULE.lower(), body_hash=False, etag=True)


def test_instance_diagnostic_survives_native_cli_without_stderr(monkeypatch, capsys):
    monkeypatch.setattr(fl, "read_manifest", _instance_failure)
    assert fl.main(["inspect", "--stdin-manifest"]) == 2
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {
        "status": "blocked", "error_code": "bootstrap-resource-instance-changed",
        "error_diagnostic": {"resource_id": RULE.lower(), "failed_comparisons": ["body_hash"]}}


def test_instance_diagnostic_survives_worker_receipt_before_arm_write(monkeypatch):
    document, templates = scoped_manifest()
    cloud = PlanCloud(document, templates)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "bootstrap_ownership_snapshot", _instance_failure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                     ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert result["status"] == "reconciliation-required"
    assert result["mutation_started"] is False and not cloud.arm_writes
    assert result["error_code"] == "bootstrap-resource-instance-changed"
    assert result["error_diagnostic"] == {
        "resource_id": RULE.lower(), "failed_comparisons": ["body_hash"]}
    assert cloud.runs["runs/" + document["run_id"] + ".worker.json"]["error_diagnostic"] == result["error_diagnostic"]


def test_instance_diagnostic_survives_parent_receipt_without_authorizing_retry(monkeypatch, workspace):
    document, cloud = manifest(), FakeCloud()
    source, execution, path = setup_execute(monkeypatch, workspace)
    monkeypatch.setattr(fl, "delete_resources", _instance_failure)
    result = fl.execute(document, source, execution, path, cloud=cloud)
    assert result["status"] == "blocked" and result["mutation_started"] is False
    assert not cloud.deleted
    assert result["error_code"] == "bootstrap-resource-instance-changed"
    assert json.loads(path.read_text())["error_diagnostic"] == {
        "resource_id": RULE.lower(), "failed_comparisons": ["body_hash"]}


def _remote_failure_case(monkeypatch, workspace, route, defect=None, remote_success=False):
    document, _ = scoped_manifest(route=route)
    foundation_cloud = ClosureCloud()
    foundation = exact_document(foundation_cloud)
    document["deployment"]["bootstrap_foundation"] = foundation["deployment"]["bootstrap_foundation"]
    document["deployment"]["bootstrap_ownership"] = fl.bootstrap_ownership_snapshot(foundation_cloud, foundation)
    cloud = FakeCloud()
    cloud.bodies[COMMON.lower()] = {"id": COMMON, "type": "Microsoft.Resources/resourceGroups"}
    cloud.enrollment = scoped_enrollment(document)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    detail = {"resource_id": RULE.lower(), "failed_comparisons": ["body_hash", "etag"]}
    worker = {"schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
              "source_commit": document["source"]["commit"], "target": copy.deepcopy(document["target"]),
              "status": "reconciliation-required", "mutation_started": False,
              "error_code": "bootstrap-resource-instance-changed", "error_diagnostic": copy.deepcopy(detail),
              "raw_response": "worker-secret-never-copy"}
    if defect in ("run_id", "manifest_hash", "source_commit"):
        worker[defect] = "foreign"
    elif defect == "target":
        worker["target"]["factory_id"] = "foreign"
    elif defect in ("status", "error_code", "schema", "mutation_started"):
        worker[defect] = "unverified"
    elif defect == "successful-receipt":
        worker["status"] = "succeeded"
    elif defect == "boolean-schema":
        worker["schema"] = True
    elif defect == "outside-proof":
        worker["error_diagnostic"]["resource_id"] = RESOURCE
    elif defect == "raw-value":
        worker["error_diagnostic"]["etag"] = "worker-secret-never-copy"
    elif defect == "legacy":
        worker.pop("error_diagnostic")
    if defect == "malformed":
        worker = []
    blob = "runs/" + document["run_id"] + ".worker.json"
    if defect != "missing":
        cloud.runs[blob] = worker
    template = (ROOT / "bootstrap" / "templates" / ("factory-lifecycle-" + route + ".yml")).read_text().strip()
    original_request = cloud.request
    worker_reads = []

    def request(method, url, audience, data=None, **kwargs):
        if method == "GET" and blob in url:
            worker_reads.append(url)
            if defect == "read-error":
                raise fl.Blocked("remote-request-unverified")
            if defect == "read-oserror":
                raise OSError("transport-private-value-never-copy")
            if defect == "read-valueerror":
                raise ValueError("malformed-private-value-never-copy")
            if defect == "non-200":
                return 404, {}, worker
        if not url.startswith("https://dev.azure.com/"):
            return original_request(method, url, audience, data, **kwargs)
        if "/serviceendpoint/endpoints?" in url:
            result = {"value": [{"name": document["route"]["auth_namespace"],
                                "authorization": {"scheme": "WorkloadIdentityFederation",
                                                  "parameters": {"tenantid": TENANT}},
                                "data": {"subscriptionId": SUB}}]}
        elif "/items?" in url:
            result = {"content": template}
        elif "/build/definitions?" in url:
            result = {"value": [{"id": 7, "repository": {"name": "consumer"},
                                "process": {"yamlFilename": fl.SCOPED_ADO}}]}
        elif method == "POST":
            assert "/pipelines/7/runs?" in url
            result = {"id": 43}
        else:
            assert "/pipelines/7/runs/43?" in url
            result = {"state": "completed", "result": "succeeded" if remote_success else "failed",
                      "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}}
        return 200, {}, result

    def command(argv, cwd=None, data=None):
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
            return json.dumps({"tree": [{"path": "azure-enterprise-scale-ml", "mode": "160000",
                                        "sha": document["source"]["commit"]}]})
        if "/workflow" in endpoint and "/runs?" in endpoint:
            return json.dumps({"workflow_runs": [{"id": 42,
                "display_title": "factory-lifecycle [" + document["run_id"] + "]",
                "head_sha": document["route"]["commit"]}]})
        if "/actions/runs/" in endpoint:
            return json.dumps({"status": "completed", "conclusion": "success" if remote_success else "failure",
                               "head_sha": document["route"]["commit"]})
        if "/git/ref/tags/" in endpoint:
            return json.dumps({"object": {"sha": document["route"]["commit"]}})
        assert method in ("POST", "DELETE")
        return ""

    cloud.request = request
    cloud.command = command
    source, execution, path = setup_execute(monkeypatch, workspace)
    result = fl.execute(document, source, execution, path, cloud=cloud)
    return SimpleNamespace(result=result, stored=json.loads(path.read_text()), worker_reads=worker_reads,
                           detail=detail, cloud=cloud, blob=blob)


@pytest.mark.parametrize("route", ["gha", "ado"])
@pytest.mark.parametrize("defect", [
    None, "missing", "malformed", "read-error", "read-oserror", "read-valueerror", "non-200",
    "run_id", "manifest_hash", "source_commit", "target", "status", "successful-receipt",
    "error_code", "schema", "boolean-schema", "mutation_started", "outside-proof", "raw-value", "legacy",
])
def test_real_remote_failure_retrieves_only_bound_diagnostic_and_preserves_failure(monkeypatch, workspace, route, defect):
    case = _remote_failure_case(monkeypatch, workspace, route, defect)
    expected_code = "scoped-github-run-failed" if route == "gha" else "scoped-ado-run-failed"
    assert len(case.worker_reads) == 1, case.result.get("error_code")
    for result in (case.result, case.stored):
        assert result["error_code"] == expected_code
        assert result["status"] == "reconciliation-required" and result["mutation_started"] is True
        assert result["remote_terminal"] is True and result["locks_retained"]
        assert "worker_receipt" not in result
        assert "worker-secret" not in json.dumps(result)
        assert "private-value" not in json.dumps(result)
        if defect is None:
            assert result["error_diagnostic"] == case.detail
        else:
            assert "error_diagnostic" not in result
    if route == "gha":
        assert case.result["remote_artifacts_cleaned"] is True
    assert not any(method == "PUT" and url.endswith(case.blob) for method, url, _, _ in case.cloud.calls)


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_real_remote_success_cannot_accept_diagnostic_bearing_failed_worker(monkeypatch, workspace, route):
    case = _remote_failure_case(monkeypatch, workspace, route, remote_success=True)
    assert len(case.worker_reads) == 1
    assert case.result["status"] == "reconciliation-required"
    assert case.result["error_code"] == "scoped-worker-receipt-unverified"
    assert "error_diagnostic" not in case.result and "worker_receipt" not in case.result


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


VNET = GROUP + "/providers/Microsoft.Network/virtualNetworks/network"
GATEWAY = GROUP + "/providers/Microsoft.Network/virtualNetworkGateways/gateway"
IPCONFIG = GATEWAY + "/ipConfigurations/default"


class GatewayCloud(ClosureCloud):
    registered_inline = False
    include_parent = True

    def __init__(self):
        super().__init__()
        self.reads = []
        self.bodies = {
            GROUP.lower(): self.bodies[GROUP.lower()],
            VNET.lower(): {"id": VNET, "type": "Microsoft.Network/virtualNetworks", "properties": {
                "subnets": [{"properties": {"ipConfigurations": [{"id": IPCONFIG}]}}]}},
            GATEWAY.lower(): {"id": GATEWAY, "type": "Microsoft.Network/virtualNetworkGateways",
                "properties": {"ipConfigurations": [{"id": IPCONFIG, "name": "default",
                    "properties": {"privateIPAllocationMethod": "Dynamic"}}]}},
        }

    def list_resources(self, scope):
        ids = [VNET, GATEWAY] if self.include_parent else [VNET]
        return [copy.deepcopy(self.bodies[key.lower()]) for key in ids]

    def provider_schema(self, namespace):
        kinds = ["virtualNetworks", "virtualNetworkGateways"]
        if self.registered_inline:
            kinds.append("virtualNetworkGateways/ipConfigurations")
        return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2023-11-01"]} for kind in kinds]}

    def provider_operations(self, namespace):
        return [namespace.lower() + "/" + kind + "/" + action
                for kind in ("virtualnetworks", "virtualnetworkgateways")
                for action in ("read", "write", "delete")]

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        assert method == "GET"
        assert resource_id.lower() != IPCONFIG.lower()
        self.reads.append((resource_id.lower(), api_version))
        return super().arm(method, resource_id, api_version, allowed, headers)

    def collection(self, path, api_version, extension=False):
        assert extension, "inline collections must not be listed independently"
        return [], None


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("parent_listed", [False, True])
def test_gateway_inline_reference_collects_exact_parent_not_invented_resource(registered, parent_listed):
    cloud = GatewayCloud()
    cloud.registered_inline, cloud.include_parent = registered, parent_listed
    closure, bodies = fl.collect_resource_closure(cloud, [GROUP], {GATEWAY.lower(): "2023-11-01"})
    assert set(bodies) == {GROUP.lower(), VNET.lower(), GATEWAY.lower()}
    assert IPCONFIG.lower() in closure["references"][VNET.lower()]
    assert IPCONFIG.lower() not in closure["resources"]
    assert closure["inline"][IPCONFIG.lower()] == {
        "parent_id": GATEWAY.lower(), "parent_body_hash": fl.digest(bodies[GATEWAY.lower()])}
    assert (GATEWAY.lower(), "2023-11-01") in cloud.reads
    if registered:
        assert closure["collections"][GATEWAY.lower() + "/ipconfigurations"] == {
            "inline_parent_hash": fl.digest(bodies[GATEWAY.lower()])}


@pytest.mark.parametrize("defect", ["missing", "wrong-path", "wrong-parent", "wrong-name", "duplicate",
                                  "not-list", "not-object", "not-id"])
def test_inline_parent_requires_exact_member_in_canonical_collection(defect):
    cloud = GatewayCloud()
    properties = cloud.bodies[GATEWAY.lower()]["properties"]
    entries = properties["ipConfigurations"]
    if defect == "missing":
        del properties["ipConfigurations"]
    elif defect == "wrong-path":
        properties["other"] = properties.pop("ipConfigurations")
    elif defect == "wrong-parent":
        entries[0]["id"] = IPCONFIG.replace("/gateway/", "/different/")
        other = GATEWAY.rsplit("/", 1)[0] + "/different"
        cloud.bodies[other.lower()] = {**copy.deepcopy(cloud.bodies[GATEWAY.lower()]), "id": other}
    elif defect == "wrong-name":
        entries[0]["id"] = IPCONFIG + "-other"
    elif defect == "duplicate":
        entries.append(copy.deepcopy(entries[0]))
    elif defect == "not-list":
        properties["ipConfigurations"] = entries[0]
    elif defect == "not-object":
        properties["ipConfigurations"] = [IPCONFIG]
    else:
        entries[0]["id"] = None
    with pytest.raises(fl.Blocked, match="inline-resource-parent-unverified"):
        fl.collect_resource_closure(cloud, [GROUP])


def test_inline_configuration_changes_change_parent_and_closure_fingerprints():
    cloud = GatewayCloud()
    before, _ = fl.collect_resource_closure(cloud, [GROUP])
    cloud.bodies[GATEWAY.lower()]["properties"]["ipConfigurations"][0]["properties"].update(
        privateIPAllocationMethod="Static")
    after, _ = fl.collect_resource_closure(cloud, [GROUP])
    assert before["inline"][IPCONFIG.lower()] != after["inline"][IPCONFIG.lower()]
    assert before["resources"][GATEWAY.lower()]["body_hash"] != after["resources"][GATEWAY.lower()]["body_hash"]
    assert fl.digest(before) != fl.digest(after)


def test_unknown_inline_looking_reference_still_fails_closed():
    cloud = GatewayCloud()
    unknown = GATEWAY + "/unknownChildren/default"
    cloud.bodies[GATEWAY.lower()]["properties"]["unknownChildren"] = [{"id": unknown}]
    with pytest.raises(fl.Blocked, match="provider-resource-kind-unclassified"):
        fl.collect_resource_closure(cloud, [GROUP])


def test_external_inline_reference_is_retained_without_reading_or_owning_parent():
    cloud = GatewayCloud()
    external = IPCONFIG.replace("/reviewed/", "/external/")
    assert external != IPCONFIG
    cloud.bodies[VNET.lower()]["properties"] = {"ipConfigurations": [{"id": external}]}
    cloud.include_parent = False
    closure, bodies = fl.collect_resource_closure(cloud, [GROUP])
    assert external.lower() in closure["references"][VNET.lower()]
    assert set(bodies) == {GROUP.lower(), VNET.lower()}
    assert not closure["inline"]


def test_inline_parent_remains_receipt_bound_and_preserved_children_cannot_be_written():
    cloud = GatewayCloud()
    document = exact_document(cloud)
    resources = document["deployment"]["bootstrap_foundation"]["resources"]
    row = resources[GATEWAY.lower()]
    row.pop("owner")
    row.update(disposition="preserve", preservation="bootstrap-prerequisite")
    snapshot = fl.bootstrap_ownership_snapshot(cloud, document)
    assert IPCONFIG.lower() not in snapshot
    assert snapshot[GATEWAY.lower()] == {"body_hash": row["body_hash"], "preserve": True}
    for action in ("Create", "Modify", "Delete"):
        with pytest.raises(fl.Blocked, match="bootstrap-prerequisite-write-forbidden"):
            fl.verify_bootstrap_preservation(document, [{"resource_id": IPCONFIG, "change_type": action}])
    cloud.bodies[GATEWAY.lower()]["properties"]["ipConfigurations"][0]["properties"].update(
        privateIPAllocationMethod="Static")
    with pytest.raises(fl.Blocked, match="bootstrap-resource-instance-changed"):
        fl.bootstrap_ownership_snapshot(cloud, document)
    del resources[GATEWAY.lower()]
    with pytest.raises(fl.Blocked, match="bootstrap-exact-resource-inventory-changed"):
        fl.bootstrap_ownership_snapshot(cloud, document)


DNS_ZONE = GROUP + "/providers/Microsoft.Network/privateDnsZones/privatelink.adf.azure.com"
DNS_APEX = DNS_ZONE + "/SOA/@"


class DnsCloud(ClosureCloud):
    def __init__(self):
        super().__init__()
        self.reads = []
        self.bodies.update({
            DNS_ZONE.lower(): {"id": DNS_ZONE, "type": "Microsoft.Network/privateDnsZones",
                               "properties": {}, "tags": copy.deepcopy(self.bodies[NSG.lower()]["tags"])},
            DNS_APEX.lower(): {"id": DNS_APEX, "type": "Microsoft.Network/privateDnsZones/SOA",
                               "etag": '"soa"', "properties": {"ttl": 3600}},
        })

    def list_resources(self, scope):
        return super().list_resources(scope) + [copy.deepcopy(self.bodies[DNS_ZONE.lower()])]

    def provider_schema(self, namespace):
        result = super().provider_schema(namespace)
        result["resourceTypes"] += [
            {"resourceType": kind, "apiVersions": ["2024-06-01"]}
            for kind in ("privateDnsZones", "privateDnsZones/SOA")]
        return result

    def collection(self, path, api_version, extension=False):
        if path.lower() == DNS_ZONE.lower() + "/soa":
            return [copy.deepcopy(self.bodies[DNS_APEX.lower()])], None
        return super().collection(path, api_version, extension)

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        assert method == "GET"
        self.reads.append(resource_id.lower())
        return super().arm(method, resource_id, api_version, allowed, headers)


@pytest.mark.parametrize("path", [
    "privateDnsZones/example.com/SOA/@", "privateDnsZones/example.com/A/@",
    "privateDnsZones/example.com/AAAA/@", "privateDnsZones/example.com/MX/@",
    "privateDnsZones/example.com/PTR/@", "privateDnsZones/example.com/SRV/@",
    "privateDnsZones/example.com/TXT/@", "dnsZones/example.com/SOA/@",
    "dnsZones/example.com/NS/@", "dnsZones/example.com/CAA/@",
    "privateDnsZones/example.com/A/*", "privateDnsZones/example.com/CNAME/*.api",
    "dnsZones/example.com/TXT/*.api", "dnsZones/example.com/CNAME/*",
    "privateDnsZones/example.com/SOA/@/providers/Microsoft.Authorization/locks/retained",
    "dnsZones/example.com/NS/@/providers/Microsoft.Authorization/roleAssignments/" + "a" * 36,
])
def test_dns_special_names_share_nested_id_validation_across_consumers(path):
    identifier = GROUP + "/providers/Microsoft.Network/" + path
    key = identifier.lower()
    assert fl.NESTED_ID.fullmatch(identifier)
    assert fl.arm_scope(identifier) == GROUP.lower()
    assert fl.resource_references({"id": identifier, "nested": [{"id": identifier.upper()}]}) == {key}
    cloud = DnsCloud()
    document = exact_document(cloud)
    row = document["deployment"]["bootstrap_foundation"]["resources"].pop(DNS_APEX.lower())
    row.update(type=fl.resource_type_from_id(identifier))
    row["receipt"]["resource_id"] = key
    document["deployment"]["bootstrap_foundation"]["resources"][key] = row
    fl.validate_exact_bootstrap(document)
    document["deployment"]["known_ownership"] = {key: {"run_id": str(uuid4()), "receipt_hash": "a" * 64}}
    fl.validate_deployment_plan(document)
    deletion = owned_group_manifest(cloud)
    item = next(item for item in deletion["deletion"]["resources"] if item["id"] == DNS_APEX.lower())
    item.update(id=identifier, type=fl.resource_type_from_id(identifier))
    deletion["deletion"]["inventory_hash"] = fl.digest(deletion["deletion"]["resources"])
    fl.validate_deletion(deletion)


@pytest.mark.parametrize("path", [
    "privateDnsZones/@/SOA/@", "privateDnsZones/example.com/unknown/@",
    "privateDnsZones/example.com/NS/@", "privateDnsZones/example.com/CAA/@",
    "privateDnsZones/example.com/CNAME/@", "dnsZones/example.com/CNAME/@",
    "privateDnsZones/example.com/SOA/*", "dnsZones/example.com/NS/*",
    "privateDnsZones/example.com/SOA/name@", "privateDnsZones/example.com/SOA/@.example",
    "privateDnsZones/example.com/SOA/@/unknown/child", "privateDnsZones/example.com/SOA/%40",
    "privateDnsZones/example.com/A/x*", "privateDnsZones/example.com/A/*..example",
    "privateDnsZones/example.com/A/../SOA/@", "virtualNetworkGateways/gateway/ipConfigurations/@",
    "privateDnsZones/example.com/SOA/@/providers/Unknown.Provider/resources/@",
    "privateDnsZones/example.com/SOA/@?query=value", "privateDnsZones/example.com/SOA/@#fragment",
    "privateDnsZones/example.com/SOA/@/", "privateDnsZones/example.com/SOA/@\n",
])
def test_dns_special_names_do_not_relax_unknown_types_paths_or_other_consumers(path):
    identifier = GROUP + "/providers/Microsoft.Network/" + path
    assert not fl.NESTED_ID.fullmatch(identifier)
    with pytest.raises(fl.Blocked, match="invalid-resource-reference"):
        fl.resource_references({"id": identifier})
    document = exact_document(DnsCloud())
    rows = document["deployment"]["bootstrap_foundation"]["resources"]
    rows[identifier.lower()] = rows.pop(DNS_APEX.lower())
    with pytest.raises(fl.Blocked, match="exact-bootstrap-resource-scope-required"):
        fl.validate_exact_bootstrap(document)
    document["deployment"].pop("bootstrap_foundation")
    document["deployment"]["known_ownership"] = {
        identifier.lower(): {"run_id": str(uuid4()), "receipt_hash": "a" * 64}}
    with pytest.raises(fl.Blocked, match="invalid-known-ownership-evidence"):
        fl.validate_deployment_plan(document)
    deletion = owned_group_manifest(DnsCloud())
    item = next(item for item in deletion["deletion"]["resources"] if item["id"] == DNS_APEX.lower())
    item["id"] = identifier
    deletion["deletion"]["inventory_hash"] = fl.digest(deletion["deletion"]["resources"])
    with pytest.raises(fl.Blocked, match="unsupported-nested-resource"):
        fl.validate_deletion(deletion)


def test_dns_apex_is_an_exact_resource_not_inline_or_inherited_authority():
    cloud = DnsCloud()
    closure, bodies = fl.collect_resource_closure(cloud, [GROUP])
    assert set(bodies) == {GROUP.lower(), NSG.lower(), RULE.lower(), DNS_ZONE.lower(), DNS_APEX.lower()}
    assert DNS_APEX.lower() in cloud.reads
    assert closure["collections"][DNS_ZONE.lower() + "/soa"]["ids"] == [DNS_APEX.lower()]
    assert closure["resources"][DNS_APEX.lower()]["body_hash"] == fl.digest(bodies[DNS_APEX.lower()])
    assert not closure["inline"]
    document = exact_document(cloud)
    assert fl.bootstrap_ownership_snapshot(cloud, document)[DNS_APEX.lower()]["owner"] == CORE_OWNER
    row = document["deployment"]["bootstrap_foundation"]["resources"][DNS_APEX.lower()]
    row["receipt"]["resource_id"] = DNS_ZONE.lower()
    with pytest.raises(fl.Blocked, match="exact-bootstrap-resource-owner-required"):
        fl.bootstrap_ownership_snapshot(cloud, document)
    row.pop("owner")
    row.update(disposition="preserve", preservation="provider-readonly")
    with pytest.raises(fl.Blocked, match="bootstrap-provider-child-is-writable"):
        fl.bootstrap_ownership_snapshot(cloud, document)


@pytest.mark.parametrize("defect", ["missing", "extra", "body", "etag", "scope", "receipt"])
def test_dns_apex_exact_inventory_and_instance_evidence_remain_mandatory(defect):
    cloud = DnsCloud()
    document = exact_document(cloud)
    rows = document["deployment"]["bootstrap_foundation"]["resources"]
    row = rows[DNS_APEX.lower()]
    if defect == "missing":
        del rows[DNS_APEX.lower()]
    elif defect == "extra":
        rows[DNS_ZONE.lower() + "/a/@"] = copy.deepcopy(row)
        rows[DNS_ZONE.lower() + "/a/@"].update(type="microsoft.network/privatednszones/a")
        rows[DNS_ZONE.lower() + "/a/@"]["receipt"]["resource_id"] = DNS_ZONE.lower() + "/a/@"
    elif defect in ("body", "etag"):
        if defect == "body":
            cloud.bodies[DNS_APEX.lower()]["properties"]["ttl"] = 42
        else:
            cloud.bodies[DNS_APEX.lower()]["etag"] = '"recreated"'
    elif defect == "scope":
        row["scope"] = GROUP.lower() + "-foreign"
    else:
        row.pop("receipt")
    with pytest.raises(fl.Blocked):
        fl.bootstrap_ownership_snapshot(cloud, document)


def test_dns_apex_preservation_and_external_scope_do_not_grant_writes_or_ownership():
    cloud = DnsCloud()
    document = exact_document(cloud)
    row = document["deployment"]["bootstrap_foundation"]["resources"][DNS_APEX.lower()]
    row.pop("owner")
    row.update(disposition="preserve", preservation="bootstrap-prerequisite")
    assert fl.bootstrap_ownership_snapshot(cloud, document)[DNS_APEX.lower()] == {
        "body_hash": row["body_hash"], "preserve": True}
    for action in ("Create", "Modify", "Delete"):
        with pytest.raises(fl.Blocked, match="bootstrap-prerequisite-write-forbidden"):
            fl.verify_bootstrap_preservation(document, [{"resource_id": DNS_APEX, "change_type": action}])
    external = DNS_APEX.replace("/reviewed/", "/external/")
    cloud.bodies[DNS_ZONE.lower()]["properties"]["external"] = external
    closure, bodies = fl.collect_resource_closure(cloud, [GROUP])
    assert external.lower() in closure["references"][DNS_ZONE.lower()]
    assert external.lower() not in bodies and external.lower() not in cloud.reads
    cloud.bodies[DNS_ZONE.lower()]["properties"]["unknown"] = DNS_ZONE + "/unknown/ordinary"
    with pytest.raises(fl.Blocked, match="provider-resource-kind-unclassified"):
        fl.collect_resource_closure(cloud, [GROUP])


def test_dns_apex_is_url_encoded_only_at_the_get_transport_boundary():
    cloud = fl.Cloud({"identity": {"object_id": str(uuid4())}}, opener=Mock())
    cloud.request = Mock(return_value=(200, {}, {"id": DNS_APEX}))
    cloud.arm("GET", DNS_APEX, "2024-06-01")
    cloud.request.assert_called_once_with(
        "GET", fl.ARM + DNS_APEX.replace("@", "%40") + "?api-version=2024-06-01",
        fl.ARM, allowed=(200,), headers=None)
    with pytest.raises(fl.Blocked, match="invalid-resource-reference"):
        fl.resource_references({"id": DNS_APEX.replace("@", "%40")})


def test_dns_apex_cannot_be_a_managed_group_parent_or_template_spec(monkeypatch):
    cloud = DnsCloud()
    group = copy.deepcopy(cloud.bodies[GROUP.lower()])
    group.pop("tags")
    group["managedBy"] = DNS_APEX
    with pytest.raises(fl.Blocked, match="owned-resource-group-marker-required"):
        fl.verify_group_ownership(group, CORE_OWNER, cloud.bodies)
    document, _ = scoped_manifest()
    document["deployment"]["steps"][0]["template_spec_id"] = DNS_APEX
    monkeypatch.setattr(fl, "compiled_plan_step", lambda *args: {"properties": {"template": {}}})
    with pytest.raises(fl.Blocked, match="reviewed-template-spec-scope-required"):
        fl.combined_plan_payload(cloud, document, ROOT)
    assert not cloud.reads


def test_dns_apex_cannot_replace_a_preservation_permit_runner(reviewed_children):
    case = reviewed_children
    case.proposal["runner"]["resource_id"] = DNS_APEX.lower()
    case.permit["proposal_hash"] = fl.digest(case.proposal)
    case.permit["approval_hash"] = fl.digest({key: value for key, value in case.permit.items()
                                            if key != "approval_hash"})
    with pytest.raises(fl.Blocked, match="reviewed-preservation-runner-proof-required"):
        fl.validate_preservation_permit(case.document)


class DnsConsentCloud(DnsCloud):
    def provider_schema(self, namespace):
        result = super().provider_schema(namespace)
        result["resourceTypes"] += [
            {"resourceType": "privateDnsZones/" + kind, "apiVersions": ["2024-06-01"]}
            for kind in fl.DNS_RECORD_TYPES if kind != "soa"]
        return result

    def collection(self, path, api_version, extension=False):
        if path.rsplit("/", 1)[0].lower() == DNS_ZONE.lower():
            return [copy.deepcopy(row) for key, row in self.bodies.items()
                    if key.rsplit("/", 1)[0] == path.lower()], None
        return super().collection(path, api_version, extension)


def add_dns_soa_consent(document, cloud, closure):
    proof = document["deployment"]["bootstrap_foundation"]
    zone, soa = DNS_ZONE.lower(), DNS_APEX.lower()
    receipt = {"resource_id": zone, "plan_id": str(uuid4()), "plan_hash": "4" * 64, "receipt_hash": "5" * 64}
    proof["resources"][zone] = {
        **closure["resources"][zone], "scope": GROUP.lower(), "disposition": "preserve",
        "preservation": "bootstrap-prerequisite", "receipt": receipt}
    baseline = {"owner_hash": "6" * 64, "workflow_id": proof["workflow_id"],
                "bootstrap_hash": proof["evidence_hash"], "zones": {zone: copy.deepcopy(proof["resources"][zone])}}
    proposal = {
        "consent": "present-state-preserve-only", "owner_hash": baseline["owner_hash"],
        "workflow_id": proof["workflow_id"], "source_commit": document["source"]["commit"],
        "operator_id": document["identity"]["object_id"],
        "deployment_object_id": document["identity"]["deployment_object_id"],
        "target": copy.deepcopy(document["target"]), "scopes": sorted(proof["groups"]),
        "bootstrap_hash": proof["evidence_hash"], "baseline_hash": fl.digest(baseline),
        "parents": {zone: {"baseline_hash": fl.digest(baseline["zones"][zone]),
                          "record_set_inventory_hash": fl.digest(fl.dns_record_set_inventory(closure, zone))}},
        "resources": {soa: {**closure["resources"][soa], "scope": GROUP.lower(), "parent_id": zone}},
        "writes": [], "deletes": [], "ownership_grants": []}
    permit = {"contract": fl.DNS_SOA_PERMIT_CONTRACT, "approved": True, "review_id": str(uuid4()),
              "owner_hash": baseline["owner_hash"], "workflow_id": proof["workflow_id"],
              "proposal": proposal, "proposal_hash": fl.digest(proposal)}
    permit["approval_hash"] = fl.digest(permit)
    proof["dns_soa_baseline"], proof["dns_soa_preservation_permit"] = baseline, permit
    proof["resources"][soa] = {
        **closure["resources"][soa], "scope": GROUP.lower(), "disposition": "preserve",
        "preservation": "reviewed-dns-soa-instance", "permit_hash": permit["approval_hash"]}
    return SimpleNamespace(document=document, cloud=cloud, proof=proof, baseline=baseline, proposal=proposal,
                           permit=permit, zone=zone, soa=soa, closure=closure)


def reseal_dns_consent(case):
    case.proposal["baseline_hash"] = fl.digest(case.baseline)
    case.permit["proposal_hash"] = fl.digest(case.proposal)
    case.permit["approval_hash"] = fl.digest({key: value for key, value in case.permit.items()
                                            if key != "approval_hash"})
    for row in case.proof["resources"].values():
        if row.get("preservation") == "reviewed-dns-soa-instance":
            row["permit_hash"] = case.permit["approval_hash"]


@pytest.fixture
def dns_consent():
    cloud = DnsConsentCloud()
    document = exact_document(cloud)
    closure, _ = fl.collect_resource_closure(cloud, [GROUP])
    for key, metadata in closure["resources"].items():
        document["deployment"]["bootstrap_foundation"]["resources"][key].update(metadata)
    return add_dns_soa_consent(document, cloud, closure)


def test_dns_soa_consent_preserves_exact_present_instance_without_historical_authority(dns_consent):
    case = dns_consent
    snapshot = fl.bootstrap_ownership_snapshot(case.cloud, case.document)
    assert snapshot[case.soa] == {"preserve": True, "body_hash": fl.digest(case.cloud.bodies[case.soa])}
    assert snapshot[case.zone] == {"preserve": True, "body_hash": fl.digest(case.cloud.bodies[case.zone])}
    assert not {"owner", "receipt"} & set(case.proof["resources"][case.soa])
    assert "microsoft.network/privatednszones/soa/write" in case.cloud.provider_operations("Microsoft.Network")
    assert fl.validate_dns_soa_preservation_permit(case.document) == case.permit
    assert fl.capabilities()["bootstrap_dns_soa_preservation_permit"] == fl.DNS_SOA_PERMIT_CONTRACT
    for identifier in (case.soa, case.zone, case.soa + "/providers/Microsoft.Authorization/locks/lock"):
        for change in ("Create", "Modify", "Delete"):
            with pytest.raises(fl.Blocked, match="bootstrap-prerequisite-write-forbidden"):
                fl.verify_bootstrap_preservation(case.document, [{"resource_id": identifier, "change_type": change}])
    fl.verify_bootstrap_preservation(case.document, [{"resource_id": case.soa, "change_type": "NoChange"}])


@pytest.mark.parametrize("defect", [
    "no-permit", "no-baseline", "unapproved", "contract", "review-id", "approval-hash", "proposal-hash",
    "owner", "workflow", "source", "operator", "deployment-identity", "target", "extra-target", "scopes",
    "bootstrap-hash", "baseline-hash", "baseline-owner", "baseline-workflow", "baseline-bootstrap",
    "writes", "deletes", "ownership_grants", "consent", "extra-envelope", "extra-proposal",
    "missing-parent", "extra-parent", "duplicate-parent", "parent-body", "parent-receipt", "parent-owned",
    "parent-readonly", "parent-baseline-hash", "parent-extra", "row-parent", "row-type", "row-scope",
    "row-api", "row-hash", "row-etag", "row-owner", "row-receipt", "row-extra",
    "actual-owner", "actual-receipt", "actual-owned", "actual-readonly", "actual-permit-hash",
    "actual-hash", "actual-etag", "actual-extra", "known-owner",
    "missing-apex", "extra-apex", "wildcard", "query", "unknown-type",
])
def test_dns_soa_consent_rejects_malformed_or_resealed_authority(dns_consent, defect):
    case = dns_consent
    p, b, proof = case.proposal, case.baseline, case.proof
    parent, row, actual = p["parents"][case.zone], p["resources"][case.soa], proof["resources"][case.soa]
    if defect == "no-permit":
        proof.pop("dns_soa_preservation_permit")
    elif defect == "no-baseline":
        proof.pop("dns_soa_baseline")
    elif defect == "unapproved":
        case.permit["approved"] = False
    elif defect == "contract":
        case.permit["contract"] = fl.PRESERVATION_PERMIT_CONTRACT
    elif defect == "review-id":
        case.permit["review_id"] = "invalid"
    elif defect in ("approval-hash", "proposal-hash"):
        case.permit[defect.replace("-", "_")] = "f" * 64
    elif defect in ("owner", "workflow", "source", "operator", "deployment-identity", "bootstrap-hash", "baseline-hash"):
        field = {"owner": "owner_hash", "workflow": "workflow_id", "source": "source_commit", "operator": "operator_id",
                 "deployment-identity": "deployment_object_id"}.get(defect, defect.replace("-", "_"))
        p[field] = "f" * 64
    elif defect == "target":
        p["target"]["scaleset_id"] = "other"
    elif defect == "extra-target":
        p["target"]["other"] = True
    elif defect == "scopes":
        p["scopes"].append(GROUP.lower() + "-foreign")
    elif defect.startswith("baseline-"):
        b[{"baseline-owner": "owner_hash", "baseline-workflow": "workflow_id",
           "baseline-bootstrap": "bootstrap_hash"}[defect]] = "f" * 64
    elif defect in ("writes", "deletes", "ownership_grants"):
        p[defect] = [case.soa]
    elif defect == "consent":
        p["consent"] = "historical-receipt"
    elif defect == "extra-envelope":
        case.permit["allow"] = True
    elif defect == "extra-proposal":
        p["allow"] = True
    elif defect == "missing-parent":
        p["parents"].clear()
    elif defect in ("extra-parent", "duplicate-parent"):
        key = case.zone + "-other" if defect == "extra-parent" else case.zone.upper()
        p["parents"][key] = copy.deepcopy(parent)
        b["zones"][key] = copy.deepcopy(b["zones"][case.zone])
    elif defect in ("parent-body", "parent-receipt", "parent-owned", "parent-readonly", "parent-extra"):
        baseline_row = b["zones"][case.zone]
        if defect == "parent-body":
            baseline_row["body_hash"] = "f" * 64
        elif defect == "parent-receipt":
            baseline_row["receipt"]["resource_id"] = GROUP.lower()
        elif defect == "parent-owned":
            baseline_row.update(disposition="owned", owner=CORE_OWNER)
        elif defect == "parent-readonly":
            baseline_row["preservation"] = "provider-readonly"
        else:
            baseline_row["other"] = True
        proof["resources"][case.zone] = copy.deepcopy(baseline_row)
        parent["baseline_hash"] = fl.digest(baseline_row)
    elif defect == "parent-baseline-hash":
        parent["baseline_hash"] = "f" * 64
    elif defect.startswith("row-"):
        field = {"row-parent": "parent_id", "row-hash": "body_hash", "row-api": "api_version"}.get(
            defect, defect.removeprefix("row-"))
        row[field] = {"owner": CORE_OWNER, "receipt": {}, "etag": [], "body_hash": "invalid"}.get(field, "wrong")
    elif defect.startswith("actual-"):
        field = {"actual-owned": "disposition", "actual-readonly": "preservation",
                 "actual-hash": "body_hash"}.get(defect, defect.removeprefix("actual-").replace("-", "_"))
        actual[field] = {"owner": CORE_OWNER, "receipt": {}, "disposition": "owned",
                         "preservation": "provider-readonly"}.get(field, "wrong")
    elif defect == "known-owner":
        case.document["deployment"]["known_ownership"] = {case.soa: {"run_id": str(uuid4()), "receipt_hash": "a" * 64}}
    elif defect == "missing-apex":
        p["resources"].clear()
    elif defect == "extra-apex":
        p["resources"][case.soa + "-extra"] = copy.deepcopy(row)
    else:
        key = {"wildcard": case.zone + "/soa/*", "query": case.soa + "?foo=bar",
               "unknown-type": case.zone + "/unknown/@"}[defect]
        p["resources"][key] = p["resources"].pop(case.soa)
        proof["resources"][key] = proof["resources"].pop(case.soa)
    if defect not in ("approval-hash", "proposal-hash"):
        if defect == "baseline-hash":
            case.permit["proposal_hash"] = fl.digest(p)
            case.permit["approval_hash"] = fl.digest({k: v for k, v in case.permit.items() if k != "approval_hash"})
        else:
            original_hash = actual.get("permit_hash")
            reseal_dns_consent(case)
            if defect == "actual-permit-hash":
                actual["permit_hash"] = original_hash
    with pytest.raises(fl.Blocked):
        fl.bootstrap_ownership_snapshot(case.cloud, case.document)


@pytest.mark.parametrize("defect", [
    "missing-soa", "soa-body", "soa-etag", "parent-body", "parent-etag", "additional-record",
    "additional-unknown-resource", "missing-record-collection", "unsupported-collection",
    "duplicate-record-id", "escaped-record-id", "collection-body", "collection-api",
])
def test_dns_soa_consent_requires_full_fresh_instance_and_record_inventory(dns_consent, monkeypatch, defect):
    case = dns_consent
    if defect == "missing-soa":
        del case.cloud.bodies[case.soa]
    elif defect in ("soa-body", "soa-etag", "parent-body", "parent-etag"):
        key = case.soa if defect.startswith("soa") else case.zone
        if defect.endswith("body"):
            case.cloud.bodies[key]["properties"]["changed"] = True
        else:
            case.cloud.bodies[key]["etag"] = '"new"'
    elif defect in ("additional-record", "additional-unknown-resource"):
        key = case.zone + ("/a/new" if defect == "additional-record" else "/unknown/new")
        case.cloud.bodies[key] = {"id": key, "type": fl.resource_type_from_id(key), "properties": {}}
        if defect == "additional-unknown-resource":
            case.cloud.bodies[case.zone]["properties"]["unknown"] = key
    else:
        original = fl.collect_resource_closure
        def closure(*args, **kwargs):
            result, bodies = original(*args, **kwargs)
            key = case.zone + "/soa"
            if defect == "missing-record-collection":
                del result["collections"][case.zone + "/txt"]
            elif defect == "unsupported-collection":
                result["collections"][key]["unsupported"] = "UnsupportedResourceType"
            elif defect == "duplicate-record-id":
                result["collections"][key]["ids"] *= 2
            elif defect == "escaped-record-id":
                result["collections"][key]["ids"] = [DNS_APEX.replace("/reviewed/", "/foreign/").lower()]
            elif defect == "collection-body":
                result["collections"][key]["body_hash"] = "f" * 64
            elif defect == "collection-api":
                result["collections"][key]["api_version"] = "2020-01-01"
            return result, bodies
        monkeypatch.setattr(fl, "collect_resource_closure", closure)
    with pytest.raises(fl.Blocked):
        fl.bootstrap_ownership_snapshot(case.cloud, case.document)


@pytest.fixture
def runner_and_dns_consent(reviewed_children, monkeypatch):
    case = reviewed_children
    dns_cloud = DnsConsentCloud()
    for key in (DNS_ZONE.lower(), DNS_APEX.lower()):
        case.cloud.bodies[key] = copy.deepcopy(dns_cloud.bodies[key])
    original = fl.collect_resource_closure
    def closure(cloud, scopes, resource_versions=None):
        result, bodies = original(cloud, scopes, resource_versions)
        result["collections"] = {}
        for kind in fl.DNS_RECORD_TYPES:
            path = DNS_ZONE.lower() + "/" + kind
            rows = [body for key, body in sorted(bodies.items()) if key.rsplit("/", 1)[0] == path]
            result["collections"][path] = {"api_version": "2024-06-01", "ids": [row["id"].lower() for row in rows],
                                           "body_hash": fl.digest(rows), "unsupported": None}
        return result, bodies
    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    result, _ = closure(case.cloud, [GROUP])
    dns = add_dns_soa_consent(case.document, case.cloud, result)
    case.dns = dns
    return case


def test_worker_and_receipt_carry_independent_runner_and_dns_consents(runner_and_dns_consent, monkeypatch):
    case = runner_and_dns_consent
    runner_before = copy.deepcopy(case.permit)
    result = _execute_reviewed_worker(case, monkeypatch)
    assert result["status"] == "succeeded", result
    assert result["bootstrap_preservation_permit"] == runner_before == case.permit
    assert len(case.permit["proposal"]["resources"]) == 2
    assert result["bootstrap_dns_soa_preservation_permit"] == case.dns.permit
    assert result["bootstrap_dns_soa_baseline"] == case.dns.baseline
    assert not {case.dns.soa, case.dns.zone} & {row["resource_id"] for row in result["ownership"]}
    assert fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document) == result


@pytest.mark.parametrize("defect", ["missing-soa", "soa-body", "soa-etag", "zone-body", "new-record", "new-unknown"])
def test_worker_dns_post_write_drift_is_reconciliation_not_adoption(runner_and_dns_consent, monkeypatch, defect):
    case = runner_and_dns_consent
    def after_apply():
        if defect == "missing-soa":
            case.cloud.bodies.pop(case.dns.soa)
        elif defect in ("soa-body", "zone-body"):
            key = case.dns.soa if defect == "soa-body" else case.dns.zone
            case.cloud.bodies[key]["properties"]["changed"] = True
        elif defect == "soa-etag":
            case.cloud.bodies[case.dns.soa]["etag"] = '"recreated"'
        else:
            key = case.dns.zone + ("/a/new" if defect == "new-record" else "/unknown/new")
            case.cloud.bodies[key] = {"id": key, "type": fl.resource_type_from_id(key), "properties": {}}
    result = _execute_reviewed_worker(case, monkeypatch, after_apply=after_apply)
    assert result["status"] == "reconciliation-required", result
    assert not result["ownership"]
    with pytest.raises(fl.Blocked, match="scoped-worker-receipt-unverified"):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)


@pytest.mark.parametrize("defect", ["permit-missing", "permit-changed", "baseline-missing", "baseline-changed",
                                   "row-owned", "closure-soa", "closure-collection", "manifest-consent"])
def test_receipt_independently_revalidates_dns_consent(runner_and_dns_consent, monkeypatch, defect):
    case = runner_and_dns_consent
    result = _execute_reviewed_worker(case, monkeypatch)
    assert result["status"] == "succeeded", result
    result = copy.deepcopy(result)
    if defect == "permit-missing":
        result.pop("bootstrap_dns_soa_preservation_permit")
    elif defect == "permit-changed":
        result["bootstrap_dns_soa_preservation_permit"]["approved"] = False
    elif defect == "baseline-missing":
        result.pop("bootstrap_dns_soa_baseline")
    elif defect == "baseline-changed":
        result["bootstrap_dns_soa_baseline"]["owner_hash"] = "f" * 64
    elif defect == "row-owned":
        result["bootstrap_preserved"][case.dns.soa]["owner"] = CORE_OWNER
    elif defect == "closure-soa":
        result["bootstrap_final_closure"]["resources"][case.dns.soa]["etag"] = '"other"'
    elif defect == "closure-collection":
        result["bootstrap_final_closure"]["collections"][case.dns.zone + "/txt"]["body_hash"] = "f" * 64
    else:
        case.dns.permit["approved"] = False
    result["inventory_closure_hash"] = fl.digest(result["bootstrap_final_closure"])
    case.cloud.runs["runs/" + case.document["run_id"] + ".worker.json"] = result
    with pytest.raises(fl.Blocked):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)


@pytest.mark.parametrize("count", [0, 1, 59, 128, 129])
def test_dns_soa_consent_bound_is_per_exact_zone_not_account_hardcoded(dns_consent, count):
    case = dns_consent
    p, b, proof = case.proposal, case.baseline, case.proof
    parent = copy.deepcopy(proof["resources"].pop(case.zone))
    apex = copy.deepcopy(proof["resources"].pop(case.soa))
    proposal_apex = copy.deepcopy(p["resources"][case.soa])
    p["parents"], p["resources"], b["zones"] = {}, {}, {}
    for index in range(count):
        zone = case.zone + "-zone" + str(index)
        soa = zone + "/soa/@"
        baseline_row = copy.deepcopy(parent)
        baseline_row["receipt"]["resource_id"] = zone
        proof["resources"][zone] = copy.deepcopy(baseline_row)
        proof["resources"][soa] = copy.deepcopy(apex)
        b["zones"][zone] = baseline_row
        p["parents"][zone] = {"baseline_hash": fl.digest(baseline_row), "record_set_inventory_hash": "7" * 64}
        p["resources"][soa] = {**proposal_apex, "parent_id": zone}
    reseal_dns_consent(case)
    if count in (0, 129):
        with pytest.raises(fl.Blocked, match="dns-soa-original-zone-baseline-required"):
            fl.validate_exact_bootstrap(case.document)
    else:
        assert fl.validate_exact_bootstrap(case.document) == proof


@pytest.mark.parametrize("field", ["dns_soa_preservation_permit", "dns_soa_baseline"])
@pytest.mark.parametrize("value", [None, [], "invalid", {}])
def test_dns_soa_malformed_envelopes_fail_closed(dns_consent, field, value):
    dns_consent.proof[field] = value
    with pytest.raises(fl.Blocked):
        fl.validate_exact_bootstrap(dns_consent.document)


@pytest.mark.parametrize("defect", ["soa-body", "soa-etag", "zone-body", "collection"])
def test_worker_dns_drift_after_whatif_blocks_before_any_arm_write(runner_and_dns_consent, monkeypatch, defect):
    case = runner_and_dns_consent
    original = fl.evaluate_what_if
    def whatif(*args, **kwargs):
        result = original(*args, **kwargs)
        if defect == "soa-etag":
            case.cloud.bodies[case.dns.soa]["etag"] = '"new"'
        elif defect in ("soa-body", "zone-body"):
            key = case.dns.soa if defect == "soa-body" else case.dns.zone
            case.cloud.bodies[key]["properties"]["changed"] = True
        else:
            key = case.dns.zone + "/a/new"
            case.cloud.bodies[key] = {"id": key, "type": "Microsoft.Network/privateDnsZones/A"}
        return result
    monkeypatch.setattr(fl, "evaluate_what_if", whatif)
    result = _execute_reviewed_worker(case, monkeypatch)
    assert result["status"] == "reconciliation-required", result
    assert not case.cloud.arm_writes
    assert not result["mutation_started"] and not result["ownership"]


def test_runner_and_dns_permit_resources_cannot_be_swapped(runner_and_dns_consent):
    case = runner_and_dns_consent
    case.permit["proposal"]["resources"] = copy.deepcopy(case.dns.proposal["resources"])
    case.permit["proposal_hash"] = fl.digest(case.permit["proposal"])
    case.permit["approval_hash"] = fl.digest({key: value for key, value in case.permit.items()
                                            if key != "approval_hash"})
    with pytest.raises(fl.Blocked, match="reviewed-preservation-runner-proof-required"):
        fl.validate_preservation_permit(case.document)


def test_dns_consent_does_not_mint_deletion_ownership(dns_consent):
    case = dns_consent
    delete = owned_group_manifest(case.cloud)
    row = next(row for row in delete["deletion"]["resources"] if row["id"] == case.soa)
    row.pop("owner")
    row.update(preservation="reviewed-dns-soa-instance", permit_hash=case.permit["approval_hash"])
    delete["deletion"]["inventory_hash"] = fl.digest(delete["deletion"]["resources"])
    with pytest.raises(fl.Blocked, match="unknown-resource-ownership"):
        fl.validate_deletion(delete)
    case.document["operation"] = "delete"
    with pytest.raises(fl.Blocked, match="dns-soa-preservation-operation-required"):
        fl.validate_dns_soa_preservation_permit(case.document)


def add_accepted_zone_witness(case, index=10):
    receipt = case.baseline["zones"][case.zone]["receipt"]
    basis = {
        "contract": "accepted-current-prerequisite-baseline-v1",
        "plan_id": receipt["plan_id"], "plan_hash": receipt["plan_hash"],
        "operator_id": case.proposal["operator_id"], "approved_current_review_sha256": "a" * 64,
        "native_plan_hash": "b" * 64, "source_payload_sha256": "c" * 64,
        "recovery_archive_hash": "d" * 64, "success_receipt_hash": "e" * 64,
        "resource_id": case.zone, "baseline_body_hash": "f" * 64,
        "provenance": {"native_effect_index": index, "native_effect_hash": "8" * 64},
    }
    receipt.update(basis=basis, receipt_hash=fl.digest(basis))
    synchronize_zone_witness(case)
    return basis


def synchronize_zone_witness(case):
    original = case.baseline["zones"][case.zone]
    case.proof["resources"][case.zone] = copy.deepcopy(original)
    case.proposal["parents"][case.zone]["baseline_hash"] = fl.digest(original)
    reseal_dns_consent(case)


@pytest.mark.parametrize("index", [10, 70, 130])
def test_dns_soa_accepts_exact_current_prerequisite_zone_witness(dns_consent, index):
    case = dns_consent
    basis = add_accepted_zone_witness(case, index)
    receipt = case.proof["resources"][case.zone]["receipt"]
    assert receipt["basis"] == basis and receipt["receipt_hash"] == fl.digest(basis)
    snapshot = fl.bootstrap_ownership_snapshot(case.cloud, case.document)
    assert snapshot[case.zone]["preserve"] is True and snapshot[case.soa]["preserve"] is True
    assert "owner" not in snapshot[case.zone] and "receipt" not in case.proof["resources"][case.soa]
    assert fl.validate_dns_soa_preservation_permit(case.document) == case.permit


@pytest.mark.parametrize("field,value", [
    ("contract", "unknown"),
    ("plan_id", "invalid"), ("plan_id", "11111111-1111-1111-1111-111111111111"),
    ("plan_hash", "invalid"), ("plan_hash", "1" * 64),
    ("operator_id", "invalid"), ("operator_id", "11111111-1111-1111-1111-111111111111"),
    ("resource_id", DNS_ZONE.lower() + "-other"), ("resource_id", DNS_APEX.lower()),
    ("resource_id", DNS_ZONE.upper()),
    ("approved_current_review_sha256", "invalid"), ("native_plan_hash", None),
    ("source_payload_sha256", "f" * 63), ("recovery_archive_hash", {}),
    ("success_receipt_hash", []), ("baseline_body_hash", 42),
    ("provenance", None), ("provenance", {"native_effect_index": 10}),
    ("provenance", {"native_effect_index": 10, "native_effect_hash": "invalid"}),
    ("provenance", {"native_effect_index": 10, "native_effect_hash": "a" * 64, "owner": "invented"}),
])
def test_dns_soa_rejects_resealed_mismatched_parent_basis(dns_consent, field, value):
    case = dns_consent
    basis = add_accepted_zone_witness(case)
    basis[field] = value
    case.baseline["zones"][case.zone]["receipt"]["receipt_hash"] = fl.digest(basis)
    synchronize_zone_witness(case)
    with pytest.raises(fl.Blocked, match="dns-soa-parent-baseline-witness-invalid"):
        fl.bootstrap_ownership_snapshot(case.cloud, case.document)


@pytest.mark.parametrize("index", [-1, 0, 9, 131, 1000, True, False, 10.0, "10", None])
def test_dns_soa_zone_witness_effect_index_is_exact_reviewed_integer(dns_consent, index):
    case = dns_consent
    add_accepted_zone_witness(case, index)
    with pytest.raises(fl.Blocked, match="dns-soa-parent-baseline-witness-invalid"):
        fl.validate_exact_bootstrap(case.document)


@pytest.mark.parametrize("defect", [
    "altered-without-receipt-hash", "baseline-only", "foundation-only", "missing-field", "extra-field",
    "basis-not-object", "receipt-extra", "receipt-plan-id", "receipt-plan-hash", "receipt-resource",
    "promote-parent", "basis-ownership", "basis-writes",
])
def test_dns_soa_parent_witness_cannot_be_tampered_or_promoted(dns_consent, defect):
    case = dns_consent
    basis = add_accepted_zone_witness(case)
    original = case.baseline["zones"][case.zone]
    receipt = original["receipt"]
    if defect == "altered-without-receipt-hash":
        basis["native_plan_hash"] = "a" * 64
    elif defect in ("baseline-only", "foundation-only"):
        selected = original if defect == "baseline-only" else case.proof["resources"][case.zone]
        selected["receipt"]["basis"]["native_plan_hash"] = "a" * 64
        selected["receipt"]["receipt_hash"] = fl.digest(selected["receipt"]["basis"])
    elif defect == "missing-field":
        basis.pop("success_receipt_hash")
    elif defect == "extra-field":
        basis["unreviewed"] = True
    elif defect == "basis-not-object":
        receipt["basis"] = []
    elif defect == "receipt-extra":
        receipt["unreviewed"] = True
    elif defect == "receipt-plan-id":
        receipt["plan_id"] = str(uuid4())
    elif defect == "receipt-plan-hash":
        receipt["plan_hash"] = "a" * 64
    elif defect == "receipt-resource":
        receipt["resource_id"] = GROUP.lower()
    elif defect == "promote-parent":
        original.update(disposition="owned", owner=CORE_OWNER)
    elif defect == "basis-ownership":
        basis["owner"] = CORE_OWNER
    else:
        basis["writes"] = [case.zone]
    if defect not in ("altered-without-receipt-hash", "baseline-only", "foundation-only"):
        receipt["receipt_hash"] = fl.digest(receipt["basis"])
    if defect in ("baseline-only", "foundation-only"):
        case.proposal["parents"][case.zone]["baseline_hash"] = fl.digest(original)
        reseal_dns_consent(case)
    else:
        synchronize_zone_witness(case)
    with pytest.raises(fl.Blocked):
        fl.bootstrap_ownership_snapshot(case.cloud, case.document)


def test_worker_receipt_preserves_exact_accepted_parent_basis(runner_and_dns_consent, monkeypatch):
    case = runner_and_dns_consent
    basis = add_accepted_zone_witness(case.dns)
    result = _execute_reviewed_worker(case, monkeypatch)
    assert result["status"] == "succeeded", result
    assert result["bootstrap_preserved"][case.dns.zone]["receipt"]["basis"] == basis
    assert result["bootstrap_dns_soa_baseline"]["zones"][case.dns.zone]["receipt"]["basis"] == basis
    assert fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document) == result
    tampered = copy.deepcopy(result)
    tampered["bootstrap_dns_soa_baseline"]["zones"][case.dns.zone]["receipt"]["basis"]["operator_id"] = str(uuid4())
    case.cloud.runs["runs/" + case.document["run_id"] + ".worker.json"] = tampered
    with pytest.raises(fl.Blocked):
        fl.verify_worker_receipt(fl.BlobLocks(case.cloud, case.document), case.document)
