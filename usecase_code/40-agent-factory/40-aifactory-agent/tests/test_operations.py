import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError
from azurefactory.errors import RequestTimeout

from aifactory_agent.operations import BlobOperationBackend, MemoryOperationBackend, OperationError, OperationStore
from aifactory_agent.security import Principal
from aifactory_agent.tools import CONFIGURE_TOOL
from test_security import CALLER, CLIENT, SCOPE, TENANT, principal, settings
from test_tools import preview, request


@pytest.fixture
def backend():
    return MemoryOperationBackend()


@pytest.fixture
def store(settings, backend):
    return OperationStore(settings, backend=backend)


@pytest.fixture
def operation(store, settings, principal):
    return store.propose(principal, SCOPE, CONFIGURE_TOOL, request(settings), preview())


def test_plan_binds_caller_scope_revision_confirmation_and_resources(operation):
    assert operation["tenant_id"] == TENANT and operation["object_id"] == CALLER
    assert operation["scope_key"] == SCOPE
    assert operation["preview"]["confirmation_id"] == preview()["confirmation_id"]
    assert operation["request"]["expected_revision"] == "a" * 64
    assert operation["affected_resources"][0]["settings_keys"] == ["org-department-name"]
    assert len(operation["plan_hash"]) == 64
    assert operation["progress"]["underlying_job_cancellation_supported"] is False


def test_durability_across_store_instances(settings, backend, principal, operation):
    reopened = OperationStore(settings, backend=backend)
    assert reopened.read(principal, operation["id"])["plan_hash"] == operation["plan_hash"]
    assert reopened.list(principal)[0]["id"] == operation["id"]


def test_cross_user_tenant_scope_and_revoked_grants_denied(settings, backend, store, operation, principal):
    for stranger in (Principal(TENANT, CLIENT), Principal(CLIENT, CALLER)):
        with pytest.raises(OperationError) as error:
            store.read(stranger, operation["id"])
        assert error.value.status_code == 404
        assert store.list(stranger) == []
    revoked = settings.model_copy(update={"auth": settings.auth.model_copy(update={"grants": []})})
    restricted = OperationStore(revoked, backend=backend)
    with pytest.raises(PermissionError):
        restricted.approve(principal, operation["id"], operation["plan_hash"])
    assert restricted.list(principal) == []


def test_unapproved_execution_and_wrong_plan_hash_never_call(store, operation, principal):
    with pytest.raises(OperationError):
        store.execute(principal, operation["id"], lambda _: pytest.fail("must not execute"))
    with pytest.raises(OperationError):
        store.approve(principal, operation["id"], "0" * 64)
    assert store.read(principal, operation["id"])["status"] == "pending"


def test_single_use_execution_and_replay_denied(store, backend, operation, principal):
    calls = []
    store.approve(principal, operation["id"], operation["plan_hash"])
    def execute(record):
        assert store.read(principal, record["id"])["status"] == "executing"
        assert backend.events[-1]["event"] == "executing"
        calls.append(record["id"])
        return {"ok": True, "data": {"status": "saved", "password": "sensitive"}}
    result = store.execute(principal, operation["id"], execute)
    assert result["status"] == "succeeded" and result["outcome"]["data"]["password"] == "<redacted>"
    assert calls == [operation["id"]]
    for action in (
        lambda: store.approve(principal, operation["id"], operation["plan_hash"]),
        lambda: store.execute(principal, operation["id"], execute),
        lambda: store.cancel(principal, operation["id"]),
    ):
        with pytest.raises(OperationError):
            action()
    assert len(calls) == 1


def test_concurrent_approvals_and_executions_have_one_winner(store, operation, principal):
    def approve(_):
        try:
            return store.approve(principal, operation["id"], operation["plan_hash"])["status"]
        except OperationError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(approve, range(8)))
    assert results.count("approved") == 1
    calls = []
    def execute(_):
        try:
            return store.execute(principal, operation["id"],
                                 lambda record: (calls.append(record["id"]) or {"ok": True}))["status"]
        except OperationError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(execute, range(8)))
    assert results.count("succeeded") == 1 and len(calls) == 1


def test_expiry_uses_earlier_api_deadline_and_is_enforced(settings, principal, backend):
    now = datetime.now(timezone.utc)
    clock = [now]
    store = OperationStore(settings, backend=backend, clock=lambda: clock[0])
    review = preview()
    review["expires_at"] = (now + timedelta(seconds=20)).isoformat()
    operation = store.propose(principal, SCOPE, CONFIGURE_TOOL, request(settings), review)
    clock[0] = now + timedelta(seconds=21)
    assert store.read(principal, operation["id"])["status"] == "expired"
    with pytest.raises(OperationError) as error:
        store.approve(principal, operation["id"], operation["plan_hash"])
    assert error.value.code == "plan_expired"


@pytest.mark.parametrize("field,value", [
    ("source_revision", "b" * 64), ("operation_mode", "runtime"), ("can_execute", False),
    ("project_id", CLIENT), ("deletion_targets", [{"resource_id": "/another"}]),
])
def test_invalid_factory_previews_not_persisted(store, settings, principal, field, value):
    review = preview()
    review[field] = value
    with pytest.raises(RuntimeError):
        store.propose(principal, SCOPE, CONFIGURE_TOOL, request(settings), review)
    assert store.list(principal) == []


def test_tampered_plan_or_configured_scope_cannot_be_approved(store, backend, settings, operation, principal):
    key = store._key(principal, operation["id"])
    record, version = backend.read(key)
    record["request"]["settings"]["org-department-name"] = "Tampered"
    backend.replace(key, record, version)
    with pytest.raises(OperationError) as error:
        store.approve(principal, operation["id"], operation["plan_hash"])
    assert error.value.code == "plan_changed"


def test_timeout_lost_response_is_uncertain_and_never_retried(store, operation, principal):
    store.approve(principal, operation["id"], operation["plan_hash"])
    def timeout(_):
        raise RequestTimeout("sensitive detail must not be stored")
    result = store.execute(principal, operation["id"], timeout)
    assert result["status"] == "uncertain"
    assert result["progress"]["completion_known"] is False
    assert result["progress"]["retry_allowed"] is False
    assert "sensitive detail" not in json.dumps(result)
    with pytest.raises(OperationError):
        store.execute(principal, operation["id"], lambda _: pytest.fail("must not retry"))


def test_unexpected_callback_error_leaves_claimed_record_without_replay(store, operation, principal):
    store.approve(principal, operation["id"], operation["plan_hash"])
    def broken(_):
        raise ValueError("programming error")
    with pytest.raises(ValueError):
        store.execute(principal, operation["id"], broken)
    assert store.read(principal, operation["id"])["status"] == "executing"
    assert store.read(principal, operation["id"])["progress"]["completion_known"] is False
    with pytest.raises(OperationError):
        store.execute(principal, operation["id"], broken)


def test_audit_contains_minimal_events_not_settings_values(backend, operation, store, principal):
    store.approve(principal, operation["id"], operation["plan_hash"])
    serialized = json.dumps(backend.events)
    assert "Research" not in serialized and "settings" not in serialized
    assert [item["event"] for item in backend.events] == ["proposed", "approved"]
    assert all(item["plan_hash"] == operation["plan_hash"] for item in backend.events)


def test_cancellation_only_unexecuted_plans(store, operation, principal):
    assert store.cancel(principal, operation["id"])["status"] == "cancelled"
    with pytest.raises(OperationError):
        store.approve(principal, operation["id"], operation["plan_hash"])


def test_disabled_writes_fail_even_for_previously_approved_plan(settings, backend, store, operation, principal):
    store.approve(principal, operation["id"], operation["plan_hash"])
    disabled = settings.model_copy(update={"factory": settings.factory.model_copy(update={"writes_enabled": False})})
    blocked = OperationStore(disabled, backend=backend)
    with pytest.raises(OperationError) as error:
        blocked.execute(principal, operation["id"], lambda _: pytest.fail("must not execute"))
    assert error.value.code == "writes_disabled" and error.value.status_code == 503


def test_blob_backend_uses_etag_cas_and_separate_immutable_audit(settings):
    uploads = []
    class Blob:
        def __init__(self, name):
            self.name = name
        def upload_blob(self, body, **kwargs):
            uploads.append((self.name, json.loads(body), kwargs))
            return {"etag": '"version-2"'}
        def download_blob(self):
            return SimpleNamespace(readall=lambda: b'{"id":"record"}', properties=SimpleNamespace(etag='"version-1"'))
    container = SimpleNamespace(get_blob_client=lambda name: Blob(name),
                                list_blobs=lambda **kwargs: [SimpleNamespace(name="operations/caller/id.json")])
    backend = BlobOperationBackend(settings, container=container)
    assert backend.read("operations/caller/id.json") == ({"id": "record"}, '"version-1"')
    backend.create("operations/caller/id.json", {"id": "record"})
    backend.replace("operations/caller/id.json", {"id": "updated"}, '"version-1"')
    backend.audit({"tenant_id": TENANT, "object_id": CALLER, "operation_id": "record", "event": "approved"})
    assert uploads[0][2] == {"overwrite": False}
    assert uploads[1][2] == {"overwrite": True, "etag": '"version-1"', "match_condition": MatchConditions.IfNotModified}
    assert uploads[2][0].startswith("audit/") and uploads[2][2] == {"overwrite": False}


def test_changed_factory_api_url_invalidates_approval(settings, backend, operation, principal):
    changed = settings.model_copy(update={"factory": settings.factory.model_copy(update={"api_url": "http://127.0.0.1:8766"})})
    store = OperationStore(changed, backend=backend)
    with pytest.raises(OperationError) as error:
        store.approve(principal, operation["id"], operation["plan_hash"])
    assert error.value.code == "plan_changed"


def test_audit_failure_after_claim_never_invokes_factory(store, backend, operation, principal, monkeypatch):
    store.approve(principal, operation["id"], operation["plan_hash"])
    def unavailable(_):
        raise OperationError("audit_unavailable", "Unavailable", 503)
    monkeypatch.setattr(backend, "audit", unavailable)
    with pytest.raises(OperationError):
        store.execute(principal, operation["id"], lambda _: pytest.fail("audit must precede API"))
    assert store.read(principal, operation["id"])["status"] == "executing"


def test_lost_final_storage_reply_preserves_one_use_claim(store, backend, operation, principal, monkeypatch):
    store.approve(principal, operation["id"], operation["plan_hash"])
    replace = backend.replace
    def fail_final(key, record, etag):
        if record["status"] == "succeeded":
            raise OperationError("store_unavailable", "Lost storage reply", 503, uncertain=True)
        return replace(key, record, etag)
    monkeypatch.setattr(backend, "replace", fail_final)
    calls = []
    with pytest.raises(OperationError) as error:
        store.execute(principal, operation["id"], lambda record: (calls.append(record["id"]) or {"ok": True}))
    assert error.value.uncertain is True and calls == [operation["id"]]
    assert store.read(principal, operation["id"])["progress"]["completion_known"] is False
    with pytest.raises(OperationError):
        store.execute(principal, operation["id"], lambda _: pytest.fail("must not retry"))


def test_production_backend_never_falls_back_to_memory(settings, monkeypatch):
    captured = []
    container = object()
    def client(**kwargs):
        captured.append(kwargs)
        return container
    monkeypatch.setattr("aifactory_agent.operations.ContainerClient", client)
    cred = object()
    store = OperationStore(settings, cred)
    assert isinstance(store.backend, BlobOperationBackend)
    assert store.backend.container is container
    assert captured == [{"account_url": settings.azure.storage_endpoint,
                         "container_name": settings.azure.storage_container, "credential": cred}]
