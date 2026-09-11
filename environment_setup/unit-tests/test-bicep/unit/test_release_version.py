"""Offline checks for version-pinned ADO updates of the v1.24 release."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

import yaml
ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("release_version", ROOT / "bootstrap/lib/release_version.py")
VERSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERSION)


class TestReleaseVersion(unittest.TestCase):
    def test_release_selector_and_invalid_typo(self):
        self.assertEqual("release/v1.24", VERSION.branch_for("124"))
        self.assertEqual("release/v1.24", VERSION.branch_for("1.24"))
        self.assertEqual("release/v1.25", VERSION.branch_for("125"))
        with self.assertRaises(ValueError):
            VERSION.branch_for("1254")

    def test_exact_published_branch_is_required(self):
        read = Mock(return_value="a" * 40 + "\trefs/heads/release/v1.24")
        result = VERSION.resolve(VERSION.select("124", environ={}), read)
        self.assertEqual("a" * 40, result["resolved_ref"])
        read.return_value = ""
        with self.assertRaisesRegex(ValueError, "not published"):
            VERSION.resolve(VERSION.select("124", environ={}), read)
        read.return_value = "b" * 40 + "\trefs/heads/release/v1.24"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            VERSION.resolve(result, read)

    def test_conflicting_selectors_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            VERSION.select("124", environ={"AIF_SUBMODULE_BRANCH": "main"})

    def test_ado_update_pins_ref_and_validates_published_pipeline(self):
        script = (ROOT / "bootstrap/ADO-update-aifactory-and-run-project.sh").read_text(encoding="utf-8")
        self.assertIn(VERSION.CONTRACT, script)
        self.assertIn('version_default="${AIF_UPDATE_DEFAULT_VERSION:-124}"', script)
        self.assertIn('git -C "$SUBMODULE_PATH" checkout --detach "$AIF_SUBMODULE_REF"', script)
        self.assertNotIn("git submodule update --init --recursive --remote", script)
        self.assertIn('aif_version_save "$REPO_ROOT"', script)
        self.assertIn('validate_pipeline_preview "$state_dir/published-preview-request.json"', script)
        self.assertLess(script.index('validate_pipeline_preview "$state_dir/published-preview-request.json"'),
                        script.index('> "$state_dir/run.json"'))

    def test_create_contract_honors_same_exact_ref(self):
        script = (ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
        self.assertIn(VERSION.CONTRACT, script)
        self.assertIn('source "$AIF_SCALESET_LIB_DIR/release_version.sh"', script)
        self.assertIn('aif_version_prepare "$AIF_REPO_ROOT" false "$AIF_NON_INTERACTIVE"', script)
        self.assertIn('git -C azure-enterprise-scale-ml checkout --detach "$AIF_SUBMODULE_REF"', script)
        self.assertNotIn('git -C azure-enterprise-scale-ml checkout "$AIF_SUBMODULE_BRANCH"', script)
        self.assertIn('--root "$AIF_REPO_ROOT" --save', script)

    def test_ado_verification_run_can_skip_all_destructive_cleanup_tasks(self):
        root = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines"
        steps = yaml.safe_load((root / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8"))["steps"]
        matched = []
        for step in steps:
            name = step.get("displayName", "")
            if any(word in name.lower() for word in ("delete", "cleanup", "orphan", "purge")) and not name.startswith("06c2_"):
                self.assertIn("ne(variables['skipCleanup'], 'true')", step["condition"], name)
                matched.append(name)
        self.assertEqual(10, len(matched))
        variables = yaml.safe_load((root / "variables/variables.yaml").read_text(encoding="utf-8"))["variables"]
        self.assertEqual("false", variables["skipCleanup"])

    def test_ado_default_target_does_not_use_empty_allowed_value(self):
        path = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-genai.yaml"
        params = {p["name"]: p for p in yaml.safe_load(path.read_text(encoding="utf-8"))["parameters"]}
        self.assertEqual("", params["deploymentTarget"]["default"])
        self.assertNotIn("", params["deploymentTarget"].get("values", []))


if __name__ == "__main__":
    unittest.main()
