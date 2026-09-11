"""Offline ADF run-parameter builder; ARM job JSON is NOT Azure ML CLI YAML."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import UUID


def load(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def utc_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("Watermarks must include the UTC timezone")
    return parsed


def reject_credentials(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if re.search(r"(?i)(password|secret|token|sas|connectionstring|accountkey)", key):
                raise ValueError("Lake run parameters must not contain credentials")
            reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            reject_credentials(child)
    elif isinstance(value, str) and (
        re.search(r"(?i)([?&](sig|token|sv)=|AccountKey=|SharedAccessSignature=|SharedAccessKey=|Bearer\s)", value)
    ):
        raise ValueError("Lake run parameters must not contain credentials")


def bind_lake(copy, payload, lake, scenario, input_name):
    from ml_model_factory.lake import LakeLayout

    reject_credentials({"lake": lake, "copy": copy, "payload": payload})
    if not isinstance(scenario, dict) or not scenario.get("name"):
        raise ValueError("Lake Copy requires --scenario with a reviewed dataset file")
    layout = LakeLayout.from_config(lake, scenario=scenario)
    if layout.use_case != scenario["name"]:
        raise ValueError("lake.use_case must match the selected scenario")
    if any("?" in key or "#" in key for key in layout.as_dict().values()):
        raise ValueError("Lake keys must not contain URI queries or fragments")
    filename = scenario.get("dataset", {}).get("file")
    if (not isinstance(filename, str)
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", filename)
            or filename in (".", "..")):
        raise ValueError("Lake Copy requires a single dataset filename; set sourceFolder to its containing directory")
    if scenario.get("task", "").startswith("image_") and not Path(filename).suffix:
        raise ValueError("Image-directory Copy needs a reviewed folder/manifest binding, not the single-file lake adapter")
    pattern = copy.get("filePattern")
    if pattern not in (None, "*", filename):
        raise ValueError("Lake Copy filePattern must select the scenario dataset file")
    if not layout.container or not layout.account_url:
        raise ValueError("Lake Copy requires lake.storage.container and account_url")
    inputs = payload["properties"].get("inputs", {})
    if not isinstance(inputs, dict) or not isinstance(inputs.get(input_name), dict):
        raise ValueError("Lake Copy requires an existing named ARM job input to bind")
    if inputs[input_name].get("jobInputType") not in ("uri_file", "uri_folder"):
        raise ValueError("The lake-bound ARM job input must be uri_file or uri_folder")
    copy = {**copy, "sinkContainer": layout.container, "sinkFolder": layout.key("landing"),
            "filePattern": filename}
    payload = deepcopy(payload)
    payload["properties"]["inputs"][input_name].update(
        jobInputType="uri_file", uri=layout.azureml_uri("landing").rstrip("/") + "/" + filename,
    )
    metadata = {
        "project": layout.project, "environment": layout.environment, "useCase": layout.use_case,
        "dataset": layout.dataset, "dataVersion": layout.data_version,
        "snapshotId": layout.snapshot_id, "runId": layout.run_id, "serving": layout.serving,
        "pipelineId": layout.pipeline_id, "pipelineVersion": layout.pipeline_version,
        "paths": layout.as_dict(), "copyStage": "landing",
        "storageAccountUrl": layout.account_url, "container": layout.container,
    }
    if layout.model_version is not None:
        metadata["modelVersion"] = layout.model_version
    tags = payload["properties"].setdefault("tags", {})
    if not isinstance(tags, dict):
        raise ValueError("ARM job properties.tags must be an object")
    for name in ("project", "environment", "useCase", "dataset", "dataVersion", "snapshotId", "runId"):
        tags["lake." + name] = metadata[name]
    return copy, payload, metadata


def build_parameters(runtime, copy, payload, lake=None, scenario=None, input_name="raw"):
    lake = lake if lake is not None else runtime.get("lake")
    UUID(runtime["subscription_id"])
    for key in ("resource_group", "workspace_name"):
        if not re.fullmatch(r"[\w.()-]+", runtime.get(key, "")):
            raise ValueError(f"Invalid runtime.{key}")
    allowed = {
        "loadMode", "sourceContainer", "sourceFolder", "sinkContainer", "sinkFolder",
        "filePattern", "watermarkStart", "watermarkEnd",
    }
    if set(copy) - allowed:
        raise ValueError("Unknown Copy configuration keys")
    if copy.get("loadMode") not in ("initial", "delta"):
        raise ValueError("loadMode must be initial or delta")
    for key in ("sourceContainer", "sinkContainer", "sourceFolder", "sinkFolder"):
        if lake is not None and key.startswith("sink"):
            continue
        if not isinstance(copy.get(key), str) or (key.endswith("Container") and not copy[key]):
            raise ValueError(f"{key} is required")
    if copy["loadMode"] == "delta":
        if utc_time(copy["watermarkStart"]) >= utc_time(copy["watermarkEnd"]):
            raise ValueError("Delta requires watermarkStart < watermarkEnd")
    properties = payload.get("properties")
    if not isinstance(properties, dict) or properties.get("jobType") not in {
        "Command", "Pipeline", "AutoML", "Spark", "Sweep",
    }:
        raise ValueError("Use Jobs ARM properties.jobType, not CLI YAML type/jobs")
    if any(key in payload for key in ("type", "$schema", "jobs")):
        raise ValueError("CLI YAML cannot be submitted as the Jobs ARM body")
    metadata = None
    if lake is not None:
        copy, payload, metadata = bind_lake(copy, payload, lake, scenario, input_name)
    result = {
        **copy,
        "subscriptionId": runtime["subscription_id"],
        "resourceGroup": runtime["resource_group"],
        "workspaceName": runtime["workspace_name"],
        "jobPayload": payload,
    }
    if metadata is not None:
        result["lakeParameters"] = metadata
    if "REPLACE" in json.dumps(result) or "<" in json.dumps(result):
        raise ValueError("Resolve example placeholders before generating a run")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--copy", required=True)
    parser.add_argument("--job-payload", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", help="Optional lake JSON; otherwise uses runtime.lake when present")
    parser.add_argument("--scenario", help="Scenario JSON required for lake-bound raw Copy input")
    parser.add_argument("--input-name", default="raw", help="Existing ARM job input bound to the copied file")
    args = parser.parse_args()
    result = build_parameters(
        load(args.runtime), load(args.copy), load(args.job_payload),
        lake=load(args.lake) if args.lake else None,
        scenario=load(args.scenario) if args.scenario else None, input_name=args.input_name,
    )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote run parameters to {path}; no Azure operations were performed.")


if __name__ == "__main__":
    main()
