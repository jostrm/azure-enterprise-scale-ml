"""Fail-closed client checks for releasing a failed run's retained single-writer claim.

The Factory API is authoritative and re-verifies everything on confirmation; these checks
only refuse a preview or result that does not describe exactly the requested release.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from .errors import ConfigError, FailureError

PURPOSE = "reconcile-run-claim-confirm"
OPERATION = "reconcile-run-claim"
CAPABILITY = "reconcile-run-claim-v1"
OPERATION_MODE = "provider-state"
STATE_REF = "refs/heads/aifactory-state/single-writer-v1"
AUDIT_PREFIX = "claim-reconciliations/"
TERMINAL = ("succeeded", "blocked", "reconciliation-required")
REQUEST_FIELDS = {"contract_version", "folder", "factory_id", "run_id"}


def _text(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _uuid(value: Any) -> bool:
    try:
        parsed = UUID(value)
        return bool(parsed.int) and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _sha(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def phrase(run_id: str) -> str:
    return "RELEASE " + run_id


def validate_request(request: Any) -> None:
    if (not isinstance(request, dict) or set(request) != REQUEST_FIELDS
            or type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or not _text(request.get("folder")) or not _uuid(request.get("factory_id"))
            or not _uuid(request.get("run_id"))):
        raise ConfigError("Run claim reconciliation requires contract 1, an exact folder, factory UUID and run UUID.")


def validate_claim_preview(request: dict[str, Any], preview: Any) -> None:
    def invalid(reason):
        raise ConfigError("Unsafe or incompatible run claim review: " + reason + ". Nothing was released.")

    validate_request(request)
    if (not isinstance(preview, dict) or type(preview.get("contract_version")) is not int
            or preview["contract_version"] != 1 or not isinstance(preview.get("capabilities"), list)
            or CAPABILITY not in preview["capabilities"] or preview.get("operation_mode") != OPERATION_MODE):
        invalid("the API must acknowledge " + CAPABILITY + "; no fallback is allowed")
    if (preview.get("folder") != request["folder"] or preview.get("factory_id") != request["factory_id"]
            or preview.get("run_id") != request["run_id"] or not _uuid(preview.get("job_id"))):
        invalid("the exact folder, factory and run were not preserved")
    if not _uuid(preview.get("confirmation_id")) or not _sha(preview.get("preview_hash"), 64):
        invalid("missing exact confirmation identity or server review fingerprint")
    if preview.get("confirmation_phrase") != phrase(request["run_id"]):
        invalid("the server confirmation phrase does not name the reviewed run")
    if preview.get("azure_writes") is not False:
        invalid("the release must not change Azure")
    if (not _text(preview.get("repository")) or preview.get("state_ref") != STATE_REF
            or not _sha(preview.get("provider_head"), 40)):
        invalid("missing provider repository, state ref or reviewed head")
    claim = preview.get("active_claim")
    if (not isinstance(claim, dict) or claim.get("kind") != "run" or claim.get("run_id") != request["run_id"]
            or not _sha(claim.get("manifest_hash"), 64) or not isinstance(claim.get("scopes"), list)
            or not claim["scopes"] or any(not _text(scope) for scope in claim["scopes"])):
        invalid("the active claim is not exactly this run's claim")
    # A run receipt that still says running is released only when the server finalizes it: its dispatcher
    # provably stopped before it saw the finished remote run while the worker receipt is terminal (aif-134,
    # 2026-10-27; aif-138, 2026-10-28: the laptop poll stopped on a provider state read).
    finalized = preview.get("run_receipt_finalized", False)
    if type(finalized) is not bool:
        invalid("the run receipt finalization flag must be true or false")
    worker, run_receipt = preview.get("worker_receipt"), preview.get("run_receipt")
    if not isinstance(worker, dict) or worker.get("status") not in TERMINAL:
        invalid("the run and worker receipts must be terminal")
    if not isinstance(run_receipt, dict) or run_receipt.get("status") not in (("running",) if finalized else TERMINAL):
        invalid("the run and worker receipts must be terminal" if not finalized else
                "a finalized release names a run receipt that still says running; the receipts do not match")
    remote = preview.get("remote_run")
    if (not isinstance(remote, dict) or remote.get("kind") not in ("gha", "ado")
            or type(remote.get("run_id")) is not int or remote.get("status") != "completed"):
        invalid("the GitHub Actions or Azure DevOps run must be completed")
    if type(preview.get("other_runs_in_progress")) is not int or preview["other_runs_in_progress"] != 0:
        invalid("another workflow run is queued or in progress")
    if (preview.get("audit_record") != AUDIT_PREFIX + request["run_id"] + "/" + str(preview.get("confirmation_id")) + ".json"
            or type(preview.get("records_preserved")) is not int or preview["records_preserved"] < 1):
        invalid("missing audit record or preserved-record count")
    for field in ("effects", "warnings"):
        if (not isinstance(preview.get(field), list) or not preview[field]
                or any(not _text(item) for item in preview[field])):
            invalid("missing exact effects or warnings")


def validate_release(result: Any, receipt: dict[str, Any]) -> None:
    preview = receipt["preview"]
    if (not isinstance(result, dict) or type(result.get("contract_version")) is not int
            or result["contract_version"] != 1 or result.get("status") != "released"
            or result.get("folder") != receipt["folder"] or result.get("run_id") != preview["run_id"]
            or result.get("factory_id") != preview["factory_id"] or result.get("repository") != preview["repository"]
            or result.get("previous_head") != preview["provider_head"] or not _sha(result.get("head"), 40)
            or result["head"] == preview["provider_head"] or result.get("audit_record") != preview["audit_record"]):
        raise FailureError("Run claim reconciliation returned an unexpected result. Read the provider state "
                           "before any further action; nothing was retried.")


def describe(preview: dict[str, Any]) -> dict[str, Any]:
    remote = preview["remote_run"]
    return {
        "Run": preview["run_id"], "Operation": preview.get("operation"), "Local job": preview["job_id"],
        "Factory ID": preview["factory_id"], "Saved folder": preview["folder"],
        "Provider repository": preview["repository"], "State ref": preview["state_ref"],
        "Reviewed state head": preview["provider_head"], "Expires": preview["expires_at"],
        "Server review fingerprint": preview["preview_hash"],
        "Retained claim": preview["active_claim"],
        "Run receipt": preview["run_receipt"], "Worker receipt": preview["worker_receipt"],
        ("GitHub Actions run" if remote["kind"] == "gha" else "Azure DevOps run"): remote,
        "Other workflow runs queued or in progress": preview["other_runs_in_progress"],
        "Records kept unchanged": preview["records_preserved"], "Audit record added": preview["audit_record"],
        "Effects": preview["effects"], "Cautions": preview["warnings"],
    }
