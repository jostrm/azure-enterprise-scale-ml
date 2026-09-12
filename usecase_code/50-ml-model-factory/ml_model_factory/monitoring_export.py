"""Read-only report validation, compact monitor tags, and explicit publication."""

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from .config import load_json
from .monitoring import SCHEMA, STATES, iso, utc
from .tags import assert_scope, scope_tags
from .lake import identifier


def add_evaluation_metrics(report: dict, metrics: dict) -> dict:
    """Expose every numeric evaluation metric without copying raw evaluation records."""
    if not isinstance(metrics, dict) or len(metrics) > 100:
        raise ValueError("Evaluation metrics must be a bounded numeric dictionary")
    names = {metric["name"] for metric in report["metrics"]}
    for name, value in metrics.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,95}", name):
            raise ValueError("Evaluation metric names must be stable identifiers")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("Evaluation metrics must be finite numbers or null")
        key = "evaluation_reference." + name
        if key in names:
            raise ValueError("Duplicate evaluation metric")
        report["metrics"].append({"name": key, "value": value, "unit": "score", "status": "unknown",
                                  "detail": "Supplied evaluation artifact; not a current-window health measurement"})
        names.add(key)
    return report


def validate_report(report: dict, *, now: datetime | None = None) -> dict:
    if report.get("schema") != SCHEMA or report.get("source") not in ("ml-model-factory", "agent-factory"):
        raise ValueError("Unsupported monitoring report contract")
    scope_tags(report.get("scope"), require=True)
    if (report["source"] == "ml-model-factory") != (report.get("subject", {}).get("kind") == "model"):
        raise ValueError("Monitoring source and subject kind disagree")
    subject = report.get("subject", {})
    if (subject.get("kind") not in ("model", "agent") or
            any(not isinstance(subject.get(key), str) or not subject[key] for key in ("name", "version", "task_type"))):
        raise ValueError("Monitoring subject must identify a specific model/agent version")
    identifier(subject["name"], "monitoring.subject.name")
    identifier(subject["version"], "monitoring.subject.version")
    if subject["version"].lower() in ("latest", "active", "production", "champion"):
        raise ValueError("Monitoring subject version must be immutable")
    if report["source"] == "ml-model-factory":
        identifier(report.get("use_case"), "monitoring.use_case")
    for name in ("status", "data_drift", "concept_drift"):
        if report.get("summary", {}).get(name) not in STATES:
            raise ValueError("Unknown monitoring status")
    generated, end, start, expires = (utc(value) for value in (
        report["generated_at"], report["window"]["end"], report["window"]["start"], report["expires_at"],
    ))
    now = now or datetime.now(timezone.utc)
    if not start < end <= generated <= now or expires < end:
        raise ValueError("Monitoring timestamps are inconsistent or in the future")
    metrics = report.get("metrics")
    if not isinstance(metrics, list) or len(metrics) > 1000:
        raise ValueError("Monitoring metrics must be a bounded list")
    names = []
    for metric in metrics:
        value = metric.get("value")
        if (not isinstance(metric.get("name"), str) or not metric["name"]
                or metric.get("status") not in STATES or not isinstance(metric.get("unit"), str)):
            raise ValueError("Invalid monitoring metric record")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int))):
            raise ValueError("Metric values must be numbers or null")
        names.append(metric["name"])
    if len(set(names)) != len(names):
        raise ValueError("Monitoring metric names must be unique")
    serialized = json.dumps(report, allow_nan=False)
    if len(serialized.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Monitoring report exceeds the two-MiB size limit")
    return report


def report_uri(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".blob.core.windows.net")
            or url.username or url.password or url.query or url.fragment or not url.path.endswith(".json")):
        raise ValueError("Monitoring report URI must be an immutable credential-free Azure Blob JSON URL")
    return value


def summary_tags(report: dict, uri: str | None = None, *, now: datetime | None = None) -> dict[str, str]:
    validate_report(report, now=now)
    now = now or datetime.now(timezone.utc)
    expired = utc(report["expires_at"]) < now
    subject = report["subject"]
    tags = {
        "mon_schema": "1", "mon_source": report["source"], "mon_kind": subject["kind"],
        "mon_subject_version": subject["version"],
        "mon_status": "stale" if expired else report["summary"]["status"],
        "mon_data_drift": "stale" if expired else report["summary"]["data_drift"],
        "mon_concept_drift": "stale" if expired else report["summary"]["concept_drift"],
        "mon_checked_at": report["generated_at"], "mon_window_end": report["window"]["end"],
        "mon_expires_at": report["expires_at"],
    }
    if uri:
        tags["mon_report_uri"] = report_uri(uri)
    features = report.get("details", {}).get("data_drift", {}).get("features", [])
    scores = [item["value"] for item in features if item.get("value") is not None]
    if scores:
        tags["mon_data_score"] = format(max(scores), ".6g")
    score = report.get("details", {}).get("concept_drift", {}).get("value")
    if score is not None:
        tags["mon_concept_score"] = format(score, ".6g")
    return tags


def publish_model_report(report_path: Path, runtime: dict) -> dict:
    """Publish immutable JSON then update only monitor summaries on the exact model.

    The SDK model update is read-modify-write; schedule one publisher per model
    version. It is not a distributed transaction with the Blob upload.
    """
    from azure.storage.blob import BlobServiceClient, ContentSettings
    from .azureml import _client
    from .lake import LakeLayout

    report = validate_report(load_json(report_path))
    if report["source"] != "ml-model-factory" or report["subject"]["kind"] != "model":
        raise ValueError("This publisher updates Azure ML model-version monitoring only")
    assert_scope(report["scope"], runtime)
    layout = LakeLayout.from_config(runtime["lake"], {"name": report["use_case"]})
    if layout.use_case != report["use_case"]:
        raise ValueError("Monitoring report use case differs from its destination lake path")
    if layout.model_version is not None and layout.model_version != report["subject"]["version"]:
        raise ValueError("Lake model_version differs from monitoring subject version")
    if not layout.account_url or not layout.container:
        raise ValueError("An existing project Blob monitoring destination is required")
    client = _client(runtime)
    subject = report["subject"]
    model = client.models.get(name=subject["name"], version=subject["version"])
    if model.name != subject["name"] or str(model.version) != subject["version"]:
        raise ValueError("Resolved registry model identity differs from the monitoring report")
    assert_scope(model.tags or {}, runtime)
    if (model.tags or {}).get("use_case") != report["use_case"]:
        raise ValueError("Registered model use case differs from monitoring report")
    tags = dict(model.tags or {})
    if tags.get("task_type") and tags["task_type"] != subject["task_type"]:
        raise ValueError("Registered model task differs from the monitoring report")
    if tags.get("mon_window_end") and utc(tags["mon_window_end"]) > utc(report["window"]["end"]):
        raise ValueError("A newer monitoring window is already published for this model")
    if (tags.get("mon_window_end") == report["window"]["end"] and tags.get("mon_checked_at")
            and utc(tags["mon_checked_at"]) > utc(report["generated_at"])):
        raise ValueError("A newer assessment of this monitoring window is already published")
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    credential = ManagedIdentityCredential(client_id=runtime.get("managed_identity_client_id")) if runtime.get("credential") == "managed_identity" else AzureCliCredential(tenant_id=runtime["tenant_id"])
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    key = layout.key("use_case_root") + f"/monitoring/models/{subject['version']}/reports/{digest}.json"
    uri = f"{layout.account_url}/{layout.container}/{key}"
    summary = summary_tags(report, uri)
    with BlobServiceClient(layout.account_url, credential=credential) as service:
        container = service.get_container_client(layout.container)
        container.get_container_properties()
        blob = container.get_blob_client(key)
        from azure.core.exceptions import ResourceExistsError
        try:
            blob.upload_blob(payload, overwrite=False, metadata={"sha256": digest},
                             content_settings=ContentSettings(content_type="application/json"))
        except ResourceExistsError:
            if blob.download_blob().readall() != payload:
                raise ValueError("Existing immutable report content differs")
    model.tags = {key: value for key, value in tags.items() if not key.startswith("mon_")} | summary
    updated = client.models.create_or_update(model)
    if any(updated.tags.get(key) != value for key, value in summary.items()):
        raise ValueError("Monitoring model tags were not persisted")
    return {"model_id": updated.id, "report_uri": uri, "tags": summary}
