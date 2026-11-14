"""Ports of the application layer (Hexagonal architecture / Anti-corruption layer).

The application talks to Azure only through these small interfaces. Each concrete
family (Azure CLI, offline inventory, test fakes) is created by an ``InfrastructureFactory``
(Abstract Factory), so the members of one family are always used together.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class ArmTransport(Protocol):
    def request(self, method: str, url: str, body: dict | None = None): ...


@runtime_checkable
class AccountVerifier(Protocol):
    def verify_account(self, tenant_id: str) -> dict: ...


@runtime_checkable
class ProviderRegistrar(Protocol):
    def provider(self) -> dict: ...

    def register_provider(self, timeout: int = 600) -> None: ...


@runtime_checkable
class ResourceDiscovery(Protocol):
    def discover(self, resource_groups: list[str], include_health_models: bool = False) -> list[dict]: ...


@runtime_checkable
class TemplateDeployer(Protocol):
    def what_if(self, resource_group: str, template: Path, parameters: Path): ...

    def deploy(self, name: str, resource_group: str, template: Path, parameters: Path) -> dict: ...


class ClientFactory(ABC):
    """Creates a health model client (the Bridge abstraction) for a model ID and transport."""

    @abstractmethod
    def __call__(self, model_id: str, transport: ArmTransport): ...


class CallableClientFactory(ClientFactory):
    def __init__(self, create: Callable):
        self._create = create

    def __call__(self, model_id: str, transport: ArmTransport):
        return self._create(model_id, transport)


class InfrastructureFactory(ABC):
    """Abstract Factory for one consistent family of Azure adapters."""

    name = "abstract"
    supports_writes = True

    @abstractmethod
    def create_transport(self) -> ArmTransport: ...

    @abstractmethod
    def create_account_verifier(self) -> AccountVerifier: ...

    @abstractmethod
    def create_provider_registrar(self, transport: ArmTransport) -> ProviderRegistrar: ...

    @abstractmethod
    def create_discovery(self, transport: ArmTransport) -> ResourceDiscovery: ...

    @abstractmethod
    def create_deployer(self) -> TemplateDeployer: ...
