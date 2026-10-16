"""Shared offline fixtures: an instantiated consumer ML factory and a reviewed rollout."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

TEMPLATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE))
sys.path.insert(0, str(TEMPLATE.parent))
# MLflow writes tracking files relative to the working directory unless told otherwise.
os.environ.setdefault("MLFLOW_TRACKING_URI", (Path(tempfile.gettempdir()) / "aif49-tests-mlruns").as_uri())

from ml_agent.configuration import make_config, write_json  # noqa: E402
from ml_agent.usecases import AIR  # noqa: E402

FACTORY_TEMPLATE = TEMPLATE.parents[1] / "50-ml-model-factory"
TENANT = "11111111-2222-3333-4444-555555555555"
SUBSCRIPTION = "66666666-7777-8888-9999-000000000000"
FACTORY = SimpleNamespace(tenant_id=TENANT, subscription_id=SUBSCRIPTION, project_number="001", environment="dev")
ENDPOINT = "https://foundry-test.services.ai.azure.com/api/projects/project-test"


def reviewed_rollout() -> dict:
    return {
        "schema": "esml.azureml-rollout-config/v1", "aifactory": "factory-test", "project_number": 1,
        "data_date_utc": "2026-10-08", "use_common_datalake_storage": True,
        "storage_targets": {
            "common": {"account_name": "lakeaccount", "resource_group": "rg-common", "container": "lake3",
                       "datastore": "esml_shared_lake"},
            "project": {"account_name": "projectaccount", "resource_group": "rg-project",
                        "container": "ml-model-factory", "datastore": "ml_model_factory"},
        },
        "storage": {"prefix": "mlops/v1", "input_area": "in", "type": "azure_blob"},
        "runtime": {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "resource_group": "rg-project",
                    "common_resource_group": "rg-common", "workspace_name": "aml-test", "environment_name": "dev",
                    "compute": "m02-cpu-dev", "environment": "azureml:esml-v2-cpu:20260928",
                    "job_identity": {"type": "managed"}, "command_timeout_seconds": 1800},
        "automl_evaluation_environment": "azureml://registries/azureml/environments/ai-ml-automl/versions/41",
        "scenarios": {AIR: {
            "mode": "custom", "compute": "m05-cpu-dev", "data_version": "bootstrap-v2-20260913-r2",
            "run_id": "mlf-esml-air-default",
            "input_path": "mlops/v1/projects/project001/environments/dev/datasets/air-passengers/versions/"
                          "bootstrap-v2-20260913-r2/in",
            "limits": {"max_trials": 3, "max_concurrent_trials": 1, "timeout_minutes": 20}}},
    }


def consumer(tmp: Path, *, instantiate: bool = True) -> dict:
    """Build an orange-like layout below tmp and return a validated agent configuration."""
    orange = Path(tmp) / "orange"
    ml_root = orange / "aifactory-usecase-code" / "50-ml-model-factory"
    if instantiate:
        from ml_model_factory.templates import instantiate as copy_templates

        copy_templates(FACTORY_TEMPLATE, ml_root)
    receipts = orange / "receipts" / "mlf-mp-02-1008"
    write_json(receipts / "training-completion.json", {
        "schema": "esml.azureml-training-completion/v1", "job": "esml-champion-job", "status": "Completed",
        "model_id": "azureml:M05_air_passengers:2"})
    rollout = write_json(orange / "reviewed" / "esml-rollout.local.json", reviewed_rollout())
    factory_config = write_json(orange / "aifactory" / "agent-factory" / "config.json", {"targets": []})
    return make_config(FACTORY, factory_config=factory_config, target="factory-test-project001-dev",
                       orange_root=orange, reviewed_rollout=rollout, project_endpoint=ENDPOINT,
                       model_deployment="gpt-test", state_root=orange / "aifactory" / "agent-factory" / "state",
                       champion_receipts=receipts)


def air_passengers_csv(path: Path) -> Path:
    """A deterministic monthly series with the AirPassengers schema for offline tests."""
    lines = ["Month,#Passengers"]
    for index in range(144):
        year, month = 1949 + index // 12, index % 12 + 1
        lines.append(f"{year}-{month:02d},{100 + index * 2 + (month in (6, 7, 8)) * 40}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
