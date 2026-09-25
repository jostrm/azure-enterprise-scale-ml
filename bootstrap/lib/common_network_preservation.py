"""Bounded preserve-v1 common-network planning; no authentication or mutations.

The caller pins this source, collects the complete routing/allocation domain,
holds the shared hub lease, freezes approval, and recollects before deployment.
ARM Incremental mode is NOT create-only. This profile never updates a VNet or
an existing subnet/NSG; it adds individually addressed missing resources only.
"""
from __future__ import annotations

import copy
import ast
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

PROFILE = "preserve-v1"
API_VERSION = "2023-11-01"
ENTRYPOINT = "environment_setup/aifactory/bicep/esml-common/main/12-networkCommon.bicep"
HELPER = "bootstrap/lib/common_network_preservation.py"
ROOT = Path(__file__).resolve().parents[2]
_LOADED_HELPER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class PreservationError(ValueError):
    pass


class RegionalServiceEndpointError(PreservationError):
    def __init__(self, preflight):
        self.preflight = copy.deepcopy(preflight)
        super().__init__("regional-service-endpoints-unsupported:" + preflight["capabilities"]["location"]
                         + ":" + ",".join(item["service"] for item in preflight["blockers"]))


def require(value, code):
    if not value:
        raise PreservationError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resource_id(value):
    require(isinstance(value, str) and re.fullmatch(
        r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/]+/providers/Microsoft\.Network/"
        r"(?:virtualNetworks/[^/]+(?:/(?:subnets|virtualNetworkPeerings)/[^/]+)?|networkSecurityGroups/[^/]+)",
        value, re.I), "invalid-network-resource-id")
    return value.lower()


def resource_type(value):
    parts = resource_id(value).split("/")
    return "/".join([parts[6], *parts[7::2]])


def network(value):
    try:
        result = ipaddress.ip_network(value, strict=True)
    except (ValueError, TypeError):
        raise PreservationError("canonical-network-cidr-required") from None
    require(result.version == 4, "reviewed-profile-requires-ipv4")
    return result


def _ordinary(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                    for p in (path, *path.parents)), "linked-network-source-forbidden")
    require(path.is_file() and path.stat().st_nlink == 1, "ordinary-network-source-file-required")
    return path


def _source_files(source_root):
    root = Path(source_root).absolute()
    pending, files = [root / ENTRYPOINT, root / HELPER], {}
    while pending:
        path = _ordinary(pending.pop())
        relative = path.relative_to(root).as_posix()
        if relative in files:
            continue
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix == ".bicep":
            for reference in re.findall(r"(?m)^\s*module\s+\w+\s+'([^']+)'", path.read_text(encoding="utf-8")):
                require(not reference.startswith(("br:", "ts:")), "unreviewed-network-registry-module")
                child = Path(Path(path.parent / reference).resolve())
                require(child.is_relative_to(root), "network-module-outside-source")
                pending.append(child)
    return files


def _resources(template):
    resources = template.get("resources", [])
    return list(resources.values()) if isinstance(resources, dict) else resources


def validate_compiled_capability(template):
    """Validate actual emitted ARM, including gates on every legacy mutation."""
    parameters = template["parameters"]
    require(parameters["commonNetworkProfile"]["defaultValue"] == "legacy"
            and set(parameters["commonNetworkProfile"]["allowedValues"]) == {"legacy", PROFILE},
            "network-profile-contract-missing")
    modules = _resources(template)
    require(len(modules) == 8 and all(r["type"] == "Microsoft.Resources/deployments" for r in modules),
            "unreviewed-common-network-resource")
    critical_variables = {
        "subscriptionIdDevTestProd": "[subscription().subscriptionId]",
        "commonResourceGroupName": "[format('{0}{1}-{2}-{3}{4}', parameters('commonRGNamePrefix'), parameters('commonResourceName'), parameters('locationSuffix'), parameters('env'), parameters('aifactorySuffixRG'))]",
        "vnetResourceGroupName": "[if(not(empty(parameters('vnetResourceGroup_param'))), replace(parameters('vnetResourceGroup_param'), '<network_env>', parameters('network_env')), variables('commonResourceGroupName'))]",
        "vnetNameFull": "[if(not(empty(parameters('vnetNameFull_param'))), parameters('vnetNameFull_param'), format('{0}-{1}-{2}{3}', parameters('vnetNameBase'), parameters('locationSuffix'), parameters('env'), parameters('commonResourceSuffix')))]",
        "vNetRGsalt": "[substring(uniqueString(subscriptionResourceId(variables('subscriptionIdDevTestProd'), 'Microsoft.Resources/resourceGroups', variables('vnetResourceGroupName'))), 0, 5)]",
        "commmonRGsalt": "[substring(uniqueString(variables('commonResourceGroupName')), 0, 5)]",
        "uniqueDetermenistic": "[format('{0}{1}', variables('commmonRGsalt'), variables('vNetRGsalt'))]",
        "common_bastion_subnet_cidr_v": "[replace(parameters('common_bastion_subnet_cidr'), 'XX', parameters('cidr_range'))]",
        "ipWhitelist_array_1": "[array(split(replace(parameters('IPwhiteList'), '\\s+', ''), ','))]",
        "ipWhitelist_array": "[if(or(or(empty(parameters('IPwhiteList')), equals(parameters('IPwhiteList'), 'null')), less(length(parameters('IPwhiteList')), 5)), createArray(), union(variables('ipWhitelist_array_1'), createArray()))]",
    }
    require(all(template.get("variables", {}).get(k) == v for k, v in critical_variables.items()),
            "unreviewed-network-scope-variable")
    for key, default in {
        "commonRGNamePrefix": "", "commonResourceName": "esml-common", "aifactorySuffixRG": "",
        "vnetResourceGroup_param": "", "vnetNameFull_param": "", "network_env": "", "IPwhiteList": "",
        "common_bastion_subnet_name": "AzureBastionSubnet", "common_pbi_subnet_name": "snt-common-pbi-gw",
    }.items():
        require(parameters[key].get("defaultValue") == default and parameters[key]["type"] == "string",
                "unreviewed-network-parameter-default")
    for module in modules:
        require(set(module) <= {"type", "apiVersion", "name", "condition", "subscriptionId",
                                "resourceGroup", "dependsOn", "properties"}
                and module.get("subscriptionId") == "[variables('subscriptionIdDevTestProd')]"
                and module.get("resourceGroup") == "[variables('vnetResourceGroupName')]",
                "unreviewed-network-deployment-scope")
        props = module["properties"]
        require(set(props) == {"expressionEvaluationOptions", "mode", "parameters", "template"}
                and props["expressionEvaluationOptions"] == {"scope": "inner"},
                "unreviewed-network-deployment-nesting")
    legacy = "equals(parameters('commonNetworkProfile'), 'legacy')"
    nsg_conditions = [
        f"[or({legacy}, contains(parameters('preservationPlan').createNetworkSecurityGroups, format('nsg-{{0}}', parameters('common_subnet_name'))))]",
        f"[or({legacy}, contains(parameters('preservationPlan').createNetworkSecurityGroups, format('nsg-{{0}}-scoring', parameters('common_subnet_name'))))]",
        f"[and(not(empty(variables('ipWhitelist_array'))), or({legacy}, contains(parameters('preservationPlan').createNetworkSecurityGroups, format('nsg-{{0}}', parameters('common_bastion_subnet_name')))))]",
        f"[and(empty(variables('ipWhitelist_array')), or({legacy}, contains(parameters('preservationPlan').createNetworkSecurityGroups, format('nsg-{{0}}', parameters('common_bastion_subnet_name')))))]",
        f"[or({legacy}, contains(parameters('preservationPlan').createNetworkSecurityGroups, format('nsg-{{0}}', parameters('common_pbi_subnet_name'))))]",
    ]
    nsg_name_expressions = [
        "[format('nsg-{0}', parameters('common_subnet_name'))]",
        "[format('nsg-{0}-scoring', parameters('common_subnet_name'))]",
        "[format('nsg-{0}', parameters('common_bastion_subnet_name'))]",
        "[format('nsg-{0}', parameters('common_bastion_subnet_name'))]",
        "[format('nsg-{0}', parameters('common_pbi_subnet_name'))]",
    ]
    deployment_names = [
        "[format('nsg-{0}-depl{1}', parameters('common_subnet_name'), variables('uniqueDetermenistic'))]",
        "[format('nsg-{0}-scoring-depl{1}', parameters('common_subnet_name'), variables('uniqueDetermenistic'))]",
        "[format('nsg-{0}-depl{1}', parameters('common_bastion_subnet_name'), variables('uniqueDetermenistic'))]",
        "[format('nsg-{0}-NoWLdepl{1}', parameters('common_bastion_subnet_name'), variables('uniqueDetermenistic'))]",
        "[format('nsg-{0}-depl{1}', parameters('common_pbi_subnet_name'), variables('uniqueDetermenistic'))]",
    ]
    for index, (module, condition) in enumerate(zip(modules[:5], nsg_conditions)):
        require(module.get("condition") == condition, "unguarded-network-security-group")
        require(module["name"] == deployment_names[index], "unreviewed-network-deployment-name")
        forwarded = {"name": nsg_name_expressions[index], "enableFlowLogs": f"[{legacy}]",
                     "tags": "[parameters('tags')]", "location": "[parameters('location')]"}
        if index < 2:
            forwarded["bastionIpRange"] = "[variables('common_bastion_subnet_cidr_v')]"
        elif index < 4:
            forwarded["IPwhiteList_Array"] = "[variables('ipWhitelist_array')]"
        require(module["properties"]["parameters"] == {k: {"value": v} for k, v in forwarded.items()},
                "unreviewed-nsg-parameter-forwarding")
        nested = _resources(module["properties"]["template"])
        require(len(nested) == 2, "unreviewed-nsg-resource-count")
        nsg, flow = nested
        require({k: v for k, v in nsg.items() if k != "properties"} == {
            "type": "Microsoft.Network/networkSecurityGroups", "apiVersion": "2020-06-01",
            "name": "[parameters('name')]", "location": "[parameters('location')]", "tags": "[parameters('tags')]"}
            and set(nsg["properties"]) == {"securityRules"}, "unreviewed-nsg-target-or-properties")
        require(flow.get("type") == "Microsoft.Network/networkWatchers/flowLogs"
                and flow.get("condition") == "[and(parameters('enableFlowLogs'), not(empty(parameters('storageAccountId'))))]"
                and set(flow) == {"condition", "type", "apiVersion", "name", "location", "tags", "properties", "dependsOn"},
                "unreviewed-nsg-module")
    require(modules[5].get("condition") == f"[and({legacy}, not(parameters('BYO_subnets')))]"
            and modules[7].get("condition") == f"[and({legacy}, parameters('deployAIGatewayNetworking'))]",
            "legacy-network-not-isolated")
    modern = modules[6]
    require(modern.get("condition") == "[equals(parameters('commonNetworkProfile'), 'preserve-v1')]"
            and modern["properties"]["parameters"]["plan"]["value"] == "[parameters('preservationPlan')]",
            "preservation-module-not-selected")
    require(modern["name"] == "[format('{0}-preserve-{1}', variables('vnetNameFull'), variables('uniqueDetermenistic'))]",
            "unreviewed-network-deployment-name")
    require(modern["properties"]["parameters"] == {
        "location": {"value": "[parameters('location')]"}, "tags": {"value": "[parameters('tags')]"},
        "vnetNameFull": {"value": "[variables('vnetNameFull')]"}, "plan": {"value": "[parameters('preservationPlan')]"}},
        "unreviewed-preservation-parameter-forwarding")
    for module in modules:
        require(module["properties"]["mode"] == "Incremental", "complete-deployment-forbidden")
    for module in [*modules[:5], modern]:
        require(set(module["properties"]["template"]) <= {
            "$schema", "languageVersion", "contentVersion", "metadata", "parameters", "resources", "outputs"},
            "unreviewed-active-network-template-nesting")
    resources = _resources(modern["properties"]["template"])
    require(len(resources) == 2, "unreviewed-preservation-resource")
    parent, children = resources
    require(parent["type"] == "Microsoft.Network/virtualNetworks"
            and parent.get("condition") == "[parameters('plan').createVnet]"
            and parent["name"] == "[parameters('vnetNameFull')]"
            and parent["properties"] == {"addressSpace": {"addressPrefixes": "[parameters('plan').addressPrefixes]"}},
            "destructive-preservation-parent")
    require(set(parent) == {"condition", "type", "apiVersion", "name", "location", "tags", "properties"}
            and parent["apiVersion"] == API_VERSION
            and parent["location"] == "[parameters('location')]" and parent["tags"] == "[parameters('tags')]",
            "unreviewed-preservation-parent-scope")
    require(children["type"] == "Microsoft.Network/virtualNetworks/subnets"
            and children["name"] == "[format('{0}/{1}', parameters('vnetNameFull'), parameters('plan').createSubnets[copyIndex()].name)]"
            and children["properties"] == "[parameters('plan').createSubnets[copyIndex()].properties]"
            and children["copy"] == {"name": "missingSubnets", "count": "[length(parameters('plan').createSubnets)]",
                                     "mode": "serial", "batchSize": 1},
            "unbounded-preservation-children")
    require(set(children) == {"copy", "type", "apiVersion", "name", "properties", "dependsOn"}
            and children["apiVersion"] == API_VERSION
            and children["dependsOn"] == ["[resourceId('Microsoft.Network/virtualNetworks', parameters('vnetNameFull'))]"],
            "unreviewed-preservation-child-scope")
    return {"profile": PROFILE, "parent_updates": False, "existing_child_updates": False,
            "external_hub_owned": False, "removal_deletes_hub": False,
            "dns_updates": False, "deployment_mode": "Incremental"}


def _compile_capability(source_root, *, expected_payload_sha256=None, bicep=None):
    files = _source_files(source_root)
    require(files.get(HELPER) == _LOADED_HELPER_SHA256, "loaded-network-helper-source-changed")
    require(files == _source_files(ROOT), "loaded-network-source-differs-from-selected-source")
    fingerprint = digest(files)
    require(expected_payload_sha256 is None or fingerprint == expected_payload_sha256,
            "reviewed-network-payload-required")
    compiler = bicep or shutil.which("bicep")
    require(compiler, "standalone-bicep-required-for-preservation-proof")
    result = subprocess.run([str(compiler), "build", str(Path(source_root) / ENTRYPOINT),
                             "--no-restore", "--stdout"], capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, "preservation-template-compile-failed:" + result.stderr[-2000:])
    template = json.loads(result.stdout)
    capability = validate_compiled_capability(template)
    require(files == _source_files(source_root), "network-source-changed-during-proof")
    return template, {**capability, "files": files, "payload_sha256": fingerprint,
                      "compiled_arm_sha256": digest(template),
                      "published_ref_verified": False, "verification": "exact-source-and-compiled-arm"}


def assert_preservation_capability(source_root, *, expected_payload_sha256=None, bicep=None):
    return _compile_capability(source_root, expected_payload_sha256=expected_payload_sha256, bicep=bicep)[1]


def _canonical(desired):
    params = copy.deepcopy(desired["parameters"])
    identifier = resource_id(desired["vnet_id"])
    require(resource_type(identifier) == "microsoft.network/virtualnetworks", "parent-vnet-id-required")
    require(isinstance(desired.get("factory_id"), str) and desired["factory_id"].strip(),
            "factory-identity-required")
    for flag in ("deployAIGatewayNetworking", "deployOnlyAIGatewayNetworking"):
        require(params.get(flag, False) is False, "unreviewed-ai-gateway-networking-extension")
    require(params.get("BYO_subnets", False) is False,
            "preserve-profile-creates-owned-subnets-not-byo-skip")
    suffix = params.get("commonResourceSuffix", "")
    name = params.get("vnetNameFull_param") or f"{params['vnetNameBase']}-{params['locationSuffix']}-{params['env']}{suffix}"
    group = params.get("vnetResourceGroup_param") or (
        f"{params.get('commonRGNamePrefix', '')}{params.get('commonResourceName', 'esml-common')}"
        f"-{params['locationSuffix']}-{params['env']}{params.get('aifactorySuffixRG', '')}")
    group = group.replace("<network_env>", params.get("network_env", ""))
    require(identifier.split("/")[4] == group.lower() and identifier.split("/")[-1] == name.lower(),
            "common-template-vnet-target-mismatch")
    require(params.get("location"), "network-location-required")
    common = params["common_subnet_name"]
    pbi = params.get("common_pbi_subnet_name", "snt-common-pbi-gw")
    bastion = params.get("common_bastion_subnet_name", "AzureBastionSubnet")
    require(bastion == "AzureBastionSubnet", "canonical-bastion-name-required")
    names = [common, common + "-scoring", pbi, bastion]
    require(len(set(n.lower() for n in names)) == 4 and all(
        re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", n) for n in names), "unique-canonical-subnet-names-required")
    cidr_keys = ["common_subnet_cidr", "common_subnet_scoring_cidr",
                 "common_pbi_subnet_cidr", "common_bastion_subnet_cidr"]
    cidrs = [str(network(params[k].replace("XX", params.get("cidr_range", "")))) for k in cidr_keys]
    rg = identifier.split("/providers/")[0]
    nsg_ids = [rg + "/providers/microsoft.network/networksecuritygroups/nsg-" + n.lower() for n in names]
    services = [
        [{"service": "Microsoft.KeyVault", "locations": [params["location"]]},
         {"service": "Microsoft.Storage"}, {"service": "Microsoft.CognitiveServices"}],
        [{"service": "Microsoft.KeyVault"}, {"service": "Microsoft.ContainerRegistry"}, {"service": "Microsoft.Storage"}],
        [], [],
    ]
    for endpoints in services:
        for endpoint in endpoints:
            endpoint["locations"] = [params["location"]]
    subnets = []
    for index, (subnet_name, cidr, nsg_id) in enumerate(zip(names, cidrs, nsg_ids)):
        props = {"addressPrefix": cidr, "serviceEndpoints": services[index],
                 "networkSecurityGroup": {"id": nsg_id}}
        if index < 2:
            props.update(privateEndpointNetworkPolicies="Disabled", privateLinkServiceNetworkPolicies="Disabled")
        elif index == 2:
            props["delegations"] = [{"name": "powerplatform-vnetaccesslinks",
                                     "properties": {"serviceName": "Microsoft.PowerPlatform/vnetaccesslinks"}}]
        else:
            props["delegations"] = []
        subnets.append({"name": subnet_name, "properties": props})
    return params, identifier, subnets, nsg_ids


def required_resource_ids(desired):
    _, identifier, subnets, nsg_ids = _canonical(desired)
    return [identifier, *[identifier + "/subnets/" + s["name"].lower() for s in subnets], *nsg_ids]


def _endpoint_capability_scope(subscription_id, location):
    require(isinstance(subscription_id, str) and re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", subscription_id),
        "endpoint-capability-subscription-required")
    require(isinstance(location, str) and re.fullmatch(r"[a-zA-Z0-9]+", location),
            "endpoint-capability-canonical-location-required")
    return (f"/subscriptions/{subscription_id.lower()}/providers/Microsoft.Network/"
            f"locations/{location.lower()}/virtualNetworkAvailableEndpointServices")


def collect_service_endpoint_capabilities(cloud, *, subscription_id, location):
    """Read the Network RP's exact subscription/region support, never infer it."""
    path = _endpoint_capability_scope(subscription_id, location)
    status, _, body = cloud.arm("GET", path, API_VERSION, allowed=(200,))
    require(status == 200, "regional-service-endpoint-capability-read-failed")
    require(isinstance(body, dict) and isinstance(body.get("value"), list)
            and not body.get("nextLink"), "complete-regional-service-endpoint-capabilities-required")
    names = [item.get("name") if isinstance(item, dict) else None for item in body["value"]]
    require(all(isinstance(name, str) and re.fullmatch(r"Microsoft\.[a-zA-Z0-9.]+", name, re.I)
                for name in names), "invalid-regional-service-endpoint-capability")
    require(len(names) == len({name.lower() for name in names}),
            "duplicate-regional-service-endpoint-capability")
    return {"subscription_id": subscription_id.lower(), "location": location.lower(),
            "api_version": API_VERSION, "source": path, "services": sorted(names, key=str.lower)}


def validate_common_network_region(desired, capabilities, *, subnets=None):
    """Read-only readiness for canonical or actually planned NEW subnets.

    Missing services are blockers, not permission to remove an endpoint, alter
    a firewall, move a workload or rewrite an existing subnet. Provider endpoint
    support is not proof of Foundry/Agent/model availability.
    """
    params, identifier, canonical_subnets, _ = _canonical(desired)
    subscription_id, location = identifier.split("/")[2], params["location"].lower()
    path = _endpoint_capability_scope(subscription_id, location)
    require(isinstance(capabilities, dict) and set(capabilities) == {
        "subscription_id", "location", "api_version", "source", "services"}
        and capabilities["subscription_id"] == subscription_id
        and capabilities["location"] == location and capabilities["api_version"] == API_VERSION
        and capabilities["source"] == path, "regional-service-endpoint-capability-scope-mismatch")
    services = capabilities["services"]
    require(isinstance(services, list)
            and all(isinstance(name, str) and re.fullmatch(r"Microsoft\.[a-zA-Z0-9.]+", name, re.I)
                    for name in services)
            and len(services) == len({name.lower() for name in services}),
            "invalid-regional-service-endpoint-capability")
    selected = canonical_subnets if subnets is None else subnets
    require(isinstance(selected, list) and all(subnet in canonical_subnets for subnet in selected),
            "unreviewed-regional-service-endpoint-subnet")
    required = sorted({endpoint["service"] for subnet in selected
                       for endpoint in subnet["properties"]["serviceEndpoints"]})
    supported = {name.lower() for name in services}
    blockers = [{
        "code": "regional-service-endpoint-not-supported", "service": service,
        "subscription_id": subscription_id, "location": location,
        "message": (f"{service} service endpoints are unavailable in {location} for the selected subscription. "
                    "No network writes are permitted. Review workload/private-network regional support; "
                    "do not silently remove endpoints, enable public access, or relocate workloads."),
    } for service in required if service.lower() not in supported]
    return {"can_execute": not blockers, "blockers": blockers, "required_services": required,
            "capabilities": copy.deepcopy(capabilities)}


def collect_inventory(cloud, *, vnet_id, other_vnet_ids, reserved_ranges=(), resource_ids=()):
    """GET only; caller supplies the complete cross-subscription routing domain.

    Authentication/authorization errors cannot be converted to absence. The Cloud
    adapter uses factory_enrollment.Cloud's (status, headers, JSON body) contract.
    Include required_resource_ids(desired), not just the VNet.
    """
    ids = {resource_id(value) for value in (vnet_id, *other_vnet_ids, *resource_ids)}
    resources, ranges = {}, []
    for identifier in sorted(ids):
        status, _, body = cloud.arm("GET", identifier, API_VERSION, allowed=(200, 404))
        require(status in (200, 404), "network-inventory-read-failed")
        resources[identifier] = copy.deepcopy(body) if status == 200 else None
        if status == 200 and resource_type(identifier) == "microsoft.network/virtualnetworks":
            require(resource_id(body["id"]) == identifier and
                    isinstance(body.get("properties", {}).get("addressSpace", {}).get("addressPrefixes"), list),
                    "incomplete-live-vnet-inventory")
            ranges.append({"id": identifier, "address_prefixes": body["properties"]["addressSpace"]["addressPrefixes"]})
    return {"complete": True, "resources": resources, "vnet_ranges": ranges,
            "reserved_ranges": list(reserved_ranges)}


def _prefixes(subnet):
    props = subnet["properties"]
    return [str(network(x)) for x in (props.get("addressPrefixes") or [props.get("addressPrefix")])]


def _validate_existing(value, identifier):
    require(isinstance(value, dict) and resource_id(value["id"]) == identifier
            and value.get("etag") and value.get("properties", {}).get("provisioningState") == "Succeeded",
            "existing-network-resource-not-ready-or-incomplete")


def plan_common_network(*, vnet, desired, inventory):
    params, identifier, subnets, nsg_ids = _canonical(desired)
    require(inventory.get("complete") is True and isinstance(inventory.get("vnet_ranges"), list)
            and isinstance(inventory.get("reserved_ranges"), list), "complete-routing-inventory-required")
    resources = {resource_id(k): v for k, v in inventory["resources"].items()}
    require(all(key in resources for key in required_resource_ids(desired)), "incomplete-network-inventory")
    require(resources[identifier] == vnet, "vnet-snapshot-mismatch")
    approved = [network(x) for x in desired["approved_address_prefixes"]]
    require(approved and len(set(approved)) == len(approved), "approved-parent-address-space-required")
    configured = network(params["common_vnet_cidr"].replace("XX", params.get("cidr_range", "")))
    require(configured in approved, "common-cidr-not-approved")
    for i, prefix in enumerate(approved):
        require(not any(prefix.overlaps(other) for other in approved[i + 1:]), "overlapping-parent-prefixes")
    owned = {resource_id(x) for x in desired.get("owned_resource_ids", [])}
    reused = {resource_id(x) for x in desired.get("reused_resource_ids", [])}
    require(not owned & reused, "ambiguous-network-ownership")
    require(owned <= set(required_resource_ids(desired)), "ownership-outside-common-network")
    if vnet is not None:
        _validate_existing(vnet, identifier)
        props = vnet["properties"]
        require(isinstance(props.get("subnets"), list) and isinstance(props.get("virtualNetworkPeerings"), list),
                "complete-parent-children-required")
        require(set(network(x) for x in props["addressSpace"]["addressPrefixes"]) == set(approved),
                "parent-address-space-change-not-supported")
        require(vnet.get("location", "").lower() == params["location"].lower(), "vnet-location-conflict")
    else:
        require(all(resources[x] is None for x in required_resource_ids(desired) if "/subnets/" in x),
                "absent-parent-has-existing-subnet")
    for entry in inventory["vnet_ranges"]:
        if resource_id(entry["id"]) != identifier:
            require(not any(prefix.overlaps(network(other)) for prefix in approved
                            for other in entry["address_prefixes"]), "live-vnet-address-overlap")
    require(not any(prefix.overlaps(network(other)) for prefix in approved
                    for other in inventory["reserved_ranges"]), "reserved-routing-address-overlap")
    existing_subnets = {resource_id(s["id"]): s for s in (vnet or {}).get("properties", {}).get("subnets", [])}
    for child_id, child in existing_subnets.items():
        require(child_id.startswith(identifier + "/subnets/") and child.get("etag"),
                "incomplete-existing-subnet")
        _prefixes(child)
    canonical_ids = [identifier + "/subnets/" + s["name"].lower() for s in subnets]
    for child_id in canonical_ids:
        require((resources[child_id] is None) == (child_id not in existing_subnets),
                "inconsistent-subnet-inventory")
        if resources[child_id] is not None:
            require(resources[child_id]["etag"] == existing_subnets[child_id]["etag"],
                    "subnet-snapshot-changed")
    additions, create_nsgs, created_ids = [], [], []
    for index, (subnet, child_id, nsg_id) in enumerate(zip(subnets, canonical_ids, nsg_ids)):
        prefix = network(subnet["properties"]["addressPrefix"])
        require(prefix.prefixlen <= (26 if subnet["name"] == "AzureBastionSubnet" else 28),
                "canonical-subnet-too-small")
        require(any(prefix.subnet_of(parent) for parent in approved), "subnet-outside-approved-parent")
        require(not any(prefix.overlaps(network(other["properties"]["addressPrefix"]))
                        for other in subnets[index + 1:]), "canonical-subnet-overlap")
        require(not any(prefix.overlaps(network(other)) for key, value in existing_subnets.items()
                        if key != child_id for other in _prefixes(value)), "live-subnet-address-overlap")
        if resources[child_id] is not None:
            _validate_existing(resources[child_id], child_id)
            require(child_id in owned | reused, "existing-subnet-reuse-approval-required")
            require(_prefixes(resources[child_id]) == [str(prefix)], "existing-subnet-cidr-conflict")
            # Keep every existing property, including service association links,
            # routes, delegations, PE policies and etags, by not issuing a PUT.
            continue
        if resources[nsg_id] is None:
            create_nsgs.append("nsg-" + subnet["name"])
            created_ids.append(nsg_id)
        else:
            _validate_existing(resources[nsg_id], nsg_id)
            require(nsg_id in owned | reused, "existing-nsg-reuse-approval-required")
        additions.append(subnet)
        created_ids.append(child_id)
    plan = {"createVnet": vnet is None, "addressPrefixes": [str(x) for x in approved],
            "createSubnets": additions, "createNetworkSecurityGroups": create_nsgs}
    if vnet is None:
        created_ids.insert(0, identifier)
    params.update(commonNetworkProfile=PROFILE, preservationPlan=plan)
    return {"profile": PROFILE, "desired": copy.deepcopy(desired), "deployment_parameters": params,
            "existing_resource_policy": "preserve-without-reconciliation",
            "snapshot_sha256": digest(inventory), "mutation_resource_ids": created_ids,
            "owned_resource_ids": sorted(owned | set(created_ids)),
            "retained_resource_ids": sorted(k for k, v in resources.items() if v is not None),
            "retained_vnet_sha256": digest(vnet), "deletion_resource_ids": []}


def revalidate_common_network(plan, *, vnet, inventory):
    require(plan["snapshot_sha256"] == digest(inventory), "network-inventory-changed-replan-required")
    fresh = plan_common_network(vnet=vnet, desired=plan["desired"], inventory=inventory)
    require(fresh == plan, "network-plan-changed-reapproval-required")
    return fresh


def _evaluate_nsg(value, parameters):
    if isinstance(value, dict):
        return {key: _evaluate_nsg(item, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [_evaluate_nsg(item, parameters) for item in value]
    if not isinstance(value, str) or not value.startswith("["):
        return copy.deepcopy(value)

    def walk(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            args = [walk(arg) for arg in node.args]
            if node.func.id == "parameters" and len(args) == 1:
                return copy.deepcopy(parameters[args[0]])
            if node.func.id == "format" and args:
                return args[0].format(*args[1:])
        raise PreservationError("unreviewed-nsg-arm-expression")
    return walk(ast.parse(value[1:-1], mode="eval").body)


def _base_expected_resources(plan):
    params = plan["deployment_parameters"]
    identifier = resource_id(plan["desired"]["vnet_id"])
    preservation = params["preservationPlan"]
    expected = {}
    if preservation["createVnet"]:
        expected[identifier] = {"location": params["location"], "tags": params["tags"],
                               "properties": {"addressSpace": {"addressPrefixes": preservation["addressPrefixes"]}}}
    for subnet in preservation["createSubnets"]:
        expected[identifier + "/subnets/" + subnet["name"].lower()] = {"properties": copy.deepcopy(subnet["properties"])}
    return expected


def expected_resource_bodies(template, plan):
    """Freeze the actual writable NSG bodies, not only resource identities."""
    validate_compiled_capability(template)
    expected = _base_expected_resources(plan)
    params, _, _, nsg_ids = _canonical(plan["desired"])
    value = params.get("IPwhiteList", "")
    whitelist = [] if not value or value == "null" or len(value) < 5 else list(dict.fromkeys(value.replace("\\s+", "").split(",")))
    selected = {name.lower() for name in plan["deployment_parameters"]["preservationPlan"]["createNetworkSecurityGroups"]}
    for index, (module, identifier) in enumerate(zip(_resources(template)[:5],
                                                    (nsg_ids[0], nsg_ids[1], nsg_ids[3], nsg_ids[3], nsg_ids[2]))):
        if identifier.rsplit("/", 1)[1] not in selected or (index == 2 and not whitelist) or (index == 3 and whitelist):
            continue
        nested_params = {"name": identifier.rsplit("/", 1)[1], "location": params["location"],
                         "tags": params["tags"], "IPwhiteList_Array": whitelist,
                         "bastionIpRange": params["common_bastion_subnet_cidr"].replace("XX", params.get("cidr_range", ""))}
        nsg = _resources(module["properties"]["template"])[0]
        expected[identifier] = _evaluate_nsg({key: nsg[key] for key in ("location", "tags", "properties")}, nested_params)
    require(set(expected) == set(plan["mutation_resource_ids"]), "compiled-network-mutation-set-mismatch")
    return expected


def _planned_associations(plan, identifier):
    vnet_id = resource_id(plan["desired"]["vnet_id"])
    return {vnet_id + "/subnets/" + subnet["name"].lower()
            for subnet in plan["deployment_parameters"]["preservationPlan"]["createSubnets"]
            if resource_id(subnet["properties"]["networkSecurityGroup"]["id"]) == identifier}


def _associations(values):
    require(isinstance(values, list) and all(isinstance(item, dict) and set(item) == {"id"} for item in values),
            "unexpected-nsg-subnet-association-shape")
    ids = [resource_id(item["id"]) for item in values]
    require(len(ids) == len(set(ids)), "duplicate-nsg-subnet-association")
    return set(ids)


def _retained_nsg_unchanged(old, new, additions):
    if not isinstance(new, dict):
        return False
    old, new = copy.deepcopy(old), copy.deepcopy(new)
    previous = _associations(old["properties"].pop("subnets", []) or [])
    current = _associations(new["properties"].pop("subnets", []) or [])
    if additions:
        old.pop("etag", None)
        new.pop("etag", None)
    return current == previous | additions and old == new


def _subnet_write_properties(properties):
    props = copy.deepcopy(properties)
    props.pop("provisioningState", None)
    prefixes = _prefixes({"properties": props})
    props.pop("addressPrefix", None)
    props.pop("addressPrefixes", None)
    props["addressPrefixes"] = sorted(prefixes)
    for name in ("ipConfigurations", "privateEndpoints", "serviceAssociationLinks", "resourceNavigationLinks", "ipConfigurationProfiles"):
        require(props.pop(name, None) in (None, []), "unexpected-new-subnet-association:" + name)
    for key, default in {"serviceEndpoints": [], "delegations": [], "serviceEndpointPolicies": [], "ipAllocations": [],
                         "privateEndpointNetworkPolicies": "Enabled", "privateLinkServiceNetworkPolicies": "Enabled"}.items():
        props.setdefault(key, default)
    for key in ("networkSecurityGroup", "routeTable", "natGateway"):
        if props.get(key) is None:
            props.pop(key, None)
        elif isinstance(props[key], dict) and set(props[key]) == {"id"}:
            props[key]["id"] = props[key]["id"].lower()
    # This API allows omitted outbound-access to receive the platform default;
    # both historic true and the private-subnet rollout's false are documented.
    if "defaultOutboundAccess" in props:
        outbound = props.pop("defaultOutboundAccess")
        require(outbound is None or type(outbound) is bool, "invalid-subnet-outbound-default")
    if props.get("sharingScope") is None:
        props.pop("sharingScope", None)
    for endpoint in props["serviceEndpoints"]:
        endpoint.pop("provisioningState", None)
        if "locations" in endpoint:
            endpoint["locations"] = sorted(endpoint["locations"])
    props["serviceEndpoints"].sort(key=lambda item: item["service"])
    for delegation in props["delegations"]:
        for key in ("id", "etag", "type"):
            delegation.pop(key, None)
        delegation["properties"].pop("provisioningState", None)
        delegation["properties"].pop("actions", None)
    props["delegations"].sort(key=lambda item: item["name"])
    return props


def _nsg_write_properties(properties, *, associations):
    props = copy.deepcopy(properties)
    for key in ("provisioningState", "resourceGuid", "defaultSecurityRules"):
        props.pop(key, None)
    require(_associations(props.pop("subnets", []) or []) == associations, "new-nsg-subnet-associations-mismatch")
    for key in ("networkInterfaces", "flowLogs"):
        require(props.pop(key, None) in (None, []), "unexpected-new-nsg-association:" + key)
    props.setdefault("flushConnection", False)
    for rule in props.get("securityRules", []):
        for key in ("id", "etag", "type"):
            rule.pop(key, None)
        rules = rule["properties"]
        rules.pop("provisioningState", None)
        for key in ("sourcePortRange", "destinationPortRange", "sourceAddressPrefix", "destinationAddressPrefix",
                    "sourcePortRanges", "destinationPortRanges", "sourceAddressPrefixes", "destinationAddressPrefixes",
                    "sourceApplicationSecurityGroups", "destinationApplicationSecurityGroups"):
            if rules.get(key) in (None, "", []):
                rules.pop(key, None)
            elif isinstance(rules[key], list):
                rules[key] = sorted(rules[key], key=lambda item: json.dumps(item, sort_keys=True))
    if "securityRules" in props:
        props["securityRules"].sort(key=lambda item: item["name"])
    return props


def _verify_created_resource(identifier, actual, expected, plan):
    _validate_existing(actual, identifier)
    require(set(actual) <= {"id", "name", "type", "etag", "systemData", "location", "tags", "properties"},
            "unexpected-new-network-resource-field")
    kind = resource_type(identifier)
    require("type" not in actual or actual["type"].lower() == kind, "created-network-type-mismatch")
    require("name" not in actual or actual["name"].lower() == identifier.rsplit("/", 1)[1],
            "created-network-name-mismatch")
    for key in ("location", "tags"):
        actual_value = actual.get(key, {} if key == "tags" else None)
        expected_value = expected.get(key, {} if key == "tags" else None)
        if key == "location" and isinstance(actual_value, str) and isinstance(expected_value, str):
            actual_value, expected_value = actual_value.lower(), expected_value.lower()
        require(actual_value == expected_value, "created-network-" + key + "-mismatch")
    if kind == "microsoft.network/virtualnetworks/subnets":
        current, frozen = _subnet_write_properties(actual["properties"]), _subnet_write_properties(expected["properties"])
    elif kind == "microsoft.network/networksecuritygroups":
        associations = _planned_associations(plan, identifier)
        current = _nsg_write_properties(actual["properties"], associations=associations)
        frozen_props = {**copy.deepcopy(expected["properties"]), "subnets": [{"id": key} for key in sorted(associations)]}
        frozen = _nsg_write_properties(frozen_props, associations=associations)
    else:
        current, frozen = copy.deepcopy(actual["properties"]), copy.deepcopy(expected["properties"])
        for key in ("provisioningState", "resourceGuid"):
            current.pop(key, None)
        subnets = current.pop("subnets", [])
        require({resource_id(item["id"]) for item in subnets} ==
                {key for key in plan["mutation_resource_ids"] if resource_type(key) == "microsoft.network/virtualnetworks/subnets"},
                "created-vnet-subnet-set-mismatch")
        for key, default in {"dhcpOptions": {"dnsServers": []}, "virtualNetworkPeerings": [],
                             "enableDdosProtection": False, "enableVmProtection": False}.items():
            current.setdefault(key, default)
            frozen.setdefault(key, default)
        current["addressSpace"]["addressPrefixes"].sort()
        frozen["addressSpace"]["addressPrefixes"].sort()
    require(current == frozen, "created-network-write-properties-mismatch:" + identifier)


def verify_common_network(plan, *, before, after, expected_resources=None):
    """Post-deploy native GET proof; retain evidence and do not roll back on failure."""
    require(digest(before) == plan["snapshot_sha256"], "network-before-evidence-mismatch")
    require(after.get("complete") is True, "complete-post-deployment-inventory-required")
    identifier = resource_id(plan["desired"]["vnet_id"])
    actual = after["resources"]
    for key, value in before["resources"].items():
        if value is None or resource_id(key) == identifier:
            continue
        same = (_retained_nsg_unchanged(value, actual.get(key), _planned_associations(plan, resource_id(key)))
                if resource_type(key) == "microsoft.network/networksecuritygroups" else actual.get(key) == value)
        require(same, "retained-network-resource-changed:" + key)
    old_parent, new_parent = before["resources"].get(identifier), actual.get(identifier)
    _validate_existing(new_parent, identifier)
    if old_parent:
        old, new = copy.deepcopy(old_parent), copy.deepcopy(new_parent)
        old.pop("etag", None)
        new.pop("etag", None)
        old_subnets = {resource_id(s["id"]): s for s in old["properties"].pop("subnets")}
        new_subnets = {resource_id(s["id"]): s for s in new["properties"].pop("subnets")}
        require(old == new and all(new_subnets.get(k) == v for k, v in old_subnets.items()),
                "retained-vnet-configuration-changed")
        added = {key for key in plan["mutation_resource_ids"] if "/subnets/" in key}
        require(set(new_subnets) == set(old_subnets) | added, "unexpected-subnet-addition-or-removal")
    expected = expected_resources if expected_resources is not None else _base_expected_resources(plan)
    require(set(expected) == set(plan["mutation_resource_ids"]), "frozen-compiled-resource-bodies-required")
    require(all(expected.get(key) == value for key, value in _base_expected_resources(plan).items()),
            "frozen-canonical-resource-body-mismatch")
    for key in plan["mutation_resource_ids"]:
        _verify_created_resource(key, actual.get(key), expected[key], plan)
    parent_subnets = {resource_id(item["id"]): item for item in new_parent["properties"].get("subnets", [])}
    for key in plan["mutation_resource_ids"]:
        if resource_type(key) == "microsoft.network/virtualnetworks/subnets":
            require(parent_subnets.get(key) == actual.get(key), "created-subnet-parent-snapshot-mismatch")
    return {"profile": PROFILE, "preserved": True, "before_sha256": digest(before),
            "after_sha256": digest(after), "mutation_resource_ids": plan["mutation_resource_ids"]}


def _deployment_parameters(template, parameters):
    schema = template["parameters"]
    require(not set(parameters) - set(schema), "unknown-common-network-parameter")
    require(all(key in parameters or "defaultValue" in definition for key, definition in schema.items()),
            "required-common-network-parameter-missing")
    types = {"string": str, "bool": bool, "object": dict, "array": list, "int": int}
    for key, value in parameters.items():
        definition = schema[key]
        require(type(value) is types[definition["type"]], "invalid-common-network-parameter-type:" + key)
        require("allowedValues" not in definition or value in definition["allowedValues"],
                "invalid-common-network-parameter-value:" + key)
    return {key: {"value": copy.deepcopy(value)} for key, value in parameters.items()}


def prepare_common_network(*, source_root, desired, inventory, expected_payload_sha256=None, bicep=None,
                           regional_capabilities=None):
    """Coordinator hook after it resolves its saved scope into template parameters."""
    template, proof = _compile_capability(source_root, expected_payload_sha256=expected_payload_sha256, bicep=bicep)
    identifier = resource_id(desired["vnet_id"])
    require(identifier in inventory["resources"], "incomplete-network-inventory")
    plan = plan_common_network(vnet=inventory["resources"][identifier], desired=desired, inventory=inventory)
    _deployment_parameters(template, plan["deployment_parameters"])
    regional = (validate_common_network_region(desired, regional_capabilities,
                subnets=plan["deployment_parameters"]["preservationPlan"]["createSubnets"])
                if regional_capabilities is not None else None)
    return {"can_execute": regional["can_execute"] if regional is not None else True,
            "blockers": regional["blockers"] if regional is not None else [], "commands": [],
            "effects": [{"kind": "create-network-resource", "resource_id": key}
                        for key in plan["mutation_resource_ids"]],
            "regional_service_endpoints": regional,
            "frozen_plan": plan, "expected_resources": expected_resource_bodies(template, plan), "source": proof}


def execute_common_network(prepared, *, cloud, source_root, inventory_collector, assert_lease,
                           bicep=None, poll_interval=5, max_polls=180, sleeper=time.sleep):
    """Native ARM executor; no auth, shell deployment, deletion, RG or MI creation.

    The coordinator owns the durable intent/journal and hub lease. Its collector
    recollects the same complete domain, and assert_lease must affirm the held
    lease. Unknown deployment outcomes raise and retain resources; never roll
    back or silently release the lease. RG/identity substrate is a separate stage.
    Every mutation is preceded by a fresh, read-only regional endpoint preflight;
    failure prevents the entire deployment, including its NSG writes.
    """
    require(prepared.get("can_execute") is True and not prepared.get("blockers"), "network-plan-not-executable")
    require(type(max_polls) is int and max_polls > 0 and poll_interval >= 0, "bounded-network-polling-required")
    plan = prepared["frozen_plan"]
    template, proof = _compile_capability(source_root,
        expected_payload_sha256=prepared["source"]["payload_sha256"], bicep=bicep)
    require(proof["compiled_arm_sha256"] == prepared["source"]["compiled_arm_sha256"],
            "compiled-network-template-changed")
    parameters = _deployment_parameters(template, plan["deployment_parameters"])
    expected = expected_resource_bodies(template, plan)
    require(prepared.get("expected_resources") == expected, "frozen-compiled-resource-bodies-changed")
    require(assert_lease() is True, "shared-hub-lease-required")
    before = inventory_collector()
    identifier = resource_id(plan["desired"]["vnet_id"])
    revalidate_common_network(plan, vnet=before["resources"].get(identifier), inventory=before)
    subscription_id = identifier.split("/")[2]
    name = "afnet-" + digest({"factory": plan["desired"]["factory_id"], "vnet": identifier})[:24]
    deployment_id = f"/subscriptions/{subscription_id}/providers/Microsoft.Resources/deployments/{name}"
    regional = None
    if plan["mutation_resource_ids"]:
        capabilities = collect_service_endpoint_capabilities(cloud, subscription_id=subscription_id,
                                                             location=plan["deployment_parameters"]["location"])
        regional = validate_common_network_region(plan["desired"], capabilities,
            subnets=plan["deployment_parameters"]["preservationPlan"]["createSubnets"])
        if not regional["can_execute"]:
            raise RegionalServiceEndpointError(regional)
        require(assert_lease() is True, "shared-hub-lease-required")
        status, _, _ = cloud.arm("PUT", deployment_id, "2022-09-01", data={
            "location": plan["deployment_parameters"]["location"],
            "properties": {"mode": "Incremental", "template": template, "parameters": parameters}},
            allowed=(200, 201, 202))
        require(status in (200, 201, 202), "network-deployment-outcome-unknown")
        for _ in range(max_polls):
            require(assert_lease() is True, "shared-hub-lease-lost-retain-evidence")
            status, _, deployment = cloud.arm("GET", deployment_id, "2022-09-01", allowed=(200,))
            require(status == 200, "network-deployment-outcome-unknown")
            state = deployment.get("properties", {}).get("provisioningState")
            if state == "Succeeded":
                break
            require(state not in ("Failed", "Canceled", "Cancelled"), "network-deployment-failed-retain-evidence")
            sleeper(poll_interval)
        else:
            raise PreservationError("network-deployment-pending-retain-evidence")
    require(assert_lease() is True, "shared-hub-lease-lost-retain-evidence")
    evidence = verify_common_network(plan, before=before, after=inventory_collector(), expected_resources=expected)
    common_subnet_id = identifier + "/subnets/" + plan["deployment_parameters"]["common_subnet_name"].lower()
    return {"succeeded": True, "outputs": {"vnet_id": identifier, "admin_subnet_id": common_subnet_id,
            "owned_resource_ids": plan["owned_resource_ids"], "preservation_evidence": evidence,
            "regional_service_endpoints": regional,
            "deployment_id": deployment_id if plan["mutation_resource_ids"] else None}}


def plan_peerings(*, hub, spoke, hub_gateway, spoke_gateways, hub_peering_name, spoke_peering_name,
                  owned_resource_ids=(), reused_resource_ids=()):
    """Exact pair only. Hub gateway and grant precede spoke useRemoteGateways.

    Existing matching external children may be approved for reuse, never adopted.
    Changing an owned child requires its etag; unrelated children/parent are not
    included. These are plan operations, not executed HTTP requests.
    """
    hub_id, spoke_id = resource_id(hub["id"]), resource_id(spoke["id"])
    require(hub_id != spoke_id, "peering-requires-distinct-vnets")
    for value, identifier in ((hub, hub_id), (spoke, spoke_id)):
        _validate_existing(value, identifier)
        require(isinstance(value["properties"].get("virtualNetworkPeerings"), list),
                "complete-peering-inventory-required")
    require(not spoke_gateways, "spoke-gateway-conflicts-with-remote-gateway")
    gateway = hub_gateway.get("properties", {})
    require(gateway.get("provisioningState") == "Succeeded" and gateway.get("gatewayType") == "Vpn"
            and any(p.get("properties", {}).get("subnet", {}).get("id", "").lower()
                    == hub_id + "/subnets/gatewaysubnet" for p in gateway.get("ipConfigurations", [])),
            "ready-hub-vpn-gateway-required")
    require(not any(network(a).overlaps(network(b))
                    for a in hub["properties"]["addressSpace"]["addressPrefixes"]
                    for b in spoke["properties"]["addressSpace"]["addressPrefixes"]), "peering-address-overlap")
    owned = {resource_id(x) for x in owned_resource_ids}
    reused = {resource_id(x) for x in reused_resource_ids}
    operations = []
    for parent, target, name, transit, remote in (
        (hub, spoke_id, hub_peering_name, True, False), (spoke, hub_id, spoke_peering_name, False, True)
    ):
        require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", name), "invalid-peering-name")
        identifier = resource_id(parent["id"] + "/virtualNetworkPeerings/" + name)
        peers = parent["properties"]["virtualNetworkPeerings"]
        require(not any(p.get("properties", {}).get("useRemoteGateways") is True
                        and resource_id(p["id"]) != identifier for p in peers) or not remote,
                "another-remote-gateway-already-configured")
        current = next((p for p in peers if resource_id(p["id"]) == identifier), None)
        props = {"remoteVirtualNetwork": {"id": target}, "allowVirtualNetworkAccess": True,
                 "allowForwardedTraffic": True, "allowGatewayTransit": transit, "useRemoteGateways": remote}
        if current:
            _validate_existing(current, identifier)
            require(current["properties"]["remoteVirtualNetwork"]["id"].lower() == target,
                    "peering-target-conflict")
            matches = all(current["properties"].get(k) == v for k, v in props.items() if k != "remoteVirtualNetwork")
            if matches:
                require(identifier in owned | reused, "existing-peering-reuse-approval-required")
                continue
            require(identifier in owned, "unowned-peering-update-forbidden")
            # Only reviewed writable properties can be replayed. Do not drop an
            # unknown writable preview property during an otherwise narrow edit.
            read_only = {"provisioningState", "peeringState", "peeringSyncLevel", "resourceGuid",
                         "remoteAddressSpace", "remoteVirtualNetworkAddressSpace"}
            writable = set(props) | {"doNotVerifyRemoteGateways", "peerCompleteVnets", "localSubnetNames",
                                     "remoteSubnetNames", "enableOnlyIPv6Peering"}
            require(set(current["properties"]) <= writable | read_only, "unreviewed-peering-property")
            body = {k: copy.deepcopy(v) for k, v in current["properties"].items() if k in writable}
            body.update(props)
        else:
            body = props
        operations.append({"method": "PUT", "id": identifier, "api_version": API_VERSION,
                           "data": {"properties": body}, "if_match": current["etag"] if current else None,
                           "must_be_absent": current is None})
    return {"operations": operations, "deletion_resource_ids": [],
            "retained_hub_id": hub_id, "retained_gateway_id": hub_gateway["id"]}
