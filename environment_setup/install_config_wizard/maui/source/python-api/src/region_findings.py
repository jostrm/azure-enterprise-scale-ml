"""Scoped, historical pipeline evidence. This module never contacts Azure or CI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from src.factory_scope import current_factory_scope


MAX_CONTENT_BYTES = 1024 * 1024
MAX_OBSERVATIONS = 200
MAX_LOCAL_REPORTS = 100
MAX_LOCAL_BYTES = 16 * MAX_CONTENT_BYTES
KINDS = {"capacity", "quota", "pipeline_error", "preflight_error"}
SOURCES = {"pipeline_artifact", "user_reported"}
_REPORT_FIELDS = {
    "schema_version", "region", "subscription_id", "tenant_id", "environment",
    "source", "run_id", "run_url", "observed_at", "observations",
}
_OBSERVATION_FIELDS = {"check_id", "kind", "service", "sku", "status", "message"}
_SECRET = re.compile(
    r"-----BEGIN .*PRIVATE KEY|"
    r"\b(?:authorization|password|client_secret|access_token|accountkey|"
    r"sharedaccesssignature|api[_-]?key)\s*[:=]\s*\S+|"
    r"\bbearer\s+[a-z0-9._~+/-]{12,}|[?&]sig=|"
    r"\b(?:gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,})",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _folder(folder: str) -> str:
    value = _text(folder, "aifactory_folder", 4096)
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("aifactory_folder must be an existing local directory.")
    return os.path.normcase(os.path.normpath(str(root)))


def _text(value: Any, field: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{field} must be a string of at most {limit} characters.")
    value = value.strip()
    if (not value and not allow_empty) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{field} must be a single-line value.")
    if _SECRET.search(value):
        raise ValueError(f"{field} must not contain credentials or raw secret-bearing logs.")
    return value


def _guid(value: Any, field: str) -> str:
    text = _text(value, field, 36)
    try:
        normalized = str(UUID(text))
    except ValueError:
        raise ValueError(f"{field} must be a UUID.") from None
    if text.casefold() != normalized:
        raise ValueError(f"{field} must be a hyphenated UUID.")
    return normalized


def _observed_at(value: Any) -> str | None:
    if value is None:
        return None
    text = _text(value, "observed_at", 40)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", text):
        raise ValueError("observed_at must be an ISO UTC timestamp or null.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("observed_at must be an ISO UTC timestamp or null.") from None
    if parsed > datetime.now(timezone.utc):
        raise ValueError("observed_at cannot be in the future.")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _run_url(value: Any) -> str | None:
    if value is None:
        return None
    text = _text(value, "run_url", 2048)
    try:
        url = urlsplit(text)
        host = (url.hostname or "").casefold()
        safe = (
            url.scheme == "https" and url.port in (None, 443)
            and not url.username and not url.password and not url.fragment
            and "\\" not in text
        )
        if host == "github.com":
            safe = safe and bool(re.fullmatch(
                r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/\d+(?:/attempts/\d+)?/?",
                url.path,
            )) and not url.query
        elif host == "dev.azure.com" or re.fullmatch(r"[a-z0-9-]+\.visualstudio\.com", host):
            query = parse_qs(url.query, keep_blank_values=True)
            safe = safe and bool(re.fullmatch(r"/[^?#\\]+/_build/results/?", url.path))
            safe = safe and set(query) <= {"buildId", "view"} and len(query.get("buildId", [])) == 1
            safe = safe and query.get("buildId", [""])[0].isdigit()
            safe = safe and (not query.get("view") or query["view"] in (["results"], ["logs"]))
        else:
            safe = False
    except ValueError:
        safe = False
    if not safe:
        raise ValueError("run_url must be an HTTPS GitHub Actions or Azure DevOps build-run URL.")
    return text


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_report(content: str) -> dict[str, Any]:
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValueError("Report content must be at most 1 MiB of UTF-8 JSON.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Report JSON must not contain duplicate keys.")
            result[key] = value
        return result

    try:
        return validate_report(json.loads(content.lstrip("\ufeff"), object_pairs_hook=unique_object))
    except (json.JSONDecodeError, RecursionError):
        raise ValueError("Report content must be valid bounded JSON.") from None


def validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) != _REPORT_FIELDS:
        raise ValueError("Report must contain exactly the schema-version-1 report fields.")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise ValueError("Unsupported region-findings schema_version; expected 1.")
    result = {"schema_version": 1}
    result["region"] = _text(report["region"], "region", 64).casefold()
    if not re.fullmatch(r"[a-z][a-z0-9]{1,63}", result["region"]):
        raise ValueError("region must be an Azure region code, for example eastus2.")
    for field in ("subscription_id", "tenant_id"):
        result[field] = _guid(report[field], field)
    environment = _text(report["environment"], "environment", 8, allow_empty=True).casefold()
    result["environment"] = "stage" if environment == "test" else environment
    if result["environment"] not in {"", "dev", "stage", "prod"}:
        raise ValueError("environment must be dev, stage, prod, test, or empty.")
    result["source"] = _text(report["source"], "source", 32)
    if result["source"] not in SOURCES:
        raise ValueError("source must be pipeline_artifact or user_reported.")
    result["run_id"] = None if report["run_id"] is None else _text(report["run_id"], "run_id", 128)
    result["run_url"] = _run_url(report["run_url"])
    result["observed_at"] = _observed_at(report["observed_at"])
    observations = report["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= MAX_OBSERVATIONS:
        raise ValueError("observations must contain between 1 and 200 entries.")
    normalized = []
    scopes = set()
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != _OBSERVATION_FIELDS:
            raise ValueError("Each observation must contain exactly the schema-version-1 observation fields.")
        item = {
            "check_id": _text(observation["check_id"], "check_id", 128).casefold(),
            "kind": _text(observation["kind"], "kind", 32),
            "service": _text(observation["service"], "service", 128).casefold(),
            "sku": None if observation["sku"] is None else _text(observation["sku"], "sku", 128).casefold(),
            "status": _text(observation["status"], "status", 16),
            "message": _text(observation["message"], "message", 1000),
        }
        if item["service"] == "azure ai search":
            item["service"] = "microsoft.search/searchservices"
        if not re.fullmatch(r"[a-z0-9_.:/-]+", item["check_id"]):
            raise ValueError("check_id must be a stable alphanumeric identifier.")
        if item["kind"] not in KINDS or item["status"] not in {"failed", "passed", "unknown"}:
            raise ValueError("Observation kind or status is unsupported.")
        scope = (item["check_id"], item["kind"], item["service"], item["sku"])
        if scope in scopes:
            raise ValueError("A report must not repeat the same check/service/SKU scope.")
        scopes.add(scope)
        normalized.append(item)
    result["observations"] = sorted(normalized, key=_json)
    if len(_json(result).encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValueError("Report content must be at most 1 MiB of UTF-8 JSON.")
    return result


def _scope_allows(scope: dict, report: dict) -> bool:
    subscriptions = {
        str(env).casefold(): str(sub).casefold()
        for env, sub in scope.get("subscriptions", {}).items()
    }
    tenants = {
        str(sub).casefold(): str(tenant).casefold()
        for sub, tenant in scope.get("subscription_tenants", {}).items()
    }
    sub, tenant, env = report["subscription_id"], report["tenant_id"], report["environment"]
    return (
        sub in subscriptions.values() and tenants.get(sub) == tenant
        and (not env or subscriptions.get(env) == sub)
    )


class RegionFindingsStore:
    """Append-only evidence with exact-scope, chronological success resolution."""

    def __init__(self, db_path: str | os.PathLike[str]):
        self.db_path = Path(db_path)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS region_findings_history (
                    id TEXT PRIMARY KEY,
                    aifactory_folder TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    region TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    service TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_at TEXT,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_region_findings_scope
                    ON region_findings_history (
                        aifactory_folder, subscription_id, tenant_id, region,
                        environment, check_id, kind, service, sku, status, observed_at
                    );
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_report(self, folder: str, report: dict[str, Any]) -> dict[str, Any]:
        root = _folder(folder)
        report = validate_report(report)
        if not _scope_allows(current_factory_scope(root), report):
            raise ValueError("Report subscription, tenant, and environment do not match the current factory scope.")
        report_hash = hashlib.sha256(_json(report).encode("utf-8")).hexdigest()
        recorded_at = _now()
        recorded = 0
        with self._connect() as connection:
            for observation in report["observations"]:
                payload = {key: value for key, value in report.items() if key != "observations"}
                payload.update(observation)
                identifier = hashlib.sha256(
                    _json([root, report_hash, observation]).encode("utf-8")
                ).hexdigest()
                payload.update(id=identifier, recorded_at=recorded_at)
                result = connection.execute("""
                    INSERT OR IGNORE INTO region_findings_history (
                        id, aifactory_folder, subscription_id, tenant_id, region,
                        environment, check_id, kind, service, sku, status, source,
                        observed_at, recorded_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    identifier, root, report["subscription_id"], report["tenant_id"],
                    report["region"], report["environment"], observation["check_id"],
                    observation["kind"], observation["service"], observation["sku"] or "",
                    observation["status"], report["source"], report["observed_at"],
                    recorded_at, _json(payload),
                ))
                recorded += result.rowcount
        return {
            "recorded": recorded,
            "message": (
                f"Recorded {recorded} historical observation(s); no Azure resources were queried or changed."
                if recorded else "Report already recorded; no observations changed."
            ),
        }

    def import_content(self, folder: str, content: str) -> dict[str, Any]:
        return self.record_report(folder, parse_report(content))

    def import_local(self, folder: str) -> list[str]:
        root = Path(_folder(folder))
        directory = root / "config-wizard" / "pipeline-reports"
        warnings = []
        if not directory.exists():
            return warnings
        if not directory.resolve().is_relative_to(root):
            return ["Local pipeline reports ignored: report directory leaves the current factory folder."]
        total_bytes = 0
        try:
            for index, path in enumerate(directory.glob("*.json")):
                if index >= MAX_LOCAL_REPORTS:
                    warnings.append("Local pipeline report limit reached (100 files per refresh).")
                    break
                try:
                    if not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
                        raise ValueError("Report must be a file inside the local pipeline-reports directory.")
                    with path.open("rb") as stream:
                        content = stream.read(MAX_CONTENT_BYTES + 1)
                    total_bytes += len(content)
                    if total_bytes > MAX_LOCAL_BYTES:
                        warnings.append("Local pipeline report byte limit reached (16 MiB per refresh).")
                        break
                    if len(content) > MAX_CONTENT_BYTES:
                        raise ValueError("Report content must be at most 1 MiB of UTF-8 JSON.")
                    self.import_content(str(root), content.decode("utf-8-sig"))
                except (ValueError, OSError, sqlite3.Error) as error:
                    detail = str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else "File could not be read or persisted."
                    warnings.append(f"Local pipeline report {index + 1} ignored: {detail}")
        except OSError:
            warnings.append("Local pipeline reports could not be read.")
        if len(warnings) > 4:
            warnings = warnings[:3] + [f"{len(warnings) - 3} additional local pipeline report warning(s)."]
        return warnings

    def unresolved(self, folder: str) -> dict[str, list[dict[str, Any]]]:
        root = _folder(folder)
        scope = current_factory_scope(root)
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT failure.payload_json FROM region_findings_history AS failure
                WHERE failure.aifactory_folder = ? AND failure.status = 'failed'
                  AND NOT EXISTS (
                    SELECT 1 FROM region_findings_history AS success
                    WHERE success.aifactory_folder = failure.aifactory_folder
                      AND success.subscription_id = failure.subscription_id
                      AND success.tenant_id = failure.tenant_id
                      AND success.region = failure.region
                      AND success.environment = failure.environment
                      AND success.check_id = failure.check_id
                      AND success.kind = failure.kind
                      AND success.service = failure.service
                      AND success.sku = failure.sku
                      AND success.status = 'passed'
                      AND success.observed_at > COALESCE(failure.observed_at, failure.recorded_at)
                  )
                ORDER BY COALESCE(failure.observed_at, failure.recorded_at) DESC,
                         failure.recorded_at DESC, failure.id
            """, (root,)).fetchall()
        latest = {}
        for row in rows:
            item = json.loads(row["payload_json"])
            if not _scope_allows(scope, item):
                continue
            key = tuple(item[field] for field in (
                "subscription_id", "tenant_id", "region", "environment", "check_id",
                "kind", "service", "sku", "source",
            ))
            latest.setdefault(key, item)
        groups = {}
        for item in latest.values():
            key = tuple(item[field] for field in (
                "subscription_id", "tenant_id", "region", "environment", "check_id",
                "kind", "service", "source", "run_id", "run_url", "observed_at",
                "recorded_at", "message",
            ))
            if key not in groups:
                groups[key] = {
                    field: item[field] for field in (
                        "kind", "service", "message", "source", "run_id", "run_url",
                        "observed_at", "recorded_at", "environment",
                    )
                }
                groups[key].update(
                    id=hashlib.sha256(_json(key).encode("utf-8")).hexdigest(),
                    skus=[], status="failed",
                )
            if item["sku"] is not None:
                groups[key]["skus"].append(item["sku"])
        by_region = defaultdict(list)
        for key, finding in groups.items():
            finding["skus"].sort()
            by_region[key[2]].append(finding)
        return dict(by_region)

    def overlay(self, folder: str, regions: list[dict]) -> list[str]:
        for region in regions:
            region["pipeline_findings"] = []
        warnings = []
        try:
            warnings.extend(self.import_local(folder))
            findings = self.unresolved(folder)
            known_regions = {region["name"] for region in regions}
            for region in regions:
                region["pipeline_findings"] = findings.get(region["name"], [])
            if findings.keys() - known_regions:
                warnings.append("Historical findings include region codes outside the current map catalog.")
        except (ValueError, OSError, sqlite3.Error):
            warnings.append("Historical region findings unavailable for the current factory scope; no success is inferred.")
        return warnings
