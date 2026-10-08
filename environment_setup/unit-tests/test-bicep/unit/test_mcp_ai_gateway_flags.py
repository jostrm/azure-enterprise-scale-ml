"""Configuration contract for the AI Factory MCP and new AI Gateway SKU opt-in flags."""
from __future__ import annotations

import json

import pytest

from base.config import REPO_ROOT, env_defaults, yaml_defaults
from domain.pipeline_contracts import (
    ADO_ROOT, CONFIG_ONLY_EXCEPTIONS, CONFIG_ONLY_SETTINGS, FEATURES, GHA_COMMON, GHA_PHASE,
    load_pipeline,
)

FLAGS = {
    "enableAIFactoryMCP": "ENABLE_AI_FACTORY_MCP",
    "enableAIGatewaySKU": "ENABLE_AI_GATEWAY_SKU",
    "addAIFactoryMCP2AIGatewaySKU": "ADD_AI_FACTORY_MCP_2_AI_GATEWAY_SKU",
}
VARIABLES_JSON = REPO_ROOT / "environment_setup/aifactory/variables.json"


@pytest.mark.parametrize("flag,public", FLAGS.items())
def test_every_template_declares_the_exact_flag_disabled(flag, public):
    assert json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))["dev"][flag] == "false"
    assert yaml_defaults()[flag] == "false"
    assert env_defaults()[public] == "false"


@pytest.mark.parametrize("flag,public", FLAGS.items())
def test_flags_are_reviewed_configuration_only_and_never_bound(flag, public):
    inventory = {**FEATURES, **{name: runtime for name, (runtime, _) in CONFIG_ONLY_SETTINGS.items()}}
    assert inventory[public] == flag
    reason = CONFIG_ONLY_EXCEPTIONS.get(public) or CONFIG_ONLY_SETTINGS[public][1]
    assert "project001" in reason and "Dev" in reason
    for path in (GHA_COMMON, GHA_PHASE):
        assert all(flag not in job.get("env", {}) for job in load_pipeline(path)["jobs"].values())
    for pipeline in ADO_ROOT.rglob("*.yaml"):
        if pipeline.name != "variables.yaml":
            assert flag not in pipeline.read_text(encoding="utf-8"), pipeline


def test_configuration_only_settings_keep_canonical_false_defaults():
    for public, (runtime, reason) in CONFIG_ONLY_SETTINGS.items():
        assert reason.strip()
        assert env_defaults()[public] == yaml_defaults()[runtime] == "false"
