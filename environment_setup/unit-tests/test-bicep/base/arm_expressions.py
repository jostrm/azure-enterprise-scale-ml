"""Base layer: evaluate compiled ARM template expressions offline.

Tests compile Bicep, then evaluate the emitted ``[...]`` expressions with concrete
parameters to assert what ARM would deploy, without Azure. Only the functions these
tests need are implemented; an unknown function raises KeyError so a gap shows up
instead of a silently wrong value. ``if`` evaluates only the chosen branch, as ARM does.
``guid()`` returns ``guid(<seed>)`` instead of ARM's hash: equal seeds mean equal names.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import subprocess


@lru_cache
def compile_bicep(path: Path) -> dict:
    """``bicep build`` one file and return the ARM template."""
    compiler = shutil.which("bicep")
    assert compiler, "Bicep CLI required"
    result = subprocess.run([compiler, "build", str(path), "--stdout", "--no-restore"],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def arm_value(expression, parameters, template, context=None, scope=None):
    """Evaluate one ARM expression; plain values pass through unchanged.

    ``context`` supplies deployment functions such as ``resourceGroup`` or ``copyIndex``.
    """
    if not isinstance(expression, str) or not expression.startswith("["):
        return expression
    source = re.sub(r"\b(and|or|not|if|lambda)\(", lambda match: match[1].upper() + "(", _python_source(expression[1:-1]))
    return _visit(ast.parse(source, mode="eval").body, parameters, template, context or {}, scope or {})


def _python_source(expression: str) -> str:
    """ARM string literals in Python syntax: '' is an escaped quote and a backslash is just a character."""
    out, quoted, index = [], False, 0
    while index < len(expression):
        char = expression[index]
        if char == "\\":
            out.append("\\\\")
        elif char == "'" and quoted and expression[index + 1:index + 2] == "'":
            out.append("\\'")
            index += 1
        else:
            quoted ^= char == "'"
            out.append(char)
        index += 1
    return "".join(out)


def _index(container, key):
    if isinstance(key, int) and key < 0:
        raise IndexError(f"ARM has no negative index: {key}")
    return container[key]


def _format(text, *args):
    return re.sub(r"\{(\d+)\}", lambda match: str(args[int(match[1])]), text)


def _visit(node, parameters, template, context, scope):
    def value(child):
        return _visit(child, parameters, template, context, scope)

    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Subscript):
        return _index(value(node.value), value(node.slice))
    if isinstance(node, ast.Attribute):
        return value(node.value)[node.attr]
    assert isinstance(node, ast.Call) and not node.keywords, ast.dump(node)
    if isinstance(node.func, ast.Attribute):
        member = next(group for group in template["functions"]
                      if group["namespace"] == node.func.value.id)["members"][node.func.attr]
        args = {key["name"]: value(arg) for key, arg in zip(member["parameters"], node.args)}
        return arm_value(member["output"]["value"], args, template, context)
    name = node.func.id
    if name == "LAMBDA":
        names = [value(arg) for arg in node.args[:-1]]
        return lambda *items: _visit(node.args[-1], parameters, template, context,
                                     {**scope, **dict(zip(names, items))})
    if name == "IF":
        return value(node.args[1] if value(node.args[0]) else node.args[2])
    values = [value(arg) for arg in node.args]
    if name == "fail":
        raise ValueError(values[0])
    functions = {
        "parameters": parameters.__getitem__,
        "variables": lambda key: arm_value(template["variables"][key], parameters, template, context),
        "lambdaVariables": scope.__getitem__,
        "AND": lambda *args: all(args), "OR": lambda *args: any(args), "NOT": lambda item: not item,
        "true": lambda: True, "false": lambda: False, "null": lambda: None,
        "empty": lambda item: not item, "equals": lambda a, b: a == b,
        "less": lambda a, b: a < b, "lessOrEquals": lambda a, b: a <= b,
        "greater": lambda a, b: a > b, "greaterOrEquals": lambda a, b: a >= b,
        "length": len, "toLower": str.lower, "trim": str.strip, "contains": lambda container, item: item in container,
        "map": lambda items, mapper: [mapper(item) for item in items],
        "replace": str.replace, "split": lambda text, separator: text.split(separator),
        "take": lambda item, count: item[:max(count, 0)], "skip": lambda item, count: item[max(count, 0):],
        "array": lambda item: item if isinstance(item, list) else [item],
        "createArray": lambda *items: list(items),
        "createObject": lambda *args: dict(zip(args[::2], args[1::2])),
        "union": lambda *arrays: list(dict.fromkeys(item for array in arrays for item in array)),
        "filter": lambda items, predicate: [item for item in items if predicate(item)],
        "range": lambda start, count: list(range(start, start + count)),
        "substring": lambda text, start, length: text[start:start + length],
        "format": _format,
        "guid": lambda *parts: f"guid({'|'.join(parts)})",
        **context,
    }
    return functions[name](*values)


def resources(template: dict) -> list[dict]:
    """Top-level resources, whether the template uses symbolic names or a list."""
    items = template["resources"]
    return list(items.values()) if isinstance(items, dict) else items


def parameters_with_defaults(template: dict, values: dict, context=None) -> dict:
    """``values`` plus the template's default for every parameter they leave out."""
    merged = dict(values)
    for key, declared in template.get("parameters", {}).items():
        if key not in merged and "defaultValue" in declared:
            merged[key] = arm_value(declared["defaultValue"], merged, template, context)
    return merged


def nested_parameters(deployment: dict, parameters: dict, template: dict, context=None) -> dict:
    """Parameter values a Microsoft.Resources/deployments module passes to its inline template."""
    passed = {key: arm_value(item, parameters, template, context)["value"] if isinstance(item, str)
              else arm_value(item["value"], parameters, template, context)
              for key, item in deployment["properties"]["parameters"].items()}
    return parameters_with_defaults(deployment["properties"]["template"], passed, context)


def copy_loop(resource: dict, parameters: dict, template: dict, properties=(), context=None) -> list[dict]:
    """Expand a resource copy loop the way ARM does: per instance, its name and the named properties."""
    context = context or {}
    if "condition" in resource and not arm_value(resource["condition"], parameters, template, context):
        return []
    count = arm_value(resource["copy"]["count"], parameters, template, context)
    instances = []
    for index in range(count):
        local = {**context, "copyIndex": lambda *_, index=index: index}
        instances.append({"name": arm_value(resource["name"], parameters, template, local),
                          **{key: arm_value(resource["properties"][key], parameters, template, local)
                             for key in properties}})
    return instances
