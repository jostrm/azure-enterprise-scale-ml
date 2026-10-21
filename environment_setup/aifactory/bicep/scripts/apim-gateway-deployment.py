#!/usr/bin/env python3
"""Offline-first, explicitly approved AI Factory APIM Bicep deployment runner."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from apim_gateway_config import (
    GatewayError, canonical, endpoint, guid, ipv4_prefix, load_config, require, same_id,
)


SCRIPT_ROOT = Path(__file__).resolve().parent
BICEP_ROOT = SCRIPT_ROOT.parent
MODULE_ROOT = BICEP_ROOT / "esml-common" / "ai-gateway" / "apim"
OWNER_TAG = "aifactory-gateway-owner"
VERSIONS = {"apim": "2024-05-01", "network": "2024-05-01",
            "group": "2022-09-01", "backend": "2024-10-01", "zone": "2020-06-01"}
PHASE_TEMPLATES = {
    "network": "network-main.bicep", "service-bootstrap": "service-main.bicep",
    "service-lockdown": "service-main.bicep", "private-endpoint": "private-endpoint-main.bicep",
    "configuration": "main.bicep",
}


def value_hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_hash(data):
    """Hash source text independently of checkout line endings (Windows CRLF vs Linux agents)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def azure_error_code(stdout, stderr):
    """Read only the CLI error envelope, never codes embedded in a service message."""
    codes = []
    for stream in (stderr, stdout):
        text = (stream or "").strip()
        if re.fullmatch(r"(?:ERROR:\s*)?(Forbidden|Unauthorized)", text):
            codes.append(text.removeprefix("ERROR:").strip())
            continue
        header = re.match(r"^(?:ERROR:\s*)?\(([A-Za-z][A-Za-z0-9]+)\)(?:\s|$)", text)
        if header:
            codes.append(header[1])
            continue
        # az rest uses: ERROR: Not Found({"error":{"code":"ResourceNotFound",...}})
        wrapper = re.fullmatch(
            r"(?:ERROR:\s*)?(Not Found|Forbidden|Unauthorized|Too Many Requests|"
            r"Service Unavailable|Internal Server Error|Gateway Timeout|Bad Request)\s*\((.*)\)",
            text, re.S)
        if wrapper and wrapper[1] in {"Forbidden", "Unauthorized"}:
            codes.append(wrapper[1])
        payload = wrapper[2] if wrapper else text
        if payload.startswith("ERROR:"):
            payload = payload[6:].strip()
        try:
            parsed = json.loads(payload)
        except (ValueError, TypeError):
            continue
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            codes.append(error["code"])
    mapping = {
        "auth-denied": {"authorizationfailed", "authenticationfailed", "invalidauthenticationtoken",
                        "expiredauthenticationtoken", "forbidden", "unauthorized"},
        "policy-denied": {"requestdisallowedbypolicy", "denyassignmentauthorizationfailed"},
        "read-transient": {"toomanyrequests", "serviceunavailable", "internalservererror", "gatewaytimeout", "429", "503"},
        "not-found": {"resourcenotfound", "resourcegroupnotfound"},
    }
    lowered = {code.lower() for code in codes}
    for category, known in mapping.items():
        if lowered & known:
            # Missing is safe only when every structured code agrees it is a resource absence.
            if category != "not-found" or lowered <= known:
                return category
    return "cli-failed"


def under(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def source_manifest(module_root=MODULE_ROOT):
    """Bind every local module/load dependency, rejecting opaque remote modules."""
    root = Path(module_root).resolve()
    boundary = BICEP_ROOT if under(root, BICEP_ROOT) else root
    paths = list(root.rglob("*.bicep")) + list(root.rglob("*.xml"))
    require((root / "main.bicep").is_file(), "source-invalid", "AI Factory APIM main.bicep is missing.")
    result = {}
    while paths:
        path = paths.pop().resolve()
        require(under(path, boundary), "source-invalid", "Template dependencies must remain in the maintained Bicep source tree.")
        name = path.relative_to(boundary).as_posix()
        if name in result:
            continue
        try:
            data = path.read_bytes()
            content = data.decode("utf-8")
        except (OSError, UnicodeError):
            raise GatewayError("source-invalid", "Cannot read a transitive Bicep/policy dependency.") from None
        result[name] = text_hash(data)
        if path.suffix == ".bicep":
            refs = re.findall(r"\bmodule\s+\w+\s+'([^']+)'", content)
            refs += re.findall(r"\bload(?:TextContent|JsonContent|YamlContent|FileAsBase64)\s*\(\s*'([^']+)'", content)
            refs += re.findall(r"\bimport\s+.+?\s+from\s+'([^']+)'", content)
            for ref in refs:
                require(not re.match(r"^(?:br|ts):", ref) and "${" not in ref and not Path(ref).is_absolute(),
                        "source-invalid", "Only reviewable local static Bicep dependencies are supported.")
                paths.append(path.parent / ref)
    for script in (Path(__file__), SCRIPT_ROOT / "apim_gateway_config.py"):
        result["runner/" + script.name] = text_hash(script.read_bytes())
    return dict(sorted(result.items()))


def service_id(c):
    return f"/subscriptions/{c['subscriptionId']}/resourceGroups/{c['resourceGroup']}/providers/Microsoft.ApiManagement/service/{c['serviceName']}"


def review_plan(c, module_root=MODULE_ROOT):
    sources = source_manifest(module_root)
    managed = c["serviceMode"] == "managed"
    if managed:
        require(all((Path(module_root) / name).is_file() for name in set(PHASE_TEMPLATES.values())),
                "source-invalid", "Managed APIM provisioning templates are missing.")
    digest = hashlib.sha256(canonical({"config": c, "sources": sources}).encode()).hexdigest()
    return {
        "schemaVersion": 1, "action": "plan", "offline": True, "armPreviewExecuted": False,
        "planDigest": digest, "approvalMeaning": "Content equality only; pipeline environment approval and exclusive writer governance are required.",
        "target": {key: c[key] for key in ("environment", "tenantId", "subscriptionId", "resourceGroup", "location", "serviceName")},
        "config": c, "sourceHashes": sources,
        "resourceChanges": (["Dedicated integration subnet only when requested and absent", "Owned StandardV2 service",
                             "Gateway private endpoint", "Existing private DNS zone group only in existingZone mode"] if managed else [])
                           + ["APIM API, policy, backend members and pool"]
                           + (["Cognitive Services OpenAI User assignments on declared backend accounts"]
                              if c["api"]["assignOpenAIUserRole"] else []),
        "transientExposure": {"possible": managed, "firstCreateRequiresExplicitApproval": managed,
                              "description": "Separate reviewed apply runs: public Enabled without APIs, then approved PE, then Disabled, then configuration (optional subnet phase first). Public exposure persists between runs, potentially indefinitely; operators must reconcile any blocked phase." if managed
                              else "Existing service SKU and network posture remain unchanged."},
        "phases": (["inventory", "network-if-absent", "service-bootstrap-if-absent", "private-endpoint",
                    "service-lockdown", "verify-private-and-identity", "configuration"] if managed
                   else ["inventory-existing-service", "configuration"]),
        "estimatedPricing": {"isQuote": False, "amount": None, "currency": None,
                             "billables": ["APIM capacity", "Private Link endpoint/data", "DNS when applicable", "Azure OpenAI usage"],
                             "instruction": "Estimate using region, SKU, capacity, traffic and current Azure pricing before approval."},
        "roles": ["Read target subscription/resource group, APIM, VNet/subnets, NSG, route table and backend accounts",
                  "Subscription deployment and relevant resource-group resource write permissions for apply only"]
                 + (["Role assignment write on each declared backend"] if c["api"]["assignOpenAIUserRole"] else []),
        "network": c.get("network", {"mode": "unchanged-existing"}),
        "rollback": "No automated deletion or write retries. Inspect the phase receipt and Azure deployment operations, reconcile partial state, produce/review a fresh plan. Never re-enable an existing service.",
        "knownLimitations": ["Offline plan is not ARM compilation, live inventory, quota, policy or pricing validation.",
                             "Each what-if previews only the next phase. Apply requires both planDigest and that phase's previewDigest and performs at most one deployment; repeat review for every later phase.",
                             "Private DNS/routing and end-to-end reachability require operator validation; no model traffic is sent.",
                             "Public Azure only; managed StandardV2 only; existing resource group/VNet/NSG; same-VNet IPv4 networking.",
                             "Approval digest is not cryptographic authorization or a concurrency lock; use one externally serialized approved writer."],
    }


class Artifacts:
    def __init__(self, directory, config_path=None, module_root=MODULE_ROOT):
        self.root = Path(directory).resolve()
        for protected in (Path(module_root).resolve(), BICEP_ROOT):
            require(not under(self.root, protected), "output-invalid", "Output directory must be outside maintained module/script sources.")
        if config_path:
            require(not under(self.root, Path(config_path).resolve().parent), "output-invalid",
                    "Output directory must be outside the consumer configuration directory.")
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, name, value):
        target = self.root / name
        require(not target.is_symlink(), "output-invalid", "Artifact destinations cannot be symbolic links.")
        intermediate = self.root / (name + "." + uuid.uuid4().hex + ".pending")
        try:
            fd = os.open(intermediate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(intermediate, target)
        finally:
            if intermediate.exists():
                intermediate.unlink()
        return target


class AzureCLI:
    """Inject this interface (read/invoke) for all tests; no Python HTTP write path."""

    def __init__(self, run=None, sleep=time.sleep, platform=None, which=shutil.which):
        self.run = run or subprocess.run
        self.sleep = sleep
        self.platform = platform or sys.platform
        self.which = which

    def command(self, args):
        executable = (self.which("az.cmd") or self.which("az")) if self.platform == "win32" else self.which("az")
        require(executable is not None, "cli-unavailable", "Azure CLI is required for what-if/apply only.")
        path = Path(executable)
        if self.platform == "win32" and path.suffix.lower() in {".cmd", ".bat"}:
            python = path.parent.parent / "python.exe"
            require(python.is_file(), "cli-unavailable", "Azure CLI bundled Python is missing; batch-shell fallback is forbidden.")
            return [str(python), "-IBm", "azure.cli", *args]
        return [str(path), *args]

    def invoke(self, args, timeout=300):
        try:
            result = self.run(self.command(list(args)), shell=False, check=False,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise GatewayError("cli-timeout", "Azure CLI timed out. Inspect the operation before retrying; deployment writes are never retried.") from None
        except OSError:
            raise GatewayError("cli-unavailable", "Cannot start Azure CLI.") from None
        if result.returncode:
            # Classify known error codes, but never retain/log stdout, stderr or error bodies.
            code = azure_error_code(result.stdout, result.stderr)
            raise GatewayError(code, "Azure operation failed; inspect authorized Azure deployment diagnostics. Raw CLI output is intentionally suppressed.")
        try:
            value = json.loads(result.stdout or "{}")
        except ValueError:
            raise GatewayError("cli-invalid-response", "Azure CLI did not return valid JSON; raw output is suppressed.") from None
        require(isinstance(value, dict), "cli-invalid-response", "Azure CLI response must be an object.")
        return value

    def read(self, args, allow_missing=False):
        require(list(args[:2]) in (["rest", "--method"], ["account", "show"]), "read-invalid", "Only Azure GET/account reads may retry.")
        if args[0] == "rest":
            require(len(args) > 2 and args[2].lower() == "get", "read-invalid", "Only GET operations may retry.")
        for attempt in range(3):
            try:
                return self.invoke(args, timeout=90)
            except GatewayError as exc:
                if exc.code == "not-found" and allow_missing:
                    return None
                if exc.code != "read-transient" or attempt == 2:
                    raise
                self.sleep(2 ** attempt)


class Deployment:
    def __init__(self, config, artifacts, cli=None, module_root=MODULE_ROOT, sleep=time.sleep, poll_attempts=12):
        self.c, self.artifacts = config, artifacts
        self.cli = cli if cli is not None else AzureCLI()
        self.module_root = Path(module_root).resolve()
        self.sleep, self.poll_attempts = sleep, poll_attempts
        self.plan = review_plan(config, self.module_root)
        self.receipt = {"schemaVersion": 1, "planDigest": self.plan["planDigest"], "target": self.plan["target"],
                        "status": "not-started", "phases": [], "resourceWritesAttempted": False,
                        "publicBootstrapMayBeActive": False, "automaticCleanup": False}
        self.expected_digest = self.plan["planDigest"]
        self.current_phase = "inventory"
        self.service = None
        self.network_missing = False
        self.network_created = False
        self.pe = None
        self.zone_group_missing = False

    def save(self):
        self.artifacts.write("receipt.json", self.receipt)

    def unchanged(self):
        require(review_plan(self.c, self.module_root)["planDigest"] == self.expected_digest,
                "approval-stale", "Configuration or transitive maintained source changed after plan approval.")

    def get(self, rid, kind, missing=False):
        result = self.cli.read(["rest", "--method", "get", "--url",
                                f"https://management.azure.com{rid}?api-version={VERSIONS[kind]}",
                                "--subscription", self.c["subscriptionId"], "--only-show-errors", "--output", "json"],
                               allow_missing=missing)
        if result is not None:
            require(same_id(result.get("id"), rid), "inventory-invalid", "Azure returned a different resource identity.")
        return result

    def account(self, subscription):
        account = self.cli.read(["account", "show", "--subscription", subscription, "--only-show-errors", "--output", "json"])
        require(same_id(account.get("id"), subscription) and same_id(account.get("tenantId"), self.c["tenantId"])
                and account.get("state") == "Enabled", "auth-target-mismatch",
                "Authenticated tenant/subscription is not the approved enabled target.")

    def properties(self, resource):
        require(isinstance(resource, dict) and isinstance(resource.get("properties"), dict),
                "inventory-invalid", "Azure resource properties are missing.")
        return resource["properties"]

    def location(self, resource):
        require(resource.get("location", "").replace(" ", "").lower() == self.c["location"],
                "network-invalid", "APIM and referenced regional network resources must have the selected location.")

    def identity(self, resource):
        identity = resource.get("identity") or {}
        require("systemassigned" in str(identity.get("type", "")).lower(), "identity-invalid",
                "APIM must have a system-assigned managed identity.")
        principal = guid(identity.get("principalId"), "observed APIM identity")
        if self.c["serviceMode"] == "managed":
            require(str(identity.get("type", "")).lower() == "systemassigned"
                    and not identity.get("userAssignedIdentities"), "identity-invalid",
                    "Managed service identity must be exactly SystemAssigned; additional identities cannot be removed by this lifecycle.")
        explicit = self.c["api"].get("managedIdentityPrincipalId")
        require(not explicit or same_id(principal, explicit), "identity-invalid",
                "Configured identity differs from the actual APIM system identity.")
        return principal

    def validate_service(self, resource, secure=False):
        self.location(resource)
        p = self.properties(resource)
        require(p.get("provisioningState") == "Succeeded", "service-not-ready", "APIM is not Succeeded; reconcile the existing operation before continuing.")
        sku = resource.get("sku", {})
        require(sku.get("name") == self.c["sku"], "service-mismatch", "APIM SKU differs; use a separately reviewed managed lifecycle, not an imperative SKU patch.")
        require(sku.get("capacity") == self.c["skuCapacity"], "service-mismatch",
                "Existing APIM capacity differs; use a separately reviewed managed lifecycle. This runner never resizes.")
        if self.c["serviceMode"] == "managed":
            require(resource.get("tags", {}).get(OWNER_TAG) == self.c["ownershipId"], "ownership-collision",
                    "Existing APIM ownership tag does not match; broad adoption is forbidden.")
            require(p.get("publisherName") == self.c["publisherName"] and p.get("publisherEmail") == self.c["publisherEmail"],
                    "service-mismatch", "Existing managed publisher properties differ; reconcile through a separately reviewed lifecycle.")
            require(p.get("virtualNetworkType") == "External", "service-mismatch",
                    "Managed StandardV2 requires the reviewed External VNet integration mode.")
            require(p.get("publicNetworkAccess") in {"Enabled", "Disabled"}, "service-mismatch",
                    "Managed public network access is unknown; reconcile before continuing.")
        if "network" in self.c:
            require(same_id((p.get("virtualNetworkConfiguration") or {}).get("subnetResourceId"),
                            self.c["network"]["integrationSubnetId"]), "service-mismatch",
                    "Existing APIM integration subnet differs; no network migration is permitted.")
        if secure:
            require(p.get("publicNetworkAccess") == "Disabled", "service-not-private", "APIM public network access is not Disabled; configuration is blocked.")
        return self.identity(resource)

    def validate_lockdown_baseline(self, resource):
        """A service PUT is safe only for the narrow bootstrap schema we own."""
        p = self.properties(resource)
        require(p.get("developerPortalStatus") == "Disabled", "service-customized",
                "Managed lockdown cannot overwrite modified developer portal settings.")
        hostnames = p.get("hostnameConfigurations") or []
        require(isinstance(hostnames, list), "service-customized", "Managed hostname configuration is uninspectable.")
        for hostname in hostnames:
            require(isinstance(hostname, dict)
                    and hostname.get("type") == "Proxy"
                    and same_id(hostname.get("hostName"), self.c["serviceName"] + ".azure-api.net")
                    and hostname.get("certificateSource") in {None, "BuiltIn"}
                    and not any(hostname.get(key) for key in
                                ("encodedCertificate", "certificatePassword", "keyVaultId", "identityClientId",
                                 "negotiateClientCertificate"))
                    and set(hostname) <= {"type", "hostName", "certificateSource", "certificate",
                                         "encodedCertificate", "certificatePassword", "keyVaultId",
                                         "identityClientId", "negotiateClientCertificate", "defaultSslBinding",
                                         "certificateStatus"},
                    "service-customized", "Managed lockdown cannot replace custom hostname or certificate configuration.")
        require(len(hostnames) <= 1, "service-customized",
                "Managed lockdown cannot replace additional hostname configuration.")
        readonly = {
            "provisioningState", "createdAtUtc", "targetProvisioningState", "gatewayUrl", "gatewayRegionalUrl",
            "portalUrl", "managementApiUrl", "scmUrl", "developerPortalUrl", "publicIPAddresses",
            "privateIPAddresses", "outboundPublicIPAddresses", "platformVersion", "privateEndpointConnections",
        }
        declared = {"publisherName", "publisherEmail", "developerPortalStatus", "publicNetworkAccess",
                    "virtualNetworkType", "virtualNetworkConfiguration", "hostnameConfigurations"}
        defaults = {"notificationSenderEmail": "apimgmt-noreply@mail.windowsazure.com",
                    "natGatewayState": "Disabled", "legacyPortalStatus": "Disabled",
                    "apiVersionConstraint": {"minApiVersion": None}}
        for key, value in p.items():
            if key in readonly | declared:
                continue
            require(value in (None, False, "", [], {}) or (key in defaults and value == defaults[key]),
                    "service-customized",
                    "Managed lockdown refuses unsupported service settings; use a separately reviewed preserving lifecycle.")
        vnet = p.get("virtualNetworkConfiguration") or {}
        require(not any(value for key, value in vnet.items() if key not in {"subnetResourceId", "vnetid", "subnetname"}),
                "service-customized", "Managed lockdown refuses additional virtual network settings.")
        require(not resource.get("zones"), "service-customized", "Managed lockdown cannot reset availability zones.")
        desired_tags = dict(self.c["tags"], **{OWNER_TAG: self.c["ownershipId"]})
        require({k.lower(): v for k, v in resource.get("tags", {}).items()}
                == {k.lower(): v for k, v in desired_tags.items()},
                "service-customized", "Managed lockdown cannot reset undeclared service tags.")

    def subnet_prefixes(self, subnet, integration=False):
        p = self.properties(subnet)
        values = p.get("addressPrefixes") or ([p["addressPrefix"]] if p.get("addressPrefix") else [])
        require(isinstance(values, list) and bool(values), "network-invalid", "Subnet has no address prefixes.")
        if integration:
            require(len(values) == 1, "network-invalid", "Integration requires a single IPv4 subnet prefix.")
        return [ipv4_prefix(value, integration=integration) for value in values]

    def validate_integration(self, subnet):
        n = self.c["network"]
        prefix = self.subnet_prefixes(subnet, integration=True)[0]
        if n.get("integrationSubnetPrefix"):
            require(prefix == ipv4_prefix(n["integrationSubnetPrefix"], integration=True), "network-invalid", "Existing integration subnet prefix differs.")
        p = self.properties(subnet)
        require(same_id((p.get("networkSecurityGroup") or {}).get("id"), n["networkSecurityGroupId"]),
                "network-invalid", "Integration subnet must use exactly the approved existing NSG.")
        route = (p.get("routeTable") or {}).get("id", "")
        require(same_id(route, n.get("routeTableId", "")), "network-invalid", "Integration subnet route table differs.")
        delegations = p.get("delegations") or []
        require(len(delegations) == 1 and delegations[0].get("properties", {}).get("serviceName", "").lower() == "microsoft.web/serverfarms",
                "network-invalid", "Integration subnet must be delegated only to Microsoft.Web/serverFarms.")
        require(not p.get("ipConfigurations") and not p.get("privateEndpoints"), "network-occupied",
                "Integration subnet is occupied/shared; the runner will not mutate it.")
        for key in ("serviceAssociationLinks", "resourceNavigationLinks"):
            for link in p.get(key) or []:
                require(self.service is not None and same_id(link.get("properties", {}).get("link"), service_id(self.c)),
                        "network-occupied", "Integration subnet links bind another or unknown service.")

    def pe_id(self):
        return (f"/subscriptions/{self.c['subscriptionId']}/resourceGroups/{self.c['resourceGroup']}"
                f"/providers/Microsoft.Network/privateEndpoints/{self.c['network']['privateEndpointName']}")

    def validate_pe(self, pe, approved=False):
        n = self.c["network"]
        self.location(pe)
        require(pe.get("tags", {}).get(OWNER_TAG) == self.c["ownershipId"], "endpoint-collision",
                "Private endpoint ownership does not match; adoption is forbidden.")
        p = self.properties(pe)
        require(same_id((p.get("subnet") or {}).get("id"), n["privateEndpointSubnetId"]), "endpoint-collision", "Private endpoint subnet differs.")
        connections = (p.get("privateLinkServiceConnections") or []) + (p.get("manualPrivateLinkServiceConnections") or [])
        require(len(connections) == 1, "endpoint-collision", "Private endpoint must have exactly the declared gateway connection.")
        connection = connections[0].get("properties") or {}
        require(same_id(connection.get("privateLinkServiceId"), service_id(self.c))
                and [str(group).lower() for group in connection.get("groupIds", [])] == ["gateway"],
                "endpoint-collision", "Private endpoint targets a different service or group.")
        if approved:
            require(p.get("provisioningState") == "Succeeded"
                    and connection.get("privateLinkServiceConnectionState", {}).get("status") == "Approved",
                    "endpoint-not-approved", "Private endpoint is not Approved/Succeeded. Obtain network/governance approval, reconcile public exposure, then re-plan. No automatic approval or deletion is performed.")

    def inventory_zone_groups(self):
        self.zone_group_missing = False
        if self.c["network"]["privateDnsMode"] != "existingZone":
            return  # Policy owns all associations; never read/adopt/write its child resources.
        self.zone_group_missing = True
        if self.pe is None:
            return
        collection = self.cli.read(["rest", "--method", "get", "--url",
                                    f"https://management.azure.com{self.pe_id()}/privateDnsZoneGroups?api-version={VERSIONS['network']}",
                                    "--subscription", self.c["subscriptionId"], "--only-show-errors", "--output", "json"])
        require(isinstance(collection.get("value"), list) and not collection.get("nextLink"),
                "dns-collision", "Complete private DNS zone group inventory is required.")
        groups = collection["value"]
        require(len(groups) <= 1, "dns-collision", "Multiple private DNS zone groups are ambiguous; no adoption or overwrite is allowed.")
        if not groups:
            return
        group = groups[0]
        require(isinstance(group, dict) and same_id(group.get("id"), self.pe_id() + "/privateDnsZoneGroups/default"),
                "dns-collision", "An existing private DNS zone group conflicts with the requested association.")
        p = self.properties(group)
        zones = p.get("privateDnsZoneConfigs")
        require(isinstance(zones, list) and len(zones) == 1 and isinstance(zones[0], dict)
                and zones[0].get("name") == "privatelink.azure-api.net"
                and same_id((zones[0].get("properties") or {}).get("privateDnsZoneId"),
                            self.c["network"]["privateDnsZoneId"])
                and p.get("provisioningState") == "Succeeded",
                "dns-collision", "The existing private DNS zone group is not the exact succeeded desired association; no overwrite is allowed.")
        self.zone_group_missing = False

    def inventory_network(self):
        n = self.c["network"]
        vnet_id = re.split("/subnets/", n["integrationSubnetId"], flags=re.I)[0]
        vnet = self.get(vnet_id, "network")
        self.location(vnet)
        self.location(self.get(n["networkSecurityGroupId"], "network"))
        if n.get("routeTableId"):
            self.location(self.get(n["routeTableId"], "network"))
        if n.get("privateDnsZoneId"):
            self.get(n["privateDnsZoneId"], "zone")
        pe_subnet = self.get(n["privateEndpointSubnetId"], "network")
        self.subnet_prefixes(pe_subnet)
        pe_properties = self.properties(pe_subnet)
        require(not any(pe_properties.get(key) for key in ("delegations", "serviceAssociationLinks", "resourceNavigationLinks")),
                "network-invalid", "Private endpoints require an existing undelegated subnet without service bindings.")
        integration = self.get(n["integrationSubnetId"], "network", missing=True)
        self.network_missing = integration is None
        if integration is None:
            require(n["createIntegrationSubnet"] and self.c["serviceMode"] == "managed", "network-missing",
                    "Integration subnet is missing; explicit managed createIntegrationSubnet approval is required.")
            prefix = ipv4_prefix(n["integrationSubnetPrefix"], integration=True)
            address_space = self.properties(vnet).get("addressSpace", {}).get("addressPrefixes", [])
            try:
                networks = [ipaddress.ip_network(value, strict=True) for value in address_space]
            except ValueError:
                raise GatewayError("network-invalid", "VNet address space could not be validated.") from None
            require(any(network.version == 4 and prefix.subnet_of(network) for network in networks),
                    "network-invalid", "New integration subnet must be wholly inside existing VNet address space.")
            # List the subnet collection; do not assume embedded VNet subnet inventory is complete.
            collection = self.cli.read(["rest", "--method", "get", "--url",
                                        f"https://management.azure.com{vnet_id}/subnets?api-version={VERSIONS['network']}",
                                        "--subscription", self.c["subscriptionId"], "--only-show-errors", "--output", "json"])
            require(isinstance(collection.get("value"), list) and not collection.get("nextLink"),
                    "network-invalid", "Complete subnet inventory is required; paginated/unknown inventory is unsupported.")
            for subnet in collection["value"]:
                require(not same_id(subnet.get("id"), n["integrationSubnetId"]), "network-collision", "Integration subnet appeared during inventory; re-plan.")
                for other in self.subnet_prefixes(subnet):
                    require(not prefix.overlaps(other), "network-overlap", "New integration prefix overlaps an existing subnet.")
        else:
            require(not n["createIntegrationSubnet"] or self.service is not None or self.network_created, "network-collision",
                    "Requested new subnet already exists. Review its ownership and re-plan with createIntegrationSubnet=false.")
            self.validate_integration(integration)
        if self.c["serviceMode"] == "managed":
            self.pe = self.get(self.pe_id(), "network", missing=True)
            if self.pe:
                self.validate_pe(self.pe)
            self.inventory_zone_groups()

    def inventory(self):
        self.account(self.c["subscriptionId"])
        group = f"/subscriptions/{self.c['subscriptionId']}/resourceGroups/{self.c['resourceGroup']}"
        self.get(group, "group")
        self.service = self.get(service_id(self.c), "apim", missing=True)
        require(self.service is not None or self.c["serviceMode"] == "managed", "service-missing",
                "Existing APIM service is missing. Existing mode never provisions automatically; supply a reviewed managed configuration.")
        if self.service:
            self.receipt["publicBootstrapMayBeActive"] = (
                self.c["serviceMode"] == "managed" and self.properties(self.service).get("publicNetworkAccess") != "Disabled")
            self.validate_service(self.service)
            if self.c["serviceMode"] == "managed" and self.properties(self.service)["publicNetworkAccess"] == "Enabled":
                self.validate_lockdown_baseline(self.service)
        else:
            require(not self.c["api"].get("managedIdentityPrincipalId"), "identity-invalid",
                    "A new service cannot preserve a preselected system identity. Remove the explicit principal ID and review a new plan.")
        subscriptions = {self.c["subscriptionId"].lower()}
        for backend in self.c["api"]["azureOpenAIBackends"]:
            subscription = backend["resourceId"].split("/")[2]
            if subscription.lower() not in subscriptions:
                self.account(subscription)
                subscriptions.add(subscription.lower())
            actual = self.get(backend["resourceId"], "backend")
            kind = str(actual.get("kind", "")).lower()
            properties = self.properties(actual)
            require(kind in {"openai", "aiservices"}, "backend-mismatch",
                    "Backend must be an Azure OpenAI or Foundry AI Services account.")
            if kind == "aiservices":
                endpoints = properties.get("endpoints")
                require(isinstance(endpoints, dict), "backend-mismatch",
                        "Foundry account does not report an OpenAI endpoint; no hostname is inferred.")
                reported_endpoint = endpoints.get("OpenAI Language Model Instance API")
            else:
                reported_endpoint = properties.get("endpoint")
            require(endpoint(reported_endpoint) == backend["endpoint"],
                    "backend-mismatch", "Declared Azure OpenAI resource and endpoint do not match live inventory.")
        if "network" in self.c:
            self.inventory_network()
        self.save()

    def prewrite(self, phase, params):
        self.inventory()
        if phase == "service-bootstrap":
            require(self.service is None, "service-race",
                    "APIM appeared after planning. Refusing to enable an existing service; re-plan.")
        next_phase, _ = self.resolve_phase()
        require(next_phase == phase, "approval-stale", "The next required phase changed after preview; review a new preview.")
        require(self.parameters(phase, "Enabled" if phase == "service-bootstrap" else "Disabled") == params,
                "approval-stale", "Phase parameters or APIM system identity changed after preview; review a new preview.")
        self.current_phase = phase

    def parameters(self, phase, public_access="Disabled"):
        c, n = self.c, self.c.get("network", {})
        common = {"apimServiceName": c["serviceName"], "apimResourceGroupName": c["resourceGroup"],
                  "apimSubscriptionId": c["subscriptionId"]}
        if phase == "network":
            return {key: n.get(key, "") for key in ("integrationSubnetId", "integrationSubnetPrefix", "networkSecurityGroupId", "routeTableId")} | {"location": c["location"]}
        if phase.startswith("service-"):
            return common | {key: c[key] for key in ("location", "publisherName", "publisherEmail", "skuCapacity", "ownershipId", "tags")} | {
                "integrationSubnetId": n["integrationSubnetId"], "publicNetworkAccess": public_access}
        if phase == "private-endpoint":
            return common | {key: c[key] for key in ("location", "tags", "ownershipId")} | {
                key: n.get(key, "") for key in ("privateEndpointSubnetId", "privateEndpointName", "privateDnsMode", "privateDnsZoneId")}
        a = c["api"]
        return common | {key: a[key] for key in ("apiId", "apiPath", "backendPoolName", "aggregateTokensPerMinute",
                                               "callerTokensPerMinute", "retryCount", "assignOpenAIUserRole", "azureOpenAIBackends")} | {
            "apimManagedIdentityPrincipalId": self.identity(self.service)}

    def preview_value(self, value, depth=0):
        require(depth <= 64, "preview-unsafe", "ARM preview structure is too deep to inspect safely.")
        if isinstance(value, dict):
            require(all(isinstance(key, str) for key in value), "preview-unsafe", "ARM preview has invalid property names.")
            properties = [{"name": self.preview_path(key), "nameHash": value_hash(key),
                           "value": self.preview_value(item, depth + 1)}
                          for key, item in sorted(value.items())]
            kind, children = "object", {"properties": properties}
        elif isinstance(value, list):
            kind, children = "array", {"items": [self.preview_value(item, depth + 1) for item in value]}
        else:
            require(value is None or type(value) in {str, bool, int, float}, "preview-unsafe",
                    "ARM preview contains an unsupported value type.")
            require(not isinstance(value, float) or (value == value and abs(value) != float("inf")),
                    "preview-unsafe", "ARM preview contains an invalid number.")
            kind = "null" if value is None else {str: "string", bool: "boolean", int: "number", float: "number"}[type(value)]
            children = {}
        return {"type": kind, "sha256": value_hash(value), **children}

    def preview_path(self, path):
        require(isinstance(path, str), "preview-unsafe", "ARM preview property path is invalid.")
        return path if re.fullmatch(r"[A-Za-z0-9_.$\[\]()-]{1,512}", path) else "sha256:" + value_hash(path)

    def preview_delta(self, delta, depth=0):
        require(depth <= 64 and isinstance(delta, list), "preview-unsafe", "ARM property changes cannot be inspected safely.")
        result = []
        for item in delta:
            require(isinstance(item, dict) and set(item) <= {"path", "propertyChangeType", "before", "after", "children"},
                    "preview-unsafe", "ARM preview has unsupported property change structure.")
            kind = item.get("propertyChangeType")
            require(isinstance(kind, str) and kind in {"Create", "Modify", "Array", "NoEffect"}, "preview-unsafe",
                    "ARM preview includes destructive property deletion or unsupported property changes.")
            require(isinstance(item.get("path"), str) and bool(item["path"]), "preview-unsafe", "ARM property change path is missing.")
            require("before" in item or "after" in item or bool(item.get("children")), "preview-unsafe",
                    "ARM property change values are unavailable; review cannot authorize an opaque change.")
            if kind == "Create":
                require("after" in item or bool(item.get("children")), "preview-unsafe", "ARM property creation is uninspectable.")
            if kind in {"Modify", "Array"}:
                require(("before" in item and "after" in item) or bool(item.get("children")), "preview-unsafe",
                        "ARM property modification is uninspectable.")
                if isinstance(item.get("before"), dict) and isinstance(item.get("after"), dict):
                    require(set(item["before"]) <= set(item["after"]), "preview-unsafe",
                            "ARM property modification includes destructive property deletion.")
            change = {"path": self.preview_path(item["path"]), "pathHash": value_hash(item["path"]),
                      "propertyChangeType": kind}
            for key in ("before", "after"):
                if key in item:
                    change[key] = self.preview_value(item[key])
            if "children" in item:
                change["children"] = None if item["children"] is None else self.preview_delta(item["children"], depth + 1)
            result.append(change)
        return sorted(result, key=canonical)

    def permitted_change(self, rid, phase):
        c, a = self.c, self.c["api"]
        service = service_id(c).lower()
        allowed = set()
        group = f"/subscriptions/{c['subscriptionId']}/resourceGroups/{c['resourceGroup']}".lower()
        deployment_groups = {group}
        if phase == "network":
            allowed.add(c["network"]["integrationSubnetId"].lower())
            deployment_groups.add(c["network"]["integrationSubnetId"].lower().split("/providers/")[0])
        elif phase.startswith("service-"):
            allowed.add(service)
        elif phase == "private-endpoint":
            allowed.add(self.pe_id().lower())
            if c["network"]["privateDnsMode"] == "existingZone":
                allowed.add(self.pe_id().lower() + "/privatednszonegroups/default")
        else:
            api = service + "/apis/" + a["apiId"].lower()
            allowed.update({api, api + "/policies/policy"})
            allowed.update(api + "/operations/" + name for name in ("chat-completions", "responses", "v1-responses"))
            allowed.update(service + "/backends/" + name.lower()
                           for name in [a["backendPoolName"], *[b["name"] for b in a["azureOpenAIBackends"]]])
            if a["assignOpenAIUserRole"]:
                for backend in a["azureOpenAIBackends"]:
                    base = backend["resourceId"].lower()
                    deployment_groups.add(base.split("/providers/")[0])
                    if re.fullmatch(re.escape(base) + r"/providers/microsoft.authorization/roleassignments/[0-9a-f-]{36}", rid):
                        return True
        return rid in allowed or any(re.fullmatch(re.escape(scope) + r"/providers/microsoft.resources/deployments/[a-z0-9_.()-]+", rid)
                                     for scope in deployment_groups)

    def preview_summary(self, result, phase, params):
        require(result.get("status") == "Succeeded" and isinstance(result.get("changes"), list),
                "preview-incomplete", "ARM what-if did not complete successfully; no deployment is allowed.")
        counts = {}
        changes = []
        resource_ids = set()
        for change in result["changes"]:
            require(isinstance(change, dict) and set(change) <= {"resourceId", "changeType", "before", "after", "delta", "unsupportedReason"}
                    and not change.get("unsupportedReason"),
                    "preview-unsafe", "ARM preview includes unsupported or uninspectable change structure.")
            kind = change.get("changeType")
            require(isinstance(kind, str) and kind in {"Create", "Modify", "NoChange", "Ignore"}, "preview-unsafe",
                    "ARM preview includes deletion, unsupported or unresolved changes; operator review is required.")
            counts[kind] = counts.get(kind, 0) + 1
            rid = change.get("resourceId", "")
            require(isinstance(rid, str) and re.fullmatch(r"/subscriptions/[A-Za-z0-9/_.()-]+", rid)
                    and all(segment not in {"", ".", ".."} for segment in rid.split("/")[1:]),
                    "preview-unsafe", "ARM preview contains an invalid resource identity.")
            require(rid.lower() not in resource_ids, "preview-unsafe", "ARM preview contains ambiguous duplicate resource changes.")
            resource_ids.add(rid.lower())
            require(kind in {"NoChange", "Ignore"} or self.permitted_change(rid.lower(), phase),
                    "preview-unsafe", "ARM preview attempts to modify a resource outside this phase's declared scope.")
            require(kind != "Create" or isinstance(change.get("after"), dict), "preview-unsafe",
                    "ARM create preview lacks inspectable resource properties.")
            require(kind != "Modify" or bool(change.get("delta"))
                    or ("before" in change and "after" in change and change["before"] == change["after"]),
                    "preview-unsafe", "ARM modify preview lacks inspectable property changes.")
            normalized = {"resourceId": rid.lower(), "changeType": kind}
            for key in ("before", "after"):
                if key in change:
                    normalized[key] = self.preview_value(change[key])
            if "delta" in change:
                normalized["delta"] = None if change["delta"] is None else self.preview_delta(change["delta"])
            if "unsupportedReason" in change:
                normalized["unsupportedReason"] = self.preview_value(change["unsupportedReason"])
            require(kind not in {"NoChange", "Ignore"} or not change.get("delta"), "preview-unsafe",
                    "ARM preview reports contradictory unchanged property deltas.")
            changes.append(normalized)
        summary = {"status": "Succeeded", "planDigest": self.expected_digest, "phase": phase,
                   "parametersHash": value_hash(params), "parameters": self.preview_value(params),
                   "counts": counts, "changes": sorted(changes, key=canonical),
                   "propertyValuesSuppressed": True}
        summary["previewDigest"] = value_hash(summary)
        return summary

    def phase(self, phase, apply=False, public_access="Disabled", approved_preview=None):
        self.current_phase = phase
        self.unchanged()
        self.account(self.c["subscriptionId"])
        params = self.parameters(phase, public_access)
        parameter_file = self.artifacts.write(phase + ".parameters.json", {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
            "contentVersion": "1.0.0.0", "parameters": {key: {"value": value} for key, value in params.items()}})
        name = f"aigw-{self.c['environment']}-{phase}-{self.expected_digest[:12]}"
        args = ["--name", name, "--subscription", self.c["subscriptionId"], "--location", self.c["location"],
                "--template-file", str(self.module_root / PHASE_TEMPLATES[phase]),
                "--parameters", "@" + str(parameter_file), "--only-show-errors", "--output", "json"]
        record = {"phase": phase, "deploymentName": name, "status": "preview-started"}
        self.receipt["phases"].append(record)
        self.save()
        result = self.cli.invoke(["deployment", "sub", "what-if", *args, "--no-pretty-print",
                                 "--result-format", "FullResourcePayloads"], timeout=600)
        summary = self.preview_summary(result, phase, params)
        summary["unresolvedPhases"] = self.receipt["unresolvedPhases"]
        summary["fullAzurePreview"] = False
        self.artifacts.write(phase + ".what-if.json", summary)
        record["status"] = "preview-succeeded"
        record["previewDigest"] = summary["previewDigest"]
        self.receipt["previewDigest"] = summary["previewDigest"]
        self.receipt["previewArtifact"] = phase + ".what-if.json"
        self.save()
        self.unchanged()
        if apply:
            require(approved_preview == summary["previewDigest"], "preview-approval-required",
                    "Apply requires --approved-preview matching this exact current phase, parameters and complete sanitized ARM preview.")
            require(json.loads(parameter_file.read_text(encoding="utf-8"))["parameters"]
                    == {key: {"value": value} for key, value in params.items()},
                    "approval-stale", "Generated deployment parameters changed after ARM preview.")
            self.prewrite(phase, params)
            self.unchanged()
            if not any(summary["counts"].get(kind) for kind in ("Create", "Modify")):
                record["status"] = "no-changes"
                self.save()
                return False
            record["status"] = "deployment-started"
            self.receipt["resourceWritesAttempted"] = True
            if phase == "service-bootstrap":
                self.receipt["publicBootstrapMayBeActive"] = True
            self.save()
            result = self.cli.invoke(["deployment", "sub", "create", *args], timeout=7200)
            require(isinstance(result.get("properties"), dict) and result["properties"].get("provisioningState") == "Succeeded",
                    "deployment-incomplete", "Deployment did not report Succeeded. Reconcile Azure operations; no write retry or automatic cleanup is performed.")
            record["status"] = "deployment-succeeded"
            self.save()
            return True
        return False

    def wait_endpoint(self):
        self.current_phase = "verify-private-endpoint"
        for attempt in range(self.poll_attempts):
            self.pe = self.get(self.pe_id(), "network")
            try:
                self.validate_pe(self.pe, approved=True)
                return
            except GatewayError as exc:
                if exc.code != "endpoint-not-approved" or attempt == self.poll_attempts - 1:
                    raise
                self.sleep(10)

    def verify_secure(self):
        self.current_phase = "verify-private-and-identity"
        self.service = self.get(service_id(self.c), "apim")
        self.validate_service(self.service, secure=True)
        self.pe = self.get(self.pe_id(), "network")
        self.validate_pe(self.pe, approved=True)
        self.inventory_zone_groups()
        require(not self.zone_group_missing, "dns-collision", "Required private DNS zone association is missing.")
        self.receipt["publicBootstrapMayBeActive"] = False
        self.save()

    def resolve_phase(self):
        if self.c["serviceMode"] == "existing":
            return "configuration", []
        remaining = []
        if self.network_missing:
            remaining.append("network")
        if self.service is None:
            remaining.append("service-bootstrap")
        if self.pe is None or self.zone_group_missing:
            remaining.append("private-endpoint")
        if self.pe is not None:
            self.validate_pe(self.pe, approved=True)
        if self.service is None or self.properties(self.service)["publicNetworkAccess"] == "Enabled":
            remaining.append("service-lockdown")
        remaining.append("configuration")
        return remaining[0], remaining[1:]

    def postcheck(self, phase):
        self.current_phase = "verify-" + phase
        if phase == "network":
            self.network_created = True
            self.validate_integration(self.get(self.c["network"]["integrationSubnetId"], "network"))
        elif phase == "service-bootstrap":
            self.service = self.get(service_id(self.c), "apim")
            self.validate_service(self.service)
            if self.properties(self.service)["publicNetworkAccess"] == "Enabled":
                self.validate_lockdown_baseline(self.service)
        elif phase == "private-endpoint":
            self.wait_endpoint()
            self.inventory_zone_groups()
            require(not self.zone_group_missing, "dns-collision", "The required private DNS zone group was not created.")
        elif phase == "service-lockdown" or self.c["serviceMode"] == "managed":
            self.verify_secure()
        else:
            self.service = self.get(service_id(self.c), "apim")
            self.validate_service(self.service)

    def execute(self, action, approved_plan=None, approve_initial=False, approved_preview=None):
        self.artifacts.write("plan.json", self.plan)
        require(action in {"plan", "what-if", "apply"}, "action-invalid", "Unsupported action.")
        self.current_phase = "inventory"
        self.receipt = {"schemaVersion": 2, "planDigest": self.expected_digest, "target": self.plan["target"],
                        "action": action, "status": "not-started", "phases": [], "resourceWritesAttempted": False,
                        "publicBootstrapMayBeActive": False, "automaticCleanup": False, "fullAzurePreview": False,
                        "gatewayConfigured": False}
        try:
            if action == "plan":
                self.receipt["status"] = "offline-plan"
                self.save()
                return self.receipt
            if action == "apply":
                require(approved_plan == self.expected_digest, "approval-required",
                        "Apply requires --approved-plan matching the current normalized configuration and transitive source digest.")
                require(isinstance(approved_preview, str) and re.fullmatch(r"[0-9a-f]{64}", approved_preview),
                        "preview-approval-required", "Apply requires --approved-preview from review of the next phase's what-if artifact.")
            self.unchanged()
            self.inventory()
            apply = action == "apply"
            phase, unresolved = self.resolve_phase()
            self.current_phase = phase
            self.receipt.update(currentPhase=phase, unresolvedPhases=unresolved)
            if apply and phase == "service-bootstrap":
                require(approve_initial, "bootstrap-approval-required",
                        "First managed create requires --approve-initial-public-bootstrap. Public access persists between separately reviewed runs, potentially indefinitely; no APIs are configured until lockdown.")
            wrote = self.phase(phase, apply=apply, public_access="Enabled" if phase == "service-bootstrap" else "Disabled",
                               approved_preview=approved_preview)
            if wrote:
                self.postcheck(phase)
            self.receipt["status"] = ("phase-applied" if wrote else "phase-no-changes") if apply else "what-if-phase"
            self.receipt["lifecycleComplete"] = bool(wrote and phase == "configuration")
            # Pipelines publish the MCP/Kong on this APIM only once an apply has reached configuration.
            self.receipt["gatewayConfigured"] = apply and phase == "configuration"
            self.receipt["nextAction"] = (
                "Rerun what-if; review the next phase's previewDigest and planDigest and obtain external approval before one further apply. No later phase has been authorized."
                if unresolved else
                "Validate private DNS/routing and configured resources separately. Any further apply requires rerunning what-if and reviewing fresh phase and plan digests.")
            if phase == "network" and wrote:
                self.receipt["nextAction"] = (
                    "Review the newly created integration subnet, set createIntegrationSubnet=false in consumer configuration, "
                    "generate a fresh offline plan, then rerun what-if and review/approve the service-bootstrap phase. "
                    "A subnet has no ownership tag; its existing state is not automatically adopted on a later invocation.")
            if apply and not wrote:
                self.receipt["nextAction"] = (
                    "No deployment was performed. Reconcile inventory if the phase is still required; rerun what-if and review/approve the next phase. No downstream changes are authorized.")
            self.receipt["apimResourceId"] = service_id(self.c)
            if phase == "configuration":
                self.receipt["foundryApiManagementResourceId"] = service_id(self.c)
            self.receipt["dnsValidationDependency"] = ("Validate policy-created DNS and private routing separately."
                                                      if self.c.get("network", {}).get("privateDnsMode") == "policy"
                                                      else "Validate private DNS and routing separately.")
            self.save()
            return self.receipt
        except GatewayError as exc:
            self.receipt.update(status="blocked", failedPhase=self.current_phase,
                                error={"code": exc.code, "message": str(exc)},
                                nextAction="Inspect phase/deployment state and public exposure. No cleanup/retry occurred. Reconcile governance or partial state, then produce and approve a new plan.")
            self.save()
            raise
        except (OSError, UnicodeError, json.JSONDecodeError):
            self.receipt.update(status="blocked", failedPhase=self.current_phase,
                                error={"code": "local-failure", "message": "Local artifact operation failed; raw details suppressed."})
            self.save()
            raise GatewayError("local-failure", "Local artifact operation failed; raw details suppressed. No automatic cleanup is performed.") from None


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise GatewayError("arguments-invalid", "Invalid CLI arguments. Use --help for supported arguments; argument values are suppressed.")


def main(argv=None, cli=None, environ=None, module_root=MODULE_ROOT):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--action", choices=("plan", "what-if", "apply"), default="plan")
    parser.add_argument("--environment", choices=("dev", "stage", "prod"), required=True)
    parser.add_argument("--config")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--approved-plan")
    parser.add_argument("--approved-preview")
    parser.add_argument("--approve-initial-public-bootstrap", action="store_true")
    try:
        args = parser.parse_args(argv)
        config = load_config(args.config, args.environment, os.environ if environ is None else environ)
        artifacts = Artifacts(args.output_dir, args.config, module_root)
        runner = Deployment(config, artifacts, cli=cli, module_root=module_root)
        receipt = runner.execute(args.action, args.approved_plan, args.approve_initial_public_bootstrap, args.approved_preview)
        print(canonical({"status": receipt["status"], "planDigest": runner.plan["planDigest"],
                         "previewDigest": receipt.get("previewDigest"), "phase": receipt.get("currentPhase"),
                         "armPreviewExecuted": args.action != "plan",
                         "gatewayConfigured": receipt["gatewayConfigured"],
                         "publicBootstrapMayBeActive": receipt["publicBootstrapMayBeActive"],
                         "nextAction": receipt.get("nextAction")}))
        return 0
    except GatewayError as exc:
        print(canonical({"status": "blocked", "code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(canonical({"status": "blocked", "code": "local-failure", "message": "Local preparation failed; raw details suppressed."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    def safe_unhandled_exception(exc_type, exc, traceback):
        print('{"status":"failed","code":"internal-failure","message":"Unexpected internal error; raw details suppressed."}', file=sys.stderr)

    sys.excepthook = safe_unhandled_exception
    sys.exit(main())
