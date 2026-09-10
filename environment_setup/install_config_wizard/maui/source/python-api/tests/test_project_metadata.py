import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, wizard, operations
from src.project_metadata import owner_from_project_state, planned_environments_from_project_state


SUB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_SUB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.mark.parametrize("state,expected", [
    ({"technical_admins_email": "owner@example.org"}, "owner@example.org"),
    ({"technical_admins_email": "Project platform security group"}, "Project platform security group"),
    ({"technical_admins_email": ["one@example.org", "two@example.org"]}, "one@example.org, two@example.org"),
    ({"technical_admins_email": "<todo>_email", "tags": {"Owner": "Tag owner"}}, "Tag owner"),
    ({"tagsProject": '{"AIF-Project Owners":"Project owner"}', "tags": {"Owner": "Other owner"}}, "Project owner"),
    ({"tags": {"Owner": "$(technical_admins_email)"}}, "Unknown"),
    ({"tags": {"Owner": "${OWNER}"}}, "Unknown"),
    ({"technical_admins_email": "bad\nvalue"}, "Unknown"),
    ({"technical_admins_email": None, "tags": "not JSON"}, "Unknown"),
    ({"technical_admins_email": {"email": "unexpected@example.org"}}, "Unknown"),
    ({}, "Unknown"),
])
def test_owner_uses_project_state_only_and_rejects_unresolved_values(state, expected):
    assert owner_from_project_state(state, "001") == expected


def test_mismatched_project_never_contributes_owner_or_planned_environments():
    state = {"project_number_000": "002", "technical_admins_email": "other-project@example.org", "dev_sub_id": SUB}
    assert owner_from_project_state(state, "001") == "Unknown"
    assert planned_environments_from_project_state(state, "001") == []
    assert owner_from_project_state(state, "2") == "other-project@example.org"


def test_planned_environments_need_explicit_valid_subscription_and_never_fall_back():
    assert planned_environments_from_project_state({"dev_sub_id": SUB}) == ["dev"]
    assert planned_environments_from_project_state({"dev_sub_id": SUB, "prod_sub_id": OTHER_SUB}) == ["dev", "prod"]
    assert planned_environments_from_project_state({
        "dev_sub_id": SUB, "test_sub_id": OTHER_SUB, "prod_sub_id": SUB
    }) == ["dev", "stage", "prod"]
    assert planned_environments_from_project_state({
        "dev_sub_id": "<todo>_SubID", "test_sub_id": "subscription-placeholder",
        "prod_sub_id": "00000000-0000-0000-0000-000000000000",
    }) == []


def test_projects_api_owner_and_planned_are_same_project_not_root_other_project(tmp_path, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    factory = tmp_path / "factory"
    snapshot = factory / "config-wizard" / "project-001"
    snapshot.mkdir(parents=True)
    (snapshot / "project_state.json").write_text(json.dumps({
        "project_number_000": "001", "technical_admins_email": "one@example.org",
        "dev_sub_id": SUB, "test_sub_id": OTHER_SUB, "prod_sub_id": "",
    }))
    (factory / "variables.json").write_text(json.dumps({
        "dev": {"project_number_000": "002", "technical_admins_email": "other-project@example.org",
                "dev_sub_id": SUB, "test_sub_id": OTHER_SUB, "prod_sub_id": SUB},
    }))
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(legacy))
    monkeypatch.setattr(api, "_operations_service", Mock(side_effect=AssertionError("No historical/inventory fallback")))
    with TestClient(api.app) as client:
        result = client.post("/api/v1/projects", json={"aifactory_folder": str(factory)}, headers={"X-API-Key": "key"})
    assert result.status_code == 200
    project = result.json()["projects"][0]
    assert project["owner"] == "one@example.org"
    assert project["planned_environments"] == ["dev", "stage"]
    assert "other-project@example.org" not in result.text


def test_global_legacy_snapshot_from_another_folder_does_not_supply_new_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    factory, legacy = tmp_path / "current", tmp_path / "global-legacy"
    factory.mkdir()
    legacy.mkdir()
    (legacy / "project_005.json").write_text(json.dumps({
        "project_number_000": "005", "_save_folder": str(tmp_path / "other-factory"),
        "technical_admins_email": "another-folder@example.org", "dev_sub_id": SUB,
    }))
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda **kwargs: str(legacy))
    with TestClient(api.app) as client:
        result = client.post("/api/v1/projects", json={"aifactory_folder": str(factory)}, headers={"X-API-Key": "key"})
    assert result.status_code == 200
    assert result.json()["projects"][0]["owner"] == "Unknown"
    assert result.json()["projects"][0]["planned_environments"] == []
    assert "another-folder@example.org" not in result.text


def test_board_owner_uses_shared_helper_for_same_project_and_preserves_all_envs(tmp_path):
    folder = tmp_path / "factory"
    snapshots = []
    for number, owner in (("001", "one@example.org"), ("002", "two@example.org")):
        path = folder / "config-wizard" / f"project-{number}" / "project_state.json"
        snapshots.append({"project_number": number, "path": str(path), "state": {
            "project_number_000": number, "technical_admins_email": owner,
        }})
    discovered = {"folder": str(folder), "project_numbers": ["001", "002", "003"],
                  "project_snapshots": snapshots, "subscriptions": {"dev": SUB}}
    groups = [{"name": f"esml-project001-{env}-001", "subscriptionId": SUB} for env in ("dev", "stage", "prod")]
    cards = operations.LocalFactoryDiscovery().annotate_with_inventory(discovered, groups, [])["projects"]
    assert {card["project_number"]: card["owner"] for card in cards} == {
        "001": "one@example.org", "002": "two@example.org", "003": "Unknown",
    }
    assert [environment["status"] for environment in cards[0]["environments"]] == ["active", "active", "active"]


def test_board_owner_rejects_other_folder_or_mismatched_snapshot_and_uses_project_group_tags(tmp_path):
    folder = tmp_path / "factory"
    discovered = {"folder": str(folder), "project_numbers": ["001", "002", "003"], "subscriptions": {}, "project_snapshots": [
        {"project_number": "001", "path": str(tmp_path / "other-factory" / "project-001" / "project_state.json"),
         "state": {"project_number_000": "001", "technical_admins_email": "other-folder@example.org"}},
        {"project_number": "002", "path": str(folder / "config-wizard" / "project-009" / "project_state.json"),
         "state": {"project_number_000": "002", "technical_admins_email": "mismatched-directory@example.org"}},
        {"project_number": "003", "state": {
            "project_number_000": "009", "technical_admins_email": "other-project@example.org",
        }},
    ]}
    groups = [
        {"name": "esml-project002-stage-001", "tags": {"AIF-Project Owners": "Group owner"}},
        {"name": "esml-common-dev-001", "tags": {"Owner": "Not project owner"}},
    ]
    cards = operations.LocalFactoryDiscovery().annotate_with_inventory(discovered, groups, [])["projects"]
    assert {card["project_number"]: card["owner"] for card in cards} == {
        "001": "Unknown", "002": "Group owner", "003": "Unknown",
    }
