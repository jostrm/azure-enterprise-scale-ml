"""Selective deletion exercises the real collector/leases against disposable fakes."""

import copy
import itertools
import json
import types
from uuid import uuid4

import pytest

from .test_factory_lifecycle import (
    fl, FakeCloud, CORE_OWNER, OWNER, SUB, GROUP, COMMON, RESOURCE, manifest, seal,
    no_real_services, workspace,
)


PROJECT = "dddddddd-dddd-dddd-dddd-dddddddddddd"
VAULT = GROUP + "/providers/Microsoft.KeyVault/vaults/project-vault"
VNET = COMMON + "/providers/Microsoft.Network/virtualNetworks/common-vnet"
SUBNET = VNET + "/subnets/project-subnet"
SHARED_SUBNET = VNET + "/subnets/shared-subnet"
ENVIRONMENTS = [list(items) for count in (1, 2, 3) for items in itertools.combinations(("dev", "stage", "prod"), count)]


def tagged(identifier, kind, owner, properties=None):
    return {"id": identifier, "type": kind, "etag": '"original"',
            "tags": {fl.TAG_KEYS[key]: value for key, value in owner.items()},
            "properties": properties or {}}


class ProjectCloud(FakeCloud):
    def __init__(self):
        super().__init__()
        self.permissions = True
        self.before_delete = lambda identifier: None
        self.after_delete = lambda identifier: None
        self.bodies = {
            GROUP.lower(): tagged(GROUP, "Microsoft.Resources/resourceGroups", OWNER),
            RESOURCE.lower(): tagged(RESOURCE, "Microsoft.Network/publicIPAddresses", OWNER),
            VAULT.lower(): tagged(VAULT, "Microsoft.KeyVault/vaults", OWNER),
            COMMON.lower(): tagged(COMMON, "Microsoft.Resources/resourceGroups", CORE_OWNER),
            VNET.lower(): tagged(VNET, "Microsoft.Network/virtualNetworks", CORE_OWNER),
            SUBNET.lower(): tagged(SUBNET, "Microsoft.Network/virtualNetworks/subnets", OWNER),
            SHARED_SUBNET.lower(): tagged(SHARED_SUBNET, "Microsoft.Network/virtualNetworks/subnets", CORE_OWNER),
        }
        self.bodies[SHARED_SUBNET.lower()]["tags"]["aifactory.shared"] = "true"
        self.bodies[VNET.lower()]["properties"]["subnets"] = [
            copy.deepcopy(self.bodies[SUBNET.lower()]), copy.deepcopy(self.bodies[SHARED_SUBNET.lower()])]

    def provider_schema(self, namespace):
        types = (["publicIPAddresses", "virtualNetworks", "virtualNetworks/subnets",
                  "networkSecurityGroups", "networkSecurityGroups/securityRules"] if namespace.lower()
                 == "microsoft.network" else ["vaults"])
        return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2024-05-01"]} for kind in types]}

    def provider_operations(self, namespace):
        return [namespace.lower() + "/" + row["resourceType"].lower() + "/" + action
                for row in self.provider_schema(namespace)["resourceTypes"] for action in ("read", "write", "delete")]

    def list_resources(self, scope):
        return [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                if fl.arm_scope(key) == scope.lower() and "/providers/" in key
                and len(key.rsplit("/providers/", 1)[-1].split("/")) == 3]

    def collection(self, path, api_version, extension=False):
        if path.lower().endswith(("/subnets", "/securityrules")):
            return [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                    if key.startswith(path.lower() + "/")], None
        assert extension
        return [], None

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if "/permissions?" in url:
            assert method == "GET"
            return 200, {}, {"value": [{"actions": ["*"] if self.permissions else ["*/read"], "notActions": []}]}
        return super().request(method, url, audience, data, headers, allowed)

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method != "DELETE":
            return super().arm(method, resource_id, api_version, allowed, headers)
        self.before_delete(resource_id)
        fl.require(not self.fail_delete, "injected-delete-failure")
        assert "purge" not in resource_id.lower()
        key = resource_id.lower()
        self.deleted.append(resource_id)
        removed = {item for item in self.bodies if item == key or item.startswith(key + "/")}
        self.bodies = {item: body for item, body in self.bodies.items() if item not in removed}
        for body in self.bodies.values():
            if "subnets" in body.get("properties", {}):
                original = body["properties"]["subnets"]
                body["properties"]["subnets"] = [row for row in original if row["id"].lower() not in removed]
                if original != body["properties"]["subnets"]:
                    body["etag"] = '"after-reviewed-child-removal"'
        self.after_delete(resource_id)
        return 202, {}, None


def prepared(subnets=False, group=False, environments=None, environment="stage", cloud_class=ProjectCloud,
             scopes=(GROUP, COMMON)):
    cloud = cloud_class()
    document = manifest()
    document["target"]["environment"] = environment
    document["locks"]["scopes"] = list(scopes)
    document["locks"]["common_dependencies"] = []
    for scope in scopes:
        cloud.enrollment["scopes"][scope.lower()] = {
            **copy.deepcopy(cloud.enrollment["scopes"][GROUP.lower()]),
            "common_dependencies": [], "target": {key: document["target"][key] for key in (
                "factory_id", "scaleset_id", "environment", "tenant_id", "subscription_id", "prefix", "region", "suffix")}}
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    options = {"environments": environments or [environment], "include_project_subnets": subnets,
               "include_keyvault_and_resource_group": group}
    document["deletion_scope"] = {
        "kind": "project", "contract": fl.SELECTIVE_PROJECT_DELETE, "project_id": PROJECT, "project_number": "017",
        "options": options, "registered_resource_ids": [GROUP, COMMON, SUBNET]}
    document["reviewed_scope"] = {"factory_id": "factory-a", "scale_set_id": None, "project_id": PROJECT,
                                  "expected_revision": "e" * 64, "deletion_options": copy.deepcopy(options)}
    document["deletion"] = fl.freeze_project_deletion(cloud, document, {})
    return seal(document), cloud


@pytest.mark.parametrize("subnets,group", list(itertools.product((False, True), repeat=2)))
@pytest.mark.parametrize("environment", ("dev", "stage", "prod"))
def test_selective_policy_and_real_offline_execution(workspace, monkeypatch, environment, subnets, group):
    document, cloud = prepared(subnets, group, environment=environment)
    fl.validate_manifest(document)
    expected = {RESOURCE.lower()}
    if group:
        expected |= {GROUP.lower(), VAULT.lower()}
    if subnets:
        expected.add(SUBNET.lower())
    assert {row["id"].lower() for row in document["deletion"]["resource_groups"]
            + document["deletion"]["resources"] if row["delete"]} == expected
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert set(value.lower() for value in result["deleted_resources"]) == expected
    assert result["deletion_scope"] == document["deletion_scope"]
    assert json.loads((run / "receipt.json").read_text()) == result
    assert SHARED_SUBNET.lower() in cloud.bodies and VNET.lower() in cloud.bodies
    assert not cloud.leases
    if not subnets:
        assert SUBNET.lower() in cloud.bodies
    if not group:
        assert GROUP.lower() in cloud.bodies and VAULT.lower() in cloud.bodies
        assert not any(fl.RG_ID.fullmatch(identifier) for identifier in cloud.deleted)


@pytest.mark.parametrize("subnets,group", list(itertools.product((False, True), repeat=2)))
@pytest.mark.parametrize("envs", ENVIRONMENTS)
def test_all_environment_and_retention_combinations_are_bound(envs, subnets, group):
    for environment in envs:
        document, cloud = prepared(subnets, group, envs, environment)
        fl.validate_manifest(document)
        assert document["deletion_scope"]["options"]["environments"] == envs
        assert not cloud.deleted


@pytest.mark.parametrize("change", ("owner", "shared", "logical", "unknown", "ambiguous", "unregistered", "permission", "scope"))
def test_prepare_blocks_whole_plan_for_unverified_scope(change):
    document, cloud = prepared()
    if change == "owner":
        cloud.bodies[RESOURCE.lower()]["tags"]["aifactory.project_id"] = "999"
    elif change == "shared":
        cloud.bodies[RESOURCE.lower()]["tags"]["aifactory.shared"] = "true"
    elif change == "logical":
        cloud.bodies[RESOURCE.lower()]["tags"]["aifactory.logical_project_id"] = str(uuid4())
    elif change == "unknown":
        cloud.bodies[RESOURCE.lower()]["tags"] = {}
    elif change == "ambiguous":
        cloud.bodies[COMMON.lower()]["tags"] = copy.deepcopy(cloud.bodies[GROUP.lower()]["tags"])
    elif change == "unregistered":
        document["deletion_scope"]["registered_resource_ids"] = [COMMON]
    elif change == "permission":
        cloud.permissions = False
    else:
        cloud.enrollment["scopes"][GROUP.lower()]["allow_delete"] = False
        document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    with pytest.raises(fl.Blocked):
        fl.freeze_project_deletion(cloud, document, {})
    assert not cloud.deleted


def test_vault_dependency_is_retained_not_silently_deleted():
    document, cloud = prepared()
    cloud.bodies[VAULT.lower()]["properties"]["dependency"] = RESOURCE
    document["deletion_scope"]["options"]["include_project_subnets"] = True
    document["reviewed_scope"]["deletion_options"]["include_project_subnets"] = True
    result = fl.freeze_project_deletion(cloud, document, {})
    assert not next(row for row in result["resources"] if row["id"].lower() == RESOURCE.lower())["delete"]
    assert next(row for row in result["resources"] if row["id"].lower() == SUBNET.lower())["delete"]


def test_rg_delete_cannot_cascade_retained_subnet():
    document, cloud = prepared(False, True)
    nested_vnet = GROUP + "/providers/Microsoft.Network/virtualNetworks/project-vnet"
    cloud.bodies[nested_vnet.lower()] = tagged(nested_vnet, "Microsoft.Network/virtualNetworks", OWNER)
    with pytest.raises(fl.Blocked, match="resource-group-policy-mismatch"):
        fl.freeze_project_deletion(cloud, document, {})
    assert not cloud.deleted


@pytest.mark.parametrize("field", ("body", "owner", "new_resource", "permissions"))
def test_execution_rereads_before_any_delete(workspace, monkeypatch, field):
    document, cloud = prepared(True, True)
    if field == "body":
        cloud.bodies[VAULT.lower()]["etag"] = "changed"
    elif field == "owner":
        cloud.bodies[SUBNET.lower()]["tags"]["aifactory.project_id"] = "999"
    elif field == "new_resource":
        extra = RESOURCE + "-new"
        cloud.bodies[extra.lower()] = tagged(extra, "Microsoft.Network/publicIPAddresses", OWNER)
    else:
        cloud.permissions = False
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "run"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "blocked"
    assert not cloud.deleted


def test_interruption_retains_atomic_receipt_and_leases(workspace, monkeypatch):
    document, cloud = prepared(True, True)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    cloud.after_delete = lambda identifier: (_ for _ in ()).throw(KeyboardInterrupt())
    run = workspace / "run"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "reconciliation-required"
    assert result["pending_resource"] and result["locks_retained"]
    assert json.loads((run / "receipt.json").read_text()) == result


def test_project_cohort_requires_every_selected_environment_before_mutation(workspace, monkeypatch):
    document, cloud = prepared(True, True, ["dev", "stage"], "stage")
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "run"
    with pytest.raises(fl.Blocked, match="environments-incomplete"):
        fl.execute_cohort([document], source, run, run / "receipt.json", cloud_factory=lambda d: cloud)
    assert not cloud.deleted and not cloud.leases and not run.exists()


def test_canonical_source_rejection_never_mutates(workspace, monkeypatch):
    document, cloud = prepared()
    monkeypatch.setattr(fl, "verify_source", lambda *args: (_ for _ in ()).throw(fl.Blocked("dirty-source")))
    run = workspace / "run"
    with pytest.raises(fl.Blocked, match="dirty-source"):
        fl.execute(document, workspace / "source", run, run / "receipt.json", cloud=cloud)
    assert not cloud.deleted


def cohort_prepared(envs, subnets, group):
    documents, clouds = [], {}
    for environment in envs:
        document, cloud = prepared(subnets, group, envs, environment)
        def relocate(value):
            return json.loads(json.dumps(value).replace("/resourceGroups/reviewed", "/resourceGroups/reviewed-" + environment)
                              .replace("/resourcegroups/reviewed", "/resourcegroups/reviewed-" + environment)
                              .replace("/resourceGroups/common", "/resourceGroups/common-" + environment)
                              .replace("/resourcegroups/common", "/resourcegroups/common-" + environment)
                              .replace("Stage001", environment + "001"))
        cloud.bodies, cloud.enrollment = relocate(cloud.bodies), relocate(cloud.enrollment)
        document = relocate(document)
        document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
        document["deletion"] = fl.freeze_project_deletion(cloud, document, {})
        documents.append(seal(document))
        clouds[document["run_id"]] = cloud
    return documents, clouds


@pytest.mark.parametrize("envs", ENVIRONMENTS)
@pytest.mark.parametrize("subnets,group", list(itertools.product((False, True), repeat=2)))
def test_all_selected_environments_execute_under_one_reviewed_cohort(workspace, monkeypatch, envs, subnets, group):
    documents, clouds = cohort_prepared(envs, subnets, group)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "run"
    result = fl.execute_cohort(documents, source, run, run / "receipt.json", cloud_factory=lambda d: clouds[d["run_id"]])
    assert result["status"] == "succeeded", result
    assert result["operation"] == "delete-project"
    assert sorted(child["target"]["environment"] for child in result["children"]) == sorted(envs)
    assert not result["locks_retained"]
    assert all(not cloud.leases for cloud in clouds.values())
    for document in documents:
        cloud = clouds[document["run_id"]]
        retained = {row["id"].lower() for row in document["deletion"]["resource_groups"]
                    + document["deletion"]["resources"] if not row["delete"]}
        assert set(cloud.bodies) == retained


def test_last_environment_permission_denial_blocks_all_children(workspace, monkeypatch):
    documents, clouds = cohort_prepared(["dev", "stage", "prod"], True, True)
    clouds[documents[-1]["run_id"]].permissions = False
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "run"
    result = fl.execute_cohort(documents, source, run, run / "receipt.json", cloud_factory=lambda d: clouds[d["run_id"]])
    assert result["status"] == "blocked", result
    assert all(not cloud.deleted and not cloud.leases for cloud in clouds.values())
    assert all(not cloud.runs for cloud in clouds.values())


def test_untaggable_subnet_requires_actual_immutable_receipt():
    document, cloud = prepared(True, False)
    cloud.bodies[SUBNET.lower()]["tags"] = {}
    cloud.bodies[VNET.lower()]["properties"]["subnets"][0] = copy.deepcopy(cloud.bodies[SUBNET.lower()])
    with pytest.raises(fl.Blocked, match="subnet-ownership-unverified"):
        fl.freeze_project_deletion(cloud, document, {})
    identifier = str(uuid4())
    receipt = {"schema": 1, "run_id": identifier, "manifest_hash": "f" * 64,
               "status": "succeeded", "target": document["target"],
               "ownership": [{"resource_id": SUBNET, "owner": OWNER, "body_hash": fl.resource_digest(cloud.bodies[SUBNET.lower()])}]}
    cloud.runs["runs/" + identifier + ".worker.json"] = receipt
    records = {SUBNET.lower(): {"owner": OWNER, "ownership_source": "deployment-receipt",
                                "ownership_evidence": {"run_id": identifier, "receipt_hash": fl.digest(receipt)}}}
    plan = fl.freeze_project_deletion(cloud, document, records)
    assert next(item for item in plan["resources"] if item["id"].lower() == SUBNET.lower())["delete"]
    cloud.runs["runs/" + identifier + ".worker.json"]["status"] = "failed"
    with pytest.raises(fl.Blocked, match="receipt-unverified"):
        fl.freeze_project_deletion(cloud, document, records)


def test_checked_subnet_cannot_elevate_readonly_common_dependency():
    document, cloud = prepared(True, False)
    document["locks"]["scopes"] = [GROUP]
    document["locks"]["common_dependencies"] = [COMMON]
    cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = [COMMON.lower()]
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    with pytest.raises(fl.Blocked, match="writable-project-subnet"):
        fl.freeze_project_deletion(cloud, document, {})


def test_case_insensitive_shared_marker_never_deleted():
    document, cloud = prepared()
    cloud.bodies[RESOURCE.lower()]["tags"]["AIFACTORY.SHARED"] = "TRUE"
    with pytest.raises(fl.Blocked, match="shared"):
        fl.freeze_project_deletion(cloud, document, {})


def test_retained_resource_drift_after_first_delete_stops_before_next(workspace, monkeypatch):
    document, cloud = prepared(True, False)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    cloud.after_delete = lambda identifier: cloud.bodies[VAULT.lower()].update(etag='"concurrent-change"')
    run = workspace / "run"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "reconciliation-required"
    assert len(cloud.deleted) == 1 and cloud.leases


@pytest.mark.parametrize("include", (False, True))
def test_exact_project_nsg_and_subnet_retention_or_ordered_delete(workspace, monkeypatch, include):
    document, cloud = prepared(include, True)
    nsg = COMMON + "/providers/Microsoft.Network/networkSecurityGroups/project-nsg"
    cloud.bodies[nsg.lower()] = tagged(nsg, "Microsoft.Network/networkSecurityGroups", OWNER, {"subnets": [{"id": SUBNET}]})
    cloud.bodies[SUBNET.lower()]["properties"]["networkSecurityGroup"] = {"id": nsg}
    cloud.bodies[VNET.lower()]["properties"]["subnets"][0] = copy.deepcopy(cloud.bodies[SUBNET.lower()])
    document["deletion_scope"]["registered_resource_ids"].append(nsg)
    document["deletion"] = fl.freeze_project_deletion(cloud, document, {})
    seal(document)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "run"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert (nsg.lower() in cloud.bodies) != include
    if include:
        assert [key.lower() for key in cloud.deleted].index(SUBNET.lower()) < [key.lower() for key in cloud.deleted].index(nsg.lower())


def test_retained_subnet_keeps_nsg_and_all_security_rules():
    document, cloud = prepared(False, False)
    nsg = GROUP + "/providers/Microsoft.Network/networkSecurityGroups/project-nsg"
    rule = nsg + "/securityRules/necessary-rule"
    cloud.bodies[nsg.lower()] = tagged(nsg, "Microsoft.Network/networkSecurityGroups", OWNER, {"subnets": [{"id": SUBNET}]})
    cloud.bodies[rule.lower()] = tagged(rule, "Microsoft.Network/networkSecurityGroups/securityRules", OWNER)
    cloud.bodies[SUBNET.lower()]["properties"]["networkSecurityGroup"] = {"id": nsg}
    cloud.bodies[VNET.lower()]["properties"]["subnets"][0] = copy.deepcopy(cloud.bodies[SUBNET.lower()])
    plan = fl.freeze_project_deletion(cloud, document, {})
    retained = {item["id"].lower() for item in plan["resources"] if not item["delete"]}
    assert {SUBNET.lower(), nsg.lower(), rule.lower()} <= retained


def test_receipt_body_drift_warns_and_the_receipt_still_proves_project_ownership(workspace, monkeypatch):
    """aif-145 Scenario 4 (2026-11-04): Scenario 3's update redeployed project resources after their receipt, and a
    private endpoint's NIC cannot be tagged. Hash drift warns, never blocks: the verified receipt names this exact
    resource id for this owner, the drift stays as review evidence and execution proves the same receipt again."""
    document, cloud = prepared()
    cloud.bodies[RESOURCE.lower()]["tags"] = {}
    identifier = str(uuid4())
    receipt = {"schema": 1, "run_id": identifier, "manifest_hash": "f" * 64,
               "status": "succeeded", "target": document["target"],
               "ownership": [{"resource_id": RESOURCE, "owner": OWNER,
                              "body_hash": fl.resource_digest(cloud.bodies[RESOURCE.lower()])}]}
    cloud.runs["runs/" + identifier + ".worker.json"] = receipt
    cloud.bodies[RESOURCE.lower()]["properties"]["ipTags"] = ["updated-after-the-receipt"]
    evidence = {"run_id": identifier, "receipt_hash": fl.digest(receipt)}
    records = {RESOURCE.lower(): {"owner": OWNER, "ownership_source": "deployment-receipt",
                                  "ownership_evidence": evidence}}
    document["deletion"] = fl.freeze_project_deletion(cloud, document, records)
    row = next(item for item in document["deletion"]["resources"] if item["id"].lower() == RESOURCE.lower())
    assert row["delete"] and row["ownership_source"] == "deployment-receipt"
    assert row["receipt_body_drift"] == {"code": "child-instance-ownership-unverified", "ownership_evidence": evidence}
    document = seal(document)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert RESOURCE in result["deleted_resources"]
    receipt["ownership"][0]["owner"] = {**OWNER, "scaleset_id": "another-scale-set"}
    cloud.runs["runs/" + identifier + ".worker.json"] = receipt
    records[RESOURCE.lower()]["ownership_evidence"] = {"run_id": identifier, "receipt_hash": fl.digest(receipt)}
    with pytest.raises(fl.Blocked):
        fl.freeze_project_deletion(cloud, prepared()[0], records)


ROLE = GROUP + "/providers/Microsoft.Authorization/roleAssignments/28724663-3b27-58be-8275-5b429900b9b9"
POLICY_SETTING = VAULT + "/providers/microsoft.insights/diagnosticSettings/setByPolicy-MCAPSGovernance"


class UntaggableChildrenCloud(ProjectCloud):
    def __init__(self):
        super().__init__()
        self.bodies[ROLE.lower()] = {"id": ROLE, "type": "Microsoft.Authorization/roleAssignments",
                                     "properties": {"scope": GROUP, "principalId": "p", "roleDefinitionId": "r"}}
        self.bodies[POLICY_SETTING.lower()] = {"id": POLICY_SETTING, "type": "microsoft.insights/diagnosticSettings",
                                               "properties": {"logs": []}}

    def collection(self, path, api_version, extension=False):
        if not extension:
            return super().collection(path, api_version, extension)
        prefix = path.lower() + "/"
        return [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                if key.startswith(prefix) and "/" not in key[len(prefix):]], None

    def provider_schema(self, namespace):
        if namespace.lower() == "microsoft.authorization":
            return {"resourceTypes": [{"resourceType": "roleAssignments", "apiVersions": ["2022-04-01"]}]}
        if namespace.lower() == "microsoft.insights":
            return {"resourceTypes": [{"resourceType": "diagnosticSettings", "apiVersions": ["2021-05-01-preview"]}]}
        return super().provider_schema(namespace)


@pytest.mark.parametrize("group", (True, False))
def test_untaggable_children_die_with_the_deleted_project_group(workspace, monkeypatch, group):
    """aif-145 Scenario 4 (2026-11-04): two role assignments on the project group and MCAPS policy's diagnostic
    setting on a project resource carry no tags and no receipt. When the reviewed deletion removes the project group
    they die with it, so their owned parent proves them; a retained group still needs real ownership evidence."""
    if not group:
        with pytest.raises(fl.Blocked, match="project-group-ownership-incomplete-or-shared"):
            prepared(False, False, cloud_class=UntaggableChildrenCloud)
        return
    document, cloud = prepared(False, True, cloud_class=UntaggableChildrenCloud)
    rows = {row["id"].lower(): row for row in document["deletion"]["resources"]}
    assert rows[ROLE.lower()]["ownership_source"] == "managed-parent"
    assert rows[ROLE.lower()]["managed_parent_id"] == GROUP.lower()
    assert rows[POLICY_SETTING.lower()]["managed_parent_id"] == VAULT.lower()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert GROUP.lower() not in cloud.bodies and ROLE.lower() not in cloud.bodies


WORKSPACE = COMMON + "/providers/Microsoft.OperationalInsights/workspaces/common-logs"
TABLE = WORKSPACE + "/tables/AACAudit"


class LogTablesCloud(ProjectCloud):
    """A common Log Analytics workspace whose tables ARM lists without a type and moves on its own schedule."""
    workspace, table, owner = WORKSPACE, TABLE, CORE_OWNER

    def __init__(self):
        super().__init__()
        self.bodies[self.workspace.lower()] = tagged(self.workspace, "Microsoft.OperationalInsights/workspaces",
                                                     self.owner)
        self.bodies[self.table.lower()] = {"id": self.table, "name": "AACAudit",
                                      "properties": {"plan": "Analytics", "totalRetentionInDays": 30,
                                                     "schema": {"name": "AACAudit"}}}

    def provider_schema(self, namespace):
        if namespace.lower() == "microsoft.operationalinsights":
            return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2026-03-01"]}
                                      for kind in ("workspaces", "workspaces/tables")]}
        return super().provider_schema(namespace)

    def collection(self, path, api_version, extension=False):
        if path.lower().endswith("/tables"):
            return [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                    if key.startswith(path.lower() + "/")], None
        return super().collection(path, api_version, extension)


class ProjectLogTablesCloud(LogTablesCloud):
    """The same workspace in the project group: its tables are frozen and die with the deleted group."""
    workspace = GROUP + "/providers/Microsoft.OperationalInsights/workspaces/project-logs"
    table, owner = workspace + "/tables/AACAudit", OWNER


@pytest.mark.parametrize("cloud_class", (LogTablesCloud, ProjectLogTablesCloud))
def test_listed_log_tables_are_fingerprinted_with_their_kind(workspace, monkeypatch, cloud_class):
    """aif-145 Scenario 4 (2026-11-04): the common workspace's 697 tables come from list rows without a type, so a
    digest without their kind kept the volatile fields the closure ignores: invalid-project-resource-proof.
    A common table no project resource names is no longer frozen at all; a project group's table still is."""
    document, cloud = prepared(False, cloud_class is ProjectLogTablesCloud, cloud_class=cloud_class)
    fl.validate_project_deletion(document)
    assert (cloud_class.table.lower() in document["deletion"]["bodies"]) == (cloud_class is ProjectLogTablesCloud)
    volatile = fl.VOLATILE_FIELDS["microsoft.operationalinsights/workspaces/tables"][0]
    body = cloud.bodies[cloud_class.table.lower()]
    for field in volatile[:-1]:
        body = body.setdefault(field, {})
    body[volatile[-1]] = "moved-by-the-platform"
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result


ALERT_RULE = GROUP + "/providers/microsoft.alertsmanagement/smartDetectorAlertRules/Failure Anomalies - ain-prj001"


class SpacedNameCloud(ProjectCloud):
    def __init__(self):
        super().__init__()
        self.bodies[ALERT_RULE.lower()] = tagged(ALERT_RULE, "microsoft.alertsmanagement/smartDetectorAlertRules", OWNER)

    def provider_schema(self, namespace):
        if namespace.lower() == "microsoft.alertsmanagement":
            return {"resourceTypes": [{"resourceType": "smartDetectorAlertRules", "apiVersions": ["2021-04-01"]}]}
        return super().provider_schema(namespace)


def test_arm_names_with_inner_spaces_are_valid_project_resources():
    """aif-145 Scenario 4 (2026-11-04): Application Insights names its Failure Anomalies rule with spaces and
    Foundry its capability hosts with @."""
    document, _ = prepared(False, True, cloud_class=SpacedNameCloud)
    fl.validate_project_deletion(document)
    assert next(row for row in document["deletion"]["resources"] if row["id"].lower() == ALERT_RULE.lower())["delete"]
    assert fl.NESTED_ID.fullmatch(GROUP + "/providers/Microsoft.CognitiveServices/accounts/a/capabilityHosts/a@aml_aiagentservice")
    assert not fl.NESTED_ID.fullmatch(GROUP + "/providers/Microsoft.Web/sites/ trailing ")
    assert not fl.NESTED_ID.fullmatch(GROUP + "/providers/Microsoft.Web/sites/..")


OTHER_GROUP = f"/subscriptions/{SUB}/resourceGroups/other-project"
OTHER_OWNER = {**OWNER, "project_id": "018"}


def padded(index):
    return {"resourceGuid": str(uuid4()), "index": index, "provisioningState": "Succeeded",
            "description": " ".join(f"Setting {item} of resource {index} as the AI Factory deploys it." for item in range(8))}


class FactorySizedCloud(LogTablesCloud):
    """aif-145 on 2026-11-04: a common group with 697 Log Analytics tables (about 4.4 KB each as ARM lists them) and
    about 580 other resources, and two project groups of about 215 resources each. A common subnet names a project
    resource, as the common VNet's project subnet names the project's private endpoint NICs."""

    def __init__(self):
        super().__init__()
        for index in range(697):
            table = WORKSPACE + f"/tables/Table{index:03d}_CL"
            self.bodies[table.lower()] = {"id": table, "name": table.rsplit("/", 1)[-1], "properties": {
                "plan": "Analytics", "totalRetentionInDays": 30, "retentionInDays": 30,
                "schema": {"name": table.rsplit("/", 1)[-1], "tableType": "Microsoft",
                           "columns": [{"name": f"Column{column}", "type": "string", "isHidden": False,
                                        "description": f"Column {column} of {table.rsplit('/', 1)[-1]} as its solution defines it"}
                                       for column in range(40)]}}}
        for index in range(64):
            nsg = COMMON + f"/providers/Microsoft.Network/networkSecurityGroups/nsg-{index:02d}"
            self.bodies[nsg.lower()] = tagged(nsg, "Microsoft.Network/networkSecurityGroups", CORE_OWNER, padded(index))
            for rule in range(8):
                identifier = nsg + f"/securityRules/rule-{rule}"
                self.bodies[identifier.lower()] = tagged(
                    identifier, "Microsoft.Network/networkSecurityGroups/securityRules", CORE_OWNER, padded(rule))
        self.bodies[OTHER_GROUP.lower()] = tagged(OTHER_GROUP, "Microsoft.Resources/resourceGroups", OTHER_OWNER)
        for scope, owner in ((GROUP, OWNER), (OTHER_GROUP, OTHER_OWNER)):
            for index in range(212):
                address = scope + f"/providers/Microsoft.Network/publicIPAddresses/ip-{index:03d}"
                self.bodies[address.lower()] = tagged(address, "Microsoft.Network/publicIPAddresses", owner, padded(index))
        self.bodies[SUBNET.lower()]["properties"]["ipConfigurations"] = [{"id": RESOURCE}]
        self.bodies[VNET.lower()]["properties"]["subnets"][0] = copy.deepcopy(self.bodies[SUBNET.lower()])


@pytest.mark.parametrize("group", (True, False))
def test_a_factory_sized_project_deletion_fits_the_protected_worker_and_github_dispatch(workspace, monkeypatch, group):
    """aif-145 Scenario 4 (2026-11-04): delete-project 002 froze every enrolled group - common with 697 Log Analytics
    tables, project001 and project002, 1704 resources - and every body twice (in the closure's collections and in
    `bodies`): 11.1 MB against the 8 MiB worker cap, 508 KB compressed against 16 GitHub secrets of 32,000 characters.
    The review freezes the project group, everything it deletes and the resources elsewhere that name them;
    execution still reads every group and verifies the same view of it."""
    document, cloud = prepared(False, group, cloud_class=FactorySizedCloud, scopes=(GROUP, OTHER_GROUP, COMMON))
    assert len(cloud.bodies) > 1700
    # pink catalog_runtime refuses a frozen manifest above 8 MiB - 4096 (protected-worker capacity)
    assert len(fl.canonical(document)) <= fl.MAX_DOCUMENT - 4096
    assert len(fl.github_envelope_chunks(document, types.SimpleNamespace(held={"run_id": document["run_id"]}))) <= 16
    frozen = set(document["deletion"]["bodies"])
    assert {key for key in cloud.bodies if fl.arm_scope(key) == GROUP.lower()} <= frozen
    assert {GROUP.lower(), OTHER_GROUP.lower(), COMMON.lower(), SUBNET.lower(), VNET.lower()} <= frozen
    assert not any(fl.arm_scope(key) == OTHER_GROUP.lower() or "/tables/" in key or "/networksecuritygroups/" in key
                   for key in frozen - {OTHER_GROUP.lower()})
    fl.validate_manifest(document)
    if not group:
        return  # a retained group deletes resource by resource; the small cases above execute that
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert GROUP.lower() not in cloud.bodies and SUBNET.lower() in cloud.bodies
    assert sum(fl.arm_scope(key) == OTHER_GROUP.lower() for key in cloud.bodies) == 213


def test_unrelated_common_changes_after_review_never_block_a_project_deletion(workspace, monkeypatch):
    """The platform adds and updates common Log Analytics tables all day. Nothing in the deleted project names them,
    so a table added or changed between review and execution is no changed reviewed resource."""
    document, cloud = prepared(False, True, cloud_class=LogTablesCloud)
    added = WORKSPACE + "/tables/AddedAfterReview_CL"
    cloud.bodies[added.lower()] = {"id": added, "name": "AddedAfterReview_CL", "properties": {"plan": "Analytics"}}
    cloud.bodies[TABLE.lower()]["properties"]["plan"] = "Basic"
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert GROUP.lower() not in cloud.bodies and added.lower() in cloud.bodies


@pytest.mark.parametrize("group", (True, False))
def test_a_new_reference_to_a_reviewed_deletion_blocks_execution(workspace, monkeypatch, group):
    """The live closure decides: a resource elsewhere that names a resource the review deletes, created after the
    review, stops the run before any delete."""
    document, cloud = prepared(False, group)
    dependent = COMMON + "/providers/Microsoft.Network/publicIPAddresses/common-dependent"
    cloud.bodies[dependent.lower()] = tagged(dependent, "Microsoft.Network/publicIPAddresses", CORE_OWNER,
                                             {"linkedPublicIPAddress": {"id": RESOURCE}})
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] != "succeeded" and not cloud.deleted, result
    assert result["error_code"] == "project-complete-inventory-changed", result


class ServiceLinkCloud(ProjectCloud):
    """The project subnet in the common VNet names a project resource and carries a Container Apps service
    association link whose `link` leaves out /providers/Microsoft.Network, as ARM lists it on aif-145."""

    def __init__(self):
        super().__init__()
        malformed = VNET.replace("/providers/Microsoft.Network", "") + "/subnets/project-subnet"
        self.bodies[SUBNET.lower()]["properties"].update(ipConfigurations=[{"id": RESOURCE}], serviceAssociationLinks=[{
            "name": "legionservicelink", "id": SUBNET + "/serviceAssociationLinks/legionservicelink",
            "properties": {"linkedResourceType": "Microsoft.App/environments", "link": malformed}}])
        self.bodies[VNET.lower()]["properties"]["subnets"][0] = copy.deepcopy(self.bodies[SUBNET.lower()])


def test_a_malformed_service_association_link_never_blocks_the_retained_vnet_check(workspace, monkeypatch):
    """aif-145 Scenario 4 (2026-11-04): the common VNet stays in a project deletion's view because its project subnet
    names the project's NICs. Execution strips back-references of deleted dependents before comparing it, and the
    strict parse of the subnets' Container Apps service association link stopped that (invalid-resource-reference).
    A malformed link names no deleted dependent; it stays and still compares."""
    document, cloud = prepared(False, True, cloud_class=ServiceLinkCloud)
    assert VNET.lower() in document["deletion"]["bodies"]
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    run = workspace / "execution"
    result = fl.execute(document, source, run, run / "receipt.json", cloud=cloud)
    assert result["status"] == "succeeded", result
    assert GROUP.lower() not in cloud.bodies and VNET.lower() in cloud.bodies
