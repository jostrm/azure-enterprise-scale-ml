"""Validated signal/profile overrides that produce tuned profile prototypes."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .. import catalog as raw
from .signals import Profile, SignalCatalog

PROFILE_OVERRIDE_FIELDS = frozenset({"enabled", "impact", "resourceHealth"})
SIGNAL_OVERRIDE_FIELDS = frozenset({"enabled", "degradedThreshold", "unhealthyThreshold", "timeGrain",
                                    "refreshInterval"})


@dataclass(frozen=True)
class OverrideSet:
    """``{"profiles": {key: change}, "signals": {"profile/signal": change}}`` (precedence: later merges win)."""

    profiles: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, document, catalog: SignalCatalog) -> "OverrideSet":
        if isinstance(document, OverrideSet):
            return document
        document = copy.deepcopy(document or {})
        if not isinstance(document, dict):
            raise ValueError("Overrides must be a JSON object with profiles and/or signals sections.")
        unknown = set(document) - {"signals", "profiles"}
        if unknown:
            raise ValueError(f"Unknown override sections: {sorted(unknown)}")
        profiles, signals = document.get("profiles") or {}, document.get("signals") or {}
        if not isinstance(profiles, dict) or not isinstance(signals, dict):
            raise ValueError("Override sections must be JSON objects.")
        for key, change in profiles.items():
            if not catalog.has_profile(key):
                raise ValueError(f"Override references unknown profile {key!r}.")
            if not isinstance(change, dict):
                raise ValueError(f"Override for profile {key} must be an object.")
            bad = set(change) - PROFILE_OVERRIDE_FIELDS
            if bad:
                raise ValueError(f"Unsupported profile override fields for {key}: {sorted(bad)}")
            if "impact" in change and change["impact"] not in raw.IMPACTS:
                raise ValueError(f"Impact for {key} must be one of {sorted(raw.IMPACTS)}.")
            if "resourceHealth" in change and change["resourceHealth"] not in {"Enabled", "Disabled"}:
                raise ValueError(f"resourceHealth for {key} must be Enabled or Disabled.")
        for key, change in signals.items():
            profile_key, _, signal_name = key.partition("/")
            profile = catalog.profile(profile_key) if catalog.has_profile(profile_key) else None
            if profile is None or profile.signal(signal_name) is None:
                raise ValueError(f"Override references unknown signal {key!r}.")
            if not isinstance(change, dict):
                raise ValueError(f"Override for signal {key} must be an object.")
            bad = set(change) - SIGNAL_OVERRIDE_FIELDS
            if bad:
                raise ValueError(f"Unsupported signal override fields for {key}: {sorted(bad)}")
            if change.get("enabled") is False and signal_name in profile.aggregation_members():
                raise ValueError(f"{key} belongs to an aggregation group; disable the whole profile instead.")
            if "refreshInterval" in change and change["refreshInterval"] not in raw.REFRESH_INTERVALS:
                raise ValueError(f"refreshInterval for {key} is not supported.")
        return cls(profiles, signals)

    def merge(self, other: "OverrideSet | None") -> "OverrideSet":
        if other is None or other.is_empty():
            return self
        merged = []
        for mine, theirs in ((self.profiles, other.profiles), (self.signals, other.signals)):
            section = {key: dict(change) for key, change in mine.items()}
            for key, change in theirs.items():
                section[key] = {**section.get(key, {}), **change}
            merged.append(section)
        return OverrideSet(*merged)

    def is_empty(self) -> bool:
        return not self.profiles and not self.signals

    def to_document(self) -> dict:
        document = {}
        if self.profiles:
            document["profiles"] = copy.deepcopy(self.profiles)
        if self.signals:
            document["signals"] = copy.deepcopy(self.signals)
        return document

    def resolve(self, catalog: SignalCatalog) -> dict[str, Profile | None]:
        """Effective profile per key (``None`` when disabled); untouched profiles stay shared."""
        resolved: dict[str, Profile | None] = {}
        for profile in catalog.profiles:
            change = self.profiles.get(profile.key, {})
            if change.get("enabled") is False:
                resolved[profile.key] = None
                continue
            changes = {}
            if "impact" in change:
                changes["impact"] = change["impact"]
            if "resourceHealth" in change:
                changes["resource_health"] = change["resourceHealth"]
            signals, touched = [], False
            for signal in profile.signals:
                key = f"{profile.key}/{signal.name}"
                signal_change = self.signals.get(key)
                if signal_change is None:
                    signals.append(signal)
                    continue
                touched = True
                if signal_change.get("enabled", True):
                    signals.append(signal.evolve(signal_change, key))
            if touched:
                changes["signals"] = tuple(signals)
            resolved[profile.key] = profile.clone(**changes) if changes else profile
        return resolved
