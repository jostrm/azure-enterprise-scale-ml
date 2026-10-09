"""Contract for the AI Factory Agent live voice flag and inputs (templates, inventory and adjacency to the chat flag).

The chat flag itself (enableFactoryChatAgent) is covered in test_factory_chat_agent_flag.py; the late foundry-phase
pipeline step that consumes the voice flag is covered in test_agent_live_voice_pipeline.py.
"""
from __future__ import annotations

import json

import pytest

from base.config import REPO_ROOT, GH_ENV_TEMPLATE, ADO_VARIABLES_YAML, env_defaults, yaml_defaults
from domain.pipeline_contracts import CONFIG_ONLY_EXCEPTIONS, EXTRA_FEATURES, FEATURES

CHAT = ("enableFactoryChatAgent", "ENABLE_FACTORY_CHAT_AGENT")
FLAGS = {
    "enableAIFactoryAgentLiveVoice": "ENABLE_AI_FACTORY_AGENT_LIVE_VOICE",
}
INPUTS = {
    "aifactoryAgentEntraAppId": "AIFACTORY_AGENT_ENTRA_APP_ID",
    "aifactoryAgentContainerAppsEnvironment": "AIFACTORY_AGENT_CONTAINER_APPS_ENVIRONMENT",
    "aifactoryAgentReaderObjectIds": "AIFACTORY_AGENT_READER_OBJECT_IDS",
    "aifactoryAgentVoiceName": "AIFACTORY_AGENT_VOICE_NAME",
    "aifactoryAgentVoiceLanguages": "AIFACTORY_AGENT_VOICE_LANGUAGES",
}
VARIABLES_JSON = REPO_ROOT / "environment_setup/aifactory/variables.json"


@pytest.mark.parametrize("name,public,default", [
    *((flag, public, "false") for flag, public in FLAGS.items()),
    *((name, public, "") for name, public in INPUTS.items()),
])
def test_every_template_declares_the_exact_setting_with_safe_default(name, public, default):
    assert json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))["dev"][name] == default
    assert yaml_defaults()[name] == default
    assert env_defaults()[public] == default


def test_flags_are_reviewed_pipeline_features_not_configuration_only():
    assert {**FEATURES, **EXTRA_FEATURES}.items() >= {public: flag for flag, public in FLAGS.items()}.items()
    assert not set(FLAGS.values()) & set(CONFIG_ONLY_EXCEPTIONS)


def _json_keys():
    return list(json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))["dev"])


def _line_keys(path, separator):
    keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and separator in stripped:
            keys.append(stripped.split(separator, 1)[0].strip())
    return keys


@pytest.mark.parametrize("keys", [
    pytest.param(_json_keys, id="variables.json"),
    pytest.param(lambda: _line_keys(ADO_VARIABLES_YAML, ":"), id="variables.yaml"),
    pytest.param(lambda: _line_keys(GH_ENV_TEMPLATE, "="), id="env.template"),
])
def test_live_voice_flag_sits_directly_after_the_chat_flag_in_every_template(keys):
    names = keys()
    chat, voice = (
        (CHAT[0], "enableAIFactoryAgentLiveVoice") if CHAT[0] in names else (CHAT[1], "ENABLE_AI_FACTORY_AGENT_LIVE_VOICE")
    )
    assert names.index(voice) == names.index(chat) + 1


def test_flag_comments_state_dependencies_and_never_delete():
    yaml_text = ADO_VARIABLES_YAML.read_text(encoding="utf-8")
    env_text = GH_ENV_TEMPLATE.read_text(encoding="utf-8")
    for text, chat, voice in (
        (yaml_text, CHAT[0], "enableAIFactoryAgentLiveVoice"),
        (env_text, CHAT[1], "ENABLE_AI_FACTORY_AGENT_LIVE_VOICE"),
    ):
        voice_line = next(line for line in text.splitlines() if line.lstrip().startswith(voice))
        chat_line = next(line for line in text.splitlines() if line.lstrip().startswith(chat))
        assert f"{chat}:'true'" in voice_line, "live voice must state that it requires the chat flag"
        assert "never deletes" in chat_line and "never deletes" in voice_line
        assert "does not remove the voice roles" in voice_line
