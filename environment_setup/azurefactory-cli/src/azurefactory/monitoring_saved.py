"""Read saved evidence and project it through the shared API, never collect or save."""

from __future__ import annotations

import sys
from typing import Any
from uuid import UUID

from .errors import APIError, ConfigError

READ_ENDPOINT = "/api/v1/monitoring/evidence/read"
CONTRACT = "aifactory.monitoring-evidence.v1"
SELECTORS = ("factory_id", "scale_set_id", "project_id")
DATES = ("start_date", "end_date")
REPORTS = ("agent-value", "showback", "foundry-tokens", "foundry-usage",
           "quality-reliability", "security-governance")


def _read_request(client, context):
    if not isinstance(context, dict) or set(context) - {"folder", *SELECTORS, *DATES}:
        raise ConfigError("Saved monitoring accepts only folder, registered scope IDs and date bounds.")
    folder = context.get("folder")
    if not isinstance(folder, str) or not folder.strip() or len(folder) > 1024:
        raise ConfigError("Saved monitoring requires a folder on the API host (1-1024 characters).")
    for key in SELECTORS:
        value = context.get(key)
        if value is None:
            continue
        try:
            valid = isinstance(value, str) and UUID(value).int != 0 and str(UUID(value)) == value
        except ValueError:
            valid = False
        if not valid:
            raise ConfigError(f"{key} must be a canonical nonzero registered UUID, not a display label.")
    client._monitoring_request(
        {"source": "live", **{key: context[key] for key in DATES if key in context}},
        require_report=False,
    )
    return context


def _evidence_response(result):
    if (not isinstance(result, dict) or result.get("contract") != CONTRACT
            or not isinstance(result.get("status"), str)
            or result["status"] not in {"available", "absent", "incompatible", "unavailable"}
            or not isinstance(result.get("window"), dict)
            or not isinstance(result.get("warnings"), list)
            or any(not isinstance(item, str) for item in result["warnings"])
            or any(not isinstance(result.get(key), list)
                   or any(not isinstance(item, dict) for item in result[key])
                   for key in ("rows", "scopes", "snapshots", "native_bindings", "source_errors"))):
        raise APIError("Unsupported saved monitoring response contract; use a matching API release. "
                       "No fallback was attempted.", details=result)
    return result


class SavedMonitoringClient:
    """SDK methods using the host's authenticated evidence scope and canonical reducers."""

    def monitoring_evidence_read(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return the unchanged saved evidence envelope, including nonavailable states."""
        body = _read_request(self, context)
        try:
            result = self.request("POST", READ_ENDPOINT, body=body)
        except APIError as exc:
            if exc.status in (404, 405):
                raise APIError(
                    "Saved monitoring requires a matching API release supporting "
                    f"POST {READ_ENDPOINT} and a registered scope. "
                    f"No fallback was attempted. {exc.message}",
                    status=exc.status, details=exc.details,
                ) from exc
            raise
        return _evidence_response(result)

    def monitoring_saved_summary(self, context: dict[str, Any]) -> dict[str, Any]:
        """Read saved sources, then reduce available evidence without losing diagnostics."""
        return self._monitoring_saved_projection(context, "summary")

    def monitoring_saved_report(self, context: dict[str, Any], *, report_id: str) -> dict[str, Any]:
        """Read saved sources, then calculate one canonical report; never execute a job."""
        self._monitoring_request({"source": "live", "report_id": report_id})
        return self._monitoring_saved_projection(context, "report", report_id=report_id)

    def _monitoring_saved_projection(self, context, action, *, report_id=None):
        evidence = self.monitoring_evidence_read(context)
        result = {"status": evidence["status"], "evidence": evidence, action: None}
        if evidence["status"] != "available":
            return result
        body = {"source": "live", "rows": evidence["rows"], "native_bindings": evidence["native_bindings"],
                **{key: context[key] for key in DATES if key in context}}
        if report_id is not None:
            body["report_id"] = report_id
        try:
            result[action] = getattr(self, "monitoring_" + action)(body)
        except APIError as exc:
            exc.details = {"evidence": evidence, "projection_error": exc.details}
            raise
        return result


def register_saved_commands(subparsers):
    saved = subparsers.add_parser("saved", help="Read saved evidence only; no collection, imports or report jobs.")
    actions = saved.add_subparsers(dest="saved_action", required=True)
    for action in ("read", "summary", "report"):
        command = actions.add_parser(action)
        command.set_defaults(func=cmd_monitoring_saved)
        command.add_argument("--folder", required=True, help="Registered factory folder on the API host.")
        for key in SELECTORS:
            command.add_argument("--" + key.replace("_", "-"), help="Exact registered UUID; omitted selects all authorized scopes.")
        command.add_argument("--start-date", help="Inclusive UTC date (YYYY-MM-DD); requires --end-date.")
        command.add_argument("--end-date", help="Inclusive UTC date (YYYY-MM-DD); at most 90 days with --start-date.")
        if action == "report":
            command.add_argument("--report", choices=REPORTS, required=True)


def cmd_monitoring_saved(args):
    from .cli import EXIT_FAILURE, EXIT_OK, client, emit, redact_secrets

    api = client(args)
    context = {key: getattr(args, key) for key in ("folder", *SELECTORS, *DATES)
               if getattr(args, key) is not None}
    if args.saved_action == "read":
        result = api.monitoring_evidence_read(context)
        evidence = result
    else:
        if args.saved_action == "summary":
            result = api.monitoring_saved_summary(context)
        else:
            result = api.monitoring_saved_report(context, report_id=args.report)
        evidence = result["evidence"]
    messages = list(evidence["warnings"])
    messages.extend(error["message"] for error in evidence["source_errors"]
                    if isinstance(error.get("message"), str))
    if evidence["status"] != "available":
        messages.append(f"Saved monitoring is {evidence['status']}; no projection or fallback was attempted.")
    for message in dict.fromkeys(messages):
        print("Warning: " + redact_secrets(message, api.api_key), file=sys.stderr)
    code = EXIT_FAILURE if evidence["status"] in {"unavailable", "incompatible"} else EXIT_OK
    return emit(redact_secrets(result, api.api_key), code)
