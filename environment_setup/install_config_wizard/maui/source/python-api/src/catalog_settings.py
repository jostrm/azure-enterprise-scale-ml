"""Scoped, non-secret wizard settings for catalog factories, scale sets and projects."""

import copy
import math
import re

from src import wizard
from src.catalog_storage import CatalogError, catalog_lock, root_folder


LOCKED = {
    "orchestrator", "aifactory_version", "version_major", "version_minor", "version_branch",
    "admin_aifactoryPrefixRG", "admin_aifactorySuffixRG", "admin_location", "admin_locationSuffix",
    "tenantId", "dev_sub_id", "test_sub_id", "prod_sub_id", "project_number_000", "projectName",
    "github_new_repo", "dev_cidr_range", "test_cidr_range", "prod_cidr_range",
    "common_vnet_cidr", "common_subnet_cidr", "common_subnet_scoring_cidr",
    "common_pbi_subnet_cidr", "common_bastion_subnet_cidr",
}
SECRET = re.compile(r"secret|password|credential|private[_ -]?key|api[_ -]?key|connection[_ -]?string|"
                    r"(?:access|refresh|auth|bearer)[_ -]?token|(?:^|_)token$|pat$", re.I)
REFERENCE = re.compile(r"secret[_ -]?(?:id|uri|url)$|credential[_ -]?env(?:ironment)?(?:variable)?$", re.I)


def secret_field(key):
    return bool(SECRET.search(key) and not REFERENCE.search(key))


def editable_keys():
    return sorted(key for key in wizard.DEFAULT_STATE if not key.startswith("_")
                  and key not in LOCKED and not secret_field(key)
                  and not key.lower().startswith(("delete", "update", "clean"))
                  and key not in ("enableDeleteForDisabledResources", "debugEnableCleaning"))


def selection(document, factory_id, scale_set_id=None, project_id=None):
    from src.factory_catalog import select_factory, select_scale
    factory = select_factory(document, factory_id)
    scale = select_scale(factory, scale_set_id) if scale_set_id else None
    project = None
    if project_id:
        project = next((item for item in factory["projects"] if item["id"] == project_id), None)
        if project is None:
            raise CatalogError("Select a project belonging to the chosen factory.", 409)
        if scale and not any(item["scale_set_id"] == scale["id"] for item in project["placements"]):
            raise CatalogError("The project is not placed in this scale set.", 409)
    return factory, scale, project


def read(folder, factory_id, scale_set_id=None, project_id=None):
    from src.factory_catalog import load_document, source_revision
    root = root_folder(folder)
    with catalog_lock(root):
        document = load_document(root)
        factory, scale, project = selection(document, factory_id, scale_set_id, project_id)
        config = document["configurations"][factory["id"]]
        state = copy.deepcopy(wizard.new_configuration_defaults())
        state.update(config["factory"])
        if scale:
            state.update(config["scale_sets"].get(scale["id"], {}))
        if project:
            state.update(config["projects"].get(project["id"], {}))
        keys = editable_keys()
        return {
            "contract_version": 1, "revision": source_revision(root), "factory_id": factory["id"],
            "scale_set_id": scale["id"] if scale else None, "project_id": project["id"] if project else None,
            "state": {key: state.get(key, wizard.DEFAULT_STATE[key]) for key in keys},
            "field_keys": keys,
            "message": "Edit non-secret configuration only. Factory identity, placement, networking addresses, versions and credentials are managed separately.",
        }


def apply(document, request):
    factory, scale, project = selection(document, request["factory_id"], request["scale_set_id"], request["project_id"])
    values = request["settings"]
    allowed = set(editable_keys())
    if not values or set(values) - allowed:
        raise CatalogError("Only listed non-secret settings may be changed; identities, paths and credentials are not accepted.", 409)
    for value in values.values():
        if type(value) not in (str, bool, int, float, type(None)) or (isinstance(value, float) and not math.isfinite(value)):
            raise CatalogError("Settings must contain finite scalar values or JSON text matching the wizard schema.", 409)
        if isinstance(value, str) and len(value) > 131072:
            raise CatalogError("One setting exceeds its supported size.", 409)
    config = document["configurations"][factory["id"]]
    if project:
        destination = config["projects"].setdefault(project["id"], {})
    elif scale:
        destination = config["scale_sets"].setdefault(scale["id"], {})
    else:
        destination = config["factory"]
    destination.update(copy.deepcopy(values))
    return factory
