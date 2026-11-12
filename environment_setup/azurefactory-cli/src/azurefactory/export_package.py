"""Validation and explicit saving of server-built project-selection exports."""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from .errors import APIError, ConfigError

MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 24 * 1024 * 1024
_FACTORY_KEY = re.compile(r"[a-z][a-z0-9-]{1,79}")
_PROJECT = re.compile(r"[0-9]{3}")
_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


def _factory_key(value: Any) -> bool:
    return isinstance(value, str) and bool(_FACTORY_KEY.fullmatch(value))


def _factory_selector(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return False
    if _factory_key(value):
        return True
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def validate_selection(factory: str, project_numbers: Sequence[str]) -> list[str]:
    if not _factory_selector(factory):
        raise ConfigError("factory must be a canonical catalog key or UUID, at most 128 characters; not a display name.")
    if not isinstance(project_numbers, (list, tuple)) or not 1 <= len(project_numbers) <= 200:
        raise ConfigError("project_numbers must contain 1 to 200 unique strings from '000' to '999'.")
    if any(not isinstance(value, str) or not _PROJECT.fullmatch(value) for value in project_numbers):
        raise ConfigError("project_numbers must contain three-digit ASCII strings from '000' to '999'.")
    if len(set(project_numbers)) != len(project_numbers):
        raise ConfigError("project_numbers must not contain duplicates.")
    return list(project_numbers)


@dataclass(frozen=True)
class EsafExportPackage:
    """Validated server archive. Nothing is written until save(destination) is called."""

    file_name: str
    zip_bytes: bytes = field(repr=False)
    allowed_azurefactory_names: tuple[str, ...]
    allowed_project_numbers: tuple[str, ...]
    contract_version: int = field(default=1, init=False)

    def save(self, destination: str | os.PathLike[str]) -> Path:
        """Write to an explicit file path, refusing to overwrite an existing file."""
        path = Path(destination)
        with path.open("xb") as stream:
            stream.write(self.zip_bytes)
        return path


def _safe_part(value: str) -> bool:
    return bool(value) and value not in (".", "..") and not value.endswith((" ", ".")) and not (
        _RESERVED.match(value) or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"/\\|?*'
                                      for char in value))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise APIError("Export project-lock.json contains duplicate keys.")
        result[key] = value
    return result


def _check_archive(data: bytes, factories: list[str], projects: list[str]) -> None:
    expected_lock = {"allowed-azurefactory-names": factories, "allowed-project-numbers": projects}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                raise APIError("Export archive exceeds the expanded-size limit or is empty.")
            names = set()
            for entry in entries:
                name = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                parts = name.split("/")
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if (entry.orig_filename != entry.filename or parts[0] != "azurefactory"
                        or any(not _safe_part(part) for part in parts)
                        or name.casefold() in names
                        or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or entry.flag_bits & 1
                        or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise APIError("Export archive contains unsafe or unsupported entries.")
                names.add(name.casefold())
            required = {"azurefactory/register.json", "azurefactory/project-lock.json"}
            files = {entry.filename for entry in entries if not entry.is_dir()}
            if not required <= files:
                raise APIError("Export archive is missing register.json or project-lock.json.")
            expanded = 0
            lock_data = bytearray()
            for entry in entries:
                if entry.is_dir():
                    continue
                with archive.open(entry) as stream:
                    while chunk := stream.read(64 * 1024):
                        expanded += len(chunk)
                        if expanded > MAX_EXPANDED_BYTES:
                            raise APIError("Export archive exceeds the expanded-size limit.")
                        if entry.filename == "azurefactory/project-lock.json":
                            if len(lock_data) + len(chunk) > 64 * 1024:
                                raise APIError("Export project-lock.json exceeds the metadata-size limit.")
                            lock_data.extend(chunk)
            if json.loads(lock_data, object_pairs_hook=_unique_object) != expected_lock:
                raise APIError("Export project-lock.json does not exactly match the response selection.")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, ValueError,
            UnicodeError, EOFError, OSError, zlib.error) as error:
        raise APIError("Export archive is invalid or unsupported.") from error


def parse_export(response: Any, requested_projects: Sequence[str]) -> EsafExportPackage:
    """Reject malformed wire data; never package, extract or discover config locally."""
    required = {"contract_version", "file_name", "zip_base64", "allowed_azurefactory_names",
                "allowed_project_numbers"}
    if not isinstance(response, dict) or not required <= response.keys():
        raise APIError("Export response is missing required contract fields.")
    if type(response["contract_version"]) is not int or response["contract_version"] != 1:
        raise APIError("Unsupported export contract_version; expected 1.")
    name = response["file_name"]
    if (not isinstance(name, str) or len(name) > 200 or not _safe_part(name)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.zip", name)):
        raise APIError("Export file_name must be a safe .zip filename without a path.")
    factories, projects = response["allowed_azurefactory_names"], response["allowed_project_numbers"]
    if not isinstance(factories, list) or len(factories) != 1 or not _factory_key(factories[0]):
        raise APIError("Export must name exactly one canonical factory catalog key.")
    if (not isinstance(projects, list) or not 1 <= len(projects) <= 200
            or any(not isinstance(value, str) or not _PROJECT.fullmatch(value) for value in projects)
            or len(set(projects)) != len(projects) or set(projects) != set(requested_projects)):
        raise APIError("Export allowed_project_numbers do not match the requested projects.")
    encoded = response["zip_base64"]
    if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * ((MAX_ZIP_BYTES + 2) // 3):
        raise APIError("Export zip_base64 is empty, invalid or exceeds the compressed-size limit.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise APIError("Export zip_base64 is invalid.") from error
    if len(data) > MAX_ZIP_BYTES or base64.b64encode(data).decode("ascii") != encoded:
        raise APIError("Export zip_base64 is noncanonical or exceeds the compressed-size limit.")
    _check_archive(data, factories, projects)
    return EsafExportPackage(name, data, tuple(factories), tuple(projects))
