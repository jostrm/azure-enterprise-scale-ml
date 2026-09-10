import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, wizard


FIELDS = {
    "adminVMBuildAgentName": "vm-test",
    "adminVMBuildAgentPool": "aifactory-build-agent-1",
    "admin_aiSearchTier": "standard",
}


@pytest.fixture
def factory(tmp_path, monkeypatch):
    root = tmp_path / "aifactory"
    project = root / "config-wizard" / "project-017"
    project.mkdir(parents=True)
    snapshot = project / "project_state.json"
    snapshot.write_text(json.dumps({
        "orchestrator": "ado",
        "project_number_000": "017",
        "admin_aiSearchTier": "standard",
        "_save_folder": "previous-folder",
        "snapshot_only": "keep",
    }), encoding="utf-8")
    monkeypatch.setattr(wizard, "_snapshot_dir", lambda: str(tmp_path / "legacy"))
    monkeypatch.setattr(wizard, "_load_template_defaults", lambda: {})
    monkeypatch.setattr(wizard, "_save_app_settings", Mock())
    monkeypatch.setattr(wizard, "_sync_vars_from_state", Mock())
    return root, snapshot


def write_source(root, format_name, values=None, project="017"):
    variables = {"project_number_000": project, **(FIELDS if values is None else values)}
    if format_name == "yaml":
        path = root / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables" / "variables.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("variables:\n" + "".join(
            f"  {key}: {json.dumps(value)}\n" for key, value in variables.items()
        ), encoding="utf-8")
    else:
        path = root / "variables.json"
        path.write_text(json.dumps({
            "dev": variables,
            "stage_prod": {**variables, "adminVMBuildAgentName": "stage-agent"},
        }), encoding="utf-8")
    return path


@pytest.mark.parametrize("format_name", ["json", "yaml"])
@pytest.mark.parametrize("endpoint", ["projects/load", "startup/load"])
def test_project017_api_loads_current_source_not_incomplete_snapshot(factory, monkeypatch, format_name, endpoint):
    root, snapshot = factory
    source = write_source(root, format_name)
    before = {path: path.read_bytes() for path in (snapshot, source)}
    monkeypatch.setenv(api.API_KEY_ENV, "project017-test-key")

    with TestClient(api.app) as client:
        response = client.post(
            f"/api/v1/{endpoint}",
            headers={"X-API-Key": "project017-test-key"},
            json={"aifactory_folder": str(root), "project_number": "017"},
        )

    assert response.status_code == 200
    state = response.json()["state"]
    assert {key: state[key] for key in FIELDS} == FIELDS
    assert state["_save_folder"] == str(root)
    assert state["project_number_000"] == "017"
    assert state["orchestrator"] == "ado"
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("format_name", ["json", "yaml"])
def test_current_values_override_stale_snapshot_even_when_explicitly_empty(factory, format_name):
    root, snapshot = factory
    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    saved.update({key: "stale" for key in FIELDS})
    snapshot.write_text(json.dumps(saved), encoding="utf-8")
    write_source(root, format_name, {key: "" for key in FIELDS})

    state = wizard._load_project_state(str(snapshot), str(root))

    assert all(state[key] == "" for key in FIELDS)
    assert state["snapshot_only"] == "keep"


@pytest.mark.parametrize("source_project", ["018", ""])
def test_other_or_unidentified_current_project_does_not_overwrite_selected_snapshot(factory, source_project):
    root, snapshot = factory
    write_source(root, "json", project=source_project)

    state = wizard._load_project_state(str(snapshot), str(root))

    assert state["project_number_000"] == "017"
    assert state["adminVMBuildAgentName"] == ""
    assert state["adminVMBuildAgentPool"] == "Default"
    assert state["admin_aiSearchTier"] == "standard"


def test_snapshot_without_current_source_preserves_empty_values_and_adds_missing_defaults(factory):
    _, snapshot = factory
    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    saved["adminVMBuildAgentPool"] = ""
    snapshot.write_text(json.dumps(saved), encoding="utf-8")

    state = wizard._load_project_state(str(snapshot))

    assert state["adminVMBuildAgentName"] == ""
    assert state["adminVMBuildAgentPool"] == ""
    assert state["admin_aiSearchTier"] == "standard"
    assert set(wizard.DEFAULT_STATE) <= state.keys()


@pytest.mark.parametrize("wrapper", ["variables", "dev"])
def test_json_supports_both_project017_export_shapes(factory, wrapper):
    root, _ = factory
    path = root / "import.json"
    path.write_text(json.dumps({wrapper: FIELDS}), encoding="utf-8")
    state = {"orchestrator": "ado"}

    assert wizard._import_json_to_state(str(path), state) == 3
    assert {key: state[key] for key in FIELDS} == FIELDS
    assert state["orchestrator"] == "ado"


def test_json_explicit_empty_dev_does_not_fall_back_to_legacy_values(factory):
    root, _ = factory
    path = root / "import.json"
    path.write_text(json.dumps({"dev": {}, "variables": FIELDS}), encoding="utf-8")
    state = {}

    assert wizard._import_json_to_state(str(path), state) == 0
    assert state == {}


def test_gha_mappings_do_not_invent_ado_agent_values(factory):
    root, _ = factory
    path = root / ".env"
    path.write_text("ADMIN_AI_SEARCH_TIER=standard\n", encoding="utf-8")
    state = {}

    assert wizard._import_env_to_state(str(path), state) == 1
    assert state["admin_aiSearchTier"] == "standard"
    assert "adminVMBuildAgentName" not in state
    assert "adminVMBuildAgentPool" not in state
    assert wizard.ENV_MAP["adminVMBuildAgentName"] is None
    assert wizard.ENV_MAP["adminVMBuildAgentPool"] is None


def test_tkinter_saved_project_load_uses_same_source_aware_state(factory, monkeypatch):
    root, snapshot = factory
    write_source(root, "json")
    monkeypatch.setattr(wizard.messagebox, "showinfo", Mock())
    monkeypatch.setattr(wizard.messagebox, "showerror", Mock())
    app = SimpleNamespace(
        state={"unrelated_project_value": "remove"},
        pages=[], _advanced=False, _proj_expanded=False,
        _retheme_all=Mock(), _mark_clean=Mock(),
    )

    wizard.WizardApp._load_project_snapshot(app, str(snapshot), "017")

    assert {key: app.state[key] for key in FIELDS} == FIELDS
    assert "unrelated_project_value" not in app.state
    wizard.messagebox.showerror.assert_not_called()


def test_tkinter_recent_project_opens_snapshot_instead_of_unrelated_current_project(factory):
    root, snapshot = factory
    write_source(root, "json", project="018")
    app = SimpleNamespace(_load_project_snapshot=Mock(), _show=Mock())

    wizard.WizardApp._open_recent_project(app, str(root), "017", "ado")

    app._load_project_snapshot.assert_called_once_with(str(snapshot), "017", notify=False)
    app._show.assert_called_once_with(1)


def test_tkinter_silent_last_project_load_hydrates_current_values(factory, monkeypatch):
    root, _ = factory
    write_source(root, "json")
    monkeypatch.setattr(wizard, "_load_app_settings", lambda: {"last_project": "017"})
    app = SimpleNamespace(
        state={"_save_folder": str(root)},
        pages=[], _advanced=False, _proj_expanded=False, _retheme_all=Mock(),
    )

    wizard.WizardApp._load_last_project_silent(app)

    assert {key: app.state[key] for key in FIELDS} == FIELDS


def test_project_load_does_not_mutate_shared_defaults(factory):
    root, snapshot = factory
    write_source(root, "json")
    before = copy.deepcopy(wizard.DEFAULT_STATE)

    wizard._load_project_state(str(snapshot), str(root))

    assert wizard.DEFAULT_STATE == before


@pytest.mark.parametrize("project", ["017", "018", ""])
@pytest.mark.parametrize("source_format", ["json", "env"])
def test_current_factory_route_overrides_stale_snapshot_without_cross_project_values(
    factory, project, source_format,
):
    root, snapshot = factory
    github = {"GITHUB_NEW_REPO": "example/current", "GITHUB_USERNAME": "example"}
    if source_format == "json":
        write_source(root, "json", {**FIELDS, **github}, project=project)
    else:
        (root.parent / ".env").write_text(
            f'PROJECT_NUMBER="{project}"\nGITHUB_NEW_REPO="example/current"\n'
            'GITHUB_USERNAME="example"\nADMIN_AI_SEARCH_TIER="premium"\n',
            encoding="utf-8",
        )
    state = wizard._load_project_state(str(snapshot), str(root))
    assert state["orchestrator"] == "gha"
    assert state["project_number_000"] == "017"
    assert state["github_new_repo"] == ("example/current" if project == "017" else "")
    assert state["snapshot_only"] == "keep"
