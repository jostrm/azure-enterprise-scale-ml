#!/usr/bin/env python3
"""Adopt this factory's existing Azure resources into the Terraform state (Bicep parity: adopt, then update in place).

The Registered Full bootstrap creates the common resource group, the VNet with its subnets and NSGs, the own hub
and the seeding Key Vault before the common workflow runs. infra-common.yml PUTs such resources again
(create-or-update); azurerm and azapi refuse to create a resource that exists:

    Error: a resource with the ID "<ARM id>" already exists - to be managed via Terraform this resource needs to be
    imported into the State. ...
      with <resource address>,

aif-tf-adopt.sh (the plan-and-apply loop of infra-common-terraform.yml) hands each failed round's stderr to
`adopt`, which writes one Terraform import block per such diagnostic into the root module (aif_adopted_imports.tf,
on the runner only). The next round plans the import together with any in-place update and applies both.
`check-plan` stops a plan that would delete or replace an adopted resource before it is applied.

    tf_adopt.py adopt --errors FILE --imports FILE --subscription ID --resource-group NAME [--resource-group NAME]
                      [--plan-json -]   (the failed round's saved plan on stdin: azapi API versions)
        0: new import blocks written; 3: nothing (new) to adopt; 2: refused, nothing written
    terraform show -json tfplan | tf_adopt.py check-plan --imports FILE
        0: safe to apply; 2: the plan deletes or replaces an adopted resource

Only ids inside the given subscription and resource groups (this factory's common group, and the VNet group when the
configuration names one) are adopted; one id outside them refuses the whole round. Standard library only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ALREADY_EXISTS = re.compile(r'resource with the ID "(?P<id>[^"]+)" already exists - to be managed via Terraform '
                            r'this resource needs to be imported into the State', re.IGNORECASE)
DIAGNOSTIC_START = re.compile(r"^(Error|Warning): ")
WITH = re.compile(r"^with (?P<address>\S+),$")
# A resource address: module path, resource type and name, optional count index or for_each key per step.
_KEY = r'(\[(\d+|"[^"\\\]]*")\])?'
ADDRESS = re.compile(rf'^(module\.[A-Za-z_][\w-]*{_KEY}\.)*[A-Za-z_][\w-]*\.[A-Za-z_][\w-]*{_KEY}$')
IMPORT_BLOCK = re.compile(r'^import \{\n  to = (?P<address>\S+)\n  id = "(?P<id>(?:[^"\\]|\\.)*)"\n\}$', re.MULTILINE)
HEADER = ("# Generated on the runner by terraform/tools/tf_adopt.py (infra-common-terraform.yml): resources of this\n"
          "# factory that existed before the run, adopted into the state and then updated in place. Never committed.\n")


def _lines(text: str) -> list[str]:
    """The diagnostic lines without a terminal's box drawing, stripped."""
    return [line.lstrip("│╷╵ \t").rstrip() for line in text.splitlines()]


def existing_resources(text: str) -> list[tuple[str, str]]:
    """(address, ARM id) of every "already exists - ... needs to be imported" diagnostic, in order, once each."""
    found: list[tuple[str, str]] = []
    block: list[str] = []
    for line in [*_lines(text), "Error: "]:
        if DIAGNOSTIC_START.match(line):
            body = " ".join(part for part in block if part)
            match = ALREADY_EXISTS.search(body)
            address = next((WITH.match(part).group("address") for part in block if WITH.match(part)), None)
            if match and address and (address, match.group("id")) not in found:
                found.append((address, match.group("id")))
            block = []
        block.append(line)
    return found


def in_scope(resource_id: str, subscription: str, resource_groups: list[str]) -> bool:
    """True when the id lies in the subscription and one of the (non-empty) resource groups, case-insensitively.

    The id may be an azurerm composite id such as a diagnostic setting's "<resource id>|<name>"."""
    parts = resource_id.split("|", 1)[0].split("?", 1)[0].strip().strip("/").split("/")
    groups = {group.lower() for group in resource_groups if group}
    return (resource_id.startswith("/") and len(parts) >= 4 and parts[0].lower() == "subscriptions"
            and parts[1].lower() == subscription.lower() and parts[2].lower() == "resourcegroups"
            and parts[3].lower() in groups)


def _hcl_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("${", "$${").replace("%{", "%%{") + '"'


def import_block(address: str, resource_id: str) -> str:
    return f"import {{\n  to = {address}\n  id = {_hcl_string(resource_id)}\n}}\n"


def adopted(imports: Path) -> dict[str, str]:
    """address -> id of the import blocks this tool wrote."""
    if not imports.is_file():
        return {}
    unescape = lambda value: re.sub(r"\\(.)", r"\1", value).replace("$${", "${").replace("%%{", "%{")  # noqa: E731
    return {match.group("address"): unescape(match.group("id"))
            for match in IMPORT_BLOCK.finditer(imports.read_text(encoding="utf-8"))}


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def azapi_api_versions(plan_text: str) -> dict[str, str]:
    """address -> API version of every azapi_resource in a saved plan (`terraform show -json`), read best effort.

    azapi imports an id without ?api-version= with the newest version of the type; the configured one keeps the
    adopted resource read (and later updated) exactly as the configuration declares it."""
    try:
        plan = json.loads(plan_text) if plan_text.strip() else {}
    except ValueError:
        return {}
    versions = {}
    for change in plan.get("resource_changes", []) or []:
        declared = str(((change.get("change") or {}).get("after") or {}).get("type") or "")
        if change.get("type") == "azapi_resource" and "@" in declared:
            versions[change.get("address", "")] = declared.rsplit("@", 1)[1]
    return versions


def adopt(errors: Path, imports: Path, subscription: str, resource_groups: list[str], plan_text: str = "") -> int:
    found = existing_resources(errors.read_text(encoding="utf-8", errors="replace"))
    if not found:
        return 3
    versions = azapi_api_versions(plan_text)
    found = [(address, resource_id + ("?api-version=" + versions[address]
                                      if address in versions and "?" not in resource_id else ""))
             for address, resource_id in found]
    refused = [(address, resource_id) for address, resource_id in found
               if not ADDRESS.match(address) or not in_scope(resource_id, subscription, resource_groups)]
    if refused:
        allowed = ", ".join(group for group in resource_groups if group)
        for address, resource_id in refused:
            _say(f"::error::tf_adopt: {resource_id} ({address}) already exists outside this factory's subscription "
                 f"{subscription} and resource groups {allowed}; it is not adopted. Nothing was imported.")
        return 2
    known = adopted(imports)
    new = [(address, resource_id) for address, resource_id in found if address not in known]
    if not new:
        _say("tf_adopt: every existing resource in this error is adopted already; not adopting again.")
        return 3
    text = imports.read_text(encoding="utf-8") if imports.is_file() else HEADER
    imports.write_text(text + "".join(import_block(address, resource_id) for address, resource_id in new),
                       encoding="utf-8", newline="\n")
    for address, resource_id in new:
        _say(f"::notice::tf_adopt: adopting the existing {resource_id} as {address} (imported, then updated in place).")
    return 0


def check_plan(plan: dict, imports: Path) -> int:
    known = adopted(imports)
    offending = [(change.get("address", ""), change.get("change", {}).get("actions", []))
                 for change in plan.get("resource_changes", []) or []
                 if "delete" in change.get("change", {}).get("actions", [])
                 and (change.get("address") in known or change.get("change", {}).get("importing"))]
    for address, actions in offending:
        verb = "replace" if "create" in actions else "delete"
        _say(f"::error::tf_adopt: refusing to apply: the plan would {verb} {address}, an existing resource this run "
             f"adopted ({known.get(address, 'being imported')}). Bicep updates it in place; align the configuration "
             "with the resource (for example its name, location or SKU) or remove the resource deliberately, then "
             "run again.")
    return 2 if offending else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    adopt_parser = commands.add_parser("adopt")
    adopt_parser.add_argument("--errors", type=Path, required=True)
    adopt_parser.add_argument("--imports", type=Path, required=True)
    adopt_parser.add_argument("--subscription", required=True)
    adopt_parser.add_argument("--resource-group", action="append", default=[], dest="resource_groups")
    adopt_parser.add_argument("--plan-json", help="'-': the failed round's saved plan as JSON on stdin (optional)")
    check_parser = commands.add_parser("check-plan")
    check_parser.add_argument("--imports", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "adopt":
        return adopt(args.errors, args.imports, args.subscription, args.resource_groups,
                     sys.stdin.read() if args.plan_json == "-" else "")
    return check_plan(json.load(sys.stdin), args.imports)


if __name__ == "__main__":
    raise SystemExit(main())
