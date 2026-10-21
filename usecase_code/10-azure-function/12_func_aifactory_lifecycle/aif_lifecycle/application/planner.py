"""Turn a scenario and a resolved target into ordered steps, enforcing existence and scope rules."""

from __future__ import annotations

from typing import Any

from ..domain.errors import AlreadyExists, ScopeNotSupported, UnknownId
from ..domain.ids import AnyId, FactoryId, ProjectId, ScalesetId
from ..domain.operation import Step, StepKind
from ..domain.scenarios import Scenario
from ..ports import Catalog
from . import resolver

DEFAULT_PROJECT_NUMBER = "001"


def plan(scenario: Scenario, target: AnyId, catalog: Catalog, options: dict[str, Any]) -> tuple[list[Step], dict[str, Any]]:
    builder = _BUILDERS[scenario]
    steps, resolved = builder(target, catalog, options)
    resolved["expected_revision"] = catalog.revision
    return steps, resolved


def _configure() -> Step:
    return Step.new("configure", StepKind.CONFIGURE)


def _init_factory(target: FactoryId, catalog: Catalog, options):
    if resolver.find_factory(catalog, target) is not None:
        raise AlreadyExists(f"A factory with prefix {target.prefix} in {target.region} is already in the catalog; "
                            "add a scale set (scenario 2) instead.")
    resolved = {"prefix": target.prefix + "-", "region": target.region, "region_code": target.region_code,
                "environment": target.catalog_env, "suffix": "001", "project_number": DEFAULT_PROJECT_NUMBER}
    if options.get("wholeWorkflow"):
        stages = [Step.new("bootstrap", StepKind.BOOTSTRAP)]
    else:
        stages = [Step.new(name, StepKind.BOOTSTRAP)
                  for name in ("deploy-connectivity", "deploy-common", "deploy-project001")]
    return [_configure(), *stages], resolved


def _add_scaleset(target: ScalesetId, catalog: Catalog, options):
    factory = resolver.find_factory(catalog, target.factory)
    if factory is None:
        raise UnknownId(f"No factory with prefix {target.factory.prefix} in {target.factory.region} is in the catalog; "
                        "initialize it first (scenario 1).")
    if resolver.find_scaleset(catalog, target) is not None:
        raise AlreadyExists(f"Scale set {target} is already in the catalog.")
    resolved = {"factory_id": factory.id, "factory_key": factory.key, "environment": target.factory.catalog_env,
                "suffix": target.suffix, "project_number": DEFAULT_PROJECT_NUMBER}
    steps = [_configure(), Step.new("deploy-common", StepKind.DEPLOY), Step.new("deploy-project001", StepKind.DEPLOY)]
    return steps, resolved


def _add_or_update_project(target: ProjectId, catalog: Catalog, options):
    found = resolver.find_scaleset(catalog, target.scaleset)
    if found is None:
        raise UnknownId(f"Scale set {target.scaleset} is not in the catalog.")
    factory, scaleset = found
    existing = resolver.find_project(catalog, target)
    resolved = {"factory_id": factory.id, "factory_key": factory.key, "scale_set_id": scaleset.id,
                "environment": scaleset.environment, "project_number": target.number,
                "project_id": existing[2].id if existing else None, "mode": "update" if existing else "add"}
    return [_configure(), Step.new("deploy-project", StepKind.DEPLOY)], resolved


def _delete_project(target: ProjectId, catalog: Catalog, options):
    found = resolver.find_project(catalog, target)
    if found is None:
        raise UnknownId(f"Project {target} is not in the catalog.")
    factory, scaleset, project = found
    resolved = {"factory_id": factory.id, "factory_key": factory.key, "scale_set_id": scaleset.id,
                "project_id": project.id, "environment": scaleset.environment, "project_number": project.number,
                "include_project_subnets": bool(options.get("includeProjectSubnets", True)),
                "include_keyvault_and_resource_group": bool(options.get("includeKeyvaultAndResourceGroup", True))}
    return [Step.new("delete-project", StepKind.DELETE)], resolved


def _delete_scaleset(target: ScalesetId, catalog: Catalog, options):
    found = resolver.find_scaleset(catalog, target)
    if found is None:
        raise UnknownId(f"Scale set {target} is not in the catalog.")
    factory, scaleset = found
    resolved = {"factory_id": factory.id, "factory_key": factory.key, "scale_set_id": scaleset.id,
                "environment": scaleset.environment}
    return [Step.new("delete-scaleset", StepKind.DELETE)], resolved


def _delete_factory(target: FactoryId, catalog: Catalog, options):
    factory = resolver.find_factory(catalog, target)
    if factory is None or target.catalog_env not in resolver.environments(factory):
        raise UnknownId(f"Factory {target} is not in the catalog.")
    envs = resolver.environments(factory)
    if envs != [target.catalog_env]:
        raise ScopeNotSupported(
            f"delete-aifactory deletes every environment of the factory, and this one also has "
            f"{', '.join(env for env in envs if env != target.catalog_env)}. Delete the {target.catalog_env} "
            "scale sets one by one with scenario 5 instead.", extra={"environments": envs})
    resolved = {"factory_id": factory.id, "factory_key": factory.key, "environment": target.catalog_env}
    return [Step.new("delete-factory", StepKind.DELETE)], resolved


_BUILDERS = {
    Scenario.INIT_FACTORY: _init_factory,
    Scenario.ADD_SCALESET: _add_scaleset,
    Scenario.ADD_OR_UPDATE_PROJECT: _add_or_update_project,
    Scenario.DELETE_PROJECT: _delete_project,
    Scenario.DELETE_SCALESET: _delete_scaleset,
    Scenario.DELETE_FACTORY: _delete_factory,
}
