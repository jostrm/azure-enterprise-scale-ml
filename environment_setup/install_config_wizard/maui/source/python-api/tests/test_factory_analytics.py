import copy
import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, operations
from src.factory_analytics import FactoryAnalytics
from src.ticketing import TicketError, TicketService


NOW = 1800000000.0
SUB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("No real Azure CLI")))
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("No live services")))


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def bundle(tmp_path):
    folder = tmp_path / "current-factory"
    for number, owner in (("001", "owner@example.org"), ("002", "")):
        root = folder / "config-wizard" / f"project-{number}"
        root.mkdir(parents=True)
        (root / "project_state.json").write_text(json.dumps({
            "project_number_000": number, "technical_admins_email": owner,
            "dev_sub_id": SUB, "tenantId": TENANT,
            "admin_aifactoryPrefixRG": "esml", "admin_aifactorySuffixRG": "001",
            "admin_location": "eastus2", "orchestrator": "gha",
            "enableAISearch": "true" if number == "001" else "false",
            "tags": {"CostCenter": "Cost-A", "Department": "HR"} if number == "001" else {},
        }), encoding="utf-8")
    (folder / "variables.json").write_text(json.dumps({
        "_wizard": {"orchestrator": "gha"},
        "dev": {"tenantId": TENANT, "dev_sub_id": SUB, "admin_aifactoryPrefixRG": "esml",
                "admin_aifactorySuffixRG": "001", "admin_location": "eastus2", "admin_locationSuffix": "eus2"},
        "stage_prod": {"test_sub_id": SUB, "prod_sub_id": SUB},
    }), encoding="utf-8")
    payload = {
        "source": "azure", "collected_at": iso(NOW), "inventory_complete": True,
        "subscriptions": [SUB], "resource_groups": [], "resources": [],
    }
    store = operations.OperationsStore(tmp_path / "ops.db")
    clock, identity = [NOW], ["user-a"]
    service = operations.OperationsService(store=store, inventory=SimpleNamespace(
        get_inventory=lambda *args: copy.deepcopy(payload)
    ))
    tickets = TicketService(store, identity=lambda folder=None: identity[0], clock=lambda: clock[0])
    analytics = FactoryAnalytics(service, tickets, clock=lambda: clock[0])
    return SimpleNamespace(folder=str(folder), payload=payload, store=store, clock=clock,
                           identity=identity, service=service, tickets=tickets, analytics=analytics)


def group(number="001", environment="dev", **extra):
    name = f"esml-project{number}-{environment}-001"
    return {"name": name, "id": f"/subscriptions/{SUB}/resourceGroups/{name}", "subscriptionId": SUB, **extra}


def resource(resource_type, number="001", environment="dev", name="resource", **extra):
    rg = group(number, environment)
    return {"type": resource_type, "name": name, "resourceGroup": rg["name"], "subscriptionId": SUB,
            "id": rg["id"] + "/providers/" + resource_type + "/" + name, **extra}


def sections(result):
    return {item["title"]: item for item in result["sections"]}


def ticket(bundle, **changes):
    return bundle.tickets.create({
        "aifactory_folder": bundle.folder, "project_number": "001", "type": "Blocker",
        "title": "Blocked", "description": "A technical blocker", **changes,
    })


def test_current_factory_envelope_all_string_cells_owner_and_every_environment(bundle):
    bundle.payload["resource_groups"] = [group(), group(environment="stage"), group(environment="prod")]
    bundle.payload["resources"] = [resource("Microsoft.Search/searchServices")]
    result = bundle.analytics.current(bundle.folder)
    assert set(result) == {"title", "source", "generated_at", "warning", "sections"}
    assert result["title"] == "Current AI Factory"
    assert all(isinstance(cell, str) for section in result["sections"] for row in section["rows"] for cell in row)
    rows = sections(result)["Projects, owners and deployment status"]["rows"]
    assert rows[0][0:5] == ["001", "owner@example.org", "Deployed (observed)", "Deployed (observed)", "Deployed (observed)"]
    assert rows[1][1] == "Unknown"
    envs = sections(result)["Projects by environment"]["rows"]
    assert [row[:3] for row in envs] == [["Dev", "2", "1"], ["Stage", "0", "1"], ["Prod", "0", "1"]]


def test_mock_resource_inventory_never_creates_projects_deployments_or_models(bundle):
    bundle.payload.update({
        "source": "mock", "resource_groups": [group("999")],
        "resources": [resource("Microsoft.CognitiveServices/accounts/deployments", "999")],
    })
    result = sections(bundle.analytics.current(bundle.folder))
    assert {row[0] for row in result["Projects, owners and deployment status"]["rows"]} == {"001", "002"}
    assert all(row[2] == "Unknown" for row in result["Projects by environment"]["rows"])
    assert all("not enumerated" in row[4] for row in result["Agents and ML models per project"]["rows"])
    with bundle.store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM factory_lifecycle_observations").fetchone()[0] == 0


def test_agent_models_only_actual_types_no_workspace_or_configuration_guess(bundle):
    bundle.payload["resource_groups"] = [group()]
    bundle.payload["resources"] = [
        resource("Microsoft.MachineLearningServices/workspaces", name="workspace"),
        resource("Microsoft.CognitiveServices/accounts", name="foundry", kind="AIServices"),
    ]
    first = sections(bundle.analytics.current(bundle.folder))
    assert "not enumerated" in first["Agents and ML models per project"]["rows"][0][3]
    assert "not enumerated" in first["Agents and ML models per project"]["rows"][0][4]
    bundle.payload["resources"] += [
        resource("Microsoft.CognitiveServices/accounts/projects/agents", name="agent"),
        resource("Microsoft.CognitiveServices/accounts/deployments", name="model"),
    ]
    second = sections(bundle.analytics.current(bundle.folder))
    assert second["Agents and ML models per project"]["rows"][0][3].startswith("1 observed")
    assert second["Agents and ML models per project"]["rows"][0][4].startswith("1 observed")
    assert second["Agents by cost center"]["rows"][0] == ["Cost-A", "1 observed (enumeration may be incomplete)"]
    departments = dict(second["Agents by department"]["rows"])
    assert departments["HR"].startswith("1 observed")
    assert set(departments) == {"HR", "Marketing", "Central IT", "Central AI Team", "Finance", "Unknown"}
    assert "not enumerated" in departments["Finance"]


def test_common_agents_are_counted_in_department_and_unknown_project(bundle):
    common = resource("Microsoft.CognitiveServices/accounts/projects/agents", name="shared-agent",
                      tags={"CostCenter": "Shared", "Department": "Finance"})
    common["resourceGroup"] = "esml-common-dev-001"
    bundle.payload["resources"] = [common]
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Agents and ML models per project"]["rows"][-1][0] == "Unknown / common project"
    assert dict(result["Agents by department"]["rows"])["Finance"].startswith("1 observed")
    assert dict(result["Agents by cost center"]["rows"])["Shared"].startswith("1 observed")


def test_pipeline_findings_without_project_are_not_multiplied_and_ticket_refs_deduplicate(bundle):
    blocker = ticket(bundle)
    original = bundle.service.overview
    def overview(*args):
        value = original(*args)
        value["regions"] = [{"pipeline_findings": [
            {"check_id": "global", "status": "failed"},
            {"project_number": "001", "check_id": "valid", "status": "failed"},
            {"project_number": "001", "check_id": "valid", "status": "failed"},
            {"project_number": "001", "check_id": "same-ticket", "status": "failed", "ticket_id": blocker["id"]},
            {"project_number": "999", "check_id": "other-project", "status": "failed"},
        ]}]
        return value
    bundle.service.overview = overview
    result = sections(bundle.analytics.current(bundle.folder))
    rows = result["Projects, owners and deployment status"]["rows"]
    assert rows[0][7] == "2"
    assert rows[1][7] == "0"
    assert "2 unattributed" in result["Projects, owners and deployment status"]["description"]


def test_lifecycle_stores_observed_since_not_config_mtime_and_cache_does_not_age(bundle):
    bundle.payload["resource_groups"] = [group()]
    first = sections(bundle.analytics.current(bundle.folder))
    stalled = first["Stalled Dev / Stage (cumulative)"]["rows"]
    assert all(row[2] == "0" and row[3] == "1" for row in stalled if row[0] == "Dev")
    bundle.clock[0] += 400 * 86400
    bundle.payload["source"] = "cached"
    cached = sections(bundle.analytics.current(bundle.folder))
    assert all(row[2] == "0" for row in cached["Stalled Dev / Stage (cumulative)"]["rows"])
    assert cached["Lifecycle observations"]["rows"][0][5] == "1"
    bundle.payload.update({"source": "azure", "collected_at": iso(bundle.clock[0])})
    aged = sections(bundle.analytics.current(bundle.folder))
    rows = [row for row in aged["Stalled Dev / Stage (cumulative)"]["rows"] if row[0] == "Dev"]
    assert [row[2] for row in rows] == ["1", "1", "1", "1", "0"]
    assert [row[3] for row in rows] == ["0", "0", "0", "0", "1"]
    assert aged["Lifecycle observations"]["rows"][0][5] == "2"
    assert aged["Lifecycle observations"]["rows"][0][3].startswith(iso(NOW)[:19])
    assert "configuration modification times" in bundle.analytics.current(bundle.folder)["warning"]


def test_confirmed_absence_resets_observed_episode_and_scope_change_isolates(bundle):
    bundle.payload["resource_groups"] = [group()]
    bundle.analytics.current(bundle.folder)
    bundle.clock[0] += 8 * 86400
    bundle.payload.update({"resource_groups": [], "collected_at": iso(bundle.clock[0])})
    bundle.analytics.current(bundle.folder)
    bundle.clock[0] += 100 * 86400
    bundle.payload.update({"resource_groups": [group()], "collected_at": iso(bundle.clock[0])})
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Lifecycle observations"]["rows"][0][5] == "1"
    with bundle.store._connect() as db:
        db.execute("UPDATE factory_lifecycle_observations SET scope_key='old-unrelated-scope'")
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Lifecycle observations"]["rows"][0][5] == "1"


def test_private_ticket_blockers_counts_and_requested_services_are_filtered(bundle, tmp_path):
    ticket(bundle)
    solved = ticket(bundle)
    bundle.tickets.update(solved["id"], "Solved")
    ticket(bundle, type="Request Azure service", requested_service="New quantum service")
    bundle.identity[0] = "user-b"
    ticket(bundle, type="Request Azure service", requested_service="PRIVATE-OTHER-USER")
    bundle.identity[0] = "user-a"
    other = tmp_path / "other-factory"
    other.mkdir()
    ticket(bundle, aifactory_folder=str(other), title="OTHER-FACTORY")
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Projects, owners and deployment status"]["rows"][0][7] == "1"
    assert result["Tickets by status"]["rows"] == [["New", "2"], ["Active", "0"], ["Solved", "1"]]
    assert result["Requested Azure services unavailable"]["rows"] == [
        ["New quantum service", "1", "Not mapped in Wizard service catalog"],
    ]
    assert "PRIVATE-OTHER-USER" not in json.dumps(result)
    assert "OTHER-FACTORY" not in json.dumps(result)


def test_unverified_identity_does_not_treat_tickets_as_zero(bundle):
    bundle.tickets.identity = Mock(side_effect=TicketError("Sign in", 401))
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Tickets by status"]["rows"] == [["New", "Unknown"], ["Active", "Unknown"], ["Solved", "Unknown"]]
    assert "private tickets unknown" in result["Projects, owners and deployment status"]["rows"][0][7]


def test_rg_blockers_use_severity_not_type_and_exact_factory_region(bundle):
    for kind, severity in (("Bug report", "minor"), ("Bug report", "major"),
                           ("Request Azure service", "blocker"), ("Blocker", "minor")):
        ticket(bundle, aifactory_folder=None, project_number=None, type=kind, severity=severity,
               requested_service="AI Search" if kind == "Request Azure service" else "",
               resource_group="esml-project001-eus2-dev-001")
    for name in ("esml-project001-sdc-dev-001", "esml-project001-eus2-dev-002",
                 "esml-other-project001-eus2-dev-001"):
        ticket(bundle, project_number=None, resource_group=name, severity="blocker")
    bundle.identity[0] = "user-b"
    ticket(bundle, project_number=None, resource_group="esml-project001-eus2-dev-001", severity="blocker")
    bundle.identity[0] = "user-a"
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Projects, owners and deployment status"]["rows"][0][7] == "1"
    assert result["Tickets by status"]["rows"] == [["New", "4"], ["Active", "0"], ["Solved", "0"]]
    assert result["Requested Azure services unavailable"]["rows"][0][0:2] == ["AI Search", "1"]
    # Naming metadata is not evidence of an observed deployment.
    assert all(row[2] == "0" for row in result["Projects by environment"]["rows"])


def test_analytics_infers_legacy_blocker_only_when_severity_key_absent(bundle):
    original = bundle.tickets.list_tickets
    ticket(bundle)
    def old_fixture(folder):
        result = original(folder)
        del result["tickets"][0]["severity"]
        return result
    bundle.tickets.list_tickets = old_fixture
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Projects, owners and deployment status"]["rows"][0][7] == "1"


def test_rg_ticket_only_project_blocker_is_visible_without_inventing_project_evidence(bundle):
    ticket(bundle, aifactory_folder=None, project_number=None, type="Request Azure service", severity="blocker",
           requested_service="AI Search", resource_group="esml-project011-eus2-dev-001")
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Private blocker tickets by project"]["rows"] == [["011", "1"]]
    assert {row[0] for row in result["Projects, owners and deployment status"]["rows"]} == {"001", "002"}
    assert result["Tickets by status"]["rows"][0] == ["New", "1"]


def test_services_include_zero_and_only_complete_inventory_asserts_zero(bundle):
    result = sections(bundle.analytics.current(bundle.folder))
    most = result["Configured services — most used"]["rows"]
    assert most[0][:3] == ["AI Search", "1", "0"]
    assert any(row[0] == "Cosmos DB" and row[1:3] == ["0", "0"] for row in most)
    bundle.payload["inventory_complete"] = False
    result = sections(bundle.analytics.current(bundle.folder))
    assert all(row[2] == "Unknown" for row in result["Configured services — least used"]["rows"])


def test_analytics_api_uses_same_native_table_contract(bundle, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    monkeypatch.setattr(api, "_operations_service", lambda: bundle.service)
    monkeypatch.setattr("src.factory_analytics.TicketService", lambda store: bundle.tickets)
    with TestClient(api.app) as client:
        result = client.post("/api/v1/analytics/current-factory", json={"aifactory_folder": bundle.folder},
                             headers={"X-API-Key": "key"})
    assert result.status_code == 200
    assert result.json()["title"] == "Current AI Factory"
    assert result.json()["sections"]


def write_project(bundle, number, **changes):
    path = Path(bundle.folder) / "config-wizard" / f"project-{number}" / "project_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "project_number_000": number, "_save_folder": bundle.folder, "orchestrator": "gha",
        "admin_aifactoryPrefixRG": "esml", "admin_aifactorySuffixRG": "001",
        "admin_location": "eastus2", "dev_sub_id": SUB, "tenantId": TENANT,
        "technical_admins_email": f"project-{number}@example.org", "enableCosmosDB": "true",
    }
    state.update(changes)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_mixed_gha_ado_history_in_same_folder_does_not_pollute_current_factory(bundle):
    write_project(bundle, "008", orchestrator="ado")
    write_project(bundle, "009", orchestrator="ado", admin_aifactorySuffixRG="009")
    write_project(bundle, "014", admin_aifactoryPrefixRG="historical")
    write_project(bundle, "015", admin_location="swedencentral")
    write_project(bundle, "016", dev_sub_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    write_project(bundle, "017", _save_folder=str(Path(bundle.folder).parent / "other-factory"))
    write_project(bundle, "018", project_number_000="099")
    write_project(bundle, "019", admin_aifactoryPrefixRG="")
    # An actual scoped resource can still prove deployment, but its historical
    # snapshot must not supply owner/planned/service metadata.
    bundle.payload["resource_groups"] = [group("008")]
    bundle.payload["resources"] = [resource("Microsoft.Search/searchServices", "008")]
    report = bundle.analytics.current(bundle.folder)
    result = sections(report)
    rows = result["Projects, owners and deployment status"]["rows"]
    assert {row[0] for row in rows} == {"001", "002", "008"}
    historical = next(row for row in rows if row[0] == "008")
    assert historical[1] == "Unknown"
    assert historical[2] == "Deployed (observed)"
    assert historical[5] == "Unknown"
    assert result["Projects by environment"]["rows"][0][:3] == ["Dev", "2", "1"]
    cosmos = next(row for row in result["Configured services — most used"]["rows"] if row[0] == "Cosmos DB")
    assert cosmos[1] == "0"
    assert "8 historical, out-of-scope or unverified" in report["warning"]
    assert "project-008@example.org" not in json.dumps(report)
    assert "project-014@example.org" not in json.dumps(report)
    assert {row[0] for row in result["Lifecycle observations"]["rows"]} == {"008"}


@pytest.mark.parametrize("field", ["tag_costceter_project", "tag_costcenter_project", "tag_costcenter"])
def test_concrete_project_cost_center_aliases_are_used(bundle, field):
    write_project(bundle, "001", **{field: "Project-Cost"}, tagsProject='{"CostCenter":"Secondary-Cost"}')
    bundle.payload["resource_groups"] = [group()]
    bundle.payload["resources"] = [resource("Microsoft.CognitiveServices/accounts/projects/agents")]
    result = sections(bundle.analytics.current(bundle.folder))
    assert result["Agents and ML models per project"]["rows"][0][5] == "Project-Cost"
    assert dict(result["Agents by cost center"]["rows"])["Project-Cost"].startswith("1 observed")


def test_tags_project_cost_center_precedes_common_tags_and_skips_placeholders(bundle):
    write_project(bundle, "001", tag_costcenter_project="$(unresolved)",
                  tagsProject='{"CostCenter":"Actual-project-cost","Department":"Finance"}',
                  tags={"CostCenter": "Common-cost"})
    bundle.payload["resource_groups"] = [group()]
    bundle.payload["resources"] = [resource("Microsoft.CognitiveServices/accounts/projects/agents")]
    result = sections(bundle.analytics.current(bundle.folder))
    row = result["Agents and ML models per project"]["rows"][0]
    assert row[5:7] == ["Actual-project-cost", "Finance"]
    assert "Common-cost" not in json.dumps(result)
    assert "$(unresolved)" not in json.dumps(result)


def test_unscoped_metadata_is_not_counted_as_a_planned_project(bundle):
    for number in ("001", "002"):
        write_project(bundle, number, admin_aifactoryPrefixRG="", admin_aifactorySuffixRG="", admin_location="")
    report = bundle.analytics.current(bundle.folder)
    result = sections(report)
    assert result["Projects, owners and deployment status"]["rows"] == []
    assert all(row[1] == "0" for row in result["Projects by environment"]["rows"])
    assert "missing scope is not active configuration" in report["warning"]
