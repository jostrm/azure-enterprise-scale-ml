"""Regression contracts for completing AKS after a partial AML deployment."""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"


def module_block(text, name):
    start = text.index(f"module {name} ")
    end = text.find("\nmodule ", start + 1)
    return text[start:end if end >= 0 else len(text)]


def test_aks_completion_does_not_require_recreating_workspace():
    source = (BICEP / "esml-genai-1" / "07-ml-data-platform.bicep").read_text()
    block = module_block(source, "amlv2Aks")
    declaration = block.splitlines()[0]
    assert "if(enableAzureMachineLearning && enableAksForAzureML)" in declaration
    assert "!amlExists" not in declaration
    assert "...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])" in block
    assert "aksExists: aksExists" in block
    assert "if(!amlExists && enableAzureMachineLearning)" in module_block(source, "amlv2").splitlines()[0]


def test_existing_cluster_attachment_omits_creation_only_sizes():
    source = (BICEP / "modules" / "machineLearningAks.bicep").read_text()
    compute = source[source.index("resource machineLearningCompute "):]
    common, creation = compute.split("}, !aksExists ? {", 1)
    assert "agentCount:" not in common
    assert "agentVmSize:" not in common
    assert "agentCount: env == 'dev' ? aksNodes_dev : aksNodes_testProd" in creation
    assert "agentVmSize: env == 'dev' ? aksVmSku_dev : aksVmSku_testProd" in creation
    assert "resourceId: aksResourceId" in common
    assert "env == 'dev' && !aksExists" in source
    assert "(env == 'test' || env == 'prod') && !aksExists" in source


def test_approved_aks_defaults_match_all_variable_templates():
    expected = {
        "admin_aks_gpu_sku_dev_override": "Standard_D4s_v5",
        "admin_aks_nodes_dev_override": 2,
        "admin_aks_version_override": "1.35.7",
    }
    config = json.loads((BICEP.parent / "variables.json").read_text(encoding="utf-8-sig"))
    ado = yaml.safe_load((BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml").read_text(encoding="utf-8-sig"))
    for name, value in expected.items():
        assert config["dev"][name] == value
        assert ado["variables"][name] == value
    github = BICEP / "copy_to_local_settings/github-actions"
    environment = (github / ".env.template").read_text(encoding="utf-8-sig")
    workflow = (github / "infra-project-phase.yml").read_text(encoding="utf-8-sig")
    for name, value in expected.items():
        assert f'{name.upper()}="{value}"' in environment
        assert f"{name}: ${{{{ vars.{name.upper()} || '{value}' }}}}" in workflow
