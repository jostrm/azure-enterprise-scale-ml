"""Offline contract tests for optional AI Foundry model deployments."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
FOUNDRY_MODULE = BICEP / "modules/csFoundry/aiFoundry2025AvmOffApim.bicep"
FOUNDRY_TEMPLATES = (
    BICEP / "esml-genai-1/09-ai-foundry-2025-v3.bicep",
    BICEP / "esml-genai-1/09-ai-foundry-2025-v4.bicep",
)


class TestFoundryModelDeployments(unittest.TestCase):
    def test_default_model_resource_is_optional(self) -> None:
        module = FOUNDRY_MODULE.read_text(encoding="utf-8")

        self.assertIn("param deployDefaultModel bool = true", module)
        self.assertIn(
            "resource aiAccountDeployment "
            "'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' "
            "= if (deployDefaultModel) {",
            module,
        )

    def test_foundry_templates_disable_default_model_for_an_empty_model_list(self) -> None:
        for template_path in FOUNDRY_TEMPLATES:
            with self.subTest(template=template_path.name):
                template = template_path.read_text(encoding="utf-8")
                account_only, full_deployment = template.split(
                    "module aiFoundry2025NoAvmV22 "
                    "'../modules/csFoundry/aiFoundry2025AvmOffApim.bicep'",
                    maxsplit=1,
                )
                self.assertNotIn(
                    "deployDefaultModel: hasModelDeploymentsV22",
                    account_only,
                )
                self.assertIn(
                    "deployDefaultModel: hasModelDeploymentsV22",
                    full_deployment,
                )


if __name__ == "__main__":
    unittest.main()
