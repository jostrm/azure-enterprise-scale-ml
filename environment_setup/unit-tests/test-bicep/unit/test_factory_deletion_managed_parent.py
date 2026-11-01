"""Whole-factory deletion: option A, an untaggable child with no receipt is owned through its owned parent.

aif-138 (2026-11-01): after delete_project("001") the project group held only role assignments that the project
pipeline created (no tags, no receipts), and factory deletion refused with factory-delete-project-group-shared-or-unowned.
As in fl.freeze_deletion_inventory (bf9686b3), a role assignment at an owned group, or an untaggable child of an owned
resource, is owned through that parent; an untagged top-level resource is never adopted.
"""

import copy

import pytest

from .test_factory_lifecycle import fl, GROUP, OWNER
from .test_factory_deletion_pipeline import factory_prepared


ASSIGNMENTS = GROUP + "/providers/Microsoft.Authorization/roleAssignments"
ASSIGNMENT = ASSIGNMENTS + "/bef0b89d-72f9-509a-a526-4b3636d67672"
STRAY = GROUP + "/providers/Microsoft.Network/publicIPAddresses/untagged-stray"


def with_assignment(stray=False):
    document, cloud, projects = factory_prepared()
    cloud.bodies[ASSIGNMENT.lower()] = {"id": ASSIGNMENT, "type": "Microsoft.Authorization/roleAssignments",
                                        "name": ASSIGNMENT.rsplit("/", 1)[1],
                                        "properties": {"scope": GROUP, "principalId": "0f3e5778-b57f-4277-98c5-0689d3f81a67"}}
    if stray:
        cloud.bodies[STRAY.lower()] = {"id": STRAY, "type": "Microsoft.Network/publicIPAddresses", "etag": '"s"',
                                       "properties": {}}
    original, roots = cloud.collection, cloud.list_resources

    def collection(path, api_version, extension=False):
        if path.lower() == ASSIGNMENTS.lower():
            return [copy.deepcopy(cloud.bodies[ASSIGNMENT.lower()])], None
        return original(path, api_version, extension)

    def list_resources(scope):
        # As ARM: a group's /resources never lists its role assignments; only the extension collection does.
        return [row for row in roots(scope) if "/microsoft.authorization/" not in row["id"].lower()]
    schema = cloud.provider_schema

    def provider_schema(namespace):
        # As ARM: role assignments have their own read/write/delete operations.
        if namespace.lower() == "microsoft.authorization":
            return {"resourceTypes": [{"resourceType": "roleAssignments", "apiVersions": ["2022-04-01"]}]}
        return schema(namespace)
    cloud.collection, cloud.list_resources, cloud.provider_schema = collection, list_resources, provider_schema
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    return unsealed, cloud, projects


def test_a_role_assignment_at_the_owned_project_group_is_owned_through_the_group():
    document, cloud, projects = with_assignment()
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    row = next(item for item in data["resources"] if item["id"].lower() == ASSIGNMENT.lower())
    assert row["ownership_source"] == "managed-parent" and row["managed_parent_id"] == GROUP.lower()
    assert row["owner"] == OWNER and row["project_number"] == "017"


def test_an_untagged_top_level_resource_is_never_adopted_through_its_group():
    document, cloud, projects = with_assignment(stray=True)
    with pytest.raises(fl.Blocked, match="^factory-delete-project-group-shared-or-unowned$"):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)


def test_a_role_assignment_granting_the_deployment_principal_is_not_its_identity():
    # aif-138: the project group keeps the deployment principal's Contributor and RBAC Administrator assignments;
    # they grant it access, they are not an identity it runs as (that still blocks, see the access-hub tests).
    document, cloud, projects = with_assignment()
    cloud.bodies[ASSIGNMENT.lower()]["properties"]["principalId"] = document["identity"]["deployment_object_id"]
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    assert any(item["id"].lower() == ASSIGNMENT.lower() for item in data["resources"])
