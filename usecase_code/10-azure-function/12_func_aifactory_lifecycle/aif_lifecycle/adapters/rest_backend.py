"""Option 1: the Factory API over plain REST (urllib, no SDK).

Same transport rules as the SDK: plain http only to loopback, no proxy, no redirects, the key in X-API-Key, and no
retries - a confirm is submitted exactly once.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..domain.errors import UpstreamTimeout, UpstreamUnavailable, ValidationFailed
from .api_errors import error_for_status
from .factory_api import FactoryApiBackend

UNAUTHENTICATED = {"/health", "/openapi.json"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _dumps(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class RestTransport:
    def __init__(self, base_url: str, api_key: str | None, timeout: float = 30.0):
        parsed = urlparse(base_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.query:
            raise ValidationFailed("AIF_FACTORY_API_URL must be an http(s) URL without credentials or query.")
        if parsed.scheme == "http" and not is_loopback(parsed.hostname):
            raise ValidationFailed("Plain http to the Factory API is allowed only for loopback hosts.")
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout

    def call(self, method: str, path: str, *, query: dict[str, Any] | None = None, body: Any = None) -> Any:
        pairs = [(key, str(value)) for key, value in (query or {}).items() if value is not None]
        url = self._base + path + ("?" + urlencode(pairs) if pairs else "")
        headers = {"Accept": "application/json"}
        if path not in UNAUTHENTICATED:
            if not self._key:
                raise ValidationFailed("AIF_FACTORY_API_KEY is required for the Factory API.")
            headers["X-API-Key"] = self._key
        data = None
        if body is not None:
            data = _dumps(body)
            headers["Content-Type"] = "application/json"
        opener = build_opener(ProxyHandler({}), _NoRedirect)
        try:
            with opener.open(Request(url, data=data, method=method, headers=headers), timeout=self._timeout) as response:
                payload = response.read()
        except HTTPError as error:
            raise error_for_status(error.code, _detail(error.read(), self._key)) from None
        except (TimeoutError, socket.timeout):
            raise UpstreamTimeout("The Factory API did not answer in time.") from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise UpstreamTimeout("The Factory API did not answer in time.") from None
            raise UpstreamUnavailable("The Factory API could not be reached.") from None
        return json.loads(payload) if payload else {}


def _detail(payload: bytes, secret: str | None) -> str:
    try:
        decoded = json.loads(payload)
        text = decoded.get("detail") if isinstance(decoded, dict) else None
        text = text if isinstance(text, str) else json.dumps(text)[:500] if text is not None else ""
    except ValueError:
        text = payload.decode("utf-8", "replace")[:500]
    return text.replace(secret, "***") if secret else text


class RestFactoryBackend(FactoryApiBackend):
    name = "rest"

    def __init__(self, transport: RestTransport, folder: str):
        super().__init__(folder)
        self._http = transport

    def _prepare(self, body):
        return self._http.call("POST", "/api/v1/factory-catalog/prepare", body=body)

    @staticmethod
    def _request(folder, factory_id, action, expected_revision=None, **values):
        return {key: value for key, value in {"folder": folder, "contract_version": 1, "action": action,
                                              "factory_id": factory_id, "expected_revision": expected_revision,
                                              **values}.items() if value is not None}

    def _catalog_list(self):
        return self._http.call("GET", "/api/v1/factory-catalog", query={"folder": self.folder})

    def _creation_prepare(self, body):
        return self._http.call("POST", "/api/v1/creation/prepare", body=body)

    def _creation_confirm(self, folder, confirmation_id):
        return self._http.call("POST", "/api/v1/creation/confirm", body={
            "contract_version": 1, "folder": folder, "confirmation_id": confirmation_id})

    def _add_scaleset(self, factory_id, scale_sets, expected_revision):
        return self._prepare(self._request(self.folder, factory_id, "create-scale-set", expected_revision,
                                           scale_sets=scale_sets))

    def _add_project(self, factory_id, number, display_name, placements, settings, expected_revision):
        return self._prepare(self._request(self.folder, factory_id, "add-project", expected_revision, settings=settings,
                                           project={"number": number, "display_name": display_name,
                                                    "placements": placements}))

    def _configure_settings(self, factory_id, settings, scale_set_id, project_id, expected_revision):
        return self._prepare(self._request(self.folder, factory_id, "configure-settings", expected_revision,
                                           settings=settings, scale_set_id=scale_set_id, project_id=project_id))

    def _deploy(self, body):
        return self._prepare(body)

    def _delete_project(self, factory_id, project_id, environments, include_project_subnets,
                        include_keyvault_and_resource_group, expected_revision, scale_set_id):
        return self._prepare(self._request(
            self.folder, factory_id, "delete-project", expected_revision, project_id=project_id,
            scale_set_id=scale_set_id, deletion_options={
                "environments": environments, "include_project_subnets": include_project_subnets,
                "include_keyvault_and_resource_group": include_keyvault_and_resource_group}))

    def _delete_scaleset(self, factory_id, scale_set_id, expected_revision):
        return self._prepare(self._request(self.folder, factory_id, "delete-scale-set", expected_revision,
                                           scale_set_id=scale_set_id))

    def _delete_factory_prepare(self, body):
        return self._http.call("POST", "/api/v1/operations/delete-aifactory/prepare", body=body)

    def _catalog_confirm(self, confirmation_id):
        return self._http.call("POST", "/api/v1/factory-catalog/confirm", body={
            "folder": self.folder, "contract_version": 1, "confirmation_id": confirmation_id})

    def _delete_factory_confirm(self, confirmation_id, preview_hash, phrase):
        return self._http.call("POST", "/api/v1/operations/delete-aifactory/confirm", body={
            "contract_version": 1, "folder": self.folder, "confirmation_id": confirmation_id,
            "preview_hash": preview_hash, "confirmation_phrase": phrase})

    def _workflow_prepare(self, body):
        return self._http.call("POST", "/api/v1/creation/workflows/prepare", body=body)

    def _workflow_start(self, workflow_id, confirmation_id, authorization_hash):
        body = {"folder": self.folder, "workflow_id": workflow_id, "confirmation_id": confirmation_id}
        if authorization_hash:
            body["authorization_hash"] = authorization_hash
        return self._http.call("POST", "/api/v1/creation/workflows/start", body=body)

    def _workflow_status(self, workflow_id):
        return self._http.call("GET", f"/api/v1/creation/workflows/{workflow_id}", query={"folder": self.folder})

    def _job(self, job_id):
        return self._http.call("GET", f"/api/v1/factory-catalog/jobs/{job_id}", query={"folder": self.folder})
