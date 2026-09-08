"""Offline checks for the update launcher's JSON producer and pipeline consumer."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = ROOT / "bootstrap" / "GH-update-aifactory-and-run-project.sh"
IDENTITY = {
    "GITHUB_USERNAME": "example",
    "GITHUB_USE_SSH": "true",
    "GITHUB_TEMPLATE_REPO": "example/template",
    "GITHUB_NEW_REPO": "example/new-repo",
    "GITHUB_NEW_REPO_VISIBILITY": "private",
}
MARKER = (
    '"${PYTHON[@]}" - "$CONFIG_FILE" "$CONFIG_TEMPLATE_FILE" "$RUNNER_LABEL" '
    '"$state_dir/current.env" <<\'PY\'\n'
)


@pytest.mark.parametrize("has_env", [True, False])
def test_inline_merge_backfills_only_missing_github_identity(tmp_path, monkeypatch, has_env):
    launcher = LAUNCHER
    # Execute only the Python merge block, never any shell command or launcher.
    code = launcher.read_text(encoding="utf-8").split(MARKER, 1)[1].split("\nPY", 1)[0]
    active = {
        "dev": {
            "projectPrefix": "", "projectSuffix": "",
            "GITHUB_NEW_REPO": "explicit/keep",
            "GITHUB_USERNAME": "",
            "unmapped": {"keep": [False, 0, ""]},
        },
        "stage_prod": {"projectPrefix": "", "projectSuffix": "", "stage_only": "keep"},
        "extra_section": {"untouched": True},
        "_wizard": {"custom": "keep"},
    }
    original = copy.deepcopy(active)
    template = {
        "dev": {
            "projectPrefix": "esml-", "projectSuffix": "-rg",
            "GITHUB_USERNAME": "", "GITHUB_USE_SSH": "false",
            "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
            "GITHUB_NEW_REPO": "", "GITHUB_NEW_REPO_VISIBILITY": "public",
        },
    }
    active_path = tmp_path / "active.json"
    template_path = tmp_path / "template.json"
    env_path = tmp_path / "current.env"
    active_path.write_text(json.dumps(active), encoding="utf-8")
    template_path.write_text(json.dumps(template), encoding="utf-8")
    if has_env:
        env_path.write_text(
            "\n".join(f"export {key}='{value}' # comment" for key, value in IDENTITY.items())
            + "\nGITHUB_TOKEN=do-not-copy\nAZURE_CLIENT_SECRET=do-not-copy\n",
            encoding="utf-8-sig",
        )
    before = {path: path.read_bytes() for path in (template_path, env_path) if path.exists()}
    monkeypatch.setattr("sys.argv", ["merge", str(active_path), str(template_path), "unit-runner", str(env_path)])
    exec(compile(code, str(launcher), "exec"), {"__name__": "__main__"})
    result = json.loads(active_path.read_text(encoding="utf-8"))
    for section in ("dev", "stage_prod"):
        for key, value in original[section].items():
            assert result[section][key] == value
        for key in IDENTITY:
            if key not in original[section]:
                assert result[section][key] == (
                    IDENTITY[key] if has_env else template["dev"][key]
                )
    assert result["extra_section"] == original["extra_section"]
    assert result["_wizard"] == {"custom": "keep", "orchestrator": "gha"}
    assert result["dev"]["selfHostedRunnerLabel"] == "unit-runner"
    assert result["dev"]["useSelfHostedBuildAgent"] == "true"
    assert all(path.read_bytes() == value for path, value in before.items())
    assert "do-not-copy" not in active_path.read_text(encoding="utf-8")


def test_source_template_contains_only_generic_github_identity():
    template_path = ROOT / "environment_setup" / "aifactory" / "variables.json"
    values = json.loads(template_path.read_text(encoding="utf-8"))["dev"]
    assert {key: values[key] for key in IDENTITY} == {
        "GITHUB_USERNAME": "",
        "GITHUB_USE_SSH": "false",
        "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
        "GITHUB_NEW_REPO": "",
        "GITHUB_NEW_REPO_VISIBILITY": "public",
    }
    assert "_wizard" not in values


def test_pipeline_consumer_ignores_wizard_metadata_and_reserved_github_identity(tmp_path, monkeypatch):
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("json_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values, section = module.selected_values({
        "dev": {"projectPrefix": "", **IDENTITY},
        "_wizard": {"orchestrator": "gha"},
    }, "dev")
    assert section == "dev"
    assert "_wizard" not in values
    github_env = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    applied, skipped = module.apply(values, "github", None)
    assert applied == 1
    assert set(skipped) == set(IDENTITY)
    assert "projectPrefix<<" in github_env.read_text(encoding="utf-8")
    assert "GITHUB_" not in github_env.read_text(encoding="utf-8")
