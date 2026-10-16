"""Service integration acceptance, never generated or mocked by the CLI."""
from __future__ import annotations

from pathlib import Path

from .chunks import verify_chunks
from .identity import SalesUnavailable
from .runtime import SalesRuntime, config_fingerprint
from .search import correlate_evidence


def verify_publication(config: dict, authorization, store, search, export_dir: Path) -> dict:
    identity = authorization.authorize()
    authorized = {
        partition["id"] for partition in config["partitions"]
        if identity.oid in partition.get("allowed_user_ids", [])
        or identity.group_ids.intersection(partition.get("allowed_group_ids", []))
    }
    if authorized != {partition["id"] for partition in config["partitions"]}:
        raise SalesUnavailable()
    result = {
        "state": "verified", "owner": config["owner"], "dataset": config["dataset"],
        "version": config["version"], "config_sha256": config_fingerprint(config),
        "service_evidence": {},
    }
    for partition in config["partitions"]:
        receipt = search.verify_partition(partition, identity)
        source = store.read_input_bytes(partition, identity).decode("utf-8")
        raw = search.service_evidence(partition["id"], identity.search_token)
        children = correlate_evidence(raw["audit"], raw["chunks"])
        checked = verify_chunks(source, children, receipt["parent_id"], partition["source"], export_dir)
        if checked["input_sha256"] != partition["input_sha256"]:
            raise SalesUnavailable()
        after = search.verify_partition(partition, identity)
        if after["chunk_hashes"] != receipt["chunk_hashes"] or after["ingestion"] != receipt["ingestion"]:
            raise SalesUnavailable()
        result["service_evidence"][partition["id"]] = after
    # Verification can run behind a closed synchronization gate, but exposes no totals.
    runtime = SalesRuntime(config, result, authorization, store, search)
    from .arithmetic import aggregate_records
    aggregate_records({partition["id"]: runtime._rows(partition, identity)
                       for partition in config["partitions"]})
    result["structured_coverage_verified"] = True
    result["claims"] = {
        "real_text_split": True, "exact_three_chunks_per_table": True,
        "all_source_bytes_preserved": True, "split_inside_record": True,
        "deployed_agent_evaluation": False, "restricted_identity_evaluation": False,
        "image_serving": False,
    }
    return result
