"""Generate the desktop update feed from complete, local release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import warnings


SPLIT_APPS = (
    ("esaif-configwizard", "Enterprise Scale AI Factory", "install_config_wizard/maui",
     r"ESAIF\.ConfigWizard-(\d+\.\d+\.\d+(?:\.\d+)?)-win-x64\.msi", "msi", "cab"),
    ("esaif-configwizard-project", "ESAF - My Project", "install_config_wizard_project/maui",
     r"ESAIF\.ConfigWizardProject-(\d+\.\d+\.\d+(?:\.\d+)?)-win-x64-setup\.exe", "inno", "bin"),
    ("esaif-tutorialapp", "ESAF Tutorials", "install_tutorial_guide",
     r"ESAF-Tutorials-(\d+\.\d+\.\d+(?:\.\d+)?)-win-x64-local-preview-(?:un)?signed\.msi", "msi", "cab"),
)
PROJECT_INNO_APP_ID = "{D77386A2-9B9B-4A66-B493-A8E5B57EBB7B}"
TK_PLATFORMS = {
    ("windows", "amd64"): ("windows-x64", "zip", "aifactory-config/aifactory-config.exe"),
    ("windows", "x86_64"): ("windows-x64", "zip", "aifactory-config/aifactory-config.exe"),
    ("linux", "x86_64"): ("linux-x64", "tar.gz", "aifactory-config"),
    ("macos", "arm64"): ("macos-arm64", "tar.gz", "aifactory-config"),
}
SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def normalized_version(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+(?:\.\d+)?", value):
        raise ValueError(f"Not a numeric release version: {value!r}")
    return value.removeprefix("v")


def _version_key(value: str) -> tuple[int, ...]:
    parts = tuple(map(int, normalized_version(value).split(".")))
    return parts + (0,) * (4 - len(parts))


def _filename(value: str) -> str:
    if not isinstance(value, str) or not SAFE_FILENAME.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"Unsafe release filename: {value!r}")
    return value


def _contained(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Release path escapes environment_setup: {path}")
    return resolved


def _checksums(folder: Path) -> dict[str, str]:
    path = folder / "SHA256SUMS.txt"
    if not path.is_file():
        raise ValueError(f"Missing SHA256SUMS.txt inventory: {folder}")
    entries = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[*]?(.+)", line.strip())
        if not match:
            raise ValueError(f"Invalid checksum inventory line in {path}")
        digest, name = match.groups()
        name = _filename(name)
        if name in entries:
            raise ValueError(f"Duplicate filename in checksum inventory: {name}")
        entries[name] = digest.lower()
    return entries


def _artifact(root: Path, path: Path, expected_hash: str | None = None,
              expected_bytes: int | None = None) -> dict:
    source = _contained(root, path)
    if not source.is_file():
        raise ValueError(f"Missing release artifact: {path}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual_hash = digest.hexdigest()
    size = source.stat().st_size
    if size == 0:
        raise ValueError(f"Empty release artifact: {path}")
    if expected_hash is not None and actual_hash != expected_hash.lower():
        warnings.warn(f"SHA256 drift for {path.name}; feed records the current local artifact.", stacklevel=2)
    if expected_bytes is not None and size != expected_bytes:
        warnings.warn(f"Byte-count drift for {path.name}; feed records the current local artifact.", stacklevel=2)
    return {"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": actual_hash}


def _split_release(root: Path, relative_folder: str, pattern: str,
                   installer_type: str, payload_extension: str) -> dict:
    folder = _contained(root, root / relative_folder)
    if not folder.exists():
        return {}
    extension = "exe" if installer_type == "inno" else "msi"
    discovered = {path.name for path in folder.glob(f"*.{extension}") if re.fullmatch(pattern, path.name)}
    if not discovered and not (folder / "SHA256SUMS.txt").exists():
        return {}
    _contained(root, folder / "SHA256SUMS.txt")
    inventory = _checksums(folder)
    declared = {name for name in inventory if re.fullmatch(pattern, name)}
    if discovered != declared:
        raise ValueError(f"Missing installer or incomplete checksum inventory in {folder}: "
                         f"{sorted(discovered.symmetric_difference(declared))}")
    if not declared:
        return {}
    candidates = [(re.fullmatch(pattern, name).group(1), name) for name in declared]
    candidates.sort(key=lambda item: _version_key(item[0]))
    version, name = candidates[-1]
    if sum(_version_key(candidate[0]) == _version_key(version) for candidate in candidates) != 1:
        raise ValueError(f"Ambiguous installers for version {version} in {folder}")
    stem = Path(name).stem
    part_pattern = re.compile(re.escape(stem) + r"-(\d+)\." + re.escape(payload_extension))
    part_names = [entry for entry in inventory if part_pattern.fullmatch(entry)]
    part_names.sort(key=lambda entry: int(part_pattern.fullmatch(entry).group(1)))
    if not part_names:
        raise ValueError(f"Missing external {payload_extension.upper()} inventory for {name}")
    numbers = [int(part_pattern.fullmatch(entry).group(1)) for entry in part_names]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"Incomplete {payload_extension.upper()} sequence for {name}")
    actual_parts = {path.name for path in folder.glob(f"*.{payload_extension}") if part_pattern.fullmatch(path.name)}
    if actual_parts != set(part_names):
        raise ValueError(f"Missing {payload_extension.upper()} or incomplete checksum inventory for {name}: "
                         f"{sorted(actual_parts.symmetric_difference(part_names))}")
    release = {
        "version": normalized_version(version),
        "installerType": installer_type,
        "files": [_artifact(root, folder / entry, inventory[entry]) for entry in (name, *part_names)],
    }
    if installer_type == "inno":
        release["innoAppId"] = PROJECT_INNO_APP_ID
    return {"windows-x64": release}


def _tk_platform(artifact: dict) -> tuple[str, str, str]:
    if not isinstance(artifact, dict):
        raise ValueError("Invalid Tkinter release artifact")
    platform = artifact.get("platform")
    architecture = artifact.get("architecture")
    if not isinstance(platform, str) or not isinstance(architecture, str):
        raise ValueError("Tkinter release artifact requires platform and architecture")
    key = (platform.lower(), architecture.lower())
    if key not in TK_PLATFORMS:
        raise ValueError(f"Unsupported Tkinter release platform: {key}")
    return TK_PLATFORMS[key]


def _tk_releases(root: Path) -> dict:
    wizard = root / "install_config_wizard"
    manifest_path = _contained(root, wizard / "release-manifest.json")
    artifacts = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
            raise ValueError("Invalid Tkinter release manifest: expected an artifacts array")
        for artifact in manifest["artifacts"]:
            platform_id, _, _ = _tk_platform(artifact)
            if platform_id in artifacts:
                raise ValueError(f"Duplicate Tkinter release platform: {platform_id}")
            artifacts[platform_id] = artifact
    # Windows-only publishing updates its sidecar without rebuilding the other platforms.
    for folder in ("windows", "linux", "macos"):
        sidecar = _contained(root, wizard / folder / "release-manifest.json")
        if not sidecar.exists():
            continue
        artifact = json.loads(sidecar.read_text(encoding="utf-8-sig"))
        platform_id, _, _ = _tk_platform(artifact)
        if artifact["platform"].lower() != folder:
            raise ValueError(f"Tkinter manifest identity does not match its folder: {sidecar}")
        previous = artifacts.get(platform_id)
        if previous is not None and previous.get("version") != artifact.get("version"):
            warnings.warn(f"{platform_id} aggregate version differs; using its platform-specific manifest.",
                          stacklevel=2)
        artifacts[platform_id] = artifact
    releases = {}
    for platform_id, artifact in artifacts.items():
        _, installer_type, entry_point = _tk_platform(artifact)
        platform = artifact["platform"].lower()
        archive = _filename(artifact.get("archive"))
        expected_archive = f"aifactory-config-{platform}.{installer_type}"
        if archive != expected_archive:
            raise ValueError(f"Unexpected {platform_id} archive: {archive}")
        releases[platform_id] = {
            "version": normalized_version(artifact.get("version")),
            "installerType": installer_type,
            "entryPoint": entry_point,
            "files": [_artifact(root, wizard / platform / archive,
                                artifact.get("sha256"), artifact.get("bytes"))],
        }
    return releases


def build_feed(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Update source directory is unavailable: {root}")
    apps = {}
    for app_id, display_name, folder, pattern, installer_type, payload_extension in SPLIT_APPS:
        apps[app_id] = {
            "displayName": display_name,
            "platforms": _split_release(root, folder, pattern, installer_type, payload_extension),
        }
    apps["aifactory-config"] = {"displayName": "AIFactory Config Wizard", "platforms": _tk_releases(root)}
    return {"schemaVersion": 1, "apps": apps}


def write_feed(root: Path) -> Path:
    root = root.resolve()
    content = json.dumps(build_feed(root), indent=2) + "\n"
    output = root / "app-updates.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=root, prefix=".app-updates-", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                        help="Canonical environment_setup directory containing the release artifacts")
    parser.add_argument("--check", action="store_true", help="Report feed drift without writing")
    args = parser.parse_args(argv)
    try:
        if args.check:
            generated = build_feed(args.root)
            path = args.root / "app-updates.json"
            current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            if current != generated:
                warnings.warn("app-updates.json is missing or stale; regenerate before publication.")
            else:
                print("app-updates.json matches the available release artifacts.")
        else:
            print(write_feed(args.root))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Cannot generate app update feed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
