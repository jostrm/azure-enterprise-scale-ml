"""Offline family: plan from a saved Resource Graph inventory, without any Azure access.

Useful for pull-request validation without credentials and for client applications
(Tkinter, MAUI, CLI) that preview a model from an exported inventory. Deployments and
what-if are not available offline.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..application.ports import InfrastructureFactory

HEALTH_MODEL_TYPE = "microsoft.cloudhealth/healthmodels"


class OfflineTransport:
    def request(self, method: str, url: str, body: dict | None = None):
        raise RuntimeError("Planning from an offline inventory: no Azure Resource Manager access.")


class StaticAccount:
    def __init__(self, subscription_id: str, tenant_id: str):
        self.subscription_id, self.tenant_id = subscription_id, tenant_id

    def verify_account(self, tenant_id: str) -> dict:
        return {"id": self.subscription_id, "tenantId": tenant_id or self.tenant_id, "offline": True}


class StaticProviders:
    def __init__(self, registration: str = "Registered", regions=None):
        self.registration = registration
        self.regions = {r.lower().replace(" ", "") for r in regions or ()}

    def provider(self) -> dict:
        return {"registrationState": self.registration, "regions": set(self.regions)}

    def register_provider(self, timeout: int = 600) -> None:
        raise RuntimeError("Cannot register resource providers from an offline inventory.")


class InventoryDiscovery:
    """Applies the same filter as the Resource Graph query to inventory rows."""

    def __init__(self, rows: list[dict], subscription_id: str):
        self.rows = list(rows)
        self.subscription_id = subscription_id.lower()

    def discover(self, resource_groups: list[str], include_health_models: bool = False) -> list[dict]:
        groups = {g.lower() for g in resource_groups if g}
        selected = []
        for row in self.rows:
            parts = str(row.get("id", "")).split("/")
            if len(parts) < 3 or parts[2].lower() != self.subscription_id:
                continue
            in_groups = str(row.get("resourceGroup", "")).lower() in groups
            if in_groups or (include_health_models and str(row.get("type", "")).lower() == HEALTH_MODEL_TYPE):
                selected.append(row)
        return selected


class OfflineDeployer:
    def what_if(self, resource_group, template, parameters):
        return "skipped: offline inventory"

    def deploy(self, *args, **kwargs):
        raise RuntimeError("Cannot deploy from an offline inventory; run deploy against Azure.")


class OfflineInfrastructure(InfrastructureFactory):
    name = "offline"
    supports_writes = False

    def __init__(self, rows: list[dict], *, subscription_id: str, tenant_id: str, registration: str = "Registered",
                 regions=None):
        self.rows = list(rows)
        self.subscription_id, self.tenant_id = subscription_id, tenant_id
        self.registration, self.regions = registration, regions

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "OfflineInfrastructure":
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise ValueError("Cannot read the inventory file as JSON.") from None
        rows = document.get("data", document) if isinstance(document, dict) else document
        if not isinstance(rows, list) or not all(isinstance(r, dict) and "id" in r and "type" in r for r in rows):
            raise ValueError("The inventory must be a JSON list of Resource Graph rows (id, name, type, "
                             "resourceGroup, ...) or an object with a data list.")
        return cls(rows, **kwargs)

    def create_transport(self) -> OfflineTransport:
        return OfflineTransport()

    def create_account_verifier(self) -> StaticAccount:
        return StaticAccount(self.subscription_id, self.tenant_id)

    def create_provider_registrar(self, transport) -> StaticProviders:
        return StaticProviders(self.registration, self.regions)

    def create_discovery(self, transport) -> InventoryDiscovery:
        return InventoryDiscovery(self.rows, self.subscription_id)

    def create_deployer(self) -> OfflineDeployer:
        return OfflineDeployer()
