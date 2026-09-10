"""Capability hosts opt into dependencies without overriding explicit service opt-outs."""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from unit.test_bootstrap_scaleset import state

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
    def test_simple_mode_preset_still_selects_its_agent_bundle(self) -> None:
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

    def test_advanced_defaults_describe_optional_capability_host_dependencies(self) -> None:
        ado = ADO_VARIABLES.read_text(encoding="utf-8")
        gha = GHA_ENV.read_text(encoding="utf-8")
        baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))["dev"]
        for key in (
            "enableAIFoundry",
            "enableAFoundryCaphost",
            "enableAISearch",
        ):
            self.assertRegex(ado, rf"(?m)^\s+{key}:\s+[\"']true[\"']")
            self.assertEqual(baseline[key], "true")
        self.assertRegex(ado, r'(?m)^\s+enableCosmosDB:\s+"false"')
        self.assertEqual(baseline["enableCosmosDB"], "false")
        for key in (
            "ENABLE_AI_FOUNDRY",
            "ENABLE_FOUNDRY_CAPHOST",
            "ENABLE_AI_SEARCH",
        ):
            self.assertRegex(gha, rf'(?m)^{key}="true"')
        self.assertRegex(gha, r'(?m)^ENABLE_COSMOS_DB="false"')
        self.assertIn(
            "enableCosmosDB: ${{ vars.ENABLE_COSMOS_DB || 'false' }}",
            GHA_PROJECT.read_text(encoding="utf-8"),
        )
        for content, keys in ((ado, ("enableAFoundryCaphost", "enableAISearch", "enableCosmosDB")),
                              (gha, ("ENABLE_FOUNDRY_CAPHOST", "ENABLE_AI_SEARCH", "ENABLE_COSMOS_DB"))):
            for key in keys:
                line = next(line for line in content.splitlines()
                            if re.match(rf"\s*{key}[:=]", line))
                self.assertNotIn("Cannot be disabled", line)
                self.assertIn("<optional>", line)

    def test_bicep_guards_and_capability_host_connections_are_complete(self) -> None:
        for path in FOUNDRY_TEMPLATES:
            with self.subTest(path=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertNotIn("privateFoundryStandardAgents", content)
                self.assertNotIn("assert privateFoundryRequires", content)
        search = FOUNDRY_TEMPLATES[0].read_text(encoding="utf-8")
        cosmos = FOUNDRY_TEMPLATES[1].read_text(encoding="utf-8")
        self.assertIn("var needsAISearch = enableAISearch || (enableAFoundryCaphost && enableAIFoundry)", search)
        self.assertIn("var needsCosmosDB = enableCosmosDB || (enableAFoundryCaphost && enableAIFoundry)", cosmos)
        self.assertIn("kind: (enableAFoundryCaphost && enableAIFoundry) ? 'GlobalDocumentDB' : cosmosKind", cosmos)
        for path in FOUNDRY_TEMPLATES[2:]:
            with self.subTest(enforcement=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("var effectiveEnableCaphost = enableCaphost", content)
                self.assertIn("var effectiveEnableAISearch = enableAISearch || (enableCaphost && enableAIFoundry)", content)
                self.assertIn("var effectiveEnableCosmosDB = enableCosmosDB || (enableCaphost && enableAIFoundry)", content)
        capability_host = (
            BICEP / "modules/csFoundry/aiFoundry2025caphost.bicep"
        ).read_text(encoding="utf-8")
        self.assertIn("threadStorageConnections", capability_host)
        self.assertIn("vectorStoreConnections", capability_host)
        self.assertIn("storageConnections", capability_host)

    def test_preflight_resolves_only_requested_capability_host_dependencies(self) -> None:
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
        if bash is None:
            self.skipTest("Bash is required")
        content = PREFLIGHT.read_text(encoding="utf-8")
        function = re.search(
            r"(?ms)^resolve_foundry_capability_host_dependencies\(\) \{.*?^\}",
            content,
        )
        self.assertIsNotNone(function)
        self.assertNotIn("PRIVATE_FOUNDRY_CAPABILITY_HOST_REQUIRED", content)
        self.assertLess(content.index("\nresolve_foundry_capability_host_dependencies\n"),
                        content.index("\nfor t in "))
        for foundry, caphost, search, cosmos, public in itertools.product((False, True), repeat=5):
            assignments = {
                "ENABLE_AI_FOUNDRY": str(foundry).lower(),
                "ENABLE_PUBLIC_GENAI": str(public).lower(),
                "ENABLE_FOUNDRY_CAPHOST": str(caphost).lower(),
                "ENABLE_AI_SEARCH": str(search).lower(),
                "ENABLE_COSMOS": str(cosmos).lower(),
            }
            shell = "\n".join(
                f"{key}={value}" for key, value in assignments.items()
            )
            script = (
                "set -uo pipefail\n"
                "is_true() { case \"${1:-}\" in true) return 0;; *) return 1;; esac; }\n"
                "add_finding() { printf '%s:%s\\n' \"$1\" \"$2\"; }\n"
                f"{function.group(0)}\n{shell}\n"
                "resolve_foundry_capability_host_dependencies\n"
                "printf 'RESULT:%s,%s,%s\\n' \"$ENABLE_FOUNDRY_CAPHOST\" \"$ENABLE_AI_SEARCH\" \"$ENABLE_COSMOS\"\n"
            )
            result = subprocess.run(
                [bash, "-c", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            with self.subTest(**assignments):
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = (caphost, search or (foundry and caphost), cosmos or (foundry and caphost))
                self.assertIn("RESULT:" + ",".join(str(v).lower() for v in expected), result.stdout)

    def test_advanced_bootstrap_preserves_explicit_resource_choices(self) -> None:
        keys = ("enableAFoundryCaphost", "enableAISearch", "enableCosmosDB")
        env_keys = ("ENABLE_FOUNDRY_CAPHOST", "ENABLE_AI_SEARCH", "ENABLE_COSMOS_DB")
        for route, flags in itertools.product(("ado", "gha"), itertools.product(("false", "true"), repeat=3)):
            with self.subTest(route=route, flags=flags), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                json_path = repo / "aifactory/variables.json"
                json_path.parent.mkdir(parents=True)
                values = dict(zip(keys, flags))
                json_path.write_text(json.dumps({"dev": values}), encoding="utf-8")
                if route == "ado":
                    config_path = repo / "aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
                    config_path.parent.mkdir(parents=True)
                    config_path.write_text(yaml.safe_dump({"variables": values}), encoding="utf-8")
                    CONFIG.apply_ado(repo, state())
                    actual = yaml.safe_load(config_path.read_text(encoding="utf-8"))["variables"]
                    self.assertEqual(tuple(actual[k] for k in keys), flags)
                else:
                    config_path = repo / ".env"
                    config_path.write_text("".join(f'{k}="{v}"\n' for k, v in zip(env_keys, flags)), encoding="utf-8")
                    CONFIG.apply_gha(repo, state())
                    actual = dict(re.findall(r'(?m)^(\w+)="([^"]*)"', config_path.read_text(encoding="utf-8")))
                    self.assertEqual(tuple(actual[k] for k in env_keys), flags)
                actual = json.loads(json_path.read_text(encoding="utf-8"))["dev"]
                self.assertEqual(tuple(actual[k] for k in keys), flags)

    def test_both_pipeline_routes_forward_all_dependency_flags(self) -> None:
        ado = yaml.safe_load(ADO_PROJECT_JOB.read_text(encoding="utf-8"))["steps"]
        gha = yaml.safe_load(GHA_PROJECT.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]
        for steps, ado_route in ((ado, True), (gha, False)):
            matched = 0
            for step in steps:
                source = step.get("inputs", {}).get("inlineScript", "") if ado_route else step.get("run", "")
                if not any(path.name in source and "--template-file" in source for path in FOUNDRY_TEMPLATES):
                    continue
                matched += 1
                is_foundry = "09-ai-foundry" in source
                names = ("enableCaphost", "enableAISearch", "enableCosmosDB") if is_foundry else (
                    "enableAFoundryCaphost",
                    "enableAISearch" if "03-cognitive-services" in source else "enableCosmosDB",
                )
                for name in (*names, "enableAIFoundry"):
                    variable = "enableAFoundryCaphost" if name == "enableCaphost" else name
                    value = f"$({variable})" if ado_route else "${{ env." + variable + " }}"
                    self.assertIn(f'--parameters {name}="{value}"', source)
            self.assertEqual(matched, 4)

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
