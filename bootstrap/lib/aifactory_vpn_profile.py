#!/usr/bin/env python3
"""Prepare an Azure VPN Client profile for private AI Factory access."""

from __future__ import annotations

import argparse
import ipaddress
import xml.etree.ElementTree as ET
from pathlib import Path


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def qualified(parent: ET.Element, name: str) -> str:
    value = namespace(parent.tag)
    return f"{{{value}}}{name}" if value else name


def child(parent: ET.Element, name: str) -> ET.Element | None:
    expected = name.lower()
    return next(
        (item for item in parent if local_name(item.tag) == expected),
        None,
    )


def ensure_child(parent: ET.Element, name: str) -> ET.Element:
    existing = child(parent, name)
    if existing is not None:
        return existing
    return ET.SubElement(parent, qualified(parent, name))


def prepare_profile(
    source: Path,
    output: Path,
    name: str,
    dns_server: str,
    routes: list[str],
) -> None:
    tree = ET.parse(source)
    root = tree.getroot()

    name_element = child(root, "name")
    if name_element is None:
        name_element = ET.SubElement(root, qualified(root, "name"))
    name_element.text = name

    client_config = ensure_child(root, "clientconfig")
    for key in list(client_config.attrib):
        if local_name(key) == "nil":
            del client_config.attrib[key]

    dns_servers = ensure_child(client_config, "dnsservers")
    existing_dns = {
        (item.text or "").strip()
        for item in dns_servers
        if local_name(item.tag) == "dnsserver"
    }
    ipaddress.ip_address(dns_server)
    if dns_server not in existing_dns:
        element = ET.SubElement(
            dns_servers,
            qualified(dns_servers, "dnsserver"),
        )
        element.text = dns_server

    include_routes = ensure_child(client_config, "includeroutes")
    existing_routes = set()
    for route in include_routes:
        if local_name(route.tag) != "route":
            continue
        destination = child(route, "destination")
        mask = child(route, "mask")
        if destination is not None and mask is not None:
            existing_routes.add(
                ((destination.text or "").strip(), (mask.text or "").strip())
            )
    for value in routes:
        network = ipaddress.ip_network(value, strict=True)
        key = (str(network.network_address), str(network.prefixlen))
        if key in existing_routes:
            continue
        route = ET.SubElement(include_routes, qualified(include_routes, "route"))
        destination = ET.SubElement(route, qualified(route, "destination"))
        destination.text = key[0]
        mask = ET.SubElement(route, qualified(route, "mask"))
        mask.text = key[1]
        existing_routes.add(key)

    ET.indent(tree, space="  ")
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--dns-server", required=True)
    parser.add_argument("--route", action="append", default=[])
    args = parser.parse_args()
    prepare_profile(
        args.input,
        args.output,
        args.name,
        args.dns_server,
        args.route,
    )


if __name__ == "__main__":
    main()
