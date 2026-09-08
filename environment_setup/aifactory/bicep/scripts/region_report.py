#!/usr/bin/env python3
"""Offline, best-effort v1 region reports; never queries Azure or pipeline APIs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID


SEARCH_SKUS = {
    "free", "basic", "standard", "standard2", "standard3",
    "storage_optimized_l1", "storage_optimized_l2",
}
SEARCH_SERVICE = "microsoft.search/searchservices"
CAPACITY_CODES = {
    "SkuNotAvailable", "InsufficientCapacity", "AllocationFailed",
    "ZonalAllocationFailed", "CapacityUnavailable", "RegionCapacityUnavailable",
}
MAX_INPUT = 1024 * 1024


def warning(message: str) -> None:
    # Never print exception strings: they can contain configuration or raw input.
    print(f"WARNING: AI Factory region report: {message}", file=sys.stderr)


def first(*names: str) -> str:
    return next((os.environ[n].strip() for n in names if os.environ.get(n, "").strip()), "")


def identifier(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
        raise ValueError("Invalid identifier")
    return str(UUID(value))


def safe_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.:-]", "-", value) or "unknown-job"
    if len(name) > 100:
        return name[:87] + "-" + sha256(value.encode("utf-8")).hexdigest()[:12]
    return name


def job_name() -> str:
    return safe_name(first("AIFACTORY_REPORT_JOB") or
                     ":".join(filter(None, (first("SYSTEM_STAGENAME"), first("SYSTEM_JOBNAME")))) or
                     first("GITHUB_JOB") or "local-preflight")


def run_url() -> str | None:
    url = first("AIFACTORY_REPORT_RUN_URL")
    if not url and first("GITHUB_SERVER_URL") and first("GITHUB_REPOSITORY") and first("GITHUB_RUN_ID"):
        url = (f"{first('GITHUB_SERVER_URL')}/{first('GITHUB_REPOSITORY')}"
               f"/actions/runs/{quote(first('GITHUB_RUN_ID'), safe='')}")
    if not url and first("SYSTEM_COLLECTIONURI") and first("SYSTEM_TEAMPROJECT") and first("BUILD_BUILDID"):
        url = (f"{first('SYSTEM_COLLECTIONURI').rstrip('/')}/{quote(first('SYSTEM_TEAMPROJECT'), safe='')}"
               f"/_build/results?buildId={quote(first('BUILD_BUILDID'), safe='')}")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    # Keep only ADO's run identifier, never SAS tokens/credentials or fragments.
    query = parts.query if re.fullmatch(r"buildId=\d+", parts.query) else ""
    github_run = parts.hostname == "github.com" and re.fullmatch(r"/[^/]+/[^/]+/actions/runs/\d+", parts.path)
    ado_run = (parts.hostname == "dev.azure.com" and
               re.fullmatch(r"/[^/]+/[^/]+/_build/results", parts.path) and query)
    if not (github_run or ado_run):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def report(observations: list[dict], *, region: str = "", subscription: str = "",
           environment: str = "") -> dict:
    if len(observations) > 200:
        raise ValueError("Too many observations")
    region = (region or first("AIFACTORY_REPORT_REGION", "admin_location", "AIFACTORY_LOCATION")).lower()
    if not re.fullmatch(r"[a-z][a-z0-9]{1,49}", region) or region in {"unknown", "none", "null", "todo"}:
        raise ValueError("Missing or invalid region")
    environment = (environment or first("AIFACTORY_REPORT_ENVIRONMENT", "dev_test_prod")).lower()
    environment = {"test": "stage", "current": ""}.get(environment, environment)
    if environment not in {"dev", "stage", "prod", ""}:
        raise ValueError("Invalid environment")
    return {
        "schema_version": 1,
        "region": region,
        "subscription_id": identifier(subscription or first("AIFACTORY_REPORT_SUBSCRIPTION_ID", "dev_test_prod_sub_id")),
        "tenant_id": identifier(first("AIFACTORY_REPORT_TENANT_ID", "tenantId", "TENANT_ID")),
        "environment": environment,
        "source": "pipeline_artifact",
        "run_id": first("AIFACTORY_REPORT_RUN_ID", "BUILD_BUILDID", "GITHUB_RUN_ID") or None,
        "run_url": run_url(),
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "observations": observations,
    }


def observation(check_id: str, kind: str, service: str, status: str,
                message: str, sku: str | None = None) -> dict:
    return dict(check_id=check_id, kind=kind, service=service, sku=sku, status=status, message=message)


def pipeline_observation(status: str) -> dict:
    status = {"failed": "failed", "failure": "failed", "succeeded": "passed", "success": "passed"}.get(
        status.strip().lower(), "unknown")
    message = {
        "failed": "Pipeline job failed; see linked run logs.",
        "passed": "This pipeline job succeeded; this does not establish SKU capacity.",
        "unknown": "Pipeline job was cancelled, skipped, partially successful, or its result is unavailable.",
    }[status]
    return observation(f"pipeline-job:{job_name()}", "pipeline_error", "AI Factory pipeline", status, message)


def finding_observation(severity: str, code: str, sku: str) -> dict:
    """Use curated reasons, not raw logs/configuration values or remediation commands."""
    code = safe_name(code)
    sku = sku.lower() if sku.lower() in SEARCH_SKUS else None
    status = {"FAIL": "failed", "PASS": "passed"}.get(severity, "unknown")
    if code in {"SEARCH_SKU_UNAVAILABLE", "SEARCH_SKU_AVAILABLE"}:
        present = code == "SEARCH_SKU_AVAILABLE"
        return observation("search_sku_availability", "capacity", SEARCH_SERVICE,
                           ("passed" if present else "failed") if sku else "unknown",
                           f"Selected SKU was {'listed in' if present else 'absent from'} the regional Search usage catalogue; "
                           "this is SKU discovery evidence, not a live allocation probe.", sku)
    if code.startswith("SEARCH_QUOTA"):
        message = {
            "failed": "Selected Azure AI Search SKU quota is exhausted.",
            "passed": "Selected Azure AI Search SKU has quota headroom; live capacity is not established.",
            "unknown": "Azure AI Search quota could not be validated.",
        }[status]
        return observation("search_sku_quota", "quota", SEARCH_SERVICE, status, message, sku)
    if code.startswith(("MODEL_QUOTA", "CS_QUOTA")):
        return observation(f"preflight:{code}", "quota", "Azure AI Foundry / OpenAI", status,
                           f"Preflight {code}: {status}; see linked run logs for the quota details.")
    return observation(f"preflight:{code}", "preflight_error", "AI Factory preflight", status,
                       f"Preflight {code}: {status}; see linked run logs for configuration/check details.")


def capacity_observations(path: Path) -> list[dict]:
    """Opt-in input: a single tested Search command's structured error envelope."""
    if path.stat().st_size > MAX_INPUT:
        raise ValueError("Oversized error input")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("service") not in {"Azure AI Search", SEARCH_SERVICE}:
        return []
    sku = str(payload.get("sku", "")).lower()
    if sku not in SEARCH_SKUS:
        return []

    def known_code(node: object, depth: int = 0) -> str | None:
        if not isinstance(node, dict) or depth > 12:
            return None
        if node.get("code") in CAPACITY_CODES:
            return node["code"]
        children = node.get("details", [])
        if not isinstance(children, list):
            children = []
        for child in [node.get("error"), node.get("innererror"), *children]:
            code = known_code(child, depth + 1)
            if code:
                return code
        return None

    code = known_code(payload.get("error"))
    if not code:
        return []
    return [observation("search_sku_capacity", "capacity", SEARCH_SERVICE, "failed",
                        f"Tested Azure AI Search SKU allocation failed with {code}; see linked run logs.", sku)]


def write_report(directory: Path, name: str, payload: dict) -> None:
    content = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if len(content) > MAX_INPUT:
        raise ValueError("Report exceeds import size limit")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{safe_name(name).replace(':', '-')}.json"
    pending = destination.with_suffix(".pending")
    try:
        pending.write_bytes(content)
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)


def preflight_reports(raw: str, completed: bool) -> list[dict]:
    # NUL-delimited groups: environment, subscription, severity, code, message, SKU.
    fields = raw.split("\0")
    if fields[-1:] == [""]:
        fields.pop()
    if len(fields) % 6:
        raise ValueError("Invalid finding stream")
    records = [fields[i:i + 6] for i in range(0, len(fields), 6)]
    targets = [t.split("|", 1) for t in os.environ.get("PF_REPORT_TARGETS", "").splitlines() if "|" in t]
    if not targets:
        targets = [[first("PF_REPORT_ENVIRONMENT", "AIFACTORY_REPORT_ENVIRONMENT", "dev_test_prod"),
                    first("PF_REPORT_SUBSCRIPTION_ID", "AIFACTORY_REPORT_SUBSCRIPTION_ID", "dev_test_prod_sub_id")]]
    reports = []
    for environment, subscription in targets:
        observations = {}
        failures = False
        warnings = False
        for record_env, record_sub, severity, code, _message, sku in records:
            if record_sub and (record_sub != subscription or record_env != environment):
                continue
            item = finding_observation(severity, code, sku)
            key = (item["check_id"], item["sku"])
            previous = observations.get(key)
            # A later unknown/pass within this invocation never hides a failure.
            if not previous or previous["status"] != "failed":
                observations[key] = item
            failures |= severity == "FAIL"
            warnings |= severity == "WARN"
        failures |= completed and first("PF_REPORT_EXIT_CODE") in {"1", "2"}
        status = "failed" if failures else ("passed" if completed and not warnings else "unknown")
        summary = observation(f"preflight-job:{job_name()}", "preflight_error", "AI Factory preflight",
                              status, "Preflight completed; inspect individual findings. No live capacity "
                              "guarantee is made." if completed else
                              "Preflight was skipped or did not complete; unchecked services remain unknown.")
        try:
            reports.append(report([summary, *observations.values()], region=first("PF_REPORT_REGION"),
                                  subscription=subscription, environment=environment))
        except ValueError:
            warning("no report written for a target with missing/invalid region, subscription, tenant, or environment.")
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "pipeline"))
    parser.add_argument("--command-error-file", type=Path)
    args = parser.parse_args(argv)
    directory = first("PREFLIGHT_REPORT_DIR" if args.mode == "preflight" else "AIFACTORY_REPORT_DIR")
    if not directory:
        return 0
    try:
        if args.mode == "preflight":
            raw = sys.stdin.buffer.read(MAX_INPUT + 1)
            if len(raw) > MAX_INPUT:
                raise ValueError("Oversized findings")
            reports = preflight_reports(raw.decode("utf-8"), first("PF_REPORT_COMPLETED") == "true")
        else:
            item = pipeline_observation(first("AIFACTORY_REPORT_JOB_STATUS", "AGENT_JOBSTATUS"))
            observations = [item]
            if args.command_error_file and item["status"] == "failed":
                try:
                    observations.extend(capacity_observations(args.command_error_file))
                except (ValueError, OSError, TypeError, RecursionError):
                    warning("structured command error could not be used; retaining the generic job result.")
            reports = [report(observations)]
        for payload in reports:
            name = f"{args.mode}-{payload['environment'] or 'current'}-{payload['subscription_id']}"
            write_report(Path(directory), name, payload)
    except (ValueError, OSError, TypeError, RecursionError):
        warning("no report written: missing/invalid region, subscription, tenant, environment, or report input/output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
