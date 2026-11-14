"""Preview-first immutable publications to an existing common or project lake."""

import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

from ml_model_factory.data import sha256
from ml_model_factory.lake import local_key_path, relative_key
from ml_model_factory.lake_flow import verified_manifest
from ml_model_factory.selection import canonical_hash


def storage_target(account_url: str, container: str) -> str:
    parsed = urlsplit(account_url)
    if (not re.fullmatch(r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net/?", account_url)
            or parsed.query or parsed.fragment):
        raise ValueError("Use an explicit credential-free Azure Blob account URL; HNS accounts support this endpoint")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container) or "--" in container:
        raise ValueError("Use an existing valid container name")
    return account_url.rstrip("/") + "/" + container


def payload_path(root: Path, key: str, blob: str) -> Path:
    if not blob.startswith(key + "/"):
        raise ValueError("Payload is outside the selected publication")
    relative = blob[len(key) + 1:]
    parts = relative.split("/")
    if (any(part in ("", ".", "..") for part in parts)
            or any(character in relative for character in ("\\", ":", "\x00"))):
        raise ValueError("Payload filename traverses outside its publication")
    directory = local_key_path(Path(root), key)
    path = directory.joinpath(*parts)
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Publication payload may not traverse links")
        if item == directory:
            break
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Payload escaped publication root")
    return path


def publication_plan(root: Path, keys: list[str], *, account_url: str, container: str) -> dict:
    target = storage_target(account_url, container)
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Select distinct complete publication roots")
    prefixes = [relative_key(key) for key in keys]
    if any(a.startswith(b + "/") or b.startswith(a + "/")
           for index, a in enumerate(prefixes) for b in prefixes[index + 1:]):
        raise ValueError("Publication roots must not overlap")
    publications = []
    for key in prefixes:
        directory = local_key_path(Path(root), key)
        manifest = verified_manifest(directory)
        files = [{"blob": key + "/" + name, "sha256": digest, "bytes": (directory / name).stat().st_size}
                 for name, digest in sorted(manifest["files"].items())]
        marker = directory / "_SUCCESS.json"
        files.append({"blob": key + "/_SUCCESS.json", "sha256": sha256(marker), "bytes": marker.stat().st_size})
        publications.append({"key": key, "files": files})
    result = {
        "schema": "esml.lake-publication/v2", "target": target, "publications": publications,
        "files": sum(len(item["files"]) for item in publications),
        "bytes": sum(file["bytes"] for item in publications for file in item["files"]),
        "changes": "Create absent blobs only; compare existing content; _SUCCESS.json last.",
        "does_not_change": ["firewall", "public access", "RBAC", "ACLs", "container", "other accounts",
                            "existing blob content", "Azure ML jobs", "vector indexes", "LLM models"],
    }
    result["plan_sha256"] = canonical_hash(result)
    return result


def publish(root: Path, plan: dict, *, credential=None, container_client=None) -> dict:
    """Publish exactly a reviewed plan; Azure data and commit markers are verified."""
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.storage.blob import ContainerClient

    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if canonical_hash(unsigned) != plan.get("plan_sha256"):
        raise ValueError("Publication plan changed; generate and review it again")
    target = urlsplit(plan["target"])
    container = target.path.strip("/")
    account_url = f"{target.scheme}://{target.netloc}"
    current = publication_plan(root, [entry["key"] for entry in plan["publications"]],
                               account_url=account_url, container=container)
    if current != plan:
        raise ValueError("Local source differs from the reviewed plan")
    if container_client is None:
        if credential is None:
            raise ValueError("Explicit token credentials are required; no keys, SAS or identity fallback")
        container_client = ContainerClient(account_url, container, credential=credential)
    properties = container_client.get_container_properties()
    public_access = getattr(properties, "public_access", None)
    if public_access is not None:
        raise ValueError("Shared publications require a private existing container")
    written, reused = 0, 0
    for entry in plan["publications"]:
        lock = container_client.get_blob_client(entry["key"] + "/.publication-lock")
        try:
            receipt = lock.upload_blob(plan["plan_sha256"].encode(), overwrite=False)
        except ResourceExistsError as exc:
            raise ValueError("Publication locked; reconcile the previous writer before retrying") from exc
        try:
            marker = entry["files"][-1]
            try:
                committed = container_client.get_blob_client(marker["blob"]).download_blob()
            except ResourceNotFoundError:
                committed = None
            if committed is not None:
                digest = hashlib.sha256()
                for block in committed.chunks():
                    digest.update(block)
                if digest.hexdigest() != marker["sha256"]:
                    raise ValueError("Existing commit marker identifies a different release; no payloads were uploaded")
            for item in entry["files"]:
                local = payload_path(root, entry["key"], item["blob"])
                if sha256(local) != item["sha256"] or local.stat().st_size != item["bytes"]:
                    raise ValueError("Local content changed during publication")
                blob = container_client.get_blob_client(item["blob"])
                try:
                    existing = blob.download_blob()
                except ResourceNotFoundError:
                    existing = None
                if existing is not None:
                    digest = hashlib.sha256()
                    length = 0
                    for block in existing.chunks():
                        digest.update(block)
                        length += len(block)
                    if digest.hexdigest() != item["sha256"] or length != item["bytes"]:
                        raise ValueError(f"Immutable remote content differs: {item['blob']}")
                    reused += 1
                    continue
                if committed is not None:
                    raise ValueError("Committed remote release has missing payloads; reconcile corruption explicitly")
                with local.open("rb") as content:
                    blob.upload_blob(content, overwrite=False, metadata={"sha256": item["sha256"]})
                digest = hashlib.sha256()
                for block in blob.download_blob().chunks():
                    digest.update(block)
                if digest.hexdigest() != item["sha256"]:
                    raise ValueError(f"Uploaded content verification failed: {item['blob']}")
                written += 1
        finally:
            lock.delete_blob(etag=receipt["etag"], match_condition=MatchConditions.IfNotModified)
    return {"state": "committed", "target": plan["target"], "written": written, "reused": reused,
            "plan_sha256": plan["plan_sha256"]}
