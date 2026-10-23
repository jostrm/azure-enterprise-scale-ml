"""Offline regressions for the Key Vault principal rule: principalId gets the grant, placeholders are skipped.

The former access-policy module kvCmnAccessPolicys.bicep is now modules/kvRbacPrincipals.bicep, which grants each
principal a Key Vault role instead of an access policy. The principal rule is unchanged.
"""

from pathlib import Path
import re

import pytest

from base.arm_expressions import compile_bicep, copy_loop, resources


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
MODULE = BICEP / "modules/kvRbacPrincipals.bicep"

DATABRICKS = "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6"
ADMIN = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
PLACEHOLDERS = ["", "<todo>", "<optional>_ObjectID", "<todo>_ObjectID", "null", "not-a-guid",
                "24ad86361b2c4d5e8f90a1b2c3d4e5f6", "24ad8636-1b2c-4d5e-8f90-a1b2c3d4-e5f6",
                "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6-"]
ARM = {"resourceId": lambda *parts: "/vault", "subscriptionResourceId": lambda kind, name: f"{kind}/{name}"}


def compiled_module():
    return compile_bicep(MODULE)


def granted(principal_id, additional_ids):
    """Evaluate the compiled role-assignment copy loop the way ARM expands it: the principals that get the role."""
    template = compiled_module()
    parameters = {"keyVaultResourceName": "kv-cmn", "principalId": principal_id, "keyVaultRole": "secretsUser",
                  "additionalPrincipalIds": additional_ids, "principalType": ""}
    loop = next(item for item in resources(template) if item["type"] == "Microsoft.Authorization/roleAssignments")
    return [item["principalId"] for item in copy_loop(loop, parameters, template, ("principalId",), ARM)]


def test_principal_id_alone_gets_the_role():
    # 13-rgLevel's Databricks grant passes only principalId; the access-policy module once produced an empty policy.
    assert granted(DATABRICKS, []) == [DATABRICKS]


def test_principal_id_and_additional_ids_are_merged_without_duplicates():
    assert granted(DATABRICKS, [ADMIN, DATABRICKS]) == [DATABRICKS, ADMIN]
    assert granted(DATABRICKS.upper(), [DATABRICKS]) == [DATABRICKS]


def test_padded_ids_are_trimmed_instead_of_dropped():
    # technical_admins "a, b" splits to ' b'; a seeding Key Vault secret can end with a newline.
    assert granted(f"{DATABRICKS}\n", [f" {ADMIN}"]) == [DATABRICKS, ADMIN]


def test_no_policy_name_so_nothing_can_replace_other_grants():
    # The access-policy 'replace' operation could wipe every policy on the vault; role assignments only add.
    assert "policyName" not in compiled_module()["parameters"]


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_placeholder_or_non_guid_principal_id_is_skipped(placeholder):
    # ADO/JSON default databricksOID '<optional>_ObjectID' and GHA .env '<todo>' must not break common deployments.
    assert granted(placeholder, []) == []
    assert granted(placeholder, [ADMIN]) == [ADMIN]


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_placeholder_or_non_guid_additional_id_is_skipped(placeholder):
    assert granted(DATABRICKS, [placeholder, ADMIN]) == [DATABRICKS, ADMIN]


def module_calls():
    calls = []
    for path in sorted(BICEP.rglob("*.bicep")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^module \w+ '[^']*/kvRbacPrincipals\.bicep'", source, re.MULTILINE):
            params = source.index("params:", match.end())
            calls.append((path.relative_to(BICEP).as_posix(), source[params:source.index("\n  }", params)]))
    return calls


def test_every_caller_passes_both_principal_parameters_and_a_role():
    calls = module_calls()
    assert {path for path, _ in calls} >= {"esml-common/main/13-rgLevel.bicep",
                                          "esml-genai-1/02-core-infrastructure.bicep"}
    for path, params in calls:
        assert re.search(r"^\s+principalId:", params, re.MULTILINE), path
        assert re.search(r"^\s+additionalPrincipalIds\s*:", params, re.MULTILINE), path
        assert re.search(r"^\s+keyVaultRole:\s*'\w+'", params, re.MULTILINE), path
