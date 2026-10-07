import json

import pytest

from azurefactory import AzureFactoryClient, ConfigError
from azurefactory.cli import EXIT_BLOCKED, main


SUB_A = "11111111-1111-4111-8111-111111111111"
SUB_B = "22222222-2222-4222-8222-222222222222"


def test_sdk_costs_preserves_explicit_scope_and_canonical_report(monkeypatch):
    calls = []
    report = {"status": "partial", "rows": [{"actual_cost": "0", "forecast_cost": None}],
              "totals": [{"currency": "SEK", "actual_cost": "0"},
                         {"currency": "USD", "actual_cost": "12.34"}]}

    def request(self, method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs["body"]))
        return report

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    body = {"subscription_ids": [SUB_A, SUB_B], "month": "2026-10",
            "aifactory_folder": r"C:\consumer", "refresh": True}
    assert AzureFactoryClient(api_key="fixture").resource_group_costs(body) is report
    assert calls == [("POST", "/api/v1/monitoring/resource-group-costs", body)]


@pytest.mark.parametrize("body", [
    {}, {"subscription_ids": []}, {"subscription_ids": "all"},
    {"subscription_ids": ["all"]}, {"subscription_ids": [SUB_A, SUB_A]},
    {"subscription_ids": [SUB_A, SUB_A.upper()]},
    {"subscription_ids": [SUB_A], "tenant_id": SUB_B},
    {"subscription_ids": [SUB_A], "month": "2026-13"},
    {"subscription_ids": [SUB_A], "month": "2026-1"},
    {"subscription_ids": [SUB_A], "refresh": "true"},
])
def test_sdk_costs_rejects_implicit_or_invalid_scope_before_transport(monkeypatch, body):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid or expanded scope must not reach HTTP transport")

    monkeypatch.setattr(AzureFactoryClient, "request", unexpected)
    with pytest.raises(ConfigError):
        AzureFactoryClient(api_key="fixture").resource_group_costs(body)


def test_cli_costs_uses_server_month_default_and_no_tenant_discovery(monkeypatch, capsys):
    calls = []

    def costs(self, body):
        calls.append(body)
        return {"status": "available", "rows": [], "totals": []}

    monkeypatch.setattr(AzureFactoryClient, "resource_group_costs", costs)
    assert main(["monitoring", "resource-group-costs", "--subscription", SUB_A]) == 0
    assert calls == [{"subscription_ids": [SUB_A]}]
    assert json.loads(capsys.readouterr().out)["status"] == "available"


@pytest.mark.parametrize("status", ["partial", "stale", "unavailable", "unauthorized"])
def test_cli_costs_preserves_incomplete_status_and_currency_buckets(monkeypatch, capsys, status):
    report = {"status": status, "rows": [], "totals": [
        {"currency": "USD", "actual_cost": "12.34", "forecast_cost": None},
        {"currency": "SEK", "actual_cost": "50", "forecast_cost": "75"}]}
    calls = []

    def costs(self, body):
        calls.append(body)
        return report

    monkeypatch.setattr(AzureFactoryClient, "resource_group_costs", costs)
    assert main(["monitoring", "resource-group-costs", "--subscription", SUB_A,
                 "--subscription", SUB_B, "--month", "2026-10", "--refresh",
                 "--folder", r"C:\consumer"]) == EXIT_BLOCKED
    assert calls == [{"subscription_ids": [SUB_A, SUB_B], "month": "2026-10",
                      "refresh": True, "aifactory_folder": r"C:\consumer"}]
    assert json.loads(capsys.readouterr().out) == report


def test_cli_costs_requires_selected_subscription():
    with pytest.raises(SystemExit) as exc:
        main(["monitoring", "resource-group-costs"])
    assert exc.value.code == 2
