"""Read-only, explicitly authorized access to an operator-selected graph snapshot."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .policy import GRAPH_APPLICATION_TOOLS


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GraphQuery(_Closed):
    operation: Literal[
        "symbols", "usages", "callers", "dependencies", "dependents", "trace", "pipeline", "impact",
    ]
    query: str = Field(default="", max_length=2000)
    node_id: str = Field(default="", max_length=512)
    depth: int = Field(default=2, ge=0, le=5)
    limit: int = Field(default=20, ge=1, le=100)


class ArchitectureSearch(_Closed):
    query: str = Field(default="", max_length=2000)
    operation: Literal["notes", "adrs"] = "notes"
    limit: int = Field(default=20, ge=1, le=100)


class ArchitectureNote(_Closed):
    node_id: str = Field(min_length=1, max_length=512)
    operation: Literal["note", "backlinks"] = "note"
    limit: int = Field(default=20, ge=1, le=100)


class DualGraphContext(_Closed):
    query: str = Field(min_length=1, max_length=2000)
    depth: int = Field(default=2, ge=0, le=5)
    limit: int = Field(default=20, ge=1, le=100)


class _Error(_Closed):
    code: str
    message: str


class _GraphPayload(_Closed):
    schema_version: Literal[1]
    status: Literal["ok"]
    operation: str
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: dict
    freshness: dict
    results: list[dict] = Field(max_length=100)
    citations: list[dict]
    truncated: bool
    warnings: list[str]
    uncertainty: list[str]
    structural_retrieved: bool | None = None
    architecture_retrieved: bool | None = None


class GraphResult(_Closed):
    ok: bool
    data: _GraphPayload | None = None
    error: _Error | None = None


_TOOLS = {
    "graph_status": (_Closed, "Report snapshot provenance and freshness; not live deployment health."),
    "graph_query": (GraphQuery, "Query bounded code relationships from the configured static snapshot."),
    "architecture_search": (ArchitectureSearch, "Search architecture notes or ADRs in the configured snapshot."),
    "architecture_note": (ArchitectureNote, "Read a bounded architecture note or its backlinks; never write notes."),
    "dual_graph_context": (DualGraphContext, "Combine cited code and architecture evidence from one static snapshot."),
}
assert frozenset(_TOOLS) == GRAPH_APPLICATION_TOOLS


def authorized(runtime, principal, scope_key) -> bool:
    config = getattr(runtime.settings, "dual_graph", None)
    if not config or scope_key not in config.allowed_scopes:
        return False
    try:
        runtime.security.authorize(runtime.settings, principal, scope_key, "graph.read")
    except PermissionError:
        return False
    return True


def descriptors() -> list[dict]:
    return [{
        "name": name, "description": description,
        "inputSchema": model.model_json_schema(), "outputSchema": GraphResult.model_json_schema(),
        "annotations": {
            "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
        },
    } for name, (model, description) in _TOOLS.items()]


def call(runtime, principal, scope_key, name, arguments) -> dict:
    if not authorized(runtime, principal, scope_key):
        raise PermissionError("Graph access requires an explicit exact-scope graph.read grant.")
    args = _TOOLS[name][0].model_validate(arguments).model_dump()
    operation = args.pop("operation", {
        "graph_status": "status", "dual_graph_context": "context",
    }.get(name))
    config = runtime.settings.dual_graph
    repository = None
    if config.allow_source_access:
        candidate = Path(runtime.settings.knowledge.repository_root)
        if candidate.is_dir():
            repository = candidate
    try:
        from aifactory_agent.dual_graph import DualGraphStore, GraphError
    except ImportError:
        return {"ok": False, "error": {
            "code": "graph_unavailable", "message": "The configured graph runtime is unavailable.",
        }}
    try:
        data = DualGraphStore(
            config.snapshot_root, repository_root=repository,
            expected_snapshot_id=config.expected_snapshot_id,
        ).query(operation, **args)
        return GraphResult(ok=True, data=data).model_dump(exclude_none=True)
    except (GraphError, OSError, ValueError):
        return {"ok": False, "error": {
            "code": "graph_unavailable",
            "message": "The configured graph snapshot is unavailable or failed integrity validation.",
        }}


class GraphOnlyBackend:
    """Fixed corpus-only ceiling for the existing server; no Factory tool/store construction."""

    def __init__(self, runtime, principal, scope_key):
        self.runtime, self.principal, self.scope_key = runtime, principal, scope_key
        self._authorize()

    def _authorize(self):
        from .backend import BackendError

        if not isinstance(self.scope_key, str) or not authorized(self.runtime, self.principal, self.scope_key):
            raise BackendError("forbidden", "An explicit graph.read grant is required for this graph scope.", 403)

    def list_tools(self) -> list[dict]:
        self._authorize()
        return descriptors()

    def call_tool(self, name: str, arguments: dict) -> dict:
        from .backend import BackendError

        self._authorize()
        if not isinstance(name, str) or name not in GRAPH_APPLICATION_TOOLS:
            raise BackendError("unsupported_tool", "This tool is not available in graph-only mode.", 400)
        if not isinstance(arguments, dict):
            raise BackendError("invalid_arguments", "Arguments do not match the closed tool schema.", 400)
        try:
            result = call(self.runtime, self.principal, self.scope_key, name, arguments)
        except ValidationError:
            raise BackendError("invalid_arguments", "Arguments do not match the closed tool schema.", 400) from None
        return self.runtime.sdk.redact_secrets(result, None)
