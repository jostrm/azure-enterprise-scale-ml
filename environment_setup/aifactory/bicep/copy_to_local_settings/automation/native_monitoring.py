"""Offline, evidence-backed native agent reports; never authenticates or writes to Azure."""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from urllib.parse import quote
import uuid


SCHEMA = "aifactory.agent-observations/v1"
REPORT_SCHEMA = "aifactory.native-monitoring-report/v1"
DIMENSIONS = ("aiFactory", "scaleset", "project", "environment", "agent")
ALL = {key: "All" for key in DIMENSIONS}
SCOPE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SCOPE_LABEL_PATTERN = re.compile(r"[^\x00-\x1f\x7f]{1,2048}")
RG_PATTERN = re.compile(r"[A-Za-z0-9_().-]{1,90}")
LIMIT = 8 * 1024 * 1024
CANONICAL_SCHEMA = "aifactory.monitoring-observations.v1"
SCHEMA_V2 = "aifactory.agent-observations/v2"
_V2 = None


def _v2():
    global _V2
    if _V2 is None:
        spec = importlib.util.spec_from_file_location(
            "aifactory_native_monitoring_v2", Path(__file__).with_name("native_monitoring_v2.py"))
        _V2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_V2)
    return _V2


def _v2_helpers():
    return SimpleNamespace(SCOPE_PATTERN=SCOPE_PATTERN, matches=matches, cost_link=cost_link)


def scope_key(scope):
    if not isinstance(scope, dict) or set(scope) != set(DIMENSIONS):
        raise ValueError("Every observation needs the complete five-part scope; unknown fields use null.")
    result = []
    for key in DIMENSIONS:
        value = scope[key]
        if value is not None and (not isinstance(value, str) or not value.strip() or not SCOPE_LABEL_PATTERN.fullmatch(value)
                                  or value.strip().casefold() in {"all", "unknown", "undefined", "null", "unavailable", "n/a"}):
            raise ValueError("Scope identifiers are strings, preserve leading zeros, and cannot be placeholders.")
        result.append(value)
    return tuple(result)


def selection(filters=None):
    filters = filters or {}
    if not isinstance(filters, dict) or set(filters) - set(DIMENSIONS):
        raise ValueError("Unsupported scope filter.")
    result = {**ALL, **filters}
    for value in result.values():
        if not isinstance(value, str) or not value.strip() or not SCOPE_LABEL_PATTERN.fullmatch(value):
            raise ValueError("Filters must be All or exact string identifiers.")
    return result


def matches(scope, filters):
    return all(selected.casefold() == "all" or scope[key] == selected for key, selected in filters.items())


def cost_link(azure, project, source):
    """Azure metadata must come from reviewed collection, never naming guesses or sample IDs."""
    if (source != "live" or not isinstance(azure, dict) or not isinstance(project, str)
            or not project.strip() or not SCOPE_LABEL_PATTERN.fullmatch(project) or project.strip().casefold() in {"all", "unknown", "undefined", "null", "unavailable", "n/a"}):
        return None
    try:
        subscription = str(uuid.UUID(azure["subscriptionId"]))
        if subscription == str(uuid.UUID(int=0)):
            return None
        group = azure["resourceGroup"]
        if not isinstance(group, str) or not RG_PATTERN.fullmatch(group) or group.endswith(".") or group.casefold() == "all":
            return None
        scope = f"/subscriptions/{subscription}/resourceGroups/{group}"
        resource = azure.get("resourceId")
        if resource:
            if not isinstance(resource, str) or not resource.casefold().startswith(scope.casefold() + "/providers/"):
                return None
            suffix = resource[len(scope):]
            if not re.fullmatch(r"/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9_.()-]+/[A-Za-z0-9_.()-]+)+", suffix):
                return None
            if any(segment in {".", ".."} for segment in suffix.split("/")):
                return None
            scope = resource
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return {
        "url": "https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/" + quote(scope, safe=""),
        "tooltip": f"Go to Azure Cost analysis for project {project}",
        "scope": scope,
    }


def _number(value, *, nonnegative=False):
    return type(value) in (int, float) and abs(value) <= 9007199254740991 and math.isfinite(value) and (not nonnegative or value >= 0)


def _evidence(row):
    value = row.get("evidence")
    return (isinstance(value, dict) and isinstance(value.get("reference"), str)
            and bool(value["reference"].strip()) and len(value["reference"]) <= 512)


def _summary(rows, field):
    values = [row[field] for row in rows if row.get(field) is not None]
    return sum(values) if values else None


def import_monitoring_observations(document, *, source, authorized_scopes=None, native_version=None):
    """Bridge the desktop/API flat contract without inferring provenance or quality approval."""
    if native_version not in (None, 1, 2):
        raise ValueError("Native observation version must be 1 or 2.")
    if isinstance(document, dict) and set(document) - {"contract", "source", "rows"}:
        raise ValueError("Unsupported canonical envelope field; nothing is silently dropped.")
    legacy_fields = {
        "factory", "scaleset", "project", "environment", "agent_id", "timestamp",
        "completed_outcomes", "baseline_minutes_per_outcome", "actual_minutes_per_outcome",
        "outcome_quality_passed", "actual_cost", "amortized_cost", "token_estimated_cost",
        "currency", "security_checks", "security_findings", "provenance", "data_source",
        "source", "metadata_validated", "subscription_id", "resource_group", "resource_id", "cost_scope",
    }
    needs_v2 = isinstance(document, dict) and isinstance(document.get("rows"), list) and any(
        isinstance(record, dict) and (
            set(record) - legacy_fields or
            isinstance(record.get("provenance"), dict) and set(record["provenance"]) - legacy_fields
        ) for record in document["rows"])
    if native_version == 1 and needs_v2:
        raise ValueError("Native v1 cannot represent these fields losslessly; select native version 2.")
    if native_version == 2 or needs_v2:
        result = _v2().import_document(document, source=source, authorized_scopes=authorized_scopes)
        build_report(result)
        return result
    if not isinstance(document, dict) or document.get("contract") != CANONICAL_SCHEMA or source not in {"sample", "live"}:
        raise ValueError("Canonical imports require monitoring-observations.v1 and explicit sample/live source.")
    if document.get("source") not in (None, source):
        raise ValueError("Explicit source must match the canonical document; sample provenance cannot be relabeled.")
    records = document.get("rows")
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Canonical imports require bounded observation rows.")
    if source == "live" and authorized_scopes is None:
        raise ValueError("Live canonical imports require a reviewed authorized scope manifest; no tenant access is inferred.")
    rows, scopes = [], []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Canonical observations must be objects.")
        if record.get("source") not in (None, source):
            raise ValueError("Explicit source must match every canonical row; sample provenance cannot be relabeled.")
        scope = {key: record.get({"aiFactory": "factory", "agent": "agent_id"}.get(key, key)) for key in DIMENSIONS}
        scope = {key: None if isinstance(value, str) and value.strip().casefold() in {"", "unknown", "undefined", "null", "unavailable", "n/a"} else value for key, value in scope.items()}
        scope_key(scope)
        if scope not in scopes:
            scopes.append(scope)
        identity = hashlib.sha256(json.dumps(record, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]
        provenance = record.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("Canonical field provenance must be an object.")

        def observation(kind, fields, values):
            provenance_fields = {"data_source", "reference", "description", "formula", "inputs"}
            upstream = {field: {key: deepcopy(value) for key, value in provenance[field].items() if key in provenance_fields}
                        for field in fields if isinstance(provenance.get(field), dict)}
            references = [entry["reference"] for entry in upstream.values() if isinstance(entry.get("reference"), str) and entry["reference"].strip()]
            sources = [entry["data_source"] for entry in upstream.values() if isinstance(entry.get("data_source"), str) and entry["data_source"]]
            row = {"id": identity + "-" + kind + "-" + fields[0], "timestamp": record.get("timestamp") or record.get("period_end"),
                   "scope": scope, "kind": kind, kind: {key: value for key, value in values.items() if value is not None},
                   "dataSource": "; ".join(dict.fromkeys(sources)) if sources else record.get("data_source") or "Unspecified collected source",
                   "provenance": upstream}
            if len(references) == len(fields):
                row["evidence"] = {"reference": references[0][:512]}
            if record.get("metadata_validated") is True:
                azure = {"subscriptionId": record.get("subscription_id"), "resourceGroup": record.get("resource_group")}
                if record.get("resource_id"):
                    azure["resourceId"] = record["resource_id"]
                link = cost_link(azure, scope["project"], source)
                supplied_scope = record.get("cost_scope")
                if link and supplied_scope:
                    group_scope = f"/subscriptions/{azure['subscriptionId']}/resourceGroups/{azure['resourceGroup']}"
                    if isinstance(supplied_scope, str) and supplied_scope.casefold() == group_scope.casefold():
                        azure.pop("resourceId", None)
                    elif not isinstance(supplied_scope, str) or supplied_scope.casefold() != link["scope"].casefold():
                        link = None
                if link:
                    row["azure"] = azure
                    row["metadata_validated"] = True
            rows.append(row)

        outcome_fields = ("completed_outcomes", "baseline_minutes_per_outcome", "actual_minutes_per_outcome")
        if any(field in record for field in outcome_fields):
            observation("outcome", outcome_fields, {
                "completed": record.get("completed_outcomes"), "baselineMinutes": record.get("baseline_minutes_per_outcome"),
                "actualMinutes": record.get("actual_minutes_per_outcome"), "qualityPassed": record.get("outcome_quality_passed"),
            })
        for field, basis in (("actual_cost", "actual"), ("amortized_cost", "amortized"), ("token_estimated_cost", "estimate")):
            if field in record:
                values = {"basis": basis, "amount": record[field], "currency": record.get("currency")}
                metadata = provenance.get(field, {})
                if basis == "estimate" and isinstance(metadata, dict):
                    values["estimateType"] = "tokens"
                    if isinstance(metadata.get("inputs"), dict):
                        values["inputs"] = deepcopy(metadata["inputs"])
                    if isinstance(metadata.get("formula"), str):
                        values["formula"] = metadata["formula"]
                observation("cost", (field,), values)
        if "security_checks" in record or "security_findings" in record:
            observation("security", ("security_checks", "security_findings"),
                        {"checks": record.get("security_checks"), "findings": record.get("security_findings")})
    result = {"schema": SCHEMA, "source": source, "authorizedScopes": scopes if authorized_scopes is None else authorized_scopes, "rows": rows}
    build_report(result)
    return result


def build_report(document, filters=None):
    if isinstance(document, dict) and document.get("schema") == SCHEMA_V2:
        return _v2().build_report(document, selection(filters), _v2_helpers())
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or document.get("source") not in {"sample", "live"}:
        raise ValueError("Expected the native agent-observations schema and explicit sample/live provenance.")
    if set(document) - {"schema", "source", "authorizedScopes", "rows"}:
        raise ValueError("Only metrics/evidence contract fields may be imported; raw prompts and responses are not accepted.")
    filters = selection(filters)
    authorized = document.get("authorizedScopes")
    rows = document.get("rows")
    if not isinstance(authorized, list) or not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("A bounded row collection and an explicit authorizedScopes manifest are required.")
    allowed = {scope_key(scope) for scope in authorized}
    selected, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not SCOPE_PATTERN.fullmatch(row["id"]):
            raise ValueError("Each observation needs a stable bounded id.")
        if set(row) - {"id", "timestamp", "scope", "kind", "dataSource", "evidence", "outcome", "cost", "security", "azure", "provenance", "metadata_validated"}:
            raise ValueError("Unsupported observation content; export metrics and evidence references only.")
        if "metadata_validated" in row and type(row["metadata_validated"]) is not bool:
            raise ValueError("metadata_validated must be an explicit collector assertion.")
        try:
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError()
        except (KeyError, AttributeError, TypeError, ValueError):
            raise ValueError("Observation timestamp must be ISO 8601 with a timezone.") from None
        for field in ("outcome", "cost", "security", "azure", "evidence", "provenance"):
            if field in row and not isinstance(row[field], dict):
                raise ValueError("Observation evidence, Azure metadata and measurements must be objects.")
        key = (scope_key(row.get("scope")), row["id"])
        if key in seen:
            raise ValueError("Duplicate scoped observation IDs are not summed.")
        seen.add(key)
        if key[0] not in allowed:
            continue
        if not matches(row["scope"], filters):
            continue
        if row.get("kind") not in {"outcome", "cost", "security"} or not isinstance(row.get("dataSource"), str) or not row["dataSource"].strip():
            raise ValueError("Collected rows require an explicit kind and dataSource.")
        selected.append(deepcopy(row))
    output, warnings = [], []
    for row in selected:
        scope = row["scope"]
        projected = {
            "id": row["id"], "scope": scope, "kind": row["kind"], "timestamp": row.get("timestamp"),
            "dataSource": row["dataSource"], "evidence": deepcopy(row.get("evidence")),
            "status": "no_data", "value": None, "unit": None, "costBasis": None,
            "drillthrough": cost_link(row.get("azure"), scope["project"], document["source"]) if row.get("metadata_validated") is True else None,
        }
        if row["kind"] == "outcome":
            values = row.get("outcome", {})
            projected["unit"] = "minutes saved"
            formula = "(baselineMinutes - actualMinutes) * completed; only evidence-backed, quality-passed outcomes"
            if (_evidence(row) and type(values.get("qualityPassed")) is bool and values["qualityPassed"]
                    and all(_number(values.get(key), nonnegative=True) for key in ("baselineMinutes", "actualMinutes", "completed"))):
                projected.update(value=(values["baselineMinutes"] - values["actualMinutes"]) * values["completed"],
                                 unit="minutes saved", status="observed")
            else:
                warnings.append("Business value unavailable without outcome evidence, baseline, actual duration, completion count and quality gate; token volumes are not value.")
        elif row["kind"] == "cost":
            values = row.get("cost", {})
            basis = values.get("basis")
            formula = "Sum collected amounts by currency and cost basis; actual, amortized and estimate are never added together"
            currency = values.get("currency")
            if basis in {"actual", "amortized", "estimate"}:
                projected["costBasis"] = basis
            if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency):
                projected["unit"] = currency
            valid = basis in {"actual", "amortized", "estimate"} and _number(values.get("amount")) and isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency)
            if basis in {"actual", "amortized"}:
                valid = valid and (row["dataSource"] == "Cost Management" or document["source"] == "sample") and _evidence(row)
            if basis == "estimate":
                valid = valid and isinstance(values.get("inputs"), dict) and bool(values["inputs"]) and isinstance(values.get("formula"), str) and bool(values["formula"].strip())
                formula = values.get("formula") or formula
            if valid:
                projected.update(value=values["amount"], unit=currency, costBasis=basis, status="observed" if basis != "estimate" else "calculated")
            else:
                warnings.append("Cost unavailable: billed costs need Cost Management evidence; estimates need supplied inputs/formula and currency.")
        else:
            values = row.get("security", {})
            projected["unit"] = "control passed"
            formula = "Count supplied evidence-backed passed/failed controls; no observation means unknown, not compliant"
            if (_evidence(row) and isinstance(values.get("control"), str)
                    and values["control"].strip() and type(values.get("passed")) is bool):
                projected.update(value=1 if values["passed"] else 0, unit="control passed", status="observed")
            elif "checks" in values or "findings" in values:
                projected["unit"] = "findings"
                formula = "Sum supplied evidence-backed findings; explicit check count is retained, not converted into fabricated individual control results"
                if _evidence(row) and all(_number(values.get(key), nonnegative=True) for key in ("checks", "findings")):
                    projected.update(value=values["findings"], status="observed")
        projected["lineage"] = {"dataSource": row["dataSource"], "formula": formula, "inputs": deepcopy(values),
                                "upstream": deepcopy(row.get("provenance", {}))}
        output.append(projected)
    groups = {}
    for row in output:
        group_key = (*scope_key(row["scope"]), row["kind"], row["unit"], row["costBasis"])
        group = groups.setdefault(group_key, {"scope": row["scope"], "kind": row["kind"], "unit": row["unit"],
                                               "costBasis": row["costBasis"], "rows": []})
        group["rows"].append(row)
    aggregates = []
    for group in groups.values():
        observations = group.pop("rows")
        links = {row["drillthrough"]["url"]: row["drillthrough"] for row in observations if row["drillthrough"]}
        available = sum(row["value"] is not None for row in observations)
        aggregates.append({**group, "value": _summary(observations, "value"),
                           "status": "no_data" if not available else "partial" if available < len(observations) else "available",
                           "observationCount": len(observations), "availableCount": sum(row["value"] is not None for row in observations),
                           "dataSource": sorted({row["dataSource"] for row in observations}),
                           "lineage": [row["lineage"] for row in observations],
                           "drillthrough": next(iter(links.values())) if len(links) == 1 else None})
    totals = {}
    for row in output:
        key = "|".join((row["kind"], row["costBasis"] or "", row["unit"] or "unavailable"))
        totals.setdefault(key, []).append(row)
    total_rows = [{"metric": key, "value": _summary(values, "value"), "availableCount": sum(row["value"] is not None for row in values),
                   "status": "no_data" if all(row["value"] is None for row in values) else "partial" if any(row["value"] is None for row in values) else "available",
                   "observationCount": len(values)} for key, values in totals.items()]
    charts = []
    for kind in ("outcome", "cost", "security"):
        points = [group for group in aggregates if group["kind"] == kind]
        charts.append({"title": {"outcome": "Business value — evidence-backed minutes saved", "cost": "Cost — distinct billing bases and currencies",
                                "security": "Security — recorded controls only"}[kind],
                       "dataSource": sorted({source for point in points for source in point["dataSource"]}) or ["No collected observations"],
                       "lineage": [item for point in points for item in point["lineage"]],
                       "xAxis": "project (compound factory/scaleset/project/environment/agent identity)", "points": points,
                       "status": "no_data" if not any(point["value"] is not None for point in points) else
                                 "partial" if any(point["status"] != "available" for point in points) else "available"})
    return {"schema": REPORT_SCHEMA, "inputSchema": SCHEMA, "source": document["source"], "filters": filters, "collectionMode": "imported_observations",
            "scopeSemantics": "Intersection before aggregation; All means all authorized collected scope, not all tenant resources.",
            "status": "no_data" if not any(row["value"] is not None for row in output) else
                      "partial" if any(row["value"] is None for row in output) else "available",
            "warnings": sorted(set(warnings + (["SAMPLE DATA ONLY; no Azure cost links."] if document["source"] == "sample" else
                                                ["No Azure API query was performed; provenance comes from the reviewed collection artifact."]))),
            "rows": output, "totals": total_rows, "projects": aggregates, "charts": charts,
            "lineage": {"inputs": "Filtered evidence-backed observation rows below; no inferred prices or outcomes",
                        "formula": "Filter authorized rows by the intersection of all five selectors before any aggregation"}}


def app_events(document, filters=None):
    """Prepare events for an approved existing telemetry publisher; never ingest them here."""
    if document.get("schema") == SCHEMA_V2:
        return [{"name": "aifactory.agent.observation", "timestamp": row["timestamp"],
                 "properties": {"observation": json.dumps(
                     {**row, "schema": SCHEMA_V2, "source": document["source"]}, allow_nan=False)}}
                for row in _v2().selected(document, selection(filters), _v2_helpers())]
    report = build_report(document, filters)
    included = {(scope_key(row["scope"]), row["id"]) for row in report["rows"]}
    return [{"name": "aifactory.agent.observation", "timestamp": row["timestamp"],
             "properties": {"observation": json.dumps({**row, "schema": SCHEMA, "source": document["source"]}, allow_nan=False)}}
            for row in document["rows"] if (scope_key(row["scope"]), row["id"]) in included]


def export_monitoring_observations(document, filters=None):
    """Pivot complementary measurements at an exact grain into the canonical input."""
    if document.get("schema") == SCHEMA_V2:
        return _v2().export_document(document, selection(filters), _v2_helpers())
    report = build_report(document, filters)
    originals = {(scope_key(row["scope"]), row["id"]): row for row in document["rows"]}
    groups = {}
    for projected in report["rows"]:
        row = originals[(scope_key(projected["scope"]), projected["id"])]
        key = (*scope_key(row["scope"]), row["timestamp"])
        state = groups.setdefault(key, {"record": {
            **{("factory" if name == "aiFactory" else "agent_id" if name == "agent" else name): value
              for name, value in row["scope"].items()},
            "timestamp": row["timestamp"], "source": document["source"],
            "metadata_validated": False, "provenance": {},
        }, "sources": [], "metadata": None})
        record, values = state["record"], row.get(row["kind"], {})
        state["sources"].append(row["dataSource"])
        if row["kind"] == "outcome":
            eligible = projected["value"] is not None
            mapped = {field: values.get(native_field) if eligible else None for field, native_field in (
               ("completed_outcomes", "completed"), ("baseline_minutes_per_outcome", "baselineMinutes"),
               ("actual_minutes_per_outcome", "actualMinutes"))}
            mapped["outcome_quality_passed"] = values.get("qualityPassed") if type(values.get("qualityPassed")) is bool else None
            inputs = {name: values.get(name) for name in ("completed", "baselineMinutes", "actualMinutes", "qualityPassed")}
            formulas = dict(zip(mapped, ("native.outcome.completed (evidence/quality gate required)",
                "native.outcome.baselineMinutes (evidence/quality gate required)",
                "native.outcome.actualMinutes (evidence/quality gate required)", "native.outcome.qualityPassed (explicit boolean)")))
        elif row["kind"] == "cost":
            if values.get("basis") == "estimate" and values.get("estimateType") != "tokens":
                raise ValueError("Canonical export cannot label a generic estimate as token cost; token_estimated_cost requires explicit estimateType=tokens.")
            field = {"actual": "actual_cost", "amortized": "amortized_cost", "estimate": "token_estimated_cost"}.get(values.get("basis"))
            if field is None:
               raise ValueError("Canonical export requires a recognized cost basis.")
            mapped = {field: projected["value"]}
            currency = projected["unit"]
            if currency and "currency" in record and record["currency"] != currency:
               raise ValueError("Canonical export cannot combine different currencies at the same grain.")
            if currency:
               record["currency"] = currency
            inputs = (deepcopy(values.get("inputs", {})) if field == "token_estimated_cost" else
                     {name: values.get(name) for name in ("basis", "amount", "currency")})
            formulas = {field: values.get("formula") if field == "token_estimated_cost" else f"native.cost.amount (basis={values['basis']}; no conversion)"}
        else:
            is_control = projected["unit"] == "control passed"
            mapped = {"security_checks": 1 if is_control and projected["value"] is not None else
                     values.get("checks") if _evidence(row) and _number(values.get("checks"), nonnegative=True) else None,
                     "security_findings": None if is_control else
                     values.get("findings") if _evidence(row) and _number(values.get("findings"), nonnegative=True) else None}
            inputs = {name: values.get(name) for name in ("control", "passed", "checks", "findings") if name in values}
            formulas = {"security_checks": "count supplied control observations = 1" if is_control else "native.security.checks",
                        "security_findings": "Unavailable: control pass/fail is not a findings count" if is_control else "native.security.findings"}
        for field, value in mapped.items():
            if field in record:
               raise ValueError(f"Canonical export has overlapping {field} at one scope/timestamp; preaggregate disjoint inputs explicitly.")
            if value is not None and field in {"completed_outcomes", "security_checks", "security_findings"} and int(value) != value:
               raise ValueError("Canonical observation counts must be whole numbers; no rounding is inferred.")
            if field == "token_estimated_cost" and value is not None and value < 0:
               raise ValueError("Canonical token estimates cannot contain negative billing adjustments.")
            record[field] = value
            upstream = row.get("provenance", {}).get(field, {})
            metadata = {name: deepcopy(upstream.get(name)) for name in ("data_source", "reference", "description", "formula", "inputs")} if isinstance(upstream, dict) else {}
            metadata["data_source"] = metadata.get("data_source") or row["dataSource"]
            metadata["reference"] = metadata.get("reference") or (row.get("evidence", {}).get("reference") if _evidence(row) else None)
            metadata["description"] = metadata.get("description") or (
               f"Native observation {row['id']}; {projected['status']}. "
               "Missing measurements remain null; control pass/fail is not a findings count.")
            metadata["formula"] = metadata.get("formula") or formulas[field]
            if not isinstance(metadata["formula"], str) or not metadata["formula"].strip():
                metadata["formula"] = None
            metadata["inputs"] = metadata.get("inputs") or deepcopy(inputs)
            record["provenance"][field] = metadata
        link = cost_link(row.get("azure"), row["scope"]["project"], document["source"])
        if row.get("metadata_validated") is True and link:
            azure = row["azure"]
            metadata = {"subscription_id": azure["subscriptionId"], "resource_group": azure["resourceGroup"],
                       "resource_id": azure.get("resourceId"), "cost_scope": link["scope"], "metadata_validated": True}
            if state["metadata"] is not None and state["metadata"] != metadata:
               raise ValueError("Canonical export cannot merge conflicting validated Azure scopes.")
            state["metadata"] = metadata
            record.update(metadata)
    for state in groups.values():
        state["record"]["data_source"] = "; ".join(dict.fromkeys(state["sources"]))
    return {"contract": CANONICAL_SCHEMA, "source": document["source"], "rows": [state["record"] for state in groups.values()]}


def export_csv(report, path):
    """Export the exact same filtered rows, including provenance and formula inputs."""
    def literal(value):
        if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
            return "'" + value
        return value

    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([*DIMENSIONS, "id", "kind", "metric", "value", "unit", "costBasis", "source", "status", "dataSource", "formula", "inputs", "upstream", "evidence", "costAnalysisUrl"])
        for row in report["rows"]:
            cells = [*(row["scope"][key] for key in DIMENSIONS), row["id"], row["kind"], row.get("metric", ""), row["value"], row["unit"],
                     row["costBasis"], report["source"], row["status"], row["dataSource"], row["lineage"]["formula"],
                     json.dumps(row["lineage"]["inputs"]), json.dumps(row["lineage"]["upstream"]), json.dumps(row["evidence"]),
                     row["drillthrough"]["url"] if row["drillthrough"] else ""]
            writer.writerow([literal(value) for value in cells])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Reviewed, already-collected observation JSON; no live collection is performed.")
    parser.add_argument("--output", help="Local JSON output, otherwise stdout.")
    parser.add_argument("--csv", help="Optional CSV with identical filtered rows and lineage.")
    parser.add_argument("--events", help="Prepare local AppEvents JSON for a separately approved publisher; never uploads.")
    parser.add_argument("--observations-output", help="Export filtered canonical monitoring-observations.v1 rows for the desktop/API.")
    parser.add_argument("--native-output", help="Save the filtered native evidence envelope locally; never publishes or ingests.")
    parser.add_argument("--source", choices=("sample", "live"), help="Required for canonical monitoring-observations.v1 imports; never inferred.")
    parser.add_argument("--native-version", type=int, choices=(1, 2),
                        help="Canonical import target. Default retains v1 for legacy-compatible inputs, otherwise selects v2. Select 2 for lossless original row grain.")
    parser.add_argument("--authorized-scopes", help="Reviewed JSON array of native five-part scopes; required for live canonical imports.")
    for name in DIMENSIONS:
        parser.add_argument("--" + name, default="All")
    args = parser.parse_args(argv)
    with Path(args.input).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        parser.error("Input exceeds 8 MiB.")
    try:
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("Observation input must be a JSON object.")
        if document.get("contract") == CANONICAL_SCHEMA:
            scopes = None
            if args.authorized_scopes:
                with Path(args.authorized_scopes).open("rb") as stream:
                    scope_bytes = stream.read(LIMIT + 1)
                if len(scope_bytes) > LIMIT:
                    raise ValueError("Authorized scope manifest exceeds 8 MiB.")
                scopes = json.loads(scope_bytes)
            document = import_monitoring_observations(document, source=args.source, authorized_scopes=scopes,
                                                     native_version=args.native_version)
        elif args.source and args.source != document.get("source"):
            raise ValueError("Explicit source must match the input document; sample provenance cannot be relabeled.")
        filters = {key: getattr(args, key) for key in DIMENSIONS}
        report = build_report(document, filters)
        observations = export_monitoring_observations(document, filters) if args.observations_output else None
    except (ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    text = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.csv:
        export_csv(report, args.csv)
    if args.events:
        Path(args.events).write_text(json.dumps(app_events(document, filters), indent=2, allow_nan=False), encoding="utf-8")
    if args.observations_output:
        Path(args.observations_output).write_text(json.dumps(observations, indent=2, allow_nan=False), encoding="utf-8")
    if args.native_output:
        if document["schema"] == SCHEMA_V2:
            filtered = _v2().selected(document, filters, _v2_helpers())
        else:
            included = {(scope_key(row["scope"]), row["id"]) for row in report["rows"]}
            filtered = [row for row in document["rows"] if (scope_key(row["scope"]), row["id"]) in included]
        Path(args.native_output).write_text(json.dumps({**document, "rows": filtered}, indent=2, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
