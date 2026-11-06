"""Offline: a resource the plan deletes through its parent is not fingerprinted again before deletion.

aif-144 (2026-11-05, delete_factory run16, worker e488859b): the common teardown deleted 5 resources and then stopped
with project-resource-instance-changed on an ACR private endpoint's privateLinkServiceProxies child: the platform rewrote
its body when the registry's private endpoint connection it depends on was deleted. The plan marks such a child
delete_via_parent: it is never sent a DELETE of its own and leaves with its parent, so its body protects nothing.
"""

import pytest

from .test_factory_lifecycle import fl
from .test_selective_project_deletion import prepared

UNRELATED = "/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/gone/providers/a.b/c/d"


def vault_row(document):
    return next(row for row in document["deletion"]["resources"] if row["id"].lower().endswith("/vaults/project-vault"))


def test_a_child_deleted_through_its_parent_may_change_before_deletion():
    document, cloud = prepared(True, True)
    row = vault_row(document)
    row["delete"], row["delete_via_parent"] = True, row["id"].rsplit("/providers/", 1)[0]
    cloud.bodies[row["id"].lower()]["properties"] = {"rewritten": "by the platform"}
    fl.verify_project_inventory(cloud, document, {UNRELATED})


def test_a_changed_resource_deleted_on_its_own_still_blocks():
    document, cloud = prepared(True, True)
    row = vault_row(document)
    row.pop("delete_via_parent", None)
    cloud.bodies[row["id"].lower()]["properties"] = {"changed": True}
    with pytest.raises(fl.Blocked, match="^project-resource-instance-changed$"):
        fl.verify_project_inventory(cloud, document, {UNRELATED})
