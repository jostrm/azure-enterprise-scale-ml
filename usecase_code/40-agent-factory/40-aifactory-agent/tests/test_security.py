from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from aifactory_agent.config import Settings
from aifactory_agent.security import (
    AuthenticationError, AuthenticationUnavailable, Principal, authorize, principal_from_token,
)


TENANT = "11111111-1111-4111-8111-111111111111"
CALLER = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"
SUBSCRIPTION = "44444444-4444-4444-8444-444444444444"
FACTORY = "55555555-5555-4555-8555-555555555555"
SCALE = "66666666-6666-4666-8666-666666666666"
PROJECT = "77777777-7777-4777-8777-777777777777"
SCOPE = "project001-dev"


@pytest.fixture
def settings():
    scope = {
        "tenant_id": TENANT, "subscription_id": SUBSCRIPTION, "resource_group": "factory-project001-dev-rg",
        "factory": "factory", "project": "001", "environment": "dev",
    }
    return Settings.model_validate({
        "location": "swedencentral", "scopes": {SCOPE: scope, "project002-dev": {**scope, "project": "002"}},
        "azure": {
            "foundry_account": "account", "foundry_project": "project",
            "project_endpoint": "https://example.services.ai.azure.com/api/projects/project",
            "openai_endpoint": "https://example.openai.azure.com",
            "model_deployment": "chat", "model_name": "chat", "model_version": "1",
            "embedding_deployment": "embedding", "search_endpoint": "https://example.search.windows.net",
            "search_index": "agent-index", "storage_endpoint": "https://example.blob.core.windows.net",
            "storage_container": "agent-operations",
        },
        "knowledge": {"repository_root": ".", "source_base_url": "https://example.test", "includes": [], "excludes": []},
        "factory": {
            "api_url": "http://127.0.0.1:8765", "folder": "C:\\state\\factory",
            "factory_id": FACTORY, "scale_set_id": SCALE, "project_id": PROJECT, "writes_enabled": True,
        },
        "auth": {
            "client_id": CLIENT, "audience": f"api://{CLIENT}", "required_scope": "access_as_user",
            "grants": [{"object_id": CALLER, "scopes": [SCOPE],
                        "permissions": ["factory.read", "config.write", "knowledge.read"]}],
        },
    })


@pytest.fixture
def principal():
    return Principal(TENANT, CALLER)


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(**changes):
    now = int(datetime.now(timezone.utc).timestamp())
    return {
        "exp": now + 300, "iat": now - 1, "nbf": now - 1, "tid": TENANT, "oid": CALLER,
        "aud": f"api://{CLIENT}", "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "scp": "access_as_user", "azp": CLIENT, **changes,
    }


def verify(settings, signing_key, body):
    token = jwt.encode(body, signing_key, algorithm="RS256", headers={"kid": "unit-key"})
    keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing_key.public_key()))
    return principal_from_token(settings, token, jwks_client=keys)


def test_real_signed_token_uses_backend_grants(settings, signing_key):
    caller = verify(settings, signing_key, claims(roles=["factory.delete"], scopes=["project002-dev"]))
    assert caller.tenant_id == TENANT and caller.object_id == CALLER
    assert caller.scopes == {SCOPE}
    assert caller.permissions == {"factory.read", "config.write", "knowledge.read"}
    assert authorize(settings, caller, SCOPE, "factory.read") == settings.scopes[SCOPE]


@pytest.mark.parametrize("missing", ["exp", "iat", "nbf", "tid", "oid", "aud", "iss"])
def test_all_identity_and_lifetime_claims_required(settings, signing_key, missing):
    body = claims()
    del body[missing]
    with pytest.raises(AuthenticationError):
        verify(settings, signing_key, body)


@pytest.mark.parametrize("change", [
    {"aud": "https://model-chosen-audience"}, {"aud": [f"api://{CLIENT}"]},
    {"iss": "https://attacker.test/v2.0"}, {"tid": CLIENT}, {"oid": "not-a-guid"},
    {"oid": "00000000-0000-0000-0000-000000000000"}, {"scp": "not_access_as_user"},
    {"scp": None, "roles": ["access_as_user"]}, {"azp": CALLER}, {"exp": 1}, {"iat": "1"},
    {"nbf": 9999999999}, {"iat": 9999999999},
])
def test_invalid_tokens_fail_closed(settings, signing_key, change):
    with pytest.raises(AuthenticationError):
        verify(settings, signing_key, claims(**change))


def test_wrong_signature_and_unsigned_tokens_rejected(settings, signing_key):
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing_key.public_key()))
    for token in (jwt.encode(claims(), wrong, algorithm="RS256"),
                  jwt.encode(claims(), "", algorithm="none")):
        with pytest.raises(AuthenticationError):
            principal_from_token(settings, token, jwks_client=keys)


@pytest.mark.parametrize("field,value", [("client_id", None), ("audience", None), ("client_id", "invalid")])
def test_unconfigured_auth_is_503_before_verification(settings, field, value):
    settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={field: value})})
    with pytest.raises(AuthenticationUnavailable) as error:
        principal_from_token(settings, "irrelevant")
    assert error.value.status_code == 503


def test_default_verifier_uses_fixed_tenant_keys(settings, signing_key, monkeypatch):
    urls = []
    def client(url):
        urls.append(url)
        return SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing_key.public_key()))
    monkeypatch.setattr("aifactory_agent.security._jwks_client", client)
    token = jwt.encode(claims(), signing_key, algorithm="RS256", headers={"jku": "https://attacker.test/keys"})
    principal_from_token(settings, token)
    assert urls == [f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"]


def test_unknown_caller_and_cross_project_denied(settings, principal):
    forged = Principal(TENANT, CLIENT, {"*"}, {"config.write", "factory.read"})
    for caller, scope, permission in (
        (forged, SCOPE, "factory.read"), (principal, "project002-dev", "factory.read"),
        (principal, SCOPE, "factory.delete"), (principal, "unknown", "factory.read"),
        (Principal(CLIENT, CALLER), SCOPE, "factory.read"),
    ):
        with pytest.raises(PermissionError):
            authorize(settings, caller, scope, permission)


def test_permissions_cannot_be_unioned_across_grants(settings, principal):
    values = settings.model_dump(mode="json")
    values["auth"]["grants"] = [
        {"object_id": CALLER, "scopes": [SCOPE], "permissions": ["factory.read"]},
        {"object_id": CALLER, "scopes": ["project002-dev"], "permissions": ["config.write"]},
    ]
    current = Settings.model_validate(values)
    with pytest.raises(PermissionError):
        authorize(current, principal, SCOPE, "config.write")
