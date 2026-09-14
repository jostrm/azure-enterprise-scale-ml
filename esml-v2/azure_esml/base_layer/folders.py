"""Folder catalogs with relative prefixes and no domain-specific naming rules."""

import os
from pathlib import Path, PureWindowsPath
import stat

from .contracts import IFolderCatalog


def _parts(prefix: str) -> tuple[str, ...]:
    if not isinstance(prefix, str):
        raise ValueError("prefix must be a relative slash-separated string")
    if (
        prefix.startswith("/")
        or "\\" in prefix
        or ":" in prefix
        or "\x00" in prefix
        or PureWindowsPath(prefix).drive
    ):
        raise ValueError("prefix must be relative, not a path root or URI")
    stripped = prefix[:-1] if prefix.endswith("/") else prefix
    parts = tuple(stripped.split("/")) if stripped else ()
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("prefix must not contain traversal or empty segments")
    return parts


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


class LocalFolderCatalog(IFolderCatalog):
    """Enumerate direct directories, including hidden names; never follow links."""

    def __init__(self, root: Path):
        self.root = Path(os.path.abspath(root))
        for path in (*reversed(self.root.parents), self.root):
            if _is_link(path):
                raise ValueError("Folder catalog roots must not contain symlinks or junctions")
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)

    def list_folders(self, prefix: str) -> tuple[str, ...]:
        current = self.root
        for part in _parts(prefix):
            current = current / part
            if _is_link(current):
                raise ValueError("Folder prefixes must not contain symlinks or junctions")
        if not current.is_dir():
            raise NotADirectoryError(current)
        result = []
        for child in current.iterdir():
            if _is_link(child):
                raise ValueError("Folder catalogs must not contain symlinks or junctions")
            if child.is_dir():
                result.append(child.name)
        return tuple(sorted(result))


class BlobFolderCatalog(IFolderCatalog):
    """Enumerate BlobPrefix entries; ordinary blob names never imply directories."""

    def __init__(self, container_client):
        self.container_client = container_client

    def list_folders(self, prefix: str) -> tuple[str, ...]:
        from azure.storage.blob import BlobPrefix

        parts = _parts(prefix)
        start = "/".join(parts) + "/" if parts else ""
        children = set()
        for item in self.container_client.walk_blobs(name_starts_with=start, delimiter="/"):
            if not isinstance(item, BlobPrefix):
                continue
            name = item.name
            if not isinstance(name, str) or not name.startswith(start) or not name.endswith("/"):
                continue
            child = name[len(start):-1]
            if child and "/" not in child:
                if _parts(child) != (child,):
                    raise ValueError("Invalid child folder name")
                children.add(child)
        return tuple(sorted(children))
