"""ADO compiles the scoped worker templates only when the conditional pool sits under a job (aif-163 run 2493).

Azure DevOps rejects a template expression in a root-level `pool:` ("A template expression is not allowed in this
context"), so the run POST failed with 400 and the worker never started. Verified with the pipelines preview API.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
TEMPLATES = ("factory-lifecycle-ado.yml", "factory-lifecycle-single-writer-ado.yml")


def load(name):
    return yaml.safe_load((ROOT / "bootstrap" / "templates" / name).read_text())


@pytest.mark.parametrize("name", TEMPLATES)
def test_scoped_ado_template_has_no_root_pool_and_keeps_the_conditional_pool_in_one_job(name):
    template = load(name)
    assert "pool" not in template and "steps" not in template
    assert len(template["jobs"]) == 1
    pool = template["jobs"][0]["pool"]
    assert any(key.startswith("${{ if eq(parameters.runnerKind, 'hosted') }}") for key in pool)
    assert any(key.startswith("${{ else }}") for key in pool)
    assert template["jobs"][0]["steps"][0]["checkout"] == "self"


@pytest.mark.parametrize("name", TEMPLATES)
def test_scoped_ado_template_optional_parameters_default_to_empty(name):
    parameters = {row["name"]: row for row in load(name)["parameters"]}
    assert all(parameters[key].get("default") == "" for key in ("vmImage", "agentPool", "agentName"))
