from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

import native_monitoring as native


ROOT = Path(__file__).resolve().parent


@pytest.fixture
def evidence():
    document = json.loads((ROOT / "samples" / "monitoring-observations.sample.json").read_text())
    row = document["rows"][0]
    row.update(requests=100, successful_requests=90, input_tokens=1200, output_tokens=300,
               attempted_outcomes=12, latency_samples=100, latency_ms_sum=12000,
               evaluated_responses=20, quality_passed_responses=18, active_users=4,
               eligible_users=10, labor_rate_per_hour=60, model="model-a", agent_name="Claims",
               period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z")
    row["provenance"]["labor_rate_per_hour"] = {"data_source": "Approved valuation", "reference": "reviewed-rate"}
    document["rows"] = [row]
    return document


def converted(evidence):
    return native.import_monitoring_observations(evidence, source="sample", native_version=2)


def test_lossless_original_rows_nulls_grain_and_provenance(evidence):
    second = deepcopy(evidence["rows"][0])
    second["model"] = "model-b"
    second["input_tokens"] = None
    evidence["rows"].append(second)
    document = converted(evidence)
    assert document["schema"] == native.SCHEMA_V2
    assert len(document["rows"]) == 2
    assert native.export_monitoring_observations(document) == evidence
    report = native.build_report(document)
    totals = {row["metric"]: row["value"] for row in report["totals"]}
    assert totals["requests"] == 200
    assert totals["input_tokens"] is None
    assert totals["adoption_rate"] is None
    assert report["supportedReportIds"] == list(native._v2().REPORT_IDS)


def test_ratio_of_sums_and_distinct_value_tiers(evidence):
    report = native.build_report(converted(evidence))
    totals = {row["metric"]: row["value"] for row in report["totals"]}
    assert totals["mean_latency_ms"] == 120
    assert totals["success_rate"] == 90
    assert totals["quality_pass_rate"] == 90
    assert totals["adoption_rate"] == 40
    assert totals["modeled_minutes_saved"] == totals["qualified_minutes_saved"] == 90
    assert totals["modeled_capacity_value"] == totals["qualified_capacity_value"] == 90
    assert totals["verified_realized_value"] is None
    evidence["rows"][0]["outcome_quality_passed"] = None
    totals = {row["metric"]: row["value"] for row in native.build_report(converted(evidence))["totals"]}
    assert totals["modeled_minutes_saved"] == 90
    assert totals["qualified_minutes_saved"] is None
    evidence["rows"][0]["outcome_quality_passed"] = False
    assert next(row for row in native.build_report(converted(evidence))["totals"]
                if row["metric"] == "modeled_minutes_saved")["value"] is None


@pytest.mark.parametrize("missing", ["rate", "reference"])
@pytest.mark.parametrize("missing_count", [1, 2])
def test_qualified_capacity_metadata_requires_every_labor_rate_and_reference(evidence, missing, missing_count):
    evidence["rows"].append(deepcopy(evidence["rows"][0]))
    for row in evidence["rows"][:missing_count]:
        if missing == "rate":
            row.pop("labor_rate_per_hour")
        else:
            row["provenance"].pop("labor_rate_per_hour")
    report = native.build_report(converted(evidence))
    metrics = {item["metric"]: item for item in report["totals"]}
    capacity = metrics["qualified_capacity_value"]
    assert capacity["value"] is None and capacity["status"] == "unavailable"
    assert capacity["availableCount"] == 2 - missing_count
    assert capacity["qualification"]["state"] == ("partial" if missing_count == 1 else "not-provided")
    assert capacity["qualification"]["qualified_rows"] == 2 - missing_count
    assert capacity["qualification"]["unqualified_rows"] == missing_count
    assert "labor_rate_per_hour and its provenance reference" in capacity["qualification"]["reason"]
    assert metrics["qualified_hours_saved"]["value"] == 3
    assert metrics["qualified_hours_saved"]["qualification"]["state"] == "qualified"
    assert metrics["qualified_hours_saved"]["qualification"]["qualified_rows"] == 2
    assert metrics["modeled_capacity_value"]["value"] == (180 if missing == "reference" else None)
    assert native.export_monitoring_observations(converted(evidence)) == evidence


def test_authorized_compound_filter_export_and_events_are_same_rows(evidence):
    second = deepcopy(evidence["rows"][0])
    second["factory"] = "factory-b"
    evidence["rows"].append(second)
    document = converted(evidence)
    filters = {"aiFactory": "factory-a", "scaleset": "001", "project": "001"}
    exported = native.export_monitoring_observations(document, filters)
    assert exported["rows"] == evidence["rows"][:1]
    events = native.app_events(document, filters)
    assert len(events) == 1
    event = json.loads(events[0]["properties"]["observation"])
    assert event["source"] == "sample" and event["schema"] == native.SCHEMA_V2
    assert event["canonical"] == evidence["rows"][0]
    assert all(row["drillthrough"] is None for row in native.build_report(document, filters)["rows"])


@pytest.mark.parametrize("extra", [{"prompt": "not accepted"}, {"latency_p95": 80}, {"tenant_id": "unknown"}, {"deployment": "not canonical"}])
def test_unknown_fields_fail_instead_of_lossy_import(evidence, extra):
    evidence["rows"][0].update(extra)
    with pytest.raises(ValueError, match="recognized canonical"):
        converted(evidence)


def test_legacy_version_cannot_drop_usage_and_v2_auto_selects(evidence):
    with pytest.raises(ValueError, match="losslessly"):
        native.import_monitoring_observations(evidence, source="sample", native_version=1)
    assert native.import_monitoring_observations(evidence, source="sample")["schema"] == native.SCHEMA_V2


def test_currency_cost_evidence_and_null_denominators(evidence):
    evidence["rows"][0]["latency_samples"] = 0
    evidence["rows"][0]["provenance"].pop("actual_cost")
    report = native.build_report(converted(evidence))
    totals = {row["metric"]: row["value"] for row in report["totals"]}
    assert totals["mean_latency_ms"] is None and totals["actual_cost"] is None
    assert totals["amortized_cost"] == 18
    assert native.export_monitoring_observations(converted(evidence))["rows"][0]["actual_cost"] == 20


def test_source_scope_tamper_duplicates_and_private_metadata_rejected(evidence):
    document = converted(evidence)
    with pytest.raises(ValueError, match="relabeled"):
        native.import_monitoring_observations(evidence, source="live", authorized_scopes=[], native_version=2)
    document["rows"][0]["scope"]["project"] = "002"
    with pytest.raises(ValueError, match="must match"):
        native.build_report(document)
    document = converted(evidence)
    document["rows"].append(deepcopy(document["rows"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        native.build_report(document)
    evidence["rows"][0]["provenance"]["requests"] = {"inputs": {"api_key": "forbidden"}}
    with pytest.raises(ValueError, match="credential"):
        converted(evidence)


def test_large_canonical_counts_are_preserved_not_rounded(evidence):
    evidence["rows"][0]["input_tokens"] = 10**40 + 1
    document = converted(evidence)
    assert native.export_monitoring_observations(document) == evidence
    total = next(item for item in native.build_report(document)["totals"] if item["metric"] == "input_tokens")
    assert total["value"] is None and total["status"] == "unavailable"
    assert total["qualification"]["state"] == "not-applicable"
    assert "2^53-1" in total["availability_reason"]


def test_isolated_cli_explicit_v2_stdout_no_outputs():
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(ROOT / "native_monitoring.py"), "--input",
         str(ROOT / "samples" / "monitoring-observations.sample.json"), "--source", "sample", "--native-version", "2",
         "--aiFactory", "factory-a", "--scaleset", "001", "--project", "001"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["inputSchema"] == native.SCHEMA_V2
    assert report["source"] == "sample"
    assert all(row["scope"]["project"] == "001" for row in report["rows"])


def test_checked_in_six_report_sample_and_partial_qualification():
    fixture = json.loads((ROOT / "samples" / "monitoring-observations.six-reports.sample.json").read_text())
    document = converted(fixture)
    report = native.build_report(document)
    totals = {row["metric"]: row for row in report["totals"]}
    assert totals["requests"]["value"] == 150
    assert totals["mean_latency_ms"]["value"] == 130
    assert totals["modeled_minutes_saved"]["value"] == 110
    assert totals["qualified_minutes_saved"]["value"] is None
    assert totals["qualified_minutes_saved"]["status"] == "unavailable"
    assert totals["qualified_hours_saved"]["value"] is None
    assert totals["qualified_outcomes"]["value"] is None
    assert totals["actual_cost"]["value"] == 27
    assert totals["amortized_cost"]["value"] == 24
    assert totals["token_estimated_cost"]["value"] == 4
    assert totals["adoption_rate"]["value"] is None
    assert report["qualification"]["state"] == "partial"
    assert report["qualification"]["evidence_refs"]
    assert len(report["charts"]) == 6 and all(chart["status"] == "available" for chart in report["charts"])
    assert native.export_monitoring_observations(document) == fixture
    scoped = native.build_report(document, {"aiFactory": "factory-a", "project": "001"})
    assert next(row["value"] for row in scoped["totals"] if row["metric"] == "requests") == 100
    assert scoped["qualification"]["state"] == "qualified"


@pytest.mark.parametrize("field,value", [
    ("requests", True), ("requests", 1.5), ("requests", -1), ("actual_cost", float("nan")),
    ("latency_ms_sum", float("inf")), ("successful_requests", 101), ("metadata_validated", "true"),
    ("factory", 1), ("project", "All"), ("model", "bad\ntext"),
])
def test_invalid_observations_are_not_published(evidence, field, value):
    evidence["rows"][0][field] = value
    with pytest.raises(ValueError):
        converted(evidence)


def test_live_evidence_needs_reviewed_scopes_and_exact_cost_metadata(evidence):
    evidence["source"] = "live"
    row = evidence["rows"][0]
    row["source"] = "live"
    row.update(subscription_id="11111111-2222-4333-8444-555555555555",
               resource_group="reviewed-project", metadata_validated=True)
    group = f"/subscriptions/{row['subscription_id']}/resourceGroups/{row['resource_group']}"
    row["resource_id"] = group + "/providers/Microsoft.CognitiveServices/accounts/reviewed"
    row["cost_scope"] = group
    row["provenance"]["actual_cost"]["data_source"] = "Cost Management"
    row["provenance"]["amortized_cost"]["data_source"] = "Not billing"
    with pytest.raises(ValueError, match="manifest"):
        native.import_monitoring_observations(evidence, source="live", native_version=2)
    scope = {"aiFactory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev", "agent": row.get("agent_id")}
    document = native.import_monitoring_observations(evidence, source="live", native_version=2, authorized_scopes=[scope])
    report = native.build_report(document)
    costs = {item["metric"]: item for item in report["rows"] if item["kind"] == "cost"}
    assert costs["actual_cost"]["value"] == 20
    assert costs["amortized_cost"]["value"] is None
    assert costs["actual_cost"]["drillthrough"]["scope"] == group
    assert native.build_report({**document, "authorizedScopes": []})["rows"] == []
    document["rows"][0]["canonical"]["cost_scope"] = group + "-other"
    assert all(item["drillthrough"] is None for item in native.build_report(document)["rows"])


def test_currency_normalization_does_not_rewrite_original_evidence(evidence):
    row = evidence["rows"][0]
    row["currency"] = " USD "
    second = deepcopy(row)
    second["currency"] = "USD"
    evidence["rows"].append(second)
    report = native.build_report(converted(evidence))
    assert next(item["value"] for item in report["totals"] if item["metric"] == "actual_cost") == 40
    assert native.export_monitoring_observations(converted(evidence)) == evidence
    second["currency"] = "EUR"
    assert all(item["value"] is None for item in native.build_report(converted(evidence))["totals"]
               if item["metric"] in native._v2().MONEY)
    evidence["rows"] = [row]
    row["currency"] = " "
    report = native.build_report(converted(evidence))
    assert all(item["value"] is None for item in report["rows"] if item["kind"] == "cost")
    assert next(item["value_class"] for item in report["totals"] if item["metric"] == "mean_latency_ms") == "observed"


def test_schema_whitelist_matches_lossless_runtime_and_requires_timestamp(evidence):
    schema = json.loads((ROOT / "agent-observations.v2.schema.json").read_text())
    assert set(schema["$defs"]["canonical"]["properties"]) == native._v2().FIELDS
    assert schema["$defs"]["row"]["properties"]["kind"] == {"const": "canonical"}
    assert set(schema["$defs"]["provenance"]["propertyNames"]["enum"]) == set(
        native._v2().COUNTS + native._v2().NUMBERS + ("outcome_quality_passed",))
    assert set(schema["$defs"]["valueEvidence"]["properties"]) == native._v2().FINANCE_EVIDENCE["value_evidence"]
    assert set(schema["$defs"]["costEvidence"]["properties"]) == native._v2().FINANCE_EVIDENCE["cost_evidence"]
    evidence["rows"][0].pop("timestamp")
    evidence["rows"][0].pop("period_end")
    with pytest.raises(ValueError, match="timezone-aware"):
        converted(evidence)


def test_powershell_v2_wrapper_prepares_identical_local_outputs(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell not installed")
    canonical = tmp_path / "canonical.json"
    wrapped = tmp_path / "native.json"
    events = tmp_path / "events.json"
    result = subprocess.run([
        pwsh, "-NoProfile", "-File", str(ROOT / "coreteam" / "finops" / "runbooks" / "Update-AgentMonitoringReport.ps1"),
        "-ObservationsPath", str(ROOT / "samples" / "monitoring-observations.six-reports.sample.json"),
        "-Source", "Sample", "-NativeVersion", "2", "-AiFactory", "factory-a",
        "-CanonicalObservationsPath", str(canonical), "-NativeObservationsPath", str(wrapped),
        "-EventsPath", str(events),
    ], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    document = json.loads(wrapped.read_text())
    assert document["schema"] == native.SCHEMA_V2 and len(document["rows"]) == 1
    assert native.export_monitoring_observations(document) == json.loads(canonical.read_text())
    assert len(json.loads(events.read_text())) == 1


def test_additive_finance_evidence_is_lossless_but_never_native_verified(evidence):
    row = evidence["rows"][0]
    scope = {key: row.get(key) for key in ("factory", "scaleset", "project", "environment", "agent_id")}
    row["realized_benefit_amount"] = 250
    row["value_evidence"] = {
        "owner": "Sample finance owner", "baseline_reference": "sample-baseline",
        "period_start": row["period_start"], "period_end": row["period_end"],
        "valuation_method": "Observed revenue", "evidence_reference": "sample-ledger",
        "approval_reference": "sample-approval", "currency": row["currency"], "scope": scope,
    }
    row["cost_evidence"] = {
        "period_start": row["period_start"], "period_end": row["period_end"],
        "currency": row["currency"], "scope": scope, "coverage": "complete", "reference": "sample-cost-export",
    }
    row["provenance"]["realized_benefit_amount"] = {"reference": "sample-ledger", "data_source": "Synthetic finance"}
    document = converted(evidence)
    assert native.export_monitoring_observations(document) == evidence
    assert json.loads(native.app_events(document)[0]["properties"]["observation"])["canonical"] == row
    report = native.build_report(document)
    totals = {item["metric"]: item for item in report["totals"]}
    for metric in native._v2().FINANCE_UNSUPPORTED:
        assert totals[metric]["value"] is None
        assert totals[metric]["status"] == "unavailable"
        assert totals[metric]["value_class"] == "unavailable"
        assert totals[metric]["qualification"]["state"] == "partial"
        assert "financial projection unsupported in native v2; evidence preserved" in totals[metric]["qualification"]["reason"]
        assert "sample-approval" in totals[metric]["qualification"]["evidence_refs"]
    assert totals["qualified_capacity_value"]["value_class"] == "modeled"
    assert totals["qualified_outcomes"]["value_class"] == "observed"
    assert totals["qualified_hours_saved"]["value"] == 1.5
    assert totals["token_estimated_cost"]["cost_basis"] == "estimated"
    assert totals["token_estimated_cost"]["estimate_type"] == "tokens"
    projected = next(item for item in report["rows"] if item["metric"] == "realized_benefit_amount")
    assert projected["status"] == "unavailable" and projected["value"] is None
    row["value_evidence"] = {"approval_reference": None}
    row["cost_evidence"] = {"coverage": "partial"}
    assert native.export_monitoring_observations(converted(evidence)) == evidence
    for gate, state in ((False, "failed"), (None, "not-provided")):
        row["outcome_quality_passed"] = gate
        report = native.build_report(converted(evidence))
        assert all(item["qualification"]["state"] == state for item in report["totals"]
                   if item["metric"] in native._v2().FINANCE_UNSUPPORTED)


@pytest.mark.parametrize("name,value", [
    ("realized_benefit_amount", -1),
    ("value_evidence", {"secret": "not accepted"}),
    ("value_evidence", {"scope": {"project": 1}}),
    ("value_evidence", {"owner": ["not text"]}),
    ("cost_evidence", {"coverage": "guessed"}),
])
def test_finance_extension_rejects_unrecognized_or_invalid_content(evidence, name, value):
    evidence["rows"][0][name] = value
    with pytest.raises(ValueError):
        converted(evidence)


def test_consumers_can_import_bridge_by_path_without_global_module_registration(evidence):
    spec = importlib.util.spec_from_file_location("isolated_consumer_native_bridge", ROOT / "native_monitoring.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    assert spec.name not in sys.modules
    document = bridge.import_monitoring_observations(evidence, source="sample", native_version=2)
    assert bridge.export_monitoring_observations(document) == evidence
    assert len(bridge.app_events(document)) == 1


@pytest.mark.parametrize("agent", [None, "unknown", "n/a", " reviewed agent "])
def test_optional_agent_text_is_not_a_four_dimension_placeholder(evidence, agent):
    row = evidence["rows"][0]
    row["agent_id"] = agent
    row["timestamp"] = None
    document = converted(evidence)
    assert document["rows"][0]["scope"]["agent"] == (agent.strip() if agent is not None else None)
    assert document["rows"][0]["timestamp"] == row["period_end"]
    assert native.export_monitoring_observations(document) == evidence
    row.pop("agent_id")
    row.pop("timestamp")
    document = converted(evidence)
    assert document["rows"][0]["scope"]["agent"] is None
    assert native.export_monitoring_observations(document) == evidence


def test_identical_raw_rows_keep_distinct_occurrence_grain(evidence):
    evidence["rows"].append(deepcopy(evidence["rows"][0]))
    document = converted(evidence)
    assert len({row["id"] for row in document["rows"]}) == 2
    assert native.export_monitoring_observations(document) == evidence
    assert next(row["value"] for row in native.build_report(document)["totals"] if row["metric"] == "requests") == 200


def test_native_projection_rejects_intermediate_and_total_overflow_without_losing_inputs(evidence):
    row = evidence["rows"][0]
    row["baseline_minutes_per_outcome"] = native._v2().NATIVE_MAX
    row["completed_outcomes"] = row["attempted_outcomes"] = 2
    document = converted(evidence)
    report = native.build_report(document)
    totals = {item["metric"]: item for item in report["totals"]}
    assert totals["modeled_minutes_saved"]["value"] is None
    assert totals["qualified_hours_saved"]["value"] is None
    assert totals["qualified_hours_saved"]["qualification"]["state"] == "qualified"
    assert native.export_monitoring_observations(document) == evidence
    row["input_tokens"] = native._v2().NATIVE_MAX
    evidence["rows"].append(deepcopy(row))
    totals = {item["metric"]: item for item in native.build_report(converted(evidence))["totals"]}
    assert totals["input_tokens"]["value"] is None


def test_shared_reviewed_fixture_is_pinned_lossless_and_never_live():
    manifest = json.loads((ROOT / "samples" / "monitoring-observations.canonical-reviewed.manifest.json").read_text())
    raw = (ROOT / "samples" / manifest["artifact"]).read_bytes()
    assert hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == manifest["sha256_lf"]
    fixture = json.loads(raw)
    assert manifest["scenario"] == "aifactory.monitoring-sample.v1"
    assert fixture["contract"] == manifest["observation_contract"]
    assert fixture["source"] == "sample" and len(fixture["rows"]) == manifest["rows"] == 18
    assert all(row["source"] == "sample" and "native_link" not in row and not row.get("resource_id")
               for row in fixture["rows"])
    assert {row["factory"] for row in fixture["rows"]} == {"Demo AI Factory", "Demo Factory B"}
    document = converted(fixture)
    assert native.export_monitoring_observations(document) == fixture
    events = native.app_events(document)
    assert len(events) == 18
    assert all(json.loads(event["properties"]["observation"])["canonical"] == row
               for event, row in zip(events, fixture["rows"]))
    filters = {"aiFactory": "Demo AI Factory", "scaleset": "demo-east", "project": "001", "environment": "dev"}
    selected = native.export_monitoring_observations(document, filters)
    assert len(selected["rows"]) == 1 and selected["rows"][0]["project"] == "001"
    report = native.build_report(document, filters)
    assert all(row["drillthrough"] is None for row in report["rows"])
    requests = next(row for row in report["totals"] if row["metric"] == "requests")
    assert requests["value"] == 80 and requests["unit"] == "requests"
    assert next(row for row in report["totals"] if row["metric"] == "verified_realized_value")["value"] is None
    with pytest.raises(ValueError, match="relabeled"):
        native.import_monitoring_observations(fixture, source="live", native_version=2, authorized_scopes=[])
