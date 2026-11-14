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


def test_set_alert_changes_only_given_fields_and_clears_groups_explicitly():
    assert run("set-alert", "--model-id", MODEL_ID, "--entity", "layer-genai", "--unhealthy", "Sev1") == 0
    assert last_calls()[0][2] == {"unhealthy": {"severity": "Sev1"}}
    assert run("set-alert", "--model-id", MODEL_ID, "--entity", "layer-genai", "--unhealthy", "Sev1",
               "--clear-action-groups") == 0
    assert last_calls()[0][2] == {"unhealthy": {"severity": "Sev1", "actionGroupIds": []}}


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


def test_tool_schemas_use_portable_json_schema_regex():
    """MCP hosts validate schemas with ECMA-262 regex; Python-only syntax would break registration."""
    def patterns(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "pattern":
                    yield value
                else:
                    yield from patterns(value)
        elif isinstance(node, list):
            for item in node:
                yield from patterns(item)
    for tool in tools.TOOLS:
        for pattern in patterns(tool["inputSchema"]):
            for python_only in ("(?P<", "(?i", "\\A", "\\Z", "(?#"):
                assert python_only not in pattern, (tool["name"], pattern)


def test_call_tool_accepts_lowercase_model_ids_like_alert_payloads_use():
    factory = lambda model_id: FakeClient(model_id)
    summary = tools.call_tool(factory, "healthmodel_summary", {"modelId": MODEL_ID.lower()})
    assert summary["root"]["state"] == "Degraded"


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


def test_read_only_client_factory_blocks_writes():
    from aifactory_healthmodel.infrastructure.proxies import ReadOnlyTransport, ReadOnlyViolation

    client = tools.read_only_client_factory("cli")(MODEL_ID)
    assert isinstance(client.transport, ReadOnlyTransport)
    with pytest.raises(ReadOnlyViolation):
        client.ingest_health_report("root", "probe", "Healthy")


# ---------------------------------------------------------------- consumer model definitions at runtime
def factory_config(tmp_path):
    document = {"dev": {"tenantId": "11111111-1111-1111-1111-111111111111", "dev_sub_id": SUB,
                        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
                        "admin_aifactoryPrefixRG": "spider-", "admin_aifactorySuffixRG": "-001",
                        "projectPrefix": "esml-", "projectSuffix": "-rg", "vnetResourceGroupBase": "esml-common",
                        "project_number_000": "001"}, "stage_prod": {}}
    folder = tmp_path / "aifactory"
    (folder / "healthmodels").mkdir(parents=True)
    (folder / "variables.json").write_text(json.dumps(document), encoding="utf-8")
    return folder


def write_definition(folder, key, token, home):
    folder.mkdir(exist_ok=True)
    (folder / f"{key}.json").write_text(json.dumps({
        "key": key, "nameToken": token, "home": home, "rootDisplayName": key,
        "layers": [{"fromCatalog": True, "select": {"all": True}}]}), encoding="utf-8")


def test_runtime_scope_resolves_consumer_definitions(tmp_path):
    folder = factory_config(tmp_path)
    write_definition(folder / "healthmodels", "data-platform", "dat{project}", "project")
    write_definition(tmp_path / "more", "vault", "kv", "common")
    config = ["--consumer-root", str(tmp_path), "--variables-json", "aifactory/variables.json",
              "--environment", "dev", "--project", "001"]
    assert run("status", *config, "--scope", "data-platform") == 0, "<config folder>/healthmodels is loaded"
    assert FakeClient.instances[-1].model_id == (
        f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CloudHealth/healthmodels/hm-spider-dat001-sdc-dev-001")
    assert run("alerts", *config, "--scope", "vault", "--definitions-dir", str(tmp_path / "more")) == 0
    assert FakeClient.instances[-1].model_id == (
        f"/subscriptions/{SUB}/resourceGroups/spider-esml-common-sdc-dev-001/providers/Microsoft.CloudHealth/"
        "healthmodels/hm-spider-kv-sdc-dev-001")


def test_consumer_definitions_can_redefine_a_built_in_key(tmp_path, capsys):
    folder = factory_config(tmp_path)
    write_definition(folder / "healthmodels", "agents", "bot{project}", "project")
    config = ["--consumer-root", str(tmp_path), "--variables-json", "aifactory/variables.json",
              "--environment", "dev", "--project", "001"]
    assert run("status", *config, "--scope", "agents") == 0
    assert FakeClient.instances[-1].model_id.endswith("/healthmodels/hm-spider-bot001-sdc-dev-001")
    assert run("status", *config, "--scope", "nope") == 1
    assert "Unknown model definition 'nope'" in capsys.readouterr().err


def test_later_definition_folders_win_even_when_the_convention_folder_is_repeated(tmp_path):
    folder = factory_config(tmp_path)
    write_definition(folder / "healthmodels", "data-platform", "dat{project}", "project")
    write_definition(tmp_path / "shared", "data-platform", "shr{project}", "project")
    config = ["--consumer-root", str(tmp_path), "--variables-json", "aifactory/variables.json",
              "--environment", "dev", "--project", "001", "--scope", "data-platform"]
    assert run("status", *config, "--definitions-dir", str(tmp_path / "shared")) == 0
    assert FakeClient.instances[-1].model_id.endswith("/hm-spider-shr001-sdc-dev-001"), "explicit folder after convention"
    assert run("status", *config, "--definitions-dir", str(tmp_path / "shared"),
               "--definitions-dir", str(folder / "healthmodels")) == 0
    assert FakeClient.instances[-1].model_id.endswith("/hm-spider-dat001-sdc-dev-001"), "the folder given last wins"
