"""Whole-factory deletion: a child changed since its deployment receipt is owned through its owned parent.

aif-138 (2026-11-01): after the access-hub links, the factory deletion freeze refused with
child-instance-ownership-unverified, as the scale-set deletion did before 389c75a8: a pipeline or the platform
updated a receipt-recorded child after its deployment receipt. Hash drift warns, never blocks; the owned parent
it is deleted with decides, and the superseded receipt stays as review evidence.
"""

import copy
from uuid import uuid4

import pytest

from .test_factory_lifecycle import fl, GROUP, OWNER
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import tagged


NSG = GROUP + "/providers/Microsoft.Network/networkSecurityGroups/project-nsg"
RULE = NSG + "/securityRules/allow-runner"


def drifted(parent_owner=OWNER):
    document, cloud, projects = factory_prepared()
    cloud.bodies[NSG.lower()] = tagged(NSG, "Microsoft.Network/networkSecurityGroups", parent_owner)
    cloud.bodies[RULE.lower()] = {"id": RULE, "type": "Microsoft.Network/networkSecurityGroups/securityRules",
                                  "etag": '"after-pipeline"', "properties": {"priority": 200}}
    run = str(uuid4())
    receipt = {"schema": 1, "status": "succeeded", "run_id": run, "manifest_hash": "e" * 64,
               "target": {key: OWNER[key] for key in ("factory_id", "scaleset_id")},
               "ownership": [{"resource_id": RULE, "owner": copy.deepcopy(OWNER),
                              "body_hash": fl.digest({"properties": {"priority": 100}})}]}
    cloud.runs["runs/" + run + ".worker.json"] = receipt
    evidence = {"run_id": run, "receipt_hash": fl.digest(receipt)}
    records = {RULE: {"owner": copy.deepcopy(OWNER), "ownership_source": "deployment-receipt",
                      "ownership_evidence": evidence}}
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    return unsealed, cloud, projects, records, evidence


def test_a_child_changed_since_its_receipt_is_deleted_with_its_owned_parent():
    document, cloud, projects, records, evidence = drifted()
    data = fl.freeze_factory_deletion_pipeline(cloud, document, records, projects)
    rule = next(row for row in data["resources"] if row["id"].lower() == RULE.lower())
    assert rule["owner"] == OWNER and rule["delete"] is True and rule["project_number"] == "017"
    assert rule["ownership_source"] == "managed-parent" and rule["managed_parent_id"] == NSG.lower()
    assert rule["receipt_superseded"] == {"code": "child-instance-ownership-unverified", "ownership_evidence": evidence}


def test_a_drifted_child_under_a_foreign_parent_still_blocks():
    document, cloud, projects, records, _ = drifted({**OWNER, "factory_id": "factory-b"})
    with pytest.raises(fl.Blocked, match="^live-resource-ownership-mismatch$"):
        fl.freeze_factory_deletion_pipeline(cloud, document, records, projects)


def test_a_drifted_hub_vnet_is_owned_through_the_bootstrap_hub_proof():
    # aif-138: the untagged common VNet changed since its receipt (peerings removed); the bootstrap record proves it.
    from .test_factory_deletion_access_hub import VNET as HUB_SOURCE_VNET, hub_document, projects
    document, cloud = hub_document()
    run = str(uuid4())
    receipt = {"schema": 1, "status": "succeeded", "run_id": run, "manifest_hash": "e" * 64,
               "target": {key: OWNER[key] for key in ("factory_id", "scaleset_id")},
               "ownership": [{"resource_id": HUB_SOURCE_VNET, "body_hash": fl.digest({"before": "peerings"}),
                              "owner": {key: OWNER[key] for key in ("factory_id", "scaleset_id")}}]}
    cloud.runs["runs/" + run + ".worker.json"] = receipt
    evidence = {"run_id": run, "receipt_hash": fl.digest(receipt)}
    records = {HUB_SOURCE_VNET: {"owner": receipt["ownership"][0]["owner"], "ownership_source": "deployment-receipt",
                                 "ownership_evidence": evidence}}
    data = fl.freeze_factory_deletion_pipeline(cloud, document, records, projects())
    vnet = next(row for row in data["resources"] if row["id"].lower() == HUB_SOURCE_VNET.lower())
    assert vnet["ownership_source"] == "access-hub-bootstrap-record" and vnet["delete"] is True
    assert vnet["receipt_superseded"] == {"code": "child-instance-ownership-unverified", "ownership_evidence": evidence}


# Option B (Joakim 2026-11-01): an API-2-Pipelines PROJECT run's deployment receipt (pink creation_pipeline_receipts)
# names untagged top-level resources too (Key Vault, storage, private endpoints, NICs, NSGs). A drifted one is deleted with
# the project group that carries exactly its owner, because the receipt (not the group) named this exact resource.
PIPELINE_NSG = GROUP + "/providers/Microsoft.Network/networkSecurityGroups/pipeline-nsg"
PIPELINE_RULE = PIPELINE_NSG + "/securityRules/deny-all"


def pipeline_receipted(drifted=(), record_owner=OWNER):
    document, cloud, projects = factory_prepared()
    cloud.bodies[PIPELINE_NSG.lower()] = {"id": PIPELINE_NSG, "type": "Microsoft.Network/networkSecurityGroups",
                                          "etag": '"v1"', "properties": {}}
    cloud.bodies[PIPELINE_RULE.lower()] = {"id": PIPELINE_RULE, "etag": '"r1"', "properties": {"priority": 4096},
                                           "type": "Microsoft.Network/networkSecurityGroups/securityRules"}
    run = str(uuid4())
    rows = [{"resource_id": key.lower(), "owner": copy.deepcopy(record_owner),
             "body_hash": fl.digest({"before": key}) if key in drifted else fl.resource_digest(cloud.bodies[key.lower()])}
            for key in (PIPELINE_NSG, PIPELINE_RULE)]
    receipt = {"schema": 1, "kind": "project-pipeline-run-v1", "status": "succeeded", "run_id": run,
               "manifest_hash": "f" * 64, "target": {key: OWNER[key] for key in ("factory_id", "scaleset_id")},
               "resource_groups": [], "ownership": rows}
    cloud.runs["runs/" + run + ".worker.json"] = receipt
    evidence = {"run_id": run, "receipt_hash": fl.digest(receipt)}
    records = {row["resource_id"]: {"owner": copy.deepcopy(record_owner), "ownership_source": "deployment-receipt",
                                    "ownership_evidence": evidence} for row in rows}
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    return unsealed, cloud, projects, records, evidence


def rows_of(data):
    return {row["id"].lower(): row for row in data["resources"]}


def test_untagged_resources_of_a_pipeline_receipt_are_deleted_with_the_project():
    document, cloud, projects, records, _ = pipeline_receipted()
    rows = rows_of(fl.freeze_factory_deletion_pipeline(cloud, document, records, projects))
    for key in (PIPELINE_NSG.lower(), PIPELINE_RULE.lower()):
        assert rows[key]["ownership_source"] == "deployment-receipt" and rows[key]["owner"] == OWNER
        assert rows[key]["delete"] is True and rows[key]["project_number"] == "017"


def test_a_top_level_resource_changed_since_its_pipeline_receipt_is_deleted_with_its_project_group():
    document, cloud, projects, records, evidence = pipeline_receipted(drifted=(PIPELINE_NSG,))
    rows = rows_of(fl.freeze_factory_deletion_pipeline(cloud, document, records, projects))
    nsg = rows[PIPELINE_NSG.lower()]
    assert nsg["ownership_source"] == "managed-parent" and nsg["managed_parent_id"] == GROUP.lower()
    assert nsg["owner"] == OWNER and nsg["delete"] is True
    assert nsg["receipt_superseded"] == {"code": "child-instance-ownership-unverified", "ownership_evidence": evidence}
    assert rows[PIPELINE_RULE.lower()]["ownership_source"] == "deployment-receipt"


def test_a_child_of_a_drifted_receipt_resource_follows_it_to_the_project_group():
    document, cloud, projects, records, _ = pipeline_receipted(drifted=(PIPELINE_NSG, PIPELINE_RULE))
    rows = rows_of(fl.freeze_factory_deletion_pipeline(cloud, document, records, projects))
    rule = rows[PIPELINE_RULE.lower()]
    assert rule["ownership_source"] == "managed-parent" and rule["managed_parent_id"] == PIPELINE_NSG.lower()
    assert rule["delete"] is True and rule["owner"] == OWNER


def test_a_drifted_top_level_resource_of_another_projects_receipt_still_blocks():
    document, cloud, projects, records, _ = pipeline_receipted(drifted=(PIPELINE_NSG,),
                                                               record_owner={**OWNER, "project_id": "018"})
    with pytest.raises(fl.Blocked, match="^live-resource-ownership-mismatch$"):
        fl.freeze_factory_deletion_pipeline(cloud, document, records, projects)
