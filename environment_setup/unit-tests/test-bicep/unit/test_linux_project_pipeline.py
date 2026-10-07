"""Linux opt-in must retain the legacy Windows task and workload contracts."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
JOBS = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs"


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def test_linux_tasks_are_explicit_opt_in_and_preserve_windows_defaults():
    for name in ("job-1-genai-networking.yaml", "job-2-genai-services.yaml"):
        document = yaml.safe_load((JOBS / name).read_text(encoding="utf-8"))
        parameter = next(p for p in document["parameters"] if p["name"] == "linuxRunner")
        assert parameter["default"] is False
        for task in walk(document["steps"]):
            if task.get("task") == "PowerShell@2":
                assert task["inputs"]["pwsh"] == "${{ parameters.linuxRunner }}"
            if task.get("task") == "AzureCLI@2":
                inputs = task["inputs"]
                assert inputs.get("scriptType") != "ps"
                if "${{ if eq(parameters.linuxRunner, true) }}" in inputs:
                    assert inputs["${{ if eq(parameters.linuxRunner, true) }}"]["scriptType"] == "pscore"
                    assert inputs["${{ else }}"]["scriptType"] == "ps"


def test_native_wif_subnet_path_reuses_allocator_without_az_module_install():
    document = yaml.safe_load((JOBS / "job-1-genai-networking.yaml").read_text(encoding="utf-8"))
    branch = next(s for s in document["steps"] if "${{ if eq(parameters.linuxRunner, true) }}" in s)
    task = branch["${{ if eq(parameters.linuxRunner, true) }}"][0]
    assert task["task"] == "AzureCLI@2"
    assert task["inputs"]["scriptType"] == "pscore"
    assert task["inputs"]["scriptPath"].endswith("/subnetCalc_v2.ps1")
    assert task["env"]["AIFACTORY_USE_AZURE_CLI"] == "true"
    assert "-useServicePrincipal" not in task["inputs"]["arguments"]
    assert "-projectNumber" in task["inputs"]["arguments"]
    legacy = next(s for s in document["steps"] if "${{ if eq(parameters.linuxRunner, false) }}" in s)
    assert legacy["${{ if eq(parameters.linuxRunner, false) }}"][0]["task"] == "AzurePowerShell@5"


def test_network_generated_parameters_stay_in_consumer_workspace():
    text = (JOBS / "job-1-genai-networking.yaml").read_text(encoding="utf-8")
    assert '$tempDir = "$(System.DefaultWorkingDirectory)/aifactory/parameters/"' in text
