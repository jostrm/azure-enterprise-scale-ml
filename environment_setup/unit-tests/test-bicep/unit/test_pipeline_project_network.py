"""Pipelines-only project subnets: the legacy allocator (subnetCalc_v2.ps1) decides the CIDRs.

Live 2026-11-17 (ADO pipelines-only, aif-163): the native planner had no project
network allocation, so 31-network stopped with genaiSubnetCidr unresolved. The
planner now feeds the same PowerShell allocator a VNet inventory (live through
ARM, or the planned common VNet when common deploys in the same plan) and maps
its output to template parameters. No Azure call happens inside PowerShell.
"""

import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
ALLOCATOR = ROOT / "environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1"
SUB = "f0fe8b33-73bf-41e4-9997-e3920d793c06"
VNET_RG = "aif63-esml-common-sdc-dev-001"
VNET = "vnt-esmlcmn-sdc-dev-001"
VNET_ID = f"/subscriptions/{SUB}/resourceGroups/{VNET_RG}/providers/Microsoft.Network/virtualNetworks/{VNET}"
COMMON_SUBNETS = {"snet-esml-cmn-001": "10.164.0.0/26", "snet-esml-cmn-001-scoring": "10.164.0.64/26",
                  "snet-esml-cmn-pbi-001": "10.164.0.128/26", "AzureBastionSubnet": "10.164.0.192/26"}

pwsh = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(not pwsh, reason="PowerShell runs the real allocator")


def values(**overrides):
    result = {"BYO_subnets": "false", "vnetNameBase": "vnt-esmlcmn", "vnetResourceGroupBase": "esml-common",
              "vnetResourceGroup_param": "", "vnetNameFull_param": "", "admin_locationSuffix": "sdc",
              "admin_location": "swedencentral", "admin_commonResourceSuffix": "-001",
              "admin_prjResourceSuffix": "-001", "admin_projectType": "all", "admin_aifactorySuffixRG": "-001",
              "admin_aifactoryPrefixRG": "aif63-", "enableLogicApps": "false", "logicAppType": "Standard",
              "byoASEv3": "false", "enablePublicAccessWithPerimeter": "false"}
    result.update(overrides)
    return result


TARGET = {"environment": "dev", "subscription_id": SUB, "tenant_id": "c157e61b-4a1e-488c-9a0c-d9a23e864a65"}
COMMON_STEP = {"common_vnet_cidr": "10.164.0.0/18", "cidr_range": "0",
               "common_subnet_name": "snet-esml-cmn-001", "common_subnet_cidr": "10.164.0.0/26",
               "common_subnet_scoring_cidr": "10.164.0.64/26",
               "common_pbi_subnet_name": "snet-esml-cmn-pbi-001", "common_pbi_subnet_cidr": "10.164.0.128/26",
               "common_bastion_subnet_name": "AzureBastionSubnet", "common_bastion_subnet_cidr": "10.164.0.192/26"}


class Cloud:
    def __init__(self, vnet=None):
        self.vnet, self.calls = vnet, []

    def command(self, argv, cwd=None, data=None):
        self.calls.append(argv[0])
        assert argv[0] == "pwsh", argv
        run = subprocess.run([pwsh, *argv[1:]], cwd=cwd, capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stdout + run.stderr
        return run.stdout

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        assert method == "GET" and resource_id == VNET_ID and 404 in allowed
        self.calls.append("arm")
        if self.vnet is None:
            return 404, {}, None
        return 200, {}, self.vnet


def arm_vnet(subnets):
    return {"id": VNET_ID, "name": VNET, "properties": {
        "addressSpace": {"addressPrefixes": ["10.164.0.0/18"]},
        "subnets": [{"id": VNET_ID + "/subnets/" + name, "name": name, "properties": {"addressPrefix": cidr}}
                    for name, cidr in subnets.items()]}}


def assert_allocated(result, reserved):
    cidrs = {key: ipaddress.ip_network(value) for key, value in result.items() if key.endswith("SubnetCidr")}
    assert set(cidrs) == {"genaiSubnetCidr", "aksSubnetCidr", "aks2SubnetCidr", "acaSubnetCidr", "aca2SubnetCidr",
                          "webappSubnetCidr", "dbxPubSubnetCidr", "dbxPrivSubnetCidr"}
    space = ipaddress.ip_network("10.164.0.0/18")
    taken = [ipaddress.ip_network(cidr) for cidr in reserved]
    assert all(net.subnet_of(space) for net in cidrs.values())
    assert not any(net.overlaps(other) for net in cidrs.values() for other in taken)
    nets = list(cidrs.values())
    assert not any(a.overlaps(b) for i, a in enumerate(nets) for b in nets[i + 1:])


@needs_pwsh
def test_allocator_inventory_mode_never_calls_azure_and_reports_the_vnet(tmp_path):
    inventory = tmp_path / "vnet.json"
    inventory.write_text(json.dumps({"id": VNET_ID, "addressSpace": {"addressPrefixes": ["10.164.0.0/18"]},
                                     "subnets": [{"name": n, "addressPrefix": c, "id": VNET_ID + "/subnets/" + n}
                                                 for n, c in COMMON_SUBNETS.items()]}), encoding="utf-8")
    code = r"""
$ErrorActionPreference = 'Stop'
function global:Install-Module { throw 'Module installation is forbidden in inventory mode' }
function global:az { throw 'Azure CLI is forbidden in inventory mode' }
function global:Get-AzContext { throw 'Az PowerShell is forbidden in inventory mode' }
& $env:ALLOC_SCRIPT -filePath $env:ALLOC_OUT -env dev -subscriptionId $env:ALLOC_SUB -prjResourceSuffix '-001' `
  -projectNumber '001' -aifactorySuffixRGADO '-001' -commonResourceSuffixADO '-001' -locationADO swedencentral `
  -locationSuffixADO sdc -projectTypeADO all -commonRGNamePrefixVar 'aif63-' -vnetNameBase vnt-esmlcmn `
  -vnetResourceGroupBase esml-common -vnetInventoryFile $env:ALLOC_INVENTORY -planFile $env:ALLOC_PLAN
"""
    run = subprocess.run([pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
                         capture_output=True, text=True, timeout=60,
                         env={**__import__("os").environ, "GITHUB_ACTIONS": "false", "AIFACTORY_USE_AZURE_CLI": "false",
                              "ALLOC_SCRIPT": str(ALLOCATOR), "ALLOC_OUT": str(tmp_path), "ALLOC_SUB": SUB,
                              "ALLOC_INVENTORY": str(inventory), "ALLOC_PLAN": str(tmp_path / "plan.json")})
    assert run.returncode == 0, run.stdout + run.stderr
    legacy = json.loads((tmp_path / "subnetParameters.json").read_text(encoding="utf-8-sig"))
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8-sig"))
    assert plan["vnetName"] == VNET and plan["vnetResourceGroup"] == VNET_RG
    assert {key: item["value"] for key, item in legacy["parameters"].items() if key.endswith("SubnetCidr")} \
        == plan["subnets"]
    assert_allocated(plan["subnets"], COMMON_SUBNETS.values())


@needs_pwsh
def test_planner_allocates_inside_the_planned_common_vnet_when_common_deploys_in_the_same_plan():
    import pipeline_project_network as network
    cloud = Cloud(vnet=None)
    result = network.allocate(cloud, ROOT, values(), TARGET, "001", planned_common=COMMON_STEP)
    assert cloud.calls == ["arm", "pwsh"]
    assert_allocated(result, COMMON_SUBNETS.values())
    assert result["vnetResourceGroup"] == VNET_RG
    assert result["genaiSubnetId"] == VNET_ID + "/subnets/snt-prj001-genai"
    assert result["aksSubnetId"] == VNET_ID + "/subnets/snt-prj001-aks"
    assert result["acaSubnetId"] == VNET_ID + "/subnets/snt-prj001-aca"
    assert result["aca2SubnetId"] == VNET_ID + "/subnets/snt-prj001-aca-002"
    assert not any(key.endswith("Exists") and value for key, value in result.items())


@needs_pwsh
def test_planner_preserves_an_existing_project_subnet_from_the_live_vnet():
    import pipeline_project_network as network
    live = dict(COMMON_SUBNETS, **{"snt-prj002-genai": "10.164.8.0/25"})
    cloud = Cloud(vnet=arm_vnet(live))
    result = network.allocate(cloud, ROOT, values(), TARGET, "002")
    assert result["genaiSubnetCidr"] == "10.164.8.0/25" and result["sntGenaiExists"] is True
    assert result["genaiSubnetId"] == VNET_ID + "/subnets/snt-prj002-genai"
    assert_allocated({k: v for k, v in result.items() if k != "genaiSubnetCidr"} | {"genaiSubnetCidr": "10.164.8.0/25"},
                     COMMON_SUBNETS.values())


def test_missing_vnet_without_common_in_the_plan_is_refused():
    import pipeline_project_network as network
    with pytest.raises(Exception) as raised:
        network.allocate(Cloud(vnet=None), ROOT, values(), TARGET, "002")
    assert "project-network-vnet-not-found" in str(raised.value.args)


def test_only_managed_networks_with_missing_subnet_parameters_need_allocation():
    import pipeline_project_network as network
    template = {"parameters": {"genaiSubnetCidr": {"type": "string"}, "aksSubnetCidr": {"type": "string"}}}
    assert network.required(template, values())
    assert not network.required(template, values(BYO_subnets="true"))
    assert not network.required(template, values(genaiSubnetCidr="10.1.0.0/25", aksSubnetCidr="10.1.1.0/26"))
    assert not network.required({"parameters": {"location": {"type": "string"}}}, values())



def test_planner_feeds_project_steps_the_allocated_network_and_the_planned_common_vnet(monkeypatch):
    import factory_lifecycle as fl
    import pipeline_lifecycle_adapters as adapters
    import pipeline_project_network as network
    common_template = {"parameters": {"common_vnet_cidr": {"type": "string"}, "cidr_range": {"type": "string"}},
                       "$schema": "deploymentTemplate.json"}
    project_template = {"parameters": {"genaiSubnetCidr": {"type": "string"}, "genaiSubnetId": {"type": "string"}},
                        "$schema": "deploymentTemplate.json"}
    asked = []

    class Planned:
        def compile_template(self, root, path):
            return common_template if "/esml-common/" in path else project_template

    def allocate(cloud, root, values, target, number, *, planned_common=None):
        asked.append((number, planned_common))
        return {"genaiSubnetCidr": "10.164.4.0/25", "genaiSubnetId": "/subnets/snt-prj001-genai",
                "vnetResourceGroup": VNET_RG}

    monkeypatch.setattr(network, "allocate", allocate)
    monkeypatch.setattr(fl, "freeze_deployment_plan", lambda cloud, document, root: document["deployment"])
    monkeypatch.setattr(fl, "COMMON_TEMPLATES", {"12-networkCommon": "environment_setup/aifactory/bicep/esml-common/main/12-networkCommon.bicep"})
    monkeypatch.setattr(fl, "PROJECT_TEMPLATES", {"environment_setup/aifactory/bicep/esml-genai-1/01-foundation.bicep"})
    project = {"id": "p1", "number": "001"}
    snapshot = {"configuration": {"factory": {}, "scale_sets": {}},
                "variables": {"p1": {"dev": values(common_vnet_cidr="10.164.0.0/18", cidr_range="0"), "stage_prod": {}}}}
    scope = f"/subscriptions/{SUB}/resourceGroups/{VNET_RG}"
    document = {"operation": "create-factory", "run_id": "r" * 32, "prepared_at": "2026-11-18T00:00:00+00:00",
                "target": dict(TARGET, region="swedencentral", prefix="aif63-", suffix="001",
                               factory_id="f", scaleset_id="s"),
                "locks": {"scopes": [scope]}}
    planner = adapters.NativePlanner(ROOT, ROOT, review=None)
    plan = planner.deployment(snapshot, {"id": "s", "environment": "dev", "subscription_id": SUB},
                              [project], document, Planned())
    project_step = [step for step in plan["steps"] if step["kind"] == "project"][0]
    assert project_step["parameters"]["genaiSubnetCidr"] == "10.164.4.0/25"
    assert project_step["parameters"]["genaiSubnetId"] == "/subnets/snt-prj001-genai"
    assert asked == [("001", plan["steps"][0]["parameters"])]
