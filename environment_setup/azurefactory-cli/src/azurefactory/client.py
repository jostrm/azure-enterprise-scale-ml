"""Stdlib-only SDK for the local AzureFactory API."""

from __future__ import annotations

import json
import math
import os
import socket
import ipaddress
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Generator
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from uuid import UUID
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .errors import APIError, AuthError, ConfigError, RedirectError, RequestTimeout
from .workflow_events import WorkflowRunEvent

DEFAULT_API_URL = "http://127.0.0.1:8765"
API_URL_ENV = "AIFACTORY_API_URL"
API_KEY_ENV = "AIFACTORY_API_KEY"
_OMITTED = object()

SAFE_UNAUTHENTICATED_PATHS = {"/health", "/openapi.json"}


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_json_hash(value: Any) -> str:
    import hashlib

    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def validate_base_url(url: str | None) -> str:
    raw = (url or DEFAULT_API_URL).strip()
    if not raw or _has_control(raw) or "\\" in raw:
        raise ConfigError("AIFACTORY_API_URL contains unsupported characters.")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("AIFACTORY_API_URL must be an http(s) URL.")
    if parsed.username or parsed.password:
        raise ConfigError("AIFACTORY_API_URL must not contain credentials.")
    if not parsed.hostname:
        raise ConfigError("AIFACTORY_API_URL must include a host.")
    try:
        if parsed.port is not None and not (0 < parsed.port < 65536):
            raise ConfigError("AIFACTORY_API_URL port is outside the valid range.")
    except ValueError as exc:
        raise ConfigError("AIFACTORY_API_URL port is invalid.") from exc
    if parsed.params or parsed.query or parsed.fragment:
        raise ConfigError("AIFACTORY_API_URL must not contain params, query or fragment.")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname or ""):
        raise ConfigError("Plain http API URLs are allowed only for loopback hosts.")
    decoded_path = unquote(parsed.path or "")
    if "\\" in decoded_path or _has_control(decoded_path) or _has_traversal(decoded_path):
        raise ConfigError("AIFACTORY_API_URL path is unsafe.")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def validate_endpoint(endpoint: str) -> str:
    if _has_control(endpoint) or "\\" in endpoint:
        raise ConfigError("Endpoint contains unsupported characters.")
    if not endpoint or endpoint.startswith(("http://", "https://", "//")):
        raise ConfigError("Endpoint must be a contained API path, not an absolute URL.")
    parsed = urlparse(endpoint)
    if parsed.scheme or parsed.netloc or parsed.params or parsed.fragment:
        raise ConfigError("Endpoint must be a relative API path without scheme, host, params or fragment.")
    path = parsed.path if parsed.path.startswith("/") else "/" + parsed.path
    decoded_path = unquote(path)
    if "\\" in decoded_path or _has_control(decoded_path) or _has_traversal(decoded_path):
        raise ConfigError("Endpoint must not contain parent-directory escapes.")
    return path + (("?" + parsed.query) if parsed.query else "")


def _has_control(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _has_traversal(path: str) -> bool:
    return any(part in {".", ".."} for part in path.split("/"))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None

    http_error_301 = HTTPRedirectHandler.http_error_302
    http_error_303 = HTTPRedirectHandler.http_error_302
    http_error_307 = HTTPRedirectHandler.http_error_302
    http_error_308 = HTTPRedirectHandler.http_error_302


@dataclass(frozen=True)
class AzureFactoryClient:
    """Small SDK returning JSON objects, with CSV for canonical monitoring export."""

    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    timeout: float = 30.0

    def __post_init__(self):
        if not isinstance(self.timeout, (int, float)) or not math.isfinite(float(self.timeout)) or self.timeout <= 0:
            raise ConfigError("Request timeout must be a finite positive number.")
        object.__setattr__(self, "base_url", validate_base_url(self.base_url or os.getenv(API_URL_ENV)))
        object.__setattr__(self, "api_key", self.api_key if self.api_key is not None else os.getenv(API_KEY_ENV))

    @property
    def canonical_base_url(self) -> str:
        return str(self.base_url)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        body: Any | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        require_key: bool | None = None,
    ) -> Any:
        method = method.upper()
        safe_endpoint = validate_endpoint(endpoint)
        path, _, existing_query = safe_endpoint.partition("?")
        query_pairs = parse_qsl(existing_query, keep_blank_values=True)
        if query:
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    query_pairs.extend((key, str(item)) for item in value)
                else:
                    query_pairs.append((key, str(value)))
        final_endpoint = path + (("?" + urlencode(query_pairs)) if query_pairs else "")
        needs_key = require_key if require_key is not None else path not in SAFE_UNAUTHENTICATED_PATHS
        if needs_key and not self.api_key:
            raise AuthError(f"{API_KEY_ENV} is required for {path}.")
        data = None
        request_headers = {"Accept": "text/csv" if path == "/api/v1/monitoring/export" and method == "POST" else "application/json"}
        if self.api_key and needs_key:
            request_headers["X-API-Key"] = self.api_key
        if body is not None:
            data = _json_dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        req = Request(str(self.base_url) + final_endpoint, data=data, method=method, headers=request_headers)
        opener = build_opener(ProxyHandler({}), _NoRedirect)
        try:
            with opener.open(req, timeout=float(self.timeout)) as response:
                payload = response.read()
                if path == "/api/v1/monitoring/export" and method == "POST":
                    if response.headers.get_content_type() != "text/csv":
                        raise APIError("Monitoring export did not return text/csv.")
                    try:
                        return payload.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        raise APIError("Monitoring export did not return UTF-8 CSV.") from None
                return _decode_response(payload, response.headers.get_content_type(), method)
        except HTTPError as exc:
            payload = exc.read()
            details = redact_secrets(_decode_error(payload), self.api_key)
            if 300 <= exc.code < 400:
                raise RedirectError("Refusing to follow API redirect.", status=exc.code, details=details) from None
            raise APIError(redact_text(_error_message(payload, exc), self.api_key), status=exc.code, details=details) from None
        except TimeoutError as exc:
            raise RequestTimeout("API request timed out.") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise RequestTimeout("API request timed out.") from exc
            raise APIError(redact_text(f"API request failed: {exc.reason}", self.api_key)) from exc

    def health(self) -> dict[str, Any]:
        return self._object(self.request("GET", "/health", require_key=False), "health")

    def openapi(self) -> dict[str, Any]:
        return self._object(self.request("GET", "/openapi.json", require_key=False), "openapi")

    def schema(self) -> dict[str, Any]:
        return self._object(self.request("GET", "/api/v1/schema"), "schema")

    def get_workflow_run_status(self, repository: str, run_id: int) -> WorkflowRunEvent:
        """Read one scoped workflow event; never dispatch or rerun a workflow."""
        from .workflow_events import get_status

        return get_status(self, repository, run_id)

    def watch_workflow_run(
        self, repository: str, run_id: int, after: str | None = None, follow: bool = True,
        *, timeout: float = 300.0, max_retries: int = 3,
        backoff_initial: float = 0.5, backoff_max: float = 8.0,
    ) -> Generator[WorkflowRunEvent, None, WorkflowRunEvent | None]:
        """Yield SSE events until completion or the bounded observation deadline.

        Close the generator when cancelling. Retries reconnect the read-only feed,
        not the workflow. Completion requires stream EOF and current-status confirmation.
        """
        from .workflow_events import watch

        return watch(self, repository, run_id, after, follow, timeout=timeout,
                     max_retries=max_retries, backoff_initial=backoff_initial, backoff_max=backoff_max)

    def subscribe_workflow_run(
        self, repository: str, run_id: int, callback: Callable[[WorkflowRunEvent], bool | None], **options,
    ) -> None:
        """Call a synchronous observer; returning False cancels and closes the feed."""
        events = self.watch_workflow_run(repository, run_id, **options)
        try:
            for event in events:
                if callback(event) is False:
                    break
        finally:
            events.close()

    def monitoring_catalog(self) -> dict[str, Any]:
        """Read canonical report/source capabilities; never start a collector."""
        return self._object(self.request("GET", "/api/v1/monitoring/catalog"), "monitoring catalog")

    def monitoring_report(self, request: dict[str, Any]) -> dict[str, Any]:
        """Calculate a report from explicit sample or supplied observation evidence."""
        return self._object(self.request(
            "POST", "/api/v1/monitoring/report", body=self._monitoring_request(request),
        ), "monitoring report")

    def monitoring_summary(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read the combined overview using the same canonical report calculations."""
        return self._object(self.request(
            "POST", "/api/v1/monitoring/summary",
            body=self._monitoring_request(request, require_report=False),
        ), "monitoring summary")

    def monitoring_export(self, request: dict[str, Any]) -> str:
        """Return canonical filtered CSV; no file, job or cloud upload."""
        result = self.request(
            "POST", "/api/v1/monitoring/export", body=self._monitoring_request(request),
        )
        if not isinstance(result, str):
            raise ConfigError("Monitoring export did not return the canonical CSV response.")
        return result

    @staticmethod
    def _monitoring_request(
        request: dict[str, Any], *, require_report: bool = True,
    ) -> dict[str, Any]:
        if (not isinstance(request, dict) or not isinstance(request.get("source"), str)
                or request["source"] not in {"sample", "live"}):
            raise ConfigError("Monitoring requires an explicit sample/live source.")
        if require_report and (not isinstance(request.get("report_id"), str) or request["report_id"] not in {
            "agent-value", "showback", "foundry-tokens", "foundry-usage",
            "quality-reliability", "security-governance",
        }):
            raise ConfigError("Select a canonical monitoring report ID from monitoring catalog.")
        if not require_report and "report_id" in request:
            raise ConfigError("Monitoring summary includes all six reports; omit report_id.")
        start, end = request.get("start_date"), request.get("end_date")
        if start is not None or end is not None:
            try:
                first, last = date.fromisoformat(start), date.fromisoformat(end)
            except (TypeError, ValueError):
                raise ConfigError("Specify both start_date and end_date as YYYY-MM-DD UTC dates.") from None
            if first.isoformat() != start or last.isoformat() != end:
                raise ConfigError("Specify both start_date and end_date as YYYY-MM-DD UTC dates.")
            if not 0 <= (last - first).days < 90:
                raise ConfigError("Monitoring date window must contain 1 to 90 inclusive UTC days.")
        return request

    def configuration_load(self, folder: str, project_number: str) -> dict[str, Any]:
        return self._object(self.request(
            "POST", "/api/v1/projects/load",
            body={"aifactory_folder": folder, "project_number": project_number},
        ), "configuration load")

    def configuration_import(self, path: str, format: str = "json") -> dict[str, Any]:
        """Import a persistent file on the API host, not inline uploaded JSON."""
        return self._object(self.request(
            "POST", "/api/v1/import", body={"format": format, "path": path},
        ), "configuration import")

    def configuration_validate(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request(
            "POST", "/api/v1/validation", body={"state": state},
        ), "configuration validation")

    def configuration_export(
        self, state: dict[str, Any], format: str = "json", path: str | None = None,
    ) -> dict[str, Any]:
        """Render without writing unless an explicit API-host destination is supplied."""
        body: dict[str, Any] = {"state": state, "format": format}
        if path is not None:
            body["path"] = path
        return self._object(self.request("POST", "/api/v1/export", body=body), "configuration export")

    def configuration_save(self, state: dict[str, Any], *, write_variables: bool = True) -> dict[str, Any]:
        """Write local configuration only; the caller must obtain approval first."""
        return self._object(self.request(
            "POST", "/api/v1/projects/save", body={"state": state, "write_variables": write_variables},
        ), "configuration save")

    def auth_status(self, **body) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/azure/auth/status", body={k: v for k, v in body.items() if v is not None}), "auth status")

    def catalog_list(self, folder: str) -> dict[str, Any]:
        return self._object(self.request("GET", "/api/v1/factory-catalog", query={"folder": folder}), "catalog list")

    def catalog_settings(self, folder: str, factory_id: str, scale_set_id: str | None = None, project_id: str | None = None):
        return self._object(self.request(
            "GET",
            "/api/v1/factory-catalog/settings",
            query={"folder": folder, "factory_id": factory_id, "scale_set_id": scale_set_id, "project_id": project_id},
        ), "catalog settings")

    def catalog_parameters(
        self, folder: str, factory_id: str, scale_set_id: str, project_id: str | None = None, version_ref: str | None = None
    ):
        return self._object(self.request(
            "GET",
            "/api/v1/factory-catalog/parameters",
            query={
                "folder": folder,
                "factory_id": factory_id,
                "scale_set_id": scale_set_id,
                "project_id": project_id,
                "version_ref": version_ref,
            },
        ), "catalog parameters")

    def catalog_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("action") == "create-factory":
            schema = self.openapi()
            issues = registered_creation_issues(schema)
            if ("target_region_short_name" in body and "target_region_short_name" not in
                    schema.get("components", {}).get("schemas", {}).get("CatalogPrepare", {}).get("properties", {})):
                issues.append("CatalogPrepare.target_region_short_name is missing; the requested region short name is unsupported.")
            if issues:
                raise ConfigError("Update/start the supported registered-creation API before creating a factory: " + "; ".join(issues))
        return self._object(self.request("POST", "/api/v1/factory-catalog/prepare", body=body), "catalog prepare")

    def factory_create_prepare(
        self, folder: str, *, prefix: str, region: str, scale_sets: list[dict[str, Any]],
        factory_key: str | None = None, kind: str = "ai", aifactory_version: str | None = None,
        initial_project: Any = _OMITTED, settings: dict[str, Any] | None = None,
        expected_revision: str | None = None, region_short_name: str | None = None,
    ) -> dict[str, Any]:
        """Prepare configuration only; backend owns initial-project/version defaults.

        Omit initial_project for the canonical AI initial project; None explicitly
        requests common-only. An explicit project is sent once, not followed by a
        second add-project request. Review before separately calling catalog_confirm.
        """
        body = factory_create_request(
            folder, prefix=prefix, region=region, scale_sets=scale_sets, factory_key=factory_key,
            kind=kind, aifactory_version=aifactory_version, initial_project=initial_project,
            settings=settings, expected_revision=expected_revision, region_short_name=region_short_name,
        )
        return self.catalog_prepare(body)

    def catalog_confirm(self, folder: str, confirmation_id: str) -> dict[str, Any]:
        return self._object(self.request(
            "POST",
            "/api/v1/factory-catalog/confirm",
            body={"folder": folder, "contract_version": 1, "confirmation_id": confirmation_id},
        ), "catalog confirm")

    def parameter_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/factory-catalog/parameters/prepare", body=body), "parameters prepare")

    def parameter_confirm(self, folder: str, confirmation_id: str) -> dict[str, Any]:
        return self._object(self.request(
            "POST",
            "/api/v1/factory-catalog/parameters/confirm",
            body={"folder": folder, "contract_version": 1, "confirmation_id": confirmation_id},
        ), "parameters confirm")

    def catalog_jobs(self, folder: str) -> dict[str, Any]:
        return self._object(self.request("GET", "/api/v1/factory-catalog/jobs", query={"folder": folder}), "catalog jobs")

    def catalog_job(self, folder: str, job_id: str) -> dict[str, Any]:
        return self._object(self.request("GET", f"/api/v1/factory-catalog/jobs/{job_id}", query={"folder": folder}), "catalog job")

    def catalog_terminal(self, folder: str, job_id: str, cursor: int = 0) -> dict[str, Any]:
        return self._object(self.request("GET", "/api/v1/factory-catalog/terminal", query={"folder": folder, "job_id": job_id, "cursor": cursor}), "catalog terminal")

    def creation_capabilities(self) -> dict[str, Any]:
        return self._object(self.request("GET", "/api/v1/creation/capabilities"), "creation capabilities")

    def bootstrap_config(self, state: dict[str, Any], *, mapping_mode: str = "strict") -> dict[str, Any]:
        if mapping_mode not in ("strict", "common-details"):
            raise ConfigError("Choose strict or common-details mapping.")
        body = {"state": state}
        if mapping_mode != "strict":
            body["mapping_mode"] = mapping_mode
        return self._object(self.request("POST", "/api/v1/creation/bootstrap/config", body=body), "bootstrap config")

    def bootstrap_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/creation/bootstrap/prepare", body=body), "bootstrap prepare")

    def bootstrap_start(self, confirmation_id: str) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/creation/bootstrap/start", body={"confirmation_id": confirmation_id}), "bootstrap start")

    def bootstrap_job(self, job_id: str) -> dict[str, Any]:
        return self._object(self.request("GET", f"/api/v1/creation/bootstrap/jobs/{job_id}"), "bootstrap job")

    def creation_workflow_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/creation/workflows/prepare", body=body), "workflow prepare")

    @staticmethod
    def _workflow_id(value: str) -> str:
        try:
            identifier = UUID(value)
            if not identifier.int or str(identifier) != value:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ConfigError("Use the exact canonical workflow UUID returned by the server.") from None
        return value

    def creation_workflow_next(self, folder: str, workflow_id: str) -> dict[str, Any]:
        identifier = self._workflow_id(workflow_id)
        return self._object(self.request(
            "POST", f"/api/v1/creation/workflows/{identifier}/prepare-next",
            body={"folder": folder}), "workflow next")

    def creation_workflow_start(self, folder: str, workflow_id: str, confirmation_id: str) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/creation/workflows/start", body={
            "folder": folder, "workflow_id": self._workflow_id(workflow_id),
            "confirmation_id": confirmation_id}), "workflow start")

    def creation_workflow_status(self, folder: str, workflow_id: str) -> dict[str, Any]:
        identifier = self._workflow_id(workflow_id)
        return self._object(self.request("GET", f"/api/v1/creation/workflows/{identifier}",
                                        query={"folder": folder}), "workflow status")

    def project_deployments(self, folder: str) -> dict[str, Any]:
        return self._object(self.request("GET", "/api/v1/operations/project-deployments", query={"folder": folder}), "project deployments")

    def project_deployment_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/operations/project-deployments/plan", body=body), "project deployment plan")

    def project_deployment_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/operations/project-deployments/prepare", body=body), "project deployment prepare")

    def project_deployment_start(self, folder: str, confirmation_id: str) -> dict[str, Any]:
        return self._object(self.request(
            "POST",
            "/api/v1/operations/project-deployments/start",
            body={"folder": folder, "confirmation_id": confirmation_id},
        ), "project deployment start")

    def project_deployment_terminal(self, folder: str, job_id: str, cursor: int = 0) -> dict[str, Any]:
        return self._object(self.request(
            "GET",
            "/api/v1/operations/project-deployments/terminal",
            query={"folder": folder, "job_id": job_id, "cursor": cursor},
        ), "project deployment terminal")

    def review_catalog_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        """Prepare only; caller must obtain explicit approval before confirm."""
        preview = self.catalog_prepare(body)
        from .review import validate_preview

        validate_preview(preview)
        return preview

    def _object(self, value: Any, context: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise APIError(f"Malformed {context} response: expected JSON object.")
        return value


def registered_creation_issues(openapi: dict[str, Any]) -> list[str]:
    properties = openapi.get("components", {}).get("schemas", {}).get("CatalogPrepare", {}).get("properties", {})
    if "initial_project" not in properties:
        return ["CatalogPrepare.initial_project is missing; this server cannot guarantee the initial-project contract."]
    return []


def factory_create_request(
    folder: str, *, prefix: str, region: str, scale_sets: list[dict[str, Any]],
    factory_key: str | None = None, kind: str = "ai", aifactory_version: str | None = None,
    initial_project: Any = _OMITTED, settings: dict[str, Any] | None = None,
    expected_revision: str | None = None, region_short_name: str | None = None,
) -> dict[str, Any]:
    """Build the shared CatalogPrepare request without inventing catalog data."""
    body = {key: value for key, value in {
        "folder": folder, "contract_version": 1, "action": "create-factory",
        "factory_key": factory_key, "factory_kind": kind,
        "target_prefix": prefix, "target_region": region,
        "target_region_short_name": region_short_name,
        "scale_sets": scale_sets, "aifactory_version": aifactory_version,
        "settings": settings, "expected_revision": expected_revision,
    }.items() if value is not None}
    if initial_project is not _OMITTED:
        if initial_project is not None and not isinstance(initial_project, dict):
            raise ConfigError("initial_project must be an object or null (common-only).")
        body["initial_project"] = initial_project
    return body


def _decode_response(payload: bytes, content_type: str, method: str) -> Any:
    if not payload:
        if method == "HEAD":
            return None
        raise APIError("API returned an empty response instead of JSON.")
    text = payload.decode("utf-8", errors="replace")
    if content_type != "application/json":
        raise APIError("API returned a non-JSON response.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise APIError("API returned malformed JSON.") from exc


def _decode_error(payload: bytes):
    if not payload:
        return None
    try:
        decoded = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return payload.decode("utf-8", errors="replace")
    if isinstance(decoded, dict) and isinstance(decoded.get("detail"), list):
        # Pydantic input/context can echo whole drafts, including serialized secrets.
        decoded["detail"] = [
            {key: value for key, value in issue.items() if key not in {"input", "ctx"}}
            if isinstance(issue, dict) else issue
            for issue in decoded["detail"]
        ]
    return decoded


def _error_message(payload: bytes, exc: HTTPError) -> str:
    decoded = _decode_error(payload)
    if isinstance(decoded, dict):
        detail = decoded.get("detail") or decoded.get("message") or decoded.get("error")
        if detail:
            if isinstance(detail, list):
                messages = [item["msg"] for item in detail if isinstance(item, dict) and isinstance(item.get("msg"), str)]
                return "; ".join(messages) or f"API returned HTTP {exc.code}."
            return str(detail)
    return f"API returned HTTP {exc.code}."


def redact_text(value: str, secret: str | None) -> str:
    if secret:
        value = value.replace(secret, "<redacted>")
    return value


def redact_secrets(value: Any, secret: str | None) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key == "_json_source" or any(marker in str(key).lower() for marker in ("api_key", "apikey", "secret", "token", "password", "credential")):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_secrets(item, secret)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item, secret) for item in value]
    if isinstance(value, str):
        return redact_text(value, secret)
    return value
