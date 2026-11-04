"""Build a curated, hash-bound context without copying credentials or dirty siblings."""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from types import ModuleType


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts:
        raise ValueError("Release paths must be safe relative paths.")
    return path


def validate_ref(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise ValueError("Use an explicit full commit hash, not a moving branch or tag.")
    return value


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class SourceReader(Protocol):
    def files(self, prefixes: tuple[str, ...]) -> dict[str, bytes]: ...


@dataclass(frozen=True)
class GitSource:
    root: Path
    commit: str

    def files(self, prefixes: tuple[str, ...]) -> dict[str, bytes]:
        validate_ref(self.commit)
        result = subprocess.run(
            ["git", "-C", str(self.root), "archive", self.commit, "--", *prefixes],
            capture_output=True, check=False, timeout=120,
        )
        if result.returncode:
            raise RuntimeError("The exact reviewed source revision could not be archived.")
        files = {}
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            for member in archive:
                path = safe_relative(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("Source archives must not contain symlinks or special files.")
                if any(part in {"tests", "history", "__pycache__", ".git", ".build"} for part in path.parts):
                    continue
                if path.suffix not in {".py", ".json", ".yaml", ".yml", ".toml", ".txt", ".sh", ".ps1", ".bicep"}:
                    continue
                if path.name.startswith(".env") or path.name.endswith(".local.json"):
                    raise ValueError("Local configuration cannot enter a release.")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("The source archive contains an unreadable file.")
                files[str(path)] = stream.read()
        if not files:
            raise ValueError("The selected source archive was empty.")
        return files


def _file_hashes(root: Path) -> dict[str, str]:
    result = {}
    for file in sorted(root.rglob("*")):
        if file.is_symlink():
            raise ValueError("Release files cannot be symlinks.")
        if file.is_file() and file != root / "release.json":
            result[file.relative_to(root).as_posix()] = digest(file.read_bytes())
    return result


def write_manifest(root: Path, metadata: dict) -> dict:
    manifest = {"schema_version": 1, "metadata": metadata, "files": _file_hashes(root)}
    manifest["release_hash"] = digest(canonical(manifest))
    (root / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_release(root: Path) -> dict:
    manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in manifest.items() if key != "release_hash"}
    if manifest.get("release_hash") != digest(canonical(unsigned)):
        raise ValueError("Release manifest hash is invalid.")
    if manifest.get("files") != _file_hashes(root):
        raise ValueError("Release files changed after preparation.")
    return manifest


def load_graph_config(path: Path) -> dict | None:
    path = path.resolve()
    config = json.loads(path.read_text(encoding="utf-8")).get("dual_graph")
    if config is not None:
        if not isinstance(config, dict) or not isinstance(config.get("snapshot_root"), str):
            raise ValueError("A complete explicit dual_graph configuration is required.")
        root = Path(config["snapshot_root"])
        if not root.is_absolute():
            config["snapshot_root"] = str((path.parent / root).resolve())
    return config


def _graph_snapshot(config: dict | None, source_files: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    if config is None:
        return {}, {}
    if not isinstance(config, dict):
        raise ValueError("Graph release configuration must be an explicit object.")
    snapshot_id = config.get("expected_snapshot_id")
    if (not isinstance(snapshot_id, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_id)
            or not isinstance(config.get("snapshot_root"), str) or not config["snapshot_root"]
            or not isinstance(config.get("allowed_scopes"), list) or not config["allowed_scopes"]
            or any(not isinstance(scope, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", scope)
                   for scope in config["allowed_scopes"])
            or len(set(config["allowed_scopes"])) != len(config["allowed_scopes"])
            or set(config) - {"snapshot_root", "expected_snapshot_id", "allowed_scopes", "allow_source_access"}
            or config.get("allow_source_access", False) is not False):
        raise ValueError("Graph releases require explicit enablement, scopes, a pinned snapshot and no source access.")
    module_path = "usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/dual_graph.py"
    if module_path not in source_files:
        raise ValueError("The reviewed purple commit must include the shared dual-graph runtime.")
    # Validate using the exact runtime being packaged, not a possibly newer dirty checkout.
    name = "_aifactory_release_dual_graph"
    module = ModuleType(name)
    module.__file__ = module_path
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(source_files[module_path], module_path, "exec"), module.__dict__)
        store = module.DualGraphStore(config["snapshot_root"], expected_snapshot_id=snapshot_id)
        snapshot = store.export_snapshot()
        if snapshot["snapshot_id"] != snapshot_id:
            raise ValueError("The graph export did not retain the configured pin.")
        files = snapshot["files"]
    except Exception as exc:
        raise ValueError("The pinned graph snapshot failed release validation.") from exc
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    prefix = f"meta/graphify/snapshots/{snapshot_id}"
    selected = {f"{prefix}/{safe_relative(path)}": data for path, data in files.items()}
    return selected, {
        "snapshot_id": snapshot_id, "path": prefix, "source_access": False,
        "source": snapshot["source"], "freshness": snapshot["freshness"],
    }


def prepare_release(
    purple: GitSource, api: GitSource, mcp_root: Path, output: Path, wheelhouse: Path, *,
    graph_config: dict | None = None,
) -> dict:
    if output.exists():
        raise ValueError("Select a new output directory; existing releases are never overwritten.")
    source_groups = {
        "repository": purple.files((
            "environment_setup/azurefactory-cli/src",
            "usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent",
            "usecase_code/40-agent-factory/agent_factory",
        )),
        "api": api.files(("src", "template-files")),
    }
    graph_files, graph_metadata = _graph_snapshot(graph_config, source_groups["repository"])
    source_groups["repository"].update(graph_files)
    local = {}
    for folder in (mcp_root / "src" / "aifactory_mcp", mcp_root / "deploy"):
        for file in sorted(folder.rglob("*")):
            if "__pycache__" in file.parts or not file.is_file():
                continue
            if file.is_symlink():
                raise ValueError("MCP build input cannot be a symlink.")
            if folder.name == "deploy" and file.name not in {
                "Dockerfile.mcp", "Dockerfile.api", ".dockerignore", "launch.py",
                "requirements.mcp.txt", "requirements.api.txt",
            }:
                continue
            if folder.name != "deploy" and file.suffix != ".py":
                continue
            local[str(file.relative_to(mcp_root).as_posix())] = file.read_bytes()
    if not local or "deploy/Dockerfile.mcp" not in local:
        raise ValueError("The reviewed MCP build inputs are missing.")
    wheels = tuple(wheelhouse.glob("*.whl"))
    if not wheels or any(wheel.is_symlink() for wheel in wheels):
        raise ValueError("A predownloaded Linux wheelhouse is required.")
    output.mkdir(parents=True)
    for prefix, files in source_groups.items():
        for name, data in files.items():
            target = output / prefix / Path(*safe_relative(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    for name, data in local.items():
        target = output / Path(*safe_relative(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output / ".dockerignore").write_bytes(local["deploy/.dockerignore"])
    (output / "wheels").mkdir()
    for wheel in wheels:
        (output / "wheels" / wheel.name).write_bytes(wheel.read_bytes())
    metadata = {
        "purple_commit": purple.commit, "api_commit": api.commit,
        "mcp_source": "Explicit current MCP source snapshot; per-file hashes bind uncommitted approved changes.",
        "pilot": "Read-only health, capabilities and skills; no customer catalog state or action execution.",
    }
    if graph_metadata:
        metadata["dual_graph"] = graph_metadata
    return write_manifest(output, metadata)
