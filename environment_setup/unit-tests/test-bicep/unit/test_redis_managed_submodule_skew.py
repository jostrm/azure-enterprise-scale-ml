"""The consumer's workflow copy may be newer than its pinned submodule (byor-151 run 42415872025, 2026-11-07).

The Managed Redis validation step must only call redis_managed_config.py when the checked-out
azure-enterprise-scale-ml submodule ships it: skip with a warning when Redis is off, fail clearly when on.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
SETTINGS = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings"
GHA = SETTINGS / "github-actions" / "infra-project-phase.yml"
ADO = SETTINGS / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project" / "jobs" / "job-2-genai-services.yaml"
VALIDATOR = Path("azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/redis_managed_config.py")
PIPELINES = [("gha", "enableRedisManaged"), ("ado", "ENABLEREDISMANAGED")]


def bash():
    path = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    assert path.is_file(), "Git Bash or Bash is required for offline shell contracts"
    return path


def gha_script():
    document = yaml.safe_load(GHA.read_text(encoding="utf-8"))
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == "00_Validate_RedisManaged":
                return step["run"].replace("${{ env.dev_test_prod }}", "dev")
    raise AssertionError("00_Validate_RedisManaged step not found")


def ado_script(workdir):
    document = yaml.safe_load(ADO.read_text(encoding="utf-8"))
    for step in document["steps"]:
        script = str(step.get("inputs", {}).get("inlineScript", ""))
        if "redis_managed_config.py" in script:
            return (script.replace("$(System.DefaultWorkingDirectory)", workdir.as_posix())
                    .replace("$(dev_test_prod)", "dev"))
    raise AssertionError("Managed Redis validation task not found")


def run(pipeline, workdir, env):
    script = gha_script() if pipeline == "gha" else ado_script(workdir)
    (workdir / "case.sh").write_text(script, encoding="utf-8", newline="\n")
    stub = workdir / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "az").write_text("#!/usr/bin/env bash\necho AzureCloud\n", encoding="utf-8", newline="\n")
    (stub / "python").write_text('#!/usr/bin/env bash\necho "VALIDATOR:$*"\n', encoding="utf-8", newline="\n")
    return subprocess.run(
        [str(bash()), "--noprofile", "--norc", "-c", 'export PATH="$PWD/bin:$PATH"; . ./case.sh'],
        cwd=workdir, capture_output=True, text=True, encoding="utf-8", timeout=20, env={**os.environ, **env},
    )


@pytest.mark.parametrize("pipeline,variable", PIPELINES)
def test_missing_validator_with_redis_off_warns_and_continues(pipeline, variable):
    with tempfile.TemporaryDirectory() as directory:
        result = run(pipeline, Path(directory), {variable: "false"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "predates Azure Managed Redis" in result.stdout
    assert "VALIDATOR:" not in result.stdout


@pytest.mark.parametrize("pipeline,variable", PIPELINES)
def test_missing_validator_with_redis_on_fails_with_a_clear_message(pipeline, variable):
    with tempfile.TemporaryDirectory() as directory:
        result = run(pipeline, Path(directory), {variable: "true"})
    assert result.returncode != 0
    assert "submodule lacks" in result.stdout
    assert "VALIDATOR:" not in result.stdout


@pytest.mark.parametrize("pipeline,variable", PIPELINES)
def test_present_validator_is_still_called(pipeline, variable):
    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        target = workdir / VALIDATOR
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        result = run(pipeline, workdir, {variable: "true"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VALIDATOR:" in result.stdout and "--environment dev --cloud AzureCloud" in result.stdout
