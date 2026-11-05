"""Reviewed COMMON deployment contract of infra-common.yml (onion-deployment-mode API-2-Pipelines for COMMON).

The Factory API writes the scale set's common configuration as a run-specific GitHub environment secret, starts
infra-common.yml with a correlation id and the configuration hash, follows that exact run and deletes the secret
(the same contract infra-project.yml carries as AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1). Joakim, 2026-11-05: the
common resource group, VNet and subnets can be deployed by the pipeline instead of by the API's direct ARM route.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml"
REVIEWED = "aifactory/.reviewed-common-config.json"
JOBS = {"common-dev": "dev", "common-stage": "stage", "common-prod": "prod"}
SUBS = {"dev": "11111111-1111-1111-1111-111111111111", "stage": "22222222-2222-2222-2222-222222222222",
        "prod": "33333333-3333-3333-3333-333333333333"}
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    return text, document, document.get("on", document.get(True))


def steps(document, job):
    return {step.get("name"): step for step in document["jobs"][job]["steps"]}


def test_header_run_name_and_inputs_carry_the_contract():
    text, document, trigger = workflow()
    assert "# AIFACTORY_COMMON_DEPLOYMENT_CONTRACT=1" in text.splitlines()[:3]
    assert "inputs.deployment_id" in document["run-name"]
    inputs = trigger["workflow_dispatch"]["inputs"]
    for name in ("config_secret", "deployment_id", "config_hash", "scale_set_suffix"):
        assert name in inputs and inputs[name]["required"] is False, name
    assert inputs["config_secret"]["default"] == "AIFACTORY_CONFIG_JSON"
    assert inputs["deployment_id"]["default"] == "" and inputs["config_hash"]["default"] == ""


@pytest.mark.parametrize("job", JOBS)
def test_every_job_materializes_then_validates_before_the_json_identity(job):
    _, document, _ = workflow()
    env = document["jobs"][job]["env"]
    assert env["AIFACTORY_CONFIG_JSON"] == "${{ inputs.use_json_config_override && secrets[inputs.config_secret] || '' }}"
    names = [step.get("name") for step in document["jobs"][job]["steps"]]
    materialize = names.index("Materialize protected JSON configuration")
    validate = names.index("Validate reviewed common target")
    identity = names.index("Resolve JSON OpenID Connect identity")
    assert names.index("Checkout") < materialize < validate < identity
    step = steps(document, job)["Validate reviewed common target"]
    assert step["env"]["TARGET_ENVIRONMENT"] == JOBS[job]


def config(target="dev", suffix="-002"):
    values = {"tenantId": TENANT, "dev_sub_id": SUBS["dev"], "test_sub_id": SUBS["stage"], "prod_sub_id": SUBS["prod"],
              "admin_aifactorySuffixRG": suffix}
    return {"dev": values, "stage_prod": dict(values)}


def run_validation(tmp_path, *, document=None, target="dev", secret=None, change=None):
    _, parsed, _ = workflow()
    job = next(name for name, environment in JOBS.items() if environment == target)
    step = steps(parsed, job)["Validate reviewed common target"]
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    raw = json.dumps(document or config(target), sort_keys=True).encode("utf-8")
    (tmp_path / "aifactory").mkdir(exist_ok=True)
    (tmp_path / REVIEWED).write_bytes(raw)
    env = {**os.environ, "TARGET_ENVIRONMENT": target, "CONFIG_FILE": REVIEWED, "CONFIG_SECRET": "AIFACTORY_COMMON_X",
           "DEPLOYMENT_ID": str(uuid.uuid4()), "CONFIG_HASH": hashlib.sha256(raw).hexdigest(),
           "SCALE_SET_SUFFIX": "002", "USE_JSON_CONFIG_OVERRIDE": "true",
           "EXPECTED_SUBSCRIPTION": SUBS[target], "EXPECTED_TENANT": TENANT,
           "AIFACTORY_CONFIG_JSON": (raw.decode("utf-8") if secret is None else secret)}
    env.update(change or {})
    return subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("target", ["dev", "stage", "prod"])
def test_the_exact_reviewed_configuration_passes(tmp_path, target):
    result = run_validation(tmp_path, target=target)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change,message", [
    ({"CONFIG_HASH": "0" * 64}, "hash mismatch"),
    ({"SCALE_SET_SUFFIX": "003"}, "scale set mismatch"),
    ({"EXPECTED_SUBSCRIPTION": SUBS["prod"]}, "does not match the reviewed target"),
    ({"EXPECTED_TENANT": SUBS["dev"]}, "does not match the reviewed target"),
    ({"CONFIG_FILE": "aifactory/variables.json"}, "path mismatch"),
    ({"DEPLOYMENT_ID": "not-a-uuid"}, "deployment_id"),
    ({"USE_JSON_CONFIG_OVERRIDE": "false"}, "use_json_config_override"),
])
def test_any_drift_from_the_review_stops_the_run(tmp_path, change, message):
    result = run_validation(tmp_path, change=change)
    assert result.returncode != 0
    assert message in (result.stderr + result.stdout)


def test_a_file_that_differs_from_the_run_secret_stops_the_run(tmp_path):
    result = run_validation(tmp_path, secret=json.dumps(config(suffix="-009")))
    assert result.returncode != 0 and "differs from the run-specific secret" in result.stderr


def test_manual_runs_without_a_deployment_id_skip_the_review_contract():
    _, document, _ = workflow()
    condition = steps(document, "common-dev")["Validate reviewed common target"]["if"]
    assert "inputs.deployment_id != ''" in condition and REVIEWED in condition
