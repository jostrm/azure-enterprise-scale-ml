"""Offline regressions for modules/kvCmnAccessPolicys.bicep: principalId gets the policy, placeholders are skipped."""

from pathlib import Path
import re

import pytest

from base.arm_expressions import arm_value, compile_bicep, resources


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
MODULE = BICEP / "modules/kvCmnAccessPolicys.bicep"

DATABRICKS = "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6"
ADMIN = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
PLACEHOLDERS = ["", "<todo>", "<optional>_ObjectID", "<todo>_ObjectID", "null", "not-a-guid",
                "24ad86361b2c4d5e8f90a1b2c3d4e5f6", "24ad8636-1b2c-4d5e-8f90a1b2c3d4-e5f6",
                "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6-"]


def compiled_module():
    return compile_bicep(MODULE)


def access_policies(principal_id, additional_ids):
    """Evaluate the compiled accessPolicies copy loop the way ARM expands it."""
    template = compiled_module()
    parameters = {"keyVaultResourceName": "kv-cmn", "principalId": principal_id, "policyName": "add",
                  "keyVaultPermissions": {"secrets": ["get", "list"]}, "additionalPrincipalIds": additional_ids}
    policy = next(item for item in resources(template) if item["type"] == "Microsoft.KeyVault/vaults/accessPolicies")
    loop = next(item for item in policy["properties"]["copy"] if item["name"] == "accessPolicies")
    count = arm_value(loop["count"], parameters, template)
    return [arm_value(loop["input"]["objectId"], parameters, template, {"copyIndex": lambda *_, index=index: index})
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
