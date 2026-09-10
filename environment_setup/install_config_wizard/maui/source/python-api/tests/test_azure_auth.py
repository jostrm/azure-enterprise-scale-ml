import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, azure_auth, operations, wizard
from src.azure_auth import AuthRequestError, AzureAuthService


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
TENANT_C = "33333333-3333-4333-8333-333333333333"
SUB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SUB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SECRET = "accessToken-secret-do-not-return"


def account(tenant=TENANT_A, subscription=SUB_A, default=True):
    return {
        "id": subscription, "tenantId": tenant, "isDefault": default,
        "accountName": "person@example.org", "accessToken": SECRET,
    }


def token(tenant=TENANT_A, expired=False):
    expiry = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)
    return {"tenant": tenant, "expiresOn": expiry.isoformat(), "accessToken": SECRET}


class FakeCLI:
    def __init__(self):
        self.accounts = [account()]
        self.tokens = {TENANT_A: token()}
        self.calls = []
        self.on_login = None
        self.on_logout = None

    def __call__(self, argv, **kwargs):
        assert argv[0] == "mock-azure-cli"
        self.calls.append((list(argv), kwargs))
        command = argv[1:3]
        if command == ["account", "list"]:
            value = self.accounts
        elif command == ["account", "get-access-token"]:
            tenant = argv[argv.index("--tenant") + 1]
            value = self.tokens.get(tenant)
            if value is None:
                return SimpleNamespace(returncode=1, stdout=SECRET, stderr="Please run az login. " + SECRET)
        elif argv[1] == "login":
            if self.on_login:
                self.on_login(argv)
            return SimpleNamespace(returncode=0, stdout=SECRET, stderr=SECRET)
        elif argv[1] == "logout":
            if self.on_logout:
                self.on_logout()
            else:
                self.accounts = []
                self.tokens = {}
            return SimpleNamespace(returncode=0, stdout=SECRET, stderr=SECRET)
        else:
            pytest.fail(f"Unexpected CLI command: {argv[1:3]}")
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch):
    monkeypatch.setattr(operations, "resolve_azure_cli", lambda: "resolved-cli")
    monkeypatch.setattr(operations, "_azure_cli_command", lambda value: ["mock-azure-cli"])
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("Real subprocess forbidden")))


@pytest.fixture
def cli():
    return FakeCLI()


@pytest.fixture
def service(cli):
    return AzureAuthService(runner=cli)


def factory(root, tenant=TENANT_A, subscriptions=(SUB_A,)):
    root.mkdir(parents=True, exist_ok=True)
    values = {"tenantId": tenant}
    values.update(zip(("dev_sub_id", "test_sub_id", "prod_sub_id"), subscriptions))
    (root / "variables.json").write_text(
        json.dumps({"dev": values, "stage_prod": {}}), encoding="utf-8",
    )
    return str(root)


def finished(service, pending):
    deadline = time.monotonic() + 3
    with service._condition:
        while service._active and time.monotonic() < deadline:
            service._condition.wait(0.05)
    result = service.operation(pending.operation_id)
    assert result.state not in ("signing_in", "signing_out")
    return result


@pytest.mark.parametrize("expired", [True, False])
def test_status_verifies_tokens_not_cached_accounts(service, cli, expired):
    cli.tokens[TENANT_A] = token(expired=expired)
    result = service.status()
    assert result.state == ("login_required" if expired else "signed_in")
    assert result.is_logged_in is not expired
    assert result.tenants[0].needs_login is expired
    assert result.account_name == "person@example.org"
    assert len(cli.calls) == 2
    account_args, token_args = cli.calls[0][0], cli.calls[1][0]
    assert account_args[1:4] == ["account", "list", "--all"]
    assert "--query" in account_args
    assert token_args[token_args.index("--query") + 1] == "{expiresOn:expiresOn,tenant:tenant}"
    assert token_args[token_args.index("--resource") + 1] == "https://management.azure.com/"
    assert all(args[1] not in ("login", "logout") for args, _ in cli.calls)
    serialized = json.dumps(asdict(result))
    assert SECRET not in serialized and "accessToken" not in serialized


def test_multi_tenant_partial_login_checks_subscription_mapping(service, cli, tmp_path):
    folder = factory(tmp_path / "aifactory", subscriptions=(SUB_A, SUB_B))
    configure_stage_tenant(tmp_path / "aifactory", TENANT_B)
    cli.accounts.append(account(TENANT_B, SUB_B, False))
    result = service.status(folder)
    assert result.state == "login_required"
    assert result.is_logged_in is False
    assert {t.tenant_id: t.needs_login for t in result.tenants} == {
        TENANT_A: False, TENANT_B: True,
    }
    assert {args[args.index("--tenant") + 1] for args, _ in cli.calls if "--tenant" in args} == {
        TENANT_A, TENANT_B,
    }


def test_unknown_subscriptions_reported_without_claiming_resource_access(service, tmp_path):
    folder = factory(tmp_path / "aifactory", subscriptions=(SUB_A, SUB_B))
    result = service.status(folder)
    assert result.is_logged_in
    assert SUB_B in result.message and "unverified" in result.message
    assert "RBAC" in result.message


def test_unknown_subscription_without_tenant_does_not_use_unrelated_default(service, tmp_path):
    folder = factory(tmp_path / "aifactory", tenant="", subscriptions=(SUB_B,))
    result = service.status(folder)
    assert not result.is_logged_in
    assert not result.tenants
    assert SUB_B in result.message


def test_source_full_factory_excludes_other_scale_set_and_root_tenants(service, cli, tmp_path, monkeypatch):
    root = tmp_path / "aifactory"
    folder = factory(root)
    config = root / "config-wizard"
    config.mkdir()
    (config / "factory_state.json").write_text(json.dumps({
        "tenantId": TENANT_B, "orchestrator": "ado",
    }), encoding="utf-8")
    scale_sets = config / "scalesets"
    scale_sets.mkdir()
    (scale_sets / "scaleset_001.json").write_text(json.dumps({
        "tenantId": TENANT_C, "dev_sub_id": SUB_B,
    }), encoding="utf-8")
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(operations, "OperationsStore", Mock(side_effect=AssertionError("No database")))
    monkeypatch.setattr(wizard, "_save_app_settings", Mock(side_effect=AssertionError("No settings")))
    result = service.status(folder)
    assert {t.tenant_id for t in result.tenants} == {TENANT_B}
    assert before == {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("source_kind", ["yaml", "env"])
def test_read_only_source_tenant_fallback(service, tmp_path, source_kind):
    root = tmp_path / "repo" / "aifactory"
    root.mkdir(parents=True)
    if source_kind == "env":
        (root.parent / ".env").write_text(f"TENANT_ID={TENANT_B}\n", encoding="utf-8")
    else:
        source = root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(f"variables:\n  tenantId: {TENANT_B}\n", encoding="utf-8")
    assert service.status(str(root)).tenants[0].tenant_id == TENANT_B


@pytest.mark.parametrize("bad_folder", ["", "relative", "bad\x00folder"])
def test_invalid_folder_does_not_call_cli(service, cli, bad_folder):
    with pytest.raises(AuthRequestError, match="existing absolute folder"):
        service.status(bad_folder)
    assert not cli.calls


@pytest.mark.parametrize("content", ['{"dev":', '[]', '{"dev":{"tenantId":"not-a-uuid"}}'])
def test_malformed_configuration_safe_error(service, cli, tmp_path, content):
    (tmp_path / "variables.json").write_text(content, encoding="utf-8")
    with pytest.raises(AuthRequestError) as error:
        service.status(str(tmp_path))
    assert str(tmp_path) not in str(error.value)
    assert content not in str(error.value)
    assert not cli.calls


def test_default_context_uses_only_default_tenant(service, cli):
    cli.accounts.append(account(TENANT_B, SUB_B, False))
    assert [item.tenant_id for item in service.status().tenants] == [TENANT_A]


@pytest.mark.parametrize("failure", [
    SimpleNamespace(returncode=1, stdout=SECRET, stderr="Network failed " + SECRET),
    SimpleNamespace(returncode=0, stdout=SECRET, stderr=SECRET),
    subprocess.TimeoutExpired(["az"], 30, output=SECRET, stderr=SECRET),
    OSError(SECRET),
])
def test_cli_failures_are_safe(failure):
    runner = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    result = AzureAuthService(runner=runner).status()
    assert result.state == "error"
    assert SECRET not in json.dumps(asdict(result))


def test_cli_missing_distinct_unavailable(service, monkeypatch):
    monkeypatch.setattr(operations, "resolve_azure_cli", Mock(side_effect=RuntimeError(SECRET)))
    assert service.status().state == "unavailable"
    result = finished(service, service.login())
    assert result.state == "unavailable"
    assert SECRET not in result.message


@pytest.mark.parametrize("metadata", [
    {}, {"tenant": TENANT_B}, {"tenant": TENANT_A, "expiresOn": "bad " + SECRET},
])
def test_invalid_token_metadata_is_not_signed_in(service, cli, metadata):
    cli.tokens[TENANT_A] = metadata
    result = service.status()
    assert result.state == "error"
    assert not result.is_logged_in
    assert SECRET not in json.dumps(asdict(result))


def test_absent_expiry_allowed_when_token_command_succeeds(service, cli):
    cli.tokens[TENANT_A] = {"tenant": TENANT_A}
    assert service.status().is_logged_in


def test_cache_context_expiry_and_defensive_copy(cli, tmp_path):
    now = [10.0]
    service = AzureAuthService(runner=cli, clock=lambda: now[0])
    a = factory(tmp_path / "a")
    b = factory(tmp_path / "b", tenant=TENANT_B, subscriptions=(SUB_B,))
    service.status(a).tenants.clear()
    assert len(service.status(a).tenants) == 1
    assert len(cli.calls) == 2
    assert service.status(b).tenants[0].tenant_id == TENANT_B
    assert len(cli.calls) == 4
    now[0] += 21
    service.status(a)
    assert len(cli.calls) == 6
    factory(tmp_path / "a", tenant=TENANT_B, subscriptions=(SUB_B,))
    assert service.status(a).tenants[0].tenant_id == TENANT_B
    assert len(cli.calls) == 8


def test_concurrent_status_calls_coalesce(cli):
    entered, release = threading.Event(), threading.Event()

    def runner(argv, **kwargs):
        if argv[1:3] == ["account", "list"]:
            entered.set()
            assert release.wait(2)
        return cli(argv, **kwargs)

    service = AzureAuthService(runner=runner)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(service.status) for _ in range(4)]
        assert entered.wait(1)
        release.set()
        assert all(future.result().is_logged_in for future in futures)
    assert len(cli.calls) == 2


def test_status_finishing_after_logout_cannot_repopulate_stale_cache(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = service._probe
    first = [True]

    def delayed(context):
        result = original(context)
        if first[0]:
            first[0] = False
            entered.set()
            assert release.wait(2)
        return result

    monkeypatch.setattr(service, "_probe", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.status)
        assert entered.wait(1)
        finished(service, service.logout())
        release.set()
        assert future.result().state == "signed_out"
    assert service.status().state == "signed_out"


def test_login_async_explicit_cli_flags_shared_cache_and_overlap(service, cli, tmp_path):
    folder = factory(tmp_path / "a")
    other = factory(tmp_path / "b", tenant=TENANT_B, subscriptions=(SUB_B,))
    cli.tokens.clear()
    service.status(folder)
    entered, release = threading.Event(), threading.Event()
    parent_env = dict(os.environ)

    def login(argv):
        entered.set()
        assert release.wait(2)
        cli.tokens[TENANT_A] = token()

    cli.on_login = login
    pending = service.login(folder)
    try:
        assert pending.state == "signing_in" and pending.operation_id
        assert entered.wait(1)
        assert service.login(folder).operation_id == pending.operation_id
        with pytest.raises(AuthRequestError) as conflict:
            service.logout(folder)
        assert conflict.value.status_code == 409
        before_count = len(cli.calls)
        assert service.status(folder).state == "signing_in"
        assert service.status(other).tenants == []
        assert len(cli.calls) == before_count
        assert dict(os.environ) == parent_env
    finally:
        release.set()
    result = finished(service, pending)
    assert result.is_logged_in and result.state == "signed_in"
    login_calls = [(args, kwargs) for args, kwargs in cli.calls if args[1] == "login"]
    assert len(login_calls) == 1
    args, kwargs = login_calls[0]
    assert args == [
        "mock-azure-cli", "login", "--tenant", TENANT_A, "--allow-no-subscriptions",
        "--output", "none", "--only-show-errors",
    ]
    assert kwargs["shell"] is False
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 300
    assert kwargs["env"]["AZURE_CORE_LOGIN_EXPERIENCE_V2"] == "off"
    assert kwargs["env"]["AZURE_CORE_ENABLE_BROKER_ON_WINDOWS"] == "false"
    assert kwargs["env"]["AZURE_LOGGING_ENABLE_LOG_FILE"] == "false"
    assert not any(args[1] in ("config", "logout") for args, _ in cli.calls)
    count = len(cli.calls)
    assert service.status(folder).is_logged_in
    assert len(cli.calls) > count
    assert SECRET not in json.dumps(asdict(result))


def test_first_login_omits_tenant_for_microsoft_chooser(service, cli):
    cli.accounts = []
    cli.tokens = {}

    def login(argv):
        assert "--tenant" not in argv
        cli.accounts = [account()]
        cli.tokens[TENANT_A] = token()

    cli.on_login = login
    assert finished(service, service.login()).is_logged_in


def test_multiple_failed_tenants_require_choice_and_recheck_all(service, cli, tmp_path):
    folder = factory(tmp_path / "a", subscriptions=(SUB_A, SUB_B))
    configure_stage_tenant(tmp_path / "a", TENANT_B)
    cli.accounts.append(account(TENANT_B, SUB_B, False))
    cli.tokens.clear()
    result = finished(service, service.login(folder))
    assert result.state == "error"
    assert "Choose a tenant" in result.message
    assert not any(args[1] == "login" for args, _ in cli.calls)
    cli.on_login = lambda argv: cli.tokens.update({TENANT_A: token()})
    result = finished(service, service.login(folder, TENANT_A))
    assert result.state == "login_required"
    assert not result.is_logged_in
    assert {item.tenant_id: item.needs_login for item in result.tenants} == {
        TENANT_A: False, TENANT_B: True,
    }


def configure_stage_tenant(root, tenant):
    path = root / "variables.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["stage_prod"] = {"tenantId": tenant, "test_sub_id": SUB_B, "prod_sub_id": SUB_B}
    path.write_text(json.dumps(document), encoding="utf-8")


def test_unexpected_cli_tenant_is_not_added_to_active_factory_context(service, cli, tmp_path):
    folder = factory(tmp_path / "a")
    cli.accounts = [account(TENANT_B, SUB_A)]
    result = service.status(folder)
    assert result.state == "error"
    assert "does not match" in result.message
    assert not any("--tenant" in argv for argv, _ in cli.calls)


@pytest.mark.parametrize("invalid", ["--debug", TENANT_A + " & echo bad", "", "x"])
def test_tenant_arg_injection_rejected(service, cli, invalid):
    with pytest.raises(AuthRequestError, match="tenant UUID"):
        service.login(tenant_id=invalid)
    assert not cli.calls


def test_foreign_tenant_rejected_with_and_without_cached_status(service, cli, tmp_path):
    folder = factory(tmp_path / "a")
    result = finished(service, service.login(folder, TENANT_C))
    assert result.state == "error"
    assert "does not belong" in result.message
    assert not any(args[1] == "login" for args, _ in cli.calls)
    service.status(folder)
    with pytest.raises(AuthRequestError, match="does not belong"):
        service.login(folder, TENANT_C)


def test_logout_only_cli_cache_and_verification(service, cli, tmp_path):
    folder = factory(tmp_path / "a")
    service.status(folder)
    result = finished(service, service.logout(folder))
    assert result.state == "signed_out" and not result.is_logged_in
    assert "Other Azure CLI tooling" in result.message
    assert cli.accounts == [] and cli.tokens == {}
    assert service.status(folder).state == "signed_out"
    assert len([args for args, _ in cli.calls if args[1] == "logout"]) == 1
    assert not any(args[1] in ("login", "config") for args, _ in cli.calls)
    assert SECRET not in json.dumps(asdict(result))


@pytest.mark.parametrize("retain_accounts", [True, False])
def test_logout_detects_success_shaped_noop(service, cli, retain_accounts):
    def noop():
        if not retain_accounts:
            cli.accounts = []

    cli.on_logout = noop
    result = finished(service, service.logout())
    assert result.state == "error"
    assert "could not be verified" in result.message


def test_mutation_invalidates_other_folder_cache(service, cli, tmp_path):
    a = factory(tmp_path / "a")
    b = factory(tmp_path / "b")
    assert service.status(a).is_logged_in
    assert service.status(b).is_logged_in
    finished(service, service.logout(a))
    assert service.status(b).is_logged_in is False


@pytest.mark.parametrize("exception", [
    subprocess.TimeoutExpired(["az", "login"], 300, output=SECRET, stderr=SECRET),
    OSError(SECRET), RuntimeError(SECRET),
])
def test_worker_failures_finish_and_do_not_log_output(service, cli, caplog, exception):
    def login(argv):
        raise exception

    cli.on_login = login
    result = finished(service, service.login())
    assert result.state == "error"
    assert SECRET not in result.message and SECRET not in caplog.text
    assert service._active is None
    assert service.operation(result.operation_id) == result


def test_recent_jobs_bounded(service, cli):
    service.MAX_RECENT = 2
    first = finished(service, service.logout())
    second = finished(service, service.logout())
    third = finished(service, service.logout())
    assert service.operation(first.operation_id) is None
    assert service.operation(second.operation_id) is not None
    assert service.operation(third.operation_id) is not None


@pytest.fixture
def api_service(service, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "test-auth-key")
    monkeypatch.setattr(azure_auth, "azure_auth_service", service)
    return service


@pytest.mark.parametrize(("method", "path"), [
    ("post", "/api/v1/azure/auth/status"),
    ("post", "/api/v1/azure/auth/login"),
    ("post", "/api/v1/azure/auth/logout"),
    ("get", "/api/v1/azure/auth/operations/unknown"),
])
def test_all_auth_endpoints_require_key(api_service, cli, method, path):
    with TestClient(api.app, client=("127.0.0.1", 12345)) as client:
        for headers in ({}, {"X-API-Key": "wrong"}):
            response = client.request(method, path, headers=headers, **({"json": {}} if method == "post" else {}))
            assert response.status_code == 401
    assert not cli.calls


@pytest.mark.parametrize("host", ["192.0.2.1", "::ffff:192.0.2.1", "testclient", "localhost"])
@pytest.mark.parametrize("action", ["login", "logout"])
def test_mutation_rejects_nonloopback_even_with_forwarded_header(api_service, cli, host, action):
    with TestClient(api.app, client=(host, 12345)) as client:
        response = client.post(
            f"/api/v1/azure/auth/{action}", json={},
            headers={"X-API-Key": "test-auth-key", "X-Forwarded-For": "127.0.0.1"},
        )
        assert response.status_code == 403
    assert not cli.calls


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"])
def test_loopback_mutation_and_poll_contract(api_service, host):
    with TestClient(api.app, client=(host, 12345)) as client:
        headers = {"X-API-Key": "test-auth-key"}
        response = client.post("/api/v1/azure/auth/logout", json={}, headers=headers)
        assert response.status_code == 200
        pending = azure_auth.AzureAuthStatus(**{**response.json(), "tenants": []})
        finished(api_service, pending)
        response = client.get(
            f"/api/v1/azure/auth/operations/{pending.operation_id}", headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["state"] == "signed_out"
        assert set(response.json()) == {
            "state", "is_logged_in", "account_name", "tenant_id", "message", "tenants", "operation_id",
        }
        assert SECRET not in response.text
        assert client.get("/api/v1/azure/auth/operations/unknown", headers=headers).status_code == 404


def test_status_remote_read_allowed_and_safe_validation(api_service):
    with TestClient(api.app, client=("192.0.2.1", 12345)) as client:
        headers = {"X-API-Key": "test-auth-key"}
        assert client.post("/api/v1/azure/auth/status", json={}, headers=headers).json()["is_logged_in"]
        response = client.post(
            "/api/v1/azure/auth/status", json={"aifactory_folder": "bad\x00folder"}, headers=headers,
        )
        assert response.status_code == 422
        assert "bad" not in response.text


def test_api_login_validation_and_active_conflict(api_service, cli):
    entered, release = threading.Event(), threading.Event()

    def login(argv):
        entered.set()
        assert release.wait(2)

    cli.on_login = login
    with TestClient(api.app, client=("127.0.0.1", 12345)) as client:
        headers = {"X-API-Key": "test-auth-key"}
        invalid = client.post(
            "/api/v1/azure/auth/login", json={"tenant_id": "--debug"}, headers=headers,
        )
        assert invalid.status_code == 422
        assert not cli.calls
        pending = client.post("/api/v1/azure/auth/login", json={}, headers=headers)
        try:
            assert pending.status_code == 200
            assert pending.json()["state"] == "signing_in"
            assert entered.wait(1)
            assert client.post("/api/v1/azure/auth/logout", json={}, headers=headers).status_code == 409
            same = client.post("/api/v1/azure/auth/login", json={}, headers=headers)
            assert same.json()["operation_id"] == pending.json()["operation_id"]
        finally:
            release.set()
        finished(api_service, azure_auth.AzureAuthStatus(**pending.json()))


def test_api_missing_key_configuration_has_no_cli_side_effects(api_service, cli, monkeypatch):
    monkeypatch.delenv(api.API_KEY_ENV)
    with TestClient(api.app, client=("127.0.0.1", 12345)) as client:
        response = client.post(
            "/api/v1/azure/auth/login", json={}, headers={"X-API-Key": "test-auth-key"},
        )
        assert response.status_code == 503
    assert not cli.calls


def test_reopened_client_recovers_active_job_without_login_response(api_service, cli, tmp_path):
    folder = factory(tmp_path / "a")
    other = factory(tmp_path / "b", tenant=TENANT_B, subscriptions=(SUB_B,))
    entered, release = threading.Event(), threading.Event()
    cli.tokens.clear()

    def login(argv):
        entered.set()
        assert release.wait(3)
        cli.tokens[TENANT_A] = token()

    cli.on_login = login
    headers = {"X-API-Key": "test-auth-key"}
    try:
        with TestClient(api.app, client=("127.0.0.1", 12345)) as first_client:
            # Discard the response/operation ID, just as a closed menu may do.
            first_client.post(
                "/api/v1/azure/auth/login", json={"aifactory_folder": folder}, headers=headers,
            )
        assert entered.wait(1)
        with TestClient(api.app, client=("127.0.0.1", 12346)) as reopened:
            count = len(cli.calls)
            status = reopened.post(
                "/api/v1/azure/auth/status", json={"aifactory_folder": folder}, headers=headers,
            ).json()
            assert status["state"] == "signing_in"
            assert status["operation_id"]
            changed_context = reopened.post(
                "/api/v1/azure/auth/status", json={"aifactory_folder": other}, headers=headers,
            ).json()
            assert changed_context["operation_id"] == status["operation_id"]
            assert changed_context["state"] == "signing_in"
            assert changed_context["tenants"] == []
            assert "Another Azure CLI authentication operation" in changed_context["message"]
            assert len(cli.calls) == count
            release.set()
            result = finished(api_service, azure_auth.AzureAuthStatus(**status))
            assert result.state == "signed_in" and result.is_logged_in
            assert all(not tenant.needs_login for tenant in result.tenants)
            assert "Resource access still depends on RBAC" in result.message
    finally:
        release.set()


def test_openapi_auth_models_and_security(api_service):
    schema = api.app.openapi()
    status = schema["components"]["schemas"]["AzureAuthStatus"]
    assert status["properties"]["state"]["enum"] == [
        "signed_in", "login_required", "signed_out", "signing_in", "signing_out", "unavailable", "error",
    ]
    assert "accessToken" not in json.dumps(status)
    for path, methods in schema["paths"].items():
        if "/azure/auth/" in path:
            for operation in methods.values():
                assert operation["security"] == [{"APIKeyHeader": []}]
                assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/AzureAuthStatus",
                }
