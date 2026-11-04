"""Completion boundaries are not provider deployment receipts."""

from __future__ import annotations

from typing import Any

from .errors import FailureError


def legacy_execution_result(response: Any) -> dict[str, Any]:
    """Interpret old status-only responses conservatively; validate new acknowledgements."""
    statuses = {"draft", "queued", "running", "submitted", "failed", "interrupted"}
    message = ("Incompatible legacy execution result. Inspect server state before retrying; "
               "local script completion does not verify deployment.")
    if (not isinstance(response, dict) or not isinstance(response.get("status"), str)
            or response["status"] not in statuses):
        raise FailureError(message)
    expected = {
        "contract_version": 1,
        "completion_scope": "local-script",
        "local_terminal": response["status"] in {"submitted", "failed", "interrupted"},
        "deployment_verified": False,
    }
    if "execution_result" not in response:
        return expected
    acknowledged = response["execution_result"]
    if not isinstance(acknowledged, dict) or any(
            type(acknowledged.get(key)) is not type(value) or acknowledged[key] != value
            for key, value in expected.items()):
        raise FailureError(message)
    return dict(acknowledged)
