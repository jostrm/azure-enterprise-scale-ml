"""Domain layer: deploy/cleanup the AI Factory COMMON part.

The common part = shared vNet, common RG, ACR, keyvault, datalake, etc. These
are placeholders; implement against the existing bootstrap scripts and
esml-common bicep one-by-one. Cleanup must be idempotent so tests re-run.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..base import cli
from ..domain.scenarios import Scenario


@dataclass
class DeployedCommon:
    resource_group: str
    vnet_name: str
    acr_name: str
    location: str


def deploy_common(scenario: Scenario, env: dict[str, str]) -> DeployedCommon:
    """Deploy the common part. Placeholder.

    TODO: shell out to bootstrap (e.g. 01/02 scripts + esml-common bicep) with
    scenario.env_overrides() merged into env, then return discovered names.
    """
    raise NotImplementedError("deploy_common not yet implemented")


def cleanup_common(common: DeployedCommon) -> bool:
    """Delete the common resource group. Placeholder (idempotent).

    TODO: `az group delete --name <rg> --yes --no-wait` and role-assignment
    cleanup via cleanup-role-assignments.ps1 equivalent in bash.
    """
    raise NotImplementedError("cleanup_common not yet implemented")


def common_exists(resource_group: str) -> bool:
    return bool(cli.az_json(["group", "show", "-n", resource_group]))
