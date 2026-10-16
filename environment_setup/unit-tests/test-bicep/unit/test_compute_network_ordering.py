"""Compiled ARM ordering for shared-VNet mutations; no Azure operations."""

import ast
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[4]
ENTRY = ROOT / "environment_setup/aifactory/bicep/esml-genai-1/05-compute-services.bicep"


@pytest.fixture(scope="module")
def compute():
    compiler = shutil.which("bicep")
    if not compiler:
        pytest.skip("Installed Bicep CLI required for offline compiled dependency checks")
    result = subprocess.run([compiler, "build", str(ENTRY), "--stdout", "--no-restore"],
                            capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stderr
    template = json.loads(result.stdout)
    prefixes = {
        "serverfarm": "05-snetDelegSF1",
        "aca-delegation": "05-snetDelegACA",
        "webapp": "05-WebApp4",
        "function": "05-Function4",
        "aca": "05-container-apps-",
    }
    modules = {
        key: next(resource for resource in template["resources"] if prefix in resource.get("name", ""))
        for key, prefix in prefixes.items()
    }
    return template, modules


def condition(expression, parameters):
    if not isinstance(expression, str):
        return expression
    source = re.sub(r"\b(and|or|not|if)\(", lambda match: match[1].upper() + "(", expression[1:-1])
    functions = {"parameters": parameters.__getitem__, "AND": lambda *items: all(items),
                 "OR": lambda *items: any(items), "NOT": lambda value: not value,
                 "IF": lambda test, yes, no: yes if test else no, "empty": lambda value: not value}

    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords
        assert node.func.id in functions, ast.dump(node)
        return functions[node.func.id](*(visit(argument) for argument in node.args))

    return visit(ast.parse(source, mode="eval").body)


def dependency_graph(modules):
    return {
        key: {other for other, resource in modules.items()
              if any(resource["name"][1:-1] in item for item in module.get("dependsOn", []))}
        for key, module in modules.items()
    }


def ancestors(graph, node, active, visiting=()):
    assert node not in visiting, f"Cyclic network dependencies: {visiting + (node,)}"
    direct = graph[node] & active
    return direct | {ancestor for dependency in direct
                     for ancestor in ancestors(graph, dependency, active, visiting + (node,))}


def test_compiled_consumers_wait_for_both_delegations_and_each_other(compute):
    _, modules = compute
    graph = dependency_graph(modules)
    assert {"serverfarm", "aca-delegation"} <= graph["webapp"]
    assert {"serverfarm", "aca-delegation", "webapp"} <= graph["function"]
    assert {"aca-delegation", "webapp", "function"} <= graph["aca"]
    for key in graph:
        ancestors(graph, key, set(graph))


@pytest.mark.parametrize("dedicated,byo_ase,foundry_existing", list(itertools.product((False, True), repeat=3)))
def test_compiled_order_preserves_disabled_existing_and_optional_service_paths(
        compute, dedicated, byo_ase, foundry_existing):
    template, modules = compute
    defaults = {key: value["defaultValue"] for key, value in template["parameters"].items()
                if "defaultValue" in value}
    graph = dependency_graph(modules)
    order = list(modules)
    for web, function, aca in itertools.product(("disabled", "existing", "new"), repeat=3):
        parameters = defaults | {
            "enableWebApp": web != "disabled", "webAppExists": web == "existing",
            "enableFunction": function != "disabled", "functionAppExists": function == "existing",
            "enableContainerApps": aca != "disabled", "containerAppsEnvExists": aca == "existing",
            "webappSubnetId": "dedicated-web-subnet" if dedicated else "",
            "aksSubnetId": "legacy-aks-subnet", "acaSubnetId": "aca-subnet", "aca2SubnetId": "",
            "enableAKS": False, "byoASEv3": byo_ase, "aiFoundryV2Exists": foundry_existing,
            "disableAgentNetworkInjection": False,
        }
        active = {key for key, module in modules.items()
                  if condition(module.get("condition", True), parameters)}
        assert ("webapp" in active) == (web == "new")
        assert ("function" in active) == (function == "new")
        assert ("aca" in active) == (aca != "disabled")
        assert ("serverfarm" in active) == (
            web != "existing" and function != "existing"
            and (web != "disabled" or function != "disabled") and not dedicated and not byo_ase)
        for index, key in enumerate(order):
            if key in active:
                expected = set(order[:index]) & active
                assert expected <= ancestors(graph, key, active), (web, function, aca, key, expected)


def test_incident_path_function_only_waits_for_aca_subnet_update(compute):
    _, modules = compute
    graph = dependency_graph(modules)
    # Dedicated web subnet skips ServerFarm delegation; Web App is disabled.
    active = {"aca-delegation", "function", "aca"}
    assert "aca-delegation" in ancestors(graph, "function", active)
    assert {"aca-delegation", "function"} <= ancestors(graph, "aca", active)
    web = modules["webapp"]["properties"]["parameters"]
    function = modules["function"]["properties"]["parameters"]
    assert web["subnetIntegrationName"] == function["subnetIntegrationName"]
    for key in ("vnetName", "vnetResourceGroupName", "location", "enablePublicAccessWithPerimeter", "byoASEv3"):
        assert web[key] == function[key]
