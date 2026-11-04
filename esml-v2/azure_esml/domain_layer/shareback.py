"""Immutable producer-qualified silver products; approval metadata is not an ACL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import sha256
from ml_model_factory.lake import identifier, local_key_path, relative_key
from ml_model_factory.lake_flow import finish, publication, verified_manifest

from .lake_ingestion import _copy_files, _file_name, _no_links, _payload_inventory, _retry_publication
from .shared_lake import SharedLake, _version


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _project(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{3}", value):
        raise ValueError("Project must be an explicit three-digit project ID")
    return value


def _key(value: str) -> str:
    return relative_key(_file_name(value))


def _hash_value(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class SilverShareback:
    def __init__(self, root: Path, layout: SharedLake):
        self.root = Path(root).absolute()
        _no_links(self.root)
        self.layout = layout

    def product_key(self, dataset: str, producer_project: str, variation: str, version: str) -> str:
        return (
            f"{self.layout.prefix}/master/environments/{self.layout.environment}/products/"
            f"{identifier(dataset, 'dataset')}/producers/project{_project(producer_project)}/"
            f"variations/{identifier(variation, 'variation')}/versions/{_version(version)}"
        )

    def _scope(self, dataset, producer_project, variation, version) -> dict:
        self.product_key(dataset, producer_project, variation, version)
        return {
            "aifactory": self.layout.aifactory, "environment": self.layout.environment,
            "dataset": dataset, "producer_project": producer_project,
            "variation": variation, "version": version,
        }

    def _source_path(self, source_key, producer_project, table_relative) -> tuple[Path, Path]:
        source_key = _key(source_key)
        table_relative = _key(table_relative) if table_relative else ""
        scope = (
            f"{self.layout.prefix}/projects/project{_project(producer_project)}/"
            f"environments/{self.layout.environment}/"
        )
        suffix = source_key.removeprefix(scope).split("/")
        versions = [suffix[index + 1] for index, part in enumerate(suffix[:-1])
                    if part in ("versions", "runs", "snapshots")]
        if not source_key.startswith(scope) or not versions:
            raise ValueError("Silver source_key must identify an immutable producer project scope publication")
        for version in versions:
            _version(version)
        table_key = source_key + ("/" + table_relative if table_relative else "")
        return local_key_path(self.root, source_key), local_key_path(self.root, table_key)

    def _lineage(self, table: Path, manifest: dict, dataset: str, producer_project: str, info: dict) -> dict:
        lineage = load_json(table / "lineage.json")
        output = lineage.get("output", {})
        stage = lineage.get("medallion_stage", lineage.get("stage", output.get("medallion_stage")))
        stages = [lineage.get("stage"), output.get("stage"), output.get("medallion_stage")]
        operation = lineage.get("operation")
        if stage is None and operation in ("in2silver", "bronze2silver"):
            stage = "silver"
        if (stage != "silver" or any(value not in (None, "silver") for value in stages)
                or operation in ("merge", "split", "inference", "in2bronze")):
            raise ValueError("Shareback requires verified silver medallion lineage, never gold or bronze")
        declared_format = output.get("format", lineage.get("table_format"))
        legacy = declared_format is None
        if declared_format is None and info["format"] == "parquet" and output.get("sha256"):
            if not (table / "data.parquet").is_file() or output["sha256"] != sha256(table / "data.parquet"):
                raise ValueError("Legacy silver lineage does not match its Parquet output")
            declared_format = "parquet"
        if declared_format != info["format"]:
            raise ValueError("Silver lineage table format does not match the table")
        if not legacy and output.get("data_fingerprint") != info["data_fingerprint"]:
            raise ValueError("Silver lineage does not match the table snapshot fingerprint")
        if not legacy and _digest({"columns": output.get("columns"), "dtypes": output.get("dtypes")}) != info["schema_sha256"]:
            raise ValueError("Silver lineage schema does not match the table")
        if info["format"] == "delta" and output.get("delta_version") != info.get("delta_version"):
            raise ValueError("Silver lineage does not pin the Delta version")
        source_hash = lineage.get("source_fingerprint", lineage.get("source_manifest_sha256"))
        if not _hash_value(source_hash):
            raise ValueError("Silver lineage requires a source fingerprint or source manifest hash")
        expected = {
            "aifactory": self.layout.aifactory, "environment": self.layout.environment,
            "project": producer_project,
        }
        candidates = [
            lineage.get("scope", {}), lineage.get("tags", {}),
            manifest.get("scope", {}), manifest.get("tags", {}), manifest,
        ]
        matched = {}
        for candidate in candidates:
            for name, value in expected.items():
                if name in candidate:
                    if candidate[name] != value:
                        raise ValueError("Silver lineage or source manifest belongs to a different scope")
                    matched[name] = value
        if matched != expected:
            raise ValueError("Silver lineage or source manifest must declare the producer scope")
        if manifest.get("dataset", dataset) != dataset:
            raise ValueError("Source publication belongs to a different dataset")
        if lineage.get("dataset", dataset) != dataset:
            raise ValueError("Silver lineage belongs to a different dataset")
        return lineage

    @staticmethod
    def _table(path: Path, *, version=None) -> dict:
        from azure_esml.base_layer.tables import table_info

        _no_links(path)
        info = table_info(path, version=version)
        if info.get("format") not in ("delta", "parquet"):
            raise ValueError("Silver shareback supports Delta and Parquet tables only")
        if info["format"] == "delta" and (
            not isinstance(info.get("delta_version"), int) or isinstance(info["delta_version"], bool)
            or info["delta_version"] < 0
        ):
            raise ValueError("Silver shareback must pin an explicit Delta version")
        inventory = _payload_inventory(path)
        if not inventory:
            raise ValueError("Silver table is empty or missing")
        return {
            "format": info["format"], "delta_version": info.get("delta_version"),
            "table_files": inventory, "table_files_sha256": _digest(inventory),
            "schema_sha256": _digest({"columns": info["columns"], "dtypes": info["dtypes"]}),
            "data_fingerprint": info["data_fingerprint"],
        }

    @_retry_publication
    def publish(
        self, *, dataset: str, producer_project: str, variation: str, version: str,
        source_key: str, table_relative: str = "silver", owner: str,
        allowed_projects: list, mode: str = "reference",
    ) -> dict:
        scope = self._scope(dataset, producer_project, variation, version)
        if mode not in ("reference", "copy"):
            raise ValueError("mode must be reference or copy")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("Silver shareback requires an explicit owner")
        if (not isinstance(allowed_projects, (list, tuple)) or not allowed_projects
                or any(not isinstance(project, str) or not re.fullmatch(r"[0-9]{3}", project)
                       for project in allowed_projects)
                or len(set(allowed_projects)) != len(allowed_projects)):
            raise ValueError("allowed_projects must contain distinct explicit three-digit project IDs")
        source, table = self._source_path(source_key, producer_project, table_relative)
        manifest = verified_manifest(source)
        table_metadata = self._table(table)
        self._lineage(table, manifest, dataset, producer_project, table_metadata)
        contract = {
            "schema": "esml.silver-shareback/v1", **scope, "mode": mode,
            "source_key": source_key, "table_relative": table_relative,
            "source_manifest_sha256": sha256(source / "_SUCCESS.json"),
            **table_metadata, "owner": owner, "allowed_projects": sorted(allowed_projects),
            "retention": "Pin source files and Delta version; vacuum can break references.",
            "access": "Metadata is not an ACL; existing RBAC/ACL access is required.",
            "materialization": "metadata-only" if mode == "reference" else "full-table-copy",
        }
        key = self.product_key(dataset, producer_project, variation, version)
        destination = local_key_path(self.root, key)
        if destination.exists():
            existing = self._product(dataset, producer_project, variation, version)[1]
            if existing != contract:
                raise ValueError("Immutable shareback version already exists with a different contract")
            return self._result(key, contract, reused=True)
        with publication(self.root, key) as staging:
            if mode == "copy":
                _copy_files(table, staging / "silver", table_metadata["table_files"])
                if (_payload_inventory(staging / "silver") != table_metadata["table_files"]
                        or self._table(staging / "silver", version=contract["delta_version"]) != table_metadata):
                    raise ValueError("Silver source changed during physical shareback copy")
            write_json(staging / "contract.json", contract)
            if (verified_manifest(source) != manifest
                    or sha256(source / "_SUCCESS.json") != contract["source_manifest_sha256"]):
                raise ValueError("Silver source changed during shareback publication")
            finish(staging, {"kind": "silver-shareback", **scope, "signature": contract})
        self._product(dataset, producer_project, variation, version)
        return self._result(key, contract, reused=False)

    def _product(self, dataset, producer_project, variation, version) -> tuple[Path, dict]:
        key = self.product_key(dataset, producer_project, variation, version)
        path = local_key_path(self.root, key)
        manifest = verified_manifest(path)
        scope = self._scope(dataset, producer_project, variation, version)
        if manifest.get("kind") != "silver-shareback" or any(
            manifest.get(name) != value for name, value in scope.items()
        ):
            raise ValueError("Shareback product manifest belongs to a different scope")
        contract = load_json(path / "contract.json")
        if (manifest.get("signature") != contract or contract.get("schema") != "esml.silver-shareback/v1"
                or any(contract.get(name) != value for name, value in scope.items())
                or contract.get("mode") not in ("reference", "copy")):
            raise ValueError("Shareback contract does not match its product manifest scope")
        return path, contract

    def resolve(self, dataset, producer_project, variation, version, *, consumer_project) -> dict:
        consumer_project = _project(consumer_project)
        product, contract = self._product(dataset, producer_project, variation, version)
        if consumer_project not in contract.get("allowed_projects", []):
            raise ValueError("Consumer project is not approved in allowed_projects")
        source, table = self._source_path(contract["source_key"], producer_project, contract["table_relative"])
        key = self.product_key(dataset, producer_project, variation, version)
        if contract["mode"] == "reference":
            manifest = verified_manifest(source)
            if sha256(source / "_SUCCESS.json") != contract["source_manifest_sha256"]:
                raise ValueError("Pinned source manifest changed since shareback publication")
            table_key = contract["source_key"] + ("/" + contract["table_relative"] if contract["table_relative"] else "")
        else:
            table, table_key = product / "silver", key + "/silver"
            manifest = {"scope": {
                "aifactory": contract["aifactory"], "environment": contract["environment"],
                "project": contract["producer_project"],
            }, "dataset": dataset}
        actual = self._table(table, version=contract["delta_version"])
        if any(actual[name] != contract.get(name) for name in actual):
            raise ValueError("Pinned silver table files, schema or Delta version changed")
        self._lineage(table, manifest, dataset, producer_project, actual)
        return {
            **self._result(key, contract, reused=True), "consumer_project": consumer_project,
            "table_key": table_key, "table_path": table_key, "silver": table_key,
            "product_manifest_sha256": sha256(product / "_SUCCESS.json"),
        }

    def reference(self, dataset, producer_project, variation, version, *, consumer_project) -> dict:
        """Resolve metadata before binding a pipeline input; AML does not dereference JSON."""
        return self.resolve(dataset, producer_project, variation, version, consumer_project=consumer_project)

    @_retry_publication
    def onboard_reference(
        self, dataset, producer_project, variation, version, *, consumer_project, consumer_version,
    ) -> dict:
        resolved = self.resolve(dataset, producer_project, variation, version, consumer_project=consumer_project)
        key = self.layout.project(consumer_project, dataset, consumer_version)
        binding = {
            "schema": "esml.silver-binding/v1", "aifactory": self.layout.aifactory,
            "environment": self.layout.environment, "project": consumer_project,
            "dataset": dataset, "version": consumer_version, "product_key": resolved["key"],
            "producer_project": producer_project, "variation": variation, "product_version": version,
            "product_manifest_sha256": resolved["product_manifest_sha256"],
            "source_key": resolved["source_key"], "table_key": resolved["table_key"],
            "format": resolved["format"], "delta_version": resolved["delta_version"],
            "materialization": "metadata-only", "access": resolved["access"],
        }
        destination = local_key_path(self.root, key)
        reused = destination.exists()
        if reused:
            manifest = verified_manifest(destination)
            if (manifest.get("kind") != "silver-binding" or manifest.get("signature") != binding
                    or load_json(destination / "silver-binding.json") != binding):
                raise ValueError("Immutable consumer version already exists with a different silver binding")
        else:
            with publication(self.root, key) as staging:
                write_json(staging / "silver-binding.json", binding)
                if self.resolve(dataset, producer_project, variation, version, consumer_project=consumer_project) != resolved:
                    raise ValueError("Shareback product changed during consumer onboarding")
                finish(staging, {"kind": "silver-binding", "signature": binding})
            verified_manifest(destination)
        return {
            **resolved, "key": key, "path": key, "product_key": resolved["key"],
            "binding": key + "/silver-binding.json", "state": "reused" if reused else "committed",
            "reused": reused,
        }

    def list_variations(self, dataset, *, consumer_project) -> list[dict]:
        consumer_project = _project(consumer_project)
        prefix = (
            f"{self.layout.prefix}/master/environments/{self.layout.environment}/products/"
            f"{identifier(dataset, 'dataset')}/producers"
        )
        directory = local_key_path(self.root, prefix)
        results = []
        # Only this dataset's fixed producer/variation/version depth; never scan other projects.
        for marker in sorted(directory.glob("project[0-9][0-9][0-9]/variations/*/versions/*/_SUCCESS.json")):
            parts = marker.relative_to(directory).parts
            producer, variation, version = parts[0][7:], parts[2], parts[4]
            _, contract = self._product(dataset, producer, variation, version)
            if consumer_project in contract.get("allowed_projects", []):
                results.append(self.resolve(dataset, producer, variation, version, consumer_project=consumer_project))
        return results

    @staticmethod
    def _result(key, contract, *, reused) -> dict:
        return {
            **contract, "key": key, "path": key, "contract": key + "/contract.json",
            "state": "reused" if reused else "committed", "reused": reused,
        }
