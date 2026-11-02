"""Offline: execution re-reads a reviewed inventory at the api-versions the review read, never re-derived ones.

aif-138 (2026-11-02): the factory deletion's project stage stopped with project-resource-instance-changed on the
common container registry. Microsoft.ContainerRegistry was rolling out 2026-11-01; ARM front ends that did not list
it yet made the walk read the registry at an older version, whose body has fewer fields (no roleAssignmentMode,
regionalEndpoints, endpointProtocol). Twenty reads at the reviewed version all matched the frozen body.
"""

import pytest

from .test_factory_lifecycle import ClosureCloud, fl, owned_group_manifest, seal
from .test_selective_project_deletion import prepared

OLDER = "2020-01-01"


def older_front_end(cloud, namespace):
    """A front end that lists only an older version of `namespace`'s types; that version answers with another shape."""
    schema, arm = cloud.provider_schema, cloud.arm

    def listed(name):
        value = schema(name)
        if name.lower() != namespace:
            return value
        return {"resourceTypes": [{**row, "apiVersions": [OLDER]} for row in value["resourceTypes"]]}

    def answered(method, resource_id, api_version, allowed=(200,), headers=None):
        status, answer_headers, body = arm(method, resource_id, api_version, allowed, headers)
        if method == "GET" and api_version == OLDER and isinstance(body, dict):
            body = {**body, "properties": {**(body.get("properties") or {}), "olderShape": True}}
        return status, answer_headers, body

    cloud.provider_schema, cloud.arm = listed, answered


@pytest.mark.parametrize("removed", [(), ("/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/gone"
                                          "/providers/a.b/c/d",)])
def test_the_project_stage_rereads_at_the_reviewed_versions(removed):
    document, cloud = prepared(True, True)
    older_front_end(cloud, "microsoft.keyvault")
    fl.verify_project_inventory(cloud, document, set(removed))


def test_a_changed_project_resource_still_blocks_at_the_reviewed_version():
    document, cloud = prepared(True, True)
    older_front_end(cloud, "microsoft.keyvault")
    vault = next(key for key in cloud.bodies if key.endswith("/vaults/project-vault"))
    cloud.bodies[vault]["properties"] = {"changed": True}
    with pytest.raises(fl.Blocked, match="^project-complete-inventory-changed$"):
        fl.verify_project_inventory(cloud, document)


def test_the_common_teardown_rereads_at_the_reviewed_versions():
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    seal(document)
    older_front_end(cloud, "microsoft.network")
    fl.verify_full_inventory(cloud, document)


def test_frozen_versions_name_every_reviewed_resource_and_collection():
    cloud = ClosureCloud()
    document = owned_group_manifest(cloud)
    closure = document["deletion"]["closure"]
    versions = fl.frozen_resource_versions(document["deletion"])
    assert {key: versions[key] for key in closure["resources"]} == {
        key: value["api_version"] for key, value in closure["resources"].items()}
    assert all(versions[path] == entry["api_version"] for path, entry in closure["collections"].items()
               if "api_version" in entry and not path.endswith("/resources"))  # a group listing is RG_API always
