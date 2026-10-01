"""Offline contracts for Azure AI Search capacity fallback."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
HELPER = BICEP / "scripts" / "ai-search-capacity-retry.sh"
VARIABLES = BICEP.parent / "variables.json"
ADO_VARIABLES = BICEP / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines" / "variables" / "variables.yaml"
ADO_PIPELINE = BICEP / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project" / "jobs" / "job-2-genai-services.yaml"
GHA_ENV = BICEP / "copy_to_local_settings" / "github-actions" / ".env.template"
GHA_PIPELINE = BICEP / "copy_to_local_settings" / "github-actions" / "infra-project-phase.yml"


def bash(script: str) -> subprocess.CompletedProcess[str]:
    executable = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    if not executable.is_file():
        executable = Path(shutil.which("bash") or "")
    if not executable.is_file():
        pytest.skip("Bash is required")
    return subprocess.run(
        [str(executable), "--noprofile", "--norc", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_capacity_retry_candidates_start_with_selected_sku_without_repeating_it():
    result = bash(
        f'cd "{ROOT.as_posix()}"; source "environment_setup/aifactory/bicep/scripts/{HELPER.name}"; '
        'aif_ai_search_candidate_order standard basic,standard,standard2 true'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["standard", "basic", "standard2"]


@pytest.mark.parametrize("candidates", ["", "basic,standard,standard2,standard3", "basic,standard,standard"])
def test_capacity_retry_rejects_invalid_candidate_arrays(candidates):
    result = bash(
        f'cd "{ROOT.as_posix()}"; source "environment_setup/aifactory/bicep/scripts/{HELPER.name}"; '
        f'aif_ai_search_candidate_order standard "{candidates}" true'
    )
    assert result.returncode != 0


def test_capacity_retry_matches_only_capacity_failures(tmp_path):
    capacity = tmp_path / "capacity.log"
    capacity.write_text("Code=SkuNotAvailable; insufficient capacity in this region", encoding="utf-8")
    unrelated = tmp_path / "unrelated.log"
    unrelated.write_text("AuthorizationFailed", encoding="utf-8")
    result = bash(
        f'cd "{ROOT.as_posix()}"; source "environment_setup/aifactory/bicep/scripts/{HELPER.name}"; '
        f'aif_ai_search_is_capacity_failure "{capacity.as_posix()}"; '
        f'! aif_ai_search_is_capacity_failure "{unrelated.as_posix()}"'
    )
    assert result.returncode == 0, result.stderr


def test_capacity_retry_defaults_and_pipeline_wiring_are_consistent():
    defaults = {
        "skuArrayAISearchDev": "basic,standard,standard2",
        "skuArrayAISearchStageProd": "basic,standard,standard2",
        "aisearchRetryCapcityArray": "true",
    }
    assert {key: json.loads(VARIABLES.read_text(encoding="utf-8"))["dev"][key] for key in defaults} == defaults
    ado = yaml.safe_load(ADO_VARIABLES.read_text(encoding="utf-8"))["variables"]
    assert {key: ado[key] for key in defaults} == defaults
    github_env = GHA_ENV.read_text(encoding="utf-8")
    github_names = {
        "skuArrayAISearchDev": "SKU_ARRAY_AISEARCH_DEV",
        "skuArrayAISearchStageProd": "SKU_ARRAY_AISEARCH_STAGEPROD",
        "aisearchRetryCapcityArray": "AISEARCH_RETRY_CAPCITY_ARRAY",
    }
    for key, value in defaults.items():
        assert f'{github_names[key]}="{value}"' in github_env
        assert f"{key}: ${{{{ vars.{github_names[key]} ||" in GHA_PIPELINE.read_text(encoding="utf-8")
    for pipeline in (ADO_PIPELINE, GHA_PIPELINE):
        source = pipeline.read_text(encoding="utf-8")
        assert "03b-ai-search.bicep" in source
        assert "--parameters deployAISearch=false" in source
        assert "ai-search-capacity-retry.sh" not in source
