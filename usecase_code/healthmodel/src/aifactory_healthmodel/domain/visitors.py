"""Visitors over the composite model: API payloads, signal counts and validation."""
from __future__ import annotations

from .. import catalog as raw
from .model import HealthEntity, LayerEntity, ResourceEntity, RootEntity, edges

AUTH_SETTING = "systemassigned"
MANAGED_BY = "aifactory-healthmodel"


class EntityVisitor:
    def visit_root(self, root: RootEntity):
        return None

    def visit_layer(self, layer: LayerEntity):
        return None

    def visit_resource(self, resource: ResourceEntity):
        return None


class PayloadVisitor(EntityVisitor):
    """Renders Microsoft.CloudHealth entity properties. The root entity is created by Bicep."""

    def visit_layer(self, layer: LayerEntity) -> dict:
        return {
            "displayName": layer.layer.display_name,
            "impact": layer.layer.impact,
            "icon": {"iconName": "SystemComponent"},
            "canvasPosition": dict(layer.position),
            "tags": {"managedBy": MANAGED_BY, "role": "layer", "layer": layer.layer.key},
            "signalGroups": {"dependencies": {"aggregationType": "WorstOf", "ignoreUnknown": True}},
        }

    def visit_resource(self, entity: ResourceEntity) -> dict:
        profile, resource = entity.profile, entity.resource
        group = {
            "authenticationSetting": AUTH_SETTING,
            "azureResourceId": resource.id,
            "azureResourceKind": resource.type if profile.nested_model else resource.kind,
            "resourceHealth": {"enabled": profile.resource_health},
            "signals": [signal.to_api() for signal in profile.signals],
        }
        properties = {
            "displayName": entity.display_name,
            "impact": profile.impact,
            "icon": {"iconName": "Resource"},
            "canvasPosition": dict(entity.position),
            "tags": {"managedBy": MANAGED_BY, "role": "resource", "profile": profile.key, "layer": entity.layer.key,
                     "aifactoryScope": entity.candidate.aifactory_scope},
            "signalGroups": {"azureResource": group},
        }
        if entity.workspace and profile.log_signals:
            signals = []
            for signal in profile.log_signals:
                payload = signal.to_api()
                # Resource IDs contain no quotes; scope every query to this one resource.
                payload["queryText"] = payload["queryText"].replace("__RESOURCE_ID__", resource.id.lower())
                signals.append(payload)
            properties["signalGroups"]["azureLogAnalytics"] = {
                "authenticationSetting": AUTH_SETTING, "logAnalyticsWorkspaceResourceId": entity.workspace,
                "signals": signals}
        if profile.aggregation_groups:
            properties["signalAggregationGroups"] = profile.aggregation_groups_api()
        return properties


class SignalCountVisitor(EntityVisitor):
    def __init__(self):
        self.total = 0

    def visit_resource(self, entity: ResourceEntity):
        self.total += len(entity.profile.signals)
        if entity.workspace:
            self.total += len(entity.profile.log_signals)


class ValidationVisitor(EntityVisitor):
    """Collects naming and size violations before anything is sent to Azure."""

    def __init__(self):
        self.errors: list[str] = []
        self._names: set[str] = set()

    def _name(self, entity: HealthEntity, pattern) -> None:
        if entity.name in self._names:
            self.errors.append(f"Duplicate entity name {entity.name!r}.")
        self._names.add(entity.name)
        if not pattern.fullmatch(entity.name):
            self.errors.append(f"Invalid entity name {entity.name!r}.")

    def visit_root(self, root: RootEntity):
        self._name(root, raw.MODEL_NAME_PATTERN)

    def visit_layer(self, layer: LayerEntity):
        self._name(layer, raw.NAME_PATTERN)

    def visit_resource(self, entity: ResourceEntity):
        self._name(entity, raw.NAME_PATTERN)
        names = [signal.name for signal in entity.profile.signals]
        if len(names) != len(set(names)):
            self.errors.append(f"Duplicate signal names in {entity.name!r}.")

    def raise_if_invalid(self) -> None:
        if self.errors:
            raise ValueError("Invalid health model: " + " ".join(self.errors))


def relationships(root: RootEntity) -> list[dict]:
    """Parent/child relationships, breadth first: root -> layers, then layers -> resources."""
    return [{"name": f"{parent.name}-to-{child.name}", "parentEntityName": parent.name,
             "childEntityName": child.name} for parent, child in edges(root)]
