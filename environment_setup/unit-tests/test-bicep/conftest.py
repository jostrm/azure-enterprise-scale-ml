"""Pytest glue for numbered test tiers; the tiers themselves are listed in tiers.py."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from base.tiers import ENVIRONMENT_VARIABLE, Selection
from tiers import MANIFEST


SUITE = Path(__file__).resolve().parent
SELECTION = pytest.StashKey[Selection]()
DESELECTED = pytest.StashKey[int]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--tiers", default=None, metavar="SELECTION",
        help=f"Test tiers to run, such as 1-4, 1,5, 5 or all (default: ${ENVIRONMENT_VARIABLE}, "
             f"else {MANIFEST.default}). A test file named on the command line runs unless a "
             "selection is given. See tiers.py.",
    )


def pytest_configure(config: pytest.Config) -> None:
    for tier in MANIFEST.tiers:
        config.addinivalue_line("markers", f"tier{tier.number}: tier {tier.number} ({tier.name}): {tier.summary}")
    try:
        config.stash[SELECTION] = MANIFEST.resolve(config.getoption("--tiers"), os.environ)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from None


def explicit_files(config: pytest.Config) -> set[Path]:
    base = Path(config.invocation_params.dir)
    paths = {(base / argument.split("::", 1)[0]).resolve() for argument in config.args}
    return {path for path in paths if path.is_file()}


def relative_to_suite(path: Path) -> str:
    try:
        return path.resolve().relative_to(SUITE).as_posix()
    except ValueError:
        return path.as_posix()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    selection = config.stash[SELECTION]
    named = explicit_files(config)
    kept, deselected = [], []
    for item in items:
        relative = relative_to_suite(item.path)
        tier = MANIFEST.tier_of(relative)
        if tier is not None:
            item.add_marker(getattr(pytest.mark, f"tier{tier}"))
        keep = MANIFEST.keeps(relative, selection, explicit=item.path.resolve() in named)
        (kept if keep else deselected).append(item)
    config.stash[DESELECTED] = len(deselected)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    selection = config.stash.get(SELECTION, None)
    deselected = config.stash.get(DESELECTED, 0)
    if selection is None or not deselected:
        return
    names = ", ".join(f"{tier.number} {tier.name}" for tier in MANIFEST.tiers if tier.number in selection.skipped)
    terminalreporter.write_line(
        f"Test tiers {selection.spec} ({selection.source}): {deselected} tests deselected from tier(s) {names}. "
        f"Run them with --tiers all or {ENVIRONMENT_VARIABLE}=all."
    )
