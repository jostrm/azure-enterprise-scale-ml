"""Pure ARM reference transport; never requests, receives or decrypts a secret."""

import copy
import re
from urllib.parse import urlsplit
from uuid import UUID


CONTRACT = "arm-keyvault-reference-v1"
VAULT = re.compile(
    r"/subscriptions/([a-f0-9-]{36})/resourceGroups/[A-Za-z0-9_.()-]{1,90}"
    r"/providers/Microsoft.KeyVault/vaults/[a-z][a-z0-9-]{1,22}[a-z0-9]", re.I)


class ReferenceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise ReferenceError(code)


def is_reference(value):
    return isinstance(value, dict) and set(value) == {"reference"}


def validate_reference(value):
    require(is_reference(value), "arm-keyvault-reference-required")
    reference = value["reference"]
    require(isinstance(reference, dict) and {"keyVault", "secretName"} <= set(reference)
            and set(reference) <= {"keyVault", "secretName", "secretVersion"}, "arm-keyvault-reference-required")
    vault = reference["keyVault"]
    require(isinstance(vault, dict) and set(vault) == {"id"} and isinstance(vault["id"], str),
            "arm-keyvault-resource-id-required")
    match = VAULT.fullmatch(vault["id"])
    require(match is not None, "arm-keyvault-resource-id-required")
    try:
        require(UUID(match[1]).int != 0, "arm-keyvault-subscription-required")
    except ValueError:
        raise ReferenceError("arm-keyvault-subscription-required") from None
    require(isinstance(reference["secretName"], str)
            and re.fullmatch(r"[A-Za-z0-9-]{1,127}", reference["secretName"]), "literal-keyvault-secret-name-required")
    require("secretVersion" not in reference or isinstance(reference["secretVersion"], str)
            and re.fullmatch(r"[a-fA-F0-9]{32}", reference["secretVersion"]), "keyvault-secret-version-invalid")
    return copy.deepcopy(value)


def from_secret_id(name, variables, environment):
    """Use existing credential-free SecretId and seeding-vault coordinates."""
    identifiers = [variables[key] for key in (name + "SecretId", name + "_secret_id") if variables.get(key)]
    if not identifiers:
        return None
    require(all(isinstance(value, str) for value in identifiers) and len(set(identifiers)) == 1,
            "unique-secret-id-required")
    parsed = urlsplit(identifiers[0])
    require(parsed.scheme == "https" and not parsed.username and not parsed.password and not parsed.query
            and not parsed.fragment and parsed.port in (None, 443)
            and re.fullmatch(r"[a-z0-9-]+\.vault\.azure\.net", parsed.hostname or ""),
            "public-azure-keyvault-secret-id-required")
    match = re.fullmatch(r"/secrets/([A-Za-z0-9-]{1,127})(?:/([a-fA-F0-9]{32}))?", parsed.path)
    require(match is not None, "keyvault-secret-id-invalid")
    prefix = "test" if environment == "stage" else environment
    vault = variables.get("inputKeyvault") or variables.get(prefix + "_admin_bicep_kv_fw")
    group = variables.get("inputKeyvaultResourcegroup") or variables.get(prefix + "_admin_bicep_kv_fw_rg")
    subscription = variables.get("inputKeyvaultSubscription") or variables.get(
        prefix + "_admin_bicep_input_keyvault_subscription")
    require(all(isinstance(value, str) and value for value in (vault, group, subscription)),
            "explicit-seeding-vault-coordinates-required")
    require(parsed.hostname.split(".", 1)[0].lower() == vault.lower(), "secret-id-seeding-vault-mismatch")
    return validate_reference({"reference": {
        "keyVault": {"id": "/subscriptions/" + subscription + "/resourceGroups/" + group
                    + "/providers/Microsoft.KeyVault/vaults/" + vault},
        "secretName": match[1], **({"secretVersion": match[2]} if match[2] else {})}})


def _secure_type(template, name):
    definition = template["parameters"][name]
    seen = set()
    while "$ref" in definition:
        reference = definition["$ref"]
        require(isinstance(reference, str) and reference.startswith("#/definitions/")
                and reference not in seen, "secure-parameter-definition-required")
        seen.add(reference)
        name = reference.removeprefix("#/definitions/")
        require(name in template.get("definitions", {}), "secure-parameter-definition-required")
        definition = {**template["definitions"][name],
                      **{key: value for key, value in definition.items() if key != "$ref"}}
    kind = str(definition.get("type", "")).lower()
    require(kind in ("securestring", "secureobject"), "keyvault-reference-requires-secure-parameter")
    return "secureString" if kind == "securestring" else "secureObject"


def encode_step_payload(payload):
    """Replace only typed secure-parameter reference wrappers, leaving literals alone."""
    result = copy.deepcopy(payload)
    properties = result["properties"]
    for name, binding in list(properties["parameters"].items()):
        if isinstance(binding, dict) and set(binding) == {"value"} and is_reference(binding["value"]):
            _secure_type(properties["template"], name)
            properties["parameters"][name] = validate_reference(binding["value"])
    return result


def lift_combined_payload(payload):
    """ARM references must be top-level parameters, never values in a secureObject."""
    result = copy.deepcopy(payload)
    properties, outer = result["properties"], result["properties"]["template"]
    for index, nested in enumerate(outer["resources"]):
        group_name = "step_" + str(index)
        group = properties["parameters"][group_name]["value"]
        for name, value in list(group.items()):
            if not is_reference(value):
                continue
            require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name), "literal-secure-parameter-name-required")
            inner = nested["properties"]
            require("template" in inner, "keyvault-template-link-unsupported")
            kind = _secure_type(inner["template"], name)
            require(inner["parameters"][name] == {"value": "[parameters('" + group_name + "')['" + name + "']]"},
                    "secure-parameter-forwarding-mismatch")
            lifted = "aif_kv_" + str(index) + "_" + name
            require(lifted not in outer["parameters"] and lifted not in properties["parameters"],
                    "secure-parameter-name-collision")
            outer["parameters"][lifted] = {"type": kind}
            properties["parameters"][lifted] = validate_reference(value)
            inner["parameters"][name] = {"value": "[parameters('" + lifted + "')]"}
            del group[name]
    return result
