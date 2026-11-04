from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from uuid import UUID


def required(values: dict, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip() or "<" in value or "$(" in value:
        raise ValueError(f"Configuration requires a resolved string for '{key}'.")
    return value.strip()


def identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def naming_value(values: dict, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or "<" in value or "$(" in value:
        raise ValueError(f"Configuration requires an explicit resolved '{key}' (empty is allowed).")
    return value


def container_name(value: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value)
            or "--" in value):
        raise ValueError("Invalid private Blob container name.")
    return value


def storage_selection(defaults: dict, selection: dict) -> dict:
    """Root storage defaults, then per-target selection; merge each profile by field."""
    if not isinstance(defaults, dict) or not isinstance(selection, dict):
        raise ValueError("Storage defaults and target selection must be objects.")
    profiles = {}
    merged = {}
    for options in (defaults, selection):
        if "use_common_datalake_storage" in options:
            value = options["use_common_datalake_storage"]
            if type(value) is not bool:
                raise ValueError("use_common_datalake_storage must be a JSON boolean.")
            merged["use_common_datalake_storage"] = value
        if "storage_targets" in options:
            incoming = options["storage_targets"]
            if not isinstance(incoming, dict) or incoming.keys() - {"common", "project"}:
                raise ValueError("storage_targets must contain only common/project profiles.")
            for name, profile in incoming.items():
                if not isinstance(profile, dict) or profile.keys() - {"account_name", "resource_group", "container"}:
                    raise ValueError(f"Invalid storage_targets.{name} profile fields.")
                profiles[name] = {**profiles.get(name, {}), **profile}
    merged.update({key: value for key, value in selection.items()
                   if key not in {"storage_targets", "use_common_datalake_storage"}})
    if profiles:
        merged["storage_targets"] = profiles
    return merged


@dataclass(frozen=True)
class FactoryConfig:
    tenant_id: str
    subscription_id: str
    environment: str
    project_number: str
    resource_group: str
    common_resource_group: str
    account_name: str = ""
    project_name: str = ""
    model_deployment: str = ""
    embedding_deployment: str = ""
    search_name: str = ""
    storage_name: str = ""
    identity_name: str = ""
    storage_resource_group: str = ""
    storage_container: str = ""
    use_common_datalake_storage: bool | None = None

    def __post_init__(self):
        flag = self.use_common_datalake_storage
        if flag is not None:
            if type(flag) is not bool:
                raise ValueError("use_common_datalake_storage must be a JSON boolean.")
            expected = self.common_resource_group if flag else self.resource_group
            if (not isinstance(self.storage_resource_group, str) or not self.storage_resource_group
                    or self.storage_resource_group.lower() != expected.lower()):
                raise ValueError("Selected storage resource group does not match common/project selection.")
            if (not isinstance(self.storage_name, str) or not re.fullmatch(r"[a-z0-9]{3,24}", self.storage_name)
                    or "1001" in self.storage_name):
                raise ValueError("Select an explicit data account, never the 1001 artifact account.")
            if not self.storage_container:
                object.__setattr__(self, "storage_container", "lake3" if flag else "agent-factory")
        if self.storage_container:
            container_name(self.storage_container)

    @classmethod
    def load(cls, variables_path: Path, environment: str = "dev",
             overrides: dict | None = None) -> FactoryConfig:
        document = json.loads(variables_path.read_text(encoding="utf-8-sig"))
        if environment not in {"dev", "test", "prod"}:
            raise ValueError("Environment must be dev, test, or prod.")
        section = environment if environment in document else "stage_prod" if environment in {"test", "prod"} else "dev"
        if section not in document:
            raise ValueError(f"variables.json has no '{environment}' section; no cross-environment fallback.")
        values = document[section]
        if not isinstance(values, dict):
            raise ValueError("The selected variables.json section must be an object.")
        selected = storage_selection({}, overrides if overrides is not None else {})
        tenant_id = str(UUID(required(values, "tenantId")))
        subscription_id = str(UUID(required(values, f"{environment}_sub_id")))
        project_number = required(values, "project_number_000")
        if not re.fullmatch(r"\d{3}", project_number):
            raise ValueError("project_number_000 must be a three-digit string.")
        prefix = naming_value(values, "admin_aifactoryPrefixRG")
        location = required(values, "admin_locationSuffix")
        suffix = required(values, "admin_aifactorySuffixRG")
        project_prefix = naming_value(values, "projectPrefix")
        project_suffix = naming_value(values, "projectSuffix")
        resource_group = selected.get("resource_group") or (
            f"{prefix}{project_prefix}project{project_number}-{location}-{environment}{suffix}{project_suffix}"
        )
        common_group = selected.get("common_resource_group") or (
            values.get("commonResourceGroup_param")
            or f"{prefix}{required(values, 'vnetResourceGroupBase')}-{location}-{environment}{suffix}"
        )
        allowed = {field for field in cls.__dataclass_fields__} - {
            "tenant_id", "subscription_id", "environment", "project_number",
            "resource_group", "common_resource_group",
        }
        profiles = selected.pop("storage_targets", {})
        flag = selected.pop("use_common_datalake_storage", None)
        allowed -= {"use_common_datalake_storage"}
        if flag is not None:
            scope = "common" if flag else "project"
            profile = profiles.get(scope, {})
            account = required(profile, "account_name")
            if not re.fullmatch(r"[a-z0-9]{3,24}", account) or "1001" in account:
                raise ValueError("Select a lowercase data storage account, never the 1001 artifact account.")
            group = required(profile, "resource_group")
            expected = common_group if flag else resource_group
            if group.lower() != expected.lower():
                raise ValueError(f"storage_targets.{scope}.resource_group must match the selected {scope} resource group.")
            normalized = {
                "storage_name": account, "storage_resource_group": group,
                "storage_container": container_name(profile.get("container", "lake3" if flag else "agent-factory")),
            }
            for key, value in normalized.items():
                if key in selected and selected[key] != value:
                    raise ValueError(f"{key} contradicts the selected storage_targets.{scope} profile.")
            selected.update(normalized)
        elif ("storage_resource_group" in selected
              and required(selected, "storage_resource_group").lower() != resource_group.lower()):
            raise ValueError("Cross-group storage requires use_common_datalake_storage and an explicit profile.")
        unknown = selected.keys() - allowed - {"resource_group", "common_resource_group"}
        if unknown:
            raise ValueError(f"Unknown target options: {', '.join(sorted(unknown))}")
        optional = {key: identifier(required(selected, key), key) for key in allowed if key in selected}
        return cls(
            tenant_id, subscription_id, environment, project_number,
            identifier(resource_group, "resource group"), identifier(common_group, "common resource group"),
            use_common_datalake_storage=flag,
            **optional,
        )


@dataclass(frozen=True)
class Target:
    tenant_id: str
    subscription_id: str
    resource_group: str
    common_resource_group: str
    account_name: str
    project_name: str
    project_endpoint: str
    location: str
    model_deployment: str
    embedding_deployment: str
    search_name: str
    storage_name: str
    identity_id: str
    identity_client_id: str
    storage_resource_group: str = ""
    storage_container: str = ""
    use_common_datalake_storage: bool | None = None

    def __post_init__(self):
        flag = self.use_common_datalake_storage
        if flag is not None and type(flag) is not bool:
            raise ValueError("use_common_datalake_storage must be a JSON boolean.")
        expected = self.common_resource_group if flag is True else self.resource_group
        if not isinstance(self.storage_resource_group, str) or not isinstance(self.storage_container, str):
            raise ValueError("Storage resource group and container metadata must be strings.")
        if flag is not None and not self.storage_resource_group:
            raise ValueError("Selected storage metadata requires storage_resource_group.")
        if self.storage_resource_group and self.storage_resource_group.lower() != expected.lower():
            raise ValueError("Storage resource group contradicts use_common_datalake_storage.")
        if flag is not None:
            if (not isinstance(self.storage_name, str) or not re.fullmatch(r"[a-z0-9]{3,24}", self.storage_name)
                    or "1001" in self.storage_name):
                raise ValueError("Select a data storage account, never the 1001 artifact account.")
            if not self.storage_container:
                object.__setattr__(self, "storage_container", "lake3" if flag else "agent-factory")
        if self.storage_container:
            container_name(self.storage_container)

    def resolve_container(self, requested: str | None = None, *, legacy: str = "agent-factory") -> str:
        """Explicit configured containers are binding, not silently overridden by callers."""
        chosen = self.storage_container or legacy
        if requested is not None:
            container_name(requested)
            if self.storage_container and requested != chosen:
                raise ValueError("Requested container contradicts selected storage_container; change the profile explicitly.")
            chosen = requested
        return container_name(chosen)

    def storage_summary(self, *, legacy: str = "agent-factory") -> dict:
        return {
            "account_name": self.storage_name,
            "resource_group": self.storage_resource_group or self.resource_group,
            "container": self.resolve_container(legacy=legacy),
            "use_common_datalake_storage": self.use_common_datalake_storage,
        }

    @property
    def group_id(self) -> str:
        return f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"

    @property
    def account_id(self) -> str:
        return f"{self.group_id}/providers/Microsoft.CognitiveServices/accounts/{self.account_name}"

    @property
    def project_id(self) -> str:
        return f"{self.account_id}/projects/{self.project_name}"

    @property
    def search_endpoint(self) -> str:
        return f"https://{self.search_name}.search.windows.net"

    @property
    def storage_id(self) -> str:
        group = self.storage_resource_group or self.resource_group
        return (f"/subscriptions/{self.subscription_id}/resourceGroups/{group}"
                f"/providers/Microsoft.Storage/storageAccounts/{self.storage_name}")

    def to_dict(self) -> dict:
        return asdict(self)
