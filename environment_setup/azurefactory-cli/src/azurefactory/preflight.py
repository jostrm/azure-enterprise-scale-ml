"""Transport contract for read-only deployment preflight, not approval receipts."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .errors import ConfigError, FailureError

REQUEST_FIELDS = {
    "contract_version", "orchestrator", "bootstrap_config", "settings", "scope",
    "expected_revision", "operation", "execution_mode", "creation_mode", "mode",
    "approval_mode", "approval_scope", "authorization_valid_for_seconds", "bootstrap_public_ipv4",
}
SCOPE_FIELDS = {"folder", "factory_id", "scale_set_id", "project_id"}
REPORT_FIELDS = {
    "contract_version", "kind", "read_only", "authorization", "status", "ready",
    "generated_at", "input_hash", "source", "target", "checks", "cost_preview",
    "limitations",
}
CHECK_FIELDS = {"id", "category", "status", "blocking", "message", "evidence", "remediation"}


def preflight_request(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) - REQUEST_FIELDS:
        raise ConfigError("Preflight request must be an object with only supported contract fields.")
    if type(body.get("contract_version")) is not int or body["contract_version"] != 1:
        raise ConfigError("Preflight request requires contract_version 1.")
    if not isinstance(body.get("bootstrap_config"), dict):
        raise ConfigError("Preflight request requires a bootstrap_config object.")
    if body.get("orchestrator", "gha") not in ("gha", "ado"):
        raise ConfigError("Preflight orchestrator must be gha or ado.")
    if "settings" in body and not isinstance(body["settings"], dict):
        raise ConfigError("Preflight settings must be an object.")
    scope = body.get("scope")
    if scope is not None:
        if not isinstance(scope, dict) or set(scope) - SCOPE_FIELDS:
            raise ConfigError("Preflight scope must contain only folder/factory_id/scale_set_id/project_id.")
        if any(value is not None and (not isinstance(value, str) or not value.strip())
               for value in scope.values()):
            raise ConfigError("Preflight scope values must be nonempty strings or null.")
    for field in ("expected_revision", "operation", "execution_mode", "creation_mode",
                  "mode", "approval_mode", "approval_scope", "bootstrap_public_ipv4"):
        if field in body and body[field] is not None and not isinstance(body[field], str):
            raise ConfigError(f"Preflight {field} must be a string or null.")
    duration = body.get("authorization_valid_for_seconds")
    if duration is not None and type(duration) is not int:
        raise ConfigError("Preflight authorization_valid_for_seconds must be an integer or null.")
    try:
        json.dumps(body, allow_nan=False)
    except (TypeError, ValueError):
        raise ConfigError("Preflight request must contain only finite JSON values.") from None
    return {"orchestrator": "gha", **body}


def validate_preflight_report(report: Any) -> None:
    def invalid(reason):
        raise FailureError(f"Malformed or incompatible preflight response: {reason}.")

    if not isinstance(report, dict) or not REPORT_FIELDS <= report.keys():
        invalid("missing required report fields")
    if (type(report["contract_version"]) is not int or report["contract_version"] != 1
            or report["kind"] != "deployment-preflight"
            or report["read_only"] is not True or report["authorization"] is not False):
        invalid("expected read-only deployment-preflight contract 1, without authorization")
    if report["status"] not in ("ready", "blocked", "incomplete") or type(report["ready"]) is not bool:
        invalid("unknown readiness status or non-boolean ready")
    if report["ready"] != (report["status"] == "ready"):
        invalid("status and ready disagree")
    if not isinstance(report["input_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", report["input_hash"]):
        invalid("input_hash must be a lowercase 64-character hexadecimal fingerprint")
    try:
        timestamp = datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        invalid("generated_at must be an ISO timestamp with timezone")
    if not isinstance(report["source"], dict) or not isinstance(report["target"], dict):
        invalid("source and target must be objects")
    if report["cost_preview"] is not None and not isinstance(report["cost_preview"], dict):
        invalid("cost_preview must be an object or null")
    if not isinstance(report["limitations"], list) or any(not isinstance(item, str) for item in report["limitations"]):
        invalid("limitations must be an array of strings")
    if not isinstance(report["checks"], list):
        invalid("checks must be an array")
    if report["ready"] and not report["checks"]:
        invalid("ready report has no checks")
    check_ids = set()
    for check in report["checks"]:
        if not isinstance(check, dict) or not CHECK_FIELDS <= check.keys():
            invalid("missing required check fields")
        if (any(not isinstance(check[field], str) for field in ("id", "category", "message", "remediation"))
                or not check["id"] or not check["category"]
                or check["status"] not in ("passed", "warning", "blocked", "unknown", "skipped")
                or type(check["blocking"]) is not bool or not isinstance(check["evidence"], dict)):
            invalid("invalid check fields or unknown check status")
        if check["id"] in check_ids:
            invalid("duplicate check IDs")
        check_ids.add(check["id"])
        if report["ready"] and (check["blocking"] or check["status"] == "blocked"):
            invalid("ready report contains a blocking check")
    try:
        json.dumps(report, allow_nan=False)
    except (TypeError, ValueError):
        invalid("report must contain only finite JSON values")
