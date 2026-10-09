"""Opt-in live voice for the AI Factory Agent chat application (project001 Dev).

The chat flag (enableFactoryChatAgent, step 70-factory-chat-agent) creates the owned Foundry prompt Agent. This module adds
the voice-enabled chat *application* on top of it. With enableAIFactoryAgentLiveVoice (which requires the chat flag), one
late project-pipeline step verifies that Agent, builds the knowledge index and deploys the private web application (the code
in usecase_code/40-agent-factory/40-aifactory-agent) with voice.enabled and the Azure Voice Live roles on the project Foundry
account. No new speech resource is created.

The engine only *reads* Azure (discovery). All writes are made by the existing, ownership-checked operator commands of the
agent (ingest, deploy.py --apply), run non-interactively with a generated configuration. False never deletes or detaches
anything; the model deployment, the Agent and the Entra registration are prerequisites, never created here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import quote, urlencode

from .azure import ARM, AzureError
from .factory_chat_agent import AGENT_NAME, AI_AUDIENCE, MODEL_NAME, OWNER
from .factory_chat_agent import API_VERSION as AGENT_API_VERSION
from .mcp_gateway import GUID, KNOWLEDGE_EXCLUDES, KNOWLEDGE_INCLUDES, flag

CHAT_FLAG = "enableFactoryChatAgent"
VOICE_FLAG = "enableAIFactoryAgentLiveVoice"
PROJECT_NUMBER = "001"
ENVIRONMENT = "dev"
SCOPE_KEY = "project001-dev"
DEFAULT_VOICE = "en-US-Ava:DragonHDLatestNeural"
DEFAULT_LANGUAGE = "en-US"
READ_ONLY_PERMISSIONS = ["knowledge.read", "factory.read"]
MAX_READERS = 20
RESOURCES_API = "2021-04-01"
COGNITIVE_API = "2025-06-01"
VOICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{1,99}$")
LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$")


class CommandError(RuntimeError):
    """An operator command failed. The message never includes command output."""


class ArmPort(Protocol):
    def arm(self, method: str, resource_id: str, body: dict | None = None, api_version: str = ...) -> dict: ...

    def pages(self, url: str, *, audience: str = ARM, field: str = "value") -> list[dict]: ...

    def request(self, method: str, url: str, body: dict | None = None, *, audience: str = ARM,
                headers: dict[str, str] | None = None) -> dict: ...


Runner = Callable[..., str]


def _unset_macro(value) -> bool:
    return isinstance(value, str) and value.startswith("$(") and value.endswith(")")


def _text(value) -> str:
    return "" if value is None or _unset_macro(value) else str(value).strip()


def _list(value, *, fold: bool = True) -> tuple[str, ...]:
    seen: list[str] = []
    for item in re.split(r"[,;\s]+", _text(value)):
        if item and item.lower() not in {entry.lower() for entry in seen}:
            seen.append(item.lower() if fold else item)
    return tuple(seen)


@dataclass(frozen=True)
class LiveVoiceRequest:
    enable_chat: bool
    enable_live_voice: bool
    subscription_id: str
    tenant_id: str
    resource_group: str
    environment: str
    project_number: str
    location: str
    factory_key: str = "aifactory"
    enable_container_apps: bool = False
    enable_ai_foundry: bool = False
    enable_ai_search: bool = False
    delete_requested: bool = False
    model_deployment: str = ""
    entra_app_id: str = ""
    container_apps_environment: str = ""
    reader_object_ids: tuple[str, ...] = ()
    voice_name: str = ""
    voice_languages: tuple[str, ...] = ()

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> "LiveVoiceRequest":
        """Build from pipeline variables (variables.yaml / .env / variables.json names)."""
        get = values.get
        prefix = _text(get("admin_aifactoryPrefixRG"))
        number = _text(get("project_number_000")).zfill(3)
        environment = _text(get("dev_test_prod")).lower()
        group = _text(get("projectResourceGroup")) or (
            f"{prefix}{_text(get('projectPrefix'))}project{number}-{_text(get('admin_locationSuffix'))}"
            f"-{environment}{_text(get('admin_aifactorySuffixRG'))}{_text(get('projectSuffix'))}")
        return cls(
            enable_chat=flag(get(CHAT_FLAG), CHAT_FLAG),
            enable_live_voice=flag(get(VOICE_FLAG), VOICE_FLAG),
            subscription_id=_text(get("dev_test_prod_sub_id")).lower(), tenant_id=_text(get("tenantId")).lower(),
            resource_group=group, environment=environment, project_number=number,
            location=_text(get("admin_location")).lower(),
            factory_key=re.sub(r"[^A-Za-z0-9_-]", "", prefix).strip("-_")[:80] or "aifactory",
            enable_container_apps=flag(get("enableContainerApps"), "enableContainerApps"),
            enable_ai_foundry=flag(get("enableAIFoundry"), "enableAIFoundry"),
            enable_ai_search=flag(get("enableAISearch"), "enableAISearch"),
            delete_requested=any(flag(get(name), name) for name in ("deleteAllServicesForProject", "deleteAllForProject")),
            model_deployment=_text(get("modelGPTXName")),
            entra_app_id=_text(get("aifactoryAgentEntraAppId")).lower(),
            container_apps_environment=_text(get("aifactoryAgentContainerAppsEnvironment")),
            reader_object_ids=_list(get("aifactoryAgentReaderObjectIds")),
            voice_name=_text(get("aifactoryAgentVoiceName")),
            voice_languages=_list(get("aifactoryAgentVoiceLanguages"), fold=False),
        )


@dataclass
class Decision:
    act: bool
    reason: str
    voice: bool = False


def decide(request: LiveVoiceRequest) -> Decision:
    """Validate intent offline; invalid combinations raise instead of being ignored."""
    if not request.enable_live_voice:
        return Decision(False, f"{VOICE_FLAG} is false: no voice application is deployed here (the Foundry Agent itself "
                               f"comes from {CHAT_FLAG}); existing resources are untouched.")
    if not request.enable_chat:
        raise ValueError(f"{VOICE_FLAG} requires {CHAT_FLAG}=true (live voice is an option of the AI Factory Agent chat, "
                         "not a separate agent).")
    if request.project_number != PROJECT_NUMBER:
        raise ValueError(f"The AI Factory Agent live voice application is supported only for project{PROJECT_NUMBER}; "
                         f"this pipeline is project{request.project_number}.")
    if request.environment != ENVIRONMENT:
        return Decision(False, f"The AI Factory Agent live voice application runs only in Dev; skipped for '{request.environment}'.")
    problems = []
    if request.delete_requested:
        problems.append("deleteAllServicesForProject/deleteAllForProject conflict with the enabled AI Factory Agent options")
    for name, enabled in (("enableContainerApps", request.enable_container_apps),
                          ("enableAIFoundry", request.enable_ai_foundry), ("enableAISearch", request.enable_ai_search)):
        if not enabled:
            problems.append(f"{VOICE_FLAG} requires {name}=true")
    if not MODEL_NAME.fullmatch(request.model_deployment):
        problems.append("modelGPTXName must identify the Foundry chat model deployment used by the Agent")
    if not GUID.fullmatch(request.entra_app_id):
        problems.append("aifactoryAgentEntraAppId must be the client ID (GUID) of the agent's Entra single-page-app registration")
    if not request.reader_object_ids:
        problems.append("aifactoryAgentReaderObjectIds must list at least one Entra object ID (GUID) allowed to use the chat")
    elif len(request.reader_object_ids) > MAX_READERS:
        problems.append(f"aifactoryAgentReaderObjectIds lists at most {MAX_READERS} object IDs")
    elif not all(GUID.fullmatch(item) for item in request.reader_object_ids):
        problems.append("aifactoryAgentReaderObjectIds entries must all be GUIDs")
    if request.voice_name and not VOICE.fullmatch(request.voice_name):
        problems.append("aifactoryAgentVoiceName must be an Azure Speech voice name such as en-US-Ava:DragonHDLatestNeural")
    if len(request.voice_languages) > 10 or not all(LANGUAGE.fullmatch(item) for item in request.voice_languages):
        problems.append("aifactoryAgentVoiceLanguages must be up to 10 comma-separated BCP-47 codes such as sv-SE,en-US")
    for name, value in (("dev_test_prod_sub_id", request.subscription_id), ("tenantId", request.tenant_id)):
        if not GUID.fullmatch(value):
            problems.append(f"{name} must be a GUID")
    if not request.resource_group or not request.location:
        problems.append("the project resource group and admin_location are required")
    if problems:
        raise ValueError("Invalid AI Factory Agent live voice configuration: " + "; ".join(problems) + ".")
    return Decision(True, "Validated project001 Dev AI Factory Agent live voice request.", True)


@dataclass
class Target:
    account_name: str
    location: str
    project_name: str
    project_endpoint: str
    model: dict
    embedding: str
    search_name: str
    storage_name: str
    insights_name: str
    environment_name: str
    agent_version: str


def _one(items: list[dict], label: str, name: str = "") -> dict:
    candidates = [item for item in items if not name or item["name"].split("/")[-1].lower() == name.lower()]
    if len(candidates) != 1:
        found = ", ".join(sorted(item["name"] for item in candidates)) or "(none)"
        raise ValueError(f"Expected exactly one {label}; found {len(candidates)}: {found}.")
    return candidates[0]


def verify_agent(session: ArmPort, project_endpoint: str) -> str:
    """The owned Foundry Agent must already exist (created by the chat step); this step never creates or changes it."""
    url = f"{project_endpoint}/agents/{quote(AGENT_NAME, safe='')}?{urlencode({'api-version': AGENT_API_VERSION})}"
    try:
        agent = session.request("GET", url, audience=AI_AUDIENCE)
    except AzureError as error:
        if error.status != 404:
            raise
        raise ValueError(f"The owned Foundry Agent '{AGENT_NAME}' does not exist yet. Enable {CHAT_FLAG} (step "
                         "70-factory-chat-agent) first; the live voice step never creates the Agent.") from None
    latest = (agent.get("versions") or {}).get("latest")
    if not isinstance(latest, dict):
        raise ValueError(f"The Foundry Agent '{AGENT_NAME}' has no valid latest version.")
    if (latest.get("metadata") or {}).get("aifactory.managed_by") != OWNER:
        raise ValueError(f"The existing Agent '{AGENT_NAME}' is not owned by the Enterprise Scale AI Factory; "
                         "refusing to attach the application to it.")
    return str(latest.get("version") or latest.get("id") or "")


def discover(session: ArmPort, request: LiveVoiceRequest) -> Target:
    """Resolve the project's actual Foundry, data and Container Apps resources (GET only)."""
    group_id = f"/subscriptions/{request.subscription_id}/resourceGroups/{request.resource_group}"
    resources = session.pages(f"{ARM}{group_id}/resources?api-version={RESOURCES_API}")

    def of_type(kind: str) -> list[dict]:
        return sorted((item for item in resources if item["type"].lower() == kind.lower()), key=lambda item: item["name"])

    account = _one([item for item in of_type("Microsoft.CognitiveServices/accounts") if item.get("kind") == "AIServices"],
                   "project Foundry (AIServices) account")
    project = _one(session.pages(f"{ARM}{account['id']}/projects?api-version={COGNITIVE_API}"), "Foundry project")
    project = session.arm("GET", project["id"], api_version=COGNITIVE_API)
    endpoint = ((project.get("properties") or {}).get("endpoints") or {}).get("AI Foundry API")
    if not endpoint:
        raise ValueError("The Foundry project does not report an 'AI Foundry API' endpoint.")
    deployments = session.pages(f"{ARM}{account['id']}/deployments?api-version={COGNITIVE_API}")
    wanted = request.model_deployment
    named = [item for item in deployments if item["name"].split("/")[-1].lower() == wanted.lower()]
    if not named:
        raise ValueError(f"The project Foundry account has no model deployment named '{wanted}' (modelGPTXName). Deploy it "
                         "first (infra/Deploy-Model.ps1 or the Foundry portal); this step never creates or replaces model deployments.")
    chat = named[0]
    state = (chat.get("properties") or {}).get("provisioningState")
    if state != "Succeeded":
        raise ValueError(f"The model deployment '{wanted}' has not succeeded yet (state {state}); retry when it is ready.")
    embeddings = sorted(item["name"].split("/")[-1] for item in deployments
                        if item["properties"]["model"]["name"].startswith("text-embedding")
                        and item["properties"].get("provisioningState") == "Succeeded")
    if not embeddings:
        raise ValueError("The agent's knowledge index requires a succeeded text-embedding deployment in the project Foundry account.")
    searches = of_type("Microsoft.Search/searchServices")
    if not searches:
        raise ValueError("The agent requires the project AI Search service (enableAISearch=true).")
    storages = of_type("Microsoft.Storage/storageAccounts")
    data = [item for item in storages if "2001" in item["name"]] or storages
    if not data:
        raise ValueError("The agent requires the project data storage account.")
    environment = _one(of_type("Microsoft.App/managedEnvironments"),
                       "project Container Apps environment (set aifactoryAgentContainerAppsEnvironment)",
                       request.container_apps_environment)
    environment = session.arm("GET", environment["id"], api_version="2024-03-01")
    if not ((environment.get("properties") or {}).get("vnetConfiguration") or {}).get("internal"):
        raise ValueError("The agent stays private: the selected Container Apps environment must be internal (VNet-integrated).")
    agent_version = verify_agent(session, endpoint.rstrip("/"))
    insights = of_type("Microsoft.Insights/components")
    model = chat["properties"]["model"]
    return Target(
        account_name=account["name"], location=account["location"], project_name=project["name"].split("/")[-1],
        project_endpoint=endpoint.rstrip("/"),
        model={"name": wanted, "model": model["name"], "version": model.get("version", ""),
               "sku": (chat.get("sku") or {}).get("name", "DataZoneStandard"),
               "capacity": int((chat.get("sku") or {}).get("capacity") or 10)},
        embedding=embeddings[0], search_name=searches[0]["name"], storage_name=data[0]["name"],
        insights_name=insights[0]["name"] if insights else "", environment_name=environment_name(environment),
        agent_version=agent_version,
    )


def environment_name(environment: dict) -> str:
    return environment["id"].rstrip("/").rsplit("/", 1)[-1]


def render_config(request: LiveVoiceRequest, target: Target, *, repository_root: Path) -> dict:
    """The application's Settings document (no secrets). Writes stay disabled; grants are read-only; voice is on."""
    root = str(repository_root)
    azure = {
        "foundry_account": target.account_name, "foundry_project": target.project_name,
        "project_endpoint": target.project_endpoint,
        "openai_endpoint": f"https://{target.account_name}.openai.azure.com/openai/v1",
        "model_deployment": target.model["name"], "model_name": target.model["model"],
        "model_version": target.model["version"], "model_sku": target.model["sku"],
        "model_capacity": target.model["capacity"], "embedding_deployment": target.embedding,
        "search_endpoint": f"https://{target.search_name}.search.windows.net", "search_index": "enterprise-scale-ai-factory-v1",
        "storage_endpoint": f"https://{target.storage_name}.blob.core.windows.net", "storage_container": "aifactory-agent",
        "credential": "cli",
    }
    if target.insights_name:
        azure["application_insights_name"] = target.insights_name
    return {
        "location": target.location,
        "scopes": {SCOPE_KEY: {"tenant_id": request.tenant_id, "subscription_id": request.subscription_id,
                               "resource_group": request.resource_group, "factory": request.factory_key,
                               "project": PROJECT_NUMBER, "environment": ENVIRONMENT}},
        "azure": azure,
        "knowledge": {"top_k": 3, "repository_root": root,
                      "source_base_url": "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main",
                      "includes": list(KNOWLEDGE_INCLUDES), "excludes": list(KNOWLEDGE_EXCLUDES)},
        "factory": {"api_url": "http://127.0.0.1:8765", "folder": "/state/azurefactory", "writes_enabled": False,
                    "allowed_write_environments": [ENVIRONMENT]},
        "actions": {"enabled_skills": []}, "costs": {},
        "workloads": {"enabled_skills": [], "repository_root": root, "profiles": {}},
        "auth": {"client_id": request.entra_app_id, "audience": "api://" + request.entra_app_id,
                 "grants": [{"object_id": object_id, "scopes": [SCOPE_KEY], "permissions": list(READ_ONLY_PERMISSIONS)}
                            for object_id in request.reader_object_ids]},
        "voice": {"enabled": True, "voice_name": request.voice_name or DEFAULT_VOICE,
                  "input_languages": list(request.voice_languages) or [DEFAULT_LANGUAGE]},
    }


def subprocess_runner(args, *, cwd, env=None) -> str:
    """Run one operator command. Output streams to the pipeline log; errors never embed it."""
    process = subprocess.run([str(item) for item in args], cwd=str(cwd), env={**os.environ, **(env or {})},
                             capture_output=True, text=True, timeout=7200)
    if process.stderr:
        sys.stderr.write(process.stderr[-6000:])
    if process.returncode != 0:
        raise CommandError(f"exit {process.returncode}")
    return process.stdout


def _last_json(output: str) -> dict:
    for start in range(len(output)):
        if output[start] == "{":
            try:
                value = json.loads(output[start:])
            except ValueError:
                continue
            return value if isinstance(value, dict) else {}
    return {}


@dataclass
class Report:
    mode: str
    actions: list[dict] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    prerequisites: list[str] = field(default_factory=list)

    def add(self, resource: str, action: str, detail: str = "") -> None:
        self.actions.append({"resource": resource, "action": action, **({"detail": detail} if detail else {})})

    def to_dict(self) -> dict:
        return {"mode": self.mode, "actions": self.actions, "outputs": self.outputs,
                "prerequisites": self.prerequisites, "mutations": self.mode == "apply"}


class LiveVoiceIntegration:
    """Dependency-injected orchestration: plan (Azure GET only) or apply (the agent's own owned writes)."""

    def __init__(self, session: ArmPort, runner: Runner, *, work_dir: Path, repository_root: Path,
                 agent_dir: Path | None = None):
        self.session, self.runner = session, runner
        self.work_dir, self.repository_root = Path(work_dir), Path(repository_root)
        self.agent_dir = agent_dir or Path(__file__).resolve().parents[1] / "40-aifactory-agent"

    def _steps(self, target: Target, config: Path) -> list[tuple[str, str, list]]:
        env_dir = self.work_dir / "agent-env"
        python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        return [
            ("isolated python environment", "python environment", [
                [sys.executable, "-m", "venv", str(env_dir)],
                [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.lock.txt"]]),
            ("linux wheels for the bundle", "wheel download", [
                [python, "-m", "pip", "download", "--quiet", "--disable-pip-version-check", "--dest", ".build/wheels",
                 "--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_28_x86_64", "--python-version", "312",
                 "--implementation", "cp", "--abi", "cp312", "--only-binary", ":all:", "-r", "requirements.lock.txt",
                 "pip==25.3"]]),
            ("knowledge index", "ingest", [[python, "-m", "aifactory_agent", "--config", str(config), "ingest"]]),
            ("container app", "deploy.py", [[python, "deploy.py", "--config", str(config), "--environment",
                                              target.environment_name, "--apply"]]),
        ]

    def run(self, request: LiveVoiceRequest, *, apply: bool) -> dict:
        decision = decide(request)
        report = Report("apply" if apply else "plan")
        if not decision.act:
            report.add("ai-factory-agent-live-voice", "skipped", decision.reason)
            report.mode = "skipped"
            return report.to_dict()
        target = discover(self.session, request)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        config = self.work_dir / "config.json"
        config.write_text(json.dumps(render_config(request, target, repository_root=self.repository_root), indent=2),
                          encoding="utf-8")
        report.outputs = {"voice": True, "scope": SCOPE_KEY, "model_deployment": target.model["name"],
                          "container_apps_environment": target.environment_name,
                          "agent": {"name": AGENT_NAME, "version": target.agent_version}}
        report.prerequisites = [
            "An Entra admin created the agent's single-page-app registration (Application ID URI api://<client-id>, delegated "
            "scope access_as_user) and registered the application's exact HTTPS root as its SPA redirect URI; pipelines never "
            "write Microsoft Graph.",
            f"The Foundry Agent comes from {CHAT_FLAG} (step 70-factory-chat-agent) earlier in the same foundry phase; this step "
            "only verifies it and never creates or changes it.",
            "The listed reader object IDs are the only users granted read-only chat access; write, delete and cost "
            "permissions are never granted by this step.",
            "Live voice assigns Cognitive Services User and Foundry User (Azure AI User) on the project Foundry account to the "
            "application identity (Microsoft's documented keyless Voice Live requirement). These are broader than the "
            "project-scoped runtime role and are never removed by turning voice off.",
            "The runner can reach the package feed (pip), the project's private Foundry and Search endpoints, and storage; the "
            "application must resolve and reach the Foundry services.ai.azure.com private endpoint.",
        ]
        details = {"ingest": "creates/reconciles the owned Search index and makes embedding calls (billed)",
                   "deploy.py": "owned identity, runtime and Voice Live roles, private Container App and refresh job; "
                                "refuses unowned resources"}
        outputs: dict = {}
        for resource, marker, commands in self._steps(target, config):
            if not apply:
                report.add(resource, "would run", details.get(marker, ""))
                continue
            result = ""
            for command in commands:
                try:
                    result = self.runner(command, cwd=self.agent_dir)
                except CommandError as error:
                    raise CommandError(f"{resource} failed ({error})") from None
            report.add(resource, "ran", details.get(marker, ""))
            parsed = _last_json(result)
            if marker == "ingest":
                outputs["knowledge"] = {key: parsed.get(key) for key in ("status", "indexed_document_count")}
            elif marker == "deploy.py":
                outputs["app"] = {"fqdn": ((parsed.get("outputs") or {}).get("fqdn") or {}).get("value"),
                                  "deployment_state": parsed.get("deployment_state")}
        report.outputs.update(outputs)
        return report.to_dict()
