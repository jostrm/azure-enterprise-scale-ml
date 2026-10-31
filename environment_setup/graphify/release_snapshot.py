"""Publish and fetch release-pinned dual-graph snapshots as GitHub Release assets.

``publish`` runs on an operator workstation, never in GitHub Actions. On a clean checkout
of a pushed release commit it runs every unit-test tier (1-5), generates the snapshot,
and packages it with a SHA-256 checksum. Only with ``--apply`` does it tag the commit
(``release_NNN``), push the tag and upload the two assets with the GitHub CLI. Nothing is
generated, tagged or uploaded unless all tiers pass, and an uploaded snapshot is never
replaced.

``fetch`` downloads a release's assets (or takes local files), verifies the checksum and
the snapshot's own integrity manifest, and unpacks it to
``meta/graphify/snapshots/<snapshot-id>``: the immutable, pinned root that the AI Factory
Agent chat and the AI Factory MCP accept. It never changes the local ``current.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"))
from aifactory_agent.dual_graph import DualGraphStore, GraphError  # noqa: E402

TAG = re.compile(r"release_\d{3,}")
HEX = re.compile(r"[a-f0-9]{64}")
ASSET_PREFIX = "aifactory-dual-graph"
RUN_CI = Path("environment_setup") / "unit-tests" / "test-bicep" / "run_ci.py"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PASSED = {"tiers": "all", "result": "passed"}


class ReleaseError(RuntimeError):
    """A release or fetch precondition failed; nothing further was done."""


def check_tag(tag: str) -> str:
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise ReleaseError("Use a release tag such as release_125 (the existing release_NNN convention); "
                           "release/v1.25 is the branch name.")
    return tag


def asset_names(tag: str) -> tuple[str, str]:
    asset = f"{ASSET_PREFIX}-{check_tag(tag)}.zip"
    return asset, asset + ".sha256"


def _run(args, cwd=None):
    return subprocess.run([str(item) for item in args], cwd=cwd, capture_output=True, text=True, check=False)


def _output(run, args, cwd, message):
    result = run(args, cwd=cwd)
    if result.returncode:
        raise ReleaseError(f"{message}: {' '.join(str(item) for item in args[:3])} failed.")
    return result.stdout


def _require_clean(run, root, when):
    if _output(run, ["git", "status", "--porcelain", "--untracked-files=normal"], root, "Git status").strip():
        raise ReleaseError(f"The checkout has uncommitted or untracked changes {when}; "
                           "release snapshots come only from a clean, committed checkout.")


def _local_tag(run, root, tag):
    result = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"], cwd=root)
    return result.stdout.strip() if result.returncode == 0 else None


def _remote_tag(run, root, tag):
    lines = _output(run, ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                    root, "Reading remote tags").split("\n")
    refs = dict(reversed(line.split("\t", 1)) for line in lines if "\t" in line)
    return refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")


def _release_assets(run, root, tag):
    result = run(["gh", "release", "view", tag, "--json", "assets"], cwd=root)
    if result.returncode:
        return None
    return {item["name"] for item in json.loads(result.stdout or "{}").get("assets", [])}


def _generate(root: Path, output: Path) -> dict:
    spec = importlib.util.spec_from_file_location("aifactory_graph_generate", Path(__file__).with_name("generate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate(root, output)


def _fresh(export: dict) -> bool:
    return export["freshness"]["status"] == "fresh"


def run_all_tiers(run, root: Path, test_python: str) -> dict:
    """Run unit-test tiers 1-5 offline; any failure stops the release."""
    with tempfile.TemporaryDirectory(prefix="aifactory-release-tests-") as results:
        result = run([test_python, str(root / RUN_CI), "--phase", "unit", "--tiers", "all",
                      "--results-dir", results], cwd=root)
        summary_file = Path(results) / "unit-summary.json"
        summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.is_file() else {}
    if (result.returncode or summary.get("failed") != []
            or summary.get("tiers", {}).get("selected") != "all"):
        raise ReleaseError("Unit-test tiers 1-5 did not all pass; nothing was generated, tagged or uploaded. "
                           f"Rerun: {test_python} {RUN_CI} --phase unit --tiers all")
    return dict(PASSED)


def package(export: dict, tag: str, revision: str, out_dir: Path, tests: dict | None = None) -> dict:
    """Write a deterministic zip of the verified snapshot plus a sha256sum-style checksum file."""
    snapshot_id = export["snapshot_id"]
    asset_name, checksum_name = asset_names(tag)
    info = {"tag": tag, "snapshot_id": snapshot_id, "source_revision": revision, "tests": tests or dict(PASSED)}
    members = {"release.json": (json.dumps(info, indent=2, sort_keys=True) + "\n").encode("utf-8")}
    for relative, data in sorted(export["files"].items()):
        members[f"snapshots/{snapshot_id}/{relative}"] = data
    out_dir.mkdir(parents=True, exist_ok=True)
    asset, checksum = out_dir / asset_name, out_dir / checksum_name
    with zipfile.ZipFile(asset, "w") as archive:
        for name, data in members.items():
            entry = zipfile.ZipInfo(name, ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, data)
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {asset_name}\n", encoding="utf-8")
    return {"asset": str(asset), "checksum": str(checksum), "sha256": digest, "snapshot_id": snapshot_id}


def publish(root: Path, tag: str, *, apply: bool = False, run=_run, generate=_generate,
            test_python: str = sys.executable, output: Path | None = None, fresh=_fresh) -> dict:
    root = Path(root).resolve()
    check_tag(tag)
    asset_name, checksum_name = asset_names(tag)
    output = Path(output or root / "meta" / "graphify").resolve()

    _require_clean(run, root, "before the release")
    head = _output(run, ["git", "rev-parse", "HEAD"], root, "Reading HEAD").strip()
    if not _output(run, ["git", "branch", "-r", "--contains", head], root, "Reading remote branches").strip():
        raise ReleaseError("The release commit has not been pushed to a remote branch; push it (for example release/v1.25) first.")
    local_tag, remote_tag = _local_tag(run, root, tag), _remote_tag(run, root, tag)
    for where, commit in (("Local", local_tag), ("Remote", remote_tag)):
        if commit and commit != head:
            raise ReleaseError(f"{where} tag {tag} points at another commit ({commit[:12]}); "
                               "check out that commit or choose a new tag.")
    existing = _release_assets(run, root, tag) if apply else None
    if existing and {asset_name, checksum_name} & existing:
        raise ReleaseError(f"Release {tag} already has a dual-graph snapshot; published snapshots are never replaced.")

    tests = run_all_tiers(run, root, test_python)
    _require_clean(run, root, "after the tests")

    snapshot_id = generate(root, output)["snapshot_id"]
    try:
        export = DualGraphStore(output, repository_root=root, expected_snapshot_id=snapshot_id).export_snapshot()
    except GraphError as error:
        raise ReleaseError(f"The generated snapshot failed its integrity check ({error.code}).") from error
    if export["source"]["dirty"]:
        raise ReleaseError("The snapshot includes uncommitted source; it is never packaged for a release.")
    if export["source"]["revision"] != head:
        raise ReleaseError("The snapshot revision is not the release commit; it is never packaged for a release.")
    if not fresh(export):
        raise ReleaseError("The snapshot is not fresh against the release checkout; regenerate it.")

    packaged = package(export, tag, head, output / "release-assets", tests)
    notes = (f"Dual-graph snapshot `{snapshot_id}` from commit `{head}`, published after unit-test tiers 1-5 passed.\n\n"
             f"Fetch it: `python environment_setup/graphify/release_snapshot.py fetch --tag {tag}`")
    steps = []
    if not local_tag:
        steps.append(["git", "tag", "-a", tag, "-m", f"Release {tag}", head])
    if not remote_tag:
        steps.append(["git", "push", "origin", f"refs/tags/{tag}"])
    if existing is None:
        steps.append(["gh", "release", "create", tag, "--verify-tag", "--title", tag, "--notes", notes])
    steps.append(["gh", "release", "upload", tag, packaged["asset"], packaged["checksum"]])
    if apply:
        for step in steps:
            _output(run, step, root, "Publishing the release")
    return {**packaged, "tag": tag, "source_revision": head, "tests": tests, "applied": apply,
            "next_steps": [] if apply else [" ".join(f'"{item}"' if " " in item else item for item in step)
                                             for step in steps]}


def _safe_member(name: str, snapshot_id: str) -> str | None:
    """Return the path inside the snapshot for an allowed member, else raise."""
    if name == "release.json":
        return None
    path = PurePosixPath(name)
    parts = path.parts
    if (name.startswith("/") or "\\" in name or len(parts) < 3 or parts[:2] != ("snapshots", snapshot_id)
            or any(part in ("", ".", "..") for part in parts) or name.endswith("/")):
        raise ReleaseError(f"The asset contains an unexpected member: {name!r}.")
    return "/".join(parts[2:])


def install(asset: Path, checksum: Path, root: Path) -> dict:
    """Verify a downloaded asset and unpack it to <root>/snapshots/<snapshot-id>."""
    asset, checksum, root = Path(asset), Path(checksum), Path(os.path.abspath(root))
    expected = checksum.read_text(encoding="utf-8").split()
    if (len(expected) != 2 or not HEX.fullmatch(expected[0]) or expected[1] != asset.name
            or hashlib.sha256(asset.read_bytes()).hexdigest() != expected[0]):
        raise ReleaseError("The asset does not match its SHA-256 checksum file; it was not unpacked.")
    with zipfile.ZipFile(asset) as archive:
        names = archive.namelist()
        if "release.json" not in names or len(names) != len(set(names)):
            raise ReleaseError("The asset has no release.json or repeats a member.")
        info = json.loads(archive.read("release.json"))
        snapshot_id = info.get("snapshot_id") if isinstance(info, dict) else None
        if not isinstance(snapshot_id, str) or not HEX.fullmatch(snapshot_id):
            raise ReleaseError("The asset's release.json does not name a valid snapshot ID.")
        files = {inner: archive.read(name) for name in names
                 if (inner := _safe_member(name, snapshot_id)) is not None}
    snapshots = root / "snapshots"
    target = snapshots / snapshot_id
    if not target.exists():
        staging = snapshots / f".fetch-{uuid.uuid4().hex}"
        unpacked = staging / snapshot_id
        try:
            for inner, data in files.items():
                path = unpacked / inner
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            try:
                verified = DualGraphStore(unpacked, expected_snapshot_id=snapshot_id).export_snapshot()
            except GraphError as error:
                raise ReleaseError(f"The snapshot failed its integrity manifest ({error.code}); it was not installed.") from error
            if set(verified["files"]) != set(files):
                raise ReleaseError("The snapshot failed its integrity manifest (unlisted files); it was not installed.")
            os.rename(unpacked, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    try:
        DualGraphStore(target, expected_snapshot_id=snapshot_id).export_snapshot()
    except GraphError as error:
        raise ReleaseError(f"The existing {target} failed its integrity manifest ({error.code}); "
                           "remove it and fetch again.") from error
    return {"tag": info.get("tag"), "snapshot_id": snapshot_id, "source_revision": info.get("source_revision"),
            "tests": info.get("tests"), "snapshot_root": str(target),
            "dual_graph": {"snapshot_root": str(target), "expected_snapshot_id": snapshot_id}}


def fetch(tag: str, root: Path, *, run=_run) -> dict:
    asset_name, checksum_name = asset_names(tag)
    with tempfile.TemporaryDirectory(prefix="aifactory-graph-fetch-") as download:
        _output(run, ["gh", "release", "download", tag, "--pattern", asset_name, "--pattern", checksum_name,
                      "--dir", download], None, "Downloading the release assets")
        return install(Path(download) / asset_name, Path(download) / checksum_name, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    publishing = commands.add_parser("publish", help="Test tiers 1-5, generate, package and (with --apply) upload.")
    publishing.add_argument("--tag", required=True, help="New release tag, for example release_125")
    publishing.add_argument("--repository-root", type=Path, default=REPOSITORY)
    publishing.add_argument("--test-python", default=sys.executable,
                            help="Python with environment_setup/unit-tests/test-bicep/requirements.txt installed")
    publishing.add_argument("--apply", action="store_true", help="Tag, push the tag and upload the assets")
    fetching = commands.add_parser("fetch", help="Download, verify and unpack a release snapshot.")
    fetching.add_argument("--tag", required=True)
    fetching.add_argument("--root", type=Path, default=REPOSITORY / "meta" / "graphify")
    fetching.add_argument("--asset", type=Path, help="Use a local asset instead of downloading it")
    fetching.add_argument("--checksum", type=Path, help="Local checksum file for --asset")
    args = parser.parse_args(argv)
    try:
        if args.command == "publish":
            result = publish(args.repository_root, args.tag, apply=args.apply, test_python=args.test_python)
        elif args.asset:
            check_tag(args.tag)
            result = install(args.asset, args.checksum or Path(str(args.asset) + ".sha256"), args.root)
        else:
            result = fetch(args.tag, args.root)
    except ReleaseError as error:
        print(json.dumps({"status": "refused", "error": str(error)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
