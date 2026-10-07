"""Optional notebook adapter; object-key ownership stays in the shared LakeLayout."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from ml_model_factory.config import load_json
from ml_model_factory.lake import LakeLayout


def load_lake(value, scenario, serving=None):
    config = json.loads(value) if value.lstrip().startswith("{") else load_json(Path(value))
    layout = LakeLayout.from_config(config, scenario=scenario)
    if layout.use_case != scenario["name"]:
        raise ValueError("lake.use_case must match the selected scenario")
    if serving and (layout.serving != serving or layout.model_version is None):
        raise ValueError("Inference requires the matching lake.serving and an immutable lake.model_version")
    if any("?" in key or "#" in key for key in layout.as_dict().values()):
        raise ValueError("Lake keys must not contain URI queries or fragments")
    return layout


def landing_file(layout, scenario):
    filename = scenario.get("dataset", {}).get("file")
    if (not isinstance(filename, str)
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", filename)
            or filename in (".", "..")):
        raise ValueError("Lake training requires a single reviewed dataset filename")
    uri = urlsplit(layout.blob_uri("landing"))
    container, key = uri.path.lstrip("/").split("/", 1)
    return f"wasbs://{container}@{uri.hostname}/{key.rstrip('/')}/{filename}"


def validate_model(layout, model_uri):
    numeric = re.fullmatch(r"models:/[^/@?#]+/([1-9][0-9]*)", model_uri)
    run = re.fullmatch(r"runs:/([a-fA-F0-9]{32})/[^?#]+", model_uri)
    version = numeric.group(1) if numeric else run.group(1) if run else None
    if version is None or version != layout.model_version:
        raise ValueError("lake.model_version must equal the immutable registered model version or MLflow run ID")


def checkpoint_path(layout, root, spark=None):
    """Use UC Volumes or a separately provisioned HNS/ABFS checkpoint backend."""
    if not root or "?" in root or "#" in root or "\\" in root:
        raise ValueError("Provide a credential-free checkpoint_root, not a SAS URI")
    if root.startswith("/Volumes/"):
        parts = root.strip("/").split("/")
        valid = len(parts) >= 4 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts)
    else:
        uri = urlsplit(root)
        valid = (
            uri.scheme == "abfss" and uri.password is None and uri.port is None
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", uri.username or "")
            and re.fullmatch(
                r"[a-z0-9]{3,24}\.dfs\.core\.(windows\.net|usgovcloudapi\.net|chinacloudapi\.cn)",
                uri.hostname or "",
            )
        )
        parts = uri.path.strip("/").split("/") if uri.path.strip("/") else []
        valid = valid and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts)
        if valid and spark is not None:
            try:
                spark._jvm.org.apache.hadoop.fs.FileSystem.getFileSystemClass(
                    "abfss", spark._jsc.hadoopConfiguration(),
                )
            except Exception:
                raise ValueError("This runtime has no configured ABFS Hadoop checkpoint connector") from None
    if not valid or any(part in (".", "..", "runs", "models") for part in parts):
        raise ValueError("checkpoint_root must be a stable UC Volume or HNS-enabled abfss location, never wasbs")
    return root.rstrip("/") + "/" + layout.key("checkpoint")


def lineage(layout, **bindings):
    return {
        "schema": "ml-model-factory-databricks-lake/v1",
        "project": layout.project, "environment": layout.environment, "use_case": layout.use_case,
        "dataset": layout.dataset, "data_version": layout.data_version,
        "snapshot_id": layout.snapshot_id, "run_id": layout.run_id, "serving": layout.serving,
        "model_version": layout.model_version, "pipeline_id": layout.pipeline_id,
        "pipeline_version": layout.pipeline_version, "paths": layout.as_dict(),
        "bindings": bindings,
        "publication": "Lineage only; declared lake areas are not automatically materialized.",
        "feedback": "Observed late labels require stable event/entity IDs and review; predictions are not labels.",
    }
