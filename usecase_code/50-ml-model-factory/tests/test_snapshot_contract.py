"""Gold snapshots are data artifacts, independent of model/quality-gate variants."""

from copy import deepcopy
from pathlib import Path
import shutil
from unittest.mock import patch

import pandas as pd
import pytest

from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import sha256
from ml_model_factory.lake import LakeLayout
from ml_model_factory.lake_flow import (
    capture_source, preparation_contract, prepare_snapshot, snapshot_signature_matches,
    file_inventory, train_in_lake, validate_request_ids, verified_manifest,
)
from test_lake import CONFIG, SCENARIO, raw_table


@pytest.mark.parametrize("field,value", [
    ("custom", {"algorithm": "random_forest"}),
    ("automl", {"limits": {"max_trials": 10}}),
    ("quality", {"min_accuracy": 0.9}),
    ("model_name", "another-model"),
    ("responsible_ai", {"intended_use": "education"}),
])
def test_model_and_evaluation_settings_do_not_change_snapshot(field, value):
    variant = {**deepcopy(SCENARIO), field: value}
    assert preparation_contract(variant) == preparation_contract(SCENARIO)


@pytest.mark.parametrize("field,value", [
    ("features", ["sex", "age"]),
    ("target", "other_label"),
    ("categorical_features", []),
    ("sensitive_features", []),
    ("split", {"seed": 13, "test_size": 0.2, "validation_size": 0.2}),
    ("split", {"seed": 42, "test_size": 0.1, "validation_size": 0.2}),
    ("split", {"seed": 42, "test_size": 0.2, "validation_size": 0.1}),
    ("split", {"seed": 42, "test_size": 0.2, "validation_size": 0.2, "group_column": "entity"}),
])
def test_preparation_changes_require_new_snapshot(field, value):
    assert preparation_contract({**deepcopy(SCENARIO), field: value}) != preparation_contract(SCENARIO)


def test_normalized_split_defaults_and_defensive_copy():
    implicit = deepcopy(SCENARIO)
    implicit.pop("split")
    assert preparation_contract(implicit) == preparation_contract(SCENARIO)
    result = preparation_contract(SCENARIO)
    result["features"].append("unrelated")
    assert "unrelated" not in SCENARIO["features"]


@pytest.mark.parametrize("field,value", [
    ("time_column", "timestamp"), ("horizon", 7), ("frequency", "W"), ("series_columns", ["store"]),
])
def test_forecast_preparation_is_part_of_identity(field, value):
    scenario = {**deepcopy(SCENARIO), "task": "forecasting",
                "forecast": {"time_column": "date", "horizon": 3, "frequency": "D", "series_columns": []}}
    variant = deepcopy(scenario)
    variant["forecast"][field] = value
    assert preparation_contract(variant) != preparation_contract(scenario)


@pytest.mark.parametrize("field,value", [
    ("format", "coco"), ("annotations", "new.jsonl"), ("image_root", "images"),
    ("image_column", "uri"), ("label_column", "category"),
    ("image_base_uri", "azureml://datastores/lake/paths/images/v2"),
])
def test_image_source_contract_is_part_of_identity(field, value):
    scenario = {"name": "images", "task": "image_classification",
                "vision": {"format": "jsonl", "annotations": "annotations.jsonl"}}
    variant = deepcopy(scenario)
    variant["vision"][field] = value
    assert preparation_contract(variant) != preparation_contract(scenario)
    training_variant = deepcopy(scenario)
    training_variant["vision"].update(epochs=3, device="cuda", batch_size=8)
    assert preparation_contract(training_variant) == preparation_contract(scenario)


def test_two_real_model_variants_reuse_gold_without_repreparation(tmp_path):
    source = tmp_path / "input.csv"
    raw_table(source)
    root = tmp_path / "lake"
    first = train_in_lake(SCENARIO, CONFIG, source, root)
    layout = LakeLayout.from_config(CONFIG)
    snapshot_marker = layout.local_path(root, "training_snapshot") / "_SUCCESS.json"
    original_hash = sha256(snapshot_marker)
    original_files = verified_manifest(snapshot_marker.parent)["files"]
    alternative = {**deepcopy(SCENARIO), "custom": {"algorithm": "random_forest"},
                   "quality": {"min_accuracy": 0.1}, "model_name": "alternative-model"}
    with patch("ml_model_factory.data.prepare", side_effect=AssertionError("Snapshot must be reused")):
        second = train_in_lake(alternative, {**CONFIG, "run_id": "r2"}, source, root)
    assert first["model"] != second["model"]
    assert sha256(snapshot_marker) == original_hash
    assert verified_manifest(snapshot_marker.parent)["files"] == original_files
    assert load_json(Path(second["model"]) / "factory.json")["scenario"]["custom"]["algorithm"] == "random_forest"
    assert load_json(Path(second["model"]).parent / "evaluation/quality-gate.json")["passed"] is True
    modified = deepcopy(alternative)
    modified["split"]["seed"] = 19
    with pytest.raises(ValueError, match="different data or preparation"):
        train_in_lake(modified, {**CONFIG, "run_id": "r3"}, source, root)


def test_legacy_snapshot_signature_is_read_without_rewriting(tmp_path):
    source = tmp_path / "input.csv"
    raw_table(source)
    root = tmp_path / "lake"
    layout = LakeLayout.from_config(CONFIG)
    captured = capture_source(SCENARIO, layout, source, root)
    prepare_snapshot(SCENARIO, layout, captured, root)
    marker = layout.local_path(root, "training_snapshot") / "_SUCCESS.json"
    metadata = load_json(marker)
    metadata["signature"].pop("preparation")
    metadata["signature"]["scenario"] = deepcopy(SCENARIO)
    write_json(marker, metadata)
    original = marker.read_bytes()
    alternative = {**SCENARIO, "quality": {"min_accuracy": 0.8}}
    with patch("ml_model_factory.data.prepare", side_effect=AssertionError("Legacy snapshot must be reused")):
        prepare_snapshot(alternative, layout, captured, root)
    assert marker.read_bytes() == original


def test_changed_source_hash_or_unknown_signature_never_matches():
    expected = {"preparation": preparation_contract(SCENARIO), "dataset_key": "dataset",
                "source_manifest_sha256": "digest"}
    assert not snapshot_signature_matches({**expected, "source_manifest_sha256": "changed"}, expected)
    assert not snapshot_signature_matches(None, expected)
    assert not snapshot_signature_matches({**expected, "unknown": True}, expected)


def test_source_change_during_copy_cannot_publish_inconsistent_version(tmp_path):
    source = tmp_path / "input.csv"
    raw_table(source)
    root = tmp_path / "lake"
    layout = LakeLayout.from_config(CONFIG)
    original_copy = shutil.copy2

    def mutate_and_copy(path, destination):
        frame = pd.read_csv(path)
        frame.loc[0, "age"] = 999
        frame.to_csv(path, index=False)
        return original_copy(path, destination)

    with patch("ml_model_factory.lake_flow.shutil.copy2", side_effect=mutate_and_copy):
        with pytest.raises(ValueError, match="changed during capture"):
            capture_source(SCENARIO, layout, source, root)
    assert not layout.local_path(root, "dataset_root").exists()


def test_nested_completion_file_is_part_of_inventory(tmp_path):
    (tmp_path / "_SUCCESS.json").write_text("{}")
    (tmp_path / "source").mkdir()
    (tmp_path / "source/_SUCCESS.json").write_text('{"source":"metadata"}')
    assert set(file_inventory(tmp_path)) == {"source/_SUCCESS.json"}


@pytest.mark.parametrize("values", [[""], ["   "], [None], ["a", "a"]])
def test_blank_missing_or_duplicate_request_ids_are_rejected(values):
    with pytest.raises(ValueError, match="nonempty unique"):
        validate_request_ids(pd.DataFrame({"request_id": values}), "request_id")


def test_rejected_training_run_id_cannot_later_be_reused(tmp_path):
    source = tmp_path / "input.csv"
    raw_table(source)
    root = tmp_path / "lake"
    invalid = {**deepcopy(SCENARIO), "quality": {"min_accuracy": 1.1}}
    with pytest.raises(ValueError, match="quality gate failed"):
        train_in_lake(invalid, CONFIG, source, root)
    with pytest.raises(ValueError, match="run ID already exists"):
        train_in_lake(SCENARIO, CONFIG, source, root)


@pytest.mark.parametrize("field,value", [("version", 2), ("kind", "competition"), ("slug", "other/source")])
def test_source_provenance_identity_must_match_requested_dataset(field, value, tmp_path):
    source = tmp_path / "input.csv"
    raw_table(source)
    declared = SCENARIO["dataset"]
    provenance = {"provider": "kaggle", "slug": declared["slug"], "kind": declared["kind"],
                  "version": declared["version"], "files": {source.name: sha256(source)}}
    provenance[field] = value
    write_json(tmp_path / "provenance.json", provenance)
    with pytest.raises(ValueError, match="provenance"):
        capture_source(SCENARIO, LakeLayout.from_config(CONFIG), source, tmp_path / "lake")
