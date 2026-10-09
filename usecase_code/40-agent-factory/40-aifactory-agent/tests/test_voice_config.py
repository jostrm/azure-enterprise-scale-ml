"""Configuration contract for the optional live voice feature: closed schema, safe defaults, fail-closed endpoint."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aifactory_agent.config import Settings
from aifactory_agent.voice_settings import VoiceSettings

ROOT = Path(__file__).parents[1]


def example(**voice):
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    if voice:
        config["voice"] = voice
    return config


def test_live_voice_is_off_by_default_and_visible_in_the_code_sample():
    sample = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    assert sample["voice"]["enabled"] is False
    settings = Settings.model_validate(sample)
    assert settings.voice == VoiceSettings()
    assert settings.voice.enabled is False
    assert Settings.model_validate({k: v for k, v in sample.items() if k != "voice"}).voice.enabled is False


def test_defaults_are_a_speech_shell_with_a_hd_voice_and_a_bounded_session():
    voice = VoiceSettings()
    assert voice.api_version == "2026-04-10" and voice.token_scope == "https://ai.azure.com/.default"
    assert voice.voice_name == "en-US-Ava:DragonHDLatestNeural" and voice.input_languages == ["en-US"]
    assert voice.turn_detection == "azure_semantic_vad" and voice.noise_suppression and voice.echo_cancellation
    assert 60 <= voice.max_session_seconds < 3600 and voice.idle_timeout_seconds < voice.max_session_seconds
    assert voice.endpoint is None


def test_a_complete_swedish_and_english_configuration_is_accepted():
    settings = Settings.model_validate(example(
        enabled=True, voice_name="en-US-AvaMultilingualNeural", input_languages=["sv-SE", "en-US"],
        turn_detection="azure_semantic_vad_multilingual", max_session_seconds=600, model="gpt-4.1-nano",
        endpoint="https://aif2bltscaae001dev.services.ai.azure.com/",
    ))
    assert settings.voice.enabled and settings.voice.input_languages == ["sv-SE", "en-US"]
    assert settings.voice.endpoint == "https://aif2bltscaae001dev.services.ai.azure.com"


@pytest.mark.parametrize("field,value", [
    ("surprise", True),
    ("turn_detection", "client_vad"),
    ("token_scope", "https://management.azure.com/.default"),
    ("api_version", "latest"),
    ("model", "gpt 4"),
    ("voice_name", "en-US-Ava; DROP"),
    ("input_languages", []),
    ("input_languages", ["en-US", "en-US"]),
    ("input_languages", ["not a locale"]),
    ("input_languages", [f"x{i}-US" for i in range(11)]),
    ("max_session_seconds", 59),
    ("max_session_seconds", 3600),
    ("idle_timeout_seconds", 5),
    ("max_concurrent_sessions", 0),
    ("max_spoken_characters", 50),
    ("silence_duration_ms", 20),
])
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        VoiceSettings.model_validate({field: value})


@pytest.mark.parametrize("endpoint", [
    "http://aif.services.ai.azure.com",
    "https://evil.example.com",
    "https://aif.services.ai.azure.com.evil.example.com",
    "https://aif.openai.azure.com",
    "https://user:pw@aif.services.ai.azure.com",
    "https://aif.services.ai.azure.com:8443",
    "https://aif.services.ai.azure.com/voice-live",
    "https://aif.services.ai.azure.com?x=1",
    "https://aif.services.ai.azure.com#frag",
    "wss://aif.services.ai.azure.com",
    "https://169.254.169.254",
])
def test_endpoint_must_be_a_plain_https_azure_ai_host(endpoint):
    with pytest.raises(ValidationError):
        VoiceSettings(endpoint=endpoint)


def test_legacy_cognitive_services_domains_are_accepted_for_older_resources():
    assert VoiceSettings(endpoint="https://old.cognitiveservices.azure.com").endpoint == "https://old.cognitiveservices.azure.com"


def test_idle_timeout_must_be_shorter_than_the_session_limit():
    with pytest.raises(ValidationError):
        VoiceSettings(max_session_seconds=60, idle_timeout_seconds=120)


def test_the_greeting_has_a_friendly_default_and_can_be_switched_off():
    assert VoiceSettings().greeting == "Factory Agent online. How can I help?"
    assert VoiceSettings(greeting=None).greeting is None and VoiceSettings(greeting="").greeting == ""
    with pytest.raises(ValidationError):
        VoiceSettings(greeting="x" * 201)


def test_voice_block_does_not_change_other_settings_equality():
    base = Settings.model_validate(example())
    enabled = Settings.model_validate(example(enabled=True))
    assert base != enabled
    assert enabled.model_copy(update={"voice": VoiceSettings()}) == base
