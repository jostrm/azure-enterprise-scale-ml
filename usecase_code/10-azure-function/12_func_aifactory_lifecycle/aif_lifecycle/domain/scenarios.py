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


ADD_PROJECT001_STEP = "add-project001"
"""Scenario 2's configuration step that puts project001 on the new scale set. The Factory API's `create-scale-set`
adds no project, and a project has one placement per environment, so this is a new logical project (`add-project`
placed on the new scale set), not a second placement of the factory's existing project001."""


ENROLL_SCALESET_STEP = "enroll-scaleset"
"""Scenario 2's reviewed step that extends a single-writer factory's binding and live enrollment to the new scale set
(the Factory API's `enroll-scale-set`). It covers only projects placed on the scale set when it is prepared, so it
runs after add-project001 and before deploy-common; a Blob-coordinated factory does not need it."""

ENROLL_PHRASE_PREFIX = "ENROLL SCALE SET "


def enrollment_phrase(factory_key: str, suffix: str) -> str:
    """The typed confirmation of enroll-scale-set; the factory key is the prefix without its trailing dash."""
    return f"{ENROLL_PHRASE_PREFIX}{factory_key} {suffix}"


def adds_project(scenario: Scenario, step_name: str, resolved: dict) -> bool:
    """Whether this configuration step creates a new logical project placed on `resolved['scale_set_id']`."""
    if scenario is Scenario.ADD_SCALESET:
        return step_name == ADD_PROJECT001_STEP
    return scenario is Scenario.ADD_OR_UPDATE_PROJECT and resolved.get("mode") == "add"


_TARGET_KIND = {
    Scenario.INIT_FACTORY: "factory",
    Scenario.ADD_SCALESET: "scaleset",
    Scenario.ADD_OR_UPDATE_PROJECT: "project",
    Scenario.DELETE_PROJECT: "project",
    Scenario.DELETE_SCALESET: "scaleset",
    Scenario.DELETE_FACTORY: "factory",
}
