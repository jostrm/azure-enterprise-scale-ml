"""Separate delegated and explicitly scoped, read-only application authentication."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .policy import (
    APPLICATION_READ_ROLE, DEFAULT_APPLICATION_TOOLS, READ_ONLY_APPLICATION_TOOLS,
)

_SCOPE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_ROLE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*")
_MAX_TOKEN_LENGTH = 32768
_REQUIRED_CLAIMS = ("exp", "iat", "nbf", "tid", "oid", "aud", "iss", "ver", "azp", "idtyp", "roles")


class AuthenticationError(PermissionError):
    status_code = 401


class AuthenticationUnavailable(RuntimeError):
    status_code = 503


class TokenVerifier(Protocol):
    def verify(self, token: str) -> object: ...


class DelegatedTokenVerifier:
    """Preserve the actual agent verifier's behavior, identity and errors unchanged."""

    def __init__(self, verify_token: Callable[[str], object]):
        self._verify_token = verify_token

    def verify(self, token: str) -> object:
        return self._verify_token(token)


def _nonzero_uuid(value: object) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise ValueError("A concrete, nonzero UUID is required.")
    try:
        identity = UUID(value) if isinstance(value, str) else value
    except ValueError:
        raise ValueError("A concrete, nonzero UUID is required.") from None
    if not identity.int:
        raise ValueError("A concrete, nonzero UUID is required.")
    return identity


def _explicit_sequence(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        raise ValueError("An explicit list is required.")
    return value


class _ClosedSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ApplicationIdentity(_ClosedSettings):
    object_id: UUID
    client_id: UUID
    scope_keys: tuple[str, ...] = Field(min_length=1)
    allowed_tools: tuple[str, ...] = Field(default=DEFAULT_APPLICATION_TOOLS, min_length=1)

    @field_validator("object_id", "client_id", mode="before")
    @classmethod
    def concrete_identity(cls, value: object) -> UUID:
        return _nonzero_uuid(value)

    @field_validator("scope_keys", "allowed_tools", mode="before")
    @classmethod
    def explicit_names(cls, value: object) -> object:
        _explicit_sequence(value)
        if any(not isinstance(name, str) for name in value):
            raise ValueError("Names must be explicit strings.")
        return value

    @field_validator("scope_keys")
    @classmethod
    def safe_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(_SCOPE_KEY.fullmatch(value) is None for value in values):
            raise ValueError("Scope keys must be unique, safe, explicit names.")
        return values

    @field_validator("allowed_tools")
    @classmethod
    def reviewed_tools(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or not set(values) <= READ_ONLY_APPLICATION_TOOLS:
            raise ValueError("Tools must be unique members of the reviewed read-only application allowlist.")
        return values


class ApplicationAuthSettings(_ClosedSettings):
    audience: str
    required_role: str = APPLICATION_READ_ROLE
    identities: tuple[ApplicationIdentity, ...] = Field(min_length=1)

    @field_validator("audience", mode="before")
    @classmethod
    def concrete_audience(cls, value: object) -> str:
        return str(_nonzero_uuid(value))

    @field_validator("required_role", mode="before")
    @classmethod
    def explicit_role(cls, value: object) -> str:
        if not isinstance(value, str) or len(value) > 128 or _ROLE.fullmatch(value) is None:
            raise ValueError("One safe, explicit application role name is required.")
        return value

    @field_validator("identities", mode="before")
    @classmethod
    def explicit_identities(cls, value: object) -> object:
        return _explicit_sequence(value)

    @model_validator(mode="after")
    def unique_identity_bindings(self) -> ApplicationAuthSettings:
        if (len({identity.object_id for identity in self.identities}) != len(self.identities)
                or len({identity.client_id for identity in self.identities}) != len(self.identities)):
            raise ValueError("Application object IDs and client IDs must each be unique.")
        return self


@dataclass(frozen=True)
class ApplicationPrincipal:
    """Verified application identity and its server-configured authorization ceiling."""

    principal: object
    scope_keys: frozenset[str]
    allowed_tools: frozenset[str]

    def __post_init__(self):
        object.__setattr__(self, "scope_keys", frozenset(self.scope_keys))
        object.__setattr__(self, "allowed_tools", frozenset(self.allowed_tools))


def _check_token(token: str) -> None:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise AuthenticationError("A valid bearer access token is required.")


def _canonical_claim(value: object) -> str:
    try:
        if not isinstance(value, str) or str(_nonzero_uuid(value)) != value:
            raise ValueError
    except ValueError:
        raise AuthenticationError("The bearer token failed validation.") from None
    return value


class ApplicationTokenVerifier:
    """Validate v2 app tokens; roles must contain exactly the configured role, with no extras.

    Roles never grant tools or scopes. Those limits come solely from the configured
    object/client identity pair. The injected factory is the loaded agent's Principal.
    """

    def __init__(
        self, tenant_id: str, settings: ApplicationAuthSettings,
        principal_factory: Callable[[str, str], object], *, jwks_client=None,
    ):
        self.tenant_id = str(_nonzero_uuid(tenant_id))
        self.settings = settings
        self._principal_factory = principal_factory
        self._issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        self._identities = {
            (str(identity.object_id), str(identity.client_id)): identity
            for identity in settings.identities
        }
        self._jwks_client = jwks_client if jwks_client is not None else jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys",
            timeout=10, cache_keys=True, lifespan=300,
        )

    def verify(self, token: str) -> ApplicationPrincipal:
        _check_token(token)
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise AuthenticationError("The bearer token failed validation.")
        except (jwt.PyJWTError, ValueError, TypeError):
            raise AuthenticationError("The bearer token failed validation.") from None
        try:
            # The tenant-derived client ignores token-supplied jku/x5u URLs.
            key = self._jwks_client.get_signing_key_from_jwt(token)
        except (jwt.PyJWKClientConnectionError, OSError, RuntimeError):
            raise AuthenticationUnavailable("Entra signing keys are temporarily unavailable.") from None
        except (jwt.PyJWTError, ValueError, TypeError):
            raise AuthenticationError("The bearer token failed validation.") from None
        try:
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"],
                audience=self.settings.audience, issuer=self._issuer,
                options={
                    "require": list(_REQUIRED_CLAIMS), "strict_aud": True,
                    "verify_signature": True, "verify_exp": True, "verify_iat": True,
                    "verify_nbf": True, "verify_aud": True, "verify_iss": True,
                },
            )
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
            raise AuthenticationError("The bearer token failed validation.") from None
        if (any(type(claims[name]) is not int for name in ("exp", "iat", "nbf"))
                or claims["ver"] != "2.0" or claims["idtyp"] != "app" or "scp" in claims
                or not isinstance(claims["roles"], list)
                or claims["roles"] != [self.settings.required_role]):
            raise AuthenticationError("The bearer token failed validation.")
        tenant = _canonical_claim(claims["tid"])
        object_id = _canonical_claim(claims["oid"])
        client_id = _canonical_claim(claims["azp"])
        identity = self._identities.get((object_id, client_id))
        if tenant != self.tenant_id or identity is None:
            raise AuthenticationError("The bearer token failed validation.")
        return ApplicationPrincipal(
            self._principal_factory(tenant, object_id),
            frozenset(identity.scope_keys), frozenset(identity.allowed_tools),
        )


def _audience_registration(audience: str) -> str:
    """Recognize registration aliases only for configuration separation, never routing."""
    candidate = audience[6:] if audience[:6].lower() == "api://" else audience
    try:
        return str(UUID(candidate))
    except ValueError:
        return audience


class AudienceTokenVerifier:
    """Use an unsigned audience only to select one full verifier, never as authentication."""

    def __init__(
        self, delegated: TokenVerifier, delegated_audience: str,
        application: ApplicationTokenVerifier,
    ):
        if (not isinstance(delegated_audience, str) or not delegated_audience.strip()
                or delegated_audience != delegated_audience.strip()
                or _audience_registration(delegated_audience) == application.settings.audience):
            raise ValueError("Separate, explicit delegated and application audiences are required.")
        self._delegated = delegated
        self._delegated_audience = delegated_audience
        self._application = application

    def verify(self, token: str) -> object:
        _check_token(token)
        try:
            routing_claims = jwt.decode(token, options={"verify_signature": False})
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
            raise AuthenticationError("The bearer token failed validation.") from None
        audience = routing_claims.get("aud")
        if not isinstance(audience, str):
            raise AuthenticationError("The bearer token failed validation.")
        if audience == self._delegated_audience:
            return self._delegated.verify(token)
        if audience == self._application.settings.audience:
            return self._application.verify(token)
        raise AuthenticationError("The bearer token failed validation.")


def load_application_auth(path: str | Path) -> ApplicationAuthSettings:
    try:
        return ApplicationAuthSettings.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError, TypeError):
        raise RuntimeError("The explicit application authentication configuration could not be loaded.") from None
