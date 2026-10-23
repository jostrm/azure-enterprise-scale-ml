"""Offline ADO manual-UI defaults and reviewed-target boundary regressions."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
ADO = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project"


def expression(source, parameters, variables, *, dev="Succeeded", stage="Succeeded"):
    source = source.removeprefix("${{").removesuffix("}}").strip()
    source = re.sub(
        r"\$\{\{\s*(parameters|variables)\.(\w+)\s*\}\}",
        lambda match: str({"parameters": parameters, "variables": variables}[match[1]][match[2]]),
        source,
    )
    for name in ("and", "or", "not"):
        source = source.replace(f"{name}(", f"ado_{name}(")
    functions = {
        "eq": lambda a, b: str(a).lower() == str(b).lower(),
        "ne": lambda a, b: str(a).lower() != str(b).lower(),
        "ado_and": lambda *items: all(items), "ado_or": lambda *items: any(items),
        "ado_not": lambda value: not value,
        "succeeded": lambda: True, "canceled": lambda: False,
    }
    bindings = {
        "parameters": parameters,
        "variables": {**variables, "Build.Reason": "Manual"},
        "dependencies": {
            "Dev_GenAI_Project": {"result": dev},
            "Stage_GenAI_Project": {"result": stage},
        },
    }

    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("true", "false"):
                return node.id == "true"
            return bindings[node.id]
        if isinstance(node, ast.Attribute):
            return visit(node.value)[node.attr]
        if isinstance(node, ast.Subscript):
            return visit(node.value)[visit(node.slice)]
        assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        return functions[node.func.id](*(visit(arg) for arg in node.args))

    return visit(ast.parse(source, mode="eval").body)


def pipeline():
    return yaml.safe_load((ADO / "infra-project-genai.yaml").read_text(encoding="utf-8"))


def resolve(pipeline, target, json_override=False):
    parameters = {item["name"]: item["default"] for item in pipeline["parameters"]}
    parameters.update(deploymentTarget=target, useJsonConfigOverride=json_override)
    variables = {}
    for item in pipeline["variables"]:
        if item.get("name") == "reviewedDeploymentTarget":
            for key, body in item.items():
                if key.startswith("${{ if "):
                    selected = expression(key.replace("${{ if ", "${{ ", 1), parameters, variables)
                    if selected:
                        variables[item["name"]] = body["value"]
                        break
                elif key == "${{ else }}":
                    value = body["value"]
                    variables[item["name"]] = expression(value, parameters, variables)
    return parameters, variables


def reviewed_calls(value):
    if isinstance(value, dict):
        if value.get("template") == "./jobs/job-0-reviewed-project-config.yaml":
            yield value["parameters"]
        for item in value.values():
            yield from reviewed_calls(item)
    elif isinstance(value, list):
        for item in value:
            yield from reviewed_calls(item)


def test_run_ui_string_defaults_do_not_require_empty_fields():
    params = {item["name"]: item for item in pipeline()["parameters"]}
    assert params["deploymentTarget"]["default"] == "manual"
    # XXX shows the 3-digit format in the Run UI; the label says it is e.g. 001, not project001 or 1.
    assert params["deploymentProjectNumber"]["default"] == "XXX"
    assert "001" in params["deploymentProjectNumber"]["displayName"]
    assert "project001" in params["deploymentProjectNumber"]["displayName"]
    assert params["deploymentConfigHash"]["default"] == "not-applicable"
    assert params["deploymentSettings"]["default"] == {}
    assert all(params[key]["default"] for key in (
        "deploymentTarget", "deploymentProjectNumber", "deploymentConfigHash"
    ))
    assert "values" not in params["deploymentTarget"]  # Old API callers may still send an empty target.


@pytest.mark.parametrize("target", ["manual", "", "dev", "stage", "prod"])
@pytest.mark.parametrize("json_override", [False, True])
def test_manual_normalization_preserves_explicit_reviewed_targets(target, json_override):
    document = pipeline()
    parameters, variables = resolve(document, target, json_override)
    normalized = "" if target in {"manual", ""} else target
    assert variables["reviewedDeploymentTarget"] == normalized
    calls = list(reviewed_calls(document["stages"]))
    assert len(calls) == 18
    for call in calls:
        assert call["target"] == "${{ variables.reviewedDeploymentTarget }}"
        assert expression(call["target"], parameters, variables) == normalized
    overrides = [key for item in document["variables"] for key in item
                 if key.startswith("${{ if ") and "reviewedDeploymentTarget" in key]
    assert len(overrides) == 1
    assert expression(overrides[0].replace("${{ if ", "${{ ", 1), parameters, variables) == bool(normalized)


@pytest.mark.parametrize("target,expected", [
    ("manual", [True, True, True]), ("", [True, True, True]),
    ("dev", [True, False, False]), ("stage", [False, True, False]), ("prod", [False, False, True]),
])
def test_stage_selection_keeps_manual_promotion_and_reviewed_isolation(target, expected):
    document = pipeline()
    parameters, variables = resolve(document, target)
    results = [
        expression(item["condition"], parameters, variables,
                   dev="Skipped" if target in {"stage", "prod"} else "Succeeded",
                   stage="Skipped" if target == "prod" else "Succeeded")
        for item in document["stages"]
    ]
    assert results == expected


def test_reviewed_guards_stay_independent_of_optional_json_override():
    document = yaml.safe_load((ADO / "jobs/job-0-reviewed-project-config.yaml").read_text(encoding="utf-8"))
    key = next(key for step in document["steps"] for key in step if "eq(parameters.cleanup, false)" in key)
    assert "useJsonConfigOverride" not in key
    assert not expression(key.replace("${{ if ", "${{ ", 1), {"target": "", "cleanup": False}, {})
    assert expression(key.replace("${{ if ", "${{ ", 1), {"target": "dev", "cleanup": False}, {})
    source = (ADO / "jobs/job-0-reviewed-project-config.yaml").read_text(encoding="utf-8")
    for message in ("protected per-run configuration variable is required",
                    "Reviewed configuration hash mismatch", "Reviewed project identity mismatch"):
        assert message in source
    pipeline_source = (ADO / "infra-project-genai.yaml").read_text(encoding="utf-8")
    assert len(re.findall(r"parameters\.deploymentTarget", pipeline_source)) == 2


@pytest.mark.parametrize("missing", ["protected-json", "hash", "project"])
def test_reviewed_preflight_rejects_manual_placeholders_before_materialization(tmp_path, missing):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is required for reviewed-preflight execution")
    document = yaml.safe_load((ADO / "jobs/job-0-reviewed-project-config.yaml").read_text(encoding="utf-8"))
    branch = next(value for step in document["steps"] for key, value in step.items()
                  if "eq(parameters.cleanup, false)" in key)
    script = tmp_path / "reviewed-preflight.ps1"
    script.write_text(branch[0]["pwsh"], encoding="utf-8")
    config = json.dumps({"dev": {
        "project_number_000": "001", "tenantId": "11111111-1111-4111-8111-111111111111",
        "dev_sub_id": "22222222-2222-4222-8222-222222222222",
    }})
    environment = {
        **os.environ, "BUILD_SOURCESDIRECTORY": str(tmp_path),
        "AIFACTORY_CONFIG_FILE": "aifactory/.reviewed-project-config.json",
        "AIFACTORY_CONFIG_JSON": "" if missing == "protected-json" else config,
        "AIFACTORY_CONFIG_HASH": "not-applicable" if missing == "hash"
        else hashlib.sha256(config.encode("utf-8")).hexdigest(),
        "AIFACTORY_PROJECT": "XXX" if missing == "project" else "001",
        "AIFACTORY_TARGET": "dev",
    }
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(script)],
        capture_output=True, text=True, encoding="utf-8", timeout=30, env=environment,
    )
    assert result.returncode != 0
    assert {
        "protected-json": "protected per-run configuration variable is required",
        "hash": "Reviewed configuration hash mismatch",
        "project": "Reviewed project identity mismatch",
    }[missing] in result.stderr
    assert not (tmp_path / "aifactory/.reviewed-project-config.json").exists()
