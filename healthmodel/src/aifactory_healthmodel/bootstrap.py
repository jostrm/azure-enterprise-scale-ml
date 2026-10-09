"""Composition root: the only place that knows every concrete class.

``create_services`` registers the domain, application and infrastructure services in the
DI container. Callers choose the infrastructure family (Abstract Factory) and may replace
any registration with ``configure`` (tests, hosts such as the AI Factory API or an MCP server).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import catalog as raw
from .application.commands import CommandInvoker
from .application.events import ConsoleReporter, EventBus, PipelineReporter
from .application.parameters import BicepParameterRenderer
from .application.ports import (AccountVerifier, ArmTransport, CallableClientFactory, ClientFactory,
                                InfrastructureFactory, ProviderRegistrar, ResourceDiscovery, TemplateDeployer)
from .application.service import HealthModelService
from .client import HealthModelClient
from .container import ServiceCollection, ServiceProvider
from .domain.definitions import DEFINITIONS_DIR, DefinitionRegistry, ModelDefinitionFactory
from .domain.signals import SignalCatalog
from .infrastructure.proxies import ReadOnlyDeployer, ReadOnlyProviders, ReadOnlyTransport
from .infrastructure.resilience import CircuitBreakerTransport, RetryingTransport, RetryPolicy

TEMPLATE = raw.HEALTHMODEL_ROOT / "bicep" / "main.bicep"


@dataclass(frozen=True)
class Settings:
    subscription_id: str
    tenant_id: str = ""
    read_only: bool = True
    definitions_dirs: tuple[Path, ...] = ()
    catalog_path: Path | None = None
    template: Path = TEMPLATE
    resilience: bool = True
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    pipeline_annotations: bool | None = None  # None: detect GitHub Actions / Azure DevOps
    sleep: Callable[[float], None] = time.sleep


def resilient(transport: ArmTransport, settings: Settings) -> ArmTransport:
    """Decorate a transport with Retry (outer) and Circuit Breaker (inner)."""
    return RetryingTransport(CircuitBreakerTransport(transport), settings.retry, sleep=settings.sleep)


def build_registry(definitions_dirs=(), catalog: SignalCatalog | None = None,
                   factory: ModelDefinitionFactory | None = None) -> DefinitionRegistry:
    """Built-in definitions first, then each consumer folder (External Configuration Store)."""
    registry = DefinitionRegistry(catalog or SignalCatalog.from_file(), factory)
    registry.load_directory(DEFINITIONS_DIR)
    for folder in definitions_dirs:
        registry.load_directory(folder)
    return registry


def _registry(provider: ServiceProvider) -> DefinitionRegistry:
    return build_registry(provider.get(Settings).definitions_dirs, provider.get(SignalCatalog),
                          provider.get(ModelDefinitionFactory))


def _events(provider: ServiceProvider) -> EventBus:
    bus, setting = EventBus(), provider.get(Settings).pipeline_annotations
    ConsoleReporter().attach(bus)
    if setting is None:
        pipeline = PipelineReporter.detect()
    elif setting:
        pipeline = PipelineReporter.detect() or PipelineReporter("github")
    else:
        pipeline = None
    if pipeline:
        pipeline.attach(bus)
    return bus


def _transport(provider: ServiceProvider) -> ArmTransport:
    settings = provider.get(Settings)
    transport = provider.get(InfrastructureFactory).create_transport()
    if settings.resilience:
        transport = resilient(transport, settings)
    return ReadOnlyTransport(transport, "plan is read-only") if settings.read_only else transport


def _guarded(provider: ServiceProvider, service, proxy):
    return proxy(service) if provider.get(Settings).read_only else service


def create_services(settings: Settings, *, infrastructure: InfrastructureFactory,
                    configure: Callable[[ServiceCollection], None] | None = None) -> ServiceProvider:
    services = ServiceCollection()
    services.add_instance(Settings, settings)
    services.add_instance(InfrastructureFactory, infrastructure)
    services.add_singleton(SignalCatalog, lambda sp: SignalCatalog.from_file(sp.get(Settings).catalog_path))
    services.add_singleton(ModelDefinitionFactory, lambda sp: ModelDefinitionFactory())
    services.add_singleton(DefinitionRegistry, _registry)
    services.add_singleton(EventBus, _events)
    services.add_singleton(ArmTransport, _transport)
    services.add_singleton(AccountVerifier, lambda sp: infrastructure.create_account_verifier())
    services.add_singleton(ProviderRegistrar, lambda sp: _guarded(
        sp, infrastructure.create_provider_registrar(sp.get(ArmTransport)), ReadOnlyProviders))
    services.add_singleton(ResourceDiscovery, lambda sp: infrastructure.create_discovery(sp.get(ArmTransport)))
    services.add_singleton(TemplateDeployer, lambda sp: _guarded(sp, infrastructure.create_deployer(),
                                                                 ReadOnlyDeployer))
    services.add_singleton(ClientFactory, lambda sp: CallableClientFactory(HealthModelClient))
    services.add_singleton(BicepParameterRenderer, lambda sp: BicepParameterRenderer())
    services.add_singleton(CommandInvoker, lambda sp: CommandInvoker(sp.get(EventBus)))
    services.add_singleton(HealthModelService, lambda sp: HealthModelService(
        registry=sp.get(DefinitionRegistry), renderer=sp.get(BicepParameterRenderer),
        account=sp.get(AccountVerifier), providers=sp.get(ProviderRegistrar), discovery=sp.get(ResourceDiscovery),
        deployer=sp.get(TemplateDeployer), transport=sp.get(ArmTransport), client_factory=sp.get(ClientFactory),
        events=sp.get(EventBus), invoker=sp.get(CommandInvoker), template=sp.get(Settings).template,
        supports_writes=infrastructure.supports_writes, read_only=sp.get(Settings).read_only))
    if configure:
        configure(services)
    return services.build()


def runtime_transport(auth: str = "cli", *, read_only: bool = False, settings: Settings | None = None) -> ArmTransport:
    """Transport for operating deployed models (status, alerts, MCP tools): resilient, optionally read-only."""
    from .infrastructure.azure_cli import AzCliTransport

    if auth == "identity":
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError:
            raise RuntimeError("--auth identity requires the azure-identity package.") from None
        from .infrastructure.identity import TokenTransport

        transport = TokenTransport(DefaultAzureCredential())
    elif auth == "cli":
        transport = AzCliTransport()
    else:
        raise ValueError("auth must be cli or identity.")
    transport = resilient(transport, settings or Settings(subscription_id=""))
    return ReadOnlyTransport(transport, "this command only reads") if read_only else transport
