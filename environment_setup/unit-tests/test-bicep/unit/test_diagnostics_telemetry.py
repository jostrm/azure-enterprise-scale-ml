"""Offline contract tests for Foundry, Azure OpenAI, and AI Search telemetry."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
COGNITIVE_DIAGNOSTICS = BICEP / "modules/diagnostics/cognitiveServicesDiagnostics.bicep"
SEARCH_DIAGNOSTICS = BICEP / "modules/diagnostics/aiSearchDiagnostics.bicep"
OPENAI = BICEP / "modules/csOpenAI.bicep"
COGNITIVE_SERVICES = BICEP / "esml-genai-1/03-cognitive-services.bicep"
FOUNDRY_V4 = BICEP / "esml-genai-1/09-ai-foundry-2025-v4.bicep"


class TestDiagnosticsTelemetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cognitive_diagnostics = COGNITIVE_DIAGNOSTICS.read_text(encoding="utf-8")
        cls.search_diagnostics = SEARCH_DIAGNOSTICS.read_text(encoding="utf-8")
        cls.openai = OPENAI.read_text(encoding="utf-8")
        cls.cognitive_services = COGNITIVE_SERVICES.read_text(encoding="utf-8")
        cls.foundry_v4 = FOUNDRY_V4.read_text(encoding="utf-8")

    def test_foundry_usage_categories_are_enabled_at_every_tier(self) -> None:
        for category in ("RequestResponse", "Trace", "AzureOpenAIRequestUsage"):
            self.assertIn(f"category: '{category}'", self.cognitive_diagnostics)
        self.assertIn("param includeAzureOpenAIUsageTelemetry bool = false", self.cognitive_diagnostics)
        self.assertIn(
            "includeAzureOpenAIUsageTelemetry ? union(tierLogs, foundryRequiredLogs) : tierLogs",
            self.cognitive_diagnostics,
        )
        self.assertIn(
            "includeAzureOpenAIUsageTelemetry: true", self.foundry_v4
        )

    def test_openai_collects_usage_metrics_and_logs_for_new_resources(self) -> None:
        self.assertIn("workspaceId: logAnalyticsWorkspace.id", self.openai)
        self.assertIn("category: 'AllMetrics'", self.openai)
        for category in ("RequestResponse", "Trace", "AzureOpenAIRequestUsage"):
            self.assertIn(f"category: '{category}'", self.openai)
        self.assertIn("logAnalyticsDestinationType: null", self.openai)

    def test_existing_openai_gets_the_same_telemetry_without_duplicate_settings(self) -> None:
        self.assertIn(
            "if (openaiExists && enableAzureOpenAI && !skipDiagAOAI)",
            self.cognitive_services,
        )
        self.assertIn(
            "includeAzureOpenAIUsageTelemetry: true", self.cognitive_services
        )
        self.assertNotIn(
            "if (!openaiExists && enableAzureOpenAI && !skipDiagAOAI)",
            self.cognitive_services,
        )

    def test_search_collects_requests_and_metrics_on_reruns(self) -> None:
        self.assertIn("category: 'OperationLogs'", self.search_diagnostics)
        self.assertIn("category: 'AllMetrics'", self.search_diagnostics)
        self.assertIn(
            "if ((enableAISearch || (enableAFoundryCaphost && enableAIFoundry)) && !skipDiagAISearch)",
            self.cognitive_services,
        )
        self.assertNotIn(
            "if (!aiSearchExists && (enableAISearch || (enableAFoundryCaphost && enableAIFoundry)) && !skipDiagAISearch)",
            self.cognitive_services,
        )


if __name__ == "__main__":
    unittest.main()