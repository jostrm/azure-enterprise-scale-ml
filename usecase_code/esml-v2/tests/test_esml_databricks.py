"""Offline SDK, notebook, and actual byte-transfer coverage; no cloud calls."""

import base64
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
import json
from pathlib import Path
import shlex
import shutil
import sys
from types import SimpleNamespace as NS
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
from uuid import uuid4

import pytest
import yaml

from azure_esml.domain_layer.contracts import IPipelineStepMap, PipelineRequest, PipelineType, StepOverride, StepType
from azure_esml.domain_layer import databricks as bridge


OPTIONS = {
    "host": "https://adb-123.1.azuredatabricks.net",
    "workspace_resource_id": "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.Databricks/workspaces/ws",
    "account_url": "https://account001.blob.core.windows.net",
    "container": "lake",
    "prefix": "mlops/v1/projects/project001/environments/dev",
}
JOB = {"job_id": 123, "task_key": "notebook"}


@pytest.fixture
def workdir(monkeypatch):
    root = Path(__file__).parent / ".databricks-runs"
    path = root / uuid4().hex
    path.mkdir(parents=True)
    for variable in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(variable, str(path))
    yield path
    shutil.rmtree(path)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


class Container:
    def __init__(self):
        self.blobs, self.uploads, self.listed, self.downloads = {}, [], [], []

    def upload_blob(self, *, name, data, overwrite):
        assert overwrite is False and name not in self.blobs
        self.blobs[name] = data.read()
        self.uploads.append(name)

    def list_blobs(self, *, name_starts_with, include):
        assert include == ["metadata"]
        self.listed.append(name_starts_with)
        return [NS(name=name) for name in self.blobs if name.startswith(name_starts_with)]

    def download_blob(self, name):
        self.downloads.append(name)
        return NS(readinto=lambda stream: stream.write(self.blobs[name]))


class Jobs:
    def __init__(self, container, *, mutate_receipt=None, files=None, status="SUCCESS", task_status="SUCCESS",
                 task_count=1, failure=None, truncated=False, notebook_error=None):
        self.container, self.calls, self.timeout = container, [], None
        self.mutate_receipt, self.files = mutate_receipt, files or {"nested/data.parquet": b"actual-data"}
        self.status, self.task_status, self.task_count = status, task_status, task_count
        self.failure, self.truncated, self.notebook_error = failure, truncated, notebook_error

    def run_now(self, **kwargs):
        self.calls.append(kwargs)
        outputs = json.loads(kwargs["job_parameters"]["outputs"])
        for uri in outputs.values():
            prefix = urlsplit(uri).path.lstrip("/")
            self.container.blobs.update({prefix + name: value for name, value in self.files.items()})
        self.receipt = {"schema": bridge.SCHEMA, "outputs": outputs}
        if self.mutate_receipt:
            self.mutate_receipt(self.receipt)
        return self

    def result(self, *, timeout):
        self.timeout = timeout
        if self.failure:
            raise self.failure
        return NS(run_id=50, state=NS(result_state=self.status), tasks=[
            NS(task_key="notebook", run_id=51, state=NS(result_state=self.task_status))
            for _ in range(self.task_count)
        ])

    def get_run_output(self, run_id):
        assert run_id == 51
        return NS(notebook_output=NS(result=json.dumps(self.receipt), truncated=self.truncated),
                  error=self.notebook_error)


def execute(workdir, *, inputs=None, outputs=None, **job_options):
    source = workdir / "source"
    source.mkdir(exist_ok=True)
    (source / "data.csv").write_bytes(b"x,y\n1,2\n")
    container = Container()
    jobs = Jobs(container, **job_options)
    result = bridge.run_step(**OPTIONS, **JOB, inputs=inputs or {"data": source},
                             outputs=outputs or {"output": workdir / "output"},
                             context={"scenario": {"target": "y"}}, timeout_seconds=17,
                             client=NS(jobs=jobs), container_client=container)
    return result, container, jobs


def provider(mapping=None, **kwargs):
    return bridge.DatabricksStepMap(mapping if mapping is not None else {step: JOB for step in StepType},
                                   **{**OPTIONS, "environment": "azureml:runtime:7", **kwargs})


def test_upload_and_download_real_files_and_unique_run_prefix(workdir):
    result, container, jobs = execute(workdir)
    call = jobs.calls[0]
    token = call["idempotency_token"]
    assert len(token) == 32
    assert call["job_id"] == 123 and jobs.timeout == timedelta(seconds=17)
    assert json.loads(call["job_parameters"]["context"])["scenario"] == {"target": "y"}
    root = f"{OPTIONS['prefix']}/_bridge/123/{token}"
    assert container.uploads == [root + "/inputs/data/data.csv"]
    assert container.blobs[container.uploads[0]] == b"x,y\n1,2\n"
    assert (workdir / "output" / "nested" / "data.parquet").read_bytes() == b"actual-data"
    assert container.listed == [root + "/outputs/output/"]
    assert all(name.startswith(container.listed[0]) for name in container.downloads)
    assert not (workdir / "output" / "result.json").exists()
    second, _, other_jobs = execute(workdir, outputs={"output": workdir / "another"})
    assert other_jobs.calls[0]["idempotency_token"] != token
    assert second["outputs"] != result["outputs"]


def test_all_named_outputs_are_materialized(workdir):
    outputs = {name: workdir / name for name in ("prepared", "train", "validation", "test")}
    result, container, _ = execute(workdir, outputs=outputs)
    assert set(result["outputs"]) == set(outputs)
    assert len(container.listed) == 4
    assert all((path / "nested" / "data.parquet").read_bytes() == b"actual-data" for path in outputs.values())


@pytest.mark.parametrize("change", [
    lambda receipt: receipt.update(schema="unknown/v0"),
    lambda receipt: receipt["outputs"].update(output="wasbs://other@account001.blob.core.windows.net/private/"),
    lambda receipt: receipt["outputs"].update(unexpected="wasbs://elsewhere/"),
    lambda receipt: receipt["outputs"].clear(),
    lambda receipt: receipt["outputs"].update(output=None),
    lambda receipt: receipt["outputs"].update(output=receipt["outputs"]["output"] + "../elsewhere/"),
])
def test_reject_receipt_mismatch_before_download(workdir, change):
    with pytest.raises(ValueError, match="receipt"):
        execute(workdir, mutate_receipt=change)
    assert not (workdir / "output").exists()


@pytest.mark.parametrize("options", [
    {"status": "FAILED"}, {"task_status": "FAILED"}, {"task_status": None},
    {"task_count": 0}, {"task_count": 2}, {"truncated": True}, {"notebook_error": "failed"},
])
def test_reject_failed_or_ambiguous_task(workdir, options):
    with pytest.raises(ValueError):
        execute(workdir, **options)
    assert not (workdir / "output").exists()


def test_waiter_timeout_is_not_a_successful_step(workdir):
    with pytest.raises(TimeoutError, match="deadline"):
        execute(workdir, failure=TimeoutError("deadline"))
    assert not (workdir / "output").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "nested/../../escape", "nested\\escape", "C:escape", "a//b",
                                 ".. /escape", "nested./escape"])
def test_reject_blob_path_traversal(workdir, name):
    with pytest.raises(ValueError, match="Unsafe"):
        execute(workdir, files={name: b"untrusted"})
    assert not (workdir / "escape").exists()


@pytest.mark.parametrize("files", [{"_SUCCESS": b""}, {"_SUCCESS": b"ok"}, {"data.parquet": b""}])
def test_marker_or_zero_byte_only_output_fails(workdir, files):
    with pytest.raises(ValueError, match="no data"):
        execute(workdir, files=files)


def test_downloads_metadata_with_data(workdir):
    execute(workdir, files={"_SUCCESS": b"", "data.parquet": b"data"})
    assert (workdir / "output" / "_SUCCESS").is_file()
    assert (workdir / "output" / "data.parquet").read_bytes() == b"data"


def test_hierarchical_namespace_directory_entries_are_not_files(workdir, monkeypatch):
    original = Container.list_blobs

    def listing(self, **kwargs):
        return [NS(name=kwargs["name_starts_with"] + "nested", metadata={"hdi_isfolder": "true"}),
                *original(self, **kwargs)]

    monkeypatch.setattr(Container, "list_blobs", listing)
    execute(workdir)
    assert (workdir / "output" / "nested" / "data.parquet").is_file()


def test_empty_input_rejected_before_launch(workdir):
    empty = workdir / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="Input.*no data"):
        execute(workdir, inputs={"data": empty})


def test_symlink_rejected_before_transfer(workdir, monkeypatch):
    source = workdir / "source"
    source.mkdir()
    target = source / "linked.csv"
    target.write_text("x\n1\n")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError, match="Symlink"):
        execute(workdir)


def test_output_must_be_empty_and_nonoverlapping(workdir):
    source = workdir / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="empty"):
        execute(workdir, outputs={"output": source})
    with pytest.raises(ValueError, match="overlap"):
        execute(workdir, outputs={"first": workdir / "out", "second": workdir / "out" / "nested"})


@pytest.mark.parametrize("override", [
    {"host": "http://adb-1.azuredatabricks.net"},
    {"host": "https://user:secret@adb-1.azuredatabricks.net"},
    {"host": "https://adb-1.azuredatabricks.net?token=secret"},
    {"workspace_resource_id": "not-an-arm-id"},
    {"account_url": "https://account001.blob.core.windows.net?sig=secret"},
    {"account_url": "https://example.com"},
    {"container": "INVALID"}, {"container": "a--b"},
    {"prefix": "mlops/v1"}, {"prefix": "../projects/project001"},
    {"prefix": "/mlops/v1/projects/project001"}, {"timeout_seconds": 0},
    {"environment": "azureml:runtime@latest"}, {"environment": "azureml:runtime:latest"},
])
def test_reject_unscoped_or_credential_bearing_configuration(override):
    with pytest.raises(ValueError):
        provider(**override)


@pytest.mark.parametrize("mapping", [
    {"IN_2_SILVER": JOB},
    {StepType.IN_2_SILVER: {"job_id": -1, "task_key": "notebook"}},
    {StepType.IN_2_SILVER: {"job_id": True, "task_key": "notebook"}},
    {StepType.IN_2_SILVER: {"job_id": 1, "task_key": ""}},
    {StepType.IN_2_SILVER: {**JOB, "token": "secret"}},
])
def test_job_mapping_validation(mapping):
    with pytest.raises(ValueError):
        provider(mapping)


def test_mapping_specificity_pinning_dynamic_ports_and_no_cache():
    mapping = provider({StepType.IN_2_SILVER: JOB, (StepType.IN_2_SILVER, "gpu-data"): {**JOB, "job_id": 456}},
                       compute="bridge-cpu")
    assert mapping.resolve(StepType.TRAINING_MANUAL) is None
    assert "--job-id 456" in mapping.resolve(StepType.IN_2_SILVER, "gpu-data").component["command"]
    assert "--job-id 123" in mapping.resolve(StepType.IN_2_SILVER, "other").component["command"]
    assert mapping.resolve(StepType.IN_2_SILVER).compute == "bridge-cpu"
    merge = provider().create_component(StepType.SILVER_MERGED_2_GOLD,
                                       {"discovered1": "uri_folder", "discovered2": "uri_folder"},
                                       {"output": "uri_folder"}, {"merge": {"mode": "concat"}})
    assert set(merge.component["inputs"]) == {"discovered1", "discovered2", "esml_context_b64"}
    assert merge.engine == "databricks" and merge.component["is_deterministic"] is False
    assert "code" not in merge.component
    context = json.loads(base64.b64decode(merge.component["inputs"]["esml_context_b64"]["default"]))
    assert context["merge"]["mode"] == "concat"
    assert '"${{inputs.esml_context_b64}}"' in merge.component["command"]
    assert not merge.inputs
    assert '"${{inputs.discovered1}}"' in merge.component["command"]


@pytest.mark.parametrize("step", list(StepType))
def test_default_ports_load_with_real_sdk(step):
    ml = pytest.importorskip("azure.ai.ml")
    override = provider(datasets=("DS-One", "2_source")).resolve(step)
    component = override.component
    assert component["is_deterministic"] is False
    if step == StepType.SILVER_MERGED_2_GOLD:
        assert set(component["inputs"]) == {"ds_one", "ds_2_source", "esml_context_b64"}
    if step == StepType.TRAINING_SPLIT_AND_REGISTER:
        assert component["outputs"]["train"]["type"] == "mltable"
    if step == StepType.INFERENCE_GOLD:
        assert component["inputs"]["model"]["type"] == "mlflow_model"
    loaded = ml.load_component(StringIO(yaml.safe_dump({**component, "name": "test_bridge"})))
    validation = loaded._validate()
    assert validation.passed, str(validation)


def test_merge_requires_unambiguous_dataset_names():
    for datasets in ((), ("ds-one", "ds_one")):
        with pytest.raises(ValueError, match="datasets"):
            provider(datasets=datasets).resolve(StepType.SILVER_MERGED_2_GOLD)


def test_cli_context_file_and_named_mounts(workdir, monkeypatch):
    config = workdir / "context.json"
    config.write_text('{"scenario":{"target":"label"}}')
    args = ["worker"]
    for name, value in {**OPTIONS, **JOB}.items():
        args += ["--" + name.replace("_", "-"), str(value)]
    args += ["--context-json-file", str(config), "--step", "IN_2_SILVER", "--dataset-name", "source",
             "--input", "data", str(workdir / "input"),
             "--output", "output", str(workdir / "output")]
    captured = {}
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(bridge, "run_step", lambda **kwargs: captured.update(kwargs))
    bridge.main()
    assert captured["context"] == {"scenario": {"target": "label"}, "step": "IN_2_SILVER", "dataset_name": "source"}
    assert captured["inputs"] == {"data": str(workdir / "input")}
    assert captured["outputs"] == {"output": str(workdir / "output")}


def test_production_clients_use_managed_identity_only(workdir, monkeypatch):
    source = workdir / "source"
    source.mkdir()
    (source / "data.csv").write_bytes(b"x\n1\n")
    container = Container()
    jobs = Jobs(container)
    recorded = {}
    credential = object()

    def identity(**kwargs):
        recorded["identity"] = kwargs
        return credential

    def storage(**kwargs):
        recorded["storage"] = kwargs
        return container

    def workspace(**kwargs):
        recorded["workspace"] = kwargs
        return NS(jobs=jobs)

    monkeypatch.setitem(sys.modules, "azure.identity", NS(ManagedIdentityCredential=identity))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", NS(ContainerClient=storage))
    monkeypatch.setitem(sys.modules, "databricks.sdk", NS(WorkspaceClient=workspace))
    bridge.run_step(**OPTIONS, **JOB, inputs={"data": source}, outputs={"output": workdir / "out"}, client_id="identity-id")
    assert recorded["identity"] == {"client_id": "identity-id"}
    assert recorded["storage"] == {"account_url": OPTIONS["account_url"], "container_name": "lake", "credential": credential}
    assert recorded["workspace"] == {"host": OPTIONS["host"], "auth_type": "azure-msi", "azure_use_msi": True,
                                     "azure_workspace_resource_id": OPTIONS["workspace_resource_id"],
                                     "azure_client_id": "identity-id"}


def pipeline_settings():
    from azure_esml.domain_layer.settings import LakeSettings
    return LakeSettings.from_dict({
        "aifactory": "factory01", "project_number": 1, "active_model": 1,
        "storage": {"datastore": "lake", "prefix": "mlops/v1"},
        "runtime": {"tenant_id": "11111111-1111-1111-1111-111111111111",
                    "subscription_id": "22222222-2222-2222-2222-222222222222",
                    "resource_group": "rg-test", "workspace_name": "ws-test",
                    "environment_name": "dev", "compute": "cpu", "environment": "azureml:runtime:7"},
        "models": [{"model_number": 1, "model_folder_name": "m01", "model_short_alias": "M01",
                    "dataset_folder_names": ["ds-one", "ds-two"], "ml_type": "classification",
                    "label": "target", "features": ["x", "y"], "bronze": False}],
    })


@pytest.mark.parametrize("kind", list(PipelineType))
def test_factory_binds_actual_context_and_never_caches_external_jobs(workdir, kind):
    pytest.importorskip("azure.ai.ml")
    from azure_esml.domain_layer.pipeline import ESMLPipelineFactory
    mapping = provider(datasets=("ds-one", "ds-two"), compute="bridge-cpu")
    request = PipelineRequest("2026-09-13", "run123", model_version="9" if kind.is_inference else None)
    plan = ESMLPipelineFactory(pipeline_settings(), step_map=mapping).create_batch_pipeline(kind, request, output=workdir / "plan")
    assert plan.document["settings"]["force_rerun"] is True
    for job in plan.document["jobs"].values():
        assert job["component"]["is_deterministic"] is False
        assert job["compute"] == "azureml:bridge-cpu"
        context = json.loads(base64.b64decode(job["inputs"]["esml_context_b64"]))
        assert context["request"]["run_id"] == "run123"
        assert context["scenario"]["features"] == ["x", "y"]
        assert context["request"]["model_version"] == ("9" if kind.is_inference else None)
        command = shlex.split(job["component"]["command"])
        assert "--step" in command and "${{inputs.esml_context_b64}}" in command
    if kind != PipelineType.GOLD_INFERENCE:
        merge = plan.document["jobs"]["merge"]
        assert set(merge["inputs"]) == {"ds_one", "ds_two", "esml_context_b64"}
        assert json.loads(base64.b64decode(merge["inputs"]["esml_context_b64"]))["merge"] == {"mode": "concat"}
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)


def test_factory_can_mix_databricks_cpu_and_gpu_replacements(workdir):
    pytest.importorskip("azure.ai.ml")
    from azure_esml.domain_layer.pipeline import ESMLPipelineFactory
    dbx = provider({(StepType.IN_2_SILVER, "ds-one"): JOB}, compute="bridge-cpu")

    class MixedMap(IPipelineStepMap):
        def resolve(self, step, dataset=None):
            if (step, dataset) == (StepType.IN_2_SILVER, "ds-two"):
                return StepOverride("azureml:gpu_conversion:1", compute="gpu")
            return dbx.resolve(step, dataset)

    plan = ESMLPipelineFactory(pipeline_settings(), step_map=MixedMap()).create_batch_pipeline(
        PipelineType.IN_2_GOLD, PipelineRequest("2026-09-13", "mixed1"), output=workdir / "plan")
    jobs = plan.document["jobs"]
    assert jobs["in2silver_ds_one"]["compute"] == "azureml:bridge-cpu"
    assert jobs["in2silver_ds_two"]["compute"] == "azureml:gpu"
    assert jobs["merge"]["compute"] == "azureml:cpu"
    assert plan.manifest["steps"]["in2silver_ds_one"]["engine"] == "databricks"
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)


def test_factory_discovers_databricks_ports_without_constructor_datasets(workdir):
    pytest.importorskip("azure.ai.ml")
    from azure_esml.domain_layer.pipeline import ESMLPipelineFactory
    settings = pipeline_settings()
    settings.models[0].options["discover_datasets"] = True
    catalog = NS(list_folders=lambda prefix: ("ds-one", "ds-two", "ds-three"))
    mapping = provider({step: JOB for step in (StepType.IN_2_SILVER, StepType.SILVER_MERGED_2_GOLD, StepType.INFERENCE_GOLD)})
    plan = ESMLPipelineFactory(settings, step_map=mapping, folder_catalog=catalog).create_batch_pipeline(
        PipelineType.IN_2_GOLD_INFERENCE_DBX, PipelineRequest("2026-09-13", "discovered1", model_version="9"),
        output=workdir / "plan")
    assert set(plan.document["jobs"]["merge"]["inputs"]) == {"ds_one", "ds_two", "ds_three", "esml_context_b64"}
    assert all(step["engine"] == "databricks" for step in plan.manifest["steps"].values())
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)


def test_example_notebook_executes_actual_in2silver_merge_and_mlflow_inference(workdir):
    pd = pytest.importorskip("pandas")
    sklearn = pytest.importorskip("sklearn.linear_model")
    mlflow = pytest.importorskip("mlflow.sklearn")
    spec = spec_from_file_location("dbx_example", Path(__file__).parents[1] / "examples" / "app_layer" / "databricks_notebook.py")
    notebook = module_from_spec(spec)
    spec.loader.exec_module(notebook)
    remote = workdir / "remote"
    remote.mkdir()

    def local(uri):
        parsed = urlsplit(uri)
        return Path(url2pathname(unquote(parsed.path))) if parsed.scheme == "file" else remote / parsed.path.lstrip("/")

    def copy(source, destination, *, recurse):
        assert recurse
        shutil.copytree(local(source), local(destination))
        return True

    receipts = []
    fs = NS(cp=copy)
    context = {"scenario": {"name": "dbx-test", "task": "regression", "target": "y", "features": ["x"],
                            "dataset": {"provider": "lake", "kind": "dataset"}},
               "dataset": {"format": "csv"}, "request": {"run_id": "dbx1", "model_version": "1"},
               "merge": {"mode": "concat"}, "tags": {"aifactory": "factory1", "project": "001", "environment": "dev"}}
    uri = "wasbs://lake@account001.blob.core.windows.net/"

    def run(step, inputs, output):
        parameters = {"context": json.dumps({**context, "step": step.value}),
                      "inputs": json.dumps({name: uri + path + "/" for name, path in inputs.items()}),
                      "outputs": json.dumps({"output": uri + output + "/"})}
        notebook.execute(NS(fs=fs, widgets=NS(get=parameters.__getitem__), notebook=NS(exit=receipts.append)),
                         work_root=workdir / "working")

    for name, values in (("a", [1, 2]), ("b", [3, 4])):
        source = remote / name
        source.mkdir()
        pd.DataFrame({"x": values, "request_id": [f"id-{value}" for value in values]}).to_csv(source / "data.csv", index=False)
        run(StepType.IN_2_SILVER, {"data": name}, "silver-" + name)
    context["dataset"]["format"] = "parquet"
    run(StepType.SILVER_MERGED_2_GOLD, {"a": "silver-a", "b": "silver-b"}, "gold")
    model = sklearn.LinearRegression().fit(pd.DataFrame({"x": [1, 2, 3, 4]}), [2, 4, 6, 8])
    mlflow.save_model(model, str(remote / "model"))
    run(StepType.INFERENCE_GOLD, {"data": "gold", "model": "model"}, "predictions")
    predictions = pd.read_parquet(remote / "predictions" / "predictions.parquet")
    assert len(predictions) == 4
    assert predictions["prediction"].tolist() == pytest.approx([2, 4, 6, 8])
    assert len(receipts) == 4
    assert all(json.loads(value)["schema"] == bridge.SCHEMA for value in receipts)
