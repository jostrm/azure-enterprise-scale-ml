"""Configuration-only factory workflows shared by desktop clients and the API."""

from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

import yaml

from src import wizard
from src.operations import LocalFactoryDiscovery, azure_region_catalog


ConfigurationKind = Literal["factory", "scale-set", "clone"]
FACTORY_STATE = Path("config-wizard") / "factory_state.json"
ESSENTIAL_KEYS = (
    "orchestrator", "admin_aifactoryPrefixRG", "admin_aifactorySuffixRG",
    "admin_location", "admin_locationSuffix", "tenantId",
    "dev_sub_id", "test_sub_id", "prod_sub_id",
)
NETWORK_KEYS = (
    "network_mode", "allowPublicAccessWhenBehindVnet", "enablePublicGenAIAccess",
    "enablePublicAccessWithPerimeter", "centralDnsZoneByPolicyInHub",
    "enableAIFactoryHub",
    "privDnsSubscription_param", "privDnsResourceGroup_param",
    "vnetResourceGroup_param", "vnetNameFull_param", "disableAgentNetworkInjection",
    "policyExemptionAssignmentIds", "policyExemptionDefinitionReferenceIds",
    "enableAISearchSharedPrivateLink", "vnet_resource_group_base", "vnet_name_base",
    "subnet_common_base", "BYO_subnets", "network_env_dev", "network_env_stage",
    "network_env_prod", "subnetCommon", "subnetCommonScoring",
    "subnetCommonPowerbiGw", "subnetProjGenAI", "subnetProjAKS", "subnetProjAKS2",
    "subnetProjACA", "subnetProjACA2", "subnetProjWebapp",
    "subnetProjDatabricksPublic", "subnetProjDatabricksPrivate",
)
FIELD_KEYS = tuple(dict.fromkeys(
    key for key in (*ESSENTIAL_KEYS, *wizard.SCALESET_KEYS, *NETWORK_KEYS)
    if not key.startswith("_") and key in wizard.DEFAULT_STATE
))
_REFERENCE_KEYS = {
    "technical_admins_ad_object_id", "BYOContributorRoleID",
    "azure_machinelearning_sp_oid", "databricksOID",
    "privDnsSubscription_param", "privDnsResourceGroup_param",
    "vnetResourceGroup_param", "vnetNameFull_param", "commonResourceGroup_param",
    "datalakeName_param", "kvNameFromCOMMON_param", "cmkKeyVersion",
}
_MESSAGE = (
    "Configuration only; no Azure resources, repositories or pipelines are changed. "
    "Review copied network addresses, subnet names and service connections before "
    "deployment; source resource references and destructive actions are cleared "
    "during preparation."
)


class ConfigurationError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _region(value: str) -> str:
    if not isinstance(value, str) or value not in {
        item["name"] for item in azure_region_catalog()
    }:
        raise ConfigurationError("target_region must be a known Azure geographic region (not global)")
    return value


def _folder(value: str | None, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} is required")
    value = value.strip()
    windows = PureWindowsPath(value)
    if any(part == ".." for part in windows.parts) or any(
        re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((" ", "."))
        or re.match(r"^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", part, re.I)
        for part in windows.parts if part != windows.anchor
    ):
        raise ConfigurationError(f"{field} contains an unsafe path component")
    path = Path(value).expanduser()
    if not path.is_absolute() or value.startswith(("\\\\?\\", "\\\\.\\")):
        raise ConfigurationError(f"{field} must be an absolute, ordinary folder path")
    # Do not follow user-controlled links into another project during persistence.
    for component in (path, *path.parents):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ConfigurationError(f"{field} must not contain symbolic links or junctions")
    return path.resolve()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ConfigurationError(f"Malformed configuration: {path}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration must be a JSON object: {path}")
    return value


def _default_state() -> dict[str, Any]:
    return {key: value for key, value in wizard.new_configuration_defaults().items()
            if key in wizard.DEFAULT_STATE}


def _schema_state(values: dict[str, Any]) -> dict[str, Any]:
    values = wizard.hub_configuration(values)
    try:
        wizard.require_hub_configuration(values)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    state = _default_state()
    for key, value in values.items():
        if key not in state:
            continue
        if not isinstance(value, (str, bool, int, float)) and value is not None:
            raise ConfigurationError(f"{key} must be a scalar configuration value")
        if isinstance(state[key], bool):
            if value not in (True, False, "true", "false"):
                raise ConfigurationError(f"{key} must be boolean")
            state[key] = value is True or value == "true"
        else:
            state[key] = str(value).lower() if isinstance(value, bool) else (
                "" if value is None else str(value)
            )
    if state["_hub_topology"] not in ("", "standalone", "own-hub", "external-hub"):
        raise ConfigurationError("_hub_topology must be standalone, own-hub, external-hub or empty")
    return state


def _load_source(source_folder: str | None) -> tuple[Path, dict[str, Any], Path]:
    folder = _folder(source_folder, "source_folder")
    if not folder.is_dir():
        raise ConfigurationError(f"Source folder not found: {folder}", 404)
    if (folder / "config-wizard" / "catalog.json").exists():
        raise ConfigurationError("Catalog roots require an explicit factory ID through the catalog API; legacy source selection is not substituted.", 409)
    factory_path = folder / FACTORY_STATE
    imported: dict[str, Any] = {}
    if factory_path.exists():
        imported = _json_object(factory_path)
        route = imported.get("orchestrator")
        source_file = factory_path
    else:
        variables_path = folder / "variables.json"
        if variables_path.exists():
            variables = _json_object(variables_path)
            if not isinstance(variables.get("dev"), dict):
                raise ConfigurationError(f"Configuration must contain a dev object: {variables_path}")
        if variables_path.exists():
            # Setup can review optional placeholders; do not silently clone an older fallback file.
            path, route = str(variables_path), None
        else:
            path, route = wizard._startup_import_candidate(str(folder), {})
        if not path:
            raise ConfigurationError("Source folder has no usable factory configuration")
        source = Path(path)
        source_file = source
        if source.suffix == ".json":
            count = wizard._import_json_to_state(path, imported)
            route = imported.get("orchestrator") or LocalFactoryDiscovery().discover(str(folder))["orchestrator"]
        elif source.name == ".env":
            text = source.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    match = re.fullmatch(r"(?:export\s+)?[A-Z_][A-Z0-9_]*\s*=\s*(.*)", line)
                    if not match:
                        raise ConfigurationError(f"Malformed environment configuration: {path}")
                    raw = match.group(1).strip()
                    if raw.startswith(("'", '"')) and raw[0] not in raw[1:]:
                        raise ConfigurationError(f"Unclosed environment value: {path}")
            count = wizard._import_env_to_state(path, imported)
        else:
            try:
                document = yaml.safe_load(source.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ConfigurationError(f"Malformed YAML configuration: {path}") from exc
            if not isinstance(document, dict) or not isinstance(document.get("variables"), dict):
                raise ConfigurationError(f"Configuration must contain variables: {path}")
            count = wizard._import_yaml_to_state(path, imported)
        if not count:
            raise ConfigurationError(f"No recognized configuration fields: {path}")
    for key in ("admin_aifactoryPrefixRG", "admin_aifactorySuffixRG", "admin_location"):
        value = imported.get(key)
        if not isinstance(value, str) or not value.strip() or "<todo>" in value.lower():
            raise ConfigurationError(f"Source configuration requires {key}")
    if route not in ("ado", "gha"):
        raise ConfigurationError("Source configuration requires a valid orchestrator")
    state = _schema_state(imported)
    if wizard.DASHBOARD_KEY not in imported:
        state[wizard.DASHBOARD_KEY] = wizard._current_dashboard_url(str(folder))
    state["orchestrator"] = route
    if "network_mode" not in imported:
        for mode, flags in wizard.NETWORK_MODE_FLAGS.items():
            if all(state.get(key) == value for key, value in flags.items()):
                state["network_mode"] = mode
                break
    return folder, state, source_file


def _configuration_only(state: dict[str, Any], *, clear_references: bool = True) -> None:
    state["_save_folder"] = ""
    state["_also_update_git"] = False
    state["github_new_repo"] = ""
    for key, value in state.items():
        lower = key.lower()
        if lower.startswith(("delete", "update", "clean")) or key in {
            "enableDeleteForDisabledResources", "debugEnableCleaning",
        }:
            state[key] = "false"
        elif key != wizard.DASHBOARD_KEY and clear_references and (key in _REFERENCE_KEYS or "resourceid" in lower or (
            "service_connection" in lower or "_admin_bicep_" in lower
        ) or (isinstance(value, str) and "/subscriptions/" in value.lower())):
            state[key] = ""
    if clear_references:
        state["policyExemptionAssignmentIds"] = "[]"
        state["policyExemptionDefinitionReferenceIds"] = "[]"
        state["byoASEv3"] = "false"
        state["cmk"] = "false"


def _prepare_state(
    kind: ConfigurationKind, target_region: str, source_folder: str | None = None,
) -> tuple[dict[str, Any], Path | None, dict[str, Any] | None, Path | None]:
    if kind not in ("factory", "scale-set", "clone"):
        raise ConfigurationError("kind must be factory, scale-set or clone")
    region = _region(target_region)
    state = _default_state()
    source_path, source, source_file = None, None, None
    if kind != "factory":
        source_path, source, source_file = _load_source(source_folder)
        state = copy.deepcopy(source)
        if kind == "clone" and state["admin_location"] == region:
            raise ConfigurationError("Clone target must differ from the source primary region")
    else:
        for key in ("admin_aifactoryPrefixRG", "tenantId", "dev_sub_id", "test_sub_id", "prod_sub_id"):
            state[key] = ""
    _configuration_only(state)
    if kind in ("factory", "clone"):
        state[wizard.DASHBOARD_KEY] = ""
    state["admin_location"] = region
    state["admin_locationSuffix"] = wizard.azure_region_suffixes().get(region, "")
    state["admin_aifactorySuffixRG"] = ""
    return state, source_path, source, source_file


def _preparation_message(
    target_region: str, source: dict[str, Any] | None, source_file: Path | None,
) -> str:
    origin = (
        f"Loaded source configuration from {source_file} "
        f"(primary region: {source['admin_location']})."
        if source is not None else "Prepared a new factory from Python template defaults."
    )
    return f"{origin} Target region: {target_region}. {_MESSAGE}"


def prepare_configuration(
    kind: ConfigurationKind, target_region: str, source_folder: str | None = None,
) -> dict[str, Any]:
    state, _, source, source_file = _prepare_state(kind, target_region, source_folder)
    return {
        "state": state, "field_keys": [
            key for key in FIELD_KEYS
            if kind != "scale-set" or key not in ("orchestrator", "admin_aifactoryPrefixRG")
        ],
        "message": _preparation_message(target_region, source, source_file),
    }


def _validate_identity(state: dict[str, Any], region: str) -> None:
    scaling_issues = wizard.scaling_validation_issues(state)
    if scaling_issues:
        raise ConfigurationError("; ".join(issue["message"] for issue in scaling_issues))
    if state.get("admin_location") != region:
        raise ConfigurationError("admin_location must match target_region")
    if state.get("orchestrator") not in ("ado", "gha"):
        raise ConfigurationError("orchestrator must be ado or gha")
    patterns = {
        "admin_aifactoryPrefixRG": r"[a-z0-9][a-z0-9-]{0,39}",
        "admin_aifactorySuffixRG": r"-?[a-z0-9][a-z0-9-]{0,19}",
        "admin_locationSuffix": r"[a-z][a-z0-9]{1,9}",
    }
    for key, pattern in patterns.items():
        if not re.fullmatch(pattern, state.get(key, "")):
            raise ConfigurationError(f"{key} is required and must be a safe lowercase name")
    for key in ("tenantId", "dev_sub_id", "test_sub_id", "prod_sub_id"):
        value = state.get(key, "")
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
            raise ConfigurationError(f"{key} must be a GUID")
        if uuid.UUID(value).int == 0:
            raise ConfigurationError(f"{key} must be a nonzero GUID")
    if state.get("network_mode") not in wizard.NETWORK_MODE_FLAGS:
        raise ConfigurationError("network_mode must be public, hybrid or private")


def _unique_suffix(folder: Path, source: dict[str, Any], suffix: str) -> None:
    identity = wizard._scaleset_id_from_suffix(suffix).casefold()
    existing = {wizard._scaleset_id_from_suffix(source["admin_aifactorySuffixRG"]).casefold()}
    for path in (folder / "config-wizard" / "scalesets").glob("scaleset_*.json"):
        existing.add(path.stem[len("scaleset_"):].casefold())
        snapshot = _json_object(path)
        if snapshot.get("admin_aifactorySuffixRG"):
            if not isinstance(snapshot["admin_aifactorySuffixRG"], str):
                raise ConfigurationError(f"Malformed scale-set suffix: {path}")
            existing.add(wizard._scaleset_id_from_suffix(snapshot["admin_aifactorySuffixRG"]).casefold())
    if identity in existing:
        raise ConfigurationError("Choose a unique suffix; this scale-set identity already exists in the source factory", 409)


def _ensure_empty(destination: Path) -> None:
    if destination.exists() and (
        not destination.is_dir() or next(destination.iterdir(), None) is not None
    ):
        raise ConfigurationError("Destination already exists and is not an empty folder", 409)


def _write_factory(destination: Path, state: dict[str, Any]) -> str:
    _ensure_empty(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f".{destination.name}.configuration-{uuid.uuid4().hex}"
    stage.mkdir()
    removed_empty = False
    try:
        (stage / FACTORY_STATE).parent.mkdir()
        (stage / FACTORY_STATE).write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        wizard._save_variables_json(state, str(stage))
        wizard._save_scaleset_snapshot(
            state, create_only=True, base_folder=str(stage),
            extra_keys=(*FIELD_KEYS, "_also_update_git"),
        )
        _folder(str(destination), "destination_folder")
        _ensure_empty(destination)
        if destination.exists():
            destination.rmdir()  # Fails safely if another writer added any files.
            removed_empty = True
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
            if removed_empty and not destination.exists():
                destination.mkdir()
    return str(destination / FACTORY_STATE)


def save_configuration(
    kind: ConfigurationKind, target_region: str, destination_folder: str,
    state: dict[str, Any], source_folder: str | None = None,
) -> dict[str, Any]:
    values, source_path, source, source_file = _prepare_state(kind, target_region, source_folder)
    destination = _folder(destination_folder, "destination_folder")
    original_mode = values["network_mode"]
    if "enableAIFactoryHub" not in state and "_hub_topology" in state:
        state = {**state, "enableAIFactoryHub": wizard.hub_configuration(state)["enableAIFactoryHub"]}
    values.update(state)
    values = _schema_state(values)
    _validate_identity(values, target_region)
    if kind == "scale-set":
        for key in ("orchestrator", "admin_aifactoryPrefixRG"):
            if values[key] != source[key]:
                raise ConfigurationError(f"Scale-set {key} must match the source factory")
    if values["network_mode"] != original_mode:
        values.update(wizard.NETWORK_MODE_FLAGS[values["network_mode"]])
    _configuration_only(values, clear_references=False)
    values["_save_folder"] = str(destination)
    if kind != "factory":
        if kind == "clone" and source_path == destination:
            raise ConfigurationError("Clone destination must differ from source_folder", 409)
        if kind == "scale-set" and source_path != destination:
            raise ConfigurationError("Scale-set destination must exactly match source_folder")
        _unique_suffix(source_path, source, values["admin_aifactorySuffixRG"])
    try:
        if kind == "scale-set":
            snapshot_folder = destination / "config-wizard" / "scalesets"
            _folder(str(snapshot_folder), "scale-set snapshot folder")
            path = wizard._save_scaleset_snapshot(
                values, create_only=True, extra_keys=(*FIELD_KEYS, "_also_update_git")
            )
        else:
            path = _write_factory(destination, values)
    except FileExistsError as exc:
        raise ConfigurationError("Configuration already exists; nothing was overwritten", 409) from exc
    return {
        "state": values, "path": path,
        "message": f"Saved local configuration. {_preparation_message(target_region, source, source_file)}",
    }
