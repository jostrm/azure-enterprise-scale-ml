"""Command pattern: every Azure write is a command object that can be described, executed and audited."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from .. import __version__
from ..client import HealthModelError
from ..domain.plan import ModelPlan
from .events import CommandExecuted, EventBus, WarningRaised


class Command(ABC):
    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    def execute(self): ...


class CommandInvoker:
    """Executes commands, publishes ``CommandExecuted`` and keeps the history (audit trail)."""

    def __init__(self, events: EventBus):
        self._events = events
        self.history: list[Command] = []

    def execute(self, command: Command):
        result = command.execute()
        self.history.append(command)
        self._events.publish(CommandExecuted(command.describe()))
        return result


class LazyClient:
    """Virtual Proxy: creates the health model client on first use, then forwards every call."""

    def __init__(self, factory: Callable[[], object]):
        self._factory = factory
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            self._client = self._factory()
        return getattr(self._client, name)


class RegisterProviderCommand(Command):
    def __init__(self, providers, subscription_id: str):
        self._providers, self._subscription_id = providers, subscription_id

    def describe(self) -> str:
        return f"Register the Microsoft.CloudHealth resource provider in subscription {self._subscription_id}."

    def execute(self):
        return self._providers.register_provider()


class DeployModelCommand(Command):
    def __init__(self, deployer, plan: ModelPlan, template: Path, parameters: Path):
        self._deployer, self._plan = deployer, plan
        self._template, self._parameters = template, parameters

    @property
    def deployment_name(self) -> str:
        return f"aifactory-{self._plan.model_name}"[:64]

    def describe(self) -> str:
        plan = self._plan
        return (f"Deploy health model {plan.model_name} to resource group {plan.home_resource_group} (incremental): "
                f"{len(plan.entities)} entities, {len(plan.relationships)} relationships, Monitoring Reader on "
                f"{len(plan.reader_resource_groups)} resource group(s), health-state alert rules.")

    def execute(self):
        return self._deployer.deploy(self.deployment_name, self._plan.home_resource_group, self._template,
                                     self._parameters)


class PruneModelCommand(Command):
    def __init__(self, client: Callable[[], object], plan: ModelPlan):
        self._client, self._plan = client, plan

    def describe(self) -> str:
        return (f"Delete entities and relationships of {self._plan.model_name} that this tool created earlier "
                "but no longer plans.")

    def execute(self) -> dict:
        client = self._client()
        stale = client.stale_managed({e.name for e in self._plan.entities},
                                     {r["name"] for r in self._plan.relationships})
        for name in stale["relationships"]:
            client.delete_relationship(name)
        for name in stale["entities"]:
            client.delete_entity(name)
        return stale


class AnnotateModelCommand(Command):
    def __init__(self, client: Callable[[], object], plan: ModelPlan, run_id: str, events: EventBus):
        self._client, self._plan, self._run_id, self._events = client, plan, run_id, events

    def describe(self) -> str:
        return f"Add a deployment annotation to the root entity of {self._plan.model_name}."

    def execute(self):
        plan = self._plan
        details = {"event": "aifactory-healthmodel-deployment", "tool": f"aifactory-healthmodel {__version__}",
                   "definition": plan.definition,
                   "resources": str(len([e for e in plan.entities if e.role == "resource"])),
                   "run": (self._run_id or "local")[:256]}
        try:
            return self._client().add_annotation(
                "root", details, f"AI Factory health model {plan.model_name} deployed or refreshed.")
        except HealthModelError as error:
            self._events.publish(WarningRaised(f"deployment annotation skipped ({error.code})."))
            return None
