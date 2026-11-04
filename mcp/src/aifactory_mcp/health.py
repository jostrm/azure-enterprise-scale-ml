"""Interchangeable read-only health strategies with explicitly injected dependencies."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict


class NoHealthArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass(frozen=True)
class HealthDefinition:
    name: str
    description: str
    arguments: type[BaseModel] = NoHealthArguments

    def __post_init__(self):
        if (not isinstance(self.name, str) or len(self.name) > 64 or not re.fullmatch(
            r"(?:factory_health|factory_cli_health|health_[a-z0-9_]+)", self.name,
        )):
            raise ValueError("Use a health_ name of at most 64 characters, or an existing Factory health name.")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("A health model description is required.")
        if (not isinstance(self.arguments, type) or not issubclass(self.arguments, BaseModel)
                or self.arguments.model_config.get("extra") != "forbid"
                or self.arguments.model_config.get("strict") is not True):
            raise ValueError("Health argument models must be strict and forbid extra fields.")


class HealthModel(Protocol):
    @property
    def definition(self) -> HealthDefinition: ...

    def evaluate(self, arguments: Mapping[str, object]) -> dict[str, object]: ...


class HealthProbe(Protocol):
    """Only read capabilities; an injected model does not receive write dispatch."""

    def api_health(self) -> dict[str, object]: ...

    def cli_health(self) -> dict[str, object]: ...

    def capabilities(self) -> dict[str, object]: ...


class ToolExecutor(Protocol):
    def execute(self, name: str, args: dict) -> dict: ...


@dataclass(frozen=True)
class AgentHealthProbe:
    """Adapter from the existing caller-bound FactoryTools to the health port."""

    _tools: ToolExecutor

    def api_health(self) -> dict[str, object]:
        return self._tools.execute("factory_health", {})

    def cli_health(self) -> dict[str, object]:
        return self._tools.execute("factory_cli_health", {})

    def capabilities(self) -> dict[str, object]:
        return self._tools.execute("factory_capabilities", {})


@dataclass(frozen=True)
class ApiHealthModel:
    probe: HealthProbe
    definition: HealthDefinition = HealthDefinition("factory_health", "Read health of the configured Factory API.")

    def evaluate(self, arguments: Mapping[str, object]) -> dict[str, object]:
        return self.probe.api_health()


@dataclass(frozen=True)
class CliHealthModel:
    probe: HealthProbe
    definition: HealthDefinition = HealthDefinition(
        "factory_cli_health", "Run the fixed AzureFactory CLI health command without a shell.",
    )

    def evaluate(self, arguments: Mapping[str, object]) -> dict[str, object]:
        return self.probe.cli_health()


HealthModelFactory: TypeAlias = Callable[[HealthProbe], Iterable[HealthModel]]


def default_health_models(probe: HealthProbe) -> tuple[HealthModel, ...]:
    return ApiHealthModel(probe), CliHealthModel(probe)


class HealthRegistry:
    """Snapshot of trusted registrations; discovery never runs health probes."""

    def __init__(self, models: Iterable[HealthModel]):
        registered: dict[str, tuple[HealthDefinition, HealthModel]] = {}
        for model in models:
            definition = model.definition
            if not isinstance(definition, HealthDefinition) or not callable(model.evaluate):
                raise ValueError("A health model must implement the HealthModel contract.")
            if definition.name in registered:
                raise ValueError("Duplicate health model name.")
            registered[definition.name] = (definition, model)
        self._models = MappingProxyType(registered)

    def __contains__(self, name: str) -> bool:
        return name in self._models

    def descriptors(self) -> list[dict]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "inputSchema": definition.arguments.model_json_schema(),
                "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                "idempotentHint": True, "openWorldHint": True},
            }
            for definition, _ in self._models.values()
        ]

    def evaluate(self, name: str, arguments: dict) -> dict[str, object]:
        if name not in self._models:
            raise ValueError("The health model is not registered.")
        definition, model = self._models[name]
        validated = definition.arguments.model_validate(arguments)
        return model.evaluate(validated.model_dump(mode="json"))

