"""Reviewed privileged prerequisites for registered (v125+) factories.

This module does not enroll external networks as factory-owned resources, publish
repositories, change the register, or invoke the legacy bootstrap launcher.
Identity/federation enrollment and common/project deployment remain separately
reviewed stages. New shared hubs use the retained standard Blob foundation in
``hub_lock_foundation``; explicitly supplied legacy factory-common ADLS coordinates
remain compatible without migration. This after-common stage never invents storage.

prepare(...) performs discovery only. execute(...) consumes its exact plan once,
under physical-resource leases or explicit manual single-writer governance, and
persists results before returning. An interruption retains any infinite leases
and an uncertain receipt: automatic retry is deliberately unsupported.
Newly generated Entra IDs require downstream review.
Existing gateway route additions require explicit manual single-writer governance:
GET/ETag comparison is not atomic, and no provider-enforced If-Match is claimed.
Blob-coordinated route updates remain blocked without that provider guarantee.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request
from uuid import uuid4, uuid5, NAMESPACE_URL

import aifactory_private_dns
import factory_enrollment as enrollment
import hub_lock_foundation
import release_version


CONTRACT_VERSION = 1
NETWORK_API = "2024-05-01"
DNS_API = "2022-07-01"
GATEWAY_ROUTE_APPEND_LIMITATION = "gateway-route-append-strong-if-match-unverified"
# VirtualNetworkGateways_CreateOrUpdate has no documented If-Match precondition;
# UpdateTags (PATCH) cannot update routes. An ETag alone is not a CAS guarantee.
GATEWAY_API_CONTRACT = (
    "https://github.com/Azure/azure-rest-api-specs/blob/main/specification/network/"
    "resource-manager/Microsoft.Network/Network/stable/2024-05-01/virtualNetworkGateway.json"
)
GATEWAY_MANUAL_WRITER_WARNING = (
    "MANUAL SINGLE-WRITER ONLY: You must serialize ALL shared-hub writers, including other "
    "factories, repositories, pipelines, portal and CLI users, from review through completion "
    "and reconciliation of any uncertain result. The initializer repository reservation does "
    "not lock the shared hub. The gateway PUT has no verified provider-enforced If-Match; "
    "the final GET/ETag comparison is not atomic. No Blob lock or distributed guarantee is "
    "provided. Do not retry an uncertain write; reconcile the durable receipt first."
)
GATEWAY_RESPONSE_EXTENSIONS = (
    "packetCaptureDiagnosticState", "isMigrateToCSES", "isMigratedLegacySKU",
    "blockUpgradeOfMigratedLegacyGateways", "remoteVirtualNetworkPeerings", "vpnStack",
)
GATEWAY_RESPONSE_EXTENSION_WARNING = (
    "This gateway exposes service extensions absent from the published request model. "
    "The explicitly recognised, type-checked extension values are retained unchanged in "
    "the PUT, not assumed read-only or silently discarded. Provider acceptance is not "
    "live-verified; active capture or migration is blocked."
)
GRAPH = "https://graph.microsoft.com/"
SOURCE_FILES = (
    "bootstrap/lib/registered_prerequisites.py",
    "bootstrap/lib/factory_enrollment.py",
    "bootstrap/lib/aifactory_private_dns.py",
    "bootstrap/lib/release_version.py",
    "bootstrap/lib/hub_lock_foundation.py",
)
CONTEXT_KEYS = {
    "coordination", "seeding_keyvault_id", "owned_resource_group_ids", "reuse_deployment_identity",
    "project_resource_group_id",
    "integrated_vnet_id", "integrated_vnet_cidr", "location_short",
    "deployment_identity_id", "deployment_principal_id", "source_payload_sha256",
    "coordination_mode", "hub_resource_group_id", "provider_serialization", "bootstrap_phase",
}
CONFIG_KEYS = {
    "tenant_id", "subscription_id", "location", "factory_prefix", "team_group_name",
    "team_group_id", "team_member_email", "access_hub_mode", "setup_hub_access",
    "access_hub_subscription_id", "access_hub_resource_group", "access_hub_vnet_name",
    "access_hub_vnet_cidr", "vpn_client_cidr", "dev_vnet_cidr",
    "first_party_apps", "resource_providers", "coordination_mode",
}
FIRST_PARTY_APPS = {"azure-machine-learning": "0736f41a-0425-4b46-bdb5-1563eff02385",
                    "databricks": "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"}
canonical = enrollment.canonical
digest = enrollment.digest


class PrerequisiteError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise PrerequisiteError(code)


def ordinary(value):
    path = Path(os.path.abspath(value))
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                    for p in (path, *path.parents)), "linked-path-forbidden")
    require(not path.is_file() or path.stat().st_nlink == 1, "hardlinked-file-forbidden")
    return path


def source_fingerprint(source_root):
    """Hash actual reviewed bytes, including unpublished additions; never label them published."""
    root = ordinary(source_root)
    files = {}
    for relative in SOURCE_FILES:
        path = ordinary(root / relative)
        require(path.is_file(), "privileged-source-file-missing:" + relative)
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"kind": "reviewed-local-payload", "root": str(root),
            "published_ref_verified": False, "verification": "exact-local-file-bytes-only",
            "files": files, "payload_sha256": digest(files)}


def _verify_loaded_source(source):
    loaded = (__file__, enrollment.__file__, aifactory_private_dns.__file__, release_version.__file__,
              hub_lock_foundation.__file__)
    require(all(hashlib.sha256(ordinary(path).read_bytes()).hexdigest() == source["files"][relative]
                for relative, path in zip(SOURCE_FILES, loaded)),
            "loaded-prerequisite-code-differs-from-reviewed-source")


def verify_source_snapshot(*, source_root, expected_payload_sha256):
    """Resolve an explicitly pinned local helper bundle; never resolve or claim Git main."""
    source = source_fingerprint(source_root)
    require(source["payload_sha256"] == expected_payload_sha256, "reviewed-source-payload-required")
    _verify_loaded_source(source)
    return source


def _resource(value, kind):
    try:
        return enrollment.resource_id(value, kind)
    except enrollment.EnrollmentError:
        raise PrerequisiteError("invalid-resource-id:" + kind) from None


def _rg(value):
    try:
        return enrollment.rg_id(value)
    except enrollment.EnrollmentError:
        raise PrerequisiteError("invalid-resource-group-id") from None


def _guid(value):
    try:
        return enrollment.guid(value)
    except enrollment.EnrollmentError:
        raise PrerequisiteError("invalid-guid") from None


def _network(value, name):
    try:
        network = ipaddress.ip_network(value, strict=True)
    except (ValueError, TypeError):
        raise PrerequisiteError("invalid-cidr:" + name) from None
    require(network.version == 4, "ipv4-required:" + name)
    return network


def _contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(actual[k], v)
                                                for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _contains(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, str) and expected.startswith("/subscriptions/"):
        return isinstance(actual, str) and actual.lower() == expected.lower()
    return actual == expected


def _read_target(root, scope):
    require(isinstance(scope, dict) and set(scope) <= {"folder", "factory_id", "scale_set_id", "project_id", "environment"}
            and {"factory_id", "scale_set_id"} <= set(scope), "exact-registered-scope-required")
    require(scope.get("environment", "dev") == "dev", "initial-dev-environment-required")
    path = ordinary(root / "azurefactory" / "register.json")
    require(path.is_file() and path.stat().st_size <= enrollment.MAX_BYTES, "consumer-register-required")
    raw = path.read_bytes()
    document = enrollment.parse_json(raw)
    require(document.get("schema_version") == 2, "consumer-schema-2-required")
    factories = [x for x in document.get("factories", []) if x.get("id") == _guid(scope["factory_id"])]
    require(len(factories) == 1, "exact-registered-factory-required")
    factory = factories[0]
    try:
        version = release_version.normalize(factory.get("aifactory_version"))
        modern = version == "main" or tuple(map(int, release_version.branch_for(version).removeprefix("release/v").split("."))) >= (1, 25)
    except (ValueError, TypeError, AttributeError):
        modern = False
    require(modern, "registered-prerequisites-require-main-or-v125-plus")
    scales = [x for x in factory.get("scale_sets", []) if x.get("id") == _guid(scope["scale_set_id"])]
    require(len(scales) == 1, "exact-registered-scaleset-required")
    scale = scales[0]
    require(scale.get("environment") == "dev" and factory.get("kind", "ai") == "ai",
            "initial-ai-dev-scaleset-required")
    if scope.get("folder"):
        require(ordinary(scope["folder"]) in (root, root / "azurefactory"), "scope-folder-mismatch")
    if scope.get("project_id"):
        projects = [x for x in factory.get("projects", []) if x.get("id") == _guid(scope["project_id"])]
        require(len(projects) == 1 and {"environment": "dev", "scale_set_id": scale["id"]}
                in projects[0].get("placements", []), "exact-project-placement-required")
    project = {"project_id": projects[0]["id"], "project_number": projects[0]["number"]} if scope.get("project_id") else {}
    return {"factory_id": factory["id"], "scale_set_id": scale["id"], **project,
            "tenant_id": _guid(scale.get("tenant_id")), "subscription_id": _guid(scale.get("subscription_id")),
            "location": factory.get("region"), "prefix": factory.get("prefix"),
            "suffix": scale.get("suffix"), "aifactory_version": version}, hashlib.sha256(raw).hexdigest()


class Cloud(enrollment.Cloud):
    """Authenticated cached CLI credentials only; no login or subscription switch."""

    def __init__(self, target, coordinates, command_runner=None, opener=None):
        super().__init__({"target": target, "coordinates": coordinates}, command_runner, opener)

    def graph(self, method, path, body=None, allowed=(200,)):
        require(method in ("GET", "POST") and (not self.read_only or method == "GET"),
                "unreviewed-graph-write")
        require(path.startswith(("groups", "users/", "servicePrincipals")) and "://" not in path and ".." not in path,
                "untrusted-graph-endpoint")
        try:
            token = self.token(GRAPH)
        except enrollment.EnrollmentError as exc:
            raise PrerequisiteError("graph-" + exc.code) from None
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        try:
            response = self.opener.open(Request(GRAPH + "v1.0/" + path, method=method,
                                               data=canonical(body) if body is not None else None,
                                               headers=headers), timeout=90)
        except HTTPError as exc:
            response = exc
        except (URLError, OSError, TimeoutError):
            raise PrerequisiteError("graph-write-or-read-uncertain") from None
        with response:
            status = response.status
            raw = response.read(enrollment.MAX_BYTES + 1)
        require(status in allowed, f"graph-request-failed-{status}")
        require(len(raw) <= enrollment.MAX_BYTES, "graph-response-too-large")
        return enrollment.parse_json(raw) if raw else None

    def blob(self, method, blob, *, data=None, headers=None, allowed=(200,), query=""):
        coordinates = self.request_config["coordinates"]
        url = coordinates["account_url"] + "/" + coordinates["container"] + "/" + quote(blob, safe="/") + query
        return self.http(method, url, enrollment.STORAGE, data, headers, allowed=allowed)

    def verify_provider_serialization(self, proof):
        require(isinstance(proof, dict) and set(proof) == {"repository", "ref", "sha", "owner"},
                "exact-provider-serialization-required")
        require(re.fullmatch(r"https://(?:github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|dev\.azure\.com/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+/_git/[A-Za-z0-9_.%-]+)",
                             str(proof["repository"]))
                and proof["ref"] == "refs/heads/aifactory-initializer-lock"
                and re.fullmatch(r"[a-f0-9]{40}", str(proof["sha"])),
                "invalid-provider-serialization")
        _guid(proof["owner"])
        text = self.command(["git", "ls-remote", proof["repository"], proof["ref"]])
        require(text.strip() == proof["sha"] + "\t" + proof["ref"], "provider-initializer-lock-not-held")


class Builder:
    def __init__(self, runtime):
        self.runtime = runtime
        self.observations = []
        self.effects = []
        self.blockers = []

    def read(self, identifier, api):
        status, _, value = self.runtime.arm("GET", identifier, api, allowed=(200, 404))
        value = value if status == 200 else None
        if value is not None and "/virtualnetworkgateways/" in identifier.lower():
            value = _gateway_configuration(value)
        self.observations.append({"kind": "arm", "id": identifier, "api": api, "value": value})
        return value

    def collection(self, identifier, api):
        value = sorted(self.runtime.collection(identifier, api), key=lambda x: x["id"].lower())
        if identifier.lower().endswith("/virtualnetworkgateways"):
            value = [_gateway_configuration(gateway) for gateway in value]
        self.observations.append({"kind": "collection", "id": identifier, "api": api, "value": value})
        return value

    def graph(self, path):
        value = self.runtime.graph("GET", path)
        require(not isinstance(value, dict) or "@odata.nextLink" not in value,
                "graph-inventory-incomplete")
        self.observations.append({"kind": "graph", "id": path, "value": value})
        return value

    def ensure(self, identifier, api, body, *, ownership, existing=None, already_read=False):
        if not already_read:
            existing = self.read(identifier, api)
        if existing is None:
            self.effects.append({"kind": "arm-create", "id": identifier, "api": api,
                                 "body": body, "ownership": ownership})
        elif not _contains(existing, body):
            self.blockers.append("existing-resource-incompatible:" + identifier)
        elif existing.get("properties", {}).get("provisioningState", "Succeeded") != "Succeeded":
            self.blockers.append("existing-resource-not-ready:" + identifier)
        return existing


def _group(builder, config, target):
    member = builder.graph("users/" + quote(config["team_member_email"], safe="") + "?$select=id")
    member_id = _guid(member.get("id"))
    if config.get("team_group_id"):
        group_id = _guid(config["team_group_id"])
        group = builder.graph("groups/" + group_id + "?$select=id,displayName,securityEnabled,mailEnabled,isAssignableToRole,groupTypes")
    else:
        name = config["team_group_name"]
        rows = builder.graph("groups?$filter=" + quote("displayName eq '" + name.replace("'", "''") + "'", safe="")
                             + "&$select=id,displayName,securityEnabled,mailEnabled,isAssignableToRole,groupTypes").get("value", [])
        require(len(rows) <= 1, "ambiguous-entra-team-group")
        group = rows[0] if rows else None
        group_id = _guid(group["id"]) if group else None
    if group:
        require(group.get("securityEnabled") is True and group.get("mailEnabled") is False,
                "entra-team-group-must-be-nonmail-security-group")
        require(not group.get("isAssignableToRole") and "DynamicMembership" not in group.get("groupTypes", []),
                "entra-team-group-cannot-be-role-assignable-or-dynamic")
        members = builder.graph("groups/" + group_id + "/members?$select=id").get("value", [])
        if not any(x.get("id") == member_id for x in members):
            builder.effects.append({"kind": "group-member-add", "group_id": group_id, "member_id": member_id})
    else:
        builder.effects.append({"kind": "group-create", "body": {
            "displayName": config["team_group_name"], "mailEnabled": False, "securityEnabled": True,
            "mailNickname": "aif-" + digest(target)[:20],
            "description": "AI Factory " + target["factory_id"] + " DEV team",
            "members@odata.bind": [GRAPH + "v1.0/directoryObjects/" + member_id],
        }})
    return group_id


def _first_party_apps(builder, config):
    selected = config.get("first_party_apps", [])
    require(isinstance(selected, list) and len(selected) == len(set(selected))
            and set(selected) <= FIRST_PARTY_APPS.keys(), "unsupported-first-party-app")
    result = {}
    for name in sorted(selected):
        app = FIRST_PARTY_APPS[name]
        path = "servicePrincipals?$filter=" + quote("appId eq '" + app + "'", safe="") + "&$select=id,appId"
        rows = builder.graph(path).get("value", [])
        require(len(rows) <= 1, "ambiguous-first-party-app")
        if rows:
            require(rows[0].get("appId") == app, "first-party-app-id-conflict")
            result[name] = _guid(rows[0].get("id"))
        else:
            builder.effects.append({"kind": "first-party-app-create", "name": name, "body": {"appId": app}})
    return result


def _private_dns(builder, vnet, rg, context, target, ownership):
    zones = aifactory_private_dns.configuration(vnet.split("/")[2], rg.rsplit("/", 1)[1],
                                                target["location"], context["location_short"])["zones"]
    for zone in zones:
        zone_id = rg + "/providers/Microsoft.Network/privateDnsZones/" + zone["name"]
        existing = builder.ensure(zone_id, "2020-06-01", {"location": "global"}, ownership=ownership)
        links = builder.collection(zone_id + "/virtualNetworkLinks", "2020-06-01") if existing else []
        targets = [vnet]
        if context.get("integrated_vnet_id"):
            common = _resource(context["integrated_vnet_id"], "Microsoft.Network/virtualNetworks")
            if common != vnet:
                targets.append(common)
        for target_vnet in targets:
            matches = [link for link in links
                       if link.get("properties", {}).get("virtualNetwork", {}).get("id", "").lower() == target_vnet]
            require(len(matches) <= 1, "ambiguous-private-dns-vnet-link:" + zone_id)
            body = {"location": "global", "properties": {"registrationEnabled": False,
                    "virtualNetwork": {"id": target_vnet}}}
            if matches:
                if not _contains(matches[0], body):
                    builder.blockers.append("existing-private-dns-link-incompatible:" + matches[0]["id"])
            else:
                builder.ensure(zone_id + "/virtualNetworkLinks/aif-" + digest(target_vnet)[:12],
                               "2020-06-01", body, ownership=ownership)


def _providers(builder, target, config, context):
    scopes = []
    selections = {(target["subscription_id"], "Microsoft.KeyVault")}
    requested = config.get("resource_providers", [])
    require(isinstance(requested, list) and len(requested) <= 50
            and all(isinstance(item, str) and re.fullmatch(r"Microsoft\.[A-Za-z][A-Za-z0-9]{0,70}", item)
                    for item in requested), "invalid-reviewed-resource-providers")
    selections.update((target["subscription_id"], namespace) for namespace in requested)
    if context.get("bootstrap_phase") == "minimum-foundation":
        selections.update((target["subscription_id"], namespace) for namespace in
                          ("Microsoft.Network", "Microsoft.ManagedIdentity", "Microsoft.Compute"))
    if context.get("deployment_identity_id"):
        selections.add((target["subscription_id"], "Microsoft.Authorization"))
    if config["access_hub_mode"] == "external" or config["setup_hub_access"]:
        selections.add((target["subscription_id"], "Microsoft.Network"))
    if config["access_hub_mode"] == "external":
        selections.add((_guid(config.get("access_hub_subscription_id")), "Microsoft.Network"))
    for subscription, namespace in sorted(selections):
        identifier = f"/subscriptions/{subscription}/providers/{namespace}"
        value = builder.read(identifier, "2021-04-01")
        state = (value or {}).get("registrationState")
        if state == "Registered":
            continue
        if state != "NotRegistered":
            builder.blockers.append("resource-provider-state-unavailable-or-transitioning:" + identifier)
        else:
            builder.effects.append({"kind": "provider-register", "id": identifier, "api": "2021-04-01",
                                    "ownership": "subscription-provider-registration-not-factory-ownership"})
            scopes.append(identifier.lower())
    return scopes


def _bastion(builder, context, target, owned, bindings):
    vnet = _resource(context.get("integrated_vnet_id"), "Microsoft.Network/virtualNetworks")
    rg = _rg(vnet.split("/providers/")[0])
    require(rg in owned, "bastion-must-use-owned-common-vnet")
    existing_vnet = builder.read(vnet, NETWORK_API)
    if existing_vnet is None:
        builder.blockers.append("bastion-access-requires-common-network-first:" + vnet)
    bastions = builder.collection(f"/subscriptions/{target['subscription_id']}/providers/Microsoft.Network/bastionHosts",
                                   NETWORK_API)
    matching = [value for value in bastions
                if value.get("properties", {}).get("virtualNetwork", {}).get("id", "").lower() == vnet
                or any(ip.get("properties", {}).get("subnet", {}).get("id", "").lower().startswith(vnet + "/subnets/")
                       for ip in value.get("properties", {}).get("ipConfigurations", []))]
    require(len(matching) <= 1, "multiple-bastions-bound-to-common-vnet")
    if matching:
        bastion = matching[0]
        if bastion.get("properties", {}).get("provisioningState") != "Succeeded":
            builder.blockers.append("existing-bastion-not-ready:" + bastion["id"])
        bindings["bastion"] = {"id": bastion["id"], "reused_unchanged": True}
    else:
        identifier = rg + "/providers/Microsoft.Network/bastionHosts/bastion-" + digest(vnet)[:12]
        builder.ensure(identifier, NETWORK_API, {"location": target["location"], "sku": {"name": "Developer"},
                       "properties": {"virtualNetwork": {"id": vnet}}}, ownership="factory-owned")
        bindings["bastion"] = {"id": identifier, "sku": "Developer", "paid_fallback": False}


def _peerings(builder, vnet, context, config, owned, bindings):
    common = _resource(context.get("integrated_vnet_id"), "Microsoft.Network/virtualNetworks")
    require(common.split("/providers/")[0] in owned and common != vnet, "exact-owned-common-vnet-required")
    existing = builder.read(common, NETWORK_API)
    if not existing:
        builder.blockers.append("external-peering-requires-common-network-first:" + common)
        return
    if config.get("dev_vnet_cidr", "172.16.0.0/18") not in existing.get("properties", {}).get("addressSpace", {}).get("addressPrefixes", []):
        builder.blockers.append("common-vnet-cidr-mismatch:" + common)
    pairs = []
    for local, remote, ownership, hub in (
        (vnet, common, "external-retain-never-enroll-or-delete", True),
        (common, vnet, "factory-owned", False),
    ):
        peers = builder.collection(local + "/virtualNetworkPeerings", NETWORK_API)
        matches = [peer for peer in peers if peer.get("properties", {}).get("remoteVirtualNetwork", {}).get("id", "").lower() == remote]
        require(len(matches) <= 1, "ambiguous-vnet-peering:" + local)
        properties = {"remoteVirtualNetwork": {"id": remote}, "allowVirtualNetworkAccess": True,
                      "allowForwardedTraffic": True, "allowGatewayTransit": bool(hub and config["setup_hub_access"]),
                      "useRemoteGateways": bool(not hub and config["setup_hub_access"])}
        if matches:
            peer = matches[0]
            if not _contains(peer.get("properties"), properties):
                builder.blockers.append("existing-peering-incompatible-review-exact-resource:" + peer["id"])
            pairs.append(peer["id"])
        else:
            identifier = local + "/virtualNetworkPeerings/aif-" + digest(remote)[:12]
            builder.ensure(identifier, NETWORK_API, {"properties": properties}, ownership=ownership)
            pairs.append(identifier)
    bindings["network"]["peering_ids"] = pairs


def _hub_private_endpoint_subnet(builder, vnet, cidr, existing_vnet, bindings, *, reserve_access_subnets):
    identifier = vnet + "/subnets/snet-aifactory-private-endpoints"
    subnets = [] if existing_vnet is None else existing_vnet.get("properties", {}).get("subnets")
    require(isinstance(subnets, list), "complete-hub-subnet-inventory-required")
    occupied = []
    matching = []
    for subnet in subnets:
        subnet_id = str(subnet.get("id", "")).lower()
        require(re.fullmatch(re.escape(vnet) + r"/subnets/[a-z0-9_.-]{1,80}", subnet_id),
                "hub-subnet-inventory-scope-mismatch")
        props = subnet.get("properties", {})
        prefixes = list(props.get("addressPrefixes", []))
        if props.get("addressPrefix"):
            prefixes.append(props["addressPrefix"])
        require(prefixes, "hub-subnet-address-prefix-required")
        networks = [_network(value, "hub-subnet-address-prefix") for value in prefixes]
        occupied.extend(networks)
        if subnet_id == identifier:
            matching.append(networks)
    require(len(matching) <= 1, "duplicate-hub-private-endpoint-subnet")
    existing = builder.read(identifier, NETWORK_API)
    require(bool(matching) == (existing is not None), "hub-private-endpoint-subnet-inventory-changed")
    if existing is not None:
        properties = existing.get("properties", {})
        require(properties.get("provisioningState") == "Succeeded"
                and not properties.get("delegations")
                and all(network.subnet_of(cidr) for network in matching[0]),
                "existing-hub-private-endpoint-subnet-incompatible")
        prefixes = list(properties.get("addressPrefixes", []))
        if properties.get("addressPrefix"):
            prefixes.append(properties["addressPrefix"])
        require({_network(value, "private-endpoint-subnet-prefix") for value in prefixes} == set(matching[0]),
                "hub-private-endpoint-subnet-inventory-changed")
    else:
        if reserve_access_subnets:
            occupied.extend((ipaddress.ip_network((int(cidr.broadcast_address) - 31, 27)),
                             ipaddress.ip_network((int(cidr.broadcast_address) - 47, 28))))
        selected = next((candidate for candidate in cidr.subnets(new_prefix=27)
                         if not any(candidate.overlaps(other) for other in occupied)), None)
        if selected is None:
            builder.blockers.append("approved-hub-address-space-has-no-private-endpoint-subnet-capacity:" + vnet)
            return
        builder.ensure(identifier, NETWORK_API, {"properties": {
            "addressPrefix": str(selected), "privateEndpointNetworkPolicies": "Disabled"}},
            ownership="external-retain-never-enroll-or-delete", already_read=True)
    bindings["hub_private_endpoint_subnet_id"] = identifier


def _gateway_routes(gateway):
    props = gateway.get("properties")
    require(isinstance(props, dict), "existing-gateway-properties-required")
    routes = props.get("customRoutes")
    if routes is None:
        return []
    require(isinstance(routes, dict) and isinstance(routes.get("addressPrefixes"), list),
            "existing-gateway-custom-routes-malformed")
    prefixes = routes["addressPrefixes"]
    require(all(isinstance(value, str) and str(_network(value, "gateway-custom-route")) == value
                for value in prefixes), "existing-gateway-custom-routes-malformed")
    require(len(set(prefixes)) == len(prefixes), "existing-gateway-custom-routes-duplicated")
    return copy.deepcopy(prefixes)


def _gateway_route_scope(gateway, identifier, vnet):
    require(isinstance(gateway, dict)
            and _resource(gateway.get("id"), "Microsoft.Network/virtualNetworkGateways") == identifier
            and identifier.split("/providers/")[0] == vnet.split("/providers/")[0],
            "existing-gateway-exact-scope-mismatch")
    props = gateway.get("properties")
    require(isinstance(props, dict), "existing-gateway-properties-required")
    configurations = props.get("ipConfigurations")
    require(isinstance(configurations, list) and configurations, "existing-gateway-ip-configurations-required")
    for item in configurations:
        require(isinstance(item, dict) and isinstance(item.get("properties"), dict),
                "existing-gateway-ip-configuration-malformed")
        subnet = item["properties"].get("subnet")
        require(isinstance(subnet, dict) and isinstance(subnet.get("id"), str)
                and subnet["id"].lower() == vnet + "/subnets/gatewaysubnet",
                "existing-gateway-exact-subnet-mismatch")


def _gateway_configuration(gateway):
    """Exclude only typed client-traffic counters, not ETags or configuration."""
    result = copy.deepcopy(gateway)
    props = result.get("properties") if isinstance(result, dict) else None
    vpn = props.get("vpnClientConfiguration") if isinstance(props, dict) else None
    if isinstance(vpn, dict) and "vpnClientConnectionHealth" in vpn:
        health = vpn["vpnClientConnectionHealth"]
        counters = {"vpnClientConnectionsCount", "totalIngressBytesTransferred", "totalEgressBytesTransferred"}
        require(isinstance(health, dict) and set(health) == counters
                and all(type(value) is int and value >= 0 for value in health.values()),
                "existing-gateway-unsupported-client-health")
        del vpn["vpnClientConnectionHealth"]
    return result


def _gateway_etag_valid(value):
    # Weak ETags are opaque freshness tokens here, never HTTP If-Match validators.
    return isinstance(value, str) and re.fullmatch(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]+"', value) is not None


def _gateway_writable_body(gateway):
    """Fail-closed GET-to-PUT projection for NETWORK_API, never a generic field stripper.

    Writable shapes: https://learn.microsoft.com/azure/templates/microsoft.network/
    2024-05-01/virtualnetworkgateways and the generated VirtualNetworkGatewayData
    reference (enableHighBandwidthVpnGateway and migration status are writable).
    Undocumented service extensions are retained, never inferred to be read-only.
    RADIUS secrets cannot be reliably recovered from GET.
    """
    gateway = _gateway_configuration(gateway)

    def fields(value, writable, readonly=()):
        require(isinstance(value, dict), "existing-gateway-unsupported-shape")
        require(set(value) <= set(writable) | set(readonly),
                "existing-gateway-unsupported-property")
        return {key: copy.deepcopy(item) for key, item in value.items() if key in writable}

    def project(value, schema):
        if isinstance(schema, type):
            require(type(value) is schema, "existing-gateway-unsupported-shape")
            return copy.deepcopy(value)
        if isinstance(schema, list):
            require(isinstance(value, list), "existing-gateway-unsupported-shape")
            return [project(item, schema[0]) for item in value]
        writable, readonly, required = schema
        output = fields(value, writable, readonly)
        require(set(required) <= set(output), "existing-gateway-incomplete-writable-shape")
        for key in output:
            output[key] = project(output[key], writable[key])
        # Read-only does not mean safe to ignore an unrecognised response shape.
        for key in set(value) & set(readonly):
            project(value[key], readonly[key])
        return output

    def obj(writable, readonly=None, required=()):
        return writable, readonly or {}, required

    resource_metadata = {"etag": str, "type": str}
    state = {"provisioningState": str}
    reference = obj({"id": str}, required=("id",))
    address_space = obj({"addressPrefixes": [str]}, required=("addressPrefixes",))
    child = lambda properties: obj(
        {"id": str, "name": str, "properties": properties}, resource_metadata, ("name", "properties"))
    certificate = lambda prop: child(obj({prop: str}, state, (prop,)))
    bgp_address = obj({"ipconfigurationId": str, "customBgpIpAddresses": [str]},
                      {"defaultBgpIpAddresses": [str], "tunnelIpAddresses": [str]}, ("ipconfigurationId",))
    ipconfig = child(obj({"privateIPAllocationMethod": str, "subnet": reference,
                         "publicIPAddress": reference}, {**state, "privateIPAddress": str}))
    mapping = obj({"addressSpace": str, "portRange": str}, required=("addressSpace",))
    nat = child(obj({"type": str, "mode": str, "ipConfigurationId": str,
                     "internalMappings": [mapping], "externalMappings": [mapping]}, state,
                    ("type", "mode", "internalMappings", "externalMappings")))
    policy = child(obj({"isDefault": bool, "priority": int, "policyMembers": [
        obj({"name": str, "attributeType": str, "attributeValue": str},
            required=("name", "attributeType", "attributeValue"))]}, state,
        ("isDefault", "priority", "policyMembers")))
    connection = child(obj({"virtualNetworkGatewayPolicyGroups": [reference],
                            "vpnClientAddressPool": address_space}, state,
                           ("virtualNetworkGatewayPolicyGroups", "vpnClientAddressPool")))
    vpn_schema = obj({
        "vpnClientAddressPool": address_space, "vpnClientProtocols": [str],
        "vpnAuthenticationTypes": [str], "aadTenant": str, "aadAudience": str, "aadIssuer": str,
        "vpnClientRootCertificates": [certificate("publicCertData")],
        "vpnClientRevokedCertificates": [certificate("thumbprint")],
        "vpnClientIpsecPolicies": [obj({
            **{key: str for key in ("dhGroup", "ikeEncryption", "ikeIntegrity",
                                   "ipsecEncryption", "ipsecIntegrity", "pfsGroup")},
            "saDataSizeKilobytes": int, "saLifeTimeSeconds": int})],
        "vngClientConnectionConfigurations": [connection],
        "radiusServerAddress": str, "radiusServerSecret": str,
        "radiusServers": [obj({"radiusServerAddress": str, "radiusServerScore": int,
                               "radiusServerSecret": str})],
    })
    props = fields(gateway.get("properties"), {
        "ipConfigurations", "gatewayType", "vpnType", "enableBgp", "activeActive", "sku",
        "vpnClientConfiguration", "bgpSettings", "customRoutes", "gatewayDefaultSite",
        "vpnGatewayGeneration", "enablePrivateIpAddress", "enableDnsForwarding",
        "disableIPSecReplayProtection", "natRules", "enableBgpRouteTranslationForNat",
        "allowRemoteVnetTraffic", "allowVirtualWanTraffic", "virtualNetworkGatewayPolicyGroups",
        "adminState", "autoScaleConfiguration", "resiliencyModel", "vNetExtendedLocationResourceId",
        "enableHighBandwidthVpnGateway", "virtualNetworkGatewayMigrationStatus",
        *GATEWAY_RESPONSE_EXTENSIONS,
    }, {"provisioningState", "resourceGuid", "inboundDnsForwardingEndpoint"})
    require(props.get("enableBgp") is False, "existing-gateway-route-append-bgp-review-required")
    require(props.get("gatewayType") == "Vpn" and props.get("vpnType") == "RouteBased",
            "existing-gateway-not-routebased-vpn")
    for key in ("resourceGuid", "provisioningState", "inboundDnsForwardingEndpoint"):
        if key in gateway["properties"]:
            project(gateway["properties"][key], str)
    require(_gateway_ready(gateway) and gateway["properties"].get("provisioningState") == "Succeeded",
            "existing-gateway-route-append-pending-configuration")
    vpn = props.get("vpnClientConfiguration")
    require(isinstance(vpn, dict), "existing-gateway-vpn-configuration-required")
    require(not any(vpn.get(key) for key in ("radiusServerAddress", "radiusServerSecret", "radiusServers"))
            and "Radius" not in (vpn.get("vpnAuthenticationTypes") or []),
            "existing-gateway-radius-secret-preservation-unverified")
    schemas = {
        "ipConfigurations": [ipconfig], "sku": obj({"name": str, "tier": str}, {"capacity": int}),
        "vpnClientConfiguration": vpn_schema,
        "bgpSettings": obj({"asn": int, "peerWeight": int, "bgpPeeringAddress": str,
                             "bgpPeeringAddresses": [bgp_address]}),
        "customRoutes": address_space, "gatewayDefaultSite": reference,
        "natRules": [nat], "virtualNetworkGatewayPolicyGroups": [policy],
        "autoScaleConfiguration": obj({"bounds": obj({"min": int, "max": int})}),
        "virtualNetworkGatewayMigrationStatus": obj(
            {"state": str, "phase": str, "errorMessage": str}, required=("state", "phase", "errorMessage")),
        "remoteVirtualNetworkPeerings": [reference],
        **{key: bool for key in ("enableBgp", "activeActive", "enablePrivateIpAddress",
                                "enableDnsForwarding", "disableIPSecReplayProtection",
                                "enableBgpRouteTranslationForNat", "allowRemoteVnetTraffic",
                                "allowVirtualWanTraffic", "enableHighBandwidthVpnGateway",
                                "isMigrateToCSES", "isMigratedLegacySKU", "blockUpgradeOfMigratedLegacyGateways")},
    }
    for key, value in props.items():
        if value is None and key in ("customRoutes", "gatewayDefaultSite"):
            continue
        props[key] = project(value, schemas.get(key, str))
    if "virtualNetworkGatewayMigrationStatus" in props:
        migration = props["virtualNetworkGatewayMigrationStatus"]
        require(migration["state"] == "None" and migration["phase"] == "None" and not migration["errorMessage"],
                "existing-gateway-migration-not-idle")
    require(props.get("isMigrateToCSES", False) is False, "existing-gateway-migration-not-idle")
    require(props.get("packetCaptureDiagnosticState", "None") in ("None", "Stopped"),
            "existing-gateway-packet-capture-not-idle")
    require(isinstance(props.get("sku"), dict) and {"name", "tier"} <= set(props["sku"]),
            "existing-gateway-sku-required")
    require(isinstance(props.get("ipConfigurations"), list) and props["ipConfigurations"],
            "existing-gateway-ip-configurations-required")
    for config in props["ipConfigurations"]:
        ip = config.get("properties", {})
        require(config.get("name") and ip.get("privateIPAllocationMethod") == "Dynamic"
                and ip.get("subnet", {}).get("id") and ip.get("publicIPAddress", {}).get("id"),
                "existing-gateway-ip-configuration-preservation-unverified")
    body = fields(gateway, {"location", "tags", "extendedLocation", "identity", "properties"},
                  {"id", "name", "type", "etag"})
    for key in ("id", "name", "type", "etag"):
        if key in gateway:
            project(gateway[key], str)
    require(isinstance(body.get("location"), str) and body["location"], "existing-gateway-location-required")
    if "tags" in body:
        require(isinstance(body["tags"], dict) and all(isinstance(key, str) and isinstance(value, str)
                for key, value in body["tags"].items()), "existing-gateway-unsupported-shape")
    if "extendedLocation" in body:
        body["extendedLocation"] = project(body["extendedLocation"], obj({"name": str, "type": str}))
    if "identity" in body:
        identity = fields(body["identity"], {"type", "userAssignedIdentities"}, {"principalId", "tenantId"})
        require(identity.get("type") in ("None", "SystemAssigned", "UserAssigned", "SystemAssigned, UserAssigned"),
                "existing-gateway-unsupported-identity")
        for key in ("principalId", "tenantId"):
            if key in body["identity"] and body["identity"][key] is not None:
                project(body["identity"][key], str)
        if "userAssignedIdentities" in identity:
            require(isinstance(identity["userAssignedIdentities"], dict), "existing-gateway-unsupported-identity")
            for identifier, value in identity["userAssignedIdentities"].items():
                _resource(identifier, "Microsoft.ManagedIdentity/userAssignedIdentities")
                identity["userAssignedIdentities"][identifier] = project(
                    value, obj({}, {"principalId": str, "clientId": str}))
        body["identity"] = identity
    body["properties"] = props
    return body


def _gateway_ready(value):
    if isinstance(value, dict):
        return value.get("provisioningState", "Succeeded") == "Succeeded" and all(
            _gateway_ready(item) for item in value.values())
    return not isinstance(value, list) or all(_gateway_ready(item) for item in value)


def _gateway_route_review(builder, gateway, vnet, dev, ownership, coordination_mode):
    gateway = _gateway_configuration(gateway)
    before = _gateway_routes(gateway)
    if dev in before:
        return False
    identifier = _resource(gateway["id"], "Microsoft.Network/virtualNetworkGateways")
    _gateway_route_scope(gateway, identifier, vnet)
    expected = copy.deepcopy(gateway)
    expected["properties"]["customRoutes"] = {
        **(expected["properties"].get("customRoutes") or {}), "addressPrefixes": before + [dev]}
    effect = {
        "kind": "gateway-route-append", "id": identifier, "api": NETWORK_API,
        "vnet_id": vnet, "factory_cidr": dev, "ownership": ownership,
        "before": copy.deepcopy(gateway), "before_etag": gateway.get("etag"),
        "expected": expected, "executable": False,
        "limitation": GATEWAY_ROUTE_APPEND_LIMITATION,
    }
    builder.effects.append(effect)
    manual = coordination_mode == "single-writer"
    if not manual:
        builder.blockers.append(GATEWAY_ROUTE_APPEND_LIMITATION + ":" + identifier)
    blockers_before = len(builder.blockers)
    etag = gateway.get("etag")
    if not _gateway_etag_valid(etag):
        builder.blockers.append("existing-gateway-valid-etag-required:" + identifier)
    props = gateway["properties"]
    if props.get("enableBgp") is not False:
        builder.blockers.append("existing-gateway-route-append-bgp-review-required:" + identifier)

    if props.get("provisioningState") != "Succeeded" or not _gateway_ready(gateway):
        builder.blockers.append("existing-gateway-route-append-pending-configuration:" + identifier)
    if manual:
        effect["manual_writer_warning"] = GATEWAY_MANUAL_WRITER_WARNING
        extensions = [key for key in GATEWAY_RESPONSE_EXTENSIONS if key in props]
        if extensions:
            effect["retained_response_extensions"] = extensions
            effect["response_extension_warning"] = GATEWAY_RESPONSE_EXTENSION_WARNING
        try:
            _gateway_writable_body(gateway)
            effect["body"] = _gateway_writable_body(expected)
        except PrerequisiteError as exc:
            builder.blockers.append(exc.code + ":" + identifier)
        effect["executable"] = len(builder.blockers) == blockers_before
        effect.pop("limitation")
    return True


def _revalidate_gateway_route_review(runtime, effect, *, coordination_mode=None, manual_writer_warning=None):
    require(coordination_mode == "single-writer", GATEWAY_ROUTE_APPEND_LIMITATION)
    require(manual_writer_warning == GATEWAY_MANUAL_WRITER_WARNING
            and effect.get("manual_writer_warning") == GATEWAY_MANUAL_WRITER_WARNING,
            "gateway-route-append-manual-writer-warning-required")
    identifier = _resource(effect["id"], "Microsoft.Network/virtualNetworkGateways")
    vnet = _resource(effect["vnet_id"], "Microsoft.Network/virtualNetworks")
    require(effect["api"] == NETWORK_API, "gateway-route-append-api-mismatch")
    _, _, current = runtime.arm("GET", identifier, NETWORK_API)
    current = _gateway_configuration(current)
    _gateway_route_scope(current, identifier, vnet)
    require(current.get("etag") == effect["before_etag"], "gateway-route-append-etag-changed")
    require(current == effect["before"], "gateway-route-append-configuration-changed")
    require(_gateway_etag_valid(current.get("etag")), "existing-gateway-valid-etag-required")
    _gateway_writable_body(current)
    before = _gateway_routes(current)
    dev = str(_network(effect["factory_cidr"], "dev_vnet_cidr"))
    require(dev not in before, "gateway-route-append-no-longer-required")
    expected = copy.deepcopy(current)
    expected["properties"]["customRoutes"] = {
        **(expected["properties"].get("customRoutes") or {}), "addressPrefixes": before + [dev]}
    require(expected == effect["expected"], "gateway-route-append-not-exact-addition")
    body = _gateway_writable_body(expected)
    require(effect.get("executable") is True and body == effect.get("body"),
            "gateway-route-append-writable-body-changed")
    return body


def _hub(builder, config, context, target, bindings, owned):
    external = config["access_hub_mode"] == "external"
    if not external and not config["setup_hub_access"]:
        bindings["network"] = {"mode": "none", "owned": False}
        return []
    if external:
        sub = _guid(config.get("access_hub_subscription_id"))
        rg = _rg(f"/subscriptions/{sub}/resourceGroups/{config.get('access_hub_resource_group', '')}")
        vnet = _resource(rg + "/providers/Microsoft.Network/virtualNetworks/" +
                         str(config.get("access_hub_vnet_name", "")), "Microsoft.Network/virtualNetworks")
        cidr = _network(config.get("access_hub_vnet_cidr"), "access_hub_vnet_cidr")
        require(rg not in owned, "external-hub-must-not-be-factory-owned")
        ownership = "external-retain-never-enroll-or-delete"
    else:
        vnet = _resource(context.get("integrated_vnet_id"), "Microsoft.Network/virtualNetworks")
        rg = _rg(vnet.split("/providers/")[0])
        require(rg in owned and vnet.split("/")[2] == target["subscription_id"],
                "integrated-network-must-be-owned")
        cidr = _network(context.get("integrated_vnet_cidr"), "integrated_vnet_cidr")
        ownership = "factory-owned"
    require(cidr.prefixlen <= 24, "access-vnet-prefix-must-be-24-or-larger")
    dev = _network(config.get("dev_vnet_cidr", "172.16.0.0/18"), "dev_vnet_cidr")
    require(not external or not cidr.overlaps(dev), "external-and-factory-vnet-overlap")
    old_rg = builder.read(rg, enrollment.RG_API)
    if external and (context.get("coordination_mode") == "connectivity-hub"
                     or config.get("coordination_mode") == "single-writer") and old_rg:
        require(not any(k.lower() in ("aifactory.factory_id", "aifactory.scaleset_id")
                        for k in old_rg.get("tags", {})), "shared-hub-resource-group-has-factory-ownership")
    if old_rg is None:
        builder.ensure(rg, enrollment.RG_API, {"location": target["location"]},
                       ownership=ownership, already_read=True)
    existing_vnet = builder.read(vnet, NETWORK_API)
    network_location = existing_vnet.get("location") if external and existing_vnet else target["location"]
    require(isinstance(network_location, str) and re.fullmatch(r"[a-z0-9]{2,40}", network_location),
            "access-vnet-location-required")
    if external and (context.get("coordination_mode") == "connectivity-hub"
                     or config.get("coordination_mode") == "single-writer") and existing_vnet:
        require(not any(key.lower() in ("aifactory.factory_id", "aifactory.scaleset_id")
                        for key in (existing_vnet.get("tags") or {})), "shared-hub-vnet-has-factory-ownership")
    vnet_body = {"location": network_location, "properties": {"addressSpace": {"addressPrefixes": [str(cidr)]}}}
    # Integrated networking belongs to the frozen common deployment. Running
    # this phase afterwards avoids the common template replacing access subnets.
    if not external and existing_vnet is None:
        builder.blockers.append("integrated-access-requires-common-network-first:" + vnet)
    else:
        builder.ensure(vnet, NETWORK_API, vnet_body, ownership=ownership,
                       existing=existing_vnet, already_read=True)
    bindings["network"] = {"mode": "external" if external else "integrated", "owned": not external,
                           "vnet_id": vnet, "resource_group_id": rg, "cidr": str(cidr)}
    if external and context.get("coordination_mode") == "connectivity-hub":
        _hub_private_endpoint_subnet(builder, vnet, cidr, existing_vnet, bindings,
                                    reserve_access_subnets=config["setup_hub_access"])
    if not config["setup_hub_access"]:
        _private_dns(builder, vnet, rg, context, target, ownership)
        if external:
            _peerings(builder, vnet, context, config, owned, bindings)
        return [rg]
    pool = _network(config.get("vpn_client_cidr", "172.31.240.0/24"), "vpn_client_cidr")
    require(not pool.overlaps(cidr) and not pool.overlaps(dev), "vpn-client-address-pool-overlap")
    gateways = builder.collection(f"/subscriptions/{vnet.split('/')[2]}/providers/Microsoft.Network/virtualNetworkGateways",
                                  NETWORK_API)
    matching = [gateway for gateway in gateways if any(
        str(ip.get("properties", {}).get("subnet", {}).get("id", "")).lower().startswith(vnet + "/subnets/")
        for ip in gateway.get("properties", {}).get("ipConfigurations", []))]
    require(len(matching) <= 1, "multiple-gateways-bound-to-access-vnet")
    vpn = {"vpnClientAddressPool": {"addressPrefixes": [str(pool)]}, "vpnClientProtocols": ["OpenVPN"],
           "vpnAuthenticationTypes": ["AAD"], "aadTenant": "https://login.microsoftonline.com/" + target["tenant_id"],
           "aadAudience": "c632b3df-fb67-4d84-bdcf-b95ad541b5c8",
           "aadIssuer": "https://sts.windows.net/" + target["tenant_id"] + "/"}
    if matching:
        identifier = _resource(matching[0]["id"], "Microsoft.Network/virtualNetworkGateways")
        gateway = builder.read(identifier, NETWORK_API)
        require(gateway == matching[0], "existing-gateway-inventory-changed:" + identifier)
        _gateway_route_scope(gateway, identifier, vnet)
        props = gateway.get("properties", {})
        if props.get("provisioningState") != "Succeeded":
            builder.blockers.append("existing-gateway-not-ready:" + gateway["id"])
        require(props.get("gatewayType") == "Vpn" and props.get("vpnType") == "RouteBased",
                "existing-gateway-not-routebased-vpn:" + gateway["id"])
        if not _contains(props.get("vpnClientConfiguration"), vpn):
            builder.blockers.append("existing-gateway-p2s-configuration-incompatible-review-exact-resource:" + gateway["id"])
        route_append = _gateway_route_review(builder, gateway, vnet, str(dev), ownership,
                                            config.get("coordination_mode", "blob"))
        dns = (existing_vnet or {}).get("properties", {}).get("dhcpOptions", {}).get("dnsServers", [])
        resolvers = builder.collection(f"/subscriptions/{vnet.split('/')[2]}/providers/Microsoft.Network/dnsResolvers", DNS_API)
        endpoints = []
        for resolver in resolvers:
            if resolver.get("properties", {}).get("virtualNetwork", {}).get("id", "").lower() != vnet:
                continue
            if resolver.get("properties", {}).get("provisioningState") != "Succeeded":
                continue
            endpoints.extend(builder.collection(resolver["id"] + "/inboundEndpoints", DNS_API))
        verified_ips = {item.get("privateIpAddress") for endpoint in endpoints
                        if endpoint.get("properties", {}).get("provisioningState") == "Succeeded"
                        for item in endpoint.get("properties", {}).get("ipConfigurations", [])}
        if not dns or any(ip not in verified_ips for ip in dns):
            builder.blockers.append("existing-gateway-private-dns-resolver-unverified:" + gateway["id"])
        bindings["network"]["gateway_id"] = gateway["id"]
        bindings["network"]["gateway_reused_unchanged"] = not route_append
        if route_append:
            bindings["network"]["gateway_route_append_required"] = True
        bindings["network"]["dns_servers"] = dns
        bindings["network"]["dns_inbound_endpoint_ids"] = [e["id"] for e in endpoints]
        # Never guess the generated name or replace an arbitrary shared gateway.
        # DNS resources are separately reviewed below.
    else:
        seed = digest({"vnet": vnet})[:12]
        gateway_subnet = str(ipaddress.ip_network((int(cidr.broadcast_address) - 31, 27)))
        resolver_subnet = str(ipaddress.ip_network((int(cidr.broadcast_address) - 47, 28)))
        existing_subnets = (existing_vnet or {}).get("properties", {}).get("subnets", [])
        for name, subnet_cidr in (("GatewaySubnet", gateway_subnet), ("snet-aif-dns-resolver", resolver_subnet)):
            for subnet in existing_subnets:
                prefixes = subnet.get("properties", {}).get("addressPrefixes", [])
                prefixes += [subnet.get("properties", {}).get("addressPrefix")] if subnet.get("properties", {}).get("addressPrefix") else []
                if subnet["name"] != name and any(_network(p, "existing-subnet").overlaps(_network(subnet_cidr, name))
                                                  for p in prefixes):
                    builder.blockers.append("reserved-access-subnet-overlaps-existing:" + subnet["name"])
            body = {"properties": {"addressPrefix": subnet_cidr}}
            if name != "GatewaySubnet":
                body["properties"]["delegations"] = [{"name": "dns-resolver", "properties": {"serviceName": "Microsoft.Network/dnsResolvers"}}]
            builder.ensure(vnet + "/subnets/" + name, NETWORK_API, body, ownership=ownership)
        resolver_ip = str(_network(resolver_subnet, "resolver").network_address + 4)
        resolver = rg + "/providers/Microsoft.Network/dnsResolvers/dnspr-" + seed
        builder.ensure(resolver, DNS_API, {"location": network_location,
                       "properties": {"virtualNetwork": {"id": vnet}}}, ownership=ownership)
        builder.ensure(resolver + "/inboundEndpoints/inbound", DNS_API, {
            "location": network_location, "properties": {"ipConfigurations": [{
                "privateIpAllocationMethod": "Static", "privateIpAddress": resolver_ip,
                "subnet": {"id": vnet + "/subnets/snet-aif-dns-resolver"}}]}}, ownership=ownership)
        dns = (existing_vnet or {}).get("properties", {}).get("dhcpOptions", {}).get("dnsServers", [])
        if dns != [resolver_ip]:
            # The bounded update is explicit, preserves every unrelated VNet
            # property, and is never folded into an unreviewed gateway update.
            builder.effects.append({"kind": "vnet-dns", "id": vnet, "api": NETWORK_API,
                                    "before_dns": dns, "dns_servers": [resolver_ip], "ownership": ownership})
        gateway_id = rg + "/providers/Microsoft.Network/virtualNetworkGateways/vpngw-" + seed
        pip = rg + "/providers/Microsoft.Network/publicIPAddresses/vpngw-" + seed
        builder.ensure(pip, NETWORK_API, {"location": network_location, "sku": {"name": "Standard"},
                       "zones": ["1", "2", "3"], "properties": {"publicIPAllocationMethod": "Static"}},
                       ownership=ownership)
        builder.ensure(gateway_id, NETWORK_API, {"location": network_location, "properties": {
            "gatewayType": "Vpn", "vpnType": "RouteBased", "sku": {"name": "VpnGw1AZ", "tier": "VpnGw1AZ"},
            "vpnGatewayGeneration": "Generation1", "enableBgp": False, "activeActive": False,
            "ipConfigurations": [{"name": "default", "properties": {"privateIPAllocationMethod": "Dynamic",
                "subnet": {"id": vnet + "/subnets/GatewaySubnet"}, "publicIPAddress": {"id": pip}}}],
            "vpnClientConfiguration": vpn, "customRoutes": {"addressPrefixes": [str(dev)]}}},
            ownership=ownership)
        bindings["network"].update(gateway_id=gateway_id, resolver_id=resolver, resolver_inbound_ip=resolver_ip)
    _private_dns(builder, vnet, rg, context, target, ownership)
    if external:
        _peerings(builder, vnet, context, config, owned, bindings)
    _bastion(builder, context, target, owned, bindings)
    return [rg]


def capabilities():
    """Advertise implemented stages only; this is not a complete creation workflow."""
    return {
        "contract_version": CONTRACT_VERSION,
        "execution_mode": "privileged-bootstrap",
        "implemented_stages": ["privileged-prerequisites"],
        "stage_order": "after-common-foundation",
        "requires_existing_common_factorymeta": False,
        "requires_existing_coordination": True,
        "coordination_modes": ["connectivity-hub", "factory-common"],
        "hub_lock_foundation_stage": "hub_lock_foundation.prepare/execute",
        "no_hub_requires_separate_checked_provider_serialization": True,
        "requires_existing_common_network_for_access": True,
        "supports_restricted_wizard": False,
        "cold_start_supported": False,
        "existing_gateway_route_append": {
            "preview_supported": True, "execution_supported": True,
            "execution_coordination_modes": ["single-writer"],
            "manual_writer_warning": GATEWAY_MANUAL_WRITER_WARNING,
            "provider_enforced_if_match": False,
            "blob_mode_limitation": GATEWAY_ROUTE_APPEND_LIMITATION, "api_contract": GATEWAY_API_CONTRACT,
        },
        "unsupported_stages": [
            "cold-start-foundation", "identity-federation-enrollment", "repository-publication",
            "runner-provisioning", "common-deployment", "project-deployment",
        ],
    }


def _commands(effects):
    commands = []
    for effect in effects:
        kind = effect["kind"]
        if kind in ("arm-create", "provider-register", "vnet-dns"):
            command = {"transport": "arm", "method": "POST" if kind == "provider-register" else "PUT",
                       "resource_id": effect["id"] + ("/register" if kind == "provider-register" else ""),
                       "api_version": effect["api"]}
            if kind == "arm-create":
                command["body"] = copy.deepcopy(effect["body"])
                command["precondition"] = "exact-resource-still-absent"
            elif kind == "vnet-dns":
                command["property_changes"] = {"properties.dhcpOptions.dnsServers": effect["dns_servers"]}
                command["precondition"] = {"existing_dns_servers": effect["before_dns"],
                                           "preserve_all_other_vnet_properties": True}
            else:
                command["precondition"] = {"registrationState": "NotRegistered"}
        elif kind == "gateway-route-append":
            command = {
                "transport": "arm", "method": "PUT", "resource_id": effect["id"],
                "api_version": effect["api"], "executable": effect["executable"],
                "api_contract": GATEWAY_API_CONTRACT,
                "property_changes": {
                    "properties.customRoutes.addressPrefixes":
                        effect["expected"]["properties"]["customRoutes"]["addressPrefixes"]},
                "precondition": {
                    "exact_gateway_state_sha256": digest(effect["before"]),
                    "etag": effect["before_etag"], "vnet_id": effect["vnet_id"],
                    "provider_enforced_strong_if_match_required": "manual_writer_warning" not in effect,
                    "provider_enforced_if_match": False,
                    "preserve_all_other_gateway_configuration": True},
            }
            if "manual_writer_warning" in effect:
                command["precondition"]["manual_writer_warning"] = effect["manual_writer_warning"]
                if "body" in effect:
                    command["body"] = copy.deepcopy(effect["body"])
                if "retained_response_extensions" in effect:
                    command["retained_response_extensions"] = effect["retained_response_extensions"]
                    command["response_extension_warning"] = effect["response_extension_warning"]
            else:
                command["limitation"] = GATEWAY_ROUTE_APPEND_LIMITATION
        elif kind in ("group-create", "first-party-app-create"):
            command = {"transport": "graph", "method": "POST",
                       "path": "groups" if kind == "group-create" else "servicePrincipals",
                       "body": copy.deepcopy(effect["body"]),
                       "precondition": "exact-display-name-still-absent" if kind == "group-create" else "exact-app-id-still-absent"}
        else:
            require(kind == "group-member-add", "unrecognized-reviewed-effect")
            command = {"transport": "graph", "method": "POST", "path": "groups/" + effect["group_id"] + "/members/$ref",
                       "body": {"@odata.id": GRAPH + "v1.0/directoryObjects/" + effect["member_id"]}}
        commands.append(command)
    return commands


def prepare(*, source_root, consumer_root, scope, bootstrap_config, expected_revision, context, runtime=None):
    """Return a read-only frozen JSON plan. Only config fields this stage consumes are accepted."""
    root = ordinary(consumer_root)
    require(isinstance(expected_revision, str) and expected_revision, "expected-catalog-revision-required")
    require(isinstance(context, dict) and set(context) <= CONTEXT_KEYS, "unknown-prerequisite-context")
    require(isinstance(bootstrap_config, dict) and set(bootstrap_config) <= CONFIG_KEYS,
            "unknown-prerequisite-config-field")
    target, consumer_hash = _read_target(root, scope)
    source = verify_source_snapshot(source_root=source_root,
                                    expected_payload_sha256=context.get("source_payload_sha256"))
    require(root != ordinary(source_root), "source-cannot-be-consumer")
    config = copy.deepcopy(bootstrap_config)
    for field, value in (("tenant_id", target["tenant_id"]), ("subscription_id", target["subscription_id"]),
                         ("location", target["location"]), ("factory_prefix", target["prefix"])):
        require(config.get(field, value) == value, "registered-config-mismatch:" + field)
    require(config.get("access_hub_mode") in ("integrated", "external"), "explicit-access-hub-mode-required")
    require(type(config.get("setup_hub_access")) is bool, "explicit-setup-hub-access-required")
    require(isinstance(config.get("team_group_name"), str) and 1 <= len(config["team_group_name"]) <= 128
            and not any(ord(c) < 32 for c in config["team_group_name"]), "team-group-name-required")
    require(isinstance(config.get("team_member_email"), str)
            and re.fullmatch(r"[^@\s/]+@[^@\s/]+", config["team_member_email"]), "team-member-email-required")
    require(re.fullmatch(r"[a-z0-9]{2,16}", str(context.get("location_short", ""))), "location-short-required")
    mode = context.get("coordination_mode", "factory-common")
    require(config.get("coordination_mode", "blob") in ("blob", "single-writer"),
            "unknown-explicit-coordination-mode")
    if config.get("coordination_mode") == "single-writer":
        require(mode == "provider" and not context.get("coordination"), "single-writer-requires-provider-reservation")
    coordinates = copy.deepcopy(context.get("coordination", {}))
    require(mode == "provider" and not coordinates
            or set(coordinates) == {"account_id", "account_url", "container"}, "exact-coordination-required")
    account = _resource(coordinates["account_id"], "Microsoft.Storage/storageAccounts") if coordinates else None
    owned = sorted({_rg(x) for x in context.get("owned_resource_group_ids", [])})
    require(owned and all(x.split("/")[2] == target["subscription_id"] for x in owned),
            "owned-scope-subscription-mismatch")
    require(mode in ("connectivity-hub", "factory-common", "provider"), "unknown-coordination-mode")
    if mode == "connectivity-hub":
        hub_rg = _rg(context.get("hub_resource_group_id"))
        require(hub_rg not in owned, "shared-hub-coordination-must-not-be-factory-owned")
        require(config["access_hub_mode"] == "external", "shared-coordination-requires-explicit-external-hub")
        configured_hub = _rg(f"/subscriptions/{_guid(config.get('access_hub_subscription_id'))}"
                             f"/resourcegroups/{config.get('access_hub_resource_group', '')}")
        require(hub_rg == configured_hub, "coordination-hub-scope-mismatch")
        require(coordinates == hub_lock_foundation.coordination(hub_rg), "canonical-shared-hub-coordination-required")
    elif mode == "factory-common":
        require("hub_resource_group_id" not in context, "legacy-coordination-cannot-imply-hub-migration")
        require(account.split("/")[2] == target["subscription_id"], "common-coordination-subscription-mismatch")
        require(coordinates["account_url"] == "https://" + account.rsplit("/", 1)[1] + ".blob.core.windows.net"
                and coordinates["container"] == "factorymeta", "factory-common-factorymeta-required")
        require(account.split("/providers/")[0] in owned, "coordination-must-be-factory-common")
    vault = _resource(context.get("seeding_keyvault_id"), "Microsoft.KeyVault/vaults")
    require(vault.split("/providers/")[0] in owned, "seeding-vault-must-be-owned")
    runtime = runtime or Cloud(target, coordinates)
    runtime.read_only = True
    builder = Builder(runtime)
    if mode == "provider":
        require(config.get("coordination_mode") == "single-writer"
                or config["access_hub_mode"] != "external" and not config["setup_hub_access"],
                "hub-requires-shared-physical-coordination")
        runtime.verify_provider_serialization(context.get("provider_serialization"))
    storage = builder.read(account, enrollment.STORAGE_API) if account else None
    if mode == "connectivity-hub":
        try:
            hub_lock_foundation.validate_shared_account(storage, hub_rg)
        except hub_lock_foundation.FoundationError as exc:
            builder.blockers.append(exc.code + ":" + account)
    elif mode == "factory-common" and (not storage or storage.get("properties", {}).get("isHnsEnabled") is not True):
        builder.blockers.append("canonical-common-adls-must-exist-before-distributed-prerequisites")
    container_id = account + "/blobservices/default/containers/" + coordinates["container"] if account else None
    container = builder.read(container_id, enrollment.STORAGE_API) if account else None
    if account and (not container or container.get("properties", {}).get("publicAccess", "None") != "None"):
        builder.blockers.append("private-coordination-container-required:" + container_id)
    if storage and container:
        runtime.blob("GET", "bootstrap-access-probe", allowed=(200, 404))
    provider_scopes = _providers(builder, target, config, context)
    project_group = context.get("project_resource_group_id")
    if project_group:
        project_group = _rg(project_group)
        require("project_id" in target and project_group in owned, "exact-owned-project-scope-required")
        expected_project = (f"/subscriptions/{target['subscription_id']}/resourcegroups/{target['prefix']}esml-project"
                            f"{target['project_number']}-{context['location_short']}-dev-{target['suffix']}-rg").lower()
        require(project_group == expected_project, "canonical-project-resource-group-required")
    for rg in owned:
        tags = {"aifactory.factory_id": target["factory_id"], "aifactory.scaleset_id": target["scale_set_id"]}
        if rg == project_group:
            tags.update({"aifactory.project_id": target["project_number"], "aifactory.logical_project_id": target["project_id"]})
        existing = builder.read(rg, enrollment.RG_API)
        if existing is None:
            builder.ensure(rg, enrollment.RG_API, {"location": target["location"], "tags": tags},
                ownership="factory-owned", already_read=True)
        else:
            require(_contains(existing.get("tags", {}), tags),
                    "existing-owned-resource-group-tags-mismatch:" + rg)
    minimum = context.get("bootstrap_phase") == "minimum-foundation"
    require(context.get("bootstrap_phase") in (None, "minimum-foundation"), "unknown-bootstrap-phase")
    bindings = {"team_group_id": None if minimum else _group(builder, config, target), "seeding_keyvault_id": vault}
    if project_group:
        bindings["project_resource_group_id"] = project_group
    if not minimum and config.get("first_party_apps"):
        bindings["first_party_apps"] = _first_party_apps(builder, config)
    if minimum:
        vnet = _resource(context.get("integrated_vnet_id"), "Microsoft.Network/virtualNetworks")
        require(vnet.split("/providers/")[0] in owned, "minimum-vnet-must-be-factory-owned")
        cidr = str(_network(context.get("integrated_vnet_cidr"), "integrated_vnet_cidr"))
        require(cidr == config.get("dev_vnet_cidr"), "minimum-vnet-config-mismatch")
        builder.ensure(vnet, NETWORK_API, {"location": target["location"],
                       "properties": {"addressSpace": {"addressPrefixes": [cidr]}}}, ownership="factory-owned")
        identity_id = _resource(context.get("deployment_identity_id"), "Microsoft.ManagedIdentity/userAssignedIdentities")
        require(type(context.get("reuse_deployment_identity", False)) is bool, "invalid-identity-reuse-selection")
        if context.get("reuse_deployment_identity"):
            identity = builder.read(identity_id, enrollment.IDENTITY_API)
            require(identity is not None, "reviewed-existing-identity-missing")
        else:
            require(identity_id.split("/providers/")[0] in owned, "minimum-identity-must-be-factory-owned")
            identity = builder.ensure(identity_id, enrollment.IDENTITY_API, {"location": target["location"]},
                                      ownership="factory-owned")
        bindings.update(integrated_vnet_id=vnet, deployment_identity_id=identity_id)
        if identity:
            props = identity.get("properties", {})
            require(props.get("tenantId") == target["tenant_id"], "minimum-identity-tenant-conflict")
            bindings.update(deployment_principal_id=_guid(props.get("principalId")),
                            deployment_client_id=_guid(props.get("clientId")))
    else:
        builder.ensure(vault, "2023-07-01", {"location": target["location"], "properties": {
            "tenantId": target["tenant_id"], "sku": {"family": "A", "name": "standard"},
            "enableRbacAuthorization": True, "enablePurgeProtection": True, "enabledForTemplateDeployment": True}},
            ownership="factory-owned")
    if not minimum and (context.get("deployment_identity_id") or context.get("deployment_principal_id")):
        identity_id = _resource(context.get("deployment_identity_id"), "Microsoft.ManagedIdentity/userAssignedIdentities")
        identity = builder.read(identity_id, enrollment.IDENTITY_API)
        principal = _guid(context.get("deployment_principal_id"))
        require(identity and identity.get("properties", {}).get("principalId") == principal
                and identity.get("properties", {}).get("tenantId") == target["tenant_id"],
                "deployment-identity-binding-mismatch")
        role = f"/subscriptions/{target['subscription_id']}/providers/Microsoft.Authorization/roleDefinitions/4633458b-17de-408a-b874-0445c86b69e6"
        role_id = vault + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid5(NAMESPACE_URL, vault + ":" + principal + ":" + role))
        builder.ensure(role_id, enrollment.ROLE_API, {"properties": {"principalId": principal,
                       "principalType": "ServicePrincipal", "roleDefinitionId": role}}, ownership="factory-owned")
        subscription = "/subscriptions/" + target["subscription_id"]
        metadata_role = subscription + "/providers/Microsoft.Authorization/roleDefinitions/" + str(
            uuid5(NAMESPACE_URL, "aifactory-deployment-metadata:" + target["subscription_id"] + ":" + target["factory_id"]))
        builder.ensure(metadata_role, enrollment.ROLE_API, {"properties": {
            "roleName": "AI Factory deployment metadata " + target["factory_id"],
            "description": "Deployment records and validation only; resource writes remain limited to separately enrolled RGs.",
            "type": "CustomRole", "assignableScopes": [subscription],
            "permissions": [{"actions": [
                "Microsoft.Resources/deployments/read", "Microsoft.Resources/deployments/write",
                "Microsoft.Resources/deployments/operations/read", "Microsoft.Resources/deployments/operationStatuses/read",
                "Microsoft.Resources/deployments/validate/action", "Microsoft.Resources/deployments/whatIf/action",
                "Microsoft.Resources/subscriptions/read", "Microsoft.Resources/subscriptions/locations/read",
                "Microsoft.Resources/subscriptions/resourceGroups/read", "Microsoft.Resources/subscriptions/providers/read"],
                "notActions": [], "dataActions": [], "notDataActions": []}]}},
            ownership="subscription-deployment-metadata-role-retain")
        metadata_assignment = subscription + "/providers/Microsoft.Authorization/roleAssignments/" + str(
            uuid5(NAMESPACE_URL, metadata_role + ":" + principal))
        builder.ensure(metadata_assignment, enrollment.ROLE_API, {"properties": {"principalId": principal,
            "principalType": "ServicePrincipal", "roleDefinitionId": metadata_role}},
            ownership="subscription-deployment-metadata-role-retain")
        provider_scopes.append(subscription)
        bindings["deployment_identity_id"] = identity_id
        bindings["deployment_metadata_role_id"] = metadata_role
    hub_scopes = [] if minimum else _hub(builder, config, context, target, bindings, owned)
    gateway_auth_scopes = []
    network = bindings.get("network", {})
    if "gateway_reused_unchanged" in network:
        append_required = network.get("gateway_route_append_required", False)
        gateway_auth_scopes.append({
            "service": "arm", "scope": _resource(network["gateway_id"], "Microsoft.Network/virtualNetworkGateways"),
            "ownership": "factory-owned" if network["owned"] else "external-retain-never-enroll-or-delete",
            "read_actions": ["Microsoft.Network/virtualNetworkGateways/read"],
            "write_actions": ["Microsoft.Network/virtualNetworkGateways/write"] if append_required else [],
            "purpose": "gateway-route-append" if append_required else "gateway-reuse-readonly",
            "execution_supported": not append_required or any(
                effect["kind"] == "gateway-route-append" and effect["executable"]
                for effect in builder.effects),
        })
    locks = sorted(set(owned + hub_scopes + provider_scopes + ["/tenants/" + target["tenant_id"] + "/groups/" +
                                           digest(config["team_group_name"].casefold())]))
    plan = {"contract_version": CONTRACT_VERSION, "stage": "privileged-prerequisites",
            "execution_mode": "privileged-bootstrap", "plan_id": str(uuid4()),
            "prepared_at": time.time(), "expires_at": time.time() + 900,
            "source": source, "consumer_root": str(root), "consumer_hash": consumer_hash,
            "scope": copy.deepcopy(scope), "expected_revision": expected_revision, "target": target,
            "bootstrap_config": config, "context": copy.deepcopy(context),
            "observations": builder.observations, "effects": builder.effects,
            "bindings": bindings, "lock_scopes": locks, "blockers": builder.blockers,
            "can_execute": not builder.blockers,
            "requires_downstream_review": True, "runtime_binding_published": False,
            "governance": (GATEWAY_MANUAL_WRITER_WARNING if config.get("coordination_mode") == "single-writer"
                           else "all-writers-use-these-" + mode +
                           "-physical-leases; no automatic recovery or lease break"),
            "warnings": ([GATEWAY_MANUAL_WRITER_WARNING] if config.get("coordination_mode") == "single-writer"
                         else ["Legacy factory-common coordination is retained unchanged; it does not establish "
                          "cross-factory shared-hub coordination. Review a separate explicit migration."]
                         if mode == "factory-common" else [])}
    if any("retained_response_extensions" in effect for effect in builder.effects):
        plan["warnings"].append(GATEWAY_RESPONSE_EXTENSION_WARNING)
    plan.update(
        commands=_commands(builder.effects),
        auth_scopes=[
            {"service": "arm", "scope": value,
             "ownership": ("factory-owned" if value in owned else "subscription-provider-registration"
                           if value in provider_scopes else "external-retained")}
            for value in sorted(set(owned + hub_scopes + provider_scopes))
        ] + gateway_auth_scopes + [{"service": "graph", "tenant_id": target["tenant_id"],
              "permissions": ["Group.ReadWrite.All", "User.Read.All"] +
                  (["Application.ReadWrite.All"] if config.get("first_party_apps") else [])},
             *([{"service": "storage", "scope": container_id,
                 "purpose": "physical-leases-and-durable-stage-proofs-only"}] if account else
               [{"service": "provider", "purpose": "exclusive-initializer-ref",
                 "scope": context["provider_serialization"]["repository"]}])],
        source_hashes=copy.deepcopy(source["files"]),
        input_hash=digest({"scope": scope, "bootstrap_config": config, "context": context,
                           "expected_revision": expected_revision, "consumer_hash": consumer_hash}),
        stages=[{"id": "privileged-prerequisites", "implemented": True,
                 "can_execute": not builder.blockers, "order": "after-common-foundation"}],
        preconditions={"expected_revision": expected_revision, "consumer_hash": consumer_hash,
                       "observations_hash": digest(builder.observations),
                       "reachable_existing_coordination": coordinates,
                       "coordination_mode": mode,
                       "exclusive_writer_governance_required": True,
                       "cold_start_supported": False},
        capabilities=capabilities(),
    )
    plan["plan_hash"] = digest(plan)
    return plan


def _persist(path, value, retry_sleep=time.sleep):
    path = ordinary(path)
    sibling = ordinary(path.with_suffix("." + str(uuid4()) + ".writing"))
    with sibling.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(20):
        try:
            os.replace(sibling, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            retry_sleep(0.05)


def _wait(runtime, identifier, api, assert_held, sleep):
    for _ in range(240):
        assert_held()
        status, _, value = runtime.arm("GET", identifier, api, allowed=(200, 404))
        state = value.get("properties", {}).get("provisioningState", "Succeeded") if status == 200 else "Creating"
        require(state not in ("Failed", "Canceled"), "resource-provisioning-failed:" + identifier)
        if state == "Succeeded":
            return value
        sleep(30)
    raise PrerequisiteError("resource-provisioning-uncertain:" + identifier)


def read_result(*, state_dir, plan_id):
    """Read durable recovery evidence only; never renew, release, or break a lease."""
    path = ordinary(ordinary(state_dir) / (_guid(plan_id) + ".json"))
    require(path.is_file() and path.stat().st_size <= enrollment.MAX_BYTES, "durable-prerequisite-result-required")
    result = enrollment.parse_json(path.read_bytes())
    require(result.get("contract_version") == 1 and result.get("plan_id") == plan_id
            and result.get("status") in ("preflight", "rejected", "claimed", "running", "uncertain", "succeeded"),
            "invalid-prerequisite-result")
    return result


def execute(plan, *, expected_plan_hash, state_dir, runtime=None,
            acknowledge_exclusive_writer_governance=False, sleep=time.sleep):
    """Consume one reviewed plan; persist preflight rejection or execution evidence."""
    require(acknowledge_exclusive_writer_governance is True, "exclusive-writer-governance-required")
    require(isinstance(plan, dict) and plan.get("contract_version") == 1
            and plan.get("plan_hash") == expected_plan_hash
            and digest({k: v for k, v in plan.items() if k != "plan_hash"}) == expected_plan_hash,
            "prerequisite-plan-hash-mismatch")
    require(plan.get("can_execute") is True and not plan.get("blockers"), "prerequisite-plan-blocked")
    folder = ordinary(state_dir)
    require(folder.is_dir(), "durable-existing-state-directory-required")
    receipt_path = ordinary(folder / (_guid(plan["plan_id"]) + ".json"))
    receipt = {"contract_version": 1, "plan_id": plan["plan_id"], "plan_hash": expected_plan_hash,
               "status": "preflight", "phase": "preflight", "cloud_writes_started": False,
               "effects_completed": [], "bindings": copy.deepcopy(plan["bindings"]),
               "source": copy.deepcopy(plan["source"]), "scope": copy.deepcopy(plan["scope"]),
               "expected_revision": plan["expected_revision"], "consumer_hash": plan["consumer_hash"],
               "coordination": copy.deepcopy(plan["context"].get("coordination", {})), "lock_scopes": plan["lock_scopes"],
               "leases": {}, "reconciliation_required": True, "runtime_ready": False,
               "changed": False, "outputs": copy.deepcopy(plan["bindings"]),
               "receipt_path": str(receipt_path), "stage_results": []}
    with receipt_path.open("xb") as stream:
        stream.write(canonical(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        require(plan["prepared_at"] <= time.time() < plan["expires_at"], "prerequisite-review-expired")
        require(source_fingerprint(plan["source"]["root"]) == plan["source"], "privileged-source-changed")
        _verify_loaded_source(plan["source"])
        target, consumer_hash = _read_target(ordinary(plan["consumer_root"]), plan["scope"])
        require(target == plan["target"] and consumer_hash == plan["consumer_hash"], "consumer-register-changed")
        runtime = runtime or Cloud(target, plan["context"].get("coordination", {}))
        require(runtime.read_only is True and runtime.serialized_provisioning is False,
                "read-only-preflight-runtime-required")
        # Rebuild commands from validated configuration, not caller-supplied argv.
        fresh = prepare(source_root=plan["source"]["root"], consumer_root=plan["consumer_root"],
                        scope=plan["scope"], bootstrap_config=plan["bootstrap_config"],
                        expected_revision=plan["expected_revision"], context=plan["context"], runtime=runtime)
        for key in ("effects", "observations", "bindings", "lock_scopes", "blockers", "commands",
                    "auth_scopes", "source_hashes", "input_hash", "stages", "preconditions", "capabilities",
                    "warnings", "governance"):
            require(fresh[key] == plan[key], "prerequisite-live-state-or-plan-changed:" + key)
        require(time.time() < plan["expires_at"], "prerequisite-review-expired")
    except (PrerequisiteError, enrollment.EnrollmentError, OSError) as exc:
        code = getattr(exc, "code", "prerequisite-preflight-io-failed")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9:/._-]{1,256}", code):
            code = "prerequisite-preflight-rejected"
        receipt.update(status="rejected", error=code, requires_fresh_review=True)
        try:
            _persist(receipt_path, receipt)
        except (OSError, PrerequisiteError) as persistence_error:
            raise exc from persistence_error
        raise
    # Persist write intent before enabling any mutating transport, including Blob.
    receipt.update(status="claimed", phase="execution", cloud_writes_started=True)
    _persist(receipt_path, receipt)
    runtime.read_only = False
    runtime.serialized_provisioning = True
    remote = "bootstrap/runs/" + plan["plan_id"] + ".json"
    claimed = False
    provider_only = plan["context"].get("coordination_mode") == "provider"

    def persist():
        receipt["outputs"] = copy.deepcopy(receipt["bindings"])
        receipt["stage_results"] = [{"stage": "privileged-prerequisites", "status": receipt["status"],
                                     "effects_completed": list(receipt["effects_completed"])}]
        if "pending_effect" in receipt:
            receipt["stage_results"][0]["pending_effect"] = receipt["pending_effect"]
        _persist(receipt_path, receipt)
        if claimed:
            runtime.blob("PUT", remote, data=receipt,
                         headers={"x-ms-blob-type": "BlockBlob", "If-Match": "*"}, allowed=(201,))

    def assert_held():
        if provider_only:
            runtime.verify_provider_serialization(plan["context"]["provider_serialization"])
            return
        require(receipt["leases"], "physical-leases-not-held")
        for scope, lease in receipt["leases"].items():
            runtime.blob("PUT", "locks/" + hashlib.sha256(scope.lower().encode()).hexdigest() + ".lock",
                         headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease},
                         query="?comp=lease", allowed=(200,))

    try:
        if not provider_only:
            runtime.blob("PUT", remote, data=receipt,
                         headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))
            claimed = True
        for scope in ([] if provider_only else plan["lock_scopes"]):
            blob = "locks/" + hashlib.sha256(scope.lower().encode()).hexdigest() + ".lock"
            runtime.blob("PUT", blob, data=b"", headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"},
                         allowed=(201, 409, 412))
            lease = str(uuid4())
            receipt["leases"][scope] = lease
            persist()  # Persist proposed lease before a potentially lost acquisition response.
            runtime.blob("PUT", blob, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                         "x-ms-proposed-lease-id": lease}, query="?comp=lease", allowed=(201,))
        assert_held()
        runtime.read_only = True
        locked = prepare(source_root=plan["source"]["root"], consumer_root=plan["consumer_root"],
                         scope=plan["scope"], bootstrap_config=plan["bootstrap_config"],
                         expected_revision=plan["expected_revision"], context=plan["context"], runtime=runtime)
        require(locked["observations"] == plan["observations"] and locked["effects"] == plan["effects"],
                "prerequisites-changed-before-lock")
        runtime.read_only = False
        receipt["status"] = "running"
        persist()
        for index, effect in enumerate(plan["effects"]):
            assert_held()
            require(source_fingerprint(plan["source"]["root"]) == plan["source"], "privileged-source-changed")
            require(_read_target(ordinary(plan["consumer_root"]), plan["scope"])[1] == plan["consumer_hash"],
                    "consumer-register-changed")
            receipt["pending_effect"] = index
            receipt["changed"] = True
            persist()
            kind = effect["kind"]
            if kind == "provider-register":
                _, _, current = runtime.arm("GET", effect["id"], effect["api"])
                require(current.get("registrationState") == "NotRegistered", "resource-provider-state-changed")
                runtime.arm("POST", effect["id"] + "/register", effect["api"], allowed=(200, 202))
                for attempt in range(120):
                    assert_held()
                    _, _, current = runtime.arm("GET", effect["id"], effect["api"])
                    if current.get("registrationState") == "Registered":
                        break
                    require(current.get("registrationState") == "Registering", "resource-provider-registration-failed")
                    sleep(10)
                require(current.get("registrationState") == "Registered", "resource-provider-registration-uncertain")
            elif kind == "arm-create":
                status, _, _ = runtime.arm("GET", effect["id"], effect["api"], allowed=(200, 404))
                require(status == 404, "resource-appeared-after-review:" + effect["id"])
                runtime.arm("PUT", effect["id"], effect["api"], data=effect["body"], allowed=(200, 201, 202))
                result = _wait(runtime, effect["id"], effect["api"], assert_held, sleep)
                require(_contains(result, effect["body"]), "created-resource-verification-failed:" + effect["id"])
            elif kind == "group-create":
                name = effect["body"]["displayName"]
                path = "groups?$filter=" + quote("displayName eq '" + name.replace("'", "''") + "'", safe="") + "&$select=id"
                require(runtime.graph("GET", path).get("value") == [], "entra-group-appeared-after-review")
                group = runtime.graph("POST", "groups", effect["body"], allowed=(201,))
                group_id = _guid(group.get("id"))
                receipt["bindings"]["team_group_id"] = group_id
                persist()
                require(runtime.graph("GET", "groups/" + group_id + "?$select=id,securityEnabled").get("securityEnabled") is True,
                        "created-entra-group-not-verified")
                members = runtime.graph("GET", "groups/" + group_id + "/members?$select=id")
                expected_member = effect["body"]["members@odata.bind"][0].rsplit("/", 1)[1]
                require(any(x.get("id") == expected_member for x in members.get("value", [])),
                        "created-entra-group-membership-not-verified")
            elif kind == "group-member-add":
                runtime.graph("POST", "groups/" + effect["group_id"] + "/members/$ref",
                              {"@odata.id": GRAPH + "v1.0/directoryObjects/" + effect["member_id"]}, allowed=(204,))
                members = runtime.graph("GET", "groups/" + effect["group_id"] + "/members?$select=id")
                require(any(x.get("id") == effect["member_id"] for x in members.get("value", [])),
                        "entra-membership-not-verified")
            elif kind == "first-party-app-create":
                app = effect["body"]["appId"]
                path = "servicePrincipals?$filter=" + quote("appId eq '" + app + "'", safe="") + "&$select=id,appId"
                require(runtime.graph("GET", path).get("value") == [], "first-party-app-appeared-after-review")
                value = runtime.graph("POST", "servicePrincipals", effect["body"], allowed=(201,))
                require(value.get("appId") == app, "created-first-party-app-not-verified")
                receipt["bindings"].setdefault("first_party_apps", {})[effect["name"]] = _guid(value.get("id"))
            elif kind == "gateway-route-append":
                require(GATEWAY_MANUAL_WRITER_WARNING in plan["warnings"],
                        "gateway-route-append-manual-writer-warning-required")
                body = _revalidate_gateway_route_review(
                    runtime, effect, coordination_mode=plan["bootstrap_config"].get("coordination_mode"),
                    manual_writer_warning=GATEWAY_MANUAL_WRITER_WARNING)
                # No If-Match: serialization is explicitly the operator's responsibility.
                runtime.arm("PUT", effect["id"], effect["api"], data=body, allowed=(200, 201, 202))
                result = _wait(runtime, effect["id"], effect["api"], assert_held, sleep)
                _gateway_route_scope(result, effect["id"], effect["vnet_id"])
                require(_gateway_writable_body(result) == body,
                        "gateway-route-append-post-verification-failed")
                receipt["bindings"]["network"]["gateway_route_append_verified"] = True
            elif kind == "vnet-dns":
                _, _, current = runtime.arm("GET", effect["id"], effect["api"])
                require(current.get("properties", {}).get("dhcpOptions", {}).get("dnsServers", []) == effect["before_dns"],
                        "vnet-dns-changed-after-review")
                body = {key: copy.deepcopy(current[key]) for key in ("location", "tags", "extendedLocation", "properties")
                        if key in current}
                body["properties"].pop("provisioningState", None)
                body["properties"]["dhcpOptions"] = {"dnsServers": effect["dns_servers"]}
                runtime.arm("PUT", effect["id"], effect["api"], data=body, allowed=(200, 201, 202))
                result = _wait(runtime, effect["id"], effect["api"], assert_held, sleep)
                require(result["properties"]["dhcpOptions"]["dnsServers"] == effect["dns_servers"],
                        "vnet-dns-write-not-verified")
            else:
                raise PrerequisiteError("unrecognized-reviewed-effect")
            receipt["effects_completed"].append(index)
            receipt.pop("pending_effect", None)
            persist()
        runtime.read_only = True
        verified = prepare(source_root=plan["source"]["root"], consumer_root=plan["consumer_root"],
                           scope=plan["scope"], bootstrap_config=plan["bootstrap_config"],
                           expected_revision=plan["expected_revision"], context=plan["context"], runtime=runtime)
        require(verified["can_execute"] and not verified["effects"], "post-prerequisite-state-not-verified")
        require(verified["bindings"]["team_group_id"] == receipt["bindings"]["team_group_id"],
                "post-prerequisite-group-id-changed")
        require(verified["bindings"].get("first_party_apps") == receipt["bindings"].get("first_party_apps"),
                "post-prerequisite-first-party-app-changed")
        if plan["context"].get("bootstrap_phase") == "minimum-foundation":
            receipt["bindings"].update(verified["bindings"])
        runtime.read_only = False
        receipt.update(status="succeeded", reconciliation_required=False, requires_downstream_review=True,
                       enrollment_required=True, runtime_binding_published=False,
                       verified_observations_hash=digest(verified["observations"]),
                       completed_stage="privileged-prerequisites")
        persist()
        for scope, lease in list(receipt["leases"].items())[::-1]:
            runtime.blob("PUT", "locks/" + hashlib.sha256(scope.lower().encode()).hexdigest() + ".lock",
                         headers={"x-ms-lease-action": "release", "x-ms-lease-id": lease},
                         query="?comp=lease", allowed=(200,))
            del receipt["leases"][scope]
            persist()
        return receipt
    except BaseException as exc:
        receipt["status"] = "uncertain"
        receipt["reconciliation_required"] = True
        receipt["error"] = getattr(exc, "code", "prerequisite-execution-interrupted")
        # Keep leases and proofs. A lost response is not permission to repeat a
        # Graph POST, ARM PUT, or bootstrap workflow.
        receipt["outputs"] = copy.deepcopy(receipt["bindings"])
        receipt["stage_results"] = [{"stage": "privileged-prerequisites", "status": "uncertain",
                                     "effects_completed": list(receipt["effects_completed"]),
                                     **({"pending_effect": receipt["pending_effect"]} if "pending_effect" in receipt else {})}]
        _persist(receipt_path, receipt)
        if claimed:
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
