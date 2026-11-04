import copy
import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import UUID

import pytest
from azurefactory.errors import APIError, RequestTimeout

from aifactory_agent import tools
from aifactory_agent.operations import BlobOperationBackend, MemoryOperationBackend, OperationStore
from aifactory_agent.security import Principal
from aifactory_agent.tools import CONFIGURE_TOOL, FactoryTools
from test_security import CALLER, FACTORY, PROJECT, SCALE, SCOPE, SUBSCRIPTION, TENANT, principal, settings
from test_signing import FakeBlobContainer, FakeVault, KeyVaultRecordSigner, signing_settings, signer, vault


REVISION = "a" * 64


def catalog():
    return {
        "contract_version": 1, "revision": REVISION, "factories": [{
            "id": FACTORY, "prefix": "factory", "key": "factory-ai", "kind": "ai",
            "scale_sets": [{"id": SCALE, "tenant_id": TENANT, "subscription_id": SUBSCRIPTION, "environment": "dev"}],
            "projects": [{"id": PROJECT, "number": "001", "key": "project001",
                          "placements": [{"scale_set_id": SCALE, "environment": "dev"}]}],
        }, {"id": "88888888-8888-4888-8888-888888888888", "prefix": "private-other-factory"}],
    }


def preview():
    return {
        "contract_version": 1, "confirmation_id": "99999999-9999-4999-8999-999999999999",
        "can_execute": True, "operation_mode": "configuration", "blockers": [],
        "source_revision": REVISION, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "factory_id": FACTORY, "scale_set_id": SCALE, "project_id": PROJECT,
        "target": catalog()["factories"][0], "inventory": [], "deletion_targets": [], "binding": None,
        "effects": ["Save project department metadata"], "warnings": [],
    }


def request(settings):
    return {
        "folder": settings.factory.folder, "contract_version": 1, "action": "configure-settings",
        "factory_id": FACTORY, "scale_set_id": SCALE, "project_id": PROJECT, "expected_revision": REVISION,
        "settings": {"org-department-name": "Research"},
    }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.catalog = catalog()
        self.review = preview()
        self.current_revision = REVISION
        self.failure = None
        self.schema = {
            "components": {"schemas": {"CatalogPrepare": {
                "additionalProperties": False,
                "properties": {"action": {"enum": ["configure-settings"]}, "settings": {},
                               "expected_revision": {}, "factory_id": {}, "scale_set_id": {}, "project_id": {}},
            }}},
        }

    def health(self):
        self.calls.append(("health",))
        if self.failure:
            raise self.failure
        return {"status": "healthy", "api_key": "never-visible", "message": "unit-test-api-key"}

    def creation_capabilities(self):
        self.calls.append(("creation_capabilities",))
        return {"contract_version": 1, "features": []}

    def catalog_list(self, folder):
        self.calls.append(("catalog_list", folder))
        return copy.deepcopy(self.catalog)

    def catalog_settings(self, folder, factory_id, scale_set_id, project_id):
        self.calls.append(("catalog_settings", folder, factory_id, scale_set_id, project_id))
        return {
            "contract_version": 1, "revision": self.current_revision, "factory_id": factory_id,
            "scale_set_id": scale_set_id, "project_id": project_id,
            "state": {"org-department-name": "Existing", "password": "never-visible"},
            "field_keys": ["org-department-name", "org-department-id"],
        }

    def openapi(self):
        return copy.deepcopy(self.schema)

    def catalog_prepare(self, body):
        self.calls.append(("catalog_prepare", copy.deepcopy(body)))
        return copy.deepcopy(self.review)

    def catalog_confirm(self, folder, confirmation_id):
        self.calls.append(("catalog_confirm", folder, confirmation_id))
        if self.failure:
            raise self.failure
        updated = copy.deepcopy(self.catalog)
        updated["revision"] = "b" * 64
        return {"contract_version": 1, "catalog": updated, "job": None}


@pytest.fixture
def api(monkeypatch):
    instance = FakeClient()
    instance.client_arguments = []
    def client(**kwargs):
        instance.client_arguments.append(kwargs)
        return instance
    monkeypatch.setattr(tools, "AzureFactoryClient", client)
    monkeypatch.setenv("AIFACTORY_API_KEY", "unit-test-api-key")
    return instance


@pytest.fixture
def store(settings):
    return OperationStore(settings, backend=MemoryOperationBackend())


@pytest.fixture
def adapter(settings, principal, store, api):
    return FactoryTools(settings, principal, SCOPE, operation_store=store)


def test_descriptors_are_strict_and_never_offer_approval(adapter):
    descriptors = adapter.descriptors()
    assert {item["name"] for item in descriptors} == {
        "factory_health", "factory_capabilities", "factory_catalog", "factory_settings", "factory_cli_health",
        "factory_operation_status",
    }
    for definition in descriptors:
        assert definition["type"] == "function" and definition["strict"] is True
        assert definition["parameters"]["additionalProperties"] is False
    changes = tools.ConfigureArguments.model_json_schema()["$defs"]["SettingsChanges"]
    assert changes["additionalProperties"] is False
    assert set(changes["required"]) == {"department_name", "department_id"}
    assert not any("approve" in item["name"] or "delete" in item["name"] for item in descriptors)


def test_health_does_not_read_credentials(settings, principal, api, monkeypatch):
    adapter = FactoryTools(settings, principal, SCOPE)
    monkeypatch.setattr(adapter, "_load_key", lambda: pytest.fail("health must not read a secret"))
    result = adapter.execute("factory_health", {})
    assert result["ok"] is True and result["data"]["api_key"] == "<redacted>"
    assert api.client_arguments[-1]["api_key"] == ""


def test_real_client_methods_and_redaction(adapter, api):
    for name in ("factory_capabilities", "factory_catalog", "factory_settings"):
        result = adapter.execute(name, {})
        assert result["ok"] is True
        assert "private-other-factory" not in json.dumps(result)
        assert "never-visible" not in json.dumps(result)
    assert ("creation_capabilities",) in api.calls
    assert ("catalog_settings", adapter.settings.factory.folder, FACTORY, SCALE, PROJECT) in api.calls
    assert api.client_arguments[-1]["timeout"] == 60


@pytest.mark.parametrize("arguments", [
    {"scope_key": "project002-dev"}, {"tenant_id": TENANT}, {"folder": "C:\\another"},
    {"endpoint": "/arbitrary"}, {"command": "echo unsafe"}, {"args": ["--api-key", "secret"]},
    {"executable": "cmd.exe"}, {"timeout": 99999}, {"audience": "different"},
])
def test_arbitrary_model_inputs_rejected_before_call(adapter, api, arguments):
    assert adapter.execute("factory_health", arguments)["error"]["code"] == "invalid_arguments"
    assert api.calls == []


def test_unknown_and_destructive_tools_unsupported(adapter, api):
    for name in ("factory_delete", "factory_deploy", "shell", "approve", "request", "factory_configure_settings", CONFIGURE_TOOL):
        assert adapter.execute(name, {})["ok"] is False
    assert api.calls == []


def test_cross_project_and_unauthorized_never_call_api(settings, principal, api):
    adapter = FactoryTools(settings, principal, "project002-dev")
    assert adapter.descriptors() == []
    assert adapter.execute("factory_health", {})["error"]["status_code"] == 403
    adapter = FactoryTools(settings, Principal(TENANT, "88888888-8888-4888-8888-888888888888"), SCOPE)
    assert adapter.execute("factory_health", {})["error"]["code"] == "forbidden"
    assert api.calls == []


def test_server_reference_mismatch_denied(adapter, api):
    api.catalog["factories"][0]["scale_sets"][0]["subscription_id"] = CALLER
    result = adapter.execute("factory_catalog", {})
    assert result["error"]["status_code"] == 403


def test_unconfigured_ids_fail_closed(settings, principal, api):
    current = settings.model_copy(update={"factory": settings.factory.model_copy(update={"project_id": None})})
    result = FactoryTools(current, principal, SCOPE).execute("factory_settings", {})
    assert result["error"]["status_code"] == 503
    assert api.calls == []


def test_fixed_cli_array_never_uses_configured_executable(settings, principal, monkeypatch):
    captured = []
    def run(argv, **kwargs):
        captured.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"status":"healthy"}', stderr="")
    monkeypatch.setattr(tools.subprocess, "run", run)
    settings = settings.model_copy(update={
        "factory": settings.factory.model_copy(update={"cli_executable": "cmd.exe /c malicious", "timeout_seconds": 600}),
    })
    result = FactoryTools(settings, principal, SCOPE).execute("factory_cli_health", {})
    argv, kwargs = captured[0]
    assert result["ok"] is True
    assert argv == [sys.executable, "-m", "azurefactory", "--api-url", "http://127.0.0.1:8765",
                    "--timeout", "60", "health"]
    assert kwargs["shell"] is False and kwargs["timeout"] == 65
    assert "AIFACTORY_API_KEY" not in kwargs["env"] and "--api-key" not in argv


@pytest.mark.parametrize("response", [
    SimpleNamespace(returncode=1, stdout="", stderr="sensitive diagnostics"),
    SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    SimpleNamespace(returncode=0, stdout="[]", stderr=""),
])
def test_cli_failures_are_structured(settings, principal, monkeypatch, response):
    monkeypatch.setattr(tools.subprocess, "run", lambda *args, **kwargs: response)
    result = FactoryTools(settings, principal, SCOPE).execute("factory_cli_health", {})
    assert result["ok"] is False
    assert "sensitive diagnostics" not in json.dumps(result)


def test_api_unavailable_and_timeouts_are_not_mock_success(adapter, api):
    api.failure = RequestTimeout("timed out")
    assert adapter.execute("factory_health", {})["error"]["status_code"] == 503
    api.failure = APIError("API failed: unit-test-api-key")
    adapter._api_key = "unit-test-api-key"
    result = adapter.execute("factory_health", {})
    assert result["ok"] is False and "unit-test-api-key" not in json.dumps(result)
    assert len(api.calls) == 2


def test_writes_disabled_do_not_prepare(settings, principal, api):
    settings = settings.model_copy(update={"factory": settings.factory.model_copy(update={"writes_enabled": False})})
    adapter = FactoryTools(settings, principal, SCOPE)
    assert CONFIGURE_TOOL not in {item["name"] for item in adapter.descriptors()}
    result = adapter.prepare_settings({"settings": {"department_name": "Research", "department_id": None}})
    assert result["error"]["code"] == "writes_disabled"
    assert api.calls == []


def test_prepare_approve_execute_real_configuration_contract(adapter, api, store, principal):
    prepared = adapter.prepare_settings({"settings": {"department_name": "Research", "department_id": None}})
    assert prepared["ok"] is True
    operation = prepared["data"]
    assert operation["status"] == "pending"
    assert not any(call[0] == "catalog_confirm" for call in api.calls)
    store.approve(principal, operation["id"], operation["plan_hash"])
    completed = store.execute(principal, operation["id"], adapter.execute_operation)
    assert completed["status"] == "succeeded"
    confirms = [call for call in api.calls if call[0] == "catalog_confirm"]
    assert confirms == [("catalog_confirm", adapter.settings.factory.folder, preview()["confirmation_id"])]
    assert completed["outcome"]["data"]["revision"] == "b" * 64
    assert "private-other-factory" not in json.dumps(completed)


@pytest.mark.parametrize("changes", [
    {"settings": {"department_name": "Research", "department_id": None, "password": "never"}},
    {"settings": {"department_name": "$(danger)", "department_id": None}},
    {"settings": {"department_name": None, "department_id": None}},
    {"settings": {"department_name": 7, "department_id": None}},
    {"settings": {"department_name": "Research", "department_id": None}, "factory_id": FACTORY},
])
def test_closed_configuration_arguments(adapter, api, changes):
    assert adapter.prepare_settings(changes)["error"]["code"] == "invalid_arguments"
    assert api.calls == []


def test_incomplete_contract_and_cross_environment_write_are_blocked(adapter, api):
    api.schema = {}
    assert adapter.prepare_settings({"settings": {"department_name": "R", "department_id": None}})["error"]["status_code"] == 503
    assert not any(call[0] == "catalog_prepare" for call in api.calls)
    api.catalog["factories"][0]["projects"][0]["placements"].append({"environment": "stage", "scale_set_id": CALLER})
    assert adapter.prepare_settings({"settings": {"department_name": "R", "department_id": None}})["error"]["code"] == "cross_scope_write"


def test_revision_changed_after_approval_never_confirms(adapter, api, store, principal):
    operation = store.propose(principal, SCOPE, CONFIGURE_TOOL, request(adapter.settings), preview())
    store.approve(principal, operation["id"], operation["plan_hash"])
    api.current_revision = "c" * 64
    completed = store.execute(principal, operation["id"], adapter.execute_operation)
    assert completed["status"] == "failed"
    assert not any(call[0] == "catalog_confirm" for call in api.calls)


def test_existing_sdk_and_real_cli_reach_only_fixed_routes(settings, principal, monkeypatch):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get("X-API-Key")))
            if self.path == "/health":
                result = {"status": "healthy"}
            elif self.path == "/api/v1/creation/capabilities":
                result = {"contract_version": 1, "capabilities": []}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("AIFACTORY_API_KEY", "unit-test-api-key")
    settings = settings.model_copy(update={
        "factory": settings.factory.model_copy(update={"api_url": f"http://127.0.0.1:{server.server_port}"}),
    })
    adapter = FactoryTools(settings, principal, SCOPE)
    try:
        assert adapter.execute("factory_health", {}) == {"ok": True, "data": {"status": "healthy"}}
        assert adapter.execute("factory_capabilities", {})["ok"] is True
        assert adapter.execute("factory_cli_health", {}) == {"ok": True, "data": {"status": "healthy"}}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert calls == [("/health", None), ("/api/v1/creation/capabilities", "unit-test-api-key"), ("/health", None)]


def test_key_vault_uses_only_configured_reference(settings, principal, api, monkeypatch):
    calls = []
    class Vault:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def get_secret(self, name, version):
            calls.append((name, version))
            return SimpleNamespace(value="unit-test-api-key")
    monkeypatch.setitem(sys.modules, "azure.keyvault.secrets", SimpleNamespace(SecretClient=Vault))
    settings = settings.model_copy(update={
        "factory": settings.factory.model_copy(update={
            "api_key_secret_url": "https://unit-vault.vault.azure.net/secrets/factory-api-key",
        }),
    })
    cred = object()
    adapter = FactoryTools(settings, principal, SCOPE, cred)
    assert adapter.execute("factory_capabilities", {})["ok"] is True
    assert calls == [{"vault_url": "https://unit-vault.vault.azure.net", "credential": cred},
                     ("factory-api-key", None)]
    assert api.client_arguments[0]["api_key"] == "unit-test-api-key"


@pytest.mark.parametrize("url", [
    "https://attacker.test/secrets/key", "http://unit-vault.vault.azure.net/secrets/key",
    "https://unit-vault.vault.azure.net/secrets/key?override=1",
    "https://user:password@unit-vault.vault.azure.net/secrets/key",
])
def test_invalid_vault_references_do_not_fetch_secrets(settings, principal, api, monkeypatch, url):
    monkeypatch.setitem(sys.modules, "azure.keyvault.secrets", SimpleNamespace(
        SecretClient=lambda **kwargs: pytest.fail("must not access vault"),
    ))
    settings = settings.model_copy(update={"factory": settings.factory.model_copy(update={"api_key_secret_url": url})})
    result = FactoryTools(settings, principal, SCOPE).execute("factory_capabilities", {})
    assert result["error"]["status_code"] == 503
    assert api.calls == []


def test_metadata_cannot_persist_factory_credential(adapter, api):
    result = adapter.prepare_settings({
        "settings": {"department_name": "unit-test-api-key", "department_id": None},
    })
    assert result["error"]["code"] == "secret_in_arguments"
    assert "unit-test-api-key" not in json.dumps(result)
    assert not any(call[0] == "catalog_prepare" for call in api.calls)


@pytest.mark.parametrize("schema", [
    {"components": []}, {"components": {"schemas": []}},
    {"components": {"schemas": {"CatalogPrepare": {"properties": []}}}},
])
def test_malformed_running_api_schema_is_explicit_blocker(adapter, api, schema):
    api.schema = schema
    result = adapter.prepare_settings({"settings": {"department_name": "R", "department_id": None}})
    assert result["error"]["status_code"] == 503
    assert not any(call[0] == "catalog_prepare" for call in api.calls)


def test_local_approval_expiry_is_checked_again_before_confirm(adapter, api, store, principal, monkeypatch):
    clock = [datetime.now(timezone.utc)]
    store.clock = lambda: clock[0]
    operation = store.propose(principal, SCOPE, CONFIGURE_TOOL, request(adapter.settings), preview())
    store.approve(principal, operation["id"], operation["plan_hash"])
    actual_datetime = tools.datetime
    class DelayedDateTime:
        @staticmethod
        def fromisoformat(value):
            return actual_datetime.fromisoformat(value)
        @staticmethod
        def now(tz):
            return actual_datetime.fromisoformat(operation["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(tools, "datetime", DelayedDateTime)
    result = store.execute(principal, operation["id"], adapter.execute_operation)
    assert result["status"] == "failed"
    assert not any(call[0] == "catalog_confirm" for call in api.calls)


def test_production_signer_must_be_ready_before_any_factory_preparation(settings, principal, api):
    container = FakeBlobContainer()
    store = OperationStore(settings, backend=BlobOperationBackend(settings, container=container))
    result = FactoryTools(settings, principal, SCOPE, operation_store=store).prepare_settings({
        "settings": {"department_name": "Research", "department_id": None},
    })
    assert result["ok"] is False and result["error"]["status_code"] == 503
    assert api.calls == [] and container.data == {}


def test_real_signer_readiness_and_signed_proposal_before_confirmation(signing_settings, principal, api, signer):
    container = FakeBlobContainer()
    store = OperationStore(signing_settings, backend=BlobOperationBackend(signing_settings, container=container, signer=signer))
    adapter = FactoryTools(signing_settings, principal, SCOPE, operation_store=store)
    result = adapter.prepare_settings({"settings": {"department_name": "Research", "department_id": None}})
    assert result["ok"] is True and result["data"]["status"] == "pending"
    stored = json.loads(container.data[store._key(principal, result["data"]["id"])])
    signer.verify(stored)
    assert any(call[0] == "catalog_prepare" for call in api.calls)
    assert not any(call[0] == "catalog_confirm" for call in api.calls)
