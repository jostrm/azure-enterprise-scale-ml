"""Reviewed factory deletion through the existing scoped provider workers.

Loaded by factory_lifecycle with its own lifecycle context so pinned distributions
and offline consumers use the same validation, identities, leases and receipts.
"""

import copy
import json
import re
import time
from urllib.parse import quote, unquote, urlsplit


CONTRACT = "ordered-project-pipelines-v1"
HUB_CONTRACT = "factory-owned-access-hub-v1"
DELETE_FLAGS = ("enableDeleteForDisabledResources", "deleteAllServicesForProject",
                "deleteKeyvaultAlso", "deleteAllForProject")
# Reusable VPN/hub/connectivity platform types. Only a factory's own bootstrap-built VPN gateway,
# Bastion and DNS private resolver may be deleted, and only with bootstrap proof; site links,
# vWAN and ExpressRoute constructs always stay protected.
PROTECTED_TYPES = {
    "microsoft.network/virtualnetworkgateways", "microsoft.network/vpngateways",
    "microsoft.network/vpnsites", "microsoft.network/virtualhubs",
    "microsoft.network/virtualwans", "microsoft.network/bastionhosts",
    "microsoft.network/expressroutecircuits", "microsoft.network/connections",
    "microsoft.network/p2svpngateways", "microsoft.network/vpnserverconfigurations",
    "microsoft.network/localnetworkgateways", "microsoft.network/dnsresolvers",
    "microsoft.network/dnsforwardingrulesets",
}
HUB_DELETABLE_TYPES = {"microsoft.network/virtualnetworkgateways", "microsoft.network/bastionhosts",
                       "microsoft.network/dnsresolvers", "microsoft.network/dnsforwardingrulesets"}
# Child resources that attach a hub to a network; each must target only this factory's VNets.
HUB_LINK_TARGETS = {
    "microsoft.network/privatednszones/virtualnetworklinks": "virtualNetwork",
    "microsoft.network/dnsforwardingrulesets/virtualnetworklinks": "virtualNetwork",
    "microsoft.network/virtualnetworks/virtualnetworkpeerings": "remoteVirtualNetwork",
}
HUB_SOURCE = "access-hub-bootstrap-record"
# A hub-connected factory's bootstrap-recorded peerings and DNS links inside a shared hub.
SHARED_HUB_CONTRACT = "shared-hub-spoke-links-v1"
VNET_TYPE = "microsoft.network/virtualnetworks"
fl = None


def validate_flags(flags):
    fl.require(isinstance(flags, dict) and set(flags) == set(DELETE_FLAGS)
               and all(flags[name] is True for name in DELETE_FLAGS),
               "factory-delete-flags-must-all-be-true")


def phase(item):
    kind = item.get("type", "").lower()
    if fl.RG_ID.fullmatch(item["id"]):
        return 4
    if kind.endswith("/capabilityhosts"):
        return 0
    if kind == "microsoft.search/services/sharedprivatelinkresources":
        return 1
    if kind.startswith("microsoft.network/"):
        return 3
    return 2


def ordered_resources(rows):
    deleted = {row["id"].lower(): copy.deepcopy(row) for row in rows if row["delete"]}
    inherited = {}
    for row in deleted.values():
        parent = str(row.get("delete_via_parent", "")).lower()
        if parent in deleted:
            # A child deleted through its parent leaves with it, so the parent precedes what the child must.
            inherited.setdefault(parent, set()).update(
                value.lower() for value in row.get("depends_on", []) if value.lower() in deleted
                and not _overlaps(value.lower(), parent))
    for identifier, row in deleted.items():
        dependencies = {value.lower() for value in row.get("depends_on", []) if value.lower() in deleted}
        dependencies.update(inherited.get(identifier, ()))
        dependencies.update(parent for parent in deleted if identifier.startswith(parent + "/"))
        fl.require(all(phase(row) <= phase(deleted[value]) for value in dependencies),
                   "factory-delete-phase-dependency-conflict")
        row["depends_on"] = sorted(dependencies)
    ordered = []
    for step in range(5):
        ordered.extend(fl.deletion_order([row for row in deleted.values() if phase(row) == step]))
    return ordered


def marked_protected(body):
    tags = {str(k).lower(): str(v).lower() for k, v in (body.get("tags") or {}).items()}
    return (fl.project_resource_shared(body)
            or any(tags.get("aifactory." + name) == "true" for name in ("bootstrap", "platform", "protected", "reusable")))


def protected(body, explicit, hub=None):
    key, kind = body["id"].lower(), str(body.get("type", "")).lower()
    return (any(key == identifier or key.startswith(identifier + "/") for identifier in explicit)
            or marked_protected(body)
            or (kind == "microsoft.machinelearningservices/workspaces" and str(body.get("kind", "")).lower() == "hub")
            or (kind in PROTECTED_TYPES and not (kind in HUB_DELETABLE_TYPES and hub_covers(hub, key))))


def access_hub(document):
    """Catalog-built proof that bootstrap records, not names/tags, tie a hub to exactly this target."""
    hub = document.get("access_hub_ownership")
    if hub is None:
        return None
    target, scopes = document["target"], {scope.lower() for scope in document["locks"]["scopes"]}

    def ids(values, pattern):
        return (isinstance(values, list) and values and values == sorted(set(values))
                and all(isinstance(value, str) and value == value.lower() and pattern.fullmatch(value)
                        for value in values))

    fl.require(isinstance(hub, dict) and hub.get("contract") == HUB_CONTRACT
               and all(hub.get(key) == target[key] for key in ("factory_id", "scaleset_id", "subscription_id"))
               and hub.get("mode") in ("integrated", "external")
               and ids(hub.get("resource_group_ids"), fl.RG_ID) and set(hub["resource_group_ids"]) <= scopes
               and ids(hub.get("resource_ids"), fl.NESTED_ID)
               and all(fl.arm_scope(value) in hub["resource_group_ids"] for value in hub["resource_ids"])
               and ids(hub.get("factory_resource_groups"), fl.RG_ID) and scopes <= set(hub["factory_resource_groups"])
               and isinstance(hub.get("evidence"), dict) and fl.guid(hub["evidence"].get("workflow_id"))
               and fl.hash_value(hub["evidence"].get("record_hash"))
               and (hub["mode"] == "integrated" or not any(
                   fl.resource_type_from_id(value) in HUB_DELETABLE_TYPES for value in hub["resource_ids"])),
               "factory-delete-access-hub-proof-invalid")
    return hub


def hub_covers(hub, key):
    return bool(hub) and any(key == root or key.startswith(root + "/") for root in hub["resource_ids"])


def verify_access_hub_network(hub, bodies, links=None):
    """Deleting a factory-owned hub must not cut DNS, peering or site links of anything else.

    The one exception is the factory side of a peering pair whose hub side the shared-hub
    link proof records: the hub VNet that this factory's bootstrap peered back to it.
    """
    if not hub:
        return
    allowed = set(hub["factory_resource_groups"])
    pairs = {(row["id"].rsplit("/virtualnetworkpeerings/", 1)[0], row["remote_virtual_network_id"])
             for row in (links or {}).get("links", []) if row["type"] == PEERING_TYPE}
    for key, body in bodies.items():
        if fl.RG_ID.fullmatch(key) or fl.arm_scope(key) not in hub["resource_group_ids"]:
            continue
        kind = fl.resource_type_from_id(key)
        fl.require(kind != "microsoft.network/connections", "factory-delete-access-hub-external-connection")
        if kind in HUB_LINK_TARGETS:
            remote = ((body.get("properties") or {}).get(HUB_LINK_TARGETS[kind]) or {}).get("id")
            fl.require(isinstance(remote, str) and fl.RG_ID.match(remote)
                       and (fl.arm_scope(remote.lower()) in allowed
                            or kind == PEERING_TYPE and (remote.lower(), key.rsplit("/virtualnetworkpeerings/", 1)[0])
                            in pairs), "factory-delete-access-hub-foreign-link")


def shared_hub_links(document):
    """Catalog-built proof that consumed bootstrap records created these links inside a shared hub.

    Each link sits in a protected connectivity hub group outside every deletion scope and
    targets a VNet inside this manifest's writable scopes; nothing else in the hub qualifies.
    """
    proof = document.get("shared_hub_links")
    if proof is None:
        return None
    target, locks = document["target"], document["locks"]
    scopes = {scope.lower() for scope in locks["scopes"]}
    closure = scopes | {scope.lower() for scope in locks["common_dependencies"]}
    explicit = {value.lower() for value in document.get("protected_resource_ids", []) if isinstance(value, str)}
    links = proof.get("links") if isinstance(proof, dict) else None
    fl.require(isinstance(proof, dict) and proof.get("contract") == SHARED_HUB_CONTRACT
               and all(proof.get(key) == target[key] for key in ("factory_id", "scaleset_id", "subscription_id"))
               and _sorted_ids(proof.get("hub_resource_group_ids"), fl.RG_ID)
               and set(proof["hub_resource_group_ids"]) <= explicit
               and not any(_overlaps(group, scope) for group in proof["hub_resource_group_ids"] for scope in closure)
               and isinstance(links, list) and links and all(isinstance(row, dict) for row in links)
               and [row.get("id") for row in links] == _sorted_unique([row.get("id") for row in links])
               and all(set(row) == {"id", "type", "remote_virtual_network_id"}
                       and _sorted_ids([row["id"]], fl.NESTED_ID) and row["type"] in HUB_LINK_TARGETS
                       and row["type"] == fl.resource_type_from_id(row["id"])
                       and fl.arm_scope(row["id"]) in proof["hub_resource_group_ids"]
                       and _sorted_ids([row["remote_virtual_network_id"]], fl.NESTED_ID)
                       and fl.resource_type_from_id(row["remote_virtual_network_id"]) == VNET_TYPE
                       and fl.arm_scope(row["remote_virtual_network_id"]) in scopes for row in links)
               and isinstance(proof.get("evidence"), dict) and fl.guid(proof["evidence"].get("workflow_id"))
               and fl.hash_value(proof["evidence"].get("record_hash")),
               "factory-delete-shared-hub-links-proof-invalid")
    return proof


def _sorted_unique(values):
    return sorted(set(values)) if all(isinstance(value, str) for value in values) else None


def _vnets(entries, deleted_only=False):
    return {key for key, row in entries.items() if not fl.RG_ID.fullmatch(key)
            and fl.resource_type_from_id(key) == VNET_TYPE and (row["delete"] or not deleted_only)}


def freeze_shared_hub_links(cloud, proof, entries):
    """Recorded hub links to a VNet this manifest deletes; links nobody can prove stay, reported."""
    deleted, vnets = _vnets(entries, deleted_only=True), _vnets(entries)
    recorded = {row["id"]: row for row in proof["links"]}
    live, _ = _hub_inventory(cloud, proof["hub_resource_group_ids"], "factory-delete-hub-inventory-incomplete")
    removable, retained = [], []
    for row in live:
        expected = recorded.get(row["id"].lower())
        remote = row["remote_virtual_network_id"]
        if expected is None:
            if remote in vnets:
                retained.append(row["id"])
            continue
        # A recorded link that now points elsewhere, or at a VNet this cohort keeps, is ambiguous.
        fl.require(remote == expected["remote_virtual_network_id"], "factory-delete-hub-link-changed")
        fl.require(remote in deleted or remote not in vnets, "factory-delete-hub-link-remote-retained")
        if remote in deleted:
            removable.append(row)
        else:
            retained.append(row["id"])  # Its VNet was already gone before this cohort: not ours to cut.
    return sorted(removable, key=lambda row: row["id"].lower()), sorted(retained, key=str.lower)


def validate_shared_hub_links(data, proof, entries):
    if not proof:
        fl.require("hub_links" not in data and "retained_hub_links" not in data,
                   "factory-delete-shared-hub-links-unproven")
        return
    recorded = {row["id"]: row for row in proof["links"]}
    links, retained = data.get("hub_links"), data.get("retained_hub_links")
    fl.require(isinstance(links, list) and all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in links)
               and isinstance(retained, list) and all(isinstance(value, str) for value in retained)
               and [row["id"].lower() for row in links] == _sorted_unique([row["id"].lower() for row in links])
               and [value.lower() for value in retained] == _sorted_unique([value.lower() for value in retained])
               and not {row["id"].lower() for row in links} & {value.lower() for value in retained},
               "factory-delete-hub-links-invalid")
    for row in links:
        expected = recorded.get(row["id"].lower())
        fl.require(expected is not None and set(row) == {"id", "type", "api_version", "remote_virtual_network_id", "side"}
                   and row["side"] == "hub" and row["type"] == expected["type"]
                   and row["api_version"] == HUB_LINK_COLLECTIONS[row["type"].rsplit("/", 1)[0]][1]
                   and row["remote_virtual_network_id"] == expected["remote_virtual_network_id"]
                   and entries.get(row["remote_virtual_network_id"], {}).get("delete") is True,
                   "factory-delete-hub-links-invalid")
    fl.require(all(fl.RG_ID.match(value) and fl.arm_scope(value.lower()) in proof["hub_resource_group_ids"]
                   for value in retained), "factory-delete-hub-links-invalid")


def require_unique_hub_links(documents):
    links = [row["id"].lower() for document in documents for row in document["deletion"].get("hub_links", [])]
    fl.require(len(set(links)) == len(links), "factory-delete-hub-link-overlap")


def unlink_shared_hub(cloud, locks, document, receipt, persist, sleep=time.sleep):
    """Last step: remove the recorded hub-side links only once their spoke VNet is verifiably gone."""
    data = document["deletion"]
    removed = {value.lower() for value in receipt.setdefault("deleted_hub_links", [])}
    deleted = {value.lower() for value in receipt["deleted_resources"]}
    versions = {row["id"].lower(): row["api_version"] for row in data["resources"]}
    for link in data["hub_links"]:
        if link["id"].lower() in removed:
            continue
        remote = link["remote_virtual_network_id"]
        fl.require(remote in deleted, "factory-delete-hub-link-before-spoke")
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        status, _, _ = cloud.arm("GET", remote, versions[remote], allowed=(200, 404))
        fl.require(status == 404, "factory-delete-hub-link-spoke-present")
        status, _, body = cloud.arm("GET", link["id"], link["api_version"], allowed=(200, 404))
        if status != 404:
            # Azure usually clears a deleted VNet's DNS links itself; a hub peering stays Disconnected.
            fl.require(_remote(body) == remote, "factory-delete-hub-link-changed")
            verify_link_permissions(cloud, [link])
            locks.authorize(document)
            receipt.update(mutation_started=True, pending_resource=link["id"])
            persist()
            cloud.arm("DELETE", link["id"], link["api_version"], allowed=(200, 202, 204, 404),
                      headers={"If-Match": body["etag"]} if body.get("etag") else None)
            fl.wait_absent(cloud, locks, link["id"], link["api_version"], sleep)
            receipt.pop("pending_resource", None)
        receipt["deleted_hub_links"].append(link["id"])
        removed.add(link["id"].lower())
        persist()
    receipt["hub_unlink_complete"] = True
    persist()


def teardown_order(document, rows):
    """Bootstrap hub and private runner closure last, after every other reviewed deletion."""
    hub = access_hub(document)
    deleted = {row["id"].lower(): row for row in rows if row["delete"]}
    late = {key for key in deleted if hub_covers(hub, key)}
    pending = list(late)
    while pending:
        key = pending.pop()
        for value in [*deleted[key].get("depends_on", []), *(parent for parent in deleted if key.startswith(parent + "/"))]:
            if value.lower() in deleted and value.lower() not in late:
                late.add(value.lower())
                pending.append(value.lower())
    if not late:
        return ordered_resources(rows)
    return (ordered_resources([row for row in rows if row["id"].lower() not in late])
            + ordered_resources([row for row in rows if row["id"].lower() in late]))


def validate_route(document):
    route = document["route"]
    fl.require(not fl.single_writer(document), "factory-delete-blob-coordination-required")
    fl.require(fl.guid(document["identity"].get("deployment_object_id")), "bound-deployment-principal-required")
    fl.require(route.get("scoped_contract") == 1
               and isinstance(route.get("auth_namespace"), str)
               and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", route["auth_namespace"]),
               "namespaced-route-required")
    runner = route.get("runner", {})
    fl.require(runner.get("os") == "linux" and runner.get("kind") in ("hosted", "self-hosted"),
               "explicit-linux-scoped-runner-required")
    if runner["kind"] == "hosted":
        fl.require(runner.get("image") in ("ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"),
                   "unsupported-hosted-runner-image")
    elif route["kind"] == "gha":
        labels = runner.get("labels")
        fl.require(isinstance(labels, list) and 2 <= len(labels) <= 16
                   and all(isinstance(label, str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", label) for label in labels)
                   and {"self-hosted", "linux"} <= {label.lower() for label in labels},
                   "explicit-self-hosted-labels-required")
    else:
        fl.require(isinstance(runner.get("pool"), str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", runner["pool"]),
                   "explicit-ado-agent-pool-required")


def normalize_projects(document, projects):
    fl.require(isinstance(projects, list), "factory-delete-registered-projects-required")
    normalized = []
    for project in projects:
        fl.require(isinstance(project, dict) and fl.guid(project.get("project_id"))
                   and isinstance(project.get("project_number"), str)
                   and re.fullmatch(r"[0-9]{3}", project["project_number"])
                   and project["project_number"] != "000", "factory-delete-project-identity-required")
        ids = project.get("registered_resource_ids")
        fl.require(isinstance(ids, list) and ids and all(isinstance(value, str)
                   and (fl.RG_ID.fullmatch(value) or fl.NESTED_ID.fullmatch(value)) for value in ids),
                   "factory-delete-registered-resources-required")
        normalized.append({"project_id": project["project_id"], "project_number": project["project_number"],
                           "registered_resource_ids": sorted(set(value.lower() for value in ids))})
    fl.require(len({row["project_id"] for row in normalized}) == len(normalized)
               and len({row["project_number"] for row in normalized}) == len(normalized)
               and sorted(row["project_number"] for row in normalized) == sorted(document["target"]["project_ids"]),
               "factory-delete-project-registration-mismatch")
    return sorted(normalized, key=lambda row: row["project_number"])


def freeze(cloud, document, ownership_records, registered_projects):
    validate_route(document)
    projects = normalize_projects(document, registered_projects)
    cloud.verify_identity()
    fl.BlobLocks(cloud, document).verify_enrollment()
    scopes = sorted(set(document["locks"]["scopes"] + document["locks"]["common_dependencies"]), key=str.lower)
    writable = {scope.lower() for scope in document["locks"]["scopes"]}
    hub, links = access_hub(document), shared_hub_links(document)
    closure, bodies = fl.collect_resource_closure(cloud, scopes)
    # The operator executes common teardown; it must never sit on anything in scope.
    fl.verify_deletion_identity(document, bodies)
    verify_access_hub_network(hub, bodies, links)
    explicit = document.get("protected_resource_ids", [])
    fl.require(isinstance(explicit, list) and all(isinstance(value, str)
               and (fl.RG_ID.fullmatch(value) or fl.NESTED_ID.fullmatch(value)) for value in explicit),
               "factory-delete-protected-identities-invalid")
    explicit = {value.lower() for value in explicit}
    project_map = {row["project_number"]: row for row in projects}
    core_owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    entries = {}
    # Explicit catalog receipts only, like the sibling deletion freezes; never manifest-embedded copies.
    fl.require(isinstance(ownership_records, dict), "factory-delete-ownership-records-required")
    records = {key.lower(): value for key, value in ownership_records.items()}
    cache = {}
    for key, body in bodies.items():
        tags = body.get("tags") or {}
        owner = {field: tags[tag] for field, tag in fl.TAG_KEYS.items() if tag in tags}
        proof = {"ownership_source": "tags", "owner": owner}
        if not owner and key in records:
            evidence = records[key]
            owner = fl.verified_receipt_owner(fl.BlobLocks(cloud, document),
                                             evidence.get("ownership_evidence"), key, fl.digest(body), cache)
            fl.require(owner == evidence.get("owner"), "factory-delete-receipt-owner-mismatch")
            proof = {**evidence, "owner": owner}
        if hub_covers(hub, key):
            fl.require(not marked_protected(body), "factory-delete-access-hub-marked-protected")
            fl.require(all(owner.get(field, value) == value for field, value in core_owner.items()),
                       "factory-delete-access-hub-owner-conflict")
            if not owner:
                owner = dict(core_owner)
                proof = {"ownership_source": HUB_SOURCE, "owner": owner,
                         "ownership_evidence": copy.deepcopy(hub["evidence"])}
        number = owner.get("project_id")
        owned = all(owner.get(field) == value for field, value in core_owner.items())
        selected = owned and (not number or number in project_map)
        if number in project_map and owned:
            logical = tags.get("aifactory.logical_project_id")
            fl.require(not logical or logical == project_map[number]["project_id"],
                       "factory-delete-logical-project-mismatch")
            registered = project_map[number]["registered_resource_ids"]
            fl.require(any(key == value or key.startswith(value + "/") for value in registered),
                       "factory-delete-project-resource-unregistered")
        metadata = closure["groups"].get(key, closure["resources"].get(key))
        keep = protected(body, explicit, hub)
        if key in explicit:
            fl.require(not selected, "factory-delete-protected-resource-selected")
        entries[key] = {"id": body["id"], **metadata, **proof,
                        "delete": selected and fl.arm_scope(key) in writable and not keep,
                        "project_number": number if owned and number in project_map else None,
                        "managed_group_ids": sorted(fl.managed_group_cascades(
                            body, document["target"]["subscription_id"])),
                        "depends_on": fl.project_resource_dependencies(body)}
        if not entries[key]["delete"]:
            entries[key]["retention_reason"] = ("protected-infrastructure" if keep else
                "outside-registered-ownership" if not selected else "read-only-dependency")
        if selected and key in closure["resources"] and entries[key]["delete"]:
            fl.require(not str(metadata["type"]).lower() in
                       ("microsoft.authorization/locks", "microsoft.authorization/denyassignments"),
                       "factory-delete-lock-or-deny-present")
    for project in projects:
        owner = {**core_owner, "project_id": project["project_number"]}
        matches = [key for key in closure["groups"] if entries[key]["owner"] == owner
                   and key in project["registered_resource_ids"]]
        fl.require(len(matches) == 1, "factory-delete-exact-project-group-required")
        project["resource_group_id"] = matches[0]
        fl.require(all(entry["owner"] == owner or protected(bodies[key], explicit, hub) for key, entry in entries.items()
                       if fl.arm_scope(key) == matches[0]), "factory-delete-project-group-shared-or-unowned")
    # The deployment principal runs only project stages; it may sit solely on bootstrap-proven
    # common hub/runner resources, which the operator tears down after the project barrier.
    worker = copy.deepcopy(document)
    worker["identity"]["object_id"] = document["identity"]["deployment_object_id"]
    fl.verify_deletion_identity(worker, {key: body for key, body in bodies.items()
                                         if not (hub_covers(hub, key) and entries[key]["project_number"] is None)})
    # Retained shared infrastructure prevents deletion of its ancestors and dependencies.
    changed = True
    while changed:
        changed = False
        for key, item in entries.items():
            if not item["delete"]:
                for candidate, other in entries.items():
                    if other["delete"] and (key.startswith(candidate + "/") or candidate in item["depends_on"]):
                        fl.require(other["project_number"] is None or fl.RG_ID.fullmatch(candidate),
                                   "factory-delete-retained-project-dependency")
                        other["delete"] = False
                        other["retention_reason"] = "retained-resource-dependency"
                        changed = True
    operations = {}
    for key, item in entries.items():
        if not item["delete"] or key in closure["groups"]:
            continue
        namespace = item["type"].split("/", 1)[0]
        if namespace not in operations:
            operations[namespace] = set(cloud.provider_operations(namespace))
        item["independent_delete"] = item["type"].lower() + "/delete" in operations[namespace]
    for key, item in entries.items():
        if not item["delete"] or key in closure["groups"] or item["independent_delete"]:
            continue
        parents = [parent for parent, candidate in entries.items() if key.startswith(parent + "/")
                   and candidate["delete"] and candidate.get("independent_delete") is True]
        fl.require(parents and phase(item) not in (0, 1), "factory-delete-service-lifecycle-unsupported")
        item["delete_via_parent"] = max(parents, key=len)
    resources = [entries[key] for key in sorted(closure["resources"])]
    groups = [entries[key] for key in sorted(closure["groups"])]
    data = {"inventory_mode": CONTRACT, "inventory_complete": True, "revision": document["manifest_revision"],
            "flags": dict.fromkeys(DELETE_FLAGS, True), "projects": projects, "resource_groups": groups,
            "resources": resources, "inventory_hash": fl.digest(resources), "closure": closure,
            "closure_hash": fl.digest(closure), "bodies": bodies, "protected_resource_ids": sorted(explicit),
            "configuration_hash": fl.digest(document["config"]),
            "route_hash": fl.digest(document["route"]), "source_hash": fl.digest(document["source"])}
    if hub:
        data["access_hub_hash"] = fl.digest(hub)
    if links:
        data["hub_links"], data["retained_hub_links"] = freeze_shared_hub_links(cloud, links, entries)
        data["shared_hub_links_hash"] = fl.digest(links)
    validate({**document, "deletion": data})
    for scope in scopes:
        cloud.assert_no_active_deployments(scope)
    verify_permissions(cloud, data)
    verify_link_permissions(cloud, data.get("hub_links", []))
    return data


def validate(document):
    validate_route(document)
    data = document["deletion"]
    validate_flags(data.get("flags"))
    fl.require(data.get("inventory_mode") == CONTRACT and data.get("inventory_complete") is True
               and data.get("revision") == document["manifest_revision"], "factory-delete-frozen-inventory-required")
    fl.require(data.get("configuration_hash") == fl.digest(document["config"])
               and data.get("route_hash") == fl.digest(document["route"])
               and data.get("source_hash") == fl.digest(document["source"]), "factory-delete-plan-binding-changed")
    hub, links = access_hub(document), shared_hub_links(document)
    fl.require(data.get("access_hub_hash") == (fl.digest(hub) if hub else None)
               and data.get("shared_hub_links_hash") == (fl.digest(links) if links else None),
               "factory-delete-plan-binding-changed")
    projects = normalize_projects(document, data.get("projects"))
    fl.require([row["project_number"] for row in projects] ==
               [row["project_number"] for row in data["projects"]], "factory-delete-project-order-changed")
    fl.require(data.get("inventory_hash") == fl.digest(data.get("resources"))
               and data.get("closure_hash") == fl.digest(data.get("closure"))
               and isinstance(data.get("bodies"), dict), "factory-delete-inventory-hash-mismatch")
    groups, resources = data["resource_groups"], data["resources"]
    expected_scopes = {scope.lower() for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]}
    fl.require({row["id"].lower() for row in groups} == expected_scopes, "factory-delete-scope-mismatch")
    entries = {row["id"].lower(): row for row in groups + resources}
    fl.require(len(entries) == len(groups + resources) and set(entries) == set(data["bodies"]),
               "factory-delete-complete-inventory-required")
    fl.protect_coordination_storage(document)
    verify_access_hub_network(hub, data["bodies"], links)
    validate_shared_hub_links(data, links, entries)
    for key, row in entries.items():
        fl.require(type(row.get("delete")) is bool and row.get("body_hash") == fl.digest(data["bodies"][key]),
                   "factory-delete-resource-fingerprint-required")
        owner_number = row.get("owner", {}).get("project_id")
        owned = all(row.get("owner", {}).get(field) == document["target"][field]
                    for field in ("factory_id", "scaleset_id"))
        expected_number = owner_number if owned and owner_number in document["target"]["project_ids"] else None
        fl.require(row.get("project_number") == expected_number, "factory-delete-project-stage-mismatch")
        if not row["delete"]:
            continue
        fl.require(fl.arm_scope(key) in {scope.lower() for scope in document["locks"]["scopes"]}
                   and all(row.get("owner", {}).get(field) == document["target"][field]
                           for field in ("factory_id", "scaleset_id")),
                   "factory-delete-resource-owner-mismatch")
        fl.require(not protected(data["bodies"][key], data["protected_resource_ids"], hub),
                   "factory-delete-protected-resource-selected")
        fl.require(row.get("ownership_source") != HUB_SOURCE or (hub_covers(hub, key) and row["owner"] == {
            field: document["target"][field] for field in ("factory_id", "scaleset_id")}),
                   "factory-delete-access-hub-owner-unproven")
        fl.require(not owner_number or owner_number in document["target"]["project_ids"],
                   "factory-delete-project-owner-unregistered")
        fl.require(row.get("managed_group_ids", []) == sorted(fl.managed_group_cascades(
            data["bodies"][key], document["target"]["subscription_id"])), "factory-delete-managed-cascade-changed")
        fl.require(all(scope in entries and all(child["delete"] and child.get("project_number") == expected_number
                       for child in entries.values() if fl.arm_scope(child["id"]) == scope)
                       for scope in row.get("managed_group_ids", [])),
                   "factory-delete-implicit-managed-group-forbidden")
        if expected_number is None:
            fl.require(not any(entries.get(value.lower(), {}).get("project_number") is not None
                               for value in row["depends_on"]), "factory-delete-common-before-project-dependency")
        fl.require(all(child["delete"] for other, child in entries.items()
                       if other.startswith(key + "/")), "factory-delete-retained-child")
        if not fl.RG_ID.fullmatch(key):
            fl.require(type(row.get("independent_delete")) is bool, "factory-delete-provider-delete-proof-required")
            if not row["independent_delete"]:
                parent = row.get("delete_via_parent", "")
                fl.require(parent in entries and key.startswith(parent + "/")
                           and entries[parent]["delete"] and entries[parent].get("independent_delete") is True
                           and not fl.RG_ID.fullmatch(parent) and phase(row) not in (0, 1),
                           "factory-delete-service-cascade-unreviewed")
    ordered_resources(groups + resources)


def verify_permissions(cloud, data, absent=()):
    # Check every independent DELETE, not merely an RG cascade permission.
    for item in data["resources"] + data["resource_groups"]:
        if (item["delete"] and not item.get("delete_via_parent")
                and item["id"].lower() not in {value.lower() for value in absent}):
            fl.verify_project_permissions(cloud, {"resource_groups": [item] if fl.RG_ID.fullmatch(item["id"]) else [],
                                                  "resources": [] if fl.RG_ID.fullmatch(item["id"]) else [item]})


def project_rows(document):
    return [row for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]
            if row["delete"] and row.get("project_number") in document["target"]["project_ids"]]


def verify_worker_result(document, result):
    expected = {row["id"].lower() for row in project_rows(document)}
    fl.require(isinstance(result, dict) and result.get("schema") == 1 and result.get("status") == "succeeded"
               and result.get("run_id") == document["run_id"]
               and result.get("manifest_hash") == document["manifest_hash"]
               and result.get("source_commit") == document["source"]["commit"]
               and result.get("target") == document["target"], "factory-delete-worker-binding-unverified")
    fl.require(result.get("flags") == document["deletion"]["flags"]
               and all(value is True for value in result.get("flags", {}).values())
               and result.get("project_numbers") == document["target"]["project_ids"]
               and isinstance(result.get("deleted_resources"), list)
               and {value.lower() for value in result["deleted_resources"]} == expected,
               "factory-delete-worker-incomplete")
    fl.require(result.get("projects") == completed_projects(document), "factory-delete-project-evidence-incomplete")
    return result


def completed_projects(document):
    return [{"project_id": project["project_id"], "project_number": project["project_number"],
             "status": "succeeded", "deleted_resources": sorted(row["id"].lower() for row in project_rows(document)
                 if row["project_number"] == project["project_number"])}
            for project in document["deletion"]["projects"]]


def observed_absent(cloud, document):
    absent = []
    for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]:
        if row["delete"]:
            api = fl.RG_API if fl.RG_ID.fullmatch(row["id"]) else row["api_version"]
            status, _, _ = cloud.arm("GET", row["id"], api, allowed=(200, 404))
            if status == 404:
                absent.append(row["id"])
    return absent


def delete_rows(cloud, locks, document, receipt, persist, rows, sleep=time.sleep, fresh=None):
    flags = document["deletion"]["flags"]
    validate_flags(flags)
    entries = document["deletion"]["resources"] + document["deletion"]["resource_groups"]
    removed = {value.lower() for value in receipt.get("deleted_resources", []) + receipt.get("observed_absent", [])}
    for row in teardown_order(document, rows):
        key = row["id"].lower()
        if key in removed:
            if key not in {value.lower() for value in receipt.get("deleted_resources", [])}:
                receipt.setdefault("deleted_resources", []).append(row["id"])
                persist()
            continue
        if row.get("delete_via_parent"):
            continue
        fl.require(flags["enableDeleteForDisabledResources"] is True
                   and flags["deleteAllServicesForProject"] is True,
                   "factory-delete-services-not-enabled")
        if row.get("type", "").startswith("microsoft.keyvault/"):
            fl.require(flags["deleteKeyvaultAlso"] is True, "factory-delete-keyvault-not-enabled")
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        api = fl.RG_API if fl.RG_ID.fullmatch(key) else row["api_version"]
        status, _, body = cloud.arm("GET", row["id"], api, allowed=(200, 404))
        if status == 404:
            # Only frozen, reviewed resources may become idempotently absent.
            removed.add(key)
            receipt.setdefault("deleted_resources", []).append(row["id"])
            for child in entries:
                if child["id"].lower().startswith(key + "/") and child["id"].lower() not in removed:
                    fl.require(child["delete"] and child.get("delete_via_parent") == key,
                               "factory-delete-unreviewed-service-cascade")
                    fl.wait_absent(cloud, locks, child["id"], child["api_version"], sleep)
                    removed.add(child["id"].lower())
                    receipt["deleted_resources"].append(child["id"])
            persist()
            continue
        if fresh:
            fresh(row, body)
        else:
            fl.verify_project_inventory(cloud, document, removed)
        if fl.RG_ID.fullmatch(key):
            fl.require(flags["deleteAllForProject"] is True, "factory-delete-group-not-enabled")
            fl.require(all(child["id"].lower() in removed for child in entries
                           if child["id"].lower().startswith(key + "/")),
                       "factory-delete-project-rg-shortcut-forbidden")
            fl.require(not cloud.list_resources(row["id"]), "factory-delete-group-not-empty")
        verify_permissions(cloud, {"resource_groups": [row] if fl.RG_ID.fullmatch(key) else [],
                                   "resources": [] if fl.RG_ID.fullmatch(key) else [row]})
        locks.authorize(document)
        receipt.update(mutation_started=True, pending_resource=row["id"])
        persist()
        cloud.arm("DELETE", row["id"], api, allowed=(200, 202, 204, 404),
                  headers={"If-Match": body["etag"]} if body.get("etag") else None)
        fl.wait_absent(cloud, locks, row["id"], api, sleep)
        removed.add(key)
        receipt.setdefault("deleted_resources", []).append(row["id"])
        for child in entries:
            if child["id"].lower().startswith(key + "/") and child["id"].lower() not in removed:
                fl.require(child["delete"] and child.get("delete_via_parent") == key,
                           "factory-delete-unreviewed-service-cascade")
                fl.wait_absent(cloud, locks, child["id"], child["api_version"], sleep)
                removed.add(child["id"].lower())
                receipt["deleted_resources"].append(child["id"])
        for scope in row.get("managed_group_ids", []):
            for child in entries:
                if fl.arm_scope(child["id"]) == scope and child["id"].lower() not in removed:
                    fl.wait_absent(cloud, locks, child["id"], fl.RG_API if fl.RG_ID.fullmatch(child["id"])
                                   else child["api_version"], sleep)
                    removed.add(child["id"].lower())
                    receipt["deleted_resources"].append(child["id"])
        receipt.pop("pending_resource", None)
        persist()
    return removed


def run_worker(envelope, source_root, expected_run, expected_hash, cloud=None, sleep=time.sleep):
    document = fl._validate_manifest(envelope.get("manifest"))
    fl.require(document["run_id"] == expected_run and document["manifest_hash"] == expected_hash,
               "worker-run-binding-mismatch")
    context = envelope.get("lease_context")
    scopes = {scope.lower() for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]}
    fl.require(isinstance(context, dict) and set(context) == scopes
               and all(fl.guid(value) for value in context.values()), "worker-lease-context-required")
    if cloud is None:
        fl.require(fl.sys.platform.startswith("linux"), "linux-scoped-worker-required")
    cloud = cloud or fl.Cloud(document, expected_object_id=document["identity"]["deployment_object_id"])
    cloud.verify_identity(require_default=True)
    locks = fl.BlobLocks(cloud, document)
    locks.held = dict(context)
    locks.verify_enrollment()
    locks.execution_claim = fl._ExecutionClaim(document, locks.read_claim())
    locks.authorize(document)
    fl._verify_source(cloud, source_root, document["source"], published=False)
    receipt = {"schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
               "source_commit": document["source"]["commit"], "target": document["target"],
               "status": "running", "deleted_resources": [], "mutation_started": False,
               "flags": copy.deepcopy(document["deletion"]["flags"]),
               "project_numbers": list(document["target"]["project_ids"])}
    blob = "runs/" + document["run_id"] + ".worker.json"
    locks.request("PUT", blob, data=receipt,
                  headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))

    def persist():
        receipt["updated_at"] = fl.utc_now()
        locks.request("PUT", blob, data=receipt,
                      headers={"x-ms-blob-type": "BlockBlob", "If-Match": "*"}, allowed=(201,))

    try:
        receipt["observed_absent"] = observed_absent(cloud, document)
        fl.verify_project_inventory(cloud, document, receipt["observed_absent"])
        delete_rows(cloud, locks, document, receipt, persist, project_rows(document), sleep)
        fl.verify_project_inventory(cloud, document, receipt["deleted_resources"] + receipt["observed_absent"])
        receipt["projects"] = completed_projects(document)
        receipt["status"] = "succeeded"
        persist()
    except BaseException as error:
        receipt["status"] = "reconciliation-required"
        receipt.update(fl.failure_fields(error, "unexpected-factory-delete-worker-failure"))
        persist()
    finally:
        cloud.tokens.clear()
    return receipt


def resume_dispatch(cloud, locks, document, receipt, persist, sleep=time.sleep):
    remote = receipt.get("remote_run")
    if not remote:
        fl.require(not receipt.get("pending_dispatch") and not receipt.get("remote_artifacts"),
                   "factory-delete-dispatch-reconciliation-required")
        return False
    route = document["route"]
    fl.require(remote.get("kind") == route["kind"] and type(remote.get("run_id")) is int
               and remote["run_id"] > 0, "factory-delete-run-identity-unverified")
    for _ in range(1440):
        locks.assert_held()
        if route["kind"] == "gha":
            repo = urlsplit(route["repository"]).path.strip("/").removesuffix(".git")
            result = json.loads(cloud.command(["gh", "api", "--method", "GET",
                f"repos/{repo}/actions/runs/{remote['run_id']}", "--hostname", "github.com"]))
            fl.require(result.get("id") == remote["run_id"] and result.get("head_sha") == route["commit"]
                       and result.get("display_title") == "factory-lifecycle [" + document["run_id"] + "]",
                       "factory-delete-run-identity-unverified")
            terminal, successful = result.get("status") == "completed", result.get("conclusion") == "success"
            active = result.get("status") in ("queued", "in_progress", "waiting", "pending", "requested")
        else:
            organization, project, _, _ = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
            pipeline = remote.get("pipeline_id")
            fl.require(type(pipeline) is int and pipeline > 0, "factory-delete-run-identity-unverified")
            endpoint = ("https://dev.azure.com/" + quote(organization, safe="") + "/" + quote(project, safe="")
                        + f"/_apis/pipelines/{pipeline}/runs/{remote['run_id']}?api-version=7.1")
            result = cloud.request("GET", endpoint, "https://app.vssps.visualstudio.com/")[2]
            fl.require(result.get("id") == remote["run_id"] and result.get("pipeline", {}).get("id") == pipeline
                       and result.get("resources", {}).get("repositories", {}).get("self", {}).get("version") == route["commit"],
                       "factory-delete-run-identity-unverified")
            terminal, successful = result.get("state") == "completed", result.get("result") == "succeeded"
            active = result.get("state") in ("inProgress", "canceling")
        if terminal:
            receipt["remote_terminal"] = True
            persist()
            fl.require(successful, "factory-delete-provider-run-failed")
            return True
        fl.require(active, "factory-delete-provider-state-unverified")
        sleep(15)
    raise fl.Blocked("factory-delete-provider-completion-unverified")


def cleanup_resumed_artifacts(cloud, document, receipt, persist):
    if document["route"]["kind"] != "gha" or receipt.get("remote_artifacts_cleaned"):
        return
    artifacts = receipt.get("remote_artifacts")
    fl.require(isinstance(artifacts, dict) and receipt.get("remote_terminal") is True,
               "factory-delete-remote-artifacts-unverified")
    prefix = "AIF_LIFECYCLE_" + document["run_id"].replace("-", "").upper()
    ref = "refs/tags/aifactory-runs/" + document["run_id"]
    namespace = document["route"]["auth_namespace"]
    fl.require(artifacts.get("ref") == ref and artifacts.get("secret_prefix") == prefix
               and artifacts.get("auth_namespace") == namespace
               and type(artifacts.get("chunks")) is int and 1 <= artifacts["chunks"] <= 16,
               "factory-delete-remote-artifacts-unverified")
    repo = urlsplit(document["route"]["repository"]).path.strip("/").removesuffix(".git")
    existing = json.loads(cloud.command(["gh", "secret", "list", "--repo", "github.com/" + repo,
                                        "--env", namespace, "--json", "name"]))
    fl.require(isinstance(existing, list) and all(isinstance(row, dict) and isinstance(row.get("name"), str)
                                                for row in existing), "factory-delete-secret-inventory-unverified")
    names = {row["name"] for row in existing}
    for index in range(artifacts["chunks"]):
        name = prefix + "_" + str(index)
        if name in names:
            cloud.command(["gh", "secret", "delete", name, "--repo", "github.com/" + repo, "--env", namespace])
    refs = json.loads(cloud.command(["gh", "api", "--method", "GET", "repos/" + repo
        + "/git/matching-refs/" + ref.removeprefix("refs/"), "--hostname", "github.com"]))
    fl.require(isinstance(refs, list), "factory-delete-run-tag-unverified")
    matches = [row for row in refs if row.get("ref") == ref]
    fl.require(len(matches) <= 1 and all(row.get("object", {}).get("sha") == document["route"]["commit"]
                                       for row in matches), "factory-delete-run-tag-changed")
    if matches:
        cloud.command(["gh", "api", "--method", "DELETE", "repos/" + repo + "/git/" + ref,
                       "--hostname", "github.com"])
    receipt["remote_artifacts_cleaned"] = True
    persist()


def execute_cohort(documents, source_root, execution_root, receipt_path, cloud_factory, lock_factory=None):
    fl.require(isinstance(documents, list) and documents, "nonempty-delete-cohort-required")
    documents = json.loads(fl.canonical(documents))
    source_root, execution_root, receipt_path = map(fl.clean_path, (source_root, execution_root, receipt_path))
    fl.require(not execution_root.is_relative_to(source_root) and not source_root.is_relative_to(execution_root)
               and receipt_path.parent == execution_root, "execution-source-isolation-required")
    resume = receipt_path.exists()
    for document in documents:
        (fl._validate_manifest if resume else fl.validate_manifest)(document)
        fl.require(document["operation"] == "delete" and document["deletion"]["inventory_mode"] == CONTRACT,
                   "factory-delete-pipeline-cohort-required")
    first = documents[0]
    fl.require(all(document["target"]["factory_id"] == first["target"]["factory_id"]
                   and document["source"] == first["source"] for document in documents),
               "factory-delete-cohort-binding-mismatch")
    fl.require(len({document["run_id"] for document in documents}) == len(documents),
               "cohort-duplicate-child")
    scopes = [scope.lower() for document in documents for scope in document["locks"]["scopes"]]
    fl.require(len(set(scopes)) == len(scopes), "cohort-duplicate-writable-scope")
    # Overlapping readable closures would need independently bound prior-run evidence.
    # Do not silently accept a re-frozen inventory after another member changed it.
    deletes = {row["id"].lower() for document in documents
               for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"] if row["delete"]}
    for document in documents:
        own = {row["id"].lower() for row in document["deletion"]["resources"] +
               document["deletion"]["resource_groups"] if row["delete"]}
        fl.require(not (set(document["deletion"]["bodies"]) & (deletes - own)),
                   "factory-delete-overlapping-closure-requires-one-manifest")
    require_unique_hub_links(documents)
    clouds = [cloud_factory(document) for document in documents]
    members = [(lock_factory or fl.BlobLocks)(cloud, document) for cloud, document in zip(clouds, documents)]
    union = fl._CohortLeases(members)
    # Same aggregate identity as the generic cohort, so catalog verification is shared.
    cohort_hash = fl.digest(sorted(document["manifest_hash"] for document in documents))
    claimed, claim_attempted = set(), False
    if resume:
        aggregate = json.loads(receipt_path.read_text(encoding="utf-8"))
        fl.require(aggregate.get("cohort_hash") == cohort_hash
                   and aggregate.get("contract") == CONTRACT, "factory-delete-resume-binding-mismatch")
        fl.require(isinstance(aggregate.get("children"), list)
                   and len(aggregate["children"]) == len(documents), "factory-delete-resume-incomplete")
    else:
        fl.require(not execution_root.exists(), "new-isolated-execution-directory-required")
        aggregate = {"schema": 1, "contract": CONTRACT, "operation": "delete-factory",
                     "cohort_hash": cohort_hash, "factory_id": first["target"]["factory_id"],
                     "source_commit": first["source"]["commit"], "source_ref": first["source"]["ref"],
                     "status": "validating",
                     "children": [{"schema": 1, "run_id": document["run_id"],
                                   "manifest_hash": document["manifest_hash"],
                                   "manifest_revision": document["manifest_revision"], "operation": "delete",
                                   "source_commit": document["source"]["commit"],
                                   "source_ref": document["source"]["ref"], "target": document["target"],
                                   "cohort_hash": cohort_hash, "status": "validating", "mutation_started": False,
                                   "deleted_resources": []} for document in documents]}
        execution_root.mkdir(parents=True, mode=0o700)

    def persist():
        aggregate["updated_at"] = fl.utc_now()
        aggregate["mutation_started"] = any(row["mutation_started"] for row in aggregate["children"])
        aggregate["lease_context"] = dict(union.held)
        aggregate["locks_retained"] = sorted(union.held)
        aggregate["lock_retained"] = bool(union.held)
        for locks, receipt in zip(members, aggregate["children"]):
            receipt["locks_retained"] = sorted(locks.held)
            receipt["lock_retained"] = bool(locks.held)
            if receipt["run_id"] in claimed:
                locks.store_receipt(receipt)
            fl.write_receipt(execution_root / (receipt["run_id"] + ".receipt.json"), receipt)
        fl.write_receipt(receipt_path, aggregate)

    try:
        fl.verify_source(clouds[0], source_root, first["source"])
        for cloud in clouds:
            cloud.verify_identity()
        if resume:
            # Durable remote evidence, never a caller-edited local receipt, is the
            # authority for a resumed provider run or retained physical lease.
            for locks, document, receipt in zip(members, documents, aggregate["children"]):
                durable = locks.request("GET", "runs/" + document["run_id"] + ".json")[2]
                fl.require(durable == receipt and receipt.get("run_id") == document["run_id"]
                           and receipt.get("manifest_hash") == document["manifest_hash"],
                           "factory-delete-durable-receipt-mismatch")
            if aggregate["status"] == "succeeded":
                fl.require(not aggregate.get("lock_retained")
                           and all(row.get("status") == "succeeded" and not row.get("lock_retained")
                                   for row in aggregate["children"]), "factory-delete-success-receipt-incomplete")
                return aggregate
            context = aggregate.get("lease_context")
            fl.require(isinstance(context, dict) and set(context) == set(union.owners)
                       and all(fl.guid(value) for value in context.values()),
                       "factory-delete-retained-leases-required")
            union.held = dict(context)
            claim_attempted = True
            for locks, document, receipt in zip(members, documents, aggregate["children"]):
                locks.held = {scope.lower(): context[scope.lower()] for scope in
                              document["locks"]["scopes"] + document["locks"]["common_dependencies"]}
                locks.cohort_guard = union.assert_held
                proof = locks.read_claim()
                fl.require(proof == receipt.get("execution_claim")
                           and proof.get("manifest_hash") == document["manifest_hash"]
                           and proof.get("lease_context_hash") == fl.digest(locks.held),
                           "factory-delete-resume-claim-mismatch")
                locks.execution_claim = fl._ExecutionClaim(document, proof)
                claimed.add(document["run_id"])
                receipt["status"] = "running"
            union.assert_held()
            persist()
        else:
            persist()
            union.acquire()
            for cloud, locks, document, receipt in zip(clouds, members, documents, aggregate["children"]):
                cloud.assert_no_active_runs(locks.enrollment)
                receipt["observed_absent"] = observed_absent(cloud, document)
                fl.verify_project_inventory(cloud, document, receipt["observed_absent"])
                verify_permissions(cloud, document["deletion"], receipt["observed_absent"])
                verify_link_permissions(cloud, document["deletion"].get("hub_links", []))
            for locks, document, receipt in zip(members, documents, aggregate["children"]):
                claim_attempted = True
                locks.claim_run()
                claimed.add(document["run_id"])
                receipt["status"] = "running"
            persist()
        aggregate["status"] = "running"
        for cloud, locks, document, receipt in zip(clouds, members, documents, aggregate["children"]):
            locks.authorize(document)
            if not document["target"]["project_ids"]:
                receipt["projects_succeeded"] = True
                continue
            resumed = resume_dispatch(cloud, locks, document, receipt, persist)
            if not resumed:
                (fl.github_scoped if document["route"]["kind"] == "gha" else fl.ado_scoped)(
                    cloud, locks, document, source_root, receipt, persist)
            result = fl.verify_worker_receipt(locks, document)
            if resumed:
                cleanup_resumed_artifacts(cloud, document, receipt, persist)
            receipt["worker_receipt"] = result
            receipt["projects_succeeded"] = True
            receipt["deleted_resources"] = sorted(set(receipt["deleted_resources"]) | set(result["deleted_resources"]))
            persist()
        fl.require(all(row.get("projects_succeeded") is True for row in aggregate["children"]),
                   "factory-delete-project-pipeline-barrier-incomplete")
        for cloud, locks, document, receipt in zip(clouds, members, documents, aggregate["children"]):
            rows = [row for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]
                    if row["delete"] and row.get("project_number") is None]
            delete_rows(cloud, locks, document, receipt, persist, rows)
            fl.verify_project_inventory(cloud, document, receipt["deleted_resources"])
            receipt["deletion_complete"] = True
        # Last, once every spoke VNet of the cohort is gone: this factory's own links in a shared hub.
        for cloud, locks, document, receipt in zip(clouds, members, documents, aggregate["children"]):
            if document["deletion"].get("hub_links"):
                unlink_shared_hub(cloud, locks, document, receipt, persist)
        union.assert_held()
        # Store completion while leases still exist; the final receipt is only
        # successful after every lease is durably observed released.
        persist()
        union.release()
        for receipt in aggregate["children"]:
            receipt["status"] = "succeeded"
        aggregate["status"] = "succeeded"
        persist()
    except BaseException as error:
        aggregate["status"] = "reconciliation-required" if claim_attempted else "blocked"
        aggregate.update(fl.failure_fields(error, "unexpected-factory-delete-failure"))
        if not claim_attempted:
            try:
                union.release()
            except (fl.Blocked, OSError):
                aggregate["status"] = "reconciliation-required"
        # Keep active durable claims available to an already-running worker.
        for receipt in aggregate["children"]:
            if receipt["run_id"] not in claimed:
                receipt["status"] = aggregate["status"]
        persist()
    finally:
        for cloud in clouds:
            cloud.tokens.clear()
    return aggregate


# --- bootstrap-operator-teardown-v1 -------------------------------------------------------
# A factory whose Full bootstrap created its groups but that was never registered or enrolled
# has no lease store, route or pipeline. The operator tears it down from frozen, reviewed
# inventory: fresh identity, inventory and active-deployment checks stand in for leases.

TEARDOWN_CONTRACT = "bootstrap-operator-teardown-v1"
TEARDOWN_SOURCE = "bootstrap-record"
RECORD_CONTRACT = "consumed-bootstrap-stage-evidence-v1"
# Audited child collections that link a hub to a spoke network, with fixed API versions.
HUB_LINK_COLLECTIONS = {
    "microsoft.network/privatednszones": ("virtualNetworkLinks", "2024-06-01"),
    "microsoft.network/dnsforwardingrulesets": ("virtualNetworkLinks", "2022-07-01"),
    "microsoft.network/virtualnetworks": ("virtualNetworkPeerings", "2024-05-01"),
}
PEERING_TYPE = "microsoft.network/virtualnetworks/virtualnetworkpeerings"


class _OperatorTeardown:
    """Stands in for leases: there is no enrollment to lease, so callers re-verify fresh state."""

    held = {}

    def __init__(self, document):
        self.document = document

    def assert_held(self):
        return None

    def authorize(self, document):
        fl.require(document is self.document, "bootstrap-teardown-document-changed")


def teardown_digest(document):
    return fl.digest({key: value for key, value in document.items() if key != "manifest_hash"})


def _sorted_ids(values, pattern, allow_empty=False):
    return (isinstance(values, list) and (allow_empty or values) and values == sorted(set(values))
            and all(isinstance(value, str) and value == value.lower() and pattern.fullmatch(value)
                    for value in values))


def _overlaps(left, right):
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _remote(body):
    field = HUB_LINK_TARGETS.get(fl.resource_type_from_id(str(body.get("id", "")).lower()))
    value = ((body.get("properties") or {}).get(field) or {}).get("id") if field else None
    return value.lower() if isinstance(value, str) else ""


def _request(document):
    return {key: value for key, value in document.items() if key not in ("deletion", "manifest_hash")}


def validate_teardown_request(document):
    target = document.get("target") if isinstance(document, dict) else None
    record = document.get("bootstrap_record") if isinstance(document, dict) else None
    fl.require(isinstance(document, dict) and document.get("schema") == 1
               and document.get("contract") == TEARDOWN_CONTRACT and fl.guid(document.get("run_id"))
               and isinstance(target, dict) and all(isinstance(target.get(key), str) and target[key]
                                                    for key in ("factory_id", "scaleset_id"))
               and target.get("environment") in ("dev", "stage", "prod")
               and fl.guid(target.get("tenant_id")) and fl.guid(target.get("subscription_id"))
               and fl.guid((document.get("identity") or {}).get("object_id"))
               and isinstance((document.get("source") or {}).get("commit"), str)
               and re.fullmatch(r"[0-9a-f]{40}", document["source"]["commit"])
               and _sorted_ids(document.get("scopes"), fl.RG_ID)
               and all(scope.split("/")[2] == target["subscription_id"].lower() for scope in document["scopes"])
               and isinstance(record, dict) and record.get("contract") == RECORD_CONTRACT
               and fl.guid(record.get("workflow_id")) and fl.hash_value(record.get("record_hash"))
               and record.get("groups") == document["scopes"]
               and _sorted_ids(record.get("resources"), fl.NESTED_ID, allow_empty=True)
               and all(fl.arm_scope(value) in document["scopes"] for value in record["resources"])
               and isinstance(record.get("principal_ids", []), list)
               and record.get("principal_ids", []) == sorted(set(record.get("principal_ids", [])))
               and all(fl.guid(value) and value == value.lower() for value in record.get("principal_ids", []))
               and _sorted_ids(document.get("hub_scopes"), fl.RG_ID, allow_empty=True)
               and not set(document["hub_scopes"]) & set(document["scopes"])
               and isinstance(document.get("protected_resource_ids"), list)
               and all(isinstance(value, str) and value == value.lower()
                       and (fl.RG_ID.fullmatch(value) or fl.NESTED_ID.fullmatch(value))
                       for value in document["protected_resource_ids"])
               and not any(_overlaps(scope, value) for scope in document["scopes"]
                           for value in document["protected_resource_ids"]),
               "bootstrap-teardown-request-invalid")
    prepared, expires = fl.timestamp(document.get("prepared_at")), fl.timestamp(document.get("expires_at"))
    fl.require(0 < expires - prepared <= 3600, "bootstrap-teardown-request-invalid")


def _hub_inventory(cloud, hub_scopes, code):
    """Every DNS zone/ruleset link and VNet peering in the hub groups, plus the hub VNets."""
    links, hub_vnets = [], set()
    for scope in hub_scopes:
        for row in cloud.list_resources(scope):
            key = str(row.get("id", "")).lower()
            fl.require(fl.arm_scope(key) == scope, code)
            kind = fl.resource_type_from_id(key)
            if kind == VNET_TYPE:
                hub_vnets.add(key)
            if kind not in HUB_LINK_COLLECTIONS:
                continue
            child, api = HUB_LINK_COLLECTIONS[kind]
            items, unsupported = cloud.collection(row["id"] + "/" + child, api)
            fl.require(unsupported is None and isinstance(items, list), code)
            for item in items:
                identifier = str(item.get("id", "")).lower()
                fl.require(identifier.startswith(key + "/") and fl.NESTED_ID.fullmatch(identifier), code)
                links.append({"id": item["id"], "type": fl.resource_type_from_id(identifier), "api_version": api,
                              "remote_virtual_network_id": _remote(item), "side": "hub"})
    return links, hub_vnets


def _hub_links(cloud, document, factory_vnets):
    """Only links and peerings in the configured hub groups whose remote is one of this factory's VNets."""
    links, hub_vnets = _hub_inventory(cloud, document["hub_scopes"], "bootstrap-teardown-hub-inventory-incomplete")
    return [row for row in links if row["remote_virtual_network_id"] in factory_vnets], hub_vnets


def verify_link_permissions(cloud, links):
    verify_permissions(cloud, {"resource_groups": [], "resources": [
        {"id": row["id"], "type": row["type"], "delete": True, "depends_on": []} for row in links]})


def _parent_resource(key):
    """Nearest parent resource of a child or extension resource; never the resource group."""
    head, separator, tail = key.rpartition("/providers/")
    parts = tail.split("/")
    if separator and len(parts) == 3 and "/providers/" in head:
        return head  # Extension resource on a resource, e.g. a role assignment on a vault.
    parent = key.rsplit("/", 2)[0]
    return parent if separator and "/providers/" in parent and len(parent.rsplit("/providers/", 1)[1].split("/")) >= 3 else None


def _cascades(key, item, parent):
    """A true child (not an extension resource such as a role assignment, not a peering) goes with its parent."""
    return (key.startswith(parent + "/") and "/providers/" not in key[len(parent):]
            and str(item.get("type", "")).lower() != PEERING_TYPE and phase(item) not in (0, 1))


def teardown_owner(document, closure, bodies, key):
    """(owner, source) proving this resource belongs to exactly this factory and scale set."""
    record = document["bootstrap_record"]
    core = {field: document["target"][field] for field in ("factory_id", "scaleset_id")}
    body = bodies[key]
    tags = body.get("tags") or {}
    fl.require(isinstance(tags, dict), "malformed-project-ownership-tags")
    owner = {field: tags[tag] for field, tag in fl.TAG_KEYS.items() if tag in tags}
    fl.require(all(owner.get(field, value) == value for field, value in core.items()),
               "bootstrap-teardown-owner-conflict")
    if owner:
        return owner, "tags"
    if key in record["groups"] or hub_covers({"resource_ids": record["resources"]}, key):
        return dict(core), TEARDOWN_SOURCE
    if fl.resource_type_from_id(key).startswith("microsoft.authorization/"):
        # Role assignments carry no tags: only a principal the bootstrap recorded proves them.
        principal = str((body.get("properties") or {}).get("principalId", "")).lower()
        fl.require(principal in record.get("principal_ids", []), "bootstrap-teardown-unowned-resource")
        return dict(core), "bootstrap-principal"
    parent = _parent_resource(key)
    fl.require(parent in bodies, "bootstrap-teardown-unowned-resource")
    return teardown_owner(document, closure, bodies, parent)[0], "parent"


def freeze_teardown(cloud, document):
    validate_teardown_request(document)
    cloud.verify_identity()
    scopes = document["scopes"]
    closure, bodies = fl.collect_resource_closure(cloud, scopes)
    fl.verify_deletion_identity(document, bodies)
    record = document["bootstrap_record"]
    proof = {"resource_ids": record["resources"]}
    explicit = set(document["protected_resource_ids"])
    core = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    entries = {}
    for key, body in bodies.items():
        owner, source = teardown_owner(document, closure, bodies, key)
        group = key in closure["groups"]
        # Connectivity types pass only as bootstrap-recorded parts of the factory's own hub.
        fl.require(not protected(body, explicit, proof), "bootstrap-teardown-protected-resource")
        fl.require(group or not owner.get("project_id"), "bootstrap-teardown-project-resources-require-pipelines")
        fl.require(not fl.managed_group_cascades(body, document["target"]["subscription_id"]),
                   "bootstrap-teardown-managed-group-unsupported")
        metadata = closure["groups"].get(key, closure["resources"].get(key))
        fl.require(group or str(metadata["type"]).lower() not in (
            "microsoft.authorization/locks", "microsoft.authorization/denyassignments"),
                   "factory-delete-lock-or-deny-present")
        entries[key] = {"id": body["id"], **metadata, "delete": True, "project_number": None,
                        "ownership_source": source, "owner": owner,
                        "managed_group_ids": [], "depends_on": fl.project_resource_dependencies(body)}
    operations = {}
    for key, item in entries.items():
        if key in closure["groups"]:
            continue
        namespace = item["type"].split("/", 1)[0]
        if namespace not in operations:
            operations[namespace] = set(cloud.provider_operations(namespace))
        item["independent_delete"] = item["type"].lower() + "/delete" in operations[namespace]
    # Whole groups go, so a child resource (NSG rule, subnet, zone link, VM extension) leaves with
    # its nearest deleted parent instead of one checked delete each. Ancestors are decided first.
    for key in sorted(entries, key=len):
        item = entries[key]
        if key in closure["groups"]:
            continue
        parents = [parent for parent, candidate in entries.items() if key.startswith(parent + "/")
                   and candidate.get("independent_delete") is True and not candidate.get("delete_via_parent")]
        if item["independent_delete"] and not (parents and _cascades(key, item, max(parents, key=len))):
            continue
        fl.require(parents and phase(item) not in (0, 1), "factory-delete-service-lifecycle-unsupported")
        item["delete_via_parent"] = max(parents, key=len)
    factory_vnets ={key for key in bodies if not fl.RG_ID.fullmatch(key)
                     and fl.resource_type_from_id(key) == "microsoft.network/virtualnetworks"}
    links, hub_vnets = _hub_links(cloud, document, factory_vnets)
    # This factory's own side of each hub peering goes in the same unlink stage.
    links += [{"id": entries[key]["id"], "type": PEERING_TYPE, "api_version": entries[key]["api_version"],
               "remote_virtual_network_id": _remote(bodies[key]), "side": "factory"}
              for key in bodies if not fl.RG_ID.fullmatch(key)
              and fl.resource_type_from_id(key) == PEERING_TYPE and _remote(bodies[key]) in hub_vnets]
    resources = [entries[key] for key in sorted(closure["resources"])]
    data = {"inventory_mode": TEARDOWN_CONTRACT, "inventory_complete": True,
            "flags": dict.fromkeys(DELETE_FLAGS, True), "resource_groups": [entries[key] for key in sorted(closure["groups"])],
            "resources": resources, "inventory_hash": fl.digest(resources), "closure": closure,
            "closure_hash": fl.digest(closure), "bodies": bodies,
            "hub_links": sorted(links, key=lambda row: row["id"].lower()),
            "factory_virtual_networks": sorted(factory_vnets), "hub_virtual_networks": sorted(hub_vnets),
            "request_hash": fl.digest(_request(document))}
    validate_teardown({**document, "deletion": data}, check_hash=False)
    for scope in scopes:
        cloud.assert_no_active_deployments(scope)
    verify_permissions(cloud, data)
    verify_link_permissions(cloud, [row for row in data["hub_links"] if row["side"] == "hub"])
    return data


def validate_teardown(document, require_unexpired=False, check_hash=True):
    validate_teardown_request(document)
    fl.require(not check_hash or document.get("manifest_hash") == teardown_digest(document),
               "bootstrap-teardown-hash-mismatch")
    fl.require(not require_unexpired or time.time() < fl.timestamp(document["expires_at"]),
               "bootstrap-teardown-expired")
    data = document.get("deletion")
    fl.require(isinstance(data, dict) and data.get("inventory_mode") == TEARDOWN_CONTRACT
               and data.get("inventory_complete") is True and data.get("request_hash") == fl.digest(_request(document))
               and data.get("inventory_hash") == fl.digest(data.get("resources"))
               and data.get("closure_hash") == fl.digest(data.get("closure")) and isinstance(data.get("bodies"), dict),
               "bootstrap-teardown-inventory-unbound")
    validate_flags(data.get("flags"))
    groups, resources = data["resource_groups"], data["resources"]
    entries = {row["id"].lower(): row for row in groups + resources}
    fl.require({row["id"].lower() for row in groups} == set(document["scopes"])
               and len(entries) == len(groups + resources) and set(entries) == set(data["bodies"]),
               "bootstrap-teardown-inventory-unbound")
    record = document["bootstrap_record"]
    proof = {"resource_ids": record["resources"]}
    for key, row in entries.items():
        body = data["bodies"][key]
        fl.require(row.get("delete") is True and row.get("body_hash") == fl.digest(body)
                   and fl.arm_scope(key) in document["scopes"] and row.get("project_number") is None
                   and row.get("managed_group_ids") == [], "bootstrap-teardown-inventory-unbound")
        fl.require(not protected(body, document["protected_resource_ids"], proof),
                   "bootstrap-teardown-protected-resource")
        owner, source = teardown_owner(document, data["closure"], data["bodies"], key)
        fl.require(row.get("ownership_source") == source and row.get("owner") == owner
                   and (key in data["closure"]["groups"] or not owner.get("project_id")),
                   "bootstrap-teardown-unowned-resource")
        if not fl.RG_ID.fullmatch(key):
            fl.require(type(row.get("independent_delete")) is bool, "factory-delete-provider-delete-proof-required")
            if not row["independent_delete"] or "delete_via_parent" in row:
                parent = row.get("delete_via_parent", "")
                fl.require(parent in entries and key.startswith(parent + "/")
                           and entries[parent].get("independent_delete") is True
                           and "delete_via_parent" not in entries[parent] and phase(row) not in (0, 1)
                           and (not row["independent_delete"] or _cascades(key, row, parent)),
                           "factory-delete-service-cascade-unreviewed")
    vnets ={key for key in entries if not fl.RG_ID.fullmatch(key)
             and fl.resource_type_from_id(key) == "microsoft.network/virtualnetworks"}
    links = data.get("hub_links")
    fl.require(data.get("factory_virtual_networks") == sorted(vnets)
               and _sorted_ids(data.get("hub_virtual_networks"), fl.NESTED_ID, allow_empty=True)
               and all(fl.arm_scope(value) in document["hub_scopes"] for value in data["hub_virtual_networks"])
               and isinstance(links, list) and links == sorted(links, key=lambda row: row["id"].lower())
               and len({row["id"].lower() for row in links}) == len(links),
               "bootstrap-teardown-hub-links-invalid")
    for row in links:
        key = row["id"].lower()
        fl.require(row.get("type") in HUB_LINK_TARGETS and row["type"] == fl.resource_type_from_id(key)
                   and isinstance(row.get("api_version"), str)
                   and (row.get("side") == "hub" and fl.arm_scope(key) in document["hub_scopes"]
                        and row.get("remote_virtual_network_id") in vnets
                        or row.get("side") == "factory" and key in entries and row["type"] == PEERING_TYPE
                        and row.get("remote_virtual_network_id") in data["hub_virtual_networks"]
                        and _remote(data["bodies"][key]) == row["remote_virtual_network_id"]),
                   "bootstrap-teardown-hub-links-invalid")
    ordered_resources(groups + resources)


def _teardown_fresh(cloud, document):
    """Per-delete check: still the reviewed resource, same owner, no new dependency, no deployment running.

    Whole groups are deleted, so the complete inventory is verified only before the first change
    and after the last; an unreviewed new resource still blocks its group's empty-group check.
    """
    bodies, subscription = document["deletion"]["bodies"], document["target"]["subscription_id"]

    def check(row, body):
        key = row["id"].lower()
        before = bodies[key]
        cloud.assert_no_active_deployments(fl.arm_scope(key))
        fl.require(str(body.get("id", "")).lower() == key
                   and str(body.get("type", "")).lower() == str(before.get("type", "")).lower()
                   and body.get("location") == before.get("location")
                   and (body.get("tags") or {}) == (before.get("tags") or {})
                   and (body.get("properties") or {}).get("principalId")
                   == (before.get("properties") or {}).get("principalId")
                   and set(fl.project_resource_dependencies(body)) <= {value.lower() for value in row["depends_on"]}
                   and not fl.managed_group_cascades(body, subscription), "bootstrap-teardown-resource-changed")
    return check


def execute_teardown(document, receipt_path, cloud=None, sleep=time.sleep):
    document = json.loads(fl.canonical(document))
    validate_teardown(document, require_unexpired=True)
    receipt_path = fl.clean_path(receipt_path)
    cloud = cloud or fl.Cloud(document)
    data = document["deletion"]
    receipt = {"schema": 1, "contract": TEARDOWN_CONTRACT, "run_id": document["run_id"],
               "manifest_hash": document["manifest_hash"], "source_commit": document["source"]["commit"],
               "target": document["target"], "status": "running", "mutation_started": False,
               "deleted_hub_links": [], "deleted_resources": [], "observed_absent": []}

    def persist():
        receipt["updated_at"] = fl.utc_now()
        fl.write_receipt(receipt_path, receipt)

    lease = _OperatorTeardown(document)
    try:
        persist()
        cloud.verify_identity()
        for scope in document["scopes"]:
            cloud.assert_no_active_deployments(scope)
        receipt["observed_absent"] = observed_absent(cloud, document)
        fl.verify_project_inventory(cloud, document, receipt["observed_absent"])
        verify_permissions(cloud, data, receipt["observed_absent"])
        # Unlink first: this factory's own hub DNS links and both sides of its hub peerings.
        for link in data["hub_links"]:
            status, _, body = cloud.arm("GET", link["id"], link["api_version"], allowed=(200, 404))
            if status != 404:
                fl.require(_remote(body) == link["remote_virtual_network_id"], "bootstrap-teardown-hub-link-changed")
                receipt.update(mutation_started=True, pending_resource=link["id"])
                persist()
                cloud.arm("DELETE", link["id"], link["api_version"], allowed=(200, 202, 204, 404),
                          headers={"If-Match": body["etag"]} if body.get("etag") else None)
                fl.wait_absent(cloud, lease, link["id"], link["api_version"], sleep)
                receipt.pop("pending_resource", None)
            receipt["deleted_hub_links"].append(link["id"])
            if link["side"] == "factory":
                receipt["deleted_resources"].append(link["id"])
            persist()
        delete_rows(cloud, lease, document, receipt, persist,
                    [row for row in data["resources"] + data["resource_groups"] if row["delete"]], sleep,
                    fresh=_teardown_fresh(cloud, document))
        fl.verify_project_inventory(cloud, document, receipt["deleted_resources"] + receipt["observed_absent"])
        receipt["status"] = "succeeded"
    except BaseException as error:
        receipt["status"] = "reconciliation-required" if receipt["mutation_started"] else "blocked"
        receipt.update(fl.failure_fields(error, "unexpected-bootstrap-teardown-failure"))
    finally:
        getattr(cloud, "tokens", {}).clear()
    persist()
    return receipt
