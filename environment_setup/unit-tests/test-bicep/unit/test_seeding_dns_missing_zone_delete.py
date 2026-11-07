"""A delete run of a partially bootstrapped factory continues when the Key Vault private DNS zone was never created.

aif-147/148 (2026-11-07): the common bootstrap stopped before the private DNS zones existed, so every project
delete run stopped in 02b_Prepare_Seeding_KeyVault_Private_DNS (prepareSeedingKeyVaultPrivateDns.ps1:255) before
it deleted anything. A delete run passes -AllowMissingZone: the missing zone warns and the run goes on; a deploy
still fails closed.
"""

import os
import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
SCRIPT = BICEP / "scripts" / "prepareSeedingKeyVaultPrivateDns.ps1"
GHA = BICEP / "copy_to_local_settings" / "github-actions" / "infra-project-phase.yml"


def missing_zone_block():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("if ($null -eq $dnsZone) {")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


def run_block(allow):
    pwsh = shutil.which("pwsh")
    assert pwsh, "PowerShell 7 (pwsh) is required for this offline contract"
    script = ("$ErrorActionPreference = 'Stop'\n$dnsZone = $null\n$dnsZoneName = 'privatelink.vaultcore.azure.net'\n"
              f"$AllowMissingZone = ${str(allow).lower()}\n" + missing_zone_block() + "\nWrite-Output 'CONTINUED'\n")
    return subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_missing_zone_on_a_delete_run_warns_and_exits_cleanly():
    result = run_block(True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deletion continues" in (result.stdout + result.stderr)
    assert "CONTINUED" not in result.stdout  # the helper ends: there is no zone to link


def test_missing_zone_on_a_deploy_still_fails_closed():
    result = run_block(False)
    assert result.returncode != 0
    assert "was not found" in result.stdout + result.stderr


def test_parameter_is_declared():
    assert "[switch] $AllowMissingZone" in SCRIPT.read_text(encoding="utf-8")


def test_github_step_allows_a_missing_zone_only_in_delete_runs():
    steps = [step for job in yaml.safe_load(GHA.read_text(encoding="utf-8"))["jobs"].values()
             for step in job.get("steps", []) if step.get("name") == "02b_Prepare_Seeding_KeyVault_Private_DNS"]
    assert steps
    for step in steps:
        assert "deleteAllForProject" in step["env"]["AIF_DELETE_RUN"]
        assert "-AllowMissingZone:($env:AIF_DELETE_RUN -eq 'true')" in step["run"]
