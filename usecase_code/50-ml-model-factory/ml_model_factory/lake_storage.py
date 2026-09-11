"""Publish committed lake artifacts to existing Blob storage without directory markers."""

import hashlib
from pathlib import Path

from .lake import LakeLayout
from .lake_flow import verified_manifest


PUBLISHABLE = {"dataset_root", "training_snapshot", "training_run", "inference_root"}


def publication_plan(layout: LakeLayout, root: Path, area: str) -> dict:
    if area not in PUBLISHABLE:
        raise ValueError(f"Publish a complete immutable area, one of {sorted(PUBLISHABLE)}")
    directory = layout.local_path(root, area)
    manifest = verified_manifest(directory)
    prefix = layout.key(area)
    files = [
        {"local_path": str(directory / name), "blob": prefix + "/" + name,
         "sha256": digest, "bytes": (directory / name).stat().st_size}
        for name, digest in sorted(manifest["files"].items())
    ]
    marker = directory / "_SUCCESS.json"
    files.append({"local_path": str(marker), "blob": prefix + "/_SUCCESS.json",
                  "sha256": hashlib.sha256(marker.read_bytes()).hexdigest(), "bytes": marker.stat().st_size})
    return {
        "area": area, "target": layout.blob_uri(area), "files": files,
        "writes": "immutable data first, _SUCCESS.json last", "creates_container": False,
        "permissions": "Existing Blob data permissions required; no ACLs or RBAC changes are performed.",
    }


def publish(layout: LakeLayout, root: Path, area: str, credential) -> dict:
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.storage.blob import BlobServiceClient

    plan = publication_plan(layout, root, area)
    if credential is None:
        raise ValueError("An explicit Azure token credential is required; account keys and SAS are not used")
    with BlobServiceClient(account_url=layout.account_url, credential=credential) as service:
        container = service.get_container_client(layout.container)
        container.get_container_properties()
        lock = container.get_blob_client(layout.key(area) + "/.publication-lock")
        try:
            receipt = lock.upload_blob(b"immutable-publication", overwrite=False)
        except ResourceExistsError as exc:
            raise ValueError("Another publication or an interrupted upload holds this prefix; inspect before retrying") from exc
        written, reused = 0, 0
        try:
            for item in plan["files"]:
                blob = container.get_blob_client(item["blob"])
                try:
                    properties = blob.get_blob_properties()
                except ResourceNotFoundError:
                    properties = None
                if properties is not None:
                    if (properties.size != item["bytes"] or
                            properties.metadata.get("sha256") != item["sha256"]):
                        raise ValueError(f"Existing immutable blob differs: {item['blob']}")
                    reused += 1
                    continue
                with Path(item["local_path"]).open("rb") as stream:
                    blob.upload_blob(stream, overwrite=False, metadata={"sha256": item["sha256"]})
                written += 1
        finally:
            lock.delete_blob(etag=receipt["etag"], match_condition=MatchConditions.IfNotModified)
    return {"target": plan["target"], "written": written, "reused": reused, "state": "committed"}
