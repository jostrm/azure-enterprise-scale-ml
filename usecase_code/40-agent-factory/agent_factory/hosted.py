"""Deterministic source packaging and persistent Foundry hosted-agent deployment."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .config import Target


ROOT = Path(__file__).resolve().parents[1]
HOSTED_ROOT = ROOT / "41-single-agent" / "hosted-agent"
FRAMEWORKS = frozenset({
    "agent-framework", "langgraph", "openai-agent-sdk", "anthropic-agents",
    "github-copilot-sdk", "custom", "multi-agent",
})
MANAGED_BY = "40-agent-factory"
OWNER_KEY = "aifactory.managed_by"
HASH_KEY = "aifactory.definition_hash"


class HostedPrerequisiteError(ValueError):
    """A required model, endpoint or persisted participant is unavailable."""


def _name(value: str) -> str:
    if (not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", value)
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", value)):
        raise ValueError("Agent names must be safe alphanumeric/hyphen names, at most 63 characters.")
    return value


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _normalize(spec: dict) -> dict:
    allowed = {
        "name", "kind", "framework", "instructions", "description",
        "metadata", "model", "members", "private_tools",
    }
    if not isinstance(spec, dict) or spec.keys() - allowed:
        raise ValueError("Only documented hosted spec fields are accepted; never supply credentials or env.")
    if spec.get("kind", "hosted") != "hosted":
        raise ValueError("deploy_hosted accepts hosted catalog entries only.")
    name = _name(spec.get("name"))
    framework = spec.get("framework")
    if framework not in FRAMEWORKS:
        raise ValueError(f"Unsupported hosted framework: {framework!r}")
    instructions = spec.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("Hosted agents require nonempty instructions.")
    description = spec.get("description", "")
    if not isinstance(description, str):
        raise ValueError("description must be a string.")
    metadata = dict(spec.get("metadata") or {})
    if metadata.get(OWNER_KEY, MANAGED_BY) != MANAGED_BY:
        raise ValueError("Cannot assign another owner's metadata.")
    metadata.pop(HASH_KEY, None)
    metadata[OWNER_KEY] = MANAGED_BY
    metadata["aifactory.framework"] = framework
    metadata["aifactory.execution_kind"] = "hosted"
    if len(metadata) > 15 or any(
        not isinstance(k, str) or not isinstance(v, str) or not k or len(k) > 64 or len(v) > 512
        for k, v in metadata.items()
    ):
        raise ValueError("Metadata must leave room for the definition hash: 16 pairs, keys 64, values 512.")
    model = spec.get("model", "")
    if not isinstance(model, str) or any(c in model for c in "\r\n"):
        raise ValueError("model must be a deployment name.")
    members = spec.get("members", [])
    if not isinstance(members, list) or len(members) > 6:
        raise ValueError("members must be a list of at most six persisted prompt agents.")
    normalized_members = []
    seen = {name.casefold()}
    for member in members:
        if not isinstance(member, dict) or member.keys() - {"name", "role"}:
            raise ValueError("Each member must have name and role only.")
        member_name = _name(member.get("name"))
        role = member.get("role", "")
        if not isinstance(role, str) or not role.strip() or len(role) > 512:
            raise ValueError("Each member requires a nonempty role of at most 512 characters.")
        if member_name.casefold() in seen:
            raise ValueError("Participants must be distinct and cannot reference the coordinator itself.")
        seen.add(member_name.casefold())
        normalized_members.append({"name": member_name, "role": role})
    if framework == "multi-agent" and len(normalized_members) < 2:
        raise HostedPrerequisiteError("multi-agent requires at least two separately persisted prompt agents.")
    if framework == "anthropic-agents" and not model.strip():
        raise HostedPrerequisiteError("Anthropic requires an explicit deployed compatible Claude model in spec.model.")
    private_tools = spec.get("private_tools", ["knowledge_base_retrieve"])
    if private_tools not in (["knowledge_base_retrieve"], ["knowledge_base_retrieve", "group_resource_list"]):
        raise ValueError("private_tools must contain only reviewed Foundry IQ and optional Azure inventory tools.")
    return {
        "name": name, "kind": "hosted", "framework": framework, "instructions": instructions,
        "description": description, "metadata": metadata, "model": model.strip(),
        "members": normalized_members,
        "private_tools": list(private_tools),
    }


def build_package(spec: dict, output_dir: Path) -> Path:
    """Build an allowlisted, byte-reproducible ZIP; no SDK or Azure access needed."""
    normalized = _normalize(spec)
    source = (ROOT / "42-multi-agent" if normalized["framework"] == "multi-agent"
              else HOSTED_ROOT / normalized["framework"])
    files = {
        "main.py": source / "main.py",
        "requirements.txt": source / "requirements.txt",
        "hosted_common.py": HOSTED_ROOT / "hosted_common.py",
    }
    payloads = {}
    for filename, path in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or symlinked package source: {path}")
        payloads[filename] = path.read_bytes().replace(b"\r\n", b"\n")
    payloads["agent_spec.json"] = _canonical(normalized)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    package = output_dir / f"{normalized['name']}.zip"
    if package.is_symlink():
        raise ValueError("Refusing to replace a symlinked package.")
    with ZipFile(package, "w", compression=ZIP_STORED) as archive:
        for filename, data in sorted(payloads.items()):
            info = ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return package


def _field(value, key: str, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _latest(project_client, name: str):
    from azure.core.exceptions import ResourceNotFoundError
    try:
        agent = project_client.agents.get(agent_name=name)
    except ResourceNotFoundError:
        return None
    if _field(agent, "state") == "disabled":
        raise HostedPrerequisiteError(f"Agent {name!r} is disabled; the factory will not enable it.")
    # SDK 2.6 AgentDetails.versions.latest is an AgentVersionDetails, not a version string.
    latest = _field(_field(agent, "versions"), "latest")
    if latest is None:
        raise RuntimeError(f"Existing agent {name!r} has no latest version; refusing to overwrite it.")
    return latest


def _models():
    try:
        from azure.ai.projects import models
    except ImportError as exc:
        raise HostedPrerequisiteError("Deployment requires azure-ai-projects==2.6.0 and openai==3.0.0.") from exc
    return models


def _route(project_client, name: str, version: str) -> None:
    from .prompt import route_version
    route_version(project_client, name, version)


def _environment(target: Target, model: str) -> dict[str, str]:
    parsed = urlsplit(target.project_endpoint)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment
            or parsed.hostname != f"{target.account_name}.services.ai.azure.com"
            or parsed.path.rstrip("/") != f"/api/projects/{target.project_name}"):
        raise HostedPrerequisiteError("A canonical HTTPS Azure Foundry project endpoint is required.")
    if not model:
        raise HostedPrerequisiteError("A deployed model is required (spec.model or target.model_deployment).")
    # Foundry injects the dedicated agent identity. Do not override it with a shared UAMI,
    # copy deployment credentials, or serialize any ambient environment variables.
    return {
        "FOUNDRY_PROJECT_ENDPOINT": target.project_endpoint.rstrip("/"),
        "FOUNDRY_RESOURCE_ENDPOINT": f"https://{parsed.hostname}",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": model,
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
    }


def _prerequisites(project_client, normalized: dict) -> None:
    from azure.core.exceptions import ResourceNotFoundError
    try:
        deployment = project_client.deployments.get(name=normalized["model"])
    except ResourceNotFoundError as exc:
        raise HostedPrerequisiteError(f"Model deployment {normalized['model']!r} does not exist.") from exc
    if normalized["framework"] == "anthropic-agents":
        publisher = _field(deployment, "model_publisher", _field(deployment, "modelPublisher", ""))
        model_name = _field(deployment, "model_name", _field(deployment, "modelName", ""))
        if str(publisher).lower() != "anthropic" or not str(model_name).lower().startswith("claude"):
            raise HostedPrerequisiteError(
                "Anthropic SDK requires a deployed Anthropic Claude model in this Foundry account; "
                "GPT deployments and public Anthropic endpoints are not supported."
            )
        if _field(deployment, "connection_name", _field(deployment, "connectionName")):
            raise HostedPrerequisiteError("Claude must be deployed in this account, not an external connection.")
    if normalized["members"]:
        for member in normalized["members"]:
            participant = _latest(project_client, member["name"])
            if (participant is None or _field(_field(participant, "definition"), "kind") != "prompt"
                    or _field(participant, "status") != "active"):
                raise HostedPrerequisiteError(
                    f"Participant {member['name']!r} must already be an active persisted Foundry prompt agent."
                )


def deploy_hosted(project_client, target: Target, spec: dict, *,
                  output_dir: Path, timeout_seconds: int = 900) -> dict:
    """Create/reuse, poll and route one hosted agent; never creates clients or selects targets.

    Returns the service's {name, version, id, status, framework}. Existing unmanaged
    names, failed provisioning, absent models and absent participants fail explicitly.
    """
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive integer.")
    resolved = dict(spec)
    if resolved.get("framework") != "anthropic-agents":
        resolved["model"] = resolved.get("model") or target.model_deployment
    normalized = _normalize(resolved)
    environment = _environment(target, normalized["model"])
    latest = _latest(project_client, normalized["name"])
    if latest is not None and (_field(latest, "metadata") or {}).get(OWNER_KEY) != MANAGED_BY:
        raise ValueError(f"Refusing to modify unmanaged agent {normalized['name']!r}.")
    _prerequisites(project_client, normalized)
    package = build_package(normalized, output_dir)
    zip_hash = hashlib.sha256(package.read_bytes()).hexdigest()
    definition_hash = hashlib.sha256(_canonical({
        "package_sha256": zip_hash, "spec": normalized, "environment": environment,
        "runtime": "python_3_13", "protocol": "responses/2.0.0", "cpu": "0.5", "memory": "1Gi",
    })).hexdigest()
    current_definition = _field(latest, "definition")
    current_code = _field(current_definition, "code_configuration")
    matches_definition = (
        _field(current_definition, "kind") == "hosted"
        and _field(current_definition, "environment_variables") == environment
        and _field(current_definition, "cpu") == "0.5"
        and _field(current_definition, "memory") == "1Gi"
        and _field(current_code, "runtime") == "python_3_13"
        and _field(current_code, "entry_point") == ["python", "main.py"]
        and _field(current_code, "dependency_resolution") == "remote_build"
        and _field(current_code, "content_hash") == zip_hash
        and _field(latest, "description") == normalized["description"]
    )
    if (latest is None or (_field(latest, "metadata") or {}).get(HASH_KEY) != definition_hash
            or not matches_definition):
        models = _models()
        definition = models.HostedAgentDefinition(
            cpu="0.5", memory="1Gi",
            code_configuration=models.CodeConfiguration(
                runtime="python_3_13", entry_point=["python", "main.py"],
                dependency_resolution="remote_build",
            ),
            environment_variables=environment,
            protocol_versions=[models.ProtocolVersionRecord(protocol="responses", version="2.0.0")],
        )
        with package.open("rb") as code:
            latest = project_client.agents.create_version_from_code(
                agent_name=normalized["name"], definition=definition, code=code,
                code_zip_sha256=zip_hash, description=normalized["description"],
                metadata={**normalized["metadata"], HASH_KEY: definition_hash},
            )
    version = _field(latest, "version")
    if not version:
        raise RuntimeError("Foundry did not return a version identifier.")
    deadline = time.monotonic() + timeout_seconds
    while True:
        detail = project_client.agents.get_version(
            agent_name=normalized["name"], agent_version=version,
        )
        status = _field(detail, "status")
        if status == "active":
            break
        if status in {"failed", "deleting", "deleted"}:
            raise RuntimeError(f"Hosted agent {normalized['name']} version {version}: {status}.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Hosted agent {normalized['name']} version {version} timed out ({status}).")
        time.sleep(min(5, remaining))
    _route(project_client, normalized["name"], version)
    return {
        "name": _field(detail, "name"), "version": _field(detail, "version"),
        "id": _field(detail, "id"), "status": status, "framework": normalized["framework"],
    }
