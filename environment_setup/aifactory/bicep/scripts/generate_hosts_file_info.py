#!/usr/bin/env python3
"""Export a read-only private-endpoint inventory and an optional client hosts fragment."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
RG = re.compile(r"[\w().-]{1,90}")
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.I)


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return default if not value or re.fullmatch(r"\$\([\w.-]+\)", value) else value


@dataclass(frozen=True)
class Scope:
    subscription: str
    resource_group: str

    def __post_init__(self) -> None:
        if not GUID.fullmatch(self.subscription):
            raise ValueError("A valid subscription GUID is required; active CLI subscription is not used implicitly.")
        if not RG.fullmatch(self.resource_group):
            raise ValueError("A valid resource group name is required.")

    @property
    def id(self) -> str:
        return f"/subscriptions/{self.subscription}/resourceGroups/{self.resource_group}"


def configuration(argv: list[str] | None = None) -> tuple[list[Scope], list[Scope], Path | None]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy", nargs="*", help="Legacy pipeline's 12 positional arguments (optional).")
    parser.add_argument("--subscription")
    parser.add_argument("--project-resource-group")
    parser.add_argument("--common-resource-group")
    parser.add_argument("--network-resource-group")
    parser.add_argument("--network-subscription")
    parser.add_argument("--output-dir")
    arguments = sys.argv[1:] if argv is None else argv
    # Legacy prefixes/suffixes such as "-rg" are values, not option switches.
    if len(arguments) == 12 and not arguments[0].startswith("--"):
        args = parser.parse_args([])
        args.legacy = arguments
    else:
        args = parser.parse_args(arguments)
    if args.legacy and len(args.legacy) != 12:
        raise ValueError("Legacy hosts invocation requires exactly 12 quoted arguments.")
    old = dict(zip((
        "SUBSCRIPTION_ID", "RG_PREFIX", "PROJECT_NUMBER", "LOCATION_SUFFIX", "ENVIRONMENT",
        "RG_SUFFIX", "RESOURCE_SUFFIX", "SALT", "SALT_RANDOM", "RANDOM", "PROJECT_PREFIX", "PROJECT_SUFFIX",
    ), args.legacy))

    def setting(name: str, default: str = "") -> str:
        return env(f"HOSTS_{name}", old.get(name, default))

    subscription = args.subscription or setting("SUBSCRIPTION_ID")
    project_rg = args.project_resource_group or setting("PROJECT_RESOURCE_GROUP")
    common_rg = args.common_resource_group or setting("COMMON_RESOURCE_GROUP")
    if not project_rg or not common_rg:
        number = setting("PROJECT_NUMBER")
        location = setting("LOCATION_SUFFIX")
        environment = setting("ENVIRONMENT")
        if environment not in ("dev", "test", "prod") or not location or not re.fullmatch(r"\d{3}", number):
            raise ValueError("Set explicit project/common resource groups or supply project number, location suffix and dev/test/prod.")
        prefix, suffix = setting("RG_PREFIX"), setting("RG_SUFFIX")
        project_rg = project_rg or (
            f"{prefix}{setting('PROJECT_PREFIX')}project{number}-{location}-{environment}"
            f"{suffix}{setting('PROJECT_SUFFIX')}"
        )
        common_rg = common_rg or f"{prefix}{setting('COMMON_NAME', 'esml-common')}-{location}-{environment}{suffix}"
    targets = list(dict.fromkeys([
        Scope(subscription, project_rg),
        Scope(setting("COMMON_SUBSCRIPTION_ID", subscription), common_rg),
    ]))
    scans = list(targets)
    network_rg = args.network_resource_group or setting("VNET_RESOURCE_GROUP")
    if network_rg:
        network = Scope(args.network_subscription or setting("VNET_SUBSCRIPTION_ID", subscription), network_rg)
        if network not in scans:
            scans.append(network)
    output = args.output_dir or setting("OUTPUT_DIR")
    return targets, scans, Path(output) if output else None


def az_json(*args: str) -> object:
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI was not found on PATH.")
    command = [executable]
    if sys.platform == "win32" and Path(executable).suffix.lower() in (".cmd", ".bat"):
        # Same shell-free Windows MSI launch pattern as the dashboard reconciler.
        cli_python = Path(executable).parent.parent / "python.exe"
        if not cli_python.is_file():
            raise RuntimeError(f"Azure CLI Python runtime not found: {cli_python}")
        command = [str(cli_python), "-X", "utf8", "-IBm", "azure.cli"]
    result = subprocess.run(
        [*command, *args, "--output", "json", "--only-show-errors"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"Azure CLI {' '.join(args[:3])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout)


def properties(item: dict) -> dict:
    """Accept both Azure CLI flattened JSON and ARM resource JSON."""
    return item.get("properties", item)


def collect(targets: list[Scope], scans: list[Scope], az=az_json) -> dict:
    warnings: list[str] = []
    mappings: dict[str, set[str]] = {}
    endpoints: list[dict] = []
    seen: set[str] = set()

    def warn(message: str) -> None:
        warnings.append(message)

    def add(fqdn: object, address: object, entry: dict, source: str) -> None:
        if not isinstance(fqdn, str) or not isinstance(address, str):
            warn(f"{entry['id']}: ignored incomplete DNS mapping.")
            return
        host = fqdn.rstrip(".").lower()
        if len(host) > 253 or "." not in host or any(not LABEL.fullmatch(label) for label in host.split(".")):
            warn(f"{entry['id']}: ignored invalid or wildcard FQDN {fqdn!r}.")
            return
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            warn(f"{entry['id']}: ignored invalid IP address {address!r}.")
            return
        if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_link_local:
            warn(f"{entry['id']}: ignored unusable endpoint IP {address!r}.")
            return
        mappings.setdefault(host, set()).add(str(ip))
        record = {"hostname": host, "ip": str(ip), "source": source}
        if record not in entry["mappings"]:
            entry["mappings"].append(record)

    for scope in scans:
        try:
            resources = az("network", "private-endpoint", "list", "--subscription", scope.subscription, "--resource-group", scope.resource_group)
            if not isinstance(resources, list):
                raise ValueError("Private endpoint list is not a JSON array.")
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
            warn(f"Cannot inventory {scope.id}: {error}")
            continue
        for resource in resources:
            if not isinstance(resource, dict):
                warn(f"{scope.id}: ignored malformed private endpoint record.")
                continue
            resource_id = resource.get("id", "")
            if not isinstance(resource_id, str) or not resource_id:
                warn(f"{scope.id}: ignored private endpoint without a resource ID.")
                continue
            if resource_id.lower() in seen:
                continue
            seen.add(resource_id.lower())
            pe = properties(resource)
            connections = (pe.get("privateLinkServiceConnections") or []) + (pe.get("manualPrivateLinkServiceConnections") or [])
            target_ids = [properties(c).get("privateLinkServiceId", "") for c in connections]
            # A shared network RG may host unrelated projects' endpoints. Include only
            # endpoints targeting the requested project/common resource groups.
            if scope not in targets and not any(
                isinstance(rid, str) and rid.lower().startswith(target.id.lower() + "/providers/")
                for rid in target_ids for target in targets
            ):
                continue
            if pe.get("provisioningState", "").lower() != "succeeded" or not connections or any(
                properties(c).get("privateLinkServiceConnectionState", {}).get("status", "").lower() != "approved"
                for c in connections
            ):
                warn(f"{resource_id}: endpoint is not Succeeded/Approved; no hosts entries emitted.")
                continue
            entry = {"id": resource_id, "targets": target_ids, "subnetId": pe.get("subnet", {}).get("id"), "mappings": []}
            endpoints.append(entry)
            for record in pe.get("customDnsConfigs", []) or []:
                for address in record.get("ipAddresses", []) or []:
                    add(record.get("fqdn"), address, entry, "privateEndpoint.customDnsConfigs")
            for reference in pe.get("networkInterfaces", []) or []:
                nic_id = reference.get("id")
                if not nic_id:
                    warn(f"{resource_id}: network interface reference has no ID.")
                    continue
                try:
                    nic = az("network", "nic", "show", "--ids", nic_id)
                    if not isinstance(nic, dict):
                        raise ValueError("Network interface is not a JSON object.")
                except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
                    warn(f"Cannot read {nic_id}: {error}")
                    continue
                for configuration in properties(nic).get("ipConfigurations", []) or []:
                    ip_config = properties(configuration)
                    for fqdn in (ip_config.get("privateLinkConnectionProperties") or {}).get("fqdns", []) or []:
                        add(fqdn, ip_config.get("privateIPAddress", ip_config.get("privateIpAddress")), entry, "networkInterface.ipConfiguration")
            if not entry["mappings"]:
                warn(f"{resource_id}: Azure returned no FQDN/IP mappings; names will not be guessed.")
    hosts = []
    for host, addresses in sorted(mappings.items()):
        if len(addresses) != 1:
            warn(f"{host}: multiple endpoint IPs ({', '.join(sorted(addresses))}); omitted instead of selecting an arbitrary route.")
        else:
            hosts.append({"hostname": host, "ip": next(iter(addresses))})
    if not hosts:
        warn("No unambiguous hosts entries found. Review the requested scopes, private endpoints and warnings.")
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "partial" if warnings else "complete",
        "scopes": [scope.id for scope in scans],
        "endpoints": endpoints,
        "hosts": hosts,
        "warnings": warnings,
    }


def fragment(report: dict) -> str:
    lines = [
        "# AI Factory private-endpoint hosts fragment",
        f"# Generated: {report['generatedAt']}",
        f"# Inventory status: {report['status']}",
        "# Optional fallback only. Azure VPN normally uses private DNS, not a hosts file.",
        "# Review IP routes and conflicts before merging; do not replace the whole system hosts file.",
        "# This does not configure VPN routes, DNS, firewall rules, or Foundry's server-side DNS.",
        "# Regenerate when endpoints change. Use only on a client with private network connectivity.",
    ]
    lines.extend(f"{item['ip']} {item['hostname']}" for item in report["hosts"])
    return "\n".join(lines) + "\n"


def write_output(directory: Path, report: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in (
        ("hosts.fragment.txt", fragment(report)),
        ("private-endpoints.json", json.dumps(report, indent=2) + "\n"),
    ):
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8", newline="\n", delete=False) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        try:
            temporary.replace(directory / name)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    try:
        targets, scans, output = configuration(argv)
        report = collect(targets, scans)
        if output:
            write_output(output, report)
        print(fragment(report), end="")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}", file=sys.stderr)
        if output:
            print(f"Hosts fragment and endpoint inventory written to: {output}", file=sys.stderr)
        return 0 if report["hosts"] else 1
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: Hosts inventory could not be generated: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
