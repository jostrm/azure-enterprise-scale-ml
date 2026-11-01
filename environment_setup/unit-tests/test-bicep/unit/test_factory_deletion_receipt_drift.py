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
