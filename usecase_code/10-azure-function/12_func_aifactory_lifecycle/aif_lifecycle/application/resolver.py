"""Resolve readable IDs against the catalog by formatting each catalog entity and matching the whole string."""

from __future__ import annotations

from ..domain import regions
from ..domain.errors import Conflict
from ..domain.ids import FactoryId, ProjectId, ScalesetId, physical_environment
from ..ports import Catalog, CatalogFactory, CatalogProject, CatalogScaleset

ENVIRONMENT_ORDER = {"dev": 0, "stage": 1, "test": 1, "prod": 2}


def factory_code(factory: CatalogFactory) -> str:
    return factory.region_short_name or regions.code_for(factory.region)


def factory_prefix(factory: CatalogFactory) -> str:
    return factory.prefix.rstrip("-")


def scaleset_id(factory: CatalogFactory, scaleset: CatalogScaleset) -> ScalesetId:
    return ScalesetId(FactoryId(factory_prefix(factory), factory_code(factory),
                                physical_environment(scaleset.environment)), scaleset.suffix)


def project_id(factory: CatalogFactory, scaleset: CatalogScaleset, project: CatalogProject) -> ProjectId:
    return ProjectId(scaleset_id(factory, scaleset), project.number)


def find_factory(catalog: Catalog, target: FactoryId) -> CatalogFactory | None:
    """The factory with this prefix and region, in any environment."""
    found = [f for f in catalog.factories if factory_prefix(f) == target.prefix and factory_code(f) == target.region_code]
    if len(found) > 1:
        raise Conflict(f"More than one catalog factory matches {target}.", code="ambiguous-id")
    return found[0] if found else None


def find_scaleset(catalog: Catalog, target: ScalesetId) -> tuple[CatalogFactory, CatalogScaleset] | None:
    factory = find_factory(catalog, target.factory)
    if factory is None:
        return None
    for scaleset in factory.scale_sets:
        if str(scaleset_id(factory, scaleset)) == str(target):
            return factory, scaleset
    return None


def find_project(catalog: Catalog, target: ProjectId) -> tuple[CatalogFactory, CatalogScaleset, CatalogProject] | None:
    found = find_scaleset(catalog, target.scaleset)
    if found is None:
        return None
    factory, scaleset = found
    for project in factory.projects:
        if any(placement[1] == scaleset.id for placement in project.placements) and \
                str(project_id(factory, scaleset, project)) == str(target):
            return factory, scaleset, project
    return None


def projects_in(factory: CatalogFactory, scaleset: CatalogScaleset) -> list[CatalogProject]:
    placed = [p for p in factory.projects if any(placement[1] == scaleset.id for placement in p.placements)]
    return sorted(placed, key=lambda p: p.number)


def environments(factory: CatalogFactory) -> list[str]:
    return sorted({s.environment for s in factory.scale_sets}, key=lambda env: ENVIRONMENT_ORDER.get(env, 9))
