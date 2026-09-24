"""Install registered-layout shell helpers without copying legacy templates."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from bootstrap_no_delete import Merge
import initialize_azurefactory as starter


def git(source, *args):
    result = subprocess.run(
        ["git", "-C", str(source), *args], capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValueError("Use an existing reviewed Git source checkout; Git could not inspect it.")
    return result.stdout.strip()


def install(source, root, provider="both", refresh_only=False):
    source = starter.ordinary(Path(os.path.abspath(source)))
    root = starter.ordinary(Path(os.path.abspath(root)))
    if source == root or not starter.ordinary(root / ".git").exists():
        raise ValueError("Run from an existing consumer Git repository, not the shared source repository.")
    if not root.is_dir():
        raise ValueError("Consumer repository must already exist.")
    if (root / "aifactory").exists():
        raise ValueError("Legacy aifactory exists. Use reviewed migration or a separate registered consumer; no automatic migration.")
    target = starter.target_root(root / "azurefactory")
    register = target / "register.json"
    if register.exists():
        starter.check_envelope(starter.read_document(register))
    elif target.exists() and any(target.iterdir()):
        raise ValueError("Without register.json, azurefactory must be empty.")
    bootstrap = source / "bootstrap"
    if starter.read_document(bootstrap / "templates" / "azurefactory" / "register.json") != starter.EMPTY_DOCUMENT:
        raise ValueError("Source does not contain the empty registered-layout starter.")
    for relative in (
        "lib/factory_lifecycle.py", "lib/factory_lifecycle_contract.txt", "lib/layout_router.sh",
        "lib/factory_enrollment.py", "lib/factory_enrollment_entry.py", "lib/runner_bootstrap.py",
        "lib/provider_repository_state.py",
        "ui/terminal.sh",
    ):
        if not starter.ordinary(bootstrap / relative).is_file():
            raise ValueError(f"Incomplete registered helper source: {relative}")
    commit = git(source, "rev-parse", "HEAD")
    branch = git(source, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(git(source, "status", "--porcelain"))
    print(f"Helper source: {source}\nSource branch: {branch}\nSource commit: {commit}\nSource dirty: {dirty}")
    print("Local source only: no fetch, checkout or pull; this does not update any consumer submodule.")
    merge = Merge(root)
    for name in ("azurefactory.sh", "AIFactory-lifecycle.sh"):
        merge.file(bootstrap / name, name)
    for selected in (("ado", "gha") if provider == "both" else (provider,)):
        name = selected.upper() + "-azurefactory.sh"
        merge.file(bootstrap / name, name)
    merge.tree(bootstrap / "lib", Path("lib"))
    merge.tree(bootstrap / "ui", Path("ui"))
    merge.file(bootstrap / "templates" / "azurefactory" / "register.json",
               Path("templates") / "azurefactory" / "register.json")
    package = Path(".azurefactory-tools") / "azurefactory"
    cli = source / "environment_setup" / "azurefactory-cli" / "src" / "azurefactory"
    for name in ("__init__.py", "__main__.py", "cli.py", "client.py", "review.py",
                 "configuration.py", "errors.py", "enrollment.py", "_vendor/__init__.py"):
        if not starter.ordinary(cli / name).is_file():
            raise ValueError(f"Incomplete CLI source: {name}")
    merge.tree(cli, package)
    merge.file(bootstrap / "lib" / "factory_enrollment.py", package / "_vendor" / "factory_enrollment.py")
    merge.file(bootstrap / "lib" / "provider_repository_state.py", package / "_vendor" / "provider_repository_state.py")
    merge.file(bootstrap / ".gitignore.template", ".gitignore", preserve=True)
    # Print a digest of the actual reviewed payload, including uncommitted changes.
    digest = hashlib.sha256()
    for destination, origin in sorted(merge.files.items()):
        if destination.name == ".gitignore":
            continue
        digest.update(destination.relative_to(root).as_posix().encode() + b"\0")
        digest.update(origin.read_bytes() if isinstance(origin, Path) else origin)
    print(f"Selected helper payload SHA256: {digest.hexdigest()}", flush=True)
    merge.execute()
    if not refresh_only:
        path, created = starter.initialize(target)
        print(f"{'Initialized empty' if created else 'Preserved existing'} register: {path}")
    print("No factory/project was created, migrated or deployed. Saved configuration/version and .gitignore are preserved.")
    print("A current authenticated local API is required for configuration; no desktop app is required.")
    print("Next: bash ./azurefactory.sh api instructions")
    print("Then: bash ./azurefactory.sh doctor")
    print("Configure: bash ./azurefactory.sh factory create --help")
    print("Review the preview, then separately approve: bash ./azurefactory.sh catalog confirm --receipt <file> --yes")
    print("Creation configures a factory plus its initial project (default project001); deployment is a separate review.")
    print("Keep receipts and .aifactory-backups private; existing ignore rules are not changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--consumer-root", required=True, type=Path)
    parser.add_argument("--provider", choices=("both", "ado", "gha"), default="both",
                        help="Install both provider wrappers by default; never delete the other provider's files.")
    parser.add_argument("--refresh-only", action="store_true", help="Refresh helpers without initializing register storage.")
    args = parser.parse_args()
    try:
        install(args.source, args.consumer_root, args.provider, args.refresh_only)
    except (OSError, ValueError) as exc:
        print(f"ERROR: Registered setup stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
