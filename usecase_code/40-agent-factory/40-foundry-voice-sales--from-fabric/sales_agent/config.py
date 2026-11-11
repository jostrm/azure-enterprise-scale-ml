from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
NATIVE_MODELS = {"gpt-realtime", "gpt-realtime-mini", "gpt-realtime-datazone"}


class ConfigurationError(ValueError):
    pass


def _required(values, key):
    value = values.get(key, "").strip()
    if not value or "<" in value or ">" in value:
        raise ConfigurationError(f"Set {key} in the selected .env file.")
    return value


def _guid(values, key, optional=False):
    if optional and not values.get(key, "").strip():
        return ""
    value = _required(values, key)
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be a GUID.") from exc


def _url(value, key):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.netloc != parsed.hostname
            or "%" in value or "\\" in value):
        raise ConfigurationError(f"{key} must be an HTTPS service URL without credentials, port or query.")
    return parsed


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    subscription_id: str
    project_endpoint: str
    agent_name: str
    agent_version: str
    fabric_url: str
    model_deployment: str = ""
    expected_user: str = ""
    resource_group: str = ""
    team_group_id: str = ""
    mcp_tool_name: str = ""
    mcp_question_argument: str = ""
    voice_enabled: bool = False
    voice_endpoint: str = ""
    voice_model: str = ""
    voice_name: str = ""
    voice_api_version: str = "2026-07-15"
    domain_path: Path = ROOT / "config" / "domain.json"

    @classmethod
    def from_mapping(cls, values, *, base_dir=ROOT, publication=False, allow_unpublished=False):
        tenant, subscription = _guid(values, "AZURE_TENANT_ID"), _guid(values, "AZURE_SUBSCRIPTION_ID")
        endpoint = _required(values, "FOUNDRY_PROJECT_ENDPOINT").rstrip("/")
        project = _url(endpoint, "FOUNDRY_PROJECT_ENDPOINT")
        if (not re.fullmatch(r"[a-z0-9-]+\.services\.ai\.azure\.com", project.hostname)
                or not re.fullmatch(r"/api/projects/[A-Za-z0-9_.-]+", project.path)):
            raise ConfigurationError("FOUNDRY_PROJECT_ENDPOINT must identify a Foundry project.")
        name = _required(values, "FOUNDRY_AGENT_NAME")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", name):
            raise ConfigurationError("FOUNDRY_AGENT_NAME contains unsupported characters.")
        version = values.get("FOUNDRY_AGENT_VERSION", "").strip() if publication or allow_unpublished else _required(
            values, "FOUNDRY_AGENT_VERSION"
        )
        if version and not re.fullmatch(r"[1-9][0-9]*", version):
            raise ConfigurationError("FOUNDRY_AGENT_VERSION must be a specific positive version, not latest.")
        model = values.get("FOUNDRY_MODEL_DEPLOYMENT", "").strip()
        if publication:
            model = _required(values, "FOUNDRY_MODEL_DEPLOYMENT")
        fabric_url = _required(values, "FABRIC_MCP_URL").rstrip("/")
        fabric = _url(fabric_url, "FABRIC_MCP_URL")
        match = re.fullmatch(
            r"/v1/mcp/workspaces/([0-9a-f-]{36})/dataagents/([0-9a-f-]{36})/agent", fabric.path
        )
        if not match:
            raise ConfigurationError("FABRIC_MCP_URL must be the published Data Agent MCP URL, not Fabric Core.")
        try:
            workspace, _ = (UUID(part) for part in match.groups())
        except ValueError as exc:
            raise ConfigurationError("FABRIC_MCP_URL must contain valid workspace and Data Agent GUIDs.") from exc
        workspace_host = f"{workspace.hex}.z{workspace.hex[:2]}.w.api.fabric.microsoft.com"
        if fabric.hostname not in {"api.fabric.microsoft.com", workspace_host}:
            raise ConfigurationError("FABRIC_MCP_URL host does not match the configured Fabric workspace.")
        enabled = values.get("VOICE_ENABLED", "false").strip().lower()
        if enabled not in {"true", "false"}:
            raise ConfigurationError("VOICE_ENABLED must be true or false.")
        voice_endpoint = values.get("VOICE_ENDPOINT", "").strip().rstrip("/")
        voice_model = values.get("VOICE_MODEL", "").strip()
        voice_name = values.get("VOICE_NAME", "").strip()
        voice_version = values.get("VOICE_API_VERSION", "2026-07-15").strip()
        if enabled == "true":
            voice = _url(_required(values, "VOICE_ENDPOINT"), "VOICE_ENDPOINT")
            if (not re.fullmatch(r"[a-z0-9-]+\.services\.ai\.azure\.com", voice.hostname)
                    or voice.path not in {"", "/"}):
                raise ConfigurationError("VOICE_ENDPOINT must be the Foundry account root URL.")
            if voice_model not in NATIVE_MODELS:
                raise ConfigurationError("VOICE_MODEL must be a documented native realtime model; see .env.example.")
            if voice_name not in {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"}:
                raise ConfigurationError("VOICE_NAME must select a supported OpenAI native voice.")
            if voice_version != "2026-07-15":
                raise ConfigurationError("This client implements VOICE_API_VERSION=2026-07-15 only.")
        path = Path(values.get("DOMAIN_CONFIG_PATH", "config/domain.json")).expanduser()
        if not path.is_absolute():
            path = Path(base_dir) / path
        settings = cls(
            tenant, subscription, endpoint, name, version, fabric_url, model,
            values.get("AZURE_EXPECTED_USER", "").strip(), values.get("AZURE_RESOURCE_GROUP", "").strip(),
            _guid(values, "TEAM_GROUP_ID", optional=True),
            values.get("MCP_TOOL_NAME", "").strip(), values.get("MCP_QUESTION_ARGUMENT", "").strip(),
            enabled == "true", voice_endpoint, voice_model, voice_name, voice_version, path.resolve(),
        )
        settings.domain_instructions()
        return settings

    @classmethod
    def load(cls, env_file: Path, *, publication=False, allow_unpublished=False):
        from dotenv import dotenv_values

        env_file = env_file.expanduser().resolve()
        if not env_file.is_file():
            raise ConfigurationError("Selected .env file is missing; copy .env.example and fill its placeholders.")
        # The explicitly selected file owns deployment identity, not unrelated shell credentials.
        values = {key: value or "" for key, value in dotenv_values(env_file, interpolate=False).items()}
        return cls.from_mapping(values, base_dir=env_file.parent, publication=publication,
                                allow_unpublished=allow_unpublished)

    def domain_instructions(self):
        try:
            raw = self.domain_path.read_text(encoding="utf-8")
            if len(raw) > 32768:
                raise ConfigurationError("Domain configuration exceeds 32 KiB.")
            domain = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError("Cannot read DOMAIN_CONFIG_PATH as a JSON object.") from exc
        if (not isinstance(domain, dict) or set(domain) != {"instructions", "schema_mappings"}
                or not isinstance(domain["instructions"], str)
                or not isinstance(domain["schema_mappings"], dict)):
            raise ConfigurationError("Domain config needs instructions (string) and schema_mappings (object).")
        return domain["instructions"] + "\nOperator-provided schema mappings:\n" + json.dumps(
            domain["schema_mappings"], ensure_ascii=True
        )
