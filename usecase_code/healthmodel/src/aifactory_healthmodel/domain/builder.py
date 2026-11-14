"""Builder for the composite health model tree."""
from __future__ import annotations

from .classification import Candidate
from .layout import LayoutStrategy, TieredLayout
from .model import LayerEntity, ResourceEntity, RootEntity
from .resources import entity_name
from .signals import Layer, Profile


class HealthModelBuilder:
    """Collects resources step by step; ``build()`` lays them out and returns the tree.

    Layers appear in the order of their first resource, resources in the order added.
    """

    def __init__(self, model_name: str, root_display_name: str, layout: LayoutStrategy | None = None):
        self._model_name = model_name
        self._root_display_name = root_display_name
        self._layout = layout or TieredLayout()
        self._workspace: str | None = None
        self._layers: dict[str, tuple[Layer, list[tuple[Profile, Candidate]]]] = {}

    def with_workspace(self, workspace: str | None) -> "HealthModelBuilder":
        self._workspace = workspace or None
        return self

    def add_resource(self, layer: Layer, profile: Profile, candidate: Candidate) -> "HealthModelBuilder":
        self._layers.setdefault(layer.key, (layer, []))[1].append((profile, candidate))
        return self

    def build(self) -> RootEntity:
        count = len(self._layers)
        layers = []
        for index, (layer, items) in enumerate(self._layers.values()):
            position = self._layout.layer_position(index, count)
            resources = tuple(
                ResourceEntity(entity_name(profile.key, candidate.resource), layer, profile, candidate,
                               self._layout.resource_position(position, number, len(items)), self._workspace)
                for number, (profile, candidate) in enumerate(items))
            layers.append(LayerEntity(layer, position, resources))
        return RootEntity(self._model_name, self._root_display_name, tuple(layers))
