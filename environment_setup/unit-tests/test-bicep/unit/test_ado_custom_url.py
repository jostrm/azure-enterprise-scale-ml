"""Offline URL prompt regressions; never launch authentication or a deployment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "bootstrap" / "ADO-update-aifactory-and-run-project.sh"
GIT = shutil.which("git")
GIT_BASH = Path(GIT).parent.parent / "usr" / "bin" / "bash.exe" if GIT else None
BASH = str(GIT_BASH) if GIT_BASH and GIT_BASH.is_file() else shutil.which("bash")
pytestmark = pytest.mark.skipif(not BASH, reason="Bash required for offline prompt checks")


def source():
    return SCRIPT.read_text(encoding="utf-8")


def functions():
    text = source()
    return text[text.index("parse_ado_project_url() {"):
                text.index('\nado_organization="${ADO_ORGANIZATION:-}"')]


def shell(code, stdin="", **environment):
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", code],
        input=stdin.encode("utf-8"), capture_output=True, timeout=20,
        env={**os.environ, "PYTHON_TEST_EXECUTABLE": sys.executable, **environment},
    )
    result.stdout = result.stdout.decode("utf-8")
    result.stderr = result.stderr.decode("utf-8")
    return result


@pytest.mark.parametrize("url,organization,project", [
    ("https://example-org.visualstudio.com/AIFactory", "https://example-org.visualstudio.com", "AIFactory"),
    ("https://example-org.visualstudio.com/AI%20Factory/", "https://example-org.visualstudio.com", "AI Factory"),
    ("https://dev.azure.com/example-org/AIFactory", "https://dev.azure.com/example-org", "AIFactory"),
    ("https://example-org.visualstudio.com/AIFactory/_build", "https://example-org.visualstudio.com", "AIFactory"),
    ("https://dev.azure.com/example-org/AIFactory/_git/Repo", "https://dev.azure.com/example-org", "AIFactory"),
])
def test_project_url_splits_organization_and_project(url, organization, project):
    result = shell(
        'set -euo pipefail\nPYTHON=("$PYTHON_TEST_EXECUTABLE")\n'
        + functions() + '\nparse_ado_project_url "$URL_UNDER_TEST"', URL_UNDER_TEST=url,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{organization}\t{project}"


@pytest.mark.parametrize("url", [
    "", "http://example-org.visualstudio.com/AIFactory", "https://example.com/AIFactory",
    "https://example-org.visualstudio.com.evil.test/AIFactory",
    "https://user:password@example-org.visualstudio.com/AIFactory",
    "https://example-org.visualstudio.com:443/AIFactory", "https://dev.azure.com/example-org",
    "https://example-org.visualstudio.com/", "https://example-org.visualstudio.com/..",
    "https://example-org.visualstudio.com/AIFactory?token=secret",
    "https://example-org.visualstudio.com/AIFactory#fragment",
    "https://example-org.visualstudio.com/AI%0AFactory",
    "https://dev.azure.com/example-org/AI%2FFactory",
])
def test_invalid_urls_fail_without_printing_sensitive_input(url):
    result = shell(
        'PYTHON=("$PYTHON_TEST_EXECUTABLE")\n' + functions()
        + '\nparse_ado_project_url "$URL_UNDER_TEST"', URL_UNDER_TEST=url,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Invalid Azure DevOps project URL" in result.stderr
    assert "password" not in result.stderr and "token=secret" not in result.stderr


def prompt(stdin):
    return shell(
        'set -euo pipefail\nPYTHON=("$PYTHON_TEST_EXECUTABLE")\n'
        'aif_prompt() { printf "%s" "$1" >&2; }\n'
        'aif_error() { printf "%s\\n" "$*" >&2; }\n'
        'aif_warn() { printf "%s\\n" "$*" >&2; }\n'
        + functions()
        + '\nado_organization=https://dev.azure.com/old-org\nado_project=OldProject\n'
        'devops_defaults_prompted=false\nprompt_ado_custom_url_override\n'
        'printf "%s\\n%s\\n%s\\n" "$ado_organization" "$ado_project" "$devops_defaults_prompted"\n',
        stdin,
    )


def test_yes_overrides_both_stale_defaults():
    result = prompt("y\nhttps://example-org.visualstudio.com/AIFactory\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["https://example-org.visualstudio.com", "AIFactory", "true"]
    assert "Do you want to override with a custom Azure DevOps URL? [y/N]" in result.stderr


@pytest.mark.parametrize("answer", ["n\n", "\n", "NO\n"])
def test_no_retains_existing_destination(answer):
    result = prompt(answer)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["https://dev.azure.com/old-org", "OldProject", "false"]


def test_invalid_answers_and_urls_reprompt():
    result = prompt("maybe\ny\nhttps://invalid.example/Project\nhttps://dev.azure.com/new-org/NewProject\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["https://dev.azure.com/new-org", "NewProject", "true"]
    assert "Invalid Azure DevOps project URL" in result.stderr


def test_eof_does_not_hang_or_reuse_the_wrong_destination():
    result = prompt("y\n")
    assert result.returncode != 0 and result.stdout == ""
    assert "Could not read" in result.stderr


def test_prompt_runs_before_auth_and_reuses_settings_writer():
    text = source()
    position = text.index("  prompt_ado_custom_url_override\n")
    save = text.index('if [[ "$devops_defaults_prompted" == "true" ]]; then', position)
    authentication = text.index("configure_pat_auth() {")
    assert position < save < authentication
    assert 'if [[ -t 0 ]]; then\n  prompt_ado_custom_url_override' in text
    assert '{"organization": sys.argv[2], "project": sys.argv[3]}' in text[save:authentication]
    assert 'cp "${BASH_SOURCE[0]}" "$stable_launcher"' in text
    if "aif_snapshot_launcher_bundle" in text:
        assert 'aif_snapshot_launcher_bundle "$bundle_source" "$state_dir/launcher-bundle"' in text
        assert 'aif_restore_launcher_bundle "$state_dir/launcher-bundle" "$REPO_ROOT"' in text
        router = (ROOT / "bootstrap/lib/layout_router.sh").read_text(encoding="utf-8")
        assert "ADO-update-aifactory-and-run-project.sh" in router
    else:
        assert 'cp "$state_dir/ADO-update-aifactory-and-run-project.sh" "$REPO_ROOT/ADO-update-aifactory-and-run-project.sh"' in text


@pytest.mark.parametrize("selection", ["environment", "saved", "cli"])
def test_noninteractive_destination_fallbacks_are_unchanged(tmp_path, selection):
    text = source()
    connection = text[text.index("read_saved_setting() {"):text.index("\nconfigure_pat_auth() {")]
    settings = tmp_path / "ado-settings.json"
    saved = {"organization": "https://saved-org.visualstudio.com", "project": "SavedProject"}
    if selection == "saved":
        settings.write_text(json.dumps(saved), encoding="utf-8")
    result = shell(
        'set -euo pipefail\nPYTHON=("$PYTHON_TEST_EXECUTABLE")\n'
        'aif_section() { :; }\naif_value() { :; }\naif_success() { :; }\n'
        'aif_info() { :; }\naif_warn() { :; }\naif_error() { printf "%s\\n" "$*" >&2; }\n'
        'az() { if [[ "$1" == extension ]]; then return 0; fi; '
        'printf "organization = https://dev.azure.com/cli-org\\nproject = CliProject\\n"; }\n'
        + connection + '\nprintf "%s\\n%s\\n" "$ado_organization" "$ado_project"',
        ADO_ORGANIZATION="https://dev.azure.com/env-org" if selection == "environment" else "",
        ADO_PROJECT="EnvProject" if selection == "environment" else "",
        ADO_SETTINGS_FILE=str(settings),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == {
        "environment": ["https://dev.azure.com/env-org", "EnvProject"],
        "saved": list(saved.values()), "cli": ["https://dev.azure.com/cli-org", "CliProject"],
    }[selection]
    assert settings.exists() == (selection == "saved")


def test_custom_destination_persists_for_future_runs(tmp_path):
    text = source()
    start = text.index('if [[ "$devops_defaults_prompted" == "true" ]]; then')
    block = text[start:text.index("\nconfigure_pat_auth() {", start)]
    settings = tmp_path / "ado-settings.json"
    result = shell(
        'set -euo pipefail\nPYTHON=("$PYTHON_TEST_EXECUTABLE")\naif_success() { :; }\n'
        'devops_defaults_prompted=true\nADO_SETTINGS_FILE="$TEST_SETTINGS_FILE"\n'
        'ado_organization=https://example-org.visualstudio.com\nado_project="AI Factory"\n' + block,
        TEST_SETTINGS_FILE=str(settings),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "organization": "https://example-org.visualstudio.com", "project": "AI Factory",
    }


def test_launcher_bash_syntax():
    result = subprocess.run(
        [BASH, "-n"], input=source().encode("utf-8"), capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
