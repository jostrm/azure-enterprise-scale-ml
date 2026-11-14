"""ARM deployment parameters for ``bicep/main.bicep``."""
from __future__ import annotations

from ..domain.plan import ModelPlan
from ..domain.policy import DEFAULT_ALERT_POLICY, validate_alert_policy, validate_health_objective

BICEP_OPTIONS = frozenset({
    "healthObjective", "alertPolicy", "actionGroupIds", "createActionGroup", "actionGroupEmails",
    "actionGroupShortName", "assignReaderRoles", "tags",
})
PARAMETERS_SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"


class BicepParameterRenderer:
    """Renders a plan as a deployment parameters document.

    Definition defaults (health objective, alert policy) apply first; deployment options win,
    alert policy keys are merged one by one.
    """

    @staticmethod
    def validate_options(options: dict | None) -> dict:
        options = dict(options or {})
        unknown = set(options) - BICEP_OPTIONS
        if unknown:
            raise ValueError(f"Unsupported Bicep option(s): {sorted(unknown)}")
        if "alertPolicy" in options:
            validate_alert_policy(options["alertPolicy"])
        if "healthObjective" in options:
            validate_health_objective(options["healthObjective"])
        return options

    @classmethod
    def effective_options(cls, plan: ModelPlan, options: dict | None = None) -> dict:
        options = cls.validate_options(options)
        effective = {**plan.defaults, **options}
        if "alertPolicy" in plan.defaults and "alertPolicy" in options:
            effective["alertPolicy"] = {**plan.defaults["alertPolicy"], **options["alertPolicy"]}
        return effective

    @classmethod
    def alert_policy(cls, plan: ModelPlan, options: dict | None = None) -> dict:
        return {**DEFAULT_ALERT_POLICY, **cls.effective_options(plan, options).get("alertPolicy", {})}

    def render(self, plan: ModelPlan, *, location: str, options: dict | None = None) -> dict:
        values = {
            "healthModelName": plan.model_name,
            "location": location,
            "modelScope": plan.model_scope,
            "rootDisplayName": plan.root_display_name,
            "readerResourceGroups": plan.reader_resource_groups,
            "entities": [e.as_parameter() for e in plan.entities],
            "relationships": plan.relationships,
            **self.effective_options(plan, options),
        }
        return {"$schema": PARAMETERS_SCHEMA, "contentVersion": "1.0.0.0",
                "parameters": {key: {"value": value} for key, value in values.items()}}
