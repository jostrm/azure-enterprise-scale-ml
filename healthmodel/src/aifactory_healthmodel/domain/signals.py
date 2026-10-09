"""Immutable catalog domain objects.

* ``Signal`` is a Flyweight: one shared, immutable definition (intrinsic state) reused by
  every entity of a profile; the entity supplies the resource (extrinsic state) when it
  renders its payload. ``SignalFactory`` interns identical definitions.
* ``Profile`` is a Prototype: overrides produce tuned copies with ``clone()`` instead of
  mutating the shared catalog.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .. import catalog as raw

SIGNAL_OVERRIDE_FIELDS = frozenset({"enabled", "degradedThreshold", "unhealthyThreshold", "timeGrain",
                                    "refreshInterval"})


def canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Signal:
    """Shared signal definition. ``kind`` is ``metric`` (azureResource) or ``log`` (azureLogAnalytics)."""

    name: str
    kind: str
    payload: str

    @classmethod
    def from_api(cls, payload: dict, kind: str = "metric") -> "Signal":
        return cls(payload["name"], kind, canonical_json(payload))

    def to_api(self) -> dict:
        return json.loads(self.payload)

    def evolve(self, change: dict, key: str) -> "Signal":
        """Copy-on-write threshold/grain change, validated like the catalog itself."""
        unknown = set(change) - SIGNAL_OVERRIDE_FIELDS
        if unknown:
            raise ValueError(f"Unsupported signal override fields for {key}: {sorted(unknown)}")
        if "refreshInterval" in change and change["refreshInterval"] not in raw.REFRESH_INTERVALS:
            raise ValueError(f"refreshInterval for {key} is not supported.")
        payload = self.to_api()
        rules = payload["evaluationRules"]
        if "unhealthyThreshold" in change:
            rules["unhealthyRule"]["threshold"] = change["unhealthyThreshold"]
        if "degradedThreshold" in change:
            if change["degradedThreshold"] is None:
                rules.pop("degradedRule", None)
            else:
                rules.setdefault("degradedRule", {"operator": rules["unhealthyRule"]["operator"]})
                rules["degradedRule"]["threshold"] = change["degradedThreshold"]
        for name in ("timeGrain", "refreshInterval"):
            if name in change:
                payload[name] = change[name]
        unhealthy, degraded = rules["unhealthyRule"], rules.get("degradedRule")
        for rule in filter(None, (unhealthy, degraded)):
            threshold = rule.get("threshold")
            if not isinstance(threshold, int) or isinstance(threshold, bool):
                raise ValueError(f"Thresholds for {key} must be integers.")
        if degraded:
            operator = unhealthy["operator"]
            if (operator.startswith("Greater") and degraded["threshold"] > unhealthy["threshold"]) or (
                    operator.startswith("Less") and degraded["threshold"] < unhealthy["threshold"]):
                raise ValueError(f"Degraded threshold for {key} must be reached before the unhealthy threshold.")
        return Signal.from_api(payload, self.kind)


class SignalFactory:
    """Flyweight factory: one shared instance per distinct signal definition."""

    def __init__(self):
        self._pool: dict[tuple[str, str], Signal] = {}

    def get(self, payload: dict, kind: str = "metric") -> Signal:
        key = (kind, canonical_json(payload))
        signal = self._pool.get(key)
        if signal is None:
            signal = self._pool[key] = Signal(payload["name"], kind, key[1])
        return signal

    def __len__(self) -> int:
        return len(self._pool)


@dataclass(frozen=True)
class Layer:
    key: str
    display_name: str
    impact: str
    description: str = ""

    def clone(self, **changes) -> "Layer":
        return dataclasses.replace(self, **changes)


@dataclass(frozen=True)
class Profile:
    key: str
    display_name: str
    resource_type: str
    layer: str
    impact: str
    resource_health: str
    kinds: tuple[str, ...] = ()
    hns: bool | None = None
    enable_flags: tuple[str, ...] = ()
    signals: tuple[Signal, ...] = ()
    log_signals: tuple[Signal, ...] = ()
    aggregation_groups: tuple[str, ...] = ()
    nested_model: bool = False
    no_source_hint: str = ""
    description: str = ""

    def clone(self, **changes) -> "Profile":
        return dataclasses.replace(self, **changes)

    def matches(self, resource_type: str, kind: str | None, hns: bool | None) -> bool:
        if self.resource_type != (resource_type or "").lower():
            return False
        if self.kinds and (kind or "").lower() not in self.kinds:
            return False
        return self.hns is None or bool(hns) is self.hns

    def has_signal_source(self, workspace: str | None) -> bool:
        return bool(self.signals or self.resource_health == "Enabled" or self.nested_model
                    or (workspace and self.log_signals))

    def signal(self, name: str) -> Signal | None:
        return next((s for s in self.signals if s.name == name), None)

    def aggregation_groups_api(self) -> list[dict]:
        return [json.loads(group) for group in self.aggregation_groups]

    def aggregation_members(self) -> frozenset[str]:
        return frozenset(m for group in self.aggregation_groups_api() for m in group["members"])


class SignalCatalog:
    """Read-only catalog: layers, profiles, classification rules and enable-flag mapping."""

    def __init__(self, *, api_version: str, layers: tuple[Layer, ...], profiles: tuple[Profile, ...],
                 excluded_types: frozenset[str] = frozenset(), not_monitorable: dict | None = None,
                 common_resource_flags: frozenset[str] = frozenset(), non_resource_flags: dict | None = None):
        self.api_version = api_version
        self.layers = tuple(layers)
        self.profiles = tuple(profiles)
        self.excluded_types = frozenset(excluded_types)
        self.not_monitorable = MappingProxyType(dict(not_monitorable or {}))
        self.common_resource_flags = frozenset(common_resource_flags)
        self.non_resource_flags = MappingProxyType(dict(non_resource_flags or {}))
        self._profiles = {p.key: p for p in self.profiles}
        self._layers = {layer.key: layer for layer in self.layers}

    @classmethod
    def from_document(cls, document: dict, factory: SignalFactory | None = None) -> "SignalCatalog":
        """Build from a resolved catalog document (see ``catalog.load_catalog``)."""
        factory = factory or SignalFactory()
        profiles = []
        for item in document["profiles"]:
            match = item["match"]
            profiles.append(Profile(
                key=item["key"], display_name=item["displayName"], resource_type=match["type"].lower(),
                layer=item["layer"], impact=item["impact"], resource_health=item["resourceHealth"],
                kinds=tuple(k.lower() for k in match.get("kinds") or ()), hns=match.get("hns"),
                enable_flags=tuple(item.get("enableFlags", ())),
                signals=tuple(factory.get(s) for s in item.get("signals", ())),
                log_signals=tuple(factory.get(s, "log") for s in item.get("logAnalyticsSignals", ())),
                aggregation_groups=tuple(canonical_json(g) for g in item.get("signalAggregationGroups", ())),
                nested_model=bool(item.get("nestedModel")), no_source_hint=item.get("noSourceHint", ""),
                description=item.get("description", ""),
            ))
        layers = tuple(Layer(item["key"], item["displayName"], item["impact"], item.get("description", ""))
                       for item in document["layers"])
        return cls(api_version=document["apiVersion"], layers=layers, profiles=tuple(profiles),
                   excluded_types=frozenset(t.lower() for t in document.get("excludedTypes", ())),
                   not_monitorable=document.get("notMonitorable", {}),
                   common_resource_flags=frozenset(document.get("commonResourceFlags", ())),
                   non_resource_flags=document.get("nonResourceFlags", {}))

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "SignalCatalog":
        return cls.from_document(raw.load_catalog(path))

    @property
    def layer_order(self) -> tuple[str, ...]:
        return tuple(layer.key for layer in self.layers)

    def profile(self, key: str) -> Profile:
        try:
            return self._profiles[key]
        except KeyError:
            raise KeyError(f"Unknown health profile: {key}") from None

    def has_profile(self, key: str) -> bool:
        return key in self._profiles

    def layer(self, key: str) -> Layer:
        try:
            return self._layers[key]
        except KeyError:
            raise KeyError(f"Unknown health layer: {key}") from None

    def has_layer(self, key: str) -> bool:
        return key in self._layers

    def classify(self, resource_type: str, kind: str | None = None, hns: bool | None = None) -> Profile | None:
        return next((p for p in self.profiles if p.matches(resource_type, kind, hns)), None)

    def is_excluded(self, resource_type: str) -> bool:
        return (resource_type or "").lower() in self.excluded_types

    def flags_to_profiles(self) -> dict[str, tuple[str, ...]]:
        mapping: dict[str, list[str]] = {}
        for profile in self.profiles:
            for flag in profile.enable_flags:
                mapping.setdefault(flag, []).append(profile.key)
        return {flag: tuple(keys) for flag, keys in mapping.items()}
