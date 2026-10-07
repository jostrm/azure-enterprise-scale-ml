"""Generate one thin notebook per use-case leaf and scenario from composable sections.

Notebooks only orchestrate shared engines (factory CLI, ESML pipeline factory,
Databricks jobs); they contain no copy of training, scoring or deployment logic.
Every cloud action sits behind a switch that defaults to ``False``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .usecases import PATTERN_SUMMARY, TASK_FOLDER_BY_TASK, UseCase, catalog, find, scenarios_by_task


GENERATED_START = "<!-- usecase-catalog:start -->"
GENERATED_END = "<!-- usecase-catalog:end -->"


def _cell(kind: str, source: str) -> dict:
    cell = {"cell_type": kind, "metadata": {}, "source": source.strip() + "\n"}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


@dataclass
class Section:
    cells: list = field(default_factory=list)
    switches: tuple = ()
    settings: tuple = ()


def _bullets(values) -> str:
    return "\n".join(f"- {value}" for value in values)


def _header(leaf: UseCase, scenario: dict) -> Section:
    dataset = scenario["dataset"]
    return Section([_cell("markdown", f"""# {scenario['name']}: {scenario['task']} ({leaf.pattern}, {leaf.technology.short})

**Use case:** `{leaf.folder.as_posix()}` — {PATTERN_SUMMARY[leaf.pattern]} with the {leaf.technology.title}.

**Training:** {leaf.training}

**Serving:** {leaf.serving}

**Status:** {leaf.status}

Kaggle-only source: `{dataset.get("slug") or "NOT SELECTED"}`.
Dataset status: **{dataset.get("status", "configured")}**.
{dataset.get("notes", "")}

**Prerequisites**

{_bullets(leaf.prerequisites)}

**Limitations**

{_bullets(leaf.limitations)}

This notebook is an executable template, not evidence of a completed Kaggle or Azure run.
Install the factory's declared extras into this kernel separately. No packages,
credentials, cloud resources, or competition terms are installed/accepted by this notebook.
All execution switches default to false. Run **either** SDK v2 **or** CLI v2 submission, not both.
""")])


def _setup(leaf: UseCase, scenario: dict, runtime_path: str, switches: list, settings: list) -> dict:
    lines = "\n".join(f"{name} = False" for name in switches)
    extra = "\n".join(f"{name} = {value}" for name, value in settings)
    return _cell("code", f"""
import json
import os
import subprocess
import sys
from pathlib import Path

candidates = [Path.cwd(), *Path.cwd().parents]
ROOT = next((p for p in candidates if (p / "pyproject.toml").is_file()
             and (p / "accelerator" / "src" / "ml_model_factory" / "config.py").is_file()), None)
if ROOT is None:
    raise RuntimeError("Open this notebook from within the 50-ml-model-factory checkout")
SOURCE = ROOT / "accelerator" / "src"
sys.path.insert(0, str(SOURCE))
from ml_model_factory.config import load_json, validate_scenario, validate_runtime, write_json

SCENARIO = ROOT / "user-config" / "model" / "scenarios" / {json.dumps(scenario["name"] + ".json")}
scenario = validate_scenario(load_json(SCENARIO))
MODE = {json.dumps(leaf.mode)}
PATTERN = {json.dumps(leaf.pattern)}
TECHNOLOGY = {json.dumps(leaf.technology.key)}
RUNTIME = Path({json.dumps(str(runtime_path))})
if not RUNTIME.is_absolute():
    RUNTIME = ROOT / RUNTIME
WORK = ROOT / "ml-environment" / "outputs" / scenario["name"] / {json.dumps(leaf.run_key)}
RAW = ROOT / "data" / "in" / scenario["name"]
PREPARED = ROOT / "data" / "out" / scenario["name"] / {json.dumps(leaf.run_key)} / "prepared"
MODEL = WORK / "model"
EVALUATION = WORK / "evaluation"
RENDERED = WORK / "azureml"
INFERENCE = WORK / PATTERN
REQUESTS = INFERENCE / "requests"
MODEL_NAME = scenario.get("model_name", scenario["name"])
MODEL_ID = ""  # immutable azureml:<name>:<version> after quality-gated registration
{lines}
{extra}
LAKE_CONFIG = ROOT / "user-config" / "lake.local.json"
LAKE_ROOT = ROOT / "data" / "out" / "lake-data"
EFFECTIVE_RUNTIME = RUNTIME
FACTORY_ENV = os.environ.copy()
FACTORY_ENV["PYTHONPATH"] = str(SOURCE) + os.pathsep + FACTORY_ENV.get("PYTHONPATH", "")
FACTORY_ENV.setdefault("MLFLOW_TRACKING_URI", (ROOT / "ml-environment" / "mlruns").as_uri())

def factory(*arguments):
    command = [sys.executable, "-m", "ml_model_factory", *map(str, arguments)]
    subprocess.run(command, cwd=ROOT, env=FACTORY_ENV, check=True)
""")


def _data() -> Section:
    return Section([
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
    ], switches=("RUN_INGEST", "RUN_PREPARE"))


def _local_training() -> Section:
    return Section([
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
    ], switches=("RUN_LOCAL_TRAIN",))


def _vision_note(leaf: UseCase) -> Section:
    return Section([_cell("markdown", """## Image portability and AutoML boundaries

Custom manifests reference copied split-local images and remain valid after relocation.
For AutoML, set `vision.image_base_uri` to an **immutable remote prepared-directory root**,
prepare again, and upload the entire prepared tree there without changing the layout.
Remote URLs must use identity-based access, not embedded SAS/credentials. This notebook
does not silently upload image data or replace URIs with job-local mount paths.

With `runtime.lake` (with a datastore) and a pinned `automl_vision_environment`, AutoML image
rendering binds the prepared images to the lake and produces a quality-gated pipeline (prepare,
AutoML, evaluate) whose evaluator uses the documented AutoML image scoring schema. Without both,
only a standalone AutoML training job is rendered, which cannot be registered.
""")])


def _lake() -> Section:
    return Section([
        _cell("markdown", """## Versioned project/use-case lake (optional)

Set the project/environment, dataset version, snapshot ID and unique run ID in
`user-config/lake.local.json`. `lake-plan` is read-only. `lake-train` publishes source, gold snapshots,
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
    ], switches=("USE_LAKE", "RUN_LAKE_TRAIN"))


def _render() -> Section:
    return Section([
        _cell("markdown", """## Render portable Azure ML v2 jobs (offline)

`user-config/runtime.local.json` must name existing subscription, workspace and compute resources and a
resolvable input data path. Resource discovery is read-only. Rendering creates files,
not Azure resources. Submission incurs compute charges. Image AutoML additionally
requires a GPU-compatible compute target and the prepared remote image layout above.
"""),
        _cell("code", """
if RENDER_AZURE:
    validate_runtime(load_json(EFFECTIVE_RUNTIME))
    factory("render", "--scenario", SCENARIO, "--runtime", EFFECTIVE_RUNTIME,
            "--mode", MODE, "--output", RENDERED)
JOB_PATH = RENDERED / "pipeline.yml" if (RENDERED / "pipeline.yml").exists() else RENDERED / "job.yml"
"""),
    ], switches=("RENDER_AZURE",))


def _submit(job: str = "JOB_PATH") -> Section:
    return Section([
        _cell("markdown", "## Azure ML SDK v2 submission — alternative A"),
        _cell("code", f"""
if SUBMIT_SDK:
    if SUBMIT_CLI:
        raise ValueError("Choose one submission route to avoid duplicate charged jobs")
    from ml_model_factory.azureml import submit
    runtime = validate_runtime(load_json(EFFECTIVE_RUNTIME))
    if not {job}.exists():
        raise RuntimeError("Render and review the job before submission")
    # Shared SDK v2 submission binds the configured tenant and rejects unresolved inputs.
    print(submit({job}, runtime))
"""),
        _cell("markdown", "## Azure ML CLI v2 submission — alternative B"),
        _cell("code", f"""
if SUBMIT_CLI:
    if SUBMIT_SDK:
        raise ValueError("Choose one submission route to avoid duplicate charged jobs")
    runtime = validate_runtime(load_json(EFFECTIVE_RUNTIME))
    if not {job}.exists():
        raise RuntimeError("Render and review the job before submission")
    subprocess.run([sys.executable, str(ROOT / "accelerator" / "scripts" / "azureml_cli.py"),
                    "--runtime", str(EFFECTIVE_RUNTIME), "--job", str({job})],
                   cwd=ROOT, env=FACTORY_ENV, check=True)

# Equivalent factory SDK-backed submission:
# factory("submit", "--runtime", RUNTIME, "--job", {job})
"""),
    ], switches=("SUBMIT_SDK", "SUBMIT_CLI"))


def _register() -> Section:
    return Section([
        _cell("markdown", """## Quality-gated model registration

Only a completed factory pipeline whose `evaluate` step wrote a passing `quality-gate.json`
can register its named model output. Standalone training jobs are not a quality gate.
Set `PIPELINE_JOB_NAME` to the completed job, then copy the printed immutable model ID
into `MODEL_ID`. Registration is not production promotion.
"""),
        _cell("code", """
if REGISTER_MODEL:
    if not PIPELINE_JOB_NAME:
        raise ValueError("Set PIPELINE_JOB_NAME to the completed, evaluated factory pipeline job")
    subprocess.run([sys.executable, str(ROOT / "accelerator" / "scripts" / "azureml_sdk.py"),
                    "--runtime", str(EFFECTIVE_RUNTIME), "register", "--job-name", PIPELINE_JOB_NAME,
                    "--model-name", MODEL_NAME], cwd=ROOT, env=FACTORY_ENV, check=True)
print("MODEL_ID:", MODEL_ID or "not set")
"""),
    ], switches=("REGISTER_MODEL",), settings=(("PIPELINE_JOB_NAME", '""'),))


def _requests(leaf: UseCase) -> Section:
    use = {
        "batch": "`requests.parquet` is the unlabeled batch input",
        "online": "`online-request.json` is the endpoint payload",
        "streaming": "`events.jsonl` holds event-shaped requests (`event_id`, `event_time`, features)",
    }[leaf.pattern]
    return Section([
        _cell("markdown", f"""## Unlabeled requests from the held-out split

`sample-requests` writes demonstration requests without labels; {use}.
`labels.parquet` keeps held-out truth separately for monitoring demos, and forecasting
also writes `history.parquet` for AutoML scoring. Never send labels to a model.
"""),
        _cell("code", """
if SAMPLE_REQUESTS:
    factory("sample-requests", "--scenario", SCENARIO, "--prepared", PREPARED, "--output", REQUESTS, "--rows", 10)
if (REQUESTS / "manifest.json").exists():
    print(json.dumps(load_json(REQUESTS / "manifest.json"), indent=2))
"""),
    ], switches=("SAMPLE_REQUESTS",))


def _local_serving(leaf: UseCase) -> Section:
    if leaf.pattern == "batch":
        return Section([
            _cell("markdown", """## Local batch scoring

Scores the unlabeled requests with the locally trained model and writes
`predictions.parquet` plus `runinfo.json` lineage (input/model hashes and model tags).
"""),
            _cell("code", """
if RUN_LOCAL_SCORE:
    factory("score", "--scenario", SCENARIO, "--model", MODEL,
            "--input", REQUESTS / "requests.parquet", "--output", INFERENCE / "predictions")
if (INFERENCE / "predictions" / "runinfo.json").exists():
    print(json.dumps(load_json(INFERENCE / "predictions" / "runinfo.json"), indent=2))
"""),
        ], switches=("RUN_LOCAL_SCORE",))
    if leaf.pattern == "online":
        return Section([
            _cell("markdown", """## Local online contract test

Runs the same request parser and scoring service as the Azure ML scoring entry point
in-process (no Docker, no network) and checks one prediction per request row.
"""),
            _cell("code", """
if RUN_ONLINE_TEST:
    factory("online-test", "--scenario", SCENARIO, "--model", MODEL,
            "--request", REQUESTS / "online-request.json", "--output", INFERENCE / "online-response.json")
if (INFERENCE / "online-response.json").exists():
    print(json.dumps(load_json(INFERENCE / "online-response.json"), indent=2))
"""),
        ], switches=("RUN_ONLINE_TEST",))
    return Section([
        _cell("markdown", """## Local stream simulation and Event Hubs consumer

`stream-score` reads JSONL events in deterministic micro-batches, quarantines invalid,
duplicate or late events, scores the rest and commits a checkpoint only after the batch
output is written. Rerunning resumes from the checkpoint without duplicating output.
The Event Hubs consumer uses `runtime.streaming.eventhubs` and your Azure CLI identity
(Event Hubs Data Receiver role); connection strings and SAS tokens are not accepted.
"""),
        _cell("code", """
STREAM = INFERENCE / "stream"
if RUN_LOCAL_STREAM:
    factory("stream-score", "--scenario", SCENARIO, "--model", MODEL, "--mode", MODE,
            "--source", "jsonl", "--events", REQUESTS, "--checkpoint", STREAM / "checkpoint.json",
            "--output", STREAM / "predictions", "--max-batches", 3, "--max-events", 4)
if RUN_EVENT_HUBS_CONSUMER:
    runtime = validate_runtime(load_json(RUNTIME))
    hub = runtime["streaming"]["eventhubs"]
    factory("stream-score", "--scenario", SCENARIO, "--model", MODEL, "--mode", MODE,
            "--source", "eventhubs", "--namespace", hub["namespace"], "--eventhub", hub["eventhub"],
            "--consumer-group", hub["consumer_group"], "--credential", "azure_cli",
            "--tenant-id", runtime["tenant_id"], "--checkpoint", STREAM / "eventhubs-checkpoint.json",
            "--output", STREAM / "eventhubs-predictions", "--max-batches", 1)
"""),
    ], switches=("RUN_LOCAL_STREAM", "RUN_EVENT_HUBS_CONSUMER"))


def _azure_serving(leaf: UseCase) -> Section:
    automl_forecast = leaf.mode == "automl" and leaf.task == "forecasting"
    if leaf.pattern == "online":
        history = '\n                 "--history", REQUESTS / "history.parquet",' if automl_forecast else ""
        return Section([
            _cell("markdown", """## Azure ML managed online endpoint

`serving-render` chooses no-code MLflow deployment where Azure supports it and a custom
scoring entry point (the same service as the local contract test) otherwise. Deployment
checks the registered model's quality-gate, pipeline, scenario, mode and scope tags and
moves traffic last. `serving-invoke` adapts the factory request to the bundle's documented
contract (AutoML image column, AutoML forecast history). Endpoints bill while deployed:
delete them when finished.
"""),
            _cell("code", f"""
ONLINE_BUNDLE = INFERENCE / "azureml-online"
if RENDER_ONLINE:
    factory("serving-render", "--scenario", SCENARIO, "--runtime", EFFECTIVE_RUNTIME, "--kind", "online",
            "--model-name", MODEL_NAME, "--mode", MODE, "--output", ONLINE_BUNDLE)
if ONLINE_ENDPOINT is None and (ONLINE_BUNDLE / "manifest.json").exists():
    ONLINE_ENDPOINT = load_json(ONLINE_BUNDLE / "manifest.json")["endpoint_name"]
if DEPLOY_ONLINE:
    if not MODEL_ID:
        raise ValueError("Set MODEL_ID to the immutable registered model version")
    factory("serving-deploy", "--runtime", EFFECTIVE_RUNTIME, "--bundle", ONLINE_BUNDLE,
            "--model-id", MODEL_ID, "--execute")
if INVOKE_ONLINE:
    factory("serving-invoke", "--runtime", EFFECTIVE_RUNTIME, "--kind", "online", "--endpoint", ONLINE_ENDPOINT,
            "--request", REQUESTS / "online-request.json", "--bundle", ONLINE_BUNDLE,{history} "--execute")
if DELETE_ONLINE:
    factory("serving-delete", "--runtime", EFFECTIVE_RUNTIME, "--kind", "online", "--endpoint", ONLINE_ENDPOINT,
            "--execute")
"""),
        ], switches=("RENDER_ONLINE", "DEPLOY_ONLINE", "INVOKE_ONLINE", "DELETE_ONLINE"),
            settings=(("ONLINE_ENDPOINT", "None"),))
    if leaf.pattern == "batch":
        history = '\n                "--history", BATCH_HISTORY_URI,' if automl_forecast else ""
        settings = (("BATCH_ENDPOINT", "None"), ("BATCH_INPUT_URI", '""  # credential-free URI of uploaded requests'))
        if automl_forecast:
            settings += (("BATCH_HISTORY_URI", '""  # credential-free URI of uploaded history.parquet'),)
        return Section([
            _cell("markdown", """## Azure ML batch serving

`serving-render --kind batch` renders a no-code MLflow batch endpoint for tabular
classification/regression and a factory scoring pipeline job otherwise (forecasting,
images, AutoML forecast with history). Upload the unlabeled requests to the selected
storage first and set `BATCH_INPUT_URI` to that credential-free URI (a folder input must
contain `data.parquet`). Scoring-job bundles have no persistent deployment: each
invocation resolves the registered model and inputs into a new job file and submits it.
"""),
            _cell("code", f"""
BATCH_BUNDLE = INFERENCE / "azureml-batch"
if RENDER_BATCH:
    factory("serving-render", "--scenario", SCENARIO, "--runtime", EFFECTIVE_RUNTIME, "--kind", "batch",
            "--model-name", MODEL_NAME, "--mode", MODE, "--output", BATCH_BUNDLE)
if BATCH_ENDPOINT is None and (BATCH_BUNDLE / "manifest.json").exists():
    BATCH_ENDPOINT = load_json(BATCH_BUNDLE / "manifest.json").get("endpoint_name")
if DEPLOY_BATCH:
    if not MODEL_ID:
        raise ValueError("Set MODEL_ID to the immutable registered model version")
    if BATCH_ENDPOINT:
        factory("serving-deploy", "--runtime", EFFECTIVE_RUNTIME, "--bundle", BATCH_BUNDLE,
                "--model-id", MODEL_ID, "--execute")
    else:
        print("Scoring-job bundle: no persistent deployment; INVOKE_BATCH submits a resolved job")
if INVOKE_BATCH:
    if not BATCH_INPUT_URI:
        raise ValueError("Upload unlabeled requests and set BATCH_INPUT_URI")
    if BATCH_ENDPOINT:
        factory("serving-invoke", "--runtime", EFFECTIVE_RUNTIME, "--kind", "batch", "--endpoint", BATCH_ENDPOINT,
                "--input", BATCH_INPUT_URI, "--execute")
    else:
        factory("serving-invoke", "--runtime", EFFECTIVE_RUNTIME, "--kind", "batch", "--bundle", BATCH_BUNDLE,
                "--model-id", MODEL_ID, "--input", BATCH_INPUT_URI,{history} "--execute")
"""),
        ], switches=("RENDER_BATCH", "DEPLOY_BATCH", "INVOKE_BATCH"), settings=settings)
    return Section([
        _cell("markdown", """## Azure ML scheduled micro-batch streaming

`stream-job render` writes a pipeline job whose step runs `stream-score` against Event Hubs
with the job's managed identity, resuming from a stable lake checkpoint, plus a recurrence
schedule. Latency is the schedule interval. Submit one bounded run first, then create
the schedule; recurring jobs incur compute charges until the schedule is disabled.
"""),
        _cell("code", """
STREAM_BUNDLE = INFERENCE / "azureml-stream-job"
if RENDER_STREAM_JOB:
    if not MODEL_ID:
        raise ValueError("Set MODEL_ID to the immutable registered model version")
    factory("stream-job", "render", "--scenario", SCENARIO, "--runtime", EFFECTIVE_RUNTIME,
            "--model-id", MODEL_ID, "--mode", MODE, "--output", STREAM_BUNDLE, "--interval-minutes", 15)
if SUBMIT_STREAM_JOB:
    factory("stream-job", "submit", "--runtime", EFFECTIVE_RUNTIME, "--job", STREAM_BUNDLE / "job.yml", "--execute")
if CREATE_STREAM_SCHEDULE:
    factory("stream-job", "schedule", "--runtime", EFFECTIVE_RUNTIME,
            "--schedule", STREAM_BUNDLE / "schedule.yml", "--execute")
"""),
    ], switches=("RENDER_STREAM_JOB", "SUBMIT_STREAM_JOB", "CREATE_STREAM_SCHEDULE"))


def _esml_training(leaf: UseCase) -> Section:
    kind = "IN_2_GOLD_TRAINING_AUTOML" if leaf.mode == "automl" else "IN_2_GOLD_TRAINING_MANUAL"
    return Section([
        _cell("markdown", f"""## ESML pipeline factory: `{kind}`

The reusable ESML v2 pipeline factory compiles this scenario's reviewed source binding from
`user-config/esml-rollout.local.json` (schema `esml.azureml-rollout-config/v1`, see the
example file) into a medallion IN-to-BRONZE-to-SILVER-to-GOLD pipeline with a leakage-aware
split, `{kind}` and held-out evaluation. `AzureMLRollout` records every cloud write as a
receipt; it never resubmits after an uncertain outcome. Preparation is offline.
"""),
        _cell("code", """
ESML_CONFIG = ROOT / "user-config" / "esml-rollout.local.json"
ESML_OUTPUT = WORK / "esml"


def esml_rollout(cloud=False):
    \"\"\"Import the ESML SDK (installed or from the purple/orange checkout) and bind this scenario.\"\"\"
    try:
        import azure_esml  # noqa: F401
    except ModuleNotFoundError:
        for candidate in (ROOT.parents[1] / "esml-v2", ROOT.parents[1] / "azure-enterprise-scale-ml" / "esml-v2"):
            if (candidate / "azure_esml" / "__init__.py").is_file():
                sys.path.insert(0, str(candidate))
                break
        else:
            raise RuntimeError("Install azure-esml-sdk or open this notebook inside the purple/orange checkout")
    from azure_esml import ESMLProject
    from azure_esml.domain_layer.rollout import AzureMLRollout, project_from_rollout_config
    config = load_json(ESML_CONFIG)
    project = project_from_rollout_config(config, ROOT / "user-config" / "model" / "scenarios",
                                          scenario=scenario["name"], mode=MODE, base_path=ESML_CONFIG.parent)
    if cloud:
        from azure_esml.base_layer import AzureMLSDKBackend
        project = ESMLProject(project.settings, backend=AzureMLSDKBackend.from_cli(project.target, subscription_bound=True))
    return AzureMLRollout(project, ESML_OUTPUT), config


if PREPARE_ESML or RUN_ESML_TRAINING:
    rollout, config = esml_rollout(cloud=RUN_ESML_TRAINING)
    binding = config["scenarios"][scenario["name"]]
    RUN_ID = RUN_ID or binding["run_id"]
    from azure_esml.domain_layer.rollout import SCENARIO_NUMBERS
    if PREPARE_ESML:
        request = rollout.prepare(model_number=SCENARIO_NUMBERS[scenario["name"]], mode=MODE,
                                  data_date_utc=config["data_date_utc"], run_id=RUN_ID,
                                  data_version=binding["data_version"])
        print(json.dumps(request, indent=2))
    if RUN_ESML_TRAINING:
        if not COMPONENT_VERSION:
            raise ValueError("Set COMPONENT_VERSION to a new pinned pipeline component version")
        if not (ESML_OUTPUT / RUN_ID / "registered-definitions.json").exists():
            rollout.register_definitions(RUN_ID, component_version=COMPONENT_VERSION)
        policy = load_json(SELECTION_POLICY) if SELECTION_POLICY else None
        print(json.dumps(rollout.execute_training(RUN_ID, selection_policy=policy, no_champion=NO_CHAMPION), indent=2))
if RUN_ID and (ESML_OUTPUT / RUN_ID / "training-completion.json").exists():
    MODEL_ID = load_json(ESML_OUTPUT / RUN_ID / "training-completion.json")["model_id"]
    MODEL_NAME = load_json(ESML_OUTPUT / RUN_ID / "request.json")["model_name"]
    print("MODEL_ID:", MODEL_ID)
"""),
    ], switches=("PREPARE_ESML", "RUN_ESML_TRAINING"),
        settings=(("RUN_ID", "None  # defaults to the reviewed binding's run_id; use a new id per attempt"),
                  ("COMPONENT_VERSION", '""  # new pinned pipeline component version, e.g. "1"'),
                  ("SELECTION_POLICY", 'None  # e.g. ROOT / "user-config" / "model" / "model-selection.json"'),
                  ("NO_CHAMPION", "False")))


def _esml_batch() -> Section:
    return Section([
        _cell("markdown", """## ESML batch inference (`GOLD_INFERENCE`)

`prepare_inference` renders an inference plan bound to the registered model version and a
new inference run ID; DataOps must place unlabeled gold features with `request_id` at the
printed input path. Publish and invoke a pipeline-component batch endpoint (alternative A)
or submit the same plan as a pipeline job (alternative B). Receipts prevent repeats.
"""),
        _cell("code", """
if PREPARE_ESML_INFERENCE or PUBLISH_AND_INVOKE_ESML or SUBMIT_ESML_INFERENCE:
    if PUBLISH_AND_INVOKE_ESML and SUBMIT_ESML_INFERENCE:
        raise ValueError("Choose one inference route to avoid duplicate charged jobs")
    rollout, config = esml_rollout(cloud=PUBLISH_AND_INVOKE_ESML or SUBMIT_ESML_INFERENCE)
    RUN_ID = RUN_ID or config["scenarios"][scenario["name"]]["run_id"]
    if PREPARE_ESML_INFERENCE:
        if not INFERENCE_RUN_ID:
            raise ValueError("Set INFERENCE_RUN_ID to a new inference run identifier")
        print(json.dumps(rollout.prepare_inference(RUN_ID, inference_date_utc=config["data_date_utc"],
                                                   inference_run_id=INFERENCE_RUN_ID), indent=2))
    if PUBLISH_AND_INVOKE_ESML:
        if not COMPONENT_VERSION:
            raise ValueError("Set COMPONENT_VERSION to a new pinned inference component version")
        print(json.dumps(rollout.deploy_and_invoke(RUN_ID, component_version=COMPONENT_VERSION), indent=2))
    if SUBMIT_ESML_INFERENCE:
        print(json.dumps(rollout.submit_inference(RUN_ID), indent=2, default=str))
"""),
    ], switches=("PREPARE_ESML_INFERENCE", "PUBLISH_AND_INVOKE_ESML", "SUBMIT_ESML_INFERENCE"),
        settings=(("INFERENCE_RUN_ID", '""'),))


def _databricks_job(leaf: UseCase, orchestration: str = "databricks") -> Section:
    task = {"batch": "batch-score", "online": "register-serve", "streaming": "stream-score"}[leaf.pattern]
    wait = "running" if leaf.pattern == "streaming" else "terminated"
    if orchestration == "databricks":
        intro = f"""## Databricks job: `train-evaluate` then `{task}`

`databricks-job render` combines the customer job template (existing cluster, wheel and
notebook locations) with `inference-settings` for this pattern and the shared accelerator
notebooks; the model URI flows between tasks as a task value. Rendering reports unresolved
placeholders; creating or running the job refuses them. Authentication uses your Azure CLI
sign-in (or managed identity in automation), never personal access tokens."""
        if leaf.pattern == "streaming":
            intro += "\nThe stream task keeps running after `RUN_DATABRICKS_JOB` returns; cancel the run to stop it."
        run = f"""
if RUN_DATABRICKS_JOB:
    if not DATABRICKS_JOB_ID:
        raise ValueError("Set DATABRICKS_JOB_ID to the created job")
    # The receipt reuses the idempotency token on retry and refuses a second run while one is unresolved.
    factory("databricks-job", "run", "--job-id", DATABRICKS_JOB_ID, "--host", DATABRICKS_HOST,
            "--auth", "azure-cli", "--wait-for", "{wait}", "--receipt", INFERENCE / "databricks-run.json",
            "--execute")"""
        switches = ("RENDER_DATABRICKS_JOB", "CREATE_DATABRICKS_JOB", "RUN_DATABRICKS_JOB")
    else:
        intro = f"""## Databricks job for Azure ML orchestration

The Azure ML steps run single tasks of an existing Databricks job (`only` task runs), so the
job is rendered with `--orchestration azureml`: `{task}` reads the model URI from a job
parameter that the second Azure ML step supplies. Create it once, then record its job ID in
`user-config/databricks/azureml-step.local.json`."""
        run = ""
        switches = ("RENDER_DATABRICKS_JOB", "CREATE_DATABRICKS_JOB")
    return Section([
        _cell("markdown", intro),
        _cell("code", f"""
DATABRICKS_TEMPLATE = ROOT / "user-config" / "databricks" / "job-template.json"
DATABRICKS_SETTINGS = ROOT / "user-config" / "databricks" / "inference-settings.local.json"
DATABRICKS_JOB = INFERENCE / "databricks-job.json"
if RENDER_DATABRICKS_JOB:
    factory("databricks-job", "render", "--scenario", SCENARIO, "--pattern", PATTERN,
            "--template", DATABRICKS_TEMPLATE, "--settings", DATABRICKS_SETTINGS,
            "--scenario-path", DATABRICKS_SCENARIO_PATH, "--orchestration", "{orchestration}",
            "--output", DATABRICKS_JOB)
if CREATE_DATABRICKS_JOB:
    factory("databricks-job", "create", "--job", DATABRICKS_JOB, "--host", DATABRICKS_HOST,
            "--auth", "azure-cli", "--execute"){run}
"""),
    ], switches=switches,
        settings=(("DATABRICKS_HOST", '""  # https://adb-<workspace-id>.<n>.azuredatabricks.net'),
                  ("DATABRICKS_SCENARIO_PATH", json.dumps("/Workspace/Shared/ml-model-factory/user-config/model/scenarios/")
                   + ' + scenario["name"] + ".json"'),
                  ("DATABRICKS_JOB_ID", '""')) if orchestration == "databricks" else
        (("DATABRICKS_HOST", '""  # https://adb-<workspace-id>.<n>.azuredatabricks.net'),
         ("DATABRICKS_SCENARIO_PATH", json.dumps("/Workspace/Shared/ml-model-factory/user-config/model/scenarios/")
          + ' + scenario["name"] + ".json"')))


def _databricks_pipeline(leaf: UseCase) -> Section:
    task = {"batch": "batch-score", "online": "register-serve", "streaming": "stream-score"}[leaf.pattern]
    return Section([
        _cell("markdown", f"""## Azure ML pipeline with Databricks steps

`databricks-pipeline render` writes an Azure ML v2 pipeline whose first command step runs only the
existing Databricks job's `train-evaluate` task and whose second step, bound to the first step's
output, runs only `{task}` with the returned model URI. Steps authenticate with the compute's
managed identity and have explicit timeouts. Configure the job ID, task keys and workspace in
`user-config/databricks/azureml-step.local.json` (see the example file).
"""),
        _cell("code", """
DATABRICKS_STEP_CONFIG = ROOT / "user-config" / "databricks" / "azureml-step.local.json"
if RENDER_DATABRICKS_PIPELINE:
    factory("databricks-pipeline", "render", "--scenario", SCENARIO, "--runtime", EFFECTIVE_RUNTIME,
            "--pattern", PATTERN, "--databricks", DATABRICKS_STEP_CONFIG, "--output", RENDERED)
JOB_PATH = RENDERED / "pipeline.yml"
"""),
    ], switches=("RENDER_DATABRICKS_PIPELINE",))


def _closing(leaf: UseCase) -> Section:
    cleanup = {
        "batch": "Batch compute scales back to zero; storage of inputs and predictions remains.",
        "online": "Delete online endpoints (or Databricks serving endpoints) when the test is over.",
        "streaming": "Stop schedules/streaming queries before deleting checkpoints; checkpoints define replay.",
    }[leaf.pattern]
    return Section([_cell("markdown", f"""## Monitoring and clean-up

Join predictions with observed labels by `request_id` only after outcomes are known, then use
`python -m ml_model_factory monitor` with explicit reference/current windows (see the
model-factory guide). Predictions are never labels. {cleanup}
""")])


def sections(leaf: UseCase) -> list[Section]:
    engine, vision = leaf.technology.engine, leaf.family == "vision"
    result = []
    if engine == "local":
        result += [_data(), _local_training()] + ([_vision_note(leaf)] if vision else [])
        result += [_requests(leaf), _local_serving(leaf), _lake(), _render(), _submit(), _register(),
                   _azure_serving(leaf)]
    elif engine == "azureml" or (engine == "pipeline" and not leaf.esml):
        result += [_data()] + ([_vision_note(leaf)] if vision else [])
        result += [_lake(), _render(), _submit(), _register(), _requests(leaf), _azure_serving(leaf)]
    elif engine == "pipeline":
        result += [_data(), _esml_training(leaf), _requests(leaf)]
        result += [_esml_batch()] if leaf.pattern == "batch" else [_azure_serving(leaf)]
    elif engine == "databricks":
        result += [_data(), _requests(leaf), _databricks_job(leaf)]
    else:
        result += [_databricks_job(leaf, "azureml"), _databricks_pipeline(leaf), _submit()]
    return result + [_closing(leaf)]


def render_example(leaf: UseCase, scenario: dict, output_dir: Path,
                   runtime_path: str = "user-config/runtime.local.json") -> Path:
    from .config import validate_scenario, write_json

    validate_scenario(scenario)
    if not leaf.supported:
        raise ValueError(f"{leaf.folder.as_posix()} is not supported: {leaf.reason}")
    if scenario["task"] != leaf.task:
        raise ValueError("Scenario task does not match the use-case task folder")
    parts = sections(leaf)
    switches = list(dict.fromkeys(name for part in parts for name in part.switches))
    settings = list(dict.fromkeys(item for part in parts for item in part.settings))
    cells = _header(leaf, scenario).cells + [_setup(leaf, scenario, runtime_path, switches, settings)]
    for part in parts:
        cells += part.cells
    notebook = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "cells": [cell | {"id": f"factory-{index:02d}"} for index, cell in enumerate(cells)],
    }
    output = Path(output_dir) / leaf.notebook_name(scenario["name"])
    write_json(output, notebook)
    return output


def batch_notebook_leaf(task: str, mode: str) -> UseCase:
    technology = "notebook" if mode == "custom" else "azure-automl/notebook"
    return find("batch", TASK_FOLDER_BY_TASK[task], technology)


def readme_block(leaf: UseCase, scenarios: list[dict]) -> str:
    lines = [GENERATED_START, "", "## Implementation", ""]
    if leaf.supported:
        examples = ", ".join(f"[{name}]({name})" for name in (leaf.notebook_name(item["name"]) for item in scenarios))
        lines += [f"**Examples:** {examples or 'no configured scenario for this task'}", "",
                  f"**Training:** {leaf.training}", "", f"**Serving:** {leaf.serving}", "",
                  "**Prerequisites**", "", _bullets(leaf.prerequisites), "", "**Limitations**", "",
                  _bullets(leaf.limitations), ""]
    else:
        lines += [f"**Not supported:** {leaf.reason}", ""]
    lines += ["Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, "
              "not this block.", "", GENERATED_END]
    return "\n".join(lines)


def _replace_status(text: str, status: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("**Status:**"):
            lines[index] = f"**Status:** {status}"
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise ValueError("README is missing its **Status:** introduction line")


def render_readme(text: str, leaf: UseCase, scenarios: list[dict]) -> str:
    text = _replace_status(text, leaf.status)
    block = readme_block(leaf, scenarios)
    if GENERATED_START in text:
        before, rest = text.split(GENERATED_START, 1)
        after = rest.split(GENERATED_END, 1)[1]
        return before + block + after
    lines = text.splitlines()
    anchor = next((index for index, line in enumerate(lines) if line.startswith("[Scenario configuration]")), None)
    if anchor is None:
        raise ValueError("README is missing its navigation line")
    return "\n".join(lines[:anchor + 1] + ["", block] + lines[anchor + 1:]) + "\n"


def _parent_status(prefix: tuple[str, ...]) -> str:
    leaves = [leaf for leaf in catalog() if (leaf.pattern, *leaf.task_folder.split("/"),
                                               *leaf.technology.key.split("/"))[:len(prefix)] == prefix]
    supported = sum(leaf.supported for leaf in leaves)
    text = (f"Executable notebook templates exist for {supported} of {len(leaves)} leaf combinations below; "
            "each leaf README lists its route, prerequisites and limitations.")
    if supported != len(leaves):
        text += " Unsupported leaves explain why and name the supported alternative."
    return text


def render_all(source: Path | None = None, *, write: bool = False) -> dict:
    """Regenerate (write=True) or verify every generated notebook and README status block."""
    from .config import load_json
    from .layout import source_root

    root = source_root(source)
    scenarios = scenarios_by_task(root / "user-config" / "model" / "scenarios")
    expected: dict[Path, bytes] = {}
    import tempfile

    with tempfile.TemporaryDirectory(prefix="usecase-examples-") as temporary:
        staging = Path(temporary)
        for leaf in catalog():
            folder = root / Path(*leaf.folder.parts)
            readme = folder / "readme.md"
            expected[readme] = render_readme(readme.read_text(encoding="utf-8"), leaf,
                                             scenarios[leaf.task]).encode("utf-8")
            if not leaf.supported:
                continue
            for scenario in scenarios[leaf.task]:
                rendered = render_example(leaf, scenario, staging / leaf.folder.as_posix())
                expected[folder / rendered.name] = rendered.read_bytes()
    parents = set()
    for leaf in catalog():
        parts = leaf.folder.parts[1:]
        for depth in range(1, len(parts)):
            parents.add(parts[:depth])
    for prefix in sorted(parents):
        readme = root / "usecase-type" / Path(*prefix) / "readme.md"
        if readme.is_file():
            expected[readme] = _replace_status(readme.read_text(encoding="utf-8"), _parent_status(prefix)).encode("utf-8")
    stale = sorted(str(path.relative_to(root).as_posix()) for path, content in expected.items()
                   if not path.is_file() or path.read_bytes() != content)
    unexpected = []
    for leaf in catalog():
        folder = root / Path(*leaf.folder.parts)
        for notebook in folder.glob("*.ipynb"):
            if notebook not in expected:
                unexpected.append(notebook.relative_to(root).as_posix())
    if write:
        for path in stale:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected[target])
    return {"checked": len(expected), "stale": [] if write else stale, "written": stale if write else [],
            "unexpected_notebooks": sorted(unexpected),
            "notebooks": sum(1 for path in expected if path.suffix == ".ipynb")}
