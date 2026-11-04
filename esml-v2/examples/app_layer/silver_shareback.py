"""Customer composition: choose a producer and variation, not a mutable latest table."""

from azure_esml.domain_layer.shareback import SilverShareback
from azure_esml.domain_layer.shared_lake import SharedLake


def share_project_silver(root, *, factory, environment, dataset, producer_project, variation,
                        release_version, completed_silver_key, owner, allowed_projects):
    catalog = SilverShareback(root, SharedLake(factory, environment))
    return catalog.publish(dataset=dataset, producer_project=producer_project, variation=variation,
                           version=release_version, source_key=completed_silver_key, table_relative="",
                           owner=owner, allowed_projects=allowed_projects, mode="reference")


def select_silver(project, root, *, dataset, producer_project, variation, release_version, input_name=None):
    catalog = SilverShareback(root, SharedLake(project.settings.aifactory, project.settings.scope["environment"]))
    return project.with_shared_silver(catalog, dataset=dataset, producer_project=producer_project,
                                      variation=variation, version=release_version, input_name=input_name)
