"""Opt-in policy for an attended ACS/Teams audio bridge, not an unattended bot."""
from __future__ import annotations

import re
from ipaddress import IPv6Address
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_meeting_url(value: str) -> str:
    """Validate syntax only. Never resolve, redirect, or fetch a supplied meeting URL."""
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise ValueError("A Teams meeting URL is required.")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError("The meeting URL contains unsafe characters.")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc not in {"teams.microsoft.com", "teams.cloud.microsoft"}
            or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("An HTTPS Teams meeting URL without credentials or fragment is required.")
    if not (re.fullmatch(r"/meet/[0-9]{3,30}", parsed.path)
            or re.fullmatch(r"/l/meetup-join/[A-Za-z0-9_%@.:-]{1,2048}/0", parsed.path)):
        raise ValueError("Only Teams meeting join links are supported.")
    return value


class MeetingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    meeting_url: str = Field(max_length=4096, repr=False)
    meeting_tenant_id: UUID | None = Field(
        default=None, description="Explicit Teams meeting tenant; omitted means the deployment tenant.",
    )
    external_audience_disclosure_approved: bool = Field(
        default=False, strict=True,
        description="Operator approval to disclose this meeting-safe scope to the exact external roster; not app access.",
    )
    meeting_safe_knowledge: bool = Field(
        default=False,
        description="Operator approval that ALL knowledge readable in this exact scope is safe for ALL meeting attendees.",
    )
    allowed_participant_object_ids: list[UUID] = Field(
        default_factory=list, max_length=32,
        description="Exact operator-verified Teams roster IDs in the meeting tenant; not voice authentication or app grants.",
    )

    @field_validator("meeting_tenant_id")
    @classmethod
    def nonzero_meeting_tenant(cls, value):
        if value is not None and not value.int:
            raise ValueError("An explicit meeting tenant must be a nonzero tenant ID.")
        return value

    @field_validator("allowed_participant_object_ids")
    @classmethod
    def distinct_listeners(cls, value):
        if len(set(value)) != len(value) or any(not participant.int for participant in value):
            raise ValueError("Meeting listeners must be distinct, nonzero object IDs.")
        return value

    @field_validator("meeting_url")
    @classmethod
    def meeting_link(cls, value):
        return validate_meeting_url(value)

    @model_validator(mode="after")
    def explicit_external_disclosure(self):
        if self.external_audience_disclosure_approved and (
            self.meeting_tenant_id is None or not self.meeting_safe_knowledge
            or not self.allowed_participant_object_ids
        ):
            raise ValueError("External meeting disclosure requires an explicit tenant, shared-knowledge approval and roster.")
        return self


class TeamsMeetingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    acs_endpoint: str | None = None
    managed_identity_client_id: UUID | None = None
    connect_origins: list[str] = Field(
        default_factory=list, max_length=64,
        description="Exact operator-reviewed HTTPS/WSS signaling origins for this deployment; no wildcards or scheme-wide CSP.",
    )
    allowed_host_object_ids: list[UUID] = Field(default_factory=list, max_length=100)
    policies: list[MeetingPolicy] = Field(default_factory=list, max_length=100)
    display_name: str = Field(default="ESAF AI meeting assistant", min_length=1, max_length=100)
    voice_mode: Literal["inherit", "realtime"] = Field(
        default="inherit", description="Meeting-only profile; realtime reuses the configured native model and governed grounding.",
    )
    full_duplex: bool = Field(
        default=False, strict=True, description="Keep meeting input capture active during playback for server-owned interruption.",
    )
    max_session_seconds: int = Field(default=900, ge=60, le=3600)
    lobby_timeout_seconds: int = Field(default=120, ge=10, le=300)
    max_concurrent_sessions: int = Field(default=4, ge=1, le=32)

    @field_validator("acs_endpoint")
    @classmethod
    def acs_url(cls, value):
        if value is None:
            return None
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if not re.fullmatch(rf"https://{label}(?:\.{label})?\.communication\.azure\.com/?", value):
            raise ValueError("ACS must be an Azure Communication Services HTTPS resource endpoint.")
        return value.rstrip("/")

    @field_validator("display_name")
    @classmethod
    def safe_name(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("The display name cannot contain control characters.")
        return value

    @field_validator("connect_origins")
    @classmethod
    def safe_connect_origins(cls, value):
        normalized = []
        for origin in value:
            if (not origin or len(origin) > 512 or any(ord(char) <= 32 for char in origin)
                    or any(char in origin for char in ("*", "\\", "?", "#", "%"))):
                raise ValueError("Meeting connection origins must be exact HTTPS/WSS origins.")
            parsed = urlsplit(origin)
            host = parsed.hostname
            if (parsed.scheme not in {"https", "wss"} or not host
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in {"", "/"} or parsed.port not in {None, 443}
                    or parsed.netloc.endswith(":")):
                raise ValueError("Meeting origins permit only HTTPS/WSS, port 443, and no credentials or paths.")
            authority = f"[{host}]" if ":" in host else host
            if parsed.netloc.lower() not in {authority, authority + ":443"}:
                raise ValueError("Meeting connection origins contain an ambiguous authority.")
            if ":" in host:
                host = f"[{IPv6Address(host)}]"
            elif (len(host) > 253 or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            )):
                raise ValueError("Meeting connection origins require a valid exact hostname.")
            normalized.append(f"{parsed.scheme}://{host}")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Meeting connection origins must be distinct.")
        return normalized

    @model_validator(mode="after")
    def explicit_policy(self):
        if self.enabled and not (self.acs_endpoint and self.allowed_host_object_ids and self.policies and self.connect_origins):
            raise ValueError("Enabled meetings require an ACS endpoint, explicit hosts, meeting policies and network origins.")
        if self.enabled and any(not policy.meeting_safe_knowledge for policy in self.policies):
            raise ValueError("Every meeting policy needs explicit shared-knowledge disclosure approval.")
        if self.enabled and any(not policy.allowed_participant_object_ids for policy in self.policies):
            raise ValueError("Every enabled meeting policy requires an explicit listener allowlist.")
        if (len(set(self.allowed_host_object_ids)) != len(self.allowed_host_object_ids)
                or any(not host.int for host in self.allowed_host_object_ids)):
            raise ValueError("Meeting hosts must be distinct, nonzero object IDs.")
        if len({policy.id for policy in self.policies}) != len(self.policies):
            raise ValueError("Meeting policy IDs must be distinct.")
        if len({(policy.meeting_url, policy.scope_key) for policy in self.policies}) != len(self.policies):
            raise ValueError("Meeting/scope policy pairs must be distinct.")
        return self
