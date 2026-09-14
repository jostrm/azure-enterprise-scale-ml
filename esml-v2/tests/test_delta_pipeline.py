from pathlib import Path
from types import SimpleNamespace
import pytest

from azure_esml import ESMLProject, LakeSettings, PipelineRequest, PipelineType
from ml_model_factory.config import load_json


ROOT = Path(__file__).resolve().parents[1]


def settings():
    document = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    model = document["models"][0]
    model["dataset_folder_names"] = ["ds01_diabetes"]
    for key in ("bronze", "table_format", "aml_table_format"):
        model.pop(key, None)
    return document


def test_one_dataset_always_has_bronze_silver_gold_and_gold_only_training(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(settings()))
    plan = project.create_pipeline(PipelineType.IN_2_GOLD_TRAINING_AUTOML,
                                   PipelineRequest("2026-09-14", "delta-default"), output=tmp_path / "job")
    assert list(plan.document["jobs"]) == ["in2bronze_ds01_diabetes", "bronze2silver_ds01_diabetes", "merge", "split", "train", "evaluate"]
    assert plan.document["jobs"]["merge"]["inputs"]["ds01_diabetes"] == "${{parent.jobs.bronze2silver_ds01_diabetes.outputs.output}}"
    assert plan.document["jobs"]["split"]["inputs"]["data"] == "${{parent.jobs.merge.outputs.output}}"
    assert plan.document["jobs"]["train"]["training_data"] == "${{parent.jobs.split.outputs.train}}"
    assert plan.manifest["table_format"] == plan.manifest["aml_table_format"] == "delta"
    assert plan.manifest["bronze_mode"] == "raw"
    assert "/gold/splits/train/" in plan.document["outputs"]["train"]["path"]
    assert "/gold/table/" in plan.document["outputs"]["gold"]["path"]
    for key in ("bronze2silver_ds01_diabetes", "merge", "split"):
        config = load_json(plan.base_path / "code" / "configs" / (key + ".json"))
        assert config["table_format"] == "delta" and config["require_gold"]
    assert plan.to_sdk()._validate().passed


def test_shared_silver_reference_feeds_gold_without_repeating_refinement(tmp_path):
    document = settings()
    document["models"][0]["datasets"] = {"ds01_diabetes": {
        "format": "delta", "source_stage": "silver", "delta_version": 0,
        "required_columns": ["Age"],
        "input_path": "mlops/v1/projects/project003/environments/dev/products/diabetes/versions/v1/silver",
    }}
    plan = ESMLProject(LakeSettings.from_dict(document)).create_pipeline(
        PipelineType.IN_2_GOLD_TRAINING_MANUAL, PipelineRequest("2026-09-14", "shared-delta"), output=tmp_path / "job")
    assert list(plan.document["jobs"]) == ["merge", "split", "train", "evaluate"]
    assert len(plan.manifest["silver_references"]) == 1
    assert plan.document["jobs"]["merge"]["inputs"]["ds01_diabetes"] == "${{parent.inputs.raw_ds01_diabetes}}"
    config = load_json(plan.base_path / "code" / "configs" / "merge.json")
    assert config["input_versions"] == {"ds01_diabetes": 0}
    assert config["dataset_overrides"] == {"ds01_diabetes": {"required_columns": ["Age"]}}
    assert plan.to_sdk()._validate().passed
    document["models"][0]["discover_datasets"] = True
    project = ESMLProject(LakeSettings.from_dict(document),
                          folder_catalog=SimpleNamespace(list_folders=lambda _: ()))
    discovered = project.create_pipeline(PipelineType.IN_2_GOLD, PipelineRequest("2026-09-14", "refs-only"),
                                          output=tmp_path / "empty-discovery")
    assert list(discovered.document["jobs"]) == ["merge"]


def test_parquet_is_an_explicit_compatible_output_choice(tmp_path):
    document = settings()
    document["models"][0]["table_format"] = "parquet"
    plan = ESMLProject(LakeSettings.from_dict(document)).create_pipeline(
        PipelineType.IN_2_GOLD, PipelineRequest("2026-09-14", "parquet"), output=tmp_path / "job")
    assert plan.manifest["table_format"] == plan.manifest["aml_table_format"] == "parquet"


@pytest.mark.parametrize("format", ["csv", "xlsx", "raw", None])
def test_strict_gold_rejects_raw_formats_before_exposing_training_inputs(tmp_path, format):
    from azure_esml.domain_layer.runtime import _gold_source
    with pytest.raises(ValueError, match="Delta or Parquet"):
        _gold_source({"require_gold": True}, tmp_path, {"format": format})
