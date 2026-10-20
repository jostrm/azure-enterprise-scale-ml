"""Offline regressions for modules/kvCmnAccessPolicys.bicep: principalId gets the policy, placeholders are skipped."""

import ast
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
MODULE = BICEP / "modules/kvCmnAccessPolicys.bicep"

DATABRICKS = "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6"
ADMIN = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
PLACEHOLDERS = ["", "<todo>", "<optional>_ObjectID", "<todo>_ObjectID", "null", "not-a-guid",
                "24ad86361b2c4d5e8f90a1b2c3d4e5f6", "24ad8636-1b2c-4d5e-8f90a1b2c3d4-e5f6",
                "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6-"]


@lru_cache
def compiled_module():
    compiler = shutil.which("bicep")
    assert compiler, "Bicep CLI required"
    result = subprocess.run([compiler, "build", str(MODULE), "--stdout", "--no-restore"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def arm_value(expression, parameters, template, scope=None):
    if not isinstance(expression, str) or not expression.startswith("["):
        return expression
    source = re.sub(r"\b(and|or|not|if|lambda)\(", lambda match: match[1].upper() + "(", expression[1:-1])
    return visit(ast.parse(source, mode="eval").body, parameters, template, scope or {})


def visit(node, parameters, template, scope):
    def value(child):
        return visit(child, parameters, template, scope)

    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Subscript):
        return value(node.value)[value(node.slice)]
    assert isinstance(node, ast.Call) and not node.keywords, ast.dump(node)
    if isinstance(node.func, ast.Attribute):
        member = next(group for group in template["functions"]
                      if group["namespace"] == node.func.value.id)["members"][node.func.attr]
        args = {key["name"]: value(arg) for key, arg in zip(member["parameters"], node.args)}
        return arm_value(member["output"]["value"], args, template)
    name = node.func.id
    if name == "LAMBDA":
        names = [value(arg) for arg in node.args[:-1]]
        return lambda *items: visit(node.args[-1], parameters, template, {**scope, **dict(zip(names, items))})
    if name == "IF":
        return value(node.args[1] if value(node.args[0]) else node.args[2])
    values = [value(arg) for arg in node.args]
    functions = {
        "parameters": parameters.__getitem__,
        "variables": lambda key: arm_value(template["variables"][key], parameters, template),
        "lambdaVariables": scope.__getitem__,
        "AND": lambda *args: all(args), "OR": lambda *args: any(args), "NOT": lambda item: not item,
        "empty": lambda item: not item, "equals": lambda a, b: a == b,
        "length": len, "toLower": str.lower, "trim": str.strip, "contains": lambda container, item: item in container,
        "map": lambda items, mapper: [mapper(item) for item in items],
        "replace": str.replace, "split": lambda text, separator: text.split(separator),
        "take": lambda item, count: item[:max(count, 0)], "skip": lambda item, count: item[max(count, 0):],
        "array": lambda item: item if isinstance(item, list) else [item],
        "createArray": lambda *items: list(items),
        "union": lambda *arrays: list(dict.fromkeys(item for array in arrays for item in array)),
        "filter": lambda items, predicate: [item for item in items if predicate(item)],
        "range": lambda start, count: list(range(start, start + count)),
        "substring": lambda text, start, length: text[start:start + length],
    }
    return functions[name](*values)


def access_policies(principal_id, additional_ids):
    """Evaluate the compiled accessPolicies copy loop the way ARM expands it."""
    template = compiled_module()
    parameters = {"keyVaultResourceName": "kv-cmn", "principalId": principal_id, "policyName": "add",
                  "keyVaultPermissions": {"secrets": ["get", "list"]}, "additionalPrincipalIds": additional_ids}
    resources = template["resources"].values() if isinstance(template["resources"], dict) else template["resources"]
    policy = next(item for item in resources if item["type"] == "Microsoft.KeyVault/vaults/accessPolicies")
    loop = next(item for item in policy["properties"]["copy"] if item["name"] == "accessPolicies")
    count = arm_value(loop["count"], parameters, template)
    object_id = loop["input"]["objectId"]
    return [arm_value(object_id.replace("copyIndex('accessPolicies')", str(index)), parameters, template)
            for index in range(count)]


def test_principal_id_alone_gets_the_access_policy():
    # 13-rgLevel spDatabricksAccessPolicyGet passes only principalId; it used to produce an empty policy.
    assert access_policies(DATABRICKS, []) == [DATABRICKS]


def test_principal_id_and_additional_ids_are_merged_without_duplicates():
    assert access_policies(DATABRICKS, [ADMIN, DATABRICKS]) == [DATABRICKS, ADMIN]
    assert access_policies(DATABRICKS.upper(), [DATABRICKS]) == [DATABRICKS]


def test_padded_ids_are_trimmed_instead_of_dropped():
    # technical_admins "a, b" splits to ' b'; a seeding Key Vault secret can end with a newline.
    assert access_policies(f"{DATABRICKS}\n", [f" {ADMIN}"]) == [DATABRICKS, ADMIN]


def test_replace_policy_is_not_allowed():
    # Placeholders filter to an empty list, which 'replace' would turn into wiping every policy on the vault.
    assert "replace" not in compiled_module()["parameters"]["policyName"]["allowedValues"]


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_placeholder_or_non_guid_principal_id_is_skipped(placeholder):
    # ADO/JSON default databricksOID '<optional>_ObjectID' and GHA .env '<todo>' must not break common deployments.
    assert access_policies(placeholder, []) == []
    assert access_policies(placeholder, [ADMIN]) == [ADMIN]


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_placeholder_or_non_guid_additional_id_is_skipped(placeholder):
    assert access_policies(DATABRICKS, [placeholder, ADMIN]) == [DATABRICKS, ADMIN]


def module_calls():
    calls = []
    for path in sorted(BICEP.rglob("*.bicep")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^module \w+ '[^']*/kvCmnAccessPolicys\.bicep'", source, re.MULTILINE):
            params = source.index("params:", match.end())
            calls.append((path.relative_to(BICEP).as_posix(), source[params:source.index("\n  }", params)]))
    return calls


def test_every_caller_passes_both_principal_parameters_and_only_adds():
    calls = module_calls()
    assert {path for path, _ in calls} >= {"esml-common/main/13-rgLevel.bicep",
                                          "esml-genai-1/02-core-infrastructure.bicep"}
    for path, params in calls:
        assert re.search(r"^\s+principalId:", params, re.MULTILINE), path
        assert re.search(r"^\s+additionalPrincipalIds\s*:", params, re.MULTILINE), path
        assert re.search(r"^\s+policyName:\s*'add'", params, re.MULTILINE), path
