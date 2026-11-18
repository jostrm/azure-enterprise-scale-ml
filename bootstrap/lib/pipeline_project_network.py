"""Project subnets for pipelines-only plans, allocated by the legacy subnetCalc_v2.ps1.

The allocation rule lives only in that PowerShell script (the legacy ADO/GHA
project pipelines run it too). This module reads the VNet through the
authenticated ARM reader, or describes the planned common VNet when the common
network deploys in the same plan, passes that inventory to the script (which
then makes no Azure call) and maps its result to the project template
parameters, including the subnet IDs 31-network would output. BYO subnets
(BYO_subnets=true with the subnetProj* names in variables.json) never allocate.
"""

import json
from pathlib import Path
import tempfile

from pipeline_lifecycle import require

ALLOCATOR = "environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1"
NETWORK_API = "2023-09-01"
# CIDR key -> (subnet suffix, template ID parameter, 31-network existence flag); names as 31-network creates them.
SUBNETS = {
    "genaiSubnetCidr": ("genai", "genaiSubnetId", "sntGenaiExists"),
    "aksSubnetCidr": ("aks", "aksSubnetId", "sntAksExists"),
    "aks2SubnetCidr": ("aks-002", "aks2SubnetId", "sntAks002Exists"),
    "acaSubnetCidr": ("aca", "acaSubnetId", "sntAcaExists"),
    "aca2SubnetCidr": ("aca-002", "aca2SubnetId", "sntAca002Exists"),
    "webappSubnetCidr": ("webapp", "webappSubnetId", "sntWebappExists"),
    "logicappSubnetCidr": ("logicapp", "logicappSubnetId", "sntLogicappExists"),
    "dbxPubSubnetCidr": ("dbxpub", None, "sntDatabricksPubExists"),
    "dbxPrivSubnetCidr": ("dbxpriv", None, "sntDatabricksPrivExists"),
}
TRIGGERS = ("genaiSubnetCidr", "aksSubnetCidr", "genaiSubnetId", "aksSubnetId", "acaSubnetId")


def required(template, values):
    """Managed networks only, and only when a template asks for subnet inputs the variables do not hold."""
    if str(values.get("BYO_subnets", "false")).lower() == "true":
        return False
    schema = template.get("parameters", {})
    return any(name in schema and not values.get(name) for name in TRIGGERS)


def _names(values, target):
    # Same formulas as subnetCalc_v2.ps1 and 12-networkCommon.bicep; the script's plan file must agree.
    env, suffix = target["environment"], values["admin_locationSuffix"]
    vnet = values.get("vnetNameFull_param") or f"{values['vnetNameBase']}-{suffix}-{env}{values['admin_commonResourceSuffix']}"
    group = values.get("vnetResourceGroup_param") or (
        f"{values['admin_aifactoryPrefixRG']}{values['vnetResourceGroupBase']}-{suffix}-{env}{values['admin_aifactorySuffixRG']}")
    return vnet, group


def _planned(common):
    rng = str(common.get("cidr_range", ""))
    cidr = lambda value: str(value).replace("XX", rng)
    subnets = [(common.get("common_subnet_name"), common.get("common_subnet_cidr")),
               (str(common.get("common_subnet_name", "")) + "-scoring", common.get("common_subnet_scoring_cidr")),
               (common.get("common_pbi_subnet_name"), common.get("common_pbi_subnet_cidr")),
               (common.get("common_bastion_subnet_name"), common.get("common_bastion_subnet_cidr")),
               ("ai-gateway-apim", common.get("ai_gateway_apim_cidr")), ("ai-gateway-app", common.get("ai_gateway_app_cidr"))]
    require(common.get("common_vnet_cidr"), "planned-common-vnet-cidr-required")
    return [cidr(common["common_vnet_cidr"])], [{"name": name, "addressPrefix": cidr(value)}
                                               for name, value in subnets if name and value]


def _live(body):
    properties = body.get("properties", {})
    prefixes = properties.get("addressSpace", {}).get("addressPrefixes")
    require(isinstance(prefixes, list) and prefixes, "project-network-vnet-address-space-required")
    subnets = []
    for row in properties.get("subnets", []):
        inner = row.get("properties", {})
        item = {"name": row.get("name"), "id": row.get("id")}
        if inner.get("addressPrefixes"):
            item["addressPrefixes"] = inner["addressPrefixes"]
        if inner.get("addressPrefix"):
            item["addressPrefix"] = inner["addressPrefix"]
        subnets.append(item)
    return prefixes, subnets


def allocate(cloud, source_root, values, target, project_number, *, planned_common=None):
    """Return the network parameters for one project: CIDRs, vnetResourceGroup, subnet IDs and existence flags."""
    vnet, group = _names(values, target)
    vnet_id = (f"/subscriptions/{target['subscription_id']}/resourceGroups/{group}"
               f"/providers/Microsoft.Network/virtualNetworks/{vnet}")
    status, _, body = cloud.arm("GET", vnet_id, NETWORK_API, allowed=(200, 404))
    if status == 200:
        prefixes, subnets = _live(body)
    else:
        require(planned_common is not None, "project-network-vnet-not-found")
        prefixes, subnets = _planned(planned_common)
    for item in subnets:
        item.setdefault("id", vnet_id + "/subnets/" + str(item["name"]))
    script = Path(source_root).resolve() / ALLOCATOR
    require(script.is_file(), "project-network-allocator-unavailable")
    with tempfile.TemporaryDirectory(prefix="esaf-network-") as work:
        inventory, plan = Path(work) / "vnet.json", Path(work) / "plan.json"
        inventory.write_text(json.dumps({"id": vnet_id, "name": vnet, "addressSpace": {"addressPrefixes": prefixes},
                                         "subnets": subnets}), encoding="utf-8")
        arguments = {
            "filePath": work, "env": target["environment"], "subscriptionId": target["subscription_id"],
            "prjResourceSuffix": values["admin_prjResourceSuffix"], "projectNumber": project_number,
            "aifactorySuffixRGADO": values["admin_aifactorySuffixRG"],
            "commonResourceSuffixADO": values["admin_commonResourceSuffix"],
            "locationADO": values["admin_location"], "locationSuffixADO": values["admin_locationSuffix"],
            "projectTypeADO": values["admin_projectType"], "commonRGNamePrefixVar": values["admin_aifactoryPrefixRG"],
            "vnetNameBase": values["vnetNameBase"], "vnetResourceGroupBase": values["vnetResourceGroupBase"],
            "vnetResourceGroup_param": values.get("vnetResourceGroup_param"),
            "vnetNameFull_param": values.get("vnetNameFull_param"),
            "enableLogicApps": values.get("enableLogicApps"), "logicAppType": values.get("logicAppType"),
            "byoASEv3": values.get("byoASEv3"),
            "enablePublicAccessWithPerimeter": values.get("enablePublicAccessWithPerimeter"),
            "vnetInventoryFile": str(inventory), "planFile": str(plan)}
        argv = ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script)]
        for name, value in arguments.items():
            if value not in (None, ""):
                argv += ["-" + name, str(value)]
        cloud.command(argv, cwd=str(script.parent))
        result = json.loads(plan.read_text(encoding="utf-8-sig"))
    require(result.get("vnetName") == vnet and result.get("vnetResourceGroup") == group,
            "project-network-naming-drift")
    allocated = result.get("subnets") or {}
    require(isinstance(allocated, dict) and allocated.get("genaiSubnetCidr") or allocated.get("aksSubnetCidr"),
            "project-network-allocation-empty")
    existing = {str(item["name"]).lower(): item for item in subnets}
    network = {"vnetResourceGroup": group}
    for key, cidr in allocated.items():
        require(key in SUBNETS, "project-network-unknown-subnet:" + key)
        suffix, id_parameter, flag = SUBNETS[key]
        name = f"snt-prj{project_number}-{suffix}"
        found = existing.get(name)
        network[key] = cidr
        network[flag] = found is not None
        if id_parameter:
            network[id_parameter] = found["id"] if found else vnet_id + "/subnets/" + name
    return network
