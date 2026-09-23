import json

import pytest

from azurefactory import AzureFactoryClient, ConfigError
from azurefactory.cli import main


def test_sdk_monitoring_routes_preserve_canonical_body(monkeypatch):
    calls = []

    def request(self, method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint.endswith("/export"):
            return "project,actual_cost\n001,20\n"
        return {"contract": "aifactory.monitoring-report.v1"}

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    client = AzureFactoryClient(api_key="fixture")
    body = {"report_id": "showback", "source": "sample", "filters": {"project": "001"}}
    client.monitoring_catalog()
    client.monitoring_report(body)
    assert client.monitoring_export(body).startswith("project,actual_cost")
    assert [call[:2] for call in calls] == [
        ("GET", "/api/v1/monitoring/catalog"),
        ("POST", "/api/v1/monitoring/report"),
        ("POST", "/api/v1/monitoring/export"),
    ]
    assert calls[1][2]["body"] == body
    assert calls[2][2]["body"] == body


@pytest.mark.parametrize("body", [
    {}, {"report_id": "showback"}, {"source": "live", "report_id": "foundry-token"},
    {"source": "sample", "report_id": "start-job"},
])
def test_sdk_requires_explicit_mode_and_canonical_id(body):
    with pytest.raises(ConfigError):
        AzureFactoryClient(api_key="fixture").monitoring_report(body)


def test_sample_cli_filters_and_export_delegate_without_calculations(monkeypatch, capsys):
    requests = []

    def export(self, body):
        requests.append(body)
        return "canonical,csv\n1,2\n"

    monkeypatch.setattr(AzureFactoryClient, "monitoring_export", export)
    assert main(["monitoring", "export", "--report", "agent-value", "--factory", "factory-a",
                 "--scaleset", "001", "--project", "001", "--environment", "dev", "--format", "csv"]) == 0
    assert requests == [{"report_id": "agent-value", "source": "sample", "days": 7,
                         "filters": {"factory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev"}}]
    assert capsys.readouterr().out == "canonical,csv\n1,2\n"


def test_live_cli_cannot_implicitly_collect(capsys):
    assert main(["monitoring", "report", "--report", "showback", "--source", "live"]) == 2
    assert "never collects" in capsys.readouterr().err


def test_request_cli_preserves_observation_document(tmp_path, monkeypatch, capsys):
    body = {"report_id": "quality-reliability", "source": "live",
            "filters": {"factory": "factory-a"}, "rows": []}
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(body))
    monkeypatch.setattr(AzureFactoryClient, "monitoring_report", lambda self, request: request)
    assert main(["monitoring", "report", "--request", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == body
    assert main(["monitoring", "report", "--request", str(path), "--project", "002"]) == 2


def test_sdk_summary_preserves_evidence_and_dates(monkeypatch):
    calls = []
    response = {"contract": "aifactory.monitoring-summary.v1", "sections": []}

    def request(self, method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs["body"]))
        return response

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    body = {"source": "live", "rows": [], "native_bindings": [],
            "filters": {"factory": "Demo AI Factory", "project": "001"},
            "start_date": "2026-09-01", "end_date": "2026-09-22"}
    assert AzureFactoryClient(api_key="fixture").monitoring_summary(body) == response
    assert calls == [("POST", "/api/v1/monitoring/summary", body)]


@pytest.mark.parametrize("bounds", [
    {"start_date": "2026-09-01"},
    {"end_date": "2026-09-22"},
    {"start_date": "", "end_date": ""},
    {"start_date": "20260901", "end_date": "20260922"},
    {"start_date": 20260901, "end_date": "2026-09-22"},
    {"start_date": "2026-02-30", "end_date": "2026-03-01"},
    {"start_date": "2026-09-22", "end_date": "2026-09-01"},
    {"start_date": "2026-01-01", "end_date": "2026-04-01"},
])
@pytest.mark.parametrize("method", ["monitoring_report", "monitoring_export", "monitoring_summary"])
def test_sdk_rejects_invalid_windows_before_transport(monkeypatch, bounds, method):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Invalid dates must not reach HTTP transport")

    monkeypatch.setattr(AzureFactoryClient, "request", unexpected_request)
    body = {"source": "sample", **bounds}
    if method != "monitoring_summary":
        body["report_id"] = "agent-value"
    with pytest.raises(ConfigError, match="date|days"):
        getattr(AzureFactoryClient(api_key="fixture"), method)(body)


@pytest.mark.parametrize("end_date", ["2026-01-01", "2026-03-31"])
def test_sdk_accepts_one_and_ninety_inclusive_days(monkeypatch, end_date):
    monkeypatch.setattr(AzureFactoryClient, "request", lambda self, method, endpoint, **kwargs: kwargs["body"])
    body = {"source": "sample", "start_date": "2026-01-01", "end_date": end_date}
    assert AzureFactoryClient(api_key="fixture").monitoring_summary(body) == body


@pytest.mark.parametrize("body", [
    {}, {"source": "automatic"}, {"source": "sample", "report_id": "showback"},
])
def test_sdk_summary_requires_explicit_source_without_report_id(body):
    with pytest.raises(ConfigError):
        AzureFactoryClient(api_key="fixture").monitoring_summary(body)


def test_summary_cli_defaults_and_exact_request(monkeypatch, capsys, tmp_path):
    requests = []

    def summary(self, body):
        requests.append(body)
        return {"contract": "aifactory.monitoring-summary.v1", "sections": []}

    monkeypatch.setattr(AzureFactoryClient, "monitoring_summary", summary)
    assert main(["monitoring", "summary", "--factory", "Demo AI Factory", "--project", "001",
                 "--start-date", "2026-09-01", "--end-date", "2026-09-22"]) == 0
    assert requests[0] == {
        "source": "sample", "days": 7,
        "filters": {"factory": "Demo AI Factory", "scaleset": "All", "project": "001", "environment": "All"},
        "start_date": "2026-09-01", "end_date": "2026-09-22",
    }
    assert json.loads(capsys.readouterr().out)["contract"] == "aifactory.monitoring-summary.v1"
    live = {"source": "live", "rows": [], "filters": {"project": "001"}}
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(live))
    assert main(["monitoring", "summary", "--request", str(path)]) == 0
    assert requests[1] == live
    capsys.readouterr()
    assert main(["monitoring", "summary", "--request", str(path), "--end-date", "2026-09-22"]) == 2
    assert "--request cannot be combined" in capsys.readouterr().err


def test_summary_cli_never_starts_live_collection(capsys):
    assert main(["monitoring", "summary", "--source", "live"]) == 2
    assert "never collects" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["report", "export"])
def test_report_and_export_cli_forward_dates(monkeypatch, capsys, action):
    requests = []

    def request(self, method, endpoint, **kwargs):
        requests.append(kwargs["body"])
        return "metric,value\n" if endpoint.endswith("/export") else kwargs["body"]

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    assert main(["monitoring", action, "--report", "showback",
                 "--start-date", "2026-09-01", "--end-date", "2026-09-22"]) == 0
    assert requests[0]["start_date"] == "2026-09-01"
    assert requests[0]["end_date"] == "2026-09-22"
    capsys.readouterr()
