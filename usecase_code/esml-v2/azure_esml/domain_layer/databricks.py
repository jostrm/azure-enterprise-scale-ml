"""Existing-job Databricks bridge: real files cross Azure ML named data ports.

The pinned Azure ML environment must install azure-esml-sdk[databricks]. Its
managed identity needs job-run access and Storage Blob Data Contributor access;
the existing notebook job needs independent read/write access to the same
project-scoped container prefix. Transfer retention is managed by the caller.
"""

import argparse
import base64
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path, PurePosixPath
import re
import shlex
from urllib.parse import urlsplit
from uuid import uuid4

from .contracts import IPipelineStepMap, StepOverride, StepType


SCHEMA = "esml.databricks-step/v1"
_PORT = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")


def _validate(host, workspace_resource_id, account_url, container, prefix, timeout_seconds):
    for value, suffix in ((host, ".azuredatabricks.net"), (account_url, ".blob.core.windows.net")):
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(suffix)
                or url.netloc != url.hostname or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("Use credential-free HTTPS Azure workspace and Blob account URLs")
    if not re.fullmatch(r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net/?", account_url):
        raise ValueError("account_url must identify an Azure Blob account")
    if not re.fullmatch(r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Databricks/workspaces/[^/]+",
                        workspace_resource_id):
        raise ValueError("Provide the existing Databricks workspace ARM resource ID")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", container) or "--" in container:
        raise ValueError("Invalid Azure Blob container name")
    parts = prefix.split("/")
    if (any(not re.fullmatch(r"[A-Za-z0-9_.=-]+", part) or part in (".", "..") for part in parts)
            or not re.search(r"(?:^|/)projects/project[0-9]{3}(?:/|$)", prefix)):
        raise ValueError("prefix must be an explicit safe project-scoped namespace")
    if type(timeout_seconds) is not int or timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")


def _job(value):
    if (not isinstance(value, dict) or set(value) != {"job_id", "task_key"}
            or type(value["job_id"]) is not int or value["job_id"] < 1
            or not isinstance(value["task_key"], str) or not value["task_key"].strip()):
        raise ValueError("Each mapping requires a positive job_id and notebook task_key")
    return value


class DatabricksStepMap(IPipelineStepMap):
    """Replace selected steps; unmapped steps remain native CPU/GPU Azure ML.

    Mapping keys are StepType or (StepType, dataset). Static merge resolution
    requires datasets; the factory supplies discovered ports to create_component.
    The factory supplies compiled configuration through esml_context_b64;
    constructor context is the default when using the component independently.
    Context must never contain credentials (base64 is not encryption).
    """

    def __init__(self, mapping, *, host, workspace_resource_id, account_url, container, prefix,
                 environment, datasets=(), compute=None, context=None, timeout_seconds=3600, client_id=None):
        _validate(host, workspace_resource_id, account_url, container, prefix, timeout_seconds)
        if (not re.fullmatch(r"azureml:[A-Za-z0-9_-]+:[A-Za-z0-9_.-]+", environment)
                or environment.rsplit(":", 1)[-1].lower() in ("0", "latest", "active", "production", "champion")):
            raise ValueError("environment must be an explicit versioned Azure ML environment")
        for key, value in mapping.items():
            if not (isinstance(key, StepType) or (
                    isinstance(key, tuple) and len(key) == 2 and isinstance(key[0], StepType)
                    and isinstance(key[1], str) and key[1])):
                raise ValueError("Mapping keys must be StepType or (StepType, dataset)")
            _job(value)
        self.mapping, self.datasets = deepcopy(mapping), tuple(datasets)
        self.environment, self.compute, self.context = environment, compute, deepcopy(context or {})
        self.options = dict(host=host, workspace_resource_id=workspace_resource_id, account_url=account_url,
                            container=container, prefix=prefix, timeout_seconds=timeout_seconds)
        if client_id:
            self.options["client_id"] = client_id

    def resolve(self, step, dataset=None):
        if (step, dataset) not in self.mapping and step not in self.mapping:
            return None
        inputs, outputs = {"data": "uri_folder"}, {"output": "uri_folder"}
        if step == StepType.SILVER_MERGED_2_GOLD:
            names = [re.sub(r"[^a-z0-9_]", "_", name.lower()) for name in self.datasets]
            names = [name if name and name[0].isalpha() else "ds_" + name for name in names]
            if not names or len(names) != len(set(names)):
                raise ValueError("Merge requires distinct datasets, or use create_component with dynamic ports")
            inputs = dict.fromkeys(names, "uri_folder")
        elif step == StepType.TRAINING_SPLIT_AND_REGISTER:
            outputs = {"prepared": "uri_folder", **dict.fromkeys(("train", "validation", "test"), "mltable")}
        elif step == StepType.TRAINING_MANUAL:
            inputs, outputs = {"prepared": "uri_folder"}, {"model": "mlflow_model"}
        elif step == StepType.TRAINING_AUTOML:
            inputs, outputs = dict.fromkeys(("train", "validation"), "mltable"), {"best_model": "mlflow_model"}
        elif step == StepType.EVALUATE:
            inputs, outputs = {"prepared": "uri_folder", "model": "mlflow_model"}, {"report": "uri_folder"}
        elif step == StepType.INFERENCE_GOLD:
            inputs["model"] = "mlflow_model"
        return self.create_component(step, inputs, outputs, {}, dataset=dataset)

    def create_component(self, step, input_names, output_names, context, *, dataset=None):
        """Build an inline command replacement from actual factory port types."""
        job = self.mapping.get((step, dataset), self.mapping.get(step))
        if job is None:
            return None
        context = {**deepcopy(self.context), **deepcopy(context), "step": step.value, "dataset_name": dataset}
        encoded = base64.b64encode(json.dumps(context, allow_nan=False).encode()).decode()
        options = {**self.options, **job, "step": step.value}
        if dataset is not None:
            options["dataset_name"] = dataset
        command = "python -m azure_esml.domain_layer.databricks"
        command += "".join(f" --{key.replace('_', '-')} {shlex.quote(str(value))}" for key, value in options.items())
        command += ' --context-base64 "${{inputs.esml_context_b64}}"'
        for direction, ports in (("input", input_names), ("output", output_names)):
            if not ports or any(name == "esml_context_b64" or not _PORT.fullmatch(name)
                                or kind not in ("uri_folder", "mlflow_model", "mltable")
                                for name, kind in ports.items()):
                raise ValueError("Databricks data ports must have safe names and folder-compatible types")
            command += "".join(f' --{direction} {name} "${{{{{direction}s.{name}}}}}"' for name in ports)
        return StepOverride({
            "type": "command", "environment": self.environment, "command": command, "is_deterministic": False,
            "inputs": {**{name: {"type": kind} for name, kind in input_names.items()},
                       "esml_context_b64": {"type": "string", "default": encoded}},
            "outputs": {name: {"type": kind} for name, kind in output_names.items()},
        }, compute=self.compute, engine="databricks")


def _safe_local(path):
    if any(item.is_symlink() or getattr(item, "is_junction", lambda: False)() for item in (path, *path.parents)):
        raise ValueError("Symlink paths are not supported")
    return path


def _payload(name):
    return not any(part.startswith((".", "_")) for part in PurePosixPath(name).parts)


def _state_success(run):
    state = getattr(getattr(run, "state", None), "result_state", None)
    if getattr(state, "value", state) != "SUCCESS":
        raise ValueError("Databricks run and selected notebook task must both report SUCCESS")


def run_step(*, host, workspace_resource_id, job_id, task_key, account_url, container, prefix,
             inputs, outputs, context=None, timeout_seconds=3600, client_id=None, client=None,
             container_client=None, credential=None):
    """Transfer files, run one existing notebook task, verify its receipt, materialize outputs.

    Injectable SDK clients permit credential-free tests. Production authentication
    is managed identity only; no PAT, SAS, or account key is accepted.
    """
    _validate(host, workspace_resource_id, account_url, container, prefix, timeout_seconds)
    _job({"job_id": job_id, "task_key": task_key})
    if any(not ports or any(not _PORT.fullmatch(name) for name in ports) for ports in (inputs, outputs)):
        raise ValueError("Provide nonempty input and output maps with safe port names")
    parameters = {"context": json.dumps(context or {}, allow_nan=False)}
    files = {}
    for name, location in inputs.items():
        path = _safe_local(Path(location).absolute())
        entries = [path] if path.is_file() else list(path.rglob("*"))
        for entry in entries:
            _safe_local(entry)
        files[name] = [(entry, entry.name if path.is_file() else entry.relative_to(path).as_posix())
                       for entry in entries if entry.is_file()]
        if not any(_payload(key) and entry.stat().st_size for entry, key in files[name]):
            raise ValueError(f"Input {name} contains no data files")
    destinations = {name: _safe_local(Path(path).absolute()) for name, path in outputs.items()}
    if any(path.exists() and (not path.is_dir() or any(path.iterdir())) for path in destinations.values()):
        raise ValueError("Output mounts must be empty directories")
    paths = list(destinations.values())
    if any(a == b or a in b.parents or b in a.parents for index, a in enumerate(paths) for b in paths[index + 1:]):
        raise ValueError("Output mounts must not overlap")
    if container_client is None:
        from azure.identity import ManagedIdentityCredential
        from azure.storage.blob import ContainerClient
        credential = credential or ManagedIdentityCredential(**({"client_id": client_id} if client_id else {}))
        container_client = ContainerClient(account_url=account_url, container_name=container, credential=credential)
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient(host=host, auth_type="azure-msi", azure_use_msi=True,
                                 azure_workspace_resource_id=workspace_resource_id,
                                 **({"azure_client_id": client_id} if client_id else {}))
    token = uuid4().hex
    root = f"{prefix}/_bridge/{job_id}/{token}"
    uri = f"wasbs://{container}@{urlsplit(account_url).hostname}/"
    expected = {name: f"{uri}{root}/outputs/{name}/" for name in outputs}
    parameters.update(inputs=json.dumps({name: f"{uri}{root}/inputs/{name}/" for name in inputs}),
                      outputs=json.dumps(expected))
    for name, entries in files.items():
        for local, key in entries:
            with local.open("rb") as source:
                container_client.upload_blob(name=f"{root}/inputs/{name}/{key}", data=source, overwrite=False)
    completed = client.jobs.run_now(job_id=job_id, job_parameters=parameters, idempotency_token=token).result(
        timeout=timedelta(seconds=timeout_seconds))
    _state_success(completed)
    tasks = [task for task in (completed.tasks or []) if task.task_key == task_key]
    if len(tasks) != 1 or not tasks[0].run_id:
        raise ValueError("Completed job must expose exactly one selected notebook task")
    _state_success(tasks[0])
    result = client.jobs.get_run_output(tasks[0].run_id)
    notebook = result.notebook_output
    if getattr(result, "error", None) or notebook is None or notebook.truncated or not notebook.result:
        raise ValueError("Notebook must return a complete JSON output receipt")
    receipt = json.loads(notebook.result)
    reported = receipt.get("outputs") if isinstance(receipt, dict) else None
    if (not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA or not isinstance(reported, dict)
            or set(reported) != set(expected)
            or any(not isinstance(value, str) or value.rstrip("/") != expected[name].rstrip("/")
                   for name, value in reported.items())):
        raise ValueError("Notebook receipt must match the exact predetermined output URIs")
    for name, destination in destinations.items():
        blob_prefix = f"{root}/outputs/{name}/"
        blobs = container_client.list_blobs(name_starts_with=blob_prefix, include=["metadata"])
        has_data = False
        for blob in blobs:
            is_directory = (getattr(blob, "metadata", None) or {}).get("hdi_isfolder", "").lower() == "true"
            relative = blob.name.removeprefix(blob_prefix)
            if is_directory:
                relative = relative.rstrip("/")
            parts = relative.split("/")
            if (not blob.name.startswith(blob_prefix) or any(not part or part.endswith((".", " ")) for part in parts)
                    or any(char in relative for char in ("\\", ":", "\x00"))):
                raise ValueError("Unsafe output blob path")
            if is_directory:
                continue
            target = _safe_local(destination.joinpath(*parts))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                container_client.download_blob(blob.name).readinto(output)
            has_data |= _payload(relative) and target.stat().st_size > 0
        if not has_data:
            raise ValueError(f"Output {name} contains no data files")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "workspace-resource-id", "task-key", "account-url", "container", "prefix"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--job-id", required=True, type=int)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--client-id")
    parser.add_argument("--context-base64")
    parser.add_argument("--context-json-file", type=Path)
    parser.add_argument("--step", choices=[step.value for step in StepType])
    parser.add_argument("--dataset-name")
    for name in ("input", "output"):
        parser.add_argument("--" + name, nargs=2, action="append", required=True)
    args = vars(parser.parse_args())
    encoded, config = args.pop("context_base64"), args.pop("context_json_file")
    if encoded and config:
        parser.error("Use only one context source")
    context = json.loads(config.read_text(encoding="utf-8") if config else base64.b64decode(encoded or "e30=", validate=True))
    if not isinstance(context, dict):
        parser.error("context must be a JSON object")
    step, dataset = args.pop("step"), args.pop("dataset_name")
    if step:
        context["step"], context["dataset_name"] = step, dataset
    for name in ("input", "output"):
        ports = args.pop(name)
        if len(dict(ports)) != len(ports):
            parser.error(f"Duplicate {name} ports")
        args[name + "s"] = dict(ports)
    run_step(**args, context=context)


if __name__ == "__main__":
    main()
