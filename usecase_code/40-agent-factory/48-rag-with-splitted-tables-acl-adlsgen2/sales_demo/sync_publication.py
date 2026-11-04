"""Approval-gated bridge from staged Graph snapshots to native ADLS/Search."""
from copy import deepcopy
from pathlib import Path

from .configuration import digest, read_json
from .deployment import publication_plan


def candidate_configuration(current: dict, publication_path: Path, policies: dict, guard: dict) -> dict:
    """Build a new consumer binding, never mutate the currently serving snapshot."""
    publication_path = publication_path.resolve()
    publication = read_json(publication_path)
    result = deepcopy(current)
    old_version = result["version"]
    version = publication["version"]
    if publication["dataset"] != result["dataset"] or set(policies) != {"json", "excel"}:
        raise ValueError("Candidate must contain the same logical dataset and both partitions.")
    for key in ("master_prefix", "project_prefix"):
        suffix = "/versions/" + old_version
        if not result[key].endswith(suffix):
            raise ValueError("Existing publication does not have an immutable version boundary.")
        result[key] = result[key][:-len(suffix)] + "/versions/" + version
    for key in ("partitions", "publication"):
        result.pop(key, None)
    result.update({
        "version": version, "artifacts_root": str(publication_path.parent),
        "publication_file": str(publication_path), "publication_sha256": digest(publication_path.read_bytes()),
        "partition_policies": deepcopy(policies), "graph_sync": deepcopy(guard),
        "publication_state": str(publication_path.parent / "service-verification.json"),
    })
    # A source-driven policy is distinct from a one-user operator preview binding.
    result.pop("evaluation_mode", None)
    result.pop("operator_preview_user_id", None)
    return result


def _check_owned_bytes(store, path, expected_hash, owner):
    raw, headers = store.request("GET", path, dfs=False)
    if headers.get("x-ms-meta-aif48owner") != owner or digest(raw) != expected_hash:
        raise ValueError("Source copy changed or is not owned by this publication.")


def refresh_permissions(config, store, *, apply=False):
    if apply is not True:
        raise ValueError("Updating mirrored ADLS permissions requires explicit --apply.")
    plan = publication_plan(config)
    policies = {part["id"]: part for part in config["partitions"]}
    groups = sorted({group for p in policies.values() for group in p.get("allowed_group_ids", [])})
    users = sorted({user for p in policies.values() for user in p.get("allowed_user_ids", [])})
    for entry in plan["files"]:
        for key in ("master", "project"):
            _check_owned_bytes(store, entry[key], entry["sha256"], config["owner"])
    for directory in plan["directories"]:
        store.directory(directory["path"], groups, users, preserve_existing=directory["preserve_existing"])
    for entry in plan["files"]:
        policy = policies[entry["source"]]
        for key in ("master", "project"):
            store.permissions(entry[key], policy.get("allowed_group_ids", []), policy.get("allowed_user_ids", []))
    return {"state": "source-permissions-updated", "search_resync_required": True,
            "changed_file_paths": [entry["project"] for entry in plan["files"]]}


def reconcile_native(config, *, state, scope_id, epoch, storage, source_reader, search_admin, search_reader,
                     authorization, export_dir, source_recheck, content_changed,
                     permissions_changed=True, apply=False, allow_paid=False):
    """No checkpoint is released by status alone; all native/source evidence is required."""
    if apply is not True or (content_changed and allow_paid is not True):
        raise ValueError("Reconciliation requires --apply and content processing requires --allow-paid.")
    state.candidate(scope_id, epoch)
    source_recheck()
    if content_changed:
        from .deployment import publish
        publish(config, storage, apply=True, synchronized_source=True)
        search_admin.configure(apply=True)
        search_admin.wait()
    elif permissions_changed:
        refresh_permissions(config, storage, apply=True)
        search_admin.synchronize(permissions_changed=True, content_changed=False, apply=True)
    state.candidate(scope_id, epoch)
    from .verification import verify_publication
    result = verify_publication(config, authorization, source_reader, search_reader, export_dir)
    source_recheck()
    state.candidate(scope_id, epoch)
    return result


def quarantine_deleted(config, partitions, storage, search_admin, *, apply=False):
    if apply is not True or not partitions or not set(partitions) <= {"json", "excel"}:
        raise ValueError("Quarantining deleted bound sources requires explicit partition scope and --apply.")
    restricted = deepcopy(config)
    for partition in restricted["partitions"]:
        if partition["id"] in partitions:
            partition["allowed_user_ids"] = []
            partition["allowed_group_ids"] = []
    refresh_permissions(restricted, storage, apply=True)
    search_admin.synchronize(permissions_changed=True, content_changed=False, apply=True)
    return {
        "state": "quarantined", "complete_dataset": False, "serving_allowed": False,
        "reason": "A required source disappeared; named mirrored readers were removed and native permissions refreshed.",
        "broad_rbac_caveat": "This cannot revoke access independently granted by broad Storage RBAC.",
    }
