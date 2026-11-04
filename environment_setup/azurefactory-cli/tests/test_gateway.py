import json

import pytest

from azurefactory import AzureFactoryClient, ConfigError
from azurefactory.cli import main


def recording(monkeypatch, response):
    calls = []

    def request(self, method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return response

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    return calls


def test_sdk_gateway_routes_match_the_shared_api(monkeypatch):
    calls = recording(monkeypatch, {"instances": [], "areas": []})
    client = AzureFactoryClient(api_key="fixture")
    client.gateway_instances()
    client.gateway_snapshot("gentle-dusk-3200")
    client.gateway_refresh("apim-spider-sdc-dev-001")
    assert [call[:2] for call in calls] == [
        ("GET", "/api/v1/gateway/instances"),
        ("GET", "/api/v1/gateway/instances/gentle-dusk-3200/snapshot"),
        ("POST", "/api/v1/gateway/instances/apim-spider-sdc-dev-001/refresh"),
    ]
    assert all("body" not in call[2] for call in calls)


@pytest.mark.parametrize("instance", ["", "../health", "a/b", "x" * 129, " DEMO", None])
def test_sdk_rejects_unsafe_instance_ids_before_transport(monkeypatch, instance):
    calls = recording(monkeypatch, {})
    with pytest.raises(ConfigError):
        AzureFactoryClient(api_key="fixture").gateway_snapshot(instance)
    assert calls == []


def test_cli_gateway_commands_print_the_api_documents(monkeypatch, capsys):
    calls = recording(monkeypatch, {"instance_id": "DEMO", "mode": "DEMO", "menu": []})
    assert main(["--api-key", "fixture", "gateway", "list"]) == 0
    capsys.readouterr()
    assert main(["--api-key", "fixture", "gateway", "show", "DEMO"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "DEMO"
    assert main(["--api-key", "fixture", "gateway", "refresh", "gentle-dusk-3200"]) == 0
    capsys.readouterr()
    assert [call[:2] for call in calls] == [
        ("GET", "/api/v1/gateway/instances"),
        ("GET", "/api/v1/gateway/instances/DEMO/snapshot"),
        ("POST", "/api/v1/gateway/instances/gentle-dusk-3200/refresh"),
    ]
