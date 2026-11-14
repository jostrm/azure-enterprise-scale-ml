"""A small dependency injection container.

Services are registered against a key, normally the abstract port (``ABC``) they
implement, with a factory that receives the provider and resolves its own
dependencies (constructor injection). Lifetimes:

* singleton - one instance per provider, created lazily and thread-safely. This is
  the container-managed form of the Singleton pattern: one shared instance without
  a global, so tests can build a provider with fakes.
* transient - a new instance per resolution.

The composition root (``bootstrap.create_services``) is the only place that
registers services; everything else receives its collaborators through
constructors.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

T = TypeVar("T")
Factory = Callable[["ServiceProvider"], Any]


class ServiceNotRegisteredError(LookupError):
    pass


class CircularDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Registration:
    lifetime: str
    factory: Factory


def _name(key: object) -> str:
    return getattr(key, "__name__", str(key))


class ServiceCollection:
    """Mutable registration list; ``build()`` freezes a copy into a provider."""

    def __init__(self):
        self._registrations: dict[object, _Registration] = {}

    def _add(self, key: object, lifetime: str, factory: Factory) -> "ServiceCollection":
        if key in self._registrations:
            raise ValueError(f"{_name(key)} is already registered; use replace() to swap it.")
        self._registrations[key] = _Registration(lifetime, factory)
        return self

    def add_singleton(self, key: object, factory: Factory) -> "ServiceCollection":
        return self._add(key, "singleton", factory)

    def add_transient(self, key: object, factory: Factory) -> "ServiceCollection":
        return self._add(key, "transient", factory)

    def add_instance(self, key: object, instance: object) -> "ServiceCollection":
        return self._add(key, "singleton", lambda _: instance)

    def replace(self, key: object, factory: Factory | None = None, *, instance: object = None,
                lifetime: str = "singleton") -> "ServiceCollection":
        if (factory is None) == (instance is None):
            raise ValueError("Pass exactly one of factory or instance.")
        self._registrations[key] = _Registration(lifetime, factory or (lambda _: instance))
        return self

    def is_registered(self, key: object) -> bool:
        return key in self._registrations

    def build(self) -> "ServiceProvider":
        return ServiceProvider(dict(self._registrations))


class ServiceProvider:
    def __init__(self, registrations: dict[object, _Registration]):
        self._registrations = registrations
        self._singletons: dict[object, Any] = {}
        self._lock = threading.RLock()
        self._resolving = threading.local()

    def is_registered(self, key: object) -> bool:
        return key in self._registrations

    def get(self, key: type[T] | object) -> T:
        registration = self._registrations.get(key)
        if registration is None:
            raise ServiceNotRegisteredError(f"No service registered for {_name(key)}.")
        if registration.lifetime == "transient":
            return self._create(key, registration)
        with self._lock:
            if key not in self._singletons:
                self._singletons[key] = self._create(key, registration)
            return self._singletons[key]

    def _create(self, key: object, registration: _Registration):
        stack = getattr(self._resolving, "stack", None)
        if stack is None:
            stack = self._resolving.stack = []
        if key in stack:
            chain = " -> ".join(_name(item) for item in [*stack[stack.index(key):], key])
            raise CircularDependencyError(f"Circular dependency: {chain}")
        stack.append(key)
        try:
            return registration.factory(self)
        finally:
            stack.pop()
