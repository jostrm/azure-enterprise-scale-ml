"""Offline: a resource reviewed for deletion that the platform removed with another deletion is absent, not drift.

aif-138 (2026-11-02): the resumed factory deletion's common stage deleted Defender for Storage's event subscription
StorageAntimalwareSubscription; the platform then removed its Event Grid system topic, which the review had also
selected for deletion. The next inventory check stopped with project-resource-closure-changed. A vanished resource
the review retains still blocks.
"""

import pytest

from .test_factory_lifecycle import fl
from .test_selective_project_deletion import prepared, RESOURCE, VNET

UNRELATED = "/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/gone/providers/a.b/c/d"


@pytest.mark.parametrize("removed", [(), (UNRELATED,)])
def test_a_reviewed_delete_the_platform_already_removed_is_accepted(removed):
    document, cloud = prepared(True, True)
    assert next(row for row in document["deletion"]["resources"] if row["id"].lower() == RESOURCE.lower())["delete"]
    del cloud.bodies[RESOURCE.lower()]
    bodies = fl.verify_project_inventory(cloud, document, removed)
    assert RESOURCE.lower() not in bodies


def test_a_vanished_retained_resource_still_blocks():
    document, cloud = prepared(True, True)
    assert not next(row for row in document["deletion"]["resources"] if row["id"].lower() == VNET.lower())["delete"]
    del cloud.bodies[VNET.lower()]
    with pytest.raises(fl.Blocked, match="^project-resource-closure-changed$"):
        fl.verify_project_inventory(cloud, document, (UNRELATED,))


def test_a_new_resource_still_blocks():
    document, cloud = prepared(True, True)
    extra = RESOURCE + "-new"
    cloud.bodies[extra.lower()] = dict(cloud.bodies[RESOURCE.lower()], id=extra)
    with pytest.raises(fl.Blocked):
        fl.verify_project_inventory(cloud, document, (UNRELATED,))
