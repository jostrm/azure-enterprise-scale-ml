"""Shared-lake publication and create-only inference IO through the esml-v2 contracts."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from .configuration import read_json, write_json
from .usecases import CHURN, DATA_FILE


def bootstrap_config(config: dict) -> dict:
    lake = config["shared_lake"]
    return {
        "schema": "esml.shared-lake-bootstrap/v2", "aifactory": config["aifactory"],
        "environment": config["environment"], "project": f"{config['project_number']:03d}",
        "prefix": lake["prefix"],
        "storage": {"account_url": lake["account_url"], "account_name": urlsplit(lake["account_url"]).netloc.split(".")[0],
                    "container": lake["container"], "datastore": lake["datastore"], "type": "azure_blob",
                    "input_area": "in"},
        "datasets": [{"scenario": CHURN, "dataset": CHURN, "file": DATA_FILE}],
    }


def stage(config: dict, location, version: str) -> dict:
    """Stage master, shared silver, project IN and gold locally; writes nothing to Azure."""
    from azure_esml.domain_layer.lake_seed import stage_kaggle_examples

    root = location.state / "lake-staging" / version
    result = stage_kaggle_examples(bootstrap_config(config), source_root=location.ml_root / "data" / "in",
                                   scenario_root=location.scenarios, root=root, version=version)
    return {"root": str(root), "plan": result["plan"], "publications": result["publications"],
            "samples": result["samples"]}


def credential(config: dict):
    """Azure CLI credential bound to the configured subscription, after verifying its tenant."""
    from azure.identity import AzureCliCredential
    from ml_model_factory.project import azure_cli

    account = azure_cli("account", "show", "--subscription", config["subscription_id"])
    if (str(account.get("id", "")).lower() != config["subscription_id"].lower()
            or str(account.get("tenantId", "")).lower() != config["tenant_id"].lower()):
        raise ValueError("The signed-in Azure CLI subscription does not belong to the configured tenant")
    return AzureCliCredential(subscription=config["subscription_id"], process_timeout=60)


def publish(config: dict, staged: dict, *, credential_factory=credential) -> dict:
    """Create-only publication of exactly the staged plan; existing identical blobs are reused."""
    from azure_esml.domain_layer.lake_publication import publish as publish_plan

    lake = config["shared_lake"]
    target = urlsplit(staged["plan"]["target"])
    if f"{target.scheme}://{target.netloc}" != lake["account_url"] or target.path.strip("/") != lake["container"]:
        raise ValueError("Staged publication targets a different storage account or container")
    return publish_plan(Path(staged["root"]), staged["plan"], credential=credential_factory(config))


class LakeIO:
    """Create-only uploads and reads below one approved use-case root of the shared lake."""

    def __init__(self, config: dict, *, container_client=None, credential_factory=credential):
        self.config = config
        self.root_prefix = config["shared_lake"]["prefix"].rstrip("/") + "/"
        self._client = container_client
        self._credential_factory = credential_factory

    @property
    def client(self):
        if self._client is None:
            from azure.storage.blob import ContainerClient

            lake = self.config["shared_lake"]
            self._client = ContainerClient(lake["account_url"], lake["container"],
                                           credential=self._credential_factory(self.config))
        return self._client

    def prefix(self, uri: str, *, allowed_root: str) -> str:
        datastore = self.config["shared_lake"]["datastore"]
        expected = f"azureml://datastores/{datastore}/paths/"
        if not isinstance(uri, str) or not uri.startswith(expected):
            raise ValueError("Inference paths must use the configured shared-lake datastore")
        prefix = uri[len(expected):].strip("/")
        if not (prefix + "/").startswith(allowed_root.rstrip("/") + "/"):
            raise ValueError("Inference path is outside the approved use-case lake root")
        return prefix

    def upload_folder(self, folder: Path, prefix: str) -> dict:
        from ml_model_factory.data import sha256

        if list(self.client.list_blobs(name_starts_with=prefix.rstrip("/") + "/")):
            raise ValueError(f"Lake path is not empty; reconcile it instead of overwriting: {prefix}")
        files = {}
        for path in sorted(item for item in Path(folder).rglob("*") if item.is_file()):
            relative = path.relative_to(folder).as_posix()
            with path.open("rb") as stream:
                self.client.upload_blob(f"{prefix.rstrip('/')}/{relative}", stream, overwrite=False)
            files[relative] = sha256(path)
        return files

    def read_parquet(self, prefix: str, name: str = "predictions.parquet"):
        import io

        import pandas as pd

        blobs = sorted(blob.name for blob in self.client.list_blobs(name_starts_with=prefix.rstrip("/") + "/")
                       if blob.name.endswith("/" + name))
        if len(blobs) != 1:
            raise ValueError(f"Expected exactly one {name} below {prefix}; found {len(blobs)}")
        return pd.read_parquet(io.BytesIO(self.client.download_blob(blobs[0]).readall())), blobs[0]

    def download_one(self, prefix: str, destination: Path, *, suffix: str) -> Path:
        """Read-only download of the single file with `suffix` below an approved lake prefix."""
        if not (prefix.rstrip("/") + "/").startswith(self.root_prefix):
            raise ValueError("Downloads are limited to the configured shared-lake namespace")
        blobs = sorted(blob.name for blob in self.client.list_blobs(name_starts_with=prefix.rstrip("/") + "/")
                       if blob.name.lower().endswith(suffix))
        if len(blobs) != 1:
            raise ValueError(f"Expected exactly one {suffix} file below {prefix}; found {len(blobs)}")
        target = Path(destination) / Path(blobs[0]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.client.download_blob(blobs[0]).readall())
        return target


def record(location, name: str, value: dict) -> Path:
    return write_json(location.state / "receipts" / name, value)


def load_record(location, name: str) -> dict | None:
    path = location.state / "receipts" / name
    return read_json(path) if path.is_file() else None
