"""Selective deletion exercises the real collector/leases against disposable fakes."""

import copy
import itertools
import json
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


def prepared(subnets=False, group=False, environments=None, environment="stage"):
    cloud = ProjectCloud()
    document = manifest()
    document["target"]["environment"] = environment
    document["locks"]["scopes"] = [GROUP, COMMON]
    document["locks"]["common_dependencies"] = []
    for scope in (GROUP, COMMON):
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
               "ownership": [{"resource_id": SUBNET, "owner": OWNER, "body_hash": fl.digest(cloud.bodies[SUBNET.lower()])}]}
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
