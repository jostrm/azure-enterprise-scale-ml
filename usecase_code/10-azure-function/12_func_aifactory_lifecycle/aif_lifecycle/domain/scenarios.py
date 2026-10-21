"""The six lifecycle scenarios and the readable ID each one takes."""

from __future__ import annotations

from enum import Enum

from .errors import ValidationFailed


class Scenario(str, Enum):
    INIT_FACTORY = "init-factory"
    ADD_SCALESET = "add-scaleset"
    ADD_OR_UPDATE_PROJECT = "add-or-update-project"
    DELETE_PROJECT = "delete-project"
    DELETE_SCALESET = "delete-scaleset"
    DELETE_FACTORY = "delete-factory"

    @classmethod
    def parse(cls, slug: str) -> "Scenario":
        try:
            return cls(slug)
        except ValueError:
            names = ", ".join(item.value for item in cls)
            raise ValidationFailed(f"Scenario '{slug}' is not one of: {names}.", code="unsupported-scenario") from None

    @property
    def number(self) -> int:
        return list(Scenario).index(self) + 1

    @property
    def target_kind(self) -> str:
        return _TARGET_KIND[self]

    @property
    def id_field(self) -> str:
        return f"{self.target_kind}Id"

    @property
    def destructive(self) -> bool:
        return self in (Scenario.DELETE_PROJECT, Scenario.DELETE_SCALESET, Scenario.DELETE_FACTORY)


_TARGET_KIND = {
    Scenario.INIT_FACTORY: "factory",
    Scenario.ADD_SCALESET: "scaleset",
    Scenario.ADD_OR_UPDATE_PROJECT: "project",
    Scenario.DELETE_PROJECT: "project",
    Scenario.DELETE_SCALESET: "scaleset",
    Scenario.DELETE_FACTORY: "factory",
}
