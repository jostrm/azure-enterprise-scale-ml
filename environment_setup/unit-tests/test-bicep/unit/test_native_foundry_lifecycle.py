"""Offline native Foundry sequencing; never invokes Azure or a provider workflow."""

import base64
import copy
import json
import uuid
import zlib
from datetime import datetime, timedelta
from urllib.parse import unquote, urlsplit
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import (
    fl, scoped_manifest, GROUP, ROOT, no_real_services, PlanCloud,
    RESOURCE, simple_plan_closure, seal, workspace, setup_execute, COMMON,
)

NSG = GROUP.lower() + "/providers/microsoft.network/networksecuritygroups/reviewed"


def reviewed_nsg(document, cloud):
    body = copy.deepcopy(cloud.bodies[RESOURCE.lower()])
    body.update(id=NSG, type="Microsoft.Network/networkSecurityGroups")
    cloud.bodies[NSG] = copy.deepcopy(body)
    cloud.planned[NSG] = body
    phase = document["deployment"]["foundry_lifecycle"]["phases"][0]
    cloud.expanded[tuple(phase["step_ids"])].append(NSG)


@pytest.mark.parametrize("defect", ["lease", "claim", "nsg", "uami"])
@pytest.mark.parametrize("producer", [False, True])
def test_convergence_completion_revalidates_instances_and_authorization(monkeypatch, defect, producer):
    document, cloud, locks = (prepare_identity_worker(monkeypatch) if producer else
                              native_worker(monkeypatch, configure=reviewed_nsg))
    original = fl.collect_resource_closure
    scans = []
    stopped = []
    def closure(*args, **kwargs):
        writes = len(cloud.arm_writes) if producer else len(cloud.executed)
        if writes == (1 if producer else 3):
            scans.append(True)
            if len(scans) == (2 if producer else 3) and not stopped:
                stopped.append(writes)
                if defect == "lease":
                    cloud.leases.clear()
                elif defect == "claim":
                    claim = cloud.runs["runs/" + document["run_id"] + ".json"]
                    claim.pop("state", None)
                    claim["status"] = "reconciliation-required"
                else:
                    key = UAMI if defect == "uami" else NSG
                    if key not in cloud.bodies:
                        cloud.bodies[key] = {**copy.deepcopy(cloud.identity), "id": key}
                    cloud.bodies[key]["etag"] = '"replacement"'
        return original(*args, **kwargs)
    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert stopped == [1 if producer else 3]
    assert result["status"] == "reconciliation-required"
    assert len(cloud.arm_writes) == 1 if producer else len(cloud.executed) == 3


@pytest.mark.parametrize("boundary", ["project", "completion"])
@pytest.mark.parametrize("instance", ["nsg", "uami"])
def test_convergence_inventory_follows_last_readiness_get(monkeypatch, boundary, instance):
    document, cloud, locks = native_worker(monkeypatch, configure=reviewed_nsg)
    original_readiness, original_request = fl.verify_foundry_live_readiness, cloud.request
    active, changed = [], []
    def readiness(*args, **kwargs):
        if len(cloud.executed) == (2 if boundary == "project" else 3):
            active.append(True)
        try:
            return original_readiness(*args, **kwargs)
        finally:
            active.clear()
    def request(method, url, *args, **kwargs):
        result = original_request(method, url, *args, **kwargs)
        if active and method == "GET" and "/capabilityhosts/" in url.lower() and not changed:
            changed.append(len(cloud.executed))
            cloud.bodies[UAMI if instance == "uami" else NSG]["etag"] = '"replacement"'
        return result
    monkeypatch.setattr(fl, "verify_foundry_live_readiness", readiness)
    monkeypatch.setattr(cloud, "request", request)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert changed == [2 if boundary == "project" else 3]
    assert result["status"] == "reconciliation-required"
    assert len(cloud.executed) == changed[0]


@pytest.mark.parametrize("instance", ["nsg", "uami"])
def test_convergence_producer_inventory_follows_last_absence_get(monkeypatch, instance):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    original = cloud.request
    pending, changed = [], []
    def request(method, url, *args, **kwargs):
        result = original(method, url, *args, **kwargs)
        if method == "PUT" and not url.startswith(fl.ARM) and (kwargs.get("data") or {}).get("pending_deployment"):
            pending.append(True)
        if pending and method == "GET" and urlsplit(url).path.lower() == UAMI and result[0] == 404 and not changed:
            changed.append(True)
            cloud.bodies[GROUP.lower()] = copy.deepcopy(cloud.group)
            key = UAMI if instance == "uami" else NSG
            cloud.bodies[key] = {**copy.deepcopy(cloud.identity), "id": key}
        return result
    monkeypatch.setattr(cloud, "request", request)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert changed and not cloud.arm_writes
    assert result["status"] == "reconciliation-required"


@pytest.mark.parametrize("defect", ["initial", "phase", "executed", "phase-hash", "final-hash",
                                    "ownership", "group", "old-contract"])
def test_convergence_success_requires_complete_bound_observation_history(monkeypatch, defect):
    document, cloud, locks = native_worker(monkeypatch, configure=reviewed_nsg)
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert receipt["status"] == "succeeded"
    if defect == "initial":
        receipt.pop("foundry_initial_observations")
    elif defect == "phase":
        receipt["foundry_phase_observations"].pop()
    elif defect == "executed":
        receipt["foundry_phase_observations"][0]["executed_changes"] = []
    elif defect == "phase-hash":
        receipt["foundry_phase_observations"][0]["resources"][NSG]["body_hash"] = "f" * 64
    elif defect == "final-hash":
        receipt["foundry_final_closure"]["resources"][NSG]["body_hash"] = "f" * 64
    elif defect == "ownership":
        receipt["ownership"][0]["body_hash"] = "f" * 64
    elif defect == "group":
        receipt["resource_groups"][0]["etag"] = '"replacement"'
    else:
        document["deployment"]["foundry_lifecycle"]["contract"] = "identity-receipt-account-uami-readiness-project-v3"
    with pytest.raises(fl.Blocked):
        fl.verify_foundry_receipt(document, receipt)


@pytest.mark.parametrize("revocation", ["lease", "claim", "nsg", "uami"])
@pytest.mark.parametrize("phase", [0, 1, 2])
def test_convergence_pending_intent_cannot_authorize_another_phase_put(monkeypatch, revocation, phase):
    document, cloud, locks = native_worker(monkeypatch, configure=reviewed_nsg)
    endpoint = fl.deployment_endpoint(document, {
        "id": document["deployment"]["foundry_lifecycle"]["phases"][phase]["id"],
        "scope": "subscription"}).removeprefix(fl.ARM)
    original = cloud.request
    stopped = []
    def request(method, url, *args, **kwargs):
        result = original(method, url, *args, **kwargs)
        data = kwargs.get("data") or {}
        if (method == "PUT" and not url.startswith(fl.ARM) and data.get("pending_deployment") == endpoint
                and len(cloud.executed) == phase and not stopped):
            stopped.append(len(cloud.executed))
            if revocation == "lease":
                cloud.leases.clear()
            elif revocation == "claim":
                claim = cloud.runs["runs/" + document["run_id"] + ".json"]
                claim.pop("state", None)
                claim["status"] = "reconciliation-required"
            else:
                key = UAMI if revocation == "uami" else NSG
                cloud.bodies[key]["etag"] = '"replacement"'
        return result
    monkeypatch.setattr(cloud, "request", request)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert stopped == [phase]
    assert len(cloud.executed) == phase
    assert result["status"] == "reconciliation-required"
    assert cloud.grant_writes == []


@pytest.mark.parametrize("boundary", ["capability-host", "final-closure"])
def test_convergence_cumulative_preview_cannot_rebase_unchanged_nsg(monkeypatch, boundary):
    nsg = GROUP.lower() + "/providers/microsoft.network/networksecuritygroups/reviewed"
    def configure(document, cloud):
        body = copy.deepcopy(cloud.bodies[RESOURCE.lower()])
        body.update(id=nsg, type="Microsoft.Network/networkSecurityGroups")
        cloud.bodies[nsg] = copy.deepcopy(body)
        cloud.planned[nsg] = body
        phase = document["deployment"]["foundry_lifecycle"]["phases"][0]
        cloud.expanded[tuple(phase["step_ids"])].append(nsg)
    document, cloud, locks = native_worker(monkeypatch, configure=configure)
    changed = []
    def drift():
        if not changed:
            changed.append(len(cloud.executed))
            cloud.bodies[nsg]["properties"]["securityRules"] = [{"name": "foreign"}]
    original_request = cloud.request
    def request(method, url, *args, **kwargs):
        result = original_request(method, url, *args, **kwargs)
        if boundary == "capability-host" and method == "GET" and "/capabilityhosts/" in url.lower():
            drift()
        return result
    original_closure = fl.collect_resource_closure
    def closure(*args, **kwargs):
        if boundary == "final-closure" and len(cloud.executed) == 3:
            drift()
        return original_closure(*args, **kwargs)
    monkeypatch.setattr(cloud, "request", request)
    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert changed
    assert result["status"] == "reconciliation-required"
    assert len(cloud.executed) == changed[0]


@pytest.mark.parametrize("defect", ["identity", "nsg", "lease", "claim"])
def test_convergence_producer_rechecks_inventory_after_persist(monkeypatch, defect):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    original = cloud.request
    changed = []
    def request(method, url, *args, **kwargs):
        result = original(method, url, *args, **kwargs)
        data = kwargs.get("data") or {}
        if method == "PUT" and not url.startswith(fl.ARM) and data.get("pending_deployment") and not changed:
            changed.append(True)
            if defect == "lease":
                cloud.leases.clear()
                return result
            if defect == "claim":
                claim = cloud.runs["runs/" + document["run_id"] + ".json"]
                claim.pop("state", None)
                claim["status"] = "reconciliation-required"
                return result
            cloud.bodies[GROUP.lower()] = copy.deepcopy(cloud.group)
            identifier = UAMI if defect == "identity" else GROUP.lower() + "/providers/microsoft.network/networksecuritygroups/foreign"
            cloud.bodies[identifier] = {**copy.deepcopy(cloud.identity), "id": identifier}
        return result
    monkeypatch.setattr(cloud, "request", request)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert changed and not cloud.arm_writes
    assert result["status"] == "reconciliation-required"


@pytest.mark.parametrize("selection", ["defender", "persona"])
def test_convergence_rejects_unordered_or_opaque_first_run_writes(selection):
    document = foundry_document()
    if selection == "defender":
        document["deployment"]["steps"][-1]["parameters"].update(
            enableDefenderforAIResourceLevel=True, enableDefenderforAISubLevel=False)
    else:
        document["deployment"]["persona_access"] = {"enabled": True}
    with pytest.raises(fl.Blocked, match="native-foundry-(defender-phase-order|persona-write-evidence)-required"):
        fl.plan_foundry_lifecycle(document)


def identity_source_case():
    document = foundry_document()
    fl.plan_foundry_lifecycle(document)
    foundation = next(step for step in document["deployment"]["steps"]
                      if step["template"] == fl.FOUNDRY_FOUNDATION)
    foundation["parameters"]["miPrjExists"] = False
    foundation["parameters"]["tagsProject"] = copy.deepcopy(foundation["parameters"]["tags"])
    identity = {
        "$schema": "resourceGroupDeploymentTemplate.json", "parameters": {
            "name": {"type": "string"}, "location": {"type": "string"}, "tags": {"type": "object"}},
        "resources": [
            {"type": "Microsoft.ManagedIdentity/userAssignedIdentities", "apiVersion": "2024-11-30",
             "name": "[parameters('name')]", "location": "[parameters('location')]",
             "tags": "[union(parameters('tags'), createObject('azd-service-name', parameters('name')))]"},
            {"type": "Microsoft.Authorization/roleAssignments", "apiVersion": "2022-04-01",
             "name": "[guid(resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', parameters('name')), variables('cognitiveServicesUserRoleDefinitionId'))]",
             "properties": {"principalId": "[reference(resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', parameters('name')), '2024-11-30').principalId]",
                            "principalType": "ServicePrincipal",
                            "roleDefinitionId": "[variables('cognitiveServicesUserRoleDefinitionId')]"}},
        ], "outputs": {"managedIdentityId": {"type": "string", "value": UAMI}},
    }
    naming = {"$schema": "resourceGroupDeploymentTemplate.json", "parameters": {}, "resources": []}
    module = lambda template, parameters: {"type": "Microsoft.Resources/deployments", "apiVersion": "2022-09-01",
        "resourceGroup": "[variables('targetResourceGroup')]",
        "subscriptionId": "[variables('subscriptionIdDevTestProd')]",
        "properties": {"template": copy.deepcopy(template), "parameters": parameters,
                       "expressionEvaluationOptions": {"scope": "inner"}, "mode": "Incremental"}}
    source = {"$schema": "subscriptionDeploymentTemplate.json", "languageVersion": "2.0",
        "parameters": {key: {} for key in foundation["parameters"]},
        "variables": {"targetResourceGroup": "reviewed", "subscriptionIdDevTestProd": "[subscription().subscriptionId]"},
        "resources": {
            "projectResourceGroup": {"type": "Microsoft.Resources/resourceGroups", "apiVersion": "2024-07-01",
                "name": "[variables('targetResourceGroup')]", "location": "[parameters('location')]",
                "tags": "[parameters('tagsProject')]"},
            "namingConvention": module(naming, {}),
            "miForPrj": {**module(identity, {
                "name": {"value": "[reference('namingConvention').outputs.namingConvention.value.miPrjName]"},
                "location": {"value": "[parameters('location')]"}, "tags": {"value": "[parameters('tagsProject')]"}}),
                "condition": "[not(variables('resourceExists').miPrj)]",
                "dependsOn": ["namingConvention", "projectResourceGroup"]},
            "unrelated": {"type": "Microsoft.Authorization/roleAssignments", "name": "must-not-run"},
        }, "outputs": {"foundationOutputs": {"type": "object", "value": {
            "miProjectName": "[reference('namingConvention').outputs.namingConvention.value.miPrjName]",
            "projectResourceGroupName": "[variables('targetResourceGroup')]", "unrelated": "[reference('unrelated')]"}}},
    }
    templates = {step["template"]: {"$schema": "subscriptionDeploymentTemplate.json",
                 "parameters": {key: {} for key in step["parameters"]}, "resources": []}
                 for step in document["deployment"]["steps"]}
    templates.update({fl.FOUNDRY_FOUNDATION: source, fl.FOUNDRY_MI_TEMPLATE: identity,
                      fl.FOUNDRY_NAMING_TEMPLATE: naming})
    lookup = {"parameters": {"managedIdentityName": {"type": "string"}}, "resources": [],
        "outputs": {key: {"type": "string", "value": "unresolved"} for key in ("principalId", "clientId", "resourceId", "name")}}
    array = {"parameters": {"managedIdentityOID": {"type": "string"}, "servicePrincipleOIDFromSecret": {"type": "secureString"}},
             "resources": [], "outputs": {"spAndMiArray": {"type": "array", "value": "unresolved"}}}
    templates[fl.FOUNDRY_LOOKUP_TEMPLATE] = lookup
    templates[fl.FOUNDRY_ARRAY_TEMPLATE] = array
    network = templates[fl.FOUNDRY_NETWORK_RBAC]
    network["languageVersion"] = "2.0"
    network["variables"] = {"targetResourceGroup": "reviewed"}
    network["resources"] = {
        "namingConvention": module(naming, {}),
        "getProjectMIPrincipalId": module(lookup, {"managedIdentityName": {
            "value": "[reference('namingConvention').outputs.miPrjName.value]"}}),
        "spAndMI2ArrayModule": module(array, {"managedIdentityOID": {
            "value": "[reference('getProjectMIPrincipalId').outputs.principalId.value]"},
            "servicePrincipleOIDFromSecret": {"value": ""}}),
        "cmnRbacVNet": module({"resources": [], "parameters": {"servicePrincipleAndMIArray": {"type": "array"}}}, {
            "servicePrincipleAndMIArray": {"value": "[reference('spAndMI2ArrayModule').outputs.spAndMiArray.value]"}}),
    }
    for step in document["deployment"]["steps"]:
        step["template_hash"] = fl.digest(templates[step["template"]])
    return document, templates


def test_identity_projection_retains_source_selector_and_excludes_all_roles():
    document, templates = identity_source_case()
    cloud = PlanCloud(document, templates)
    before = copy.deepcopy(templates)
    payload = fl.foundry_identity_projection(cloud, document, ROOT)
    resources = payload["properties"]["template"]["resources"]
    assert set(resources) == {"projectResourceGroup", "namingConvention", "miForPrj"}
    assert resources["miForPrj"]["condition"] == "[not(variables('resourceExists').miPrj)]"
    leaf = resources["miForPrj"]["properties"]["template"]["resources"]
    assert len(leaf) == 1 and leaf[0]["type"] == "Microsoft.ManagedIdentity/userAssignedIdentities"
    assert "roleAssignments" not in json.dumps(payload)
    assert templates == before


@pytest.mark.parametrize("defect", ["source-mismatch", "extra-identity", "existing-flag", "wrong-selector", "template-spec"])
def test_identity_projection_does_not_accept_an_arbitrary_producer(defect):
    document, templates = identity_source_case()
    foundation = next(step for step in document["deployment"]["steps"] if step["template"] == fl.FOUNDRY_FOUNDATION)
    source = templates[fl.FOUNDRY_FOUNDATION]
    if defect == "source-mismatch":
        source["resources"]["miForPrj"]["properties"]["template"]["resources"][0]["location"] = "foreign"
    elif defect == "extra-identity":
        templates[fl.FOUNDRY_MI_TEMPLATE]["resources"].append(
            copy.deepcopy(templates[fl.FOUNDRY_MI_TEMPLATE]["resources"][0]))
        source["resources"]["miForPrj"]["properties"]["template"] = templates[fl.FOUNDRY_MI_TEMPLATE]
    elif defect == "existing-flag":
        foundation["parameters"]["miPrjExists"] = True
    elif defect == "template-spec":
        document["deployment"]["steps"][-1]["template_spec_id"] = "unbound-template-spec"
    else:
        source["resources"]["miForPrj"]["properties"]["parameters"]["name"]["value"] = "arbitrary"
    foundation["template_hash"] = fl.digest(source)
    with pytest.raises(fl.Blocked):
        fl.foundry_identity_projection(PlanCloud(document, templates), document, ROOT)


class IdentityProducerCloud(PlanCloud):
    arm = fl.Cloud.arm

    def __init__(self, document, templates, failure=None):
        super().__init__(document, templates)
        self.bodies = {}
        self.failure = failure
        self.owner = {fl.TAG_KEYS[key]: document["target"][key] for key in ("factory_id", "scaleset_id")}
        self.owner[fl.TAG_KEYS["project_id"]] = "017"
        self.group = {"id": GROUP.lower(), "tags": self.owner, "location": document["target"]["region"],
                      "properties": {"provisioningState": "Succeeded"}, "etag": '"group"'}
        self.identity = {"id": UAMI, "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
            "location": document["target"]["region"], "tags": self.owner, "etag": '"identity"',
            "properties": {"principalId": UAMI_PRINCIPAL, "clientId": UAMI_CLIENT,
                           "tenantId": document["target"]["tenant_id"]}}
        # The prerequisites created the project group with the ownership tags only; the producer applies tagsProject.
        self.group_after = {**self.group, "tags": {**self.owner, "CostCenter": "reviewed-cost-center"}}
        if failure in ("group-tags", "group-modify"):
            self.bodies[GROUP.lower()] = copy.deepcopy(self.group)

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if not url.startswith(fl.ARM):
            return super().request(method, url, audience, data, headers, allowed)
        if "/whatIf?" in url:
            intent = {key: value for key, value in self.identity.items() if key not in ("properties", "etag")}
            changes = [{"resourceId": identifier, "changeType": "NoChange" if identifier in self.bodies else "Create",
                        "before": self.bodies.get(identifier), "after": body}
                       for identifier, body in ((GROUP.lower(), self.group), (UAMI, intent))]
            if self.failure == "identity-modify" and UAMI in self.bodies:
                # The projection re-applied with this review's tags differs from the producer's tags.
                changes[1] = {**changes[1], "changeType": "Modify",
                              "delta": [{"path": "tags.Updated", "propertyChangeType": "Modify", "before": "a", "after": "b"}]}
            if self.failure == "preview-role":
                changes.append({"resourceId": GROUP.lower() + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid.uuid4()),
                                "changeType": "Create", "after": {}})
            if self.failure == "no-identity":
                changes = [row for row in changes if row["resourceId"] != UAMI]
            if self.failure in ("group-tags", "group-modify"):
                delta = ([{"path": "tags.CostCenter", "propertyChangeType": "Create", "after": "reviewed-cost-center"}]
                         if self.failure == "group-tags" else
                         [{"path": "tags.CostCenter", "propertyChangeType": "Create", "after": "reviewed-cost-center"},
                          {"path": "properties.managedBy", "propertyChangeType": "Create", "after": "/subscriptions/other"}])
                changes[0] = {"resourceId": GROUP.lower(), "changeType": "Modify", "before": self.group,
                              "after": self.group_after, "delta": delta}
            return 200, {}, {"status": "Succeeded", "properties": {"changes": changes}}
        if method == "PUT":
            self.arm_writes.append((url, copy.deepcopy(data)))
            self.bodies.update({GROUP.lower(): copy.deepcopy(self.group_after if self.failure == "group-tags" else self.group),
                                UAMI: copy.deepcopy(self.identity)})
            if self.failure == "lost-put":
                raise fl.Blocked("transport-ambiguous")
            if self.failure == "wrong-tenant":
                self.bodies[UAMI]["properties"]["tenantId"] = str(uuid.uuid4())
            return 201, {}, {}
        identifier = urlsplit(url).path.lower()
        if "/providers/microsoft.resources/deployments/" in identifier:
            return 200, {}, {"id": identifier, "properties": {"provisioningState": "Succeeded", "outputs": {
                "foundationOutputs": {"value": {"miProjectName": "project-uami", "projectResourceGroupName": "reviewed"}}}}}
        return (200, {}, copy.deepcopy(self.bodies[identifier])) if identifier in self.bodies else (404, {}, {})


def identity_closure(cloud, scopes, resource_versions=None):
    bodies = {key: copy.deepcopy(value) for key, value in cloud.bodies.items() if fl.arm_scope(key) in {
        scope.lower() for scope in scopes}}
    groups = {key: {"body_hash": fl.digest(value), "etag": value.get("etag")} for key, value in bodies.items()
              if fl.RG_ID.fullmatch(key)}
    resources = {key: {"body_hash": fl.digest(value), "etag": value.get("etag"), "type": fl.resource_type_from_id(key),
                       "api_version": fl.FOUNDRY_MI_API} for key, value in bodies.items() if key not in groups}
    return {"groups": groups, "resources": resources, "providers": {}, "collections": {}}, bodies


def prepare_identity_worker(monkeypatch, failure=None):
    document, templates = identity_source_case()
    cloud = IdentityProducerCloud(document, templates, failure)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    monkeypatch.setattr(fl, "collect_resource_closure", identity_closure)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    document["deployment"] = fl._freeze_deployment_contents(cloud, document, ROOT)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    return document, cloud, locks


def test_cold_freeze_and_worker_produce_only_identity_then_stop_for_separate_approval(monkeypatch):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    assert document["deployment"]["foundry_identity_stage"]["contract"] == fl.FOUNDRY_IDENTITY_CONTRACT
    assert "account_resource_id" not in document["deployment"]["foundry_lifecycle"]
    assert not cloud.arm_writes
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    assert receipt["completion"] == "identity-only" and receipt["continuation_required"] is True
    assert len(cloud.arm_writes) == 1
    assert "roleAssignments" not in json.dumps(cloud.arm_writes)
    assert receipt["foundry_identity_receipt"]["identity"]["principal_id"] == UAMI_PRINCIPAL
    assert "foundry_readiness" not in receipt
    fl.verify_worker_receipt(locks, document)
    with pytest.raises(fl.Blocked):
        fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
            ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert len(cloud.arm_writes) == 1


@pytest.mark.parametrize("defect", [None, "bootstrap_preserved", "bootstrap_preservation_permit",
    "bootstrap_dns_soa_baseline", "foundry_phase_observations", "deleted", "proof",
    "deployment", "ownership", "source", "target"])
def test_identity_receipt_effects_never_claim_common_preservation_or_extra_work(monkeypatch, defect):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded"
    if defect in ("bootstrap_preserved", "bootstrap_preservation_permit",
                  "bootstrap_dns_soa_baseline", "foundry_phase_observations", "deleted"):
        receipt[defect] = {}
    elif defect == "proof":
        receipt["foundry_identity_receipt"] = None
    elif defect == "deployment":
        receipt["deployments"].append(copy.deepcopy(receipt["deployments"][0]))
    elif defect == "ownership":
        receipt["ownership"].append(copy.deepcopy(receipt["ownership"][0]))
    elif defect == "source":
        receipt["source_commit"] = "f" * 40
    elif defect == "target":
        receipt["target"] = {**receipt["target"], "project_ids": ["999"]}
    minimal = {key: document[key] for key in ("source", "target", "locks")}
    if defect:
        with pytest.raises(fl.Blocked):
            fl.verify_foundry_identity_receipt_effects(minimal, receipt)
        with pytest.raises(fl.Blocked):
            fl.verify_foundry_identity_receipt(document, receipt)
    else:
        fl.verify_foundry_identity_receipt_effects(minimal, receipt)
        fl.verify_foundry_identity_receipt(document, receipt)
    assert len(cloud.arm_writes) == 1


@pytest.mark.parametrize("failure", ["lost-put", "wrong-tenant"])
def test_identity_partial_or_failed_observation_is_durable_and_never_continues(monkeypatch, failure):
    document, cloud, locks = prepare_identity_worker(monkeypatch, failure)
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "reconciliation-required" and receipt["mutation_started"] is True
    assert len(cloud.arm_writes) == 1 and ACCOUNT not in cloud.bodies
    assert locks.request("GET", "runs/" + document["run_id"] + ".worker.json")[2] == receipt
    with pytest.raises(fl.Blocked):
        fl.verify_worker_receipt(locks, document)


def test_identity_preview_cannot_admit_roles_or_hide_incomplete_identity(monkeypatch):
    with pytest.raises(fl.Blocked, match="identity"):
        prepare_identity_worker(monkeypatch, "preview-role")


def test_identity_producer_rechecks_claim_after_last_read_before_put(monkeypatch):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    original_request, original_assert = cloud.request, locks.assert_held
    reads = []
    def request(method, url, audience, **kwargs):
        result = original_request(method, url, audience, **kwargs)
        if method == "GET" and urlsplit(url).path.lower() == UAMI and result[0] == 404:
            reads.append(url)
        return result
    def held():
        fl.require(len(reads) < 2, "cancelled-after-read")
        original_assert()
    monkeypatch.setattr(cloud, "request", request)
    monkeypatch.setattr(locks, "assert_held", held)
    monkeypatch.setattr(fl, "coordination", lambda *_: locks)
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "reconciliation-required" and receipt["error_code"] == "cancelled-after-read"
    assert not cloud.arm_writes


def test_identity_observation_polls_materialization_without_retrying_creation(monkeypatch):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    original_request, pending = cloud.request, []
    def request(method, url, audience, **kwargs):
        result = original_request(method, url, audience, **kwargs)
        if method == "GET" and urlsplit(url).path.lower() == UAMI and result[0] == 200 and not pending:
            pending.append(True)
            return 200, {}, {**result[2], "properties": {}}
        return result
    monkeypatch.setattr(cloud, "request", request)
    sleep = Mock()
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=sleep)
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    assert len(cloud.arm_writes) == 1
    sleep.assert_called_once_with(5)


@pytest.mark.parametrize("common_scope", ["owned", "dependency"])
def test_outer_native_producer_accepts_absent_owned_groups_not_absent_dependencies(monkeypatch, workspace, common_scope):
    document, templates = identity_source_case()
    if common_scope == "owned":
        document["locks"]["scopes"].append(COMMON)
        document["locks"]["common_dependencies"] = []
    cloud = IdentityProducerCloud(document, templates)
    if common_scope == "owned":
        cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
        cloud.enrollment["scopes"][COMMON.lower()] = copy.deepcopy(cloud.enrollment["scopes"][GROUP.lower()])
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    monkeypatch.setattr(fl, "collect_resource_closure", identity_closure)
    document["deployment"] = fl._freeze_deployment_contents(cloud, document, ROOT)
    seal(document)
    source, execution, path = setup_execute(monkeypatch, workspace)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(cloud, "assert_no_active_deployments",
                        lambda scope: fl.require(scope.lower() in cloud.bodies, "absent-group-enumerated"))
    def dispatch(cloud, locks, frozen, source_root, receipt, persist):
        receipt["mutation_started"] = True
        persist()
        fl.run_deployment_worker({"manifest": frozen, "lease_context": locks.held},
            source_root, frozen["run_id"], frozen["manifest_hash"], cloud=cloud, sleep=Mock())
        receipt["worker_receipt"] = fl.verify_worker_receipt(locks, frozen)
    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    result = fl.execute(document, source, execution, path, cloud=cloud)
    if common_scope == "dependency":
        assert result["status"] == "blocked" and result["error_code"] == "common-dependency-does-not-exist"
        assert not cloud.arm_writes
        return
    assert result["status"] == "succeeded", json.dumps(result)
    assert result["completion"] == "identity-only" and result["continuation_required"] is True
    assert COMMON.lower() not in cloud.bodies
    assert len(cloud.arm_writes) == 1 and path.exists()


def completed_identity(monkeypatch):
    document, cloud, locks = prepare_identity_worker(monkeypatch)
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    following = copy.deepcopy(document)
    following["run_id"] = str(uuid.uuid4())
    following["prepared_at"] = fl.utc_now()
    following["deployment"].pop("foundry_identity_stage")
    following["deployment"].setdefault("known_ownership", {})[UAMI] = {
        "run_id": receipt["run_id"], "receipt_hash": fl.digest(receipt)}
    return following, cloud, locks, receipt


def test_identity_continuation_requires_fresh_review_and_durable_exact_instance(monkeypatch):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    continuation = document["deployment"]["foundry_identity_continuation"]
    assert continuation["run_id"] == receipt["run_id"] != document["run_id"]
    assert continuation["proof"]["identity"]["principal_id"] == UAMI_PRINCIPAL
    assert len(cloud.arm_writes) == 1
    assert "account_resource_id" not in document["deployment"]["foundry_lifecycle"]


def test_identity_preparation_reuses_only_receipt_bound_original_run_inputs(monkeypatch):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    known = document["deployment"]["known_ownership"]
    following = copy.deepcopy(document)
    following.pop("deployment")
    result = fl.foundry_identity_preparation(cloud, following, known)
    assert result == {"run_id": receipt["run_id"],
                      "prepared_at": receipt["foundry_identity_receipt"]["producer_prepared_at"]}
    assert result["run_id"] != following["run_id"]
    assert "deployment" not in following
    # A changed config only changes what the receipt's hashes cover: the recovery warns (drift) and the live identity decides.
    following["config"]["changed"] = True
    assert fl.foundry_identity_preparation(cloud, following, known)["run_id"] == receipt["run_id"]
    assert len(cloud.arm_writes) == 1


@pytest.mark.parametrize("defect", ["hash", "same-run", "missing-time", "body", "tenant", "future"])
def test_identity_preparation_rejects_untrusted_or_replayed_seed(monkeypatch, defect):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    known = document["deployment"]["known_ownership"]
    if defect == "hash":
        known[UAMI]["receipt_hash"] = "a" * 64
    elif defect == "future":
        document["prepared_at"] = "2000-01-01T00:00:00Z"
    elif defect == "same-run":
        document["run_id"] = receipt["run_id"]
    elif defect == "body":
        cloud.bodies[UAMI]["etag"] = '"changed"'
    elif defect == "tenant":
        cloud.bodies[UAMI]["properties"]["tenantId"] = str(uuid.uuid4())
    else:
        receipt["foundry_identity_receipt"].pop("producer_prepared_at", None)
        cloud.runs["runs/" + receipt["run_id"] + ".worker.json"] = copy.deepcopy(receipt)
        known[UAMI]["receipt_hash"] = fl.digest(receipt)
    with pytest.raises(fl.Blocked):
        fl.foundry_identity_preparation(cloud, document, known)
    assert len(cloud.arm_writes) == 1


@pytest.mark.parametrize("defect", ["same-run", "tenant", "future", "principal",
                                  "body", "receipt-hash", "missing-receipt"])
def test_identity_continuation_rejects_replay_drift_and_unbound_success(monkeypatch, defect):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    if defect == "same-run":
        document["run_id"] = receipt["run_id"]
    elif defect == "config":
        document["config"]["extra"] = "different"
    elif defect == "source":
        document["source"]["commit"] = "b" * 40
    elif defect == "tenant":
        document["target"]["tenant_id"] = str(uuid.uuid4())
    elif defect == "scope":
        document["locks"]["scopes"].append(GROUP + "-different")
    elif defect == "future":
        document["prepared_at"] = "2000-01-01T00:00:00Z"
    elif defect == "principal":
        cloud.bodies[UAMI]["properties"]["principalId"] = str(uuid.uuid4())
    elif defect == "body":
        cloud.bodies[UAMI]["etag"] = '"changed"'
    elif defect == "receipt-hash":
        document["deployment"]["known_ownership"][UAMI]["receipt_hash"] = "a" * 64
    else:
        document["deployment"]["known_ownership"].pop(UAMI)
    with pytest.raises(fl.Blocked):
        fl.freeze_foundry_identity_stage(cloud, document, ROOT)
    assert len(cloud.arm_writes) == 1


def test_source_mi_role_principal_is_literal_only_after_valid_producer_receipt(monkeypatch):
    document, cloud, _, _ = completed_identity(monkeypatch)
    fl.freeze_foundry_identity_stage(cloud, document, ROOT)
    step = next(step for step in document["deployment"]["steps"] if step["template"] == fl.FOUNDRY_FOUNDATION)
    payload = fl.compiled_plan_step(cloud, document, step, ROOT)
    mi = payload["properties"]["template"]["resources"]["miForPrj"]["properties"]["template"]
    assert len(mi["resources"]) == 1
    assert mi["resources"][0]["properties"]["principalId"] == UAMI_PRINCIPAL
    assert cloud.templates[fl.FOUNDRY_MI_TEMPLATE]["resources"][1]["properties"]["principalId"].startswith("[reference(")
    assert len(cloud.arm_writes) == 1


def test_source_lookup_and_array_are_literal_bound_without_creating_another_identity(monkeypatch):
    document, cloud, _, _ = completed_identity(monkeypatch)
    fl.freeze_foundry_identity_stage(cloud, document, ROOT)
    step = next(step for step in document["deployment"]["steps"] if step["template"] == fl.FOUNDRY_NETWORK_RBAC)
    payload = fl.compiled_plan_step(cloud, document, step, ROOT)
    resources = payload["properties"]["template"]["resources"]
    assert resources["spAndMI2ArrayModule"]["properties"]["parameters"]["managedIdentityOID"] == {"value": UAMI_PRINCIPAL}
    assert resources["cmnRbacVNet"]["properties"]["parameters"]["servicePrincipleAndMIArray"] == {"value": [UAMI_PRINCIPAL]}
    assert resources["getProjectMIPrincipalId"]["properties"]["template"]["outputs"]["principalId"]["value"] == UAMI_PRINCIPAL
    assert len(cloud.arm_writes) == 1


def continued_native_worker(monkeypatch, *, omit_cognitive=False, repinned=False, stale=False):
    document, producer, prior_locks, producer_receipt = completed_identity(monkeypatch)
    if repinned:
        produced = document["route"]["commit"]
        document["route"]["commit"] = "e" * 40
        document["deployment"]["known_ownership"][UAMI]["route_commit"] = produced
    if stale:
        aged(document, producer_receipt)
        # The run happens a minute after the review prepared (15 h after the producer observed the identity).
        clock = fl.time.time
        monkeypatch.setattr(fl.time, "time", lambda: clock() + fl.RECEIPT_OBSERVATION_AGE_SECONDS + 3600 + 60)
    fl.freeze_foundry_identity_stage(producer, document, ROOT)
    prior_locks.release()
    cloud = FoundryCloud(document, producer.templates)
    cloud.runs = copy.deepcopy(producer.runs)
    cloud.bodies = copy.deepcopy(producer.bodies)
    cloud.planned[UAMI] = copy.deepcopy(cloud.bodies[UAMI])
    if not omit_cognitive:
        definition = GROUP.lower() + "/providers/microsoft.authorization/roledefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
        role = GROUP.lower() + "/providers/microsoft.authorization/roleassignments/" + str(
            uuid.uuid5(BICEP_GUID_NAMESPACE, UAMI + "-" + definition))
        cloud.planned[role] = {"id": role, "type": "Microsoft.Authorization/roleAssignments", "etag": '"role"',
            "properties": {"principalId": UAMI_PRINCIPAL, "principalType": "ServicePrincipal", "roleDefinitionId": definition}}
        prerequisites = tuple(document["deployment"]["foundry_lifecycle"]["phases"][0]["step_ids"])
        cloud.expanded[prerequisites].append(role)
    monkeypatch.setattr(fl, "combined_plan_payload", lambda cloud, doc, root, step_ids=None: {
        "step_ids": step_ids or [step["id"] for step in doc["deployment"]["steps"]]})
    monkeypatch.setattr(fl, "evaluate_what_if", cloud.preview)
    document["deployment"]["changes"] = cloud.preview(
        cloud, document, {}, {"step_ids": [step["id"] for step in document["deployment"]["steps"]]})
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    return document, cloud, locks, producer_receipt


def test_observed_identity_continuation_needs_new_claim_and_complete_literal_grants(monkeypatch):
    document, cloud, locks, producer = continued_native_worker(monkeypatch)
    assert document["run_id"] != producer["run_id"]
    with pytest.raises(fl.Blocked):
        fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
            ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert not cloud.executed
    locks.claim_run()
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    assert len(cloud.executed) == 3 and cloud.model in cloud.bodies
    assert receipt["foundry_identity_continuation"]["run_id"] == producer["run_id"]
    fl.verify_worker_receipt(locks, document)


def test_missing_source_cognitive_grant_blocks_receipt_bound_full_freeze(monkeypatch):
    with pytest.raises(fl.Blocked, match="dependent-cognitive-grant-required"):
        continued_native_worker(monkeypatch, omit_cognitive=True)


@pytest.mark.parametrize("defect", ["missing-proof", "drift", "forged-receipt"])
def test_identity_continuation_drift_blocks_before_any_dependent_put(monkeypatch, defect):
    document, cloud, locks, producer = continued_native_worker(monkeypatch)
    if defect == "missing-proof":
        document["deployment"]["foundry_identity_continuation"]["proof"].pop("body_hash")
        seal(document)
        with pytest.raises(fl.Blocked, match="identity-continuation"):
            locks.claim_run()
        assert not cloud.executed
        return
    elif defect == "drift":
        cloud.bodies[UAMI]["properties"]["principalId"] = str(uuid.uuid4())
    else:
        cloud.runs["runs/" + producer["run_id"] + ".worker.json"]["foundry_identity_receipt"]["role_writes"] = ["forged"]
    locks.claim_run()
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "reconciliation-required" and not cloud.executed


def foundry_document(*, network=True, route="ado"):
    document, templates = scoped_manifest(("017",), operation="deploy-project", route=route)
    for identifier, template in (("project-foundation", fl.FOUNDRY_FOUNDATION),
                                 ("project-network-rbac", fl.FOUNDRY_NETWORK_RBAC)):
        if any(item["template"] == template for item in document["deployment"]["steps"]):
            continue
        previous = document["deployment"]["steps"][-1]
        prerequisite = copy.deepcopy(previous)
        prerequisite.update(id=identifier, template=template, depends_on=[previous["id"]],
                            owner={**{key: document["target"][key] for key in ("factory_id", "scaleset_id")},
                                   "project_id": "017"})
        document["deployment"]["steps"].append(prerequisite)
    step = copy.deepcopy(document["deployment"]["steps"][0])
    step.update(id="foundry", template=fl.FOUNDRY_TEMPLATE,
                depends_on=[document["deployment"]["steps"][-1]["id"]])
    parameters = step["parameters"]
    parameters["tagsProject"] = parameters.pop("tags")
    parameters.update(enableAIFoundry=True, foundryV22AccountOnly=False, aiFoundryV2Exists=False,
                      useAVMFoundry=False, cmk=False, cmkDisableForFoundry=False,
                      aiFoundryV2ProjectExists=False,
                      disableAgentNetworkInjection=not network,
                      aca2SubnetId=GROUP + "/providers/Microsoft.Network/virtualNetworks/owned/subnets/agent",
                      deployModel_gpt_54_mini=True, deployModel_text_embedding_3_small=True)
    document["deployment"]["steps"].append(step)
    return document


def test_plan_splits_only_account_flag_preserves_models_and_full_configuration():
    document = foundry_document()
    original = copy.deepcopy(document["deployment"]["steps"][-1])
    fl.plan_foundry_lifecycle(document)
    data = document["deployment"]["foundry_lifecycle"]
    assert data["contract"] == fl.FOUNDRY_CONTRACT
    account, full = document["deployment"]["steps"][-2:]
    assert account["parameters"] == {**original["parameters"], "foundryV22AccountOnly": True}
    assert full["parameters"] == original["parameters"]
    assert full["depends_on"] == [account["id"]]
    assert data["network_scopes"] == [
        GROUP.lower() + "/providers/microsoft.network/virtualnetworks/owned",
        GROUP.lower() + "/providers/microsoft.network/virtualnetworks/owned/subnets/agent"]
    fl.validate_foundry_lifecycle(document)


def test_principal_binding_exposes_exact_producer_selectors_and_before_full_gates():
    document = foundry_document()
    fl.plan_foundry_lifecycle(document)
    data = document["deployment"]["foundry_lifecycle"]
    binding = data["principal_binding"]
    assert binding["source_commit"] == document["source"]["commit"]
    assert binding["template"] == fl.FOUNDRY_TEMPLATE
    assert binding["module"] == "aiFoundry2025NoAvmV22AccountOnly"
    assert binding["resource"] == "aiAccount"
    assert binding["producer_phase"] == "foundry-account-phase"
    assert binding["producer_step"] == data["account_step"]
    assert binding["resource_id_output"] == ["properties", "outputs", "aiFoundryV2ResourceId", "value"]
    assert binding["principal_property"] == ["identity", "principalId"]
    assert binding["tenant_property"] == ["identity", "tenantId"]
    assert binding["required_gates"] == [
        "account-identity", "configured-agent-network-ready"]
    assert binding["before_phase"] == "foundry-project-phase"
    assert binding["before_step"] == data["full_step"]
    binding["principal_property"] = ["properties", "principalId"]
    with pytest.raises(fl.Blocked, match="native-foundry-phase-binding-mismatch"):
        fl.validate_foundry_lifecycle(document)


@pytest.mark.parametrize("changes", [
    {"useAVMFoundry": True}, {"cmk": True}, {"foundryV22AccountOnly": True},
    {"aca2SubnetId": "/subscriptions/foreign/resourceGroups/foreign/providers/Microsoft.Network/virtualNetworks/x/subnets/y"},
])
def test_unknown_or_unsupported_topology_is_not_silently_planned(changes):
    document = foundry_document()
    document["deployment"]["steps"][-1]["parameters"].update(changes)
    with pytest.raises(fl.Blocked):
        fl.plan_foundry_lifecycle(document)


@pytest.mark.parametrize("changes", [{"aiFoundryV2Exists": True}, {"enableAIFoundry": False}])
def test_existing_or_disabled_path_is_unchanged(changes):
    document = foundry_document()
    document["deployment"]["steps"][-1]["parameters"].update(changes)
    before = copy.deepcopy(document)
    fl.plan_foundry_lifecycle(document)
    assert document == before


def test_empty_agent_subnet_matches_source_no_injection_branch_without_changing_flags():
    document = foundry_document()
    document["deployment"]["steps"][-1]["parameters"]["aca2SubnetId"] = ""
    fl.plan_foundry_lifecycle(document)
    data = document["deployment"]["foundry_lifecycle"]
    assert data["network_scopes"] == []
    assert data["require_capability_host"] is False
    assert data["principal_binding"]["required_gates"] == ["account-identity"]
    assert document["deployment"]["steps"][-1]["parameters"]["disableAgentNetworkInjection"] is False


def test_unsequenced_native_first_run_and_tampered_continuation_are_rejected():
    document = foundry_document()
    with pytest.raises(fl.Blocked, match="foundry"):
        fl.validate_foundry_lifecycle(document)
    fl.plan_foundry_lifecycle(document)
    document["deployment"]["steps"][-1]["parameters"]["deployModel_gpt_54_mini"] = False
    with pytest.raises(fl.Blocked, match="foundry"):
        fl.validate_foundry_lifecycle(document)


def test_phase_what_if_requires_exact_final_payload_not_just_matching_ids():
    expected = [{"resource_id": GROUP.lower(), "change_type": "Create", "before_hash": None, "after_hash": "a" * 64}]
    fl.verify_foundry_phase_changes(expected, expected, {})
    with pytest.raises(fl.Blocked, match="foundry-phase-what-if"):
        fl.verify_foundry_phase_changes(
            [{**expected[0], "after_hash": "b" * 64}], expected, {})
    with pytest.raises(fl.Blocked, match="foundry-phase-what-if"):
        fl.verify_foundry_phase_changes(
            [{**expected[0], "change_type": "Modify", "before_hash": "b" * 64}], expected, {})


def test_observed_generated_fields_only_allow_verified_nochange_not_new_desired_payloads():
    resource = GROUP.lower()
    reviewed = {"resource_id": resource, "change_type": "Create", "before_hash": None, "after_hash": "a" * 64}
    observed = {resource: {"body_hash": "b" * 64}}
    unchanged = {**reviewed, "change_type": "NoChange", "before_hash": "b" * 64, "after_hash": "b" * 64}
    fl.verify_foundry_phase_changes([unchanged], [reviewed], {resource: reviewed}, observed)
    with pytest.raises(fl.Blocked, match="foundry-phase-what-if"):
        fl.verify_foundry_phase_changes([unchanged], [reviewed], {resource: reviewed})
    with pytest.raises(fl.Blocked, match="foundry-phase-what-if"):
        fl.verify_foundry_phase_changes([unchanged], [{**reviewed, "after_hash": "c" * 64}],
                                        {resource: reviewed}, observed)
    with pytest.raises(fl.Blocked, match="foundry-phase-what-if"):
        fl.verify_foundry_phase_changes([{**unchanged, "change_type": "Modify"}], [reviewed],
                                        {resource: reviewed}, observed)


def test_readiness_is_bounded_and_observes_cancellation_and_errors():
    locks = Mock(spec=["assert_held", "authorize"])
    cloud = Mock()
    cloud.arm.return_value = (404, {}, {})
    with pytest.raises(fl.Blocked, match="foundry-readiness-timeout"):
        fl.wait_foundry_resource(cloud, locks, GROUP, lambda body: True, Mock(), attempts=2)
    assert cloud.arm.call_count == 2
    cloud.arm.reset_mock()
    locks.assert_held.side_effect = fl.Blocked("cancelled")
    with pytest.raises(fl.Blocked, match="cancelled"):
        fl.wait_foundry_resource(cloud, locks, GROUP, lambda body: True, Mock())
    cloud.arm.assert_not_called()
    locks.assert_held.side_effect = None
    cloud.arm.side_effect = fl.Blocked("HTTP-403")
    with pytest.raises(fl.Blocked, match="HTTP-403"):
        fl.wait_foundry_resource(cloud, locks, GROUP, lambda body: True, Mock())


ACCOUNT = GROUP.lower() + "/providers/microsoft.cognitiveservices/accounts/frozen-foundry"
PRINCIPAL = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
UAMI = GROUP.lower() + "/providers/microsoft.managedidentity/userassignedidentities/project-uami"
UAMI_PRINCIPAL = "aaaaaaaa-0000-4000-8000-000000000001"
UAMI_CLIENT = "aaaaaaaa-0000-4000-8000-000000000002"
BICEP_GUID_NAMESPACE = uuid.UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")


class FoundryCloud(PlanCloud):
    arm = fl.Cloud.arm

    def __init__(self, document, templates, failure=None):
        super().__init__(document, templates)
        self.failure = failure
        self.executed = []
        self.grant_writes = []
        self.source_grant_writes = []
        self.events = []
        self.planned = {}
        self.intents = {}
        self.expanded = {}
        owner = {fl.TAG_KEYS[key]: document["target"][key] for key in ("factory_id", "scaleset_id")}
        owner[fl.TAG_KEYS["project_id"]] = "017"
        network = document["deployment"]["foundry_lifecycle"]["network_scopes"]
        for identifier in network:
            self.planned[identifier] = {
                "id": identifier, "type": fl.resource_type_from_id(identifier),
                "location": document["target"]["region"], "tags": owner,
                "properties": {"provisioningState": "Succeeded"}}
        self.network_grant = (network[0] + "/providers/microsoft.authorization/roleassignments/" + str(uuid.uuid5(
            BICEP_GUID_NAMESPACE, UAMI_PRINCIPAL + "-nwContribSP-" + network[0].rsplit("/", 1)[-1]
            + "-" + fl.arm_scope(network[0])))) if network else None
        if network:
            self.planned[UAMI] = {
                "id": UAMI, "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
                "location": document["target"]["region"], "tags": owner, "etag": '"observed"',
                "properties": {"principalId": UAMI_PRINCIPAL, "clientId": UAMI_CLIENT,
                               "tenantId": document["target"]["tenant_id"]}}
            self.bodies[UAMI] = copy.deepcopy(self.planned[UAMI])
            self.planned[self.network_grant] = {
                "id": self.network_grant, "type": "Microsoft.Authorization/roleAssignments", "properties": {
                    "principalId": UAMI_PRINCIPAL, "principalType": "ServicePrincipal",
                    "roleDefinitionId": document["deployment"]["foundry_lifecycle"]["role_definition_id"],
                    "scope": network[0]}}
        self.planned[ACCOUNT] = {
            "id": ACCOUNT, "kind": "AIServices", "location": document["target"]["region"], "tags": owner,
            "identity": {"type": "SystemAssigned,UserAssigned" if network else "SystemAssigned",
                         "principalId": PRINCIPAL, "tenantId": document["target"]["tenant_id"],
                         **({"userAssignedIdentities": {UAMI: {
                             "principalId": UAMI_PRINCIPAL, "clientId": UAMI_CLIENT}}} if network else {})},
            "properties": {"provisioningState": "Succeeded",
            "networkInjections": [{"scenario": "agent", "subnetArmId": network[-1],
                                   "useMicrosoftManagedNetwork": False}] if network else []}}
        self.model = ACCOUNT + "/deployments/model-one"
        self.planned[self.model] = {"id": self.model, "tags": owner, "properties": {"provisioningState": "Succeeded"}}
        for body in self.planned.values():
            body["etag"] = '"observed"'
        stages = document["deployment"]["foundry_lifecycle"]["phases"]
        for stage, identifiers in zip(stages, [
                network + ([self.network_grant] if network else []), [ACCOUNT], [self.model]]):
            self.expanded[tuple(stage["step_ids"])] = list(identifiers)

    def payload_steps(self, payload):
        if "step_ids" in payload:
            return payload["step_ids"]
        names = {row["name"] for row in payload["properties"]["template"]["resources"]}
        return [step["id"] for step in self.document["deployment"]["steps"]
                if fl.deployment_endpoint(self.document, step).rsplit("/", 1)[-1] in names]

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if not url.startswith(fl.ARM):
            return super().request(method, url, audience, data, headers, allowed)
        identifier = unquote(urlsplit(url).path).lower()
        self.events.append((method, identifier))
        if method == "POST" and "/whatIf?" in url:
            selected = self.payload_steps(data)
            identifiers = [key for ids, values in self.expanded.items() if set(ids) <= set(selected) for key in values]
            return 200, {}, {"properties": {"changes": [
                {"resourceId": key, "changeType": "NoChange" if key in self.bodies else "Create",
                 "before": copy.deepcopy(self.bodies.get(key)), "after": copy.deepcopy(self.planned[key])}
                for key in identifiers]}}
        if method == "PUT" and "/providers/microsoft.resources/deployments/" in identifier:
            ids = tuple(self.payload_steps(data))
            self.executed.append(ids)
            for resource in self.expanded[ids]:
                self.bodies[resource] = copy.deepcopy(self.planned[resource])
                if "/roleassignments/" in resource:
                    self.source_grant_writes.append(resource)
                if resource == ACCOUNT and self.document["deployment"]["foundry_lifecycle"]["require_capability_host"]:
                    host = ACCOUNT + "/capabilityhosts/" + ACCOUNT.rsplit("/", 1)[-1] + "@aml_aiagentservice"
                    self.bodies[host] = {"id": host, "type": "Microsoft.CognitiveServices/accounts/capabilityHosts",
                        "tags": copy.deepcopy(self.planned[ACCOUNT]["tags"]), "etag": '"observed"',
                        "properties": {"provisioningState": "Succeeded"}}
            return 201, {}, {"id": identifier, "properties": {"provisioningState": "Accepted"}}
        if "/providers/microsoft.resources/deployments/" in identifier:
            body = {"id": identifier, "properties": {"provisioningState": "Succeeded"}}
            account_step = next(step for step in self.document["deployment"]["steps"]
                                if step["id"] == "foundry-account")
            if identifier == fl.deployment_endpoint(self.document, account_step).removeprefix(fl.ARM).lower():
                body["properties"]["outputs"] = {
                    "aiFoundryV2ResourceId": {"value": ACCOUNT if self.failure != "output" else ACCOUNT + "-wrong"},
                    "aiFoundryV2Name": {"value": ACCOUNT.rsplit("/", 1)[-1]}}
            foundation = next(step for step in self.document["deployment"]["steps"]
                              if step["template"] == fl.FOUNDRY_FOUNDATION)
            if identifier == fl.deployment_endpoint(self.document, foundation).removeprefix(fl.ARM).lower():
                body["properties"]["outputs"] = {"foundationOutputs": {"value": {
                    "miProjectName": UAMI.rsplit("/", 1)[-1],
                    "projectResourceGroupName": GROUP.split("/")[4]}}}
            return 200, {}, body
        if "/roleassignments/" in identifier:
            if method == "PUT":
                self.grant_writes.append(identifier)
                if self.failure == "rbac":
                    raise fl.Blocked("test-role-403")
                self.bodies[identifier] = {"id": identifier, "etag": '"observed"', **copy.deepcopy(data)}
                return 201, {}, self.bodies[identifier]
            if self.failure == "rbac" and self.executed:
                raise fl.Blocked("test-role-403")
            if self.failure == "role-conflict" and self.executed:
                return 200, {}, {"id": identifier, "properties": {"principalId": "foreign"}}
            if self.failure == "role-timeout" and self.executed:
                return 404, {}, {}
        if identifier == UAMI and self.executed:
            if self.failure == "uami-tenant":
                value = copy.deepcopy(self.bodies[identifier])
                value["properties"]["tenantId"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
                return 200, {}, value
            if self.failure == "uami-principal":
                value = copy.deepcopy(self.bodies[identifier])
                value["properties"]["principalId"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
                return 200, {}, value
        if "/capabilityhosts/" in identifier:
            if self.failure == "cancel":
                raise KeyboardInterrupt()
            body = copy.deepcopy(self.bodies[identifier])
            body["properties"]["provisioningState"] = ("Creating" if self.failure == "timeout" else
                "Failed" if self.failure == "caphost" else "Succeeded")
            return 200, {}, body
        if identifier == ACCOUNT and ACCOUNT in self.bodies:
            if self.failure == "account":
                raise fl.Blocked("test-account-403")
            if self.failure == "principal":
                return 200, {}, {**self.bodies[identifier], "identity": {"principalId": ""}}
            if self.failure == "principal-changed" and any("/capabilityhosts/" in path for _, path in self.events):
                return 200, {}, {**self.bodies[identifier],
                                 "identity": {**self.bodies[identifier]["identity"],
                                              "principalId": "ffffffff-ffff-ffff-ffff-ffffffffffff"}}
            if self.failure == "tenant":
                return 200, {}, {**self.bodies[identifier],
                                 "identity": {**self.bodies[identifier]["identity"],
                                              "tenantId": "ffffffff-ffff-ffff-ffff-ffffffffffff"}}
        if identifier not in self.bodies:
            assert 404 in allowed
            return 404, {}, {}
        return 200, {}, copy.deepcopy(self.bodies[identifier])

    def preview(self, cloud, document, step, payload, sleep=None, unchanged_resources=None,
                resource_payloads=None, source_changes=None, phase_receipt=None):
        selected = payload["step_ids"]
        resources = [identifier for ids, values in self.expanded.items() if set(ids) <= set(selected)
                     for identifier in values]
        after = {identifier: self.intents.get(identifier, self.planned[identifier])
                 if identifier not in self.bodies else self.planned[identifier] for identifier in resources}
        changes = sorted([{
            "resource_id": identifier, "change_type": "NoChange" if identifier in self.bodies else "Create",
            "before_hash": fl.digest(self.bodies[identifier]) if identifier in self.bodies else None,
            "after_hash": fl.digest(after[identifier]),
        } for identifier in resources], key=lambda row: row["resource_id"])
        if resource_payloads is not None:
            resource_payloads.update(copy.deepcopy(after))
        if source_changes is not None:
            source_changes.update({row["resource_id"]: row["change_type"] for row in changes})
        if self.failure == "drift" and len(self.executed) == 2 and changes:
            changes[-1]["after_hash"] = "f" * 64
        return changes


def native_closure(cloud, scopes, resource_versions=None):
    selected = {scope.lower() for scope in scopes}
    bodies = {key: copy.deepcopy(body) for key, body in cloud.bodies.items() if fl.arm_scope(key) in selected}
    groups = {key: {"body_hash": fl.digest(body), "etag": body.get("etag")}
              for key, body in bodies.items() if fl.RG_ID.fullmatch(key)}
    closure = {"providers": {}, "collections": {}, "groups": groups,
               "resources": {key: {"body_hash": fl.digest(body), "etag": body.get("etag"),
                                   "api_version": "2024-05-01"} for key, body in bodies.items() if key not in groups}}
    for identifier, row in closure["resources"].items():
        row["type"] = fl.resource_type_from_id(identifier)
        if "/capabilityhosts/" in identifier or identifier == ACCOUNT:
            row["api_version"] = fl.FOUNDRY_API
        elif identifier == UAMI:
            row["api_version"] = fl.FOUNDRY_MI_API
        elif "/roleassignments/" in identifier:
            row["api_version"] = "2022-04-01"
    return closure, bodies


def native_worker(monkeypatch, failure=None, configure=None, *, claim=True, injected=True, route="ado", prepare=None, real_payload=False):
    document = foundry_document(route=route)
    if prepare:
        prepare(document)
    if not injected:
        document["deployment"]["steps"][-1]["parameters"]["disableAgentNetworkInjection"] = True
    fl.plan_foundry_lifecycle(document)
    templates = {}
    for step in document["deployment"]["steps"]:
        template = {"$schema": "subscriptionDeploymentTemplate.json",
                    "parameters": {key: {} for key in step["parameters"]}, "resources": []}
        templates[step["template"]] = template
        step["template_hash"] = fl.digest(template)
    cloud = FoundryCloud(document, templates, failure)
    if route == "gha":
        common = copy.deepcopy(cloud.bodies[GROUP.lower()])
        common["id"] = COMMON
        common["tags"].pop(fl.TAG_KEYS["project_id"], None)
        cloud.bodies[COMMON.lower()] = common
    if configure:
        configure(document, cloud)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", native_closure)
    if real_payload:
        payload = fl.combined_plan_payload(cloud, document, ROOT)
        document["deployment"]["changes"] = fl.evaluate_what_if(
            cloud, document, {"id": "factory", "scope": "subscription"}, payload)
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    else:
        monkeypatch.setattr(fl, "combined_plan_payload", lambda cloud, doc, root, step_ids=None: {
            "step_ids": step_ids or [step["id"] for step in doc["deployment"]["steps"]]})
        monkeypatch.setattr(fl, "evaluate_what_if", cloud.preview)
        document["deployment"]["changes"] = cloud.preview(
            cloud, document, {}, {"step_ids": [step["id"] for step in document["deployment"]["steps"]]})
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    if claim:
        locks.acquire()
        locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", native_closure)
    return document, cloud, locks


def test_noninjected_worker_runs_real_ordered_phases_and_verifies_durable_receipt(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch, injected=False)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result.get("error_code") is None, result.get("error_code")
    assert result["status"] == "succeeded", result
    phases = document["deployment"]["foundry_lifecycle"]["phases"]
    assert cloud.executed == [tuple(phase["step_ids"]) for phase in phases]
    assert cloud.grant_writes == []
    assert cloud.source_grant_writes == []
    assert len([key for key in cloud.bodies if key.endswith("/deployments/model-one")]) == 1
    assert fl.verify_worker_receipt(locks, document) == result
    assert result["foundry_readiness"]["principal_binding_hash"] == fl.digest(
        document["deployment"]["foundry_lifecycle"]["principal_binding"])
    assert result["foundry_readiness"]["completed_gates"] == ["account-identity"]
    assert "foundry_agent_readiness" not in result


@pytest.mark.parametrize("failure,code", [
    ("output", "foundry-account-outputs-mismatch"), ("account", "test-account-403"),
    ("principal", "foundry-readiness-timeout"),
    ("caphost", "foundry-resource-provisioning-failed"), ("timeout", "foundry-readiness-timeout"),
    ("principal-changed", "foundry-account-principal-changed"),
    ("cancel", "unexpected-worker-failure"),
    ("tenant", "foundry-account-tenant-mismatch"),
])
def test_native_worker_never_continues_or_replays_failed_account_gate(monkeypatch, failure, code):
    document, cloud, locks = native_worker(monkeypatch, failure)
    envelope = {"manifest": document, "lease_context": locks.held}
    result = fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required", result
    assert result["error_code"] == code, result
    assert result["mutation_started"] is True
    assert len(cloud.executed) == 2
    assert len(result["foundry_phases"]) == 1
    assert "pending_deployment" in result
    assert cloud.leases
    with pytest.raises(fl.Blocked):
        fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert len(cloud.executed) == 2


@pytest.mark.parametrize("failure,code", [
    ("rbac", "test-role-403"), ("role-conflict", "native-foundry-phase-instance-changed"),
    ("role-timeout", "native-foundry-phase-instance-changed"),
    ("uami-tenant", "native-foundry-phase-instance-changed"),
    ("uami-principal", "native-foundry-phase-instance-changed"),
])
def test_source_uami_or_grant_failure_blocks_account_creation(monkeypatch, failure, code):
    document, cloud, locks = native_worker(monkeypatch, failure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required", result
    assert result["error_code"] == code, result
    assert len(cloud.executed) == 1
    assert ACCOUNT not in cloud.bodies and cloud.grant_writes == []
    assert len(result["foundry_phases"]) == 1
    assert cloud.leases
    with pytest.raises(fl.Blocked):
        fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
            ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert len(cloud.executed) == 1


def test_changed_full_phase_after_account_success_stops_with_both_completed_phases(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch, "drift")
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "foundry-phase-what-if-changed"
    assert len(result["foundry_phases"]) == 2
    assert result["foundry_readiness"]["status"] == "provider-ready"
    assert len(cloud.executed) == 2


def test_canonical_phase_payloads_have_unique_ids_and_do_not_replay_prerequisites():
    document = foundry_document()
    fl.plan_foundry_lifecycle(document)
    templates = {}
    for step in document["deployment"]["steps"]:
        template = {"$schema": "subscriptionDeploymentTemplate.json",
                    "parameters": {key: {} for key in step["parameters"]}, "resources": []}
        step["template_hash"] = fl.digest(template)
        templates[step["template"]] = template
    cloud = Mock()
    cloud.compile_template.side_effect = lambda root, path: templates[path]
    data = document["deployment"]["foundry_lifecycle"]
    for phase in data["phases"]:
        payload = fl.combined_plan_payload(cloud, document, ROOT, phase["step_ids"])
        children = payload["properties"]["template"]["resources"]
        assert len(children) == len(phase["step_ids"])
        assert children[0]["dependsOn"] == []
    account = fl.combined_plan_payload(cloud, document, ROOT, [data["account_step"]])
    full = fl.combined_plan_payload(cloud, document, ROOT, [data["full_step"]])
    assert account["properties"]["parameters"]["step_0"]["value"]["foundryV22AccountOnly"] is True
    assert full["properties"]["parameters"]["step_0"]["value"]["foundryV22AccountOnly"] is False
    assert account["properties"]["template"]["resources"][0]["name"] != full["properties"]["template"]["resources"][0]["name"]


def test_freeze_does_not_claim_existing_account_as_new_or_change_existence_flags(monkeypatch):
    document, cloud, _ = native_worker(monkeypatch)
    cloud.bodies[ACCOUNT] = copy.deepcopy(cloud.planned[ACCOUNT])
    with pytest.raises(fl.Blocked, match="native-foundry-exact-created-account-required"):
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    assert not cloud.executed
    assert not cloud.grant_writes
    assert document["deployment"]["steps"][-1]["parameters"]["aiFoundryV2Exists"] is False


def test_frozen_account_binding_cannot_substitute_another_created_resource(monkeypatch):
    document, _, _ = native_worker(monkeypatch)
    document["deployment"]["foundry_lifecycle"]["account_resource_id"] = ACCOUNT + "-other"
    with pytest.raises(fl.Blocked, match="native-foundry-account-preview-binding-mismatch"):
        fl.validate_foundry_lifecycle(document)


@pytest.mark.parametrize("field,value", [
    ("principal_binding_hash", "f" * 64),
    ("completed_gates", ["account-identity"]),
    ("completed_gates", ["configured-agent-network-ready", "account-identity"]),
])
def test_gate_binding_receipt_must_be_complete_and_ordered(monkeypatch, field, value):
    document, cloud, locks = native_worker(monkeypatch)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    result["foundry_readiness"][field] = value
    with pytest.raises(fl.Blocked, match="native-foundry-readiness-receipt-incomplete"):
        fl.verify_foundry_provider_readiness_receipt(document, result)


class ActualWhatIfCloud(FoundryCloud):
    """Exercise the real what-if normalizer and original/observed proof merge."""

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if method == "POST" and "/whatIf?" in url:
            selected = data["step_ids"]
            identifiers = [identifier for ids, values in self.expanded.items() if set(ids) <= set(selected)
                           for identifier in values]
            changes = []
            for identifier in identifiers:
                before, after = self.bodies.get(identifier), self.planned[identifier]
                kind = "Create" if before is None else "NoChange" if before == after else "Modify"
                changes.append({"resourceId": identifier, "changeType": kind,
                                "before": copy.deepcopy(before), "after": copy.deepcopy(after)})
            return 200, {}, {"properties": {"changes": changes}}
        return super().request(method, url, audience, data, headers, allowed)


def observation_case(monkeypatch, disposition="owned"):
    document = foundry_document()
    document["deployment"]["steps"][-1]["parameters"]["aca2SubnetId"] = ""
    fl.plan_foundry_lifecycle(document)
    cloud = ActualWhatIfCloud(document, {})
    identifier = RESOURCE.lower()
    before = copy.deepcopy(cloud.bodies[identifier])
    after = {**before, "properties": {**before.get("properties", {}), "reviewedSetting": "changed"}}
    cloud.planned[identifier] = after
    phases = document["deployment"]["foundry_lifecycle"]["phases"]
    cloud.expanded[tuple(phases[0]["step_ids"])] = [identifier]
    document["deployment"]["bootstrap_foundation"] = {
        "contract": fl.EXACT_BOOTSTRAP_CONTRACT,
        "resources": {identifier: {"disposition": disposition, "body_hash": fl.digest(before),
                                   "api_version": "2024-05-01"}}}
    monkeypatch.setattr(fl, "combined_plan_payload", lambda cloud, doc, root, step_ids=None: {
        "step_ids": step_ids or [step["id"] for step in doc["deployment"]["steps"]], "properties": {}})
    monkeypatch.setattr(fl, "collect_resource_closure", native_closure)
    payload = fl.combined_plan_payload(cloud, document, ROOT)
    document["deployment"]["changes"] = fl.evaluate_what_if(
        cloud, document, {"id": "factory", "scope": "subscription"}, payload)
    return document, cloud, before, after


def test_real_multiphase_what_if_accepts_only_reviewed_owned_postphase_observations(monkeypatch):
    document, cloud, before, after = observation_case(monkeypatch)
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    seal(document)
    closure, bodies = native_closure(cloud, document["locks"]["scopes"])
    receipt = {"deployments": [], "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
               "status": "running", "foundry_initial_observations": fl.foundry_inventory_observations(document, closure, bodies)}
    fl.run_foundry_phases(cloud, Mock(spec=["assert_held", "authorize"]), document, ROOT, receipt, Mock(), Mock())
    assert len(cloud.executed) == 3
    assert cloud.bodies[RESOURCE.lower()] == after
    assert receipt["foundry_phase_observations"][0]["resources"][RESOURCE.lower()]["body_hash"] == fl.digest(after)
    assert document["deployment"]["bootstrap_foundation"]["resources"][RESOURCE.lower()]["body_hash"] == fl.digest(before)
    fl.verify_foundry_phase_receipts(document, receipt)


def test_preserve_only_modification_is_rejected_before_any_native_phase_write(monkeypatch):
    document, cloud, _, _ = observation_case(monkeypatch, "preserve")
    with pytest.raises(fl.Blocked, match="bootstrap-prerequisite-write-forbidden"):
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    assert cloud.executed == [] and cloud.grant_writes == []


@pytest.mark.parametrize("defect", ["preserve", "unreviewed", "wrong-before", "no-prior-phase"])
def test_phase_observation_cannot_supersede_unapproved_or_preserved_original(monkeypatch, defect):
    document, cloud, before, after = observation_case(monkeypatch)
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    phase = document["deployment"]["foundry_lifecycle"]["phases"][1]
    if defect == "preserve":
        document["deployment"]["bootstrap_foundation"]["resources"][RESOURCE.lower()]["disposition"] = "preserve"
    elif defect == "unreviewed":
        document["deployment"]["foundry_lifecycle"]["phases"][0]["changes"][0]["change_type"] = "NoChange"
    elif defect == "wrong-before":
        document["deployment"]["foundry_lifecycle"]["phases"][0]["changes"][0]["before_hash"] = "f" * 64
    else:
        phase = document["deployment"]["foundry_lifecycle"]["phases"][0]
    with pytest.raises(fl.Blocked, match="what-if-instance-proof-conflict"):
        fl.evaluate_what_if(cloud, document, {"id": phase["id"], "scope": "subscription"},
                           fl.combined_plan_payload(cloud, document, ROOT, phase["step_ids"]),
                           unchanged_resources={RESOURCE.lower(): {"body_hash": fl.digest(after)}})


def test_uami_binding_matches_real_foundation_account_and_network_grant_source():
    document = foundry_document()
    fl.plan_foundry_lifecycle(document)
    binding = document["deployment"]["foundry_lifecycle"]["agent_identity_binding"]
    root = (ROOT / fl.FOUNDRY_TEMPLATE).read_text()
    account = (ROOT / "environment_setup/aifactory/bicep/modules/csFoundry/aiFoundry2025AvmOffApimAccount.bicep").read_text()
    foundation = (ROOT / fl.FOUNDRY_FOUNDATION).read_text()
    network = (ROOT / fl.FOUNDRY_NETWORK_RBAC).read_text()
    grant = (ROOT / "environment_setup/aifactory/bicep/modules/vnetRBACReader.bicep").read_text()
    identity = (ROOT / "environment_setup/aifactory/bicep/modules/mi.bicep").read_text()
    principals = (ROOT / "environment_setup/aifactory/bicep/modules/spAndMiArray.bicep").read_text()
    assert root.count("agentInjectionUserAssignedIdentityResourceId: getProjectMIPrincipalId.outputs.resourceId") == 2
    assert "var useAgentInjectionUami = agentNetworkInjectionEnabled && !empty(agentInjectionUserAssignedIdentityResourceId)" in account
    assert "type: 'SystemAssigned,UserAssigned'" in account
    assert "'${agentInjectionUserAssignedIdentityResourceId}': {}" in account
    assert "miProjectName: miPrjName" in foundation
    assert "module miForPrj '../modules/mi.bicep'" in foundation
    assert "module cmnRbacVNet '../modules/vnetRBACReader.bicep'" in network
    assert "assignBastionNsgRole: false" in network
    assert "var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId" in network
    assert "managedIdentityOID: var_miPrj_PrincipalId" in network
    assert "var spAndMiArray = spAndMI2ArrayModule.outputs.spAndMiArray" in network
    assert "servicePrincipleAndMIArray: spAndMiArray" in network
    assert "param includeManagedIdentity bool = true" in principals
    assert "[managedIdentityOID]" in principals
    assert "output spAndMiArray array = concat(serviceArray, managedIdentityArray)" in principals
    assert "resource networkContributorSPVnet " in grant and "scope:vNetNameResource" in grant
    assert "guid('${servicePrincipleAndMIArray[i]}-nwContribSP-${vNetName}-${resourceGroup().id}')" in grant
    assert "resource cognitiveServicesUserRoleAssignment " in identity
    assert "name: guid(managedIdentity.id, cognitiveServicesUserRoleDefinitionId)" in identity
    assert "principalId: managedIdentity.properties.principalId" in identity
    assert binding["principal_property"] == ["properties", "principalId"]
    assert binding["module"] == "getProjectMIPrincipalId"
    assert binding["grant_resource"] == "networkContributorSPVnet"
    assert binding["before_phase"] == "foundry-account-phase"


def test_uami_and_reviewed_role_are_observed_before_account_put(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    account = fl.deployment_endpoint(document, {"id": "foundry-account-phase", "scope": "subscription"})
    put = cloud.events.index(("PUT", urlsplit(account).path.lower()))
    assert ("GET", UAMI) in cloud.events[:put]
    assert ("GET", cloud.network_grant) in cloud.events[:put]
    assert result["foundry_agent_readiness"]["principal_id"] != result["foundry_readiness"]["principal_id"]
    assert cloud.grant_writes == []


@pytest.mark.parametrize("defect", ["system-only", "different-uami", "different-client", "different-principal"])
def test_account_must_attach_the_exact_source_uami_before_full_continuation(monkeypatch, defect):
    document, cloud, locks = native_worker(monkeypatch)
    original_request = cloud.request
    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        result = original_request(method, url, audience, data, headers, allowed)
        if method == "GET" and urlsplit(url).path.lower() == ACCOUNT and ACCOUNT in cloud.bodies:
            status, response_headers, body = result
            body = copy.deepcopy(body)
            if defect == "system-only":
                body["identity"].pop("userAssignedIdentities")
                body["identity"]["type"] = "SystemAssigned"
            elif defect == "different-uami":
                body["identity"]["userAssignedIdentities"] = {UAMI + "-other": {
                    "clientId": UAMI_CLIENT, "principalId": UAMI_PRINCIPAL}}
            else:
                key = "clientId" if defect == "different-client" else "principalId"
                body["identity"]["userAssignedIdentities"][UAMI][key] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
            return status, response_headers, body
        return result
    cloud.request = request
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] in ("native-foundry-source-uami-required", "native-foundry-account-agent-identity-mismatch")
    assert len(cloud.executed) == 2 and cloud.model not in cloud.bodies


def test_claim_cancellation_after_read_is_not_accepted_as_readiness():
    document = foundry_document()
    locks = Mock(spec=["assert_held", "authorize"])
    locks.authorize.side_effect = [None, fl.Blocked("execution-claim-not-active")]
    cloud = Mock()
    cloud.arm.return_value = (200, {}, {"id": UAMI, "properties": {"provisioningState": "Succeeded"}})
    with pytest.raises(fl.Blocked, match="execution-claim-not-active"):
        fl.wait_foundry_resource(cloud, locks, UAMI, lambda body: True, Mock(), document=document)
    assert cloud.arm.call_count == 1


@pytest.mark.parametrize("defect", ["tenant", "principal", "client", "scope", "effective", "host-subject", "binding"])
def test_source_uami_receipts_do_not_accept_wrong_or_overstated_evidence(monkeypatch, defect):
    document, cloud, locks = native_worker(monkeypatch)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    proof = result["foundry_agent_readiness"]
    if defect in ("tenant", "principal", "client"):
        proof[defect + "_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    elif defect == "scope":
        proof["grants"][0]["scope"] += "/subnets/not-reviewed"
    elif defect == "effective":
        proof["effective_permissions_proven"] = True
    elif defect == "host-subject":
        result["foundry_readiness"]["capability_host"]["configured_principal_id"] = PRINCIPAL
    else:
        proof["binding_hash"] = "f" * 64
    with pytest.raises(fl.Blocked):
        fl.verify_foundry_provider_readiness_receipt(document, result)


def preserved_network_case(monkeypatch, *, grant_exists):
    from .test_factory_lifecycle_bootstrap_handoff import exact_document
    document = foundry_document()
    fl.plan_foundry_lifecycle(document)
    templates = {}
    for step in document["deployment"]["steps"]:
        template = {"$schema": "subscriptionDeploymentTemplate.json",
                    "parameters": {key: {} for key in step["parameters"]}, "resources": []}
        templates[step["template"]] = template
        step["template_hash"] = fl.digest(template)
    cloud = FoundryCloud(document, templates)
    protected = document["deployment"]["foundry_lifecycle"]["network_scopes"][:]
    if grant_exists:
        protected.append(cloud.network_grant)
    for identifier in protected:
        cloud.bodies[identifier] = copy.deepcopy(cloud.planned[identifier])
    proof = exact_document(cloud)["deployment"]["bootstrap_foundation"]
    for identifier in protected:
        row = proof["resources"][identifier]
        row.update(disposition="preserve", preservation="bootstrap-prerequisite")
        row.pop("owner")
    document["deployment"]["bootstrap_foundation"] = proof
    def closure(cloud, scopes, versions=None):
        result, bodies = simple_plan_closure(cloud, scopes, versions)
        for identifier, row in result["resources"].items():
            row.update(type=fl.resource_type_from_id(identifier),
                       api_version=(versions or {}).get(identifier, row["api_version"]))
        for identifier, row in result["groups"].items():
            row.update(body_hash=fl.digest(bodies[identifier]), etag=bodies[identifier].get("etag"))
        return result, bodies
    monkeypatch.setattr(fl, "collect_resource_closure", closure)
    monkeypatch.setattr(fl, "combined_plan_payload", lambda cloud, doc, root, step_ids=None: {
        "step_ids": step_ids or [step["id"] for step in doc["deployment"]["steps"]]})
    monkeypatch.setattr(fl, "evaluate_what_if", cloud.preview)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    document["deployment"]["bootstrap_ownership"] = fl.bootstrap_ownership_snapshot(cloud, document)
    document["deployment"]["changes"] = cloud.preview(
        cloud, document, {}, fl.combined_plan_payload(cloud, document, ROOT))
    return document, cloud, protected


def test_missing_source_grant_under_preserved_network_blocks_before_any_arm_write(monkeypatch):
    document, cloud, _ = preserved_network_case(monkeypatch, grant_exists=False)
    with pytest.raises(fl.Blocked, match="bootstrap-prerequisite-write-forbidden"):
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    assert cloud.executed == [] and cloud.grant_writes == [] and cloud.source_grant_writes == []
    assert ACCOUNT not in cloud.bodies


def test_bootstrap_grant_cannot_replace_an_assignment_missing_from_source_phase(monkeypatch):
    document, cloud, _ = preserved_network_case(monkeypatch, grant_exists=True)
    prerequisites = tuple(document["deployment"]["foundry_lifecycle"]["phases"][0]["step_ids"])
    cloud.expanded[prerequisites].remove(cloud.network_grant)
    document["deployment"]["changes"] = cloud.preview(
        cloud, document, {}, fl.combined_plan_payload(cloud, document, ROOT))
    with pytest.raises(fl.Blocked, match="native-foundry-reviewed-network-grants-required"):
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    assert cloud.executed == [] and cloud.grant_writes == [] and cloud.source_grant_writes == []


def real_preserved_grant_case(monkeypatch, *, kind="NoChange", after_none=False):
    evaluate = fl.evaluate_what_if
    document, cloud, _ = preserved_network_case(monkeypatch, grant_exists=True)
    monkeypatch.setattr(fl, "evaluate_what_if", evaluate)
    monkeypatch.setattr(fl, "combined_plan_payload", lambda cloud, doc, root, step_ids=None: {
        "step_ids": step_ids or [step["id"] for step in doc["deployment"]["steps"]], "properties": {}})
    original = cloud.request
    cloud.raw_grant_kind, cloud.what_if_count, cloud.ignore_on = kind, 0, None
    cloud.ignored_network = False
    if kind == "Ignore":
        prerequisites = tuple(document["deployment"]["foundry_lifecycle"]["phases"][0]["step_ids"])
        cloud.expanded[prerequisites].remove(cloud.network_grant)

    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        if method != "POST" or "/whatIf?" not in url:
            return original(method, url, audience, data, headers, allowed)
        cloud.what_if_count += 1
        identifiers = [identifier for ids, values in cloud.expanded.items()
                       if set(ids) <= set(data["step_ids"]) for identifier in values]
        changes = []
        for identifier in identifiers:
            if identifier == cloud.network_grant:
                continue
            before, after = cloud.bodies.get(identifier), cloud.planned[identifier]
            change = "Create" if before is None else "NoChange" if before == after else "Modify"
            if cloud.ignored_network and identifier in document["deployment"]["foundry_lifecycle"]["network_scopes"]:
                change, after = "Ignore", None
            changes.append({"resourceId": identifier, "changeType": change,
                            "before": copy.deepcopy(before), "after": copy.deepcopy(after)})
        grant_kind = ("Ignore" if cloud.what_if_count == cloud.ignore_on else cloud.raw_grant_kind)
        body = copy.deepcopy(cloud.bodies[cloud.network_grant])
        changes.append({"resourceId": cloud.network_grant, "changeType": grant_kind,
                        "before": body, "after": None if after_none else copy.deepcopy(body)})
        return 200, {}, {"properties": {"changes": changes}}

    cloud.request = request
    document["deployment"]["changes"] = fl.evaluate_what_if(
        cloud, document, {"id": "factory", "scope": "subscription"},
        fl.combined_plan_payload(cloud, document, ROOT))
    cloud.what_if_count = 0
    return document, cloud


@pytest.mark.parametrize("after_none", [False, True])
def test_real_ignored_preserved_grant_is_not_a_source_declaration(monkeypatch, after_none):
    document, cloud = real_preserved_grant_case(monkeypatch, kind="Ignore", after_none=after_none)
    normalized = next(row for row in document["deployment"]["changes"]
                      if row["resource_id"] == cloud.network_grant)
    assert normalized["change_type"] == "NoChange"
    with pytest.raises(fl.Blocked, match="native-foundry-reviewed-network-grants-required"):
        fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    assert cloud.executed == [] and cloud.grant_writes == [] and cloud.source_grant_writes == []
    assert ACCOUNT not in cloud.bodies


@pytest.mark.parametrize("after_none", [False, True])
def test_real_source_nochange_grant_retains_declaration_provenance(monkeypatch, after_none):
    document, cloud = real_preserved_grant_case(monkeypatch, after_none=after_none)
    before = copy.deepcopy(cloud.bodies[cloud.network_grant])
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    data = document["deployment"]["foundry_lifecycle"]
    assert data["phases"][0]["source_changes"][cloud.network_grant] == "NoChange"
    assert [row["id"] for row in data["agent_identity"]["candidate_grants"]] == [cloud.network_grant]
    fl.validate_foundry_lifecycle(document)
    assert cloud.bodies[cloud.network_grant] == before
    assert cloud.executed == [] and cloud.grant_writes == []


def test_real_ignored_network_preservation_does_not_hide_genuine_source_grant(monkeypatch):
    document, cloud = real_preserved_grant_case(monkeypatch)
    cloud.ignored_network = True
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    data = document["deployment"]["foundry_lifecycle"]
    assert data["phases"][0]["source_changes"][data["network_scopes"][0]] == "Ignore"
    assert data["phases"][0]["source_changes"][cloud.network_grant] == "NoChange"
    fl.validate_foundry_lifecycle(document)
    assert cloud.executed == [] and cloud.grant_writes == []


@pytest.mark.parametrize("when", ["initial-previews", "before-prerequisite-put"])
def test_real_ignored_grant_drift_stops_before_any_phase_put(monkeypatch, when):
    document, cloud = real_preserved_grant_case(monkeypatch)
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    cloud.what_if_count = 0
    if when == "initial-previews":
        cloud.raw_grant_kind = "Ignore"
    else:
        cloud.ignore_on = 4
    seal(document)
    closure, bodies = native_closure(cloud, document["locks"]["scopes"])
    receipt = {"deployments": [], "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
               "status": "running", "foundry_initial_observations": fl.foundry_inventory_observations(document, closure, bodies)}
    with pytest.raises(fl.Blocked, match="native-foundry-reviewed-network-grants-required"):
        fl.run_foundry_phases(cloud, Mock(spec=["assert_held", "authorize"]), document, ROOT,
                             receipt, Mock(), Mock())
    assert cloud.executed == [] and cloud.grant_writes == [] and cloud.source_grant_writes == []
    assert ACCOUNT not in cloud.bodies


@pytest.mark.parametrize("provenance", ["Ignore", "missing"])
def test_frozen_source_grant_requires_retained_nonignored_provenance(monkeypatch, provenance):
    document, cloud = real_preserved_grant_case(monkeypatch)
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    phase = document["deployment"]["foundry_lifecycle"]["phases"][0]
    if provenance == "missing":
        phase.pop("source_changes", None)
    else:
        phase.setdefault("source_changes", {})[cloud.network_grant] = "Ignore"
    with pytest.raises(fl.Blocked, match="native-foundry-"):
        fl.validate_foundry_lifecycle(document)


def test_unrelated_bootstrap_grant_name_does_not_become_an_additional_source_candidate(monkeypatch):
    document, cloud, _ = preserved_network_case(monkeypatch, grant_exists=True)
    other = cloud.network_grant.rsplit("/", 1)[0] + "/ffffffff-ffff-ffff-ffff-ffffffffffff"
    cloud.bodies[other] = {**copy.deepcopy(cloud.bodies[cloud.network_grant]), "id": other}
    original = document["deployment"]["bootstrap_foundation"]["resources"][cloud.network_grant]
    document["deployment"]["bootstrap_foundation"]["resources"][other] = {
        **copy.deepcopy(original), "body_hash": fl.digest(cloud.bodies[other])}
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    candidates = document["deployment"]["foundry_lifecycle"]["agent_identity"]["candidate_grants"]
    assert [candidate["id"] for candidate in candidates] == [cloud.network_grant]
    assert cloud.executed == [] and cloud.grant_writes == []


def test_resealed_grant_name_cannot_leave_the_frozen_source_phase(monkeypatch):
    document, cloud, _ = native_worker(monkeypatch)
    candidate = document["deployment"]["foundry_lifecycle"]["agent_identity"]["candidate_grants"][0]
    candidate["id"] = cloud.network_grant.rsplit("/", 1)[0] + "/ffffffff-ffff-ffff-ffff-ffffffffffff"
    candidate["intent"]["id"] = candidate["id"]
    with pytest.raises(fl.Blocked, match="native-foundry-reviewed-network-grants-required"):
        fl.validate_foundry_agent_binding(document)


def test_preserved_network_uses_existing_source_uami_grant_without_extra_sami_writes(monkeypatch):
    document, cloud, protected = preserved_network_case(monkeypatch, grant_exists=True)
    before = {key: copy.deepcopy(cloud.bodies[key]) for key in protected}
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    assert cloud.grant_writes == []
    assert {key: cloud.bodies[key] for key in protected} == before
    assert not any("/roleassignments/" in key and key not in before for key in cloud.bodies)


def test_expired_review_cannot_admit_a_new_native_claim(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch, claim=False)
    monkeypatch.setattr(fl.time, "time", lambda: fl.timestamp(document["expires_at"]) + 1)
    with pytest.raises(fl.Blocked, match="manifest-expired-or-invalid-lifetime"):
        locks.claim_run()
    assert cloud.executed == [] and cloud.grant_writes == []


def test_already_accepted_claim_can_finish_after_review_admission_deadline(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch, injected=False)
    monkeypatch.setattr(fl.time, "time", lambda: fl.timestamp(document["expires_at"]) + 1)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    assert len(cloud.executed) == 3 and cloud.grant_writes == []


def test_missing_preobserved_uami_blocks_account_without_materialization_retry(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch)
    original_request, unavailable = cloud.request, []
    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        result = original_request(method, url, audience, data, headers, allowed)
        if method == "GET" and urlsplit(url).path.lower() == UAMI and cloud.executed:
            unavailable.append(url)
            return 404, {}, {}
        return result
    cloud.request = request
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "native-foundry-phase-instance-changed"
    assert len(unavailable) == 1 and len(cloud.executed) == 1
    assert ACCOUNT not in cloud.bodies and cloud.grant_writes == []


def test_wrong_foundation_output_cannot_authorize_account_creation(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch)
    original_request = cloud.request
    producer = next(step for step in document["deployment"]["steps"] if step["template"] == fl.FOUNDRY_FOUNDATION)
    endpoint = urlsplit(fl.deployment_endpoint(document, producer)).path.lower()
    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        status, response_headers, body = original_request(method, url, audience, data, headers, allowed)
        if method == "GET" and urlsplit(url).path.lower() == endpoint:
            body["properties"]["outputs"]["foundationOutputs"]["value"]["miProjectName"] = "another-uami"
        return status, response_headers, body
    cloud.request = request
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["error_code"] == "native-foundry-agent-producer-output-mismatch"
    assert len(cloud.executed) == 1 and ACCOUNT not in cloud.bodies


@pytest.mark.parametrize("field,value", [
    ("principalId", "00000000-0000-0000-0000-000000000000"),
    ("clientId", UAMI_PRINCIPAL), ("clientId", None), ("provisioningState", "Creating"),
])
def test_uami_metadata_does_not_fabricate_materialization(field, value):
    document = foundry_document()
    body = {"properties": {"principalId": UAMI_PRINCIPAL, "clientId": UAMI_CLIENT,
                           "tenantId": document["target"]["tenant_id"], field: value}}
    with pytest.raises(fl.Blocked, match="native-foundry-agent"):
        fl.foundry_uami_metadata(document, body)


@pytest.mark.parametrize("field,value", [
    ("condition", "unreviewed-condition"), ("scope", GROUP + "/providers/Microsoft.Network/virtualNetworks/other"),
    ("principalId", "00000000-0000-0000-0000-000000000000"),
    ("roleDefinitionId", "/providers/Microsoft.Authorization/roleDefinitions/not-reviewed"),
])
def test_invalid_source_grant_is_rejected_while_freezing_without_writes(monkeypatch, field, value):
    saved = []
    def configure(document, cloud):
        saved.append(cloud)
        cloud.planned[cloud.network_grant]["properties"][field] = value
    with pytest.raises(fl.Blocked, match="native-foundry-reviewed-network-grants-required"):
        native_worker(monkeypatch, configure=configure)
    assert saved[0].executed == [] and saved[0].grant_writes == [] and saved[0].source_grant_writes == []


def test_unresolved_future_role_id_is_not_accepted_as_a_frozen_resource(monkeypatch):
    saved = []
    def configure(document, cloud):
        saved.append(cloud)
        role = cloud.network_grant
        unresolved = role.rsplit("/", 1)[0] + "/[guid(reference('future-uami').principalId)]"
        cloud.planned[unresolved] = cloud.planned.pop(role)
        cloud.planned[unresolved]["id"] = unresolved
        for ids in cloud.expanded.values():
            if role in ids:
                ids[ids.index(role)] = unresolved
    with pytest.raises(fl.Blocked, match="native-foundry-unresolved-preview-resource"):
        native_worker(monkeypatch, configure=configure)
    assert saved[0].executed == [] and saved[0].source_grant_writes == []


def test_synthetic_planned_uami_postconditions_do_not_advertise_cold_start_feasibility(monkeypatch):
    declared_roles = []
    def configure(document, cloud):
        cloud.bodies.pop(UAMI)
        prerequisites = tuple(document["deployment"]["foundry_lifecycle"]["phases"][0]["step_ids"])
        cloud.expanded[prerequisites].append(UAMI)
        definition = GROUP.lower() + "/providers/microsoft.authorization/roledefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
        role = GROUP.lower() + "/providers/microsoft.authorization/roleassignments/" + str(
            uuid.uuid5(BICEP_GUID_NAMESPACE, UAMI + "-" + definition))
        cloud.planned[role] = {
            "id": role, "type": "Microsoft.Authorization/roleAssignments", "etag": '"observed"',
            "properties": {"roleDefinitionId": definition, "principalId": UAMI_PRINCIPAL,
                           "principalType": "ServicePrincipal"}}
        cloud.expanded[prerequisites].append(role)
        declared_roles.append(role)
        cloud.intents[UAMI] = {**cloud.planned[UAMI], "properties": {}}
        cloud.intents[ACCOUNT] = copy.deepcopy(cloud.planned[ACCOUNT])
        cloud.intents[ACCOUNT]["identity"]["userAssignedIdentities"][UAMI] = {}
    # The fake provider supplies a concrete role ID; this does not establish that
    # Azure what-if resolves a name derived from a not-yet-created principal.
    with pytest.raises(fl.Blocked, match="native-foundry-agent-producer-required"):
        native_worker(monkeypatch, configure=configure)


@pytest.mark.parametrize("defect", ["account-uami", "account-subnet", "uami-client"])
def test_account_phase_rechecks_actual_uami_and_injection_before_full(monkeypatch, defect):
    document, cloud, locks = native_worker(monkeypatch)
    original_request = cloud.request
    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        status, response_headers, body = original_request(method, url, audience, data, headers, allowed)
        if method == "PUT" and len(cloud.executed) == 2:
            if defect == "account-uami":
                cloud.bodies[ACCOUNT]["identity"]["userAssignedIdentities"] = {UAMI + "-other": {}}
            elif defect == "account-subnet":
                cloud.bodies[ACCOUNT]["properties"]["networkInjections"][0]["subnetArmId"] += "-other"
            elif defect == "uami-client":
                cloud.bodies[UAMI]["properties"]["clientId"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        return status, response_headers, body
    cloud.request = request
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required", result
    assert result["error_code"] in (
        "native-foundry-account-agent-identity-mismatch", "foundry-account-network-injection-mismatch",
        "native-foundry-agent-identity-changed")
    assert len(cloud.executed) == 2 and cloud.grant_writes == []
    assert cloud.model not in cloud.bodies


def test_exact_injected_service_readiness_allows_full_without_claiming_effective_access(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch)
    envelope = {"manifest": document, "lease_context": locks.held}
    result = fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    assert result["foundry_readiness"]["status"] == "provider-ready"
    assert result["foundry_agent_readiness"]["effective_permissions_proven"] is False
    host = result["foundry_readiness"]["capability_host"]
    assert host["general_effective_permissions_proven"] is False
    assert host["configured_identity_id"] == UAMI
    assert host["configured_principal_id"] == UAMI_PRINCIPAL
    assert result["foundry_readiness"]["completed_gates"] == [
        "account-identity", "configured-agent-network-ready"]
    assert "pending_foundry_gate" not in result
    assert len(cloud.executed) == 3 and cloud.model in cloud.bodies
    full = fl.deployment_endpoint(document, {"id": "foundry-project-phase", "scope": "subscription"})
    put = cloud.events.index(("PUT", urlsplit(full).path.lower()))
    assert ("GET", host["id"].lower()) in cloud.events[:put]
    assert fl.verify_worker_receipt(locks, document) == result


def test_cold_uami_advertises_only_the_separate_identity_receipt_contract():
    assert fl.capabilities()["native_foundry"] == fl.FOUNDRY_CONTRACT
    assert fl.capabilities()["native_foundry_identity_producer"] == fl.FOUNDRY_IDENTITY_CONTRACT
    assert fl.capabilities().get("native_foundry_blocker") is None


def test_missing_observation_limitation_rejects_malformed_readiness_receipt(monkeypatch):
    document, cloud, locks = native_worker(monkeypatch)
    original = fl.foundry_readiness
    def without_effective_field(cloud, locks, document, receipt, persist, account_result, sleep):
        original(cloud, locks, document, receipt, persist, account_result, sleep)
        receipt["foundry_agent_readiness"].pop("effective_permissions_proven")
        persist()
    monkeypatch.setattr(fl, "foundry_readiness", without_effective_field)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "native-foundry-agent-receipt-incomplete"
    full = fl.deployment_endpoint(document, {"id": "foundry-project-phase", "scope": "subscription"})
    assert ("PUT", urlsplit(full).path.lower()) not in cloud.events
    assert len(cloud.executed) == 2 and cloud.model not in cloud.bodies and cloud.leases
    with pytest.raises(fl.Blocked):
        fl.verify_foundry_readiness_receipt(document, result)


@pytest.mark.parametrize("forgery", [
    "phase-success", "phase-success-missing", "effective-boolean", "missing-effective", "completed-gate"])
def test_receipt_consumers_reject_overstated_or_incomplete_service_readiness(monkeypatch, forgery):
    document, cloud, locks = native_worker(monkeypatch)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result
    fl.verify_foundry_provider_readiness_receipt(document, result)
    if forgery == "effective-boolean":
        result["foundry_agent_readiness"]["effective_permissions_proven"] = True
    elif forgery == "missing-effective":
        result["foundry_agent_readiness"].pop("effective_permissions_proven")
    elif forgery == "completed-gate":
        result["foundry_readiness"]["completed_gates"].append("actor-effective-rbac")
        result["foundry_readiness"]["status"] = "succeeded"
    else:
        if forgery == "phase-success-missing":
            result.pop("foundry_readiness")
        else:
            result["foundry_readiness"].pop("capability_host")
    with pytest.raises(fl.Blocked):
        if forgery.startswith("phase-success"):
            fl.verify_foundry_receipt(document, result)
        else:
            fl.verify_foundry_readiness_receipt(document, result)
    assert len(cloud.executed) == 3 and cloud.model in cloud.bodies


@pytest.mark.parametrize("defect", ["host", "configured-principal", "account-resource", "agent-grants"])
def test_incomplete_exact_service_readiness_blocks_full_put_and_replay(monkeypatch, defect):
    document, cloud, locks = native_worker(monkeypatch)
    original = fl.foundry_readiness
    def incomplete(cloud, locks, document, receipt, persist, account_result, sleep):
        original(cloud, locks, document, receipt, persist, account_result, sleep)
        proof = receipt["foundry_readiness"]
        if defect == "host":
            proof.pop("capability_host")
        elif defect == "configured-principal":
            proof["capability_host"]["configured_principal_id"] = PRINCIPAL
        elif defect == "account-resource":
            proof["account_resource_id"] += "-other"
        else:
            receipt["foundry_agent_readiness"]["grants"] = []
        persist()
    monkeypatch.setattr(fl, "foundry_readiness", incomplete)
    envelope = {"manifest": document, "lease_context": locks.held}
    result = fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == {
        "host": "native-foundry-capability-host-receipt-incomplete",
        "configured-principal": "native-foundry-capability-host-receipt-incomplete",
        "account-resource": "native-foundry-readiness-receipt-incomplete",
        "agent-grants": "native-foundry-agent-receipt-incomplete"}[defect]
    full = fl.deployment_endpoint(document, {"id": "foundry-project-phase", "scope": "subscription"})
    assert ("PUT", urlsplit(full).path.lower()) not in cloud.events
    assert len(cloud.executed) == 2 and cloud.model not in cloud.bodies and cloud.leases
    with pytest.raises(fl.Blocked):
        fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert len(cloud.executed) == 2


@pytest.mark.parametrize("defect", ["initial-host-id", "late-host-id", "late-host-state", "late-host-body"])
def test_host_must_remain_exact_and_ready_until_full_put(monkeypatch, defect):
    document, cloud, locks = native_worker(monkeypatch)
    original = cloud.request
    host_reads = []
    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        status, response_headers, body = original(method, url, audience, data, headers, allowed)
        if method == "GET" and "/capabilityhosts/" in url.lower():
            host_reads.append(url)
            if defect == "initial-host-id" or defect == "late-host-id" and len(host_reads) > 1:
                body["id"] += "-other"
            elif defect == "late-host-state" and len(host_reads) > 1:
                body["properties"]["provisioningState"] = "Failed"
            elif defect == "late-host-body" and len(host_reads) > 1:
                body["etag"] = '"changed"'
        return status, response_headers, body
    cloud.request = request
    envelope = {"manifest": document, "lease_context": locks.held}
    result = fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "reconciliation-required", result
    assert result["error_code"] == {
        "initial-host-id": "foundry-resource-identity-mismatch",
        "late-host-id": "native-foundry-phase-instance-changed",
        "late-host-state": "native-foundry-phase-instance-changed",
        "late-host-body": "native-foundry-phase-instance-changed"}[defect]
    assert len(host_reads) == (1 if defect == "initial-host-id" else 2)
    full = fl.deployment_endpoint(document, {"id": "foundry-project-phase", "scope": "subscription"})
    assert ("PUT", urlsplit(full).path.lower()) not in cloud.events
    assert len(cloud.executed) == 2 and cloud.model not in cloud.bodies and cloud.leases
    with pytest.raises(fl.Blocked):
        fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert len(cloud.executed) == 2


def offline_github_transport(cloud, source_root, *, expected_worker_status="succeeded"):
    secrets, commands = {}, []
    document = cloud.document
    template = (source_root / fl.scoped_template(document)).read_text()
    def command(argv, **kwargs):
        commands.append(argv)
        if argv[:2] == ["git", "show"]:
            return template.strip()
        if argv[:3] == ["gh", "api", "user"]:
            return json.dumps({"id": document["route"]["github_user_id"]})
        if argv[:3] == ["gh", "secret", "set"]:
            secrets[argv[3]] = kwargs["data"]
            return ""
        if argv[:3] == ["gh", "secret", "delete"]:
            del secrets[argv[3]]
            return ""
        assert argv[:3] == ["gh", "api", "--method"], argv
        method, endpoint = argv[3:5]
        if "/contents/" in endpoint:
            return json.dumps({"encoding": "base64", "content": base64.b64encode(template.encode()).decode()})
        if "/git/trees/" in endpoint:
            return json.dumps({"tree": [{"path": "azure-enterprise-scale-ml", "mode": "160000",
                                         "sha": document["source"]["commit"]}]})
        if endpoint.endswith("/dispatches"):
            inputs = json.loads(kwargs["data"])["inputs"]
            raw = "".join(secrets[inputs["secret_prefix"] + "_" + str(index)]
                          for index in range(int(inputs["secret_chunks"])))
            envelope = json.loads(zlib.decompress(base64.b64decode(raw)))
            result = fl.run_deployment_worker(envelope, source_root, inputs["run_id"],
                                              inputs["manifest_hash"], cloud, Mock())
            assert result["status"] == expected_worker_status, result.get("error_code")
        if "/runs?event=" in endpoint:
            return json.dumps({"workflow_runs": [{"id": 1, "head_sha": document["route"]["commit"],
                                                  "display_title": "factory-lifecycle [" + document["run_id"] + "]"}]})
        if endpoint.endswith("/actions/runs/1"):
            return json.dumps({"status": "completed", "conclusion": "success", "head_sha": document["route"]["commit"]})
        if "/git/ref/tags/" in endpoint:
            return json.dumps({"object": {"sha": document["route"]["commit"]}})
        assert method in ("POST", "DELETE"), argv
        return "{}"
    cloud.command = command
    return commands


def test_identity_stage_accepts_a_tags_only_update_of_the_owned_existing_group(monkeypatch):
    """aif-138 (2026-10-29): the prerequisites create the project group with the ownership tags; the producer's
    what-if then reports the group as Modify (tagsProject adds tags) and the review blocked every PROJECT stage."""
    document, cloud, locks = prepare_identity_worker(monkeypatch, "group-tags")
    stage = document["deployment"]["foundry_identity_stage"]
    assert stage["group_tags_updated"] is True and stage["group_tags_after"] == cloud.group_after["tags"]
    assert stage["group_tags_before"] == cloud.group["tags"]
    group_row = next(row for row in stage["changes"] if row["resource_id"] == GROUP.lower())
    assert group_row["change_type"] == "Modify" and stage["source_changes"][GROUP.lower()] == "Modify"
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    assert len(cloud.arm_writes) == 1 and cloud.bodies[GROUP.lower()]["tags"]["CostCenter"] == "reviewed-cost-center"
    assert receipt["resource_groups"][0]["body_hash"] == fl.digest(cloud.group_after)
    fl.verify_worker_receipt(locks, document)


def test_identity_preview_refuses_a_change_of_the_group_beyond_its_tags(monkeypatch):
    with pytest.raises(fl.Blocked, match="^native-foundry-identity-preview-footprint-invalid$"):
        prepare_identity_worker(monkeypatch, "group-modify")


def test_identity_stage_without_a_tag_update_records_none(monkeypatch):
    document, _, _ = prepare_identity_worker(monkeypatch)
    stage = document["deployment"]["foundry_identity_stage"]
    assert stage["group_tags_updated"] is False and "group_tags_after" not in stage


def test_identity_preview_footprint_refusal_names_the_what_if_rows(monkeypatch):
    with pytest.raises(fl.Blocked) as raised:
        prepare_identity_worker(monkeypatch, "group-modify")
    assert raised.value.code == "native-foundry-identity-preview-footprint-invalid"
    assert raised.value.error_diagnostic == {"resource_changes": {GROUP.lower(): "Modify", UAMI: "Create"},
                                             "tag_updates": []}


def test_identity_continuation_accepts_the_receipt_from_a_carried_published_ancestor(monkeypatch):
    """aif-138 (2026-10-29): the identity was produced on one published commit; the continuation reviewed on a
    published fast-forward that carries that commit as a consent ancestor keeps the receipt's binding."""
    document, cloud, _, receipt = completed_identity(monkeypatch)
    produced = document["source"]["commit"]
    document["source"]["commit"] = "c" * 40
    document["deployment"].setdefault("bootstrap_foundation", {})["consent_ancestors"] = [produced]
    known = document["deployment"]["known_ownership"]
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    fl.verify_foundry_identity_receipt(document, receipt, continuation=True)
    # A commit the plan does not carry as an ancestor is drift: a warning, the live identity decides (Joakim, 2026-10-30).
    document["deployment"]["bootstrap_foundation"]["consent_ancestors"] = ["d" * 40]
    record = fl.verify_foundry_identity_receipt(document, receipt, continuation=True, cloud=cloud)
    assert set(record["drift"]) <= {"request_hash", "binding_hash"} and record["drift"]
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    with pytest.raises(fl.Blocked, match="stale-or-replayed"):
        fl.verify_foundry_identity_receipt(document, receipt, continuation=True)


def test_identity_preview_without_an_identity_row_names_the_rows_it_did_list(monkeypatch):
    with pytest.raises(fl.Blocked) as raised:
        prepare_identity_worker(monkeypatch, "no-identity")
    assert raised.value.code == "native-foundry-identity-source-preview-incomplete"
    assert raised.value.error_diagnostic == {"resource_changes": {GROUP.lower(): "Create"}, "tag_updates": []}


def aged(document, receipt):
    """The review is prepared past the receipt's freshness window (aif-138, 2026-10-30: the identity was produced
    the day before the continuation could run)."""
    observed = datetime.fromisoformat(receipt["foundry_identity_receipt"]["observed_at"])
    lifetime = (datetime.fromisoformat(document["expires_at"]) - datetime.fromisoformat(document["prepared_at"])
                if "expires_at" in document else None)
    prepared = observed + timedelta(seconds=fl.RECEIPT_OBSERVATION_AGE_SECONDS + 3600)
    document["prepared_at"] = prepared.isoformat()
    if lifetime is not None:
        document["expires_at"] = (prepared + lifetime).isoformat()


def test_stale_receipt_with_the_same_live_identity_is_revalidated_not_refused(monkeypatch):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    aged(document, receipt)
    known = document["deployment"]["known_ownership"]
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    revalidation = document["deployment"]["foundry_identity_continuation"]["revalidation"]
    assert revalidation["receipt_observed_at"] == receipt["foundry_identity_receipt"]["observed_at"]
    assert revalidation["compared"] == ["resource_id", "principal_id", "client_id", "tenant_id", "resource_group",
                                        "identity_body", "resource_group_tags"]
    fl.verify_foundry_identity_receipt(document, receipt, continuation=True, cloud=cloud)
    fl.validate_foundry_identity_continuation(document)
    # The next review of the same plan reproduces the same record, so confirmation sees an unchanged plan.
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False


def test_fresh_receipt_records_no_revalidation(monkeypatch):
    document, cloud, _, _ = completed_identity(monkeypatch)
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    assert "revalidation" not in document["deployment"]["foundry_identity_continuation"]


@pytest.mark.parametrize("defect,field", [("principal", "principal_id"), ("client", "client_id"),
                                           ("tenant", "tenant_id"), ("missing", "resource_id"),
                                           ("body", "identity_body"), ("group-missing", "resource_group")])
def test_stale_receipt_with_a_different_or_missing_live_identity_refuses_naming_the_field(monkeypatch, defect, field):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    aged(document, receipt)
    known = document["deployment"]["known_ownership"]
    if defect == "principal":
        cloud.bodies[UAMI]["properties"]["principalId"] = str(uuid.uuid4())
    elif defect == "client":
        cloud.bodies[UAMI]["properties"]["clientId"] = str(uuid.uuid4())
    elif defect == "tenant":
        cloud.bodies[UAMI]["properties"]["tenantId"] = str(uuid.uuid4())
    elif defect == "missing":
        cloud.bodies.pop(UAMI)
    elif defect == "body":
        cloud.bodies[UAMI]["etag"] = '"changed"'
    else:
        cloud.bodies.pop(GROUP.lower())
    with pytest.raises(fl.Blocked) as raised:
        fl.foundry_identity_preparation(cloud, document, known)
    assert raised.value.code == "native-foundry-identity-revalidation-mismatch-" + field.replace("_", "-")
    with pytest.raises(fl.Blocked) as raised:
        fl.verify_foundry_identity_receipt(document, receipt, continuation=True, cloud=cloud)
    assert raised.value.code == "native-foundry-identity-revalidation-mismatch-" + field.replace("_", "-")


def test_stale_receipt_cannot_be_verified_without_a_live_cloud(monkeypatch):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    aged(document, receipt)
    with pytest.raises(fl.Blocked, match="^native-foundry-identity-receipt-stale-or-replayed$"):
        fl.verify_foundry_identity_receipt(document, receipt, continuation=True)


def test_stale_receipt_with_changed_group_tags_refuses_naming_the_tags(monkeypatch):
    document, cloud, locks = prepare_identity_worker(monkeypatch, "group-tags")
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    following = copy.deepcopy(document)
    following["run_id"] = str(uuid.uuid4())
    following["deployment"].pop("foundry_identity_stage")
    following["deployment"].setdefault("known_ownership", {})[UAMI] = {
        "run_id": receipt["run_id"], "receipt_hash": fl.digest(receipt)}
    aged(following, receipt)
    assert fl.freeze_foundry_identity_stage(cloud, following, ROOT) is False
    cloud.bodies[GROUP.lower()]["tags"]["CostCenter"] = "someone-else"
    with pytest.raises(fl.Blocked) as raised:
        fl.verify_foundry_identity_receipt(following, receipt, continuation=True, cloud=cloud)
    assert raised.value.code == "native-foundry-identity-revalidation-mismatch-resource-group-tags"


def repinned_identity(monkeypatch):
    """aif-138 (2026-10-30): the consumer was repinned between the identity producer and its continuation, so the
    review's route carries another consumer commit than the producer's request did."""
    document, cloud, _, receipt = completed_identity(monkeypatch)
    produced = document["route"]["commit"]
    document["route"]["commit"] = "e" * 40
    return document, cloud, receipt, document["deployment"]["known_ownership"], produced


def test_repinned_consumer_without_the_producers_route_commit_is_recovered_with_a_drift_warning(monkeypatch):
    document, cloud, receipt, known, _ = repinned_identity(monkeypatch)
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    assert document["deployment"]["foundry_identity_continuation"]["revalidation"]["drift"]


def test_repinned_consumer_keeps_the_receipt_when_its_hash_proves_the_producers_route_commit(monkeypatch):
    document, cloud, receipt, known, produced = repinned_identity(monkeypatch)
    known[UAMI]["route_commit"] = produced
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    assert document["deployment"]["foundry_identity_continuation"]["producer"] == {"route_commit": produced}
    fl.validate_foundry_identity_continuation(document)
    fl.verify_foundry_identity_receipt(document, receipt, continuation=True, route_commit=produced)
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False


@pytest.mark.parametrize("claimed", ["f" * 40, "not-a-commit", 7])
def test_a_route_commit_the_receipt_does_not_prove_is_only_drift(monkeypatch, claimed):
    document, cloud, receipt, known, _ = repinned_identity(monkeypatch)
    known[UAMI]["route_commit"] = claimed
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    assert document["deployment"]["foundry_identity_continuation"]["revalidation"]["drift"]


def test_the_recorded_producer_route_commit_cannot_be_swapped_after_review(monkeypatch):
    document, cloud, receipt, known, produced = repinned_identity(monkeypatch)
    known[UAMI]["route_commit"] = produced
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    document["deployment"]["foundry_identity_continuation"]["producer"] = {"route_commit": "f" * 40}
    with pytest.raises(fl.Blocked):
        fl.validate_foundry_identity_continuation(document)


def test_existing_producer_identity_may_preview_as_modify_when_its_receipt_binds_it(monkeypatch):
    """aif-138, 2026-10-30: the continuation re-previews the producer's projection with this review's tags, so the
    identity the receipt already proves can show as Modify; the continuation never applies that projection."""
    document, cloud, _, receipt = completed_identity(monkeypatch)
    cloud.failure = "identity-modify"
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    assert document["deployment"]["foundry_identity_continuation"]["run_id"] == receipt["run_id"]
    assert len(cloud.arm_writes) == 1


def test_modify_of_an_identity_without_a_binding_receipt_is_still_refused(monkeypatch):
    document, cloud, _, _ = completed_identity(monkeypatch)
    cloud.failure = "identity-modify"
    document["deployment"]["known_ownership"].pop(UAMI)
    with pytest.raises(fl.Blocked):
        fl.freeze_foundry_identity_stage(cloud, document, ROOT)


def test_repinned_identity_continuation_runs_the_whole_worker(monkeypatch):
    """aif-138, 2026-10-30: the consumer was repinned after the producer; the continuation still deploys with the
    producer's identity (the planned templates, the what-if and the dispatch check all bind to the producer's request)."""
    document, cloud, locks, producer = continued_native_worker(monkeypatch, repinned=True)
    continuation = document["deployment"]["foundry_identity_continuation"]
    assert continuation["producer"] == {"route_commit": "b" * 40} and "revalidation" not in continuation
    locks.claim_run()
    receipt = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert receipt["status"] == "succeeded", json.dumps(receipt)
    assert receipt["foundry_identity_continuation"]["run_id"] == producer["run_id"]
    fl.verify_worker_receipt(locks, document)


def producer_with_secret_expiry(monkeypatch):
    """Pink freezes keyVaultSecretExpiry as one year after the review time (accelerator 1c7941ad), so the continuation's
    step parameter differs from the producer's: give the producer's binding the parameter its own review time implies."""
    document, cloud, _, receipt = completed_identity(monkeypatch)
    step = document["deployment"]["steps"][1]
    produced = receipt["foundry_identity_receipt"]["producer_prepared_at"]
    step["parameters"]["keyVaultSecretExpiry"] = fl.secret_expiry_after(produced)
    receipt["foundry_identity_receipt"]["binding_hash"] = fl.foundry_identity_context(document)
    cloud.runs["runs/" + receipt["run_id"] + ".worker.json"] = copy.deepcopy(receipt)
    document["deployment"]["known_ownership"][UAMI]["receipt_hash"] = fl.digest(receipt)
    step["parameters"]["keyVaultSecretExpiry"] = fl.secret_expiry_after(document["prepared_at"])
    return document, cloud, receipt, step


def test_secret_expiry_is_one_year_after_the_review_time():
    assert fl.secret_expiry_after("2026-10-29T09:43:11.776265+00:00") == int(
        datetime.fromisoformat("2027-10-29T09:43:11+00:00").timestamp())
    assert fl.secret_expiry_after("2028-02-29T00:00:00+00:00") == int(
        datetime.fromisoformat("2029-02-28T00:00:00+00:00").timestamp())
    assert fl.secret_expiry_after("not a time") is None


def test_continuation_binds_to_the_producers_secret_expiry_not_its_own_review_time(monkeypatch):
    """aif-138, 2026-10-30: the continuation's keyVaultSecretExpiry is one year after its own review time; the producer's
    receipt binds the one year after the producer's, which the receipt's producer_prepared_at proves."""
    document, cloud, receipt, step = producer_with_secret_expiry(monkeypatch)
    assert step["parameters"]["keyVaultSecretExpiry"] != fl.secret_expiry_after(
        receipt["foundry_identity_receipt"]["producer_prepared_at"])
    assert fl.foundry_identity_preparation(cloud, document, document["deployment"]["known_ownership"])["run_id"] == receipt["run_id"]
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    fl.validate_foundry_identity_continuation(document)
    fl.verify_foundry_identity_receipt(document, receipt, continuation=True)
    assert step["parameters"]["keyVaultSecretExpiry"] == fl.secret_expiry_after(document["prepared_at"])


def test_a_secret_expiry_that_is_neither_the_reviews_nor_the_producers_is_not_rebound(monkeypatch):
    document, cloud, receipt, step = producer_with_secret_expiry(monkeypatch)
    step["parameters"]["keyVaultSecretExpiry"] = 1893456000
    # Neither value: the receipt's hashes drift, which warns (Joakim, 2026-10-30), and the live identity decides.
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    assert document["deployment"]["foundry_identity_continuation"]["revalidation"]["drift"]


@pytest.mark.parametrize("change", ["config", "source", "route", "steps"])
def test_receipt_hash_drift_only_warns_and_the_live_identity_decides(monkeypatch, change):
    """aif-138, 2026-10-30 (Joakim: hash comparisons warn, they never block): whatever the hashes cover changes between
    the producer and its continuation (config, published commit, consumer pin, a step parameter such as the secret
    expiry); the identity is the same live resource, so the continuation records the drift and proceeds."""
    document, cloud, _, receipt = completed_identity(monkeypatch)
    if change == "config":
        document["config"]["extra"] = "different"
    elif change == "source":
        document["source"]["commit"] = "b" * 40
    elif change == "route":
        document["route"]["commit"] = "e" * 40
    else:
        document["deployment"]["steps"][1]["parameters"]["keyVaultSecretExpiry"] = 1893456000
    known = document["deployment"]["known_ownership"]
    assert fl.foundry_identity_preparation(cloud, document, known)["run_id"] == receipt["run_id"]
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    revalidation = document["deployment"]["foundry_identity_continuation"]["revalidation"]
    assert revalidation["drift"] and set(revalidation["drift"]) <= {"request_hash", "binding_hash"}
    fl.validate_foundry_identity_continuation(document)
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False


@pytest.mark.parametrize("defect", ["principal", "body", "tenant"])
def test_receipt_hash_drift_with_a_changed_live_identity_still_refuses(monkeypatch, defect):
    document, cloud, _, receipt = completed_identity(monkeypatch)
    document["config"]["extra"] = "different"
    if defect == "principal":
        cloud.bodies[UAMI]["properties"]["principalId"] = str(uuid.uuid4())
    elif defect == "body":
        cloud.bodies[UAMI]["etag"] = '"changed"'
    elif defect == "tenant":
        cloud.bodies[UAMI]["properties"]["tenantId"] = str(uuid.uuid4())
    else:
        cloud.bodies.pop(UAMI)
    with pytest.raises(fl.Blocked, match="revalidation-mismatch|receipt-instance-changed|agent-tenant"):
        fl.freeze_foundry_identity_stage(cloud, document, ROOT)


def test_the_recorded_drift_cannot_be_hidden_after_review(monkeypatch):
    document, cloud, _, _ = completed_identity(monkeypatch)
    document["config"]["extra"] = "different"
    assert fl.freeze_foundry_identity_stage(cloud, document, ROOT) is False
    document["deployment"]["foundry_identity_continuation"].pop("revalidation")
    with pytest.raises(fl.Blocked):
        fl.validate_foundry_identity_continuation(document)
