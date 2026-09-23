"""Lossless, bounded canonical observations in the native v2 evidence envelope."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re


SCHEMA = "aifactory.agent-observations/v2"
CANONICAL = "aifactory.monitoring-observations.v1"
COUNTS = (
    "requests", "input_tokens", "output_tokens", "completed_outcomes", "attempted_outcomes",
    "successful_requests", "latency_samples", "evaluated_responses", "quality_passed_responses",
    "security_findings", "security_checks", "active_users", "eligible_users",
)
NUMBERS = (
    "baseline_minutes_per_outcome", "actual_minutes_per_outcome", "labor_rate_per_hour",
    "latency_ms_sum", "token_estimated_cost", "actual_cost", "amortized_cost", "realized_benefit_amount",
)
TEXT = (
    "factory", "scaleset", "project", "environment", "agent_id", "agent_name", "timestamp",
    "period_start", "period_end", "model", "cost_center", "currency", "data_source",
    "subscription_id", "resource_group", "resource_id", "cost_scope",
)
FLAGS = ("outcome_quality_passed", "metadata_validated")
FIELDS = set(COUNTS + NUMBERS + TEXT + FLAGS + ("source", "provenance", "value_evidence", "cost_evidence"))
FINANCE_EVIDENCE = {
    "value_evidence": {"owner", "baseline_reference", "period_start", "period_end", "valuation_method",
                       "evidence_reference", "approval_reference", "currency", "scope"},
    "cost_evidence": {"period_start", "period_end", "currency", "scope", "coverage", "reference"},
}
FINANCE_UNSUPPORTED = (
    "realized_benefit_amount", "verified_realized_value", "cost_per_accepted_outcome",
    "verified_net_value", "verified_roi_percent",
)
FINANCE_NOTICE = "financial projection unsupported in native v2; evidence preserved. Use canonical API period/scope/approval/coverage/overlap validation; supplied references are not independently audited."
NATIVE_MAX = 9007199254740991
SCOPE = {"aiFactory": "factory", "scaleset": "scaleset", "project": "project",
         "environment": "environment", "agent": "agent_id"}
VALUE_INPUTS = ("completed_outcomes", "baseline_minutes_per_outcome", "actual_minutes_per_outcome")
REPORT_IDS = ("agent-value", "showback", "foundry-tokens", "foundry-usage",
              "quality-reliability", "security-governance")
MONEY = {"actual_cost", "amortized_cost", "token_estimated_cost", "modeled_capacity_value",
         "qualified_capacity_value", "realized_benefit_amount", "verified_realized_value",
         "verified_net_value", "cost_per_accepted_outcome"}
UNITS = {
    **{name: "count" for name in COUNTS},
    "requests": "requests", "successful_requests": "requests",
    "completed_outcomes": "outcomes", "attempted_outcomes": "outcomes",
    "latency_samples": "samples", "evaluated_responses": "responses", "quality_passed_responses": "responses",
    "security_checks": "checks", "security_findings": "findings", "active_users": "users", "eligible_users": "users",
    "input_tokens": "tokens", "output_tokens": "tokens",
    "latency_ms_sum": "milliseconds", "mean_latency_ms": "milliseconds",
    "baseline_minutes_per_outcome": "minutes/outcome", "actual_minutes_per_outcome": "minutes/outcome",
    "labor_rate_per_hour": "currency/hour", "modeled_minutes_saved": "minutes saved",
    "qualified_minutes_saved": "minutes saved", "success_rate": "%", "quality_pass_rate": "%",
    "qualified_hours_saved": "hours saved", "qualified_outcomes": "outcomes",
    "adoption_rate": "%", "verified_roi_percent": "%",
}


def _number(value):
    return type(value) in (int, float) and abs(value) <= 1e100 and math.isfinite(value)


def _native_number(value):
    return _number(value) and abs(value) <= NATIVE_MAX


def _native_sum(values):
    if not values or any(not _native_number(value) for value in values):
        return None
    result = sum(values)
    return result if _native_number(result) else None


def _text(value):
    return value is None or (isinstance(value, str) and len(value) <= 2048
                             and not re.search(r"[\x00-\x1f\x7f]", value))


def _clean_text(value):
    return value.strip() or None if isinstance(value, str) else None


def _inputs(value, depth=0):
    if depth > 6:
        raise ValueError("Provenance inputs exceed six nesting levels.")
    if value is None or isinstance(value, bool) or _number(value):
        return
    if isinstance(value, str) and _text(value):
        return
    if isinstance(value, list) and len(value) <= 100:
        for item in value:
            _inputs(item, depth + 1)
        return
    if isinstance(value, dict) and len(value) <= 50:
        for key, item in value.items():
            if (not isinstance(key, str) or not _text(key)
                    or re.search(r"password|secret|credential|authorization|api.?key|access.?token|connectionstring", key, re.I)):
                raise ValueError("Provenance inputs contain an unsupported or credential-like key.")
            _inputs(item, depth + 1)
        return
    raise ValueError("Provenance inputs must be bounded JSON values.")


def validate_record(record, source):
    if not isinstance(record, dict) or set(record) - FIELDS:
        raise ValueError("Lossless v2 accepts only recognized canonical fields; unsupported fields are never dropped.")
    if record.get("source") not in (None, source):
        raise ValueError("Sample evidence cannot be relabeled live.")
    for name in TEXT:
        if name in record and not _text(record[name]):
            raise ValueError(f"{name} must be bounded text or null.")
    for name in COUNTS + NUMBERS:
        value = record.get(name)
        if value is None:
            continue
        if not _number(value) or (name not in {"actual_cost", "amortized_cost"} and value < 0):
            raise ValueError(f"{name} must be a finite canonical number, not a boolean.")
        if name in COUNTS and int(value) != value:
            raise ValueError(f"{name} must be a whole-number observation.")
    for name in FLAGS:
        if record.get(name) is not None and type(record[name]) is not bool:
            raise ValueError(f"{name} must be a boolean or null.")
    for name, allowed in FINANCE_EVIDENCE.items():
        evidence = record.get(name)
        if evidence is None:
            continue
        if not isinstance(evidence, dict) or set(evidence) - allowed:
            raise ValueError(f"Unsupported {name} metadata; nothing is silently dropped.")
        for key, value in evidence.items():
            if key == "scope":
                if value is not None and (
                    not isinstance(value, dict) or set(value) - set(SCOPE.values())
                    or any(not _text(item) for item in value.values())
                ):
                    raise ValueError("Finance evidence scope must contain only bounded canonical identities.")
            elif key == "coverage":
                if value not in (None, "complete", "partial", "unknown"):
                    raise ValueError("Unsupported finance evidence coverage.")
            elif not _text(value):
                raise ValueError("Finance evidence fields must be bounded text or null.")
    for numerator, denominator in (
        ("successful_requests", "requests"), ("completed_outcomes", "attempted_outcomes"),
        ("quality_passed_responses", "evaluated_responses"), ("active_users", "eligible_users"),
    ):
        if record.get(numerator) is not None and record.get(denominator) is not None:
            if record[numerator] > record[denominator]:
                raise ValueError(f"{numerator} exceeds {denominator}.")
    provenance = record.get("provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - set(COUNTS + NUMBERS + ("outcome_quality_passed",)):
        raise ValueError("Unsupported canonical provenance field.")
    for metadata in provenance.values():
        if not isinstance(metadata, dict) or set(metadata) - {"data_source", "reference", "description", "formula", "inputs"}:
            raise ValueError("Unsupported provenance metadata; nothing is silently dropped.")
        for key, value in metadata.items():
            if key == "inputs":
                if value is not None and not isinstance(value, dict):
                    raise ValueError("Provenance inputs must be an object or null.")
                _inputs(value)
            elif not _text(value):
                raise ValueError("Provenance text must be bounded.")
    scope = {}
    for native, canonical in SCOPE.items():
        value = record.get(canonical)
        value = value.strip() if isinstance(value, str) else None
        if value is not None and (not value or native != "agent" and value.casefold() in {"unknown", "unavailable", "n/a"}):
            value = None
        if value is not None and value.casefold() == "all":
            raise ValueError("All is a selector, never an observed identity.")
        scope[native] = value
    timestamp = _clean_text(record.get("timestamp")) or _clean_text(record.get("period_end"))
    try:
        if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Native publication requires an explicit timezone-aware timestamp or period_end; none is invented.") from None
    return scope, timestamp


def import_document(document, *, source, authorized_scopes=None):
    if (not isinstance(document, dict) or set(document) - {"contract", "source", "rows"}
            or document.get("contract") != CANONICAL or source not in ("sample", "live")):
        raise ValueError("Expected the canonical observation envelope and explicit sample/live mode.")
    if document.get("source") not in (None, source):
        raise ValueError("Sample envelope cannot be relabeled live.")
    records = document.get("rows")
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Canonical observations require at most 10,000 rows.")
    if source == "live" and authorized_scopes is None:
        raise ValueError("Live canonical imports require an explicit reviewed authorized scope manifest.")
    scopes, rows, occurrences = [], [], {}
    for record in records:
        scope, timestamp = validate_record(record, source)
        if scope not in scopes:
            scopes.append(scope)
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, allow_nan=False).encode()).hexdigest()[:32]
        ordinal = occurrences.get(digest, 0)
        occurrences[digest] = ordinal + 1
        rows.append({
            "id": f"{digest}-{ordinal}", "timestamp": timestamp, "scope": scope,
            "kind": "canonical", "dataSource": record.get("data_source") or "Supplied canonical evidence",
            "canonical": deepcopy(record),
        })
    return {"schema": SCHEMA, "source": source,
            "authorizedScopes": scopes if authorized_scopes is None else deepcopy(authorized_scopes), "rows": rows}


def selected(document, filters, native):
    if (document.get("schema") != SCHEMA or set(document) - {"schema", "source", "authorizedScopes", "rows"}
            or document.get("source") not in ("sample", "live")
            or not isinstance(document.get("rows"), list) or len(document["rows"]) > 10000
            or not isinstance(document.get("authorizedScopes"), list) or len(document["authorizedScopes"]) > 10000):
        raise ValueError("Invalid bounded v2 observation envelope.")
    def scope_key(scope):
        if not isinstance(scope, dict) or set(scope) != set(SCOPE):
            raise ValueError("An exact five-part authorized scope is required.")
        if any(not _text(value) or (isinstance(value, str) and (not value.strip() or value.casefold() == "all"))
               for value in scope.values()):
            raise ValueError("Invalid authorized scope identity.")
        return tuple(scope[key] for key in SCOPE)

    allowed = {scope_key(scope) for scope in document["authorizedScopes"]}
    seen, result = set(), []
    for row in document["rows"]:
        if (not isinstance(row, dict) or set(row) != {"id", "timestamp", "scope", "kind", "dataSource", "canonical"}
                or row["kind"] != "canonical" or not isinstance(row["id"], str)
                or not native.SCOPE_PATTERN.fullmatch(row["id"])):
            raise ValueError("Invalid native v2 canonical observation wrapper.")
        scope, timestamp = validate_record(row["canonical"], document["source"])
        if (row["scope"] != scope or row["timestamp"] != timestamp
                or row["dataSource"] != (row["canonical"].get("data_source") or "Supplied canonical evidence")):
            raise ValueError("Native wrapper scope/time must match its original canonical observation.")
        identity = (scope_key(scope), row["id"])
        if identity in seen:
            raise ValueError("Duplicate scoped native observation IDs are not summed.")
        seen.add(identity)
        if identity[0] in allowed and native.matches(scope, filters):
            result.append(row)
    return result


def _sum(records, field):
    return _native_sum([row.get(field) for row in records])


def _reference(record, field):
    value = record.get("provenance", {}).get(field, {}).get("reference")
    return isinstance(value, str) and bool(value.strip())


def _modeled(record):
    if record.get("outcome_quality_passed") is False or any(record.get(key) is None for key in VALUE_INPUTS):
        return None
    return (record["baseline_minutes_per_outcome"] - record["actual_minutes_per_outcome"]) * record["completed_outcomes"]


def _qualified(record):
    return record.get("outcome_quality_passed") is True and all(_reference(record, key) for key in VALUE_INPUTS)


def _native_modeled(record):
    value = _modeled(record)
    return value if all(_native_number(record.get(key)) for key in VALUE_INPUTS) and _native_number(value) else None


def qualification(records, metric=None):
    financial = metric in FINANCE_UNSUPPORTED
    if metric is not None and not financial and not metric.startswith(("modeled_", "qualified_")):
        return {"state": "not-applicable", "evidence_refs": [], "reason": "Not an outcome-value qualification metric."}
    monetary_capacity = metric == "qualified_capacity_value"
    required_inputs = VALUE_INPUTS + (("labor_rate_per_hour",) if monetary_capacity else ())
    qualified = sum(
        _qualified(row) and all(row.get(key) is not None for key in required_inputs)
        and (not monetary_capacity or _reference(row, "labor_rate_per_hour"))
        for row in records
    )
    references = {
        metadata["reference"].strip()
        for row in records for field, metadata in row.get("provenance", {}).items()
        if (financial or field in VALUE_INPUTS + ("labor_rate_per_hour", "outcome_quality_passed"))
        and isinstance(metadata.get("reference"), str) and metadata["reference"].strip()
    }
    if financial:
        for row in records:
            for name, keys in (("value_evidence", ("baseline_reference", "evidence_reference", "approval_reference")),
                               ("cost_evidence", ("reference",))):
                for key in keys:
                    value = (row.get(name) or {}).get(key)
                    if _clean_text(value):
                        references.add(value.strip())
    state = (
        "qualified" if records and qualified == len(records) else "partial" if qualified else
        "failed" if any(row.get("outcome_quality_passed") is False for row in records) else "not-provided")
    if financial and state == "qualified":
        state = "partial"
    return {
        "state": state, "evidence_refs": sorted(references),
        "reason": FINANCE_NOTICE if financial else
            "Qualified monetary capacity requires ALL visible rows to have qualified outcome inputs, labor_rate_per_hour and its provenance reference; currency agreement and native numeric-range support also constrain projection." if monetary_capacity else
            "Qualified aggregates require ALL visible rows; evidence counts do not imply financial verification or native numeric-range support.",
        "qualified_rows": qualified, "unqualified_rows": len(records) - qualified,
    }


def _cost_available(record, field, source):
    metadata = record.get("provenance", {}).get(field, {})
    if field == "token_estimated_cost":
        return (isinstance(metadata.get("formula"), str) and bool(metadata["formula"].strip())
                and isinstance(metadata.get("inputs"), dict) and bool(metadata["inputs"]))
    return _reference(record, field) and (source == "sample" or
        (_clean_text(metadata.get("data_source")) or _clean_text(record.get("data_source"))) == "Cost Management")


def summarize(records, source="live"):
    currencies = {_clean_text(row.get("currency")) for row in records}
    currency = next(iter(currencies)) if len(currencies) == 1 and None not in currencies else None
    result = {}
    for field in COUNTS + NUMBERS:
        if field in {"baseline_minutes_per_outcome", "actual_minutes_per_outcome", "labor_rate_per_hour"}:
            continue
        if field in FINANCE_UNSUPPORTED:
            result[field] = (None, FINANCE_NOTICE)
            continue
        value = _sum(records, field)
        if field in {"active_users", "eligible_users"} and len(records) != 1:
            value = None
        if field in MONEY and not currency:
            value = None
        if field in {"actual_cost", "amortized_cost", "token_estimated_cost"} and any(
            not _cost_available(row, field, source) for row in records
        ):
            value = None
        result[field] = (value, f"Complete-row sum of {field}; missing inputs are unavailable")
    for metric, numerator, denominator, factor in (
        ("success_rate", "successful_requests", "requests", 100),
        ("quality_pass_rate", "quality_passed_responses", "evaluated_responses", 100),
        ("mean_latency_ms", "latency_ms_sum", "latency_samples", 1),
        ("adoption_rate", "active_users", "eligible_users", 100),
    ):
        n, d = result[numerator][0], result[denominator][0]
        result[metric] = (factor * n / d if n is not None and d is not None and d > 0 else None,
                          f"{factor} * sum({numerator}) / sum({denominator}); adoption requires a single observation")
    modeled = [_native_modeled(row) for row in records]
    complete = bool(modeled) and all(value is not None for value in modeled)
    result["modeled_minutes_saved"] = (_native_sum(modeled) if complete else None,
                                      "sum((baseline_minutes_per_outcome - actual_minutes_per_outcome) * completed_outcomes); explicit false quality gate rejects modeled value")
    rates = [row.get("labor_rate_per_hour") for row in records]
    result["modeled_capacity_value"] = (
        _native_sum([value * rate / 60 for value, rate in zip(modeled, rates)])
        if complete and currency and all(_native_number(rate) for rate in rates) else None,
        "sum(modeled minutes / 60 * supplied labor rate); modeled capacity, not realized cash",
    )
    eligible = [row for row in records if _qualified(row) and _modeled(row) is not None]
    qualified_complete = bool(records) and len(eligible) == len(records) and complete
    result["qualified_minutes_saved"] = (
        _native_sum([_native_modeled(row) for row in eligible]) if qualified_complete else None,
        "sum(modeled minutes) only when ALL visible rows have explicit quality approval and completion/baseline/effort references",
    )
    result["qualified_hours_saved"] = (
        result["qualified_minutes_saved"][0] / 60 if result["qualified_minutes_saved"][0] is not None else None,
        "qualified_minutes_saved / 60; quality-qualified capacity, not verified cash",
    )
    result["qualified_outcomes"] = (
        _native_sum([row["completed_outcomes"] for row in eligible]) if qualified_complete else None,
        "sum(completed_outcomes) only when ALL visible rows are quality-passed with completion/baseline/effort references",
    )
    valued = [row for row in eligible if row.get("labor_rate_per_hour") is not None and _reference(row, "labor_rate_per_hour")]
    result["qualified_capacity_value"] = (
        _native_sum([_native_modeled(row) * row["labor_rate_per_hour"] / 60 for row in valued])
        if qualified_complete and len(valued) == len(records) and currency
        and all(_native_number(row["labor_rate_per_hour"]) for row in valued) else None,
        "qualified minutes / 60 * evidence-backed labor rate for ALL visible rows; qualified capacity, not realized cash",
    )
    for metric in FINANCE_UNSUPPORTED:
        result[metric] = (None, FINANCE_NOTICE)
    return result, currency, len(eligible), len(valued)


def metric_records(records, source):
    aggregate, currency, qualified, valued = summarize(records, source)
    totals = []
    for metric, (value, formula) in aggregate.items():
        unit = currency if metric in MONEY else UNITS.get(metric, "count")
        tier = "qualified-outcomes" if metric == "qualified_outcomes" else "qualified-capacity" if metric.startswith("qualified_") else (
            "modeled-time-saving" if metric.startswith("modeled_") else
            "verified-realized" if metric == "verified_realized_value" else
            "calculated" if metric in {"success_rate", "quality_pass_rate", "mean_latency_ms", "adoption_rate"} else "observed")
        available = valued if metric == "qualified_capacity_value" else qualified
        totals.append({
            "metric": metric, "value": value, "unit": unit,
            "value_class": "unavailable" if value is None else "modeled" if tier in {"modeled-time-saving", "qualified-capacity"} else "observed",
            "value_tier": tier,
            "cost_basis": {"actual_cost": "actual", "amortized_cost": "amortized", "token_estimated_cost": "estimated"}.get(metric),
            "estimate_type": "tokens" if metric == "token_estimated_cost" else None,
            "currency": currency if metric in MONEY else None,
            "qualification": qualification(records, metric),
            "evidence_requirements": FINANCE_NOTICE if metric in FINANCE_UNSUPPORTED else
                "All required inputs and projected totals must be within the native numeric range (absolute value <= 2^53-1); originals remain preserved.",
            "status": "unavailable" if value is None else "available",
            "availability_reason": None if value is not None else FINANCE_NOTICE if metric in FINANCE_UNSUPPORTED else
                "Missing required evidence, incomplete qualification, mixed currency, non-additive cohorts or unsupported native magnitude (absolute 2^53-1); no zero is inferred.",
            "observationCount": len(records),
            "availableCount": available if metric.startswith("qualified_") else len(records) if value is not None else 0,
            "formula": formula,
        })
    return totals, qualified


def build_report(document, filters, native):
    wrappers = selected(document, filters, native)
    records = [row["canonical"] for row in wrappers]
    totals, _ = metric_records(records, document["source"])
    rows, groups, projects = [], {}, []
    for wrapper in wrappers:
        groups.setdefault(tuple(wrapper["scope"][key] for key in SCOPE), []).append(wrapper)
    for group in groups.values():
        metrics, _ = metric_records([row["canonical"] for row in group], document["source"])
        sources = sorted({row["dataSource"] for row in group})
        projects.extend({**metric, "scope": deepcopy(group[0]["scope"]), "dataSource": sources} for metric in metrics)
    for wrapper in wrappers:
        record = wrapper["canonical"]
        for metric in COUNTS + NUMBERS:
            if metric not in record:
                continue
            metadata = record.get("provenance", {}).get(metric, {})
            kind = ("outcome" if metric == "realized_benefit_amount" else "cost" if metric in MONEY else "security" if metric.startswith("security_")
                    else "reliability" if metric in {"successful_requests", "latency_samples", "latency_ms_sum", "evaluated_responses", "quality_passed_responses"}
                    else "outcome" if metric in VALUE_INPUTS or metric in {"attempted_outcomes", "labor_rate_per_hour"}
                    else "usage")
            azure = {"subscriptionId": _clean_text(record.get("subscription_id")), "resourceGroup": _clean_text(record.get("resource_group")),
                     "resourceId": _clean_text(record.get("resource_id"))}
            link = native.cost_link(azure, wrapper["scope"]["project"], document["source"]) if record.get("metadata_validated") is True else None
            cost_scope = _clean_text(record.get("cost_scope"))
            if link and cost_scope and link["scope"].casefold() != cost_scope.casefold():
                group_link = native.cost_link({**azure, "resourceId": None}, wrapper["scope"]["project"], document["source"])
                link = group_link if group_link and group_link["scope"].casefold() == cost_scope.casefold() else None
            value = record[metric]
            if value is not None and not _native_number(value):
                value = None
            if metric in FINANCE_UNSUPPORTED:
                value = None
            if metric in {"actual_cost", "amortized_cost", "token_estimated_cost"} and (
                not _clean_text(record.get("currency")) or not _cost_available(record, metric, document["source"])
            ):
                value = None
            rows.append({
                "id": wrapper["id"] + "-" + metric, "scope": deepcopy(wrapper["scope"]),
                "kind": kind, "metric": metric, "timestamp": wrapper["timestamp"],
                "value": value, "unit": _clean_text(record.get("currency")) if metric in MONEY else UNITS.get(metric, "count"),
                "costBasis": {"actual_cost": "actual", "amortized_cost": "amortized", "token_estimated_cost": "estimate"}.get(metric),
                "cost_basis": {"actual_cost": "actual", "amortized_cost": "amortized", "token_estimated_cost": "estimated"}.get(metric),
                "estimate_type": "tokens" if metric == "token_estimated_cost" else None,
                "currency": _clean_text(record.get("currency")) if metric in MONEY else None,
                "value_class": "unavailable" if value is None else "observed",
                "qualification": qualification([record], metric),
                "status": "unavailable" if value is None else "available",
                "availability_reason": FINANCE_NOTICE if metric in FINANCE_UNSUPPORTED else
                    "Unsupported native magnitude (absolute 2^53-1); original input preserved." if record[metric] is not None and not _native_number(record[metric]) else
                    "Required value, currency or cost evidence unavailable." if value is None else None,
                "dataSource": metadata.get("data_source") or wrapper["dataSource"],
                "evidence": {"reference": metadata.get("reference")}, "drillthrough": link,
                "lineage": {"dataSource": metadata.get("data_source") or wrapper["dataSource"],
                            "formula": FINANCE_NOTICE if metric in FINANCE_UNSUPPORTED else metadata.get("formula") or "Supplied canonical observation; no inferred measurement",
                            "inputs": deepcopy(metadata.get("inputs")), "upstream": deepcopy(metadata)},
            })
    source = document["source"]
    families = {
        "agent-value": {"modeled_minutes_saved", "modeled_capacity_value", "qualified_minutes_saved", "qualified_hours_saved",
                        "qualified_outcomes", "qualified_capacity_value", "verified_realized_value",
                        "cost_per_accepted_outcome", "verified_net_value", "verified_roi_percent"},
        "showback": {"actual_cost", "amortized_cost", "token_estimated_cost"},
        "foundry-tokens": {"input_tokens", "output_tokens"},
        "foundry-usage": {"requests", "active_users", "eligible_users", "adoption_rate"},
        "quality-reliability": {"successful_requests", "success_rate", "mean_latency_ms", "quality_pass_rate"},
        "security-governance": {"security_checks", "security_findings"},
    }
    charts = [{
        "report_id": report_id, "title": report_id, "xAxis": "compound factory/scaleset/project/environment/agent identity",
        "points": [point for point in projects if point["metric"] in fields],
        "dataSource": sorted({row["dataSource"] for row in wrappers}),
        "status": "available" if any(point["value"] is not None for point in projects if point["metric"] in fields) else "unavailable",
    } for report_id, fields in families.items()]
    return {
        "schema": "aifactory.native-monitoring-report/v2", "inputSchema": SCHEMA, "source": source,
        "filters": filters, "collectionMode": "imported_observations", "supportedReportIds": list(REPORT_IDS),
        "scopeSemantics": "Five-part intersection over authorized supplied rows; native agent filter is additional to canonical API's four selectors.",
        "status": "available" if any(item["value"] is not None for item in totals) else "unavailable",
        "rows": rows, "totals": totals, "projects": projects, "charts": charts,
        "qualification": qualification(records),
        "warnings": [
            "Sample evidence; no Azure calls or live links." if source == "sample" else "Imported evidence only; no Azure collection or source attestation.",
            "Rows must be disjoint additive observations. Active-user adoption is not summed across rows.",
            "Actual, amortized and estimated costs are alternative bases; modeled/qualified capacity is not realized cash.",
            FINANCE_NOTICE,
            "Native projections outside absolute 2^53-1 are unavailable, never rounded or clamped; canonical originals up to absolute 1e100 remain losslessly exportable.",
            "Event files are local artifacts only; Azure ingestion size limits, storage fidelity, query execution and rendering have not been validated.",
        ],
        "lineage": {"formula": "Filter first; preserve original row grain on reverse export; complete-row sums and ratio-of-sums only.",
                    "inputs": "Selected canonical observation fields and per-field provenance"},
    }


def export_document(document, filters, native):
    return {"contract": CANONICAL, "source": document["source"],
            "rows": [deepcopy(row["canonical"]) for row in selected(document, filters, native)]}
