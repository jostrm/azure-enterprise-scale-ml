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


if __name__ == "__main__":
    unittest.main()
