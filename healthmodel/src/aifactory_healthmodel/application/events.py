"""Observer: an in-process event bus and the reporters that subscribe to it."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Event:
    pass


@dataclass(frozen=True)
class RunStarted(Event):
    mode: str
    models: tuple[str, ...]
    subscription: str


@dataclass(frozen=True)
class ModelPlanned(Event):
    definition: str
    model: str
    entities: int
    signals: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandExecuted(Event):
    description: str


@dataclass(frozen=True)
class WarningRaised(Event):
    message: str


@dataclass(frozen=True)
class RunCompleted(Event):
    mode: str
    models: tuple[str, ...]
    writes: int


class EventBus:
    """Publishes events to every handler subscribed to the event's type (or a base type)."""

    def __init__(self):
        self._handlers: list[tuple[type, Callable]] = []

    def subscribe(self, event_type: type, handler: Callable) -> Callable[[], None]:
        entry = (event_type, handler)
        self._handlers.append(entry)
        return lambda: self._handlers.remove(entry)

    def publish(self, event: Event) -> None:
        for event_type, handler in list(self._handlers):
            if isinstance(event, event_type):
                handler(event)


class ConsoleReporter:
    """Progress and operational warnings on stderr; stdout stays reserved for the JSON report."""

    def __init__(self, stream=None):
        self._stream = stream

    @property
    def stream(self):
        return self._stream or sys.stderr

    def attach(self, bus: EventBus) -> "ConsoleReporter":
        bus.subscribe(ModelPlanned, self._planned)
        bus.subscribe(CommandExecuted, lambda e: print(f"Done: {e.description}", file=self.stream))
        bus.subscribe(WarningRaised, lambda e: print(f"WARNING: {e.message}", file=self.stream))
        return self

    def _planned(self, event: ModelPlanned) -> None:
        print(f"Planned {event.model} ({event.definition}): {event.entities} entities, {event.signals} signals, "
              f"{len(event.warnings)} warning(s).", file=self.stream)


class PipelineReporter:
    """Surfaces plan warnings as GitHub Actions or Azure DevOps pipeline annotations."""

    def __init__(self, flavour: str, stream=None):
        if flavour not in ("github", "azure-devops"):
            raise ValueError("flavour must be github or azure-devops.")
        self.flavour = flavour
        self._stream = stream

    @classmethod
    def detect(cls, environ=None) -> "PipelineReporter | None":
        environ = os.environ if environ is None else environ
        if str(environ.get("GITHUB_ACTIONS", "")).lower() == "true":
            return cls("github")
        if str(environ.get("TF_BUILD", "")).lower() == "true":
            return cls("azure-devops")
        return None

    def attach(self, bus: EventBus) -> "PipelineReporter":
        bus.subscribe(ModelPlanned, lambda e: [self._emit(w, f"Health model {e.model}") for w in e.warnings])
        bus.subscribe(WarningRaised, lambda e: self._emit(e.message, "AI Factory health model"))
        return self

    def _emit(self, message: str, title: str) -> None:
        stream = self._stream or sys.stdout
        if self.flavour == "github":
            text = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::warning title={title}::{text}", file=stream)
        else:
            print(f"##vso[task.logissue type=warning]{' '.join(message.split())}", file=stream)
