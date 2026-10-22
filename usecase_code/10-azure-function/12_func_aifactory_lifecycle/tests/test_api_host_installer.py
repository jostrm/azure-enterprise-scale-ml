"""install-factory-api-host.ps1 checks the GitHub token's scopes before it changes anything on the VM."""

import base64
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install-factory-api-host.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")  # the VM runs Windows PowerShell 5.1


def function_text(name):
    match = re.search(rf"^function {name}\b.*?^}}", SCRIPT.read_text(encoding="utf-8"), re.S | re.M)
    assert match, f"{name} is missing from {SCRIPT.name}"
    return match.group(0)


@pytest.mark.parametrize("granted, missing", [
    ("admin:repo_hook, repo, workflow", "read:org"),  # the token that failed gh auth login on 2026-10-22
    ("repo, workflow, read:org", ""),
    ("repo,workflow,write:org", ""),  # write:org and admin:org include read:org
    ("admin:org, workflow, repo", ""),
    ("public_repo, workflow, read:org", "repo"),  # public_repo can't reach the private factory repo
    ("", "repo,workflow,read:org"),
])
def test_missing_scopes_name_every_scope_the_api_host_needs(granted, missing):
    assert SHELL, "this test runs the installer's function in Windows PowerShell or pwsh"
    script = function_text("Get-MissingGitHubScope") + f"\n(Get-MissingGitHubScope '{granted}') -join ','"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == missing


def test_the_token_is_checked_before_folders_or_gh_change():
    text = SCRIPT.read_text(encoding="utf-8")
    check = text.index("Assert-GitHubTokenScope $token")
    assert check < text.index("foreach ($folder in")
    assert check < text.index("| gh auth login")


def test_the_task_runs_the_windowed_api_with_redirected_output_and_waits_for_it():
    """aifactory-config.exe is a windowed app: started with the call operator it gets no output streams, so its web
    server fails at startup, and the task ends at once (observed on 2026-10-22: no port, task Ready, exit 0)."""
    text = SCRIPT.read_text(encoding="utf-8")
    begin = text.index('$start = @"')
    start = text[begin:text.index('"@', begin)]
    assert "& '$exe'" not in start
    assert "Start-Process @arguments" in start
    for part in ("RedirectStandardOutput", "RedirectStandardError", "Wait = `$true", "exit `$api.ExitCode"):
        assert part in start


def test_a_reinstall_stops_the_running_api_before_the_task_starts_it_again():
    text = SCRIPT.read_text(encoding="utf-8")
    stop = text.index("Get-Process -Name aifactory-config")
    assert text.index("Stop-ScheduledTask") < stop < text.index("Start-ScheduledTask")
