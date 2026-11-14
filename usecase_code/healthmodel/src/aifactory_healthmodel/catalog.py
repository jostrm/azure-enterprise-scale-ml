"""Load, validate and query the AI Factory health signal catalog.

The catalog (``healthmodel/catalog/signal-catalog.json``) is the single source
of truth for layers, resource profiles, classification rules and signals.
"""
from __future__ import annotations

import copy
import json
import os
import re
from functools import lru_cache
from pathlib import Path

HEALTHMODEL_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = HEALTHMODEL_ROOT / "catalog" / "signal-catalog.json"

# Proxy (child) resource names: entities, signals, relationships, auth settings.
NAME_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]{1,258}[a-zA-Z0-9]")
# Health model names are restricted further to lowercase so the implicit root
# entity name always equals the model name.
MODEL_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,42}[a-z0-9]")

SUPPORTED_API_VERSIONS = frozenset({"2026-09-01-preview", "2026-10-01-preview"})
IMPACTS = frozenset({"Standard", "Limited", "Suppressed"})
AGGREGATIONS = frozenset({"Average", "Count", "Maximum", "Minimum", "None", "Total"})
REFRESH_INTERVALS = frozenset({"PT1M", "PT5M", "PT10M", "PT15M", "PT30M", "PT1H", "PT2H"})
OPERATORS = frozenset({
    "Dynamic", "Equal", "GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual", "NotEqual",
})
GROUP_AGGREGATIONS = frozenset({"BestOf", "MaxNotHealthy", "MinHealthy", "WorstOf"})
SEVERITIES = ("Sev0", "Sev1", "Sev2", "Sev3", "Sev4")
HEALTH_STATES = ("Healthy", "Degraded", "Unhealthy", "Unknown")
SIGNAL_KEYS = frozenset({
    "name", "displayName", "signalKind", "metricNamespace", "metricName", "aggregationType",
    "dataUnit", "timeGrain", "refreshInterval", "dimensionFilter", "evaluationRules",
})
REQUIRED_SIGNAL_KEYS = frozenset({
    "name", "displayName", "signalKind", "metricNamespace", "metricName", "aggregationType",
    "timeGrain", "refreshInterval", "evaluationRules",
})


def load_catalog(path: str | os.PathLike | None = None) -> dict:
    """Return a resolved deep copy of the catalog (profile inheritance applied)."""
    source = Path(path or os.environ.get("AIF_HEALTHMODEL_CATALOG") or CATALOG_PATH)
    return copy.deepcopy(_load(str(source.resolve())))


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), list):
        raise ValueError("Signal catalog must be an object with a profiles list.")
    by_key = {p["key"]: p for p in document["profiles"]}
    for item in document["profiles"]:
        parent_key = item.get("inherits")
        if parent_key:
            parent = by_key.get(parent_key)
            if parent is None or parent.get("inherits"):
                raise ValueError(f"Profile {item['key']} inherits from an unknown or nested profile.")
            for field in ("signals", "signalAggregationGroups"):
                item.setdefault(field, copy.deepcopy(parent.get(field, [])))
        item.setdefault("signals", [])
        item.setdefault("signalAggregationGroups", [])
        item.setdefault("enableFlags", [])
    return document


def profile(catalog: dict, key: str) -> dict:
    for item in catalog["profiles"]:
        if item["key"] == key:
            return item
    raise KeyError(f"Unknown health profile: {key}")


def layer(catalog: dict, key: str) -> dict:
    for item in catalog["layers"]:
        if item["key"] == key:
            return item
    raise KeyError(f"Unknown health layer: {key}")


def classify(catalog: dict, resource_type: str, kind: str | None = None, hns: bool | None = None) -> dict | None:
    """Return the profile that models a resource, or None when it is not modelled."""
    resource_type = (resource_type or "").lower()
    kind = (kind or "").lower()
    for item in catalog["profiles"]:
        match = item["match"]
        if match["type"] != resource_type:
            continue
        kinds = [k.lower() for k in match.get("kinds") or []]
        if kinds and kind not in kinds:
            continue
        if "hns" in match and bool(hns) is not match["hns"]:
            continue
        return item
    return None


def is_excluded(catalog: dict, resource_type: str) -> bool:
    return (resource_type or "").lower() in set(catalog["excludedTypes"])
