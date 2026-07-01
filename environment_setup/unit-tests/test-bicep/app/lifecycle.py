"""App layer: deploy/cleanup lifecycle context managers.

Guarantees cleanup even on failure so integration tests are idempotent and
re-runnable. Set env LIVE_AZURE=1 to opt in; otherwise integration tests skip.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from domain import factory, project
from domain.scenarios import Scenario


def live_enabled() -> bool:
    return os.environ.get("LIVE_AZURE", "0") == "1"


@contextmanager
def common_environment(scenario: Scenario, env: dict[str, str]):
    common = factory.deploy_common(scenario, env)
    try:
        yield common
    finally:
        factory.cleanup_common(common)


@contextmanager
def project_environment(scenario: Scenario, env: dict[str, str]):
    proj = project.deploy_project(scenario, env)
    try:
        yield proj
    finally:
        project.cleanup_project(proj)
