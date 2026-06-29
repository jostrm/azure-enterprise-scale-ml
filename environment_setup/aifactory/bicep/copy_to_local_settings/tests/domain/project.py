"""Domain layer: deploy/cleanup a single AI Factory PROJECT.

A project is deployed AFTER the common part exists. Placeholders; implement
against esml-genai-1 / esml-project bicep one-by-one. Cleanup deletes the
project RG so the suite re-runs cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..base import cli
from ..domain.scenarios import Scenario


@dataclass
class DeployedProject:
    resource_group: str
    project_number: str
    search_name: str | None = None
    foundry_name: str | None = None
    storage_name: str | None = None


def deploy_project(scenario: Scenario, env: dict[str, str]) -> DeployedProject:
    """Deploy one project with scenario flags. Placeholder.

    TODO: invoke esml-genai-1 deploy with scenario.env_overrides(); supports
    all-enabled and all-disabled service matrices.
    """
    raise NotImplementedError("deploy_project not yet implemented")


def cleanup_project(project: DeployedProject) -> bool:
    """Delete the project resource group. Placeholder (idempotent)."""
    raise NotImplementedError("cleanup_project not yet implemented")


def project_exists(resource_group: str) -> bool:
    return bool(cli.az_json(["group", "show", "-n", resource_group]))
