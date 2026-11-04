"""Shared test setup: import the template package and build services from fakes."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
if str(TEMPLATE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEMPLATE_ROOT))


def find_accelerator_file(relative: str) -> Path | None:
    """Find a file of the accelerator checkout above this template.

    The template lives in purple (`usecase_code/...`) or in a consumer copy next to
    the `azure-enterprise-scale-ml` submodule.
    """
    for parent in TEMPLATE_ROOT.parents:
        for base in (parent, parent / "azure-enterprise-scale-ml"):
            candidate = base / relative
            if candidate.is_file():
                return candidate
    return None


def _add_sdk_source() -> None:
    """Use the SDK from this accelerator checkout when it is not installed (it is stdlib only)."""
    if importlib.util.find_spec("azurefactory") is not None:
        return
    found = find_accelerator_file("environment_setup/azurefactory-cli/src/azurefactory/__init__.py")
    if found is not None:
        sys.path.insert(0, str(found.parents[1]))


_add_sdk_source()


class FakeClock:
    def __init__(self, start: datetime | None = None):
        self.current = start or datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
