import copy
import json

import pytest

from azurefactory import APIError, AzureFactoryClient, ConfigError
from azurefactory.cli import main


CONTEXT = {
    "folder": r"C:\registered\azurefactory",
    "factory_id": "11111111-1111-4111-8111-111111111111",
    "scale_set_id": "22222222-2222-4222-8222-222222222222",
    "project_id": "33333333-3333-4333-8333-333333333333",
    "start_date": "2026-09-01",
    "end_date": "2026-09-22",
}
READ = "/api/v1/monitoring/evidence/read"


@pytest.fixture
def evidence():
    return {
        "contract": "aifactory.monitoring-evidence.v1",
        "status": "available",
        "rows": [{
            "factory": "factory-a", "scaleset": "001", "project": "001", "environment": "dev",
            "source": "live", "timestamp": "2026-09-02T07:12:34+00:00",
            "period_start": "2026-09-01T00:00:00+00:00",
            "period_end": "2026-09-03T00:00:00+00:00",
            "actual_cost": 21.5, "provenance": {"actual_cost": "observed"},
        }],
        "scopes": [{key: CONTEXT[key] for key in ("factory_id", "scale_set_id", "project_id")}],
        "snapshots": [{
            "source_id": "cost-import", "collected_at": None,
            "saved_at": "2026-09-23T00:00:00+00:00", "origin": "imported",
            "window": {"start": "2026-09-01T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00"},
            "row_count": 1,
        }],
        "native_bindings": [{"id": "billing", "observed_at": "2026-09-02T07:12:34+00:00"}],
        "window": {"start_date": "2026-09-01", "end_date": "2026-09-22",
                   "timezone": "UTC", "mode": "explicit"},
        "source_errors": [],
        "warnings": ["Imported observations are unverified; saved_at is not collection time."],
    }


def transport(monkeypatch, evidence):
    calls = []

    def request(self, method, endpoint, **kwargs):
        calls.append((method, endpoint, copy.deepcopy(kwargs["body"])))
        if endpoint == READ:
            return evidence
        assert endpoint in ("/api/v1/monitoring/summary", "/api/v1/monitoring/report")
        return {"contract": "aifactory.monitoring-" + endpoint.rsplit("/", 1)[1] + ".v1",
                "warnings": ["Missing quality evidence."], "rows": kwargs["body"]["rows"]}

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    return calls


def invoke_sdk(client, action, context):
    if action == "report":
        return client.monitoring_saved_report(context, report_id="showback")
    return getattr(client, "monitoring_" + ("evidence_read" if action == "read" else "saved_summary"))(context)


def cli_args(action, **overrides):
    args = ["--api-key", "fixture", "monitoring", "saved", action]
    for key, value in (CONTEXT | overrides).items():
        if value is not None:
            args += ["--" + key.replace("_", "-"), value]
    return args + (["--report", "showback"] if action == "report" else [])


@pytest.mark.parametrize("context", [CONTEXT, {"folder": CONTEXT["folder"]},
                                    {"folder": CONTEXT["folder"], "start_date": None, "end_date": None}])
def test_sdk_read_preserves_exact_request_and_response(monkeypatch, evidence, context):
    calls = transport(monkeypatch, evidence)
    before = copy.deepcopy(evidence)
    result = AzureFactoryClient(api_key="fixture").monitoring_evidence_read(context)
    assert result == before == evidence
    assert calls == [("POST", READ, context)]


@pytest.mark.parametrize("action", ["summary", "report"])
@pytest.mark.parametrize("dated", [False, True])
def test_sdk_saved_pipeline_preserves_evidence_and_unchanged_bounds(monkeypatch, evidence, action, dated):
    context = CONTEXT if dated else {"folder": CONTEXT["folder"]}
    before = copy.deepcopy(evidence)
    calls = transport(monkeypatch, evidence)
    result = invoke_sdk(AzureFactoryClient(api_key="fixture"), action, context)
    projection = {"source": "live", "rows": before["rows"], "native_bindings": before["native_bindings"]}
    if dated:
        projection.update(start_date=CONTEXT["start_date"], end_date=CONTEXT["end_date"])
    if action == "report":
        projection["report_id"] = "showback"
    assert calls == [("POST", READ, context), ("POST", "/api/v1/monitoring/" + action, projection)]
    assert result["status"] == "available"
    assert result["evidence"] == evidence == before
    assert result[action]["rows"] == before["rows"]
    assert result[action]["warnings"] == ["Missing quality evidence."]


@pytest.mark.parametrize("status", ["absent", "incompatible", "unavailable"])
@pytest.mark.parametrize("action", ["read", "summary", "report"])
def test_sdk_nonavailable_never_projects_or_falls_back(monkeypatch, evidence, status, action):
    evidence.update(status=status, rows=[], snapshots=[], native_bindings=[])
    calls = transport(monkeypatch, evidence)
    result = invoke_sdk(AzureFactoryClient(api_key="fixture"), action, CONTEXT)
    assert result["status"] == status
    if action == "read":
        assert result == evidence
    else:
        assert result == {"status": status, "evidence": evidence, action: None}
    assert calls == [("POST", READ, CONTEXT)]


@pytest.mark.parametrize("action", ["read", "summary", "report"])
def test_cli_partial_sources_remain_visible_with_surviving_evidence(monkeypatch, evidence, capsys, action):
    evidence["source_errors"] = [{"source_id": "automation", "status_code": 503,
                                  "scope": evidence["scopes"][0], "message": "Saved automation storage unavailable."}]
    before = copy.deepcopy(evidence)
    calls = transport(monkeypatch, evidence)
    assert main(cli_args(action)) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert (result if action == "read" else result["evidence"]) == before
    assert "warning" in captured.err.lower()
    assert "Saved automation storage unavailable." in captured.err
    assert before["warnings"][0] in captured.err
    assert len(calls) == (1 if action == "read" else 2)


@pytest.mark.parametrize("status,exit_code", [("absent", 0), ("incompatible", 5), ("unavailable", 5)])
@pytest.mark.parametrize("action", ["read", "summary", "report"])
def test_cli_nonavailable_status_is_explicit_without_healthy_zero(monkeypatch, evidence, capsys, status, exit_code, action):
    evidence.update(status=status, rows=[], snapshots=[], native_bindings=[])
    calls = transport(monkeypatch, evidence)
    assert main(cli_args(action)) == exit_code
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == status
    assert status in captured.err
    if action != "read":
        assert result[action] is None
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 503])
def test_http_failures_are_not_replaced_or_retried(monkeypatch, capsys, status):
    calls = []

    def request(self, method, endpoint, **kwargs):
        calls.append(endpoint)
        raise APIError("Saved read failed.", status=status, details={"detail": "server diagnostic"})

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    assert main(cli_args("summary")) != 0
    captured = capsys.readouterr()
    assert not captured.out
    error = json.loads(captured.err)["error"]
    assert error["status"] == status
    assert error["details"] == {"detail": "server diagnostic"}
    if status in (404, 405):
        assert "matching API release" in error["message"]
        assert "fallback" in error["message"]
    assert calls == [READ]


@pytest.mark.parametrize("status", [404, 405])
def test_sdk_missing_read_route_explains_release_requirement(monkeypatch, status):
    def request(*args, **kwargs):
        raise APIError("Route missing.", status=status, details={"detail": "Not Found"})

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    with pytest.raises(APIError, match="matching API release") as caught:
        AzureFactoryClient(api_key="fixture").monitoring_evidence_read(CONTEXT)
    assert caught.value.status == status
    assert caught.value.details == {"detail": "Not Found"}


@pytest.mark.parametrize("change", [
    {"contract": "aifactory.monitoring-evidence.v2"},
    {"status": "saved"}, {"status": ["available"]}, {"rows": None},
    {"native_bindings": {}}, {"source_errors": "lost"}, {"warnings": None},
    {"window": None}, {"scopes": {}}, {"snapshots": None},
])
def test_incompatible_response_fails_closed(monkeypatch, evidence, change):
    evidence.update(change)
    calls = transport(monkeypatch, evidence)
    with pytest.raises(APIError, match="contract|response"):
        AzureFactoryClient(api_key="fixture").monitoring_saved_summary(CONTEXT)
    assert len(calls) == 1


@pytest.mark.parametrize("context", [
    {}, {"folder": ""}, {"folder": 1}, CONTEXT | {"source": "sample"},
    CONTEXT | {"factory_id": "factory-a"}, CONTEXT | {"scale_set_id": "001"},
    CONTEXT | {"project_id": "00000000-0000-0000-0000-000000000000"},
    CONTEXT | {"start_date": None}, CONTEXT | {"end_date": "2026-09-01T00:00:00Z"},
    CONTEXT | {"end_date": "2026-08-31"}, CONTEXT | {"end_date": "2027-01-01"},
])
def test_invalid_read_context_rejected_before_transport(monkeypatch, context):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid context must not reach transport")

    monkeypatch.setattr(AzureFactoryClient, "request", unexpected)
    with pytest.raises(ConfigError):
        AzureFactoryClient(api_key="fixture").monitoring_evidence_read(context)


def test_invalid_report_rejected_before_saved_read(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid report must not reach transport")

    monkeypatch.setattr(AzureFactoryClient, "request", unexpected)
    with pytest.raises(ConfigError):
        AzureFactoryClient(api_key="fixture").monitoring_saved_report(CONTEXT, report_id="run-job")


def test_projection_failure_retains_saved_diagnostics(monkeypatch, evidence, capsys):
    calls = []

    def request(self, method, endpoint, **kwargs):
        calls.append(endpoint)
        if endpoint == READ:
            return evidence
        raise APIError("Cannot reduce evidence.", status=422, details={"detail": "bad row"})

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    assert main(cli_args("summary")) != 0
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["status"] == 422
    assert error["details"]["evidence"] == evidence
    assert error["details"]["projection_error"] == {"detail": "bad row"}
    assert calls == [READ, "/api/v1/monitoring/summary"]
