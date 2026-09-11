"""Initialize only a zero-factory register; never migrate or generate projections."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4


TEMPLATE = Path(__file__).absolute().parents[1] / "templates" / "azurefactory" / "register.json"
EMPTY_DOCUMENT = {
    "schema_version": 2, "generation": "new",
    "factories": [], "configurations": {}, "bindings": {},
}
MAX_REGISTER_BYTES = 16 * 1024 * 1024


def ordinary(path):
    """Check before resolving: symlinks and Windows reparse points are not roots."""
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Symbolic links/junctions are not supported: {item}")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError(f"Expected an ordinary file or directory: {item}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError(f"Hard-linked files are not supported: {item}")
    return path


def read_document(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("Nonfinite JSON value")

    ordinary(path)
    if not path.is_file() or path.stat().st_size > MAX_REGISTER_BYTES:
        raise ValueError(f"Expected a register file of at most 16 MiB: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"),
                              object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Malformed register JSON: {path}") from exc
    return document


def check_envelope(document):
    """Recognize v2 storage, not validate deployment settings (the catalog owns those)."""
    fields = {"schema_version", "generation", "factories", "configurations", "bindings"}
    if (not isinstance(document, dict) or not fields <= document.keys()
            or document.keys() - fields - {"ownership_evidence", "migration_receipt"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 2
            or not isinstance(document["generation"], str)
            or not isinstance(document["factories"], list)
            or not isinstance(document["configurations"], dict)
            or not isinstance(document["bindings"], dict)):
        raise ValueError("Unsupported azurefactory/register.json envelope; use the catalog API.")
    identifiers = set()
    for factory in document["factories"]:
        if (not isinstance(factory, dict) or not isinstance(factory.get("id"), str)
                or not isinstance(factory.get("key"), str)
                or not isinstance(factory.get("kind"), str)
                or not isinstance(factory.get("scale_sets"), list)
                or not isinstance(factory.get("projects"), list)
                or factory["id"] in identifiers):
            raise ValueError("Malformed register factory envelope; use the catalog API.")
        identifiers.add(factory["id"])
        configuration = document["configurations"].get(factory["id"])
        if (not isinstance(configuration, dict)
                or set(configuration) != {"factory", "scale_sets", "projects", "variables"}
                or any(not isinstance(value, dict) for value in configuration.values())):
            raise ValueError("Malformed register configuration envelope; use the catalog API.")
    if (set(document["configurations"]) != identifiers
            or set(document["bindings"]) - identifiers
            or any(not isinstance(value, dict) or set(value) - {"ado", "gha"}
                   for value in document["bindings"].values())
            or not isinstance(document.get("ownership_evidence", {}), dict)
            or ("migration_receipt" in document and not isinstance(document["migration_receipt"], dict))):
        raise ValueError("Malformed register ownership/binding envelope; use the catalog API.")


def target_root(value, *, staging=False):
    raw = os.fspath(value)
    root = Path(raw)
    if (not root.is_absolute() or ".." in root.parts or raw.startswith(("\\\\", "//"))
            or any(ord(character) < 32 for character in raw)
            or any(re.search(r'[<>:"|?*]', part) or part != part.rstrip(" .")
                   for part in root.parts[1:])
            or root.name.casefold() != "azurefactory"):
        raise ValueError("Select an absolute local azurefactory folder without traversal.")
    ordinary(root)
    if not root.parent.is_dir() or (root.exists() and not root.is_dir()):
        raise ValueError("The parent must exist and azurefactory must be a directory.")
    if staging and root.parent.name.casefold() != "aifactory-templates":
        raise ValueError("An inactive starter must be staged directly under aifactory-templates.")
    for ancestor in root.parents:
        if (ancestor.name.casefold() in {"aifactory", "azurefactory", "aifactory-templates"}
                and not (staging and ancestor == root.parent)):
            raise ValueError("Do not nest Azure Factory storage inside another factory/template root.")
        if (ordinary(ancestor / "register.json").exists()
                or ordinary(ancestor / "config-wizard" / "catalog.json").exists()):
            raise ValueError("An ancestor already contains catalog storage; mixed roots are unsafe.")
    for relative in ("variables.json", "aifactory", "config-wizard", "azurefactory"):
        if ordinary(root / relative).exists():
            raise ValueError(f"Mixed legacy/new folder layout at {root / relative}; use explicit migration.")
    return root


def initialize(value, *, staging=False):
    root = target_root(value, staging=staging)
    register = ordinary(root / "register.json")
    if register.exists():
        document = read_document(register)
        check_envelope(document)
        if staging and document != EMPTY_DOCUMENT:
            raise ValueError("Existing staged register is not the empty starter; nothing was changed.")
        return register, False
    if root.exists() and any(root.iterdir()):
        raise ValueError("Without register.json the azurefactory destination must be empty; nothing was changed.")
    template = read_document(TEMPLATE)
    check_envelope(template)
    if template != EMPTY_DOCUMENT:
        raise ValueError("The central starter must contain exactly the empty v2 document.")
    data = (json.dumps(template, indent=2, allow_nan=False) + "\n").encode("utf-8")
    root.mkdir(exist_ok=True)
    target_root(root, staging=staging)
    # Publish a complete file with atomic no-clobber semantics; never os.replace().
    pending = root.parent / (".azurefactory-register-" + uuid4().hex + ".pending")
    try:
        with pending.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        ordinary(root)
        if not register.exists() and any(root.iterdir()):
            raise ValueError("The destination changed during initialization; nothing was published.")
        try:
            os.link(pending, register)
        except FileExistsError:
            ordinary(pending).unlink()
            document = read_document(register)
            check_envelope(document)
            if staging and document != EMPTY_DOCUMENT:
                raise ValueError("Existing staged register is not the empty starter; nothing was changed.")
            return register, False
        pending.unlink()
    finally:
        if pending.exists():
            pending.unlink()
    return register, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Absolute path ending in azurefactory (not a repository or aifactory).")
    parser.add_argument("--stage-template", action="store_true",
                        help="Stage an inactive starter only under aifactory-templates/azurefactory.")
    args = parser.parse_args()
    try:
        register, created = initialize(args.root, staging=args.stage_template)
    except (OSError, ValueError) as exc:
        print(f"ERROR: Cannot initialize azurefactory/register.json: {exc}", file=sys.stderr)
        return 2
    if args.stage_template:
        print(f"{'Staged empty' if created else 'Preserved existing'} starter: {register}")
        print("Inactive template only: no factory, project, imported configuration or deployment data.")
        return 0
    print(f"{'Initialized empty' if created else 'Preserved existing'} register: {register}")
    print("No factory was registered or deployed. Existing aifactory configuration is not imported.")
    print("Use explicit catalog creation or reviewed migration; populated registers need catalog validation.")
    if (register.parent.parent / "aifactory").exists():
        print("A sibling legacy aifactory is preserved, but legacy launchers refuse this mixed repository.")
        print("Keep a separate legacy execution repository; initialization does not authorize deployment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
