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


FAKE_AZ = r"""
$global:calls = @()
function az {
    $global:calls += "$env:AZURE_CONFIG_DIR|$($args -join ' ')"
    $marker = Join-Path $env:AZURE_CONFIG_DIR 'signed-in'
    if ($args[0] -eq 'login') { Set-Content $marker '' }
    if ($args[0] -eq 'account' -and $args[1] -eq 'show') {
        if (Test-Path $marker) { $global:LASTEXITCODE = 0; return 'sub-current' }
        Write-Error 'Please run az login to setup account.'; $global:LASTEXITCODE = 1; return
    }
    $global:LASTEXITCODE = 0
}
"""


def run_initialize(tmp_path, signed_in, subscription):
    assert SHELL, "this test runs the installer's function in Windows PowerShell or pwsh"
    folder = tmp_path / "azure-cli"
    if signed_in:
        folder.mkdir()
        (folder / "signed-in").write_text("")
    script = ("$ErrorActionPreference = 'Stop'\n" + FAKE_AZ + function_text("Initialize-ApiAzureCli")
              + f"\nInitialize-ApiAzureCli '{folder}' '{subscription}'\n$global:calls -join [char]10")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return [line.split("|", 1) for line in result.stdout.strip().splitlines()], str(folder)


def test_the_api_signs_in_its_own_az_profile_with_the_managed_identity(tmp_path):
    """SYSTEM's shared az profile was emptied three times on 2026-10-23/24 while an Azure DevOps agent (running as
    SYSTEM on the same VM) ran Azure CLI tasks; the Factory API's next token request failed and stopped a factory
    creation (stage-execution-interrupted). The API's own AZURE_CONFIG_DIR keeps its login apart from other jobs."""
    calls, folder = run_initialize(tmp_path, signed_in=False, subscription="sub-factory")
    assert all(directory == folder for directory, _ in calls)
    commands = [command for _, command in calls]
    assert commands[0].startswith("account show")
    assert "login --identity --allow-no-subscriptions --output none" in commands
    assert commands[-1] == "account set --subscription sub-factory"


def test_an_api_profile_that_is_signed_in_is_kept(tmp_path):
    calls, _ = run_initialize(tmp_path, signed_in=True, subscription="")
    assert [command for _, command in calls] == ["account show --query id -o tsv"]


def test_every_api_start_uses_and_signs_in_its_own_az_profile_before_the_api_runs():
    text = SCRIPT.read_text(encoding="utf-8")
    begin = text.index('$start = @"')
    start = text[begin:text.index('"@', begin)]
    assert "function Initialize-ApiAzureCli {$((Get-Command Initialize-ApiAzureCli).Definition)}" in start
    call = start.index("Initialize-ApiAzureCli '$AzureConfigDir' '$SubscriptionId'")
    assert call < start.index("Start-Process @arguments")
    assert "Join-Path $InstallRoot 'azure-cli'" in text  # inside the SYSTEM/Administrators-only install root
