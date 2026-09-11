"""Versioned lake object keys shared by local, Azure ML, ADF, and Databricks flows."""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


def identifier(value, field: str) -> str:
    value = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if (not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value)
            or value.lower() in {"con", "prn", "aux", "nul"}
            or re.fullmatch(r"(?i)(com|lpt)[1-9]", value)):
        raise ValueError(f"lake.{field} must be an explicit safe identifier (letters, digits, _ or -)")
    return value


def relative_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_./=-]+", value):
        raise ValueError("Lake object keys must be relative slash-separated paths without escapes")
    path = PurePosixPath(value)
    if not value or value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Lake object keys must not be absolute or traverse parent directories")
    return str(path)


@dataclass(frozen=True)
class LakeLayout:
    project: str
    environment: str
    use_case: str
    dataset: str
    data_version: str
    snapshot_id: str
    run_id: str
    serving: str = "batch"
    model_version: str | None = None
    pipeline_id: str = ""
    pipeline_version: str = "v1"
    prefix: str = "mlops/v1"
    account_url: str | None = None
    container: str | None = None
    datastore: str | None = None

    @classmethod
    def from_config(cls, config: dict, scenario: dict | None = None):
        if not isinstance(config, dict):
            raise ValueError("lake configuration must be an object")
        project = config.get("project")
        if not isinstance(project, str) or not re.fullmatch(r"\d{3}", project):
            raise ValueError("lake.project must be an explicit three-digit project number")
        environment = config.get("environment")
        if environment not in ("dev", "test", "prod"):
            raise ValueError("lake.environment must be dev, test, or prod (not a dataset split)")
        use_case = identifier(config.get("use_case", (scenario or {}).get("name")), "use_case")
        serving = config.get("serving", "batch")
        if serving not in ("batch", "online", "streaming"):
            raise ValueError("lake.serving must be batch, online, or streaming")
        if str(config.get("model_version", "")).lower() in ("latest", "active", "champion", "production"):
            raise ValueError("lake.model_version must be immutable, not an active/latest alias")
        storage = config.get("storage", {})
        if not isinstance(storage, dict):
            raise ValueError("lake.storage must be an object")
        account = storage.get("account_url")
        if account:
            url = urlsplit(account)
            if (url.scheme != "https" or url.username or url.password or url.query or url.fragment
                    or url.path not in ("", "/") or url.port
                    or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.(windows\.net|usgovcloudapi\.net|chinacloudapi\.cn)", url.hostname or "")):
                raise ValueError("lake.storage.account_url must be a credential-free Azure Blob HTTPS endpoint")
            account = account.rstrip("/")
        container = storage.get("container")
        if container and (not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container) or "--" in container):
            raise ValueError("lake.storage.container must be a valid Blob container name")
        datastore = storage.get("datastore")
        if datastore:
            datastore = identifier(datastore, "storage.datastore")
        prefix = relative_key(config.get("prefix", "mlops/v1"))
        if prefix == "projects" or prefix.startswith("projects/"):
            raise ValueError("Use a versioned namespace separate from the legacy ESML projects root")
        return cls(
            project=project, environment=environment, use_case=use_case,
            dataset=identifier(config.get("dataset"), "dataset"),
            data_version=identifier(config.get("data_version"), "data_version"),
            snapshot_id=identifier(config.get("snapshot_id"), "snapshot_id"),
            run_id=identifier(config.get("run_id"), "run_id"),
            serving=serving,
            model_version=identifier(config["model_version"], "model_version") if config.get("model_version") is not None else None,
            pipeline_id=identifier(config.get("pipeline_id", use_case), "pipeline_id"),
            pipeline_version=identifier(config.get("pipeline_version", "v1"), "pipeline_version"),
            prefix=prefix, account_url=account, container=container, datastore=datastore,
        )

    def as_dict(self) -> dict[str, str]:
        scope = f"{self.prefix}/projects/project{self.project}/environments/{self.environment}"
        dataset = f"{scope}/datasets/{self.dataset}/versions/{self.data_version}"
        use_case = f"{scope}/usecases/{self.use_case}"
        snapshot = f"{use_case}/training/snapshots/{self.snapshot_id}"
        run = f"{use_case}/training/runs/{self.run_id}"
        result = {
            "scope": scope, "dataset_root": dataset, "use_case_root": use_case,
            "training_snapshot": snapshot, "training_gold": f"{snapshot}/gold",
            "training_run": run, "training_model": f"{run}/model",
            "training_evaluation": f"{run}/evaluation",
            "checkpoint": f"{use_case}/operations/streaming/{self.pipeline_id}/versions/{self.pipeline_version}/checkpoints",
        }
        result.update({stage: f"{dataset}/{stage}" for stage in ("landing", "bronze", "silver")})
        result["dataset_quarantine"] = f"{scope}/datasets/{self.dataset}/quarantine/versions/{self.data_version}"
        if self.model_version is not None:
            inference = f"{use_case}/inference/{self.serving}/models/{self.model_version}/runs/{self.run_id}"
            result.update({
                "inference_root": inference, "input": f"{inference}/in",
                "inference_gold": f"{inference}/gold", "output": f"{inference}/out",
                "quarantine": f"{use_case}/quarantine/{self.serving}/models/{self.model_version}/runs/{self.run_id}",
                "feedback": f"{use_case}/feedback/models/{self.model_version}/inference-runs/{self.run_id}",
            })
        return result

    def key(self, name: str) -> str:
        keys = self.as_dict()
        if name not in keys:
            raise ValueError(f"Unknown or unavailable lake area {name!r}; inference areas require model_version")
        return keys[name]

    def blob_uri(self, name: str) -> str:
        if not self.account_url or not self.container:
            raise ValueError("Blob URIs require explicit lake.storage.account_url and container")
        return f"{self.account_url}/{self.container}/{self.key(name)}/"

    def azureml_uri(self, name: str, datastore: str | None = None) -> str:
        datastore = datastore or self.datastore
        if not datastore:
            raise ValueError("Azure ML lake URIs require an existing credentialless datastore")
        return f"azureml://datastores/{identifier(datastore, 'datastore')}/paths/{self.key(name)}/"

    def local_path(self, root: Path, name: str) -> Path:
        return local_key_path(root, self.key(name))


def local_key_path(root: Path, key: str) -> Path:
    root = Path(root).absolute()
    key = relative_key(key)
    result = root.joinpath(*key.split("/"))
    for path in (result, *result.parents):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Local lake paths may not traverse symbolic links or junctions")
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Lake path escapes its root")
    return result


def lake_manifest(layout: LakeLayout, scenario: dict) -> dict:
    return {
        "schema": "ml-model-factory-lake/v1",
        "project": layout.project, "environment": layout.environment, "use_case": layout.use_case,
        "dataset": layout.dataset, "data_version": layout.data_version,
        "snapshot_id": layout.snapshot_id, "run_id": layout.run_id,
        "task": scenario["task"], "serving": layout.serving, "model_version": layout.model_version,
        "paths": layout.as_dict(),
        "contract": {
            "legacy": "Never rename or overwrite the legacy projects/ hierarchy.",
            "landing": "Immutable source bytes; provenance and checksum, no fabricated labels.",
            "bronze": "Parsed source records; transformations must be recorded.",
            "silver": "Schema-validated reusable data; learned preprocessing is not fitted here.",
            "gold": "Use-case-specific training snapshots or inference features, with schema and source lineage.",
            "quarantine": "Rejected data references and reason codes, isolated from training and predictions.",
            "feedback": "Late observed labels joined by stable request/entity IDs; never auto-promote predictions to labels.",
            "checkpoint": "Stable across runs/model rollouts; change pipeline_version for incompatible query/schema changes.",
            "permissions": "Blob prefixes are not ACL boundaries; use configured container/RBAC and network controls.",
        },
    }
