"""Infrastructure adapters: Azure CLI/identity transports, resilience decorators, proxies, offline family."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aifactory_healthmodel.client import HealthModelError
from aifactory_healthmodel.infrastructure import azure_cli, identity
from aifactory_healthmodel.infrastructure.azure_cli import AzCliTransport, AzureCliInfrastructure
from aifactory_healthmodel.infrastructure.offline import OfflineInfrastructure
from aifactory_healthmodel.infrastructure.proxies import ReadOnlyDeployer, ReadOnlyTransport, ReadOnlyViolation
from aifactory_healthmodel.infrastructure.resilience import (CircuitBreakerTransport, CircuitOpenError,
                                                             RetryingTransport, RetryPolicy, is_transient)

ARM = "https://management.azure.com"
SUB = "00000000-0000-0000-0000-0000000000aa"
ARG = f"{ARM}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"


# ---------------------------------------------------------------- Azure CLI and identity adapters
def test_az_launcher_never_uses_a_batch_shell(tmp_path, monkeypatch):
    wbin = tmp_path / "CLI2" / "wbin"
    wbin.mkdir(parents=True)
    (wbin / "az.cmd").write_text("@echo off", encoding="utf-8")
    (tmp_path / "CLI2" / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(azure_cli.shutil, "which", lambda name: str(wbin / "az.cmd") if name in ("az.cmd", "az") else None)
    assert azure_cli.az_command() == [str(tmp_path / "CLI2" / "python.exe"), "-IBm", "azure.cli"]
    (tmp_path / "CLI2" / "python.exe").unlink()
    with pytest.raises(RuntimeError, match="batch"):
        azure_cli.az_command()


def test_az_cli_transport_passes_body_by_file_and_maps_arm_errors():
    seen = {}

    def runner(args, input_text=None):
        seen["args"] = args
        seen["body"] = json.loads(Path(args[args.index("--body") + 1][1:]).read_text(encoding="utf-8"))
        error = 'ERROR: Bad Request({"error":{"code":"InvalidEntity","message":"Signal x is invalid"}})'
        return subprocess.CompletedProcess(args, 1, "", error)

    with pytest.raises(HealthModelError) as caught:
        AzCliTransport(runner).request("POST", f"{ARM}/x?api-version=1&a=b", {"k": "v"})
    assert caught.value.code == "InvalidEntity" and "Signal x is invalid" in str(caught.value)
    assert caught.value.status == 400
    assert seen["body"] == {"k": "v"}
    assert seen["args"][seen["args"].index("--url") + 1].endswith("&a=b")
    assert not Path(seen["args"][seen["args"].index("--body") + 1][1:]).exists(), "temporary body file removed"


@pytest.mark.parametrize("stderr,status", [
    ('ERROR: Too Many Requests({"error":{"code":"TooManyRequests","message":"slow down"}})', 429),
    ("ERROR: (ServiceUnavailable) The service is unavailable.", 503),
    ("ERROR: Not Found({\"error\":{\"code\":\"ResourceNotFound\"}})", 404),
    ("ERROR: token=abc.def secret stuff", None),
])
def test_arm_errors_carry_the_http_status_without_raw_output(stderr, status):
    error = azure_cli.arm_error(subprocess.CompletedProcess([], 1, "", stderr), "GET /x")
    assert error.status == status
    assert "abc.def" not in str(error)


def test_token_transport_uses_bearer_token_and_json(monkeypatch):
    class Credential:
        def get_token(self, scope):
            assert scope == f"{ARM}/.default"
            return type("T", (), {"token": "secret-token"})()

    captured = {}

    class Response:
        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = request.data
        return Response()

    monkeypatch.setattr(identity.urllib.request, "urlopen", fake_urlopen)
    result = identity.TokenTransport(Credential()).request("POST", f"{ARM}/x", {"a": 1})
    assert result == {"ok": True} and captured["auth"] == "Bearer secret-token"
    assert json.loads(captured["body"]) == {"a": 1}
    with pytest.raises(ValueError):
        identity.TokenTransport(Credential()).request("GET", "https://evil.example.com/x")


def test_azure_cli_family_scopes_discovery_and_deployments(tmp_path):
    calls, bodies = [], []

    def runner(args, input_text=None):
        calls.append(args)
        if args[:1] == ["rest"]:
            bodies.append(json.loads(Path(args[args.index("--body") + 1][1:]).read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(args, 0, json.dumps({"data": [{"id": "x"}], "$skipToken": None}), "")
        return subprocess.CompletedProcess(args, 0, json.dumps({"changes": [{"changeType": "NoChange"}] * 2}), "")

    family = AzureCliInfrastructure(SUB, runner=runner)
    transport = family.create_transport()
    rows = family.create_discovery(transport).discover(["rg-a", "rg-b"], include_health_models=True)
    assert rows == [{"id": "x"}]
    assert bodies[0]["subscriptions"] == [SUB]
    assert "'rg-a', 'rg-b'" in bodies[0]["query"] and "microsoft.cloudhealth/healthmodels" in bodies[0]["query"]
    counts = family.create_deployer().what_if("rg-a", tmp_path / "main.bicep", tmp_path / "p.json")
    assert counts == {"NoChange": 2}
    assert calls[-1][:3] == ["deployment", "group", "what-if"] and SUB in calls[-1]


# ---------------------------------------------------------------- resilience decorators
class Flaky:
    """Transport that fails with the given errors before succeeding."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def request(self, method, url, body=None):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"ok": True}


def busy(status=503):
    return HealthModelError("busy", "ServiceUnavailable" if status == 503 else "TooManyRequests", status)


def test_transient_errors_are_recognised():
    assert is_transient(busy(503)) and is_transient(busy(429))
    assert not is_transient(HealthModelError("bad", "InvalidEntity", 400))
    assert not is_transient(ValueError("x"))


def test_retry_decorator_backs_off_for_idempotent_calls():
    sleeps = []
    inner = Flaky(busy(), busy())
    transport = RetryingTransport(inner, RetryPolicy(attempts=4, base_delay=1, max_delay=8, jitter=0),
                                  sleep=sleeps.append)
    assert transport.request("GET", f"{ARM}/x") == {"ok": True}
    assert inner.calls == 3 and sleeps == [1, 2]


def test_retry_decorator_gives_up_after_the_last_attempt():
    inner = Flaky(*[busy()] * 5)
    transport = RetryingTransport(inner, RetryPolicy(attempts=3, base_delay=0, jitter=0), sleep=lambda s: None)
    with pytest.raises(HealthModelError):
        transport.request("PUT", f"{ARM}/x", {})
    assert inner.calls == 3


def test_non_idempotent_posts_are_only_retried_when_throttled():
    no_retry = Flaky(busy(503))
    with pytest.raises(HealthModelError):
        RetryingTransport(no_retry, RetryPolicy(base_delay=0, jitter=0), sleep=lambda s: None).request(
            "POST", f"{ARM}/x/ingestHealthReport", {})
    assert no_retry.calls == 1
    throttled = Flaky(busy(429))
    RetryingTransport(throttled, RetryPolicy(base_delay=0, jitter=0), sleep=lambda s: None).request(
        "POST", f"{ARM}/x/ingestHealthReport", {})
    assert throttled.calls == 2
    query = Flaky(busy(503))
    RetryingTransport(query, RetryPolicy(base_delay=0, jitter=0), sleep=lambda s: None).request("POST", ARG, {})
    assert query.calls == 2, "Resource Graph queries are read-only and safe to retry"


def test_client_errors_are_not_retried():
    inner = Flaky(HealthModelError("bad", "InvalidEntity", 400))
    with pytest.raises(HealthModelError):
        RetryingTransport(inner, RetryPolicy(base_delay=0, jitter=0), sleep=lambda s: None).request("GET", f"{ARM}/x")
    assert inner.calls == 1


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_circuit_breaker_states():
    clock = Clock()
    inner = Flaky(*[busy()] * 3)
    breaker = CircuitBreakerTransport(inner, failure_threshold=2, reset_timeout=30, clock=clock)
    assert breaker.state_name == "closed"
    for _ in range(2):
        with pytest.raises(HealthModelError):
            breaker.request("GET", f"{ARM}/x")
    assert breaker.state_name == "open"
    with pytest.raises(CircuitOpenError):
        breaker.request("GET", f"{ARM}/x")
    assert inner.calls == 2, "an open circuit fails fast without calling Azure"
    clock.now = 31
    with pytest.raises(HealthModelError):
        breaker.request("GET", f"{ARM}/x")
    assert breaker.state_name == "open", "a failed trial call re-opens the circuit"
    clock.now = 62
    assert breaker.request("GET", f"{ARM}/x") == {"ok": True}
    assert breaker.state_name == "closed"


def test_circuit_breaker_ignores_client_errors():
    inner = Flaky(*[HealthModelError("missing", "ResourceNotFound", 404)] * 3)
    breaker = CircuitBreakerTransport(inner, failure_threshold=2, reset_timeout=30, clock=Clock())
    for _ in range(3):
        with pytest.raises(HealthModelError):
            breaker.request("GET", f"{ARM}/x")
    assert breaker.state_name == "closed"


def test_half_open_circuit_allows_one_trial_and_closes_when_azure_answers():
    clock = Clock()
    inner = Flaky(busy(), busy(), HealthModelError("missing", "ResourceNotFound", 404))
    breaker = CircuitBreakerTransport(inner, failure_threshold=2, reset_timeout=30, clock=clock)
    for _ in range(2):
        with pytest.raises(HealthModelError):
            breaker.request("GET", f"{ARM}/x")
    clock.now = 31
    breaker._state.before_call(breaker)  # a concurrent trial is already running
    with pytest.raises(CircuitOpenError):
        breaker.request("GET", f"{ARM}/x")
    breaker._transition(type(breaker._state)())
    with pytest.raises(HealthModelError, match="missing"):
        breaker.request("GET", f"{ARM}/x")
    assert breaker.state_name == "closed", "a 404 proves Azure is reachable"


def test_retry_stops_when_the_circuit_opens():
    inner = Flaky(*[busy()] * 10)
    transport = RetryingTransport(CircuitBreakerTransport(inner, failure_threshold=2, reset_timeout=30, clock=Clock()),
                                  RetryPolicy(attempts=5, base_delay=0, jitter=0), sleep=lambda s: None)
    with pytest.raises(CircuitOpenError):
        transport.request("GET", f"{ARM}/x")
    assert inner.calls == 2


# ---------------------------------------------------------------- protection proxies
def test_read_only_transport_blocks_writes():
    inner = Flaky()
    proxy = ReadOnlyTransport(inner)
    proxy.request("GET", f"{ARM}/x")
    proxy.request("POST", ARG, {"query": "resources"})
    proxy.request("POST", f"{ARM}/x/providers/Microsoft.CloudHealth/healthmodels/m/getHistory?api-version=1", {})
    for method, url in (("PUT", f"{ARM}/x"), ("DELETE", f"{ARM}/x"), ("PATCH", f"{ARM}/x"),
                        ("POST", f"{ARM}/x/ingestHealthReport?api-version=1")):
        with pytest.raises(ReadOnlyViolation):
            proxy.request(method, url, {})
    assert inner.calls == 3


def test_read_only_deployer_allows_what_if_only(tmp_path):
    class Deployer:
        def what_if(self, *args):
            return {"NoChange": 1}

        def deploy(self, *args):
            raise AssertionError("must not deploy")

    proxy = ReadOnlyDeployer(Deployer())
    assert proxy.what_if("rg", tmp_path, tmp_path) == {"NoChange": 1}
    with pytest.raises(ReadOnlyViolation):
        proxy.deploy("name", "rg", tmp_path, tmp_path)


# ---------------------------------------------------------------- offline family
def test_offline_family_plans_from_an_inventory_without_azure(test_env_resources, tmp_path):
    other = {**test_env_resources[0], "id": test_env_resources[0]["id"].replace(SUB, "00000000-0000-0000-0000-0000000000bb")}
    family = OfflineInfrastructure([*test_env_resources, other], subscription_id=SUB, tenant_id="t")
    assert family.create_account_verifier().verify_account("t")["offline"] is True
    providers = family.create_provider_registrar(family.create_transport())
    assert providers.provider()["registrationState"] == "Registered"
    rows = family.create_discovery(family.create_transport()).discover(["spider-esml-project001-sdc-dev-001-rg"])
    assert rows and all(r["resourceGroup"] == "spider-esml-project001-sdc-dev-001-rg" for r in rows)
    assert all(SUB in r["id"] for r in rows)
    deployer = family.create_deployer()
    assert deployer.what_if("rg", tmp_path, tmp_path) == "skipped: offline inventory"
    with pytest.raises(RuntimeError, match="offline"):
        deployer.deploy("n", "rg", tmp_path, tmp_path)
    with pytest.raises(RuntimeError, match="offline"):
        family.create_transport().request("GET", f"{ARM}/x")
