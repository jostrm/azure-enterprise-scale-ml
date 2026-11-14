"""Coverage of the AI Factory ``enable*`` flags by the resources a model found."""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .classification import Candidate
from .signals import SignalCatalog


class CoverageAnalyzer:
    """Compares the configuration flags of the factory with what discovery found.

    Project-home models report project flags; common-home models report the flags of
    resources deployed to the common resource group (``commonResourceFlags``).
    """

    def __init__(self, catalog: SignalCatalog):
        self._catalog = catalog

    def analyze(self, flags: dict, home: str, candidates: Iterable[Candidate],
                disabled_profiles: set[str] | frozenset[str] = frozenset()) -> tuple[list[dict], list[str]]:
        if not flags:
            return [], []
        counts = Counter(c.profile.key for c in candidates if c.origin == home)
        by_flag = self._catalog.flags_to_profiles()
        rows, warnings = [], []
        for flag in sorted(by_flag):
            if flag not in flags or (flag in self._catalog.common_resource_flags) != (home == "common"):
                continue
            profiles = list(by_flag[flag])
            enabled, found = flags[flag], sum(counts[p] for p in profiles)
            excluded = found and all(p in disabled_profiles for p in profiles if counts[p])
            status = ("excluded-by-override" if excluded else "monitored" if enabled and found
                      else "missing" if enabled else "present-but-disabled" if found else "disabled")
            rows.append({"flag": flag, "enabled": enabled, "profiles": profiles, "resources": found,
                         "status": status})
            if status == "missing":
                warnings.append(f"{flag} is true but no {'/'.join(profiles)} resource was found; "
                                "the deployment may be incomplete or the resource was removed.")
        return rows, warnings
