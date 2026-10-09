"""The result of planning one health model: entities, relationships, coverage and summary."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..naming import FactoryScope
from .model import RootEntity
from .resources import DiscoveredResource


@dataclass
class PlannedEntity:
    name: str
    role: str
    layer: str
    display_name: str
    properties: dict
    profile: str | None = None
    resource_id: str | None = None
    scope: str | None = None

    def as_parameter(self) -> dict:
        return {"name": self.name, "role": self.role, "properties": self.properties}


@dataclass
class ModelPlan:
    definition: str
    model_name: str
    model_scope: str
    scope: FactoryScope
    root_display_name: str
    entities: list[PlannedEntity]
    relationships: list[dict]
    reader_resource_groups: list[str]
    coverage: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unmodelled: list[DiscoveredResource] = field(default_factory=list)
    not_monitorable: list[DiscoveredResource] = field(default_factory=list)
    root: RootEntity | None = None
    defaults: dict = field(default_factory=dict)
    nests: frozenset[str] = frozenset()

    def entity(self, name: str) -> PlannedEntity:
        for item in self.entities:
            if item.name == name:
                return item
        raise KeyError(name)

    @property
    def home_resource_group(self) -> str:
        return self.scope.project_resource_group if self.model_scope == "project" else self.scope.common_resource_group

    @property
    def model_id(self) -> str:
        return (f"/subscriptions/{self.scope.subscription_id}/resourceGroups/{self.home_resource_group}"
                f"/providers/Microsoft.CloudHealth/healthmodels/{self.model_name}")

    def summary(self) -> dict:
        resources = [e for e in self.entities if e.role == "resource"]
        return {
            "model": self.model_name,
            "modelScope": self.model_scope,
            "subscription": self.scope.subscription_id,
            "resourceGroup": self.home_resource_group,
            "entities": len(self.entities),
            "resources": len(resources),
            "layers": dict(Counter(e.layer for e in resources)),
            "profiles": dict(sorted(Counter(e.profile for e in resources).items())),
            "signals": sum(len(group.get("signals", [])) for e in resources
                           for group in e.properties["signalGroups"].values()),
            "relationships": len(self.relationships),
            "readerResourceGroups": self.reader_resource_groups,
            "unmodelled": sorted({r.type for r in self.unmodelled}),
            "notMonitorable": dict(sorted(Counter(r.type for r in self.not_monitorable).items())),
            "coverage": self.coverage,
            "warnings": self.warnings,
        }
