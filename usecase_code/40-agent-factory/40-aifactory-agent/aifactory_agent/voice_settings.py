"""Settings for the optional live voice feature (Azure Voice Live as a speech shell).

Kept free of other package imports so config.py can import it without cycles. Everything here is closed and
fail-closed: the backend presents a managed-identity token to the configured host, so the endpoint may only be a
plain HTTPS Azure AI resource host.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_TOKEN_SCOPE = "https://ai.azure.com/.default"
LEGACY_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
DEFAULT_VOICE = "en-US-Ava:DragonHDLatestNeural"
_HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\.(?:services\.ai|cognitiveservices)\.azure\.com")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Code-level mirror of the pipeline switch enableAIFactoryAgentLiveVoice / ENABLE_AI_FACTORY_AGENT_LIVE_VOICE.
    enabled: bool = False
    api_version: str = Field(default="2026-04-10", pattern=r"^\d{4}-\d{2}-\d{2}(?:-preview)?$")
    # Voice Live bills by the tier of this model even though it never writes an answer (speech shell), so use a lite one.
    model: str = Field(default="gpt-4.1-nano", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    endpoint: str | None = None
    token_scope: Literal["https://ai.azure.com/.default", "https://cognitiveservices.azure.com/.default"] = DEFAULT_TOKEN_SCOPE
    voice_name: str = Field(default=DEFAULT_VOICE, pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{1,99}$")
    voice_temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    input_languages: list[str] = Field(default_factory=lambda: ["en-US"], min_length=1, max_length=10)
    turn_detection: Literal["azure_semantic_vad", "azure_semantic_vad_multilingual", "server_vad"] = "azure_semantic_vad"
    silence_duration_ms: int = Field(default=500, ge=100, le=3000)
    noise_suppression: bool = True
    echo_cancellation: bool = True
    max_session_seconds: int = Field(default=900, ge=60, lt=3600)
    idle_timeout_seconds: int = Field(default=120, ge=15, le=1800)
    max_concurrent_sessions: int = Field(default=4, ge=1, le=100)
    max_spoken_characters: int = Field(default=1200, ge=200, le=4000)
    answer_timeout_seconds: int = Field(default=120, ge=10, le=300)
    # Spoken once when a session starts (also proves the audio path works). null or "" disables it.
    greeting: str | None = Field(default="Factory Agent online. How can I help?", max_length=200)
    # Browsers must call from the app's own origin; list extra HTTPS origins only when a front door rewrites Host.
    allowed_origins: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("endpoint")
    @classmethod
    def azure_ai_host_only(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError:
            port = -1
        hostname = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not _HOST.fullmatch(hostname) or parsed.username or parsed.password
                or port is not None or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("The voice endpoint must be https://<resource>.services.ai.azure.com "
                             "(or the legacy .cognitiveservices.azure.com) without credentials, port, path, query or fragment.")
        return f"https://{hostname}"

    @field_validator("input_languages")
    @classmethod
    def distinct_locales(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or not all(_LANGUAGE.fullmatch(item) for item in value):
            raise ValueError("Input languages must be distinct BCP-47 codes such as en-US or sv-SE.")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def https_origins(cls, value: list[str]) -> list[str]:
        origins = []
        for item in value:
            parsed = urlsplit(item)
            try:
                parsed.port
            except ValueError:
                raise ValueError("Allowed origins must be plain HTTPS origins such as https://agent.example.com.")
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
                raise ValueError("Allowed origins must be plain HTTPS origins such as https://agent.example.com.")
            origins.append(f"https://{parsed.netloc.lower()}")
        if len(set(origins)) != len(origins):
            raise ValueError("Allowed origins must be distinct.")
        return origins

    @model_validator(mode="after")
    def idle_before_limit(self):
        if self.idle_timeout_seconds >= self.max_session_seconds:
            raise ValueError("The idle timeout must be shorter than the maximum session length.")
        return self


def effective_endpoint(voice: VoiceSettings, foundry_account: str) -> str:
    """The configured host, or the project's own Foundry resource (no new resource is created for speech)."""
    return voice.endpoint or f"https://{foundry_account.lower()}.services.ai.azure.com"
