"""Offline contract tests for optional AI Foundry model deployments."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import unittest
from pathlib import Path

from base.config import env_defaults, yaml_defaults


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
FOUNDRY_MODULE = BICEP / "modules/csFoundry/aiFoundry2025AvmOffApim.bicep"
ACCOUNT_MODULE = BICEP / "modules/csFoundry/aiFoundry2025AvmOffApimAccount.bicep"
FOUNDRY_TEMPLATES = (
    BICEP / "esml-genai-1/09-ai-foundry-2025-v3.bicep",
    BICEP / "esml-genai-1/09-ai-foundry-2025-v4.bicep",
)
GPTX_DEFAULTS = {
    "modelGPTXName": ("MODEL_GPTX_NAME", "gpt-5.4-mini"),
    "modelGPTXVersion": ("MODEL_GPTX_VERSION", "2026-03-17"),
    "modelGPTXSku": ("MODEL_GPTX_SKU", "GlobalStandard"),
}
GPTX_TEMPLATES = (
    *FOUNDRY_TEMPLATES,
    BICEP / "esml-genai-1/03-cognitive-services.bicep",
    BICEP / "esml-genai-1/06-ai-platform.bicep",
    BICEP / "modules/csAIServices.bicep",
)


class TestFoundryModelDeployments(unittest.TestCase):
    def test_gptx_defaults_match_in_yaml_dotenv_json_and_workflow(self) -> None:
        baseline = json.loads((ROOT / "environment_setup/aifactory/variables.json").read_text(encoding="utf-8"))
        workflow = (BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
        for camel, (upper, expected) in GPTX_DEFAULTS.items():
            with self.subTest(parameter=camel):
                self.assertEqual(expected, yaml_defaults()[camel])
                self.assertEqual(expected, env_defaults()[upper])
                self.assertEqual(expected, baseline["dev"][camel])
                self.assertIn(f"{camel}: ${{{{ vars.{upper} || '{expected}' }}}}", workflow)

    def test_gptx_defaults_match_every_bicep_entry_point(self) -> None:
        for path in GPTX_TEMPLATES:
            content = path.read_text(encoding="utf-8")
            with self.subTest(template=path.name):
                for parameter, (_, expected) in GPTX_DEFAULTS.items():
                    self.assertIn(f"param {parameter} string = '{expected}'", content)
                self.assertIn("param deployModel_gpt_X bool = false", content)

    def test_explicit_gptx_parameters_still_drive_foundry_model_selection(self) -> None:
        for path in FOUNDRY_TEMPLATES:
            with self.subTest(template=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertRegex(
                    content,
                    r"deployModel_gpt_X \? \[\{\s+modelName: modelGPTXName\s+"
                    r"version: modelGPTXVersion\s+capacity: modelGPTXCapacity\s+"
                    r"skuLocation: modelGPTXSku\s+\}\] : \[\]",
                )

    def test_preflight_defaults_overrides_and_disabled_flags(self) -> None:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("Bash is required to exercise preflight model selection")
        preflight = (BICEP / "scripts/preflight.sh").read_text(encoding="utf-8")
        getval = re.search(r"(?ms)^getval\(\).*?^\}", preflight).group(0)
        is_true = re.search(r"(?m)^is_true\(\).*?$", preflight).group(0)
        selection = preflight.split("# Model deployments\n", 1)[1].split("# --- Networking CIDRs", 1)[0]
        script = (
            "set -euo pipefail\nyaml_get() { :; }\ndotenv_get() { :; }\n"
            + getval + "\n" + is_true + "\n" + selection
            + '\nfor model in "${MODELS[@]}"; do printf "MODEL:%s\\n" "$model"; done\n'
        )
        inherited = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith(("DEPLOY", "MODEL", "DEFAULT", "GPTX"))
        }
        cases = (
            ({}, []),
            ({"DEPLOY_MODEL_GPT_X": "true"}, ["gpt-5.4-mini|GlobalStandard|30"]),
            ({
                "DEPLOY_MODEL_GPT_X": "true", "MODEL_GPTX_NAME": "gpt-5.1",
                "MODEL_GPTX_SKU": "DataZoneStandard", "MODEL_GPTX_CAPACITY": "10",
            }, ["gpt-5.1|DataZoneStandard|10"]),
            ({
                "deployModel_gpt_X": "true", "modelGPTXName": "gpt-5.1",
                "modelGPTXSku": "DataZoneStandard", "modelGPTXCapacity": "20",
            }, ["gpt-5.1|DataZoneStandard|20"]),
            ({"DEPLOY_MODEL_GPT_X": "false", "MODEL_GPTX_NAME": "gpt-5.4-mini"}, []),
        )
        for values, expected in cases:
            with self.subTest(values=values):
                # Inject in Bash too: WSL does not automatically inherit arbitrary Windows env vars.
                exports = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())
                result = subprocess.run(
                    [bash, "--noprofile", "--norc", "-s"],
                    input=(exports + script).encode("utf-8"), env=inherited | values,
                    capture_output=True, check=False, timeout=30,
                )
                self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
                models = re.findall(r"(?m)^MODEL:(.*)\r?$", result.stdout.decode("utf-8"))
                self.assertEqual(expected, [model.rstrip("\r") for model in models])

    def test_default_model_and_version_are_consistent_in_both_child_modules(self) -> None:
        for path in (FOUNDRY_MODULE, ACCOUNT_MODULE):
            with self.subTest(module=path.name):
                content = path.read_text(encoding="utf-8")
                for parameter, expected in (
                    ("modelName", "gpt-5.4-mini"),
                    ("modelVersion", "2026-03-17"),
                    ("modelFormat", "OpenAI"),
                    ("modelSkuName", "GlobalStandard"),
                ):
                    self.assertIn(f"param {parameter} string = '{expected}'", content)

    def test_empty_selection_placeholder_matches_child_default(self) -> None:
        for path in FOUNDRY_TEMPLATES:
            with self.subTest(template=path.name):
                content = path.read_text(encoding="utf-8")
                placeholder = content.split("var defaultModelDeploymentV22 =", 1)[1].split(
                    "var extraModelDeploymentsV22 =", 1
                )[0]
                self.assertIn("hasModelDeploymentsV22 ? aiFoundryDeployments[0] : {", placeholder)
                self.assertEqual(2, placeholder.count("name: 'gpt-5.4-mini'"))
                self.assertIn("version: '2026-03-17'", placeholder)
                self.assertIn("name: 'GlobalStandard'", placeholder)
                self.assertNotIn("gpt-4o", placeholder)

    def test_explicit_gpt_4o_selection_is_preserved(self) -> None:
        for path in FOUNDRY_TEMPLATES:
            with self.subTest(template=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertRegex(
                    content,
                    r"deployModel_gpt_4o \? \[\{\s+modelName: 'gpt-4o'\s+"
                    r"version: default_gpt_4o_version\s+capacity: default_gpt_capacity\s+"
                    r"skuLocation: default_model_sku\s+\}\] : \[\]",
                )

    def test_additional_models_do_not_depend_on_a_disabled_default(self) -> None:
        content = FOUNDRY_MODULE.read_text(encoding="utf-8")
        self.assertIn("...(deployDefaultModel ? [aiAccountDeployment] : [])", content)
        for path in FOUNDRY_TEMPLATES:
            with self.subTest(template=path.name):
                template = path.read_text(encoding="utf-8")
                self.assertIn("var hasModelDeploymentsV22 = length(aiFoundryDeployments) > 0", template)
                self.assertIn(
                    "var extraModelDeploymentsV22 = (hasModelDeploymentsV22 && length(aiFoundryDeployments) > 1) "
                    "? skip(aiFoundryDeployments, 1) : []",
                    template,
                )

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
