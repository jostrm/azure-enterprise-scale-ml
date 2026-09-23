"""Retained hub Blob private transition, approved ARM plan and runner attestation.

Public entry points: prepare, execute, recover, source_fingerprint, prepare_probe,
execute_probe. The probe stage provisions/verifies private access but retains the
public bootstrap path; final transition separately freezes all writers and closes.
``context`` contains private_endpoint_subnet_id, dns_zone_id, dns_vnet_ids,
closure_writer_id and foundation_receipt (a plan_id reference, NOT trusted proof).
Optional writer_targets, derived from reviewed enrollment/runner stage outputs,
can add missing registry targets; existing targets are never silently replaced.
Workflow adapters require a verified hub_private_endpoint_subnet_id in the
retained connectivity-hub VNet; a factory runner subnet is never a PE fallback.
The account's hub-locks/coordination.json is authoritative for all factory writers.
hub-locks/private-transition/writers.json supplies independently verified runner
targets: schema=1, hub_resource_group_id, inventory_complete=true, writers={id:
{provider, repository, repository_id, runner_id, runner_name, vm_id,
runner_config_path, principal_id, tenant_id, source_commit, probe_path,
client_id?, pool_id?}}. De-enrollment requires removal from coordination scopes
and an explicit inactive entry with de_enrollment_revision and reason. Unknown
or unrepresented writers fail closed. Registry publication is separately governed.

Native transport uses reviewed VM RunCommand (not local DNS or caller JSON), with
provider registration and pinned repository probe bytes independently checked.
GHA Linux self-hosted and existing ADO Windows/Linux VMs are supported; Python 3
and the registered writer's managed identity must already be present on the VM.
Infinite physical hub leases survive interrupted/uncertain operations.
Storage-account updates use the physical lease and frozen resource snapshots,
not unsupported ARM Storage account ETags. Expired recovery only records
observations; it never extends consent or starts another runner operation.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import os
from pathlib import Path
import re
from threading import Event
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4
from xml.etree import ElementTree

import factory_enrollment as enrollment
import hub_lock_foundation as foundation


CONTRACT_VERSION = 1
NETWORK_API = "2024-05-01"
DNS_API = "2024-06-01"
COMPUTE_API = "2024-03-01"
PROBE = "bootstrap/templates/hub_private_probe.py"
SOURCE_FILES = ("bootstrap/lib/hub_private_transition.py", "bootstrap/lib/hub_lock_foundation.py",
                "bootstrap/lib/factory_enrollment.py", PROBE)
REGISTRY = "private-transition/writers.json"
COORDINATION = "coordination.json"
canonical = enrollment.canonical
digest = enrollment.digest


class TransitionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise TransitionError(code)


def source_fingerprint(source_root):
    root = foundation.ordinary(source_root)
    files = {}
    for relative in SOURCE_FILES:
        path = foundation.ordinary(root / relative)
        require(path.is_file(), "transition-source-missing:" + relative)
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"kind": "reviewed-local-payload", "root": str(root), "published_ref_verified": False,
            "verification": "exact-local-file-bytes-only", "files": files, "payload_sha256": digest(files),
            "probe_normalization": "CRLF-to-LF-only", "probe_sha256": hashlib.sha256(_probe_bytes(root)).hexdigest()}


def _probe_bytes(source_root):
    return foundation.ordinary(Path(source_root) / PROBE).read_bytes().replace(b"\r\n", b"\n")


def verify_source_snapshot(*, source_root, expected_payload_sha256):
    source = source_fingerprint(source_root)
    require(source["payload_sha256"] == expected_payload_sha256, "reviewed-source-payload-required")
    for relative, loaded in zip(SOURCE_FILES, (__file__, foundation.__file__, enrollment.__file__)):
        require(hashlib.sha256(foundation.ordinary(loaded).read_bytes()).hexdigest() == source["files"][relative],
                "loaded-transition-code-differs-from-reviewed-source")
    return source


def _id(value, resource_type):
    types = resource_type.split("/")
    pattern = r"(.+)/providers/" + re.escape(types[0])
    for segment in types[1:]:
        pattern += "/" + re.escape(segment) + r"/[A-Za-z0-9_.-]{1,128}"
    match = re.fullmatch(pattern, str(value), re.I)
    require(match, "invalid-transition-resource-id")
    enrollment.rg_id(match[1])
    return value.lower()


def _contains(actual, expected):
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _contains(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(actual[k], v) for k, v in expected.items())
    return foundation._contains(actual, expected)


def _etag(headers, value):
    result = headers.get("etag") or (value or {}).get("etag")
    require(isinstance(result, str) and result, "resource-etag-required")
    return result


def _persist(path, value):
    path = foundation.ordinary(path)
    sibling = foundation.ordinary(path.with_suffix("." + str(uuid4()) + ".writing"))
    with sibling.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    # Windows indexers can briefly open the previous receipt without delete
    # sharing. Retry only this local atomic rename, never a remote mutation.
    for attempt in range(10):
        try:
            os.replace(sibling, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            Event().wait(0.025 * (attempt + 1))


def _read(runtime, identifier, api):
    status, headers, value = runtime.arm("GET", identifier, api, allowed=(200, 404))
    require(status in (200, 404), "invalid-arm-read-status")
    storage_account = bool(re.fullmatch(
        r"/subscriptions/[^/]+/resourcegroups/[^/]+/providers/microsoft\.storage/storageaccounts/[^/]+",
        identifier, re.I))
    compute_vm = bool(re.fullmatch(
        r"/subscriptions/[^/]+/resourcegroups/[^/]+/providers/microsoft\.compute/virtualmachines/[^/]+(?:/runcommands/[^/]+)?",
        identifier, re.I))
    if status == 200 and (storage_account or compute_vm):
        value = _account_snapshot(value)
    return {"id": identifier, "api": api, "value": value if status == 200 else None,
            "etag": _etag(headers, value) if status == 200 and not (storage_account or compute_vm) else None}


def _account_snapshot(value):
    result = copy.deepcopy(value)
    result.pop("etag", None)
    return result


def _vm_snapshot(value):
    result = _account_snapshot(value)
    result.pop("resources", None)
    for field in ("instanceView", "provisioningState"):
        result.get("properties", {}).pop(field, None)
    return result


def _authorized(plan):
    require(plan["prepared_at"] <= time.time() < plan["expires_at"], "transition-review-expired")


class _AuthorizedRuntime:
    """Bound every mutating transport call to the original reviewed deadline."""

    def __init__(self, runtime, plan):
        self.inner, self.plan = runtime, plan

    def __getattr__(self, name):
        return getattr(self.inner, name)

    @property
    def read_only(self):
        return self.inner.read_only

    @read_only.setter
    def read_only(self, value):
        self.inner.read_only = value

    @property
    def serialized_provisioning(self):
        return self.inner.serialized_provisioning

    @serialized_provisioning.setter
    def serialized_provisioning(self, value):
        self.inner.serialized_provisioning = value

    def arm(self, method, *args, **kwargs):
        if method not in ("GET", "HEAD"):
            _authorized(self.plan)
        return self.inner.arm(method, *args, **kwargs)

    def blob(self, method, *args, **kwargs):
        if method not in ("GET", "HEAD"):
            _authorized(self.plan)
        return self.inner.blob(method, *args, **kwargs)

    def run_probe(self, writer, request, script, *, resume=False):
        require(request["expires_at"] <= self.plan["expires_at"], "probe-exceeds-reviewed-authorization")
        if not resume:
            _authorized(self.plan)
        return self.inner.run_probe(writer, request, script, resume=resume)


def _references_after(before, after, allowed_ids):
    remaining = copy.deepcopy(after)
    for item in before:
        if item not in remaining:
            return False
        remaining.remove(item)
    return (all(set(item) == {"id"} and item["id"].lower() in allowed_ids for item in remaining)
            and len({item["id"].lower() for item in remaining}) == len(remaining))


def _subnet_after_endpoint(before, after, endpoint_id, configuration_ids):
    old, new = copy.deepcopy(before), copy.deepcopy(after)
    old.pop("etag", None)
    new.pop("etag", None)
    for field, allowed in (("privateEndpoints", {endpoint_id}), ("ipConfigurations", configuration_ids)):
        old_refs = old.get("properties", {}).pop(field, [])
        new_refs = new.get("properties", {}).pop(field, [])
        if not _references_after(old_refs, new_refs, allowed):
            return False
    return old == new


def _dns_link_configuration(value):
    result = _account_snapshot(value)
    for field in ("provisioningState", "virtualNetworkLinkState"):
        result.get("properties", {}).pop(field, None)
    return result


def _wait_dns_link(plan, state, runtime, effect, observed, persist):
    identifier = effect["id"]
    readiness = state.setdefault("dns_link_readiness", {})
    entry = readiness.get(identifier)
    if entry is None:
        entry = {"effect_hash": digest(effect), "configuration": _dns_link_configuration(observed["value"]),
                 "started_at": time.time(), "deadline": min(plan["expires_at"], time.time() + 120),
                 "provisioning_state": None, "link_state": None}
        readiness[identifier] = entry
        persist()
    require(entry["effect_hash"] == digest(effect), "dns-link-readiness-journal-conflict")
    while True:
        _authorized(plan)
        value = observed["value"]
        require(value and _contains(value, effect["body"])
                and _dns_link_configuration(value) == entry["configuration"],
                "dns-link-configuration-changed-during-readiness")
        properties = value.get("properties", {})
        provisioning = properties.get("provisioningState")
        link = properties.get("virtualNetworkLinkState")
        require(provisioning in ("Creating", "Updating", "Succeeded")
                and link in ("InProgress", "Completed"), "dns-link-readiness-invalid-or-failed")
        require(entry["provisioning_state"] != "Succeeded" or provisioning == "Succeeded",
                "dns-link-provisioning-state-regressed")
        require(entry["link_state"] != "Completed" or link == "Completed", "dns-link-state-regressed")
        entry.update(provisioning_state=provisioning, link_state=link)
        if provisioning == "Succeeded" and link == "Completed":
            entry["status"] = "ready"
            persist()
            return observed
        entry["status"] = "waiting"
        persist()
        remaining = min(entry["deadline"], plan["expires_at"]) - time.time()
        require(remaining > 0, "dns-link-readiness-timeout")
        time.sleep(min(2, remaining))
        _authorized(plan)
        observed = _read(runtime, identifier, effect["api"])
        _authorized(plan)


def _dns_children(plan, state, runtime, persist):
    zone_id = plan["context"]["dns_zone_id"].lower()
    effects = [effect for effect in plan["effects"]
               if effect["id"].startswith(zone_id + "/virtualnetworklinks/")
               or effect["id"].startswith(plan["private_endpoint_id"] + "/privatednszonegroups/")]
    require(len(effects) <= 128, "dns-child-validation-bound-exceeded")
    snapshots = state.setdefault("dns_child_observations", {})
    applied, links, records = set(), 0, 0

    def retain(identifier, observed):
        require(identifier not in snapshots or snapshots[identifier] == observed, "journaled-dns-child-drift")
        snapshots.setdefault(identifier, copy.deepcopy(observed))

    for effect in effects:
        journaled = state.get("resource_journal", {}).get(effect["id"])
        if not journaled:
            continue
        require(journaled["effect_hash"] == digest(effect), "dns-effect-journal-proof-invalid")
        child = _read(runtime, effect["id"], effect["api"])
        if child["value"] is None and journaled["state"] == "submitted":
            continue
        require(child["value"] and _contains(child["value"], effect["body"]),
                "journaled-dns-child-conflict")
        if effect["id"].startswith(zone_id + "/virtualnetworklinks/"):
            child = _wait_dns_link(plan, state, runtime, effect, child, persist)
            require(child["value"]["properties"].get("registrationEnabled") is False,
                    "journaled-dns-link-registration-conflict")
            retain(effect["id"], child)
            links += 1
        else:
            require(child["value"].get("properties", {}).get("provisioningState", "Succeeded") == "Succeeded",
                    "journaled-dns-child-conflict")
            endpoint = _read(runtime, plan["private_endpoint_id"], NETWORK_API)["value"]
            private_ip = _private_ip(runtime, endpoint, plan["coordination"]["account_id"],
                                     plan["context"]["private_endpoint_subnet_id"].lower())
            record = _read(runtime, plan["record_id"], DNS_API)
            configs = child["value"]["properties"].get("privateDnsZoneConfigs", [])
            require(len(configs) == 1, "journaled-dns-group-conflict")
            managed = configs[0].get("properties", {}).get("recordSets", [])
            name = plan["coordination"]["account_id"].rsplit("/", 1)[1]
            require(len(managed) == 1 and managed[0].get("recordType", "").upper() == "A"
                    and managed[0].get("recordSetName", "").lower() == name
                    and managed[0].get("fqdn", "").rstrip(".").lower() == name + ".privatelink.blob.core.windows.net"
                    and managed[0].get("ipAddresses") == [private_ip]
                    and record["value"] and record["value"].get("properties", {}).get("aRecords") == [{"ipv4Address": private_ip}]
                    and record["value"]["properties"].get("ttl") == managed[0].get("ttl"),
                    "journaled-managed-dns-record-conflict")
            retain(effect["id"], child)
            retain(plan["record_id"], record)
            records += 1
        applied.add(effect["id"])
    require(records <= 1, "ambiguous-managed-dns-record-effects")
    return applied, {"numberOfVirtualNetworkLinks": links, "numberOfRecordSets": records,
                     "numberOfVirtualNetworkLinksWithRegistration": 0}


def _zone_after_children(before, after, increments):
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    old, new = copy.deepcopy(before), copy.deepcopy(after)
    old.pop("etag", None)
    new.pop("etag", None)
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    for field, increment in increments.items():
        if field in old_props:
            initial, actual = old_props.pop(field), new_props.pop(field, None)
            if type(initial) is not int or initial < 0 or type(actual) is not int or actual != initial + increment:
                return False
    return old == new


def _reconcile_observations(plan, state, runtime, persist):
    """Reconcile exact journaled PE references and verified DNS-child counters."""
    endpoint_id = plan["private_endpoint_id"]
    submitted = state.get("resource_journal", {}).get(endpoint_id)
    subnet_id = plan["context"]["private_endpoint_subnet_id"].lower()
    vnet_id = subnet_id.rsplit("/subnets/", 1)[0]
    endpoint, configuration_ids = None, set()
    if submitted:
        effect = next((e for e in plan["effects"] if e["id"] == endpoint_id), None)
        require(effect and submitted["effect_hash"] == digest(effect), "endpoint-journal-proof-invalid")
        endpoint = _read(runtime, endpoint_id, NETWORK_API)["value"]
        if endpoint:
            nic_id = _endpoint(endpoint, plan["coordination"]["account_id"], subnet_id)
            nic = _read(runtime, nic_id, NETWORK_API)["value"]
            require(nic and nic.get("properties", {}).get("privateEndpoint", {}).get("id", "").lower() == endpoint_id,
                    "private-endpoint-nic-owner-conflict")
            configuration_ids = {entry["id"].lower() for entry in nic["properties"].get("ipConfigurations", [])
                                 if entry.get("id")}
    journal = state.setdefault("reconciled_observations", {})
    dns_effects, dns_increments = _dns_children(plan, state, runtime, persist)
    zone_id = plan["context"]["dns_zone_id"].lower()
    for original in plan["observations"]:
        if original["value"] is None:
            continue
        identifier = original["id"]
        expected = journal.get(identifier, original)
        actual = _read(runtime, identifier, original["api"])
        if identifier == zone_id:
            require(_zone_after_children(original["value"], actual["value"], dns_increments),
                    "reviewed-dns-zone-counter-or-configuration-drift")
            previous = set(state.get("dns_zone_applied_effects", []))
            if actual != expected:
                require(dns_effects and dns_effects != previous and previous <= dns_effects,
                        "reviewed-dns-zone-unexplained-drift")
                journal[identifier] = actual
            state["dns_zone_applied_effects"] = sorted(dns_effects)
            continue
        account = identifier == plan["coordination"]["account_id"]
        equal = (_account_snapshot(actual["value"]) == _account_snapshot(expected["value"])
                 if account else actual == expected)
        if equal:
            continue
        require(identifier not in journal and endpoint, "reviewed-private-resource-changed")
        old, new = copy.deepcopy(original["value"]), copy.deepcopy(actual["value"])
        allowed = False
        if identifier == subnet_id:
            allowed = _subnet_after_endpoint(old, new, endpoint_id, configuration_ids)
        elif identifier == vnet_id:
            old.pop("etag", None)
            new.pop("etag", None)
            old_subnets = old["properties"].pop("subnets", [])
            new_subnets = new["properties"].pop("subnets", [])
            if len(old_subnets) == len(new_subnets) and old == new:
                allowed = True
                for prior in old_subnets:
                    matches = [item for item in new_subnets if item.get("id", "").lower() == prior.get("id", "").lower()]
                    if len(matches) != 1 or not (
                        _subnet_after_endpoint(prior, matches[0], endpoint_id, configuration_ids)
                        if prior.get("id", "").lower() == subnet_id else prior == matches[0]):
                        allowed = False
                        break
        elif account:
            old, new = _account_snapshot(old), _account_snapshot(new)
            old_connections = old["properties"].pop("privateEndpointConnections", [])
            new_connections = new["properties"].pop("privateEndpointConnections", [])
            remaining = copy.deepcopy(new_connections)
            for connection in old_connections:
                if connection not in remaining:
                    break
                remaining.remove(connection)
            else:
                allowed = old == new and len(remaining) == 1 and (
                    remaining[0].get("properties", {}).get("privateEndpoint", {}).get("id", "").lower() == endpoint_id
                    and remaining[0]["properties"].get("privateLinkServiceConnectionState", {}).get("status") == "Approved")
        require(allowed, "reviewed-private-resource-changed")
        journal[identifier] = actual


def _blob(runtime, name):
    status, headers, value = runtime.blob("GET", name, allowed=(200, 404))
    require(status == 200 and isinstance(value, dict), "hub-proof-required:" + name)
    return {"value": value, "etag": _etag(headers, value)}


def _account(value, hub):
    # Foundation's initial one-rule restriction is intentionally not reused:
    # transition must preserve any independently preexisting unrelated ACLs.
    check = copy.deepcopy(value)
    check["properties"]["publicNetworkAccess"] = "Disabled"
    check["properties"]["networkAcls"] = {"defaultAction": "Deny", "bypass": "None", "ipRules": []}
    foundation.validate_shared_account(check, hub)
    network = value["properties"].get("networkAcls", {})
    require(network.get("defaultAction") == "Deny" and network.get("bypass") == "None",
            "hub-account-firewall-not-deny-default")
    require(value["properties"].get("publicNetworkAccess") in ("Enabled", "Disabled"),
            "hub-account-network-mode-invalid")


def _endpoint(value, account, subnet):
    require(value and value.get("properties", {}).get("provisioningState") == "Succeeded",
            "private-endpoint-not-ready")
    props = value["properties"]
    connections = props.get("privateLinkServiceConnections", []) + props.get("manualPrivateLinkServiceConnections", [])
    require(len(connections) == 1
            and connections[0]["properties"].get("privateLinkServiceId", "").lower() == account
            and connections[0]["properties"].get("groupIds") == ["blob"]
            and connections[0]["properties"].get("privateLinkServiceConnectionState", {}).get("status") == "Approved"
            and props.get("subnet", {}).get("id", "").lower() == subnet,
            "private-endpoint-target-subnet-or-approval-conflict")
    interfaces = props.get("networkInterfaces", [])
    require(len(interfaces) == 1, "private-endpoint-nic-ambiguous")
    return _id(interfaces[0]["id"], "microsoft.network/networkinterfaces")


def _private_ip(runtime, endpoint, account, subnet):
    nic_id = _endpoint(endpoint, account, subnet)
    nic = _read(runtime, nic_id, NETWORK_API)
    props = (nic["value"] or {}).get("properties", {})
    require(props.get("privateEndpoint", {}).get("id", "").lower() == endpoint["id"].lower(),
            "private-endpoint-nic-owner-conflict")
    configs = props.get("ipConfigurations", [])
    require(len(configs) == 1, "private-endpoint-ip-ambiguous")
    value = configs[0]["properties"].get("privateIPAddress")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise TransitionError("private-endpoint-assigned-ip-required") from None
    require(address.version == 4 and address.is_private and not address.is_loopback,
            "private-endpoint-assigned-ip-required")
    return str(address)


def _writers(registry, coordination, hub):
    require(registry.get("schema") == 1 and registry.get("hub_resource_group_id", "").lower() == hub
            and registry.get("inventory_complete") is True and isinstance(registry.get("writers"), dict),
            "complete-hub-writer-registry-required")
    require(coordination.get("protocol") == "aifactory-physical-lock-v1"
            and coordination.get("enforcement") == "all-writers-exclusive"
            and isinstance(coordination.get("writers"), dict) and isinstance(coordination.get("scopes"), dict),
            "authoritative-coordination-required")
    all_writers = coordination["writers"]
    referenced = {w for s in coordination["scopes"].values() for w in s.get("writers", [])}
    require(referenced <= set(all_writers), "unknown-scope-writer")
    factory_routes = {}
    for scope in coordination["scopes"].values():
        factory = scope.get("target", {}).get("factory_id")
        if factory:
            routes = factory_routes.setdefault(factory, set())
            routes.update((all_writers[w].get("kind"), all_writers[w].get("repository")) for w in scope["writers"])
            require(len(routes) == 1, "one-provider-repository-per-factory-required")
    result = {}
    for name in set(all_writers) | set(registry["writers"]):
        target = registry["writers"].get(name)
        require(isinstance(target, dict), "unknown-hub-writer:" + name)
        if target.get("status") == "inactive":
            require(name not in all_writers and name not in referenced and target.get("reason")
                    and target.get("de_enrollment_revision") == coordination.get("revision"),
                    "writer-not-explicitly-de-enrolled:" + name)
            continue
        writer = all_writers.get(name)
        require(isinstance(writer, dict), "unregistered-hub-writer:" + name)
        require(target.get("provider") == writer.get("kind")
                and target.get("repository") == writer.get("repository")
                and target.get("principal_id") == writer.get("deployment_object_id")
                and writer.get("runner", {}).get("kind") == "self-hosted",
                "registered-writer-identity-conflict:" + name)
        require(re.fullmatch(r"[0-9a-f]{40}", str(target.get("source_commit", "")))
                and isinstance(target.get("probe_path"), str)
                and not any(x in ("", ".", "..") for x in target["probe_path"].split("/")),
                "pinned-provider-probe-source-required")
        enrollment.guid(target["principal_id"])
        enrollment.guid(target["tenant_id"])
        _id(target["vm_id"], "microsoft.compute/virtualmachines")
        require(str(target.get("runner_id", "")).isdigit() and str(target.get("repository_id", "")),
                "provider-runner-repository-identity-required")
        result[name] = copy.deepcopy(target)
    require(result, "active-private-writer-required")
    return result


class Cloud(foundation.Cloud):
    """Native ARM/Blob/provider transport; dependency injection only for tests."""

    def provider_read(self, writer, path):
        if writer["provider"] == "gha":
            return self.gh("GET", path)[2]
        organization = urlsplit(writer["repository"]).path.strip("/").split("/")[0]
        url = "https://dev.azure.com/" + quote(organization, safe="") + "/" + path
        return self.http("GET", url, enrollment.ADO_AUDIENCE,
                         tenant=enrollment.guid(writer.get("provider_tenant_id", writer["tenant_id"])))[2]

    def foundation_proofs(self):
        prefix = "bootstrap/foundation/"
        marker, seen, proofs = "", set(), []
        for _ in range(20):
            query = "?restype=container&comp=list&prefix=" + quote(prefix, safe="") + "&maxresults=100"
            if marker:
                query += "&marker=" + quote(marker, safe="")
            coordinates = self.request_config["coordinates"]
            _, _, value = self.http("GET", coordinates["account_url"] + "/hub-locks" + query, enrollment.STORAGE)
            require(isinstance(value, bytes), "foundation-proof-list-invalid")
            document = ElementTree.fromstring(value)
            for entry in document.findall("./Blobs/Blob/Name"):
                name = entry.text or ""
                require(re.fullmatch(r"bootstrap/foundation/[0-9a-f-]{36}\.json", name),
                        "foundation-proof-name-invalid")
                proofs.append(_blob(self, name))
            marker = document.findtext("NextMarker") or ""
            if not marker:
                return proofs
            require(marker not in seen, "foundation-proof-list-pagination-loop")
            seen.add(marker)
        raise TransitionError("foundation-proof-list-incomplete")

    def discover_writer_target(self, writer, bindings, tenant, source):
        """Resolve IDs/commit from provider authority, not new user/profile fields."""
        vm_id = _id(bindings["runner_vm_id"], "microsoft.compute/virtualmachines")
        vm = _read(self, vm_id, COMPUTE_API)["value"]
        require(vm, "runner-vm-missing")
        provider = writer["kind"]
        target = {"provider": provider, "repository": writer["repository"], "tenant_id": tenant,
                  "principal_id": enrollment.guid(writer["deployment_object_id"]), "vm_id": vm_id,
                  "probe_path": bindings.get("runner_probe_path", ".azurefactory/hub_private_probe.py")}
        if bindings.get("deployment_client_id"):
            target["client_id"] = enrollment.guid(bindings["deployment_client_id"])
        if bindings.get("provider_tenant_id"):
            target["provider_tenant_id"] = enrollment.guid(bindings["provider_tenant_id"])
        runner_names = {value for value in (bindings.get("runner_name"), bindings.get("runner_agent_name"),
                        writer.get("runner", {}).get("agent_name"), vm.get("name"),
                        vm.get("properties", {}).get("osProfile", {}).get("computerName"),
                        vm_id.rsplit("/", 1)[1]) if value}
        if provider == "gha":
            slug = target["repository"].removeprefix("https://github.com/").removesuffix(".git")
            require(re.fullmatch(r"[\w.-]+/[\w.-]+", slug), "github-repository-required")
            base = "repos/" + slug
            repository = self.provider_read(target, base)
            target["repository_id"] = repository["id"]
            published_ref = bindings.get("publication_ref") or repository.get("default_branch")
            require(isinstance(published_ref, str) and published_ref, "published-source-ref-required")
            target["source_commit"] = self.provider_read(target, base + "/commits/" + quote(published_ref, safe=""))["sha"]
            runners = []
            for page in range(1, 101):
                value = self.provider_read(target, base + "/actions/runners?per_page=100&page=" + str(page))
                rows = value.get("runners")
                require(isinstance(rows, list), "provider-runner-list-invalid")
                runners.extend(rows)
                if len(rows) < 100:
                    break
            else:
                raise TransitionError("provider-runner-list-incomplete")
            candidates = [r for r in runners if r.get("name") in runner_names]
            target["runner_config_path"] = bindings.get("runner_config_path", "/opt/aifactory-gha-runner/.runner")
        else:
            require(re.fullmatch(r"https://dev\.azure\.com/[\w.-]+/[^/]+/_git/[^/]+", target["repository"]),
                    "ado-repository-required")
            _, project, _, repo_name = urlsplit(target["repository"]).path.strip("/").split("/")
            base = quote(project, safe="") + "/_apis/git/repositories/" + quote(repo_name, safe="")
            repository = self.provider_read(target, base + "?api-version=7.1")
            target["repository_id"] = repository["id"]
            published_ref = bindings.get("publication_ref") or repository.get("defaultBranch")
            require(isinstance(published_ref, str) and published_ref.startswith("refs/heads/"),
                    "published-source-ref-required")
            refs = self.provider_read(target, base + "/refs?filter=" + quote(published_ref.removeprefix("refs/"), safe="")
                                      + "&api-version=7.1").get("value", [])
            refs = [r for r in refs if r.get("name") == published_ref]
            require(len(refs) == 1, "published-source-ref-ambiguous")
            target["source_commit"] = refs[0]["objectId"]
            pool_name = writer.get("runner", {}).get("pool")
            pools = self.provider_read(target, "_apis/distributedtask/pools?poolName=" + quote(str(pool_name), safe="")
                                       + "&api-version=7.1").get("value", [])
            pools = [p for p in pools if p.get("name") == pool_name]
            require(len(pools) == 1, "provider-runner-pool-ambiguous")
            target["pool_id"] = pools[0]["id"]
            runners = self.provider_read(target, "_apis/distributedtask/pools/" + str(target["pool_id"])
                                         + "/agents?includeCapabilities=true&api-version=7.1").get("value", [])
            candidates = [r for r in runners if r.get("name") in runner_names]
            windows = vm.get("properties", {}).get("storageProfile", {}).get("osDisk", {}).get("osType") == "Windows"
            target["runner_config_path"] = bindings.get("runner_config_path",
                r"C:\aifactory-agent\.agent" if windows else "/opt/aifactory-agent/.agent")
        require(len(candidates) == 1, "selected-vm-provider-runner-ambiguous")
        target.update(runner_id=candidates[0]["id"], runner_name=candidates[0]["name"])
        self.attest_writer(target, source["probe_sha256"])
        return target

    def attest_writer(self, writer, source_hash):
        repo = writer["repository"]
        if writer["provider"] == "gha":
            require(re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?", repo),
                    "github-repository-required")
            slug = repo.removeprefix("https://github.com/").removesuffix(".git")
            base = "repos/" + slug
            repository = self.provider_read(writer, base)
            require(str(repository.get("id")) == str(writer["repository_id"])
                    and repository.get("full_name", "").lower() == slug.lower(), "provider-repository-mismatch")
            runner = self.provider_read(writer, base + "/actions/runners/" + str(writer["runner_id"]))
            require(str(runner.get("id")) == str(writer["runner_id"]) and runner.get("name") == writer["runner_name"]
                    and runner.get("os", "").lower() == "linux" and runner.get("status") == "online",
                    "provider-runner-mismatch")
            commit = self.provider_read(writer, base + "/commits/" + writer["source_commit"])
            require(commit.get("sha") == writer["source_commit"], "provider-source-commit-mismatch")
            source = self.provider_read(writer, base + "/contents/" + quote(writer["probe_path"], safe="/")
                                        + "?ref=" + writer["source_commit"])
            require(source.get("encoding") == "base64" and source.get("type") == "file",
                    "provider-probe-source-invalid")
            raw = base64.b64decode(source["content"])
            os_type = "Linux"
        else:
            require(re.fullmatch(r"https://dev\.azure\.com/[\w.-]+/[^/]+/_git/[^/]+", repo),
                    "ado-repository-required")
            _, project, _, _ = urlsplit(repo).path.strip("/").split("/")
            base = quote(project, safe="") + "/_apis/git/repositories/" + quote(str(writer["repository_id"]), safe="")
            repository = self.provider_read(writer, base + "?api-version=7.1")
            require(str(repository.get("id", "")).lower() == str(writer["repository_id"]).lower()
                    and repository.get("webUrl", "").lower() == repo.lower(), "provider-repository-mismatch")
            require(str(writer.get("pool_id", "")).isdigit(), "ado-pool-required")
            runner = self.provider_read(writer, "_apis/distributedtask/pools/" + str(writer["pool_id"])
                                        + "/agents/" + str(writer["runner_id"]) + "?includeCapabilities=true&api-version=7.1")
            require(str(runner.get("id")) == str(writer["runner_id"]) and runner.get("name") == writer["runner_name"]
                    and runner.get("enabled") is True and runner.get("status") == "online",
                    "provider-runner-mismatch")
            source = self.provider_read(writer, base + "/items?path=" + quote(writer["probe_path"], safe="")
                                        + "&includeContent=true&versionDescriptor.versionType=commit"
                                        + "&versionDescriptor.version=" + writer["source_commit"] + "&api-version=7.1")
            require(source.get("commitId") == writer["source_commit"], "provider-source-commit-mismatch")
            raw = source["content"].encode("utf-8")
            os_type = "Windows" if runner.get("systemCapabilities", {}).get("Agent.OS") == "Windows_NT" else "Linux"
        require(hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == source_hash, "provider-probe-source-hash-mismatch")
        vm = _read(self, writer["vm_id"].lower(), COMPUTE_API)
        require(vm["value"], "runner-vm-missing")
        identity = vm["value"].get("identity", {})
        principals = {identity.get("principalId", "").lower()}
        principals.update(x.get("principalId", "").lower() for x in identity.get("userAssignedIdentities", {}).values())
        require(writer["principal_id"] in principals, "runner-vm-managed-identity-mismatch")
        props = vm["value"].get("properties", {})
        require(props.get("provisioningState") == "Succeeded"
                and props.get("storageProfile", {}).get("osDisk", {}).get("osType") == os_type,
                "runner-vm-os-or-state-mismatch")
        return {"vm_id": writer["vm_id"].lower(), "vm_snapshot": _vm_snapshot(vm["value"]), "os": os_type,
                "repository_id": writer["repository_id"], "runner_id": writer["runner_id"],
                "source_commit": writer["source_commit"], "source_sha256": source_hash}

    def run_probe(self, writer, request, script, *, resume=False):
        require(hashlib.sha256(script).hexdigest() == request["source_sha256"], "runner-script-source-changed")
        identifier = request["operation_id"]
        encoded_script = base64.b64encode(script).decode()
        encoded_request = base64.b64encode(canonical(request)).decode()
        python = "import base64,sys;sys.argv=['probe','" + encoded_request + "'];exec(base64.b64decode('" + encoded_script + "'))"
        if request["runner_os"] == "Windows":
            command = "$ErrorActionPreference='Stop'\npython.exe -c \"" + python.replace('"', '`"') + "\"\nexit $LASTEXITCODE"
        else:
            command = "set -eu\npython3 -c " + "'" + python.replace("'", "'\"'\"'") + "'"
        body = {"location": request["vm_location"], "properties": {"source": {"script": command},
                "asyncExecution": False,
                "timeoutInSeconds": min(600, max(1, int(request["expires_at"] - request["issued_at"])))}}
        if not resume:
            require(_read(self, identifier, COMPUTE_API)["value"] is None, "probe-operation-already-exists")
            vm = _read(self, writer["vm_id"].lower(), COMPUTE_API)["value"]
            require(vm and vm.get("properties", {}).get("provisioningState") == "Succeeded"
                    and digest(_vm_snapshot(vm)) == request["vm_snapshot_sha256"],
                    "runner-vm-configuration-changed-before-dispatch")
            require(request["issued_at"] <= time.time() < request["expires_at"], "probe-request-expired")
            self.arm("PUT", identifier, COMPUTE_API, data=body, headers={"If-None-Match": "*"},
                     allowed=(200, 201, 202))
        for _ in range(150):
            status, _, operation = self.arm("GET", identifier + "?$expand=instanceView", COMPUTE_API, allowed=(200, 404))
            if status == 200:
                require(operation.get("id", "").lower() == identifier.lower(), "run-command-identity-mismatch")
                props = operation.get("properties", {})
                require(props.get("source", {}).get("script") == command, "run-command-source-mismatch")
                view = props.get("instanceView", {})
                state = view.get("executionState")
                require(state not in ("Failed", "Canceled", "TimedOut"), "runner-probe-failed")
                if state == "Succeeded":
                    require(view.get("exitCode") == 0 and not view.get("error"), "runner-probe-failed")
                    lines = [line.removeprefix("AFHUB_ATTESTATION:") for line in view.get("output", "").splitlines()
                             if line.startswith("AFHUB_ATTESTATION:")]
                    require(len(lines) == 1, "runner-attestation-missing")
                    return enrollment.parse_json(lines[0])
            time.sleep(4)
        raise TransitionError("runner-probe-outcome-uncertain")


def prepare(*, source_root, tenant_id, hub_resource_group_id, context, expected_source_hash=None, runtime=None,
            phase="transition"):
    require(phase in ("probe", "transition"), "invalid-private-access-phase")
    source = source_fingerprint(source_root)
    verify_source_snapshot(source_root=source_root, expected_payload_sha256=expected_source_hash or source["payload_sha256"])
    tenant, hub = enrollment.guid(tenant_id), enrollment.rg_id(hub_resource_group_id)
    coordinates = foundation.coordination(hub)
    target = {"tenant_id": tenant, "subscription_id": hub.split("/")[2]}
    runtime = runtime or Cloud(target, coordinates)
    runtime.read_only = True
    principal = runtime.principal()
    subnet = _id(context["private_endpoint_subnet_id"], "microsoft.network/virtualnetworks/subnets")
    require(subnet.split("/providers/", 1)[0] == hub,
            "private-endpoint-subnet-must-be-in-retained-connectivity-hub")
    zone = _id(context["dns_zone_id"], "microsoft.network/privatednszones")
    require(zone.endswith("/privatelink.blob.core.windows.net"), "blob-private-dns-zone-required")
    vnets = sorted({_id(v, "microsoft.network/virtualnetworks") for v in context["dns_vnet_ids"]})
    require(subnet.rsplit("/subnets/", 1)[0] in vnets, "endpoint-vnet-dns-link-required")
    account = _read(runtime, coordinates["account_id"], enrollment.STORAGE_API)
    require(account["value"], "hub-foundation-required")
    _account(account["value"], hub)
    subnet_observation = _read(runtime, subnet, NETWORK_API)
    require(subnet_observation["value"], "private-endpoint-subnet-missing")
    require(subnet_observation["value"].get("properties", {}).get("provisioningState") == "Succeeded",
            "private-endpoint-subnet-not-ready")
    require(not subnet_observation["value"].get("properties", {}).get("delegations"), "private-endpoint-subnet-delegated")
    observations = [account, subnet_observation]
    for vnet in vnets:
        value = _read(runtime, vnet, NETWORK_API)
        require(value["value"], "dns-vnet-missing")
        if vnet == subnet.rsplit("/subnets/", 1)[0]:
            require(value["value"].get("properties", {}).get("provisioningState") == "Succeeded",
                    "private-endpoint-vnet-not-ready")
            require(not any(key.lower() in ("aifactory.factory_id", "aifactory.scaleset_id")
                            for key in (value["value"].get("tags") or {})),
                    "shared-hub-vnet-has-factory-ownership")
        observations.append(value)
    registries = {COORDINATION: _blob(runtime, COORDINATION)}
    status, headers, value = runtime.blob("GET", REGISTRY, allowed=(200, 404))
    require(status in (200, 404), "writer-registry-read-failed")
    registries[REGISTRY] = {"value": value if status == 200 else None,
                            "etag": _etag(headers, value) if status == 200 else None}
    desired_registry = copy.deepcopy(value) if status == 200 else {
        "schema": 1, "hub_resource_group_id": hub, "inventory_complete": True, "writers": {}}
    require(isinstance(desired_registry, dict) and isinstance(desired_registry.get("writers"), dict),
            "invalid-private-writer-registry")
    for name, writer in context.get("writer_targets", {}).items():
        prior = desired_registry["writers"].get(name)
        stable = lambda value: {k: v for k, v in value.items() if k not in ("source_commit", "probe_path")}
        require(prior is None or stable(prior) == stable(writer), "existing-private-writer-target-conflict")
        desired_registry["writers"][name] = copy.deepcopy(writer)
    writers = _writers(desired_registry, registries[COORDINATION]["value"], hub)
    require(context["closure_writer_id"] in writers, "closure-writer-not-registered")
    writer_attestations = {}
    for name, writer in writers.items():
        require(writer["tenant_id"] == tenant, "writer-tenant-mismatch")
        writer_attestations[name] = runtime.attest_writer(writer, source["probe_sha256"])
    endpoint_vnet = subnet.rsplit("/subnets/", 1)[0]
    location = next(observed["value"].get("location") for observed in observations if observed["id"] == endpoint_vnet)
    require(isinstance(location, str) and re.fullmatch(r"[a-z0-9]{2,40}", location),
            "private-endpoint-vnet-location-required")
    endpoint_id = hub + "/providers/microsoft.network/privateendpoints/" + coordinates["account_id"].rsplit("/", 1)[1] + "-blob"
    endpoint = _read(runtime, endpoint_id, NETWORK_API)
    observations.append(endpoint)
    private_ip = _private_ip(runtime, endpoint["value"], coordinates["account_id"], subnet) if endpoint["value"] else None
    tags = foundation.ownership_tags(hub)
    effects = []

    def ensure(identifier, api, body):
        observed = _read(runtime, identifier, api)
        observations.append(observed)
        if observed["value"] is None:
            effects.append({"id": identifier, "api": api, "body": body, "ownership": "external-retain-never-delete"})
        else:
            require(_contains(observed["value"], body), "existing-private-resource-conflict:" + identifier)

    if endpoint["value"] is None:
        effects.append({"id": endpoint_id, "api": NETWORK_API, "ownership": "external-retain-never-delete",
                        "body": {"location": location, "tags": tags, "properties": {
                            "subnet": {"id": subnet}, "privateLinkServiceConnections": [{"name": "blob",
                            "properties": {"privateLinkServiceId": coordinates["account_id"], "groupIds": ["blob"]}}]}}})
    # No tags are imposed on a reused shared zone or link.
    ensure(zone, DNS_API, {"location": "global"})
    zone_exists = observations[-1]["value"] is not None
    links = runtime.collection(zone + "/virtualNetworkLinks", DNS_API) if zone_exists else []
    for vnet in vnets:
        matches = [link for link in links
                   if link.get("properties", {}).get("virtualNetwork", {}).get("id", "").lower() == vnet]
        require(len(matches) <= 1, "ambiguous-existing-dns-vnet-links")
        link_id = matches[0]["id"].lower() if matches else zone + "/virtualnetworklinks/afhub-" + digest(vnet)[:20]
        ensure(link_id, DNS_API, {"location": "global", "properties": {
            "virtualNetwork": {"id": vnet}, "registrationEnabled": False}})
        existing_link = observations[-1]["value"]
        if existing_link:
            require(existing_link["properties"].get("provisioningState") == "Succeeded"
                    and existing_link["properties"].get("virtualNetworkLinkState") == "Completed",
                    "existing-dns-link-readiness-required")
    record_id = zone + "/a/" + coordinates["account_id"].rsplit("/", 1)[1]
    record = _read(runtime, record_id, DNS_API)
    observations.append(record)
    cname = _read(runtime, record_id.replace("/a/", "/cname/"), DNS_API)
    observations.append(cname)
    require(cname["value"] is None, "shared-dns-cname-would-conflict")
    if record["value"]:
        require(private_ip and record["value"].get("properties", {}).get("aRecords") == [{"ipv4Address": private_ip}],
                "shared-dns-record-would-be-overwritten")
    group_body = {"properties": {"privateDnsZoneConfigs": [{"name": "blob", "properties": {"privateDnsZoneId": zone}}]}}
    groups = runtime.collection(endpoint_id + "/privateDnsZoneGroups", NETWORK_API) if endpoint["value"] else []
    require(len(groups) <= 1, "ambiguous-private-endpoint-zone-groups")
    if groups:
        configs = groups[0].get("properties", {}).get("privateDnsZoneConfigs", [])
        require(len(configs) == 1 and configs[0].get("properties", {}).get("privateDnsZoneId", "").lower() == zone,
                "existing-endpoint-dns-zone-conflict")
        group_body["properties"]["privateDnsZoneConfigs"][0]["name"] = configs[0]["name"]
    group_id = groups[0]["id"].lower() if groups else endpoint_id + "/privatednszonegroups/default"
    # An existing exact manual record already supplies the required DNS
    # configuration; attaching a new zone group would take over its TTL/metadata.
    if groups or record["value"] is None:
        ensure(group_id, NETWORK_API, group_body)
    expected_network = {k: copy.deepcopy(account["value"]["properties"].get(k))
                        for k in ("networkAcls", "publicNetworkAccess")}
    desired_network = copy.deepcopy(expected_network)
    proof = None
    if phase == "transition" and expected_network["publicNetworkAccess"] != "Disabled":
        reference = context.get("foundation_receipt", {})
        if reference.get("plan_id"):
            plan_id = enrollment.guid(reference["plan_id"])
            proof = _blob(runtime, "bootstrap/foundation/" + plan_id + ".json")
        if proof is None or proof["value"].get("bootstrap_network_access", {}).get("added_by_this_execution") is not True:
            candidates = [candidate for candidate in runtime.foundation_proofs()
                if candidate["value"].get("status") == "succeeded"
                and candidate["value"].get("hub_resource_group_id") == hub
                and candidate["value"].get("coordination") == coordinates
                and candidate["value"].get("bootstrap_network_access", {}).get("added_by_this_execution") is True
                and candidate["value"].get("bootstrap_network_access", {}).get("rule")
                    in expected_network["networkAcls"].get("ipRules", [])]
            require(len(candidates) == 1, "unique-created-bootstrap-rule-provenance-required")
            proof = candidates[0]
        receipt = proof["value"]
        access = receipt.get("bootstrap_network_access", {})
        require(receipt.get("status") == "succeeded" and receipt.get("hub_resource_group_id") == hub
                and receipt.get("coordination") == coordinates and access.get("account_id") == coordinates["account_id"]
                and access.get("added_by_this_execution") is True and access.get("rule_write_state") == "verified-created"
                and access.get("rule_origin") == "planned-with-new-account",
                "bootstrap-rule-created-provenance-required")
        rule = access.get("rule")
        require(rule and rule.get("action") == "Allow" and foundation._public_ipv4(rule.get("value")),
                "bootstrap-rule-proof-invalid")
        rules = desired_network["networkAcls"].get("ipRules", [])
        require(rules.count(rule) == 1, "bootstrap-rule-changed-or-ambiguous")
        desired_network["networkAcls"]["ipRules"] = [r for r in rules if r != rule]
        acl = desired_network["networkAcls"]
        # Preexisting alternate paths are retained, never implicitly disabled.
        if not any(acl.get(k) for k in ("ipRules", "virtualNetworkRules", "resourceAccessRules")):
            desired_network["publicNetworkAccess"] = "Disabled"
    plan = {"contract_version": CONTRACT_VERSION, "stage": "hub-private-" + phase, "plan_id": str(uuid4()),
            "source": source, "prepared_at": time.time(), "expires_at": time.time() + 900,
            "target": target, "principal_id": principal, "hub_resource_group_id": hub, "coordination": coordinates,
            "context": copy.deepcopy(context), "observations": observations, "effects": effects,
            "registries": registries, "writers": writers, "writer_attestations": writer_attestations,
            "desired_registry": desired_registry,
            "foundation_proof": proof, "private_endpoint_id": endpoint_id, "record_id": record_id,
            "private_ip": private_ip, "expected_network": expected_network, "desired_network": desired_network,
            "account_snapshot": _account_snapshot(account["value"]),
            "account_concurrency": "physical-hub-lease-and-frozen-storage-snapshot",
            "blockers": [], "can_execute": True,
            "lock_scopes": [hub], "runtime_ready": False}
    plan["commands"] = [{"transport": "arm", "method": "PUT", "resource_id": effect["id"],
                         "api_version": effect["api"], "body": copy.deepcopy(effect["body"]),
                         "precondition": "physical-hub-lease-and-If-None-Match"}
                        for effect in effects]
    if registries[REGISTRY]["value"] != desired_registry:
        plan["commands"].append({"transport": "storage", "method": "PUT", "blob": REGISTRY,
            "body": copy.deepcopy(desired_registry), "precondition": {
                "If-Match": registries[REGISTRY]["etag"]} if registries[REGISTRY]["etag"] else {"If-None-Match": "*"}})
    plan["commands"].extend({"transport": "arm-run-command", "vm_id": writer["vm_id"],
                             "writer_id": name, "source_commit": writer["source_commit"],
                             "source_sha256": source["probe_sha256"], "phase": "private-probe"}
                            for name, writer in sorted(writers.items()))
    if phase == "transition":
        plan["commands"].append({"transport": "arm-from-private-runner", "method": "PATCH",
            "resource_id": coordinates["account_id"], "runner_writer_id": context["closure_writer_id"],
            "properties": desired_network,
            "precondition": "hub-lease-frozen-registries-fresh-writer-proofs-and-storage-account-snapshot"})
    plan["auth_scopes"] = [
        {"scope": hub, "service": "arm", "permissions": ["Microsoft.Network/privateEndpoints/read",
            "Microsoft.Network/privateEndpoints/write", "Microsoft.Network/privateEndpoints/privateDnsZoneGroups/read",
            "Microsoft.Network/privateEndpoints/privateDnsZoneGroups/write", "Microsoft.Network/networkInterfaces/read"]},
        {"scope": subnet, "service": "arm", "permissions": ["Microsoft.Network/virtualNetworks/subnets/read",
            "Microsoft.Network/virtualNetworks/subnets/join/action"]},
        {"scope": zone, "service": "arm", "permissions": ["Microsoft.Network/privateDnsZones/read",
            "Microsoft.Network/privateDnsZones/write", "Microsoft.Network/privateDnsZones/virtualNetworkLinks/write"]},
        {"scope": coordinates["account_id"], "service": "arm",
         "permissions": ["Microsoft.Storage/storageAccounts/read"] +
                        (["Microsoft.Storage/storageAccounts/write"] if phase == "transition" else [])},
        {"scope": coordinates["account_url"] + "/hub-locks", "service": "storage",
         "authentication": "Entra-OAuth-only", "permissions": ["blob-read-write-lease"]}]
    plan["auth_scopes"].extend({"scope": writer["vm_id"], "service": "arm",
        "permissions": ["Microsoft.Compute/virtualMachines/read", "Microsoft.Compute/virtualMachines/runCommands/read",
                        "Microsoft.Compute/virtualMachines/runCommands/write"]} for writer in writers.values())
    plan["auth_scopes"].extend({"scope": vnet, "service": "arm",
        "permissions": ["Microsoft.Network/virtualNetworks/read", "Microsoft.Network/virtualNetworks/join/action"]}
        for vnet in vnets)
    plan["auth_scopes"].extend({"scope": writer["repository"], "service": writer["provider"],
        "permissions": ["repository-read", "pinned-commit-content-read", "selected-selfhosted-runner-read"]}
        for writer in writers.values())
    plan["plan_hash"] = digest(plan)
    return plan


def _validate_plan(plan, source_root, expected_plan_hash, recovery=False):
    require(plan.get("stage") in ("hub-private-transition", "hub-private-probe") and plan.get("contract_version") == CONTRACT_VERSION
            and plan.get("plan_hash") == expected_plan_hash
            and digest({k: v for k, v in plan.items() if k != "plan_hash"}) == expected_plan_hash,
            "transition-plan-hash-mismatch")
    require(plan.get("can_execute") is True and not plan.get("blockers"), "transition-plan-blocked")
    if not recovery:
        _authorized(plan)
    verify_source_snapshot(source_root=source_root, expected_payload_sha256=plan["source"]["payload_sha256"])
    require(source_fingerprint(source_root) == plan["source"], "transition-source-changed")
    enrollment.guid(plan["plan_id"])


def _verify_result(result, request, *, historical=False):
    require(isinstance(result, dict) and result.get("success") is True, "runner-probe-unsuccessful")
    for key in ("nonce", "plan_hash", "writer_id", "tenant_id", "principal_id", "source_commit",
                "source_sha256", "operation_id", "phase", "runner_id", "repository"):
        require(result.get(key) == request[key], "runner-attestation-mismatch:" + key)
    require(request["issued_at"] <= result.get("at", 0) <= min(time.time() + 30, request["expires_at"])
            and (historical or time.time() < request["expires_at"])
            and result.get("addresses") == [request["private_ip"]], "runner-attestation-stale-or-wrong-ip")


def _run(plan, *, source_root, expected_plan_hash, state_dir, runtime, recovery):
    _validate_plan(plan, source_root, expected_plan_hash, recovery)
    runtime = runtime or Cloud(plan["target"], plan["coordination"])
    runtime.read_only = True
    require(runtime.principal() == plan["principal_id"], "transition-operator-changed")
    folder = foundation.ordinary(state_dir)
    require(folder.is_dir(), "durable-existing-state-directory-required")
    path = foundation.ordinary(folder / ("private-transition-" + plan["plan_id"] + ".json"))
    if recovery:
        require(path.is_file(), "transition-recovery-receipt-required")
        state = enrollment.parse_json(path.read_bytes())
        require(state.get("plan_hash") == plan["plan_hash"], "transition-recovery-plan-mismatch")
        if state["status"] == "succeeded":
            return state
        if not plan["prepared_at"] <= time.time() < plan["expires_at"]:
            observed = _read(runtime, plan["coordination"]["account_id"], enrollment.STORAGE_API)
            state.update(status="approval-expired", runtime_ready=False, requires_new_approval=True,
                         reconciliation={"observed_at": time.time(),
                             "account_snapshot": _account_snapshot(observed["value"]) if observed["value"] else None,
                             "pending_effect": state.get("pending"),
                             "pending_close_operation": (state.get("close_request") or {}).get("operation_id"),
                             "mutations_permitted": False})
            _persist(path, state)
            return state
    else:
        require(not path.exists(), "transition-already-started-use-recover")
        fresh = prepare(source_root=source_root, tenant_id=plan["target"]["tenant_id"],
                        hub_resource_group_id=plan["hub_resource_group_id"], context=plan["context"], runtime=runtime,
                        phase="probe" if plan["stage"] == "hub-private-probe" else "transition")
        for key in ("observations", "registries", "writers", "writer_attestations", "effects",
                    "foundation_proof", "expected_network", "desired_network", "desired_registry"):
            require(fresh[key] == plan[key], "transition-live-state-changed:" + key)
        state = {"stage": plan["stage"], "plan_hash": plan["plan_hash"], "plan_id": plan["plan_id"],
                 "status": "uncertain", "completed": [], "pending": None, "probes": {},
                 "lease_id": str(uuid4()), "lease_state": "proposed", "runtime_ready": False,
                 "registry_publication": "not-started", "registry_snapshot": None, "resource_journal": {},
                 "registry_leases": {name: {"id": str(uuid4()), "state": "proposed"} for name in plan["registries"]}}
        with path.open("xb") as output:
            output.write(canonical(state))
            output.flush()
            os.fsync(output.fileno())
    runtime = _AuthorizedRuntime(runtime, plan)
    runtime.read_only = False
    runtime.serialized_provisioning = True
    blob = foundation.lock_blob(plan["hub_resource_group_id"])
    remote = "private-transition/receipts/" + plan["plan_id"] + ".json"

    def save():
        _persist(path, state)

    try:
        if state["lease_state"] in ("proposed", "released"):
            # A proposed infinite lease may have been acquired before interruption.
            if recovery:
                try:
                    runtime.blob("PUT", blob, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": state["lease_id"]},
                                 query="?comp=lease")
                except enrollment.EnrollmentError as error:
                    require(error.code in ("remote-request-failed-409", "remote-request-failed-412"),
                            "hub-lease-acquisition-uncertain")
                    runtime.blob("PUT", blob, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                                 "x-ms-proposed-lease-id": state["lease_id"]}, query="?comp=lease", allowed=(201,))
            else:
                runtime.blob("PUT", blob, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                             "x-ms-proposed-lease-id": state["lease_id"]}, query="?comp=lease", allowed=(201,))
            state["lease_state"] = "acquired"
            save()
        # A close operation may have removed the controller's network path. Poll
        # its authenticated ARM result before attempting any local Blob request.
        pending_close = state.get("close_request")
        if pending_close:
            writer = plan["writers"][pending_close["writer_id"]]
            try:
                result = runtime.run_probe(writer, pending_close, _probe_bytes(source_root), resume=True)
            except TransitionError as error:
                # Only an independently observed terminal failed operation can
                # be retried; a timeout/unknown operation remains uncertain.
                require(error.code == "runner-probe-failed", "close-operation-still-uncertain")
                result = _retry_close(plan, state, runtime, source_root, save)
                pending_close = state["close_request"]
            _verify_result(result, pending_close, historical=True)
            attestation = runtime.attest_writer(writer, plan["source"]["probe_sha256"])
            require(attestation == plan["writer_attestations"][pending_close["writer_id"]],
                    "recovery-runner-attestation-changed")
            pe = _read(runtime, plan["private_endpoint_id"], NETWORK_API)["value"]
            require(_private_ip(runtime, pe, plan["coordination"]["account_id"],
                                plan["context"]["private_endpoint_subnet_id"].lower()) == pending_close["private_ip"],
                    "recovery-private-endpoint-changed")
            request = _request(plan, pending_close["writer_id"], writer, attestation,
                               pending_close["private_ip"], runtime)
            request.update(phase="verify-closed", account_id=plan["coordination"]["account_id"],
                           desired_network=plan["desired_network"],
                           expected_account_snapshot=pending_close["expected_account_snapshot"])
            result = runtime.run_probe(writer, request, _probe_bytes(source_root))
            _verify_result(result, request)
            state.update(status="succeeded", runtime_ready=True, lease_state="released", final_probe=result)
            _outputs(plan, state, pending_close["private_ip"])
            save()
            return state
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": state["lease_id"]},
                     query="?comp=lease")
        if plan["registries"][REGISTRY]["value"] != plan["desired_registry"]:
            status, headers, value = runtime.blob("GET", REGISTRY, allowed=(200, 404))
            observed = {"value": value if status == 200 else None,
                        "etag": _etag(headers, value) if status == 200 else None}
            if state["registry_publication"] in ("pending", "published") and value == plan["desired_registry"]:
                state["registry_snapshot"] = observed
            else:
                require(observed == plan["registries"][REGISTRY], "private-writer-registry-changed")
                state["registry_publication"] = "pending"
                save()
                condition = {"If-Match": observed["etag"]} if observed["etag"] else {"If-None-Match": "*"}
                runtime.blob("PUT", REGISTRY, data=plan["desired_registry"],
                             headers={"x-ms-blob-type": "BlockBlob", **condition}, allowed=(201,))
                state["registry_snapshot"] = _blob(runtime, REGISTRY)
                require(state["registry_snapshot"]["value"] == plan["desired_registry"],
                        "private-writer-registry-publication-unverified")
            state["registry_publication"] = "published"
            save()
        for name, expected in plan["registries"].items():
            if name == REGISTRY and state["registry_snapshot"]:
                expected = state["registry_snapshot"]
            lease = state["registry_leases"][name]
            if lease["state"] in ("proposed", "released"):
                if recovery:
                    try:
                        runtime.blob("PUT", name, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease["id"]},
                                     query="?comp=lease")
                    except enrollment.EnrollmentError as error:
                        require(error.code in ("remote-request-failed-409", "remote-request-failed-412"),
                                "registry-lease-acquisition-uncertain")
                        runtime.blob("PUT", name, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                                     "x-ms-proposed-lease-id": lease["id"]}, query="?comp=lease", allowed=(201,))
                else:
                    runtime.blob("PUT", name, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                                 "x-ms-proposed-lease-id": lease["id"]}, query="?comp=lease", allowed=(201,))
                lease["state"] = "acquired"
                save()
            else:
                runtime.blob("PUT", name, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease["id"]},
                             query="?comp=lease")
            require(_blob(runtime, name) == expected, "writer-registry-changed-under-hub-lease")
        _reconcile_observations(plan, state, runtime, save)
        save()
        account = _read(runtime, plan["coordination"]["account_id"], enrollment.STORAGE_API)
        _account(account["value"], plan["hub_resource_group_id"])
        require(all(account["value"]["properties"].get(k) == v for k, v in plan["expected_network"].items()),
                "account-network-changed-under-hub-lease")
        for effect in plan["effects"]:
            actual = _read(runtime, effect["id"], effect["api"])
            if actual["value"] is not None:
                journaled = state["resource_journal"].get(effect["id"])
                require(journaled and journaled["effect_hash"] == digest(effect)
                        and journaled["state"] in ("submitted", "completed"),
                        "resource-appeared-after-review")
                if effect["id"] == plan["private_endpoint_id"]:
                    _endpoint(actual["value"], plan["coordination"]["account_id"],
                              plan["context"]["private_endpoint_subnet_id"].lower())
                else:
                    require(_contains(actual["value"], effect["body"]), "created-resource-proof-mismatch")
            else:
                require(effect["id"] not in state["completed"], "completed-private-resource-disappeared")
                if effect["id"].endswith("/privatednszonegroups/default"):
                    pe = _read(runtime, plan["private_endpoint_id"], NETWORK_API)["value"]
                    ip = _private_ip(runtime, pe, plan["coordination"]["account_id"],
                                     plan["context"]["private_endpoint_subnet_id"].lower())
                    existing = _read(runtime, plan["record_id"], DNS_API)["value"]
                    require(not existing,
                            "shared-dns-record-would-be-overwritten")
                    require(_read(runtime, plan["record_id"].replace("/a/", "/cname/"), DNS_API)["value"] is None,
                            "shared-dns-cname-would-conflict")
                state["pending"] = effect["id"]
                state["resource_journal"][effect["id"]] = {"state": "submitted", "effect_hash": digest(effect)}
                save()
                runtime.arm("PUT", effect["id"], effect["api"], data=effect["body"],
                            headers={"If-None-Match": "*"}, allowed=(200, 201, 202))
                foundation._wait(runtime, effect["id"], effect["api"], time.sleep)
            if effect["id"] not in state["completed"]:
                state["completed"].append(effect["id"])
            state["resource_journal"][effect["id"]] = {"state": "completed", "effect_hash": digest(effect)}
            state["pending"] = None
            save()
            if (effect["id"] == plan["private_endpoint_id"]
                    or "/virtualnetworklinks/" in effect["id"] or "/privatednszonegroups/" in effect["id"]):
                _reconcile_observations(plan, state, runtime, save)
                save()
        pe = _read(runtime, plan["private_endpoint_id"], NETWORK_API)["value"]
        ip = _private_ip(runtime, pe, plan["coordination"]["account_id"], plan["context"]["private_endpoint_subnet_id"].lower())
        record = _read(runtime, plan["record_id"], DNS_API)["value"]
        require(record and record["properties"].get("aRecords") == [{"ipv4Address": ip}], "private-dns-record-not-ready")
        _reconcile_observations(plan, state, runtime, save)
        save()
        account = _read(runtime, plan["coordination"]["account_id"], enrollment.STORAGE_API)
        _account(account["value"], plan["hub_resource_group_id"])
        require(all(account["value"]["properties"].get(k) == v for k, v in plan["expected_network"].items()),
                "account-network-changed-during-provisioning")
        proofs = []
        for name, writer in sorted(plan["writers"].items()):
            attestation = runtime.attest_writer(writer, plan["source"]["probe_sha256"])
            require(attestation == plan["writer_attestations"][name], "private-runner-attestation-changed")
            request = _request(plan, name, writer, attestation, ip, runtime)
            state["probes"][name] = {"request": request, "status": "pending"}
            save()
            result = runtime.run_probe(writer, request, _probe_bytes(source_root))
            _verify_result(result, request)
            proof = {"attestation": result, "expires_at": request["expires_at"]}
            proof_blob = "private-transition/attestations/" + request["nonce"] + ".json"
            proofs.append({"blob": proof_blob, "hash": digest(proof)})
            state["probes"][name].update(status="verified", result=result)
            save()
        if plan["stage"] == "hub-private-probe":
            runtime.blob("PUT", remote, data={"status": "private-path-verified-public-bootstrap-retained",
                         "plan_hash": plan["plan_hash"], "writer_proofs": proofs, "private_ip": ip},
                         headers={"x-ms-blob-type": "BlockBlob"}, allowed=(201,))
            for name, lease in state["registry_leases"].items():
                runtime.blob("PUT", name, headers={"x-ms-lease-action": "release", "x-ms-lease-id": lease["id"]},
                             query="?comp=lease")
                lease["state"] = "released"
                save()
            runtime.blob("PUT", blob, headers={"x-ms-lease-action": "release", "x-ms-lease-id": state["lease_id"]},
                         query="?comp=lease")
            state.update(status="succeeded", runtime_ready=True, lease_state="released",
                         private_path_verified=True, public_bootstrap_retained=True,
                         private_transition_required=plan["expected_network"]["publicNetworkAccess"] != "Disabled")
            _outputs(plan, state, ip)
            save()
            return state
        name = plan["context"]["closure_writer_id"]
        writer = plan["writers"][name]
        request = _request(plan, name, writer, plan["writer_attestations"][name], ip, runtime)
        request.update(phase="close", expected_network=plan["expected_network"], desired_network=plan["desired_network"],
                       account_id=plan["coordination"]["account_id"], expected_account_snapshot=_account_snapshot(account["value"]),
                       lock_blob=blob, lease_id=state["lease_id"], remote_receipt=remote, writer_proofs=proofs,
                       registry_leases={key: value["id"] for key, value in state["registry_leases"].items()},
                       registry_hashes={COORDINATION: digest(plan["registries"][COORDINATION]["value"]),
                                        REGISTRY: digest(plan["desired_registry"])})
        state["close_request"] = request
        save()
        result = runtime.run_probe(writer, request, _probe_bytes(source_root))
        _verify_result(result, request)
        state.update(status="succeeded", runtime_ready=True, lease_state="released", final_probe=result,
                     public_network_access=plan["desired_network"]["publicNetworkAccess"],
                     bootstrap_rule_removed=plan["expected_network"] != plan["desired_network"])
        _outputs(plan, state, ip)
        save()
        return state
    except BaseException as error:
        state.update(status="uncertain", runtime_ready=False, error=getattr(error, "code", "private-transition-interrupted"))
        save()
        if not isinstance(error, Exception):
            raise
        return state
    finally:
        runtime.read_only = True
        runtime.serialized_provisioning = False


def _request(plan, name, writer, attestation, ip, runtime):
    _authorized(plan)
    vm = _read(runtime, writer["vm_id"].lower(), COMPUTE_API)["value"]
    require(vm and vm.get("properties", {}).get("provisioningState") == "Succeeded"
            and _vm_snapshot(vm) == attestation["vm_snapshot"], "runner-vm-configuration-changed")
    _authorized(plan)
    nonce = str(uuid4())
    request = {k: writer[k] for k in ("repository", "runner_id", "runner_name", "runner_config_path",
                                     "tenant_id", "principal_id", "source_commit", "provider")}
    request.update(writer_id=name, plan_hash=plan["plan_hash"], nonce=nonce, private_ip=ip,
                   account_url=plan["coordination"]["account_url"], source_sha256=plan["source"]["probe_sha256"],
                   operation_id=writer["vm_id"].lower() + "/runcommands/afhub-" + nonce,
                   issued_at=time.time(), expires_at=plan["expires_at"], phase="probe",
                   runner_os=attestation["os"], vm_location=vm["location"])
    request["vm_snapshot_sha256"] = digest(attestation["vm_snapshot"])
    if writer.get("client_id"):
        request["client_id"] = writer["client_id"]
    if writer["provider"] == "ado":
        request["pool_id"] = writer["pool_id"]
        request["organization_url"] = "https://dev.azure.com/" + urlsplit(writer["repository"]).path.strip("/").split("/")[0]
    return request


def _outputs(plan, state, ip):
    values = {"hub_private_access": {"stage": plan["stage"], "account_id": plan["coordination"]["account_id"],
        "private_endpoint_id": plan["private_endpoint_id"], "private_ip": ip,
        "private_endpoint_subnet_id": plan["context"]["private_endpoint_subnet_id"].lower(),
        "private_endpoint_vnet_id": plan["context"]["private_endpoint_subnet_id"].lower().rsplit("/subnets/", 1)[0],
        "hub_resource_group_id": plan["hub_resource_group_id"],
        "writer_ids": sorted(plan["writers"]), "private_path_verified": True,
        "public_network_access": plan["desired_network"]["publicNetworkAccess"],
        "private_transition_complete": plan["stage"] == "hub-private-transition"}}
    state["outputs"] = values
    state["bindings"] = copy.deepcopy(values)


def _retry_close(plan, state, runtime, source_root, save):
    pe = _read(runtime, plan["private_endpoint_id"], NETWORK_API)["value"]
    ip = _private_ip(runtime, pe, plan["coordination"]["account_id"],
                     plan["context"]["private_endpoint_subnet_id"].lower())
    account = _read(runtime, plan["coordination"]["account_id"], enrollment.STORAGE_API)
    _account(account["value"], plan["hub_resource_group_id"])
    current = {k: account["value"]["properties"].get(k) for k in ("networkAcls", "publicNetworkAccess")}
    require(current in (plan["expected_network"], plan["desired_network"]), "recovery-account-network-drift")
    expected_account = copy.deepcopy(state["close_request"]["expected_account_snapshot"])
    expected_account["properties"].update(current)
    require(_account_snapshot(account["value"]) == expected_account, "recovery-account-snapshot-drift")
    proofs = []
    for name, writer in sorted(plan["writers"].items()):
        attestation = runtime.attest_writer(writer, plan["source"]["probe_sha256"])
        require(attestation == plan["writer_attestations"][name], "recovery-writer-identity-changed")
        request = _request(plan, name, writer, attestation, ip, runtime)
        state["probes"][name] = {"request": request, "status": "pending"}
        save()
        result = runtime.run_probe(writer, request, _probe_bytes(source_root))
        _verify_result(result, request)
        proof = {"attestation": result, "expires_at": request["expires_at"]}
        proofs.append({"blob": "private-transition/attestations/" + request["nonce"] + ".json", "hash": digest(proof)})
        state["probes"][name].update(status="verified", result=result)
        save()
    previous = state["close_request"]
    writer = plan["writers"][previous["writer_id"]]
    request = _request(plan, previous["writer_id"], writer, plan["writer_attestations"][previous["writer_id"]], ip, runtime)
    for key in ("phase", "expected_network", "desired_network", "account_id", "lock_blob",
                "lease_id", "remote_receipt", "registry_hashes", "registry_leases"):
        request[key] = previous[key]
    request.update(expected_account_snapshot=previous["expected_account_snapshot"], writer_proofs=proofs)
    state.setdefault("previous_close_operations", []).append(previous["operation_id"])
    state["close_request"] = request
    save()
    result = runtime.run_probe(writer, request, _probe_bytes(source_root))
    _verify_result(result, request)
    return result


def execute(plan, *, source_root, expected_plan_hash, state_dir, runtime=None):
    require(plan.get("stage") == "hub-private-transition", "final-private-transition-plan-required")
    return _run(plan, source_root=source_root, expected_plan_hash=expected_plan_hash,
                state_dir=state_dir, runtime=runtime, recovery=False)


def recover(plan, *, source_root, expected_plan_hash, state_dir, runtime=None):
    return _run(plan, source_root=source_root, expected_plan_hash=expected_plan_hash,
                state_dir=state_dir, runtime=runtime, recovery=True)


def prepare_probe(*, source_root, tenant_id, hub_resource_group_id, context, expected_source_hash=None, runtime=None):
    return prepare(source_root=source_root, tenant_id=tenant_id, hub_resource_group_id=hub_resource_group_id,
                   context=context, expected_source_hash=expected_source_hash, runtime=runtime, phase="probe")


def execute_probe(plan, *, source_root, expected_plan_hash, state_dir, runtime=None):
    require(plan.get("stage") == "hub-private-probe", "private-probe-plan-required")
    return _run(plan, source_root=source_root, expected_plan_hash=expected_plan_hash,
                state_dir=state_dir, runtime=runtime, recovery=False)


class _WorkflowAdapter:
    """Concrete coordinator bridge; constructor receives the verified source root."""

    phase = None

    def __init__(self, *, source_root, state_dir, command_runner=None, expected_source_hash=None, runtime_factory=None):
        self.source_root = foundation.ordinary(source_root)
        self.state_dir = foundation.ordinary(state_dir)
        self.command_runner = command_runner
        self.expected_source_hash = expected_source_hash or source_fingerprint(self.source_root)["payload_sha256"]
        self.runtime_factory = runtime_factory

    def _runtime(self, target, coordinates):
        if self.runtime_factory is not None:
            return self.runtime_factory(target, coordinates)
        return Cloud(target, coordinates, command_runner=self.command_runner)

    def prepare(self, *, root, scope, bootstrap_config, expected_revision, workflow_id,
                coordination=None, bindings=None, provider_serialization=None):
        try:
            require(isinstance(scope, dict) and isinstance(bootstrap_config, dict)
                    and (bindings is None or isinstance(bindings, dict)), "workflow-scope-profile-bindings-required")
            source = verify_source_snapshot(source_root=self.source_root, expected_payload_sha256=self.expected_source_hash)
            bindings = copy.deepcopy(bindings or {})
            require(isinstance(coordination, dict) and isinstance(coordination.get("account_id"), str),
                    "hub-coordination-bindings-required")
            account = _id(coordination["account_id"], "microsoft.storage/storageaccounts")
            hub = enrollment.rg_id(account.split("/providers/", 1)[0])
            coordinates = foundation.coordination(hub)
            require(all(coordination.get(k) == v for k, v in coordinates.items()), "hub-coordination-bindings-conflict")
            tenant = enrollment.guid(bootstrap_config.get("tenant_id") or bindings.get("tenant_id"))
            runtime = self._runtime({"tenant_id": tenant, "subscription_id": hub.split("/")[2]}, coordinates)
            runtime.read_only = True
            enrolled = _blob(runtime, COORDINATION)["value"]
            selected_principal = enrollment.guid(bindings["deployment_principal_id"])
            selected_ids = {writer_id for record in enrolled.get("scopes", {}).values()
                            if record.get("target", {}).get("factory_id") == scope.get("factory_id")
                            for writer_id in record.get("writers", [])}
            require(selected_ids, "selected-factory-enrollment-required")
            candidates = [(name, writer) for name, writer in enrolled.get("writers", {}).items()
                          if name in selected_ids and writer.get("deployment_object_id") == selected_principal]
            repository = (provider_serialization or {}).get("repository")
            if repository:
                normalize = lambda value: value.lower().removeprefix("https://github.com/").removesuffix(".git").rstrip("/")
                candidates = [(name, writer) for name, writer in candidates
                              if normalize(writer["repository"]) == normalize(repository)]
            require(len(candidates) == 1, "selected-factory-writer-ambiguous")
            writer_id, writer = candidates[0]
            require(bindings.get("hub_private_endpoint_subnet_id"), "hub-private-endpoint-subnet-binding-required")
            subnet = _id(bindings["hub_private_endpoint_subnet_id"], "microsoft.network/virtualnetworks/subnets")
            network = bindings.get("network")
            require(isinstance(network, dict) and network.get("owned") is False,
                    "retained-shared-hub-network-bindings-required")
            require(network.get("mode") == "external"
                    and bootstrap_config.get("access_hub_mode", "external") == "external",
                    "integrated-shared-private-endpoint-retention-contract-required")
            hub_vnet = _id(network.get("vnet_id"), "microsoft.network/virtualnetworks")
            require(enrollment.rg_id(network.get("resource_group_id")) == hub
                    and hub_vnet.split("/providers/", 1)[0] == hub
                    and subnet.rsplit("/subnets/", 1)[0] == hub_vnet,
                    "private-endpoint-subnet-must-be-in-retained-connectivity-hub")
            runner_subnet = _id(bindings["runner_subnet_id"], "microsoft.network/virtualnetworks/subnets")
            vnets = {hub_vnet, runner_subnet.rsplit("/subnets/", 1)[0]}
            for vnet in (bindings.get("integrated_vnet_id"),):
                if vnet:
                    vnets.add(_id(vnet, "microsoft.network/virtualnetworks"))
            discovered = runtime.discover_writer_target(writer, bindings, tenant, source)
            status, _, registry = runtime.blob("GET", REGISTRY, allowed=(200, 404))
            prior_target = registry.get("writers", {}).get(writer_id, {}) if status == 200 else {}
            context = {"private_endpoint_subnet_id": subnet,
                "dns_zone_id": bindings.get("hub_blob_dns_zone_id") or hub + "/providers/microsoft.network/privatednszones/privatelink.blob.core.windows.net",
                "dns_vnet_ids": sorted(vnets), "closure_writer_id": writer_id,
                "writer_targets": {writer_id: {**prior_target, **discovered}}}
            if bindings.get("hub_foundation_receipt"):
                context["foundation_receipt"] = bindings["hub_foundation_receipt"]
            frozen = prepare(source_root=self.source_root, tenant_id=tenant, hub_resource_group_id=hub,
                             context=context, expected_source_hash=self.expected_source_hash, runtime=runtime, phase=self.phase)
            frozen["workflow_binding"] = {"root": str(foundation.ordinary(root)), "scope": copy.deepcopy(scope),
                "expected_revision": expected_revision, "workflow_id": workflow_id,
                "provider_serialization": copy.deepcopy(provider_serialization)}
            frozen["plan_hash"] = digest({k: v for k, v in frozen.items() if k != "plan_hash"})
            return {**{k: copy.deepcopy(frozen[k]) for k in ("can_execute", "effects", "blockers", "commands", "auth_scopes")},
                    "plan_hash": frozen["plan_hash"], "frozen_plan": frozen}
        except (TransitionError, enrollment.EnrollmentError, foundation.FoundationError, KeyError, TypeError) as error:
            return {"can_execute": False, "effects": [], "blockers": [
                getattr(error, "code", "private-access-stage-bindings-incomplete")], "commands": [],
                "auth_scopes": [], "frozen_plan": None}

    def execute(self, prepared, *, root, workflow_id):
        require(prepared.get("can_execute") is True and isinstance(prepared.get("frozen_plan"), dict),
                "private-access-stage-blocked")
        frozen = prepared["frozen_plan"]
        binding = frozen.get("workflow_binding", {})
        require(binding.get("root") == str(foundation.ordinary(root)) and binding.get("workflow_id") == workflow_id,
                "private-access-workflow-binding-changed")
        require(frozen["stage"] == "hub-private-" + self.phase, "private-access-workflow-phase-conflict")
        folder = foundation.ordinary(self.state_dir / digest({"root": binding["root"], "workflow_id": workflow_id}))
        folder.mkdir(parents=True, exist_ok=True)
        state_path = foundation.ordinary(folder / ("private-transition-" + frozen["plan_id"] + ".json"))
        runtime = self._runtime(frozen["target"], frozen["coordination"])
        call = recover if state_path.exists() else execute_probe if self.phase == "probe" else execute
        return call(frozen, source_root=self.source_root, expected_plan_hash=prepared["plan_hash"],
                    state_dir=folder, runtime=runtime)


class PrivateProbeAdapter(_WorkflowAdapter):
    phase = "probe"


class PrivateTransitionAdapter(_WorkflowAdapter):
    phase = "transition"
