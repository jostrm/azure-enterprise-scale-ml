#!/usr/bin/env python3
"""Retry only Logic Apps plan worker exhaustion, without changing deployment inputs."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 120
WRAPPERS = {"deploymentfailed", "resourcedeploymentfailure", "deploymentoperationfailed"}
CAPACITY_PREFIX = "No available instances to satisfy this request."


def error_object(pairs):
    result = {}
    for key, value in pairs:
        key = key.lower()
        if key in result:
            raise ValueError("Duplicate error property.")
        result[key] = value
    return result


def parse_error(text):
    def invalid_constant(_value):
        raise ValueError("Invalid error constant.")
    return json.loads(text, object_pairs_hook=error_object, parse_constant=invalid_constant)


def is_plan_capacity_error(text, subscription):
    """Require only capacity failures on one exact Logic Apps plan in this subscription."""
    plan_ids = set()
    resource_groups = set()

    def visit(node, inherited_target="", depth=0, diagnostic=False):
        if depth > 16 or not isinstance(node, dict) or not node:
            raise ValueError("Missing or malformed deployment error.")
        code = node.get("code")
        if code is not None and (not isinstance(code, str) or code.lower() not in WRAPPERS | {"conflict"}):
            raise ValueError("Noncapacity error.")
        code = (code or "").lower()
        target = node.get("target") or inherited_target
        if target:
            if not isinstance(target, str):
                raise ValueError("Malformed error target.")
            target = target.lower()
            scope = re.fullmatch(
                r"/subscriptions/([^/]+)(?:/resourcegroups/([^/]+))?"
                r"/providers/([^/]+/[^/]+)/([^/]+)", target,
            )
            if not scope or scope[1] != subscription.lower():
                raise ValueError("Error is outside the deployment subscription.")
            if scope[2]:
                resource_groups.add(scope[2])
            if scope[3] == "microsoft.web/serverfarms" and scope[4] == "appfarm-logicapp01" and scope[2]:
                plan_ids.add(target)
            elif scope[3] != "microsoft.resources/deployments":
                raise ValueError("Error is not from the Logic Apps plan.")
        if node.get("extendedcode") not in (None, "03029"):
            raise ValueError("Different App Service error.")
        proofs = []
        for key in ("error", "innererror", "errorentity"):
            if node.get(key) is not None:
                proofs.append(visit(node[key], target, depth + 1, diagnostic))
        if node.get("details") is not None:
            if not isinstance(node["details"], list):
                raise ValueError("Malformed error details.")
            proofs.extend(visit(child, target, depth + 1, diagnostic)
                          for child in node["details"])
        message = node.get("message")
        if message is not None:
            if not isinstance(message, str):
                raise ValueError("Malformed error message.")
            if message.lstrip().startswith("{"):
                proofs.append(visit(parse_error(message), target, depth + 1, True))
            elif code not in WRAPPERS:
                if (message.startswith(CAPACITY_PREFIX)
                        and "App Service is attempting to increase capacity." in message
                        and target in plan_ids):
                    proofs.append(True)
                else:
                    raise ValueError("Conflict does not establish worker exhaustion.")
        if not proofs and not (diagnostic and code == "conflict" and set(node) <= {"code"}):
            raise ValueError("Unresolved error without capacity evidence.")
        return any(proofs)

    try:
        payload = parse_error(re.sub(r"^ERROR:\s*", "", text.strip()))
        return visit(payload) and len(plan_ids) == 1 and len(resource_groups) == 1
    except (ValueError, TypeError, RecursionError):
        return False


def command_inputs(command):
    if command[:4] != ["az", "deployment", "sub", "create"]:
        raise ValueError("Only the existing subscription integration deployment can be retried.")
    if any(value in command for value in ("--no-wait", "--confirm-with-what-if", "--what-if")):
        raise ValueError("Integration retries require a synchronous deployment.")

    def option(name):
        if command.count(name) != 1:
            raise ValueError(f"Exactly one {name} is required.")
        position = command.index(name) + 1
        if position >= len(command) or not command[position] or command[position].startswith("-"):
            raise ValueError(f"A value for {name} is required.")
        return command[position]

    subscription = option("--subscription")
    option("--name")
    option("--location")
    template = Path(option("--template-file"))
    if template.name != "11-integration.bicep":
        raise ValueError("Only 11-integration.bicep uses this retry policy.")
    files = [template]
    for index, value in enumerate(command):
        if value == "--parameters":
            if index + 1 >= len(command):
                raise ValueError("Missing deployment parameters.")
            argument = command[index + 1]
            if argument.startswith("@"):
                files.append(Path(argument[1:]))
    return subscription, {path: hashlib.sha256(path.read_bytes()).digest() for path in files}


def prepared_invocation(command, executable, template, directory):
    """Keep JSON, secrets and shell metacharacters out of the Windows az.cmd argv."""
    values = {}
    invocation = [executable]
    index = 1
    compiled_path = directory / "template.json"
    parameter_path = directory / "parameters.json"
    while index < len(command):
        argument = command[index]
        if argument == "--template-file":
            invocation.extend((argument, str(compiled_path)))
            index += 2
        elif argument == "--parameters":
            argument = command[index + 1]
            if argument.startswith("@"):
                source = json.loads(Path(argument[1:]).read_text(encoding="utf-8-sig"))
                if not isinstance(source, dict):
                    raise ValueError("Deployment parameter file must contain an object.")
                parameters = source.get("parameters", source)
                if not isinstance(parameters, dict):
                    raise ValueError("Deployment parameter file must contain an object.")
                values.update(parameters)
            else:
                name, separator, value = argument.partition("=")
                if not separator or name not in template["parameters"]:
                    raise ValueError("Invalid or unknown integration parameter.")
                kind = template["parameters"][name]["type"].lower()
                if kind == "bool":
                    if value.lower() not in ("true", "false"):
                        raise ValueError(f"Parameter {name} must be boolean.")
                    value = value.lower() == "true"
                elif kind == "int":
                    value = int(value)
                elif kind in ("object", "array", "secureobject"):
                    value = json.loads(value)
                    expected = list if kind == "array" else dict
                    if not isinstance(value, expected):
                        raise ValueError(f"Parameter {name} has the wrong JSON type.")
                elif kind not in ("string", "securestring"):
                    raise ValueError(f"Unsupported type for parameter {name}.")
                values[name] = {"value": value}
            index += 2
        else:
            invocation.append(argument)
            index += 1
    compiled_path.write_text(json.dumps(template), encoding="utf-8")
    parameter_path.write_text(json.dumps({"parameters": values}), encoding="utf-8")
    return [*invocation, "--parameters", "@" + str(parameter_path)]


def deploy(invocation, subscription, inputs):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if any(hashlib.sha256(path.read_bytes()).digest() != digest for path, digest in inputs.items()):
            raise ValueError("Integration inputs changed during capacity recovery; no further deployment attempted.")
        print(f"Integration deployment attempt {attempt}/{MAX_ATTEMPTS}; same resource group, region and SKU.", flush=True)
        result = subprocess.run(invocation, capture_output=True, text=True, check=False)
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
        if result.returncode == 0:
            return 0
        responses = [text for text in (result.stdout, result.stderr) if text.strip()]
        if not responses or not all(is_plan_capacity_error(text, subscription) for text in responses):
            print("Integration failed with a noncapacity, mixed or unrecognized error; no retry.", file=sys.stderr)
            return result.returncode
        if attempt == MAX_ATTEMPTS:
            print("Logic Apps hosting capacity is still unavailable. No resource group, region or SKU was changed. "
                  "Retry later or request App Service capacity assistance for this existing resource group.",
                  file=sys.stderr)
            return result.returncode
        print(f"Logic Apps plan worker capacity unavailable; retrying identical deployment in {RETRY_DELAY_SECONDS}s.",
              flush=True)
        time.sleep(RETRY_DELAY_SECONDS)
    raise AssertionError("Unreachable retry state.")


def run(command):
    subscription, inputs = command_inputs(command)
    executable = shutil.which("az")
    if executable is None:
        raise ValueError("Azure CLI is required for integration deployment.")
    build = subprocess.run(
        [executable, "bicep", "build", "--file", command[command.index("--template-file") + 1],
         "--stdout", "--only-show-errors"], capture_output=True, text=True, check=False,
    )
    if build.stderr:
        print(build.stderr, end="", file=sys.stderr, flush=True)
    if build.returncode:
        return build.returncode
    template = json.loads(build.stdout)
    if not isinstance(template, dict) or not isinstance(template.get("parameters"), dict):
        raise ValueError("Bicep compilation did not return a valid parameter schema.")
    with tempfile.TemporaryDirectory(prefix=".aif-integration-", dir=Path.cwd()) as temporary:
        invocation = prepared_invocation(command, executable, template, Path(temporary))
        return deploy(invocation, subscription, inputs)


if __name__ == "__main__":
    try:
        if sys.argv[1:2] != ["--"]:
            raise ValueError("Usage: deploy-integration-with-retry.py -- az deployment sub create ...")
        sys.exit(run(sys.argv[2:]))
    except (OSError, ValueError) as error:
        print(f"Integration deployment blocked: {error}", file=sys.stderr)
        sys.exit(1)
