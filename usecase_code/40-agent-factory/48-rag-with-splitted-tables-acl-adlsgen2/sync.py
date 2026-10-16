"""Optional Graph delta/security reconciliation; plans are offline and mutations require approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import quote

import main as common
from agent_factory.cli import write_json
from sales_demo.configuration import digest, load_config, local_file, read_json
from sales_demo.graph_delta import (
    BinaryGraphTransport, GraphDeltaClient, UnsupportedPermissions, build_change_plan, validate_graph_config,
    reconcile_inventory,
)
from sales_demo.graph_publication import build_candidate
from sales_demo.graph_webhooks import SubscriptionManager, client_state_from_env
from sales_demo.runtime import config_fingerprint
from sales_demo.sync_state import SyncState, SyncConflict
from sales_demo.sync_publication import candidate_configuration, quarantine_deleted, reconcile_native


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_sync(path):
    config = validate_graph_config(read_json(path))
    for key in ("database", "staging_directory"):
        candidate = Path(config[key])
        if not candidate.is_absolute():
            raise ValueError("Synchronization state and staging require absolute consumer-owned paths.")
        common.external_output(candidate)
    age = config.get("max_age_seconds", 900)
    if type(age) is not int or not 30 <= age <= 86400:
        raise ValueError("Freshness age must be a bounded integer, 30..86400 seconds.")
    config["max_age_seconds"] = age
    return config


def guard(config):
    return {key: config[key] for key in ("database", "scope_id", "max_age_seconds")}


def bindings(config):
    return {binding["partition"]: binding["item_id"] for binding in config["bindings"]}


def source_pins(snapshots):
    return {
        key: {"item_id": value["item"]["id"], "source_etag": value["item"]["eTag"],
              "source_sha256": digest(value["raw"]), "permission_sha256": value["permission_sha256"]}
        for key, value in snapshots.items()
    }


def _copy_permission_candidate(current, snapshots, directory):
    directory.mkdir(parents=True, exist_ok=False)
    publication = deepcopy(current["publication"])
    for partition in publication["partitions"]:
        snapshot = snapshots[partition["id"]]
        partition["graph_lineage"].update({
            "source_etag": snapshot["item"]["eTag"],
            "permission_sha256": snapshot["permission_sha256"],
        })
        partition.update(snapshot["policy"])
        partition.pop("permission_sha256", None)
    for item in publication["files"]:
        for tree in ("master", "project"):
            original = local_file(Path(current["artifacts_root"]) / tree, item["path"])
            if digest(original.read_bytes()) != item["sha256"]:
                raise ValueError("Existing immutable source bytes changed; do not reuse the publication.")
            destination = local_file(directory / tree, item["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
    write_json(directory / "publication.json", publication)
    return publication


def stage_round(graph, current, state, client):
    cycle = state.begin(graph["scope_id"])
    round = client.fetch(cycle["cursor"])
    inventory = reconcile_inventory(cycle["inventory"], round)
    old_hashes = {
        part.get("graph_lineage", {}).get("item_id"): part.get("graph_lineage", {}).get("permission_sha256")
        for part in current["partitions"]
    }
    plan = build_change_plan(graph, cycle["inventory"], inventory, old_hashes)
    missing = [key for key, item in bindings(graph).items() if item not in inventory]
    reason = "required-source-deleted"
    snapshots = None
    if not missing:
        try:
            snapshots = client.inspect_selected(inventory)
        except UnsupportedPermissions:
            missing = ["json", "excel"]
            reason = "unsupported-source-permissions"
    if missing:
        candidate = {
            "delta_link": round["delta_link"], "inventory": inventory, "plan": plan,
            "action": "quarantine", "deleted_partitions": missing,
            "quarantine_reason": reason,
            "source_config_sha256": fingerprint(graph), "active_config_sha256": config_fingerprint(current),
        }
    else:
        pins = source_pins(snapshots)
        plan = build_change_plan(
            graph, cycle["inventory"], inventory, old_hashes,
            {value["item_id"]: value["permission_sha256"] for value in pins.values()},
        )
        previous = {p["id"]: p.get("graph_lineage", {}) for p in current["partitions"]}
        content_changed = any(
            previous[key].get("source_sha256") != pin["source_sha256"]
            or previous[key].get("item_id") != pin["item_id"]
            or previous[key].get("drive_id") != graph["drive_id"]
            or previous[key].get("tenant_id") != graph["tenant_id"]
            for key, pin in pins.items()
        )
        unchanged = not cycle["repair_required"] and not content_changed and all(
            all(previous[key].get(name) == value for name, value in pin.items())
            for key, pin in pins.items()
        ) and all(
            all(current["partition_policies"][key].get(field, []) == snapshots[key]["policy"][field]
                for field in ("allowed_user_ids", "allowed_group_ids"))
            for key in snapshots
        )
        directory = common.external_output(Path(graph["staging_directory"]) / ("epoch-" + str(cycle["epoch"])))
        if unchanged:
            directory.mkdir(parents=True, exist_ok=False)
            configuration = deepcopy(current)
            configuration.pop("partitions", None)
            configuration.pop("publication", None)
        elif content_changed:
            build_candidate(graph, snapshots, directory)
        else:
            _copy_permission_candidate(current, snapshots, directory)
        policies = {key: {name: value["policy"][name] for name in ("allowed_user_ids", "allowed_group_ids")}
                    for key, value in snapshots.items()}
        if not unchanged:
            configuration = candidate_configuration(current, directory / "publication.json", policies, guard(graph))
        configuration["paths_approved"] = True
        candidate_path = directory / "candidate-config.json"
        write_json(candidate_path, configuration)
        hydrated = load_config(candidate_path)
        candidate = {
            "delta_link": round["delta_link"], "inventory": inventory, "plan": plan,
            "action": "content" if content_changed else "recheck" if unchanged else "permissions", "source_pins": pins,
            "candidate_config": str(candidate_path), "candidate_config_sha256": config_fingerprint(hydrated),
            "source_config_sha256": fingerprint(graph), "active_config_sha256": config_fingerprint(current),
        }
    state.stage(graph["scope_id"], cycle["epoch"], candidate)
    return {
        "scope_id": graph["scope_id"], "epoch": cycle["epoch"], "action": candidate["action"],
        "candidate_sha256": fingerprint(candidate), "plan": plan,
        "azure_mutations": False, "serving_allowed": False,
        "next": "Review candidate-config.json, source ACL projection and exact version-scoped ingestion rights before reconcile.",
    }


def reconcile(graph, current, config_path, state, client, args, session):
    with state.apply_lock(graph["scope_id"]):
        return _reconcile_locked(graph, current, config_path, state, client, args, session)


def _reconcile_locked(graph, current, config_path, state, client, args, session):
    candidate = state.candidate(graph["scope_id"], args.epoch)
    if (not args.approved_candidate or fingerprint(candidate) != args.approved_candidate
            or candidate["source_config_sha256"] != fingerprint(graph)
            or candidate["active_config_sha256"] != config_fingerprint(current)):
        raise ValueError("Candidate approval, Graph source or active publication changed; reconcile again.")
    if args.apply is not True:
        raise ValueError("Applying synchronized content/permissions requires --apply.")
    if config_fingerprint(load_config(config_path)) != config_fingerprint(current):
        raise SyncConflict("Active consumer configuration changed while waiting for the publication lock.")
    if candidate["action"] == "content" and not args.allow_paid:
        raise ValueError("Content synchronization invokes embeddings and requires --allow-paid.")
    if state.scope(graph["scope_id"])["repair_required"] and candidate["action"] == "recheck":
        raise SyncConflict("A prior writer changed the mirror after staging; stage a repair reconciliation.")
    from sales_demo.deployment import StorageWriter
    from sales_demo.identity import AzureCliTokenProvider, DelegatedAuthorization, ManagedIdentitySearchTransport
    from sales_demo.runtime import DelegatedRowStore
    from sales_demo.search import SearchClient
    if candidate["action"] == "quarantine":
        # Reconcile current source state before removing named readers from owned copies.
        fresh = client.fetch(candidate["delta_link"])
        inventory = reconcile_inventory(candidate["inventory"], fresh)
        if candidate.get("quarantine_reason") == "required-source-deleted":
            if any(bindings(graph)[part] in inventory for part in candidate["deleted_partitions"]):
                raise SyncConflict("A source reappeared; stage a new reconciliation instead of revoking it.")
        elif candidate.get("quarantine_reason") == "unsupported-source-permissions":
            try:
                client.inspect_selected(inventory)
            except UnsupportedPermissions:
                pass
            else:
                raise SyncConflict("Permissions are representable again; stage a new reconciliation.")
        else:
            raise ValueError("Unknown quarantine reason.")
        state.mark_repair_required(graph["scope_id"], args.epoch)
        return quarantine_deleted(
            current, candidate["deleted_partitions"], StorageWriter(current, session),
            SearchClient(current, session), apply=True,
        )
    path = common.external_output(Path(candidate["candidate_config"]))
    if not path.is_relative_to(Path(graph["staging_directory"]).resolve()):
        raise ValueError("Candidate configuration escaped its approved staging directory.")
    selected = load_config(path)
    if config_fingerprint(selected) != candidate["candidate_config_sha256"]:
        raise ValueError("Candidate changed after approval.")

    def recheck():
        snapshots = client.inspect_selected(candidate["inventory"])
        if source_pins(snapshots) != candidate["source_pins"]:
            raise SyncConflict("Source content or permissions changed; stage a new delta cycle.")
        state.candidate(graph["scope_id"], args.epoch)

    if candidate["action"] != "recheck":
        state.mark_repair_required(graph["scope_id"], args.epoch)
    authorization = DelegatedAuthorization(selected["tenant_id"], AzureCliTokenProvider(
        selected["tenant_id"], selected["subscription_id"], config_dir=args.user_profile,
    ))
    proof = reconcile_native(
        selected, state=state, scope_id=graph["scope_id"], epoch=args.epoch,
        storage=StorageWriter(selected, session), source_reader=DelegatedRowStore(selected),
        search_admin=SearchClient(selected, session),
        search_reader=SearchClient(selected, ManagedIdentitySearchTransport(selected)),
        authorization=authorization, export_dir=path.parent / "real-chunk-evidence",
        source_recheck=recheck, content_changed=candidate["action"] == "content",
        permissions_changed=candidate["action"] == "permissions",
        apply=True, allow_paid=args.allow_paid,
    )
    write_json(Path(selected["publication_state"]), proof)
    # New binding is closed until complete commits the same epoch and native proof.
    write_json(config_path, read_json(path))
    state.complete(graph["scope_id"], args.epoch, selected, proof)
    return {"state": "ready", "epoch": args.epoch, "version": selected["version"],
            "complete_acl_acceptance": False,
            "agent_redeploy_required": config_fingerprint(selected) != config_fingerprint(current)}


def parser():
    import argparse
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=["plan", "init", "status", "poll", "reconcile", "subscribe", "renew", "recreate"])
    result.add_argument("--sync-config", type=Path, required=True)
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--apply", action="store_true")
    result.add_argument("--allow-paid", action="store_true")
    result.add_argument("--approved-candidate")
    result.add_argument("--epoch", type=int)
    result.add_argument("--subscription-id")
    result.add_argument("--force-renew", action="store_true",
                        help="Explicitly renew early to repair a reauthorization lifecycle hold.")
    result.add_argument("--user-profile", type=Path)
    result.add_argument("--output", type=Path)
    return result


def run(args):
    graph = load_sync(args.sync_config)
    current = load_config(args.config)
    if graph["tenant_id"] != current["tenant_id"]:
        raise ValueError("Graph source and sales publication must use the same tenant.")
    if args.command == "plan":
        return {
            "subscription": SubscriptionManager(graph, None, None).plan(),
            "scope_id": graph["scope_id"], "drive_id": graph["drive_id"],
            "serving_gate": guard(graph), "approval_required": True, "azure_mutations": False,
            "requires": ["Approved real source IDs and complete permission scan consent.",
                         "Reviewed Graph-to-Entra mapping and version-specific ADLS/Search ingestion rights.",
                         "Public HTTPS notification host; no host is created by this command."],
        }
    if args.command == "init":
        if not args.apply:
            raise ValueError("Enabling the closed synchronization gate requires --apply.")
        state = SyncState(Path(graph["database"]))
        state.initialize(graph["scope_id"], graph["tenant_id"], graph["drive_id"])
        state.signal_many([(graph["scope_id"], "initial-sync-required")])
        raw = read_json(args.config)
        raw["graph_sync"] = guard(graph)
        write_json(common.external_output(args.config), raw)
        return state.status(graph["scope_id"])
    if not Path(graph["database"]).is_file() or current.get("graph_sync") != guard(graph):
        raise ValueError("Initialize the exact synchronization scope and serving gate first.")
    state = SyncState(Path(graph["database"]))
    row = state.scope(graph["scope_id"])
    if row["tenant_id"] != graph["tenant_id"] or row["drive_id"] != graph["drive_id"]:
        raise ValueError("Synchronization database belongs to another Graph source.")
    if args.command == "status":
        return state.status(graph["scope_id"])
    session, _ = common.operator(current)
    if args.command in {"subscribe", "renew", "recreate"}:
        manager = SubscriptionManager(graph, session, state)
        if args.command == "renew":
            return manager.renew(args.subscription_id, apply=args.apply, force=args.force_renew)
        secret = client_state_from_env(graph["client_state_environment"]) if args.apply else None
        if args.command == "recreate":
            return manager.recreate(args.subscription_id, secret, apply=args.apply)
        return manager.create(secret, apply=args.apply)
    if args.command == "poll":
        state.signal_many([(graph["scope_id"], "graph-source-preflight")])
    drive = session.request(
        "GET", "https://graph.microsoft.com/v1.0/drives/" + quote(graph["drive_id"], safe="") + "?$select=id,driveType",
        audience="https://graph.microsoft.com",
    )
    if drive.get("id") != graph["drive_id"] or drive.get("driveType") != graph["drive_type"]:
        raise ValueError("Live drive identity/type differs from the configured business source.")
    client = GraphDeltaClient(graph, BinaryGraphTransport(graph, session))
    if args.command == "poll":
        return stage_round(graph, current, state, client)
    return reconcile(graph, current, args.config.resolve(), state, client, args, session)


if __name__ == "__main__":
    args = parser().parse_args()
    report = run(args)
    if args.output:
        write_json(common.external_output(args.output), report)
    print(json.dumps(report, indent=2))
