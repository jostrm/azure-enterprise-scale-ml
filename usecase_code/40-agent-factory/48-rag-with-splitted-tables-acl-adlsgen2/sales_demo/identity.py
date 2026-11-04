"""Trusted-local-CLI delegated users, kept separate from the backend identity.

This is NOT a bearer-token validation API. Tokens originate only in the local
Azure CLI OAuth provider. Decoded claims are consistency checks, not signature
verification; authenticated Graph /me establishes the principal and Graph checks
current transitive groups on every operation. Search and Storage subsequently
validate their own audience tokens. Do not expose injected adapters over a server.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

GRAPH = "https://graph.microsoft.com"
SEARCH = "https://search.azure.com"
STORAGE = "https://storage.azure.com"
GROUP_PATH = "/v1.0/me/transitiveMemberOf/microsoft.graph.group"
UNAVAILABLE = "Sales data unavailable."


class SalesUnavailable(RuntimeError):
    def __init__(self):
        super().__init__(UNAVAILABLE)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise SalesUnavailable()


@dataclass(frozen=True)
class UserIdentity:
    tenant_id: str
    oid: str
    group_ids: frozenset[str]
    search_token: str = field(repr=False)
    storage_token: str = field(repr=False)


def backend_credential(client_id: str):
    """Never fall back to the operator or DefaultAzureCredential."""
    from azure.identity import ManagedIdentityCredential
    return ManagedIdentityCredential(client_id=str(UUID(client_id)))


class AzureCliTokenProvider:
    def __init__(self, tenant_id: str, subscription_id: str, *, config_dir: Path | None = None):
        self.tenant_id = str(UUID(tenant_id))
        self.subscription_id = str(UUID(subscription_id))
        self.config_dir = None if config_dir is None else Path(config_dir).resolve()
        if self.config_dir is not None and not self.config_dir.is_dir():
            raise ValueError("The separately authenticated Azure CLI profile directory must already exist.")

    def token(self, resource: str) -> str:
        if resource not in {GRAPH, SEARCH, STORAGE}:
            raise SalesUnavailable()
        executable = shutil.which("az")
        if not executable:
            raise SalesUnavailable()
        environment = dict(os.environ)
        if self.config_dir is not None:
            environment["AZURE_CONFIG_DIR"] = str(self.config_dir)
        result = subprocess.run(
            [executable, "account", "get-access-token", "--tenant", self.tenant_id,
             "--resource", resource, "--output", "json", "--only-show-errors"],
            capture_output=True, text=True, timeout=90, check=False, env=environment,
        )
        try:
            document = json.loads(result.stdout)
            if result.returncode or str(UUID(document["tenant"])) != self.tenant_id:
                raise SalesUnavailable()
            bearer = document["accessToken"]
            if not isinstance(bearer, str) or not bearer or "\n" in bearer or "\r" in bearer:
                raise SalesUnavailable()
            return bearer
        except (KeyError, ValueError, TypeError):
            raise SalesUnavailable() from None


class GraphTransport:
    def get(self, url: str, bearer: str) -> dict:
        _graph_url(url)
        headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        if urlsplit(url).path == GROUP_PATH:
            headers["ConsistencyLevel"] = "eventual"
        request = Request(url, headers=headers)
        with build_opener(ProxyHandler({}), NoRedirects()).open(request, timeout=45) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise SalesUnavailable()
        return json.loads(raw)


def search_endpoint(config: dict) -> str:
    parsed = urlsplit(config["search_endpoint"])
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".search.windows.net")
            or parsed.port is not None or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("Select one exact HTTPS Search service endpoint.")
    return config["search_endpoint"].rstrip("/")


class ManagedIdentitySearchTransport:
    """Runtime Search backend. Not the operator ingestion/admin transport."""
    def __init__(self, config: dict):
        self.endpoint = search_endpoint(config)
        self.credential = backend_credential(config["backend_identity_client_id"])

    def request(self, method, url, body=None, *, audience=SEARCH, headers=None):
        parsed, origin = urlsplit(url), urlsplit(self.endpoint)
        supplied = headers or {}
        if (audience != SEARCH or parsed.scheme != "https" or parsed.netloc != origin.netloc
                or parsed.fragment or method not in {"GET", "POST"}
                or not parsed.path.startswith(("/indexes/", "/indexers/"))
                or set(supplied) - {"x-ms-query-source-authorization"}):
            raise SalesUnavailable()
        is_query = parsed.path.endswith("/docs/search")
        if ((method == "POST" and not is_query)
                or (is_query and not supplied.get("x-ms-query-source-authorization"))
                or (not is_query and not parsed.path.endswith("/status"))):
            raise SalesUnavailable()
        from agent_factory.data import require_private_endpoint
        require_private_endpoint(url)
        bearer = self.credential.get_token(SEARCH + "/.default").token
        payload = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(url, data=payload, method=method, headers={
            "Authorization": f"Bearer {bearer}", "Content-Type": "application/json",
            "Accept": "application/json", **supplied,
        })
        with build_opener(ProxyHandler({}), NoRedirects()).open(request, timeout=60) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise SalesUnavailable()
        return json.loads(raw)


def _graph_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
            or parsed.fragment or parsed.path not in {"/v1.0/me", GROUP_PATH}):
        raise SalesUnavailable()


def _claims(bearer: str, resource: str, tenant: str) -> dict:
    """Consistency checks on tokens obtained from the trusted OAuth provider."""
    try:
        if not isinstance(bearer, str) or "\r" in bearer or "\n" in bearer:
            raise ValueError()
        parts = bearer.split(".")
        if len(parts) != 3:
            raise ValueError()
        payload = parts[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        audiences = {resource, resource + "/"}
        if resource == GRAPH:
            audiences.add("00000003-0000-0000-c000-000000000000")
        if (str(UUID(claims["tid"])) != tenant or claims.get("aud") not in audiences
                or not isinstance(claims.get("scp"), str) or not claims["scp"].strip()
                or claims.get("idtyp") == "app" or float(claims["exp"]) < time.time() + 60
                or float(claims.get("nbf", 0)) > time.time() + 60):
            raise ValueError()
        claims["oid"] = str(UUID(claims["oid"]))
        return claims
    except (ValueError, TypeError, KeyError):
        raise SalesUnavailable() from None


class DelegatedAuthorization:
    def __init__(self, tenant_id: str, token_provider, graph=None):
        self.tenant_id = str(UUID(tenant_id))
        self.provider = token_provider
        self.graph = graph or GraphTransport()

    def authorize(self) -> UserIdentity:
        try:
            tokens = {scope: self.provider.token(scope) for scope in (GRAPH, SEARCH, STORAGE)}
            claims = {scope: _claims(token, scope, self.tenant_id) for scope, token in tokens.items()}
            principal = self.graph.get(GRAPH + "/v1.0/me?$select=id", tokens[GRAPH])
            oid = str(UUID(principal["id"]))
            if any(claim["oid"] != oid for claim in claims.values()):
                raise SalesUnavailable()
            groups, seen = set(), set()
            url = GRAPH + GROUP_PATH + "?$select=id&$top=999&$count=true"
            for _ in range(1000):
                _graph_url(url)
                if url in seen or urlsplit(url).path != GROUP_PATH:
                    raise SalesUnavailable()
                seen.add(url)
                page = self.graph.get(url, tokens[GRAPH])
                values = page["value"]
                following = page.get("@odata.nextLink")
                if not isinstance(values, list) or (following and not values):
                    raise SalesUnavailable()
                groups.update(str(UUID(item["id"])) for item in values)
                if not following:
                    return UserIdentity(self.tenant_id, oid, frozenset(groups), tokens[SEARCH], tokens[STORAGE])
                url = following
            raise SalesUnavailable()
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, subprocess.SubprocessError):
            # Nothing about hidden partitions, tokens or Graph details crosses this boundary.
            raise SalesUnavailable() from None
