"""Synthetic sources stage through the same shared-lake seed contract as reviewed Kaggle data."""

from pathlib import Path

import pytest

from azure_esml.domain_layer.lake_seed import stage_kaggle_examples
from azure_esml.domain_layer.shared_lake import SharedLake
from ml_model_factory.config import load_json, validate_scenario, write_json
from ml_model_factory.synthetic import generate


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = load_json(ROOT.parent / "usecase_code" / "50-ml-model-factory" / "user-config" / "model" / "scenarios" / "churn.json")
NAME = "49-synthetic-churn"
VERSION = "aif49-synth-v1"


def scenario():
    value = {key: item for key, item in TEMPLATE.items() if key != "dataset"}
    value.update(name=NAME, dataset={
        "provider": "lake", "kind": "dataset", "file": "telco-churn-synthetic.csv", "version": 1,
        "status": "configured", "license": "synthetic",
        "synthetic": {"generator": "telco-churn", "seed": 49, "rows": 600}})
    return validate_scenario(value)


def bootstrap():
    return {"schema": "esml.shared-lake-bootstrap/v2", "aifactory": "factory-a", "environment": "dev",
            "project": "001", "prefix": "mlops/v1",
            "storage": {"account_url": "https://lakeaccount.blob.core.windows.net", "account_name": "lakeaccount",
                        "container": "lake3", "datastore": "esml_shared_lake", "type": "azure_blob",
                        "input_area": "in"},
            "datasets": [{"scenario": NAME, "dataset": NAME, "file": "telco-churn-synthetic.csv"}]}


def staged(tmp_path, *, tamper=False):
    write_json(tmp_path / "scenarios" / f"{NAME}.json", scenario())
    generate(scenario(), tmp_path / "source" / NAME)
    if tamper:
        data = tmp_path / "source" / NAME / "telco-churn-synthetic.csv"
        data.write_bytes(data.read_bytes() + b"SYN-999999,Female,0,No,No,1,Yes,DSL,One year,No,Mailed check,50.00,50.00,No\n")
    return stage_kaggle_examples(bootstrap(), source_root=tmp_path / "source", scenario_root=tmp_path / "scenarios",
                                 root=tmp_path / "lake", version=VERSION)


def test_synthetic_source_stages_master_project_in_and_gold_without_azure_writes(tmp_path):
    result = staged(tmp_path)
    lake = SharedLake("factory-a", "dev", "mlops/v1")
    assert result["azure_written"] is False
    assert {lake.master(NAME, VERSION), lake.product(NAME, VERSION), lake.project("001", NAME, VERSION)} <= set(
        result["publications"])
    assert result["plan"]["target"] == "https://lakeaccount.blob.core.windows.net/lake3"
    master = load_json(tmp_path / "lake" / lake.master(NAME, VERSION) / "_SUCCESS.json")
    assert master["download_provenance_verified"] is False
    assert master["signature"]["provenance"]["synthetic"] == {"generator": "telco-churn", "seed": 49, "rows": 600}
    sample = result["samples"][0]
    assert sample["project_in"] == lake.project("001", NAME, VERSION) + "/in"
    assert sum(sample["split_rows"].values()) == 600
    binding = load_json(tmp_path / "lake" / sample["gold"].rsplit("/gold", 1)[0] / "source-binding.json")
    assert binding["purpose"].startswith("Synthetic teaching data")


def test_tampered_synthetic_bytes_are_refused(tmp_path):
    with pytest.raises(ValueError, match="provenance hash"):
        staged(tmp_path, tamper=True)
