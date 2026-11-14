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
