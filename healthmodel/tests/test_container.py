"""Dependency injection container: lifetimes, resolution, cycle detection, thread safety."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import pytest

from aifactory_healthmodel.container import (
    CircularDependencyError, ServiceCollection, ServiceNotRegisteredError,
)


class Clock(ABC):
    @abstractmethod
    def now(self) -> int: ...


class FixedClock(Clock):
    def now(self) -> int:
        return 42


class Greeter:
    def __init__(self, clock: Clock):
        self.clock = clock


def test_singleton_is_created_once_and_shared():
    provider = ServiceCollection().add_singleton(Clock, lambda sp: FixedClock()).build()
    assert provider.get(Clock) is provider.get(Clock)


def test_transient_is_created_per_resolution_with_injected_dependencies():
    provider = (ServiceCollection()
                .add_singleton(Clock, lambda sp: FixedClock())
                .add_transient(Greeter, lambda sp: Greeter(sp.get(Clock)))
                .build())
    first, second = provider.get(Greeter), provider.get(Greeter)
    assert first is not second and first.clock is second.clock


def test_instance_registration_and_replacement_for_tests():
    services = ServiceCollection().add_singleton(Clock, lambda sp: FixedClock())
    fake = FixedClock()
    provider = services.replace(Clock, instance=fake).build()
    assert provider.get(Clock) is fake


def test_duplicate_registration_is_rejected_unless_replaced():
    services = ServiceCollection().add_singleton(Clock, lambda sp: FixedClock())
    with pytest.raises(ValueError, match="already registered"):
        services.add_singleton(Clock, lambda sp: FixedClock())


def test_missing_registration_names_the_service():
    with pytest.raises(ServiceNotRegisteredError, match="Clock"):
        ServiceCollection().build().get(Clock)


def test_circular_dependencies_are_detected():
    class A: ...

    class B: ...

    provider = (ServiceCollection()
                .add_singleton(A, lambda sp: sp.get(B))
                .add_singleton(B, lambda sp: sp.get(A))
                .build())
    with pytest.raises(CircularDependencyError, match="A -> B -> A"):
        provider.get(A)


def test_collection_changes_after_build_do_not_leak_into_the_provider():
    services = ServiceCollection()
    provider = services.build()
    services.add_singleton(Clock, lambda sp: FixedClock())
    assert not provider.is_registered(Clock)


def test_singletons_are_thread_safe():
    calls = []

    def factory(sp):
        calls.append(1)
        return FixedClock()

    provider = ServiceCollection().add_singleton(Clock, factory).build()
    barrier = threading.Barrier(8)
    seen = []

    def worker():
        barrier.wait()
        seen.append(provider.get(Clock))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1 and len({id(item) for item in seen}) == 1
