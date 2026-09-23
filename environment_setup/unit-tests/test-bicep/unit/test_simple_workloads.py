"""Offline end-to-end selection contracts; all external cloud calls are mocked."""

import ast
import itertools
import json
import shutil
import subprocess
import sys

import pytest

from domain.pipeline_contracts import GHA_PHASE, evaluate, load_pipeline
from unit.test_simple_bootstrap import CONFIG, LIB, ROOT, bash, settings


BASELINE = {"storage", "key-vault", "managed-identities"}
FOUNDRY = {"foundry", "foundry-capability-host", "ai-search", "cosmos-db"}
FLAGS = {
    "foundry": ("enableAIFoundry", "enableAIFactoryCreatedDefaultProjectForAIFv2"),
    "foundry-capability-host": ("enableAFoundryCaphost",),
    "ai-search": ("enableAISearch", "enableAISearchSharedPrivateLink"),
    "cosmos-db": ("enableCosmosDB",),
    "application-insights": ("enableApplicationInsights",),
    "azure-machine-learning": ("enableAzureMachineLearning", "addAzureMachineLearning"),
    "aks-for-azure-ml": ("enableAksForAzureML",),
    "aks": ("enableAKS",),
    "databricks": ("enableDatabricks",),
    "datafactory": ("enableDatafactory",),
    "event-hubs": ("enableEventHubs",),
    "postgresql": ("enablePostgreSQL",),
    "container-apps": ("enableContainerApps",),
}
SCENARIOS = [
    ["application-insights", "azure-machine-learning"],
    ["application-insights", "azure-machine-learning", "aks-for-azure-ml"],
    ["aks"],
    ["databricks"],
    ["datafactory"],
    ["event-hubs"],
    ["postgresql"],
    ["application-insights", "container-apps"],
]
PROVIDERS = {
    "foundry": "Microsoft.CognitiveServices",
    "ai-search": "Microsoft.Search",
    "cosmos-db": "Microsoft.DocumentDB",
    "azure-machine-learning": "Microsoft.MachineLearningServices",
    "aks": "Microsoft.ContainerService",
    "databricks": "Microsoft.Databricks",
    "datafactory": "Microsoft.DataFactory",
    "event-hubs": "Microsoft.EventHub",
    "postgresql": "Microsoft.DBforPostgreSQL",
    "container-apps": "Microsoft.App",
}


def test_literal_additive_selection_metadata_and_catalog_defaults():
    tree = ast.parse((LIB / "aifactory_scaleset_config.py").read_text(encoding="utf-8"))
    manifest = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "simple_mode_manifest")
    returned = next(node.value for node in manifest.body if isinstance(node, ast.Return))
    metadata = next(value for key, value in zip(returned.keys, returned.values)
                    if key.value == "projectResourceSelection")
    assert ast.literal_eval(metadata) == {
        "contractVersion": 1, "environment": "AIF_SIMPLE_PROJECT_RESOURCES_JSON",
        "omittedDefault": "catalog-defaults", "dependencies": "strict",
        "foundryRequires": ["foundry-capability-host", "ai-search", "cosmos-db"],
        "capabilityHostRequiresFoundry": True, "aksForAzureMLRequires": "azure-machine-learning",
    }
    catalog = CONFIG.SIMPLE_MODE_RESOURCE_CATALOG["project"]
    assert {item["id"] for item in catalog if item["required"]} == BASELINE
    assert {item["id"] for item in catalog if item["default_selected"]} == BASELINE | FOUNDRY | {"application-insights"}
    assert {item["id"] for item in catalog} == BASELINE | set(FLAGS)
    resources = {item["id"]: item for entries in CONFIG.SIMPLE_MODE_RESOURCE_CATALOG.values()
                 for item in entries}

    def visit(resource, ancestors):
        assert resource not in ancestors, f"Cyclic dependency at {resource}"
        for dependency in resources[resource]["dependencies"]:
            visit(dependency, ancestors | {resource})

    for resource in resources:
        visit(resource, set())
    foundry = next(item for item in catalog if item["id"] == "foundry")
    assert "foundry-capability-host" not in foundry["dependencies"]


def test_linked_application_insights_are_conditional_workload_dependencies():
    catalog = {item["id"]: item for item in CONFIG.SIMPLE_MODE_RESOURCE_CATALOG["project"]}
    assert catalog["application-insights"]["required"] is False
    for resource in ("azure-machine-learning", "container-apps"):
        assert "application-insights" in catalog[resource]["dependencies"]
        with pytest.raises(ValueError, match="application-insights"):
            CONFIG.simple_mode_project_resources([resource])
        assert resource in CONFIG.simple_mode_project_resources([resource, "application-insights"])
    aml = ROOT / "environment_setup/aifactory/bicep/modules/machineLearningv2.bicep"
    assert "applicationInsights: existingAppInsights.id" in aml.read_text(encoding="utf-8")


def test_compiled_container_apps_skip_search_rbac_when_search_is_unselected(tmp_path):
    compiler = shutil.which("bicep")
    if not compiler:
        pytest.skip("Existing Bicep CLI required for cached offline compilation")
    source = ROOT / "environment_setup/aifactory/bicep/esml-genai-1/05-compute-services.bicep"
    output = tmp_path / "compute.json"
    result = subprocess.run([compiler, "build", str(source), "--no-restore", "--outfile", str(output)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    template = json.loads(output.read_text(encoding="utf-8"))
    deployment = next(item for item in template["resources"] if "05rbacACAMI" in item["name"])
    binding = deployment["properties"]["parameters"]["aiSearchName"]
    if isinstance(binding, dict):
        assert binding["value"].startswith("[if(parameters('enableAISearch'),")
        assert binding["value"].endswith(", '')]")
    else:
        assert binding.startswith("[if(parameters('enableAISearch'),")
        assert binding.endswith(", createObject('value', ''))]")
    roles = deployment["properties"]["template"]["resources"]
    search_roles = [item for item in roles if "existingAiSearch" in item.get("name", "")
                    or "searchIndexDataContributorRoleId" in item.get("name", "")
                    or "searchServiceContributorRoleId" in item.get("name", "")]
    assert len(search_roles) == 2
    assert all(item["condition"] == "[not(empty(parameters('aiSearchName')))]" for item in search_roles)
    insights_roles = [item for item in roles if "monitoring" in item["name"]]
    assert len(insights_roles) == 2
    assert all("appInsightsName" in item["condition"] for item in insights_roles)


def test_exhaustive_project_domain_rejects_incomplete_dependencies_and_maps_all_flags():
    catalog = CONFIG.SIMPLE_MODE_RESOURCE_CATALOG["project"]
    optional = [item["id"] for item in catalog if not item["required"]]
    assert len(optional) == 13
    for bits in itertools.product((False, True), repeat=len(optional)):
        selection = {key for key, on in zip(optional, bits) if on}
        invalid = (
            ("foundry" in selection and not FOUNDRY <= selection)
            or ("foundry-capability-host" in selection and "foundry" not in selection)
            or ("aks-for-azure-ml" in selection and "azure-machine-learning" not in selection)
            or (bool(selection & {"azure-machine-learning", "container-apps"}) and "application-insights" not in selection)
        )
        if invalid:
            with pytest.raises(ValueError, match="requires selected project resources"):
                CONFIG.simple_mode_project_resources(list(selection))
            continue
        selected = CONFIG.simple_mode_project_resources(list(reversed(sorted(selection))) * 2)
        assert selected == [item["id"] for item in catalog if item["id"] in BASELINE | selection]
        values = CONFIG.simple_mode_values(project_resources=selected)
        for resource, flags in FLAGS.items():
            assert all(values[flag] == str(resource in selection).lower() for flag in flags), selection
        assert all(values[flag] == "false" for flag in CONFIG.SIMPLE_MODE_DISABLED)
        assert values["default_model_sku"] == values["modelGPTXSku"] == "DataZoneStandard"
        assert values["disableAgentNetworkInjection"] == str("foundry" not in selection).lower()


@pytest.mark.parametrize("selection", SCENARIOS, ids=[items[-1] for items in SCENARIOS])
@pytest.mark.parametrize("with_foundry", [False, True], ids=["foundry-off", "foundry-on"])
@pytest.mark.parametrize("route", ["gha", "ado"])
def test_eight_workloads_persist_real_flags_and_exports(tmp_path, selection, with_foundry, route):
    selection = selection + (sorted(FOUNDRY) if with_foundry else [])
    (tmp_path / "aifactory").mkdir()
    json_path = tmp_path / "aifactory/variables.json"
    shutil.copyfile(ROOT / "environment_setup/aifactory/variables.json", json_path)
    before = json.loads(json_path.read_text(encoding="utf-8"))
    before["stage_prod"] = {"enableAIFoundry": "false", "skuEventHubsStageProd": "Standard"}
    json_path.write_text(json.dumps(before), encoding="utf-8")
    if route == "gha":
        target = tmp_path / ".env"
        target.write_text("", encoding="utf-8")
    else:
        target = tmp_path / "aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
        target.parent.mkdir(parents=True)
        target.write_text("variables:\n", encoding="utf-8")
    state = settings() | {"simple_project_resources_json": json.dumps(selection)}
    getattr(CONFIG, f"apply_{route}")(tmp_path, state)
    document = json.loads(json_path.read_text(encoding="utf-8"))
    values = document["dev"]
    assert document["stage_prod"] == before["stage_prod"]
    expected = CONFIG.simple_mode_values(project_resources=selection)
    exports = CONFIG.simple_mode_env_values(expected) if route == "gha" else expected
    text = target.read_text(encoding="utf-8")
    for resource, flags in FLAGS.items():
        for flag in flags:
            assert values[flag] == str(resource in selection).lower()
            if route == "ado":
                assert f'  {flag}: "{expected[flag]}"' in text
            else:
                aliases = CONFIG.simple_mode_env_values(expected | {flag: "selection-marker"})
                names = [name for name, value in aliases.items() if value == "selection-marker"]
                assert names, f"No actual workflow alias for {flag}"
                assert all(f'{name}="{exports[name]}"' in text for name in names)
    assert all(values[key] == "false" for key in values if key.startswith("deployModel_"))
    assert values["default_model_sku"] == values["modelGPTXSku"] == "DataZoneStandard"
    assert values["skuEventHubsDev"] == "Standard"
    assert values["enablePublicGenAIAccess"] == values["allowPublicAccessWhenBehindVnet"] == "false"


@pytest.mark.parametrize("selection", [[], ["ai-search"], ["cosmos-db"], ["ai-search", "cosmos-db"]])
def test_independent_data_services_never_force_foundry_back_on(selection):
    values = CONFIG.common_values(settings() | {"simple_project_resources_json": json.dumps(selection)})
    assert values["enableAIFoundry"] == values["enableAFoundryCaphost"] == "false"
    assert values["enableAISearch"] == str("ai-search" in selection).lower()
    assert values["enableCosmosDB"] == str("cosmos-db" in selection).lower()


@pytest.mark.parametrize("selection", [
    ["foundry"], ["foundry", "ai-search", "cosmos-db"],
    ["foundry-capability-host"], ["foundry-capability-host", "ai-search", "cosmos-db"],
    ["aks-for-azure-ml"], ["aks-for-azure-ml", "aks"],
    ["azure-machine-learning"], ["container-apps"],
])
def test_invalid_workload_dependencies_fail_before_cloud_even_without_gateway(selection):
    result = bash(f"""AIF_ENABLE_APPLICATION_GATEWAY=false
AIF_PYTHON=('{sys.executable}'); AIF_SCALESET_LIB_DIR='{LIB}'
AIF_SIMPLE_PROJECT_RESOURCES_JSON='{json.dumps(selection)}'; GITHUB_REPOSITORY_VISIBILITY=private
aif_simple_gateway_config
az forbidden-after-invalid-selection
""", "aif_simple_gateway_config")
    assert result.returncode != 0 and "requires selected project resources" in result.stderr
    assert "UNEXPECTED_AZ" not in result.stderr


@pytest.mark.parametrize("selection", SCENARIOS + [[], sorted(FOUNDRY)], ids=[
    items[-1] for items in SCENARIOS] + ["baseline", "foundry"])
def test_shell_registers_selected_providers_and_keeps_shared_foundation(selection):
    result = bash(f"""AIF_SIMPLE_MODE=true; AIF_DRY_RUN=false
AIF_PYTHON=('{sys.executable}'); AIF_SCALESET_LIB_DIR='{LIB}'
AIF_SIMPLE_PROJECT_RESOURCES_JSON='{json.dumps(selection)}'
az() {{ [[ "$1 $2" == "provider register" ]] || return 91; printf '%s\\n' "$4" >&2; }}
aif_register_resource_providers sub
""", "aif_simple_project_config", "aif_register_resource_providers")
    assert result.returncode == 0, result.stderr
    expected = CONFIG.simple_mode_project_providers(selection)
    assert result.stderr.splitlines() == expected
    assert {"Microsoft.Network", "Microsoft.Storage", "Microsoft.KeyVault", "Microsoft.PolicyInsights"} <= set(expected)
    for resource, provider in PROVIDERS.items():
        present = resource in selection
        if provider == "Microsoft.ContainerService":
            present |= "aks-for-azure-ml" in selection
        if provider == "Microsoft.App":
            present |= "foundry" in selection
        assert (provider in expected) is present


@pytest.mark.parametrize("foundry,aml,datafactory", list(itertools.product((False, True), repeat=3)))
def test_foundry_aml_datafactory_matrix_reaches_flags_providers_and_principals(foundry, aml, datafactory):
    selection = sorted(FOUNDRY) if foundry else []
    if aml:
        selection += ["azure-machine-learning", "application-insights"]
    if datafactory:
        selection += ["datafactory"]
    values = CONFIG.common_values(settings() | {"simple_project_resources_json": json.dumps(selection)})
    exports = CONFIG.simple_mode_env_values(values)
    for name, enabled in [
        ("ENABLE_AI_FOUNDRY", foundry), ("ENABLE_FOUNDRY_CAPHOST", foundry),
        ("ENABLE_AI_SEARCH", foundry), ("ENABLE_COSMOS_DB", foundry),
        ("ENABLE_AZURE_MACHINE_LEARNING", aml), ("ADD_AZURE_MACHINE_LEARNING", aml),
        ("ENABLE_DATAFACTORY", datafactory),
    ]:
        assert exports[name] == str(enabled).lower()
    result = bash(f"""AIF_SIMPLE_MODE=true; AIF_DRY_RUN=false; AIF_ENABLE_APPLICATION_GATEWAY=false
AIF_PYTHON=('{sys.executable}'); AIF_SCALESET_LIB_DIR='{LIB}'
AIF_SIMPLE_PROJECT_RESOURCES_JSON='{json.dumps(selection)}'
AIF_AZURE_ML_PRINCIPAL_ID=; AIF_DATABRICKS_PRINCIPAL_ID=
az() {{
  if [[ "$1 $2" == 'provider register' ]]; then echo "$4" >&2
  elif [[ "$1 $2 $3" == 'ad sp show' && "$5" == 0736f41a-0425-4b46-bdb5-1563eff02385 ]]; then
    echo 11111111-1111-1111-1111-111111111111
  else echo UNEXPECTED_AZ >&2; return 91
  fi
}}
aif_register_resource_providers sub
aif_ensure_first_party_enterprise_apps
aif_deploy_simple_application_gateway
echo "AML=$AIF_AZURE_ML_PRINCIPAL_ID"
echo "DBX=$AIF_DATABRICKS_PRINCIPAL_ID"
""", "aif_simple_project_config", "aif_validate_guid", "aif_register_resource_providers",
                  "aif_ensure_first_party_enterprise_apps", "aif_deploy_simple_application_gateway")
    assert result.returncode == 0, result.stderr
    assert result.stderr.splitlines() == CONFIG.simple_mode_project_providers(selection)
    assert result.stdout.splitlines() == [
        "AML=" + ("11111111-1111-1111-1111-111111111111" if aml else ""), "DBX="]


@pytest.mark.parametrize("selection", [[], ["azure-machine-learning"], ["databricks"],
                                       ["azure-machine-learning", "databricks"]])
@pytest.mark.parametrize("existing", [True, False])
def test_only_selected_enterprise_principals_are_resolved_without_public_workspaces(selection, existing):
    if "azure-machine-learning" in selection:
        selection = selection + ["application-insights"]
    result = bash(f"""AIF_SIMPLE_MODE=true
AIF_PYTHON=('{sys.executable}'); AIF_SCALESET_LIB_DIR='{LIB}'
AIF_SIMPLE_PROJECT_RESOURCES_JSON='{json.dumps(selection)}'
AIF_AZURE_ML_PRINCIPAL_ID=; AIF_DATABRICKS_PRINCIPAL_ID=
az() {{
  [[ "$1 $2" == 'ad sp' && ( "$3" == show || "$3" == create ) ]] || {{ echo UNEXPECTED_RESOURCE >&2; return 91; }}
  printf '%s %s\\n' "$3" "$5" >&2
  if [[ "$3" == show && '{str(existing).lower()}' == false ]]; then return 1; fi
  printf '%s\\n' '11111111-1111-1111-1111-111111111111'
}}
aif_ensure_first_party_enterprise_apps
printf '%s\\n' "AML=$AIF_AZURE_ML_PRINCIPAL_ID" "DBX=$AIF_DATABRICKS_PRINCIPAL_ID"
""", "aif_simple_project_config", "aif_validate_guid", "aif_ensure_first_party_enterprise_apps")
    assert result.returncode == 0, result.stderr
    for resource, app_id, variable in [
        ("azure-machine-learning", "0736f41a-0425-4b46-bdb5-1563eff02385", "AML"),
        ("databricks", "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d", "DBX"),
    ]:
        assert (app_id in result.stderr) is (resource in selection and not existing)
        assert f"{variable}=" + ("11111111-1111-1111-1111-111111111111" if resource in selection else "") in result.stdout.splitlines()
    assert "UNEXPECTED_RESOURCE" not in result.stderr


@pytest.mark.parametrize("selection", SCENARIOS + [[]])
@pytest.mark.parametrize("runner_mode,runner_os,expected_runner", [
    ("github-hosted", "", "github-hosted"),
    ("self-hosted", "Linux", "self-hosted-linux"),
    ("self-hosted", "Windows", "self-hosted-windows"),
])
def test_gateway_off_still_dispatches_common_access_and_each_selected_workload(selection, runner_mode, runner_os, expected_runner):
    result = bash(f"""AIF_SIMPLE_MODE=true; AIF_ENABLE_APPLICATION_GATEWAY=false; AIF_NO_WAIT=false
AIF_RUNNER_MODE='{runner_mode}'; AIF_RUNNER_OS='{runner_os}'; AIF_DRY_RUN=false
AIF_SIMPLE_PROJECT_RESOURCES_JSON='{json.dumps(selection)}'
aif_run_github_workflow() {{
  if [[ "$1" == infra-project.yml ]]; then
    [[ " $* " == *" runner_selection={expected_runner} "* ]] || return 91
  fi
  echo "$1"
}}
aif_verify_common_resource_group() {{ echo COMMON; }}
aif_ensure_private_network_access() {{ echo VPN_DNS; }}
aif_ensure_github_self_hosted_agent() {{ echo RUNNER_READY; }}
aif_deploy_github
""", "aif_simple_stage", "aif_deploy_github", "aif_deploy_simple_application_gateway")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "AIF_SIMPLE_STAGE=common", "infra-common.yml", "COMMON", "AIF_SIMPLE_STAGE=hub",
        "VPN_DNS", "RUNNER_READY", "AIF_SIMPLE_STAGE=project", "infra-project.yml"]
    assert result.stderr == ""


@pytest.mark.parametrize("with_foundry", [False, True])
def test_actual_foundry_deploy_and_caphost_verification_guards(with_foundry):
    workflow = load_pipeline(GHA_PHASE)
    values = CONFIG.simple_mode_values(project_resources=sorted(FOUNDRY) if with_foundry else [])
    values.update({"aiFoundryV2Exists": "false", "debug_disable_69_aifoundry_2025": "false"})
    steps = {step["name"]: step for job in workflow["jobs"].values()
             for step in job["steps"] if "name" in step}
    names = [
        "69a-Validate-Subnet-For-NetworkInjection",
        "69-pre-account-ensure-AISearch-private-DNS-reachable",
        "69a-aifoundry-2025-2ndOption-Account",
        "69a-Grant-NetworkContributor-For-Injection",
        "69-Rehydrate", "69-wait-account-caphost-succeeded",
        "69b-aifoundry-2025-2ndOption-AccountUpdate",
        "69c_cosmosdb_data_contributor_for_foundry_project", "100b_create_foundry_agent",
    ]
    for name in names:
        context = {f"env.{key}": value for key, value in values.items()} | {"inputs.phase": "foundry"}
        assert bool(evaluate(steps[name]["if"], context)) is with_foundry, name
    for name in ["61-foundation", "63-cognitive-services", "64-databases",
                 "65-compute-services", "66-ai-platform", "67-data_ml_platform", "68-integration"]:
        assert evaluate(steps[name]["if"], context | {"inputs.phase": "infra"}), name
