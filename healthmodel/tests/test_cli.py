from __future__ import annotations

import json

import pytest

from aifactory_healthmodel import cli, tools

SUB = "00000000-0000-0000-0000-0000000000aa"
RG = "spider-esml-project001-sdc-dev-001-rg"
MODEL_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CloudHealth/healthmodels/hm-spider-prj001-sdc-dev-001"


class FakeClient:
    instances = []

    def __init__(self, model_id, transport=None):
        self.model_id = model_id
        self.calls = []
        FakeClient.instances.append(self)

    def summary(self):
        self.calls.append(("summary",))
        return {"model": "hm-spider-prj001-sdc-dev-001",
                "root": {"name": "hm-spider-prj001-sdc-dev-001", "displayName": "AI Factory project 001 (dev)",
                         "state": "Degraded"},
                "layers": [{"name": "layer-genai", "displayName": "Generative AI and agents", "state": "Degraded"}],
                "counts": {"Degraded": 3, "Healthy": 10},
                "problems": [{"name": "foundry-a", "displayName": "AI Foundry account: a", "state": "Degraded",
                              "path": ["AI Factory project 001 (dev)", "Generative AI and agents", "AI Foundry account: a"],
                              "signals": [{"name": "throttled-calls", "displayName": "Throttled calls", "state": "Degraded",
                                           "value": 42, "reportedAt": "2026-10-03T20:00:00Z"}]}],
                "unknown": [{"name": "search-b", "displayName": "AI Search: b"}]}

    def alerts(self, hours=24, state=None):
        self.calls.append(("alerts", hours, state))
        return [{"id": "/subscriptions/x/providers/Microsoft.AlertsManagement/alerts/1", "entity": "root",
                 "severity": "Sev1", "state": "New", "condition": "Fired", "firedAt": "t", "name": "n",
                 "description": "d", "monitorService": "Health Model"}]

    def history(self, entity, hours=24):
        self.calls.append(("history", entity, hours))
        return [{"previousState": "Healthy", "newState": "Degraded", "occurredAt": "t"}]

    def signal_history(self, entity, signal, hours=24):
        self.calls.append(("signal_history", entity, signal, hours))
        return [{"occurredAt": "t", "value": 1, "healthState": "Healthy"}]

    def ingest_health_report(self, entity, signal, state, **kwargs):
        self.calls.append(("report", entity, signal, state, kwargs))

    def add_annotation(self, entity, details, description=None):
        self.calls.append(("annotate", entity, details, description))
        return {"annotationId": "a1"}

    def set_entity_alerts(self, entity, **kwargs):
        self.calls.append(("set_alerts", entity, kwargs))
        return {"name": entity}

    def change_alert_state(self, alert_id, new_state, comment=None):
        self.calls.append(("alert_state", alert_id, new_state, comment))
        return {}


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(cli, "HealthModelClient", FakeClient)
    monkeypatch.setattr(cli, "make_transport", lambda auth: object())
    yield


def run(*argv):
    return cli.main(list(argv))


def last_calls():
    return FakeClient.instances[-1].calls


def test_status_prints_tree_and_problems(capsys):
    assert run("status", "--model-id", MODEL_ID) == 0
    out = capsys.readouterr().out
    assert "AI Factory project 001 (dev)  [Degraded]" in out
    assert "Generative AI and agents  [Degraded]" in out
    assert "throttled-calls" in out and "42" in out
    assert "AI Search: b" in out


def test_status_json_is_machine_readable(capsys):
    assert run("status", "--model-id", MODEL_ID, "--json") == 0
    assert json.loads(capsys.readouterr().out)["root"]["state"] == "Degraded"


def test_status_exit_code_can_gate_pipelines(capsys):
    assert run("status", "--model-id", MODEL_ID, "--fail-on", "Degraded") == 3
    assert run("status", "--model-id", MODEL_ID, "--fail-on", "Unhealthy") == 0


def test_model_can_be_named_explicitly():
    assert run("status", "--subscription", SUB, "--resource-group", RG, "--name", "hm-spider-prj001-sdc-dev-001") == 0
    assert FakeClient.instances[-1].model_id == MODEL_ID


def test_model_identification_is_required(capsys):
    assert run("status") == 1
    assert "--model-id" in capsys.readouterr().err


def test_alerts_listing(capsys):
    assert run("alerts", "--model-id", MODEL_ID, "--hours", "168", "--state", "New") == 0
    assert last_calls() == [("alerts", 168, "New")]
    assert "Sev1" in capsys.readouterr().out


def test_history_and_signal_history():
    assert run("history", "--model-id", MODEL_ID, "--entity", "foundry-a", "--hours", "6") == 0
    assert last_calls() == [("history", "foundry-a", 6.0)]
    assert run("history", "--model-id", MODEL_ID, "--entity", "foundry-a", "--signal", "throttled-calls") == 0
    assert last_calls() == [("signal_history", "foundry-a", "throttled-calls", 24.0)]


def test_report_ingests_external_signal():
    assert run("report", "--model-id", MODEL_ID, "--entity", "root", "--signal", "pipeline-smoke-test",
               "--state", "Unhealthy", "--value", "0", "--expires", "30", "--context", "Smoke test failed") == 0
    assert last_calls() == [("report", "root", "pipeline-smoke-test", "Unhealthy",
                             {"value": 0.0, "expires_in_minutes": 30, "context": "Smoke test failed"})]


def test_annotate_parses_key_value_details(capsys):
    assert run("annotate", "--model-id", MODEL_ID, "--detail", "event=release", "--detail", "version=1.2.3",
               "--description", "AI Factory 1.2.3") == 0
    assert last_calls() == [("annotate", "root", {"event": "release", "version": "1.2.3"}, "AI Factory 1.2.3")]
    assert run("annotate", "--model-id", MODEL_ID, "--detail", "missing-equals") == 1


def test_set_alert_maps_off_and_action_groups():
    group = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/microsoft.insights/actionGroups/ag1"
    assert run("set-alert", "--model-id", MODEL_ID, "--entity", "layer-genai", "--unhealthy", "Sev1",
               "--degraded", "off", "--action-group-id", group) == 0
    name, entity, kwargs = last_calls()[0]
    assert entity == "layer-genai" and kwargs["degraded"] is None
    assert kwargs["unhealthy"] == {"severity": "Sev1", "actionGroupIds": [group]}
    assert "UNCHANGED" not in str(kwargs)


def test_set_alert_requires_a_change(capsys):
    assert run("set-alert", "--model-id", MODEL_ID, "--entity", "root") == 1
    assert "--unhealthy" in capsys.readouterr().err


def test_alert_state_change():
    alert_id = f"/subscriptions/{SUB}/providers/Microsoft.AlertsManagement/alerts/1"
    assert run("alert-state", "--model-id", MODEL_ID, "--alert-id", alert_id, "--state", "Acknowledged",
               "--comment", "On it") == 0
    assert last_calls() == [("alert_state", alert_id, "Acknowledged", "On it")]


def test_plan_and_deploy_delegate_to_deploy_module(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.deploy, "main", lambda argv: seen.append(argv) or 0)
    assert run("plan", "--environment", "dev", "--project", "001") == 0
    assert seen == [["plan", "--environment", "dev", "--project", "001"]]


# ---------------------------------------------------------------- MCP-ready tools

def test_tool_definitions_are_read_only_and_schema_shaped():
    names = {tool["name"] for tool in tools.TOOLS}
    assert names == {"healthmodel_summary", "healthmodel_alerts", "healthmodel_entity_history",
                     "healthmodel_signal_history"}
    for tool in tools.TOOLS:
        assert tool["annotations"]["readOnlyHint"] is True
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and "modelId" in schema["required"]
        assert schema["additionalProperties"] is False
        assert len(tool["description"]) > 40


def test_call_tool_dispatches_with_validation():
    factory = lambda model_id: FakeClient(model_id)
    result = tools.call_tool(factory, "healthmodel_alerts", {"modelId": MODEL_ID, "hours": 168})
    assert result["alerts"][0]["severity"] == "Sev1"
    assert FakeClient.instances[-1].calls == [("alerts", 168, None)]
    summary = tools.call_tool(factory, "healthmodel_summary", {"modelId": MODEL_ID})
    assert summary["root"]["state"] == "Degraded"
    for bad in ({"modelId": "nope"}, {"modelId": MODEL_ID, "extra": 1}, {}):
        with pytest.raises(ValueError):
            tools.call_tool(factory, "healthmodel_summary", bad)
    with pytest.raises(ValueError):
        tools.call_tool(factory, "healthmodel_alerts", {"modelId": MODEL_ID, "hours": 5})
    with pytest.raises(KeyError):
        tools.call_tool(factory, "healthmodel_delete", {"modelId": MODEL_ID})
