"""ARM parameter constraints translated to an offline JSON Schema validator."""

import copy
import math

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError

from src.catalog_storage import CatalogError


TYPES = {"string": "string", "securestring": "string", "object": "object", "secureobject": "object",
         "array": "array", "int": "integer", "bool": "boolean"}
ANNOTATIONS = {"metadata", "defaultValue", "description"}
DIRECT = {"required", "pattern", "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties"}
Validator = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
    "integer", lambda checker, value: type(value) is int))


def arm_definition(definition, definitions, seen=()):
    reference = definition.get("$ref")
    if reference:
        if not isinstance(reference, str) or not reference.startswith("#/definitions/") or reference in seen:
            raise CatalogError("Published parameter schema has an unsupported reference.", 409)
        name = reference.removeprefix("#/definitions/").replace("~1", "/").replace("~0", "~")
        if name not in definitions:
            raise CatalogError("Published parameter schema has an unresolved type reference.", 409)
        return {**arm_definition(definitions[name], definitions, (*seen, reference)),
                **{key: value for key, value in definition.items() if key != "$ref"}}
    return definition


def arm_kind(definition, definitions):
    return str(arm_definition(definition, definitions).get("type", "")).lower()


def _convert(value, definitions):
    if isinstance(value, bool):
        return value
    if not isinstance(value, dict):
        raise CatalogError("Published ARM parameter schema is malformed.", 409)
    result = {}
    description = value.get("metadata", {}).get("description") if isinstance(value.get("metadata"), dict) else None
    if isinstance(description, str):
        result["description"] = description
    kind = arm_kind(value, definitions)
    if kind.startswith("secure"):
        result["writeOnly"] = True
    for key, item in value.items():
        if key in ANNOTATIONS or key == "nullable":
            continue
        if key == "type":
            if str(item).lower() not in TYPES:
                raise CatalogError("Published ARM parameter type is unsupported.", 409)
            result["type"] = TYPES[str(item).lower()]
        elif key == "$ref":
            result[key] = item
        elif key == "allowedValues":
            if kind == "array":
                result.setdefault("allOf", []).append({"items": {"enum": copy.deepcopy(item)}})
            else:
                result["enum"] = copy.deepcopy(item)
        elif key in ("minValue", "maxValue"):
            result["minimum" if key == "minValue" else "maximum"] = item
        elif key in ("minLength", "maxLength"):
            result[key.replace("Length", "Items") if kind == "array" else key] = item
        elif key == "properties":
            result[key] = {name: _convert(child, definitions) for name, child in item.items()}
            if "required" not in value:
                result["required"] = [name for name, child in item.items()
                                      if not arm_definition(child, definitions).get("nullable", False)]
        elif key in ("additionalProperties", "items"):
            result[key] = _convert(item, definitions)
        elif key in ("prefixItems", "allOf", "anyOf", "oneOf"):
            converted = [_convert(child, definitions) for child in item]
            result[key] = result.get(key, []) + converted
            if key == "prefixItems":
                result["minItems"] = max(value.get("minLength", value.get("minItems", 0)), len(item))
        elif key == "discriminator":
            if not isinstance(item, dict) or set(item) != {"propertyName", "mapping"}:
                raise CatalogError("Published discriminator schema is unsupported.", 409)
            result["oneOf"] = []
            for name, child in item["mapping"].items():
                branch = _convert(arm_definition(child, definitions), definitions)
                properties = branch.setdefault("properties", {})
                properties[item["propertyName"]] = {"allOf": [
                    properties.get(item["propertyName"], {}), {"const": name}]}
                branch["required"] = sorted(set(branch.get("required", [])) | {item["propertyName"]})
                result["oneOf"].append(branch)
        elif key in DIRECT:
            result[key] = copy.deepcopy(item)
        else:
            raise CatalogError("Published ARM schema uses unsupported validation keywords; install a compatible parameter adapter.", 409)
    if "prefixItems" in value:
        result["minItems"] = max(result.get("minItems", 0), len(value["prefixItems"]))
    if value.get("nullable") is True:
        return {"anyOf": [result, {"type": "null"}]}
    return result


def parameter_schema(parameters, definitions=None):
    definitions = definitions or {}
    try:
        schema = {"type": "object", "properties": {
            name: _convert(definition, definitions) for name, definition in parameters.items()},
            "additionalProperties": False,
            "definitions": {name: _convert(definition, definitions) for name, definition in definitions.items()}}
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, AttributeError, RecursionError):
        raise CatalogError("The selected published parameter schema cannot be validated safely.", 409) from None
    return schema


def validate_values(schema, values):
    def finite(value):
        if isinstance(value, dict):
            return all(isinstance(key, str) and finite(item) for key, item in value.items())
        if isinstance(value, list):
            return all(finite(item) for item in value)
        return type(value) in (str, int, bool, type(None)) or (type(value) is float and math.isfinite(value))
    try:
        valid = finite(values) and Validator(schema).is_valid(values)
    except RecursionError:
        valid = False
    if not valid:
        # ValidationError includes submitted values (including secrets); never surface it.
        raise CatalogError("Parameter values violate the exact published schema (name, type, nested shape or constraint).", 409)


def sensitive(schema, definitions, seen=()):
    if not isinstance(schema, dict):
        return False
    if schema.get("writeOnly") is True:
        return True
    reference = schema.get("$ref")
    if reference and reference not in seen:
        name = reference.removeprefix("#/definitions/").replace("~1", "/").replace("~0", "~")
        if sensitive(definitions[name], definitions, (*seen, reference)):
            return True
    return (any(sensitive(value, definitions, seen) for value in schema.get("properties", {}).values())
            or any(sensitive(schema.get(key), definitions, seen) for key in ("items", "additionalProperties"))
            or any(sensitive(value, definitions, seen) for key in ("prefixItems", "allOf", "anyOf", "oneOf")
                   for value in schema.get(key, [])))
