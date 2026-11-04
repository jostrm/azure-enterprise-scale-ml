"""Local producer-qualified shareback, immutable snapshots and metadata-only bindings."""

from pathlib import Path
import shutil
from uuid import uuid4

import pandas as pd
import pytest

from azure_esml.domain_layer.shareback import SilverShareback
from azure_esml.domain_layer.shared_lake import SharedLake
from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import sha256
from ml_model_factory.lake import local_key_path
from ml_model_factory.lake_flow import file_inventory, finish, verified_manifest


@pytest.fixture
def workdir():
    parent = Path.cwd() / ".shareback-tests"
    path = parent / uuid4().hex[:12]
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


@pytest.fixture
def shareback(workdir):
    return SilverShareback(workdir / "lake", SharedLake("factory1", "dev"))


def producer(shareback, project="003", version="v1", value=3, *, stage="silver",
             table_relative="silver", table_format="parquet", key=None):
    key = key or shareback.layout.project(project, "example", version)
    path = local_key_path(shareback.root, key)
    table = path.joinpath(*table_relative.split("/"))
    table.mkdir(parents=True)
    frame = pd.DataFrame({"id": [1], "value": [value]})
    if table_format == "delta":
        from azure_esml.base_layer.tables import write_table
        output = write_table(frame, table, format="delta")
    else:
        frame.to_parquet(table / "data.parquet", index=False)
        output = {"sha256": sha256(table / "data.parquet"), "rows": 1, "columns": ["id", "value"]}
    write_json(table / "lineage.json", {
        "schema": "azure-esml.runtime/v1", "operation": "in2silver", "medallion_stage": stage,
        "tags": {"aifactory": "factory1", "project": project, "environment": "dev",
                 "pipeline_id": "silver-clean", "pipeline_version": "v1"},
        "source_fingerprint": "a" * 64, "output": output,
    })
    finish(path, {"kind": "project-dataset", "project": project, "environment": "dev",
                  "aifactory": "factory1", "dataset": "example", "version": version})
    return key, path, table


def publish(shareback, source, **options):
    return shareback.publish(**{
        "dataset": "example", "producer_project": "003", "variation": "clean", "version": "v1",
        "source_key": source, "owner": "data-team", "allowed_projects": ["003", "004"],
        **options,
    })


def resolve(shareback, **options):
    return shareback.resolve(**{
        "dataset": "example", "producer_project": "003", "variation": "clean", "version": "v1",
        "consumer_project": "004", **options,
    })


def recommit(path):
    manifest = load_json(path / "_SUCCESS.json")
    manifest.pop("files")
    finish(path, manifest)


def test_two_producers_same_variation_multiple_versions_select_exact_table(shareback):
    expected = {}
    for project, version, value in [("003", "v1", 31), ("003", "v2", 32), ("004", "v1", 41)]:
        key, _, _ = producer(shareback, project, version, value)
        product = publish(shareback, key, producer_project=project, version=version)
        assert f"/producers/project{project}/variations/clean/versions/{version}" in product["key"]
        for consumer in ("003", "004"):
            resolved = resolve(shareback, producer_project=project, version=version, consumer_project=consumer)
            assert resolved["table_key"] == key + "/silver"
            assert pd.read_parquet(local_key_path(shareback.root, resolved["table_key"]) / "data.parquet")["value"].item() == value
        expected[project, version] = value
    products = shareback.list_variations("example", consumer_project="004")
    assert {(item["producer_project"], item["version"]) for item in products} == set(expected)
    assert not any(path.name.lower() == "latest" for path in shareback.root.rglob("*"))
    with pytest.raises(FileNotFoundError):
        resolve(shareback, version="v3")


def test_reference_publish_and_onboard_write_only_metadata(shareback):
    key, path, _ = producer(shareback)
    before = file_inventory(path)
    published = publish(shareback, key)
    assert publish(shareback, key)["reused"]
    product_path = local_key_path(shareback.root, published["key"])
    assert {p.name for p in product_path.iterdir()} == {"contract.json", "_SUCCESS.json"}
    assert published["materialization"] == "metadata-only"
    assert "ACL" in published["access"] and "vacuum" in published["retention"]
    binding = shareback.onboard_reference("example", "003", "clean", "v1",
                                         consumer_project="004", consumer_version="selected1")
    consumer = local_key_path(shareback.root, binding["key"])
    assert {p.name for p in consumer.iterdir()} == {"silver-binding.json", "_SUCCESS.json"}
    metadata = load_json(consumer / "silver-binding.json")
    assert metadata["source_key"] == key
    assert metadata["table_key"] == key + "/silver"
    assert not (consumer / "in").exists()
    assert not list(consumer.rglob("*.parquet"))
    assert file_inventory(path) == before
    assert shareback.onboard_reference("example", "003", "clean", "v1",
                                      consumer_project="004", consumer_version="selected1")["reused"]
    assert shareback.reference("example", "003", "clean", "v1", consumer_project="004")["table_key"] == key + "/silver"


def test_nested_runtime_output_requires_explicit_relative_table(shareback):
    key = shareback.layout.use_case("003", "model") + "/training/runs/run1"
    key, _, _ = producer(shareback, key=key, table_relative="data/example/silver")
    publish(shareback, key, table_relative="data/example/silver")
    assert resolve(shareback)["table_key"] == key + "/data/example/silver"


def test_copy_is_explicit_exact_and_survives_producer_deletion(shareback):
    key, path, table = producer(shareback)
    inventory = file_inventory(table)
    published = publish(shareback, key, mode="copy")
    copied = local_key_path(shareback.root, published["key"]) / "silver"
    assert file_inventory(copied) == inventory
    shutil.rmtree(path)
    resolved = resolve(shareback)
    assert resolved["table_key"] == published["key"] + "/silver"
    assert pd.read_parquet(copied / "data.parquet")["value"].item() == 3


@pytest.mark.parametrize("mutation", ["delete", "file", "manifest"])
def test_reference_fails_on_missing_or_changed_producer(shareback, mutation):
    key, path, table = producer(shareback)
    publish(shareback, key)
    if mutation == "delete":
        shutil.rmtree(path)
    elif mutation == "file":
        (table / "data.parquet").write_bytes(b"changed")
    else:
        manifest = load_json(path / "_SUCCESS.json")
        manifest["extra"] = "changed"
        write_json(path / "_SUCCESS.json", manifest)
    with pytest.raises((ValueError, FileNotFoundError)):
        resolve(shareback)


def test_allowed_projects_checked_before_accessing_producer(shareback, monkeypatch):
    key, path, _ = producer(shareback)
    publish(shareback, key, allowed_projects=["003"])
    shutil.rmtree(path)
    with pytest.raises(ValueError, match="not approved"):
        resolve(shareback)
    assert shareback.list_variations("example", consumer_project="004") == []
    with pytest.raises(ValueError, match="not approved"):
        resolve(shareback, consumer_project="999")


@pytest.mark.parametrize("changed", [
    {"producer_project": "004"}, {"producer_project": "3"}, {"producer_project": "project003"},
    {"source_key": "mlops/v1/master/environments/dev/datasets/example/versions/v1"},
    {"source_key": "mlops/v1/projects/project003/environments/prod/datasets/example/versions/v1"},
    {"source_key": "../outside"}, {"table_relative": "../gold"},
    {"table_relative": "/silver"}, {"table_relative": "silver\\child"}, {"table_relative": "CON"},
    {"variation": "../clean"}, {"variation": "NUL"}, {"version": "latest"}, {"version": "0"},
    {"owner": ""}, {"allowed_projects": []}, {"allowed_projects": ["1"]},
    {"allowed_projects": ["003", "003"]}, {"allowed_projects": ["foo"]}, {"mode": "foo"},
])
def test_invalid_publish_selection_never_writes_product(shareback, changed):
    key, _, _ = producer(shareback)
    with pytest.raises(ValueError):
        publish(shareback, key, **changed)
    assert not (shareback.root / "mlops" / "v1" / "master").exists()


@pytest.mark.parametrize("change,match", [
    ({"medallion_stage": "gold"}, "silver medallion"),
    ({"medallion_stage": "bronze"}, "silver medallion"),
    ({"operation": "merge"}, "silver medallion"),
    ({"source_fingerprint": "invalid"}, "fingerprint"),
    ({"table_format": "csv"}, "format"),
    ({"tags": {"aifactory": "factory1", "project": "004", "environment": "dev"}}, "scope"),
])
def test_lineage_rejects_gold_wrong_scope_hash_or_format(shareback, change, match):
    key, path, table = producer(shareback)
    lineage = load_json(table / "lineage.json")
    lineage.update(change)
    write_json(table / "lineage.json", lineage)
    recommit(path)
    with pytest.raises(ValueError, match=match):
        publish(shareback, key)


def test_missing_completion_and_missing_lineage_rejected(shareback):
    key, path, table = producer(shareback)
    marker = (path / "_SUCCESS.json").read_bytes()
    (path / "_SUCCESS.json").unlink()
    with pytest.raises(FileNotFoundError):
        publish(shareback, key)
    (path / "_SUCCESS.json").write_bytes(marker)
    (table / "lineage.json").unlink()
    recommit(path)
    with pytest.raises(FileNotFoundError):
        publish(shareback, key)


def test_product_scope_tampering_even_with_recomputed_inventory_is_rejected(shareback):
    key, _, _ = producer(shareback)
    product = publish(shareback, key)
    path = local_key_path(shareback.root, product["key"])
    manifest = load_json(path / "_SUCCESS.json")
    manifest["producer_project"] = "004"
    write_json(path / "_SUCCESS.json", manifest)
    with pytest.raises(ValueError, match="scope"):
        resolve(shareback)


def test_product_approval_tampering_is_rejected(shareback):
    key, _, _ = producer(shareback)
    product = publish(shareback, key, allowed_projects=["003"])
    path = local_key_path(shareback.root, product["key"])
    contract = load_json(path / "contract.json")
    contract["allowed_projects"].append("004")
    write_json(path / "contract.json", contract)
    with pytest.raises(ValueError, match="files changed"):
        resolve(shareback)


def test_immutable_product_and_consumer_selection(shareback):
    first, _, _ = producer(shareback)
    second, _, _ = producer(shareback, version="v2", value=99)
    publish(shareback, first)
    with pytest.raises(ValueError, match="Immutable"):
        publish(shareback, second)
    publish(shareback, second, version="v2")
    shareback.onboard_reference("example", "003", "clean", "v1", consumer_project="004", consumer_version="v1")
    with pytest.raises(ValueError, match="Immutable"):
        shareback.onboard_reference("example", "003", "clean", "v2", consumer_project="004", consumer_version="v1")


def test_copy_rolls_back_if_table_changes_during_capture(shareback, monkeypatch):
    key, _, _ = producer(shareback)
    copy = shutil.copy2

    def changed(source, destination, *args, **kwargs):
        result = copy(source, destination, *args, **kwargs)
        if Path(destination).suffix == ".parquet":
            Path(destination).write_bytes(b"corrupt")
        return result

    monkeypatch.setattr("azure_esml.domain_layer.lake_ingestion.shutil.copy2", changed)
    with pytest.raises(ValueError, match="changed"):
        publish(shareback, key, mode="copy")
    assert not local_key_path(shareback.root, shareback.product_key("example", "003", "clean", "v1")).exists()
    assert not list(shareback.root.rglob("*.lock"))
    assert not list(shareback.root.rglob(".publishing-*"))


def test_fresh_delta_reference_pins_snapshot_and_copy_preserves_log(shareback):
    pytest.importorskip("deltalake", reason="Real Delta verification requires the optional deltalake dependency")
    from azure_esml.base_layer.tables import read_table

    key, path, table = producer(shareback, table_format="delta")
    published = publish(shareback, key)
    assert published["format"] == "delta" and published["delta_version"] == 0
    assert (table / "_delta_log").is_dir()
    resolved = resolve(shareback)
    frame, metadata = read_table(local_key_path(shareback.root, resolved["table_key"]),
                                 version=resolved["delta_version"])
    assert frame["value"].item() == 3 and metadata["delta_version"] == 0
    copied = publish(shareback, key, variation="copied", mode="copy")
    copy_path = local_key_path(shareback.root, copied["key"]) / "silver"
    assert file_inventory(copy_path) == file_inventory(table)
    shutil.rmtree(path)
    result = resolve(shareback, variation="copied")
    assert read_table(local_key_path(shareback.root, result["table_key"]), version=0)[0]["value"].item() == 3
    verified_manifest(local_key_path(shareback.root, copied["key"]))


def test_runtime_silver_can_be_shared_but_gold_cannot(shareback, workdir):
    from azure_esml.domain_layer.runtime import TabularDataSteps

    config = {
        "scenario": {"name": "silver-example", "task": "regression", "target": "value",
                     "features": ["id"], "dataset": {"provider": "lake", "kind": "dataset"},
                     "custom": {"algorithm": "ridge"}, "quality": {"max_rmse": 1}},
        "table_format": "parquet",
        "tags": {"aifactory": "factory1", "project": "003", "environment": "dev"},
        "dataset": {"format": "csv", "required_columns": ["id", "value"]},
    }
    source = workdir / "source.csv"
    source.write_bytes(b"id,value\n1,10\n2,20\n")
    key = shareback.layout.project("003", "example", "runtime1")
    path = local_key_path(shareback.root, key)
    steps = TabularDataSteps(config)
    steps.convert("in2silver", {"example": source}, path / "silver")
    finish(path, {"kind": "runtime-source", "dataset": "example"})
    publish(shareback, key)
    assert resolve(shareback)["format"] == "parquet"
    gold_key = shareback.layout.project("003", "example", "gold1")
    gold_root = local_key_path(shareback.root, gold_key)
    steps.merge({"example": path / "silver"}, gold_root / "silver")
    finish(gold_root, {"kind": "runtime-source", "dataset": "example"})
    with pytest.raises(ValueError, match="silver medallion"):
        publish(shareback, gold_key, version="gold1")


def test_list_validates_approved_product_hashes(shareback):
    key, _, table = producer(shareback)
    publish(shareback, key)
    (table / "data.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="files changed"):
        shareback.list_variations("example", consumer_project="004")


def test_csv_payload_is_not_silver_even_with_silver_lineage(shareback):
    key, path, table = producer(shareback)
    (table / "data.parquet").unlink()
    (table / "data.csv").write_bytes(b"id,value\n1,3\n")
    recommit(path)
    with pytest.raises(ValueError, match="CSV|parquet"):
        publish(shareback, key)


def test_recommitted_producer_does_not_retarget_existing_product(shareback):
    key, path, table = producer(shareback)
    publish(shareback, key)
    pd.DataFrame({"id": [1], "value": [99]}).to_parquet(table / "data.parquet", index=False)
    recommit(path)
    with pytest.raises(ValueError, match="manifest changed"):
        resolve(shareback)


def test_reference_does_not_materialize_a_pandas_frame(shareback, monkeypatch):
    key, _, _ = producer(shareback)

    def no_read(*args, **kwargs):
        raise AssertionError("Sharing must inspect metadata, not materialize a pandas frame")

    monkeypatch.setattr("azure_esml.base_layer.tables.read_table", no_read)
    monkeypatch.setattr(pd, "read_parquet", no_read)
    publish(shareback, key)
    resolve(shareback)
