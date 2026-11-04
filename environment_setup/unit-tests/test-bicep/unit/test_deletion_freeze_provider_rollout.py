"""Scale-set and whole-factory deletion: a provider rollout between prepare and confirm changes no frozen closure.

aif-145 Scenario 4 (2026-11-04, job fa5a0a58): pink's confirmation re-freezes the inventory and compares the whole
closure (catalog_frozen_plan.deletion_changes), so Azure's continuous resource-provider manifest rollouts refused every
confirmation "closure, closure_hash changed". f16240b4 dropped provider fingerprints from the project view; the
delete-scale-set (freeze_deletion_inventory) and delete-factory (freeze_factory_deletion_pipeline) closures keep none
either. A provider fingerprint is derived and warns, never blocks (48b243f8): the live closure decides.
"""

import copy

from .test_factory_lifecycle import fl, ClosureCloud, manifest
from .test_factory_deletion_pipeline import factory_prepared


def rolling(cloud):
    """Azure rolls provider manifests out continuously: each read after a rollout lists one more api-version."""
    schema = cloud.provider_schema
    cloud.rollout = 0

    def provider_schema(namespace):
        value = copy.deepcopy(schema(namespace))
        for row in value["resourceTypes"]:
            row["apiVersions"] = row["apiVersions"] + ["2026-0%d-01-preview" % (1 + cloud.rollout % 9)] * bool(cloud.rollout)
        return value
    cloud.provider_schema = provider_schema
    return cloud


def test_a_provider_rollout_changes_no_frozen_scale_set_deletion_closure():
    cloud, document = rolling(ClosureCloud()), manifest()
    first = fl.freeze_deletion_inventory(cloud, document, {})
    cloud.rollout += 1
    again = fl.freeze_deletion_inventory(cloud, document, {})
    assert first["closure"]["providers"] == {}
    assert again["closure"] == first["closure"] and again["closure_hash"] == first["closure_hash"]
    assert first["closure_hash"] == fl.digest(first["closure"])


def test_a_provider_rollout_changes_no_frozen_factory_deletion_closure():
    document, cloud, projects = factory_prepared()
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    rolling(cloud)
    first = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    cloud.rollout += 1
    again = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    assert first["closure"]["providers"] == {}
    assert again["closure"] == first["closure"] and again["closure_hash"] == first["closure_hash"]
    assert first["closure_hash"] == fl.digest(first["closure"])
