"""Real, local Delta/parquet snapshots; no cloud credentials or services."""

import builtins
from datetime import date
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pytest
import yaml
from deltalake import DeltaTable, write_deltalake

from azure_esml.base_layer import tables
from azure_esml.base_layer.tables import (
    ITableStore, PortableTableStore, read_table, table_info, write_table,
)


@pytest.fixture
def workdir(monkeypatch):
    root = Path.cwd() / ".table-test-artifacts"
    path = root / uuid4().hex
    path.mkdir(parents=True)
    for variable in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(variable, str(path))
    yield path
    shutil.rmtree(path)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


def _save_metadata(path, metadata):
    (path / "_table.json").write_text(json.dumps(metadata), encoding="utf-8")


@pytest.mark.parametrize("format", ["delta", "parquet"])
def test_real_roundtrip_preserves_csv_labels_values_and_not_index(workdir, format):
    frame = pd.read_csv(StringIO("feature,label,category\n1.2,0,cat\n,1,dog\n3.4,0,cat\n"))
    frame.index = pd.Index([20, 40, 60], name="not_a_feature")
    destination = workdir / format
    metadata = write_table(frame, destination, format=format)
    result, inspected = read_table(destination)
    pd.testing.assert_frame_equal(result, frame.reset_index(drop=True))
    assert metadata == inspected == table_info(destination)
    assert metadata["schema"] == "azure-esml.table/v1"
    assert metadata["format"] == format
    assert metadata["row_count"] == 3
    assert metadata["columns"] == ["feature", "label", "category"]
    assert "not_a_feature" not in metadata["dtypes"]
    assert len(metadata["data_fingerprint"]) == 64
    assert "_table.json" not in metadata["files"]
    assert json.loads((destination / "_table.json").read_text()) == metadata
    if format == "delta":
        delta = DeltaTable(str(destination), version=0)
        assert delta.version() == metadata["delta_version"] == 0
        assert delta.protocol().min_reader_version == 1
        assert delta.protocol().min_writer_version == 2
        assert metadata["protocol"] == {"min_reader_version": 1, "min_writer_version": 2}
        assert "_delta_log/00000000000000000000.json" in metadata["files"]
        descriptor = yaml.safe_load((destination / "MLTable").read_text())
        assert descriptor == {
            "type": "mltable",
            "paths": [{"folder": "./"}],
            "transformations": [{"read_delta_lake": {"version_as_of": 0}}],
        }
        assert "MLTable" not in metadata["files"]
        pd.testing.assert_frame_equal(delta.to_pandas(), result)
    else:
        assert metadata["delta_version"] is None
        assert metadata["protocol"] is None
        assert not (destination / "_delta_log").exists()
        assert "read_parquet" in (destination / "MLTable").read_text()
        pd.testing.assert_frame_equal(pd.read_parquet(destination / "data.parquet"), result)


@pytest.mark.parametrize("format", ["delta", "parquet"])
def test_nullable_scalars_dates_decimals_and_timestamps(workdir, format):
    frame = pd.DataFrame({
        "integer": pd.Series([1, None], dtype="Int64"),
        "boolean": pd.Series([True, None], dtype="boolean"),
        "string": pd.Series(["", None], dtype="string"),
        "floating": pd.Series([1.25, None], dtype="Float64"),
        "date": [date(2026, 1, 1), None],
        "amount": [Decimal("12.30"), None],
        "naive": pd.to_datetime(["2026-01-01T12:30:00.123456", None]),
        "aware": pd.to_datetime(["2026-01-01T12:30:00.123456", None]).tz_localize("Europe/Stockholm"),
    })
    destination = workdir / format
    metadata = write_table(frame, destination, format=format)
    result, inspected = read_table(destination)
    expected = frame.copy()
    expected["naive"] = expected["naive"].dt.tz_localize("UTC").dt.as_unit("us")
    expected["aware"] = expected["aware"].dt.tz_convert("UTC").dt.as_unit("us")
    pd.testing.assert_frame_equal(result, expected)
    assert inspected == metadata
    assert metadata["dtypes"]["naive"] == "timestamp[us, tz=UTC]"
    assert metadata["dtypes"]["aware"] == "timestamp[us, tz=UTC]"
    if format == "delta":
        assert DeltaTable(str(destination)).protocol().min_writer_version == 2


@pytest.mark.parametrize("format", ["delta", "parquet"])
def test_typed_empty_table_and_all_null_columns(workdir, format):
    for name, frame in {
        "empty": pd.DataFrame({"value": pd.Series([], dtype="int64")}),
        "nulls": pd.DataFrame({"value": pd.Series([None, None], dtype="string")}),
    }.items():
        path = workdir / name
        metadata = write_table(frame, path, format=format)
        actual, _ = read_table(path)
        pd.testing.assert_frame_equal(actual, frame)
        assert metadata["row_count"] == len(frame)


def test_historical_reads_apply_log_and_exclude_removed_parquet_files(workdir):
    path = workdir / "history"
    original = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
    metadata0 = write_table(original, path)
    initial_payloads = {name for name in metadata0["files"] if name.endswith(".parquet")}
    delta = DeltaTable(str(path))
    delta.update(new_values={"value": 99}, predicate="id = 1")
    assert delta.version() == 1
    expected = pd.DataFrame({"id": [1, 2], "value": [99, 20]})
    latest, metadata1 = read_table(path, version=1)
    pd.testing.assert_frame_equal(latest.sort_values("id").reset_index(drop=True), expected)
    assert metadata1["delta_version"] == 1
    assert not initial_payloads.intersection(metadata1["files"])
    assert all((path / name).is_file() for name in initial_payloads)
    pd.testing.assert_frame_equal(read_table(path, version=0)[0], original)
    historical, inspected = read_table(path)
    pd.testing.assert_frame_equal(historical, original)
    assert inspected == metadata0
    assert table_info(path, version=1) == metadata1
    assert metadata0["data_fingerprint"] != metadata1["data_fingerprint"]
    assert json.loads((path / "_table.json").read_text()) == metadata0
    descriptor = yaml.safe_load((path / "MLTable").read_text())
    assert descriptor["transformations"] == [{"read_delta_lake": {"version_as_of": 0}}]


def test_appending_does_not_change_default_pinned_snapshot(workdir):
    path = workdir / "appended"
    original = pd.DataFrame({"id": [1, 2]})
    metadata = write_table(original, path)
    write_deltalake(path, pa.table({"id": [3]}), mode="append")
    pd.testing.assert_frame_equal(read_table(path)[0], original)
    assert table_info(path) == metadata
    latest, info = read_table(path, version=1)
    assert sorted(latest["id"]) == [1, 2, 3]
    assert info["row_count"] == 3


def test_external_delta_requires_pin_and_reports_actual_info(workdir):
    path = workdir / "external"
    write_deltalake(path, pa.table({"id": [1, 2]}))
    for inspect in (read_table, table_info):
        with pytest.raises(ValueError, match="explicit version"):
            inspect(path)
    frame, info = read_table(path, version=0)
    assert frame["id"].tolist() == [1, 2]
    assert info == table_info(path, version=0)
    assert info["row_count"] == 2
    assert info["delta_version"] == 0
    assert not (path / "_table.json").exists()


def test_legacy_parquet_folder_and_standalone_file(workdir):
    path = workdir / "legacy"
    path.mkdir()
    expected = pd.DataFrame({"x": [1, 2], "target": [0, 1]})
    expected.to_parquet(path / "data.parquet", index=False)
    (path / "lineage.json").write_text('{"stage":"not-a-base-layer-field"}')
    for source in (path, path / "data.parquet"):
        actual, metadata = read_table(source)
        pd.testing.assert_frame_equal(actual, expected)
        assert metadata["format"] == "parquet"
        assert metadata["row_count"] == 2
        assert set(metadata["files"]) == {"data.parquet"}
        assert "stage" not in metadata
    assert not (path / "_table.json").exists()


def test_external_partitioned_delta_snapshot(workdir):
    path = workdir / "partitioned"
    write_deltalake(
        path, pa.table({"id": [1, 2, 3], "group": ["a b", "a b", "c"]}),
        partition_by=["group"],
    )
    frame, info = read_table(path, version=0)
    assert sorted(frame["id"]) == [1, 2, 3]
    assert info["row_count"] == 3
    assert any("/" in name and not name.startswith("_delta_log") for name in info["files"])
    payload = next(path / name for name in info["files"] if not name.startswith("_delta_log"))
    with pytest.raises(ValueError, match="Delta table root"):
        read_table(payload)
    with pytest.raises(ValueError, match="Delta table root"):
        read_table(payload.parent)


@pytest.mark.parametrize("version", [-1, True, "latest", 1.5])
def test_invalid_versions_rejected(workdir, version):
    path = workdir / "versions"
    write_table(pd.DataFrame({"x": [1]}), path)
    for inspect in (read_table, table_info):
        with pytest.raises(ValueError, match="nonnegative integer"):
            inspect(path, version=version)


@pytest.mark.parametrize("format", ["delta", "parquet"])
def test_immutable_destination_and_invalid_format(workdir, format):
    frame = pd.DataFrame({"x": [1]})
    destination = workdir / "table"
    destination.mkdir()
    expected = write_table(frame, destination, format=format)
    with pytest.raises(ValueError, match="new or empty directory"):
        write_table(pd.DataFrame({"x": [2]}), destination, format=format)
    assert table_info(destination) == expected
    with pytest.raises(ValueError, match="new or empty directory|inside an existing Delta"):
        write_table(frame, destination / "_table.json", format=format)
    with pytest.raises(ValueError, match="format"):
        write_table(frame, workdir / "bad", format="csv")
    assert not (workdir / "bad").exists()


def test_delta_parts_and_nested_writes_are_rejected(workdir):
    path = workdir / "delta"
    metadata = write_table(pd.DataFrame({"id": [1]}), path)
    payload = next(path / name for name in metadata["files"] if name.endswith(".parquet"))
    with pytest.raises(ValueError, match="Delta table root"):
        read_table(payload)
    with pytest.raises(ValueError, match="inside an existing Delta"):
        write_table(pd.DataFrame({"id": [1]}), path / "child", format="parquet")
    assert not (path / "child").exists()


@pytest.mark.parametrize("format", ["delta", "parquet"])
@pytest.mark.parametrize("kind", ["data", "fingerprint", "row_count"])
def test_corrupt_payload_or_metadata_is_detected(workdir, format, kind):
    path = workdir / "corrupt"
    metadata = write_table(pd.DataFrame({"x": [1, 2]}), path, format=format)
    if kind == "data":
        name = next(name for name in metadata["files"] if name.endswith(".parquet"))
        with (path / name).open("ab") as stream:
            stream.write(b"corruption")
    else:
        metadata["data_fingerprint" if kind == "fingerprint" else kind] = (
            "0" * 64 if kind == "fingerprint" else 900
        )
        _save_metadata(path, metadata)
    for inspect in (read_table, table_info):
        with pytest.raises(ValueError, match="hash mismatch|fingerprint mismatch|row_count disagrees"):
            inspect(path)


def test_corrupt_log_is_checked_before_loading_delta(workdir):
    path = workdir / "corrupt-log"
    write_table(pd.DataFrame({"x": [1]}), path)
    (path / "_delta_log" / "00000000000000000000.json").write_text("not valid json")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_table(path)


def test_delta_log_payload_cannot_escape_the_local_root(workdir):
    path = workdir / "escape"
    metadata = write_table(pd.DataFrame({"x": [1]}), path)
    payload = next(path / name for name in metadata["files"] if name.endswith(".parquet"))
    shutil.copyfile(payload, workdir / "outside.parquet")
    log = path / "_delta_log" / "00000000000000000000.json"
    actions = [json.loads(line) for line in log.read_text().splitlines()]
    for action in actions:
        if "add" in action:
            action["add"]["path"] = "../outside.parquet"
    log.write_text("\n".join(json.dumps(action) for action in actions) + "\n")
    (path / "_table.json").unlink()
    with pytest.raises(ValueError, match="unsafe relative|local table root"):
        read_table(path, version=0)


def test_malformed_delta_log_is_never_read_as_parquet(workdir):
    path = workdir / "invalid-log"
    path.mkdir()
    pd.DataFrame({"x": [1]}).to_parquet(path / "data.parquet", index=False)
    (path / "_delta_log").write_text("not a transaction log directory")
    with pytest.raises(ValueError, match="transaction log"):
        read_table(path)


def test_missing_payload_and_incomplete_inventory_are_detected(workdir):
    path = workdir / "missing"
    metadata = write_table(pd.DataFrame({"x": [1]}), path)
    name = next(name for name in metadata["files"] if name.endswith(".parquet"))
    saved = metadata["files"].pop(name)
    metadata["data_fingerprint"] = tables._fingerprint(metadata["files"])
    _save_metadata(path, metadata)
    with pytest.raises(ValueError, match="inventory does not cover"):
        read_table(path)
    metadata["files"][name] = saved
    metadata["data_fingerprint"] = tables._fingerprint(metadata["files"])
    _save_metadata(path, metadata)
    (path / name).unlink()
    with pytest.raises(ValueError, match="payload is missing"):
        table_info(path)


@pytest.mark.parametrize("relative", [
    "../outside.parquet", "/outside.parquet", "C:/outside.parquet",
    "nested\\outside.parquet", "nested//data.parquet", "_table.json",
])
def test_unsafe_metadata_inventory_paths_rejected(workdir, relative):
    path = workdir / "unsafe"
    metadata = write_table(pd.DataFrame({"x": [1]}), path)
    metadata["files"] = {relative: "0" * 64}
    metadata["data_fingerprint"] = tables._fingerprint(metadata["files"])
    _save_metadata(path, metadata)
    with pytest.raises(ValueError, match="unsafe relative"):
        read_table(path)


@pytest.mark.parametrize("path", ["abfss://lake@account/path", "https://host/path", "../table"])
def test_nonlocal_and_traversing_paths_are_rejected(path):
    with pytest.raises(ValueError, match="local filesystem"):
        read_table(Path(path), version=0)
    with pytest.raises(ValueError, match="local filesystem"):
        write_table(pd.DataFrame({"x": [1]}), Path(path))


def test_symlink_root_and_payload_are_rejected(workdir):
    path = workdir / "table"
    metadata = write_table(pd.DataFrame({"x": [1]}), path)
    link = workdir / "link"
    try:
        link.symlink_to(path, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows developer mode or elevated privileges")
    for operation in (
        lambda: read_table(link),
        lambda: write_table(pd.DataFrame({"x": [1]}), link / "child"),
    ):
        with pytest.raises(ValueError, match="symlinks or junctions"):
            operation()
    payload = next(path / name for name in metadata["files"] if name.endswith(".parquet"))
    actual = workdir / "outside.parquet"
    payload.rename(actual)
    payload.symlink_to(actual)
    with pytest.raises(ValueError, match="symlinks or junctions"):
        read_table(path)


def test_junction_reparse_point_is_rejected_without_following(monkeypatch, workdir):
    path = workdir / "junction"
    path.mkdir()
    original = Path.lstat

    def lstat(candidate, *args, **kwargs):
        if candidate == path:
            return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(tables.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    with pytest.raises(ValueError, match="symlinks or junctions"):
        write_table(pd.DataFrame({"x": [1]}), path)


def test_no_silent_fallback_when_delta_dependency_is_missing(monkeypatch, workdir):
    original = builtins.__import__

    def without_delta(name, *args, **kwargs):
        if name == "deltalake":
            raise ImportError("dependency unavailable")
        return original(name, *args, **kwargs)

    path = workdir / "delta"
    write_table(pd.DataFrame({"x": [1]}), path)
    monkeypatch.setattr(builtins, "__import__", without_delta)
    with pytest.raises(ImportError, match=r"azure-esml-sdk\[delta\].*table_format='parquet'"):
        write_table(pd.DataFrame({"x": [1]}), workdir / "missing")
    assert not (workdir / "missing").exists()
    with pytest.raises(ImportError, match=r"azure-esml-sdk\[delta\]"):
        read_table(path)
    parquet = workdir / "explicit-parquet"
    write_table(pd.DataFrame({"x": [1]}), parquet, format="parquet")
    assert read_table(parquet)[0]["x"].tolist() == [1]


@pytest.mark.parametrize("frame", [
    pd.DataFrame([[1, 2]], columns=["same", "same"]),
    pd.DataFrame([[1]], columns=[0]),
    pd.DataFrame([[1]], columns=[""]),
    pd.DataFrame({"x": [[1, 2]]}),
    pd.DataFrame({"x": [{"a": 1}]}),
    pd.DataFrame({"x": [b"binary"]}),
    pd.DataFrame({"x": [None]}),
    pd.DataFrame({"x": pd.Categorical(["a"])}),
    pd.DataFrame(),
])
@pytest.mark.parametrize("format", ["delta", "parquet"])
def test_invalid_or_nonportable_schemas_fail_before_writing(workdir, frame, format):
    path = workdir / "bad-schema"
    with pytest.raises(ValueError, match="column|Unsupported table type|scalar"):
        write_table(frame, path, format=format)
    assert not path.exists()


@pytest.mark.parametrize("name", ["has space", "a,b", "a=b", "a(b)", "a{b}", "a\tb", "a\nb", "a;b"])
def test_delta_names_that_need_column_mapping_are_rejected(workdir, name):
    with pytest.raises(ValueError, match="without column mapping"):
        write_table(pd.DataFrame({name: [1]}), workdir / "invalid")
    write_table(pd.DataFrame({name: [1]}), workdir / "parquet", format="parquet")


def test_case_insensitive_delta_duplicates_rejected(workdir):
    with pytest.raises(ValueError, match="unique"):
        write_table(pd.DataFrame({"x": [1], "X": [2]}), workdir / "case")


@pytest.mark.parametrize("frame", [
    pd.DataFrame({"x": pd.to_datetime(["2026-01-01T00:00:00.000000001"])}),
    pd.DataFrame({"x": pd.Series([2**64 - 1], dtype="uint64")}),
])
def test_unsafe_casts_do_not_silently_lose_values(workdir, frame):
    with pytest.raises(ValueError, match="safely represented"):
        write_table(frame, workdir / "lossy")
    assert not (workdir / "lossy").exists()


def test_external_timestamp_ntz_protocol_is_rejected(workdir):
    path = workdir / "timestamp-ntz"
    frame = pd.DataFrame({"when": pd.to_datetime(["2026-01-01"])})
    write_deltalake(path, pa.Table.from_pandas(frame, preserve_index=False))
    assert DeltaTable(str(path)).protocol().min_writer_version > 2
    with pytest.raises(ValueError, match="Unsupported Delta protocol"):
        read_table(path, version=0)


@pytest.mark.parametrize("configuration,features", [
    ({"delta.columnMapping.mode": "name"}, None),
    ({"delta.enableDeletionVectors": "true"}, None),
    ({"delta.checkpointPolicy": "v2"}, None),
    ({}, ["timestampNtz"]),
])
def test_disallowed_features_rejected_even_if_protocol_numbers_look_classic(configuration, features):
    fake = SimpleNamespace(
        protocol=lambda: SimpleNamespace(
            min_reader_version=1, min_writer_version=2,
            reader_features=None, writer_features=features,
        ),
        metadata=lambda: SimpleNamespace(configuration=configuration),
    )
    with pytest.raises(ValueError, match="Unsupported Delta protocol"):
        tables._protocol(fake)


def test_writer_does_not_publish_metadata_if_engine_upgrades_protocol(monkeypatch, workdir):
    def upgraded_writer(path, data, **kwargs):
        write_deltalake(path, data, mode="error", configuration={"delta.minWriterVersion": "3"})

    monkeypatch.setattr(tables, "_delta", lambda: (DeltaTable, upgraded_writer))
    path = workdir / "upgraded"
    with pytest.raises(ValueError, match="Unsupported Delta protocol"):
        write_table(pd.DataFrame({"x": [1]}), path)
    assert DeltaTable(str(path)).protocol().min_writer_version == 3
    assert not (path / "_table.json").exists()


def test_metadata_is_published_only_after_payload_validation(monkeypatch, workdir):
    path = workdir / "publish-last"
    original = PortableTableStore.table_info

    def inspect(store, destination, **kwargs):
        assert (destination / "_delta_log" / "00000000000000000000.json").is_file()
        assert list(destination.glob("*.parquet"))
        assert not (destination / "_table.json").exists()
        return original(store, destination, **kwargs)

    monkeypatch.setattr(PortableTableStore, "table_info", inspect)
    metadata = write_table(pd.DataFrame({"x": [1]}), path)
    assert json.loads((path / "_table.json").read_text()) == metadata


def test_marker_format_must_match_storage(workdir):
    path = workdir / "mismatch"
    metadata = write_table(pd.DataFrame({"x": [1]}), path)
    metadata.update(format="parquet", delta_version=None)
    _save_metadata(path, metadata)
    with pytest.raises(ValueError, match="format disagrees"):
        read_table(path)


def test_parquet_has_no_delta_version_and_csv_is_not_implicitly_loaded(workdir):
    path = workdir / "parquet"
    write_table(pd.DataFrame({"x": [1]}), path, format="parquet")
    with pytest.raises(ValueError, match="cannot be used to read parquet"):
        read_table(path, version=0)
    csv = workdir / "source.csv"
    csv.write_text("x\n1\n")
    with pytest.raises(ValueError, match="CSV is not supported"):
        read_table(csv)


def test_object_oriented_store_matches_module_api(workdir):
    store = PortableTableStore()
    assert isinstance(store, ITableStore)
    metadata = store.write_table(pd.DataFrame({"x": [1]}), workdir / "table")
    assert store.table_info(workdir / "table") == metadata
    assert store.read_table(workdir / "table")[1] == metadata
