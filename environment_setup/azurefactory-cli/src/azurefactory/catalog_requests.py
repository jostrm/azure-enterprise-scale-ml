"""Shared CLI/SDK request builders; catalog semantics remain server-owned."""

from typing import Any

from .errors import ConfigError


def _request(folder, factory_id, action, expected_revision=None, **values):
    return {key: value for key, value in {
        "folder": folder, "contract_version": 1, "action": action, "factory_id": factory_id,
        "expected_revision": expected_revision, **values,
    }.items() if value is not None}


def factory_clone_request(
    folder: str, factory_id: str, *, prefix: str | None = None, region: str | None = None,
    factory_key: str | None = None, scale_set_id: str | None = None, include_projects: str = "none",
    aifactory_version: str | None = None, expected_revision: str | None = None,
    region_short_name: str | None = None,
) -> dict[str, Any]:
    return _request(folder, factory_id, "clone", expected_revision, target_prefix=prefix,
                    target_region=region, target_region_short_name=region_short_name,
                    factory_key=factory_key, scale_set_id=scale_set_id,
                    include_projects=include_projects, aifactory_version=aifactory_version)


def scaleset_add_request(
    folder: str, factory_id: str, scale_sets: list[dict[str, Any]], *,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    return _request(folder, factory_id, "create-scale-set", expected_revision, scale_sets=scale_sets)


def _placements(placements, environments):
    if (placements is None) == (environments is None) or not (placements or environments):
        raise ConfigError("Supply nonempty placements OR explicit environments, never both; there is no implicit dev.")
    if placements is not None:
        return placements
    return [{"environment": environment} for environment in environments]


def project_add_request(
    folder: str, factory_id: str, *, number: str, display_name: str = "",
    placements: list[dict[str, str]] | None = None, environments: list[str] | None = None,
    settings: dict[str, Any] | None = None, expected_revision: str | None = None,
) -> dict[str, Any]:
    return _request(folder, factory_id, "add-project", expected_revision, settings=settings,
                    project={"number": number, "display_name": display_name,
                             "placements": _placements(placements, environments)})


def project_add_placements_request(
    folder: str, factory_id: str, project_id: str, *,
    placements: list[dict[str, str]] | None = None, environments: list[str] | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    return _request(folder, factory_id, "add-project-placements", expected_revision,
                    project_id=project_id, placements=_placements(placements, environments))


def project_delete_request(
    folder: str, factory_id: str, project_id: str, *, environments: list[str],
    include_project_subnets: bool, include_keyvault_and_resource_group: bool,
    expected_revision: str, scale_set_id: str | None = None, version_ref: str | None = None,
) -> dict[str, Any]:
    if type(include_project_subnets) is not bool or type(include_keyvault_and_resource_group) is not bool:
        raise ConfigError("Both project deletion options must be explicit booleans.")
    if not environments:
        raise ConfigError("Project deletion requires explicit environments.")
    return _request(folder, factory_id, "delete-project", expected_revision,
                    project_id=project_id, scale_set_id=scale_set_id, version_ref=version_ref,
                    deletion_options={"environments": environments,
                                      "include_project_subnets": include_project_subnets,
                                      "include_keyvault_and_resource_group": include_keyvault_and_resource_group})


def scaleset_delete_request(
    folder: str, factory_id: str, scale_set_id: str, *, expected_revision: str,
    version_ref: str | None = None,
) -> dict[str, Any]:
    return _request(folder, factory_id, "delete-scale-set", expected_revision,
                    scale_set_id=scale_set_id, version_ref=version_ref)


def draft_remove_request(
    folder: str, factory_id: str, *, kind: str, expected_revision: str,
    scale_set_id: str | None = None, project_id: str | None = None,
) -> dict[str, Any]:
    if kind not in {"factory", "scale-set", "project"}:
        raise ConfigError("Draft kind must be factory, scale-set or project; this never deletes Azure resources.")
    return _request(folder, factory_id, "delete-draft-" + kind, expected_revision,
                    scale_set_id=scale_set_id, project_id=project_id)
