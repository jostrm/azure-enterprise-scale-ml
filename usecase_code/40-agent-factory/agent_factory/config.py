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
        selected = overrides or {}
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
        unknown = selected.keys() - allowed - {"resource_group", "common_resource_group"}
        if unknown:
            raise ValueError(f"Unknown target options: {', '.join(sorted(unknown))}")
        optional = {key: identifier(required(selected, key), key) for key in allowed if key in selected}
        return cls(
            tenant_id, subscription_id, environment, project_number,
            identifier(resource_group, "resource group"), identifier(common_group, "common resource group"),
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
        return f"{self.group_id}/providers/Microsoft.Storage/storageAccounts/{self.storage_name}"

    def to_dict(self) -> dict:
        return asdict(self)
