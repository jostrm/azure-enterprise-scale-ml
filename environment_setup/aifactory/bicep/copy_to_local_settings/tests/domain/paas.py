"""Domain layer: PaaS reachability / connectivity checks.

Verify service-to-service reachability using CLIs (az, nslookup) rather than
SDKs. Each check returns a bool so app-layer tests can assert. Pure read-only
checks; safe to run repeatedly against a live deployment.
"""
from __future__ import annotations

from ..base import cli, naming


def acr_reachable(registry: str) -> bool:
    """Container registry resolves + responds to `az acr show`. Placeholder body ok."""
    host = naming.acr_login_host(registry)
    return cli.resolves_to_private_ip(host) and bool(
        cli.az_json(["acr", "show", "-n", registry])
    )


def search_reachable(service: str) -> bool:
    host = naming.search_host(service)
    return cli.resolves_to_private_ip(host)


def storage_reachable(account: str) -> bool:
    host = naming.storage_blob_host(account)
    return cli.resolves_to_private_ip(host)


def foundry_can_reach_search(foundry: str, search: str) -> bool:
    """Foundry -> AI Search connection. Placeholder.

    TODO: query foundry connections via `az` and assert AI Search target.
    """
    raise NotImplementedError("foundry_can_reach_search not yet implemented")


def foundry_can_reach_storage(foundry: str, storage: str) -> bool:
    """Foundry -> Storage connection. Placeholder."""
    raise NotImplementedError("foundry_can_reach_storage not yet implemented")
