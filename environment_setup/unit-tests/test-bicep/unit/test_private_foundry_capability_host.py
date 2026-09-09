"""Contracts for the private Foundry standard-agent capability-host bundle."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
CONFIG_PATH = ROOT / "bootstrap/lib/aifactory_scaleset_config.py"
ADO_VARIABLES = (
    BICEP
    / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml"
)
ADO_PROJECT_JOB = (
    BICEP
    / "copy_to_local_settings/azure-devops/esml-yaml-pipelines"
    / "esml-infra-project/jobs/job-2-genai-services.yaml"
)
GHA_ENV = BICEP / "copy_to_local_settings/github-actions/.env.template"
GHA_PROJECT = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
PREFLIGHT = BICEP / "scripts/preflight.sh"
BASELINE_JSON = ROOT / "environment_setup/aifactory/variables.json"
FOUNDRY_TEMPLATES = (
    BICEP / "esml-genai-1/03-cognitive-services.bicep",
    BICEP / "esml-genai-1/04-databases.bicep",
    BICEP / "esml-genai-1/09-ai-foundry-2025-v3.bicep",
    BICEP / "esml-genai-1/09-ai-foundry-2025-v4.bicep",
)

SPEC = importlib.util.spec_from_file_location("aifactory_scaleset_config", CONFIG_PATH)
assert SPEC and SPEC.loader
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


class TestPrivateFoundryCapabilityHost(unittest.TestCase):
    def test_required_bundle_is_visible_and_not_deselectable(self) -> None:
        catalog = getattr(CONFIG, "SIMPLE_MODE_RESOURCE_CATALOG", None)
        if catalog is not None:
            project = {item["id"]: item for item in catalog["project"]}
            required = {
                "foundry",
                "foundry-capability-host",
                "storage",
                "ai-search",
                "cosmos-db",
            }
            self.assertTrue(required.issubset(project))
            self.assertTrue(all(project[item]["required"] for item in required))
        values = CONFIG.simple_mode_values()
        for key in (
            "enableAIFoundry",
            "enableAFoundryCaphost",
            "enableAISearch",
            "enableAISearchSharedPrivateLink",
            "enableCosmosDB",
        ):
            self.assertEqual(values[key], "true")
        manifest = CONFIG.simple_mode_manifest()
        self.assertIn("capability host", manifest["services"]["Foundry"])
        self.assertIn("Cosmos DB", manifest["services"])
        self.assertNotIn(
            "No model deployments or agent capability host",
            manifest["limitations"],
        )

    def test_ado_gha_and_json_defaults_enable_the_bundle(self) -> None:
        ado = ADO_VARIABLES.read_text(encoding="utf-8")
        gha = GHA_ENV.read_text(encoding="utf-8")
        baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))["dev"]
        for key in (
            "enableAIFoundry",
            "enableAFoundryCaphost",
            "enableAISearch",
            "enableCosmosDB",
        ):
            self.assertRegex(ado, rf"(?m)^\s+{key}:\s+[\"']true[\"']")
            self.assertEqual(baseline[key], "true")
        for key in (
            "ENABLE_AI_FOUNDRY",
            "ENABLE_FOUNDRY_CAPHOST",
            "ENABLE_AI_SEARCH",
            "ENABLE_COSMOS_DB",
        ):
            self.assertRegex(gha, rf'(?m)^{key}="true"')
        self.assertIn(
            "enableCosmosDB: ${{ vars.ENABLE_COSMOS_DB || 'true' }}",
            GHA_PROJECT.read_text(encoding="utf-8"),
        )
        config = CONFIG_PATH.read_text(encoding="utf-8")
        for assignment in (
            '"enableAFoundryCaphost": "true"',
            '"enableAISearch": "true"',
            '"enableCosmosDB": "true"',
            '"ENABLE_FOUNDRY_CAPHOST": "true"',
            '"ENABLE_AI_SEARCH": "true"',
            '"ENABLE_COSMOS_DB": "true"',
        ):
            self.assertIn(assignment, config)

    def test_bicep_guards_and_capability_host_connections_are_complete(self) -> None:
        for path in FOUNDRY_TEMPLATES:
            with self.subTest(path=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("privateFoundryStandardAgents", content)
                self.assertNotIn("assert privateFoundryRequires", content)
        for path in FOUNDRY_TEMPLATES[2:]:
            with self.subTest(enforcement=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("effectiveEnableCaphost", content)
                self.assertIn("effectiveEnableAISearch", content)
                self.assertIn("effectiveEnableCosmosDB", content)
        capability_host = (
            BICEP / "modules/csFoundry/aiFoundry2025caphost.bicep"
        ).read_text(encoding="utf-8")
        self.assertIn("threadStorageConnections", capability_host)
        self.assertIn("vectorStoreConnections", capability_host)
        self.assertIn("storageConnections", capability_host)

    def test_preflight_hard_fails_when_private_bundle_is_disabled(self) -> None:
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
        if bash is None:
            self.skipTest("Bash is required")
        content = PREFLIGHT.read_text(encoding="utf-8")
        function = re.search(
            r"(?ms)^check_private_foundry_capability_host\(\) \{.*?^\}",
            content,
        )
        assert function
        for variable in (
            "ENABLE_FOUNDRY_CAPHOST",
            "ENABLE_AI_SEARCH",
            "ENABLE_COSMOS",
        ):
            assignments = {
                "ENABLE_AI_FOUNDRY": "true",
                "ENABLE_PUBLIC_GENAI": "false",
                "ENABLE_FOUNDRY_CAPHOST": "true",
                "ENABLE_AI_SEARCH": "true",
                "ENABLE_COSMOS": "true",
            }
            assignments[variable] = "false"
            shell = "\n".join(
                f"{key}={value}" for key, value in assignments.items()
            )
            script = (
                "set -uo pipefail\n"
                "is_true() { case \"${1:-}\" in true) return 0;; *) return 1;; esac; }\n"
                "add_finding() { printf '%s:%s\\n' \"$1\" \"$2\"; }\n"
                f"{function.group(0)}\n{shell}\n"
                "check_private_foundry_capability_host\n"
            )
            result = subprocess.run(
                [bash, "-c", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            with self.subTest(variable=variable):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "PRIVATE_FOUNDRY_CAPABILITY_HOST_REQUIRED",
                    result.stdout,
                )

    def test_ado_preflight_receives_private_bundle_flags(self) -> None:
        job = ADO_PROJECT_JOB.read_text(encoding="utf-8")
        self.assertIn(
            "enableAFoundryCaphost: $(enableAFoundryCaphost)",
            job,
        )
        self.assertIn(
            "enablePublicGenAIAccess: $(enablePublicGenAIAccess)",
            job,
        )


if __name__ == "__main__":
    unittest.main()
