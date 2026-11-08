"""An added scale set joins the factory's own access hub (aif-154, 2026-11-08).

Own-hub factories (access_hub_mode integrated + setup_hub_access, no central DNS policy) create the hub and every
private DNS zone for the bootstrap scale set only. An added scale set (DEV/002) got the same factory-level values,
so 13-rgLevel skipped zone creation and pointed its zone groups at its own resource group, which has no zones:
"Private Dns Zone group ... has invalid private dns zone ids" (GHA run 42483312656). It was not peered to the hub
and its VNet was linked to no zone either.

Contract (2026-11-08): own_hub_vnet_id and own_hub_private_dns_resource_group_id, both default ''. Set only for a
non-bootstrap scale set of an own-hub factory; empty keeps every other topology exactly as before.
"""

from pathlib import Path
import json
import os
import re
import shlex
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
CLS = BICEP / "copy_to_local_settings"
GHA = CLS / "github-actions"
ADO = CLS / "azure-devops" / "esml-yaml-pipelines"
COMMON = BICEP / "esml-common" / "main" / "13-rgLevel.bicep"
FOUNDATION = BICEP / "esml-genai-1" / "01-foundation.bicep"
PEERING = BICEP / "modules" / "networking" / "vnetPeering.bicep"
LINKS = BICEP / "modules" / "networking" / "privateDnsZoneVnetLinks.bicep"
CONTEXT = BICEP / "modules" / "common" / "CmnServiceDeploymentContext.bicep"

VNET = "own_hub_vnet_id"
DNS = "own_hub_private_dns_resource_group_id"
# Project templates the pipelines deploy that resolve private DNS zone ids (01 has its own rule, see below).
PROJECT_TEMPLATES = [
    "esml-genai-1/02-core-infrastructure.bicep",
    "esml-genai-1/03-cognitive-services.bicep",
    "esml-genai-1/04-databases.bicep",
    "esml-genai-1/05-compute-services.bicep",
    "esml-genai-1/06-ai-platform.bicep",
    "esml-genai-1/07-ml-data-platform.bicep",
    "esml-genai-1/08-rbac-security.bicep",
    "esml-genai-1/09-ai-foundry-2025-v4.bicep",
    "esml-genai-1/11-integration.bicep",
    "modules/common/CmnServiceDeploymentContext.bicep",
]
CONTEXT_CALLERS = [
    "esml-genai-1/03b-ai-search.bicep",
    "esml-genai-1/04b-postgresql.bicep",
    "esml-genai-1/05b-container-apps.bicep",
]


def text(path):
    return Path(path).read_text(encoding="utf-8")


def block(source, header):
    """The body of the module/resource declaration that starts with header, up to its closing brace."""
    start = source.index(header)
    depth, index = 0, source.index("{", start)
    for index in range(index, len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(header)


def declares(name):
    return re.compile(r"^param " + name + r" string = ''$", re.M)


# ---------------------------------------------------------------- 13-rgLevel (common)

def test_common_declares_both_contract_parameters_and_the_join_switch():
    common = text(COMMON)
    assert declares(VNET).search(common)
    assert declares(DNS).search(common)
    assert "var joinOwnHub = bootstrapManagedPrivateDns && own_hub_vnet_id != ''" in common


def test_common_zone_ids_come_from_the_own_hub_dns_group_and_otherwise_stay_unchanged():
    common = text(COMMON)
    rg = re.search(r"^var privDnsResourceGroupName = (.+)$", common, re.M)[1]
    sub = re.search(r"^var privDnsSubscription = (.+)$", common, re.M)[1]
    assert rg.startswith("joinOwnHub ? ownHubPrivateDnsParts[4] : ")
    assert sub.startswith("joinOwnHub ? ownHubPrivateDnsParts[2] : ")
    # Empty parameters: the expressions are the unchanged pre-own-hub ones.
    assert rg.endswith("((privDnsResourceGroup_param != '' && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName)")
    assert sub.endswith("((privDnsSubscription_param != '' && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd)")
    assert "split('${ownHubPrivateDnsResourceGroupId}////', '/')" in common
    # Without an explicit DNS group the zones are in the hub VNet's resource group (aif-154 layout).
    assert ("var ownHubPrivateDnsResourceGroupId = own_hub_private_dns_resource_group_id != '' ? "
            "own_hub_private_dns_resource_group_id : '/subscriptions/${ownHubVnetParts[2]}/resourceGroups/${ownHubVnetParts[4]}'") in common


def test_common_peers_hub_to_spoke_first_then_spoke_to_hub():
    common = text(COMMON)
    hub = block(common, "module ownHubPeeringHubToSpoke '../../modules/networking/vnetPeering.bicep' = if (joinOwnHub)")
    spoke = block(common, "module ownHubPeeringSpokeToHub '../../modules/networking/vnetPeering.bicep' = if (joinOwnHub)")
    assert "scope: resourceGroup(ownHubSubscriptionId, ownHubResourceGroupName)" in hub
    common_vars = (
        "var ownHubSubscriptionId = joinOwnHub ? ownHubVnetParts[2] : subscriptionIdDevTestProd",
        "var ownHubResourceGroupName = joinOwnHub ? ownHubVnetParts[4] : vnetResourceGroupName",
    )
    assert all(line in common for line in common_vars)
    assert "vnetName: ownHubVnetParts[8]" in hub
    assert "remoteVnetId: vnetId" in hub
    assert "allowGatewayTransit: true" in hub and "useRemoteGateways: false" in hub
    assert "scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)" in spoke
    assert "vnetName: vnetNameFull" in spoke
    assert "remoteVnetId: own_hub_vnet_id" in spoke
    assert "allowGatewayTransit: false" in spoke and "useRemoteGateways: true" in spoke
    assert re.search(r"dependsOn: \[\s*ownHubPeeringHubToSpoke\s*\]", spoke)
    # Deterministic peering names: re-runs PUT the same child, a second added scale set gets its own.
    assert "peeringName: take('peer-${vnetNameFull}-${uniqueString(vnetId)}', 80)" in hub
    assert "peeringName: take('peer-${ownHubVnetParts[8]}-${uniqueString(own_hub_vnet_id)}', 80)" in spoke


def test_common_links_every_zone_of_the_own_hub_group_to_its_common_vnet():
    common = text(COMMON)
    links = block(common, "module ownHubPrivateDnsLinks '../../modules/networking/privateDnsZoneVnetLinks.bicep' = if (joinOwnHub)")
    assert "scope: resourceGroup(privDnsSubscription, privDnsResourceGroupName)" in links
    assert "privateLinksDnsZones: privateLinksDnsZonesArray" in links
    assert "vnetId: vnetId" in links
    # The bootstrap's own zone creation stays off for every own-hub scale set.
    assert ("module createPrivateDnsZonesIfNotExists '../../modules/createPrivateDnsZones.bicep' = "
            "if(!centralDnsZoneByPolicyInHub && !bootstrapManagedPrivateDns)") in common


def test_peering_module_sets_the_reviewed_properties():
    peering = text(PEERING)
    assert "resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing" in peering
    resource = block(peering, "resource peering 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01'")
    assert "parent: vnet" in resource and "name: peeringName" in resource
    for line in ("allowVirtualNetworkAccess: true", "allowForwardedTraffic: true",
                 "allowGatewayTransit: allowGatewayTransit", "useRemoteGateways: useRemoteGateways",
                 "id: remoteVnetId"):
        assert line in resource


def test_link_module_links_existing_zones_without_rewriting_them():
    links = text(LINKS)
    # Zones are the bootstrap's (with its tags): referenced, never PUT again.
    assert "resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' existing = [for zone in privateLinksDnsZones:" in links
    resource = block(links, "resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01'")
    assert "parent: zones[i]" in resource
    assert "name: take('${last(split(vnetId, '/'))}-${uniqueString(vnetId)}', 80)" in resource
    assert "registrationEnabled: false" in resource
    assert "id: vnetId" in resource
    assert not re.search(r"privateDnsZones@[^']+' = ", links)


# ---------------------------------------------------------------- project templates

def test_foundation_uses_the_own_hub_dns_group_only_with_bootstrap_managed_dns():
    foundation = text(FOUNDATION)
    assert declares(DNS).search(foundation)
    assert ("var ownHubPrivateDns = bootstrapManagedPrivateDns && "
            "startsWith(toLower(own_hub_private_dns_resource_group_id), '/subscriptions/')") in foundation
    rg = re.search(r"^var privDnsResourceGroupName = (.+)$", foundation, re.M)[1]
    sub = re.search(r"^var privDnsSubscription = (.+)$", foundation, re.M)[1]
    assert rg.startswith("ownHubPrivateDns ? ownHubPrivateDnsParts[4] : (")
    assert sub.startswith("ownHubPrivateDns ? ownHubPrivateDnsParts[2] : (")


@pytest.mark.parametrize("template", PROJECT_TEMPLATES)
def test_project_template_resolves_zones_in_the_own_hub_dns_group(template):
    source = text(BICEP / template)
    assert declares(DNS).search(source), template
    # A literal '$(own_hub_private_dns_resource_group_id)' (ADO, variable not defined) is not an id.
    assert ("var ownHubPrivateDns = !centralDnsZoneByPolicyInHub && "
            "startsWith(toLower(own_hub_private_dns_resource_group_id), '/subscriptions/')") in source, template
    assert "var ownHubPrivateDnsParts = split('${own_hub_private_dns_resource_group_id}////', '/')" in source, template
    if template.endswith(("07-ml-data-platform.bicep", "11-integration.bicep")):
        zones = block(source, "module CmnZones '../modules/common/CmnPrivateDnsZones.bicep'")
        assert "privDnsResourceGroupName: ownHubPrivateDns ? ownHubPrivateDnsParts[4] : vnetResourceGroupName" in zones
        assert "privDnsSubscription: ownHubPrivateDns ? ownHubPrivateDnsParts[2] : subscriptionIdDevTestProd" in zones
    else:
        assert re.search(r"^var privDnsResourceGroupName = ownHubPrivateDns \? ownHubPrivateDnsParts\[4\] : \(", source, re.M), template
        assert re.search(r"^var privDnsSubscription = ownHubPrivateDns \? ownHubPrivateDnsParts\[2\] : \(", source, re.M), template


@pytest.mark.parametrize("template", CONTEXT_CALLERS)
def test_capacity_templates_forward_the_dns_group_to_the_shared_context(template):
    source = text(BICEP / template)
    assert declares(DNS).search(source)
    context = block(source, "module deploymentContext '../modules/common/CmnServiceDeploymentContext.bicep'")
    assert "own_hub_private_dns_resource_group_id: own_hub_private_dns_resource_group_id" in context


# ---------------------------------------------------------------- pipelines

def templates_declaring(name):
    return {str(p.relative_to(BICEP)).replace("\\", "/") for p in BICEP.rglob("*.bicep")
            if declares(name).search(text(p))}


def commands(path):
    """(line, template, command text) of each az deployment of a template in path."""
    lines = text(path).splitlines()
    for number, line in enumerate(lines):
        # GHA: azure-enterprise-scale-ml/environment_setup/aifactory/bicep/<template>; ADO: <template> (relative).
        match = re.search(r"--template-file \"?(?:[^\"\s]*?/aifactory/bicep/)?((?:esml-|modules/)[^\"\s]+\.bicep)", line)
        if not match:
            continue
        command = []
        for item in lines[number:]:
            command.append(item)
            if not item.rstrip().endswith("\\"):
                break
        yield number + 1, match[1], "\n".join(command)


GHA_FILES = [GHA / "infra-common.yml", GHA / "infra-project-phase.yml"]
ADO_FILES = [ADO / "esml-infra-common" / "jobs" / "job-1-aif-cmn.yaml",
             ADO / "esml-infra-project" / "jobs" / "job-2-genai-services.yaml"]


def deployments(files, name):
    declared = templates_declaring(name)
    for path in files:
        for number, template, command in commands(path):
            if template in declared and "--parameters-file" not in command:
                yield path.name, number, template, command


def test_the_workflows_deploy_every_template_that_declares_the_parameters():
    assert templates_declaring(VNET) == {"esml-common/main/13-rgLevel.bicep"}
    deployed = {template for _, _, template, _ in deployments(GHA_FILES, DNS)}
    assert deployed == templates_declaring(DNS) - set(CONTEXT_CALLERS) - {"modules/common/CmnServiceDeploymentContext.bicep"}


@pytest.mark.parametrize("name,number,template,command", list(deployments(GHA_FILES, DNS)), ids=lambda i: str(i)[:60])
def test_gha_deployment_passes_the_own_hub_parameters(name, number, template, command):
    assert DNS + '="${{ env.' + DNS + ' }}"' in command, f"{name}:{number}"
    if template == "esml-common/main/13-rgLevel.bicep":
        assert VNET + '="${{ env.' + VNET + ' }}"' in command, f"{name}:{number}"


@pytest.mark.parametrize("name,number,template,command", list(deployments(ADO_FILES, DNS)), ids=lambda i: str(i)[:60])
def test_ado_deployment_passes_the_own_hub_parameters(name, number, template, command):
    assert DNS + '="$(' + DNS + ')"' in command, f"{name}:{number}"
    if template == "esml-common/main/13-rgLevel.bicep":
        assert VNET + '="$(' + VNET + ')"' in command, f"{name}:{number}"


def job_env(path):
    return re.findall(r"^\s{6}(own_hub_\w+): (.+)$", text(path), re.M)


def test_gha_jobs_bind_the_repository_variables_for_non_json_runs():
    # deploy-capacity-resource.py (03b/04b/05b) fills template parameters from the job environment by name.
    for path, jobs in ((GHA / "infra-common.yml", 3), (GHA / "infra-project-phase.yml", 1)):
        bindings = job_env(path)
        assert bindings.count((VNET, "\"${{ vars.OWN_HUB_VNET_ID || '' }}\"")) == jobs, path.name
        assert bindings.count((DNS, "\"${{ vars.OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID || '' }}\"")) == jobs, path.name


def test_gha_zone_discovery_looks_in_the_own_hub_dns_group():
    phase = text(GHA / "infra-project-phase.yml")
    step = phase[phase.index("- name: 15_Check_Private_DNS_Zones"):phase.index("- name: 16_Check_Resource_Existence")]
    assert 'OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID: ${{ env.own_hub_private_dns_resource_group_id }}' in step
    assert 'elif [[ "${OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID,,}" == /subscriptions/* ]]; then' in step
    assert "privDnsSubscription=\"$(cut -d/ -f3 <<< \"$OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID\")\"" in step
    assert "privDnsRg=\"$(cut -d/ -f5 <<< \"$OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID\")\"" in step


def bash_executable():
    """Git Bash on Windows (WSL's bash.exe does not see Windows paths), bash elsewhere."""
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


@pytest.mark.parametrize("own_hub,subscription,group", [
    ("/subscriptions/hub-sub/resourceGroups/hub-rg", "hub-sub", "hub-rg"),
    ("", "project-sub", "spoke-rg"),
    ("$(own_hub_private_dns_resource_group_id)", "project-sub", "spoke-rg"),
])
def test_gha_zone_discovery_runs_against_the_zone_group(tmp_path, own_hub, subscription, group):
    bash = bash_executable()
    if not bash:
        pytest.skip("bash is required (Git Bash on Windows)")
    workflow = yaml.safe_load(text(GHA / "infra-project-phase.yml"))
    step = next(item for job in workflow["jobs"].values() for item in job.get("steps", [])
                if item.get("name") == "15_Check_Private_DNS_Zones")
    values = {"centralDnsZoneByPolicyInHub": "false", "dev_test_prod_sub_id": "project-sub",
              "vnetResourceGroup_resolved": "spoke-rg", "vnetNameFull_resolved": "spoke",
              "admin_location": "swedencentral", "privDnsSubscription_param": "", "privDnsResourceGroup_param": ""}
    source = re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", lambda m: values[m[1]], step["run"])
    source = source.replace('"$GITHUB_ENV"', shlex.quote((tmp_path / "github-env").as_posix()))
    spoke = "/subscriptions/project-sub/resourceGroups/spoke-rg/providers/Microsoft.Network/virtualNetworks/spoke"
    prelude = f"""
export DNS_MANAGED_BY_POLICY=false
export OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID={shlex.quote(own_hub)}
az() {{
  printf '%s\n' "$*" >> calls.log
  if [ "$1 $2 $3 $4" = "network private-dns zone list" ]; then printf '1\n'; return 0; fi
  if [ "$1 $2 $3 $4 $5" = "network private-dns link vnet list" ]; then printf '%s\n' '{spoke}'; return 0; fi
  return 0
}}
"""
    result = subprocess.run([bash, "--noprofile", "--norc", "-s"], input=prelude + source, text=True,
                            capture_output=True, timeout=60, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls[0] == f"account set --subscription {subscription}"
    zone_calls = [call for call in calls if "private-dns" in call]
    assert zone_calls and all(f"--resource-group {group}" in call and f"--subscription {subscription}" in call
                              for call in zone_calls)
    assert "zoneRedisManagedLinkExists=true" in (tmp_path / "github-env").read_text()


# ---------------------------------------------------------------- variable templates

def test_variable_templates_carry_both_keys_empty_by_default():
    document = json.loads(text(ROOT / "environment_setup" / "aifactory" / "variables.json"))
    assert document["dev"][VNET] == "" and document["dev"][DNS] == ""
    yaml = text(ADO / "variables" / "variables.yaml")
    assert re.search(r'^  own_hub_vnet_id: "" # <optional>', yaml, re.M)
    assert re.search(r'^  own_hub_private_dns_resource_group_id: "" # <optional>', yaml, re.M)
    env = text(GHA / ".env.template")
    assert re.search(r'^OWN_HUB_VNET_ID="" # <optional>', env, re.M)
    assert re.search(r'^OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID="" # <optional>', env, re.M)
    upload = text(GHA / "03a-GH-create-or-update-github-variables.sh")
    assert '"OWN_HUB_VNET_ID"' in upload and '"OWN_HUB_PRIVATE_DNS_RESOURCE_GROUP_ID"' in upload
