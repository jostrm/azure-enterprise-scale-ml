import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import release_version as rv, simple_mode
from src.ticket_connectors import TicketError


@pytest.mark.parametrize("value,canonical,branch", [
    ("124", "124", "release/v1.24"), ("125", "125", "release/v1.25"),
    ("1.24", "124", "release/v1.24"), ("100", "100", "release/v1.0"),
    ("999", "999", "release/v9.99"), ("1.100", "1.100", "release/v1.100"),
    ("10.2", "10.2", "release/v10.2"), ("main", "main", "main"),
])
def test_versions_are_formula_not_release_table(value, canonical, branch):
    assert rv.normalize(value) == canonical
    assert rv.branch_for(value) == branch
    assert rv.version_for_branch(branch) == canonical


@pytest.mark.parametrize("value", ["", "12", "1240", "1.024", "01.24", "v1.24", "release/v1.24",
                                      "main ", "Main", "main;whoami", "-124", 124, True])
def test_reject_ambiguous_or_unsafe_explicit_values(value):
    with pytest.raises(TicketError):
        rv.select(value)


def test_default_inheritance_and_explicit_conflicts(monkeypatch):
    monkeypatch.setenv("AIFACTORY_VERSION", "999")
    assert rv.select()["requested_version"] == "124"
    assert rv.select(saved="125")["requested_version"] == "125"
    assert rv.select("126", saved="125")["requested_version"] == "126"
    assert rv.select("125", environ={"AIF_SUBMODULE_BRANCH": "release/v1.25"})["branch"] == "release/v1.25"
    with pytest.raises(TicketError, match="Conflicting"):
        rv.select("125", environ={"AIFACTORY_VERSION": "124"})
    with pytest.raises(TicketError, match="Conflicting"):
        rv.select("125", environ={"AIF_SUBMODULE_BRANCH": "main"})


def write_saved(root, value="125"):
    selected = {**rv.select(value), "resolved_ref": "a" * 40}
    path = root / rv.STATE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(selected), encoding="utf-8")
    return path


def test_saved_record_overrides_legacy_configuration_without_mutating_it(tmp_path):
    path = write_saved(tmp_path, "1.100")
    legacy = path.parent / "factory_state.json"
    legacy.write_text(json.dumps({"version_major": "1", "version_minor": "24", "raw": "preserve"}))
    before = legacy.read_bytes()
    assert rv.saved_version(tmp_path) == "1.100"
    assert legacy.read_bytes() == before


@pytest.mark.parametrize("data,expected", [
    ({"version_major": "1", "version_minor": "25"}, "125"),
    ({"variables": {"aifactory_version_major": "10", "aifactory_version_minor": "2"}}, "10.2"),
    ({"version_branch": "main", "version_major": "1", "version_minor": "24"}, "main"),
])
def test_existing_raw_versions_are_inherited(tmp_path, data, expected):
    path = tmp_path / "aifactory" / "config-wizard" / "factory_state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data))
    assert rv.saved_version(tmp_path) == expected


def test_unknown_existing_factory_never_defaults_to_124(tmp_path):
    (tmp_path / "aifactory").mkdir()
    with pytest.raises(TicketError, match="unknown"):
        rv.saved_version(tmp_path)


def test_project_only_preserves_installed_commit_and_blocks_version_change(tmp_path):
    write_saved(tmp_path)
    cli = SimpleNamespace(read=Mock(return_value="b" * 40))
    selected = rv.project_selection(tmp_path, None, False, cli)
    assert selected["requested_version"] == "125"
    assert selected["resolved_ref"] == "b" * 40
    assert cli.read.call_args.args[1][-2:] == ["rev-parse", "HEAD"]
    with pytest.raises(TicketError, match="requires Patch"):
        rv.project_selection(tmp_path, "124", False, cli)
    assert cli.read.call_count == 1


def test_patch_resolves_published_ref_and_requires_contract(tmp_path):
    write_saved(tmp_path)
    cli = SimpleNamespace(read=Mock(side_effect=[
        "b" * 40 + "\trefs/heads/release/v1.26", rv.CONTRACT, rv.CONTRACT,
    ]))
    selected = rv.project_selection(tmp_path, "126", True, cli)
    assert selected["resolved_ref"] == "b" * 40
    assert all("b" * 40 + ":" in call.args[1][-1] for call in cli.read.call_args_list[1:])
    cli.read.side_effect = ["b" * 40 + "\trefs/heads/release/v1.26", "# old helper"]
    with pytest.raises(TicketError, match="contract"):
        rv.project_selection(tmp_path, "126", True, cli)


@pytest.mark.parametrize("remote", ["", "a" * 40 + "\trefs/heads/main", "bad\trefs/heads/release/v1.24"])
def test_missing_or_wrong_branch_never_falls_back(remote):
    with pytest.raises(TicketError, match="not published"):
        rv.resolve(rv.select(), SimpleNamespace(read=Mock(return_value=remote)))


def test_conflicting_explicit_commit_is_rejected():
    selected = rv.select("125", environ={"AIF_SUBMODULE_REF": "a" * 40})
    with pytest.raises(TicketError, match="conflicts"):
        rv.resolve(selected, SimpleNamespace(read=Mock(return_value="b" * 40 + "\trefs/heads/release/v1.25")))


def test_materialize_is_exact_per_job_archive_not_global_checkout(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bootstrap/GHA-create-new-aifactory-scaleset.sh", "# reviewed source")
    run = Mock(return_value=SimpleNamespace(stdout=buffer.getvalue()))
    monkeypatch.setattr(subprocess, "run", run)
    source = simple_mode.SourceReadiness(None, tmp_path / "main" / "bootstrap" / "GHA-create-new-aifactory-scaleset.sh")
    destination = tmp_path / "job" / "source"
    script = source.materialize({"commit": "a" * 40}, destination, {"git": "git"})
    assert script.read_text() == "# reviewed source"
    assert "archive" in run.call_args.args[0]
    assert "a" * 40 in run.call_args.args[0]
    assert not (tmp_path / "main").exists()


def test_materialize_rejects_traversal(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../outside.sh", "not allowed")
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(stdout=buffer.getvalue())))
    with pytest.raises(ValueError, match="unsafe"):
        simple_mode.SourceReadiness(None).materialize({"commit": "a" * 40}, tmp_path / "job", {"git": "git"})
    assert not (tmp_path / "outside.sh").exists()


def test_generic_published_source_is_read_only_and_enforces_lifecycle_contract(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    (root / ".git").mkdir()
    cli = SimpleNamespace(read=Mock(side_effect=[
        "a" * 40 + "\trefs/heads/release/v1.25", "", rv.CONTRACT, "AIFACTORY_LIFECYCLE_CONTRACT=1",
    ]))
    source = rv.published_source("125", cli, root, required_paths={
        "bootstrap/lib/factory_lifecycle.py": "AIFACTORY_LIFECYCLE_CONTRACT=1",
    })
    assert source == {**rv.select("125"), "resolved_ref": "a" * 40, "source_root": str(root)}
    assert list(root.iterdir()) == [root / ".git"]
    assert all("checkout" not in call.args[1] and "fetch" not in call.args[1] for call in cli.read.call_args_list)


def test_generic_source_materialization_only_mutates_private_checkout(tmp_path):
    root, target = tmp_path / "dirty-main", tmp_path / "job" / "source"
    root.mkdir()
    (root / ".git").mkdir()
    dirty = root / "keep.txt"
    dirty.write_text("keep uncommitted work")
    runner = Mock(side_effect=[
        SimpleNamespace(returncode=0, stdout=value) for value in ("", "", "", "b" * 40, "")
    ])
    assert rv.materialize_source(root, "b" * 40, target, runner=runner) == str(target)
    commands = [call.args[0] for call in runner.call_args_list]
    assert "--local" in commands[0] and "--no-hardlinks" in commands[0]
    assert commands[0][-2:] == [str(root), str(target)]
    assert all(str(root) not in command for command in commands[1:])
    assert all("core.hooksPath=" in command[2] for command in commands)
    assert dirty.read_text() == "keep uncommitted work"
    assert all(call.kwargs["stdin"] == subprocess.DEVNULL and call.kwargs["shell"] is False
               for call in runner.call_args_list)


def test_generic_source_materialization_rejects_existing_or_nested_destination(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    runner = Mock(side_effect=AssertionError("No git should run"))
    with pytest.raises(TicketError, match="isolated"):
        rv.materialize_source(root, "a" * 40, root / "nested", runner=runner)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(TicketError, match="isolated"):
        rv.materialize_source(root, "a" * 40, existing, runner=runner)
