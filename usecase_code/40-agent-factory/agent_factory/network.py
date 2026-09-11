from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from .azure import AzureSession
from .config import Target

NETWORK_API = "2024-05-01"
FOUNDRY_ZONES = (
    "privatelink.cognitiveservices.azure.com",
    "privatelink.openai.azure.com",
    "privatelink.services.ai.azure.com",
)


def private_endpoint_checks(target: Target) -> list[dict]:
    hosts = [
        urlsplit(target.project_endpoint).hostname,
        f"{target.account_name}.openai.azure.com",
        urlsplit(target.search_endpoint).hostname,
        f"{target.storage_name}.blob.core.windows.net",
    ]
    result = []
    for host in hosts:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        private = bool(addresses) and all(ipaddress.ip_address(value).is_private for value in addresses)
        reachable = False
        error = ""
        if private:
            try:
                with socket.create_connection((host, 443), timeout=5):
                    reachable = True
            except OSError as exc:
                error = str(exc)
        else:
            error = "Resolves outside the private network. Check the hub DNS zone group and VPN DNS."
        result.append({"host": host, "addresses": addresses, "private": private,
                       "reachable": reachable, "error": error})
    return result


def repair_foundry_dns(session: AzureSession, target: Target, *, dns_subscription_id: str,
                       dns_resource_group: str, apply: bool = False) -> dict:
    """Add missing associations to the existing group, never replace policy ownership."""
    endpoint_id = f"{target.group_id}/providers/Microsoft.Network/privateEndpoints/{target.account_name}-pend"
    endpoint = session.arm("GET", endpoint_id, api_version=NETWORK_API)
    connections = endpoint["properties"]["privateLinkServiceConnections"]
    if not any(
        item["properties"]["privateLinkServiceId"].lower() == target.account_id.lower()
        and item["properties"]["privateLinkServiceConnectionState"]["status"] == "Approved"
        for item in connections
    ):
        raise RuntimeError("The selected Foundry account does not have an approved private endpoint.")
    groups = session.arm("GET", f"{endpoint_id}/privateDnsZoneGroups", api_version=NETWORK_API)["value"]
    if len(groups) != 1:
        raise RuntimeError("Expected one existing DNS zone group. Ask the hub DNS owner to configure it.")
    group = groups[0]
    current = group["properties"]["privateDnsZoneConfigs"]
    desired = [{"name": item["name"], "properties": {
        "privateDnsZoneId": item["properties"]["privateDnsZoneId"],
    }} for item in current]
    ids = {item["properties"]["privateDnsZoneId"].lower() for item in desired}
    missing = []
    for zone in FOUNDRY_ZONES:
        zone_id = (f"/subscriptions/{dns_subscription_id}/resourceGroups/{dns_resource_group}"
                   f"/providers/Microsoft.Network/privateDnsZones/{zone}")
        session.arm("GET", zone_id, api_version="2020-06-01")
        if zone_id.lower() not in ids:
            missing.append(zone)
            desired.append({"name": zone.replace(".", "-"), "properties": {"privateDnsZoneId": zone_id}})
    result = {"resource_id": group["id"], "missing_zones": missing, "applied": False,
              "policy_note": "The hub policy owner must retain these Foundry zones in future remediations."}
    if apply and missing:
        etag = group.get("etag")
        if not etag:
            raise RuntimeError("DNS zone group has no ETag; refusing an unsafe concurrent update.")
        session.request(
            "PUT", f"https://management.azure.com{group['id']}?api-version={NETWORK_API}",
            {"properties": {"privateDnsZoneConfigs": desired}}, headers={"If-Match": etag},
        )
        verified = session.arm("GET", group["id"], api_version=NETWORK_API)
        actual = {item["properties"]["privateDnsZoneId"].lower()
                  for item in verified["properties"]["privateDnsZoneConfigs"]}
        if not {item["properties"]["privateDnsZoneId"].lower() for item in desired} <= actual:
            raise RuntimeError("DNS zone update did not retain all requested associations.")
        result["applied"] = True
    return result
