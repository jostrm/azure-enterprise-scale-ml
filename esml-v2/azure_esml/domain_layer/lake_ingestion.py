"""Local, immutable shared-lake source releases and explicit file deltas."""

from __future__ import annotations

from copy import deepcopy
import csv
from datetime import date, datetime, timezone
from functools import wraps
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import time

from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import read_frame, sha256
from ml_model_factory.lake import local_key_path
from ml_model_factory.lake_flow import file_inventory, finish, publication, verified_manifest

from .shared_lake import SharedLake


def _retry_publication(method):
    @wraps(method)
    def publish_with_retry(*args, **kwargs):
        for attempt in range(5):
            try:
                result = method(*args, **kwargs)
                if attempt:
                    result["publication_retries"] = attempt
                return result
            except PermissionError as exc:
                # Windows file scanners can briefly deny the final directory
                # rename. The canonical publication context has already rolled
                # it back; retry the whole verified transaction, never overwrite.
                if (getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 4
                        or not exc.filename or not getattr(exc, "filename2", None)
                        or not Path(exc.filename).name.startswith(".publishing-")):
                    raise
                time.sleep(0.05 * 2**attempt)
    return publish_with_retry


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Source and lake paths may not traverse symbolic links or junctions")


def _file_name(name: str) -> str:
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or name.startswith("/") or any(ord(character) < 32 for character in name)):
        raise ValueError("File names must be safe relative slash-separated paths")
    parts = name.split("/")
    if any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts):
        raise ValueError("File names must not contain traversal or ambiguous path components")
    if any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part) for part in parts):
        raise ValueError("File names must not contain reserved device names")
    return name


def _payload_inventory(directory: Path) -> dict[str, str]:
    inventory = file_inventory(directory)
    # The canonical helper excludes a publication marker at its own root. Inside
    # landing it is just another source file and must not silently disappear.
    marker = directory / "_SUCCESS.json"
    if marker.is_file():
        inventory[marker.name] = sha256(marker)
    for name in inventory:
        _file_name(name)
    return dict(sorted(inventory.items()))


def _copy_files(source: Path, destination: Path, names) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = destination.joinpath(*_file_name(name).split("/"))
        original = source if source.is_file() else source.joinpath(*name.split("/"))
        _no_links(original)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)


def _json_object(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    try:
        serialized = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only JSON values") from exc
    return json.loads(serialized)


def _watermark(value, previous: dict | None = None) -> dict | None:
    if value is None:
        return deepcopy(previous)
    value = _json_object(value, "watermark")
    if set(value) != {"start", "end"}:
        raise ValueError("watermark requires exactly start and end UTC timestamps")
    dates = {}
    for field in ("start", "end"):
        try:
            date = datetime.fromisoformat(value[field].replace("Z", "+00:00"))
            if date.utcoffset() != timezone.utc.utcoffset(date):
                raise ValueError("not UTC")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("watermark start and end must be explicit UTC timestamps") from exc
        dates[field] = date
    if dates["start"] >= dates["end"]:
        raise ValueError("watermark start must be before end")
    normalized = {field: date.isoformat().replace("+00:00", "Z") for field, date in dates.items()}
    if previous and normalized["start"] != previous["end"]:
        raise ValueError("watermark start must be contiguous with the previous committed end")
    return normalized


def _columns(value, label: str, *, allow_empty=False) -> list[str]:
    if (not isinstance(value, (tuple, list)) or (not value and not allow_empty)
            or any(not isinstance(name, str) or not name for name in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{label} must contain distinct nonempty column names")
    return list(value)


def _validate_frame(frame, *, primary_key=(), allow_empty=False) -> None:
    if (not len(frame.columns) or (frame.empty and not allow_empty)
            or not frame.columns.is_unique
            or any(not isinstance(column, str) or not column for column in frame.columns)):
        raise ValueError("Tabular data must have records and unique nonempty column names")
    if primary_key:
        if not set(primary_key).issubset(frame.columns):
            raise ValueError("Primary key columns are missing")
        if frame[list(primary_key)].isna().any().any():
            raise ValueError("Primary keys must not contain null values")
        if frame.duplicated(list(primary_key)).any():
            raise ValueError("Primary keys must be unique")


def _csv_header(path: Path) -> None:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            header = next((row for row in csv.reader(stream) if row), [])
        if not header or any(not name for name in header) or len(set(header)) != len(header):
            raise ValueError("CSV column names must be unique and nonempty")


def _provenance(provenance: dict, inventory: dict, source: Path) -> dict:
    value = _json_object(provenance, "provenance")
    if not isinstance(value.get("provider"), str) or not value["provider"].strip():
        raise ValueError("provenance.provider must identify the real source")
    if value["provider"] != "kaggle":
        return value
    if (value.get("kind") not in ("dataset", "competition")
            or not isinstance(value.get("slug"), str) or not value["slug"].strip()):
        raise ValueError("Kaggle provenance requires kind and slug")
    if not isinstance(value.get("license"), str) or not value["license"].strip():
        raise ValueError("Kaggle provenance requires explicit license information")
    if value["kind"] == "dataset" and (
            not isinstance(value.get("version"), (str, int)) or isinstance(value.get("version"), bool)
            or not str(value["version"]).strip() or str(value["version"]).lower() == "latest"):
        raise ValueError("Kaggle dataset provenance requires a pinned version")
    hashes = value.get("files")
    if not isinstance(hashes, dict):
        raise ValueError("Kaggle provenance requires a files checksum mapping")
    for name, digest in hashes.items():
        _file_name(name)
        if not isinstance(digest, str) or re.fullmatch(r"[a-fA-F0-9]{64}", digest) is None:
            raise ValueError("Kaggle provenance files require SHA-256 digests")
    for name, digest in inventory.items():
        expected = hashes.get(name)
        if expected is None and source.is_file():
            matches = [key for key in hashes
                       if tuple(source.parts[-len(PurePosixPath(key).parts):]) == PurePosixPath(key).parts]
            if len(matches) == 1:
                expected = hashes[matches[0]]
        if expected is None or expected.lower() != digest:
            raise ValueError(f"Kaggle source file does not match its provenance hash: {name}")
    return value


class SharedLakeIngestion:
    """Publish only local files; no download, storage provisioning or cloud writes."""

    def __init__(self, root: Path, layout: SharedLake):
        self.root = Path(root).absolute()
        _no_links(self.root)
        self.layout = layout

    def _source(self, source: Path) -> Path:
        source = Path(source).absolute()
        _no_links(source)
        resolved_source, resolved_root = source.resolve(), self.root.resolve()
        if (resolved_source == resolved_root or resolved_root.is_relative_to(resolved_source)
                or resolved_source.is_relative_to(resolved_root)):
            raise ValueError("Source dataset and lake root must not overlap")
        if not source.exists():
            raise FileNotFoundError(source)
        return source

    def _master(self, dataset: str, version: str) -> tuple[Path, dict]:
        directory = local_key_path(self.root, self.layout.master(dataset, version))
        manifest = verified_manifest(directory)
        expected = {
            "kind": "shared-master", "aifactory": self.layout.aifactory,
            "environment": self.layout.environment, "dataset": dataset, "version": version,
        }
        if any(manifest.get(name) != value for name, value in expected.items()):
            raise ValueError("Previous master publication belongs to a different source or scope")
        if manifest.get("source_files") != _payload_inventory(directory / "landing"):
            raise ValueError("Previous master source inventory does not match its landing files")
        return directory, manifest

    @_retry_publication
    def ingest(
        self, dataset: str, version: str, source: Path, *, provenance: dict,
        mode: str = "initial", previous_version: str | None = None,
        deleted_files: tuple[str, ...] = (), watermark: dict | None = None,
    ) -> dict:
        """Capture a full initial release or apply explicit file changes to a prior release.

        Omitted files in a delta are retained. Deletions affect only the new
        version. A no-op delta still commits an auditable, immutable version.
        """
        if mode not in ("initial", "delta"):
            raise ValueError("mode must be initial or delta")
        if mode == "initial" and (previous_version is not None or deleted_files):
            raise ValueError("Initial loads cannot specify previous_version or deleted_files")
        if mode == "delta" and (not previous_version or previous_version == version):
            raise ValueError("Delta loads require a different, explicit previous_version")
        if isinstance(deleted_files, str):
            raise ValueError("deleted_files must be a sequence of relative file paths")
        deleted = tuple(_file_name(name) for name in deleted_files)
        if len(set(deleted)) != len(deleted):
            raise ValueError("deleted_files must not contain duplicate paths")
        requested_watermark = _watermark(watermark)
        key = self.layout.master(dataset, version)
        destination = local_key_path(self.root, key)
        source = self._source(source)
        if source.is_file():
            if source.name == "provenance.json":
                raise ValueError("Select source data explicitly, not provenance.json metadata")
            inventory = {_file_name(source.name): sha256(source)}
        elif source.is_dir():
            inventory = _payload_inventory(source)
            inventory.pop("provenance.json", None)
        else:
            raise FileNotFoundError(source)
        if mode == "initial" and not inventory:
            raise ValueError("Initial source must contain at least one data file")
        provenance = _provenance(provenance, inventory, source)
        previous, previous_manifest, prior = None, None, {}
        if previous_version is not None:
            previous, previous_manifest = self._master(dataset, previous_version)
            prior = previous_manifest["source_files"]
            old_provenance = load_json(previous / "provenance.json")
            for field in ("provider", "kind", "slug"):
                if old_provenance.get(field) != provenance.get(field):
                    raise ValueError("Delta provenance must identify the same source as the previous version")
            if previous_manifest.get("ingestion") == "rows":
                raise ValueError("Use ingest_rows for a master version governed by a row CDC contract")
        watermark = _watermark(requested_watermark, (previous_manifest or {}).get("watermark"))
        unknown = set(deleted) - set(prior)
        if unknown:
            raise ValueError(f"Cannot delete files absent from the previous version: {sorted(unknown)}")
        if set(deleted) & set(inventory):
            raise ValueError("A file cannot be both supplied and explicitly deleted")
        added = {name: digest for name, digest in inventory.items() if name not in prior}
        updated = {name: digest for name, digest in inventory.items()
                   if name in prior and prior[name] != digest}
        removed = {name: prior[name] for name in sorted(deleted)}
        unchanged = {name: digest for name, digest in prior.items()
                     if name not in removed and name not in updated}
        snapshot = {**unchanged, **added, **updated}
        signature = {
            "mode": mode, "previous_version": previous_version,
            "previous_manifest_sha256": sha256(previous / "_SUCCESS.json") if previous else None,
            "provided_files": inventory, "deleted_files": sorted(deleted),
            "provenance": provenance, "watermark": requested_watermark,
        }
        no_changes = mode == "delta" and not (added or updated or removed)
        if destination.exists():
            _, existing = self._master(dataset, version)
            if existing.get("signature") != signature:
                raise ValueError("Immutable master version already exists with different content or provenance")
            return self._result(key, existing, reused=True)
        changes = {
            "schema": "esml.shared-lake-changes/v1", "mode": mode,
            "previous_version": previous_version, "added": added, "updated": updated,
            "deleted": removed, "unchanged": unchanged, "watermark": watermark,
            "semantics": "file-replacement; omitted files retained; deletions explicit",
        }
        with publication(self.root, key) as staging:
            landing = staging / "landing"
            landing.mkdir()
            if previous is not None:
                _copy_files(previous / "landing", landing, unchanged)
            _copy_files(source, landing, {**added, **updated})
            if _payload_inventory(landing) != dict(sorted(snapshot.items())):
                raise ValueError("Source changed during capture; no master version was published")
            if mode == "delta":
                _copy_files(source, staging / "changes" / "files", {**added, **updated})
                if _payload_inventory(staging / "changes" / "files") != dict(sorted({**added, **updated}.items())):
                    raise ValueError("Source changed during delta capture; no version was published")
            write_json(staging / "changes" / "manifest.json", changes)
            write_json(staging / "provenance.json", provenance)
            self._bronze(landing, staging / "bronze", snapshot, key)
            if previous is not None and verified_manifest(previous) != previous_manifest:
                raise ValueError("Previous master changed during capture")
            finish(staging, {
                "kind": "shared-master", "aifactory": self.layout.aifactory,
                "environment": self.layout.environment, "dataset": dataset, "version": version,
                "source_files": dict(sorted(snapshot.items())), "signature": signature,
                "mode": mode, "previous_version": previous_version, "no_changes": no_changes,
                "ingestion": "files", "watermark": watermark,
                "download_provenance_verified": provenance["provider"] == "kaggle",
                "provenance_note": "Local bytes verified against supplied checksums; no remote source attestation.",
            })
        return self._result(key, verified_manifest(destination), reused=False)

    @_retry_publication
    def ingest_rows(
        self, dataset: str, version: str, changes: Path, *, provenance: dict,
        primary_key: list, previous_version: str | None = None,
        operation_column: str = "_operation", sequence_column: str | None = None,
        watermark: dict | None = None,
    ) -> dict:
        """Publish a keyed table snapshot from an initial table or ordered row CDC."""
        primary_key = _columns(primary_key, "primary_key")
        _columns([operation_column], "operation_column")
        if sequence_column is not None:
            _columns([sequence_column], "sequence_column")
        if operation_column in primary_key or sequence_column in primary_key or operation_column == sequence_column:
            raise ValueError("CDC metadata columns must be distinct from the primary key")
        if previous_version == version:
            raise ValueError("Row CDC requires a different previous_version")
        key = self.layout.master(dataset, version)
        destination = local_key_path(self.root, key)
        source = self._source(changes)
        if not source.is_file() or source.suffix.lower() not in (".csv", ".parquet"):
            raise ValueError("Row ingestion requires one explicit CSV or Parquet file")
        supplied = {_file_name(source.name): sha256(source)}
        provenance = _provenance(provenance, supplied, source)
        requested_watermark = _watermark(watermark)
        previous, previous_manifest, before = None, None, None
        if previous_version is not None:
            previous, previous_manifest = self._master(dataset, previous_version)
            if (previous_manifest.get("ingestion") != "rows"
                    or previous_manifest.get("primary_key") != primary_key):
                raise ValueError("Previous master does not have the same primary key row CDC contract")
            old_provenance = load_json(previous / "provenance.json")
            if any(old_provenance.get(field) != provenance.get(field) for field in ("provider", "kind", "slug")):
                raise ValueError("Row CDC provenance must identify the same source")
            before = read_frame(previous / "landing" / "data.parquet")
            _validate_frame(before, primary_key=primary_key, allow_empty=True)
        watermark = _watermark(requested_watermark, (previous_manifest or {}).get("watermark"))
        signature = {
            "ingestion": "rows", "previous_version": previous_version,
            "previous_manifest_sha256": sha256(previous / "_SUCCESS.json") if previous else None,
            "provided_files": supplied, "primary_key": primary_key,
            "operation_column": operation_column, "sequence_column": sequence_column,
            "provenance": provenance, "watermark": requested_watermark,
        }
        if destination.exists():
            _, existing = self._master(dataset, version)
            if existing.get("signature") != signature:
                raise ValueError("Immutable master version already exists with a different row CDC request")
            return self._result(key, existing, reused=True)
        with publication(self.root, key) as staging:
            raw = staging / "changes" / "files"
            _copy_files(source, raw, supplied)
            if _payload_inventory(raw) != supplied:
                raise ValueError("Source changed during row CDC capture")
            _csv_header(raw / source.name)
            frame = read_frame(raw / source.name)
            _validate_frame(frame, allow_empty=before is not None)
            if before is None:
                if operation_column in frame:
                    raise ValueError("Initial row ingestion requires a full table, not CDC operations")
                if sequence_column:
                    if sequence_column not in frame or frame[sequence_column].isna().any():
                        raise ValueError("Initial sequence column must exist without null values")
                    frame = frame.drop(columns=[sequence_column])
                _validate_frame(frame, primary_key=primary_key)
                snapshot = frame
                change_set = {
                    "added": self._key_records(frame, primary_key), "updated": [], "deleted": [],
                    "unchanged": 0, "received_records": len(frame), "superseded_records": 0,
                }
            else:
                snapshot, change_set = self._merge_rows(
                    before, frame, primary_key, operation_column, sequence_column,
                )
            landing = staging / "landing"
            landing.mkdir()
            snapshot.to_parquet(landing / "data.parquet", index=False)
            inventory = _payload_inventory(landing)
            self._bronze(landing, staging / "bronze", inventory, key, allow_empty=True)
            no_changes = before is not None and not any(change_set[name] for name in ("added", "updated", "deleted"))
            write_json(staging / "provenance.json", provenance)
            write_json(staging / "changes" / "manifest.json", {
                "schema": "esml.shared-lake-row-changes/v1", "primary_key": primary_key,
                "previous_version": previous_version, "source_files": supplied,
                "snapshot_files": inventory, "watermark": watermark, **change_set,
            })
            if previous is not None and verified_manifest(previous) != previous_manifest:
                raise ValueError("Previous master changed during row CDC capture")
            finish(staging, {
                "kind": "shared-master", "aifactory": self.layout.aifactory,
                "environment": self.layout.environment, "dataset": dataset, "version": version,
                "ingestion": "rows", "mode": "delta" if previous else "initial",
                "primary_key": primary_key, "source_files": inventory,
                "signature": signature, "previous_version": previous_version, "watermark": watermark,
                "no_changes": no_changes, "rows": len(snapshot),
                "download_provenance_verified": provenance["provider"] == "kaggle",
                "provenance_note": "Local bytes verified against supplied checksums; no remote source attestation.",
            })
        return self._result(key, verified_manifest(destination), reused=False)

    @staticmethod
    def _key_records(frame, primary_key) -> list:
        def encode(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise ValueError("Primary keys must contain JSON scalars or dates")
        return json.loads(json.dumps(
            frame[list(primary_key)].to_dict("records"), default=encode, allow_nan=False,
        ))

    @staticmethod
    def _align_types(frame, reference):
        from pandas.api.types import is_dtype_equal, is_numeric_dtype

        result = frame.copy()
        for column in frame.columns:
            expected, actual = reference[column].dtype, frame[column].dtype
            if is_dtype_equal(expected, actual):
                continue
            if not frame.empty and not (is_numeric_dtype(expected) and is_numeric_dtype(actual)):
                raise ValueError(f"Row CDC schema drift: incompatible dtype for {column}")
            try:
                converted = frame[column].astype(expected)
                old_values, new_values = frame[column].dropna().tolist(), converted.dropna().tolist()
                old_values = [value.item() if hasattr(value, "item") else value for value in old_values]
                new_values = [value.item() if hasattr(value, "item") else value for value in new_values]
                if (not converted.isna().equals(frame[column].isna()) or old_values != new_values):
                    raise ValueError("conversion changes values")
                result[column] = converted
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Row CDC schema drift: lossy conversion for {column}") from exc
        return result

    @classmethod
    def _merge_rows(cls, before, frame, primary_key, operation_column, sequence_column):
        import pandas as pd

        if operation_column not in frame or not frame[operation_column].isin(("upsert", "delete")).all():
            raise ValueError("Row CDC requires explicit upsert/delete operations")
        if not set(primary_key).issubset(frame) or frame[primary_key].isna().any().any():
            raise ValueError("Row CDC primary keys must exist and must not contain null values")
        received = len(frame)
        if sequence_column:
            if sequence_column not in frame or frame[sequence_column].isna().any():
                raise ValueError("CDC sequence column must exist and must not contain null values")
            if frame.duplicated(primary_key + [sequence_column]).any():
                raise ValueError("CDC sequence ties for the same primary key are ambiguous")
            try:
                frame = frame.sort_values(sequence_column, kind="stable").drop_duplicates(primary_key, keep="last")
            except TypeError as exc:
                raise ValueError("CDC sequence values must have a consistent sortable type") from exc
        elif frame.duplicated(primary_key).any():
            raise ValueError("Row CDC primary keys must be unique unless an ordering sequence is supplied")
        metadata = [operation_column] + ([sequence_column] if sequence_column else [])
        data_columns = [column for column in frame if column not in metadata]
        upserts = frame.loc[frame[operation_column] == "upsert", data_columns]
        deletes = frame.loc[frame[operation_column] == "delete", primary_key]
        if set(data_columns) - set(before.columns):
            raise ValueError("Row CDC schema drift: unexpected columns")
        if not upserts.empty and set(data_columns) != set(before.columns):
            raise ValueError("Row CDC schema drift: upserts must provide every data column")
        upserts = cls._align_types(upserts, before)
        deletes = cls._align_types(deletes, before)
        old_keys = list(before[primary_key].itertuples(index=False, name=None))
        upsert_keys = list(upserts[primary_key].itertuples(index=False, name=None))
        delete_keys = list(deletes[primary_key].itertuples(index=False, name=None))
        try:
            old_positions = {key: index for index, key in enumerate(old_keys)}
            if set(delete_keys) - set(old_keys):
                raise ValueError("Cannot delete a primary key absent from the previous snapshot")
            affected = set(upsert_keys) | set(delete_keys)
        except TypeError as exc:
            raise ValueError("Primary keys must contain scalar hashable values") from exc
        if not upserts.empty:
            upserts = upserts.loc[:, before.columns]
        added_positions, updated_positions = [], []
        for index, key in enumerate(upsert_keys):
            if key not in old_positions:
                added_positions.append(index)
            elif not before.iloc[[old_positions[key]]].reset_index(drop=True).equals(
                    upserts.iloc[[index]].reset_index(drop=True)):
                updated_positions.append(index)
        retained = before.loc[[key not in affected for key in old_keys]]
        snapshot = pd.concat([retained, upserts], ignore_index=True) if not upserts.empty else retained.reset_index(drop=True)
        snapshot = snapshot.astype(before.dtypes.to_dict())
        if not added_positions and not updated_positions and deletes.empty:
            snapshot = before.copy()
        _validate_frame(snapshot, primary_key=primary_key, allow_empty=True)
        return snapshot, {
            "added": cls._key_records(upserts.iloc[added_positions], primary_key),
            "updated": cls._key_records(upserts.iloc[updated_positions], primary_key),
            "deleted": cls._key_records(deletes, primary_key),
            "unchanged": len(before) - len(updated_positions) - len(deletes),
            "received_records": received, "superseded_records": received - len(frame),
        }

    @_retry_publication
    def publish_silver(
        self, dataset: str, source_version: str, product_version: str, *,
        required_columns: list, owner: str, allowed_projects: tuple, primary_key=(),
        table_format: str = "delta",
    ) -> dict:
        """Validate a reusable tabular product; approvals do not grant storage ACLs."""
        from azure_esml.base_layer.tables import write_table
        from .runtime import read_tabular

        if table_format not in ("delta", "parquet"):
            raise ValueError("table_format must be delta or parquet")
        required_columns = _columns(required_columns, "required_columns")
        primary_key = _columns(primary_key, "primary_key", allow_empty=True)
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("A shared silver product requires an explicit owner")
        if (not isinstance(allowed_projects, (tuple, list)) or not allowed_projects
                or any(not isinstance(project, str) or not re.fullmatch(r"[0-9]{3}", project)
                       for project in allowed_projects) or len(set(allowed_projects)) != len(allowed_projects)):
            raise ValueError("allowed_projects must contain distinct explicit three-digit project IDs")
        allowed_projects = sorted(allowed_projects)
        source, source_manifest = self._master(dataset, source_version)
        source_key = self.layout.master(dataset, source_version)
        key = self.layout.product(dataset, product_version)
        destination = local_key_path(self.root, key)
        signature = {
            "source_version": source_version, "source_key": source_key,
            "source_manifest_sha256": sha256(source / "_SUCCESS.json"), "required_columns": required_columns,
            "owner": owner, "allowed_projects": allowed_projects, "primary_key": primary_key,
            "table_format": table_format,
        }
        if destination.exists():
            existing = self._product(dataset, product_version)[1]
            existing_signature = {"table_format": "parquet", **existing.get("signature", {})}
            if existing_signature != signature:
                raise ValueError("Immutable shared silver version already exists with a different contract")
            return self._result(key, existing, reused=True)
        names = list(source_manifest["source_files"])
        extensions = {PurePosixPath(name).suffix.lower() for name in names}
        if len(extensions) != 1 or not extensions.issubset({".csv", ".parquet"}):
            raise ValueError("Shared tabular silver requires only CSV or only Parquet source files")
        format_ = next(iter(extensions))[1:]
        with publication(self.root, key) as staging:
            for name in names:
                _csv_header(source.joinpath("landing", *name.split("/")))
            frame, _ = read_tabular(source / "landing", {"format": format_, "file_pattern": "**/*"})
            _validate_frame(frame, primary_key=primary_key)
            if not set(required_columns).issubset(frame.columns):
                raise ValueError("Shared silver source is missing required columns")
            silver = staging / "silver"
            table = write_table(frame, silver, format=table_format)
            write_json(silver / "lineage.json", {
                "schema": "esml.shared-silver-lineage/v1", "medallion_stage": "silver",
                "source_key": source_key, "source_manifest_sha256": signature["source_manifest_sha256"],
                "scope": {"aifactory": self.layout.aifactory, "environment": self.layout.environment},
                "output": table, "learned_preprocessing": False,
            })
            write_json(staging / "contract.json", {
                "schema": "esml.shared-silver-contract/v1", "status": "validated",
                **signature, "rows": len(frame), "columns": frame.columns.tolist(),
                "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
                "checks": ["nonempty", "unique-column-names", "required-columns"]
                          + (["unique-nonnull-primary-key"] if primary_key else []),
                "transformations": [], "learned_preprocessing": False,
                "table": table, "medallion_stage": "silver",
                "access": "Explicit product approval only; existing RBAC/ACL access is still required.",
            })
            if verified_manifest(source) != source_manifest:
                raise ValueError("Master source changed during shared silver publication")
            finish(staging, {
                "kind": "shared-silver", "aifactory": self.layout.aifactory,
                "environment": self.layout.environment, "dataset": dataset, "version": product_version,
                "source_version": source_version, "signature": signature,
                "table": table,
            })
        return self._result(key, verified_manifest(destination), reused=False)

    def _product(self, dataset: str, version: str) -> tuple[Path, dict]:
        source = local_key_path(self.root, self.layout.product(dataset, version))
        manifest = verified_manifest(source)
        expected = {
            "kind": "shared-silver", "aifactory": self.layout.aifactory,
            "environment": self.layout.environment, "dataset": dataset, "version": version,
        }
        if any(manifest.get(field) != value for field, value in expected.items()):
            raise ValueError("Shared silver publication belongs to a different source or scope")
        return source, manifest

    @_retry_publication
    def onboard(
        self, project: str, dataset: str, version: str, *, source_version: str,
        source_kind: str = "master", product_version: str | None = None,
    ) -> dict:
        """Copy a verified, pinned master or approved silver product into project IN."""
        key = self.layout.project(project, dataset, version)
        destination = local_key_path(self.root, key)
        if source_kind == "master":
            if product_version is not None:
                raise ValueError("A master binding must not specify product_version")
            source, source_manifest = self._master(dataset, source_version)
            source_key = self.layout.master(dataset, source_version)
            payload = source / "landing"
        elif source_kind == "silver":
            if not product_version:
                raise ValueError("A silver binding requires an explicit product_version")
            source, source_manifest = self._product(dataset, product_version)
            if source_manifest.get("source_version") != source_version:
                raise ValueError("Shared product source_version does not match the requested binding")
            contract = load_json(source / "contract.json")
            if project not in contract.get("allowed_projects", []):
                raise ValueError("Project is not approved in the shared product allowed_projects")
            source_key = self.layout.product(dataset, product_version)
            payload = source / "silver"
        else:
            raise ValueError("source_kind must be master or silver")
        inventory = _payload_inventory(payload)
        binding = {
            "schema": "esml.shared-lake-source-binding/v1", "project": project, "dataset": dataset,
            "aifactory": self.layout.aifactory, "environment": self.layout.environment,
            "version": version, "source_kind": source_kind, "source_version": source_version,
            "product_version": product_version, "source_key": source_key,
            "source_manifest_sha256": sha256(source / "_SUCCESS.json"), "source_files": inventory,
        }
        if source_kind == "silver":
            binding["contract_sha256"] = sha256(source / "contract.json")
        if destination.exists():
            existing = verified_manifest(destination)
            if existing.get("kind") != "shared-project" or existing.get("signature") != binding:
                raise ValueError("Immutable project version already exists with a different source binding")
            return self._result(key, existing, reused=True)
        with publication(self.root, key) as staging:
            _copy_files(payload, staging / "in", inventory)
            if _payload_inventory(staging / "in") != inventory:
                raise ValueError("Source changed during project onboarding")
            write_json(staging / "source-binding.json", binding)
            if verified_manifest(source) != source_manifest:
                raise ValueError("Source publication changed during project onboarding")
            finish(staging, {
                "kind": "shared-project", "aifactory": self.layout.aifactory,
                "environment": self.layout.environment, "project": project,
                "dataset": dataset, "version": version, "signature": binding,
            })
        return self._result(key, verified_manifest(destination), reused=False)

    @staticmethod
    def _bronze(landing: Path, bronze: Path, inventory: dict, key: str, *, allow_empty=False) -> None:
        bronze.mkdir()
        _copy_files(landing, bronze / "raw", inventory)
        if _payload_inventory(bronze / "raw") != inventory:
            raise ValueError("Source changed during raw bronze capture")
        contract = {
            "schema": "esml.shared-lake-bronze/v1", "source": key + "/landing",
            "files": inventory, "transformations": [], "learned_preprocessing": False,
            "status": "raw-inventory; requires-modality-specific-validation",
            "payload": key + "/bronze/raw", "byte_preserving": True,
        }
        write_json(bronze / "source-index.json", contract)

    def _result(self, key: str, manifest: dict, *, reused: bool) -> dict:
        result = {
            "status": "no_changes" if manifest.get("no_changes") else "committed",
            "state": "reused" if reused else "committed",
            "reused": reused, "key": key, "path": key,
            "local_path": str(local_key_path(self.root, key)),
            "manifest": manifest,
        }
        if manifest["kind"] == "shared-master":
            result.update(landing=key + "/landing", bronze=key + "/bronze", changes=key + "/changes/manifest.json")
        elif manifest["kind"] == "shared-silver":
            result.update(silver=key + "/silver", contract=key + "/contract.json")
        elif manifest["kind"] == "shared-project":
            result.update(input=key + "/in", source_binding=key + "/source-binding.json")
        return result
