from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GHA_COMMON = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml"
GHA_PROJECT = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml"
GHA_PROJECT_PHASE = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml"
ADO_PROJECT_JOB = ROOT / (
    "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/"
    "esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
)

FORBIDDEN_NETWORK_KEYS = {"network_env_dev", "network_env_stage", "network_env_prod"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains_forbidden_network_keys(content: str) -> list[str]:
    return [k for k in FORBIDDEN_NETWORK_KEYS if k in content]


def _env_value(content: str, key: str) -> str | None:
    for line in content.splitlines():
        if line.strip().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return None


def _section(content: str, start: str, end: str) -> str:
    start_index = content.index(start)
    end_index = content.index(end, start_index)
    return content[start_index:end_index]


class TestWorkflowParity(unittest.TestCase):
    def test_common_has_single_network_env(self) -> None:
        content = _read_text(GHA_COMMON)
        forbidden = _contains_forbidden_network_keys(content)
        self.assertFalse(forbidden, msg=f"infra-common.yml contains forbidden keys: {forbidden}")
        net = _env_value(content, "network_env")
        self.assertIsNotNone(net, msg="infra-common.yml missing network_env")

    def test_project_has_single_network_env(self) -> None:
        content = _read_text(GHA_PROJECT)
        forbidden = _contains_forbidden_network_keys(content)
        self.assertFalse(forbidden, msg=f"infra-project.yml contains forbidden keys: {forbidden}")
        net = _env_value(content, "network_env")
        self.assertIsNotNone(net, msg="infra-project.yml missing network_env")

    def test_env_names_match_job_env_common(self) -> None:
        content = _read_text(GHA_COMMON)
        # basic sanity: dev job env set to dev, stage job env set to stage, prod job env set to prod
        for expected in ("dev", "test", "prod"):
            self.assertIn(f"dev_test_prod: {expected}", content, msg=f"infra-common.yml missing dev_test_prod {expected}")

    def test_env_names_project_present(self) -> None:
        content = _read_text(GHA_PROJECT)
        # env block should expose dev_test_prod
        self.assertIn("dev_test_prod:", content, msg="infra-project.yml missing dev_test_prod")

    def test_orphan_cleanup_is_project_owned_in_both_rgs_and_fail_safe(self) -> None:
        cases = (
            (
                ADO_PROJECT_JOB,
                "displayName: 'Check and Delete Current Project Orphan Role Assignments'",
                "displayName: '61-foundation'",
            ),
            (
                GHA_PROJECT_PHASE,
                "- name: Check and Delete Current Project Orphan Role Assignments",
                "# === Deploy sequences ===",
            ),
        )
        for path, start, end in cases:
            with self.subTest(path=path):
                cleanup = _section(_read_text(path), start, end)
                self.assertIn("cleanup-project-orphan-roles.py", cleanup)
                self.assertIn("ORPHAN_PROJECT_NUMBER", cleanup)
                self.assertIn("ORPHAN_COMMON_RG", cleanup)
                self.assertNotIn("ORPHAN_PROJECT_ENTRA_IDS", cleanup)
                self.assertNotIn("technical_admins_ad_object_id", cleanup)
                self.assertNotIn("principalName==null", cleanup)
                self.assertNotIn("role assignment delete", cleanup)

    def test_cleanup_custom_rg_bindings_do_not_use_byo_network_scope(self) -> None:
        mappings = {
            "ORPHAN_COMMON_RG": "commonResourceGroup_param",
            "ORPHAN_COMMON_NAME": "vnetResourceGroupBase",
            "ORPHAN_RG_PREFIX": "admin_aifactoryPrefixRG",
            "ORPHAN_RG_SUFFIX": "admin_aifactorySuffixRG",
            "ORPHAN_PROJECT_PREFIX": "projectPrefix",
            "ORPHAN_PROJECT_SUFFIX": "projectSuffix",
            "ORPHAN_LOCATION_SUFFIX": "admin_locationSuffix",
            "ORPHAN_ENV": "dev_test_prod",
            "ORPHAN_PROJECT_NUMBER": "project_number_000",
        }
        ado = _section(
            _read_text(ADO_PROJECT_JOB), "displayName: 'Check and Delete Current Project Orphan Role Assignments'",
            "displayName: '61-foundation'",
        )
        gha = _section(
            _read_text(GHA_PROJECT_PHASE), "- name: Check and Delete Current Project Orphan Role Assignments",
            "# === Deploy sequences ===",
        )
        for target, source in mappings.items():
            with self.subTest(target=target):
                self.assertEqual(f"$({source})", _env_value(ado, target))
                self.assertEqual("${{ env." + source + " }}", _env_value(gha, target))
        for cleanup in (ado, gha):
            self.assertNotIn("vnetResourceGroup_resolved", cleanup)
            self.assertNotIn("vnetResourceGroup_param", cleanup)
            self.assertNotIn("admin_commonResourceSuffix", cleanup)


if __name__ == "__main__":
    unittest.main()
