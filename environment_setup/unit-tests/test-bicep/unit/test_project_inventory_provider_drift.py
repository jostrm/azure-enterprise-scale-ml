"""Project inventory: a provider-schema fingerprint read from another ARM front end never blocks by itself.

aif-138 (2026-11-01): the whole-factory deletion's project stage stopped with project-complete-inventory-changed
under ARM throttling; the project closure was compared exactly, its derived provider-schema fingerprints included.
As 48b243f8 did for whole-group deletion, the live closure (groups, resources, collections) decides.
"""

import pytest

from .test_factory_lifecycle import fl
from .test_selective_project_deletion import prepared


def test_a_provider_schema_from_another_front_end_never_blocks_the_project_inventory():
    document, cloud = prepared(True, True)
    schema = cloud.provider_schema

    def rolled_out(namespace):
        # Another front end lists one more (unrelated) type: the provider digest moves, the chosen versions do not.
        value = schema(namespace)
        return {"resourceTypes": [*value["resourceTypes"], {"resourceType": "unrelatedPreviewThings",
                                                            "apiVersions": ["2026-09-01-preview"]}]}
    cloud.provider_schema = rolled_out
    fl.verify_project_inventory(cloud, document)


def test_a_changed_project_resource_still_blocks():
    document, cloud = prepared(True, True)
    vault = next(key for key in cloud.bodies if key.endswith("/vaults/project-vault"))
    cloud.bodies[vault]["properties"] = {"changed": True}
    with pytest.raises(fl.Blocked, match="^project-complete-inventory-changed$"):
        fl.verify_project_inventory(cloud, document)
