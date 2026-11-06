"""Offline regression for project-MI blob access on the secondary storage account."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"


def block(text, kind, symbol):
    match = re.search(
        rf"(?m)^{kind} {symbol}\b.*?(?=^(?:module|resource|var|param|output)\s|\Z)",
        text, re.S,
    )
    if match is None:
        raise AssertionError(f"Missing {kind} {symbol}")
    return match.group()


class SecondaryStorageMiRbacTests(unittest.TestCase):
    def setUp(self):
        self.module = (BICEP / "modules/storageRbacUsers.bicep").read_text(encoding="utf-8")
        self.phase = (BICEP / "esml-genai-1/08-rbac-security.bicep").read_text(encoding="utf-8")

    def test_additional_secondary_blob_principals_are_opt_in_and_deduplicated(self):
        self.assertIn("param additionalSecondaryBlobPrincipalIds array = []", self.module)
        self.assertIn(
            "var secondaryBlobPrincipals = union(servicePrincipleAndMIArray, additionalSecondaryBlobPrincipalIds)",
            self.module,
        )

    def test_primary_and_secondary_non_blob_grants_keep_original_principal_array(self):
        for symbol in (
            "userStorageBlobDataContributorRoleSP",
            "roleAssignmentStorageUserFileDataPrivilegedContributorSP",
            "userStorageQueueDataContributorRoleSP",
            "roleAssignmentStorageUserFileDataPrivilegedContributor2SP",
            "userStorageQueueDataContributorRole2SP",
        ):
            with self.subTest(symbol=symbol):
                resource = block(self.module, "resource", symbol)
                self.assertIn("principalId: servicePrincipleAndMIArray[i]", resource)
                self.assertNotIn("secondaryBlobPrincipals", resource)

    def test_secondary_blob_grant_preserves_scope_role_guid_order_and_optional_account(self):
        resource = block(self.module, "resource", "userStorageBlobDataContributorRole2SP")
        for expression in (
            "length(secondaryBlobPrincipals)",
            "if(!empty(storageAccountName2))",
            "name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, secondaryBlobPrincipals[i])",
            "principalId: secondaryBlobPrincipals[i]",
            "principalType: 'ServicePrincipal'",
            "scope: existingStorageAccount2",
        ):
            self.assertIn(expression, resource)

    def test_rbac_phase_supplies_only_project_mi_without_regranting_primary_service_roles(self):
        module = block(self.phase, "module", "rbacStorageUsers")
        self.assertIn("servicePrincipleAndMIArray: spAndMiUnique", module)
        self.assertRegex(
            module,
            r"additionalSecondaryBlobPrincipalIds:\s*\[\s*getProjectMIPrincipalId\.outputs\.principalId\s*\]",
        )
        self.assertIn("storageAccountName2: storageAccount2001Name", module)
        self.assertIn("if (!updateRbac && !skipExistingRoleAssignments)", module.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
