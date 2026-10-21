"""aksOutboundType on the ESML project route compiles and reaches the AKS cluster unchanged.

esml-project/22-main.bicep -> modules/machineLearning.bicep -> modules/aksCluster.bicep. aksCluster.bicep owns
the AKS values; c7a9d8d8 dropped 'none' from its @allowed list while both callers still allowed it, so Bicep
rejected the module call (BCP036) and 22-main stopped compiling. 'none' is not mapped to null: the module
default loadBalancer would then apply, a public egress IP, the opposite of asking for no outbound path.
The route offers the values every config surface documents and the pink wizard
offers (AKS_OUTBOUND): variables.json, variables.yaml and .env.template say loadBalancer, otherwise
userDefinedRouting.

The GenAI route still declares aksCluster's four values, and its 31-network gate (loadBalancer and
userDefinedRouting only) is skipped when BYO_subnets is true or runNetworkingVar is false. So preflight
judges the value itself: managedNATGateway needs an AKS-managed VNet and AI Factory always brings the
subnet; userAssignedNATGateway needs a NAT gateway on a BYO AKS subnet, which preflight cannot see.
userDefinedRouting needs a route table on the cluster subnet, but 31-network attaches its UDR route table
only to snt-<project>-aks-002 (the AML AKS in 07), while the GenAI cluster in 05 (enableAKS) lands on
snt-<project>-aks. So without BYO subnets, GenAI AKS with userDefinedRouting fails in preflight.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from base.arm_expressions import arm_value, compile_bicep, parameters_with_defaults, resources


ROOT = Path(__file__).resolve().parents[4]
ESML_PROJECT = ROOT / "environment_setup/aifactory/bicep/esml-project/22-main.bicep"
PREFLIGHT = ROOT / "environment_setup/aifactory/bicep/scripts/preflight.sh"
CLUSTER_TYPE = "Microsoft.ContainerService/managedClusters"
WIZARD_VALUES = ["loadBalancer", "userDefinedRouting"]
AKS_MODULE = {"dev": "AMLAKSDev4", "test": "AMLAKSTestProd4", "prod": "AMLAKSTestProd4"}


def deployment(template, name_part):
    matches = [item for item in resources(template)
               if item["type"] == "Microsoft.Resources/deployments" and name_part in item["name"]]
    assert len(matches) == 1, f"expected one module deployment named like {name_part!r}, found {len(matches)}"
    return matches[0]


def passed(module, key, parameters, template):
    return arm_value(module["properties"]["parameters"][key]["value"], parameters, template)


@pytest.fixture(scope="module")
def entrypoint():
    return compile_bicep(ESML_PROJECT)


@pytest.fixture(scope="module")
def machine_learning(entrypoint):
    return deployment(entrypoint, "AML1classic")["properties"]["template"]


@pytest.fixture(scope="module")
def aks_cluster(machine_learning):
    return deployment(machine_learning, AKS_MODULE["dev"])["properties"]["template"]


def test_esml_project_entrypoint_compiles(entrypoint):
    assert deployment(entrypoint, "AML1classic")


def test_route_allows_the_documented_values_only(entrypoint, machine_learning):
    for template in (entrypoint, machine_learning):
        declared = template["parameters"]["aksOutboundType"]
        assert declared["allowedValues"] == WIZARD_VALUES
        assert declared["defaultValue"] == "loadBalancer"


def test_route_values_are_values_the_aks_module_accepts(entrypoint, machine_learning, aks_cluster):
    accepted = set(aks_cluster["parameters"]["outboundType"]["allowedValues"])
    for template in (entrypoint, machine_learning):
        assert set(template["parameters"]["aksOutboundType"]["allowedValues"]) <= accepted


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
@pytest.mark.parametrize("outbound", WIZARD_VALUES)
def test_outbound_type_reaches_the_cluster(entrypoint, outbound, env):
    aml = deployment(entrypoint, "AML1classic")
    ml_value = passed(aml, "aksOutboundType", {"aksOutboundType": outbound}, entrypoint)
    ml_template = aml["properties"]["template"]
    aks = deployment(ml_template, AKS_MODULE[env])
    assert arm_value(aks["condition"], {"env": env}, ml_template)
    cluster_value = passed(aks, "outboundType", {"aksOutboundType": ml_value}, ml_template)
    aks_template = aks["properties"]["template"]
    cluster = next(item for item in resources(aks_template) if item["type"] == CLUSTER_TYPE)
    parameters = parameters_with_defaults(aks_template, {"outboundType": cluster_value})
    network = cluster["properties"]["networkProfile"]

    assert arm_value(network["outboundType"], parameters, aks_template) == outbound
    load_balancer = arm_value(network["loadBalancerProfile"], parameters, aks_template)
    assert (load_balancer is not None) == (outbound == "loadBalancer")


def preflight_findings(outbound, byo_subnets, enable_aks="true", enable_aks_aml="false"):
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    assert bash.is_file(), "Bash runs the isolated preflight AKS check"
    source = PREFLIGHT.read_text(encoding="utf-8")

    def function(name):
        return name + "() {" + source.split("\n" + name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"

    one_liners = [line for line in source.splitlines() if line.startswith(("is_true() {", "lc() {"))]
    script = "\n".join([
        "set -u", *one_liners, function("is_unset_placeholder"), function("check_aks_networking"),
        "add_finding() { printf 'FINDING:%s:%s\n' \"$1\" \"$2\"; }",
        f"ENABLE_AKS={enable_aks}; ENABLE_AKS_AML={enable_aks_aml}; AKS_FW_IP=10.0.0.4; AKS_PRIVATE_DNS=none",
        f"AKS_OUTBOUND_TYPE={outbound}; BYO_SUBNETS={byo_subnets}",
        "check_aks_networking",
    ])
    result = subprocess.run([str(bash), "--noprofile", "--norc", "-c", script],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return [line.split(":", 1)[1] for line in result.stdout.splitlines() if line.startswith("FINDING:")]


@pytest.mark.parametrize("byo_subnets", ["false", "true"])
@pytest.mark.parametrize("outbound,expected", [
    ("loadBalancer", []),
    ("managedNATGateway", ["FAIL:AKS_OUTBOUND_UNSUPPORTED"]),
    ("none", ["FAIL:AKS_OUTBOUND_UNSUPPORTED"]),
])
def test_preflight_rejects_outbound_types_no_route_can_deploy(outbound, expected, byo_subnets):
    assert preflight_findings(outbound, byo_subnets) == expected


@pytest.mark.parametrize("byo_subnets,expected", [
    ("false", ["FAIL:AKS_OUTBOUND_NAT_NEEDS_BYO"]),
    ("true", ["WARN:AKS_OUTBOUND_NAT_UNVERIFIED"]),
])
def test_preflight_allows_a_user_assigned_nat_gateway_only_on_byo_subnets(byo_subnets, expected):
    assert preflight_findings("userAssignedNATGateway", byo_subnets) == expected


@pytest.mark.parametrize("enable_aks,enable_aks_aml,byo_subnets,expected", [
    ("true", "false", "false", ["FAIL:AKS_UDR_GENAI_SUBNET_NO_ROUTE"]),
    ("true", "true", "false", ["FAIL:AKS_UDR_GENAI_SUBNET_NO_ROUTE"]),
    ("true", "false", "true", []),
    ("false", "true", "false", []),
])
def test_preflight_fails_genai_udr_on_the_ai_factory_aks_subnet(enable_aks, enable_aks_aml, byo_subnets, expected):
    assert preflight_findings("userDefinedRouting", byo_subnets, enable_aks, enable_aks_aml) == expected
