"""Opt-in factory identities, explicit placements and reviewed local lifecycle changes."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from pydantic import ValidationError

from src import factory_configuration, release_version, wizard
from src.catalog_storage import (
    CatalogError, atomic_write, catalog_lock, database, digest, encode, ordinary, read_json, root_folder,
)
from src.factory_catalog_models import CatalogFactory, CatalogPrepare, CatalogSummary, RuntimeBinding
from src.network_placement import estimate_full_projects
from src.project_metadata import planned_environments_from_project_state
from src.scaling_policy import resolved_common_networks
from src.ticket_connectors import TicketError


ENV_KEYS = {"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}
CATALOG_PATH = Path("config-wizard") / "catalog.json"
RUNTIME_ACTIONS = {"deploy", "delete-factory", "delete-scale-set"}
CONFIG_WARNING = "Configuration drafts only: no Azure resource, subscription, repository or pipeline is changed."


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def has_catalog(folder):
    return (Path(folder) / CATALOG_PATH).exists()


def _identity(seed=None):
    return str(uuid5(NAMESPACE_URL, seed)) if seed else str(uuid4())


def _settings(state, *, clone=False):
    from src.catalog_settings import REFERENCE, secret_field
    result = {key: value for key, value in state.items()
              if key in {*wizard.DEFAULT_STATE, "tagsProject", "tags"} and isinstance(value, (str, bool, int, float, type(None)))
              and not secret_field(key)}
    factory_configuration._configuration_only(result, clear_references=clone)
    if clone:
        for key in result:
            if REFERENCE.search(key):
                result[key] = ""
        for key in ("tags", "tagsProject"):
            if result.get(key):
                try:
                    tags = json.loads(result[key])
                except (ValueError, TypeError):
                    raise CatalogError("Project tags must be a JSON object before cloning.", 409) from None
                if not isinstance(tags, dict):
                    raise CatalogError("Project tags must be a JSON object before cloning.", 409)
                result[key] = json.dumps({name: value for name, value in tags.items()
                                          if not name.lower().startswith("aifactory.")})
    # Configuration never carries local path ownership or a deployment version implicitly.
    for key in list(result):
        if key.startswith("_") or re.search(r"status|job_id|run_id", key, re.I):
            result.pop(key)
    return result


def _network(state, environment):
    range_key = {"dev": "dev_cidr_range", "stage": "test_cidr_range", "prod": "prod_cidr_range"}[environment]
    try:
        vnet, common = resolved_common_networks(state, range_key)
    except (ValueError, KeyError, TypeError) as exc:
        raise CatalogError(f"Legacy {environment} networking needs explicit repair before migration.", 409) from exc
    capacity = estimate_full_projects(vnet, common)
    if not capacity:
        raise CatalogError(f"Legacy {environment} network has no supported full-project allocator capacity.", 409)
    return {"vnet_cidr": str(vnet), "max_projects": min(8, capacity),
            "common_subnets": {name: str(common[key]) for name, key in zip(
                ("common", "scoring", "powerbi", "bastion"),
                ("common_subnet_cidr", "common_subnet_scoring_cidr", "common_pbi_subnet_cidr", "common_bastion_subnet_cidr"))}}


def allocator_capacity(network):
    try:
        vnet = ipaddress.IPv4Network(network["vnet_cidr"], strict=True)
    except (ValueError, KeyError):
        raise CatalogError("Each scale set requires a network-aligned IPv4 VNet CIDR.") from None
    if not vnet.is_private or not 16 <= vnet.prefixlen <= 23:
        raise CatalogError("VNet CIDR must be private IPv4 /16 through /23.")
    try:
        common = ({key: ipaddress.IPv4Network(value, strict=True) for key, value in network["common_subnets"].items()}
                  if network.get("common_subnets") else
                  {str(index): ipaddress.IPv4Network((int(vnet.network_address) + index * 64, 26))
                   for index in range(4)})
        subnets = list(common.values())
        if any(not subnet.subnet_of(vnet) for subnet in subnets) or any(
                left.overlaps(right) for index, left in enumerate(subnets) for right in subnets[index + 1:]):
            raise ValueError("Overlapping or out-of-scope subnets")
        capacity = estimate_full_projects(vnet, common)
        if capacity is None:
            raise ValueError("Unsupported allocator capacity")
        return capacity
    except (ValueError, KeyError, TypeError):
        raise CatalogError("Common subnets must be aligned, disjoint, inside the VNet and supported by the allocator.", 409) from None


def _legacy_files(root):
    paths = {root / "variables.json", root / "config-wizard" / "factory_state.json",
             root / "config-wizard" / "aifactory-version.json", root.parent / ".gitmodules"}
    paths.update(Path(path) for path in wizard._list_project_snapshots(str(root), create_legacy_dir=False).values())
    paths.update(Path(path) for path in wizard._list_scalesets(str(root), create_legacy_dir=False).values())
    candidate, _ = wizard._startup_import_candidate(str(root), {})
    if candidate:
        paths.add(Path(candidate))
    # Orchestration source changes invalidate a migration even when factory_state is authoritative.
    for path in (root.parent / ".env",
                 root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"):
        if path.exists():
            paths.add(path)
    result = {}
    for path in sorted(paths):
        ordinary(path)
        if path.exists():
            if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise CatalogError("A legacy input is not a bounded ordinary file.", 409)
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            result[str(path)] = None
    return result


def _same_factory(state, prefix, region, root):
    owner = state.get("_save_folder")
    if owner and root_folder(owner) != root:
        raise CatalogError("Legacy snapshot ownership belongs to another factory folder.", 409)
    for key, expected in (("admin_aifactoryPrefixRG", prefix), ("admin_location", region)):
        if state.get(key) and str(state[key]).casefold() != expected.casefold():
            raise CatalogError("Legacy snapshots contain multiple factory identities; resolve ownership before migration.", 409)


def legacy_document(root):
    try:
        _, state, source_file = factory_configuration._load_source(str(root))
    except factory_configuration.ConfigurationError as exc:
        raise CatalogError(str(exc), exc.status_code) from None
    source_json = read_json(source_file) if source_file.suffix.lower() == ".json" else {}
    prefix = str(state["admin_aifactoryPrefixRG"]).strip()
    region = str(state["admin_location"]).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,19}", prefix):
        raise CatalogError("Legacy prefix needs repair to a lowercase readable catalog key.", 409)
    factory_configuration._region(region)
    seed = os.path.normcase(str(root)) + ":" + prefix + ":" + region
    factory = {"id": _identity(seed), "key": f"{prefix.rstrip('-')}-{region}", "prefix": prefix, "region": region,
               "default_orchestrator": state["orchestrator"], "status": "configured",
               "scale_sets": [], "projects": []}
    try:
        factory["aifactory_version"] = release_version.saved_version(root.parent)
    except TicketError:
        factory["aifactory_version"] = None
    configs = {"factory": _settings(state), "scale_sets": {}, "projects": {}}
    sources = [(None, state)]
    for path in wizard._list_scalesets(str(root), create_legacy_dir=False).values():
        snapshot = read_json(Path(path))
        if not Path(path).is_relative_to(root) and not snapshot.get("_save_folder"):
            raise CatalogError("External legacy scale-set snapshots need explicit folder ownership.", 409)
        _same_factory(snapshot, prefix, region, root)
        sources.append((path, {**state, **snapshot}))
    by_scope = {}
    for path, saved in sources:
        suffix = str(saved.get("admin_aifactorySuffixRG", "")).lstrip("-")
        if not re.fullmatch(r"\d{3}", suffix):
            raise CatalogError("Each legacy scale-set suffix must have exactly three digits.", 409)
        for env, key in ENV_KEYS.items():
            environment_state = saved
            if path is None and source_file.name == "variables.json":
                section = source_json.get("dev" if env == "dev" else "stage_prod", {})
                if not isinstance(section, dict):
                    raise CatalogError("Legacy environment variables must be JSON objects.", 409)
                reverse = {name.removeprefix("variables."): field for field, name in wizard.YAML_MAP.items()
                           if name.startswith("variables.")}
                environment_state = {**saved, **{reverse.get(name, name): value for name, value in section.items()}}
                _same_factory(environment_state, prefix, region, root)
            subscription = str(environment_state.get(key) or "").strip()
            if not subscription or "<todo>" in subscription.lower():
                continue
            try:
                subscription, tenant = str(UUID(subscription)), str(UUID(environment_state.get("tenantId", "")))
            except (ValueError, TypeError, AttributeError):
                raise CatalogError(f"Legacy {env} subscription/tenant must be explicit UUIDs.", 409) from None
            physical = (env, suffix, subscription)
            item = {"id": _identity(seed + ":" + ":".join(physical)), "environment": env, "suffix": suffix,
                    "subscription_id": subscription, "tenant_id": tenant,
                    "orchestrator": saved.get("orchestrator", state["orchestrator"]),
                    "network": _network(environment_state, env), "status": "configured", "owned_resource_ids": []}
            if physical in by_scope:
                if item != by_scope[physical]:
                    raise CatalogError("Legacy scale-set snapshots disagree on the same physical target.", 409)
                continue
            if any(ss["environment"] == env and ss["suffix"] == suffix for ss in factory["scale_sets"]):
                raise CatalogError("Legacy environment/suffix maps to multiple subscriptions; resolve the ambiguity.", 409)
            by_scope[physical] = item
            factory["scale_sets"].append(item)
            configs["scale_sets"][item["id"]] = _settings(environment_state)
    for number, path in wizard._list_project_snapshots(str(root), create_legacy_dir=False).items():
        saved = read_json(Path(path))
        if not Path(path).is_relative_to(root) and not saved.get("_save_folder"):
            raise CatalogError("External legacy project snapshots need explicit folder ownership.", 409)
        _same_factory(saved, prefix, region, root)
        declared = str(saved.get("project_number_000") or "")
        if not declared.isdigit() or int(declared) != int(number) or not 1 <= int(number) <= 999:
            raise CatalogError("Legacy project number and snapshot identity disagree.", 409)
        number = f"{int(number):03}"
        suffix = str(saved.get("admin_aifactorySuffixRG") or state["admin_aifactorySuffixRG"]).lstrip("-")
        placements = []
        for env in planned_environments_from_project_state(saved, number):
            physical = (env, suffix, str(saved[ENV_KEYS[env]]).lower())
            if physical not in by_scope:
                raise CatalogError("A project placement has no unambiguous matching scale set.", 409)
            placements.append({"environment": env, "scale_set_id": by_scope[physical]["id"]})
        if not placements:
            raise CatalogError("Each migrated project needs at least one explicit environment/subscription placement.", 409)
        project_id = _identity(seed + ":project:" + number + ":" + suffix)
        factory["projects"].append({"id": project_id, "key": f"project-{number}-{suffix}", "number": number,
                                    "display_name": str(saved.get("projectName") or f"Project {number}"),
                                    "status": "configured", "placements": placements})
        configs["projects"][project_id] = _settings(saved)
    document = {"schema_version": 1, "generation": "legacy", "factories": [factory],
                "configurations": {factory["id"]: configs}}
    validate_document(document, capacity=False)
    return document


def validate_document(document, *, capacity=True):
    if document.get("schema_version") != 1 or not isinstance(document.get("configurations"), dict):
        raise CatalogError("Unsupported catalog schema; install a compatible backend.", 409)
    ledger = document.get("ownership_evidence", {})
    if not isinstance(ledger, dict):
        raise CatalogError("Ownership receipt ledger is malformed.", 409)
    for resource, record in ledger.items():
        if (not isinstance(resource, str) or not resource.lower().startswith("/subscriptions/")
                or not isinstance(record, dict) or not isinstance(record.get("owner"), dict)
                or record.get("ownership_source") != "deployment-receipt"
                or not isinstance(record.get("ownership_evidence"), dict)
                or not re.fullmatch(r"[a-f0-9]{64}", str(record["ownership_evidence"].get("receipt_hash", "")))):
            raise CatalogError("Ownership evidence requires an exact deployment receipt record.", 409)
    identifiers, names, physical_targets, resources = set(), set(), set(), set()
    subscription_tenants = {}
    for factory in document.get("factories", []):
        try:
            CatalogFactory.model_validate(factory)
        except ValidationError:
            raise CatalogError("Catalog factory data does not match contract version 1.", 409) from None
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,79}", factory["key"]):
            raise CatalogError("Unsafe catalog factory key.", 409)
        if factory["key"] in names or (factory["prefix"], factory["region"]) in names:
            raise CatalogError("Duplicate factory key or prefix/region identity.", 409)
        names.update((factory["key"], (factory["prefix"], factory["region"])))
        factory_configuration._region(factory["region"])
        if factory["id"] not in document["configurations"]:
            raise CatalogError("Factory configuration is missing.", 409)
        config = document["configurations"][factory["id"]]
        if not isinstance(config, dict) or set(config) != {"factory", "scale_sets", "projects"} or any(
                not isinstance(config[name], dict) for name in config):
            raise CatalogError("Catalog configuration records are malformed.", 409)
        per_factory, numbers, env_suffixes = {}, set(), set()
        for entity in [factory, *factory["scale_sets"], *factory["projects"]]:
            if entity["id"] in identifiers:
                raise CatalogError("Stable catalog IDs must be globally unique.", 409)
            if str(UUID(entity["id"])) != entity["id"]:
                raise CatalogError("Catalog IDs must use canonical UUID spelling.", 409)
            identifiers.add(entity["id"])
        for scale in factory["scale_sets"]:
            if any(str(UUID(scale[key])) != scale[key] for key in ("subscription_id", "tenant_id")):
                raise CatalogError("Catalog tenant and subscription IDs must use canonical UUID spelling.", 409)
            if subscription_tenants.setdefault(scale["subscription_id"], scale["tenant_id"]) != scale["tenant_id"]:
                raise CatalogError("A physical subscription cannot be assigned to conflicting tenants.", 409)
            pair = (scale["environment"], scale["suffix"])
            if pair in env_suffixes:
                raise CatalogError("Environment/suffix must be unique within a factory.", 409)
            env_suffixes.add(pair)
            target = (scale["subscription_id"].lower(), factory["prefix"], factory["region"],
                      scale["environment"], scale["suffix"])
            if target in physical_targets:
                raise CatalogError("One writer is allowed per physical Azure target.", 409)
            physical_targets.add(target)
            per_factory[scale["id"]] = scale
            if capacity and scale["network"]["max_projects"] > allocator_capacity(scale["network"]):
                raise CatalogError("Configured project capacity exceeds the current aligned allocator; /18 fits 7, not 8 full profiles.", 409)
            for resource in scale["owned_resource_ids"]:
                if resource.lower() in resources:
                    raise CatalogError("Resource ownership cannot be shared between scale sets.", 409)
                resources.add(resource.lower())
        counts = {}
        project_keys = set()
        for project in factory["projects"]:
            if not re.fullmatch(r"[a-z][a-z0-9-]{1,79}", project["key"]):
                raise CatalogError("Unsafe catalog project key.", 409)
            if project["key"] in project_keys:
                raise CatalogError("Readable project keys must be unique within a factory.", 409)
            project_keys.add(project["key"])
            environments = set()
            for placement in project["placements"]:
                scale = per_factory.get(placement["scale_set_id"])
                env = placement["environment"]
                if not scale or scale["environment"] != env or env in environments:
                    raise CatalogError("Project placements require one matching scale set per environment.", 409)
                environments.add(env)
                uniqueness = (scale["id"], project["number"])
                if uniqueness in numbers:
                    raise CatalogError("Project number conflicts in the selected physical scope.", 409)
                numbers.add(uniqueness)
                counts[scale["id"]] = counts.get(scale["id"], 0) + 1
        for scale_id, count in counts.items():
            if count > per_factory[scale_id]["network"]["max_projects"]:
                raise CatalogError("Project placements exceed configured scale-set capacity.", 409)
        if set(config["scale_sets"]) != set(per_factory) or set(config["projects"]) != {
                project["id"] for project in factory["projects"]}:
            raise CatalogError("Catalog definitions and their configuration snapshots disagree.", 409)


def load_document(root):
    document = read_json(root / CATALOG_PATH)
    validate_document(document, capacity=False)
    return document


def binding_path(root, factory, route):
    return ordinary(root / "config-wizard" / "factories" / factory["key"] / "orchestrators" / (route + ".json"))


def _binding_hash(path):
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise CatalogError("A binding must be a bounded ordinary file.", 409)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_local_binding(root, document, factory, binding):
    proposed = {}
    for target in binding["targets"]:
        scale = select_scale(factory, target["scale_set_id"])
        if scale["orchestrator"] != binding["orchestrator"]:
            raise CatalogError("Binding route must match the explicitly selected scale-set writer.", 409)
        for resource in target["resource_group_ids"]:
            if resource.split("/")[2].lower() != scale["subscription_id"].lower():
                raise CatalogError("Writable binding groups must belong to the selected scale-set subscription.", 409)
            if resource.lower() in proposed:
                raise CatalogError("One physical resource group cannot have multiple scale-set writers.", 409)
            proposed[resource.lower()] = scale["id"]
    destination = binding_path(root, factory, binding["orchestrator"])
    for other in document["factories"]:
        for scale in other["scale_sets"]:
            if any(proposed.get("/".join(resource.split("/")[:5]).lower(), scale["id"]) != scale["id"]
                   for resource in scale["owned_resource_ids"]):
                raise CatalogError("A writable group already belongs to another registered scale-set owner.", 409)
        for route in ("ado", "gha"):
            path = binding_path(root, other, route)
            if path == destination or not path.exists():
                continue
            try:
                existing = RuntimeBinding.model_validate(read_json(path)).model_dump(mode="json")
            except ValidationError:
                raise CatalogError("Another local binding is malformed; repair it before assigning physical writers.", 409) from None
            if any(resource.lower() in proposed for target in existing["targets"] for resource in target["resource_group_ids"]):
                raise CatalogError("A physical target already has another configured writer; reconcile enrollment rather than duplicating it.", 409)
    return destination


def source_revision(root):
    if has_catalog(root):
        document = load_document(root)
        bindings = {}
        for factory in document["factories"]:
            for route in ("ado", "gha"):
                path = binding_path(root, factory, route)
                bindings[str(path)] = _binding_hash(path)
            for scale in factory["scale_sets"]:
                path = ordinary(root / "config-wizard" / "factories" / factory["key"] / "scalesets"
                                / scale["environment"] / scale["suffix"] / "deployment_parameters.dpapi")
                if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
                    raise CatalogError("Protected deployment parameters exceed the supported size.", 409)
                bindings[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return digest({"catalog": document, "bindings": bindings})
    return digest(_legacy_files(root))


def target_revision(root, factory_id):
    document = load_document(root)
    factory = select_factory(document, factory_id)
    bindings = {}
    for route in ("ado", "gha"):
        path = binding_path(root, factory, route)
        bindings[route] = _binding_hash(path)
    for scale in factory["scale_sets"]:
        path = ordinary(root / "config-wizard" / "factories" / factory["key"] / "scalesets"
                        / scale["environment"] / scale["suffix"] / "deployment_parameters.dpapi")
        if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
            raise CatalogError("Protected deployment parameters exceed the supported size.", 409)
        bindings[scale["id"]] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    ownership = {key: value for key, value in document.get("ownership_evidence", {}).items()
                 if value.get("owner", {}).get("factory_id") == factory["id"]}
    return digest({"factory": factory, "configuration": document["configurations"][factory["id"]],
                   "bindings": bindings, "ownership_evidence": ownership})


def summary(root, document=None):
    warnings = []
    if document is None:
        if has_catalog(root):
            document = load_document(root)
        else:
            try:
                document = legacy_document(root)
            except CatalogError as exc:
                document = {"factories": []}
                warnings.append(str(exc))
    mode = "catalog" if has_catalog(root) else "legacy"
    if mode == "legacy":
        warnings.append("Legacy configuration is unchanged. Explicit migration is required for catalog lifecycle actions.")
    factories = copy.deepcopy(document["factories"])
    for factory in factories:
        factory["bindings"] = []
        if not factory.get("aifactory_version"):
            warnings.append(factory["key"] + ": saved AI Factory version is unresolved; an explicit runtime version is required.")
        if mode != "catalog":
            continue
        for route in ("ado", "gha"):
            path = binding_path(root, factory, route)
            if not path.exists():
                continue
            state = {"orchestrator": route, "configuration": None, "error": None, "verified": False}
            try:
                binding = RuntimeBinding.model_validate(read_json(path)).model_dump(mode="json")
                if binding["orchestrator"] != route:
                    raise CatalogError("Binding file and declared orchestrator disagree.", 409)
                state["configuration"] = binding
            except (ValidationError, CatalogError):
                state["error"] = "Stored binding is malformed; review and replace it through configure-binding."
                warnings.append(factory["key"] + ": " + state["error"])
            factory["bindings"].append(state)
    return CatalogSummary(contract_version=1, mode=mode, revision=source_revision(root),
                          factories=factories, warnings=warnings,
                          requires_selection=len(document["factories"]) != 1).model_dump(mode="json")


def select_factory(document, factory_id):
    matches = [factory for factory in document["factories"] if factory["id"] == str(factory_id)]
    if len(matches) != 1:
        raise CatalogError("Select an exact registered factory ID; refresh the catalog.", 409)
    return matches[0]


def select_scale(factory, scale_set_id):
    matches = [scale for scale in factory["scale_sets"] if scale["id"] == str(scale_set_id)]
    if len(matches) != 1:
        raise CatalogError("Select an exact scale set belonging to this factory.", 409)
    return matches[0]


def catalog_scope(folder, factory_id=None, scale_set_id=None):
    root = root_folder(str(folder))
    document = load_document(root)
    if factory_id is None:
        raise CatalogError("This is a catalog root. Select an explicit factory ID through the catalog API; legacy root scope is not substituted.", 409)
    factory = select_factory(document, factory_id)
    scales = [select_scale(factory, scale_set_id)] if scale_set_id else factory["scale_sets"]
    subscriptions, tenants, targets = {}, {}, []
    for scale in scales:
        env, subscription, tenant = scale["environment"], scale["subscription_id"], scale["tenant_id"]
        if env in subscriptions:
            raise CatalogError("Multiple scale sets exist for this environment; select one exact scale-set ID.", 409)
        if subscription in tenants and tenants[subscription] != tenant:
            raise CatalogError("Subscription tenant ownership is inconsistent.", 409)
        subscriptions[env], tenants[subscription] = subscription, tenant
        targets.append({"factory_id": factory["id"], "scale_set_id": scale["id"], "environment": env,
                        "subscription_id": subscription, "region": factory["region"],
                        "location_suffix": wizard.azure_region_suffixes().get(factory["region"], ""),
                        "prefix": factory["prefix"], "suffix": "-" + scale["suffix"], "project_suffix": ""})
    return {"subscriptions": subscriptions, "subscription_ids": sorted(tenants), "tenant_ids": sorted(set(tenants.values())),
            "subscription_tenants": tenants, "monitoring_regions": [factory["region"]], "monitoring_targets": targets}


def commit_document(root, document, expected_revision=None):
    validate_document(document)
    for factory in document["factories"]:
        factory["version_ref"] = CatalogFactory.model_validate(factory).version_ref
    previous = load_document(root) if has_catalog(root) else {"factories": [], "configurations": {}}
    previous_factories = {factory["id"]: factory for factory in previous["factories"]}
    generation = document["generation"] = str(uuid4())
    serialized = encode(document)
    if len(serialized) > 16 * 1024 * 1024:
        raise CatalogError("Catalog configuration exceeds its bounded storage capacity; no catalog changes were committed.", 409)
    # catalog.json is the sole authoritative commit point. Named files are human-readable
    # projections, never read as transaction inputs; interrupted projection writes cannot switch scope.
    for factory in document["factories"]:
        base = root / "config-wizard" / "factories" / factory["key"]
        config = document["configurations"][factory["id"]]
        old_factory = previous_factories.get(factory["id"])
        old_config = previous["configurations"].get(factory["id"], {})
        if old_factory == factory and old_config == config:
            continue
        if old_factory is None and base.exists():
            entry = ordinary(base / "factory_state.json")
            if not entry.is_file() or read_json(entry).get("id") != factory["id"]:
                raise CatalogError("The generated factory destination is now occupied; prepare again rather than overwrite it.", 409)
        _projection(base / "factory_state.json", {"generation": generation, **factory,
                                                  "settings": config["factory"]})
        old_scales = {scale["id"]: scale for scale in (old_factory or {}).get("scale_sets", [])}
        for scale in factory["scale_sets"]:
            if old_scales.get(scale["id"]) == scale and old_config.get("scale_sets", {}).get(scale["id"]) == config["scale_sets"].get(scale["id"]):
                continue
            _projection(base / "scalesets" / scale["environment"] / scale["suffix"] / "scaleset_state.json",
                        {"generation": generation, **scale, "settings": config["scale_sets"].get(scale["id"], {})})
        old_projects = {project["id"]: project for project in (old_factory or {}).get("projects", [])}
        for project in factory["projects"]:
            if old_projects.get(project["id"]) == project and old_config.get("projects", {}).get(project["id"]) == config["projects"].get(project["id"]):
                continue
            target = base / "projects" / project["key"]
            _projection(target / "project_state.json", {"generation": generation, **project,
                        "settings": config["projects"].get(project["id"], {})})
            _projection(target / "placements.json", {"generation": generation, "project_id": project["id"],
                                                    "placements": project["placements"]})
    if expected_revision is not None and source_revision(root) != expected_revision:
        raise CatalogError("Source changed while writing projections; catalog activation was not committed.", 409)
    atomic_write(root / CATALOG_PATH, serialized)


def _projection(path, value):
    ordinary(path)
    if path.exists():
        previous = read_json(path)
        identity_key = "id" if "id" in value else "project_id"
        if previous.get(identity_key) != value.get(identity_key):
            raise CatalogError("A generated catalog projection is occupied by another identity; no file was overwritten.", 409)
        if {key: val for key, val in previous.items() if key != "generation"} == {
                key: val for key, val in value.items() if key != "generation"}:
            return
    atomic_write(path, encode(value))


def _available_key(root, key):
    for index in range(1, 1001):
        candidate = key if index == 1 else f"{key}-{index}"
        path = ordinary(root / "config-wizard" / "factories" / candidate)
        if not path.exists():
            return candidate
    raise CatalogError("No unoccupied internal factory key is available; inspect prior draft directories.", 409)


def _rebind(factory, config, prefix, region, include_projects, scale_id=None):
    result, settings = copy.deepcopy(factory), copy.deepcopy(config)
    result.update(id=str(uuid4()), prefix=prefix, region=region, key=f"{prefix.rstrip('-')}-{region}", status="draft")
    selected = [ss for ss in result["scale_sets"] if scale_id is None or ss["id"] == str(scale_id)]
    if scale_id and not selected:
        raise CatalogError("Clone source scale set is not registered in the selected factory.", 409)
    mapping = {ss["id"]: str(uuid4()) for ss in selected}
    result["scale_sets"] = selected
    settings["factory"] = _settings(settings["factory"], clone=True)
    settings["factory"].update(admin_aifactoryPrefixRG=prefix, admin_location=region,
                               admin_locationSuffix=wizard.azure_region_suffixes().get(region, ""))
    settings["scale_sets"] = {mapping[ss["id"]]: _settings(config["scale_sets"].get(ss["id"], {}), clone=True)
                              for ss in selected}
    for scale in selected:
        scale.update(id=mapping[scale["id"]], status="draft", owned_resource_ids=[])
    projects, project_settings = [], {}
    if include_projects == "all":
        for project in result["projects"]:
            project["placements"] = [
                {**placement, "scale_set_id": mapping[placement["scale_set_id"]]}
                for placement in project["placements"] if placement["scale_set_id"] in mapping]
            if not project["placements"]:
                continue
            old = project["id"]
            project.update(id=str(uuid4()), status="draft")
            project_settings[project["id"]] = _settings(config["projects"].get(old, {}), clone=True)
            projects.append(project)
    result["projects"], settings["projects"] = projects, project_settings
    for state in [*settings["scale_sets"].values(), *settings["projects"].values()]:
        state.update(admin_aifactoryPrefixRG=prefix, admin_location=region,
                     admin_locationSuffix=wizard.azure_region_suffixes().get(region, ""))
    return result, settings


class CatalogService:
    def __init__(self, runtime=None, clock=time.time):
        self.clock = clock
        if runtime is None:
            from src.catalog_runtime import CatalogRuntime
            runtime = CatalogRuntime()
        self.runtime = runtime

    def list(self, folder):
        root = root_folder(folder)
        if has_catalog(root):
            with catalog_lock(root):
                return summary(root)
        return summary(root)

    def prepare(self, body, owner):
        request = CatalogPrepare.model_validate(body).model_dump(mode="json")
        root = root_folder(request["folder"])
        with catalog_lock(root):
            revision = source_revision(root)
            if request["expected_revision"] and request["expected_revision"] != revision:
                raise CatalogError("The selected catalog revision changed; refresh before preparing.", 409)
            blockers, warnings, effects = [], [], []
            target, updated, runtime_payload = None, None, None
            action = request["action"]
            try:
                if action == "migrate":
                    if has_catalog(root):
                        raise CatalogError("This root already has a catalog; migration cannot overwrite it.", 409)
                    updated = legacy_document(root)
                    # Migration preserves all project definitions and their explicit ownership.
                    target = updated["factories"][0]
                    target["key"] = _available_key(root, target["key"])
                    validate_document(updated)
                    effects = ["Register existing factory and project identities without moving or modifying legacy files.",
                               "Write a revision-checked snapshot backup before activating the opt-in catalog."]
                    warnings = ["Migration copies configuration, not Azure ownership evidence. Delete remains blocked until ownership is verified."]
                elif action == "create-factory":
                    if has_catalog(root):
                        updated = copy.deepcopy(load_document(root))
                    else:
                        if any(value is not None for value in _legacy_files(root).values()):
                            raise CatalogError("Existing legacy inputs require explicit migration before creating another factory.", 409)
                        updated = {"schema_version": 1, "generation": "new", "factories": [], "configurations": {}}
                    prefix, region = request["target_prefix"], request["target_region"]
                    factory_configuration._region(region)
                    version = request["aifactory_version"] or request["version_ref"] or release_version.DEFAULT_VERSION
                    target = {"id": str(uuid4()), "key": _available_key(root, f"{prefix.rstrip('-')}-{region}"),
                              "prefix": prefix, "region": region, "default_orchestrator": request["scale_sets"][0]["orchestrator"],
                              "aifactory_version": version, "version_ref": release_version.normalize(version),
                              "status": "draft", "scale_sets": [
                                  {**scale, "id": str(uuid4()), "status": "draft", "owned_resource_ids": []}
                                  for scale in request["scale_sets"]], "projects": []}
                    state = _settings(wizard.new_configuration_defaults(), clone=True)
                    state.update(admin_aifactoryPrefixRG=prefix, admin_location=region,
                                 admin_locationSuffix=wizard.azure_region_suffixes().get(region, ""))
                    updated["factories"].append(target)
                    updated["configurations"][target["id"]] = {
                        "factory": state, "scale_sets": {scale["id"]: {} for scale in target["scale_sets"]}, "projects": {}}
                    validate_document(updated)
                    effects = ["Create a new local factory identity with no projects and only the explicitly listed draft scale sets.",
                               "Generate internal folders under the selected root; never rewrite root variables.json.",
                               "No Azure subscriptions, resources, repositories, bindings or authentication are created."]
                    warnings = ["Defaults are configuration drafts, not verified deployment readiness; complete settings and enrollment before deploying."]
                else:
                    if not has_catalog(root):
                        raise CatalogError("Explicitly migrate this legacy root before catalog lifecycle operations.", 409)
                    updated = copy.deepcopy(load_document(root))
                    factory = select_factory(updated, request["factory_id"])
                    target = factory
                    if action == "configure-settings":
                        from src import catalog_settings
                        target = catalog_settings.apply(updated, request)
                        effects = ["Save only the selected factory, scale-set or project settings in the catalog.",
                                   "Keep source/root variable files, other scopes and Azure resources unchanged.",
                                   "Validate the effective configuration and exact published parameters again before deployment."]
                        warnings = ["Secrets and immutable identity/placement fields cannot be changed here.",
                                    "Changing settings does not deploy resources or update an existing job's frozen inputs."]
                    elif action == "add-project":
                        definition = request["project"]
                        keys = {project["key"] for project in factory["projects"]}
                        base_key = key = "project-" + definition["number"]
                        counter = 1
                        while key in keys or ordinary(root / "config-wizard" / "factories" / factory["key"] / "projects" / key).exists():
                            counter += 1
                            if counter > 10000:
                                raise CatalogError("No available readable project key; reconcile retained project drafts.", 409)
                            key = base_key + "-" + str(counter)
                        project = {**definition, "id": str(uuid4()), "key": key, "status": "draft"}
                        factory["projects"].append(project)
                        settings = {"project_number_000": project["number"], "projectName": project["display_name"]}
                        updated["configurations"][factory["id"]]["projects"][project["id"]] = settings
                        effects = ["Create a new logical project UUID and draft configuration with only the explicitly selected placements.",
                                   "Inherit factory and per-scale-set configuration without overriding their tenant, networking or shared-resource references.",
                                   "Validate project-number uniqueness and configured allocator capacity in every selected physical scale set.",
                                   "No Azure resource or deployment is created; no other project's identity or placements are changed."]
                    elif action == "add-project-placements":
                        project = next((item for item in factory["projects"] if item["id"] == request["project_id"]), None)
                        if project is None:
                            raise CatalogError("Select an exact project belonging to this factory.", 409)
                        previous = {placement["environment"]: placement["scale_set_id"] for placement in project["placements"]}
                        additions = []
                        for placement in request["placements"]:
                            existing = previous.get(placement["environment"])
                            if existing and existing != placement["scale_set_id"]:
                                raise CatalogError("An existing environment placement cannot be silently retargeted; registered configuration and ownership must be retained.", 409)
                            if not existing:
                                previous[placement["environment"]] = placement["scale_set_id"]
                                additions.append(placement)
                        if not additions:
                            raise CatalogError("The selected placements already exist; no configuration change is required.", 409)
                        project["placements"].extend(additions)
                        project["status"] = "draft"
                        effects = ["Add only the reviewed placements to the existing logical project identity.",
                                   "Reject physical project-number conflicts, mismatched environments and insufficient scale-set capacity.",
                                   "Existing placements are retained; this action neither promotes Azure resources nor changes live deployments."]
                    elif action == "configure-binding":
                        _validate_local_binding(root, updated, factory, request["binding"])
                        effects = ["Replace the complete local " + request["binding"]["orchestrator"] + " binding with the reviewed typed configuration.",
                                   "Save only exact scale-set and resource-group references; this does not establish Azure ownership or deletion authority.",
                                   "No lock storage, enrollment, authentication, pipeline or remote resource is provisioned."]
                        warnings = ["Binding saved does not mean verified. Runtime preparation must verify live enrollment, exclusive writer, identity and scope."]
                    elif action == "clone":
                        prefix = request["target_prefix"] or factory["prefix"]
                        region = request["target_region"] or factory["region"]
                        factory_configuration._region(region)
                        if (prefix, region) == (factory["prefix"], factory["region"]):
                            raise CatalogError("Clone needs a different prefix and/or region.", 409)
                        target, config = _rebind(factory, updated["configurations"][factory["id"]], prefix, region,
                                                 request["include_projects"], request["scale_set_id"])
                        version = request["aifactory_version"] or request["version_ref"]
                        if version is not None:
                            target.update(aifactory_version=version, version_ref=release_version.normalize(version))
                        target["key"] = _available_key(root, target["key"])
                        updated["factories"].append(target)
                        updated["configurations"][target["id"]] = config
                        effects = ["Create a new factory identity and draft scale-set settings in an internal generated folder.",
                                   f"Copy {'all selected' if request['include_projects'] == 'all' else 'no'} project definitions with rebound placements.",
                                   "Clear resource ownership, run status, secrets and external resource references."]
                        warnings = ["Review copied network addresses and per-instance subscriptions before deployment.",
                                    "Clone does not copy live writer/lock enrollment; explicitly enroll each new physical target."]
                    elif action == "create-scale-set":
                        if request["version_ref"] is not None and (
                                factory.get("aifactory_version") is None
                                or release_version.normalize(request["version_ref"]) != release_version.normalize(factory["aifactory_version"])):
                            raise CatalogError("New scale sets inherit the saved factory version; the supplied version_ref cannot change it.", 409)
                        for item in request["scale_sets"]:
                            destination = ordinary(root / "config-wizard" / "factories" / factory["key"]
                                                   / "scalesets" / item["environment"] / item["suffix"])
                            if destination.exists():
                                raise CatalogError("The selected environment/suffix already has an internal draft directory; inspect it or select a new suffix.", 409)
                            scale = {**item, "id": str(uuid4()), "status": "draft", "owned_resource_ids": []}
                            target["scale_sets"].append(scale)
                            updated["configurations"][target["id"]]["scale_sets"][scale["id"]] = {}
                        effects = ["Add only the explicitly listed environments and subscriptions as draft scale sets.",
                                   "No Stage/Prod scale sets or Azure subscriptions are implicitly created."]
                    else:
                        runtime_payload = self.runtime.prepare(root, request, updated)
                        blockers.extend(runtime_payload.get("blockers", []))
                        warnings.extend(runtime_payload.get("warnings", []))
                        effects.extend(runtime_payload.get("effects", []))
                    if action not in RUNTIME_ACTIONS:
                        validate_document(updated)
            except (TicketError, factory_configuration.ConfigurationError) as exc:
                blockers.append(str(exc))
            if source_revision(root) != revision:
                raise CatalogError("Configuration changed during prepare; refresh and prepare again.", 409)
            if action not in RUNTIME_ACTIONS:
                warnings.append(CONFIG_WARNING)
            confirmation_id = str(uuid4())
            expires = min(self.clock() + 600, (runtime_payload or {}).get("expires", self.clock() + 600))
            preview = {"contract_version": 1, "confirmation_id": confirmation_id, "can_execute": not blockers,
                       "summary": f"{action}: {target['key'] if target else 'selected factory'}", "effects": effects,
                       "warnings": warnings, "blockers": blockers, "expires_at": utc(expires),
                       "source_revision": revision, "operation_mode": "runtime" if action in RUNTIME_ACTIONS else "configuration",
                       "target": target, "inventory": (runtime_payload or {}).get("inventory", []),
                       "binding": request["binding"],
                       "source_version": ({"aifactory_version": request["version_ref"], **{
                           key: runtime_payload["version"][key] for key in
                           ("requested_version", "branch", "resolved_ref")}} if runtime_payload else None)}
            payload = {"request": request, "preview": preview, "document": updated, "runtime": runtime_payload}
            with database(root) as db:
                db.execute("INSERT INTO confirmations(id,owner,expires,revision,payload) VALUES (?,?,?,?,?)",
                           (confirmation_id, owner, expires, revision, json.dumps(payload)))
            return preview

    def confirm(self, folder, confirmation_id, owner):
        root = root_folder(folder)
        with catalog_lock(root), database(root) as db:
            row = db.execute("SELECT * FROM confirmations WHERE id=? AND owner=?", (str(confirmation_id), owner)).fetchone()
            if not row:
                raise CatalogError("Confirmation not found for this authenticated caller.", 404)
            payload = json.loads(row["payload"])
            if payload.get("kind") == "catalog-parameters-v1":
                raise CatalogError("Use the parameter configuration confirmation endpoint.", 409)
            if row["consumed"] or row["expires"] <= self.clock():
                raise CatalogError("Confirmation is expired or already used; prepare again.", 409)
            if not payload["preview"]["can_execute"]:
                raise CatalogError("Resolve every preview blocker before confirming.", 409)
            if source_revision(root) != row["revision"]:
                raise CatalogError("Reviewed source revision changed; prepare again.", 409)
            request = payload["request"]
            if request["action"] in RUNTIME_ACTIONS:
                job = self.runtime.confirm(root, payload, owner, db)
                db.commit()
                return {"contract_version": 1, "catalog": None, "job": job}
            if request["action"] == "configure-binding":
                document = load_document(root)
                factory = select_factory(document, request["factory_id"])
                destination = _validate_local_binding(root, document, factory, request["binding"])
                if source_revision(root) != row["revision"]:
                    raise CatalogError("Binding inputs changed before saving; prepare again.", 409)
                atomic_write(destination, encode(request["binding"]))
                db.execute("UPDATE confirmations SET consumed=1 WHERE id=?", (str(confirmation_id),))
                return {"contract_version": 1, "catalog": summary(root), "job": None}
            if request["action"] == "migrate":
                files = _legacy_files(root)
                backup = root / "config-wizard" / "catalog-backups" / str(confirmation_id)
                manifest = {}
                for index, (name, file_hash) in enumerate(files.items()):
                    if file_hash is not None:
                        data = Path(name).read_bytes()
                        if hashlib.sha256(data).hexdigest() != file_hash:
                            raise CatalogError("Legacy input changed during backup; prepare again.", 409)
                        # Backups may contain old credentials, so protect their content for the OS user.
                        from src.deployment_config import protect
                        atomic_write(backup / f"{index:04}.dpapi", protect(data))
                        manifest[name] = {"sha256": file_hash, "backup": f"{index:04}.dpapi"}
                atomic_write(backup / "manifest.json", encode({"source_revision": row["revision"], "files": manifest}))
                if source_revision(root) != row["revision"]:
                    raise CatalogError("Legacy source changed during backup; migration was not activated.", 409)
            commit_document(root, payload["document"], expected_revision=row["revision"])
            db.execute("UPDATE confirmations SET consumed=1 WHERE id=?", (str(confirmation_id),))
            return {"contract_version": 1, "catalog": summary(root), "job": None}

    def jobs(self, folder, owner):
        return self.runtime.jobs(root_folder(folder), owner)

    def job(self, folder, job_id, owner):
        return self.runtime.job(root_folder(folder), str(job_id), owner)
