"""Offline cross-surface contracts, not Azure training/deployment end-to-end tests.

Only service I/O is simulated: rendering, CLI validation, SDK YAML loading,
registration gates, and deployment orchestration execute their real code.
Training/evaluation commands inside YAML are never executed, including custom
training. Downloaded quality reports are service fixtures: their passing gates
prove the registration consumer's behavior, not measured model quality.
ADF Copy and ADO/GitHub runners are not executed; no cloud submission is allowed.
Set ML_FACTORY_MATRIX_COVERAGE to a project-local JSON path to retain evidence
for assertions that completed; absent rows must not be interpreted as passes.
"""

from contextlib import contextmanager
from copy import deepcopy
import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from azure.ai.ml import load_job
import pytest
import yaml

from ml_model_factory import azureml, serving
from ml_model_factory.config import load_json, validate_scenario
from ml_model_factory.lake import LakeLayout
from ml_model_factory.tags import TAG_KEYS


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
EXTERNAL = REPO / "copy_my_subfolders_to_my_grandparent"
ADF = EXTERNAL / "dataops" / "azure-datafactory"
MLOPS = EXTERNAL / "mlops" / "03_mlops_2026-09"
MODES = ("custom", "automl")
SCENARIOS = (
    "titanic", "diabetes", "churn", "insurance-regression",
    "air-passengers", "delhi-weather", "orangejuice", "image-multiclass",
    "image-multilabel", "image-object-detection", "image-instance-segmentation",
)
REPRESENTATIVES = (
    "titanic", "insurance-regression", "air-passengers", "image-multiclass",
    "image-multilabel", "image-object-detection", "image-instance-segmentation",
)
SERVING_PATTERNS = ("batch", "online", "streaming")
AZ = r"C:\matrix-service-double\az.cmd"


def external_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci = external_module("matrix_ci", MLOPS / "scripts" / "ci.py")
adf = external_module("matrix_adf", ADF / "prepare_run.py")
sdk_entry = external_module("matrix_sdk", ROOT / "scripts" / "azureml_sdk.py")
cli_entry = external_module("matrix_cli", ROOT / "scripts" / "azureml_cli.py")


def scenario_named(name):
    return load_json(ROOT / "scenarios" / f"{name}.json")


def runtime_for(name, pattern="batch"):
    return {
        "aifactory": "fixture-factory", "project": "001", "environment_name": "dev",
        "subscription_id": "10000000-0000-4000-8000-000000000001",
        "tenant_id": "20000000-0000-4000-8000-000000000002",
        "resource_group": "matrix-rg", "workspace_name": "matrix-workspace",
        "compute": "matrix-cpu", "gpu_compute": "matrix-gpu",
        "datastore": "matrix_blob", "environment": "azureml:matrix-environment:7",
        "input_data": "azureml://datastores/matrix_blob/paths/source/input.csv",
        "serving": {"instance_count": 1, "batch_instance_count": 1},
        "lake": {
            "project": "001", "environment": "dev", "use_case": name,
            "dataset": "reviewed-source", "data_version": "source-v3",
            "snapshot_id": "reviewed-snapshot-v1", "run_id": "render-" + uuid4().hex,
            "model_version": "17", "serving": pattern,
            "pipeline_id": "prediction-events", "pipeline_version": "v1",
            "storage": {
                "account_url": "https://matrixstorage.blob.core.windows.net",
                "container": "matrix-data", "datastore": "matrix_blob",
            },
        },
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def generate_coverage_artifact(destination, evidence):
    """Persist only observed assertion evidence, without expanding a Cartesian grid."""
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT):
        raise ValueError("Coverage artifact must stay underneath the factory project")
    write_json(destination, {
        "schema": "ml-factory-orchestration-matrix/v1",
        "execution_level": "local-contract-and-service-io-simulation",
        "live_azure": False,
        "lifecycle_boundaries": {
            "ingest": "Real ADF parameter binding; source Copy and Kaggle download not executed.",
            "prepare_train_evaluate": (
                "Real rendering and SDK YAML loading; no custom/AutoML fit, preparation job, "
                "evaluation job, or model-quality measurement executed."
            ),
            "register": (
                "Real registration gate consumer; job status, downloaded quality/lineage reports, "
                "and model registry service writes simulated."
            ),
            "deploy": "Real SDK loaders and orchestration; endpoint/deployment service calls simulated.",
            "serving": "Batch/online/streaming metadata validated; no scoring or streaming query executed.",
            "ci": (
                "Real local CLI validate/render subprocesses; Azure CLI service responses simulated; "
                "ADO/GitHub YAML inspected, not executed; no live authentication/approval verified."
            ),
        },
        "limitations": [
            "No AutoML fitting, Azure compute, endpoint scoring, ADF Copy, or CI runner executed.",
            "SDK load_job validates local YAML, not remote asset/compute availability.",
            "Workflow wrappers are inspected as YAML, not executed by ADO or GitHub.",
            "SUPPORT is operation-specific; rendered metadata does not imply deployability.",
            "Only completed assertion rows are recorded; this is not a full test-run verdict.",
        ],
        "evidence": sorted(evidence, key=lambda row: (row["test"], row["operation"])),
    })


@pytest.fixture(scope="module")
def workspace():
    work = ROOT / ".orchestration-matrix-artifacts" / uuid4().hex
    work.mkdir(parents=True)
    yield work
    shutil.rmtree(work)
    try:
        work.parent.rmdir()
    except OSError:
        pass


@pytest.fixture(scope="module")
def evidence_rows():
    rows = []
    yield rows
    destination = os.environ.get("ML_FACTORY_MATRIX_COVERAGE")
    if destination:
        generate_coverage_artifact(destination, rows)


@pytest.fixture
def evidence(request, evidence_rows):
    def record(operation, expected, **dimensions):
        assert expected in {"SUPPORTED", "BLOCKED"}
        evidence_rows.append({
            "test": request.node.nodeid, "operation": operation,
            "expected": expected, "observed": expected,
            "cloud_service_executed": False,
            "assertions_completed": True, **dimensions,
        })
    return record


@pytest.fixture
def work(workspace):
    path = workspace / uuid4().hex
    path.mkdir()
    return path


@pytest.fixture(scope="module")
def bundle_factory(workspace):
    bundles = {}

    def build(name, mode):
        if (name, mode) not in bundles:
            scenario, runtime = scenario_named(name), runtime_for(name)
            original = deepcopy((scenario, runtime))
            paths = azureml.render(
                validate_scenario(scenario), runtime,
                workspace / f"{name}-{mode}", ROOT, mode,
            )
            assert (scenario, runtime) == original
            bundles[name, mode] = SimpleNamespace(
                scenario=scenario, runtime=runtime, paths=paths,
                root=Path(paths["manifest"]).parent,
                manifest=load_json(Path(paths["manifest"])),
            )
        return bundles[name, mode]

    return build


def mock_service_client(monkeypatch):
    """Retain real _client validation and scope selection; replace remote adapters."""
    client = MagicMock(name="azure_service_io")
    constructor = MagicMock(return_value=client)
    credential = MagicMock(name="tenant_scoped_cli_credential")
    monkeypatch.setattr("azure.ai.ml.MLClient", constructor)
    monkeypatch.setattr("azure.identity.AzureCliCredential", credential)
    client.online_endpoints.get.side_effect = lambda name: SimpleNamespace(name=name, traffic={})
    client.batch_endpoints.get.side_effect = lambda name: SimpleNamespace(
        name=name, defaults=SimpleNamespace(deployment_name=None),
    )
    return client, constructor, credential


def assert_scope(command, runtime):
    for flag, field in (
        ("--subscription", "subscription_id"),
        ("--resource-group", "resource_group"), ("--workspace-name", "workspace_name"),
    ):
        assert command.count(flag) == 1
        assert command[command.index(flag) + 1] == runtime[field]


def assert_no_deployment(client):
    for name in ("online_endpoints", "online_deployments", "batch_endpoints", "batch_deployments"):
        getattr(client, name).begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("name", SCENARIOS)
def test_catalog_selection_gates_are_distinct_from_renderability(name, evidence):
    assert set(SCENARIOS) == {path.stem for path in (ROOT / "scenarios").glob("*.json")}
    assert {scenario_named(item)["task"] for item in REPRESENTATIVES} == set(azureml.TASK_SCHEMAS)
    scenario = scenario_named(name)
    validate_scenario(scenario)
    blocked = name in {"churn", "orangejuice", "image-multiclass"}
    if blocked:
        with pytest.raises(ValueError, match="license-review|required-selection"):
            validate_scenario(scenario, require_dataset=True)
    else:
        validate_scenario(scenario, require_dataset=True)
    evidence("dataset-selection-validation", "BLOCKED" if blocked else "SUPPORTED",
             scenario=name, task=scenario["task"], level="configuration-only-no-ingestion")


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("mode", MODES)
def test_real_render_sdk_and_cli_entrypoints_share_yaml_and_scope(
    name, mode, bundle_factory, monkeypatch, evidence,
):
    bundle = bundle_factory(name, mode)
    paths, scenario, runtime = bundle.paths, bundle.scenario, bundle.runtime
    image = scenario["task"].startswith("image_")
    train_only = image and mode == "automl"
    expected_keys = {"job"} if train_only else {"prepare_job", "job", "pipeline"}
    loaded = {key: load_job(source=paths[key]) for key in expected_keys}
    assert loaded["job"].type == ("automl" if mode == "automl" else "command")
    assert ("pipeline" in paths) is not train_only
    assert ("prepare_job" in paths) is not train_only
    if mode == "automl":
        assert loaded["job"].task_type.name.lower() == scenario["task"]
    if not train_only:
        pipeline = yaml.safe_load(Path(paths["pipeline"]).read_text(encoding="utf-8"))
        assert set(pipeline["jobs"]) == {"prepare", "train", "evaluate"}
        assert pipeline["settings"]["continue_on_step_failure"] is False
        model_port = "best_model" if mode == "automl" else "model"
        assert pipeline["jobs"]["evaluate"]["inputs"]["model"] == (
            "${{parent.jobs.train.outputs." + model_port + "}}"
        )
        assert pipeline["inputs"]["raw"]["type"] == ("uri_folder" if image else "uri_file")
        assert f"--mode {mode}" in pipeline["jobs"]["evaluate"]["command"]
    else:
        assert "training-only" in " ".join(bundle.manifest["limitations"])

    client, constructor, credential = mock_service_client(monkeypatch)
    cloud_cli = MagicMock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(cli_entry.shutil, "which", lambda executable: AZ)
    monkeypatch.setattr(cli_entry.subprocess, "run", cloud_cli)
    runtime_path = paths["runtime"]
    unresolved = Path(paths["job"])
    monkeypatch.setattr(sys, "argv", [
        "azureml_sdk.py", "--runtime", runtime_path, "submit", "--job", str(unresolved),
    ])
    with pytest.raises(ValueError, match="placeholders"):
        sdk_entry.main()
    monkeypatch.setattr(sys, "argv", [
        "azureml_cli.py", "--runtime", runtime_path, "--job", str(unresolved),
    ])
    with pytest.raises(ValueError, match="placeholders"):
        cli_entry.main()
    constructor.assert_not_called()
    cloud_cli.assert_not_called()

    if train_only:
        resolved = yaml.safe_load(unresolved.read_text(encoding="utf-8"))
        for split in ("training", "validation"):
            resolved[f"{split}_data"]["path"] = f"azureml:reviewed-images-{split}:3"
        submit_path = bundle.root / "resolved-training.yml"
        submit_path.write_text(yaml.safe_dump(resolved), encoding="utf-8")
    else:
        submit_path = Path(paths["pipeline"])
    original_yaml = submit_path.read_bytes()
    client.jobs.create_or_update.return_value = SimpleNamespace(name="job-" + uuid4().hex)
    monkeypatch.setattr(sys, "argv", [
        "azureml_sdk.py", "--runtime", runtime_path, "submit", "--job", str(submit_path),
    ])
    sdk_entry.main()
    submitted = client.jobs.create_or_update.call_args.args[0]
    assert submitted.type == ("automl" if train_only else "pipeline")
    credential.assert_called_once_with(tenant_id=runtime["tenant_id"])
    constructor.assert_called_once_with(
        credential.return_value, runtime["subscription_id"],
        runtime["resource_group"], runtime["workspace_name"],
    )
    monkeypatch.setattr(sys, "argv", [
        "azureml_cli.py", "--runtime", runtime_path, "--job", str(submit_path),
    ])
    cli_entry.main()
    command = cloud_cli.call_args.args[0]
    assert command[:4] == [AZ, "ml", "job", "create"]
    assert Path(command[command.index("--file") + 1]) == submit_path.resolve()
    assert_scope(command, runtime)
    assert cloud_cli.call_args.kwargs == {"check": True}
    assert submit_path.read_bytes() == original_yaml
    assert load_json(Path(runtime_path))["tenant_id"] == runtime["tenant_id"]
    evidence("sdkv2-and-cliv2-submit-same-yaml", "SUPPORTED", scenario=name,
             task=scenario["task"], mode=mode,
             scope="standalone-training-only" if train_only else "gated-pipeline",
             level="real-sdk-load-and-entrypoints-mocked-cloud-submission")
    evidence("unresolved-standalone-submission", "BLOCKED", scenario=name, mode=mode)


class CIService:
    """Fake job status/artifact transfer; never fabricate rendered factory files."""

    def __init__(self, monkeypatch, work, *, status="Completed", report="passed"):
        self.work, self.status, self.report = work, status, report
        self.client, self.constructor, self.credential = mock_service_client(monkeypatch)
        self.commands, self.local_commands, self.submitted = [], [], []
        self.registered = []
        self.client.jobs.get.side_effect = lambda name: self.job
        self.client.jobs.download.side_effect = self.download
        self.client.models.create_or_update.side_effect = self.register
        self.native_run = subprocess.run
        monkeypatch.setattr(ci.shutil, "which", lambda name: AZ)
        monkeypatch.setattr(ci.subprocess, "run", self.run)
        monkeypatch.setattr(azureml.tempfile, "TemporaryDirectory", self.download_directory)

    @contextmanager
    def download_directory(self, **kwargs):
        directory = self.work / ("download-" + uuid4().hex)
        directory.mkdir()
        try:
            yield str(directory)
        finally:
            shutil.rmtree(directory)

    def run(self, command, **kwargs):
        if command[:3] == [sys.executable, "-m", "ml_model_factory"]:
            assert command[3] in {"validate", "render"}
            self.local_commands.append(command)
            return self.native_run(command, cwd=ROOT, **kwargs)
        assert command[0] == AZ, f"Unexpected subprocess forbidden in offline matrix: {command}"
        self.commands.append(command)
        if command[1:3] == ["extension", "show"]:
            value = ci.ML_EXTENSION_VERSION
        elif command[1:4] == ["ml", "job", "create"]:
            path = Path(command[command.index("-f") + 1])
            assert path.name == "pipeline.yml"
            job = load_job(source=str(path))
            assert job.type == "pipeline"
            assert set(job.jobs) == {"prepare", "train", "evaluate"}
            self.submitted.append(path)
            self.name = "ci-job-" + uuid4().hex
            self.job = SimpleNamespace(
                type=job.type, status=self.status, tags=job.tags,
                jobs=job.jobs, outputs=job.outputs,
            )
            value = self.name
        elif command[1:4] == ["ml", "job", "show"]:
            assert command[command.index("--name") + 1] == self.name
            value = json.dumps({"status": self.status})
        else:
            raise AssertionError(f"Unexpected Azure operation: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=value, stderr="")

    def download(self, *, name, download_path, output_name):
        assert name == self.name
        assert output_name == "report"
        if self.report == "missing":
            return
        passed = {"passed": True} if self.report == "passed" else (
            {} if self.report == "unknown" else {"passed": self.report}
        )
        root = Path(download_path) / "named-report"
        write_json(root / "quality-gate.json", passed)
        lake = {key: self.job.tags[f"factory_lake_{key}"] for key in azureml.LAKE_LINEAGE_FIELDS}
        write_json(root / "lineage.json", {
            "model_output": "model", "scenario": self.job.tags["factory_scenario"],
            "task": self.job.tags["factory_task"], "lake": {"config": lake},
            "mode": self.job.tags["factory_mode"],
            "model_tags": {key: self.job.tags[key] for key in TAG_KEYS if key in self.job.tags},
        })

    def register(self, model):
        self.registered.append(model)
        return SimpleNamespace(id=f"/models/{model.name}/versions/17")


def ci_arguments(work, name, mode):
    runtime = runtime_for(name)
    path = work / "runtime.json"
    write_json(path, runtime)
    return SimpleNamespace(
        scenario=str(ROOT / "scenarios" / f"{name}.json"), runtime=str(path),
        output=str(work / "ci"), mode=mode, lake_run_id=None,
        ml_extension_version=ci.ML_EXTENSION_VERSION, timeout_seconds=30, poll_seconds=1,
    )


@pytest.mark.parametrize("name", REPRESENTATIVES)
@pytest.mark.parametrize("mode", MODES)
def test_ci_uses_real_cli_render_poll_and_registration_gates(
    name, mode, work, monkeypatch, evidence,
):
    args = ci_arguments(work, name, mode)
    original_runtime = Path(args.runtime).read_bytes()
    service = CIService(monkeypatch, work)
    receipt = Path(args.output) / "registered-model.json"
    write_json(receipt, {"id": "stale-from-earlier-attempt"})
    train_only = scenario_named(name)["task"].startswith("image_") and mode == "automl"
    if train_only:
        with pytest.raises(RuntimeError, match="pipeline.yml"):
            ci.train(args)
        assert not service.submitted
        service.client.models.create_or_update.assert_not_called()
        assert not receipt.exists()
    else:
        ci.train(args)
        assert len(service.registered) == 1
        model = service.registered[0]
        assert model.path == f"azureml://jobs/{service.name}/outputs/model/paths/"
        assert model.tags["quality_gate"] == "passed"
        assert model.tags["factory_mode"] == mode
        assert model.tags["factory_scenario"] == name
        assert load_json(receipt) == {
            "id": f"/models/{model.name}/versions/17", "job": service.name, "outcome": "Succeeded",
        }
        for command in service.commands:
            if command[1] == "ml":
                assert_scope(command, load_json(Path(args.runtime)))
    assert [command[3] for command in service.local_commands] == ["validate", "render"]
    validate_runtime_path, render_runtime_path = [
        Path(command[command.index("--runtime") + 1]) for command in service.local_commands
    ]
    assert validate_runtime_path == render_runtime_path
    effective = load_json(render_runtime_path)
    assert effective["lake"]["run_id"] != load_json(Path(args.runtime))["lake"]["run_id"]
    UUID(effective["lake"]["run_id"].removeprefix("ci-"))
    assert Path(args.runtime).read_bytes() == original_runtime
    assert_no_deployment(service.client)
    evidence("ci-train-through-real-cli-and-registration", "BLOCKED" if train_only else "SUPPORTED",
             scenario=name, task=scenario_named(name)["task"], mode=mode,
             level="service-status-and-report-download-simulation")


@pytest.mark.parametrize("mode", MODES)
def test_ci_rerun_changes_execution_not_source_snapshot_or_stream_checkpoint(
    mode, work, monkeypatch, evidence,
):
    args = ci_arguments(work, "titanic", mode)
    original = load_json(Path(args.runtime))
    original["lake"]["serving"] = "streaming"
    write_json(Path(args.runtime), original)
    service = CIService(monkeypatch, work)
    ci.train(args)
    first_model = service.registered[0]
    first = load_json(service.submitted[0].parent / "lake-manifest.json")
    ci.train(args)
    second = load_json(service.submitted[1].parent / "lake-manifest.json")
    assert service.submitted[0] != service.submitted[1]
    assert first["run_id"] != second["run_id"] != original["lake"]["run_id"]
    for key in ("landing", "silver", "training_snapshot", "training_gold", "checkpoint"):
        assert first["paths"][key] == second["paths"][key]
    for key in ("training_run", "training_model", "training_evaluation", "input", "output"):
        assert first["paths"][key] != second["paths"][key]
    assert first_model.path != service.registered[1].path
    assert load_json(Path(args.runtime)) == original
    evidence("ci-fresh-execution-stable-snapshot-and-checkpoint", "SUPPORTED",
             scenario="titanic", mode=mode, serving="streaming")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("status,report", [
    ("Failed", "passed"), ("UnexpectedStatus", "passed"), (None, "passed"),
    ("Completed", False), ("Completed", "error"), ("Completed", "unknown"),
    ("Completed", "missing"),
], ids=["failed-job", "unknown-job", "missing-job-status", "failed-gate",
        "error-gate", "missing-passed-field", "missing-report"])
def test_ci_failure_never_registers_deploys_or_keeps_stale_receipt(
    mode, status, report, work, monkeypatch, evidence,
):
    args = ci_arguments(work, "titanic", mode)
    service = CIService(monkeypatch, work, status=status, report=report)
    receipt = Path(args.output) / "registered-model.json"
    write_json(receipt, {"id": "stale"})
    with pytest.raises((ValueError, RuntimeError)):
        ci.train(args)
    assert [command[3] for command in service.local_commands] == ["validate", "render"]
    assert len(service.submitted) == 1
    service.client.models.create_or_update.assert_not_called()
    assert_no_deployment(service.client)
    assert not receipt.exists()
    evidence("ci-promotion-gate", "BLOCKED", scenario="titanic", mode=mode,
             job_status=status, quality_report=report)


@pytest.mark.parametrize("name", REPRESENTATIVES[3:])
def test_automl_vision_standalone_cannot_register_even_when_training_completed(
    name, bundle_factory, monkeypatch, evidence,
):
    bundle = bundle_factory(name, "automl")
    loaded = load_job(source=bundle.paths["job"])
    client, _, _ = mock_service_client(monkeypatch)
    client.jobs.get.return_value = SimpleNamespace(
        type=loaded.type, status="Completed", tags=loaded.tags,
        jobs=None, outputs=loaded.outputs,
    )
    with pytest.raises(ValueError, match="successful.*factory pipeline"):
        azureml.register("completed-vision-" + uuid4().hex, bundle.runtime, bundle.manifest["model_name"])
    client.jobs.download.assert_not_called()
    client.models.create_or_update.assert_not_called()
    assert_no_deployment(client)
    evidence("standalone-automl-vision-registration", "BLOCKED", scenario=name,
             task=bundle.scenario["task"], mode="automl", job_status="Completed")


def registered_model(bundle, **tag_overrides):
    tags = {
        **bundle.manifest["model_tags"],
        "quality_gate": "passed", "pipeline_job": "reviewed-job-" + uuid4().hex,
        "factory_scenario": bundle.scenario["name"], "factory_mode": bundle.manifest["mode"],
    }
    tags.update(tag_overrides)
    return SimpleNamespace(
        name=bundle.manifest["model_name"], type="mlflow_model", tags=tags,
        id=f"/models/{bundle.manifest['model_name']}/versions/17",
    )


@pytest.mark.parametrize("name,mode,kind,approved,supported", [
    ("titanic", "custom", "online", True, True),
    ("insurance-regression", "automl", "batch", True, True),
    ("air-passengers", "automl", "online", True, False),
    ("image-multiclass", "automl", "online", True, False),
    ("image-multiclass", "custom", "batch", True, False),
    ("titanic", "custom", "online", False, False),
])
def test_ci_deployment_real_cli_preserves_support_and_approval_boundaries(
    name, mode, kind, approved, supported, work, bundle_factory, monkeypatch, evidence,
):
    args = ci_arguments(work, name, mode)
    args.approval_environment = "protected-matrix-environment" if approved else ""
    args.kind = kind
    model = registered_model(bundle_factory(name, mode))
    args.model_id = f"azureml:{model.name}:17"
    service = CIService(monkeypatch, work)
    service.client.models.get.return_value = model
    original = Path(args.runtime).read_bytes()
    if supported:
        ci.deploy(args)
        getattr(service.client, f"{kind}_deployments").begin_create_or_update.assert_called_once()
        assert getattr(service.client, f"{kind}_endpoints").begin_create_or_update.call_count == 2
    else:
        with pytest.raises(ValueError, match="not supported|approval environment"):
            ci.deploy(args)
        assert_no_deployment(service.client)
    assert [command[3] for command in service.local_commands] == (
        ["validate", "render"] if approved else []
    )
    if approved:
        service.client.models.get.assert_called_once_with(name=model.name, version="17")
        service.credential.assert_called_once_with(
            tenant_id=load_json(Path(args.runtime))["tenant_id"],
        )
    else:
        service.constructor.assert_not_called()
    assert not service.commands
    assert Path(args.runtime).read_bytes() == original
    service.client.models.create_or_update.assert_not_called()
    evidence("ci-explicit-deployment", "SUPPORTED" if supported else "BLOCKED",
             scenario=name, mode=mode, serving=kind, approval_name_present=approved,
             level="real-cli-validation-render-and-deploy-mocked-cloud-io")


@pytest.mark.parametrize("field", ("subscription_id", "tenant_id"))
def test_ci_missing_explicit_identity_cannot_submit_or_register(field, work, monkeypatch, evidence):
    args = ci_arguments(work, "titanic", "custom")
    runtime = load_json(Path(args.runtime))
    runtime.pop(field)
    write_json(Path(args.runtime), runtime)
    service = CIService(monkeypatch, work)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        ci.train(args)
    assert not service.submitted
    service.client.models.create_or_update.assert_not_called()
    assert_no_deployment(service.client)
    evidence("ci-explicit-runtime-identity", "BLOCKED", missing_field=field)


@pytest.mark.parametrize("name", REPRESENTATIVES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", ("online", "batch"))
def test_deployment_support_matrix_executes_real_sdk_loaders_and_orchestrator(
    name, mode, kind, bundle_factory, monkeypatch, evidence,
):
    bundle = bundle_factory(name, mode)
    image = bundle.scenario["task"].startswith("image_")
    blocked = (
        (image and (mode == "automl" or kind == "batch"))
        or (bundle.scenario["task"] == "forecasting" and mode == "automl")
    )
    client, _, _ = mock_service_client(monkeypatch)
    model = registered_model(bundle)
    client.models.get.return_value = model
    identifier = f"azureml:{model.name}:17"
    original = Path(bundle.paths["runtime"]).read_bytes()
    if blocked:
        with pytest.raises(ValueError, match="not supported"):
            serving.deploy(bundle.runtime, bundle.root, identifier, kind)
        assert not (bundle.root / f"{kind}-deployment.yml").exists()
        assert_no_deployment(client)
    else:
        endpoint = serving.deploy(bundle.runtime, bundle.root, identifier, kind)
        endpoint_api = getattr(client, f"{kind}_endpoints")
        deployment_api = getattr(client, f"{kind}_deployments")
        assert endpoint == endpoint_api.get.call_args.args[0]
        assert endpoint_api.begin_create_or_update.call_count == 2
        deployment_api.begin_create_or_update.assert_called_once()
        deployment = deployment_api.begin_create_or_update.call_args.args[0]
        assert deployment.model == model.id
        promoted = endpoint_api.begin_create_or_update.call_args.args[0]
        if kind == "online":
            assert promoted.traffic == {deployment.name: 100}
        else:
            assert promoted.defaults.deployment_name == deployment.name
        events = [call[0] for call in client.mock_calls if "begin_create_or_update" in call[0]]
        assert events == [
            f"{kind}_endpoints.begin_create_or_update",
            f"{kind}_endpoints.begin_create_or_update().result",
            f"{kind}_deployments.begin_create_or_update",
            f"{kind}_deployments.begin_create_or_update().result",
            f"{kind}_endpoints.begin_create_or_update",
            f"{kind}_endpoints.begin_create_or_update().result",
        ]
    client.models.get.assert_called_once_with(name=model.name, version="17")
    assert Path(bundle.paths["runtime"]).read_bytes() == original
    evidence("deployment", "BLOCKED" if blocked else "SUPPORTED",
             scenario=name, task=bundle.scenario["task"], mode=mode, serving=kind,
             level="real-sdk-loaders-and-orchestrator-mocked-endpoint-io")


@pytest.mark.parametrize("kind", ("online", "batch"))
@pytest.mark.parametrize("gate", [None, "unknown", "error", "failed"])
def test_deployment_unknown_error_or_missing_gate_cannot_write_endpoints(
    kind, gate, bundle_factory, monkeypatch, evidence,
):
    bundle = bundle_factory("titanic", "custom")
    client, _, _ = mock_service_client(monkeypatch)
    model = registered_model(bundle, quality_gate=gate)
    if gate is None:
        model.tags.pop("quality_gate")
    client.models.get.return_value = model
    with pytest.raises(ValueError, match="passing factory pipeline"):
        serving.deploy(bundle.runtime, bundle.root, f"azureml:{model.name}:17", kind)
    assert_no_deployment(client)
    evidence("deployment-model-quality-gate", "BLOCKED", scenario="titanic",
             mode="custom", serving=kind, quality_gate=gate)


@pytest.mark.parametrize("identifier", ("azureml:titanic@latest", "azureml:titanic", "titanic"))
def test_deployment_requires_explicit_immutable_version(
    identifier, bundle_factory, monkeypatch, evidence,
):
    bundle = bundle_factory("titanic", "custom")
    client, _, _ = mock_service_client(monkeypatch)
    with pytest.raises(ValueError, match="immutable"):
        serving.deploy(bundle.runtime, bundle.root, identifier)
    client.models.get.assert_not_called()
    assert_no_deployment(client)
    evidence("deployment-model-reference", "BLOCKED", model_reference=identifier)


@pytest.mark.parametrize("name", REPRESENTATIVES)
@pytest.mark.parametrize("load_mode", ("initial", "delta"))
def test_adf_initial_delta_lake_binding_and_image_directory_boundary(
    name, load_mode, evidence,
):
    scenario, runtime = scenario_named(name), runtime_for(name)
    copy = {
        "loadMode": load_mode, "sourceContainer": "source", "sourceFolder": "reviewed",
        "filePattern": "*",
    }
    if load_mode == "delta":
        copy.update(watermarkStart="2026-09-01T00:00:00Z", watermarkEnd="2026-09-02T00:00:00Z")
    payload = {"properties": {"jobType": "Pipeline", "inputs": {
        "raw": {"jobInputType": "uri_folder", "uri": "azureml://datastores/old/paths/raw/"},
    }}}
    original = deepcopy((scenario, runtime, copy, payload))
    blocked = scenario["task"].startswith("image_")
    if blocked:
        with pytest.raises(ValueError, match="single dataset filename|Image-directory Copy"):
            adf.build_parameters(runtime, copy, payload, scenario=scenario)
    else:
        result = adf.build_parameters(runtime, copy, payload, scenario=scenario)
        layout = LakeLayout.from_config(runtime["lake"], scenario)
        assert result["sourceContainer"] == copy["sourceContainer"]
        assert result["sourceFolder"] == copy["sourceFolder"]
        assert result["sinkContainer"] == layout.container
        assert result["sinkFolder"] == layout.key("landing")
        assert result["sinkFolder"] != layout.key("silver")
        assert result["jobPayload"]["properties"]["inputs"]["raw"] == {
            "jobInputType": "uri_file",
            "uri": layout.azureml_uri("landing") + scenario["dataset"]["file"],
        }
        assert result["filePattern"] == scenario["dataset"]["file"]
        assert result["subscriptionId"] == runtime["subscription_id"]
        assert result["resourceGroup"] == runtime["resource_group"]
        assert result["workspaceName"] == runtime["workspace_name"]
        assert result["lakeParameters"]["copyStage"] == "landing"
        assert result["lakeParameters"]["paths"] == layout.as_dict()
        assert result["jobPayload"]["properties"]["tags"]["lake.runId"] == layout.run_id
        if load_mode == "delta":
            assert result["watermarkStart"] == copy["watermarkStart"]
            assert result["watermarkEnd"] == copy["watermarkEnd"]
    assert (scenario, runtime, copy, payload) == original
    evidence("adf-single-file-lake-parameters", "BLOCKED" if blocked else "SUPPORTED",
             scenario=name, task=scenario["task"], load_mode=load_mode,
             level="arm-parameter-builder-not-copy-execution")


@pytest.mark.parametrize("end", [
    "2026-09-01T00:00:00Z", "2026-08-31T23:59:59Z",
    "2026-09-02T00:00:00", "2026-09-02T00:00:00+02:00", "not-a-time",
])
def test_adf_delta_rejects_equal_backward_naive_non_utc_and_invalid_windows(end, evidence):
    copy = {
        "loadMode": "delta", "sourceContainer": "source", "sourceFolder": "reviewed",
        "watermarkStart": "2026-09-01T00:00:00Z", "watermarkEnd": end,
    }
    with pytest.raises(ValueError):
        adf.build_parameters(
            runtime_for("titanic"), copy, {"properties": {"jobType": "Pipeline"}},
            scenario=scenario_named("titanic"),
        )
    evidence("adf-temporal-delta-window", "BLOCKED", watermark_end=end)


@pytest.mark.parametrize("pattern", SERVING_PATTERNS)
def test_adf_and_render_share_versioned_serving_metadata_not_deployment_promises(
    pattern, work, evidence,
):
    name = "insurance-regression"
    scenario, runtime = scenario_named(name), runtime_for(name, pattern)
    original = deepcopy(runtime)
    configurations = [
        runtime,
        {**deepcopy(runtime), "lake": {**deepcopy(runtime["lake"]), "run_id": "next-run", "model_version": "18"}},
    ]
    manifests = []
    for index, current in enumerate(configurations):
        result = adf.build_parameters(current, {
            "loadMode": "initial", "sourceContainer": "source", "sourceFolder": "reviewed",
        }, {"properties": {"jobType": "Pipeline", "inputs": {
            "raw": {"jobInputType": "uri_file"},
        }}}, scenario=scenario)
        raw_uri = result["jobPayload"]["properties"]["inputs"]["raw"]["uri"]
        paths = azureml.render(
            scenario, {**current, "input_data": raw_uri}, work / f"bundle-{index}", ROOT, "automl",
        )
        loaded = load_job(source=paths["pipeline"])
        assert loaded.inputs["raw"].path == raw_uri
        rendered = load_json(Path(paths["lake_manifest"]))
        assert result["lakeParameters"]["paths"] == rendered["paths"]
        assert result["lakeParameters"]["serving"] == rendered["serving"] == pattern
        assert result["lakeParameters"]["modelVersion"] == rendered["model_version"]
        assert f"/inference/{pattern}/models/{current['lake']['model_version']}/" in rendered["paths"]["output"]
        manifests.append(rendered)
    first, second = manifests
    assert first["paths"]["checkpoint"] == second["paths"]["checkpoint"]
    assert first["paths"]["output"] != second["paths"]["output"]
    assert first["paths"]["training_gold"] == second["paths"]["training_gold"]
    incompatible = deepcopy(runtime["lake"])
    incompatible["pipeline_version"] = "v2"
    assert LakeLayout.from_config(incompatible, scenario).key("checkpoint") != first["paths"]["checkpoint"]
    assert runtime == original
    if pattern == "streaming":
        assert not list(work.rglob("streaming-deployment.yml"))
    evidence("adf-render-shared-serving-lineage", "SUPPORTED", scenario=name,
             task="regression", mode="automl", serving=pattern,
             level="metadata-not-live-serving")


@pytest.mark.parametrize("alias", ("latest", "active", "champion", "production"))
def test_mutable_model_alias_cannot_enter_cross_surface_lake_metadata(alias, work, evidence):
    scenario, runtime = scenario_named("titanic"), runtime_for("titanic", "streaming")
    runtime["lake"]["model_version"] = alias
    with pytest.raises(ValueError, match="immutable"):
        azureml.render(scenario, runtime, work / "bundle", ROOT, "custom")
    assert not (work / "bundle").exists()
    with pytest.raises(ValueError, match="immutable"):
        adf.build_parameters(runtime, {
            "loadMode": "initial", "sourceContainer": "source", "sourceFolder": "reviewed",
        }, {"properties": {"jobType": "Pipeline"}}, scenario=scenario)
    evidence("adf-render-model-version-alias", "BLOCKED", alias=alias, serving="streaming")


@pytest.mark.parametrize("key", ("job", "pipeline"))
def test_adf_rejects_real_cli_yaml_as_arm_payload(key, bundle_factory, evidence):
    bundle = bundle_factory("titanic", "custom")
    payload = yaml.safe_load(Path(bundle.paths[key]).read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="ARM"):
        adf.build_parameters(bundle.runtime, {
            "loadMode": "initial", "sourceContainer": "source", "sourceFolder": "reviewed",
        }, payload, scenario=bundle.scenario)
    evidence("adf-cli-yaml-as-arm-body", "BLOCKED", yaml_kind=key)


def nested_mappings(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nested_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_mappings(child)


@pytest.mark.parametrize("platform", ("github", "ado"))
def test_workflow_wrappers_preserve_modes_scope_and_explicit_approval(platform, evidence):
    path = MLOPS / platform / "ml-factory.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    if platform == "github":
        assert set(workflow["on"]) == {"workflow_call", "workflow_dispatch"}
        assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["options"] == ["automl", "custom"]
        assert workflow["env"]["MODE"] == "${{ inputs.mode }}"
        for action in ("train", "deploy"):
            job = workflow["jobs"][action]
            assert job["if"] == f"inputs.action == '{action}'"
            assert job["needs"] == "validate"
            login = next(step for step in job["steps"] if step.get("uses") == "azure/login@v2")
            assert login["with"]["tenant-id"] == "${{ secrets.TENANT_ID }}"
            assert login["with"]["subscription-id"] == "${{ secrets.AZURE_SUBSCRIPTION_ID }}"
        assert workflow["jobs"]["deploy"]["environment"] == "${{ inputs.deployment_environment }}"
        validation = workflow["jobs"]["validate"]
    else:
        parameters = {parameter["name"]: parameter for parameter in workflow["parameters"]}
        assert parameters["mode"]["values"] == ["automl", "custom"]
        stages = {value["stage"]: value for value in nested_mappings(workflow) if "stage" in value}
        for action in ("Train", "Deploy"):
            assert stages[action]["dependsOn"] == "Validate"
            assert stages[action]["condition"] == "succeeded()"
            commands = [value for value in nested_mappings(stages[action]) if value.get("task") == "AzureCLI@2"]
            assert len(commands) == 1
            assert commands[0]["inputs"]["azureSubscription"] == "${{ parameters.serviceConnection }}"
            assert commands[0]["env"]["MODE"] == "${{ parameters.mode }}"
        assert stages["Deploy"]["jobs"][0]["environment"] == "${{ parameters.deploymentEnvironment }}"
        validation = stages["Validate"]
    scripts = [
        value[key] for value in nested_mappings(workflow)
        for key in ("run", "pwsh", "inlineScript") if isinstance(value.get(key), str)
    ]
    for action in ("train", "deploy"):
        command = next(script for script in scripts if f'ci.py" {action} ' in script)
        assert "--scenario $env:SCENARIO --runtime $env:RUNTIME --mode $env:MODE" in command
        assert "if ($LASTEXITCODE) { exit $LASTEXITCODE }" in command
        if action == "deploy":
            assert "--model-id $env:MODEL_ID" in command
            assert "--approval-environment $env:DEPLOYMENT_ENVIRONMENT" in command
        else:
            assert " deploy " not in command
    for forbidden in ("azure/login", "AzureCLI@", "az ml", "pip install"):
        assert forbidden not in json.dumps(validation)
    evidence("workflow-wrapper-contract", "SUPPORTED", platform=platform,
             modes=list(MODES), level="yaml-static-contract-not-runner-execution",
             limitation="actual login tenant/subscription and approvals require configured CI infrastructure")


def test_active_orchestration_entrypoints_have_no_sdkv1_imports(evidence):
    sources = [
        ROOT / "ml_model_factory" / "azureml.py", ROOT / "ml_model_factory" / "serving.py",
        ROOT / "scripts" / "azureml_sdk.py", ROOT / "scripts" / "azureml_cli.py",
        MLOPS / "scripts" / "ci.py", ADF / "prepare_run.py",
    ]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imports.append(node.module or "")
        assert not any(name == "azureml" or name.startswith("azureml.") for name in imports), path
    evidence("active-entrypoint-sdk-generation", "SUPPORTED",
             sdk_generation=2, level="python-import-ast")
