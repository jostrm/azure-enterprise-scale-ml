"""Versioned shared-lake addresses, independent of storage account and processing engine."""

from dataclasses import dataclass

from ml_model_factory.lake import LakeLayout, identifier, relative_key


def _version(value):
    result = identifier(value, "version")
    if result.lower() in ("0", "latest", "active", "champion", "production"):
        raise ValueError("Lake releases must use immutable versions, not active/latest aliases")
    return result


@dataclass(frozen=True)
class SharedLake:
    aifactory: str
    environment: str
    prefix: str = "mlops/v1"

    def __post_init__(self):
        identifier(self.aifactory, "aifactory")
        if self.environment not in ("dev", "test", "prod"):
            raise ValueError("Shared lake environment must be dev, test or prod")
        relative_key(self.prefix)
        if self.prefix == "projects" or self.prefix.startswith("projects/"):
            raise ValueError("Shared lake needs a versioned namespace separate from legacy projects")

    def master(self, dataset: str, version: str) -> str:
        return f"{self.prefix}/master/environments/{self.environment}/datasets/{identifier(dataset, 'dataset')}/versions/{_version(version)}"

    def product(self, dataset: str, version: str) -> str:
        return f"{self.prefix}/master/environments/{self.environment}/products/{identifier(dataset, 'dataset')}/versions/{_version(version)}"

    def annotations(self, dataset: str, version: str) -> str:
        return f"{self.prefix}/master/environments/{self.environment}/annotations/{identifier(dataset, 'dataset')}/versions/{_version(version)}"

    def project(self, project: str, dataset: str, version: str) -> str:
        scope = self._layout(project, "dataset", dataset, version, "request", "snapshot").key("scope")
        return f"{scope}/datasets/{identifier(dataset, 'dataset')}/versions/{_version(version)}"

    def _layout(self, project, use_case, dataset, version, run_id, snapshot_id, **options):
        return LakeLayout.from_config({
            "aifactory": self.aifactory, "project": project, "environment": self.environment,
            "prefix": self.prefix, "use_case": use_case, "dataset": dataset, "data_version": version,
            "run_id": run_id, "snapshot_id": snapshot_id, **options,
        })

    def use_case(self, project: str, use_case: str) -> str:
        return self._layout(project, use_case, "dataset", "version", "run", "snapshot").key("use_case_root")

    def areas(self, *, project: str, use_case: str, dataset: str, version: str,
              run_id: str, snapshot_id: str, model_version: str, serving: str = "batch") -> dict[str, str]:
        layout = self._layout(project, use_case, dataset, version, run_id, snapshot_id,
                              model_version=model_version, serving=serving)
        base = layout.key("use_case_root")
        master, product = self.master(dataset, version), self.product(dataset, version)
        source = self.project(project, dataset, version)
        return {
            **layout.as_dict(),
            "master_version": master, "master_landing": master + "/landing",
            "master_changes": master + "/changes", "master_bronze": master + "/bronze",
            "shared_product": product, "shared_silver": product + "/silver",
            "shared_contract": product + "/contract.json",
            "project_version": source, "project_in": source + "/in",
            "project_source_binding": source + "/source-binding.json",
            "image_assets": master + "/landing/images",
            "label_exports": self.annotations(dataset, version) + "/exports",
            "label_reviews": base + f"/labeling/tasks/{identifier(run_id, 'run_id')}",
            "training_annotations": base + f"/training/snapshots/{identifier(snapshot_id, 'snapshot_id')}/gold/annotations",
            "stream_events": source + "/events",
            "stream_deadletter": base + f"/quarantine/streaming/runs/{identifier(run_id, 'run_id')}",
            "online_capture": layout.key("input") if serving == "online" else base + f"/inference/online/models/{model_version}/runs/{run_id}/in",
            "rag_documents": source + "/documents",
            "rag_snapshot": base + f"/rag/corpora/{identifier(dataset, 'dataset')}/versions/{identifier(version, 'version')}",
            "rag_chunks": base + f"/rag/corpora/{dataset}/versions/{version}/chunks",
            "rag_embeddings": base + f"/rag/corpora/{dataset}/versions/{version}/embeddings",
            "rag_index_manifest": base + f"/rag/corpora/{dataset}/versions/{version}/index-manifest.json",
            "rag_evaluation": base + f"/rag/evaluation/runs/{run_id}",
            "fine_tuning_snapshot": base + f"/fine-tuning/snapshots/{snapshot_id}",
            "fine_tuning_run": base + f"/fine-tuning/runs/{run_id}",
            "monitoring": base + f"/monitoring/models/{model_version}",
        }

    def blueprint(self) -> dict:
        return {
            "schema": "esml.shared-lake/v2", "aifactory": self.aifactory,
            "environment": self.environment, "prefix": self.prefix,
            "format_policy": {"bronze": "original source bytes", "silver": "delta", "gold": "delta",
                              "fallback": "Explicitly selected Parquet; never an implicit downgrade",
                              "delta_profile": "Classic reader 1 / writer 2; validate each actual consumer"},
            "areas": self.areas(project="001", use_case="example-usecase", dataset="example-dataset",
                                version="v1", run_id="run-001", snapshot_id="snapshot-001", model_version="1"),
            "semantics": {
                "master": "Immutable source releases with source/license/checksum, explicit change sets and provenance.",
                "shared_silver": "Validated reusable table; producer/project/variation/release shareback is reference-first with explicit copy mode.",
                "project_in": "Pinned master or shared-product import; no connection to mutable latest folders.",
                "gold": "Use-case-specific even for one input; training uses gold-derived splits isolated by entity or time.",
                "delta": "File-change manifests or keyed row CDC; a modification-time Copy alone is not a merge.",
                "streaming": "Immutable source event partitions; checkpoints stable across runs/model versions.",
                "images": "Images and versioned annotations linked by content/record IDs; no inferred labels.",
                "rag": "Source ACLs/deletions propagate to chunks/index; index manifest pins embedding model/chunker.",
                "fine_tuning": "Reviewed dataset splits and safety/license evidence, pinned base-model lineage; no fake jobs.",
                "online": "Request/response capture is opt-in, redacted and retention-controlled; not raw unrestricted prompts.",
                "access": "Cross-project silver reuse requires explicit product approval and existing RBAC/ACL access.",
                "formats": "CSV/Parquet/JSONL and immutable image/document files; Delta needs transactional engine commits.",
            },
            "not_activated": ["stream ingestion", "image-labeling service", "vector index", "LLM fine-tuning",
                              "retention policies", "ACL/RBAC changes", "monitoring schedules"],
        }
