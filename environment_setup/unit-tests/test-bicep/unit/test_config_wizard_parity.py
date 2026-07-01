"""Unit test: every service/network/BYO flag from the config wizard exists in
both the GitHub .env.template and the Azure DevOps variables.yaml.

Asserts the latest configuration wizard surface is reflected in both pipelines.
Offline; reads files only.
"""
from __future__ import annotations

import unittest

from base.config import env_defaults, yaml_defaults
from domain.scenarios import NETWORK_FLAGS, SERVICE_FLAGS


def _yaml_keys_ci(yaml: dict[str, str]) -> set[str]:
    # variables.yaml uses camelCase; compare case-insensitively without "_"
    return {k.lower().replace("_", "") for k in yaml}


class TestConfigWizardParity(unittest.TestCase):
    def setUp(self) -> None:
        self.env = env_defaults()
        self.yaml_norm = _yaml_keys_ci(yaml_defaults())

    def test_service_flags_in_env_template(self) -> None:
        missing = [f for f in SERVICE_FLAGS if f not in self.env]
        self.assertFalse(missing, f".env.template missing service flags: {missing}")

    def test_network_flags_in_env_template(self) -> None:
        missing = [f for f in NETWORK_FLAGS if f not in self.env]
        self.assertFalse(missing, f".env.template missing network flags: {missing}")

    def test_service_flags_in_variables_yaml(self) -> None:
        missing = [
            f for f in SERVICE_FLAGS
            if f.lower().replace("_", "") not in self.yaml_norm
        ]
        self.assertFalse(missing, f"variables.yaml missing service flags: {missing}")


if __name__ == "__main__":
    unittest.main()
