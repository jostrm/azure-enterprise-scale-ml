from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError

from .config import credential


ALGORITHM = "HMAC-SHA256"
_VERSION = re.compile(r"^[a-f0-9]{32}$")


class SigningError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _reference(value):
    if not isinstance(value, str) or not value:
        raise SigningError("operation_signing_unconfigured", "Configure a dedicated operation signing secret URL.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise SigningError("operation_signing_configuration", "The operation signing secret URL is invalid.") from None
    match = re.fullmatch(r"/secrets/([A-Za-z0-9-]{1,127})(?:/([a-f0-9]{32}))?", parsed.path)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or not re.fullmatch(r"[a-z0-9-]{3,24}\.vault\.azure\.net", parsed.hostname)
        or parsed.username or parsed.password or port or parsed.query or parsed.fragment or not match
    ):
        raise SigningError("operation_signing_configuration", "Configure an exact Azure Key Vault signing secret URL.")
    return f"https://{parsed.hostname}", match[1], match[2]


def _canonical(record: dict) -> bytes:
    if not isinstance(record, dict) or any(not isinstance(key, str) for key in record):
        raise SigningError("operation_integrity_failed", "The operation record cannot be verified.")
    try:
        return json.dumps(
            {key: value for key, value in record.items() if key != "signature"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise SigningError("operation_integrity_failed", "The operation record cannot be verified.") from None


class KeyVaultRecordSigner:
    """Versioned HMAC keys come exclusively from one server-configured Key Vault secret."""

    def __init__(self, settings, cred=None, *, secret_client=None):
        self.settings, self.cred = settings, cred
        self._client = secret_client
        self._binding = None

    def _configured(self):
        if self._binding is None:
            configured = _reference(getattr(self.settings.factory, "operation_signing_secret_url", None))
            api_reference = self.settings.factory.api_key_secret_url
            if api_reference:
                try:
                    api_binding = _reference(api_reference)
                except SigningError:
                    api_binding = None
                if api_binding is not None and configured[:2] == api_binding[:2]:
                    raise SigningError(
                        "operation_signing_configuration", "Operation signing requires a dedicated secret, not the Factory API credential."
                    )
            self._binding = configured
        return self._binding

    def _secret_client(self):
        vault_url, _, _ = self._configured()
        if self._client is None:
            try:
                from azure.keyvault.secrets import SecretClient
            except ImportError:
                raise SigningError("operation_signing_unavailable", "The required Key Vault SDK is not installed.") from None
            self._client = SecretClient(
                vault_url=vault_url, credential=self.cred or credential(self.settings),
                connection_timeout=5, read_timeout=10, retry_total=2,
            )
        return self._client

    def _key(self, version=None):
        vault_url, name, configured_version = self._configured()
        if version is not None and (not isinstance(version, str) or not _VERSION.fullmatch(version)):
            raise SigningError("operation_integrity_failed", "The operation signing key version is invalid.")
        requested_version = version if version is not None else configured_version
        try:
            secret = self._secret_client().get_secret(name, requested_version)
        except AzureError:
            raise SigningError("operation_signing_unavailable", "The configured operation signing key is unavailable.") from None
        properties = getattr(secret, "properties", None)
        returned_version = getattr(properties, "version", None)
        if (
            not isinstance(returned_version, str) or not _VERSION.fullmatch(returned_version)
            or requested_version is not None and requested_version != returned_version
            or getattr(properties, "enabled", None) is False
        ):
            raise SigningError("operation_signing_unavailable", "The signing secret did not return the requested enabled key version.")
        try:
            returned_binding = _reference(secret.id)
        except (SigningError, AttributeError):
            raise SigningError("operation_signing_unavailable", "The signing secret identity could not be verified.") from None
        if returned_binding != (vault_url, name, returned_version):
            raise SigningError("operation_signing_unavailable", "The signing secret identity differs from the configured vault and name.")
        value = getattr(secret, "value", None)
        if not isinstance(value, str) or not 44 <= len(value) <= 172:
            raise SigningError("operation_signing_configuration", "The signing key must be base64-encoded, 32 to 128 bytes.")
        try:
            key = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise SigningError("operation_signing_configuration", "The signing key must be valid base64.") from None
        if not 32 <= len(key) <= 128:
            raise SigningError("operation_signing_configuration", "The signing key must contain 32 to 128 bytes.")
        return returned_version, key

    def ensure_ready(self):
        self._key()

    def sign(self, record: dict) -> dict:
        version, key = self._key()
        signed = copy.deepcopy(record)
        if not isinstance(signed, dict):
            raise SigningError("operation_integrity_failed", "The operation record cannot be signed.")
        signed["signing_algorithm"] = ALGORITHM
        signed["signing_key_version"] = version
        signed["signature"] = hmac.new(key, _canonical(signed), hashlib.sha256).hexdigest()
        return signed

    def verify(self, record: dict):
        self._configured()
        if (
            not isinstance(record, dict) or record.get("signing_algorithm") != ALGORITHM
            or not isinstance(record.get("signature"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", record["signature"])
            or not isinstance(record.get("signing_key_version"), str)
            or not _VERSION.fullmatch(record["signing_key_version"])
        ):
            raise SigningError("operation_integrity_failed", "The operation record has no valid integrity signature.")
        _, key = self._key(record["signing_key_version"])
        expected = hmac.new(key, _canonical(record), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, record["signature"]):
            raise SigningError("operation_integrity_failed", "The operation record integrity check failed.")
