import base64
import json
import socket
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from src import api, azure_auth, operations, ticket_connectors
from src.ticket_connectors import JsonTransport, SyncError, TicketConnector, TicketError, validate_origin
from src.ticketing import AzureTicketIdentity, IDENTITY_FIELDS, TicketService, parse_ticket_resource_group


TENANT = "11111111-1111-4111-8111-111111111111"
SUB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
NOW = 1800000000.0


@pytest.fixture(autouse=True)
def forbid_network_and_cli(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("No real CLI in ticket tests")))
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("No live connector calls")))


@pytest.fixture
def context(tmp_path):
    folder = tmp_path / "factory"
    folder.mkdir()
    (folder / "variables.json").write_text(json.dumps({
        "dev": {"tenantId": TENANT, "dev_sub_id": SUB},
        "stage_prod": {},
    }), encoding="utf-8")
    return str(folder)


@pytest.fixture
def service(tmp_path):
    active_user = [f"azure:{TENANT}:{USER}"]
    clock = [NOW]
    result = TicketService(
        operations.OperationsStore(tmp_path / "ops.db"), identity=lambda folder=None: active_user[0],
        clock=lambda: clock[0],
    )
    result.active_user = active_user
    result.test_clock = clock
    return result


def create(service, folder, **changes):
    return service.create({
        "aifactory_folder": folder, "project_number": "001", "type": "Bug report",
        "title": "Test issue", "description": "No credentials here.", **changes,
    })


def connection(service, **changes):
    return service.save_connection({
        "name": "Jira test", "provider": "Jira", "base_url": "https://example.atlassian.net",
        "project_key": "AI", "username": "test@example.org", "credential_env": "TEST_JIRA_TOKEN", **changes,
    })


def token(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "e30." + payload + ".cli-acquired-not-client-provided"


def identity(monkeypatch, claims=None, account_changes=None):
    claims = claims or {"tid": TENANT, "oid": USER, "exp": NOW + 3600, "aud": "https://management.azure.com/"}
    account = {"id": SUB, "tenantId": TENANT, "isDefault": True, "accountName": "status-name@example.org"}
    account.update(account_changes or {})
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["account", "list"]:
            payload = [account]
        elif argv[1:3] == ["account", "get-access-token"]:
            assert argv[argv.index("--subscription") + 1] == SUB
            payload = {"tenant": TENANT, "accessToken": token(claims)}
        else:
            pytest.fail("Unexpected auth command")
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(operations, "resolve_azure_cli", lambda: "mock-az")
    monkeypatch.setattr(operations, "_azure_cli_command", lambda _: ["mock-az"])
    auth = azure_auth.AzureAuthService(runner=run)
    return AzureTicketIdentity(auth, clock=lambda: NOW), calls


def test_concrete_identity_uses_tenant_oid_from_authenticated_cli_not_status(monkeypatch, context):
    provider, calls = identity(monkeypatch)
    provider.auth.status = Mock(side_effect=AssertionError("cached status is not identity"))
    assert provider(context) == f"azure:{TENANT}:{USER}"
    assert len(calls) == 2
    assert calls[1][1]["env"]["AZURE_LOGGING_ENABLE_LOG_FILE"] == "false"
    assert calls[1][1]["env"]["AZURE_CORE_LOG_LEVEL"] == "critical"
    assert calls[1][1]["shell"] is False
    assert "status-name" not in provider()


@pytest.mark.parametrize("change", [
    {"tid": OTHER}, {"oid": "invalid"}, {"exp": NOW - 1},
    {"nbf": NOW + 300}, {"aud": "https://graph.microsoft.com"},
])
def test_identity_rejects_invalid_claims(monkeypatch, context, change):
    claims = {"tid": TENANT, "oid": USER, "exp": NOW + 3600, "aud": "https://management.azure.com/"}
    provider, _ = identity(monkeypatch, claims={**claims, **change})
    with pytest.raises(TicketError) as error:
        provider(context)
    assert error.value.status_code == 401
    assert token(claims) not in str(error.value)


def test_identity_rejects_factory_tenant_mismatch(monkeypatch, context):
    provider, calls = identity(monkeypatch)
    path = Path(context) / "variables.json"
    path.write_text(json.dumps({"dev": {"tenantId": OTHER, "dev_sub_id": SUB}}))
    with pytest.raises(TicketError) as error:
        provider(context)
    assert error.value.status_code == 403
    assert len(calls) == 1


def test_private_sqlite_persistence_counts_and_owner_isolation(service, context):
    first = create(service, context)
    active = create(service, context)
    solved = create(service, context)
    service.update(active["id"], "Active")
    service.update(solved["id"], "Solved")
    assert service.list_tickets(context)["counts"] == {"new": 1, "active": 1, "solved": 1}
    stored = TicketService(service.store, identity=service.identity)
    assert len(stored.list_tickets(context)["tickets"]) == 3
    service.active_user[0] = f"azure:{TENANT}:{OTHER}"
    assert service.list_tickets()["tickets"] == []
    with pytest.raises(TicketError) as error:
        service.update(first["id"], "Solved")
    assert error.value.status_code == 404
    conn = connection(service)
    service.active_user[0] = f"azure:{TENANT}:{USER}"
    assert service.list_connections()["connections"] == []
    with pytest.raises(TicketError):
        service.preview(first["id"], conn["id"])


def test_list_is_not_silently_truncated_at_500(service, context):
    for index in range(503):
        create(service, context, title=f"Ticket {index}")
    result = service.list_tickets(context)
    assert len(result["tickets"]) == 503
    assert result["counts"]["new"] == 503


def test_list_scope_excludes_other_factory(service, context, tmp_path):
    other = tmp_path / "factory-two"
    other.mkdir()
    create(service, context)
    create(service, str(other))
    assert len(service.list_tickets()["tickets"]) == 2
    assert len(service.list_tickets(context)["tickets"]) == 1


@pytest.mark.parametrize("url", [
    "http://example.atlassian.net", "https://example.atlassian.net/path",
    "https://example.atlassian.net?secret=test", "https://example.atlassian.net#part",
    "https://user:password@example.atlassian.net", "https://localhost",
    "https://127.0.0.1", "https://169.254.169.254", "https://example.atlassian.net.evil.org",
    "https://example.atlassian.net:8443", "https://example..atlassian.net",
])
def test_connections_validate_safe_https_origin(service, url):
    with pytest.raises(TicketError):
        connection(service, base_url=url)


def test_custom_public_host_requires_explicit_host_setting(monkeypatch):
    with pytest.raises(TicketError):
        validate_origin("ServiceNow", "https://support.example.org")
    monkeypatch.setenv("AIFACTORY_TICKETING_ALLOWED_HOSTS", "support.example.org")
    assert validate_origin("ServiceNow", "https://support.example.org") == "https://support.example.org"


def test_preview_contains_payload_but_no_secrets_and_unset_sync_fails(service, context, monkeypatch):
    monkeypatch.delenv("TEST_JIRA_TOKEN", raising=False)
    ticket, conn = create(service, context), connection(service)
    preview = service.preview(ticket["id"], conn["id"])
    assert preview["recipient"] == "Jira: https://example.atlassian.net/rest/api/3/issue"
    assert '"summary": "Test issue"' in preview["content"]
    assert "NOT SET" in preview["content"]
    assert "→ ADF description" in preview["content"]
    with pytest.raises(TicketError) as error:
        service.sync(preview["confirmation_id"])
    assert error.value.status_code == 409
    monkeypatch.setenv("TEST_JIRA_TOKEN", "token-secret-123")
    preview = service.preview(ticket["id"], conn["id"])
    assert "token-secret-123" not in json.dumps(preview)
    with service.store._connect() as db:
        assert "token-secret-123" not in json.dumps([dict(row) for row in db.execute("SELECT * FROM private_ticket_connections")])
        assert "token-secret-123" not in json.dumps([dict(row) for row in db.execute("SELECT * FROM private_ticket_confirmations")])


@pytest.mark.parametrize("mutation", ["expiry", "ticket", "connection", "owner"])
def test_preview_binding_is_immutable_and_owner_scoped(service, context, monkeypatch, mutation):
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    ticket, conn = create(service, context), connection(service)
    preview = service.preview(ticket["id"], conn["id"])
    if mutation == "expiry":
        service.test_clock[0] += 301
    elif mutation == "ticket":
        service.update(ticket["id"], "Active")
    elif mutation == "connection":
        connection(service, id=conn["id"], name="Changed name")
    else:
        service.active_user[0] = f"azure:{TENANT}:{OTHER}"
    with pytest.raises(TicketError) as error:
        service.sync(preview["confirmation_id"])
    assert error.value.status_code == (404 if mutation == "owner" else 409)


def test_jira_create_update_adf_transition_and_idempotence(service, context, monkeypatch):
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    calls = []

    def transport(method, url, headers, payload=None):
        calls.append((method, url, payload))
        assert headers["Authorization"].startswith("Basic ")
        if method == "POST" and url.endswith("/issue"):
            return {"key": "AI-42"}
        if method == "GET" and "?fields=status" in url:
            return {"fields": {"status": {"name": "Open"}}}
        if method == "GET" and url.endswith("/transitions"):
            return {"transitions": [{"id": "31", "to": {"name": "In Progress"}}]}
        return {}

    service.connector = TicketConnector(transport)
    ticket, conn = create(service, context), connection(service)
    preview = service.preview(ticket["id"], conn["id"])
    result = service.sync(preview["confirmation_id"])
    assert result["sync_state"] == "synced"
    assert result["external_url"] == "https://example.atlassian.net/browse/AI-42"
    assert calls[0][2]["fields"]["description"]["version"] == 1
    service.sync(preview["confirmation_id"])
    assert len(calls) == 2
    service.update(ticket["id"], "Active")
    preview = service.preview(ticket["id"], conn["id"])
    result = service.sync(preview["confirmation_id"])
    assert calls[2][0] == "PUT" and calls[2][1].endswith("/issue/AI-42")
    assert calls[-1][2] == {"transition": {"id": "31"}}
    assert sum(method == "POST" and url.endswith("/issue") for method, url, _ in calls) == 1
    with pytest.raises(TicketError):
        connection(service, id=conn["id"], base_url="https://other.atlassian.net")


def test_failed_jira_workflow_saves_external_id_before_failure(service, context, monkeypatch):
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    def transport(method, url, headers, payload=None):
        if method == "POST":
            return {"key": "AI-43"}
        if "?fields=status" in url:
            return {"fields": {"status": {"name": "Open"}}}
        return {"transitions": []}
    service.connector = TicketConnector(transport)
    ticket, conn = create(service, context), connection(service)
    service.update(ticket["id"], "Solved")
    preview = service.preview(ticket["id"], conn["id"])
    with pytest.raises(SyncError):
        service.sync(preview["confirmation_id"])
    row = service.list_tickets()["tickets"][0]
    assert row["sync_state"] == "failed"
    assert row["external_url"].endswith("AI-43")
    assert "/issue/AI-43" in service.preview(ticket["id"], conn["id"])["recipient"]


def test_uncertain_result_never_blindly_retries_or_recreates(service, context, monkeypatch):
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    service.connector = TicketConnector(Mock(side_effect=SyncError("Result uncertain.", uncertain=True)))
    ticket, conn = create(service, context), connection(service)
    preview = service.preview(ticket["id"], conn["id"])
    with pytest.raises(SyncError):
        service.sync(preview["confirmation_id"])
    assert service.list_tickets()["tickets"][0]["sync_state"] == "uncertain"
    service.update(ticket["id"], "Active")
    with pytest.raises(TicketError):
        service.preview(ticket["id"], conn["id"])
    with pytest.raises(TicketError):
        service.sync(preview["confirmation_id"])
    assert service.connector.transport.call_count == 1


def test_servicenow_incident_request_and_solved_mapping(service, context, monkeypatch):
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    calls = []
    def transport(method, url, headers, payload=None):
        calls.append((method, url, payload))
        return {"result": {"sys_id": "a" * 32, "state": payload["state"]}}
    service.connector = TicketConnector(transport)
    ticket = create(service, context, type="Request Azure service", requested_service="AI Search")
    conn = connection(service, provider="ServiceNow", base_url="https://example.service-now.com", username="")
    service.sync(service.preview(ticket["id"], conn["id"])["confirmation_id"])
    assert calls[0][2]["category"] == "inquiry"
    assert calls[0][2]["state"] == "1"
    service.update(ticket["id"], "Solved")
    service.sync(service.preview(ticket["id"], conn["id"])["confirmation_id"])
    assert calls[-1][0] == "PATCH"
    assert calls[-1][2]["state"] == "6"
    assert calls[-1][2]["close_notes"]


def test_transport_blocks_private_dns_and_dns_rebinding_before_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
    ])
    with pytest.raises(SyncError, match="public IP"):
        JsonTransport()("POST", "https://example.atlassian.net/rest/api/3/issue", {}, {})
    socket.create_connection.assert_not_called()


def test_transport_disables_redirects_and_hides_provider_error_body(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ])
    handlers_seen = []
    def opener(*handlers):
        handlers_seen.extend(handlers)
        return SimpleNamespace(open=Mock(side_effect=HTTPError(
            "https://example.atlassian.net", 302, "secret provider diagnostic", {}, None
        )))
    monkeypatch.setattr(ticket_connectors, "build_opener", opener)
    with pytest.raises(SyncError) as error:
        JsonTransport()("POST", "https://example.atlassian.net/rest/api/3/issue", {}, {})
    assert "secret" not in str(error.value)
    assert error.value.uncertain
    redirect = next(item for item in handlers_seen if isinstance(item, ticket_connectors._NoRedirect))
    assert redirect.redirect_request(None, None, 302, "", {}, "http://127.0.0.1") is None
    assert any(getattr(item, "address", None) == "8.8.8.8" for item in handlers_seen)


def test_transport_response_cap_and_timeout_never_leak_headers(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ])
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"x" * (1024 * 1024 + 1)
    fake_opener = SimpleNamespace(open=Mock(return_value=response))
    monkeypatch.setattr(ticket_connectors, "build_opener", lambda *handlers: fake_opener)
    with pytest.raises(SyncError) as error:
        JsonTransport()("POST", "https://example.atlassian.net/rest/api/3/issue", {"Authorization": "SECRET"}, {})
    assert error.value.uncertain
    assert fake_opener.open.call_args.kwargs["timeout"] == 20
    assert "SECRET" not in str(error.value)


def test_servicenow_missing_state_is_not_false_sync_success(service, context, monkeypatch):
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    service.connector = TicketConnector(lambda *args: {"result": {"sys_id": "a" * 32}})
    ticket, conn = create(service, context), connection(
        service, provider="ServiceNow", base_url="https://example.service-now.com"
    )
    with pytest.raises(SyncError, match="did not confirm"):
        service.sync(service.preview(ticket["id"], conn["id"])["confirmation_id"])
    row = service.list_tickets()["tickets"][0]
    assert row["sync_state"] == "failed"
    assert "a" * 32 in row["external_url"]
    assert ("a" * 32) in service.preview(ticket["id"], conn["id"])["recipient"]


def test_connection_raw_credential_field_is_never_accepted_or_echoed(service, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_ticket_service", lambda: service)
    with TestClient(api.app) as client:
        response = client.post("/api/v1/tickets/connections/save", headers={"X-API-Key": "test-key"}, json={
            "name": "Jira", "provider": "Jira", "base_url": "https://example.atlassian.net",
            "username": "test@example.org", "project_key": "AI", "credential_env": "TEST_JIRA_TOKEN",
            "api_token": "secret-unexpected-token",
        })
    assert response.status_code == 422 and "secret-unexpected-token" not in response.text
    assert service.list_connections()["connections"] == []


def test_new_api_routes_are_secured_and_never_accept_client_identity(service, context, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_ticket_service", lambda: service)
    headers = {"X-API-Key": "test-key"}
    with TestClient(api.app) as client:
        for path in (
            "/api/v1/tickets/list", "/api/v1/tickets/create", "/api/v1/tickets/update",
            "/api/v1/tickets/connections/list", "/api/v1/tickets/connections/save",
            "/api/v1/tickets/sync/preview", "/api/v1/tickets/sync", "/api/v1/analytics/current-factory",
            "/api/v1/tickets/resource-group/parse",
        ):
            assert client.post(path, json={}).status_code == 401
        body = {"aifactory_folder": context, "type": "Bug report", "title": "API ticket", "description": "Details"}
        assert client.post("/api/v1/tickets/create", json={**body, "owner": "spoof"}, headers=headers).status_code == 422
        rejected = client.post("/api/v1/tickets/connections/save", json={"token": "secret-do-not-echo"}, headers=headers)
        assert rejected.status_code == 422
        assert "secret-do-not-echo" not in rejected.text
        created = client.post("/api/v1/tickets/create", json=body, headers=headers)
        assert created.status_code == 200
        assert created.json()["owner"] == f"azure:{TENANT}:{USER}"
        assert client.post("/api/v1/tickets/list", json={}, headers=headers).json()["counts"]["new"] == 1
        changed = client.post("/api/v1/tickets/update", json={"id": created.json()["id"], "status": "Solved"}, headers=headers)
        assert changed.json()["status"] == "Solved"


@pytest.mark.parametrize("name,prefix,number,region,environment,suffix", [
    ("mrvel-1-project011-sdc-dev-007", "mrvel-1-", "011", "sdc", "dev", "-007"),
    ("  MRVEL-1-PROJECT011-SDC-TEST-007  ", "mrvel-1-", "011", "sdc", "stage", "-007"),
    ("gh-esml-project001-eus2-dev-001-rg", "gh-", "001", "eus2", "dev", "-001"),
    ("gh-project006-eus2-dev-001", "gh-", "006", "eus2", "dev", "-001"),
    ("mrvel-1-esml-project017-sdc-test-007-rg", "mrvel-1-", "017", "sdc", "stage", "-007"),
    ("esml-project002-eus2-prod-001", "esml-", "002", "eus2", "prod", "-001"),
    ("team-long-prefix-project-000011-sdc-stage-000007", "team-long-prefix-", "000011", "sdc", "stage", "-000007"),
    ("team-project_011-eus2-dev-007", "team-", "011", "eus2", "dev", "-007"),
])
def test_resource_group_identity_is_pure_and_preserves_number_strings(name, prefix, number, region, environment, suffix):
    assert parse_ticket_resource_group(name) == {
        "resource_group": name.strip().lower(), "ai_factory_prefix": prefix, "project_number": number,
        "region": region, "environment": environment, "ai_factory_suffix": suffix,
    }


@pytest.mark.parametrize("name", [
    "", " ", "project011", "mrvel-1-project011", "mrvel-1-project011-dev-007",
    "mrvel-1-project011-sdc-dev", "project011-sdc-dev-007", "mrvel-1-common-sdc-dev-007",
    "gh-esml-common-eus2-dev-001-rg", "mrvel-1-project011-sdc-dev-007-extra",
    "mrvel-1-project011-sdc-dev-007-rg-extra", "mrvel-1-project011-sdc-wat-007",
    "mrvel-1-project011-sdc-dev-", "mrvel-1-project011-sdc-dev-007\n",
    "mrvel-1-project011-sdc-dev-007\u0085", "mrvel--1-project011-sdc-dev-007",
    "mrvel-1-project011-sdc-dev-007/abc", "gh-notproject011-sdc-dev-007",
    "gh-project001-project002-sdc-dev-007", "gh-project1234567-sdc-dev-007",
    "prod-team-project011-sdc-dev-007", "x" * 91, None, 123,
])
def test_resource_group_parser_rejects_partial_malformed_and_common_names(name):
    with pytest.raises(TicketError):
        parse_ticket_resource_group(name)


def test_parse_api_needs_key_but_neither_azure_nor_storage(monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_ticket_service", Mock(side_effect=AssertionError("Pure parser must not open storage")))
    with TestClient(api.app) as client:
        path = "/api/v1/tickets/resource-group/parse"
        body = {"resource_group": "mrvel-1-project011-sdc-dev-007"}
        assert client.post(path, json=body).status_code == 401
        result = client.post(path, json=body, headers={"X-API-Key": "test-key"})
        assert result.status_code == 200
        assert result.json() == parse_ticket_resource_group(body["resource_group"])
        for invalid in ("gh-common-eus2-dev-001", "private-invalid\ntext", 123):
            result = client.post(path, json={"resource_group": invalid}, headers={"X-API-Key": "test-key"})
            assert result.status_code == 422
            assert isinstance(result.json()["detail"], str)
            assert "private-invalid" not in result.text


@pytest.mark.parametrize("folder", [None, "Z:\\unknown-factory", "context"])
def test_rg_ticket_needs_no_local_folder_or_rg_access(service, context, monkeypatch, folder):
    provider, calls = identity(monkeypatch)
    service.identity = provider
    ticket = create(
        service, context if folder == "context" else folder, project_number=None,
        resource_group="mrvel-1-project011-sdc-dev-007", cost_center="12345", department_name="hr",
    )
    assert {key: ticket[key] for key in IDENTITY_FIELDS} == parse_ticket_resource_group(ticket["resource_group"])
    assert ticket["aifactory_folder"] == ""
    assert ticket["cost_center"] == "12345" and ticket["department_name"] == "hr"
    assert ticket["owner"] == f"azure:{TENANT}:{USER}"
    assert len(calls) == 2  # account identity only; no resource access verification


def test_scoped_rg_tickets_use_exact_factory_region_identity_and_authenticated_owner(service, context):
    Path(context, "variables.json").write_text(json.dumps({
        "dev": {"tenantId": TENANT, "dev_sub_id": SUB, "admin_aifactoryPrefixRG": "mrvel-1-",
                "admin_aifactorySuffixRG": "-007", "admin_locationSuffix": "sdc", "admin_location": "swedencentral"},
        "stage_prod": {},
    }))
    legacy = create(service, context)
    expected = [legacy["id"]]
    for name, included in [
        ("mrvel-1-project011-sdc-dev-007", True),
        ("mrvel-1-esml-project011-sdc-test-007-rg", True),
        ("mrvel-1-project011-eus2-dev-007", False),
        ("mrvel-1-project011-sdc-dev-008", False),
        ("mrvel-11-project011-sdc-dev-007", False),
        ("mrvel-1-other-project011-sdc-dev-007", False),
        ("other-mrvel-1-project011-sdc-dev-007", False),
    ]:
        ticket = create(service, context, project_number=None, resource_group=name)
        assert ticket["aifactory_folder"] == ""
        if included:
            expected.append(ticket["id"])
    service.active_user[0] = f"azure:{TENANT}:{OTHER}"
    create(service, None, project_number=None, resource_group="mrvel-1-project011-sdc-dev-007")
    service.active_user[0] = f"azure:{TENANT}:{USER}"
    listing = service.list_tickets(context)
    assert {ticket["id"] for ticket in listing["tickets"]} == set(expected)
    assert listing["counts"] == {"new": 3, "active": 0, "solved": 0}
    assert len(service.list_tickets()["tickets"]) == 8


@pytest.mark.parametrize("severity", ["minor", "major", "blocker"])
def test_all_severities_are_independent_of_type_and_persist(service, context, severity):
    ticket = create(service, context, severity=severity)
    assert ticket["severity"] == severity
    assert TicketService(service.store, identity=service.identity).list_tickets()["tickets"][0]["severity"] == severity
    assert create(service, context, type="Blocker", severity=severity)["severity"] == severity


def test_legacy_create_defaults_and_unknown_identity_are_not_hydrated(service, context):
    Path(context, "variables.json").write_text(json.dumps({"dev": {
        "admin_aifactoryPrefixRG": "current-", "admin_aifactorySuffixRG": "-987", "admin_locationSuffix": "eus2",
    }}))
    assert create(service, context)["severity"] == "minor"
    assert create(service, context, type="Blocker")["severity"] == "blocker"
    ticket = create(service, context, project_number=None)
    assert all(ticket[field] == "" for field in IDENTITY_FIELDS)
    assert ticket["cost_center"] == ticket["department_name"] == ""
    with pytest.raises(TicketError):
        create(service, None)


@pytest.mark.parametrize("field,value", [
    ("severity", "critical"), ("severity", "Minor"), ("severity", ""), ("severity", 1),
    ("cost_center", 12345), ("department_name", "x" * 201), ("cost_center", "x" * 201),
    ("cost_center", "123\n45"), ("department_name", "hr\x00"), ("department_name", "\u007fhr"),
    ("department_name", "hr\u0085"),
])
def test_api_rejects_invalid_severity_and_organization_metadata(service, monkeypatch, field, value):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    monkeypatch.setattr(api, "_ticket_service", lambda: service)
    body = {"type": "Bug report", "title": "Test", "description": "Details",
            "resource_group": "mrvel-1-project011-sdc-dev-007", field: value}
    with TestClient(api.app) as client:
        result = client.post("/api/v1/tickets/create", json=body, headers={"X-API-Key": "key"})
    assert result.status_code == 422
    assert isinstance(result.json()["detail"], str)
    assert service.list_tickets()["tickets"] == []


@pytest.mark.parametrize("field", [
    "environment", "project_number", "region", "ai_factory_prefix", "ai_factory_suffix", "owner",
])
def test_rg_create_api_rejects_spoofed_derived_fields(service, monkeypatch, field):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    monkeypatch.setattr(api, "_ticket_service", lambda: service)
    body = {"type": "Bug report", "title": "Test", "description": "Details",
            "resource_group": "mrvel-1-project011-sdc-dev-007", field: "999"}
    with TestClient(api.app) as client:
        assert client.post("/api/v1/tickets/create", json=body, headers={"X-API-Key": "key"}).status_code == 422
    assert service.list_tickets()["tickets"] == []


def test_rg_create_api_and_status_severity_update_invalidate_consent(service, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    monkeypatch.setattr(api, "_ticket_service", lambda: service)
    service.connector = Mock()
    headers = {"X-API-Key": "key"}
    with TestClient(api.app) as client:
        response = client.post("/api/v1/tickets/create", headers=headers, json={
            "aifactory_folder": None, "resource_group": "mrvel-1-project011-sdc-dev-007",
            "type": "Request Azure service", "title": "Service", "description": "Details",
            "requested_service": "AI Search", "severity": "minor", "cost_center": "12345", "department_name": "hr",
        })
        assert response.status_code == 200
        ticket = response.json()
        assert ticket["aifactory_folder"] == "" and ticket["project_number"] == "011"
        with service.store._connect() as db:
            db.execute("UPDATE private_tickets SET sync_state='synced' WHERE id=?", (ticket["id"],))
        preview = service.preview(ticket["id"], connection(service)["id"])
        changed = client.post("/api/v1/tickets/update", headers=headers,
                              json={"id": ticket["id"], "status": "Active", "severity": "blocker"})
        assert changed.status_code == 200
        assert changed.json()["severity"] == "blocker" and changed.json()["sync_state"] == "pending"
        rejected = client.post("/api/v1/tickets/sync", headers=headers, json={"confirmation_id": preview["confirmation_id"]})
        assert rejected.status_code == 409
        service.connector.send.assert_not_called()
        old_caller = client.post("/api/v1/tickets/update", headers=headers, json={"id": ticket["id"], "status": "Solved"})
        assert old_caller.status_code == 200 and old_caller.json()["severity"] == "blocker"
        assert client.post("/api/v1/tickets/update", headers=headers,
                           json={"id": ticket["id"], "status": "New", "severity": "urgent"}).status_code == 422


@pytest.mark.parametrize("provider", ["Jira", "ServiceNow"])
def test_connector_consent_includes_every_identity_org_field_and_severity(service, monkeypatch, provider):
    ticket = create(service, None, project_number=None, resource_group="mrvel-1-project011-sdc-dev-007",
                    cost_center="12345", department_name="hr", severity="blocker")
    conn = connection(service) if provider == "Jira" else connection(
        service, provider="ServiceNow", base_url="https://example.service-now.com", project_key=None,
    )
    preview = service.preview(ticket["id"], conn["id"])
    with service.store._connect() as db:
        plan = json.loads(db.execute("SELECT plan_json FROM private_ticket_confirmations WHERE id=?",
                                    (preview["confirmation_id"],)).fetchone()[0])
    description = plan["payload"]["fields"]["description"]["content"][0]["content"][0]["text"] if provider == "Jira" else plan["payload"]["description"]
    for text in (
        "Severity: blocker", "Project: 011", "Resource group: mrvel-1-project011-sdc-dev-007",
        "Environment: dev", "Region: sdc", "AI Factory prefix: mrvel-1-", "AI Factory suffix: -007",
        "Cost center: 12345", "Department name: hr",
    ):
        assert text in description and text in preview["content"]
    assert "priority" not in plan["payload"] and "priority" not in plan["payload"].get("fields", {})
    assert "not deployment or access verification" in preview["content"]


def seed_v1_store(store):
    with store._connect() as db:
        db.executescript("""
            CREATE TABLE ticketing_schema (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO ticketing_schema VALUES (1,'old');
            CREATE TABLE private_tickets (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, aifactory_folder TEXT NOT NULL,
                project_number TEXT NOT NULL DEFAULT '', type TEXT NOT NULL,
                title TEXT NOT NULL, description TEXT NOT NULL, requested_service TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('New','Active','Solved')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                external_id TEXT NOT NULL DEFAULT '', external_url TEXT NOT NULL DEFAULT '',
                connection_id TEXT NOT NULL DEFAULT '', sync_state TEXT NOT NULL DEFAULT 'local',
                CHECK(type IN ('Request Azure service','Bug report','Blocker'))
            );
            CREATE TABLE private_ticket_connections (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                provider TEXT NOT NULL CHECK(provider IN ('Jira','ServiceNow')),
                base_url TEXT NOT NULL, project_key TEXT NOT NULL, username TEXT NOT NULL,
                credential_env TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE private_ticket_confirmations (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, ticket_id TEXT NOT NULL,
                connection_id TEXT NOT NULL, ticket_version INTEGER NOT NULL,
                connection_version INTEGER NOT NULL, plan_json TEXT NOT NULL,
                expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(ticket_id) REFERENCES private_tickets(id),
                FOREIGN KEY(connection_id) REFERENCES private_ticket_connections(id)
            );
            INSERT INTO private_ticket_connections VALUES
                ('conn','owner','Connection','Jira','https://example.atlassian.net','AI','test@example.org',
                 'TEST_JIRA_TOKEN',4,'before','after');
            INSERT INTO private_tickets VALUES
                ('blocker','owner','old-folder','011','Blocker','title','body','','Active','before','after',
                 7,'AI-123','https://example.atlassian.net/browse/AI-123','conn','synced'),
                ('bug','owner','old-folder','002','Bug report','bug','body','','New','before','after',1,'','','','local');
        """)
        db.execute("INSERT INTO private_ticket_confirmations VALUES ('confirmation','owner','blocker','conn',7,4,'{}',?,'pending')", (NOW + 100,))


def test_v1_sqlite_migration_is_idempotent_preserves_rows_and_rejects_old_payload(tmp_path, monkeypatch):
    store = operations.OperationsStore(tmp_path / "old.db")
    seed_v1_store(store)
    with store._connect() as db:
        before = {name: [dict(row) for row in db.execute(f"SELECT * FROM {name}")] for name in (
            "private_tickets", "private_ticket_connections", "private_ticket_confirmations",
        )}
    migrated = TicketService(store, identity=lambda folder=None: "owner", clock=lambda: NOW)
    with store._connect() as db:
        for table, originals in before.items():
            for original, row in zip(originals, db.execute(f"SELECT * FROM {table}")):
                assert {key: row[key] for key in original} == original
        rows = {row["id"]: dict(row) for row in db.execute("SELECT * FROM private_tickets")}
        assert rows["blocker"]["severity"] == "blocker" and rows["bug"]["severity"] == "minor"
        assert all(rows["blocker"][field] == "" for field in IDENTITY_FIELDS if field != "project_number")
        assert [row[0] for row in db.execute("SELECT version FROM ticketing_schema ORDER BY version")] == [1, 2]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    monkeypatch.setenv("TEST_JIRA_TOKEN", "fake-secret")
    migrated.connector = Mock()
    with pytest.raises(TicketError, match="payload changed"):
        migrated.sync("confirmation")
    migrated.connector.send.assert_not_called()
    migrated.update("blocker", "Active", "major")
    reopened = TicketService(store, identity=lambda folder=None: "owner")
    assert {ticket["id"]: ticket["severity"] for ticket in reopened.list_tickets()["tickets"]} == {
        "blocker": "major", "bug": "minor",
    }
    assert len(reopened.list_connections()["connections"]) == 1
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM private_ticket_confirmations").fetchone()[0] == 1


def test_v2_migration_failure_rolls_back_columns_and_version(tmp_path, monkeypatch):
    store = operations.OperationsStore(tmp_path / "rollback.db")
    seed_v1_store(store)
    original_connect = store._connect

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("ALTER TABLE") and "department_name" in sql:
                raise sqlite3.OperationalError("Injected migration failure")
            return super().execute(sql, parameters)

    def connect():
        db = sqlite3.connect(str(store.db_path), factory=FailingConnection)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(store, "_connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="Injected"):
        TicketService(store, identity=lambda folder=None: "owner")
    with original_connect() as db:
        assert "severity" not in {row["name"] for row in db.execute("PRAGMA table_info(private_tickets)")}
        assert [row[0] for row in db.execute("SELECT version FROM ticketing_schema")] == [1]
        assert db.execute("SELECT COUNT(*) FROM private_tickets").fetchone()[0] == 2
