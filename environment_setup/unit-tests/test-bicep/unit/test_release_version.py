"""Offline release selector tests; no Git/network/deployment execution."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("bootstrap_release_version", ROOT / "bootstrap/lib/release_version.py")
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)


@pytest.mark.parametrize("value,expected", [
    ("124", "release/v1.24"), ("125", "release/v1.25"), ("126", "release/v1.26"),
    ("1.100", "release/v1.100"), ("10.2", "release/v10.2"), ("main", "main"),
])
def test_numeric_formula_and_unambiguous_future_versions(value, expected):
    assert rv.branch_for(value) == expected
    assert rv.version_for_branch(expected) == rv.normalize(value)


@pytest.mark.parametrize("value", ["", "1240", "12", "v1.24", "release/v1.24", "main;echo", 124, None])
def test_invalid_versions(value):
    with pytest.raises(ValueError):
        rv.normalize(value)


def test_explicit_cli_environment_and_branch_must_agree():
    assert rv.select("125", environ={"AIFACTORY_VERSION": "1.25", "AIF_SUBMODULE_BRANCH": "release/v1.25"})["requested_version"] == "125"
    for env in ({"AIFACTORY_VERSION": "124"}, {"AIF_SUBMODULE_BRANCH": "main"}):
        with pytest.raises(ValueError, match="Conflicting"):
            rv.select("125", environ=env)


def test_new_default_and_saved_version_inheritance(tmp_path):
    assert rv.select(environ={})["requested_version"] == "124"
    selected = {**rv.select("1.100", environ={}), "resolved_ref": "a" * 40}
    rv.save(tmp_path, selected)
    assert rv.saved_version(tmp_path) == "1.100"
    assert rv.select(saved=rv.saved_version(tmp_path), environ={})["requested_version"] == "1.100"
    assert json.loads((tmp_path / rv.STATE_PATH).read_text())["resolved_ref"] == "a" * 40


def test_existing_unknown_factory_fails_instead_of_downgrading(tmp_path):
    (tmp_path / "aifactory").mkdir()
    with pytest.raises(ValueError, match="unknown"):
        rv.saved_version(tmp_path)


def test_update_default_main_and_project_only_inheritance_are_distinct():
    ado = (ROOT / "bootstrap/ADO-update-aifactory-and-run-project.sh").read_text(
        encoding="utf-8"
    )
    github = (ROOT / "bootstrap/GH-update-aifactory-and-run-project.sh").read_text(
        encoding="utf-8"
    )
    alias = (ROOT / "bootstrap/GHA-update-aifactory-and-run-project.sh").read_text(
        encoding="utf-8"
    )
    for source in (ado, github):
        assert 'version_default=""' in source
        assert (
            '[[ "$project_only" == "true" ]] || '
            'version_default="${AIF_UPDATE_DEFAULT_VERSION:-main}"'
            in source
        )
        assert (
            'aif_version_prepare "$REPO_ROOT" "$project_only" false "$version_default"'
            in source
        )
    assert 'AIF_UPDATE_DEFAULT_VERSION="${AIF_UPDATE_DEFAULT_VERSION:-main}"' in alias
    assert "exec bash" in alias
    assert "GH-update-aifactory-and-run-project.sh" in alias


def test_explicit_main_bypasses_unknown_existing_factory(tmp_path, monkeypatch, capsys):
    (tmp_path / "aifactory").mkdir()
    monkeypatch.setattr(
        rv.sys,
        "argv",
        [
            "release_version.py",
            "--root",
            str(tmp_path),
            "--aifactory-version",
            "main",
            "--non-interactive",
        ],
    )
    monkeypatch.setattr(
        rv,
        "resolve",
        lambda selected, read, **kwargs: {
            **selected,
            "resolved_ref": "a" * 40,
        },
    )
    monkeypatch.setattr(
        rv.subprocess,
        "run",
        Mock(return_value=type("Result", (), {"stdout": rv.CONTRACT})()),
    )
    for key in ("AIFACTORY_VERSION", "AIF_SUBMODULE_BRANCH", "AIF_SUBMODULE_REF"):
        monkeypatch.delenv(key, raising=False)
    rv.main()
    output = capsys.readouterr()
    assert "export AIFACTORY_VERSION=main" in output.out
    assert "export AIF_SUBMODULE_BRANCH=main" in output.out


def test_resolve_binds_published_exact_ref_and_rejects_conflict():
    read = Mock(return_value="a" * 40 + "\trefs/heads/release/v1.25")
    selected = rv.resolve(rv.select("125", environ={}), read)
    assert selected["resolved_ref"] == "a" * 40
    read.return_value = "b" * 40 + "\trefs/heads/release/v1.25"
    with pytest.raises(ValueError, match="conflicts"):
        rv.resolve(selected, read)
    read.return_value = ""
    with pytest.raises(ValueError, match="not published"):
        rv.resolve(rv.select("125", environ={}), read)


def test_noninteractive_selection_never_prompts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rv.sys, "argv", ["release_version.py", "--root", str(tmp_path), "--non-interactive"])
    monkeypatch.setattr(rv.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("Unexpected prompt")))
    monkeypatch.setattr(rv, "resolve", lambda selected, read, **kwargs: {**selected, "resolved_ref": "a" * 40})
    monkeypatch.setattr(rv.subprocess, "run", Mock(return_value=type("Result", (), {"stdout": rv.CONTRACT})()))
    for key in ("AIFACTORY_VERSION", "AIF_SUBMODULE_BRANCH", "AIF_SUBMODULE_REF"):
        monkeypatch.delenv(key, raising=False)
    rv.main()
    output = capsys.readouterr()
    assert "export AIFACTORY_VERSION=124" in output.out
    assert "Hit ENTER" not in output.err


def test_interactive_default_prompt_tracks_inherited_version(tmp_path, monkeypatch, capsys):
    rv.save(tmp_path, {**rv.select("125", environ={}), "resolved_ref": "a" * 40})
    monkeypatch.setattr(rv.sys, "argv", ["release_version.py", "--root", str(tmp_path)])
    monkeypatch.setattr(rv.sys.stdin, "isatty", lambda: True)
    prompt = Mock(return_value="")
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(rv, "resolve", lambda selected, read, **kwargs: {**selected, "resolved_ref": "a" * 40})
    monkeypatch.setattr(rv.subprocess, "run", Mock(return_value=type("Result", (), {"stdout": rv.CONTRACT})()))
    for key in ("AIFACTORY_VERSION", "AIF_SUBMODULE_BRANCH", "AIF_SUBMODULE_REF"):
        monkeypatch.delenv(key, raising=False)
    rv.main()
    output = capsys.readouterr()
    assert "will be 125, meaning branch release/v1.25" in output.err
    assert "Hit ENTER if OK" in output.err
    assert "export AIFACTORY_VERSION=125" in output.out


def test_existing_exact_ref_override_accepts_only_verified_published_ancestor(tmp_path):
    selected = rv.select("125", environ={"AIF_SUBMODULE_REF": "a" * 40})
    read = Mock(side_effect=["b" * 40 + "\trefs/heads/release/v1.25", ""])
    assert rv.resolve(selected, read, repository=tmp_path)["resolved_ref"] == "a" * 40
    assert read.call_args.args[0][-4:] == ["merge-base", "--is-ancestor", "a" * 40, "b" * 40]
    read.side_effect = ["b" * 40 + "\trefs/heads/release/v1.25", rv.subprocess.CalledProcessError(1, "git")]
    with pytest.raises(ValueError, match="not a verified published ancestor"):
        rv.resolve(selected, read, repository=tmp_path)
