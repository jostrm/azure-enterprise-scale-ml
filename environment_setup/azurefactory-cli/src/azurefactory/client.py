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

from .errors import APIError, AuthError, ConfigError, FailureError, RedirectError, RequestTimeout
from . import catalog_requests
from .monitoring_saved import SavedMonitoringClient
from .operation_results import legacy_execution_result
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
class AzureFactoryClient(SavedMonitoringClient):
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

    def preflight(self, body: dict[str, Any]) -> dict[str, Any]:
        """Read readiness from the shared API; never prepare, authorize or provision."""
        from .preflight import preflight_request, validate_preflight_report

        request = preflight_request(body)
        try:
            report = self.request("POST", "/api/v1/creation/preflight", body=request)
        except APIError as exc:
            if exc.status in (404, 405):
                raise APIError(
                    "Preflight requires a newer API supporting POST /api/v1/creation/preflight; no fallback was attempted.",
                    status=exc.status,
                ) from None
            raise
        try:
            validate_preflight_report(report)
        except FailureError as exc:
            raise FailureError(exc.message, details=redact_secrets(report, self.api_key)) from None
        return report

    def openapi(self) -> dict[str, Any]:
        return self._object(self.request("GET", "/openapi.json", require_key=False), "openapi")

    def _factory_deletion_request(self, action: str, *, body=None, query=None) -> dict[str, Any]:
        endpoint = f"/api/v1/operations/delete-aifactory/{action}"
        try:
            return self._object(self.request("GET" if action == "status" else "POST",
                                            endpoint, body=body, query=query), "factory deletion")
        except APIError as exc:
            if exc.status in (404, 405):
                raise APIError(
                    "Factory deletion requires an API supporting the named delete-aifactory routes; "
                    "no catalog or legacy fallback was attempted.", status=exc.status,
                ) from None
            raise

    def delete_aifactory_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        """Prepare only; deletion requires a separate reviewed confirmation."""
        from .factory_deletion import validate_request

        validate_request(body)
        return self._factory_deletion_request("prepare", body=body)

    def delete_aifactory_confirm(self, *, folder: str, confirmation_id: str,
                                preview_hash: str, confirmation_phrase: str) -> dict[str, Any]:
        """Submit exactly one confirmation; never retry an uncertain result."""
        return self._factory_deletion_request("confirm", body={
            "contract_version": 1, "folder": folder, "confirmation_id": confirmation_id,
            "preview_hash": preview_hash, "confirmation_phrase": confirmation_phrase,
        })

    def delete_aifactory_status(self, folder: str, job_id: str) -> dict[str, Any]:
        return self._factory_deletion_request("status", query={"folder": folder, "job_id": job_id})

    def delete_aifactory_reconcile(self, folder: str, job_id: str) -> dict[str, Any]:
        """Server-side local completion from existing verified receipts; never redispatches pipelines."""
        return self._factory_deletion_request("reconcile", body={
            "contract_version": 1, "folder": folder, "job_id": job_id})

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

    def resource_group_costs(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read Azure billing for explicitly selected subscriptions; never allocate locally."""
        if (not isinstance(request, dict)
                or set(request) - {"subscription_ids", "month", "aifactory_folder", "refresh"}):
            raise ConfigError("Resource-group costs require an explicit subscription_ids scope.")
        subscriptions = request.get("subscription_ids")
        if not isinstance(subscriptions, list) or not subscriptions:
            raise ConfigError("Select at least one subscription_id; tenant-wide discovery is not supported.")
        identities = set()
        for value in subscriptions:
            try:
                identifier = UUID(value)
                if not identifier.int or str(identifier) != value.lower():
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ConfigError("Every selected subscription_id must be an Azure subscription UUID.") from None
            if identifier in identities:
                raise ConfigError("Select each subscription_id only once.")
            identities.add(identifier)
        if "month" in request:
            value = request["month"]
            try:
                parsed = date.fromisoformat(value + "-01")
            except (ValueError, TypeError):
                raise ConfigError("Cost month must be YYYY-MM.") from None
            if parsed.strftime("%Y-%m") != value:
                raise ConfigError("Cost month must be YYYY-MM.")
        if "refresh" in request and type(request["refresh"]) is not bool:
            raise ConfigError("Cost refresh must be a boolean.")
        if "aifactory_folder" in request and (
                not isinstance(request["aifactory_folder"], str) or not request["aifactory_folder"].strip()
                or _has_control(request["aifactory_folder"])):
            raise ConfigError("Cost catalog folder must be a nonempty API-host path.")
        return self._object(self.request(
            "POST", "/api/v1/monitoring/resource-group-costs", body=request,
        ), "resource-group cost report")

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

    def catalog_settings_prepare(
        self, folder: str, factory_id: str, settings: dict[str, Any], *,
        scale_set_id: str | None = None, project_id: str | None = None,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Review supplied setting replacements; omitted keys are unchanged.

        The API owns editable fields, scope validation and persistence. This does
        not deploy or delete resources. Obtain approval before catalog_confirm.
        """
        body = catalog_settings_request(
            folder, factory_id, settings, scale_set_id=scale_set_id,
            project_id=project_id, expected_revision=expected_revision,
        )
        preview = self.catalog_prepare(body)
        if preview.get("can_execute") is True:
            from .review import validate_settings_selection
            validate_settings_selection(body, preview)
        return preview

    def catalog_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        """Prepare once; the server owns defaults and project placement selection.

        Project placements may explicitly request scale_set_id='latest-successful'
        on supporting APIs. Review the resolved UUIDs before catalog_confirm.
        No client-side selection, confirmation, fallback or retry is performed.
        """
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

    def factory_clone_prepare(
        self, folder: str, factory_id: str, *, prefix: str | None = None, region: str | None = None,
        factory_key: str | None = None, scale_set_id: str | None = None, include_projects: str = "none",
        aifactory_version: str | None = None, expected_revision: str | None = None,
        region_short_name: str | None = None,
    ) -> dict[str, Any]:
        """Prepare a configuration clone, never a deployment."""
        return self._catalog_wrapper_prepare(catalog_requests.factory_clone_request(
            folder, factory_id, prefix=prefix, region=region, factory_key=factory_key,
            scale_set_id=scale_set_id, include_projects=include_projects, aifactory_version=aifactory_version,
            expected_revision=expected_revision, region_short_name=region_short_name), "factory-clone")

    def scaleset_add_prepare(
        self, folder: str, factory_id: str, scale_sets: list[dict[str, Any]], *,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Prepare explicit scale-set configuration; server validates network and scope."""
        return self._catalog_wrapper_prepare(catalog_requests.scaleset_add_request(
            folder, factory_id, scale_sets, expected_revision=expected_revision), "scaleset-add")

    def project_add_prepare(
        self, folder: str, factory_id: str, *, number: str, display_name: str = "",
        placements: list[dict[str, str]] | None = None, environments: list[str] | None = None,
        settings: dict[str, Any] | None = None, expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Prepare a project using explicit placements OR server-resolved environments."""
        return self._catalog_wrapper_prepare(catalog_requests.project_add_request(
            folder, factory_id, number=number, display_name=display_name, placements=placements,
            environments=environments, settings=settings, expected_revision=expected_revision), "project-add")

    def project_add_placements_prepare(
        self, folder: str, factory_id: str, project_id: str, *,
        placements: list[dict[str, str]] | None = None, environments: list[str] | None = None,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Prepare placements on the same saved project; never creates resources."""
        return self._catalog_wrapper_prepare(catalog_requests.project_add_placements_request(
            folder, factory_id, project_id, placements=placements, environments=environments,
            expected_revision=expected_revision), "project-add-placements")

    def project_delete_prepare(
        self, folder: str, factory_id: str, project_id: str, *, environments: list[str],
        include_project_subnets: bool, include_keyvault_and_resource_group: bool,
        expected_revision: str, scale_set_id: str | None = None, version_ref: str | None = None,
    ) -> dict[str, Any]:
        """Review guarded Azure project deletion; confirmation is separate approval."""
        return self._catalog_wrapper_prepare(catalog_requests.project_delete_request(
            folder, factory_id, project_id, environments=environments,
            include_project_subnets=include_project_subnets,
            include_keyvault_and_resource_group=include_keyvault_and_resource_group,
            expected_revision=expected_revision, scale_set_id=scale_set_id,
            version_ref=version_ref), "project-delete")

    def scaleset_delete_prepare(
        self, folder: str, factory_id: str, scale_set_id: str, *, expected_revision: str,
        version_ref: str | None = None,
    ) -> dict[str, Any]:
        """Review guarded Azure scale-set deletion; never confirms or retries."""
        return self._catalog_wrapper_prepare(catalog_requests.scaleset_delete_request(
            folder, factory_id, scale_set_id, expected_revision=expected_revision,
            version_ref=version_ref), "scaleset-delete")

    def draft_remove_prepare(
        self, folder: str, factory_id: str, *, kind: str, expected_revision: str,
        scale_set_id: str | None = None, project_id: str | None = None,
    ) -> dict[str, Any]:
        """Review local draft removal only; the API must prove safe draft lifecycle."""
        return self._catalog_wrapper_prepare(catalog_requests.draft_remove_request(
            folder, factory_id, kind=kind, expected_revision=expected_revision,
            scale_set_id=scale_set_id, project_id=project_id), "draft-remove-" + kind)

    def _catalog_wrapper_prepare(self, body: dict[str, Any], operation: str) -> dict[str, Any]:
        from .review import validate_bindings, validate_preview

        preview = self.catalog_prepare(body)
        if type(preview.get("can_execute")) is not bool:
            raise FailureError("Malformed preview: missing boolean can_execute.")
        if preview["can_execute"]:
            validate_preview(preview)
            validate_bindings(body, preview, "catalog-confirm", operation)
        return preview

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

    def creation_workflow_start(self, folder: str, workflow_id: str, confirmation_id: str,
                                *, authorization_hash: str | None = None) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/creation/workflows/start", body={
            "folder": folder, "workflow_id": self._workflow_id(workflow_id),
            "confirmation_id": confirmation_id,
            **({"authorization_hash": authorization_hash} if authorization_hash else {})}), "workflow start")

    def creation_workflow_continue(self, folder: str, workflow_id: str, authorization_hash: str) -> dict[str, Any]:
        identifier = self._workflow_id(workflow_id)
        return self._object(self.request("POST", f"/api/v1/creation/workflows/{identifier}/continue",
                                        body={"folder": folder, "authorization_hash": authorization_hash}),
                            "workflow continue")

    def creation_workflow_status(self, folder: str, workflow_id: str) -> dict[str, Any]:
        identifier = self._workflow_id(workflow_id)
        return self._object(self.request("GET", f"/api/v1/creation/workflows/{identifier}",
                                        query={"folder": folder}), "workflow status")

    def project_deployments(self, folder: str) -> dict[str, Any]:
        result = self._object(self.request("GET", "/api/v1/operations/project-deployments", query={"folder": folder}), "project deployments")
        if not isinstance(result.get("drafts"), list):
            raise FailureError("Malformed legacy execution draft list.")
        return {**result, "drafts": [self._legacy_object(item) for item in result["drafts"]]}

    def project_deployment_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._legacy_object(self.request("POST", "/api/v1/operations/project-deployments/plan", body=body))

    def project_deployment_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._object(self.request("POST", "/api/v1/operations/project-deployments/prepare", body=body), "project deployment prepare")

    def project_deployment_start(self, folder: str, confirmation_id: str) -> dict[str, Any]:
        """Submit once; the returned local job never proves provider deployment."""
        return self._legacy_object(self.request(
            "POST",
            "/api/v1/operations/project-deployments/start",
            body={"folder": folder, "confirmation_id": confirmation_id},
        ))

    def project_deployment_terminal(self, folder: str, job_id: str, cursor: int = 0) -> dict[str, Any]:
        return self._legacy_object(self.request(
            "GET",
            "/api/v1/operations/project-deployments/terminal",
            query={"folder": folder, "job_id": job_id, "cursor": cursor},
        ))

    def _legacy_object(self, value: Any) -> dict[str, Any]:
        result = legacy_execution_result(value)
        return {**value, "execution_result": result}

    def review_catalog_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        """Prepare only; caller must obtain explicit approval before confirm."""
        preview = self.catalog_prepare(body)
        from .review import validate_preview, validate_project_selection, validate_settings_selection, validate_removal_selection

        validate_preview(preview)
        validate_project_selection(body, preview)
        validate_settings_selection(body, preview)
        validate_removal_selection(body, preview)
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


def catalog_settings_request(
    folder: str, factory_id: str, settings: dict[str, Any], *,
    scale_set_id: str | None = None, project_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Build the existing scoped settings contract without copying server defaults."""
    if not isinstance(settings, dict):
        raise ConfigError("settings must be a JSON object.")
    return {key: value for key, value in {
        "folder": folder, "contract_version": 1, "action": "configure-settings",
        "factory_id": factory_id, "settings": settings, "scale_set_id": scale_set_id,
        "project_id": project_id, "expected_revision": expected_revision,
    }.items() if value is not None}


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
