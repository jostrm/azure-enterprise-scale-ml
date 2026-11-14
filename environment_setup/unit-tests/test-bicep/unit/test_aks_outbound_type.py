"""aksOutboundType reaches the AKS cluster unchanged, and preflight rejects what no route can deploy.

modules/aksCluster.bicep owns the AKS values; c7a9d8d8 dropped 'none' from its @allowed list while its
callers still allowed it, so Bicep rejected the module call (BCP036). 'none' is not mapped to null: the
module default loadBalancer would then apply, a public egress IP, the opposite of asking for no outbound
path. The cluster accepts the values every config surface documents and the pink wizard
offers (AKS_OUTBOUND): variables.json, variables.yaml and .env.template say loadBalancer, otherwise
userDefinedRouting. The ESML v1 project route that also called this module is not part of release/v1.26
(it stays on main), so the module is checked on its own.

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
AKS_CLUSTER = ROOT / "environment_setup/aifactory/bicep/modules/aksCluster.bicep"
PREFLIGHT = ROOT / "environment_setup/aifactory/bicep/scripts/preflight.sh"
CLUSTER_TYPE = "Microsoft.ContainerService/managedClusters"
WIZARD_VALUES = ["loadBalancer", "userDefinedRouting"]


@pytest.fixture(scope="module")
def aks_cluster():
    return compile_bicep(AKS_CLUSTER)


def test_documented_values_are_values_the_aks_module_accepts(aks_cluster):
    assert set(WIZARD_VALUES) <= set(aks_cluster["parameters"]["outboundType"]["allowedValues"])


@pytest.mark.parametrize("outbound", WIZARD_VALUES)
def test_outbound_type_reaches_the_cluster(aks_cluster, outbound):
    cluster = next(item for item in resources(aks_cluster) if item["type"] == CLUSTER_TYPE)
    parameters = parameters_with_defaults(aks_cluster, {"outboundType": outbound})
    network = cluster["properties"]["networkProfile"]

    assert arm_value(network["outboundType"], parameters, aks_cluster) == outbound
    load_balancer = arm_value(network["loadBalancerProfile"], parameters, aks_cluster)
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
