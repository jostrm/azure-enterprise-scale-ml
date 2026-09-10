import copy
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src import api, region_findings, wizard
from src.operations import OperationsService, OperationsStore
from src.region_findings import RegionFindingsStore, parse_report


SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
OTHER_SUB = "33333333-3333-4333-8333-333333333333"
OTHER_TENANT = "44444444-4444-4444-8444-444444444444"


def write_scope(root, sub=SUB, tenant=TENANT):
    root.mkdir(parents=True, exist_ok=True)
    (root / "variables.json").write_text(json.dumps({
        "dev": {"dev_sub_id": sub, "tenantId": tenant, "admin_location": "westeurope"},
        "stage_prod": {},
    }), encoding="utf-8")


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path / "aifactory"
    write_scope(root)
    monkeypatch.setattr(wizard, "_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda: str(tmp_path / "legacy"))
    store = OperationsStore(tmp_path / "operations.db")
    findings = RegionFindingsStore(store.db_path)
    return root, store, findings


def report(*, status="failed", source="pipeline_artifact", observed="2026-08-01T12:00:00Z",
           run="101", check="search_sku_capacity", kind="capacity", skus=("basic",)):
    return {
        "schema_version": 1, "region": "eastus2", "subscription_id": SUB,
        "tenant_id": TENANT, "environment": "dev", "source": source, "run_id": run,
        "run_url": f"https://github.com/example/factory/actions/runs/{run}" if run else None,
        "observed_at": observed,
        "observations": [
            {
                "check_id": check, "kind": kind, "service": "microsoft.search/searchservices",
                "sku": sku, "status": status, "message": "Search SKU unavailable in the reported run."
            } for sku in skus
        ],
    }


def eastus2(service, root, **kwargs):
    overview = service.overview(str(root), include_azure=False, **kwargs)
    return next(row for row in overview["regions"] if row["name"] == "eastus2")


def test_three_reported_skus_overlay_unoccupied_region_and_unknown_run_time(context):
    root, store, findings = context
    evidence = report(
        source="user_reported", observed=None, run=None,
        skus=("basic", "standard", "standard2"),
    )
    before = datetime.now(timezone.utc)
    assert findings.record_report(str(root), evidence)["recorded"] == 3
    region = eastus2(OperationsService(store), root)
    assert region["has_factory"] is False
    assert len(region["pipeline_findings"]) == 1
    finding = region["pipeline_findings"][0]
    assert finding["skus"] == ["basic", "standard", "standard2"]
    assert finding["status"] == "failed"
    assert finding["source"] == "user_reported"
    assert finding["observed_at"] is finding["run_id"] is finding["run_url"] is None
    assert before <= datetime.fromisoformat(finding["recorded_at"].replace("Z", "+00:00"))
    assert finding["environment"] == "dev"
    assert len(finding["id"]) == 64


def test_empty_default_does_not_invent_reports(context):
    root, store, findings = context
    overview = OperationsService(store).overview(str(root), include_azure=False)
    assert all(region["pipeline_findings"] == [] for region in overview["regions"])
    assert findings.unresolved(str(root)) == {}
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM region_findings_history").fetchone()[0] == 0


def test_local_refresh_is_idempotent_and_preserves_recorded_at(context):
    root, store, findings = context
    directory = root / "config-wizard" / "pipeline-reports"
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps(report()), encoding="utf-8")
    first = eastus2(OperationsService(store), root)["pipeline_findings"]
    second = eastus2(OperationsService(store), root)["pipeline_findings"]
    assert first == second
    assert first[0]["run_id"] == "101"
    assert first[0]["run_url"] == "https://github.com/example/factory/actions/runs/101"
    assert first[0]["observed_at"] == "2026-08-01T12:00:00.000000Z"
    assert findings.record_report(str(root / ".." / "aifactory"), report())["recorded"] == 0
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM region_findings_history").fetchone()[0] == 1


@pytest.mark.parametrize("field,value", [
    ("subscription_id", OTHER_SUB), ("tenant_id", OTHER_TENANT),
])
def test_foreign_scope_rejected_without_writes(context, field, value):
    root, store, findings = context
    evidence = report()
    evidence[field] = value
    with pytest.raises(ValueError, match="current factory scope"):
        findings.record_report(str(root), evidence)
    assert not findings.unresolved(str(root))


def test_folder_subscription_tenant_and_environment_isolation(context, tmp_path):
    root, store, findings = context
    findings.record_report(str(root), report())
    other = tmp_path / "other-factory"
    write_scope(other)
    assert findings.unresolved(str(other)) == {}
    write_scope(root, sub=OTHER_SUB)
    assert findings.unresolved(str(root)) == {}
    write_scope(root, tenant=OTHER_TENANT)
    assert findings.unresolved(str(root)) == {}
    write_scope(root)
    assert findings.unresolved(str(root))["eastus2"]
    passed = report(status="passed", observed="2026-08-03T12:00:00Z", run="103")
    passed["environment"] = "prod"
    findings.record_report(str(root), passed)
    assert findings.unresolved(str(root))["eastus2"]


def test_environment_subscription_pair_must_match(context):
    root, store, findings = context
    variables = json.loads((root / "variables.json").read_text())
    variables["stage_prod"]["test_sub_id"] = OTHER_SUB
    (root / "variables.json").write_text(json.dumps(variables))
    evidence = report()
    evidence["environment"] = "stage"
    with pytest.raises(ValueError, match="current factory scope"):
        findings.record_report(str(root), evidence)


def test_full_current_factory_state_wins_over_old_variables(context):
    root, store, findings = context
    (root / "config-wizard").mkdir()
    (root / "config-wizard" / "factory_state.json").write_text(json.dumps({
        "dev_sub_id": OTHER_SUB, "tenantId": OTHER_TENANT,
    }))
    with pytest.raises(ValueError, match="current factory scope"):
        findings.record_report(str(root), report())


def test_unknown_and_quota_catalog_or_generic_success_do_not_clear_capacity(context):
    root, store, findings = context
    findings.record_report(str(root), report())
    for status, check, kind in [
        ("unknown", "search_sku_capacity", "capacity"),
        ("passed", "search_quota", "quota"),
        ("passed", "search_sku_availability", "preflight_error"),
        ("passed", "deployment", "pipeline_error"),
    ]:
        findings.record_report(str(root), report(
            status=status, check=check, kind=kind, run="102", observed="2026-08-02T12:00:00Z",
        ))
    assert findings.unresolved(str(root))["eastus2"][0]["status"] == "failed"


def test_same_check_later_pass_resolves_only_its_sku_and_preserves_history(context):
    root, store, findings = context
    findings.record_report(str(root), report(skus=("basic", "standard", "standard2")))
    findings.record_report(str(root), report(
        status="passed", run="103", observed="2026-08-03T12:00:00Z",
    ))
    assert findings.unresolved(str(root))["eastus2"][0]["skus"] == ["standard", "standard2"]
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM region_findings_history").fetchone()[0] == 4


def test_search_producer_service_alias_has_canonical_scope_and_deduplicates(context):
    root, store, findings = context
    evidence = report()
    findings.record_report(str(root), evidence)
    evidence["observations"][0]["service"] = "Azure AI Search"
    assert findings.record_report(str(root), evidence)["recorded"] == 0
    passed = report(
        status="passed", run="103", observed="2026-08-03T12:00:00Z",
        check="search_sku_quota", kind="quota",
    )
    passed["observations"][0]["service"] = "Azure AI Search"
    findings.record_report(str(root), passed)
    active = findings.unresolved(str(root))["eastus2"]
    assert active[0]["service"] == "microsoft.search/searchservices"
    passed["observations"][0].update(check_id="search_sku_capacity", kind="capacity")
    findings.record_report(str(root), passed)
    assert findings.unresolved(str(root)) == {}


@pytest.mark.parametrize("arrival_order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_late_old_artifacts_never_replace_later_failure(context, arrival_order):
    root, store, findings = context
    evidence = [
        report(run="101", observed="2026-08-01T12:00:00Z"),
        report(status="passed", run="102", observed="2026-08-02T12:00:00Z"),
        report(run="103", observed="2026-08-03T12:00:00Z"),
    ]
    for index in arrival_order:
        findings.record_report(str(root), evidence[index])
    active = findings.unresolved(str(root))["eastus2"]
    assert len(active) == 1 and active[0]["run_id"] == "103"


def test_null_or_equal_timestamp_pass_cannot_claim_resolution(context):
    root, store, findings = context
    findings.record_report(str(root), report())
    for observed in (None, "2026-08-01T12:00:00Z"):
        findings.record_report(str(root), report(status="passed", run="102", observed=observed))
    assert findings.unresolved(str(root))["eastus2"]


def test_unknown_user_time_uses_recording_cutoff_for_cross_source_resolution(context, monkeypatch):
    root, store, findings = context
    monkeypatch.setattr(region_findings, "_now", lambda: "2026-08-02T12:00:00.000000Z")
    findings.record_report(str(root), report(source="user_reported", run=None, observed=None))
    findings.record_report(str(root), report(
        status="passed", observed="2026-08-01T12:00:00Z", run="101",
    ))
    assert findings.unresolved(str(root))["eastus2"][0]["observed_at"] is None
    findings.record_report(str(root), report(
        status="passed", observed="2026-08-03T12:00:00Z", run="103",
    ))
    assert findings.unresolved(str(root)) == {}


def test_capacity_and_hard_pipeline_error_are_independent(context):
    root, store, findings = context
    findings.record_report(str(root), report())
    findings.record_report(str(root), report(check="deployment", kind="pipeline_error", skus=(None,)))
    findings.record_report(str(root), report(
        status="passed", run="103", observed="2026-08-03T12:00:00Z",
    ))
    active = findings.unresolved(str(root))["eastus2"]
    assert len(active) == 1 and active[0]["kind"] == "pipeline_error" and active[0]["skus"] == []


def test_multiple_sources_do_not_erase_each_other(context, monkeypatch):
    root, store, findings = context
    monkeypatch.setattr(region_findings, "_now", lambda: "2026-08-02T12:00:00.000000Z")
    findings.record_report(str(root), report(source="user_reported", run=None, observed=None))
    findings.record_report(str(root), report())
    assert {row["source"] for row in findings.unresolved(str(root))["eastus2"]} == {
        "pipeline_artifact", "user_reported",
    }


def test_malformed_and_foreign_local_import_warn_without_losing_existing_map(context):
    root, store, findings = context
    findings.record_report(str(root), report())
    directory = root / "config-wizard" / "pipeline-reports"
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{not json}")
    (directory / "invalid-utf8.json").write_bytes(b"\xff\xff")
    foreign = report()
    foreign["tenant_id"] = OTHER_TENANT
    (directory / "foreign.json").write_text(json.dumps(foreign))
    overview = OperationsService(store).overview(str(root), include_azure=False)
    assert "Local pipeline report" in overview["warning"]
    assert "current factory scope" in overview["warning"]
    assert len(overview["regions"]) >= 55
    assert next(r for r in overview["regions"] if r["name"] == "eastus2")["pipeline_findings"]


def test_cached_azure_overview_still_imports_new_local_findings(context):
    root, store, findings = context

    class CachedInventory:
        def get_inventory(self, *args):
            return {"source": "cached", "warning": None, "resource_groups": [], "resources": []}

    service = OperationsService(store, inventory=CachedInventory())
    assert all(not row["pipeline_findings"] for row in service.overview(str(root))["regions"])
    directory = root / "config-wizard" / "pipeline-reports"
    directory.mkdir(parents=True)
    (directory / "new.json").write_text(json.dumps(report()))
    overview = service.overview(str(root))
    assert next(r for r in overview["regions"] if r["name"] == "eastus2")["pipeline_findings"]


@pytest.mark.parametrize("url", [
    "http://github.com/example/factory/actions/runs/101",
    "https://github.com.evil.invalid/example/factory/actions/runs/101",
    "https://evil.invalid/run/101",
    "https://github.com/example/factory/actions/runs/101?access_token=secret",
    "https://user:password@dev.azure.com/org/project/_build/results?buildId=101",
    "https://dev.azure.com/org/project/_build/results?buildId=101&sig=secret",
    "https://github.com/example/factory/blob/main/README.md",
])
def test_untrusted_run_urls_rejected(url):
    evidence = report()
    evidence["run_url"] = url
    with pytest.raises(ValueError):
        parse_report(json.dumps(evidence))


@pytest.mark.parametrize("url", [
    "https://dev.azure.com/org/project/_build/results?buildId=101",
    "https://example.visualstudio.com/project/_build/results?buildId=101&view=results",
    "https://github.com/example/factory/actions/runs/101/attempts/2",
])
def test_known_run_urls_accepted(url):
    evidence = report()
    evidence["run_url"] = url
    assert parse_report(json.dumps(evidence))["run_url"] == url


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(schema_version=True),
    lambda row: row.update(observed_at="2026-08-01T12:00:00"),
    lambda row: row.update(observed_at="2099-08-01T12:00:00Z"),
    lambda row: row.update(raw_log="Do not store"),
    lambda row: row.update(observations=row["observations"] * 201),
    lambda row: row["observations"][0].update(message="x" * 1001),
    lambda row: row["observations"][0].update(message="failed\nraw log"),
    lambda row: row["observations"][0].update(message="AccountKey=secret"),
    lambda row: row["observations"][0].update(raw_log="Do not store"),
    lambda row: row.update(observations=row["observations"] * 2),
])
def test_invalid_report_limits_and_secret_logs_rejected(mutate):
    evidence = report()
    mutate(evidence)
    with pytest.raises(ValueError):
        parse_report(json.dumps(evidence))


def test_content_bounds_duplicate_json_keys_and_environment_normalization():
    with pytest.raises(ValueError, match="1 MiB"):
        parse_report(" " * (region_findings.MAX_CONTENT_BYTES + 1))
    with pytest.raises(ValueError, match="duplicate"):
        parse_report('{"schema_version":1,"schema_version":1}')
    evidence = report()
    evidence["environment"] = "test"
    assert parse_report(json.dumps(evidence))["environment"] == "stage"


def test_report_and_import_endpoints_are_secured_and_persistent(context, monkeypatch):
    root, store, findings = context
    monkeypatch.setenv(api.API_KEY_ENV, "unit-test-key")
    monkeypatch.setattr(api, "_operations_service", lambda: OperationsService(store))
    headers = {"X-API-Key": "unit-test-key"}
    base = "/api/v1/operations/region-findings/"
    with TestClient(api.app) as client:
        for endpoint, body in [
            ("report", {"aifactory_folder": str(root), "report": report()}),
            ("import", {"aifactory_folder": str(root), "content": json.dumps(report())}),
        ]:
            assert client.post(base + endpoint, json=body).status_code == 401
            response = client.post(base + endpoint, headers=headers, json=body)
            assert response.status_code == 200
            assert set(response.json()) == {"recorded", "message"}
            assert response.json()["recorded"] == (1 if endpoint == "report" else 0)
        bad = copy.deepcopy(report())
        bad["tenant_id"] = OTHER_TENANT
        response = client.post(base + "report", headers=headers, json={
            "aifactory_folder": str(root), "report": bad,
        })
        assert response.status_code == 400 and "scope" in response.json()["detail"]
        response = client.post(base + "import", headers=headers, json={
            "aifactory_folder": str(root), "content": "{broken",
        })
        assert response.status_code == 400
    assert RegionFindingsStore(store.db_path).unresolved(str(root))["eastus2"]
