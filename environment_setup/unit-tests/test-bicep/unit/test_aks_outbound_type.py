"""aksOutboundType on the ESML project route compiles and reaches the AKS cluster unchanged.

esml-project/22-main.bicep -> modules/machineLearning.bicep -> modules/aksCluster.bicep. aksCluster.bicep owns
the AKS values; c7a9d8d8 dropped 'none' from its @allowed list while both callers still allowed it, so Bicep
rejected the module call (BCP036) and 22-main stopped compiling. 'none' is not mapped to null: the module
default loadBalancer would then apply, a public egress IP, the opposite of asking for no outbound path.
The route offers the values every config surface documents and the pink wizard
offers (AKS_OUTBOUND): variables.json, variables.yaml and .env.template say loadBalancer, otherwise
userDefinedRouting.
"""
from pathlib import Path

import pytest

from base.arm_expressions import arm_value, compile_bicep, parameters_with_defaults, resources


ROOT = Path(__file__).resolve().parents[4]
ESML_PROJECT = ROOT / "environment_setup/aifactory/bicep/esml-project/22-main.bicep"
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
