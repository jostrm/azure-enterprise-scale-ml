import json
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from ml_model_factory import cli
from ml_model_factory.endpoints import (
    adapt_online_request, delete_endpoint, deploy_serving, invoke_batch, invoke_online, render_serving,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = {"provider": "kaggle", "kind": "dataset", "slug": "example/example", "version": 1, "file": "train.csv"}
SCENARIO = {"name": "serve-fixture", "task": "classification", "target": "label",
            "features": ["age", "income"], "dataset": DATASET}
FORECAST = {**SCENARIO, "task": "forecasting", "features": ["date"], "target": "sales",
            "forecast": {"time_column": "date", "series_columns": [], "frequency": "D", "horizon": 2}}
RUNTIME = {"aifactory": "factory", "project": "001", "environment_name": "dev",
           "subscription_id": "00000000-0000-0000-0000-000000000001",
           "tenant_id": "00000000-0000-0000-0000-000000000002",
           "resource_group": "rg", "workspace_name": "ws", "compute": "cpu", "gpu_compute": "gpu",
           "input_data": "azureml://datastores/raw/paths/train.csv",
           "serving": {"instance_count": 1, "batch_instance_count": 1}}


def _loaders():
    try:
        from azure.ai.ml import load_batch_endpoint, load_job, load_online_deployment, load_online_endpoint
        from ml_model_factory.serving import load_model_batch_deployment
    except ImportError:
        return None
    return load_online_endpoint, load_online_deployment, load_batch_endpoint, load_model_batch_deployment, load_job


def test_render_no_code_online_and_batch_are_sdk_loadable(tmp_path):
    online = render_serving(SCENARIO, RUNTIME, tmp_path / "online", kind="online", model_name="serve-fixture",
                            mode="custom", source=ROOT)
    batch = render_serving(SCENARIO, RUNTIME, tmp_path / "batch", kind="batch", model_name="serve-fixture",
                           mode="automl", source=ROOT)
    online_manifest = json.loads(Path(online["manifest"]).read_text())
    batch_manifest = json.loads(Path(batch["manifest"]).read_text())
    assert online_manifest["endpoint_name"] == "serve-fixture-online"
    assert batch_manifest["endpoint_name"] == "serve-fixture-batch"
    assert "code" not in online and "online_deployment" in online
    assert yaml.safe_load(Path(online["online_deployment"]).read_text())["model"].endswith(":REPLACE_WITH_REGISTERED_VERSION")
    assert "batch_deployment" in batch
    loaders = _loaders()
    if loaders:
        load_online_endpoint, load_online_deployment, load_batch_endpoint, load_batch_deployment, _ = loaders
        assert load_online_endpoint(source=online["online_endpoint"])
        assert load_online_deployment(source=online["online_deployment"])
        assert load_batch_endpoint(source=batch["batch_endpoint"])
        assert load_batch_deployment(Path(batch["batch_deployment"]))


def test_render_custom_forecast_online_and_batch_job_include_bundle_and_env(tmp_path):
    online = render_serving(FORECAST, RUNTIME, tmp_path / "forecast-online", kind="online", model_name="forecast-model",
                            mode="custom", source=ROOT)
    deployment = yaml.safe_load(Path(online["online_deployment"]).read_text())
    assert deployment["code_configuration"]["scoring_script"] == "scripts/online_score.py"
    assert "azureml-serving-custom.yml" in json.dumps(deployment["environment"])
    assert (Path(online["code"]) / "ml_model_factory" / "online.py").is_file()
    batch = render_serving(FORECAST, RUNTIME, tmp_path / "forecast-batch", kind="batch", model_name="forecast-model",
                           mode="automl", source=ROOT)
    assert json.loads(Path(batch["manifest"]).read_text())["endpoint_name"] is None
    assert "batch_job" in batch and "batch_deployment" not in batch
    loaders = _loaders()
    if loaders:
        assert loaders[-1](source=batch["batch_job"])


def test_preview_invoke_delete_and_secure_batch_inputs(tmp_path):
    request = tmp_path / "request.json"
    request.write_text("{}")
    assert invoke_online(RUNTIME, "e", request)["preview_only"] is True
    assert invoke_batch(RUNTIME, "b", "azureml://datastores/raw/paths/requests/")["preview_only"] is True
    with pytest.raises(ValueError):
        invoke_batch(RUNTIME, "b", "https://account.blob.core.windows.net/c/data?sas=secret")
    assert delete_endpoint(RUNTIME, "online", "e")["preview_only"] is True


def _registered(paths, mode="custom", scenario="serve-fixture", name="serve-fixture"):
    tags = json.loads(Path(paths["manifest"]).read_text())["model_tags"]
    return types.SimpleNamespace(type="mlflow_model", id=f"azureml:{name}:3",
                                 tags={**tags, "quality_gate": "passed", "pipeline_job": "pipe",
                                       "factory_scenario": scenario, "factory_mode": mode})


def test_deploy_preview_and_execute_online_traffic_last(tmp_path):
    paths = render_serving(SCENARIO, RUNTIME, tmp_path / "bundle", kind="online", model_name="serve-fixture",
                           mode="custom", scoring="custom", source=ROOT)
    assert deploy_serving(RUNTIME, tmp_path / "bundle", "azureml:serve-fixture:3")["preview_only"] is True
    try:
        import azure.ai.ml  # noqa: F401
    except ImportError:
        pytest.skip("azure-ai-ml optional")
    client = MagicMock()
    client.models.get.return_value = _registered(paths)
    # Registry lineage tags may exceed the ARM 256-character tag value limit of endpoints/deployments.
    client.models.get.return_value.tags["copied_from_path"] = "azureml://" + "x" * 300
    endpoint = types.SimpleNamespace(name="serve-fixture-online", traffic={})
    client.online_endpoints.get.return_value = endpoint
    assert json.loads((tmp_path / "bundle" / "code" / "serving.json").read_text())["model_version"] == "REPLACE_WITH_REGISTERED_VERSION"
    result = deploy_serving(RUNTIME, tmp_path / "bundle", "azureml:serve-fixture:3", execute=True, client=client)
    assert result["endpoint"] == "serve-fixture-online" and result["resolved_version"] == "3"
    assert result["omitted_resource_tags"] == ["copied_from_path"]
    sent = client.online_deployments.begin_create_or_update.call_args.args[0].tags
    assert "copied_from_path" not in sent and sent["quality_gate"] == "passed"
    assert all(len(value) <= 256 for value in sent.values())
    assert json.loads((tmp_path / "bundle" / "code" / "serving.json").read_text())["model_version"] == "3"
    assert client.online_endpoints.begin_create_or_update.call_count == 2
    assert endpoint.traffic == {"blue": 100}
    client.models.get.return_value.tags["factory_mode"] = "automl"
    with pytest.raises(ValueError, match="mode"):
        deploy_serving(RUNTIME, tmp_path / "bundle", "azureml:serve-fixture:3", execute=True, client=client)


def test_deploy_scoring_job_bundle_has_no_persistent_submission(tmp_path):
    render_serving(FORECAST, RUNTIME, tmp_path / "bundle", kind="batch", model_name="forecast-model",
                   mode="automl", source=ROOT)
    preview = deploy_serving(RUNTIME, tmp_path / "bundle", "azureml:forecast-model:3")
    assert preview["endpoint"] is None and "per invocation" in preview["message"]
    with pytest.raises(ValueError, match="per invocation"):
        deploy_serving(RUNTIME, tmp_path / "bundle", "azureml:forecast-model:3", execute=True, client=MagicMock())


def test_invoke_scoring_job_resolves_unique_job_files_and_submits_on_execute(tmp_path):
    paths = render_serving(FORECAST, RUNTIME, tmp_path / "bundle", kind="batch", model_name="forecast-model",
                           mode="automl", source=ROOT)
    client = MagicMock()
    client.models.get.return_value = _registered(paths, mode="automl", scenario="serve-fixture", name="forecast-model")
    preview1 = invoke_batch(RUNTIME, input_uri="azureml://datastores/raw/paths/requests/", bundle=tmp_path / "bundle",
                            model_id="azureml:forecast-model:3", history_uri="azureml://datastores/raw/paths/history/",
                            client=client)
    preview2 = invoke_batch(RUNTIME, input_uri="https://account.blob.core.windows.net/c/requests.parquet",
                            bundle=tmp_path / "bundle", model_id="azureml:forecast-model:3",
                            history_uri="https://account.blob.core.windows.net/c/history.parquet", client=client)
    assert preview1["endpoint"] is None and preview1["job_file"] != preview2["job_file"]
    job1 = yaml.safe_load(Path(preview1["job_file"]).read_text())
    assert job1["inputs"]["model"]["path"] == "azureml:forecast-model:3"
    assert job1["inputs"]["requests"]["type"] == "uri_folder"
    assert "REPLACE_WITH" not in Path(preview1["job_file"]).read_text()
    with pytest.raises(ValueError, match="history"):
        invoke_batch(RUNTIME, input_uri="azureml://datastores/raw/paths/requests/", bundle=tmp_path / "bundle",
                     model_id="azureml:forecast-model:3", client=client)
    try:
        import azure.ai.ml  # noqa: F401
    except ImportError:
        pytest.skip("azure-ai-ml optional")
    client.jobs.create_or_update.return_value.name = "score-job"
    executed = invoke_batch(RUNTIME, input_uri="azureml://datastores/raw/paths/requests/", bundle=tmp_path / "bundle",
                            model_id="azureml:forecast-model:3", history_uri="azureml://datastores/raw/paths/history/",
                            execute=True, client=client)
    assert executed["job"] == "score-job"


def test_lake_bound_scoring_job_writes_governed_inference_output_with_job_identity(tmp_path):
    runtime = {**RUNTIME, "datastore": "lake", "job_identity": {"type": "managed"},
               "lake": {"aifactory": "factory", "project": "001", "environment": "dev", "dataset": "serve-data",
                        "data_version": "v1", "snapshot_id": "snap-1", "run_id": "score-run-7",
                        "storage": {"datastore": "lake"}}}
    paths = render_serving(SCENARIO, runtime, tmp_path / "bundle", kind="batch", model_name="serve-fixture",
                           mode="custom", scoring="custom", source=ROOT)
    rendered = yaml.safe_load(Path(paths["batch_job"]).read_text())
    assert rendered["jobs"]["score"]["identity"] == {"type": "managed"}
    assert "path" not in rendered["outputs"]["predictions"]
    client = MagicMock()
    client.models.get.return_value = _registered(paths)
    preview = invoke_batch(runtime, input_uri="azureml://datastores/lake/paths/requests/", bundle=tmp_path / "bundle",
                           model_id="azureml:serve-fixture:3", client=client, inference_run_id="score-day-1")
    job = yaml.safe_load(Path(preview["job_file"]).read_text())
    expected = ("azureml://datastores/lake/paths/mlops/v1/projects/project001/environments/dev/usecases/"
                "serve-fixture/inference/batch/models/3/runs/score-day-1/out/")
    assert job["outputs"]["predictions"] == {"type": "uri_folder", "path": expected, "mode": "rw_mount"}
    assert preview["predictions_uri"] == expected and preview["inference_run_id"] == "score-day-1"
    assert job["jobs"]["score"]["identity"] == {"type": "managed"}
    loaders = _loaders()
    if loaders:
        assert loaders[-1](source=preview["job_file"])
    # Repeated scoring of one model version must never share an output folder (fail-late or silent overwrite).
    first, second = (invoke_batch(runtime, input_uri="azureml://datastores/lake/paths/requests/",
                                  bundle=tmp_path / "bundle", model_id="azureml:serve-fixture:3", client=client)
                     for _ in range(2))
    assert first["predictions_uri"] != second["predictions_uri"]
    assert "/runs/score-run-7/" not in first["predictions_uri"]
    with pytest.raises(ValueError, match="differ from the training"):
        invoke_batch(runtime, input_uri="azureml://datastores/lake/paths/requests/", bundle=tmp_path / "bundle",
                     model_id="azureml:serve-fixture:3", client=client, inference_run_id="score-run-7")
    with pytest.raises(ValueError, match="inference_run_id"):
        invoke_batch(runtime, input_uri="azureml://datastores/lake/paths/requests/", bundle=tmp_path / "bundle",
                     model_id="azureml:serve-fixture:3", client=client, inference_run_id="../escape")
    no_lake = {key: value for key, value in runtime.items() if key != "lake"}
    with pytest.raises(ValueError, match="requires runtime.lake"):
        invoke_batch(no_lake, input_uri="azureml://datastores/lake/paths/requests/", bundle=tmp_path / "bundle",
                     model_id="azureml:serve-fixture:3", client=client, inference_run_id="score-day-2")


def test_adapt_online_request_for_automl_image_and_history_and_invoke_writes_file(tmp_path):
    image = {"name": "serve-image", "task": "image_classification", "dataset": DATASET}
    paths = render_serving(image, RUNTIME, tmp_path / "image", kind="online", model_name="image-model",
                           mode="automl", source=ROOT)
    payload = {"input_data": {"columns": ["image_base64"], "data": [["abc"]]}}
    assert adapt_online_request(paths["manifest"], payload)["input_data"]["columns"] == ["image"]
    import pandas as pd
    request = tmp_path / "request.json"
    request.write_text(json.dumps(payload))
    history = tmp_path / "history.parquet"
    pd.DataFrame({"image_base64": ["x"], "label": ["cat"]}).to_parquet(history)
    preview = invoke_online(RUNTIME, "serve-image-online", request, bundle=tmp_path / "image", history_path=history)
    adapted = json.loads(Path(preview["request"]).read_text())
    assert adapted["input_data"]["columns"] == ["image"] and "history" in adapted


def test_cli_serving_render_and_previews(tmp_path, capsys):
    scenario = tmp_path / "scenario.json"
    runtime = tmp_path / "runtime.json"
    request = tmp_path / "request.json"
    scenario.write_text(json.dumps(SCENARIO))
    runtime.write_text(json.dumps(RUNTIME))
    request.write_text("{}")
    bundle = tmp_path / "cli-bundle"
    assert cli.main(["serving-render", "--scenario", str(scenario), "--runtime", str(runtime), "--kind", "online",
                     "--model-name", "serve-fixture", "--mode", "custom", "--output", str(bundle),
                     "--source", str(ROOT)]) == 0
    assert json.loads(capsys.readouterr().out)["online_deployment"]
    assert cli.main(["serving-deploy", "--runtime", str(runtime), "--bundle", str(bundle),
                     "--model-id", "azureml:serve-fixture:3"]) == 0
    assert cli.main(["serving-invoke", "--runtime", str(runtime), "--kind", "online", "--endpoint", "e",
                     "--request", str(request), "--bundle", str(bundle)]) == 0
    assert cli.main(["serving-invoke", "--runtime", str(runtime), "--kind", "batch",
                     "--input", "azureml://datastores/raw/paths/requests/"]) == 1
    assert cli.main(["serving-delete", "--runtime", str(runtime), "--kind", "online", "--endpoint", "e"]) == 0


def test_private_workspace_network_settings_and_explicit_endpoint_name(tmp_path):
    runtime = {**RUNTIME, "serving": {**RUNTIME["serving"], "public_network_access": "disabled",
                                      "egress_public_network_access": "disabled"}}
    paths = render_serving(SCENARIO, runtime, tmp_path / "online", kind="online", model_name="serve-fixture",
                           mode="custom", source=ROOT, endpoint_name="spider-p001-fixture-online")
    endpoint = yaml.safe_load(Path(paths["online_endpoint"]).read_text())
    deployment = yaml.safe_load(Path(paths["online_deployment"]).read_text())
    assert endpoint["name"] == deployment["endpoint_name"] == "spider-p001-fixture-online"
    assert endpoint["public_network_access"] == "disabled"
    assert deployment["egress_public_network_access"] == "disabled"
    assert json.loads(Path(paths["manifest"]).read_text())["endpoint_name"] == "spider-p001-fixture-online"
    loaders = _loaders()
    if loaders:
        assert loaders[0](source=paths["online_endpoint"]).public_network_access == "disabled"
        assert loaders[1](source=paths["online_deployment"]).egress_public_network_access == "disabled"
    with pytest.raises(ValueError, match="endpoint_name"):
        render_serving(SCENARIO, runtime, tmp_path / "bad", kind="online", model_name="serve-fixture", mode="custom",
                       source=ROOT, endpoint_name="9-invalid")
    with pytest.raises(ValueError, match="egress_public_network_access"):
        render_serving(SCENARIO, {**runtime, "serving": {"egress_public_network_access": "off"}}, tmp_path / "bad2",
                       kind="online", model_name="serve-fixture", mode="custom", source=ROOT)
