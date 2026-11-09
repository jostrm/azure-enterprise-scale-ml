"""Exercise the actual PowerShell entry points without Azure or catalog writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from base.config import REPO_ROOT


WRAPPERS = REPO_ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-publishing"
BACKEND = Path("environment_setup/aifactory/bicep/scripts/publish-foundry-agent.py")
PWSH = shutil.which("pwsh")
SURFACES = (("publich-agent-to-TEAMS.ps1", "Teams"), ("publich-agent-to-Copilot.ps1", "Copilot"))
pytestmark = pytest.mark.skipif(PWSH is None, reason="Actual PowerShell (pwsh) is required")


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture
def runner(tmp_path):
    root = tmp_path / "fake repo's space"
    config_dir = root / "consumer's project"
    config_dir.mkdir(parents=True)
    (config_dir / "variables.json").write_text("{}", encoding="utf-8")
    backend = root / BACKEND
    backend.parent.mkdir(parents=True)
    control = root / "control.json"
    log = root / "calls.jsonl"
    scratch = tmp_path / "transient files"
    scratch.mkdir()
    copied_wrappers = root / WRAPPERS.relative_to(REPO_ROOT)
    copied_wrappers.mkdir(parents=True)
    for name in (SURFACES[0][0], SURFACES[1][0], "FoundryPublishing.psm1"):
        shutil.copyfile(WRAPPERS / name, copied_wrappers / name)
    plan = {
        "mode": "plan",
        "status": "ready",
        "target": {
            "tenant_id": "tenant-exact",
            "subscription_id": "subscription-exact",
            "project_resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/account/projects/project",
            "agent_name": "agent-exact",
            "scope": "Shared",
        },
        "preparation": {
            "before": {"publicNetworkAccess": "Disabled", "auth": "old-auth"},
            "after": {"publicNetworkAccess": "Enabled", "auth": "Entra"},
            "patch": {"publicNetworkAccess": "Enabled"},
            "changed": True,
        },
        "publish_body": {
            "agentDisplayName": "A real agent",
            "shortDescription": "Reviewed short description",
            "fullDescription": "Reviewed full description",
            "developerName": "Actual developer",
            "developerWebsiteUrl": "https://developer.example",
            "privacyUrl": "https://developer.example/privacy",
            "termsOfUseUrl": "https://developer.example/terms",
            "appVersion": "1.0.0",
            "publishScope": "Shared",
            "performBotRegistration": True,
            "publishAsAutopilot": False,
        },
        "missing_fields": [],
        "warnings": ["Metadata includes saved values."],
        "needs_publish": True,
        "active_version": {"id": "version-exact"},
        "config_path": str(config_dir / "variables.json"),
        "environment": "dev",
        "scope": "Shared",
        "profile_path": str(config_dir / "profile.json"),
        "receipt_path": str(config_dir / "receipt.json"),
        "surface": "Teams",
        "retry_uncertain": False,
        "access_instructions": "Find application-exact in the organization store.",
        "block_reasons": [],
    }
    backend.write_text(
        """import json, os, pathlib, sys
args = sys.argv[1:]
control = json.loads(pathlib.Path(os.environ["FAKE_CONTROL"]).read_text())
record = {"args": args}
for flag, key in (("--reviewed-plan", "reviewed_plan"), ("--metadata-file", "metadata")):
    if flag in args:
        record[key] = json.loads(pathlib.Path(args[args.index(flag) + 1]).read_text(encoding="utf-8-sig"))
with pathlib.Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\\n")
exit_code = control.get("apply_exit_code") if args[0] == "apply" else control.get("exit_code")
if exit_code:
    print("backend diagnostic without credentials", file=sys.stderr)
    sys.exit(exit_code)
if control.get("invalid_json"):
    print("not JSON")
    sys.exit(0)
plan = control["plan"]
if "metadata" in record and not control.get("keep_missing"):
    plan["publish_body"].update(record["metadata"])
    plan["missing_fields"] = []
    plan["block_reasons"] = []
    plan["status"] = "ready"
if args[0] == "plan":
    print(json.dumps(plan))
else:
    assert "--apply" in args and "reviewed_plan" in record
    print(json.dumps({"mode": "apply", "status": control.get("apply_status", "published"),
                      "target": record["reviewed_plan"]["target"], "application_id": "application-exact",
                      "access_instructions": "Find application-exact in the organization store."}))
""",
        encoding="utf-8",
    )

    class Runner:
        def __init__(self):
            self.root = root
            self.config_dir = config_dir
            self.backend = backend
            self.scratch = scratch
            self.plan = plan
            self.options = {}

        def run(self, filename=SURFACES[0][0], arguments="", *, wrapper=None, prelude="", confirmation=None):
            control.write_text(json.dumps({"plan": self.plan, **self.options}), encoding="utf-8")
            source = wrapper or copied_wrappers / filename
            env = dict(os.environ, FAKE_CONTROL=str(control), FAKE_LOG=str(log),
                       TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch))
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
            command = (
                "$ErrorActionPreference = 'Stop'; "
                + prelude
                + "; try { $result = & "
                + quote(source)
                + " "
                + arguments
                + "; Write-Output ('RESULT_JSON:' + (ConvertTo-Json -InputObject $result -Depth 100 -Compress)) "
                + "} catch { Write-Output ('FAILURE:' + $_.Exception.Message); exit 1 }"
            )
            shell_args = [PWSH, "-NoLogo", "-NoProfile"]
            if confirmation is None:
                shell_args.append("-NonInteractive")
            return subprocess.run(shell_args + ["-Command", command], cwd=config_dir, env=env,
                                  text=True, input=confirmation, capture_output=True, timeout=30)

        def calls(self):
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    return Runner()


def succeeded(result):
    assert result.returncode == 0, result.stdout + result.stderr


def failed(result, text):
    assert result.returncode != 0, result.stdout + result.stderr
    assert text.lower() in (result.stdout + result.stderr).lower()


def result_object(result):
    return json.loads(next(line.removeprefix("RESULT_JSON:") for line in result.stdout.splitlines()
                           if line.startswith("RESULT_JSON:")))


@pytest.mark.parametrize("filename,surface", SURFACES)
def test_whatif_plans_only_from_current_directory(runner, filename, surface):
    before = set(runner.config_dir.iterdir())
    result = runner.run(filename, "-WhatIf")
    succeeded(result)
    calls = runner.calls()
    assert len(calls) == 1
    args = calls[0]["args"]
    assert args[0] == "plan"
    assert args[args.index("--config-file") + 1] == str(runner.config_dir / "variables.json")
    assert args[args.index("--environment") + 1] == "dev"
    assert args[args.index("--surface") + 1] == surface
    assert "--scope" not in args
    assert set(runner.config_dir.iterdir()) == before
    assert list(runner.scratch.iterdir()) == []
    for text in ("tenant-exact", "subscription-exact", "agent-exact", "Disabled", "Enabled",
                 "old-auth", "Entra", "privacyUrl", "Teams", "Microsoft 365"):
        assert text in result.stdout
    assert result_object(result)["mode"] == "plan"


@pytest.mark.parametrize("filename,surface", SURFACES)
def test_whatif_never_prompts_for_missing_metadata(runner, filename, surface):
    runner.plan.update(status="blocked", missing_fields=["privacyUrl", "shortDescription"],
                       block_reasons=["metadata incomplete"])
    result = runner.run(filename, "-WhatIf", prelude="function global:Read-Host { throw 'PROMPT_FORBIDDEN' }")
    succeeded(result)
    assert "privacyUrl" in result.stdout and "shortDescription" in result.stdout
    assert "PROMPT_FORBIDDEN" not in result.stdout
    assert len(runner.calls()) == 1
    assert list(runner.scratch.iterdir()) == []


def test_saved_tenant_scope_is_explicit_in_preview_and_confirmation(runner):
    runner.plan["scope"] = "Tenant"
    runner.plan["publish_body"]["publishScope"] = "Tenant"
    result = runner.run(arguments="-WhatIf")
    succeeded(result)
    assert "all tenant users" in result.stdout.lower()
    assert "scope: Tenant" in result.stdout
    assert len(runner.calls()) == 1


@pytest.mark.parametrize("filename,surface", SURFACES)
def test_unattended_default_cannot_apply(runner, filename, surface):
    result = runner.run(filename, "-NonInteractive")
    failed(result, "-Confirm:$false")
    assert [call["args"][0] for call in runner.calls()] == ["plan"]
    assert list(runner.scratch.iterdir()) == []


@pytest.mark.parametrize("filename,surface", SURFACES)
def test_explicit_approval_applies_exact_reviewed_plan(runner, filename, surface):
    result = runner.run(filename, "-NonInteractive -Confirm:$false")
    succeeded(result)
    calls = runner.calls()
    assert [call["args"][0] for call in calls] == ["plan", "apply"]
    assert calls[1]["reviewed_plan"] == runner.plan
    assert calls[1]["args"][calls[1]["args"].index("--surface") + 1] == surface
    assert "--apply" in calls[1]["args"]
    assert result_object(result)["target"] == runner.plan["target"]
    assert "application-exact" in result.stdout
    assert list(runner.scratch.iterdir()) == []


def test_noninteractive_missing_metadata_cannot_apply(runner):
    runner.plan.update(status="blocked", missing_fields=["privacyUrl"])
    result = runner.run(arguments="-NonInteractive -Confirm:$false")
    failed(result, "privacyUrl")
    assert len(runner.calls()) == 1
    assert list(runner.scratch.iterdir()) == []


def test_blocked_recovery_never_applies(runner):
    runner.plan.update(status="blocked", block_reasons=["Uncertain previous publish requires operator recovery"])
    result = runner.run(arguments="-NonInteractive -Confirm:$false")
    failed(result, "Uncertain previous publish")
    assert len(runner.calls()) == 1


def test_already_published_is_not_applied_twice(runner):
    runner.plan.update(status="unchanged", needs_publish=False)
    runner.plan["preparation"].update(changed=False, patch={})
    runner.plan["preparation"]["after"] = runner.plan["preparation"]["before"]
    result = runner.run(arguments="-NonInteractive")
    succeeded(result)
    assert len(runner.calls()) == 1
    assert result_object(result)["status"] == "unchanged"


def test_existing_publication_with_preparation_changes_still_requires_approval(runner):
    runner.plan.update(status="unchanged", needs_publish=False)
    result = runner.run(arguments="-NonInteractive")
    failed(result, "-Confirm:$false")
    assert len(runner.calls()) == 1


def test_reviewed_plan_preserves_json_strings_without_datetime_conversion(runner):
    runner.plan["active_version"]["created_at"] = "2026-11-09T22:41:20Z"
    result = runner.run(arguments="-NonInteractive -Confirm:$false")
    succeeded(result)
    assert runner.calls()[-1]["reviewed_plan"] == runner.plan


def test_apply_failure_cleans_up_reviewed_plan(runner):
    runner.options["apply_exit_code"] = 23
    result = runner.run(arguments="-NonInteractive -Confirm:$false")
    failed(result, "23")
    assert [call["args"][0] for call in runner.calls()] == ["plan", "apply"]
    assert list(runner.scratch.iterdir()) == []


@pytest.mark.parametrize("options,message", [
    ({"exit_code": 19}, "19"),
    ({"invalid_json": True}, "JSON"),
])
def test_backend_failures_are_actionable(runner, options, message):
    runner.options = options
    result = runner.run(arguments="-NonInteractive -Confirm:$false")
    failed(result, message)
    assert len(runner.calls()) == 1
    assert list(runner.scratch.iterdir()) == []


def test_unexpected_json_conversion_error_is_not_mislabeled_as_invalid_json(runner):
    result = runner.run(
        arguments="-WhatIf",
        prelude="function global:ConvertFrom-Json { throw [System.InvalidOperationException]::new('UNEXPECTED_JSON_FAILURE') }",
    )
    failed(result, "UNEXPECTED_JSON_FAILURE")
    assert len(runner.calls()) == 1


def test_argument_arrays_preserve_spaces_apostrophes_and_shell_characters(runner):
    agent = "O'Brien agent; $(throw 'INJECTED')"
    project = "/subscriptions/a space/projects/O'Brien"
    profile = runner.config_dir / "O'Brien profile.json"
    result = runner.run(arguments=(
        "-NonInteractive -Confirm:$false -Environment prod -Scope Tenant -RetryUncertain "
        f"-AgentName {quote(agent)} -ProjectResourceId {quote(project)} -ProfileFile {quote(profile)} "
        f"-RepositoryRoot {quote(runner.root)}"
    ))
    succeeded(result)
    for call in runner.calls():
        args = call["args"]
        for flag, value in (("--agent-name", agent), ("--project-resource-id", project),
                            ("--profile-file", str(profile)), ("--scope", "Tenant"), ("--environment", "prod")):
            assert args[args.index(flag) + 1] == value
        assert "--retry-uncertain" in args
    assert "all tenant users" in result.stdout.lower()
    assert "admin" in result.stdout.lower()


@pytest.mark.parametrize("filename,surface", SURFACES)
def test_invalid_scope_rejected_before_backend(runner, filename, surface):
    failed(runner.run(filename, "-Scope Everything -Confirm:$false"), "Scope")
    assert runner.calls() == []


def test_copied_consumer_finds_backend_in_submodule(runner):
    copied = runner.config_dir / "automation" / "foundry-publishing"
    copied.mkdir(parents=True)
    for name in (SURFACES[0][0], "FoundryPublishing.psm1"):
        shutil.copyfile(WRAPPERS / name, copied / name)
    submodule = runner.root / "azure-enterprise-scale-ml" / BACKEND
    submodule.parent.mkdir(parents=True)
    runner.backend.rename(submodule)
    result = runner.run(arguments="-WhatIf", wrapper=copied / SURFACES[0][0])
    succeeded(result)
    assert len(runner.calls()) == 1


def test_invalid_explicit_repository_root_does_not_fall_back(runner):
    result = runner.run(arguments=f"-WhatIf -RepositoryRoot {quote(runner.config_dir)}")
    failed(result, "publish-foundry-agent.py")
    assert runner.calls() == []


def test_interactive_metadata_prompts_only_missing_fields_and_cleans_up(runner):
    runner.plan.update(status="blocked", missing_fields=["privacyUrl"])
    result = runner.run(
        arguments="-Confirm:$false",
        prelude="function global:Read-Host { param($Prompt) if ($Prompt -ne 'privacyUrl') { throw 'Unexpected prompt' }; 'https://legal.example/privacy' }",
    )
    succeeded(result)
    calls = runner.calls()
    assert [call["args"][0] for call in calls] == ["plan", "plan", "apply"]
    assert calls[1]["metadata"] == {"privacyUrl": "https://legal.example/privacy"}
    assert calls[2]["reviewed_plan"]["publish_body"]["privacyUrl"] == "https://legal.example/privacy"
    assert list(runner.scratch.iterdir()) == []


def test_metadata_reprompt_is_bounded_and_cleans_up(runner):
    runner.plan.update(status="blocked", missing_fields=["privacyUrl"])
    runner.options["keep_missing"] = True
    result = runner.run(
        arguments="-Confirm:$false",
        prelude="function global:Read-Host { 'not a legal URL' }",
    )
    failed(result, "metadata")
    assert 2 <= len(runner.calls()) <= 4
    assert all(call["args"][0] == "plan" for call in runner.calls())
    assert list(runner.scratch.iterdir()) == []


def test_cleanup_failure_warns_about_retained_metadata_without_hiding_apply_result(runner):
    runner.plan.update(status="blocked", missing_fields=["privacyUrl"])
    result = runner.run(
        arguments="-Confirm:$false",
        prelude=(
            "function global:Read-Host { 'https://legal.example/privacy' }; "
            "function global:Remove-Item { "
            "[CmdletBinding(SupportsShouldProcess=$true)] param([string]$LiteralPath, [switch]$Force); "
            "$problem = [System.Management.Automation.ErrorRecord]::new("
            "[System.UnauthorizedAccessException]::new('SIMULATED_CLEANUP_DENIED'), "
            "'SimulatedCleanupFailure', [System.Management.Automation.ErrorCategory]::PermissionDenied, $LiteralPath); "
            "$PSCmdlet.WriteError($problem) }"
        ),
    )
    retained = list(runner.scratch.iterdir())
    try:
        succeeded(result)
        assert result_object(result)["status"] == "published"
        assert len(retained) == 2
        assert "SIMULATED_CLEANUP_DENIED" in result.stdout
        for path in retained:
            assert str(path) in result.stdout
        assert "remove" in result.stdout.lower() and "manually" in result.stdout.lower()
    finally:
        for path in retained:
            path.unlink()


def test_default_confirmation_cannot_mutate_without_consent(runner):
    result = runner.run()
    assert result.returncode != 0
    assert [call["args"][0] for call in runner.calls()] == ["plan"]
    assert list(runner.scratch.iterdir()) == []


def test_inherited_confirm_preference_does_not_silently_approve_default(runner):
    result = runner.run(prelude="$ConfirmPreference = 'None'")
    assert result.returncode != 0
    assert [call["args"][0] for call in runner.calls()] == ["plan"]
    assert list(runner.scratch.iterdir()) == []


def test_declined_confirmation_never_applies_or_creates_reviewed_file(runner):
    result = runner.run(confirmation="n\n")
    succeeded(result)
    assert result_object(result)["status"] == "cancelled"
    assert [call["args"][0] for call in runner.calls()] == ["plan"]
    assert list(runner.scratch.iterdir()) == []


@pytest.mark.parametrize("status", ["pending_admin", "pending_verification", "verification_pending", "already_published"])
def test_final_status_and_store_instructions_are_preserved(runner, status):
    runner.options["apply_status"] = status
    result = runner.run(arguments="-NonInteractive -Confirm:$false")
    succeeded(result)
    assert result_object(result)["status"] == status
    assert "Find application-exact in the organization store." in result.stdout
    if status in {"pending_verification", "verification_pending"}:
        assert "Publication verification is pending." in result.stdout
    assert list(runner.scratch.iterdir()) == []
