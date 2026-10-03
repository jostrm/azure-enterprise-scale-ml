import base64
import copy
import json
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError

from aifactory_agent.signing import ALGORITHM, KeyVaultRecordSigner, SigningError
from test_security import CALLER, SCOPE, TENANT, settings


SIGNING_URL = "https://signing-unit.vault.azure.net/secrets/agent-operation-integrity"
VERSION_1 = "a" * 32
VERSION_2 = "b" * 32


@pytest.fixture
def signing_settings(settings):
    return settings.model_copy(update={
        "factory": settings.factory.model_copy(update={"operation_signing_secret_url": SIGNING_URL}),
    })


class FakeVault:
    def __init__(self):
        self.current_version = VERSION_1
        self.calls = []
        self.values = {
            VERSION_1: base64.b64encode(b"A" * 32).decode("ascii"),
            VERSION_2: base64.b64encode(b"B" * 32).decode("ascii"),
        }
        self.response = None

    def get_secret(self, name, version=None):
        self.calls.append((name, version))
        selected = version or self.current_version
        if self.response is not None:
            return self.response
        if selected not in self.values:
            raise ResourceNotFoundError("The unit-test key version is unavailable.")
        return SimpleNamespace(
            id=f"{SIGNING_URL}/{selected}", value=self.values[selected],
            properties=SimpleNamespace(version=selected, enabled=True),
        )


@pytest.fixture
def vault():
    return FakeVault()


@pytest.fixture
def signer(signing_settings, vault):
    return KeyVaultRecordSigner(signing_settings, secret_client=vault)


@pytest.fixture
def unsigned():
    return {
        "id": "unit-operation", "tenant_id": TENANT, "object_id": CALLER, "scope_key": SCOPE,
        "scope": {"environment": "dev", "project": "001"}, "status": "pending", "approval": None,
        "outcome": None, "request": {"expected_revision": "a" * 64}, "plan_hash": "c" * 64,
        "created_at": "2026-10-03T18:00:00+00:00", "expires_at": "2026-10-03T18:15:00+00:00",
    }


class FakeBlobContainer:
    def __init__(self):
        self.data = {}
        self.versions = {}
        self.uploads = []

    def get_blob_client(self, name):
        container = self
        class Blob:
            def upload_blob(self, body, **kwargs):
                if not kwargs.get("overwrite") and name in container.data:
                    raise ResourceExistsError("Existing test blob.")
                if kwargs.get("overwrite") and kwargs.get("etag") != container.versions.get(name):
                    raise ResourceModifiedError("Changed test blob.")
                container.data[name] = body.encode("utf-8") if isinstance(body, str) else body
                container.versions[name] = str(int(container.versions.get(name, "0")) + 1)
                container.uploads.append((name, kwargs))
                return {"etag": container.versions[name]}
            def download_blob(self):
                if name not in container.data:
                    raise ResourceNotFoundError("Missing test blob.")
                return SimpleNamespace(
                    readall=lambda: container.data[name],
                    properties=SimpleNamespace(etag=container.versions[name]),
                )
        return Blob()

    def list_blobs(self, name_starts_with):
        return [SimpleNamespace(name=name) for name in self.data if name.startswith(name_starts_with)]


def test_real_hmac_signs_entire_canonical_record(signer, unsigned, vault):
    signed = signer.sign(unsigned)
    assert unsigned.get("signature") is None
    assert signed["signing_algorithm"] == ALGORITHM and signed["signing_key_version"] == VERSION_1
    assert len(signed["signature"]) == 64
    reordered = dict(reversed(list(signed.items())))
    signer.verify(reordered)
    assert vault.values[VERSION_1] not in json.dumps(signed)


@pytest.mark.parametrize("key,value", [
    ("status", "approved"), ("tenant_id", "another-tenant"), ("object_id", "another-caller"),
    ("scope_key", "another-scope"), ("scope", {"environment": "prod", "project": "001"}),
    ("approval", {"object_id": CALLER, "approved_at": "forged"}),
    ("outcome", {"ok": True, "data": "forged"}), ("plan_hash", "d" * 64),
    ("request", {"expected_revision": "b" * 64}),
    ("expires_at", "2099-01-01T00:00:00+00:00"), ("additional_metadata", "unsigned-addition"),
])
def test_every_persisted_field_is_integrity_protected(signer, unsigned, key, value):
    signed = signer.sign(unsigned)
    signed[key] = value
    with pytest.raises(SigningError) as error:
        signer.verify(signed)
    assert error.value.code == "operation_integrity_failed"


def test_signature_checked_using_constant_time_comparison(signer, unsigned, monkeypatch):
    signed = signer.sign(unsigned)
    comparisons = []
    import hmac
    original = hmac.compare_digest
    def compare(left, right):
        comparisons.append((left, right))
        return original(left, right)
    monkeypatch.setattr("aifactory_agent.signing.hmac.compare_digest", compare)
    signer.verify(signed)
    assert len(comparisons) == 1


def test_rotation_pins_records_and_reads_old_version_from_same_secret(signer, unsigned, vault):
    first = signer.sign(unsigned)
    vault.current_version = VERSION_2
    second = signer.sign({**unsigned, "status": "approved"})
    assert first["signing_key_version"] == VERSION_1 and second["signing_key_version"] == VERSION_2
    signer.verify(first)
    signer.verify(second)
    assert vault.calls[-2:] == [("agent-operation-integrity", VERSION_1), ("agent-operation-integrity", VERSION_2)]
    assert all(name == "agent-operation-integrity" for name, _ in vault.calls)


def test_configured_version_pins_new_signatures(signing_settings, unsigned, vault):
    pinned = signing_settings.model_copy(update={
        "factory": signing_settings.factory.model_copy(update={"operation_signing_secret_url": f"{SIGNING_URL}/{VERSION_1}"}),
    })
    vault.current_version = VERSION_2
    signer = KeyVaultRecordSigner(pinned, secret_client=vault)
    assert signer.sign(unsigned)["signing_key_version"] == VERSION_1
    assert vault.calls == [("agent-operation-integrity", VERSION_1)]


@pytest.mark.parametrize("version", [
    "https://attacker.test/secrets/key/version", "../different-secret", "c" * 31, "C" * 32, None,
])
def test_record_cannot_select_arbitrary_key_url_or_name(signer, unsigned, vault, version):
    signed = signer.sign(unsigned)
    signed["signing_key_version"] = version
    vault.calls.clear()
    with pytest.raises(SigningError):
        signer.verify(signed)
    assert vault.calls == []


def test_record_supplied_secret_url_never_used(signer, unsigned, vault):
    signed = signer.sign(unsigned)
    signed["operation_signing_secret_url"] = "https://attacker.test/secrets/stolen"
    vault.calls.clear()
    with pytest.raises(SigningError):
        signer.verify(signed)
    assert vault.calls == [("agent-operation-integrity", VERSION_1)]


@pytest.mark.parametrize("url", [
    None, "", "http://signing-unit.vault.azure.net/secrets/key", "https://attacker.test/secrets/key",
    "https://signing-unit.vault.azure.net/secrets/key?override=1",
    "https://user:password@signing-unit.vault.azure.net/secrets/key",
    "https://signing-unit.vault.azure.net/secrets/key/../other",
    "https://signing-unit.vault.azure.net:invalid/secrets/key",
])
def test_signing_configuration_fails_closed_before_secret_access(settings, unsigned, vault, monkeypatch, url):
    monkeypatch.setenv("AIFACTORY_OPERATION_SIGNING_KEY", "no-production-environment-fallback")
    configured = settings.model_copy(update={
        "factory": settings.factory.model_copy(update={"operation_signing_secret_url": url}),
    })
    signer = KeyVaultRecordSigner(configured, secret_client=vault)
    with pytest.raises(SigningError) as error:
        signer.sign(unsigned)
    assert error.value.status_code == 503 and vault.calls == []


def test_signing_secret_must_be_dedicated(signing_settings, vault):
    settings = signing_settings.model_copy(update={
        "factory": signing_settings.factory.model_copy(update={"api_key_secret_url": f"{SIGNING_URL}/{VERSION_2}"}),
    })
    with pytest.raises(SigningError):
        KeyVaultRecordSigner(settings, secret_client=vault).ensure_ready()
    assert vault.calls == []


@pytest.mark.parametrize("key_value", [
    "not-base64" * 8, base64.b64encode(b"short").decode("ascii"),
    base64.b64encode(b"X" * 129).decode("ascii"), None,
])
def test_weak_invalid_keys_never_sign(signer, unsigned, vault, key_value):
    vault.values[VERSION_1] = key_value
    with pytest.raises(SigningError) as error:
        signer.sign(unsigned)
    assert error.value.status_code == 503


def test_key_identity_and_requested_version_are_verified(signer, unsigned, vault):
    for secret_id, version, enabled in (
        (f"https://attacker.test/secrets/key/{VERSION_1}", VERSION_1, True),
        (f"https://signing-unit.vault.azure.net/secrets/different/{VERSION_1}", VERSION_1, True),
        (f"{SIGNING_URL}/{VERSION_2}", VERSION_1, True),
        (f"{SIGNING_URL}/{VERSION_1}", VERSION_1, False),
    ):
        vault.response = SimpleNamespace(
            id=secret_id, value=base64.b64encode(b"A" * 32).decode("ascii"),
            properties=SimpleNamespace(version=version, enabled=enabled),
        )
        with pytest.raises(SigningError):
            signer.sign(unsigned)


def test_missing_historical_version_fails_closed(signer, unsigned, vault):
    signed = signer.sign(unsigned)
    del vault.values[VERSION_1]
    with pytest.raises(SigningError) as error:
        signer.verify(signed)
    assert error.value.code == "operation_signing_unavailable"


def test_unsigned_records_never_accepted(signer, unsigned):
    with pytest.raises(SigningError):
        signer.verify(unsigned)


def test_real_secret_client_uses_explicit_credential_and_configured_vault(signing_settings, monkeypatch):
    vault = FakeVault()
    created = []
    def client(**kwargs):
        created.append(kwargs)
        return vault
    monkeypatch.setattr("azure.keyvault.secrets.SecretClient", client)
    cred = object()
    KeyVaultRecordSigner(signing_settings, cred).ensure_ready()
    assert created[0]["vault_url"] == "https://signing-unit.vault.azure.net"
    assert created[0]["credential"] is cred
    assert vault.calls == [("agent-operation-integrity", None)]
