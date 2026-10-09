"""Canvas layout strategies for the health model designer view."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LayoutStrategy(ABC):
    @abstractmethod
    def layer_position(self, index: int, count: int) -> dict: ...

    @abstractmethod
    def resource_position(self, layer_position: dict, index: int, count: int) -> dict: ...


class TieredLayout(LayoutStrategy):
    """Root on top, one column per layer, resources in two staggered columns below their layer."""

    LAYER_SPACING, RESOURCE_OFFSET, ROW_HEIGHT = 360, 90, 140
    LAYER_Y, RESOURCE_Y = 220, 440

    def layer_position(self, index: int, count: int) -> dict:
        return {"x": int((index - (count - 1) / 2) * self.LAYER_SPACING), "y": self.LAYER_Y}

    def resource_position(self, layer_position: dict, index: int, count: int) -> dict:
        offset = 0 if count == 1 else (self.RESOURCE_OFFSET if index % 2 else -self.RESOURCE_OFFSET)
        row = index // 2 if count > 1 else index
        return {"x": layer_position["x"] + offset, "y": self.RESOURCE_Y + row * self.ROW_HEIGHT}
