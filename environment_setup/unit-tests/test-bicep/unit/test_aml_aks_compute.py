"""Unit tests guarding the Azure ML + AKS inference compute (offline).

Regression context: machineLearningAks.bicep once declared TWO AKS inference
compute resources (dev and test/prod) that compiled to the SAME ARM name
(`aksName`) under the SAME parent workspace. Bicep serializes same-named
resources with an implicit dependsOn, so a prod run referenced the
condition-excluded dev twin and ARM failed validation with:

  "The resource '.../computes/<aksName>' is not defined in the template."

These tests assert the two twins stay merged into a single env-agnostic
resource, so Azure ML deploys correctly WITH AKS in dev, test and prod (and,
being conditional, still deploys WITHOUT AKS when enableAksForAzureML=false).

`az bicep build` compiles the defective form fine, so this must be a static
source check rather than a build test.
"""
from __future__ import annotations

import unittest

from base import config
from domain import iac

_AML_AKS_TEMPLATE = config.MODULES_BICEP_DIR / "machineLearningAks.bicep"
_COMPUTE_TYPE = "Microsoft.MachineLearningServices/workspaces/computes"


class TestAmlAksCompute(unittest.TestCase):
    def test_module_exists(self) -> None:
        self.assertTrue(
            _AML_AKS_TEMPLATE.is_file(),
            f"expected AML AKS module at {_AML_AKS_TEMPLATE}",
        )

    def test_no_duplicate_named_compute(self) -> None:
        """No two computes share (parent, name) -> no 'not defined' error."""
        dups = iac.duplicate_named_resources(_AML_AKS_TEMPLATE, _COMPUTE_TYPE)
        self.assertEqual(
            [], dups,
            "duplicate (parent, name) AKS compute declarations reintroduce the "
            f"ARM 'resource is not defined in the template' failure: {dups}",
        )

    def test_single_aks_inference_compute(self) -> None:
        """The dev + test/prod computes must remain a single merged resource."""
        aks_computes = [
            d for d in iac.resource_declarations(_AML_AKS_TEMPLATE, _COMPUTE_TYPE)
            if "'AKS'" in d["body"]
        ]
        self.assertEqual(
            1, len(aks_computes),
            f"expected exactly one AKS inference compute, found {len(aks_computes)}",
        )

    def test_merged_compute_covers_all_environments(self) -> None:
        """The single compute selects dev vs test/prod values (all envs work)."""
        aks_computes = [
            d for d in iac.resource_declarations(_AML_AKS_TEMPLATE, _COMPUTE_TYPE)
            if "'AKS'" in d["body"]
        ]
        self.assertEqual(1, len(aks_computes), "precondition: one AKS compute")
        body = aks_computes[0]["body"]
        # Env-specific branches proving dev, test and prod are all handled.
        for token in ("DevTest", "FastProd", "aksVmSku_dev", "aksVmSku_testProd"):
            self.assertIn(
                token, body,
                f"merged AKS compute is missing env-specific handling: '{token}'",
            )

    def test_compute_not_hard_gated_to_single_env(self) -> None:
        """The compute condition must not pin a single env (e.g. env == 'dev')."""
        aks_computes = [
            d for d in iac.resource_declarations(_AML_AKS_TEMPLATE, _COMPUTE_TYPE)
            if "'AKS'" in d["body"]
        ]
        self.assertEqual(1, len(aks_computes), "precondition: one AKS compute")
        header = aks_computes[0]["body"].split("{", 1)[0]
        self.assertNotIn(
            "env == 'dev'", header,
            "AKS compute condition is hard-gated to dev; test/prod would be excluded",
        )

    def test_existing_cluster_attach_sets_load_balancer_subnet(self) -> None:
        """Attaching an existing AKS (aksExists) must still name the internal LB subnet.

        Without loadBalancerSubnet Azure ML defaults to 'aks-subnet' and the
        azureml-fe internal load balancer fails after ~50 minutes with
        "failed to get subnet: <vnet>/aks-subnet" (GetAssignedIPFromK8sFailed).
        """
        aks_computes = [
            d for d in iac.resource_declarations(_AML_AKS_TEMPLATE, _COMPUTE_TYPE)
            if "'AKS'" in d["body"]
        ]
        self.assertEqual(1, len(aks_computes), "precondition: one AKS compute")
        body = aks_computes[0]["body"]
        always_applied = body.split("!aksExists ?", 1)[0]
        self.assertIn("loadBalancerType: 'InternalLoadBalancer'", always_applied)
        self.assertIn(
            "loadBalancerSubnet: aksSubnetName", always_applied,
            "loadBalancerSubnet is only set for new clusters; attaching an existing "
            "cluster falls back to the non-existent 'aks-subnet'",
        )

    def test_repeated_attachment_resubmits_immutable_sizes(self) -> None:
        """An omitted size defaults on PUT and fails an already-attached compute."""
        aks_computes = [
            d for d in iac.resource_declarations(_AML_AKS_TEMPLATE, _COMPUTE_TYPE)
            if "'AKS'" in d["body"]
        ]
        self.assertEqual(1, len(aks_computes), "precondition: one AKS compute")
        common, creation = aks_computes[0]["body"].split("}, !aksExists ? {", 1)
        for binding in (
            "agentCount: env == 'dev' ? aksNodes_dev : aksNodes_testProd",
            "agentVmSize: env == 'dev' ? aksVmSku_dev : aksVmSku_testProd",
        ):
            with self.subTest(binding=binding):
                self.assertIn(binding, common, "Existing attachments must resend their immutable sizes")
                self.assertNotIn(binding, creation)
        self.assertNotIn("aksNetworkingConfiguration:", common)
        self.assertIn("aksNetworkingConfiguration:", creation)

    def test_attachment_caller_preserves_configured_sizes(self) -> None:
        """aksExists must not replace immutable attachment sizes with zero/empty."""
        source = (config.GENAI_BICEP_DIR / "07-ml-data-platform.bicep").read_text()
        caller = source.split("module amlv2Aks ", 1)[1].split("\nmodule ", 1)[0]
        for binding in (
            "aksVmSku_dev: aks_dev_sku_param",
            "aksVmSku_testProd: aks_test_prod_sku_param",
            "aksNodes_dev: aks_dev_nodes_param",
            "aksNodes_testProd: aks_test_prod_nodes_param",
        ):
            with self.subTest(binding=binding):
                self.assertIn(binding, caller, "Attachment caller must forward desired immutable sizes")


if __name__ == "__main__":
    unittest.main()
