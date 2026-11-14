"""Receipt-bound continuation inputs; no retries, claim release, or cloud writes."""

import copy

import pipeline_inputs
from pipeline_lifecycle import digest, require


def input_hash(record):
    return record["plan"].get("input_snapshot_hash", record["snapshot_hash"])


def continuation_snapshot(record, resolved):
    require(digest(resolved) == input_hash(record), "continuation-input-changed")
    return finalized_snapshot(record)


def finalized_snapshot(record):
    """Resolve the persisted continuation; callers still reobserve native effects."""
    require(record["status"] == "continuation-required"
            and record.get("admission", {}).get("status") == "released"
            and record.get("finalization", {}).get("status") == "succeeded",
            "continuation-finalization-required")
    canonical = record.get("configuration")
    require(isinstance(canonical, dict) and isinstance(canonical.get("document"), dict)
            and canonical.get("revision") == digest(canonical["document"]),
            "continuation-canonical-configuration-required")
    snapshot = record["snapshot"]
    operational = {key: copy.deepcopy(snapshot["binding"][key]) for key in (
        "schema", "provider", "consumer_commit", "consumer_ref", "pipeline_id", "bootstrap", "admission", "repository")
        if key in snapshot["binding"]}
    stages = record["plan"].get("stages", [])
    reconciled = len(stages) == 1 and stages[0].get("kind") in (
        "retained-claim-reconciliation", "bootstrap-reconciliation")
    completed = reconciled and stages[0].get("kind") == "retained-claim-reconciliation" \
        and stages[0].get("reconciliation", {}).get("completed_outcome") is True
    if completed:
        from pipeline_lifecycle_configuration import completed_document
        require(stages[0]["reconciliation"].get("continuation_required") is True
                and stages[0]["reconciliation"].get("requires_reprepare") is True
                and canonical["document"] == completed_document(record),
                "continuation-completed-configuration-mismatch")
    intended = snapshot["document"] if reconciled and not completed else canonical["document"]
    result = pipeline_inputs.resolve_document(intended, snapshot["request"],
                                               operational=operational or None)
    if reconciled and not completed:
        result["warnings"] = copy.deepcopy(snapshot.get("warnings", []))
    require(result["factory"]["id"] == snapshot["factory"]["id"]
            and {row["id"] for row in result["scales"]} == {row["id"] for row in snapshot["scales"]}
            and {row["id"] for row in result["projects"]} == {row["id"] for row in snapshot["projects"]},
            "continuation-target-changed")
    binding = result["document"].get("bindings", {}).get(
        result["factory"]["id"], {}).get(result["request"]["provider"])
    require(isinstance(binding, dict)
            or stages and all(row.get("kind") in ("admission-installation", "retained-claim-reconciliation", "bootstrap-reconciliation")
                              for row in stages),
            "continuation-binding-not-persisted")
    return result
