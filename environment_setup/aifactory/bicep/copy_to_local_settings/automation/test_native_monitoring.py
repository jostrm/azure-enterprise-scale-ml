"""Offline native monitoring contracts, scoped totals, lineage and portal-link validation."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote

import pytest

import native_monitoring as native


ROOT = Path(__file__).resolve().parent
MODULES = ROOT.parents[1] / "modules" / "monitoring"


@pytest.fixture
def sample():
    return json.loads((ROOT / "samples" / "agent-observations.sample.json").read_text())


def test_all_and_compound_scope_intersection_before_every_aggregation(sample, tmp_path):
    assert len(native.build_report(sample)["rows"]) == 9
    result = native.build_report(sample, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    assert len(result["rows"]) == 4
    assert all(row["scope"]["project"] == "001" for row in result["rows"])
    totals = {row["metric"]: row["value"] for row in result["totals"]}
    assert totals["cost|actual|USD"] == 20
    assert totals["cost|amortized|USD"] == 18
    assert totals["outcome||minutes saved"] == 90
    assert totals["security||control passed"] == 0
    assert all(point["scope"]["scaleset"] == "001" for chart in result["charts"] for point in chart["points"])
    assert all(row["drillthrough"] is None for row in result["rows"])
    target = tmp_path / "report.csv"
    native.export_csv(result, target)
    rows = list(csv.DictReader(target.open(encoding="utf-8")))
    assert len(rows) == 4 and all(row["project"] == "001" for row in rows)
    assert all(row["source"] == "sample" for row in rows)
    assert all(row["dataSource"] and row["formula"] and row["inputs"] for row in rows)


def test_project_number_is_not_a_cross_factory_identity(sample):
    result = native.build_report(sample, {"project": "001"})
    assert len(result["rows"]) == 6
    assert len([p for p in result["projects"] if p["kind"] == "cost" and p["costBasis"] == "actual"]) == 3
    assert all(row["scope"]["project"] not in {"1", "002", None} for row in result["rows"])


def test_unauthorized_rows_and_unknown_scope_do_not_match_concrete_selection(sample):
    sample["authorizedScopes"] = sample["authorizedScopes"][:1]
    assert len(native.build_report(sample)["rows"]) == 4
    result = native.build_report(sample, {"scaleset": "missing"})
    assert result["status"] == "no_data" and result["totals"] == [] and result["rows"] == []


def test_missing_baseline_and_quality_never_infer_business_value(sample):
    for key in ("baselineMinutes", "actualMinutes", "completed", "qualityPassed"):
        document = deepcopy(sample)
        del document["rows"][0]["outcome"][key]
        assert native.build_report(document)["rows"][0]["value"] is None
    sample["rows"][0]["outcome"]["qualityPassed"] = False
    assert native.build_report(sample)["rows"][0]["value"] is None


def test_missing_observation_marks_same_unit_totals_partial(sample):
    missing = deepcopy(sample["rows"][0])
    missing["id"] = "missing-baseline"
    del missing["outcome"]["baselineMinutes"]
    sample["rows"].append(missing)
    result = native.build_report(sample, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    total = next(row for row in result["totals"] if row["metric"] == "outcome||minutes saved")
    assert total["value"] == 90 and total["status"] == "partial"
    assert total["availableCount"] == 1 and total["observationCount"] == 2
    assert result["charts"][0]["status"] == "partial"


@pytest.mark.parametrize("formula", [None, "", " \t ", 123])
def test_estimates_require_nonblank_string_formula(sample, formula):
    row = deepcopy(sample["rows"][1])
    row["kind"], row["dataSource"] = "cost", "Calculated"
    row["cost"] = {"basis": "estimate", "estimateType": "tokens", "amount": 0.25, "currency": "USD",
                   "formula": formula, "inputs": {"input_tokens": 100, "cost_per_token": 0.0025}}
    row.pop("provenance", None)
    sample["rows"] = [row]
    result = native.build_report(sample)
    assert result["rows"][0]["value"] is None
    assert result["totals"][0]["status"] == "no_data"
    exported = native.export_monitoring_observations(sample)["rows"][0]
    assert exported["token_estimated_cost"] is None
    exported_formula = exported["provenance"]["token_estimated_cost"]["formula"]
    assert exported_formula is None or isinstance(exported_formula, str) and exported_formula.strip()
    workbook = (MODULES / "agentMonitoringWorkbook.bicep").read_text(encoding="utf-8")
    assert 'gettype(observation.cost.formula) == "string"' in workbook
    assert 'isnotempty(trim(@"\\s+", tostring(observation.cost.formula)))' in workbook


def test_no_data_is_not_zero_and_duplicate_observations_rejected(sample):
    sample["rows"] = []
    result = native.build_report(sample)
    assert result["status"] == "no_data" and result["totals"] == []
    assert all(chart["status"] == "no_data" for chart in result["charts"])
    sample["rows"] = [{"id": "same", "timestamp": "2026-09-01T00:00:00Z", "scope": sample["authorizedScopes"][0], "kind": "cost", "dataSource": "Cost Management"}] * 2
    with pytest.raises(ValueError, match="Duplicate"):
        native.build_report(sample)


def test_live_cost_links_use_validated_metadata_only():
    azure = {"subscriptionId": "cb872220-b0e8-471b-9075-cc5bd4aba298", "resourceGroup": "reviewed-project001"}
    link = native.cost_link(azure, "001", "live")
    assert link["tooltip"] == "Go to Azure Cost analysis for project 001"
    assert "%2FresourceGroups%2Freviewed-project001" in link["url"]
    assert link["url"].startswith("https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/")
    assert unquote(link["url"].split("/scope/", 1)[1]) == link["scope"]
    assert native.cost_link(azure, "001", "sample") is None
    assert native.cost_link({**azure, "resourceGroup": "bad/#scope"}, "001", "live") is None
    assert native.cost_link({**azure, "resourceId": "/subscriptions/other/resourceGroups/wrong"}, "001", "live") is None
    assert native.cost_link({"subscriptionId": "invented", "resourceGroup": "bad"}, "001", "live") is None
    assert native.cost_link(azure, "All", "live") is None
    encoded = native.cost_link({**azure, "resourceGroup": "project(001)"}, "001", "live")
    assert "%2FresourceGroups%2Fproject%28001%29" in encoded["url"]
    assert native.cost_link({**azure, "resourceGroup": "project%28001%29"}, "001", "live") is None
    resource = f"/subscriptions/{azure['subscriptionId']}/resourceGroups/{azure['resourceGroup']}/providers/Microsoft.Example/widgets/.."
    assert native.cost_link({**azure, "resourceId": resource}, "001", "live") is None


def test_workbook_is_opt_in_and_scope_filters_precede_summarization():
    text = (MODULES / "agentMonitoringWorkbook.bicep").read_text(encoding="utf-8")
    assert "param enableAgentMonitoring bool = false" in text
    assert "if (enableAgentMonitoring)" in text
    assert all(f'"{{{name}:escapejson}}" == "All"' in text for name in ("AiFactory", "Scaleset", "Project", "Environment", "Agent"))
    assert text.index("var filteredRows") < text.index("MinutesSaved=sum")
    assert text.index('"{Agent:escapejson}" == "All"') < text.index("summarize arg_max")
    assert "CostAnalysisUrl" in text and "Go to Azure Cost analysis for project " in text
    assert "Microsoft.Authorization/roleAssignments" not in text
    assert "Data source:" in text and "noDataMessage" in text


def test_workbook_uses_verified_link_column_renderer():
    text = (MODULES / "agentMonitoringWorkbook.bicep").read_text(encoding="utf-8")
    assert "columnMatch: 'Project'\n          formatter: 1" in text
    assert "linkTarget: 'Url'" in text and "linkColumn: 'CostAnalysisUrl'" in text
    assert "columnMatch: 'CostAnalysisUrl'\n          formatter: 5" in text
    assert "linkLabel: '{Project}'" not in text
    assert "customTooltip" not in text
    assert "Tooltip=strcat" in text
    assert "/Menu/open/costanalysis/scope/" in text and "/Menu/costanalysis/" not in text
    assert "CostAnalysisUrl=iff(MetadataValidated and ValidScope" in text
    projection = (MODULES / "agentMonitoringRows.kql").read_text(encoding="utf-8")
    assert 'tostring(observation.source) == "live"' in projection
    assert 'MetadataValidated=gettype(observation.metadata_validated) == "bool"' in projection
    assert 'tobool(observation.metadata_validated) == true' in projection


def test_native_report_links_require_explicit_collector_assertion(sample):
    sample["source"] = "live"
    row = sample["rows"][1]
    sample["rows"] = [row]
    row["azure"] = {"subscriptionId": "cb872220-b0e8-471b-9075-cc5bd4aba298",
                    "resourceGroup": "reviewed-project001"}
    assert native.build_report(sample)["rows"][0]["drillthrough"] is None
    row["metadata_validated"] = False
    assert native.build_report(sample)["rows"][0]["drillthrough"] is None
    row["metadata_validated"] = True
    assert native.build_report(sample)["rows"][0]["drillthrough"]["tooltip"] == "Go to Azure Cost analysis for project 001"
    sample["source"] = "sample"
    assert native.build_report(sample)["rows"][0]["drillthrough"] is None


def test_sample_has_no_azure_identifiers_or_links(sample):
    serialized = json.dumps(sample)
    assert "subscriptions/" not in serialized and "portal.azure.com" not in serialized


def test_prepared_events_match_workbook_contract_without_ingestion(sample):
    events = native.app_events(sample, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    assert len(events) == 4
    assert all(event["name"] == "aifactory.agent.observation" for event in events)
    row = json.loads(events[0]["properties"]["observation"])
    assert row["schema"] == native.SCHEMA and row["source"] == "sample"
    assert row["outcome"]["baselineMinutes"] == 12


@pytest.fixture
def canonical():
    record = {
        "factory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev", "agent_id": "claims",
        "timestamp": "2026-09-01T12:00:00Z", "completed_outcomes": 10, "baseline_minutes_per_outcome": 12,
        "actual_minutes_per_outcome": 3, "outcome_quality_passed": True,
        "actual_cost": 20, "amortized_cost": 18, "currency": "USD", "security_checks": 5, "security_findings": 2,
        "provenance": {},
    }
    for field in ("completed_outcomes", "baseline_minutes_per_outcome", "actual_minutes_per_outcome",
                  "actual_cost", "amortized_cost", "security_checks", "security_findings"):
        record["provenance"][field] = {"data_source": "Cost Management" if field.endswith("_cost") else "Application Insights",
                                       "reference": "sample-" + field, "description": "Explicit sample fixture"}
    return {"contract": native.CANONICAL_SCHEMA, "rows": [record]}


def test_canonical_bridge_preserves_evidence_scope_and_security_aggregates(canonical):
    document = native.import_monitoring_observations(canonical, source="sample")
    result = native.build_report(document, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    totals = {row["metric"]: row["value"] for row in result["totals"]}
    assert totals == {"outcome||minutes saved": 90, "cost|actual|USD": 20, "cost|amortized|USD": 18, "security||findings": 2}
    assert result["rows"][-1]["lineage"]["inputs"]["checks"] == 5
    assert result["rows"][0]["lineage"]["upstream"]["baseline_minutes_per_outcome"]["reference"] == "sample-baseline_minutes_per_outcome"
    assert all(row["drillthrough"] is None for row in result["rows"])


@pytest.mark.parametrize("source, actual, amortized", [("sample", 20, 18), ("live", None, None)])
def test_canonical_sample_cost_labels_are_preserved_without_live_promotion(canonical, source, actual, amortized):
    for field in ("actual_cost", "amortized_cost"):
        canonical["rows"][0]["provenance"][field]["data_source"] = "Sample fixture"
    scopes = [{"aiFactory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev", "agent": "claims"}]
    document = native.import_monitoring_observations(canonical, source=source, authorized_scopes=scopes)
    report = native.build_report(document)
    costs = {row["costBasis"]: row for row in report["rows"] if row["kind"] == "cost"}
    assert costs["actual"]["value"] == actual
    assert costs["amortized"]["value"] == amortized
    assert all(row["dataSource"] == "Sample fixture" and row["drillthrough"] is None for row in costs.values())
    assert report["source"] == source


@pytest.mark.parametrize("marker", ["document", "rows"])
def test_shipped_canonical_sample_is_rejected_as_live_with_valid_authorization(marker):
    document = json.loads((ROOT / "samples" / "monitoring-observations.sample.json").read_text())
    assert document["source"] == "sample" and all(row["source"] == "sample" for row in document["rows"])
    scopes = native.import_monitoring_observations(document, source="sample")["authorizedScopes"]
    assert scopes
    if marker == "document":
        for row in document["rows"]:
            del row["source"]
    else:
        del document["source"]
    with pytest.raises(ValueError, match="sample provenance cannot be relabeled"):
        native.import_monitoring_observations(document, source="live", authorized_scopes=scopes)


@pytest.mark.parametrize("marker", [None, "", "Unknown", "unavailable", "N/A", " \tUNKNOWN "])
def test_canonical_unknown_scope_markers_never_match_concrete_selection(canonical, marker):
    for field in ("factory", "scaleset", "project", "environment", "agent_id"):
        canonical["rows"][0][field] = marker
    imported = native.import_monitoring_observations(canonical, source="sample")
    assert imported["authorizedScopes"] == [{field: None for field in native.DIMENSIONS}]
    assert len(native.build_report(imported)["rows"]) == 4
    assert native.build_report(imported, {"project": "001"})["rows"] == []
    assert native.build_report(imported, {"project": "unavailable"})["rows"] == []
    with pytest.raises(ValueError, match="placeholders"):
        native.scope_key({**imported["authorizedScopes"][0], "project": "unavailable"})
    assert native.cost_link({"subscriptionId": "cb872220-b0e8-471b-9075-cc5bd4aba298",
                             "resourceGroup": "reviewed-project001"}, "unavailable", "live") is None


def test_opaque_collected_factory_path_and_scaleset_identity_are_preserved(canonical):
    factory, scaleset = r"C:\reviewed factories\café001", "westeurope:001"
    canonical["rows"][0].update(factory=factory, scaleset=scaleset)
    imported = native.import_monitoring_observations(canonical, source="sample")
    filters = {"aiFactory": factory, "scaleset": scaleset, "project": "001"}
    assert len(native.build_report(imported, filters)["rows"]) == 4
    row = native.export_monitoring_observations(imported, filters)["rows"][0]
    assert (row["factory"], row["scaleset"], row["project"]) == (factory, scaleset, "001")
    assert native.build_report(imported, {**filters, "scaleset": "westeurope:002"})["rows"] == []
    with pytest.raises(ValueError):
        native.selection({"aiFactory": "bad\nidentity"})


def test_canonical_export_pivots_exact_scope_and_preserves_missing_values(sample, tmp_path):
    exported = native.export_monitoring_observations(sample, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    assert exported["contract"] == "aifactory.monitoring-observations.v1"
    assert len(exported["rows"]) == 1
    row = exported["rows"][0]
    assert (row["factory"], row["scaleset"], row["project"], row["agent_id"]) == ("factory-a", "001", "001", "claims")
    assert (row["actual_cost"], row["amortized_cost"], row["completed_outcomes"]) == (20, 18, 10)
    assert row["security_checks"] == 1 and row["security_findings"] is None
    assert row["outcome_quality_passed"] is True and row.get("labor_rate_per_hour") is None
    assert row["source"] == "sample" and row["metadata_validated"] is False and "cost_scope" not in row
    assert row["provenance"]["actual_cost"]["reference"] == "sample-cost-export-001"
    assert "native.cost.amount" in row["provenance"]["actual_cost"]["formula"]
    assert "qualityPassed" in row["provenance"]["outcome_quality_passed"]["formula"]
    assert all(metadata["formula"] and metadata["inputs"] for metadata in row["provenance"].values())
    target = tmp_path / "observations.json"
    report = tmp_path / "report.json"
    assert native.main(["--input", str(ROOT / "samples" / "agent-observations.sample.json"),
                        "--aiFactory", "factory-a", "--scaleset", "001", "--project", "001",
                        "--output", str(report), "--observations-output", str(target)]) == 0
    assert json.loads(target.read_text()) == exported


@pytest.mark.parametrize("qualification", [None, False])
def test_canonical_export_never_promotes_unqualified_value(sample, qualification):
    sample["rows"][0]["outcome"]["qualityPassed"] = qualification
    row = native.export_monitoring_observations(sample, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})["rows"][0]
    assert row["completed_outcomes"] is None and row["baseline_minutes_per_outcome"] is None
    assert row["actual_minutes_per_outcome"] is None and row["outcome_quality_passed"] is qualification


def test_canonical_export_refuses_ambiguous_grain_or_currency(sample):
    duplicate = deepcopy(sample["rows"][1])
    duplicate["id"] = "another-disjoint-cost-needs-explicit-preaggregation"
    sample["rows"].append(duplicate)
    with pytest.raises(ValueError, match="overlapping actual_cost"):
        native.export_monitoring_observations(sample)
    sample["rows"].pop()
    sample["rows"][2]["cost"]["currency"] = "EUR"
    with pytest.raises(ValueError, match="different currencies"):
        native.export_monitoring_observations(sample)


@pytest.mark.parametrize("classification", [None, "other"])
def test_generic_native_estimate_is_never_reclassified_as_token_cost(sample, classification):
    row = deepcopy(sample["rows"][1])
    row["dataSource"] = "Calculated"
    row["cost"] = {"basis": "estimate", "amount": 10, "currency": "USD",
                   "formula": "server_hours * hourly_rate", "inputs": {"server_hours": 2, "hourly_rate": 5}}
    row["provenance"] = {"token_estimated_cost": {"data_source": "Calculated", "reference": "sample-ambiguous-cost-component"}}
    if classification is not None:
        row["cost"]["estimateType"] = classification
    sample["rows"] = [row]
    assert native.build_report(sample)["rows"][0]["value"] == 10
    with pytest.raises(ValueError, match="requires explicit estimateType=tokens"):
        native.export_monitoring_observations(sample)


def test_explicit_canonical_token_estimate_preserves_its_classification(canonical):
    canonical["rows"][0]["token_estimated_cost"] = 0.25
    canonical["rows"][0]["provenance"]["token_estimated_cost"] = {
        "data_source": "Calculated", "reference": "sample-supplied-token-assumptions",
        "formula": "input_tokens * cost_per_token", "inputs": {"input_tokens": 100, "cost_per_token": 0.0025}}
    imported = native.import_monitoring_observations(canonical, source="sample")
    estimate = next(row for row in imported["rows"] if row.get("cost", {}).get("basis") == "estimate")
    assert estimate["cost"]["estimateType"] == "tokens"
    exported = native.export_monitoring_observations(imported)["rows"][0]
    assert exported["token_estimated_cost"] == 0.25
    assert exported["provenance"]["token_estimated_cost"]["inputs"]["cost_per_token"] == 0.0025


def test_canonical_export_preserves_only_explicit_collector_metadata(canonical):
    scope = {"aiFactory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev", "agent": "claims"}
    canonical["rows"][0].update(subscription_id="cb872220-b0e8-471b-9075-cc5bd4aba298",
                               resource_group="reviewed-project001", metadata_validated=True)
    imported = native.import_monitoring_observations(canonical, source="live", authorized_scopes=[scope])
    exported = native.export_monitoring_observations(imported)
    assert exported["rows"][0]["metadata_validated"] is True
    assert exported["rows"][0]["resource_group"] == "reviewed-project001"
    for row in imported["rows"]:
        row.pop("metadata_validated")
    unasserted = native.export_monitoring_observations(imported)["rows"][0]
    assert unasserted["metadata_validated"] is False and "cost_scope" not in unasserted


def test_canonical_export_wrapper_uses_same_observation_contract(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime is unavailable")
    target = tmp_path / "observations.json"
    subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "coreteam" / "finops" / "runbooks" / "Update-AgentMonitoringReport.ps1"),
                    "-ObservationsPath", str(ROOT / "samples" / "agent-observations.sample.json"),
                    "-AiFactory", "factory-a", "-Scaleset", "001", "-Project", "001",
                    "-CanonicalObservationsPath", str(target), "-OutputPath", str(tmp_path / "report.json")],
                   check=True, capture_output=True, text=True)
    document = json.loads(target.read_text())
    assert document["contract"] == native.CANONICAL_SCHEMA and len(document["rows"]) == 1
    assert document["rows"][0]["project"] == "001" and document["rows"][0]["source"] == "sample"


def test_canonical_sample_costs_retain_sample_provenance_without_weakening_live(canonical):
    for field in ("actual_cost", "amortized_cost"):
        canonical["rows"][0]["provenance"][field]["data_source"] = "Sample fixture"
    imported = native.import_monitoring_observations(canonical, source="sample")
    result = native.build_report(imported)
    costs = {row["costBasis"]: row for row in result["rows"] if row["kind"] == "cost"}
    assert costs["actual"]["value"] == 20
    assert costs["amortized"]["value"] == 18
    assert all(row["dataSource"] == "Sample fixture" and row["drillthrough"] is None for row in costs.values())
    reviewed = native.import_monitoring_observations(canonical, source="live", authorized_scopes=imported["authorizedScopes"])
    assert all(row["value"] is None for row in native.build_report(reviewed)["rows"] if row["kind"] == "cost")


@pytest.mark.parametrize("marker", ("document", "row"))
def test_canonical_sample_marker_cannot_be_reclassified_as_live(canonical, marker):
    target = canonical if marker == "document" else canonical["rows"][0]
    target["source"] = "sample"
    with pytest.raises(ValueError, match="sample provenance cannot be relabeled"):
        native.import_monitoring_observations(canonical, source="live", authorized_scopes=[])


def test_canonical_bridge_never_infers_quality_or_pricing_inputs(canonical):
    row = canonical["rows"][0]
    del row["outcome_quality_passed"]
    row["token_estimated_cost"] = 3
    document = native.import_monitoring_observations(canonical, source="sample")
    result = native.build_report(document)
    assert next(row for row in result["rows"] if row["kind"] == "outcome")["value"] is None
    assert next(row for row in result["rows"] if row["costBasis"] == "estimate")["value"] is None


def test_reverse_export_never_relabels_generic_estimates_as_token_cost(canonical):
    record = canonical["rows"][0]
    record["token_estimated_cost"] = 3
    record["provenance"]["token_estimated_cost"] = {
        "data_source": "Calculated", "reference": "explicit sample token estimate",
        "formula": "input_tokens * usd_per_1k_tokens / 1000",
        "inputs": {"input_tokens": 1000, "usd_per_1k_tokens": 3},
    }
    document = native.import_monitoring_observations(canonical, source="sample")
    assert native.export_monitoring_observations(document)["rows"][0]["token_estimated_cost"] == 3
    estimate = next(row for row in document["rows"] if row["kind"] == "cost" and row["cost"]["basis"] == "estimate")
    estimate.pop("provenance")
    estimate["cost"].pop("estimateType", None)
    estimate["cost"].update(formula="vm_hours * hourly_rate", inputs={"vm_hours": 1, "hourly_rate": 3})
    assert next(row for row in native.build_report(document)["rows"] if row["costBasis"] == "estimate")["value"] == 3
    with pytest.raises(ValueError, match="generic estimate"):
        native.export_monitoring_observations(document)


@pytest.mark.parametrize("designation", ["type", "provenance"])
def test_reverse_export_requires_explicit_type_even_with_provenance(sample, designation):
    row = sample["rows"][1]
    sample["rows"] = [row]
    row["dataSource"] = "Calculated sample fixture"
    row.pop("provenance", None)
    row["cost"] = {"basis": "estimate", "amount": 3, "currency": "USD",
                   "formula": "input_tokens * rate", "inputs": {"input_tokens": 1000, "rate": 0.003}}
    if designation == "type":
        row["cost"]["estimateType"] = "tokens"
    else:
        row["provenance"] = {"token_estimated_cost": {"data_source": "Calculated", "reference": "sample-token-inputs"}}
    assert native.build_report(sample)["rows"][0]["value"] == 3
    if designation == "type":
        assert native.export_monitoring_observations(sample)["rows"][0]["token_estimated_cost"] == 3
    else:
        with pytest.raises(ValueError, match="requires explicit estimateType=tokens"):
            native.export_monitoring_observations(sample)


def test_canonical_live_import_requires_reviewed_authorization_and_source(canonical):
    with pytest.raises(ValueError, match="explicit"):
        native.import_monitoring_observations(canonical, source=None)
    with pytest.raises(ValueError, match="authorized scope manifest"):
        native.import_monitoring_observations(canonical, source="live")
    result = native.import_monitoring_observations(canonical, source="live", authorized_scopes=[])
    assert native.build_report(result)["rows"] == []


def test_canonical_cost_metadata_flag_and_scope_consistency_are_revalidated(canonical):
    row = canonical["rows"][0]
    row.update(subscription_id="cb872220-b0e8-471b-9075-cc5bd4aba298", resource_group="reviewed-project001", metadata_validated=True)
    scope = {"aiFactory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev", "agent": "claims"}
    valid = native.import_monitoring_observations(canonical, source="live", authorized_scopes=[scope])
    assert native.build_report(valid)["rows"][0]["drillthrough"]["tooltip"] == "Go to Azure Cost analysis for project 001"
    row["cost_scope"] = "/subscriptions/other/resourceGroups/other"
    wrong = native.import_monitoring_observations(canonical, source="live", authorized_scopes=[scope])
    assert all(item["drillthrough"] is None for item in native.build_report(wrong)["rows"])
    del row["cost_scope"]
    row["metadata_validated"] = False
    unreviewed = native.import_monitoring_observations(canonical, source="live", authorized_scopes=[scope])
    assert all(item["drillthrough"] is None for item in native.build_report(unreviewed)["rows"])


def test_canonical_cli_import_is_explicit_and_offline(canonical, tmp_path):
    source = tmp_path / "canonical.json"
    target = tmp_path / "native.json"
    source.write_text(json.dumps(canonical))
    assert native.main(["--input", str(source), "--source", "sample", "--project", "001", "--output", str(target)]) == 0
    result = json.loads(target.read_text())
    assert result["schema"] == native.REPORT_SCHEMA and result["inputSchema"] == native.SCHEMA
    assert len(result["rows"]) == 4 and result["source"] == "sample"


def test_canonical_friendly_factory_names_are_not_slugged(canonical):
    canonical["rows"][0].update(factory="Demo AI Factory", scaleset="demo-east")
    document = native.import_monitoring_observations(canonical, source="sample")
    result = native.build_report(document, {"aiFactory": "Demo AI Factory", "scaleset": "demo-east", "project": "001"})
    assert len(result["rows"]) == 4
    assert all(row["scope"]["aiFactory"] == "Demo AI Factory" and row["scope"]["project"] == "001" for row in result["rows"])
    assert native.build_report(document, {"aiFactory": "demo-ai-factory"})["rows"] == []


def test_shared_canonical_fixture_preserves_all_scope_intersections():
    document = json.loads((ROOT / "samples" / "monitoring-observations.sample.json").read_text())
    imported = native.import_monitoring_observations(document, source="sample")
    assert len(native.build_report(imported)["rows"]) == 6
    filtered = native.build_report(imported, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    assert len(filtered["rows"]) == 4
    assert next(row["value"] for row in filtered["totals"] if row["metric"] == "cost|actual|USD") == 20


def test_csv_keeps_untrusted_formula_text_literal(sample, tmp_path):
    result = native.build_report(sample, {"project": "001"})
    result["rows"][0]["lineage"]["formula"] = "=1+1"
    destination = tmp_path / "literal-formula.csv"
    native.export_csv(result, destination)
    rows = list(csv.DictReader(destination.open(encoding="utf-8")))
    assert rows[0]["formula"] == "'=1+1"
    assert result["rows"][0]["lineage"]["formula"] == "=1+1"


def test_whitespace_evidence_and_control_do_not_imply_value_or_compliance(sample, canonical):
    sample["rows"][0]["evidence"]["reference"] = " \t "
    sample["rows"][3]["security"]["control"] = " \t "
    result = native.build_report(sample, {"aiFactory": "factory-a", "scaleset": "001", "project": "001"})
    assert result["rows"][0]["value"] is None
    assert result["rows"][3]["value"] is None
    canonical["rows"][0]["provenance"]["baseline_minutes_per_outcome"]["reference"] = " "
    imported = native.import_monitoring_observations(canonical, source="sample")
    assert native.build_report(imported)["rows"][0]["value"] is None
    assert 'EvidencePresent=isnotempty(trim(@"\\s+", Evidence))' in (MODULES / "agentMonitoringRows.kql").read_text()


def test_powershell_source_enum_case_does_not_change_scope_identity(canonical, tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime is unavailable")
    document = tmp_path / "canonical.json"
    output = tmp_path / "report.json"
    document.write_text(json.dumps(canonical))
    script = ROOT / "coreteam" / "finops" / "runbooks" / "Update-AgentMonitoringReport.ps1"
    process = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(script),
                              "-ObservationsPath", str(document), "-Python", sys.executable, "-Source", "Sample",
                              "-Project", "001", "-OutputPath", str(output)],
                             cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert report["source"] == "sample" and len(report["rows"]) == 4
    assert report["filters"]["project"] == "001"
