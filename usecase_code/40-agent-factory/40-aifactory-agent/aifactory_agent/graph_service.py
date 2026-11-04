"""Scoped read-only Chat adapter over the shared graph core; never a Search provider."""

from __future__ import annotations

import re
from typing import Callable

from .config import Settings
from .security import Principal, authorize

OPERATIONS = (
    "status", "symbols", "usages", "callers", "dependencies", "dependents",
    "trace", "pipeline", "impact", "notes", "note", "backlinks", "adrs", "context",
)


def degraded_graph(reason: str) -> dict:
    return {"status": "degraded", "snapshot_id": None, "freshness": {"status": "unknown"},
            "warnings": [reason], "truncated": False, "results": {},
            "evidence": [], "citations": []}


def requires_graph_context(question: str) -> bool:
    if (re.search(r"\bhealth\b", question, flags=re.IGNORECASE)
            and not re.search(r"\b(?:why|how|code|architect\w*|implement\w*|dependenc\w*)\b",
                              question, flags=re.IGNORECASE)):
        return False
    return bool(re.search(
        r"\b(?:architect\w*|code|source|symbols?|functions?|methods?|classes|class|modules?|"
        r"dependenc\w*|depends?|dependents?|callers?|callees?|calls?|called|defined|definitions?|"
        r"imports?|imported|inherit\w*|usages?|pipeline\w*|"
        r"workflow\w*|implement\w*|refactor\w*|impact|trace|design|adr[s]?|"
        r"repository|bootstrap|deployment|bicep|terraform)\b"
        r"|`[^`]+`|\b[\w.-]+\.(?:py|bicep|yaml|yml|tf)\b"
        r"|(?:how|why)\b.{0,80}\b(?:factory|component|system|service)\b",
        question, flags=re.IGNORECASE,
    ))


def _citation_context(result: dict) -> dict:
    records = result.get("results", [])
    if not isinstance(records, list):
        return result
    note_sources = {item.get("source_file") for item in records if item.get("record_type") == "note"}
    citations, identifiers = [], {}
    counters = {"G": 0, "A": 0}
    used = {item.get("citation_id") for item in result.get("citations", [])}

    def key(item):
        return tuple(item.get(field) for field in ("source_file", "line", "cell", "evidence", "resolution"))

    for original in result.get("citations", []):
        citation = dict(original)
        identifier = citation.get("citation_id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[GA]\d+", identifier):
            prefix = "A" if citation.get("source_file") in note_sources else "G"
            counters[prefix] += 1
            while prefix + str(counters[prefix]) in used:
                counters[prefix] += 1
            identifier = prefix + str(counters[prefix])
            used.add(identifier)
        citation["citation_id"] = identifier
        identifiers[key(citation)] = identifier
        citations.append(citation)
    records = [{**item, "citation_id": identifiers[key(item)]} if key(item) in identifiers else dict(item)
               for item in records]
    if result.get("operation") == "context":
        present = {
            "structural": any(item.get("record_type") in {"node", "edge"} for item in records),
            "architecture": any(item.get("record_type") == "note" for item in records),
        }
        missing = ["graph_" + plane + "_context_missing" for plane, found in present.items() if not found]
        if missing:
            result = {**result, "status": "degraded", "warnings": [*result.get("warnings", []), *missing]}
        result = {**result, "context_planes": present}
    return {**result, "results": records, "evidence": result.get("evidence", records), "citations": citations}


class GraphQueryService:
    def __init__(self, settings: Settings, *, store_factory: Callable | None = None):
        self.settings = settings
        self.store_factory = store_factory

    def query(self, principal: Principal, scope_key: str, operation: str, *,
              query: str = "", node_id: str = "", depth: int = 2, limit: int = 20) -> dict:
        authorize(self.settings, principal, scope_key, "graph.read")
        config = self.settings.dual_graph
        if config is None:
            return degraded_graph("graph_disabled")
        if scope_key not in config.allowed_scopes:
            raise PermissionError("Graph access is not enabled for this exact scope.")
        if operation not in OPERATIONS:
            raise ValueError("Unknown read-only graph operation.")
        if (not isinstance(query, str) or len(query) > 2048
                or not isinstance(node_id, str) or len(node_id) > 1000
                or type(depth) is not int or not 0 <= depth <= 5
                or type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError("Graph queries require bounded text, depth 0-5 and limit 1-50.")
        from .dual_graph import DualGraphStore, GraphError
        factory = self.store_factory or DualGraphStore
        try:
            store = factory(
                config.snapshot_root,
                repository_root=self.settings.knowledge.repository_root if config.allow_source_access else None,
                expected_snapshot_id=config.expected_snapshot_id,
            )
            result = store.query(operation, query=query, node_id=node_id, depth=depth, limit=limit)
            freshness = result.get("freshness", {}).get("status")
            immutable = (config.expected_snapshot_id is not None
                         and config.snapshot_root.name == config.expected_snapshot_id
                         and not config.allow_source_access)
            if freshness not in {"fresh", "immutable"} and not (immutable and freshness == "unverified"):
                result = {**result, "status": "degraded",
                          "warnings": [*result.get("warnings", []), "graph_source_freshness_not_verified"]}
            return _citation_context(result)
        except GraphError as error:
            return degraded_graph("graph_" + error.code)
        except OSError:
            # Do not leak configured workstation paths or unverified snapshot content.
            return degraded_graph("graph_unavailable_or_invalid")
