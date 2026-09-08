#!/usr/bin/env python3
"""Prepare an Azure VPN Client profile for private AI Factory access."""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child(parent: ET.Element, name: str) -> ET.Element | None:
    expected = name.lower()
    return next(
        (item for item in parent if local_name(item.tag) == expected),
        None,
    )


def prepare_profile(
    source: Path,
    output: Path,
    name: str,
) -> None:
    content = source.read_text(encoding="utf-8")
    root = ET.fromstring(content)
    name_element = child(root, "name")
    if name_element is None:
        raise ValueError("The Azure VPN profile has no name element.")
    updated, replacements = re.subn(
        r"(<name(?:\s[^>]*)?>).*?(</name>)",
        rf"\g<1>{escape(name)}\g<2>",
        content,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise ValueError("The Azure VPN profile name could not be updated.")
    ET.fromstring(updated)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    prepare_profile(
        args.input,
        args.output,
        args.name,
    )


if __name__ == "__main__":
    main()
