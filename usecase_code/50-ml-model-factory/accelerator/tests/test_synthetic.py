"""Deterministic synthetic sources: no download, license gate or third-party data."""

import csv
import json
from pathlib import Path

import pytest

from ml_model_factory import cli
from ml_model_factory.config import load_json, validate_scenario, write_json
from ml_model_factory.synthetic import generate, generate_requests


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = load_json(ROOT / "user-config" / "model" / "scenarios" / "churn.json")


def synthetic_scenario(**dataset):
    scenario = {key: value for key, value in TEMPLATE.items() if key != "dataset"}
    scenario["name"] = "49-synthetic-churn"
    scenario["dataset"] = {"provider": "lake", "kind": "dataset", "file": "telco-churn-synthetic.csv",
                           "version": 1, "status": "configured", "license": "synthetic",
                           "synthetic": {"generator": "telco-churn", "seed": 49, "rows": 7043}, **dataset}
    return validate_scenario(scenario)


def test_generation_is_deterministic_and_records_hash_pinned_provenance(tmp_path):
    first = generate(synthetic_scenario(), tmp_path / "a")
    second = generate(synthetic_scenario(), tmp_path / "b")
    data = tmp_path / "a" / "telco-churn-synthetic.csv"
    assert first["sha256"] == second["sha256"] and first["rows"] == 7043 and first["status"] == "created"
    assert data.read_bytes() == (tmp_path / "b" / "telco-churn-synthetic.csv").read_bytes()
    provenance = load_json(tmp_path / "a" / "provenance.json")
    assert provenance["provider"] == "lake" and provenance["kind"] == "dataset" and provenance["version"] == 1
    assert provenance["synthetic"] == {"generator": "telco-churn", "seed": 49, "rows": 7043}
    assert provenance["files"] == {"telco-churn-synthetic.csv": first["sha256"]}
    assert "slug" not in provenance and "third-party" in provenance["license"]
    with data.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert set(TEMPLATE["features"]) | {"customerID", "TotalCharges", "Churn"} == set(rows[0])
    churn_rate = sum(row["Churn"] == "Yes" for row in rows) / len(rows)
    assert 0.22 <= churn_rate <= 0.31
    assert all((row["TotalCharges"] == "") == (row["tenure"] == "0") for row in rows)
    assert len({row["customerID"] for row in rows}) == len(rows)
    assert generate(synthetic_scenario(), tmp_path / "a")["status"] == "unchanged"


def test_existing_different_outputs_are_never_replaced(tmp_path):
    generate(synthetic_scenario(), tmp_path)
    with pytest.raises(ValueError, match="differs"):
        generate(synthetic_scenario(synthetic={"generator": "telco-churn", "seed": 50, "rows": 7043}), tmp_path)


def test_requests_are_unlabeled_unique_and_reproducible(tmp_path):
    import pandas as pd

    first = generate_requests(synthetic_scenario(), tmp_path / "a", rows=50, seed=4901)
    second = generate_requests(synthetic_scenario(), tmp_path / "b", rows=50, seed=4901)
    frame = pd.read_parquet(first["requests"])
    assert first["rows"] == len(frame) == 50 and first["seed"] == 4901
    assert list(frame.columns) == ["request_id", *TEMPLATE["features"]]
    assert frame["request_id"].is_unique and "Churn" not in frame
    pd.testing.assert_frame_equal(frame, pd.read_parquet(second["requests"]))
    assert load_json(tmp_path / "a" / "manifest.json")["labels_included"] is False


@pytest.mark.parametrize("change, message", [
    ({"provider": "kaggle", "slug": "a/b"}, "lake"),
    ({"synthetic": {"generator": "unknown", "seed": 1, "rows": 100}}, "generator"),
    ({"synthetic": {"generator": "telco-churn", "seed": -1, "rows": 100}}, "seed"),
    ({"synthetic": {"generator": "telco-churn", "seed": 1, "rows": 10}}, "rows"),
    ({"synthetic": {"generator": "telco-churn", "seed": 1, "rows": 100, "extra": 1}}, "fields"),
])
def test_synthetic_sources_are_validated(change, message):
    with pytest.raises(ValueError, match=message):
        synthetic_scenario(**change)


def test_synthetic_generator_contract_must_match_the_scenario(tmp_path):
    scenario = synthetic_scenario()
    scenario["target"] = "Outcome"
    with pytest.raises(ValueError, match="target"):
        generate(scenario, tmp_path)


def test_synthesize_cli_writes_data_and_provenance(tmp_path, capsys):
    path = write_json(tmp_path / "49-synthetic-churn.json", synthetic_scenario()) or tmp_path / "49-synthetic-churn.json"
    assert cli.main(["synthesize", "--scenario", str(path), "--output", str(tmp_path / "raw")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["rows"] == 7043 and (tmp_path / "raw" / "provenance.json").is_file()


def test_synthetic_churn_is_learnable_by_the_custom_template(tmp_path):
    from ml_model_factory.data import prepare
    from ml_model_factory.evaluation import evaluate
    from ml_model_factory.training import train

    scenario = synthetic_scenario()
    generate(scenario, tmp_path / "raw")
    prepare(scenario, tmp_path / "raw" / "telco-churn-synthetic.csv", tmp_path / "prepared")
    train(scenario, tmp_path / "prepared", tmp_path / "model")
    evaluate(scenario, tmp_path / "prepared", tmp_path / "model", tmp_path / "evaluation")
    metrics = load_json(next((tmp_path / "evaluation").rglob("metrics.json")))
    assert metrics["accuracy"] >= 0.65 and metrics["auc_weighted"] >= 0.70
    assert load_json(next((tmp_path / "evaluation").rglob("quality-gate.json")))["passed"] is True
