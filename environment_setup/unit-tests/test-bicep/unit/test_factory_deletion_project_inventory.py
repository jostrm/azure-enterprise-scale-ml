"""Whole-factory deletion re-reads its frozen inventory with the factory's own view, not a project deletion's.

aif-144 (2026-11-04, delete_factory run7/run10/run11): every cohort worker stopped before its run claim with
unexpected-factory-delete-failure. verify_project_inventory reads data["project_resource_group"] since 8a3e04eb
(project deletion freezes the project's view), and a factory deletion's frozen data has no such key: KeyError.
The factory deletion tests replaced verify_project_inventory, so no test read a real factory freeze with it.
"""

import pytest

from .test_factory_lifecycle import fl
from .test_factory_deletion_pipeline import factory_prepared


def test_an_unchanged_factory_inventory_verifies_before_the_run_claim():
    document, cloud, _ = factory_prepared()
    assert "project_resource_group" not in document["deletion"]
    fl.verify_project_inventory(cloud, document)


def test_a_changed_resource_in_a_factory_inventory_still_blocks():
    document, cloud, _ = factory_prepared()
    common_ip = next(key for key in cloud.bodies if key.endswith("/publicipaddresses/common-ip"))
    cloud.bodies[common_ip]["properties"] = {"changed": True}
    with pytest.raises(fl.Blocked, match="^project-complete-inventory-changed$"):
        fl.verify_project_inventory(cloud, document)
