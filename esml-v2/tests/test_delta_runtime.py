"""Real Delta medallion execution and portable gold-derived model boundaries."""

from copy import deepcopy
from pathlib import Path

from deltalake import DeltaTable, write_deltalake
import pandas as pd
import pyarrow as pa
import pytest
import yaml

from azure_esml.base_layer.tables import read_table
from azure_esml.domain_layer.runtime import read_tabular, run_operation
from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import sha256
from ml_model_factory.lake_flow import verified_manifest
from test_esml_runtime import config, forecast_config, forecast_records, records, workdir


def defaults(task="classification"):
    cfg = forecast_config() if task == "forecasting" else config(task)
    cfg.pop("table_format")
    cfg.pop("bronze_mode")
    cfg["dataset"]["format"] = "csv"
    return cfg


def gold_snapshot(workdir, cfg):
    source = workdir / "original.csv"
    records().to_csv(source, index=False)
    silver, gold = workdir / "silver", workdir / "gold"
    run_operation("in2silver", cfg, silver, inputs={"original": source})
    run_operation("merge", cfg, gold, inputs={"silver": silver})
    return source, silver, gold


@pytest.mark.parametrize("format_", ["delta", "parquet"])
def test_silver_and_gold_outputs_are_verified_committed_units(workdir, format_):
    cfg = defaults()
    cfg["table_format"] = format_
    _, silver, gold = gold_snapshot(workdir, cfg)
    for stage, path in (("silver", silver), ("gold", gold)):
        marker = verified_manifest(path)
        assert marker["kind"] == "medallion-table" and marker["state"] == "committed"
        assert marker["medallion_stage"] == stage
        assert {key: marker[key] for key in cfg["request"]["scope"]} == cfg["request"]["scope"]
        assert marker["use_case"] == cfg["scenario"]["name"]
        assert marker["files"]["lineage.json"] == sha256(path / "lineage.json")
        assert marker["files"]["_table.json"] == sha256(path / "_table.json")
        assert marker["files"]["MLTable"] == sha256(path / "MLTable")
        assert "_SUCCESS.json" not in marker["files"]
        actual, metadata = read_table(path)
        assert len(actual) == len(records())
        assert "_SUCCESS.json" not in metadata["files"]
        assert "lineage.json" not in metadata["files"]
    lineage = load_json(silver / "lineage.json")
    write_json(silver / "lineage.json", {**lineage, "transformation": "modified-after-completion"})
    with pytest.raises(ValueError, match="files changed"):
        verified_manifest(silver)


@pytest.mark.parametrize("task", ["classification", "regression", "forecasting"])
@pytest.mark.parametrize("dataset_count", [1, 2])
def test_default_raw_delta_gold_training_evaluation_inference(workdir, task, dataset_count):
    cfg = defaults(task)
    frame = forecast_records() if task == "forecasting" else records(task)
    silvers = {}
    for index in range(dataset_count):
        source = workdir / f"original-{index}.csv"
        frame.iloc[index * len(frame) // dataset_count:(index + 1) * len(frame) // dataset_count].to_csv(
            source, index=False,
        )
        bronze, silver = workdir / f"bronze-{index}", workdir / f"silver-{index}"
        raw = run_operation("in2bronze", cfg, bronze, inputs={"source": source})
        assert (bronze / source.name).read_bytes() == source.read_bytes()
        assert raw["output"]["format"] == "raw"
        assert raw["output"]["bytes"] == source.stat().st_size
        assert not list(bronze.rglob("*.parquet"))
        converted = run_operation("bronze2silver", cfg, silver, inputs={"bronze": bronze})
        assert converted["medallion_stage"] == "silver"
        assert converted["output"]["format"] == "delta"
        assert converted["output"]["delta_version"] == 0
        assert (silver / "_delta_log").is_dir()
        assert "read_delta_lake" in (silver / "MLTable").read_text(encoding="utf-8")
        silvers[f"source-{index}"] = silver
    gold, prepared, model = workdir / "gold", workdir / "prepared", workdir / "model"
    merged = run_operation("merge", cfg, gold, inputs=silvers)
    assert merged["medallion_stage"] == "gold"
    assert merged["scope"] == cfg["request"]["scope"]
    assert merged["transformation"] == "concat"
    assert (gold / "_delta_log").is_dir()
    assert "read_delta_lake" in (gold / "MLTable").read_text(encoding="utf-8")
    gold_frame, metadata = read_table(gold)
    assert len(gold_frame) == len(frame)
    outputs = {name: workdir / name for name in ("train", "validation", "test")}
    manifest = run_operation("split", cfg, prepared, inputs={"gold": gold}, **outputs)
    binding = load_json(prepared / "gold-source.json")
    assert manifest["gold_source"] == binding
    assert binding["input_format"] == "delta" and binding["delta_version"] == 0
    assert binding["input_fingerprint"] == metadata["data_fingerprint"]
    assert binding["model_input_format"] == "parquet"
    assert binding["medallion_stage"] == "gold" and binding["legacy_adapter"] is False
    assert ".esml-projection-" not in str(binding)
    assert sum(manifest["split_rows"].values()) == len(frame)
    for name, destination in outputs.items():
        actual, table_metadata = read_table(destination)
        expected = pd.read_parquet(prepared / name / "data.parquet")
        if task == "forecasting":
            for rows in (actual, expected):
                rows["date"] = pd.to_datetime(rows["date"], utc=True).dt.tz_localize(None).astype("datetime64[ns]")
        pd.testing.assert_frame_equal(actual, expected)
        assert sha256(prepared / name / "data.parquet") == manifest["split_sha256"][name]
        assert manifest["aml_tables"][name] == table_metadata
        assert table_metadata["format"] == "delta" and table_metadata["delta_version"] == 0
        assert (destination / "_delta_log").is_dir()
        descriptor = yaml.safe_load((destination / "MLTable").read_text(encoding="utf-8"))
        assert descriptor["paths"] == [{"folder": "./"}]
        assert descriptor["transformations"] == [{"read_delta_lake": {"version_as_of": 0}}]
        assert not (prepared / name / "_delta_log").exists()
    run_operation("training_manual", cfg, model, prepared=prepared)
    gold.rename(workdir / "relocated-gold")
    run_operation("evaluate", cfg, workdir / "evaluation", prepared=prepared, model=model)
    assert load_json(workdir / "evaluation" / "quality-gate.json")["passed"] is True
    future = pd.read_parquet(prepared / "test" / "data.parquet").drop(columns="target")
    future["request_id"] = [f"row-{index}" for index in range(len(future))]
    source = workdir / "future.parquet"
    future.to_parquet(source, index=False)
    inference_cfg = deepcopy(cfg)
    inference_cfg["request"]["pipeline_type"] = "IN_2_GOLD_INFERENCE"
    inference_cfg["dataset"] = {"format": "parquet"}
    silver, gold = workdir / "inference-silver", workdir / "inference-gold"
    run_operation("in2silver", inference_cfg, silver, inputs={"source": source})
    run_operation("merge", inference_cfg, gold, inputs={"silver": silver})
    assert "target" not in read_tabular(gold)[0]
    result = run_operation("inference", inference_cfg, workdir / "predictions", inputs={"gold": gold}, model=model)
    predicted = pd.read_parquet(workdir / "predictions" / "predictions.parquet")
    assert predicted["request_id"].tolist() == future["request_id"].tolist()
    assert predicted["prediction"].notna().all()
    assert result["inputs"]["gold"]["format"] == "delta"
    assert result["inputs"]["gold"]["delta_version"] == 0


@pytest.mark.parametrize("extension,payload", [
    ("csv", b"\xef\xbb\xbfduplicate,duplicate\r\nnot-a-number,?\r\nx,y,z\r\n"),
    ("xlsx", b"opaque-xlsx-bytes-not-a-parseable-workbook\x00\xff"),
])
def test_raw_bronze_never_parses_validates_or_transforms(workdir, extension, payload):
    cfg = defaults()
    cfg["dataset"] = {"format": extension, "required_columns": ["missing"], "column_types": {"x": "float64"}}
    source = workdir / f"original.{extension}"
    source.write_bytes(payload)

    def forbidden(frame, context):
        pytest.fail("Raw bronze must not call consumer transformations")

    output = workdir / "bronze"
    lineage = run_operation("in2bronze", cfg, output, inputs={"source": source}, transformer=forbidden)
    assert (output / source.name).read_bytes() == payload
    assert lineage["learned_preprocessing"] is False
    assert lineage["transformation"] == "none"
    assert lineage["output"]["files"] == {source.name: sha256(source)}
    assert load_json(output / "bronze.json")["source_format"] == extension
    assert not list(output.rglob("*.parquet"))


def test_bronze_index_remembers_original_format_and_rejects_mutation(workdir):
    cfg = defaults()
    raw = workdir / "raw"
    raw.mkdir()
    (raw / "nested").mkdir()
    records().iloc[:90].to_csv(raw / "a.csv", index=False)
    records().iloc[90:].to_csv(raw / "nested" / "z.csv", index=False)
    cfg["dataset"]["file_pattern"] = "**/*.csv"
    bronze, silver = workdir / "bronze", workdir / "silver"
    run_operation("in2bronze", cfg, bronze, inputs={"source": raw})
    for source in raw.rglob("*.csv"):
        assert source.read_bytes() == (bronze / source.relative_to(raw)).read_bytes()
    cfg["dataset"] = {"format": "parquet"}
    run_operation("bronze2silver", cfg, silver, inputs={"bronze": bronze})
    assert len(read_table(silver)[0]) == len(records())
    (bronze / "a.csv").write_bytes(b"x,target\n1,0\n")
    with pytest.raises(ValueError, match="source index"):
        run_operation("bronze2silver", cfg, workdir / "mutated", inputs={"bronze": bronze})


def test_delta_reader_obeys_log_not_physical_parquet_discovery(workdir):
    table = workdir / "table"
    first = records().iloc[:40].reset_index(drop=True)
    latest = records().iloc[40:50].reset_index(drop=True)
    write_deltalake(str(table), pa.Table.from_pandas(first, preserve_index=False))
    write_deltalake(str(table), pa.Table.from_pandas(latest, preserve_index=False), mode="overwrite")
    assert len(list(table.glob("*.parquet"))) > 1
    with pytest.raises(ValueError, match="explicit version"):
        read_tabular(table)
    current, source = read_tabular(table, {"format": "parquet", "file_pattern": "**/*.parquet", "delta_version": 1})
    pd.testing.assert_frame_equal(current, latest)
    assert source["format"] == "delta" and source["delta_version"] == 1
    original, source = read_tabular(table, {"format": "delta", "delta_version": 0})
    pd.testing.assert_frame_equal(original, first)
    assert source["delta_version"] == 0
    with pytest.raises(ValueError, match="Delta table"):
        read_tabular(workdir / "plain.csv", {"delta_version": 0})
    with pytest.raises(ValueError, match="physical Parquet"):
        read_tabular(next(table.glob("*.parquet")))


def test_split_reads_the_gold_lineage_version_after_later_delta_commits(workdir):
    cfg = defaults()
    _, _, gold = gold_snapshot(workdir, cfg)
    original, metadata = read_table(gold)
    write_deltalake(str(gold), pa.Table.from_pandas(original.iloc[:12], preserve_index=False), mode="append")
    assert len(read_tabular(gold, {"delta_version": 1})[0]) == len(original) + 12
    manifest = run_operation("split", cfg, workdir / "prepared", inputs={"gold": gold})
    assert sum(manifest["split_rows"].values()) == len(original)
    assert manifest["gold_source"]["delta_version"] == 0
    assert manifest["gold_source"]["input_fingerprint"] == metadata["data_fingerprint"]
    cfg["gold_dataset"] = {"delta_version": 1}
    with pytest.raises(ValueError, match="fingerprint/version"):
        run_operation("split", cfg, workdir / "different-version", inputs={"gold": gold})


@pytest.mark.parametrize("version", [0, 1])
def test_merge_honors_selected_shared_silver_input_version(workdir, version):
    cfg = defaults()
    _, silver, _ = gold_snapshot(workdir, cfg)
    original, _ = read_table(silver)
    appended = original.iloc[:12]
    write_deltalake(str(silver), pa.Table.from_pandas(appended, preserve_index=False), mode="append")
    cfg["input_versions"] = {"original-dataset-name": version}
    gold = workdir / "selected-gold"
    lineage = run_operation("merge", cfg, gold, inputs={"original-dataset-name": silver})
    expected = original if version == 0 else pd.concat([original, appended], ignore_index=True)
    actual, metadata = read_table(gold)
    pd.testing.assert_frame_equal(
        actual.sort_values(["x", "category", "target"]).reset_index(drop=True),
        expected.sort_values(["x", "category", "target"]).reset_index(drop=True),
    )
    assert lineage["inputs"]["original-dataset-name"]["delta_version"] == version
    assert metadata["delta_version"] == 0
    assert lineage["medallion_stage"] == "gold"


def test_merge_rejects_conflicting_shared_silver_versions(workdir):
    cfg = defaults()
    _, silver, _ = gold_snapshot(workdir, cfg)
    cfg["input_versions"] = {"source": 1}
    cfg["dataset_overrides"] = {"source": {"delta_version": 0}}
    with pytest.raises(ValueError, match="disagrees with input_versions"):
        run_operation("merge", cfg, workdir / "conflicting", inputs={"source": silver})
    assert not (workdir / "conflicting").exists()


def test_shared_silver_merge_enforces_consumer_required_columns(workdir):
    cfg = defaults()
    _, silver, _ = gold_snapshot(workdir, cfg)
    cfg["input_versions"] = {"shared-customers": 0}
    cfg["dataset_overrides"] = {"shared-customers": {"required_columns": ["consumer_required_feature"]}}
    rejected = workdir / "rejected-gold"
    with pytest.raises(ValueError, match="Missing required columns.*consumer_required_feature"):
        run_operation("merge", cfg, rejected, inputs={"shared-customers": silver})
    assert not rejected.exists()
    cfg["dataset_overrides"]["shared-customers"]["required_columns"] = ["x", "category", "target"]
    accepted = workdir / "accepted-gold"
    run_operation("merge", cfg, accepted, inputs={"shared-customers": silver})
    assert verified_manifest(accepted)["medallion_stage"] == "gold"


def test_delta_gold_group_split_and_strict_join(workdir):
    cfg = defaults()
    cfg["scenario"]["split"]["group_column"] = "entity"
    frame = records().assign(entity=lambda rows: rows.index % 12)
    source = workdir / "source.csv"
    frame.to_csv(source, index=False)
    silver, gold = workdir / "silver", workdir / "gold"
    run_operation("in2silver", cfg, silver, inputs={"source": source})
    run_operation("merge", cfg, gold, inputs={"silver": silver})
    prepared = workdir / "prepared"
    run_operation("split", cfg, prepared, inputs={"gold": gold})
    groups = {name: set(pd.read_parquet(prepared / name / "data.parquet")["entity"])
              for name in ("train", "validation", "test")}
    assert not groups["train"] & groups["validation"]
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & groups["test"]
    cfg["merge"] = {"mode": "join", "on": ["entity"], "how": "left", "validate": "one_to_one"}
    with pytest.raises(pd.errors.MergeError, match="unique"):
        run_operation("merge", cfg, workdir / "duplicates", inputs={"silver": silver})


def test_raw_bronze_patterns_and_nonempty_sources_are_guarded(workdir):
    cfg = defaults()
    (workdir / "raw").mkdir()
    cfg["dataset"]["file_pattern"] = "../*.csv"
    with pytest.raises(ValueError, match="traversal"):
        run_operation("in2bronze", cfg, workdir / "unsafe", inputs={"source": workdir / "raw"})
    source = workdir / "empty.csv"
    source.write_bytes(b"")
    cfg["dataset"].pop("file_pattern")
    with pytest.raises(ValueError, match="nonempty source bytes"):
        run_operation("in2bronze", cfg, workdir / "empty", inputs={"source": source})


@pytest.mark.parametrize("selected", ["original", "silver", "renamed-silver"])
def test_split_requires_actual_gold_lineage_not_input_alias(workdir, selected):
    cfg = defaults()
    original, silver, gold = gold_snapshot(workdir, cfg)
    if selected == "renamed-silver":
        silver.rename(workdir / "looks-like-gold")
    path = {"original": original, "silver": silver, "renamed-silver": workdir / "looks-like-gold"}[selected]
    with pytest.raises(ValueError, match="gold artifact"):
        run_operation("split", cfg, workdir / "rejected", inputs={"gold": path})
    assert not (workdir / "rejected").exists()


def test_split_verifies_gold_hash_scope_scenario_and_inference_lineage(workdir):
    cfg = defaults()
    _, _, gold = gold_snapshot(workdir, cfg)
    original = load_json(gold / "lineage.json")
    for key, value, message in (
        ("scope", {"aifactory": "wrong", "project": "001", "environment": "dev"}, "scope"),
        ("scenario", {**cfg["scenario"], "name": "another-use-case"}, "scenario"),
        ("request", {**cfg["request"], "pipeline_type": "IN_2_GOLD_INFERENCE"}, "Inference gold"),
        ("output", {**original["output"], "fingerprint": "0" * 64}, "fingerprint"),
    ):
        write_json(gold / "lineage.json", {**original, key: value})
        with pytest.raises(ValueError, match=message):
            run_operation("split", cfg, workdir / f"bad-{key}", inputs={"gold": gold})
    write_json(gold / "lineage.json", original)
    active = Path(DeltaTable(str(gold)).file_uris()[0])
    active.write_bytes(b"corrupted parquet")
    with pytest.raises((ValueError, OSError, pa.ArrowInvalid)):
        run_operation("split", cfg, workdir / "corrupt-data", inputs={"gold": gold})


@pytest.mark.parametrize("change,message", [
    ("missing-binding", "gold-source"),
    ("binding-disagrees", "gold-source"),
    ("scope", "scope"),
    ("scenario", "scenario"),
    ("snapshot", "snapshot"),
    ("inference", "training snapshots"),
    ("projection", "manifest hash"),
])
def test_training_and_evaluation_reject_unbound_prepared_inputs(workdir, change, message):
    cfg = defaults()
    _, _, gold = gold_snapshot(workdir, cfg)
    prepared = workdir / "prepared"
    run_operation("split", cfg, prepared, inputs={"gold": gold})
    if change == "missing-binding":
        (prepared / "gold-source.json").unlink()
    elif change == "binding-disagrees":
        binding = load_json(prepared / "gold-source.json")
        write_json(prepared / "gold-source.json", {**binding, "delta_version": 7})
    elif change == "scope":
        cfg["request"]["scope"]["environment"] = cfg["tags"]["environment"] = "prod"
        cfg["tags"]["training_environment"] = "prod"
    elif change == "scenario":
        cfg["scenario"]["target"] = "different"
    elif change == "snapshot":
        cfg["request"]["snapshot_id"] = "different"
    elif change == "inference":
        cfg["request"]["pipeline_type"] = "GOLD_INFERENCE"
    else:
        path = prepared / "train" / "data.parquet"
        pd.read_parquet(path).iloc[:-1].to_parquet(path, index=False)
    for operation in ("training_manual", "evaluate"):
        with pytest.raises(ValueError, match=message):
            run_operation(operation, cfg, workdir / f"bad-{operation}", prepared=prepared, model=workdir / "model")


def test_explicit_parquet_and_legacy_split_adapter(workdir):
    cfg = defaults()
    cfg["table_format"] = "parquet"
    original, _, gold = gold_snapshot(workdir, cfg)
    assert (gold / "data.parquet").is_file()
    assert not (gold / "_delta_log").exists()
    prepared = workdir / "prepared"
    run_operation("split", cfg, prepared, inputs={"gold": gold})
    assert load_json(prepared / "gold-source.json")["input_format"] == "parquet"
    legacy = deepcopy(cfg)
    legacy["require_gold"] = False
    run_operation("split", legacy, workdir / "legacy", inputs={"gold": original})
    binding = load_json(workdir / "legacy" / "gold-source.json")
    assert binding["legacy_adapter"] is True and binding["medallion_stage"] == "legacy"
    with pytest.raises(ValueError, match="training snapshots"):
        run_operation("training_manual", cfg, workdir / "rejected-legacy", prepared=workdir / "legacy")


@pytest.mark.parametrize("gold_format,aml_format", [("delta", "parquet"), ("parquet", "delta")])
def test_external_aml_table_format_override_preserves_gold_bound_projection(workdir, gold_format, aml_format):
    cfg = defaults()
    cfg.update(table_format=gold_format, aml_table_format=aml_format)
    _, _, gold = gold_snapshot(workdir, cfg)
    prepared = workdir / "prepared"
    outputs = {name: workdir / name for name in ("train", "validation", "test")}
    manifest = run_operation("split", cfg, prepared, inputs={"gold": gold}, **outputs)
    assert manifest == load_json(prepared / "manifest.json")
    assert manifest["gold_source"] == load_json(prepared / "gold-source.json")
    assert manifest["gold_source"]["input_format"] == gold_format
    assert manifest["gold_source"]["model_input_format"] == "parquet"
    for name, destination in outputs.items():
        actual, metadata = read_table(destination)
        pd.testing.assert_frame_equal(actual, pd.read_parquet(prepared / name / "data.parquet"))
        assert metadata == manifest["aml_tables"][name]
        assert metadata["format"] == aml_format
        assert (destination / "_delta_log").exists() is (aml_format == "delta")
        descriptor = yaml.safe_load((destination / "MLTable").read_text(encoding="utf-8"))
        if aml_format == "delta":
            assert descriptor["transformations"] == [{"read_delta_lake": {"version_as_of": 0}}]
        else:
            assert descriptor["paths"] == [{"file": "./data.parquet"}]
            assert descriptor["transformations"] == [{"read_parquet": None}]
        assert sha256(prepared / name / "data.parquet") == manifest["split_sha256"][name]


def test_invalid_aml_table_format_rejected_before_split_outputs(workdir):
    cfg = defaults()
    _, _, gold = gold_snapshot(workdir, cfg)
    cfg["aml_table_format"] = "csv"
    outputs = {name: workdir / name for name in ("train", "validation", "test")}
    with pytest.raises(ValueError, match="aml_table_format"):
        run_operation("split", cfg, workdir / "prepared", inputs={"gold": gold}, **outputs)
    assert not (workdir / "prepared").exists()
    assert all(not path.exists() for path in outputs.values())


@pytest.mark.parametrize("field,value", [("table_format", "csv"), ("bronze_mode", "clean"), ("require_gold", "false")])
def test_invalid_storage_modes_fail_before_writing(workdir, field, value):
    cfg = defaults()
    cfg[field] = value
    source = workdir / "source.csv"
    records().to_csv(source, index=False)
    with pytest.raises(ValueError, match=field):
        run_operation("in2bronze", cfg, workdir / "output", inputs={"source": source})
    assert not (workdir / "output").exists()
