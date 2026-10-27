"""The GHA project job resolves the same common subnet as the common job.

Simple Mode dispatches the common workflow without the JSON override and the
project workflow with aifactory/variables.json. The shipped subnetCommon* values
are BYO examples, so with BYO_subnets=false they must not reach 02, 06 or 09.
Offline replay: job env, then 00_Apply_JSON_Config_Override, then the BYO guard
step, run as GitHub Actions would. Never deploys.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from . import test_simple_bootstrap as simple


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
GHA = BICEP / "copy_to_local_settings/github-actions"
PHASE = GHA / "infra-project-phase.yml"
COMMON = GHA / "infra-common.yml"
OVERRIDE = BICEP / "scripts/apply-json-config-overrides.py"
OVERRIDE_STEP = "00_Apply_JSON_Config_Override"
GUARD_STEP = "00_Resolve_Network_Env_Placeholders"
PROJECT_TEMPLATES = ("02-core-infrastructure.bicep", "06-ai-platform.bicep", "09-ai-foundry-2025-v4.bicep")
SUBNET_KEYS = ("BYO_subnets", "common_subnet_name", "subnetCommon", "subnetCommonScoring", "subnetCommonPowerbiGw")
COMMON_JOBS = {"dev": "common-dev", "stage": "common-stage", "prod": "common-prod"}
CREATED_COMMON_SUBNET = "snet-esml-cmn-001"  # vNetCommon.bicep creates common_subnet_name
BYO_SUBNET = "snet-customer-cmn-001"


def workflow(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def evaluate(expression, variables):
    """Evaluate the vars-only `||`, `&&`, `==` expressions these job env keys use."""
    inner = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", expression.strip()).group(1)
    assert re.fullmatch(r"[\w.\s'|&=()-]*", inner), inner
    python = re.sub(r"vars\.([A-Z0-9_]+)", r"vars.get('\1', '')", inner)
    python = python.replace("&&", " and ").replace("||", " or ")
    return eval(python, {"__builtins__": {}}, {"vars": variables})  # noqa: S307 - checked grammar above


def job_env(path, job, variables):
    env = workflow(path)["jobs"][job]["env"]
    return {key: evaluate(env[key], variables) for key in SUBNET_KEYS}


def read_github_env(path):
    values, lines = {}, path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    index = 0
    while index < len(lines):
        name, heredoc, delimiter = lines[index].partition("<<")
        if heredoc and "=" not in name:
            end = lines.index(delimiter, index + 1)
            values[name] = "\n".join(lines[index + 1:end])
            index = end + 1
        else:
            name, _, value = lines[index].partition("=")
            values[name] = value
            index += 1
    return values


def phase_steps():
    return workflow(PHASE)["jobs"]["deploy-project"]["steps"]


def step(name):
    return next(item for item in phase_steps() if item.get("name") == name)


def run_step(run, env, workspace):
    """Run a bash step with `${{ env.X }}` taken from the current job env, as Actions does."""
    script = re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", lambda match: env.get(match[1], ""), run)
    github_env, github_output = workspace / "step.env", workspace / "step.output"
    github_env.unlink(missing_ok=True)
    completed = subprocess.run(
        ["bash", "-c", script], cwd=workspace, text=True, capture_output=True, timeout=30,
        env={"PATH": os.environ["PATH"], **env, "GITHUB_ENV": str(github_env), "GITHUB_OUTPUT": str(github_output)})
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return {**env, **read_github_env(github_env)}


def apply_override(config, environment, env, workspace):
    (workspace / "aifactory").mkdir(exist_ok=True)
    (workspace / "aifactory/variables.json").write_text(json.dumps(config), encoding="utf-8")
    github_env = workspace / "override.env"
    github_env.unlink(missing_ok=True)
    completed = subprocess.run(
        [sys.executable, str(OVERRIDE), "--file", "aifactory/variables.json", "--environment", environment,
         "--format", "github", "--github-workflow", str(PHASE)],
        cwd=workspace, text=True, capture_output=True, timeout=60,
        env={**os.environ, "GITHUB_ENV": str(github_env)})
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return {**env, **read_github_env(github_env)}


def project_env(environment, variables, config, workspace):
    env = {**job_env(PHASE, "deploy-project", variables), "network_env": "dev"}
    if config is not None:
        env = apply_override(config, environment, env, workspace)
    return run_step(step(GUARD_STEP)["run"], env, workspace)


def project_subnet(env):
    # 02-core-infrastructure.bicep commonSubnetName; 06/09 commonSubnetPends.
    if env["subnetCommon"]:
        return env["subnetCommon"].replace("<network_env>", env.get("network_env", ""))
    return env["common_subnet_name"]


def common_subnet(env):
    # esml-common/main/13-rgLevel.bicep defaultSubnet.
    return env["subnetCommon"] if env["BYO_subnets"] == "true" else env["common_subnet_name"]


def simple_mode_config(tmp_path):
    repo = tmp_path / "repo"
    (repo / "aifactory").mkdir(parents=True)
    shutil.copyfile(ROOT / "environment_setup/aifactory/variables.json", repo / "aifactory/variables.json")
    (repo / ".env").write_text("", encoding="utf-8")
    simple.CONFIG.apply_gha(repo, simple.settings())
    return json.loads((repo / "aifactory/variables.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("environment", ["dev", "stage", "prod"])
def test_simple_mode_project_and_common_resolve_the_created_common_subnet(tmp_path, environment):
    config = simple_mode_config(tmp_path)
    assert config["dev"]["BYO_subnets"] == "false"
    assert config["dev"]["subnetCommon"] not in ("", CREATED_COMMON_SUBNET)  # shipped BYO example
    project = project_env(environment, {}, config, tmp_path)
    common = job_env(COMMON, COMMON_JOBS[environment], {})
    assert project_subnet(project) == common_subnet(common) == CREATED_COMMON_SUBNET
    assert project["subnetCommon"] == project["subnetCommonScoring"] == project["subnetCommonPowerbiGw"] == ""


def test_json_byo_subnets_keep_their_common_subnet(tmp_path):
    config = simple_mode_config(tmp_path)
    config["dev"].update(BYO_subnets="true", subnetCommon=BYO_SUBNET)
    project = project_env("dev", {}, config, tmp_path)
    common = job_env(COMMON, "common-dev", {"BYO_SUBNETS": "true", "SUBNET_COMMON": BYO_SUBNET})
    assert project_subnet(project) == common_subnet(common) == BYO_SUBNET
    assert project["subnetCommonScoring"] == config["dev"]["subnetCommonScoring"]


def test_json_byo_false_wins_over_byo_repository_variables(tmp_path):
    variables = {"BYO_SUBNETS": "true", "SUBNET_COMMON": BYO_SUBNET}
    project = project_env("dev", variables, simple_mode_config(tmp_path), tmp_path)
    assert project["BYO_subnets"] == "false"
    assert project_subnet(project) == CREATED_COMMON_SUBNET


@pytest.mark.parametrize("variables,expected", [
    ({}, CREATED_COMMON_SUBNET),
    ({"BYO_SUBNETS": "true", "SUBNET_COMMON": BYO_SUBNET}, BYO_SUBNET),
])
def test_repository_variables_without_json_override_are_unchanged(tmp_path, variables, expected):
    project = project_env("dev", variables, None, tmp_path)
    assert project_subnet(project) == common_subnet(job_env(COMMON, "common-dev", variables)) == expected


def test_guard_runs_after_json_override_and_before_project_templates():
    names = [item.get("name") for item in phase_steps()]
    runs = [item.get("run", "") for item in phase_steps()]
    deployed = {index: template for index, run in enumerate(runs) for template in PROJECT_TEMPLATES
                if f"esml-genai-1/{template}" in run}
    deploys = sorted(deployed)
    assert set(deployed.values()) == set(PROJECT_TEMPLATES)
    assert names.index(OVERRIDE_STEP) < names.index(GUARD_STEP) < min(deploys)
    assert "if" not in step(GUARD_STEP)
    for index in deploys:
        assert 'subnetCommon="${{ env.subnetCommon }}"' in runs[index], names[index]


@pytest.mark.parametrize("template,variable", [
    ("02-core-infrastructure.bicep", "commonSubnetName"),
    ("06-ai-platform.bicep", "commonSubnetPends"),
    ("09-ai-foundry-2025-v4.bicep", "commonSubnetPends"),
])
def test_project_templates_prefer_any_non_empty_subnet_common(template, variable):
    # project_subnet() models this: the templates do not read BYO_subnets, so the job must clear it.
    source = re.sub(r"\s+", "", (BICEP / "esml-genai-1" / template).read_text(encoding="utf-8"))
    assert re.search(rf"var{variable}=(!empty\(subnetCommon\)|subnetCommon!='')\?"
                     r"replace\(subnetCommon,'<network_env>',network_env\):common_subnet_name", source)
    assert "paramBYO_subnets" not in source


def test_common_template_gates_subnet_common_on_byo_subnets():
    # common_subnet() models this.
    source = re.sub(r"\s+", "", (BICEP / "esml-common/main/13-rgLevel.bicep").read_text(encoding="utf-8"))
    assert "vardefaultSubnet=(BYO_subnets)?replace(subnetCommon,'<network_env>',network_env):common_subnet_name" in source
