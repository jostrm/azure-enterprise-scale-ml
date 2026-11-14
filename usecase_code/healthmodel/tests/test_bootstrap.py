"""Composition root: DI registrations, decorator chains and replaceable services."""
from __future__ import annotations

import json

import pytest

from aifactory_healthmodel.application.events import EventBus
from aifactory_healthmodel.application.ports import ArmTransport, CallableClientFactory, ClientFactory
from aifactory_healthmodel.application.service import HealthModelService
from aifactory_healthmodel.bootstrap import Settings, create_services, runtime_transport
from aifactory_healthmodel.domain.definitions import DefinitionRegistry
from aifactory_healthmodel.infrastructure.azure_cli import AzureCliInfrastructure
from aifactory_healthmodel.infrastructure.offline import OfflineInfrastructure
from aifactory_healthmodel.infrastructure.resilience import RetryingTransport

SUB = "00000000-0000-0000-0000-0000000000aa"


def services(read_only=True, **settings):
    return create_services(Settings(subscription_id=SUB, read_only=read_only, pipeline_annotations=False, **settings),
                           infrastructure=AzureCliInfrastructure(SUB, runner=lambda *a, **k: None))


def chain(transport):
    names = []
    while transport is not None:
        names.append(type(transport).__name__)
        transport = getattr(transport, "inner", None)
    return names


def test_the_service_graph_resolves_with_shared_singletons():
    provider = services()
    service = provider.get(HealthModelService)
    assert service is provider.get(HealthModelService)
    assert service.events is provider.get(EventBus)
    assert service.registry.keys() == ("agents", "common", "project")


def test_transport_decorators_depend_on_the_mode():
    assert chain(services(read_only=False).get(ArmTransport)) == [
        "RetryingTransport", "CircuitBreakerTransport", "AzCliTransport"]
    assert chain(services(read_only=True).get(ArmTransport)) == [
        "ReadOnlyTransport", "RetryingTransport", "CircuitBreakerTransport", "AzCliTransport"]
    assert chain(services(read_only=False, resilience=False).get(ArmTransport)) == ["AzCliTransport"]


def test_any_registration_can_be_replaced(tmp_path):
    created = []
    provider = create_services(
        Settings(subscription_id=SUB, pipeline_annotations=False),
        infrastructure=OfflineInfrastructure([], subscription_id=SUB, tenant_id="t"),
        configure=lambda s: s.replace(ClientFactory, instance=CallableClientFactory(lambda *a: created.append(a))))
    provider.get(ClientFactory)("model", "transport")
    assert created == [("model", "transport")]


def test_consumer_definition_folders_extend_the_registry(tmp_path):
    (tmp_path / "data.json").write_text(json.dumps({
        "key": "data", "nameToken": "dat{project}", "home": "project", "rootDisplayName": "Data {project}",
        "layers": [{"fromCatalog": True, "select": {"layer": "data"}}]}), encoding="utf-8")
    registry = services(definitions_dirs=(tmp_path,)).get(DefinitionRegistry)
    assert "data" in registry and registry.keys() == ("agents", "common", "data", "project")


def test_read_only_services_refuse_to_deploy(tmp_path):
    from aifactory_healthmodel import naming
    from aifactory_healthmodel.application.service import RunRequest

    scope = naming.explicit(tenant_id="11111111-1111-1111-1111-111111111111", subscription_id=SUB,
                            environment="dev", project_number="001", location="swedencentral",
                            location_suffix="sdc", project_resource_group="rg")
    with pytest.raises(RuntimeError, match="read-only"):
        services(read_only=True).get(HealthModelService).run(RunRequest(mode="deploy", scope=scope, work_root=tmp_path))


def test_runtime_transport_for_operations():
    assert chain(runtime_transport("cli", read_only=True)) == [
        "ReadOnlyTransport", "RetryingTransport", "CircuitBreakerTransport", "AzCliTransport"]
    assert isinstance(runtime_transport("cli"), RetryingTransport)
    with pytest.raises(ValueError):
        runtime_transport("password")


def test_each_composition_has_its_own_singletons():
    first, second = services(), services()
    assert first.get(EventBus) is not second.get(EventBus)
