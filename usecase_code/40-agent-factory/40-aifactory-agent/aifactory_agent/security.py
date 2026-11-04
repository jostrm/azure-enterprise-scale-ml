from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from uuid import UUID

import jwt

from .config import Scope, Settings


class AuthenticationError(PermissionError):
    status_code = 401


class AuthenticationUnavailable(RuntimeError):
    status_code = 503


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    object_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    client_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "tenant_id", str(UUID(str(self.tenant_id))))
        object.__setattr__(self, "object_id", str(UUID(str(self.object_id))))
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        if self.client_id is not None:
            object.__setattr__(self, "client_id", str(UUID(str(self.client_id))))


def authorize(settings: Settings, principal: Principal, scope_key: str, permission: str) -> Scope:
    scope = settings.scopes.get(scope_key)
    if scope is None or principal.tenant_id != str(scope.tenant_id):
        raise PermissionError("The caller is not authorized for this exact scope.")
    # Re-evaluate current grants, without combining permissions from another scope.
    if not any(
        str(grant.object_id) == principal.object_id
        and scope_key in grant.scopes
        and permission in grant.permissions
        for grant in settings.auth.grants
    ):
        raise PermissionError("The caller lacks the required permission in this exact scope.")
    return scope


@lru_cache(maxsize=16)
def _jwks_client(url: str):
    return jwt.PyJWKClient(url, timeout=10, cache_keys=True, lifespan=300)


def principal_from_token(settings: Settings, token: str, *, jwks_client=None) -> Principal:
    """Validate an Entra v2 delegated access token; injection is for verifier tests."""
    auth = settings.auth
    if not auth.client_id or not auth.audience or not auth.audience.strip():
        raise AuthenticationUnavailable("Entra client_id and audience must be configured.")
    try:
        client_id = str(UUID(auth.client_id))
        if not UUID(client_id).int:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise AuthenticationUnavailable("Entra client_id must be a registration UUID.") from None
    if not auth.required_scope or any(char.isspace() for char in auth.required_scope):
        raise AuthenticationUnavailable("One delegated access scope must be configured.")
    if not isinstance(token, str) or not token or len(token) > 32768:
        raise AuthenticationError("A valid bearer access token is required.")
    tenant = settings.tenant_id
    issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
    keys = jwks_client if jwks_client is not None else _jwks_client(
        f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
    )
    try:
        key = keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=auth.audience,
            issuer=issuer,
            options={
                "require": ["exp", "iat", "nbf", "tid", "oid", "aud", "iss"],
                "strict_aud": True,
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.PyJWKClientConnectionError:
        raise AuthenticationUnavailable("Entra signing keys are temporarily unavailable.") from None
    except (jwt.PyJWTError, ValueError, TypeError):
        raise AuthenticationError("The bearer token failed validation.") from None
    if any(type(claims[name]) is not int for name in ("exp", "iat", "nbf")):
        raise AuthenticationError("Token lifetime claims must be integer NumericDates.")
    try:
        token_tenant = str(UUID(claims["tid"]))
        object_id = str(UUID(claims["oid"]))
    except (ValueError, TypeError, AttributeError):
        raise AuthenticationError("Concrete tenant and caller object IDs are required.") from None
    if token_tenant != tenant or not UUID(object_id).int:
        raise AuthenticationError("The token does not identify a caller in this deployment tenant.")
    delegated = claims.get("scp")
    if not isinstance(delegated, str) or auth.required_scope not in delegated.split():
        raise AuthenticationError("The configured delegated access scope is required.")
    # The primary SPA registration plus explicitly reviewed public clients (for example Azure CLI for the
    # MAUI-embedded Chat) share this audience, scope and grants. The authorized client must be present.
    allowed_clients = {client_id, *(str(client) for client in auth.additional_client_ids)}
    authorized_client = claims.get("azp")
    if not isinstance(authorized_client, str) or authorized_client not in allowed_clients:
        raise AuthenticationError("The token's authorized client differs from the configured registrations.")
    grants = [grant for grant in auth.grants if str(grant.object_id) == object_id]
    return Principal(
        tenant_id=token_tenant,
        object_id=object_id,
        scopes=frozenset(key for grant in grants for key in grant.scopes),
        permissions=frozenset(permission for grant in grants for permission in grant.permissions),
        client_id=authorized_client,
    )
