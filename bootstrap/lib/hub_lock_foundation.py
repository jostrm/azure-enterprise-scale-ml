"""First-artifact, add-only connectivity-hub Blob coordination.

ARM PUT is NOT atomic create-only. Before a container and operator RBAC exist,
all initializers must be serialized by explicit external governance. Thereafter
physical hub-RG leases coordinate shared changes across factories and providers.
No consumer, common deployment, Git origin, shared key, SAS or public data is used.
Unknown write outcomes retain local evidence and any acquired infinite lease.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid4, uuid5

import factory_enrollment as enrollment


CONTRACT_VERSION = 1
SOURCE_FILES = ("bootstrap/lib/hub_lock_foundation.py", "bootstrap/lib/factory_enrollment.py")
CONTAINER = "hub-locks"
canonical = enrollment.canonical
digest = enrollment.digest


class FoundationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise FoundationError(code)


def ordinary(value):
    path = Path(os.path.abspath(value))
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                    for p in (path, *path.parents)), "linked-path-forbidden")
    require(not path.is_file() or path.stat().st_nlink == 1, "hardlinked-file-forbidden")
    return path


def source_fingerprint(source_root):
    root = ordinary(source_root)
    files = {}
    for relative in SOURCE_FILES:
        path = ordinary(root / relative)
        require(path.is_file(), "foundation-source-file-missing:" + relative)
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"kind": "reviewed-local-payload", "root": str(root),
            "published_ref_verified": False, "verification": "exact-local-file-bytes-only",
            "files": files, "payload_sha256": digest(files)}


def verify_source_snapshot(*, source_root, expected_payload_sha256):
    source = source_fingerprint(source_root)
    require(source["payload_sha256"] == expected_payload_sha256, "reviewed-source-payload-required")
    _verify_loaded_source(source)
    return source


def _verify_loaded_source(source):
    require(all(hashlib.sha256(ordinary(path).read_bytes()).hexdigest() == source["files"][relative]
                for relative, path in zip(SOURCE_FILES, (__file__, enrollment.__file__))),
            "loaded-foundation-code-differs-from-reviewed-source")


def coordination(hub_resource_group_id):
    """Stable across factories, repos, users, casing and tenant-local execution paths."""
    rg = enrollment.rg_id(hub_resource_group_id)
    name = "afhub" + hashlib.sha256(rg.encode("utf-8")).hexdigest()[:19]
    return {"account_id": rg + "/providers/microsoft.storage/storageaccounts/" + name,
            "account_url": "https://" + name + ".blob.core.windows.net", "container": CONTAINER}


def ownership_tags(hub_resource_group_id):
    return {"aifactory.coordination": "connectivity-hub-v1",
            "aifactory.hub_scope_sha256": hashlib.sha256(enrollment.rg_id(hub_resource_group_id).encode()).hexdigest()}


def lock_blob(scope):
    return "locks/" + hashlib.sha256(enrollment.rg_id(scope).encode()).hexdigest() + ".lock"


def _public_ipv4(value):
    require(isinstance(value, str), "approved-bootstrap-public-ipv4-required")
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise FoundationError("approved-bootstrap-public-ipv4-required") from None
    require(address.version == 4 and address.is_global and not address.is_multicast,
            "approved-bootstrap-public-ipv4-required")
    return str(address)


def account_body(hub_resource_group_id, location, bootstrap_public_ipv4):
    return {"location": location, "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
            "tags": ownership_tags(hub_resource_group_id), "properties": {
                "isHnsEnabled": False, "allowSharedKeyAccess": False, "allowBlobPublicAccess": False,
                "supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2",
                "defaultToOAuthAuthentication": True, "accessTier": "Hot",
                "publicNetworkAccess": "Enabled", "networkAcls": {
                    "defaultAction": "Deny", "bypass": "None",
                    "ipRules": [{"value": _public_ipv4(bootstrap_public_ipv4), "action": "Allow"}]}}}


def validate_shared_account(value, hub_resource_group_id, *, location=None, bootstrap_public_ipv4=None):
    """Validate an external retained account without changing its network policy.

    Consumers may use an already approved public rule, but cannot infer runner
    reachability from it. Foundation execution additionally pins its exact IPv4.
    """
    coords = coordination(hub_resource_group_id)
    require(isinstance(value, dict) and str(value.get("id", "")).lower() == coords["account_id"],
            "hub-coordination-account-identity-conflict")
    tags = value.get("tags") or {}
    require(all(tags.get(k) == v for k, v in ownership_tags(hub_resource_group_id).items())
            and not any(k.lower() in ("aifactory.factory_id", "aifactory.scaleset_id") for k in tags),
            "hub-coordination-account-ownership-conflict")
    props = value.get("properties", {})
    require(value.get("kind") == "StorageV2" and value.get("sku", {}).get("name") == "Standard_LRS"
            and props.get("isHnsEnabled") is False and props.get("allowSharedKeyAccess") is False
            and props.get("allowBlobPublicAccess") is False and props.get("supportsHttpsTrafficOnly") is True
            and props.get("minimumTlsVersion") in ("TLS1_2", "TLS1_3")
            and props.get("defaultToOAuthAuthentication") is True,
            "hub-coordination-account-security-conflict")
    require(location is None or value.get("location", "").lower() == location, "hub-account-location-conflict")
    require(props.get("provisioningState") == "Succeeded", "hub-account-not-ready")
    network = props.get("networkAcls", {})
    require(network.get("defaultAction") == "Deny" and network.get("bypass") == "None"
            and not network.get("virtualNetworkRules") and not network.get("resourceAccessRules"),
            "hub-coordination-network-conflict")
    public = props.get("publicNetworkAccess")
    rules = network.get("ipRules", [])
    require(public in ("Enabled", "Disabled") and isinstance(rules, list), "hub-coordination-network-conflict")
    if public == "Enabled":
        require(len(rules) == 1 and rules[0].get("action") == "Allow", "hub-coordination-network-conflict")
        address = _public_ipv4(rules[0].get("value"))
        require(bootstrap_public_ipv4 is None or address == bootstrap_public_ipv4,
                "hub-approved-bootstrap-ipv4-conflict")
    else:
        require(not rules, "hub-private-account-has-public-rules")
    return public == "Enabled"


class Cloud(enrollment.Cloud):
    def __init__(self, target, coordinates, command_runner=None, opener=None):
        super().__init__({"target": target, "coordinates": coordinates}, command_runner, opener)

    def principal(self):
        self.token(enrollment.ARM + "/")
        token = self.token(enrollment.STORAGE)
        try:
            encoded = token.split(".")[1]
            claims = enrollment.parse_json(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            require(enrollment.guid(claims["oid"]) == self.operator_id,
                    "arm-and-storage-principal-mismatch")
        except (KeyError, IndexError, ValueError, TypeError):
            raise FoundationError("invalid-authenticated-storage-principal") from None
        return enrollment.guid(self.operator_id)

    def blob(self, method, blob=None, *, data=None, headers=None, allowed=(200,), query=""):
        coords = self.request_config["coordinates"]
        url = coords["account_url"] + "/" + coords["container"]
        url += "?restype=container" if blob is None else "/" + quote(blob, safe="/") + query
        return self.http(method, url, enrollment.STORAGE, data, headers, allowed=allowed)


def _contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return actual == expected
    if isinstance(expected, str) and expected.startswith("/subscriptions/"):
        return isinstance(actual, str) and actual.lower() == expected.lower()
    return actual == expected


def _matching_container_role(value, body, scope):
    props = value.get("properties", {})
    expected = body["properties"]
    return (str(props.get("principalId", "")).lower() == expected["principalId"]
            and str(props.get("roleDefinitionId", "")).lower() == expected["roleDefinitionId"]
            and str(props.get("scope", "")).lower() == scope)


def capabilities():
    return {"contract_version": CONTRACT_VERSION, "implemented_stages": ["hub-lock-foundation"],
            "cold_start_supported": True, "requires_common_deployment": False,
            "private_transition_implemented": False, "runner_reachability_verified": False,
            "distributed_lock_before_initialization": False, "initialization_governance_required": True}


def prepare(*, source_root, tenant_id, hub_resource_group_id, location, bootstrap_public_ipv4=None,
            expected_source_hash=None, runtime=None):
    """Read-only frozen native plan; no hub is a separate provider-serialization path."""
    source = source_fingerprint(source_root)
    require(expected_source_hash is None or source["payload_sha256"] == expected_source_hash,
            "reviewed-source-payload-required")
    _verify_loaded_source(source)
    tenant = enrollment.guid(tenant_id)
    rg = enrollment.rg_id(hub_resource_group_id)
    require(isinstance(location, str) and re.fullmatch(r"[a-z0-9]{2,40}", location),
            "canonical-azure-location-required")
    blank_ip = bootstrap_public_ipv4 is None or (
        isinstance(bootstrap_public_ipv4, str) and not bootstrap_public_ipv4.strip())
    ip = None if blank_ip else _public_ipv4(bootstrap_public_ipv4)
    coords = coordination(rg)
    target = {"tenant_id": tenant, "subscription_id": rg.split("/")[2]}
    runtime = runtime or Cloud(target, coords)
    runtime.read_only = True
    principal = enrollment.guid(runtime.principal())
    observations, effects, blockers = [], [], []

    def read(identifier, api, *, absent_parent=None):
        if absent_parent is not None:
            observations.append({"id": identifier, "api": api, "value": None,
                                 "absence_derived_from_parent": absent_parent})
            return None
        status, _, value = runtime.arm("GET", identifier, api, allowed=(200, 404))
        require(status in (200, 404), "unexpected-foundation-read-status")
        value = value if status == 200 else None
        observations.append({"id": identifier, "api": api, "value": copy.deepcopy(value)})
        return value

    def ensure(identifier, api, body, value):
        if value is None:
            effects.append({"kind": "arm-create", "id": identifier, "api": api, "body": body,
                            "ownership": "external-retain-never-enroll-or-delete"})
        elif not _contains(value, body) or value.get("properties", {}).get("provisioningState", "Succeeded") != "Succeeded":
            blockers.append("existing-foundation-resource-conflict:" + identifier)

    provider = f"/subscriptions/{target['subscription_id']}/providers/Microsoft.Storage"
    if (read(provider, "2021-04-01") or {}).get("registrationState") != "Registered":
        blockers.append("storage-provider-registration-required:" + provider)
    group = read(rg, enrollment.RG_API)
    if group is None:
        ensure(rg, enrollment.RG_API, {"location": location, "tags": ownership_tags(rg)}, None)
    elif any(k.lower() in ("aifactory.factory_id", "aifactory.scaleset_id") for k in (group.get("tags") or {})):
        blockers.append("connectivity-resource-group-must-not-be-factory-owned:" + rg)
    elif any(k in (group.get("tags") or {}) and group["tags"][k] != v for k, v in ownership_tags(rg).items()):
        blockers.append("connectivity-resource-group-ownership-conflict:" + rg)
    account = read(coords["account_id"], enrollment.STORAGE_API, absent_parent=rg if group is None else None)
    private_required = True
    if account is None:
        require(ip is not None, "approved-bootstrap-public-ipv4-required")
        available = runtime.az("storage", "account", "check-name", "--name", coords["account_id"].rsplit("/", 1)[1],
                               "--subscription", target["subscription_id"])
        observations.append({"kind": "name-availability", "value": copy.deepcopy(available)})
        if available.get("nameAvailable") is not True:
            blockers.append("deterministic-hub-account-name-unavailable:" + coords["account_id"])
        ensure(coords["account_id"], enrollment.STORAGE_API, account_body(rg, location, ip), None)
    else:
        try:
            private_required = validate_shared_account(account, rg, bootstrap_public_ipv4=ip)
        except FoundationError as exc:
            blockers.append(exc.code + ":" + coords["account_id"])
        if blank_ip:
            require(not private_required and not blockers, "approved-bootstrap-public-ipv4-required")
    container_id = coords["account_id"] + "/blobservices/default/containers/" + CONTAINER
    container = read(container_id, enrollment.STORAGE_API,
                     absent_parent=coords["account_id"] if account is None else None)
    ensure(container_id, enrollment.STORAGE_API, {"properties": {"publicAccess": "None"}}, container)
    role = f"/subscriptions/{target['subscription_id']}/providers/Microsoft.Authorization/roleDefinitions/{enrollment.DATA_ROLE}".lower()
    role_id = container_id + "/providers/microsoft.authorization/roleassignments/" + str(
        uuid5(NAMESPACE_URL, container_id + ":" + principal + ":" + role))
    role_body = {"properties": {"principalId": principal, "roleDefinitionId": role}}
    existing_role = read(role_id, enrollment.ROLE_API, absent_parent=container_id if container is None else None)
    roles = runtime.collection(container_id + "/providers/Microsoft.Authorization/roleAssignments", enrollment.ROLE_API) if container else []
    roles = sorted(roles, key=lambda r: r["id"].lower())
    observations.append({"kind": "container-role-assignments", "value": copy.deepcopy(roles)})
    matches = [r for r in roles if _matching_container_role(r, role_body, container_id)]
    if existing_role and (not _matching_container_role(existing_role, role_body, container_id)
                          or existing_role.get("properties", {}).get("condition")):
        blockers.append("hub-container-role-assignment-conflict:" + role_id)
    elif not existing_role and not any(not r.get("properties", {}).get("condition") for r in matches):
        if matches:
            blockers.extend("hub-container-conditioned-role-requires-explicit-review:" + r["id"] for r in matches)
        else:
            ensure(role_id, enrollment.ROLE_API, role_body, None)
    private_data_plane_verified = False
    if account and container and not blockers:
        try:
            status, _, _ = runtime.blob("HEAD", allowed=(200,))
            require(status == 200, "authenticated-container-head-required")
            private_data_plane_verified = not private_required
        except (enrollment.EnrollmentError, FoundationError) as exc:
            if blank_ip or exc.code != "remote-request-failed-403" or not any(e["id"] == role_id for e in effects):
                blockers.append("bootstrap-entra-data-plane-unreachable:" + container_id + ":" + exc.code)
    if blank_ip and not private_data_plane_verified:
        blockers.append("existing-private-hub-authenticated-execution-path-required:" + container_id)
    private_reuse_access = None if private_required else {
        "verified": private_data_plane_verified, "account_id": coords["account_id"], "container": CONTAINER,
        "tenant_id": tenant, "principal_id": principal, "authentication": "Entra-OAuth-only",
        "proof": "native-container-head-with-public-network-disabled",
        "execution_path": "current-authenticated-private-execution-host",
        "provider_runner_attested": False}
    warnings = [
        "Initial RG/account/container/RBAC writes have NO distributed lease: externally serialize ALL initializers for " + rg,
        "ARM create-or-update has no atomic create-only guarantee; immediate rechecks do not replace first-initialization governance.",
        "No common network, provider runner, VPN, repository or factory deployment is performed by this stage.",
        "Control-plane create/grant permissions are required at the listed scopes; discovery reads do not prove write authorization.",
        "Account/key administrators remain trusted; leases are not a security boundary.",
        "Storage IPv4 firewall rules have NO automatic expiry; a blocked or interrupted workflow does not close the public path.",
    ]
    if account and account.get("location", "").lower() != location:
        warnings.append("Existing shared account location is retained unchanged: " + str(account.get("location"))
                        + "; requested location applies only to new resources.")
    bootstrap_network_access = {
        "account_id": coords["account_id"],
        "rule": {"value": ip, "action": "Allow"} if private_required else None,
        "rule_origin": "planned-with-new-account" if account is None else "existing-rule-retained" if private_required else "existing-private-account",
        "automatic_expiration": False, "expires_at": None,
        "removal_authorized": False, "existing_rules_must_be_retained": True,
    }
    cleanup_instructions = [
        "The recorded Storage IPv4 rule does not expire. Keep the approved public path while any private execution path is unverified.",
        "Separately approve a private endpoint whose privateLinkServiceId targets exactly " + coords["account_id"]
        + " and whose groupIds select blob; verify its connection is Approved and read its assigned private IP.",
        "From each execution path, resolve " + coords["account_url"].removeprefix("https://")
        + " to that approved endpoint's actual private IP, then verify an Entra-authenticated data-plane request to " + container_id + ".",
        "Enumerate and probe every known bootstrap/provider-runner writer; unknown or unverified writers block closing the public path.",
        "Only a separately reviewed transition may remove the exact rule proven added by this execution; never remove a pre-existing rule on reuse.",
        "If an account PUT outcome is uncertain, reconcile the exact account and receipt before attributing or removing any firewall rule.",
    ]
    transition = {"status": "pending" if private_required else "existing-private-path-bootstrap-only",
                  "account_id": coords["account_id"], "container_scope": container_id,
                  "execution_path": "current-bootstrap-host", "runner_reachability_verified": False,
                  "writer_inventory_complete": False, "private_endpoint_verified": False,
                  "private_dns_verified": False, "authenticated_private_path_verified": private_data_plane_verified,
                  "cleanup_instructions": cleanup_instructions,
                  "blockers": ["approved-private-endpoint-and-dns-evidence-required:" + coords["account_id"],
                               "authenticated-private-bootstrap-path-verification-required:" + container_id,
                               "provider-runner-access-unverified-public-path-must-not-be-disabled:" + coords["account_id"]]
                  if private_required else ["provider-runner-access-unverified:" + container_id],
                  "automatic_network_changes": False}
    plan = {"contract_version": CONTRACT_VERSION, "stage": "hub-lock-foundation", "plan_id": str(uuid4()),
            "prepared_at": time.time(), "expires_at": time.time() + 900, "source": source,
            "inputs": {"tenant_id": tenant, "hub_resource_group_id": rg, "location": location, "bootstrap_public_ipv4": ip},
            "target": target, "principal_id": principal, "coordination": coords, "coordination_mode": "connectivity-hub",
            "hub_resource_group_id": rg, "observations": observations, "effects": effects,
            "blockers": blockers, "warnings": warnings, "can_execute": not blockers,
            "lock_scopes": [rg], "initialization_governance_required": True,
            "private_transition_required": private_required, "private_transition": transition,
            "private_reuse_access": private_reuse_access,
            "bootstrap_network_access": bootstrap_network_access,
            "capabilities": capabilities(), "runtime_ready": False,
            "commands": [{"transport": "arm", "method": "PUT", "resource_id": e["id"],
                          "api_version": e["api"], "body": copy.deepcopy(e["body"]),
                          "precondition": "externally-serialized-initialization-and-resource-still-absent"}
                         for e in effects] + [
                {"transport": "storage", "method": "PUT", "blob": lock_blob(rg), "container": CONTAINER,
                 "precondition": "If-None-Match:*", "purpose": "retain-existing-lock-blob"},
                {"transport": "storage", "method": "PUT", "blob": lock_blob(rg), "query": "comp=lease",
                 "purpose": "acquire-infinite-hub-lease-then-verify-and-release-own-lease"}],
            "auth_scopes": [{"service": "arm", "scope": rg,
                             "permissions": ["Microsoft.Resources/subscriptions/resourceGroups/read",
                                             "Microsoft.Storage/storageAccounts/read",
                                             "Microsoft.Storage/storageAccounts/write",
                                             "Microsoft.Storage/storageAccounts/blobServices/containers/read",
                                             "Microsoft.Storage/storageAccounts/blobServices/containers/write"]},
                            {"service": "arm", "scope": container_id,
                             "permissions": ["Microsoft.Authorization/roleAssignments/read",
                                             "Microsoft.Authorization/roleAssignments/write"]},
                            {"service": "storage", "scope": container_id, "principal_id": principal,
                             "role_definition_id": enrollment.DATA_ROLE, "authentication": "Entra-OAuth-only"}]}
    if group is None:
        plan["auth_scopes"].append({"service": "arm", "scope": "/subscriptions/" + target["subscription_id"],
                                    "permissions": ["Microsoft.Resources/subscriptions/resourceGroups/write"]})
    plan["plan_hash"] = digest(plan)
    return plan


def _persist(path, value, retry_sleep=time.sleep):
    path = ordinary(path)
    sibling = ordinary(path.with_suffix("." + str(uuid4()) + ".writing"))
    with sibling.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    # Retry only the atomic local rename while Windows releases a sharing lock.
    for attempt in range(20):
        try:
            os.replace(sibling, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            retry_sleep(0.05)


def _wait(runtime, identifier, api, sleep):
    for _ in range(120):
        status, _, value = runtime.arm("GET", identifier, api, allowed=(200, 404))
        state = value.get("properties", {}).get("provisioningState", "Succeeded") if status == 200 else "Creating"
        require(state not in ("Failed", "Canceled"), "foundation-provisioning-failed:" + identifier)
        if state == "Succeeded":
            return value
        sleep(5)
    raise FoundationError("foundation-provisioning-uncertain:" + identifier)


def execute(plan, *, state_dir, expected_plan_hash, acknowledge_initialization_governance=False,
            runtime=None, sleep=time.sleep):
    """One use only. Failed writes are uncertain, never retried, rolled back or deleted."""
    require(acknowledge_initialization_governance is True, "initialization-governance-required")
    require(isinstance(plan, dict) and plan.get("contract_version") == CONTRACT_VERSION
            and plan.get("stage") == "hub-lock-foundation" and plan.get("plan_hash") == expected_plan_hash
            and digest({k: v for k, v in plan.items() if k != "plan_hash"}) == expected_plan_hash,
            "foundation-plan-hash-mismatch")
    require(plan.get("can_execute") is True and not plan.get("blockers"), "foundation-plan-blocked")
    require(plan["prepared_at"] <= time.time() < plan["expires_at"], "foundation-review-expired")
    require(source_fingerprint(plan["source"]["root"]) == plan["source"], "foundation-source-changed")
    _verify_loaded_source(plan["source"])
    enrollment.guid(plan["plan_id"])
    runtime = runtime or Cloud(plan["target"], plan["coordination"])
    fresh = prepare(source_root=plan["source"]["root"], expected_source_hash=plan["source"]["payload_sha256"],
                    **plan["inputs"], runtime=runtime)
    for key in ("inputs", "target", "principal_id", "coordination", "hub_resource_group_id", "effects",
                "observations", "blockers", "commands", "auth_scopes", "lock_scopes", "private_transition",
                "bootstrap_network_access", "private_transition_required", "coordination_mode",
                "private_reuse_access",
                "capabilities", "initialization_governance_required", "runtime_ready", "warnings"):
        require(fresh[key] == plan[key], "foundation-live-state-or-plan-changed:" + key)
    folder = ordinary(state_dir)
    require(folder.is_dir(), "durable-existing-state-directory-required")
    receipt_path = ordinary(folder / (plan["plan_id"] + ".json"))
    guard_path = ordinary(folder / ("hub-initialization-" + digest(plan["hub_resource_group_id"]) + ".claim"))
    receipt = {"contract_version": CONTRACT_VERSION, "stage": "hub-lock-foundation",
               "plan_id": plan["plan_id"], "plan_hash": expected_plan_hash, "status": "uncertain",
               "source": copy.deepcopy(plan["source"]), "principal_id": plan["principal_id"],
               "coordination": copy.deepcopy(plan["coordination"]), "coordination_mode": "connectivity-hub",
               "hub_resource_group_id": plan["hub_resource_group_id"],
               "receipt_path": str(receipt_path), "initialization_guard_path": str(guard_path),
               "effects_completed": [], "leases": {}, "changed": False,
               "reconciliation_required": True, "runtime_ready": False,
               "private_transition_required": plan["private_transition_required"],
               "private_transition": copy.deepcopy(plan["private_transition"]),
               "private_reuse_access": copy.deepcopy(plan["private_reuse_access"]),
               "bootstrap_network_access": {
                   **copy.deepcopy(plan["bootstrap_network_access"]),
                   "added_by_this_execution": False,
                   "rule_write_state": "not-attempted" if plan["bootstrap_network_access"]["rule_origin"] == "planned-with-new-account"
                   else "reused-unchanged"}}
    with receipt_path.open("xb") as stream:
        stream.write(canonical(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    # A retained guard blocks new plans on this execution path after uncertainty.
    # It is NOT distributed protection of the pre-lease account/container writes.
    with guard_path.open("xb") as stream:
        stream.write(canonical({"plan_id": plan["plan_id"], "receipt_path": str(receipt_path)}))
        stream.flush()
        os.fsync(stream.fileno())
    runtime.read_only = False
    runtime.serialized_provisioning = True
    remote = "bootstrap/foundation/" + plan["plan_id"] + ".json"
    remote_etag = None
    blob = lock_blob(plan["hub_resource_group_id"])

    def persist():
        nonlocal remote_etag
        _persist(receipt_path, receipt)
        if remote_etag is not None:
            _, headers, _ = runtime.blob("PUT", remote, data=receipt,
                                        headers={"x-ms-blob-type": "BlockBlob", "If-Match": remote_etag}, allowed=(201,))
            require(headers.get("etag"), "foundation-proof-etag-required")
            remote_etag = headers["etag"]

    try:
        for index, effect in enumerate(plan["effects"]):
            require(source_fingerprint(plan["source"]["root"]) == plan["source"], "foundation-source-changed")
            status, _, _ = runtime.arm("GET", effect["id"], effect["api"], allowed=(200, 404))
            require(status == 404, "foundation-resource-appeared-after-review:" + effect["id"])
            receipt.update(pending_effect=index, changed=True)
            if effect["id"] == plan["coordination"]["account_id"]:
                receipt["bootstrap_network_access"].update(
                    added_by_this_execution=None, rule_write_state="submitted-outcome-unknown")
            persist()
            runtime.arm("PUT", effect["id"], effect["api"], data=effect["body"], allowed=(200, 201, 202))
            value = _wait(runtime, effect["id"], effect["api"], sleep)
            require(_contains(value, effect["body"]), "foundation-created-resource-verification-failed:" + effect["id"])
            if effect["id"] == plan["coordination"]["account_id"]:
                validate_shared_account(value, plan["hub_resource_group_id"], location=plan["inputs"]["location"],
                                        bootstrap_public_ipv4=plan["inputs"]["bootstrap_public_ipv4"])
                receipt["bootstrap_network_access"].update(
                    added_by_this_execution=True, rule_write_state="verified-created")
            receipt["effects_completed"].append(index)
            receipt.pop("pending_effect", None)
            persist()
        # Only retry authenticated READs for RBAC propagation, never uncertain writes.
        for attempt in range(25):
            try:
                runtime.blob("HEAD", allowed=(200,))
                break
            except enrollment.EnrollmentError as exc:
                if exc.code != "remote-request-failed-403" or attempt == 24:
                    raise
                sleep(5)
        _, headers, _ = runtime.blob("PUT", remote, data=receipt,
                                    headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))
        require(headers.get("etag"), "foundation-proof-etag-required")
        remote_etag = headers["etag"]
        runtime.blob("PUT", blob, data=b"", headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"},
                     allowed=(201, 412))
        lease = str(uuid4())
        receipt["leases"][plan["hub_resource_group_id"]] = lease
        receipt["lease_state"] = "proposed-acquisition-not-yet-confirmed"
        persist()
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                     "x-ms-proposed-lease-id": lease}, query="?comp=lease", allowed=(201,))
        receipt["lease_state"] = "acquired"
        persist()
        verified = prepare(source_root=plan["source"]["root"], expected_source_hash=plan["source"]["payload_sha256"],
                           **plan["inputs"], runtime=runtime)
        require(verified["can_execute"] and not verified["effects"]
                and verified["principal_id"] == plan["principal_id"], "foundation-post-state-not-verified")
        runtime.read_only = False
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease},
                     query="?comp=lease", allowed=(200,))
        receipt["bootstrap_data_plane_verified"] = True
        receipt["verified_observations_hash"] = digest(verified["observations"])
        persist()
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "release", "x-ms-lease-id": lease},
                     query="?comp=lease", allowed=(200,))
        receipt["leases"] = {}
        receipt["lease_state"] = "released"
        receipt.update(status="succeeded", reconciliation_required=False,
                       completed_stage="hub-lock-foundation", runtime_ready=False)
        persist()
        guard_path.unlink()  # Only our completed local claim; never an Azure object or lease break.
        return receipt
    except BaseException as exc:
        receipt.update(status="uncertain", reconciliation_required=True,
                       error=getattr(exc, "code", "foundation-execution-interrupted"))
        _persist(receipt_path, receipt)
        if remote_etag:
            try:
                runtime.read_only = False
                persist()
            except Exception:
                pass
        if not isinstance(exc, Exception):
            raise
        return receipt
    finally:
        runtime.read_only = True
        runtime.serialized_provisioning = False
