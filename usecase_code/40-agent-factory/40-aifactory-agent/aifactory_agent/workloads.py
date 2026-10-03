"""Server-selected workload strategies, bound to reviewed sources and exact project IDs."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import stat
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Callable, Iterable, Literal, Mapping, Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .ports import OperationStorePort


AGENT_CREATE = "create-agent-oftype-for-project"
MODEL_CREATE = "create-ml-model-oftype-for-project"
WORKLOAD_SKILLS = (AGENT_CREATE, MODEL_CREATE)
SkillName = Literal["create-agent-oftype-for-project", "create-ml-model-oftype-for-project"]
ServingMode = Literal["batch", "online", "streaming"]
Family = Literal["prompt", "hosted", "azureml"]
TYPE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"
_UUID = r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"
_RG = rf"/subscriptions/{_UUID}/resourceGroups/[A-Za-z0-9_().-]{{1,90}}"
_NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
_FOUNDRY = _RG + rf"/providers/Microsoft\.CognitiveServices/accounts/{_NAME}/projects/{_NAME}"
_WORKSPACE = _RG + rf"/providers/Microsoft\.MachineLearningServices/workspaces/{_NAME}"
_IGNORED = frozenset({
    "__pycache__", ".venv", ".git", ".pytest_cache", ".build", "node_modules",
    "build", "dist", "outputs", "artifacts", "generated", ".env",
})
_HELPERS = _IGNORED | frozenset({
    "agent_factory", "ml_model_factory", "tests", "scripts", "scenarios", "environments",
    "docs", "data", "43-data", "44-azure-mcp", "config", "40-aifactory-agent", "40-aifactory-agent-v2",
})
_SOURCE_SUFFIXES = frozenset({".py", ".json", ".yaml", ".yml", ".ipynb", ".toml", ".bicep"})
_EXCLUDED_SOURCE_PARTS = _IGNORED | frozenset({"tests", "docs", "data", "40-aifactory-agent", "40-aifactory-agent-v2"})
_PRIVATE_PART = re.compile(r"(?i)^(?:private|secrets?|credentials?|tokens?)(?:[_.-]|$)")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _arm(value: str, pattern: str) -> str:
    if not re.fullmatch(pattern, value) or any(part.endswith(".") for part in value.split("/")):
        raise ValueError("An exact canonical project/workspace/resource-group ARM ID is required.")
    return value


def _relative(value: str) -> str:
    pieces = re.split(r"[\\/]", value)
    if (not pieces or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..")
                          for part in pieces)):
        raise ValueError("Server source paths must be literal repository-relative paths without traversal.")
    return str(Path(*pieces))


class WorkloadArgs(Closed):
    type: str = Field(pattern=TYPE_PATTERN)
    project_resource_id: str

    @field_validator("project_resource_id")
    @classmethod
    def project_id(cls, value):
        return _arm(value, _FOUNDRY)


class ModelArgs(Closed):
    type: str = Field(pattern=TYPE_PATTERN)
    project_resource_id: str
    serving_mode: ServingMode

    @field_validator("project_resource_id")
    @classmethod
    def workspace_or_group(cls, value):
        return _arm(value, rf"(?:{_WORKSPACE}|{_RG})")


class WorkloadProfile(Closed):
    """Deployment-operator input only; callers select neither code nor runtime."""

    profile_id: str = Field(pattern=TYPE_PATTERN)
    kind: Literal["agent", "model"]
    type: str = Field(pattern=TYPE_PATTERN)
    family: Family
    project_resource_id: str
    config_path: str
    catalog_selection: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
    agent_prefix: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,40}$")
    serving_mode: ServingMode | None = None
    scenario_path: str | None = None
    training_mode: Literal["automl", "custom"] | None = None
    output_directory: str | None = None
    hosted_runtime_path: str | None = None

    @field_validator("config_path", "scenario_path", "output_directory", "hosted_runtime_path")
    @classmethod
    def source_path(cls, value):
        return _relative(value) if value is not None else None

    @model_validator(mode="after")
    def concrete_profile(self):
        if self.kind == "agent":
            _arm(self.project_resource_id, _FOUNDRY)
            if (self.family not in ("prompt", "hosted") or not self.catalog_selection or not self.agent_prefix
                    or self.serving_mode is not None or self.scenario_path is not None or self.training_mode is not None):
                raise ValueError("Agent profiles require an explicit catalog selection/prefix and agent family.")
            if self.family == "hosted" and (not self.hosted_runtime_path or not self.output_directory):
                raise ValueError("Hosted profiles require an explicit runtime/source-upload approval and output directory.")
            if self.family == "prompt" and (self.hosted_runtime_path is not None or self.output_directory is not None):
                raise ValueError("Prompt profiles have no hosted runtime or output directory.")
        else:
            _arm(self.project_resource_id, rf"(?:{_WORKSPACE}|{_RG})")
            if (self.family != "azureml" or not all((self.serving_mode, self.scenario_path,
                                                   self.training_mode, self.output_directory))
                    or any((self.catalog_selection, self.agent_prefix, self.hosted_runtime_path))):
                raise ValueError("Model profiles require explicit mode, canonical scenario, runtime and output directory.")
        return self


class WorkloadSettings(Closed):
    enabled_skills: list[SkillName] = Field(default_factory=list)
    repository_root: str | None = None
    profiles: dict[str, list[WorkloadProfile]] = Field(default_factory=dict)
    plan_ttl_seconds: int = Field(default=900, ge=1, le=900)
    max_files: int = Field(default=2000, ge=1, le=10000)
    max_file_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    max_total_bytes: int = Field(default=32_000_000, ge=1, le=100_000_000)

    @model_validator(mode="after")
    def distinct_selections(self):
        if len(set(self.enabled_skills)) != len(self.enabled_skills):
            raise ValueError("Enabled workload skills must be distinct.")
        for key, profiles in self.profiles.items():
            if not re.fullmatch(TYPE_PATTERN, key):
                raise ValueError("Workload scope keys must be safe identifiers.")
            selections = [(item.kind, item.type, item.serving_mode) for item in profiles]
            if (len(set(selections)) != len(selections)
                    or len({item.profile_id for item in profiles}) != len(profiles)):
                raise ValueError("Each scope/type/mode and profile ID must have one server-approved selection.")
        return self


def _error(code, message, status_code=409):
    from .tools import ToolError
    raise ToolError(code, message, status_code)


def _workloads(settings) -> WorkloadSettings:
    return settings if isinstance(settings, WorkloadSettings) else settings.workloads


def _hash(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe(value):
    from azurefactory.client import redact_secrets
    return redact_secrets(copy.deepcopy(value), None)


def required_permission(name: str) -> str:
    if name == AGENT_CREATE:
        return "agent.create"
    if name == MODEL_CREATE:
        return "model.create"
    _error("unsupported_operation", "This workload skill is not in the backend allowlist.", 400)


def argument_model(name):
    required_permission(name)
    return WorkloadArgs if name == AGENT_CREATE else ModelArgs


def _linked(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _unlinked(path: Path):
    for candidate in (path, *path.parents):
        if candidate.exists() and _linked(candidate):
            _error("unsafe_source_path", "Workload source and output paths cannot contain symbolic links or junctions.", 403)


def _root(settings) -> Path:
    root = _workloads(settings).repository_root
    if not root:
        _error("workload_source_unconfigured", "Configure the approved purple repository root on the server.", 503)
    path = Path(root)
    if not path.is_absolute() or not path.is_dir():
        _error("workload_source_unconfigured", "The approved workload repository must be an existing absolute directory.", 503)
    _unlinked(path)
    return path.resolve()


def _path(root: Path, relative: str, *, must_exist=True) -> Path:
    try:
        path = root / _relative(relative)
    except ValueError:
        _error("unsafe_source_path", "The approved source reference is not a literal repository-relative path.", 403)
    _unlinked(path)
    if not path.resolve().is_relative_to(root):
        _error("unsafe_source_path", "The selected workload source escapes the approved repository.", 403)
    if must_exist and not path.exists():
        _error("workload_config_missing", "A required approved source/configuration artifact is absent.", 503)
    return path


def _source_path_allowed(relative: Path, *, file=False) -> bool:
    if any(part.startswith(".") or part.casefold() in _EXCLUDED_SOURCE_PARTS or _PRIVATE_PART.match(part)
           for part in relative.parts):
        return False
    return not file or relative.suffix.lower() in _SOURCE_SUFFIXES or relative.name == "requirements.txt"


def _files(path: Path, settings, *, strict=False) -> list[Path]:
    limits = _workloads(settings)
    found = []
    visited = 0

    def visit(candidate):
        nonlocal visited
        visited += 1
        if visited > limits.max_files * 4:
            _error("source_limit_exceeded", "The workload source tree exceeds its bounded directory/entry count.", 503)
        if _linked(candidate):
            _error("unsafe_source_path", "Workload manifests cannot contain symbolic links or junctions.", 403)
        if candidate.is_dir():
            for child in sorted(candidate.iterdir(), key=lambda item: item.name):
                if not strict and not _source_path_allowed(child.relative_to(path)):
                    continue
                visit(child)
        elif candidate.is_file():
            if not strict and not _source_path_allowed(candidate.relative_to(path) if candidate != path else Path(candidate.name), file=True):
                return
            if candidate.stat().st_size > limits.max_file_bytes:
                _error("source_limit_exceeded", "An approved workload input exceeds the bounded artifact size.", 503)
            found.append(candidate)
            if len(found) > limits.max_files:
                _error("source_limit_exceeded", "The workload source manifest exceeds its file-count bound.", 503)

    visit(path)
    return found


@dataclass(frozen=True)
class Template:
    kind: str
    type: str
    mode: str | None
    path: Path


class TemplateCatalog(Protocol):
    def types(self, kind: str | None = None, serving_mode: str | None = None) -> list[dict]: ...

    def resolve(self, kind: str, type: str, serving_mode: str | None = None) -> Template: ...


class FileSystemTemplateCatalog:
    """Only immediate, nonempty source folders are workload types, never framework names."""

    def __init__(self, settings):
        self.settings = settings

    def types(self, kind=None, serving_mode=None):
        if kind not in (None, "agent", "model") or serving_mode not in (None, "batch", "online", "streaming"):
            _error("unsupported_workload_type", "Select an agent type or model type and serving mode.", 400)
        root = _root(self.settings)
        parents = []
        if (kind in (None, "agent") and serving_mode is None
                and (root / "usecase_code" / "40-agent-factory").is_dir()):
            parents.append(("agent", None, _path(root, "usecase_code\\40-agent-factory")))
        if kind in (None, "model") and (root / "usecase_code" / "50-ml-model-factory").is_dir():
            base = _path(root, "usecase_code\\50-ml-model-factory")
            for mode in ("batch", "online", "streaming"):
                if serving_mode in (None, mode) and (base / mode).is_dir():
                    parents.append(("model", mode, _path(root, str((base / mode).relative_to(root)))))
        result = []
        for selected_kind, mode, parent in parents:
            for child in sorted(parent.iterdir(), key=lambda item: item.name):
                if (not child.is_dir() or _linked(child) or child.name.casefold() in _HELPERS
                        or not re.fullmatch(TYPE_PATTERN, child.name)):
                    continue
                files = _files(child, self.settings)
                if not any(item.suffix.lower() in _SOURCE_SUFFIXES for item in files):
                    continue
                result.append({
                    "kind": selected_kind, "type": child.name, "mode": mode,
                    "family": "unconfigured", "available": False, "blockers": ["workload_profile_required"],
                })
                if len(result) > _workloads(self.settings).max_files:
                    _error("source_limit_exceeded", "Template discovery exceeds its bounded manifest.", 503)
        return result

    def resolve(self, kind, type, serving_mode=None):
        if not isinstance(type, str) or not re.fullmatch(TYPE_PATTERN, type):
            _error("unsupported_workload_type", "Workload type must be one literal immediate folder name.", 400)
        if not any(item["type"] == type and item["mode"] == serving_mode
                   for item in self.types(kind, serving_mode)):
            _error("unsupported_workload_type", "That type/mode is not an actual nonempty immediate workload folder.", 400)
        parent = "usecase_code\\40-agent-factory" if kind == "agent" else "usecase_code\\50-ml-model-factory\\" + serving_mode
        return Template(kind, type, serving_mode, _path(_root(self.settings), parent + "\\" + type))


def _select_profile(settings, scope_key, name, arguments, catalog: TemplateCatalog):
    kind = "agent" if name == AGENT_CREATE else "model"
    mode = getattr(arguments, "serving_mode", None)
    template = catalog.resolve(kind, arguments.type, mode)
    profiles = [item for item in _workloads(settings).profiles.get(scope_key, [])
                if (item.kind, item.type, item.serving_mode) == (kind, arguments.type, mode)]
    if len(profiles) != 1:
        _error("workload_profile_required", "This exact workload type/mode needs a server-approved source/runtime profile.", 503)
    profile = profiles[0]
    scope = settings.scopes[scope_key]
    group = f"/subscriptions/{scope.subscription_id}/resourceGroups/{scope.resource_group}"
    if (profile.project_resource_id != arguments.project_resource_id
            or profile.project_resource_id.split("/providers/", 1)[0] != group):
        _error("workload_target_mismatch", "The workload must target the active project's exact approved ARM ID and resource group.", 403)
    expected = FileSystemTemplateCatalog(settings).resolve(kind, arguments.type, mode)
    if (template.kind, template.type, template.mode, template.path.resolve()) != (
            expected.kind, expected.type, expected.mode, expected.path.resolve()):
        _error("unsafe_source_path", "The catalog selection differs from the server's exact immediate source folder.", 403)
    if profile.output_directory:
        _approved_output(settings, profile)
    return profile, template


def _approved_output(settings, profile):
    root = _root(settings)
    parent = _path(root, profile.output_directory, must_exist=False)
    source = root / "usecase_code"
    if (parent == source or parent.is_relative_to(source) or source.is_relative_to(parent)
            or parent.exists() and not parent.is_dir()):
        _error("unsafe_source_path", "Generated workload bundles must be directories separate from executable/template sources.", 403)
    return parent


def _profile_input_paths(settings, profile, template) -> list[Path]:
    root = _root(settings)
    factory = root / "usecase_code" / ("40-agent-factory" if profile.kind == "agent" else "50-ml-model-factory")
    package = factory / ("agent_factory" if profile.kind == "agent" else "ml_model_factory")
    if not package.is_dir():
        _error("workload_config_missing", "The approved in-process provider source package is absent.", 503)
    paths = _files(template.path, settings) + _files(package, settings)
    if profile.family == "hosted":
        shared_runtime = factory / "41-single-agent" / "hosted-agent"
        if not shared_runtime.is_dir():
            _error("workload_config_missing", "The hosted strategy requires the approved shared runtime source.", 503)
        paths.extend(_files(shared_runtime, settings))
    paths.append(_path(root, profile.config_path))
    for relative in (profile.scenario_path, profile.hosted_runtime_path):
        if relative:
            paths.append(_path(root, relative))
    for filename in ("pyproject.toml", "requirements.txt"):
        if (factory / filename).is_file():
            paths.append(factory / filename)
    if profile.kind == "model":
        for directory in ("scripts", "environments"):
            if (factory / directory).is_dir():
                paths.extend(_files(factory / directory, settings))
    for path in paths:
        if not _source_path_allowed(path.relative_to(root), file=True):
            _error("unsafe_source_path", "Every approved input must pass the same private/generated source-path policy.", 403)
    return sorted(set(paths), key=str)


def _input_paths(settings, profile, template) -> list[Path]:
    paths = _profile_input_paths(settings, profile, template)
    runtime_package = Path(__file__).resolve().parent
    paths.extend(runtime_package.glob("*.py"))
    for filename in ("requirements.txt", "requirements.lock.txt"):
        if (runtime_package.parent / filename).is_file():
            paths.append(runtime_package.parent / filename)
    client_module = importlib.import_module("azurefactory.client")
    paths.extend(_files(Path(client_module.__file__).resolve().parent, settings))
    return sorted(set(paths), key=str)


def _artifact_name(path, root):
    if path.is_relative_to(root):
        return str(path.relative_to(root))
    runtime_package = Path(__file__).resolve().parent
    if path.is_relative_to(runtime_package):
        return str(Path("adapter") / "aifactory_agent" / path.relative_to(runtime_package))
    if path.parent == runtime_package.parent:
        return str(Path("adapter") / path.name)
    client_module = importlib.import_module("azurefactory.client")
    provider = Path(client_module.__file__).resolve().parent
    if path.is_relative_to(provider):
        return str(Path("adapter") / "azurefactory" / path.relative_to(provider))
    _error("unsafe_source_path", "An execution dependency is outside the approved source packages.", 403)


def _snapshot(settings, profile, template):
    root, limits = _root(settings), _workloads(settings)
    manifest, total = [], 0
    paths = _input_paths(settings, profile, template)
    if len(paths) > limits.max_files:
        _error("source_limit_exceeded", "The combined workload artifact manifest exceeds its file-count bound.", 503)
    for path in paths:
        _unlinked(path)
        if not path.is_file():
            _error("workload_config_missing", "Every approved workload configuration reference must be a file.", 503)
        data = _read_source(path, limits)
        size = len(data)
        total += size
        if size > limits.max_file_bytes or total > limits.max_total_bytes:
            _error("source_limit_exceeded", "The approved source artifacts exceed their bounded size.", 503)
        relative = _artifact_name(path, root)
        _inspect_config_source(path, data)
        manifest.append({"path": relative, "size": size, "sha256": hashlib.sha256(data).hexdigest()})
    return manifest, _hash(manifest)


def _read_source(path, limits):
    _unlinked(path)
    if not path.is_file():
        _error("workload_config_missing", "The approved configuration must be a bounded JSON file.", 503)
    try:
        with path.open("rb") as source:
            data = source.read(limits.max_file_bytes + 1)
    except OSError:
        _error("workload_source_unavailable", "An approved workload input could not be read.", 503)
    if len(data) > limits.max_file_bytes:
        _error("source_limit_exceeded", "An approved workload input exceeds its bounded size.", 503)
    return data


def _credential_free(value):
    forbidden = {
        "accountkey", "apikey", "accesskey", "sharedaccesskey", "sharedaccesssignature",
        "sastoken", "password", "passwd", "clientsecret", "secret", "token", "accesstoken",
        "refreshtoken", "authorization", "privatekey", "subscriptionkey",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if (any(normalized.endswith(name) for name in forbidden) or normalized in ("secrets", "credentials")
                    or "connectionstring" in normalized
                    or normalized == "credential" and item not in ("managed_identity", "azure_cli")):
                _error("secret_in_workload_config", "Workload inputs cannot contain credentials, connection strings or signed URLs.", 503)
            _credential_free(item)
    elif isinstance(value, list):
        for item in value:
            _credential_free(item)
    elif isinstance(value, str):
        if (re.search(r"(?i)\b(?:AccountKey|SharedAccessSignature|Password|ClientSecret)\s*=", value)
                or re.search(r"(?i)\b(?:account[_-]?key|shared[_-]?access[_-]?key|connection[_-]?string|client[_-]?secret|password|sas[_-]?token|api[_-]?key)\s*[\"']?\s*[:=]\s*[\"']?\S+", value)
                or re.search(r"(?i)\bBearer\s+\S+", value)
                or re.search(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----", value)):
            _error("secret_in_workload_config", "Workload inputs cannot contain credential material.", 503)
        for url in re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+", value):
            try:
                parsed = urlsplit(url)
                parameters = parse_qsl(parsed.query, keep_blank_values=True) + parse_qsl(parsed.fragment, keep_blank_values=True)
            except ValueError:
                _error("workload_config_invalid", "A workload input contains a malformed URL.", 503)
            signed = {
                "sig", "signature", "sastoken", "token", "accesstoken", "apikey",
                "xamzsignature", "xamzcredential", "xgoogsignature", "xgoogcredential",
            }
            if (parsed.username is not None or parsed.password is not None
                    or any(re.sub(r"[^a-z0-9]", "", key.casefold()) in signed for key, _ in parameters)):
                _error("secret_in_workload_config", "Workload inputs cannot contain credential-bearing or signed URLs.", 503)


def _parse_config(data):
    def unique_object(pairs):
        document = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("Duplicate configuration property.")
            document[key] = value
        return document

    try:
        document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, ValueError):
        _error("workload_config_invalid", "The approved configuration is not a readable JSON object.", 503)
    if not isinstance(document, dict):
        _error("workload_config_invalid", "The approved configuration must be a JSON object.", 503)
    _credential_free(document)
    credential_free = copy.deepcopy(document)
    if isinstance(credential_free, dict) and credential_free.get("credential") in ("managed_identity", "azure_cli"):
        # The provider uses this field for a credential *mode*, not credential material.
        credential_free.pop("credential")
    if not isinstance(document, dict) or _safe(credential_free) != credential_free:
        _error("secret_in_workload_config", "Workload source profiles must be JSON objects without embedded credentials.", 503)
    return document


def _inspect_config_source(path, data):
    if path.suffix.lower() in (".json", ".ipynb"):
        _parse_config(data)
    elif path.suffix.lower() in (".yaml", ".yml", ".toml") or path.name == "requirements.txt":
        try:
            value = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            _error("workload_config_invalid", "Approved source configurations must be UTF-8 text.", 503)
        _credential_free(value)


def _json_config(settings, relative):
    root = _root(settings)
    path = _path(root, relative)
    if not _source_path_allowed(path.relative_to(root), file=True):
        _error("unsafe_source_path", "Approved configurations cannot be private/generated source paths.", 403)
    return _parse_config(_read_source(path, _workloads(settings)))


def _capture_approved_inputs(context):
    expected = {item["path"]: dict(item) for item in context.source_manifest}
    if not expected or _hash([dict(item) for item in context.source_manifest]) != context.source_artifact_hash:
        _error("plan_changed", "Execution requires the exact immutable approved source manifest.")
    paths = _input_paths(context.settings, context.profile, context.template)
    root = _root(context.settings)
    if {_artifact_name(path, root) for path in paths} != expected.keys():
        _error("plan_changed", "The approved source inventory changed before capture.")
    captured = {}
    total = 0
    limits = _workloads(context.settings)
    for path in paths:
        data = _read_source(path, limits)
        total += len(data)
        item = expected[_artifact_name(path, root)]
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            _error("plan_changed", "An approved source/configuration input changed before immutable capture.")
        if total > limits.max_total_bytes:
            _error("source_limit_exceeded", "Captured workload inputs exceed the approved bounded size.", 503)
        _inspect_config_source(path, data)
        captured[path] = data
    return MappingProxyType(captured)


def _write_immutable_tree(root, files):
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o444)
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            path.chmod(0o555)
    root.chmod(0o555)


def _remove_owned_tree(path):
    if not path.exists() and not path.is_symlink():
        return
    if _linked(path):
        path.rmdir() if path.is_dir() else path.unlink()
    elif path.is_dir():
        path.chmod(0o700)
        for child in path.iterdir():
            _remove_owned_tree(child)
        path.rmdir()
    else:
        path.chmod(0o600)
        path.unlink()


def _verify_exact_tree(root, expected, settings):
    paths = _files(root, settings, strict=True)
    if {path.relative_to(root) for path in paths} != expected.keys():
        _error("invalid_workload_bundle", "Rendered/uploaded code contains missing or unapproved files.", 502)
    manifest = []
    for path in paths:
        relative = path.relative_to(root)
        data = _read_source(path, _workloads(settings))
        if data != expected[relative]:
            _error("invalid_workload_bundle", "Rendered/uploaded code differs from the approved immutable source bytes.", 502)
        manifest.append({"path": str(relative), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return _hash(manifest)


def _verify_pipeline_code(path):
    import yaml
    _unlinked(path)
    job = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(job, dict) or not isinstance(job.get("jobs"), dict) or set(job["jobs"]) != {"prepare", "train", "evaluate"}:
        _error("invalid_workload_bundle", "Only the approved canonical prepare/train/evaluate pipeline may be submitted.", 502)

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "code" and item != "./code":
                    _error("invalid_workload_bundle", "Every uploaded code reference must use only the verified local bundle.", 502)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(job)


@dataclass(frozen=True)
class WorkloadContext:
    settings: object
    scope_key: str
    arguments: WorkloadArgs | ModelArgs
    profile: WorkloadProfile
    template: Template
    target: Mapping[str, str]
    source_artifact_hash: str
    source_manifest: tuple[Mapping, ...] = ()


@dataclass(frozen=True)
class AdapterPlan:
    effects: tuple[str, ...]
    details: dict = field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterResult:
    execution_status: Literal["running", "succeeded", "failed"]
    data: dict


class WorkloadAdapter(ABC):
    @abstractmethod
    def plan(self, context: WorkloadContext) -> AdapterPlan: ...

    @abstractmethod
    def execute(self, context: WorkloadContext, plan: AdapterPlan) -> AdapterResult: ...

    @abstractmethod
    def status(self, context: WorkloadContext, receipt: dict) -> AdapterResult: ...


class WorkloadRegistry:
    def __init__(self, adapters: Mapping[str, WorkloadAdapter] | None = None):
        self._adapters = dict(adapters) if adapters is not None else {
            "prompt": PromptWorkloadAdapter(), "hosted": HostedWorkloadAdapter(), "azureml": AzureMLWorkloadAdapter(),
        }
        if any(key not in ("prompt", "hosted", "azureml") or not isinstance(value, WorkloadAdapter)
               for key, value in self._adapters.items()):
            raise ValueError("Only explicitly injected workload family strategies are permitted.")

    def resolve(self, family: str) -> WorkloadAdapter:
        adapter = self._adapters.get(family)
        if adapter is None:
            _error("workload_adapter_unconfigured", "The selected workload family has no configured strategy.", 503)
        return adapter


def _context(settings, scope_key, arguments, profile, template, source_hash, manifest=()):
    scope = settings.scopes[scope_key]
    return WorkloadContext(settings, scope_key, arguments, profile, template, MappingProxyType({
        "tenant_id": str(scope.tenant_id), "subscription_id": str(scope.subscription_id),
        "resource_group": scope.resource_group,
        "resource_group_id": f"/subscriptions/{scope.subscription_id}/resourceGroups/{scope.resource_group}",
        "project_resource_id": profile.project_resource_id, "environment": scope.environment,
    }), source_hash, tuple(MappingProxyType(dict(item)) for item in manifest))


def _target_config(context, config=None):
    config = _json_config(context.settings, context.profile.config_path) if config is None else config
    target = context.target
    if any(config.get(key) != target[key] for key in ("tenant_id", "subscription_id", "resource_group")):
        _error("workload_target_mismatch", "The approved provider configuration differs from the active project scope.", 403)
    if context.profile.kind == "agent":
        project_id = (target["resource_group_id"] + "/providers/Microsoft.CognitiveServices/accounts/"
                      + str(config.get("account_name", "")) + "/projects/" + str(config.get("project_name", "")))
        endpoint = f"https://{config.get('account_name', '')}.services.ai.azure.com/api/projects/{config.get('project_name', '')}"
        if (project_id != context.profile.project_resource_id or config.get("project_endpoint") != endpoint
                or config.get("location") != context.settings.location or not config.get("model_deployment")):
            _error("workload_target_mismatch", "Select an explicit canonical Foundry project endpoint, ARM ID, region and deployed model.", 403)
    else:
        workspace = target["resource_group_id"] + "/providers/Microsoft.MachineLearningServices/workspaces/" + str(config.get("workspace_name", ""))
        if (not config.get("workspace_name")
                or not re.fullmatch(_WORKSPACE, workspace)
                or context.profile.project_resource_id not in (target["resource_group_id"], workspace)):
            _error("workload_target_mismatch", "The explicit runtime workspace must match the approved project workspace or exact project resource group.", 403)
    return config


@dataclass(frozen=True)
class _VerifiedSourceLoader(Loader):
    path: Path
    source: bytes
    source_sha256: str

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__workload_source_sha256__ = self.source_sha256
        exec(compile(self.source, str(self.path), "exec", dont_inherit=True), module.__dict__)


@dataclass(frozen=True)
class _VerifiedProviderFinder(MetaPathFinder):
    alias: str
    root: Path
    artifact_hash: str
    sources: Mapping

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.alias + "."):
            return None
        names = fullname[len(self.alias) + 1:].split(".")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
            _error("workload_provider_source_mismatch", "Provider module names must belong to the approved source namespace.", 503)
        relative = Path(*names)
        candidates = (self.root / relative.with_suffix(".py"), self.root / relative / "__init__.py")
        selected = next((candidate for candidate in candidates if candidate in self.sources), None)
        if selected is None:
            _error("workload_provider_source_mismatch", "An imported provider module is absent from the approved source manifest.", 503)
        source, fingerprint = self.sources[selected]
        loader = _VerifiedSourceLoader(selected, source, fingerprint)
        return spec_from_file_location(
            fullname, selected, loader=loader,
            submodule_search_locations=[str(selected.parent)] if selected.name == "__init__.py" else None,
        )


class _ProviderAdapter(WorkloadAdapter):
    def __init__(self):
        self._modules = {}

    def _module(self, context, name):
        kind = context.profile.kind
        provider = "agent_factory" if kind == "agent" else "ml_model_factory"
        base = _root(context.settings) / "usecase_code" / ("40-agent-factory" if kind == "agent" else "50-ml-model-factory")
        package = base / provider
        # Static provider names under the hashed, server-approved root; never model-supplied modules.
        if name not in ("catalog", "config", "prompt", "hosted", "azureml", "tags", "storage_selection"):
            raise ValueError("Unsupported in-process provider module.")
        key = (str(package), context.source_artifact_hash, name)
        alias = ("_aifactory_workload_" + provider + "_"
                 + hashlib.sha256((str(package) + context.source_artifact_hash).encode()).hexdigest()[:20])
        expected = {
            _artifact_name(path, _root(context.settings)): path
            for path in _files(package, context.settings) if path.suffix == ".py"
        }
        pinned = {item["path"]: item for item in context.source_manifest}
        if not expected or not expected.keys() <= pinned.keys():
            _error("workload_provider_source_mismatch", "Provider execution requires manifest-pinned Python source files.", 503)
        for fullname, loaded in list(sys.modules.items()):
            if loaded is None or not (fullname == provider or fullname.startswith(provider + ".")):
                continue
            origin = getattr(loaded, "__file__", None)
            if origin is None and fullname == provider and hasattr(loaded, "__path__"):
                continue
            if not origin:
                _error("workload_provider_source_mismatch", "A globally loaded provider module has no verifiable source origin.", 503)
            names = fullname[len(provider) + 1:].split(".") if fullname != provider else []
            if not names and Path(origin).name != "__init__.py":
                _error("workload_provider_source_mismatch", "The globally loaded provider must be an approved source package.", 503)
            relative = Path(*names) if names else Path()
            target = package / relative / "__init__.py" if Path(origin).name == "__init__.py" else package / relative.with_suffix(".py")
            record = pinned.get(_artifact_name(target, _root(context.settings)))
            if record is None or not Path(origin).is_file():
                _error("workload_provider_source_mismatch", "A globally loaded provider version is outside the approved source manifest.", 503)
            data = _read_source(Path(origin), _workloads(context.settings))
            if hashlib.sha256(data).hexdigest() != record["sha256"] or len(data) != record["size"]:
                _error("workload_provider_source_mismatch", "Distinct provider source versions cannot share this agent process.", 503)
        if alias not in sys.modules:
            sources = {}
            for artifact, path in expected.items():
                data = _read_source(path, _workloads(context.settings))
                fingerprint = hashlib.sha256(data).hexdigest()
                if fingerprint != pinned[artifact]["sha256"] or len(data) != pinned[artifact]["size"]:
                    _error("workload_provider_source_mismatch", "Provider source changed before verified module loading.", 503)
                sources[path] = (data, fingerprint)
            finder = _VerifiedProviderFinder(alias, package, context.source_artifact_hash, MappingProxyType(sources))
            namespace = ModuleType(alias)
            namespace.__path__ = [str(package)]
            namespace.__package__ = alias
            namespace.__loader__ = finder
            sys.meta_path.insert(0, finder)
            sys.modules[alias] = namespace
        namespace = sys.modules[alias]
        finder = getattr(namespace, "__loader__", None)
        if (getattr(namespace, "__path__", None) != [str(package)]
                or not isinstance(finder, _VerifiedProviderFinder) or finder.root != package
                or finder.alias != alias or finder.artifact_hash != context.source_artifact_hash):
            _error("workload_provider_source_mismatch", "The loaded provider namespace differs from the approved source root/hash.", 503)
        if key not in self._modules:
            try:
                self._modules[key] = importlib.import_module(alias + "." + name)
            except ImportError:
                _error("dependency_missing", "Install the deployment's pinned provider dependencies before enabling this workload.", 503)
            except SyntaxError:
                _error("workload_provider_source_mismatch", "The approved provider source cannot be compiled.", 503)
        for fullname, loaded in list(sys.modules.items()):
            if not fullname.startswith(alias + ".") or loaded is None:
                continue
            origin = getattr(loaded, "__file__", None)
            loader = getattr(loaded, "__loader__", None)
            spec = getattr(loaded, "__spec__", None)
            spec_origin = getattr(spec, "origin", None)
            if (not origin or not isinstance(loader, _VerifiedSourceLoader)
                    or Path(origin) != loader.path or not spec_origin or Path(spec_origin) != loader.path
                    or loader.path not in finder.sources
                    or loader.source_sha256 != finder.sources[loader.path][1]
                    or loader.source_sha256 != pinned.get(
                        _artifact_name(loader.path, _root(context.settings)), {},
                    ).get("sha256")
                    or getattr(loaded, "__workload_source_sha256__", None) != loader.source_sha256):
                _error("workload_provider_source_mismatch", "Loaded provider code differs from the approved source path/fingerprint.", 503)
        return self._modules[key]

    @staticmethod
    def _dependencies(*names):
        for name in names:
            try:
                importlib.import_module(name)
            except ImportError:
                _error("dependency_missing", "A required pinned Azure workload dependency is unavailable; no installation was attempted.", 503)

    @staticmethod
    def _verify_sources(context):
        _, source_hash = _snapshot(context.settings, context.profile, context.template)
        if source_hash != context.source_artifact_hash:
            _error("plan_changed", "A workload input changed before provider submission; prepare and approve again.")

    @staticmethod
    def _output(context):
        parent = _approved_output(context.settings, context.profile)
        parent.mkdir(parents=True, exist_ok=True)
        output = parent / uuid4().hex
        output.mkdir()
        return output


class _VersionOnlyAgents:
    def __init__(self, agents):
        self._agents = agents

    def __getattr__(self, name):
        if name not in ("get", "get_version", "create_version", "create_version_from_code"):
            raise AttributeError(name)
        return getattr(self._agents, name)

    def update_details(self, **kwargs):
        # Existing purple deploy functions route implicitly. This boundary deliberately creates
        # versions only; endpoint promotion needs a distinct bounded approval.
        return None


class _VersionOnlyProject:
    def __init__(self, project):
        self.agents = _VersionOnlyAgents(project.agents)
        self.deployments = project.deployments


class PromptWorkloadAdapter(_ProviderAdapter):
    def _spec(self, context):
        if context.arguments.type != "41-single-agent":
            _error("unsupported_workload_strategy", "The prompt strategy supports only the actual 41-single-agent folder.", 503)
        catalog = self._module(context, "catalog").agent_catalog(context.profile.agent_prefix, expanded_tools=False)
        selected = [spec for spec in catalog if spec.get("name") == context.profile.catalog_selection]
        if len(selected) != 1 or selected[0].get("kind") != "prompt":
            _error("workload_selection_invalid", "The server must select exactly one supported prompt catalog spec.", 503)
        spec = copy.deepcopy(selected[0])
        if any(spec.get(key) for key in ("grounding", "knowledge_tool", "azure_inventory", "microsoft_docs")):
            _error("workload_prerequisite_required", "This spec requires separate bounded knowledge/MCP configuration; no fleet or MCP setup is implicit.", 503)
        return spec

    def plan(self, context):
        self._dependencies("azure.ai.projects.models", "azure.identity")
        config = _target_config(context)
        spec = self._spec(context)
        self._module(context, "prompt")
        try:
            self._module(context, "config").Target(**config)
        except (ValueError, TypeError):
            _error("workload_config_invalid", "The approved Foundry target does not match the provider's resolved target schema.", 503)
        return AdapterPlan(
            effects=("Create or reuse only one owned prompt-agent version in the approved Foundry project.",
                     "Do not change endpoint routing, create identities, configure MCP, deploy a fleet or change DNS."),
            details={"phase": "version_creation", "agent_name": spec["name"], "model_deployment": config["model_deployment"],
                     "catalog_selection": context.profile.catalog_selection, "routing": "not_requested"},
        )

    def _client(self, context, config):
        from azure.ai.projects import AIProjectClient
        from .config import credential
        return AIProjectClient(endpoint=config["project_endpoint"], credential=credential(context.settings))

    def execute(self, context, plan):
        config, spec = _target_config(context), self._spec(context)
        self._verify_sources(context)
        target = self._module(context, "config").Target(**config)
        client = self._client(context, config)
        try:
            result = self._module(context, "prompt").deploy_prompt(_VersionOnlyProject(client), target, spec)
        finally:
            client.close()
        return AdapterResult("succeeded", {
            "phase": "version_created", "agent_name": spec["name"], "version": str(result["version"]),
            "id": str(result["id"]), "routing": "not_requested", "framework": "prompt",
        })

    def status(self, context, receipt):
        data = receipt.get("data", {})
        if data.get("agent_name") != context.profile.catalog_selection or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(data.get("version", ""))):
            _error("invalid_workload_receipt", "Status requires the exact submitted agent name and version.", 502)
        client = self._client(context, _target_config(context))
        try:
            version = client.agents.get_version(agent_name=data["agent_name"], agent_version=data["version"])
        finally:
            client.close()
        state = str(version.status)
        execution = "succeeded" if state == "active" else "failed" if state in ("failed", "deleted", "deleting") else "running"
        return AdapterResult(execution, {**{key: data[key] for key in ("agent_name", "version")},
                                        "phase": "version_observation", "provider_status": state, "routing": "not_requested"})


class HostedWorkloadAdapter(PromptWorkloadAdapter):
    def _spec(self, context):
        catalog = self._module(context, "catalog").agent_catalog(context.profile.agent_prefix, expanded_tools=False)
        selected = [spec for spec in catalog if spec.get("name") == context.profile.catalog_selection]
        if len(selected) != 1 or selected[0].get("kind") != "hosted":
            _error("workload_selection_invalid", "The server must select exactly one supported hosted catalog spec.", 503)
        spec = copy.deepcopy(selected[0])
        expected_type = "42-multi-agent" if spec.get("framework") == "multi-agent" else "41-single-agent"
        if context.arguments.type != expected_type:
            _error("unsupported_workload_strategy", "The selected hosted spec does not belong to the exact immediate workload folder.", 503)
        config = _target_config(context)
        spec["model"] = config["model_deployment"]
        return spec

    def _runtime(self, context):
        runtime = _json_config(context.settings, context.profile.hosted_runtime_path)
        expected = {"cpu": "0.5", "memory": "1Gi", "runtime": "python_3_13", "protocol": "responses/2.0.0",
                    "dependency_resolution": "remote_build", "approved_source_upload": True,
                    "timeout_seconds": 900}
        if runtime != expected:
            _error("hosted_runtime_unapproved", "Approve the purple provider's exact hosted runtime, CPU, memory, timeout and first-party code upload; no guessed cost/runtime.", 503)
        return runtime

    def plan(self, context):
        self._dependencies("azure.ai.projects.models", "azure.identity")
        spec, runtime = self._spec(context), self._runtime(context)
        try:
            self._module(context, "hosted")._normalize(spec)
            self._module(context, "config").Target(**_target_config(context))
        except (ValueError, TypeError):
            _error("workload_config_invalid", "The hosted spec/target does not match the approved provider schema.", 503)
        return AdapterPlan(
            effects=("Create/reuse one owned hosted-agent version using the explicitly approved first-party Foundry build runtime.",
                     "Read only existing same-project participants; do not create a fleet, identities, MCP infrastructure, DNS or routes."),
            details={"phase": "version_creation", "agent_name": spec["name"], "framework": spec["framework"],
                     "existing_participants": [item["name"] for item in spec.get("members", [])],
                     "runtime": runtime, "routing": "not_requested"},
        )

    def execute(self, context, plan):
        config, spec, runtime = _target_config(context), self._spec(context), self._runtime(context)
        self._verify_sources(context)
        target = self._module(context, "config").Target(**config)
        client = self._client(context, config)
        try:
            result = self._module(context, "hosted").deploy_hosted(
                _VersionOnlyProject(client), target, spec, output_dir=self._output(context),
                timeout_seconds=runtime["timeout_seconds"],
            )
        finally:
            client.close()
        return AdapterResult("succeeded", {"phase": "version_created", "agent_name": spec["name"],
                                          "version": str(result["version"]), "id": str(result["id"]),
                                          "framework": spec["framework"], "routing": "not_requested"})


class AzureMLWorkloadAdapter(_ProviderAdapter):
    def _inputs(self, context, captured=None):
        root = _root(context.settings)

        def document(relative):
            if captured is None:
                return _json_config(context.settings, relative)
            path = root / _relative(relative)
            if path not in captured:
                _error("plan_changed", "A required provider configuration is absent from the approved captured inputs.")
            return _parse_config(captured[path])

        runtime = _target_config(context, document(context.profile.config_path))
        model_root = root / "usecase_code" / "50-ml-model-factory"
        scenario_path = root / _relative(context.profile.scenario_path)
        if scenario_path.parent != model_root / "scenarios" or scenario_path.suffix != ".json":
            _error("workload_selection_invalid", "Select one canonical immediate ml-model-factory scenario JSON.", 503)
        scenario = document(context.profile.scenario_path)
        expected = {"classification": ("classification",), "regression": ("regression",),
                    "timeseries-forecasting": ("forecasting",),
                    "computer-vision": ("image_classification", "image_classification_multilabel",
                                        "image_object_detection", "image_instance_segmentation")}
        if scenario.get("task") not in expected.get(context.arguments.type, ()):
            _error("workload_selection_invalid", "The canonical training scenario does not match the selected immediate model type.", 503)
        required = ("compute", "environment", "input_data", "credential")
        if any(not runtime.get(key) for key in required):
            _error("workload_runtime_required", "Approve exact existing compute, pinned environment, data asset and credential mode before submission.", 503)
        if runtime["credential"] not in ("managed_identity", "azure_cli"):
            _error("workload_runtime_required", "Use an explicit approved Azure credential mode.", 503)
        if (not isinstance(runtime["environment"], str)
                or not re.fullmatch(r"azureml:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", runtime["environment"])
                or runtime["environment"].rsplit(":", 1)[-1].casefold() in ("latest", "default")):
            _error("workload_runtime_required", "The server runtime must pin an existing Azure ML environment name/version.", 503)
        if (not isinstance(runtime["input_data"], str) or not runtime["input_data"].startswith("azureml:")
                or any(marker in json.dumps(runtime) for marker in ("REPLACE_WITH_", "<existing", "${"))):
            _error("workload_runtime_required", "Supply an explicitly approved resolved Azure ML data asset/URI; no placeholders or implicit data upload.", 503)
        if runtime.get("lake"):
            _error("workload_output_scope_unapproved", "Lake publishing/output paths require a separate bounded storage approval; this skill submits workspace training only.", 503)
        try:
            storage = self._module(context, "storage_selection").selected_profile(runtime)
        except (ValueError, TypeError):
            _error("workload_config_invalid", "The runtime storage selection does not satisfy the provider's explicit profile contract.", 503)
        if storage is not None and storage.get("resource_group") != context.target["resource_group"]:
            _error("workload_output_scope_unapproved", "Workload training may not implicitly write to storage outside the approved project resource group.", 503)
        if (scenario["task"].startswith("image_") and scenario.get("vision", {}).get("device") != "cpu"
                and not runtime.get("gpu_compute")):
            _error("workload_runtime_required", "Approve an explicit existing GPU compute for this vision training profile.", 503)
        config = self._module(context, "config")
        try:
            config.validate_runtime(runtime)
            config.validate_scenario(scenario)
            tags = self._module(context, "tags").scope_tags(runtime, require=True)
        except (ValueError, TypeError):
            _error("workload_config_invalid", "The canonical model scenario/runtime does not satisfy the provider's validated schema.", 503)
        scope = context.settings.scopes[context.scope_key]
        if tags != {"aifactory": scope.factory, "project": scope.project, "environment": scope.environment}:
            _error("workload_target_mismatch", "Model lineage must name the active factory/project/environment, not another scope.", 403)
        for name in ("pyproject.toml", "scripts\\azureml_prepare.py", "scripts\\azureml_evaluate.py",
                     "scripts\\azureml_sdk.py", "scripts\\azureml_cli.py", "environments\\azureml-custom.yml",
                     "environments\\azureml-automl.yml", "environments\\azureml-vision.yml"):
            relative = str(model_root.relative_to(root) / name)
            if captured is None:
                _path(root, relative)
            elif root / _relative(relative) not in captured:
                _error("plan_changed", "A required rendering script/environment is absent from the approved captured inputs.")
        if scenario["task"].startswith("image_") and context.profile.training_mode == "automl":
            _error("unsupported_workload_training", "AutoML vision has no gated creation pipeline here; configure an explicit supported custom training profile.", 503)
        return scenario, runtime, model_root

    def plan(self, context):
        self._dependencies("azure.ai.ml", "azure.identity", "yaml")
        scenario, runtime, _ = self._inputs(context)
        self._module(context, "azureml")
        return AdapterPlan(
            effects=("Render the approved source bundle and submit only its canonical Azure ML training/evaluation pipeline to the exact workspace.",
                     "Submission is asynchronous, not a completed model; do not register, serve, route or promote a model."),
            details={"phase": "training_submission", "scenario_name": scenario["name"], "task": scenario["task"],
                     "training_mode": context.profile.training_mode, "compute": runtime["compute"],
                     "gpu_compute": runtime.get("gpu_compute"), "workspace_name": runtime["workspace_name"],
                     "environment": runtime["environment"], "input_data": runtime["input_data"],
                     "serving_mode": context.profile.serving_mode, "model_created": False,
                     "registration_status": "not_requested", "serving_status": "not_requested",
                     "training_configuration": copy.deepcopy(scenario.get(context.profile.training_mode, {})),
                     "quality_gates": copy.deepcopy(scenario.get("quality", {}))},
        )

    def execute(self, context, plan):
        captured = _capture_approved_inputs(context)
        scenario, runtime, source = self._inputs(context, captured)
        provider = self._module(context, "azureml")
        work = self._output(context)
        stage, output = work / "approved-source", work / "rendered"
        source_files = {path.relative_to(source): data for path, data in captured.items() if path.is_relative_to(source)}
        package = source / "ml_model_factory"
        code_files = {
            Path("ml_model_factory") / path.relative_to(package): data
            for path, data in captured.items() if path.is_relative_to(package)
        }
        code_files[Path("pyproject.toml")] = captured[source / "pyproject.toml"]
        for name in ("azureml_prepare.py", "azureml_evaluate.py", "azureml_sdk.py", "azureml_cli.py"):
            code_files[Path("scripts") / name] = captured[source / "scripts" / name]
        rendered_scenario = copy.deepcopy(scenario)
        if rendered_scenario["task"].startswith("image_"):
            if rendered_scenario.get("vision", {}).get("image_base_uri"):
                rendered_scenario["vision"]["image_base_uri"] = provider.resolve_location(
                    rendered_scenario["vision"]["image_base_uri"], runtime,
                )
            rendered_scenario.setdefault("target", "label")
        tags = self._module(context, "tags").build_tags(rendered_scenario, runtime, mode=context.profile.training_mode, engine="azureml")
        for name, value in (("scenario.json", rendered_scenario), ("model-tags.json", tags)):
            _credential_free(value)
            code_files[Path(name)] = json.dumps(value, indent=2).replace("\n", os.linesep).encode("utf-8")
        try:
            _write_immutable_tree(stage, source_files)
            files = provider.render(scenario, runtime, output, stage, mode=context.profile.training_mode)
            if not files.get("pipeline_job"):
                _error("unsupported_workload_training", "This scenario has no canonical gated training pipeline; nothing was submitted.", 503)
            job_path = Path(files["pipeline_job"])
            if job_path.resolve() != (output / "pipeline.yml").resolve():
                _error("invalid_workload_bundle", "The provider must submit only the bounded rendered pipeline file.", 502)
            for path in _files(output, context.settings, strict=True):
                path.chmod(0o444)
            for path in sorted(output.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                if path.is_dir():
                    path.chmod(0o555)
            output.chmod(0o555)
            _verify_exact_tree(stage, source_files, context.settings)
            bundle_hash = _verify_exact_tree(output / "code", code_files, context.settings)
            _verify_pipeline_code(job_path)
            pipeline_hash = hashlib.sha256(_read_source(job_path, _workloads(context.settings))).hexdigest()
            job_name = provider.submit(job_path, runtime)
        finally:
            _remove_owned_tree(work)
        if not isinstance(job_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", job_name):
            _error("invalid_workload_receipt", "Azure ML did not return a bounded submitted job name.", 502)
        workspace = context.target["resource_group_id"] + "/providers/Microsoft.MachineLearningServices/workspaces/" + runtime["workspace_name"]
        return AdapterResult("running", {
            **plan.details, "job_name": job_name, "job_resource_id": workspace + "/jobs/" + job_name,
            "provider_status": "submitted", "model_created": False,
            "registration_status": "not_requested", "serving_status": "not_requested",
            "uploaded_source_artifact_hash": context.source_artifact_hash, "code_bundle_hash": bundle_hash,
            "pipeline_artifact_hash": pipeline_hash,
        })

    def status(self, context, receipt):
        data = receipt.get("data", {})
        runtime = _target_config(context)
        name = data.get("job_name")
        workspace = context.target["resource_group_id"] + "/providers/Microsoft.MachineLearningServices/workspaces/" + runtime["workspace_name"]
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", name)
                or data.get("job_resource_id") != workspace + "/jobs/" + name):
            _error("invalid_workload_receipt", "Status requires the exact submitted job in the approved runtime workspace.", 502)
        provider = self._module(context, "azureml")
        client = provider._client(runtime)
        job = client.jobs.get(name)
        if getattr(job, "id", data["job_resource_id"]) != data["job_resource_id"]:
            _error("invalid_workload_receipt", "Azure ML returned a job outside the reviewed workspace/job identity.", 502)
        state = str(job.status)
        execution = "succeeded" if state == "Completed" else "failed" if state in ("Failed", "Canceled", "NotResponding") else "running"
        return AdapterResult(execution, {
            "phase": "training_complete" if state == "Completed" else "training_observation",
            "job_name": name, "job_resource_id": data["job_resource_id"], "provider_status": state,
            "model_created": False, "registration_status": "not_requested", "serving_status": "not_requested",
        })


_REQUEST_KEYS = frozenset({"contract_version", "arguments", "profile_id", "family", "profile_hash",
                           "source_manifest", "source_artifact_hash"})
_PREVIEW_KEYS = frozenset({"contract_version", "can_execute", "expires_at", "target", "profile_id", "family",
                           "source_artifact_hash", "effects", "warnings", "blockers", "execution", "summary"})


def validate_workload_plan(settings, scope_key, tool_name, request, preview):
    required_permission(tool_name)
    if (not isinstance(request, dict) or set(request) != _REQUEST_KEYS
            or not isinstance(preview, dict) or set(preview) != _PREVIEW_KEYS
            or type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or type(preview.get("contract_version")) is not int or preview["contract_version"] != 1):
        _error("invalid_workload_plan", "The workload plan must use the exact closed contract-1 schema.", 400)
    arguments = argument_model(tool_name).model_validate(request["arguments"])
    profile, template = _select_profile(settings, scope_key, tool_name, arguments, FileSystemTemplateCatalog(settings))
    manifest, source_hash = _snapshot(settings, profile, template)
    context = _context(settings, scope_key, arguments, profile, template, source_hash, manifest)
    _target_config(context)
    if (request["profile_id"] != profile.profile_id or request["family"] != profile.family
            or request["profile_hash"] != _hash(profile.model_dump(mode="json"))
            or request["source_manifest"] != manifest or request["source_artifact_hash"] != source_hash
            or preview["profile_id"] != profile.profile_id or preview["family"] != profile.family
            or preview["source_artifact_hash"] != source_hash or preview["target"] != dict(context.target)):
        _error("plan_changed", "The approved workload type, exact target, server profile or source artifacts changed; prepare again.")
    if (preview["can_execute"] is not True or preview["blockers"] != []
            or not isinstance(preview["execution"], dict) or not isinstance(preview["summary"], str)
            or not isinstance(preview["effects"], list) or not preview["effects"]
            or any(not isinstance(item, str) for item in preview["effects"])
            or not isinstance(preview["warnings"], list) or any(not isinstance(item, str) for item in preview["warnings"])
            or _safe(request) != request or _safe(preview) != preview):
        _error("invalid_workload_plan", "Only an executable, secret-free, explicitly bounded workload review may be persisted.", 400)
    try:
        expires = datetime.fromisoformat(preview["expires_at"])
    except (ValueError, TypeError):
        _error("invalid_workload_plan", "The workload review requires a timezone-aware expiry.", 400)
    if expires.tzinfo is None:
        _error("invalid_workload_plan", "The workload review requires a timezone-aware expiry.", 400)
    return context


def plan_details(settings, scope_key, tool_name, request, preview):
    context = validate_workload_plan(settings, scope_key, tool_name, request, preview)
    affected = [{
        "kind": "foundry-agent-version" if tool_name == AGENT_CREATE else "azureml-training-job",
        **dict(context.target), "type": context.arguments.type, "family": context.profile.family,
        "serving_mode": context.profile.serving_mode, "profile_id": context.profile.profile_id,
        "source_artifact_hash": context.source_artifact_hash,
    }]
    if tool_name == MODEL_CREATE:
        affected[0].update({"model_registration": False, "model_serving": False})
    else:
        affected[0]["endpoint_routing"] = False
    return _safe(preview), _safe(affected)


def package_sources(settings) -> Iterable[tuple[Path, str]]:
    """Thin cloud bundles discover only the approved immediate template types included here.

    Runtime agent/CLI code is hashed independently and already packaged by deploy.py.
    """
    workloads = _workloads(settings)
    if not workloads.profiles:
        return
    root = _root(settings)
    catalog = FileSystemTemplateCatalog(settings)
    packaged = {}
    for profiles in workloads.profiles.values():
        for profile in profiles:
            template = catalog.resolve(profile.kind, profile.type, profile.serving_mode)
            _snapshot(settings, profile, template)
            references = {
                _path(root, relative)
                for relative in (profile.config_path, profile.scenario_path, profile.hosted_runtime_path)
                if relative is not None
            }
            for path in references:
                _json_config(settings, str(path.relative_to(root)))
            for path in _profile_input_paths(settings, profile, template):
                source_relative = path.relative_to(root)
                relative = str(Path("workload_sources") / source_relative)
                packaged[relative] = path
    for relative, path in sorted(packaged.items()):
        yield path, relative


class WorkloadSkills:
    def __init__(self, settings, principal, scope_key, operation_store: OperationStorePort | None,
                 registry: WorkloadRegistry | None = None, catalog: TemplateCatalog | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.settings, self.principal, self.scope_key = settings, principal, scope_key
        self.operation_store = operation_store
        self.registry = registry if registry is not None else WorkloadRegistry()
        self.catalog: TemplateCatalog = catalog if catalog is not None else FileSystemTemplateCatalog(settings)
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def _now(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("The workload clock must return a timezone-aware datetime.")
        return now.astimezone(timezone.utc)

    def _authorize(self, permission):
        from .security import authorize
        return authorize(self.settings, self.principal, self.scope_key, permission)

    def _gate(self, name):
        scope = self._authorize(required_permission(name))
        self._authorize("factory.read")
        if name not in _workloads(self.settings).enabled_skills:
            _error("skill_disabled", "This workload skill is disabled by the server deployment operator.", 503)
        if not self.settings.factory.writes_enabled:
            _error("writes_disabled", "Factory workload writes are disabled.", 503)
        if scope.environment not in self.settings.factory.allowed_write_environments:
            _error("environment_not_enabled", "Workload writes are not enabled for this environment.", 403)

    def prepare(self, name, args):
        self._gate(name)
        arguments = argument_model(name).model_validate(args)
        if self.operation_store is None:
            _error("operation_store_required", "Signed durable operation storage is required before workload preparation.", 503)
        self.operation_store.ensure_ready()
        profile, template = _select_profile(self.settings, self.scope_key, name, arguments, self.catalog)
        manifest, source_hash = _snapshot(self.settings, profile, template)
        context = _context(self.settings, self.scope_key, arguments, profile, template, source_hash, manifest)
        _target_config(context)
        plan = self.registry.resolve(profile.family).plan(context)
        if not isinstance(plan, AdapterPlan):
            _error("invalid_workload_plan", "The injected workload strategy did not return a typed plan.", 502)
        if plan.blockers:
            _error(plan.blockers[0], "The workload provider explicitly blocked this plan; no write was proposed.", 503)
        request = {
            "contract_version": 1, "arguments": arguments.model_dump(mode="json"),
            "profile_id": profile.profile_id, "family": profile.family,
            "profile_hash": _hash(profile.model_dump(mode="json")),
            "source_manifest": manifest, "source_artifact_hash": source_hash,
        }
        preview = {
            "contract_version": 1, "can_execute": True,
            "expires_at": (self._now() + timedelta(seconds=_workloads(self.settings).plan_ttl_seconds)).isoformat(),
            "target": dict(context.target), "profile_id": profile.profile_id, "family": profile.family,
            "source_artifact_hash": source_hash, "effects": list(plan.effects), "warnings": list(plan.warnings),
            "blockers": [], "execution": copy.deepcopy(plan.details),
            "summary": ("Create one approved agent version; no fleet, infrastructure or endpoint routing."
                        if name == AGENT_CREATE else "Submit approved training asynchronously; registration and serving are not authorized."),
        }
        validate_workload_plan(self.settings, self.scope_key, name, request, preview)
        return self.operation_store.propose(self.principal, self.scope_key, name, request, preview)

    def _record(self, record, *, executing=False):
        from azurefactory.client import validate_base_url
        from .operations import plan_hash
        if (not isinstance(record, dict) or record.get("tenant_id") != self.principal.tenant_id
                or record.get("object_id") != self.principal.object_id or record.get("scope_key") != self.scope_key
                or record.get("agent_namespace") != getattr(self.operation_store, "namespace", None)
                or record.get("tool_name") not in WORKLOAD_SKILLS
                or record.get("scope") != self.settings.scopes[self.scope_key].model_dump(mode="json")
                or record.get("factory_api_url") != validate_base_url(self.settings.factory.api_url)):
            _error("invalid_execution", "Only this caller's exact persisted scope-bound workload operation is accepted.", 403)
        if (any(key not in record for key in ("id", "correlation_id", "request", "preview", "created_at",
                                              "expires_at", "affected_resources", "plan_hash"))
                or record["plan_hash"] != plan_hash(record)):
            _error("plan_changed", "The persisted workload approval plan changed.")
        self._authorize("factory.read")
        self._authorize(required_permission(record["tool_name"]))
        if executing:
            approval = record.get("approval")
            if (record.get("status") != "executing" or not isinstance(approval, dict)
                    or any(approval.get(key) != record[key] for key in ("tenant_id", "object_id", "plan_hash"))
                    or not approval.get("approved_at")):
                _error("approval_required", "The exact persisted workload plan must be approved and single-use claimed before execution.", 403)
            try:
                deadline = datetime.fromisoformat(record["expires_at"])
                reviewed_deadline = datetime.fromisoformat(record["preview"]["expires_at"])
            except (TypeError, ValueError, KeyError):
                _error("plan_expired", "The persisted workload approval has an invalid expiry.")
            if (deadline.tzinfo is None or reviewed_deadline.tzinfo is None
                    or deadline > reviewed_deadline or deadline <= self._now()):
                _error("plan_expired", "The persisted workload approval expired; prepare again.")
        return validate_workload_plan(self.settings, self.scope_key, record["tool_name"], record["request"], record["preview"])

    def _envelope(self, context, result):
        if (not isinstance(result, AdapterResult) or result.execution_status not in ("running", "succeeded", "failed")
                or not isinstance(result.data, dict)):
            _error("invalid_workload_receipt", "The provider returned an invalid typed execution observation.", 502)
        if (result.data.get("type", context.arguments.type) != context.arguments.type
                or result.data.get("project_resource_id", context.arguments.project_resource_id) != context.arguments.project_resource_id):
            _error("invalid_workload_receipt", "The provider changed the approved workload type or exact project target.", 502)
        if (context.profile.kind == "model" and result.data.get("phase") == "training_submission"
                and (result.execution_status == "succeeded" or result.data.get("model_created", False))):
            _error("invalid_workload_receipt", "An asynchronous training submission cannot claim a completed model.", 502)
        return {"ok": True, "scope_key": self.scope_key,
                "data": _safe({**result.data, "type": context.arguments.type,
                               "project_resource_id": context.arguments.project_resource_id}),
                "execution_status": result.execution_status}

    def execute_operation(self, record):
        from azure.core.exceptions import AzureError
        from .operations import OperationError
        from .tools import ToolError
        write_started = False
        try:
            context = self._record(record, executing=True)
            self._gate(record["tool_name"])
            adapter = self.registry.resolve(context.profile.family)
            plan = adapter.plan(context)
            if (not isinstance(plan, AdapterPlan) or plan.blockers
                    or plan.details != record["preview"]["execution"] or list(plan.effects) != record["preview"]["effects"]
                    or list(plan.warnings) != record["preview"]["warnings"]):
                _error("plan_changed", "The provider execution effects or runtime changed after review; prepare again.")
            _, current_hash = _snapshot(self.settings, context.profile, context.template)
            if current_hash != context.source_artifact_hash:
                _error("plan_changed", "A source/configuration artifact changed during provider revalidation; prepare again.")
            write_started = True
            result = adapter.execute(context, plan)
            if isinstance(result, AdapterResult) and result.execution_status == "failed":
                raise OperationError("workload_execution_failed", "The approved workload provider reported a failed execution.", 502)
            return self._envelope(context, result)
        except OperationError:
            raise
        except ToolError as exc:
            message = ("The provider result could not be confirmed; do not replay this approval."
                       if write_started else str(exc))
            raise OperationError(exc.code, message, exc.status_code, uncertain=write_started) from None
        except (AzureError, TimeoutError, ConnectionError, OSError):
            raise OperationError(
                "workload_submission_uncertain" if write_started else "workload_validation_unavailable",
                ("Provider completion could not be confirmed; do not replay this approval."
                 if write_started else "Workload validation was unavailable; no provider execution was attempted."),
                503, uncertain=write_started,
            ) from None
        except ImportError:
            raise OperationError(
                "dependency_missing", "A pinned workload dependency disappeared; no installation was attempted.",
                503, uncertain=write_started,
            ) from None
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError):
            raise OperationError(
                "workload_provider_contract_invalid",
                ("Provider completion is unknown because its result contract was invalid; do not replay this approval."
                 if write_started else "The provider rejected the approved workload inputs before execution."),
                502, uncertain=write_started,
            ) from None

    def status(self, record):
        from azure.core.exceptions import AzureError
        context = self._record(record)
        if record.get("status") in ("pending", "approved", "canceled", "cancelled", "expired"):
            return {"ok": True, "scope_key": self.scope_key,
                    "data": {"phase": "not_submitted", "operation_status": record["status"]}}
        receipt = record.get("outcome")
        if not isinstance(receipt, dict):
            _error("workload_status_unavailable", "No confirmed provider submission receipt is persisted; do not replay execution.", 503)
        try:
            result = self.registry.resolve(context.profile.family).status(context, copy.deepcopy(receipt))
            return self._envelope(context, result)
        except (AzureError, TimeoutError, ConnectionError, OSError):
            _error("workload_status_unavailable", "The approved provider workload could not be safely observed; no write was attempted.", 503)

    def templates(self):
        from .tools import ToolError
        self._authorize("factory.read")
        result = []
        for discovered in self.catalog.types():
            name = AGENT_CREATE if discovered["kind"] == "agent" else MODEL_CREATE
            profiles = [item for item in _workloads(self.settings).profiles.get(self.scope_key, [])
                        if (item.kind, item.type, item.serving_mode) == (
                            discovered["kind"], discovered["type"], discovered["mode"])]
            record = copy.deepcopy(discovered)
            blockers = []
            if len(profiles) != 1:
                blockers.append("workload_profile_required")
            else:
                record["family"] = profiles[0].family
                record["profile_id"] = profiles[0].profile_id
                record["project_resource_id"] = profiles[0].project_resource_id
            if name not in _workloads(self.settings).enabled_skills:
                blockers.append("skill_disabled")
            if not self.settings.factory.writes_enabled:
                blockers.append("writes_disabled")
            if self.settings.scopes[self.scope_key].environment not in self.settings.factory.allowed_write_environments:
                blockers.append("environment_not_enabled")
            try:
                self._authorize(required_permission(name))
            except PermissionError:
                blockers.append("permission_required")
            if not blockers:
                profile = profiles[0]
                values = {"type": profile.type, "project_resource_id": profile.project_resource_id}
                if profile.kind == "model":
                    values["serving_mode"] = profile.serving_mode
                try:
                    arguments = argument_model(name).model_validate(values)
                    approved, template = _select_profile(self.settings, self.scope_key, name, arguments, self.catalog)
                    manifest, source_hash = _snapshot(self.settings, approved, template)
                    context = _context(self.settings, self.scope_key, arguments, approved, template, source_hash, manifest)
                    _target_config(context)
                    plan = self.registry.resolve(profile.family).plan(context)
                    if not isinstance(plan, AdapterPlan):
                        blockers.append("invalid_workload_plan")
                    else:
                        blockers.extend(plan.blockers)
                except ToolError as exc:
                    blockers.append(exc.code)
                except ValidationError:
                    blockers.append("workload_config_invalid")
            record.update({"available": not blockers, "blockers": blockers})
            result.append(record)
        return _safe(result)

    def discover(self) -> list[dict]:
        """Scoped UI records; configuration/dependency blockers never imply deployability."""
        return [
            {**record, "serving_mode": record["mode"],
             "arguments_schema": argument_model(
                 AGENT_CREATE if record["kind"] == "agent" else MODEL_CREATE,
             ).model_json_schema()}
            for record in self.templates()
        ]
