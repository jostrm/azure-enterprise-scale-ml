"""Data-source settings for one agent: SharePoint, Foundry IQ, Fabric IQ and uploaded documents.

Pure domain module: no Azure SDK imports, so any client (CLI, web app, desktop "Settings"
screen) can validate the same data-sources.json before it is saved. agents.py is the
Foundry adapter that turns the enabled sources into SDK tool objects.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from pathlib import Path, PurePath
from typing import Callable, Protocol
from urllib.parse import urlsplit

KINDS = ("sharepoint", "foundry_iq", "fabric_iq", "uploaded_documents")
LABELS = {
    "sharepoint": "SharePoint",
    "foundry_iq": "Foundry IQ knowledge base",
    "fabric_iq": "Fabric IQ data agent",
    "uploaded_documents": "uploaded documents",
}
UPLOAD_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html", ".csv", ".json"})
MAX_UPLOAD_BYTES = 16 * 1024 * 1024  # Azure AI Search blob indexer limit on the Basic tier

_STORAGE_ACCOUNT = re.compile(r"^[a-z0-9]{3,24}$")
_CONTAINER = re.compile(r"^(?!.*--)[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DataSourceError(ValueError):
    """A data-sources.json value is missing, unknown or unsafe."""


@dataclass(frozen=True)
class SharePointSource:
    enabled: bool = False
    project_connection_name: str = ""
    kind = "sharepoint"
    required = ("project_connection_name",)


@dataclass(frozen=True)
class FoundryIqSource:
    enabled: bool = False
    server_label: str = ""
    server_url: str = ""
    project_connection_name: str = ""
    kind = "foundry_iq"
    required = ("server_label", "server_url", "project_connection_name")


@dataclass(frozen=True)
class FabricIqSource:
    enabled: bool = False
    project_connection_name: str = ""
    kind = "fabric_iq"
    required = ("project_connection_name",)


@dataclass(frozen=True)
class UploadedDocumentsSource:
    """Own documents in the project's data storage, indexed by a Foundry IQ knowledge base."""

    enabled: bool = False
    storage_account: str = ""
    container: str = ""
    folder: str = ""
    server_label: str = ""
    server_url: str = ""
    project_connection_name: str = ""
    kind = "uploaded_documents"
    required = ("storage_account", "container", "server_label", "server_url", "project_connection_name")


_TYPES = {
    "sharepoint": SharePointSource,
    "foundry_iq": FoundryIqSource,
    "fabric_iq": FabricIqSource,
    "uploaded_documents": UploadedDocumentsSource,
}


@dataclass(frozen=True)
class DataSourceSettings:
    sharepoint: SharePointSource = SharePointSource()
    foundry_iq: FoundryIqSource = FoundryIqSource()
    fabric_iq: FabricIqSource = FabricIqSource()
    uploaded_documents: UploadedDocumentsSource = UploadedDocumentsSource()


class ToolFactory(Protocol):
    """Port implemented by the Foundry adapter (agents.FoundryToolFactory)."""

    def sharepoint(self, connection_id: str): ...
    def knowledge_base(self, server_label: str, server_url: str, connection_id: str): ...
    def fabric_iq(self, connection_id: str): ...


def _check_kb_url(kind: str, url: str) -> None:
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or "/knowledgebases/" not in parts.path or not parts.path.endswith("/mcp")):
        raise DataSourceError(f"{kind}.server_url must be an https Foundry IQ knowledge-base MCP endpoint "
                              "(https://<search>.search.windows.net/knowledgebases/<kb>/mcp?api-version=...)")


def _check_folder(folder: str) -> None:
    if not folder:
        return
    segments = folder.split("/")
    if "\\" in folder or folder.startswith("/") or any(s in ("", ".", "..") for s in segments):
        raise DataSourceError("uploaded_documents.folder must be a relative blob prefix such as users/alex")


def _parse_one(kind: str, raw) -> object:
    if not isinstance(raw, dict):
        raise DataSourceError(f"{kind} must be an object")
    source_type = _TYPES[kind]
    allowed = {f.name for f in fields(source_type)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DataSourceError(f"{kind} has unknown field(s): {', '.join(unknown)}")
    if not isinstance(raw.get("enabled", False), bool):
        raise DataSourceError(f"{kind}.enabled must be true or false")
    values = {}
    for name in allowed - {"enabled"}:
        value = raw.get(name, "")
        if not isinstance(value, str) or any(ord(ch) < 32 for ch in value):
            raise DataSourceError(f"{kind}.{name} must be a single-line string")
        values[name] = value.strip()
    source = source_type(enabled=raw.get("enabled", False), **values)
    if not source.enabled:
        return source
    missing = [name for name in source.required if not values[name]]
    if missing:
        raise DataSourceError(f"{kind} is enabled but misses: {', '.join(missing)}")
    if "server_url" in values:
        _check_kb_url(kind, values["server_url"])
    for name in ("project_connection_name", "server_label"):
        if name in values and not _NAME.match(values[name]):
            raise DataSourceError(f"{kind}.{name} may only contain letters, digits, '.', '_' and '-'")
    if kind == "uploaded_documents":
        if not _STORAGE_ACCOUNT.match(values["storage_account"]):
            raise DataSourceError("uploaded_documents.storage_account must be 3-24 lowercase letters or digits")
        if not _CONTAINER.match(values["container"]):
            raise DataSourceError("uploaded_documents.container must be a valid lowercase blob container name")
        _check_folder(values["folder"])
    return source


def parse_data_sources(raw: dict) -> DataSourceSettings:
    if not isinstance(raw, dict):
        raise DataSourceError("data sources must be a JSON object")
    unknown = sorted(set(raw) - set(KINDS))
    if unknown:
        raise DataSourceError(f"unknown data source(s): {', '.join(unknown)} (supported: {', '.join(KINDS)})")
    return DataSourceSettings(**{kind: _parse_one(kind, raw[kind]) for kind in KINDS if kind in raw})


def load_data_sources(path: str | Path) -> DataSourceSettings:
    return parse_data_sources(json.loads(Path(path).read_text(encoding="utf-8")))


def enabled_sources(settings: DataSourceSettings) -> list:
    return [source for source in (getattr(settings, kind) for kind in KINDS) if source.enabled]


def build_tools(settings: DataSourceSettings, factory: ToolFactory,
                resolve_connection: Callable[[str], str]) -> list:
    """One tool per enabled source, in KINDS order.

    SharePoint and Fabric IQ tools need the project connection's id (resolve_connection);
    a knowledge-base MCP tool takes the connection name as the SDK expects.
    """
    builders = {  # Factory Method per kind
        "sharepoint": lambda s: factory.sharepoint(resolve_connection(s.project_connection_name)),
        "foundry_iq": lambda s: factory.knowledge_base(s.server_label, s.server_url, s.project_connection_name),
        "fabric_iq": lambda s: factory.fabric_iq(resolve_connection(s.project_connection_name)),
        "uploaded_documents": lambda s: factory.knowledge_base(s.server_label, s.server_url,
                                                               s.project_connection_name),
    }
    return [builders[source.kind](source) for source in enabled_sources(settings)]


def agent_instructions(settings: DataSourceSettings) -> str:
    sources = enabled_sources(settings)
    if not sources:
        return ("No data source is enabled in data-sources.json. Say that you cannot answer from "
                "company data until a data source is enabled in Settings. Never invent facts.")
    names = "\n".join(f"- {LABELS[source.kind]}" for source in sources)
    return ("You answer questions using only these enabled data sources:\n"
            f"{names}\n"
            "Pick the tool whose source fits the question; use several when the question spans them.\n"
            "Cite the source (document title, site or table) for every fact. If no tool returns the "
            "information, say that it could not be found. Never invent values.")


def upload_blob_name(source: UploadedDocumentsSource, path: PurePath) -> str:
    name = PurePath(path).name.strip()
    if not name or any(ord(ch) < 32 for ch in name):
        raise DataSourceError("the file needs a name")
    if PurePath(name).suffix.lower() not in UPLOAD_EXTENSIONS:
        raise DataSourceError(f"{name}: file type not supported ({', '.join(sorted(UPLOAD_EXTENSIONS))})")
    return f"{source.folder}/{name}" if source.folder else name


def check_upload_size(size: int) -> None:
    if size > MAX_UPLOAD_BYTES:
        raise DataSourceError(f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")


def blob_account_url(source: UploadedDocumentsSource) -> str:
    return f"https://{source.storage_account}.blob.core.windows.net"
