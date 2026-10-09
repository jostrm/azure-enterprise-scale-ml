from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from aifactory_healthmodel.client import HealthModelClient, UNCHANGED

SUB = "00000000-0000-0000-0000-0000000000aa"
RG = "spider-esml-project001-sdc-dev-001-rg"
NAME = "hm-spider-prj001-sdc-dev-001"
MODEL_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CloudHealth/healthmodels/{NAME}"


class FakeTransport:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def request(self, method, url, body=None):
        parts = urlsplit(url)
        self.calls.append((method, parts.path, parse_qs(parts.query), json.loads(json.dumps(body))))
        key = (method, parts.path)
        if key not in self.routes:
            raise AssertionError(f"Unexpected call {key}")
        response = self.routes[key]
        return response(body, parse_qs(parts.query)) if callable(response) else response


def entity(name, state, *, display=None, signals=(), alerts=None, **extra):
    properties = {"displayName": display or name, "healthState": state, "provisioningState": "Succeeded",
                  "signalGroups": {}, **extra}
    if signals:
        properties["signalGroups"]["azureResource"] = {
            "authenticationSetting": "systemassigned", "azureResourceId": "/x", "signals": list(signals)}
    if alerts is not None:
        properties["alerts"] = alerts
    return {"id": f"{MODEL_ID}/entities/{name}", "name": name, "properties": properties}


def signal(name, state, value=None):
    return {"name": name, "displayName": name.title(), "signalKind": "AzureResourceMetric",
            "metricName": "M", "metricNamespace": "n", "aggregationType": "Average", "timeGrain": "PT5M",
            "evaluationRules": {"unhealthyRule": {"operator": "GreaterThan", "threshold": 1}},
            "status": {"healthState": state, "value": value, "reportedAt": "2026-10-03T20:00:00Z"}}


def rel(parent, child):
    return {"name": f"{parent}-to-{child}", "properties": {"parentEntityName": parent, "childEntityName": child}}


@pytest.fixture()
def model_routes():
    entities = [
        entity(NAME, "Degraded", display="AI Factory project 001 (dev)"),
        entity("layer-genai", "Degraded", display="Generative AI and agents"),
        entity("layer-data", "Healthy", display="Data storage and databases"),
        entity("foundry-a", "Degraded", display="AI Foundry account: a",
               signals=[signal("model-availability", "Healthy", 100), signal("throttled-calls", "Degraded", 42)]),
        entity("search-b", "Unknown", display="AI Search: b", signals=[signal("search-latency", "Unknown")]),
        entity("storage-c", "Healthy", display="Storage account: c", signals=[signal("availability", "Healthy", 100)]),
    ]
    relationships = [rel(NAME, "layer-genai"), rel(NAME, "layer-data"), rel("layer-genai", "foundry-a"),
                     rel("layer-genai", "search-b"), rel("layer-data", "storage-c")]
    return {
        ("GET", f"{MODEL_ID}/entities"): {"value": entities[:3], "nextLink":
                                          f"https://management.azure.com{MODEL_ID}/entities?api-version=x&$skiptoken=2"},
        ("GET", f"{MODEL_ID}/relationships"): {"value": relationships},
    }, entities


def client_with(routes):
    return HealthModelClient(MODEL_ID, FakeTransport(routes))


def test_rejects_ids_that_are_not_health_models():
    with pytest.raises(ValueError):
        HealthModelClient("/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/s",
                          FakeTransport())


def test_entities_follow_next_link_pages(model_routes):
    routes, entities = model_routes
    first = routes[("GET", f"{MODEL_ID}/entities")]

    def paged(body, query):
        return {"value": entities[3:]} if "$skiptoken" in query else first
    routes[("GET", f"{MODEL_ID}/entities")] = paged
    client = client_with(routes)
    assert [e["name"] for e in client.entities()] == [e["name"] for e in entities]
    assert all(q["api-version"] == [client.api_version] for _, _, q, _ in client.transport.calls if "$skiptoken" not in q)


def test_summary_rolls_up_root_layers_and_failing_signals(model_routes):
    routes, entities = model_routes
    routes[("GET", f"{MODEL_ID}/entities")] = {"value": entities}
    summary = client_with(routes).summary()
    assert summary["model"] == NAME
    assert summary["root"] == {"name": NAME, "displayName": "AI Factory project 001 (dev)", "state": "Degraded"}
    assert [(l["name"], l["state"]) for l in summary["layers"]] == [("layer-genai", "Degraded"), ("layer-data", "Healthy")]
    assert summary["counts"] == {"Healthy": 2, "Degraded": 3, "Unknown": 1}
    problem = summary["problems"][0]
    assert problem["name"] == "foundry-a" and problem["state"] == "Degraded"
    assert problem["path"] == ["AI Factory project 001 (dev)", "Generative AI and agents", "AI Foundry account: a"]
    assert problem["signals"] == [{"name": "throttled-calls", "displayName": "Throttled-Calls", "state": "Degraded",
                                   "value": 42, "reportedAt": "2026-10-03T20:00:00Z"}]
    assert [p["name"] for p in summary["problems"]] == ["foundry-a"]
    assert [u["name"] for u in summary["unknown"]] == ["search-b"]


def test_summary_lists_parents_that_fail_through_their_own_signals(model_routes):
    routes, entities = model_routes
    layer = entity("layer-data", "Unhealthy", display="Data storage and databases")
    layer["properties"]["signalGroups"]["external"] = {"signals": [signal("pipeline-smoke-test", "Unhealthy", 0)]}
    routes[("GET", f"{MODEL_ID}/entities")] = {"value": [entities[0], entities[1], layer, *entities[3:]]}
    summary = client_with(routes).summary()
    names = [p["name"] for p in summary["problems"]]
    assert names == ["layer-data", "foundry-a"]
    assert summary["problems"][0]["signals"][0]["name"] == "pipeline-smoke-test"


def test_summary_explains_a_root_failing_through_its_own_external_report(model_routes):
    routes, entities = model_routes
    root = entity(NAME, "Unhealthy", display="AI Factory project 001 (dev)")
    root["properties"]["signalGroups"]["external"] = {"signals": [signal("synthetic-probe", "Unhealthy", 0)]}
    healthy = [entity(e["name"], "Healthy", display=e["properties"]["displayName"]) for e in entities[1:]]
    routes[("GET", f"{MODEL_ID}/entities")] = {"value": [root, *healthy]}
    summary = client_with(routes).summary()
    assert [p["name"] for p in summary["problems"]] == [NAME]
    assert summary["problems"][0]["signals"][0]["name"] == "synthetic-probe"
    assert summary["problems"][0]["path"] == ["AI Factory project 001 (dev)"]


def test_set_entity_alerts_keeps_existing_action_groups_and_description(model_routes):
    _, entities = model_routes
    group = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/microsoft.insights/actionGroups/ag-deployed"
    current = json.loads(json.dumps(entities[1]))
    current["properties"]["alerts"] = {"unhealthy": {"severity": "Sev2", "description": "Deployed text.",
                                                     "actionGroupIds": [group]}}
    routes = {("GET", f"{MODEL_ID}/entities/layer-genai"): current,
              ("PUT", f"{MODEL_ID}/entities/layer-genai"): lambda body, query: body}
    client = client_with(routes)
    client.set_entity_alerts("layer-genai", unhealthy={"severity": "Sev1"})
    assert client.transport.calls[-1][3]["properties"]["alerts"]["unhealthy"] == {
        "severity": "Sev1", "description": "Deployed text.", "actionGroupIds": [group]}
    client.set_entity_alerts("layer-genai", unhealthy={"severity": "Sev1", "actionGroupIds": []})
    assert "actionGroupIds" not in client.transport.calls[-1][3]["properties"]["alerts"]["unhealthy"]


def test_summary_surfaces_signal_errors_such_as_missing_rbac(model_routes):
    routes, entities = model_routes
    broken = signal("model-availability", "Unknown")
    broken["status"]["error"] = "Metrics query failed: ... does not have authorization to perform action 'Microsoft.Insights/metrics/read'"
    foundry = entity("foundry-a", "Unknown", display="AI Foundry account: a", signals=[broken])
    foundry["properties"]["signalGroups"]["azureResource"]["resourceHealth"] = {
        "enabled": "Enabled", "signalName": "ResourceHealth-1",
        "status": {"healthState": "Unknown", "error": "Insufficient permissions to query Azure Resource Health (HTTP 403)"}}
    routes[("GET", f"{MODEL_ID}/entities")] = {"value": [entities[0], entities[1], entities[2], foundry]}
    summary = client_with(routes).summary()
    assert [(e["entity"], e["signal"]) for e in summary["signalErrors"]] == [
        ("foundry-a", "model-availability"), ("foundry-a", "resource-health")]
    assert "metrics/read" in summary["signalErrors"][0]["error"]
    assert summary["hints"] and "Monitoring Reader" in summary["hints"][0]


def test_writable_properties_keep_only_resource_health_switch():
    properties = {"healthState": "Healthy", "signalGroups": {"azureResource": {
        "authenticationSetting": "systemassigned", "azureResourceId": "/x",
        "resourceHealth": {"enabled": "Enabled", "signalName": "ResourceHealth-1", "status": {"healthState": "Healthy"}},
        "signals": [{"name": "a", "status": {"healthState": "Healthy"}}]}}}
    from aifactory_healthmodel.client import writable_properties
    cleaned = writable_properties(properties)
    assert cleaned == {"signalGroups": {"azureResource": {
        "authenticationSetting": "systemassigned", "azureResourceId": "/x",
        "resourceHealth": {"enabled": "Enabled"}, "signals": [{"name": "a"}]}}}


def test_history_and_signal_history_post_time_windows():
    routes = {
        ("POST", f"{MODEL_ID}/entities/foundry-a/getHistory"): {"history": [
            {"previousState": "Healthy", "newState": "Degraded", "occurredAt": "2026-10-03T19:00:00Z"}]},
        ("POST", f"{MODEL_ID}/entities/foundry-a/getSignalHistory"): {"history": [
            {"occurredAt": "2026-10-03T19:00:00Z", "value": 42, "healthState": "Degraded"}]},
    }
    client = client_with(routes)
    assert client.history("foundry-a", hours=6)[0]["newState"] == "Degraded"
    assert client.signal_history("foundry-a", "throttled-calls", hours=6)[0]["value"] == 42
    _, _, _, body = client.transport.calls[0]
    assert set(body) == {"startAt", "endAt", "top"} and body["top"] == 1000
    assert client.transport.calls[1][3]["signalName"] == "throttled-calls"


def test_root_alias_resolves_to_model_name():
    routes = {("POST", f"{MODEL_ID}/entities/{NAME}/getHistory"): {"history": []}}
    assert client_with(routes).history("root") == []


def test_ingest_health_report_body_and_validation():
    routes = {("POST", f"{MODEL_ID}/entities/foundry-a/ingestHealthReport"): None}
    client = client_with(routes)
    client.ingest_health_report("foundry-a", "synthetic-probe", "Unhealthy", value=0, expires_in_minutes=15,
                                context="Probe failed: HTTP 503")
    body = client.transport.calls[0][3]
    assert body == {"signalName": "synthetic-probe", "healthState": "Unhealthy", "value": 0,
                    "expiresInMinutes": 15, "additionalContext": "Probe failed: HTTP 503"}
    for kwargs in ({"state": "Broken"}, {"expires_in_minutes": 0}, {"expires_in_minutes": 10081},
                   {"signal": "x"}, {"context": "x" * 4097}):
        args = {"entity": "foundry-a", "signal": "synthetic-probe", "state": "Healthy"} | kwargs
        with pytest.raises(ValueError):
            client.ingest_health_report(args.pop("entity"), args.pop("signal"), args.pop("state"), **args)


def test_annotations_respect_service_limits():
    routes = {
        ("POST", f"{MODEL_ID}/entities/{NAME}/addDataAnnotation"): {"annotationId": "a1", "createdAt": "t"},
        ("POST", f"{MODEL_ID}/entities/{NAME}/getDataAnnotations"): {"annotations": [{"annotationId": "a1"}]},
    }
    client = client_with(routes)
    assert client.add_annotation("root", {"event": "deployment", "version": "1.2.3"}, "AI Factory release")["annotationId"] == "a1"
    assert client.annotations("root", hours=24) == [{"annotationId": "a1"}]
    with pytest.raises(ValueError):
        client.add_annotation("root", {f"k{i}": "v" for i in range(11)})
    with pytest.raises(ValueError):
        client.add_annotation("root", {"k": "v" * 257})


def test_set_entity_alerts_read_modify_write_preserves_signals(model_routes):
    _, entities = model_routes
    current = json.loads(json.dumps(entities[3]))
    current["properties"]["discoveredBy"] = None
    current["properties"]["signalGroups"]["external"] = {"signals": [{"name": "probe"}]}
    routes = {
        ("GET", f"{MODEL_ID}/entities/foundry-a"): current,
        ("PUT", f"{MODEL_ID}/entities/foundry-a"): lambda body, query: {"name": "foundry-a", **body},
    }
    client = client_with(routes)
    group = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/microsoft.insights/actionGroups/ag1"
    client.set_entity_alerts("foundry-a", unhealthy={"severity": "Sev2", "actionGroupIds": [group]})
    sent = client.transport.calls[-1][3]["properties"]
    assert sent["alerts"]["unhealthy"]["severity"] == "Sev2"
    assert sent["alerts"]["unhealthy"]["actionGroupIds"] == [group]
    assert sent["alerts"]["unhealthy"]["description"]
    assert {"healthState", "provisioningState", "discoveredBy"}.isdisjoint(sent)
    assert "external" not in sent["signalGroups"]
    assert all("status" not in s for s in sent["signalGroups"]["azureResource"]["signals"])
    assert [s["name"] for s in sent["signalGroups"]["azureResource"]["signals"]] == ["model-availability", "throttled-calls"]


def test_set_entity_alerts_can_disable_one_state_and_keep_the_other(model_routes):
    _, entities = model_routes
    current = json.loads(json.dumps(entities[1]))
    current["properties"]["alerts"] = {"unhealthy": {"severity": "Sev2", "description": "x"},
                                       "degraded": {"severity": "Sev3", "description": "y"}}
    routes = {("GET", f"{MODEL_ID}/entities/layer-genai"): current,
              ("PUT", f"{MODEL_ID}/entities/layer-genai"): lambda body, query: body}
    client = client_with(routes)
    client.set_entity_alerts("layer-genai", degraded=None, unhealthy=UNCHANGED)
    assert client.transport.calls[-1][3]["properties"]["alerts"] == {"unhealthy": {"severity": "Sev2", "description": "x"}}


@pytest.mark.parametrize("bad", [
    {"severity": "Sev9"},
    {"severity": "Sev1", "actionGroupIds": ["/x"] * 6},
    {"severity": "Sev1", "description": ""},
    {"severity": "Sev1", "actionGroupIds": ["not-an-arm-id"]},
    {"severity": "Sev1", "unknown": True},
])
def test_set_entity_alerts_validates_configuration(model_routes, bad):
    _, entities = model_routes
    routes = {("GET", f"{MODEL_ID}/entities/foundry-a"): entities[3]}
    with pytest.raises(ValueError):
        client_with(routes).set_entity_alerts("foundry-a", unhealthy=bad)


def alert(target, *, state="New", condition="Fired", severity="Sev1", entity_name=None, display=None):
    """Shape captured from a live health-model alert (Alerts Management 2025-05-25-preview)."""
    model_id = target.split("/providers/Microsoft.AlertsManagement")[0]
    return {"id": f"{model_id}/providers/Microsoft.AlertsManagement/alerts/{abs(hash(target + state)) % 10**8}",
            "name": f"Entity {display} in health model x is Degraded",
            "type": "microsoft.alertsmanagement/alerts",
            "properties": {
                "context": {"entityName": entity_name, "entityDisplayName": display,
                            "linkToHealthTimeline": f"https://portal.azure.com/#@/resource{model_id}/timeline"},
                "essentials": {
                    "severity": severity, "alertState": state, "monitorCondition": condition,
                    "monitorService": "Health Model", "signalType": "Health",
                    "targetResource": target, "targetResourceType": "microsoft.cloudhealth/healthmodels",
                    "startDateTime": "2026-10-03T20:00:00Z", "description": "x",
                    "monitorConditionResolvedDateTime": "2026-10-03T20:05:00Z" if condition == "Resolved" else None}}}


def test_alerts_are_filtered_to_this_model_and_flattened():
    other = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/s1"
    payload = {"value": [
        alert(MODEL_ID.lower(), entity_name=NAME, display="AI Factory project 001 (dev)"),
        alert(other, severity="Sev3", entity_name="x", display="x"),
        alert(MODEL_ID, state="Acknowledged", condition="Resolved", severity="Sev2", entity_name="layer-genai",
              display="Generative AI and agents"),
    ]}
    routes = {("GET", f"/subscriptions/{SUB}/providers/Microsoft.AlertsManagement/alerts"): payload}
    client = client_with(routes)
    alerts = client.alerts(hours=24)
    assert [(a["entity"], a["severity"], a["state"], a["condition"]) for a in alerts] == [
        (NAME, "Sev1", "New", "Fired"), ("layer-genai", "Sev2", "Acknowledged", "Resolved")]
    assert alerts[0]["entityDisplayName"] == "AI Factory project 001 (dev)"
    assert alerts[0]["timeline"].endswith("/timeline") and alerts[1]["resolvedAt"] == "2026-10-03T20:05:00Z"
    query = client.transport.calls[0][2]
    assert query["targetResourceGroup"] == [RG] and query["timeRange"] == ["1d"]
    assert query["includeContext"] == ["true"]


def test_alerts_time_range_must_be_supported():
    with pytest.raises(ValueError):
        client_with({}).alerts(hours=5)


@pytest.mark.parametrize("alert_id", [
    f"/subscriptions/{SUB}/providers/Microsoft.AlertsManagement/alerts/123",
    f"{MODEL_ID}/providers/Microsoft.AlertsManagement/alerts/1a7a207c-8e4f-ef52-f74b-d1b74bad0033",
])
def test_change_alert_state_uses_alerts_management_action(alert_id):
    routes = {("POST", f"{alert_id}/changestate"): {"properties": {"essentials": {"alertState": "Acknowledged"}}}}
    client = client_with(routes)
    client.change_alert_state(alert_id, "Acknowledged", comment="Investigating Foundry throttling")
    method, path, query, body = client.transport.calls[0]
    assert query["newState"] == ["Acknowledged"] and body == {"comments": "Investigating Foundry throttling"}


def test_change_alert_state_rejects_other_ids_and_states():
    client = client_with({})
    with pytest.raises(ValueError):
        client.change_alert_state(f"/subscriptions/{SUB}/providers/Microsoft.AlertsManagement/alerts/1", "Resolved")
    for bad in ("/subscriptions/x/providers/Microsoft.Storage/foo",
                f"/subscriptions/{SUB}/providers/Microsoft.AlertsManagement/alerts/1/../../x"):
        with pytest.raises(ValueError):
            client.change_alert_state(bad, "Closed")


def test_managed_entities_and_relationships_for_pruning(model_routes):
    routes, entities = model_routes
    entities[3]["properties"]["tags"] = {"managedBy": "aifactory-healthmodel"}
    routes[("GET", f"{MODEL_ID}/entities")] = {"value": entities}
    client = client_with(routes)
    stale = client.stale_managed(desired_entities={"layer-genai"}, desired_relationships=set())
    assert stale["entities"] == ["foundry-a"]
