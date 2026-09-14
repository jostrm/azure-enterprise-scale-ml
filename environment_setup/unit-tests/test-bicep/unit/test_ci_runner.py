from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

import pytest
import yaml

from base.config import REPO_ROOT
import run_ci


def test_default_collection_includes_root_tests_but_never_live_integration(tmp_path):
    (tmp_path / "unit").mkdir()
    (tmp_path / "integration").mkdir()
    (tmp_path / "test_parity.py").touch()
    (tmp_path / "integration" / "test_deploy.py").touch()
    assert run_ci.offline_test_paths(tmp_path) == [
        str(tmp_path / "unit"), str(tmp_path / "test_parity.py"),
    ]


def test_offline_environment_cannot_be_overridden_by_live_or_pytest_environment():
    with patch.dict(os.environ, {
        "LIVE_AZURE": "1", "BASH_ENV": "unsafe.sh", "ENV": "unsafe.sh",
        "PYTEST_ADDOPTS": "integration", "PYTEST_PLUGINS": "unexpected",
    }):
        environment = run_ci.offline_environment()
    assert environment["LIVE_AZURE"] == "0"
    assert environment["PYTHONUTF8"] == "1"
    assert not {"BASH_ENV", "ENV", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"} & environment.keys()


def test_yaml_loader_preserves_github_trigger_key_and_boolean_values():
    document = yaml.load("on:\n  push:\npermissions:\n  contents: read\nflag: false\n", Loader=run_ci.UniqueKeyLoader)
    assert "on" in document
    assert document["flag"] is False


@pytest.mark.parametrize("source", ["jobs:\n  build: 1\n  build: 2\n", "on: push\non: pull_request\n"])
def test_duplicate_yaml_keys_fail_instead_of_overwriting_a_trigger(source):
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        yaml.load(source, Loader=run_ci.UniqueKeyLoader)


def test_syntax_checks_never_execute_shell_or_python(tmp_path):
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    marker = tmp_path / "must-not-exist"
    (bootstrap / "script.sh").write_text(f"#!/usr/bin/env bash\ntouch '{marker.as_posix()}'\n", encoding="utf-8", newline="\n")
    (bootstrap / "script.py").write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    report = run_ci.check_syntax(tmp_path, run_ci.find_bash())
    assert report == {"checked": {"yaml": 0, "bash": 1, "python": 1}, "failures": []}
    assert not marker.exists()


def test_invalid_syntax_reports_every_affected_file(tmp_path):
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "bad.py").write_text("if :\n", encoding="utf-8")
    (bootstrap / "bad.sh").write_text("if then\n", encoding="utf-8", newline="\n")
    (bootstrap / "bad.yml").write_text("key: 1\nkey: 2\n", encoding="utf-8")
    report = run_ci.check_syntax(tmp_path, run_ci.find_bash())
    assert {failure["path"] for failure in report["failures"]} == {
        "bootstrap/bad.py", "bootstrap/bad.sh", "bootstrap/bad.yml",
    }


def test_crlf_bash_is_rejected_before_text_mode_can_hide_linux_failure(tmp_path):
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "windows.sh").write_bytes(b"#!/bin/bash\r\nset -euo pipefail\r\n")
    report = run_ci.check_syntax(tmp_path, run_ci.find_bash())
    assert len(report["failures"]) == 1
    assert "LF line endings" in report["failures"][0]["error"]


def test_failed_unit_suite_propagates_nonzero_and_forces_offline(tmp_path, monkeypatch):
    calls = []

    def failed(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(run_ci.subprocess, "run", failed)
    assert run_ci.main(["--phase", "unit", "--results-dir", str(tmp_path)]) == 1
    command, options = calls[0]
    assert "pytest" in command
    assert options["env"]["LIVE_AZURE"] == "0"
    assert not any(Path(argument).name == "integration" for argument in command)
    assert (tmp_path / "unit-summary.json").is_file()


def test_ci_missing_powershell_fails_before_any_tests_are_silently_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(run_ci, "find_bash", lambda: "bash")
    monkeypatch.setattr(run_ci.shutil, "which", lambda tool, **_: None if tool == "pwsh" else tool)
    with patch.object(run_ci.subprocess, "run") as execute:
        assert run_ci.main(["--phase", "unit", "--require-ci-tools", "--results-dir", str(tmp_path)]) == 1
    execute.assert_not_called()


def test_github_runs_all_checks_on_push_and_pull_requests_without_azure_permissions():
    path = REPO_ROOT / ".github" / "workflows" / "infrastructure-tests.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=run_ci.UniqueKeyLoader)
    assert {"push", "pull_request", "workflow_dispatch"} <= workflow["on"].keys()
    assert "pull_request_target" not in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["offline"]
    matrix = job["strategy"]["matrix"]["include"]
    assert {(row["phase"], row["os"]) for row in matrix} == {
        ("unit", "ubuntu-22.04"), ("unit", "windows-2022"),
        ("syntax", "ubuntu-22.04"), ("bicep", "ubuntu-22.04"),
    }
    assert job["defaults"]["run"]["shell"] == "bash"
    assert job["env"]["LIVE_AZURE"] == "0"
    assert "environment" not in job
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"actions/[\w-]+@[0-9a-f]{40}", step["uses"])
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    execution = next(step for step in job["steps"] if "run_ci.py" in step.get("run", ""))
    assert "--require-ci-tools" in execution["run"]
    assert "${{ secrets." not in path.read_text(encoding="utf-8")


def test_ado_runs_same_phases_without_service_connections_and_publishes_results():
    path = run_ci.SUITE / "azure-pipelines.yml"
    pipeline = yaml.load(path.read_text(encoding="utf-8"), Loader=run_ci.UniqueKeyLoader)
    assert pipeline["trigger"]["branches"]["include"] == ["*"]
    assert pipeline["pr"]["branches"]["include"] == ["*"]
    job = pipeline["jobs"][0]
    assert {value["testPhase"] for value in job["strategy"]["matrix"].values()} == {"unit", "syntax", "bicep"}
    assert {value["imageName"] for value in job["strategy"]["matrix"].values()
            if value["testPhase"] == "unit"} == {"ubuntu-22.04", "windows-2022"}
    steps = job["steps"]
    assert steps[0]["persistCredentials"] is False
    tasks = {step["task"] for step in steps if "task" in step}
    assert "PublishTestResults@2" in tasks
    assert not any(task.startswith(("AzureCLI", "AzurePowerShell", "AzureResourceManager")) for task in tasks)
    execution = next(step for step in steps if "run_ci.py" in step.get("bash", ""))
    assert execution["env"]["LIVE_AZURE"] == "0"
    assert "--require-ci-tools" in execution["bash"]


def test_bicep_installer_is_version_and_checksum_pinned():
    source = (run_ci.SUITE / "ci" / "install-bicep.sh").read_text(encoding="utf-8")
    assert re.search(r"version='\d+\.\d+\.\d+'", source)
    assert re.search(r"checksum='[a-f0-9]{64}'", source)
    assert "sha256sum --check --status" in source
    assert "latest" not in source


def test_legacy_dev_check_uses_the_same_pytest_discovery_not_unittest_only():
    path = REPO_ROOT / ".github" / "workflows" / "verify-aifactory-dev.yml"
    job = yaml.load(path.read_text(encoding="utf-8"), Loader=run_ci.UniqueKeyLoader)["jobs"]["run-iac-unit-tests"]
    assert job["env"]["LIVE_AZURE"] == "0"
    commands = [step["run"] for step in job["steps"] if "run" in step]
    assert any("pip install -r environment_setup/unit-tests/test-bicep/requirements.txt" in command for command in commands)
    assert any("run_ci.py --phase unit --require-ci-tools" in command for command in commands)
    assert not any("unittest discover" in command for command in commands)
