"""Pure translation of canonical variables to existing compiled ARM parameters.

No template, API configuration model, secret store, or deployment engine lives
here. Unresolved expressions and literal credentials stop preparation; secure
parameters may use ARM Key Vault references; an explicit secret version is optional.
"""

import copy
from datetime import datetime
import json
import re

from pipeline_lifecycle import require, PipelineError
from pipeline_lifecycle_keyvault import from_secret_id, is_reference, validate_reference


ALIASES = {
    "locationSuffix": "admin_locationSuffix", "commonResourceSuffix": "admin_commonResourceSuffix",
    "containerRegistrySkuName": "acr_SKU", "technicalAdminsObjectID": "technical_admins_ad_object_id",
    "technicalAdminsEmail": "technical_admins_email", "vnetNameBase": "vnet_name_base",
    "common_subnet_name": "subnet_common_base", "resourceSuffix": "admin_prjResourceSuffix",
    "randomValue": "deployment_random_value",
    "projectServicePrincipleOID_SeedingKeyvaultName": "project_service_principal_OID_seeding_kv_name",
    "projectServicePrincipleAppID_SeedingKeyvaultName": "project_service_principal_AppID_seeding_kv_name",
    "projectServicePrincipleSecret_SeedingKeyvaultName": "project_service_principal_Secret_seeding_kv_name",
}


def expand(value, variables, stack=()):
    if isinstance(value, dict):
        return {key: expand(item, variables, stack) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, variables, stack) for item in value]
    if not isinstance(value, str):
        return copy.deepcopy(value)

    def replace(match):
        name = match[1]
        require(name not in stack and name in variables, "unresolved-parameter-variable:" + name)
        item = expand(variables[name], variables, (*stack, name))
        return json.dumps(item) if isinstance(item, (dict, list, bool)) else str(item)

    result = re.sub(r"\$\(([A-Za-z0-9_.-]+)\)", replace, value)
    require(not any(marker in result.lower() for marker in ("<todo>", "$(", "${{"))
            and not re.match(r"^\[[A-Za-z][A-Za-z0-9]*\(", result), "unresolved-arm-parameter")
    return result


def definition(value, definitions):
    seen = set()
    while "$ref" in value:
        ref = value["$ref"]
        require(isinstance(ref, str) and ref.startswith("#/definitions/") and ref not in seen,
                "unsupported-arm-parameter-reference")
        seen.add(ref)
        name = ref.removeprefix("#/definitions/")
        require(name in definitions, "missing-arm-parameter-definition")
        value = {**definitions[name], **{key: item for key, item in value.items() if key != "$ref"}}
    return value


def parameters(template, variables, target, *, project=None, prepared_at=None):
    schema, definitions = template["parameters"], template.get("definitions", {})
    env = "test" if target["environment"] == "stage" else target["environment"]
    required = {"env": env, "location": target["region"], "commonRGNamePrefix": target["prefix"],
                "aifactorySuffixRG": "-" + target["suffix"], "tenantId": target["tenant_id"],
                "subscriptionId": target["subscription_id"], "subscriptionIdDevTestProd": target["subscription_id"]}
    if project:
        required["projectNumber"] = project
    else:
        required["enableAIFactoryCreatedDefaultProjectForAIFv2"] = False
    owners = {"aifactory.factory_id": target["factory_id"], "aifactory.scaleset_id": target["scaleset_id"]}
    if project:
        owners["aifactory.project_id"] = project
    aliases = {**ALIASES, "network_env": "network_env_" + target["environment"]}
    for parameter, name in (("inputKeyvault", "admin_bicep_kv_fw"),
                            ("inputKeyvaultResourcegroup", "admin_bicep_kv_fw_rg"),
                            ("inputKeyvaultSubscription", "admin_bicep_input_keyvault_subscription"),
                            ("cidr_range", "cidr_range")):
        if variables.get(env + "_" + name):
            aliases[parameter] = env + "_" + name
    normalize = lambda name: re.sub(r"[^a-z0-9]", "", name.lower().removeprefix("admin_"))
    result = {}
    for name, raw in schema.items():
        spec = definition(raw, definitions)
        kind = str(spec.get("type", "")).lower()
        if name in ("tags", "tagsProject"):
            value = variables.get(name, spec.get("defaultValue", {}))
        elif name in required:
            value = required[name]
        elif aliases.get(name, name) in variables:
            value = variables[aliases.get(name, name)]
        elif kind.startswith("secure") and (reference := from_secret_id(name, variables, target["environment"])):
            value = reference
        else:
            candidates = [item for key, item in variables.items() if normalize(key) == normalize(name)]
            require(len(candidates) <= 1, "ambiguous-arm-parameter:" + name)
            if candidates:
                value = candidates[0]
            elif "defaultValue" in spec:
                value = spec["defaultValue"]
            elif spec.get("nullable") is True:
                value = None
            else:
                raise PipelineError("resolved-arm-parameter-required:" + name)
        if name in ("tags", "tagsProject"):
            if isinstance(value, str):
                value = json.loads(value)
            require(isinstance(value, dict), "ownership-tags-object-required")
            for key, item in value.items():
                require(key.lower() not in owners or item == owners[key.lower()], "conflicting-ownership-tag")
                require(project or key.lower() not in ("aifactory.project_id", "aifactory.logical_project_id"),
                        "common-project-ownership-forbidden")
            value = {**value, **owners}
        if value == "[not(parameters('enablePublicAccessWithPerimeter'))]":
            public = result.get("enablePublicAccessWithPerimeter", variables.get("enablePublicAccessWithPerimeter"))
            require(str(public).lower() in ("true", "false"), "resolved-public-network-policy-required")
            value = str(public).lower() != "true"
        elif value == "[if(equals(parameters('env'), 'test'), 'stage', parameters('env'))]":
            value = target["environment"]
        elif value == "[dateTimeToEpoch(dateTimeAdd(utcNow(), 'P1Y'))]":
            moment = datetime.fromisoformat(prepared_at)
            try:
                value = int(moment.replace(year=moment.year + 1).timestamp())
            except ValueError:
                value = int(moment.replace(year=moment.year + 1, day=28).timestamp())
        if kind.startswith("secure") and is_reference(value):
            result[name] = validate_reference(value)
            continue
        require(not kind.startswith("secure") or value in ("", None), "secure-parameter-transport-required:" + name)
        value = expand(value, variables)
        if kind == "bool" and isinstance(value, str) and value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif kind == "int" and isinstance(value, str) and re.fullmatch(r"-?\d+", value):
            value = int(value)
        elif kind in ("array", "object") and isinstance(value, str):
            value = expand(json.loads(value), variables)
        types = {"bool": bool, "int": int, "string": str, "securestring": str, "object": dict,
                 "secureobject": dict, "array": list}
        require(kind in types and (value is None and spec.get("nullable") is True or type(value) is types[kind]),
                "arm-parameter-type-mismatch:" + name)
        if "allowedValues" in spec:
            require(value in spec["allowedValues"], "arm-parameter-value-not-allowed:" + name)
        for field, check in (("minValue", lambda bound: value >= bound),
                             ("maxValue", lambda bound: value <= bound),
                             ("minLength", lambda bound: len(value) >= bound),
                             ("maxLength", lambda bound: len(value) <= bound)):
            if field in spec and value is not None:
                require(check(spec[field]), "arm-parameter-constraint:" + name)
        result[name] = value
    return result
