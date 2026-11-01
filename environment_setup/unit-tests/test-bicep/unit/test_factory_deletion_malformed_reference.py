"""Whole-factory deletion: a provider-owned malformed ID-looking string never stops dependency planning.

aif-138 (2026-11-01): a Container Apps subnet's serviceAssociationLinks/legionservicelink carries
properties.link "/subscriptions/<sub>/resourcegroups/<rg>/virtualnetworks/<vnet>/subnets/<subnet>" (no /providers/).
The closure walk skips it (tolerant), but project_resource_dependencies parsed it strictly and the factory
deletion freeze refused with invalid-resource-reference. It is not a resolvable dependency; it is skipped.
"""

import copy

from .test_factory_lifecycle import fl
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import SUBNET, VNET


MALFORMED = "/subscriptions/" + SUBNET.split("/")[2] + "/resourcegroups/common/virtualnetworks/common-vnet/subnets/x"


def test_a_malformed_provider_link_is_not_a_dependency_and_never_blocks_the_freeze():
    document, cloud, projects = factory_prepared()
    link = {"id": SUBNET + "/serviceAssociationLinks/legionservicelink", "name": "legionservicelink",
            "properties": {"link": MALFORMED, "linkedResourceType": "Microsoft.App/environments"}}
    cloud.bodies[SUBNET.lower()]["properties"]["serviceAssociationLinks"] = [link]
    cloud.bodies[VNET.lower()]["properties"]["subnets"] = [
        copy.deepcopy(cloud.bodies[key]) for key in sorted(cloud.bodies) if key.startswith(VNET.lower() + "/subnets/")]
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    data = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    rows = {row["id"].lower(): row for row in data["resources"]}
    assert MALFORMED.lower() not in rows[SUBNET.lower()]["depends_on"]
    assert MALFORMED.lower() not in rows[VNET.lower()]["depends_on"]


def test_a_well_formed_cross_group_reference_is_still_a_dependency():
    body = {"id": SUBNET, "properties": {"routeTable": {"id": VNET.replace("virtualNetworks/common-vnet",
                                                                           "routeTables/common-rt")}}}
    assert fl.project_resource_dependencies(body) == [
        VNET.replace("virtualNetworks/common-vnet", "routeTables/common-rt").lower()]
