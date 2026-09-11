"""Generate one portable notebook per scenario/mode, without cloud side effects."""

import json
from pathlib import Path

from .config import validate_scenario, write_json


def _cell(kind, source):
    cell = {"cell_type": kind, "metadata": {}, "source": source.strip() + "\n"}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


def render_notebooks(scenario, output_dir, mode="custom", runtime_path="runtime.json") -> dict:
    validate_scenario(scenario)
    if mode not in {"automl", "custom"}:
        raise ValueError("mode must be custom or automl")
    name, task = scenario["name"], scenario["task"]
    cells = [
        _cell("markdown", f"""# {name}: {task} ({mode})

Kaggle-only source: `{scenario["dataset"].get("slug") or "NOT SELECTED"}`.
Dataset status: **{scenario["dataset"].get("status", "configured")}**.
{scenario["dataset"].get("notes", "")}

This notebook is an executable template, not evidence of a completed Kaggle or Azure run.
Install the factory's declared extras into this kernel separately. No packages,
credentials, cloud resources, or competition terms are installed/accepted by this notebook.
All execution switches default to false. Run **either** SDK v2 **or** CLI v2 submission, not both.
"""),
        _cell("code", f"""
import json
import subprocess
import sys
from pathlib import Path

candidates = [Path.cwd(), *Path.cwd().parents]
ROOT = next((p for p in candidates if (p / "ml_model_factory" / "config.py").is_file()), None)
if ROOT is None:
    raise RuntimeError("Open this notebook from within the 50-ml-model-factory checkout")
sys.path.insert(0, str(ROOT))
from ml_model_factory.config import load_json, validate_scenario, validate_runtime, write_json

SCENARIO = ROOT / "scenarios" / {json.dumps(name + ".json")}
scenario = validate_scenario(load_json(SCENARIO))
MODE = {json.dumps(mode)}
RUNTIME = Path({json.dumps(str(runtime_path))})
if not RUNTIME.is_absolute():
    RUNTIME = ROOT / RUNTIME
WORK = ROOT / "outputs" / scenario["name"] / MODE
RAW = WORK / "raw"
PREPARED = WORK / "prepared"
MODEL = WORK / "model"
EVALUATION = WORK / "evaluation"
RENDERED = WORK / "azureml"
RUN_INGEST = False
RUN_PREPARE = False
RUN_LOCAL_TRAIN = False
RENDER_AZURE = False
SUBMIT_SDK = False
SUBMIT_CLI = False
USE_LAKE = False
RUN_LAKE_TRAIN = False
LAKE_CONFIG = ROOT / "lake.local.json"
LAKE_ROOT = ROOT / "lake-data"
EFFECTIVE_RUNTIME = RUNTIME

def factory(*arguments):
    command = [sys.executable, "-m", "ml_model_factory", *map(str, arguments)]
    subprocess.run(command, cwd=ROOT, check=True)
"""),
        _cell("markdown", """## Kaggle ingestion and reproducible preparation

Review the source license and any competition rules first. Required-selection and
license-review gates block ingestion. Do not clear them without documented approval.
The download manifest records file hashes and pinned dataset version. Existing nonempty
outputs are never silently replaced. Titanic preparation additionally writes `titanic.parquet`.
Forecasting uses chronological holdouts, not random rows.
"""),
        _cell("code", """
if RUN_INGEST:
    factory("ingest", "--scenario", SCENARIO, "--output", RAW)
INPUT = RAW / scenario["dataset"]["file"]
if RUN_PREPARE:
    factory("prepare", "--scenario", SCENARIO, "--input", INPUT, "--output", PREPARED)
if (PREPARED / "manifest.json").exists():
    print(json.dumps(load_json(PREPARED / "manifest.json"), indent=2))
"""),
    ]
    if mode == "custom":
        cells += [
            _cell("markdown", """## Custom training, held-out evaluation, and Responsible AI

The custom route fits only the training split and exports an MLflow pyfunc model.
Tabular classification/regression provide held-out errors, cohorts and permutation
importance; forecasting preserves time order. Vision produces task-specific metrics
and image/class diagnostics, not an unsupported Azure tabular RAI dashboard.
Small CPU vision limits demonstrate optimization, not production model quality.
"""),
            _cell("code", """
if RUN_LOCAL_TRAIN:
    factory("train", "--scenario", SCENARIO, "--prepared", PREPARED, "--model-output", MODEL)
    factory("evaluate", "--scenario", SCENARIO, "--prepared", PREPARED, "--model", MODEL, "--output", EVALUATION)
if (EVALUATION / "responsible-ai.json").exists():
    print(json.dumps(load_json(EVALUATION / "responsible-ai.json"), indent=2))
"""),
        ]
    if task.startswith("image_"):
        cells.append(_cell("markdown", """## Image portability and AutoML boundaries

Custom manifests reference copied split-local images and remain valid after relocation.
For AutoML, set `vision.image_base_uri` to an **immutable remote prepared-directory root**,
prepare again, and upload the entire prepared tree there without changing the layout.
Remote URLs must use identity-based access, not embedded SAS/credentials. This notebook
does not silently upload image data or replace URIs with job-local mount paths.

AutoML image training is a standalone v2 job where supported; its model requires a
task/version-specific inference adapter. The custom evaluator intentionally rejects
AutoML checkpoints rather than fabricating metrics or claiming an end-to-end RAI pipeline.
"""))
    cells += [
        _cell("markdown", """## Versioned project/use-case lake (optional)

Set the project/environment, dataset version, snapshot ID and unique run ID in
`lake.local.json`. `lake-plan` is read-only. `lake-train` publishes source, gold snapshots,
models and evaluations locally with completion manifests; it does not upload data.
Keep unlabeled inference requests and observed feedback separate. Use `lake-infer` with
an immutable model version and unique request IDs, and `lake-feedback` for reviewed labels.
Streaming checkpoints are independent of execution run IDs and model versions.

Azure preparation uses a per-run working area and records the snapshot reference;
it does not claim that binding an output URI alone publishes an immutable snapshot.
"""),
        _cell("code", """
if USE_LAKE:
    factory("lake-plan", "--scenario", SCENARIO, "--config", LAKE_CONFIG)
    if RENDER_AZURE:
        runtime_with_lake = validate_runtime(load_json(RUNTIME))
        runtime_with_lake["lake"] = load_json(LAKE_CONFIG)
        EFFECTIVE_RUNTIME = WORK / "runtime.local.json"
        write_json(EFFECTIVE_RUNTIME, runtime_with_lake)
if RUN_LAKE_TRAIN:
    if not USE_LAKE or MODE != "custom":
        raise ValueError("Local lake training requires USE_LAKE and custom mode")
    factory("lake-train", "--scenario", SCENARIO, "--config", LAKE_CONFIG,
            "--root", LAKE_ROOT, "--input", INPUT)
"""),
        _cell("markdown", """## Render portable Azure ML v2 jobs (offline)

`runtime.json` must name existing subscription, workspace and compute resources and a
resolvable input data path. Resource discovery is read-only. Rendering creates files,
not Azure resources. Submission incurs compute charges. Image AutoML additionally
requires a GPU-compatible compute target and the prepared remote image layout above.
"""),
        _cell("code", """
if RENDER_AZURE:
    validate_runtime(load_json(EFFECTIVE_RUNTIME))
    factory("render", "--scenario", SCENARIO, "--runtime", EFFECTIVE_RUNTIME,
            "--mode", MODE, "--output", RENDERED)
"""),
        _cell("markdown", "## Azure ML SDK v2 submission — alternative A"),
        _cell("code", """
if SUBMIT_SDK:
    if SUBMIT_CLI:
        raise ValueError("Choose one submission route to avoid duplicate charged jobs")
    from ml_model_factory.azureml import submit
    runtime = validate_runtime(load_json(EFFECTIVE_RUNTIME))
    job_path = RENDERED / ("job.yml" if MODE == "automl" and scenario["task"].startswith("image_") else "pipeline.yml")
    if not job_path.exists():
        raise RuntimeError("Render and review the job before submission")
    # Shared SDK v2 submission binds the configured tenant and rejects unresolved inputs.
    print(submit(job_path, runtime))
"""),
        _cell("markdown", "## Azure ML CLI v2 submission — alternative B"),
        _cell("code", """
if SUBMIT_CLI:
    if SUBMIT_SDK:
        raise ValueError("Choose one submission route to avoid duplicate charged jobs")
    runtime = validate_runtime(load_json(EFFECTIVE_RUNTIME))
    job_path = RENDERED / ("job.yml" if MODE == "automl" and scenario["task"].startswith("image_") else "pipeline.yml")
    if not job_path.exists():
        raise RuntimeError("Render and review the job before submission")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "azureml_cli.py"),
                    "--runtime", str(EFFECTIVE_RUNTIME), "--job", str(job_path)], check=True)

# Equivalent factory SDK-backed submission:
# factory("submit", "--runtime", RUNTIME, "--job", RENDERED / "pipeline.yml")
"""),
    ]
    notebook = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "cells": [cell | {"id": f"factory-{i:02d}"} for i, cell in enumerate(cells)],
    }
    output = Path(output_dir) / f"{name}-{mode}.ipynb"
    write_json(output, notebook)
    return {"notebooks": [str(output)]}
