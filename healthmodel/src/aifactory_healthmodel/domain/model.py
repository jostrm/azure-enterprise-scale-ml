"""Composite health model tree (root -> layers -> resources) and its iterators."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import ClassVar, Iterator

from .classification import Candidate
from .resources import DiscoveredResource
from .signals import Layer, Profile


class HealthEntity(ABC):
    """Component: every node of the model tree can be visited and asked for its children."""

    role: ClassVar[str]

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    def children(self) -> tuple["HealthEntity", ...]:
        return ()

    @abstractmethod
    def accept(self, visitor): ...


@dataclass(frozen=True, eq=False)
class ResourceEntity(HealthEntity):
    """Leaf: one Azure resource modelled with its (possibly overridden) catalog profile."""

    entity_name: str
    layer: Layer
    profile: Profile
    candidate: Candidate
    position: dict
    workspace: str | None = None
    role: ClassVar[str] = "resource"

    @property
    def name(self) -> str:
        return self.entity_name

    @property
    def display_name(self) -> str:
        return f"{self.profile.display_name}: {self.resource.short_name}"[:260]

    @property
    def resource(self) -> DiscoveredResource:
        return self.candidate.resource

    def accept(self, visitor):
        return visitor.visit_resource(self)


@dataclass(frozen=True, eq=False)
class LayerEntity(HealthEntity):
    """Composite: aggregates the health of the resources in one layer."""

    layer: Layer
    position: dict
    resources: tuple[ResourceEntity, ...]
    role: ClassVar[str] = "layer"

    @property
    def name(self) -> str:
        return f"layer-{self.layer.key}"

    @property
    def display_name(self) -> str:
        return self.layer.display_name

    def children(self) -> tuple[ResourceEntity, ...]:
        return self.resources

    def accept(self, visitor):
        return visitor.visit_layer(self)


@dataclass(frozen=True, eq=False)
class RootEntity(HealthEntity):
    """Composite root: the health model itself (the root entity name equals the model name)."""

    model_name: str
    root_display_name: str
    layers: tuple[LayerEntity, ...]
    role: ClassVar[str] = "root"

    @property
    def name(self) -> str:
        return self.model_name

    @property
    def display_name(self) -> str:
        return self.root_display_name

    def children(self) -> tuple[LayerEntity, ...]:
        return self.layers

    def accept(self, visitor):
        return visitor.visit_root(self)


def breadth_first(root: HealthEntity) -> Iterator[HealthEntity]:
    queue = deque([root])
    while queue:
        entity = queue.popleft()
        yield entity
        queue.extend(entity.children())


def depth_first(root: HealthEntity) -> Iterator[HealthEntity]:
    stack = [root]
    while stack:
        entity = stack.pop()
        yield entity
        stack.extend(reversed(entity.children()))


def edges(root: HealthEntity) -> Iterator[tuple[HealthEntity, HealthEntity]]:
    for parent in breadth_first(root):
        for child in parent.children():
            yield parent, child
