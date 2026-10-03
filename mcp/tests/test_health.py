from dataclasses import dataclass, replace
import importlib.util
from pathlib import Path
import sys

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel, ConfigDict

from aifactory_mcp.health import (
    ApiHealthModel, CliHealthModel, HealthDefinition, HealthRegistry, NoHealthArguments,
)
from aifactory_mcp.server import create_server
from test_backend import setup_backend, assert_error
from test_runtime import (
    CALLER, SCOPE, artifacts, config_path, configuration, runtime,
)


class FakeProbe:
    def __init__(self):
        self.calls = []

    def api_health(self):
        self.calls.append("api")
        return {"ok": True, "data": {"status": "ok", "version": "1.0.0"}}

    def cli_health(self):
        self.calls.append("cli")
        return {"ok": True, "data": {"status": "cli-ok"}}

    def capabilities(self):
        self.calls.append("capabilities")
        return {"ok": True, "data": {"features": ["review"]}}


@dataclass
class CustomHealthModel:
    probe: FakeProbe
    definition: HealthDefinition = HealthDefinition(
        "health_custom_api", "Read API health through a custom model.",
    )

    def evaluate(self, arguments):
        return self.probe.api_health()


def test_multiple_health_strategies_keep_existing_response_contract():
    probe = FakeProbe()
    registry = HealthRegistry([ApiHealthModel(probe), CliHealthModel(probe), CustomHealthModel(probe)])
    assert probe.calls == []
    definitions = registry.descriptors()
    assert [item["name"] for item in definitions] == [
        "factory_health", "factory_cli_health", "health_custom_api",
    ]
    assert all(item["annotations"]["readOnlyHint"] for item in definitions)
    assert registry.evaluate("factory_health", {}) == probe.api_health()
    assert registry.evaluate("factory_cli_health", {})["data"]["status"] == "cli-ok"
    assert registry.evaluate("health_custom_api", {})["ok"] is True


def test_registry_defensively_returns_descriptors_and_has_closed_arguments():
    registry = HealthRegistry([ApiHealthModel(FakeProbe())])
    definition = registry.descriptors()[0]
    definition["inputSchema"]["additionalProperties"] = True
    assert registry.descriptors()[0]["inputSchema"]["additionalProperties"] is False
    with pytest.raises(ValueError):
        registry.evaluate("factory_health", {"url": "https://other.example"})
    with pytest.raises(ValueError, match="registered"):
        registry.evaluate("missing", {})


@pytest.mark.parametrize("name", [
    "", "health_" + "a" * 64, "factory_execute_operation", "health_bad-name", "https://other.example",
])
def test_health_model_names_cannot_shadow_operations(name):
    with pytest.raises(ValueError):
        HealthDefinition(name, "Description")


def test_duplicate_health_registrations_fail_at_composition():
    with pytest.raises(ValueError, match="Duplicate"):
        HealthRegistry([ApiHealthModel(FakeProbe()), ApiHealthModel(FakeProbe())])


def test_health_models_require_closed_strict_argument_models():
    class OpenArguments(BaseModel):
        value: str

    with pytest.raises(ValueError, match="strict"):
        HealthDefinition("health_custom", "Description", arguments=OpenArguments)


def test_injected_health_model_accepts_its_own_validated_schema():
    class Arguments(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        expected_version: str

    class VersionHealth:
        definition = HealthDefinition("health_version", "Compare the reported API version.", Arguments)

        def evaluate(self, arguments):
            return {"ok": True, "data": {"expected": arguments["expected_version"]}}

    registry = HealthRegistry([VersionHealth()])
    assert registry.evaluate("health_version", {"expected_version": "1.0.0"})["data"]["expected"] == "1.0.0"
    for args in ({}, {"expected_version": 1}, {"expected_version": "1", "scope": "other"}):
        with pytest.raises(ValueError):
            registry.evaluate("health_version", args)


def test_backend_dispatches_injected_health_models_without_transport_changes(setup_backend):
    from aifactory_mcp.backend import AgentBackend

    backend, api, store = setup_backend
    probe = FakeProbe()
    injected = AgentBackend(
        backend.runtime, backend.principal, SCOPE, operation_store=store,
        tools_factory=type(backend._tools), health_models=[CustomHealthModel(probe)],
    )
    assert "health_custom_api" in {item["name"] for item in injected.list_tools()}
    assert "factory_health" not in {item["name"] for item in injected.list_tools()}
    assert probe.calls == api.calls == []
    assert injected.call_tool("health_custom_api", {})["ok"] is True
    assert probe.calls == ["api"]
    assert api.calls == []
    assert_error("invalid_arguments", lambda: injected.call_tool("health_custom_api", {"url": "bad"}))
    assert probe.calls == ["api"]
    injected.runtime.settings.auth.grants.clear()
    assert_error("forbidden", lambda: injected.call_tool("health_custom_api", {}))
    assert probe.calls == ["api"]


def test_health_model_result_uses_backend_failure_and_redaction_boundary(setup_backend, monkeypatch):
    from aifactory_mcp.backend import AgentBackend

    backend, _, store = setup_backend
    probe = FakeProbe()
    injected = AgentBackend(
        backend.runtime, backend.principal, SCOPE, operation_store=store,
        health_models=[CustomHealthModel(probe)],
    )
    monkeypatch.setattr(probe, "api_health", lambda: {
        "ok": False, "error": {"code": "factory_timeout", "status_code": 503, "message": "private-key"},
    })
    failure = assert_error("factory_timeout", lambda: injected.call_tool("health_custom_api", {}))
    assert "private-key" not in str(failure)
    monkeypatch.setattr(probe, "api_health", lambda: {"ok": True, "data": {"password": "private-key"}})
    assert injected.call_tool("health_custom_api", {})["data"]["password"] == "<redacted>"


@pytest.mark.anyio
async def test_composition_factory_is_per_caller_and_visible_over_mcp(runtime):
    from aifactory_mcp.backend import AgentBackend

    probes = []

    def models(probe):
        probes.append(probe)
        return [CustomHealthModel(FakeProbe())]

    runtime = replace(runtime, health_models_factory=models)
    first = runtime.backend(runtime.local_principal(CALLER), SCOPE)
    second = runtime.backend(runtime.local_principal(CALLER), SCOPE)
    assert isinstance(first, AgentBackend)
    assert probes[0] is not probes[1]
    server = create_server(runtime, SCOPE, object_id=CALLER)
    async with create_connected_server_and_client_session(server) as session:
        names = {item.name for item in (await session.list_tools()).tools}
        assert "health_custom_api" in names
        result = await session.call_tool("health_custom_api", {})
        assert not result.isError
        assert result.structuredContent["data"]["status"] == "ok"


def test_load_runtime_accepts_explicit_health_composition(config_path):
    from aifactory_mcp.runtime import load_runtime

    factory = lambda probe: [CustomHealthModel(FakeProbe())]
    runtime = load_runtime(config_path, health_models_factory=factory)
    assert runtime.health_models_factory is factory
    assert runtime.backend(runtime.local_principal(CALLER), SCOPE).call_tool("health_custom_api", {})["ok"]


def test_version_health_example_has_independent_policy_and_no_discovery_io(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "usecase_code" / "health_models.py"
    spec = importlib.util.spec_from_file_location("example_health_models", path)
    example = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, example)
    spec.loader.exec_module(example)
    probe = FakeProbe()
    registry = HealthRegistry(example.health_models(probe))
    assert len(registry.descriptors()) == 3
    assert probe.calls == []
    assert registry.evaluate("health_api_version", {"expected_version": "1.0.0"})["data"]["status"] == "healthy"
    assert registry.evaluate("health_api_version", {"expected_version": "2.0.0"})["data"]["status"] == "degraded"
    monkeypatch.setattr(probe, "api_health", lambda: {"ok": True, "data": {}})
    assert registry.evaluate("health_api_version", {"expected_version": "1"})["ok"] is False
    failure = {"ok": False, "error": {"code": "factory_timeout"}}
    monkeypatch.setattr(probe, "api_health", lambda: failure)
    assert registry.evaluate("health_api_version", {"expected_version": "1"}) is failure


@pytest.mark.anyio
async def test_custom_health_model_is_discovered_by_readonly_foundry_host(runtime):
    from aifactory_mcp.host import _discover

    runtime = replace(runtime, health_models_factory=lambda probe: [CustomHealthModel(FakeProbe())])
    async with create_connected_server_and_client_session(
        create_server(runtime, SCOPE, object_id=CALLER),
    ) as session:
        descriptors, names = await _discover(session)
        assert "health_custom_api" in names
        definition = next(item for item in descriptors if item["name"] == "health_custom_api")
        assert definition["parameters"]["additionalProperties"] is False
        assert "factory_execute_operation" not in names
