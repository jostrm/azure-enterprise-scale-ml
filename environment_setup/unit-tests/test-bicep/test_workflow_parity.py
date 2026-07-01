from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
GHA_COMMON = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml"
GHA_PROJECT = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml"

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


if __name__ == "__main__":
    unittest.main()
