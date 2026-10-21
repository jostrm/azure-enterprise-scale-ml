"""aksOutboundType on the ESML project route compiles and reaches the AKS cluster unchanged (v1.24 backport).

esml-project/22-main.bicep -> modules/machineLearning.bicep -> modules/aksCluster.bicep. aksCluster.bicep owns
the AKS values; c7a9d8d8 dropped 'none' from its @allowed list while both callers still allowed it, so Bicep
rejected the module call (BCP036) and 22-main stopped compiling. 'none' is not mapped to null: the module
default loadBalancer would then apply, a public egress IP, the opposite of asking for no outbound path.
The route offers the values every config surface documents and the pink wizard offers (AKS_OUTBOUND):
variables.yaml and .env.template say loadBalancer, otherwise userDefinedRouting. Same contract as main af75afe9.
"""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[4]
ESML_PROJECT = ROOT / "environment_setup/aifactory/bicep/esml-project/22-main.bicep"
CLUSTER_TYPE = "Microsoft.ContainerService/managedClusters"
WIZARD_VALUES = ["loadBalancer", "userDefinedRouting"]


@lru_cache
def compiled_entrypoint():
    compiler = shutil.which("bicep")
    assert compiler, "Bicep CLI required"
    result = subprocess.run([compiler, "build", str(ESML_PROJECT), "--stdout", "--no-restore"],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def resources(template):
    items = template["resources"]
    return list(items.values()) if isinstance(items, dict) else items


def deployment(template, name_part):
    matches = [item for item in resources(template)
               if item["type"] == "Microsoft.Resources/deployments" and name_part in item["name"]]
    assert len(matches) == 1, f"expected one module deployment named like {name_part!r}, found {len(matches)}"
    return matches[0]


def machine_learning():
    return deployment(compiled_entrypoint(), "AML1classic")


def test_esml_project_entrypoint_compiles():
    assert machine_learning()


def test_route_allows_the_documented_values_only():
    for template in (compiled_entrypoint(), machine_learning()["properties"]["template"]):
        declared = template["parameters"]["aksOutboundType"]
        assert declared["allowedValues"] == WIZARD_VALUES
        assert declared["defaultValue"] == "loadBalancer"


@pytest.mark.parametrize("module", ["AMLAKSDev4", "AMLAKSTestProd4"])
def test_outbound_type_is_passed_through_to_the_cluster(module):
    aml = machine_learning()
    assert aml["properties"]["parameters"]["aksOutboundType"]["value"] == "[parameters('aksOutboundType')]"
    aks = deployment(aml["properties"]["template"], module)
    assert aks["properties"]["parameters"]["outboundType"]["value"] == "[parameters('aksOutboundType')]"
    aks_template = aks["properties"]["template"]
    assert set(WIZARD_VALUES) <= set(aks_template["parameters"]["outboundType"]["allowedValues"])
    cluster = next(item for item in resources(aks_template) if item["type"] == CLUSTER_TYPE)
    assert cluster["properties"]["networkProfile"]["outboundType"] == "[parameters('outboundType')]"
