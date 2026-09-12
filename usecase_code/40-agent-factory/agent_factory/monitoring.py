"""Offline, metrics-only projection of recorded Agent Factory results."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


SCHEMA = "aifactory.monitoring/v1"
SOURCE_FORMATS = ("metrics-only", "preflight", "knowledge", "ingestion", "invocation", "deployment")
MAX_METRICS = 128
MAX_INPUT_BYTES = 1024 * 1024
CHECK_NAMES = {
    "invocation_completed", "grounding_verified", "retrieval_verified",
    "foundry_access", "private_endpoints", "corpus_sha256_verified",
}
UNITS = {"count", "ms", "s", "tokens", "bytes", "percent", "ratio", "USD", "unitless", "unknown"}
LIMITATIONS = [
    "Recorded observations only; this exporter performs no live checks or Azure writes.",
    "Agent health and grounding checks are not data drift or concept drift; both are not_supported.",
    "Health describes only supplied checks, not all agents or ongoing availability.",
    "Missing latency, token, error, sample-count and evaluation metrics are not inferred.",
    "Raw prompts, responses, tool arguments, identities, endpoints and credentials are not exported.",
]


def _identifier(value: str, label: str, limit: int = 128) -> str:
    if not isinstance(value, str) or len(value) > limit or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError(f"{label} must be an explicit, bounded identifier.")
    if value.lower() in {"unknown", "none", "null", "undefined", "placeholder"}:
        raise ValueError(f"{label} must not be a placeholder.")
    return value


def normalize_scope(aifactory: str, project: str, environment: str) -> dict:
    factory = _identifier(aifactory, "aifactory")
    if not isinstance(project, str) or not re.fullmatch(r"[0-9]{3}", project):
        raise ValueError("project must be an explicit three-digit string, for example 001.")
    environment = "test" if environment == "stage" else environment
    if not isinstance(environment, str) or environment not in {"dev", "test", "prod"}:
        raise ValueError("environment must be dev, test (or stage), or prod.")
    return {"aifactory": factory, "project": project, "environment": environment}


def _timestamp(value: str, label: str) -> datetime:
    try:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{label} must be an ISO 8601 timestamp with timezone.") from None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _metric_segment(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", value):
        raise ValueError("Metric keys must be bounded, stable names, not free text or dimensions.")
    # Token *counts* are telemetry; authentication tokens and arbitrary content are not.
    compact = value.lower().replace("_", "")
    if (any(word in compact for word in ("password", "secret", "credential", "authorization", "apikey", "accesstoken"))
            or compact in {"prompt", "prompts", "response", "responses", "text", "content", "user", "userdata",
                           "userid", "email", "token", "key", "input", "output", "arguments", "messages"}):
        raise ValueError("Sensitive/content fields are not metric names.")
    return value


def flatten_metrics(values: dict) -> dict:
    """Accept only numeric/null leaves of a caller-curated aggregate object."""
    if not isinstance(values, dict):
        raise ValueError("metrics must be an object of numeric aggregates.")
    flattened = {}
    visited = 0

    def visit(node: dict, path: tuple[str, ...]) -> None:
        nonlocal visited
        if len(path) > 6:
            raise ValueError("Metric nesting exceeds six levels.")
        for key in sorted(node):
            visited += 1
            if visited > MAX_METRICS * 7:
                raise ValueError("Metric object exceeds the bounded node limit.")
            current = (*path, _metric_segment(key))
            if len(current) > 6:
                raise ValueError("Metric nesting exceeds six levels.")
            name = ".".join(current)
            if len(name) > 128:
                raise ValueError("Flattened metric names must not exceed 128 characters.")
            value = node[key]
            if isinstance(value, dict):
                visit(value, current)
                continue
            if value is not None:
                if type(value) not in {int, float}:
                    raise ValueError("Metrics must contain numbers or null, never strings, booleans, or arrays.")
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite or (type(value) is int and abs(value) > 9007199254740991):
                    raise ValueError("Metrics must be finite JSON numbers in the interoperable numeric range.")
            flattened[name] = value
            if len(flattened) > MAX_METRICS:
                raise ValueError(f"At most {MAX_METRICS} metrics may be exported; split aggregate reports explicitly.")

    visit(values, ())
    return flattened


def _project_source(payload: dict, source_format: str) -> tuple[dict, dict, dict, list[str]]:
    values, units, checks, notes = {}, {}, {}, []

    def number(key: str, unit: str = "count") -> None:
        if key in payload:
            values[key] = payload[key]
            units[key] = unit

    def check(key: str) -> None:
        if key in payload:
            if type(payload[key]) is not bool:
                raise ValueError("Recorded checks must be JSON booleans.")
            checks[key] = payload[key]

    if source_format == "metrics-only":
        allowed = {"metrics", "units", "checks", "scope", "subject"}
        if payload.keys() - allowed:
            raise ValueError("metrics-only accepts only metrics, units, checks and optional scope/subject.")
        values = payload.get("metrics", {})
        units = payload.get("units", {})
        supplied_checks = payload.get("checks", {})
        if not isinstance(supplied_checks, dict) or supplied_checks.keys() - CHECK_NAMES:
            raise ValueError("checks contains an unsupported check name.")
        for key, value in supplied_checks.items():
            if type(value) is not bool:
                raise ValueError("Recorded checks must be JSON booleans.")
            checks[key] = value
        notes.append("metrics-only trusts caller-curated aggregate measurements; it does not instrument agent runtimes.")
    elif source_format == "preflight":
        number("agent_count_on_page")
        check("foundry_access")
        if "network" in payload:
            network = payload["network"]
            if not isinstance(network, list) or len(network) > 128:
                raise ValueError("network must be a bounded list of recorded endpoint checks.")
            if network:
                for item in network:
                    if not isinstance(item, dict) or any(type(item.get(key)) is not bool for key in ("private", "reachable")):
                        raise ValueError("Each recorded endpoint requires private/reachable booleans.")
                checks["private_endpoints"] = all(item["private"] and item["reachable"] for item in network)
                values.update(network_checked_count=len(network),
                              network_private_count=sum(item["private"] for item in network),
                              network_reachable_count=sum(item["reachable"] for item in network))
                units.update({key: "count" for key in values})
        notes.append("Preflight measures shared dependencies and one inventory page, not per-agent invocation health.")
    elif source_format == "knowledge":
        number("document_count")
        number("reference_count")
        check("retrieval_verified")
        notes.append("Knowledge counts and retrieval checks describe the selected shared grounding service.")
    elif source_format == "ingestion":
        for key in ("row_count", "document_count", "evaluation_count"):
            number(key)
        check("corpus_sha256_verified")
        if "blob_integrity" in payload:
            integrity = payload["blob_integrity"]
            if not isinstance(integrity, dict):
                raise ValueError("blob_integrity must be an object.")
            for key in ("raw", "knowledge", "evaluation"):
                item = integrity.get(key, {})
                if not isinstance(item, dict):
                    raise ValueError("Blob integrity entries must be objects.")
                if "bytes" in item:
                    values.setdefault("blob_integrity", {})[key] = {"bytes": item["bytes"]}
                    units[f"blob_integrity.{key}.bytes"] = "bytes"
        notes.append("Ingestion/evaluation row counts are corpus sizes, not measured agent quality or evaluation scores.")
    elif source_format == "invocation":
        if "tool_calls" in payload:
            calls = payload["tool_calls"]
            if not isinstance(calls, list) or len(calls) > 10000 or any(not isinstance(item, dict) for item in calls):
                raise ValueError("tool_calls must be a bounded list of recorded calls.")
            values["tool_call_count"] = len(calls)
            units["tool_call_count"] = "count"
        notes.append("Invocation summaries retain no usage, latency or explicit health check; only recorded tool-call count is available.")
    elif source_format == "deployment":
        notes.append("Deployment lifecycle state/version is not an agent health measurement; no metrics are inferred.")
    return flatten_metrics(values), units, checks, notes


def build_report(payload: dict, *, source_format: str, aifactory: str, project: str, environment: str,
                 subject: str, version: str, window_start: str, window_end: str,
                 generated_at: str | None = None, ttl_hours: float = 24,
                 now: datetime | None = None) -> dict:
    """Export one explicitly selected agent; never discover, authenticate, or mutate Azure."""
    if not isinstance(payload, dict) or source_format not in SOURCE_FORMATS:
        raise ValueError("Select a supported source format and a JSON object.")
    scope = normalize_scope(aifactory, project, environment)
    identity = {"kind": "agent", "name": _identifier(subject, "subject"),
                "version": _identifier(version, "version"), "task_type": "agent"}
    if "scope" in payload:
        given = payload["scope"]
        if (not isinstance(given, dict) or set(given) != set(scope)
                or normalize_scope(**given) != scope):
            raise ValueError("Input scope does not match the explicit selected scope.")
    if "subject" in payload and payload["subject"] != identity:
        raise ValueError("Input subject does not match the explicit selected subject/version.")
    if source_format == "invocation" and "agent" in payload and payload["agent"] != subject:
        raise ValueError("Invocation agent does not match the explicit subject.")
    if source_format == "deployment":
        for key, expected in (("name", subject), ("version", version)):
            if key in payload and str(payload[key]) != expected:
                raise ValueError("Deployment subject/version does not match the explicit selection.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone.")
    start, end = _timestamp(window_start, "window_start"), _timestamp(window_end, "window_end")
    generated = _timestamp(generated_at, "generated_at") if generated_at is not None else now
    if start > end or end > generated or generated > now:
        raise ValueError("Require window_start <= window_end <= generated_at <= now; future observations are rejected.")
    if type(ttl_hours) not in {int, float} or not 0 < ttl_hours <= 24 * 30 or not math.isfinite(ttl_hours):
        raise ValueError("ttl_hours must be finite and greater than zero, at most 720.")
    expires = end + timedelta(hours=ttl_hours)
    metrics, units, checks, notes = _project_source(payload, source_format)
    if (not isinstance(units, dict) or units.keys() - metrics.keys()
            or any(not isinstance(unit, str) or unit not in UNITS for unit in units.values())):
        raise ValueError("units must map existing flattened metric names to supported units.")
    state = ("healthy" if all(checks.values()) else "warning") if checks else "unknown"
    if expires <= now:
        state = "stale"
    limitations = [*LIMITATIONS, *notes]
    if not checks:
        limitations.append("No explicit recorded health checks were supplied; health is unknown, not healthy.")
    return {
        "schema": SCHEMA, "source": "agent-factory", "scope": scope, "subject": identity,
        "generated_at": _iso(generated), "window": {"start": _iso(start), "end": _iso(end)},
        "expires_at": _iso(expires),
        "summary": {"status": state, "data_drift": "not_supported", "concept_drift": "not_supported"},
        "metrics": [{"name": name, "value": value, "unit": units.get(name, "unknown"),
                     "status": "insufficient_data" if value is None else "unknown"}
                    for name, value in metrics.items()],
        "details": {"source_format": source_format, "aggregates": metrics, "checks": checks},
        "limitations": limitations,
    }


def monitoring_tags(report: dict, report_uri: str | None = None) -> dict[str, str]:
    """Return compact tags for a caller to attach; do not publish anything."""
    if report.get("schema") != SCHEMA or report.get("source") != "agent-factory":
        raise ValueError("Expected an agent-factory monitoring/v1 report.")
    scope = normalize_scope(**report["scope"])
    tags = {
        "mon_schema": "1", "mon_source": "agent-factory", "mon_kind": "agent",
        "mon_status": report["summary"]["status"],
        "mon_data_drift": "not_supported", "mon_concept_drift": "not_supported",
        "mon_checked_at": report["generated_at"], "mon_window_end": report["window"]["end"],
        "mon_expires_at": report["expires_at"], "mon_subject_version": report["subject"]["version"],
        **scope,
    }
    if report_uri is not None:
        try:
            uri = urlsplit(report_uri)
            host = uri.hostname or ""
            blob = (uri.scheme == "https" and re.fullmatch(
                r"[a-z0-9]{3,24}\.blob\.core\.(?:windows\.net|usgovcloudapi\.net|chinacloudapi\.cn)", host))
            artifact = uri.scheme == "azureml" and uri.netloc == "jobs" and re.fullmatch(
                r"/[A-Za-z0-9_-]+/outputs/[A-Za-z0-9_-]+/paths/[A-Za-z0-9_./-]+", uri.path)
            valid = (isinstance(report_uri, str) and len(report_uri) <= 256 and (blob or artifact)
                     and not uri.query and not uri.fragment and not uri.username and not uri.password
                     and uri.port is None and len(uri.path.strip("/").split("/")) >= 2
                     and re.fullmatch(r"[A-Za-z0-9_./-]+", uri.path)
                     and not {".", ".."} & set(uri.path.split("/")))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("report_uri must be a credential-free Azure Blob or azureml job artifact URI, at most 256 characters.")
        tags["mon_report_uri"] = report_uri
    return tags


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not allowed.")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("Input contains a non-finite JSON number.")


def read_input(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 1 MiB limit; project aggregate metrics first.")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Input must be a bounded UTF-8 JSON object.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export recorded agent metrics locally; never connect to Azure.")
    parser.add_argument("--input", type=Path, required=True, help="Existing result JSON or a curated metrics-only object.")
    parser.add_argument("--source-format", choices=SOURCE_FORMATS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for field in ("aifactory", "project", "environment", "subject", "version", "window-start", "window-end"):
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--generated-at")
    parser.add_argument("--ttl-hours", type=float, default=24)
    parser.add_argument("--tags-output", type=Path)
    parser.add_argument("--report-uri", help="Already-published credential-free Azure Blob/job artifact URI for tags only.")
    args = parser.parse_args(argv)
    try:
        paths = [args.input.resolve(), args.output.resolve()]
        if args.tags_output:
            paths.append(args.tags_output.resolve())
        if len(set(paths)) != len(paths):
            raise ValueError("Input, report output and tags output must be different files.")
        if args.report_uri and not args.tags_output:
            raise ValueError("--report-uri requires --tags-output; no publishing is performed.")
        payload = read_input(args.input)
        report = build_report(
            payload, source_format=args.source_format, aifactory=args.aifactory, project=args.project,
            environment=args.environment, subject=args.subject, version=args.version,
            window_start=args.window_start, window_end=args.window_end,
            generated_at=args.generated_at, ttl_hours=args.ttl_hours,
        )
        tags = monitoring_tags(report, args.report_uri)
        outputs = [(args.output, report)]
        if args.tags_output:
            outputs.append((args.tags_output, tags))
        for path, value in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
