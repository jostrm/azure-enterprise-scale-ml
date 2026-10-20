"""Numbered test tiers: parse a selection such as "1-4", "1,5" or "all" and filter test files.

Domain-agnostic: the suite's manifest (``tiers.py``) names the tiers and their files;
this module only validates that manifest, resolves which tiers to run and decides
whether a test file is kept. Standard library only.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

ENVIRONMENT_VARIABLE = "AIF_TEST_TIERS"
ALL = "all"
DEFAULT = "default"


@dataclass(frozen=True)
class Tier:
    number: int
    name: str
    summary: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    tiers: frozenset[int]
    spec: str
    source: str
    skipped: tuple[int, ...]

    @property
    def is_default(self) -> bool:
        return self.source == DEFAULT


@dataclass(frozen=True)
class TierManifest:
    tiers: tuple[Tier, ...]
    default: str
    _by_file: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        numbers = [tier.number for tier in self.tiers]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"Tiers must be numbered 1-{len(numbers)} in order, not {numbers}.")
        names = [tier.name for tier in self.tiers]
        if len(set(names)) != len(names):
            raise ValueError(f"Each tier needs a unique name: {names}.")
        by_file: dict[str, int] = {}
        for tier in self.tiers:
            for path in tier.files:
                if path in by_file:
                    raise ValueError(f"{path} is in tier {by_file[path]} and tier {tier.number}.")
                by_file[path] = tier.number
        object.__setattr__(self, "_by_file", by_file)
        self.parse(self.default)

    @property
    def numbers(self) -> tuple[int, ...]:
        return tuple(tier.number for tier in self.tiers)

    def tier_of(self, relative_path: str) -> int | None:
        return self._by_file.get(relative_path)

    def parse(self, spec: str) -> frozenset[int]:
        text = spec.strip().lower()
        if text == ALL:
            return frozenset(self.numbers)
        selected: set[int] = set()
        try:
            for part in text.split(","):
                low, separator, high = part.partition("-")
                first = int(low)
                last = int(high) if separator else first
                if not 1 <= first <= last <= len(self.tiers):
                    raise ValueError
                selected.update(range(first, last + 1))
        except ValueError:
            # The raw value is not echoed: CI logs interpret some text as commands.
            raise ValueError(
                f"Unknown test-tier selection: use tiers 1-{len(self.tiers)}, "
                "a range such as 1-4, a list such as 1,5, or all."
            ) from None
        return frozenset(selected)

    def describe(self, tiers: frozenset[int]) -> str:
        if tiers == frozenset(self.numbers):
            return ALL
        ranges: list[list[int]] = []
        for number in sorted(tiers):
            if ranges and number == ranges[-1][1] + 1:
                ranges[-1][1] = number
            else:
                ranges.append([number, number])
        return ",".join(str(low) if low == high else f"{low}-{high}" for low, high in ranges)

    def resolve(self, option: str | None, environment: Mapping[str, str]) -> Selection:
        """Pick the selection: command-line option, then environment variable, then manifest default."""
        for source, value in (("option", option), ("environment", environment.get(ENVIRONMENT_VARIABLE))):
            if value and value.strip() and value.strip().lower() != DEFAULT:
                return self._selection(value, source)
        return self._selection(self.default, DEFAULT)

    def keeps(self, relative_path: str, selection: Selection, explicit: bool = False) -> bool:
        """Unclassified files always run; a file named explicitly overrides only the default selection."""
        tier = self.tier_of(relative_path)
        return tier is None or tier in selection.tiers or (explicit and selection.is_default)

    def _selection(self, spec: str, source: str) -> Selection:
        tiers = self.parse(spec)
        skipped = tuple(number for number in self.numbers if number not in tiers)
        return Selection(tiers, self.describe(tiers), source, skipped)
