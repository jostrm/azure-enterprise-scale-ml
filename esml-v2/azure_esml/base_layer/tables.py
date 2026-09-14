"""Portable, version-pinned table IO on local filesystems and mounted folders."""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

if TYPE_CHECKING:
    from pandas import DataFrame


_SCHEMA = "azure-esml.table/v1"
_MARKER = "_table.json"
_CLASSIC_PROTOCOL = {"min_reader_version": 1, "min_writer_version": 2}
_LOG_FILE = re.compile(r"^(\d{20})(?:\.json|\.checkpoint(?:\.\d{10}\.\d{10})?\.parquet)$")
_PANDAS_NULLABLE = {
    "boolean", "string", "Int8", "Int16", "Int32", "Int64",
    "UInt8", "UInt16", "UInt32", "UInt64", "Float32", "Float64",
}


def _delta():
    try:
        from deltalake import DeltaTable, write_deltalake
    except ImportError as exc:
        raise ImportError(
            "Delta IO requires deltalake: install azure-esml-sdk[delta] "
            "or explicitly set table_format='parquet'."
        ) from exc
    return DeltaTable, write_deltalake


def _arrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportError("Table IO requires pyarrow; install azure-esml-sdk[delta].") from exc
    return pa, pq


def _no_link(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ValueError("Table paths must not contain symlinks or junctions")


def _local_path(path: Path) -> Path:
    text = os.fspath(path)
    if (
        "\x00" in text
        or (re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", text)
            and not re.match(r"^[A-Za-z]:[\\/]", text))
        or ".." in Path(text).parts
    ):
        raise ValueError("Table paths must be local filesystem paths without traversal")
    result = Path(os.path.abspath(text))
    for parent in (*reversed(result.parents), result):
        _no_link(parent)
    return result


def _check_tree(root: Path) -> None:
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            _no_link(Path(directory) / name)


def _payload(root: Path, relative: str) -> Path:
    decoded = unquote(relative) if isinstance(relative, str) else ""
    if (
        not isinstance(relative, str) or not relative
        or "\\" in relative or ":" in relative or "\x00" in relative
        or relative.startswith("/")
        or any(part in ("", ".", "..") for part in relative.split("/"))
        or "\\" in decoded or ":" in decoded or "\x00" in decoded
        or decoded.startswith("/")
        or any(part in (".", "..") for part in decoded.split("/"))
        or relative == _MARKER
    ):
        raise ValueError("Table inventory contains an unsafe relative payload path")
    path = root.joinpath(*PurePosixPath(relative).parts)
    for part in (path, *path.parents):
        _no_link(part)
        if part == root:
            break
    if not path.is_file():
        raise ValueError(f"Table payload is missing: {relative}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(files: dict) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _version(version: int | None) -> None:
    if version is not None and (type(version) is not int or version < 0):
        raise ValueError("Delta version must be an explicit nonnegative integer")


def _marker(root: Path) -> dict | None:
    path = root / _MARKER
    _no_link(path)
    if not path.exists():
        return None
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid _table.json metadata") from exc
    if not isinstance(metadata, dict) or metadata.get("schema") != _SCHEMA:
        raise ValueError("Unsupported _table.json schema")
    if metadata.get("format") not in ("delta", "parquet"):
        raise ValueError("Invalid _table.json format")
    if metadata["format"] == "delta":
        if metadata.get("delta_version") is None:
            raise ValueError("_table.json must pin a Delta version")
        _version(metadata["delta_version"])
    elif metadata.get("delta_version") is not None:
        raise ValueError("Parquet metadata cannot specify a Delta version")
    return metadata


def _verify_inventory(root: Path, metadata: dict) -> dict:
    files = metadata.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("_table.json must contain a payload hash inventory")
    for relative, expected in files.items():
        payload = _payload(root, relative)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Invalid payload SHA256 hash")
        if _sha256(payload) != expected:
            raise ValueError(f"Table payload hash mismatch: {relative}")
    if metadata.get("data_fingerprint") != _fingerprint(files):
        raise ValueError("Table data_fingerprint mismatch")
    return files


def _validate_columns(names: list[str], format: str) -> None:
    if not names or any(not isinstance(name, str) or not name or "\x00" in name for name in names):
        raise ValueError("Tables require nonempty string column names")
    if len(set(names)) != len(names):
        raise ValueError("Tables cannot contain duplicate column names")
    if format == "delta" and (
        len({name.casefold() for name in names}) != len(names)
        or any(re.search(r"[ ,;{}()\n\r\t=]", name) for name in names)
    ):
        raise ValueError("Delta column names must be unique and valid without column mapping")


def _primitive(pa, dtype) -> bool:
    return (
        pa.types.is_boolean(dtype) or pa.types.is_signed_integer(dtype)
        or pa.types.is_float32(dtype) or pa.types.is_float64(dtype)
        or pa.types.is_string(dtype) or pa.types.is_large_string(dtype)
        or pa.types.is_date32(dtype) or pa.types.is_timestamp(dtype)
        or pa.types.is_decimal128(dtype)
    )


def _from_frame(frame: DataFrame, format: str):
    import pandas as pd

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("write_table requires a pandas DataFrame")
    _validate_columns(list(frame.columns), format)
    pa, _ = _arrow()
    try:
        table = pa.Table.from_pandas(frame, preserve_index=False, safe=True)
    except (pa.ArrowException, TypeError) as exc:
        raise ValueError("Table values must have consistent supported scalar types") from exc
    fields = []
    for field in table.schema:
        dtype = field.type
        if pa.types.is_timestamp(dtype):
            dtype = pa.timestamp("us", tz="UTC")
        elif pa.types.is_unsigned_integer(dtype):
            dtype = pa.int64()
        elif pa.types.is_large_string(dtype):
            dtype = pa.string()
        if not _primitive(pa, dtype):
            raise ValueError(
                f"Unsupported table type for {field.name!r}: {field.type}; "
                "use typed scalar columns (including explicitly typed all-null columns)"
            )
        fields.append(pa.field(field.name, dtype, nullable=True))
    try:
        return table.cast(pa.schema(fields), safe=True)
    except pa.ArrowException as exc:
        raise ValueError(
            "Table values cannot be safely represented; timestamps require exact "
            "microsecond precision and unsigned integers must fit int64"
        ) from exc


def _protocol(table) -> dict:
    protocol = table.protocol()
    result = {
        "min_reader_version": protocol.min_reader_version,
        "min_writer_version": protocol.min_writer_version,
    }
    configuration = table.metadata().configuration
    if (
        result != _CLASSIC_PROTOCOL
        or getattr(protocol, "reader_features", None)
        or getattr(protocol, "writer_features", None)
        or configuration.get("delta.columnMapping.mode", "none") != "none"
        or str(configuration.get("delta.enableDeletionVectors", "false")).lower() != "false"
        or configuration.get("delta.checkpointPolicy", "classic") != "classic"
    ):
        raise ValueError(
            "Unsupported Delta protocol/features: require classic reader 1 / writer 2, "
            "without column mapping, deletion vectors, timestampNtz or v2 checkpoints"
        )
    return result


def _delta_inventory(root: Path, table, version: int) -> dict:
    files = {}
    for uri in table.file_uris():
        text = uri
        if text.startswith("file:"):
            parsed = urlsplit(text)
            if parsed.netloc:
                raise ValueError("Delta payload must stay within the local table root")
            text = url2pathname(parsed.path)
        candidate = Path(text)
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("Delta payload must stay within the local table root") from exc
        files[relative] = _sha256(_payload(root, relative))
    for path in sorted((root / "_delta_log").iterdir()):
        match = _LOG_FILE.fullmatch(path.name)
        if match and int(match[1]) <= version:
            relative = path.relative_to(root).as_posix()
            files[relative] = _sha256(_payload(root, relative))
    return dict(sorted(files.items()))


def _info(table, format: str, version: int | None, protocol: dict | None, files: dict) -> dict:
    return {
        "schema": _SCHEMA,
        "format": format,
        "delta_version": version,
        "row_count": table.num_rows,
        "columns": table.column_names,
        "dtypes": {field.name: str(field.type) for field in table.schema},
        "protocol": protocol,
        "files": files,
        "data_fingerprint": _fingerprint(files),
    }


def _load(path: Path, version: int | None):
    _version(version)
    path = _local_path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    for parent in path.parents:
        if (parent / "_delta_log").exists():
            raise ValueError("Read the Delta table root with a pinned version, not a parquet part")
    root = path if path.is_dir() else path.parent
    if path.is_dir():
        _check_tree(root)
    metadata = _marker(root)
    is_delta = (root / "_delta_log").is_dir()
    if (root / "_delta_log").exists() and not is_delta:
        raise ValueError("The Delta transaction log must be a directory")
    format = "delta" if is_delta else "parquet"
    if metadata and metadata["format"] != format:
        raise ValueError("_table.json format disagrees with the actual table")
    if is_delta:
        if version is None:
            version = metadata["delta_version"] if metadata else None
        if version is None:
            raise ValueError("Delta reads require an explicit version or a pinned _table.json")
    elif version is not None:
        raise ValueError("A Delta version cannot be used to read parquet")
    matching = metadata is not None and metadata.get("delta_version") == version
    recorded = _verify_inventory(root, metadata) if matching else None
    pa, pq = _arrow()
    if is_delta:
        DeltaTable, _ = _delta()
        delta = DeltaTable(str(root), version=version)
        protocol = _protocol(delta)
        files = _delta_inventory(root, delta, version)
        arrow = delta.to_pyarrow_table()
        if any(not _primitive(pa, field.type) for field in arrow.schema):
            raise ValueError("Unsupported scalar schema in Delta table")
    else:
        if path.is_file():
            payloads = [path] if path.suffix.lower() == ".parquet" else []
        else:
            payloads = sorted(root.glob("*.parquet"))
        if not payloads:
            raise ValueError("No parquet payload found; CSV is not supported by table IO")
        files = {p.relative_to(root).as_posix(): _sha256(p) for p in payloads}
        if (root / "MLTable").is_file():
            files["MLTable"] = _sha256(root / "MLTable")
        tables = [pq.ParquetFile(p).read() for p in payloads]
        arrow = pa.concat_tables(tables)
        protocol = None
    _validate_columns(arrow.column_names, format)
    actual = _info(arrow, format, version, protocol, dict(sorted(files.items())))
    if matching:
        for key in ("row_count", "columns", "dtypes", "protocol"):
            if metadata.get(key) != actual[key]:
                raise ValueError(f"_table.json {key} disagrees with the actual table")
        # New checkpoints may appear later, but cannot change the pinned inventory.
        required = {
            name for name in files
            if not (name.startswith("_delta_log/") and ".checkpoint" in name)
        }
        if not required.issubset(recorded):
            raise ValueError("_table.json inventory does not cover the actual snapshot")
        actual["files"] = recorded
        actual["data_fingerprint"] = metadata["data_fingerprint"]
        hints = metadata.get("pandas_dtypes", {})
        if not isinstance(hints, dict) or any(
            column not in arrow.column_names
            or not isinstance(dtype, str) or dtype not in _PANDAS_NULLABLE
            for column, dtype in hints.items()
        ):
            raise ValueError("Invalid pandas_dtypes in _table.json")
        if hints:
            actual["pandas_dtypes"] = hints
    return arrow, actual


class ITableStore(ABC):
    @abstractmethod
    def write_table(self, frame: DataFrame, destination: Path, *, format: str = "delta") -> dict:
        """Write one new immutable table and return its actual snapshot metadata."""

    @abstractmethod
    def read_table(self, path: Path, *, version: int | None = None) -> tuple[DataFrame, dict]:
        """Read a pinned snapshot and its verified metadata."""

    @abstractmethod
    def table_info(self, path: Path, *, version: int | None = None) -> dict:
        """Inspect actual payloads and transaction-log state, not just a sidecar."""


class PortableTableStore(ITableStore):
    """Immutable Delta/parquet releases, without cloud clients or credentials.

    Delta uses classic reader 1 / writer 2 and no table features; this is a
    conservative interoperability profile, not a guarantee for every consumer.
    Naive timestamps are interpreted as UTC; aware timestamps are converted to
    UTC. Values must be exactly representable at microsecond precision. Nested,
    binary and untyped-null columns are rejected, rather than changing protocols.
    Pandas indexes are never persisted. Empty tables with typed columns are valid.

    Writers require a new or empty directory and publish ``_table.json`` last.
    Delta MLTable descriptors use native ``read_delta_lake`` with the same pinned
    version; the descriptor is not part of the Delta payload fingerprint. Consumer
    support for this descriptor and protocol still needs environment validation.
    Delta readers use its pinned version unless explicitly overridden; an external
    table without that marker requires a version. Later commits do not invalidate
    a historical snapshot, but changing or vacuuming its recorded files does.
    SHA256 detects corruption; the sidecar is provenance, not a signed trust root.
    """

    def write_table(self, frame: DataFrame, destination: Path, *, format: str = "delta") -> dict:
        if format not in ("delta", "parquet"):
            raise ValueError("Table format must be 'delta' or 'parquet'")
        destination = _local_path(destination)
        for parent in destination.parents:
            if (parent / "_delta_log").exists():
                raise ValueError("Cannot write a table inside an existing Delta table")
        if destination.exists() and (
            not destination.is_dir() or any(destination.iterdir())
        ):
            raise ValueError("Table destination must be a new or empty directory")
        writer = _delta()[1] if format == "delta" else None
        arrow = _from_frame(frame, format)
        destination.mkdir(parents=True, exist_ok=True)
        if format == "delta":
            writer(
                str(destination), arrow, mode="error",
                configuration={"delta.minReaderVersion": "1", "delta.minWriterVersion": "2"},
            )
            metadata = self.table_info(destination, version=0)
            (destination / "MLTable").write_text(
                "type: mltable\npaths:\n  - folder: ./\n"
                "transformations:\n  - read_delta_lake:\n"
                f"      version_as_of: {metadata['delta_version']}\n",
                encoding="utf-8",
            )
        else:
            _, pq = _arrow()
            pq.write_table(arrow, destination / "data.parquet")
            (destination / "MLTable").write_text(
                "paths:\n  - file: ./data.parquet\n"
                "transformations:\n  - read_parquet:\n", encoding="utf-8",
            )
            metadata = self.table_info(destination)
        hints = {
            name: str(dtype) for name, dtype in frame.dtypes.items()
            if str(dtype) in _PANDAS_NULLABLE
        }
        if hints:
            metadata["pandas_dtypes"] = hints
        with (destination / _MARKER).open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        return metadata

    def read_table(self, path: Path, *, version: int | None = None) -> tuple[DataFrame, dict]:
        arrow, metadata = _load(path, version)
        frame = arrow.to_pandas()
        if metadata.get("pandas_dtypes"):
            frame = frame.astype(metadata["pandas_dtypes"])
        return frame, metadata

    def table_info(self, path: Path, *, version: int | None = None) -> dict:
        return _load(path, version)[1]


def write_table(frame: DataFrame, destination: Path, *, format: str = "delta") -> dict:
    return PortableTableStore().write_table(frame, destination, format=format)


def read_table(path: Path, *, version: int | None = None) -> tuple[DataFrame, dict]:
    return PortableTableStore().read_table(path, version=version)


def table_info(path: Path, *, version: int | None = None) -> dict:
    return PortableTableStore().table_info(path, version=version)
