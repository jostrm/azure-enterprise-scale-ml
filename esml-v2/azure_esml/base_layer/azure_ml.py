"""Azure ML v2 SDK and CLI adapters with explicit workspace and identity selection."""

from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from enum import Enum
from io import StringIO
from itertools import islice
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

import yaml

from .contracts import MLBackend, WorkspaceTarget


def _name(value, field="name") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError(f"{field} must be a nonempty safe identifier")
    return value


def _version(value) -> str:
    version = _name(value, "version")
    if version.lower() in {"latest", "active", "0"}:
        raise ValueError("An explicit, nonzero version is required, not a label")
    return version


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    return limit


def _document(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("A dictionary document is required")
    def plain(item):
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain(child) for child in item]
        return deepcopy(item)
    return plain(value)


def _tags(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("tags must map strings to strings")
    return dict(value)


def _field(obj, name, default=None):
    value = obj[name] if isinstance(obj, dict) and name in obj else getattr(obj, name, default)
    return value.value if isinstance(value, Enum) else value


def _public(value):
    if isinstance(value, dict):
        return {
            key: _public(item) for key, item in value.items()
            if not re.search(r"secret|password|credential|token|signature|connection.?string|account.?key|authorization",
                             str(key), re.IGNORECASE)
        }
    if isinstance(value, str) and "://" in value:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    return value


def _require_named(obj) -> None:
    if not isinstance(_field(obj, "name"), str) or not _field(obj, "name"):
        raise TypeError("Azure ML must return a named resource")


def _job(obj) -> dict:
    _require_named(obj)
    outputs = {}
    for key, value in (_field(obj, "outputs") or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            outputs[key] = value
        else:
            outputs[key] = {field: _field(value, field) for field in ("type", "path", "mode")}
    return _public({
        **{key: _field(obj, key) for key in ("name", "id", "status", "experiment_name", "type")},
        "tags": dict(_field(obj, "tags") or {}),
        "outputs": outputs,
        "jobs": {
            key: {"type": _field(value, "type")}
            for key, value in (_field(obj, "jobs") or {}).items()
        },
    })


def _asset(obj) -> dict:
    _require_named(obj)
    return _public({
        **{key: _field(obj, key) for key in ("name", "id", "version", "path", "type")},
        "tags": dict(_field(obj, "tags") or {}),
    })


def _datastore(obj) -> dict:
    _require_named(obj)
    fields = ("name", "id", "type", "account_name", "container_name", "filesystem", "endpoint", "protocol")
    return _public({
        **{key: _field(obj, key) for key in fields}, "type": _store_type(obj),
        "tags": dict(_field(obj, "tags") or {}),
    })


def _store_type(obj):
    value = _field(obj, "type")
    return {"AzureBlob": "azure_blob", "AzureDataLakeGen2": "azure_data_lake_gen2"}.get(value, value)


def _credentialless(credentials) -> bool:
    if credentials is None:
        return True
    if isinstance(credentials, dict):
        return set(credentials) == {"type"} and str(credentials["type"]).lower() == "none"
    from azure.ai.ml.entities import NoneCredentialConfiguration

    return isinstance(credentials, NoneCredentialConfiguration)


def _datastore_definition(definition: dict) -> dict:
    doc = _document(definition)
    doc.pop("$schema", None)
    credentials = doc.pop("credentials", None)
    if credentials != {} and not _credentialless(credentials):
        raise ValueError("Only credentialless datastores are supported")
    store_type = doc.get("type")
    if store_type not in {"azure_blob", "azure_data_lake_gen2"}:
        raise ValueError("Datastore type must be azure_blob or azure_data_lake_gen2")
    location = "container_name" if store_type == "azure_blob" else "filesystem"
    allowed = {"type", "name", "account_name", location, "description", "tags", "endpoint", "protocol"}
    if set(doc) - allowed:
        raise ValueError(f"Unsupported datastore fields: {sorted(set(doc) - allowed)}")
    for field in ("name", "account_name", location):
        doc[field] = _name(doc.get(field), field)
    doc["endpoint"] = doc.get("endpoint", "core.windows.net")
    if not isinstance(doc["endpoint"], str) or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", doc["endpoint"]):
        raise ValueError("Datastore endpoint must be a DNS suffix")
    doc["protocol"] = doc.get("protocol", "https")
    if doc["protocol"] != "https":
        raise ValueError("Credentialless datastore connections must use https")
    doc["tags"] = _tags(doc.get("tags"))
    return doc


def _match_datastore(existing, doc: dict) -> None:
    location = "container_name" if doc["type"] == "azure_blob" else "filesystem"
    if not _credentialless(_field(existing, "credentials")) or _store_type(existing) != doc["type"] or any(
        _field(existing, key) != doc[key] for key in ("name", "account_name", location)
    ):
        raise ValueError("Existing datastore target or credentials differ; refusing to overwrite")
    if any(
        (_field(existing, key) or default) != doc[key]
        for key, default in (("endpoint", "core.windows.net"), ("protocol", "https"))
    ):
        raise ValueError("Existing datastore endpoint or protocol differs; refusing to overwrite")


def _data_definition(definition: dict) -> dict:
    doc = _document(definition)
    doc.pop("$schema", None)
    allowed = {"name", "version", "type", "path", "tags", "description"}
    if set(doc) - allowed:
        raise ValueError(f"Unsupported data fields: {sorted(set(doc) - allowed)}")
    doc["name"], doc["version"] = _name(doc.get("name")), _version(doc.get("version"))
    if doc.get("type") not in {"uri_folder", "uri_file", "mltable"}:
        raise ValueError("Data type must be uri_folder, uri_file or mltable")
    if not isinstance(doc.get("path"), str) or not doc["path"].strip():
        raise ValueError("Data path must be a nonempty string")
    doc["path"] = doc["path"].strip()
    doc["tags"] = _tags(doc.get("tags"))
    return doc


def _match_data(existing, doc: dict) -> None:
    if any(_field(existing, key) != doc[key] for key in ("name", "version", "path", "type")):
        raise ValueError("Existing data version differs; refusing to overwrite")
    tags = _field(existing, "tags") or {}
    if tags != doc["tags"]:
        raise ValueError("Existing data version tags differ; refusing to overwrite")


def _model_definition(definition: dict) -> dict:
    doc = _document(definition)
    doc.pop("$schema", None)
    allowed = {"name", "version", "type", "path", "tags", "description"}
    if set(doc) - allowed:
        raise ValueError(f"Unsupported model fields: {sorted(set(doc) - allowed)}")
    doc["name"] = _name(doc.get("name"))
    if "version" in doc:
        doc["version"] = _version(doc["version"])
    if doc.get("type") not in {"custom_model", "mlflow_model", "triton_model"}:
        raise ValueError("Model type must be custom_model, mlflow_model or triton_model")
    if not isinstance(doc.get("path"), str) or not doc["path"].strip():
        raise ValueError("Model path must be a nonempty string")
    doc["path"] = doc["path"].strip()
    doc["tags"] = _tags(doc.get("tags"))
    return doc


def _publication(component: dict, endpoint: dict, deployment: dict) -> tuple[dict, dict, dict]:
    component, endpoint, deployment = map(_document, (component, endpoint, deployment))
    component["name"] = _name(component.get("name"))
    component["version"] = _version(component.get("version"))
    if component.get("type") != "pipeline":
        raise ValueError("Batch publication requires a pipeline component")
    for doc, allowed in (
        (endpoint, {"name", "description", "tags"}),
        (deployment, {"name", "description", "tags", "settings"}),
    ):
        doc.pop("$schema", None)
        if set(doc) - allowed:
            raise ValueError(f"Unsupported publication fields: {sorted(set(doc) - allowed)}")
        doc["name"] = _name(doc.get("name"))
        doc["tags"] = _tags(doc.get("tags"))
    if "settings" in deployment and not isinstance(deployment["settings"], dict):
        raise ValueError("Deployment settings must be a dictionary")
    return component, endpoint, deployment


def _component_id(component, definition: dict, target: WorkspaceTarget) -> str:
    expected = (
        f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{target.workspace_name}"
        f"/components/{definition['name']}/versions/{definition['version']}"
    )
    actual = _field(component, "id")
    if not isinstance(actual, str) or actual.lower() != expected.lower():
        raise ValueError("Published component ID does not match the requested workspace/name/version")
    return actual


def _published(component_id: str, endpoint, deployment_name: str) -> dict:
    _require_named(endpoint)
    return _public({
        "component_id": component_id,
        "endpoint_name": _field(endpoint, "name"),
        "deployment_name": deployment_name,
        "inference_uri": _field(endpoint, "scoring_uri"),
    })


def _bindings(inputs: dict, outputs: dict) -> tuple[dict, dict]:
    inputs, outputs = _document(inputs), _document(outputs)
    for key, value in inputs.items():
        _name(key, "input name")
        if not isinstance(value, (dict, str, int, float, bool)):
            raise ValueError("Inputs must be binding dictionaries or scalar values")
        if not isinstance(value, dict):
            kind = "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else (
                "number" if isinstance(value, float) else "string"
            )
            value = inputs[key] = {"type": kind, "default": value}
        kind = value.get("type")
        if kind in {"string", "integer", "number", "boolean"}:
            if set(value) - {"type", "default"} or "default" not in value:
                raise ValueError("Literal inputs require only type and default")
            scalar = value["default"]
            valid = {
                "string": isinstance(scalar, str),
                "integer": isinstance(scalar, int) and not isinstance(scalar, bool),
                "number": isinstance(scalar, (float, int)) and not isinstance(scalar, bool),
                "boolean": isinstance(scalar, bool),
            }[kind]
            if not valid or isinstance(scalar, float) and not math.isfinite(scalar):
                raise ValueError("Literal input type and value do not agree")
        else:
            _path_binding(value, output=False)
    for key, value in outputs.items():
        _name(key, "output name")
        if not isinstance(value, dict):
            raise ValueError("Outputs must be binding dictionaries")
        _path_binding(value, output=True)
    return inputs, outputs


def _path_binding(value: dict, *, output: bool) -> None:
    if set(value) - {"type", "path", "mode"}:
        raise ValueError("Data bindings support only type, path and mode")
    if value.get("type") not in {"uri_folder", "uri_file", "mltable", "custom_model", "mlflow_model", "triton_model"}:
        raise ValueError("An explicit supported data binding type is required")
    if not isinstance(value.get("path"), str) or not value["path"].strip():
        raise ValueError("Data bindings require an explicit path")
    modes = {"rw_mount", "upload", "direct"} if output else {"ro_mount", "download", "direct"}
    if "mode" in value and value["mode"] not in modes:
        raise ValueError("Unsupported data binding mode")


def _base_path(path: Path) -> Path:
    result = Path(path).resolve(strict=True)
    if not result.is_dir():
        raise NotADirectoryError(result)
    return result


def _origin(path: Path) -> str:
    # SDK relative_origin is a source filename, not a directory.
    return str(_base_path(path) / "azure-esml-document.yaml")


def _download_destination(destination: Path) -> Path:
    destination = Path(destination).absolute()
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def _component_reuse(value) -> None:
    if not isinstance(value, bool):
        raise ValueError("reuse_component must be a boolean")


def _deployment_entity(document: dict, base_path: Path):
    from azure.ai.ml import load_batch_deployment
    from azure.ai.ml.entities import PipelineComponentBatchDeployment

    fields = _document(document)
    settings = fields.pop("settings", None)
    entity = load_batch_deployment(StringIO(_yaml(fields)), relative_origin=_origin(base_path))
    if not isinstance(entity, PipelineComponentBatchDeployment):
        raise ValueError("A pipeline component batch deployment is required")
    # SDK 1.35's public generic loader rejects pipeline-specific settings.
    # Its pipeline loader validates those settings with the actual pipeline schema.
    if settings is not None:
        entity = PipelineComponentBatchDeployment._load(data=document, yaml_path=_origin(base_path))
    return entity


def _publication_entities(component: dict, endpoint: dict, deployment: dict, base_path: Path):
    from azure.ai.ml import load_component, load_batch_endpoint

    entity = load_component(StringIO(_yaml(component)), relative_origin=_origin(base_path))
    entity._validate().try_raise()
    endpoint_entity = load_batch_endpoint(StringIO(_yaml(endpoint)), relative_origin=_origin(base_path))
    deployment_entity = _deployment_entity({
        **deployment, "type": "pipeline", "endpoint_name": endpoint["name"],
        "component": f"azureml:{component['name']}:{component['version']}",
    }, base_path)
    return entity, endpoint_entity, deployment_entity


def _yaml(document: dict) -> str:
    return yaml.safe_dump(document, sort_keys=False)


class AzureMLSDKBackend(MLBackend):
    def __init__(self, target: WorkspaceTarget, client=None, credential=None):
        if not isinstance(target, WorkspaceTarget):
            raise TypeError("target must be a WorkspaceTarget")
        self.target = target
        if client is None:
            if credential is None:
                raise ValueError("Provide an explicit credential or injected client")
            from azure.ai.ml import MLClient

            client = MLClient(
                credential=credential,
                subscription_id=target.subscription_id,
                resource_group_name=target.resource_group,
                workspace_name=target.workspace_name,
            )
        self.client = client

    @classmethod
    def from_cli(cls, target: WorkspaceTarget):
        from azure.identity import AzureCliCredential

        return cls(target, credential=AzureCliCredential(tenant_id=target.tenant_id, process_timeout=60))

    @classmethod
    def from_managed_identity(cls, target: WorkspaceTarget, client_id=None):
        from azure.identity import ManagedIdentityCredential

        if client_id is not None:
            _name(client_id, "managed identity client_id")
        credential = ManagedIdentityCredential(client_id=client_id) if client_id is not None else ManagedIdentityCredential()
        return cls(target, credential=credential)

    def submit(self, document: dict, base_path: Path) -> dict:
        from azure.ai.ml import load_job

        job = load_job(StringIO(_yaml(_document(document))), relative_origin=_origin(base_path))
        return _job(self.client.jobs.create_or_update(job))

    def get_job(self, name: str) -> dict:
        return _job(self.client.jobs.get(name=_name(name)))

    def list_jobs(self, limit: int = 100) -> list[dict]:
        limit = _limit(limit)
        return [_job(job) for job in islice(self.client.jobs.list(), limit)]

    def download_job(self, name: str, destination: Path, output_name: str) -> None:
        name, output_name = _name(name), _name(output_name, "output_name")
        self.client.jobs.download(name=name, download_path=str(_download_destination(destination)), output_name=output_name)

    def ensure_datastore(self, definition: dict) -> dict:
        from azure.ai.ml import load_datastore
        from azure.core.exceptions import ResourceNotFoundError

        doc = _datastore_definition(definition)
        entity = load_datastore(StringIO(_yaml(doc)), relative_origin=_origin(Path.cwd()))
        try:
            existing = self.client.datastores.get(name=doc["name"])
        except ResourceNotFoundError:
            return _datastore(self.client.datastores.create_or_update(entity))
        _match_datastore(existing, doc)
        return _datastore(existing)

    def register_data(self, definition: dict) -> dict:
        from azure.ai.ml import load_data
        from azure.core.exceptions import ResourceNotFoundError

        doc = _data_definition(definition)
        entity = load_data(StringIO(_yaml(doc)), relative_origin=_origin(Path.cwd()))
        try:
            existing = self.client.data.get(name=doc["name"], version=doc["version"])
        except ResourceNotFoundError:
            return _asset(self.client.data.create_or_update(entity))
        _match_data(existing, doc)
        return _asset(existing)

    def get_data(self, name: str, version: str) -> dict:
        return _asset(self.client.data.get(name=_name(name), version=_version(version)))

    def get_model(self, name: str, version: str) -> dict:
        return _asset(self.client.models.get(name=_name(name), version=_version(version)))

    def register_model(self, definition: dict) -> dict:
        from azure.ai.ml.entities import Model

        return _asset(self.client.models.create_or_update(Model(**_model_definition(definition))))

    def publish(
        self, component: dict, endpoint: dict, deployment: dict, base_path: Path, *,
        reuse_component: bool = False,
    ) -> dict:
        from azure.core.exceptions import ResourceNotFoundError

        component, endpoint, deployment = _publication(component, endpoint, deployment)
        _component_reuse(reuse_component)
        # Construct the other entities before the first write so local errors cannot leave partial publication.
        entity, endpoint_entity, deployment_entity = _publication_entities(component, endpoint, deployment, base_path)
        try:
            registered = self.client.components.get(name=component["name"], version=component["version"])
        except ResourceNotFoundError:
            registered = self.client.components.create_or_update(entity)
        else:
            if not reuse_component:
                raise ValueError("Component version already exists; select a new version or explicitly reuse_component=True")
        component_id = _component_id(registered, component, self.target)
        try:
            actual_endpoint = self.client.batch_endpoints.get(name=endpoint["name"])
        except ResourceNotFoundError:
            actual_endpoint = self.client.batch_endpoints.begin_create_or_update(endpoint_entity).result()
        deployment_entity.component = component_id
        self.client.batch_deployments.begin_create_or_update(deployment_entity).result()
        return _published(component_id, actual_endpoint, deployment["name"])

    def invoke(self, endpoint_name: str, deployment_name: str, inputs: dict, outputs: dict) -> dict:
        from azure.ai.ml import Input, Output

        endpoint_name, deployment_name = _name(endpoint_name), _name(deployment_name)
        inputs, outputs = _bindings(inputs, outputs)
        return _job(self.client.batch_endpoints.invoke(
            endpoint_name=endpoint_name,
            deployment_name=deployment_name,
            inputs={key: Input(**value) for key, value in inputs.items()},
            outputs={key: Output(**value) for key, value in outputs.items()},
        ))


class AzureMLCLIBackend(MLBackend):
    """CLI v2 adapter. Injected runners receive argv (including az) and return JSON."""

    def __init__(
        self, target: WorkspaceTarget, runner: Callable[[list[str]], dict | list] | None = None
    ):
        if not isinstance(target, WorkspaceTarget):
            raise TypeError("target must be a WorkspaceTarget")
        self.target = target
        self._runner = runner if runner is not None else self._run
        self._checked = False

    @staticmethod
    def _run(argv: list[str]) -> dict | list:
        executable = shutil.which("az")
        if executable is None:
            raise FileNotFoundError("Azure CLI is not installed; install it and the ml v2 extension explicitly")
        command = [executable]
        if Path(executable).suffix.lower() in {".cmd", ".bat"}:
            candidates = [Path(executable).parent / "python.exe", Path(executable).parent.parent / "python.exe"]
            python = next((path for path in candidates if path.is_file()), None)
            if python is None:
                raise RuntimeError("Cannot safely run the Azure CLI batch shim; its python.exe was not found")
            command = [str(python), "-I", "-m", "azure.cli"]
        result = subprocess.run(
            [*command, *argv[1:]], shell=False, check=True, capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no"},
        )
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def _transport(self, arguments: list[str]) -> dict | list:
        return self._runner(["az", *arguments, "--output", "json", "--only-show-errors"])

    def _check(self) -> None:
        if self._checked:
            return
        extension = self._transport(["extension", "show", "--name", "ml"])
        version = _field(extension, "version")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9.+-]*)", version) or int(version.split(".")[0]) < 2:
            raise ValueError("The installed Azure CLI ml extension must be version 2 or later")
        account = self._transport(["account", "show", "--subscription", self.target.subscription_id])
        if str(_field(account, "tenantId", "")).lower() != self.target.tenant_id:
            raise ValueError("Azure CLI subscription tenant differs from the explicit target")
        if str(_field(account, "id", "")).lower() != self.target.subscription_id:
            raise ValueError("Azure CLI account differs from the explicit subscription")
        self._checked = True

    def _call(self, *arguments: str) -> dict | list:
        self._check()
        return self._transport([
            "ml", *arguments,
            "--subscription", self.target.subscription_id,
            "--resource-group", self.target.resource_group,
            "--workspace-name", self.target.workspace_name,
        ])

    @contextmanager
    def _file(self, document: dict, base_path: Path):
        # Keep the document beside its relative assets, and alive until az has finished reading it.
        path = _base_path(base_path) / f".azure-esml-{uuid4().hex}.yaml"
        created = False
        try:
            with path.open("x", encoding="utf-8") as handle:
                created = True
                handle.write(_yaml(document))
            yield str(path)
        finally:
            if created:
                path.unlink(missing_ok=True)

    def _get_optional(self, group: str, *arguments: str):
        try:
            result = self._call(group, "show", *arguments)
        except subprocess.CalledProcessError as error:
            # Never interpret authentication, permissions or transport errors as absence.
            if re.search(r"(?m)^ERROR:\s*\((?:ResourceNotFound|AssetNotFound|NotFound)\)", error.stderr or ""):
                return None
            raise
        if not isinstance(result, dict) or not result.get("name"):
            raise TypeError("Azure CLI show must return a named object")
        return result

    def _create(self, group: str, doc: dict, base_path: Path, *arguments: str) -> dict:
        with self._file(doc, base_path) as file:
            result = self._call(group, "create", "--file", file, *arguments)
        if not isinstance(result, dict):
            raise TypeError("Azure CLI create must return an object")
        return result

    def submit(self, document: dict, base_path: Path) -> dict:
        return _job(self._create("job", _document(document), base_path))

    def get_job(self, name: str) -> dict:
        return _job(self._call("job", "show", "--name", _name(name)))

    def list_jobs(self, limit: int = 100) -> list[dict]:
        limit = _limit(limit)
        rows = self._call("job", "list", "--max-results", str(limit))
        if not isinstance(rows, list):
            raise TypeError("Azure CLI job list must return an array")
        return [_job(row) for row in rows[:limit]]

    def download_job(self, name: str, destination: Path, output_name: str) -> None:
        name, output_name = _name(name), _name(output_name, "output_name")
        self._check()
        self._call("job", "download", "--name", name, "--download-path", str(_download_destination(destination)),
                   "--output-name", output_name)

    def ensure_datastore(self, definition: dict) -> dict:
        doc = _datastore_definition(definition)
        existing = self._get_optional("datastore", "--name", doc["name"])
        if existing is not None:
            # `az ml datastore show` strips credential type when hiding secrets,
            # making AccountKey/SAS stores indistinguishable from identity stores.
            resource = (
                f"/subscriptions/{self.target.subscription_id}/resourceGroups/{self.target.resource_group}"
                f"/providers/Microsoft.MachineLearningServices/workspaces/{self.target.workspace_name}"
                f"/datastores/{doc['name']}?api-version=2024-04-01"
            )
            credential_type = self._transport([
                "rest", "--method", "get", "--url", resource,
                "--subscription", self.target.subscription_id,
                "--query", "{credentials_type:properties.credentials.credentialsType}",
            ])
            if str(_field(credential_type, "credentials_type", "")).lower() != "none":
                raise ValueError("Existing datastore credentials differ or cannot be verified; refusing to overwrite")
            existing = {**existing, "credentials": {"type": "none"}}
            _match_datastore(existing, doc)
            return _datastore(existing)
        return _datastore(self._create("datastore", doc, Path.cwd()))

    def register_data(self, definition: dict) -> dict:
        doc = _data_definition(definition)
        existing = self._get_optional("data", "--name", doc["name"], "--version", doc["version"])
        if existing is not None:
            _match_data(existing, doc)
            return _asset(existing)
        return _asset(self._create("data", doc, Path.cwd()))

    def get_data(self, name: str, version: str) -> dict:
        name, version = _name(name), _version(version)
        return _asset(self._call("data", "show", "--name", name, "--version", version))

    def get_model(self, name: str, version: str) -> dict:
        name, version = _name(name), _version(version)
        return _asset(self._call("model", "show", "--name", name, "--version", version))

    def register_model(self, definition: dict) -> dict:
        return _asset(self._create("model", _model_definition(definition), Path.cwd()))

    def publish(
        self, component: dict, endpoint: dict, deployment: dict, base_path: Path, *,
        reuse_component: bool = False,
    ) -> dict:
        component, endpoint, deployment = _publication(component, endpoint, deployment)
        _component_reuse(reuse_component)
        base_path = _base_path(base_path)
        _publication_entities(component, endpoint, deployment, base_path)
        registered = self._get_optional("component", "--name", component["name"], "--version", component["version"])
        if registered is None:
            registered = self._create("component", component, base_path)
        elif not reuse_component:
            raise ValueError("Component version already exists; select a new version or explicitly reuse_component=True")
        component_id = _component_id(registered, component, self.target)
        actual_endpoint = self._get_optional("batch-endpoint", "--name", endpoint["name"])
        if actual_endpoint is None:
            actual_endpoint = self._create("batch-endpoint", endpoint, base_path)
        self._create("batch-deployment", {
            **deployment, "type": "pipeline", "endpoint_name": endpoint["name"], "component": f"azureml:{component_id}",
        }, base_path)
        return _published(component_id, actual_endpoint, deployment["name"])

    def invoke(self, endpoint_name: str, deployment_name: str, inputs: dict, outputs: dict) -> dict:
        endpoint_name, deployment_name = _name(endpoint_name), _name(deployment_name)
        inputs, outputs = _bindings(inputs, outputs)
        with self._file({"inputs": inputs, "outputs": outputs}, Path.cwd()) as file:
            return _job(self._call("batch-endpoint", "invoke", "--name", endpoint_name,
                                   "--deployment-name", deployment_name, "--file", file))
