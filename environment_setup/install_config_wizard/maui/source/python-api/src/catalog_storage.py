"""Catalog serialization with an OS-released cross-process lock and atomic commit."""

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from src.ticket_connectors import TicketError


class CatalogError(TicketError):
    pass


def ordinary(path):
    path = Path(path)
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise CatalogError("Catalog paths cannot traverse symbolic links or junctions.", 409)
    if path.is_file() and path.stat().st_nlink != 1:
        raise CatalogError("Catalog files must not be hard linked.", 409)
    return path


def root_folder(value):
    if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise CatalogError("Select an absolute local aifactory folder.")
    root = Path(value)
    if not root.is_absolute() or ".." in root.parts or value.startswith(("\\\\", "//")):
        raise CatalogError("Select an absolute local aifactory folder without traversal.")
    ordinary(root)
    if root.name.casefold() != "aifactory" or not root.is_dir():
        raise CatalogError("Select the existing aifactory folder.", 404)
    return root.resolve()


def read_json(path):
    ordinary(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise CatalogError("Catalog input exceeds the supported size.", 409)
    try:
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("Duplicate JSON key")
                value[key] = item
            return value
        def nonfinite(value):
            raise ValueError("Nonfinite JSON value")
        result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError):
        raise CatalogError("A catalog configuration file is malformed.", 409) from None
    if not isinstance(result, dict):
        raise CatalogError("Catalog configuration must contain a JSON object.", 409)
    return result


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def atomic_write(path, data):
    ordinary(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordinary(path.parent)
    pending = path.with_name(path.name + "." + str(uuid4()) + ".pending")
    try:
        with pending.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        ordinary(path)
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


@contextmanager
def catalog_lock(root, timeout=10):
    directory = ordinary(root / "config-wizard")
    directory.mkdir(exist_ok=True)
    path = ordinary(directory / ".catalog.lock")
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise CatalogError("Another catalog operation owns the configuration lock; retry.", 409) from None
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def database(root):
    path = ordinary(root / "config-wizard" / "catalog-operations.sqlite")
    for suffix in ("-journal", "-wal", "-shm"):
        ordinary(path.with_name(path.name + suffix))
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS confirmations (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL,
            revision TEXT NOT NULL, payload TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.commit()
        yield db
        db.commit()
    finally:
        db.close()
