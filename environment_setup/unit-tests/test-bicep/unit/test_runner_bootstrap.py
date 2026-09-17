"""Offline runner contract tests: no provider calls or software installations."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
POWERSHELL = shutil.which("pwsh")
BASH = (
    str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe")
    if os.name == "nt" else shutil.which("bash")
)


def quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell_stream_text(value: str) -> str:
    if not value.startswith("#< CLIXML"):
        return value
    value = re.sub(r"<[^>]+>", " ", value.partition("\n")[2])
    value = html.unescape(value)
    value = re.sub(r"_x([0-9a-fA-F]{4})_", lambda match: chr(int(match.group(1), 16)), value)
    value = re.sub(r"\x1b\[[0-9;]*m", "", value)
    value = re.sub(r"\s+\|\s+", " ", value)
    return " ".join(value.split())


def test_powershell_stream_text_normalizes_wrapped_clixml() -> None:
    stream = '#< CLIXML\n<Objs><S S="Error">left_x000A_</S><S S="Error"> | untouched &amp; safe</S></Objs>'
    assert powershell_stream_text(stream) == "left untouched & safe"


@unittest.skipUnless(POWERSHELL, "PowerShell is required for offline function tests")
class RunnerPowerShellTests(unittest.TestCase):
    def run_ps(self, body: str, *, success: bool = True) -> subprocess.CompletedProcess[str]:
        source = (
            "$ErrorActionPreference = 'Stop'\n"
            f". {quote(LIB / 'runner-prerequisites.ps1')}\n"
            f". {quote(LIB / 'runner-registration.ps1')}\n"
            "$env:OS = 'Windows_NT'\n"
            "function Invoke-WebRequest { throw 'UNMOCKED NETWORK REQUEST' }\n"
            "function Invoke-RestMethod { throw 'UNMOCKED NETWORK REQUEST' }\n"
            "function Start-Process { throw 'UNMOCKED PROCESS INSTALLER' }\n"
            + body
        )
        encoded = base64.b64encode(source.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        result.stdout = powershell_stream_text(result.stdout)
        result.stderr = powershell_stream_text(result.stderr)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_powershell_scripts_parse(self) -> None:
        self.run_ps(
            f"""
foreach ($path in @({quote(LIB / 'runner-prerequisites.ps1')}, {quote(LIB / 'runner-registration.ps1')})) {{
    $errors = $null; $tokens = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors) {{ throw ($errors | Out-String) }}
}}
"""
        )

    def test_existing_version_is_checked_without_installation(self) -> None:
        result = self.run_ps(
            f"""
$spec = @{{Name='python'; Minimum='3.10'; Arguments=@('--version'); Exact=$true; Paths=@({quote(sys.executable)})}}
$valid = Test-AifRunnerTool $spec
$spec.Minimum = '99.0'
$invalid = Test-AifRunnerTool $spec
$spec.Paths = @('Z:\\not-an-existing-python.exe')
$missing = Test-AifRunnerTool $spec
@($valid, $invalid, $missing) | ConvertTo-Json -Compress
"""
        )
        self.assertEqual([x["Status"] for x in json.loads(result.stdout)], ["ready", "invalid", "missing"])

    def test_git_bash_never_uses_wsl_shim(self) -> None:
        self.run_ps("""
$spec = Get-AifRunnerToolSpecs | Where-Object Name -eq bash
if (-not $spec.Exact -or $spec.Paths[0] -notlike '*\\Git\\bin\\bash.exe') { throw 'Wrong Bash selection' }
function Get-Command { throw 'Exact Git Bash must not search PATH / WSL' }
function Test-Path { $false }
if ((Test-AifRunnerTool $spec).Status -ne 'missing') { throw 'Expected missing Git Bash' }
""")

    def test_check_with_valid_tools_never_changes_machine(self) -> None:
        self.run_ps("""
function Test-AifRunnerTool { param($Spec)
    [pscustomobject]@{Name=$Spec.Name; Status='ready'; Path='C:\\tools\\tool.exe'; Version='99.0'}
}
function Install-AifMissingTool { throw 'INSTALL CALLED' }
function Set-AifRunnerMachinePath { throw 'PATH MUTATION CALLED' }
if ((Invoke-AifRunnerPrerequisites).Status -ne 'ready') { throw 'Expected readiness' }
""")

    def test_check_missing_tools_is_read_only(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerTool { param($Spec)
    [pscustomobject]@{Name=$Spec.Name; Status='missing'; Path=''; Version=''}
}
function Install-AifMissingTool { throw 'INSTALL CALLED' }
Invoke-AifRunnerPrerequisites
""", success=False)
        self.assertIn("check mode made no changes", result.stderr)
        self.assertNotIn("INSTALL CALLED", result.stderr)

    def test_invalid_install_blocks_even_with_install_missing(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerTool { param($Spec)
    [pscustomobject]@{Name=$Spec.Name; Status='invalid'; Path='C:\\old\\tool.exe'; Version='0.1'}
}
function Install-AifMissingTool { throw 'INSTALL CALLED' }
Invoke-AifRunnerPrerequisites -InstallMissing
""", success=False)
        self.assertIn("no upgrades or replacements", result.stderr)
        self.assertNotIn("INSTALL CALLED", result.stderr)

    def test_missing_install_must_pass_post_install_verification(self) -> None:
        result = self.run_ps("""
function Get-AifRunnerToolSpecs { @{ Name='gh' } }
function Test-AifRunnerTool { param($Spec)
    [pscustomobject]@{Name='gh'; Status='missing'; Path=''; Version=''}
}
function Test-AifRunnerElevation { $true }
function Install-AifMissingTool { param($Name) }
function Set-AifRunnerPrerequisiteMarker { }
function Set-AifRunnerMachinePath { $false }
Invoke-AifRunnerPrerequisites -InstallMissing
""", success=False)
        self.assertIn("post-install verification", result.stderr)

    def test_only_missing_tool_installed_and_verified(self) -> None:
        self.run_ps("""
$script:installed = @()
function Get-AifRunnerToolSpecs { @{Name='gh'}, @{Name='python'} }
function Test-AifRunnerTool { param($Spec)
    $status = if ($Spec.Name -eq 'gh' -and $script:installed.Count -eq 0) {'missing'} else {'ready'}
    [pscustomobject]@{Name=$Spec.Name; Status=$status; Path='C:\\tools\\tool.exe'; Version='99.0'}
}
function Test-AifRunnerElevation { $true }
function Install-AifMissingTool { param($Name) $script:installed += $Name }
function Set-AifRunnerPrerequisiteMarker { }
function Set-AifRunnerMachinePath { $false }
$report = Invoke-AifRunnerPrerequisites -InstallMissing
if ($report.Status -ne 'ready' -or ($script:installed -join ',') -ne 'gh') { throw 'Unexpected installation' }
""")

    def test_scoped_windows_is_explicitly_blocked(self) -> None:
        result = self.run_ps("Invoke-AifRunnerPrerequisites -Scoped", success=False)
        self.assertIn("Scoped enrollment requires Linux", result.stderr)

    def test_official_installer_does_not_depend_on_chocolatey_mirror(self) -> None:
        self.run_ps("""
function New-Item { }
function Get-AifOfficialReleaseAsset { [pscustomobject]@{Version='2.99.0'; Name='gh.msi'; Url='https://github.com/cli/cli/releases/download/v2.99.0/gh.msi'; Digest='sha256:fixture'} }
function Get-Command { throw 'Chocolatey must not be consulted' }
function Test-Path { $false }
$script:verified = $false
function Save-AifVerifiedDownload { $script:verified = $true }
function Start-Process { param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru)
    if (-not $script:verified -or $FilePath -ne 'msiexec.exe' -or '/norestart' -notin $ArgumentList) { throw 'Unverified/rebooting installer' }
    [pscustomobject]@{ExitCode=0}
}
Install-AifMissingTool gh
""")

    def test_download_checksum_is_verified_before_installing(self) -> None:
        result = self.run_ps("""
function Invoke-WebRequest { }
function Get-FileHash { [pscustomobject]@{Hash=('b' * 64)} }
Save-AifVerifiedDownload 'https://github.com/Azure/bicep/releases/download/v0.44.1/bicep-win-x64.exe' `
    'not-created.exe' ('sha256:' + ('a' * 64)) ''
""", success=False)
        self.assertIn("SHA256 verification failed", result.stderr)

    def test_official_digest_is_sufficient_for_unsigned_msi(self) -> None:
        self.run_ps("""
function Invoke-WebRequest { }
function Get-FileHash { [pscustomobject]@{Hash=('a' * 64)} }
function Get-AuthenticodeSignature { throw 'Verified official SHA256 does not require another trust chain' }
Save-AifVerifiedDownload 'https://github.com/cli/cli/releases/download/v2.99.0/gh.msi' `
    'not-created.msi' ('sha256:' + ('a' * 64)) 'GitHub'
""")

    def test_exact_registration_scope_and_name_for_both_providers(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
            path = Path(directory)
            for provider, filename, data, url, pool in (
                ("ado", ".agent", {"serverUrl": "https://dev.azure.com/org/", "poolName": "Default", "agentName": "vm"}, "https://dev.azure.com/org", "Default"),
                ("gha", ".runner", {"gitHubUrl": "https://github.com/org/repo", "agentName": "vm"}, "https://github.com/org/repo", ""),
            ):
                with self.subTest(provider=provider):
                    (path / filename).write_text(json.dumps(data), encoding="utf-8")
                    self.run_ps(f"""
if (-not (Test-AifRunnerConfiguration {quote(provider)} {quote(path)} {quote(url)} {quote(pool)} 'vm')) {{ throw 'Expected reuse' }}
""")
                    for wrong_url, wrong_pool, wrong_name in (
                        (url + "-other", pool, "vm"),
                        (url, pool, "other-vm"),
                        *(([(url, "OtherPool", "vm")]) if provider == "ado" else []),
                    ):
                        result = self.run_ps(
                            f"Test-AifRunnerConfiguration {quote(provider)} {quote(path)} {quote(wrong_url)} {quote(wrong_pool)} {quote(wrong_name)}",
                            success=False,
                        )
                        self.assertIn("Refusing reconfiguration", result.stderr)

    def test_service_selection_is_bound_to_exact_folder(self) -> None:
        for provider, prefix, exe in (("ado", "vstsagent.", "AgentService.exe"), ("gha", "actions.runner.", "RunnerService.exe")):
            with self.subTest(provider=provider):
                self.run_ps(f"""
function Get-CimInstance {{
    [pscustomobject]@{{Name='{prefix}other'; PathName='"C:\\other\\bin\\{exe}"'; State='Running'}}
    [pscustomobject]@{{Name='{prefix}mine'; PathName='"C:\\owned\\bin\\{exe}"'; State='Running'}}
}}
function Test-Path {{ $false }}
$service = Get-AifOwnedRunnerService '{provider}' 'C:\\owned'
if ($service.Name -ne '{prefix}mine') {{ throw 'Selected a different runner service' }}
""")

    def test_stale_provider_agent_id_is_not_reused(self) -> None:
        for remote_id in ("0", "99"):
            result = self.run_ps(f"""
function Test-Path {{ $true }}
function Get-Content {{ '{{"serverUrl":"https://dev.azure.com/org","agentName":"vm","poolName":"Default","agentId":7}}' }}
Test-AifRunnerConfiguration ado 'C:\\fixture' https://dev.azure.com/org Default vm '{remote_id}'
""", success=False)
            self.assertIn("different provider agent ID", result.stderr)

    def test_running_service_is_not_interrupted(self) -> None:
        self.run_ps("""
function Start-Service { throw 'Running service was interrupted' }
Start-AifOwnedRunnerService ([pscustomobject]@{Name='vstsagent.owned'; State='Running'; StartMode='Auto'})
""")

    def test_only_owned_stopped_service_is_started(self) -> None:
        self.run_ps("""
$script:started = @()
function Start-Service { param($Name) $script:started += $Name }
function Get-Service { param($Name)
    $service = [pscustomobject]@{Name=$Name}
    $service | Add-Member ScriptMethod WaitForStatus { param($state,$timeout) }
    $service
}
Start-AifOwnedRunnerService ([pscustomobject]@{Name='actions.runner.mine'; State='Stopped'; StartMode='Auto'})
if (($script:started -join ',') -ne 'actions.runner.mine') { throw 'Unexpected service start' }
""")

    def test_disabled_service_is_not_reconfigured(self) -> None:
        result = self.run_ps("""
function Start-Service { throw 'START CALLED' }
Start-AifOwnedRunnerService ([pscustomobject]@{Name='vstsagent.owned'; State='Stopped'; StartMode='Disabled'})
""", success=False)
        self.assertIn("resolve this explicitly", result.stderr)
        self.assertNotIn("START CALLED", result.stderr)

    def test_online_runner_still_checks_prerequisites_without_registration(self) -> None:
        self.run_ps("""
function Test-AifRunnerConfiguration { $true }
function Get-AifOwnedRunnerService { [pscustomobject]@{Name='vstsagent.mine'; State='Running'} }
function Test-Path { $false }
function Start-Service { throw 'Do not interrupt online runner' }
function Invoke-WebRequest { throw 'Do not download on reuse' }
$prereqs = 'function Invoke-AifRunnerPrerequisites { [pscustomobject]@{Status="ready"; PathChanged=$false} }'
Invoke-AifWindowsRunnerRegistration -Provider ado -AgentName vm -AgentPool Default `
    -RegistrationUrl https://dev.azure.com/org -PrerequisitesScript $prereqs -InstallMissing $true
""")

    def test_wrong_scope_blocks_before_prerequisite_install(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerConfiguration { throw 'WRONG SCOPE' }
Invoke-AifWindowsRunnerRegistration -Provider gha -AgentName vm `
    -RegistrationUrl https://github.com/org/repo `
    -PrerequisitesScript 'throw "PREREQUISITES CALLED"' -InstallMissing $true
""", success=False)
        self.assertIn("WRONG SCOPE", result.stderr)
        self.assertNotIn("PREREQUISITES CALLED", result.stderr)

    def test_remote_runner_cannot_be_taken_over_by_unregistered_folder(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerConfiguration { $false }
Invoke-AifWindowsRunnerRegistration -Provider gha -AgentName vm -RemoteExists $true `
    -RegistrationUrl https://github.com/org/repo -InstallMissing $true
""", success=False)
        self.assertIn("Refusing to replace or take over", result.stderr)

    def test_github_package_without_official_checksum_is_rejected(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerConfiguration { $false }
function Test-Path { $false }
function New-Item { throw 'MUTATION CALLED' }
$prereqs = 'function Invoke-AifRunnerPrerequisites { [pscustomobject]@{Status="ready"; PathChanged=$false} }'
Invoke-AifWindowsRunnerRegistration -Provider gha -AgentName vm `
    -RegistrationUrl https://github.com/org/repo -RegistrationToken 'test-only-placeholder' `
    -PackageUrl https://github.com/actions/runner/releases/download/v2.330.0/actions-runner-win-x64-2.330.0.zip `
    -PrerequisitesScript $prereqs -InstallMissing $true
""", success=False)
        self.assertIn("Official runner SHA256 metadata is required", result.stderr)
        self.assertNotIn("MUTATION CALLED", result.stderr)

    def test_pending_path_refresh_is_blocked_until_service_was_restarted(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerConfiguration { $true }
function Get-AifOwnedRunnerService { [pscustomobject]@{Name='vstsagent.mine'; State='Running'; ProcessId=42} }
function Test-Path { $true }
function Get-Content { '{"ChangedUtc":"2026-01-02T00:00:00Z"}' }
function Get-Process { [pscustomobject]@{StartTime=[DateTime]::Parse('2026-01-01T00:00:00Z')} }
function Start-Service { throw 'Do not interrupt online runner' }
$prereqs = 'function Invoke-AifRunnerPrerequisites { [pscustomobject]@{Status="ready"; PathChanged=$false} }'
Invoke-AifWindowsRunnerRegistration -Provider ado -AgentName vm -AgentPool Default `
    -RegistrationUrl https://dev.azure.com/org -PrerequisitesScript $prereqs -InstallMissing $true
""", success=False)
        self.assertIn("running service", result.stderr)
        self.assertIn("left untouched", result.stderr)

    def test_check_registration_never_starts_stopped_service(self) -> None:
        self.run_ps("""
function Test-AifRunnerConfiguration { $true }
function Get-AifOwnedRunnerService { [pscustomobject]@{Name='vstsagent.mine'; State='Stopped'; StartMode='Auto'} }
function Start-Service { throw 'Check cannot start service' }
$prereqs = 'function Invoke-AifRunnerPrerequisites { [pscustomobject]@{Status="ready"; PathChanged=$false} }'
Invoke-AifWindowsRunnerRegistration -Provider ado -AgentName vm -AgentPool Default `
    -RegistrationUrl https://dev.azure.com/org -PrerequisitesScript $prereqs -InstallMissing $false
""")

    def test_azure_cli_version_is_selected_by_key(self) -> None:
        result = self.run_ps("""
$spec = Get-AifRunnerToolSpecs | Where-Object Name -eq az
if (($spec.Arguments -join ',') -ne 'version,--output,json') { throw 'Avoid cmd.exe query quoting' }
function Get-Command { [pscustomobject]@{Source='Invoke-AzureVersion'} }
function Invoke-AzureVersion { $global:LASTEXITCODE = 0; '{"dependency":"0.1.0","azure-cli":"2.78.0"}' }
Test-AifRunnerTool $spec | ConvertTo-Json -Compress
""")
        report = json.loads(result.stdout)
        self.assertEqual(report["Version"], "2.78.0")
        self.assertEqual(report["Status"], "ready")

    def test_old_python_gets_dedicated_install_without_replacing_miniconda(self) -> None:
        self.run_ps("""
$script:installed = @()
function Get-AifRunnerToolSpecs { @{Name='python'} }
function Test-AifRunnerTool { param($Spec)
    if ($script:installed.Count) { [pscustomobject]@{Name='python'; Status='ready'; Path='C:\\Program Files\\AIFactory\\Python312\\python.exe'; Version='3.12.10'} }
    else { [pscustomobject]@{Name='python'; Status='invalid'; Path='C:\\Miniconda\\python.exe'; Version='3.9.21'} }
}
function Test-Path { $false }
function Test-AifRunnerElevation { $true }
function Set-AifRunnerPrerequisiteMarker { }
function Install-AifMissingTool { param($Name) $script:installed += $Name }
function Set-AifRunnerMachinePath { $false }
$report = Invoke-AifRunnerPrerequisites -InstallMissing
if ($report.Status -ne 'ready' -or ($script:installed -join ',') -ne 'python') { throw 'Dedicated Python was not installed once' }
""")

    def test_python_installer_does_not_retarget_existing_python(self) -> None:
        source = (LIB / "runner-prerequisites.ps1").read_text(encoding="utf-8")
        self.assertIn("'AIFactory\\Python312'", source)
        self.assertIn("'PrependPath=0'", source)
        self.assertNotIn("'TargetDir=C:\\Python312'", source)

    def test_expected_execution_error_reports_reason(self) -> None:
        result = self.run_ps("""
function Get-Command { [pscustomobject]@{Source='Invoke-DeniedVersion'} }
function Invoke-DeniedVersion { throw [UnauthorizedAccessException]::new('denied fixture') }
Test-AifRunnerTool @{Name='fixture'; Arguments=@(); Minimum='1.0'} | ConvertTo-Json -Compress
""")
        report = json.loads(result.stdout)
        self.assertEqual(report["Status"], "invalid")
        self.assertIn("denied fixture", report["Reason"])

    def test_unexpected_execution_error_is_not_swallowed(self) -> None:
        result = self.run_ps("""
function Get-Command { [pscustomobject]@{Source='Invoke-BrokenVersion'} }
function Invoke-BrokenVersion { throw [InvalidOperationException]::new('unexpected fixture defect') }
Test-AifRunnerTool @{Name='fixture'; Arguments=@(); Minimum='1.0'}
""", success=False)
        self.assertIn("unexpected fixture defect", result.stderr)

    def test_invalid_version_has_actionable_reason(self) -> None:
        result = self.run_ps(f"""
Test-AifRunnerTool @{{Name='python'; Exact=$true; Paths=@({quote(sys.executable)}); Arguments=@('--version'); Minimum='99.0'}} | ConvertTo-Json -Compress
""")
        self.assertIn("requires >= 99.0", json.loads(result.stdout)["Reason"])

    def test_check_keeps_both_process_and_machine_environment(self) -> None:
        self.run_ps("""
$beforePath = $env:Path
$beforeBicep = $env:AZURE_BICEP_USE_BINARY_FROM_PATH
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
function Test-AifRunnerTool { param($Spec) [pscustomobject]@{Name=$Spec.Name;Status='ready';Path='C:\\fixture.exe'} }
$null = Invoke-AifRunnerPrerequisites
if ($beforePath -cne $env:Path -or $beforeBicep -cne $env:AZURE_BICEP_USE_BINARY_FROM_PATH -or
    $machinePath -cne [Environment]::GetEnvironmentVariable('Path', 'Machine')) { throw 'Check changed environment' }
""")

    def test_bicep_install_pin_is_not_an_existing_install_minimum(self) -> None:
        self.run_ps("""
$spec = Get-AifRunnerToolSpecs | Where-Object Name -eq bicep
if ([version]$spec.Minimum -gt [version]'0.37.4') { throw 'Unnecessary Bicep upgrade' }
""")

    def test_ado_package_requires_digest_too(self) -> None:
        result = self.run_ps("""
function Test-AifRunnerConfiguration { $false }
function Test-Path { $false }
function New-Item { throw 'MUTATION CALLED' }
$prereqs = 'function Invoke-AifRunnerPrerequisites { [pscustomobject]@{Status="ready"; PathChanged=$false} }'
Invoke-AifWindowsRunnerRegistration -Provider ado -AgentName vm -AgentPool Default `
    -RegistrationUrl https://dev.azure.com/org -RegistrationToken 'test-only-placeholder' `
    -PackageUrl https://download.agent.dev.azure.com/agent/4.260.0/vsts-agent-win-x64-4.260.0.zip `
    -PrerequisitesScript $prereqs -InstallMissing $true
""", success=False)
        self.assertIn("Official runner SHA256 metadata is required", result.stderr)
        self.assertNotIn("MUTATION CALLED", result.stderr)


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is required")
class RunnerLinuxTests(unittest.TestCase):
    def run_bash(self, body: str, *, success: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        source = f"source {shlex.quote(str(LIB / 'runner-registration.sh').replace(chr(92), '/'))}\n"
        source += f"python3() {{ {shlex.quote(sys.executable.replace(chr(92), '/'))} \"$@\"; }}\n"
        result = subprocess.run([BASH, "-c", source + body], cwd=ROOT, text=True,
                                input=input_text, capture_output=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_exact_linux_scope_for_both_providers(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
            root = Path(directory)
            for provider, filename, url, data in (
                ("ado", ".agent", "https://dev.azure.com/org", {"serverUrl": "https://org.visualstudio.com/", "poolName": "Default", "agentName": "vm", "agentId": 7}),
                ("gha", ".runner", "https://github.com/org/repo", {"gitHubUrl": "https://github.com/ORG/repo/", "agentName": "vm", "agentId": 7}),
            ):
                (root / filename).write_text(json.dumps(data), encoding="utf-8")
                args = [provider, directory.replace("\\", "/"), url, "Default", "vm", "7"]
                self.assertIn("true", self.run_bash("aif_linux_runner_scope " + shlex.join(args)).stdout)
                for index, wrong in ((2, url + "-other"), (4, "other"), (5, "0"), (5, "99")):
                    mismatch = args.copy()
                    mismatch[index] = wrong
                    self.assertIn("refusing", self.run_bash(
                        "aif_linux_runner_scope " + shlex.join(mismatch), success=False).stderr)

    def test_dedicated_worker_rejects_root_and_extra_groups(self) -> None:
        for uid, groups, expected in (("991", "991", True), ("0", "0", False), ("991", "991 27", False)):
            with self.subTest(uid=uid, groups=groups):
                self.run_bash(f"""
getent() {{ echo 'aifactory-ado:x:{uid}:991::/var/lib/aifactory-ado:/usr/sbin/nologin'; }}
id() {{ echo '{groups}'; }}
useradd() {{ echo MUTATION >&2; return 99; }}
aif_linux_runner_worker aifactory-ado /var/lib/aifactory-ado false
""", success=expected)

    def test_service_requires_exact_folder_identity_and_unit(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
            root = Path(directory)
            (root / ".service").write_text("vsts.agent.aifactory.service\n", encoding="utf-8")
            path = directory.replace("\\", "/")
            # Convert just the local test directory; systemd's reported values remain Linux-shaped.
            for wrong in ("", "User", "WorkingDirectory", "ExecStart", "FragmentPath", "UnitFileState"):
                with self.subTest(wrong=wrong):
                    body = f"""
root={shlex.quote(path)}
systemctl() {{
  [[ "$1" == show ]] || {{ echo MUTATION >&2; return 99; }}
  echo Id=vsts.agent.aifactory.service
  echo LoadState=loaded
  echo User={'other-worker' if wrong == 'User' else 'aifactory-ado'}
  echo WorkingDirectory={'/other' if wrong == 'WorkingDirectory' else '$root'}
  echo 'ExecStart={{ path='"{'/other' if wrong == 'ExecStart' else '$root'}"'/runsvc.sh ; argv[]='"$root"'/runsvc.sh ; ignore_errors=no ; }}'
  echo FragmentPath={'/other' if wrong == 'FragmentPath' else '/etc/systemd/system/vsts.agent.aifactory.service'}
  echo ActiveState=active
  echo SubState=running
  echo UnitFileState={'disabled' if wrong == 'UnitFileState' else 'enabled'}
  echo MainPID=42
}}
aif_linux_runner_service ado "$root" aifactory-ado
[[ "$AIF_OWNED_SERVICE" == vsts.agent.aifactory.service ]]
"""
                    self.run_bash(body, success=not wrong)

    def test_linux_check_reuses_without_install_or_service_changes(self) -> None:
        for distro in ("22.04", "24.04"):
            for state in ("active", "inactive"):
                self.run_bash(f"""
Provider=ado; AgentName=vm; AgentPool=Default; RegistrationUrl=https://dev.azure.com/org
InstallMissing=false
PrerequisitesScript='aif_runner_prerequisites_main() {{ [[ "$1" == --check ]]; }}'
uname() {{ [[ "$1" != -m ]] && echo Linux || echo x86_64; }}
source() {{ if [[ "$1" == /etc/os-release ]]; then ID=ubuntu; VERSION_ID={distro}; else builtin source "$@"; fi; }}
aif_linux_runner_scope() {{ echo true; }}
aif_linux_runner_worker() {{ [[ "$3" == false ]]; }}
aif_linux_runner_service() {{ AIF_OWNED_SERVICE=vsts.agent.mine.service; AIF_OWNED_STATE={state}; AIF_OWNED_PID=42; }}
aif_linux_runner_worker_check() {{ return 0; }}
aif_linux_runner_fresh_process() {{ return 0; }}
systemctl() {{ echo MUTATION >&2; return 99; }}
aif_linux_runner_download() {{ echo DOWNLOAD >&2; return 99; }}
aif_linux_runner_main
""")

    def test_token_reaches_config_only_through_provider_environment(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
            root = Path(directory)
            config = root / "config.sh"
            config.write_text("""#!/usr/bin/env bash
set -euo pipefail
[[ "${VSTS_AGENT_INPUT_TOKEN:-${ACTIONS_RUNNER_INPUT_TOKEN:-}}" == test-only-fixture ]]
[[ "$*" != *test-only-fixture* && "$*" != *--token* ]]
printf ok > configured-ok
""", encoding="utf-8")
            for provider in ("ado", "gha"):
                result = self.run_bash(f"""
runuser() {{ shift 3; "$@"; }}
root={shlex.quote(directory.replace(chr(92), '/'))}
chmod +x "$root/config.sh"
printf '%s\\n' test-only-fixture | aif_linux_runner_configure worker "$root" "$root" {provider} https://github.com/org/repo Default vm label "$PATH"
""")
                self.assertEqual((root / "configured-ok").read_text(), "ok")
                self.assertNotIn("test-only-fixture", result.stdout + result.stderr)

    def test_linux_download_rejects_wrong_os_or_missing_digest_before_network(self) -> None:
        for url, checksum in (
            ("https://github.com/actions/runner/releases/download/v2.0.0/actions-runner-win-x64-2.0.0.zip", "a" * 64),
            ("https://github.com/actions/runner/releases/download/v2.0.0/actions-runner-linux-x64-2.0.0.tar.gz", ""),
        ):
            result = self.run_bash("aif_linux_runner_download " + shlex.join(["gha", url, checksum, "must-not-exist.tar.gz"]), success=False)
            self.assertFalse((ROOT / "must-not-exist.tar.gz").exists())
            self.assertNotIn("HTTP", result.stderr)
            self.assertRegex(result.stderr, "pinned official Linux|SHA256 metadata is required")

    def test_vm_os_dispatch_uses_isolated_create_or_reuse(self) -> None:
        launcher = shlex.quote(str(LIB / "create-new-aifactory-scaleset.sh").replace("\\", "/"))
        for provider, os_type in (("ado", "Windows"), ("gha", "Linux")):
            result = self.run_bash(f"""
source {launcher}
AIF_LOCATION_SHORT=sdc; AIF_LOCATION=swedencentral; AIF_PREFIX=fixture; AIF_SCALESET_SUFFIX_DASH=-001; AIF_DEV_SUBSCRIPTION_ID=fixture
AIF_ROUTE={provider}; AIF_REPO_ROOT="$PWD"; AIF_PYTHON=(fake_python)
unset AIF_RUNNER_VM_NAME AIF_RUNNER_VM_RESOURCE_GROUP AIF_RUNNER_VM_OS
aif_use_azure_tenant() {{ echo UNEXPECTED_ACCOUNT_SET; return 99; }}
aif_error() {{ echo "$*" >&2; }}
az() {{ echo 'UNEXPECTED AZ MUTATION' >&2; return 99; }}
fake_python() {{
  [[ "$*" == *'prepare-vm'* && "$*" == *'--prereqs-only --yes'* ]]
  [[ "$*" == *'--vm-os {os_type.lower()}'* && "$*" == *'--common-rg fixtureesml-common-sdc-dev-001'* ]]
}}
aif_prepare_runner_vm
[[ "$AIF_RUNNER_OS" == {os_type} ]]
""")
            self.assertNotIn("UNEXPECTED AZ MUTATION", result.stderr)

    def test_managed_payload_dispatches_os_with_protected_named_token(self) -> None:
        launcher = shlex.quote(str(LIB / "create-new-aifactory-scaleset.sh").replace("\\", "/"))
        for os_type, filename in (("Linux", "runner-registration.sh"), ("Windows", "runner-registration.ps1")):
            with self.subTest(os_type=os_type), tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
                result = self.run_bash(f"""
source {launcher}
AIF_PYTHON=({shlex.quote(sys.executable.replace(chr(92), '/'))})
AIF_STATE_DIR={shlex.quote(directory.replace(chr(92), '/'))}
AIF_RUNNER_OS={os_type}; AIF_RUNNER_VM_LOCATION=swedencentral
AIF_DEV_SUBSCRIPTION_ID=fixture; AIF_RUNNER_VM_RESOURCE_GROUP=fixture; AIF_RUNNER_VM_NAME=fixture
AIF_RUNNER_REGISTRATION_TOKEN=test-only-fixture
aif_error() {{ echo "$*" >&2; }}
az() {{
  [[ "$*" != *test-only-fixture* ]] || return 91
  if [[ " $* " == *' --method put '* ]]; then
    local arg body='' next=false
    for arg in "$@"; do
      if [[ "$next" == true ]]; then body="${{arg#@}}"; break; fi
      [[ "$arg" != --body ]] || next=true
    done
    "${{AIF_PYTHON[@]}}" - "$body" "$AIF_SCALESET_LIB_DIR/{filename}" <<'PY'
import json
from pathlib import Path
import sys
body = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert body["location"] == "swedencentral"
properties = body["properties"]
assert properties["source"] == {{"script": Path(sys.argv[2]).read_text(encoding="utf-8")}}
assert properties["protectedParameters"] == [{{"name": "RegistrationToken", "value": "test-only-fixture"}}]
assert all(p["name"] != "RegistrationToken" and p["value"] != "test-only-fixture" for p in properties["parameters"])
PY
  else
    printf 'Succeeded\\n0\\n'
  fi
}}
aif_invoke_runner_registration gha https://github.com/org/repo '' vm '' '' true label
[[ ! -e "$AIF_STATE_DIR/gha-runner-run-command.json" && -z "${{AIF_RUNNER_REGISTRATION_TOKEN+x}}" ]]
""")
                self.assertNotIn("test-only-fixture", result.stdout + result.stderr)

    def test_existing_protected_request_is_not_overwritten_or_deleted(self) -> None:
        launcher = shlex.quote(str(LIB / "create-new-aifactory-scaleset.sh").replace("\\", "/"))
        with tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
            request = Path(directory) / "ado-runner-run-command.json"
            request.write_text("existing-fixture", encoding="utf-8")
            result = self.run_bash(f"""
source {launcher}
AIF_STATE_DIR={shlex.quote(directory.replace(chr(92), '/'))}
AIF_RUNNER_REGISTRATION_TOKEN=test-only-fixture
aif_error() {{ echo "$*" >&2; }}
az() {{ echo MUTATION >&2; return 99; }}
aif_invoke_runner_registration ado https://dev.azure.com/org Default vm '' '' true ''
""", success=False)
            self.assertEqual(request.read_text(), "existing-fixture")
            self.assertNotIn("MUTATION", result.stderr)

    def test_linux_pending_restart_blocks_without_interrupting_service(self) -> None:
        result = self.run_bash("""
Provider=ado; AgentName=vm; AgentPool=Default; RegistrationUrl=https://dev.azure.com/org
InstallMissing=false
PrerequisitesScript='aif_runner_prerequisites_main() { return 0; }'
uname() { [[ "$1" != -m ]] && echo Linux || echo x86_64; }
source() { if [[ "$1" == /etc/os-release ]]; then ID=ubuntu; VERSION_ID=22.04; else builtin source "$@"; fi; }
aif_linux_runner_scope() { echo true; }
aif_linux_runner_worker() { return 0; }
aif_linux_runner_service() { AIF_OWNED_SERVICE=vsts.agent.mine.service; AIF_OWNED_STATE=active; AIF_OWNED_PID=42; }
aif_linux_runner_worker_check() { return 0; }
aif_linux_runner_fresh_process() { echo 'Explicit idle restart required' >&2; return 1; }
systemctl() { echo MUTATION >&2; return 99; }
aif_linux_runner_main
""", success=False)
        self.assertIn("Explicit idle restart required", result.stderr)
        self.assertNotIn("MUTATION", result.stderr)


class RunnerSourceTests(unittest.TestCase):
    def test_linux_official_archive_digest_and_safe_relative_link(self) -> None:
        source = (LIB / "runner-registration.sh").read_text(encoding="utf-8")
        code = source.split("aif_linux_runner_download() {", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as output:
            directory = tarfile.TarInfo("bin")
            directory.type = tarfile.DIRTYPE
            output.addfile(directory)
            file = tarfile.TarInfo("config.sh")
            file.size = 4
            output.addfile(file, io.BytesIO(b"true"))
            link = tarfile.TarInfo("bin/config")
            link.type = tarfile.SYMTYPE
            link.linkname = "../config.sh"
            output.addfile(link)
        data = archive.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        url = "https://github.com/actions/runner/releases/download/v2.0.0/actions-runner-linux-x64-2.0.0.tar.gz"
        with tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
            destination = Path(directory) / "package.tar.gz"
            with mock.patch("sys.argv", ["fixture", "gha", url, checksum, str(destination)]), \
                    mock.patch("urllib.request.urlopen", return_value=io.BytesIO(data)):
                exec(compile(code, "runner-archive-fixture", "exec"), {})
            self.assertEqual(destination.read_bytes(), data)

    def test_registration_is_create_only_and_uses_protected_parameters(self) -> None:
        launcher = (LIB / "create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
        script = (LIB / "runner-registration.ps1").read_text(encoding="utf-8")
        self.assertNotIn("--replace", script)
        self.assertNotIn("config.cmd remove", script)
        self.assertNotIn("Stop-Service", script)
        self.assertNotIn("Remove-Item -Recurse", script)
        self.assertIn('"protectedParameters": [{"name": "RegistrationToken"', launcher)
        self.assertIn("os.O_EXCL, 0o600", launcher)
        self.assertIn('"/inheritance:r"', launcher)
        self.assertIn("actions/runners/registration-token", launcher)
        self.assertIn('"runner_selection=$runner_selection"', launcher)
        self.assertIn("aif_ensure_github_self_hosted_agent", launcher)
        self.assertNotIn("is already online", launcher)

    def test_both_registrations_use_minimum_rights_and_no_token_arguments(self) -> None:
        windows = (LIB / "runner-registration.ps1").read_text(encoding="utf-8")
        linux = (LIB / "runner-registration.sh").read_text(encoding="utf-8")
        self.assertIn(r"NT AUTHORITY\NETWORK SERVICE", windows)
        for script in (windows, linux):
            self.assertNotIn("'--token'", script)
            self.assertIn("VSTS_AGENT_INPUT_TOKEN", script)
            self.assertIn("ACTIONS_RUNNER_INPUT_TOKEN", script)
            self.assertNotIn("--replace", script)
        self.assertNotIn("systemctl stop", linux)
        self.assertNotIn("systemctl restart", linux)
        self.assertNotIn("rm -rf", linux)
        self.assertIn("NoNewPrivileges=true", linux)
        self.assertIn("--shell /usr/sbin/nologin", linux)

    def test_linux_pins_reviewed_bicep_and_uses_signed_official_sources(self) -> None:
        source = (LIB / "runner-prerequisites.sh").read_text(encoding="utf-8")
        ci = (ROOT / "environment_setup/unit-tests/test-bicep/ci/install-bicep.sh").read_text(encoding="utf-8")
        self.assertIn("0.44.1", source)
        self.assertIn("e17dc9a9888184886bb0c0051a3230b83b19f342749999f707bc571c3dfd2f45", source)
        self.assertIn("e17dc9a9888184886bb0c0051a3230b83b19f342749999f707bc571c3dfd2f45", ci)
        self.assertIn("--no-upgrade", source)
        self.assertIn("signed-by=", source)
        self.assertIn("22.04", source)
        self.assertIn("24.04", source)
        self.assertNotIn("| bash", source)
        self.assertNotIn("terraform", source)
        self.assertNotIn("docker", source)

    @unittest.skipUnless(BASH and Path(BASH).exists(), "Git Bash or Bash is required")
    def test_shell_syntax_and_version_comparison(self) -> None:
        for filename in ("runner-prerequisites.sh", "runner-registration.sh", "runner-only-registration.sh",
                         "create-new-aifactory-scaleset.sh"):
            if filename != "runner-registration.sh":
                self.assertEqual((LIB / filename).read_bytes().count(b"\r"), 0, filename)
            result = subprocess.run(
                [BASH, "-n", str(LIB / filename)], cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        path = str(LIB / "runner-prerequisites.sh").replace("\\", "/")
        result = subprocess.run(
            [BASH, "-c", f"source '{path}'; aif_runner_version_at_least 3.10.9 3.10 && ! aif_runner_version_at_least 3.9.20 3.10"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(BASH and Path(BASH).exists(), "Git Bash or Bash is required")
    def test_ubuntu_check_and_invalid_versions_never_install(self) -> None:
        path = str(LIB / "runner-prerequisites.sh").replace("\\", "/")
        for distro in ("22.04", "24.04"):
            for state, expected in (("ready", 0), ("missing", 2), ("invalid", 2)):
                with self.subTest(distro=distro, state=state):
                    script = f"""
builtin source '{path}'
uname() {{ if [[ "$1" == -m ]]; then echo x86_64; else echo Linux; fi; }}
source() {{ ID=ubuntu; VERSION_ID={distro}; VERSION_CODENAME=noble; }}
for tool in git bash python3 python az pwsh gh bicep jq; do
  eval "$tool() {{ echo 99.0.0; }}"
done
apt-get() {{ echo INSTALL_WAS_CALLED >&2; return 99; }}
curl() {{ echo DOWNLOAD_WAS_CALLED >&2; return 99; }}
if [[ {state} == missing ]]; then
  command() {{ if [[ "$1" == -v && "$2" == gh ]]; then return 1; else builtin command "$@"; fi; }}
fi
if [[ {state} == invalid ]]; then python3() {{ echo 'Python 3.9.0'; }}; fi
args=()
[[ {state} != invalid ]] || args=(--install-missing)
aif_runner_prerequisites_main "${{args[@]}}"
"""
                    result = subprocess.run([BASH, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    self.assertNotIn("INSTALL_WAS_CALLED", result.stderr)
                    self.assertNotIn("DOWNLOAD_WAS_CALLED", result.stderr)


class RunnerEnsureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(LIB))
        import runner_bootstrap
        cls.core = runner_bootstrap
        sys.path.pop(0)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".runner-ensure with spaces-", dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "variables.json"
        self.values = {
                    "useSelfHostedBuildAgent": True, "tenantId": "11111111-1111-1111-1111-111111111111",
                    "dev_sub_id": "22222222-2222-2222-2222-222222222222", "test_sub_id": "33333333-3333-3333-3333-333333333333",
                    "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
                    "admin_aifactoryPrefixRG": "fixture-", "admin_aifactorySuffixRG": "-001",
        }
        self.save()

    def save(self):
        self.path.write_text(json.dumps({"dev": self.values}), encoding="utf-8")

    def request(self, provider="gha", **kwargs):
        return self.core.load_request(self.root, provider, config_source=self.path, environ={},
                                              repository="owner/repo" if provider == "gha" else None,
                                              prereqs_only=kwargs.pop("prereqs_only", True), **kwargs)

    def cloud(self, request):
        import copy
        core = self.core
        class FakeCloud:
                    def __init__(self):
                        self.read_only = True
                        self.writes = []
                        self.data = {}
                        for identifier in (request["rg_id"], request["subnet"], request["subnet"].rsplit("/subnets/", 1)[0]):
                            self.data[identifier] = {"id": identifier, "location": request["location"],
                                                     "properties": {"provisioningState": "Succeeded"}}
                    def az(self, *args):
                        assert args == ("account", "show", "--subscription", request["target"]["subscription_id"])
                        return {"tenantId": request["target"]["tenant_id"], "id": request["target"]["subscription_id"], "state": "Enabled"}
                    def arm(self, method, identifier, version, data=None, **kwargs):
                        if method == "GET":
                            if identifier.endswith("/instanceView"):
                                return 200, {}, {"statuses": [{"code": "PowerState/running"}]}
                            if identifier not in self.data:
                                return 404, {}, {"error": {"code": "ResourceNotFound"}}
                            return 200, {}, copy.deepcopy(self.data[identifier])
                        assert not self.read_only
                        assert method == "PUT"
                        self.writes.append(identifier)
                        if identifier.endswith("/providers/Microsoft.Resources/tags/default"):
                            disk_id = identifier.rsplit("/providers/", 1)[0]
                            self.data[disk_id]["tags"] = data["properties"]["tags"]
                            return 200, {}, {}
                        assert identifier not in self.data, "overwrite attempted"
                        value = copy.deepcopy(data)
                        value["id"] = identifier
                        value["properties"]["provisioningState"] = "Succeeded"
                        self.data[identifier] = value
                        if identifier == request["vm_id"]:
                            ids = core.resource_ids(request)
                            value["properties"]["storageProfile"]["osDisk"].update(osType="Linux", managedDisk={"id": ids["disk"]})
                            self.data[ids["disk"]] = {
                                "id": ids["disk"], "location": request["location"], "managedBy": identifier,
                                "sku": {"name": "StandardSSD_LRS"},
                                "properties": {"provisioningState": "Succeeded", "diskSizeGB": 128},
                            }
                        return 201, {}, value
        return FakeCloud()

    def test_flag_all_formats_any_true_wins_and_environment_isolated(self):
        for name, content in (
                    ("variables.yaml", "variables:\n  useSelfHostedBuildAgent: true\n"),
                    ("variables.yml", "dev:\n  variables:\n    useSelfHostedBuildAgent: 'TRUE'\n"),
                    ("variables.yaml", "variables:\n- name: useSelfHostedBuildAgent\n  value: true\n"),
                    ("variables.yml", "dev:\n  variables:\n    - name: 'useSelfHostedBuildAgent'\n      value: true\n"),
                    ("variables.yaml", 'variables:\n  "useSelfHostedBuildAgent": true\n'),
                    (".env", "USE_SELF_HOSTED_BUILD_AGENT=true # selected\n"),
        ):
                    with self.subTest(name=name):
                        self.values["useSelfHostedBuildAgent"] = False
                        self.save()
                        other = self.root / name
                        other.write_text(content, encoding="utf-8")
                        self.assertTrue(self.request()["desired"])
                        other.unlink()
        self.path.write_text(json.dumps({"dev": self.values, "stage_prod": {"useSelfHostedBuildAgent": True}}), encoding="utf-8")
        self.assertFalse(self.request()["desired"])
        self.assertTrue(self.core.requested(self.core.selected_values(self.core.read_config(self.path), "prod")))
        self.assertFalse(self.core.requested([{"useSelfHostedBuildAgent": False}, {}]))

    def test_invalid_flag_even_with_true_fails_and_never_evaluates(self):
        for value in ("yes", "1", "", "$(touch INJECTED)", 1, None, {}, []):
                    with self.subTest(value=value):
                        self.path.write_text(json.dumps({"dev": dict(self.values, useSelfHostedBuildAgent=value)}), encoding="utf-8")
                        with self.assertRaisesRegex(self.core.EnrollmentError, "invalid-self-hosted-flag"):
                            self.request()
        self.assertFalse((self.root / "INJECTED").exists())

    def test_malformed_sources_and_unknown_scope_fail(self):
        for name, text in (("variables.json", '{"dev":{"useSelfHostedBuildAgent":true, "useSelfHostedBuildAgent":false}}'),
                                   ("variables.yml", "variables:\n  useSelfHostedBuildAgent: 'unterminated\n"),
                                   (".env", "USE_SELF_HOSTED_BUILD_AGENT=true\nnot an assignment"),
                                   ("variables.yml", "variables:\n  useSelfHostedBuildAgent: true\n invalid: false")):
                    with self.subTest(name=name):
                        path = self.root / name
                        path.write_text(text, encoding="utf-8")
                        with self.assertRaises(self.core.EnrollmentError):
                            self.core.read_config(path)
                        if path != self.path:
                            path.unlink()
        with self.assertRaisesRegex(self.core.EnrollmentError, "ambiguous"):
                    self.core.selected_values({"factories": {"other": {"useSelfHostedBuildAgent": True}}}, "dev")

    def test_provider_defaults_and_supported_explicit_choices(self):
        self.assertEqual(self.request()["vm_os"], "linux")
        self.assertEqual(self.request()["vm_name"], "runner-gha-sdc-dev-001")
        self.assertEqual(self.request("ado")["vm_os"], "windows")
        self.assertEqual(self.request("ado")["vm_name"], "dsvm-cmn-sdc-dev-001")
        self.assertEqual(self.request("ado", vm_os="linux")["vm_os"], "linux")
        self.assertEqual(self.request(vm_os="windows")["vm_os"], "windows")

    def test_only_selected_environment_and_provider_metadata_is_required(self):
        self.path.write_text(json.dumps({"dev": {"useSelfHostedBuildAgent": False}, "stage_prod": {
            **self.values, "azureDevOpsTenantId": "<unused>", "ADO_ORGANIZATION": "<unused>"}}), encoding="utf-8")
        request = self.core.load_request(self.root, "gha", "stage", config_source=self.path,
                                        repository="owner/repo", environ={}, prereqs_only=True)
        self.assertEqual(request["target"]["subscription_id"], self.values["test_sub_id"])
        self.assertIn("-test-001", request["common_rg"])
        self.assertNotIn("-dev-", request["vm_name"])
        self.assertIsNone(request["ado_tenant_id"])

    def test_canonical_env_only_source_and_byo_network_names(self):
        self.path.unlink()
        path = self.root / ".env"
        path.write_text("\n".join(f"{key}={value}" for key, value in {
            "USE_SELF_HOSTED_BUILD_AGENT": "true", "TENANT_ID": self.values["tenantId"],
            "DEV_SUBSCRIPTION_ID": self.values["dev_sub_id"], "AIFACTORY_LOCATION": "swedencentral",
            "AIFACTORY_LOCATION_SHORT": "sdc", "AIFACTORY_PREFIX": "fixture-", "AIFACTORY_SUFFIX": "-001",
            "BYO_SUBNETS": "true", "SUBNET_COMMON": "snet-<network_env>common",
            "NETWORK_ENV_DEV": "dev-", "VNET_NAME_FULL_PARAM": "existing-<network_env>vnet",
            "VNET_RESOURCE_GROUP_PARAM": "existing-network",
        }.items()), encoding="utf-8")
        request = self.core.load_request(self.root, "gha", config_source=path, environ={}, prereqs_only=True)
        self.assertEqual(request["target"]["subscription_id"], self.values["dev_sub_id"])
        self.assertTrue(request["subnet"].endswith("/virtualNetworks/existing-dev-vnet/subnets/snet-dev-common"))
        self.assertIn("/resourceGroups/existing-network/", request["subnet"])
        with self.assertRaisesRegex(self.core.EnrollmentError, "selected-subnet-mismatch"):
            self.core.load_request(self.root, "gha", config_source=path, environ={}, prereqs_only=True,
                                   subnet_id=request["subnet"] + "-other")

    def test_provider_inventory_is_read_only_and_rejects_busy_mismatches(self):
        request = self.request(prereqs_only=False)
        cloud = mock.Mock()
        cloud.gh.return_value = (200, {}, {"runners": []})
        self.assertEqual(self.core.provider_action(request, cloud), "create")
        runner = {"name": request["agent_name"], "os": "linux", "busy": False,
                  "labels": [{"name": request["runner_label"]}]}
        cloud.gh.return_value = (200, {}, {"runners": [runner]})
        self.assertEqual(self.core.provider_action(request, cloud), "reuse")
        runner["busy"] = True
        with self.assertRaisesRegex(self.core.EnrollmentError, "busy"):
            self.core.provider_action(request, cloud)
        runner["busy"] = False
        runner["os"] = "windows"
        with self.assertRaisesRegex(self.core.EnrollmentError, "mismatch"):
            self.core.provider_action(request, cloud)
        self.assertTrue(all(call.args[0] == "GET" for call in cloud.gh.call_args_list))

    def test_registered_ado_layout_can_ensure_all_github_prerequisites_without_a_repository(self):
        from contextlib import redirect_stdout
        factory_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        scale_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self.path.unlink()
        self.path = self.root / "aifactory" / "variables.json"
        self.path.parent.mkdir()
        self.values["admin_aifactoryPrefixRG"] = "spider-"
        self.save()
        register = self.root / "azurefactory" / "register.json"
        register.parent.mkdir()
        register.write_text(json.dumps({
            "schema_version": 2, "factories": [{
                "id": factory_id, "prefix": "spider-", "region": "swedencentral",
                "scale_sets": [{"id": scale_id, "environment": "dev", "orchestrator": "ado",
                    "suffix": "001", "tenant_id": self.values["tenantId"],
                    "subscription_id": self.values["dev_sub_id"],
                    "provenance": {"source_ref": "frozen-test-source"}}]}],
            "configurations": {}, "bindings": {},
        }), encoding="utf-8")
        original = {path: path.read_bytes() for path in (register, self.path)}
        request = self.core.load_request(
            self.root, "gha", config_source=self.path, factory_id=factory_id, scale_set_id=scale_id,
            separate_github=True, prereqs_only=True, environ={})
        self.assertIsNone(request["repository"])
        self.assertEqual(request["common_rg"], "spider-esml-common-sdc-dev-001")
        self.assertEqual(request["vm_name"], "runner-gha-sdc-dev-001")
        self.assertTrue(request["subnet"].endswith(
            "/virtualNetworks/vnt-esmlcmn-sdc-dev-001/subnets/snet-esml-cmn-001"))
        cloud = self.cloud(request)
        windows_id = request["rg_id"] + "/providers/Microsoft.Compute/virtualMachines/dsvm-cmn-sdc-dev-001"
        windows = {"id": windows_id, "location": "swedencentral",
                   "properties": {"storageProfile": {"osDisk": {"osType": "Windows"}}}}
        cloud.data[windows_id] = windows
        normal_arm = cloud.arm
        guest_scripts = []
        guest_exit_code = 0

        def arm(method, identifier, version, data=None, **kwargs):
            if "/runCommands/" not in identifier:
                return normal_arm(method, identifier, version, data=data, **kwargs)
            self.assertTrue(identifier.startswith(request["vm_id"] + "/runCommands/prerequisites-"))
            if method == "PUT":
                self.assertFalse(cloud.read_only)
                guest_scripts.append(data["properties"]["source"]["script"])
                self.assertNotIn("protectedParameters", data["properties"])
                return 201, {}, {}
            self.assertEqual(method, "GET")
            return 200, {}, {"id": identifier.split("?")[0], "properties": {
                "instanceView": {"executionState": "Succeeded", "exitCode": guest_exit_code}}}

        key = self.root / "public-key"
        key.write_text("ssh-ed25519 YWJjZA== offline-fixture", encoding="utf-8")
        arguments = ["gha", "ensure", "--consumer-root", str(self.root), "--config-source", str(self.path),
                     "--factory-id", factory_id, "--scale-set-id", scale_id, "--environment", "dev",
                     "--separate-github", "--prereqs-only", "--ssh-public-key", str(key), "--yes"]
        with mock.patch.object(self.core, "Cloud", return_value=cloud), \
                mock.patch.object(cloud, "arm", side_effect=arm), \
                mock.patch.object(self.core.subprocess, "run", side_effect=AssertionError("No host or git-remote commands")), \
                mock.patch.object(self.core, "register_agent", side_effect=AssertionError("No provider registration")):
            for expected_vm_action in ("create", "reuse"):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(self.core.main(arguments), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report["status"], "prerequisites-ready")
                self.assertFalse(report["agent_ready"])
                self.assertEqual(report["actions"]["agent"], "noop")
                self.assertEqual(report["actions"]["vm"], expected_vm_action)
            guest_exit_code = 1
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(self.core.main(arguments), 2)
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["error"], "runner-prerequisites-failed")
            self.assertFalse(report["agent_ready"])
        self.assertEqual(len(guest_scripts), 3)
        for script in guest_scripts:
            self.assertIn((LIB / "runner-prerequisites.sh").read_text(encoding="utf-8"), script)
            self.assertIn("aif_runner_prerequisites_main --install-missing --require-runner-runtime --require-az-modules", script)
        self.assertEqual(cloud.data[windows_id], windows)
        self.assertNotIn(windows_id, cloud.writes)
        self.assertEqual(cloud.writes.count(request["vm_id"]), 1)
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertFalse((self.root / ".env").exists())

    def test_no_flag_needs_no_unrelated_config_or_cloud(self):
        self.path.write_text('{"useSelfHostedBuildAgent":false}', encoding="utf-8")
        request = self.request()
        cloud = mock.Mock()
        self.assertEqual(self.core.plan(request, cloud)["status"], "skipped-not-requested")
        self.assertIsNone(self.core.ensure_vm(request, yes=True, cloud=cloud))
        self.assertEqual(cloud.mock_calls, [])

    def test_create_linux_then_reuse_without_mutating_existing_resources(self):
        request = self.request()
        cloud = self.cloud(request)
        report = self.core.plan(request, cloud)
        self.assertEqual(report["actions"]["vm"], "create")
        self.assertEqual(cloud.writes, [])
        self.assertNotIn("fingerprints", report)
        key = self.root / "public-key"
        key.write_text("ssh-ed25519 YWJjZA== offline-fixture", encoding="utf-8")
        with mock.patch.object(self.core.subprocess, "run", side_effect=AssertionError("host install/keygen")):
                    self.core.ensure_vm(request, yes=True, cloud=cloud, ssh_public_key=key)
                    first = list(cloud.writes)
                    self.core.ensure_vm(request, yes=True, cloud=cloud, ssh_public_key=key)
        self.assertEqual(cloud.writes, first)
        self.assertEqual(self.core.plan(request, cloud)["actions"]["vm"], "reuse")
        vm = cloud.data[request["vm_id"]]
        self.assertNotIn("identity", vm)
        self.assertEqual(vm["properties"]["storageProfile"]["imageReference"], self.core.IMAGE)
        self.assertEqual(vm["properties"]["hardwareProfile"]["vmSize"], "Standard_D4s_v5")
        self.assertTrue(all(identifier.startswith(request["rg_id"] + "/providers/") for identifier in first))
        self.assertFalse(any("publicIPAddresses" in identifier or "deployments" in identifier for identifier in first))

    def test_exact_existing_windows_reused_without_ownership_adoption(self):
        request = self.request("ado")
        cloud = self.cloud(request)
        nic_id = request["rg_id"] + "/providers/Microsoft.Network/networkInterfaces/original"
        cloud.data[request["vm_id"]] = {"id": request["vm_id"], "location": request["location"],
                    "properties": {"storageProfile": {"osDisk": {"osType": "Windows"}},
                                   "hardwareProfile": {"vmSize": "Standard_D2s_v5"},
                                   "networkProfile": {"networkInterfaces": [{"id": nic_id}]}}}
        cloud.data[nic_id] = {"id": nic_id, "properties": {"ipConfigurations": [
                    {"properties": {"subnet": {"id": request["subnet"]}}}]}}
        self.core.ensure_vm(request, yes=True, cloud=cloud)
        self.assertEqual(cloud.writes, [])
        self.assertEqual(self.core.plan(request, cloud)["size"], "Standard_D2s_v5")
        cloud.data[request["vm_id"]]["properties"]["storageProfile"]["osDisk"]["osType"] = "Linux"
        with self.assertRaisesRegex(self.core.EnrollmentError, "os-or-location-mismatch"):
                    self.core.ensure_vm(request, yes=True, cloud=cloud)
        self.assertEqual(cloud.writes, [])

    def test_absence_is_only_structured_404_and_conflicts_never_write(self):
        request = self.request()
        for response in ((403, {}, {"error": {"code": "AuthorizationFailed"}}), (404, {}, b"not found")):
                    cloud = self.cloud(request)
                    with mock.patch.object(cloud, "arm", return_value=response):
                        with self.assertRaises(self.core.EnrollmentError):
                            self.core.ensure_vm(request, yes=True, cloud=cloud)
                    self.assertEqual(cloud.writes, [])
        cloud = self.cloud(request)
        identifier = self.core.resource_ids(request)["nic"]
        cloud.data[identifier] = {"id": identifier, "location": request["location"], "tags": {"unrelated": "owner"}}
        with self.assertRaisesRegex(self.core.EnrollmentError, "ownership-conflict"):
                    self.core.ensure_vm(request, yes=True, cloud=cloud)
        self.assertEqual(cloud.writes, [])

    def test_concurrent_resource_creation_is_not_overwritten(self):
        request = self.request()
        cloud = self.cloud(request)
        cloud.read_only = False
        identifier = self.core.resource_ids(request)["nic"]
        cloud.data[identifier] = {"id": identifier}
        with self.assertRaisesRegex(self.core.EnrollmentError, "appeared"):
                    self.core.create_absent(cloud, identifier, self.core.NETWORK_API, {})
        self.assertEqual(cloud.writes, [])

    def test_registered_tuple_and_route_are_required_without_changing_register(self):
        factory_id, scale_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        register = self.root / "azurefactory" / "register.json"
        register.parent.mkdir()
        register.write_text(json.dumps({"schema_version": 2, "factories": [{"id": factory_id, "prefix": "fixture",
                    "region": "swedencentral", "scale_sets": [{"id": scale_id, "environment": "dev", "orchestrator": "ado",
                    "suffix": "001", "tenant_id": self.values["tenantId"], "subscription_id": self.values["dev_sub_id"]}]}],
                    "configurations": {}, "bindings": {}}), encoding="utf-8")
        original = register.read_bytes()
        with self.assertRaisesRegex(self.core.EnrollmentError, "factory-id"):
                    self.request()
        with self.assertRaisesRegex(self.core.EnrollmentError, "orchestrator-mismatch"):
                    self.request(factory_id=factory_id, scale_set_id=scale_id)
        request = self.request(factory_id=factory_id, scale_set_id=scale_id, separate_github=True)
        self.assertEqual(request["vm_os"], "linux")
        with self.assertRaisesRegex(self.core.EnrollmentError, "linux-scoped"):
                    self.request("ado", factory_id=factory_id, scale_set_id=scale_id, vm_os="windows")
        with self.assertRaisesRegex(self.core.EnrollmentError, "separate-github-requires"):
                    self.request("ado", factory_id=factory_id, scale_set_id=scale_id, separate_github=True, vm_os="windows")
        child = self.root / "child"
        child.mkdir()
        with self.assertRaisesRegex(self.core.EnrollmentError, "factory-id"):
                    self.core.load_request(child, "gha", config_source=self.path, environ={})
        self.assertEqual(register.read_bytes(), original)

    def test_config_changes_require_replan_and_ensure_requires_yes(self):
        request = self.request()
        cloud = self.cloud(request)
        with self.assertRaisesRegex(self.core.EnrollmentError, "requires-yes"):
                    self.core.ensure_vm(request, cloud=cloud)
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(self.core.EnrollmentError, "changed-replan"):
                    self.core.ensure_vm(request, yes=True, cloud=cloud)
        self.assertEqual(cloud.writes, [])

    def test_runner_routes_before_legacy_and_register_paths(self):
        env = dict(os.environ, AIFACTORY_PYTHON=sys.executable)
        self.path.write_text('{"useSelfHostedBuildAgent": false}', encoding="utf-8")
        for script in ("ADO-azurefactory.sh", "GHA-azurefactory.sh",
                               "ADO-create-new-aifactory-scaleset.sh", "GHA-create-new-aifactory-scaleset.sh"):
                    result = subprocess.run([BASH, str(ROOT / "bootstrap" / script), "runner", "plan",
                                             "--consumer-root", str(self.root), "--config-source", str(self.path)],
                                            env=env, capture_output=True, text=True, cwd=ROOT, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)["status"], "skipped-not-requested")
        self.assertFalse((self.root / ".git").exists())
        source = (LIB / "runner-only-registration.sh").read_text()
        self.assertNotIn("aif_scaleset_main", source)
        self.assertNotIn("account set", source)
        self.assertNotIn("login", source)


@unittest.skipUnless(BASH and Path(BASH).exists(), "Git Bash or Bash is required")
class RunnerPythonAliasTests(unittest.TestCase):
    def run_fixture(self, directory: Path, body: str, *, distro: str = "22.04") -> subprocess.CompletedProcess[str]:
        path = shlex.quote(str(LIB / "runner-prerequisites.sh").replace("\\", "/"))
        script = f"""
builtin source {path}
fixture="$PWD"
export PATH="$fixture:$PATH"
uname() {{ if [[ "$1" == -m ]]; then echo x86_64; else echo Linux; fi; }}
source() {{ ID=ubuntu; VERSION_ID={distro}; VERSION_CODENAME=noble; }}
for tool in git bash az pwsh gh bicep jq; do
  eval "$tool() {{ echo 99.0.0; }}"
done
command() {{
  if [[ "$1" == -v && "$2" == python && ! -f "$fixture/python" ]]; then return 1; fi
  builtin command "$@"
}}
apt-get() {{
  [[ "$*" == 'update -qq' ]] || {{ echo UNEXPECTED_INSTALL >&2; return 99; }}
  echo apt-update >> "$fixture/mutations"
}}
dpkg-query() {{ echo 'install ok installed'; }}
curl() {{ echo UNEXPECTED_DOWNLOAD >&2; return 99; }}
gpg() {{ echo UNEXPECTED_DOWNLOAD >&2; return 99; }}
aif_runner_require_root() {{ :; }}
aif_runner_mark_prerequisites_changed() {{ echo marker >> "$fixture/mutations"; }}
eval "$(declare -f aif_runner_python_alias | sed '1s/aif_runner_python_alias/aif_test_python_alias/')"
aif_runner_python_alias() {{ aif_test_python_alias "$fixture/python"; }}
{body}
"""
        return subprocess.run([BASH, "-c", script], cwd=directory, capture_output=True, text=True, timeout=30)

    def make_python(self, path: Path, version: str = "3.10.12") -> bytes:
        data = f"#!/usr/bin/env bash\nprintf 'Python {version}\\n'\n".encode()
        path.write_bytes(data)
        path.chmod(0o755)
        return data

    def test_ensure_adds_only_missing_python_alias_and_check_requires_it(self) -> None:
        for distro, version in (("22.04", "3.10.12"), ("24.04", "3.12.3")):
            with self.subTest(distro=distro), tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
                root = Path(directory)
                original = self.make_python(root / "python3", version)
                result = self.run_fixture(root, """
if aif_runner_prerequisites_main --check; then exit 91; fi
[[ ! -e "$fixture/mutations" && ! -e "$fixture/python" ]]
aif_runner_prerequisites_main --install-missing
python --version
aif_runner_prerequisites_main --check
aif_runner_prerequisites_main --install-missing
""", distro=distro)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("missing: python >= 3.10", result.stdout)
                self.assertIn("created: python ->", result.stdout)
                self.assertIn(f"ready: python {version}", result.stdout)
                self.assertEqual((root / "mutations").read_text().splitlines(), ["marker", "apt-update"])
                self.assertEqual((root / "python3").read_bytes(), original)
                self.assertEqual((root / "python").read_bytes(), original)
                self.assertFalse((root / ".aifactory-runner-downloads").exists())
                (root / "python").unlink()
                result = self.run_fixture(root, "aif_runner_prerequisites_main --check", distro=distro)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("missing: python >= 3.10", result.stdout)

    def test_existing_python_is_never_replaced_even_when_invalid(self) -> None:
        for version, expected in (("2.7.18", 2), ("3.9.20", 2), ("3.12.3", 0), ("unknown", 2)):
            with self.subTest(version=version), tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
                root = Path(directory)
                self.make_python(root / "python3")
                original = self.make_python(root / "python", version)
                result = self.run_fixture(root, "aif_runner_prerequisites_main --install-missing")
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual((root / "python").read_bytes(), original)
                self.assertFalse((root / "mutations").exists())

    def test_alias_rejects_existing_destination_and_concurrent_creation(self) -> None:
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
                root = Path(directory)
                self.make_python(root / "python3")
                mutation = (
                    'ln() { printf existing > "$fixture/python"; builtin command ln "$@"; }'
                    if concurrent else 'printf existing > "$fixture/python"'
                )
                result = self.run_fixture(root, f"""
command() {{ if [[ "$1" == -v && "$2" == python ]]; then return 1; fi; builtin command "$@"; }}
{mutation}
aif_runner_python_alias
""")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((root / "python").read_text(), "existing")
                self.assertFalse((root / "mutations").exists())

    def test_missing_python_alias_requires_valid_python3_and_post_install_check(self) -> None:
        for version, failed_link in (("3.9.20", False), ("3.12.3", True)):
            with self.subTest(version=version), tempfile.TemporaryDirectory(prefix=".runner-tests-", dir=ROOT) as directory:
                root = Path(directory)
                self.make_python(root / "python3", version)
                result = self.run_fixture(root, (
                    "ln() { :; }\n" if failed_link else ""
                ) + "aif_runner_python_alias")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("post-install verification" if failed_link else "explicit repair/upgrade", result.stderr)
                self.assertFalse((root / "python").exists())


if __name__ == "__main__":
    unittest.main()
