import pytest

from .test_pipeline_lifecycle_adapters import FACTORY, SCALE, SUB, TENANT


def target():
    return {"factory_id": FACTORY, "scaleset_id": SCALE, "environment": "prod", "region": "eastus2",
            "prefix": "acme", "suffix": "003", "subscription_id": SUB, "tenant_id": TENANT}


def test_parameter_resolution_binds_exact_environment_and_ownership():
    from pipeline_lifecycle_parameters import parameters
    template = {"parameters": {"env": {"type": "string"}, "tags": {"type": "object"},
                                "projectNumber": {"type": "string"}, "enabled": {"type": "bool"},
                                "count": {"type": "int"}, "settings": {"type": "object"}}}
    result = parameters(template, {"enabled": "false", "count": "4", "settings": '{"key":"$(name)"}',
                                   "name": "literal"}, target(), project="017")
    assert result == {"env": "prod", "projectNumber": "017", "enabled": False, "count": 4,
                      "settings": {"key": "literal"}, "tags": {
                          "aifactory.factory_id": FACTORY, "aifactory.scaleset_id": SCALE,
                          "aifactory.project_id": "017"}}


@pytest.mark.parametrize("schema,variables,code", [
    ({"missing": {"type": "string"}}, {}, "resolved-arm-parameter-required"),
    ({"password": {"type": "securestring"}}, {"password": "do-not-store"}, "secure-parameter-transport"),
    ({"value": {"type": "string"}}, {"value": "$(a)", "a": "$(value)"}, "unresolved-parameter-variable"),
    ({"value": {"type": "string", "defaultValue": "[uniqueString('x')]"}}, {}, "unresolved-arm-parameter"),
    ({"value": {"type": "bool"}}, {"value": "yes"}, "arm-parameter-type-mismatch"),
    ({"value": {"type": "string", "allowedValues": ["a"]}}, {"value": "b"}, "not-allowed"),
    ({"tags": {"type": "object"}}, {"tags": {"aifactory.factory_id": "other"}}, "conflicting-ownership"),
    ({"tags": {"type": "object"}}, {"tags": {"aifactory.project_id": "017"}}, "common-project-ownership"),
])
def test_unresolved_insecure_or_conflicting_parameters_block(schema, variables, code):
    from pipeline_lifecycle_parameters import parameters
    with pytest.raises(ValueError, match=code):
        parameters({"parameters": schema}, variables, target())


def test_arm_expression_defaults_are_frozen_from_prepare_time_and_resolved_parameters():
    """Live 2026-11-18 (aif-163): 05/08/08b defaults use utcNow() and parameters() and were refused."""
    from pipeline_lifecycle_parameters import parameters
    template = {"parameters": {
        "webappSKUAce": {"type": "object", "defaultValue": {
            "name": "[parameters('aseSkuCode')]", "tier": "[parameters('aseSku')]", "family": "Iv2",
            "capacity": "[parameters('aseSkuWorkers')]"}},
        "aseSkuCode": {"type": "string", "defaultValue": "I1v2"}, "aseSku": {"type": "string"},
        "aseSkuWorkers": {"type": "int", "defaultValue": 1},
        "deploymentId": {"type": "string", "defaultValue": "[utcNow('yyyyMMddHHmmss')]"}}}
    result = parameters(template, {"aseSku": "IsolatedV2"}, target(), prepared_at="2026-11-18T09:08:07+00:00")
    assert result["webappSKUAce"] == {"name": "I1v2", "tier": "IsolatedV2", "family": "Iv2", "capacity": 1}
    assert result["deploymentId"] == "20261118090807"


@pytest.mark.parametrize("default", ["[parameters('absent')]", "[utcNow('yyyy-MM-ddTHH:mm:ssK')]",
                                     "[concat(parameters('a'), 'b')]"])
def test_other_arm_expression_defaults_still_block(default):
    from pipeline_lifecycle_parameters import parameters
    with pytest.raises(ValueError, match="unresolved-arm-parameter"):
        parameters({"parameters": {"a": {"type": "string", "defaultValue": "x"},
                                   "value": {"type": "string", "defaultValue": default}}},
                   {}, target(), prepared_at="2026-11-18T09:08:07+00:00")


def test_every_admin_password_template_parameter_is_secure():
    """A clear-text password parameter cannot travel through the reviewed pipelines-only plan."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[4] / "environment_setup" / "aifactory" / "bicep"
    found = []
    for path in list((root / "esml-genai-1").glob("*.bicep")) + list((root / "esml-common" / "main").glob("*.bicep")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^param adminPassword\s", text):
            before = text[:match.start()].rstrip().splitlines()[-3:]
            found.append((path.name, any(line.strip().startswith("@secure()") for line in before)))
    assert found and all(secure for _, secure in found), found
