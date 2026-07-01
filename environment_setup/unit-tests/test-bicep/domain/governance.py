"""Domain layer: config integrity + security/governance checks.

Two kinds of checks:
- Offline config integrity over .env.template / variables.yaml (pure, no Azure).
- Security posture over a live deployment via the CLI seam (mockable).

Once-and-only-once rules: placeholder detection, mandatory vars, mutually
exclusive flags, key-auth disablement. Live checks return bools so app-layer
tests can assert least-privilege RBAC and Defender propagation.
"""
from __future__ import annotations

from base import cli, config

# Vars that must always be present and non-empty in the GitHub .env.template.
MANDATORY_VARS: tuple[str, ...] = (
    "AIFACTORY_LOCATION",
    "AIFACTORY_LOCATION_SHORT",
    "AIFACTORY_PREFIX",
)


def placeholder_leaks(env: dict[str, str], keys: tuple[str, ...]) -> list[str]:
    """Mandatory keys whose default still contains an unresolved <todo> marker.

    Optional user-fill vars legitimately ship <todo> placeholders; mandatory
    ones must have a concrete committed default.
    """
    return [k for k in keys if "todo" in env.get(k, "").lower()]


def missing_mandatory(env: dict[str, str]) -> list[str]:
    return [k for k in MANDATORY_VARS if not env.get(k)]


def cmk_softdelete_conflict(env: dict[str, str]) -> bool:
    """CMK requires Key Vault soft-delete > 7 days; flag the invalid combo."""
    if env.get("CMK", "false").lower() != "true":
        return False
    try:
        days = int(env.get("KEYVAULT_SOFT_DELETE", "0"))
    except ValueError:
        return True
    return days <= 7


def key_auth_disabled(account: str) -> bool:
    """Account has disableLocalAuth=true (AAD-only). Live read via az."""
    data = cli.az_json(["cognitiveservices", "account", "show", "-n", account])
    return bool(data) and data.get("properties", {}).get("disableLocalAuth") is True


def public_endpoint_count(env: dict[str, str]) -> int:
    """Number of public-access flags left enabled (0 in private mode)."""
    flags = ("ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET", "ENABLE_PUBLIC_GENAI_ACCESS")
    return sum(1 for f in flags if env.get(f, "false").lower() == "true")


def identity_roles(principal_id: str) -> list[str]:
    """Role names assigned to a managed identity (for least-privilege checks)."""
    data = cli.az_json(["role", "assignment", "list", "--assignee", principal_id, "--all"])
    if not data:
        return []
    return sorted({a.get("roleDefinitionName", "") for a in data if a.get("roleDefinitionName")})
