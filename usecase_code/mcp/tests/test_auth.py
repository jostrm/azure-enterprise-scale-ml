import json
import time
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from test_runtime import (
    SCOPE, artifacts, config_path, configuration, runtime, security_fixtures, signing_key,
)
from aifactory_mcp.auth import (
    READ_ONLY_APPLICATION_TOOLS,
    ApplicationAuthSettings,
    ApplicationIdentity,
    ApplicationPrincipal,
    ApplicationTokenVerifier,
    AudienceTokenVerifier,
    AuthenticationError,
    AuthenticationUnavailable,
    DelegatedTokenVerifier,
    load_application_auth,
)


TENANT = security_fixtures.TENANT
AUDIENCE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OBJECT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CLIENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OTHER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
ZERO = "00000000-0000-0000-0000-000000000000"
ROLE = "AiFactory.Mcp.Read"
DEFAULT_TOOLS = ("factory_health", "factory_capabilities", "factory_skills")


def settings_values():
    return {
        "audience": AUDIENCE,
        "identities": [{"object_id": OBJECT, "client_id": CLIENT, "scope_keys": [SCOPE]}],
    }


def application_claims(**changes):
    now = int(time.time())
    return {
        "exp": now + 300, "iat": now - 1, "nbf": now - 1, "tid": TENANT,
        "oid": OBJECT, "azp": CLIENT, "aud": AUDIENCE,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "ver": "2.0", "idtyp": "app", "roles": [ROLE], **changes,
    }


@pytest.fixture
def application_settings():
    return ApplicationAuthSettings.model_validate(settings_values())


@pytest.fixture
def keys(signing_key):
    return Mock(get_signing_key_from_jwt=Mock(
        return_value=SimpleNamespace(key=signing_key.public_key()),
    ))


@pytest.fixture
def application_verifier(runtime, application_settings, keys):
    return ApplicationTokenVerifier(
        TENANT, application_settings, runtime.security.Principal, jwks_client=keys,
    )


def signed(signing_key, claims=None, **kwargs):
    return jwt.encode(
        application_claims() if claims is None else claims,
        signing_key, algorithm="RS256", **kwargs,
    )


def test_application_config_is_closed_frozen_and_accepts_json(application_settings):
    settings = ApplicationAuthSettings.model_validate_json(json.dumps(settings_values()))
    assert settings == application_settings
    assert settings.audience == AUDIENCE
    assert settings.required_role == ROLE
    assert isinstance(settings.identities, tuple)
    identity = settings.identities[0]
    assert isinstance(identity, ApplicationIdentity)
    assert identity.object_id == UUID(OBJECT)
    assert identity.client_id == UUID(CLIENT)
    assert identity.scope_keys == (SCOPE,)
    assert identity.allowed_tools == DEFAULT_TOOLS
    with pytest.raises(ValidationError):
        settings.audience = OTHER
    with pytest.raises(ValidationError):
        identity.scope_keys = ("other",)


def test_config_canonicalizes_uuid_strings():
    values = settings_values()
    values["audience"] = AUDIENCE.upper()
    values["identities"][0]["object_id"] = OBJECT.upper()
    values["identities"][0]["client_id"] = CLIENT.upper()
    settings = ApplicationAuthSettings.model_validate(values)
    assert settings.audience == AUDIENCE
    assert str(settings.identities[0].object_id) == OBJECT
    assert str(settings.identities[0].client_id) == CLIENT


@pytest.mark.parametrize("field,value", [
    ("audience", ZERO), ("audience", "api://" + AUDIENCE), ("audience", ""),
    ("audience", None), ("audience", 123), ("audience", [AUDIENCE]),
    ("audience", "not-a-uuid"), ("identities", []), ("identities", None),
    ("identities", {}), ("identities", "identity"),
    ("required_role", ""), ("required_role", "*"), ("required_role", "AiFactory.*"),
    ("required_role", "read write"), ("required_role", " read"), ("required_role", "read\n"),
    ("required_role", 3), ("required_role", ["read"]), ("required_role", "read/anything"),
    ("required_role", "a" * 129), ("required_role", True), ("secret", "not-allowed"),
    ("credentials", {"token": "not-allowed"}), ("jwks_url", "https://untrusted.invalid"),
])
def test_config_rejects_invalid_top_level_values(field, value):
    values = settings_values()
    values[field] = value
    with pytest.raises(ValidationError):
        ApplicationAuthSettings.model_validate(values)


@pytest.mark.parametrize("field,value", [
    ("object_id", ZERO), ("client_id", ZERO), ("object_id", "invalid"),
    ("client_id", "invalid"), ("object_id", 1), ("client_id", True),
    ("object_id", None), ("client_id", None),
    ("scope_keys", []), ("scope_keys", [SCOPE, SCOPE]), ("scope_keys", ["*"]),
    ("scope_keys", ["project*"]), ("scope_keys", ["../project"]),
    ("scope_keys", ["project/dev"]), ("scope_keys", ["project\\dev"]),
    ("scope_keys", ["project dev"]), ("scope_keys", ["project\n"]),
    ("scope_keys", [""]), ("scope_keys", ["a" * 129]), ("scope_keys", [1]),
    ("scope_keys", SCOPE), ("scope_keys", {SCOPE}),
    ("allowed_tools", []), ("allowed_tools", ["factory_health", "factory_health"]),
    ("allowed_tools", ["*"]), ("allowed_tools", ["factory_*"]),
    ("allowed_tools", ["factory_cli_health"]), ("allowed_tools", ["factory_operations"]),
    ("allowed_tools", ["factory_operation_status"]), ("allowed_tools", ["factory_list_operations"]),
    ("allowed_tools", ["factory_prepare_action"]), ("allowed_tools", ["factory_execute_operation"]),
    ("allowed_tools", ["factory_cancel_operation"]), ("allowed_tools", ["factory_approve_operation"]),
    ("allowed_tools", ["health_custom_api"]), ("allowed_tools", ["factory_health "]),
    ("allowed_tools", [1]), ("allowed_tools", "factory_health"),
    ("allowed_tools", {"factory_health"}), ("permissions", ["factory.delete"]),
    ("token", "not-allowed"),
])
def test_config_rejects_unsafe_identity_values(field, value):
    values = settings_values()
    values["identities"][0][field] = value
    with pytest.raises(ValidationError):
        ApplicationAuthSettings.model_validate(values)


@pytest.mark.parametrize("missing", ["audience", "identities"])
def test_config_requires_audience_and_identities(missing):
    values = settings_values()
    del values[missing]
    with pytest.raises(ValidationError):
        ApplicationAuthSettings.model_validate(values)


@pytest.mark.parametrize("missing", ["object_id", "client_id", "scope_keys"])
def test_config_requires_identity_binding_and_scopes(missing):
    values = settings_values()
    del values["identities"][0][missing]
    with pytest.raises(ValidationError):
        ApplicationAuthSettings.model_validate(values)


@pytest.mark.parametrize("second", [
    {"object_id": OBJECT, "client_id": CLIENT},
    {"object_id": OBJECT, "client_id": OTHER},
    {"object_id": OTHER, "client_id": CLIENT},
    {"object_id": OBJECT.upper(), "client_id": OTHER},
])
def test_config_rejects_duplicate_identity_bindings(second):
    values = settings_values()
    values["identities"].append({**second, "scope_keys": ["other-dev"]})
    with pytest.raises(ValidationError):
        ApplicationAuthSettings.model_validate(values)


def test_read_only_allowlist_is_exact_and_immutable():
    assert READ_ONLY_APPLICATION_TOOLS == frozenset({
        "factory_health", "factory_capabilities", "factory_skills", "factory_catalog",
        "factory_settings", "cost_default_project_idle", "cost_common_idle",
        "cost_monthly_project_forecast",
        "graph_status", "graph_query", "architecture_search", "architecture_note", "dual_graph_context",
    })
    assert isinstance(READ_ONLY_APPLICATION_TOOLS, frozenset)
    values = settings_values()
    values["identities"][0]["allowed_tools"] = sorted(READ_ONLY_APPLICATION_TOOLS)
    settings = ApplicationAuthSettings.model_validate(values)
    assert frozenset(settings.identities[0].allowed_tools) == READ_ONLY_APPLICATION_TOOLS


def test_load_explicit_application_config(application_settings, artifacts):
    path = artifacts / "application.json"
    path.write_text(json.dumps(settings_values()), encoding="utf-8")
    assert load_application_auth(path) == application_settings
    assert load_application_auth(str(path)) == application_settings


@pytest.mark.parametrize("contents", [
    '{"token":"configuration-secret"}',
    '{"audience": "configuration-secret", "identities":[]}',
    '{"identities": [configuration-secret]}',
])
def test_invalid_config_errors_are_sanitized(artifacts, contents):
    path = artifacts / "application.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(RuntimeError) as error:
        load_application_auth(path)
    assert "configuration-secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_unreadable_config_error_does_not_echo_path(artifacts):
    with pytest.raises(RuntimeError) as error:
        load_application_auth(artifacts / "configuration-secret.json")
    assert "configuration-secret" not in str(error.value)


def test_application_uses_actual_agent_principal_and_frozen_policy(application_verifier, signing_key, runtime):
    principal = application_verifier.verify(signed(signing_key))
    assert isinstance(principal, ApplicationPrincipal)
    assert not isinstance(principal, runtime.security.Principal)
    assert isinstance(principal.principal, runtime.security.Principal)
    assert principal.principal.tenant_id == TENANT
    assert principal.principal.object_id == OBJECT
    assert principal.principal.permissions == frozenset()
    assert principal.principal.scopes == frozenset()
    assert principal.scope_keys == frozenset({SCOPE})
    assert principal.allowed_tools == frozenset(DEFAULT_TOOLS)
    with pytest.raises(FrozenInstanceError):
        principal.scope_keys = frozenset({"other-dev"})


def test_principal_wrapper_freezes_mutable_input(runtime):
    scopes, tools = {SCOPE}, {"factory_health"}
    principal = ApplicationPrincipal(runtime.security.Principal(TENANT, OBJECT), scopes, tools)
    scopes.add("other-dev")
    tools.add("factory_execute_operation")
    assert principal.scope_keys == frozenset({SCOPE})
    assert principal.allowed_tools == frozenset({"factory_health"})


def test_token_supplied_scope_and_tools_never_override_policy(application_verifier, signing_key):
    principal = application_verifier.verify(signed(signing_key, application_claims(
        scope_keys=["other-dev"], scopes=["other-dev"], permissions=["factory.delete"],
        allowed_tools=["factory_execute_operation"],
    )))
    assert principal.scope_keys == frozenset({SCOPE})
    assert principal.allowed_tools == frozenset(DEFAULT_TOOLS)
    assert principal.principal.permissions == frozenset()


def test_multiple_application_identities_do_not_combine_policy(runtime, keys, signing_key):
    values = settings_values()
    values["identities"].append({
        "object_id": OTHER, "client_id": AUDIENCE,
        "scope_keys": ["other-dev"], "allowed_tools": ["factory_catalog"],
    })
    verifier = ApplicationTokenVerifier(
        TENANT, ApplicationAuthSettings.model_validate(values), runtime.security.Principal,
        jwks_client=keys,
    )
    selected = verifier.verify(signed(signing_key, application_claims(oid=OTHER, azp=AUDIENCE)))
    assert selected.scope_keys == frozenset({"other-dev"})
    assert selected.allowed_tools == frozenset({"factory_catalog"})
    with pytest.raises(AuthenticationError):
        verifier.verify(signed(signing_key, application_claims(oid=OBJECT, azp=AUDIENCE)))


@pytest.mark.parametrize("missing", [
    "exp", "iat", "nbf", "tid", "oid", "aud", "iss", "ver", "azp", "idtyp", "roles",
])
def test_application_requires_all_security_claims(application_verifier, signing_key, missing):
    claims = application_claims()
    del claims[missing]
    with pytest.raises(AuthenticationError):
        application_verifier.verify(signed(signing_key, claims))


@pytest.mark.parametrize("changes", [
    {"tid": OTHER}, {"tid": ZERO}, {"tid": 1}, {"tid": None},
    {"tid": "{" + TENANT + "}"}, {"tid": TENANT.replace("-", "")},
    {"oid": OTHER}, {"oid": ZERO}, {"oid": 1}, {"oid": OBJECT.upper()},
    {"azp": OTHER}, {"azp": ZERO}, {"azp": 1}, {"azp": CLIENT.upper()},
    {"aud": OTHER}, {"aud": "api://" + AUDIENCE}, {"aud": AUDIENCE.upper()},
    {"aud": [AUDIENCE]}, {"aud": [AUDIENCE, OTHER]},
    {"iss": f"https://login.microsoftonline.com/{OTHER}/v2.0"},
    {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0/"},
    {"iss": f"https://sts.windows.net/{TENANT}/"}, {"iss": "https://attacker.invalid"},
    {"ver": "1.0"}, {"ver": 2}, {"ver": None},
    {"idtyp": "user"}, {"idtyp": "APP"}, {"idtyp": None},
    {"scp": "access_as_user"}, {"scp": ""}, {"scp": None}, {"scp": []},
    {"roles": []}, {"roles": ROLE}, {"roles": [1]}, {"roles": [ROLE, 1]},
    {"roles": ["factory.read"]}, {"roles": [ROLE, "factory.delete"]},
    {"roles": [ROLE, ROLE]}, {"roles": [ROLE.lower()]}, {"roles": None},
    {"exp": 1}, {"iat": 9999999999}, {"nbf": 9999999999},
    {"exp": True}, {"iat": True}, {"nbf": False},
    {"exp": 9999999999.0}, {"iat": 1.0}, {"nbf": 1.0},
    {"exp": "9999999999"}, {"iat": "1"}, {"nbf": "1"},
    {"exp": None}, {"iat": None}, {"nbf": None},
])
def test_application_rejects_invalid_signed_tokens(application_verifier, signing_key, changes):
    with pytest.raises(AuthenticationError) as error:
        application_verifier.verify(signed(signing_key, application_claims(**changes)))
    assert error.value.status_code == 401


def test_custom_required_role_is_exact(runtime, keys, signing_key):
    values = settings_values()
    values["required_role"] = "Spider.Mcp.Read"
    verifier = ApplicationTokenVerifier(
        TENANT, ApplicationAuthSettings.model_validate(values), runtime.security.Principal,
        jwks_client=keys,
    )
    assert verifier.verify(signed(signing_key, application_claims(roles=["Spider.Mcp.Read"])))
    with pytest.raises(AuthenticationError):
        verifier.verify(signed(signing_key))


def test_application_rejects_wrong_signature(application_verifier):
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthenticationError):
        application_verifier.verify(signed(wrong_key))


@pytest.mark.parametrize("algorithm,key", [("none", ""), ("HS256", "unit-only-signing-secret-with-32-bytes")])
def test_application_rejects_unapproved_algorithm_before_key_lookup(application_verifier, keys, algorithm, key):
    token = jwt.encode(application_claims(), key, algorithm=algorithm)
    with pytest.raises(AuthenticationError):
        application_verifier.verify(token)
    keys.get_signing_key_from_jwt.assert_not_called()


def test_application_uses_only_trusted_tenant_jwks_and_reuses_client(
    runtime, application_settings, keys, signing_key, monkeypatch,
):
    constructor = Mock(return_value=keys)
    monkeypatch.setattr("aifactory_mcp.auth.jwt.PyJWKClient", constructor)
    verifier = ApplicationTokenVerifier(TENANT, application_settings, runtime.security.Principal)
    token = signed(signing_key, headers={
        "kid": "unit-key", "jku": "https://attacker.invalid/keys",
        "x5u": "https://attacker.invalid/certificate",
    })
    assert verifier.verify(token).principal.object_id == OBJECT
    assert verifier.verify(token).principal.object_id == OBJECT
    constructor.assert_called_once()
    assert constructor.call_args.args == (
        f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys",
    )
    assert constructor.call_args.kwargs["cache_keys"] is True
    assert keys.get_signing_key_from_jwt.call_count == 2


@pytest.mark.parametrize("tenant", [ZERO, "common", "organizations", "", None, 1, "../tenant"])
def test_application_requires_concrete_tenant(application_settings, tenant, keys):
    with pytest.raises(ValueError):
        ApplicationTokenVerifier(tenant, application_settings, Mock(), jwks_client=keys)


@pytest.mark.parametrize("failure", [
    jwt.PyJWKClientConnectionError("token-secret"), OSError("token-secret"),
    TimeoutError("token-secret"), RuntimeError("token-secret"),
])
def test_unavailable_keys_are_sanitized(application_verifier, keys, signing_key, failure):
    keys.get_signing_key_from_jwt.side_effect = failure
    with pytest.raises(AuthenticationUnavailable) as error:
        application_verifier.verify(signed(signing_key))
    assert error.value.status_code == 503
    assert "token-secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_unknown_signing_key_fails_authentication(application_verifier, keys, signing_key):
    keys.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("token-secret")
    with pytest.raises(AuthenticationError) as error:
        application_verifier.verify(signed(signing_key))
    assert "token-secret" not in str(error.value)


def test_principal_factory_only_called_after_full_validation(application_settings, signing_key, keys, runtime):
    factory = Mock(side_effect=runtime.security.Principal)
    verifier = ApplicationTokenVerifier(TENANT, application_settings, factory, jwks_client=keys)
    with pytest.raises(AuthenticationError):
        verifier.verify(signed(signing_key, application_claims(roles=["wrong"])))
    factory.assert_not_called()
    verifier.verify(signed(signing_key))
    factory.assert_called_once_with(TENANT, OBJECT)


@pytest.mark.parametrize("token", [
    "", None, b"token-secret", 1, "token-secret", "a.b.c", "a.b.c.d",
    pytest.param("x" * 32769, id="oversize"),
])
def test_malformed_and_oversize_tokens_rejected_before_keys(application_verifier, keys, token):
    with pytest.raises(AuthenticationError) as error:
        application_verifier.verify(token)
    assert "token-secret" not in str(error.value)
    keys.get_signing_key_from_jwt.assert_not_called()


def test_delegated_adapter_is_transparent():
    result = object()
    authenticate = Mock(return_value=result)
    assert DelegatedTokenVerifier(authenticate).verify("opaque-token") is result
    authenticate.assert_called_once_with("opaque-token")
    failure = PermissionError("existing delegated error")
    authenticate.side_effect = failure
    with pytest.raises(PermissionError) as error:
        DelegatedTokenVerifier(authenticate).verify("opaque-token")
    assert error.value is failure


def test_router_preserves_actual_delegated_verification(runtime, keys, signing_key, application_verifier):
    delegate = DelegatedTokenVerifier(lambda token: runtime.security.principal_from_token(
        runtime.settings, token, jwks_client=keys,
    ))
    router = AudienceTokenVerifier(delegate, runtime.settings.auth.audience, application_verifier)
    claims = security_fixtures.claims()
    token = signed(signing_key, claims)
    principal = router.verify(token)
    assert isinstance(principal, runtime.security.Principal)
    assert principal.object_id == security_fixtures.CALLER
    assert principal.scopes == frozenset({SCOPE})
    assert "factory.read" in principal.permissions
    for changes in ({"scp": "wrong"}, {"tid": OTHER}, {"azp": OTHER}, {"exp": 1}):
        with pytest.raises(PermissionError):
            router.verify(signed(signing_key, {**claims, **changes}))
    app = router.verify(signed(signing_key))
    assert isinstance(app, ApplicationPrincipal)


def test_router_routes_to_application_full_verifier(application_verifier, signing_key):
    delegated = Mock()
    router = AudienceTokenVerifier(delegated, "api://delegated", application_verifier)
    principal = router.verify(signed(signing_key))
    assert isinstance(principal, ApplicationPrincipal)
    delegated.verify.assert_not_called()


@pytest.mark.parametrize("audience", [
    AUDIENCE, AUDIENCE.upper(), "api://" + AUDIENCE, "api://" + AUDIENCE.upper(),
    "API://" + AUDIENCE.upper(), "", " ", None, 1, [AUDIENCE],
])
def test_router_requires_separate_nonempty_audiences(application_verifier, audience):
    with pytest.raises(ValueError):
        AudienceTokenVerifier(Mock(), audience, application_verifier)


@pytest.mark.parametrize("audience,other_form", [
    (OTHER.upper(), OTHER),
    ("api://" + OTHER.upper(), "api://" + OTHER),
    ("https://custom.example/resource", "https://custom.example/Resource"),
    ("api://not-a-uuid", "not-a-uuid"),
    ("api://" + AUDIENCE + "/custom", "api://" + AUDIENCE + "/Custom"),
])
def test_router_audience_separation_does_not_normalize_routing(
    application_verifier, signing_key, audience, other_form,
):
    delegated = Mock()
    router = AudienceTokenVerifier(delegated, audience, application_verifier)
    token = signed(signing_key, application_claims(aud=audience))
    assert router.verify(token) is delegated.verify.return_value
    delegated.verify.assert_called_once_with(token)
    delegated.reset_mock()
    with pytest.raises(AuthenticationError):
        router.verify(signed(signing_key, application_claims(aud=other_form)))
    delegated.verify.assert_not_called()


@pytest.mark.parametrize("audience", [OTHER, [AUDIENCE], [AUDIENCE, OTHER], None, 1, ""])
def test_router_rejects_unknown_or_array_audience(application_verifier, signing_key, audience):
    delegated, application = Mock(), Mock(wraps=application_verifier)
    application.settings = application_verifier.settings
    router = AudienceTokenVerifier(delegated, "api://delegated", application)
    with pytest.raises(AuthenticationError):
        router.verify(signed(signing_key, application_claims(aud=audience)))
    delegated.verify.assert_not_called()
    application.verify.assert_not_called()


@pytest.mark.parametrize("token", [
    "", None, b"opaque", 1, "token-secret", "a.b.c", pytest.param("x" * 32769, id="oversize"),
])
def test_router_rejects_bad_token_without_invoking_verifiers(application_verifier, token):
    delegated, application = Mock(), Mock(wraps=application_verifier)
    application.settings = application_verifier.settings
    router = AudienceTokenVerifier(delegated, "api://delegated", application)
    with pytest.raises(AuthenticationError):
        router.verify(token)
    delegated.verify.assert_not_called()
    application.verify.assert_not_called()


@pytest.mark.parametrize("selected", ["delegated", "application"])
@pytest.mark.parametrize("failure", [AuthenticationError("denied"), AuthenticationUnavailable("offline")])
def test_router_never_falls_back_after_selected_verifier_fails(
    application_verifier, signing_key, selected, failure,
):
    delegated, application = Mock(), Mock(wraps=application_verifier)
    application.settings = application_verifier.settings
    chosen = delegated if selected == "delegated" else application
    other = application if selected == "delegated" else delegated
    chosen.verify.side_effect = failure
    audience = "api://delegated" if selected == "delegated" else AUDIENCE
    token = signed(signing_key, application_claims(aud=audience))
    router = AudienceTokenVerifier(delegated, "api://delegated", application)
    with pytest.raises(type(failure)) as error:
        router.verify(token)
    assert error.value is failure
    chosen.verify.assert_called_once_with(token)
    other.verify.assert_not_called()


def test_router_unsigned_routing_hint_never_authenticates(application_verifier):
    delegate = Mock()
    router = AudienceTokenVerifier(delegate, "api://delegated", application_verifier)
    unsigned = jwt.encode(application_claims(), "", algorithm="none")
    with pytest.raises(AuthenticationError):
        router.verify(unsigned)
    delegate.verify.assert_not_called()
