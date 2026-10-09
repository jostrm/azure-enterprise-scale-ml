"""Alert policy and health objective value rules shared by definitions and the CLI."""
from __future__ import annotations

from .. import catalog as raw

POLICY_KEYS = frozenset({
    "rootUnhealthySeverity", "rootDegradedSeverity", "layerUnhealthySeverity", "layerDegradedSeverity",
    "resourceUnhealthySeverity", "resourceDegradedSeverity",
})
DEFAULT_ALERT_POLICY = {
    "rootUnhealthySeverity": "Sev1", "rootDegradedSeverity": "Sev3", "layerUnhealthySeverity": "Sev2",
    "layerDegradedSeverity": "", "resourceUnhealthySeverity": "", "resourceDegradedSeverity": "",
}


def validate_alert_policy(policy) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("The alert policy must be a JSON object.")
    unknown = set(policy) - POLICY_KEYS
    if unknown:
        raise ValueError(f"Unknown alert policy keys: {sorted(unknown)}")
    for key, value in policy.items():
        if value not in ("", *raw.SEVERITIES):
            raise ValueError(f"{key}: severity must be empty or one of {raw.SEVERITIES}.")
    return dict(policy)


def validate_health_objective(value, name: str = "healthObjective") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be an integer between 0 and 100.")
    return value
