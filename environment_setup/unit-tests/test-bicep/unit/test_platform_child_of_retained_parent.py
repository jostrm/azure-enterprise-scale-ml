"""Offline: a platform child stays when its parent stays; the freeze no longer refuses the whole deletion.

aif-144 (2026-11-04, delete_factory run3/run4): the common VNet was retained (an unowned NIC pinned one of its
subnets), but its platform child taggedTrafficConsumers/Microsoft.CosmosDB.swedencentral was marked for deletion. A
platform child is only ever deleted with its parent, so the freeze refused factory-delete-service-lifecycle-unsupported.
"""

from .test_factory_lifecycle import fl, COMMON, OWNER, seal, no_real_services  # noqa: F401
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import tagged

REGISTRY = COMMON + "/providers/Microsoft.ContainerRegistry/registries/acrcommon"
BUILT_IN = REGISTRY + "/scopeMaps/_repositories_admin"
CORE = {key: value for key, value in OWNER.items() if key != "project_id"}


def frozen_with_unowned_registry():
    document, cloud, projects = factory_prepared()
    cloud.bodies[REGISTRY.lower()] = {"id": REGISTRY, "type": "Microsoft.ContainerRegistry/registries",
                                      "etag": '"registry"', "properties": {}}  # no owner tags: retained
    cloud.bodies[BUILT_IN.lower()] = tagged(BUILT_IN, "Microsoft.ContainerRegistry/registries/scopeMaps", CORE)
    old_schema, old_operations, old_collection = cloud.provider_schema, cloud.provider_operations, cloud.collection

    def schema(namespace):
        if namespace.lower() == "microsoft.containerregistry":
            return {"resourceTypes": [{"resourceType": name, "apiVersions": ["2025-04-01"]}
                                      for name in ("registries", "registries/scopeMaps")]}
        return old_schema(namespace)

    def operations(namespace):
        if namespace.lower() == "microsoft.containerregistry":
            return ["microsoft.containerregistry/" + kind + "/" + action
                    for kind in ("registries", "registries/scopemaps") for action in ("read", "write", "delete")]
        return old_operations(namespace)

    def collection(path, api_version, extension=False):
        if path.lower().endswith("/scopemaps"):
            return [dict(body) for key, body in sorted(cloud.bodies.items()) if key.startswith(path.lower() + "/")], None
        return old_collection(path, api_version, extension)

    cloud.provider_schema, cloud.provider_operations, cloud.collection = schema, operations, collection
    unsealed = dict(document)
    unsealed["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    return seal(unsealed)


def test_a_platform_child_of_a_retained_parent_is_retained_with_it():
    document = frozen_with_unowned_registry()
    fl.validate_manifest(document)
    frozen = {row["id"].lower(): row for row in document["deletion"]["resources"]}
    assert frozen[REGISTRY.lower()]["delete"] is False
    assert frozen[BUILT_IN.lower()]["delete"] is False
    assert frozen[BUILT_IN.lower()]["retention_reason"] == "retained-parent"
    assert "delete_via_parent" not in frozen[BUILT_IN.lower()]
