"""Unit tests for security/governance posture using mocked CLI + scenarios."""
from __future__ import annotations

import unittest
from unittest import mock
import json
from pathlib import Path
import shutil
import subprocess

from domain import governance
from domain.scenarios import all_disabled, matrix


class TestSecurityPostureMocked(unittest.TestCase):
    def test_private_mode_has_zero_public_endpoints(self) -> None:
        ov = next(s for s in matrix() if s.name == "net_private").env_overrides()
        self.assertEqual(0, governance.public_endpoint_count(ov))

    def test_public_mode_has_public_endpoints(self) -> None:
        ov = next(s for s in matrix() if s.name == "net_public").env_overrides()
        self.assertGreater(governance.public_endpoint_count(ov), 0)

    def test_all_disabled_has_zero_public_endpoints(self) -> None:
        self.assertEqual(0, governance.public_endpoint_count(all_disabled().env_overrides()))

    @mock.patch(
        "domain.governance.cli.az_json",
        return_value={"properties": {"disableLocalAuth": True}},
    )
    def test_key_auth_disabled_true(self, _json) -> None:
        self.assertTrue(governance.key_auth_disabled("foundry1"))

    @mock.patch(
        "domain.governance.cli.az_json",
        return_value={"properties": {"disableLocalAuth": False}},
    )
    def test_key_auth_disabled_false(self, _json) -> None:
        self.assertFalse(governance.key_auth_disabled("foundry1"))


class TestDefenderOptInContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("bicep")
        if not compiler:
            raise unittest.SkipTest("Standalone Bicep is required for Defender template contracts")
        root = Path(__file__).resolve().parents[4] / "environment_setup/aifactory/bicep"
        cls.templates = {}
        for name, relative in (
            ("defender", "esml-common/security/defender.bicep"),
            ("common", "esml-common/main/11-rgCommon.bicep"),
        ):
            result = subprocess.run(
                [compiler, "build", str(root / relative), "--stdout", "--no-restore"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.templates[name] = json.loads(result.stdout)

    def defender_deployment(self):
        matches = [
            resource for resource in self.templates["common"]["resources"]
            if resource["type"] == "Microsoft.Resources/deployments"
            and resource["name"].startswith("[format('DefenderForCloud-")
        ]
        self.assertEqual(1, len(matches))
        return matches[0]

    def test_subscription_writes_remain_explicit_opt_in(self) -> None:
        common = self.templates["common"]
        self.assertIs(False, common["parameters"]["enableDefenderforAISubLevel"]["defaultValue"])
        self.assertEqual(
            "[parameters('enableDefenderforAISubLevel')]",
            self.defender_deployment()["condition"],
        )

    def test_common_opt_in_respects_individual_plan_selection(self) -> None:
        params = self.defender_deployment()["properties"]["parameters"]
        self.assertIs(False, params["enableAll"]["value"])
        self.assertIs(False, params["enableDefenderForContainers"]["value"])
        self.assertIs(False, params["enableDefenderForCloudPosture"]["value"])
        self.assertEqual("[parameters('enableAdminVM')]", params["enableDefenderForVirtualMachines"]["value"])
        for parameter in ("enableDefenderForKeyVault", "enableDefenderForStorage"):
            self.assertIs(True, params[parameter]["value"])

    def test_opt_in_does_not_write_free_tiers_or_servers_p1(self) -> None:
        params = self.defender_deployment()["properties"]["parameters"]
        self.assertEqual("Standard", params["pricingTier"]["value"])
        self.assertEqual("Standard", params["advancedPricingTier"]["value"])
        self.assertEqual("P2", params["vmSubPlan"]["value"])
        defaults = self.templates["defender"]["parameters"]
        self.assertEqual("Standard", defaults["pricingTier"]["defaultValue"])
        self.assertEqual("P2", defaults["vmSubPlan"]["defaultValue"])
        self.assertEqual(["Standard", "Free"], defaults["pricingTier"]["allowedValues"])
        self.assertEqual(["P1", "P2", ""], defaults["vmSubPlan"]["allowedValues"])

    def test_standalone_module_honors_false_flags_without_master_override(self) -> None:
        template = self.templates["defender"]
        self.assertIs(False, template["parameters"]["enableAll"]["defaultValue"])
        flags = {
            "[parameters('aiPlanName')]": "enableDefenderForAI",
            "StorageAccounts": "enableDefenderForStorage",
            "KeyVaults": "enableDefenderForKeyVault",
            "Containers": "enableDefenderForContainers",
            "CloudPosture": "enableDefenderForCloudPosture",
            "VirtualMachines": "enableDefenderForVirtualMachines",
        }
        self.assertEqual(set(flags), {r["name"] for r in template["resources"]})
        for resource in template["resources"]:
            with self.subTest(plan=resource["name"]):
                self.assertEqual(
                    f"[or(parameters('enableAll'), parameters('{flags[resource['name']]}'))]",
                    resource["condition"],
                )

    def test_ai_extensions_require_paid_tier_and_no_new_auto_provisioning(self) -> None:
        template = self.templates["defender"]
        ai = next(r for r in template["resources"] if r["name"] == "[parameters('aiPlanName')]")
        self.assertIn(
            "and(equals(parameters('pricingTier'), 'Standard'), parameters('enableAIPromptEvidence'))",
            ai["properties"]["extensions"],
        )
        for parameter in (
            "enableAIPromptEvidence", "enableContainerSensor",
            "enableAgentlessDiscoveryForKubernetes", "enableMdeDesignatedSubscription",
        ):
            self.assertIs(False, template["parameters"][parameter]["defaultValue"])
        self.assertEqual("False", template["parameters"]["enforce"]["defaultValue"])


if __name__ == "__main__":
    unittest.main()
