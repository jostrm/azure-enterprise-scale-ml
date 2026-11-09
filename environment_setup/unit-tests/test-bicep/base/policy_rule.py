"""Offline evaluator for the Azure Policy rule subset used by the AI Factory's custom policies.

It answers "would this policy deny a resource of type T in location L?" from the policy JSON itself,
so tests check the real rule instead of a restatement. Supported: allOf, anyOf, not, and `field`
conditions with equals, notEquals, in, notIn (case-insensitive, as Azure Policy compares strings),
plus `[parameters('name')]` references and the Indexed/All modes.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_PARAMETER = re.compile(r"^\[parameters\('([^']+)'\)\]$")
RESOURCE_GROUP_TYPE = "microsoft.resources/subscriptions/resourcegroups"
SUBSCRIPTION_TYPE = "microsoft.resources/subscriptions"


def resolve(value: Any, parameters: Mapping[str, Any]) -> Any:
    """Replace a whole-string `[parameters('x')]` reference with the parameter's value."""
    if isinstance(value, str):
        match = _PARAMETER.match(value)
        if match:
            return parameters[match.group(1)]
    return value


def _fold(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, list):
        return [_fold(item) for item in value]
    return value


def evaluate(condition: Mapping[str, Any], resource: Mapping[str, Any], parameters: Mapping[str, Any]) -> bool:
    if "allOf" in condition:
        return all(evaluate(item, resource, parameters) for item in condition["allOf"])
    if "anyOf" in condition:
        return any(evaluate(item, resource, parameters) for item in condition["anyOf"])
    if "not" in condition:
        return not evaluate(condition["not"], resource, parameters)
    actual = _fold(resource.get(condition["field"]))
    for operator in ("equals", "notEquals", "in", "notIn"):
        if operator in condition:
            expected = _fold(resolve(condition[operator], parameters))
            if operator == "equals":
                return actual == expected
            if operator == "notEquals":
                return actual != expected
            if operator == "in":
                return actual in expected
            return actual not in expected
    raise ValueError(f"Unsupported policy condition: {condition}")


def definition_parameters(definition: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    """Definition defaults overlaid with the values an assignment or policy set passes in."""
    declared = definition["properties"].get("parameters", {})
    merged = {name: spec["defaultValue"] for name, spec in declared.items() if "defaultValue" in spec}
    merged.update(values)
    return merged


def applies(definition: Mapping[str, Any], resource_type: str) -> bool:
    """Indexed mode skips resource groups and subscriptions; All mode evaluates them."""
    mode = definition["properties"].get("mode", "Indexed").lower()
    return mode == "all" or resource_type.lower() not in (RESOURCE_GROUP_TYPE, SUBSCRIPTION_TYPE)


def is_denied(definition: Mapping[str, Any], resource: Mapping[str, Any], values: Mapping[str, Any]) -> bool:
    if not applies(definition, resource["type"]):
        return False
    parameters = definition_parameters(definition, values)
    rule = definition["properties"]["policyRule"]
    if not evaluate(rule["if"], resource, parameters):
        return False
    return str(resolve(rule["then"]["effect"], parameters)).lower() == "deny"
