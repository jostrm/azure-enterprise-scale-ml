"""Opt-in local bootstrap merge; back up changed files, never remove paths."""

import argparse
from datetime import datetime, timezone
import filecmp
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import initialize_azurefactory as starter


class Merge:
    def __init__(self, root):
        self.root = starter.ordinary(root)
        if not root.is_dir():
            raise ValueError(f"Repository root must exist: {root}")
        self.directories = set()
        self.files = {}

    def directory(self, relative):
        destination = self.root / relative
        starter.ordinary(destination)
        if destination.exists() and not destination.is_dir():
            raise ValueError(f"Cannot replace a file with a directory: {destination}")
        self.directories.add(destination)

    def file(self, source, relative, *, preserve=False):
        if isinstance(source, Path):
            starter.ordinary(source)
            if not source.is_file():
                raise ValueError(f"Missing bootstrap source: {source}")
        destination = self.root / relative
        starter.ordinary(destination)
        if destination.exists() and not destination.is_file():
            raise ValueError(f"Cannot replace a directory with a file: {destination}")
        if preserve and destination.exists():
            print(f"Preserved existing: {destination}")
            return
        self.directory(Path(relative).parent)
        self.files[destination] = source

    def tree(self, source, relative, *, api=False):
        starter.ordinary(source)
        if not source.is_dir():
            raise ValueError(f"Missing bootstrap source directory: {source}")
        self.directory(relative)
        for child in sorted(source.iterdir()):
            name = child.name
            if name in {"__pycache__", ".git", ".pytest_cache", ".venv"} or name.endswith(".pyc"):
                continue
            if api:
                if child.is_dir() and (name.startswith(".") or name in {
                        "node_modules", "build", "dist", "venv"} or name.endswith(".egg-info")):
                    continue
                if not child.is_dir() and (
                        (name.startswith(".") and name != ".gitignore")
                        or (child.suffix not in {".py", ".mjs", ".ps1", ".json", ".toml", ".md"}
                            and name != ".gitignore")
                        or name.endswith((".receipt.json", ".review.json", ".private.json"))):
                    continue
            target = Path(relative) / name
            if child.is_dir():
                self.tree(child, target, api=api)
            else:
                self.file(child, target, preserve=name == ".gitignore")

    def execute(self):
        changed = []
        for destination, source in self.files.items():
            same = destination.exists() and (
                filecmp.cmp(source, destination, shallow=False) if isinstance(source, Path)
                else destination.read_bytes() == source)
            if not same:
                changed.append((destination, source))
        replaced = [destination for destination, _ in changed if destination.exists()]
        if replaced:
            backup = self.root / ".aifactory-backups" / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex)
            starter.ordinary(backup)
            backup.parent.mkdir(mode=0o700, exist_ok=True)
            backup.mkdir(mode=0o700)
            print(f"Backup (keep private; do not commit): {backup}", flush=True)
            # Finish every backup before refreshing any existing file.
            for destination in replaced:
                target = backup / destination.relative_to(self.root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(starter.ordinary(destination), target)
        for directory in sorted(self.directories, key=lambda path: len(path.parts)):
            starter.ordinary(directory).mkdir(parents=True, exist_ok=True)
        for destination, source in changed:
            starter.ordinary(destination)
            if isinstance(source, Path):
                shutil.copy2(starter.ordinary(source), destination)
            else:
                # Generated starter/placeholder files are only planned when absent.
                with destination.open("xb") as stream:
                    stream.write(source)
            if destination.suffix == ".sh":
                destination.chmod(destination.stat().st_mode | 0o111)
        print(f"Refreshed {len(changed)} files; no files or directories removed.")


def bundle(merge, source):
    aliases = {
        "02a-GH-bootstrap-files.sh": "02-GH-bootstrap-files.sh",
        "03a-GH-bootstrap-files-no-env-overwrite.sh": "03-GH-bootstrap-files-no-env-overwrite.sh",
        "02b-ADO-YAML-bootstrap-files.sh": "02-ADO-YAML-bootstrap-files.sh",
        "03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh": "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh",
    }
    for name in ("01-aif-copy-aifactory-templates.sh", "11-ESML-upload-lake-structure.sh", *aliases):
        merge.file(source / name, aliases.get(name, name))
    for script in sorted(source.glob("*.sh")):
        if script.name not in aliases and script.name != "00-aif-add-submodule.sh":
            merge.file(script, script.name)
    merge.tree(source / "lib", Path("lib"))
    merge.tree(source / "ui", Path("ui"))
    for name in ("bootstrap_no_delete.py", "initialize_azurefactory.py"):
        merge.file(source / "lib" / name, Path("lib") / name)
    template = source / "templates" / "azurefactory" / "register.json"
    if starter.read_document(template) != starter.EMPTY_DOCUMENT:
        raise ValueError("The central starter must contain exactly the empty v2 document.")
    merge.file(template, Path("templates/azurefactory/register.json"))
    merge.file(source / ".gitignore.template", ".gitignore", preserve=True)


def templates(merge, source, layout_mode, api_assets):
    # Keep the shell guard in force even if this helper is invoked directly.
    for ancestor in (merge.root, *merge.root.parents):
        register = ancestor / "azurefactory" / "register.json"
        if starter.ordinary(register).exists() or (
                ancestor.name == "azurefactory" and starter.ordinary(ancestor / "register.json").exists()):
            raise ValueError("azurefactory/register.json is not a legacy template destination.")
    if starter.ordinary(merge.root / "azurefactory").exists():
        raise ValueError("An azurefactory folder exists; template copy refuses mixed/new roots.")
    legacy = starter.ordinary(merge.root / "aifactory")
    if legacy.exists() and not legacy.is_dir():
        raise ValueError("aifactory must be an ordinary directory.")
    target = Path("aifactory-templates")
    infra = source / "environment_setup" / "aifactory"
    settings = infra / "bicep" / "copy_to_local_settings"
    for origin, destination in (
        (settings / "azure-devops/esml-yaml-pipelines", target / "esml-infra/azure-devops/bicep/yaml"),
        (settings / "github-actions", target / "esml-infra/github-actions/bicep"),
        (settings / "github-actions", target / "esml-infra/github-actions/terraform"),
        (settings / "automation", target / "automation"),
        (infra / "azure_dashboards", target / "esml-infra/azure_dashboards"),
        (source / "usecase_code", Path("aifactory-usecase-code")),
    ):
        merge.tree(origin, destination)
    for asset in api_assets:
        origin = source / "environment_setup" / asset
        if origin.is_dir():
            merge.tree(origin, target / asset, api=True)
        else:
            merge.file(origin, target / asset, preserve=origin.name == ".gitignore")
    merge.file(source / "bootstrap/.gitignore.template", ".gitignore", preserve=True)
    merge.file(b"# Placeholder folder for the AI Factory configuration wizard\n",
               target / "config-wizard/readme.md", preserve=True)
    if layout_mode == "auto":
        # The existing initializer uses a removable pending file. This path instead
        # validates the same contract and creates the absent inactive starter only.
        (merge.root / target).mkdir(exist_ok=True)
        staged = starter.target_root(merge.root / target / "azurefactory", staging=True)
        register = staged / "register.json"
        if register.exists():
            if starter.read_document(register) != starter.EMPTY_DOCUMENT:
                raise ValueError("Existing staged register is not the empty starter; nothing was changed.")
            print(f"Preserved existing starter: {register}")
        else:
            if staged.exists() and any(staged.iterdir()):
                raise ValueError("Without register.json the staged azurefactory destination must be empty.")
            if starter.read_document(starter.TEMPLATE) != starter.EMPTY_DOCUMENT:
                raise ValueError("The central starter must contain exactly the empty v2 document.")
            merge.file(starter.TEMPLATE.read_bytes(), target / "azurefactory/register.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("bundle", "templates"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--layout-mode", choices=("auto", "legacy-templates"), default="auto")
    parser.add_argument("--api-assets", nargs="+", default=[])
    args = parser.parse_args()
    try:
        merge = Merge(Path(os.path.abspath(args.root)))
        source = starter.ordinary(Path(os.path.abspath(args.source)))
        if args.operation == "bundle":
            bundle(merge, source)
        else:
            if not args.api_assets or any(
                    Path(asset).is_absolute() or ".." in Path(asset).parts for asset in args.api_assets):
                raise ValueError("Explicit relative CLI/API assets are required.")
            templates(merge, source, args.layout_mode, args.api_assets)
        merge.execute()
    except (OSError, ValueError) as exc:
        print(f"ERROR: Non-deleting bootstrap stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
